"""Simulation server that wraps the Simulation engine behind a ZeroMQ REP socket.

External TX/RX clients connect, send requests, and receive responses.
The server alternates between polling for requests and ticking the
simulation, so the engine stays responsive.
"""

from __future__ import annotations

import signal
import time
from pathlib import Path
from typing import Any


from ris_sim.core.engine import Simulation
from ris_sim.core.logging import get_logger
from ris_sim.io.transport import ServerTransport, TransportError
from ris_sim.modules import validation as val

_log = get_logger("server")


class SimulationServer:
    """Run a Simulation behind a ZeroMQ REP socket.

    Usage::

        server = SimulationServer.from_scenario_file("scenario.json")
        server.serve()  # blocks until SIGINT/SIGTERM
    """

    def __init__(self, sim: Simulation, bind_addr: str = "tcp://127.0.0.1:5555"):
        self.sim = sim
        self.transport = ServerTransport(bind_addr)
        self._running = False
        self._pending_rx: dict[str, dict[str, Any]] = {}  # request_id → rx_info

    @classmethod
    def from_scenario_file(cls, path: str | Path, *, seed: int | None = None, **kwargs) -> SimulationServer:
        sim = Simulation.from_scenario_file(str(path), seed=seed)
        return cls(sim, **kwargs)

    @classmethod
    def from_scenario(cls, scenario: dict[str, Any], *, seed: int | None = None, **kwargs) -> SimulationServer:
        sim = Simulation.from_scenario(scenario, seed=seed)
        return cls(sim, **kwargs)

    # ── main loop ───────────────────────────────────────────────────

    def serve(self) -> None:
        """Blocking main loop. Exits on SIGINT/SIGTERM or when no nodes are active and no
        pending requests remain."""
        self._running = True
        _log.info("server_listening", addr=self.transport.bind_addr, nodes=len(self.sim.nodes), ris=len(self.sim.ris_controllers))

        try:
            signal.signal(signal.SIGINT, self._handle_shutdown)
            signal.signal(signal.SIGTERM, self._handle_shutdown)
        except (ValueError, OSError):
            pass  # not in main thread — signals unavailable

        poll_interval_ms = 1  # check for requests every 1ms

        try:
            while self._running:
                # 1. Process any incoming requests
                self._process_requests(poll_interval_ms)

                # 2. Tick the simulation if there are active nodes OR pending requests
                if not self.sim._all_idle() or self._has_pending_node_requests():
                    self.sim.tick()

                    # 3. Check for completed RX requests after the tick
                    self._check_rx_completions()
                else:
                    # No active nodes and no pending requests — small sleep
                    time.sleep(0.001)

        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Clean shutdown."""
        self._running = False
        self.transport.close()
        elapsed = self.sim.elapsed or (time.time() - (self.sim.start_time or time.time()))
        _log.info("server_stopped", ticks=self.sim.counter, elapsed_s=f"{elapsed:.3f}")

    def _handle_shutdown(self, signum, frame) -> None:
        _log.info("shutdown_requested", signal=signum)
        self._running = False

    def _has_pending_node_requests(self) -> bool:
        """True if any node has a queued request waiting to be assigned."""
        return any(node.request for node in self.sim.nodes)

    # ── request handling ────────────────────────────────────────────

    def _process_requests(self, poll_ms: int) -> bool:
        """Check for incoming ZeroMQ requests and dispatch them.

        Returns True if a request was processed (so the caller knows to tick).
        """
        request = self.transport.poll(poll_ms)
        if request is None:
            return False

        cmd = request.get("cmd", "")
        try:
            if cmd == "tx":
                self._handle_tx(request)
            elif cmd == "rx":
                self._handle_rx(request)
            elif cmd == "ris_config":
                self._handle_ris_config(request)
            elif cmd == "status":
                self._handle_status()
            elif cmd == "health":
                self._handle_health()
            elif cmd == "stop":
                self._handle_stop()
            else:
                self.transport.send_response(
                    {"status": "error", "message": f"Unknown command: {cmd!r}"}
                )
        except Exception as exc:
            self.transport.send_response(
                {"status": "error", "message": str(exc)}
            )
        return True

    def _handle_tx(self, request: dict[str, Any]) -> None:
        node_id = request["node_id"]
        data = request["data"]
        fc = float(request["fc"])
        sample_rate = float(request["sample_rate"])
        tau = float(request.get("tau", self.sim.tau))

        # Convert incoming data to the format the engine expects
        if isinstance(data, list):
            streams = val.normalize_transmit_data(data)
        else:
            raise TransportError("TX data must be a list of [I, Q] pairs.")

        val.validate_transmit_request(sample_rate, streams, tau=tau)
        request_id = self.sim.queue_tx(node_id, data, fc, sample_rate, tau=tau)
        self.transport.send_response({"status": "ok", "request_id": request_id})

    def _handle_rx(self, request: dict[str, Any]) -> None:
        node_id = request["node_id"]
        num_samps = int(request["num_samps"])
        fc = float(request["fc"])
        sample_rate = float(request["sample_rate"])
        tau = float(request.get("tau", self.sim.tau))
        timeout = float(request.get("timeout", 30.0))

        val.validate_receive_request(sample_rate, num_samps, tau=tau)
        request_id = self.sim.queue_rx(node_id, num_samps, fc, sample_rate, tau=tau)

        # Block the REP socket until RX completes, ticking the simulation as needed
        self._block_until_rx_complete(request_id, timeout)

    def _block_until_rx_complete(self, request_id: str, timeout_s: float) -> None:
        """Tick the simulation until the RX request completes or timeout."""
        deadline = time.time() + timeout_s

        while time.time() < deadline:
            # Always tick — _assign_requests picks up pending requests
            self.sim.tick()

            # Check if our RX has completed
            entry = self.sim.output.find_entry(request_id)
            if entry is not None:
                rx_node = None
                for node in self.sim.nodes:
                    if node.request_id == request_id:
                        rx_node = node
                        break
                if rx_node is None or rx_node.is_idle:
                    samples = entry.flatten_iq()
                    self.transport.send_response({
                        "status": "ok",
                        "request_id": request_id,
                        "num_samples": int(len(samples)),
                        "data": [[float(v.real), float(v.imag)] for v in samples],
                    })
                    return

            time.sleep(0.001)

        # Timeout
        self.transport.send_response({
            "status": "error",
            "message": f"RX request {request_id} timed out after {timeout_s}s",
        })

    def _handle_ris_config(self, request: dict[str, Any]) -> None:
        """Update a RIS panel configuration. Takes effect next tick."""
        ris_id = str(request["ris_id"])
        matrix = request["matrix"]
        self.sim.ris_set_config(ris_id, matrix)
        self.transport.send_response({
            "status": "ok",
            "message": f"RIS {ris_id!r} config queued for next tick.",
        })

    def _handle_status(self) -> None:
        nodes_info = []
        for node in self.sim.nodes:
            nodes_info.append({
                "id": node.id,
                "mode": node.current_mode,
                "location": node.location,
            })
        uptime = time.time() - (self.sim.metrics.start_time or time.time())
        self.transport.send_response({
            "status": "ok",
            "healthy": True,
            "uptime_s": round(uptime, 3),
            "tick": self.sim.counter,
            "nodes": nodes_info,
            "ris_count": len(self.sim.ris_controllers),
            "metrics": {
                "avg_tick_us": round(self.sim.metrics.avg_tick_us, 1),
                "max_tick_us": round(self.sim.metrics.max_tick_us, 1),
                "iq_samples_processed": self.sim.metrics.total_iq_samples_processed,
            },
        })

    def _handle_health(self) -> None:
        """Lightweight health check — no metrics, just alive + node states."""
        self.transport.send_response({
            "status": "ok",
            "healthy": True,
            "uptime_s": round(time.time() - (self.sim.metrics.start_time or time.time()), 3),
            "tick": self.sim.counter,
            "active_nodes": sum(1 for n in self.sim.nodes if not n.is_idle),
            "total_nodes": len(self.sim.nodes),
        })

    def _handle_stop(self) -> None:
        self._running = False
        self.transport.send_response({"status": "ok", "message": "Server stopping."})

    # ── RX completion callback ──────────────────────────────────────

    def _check_rx_completions(self) -> None:
        """Called after each tick to detect RX nodes that just finished.

        In the server mode, RX completions are handled via _block_until_rx_complete,
        so this is a no-op for the REP-socket model. If we add PUB/SUB event
        notifications later, this is where they'd be emitted.
        """
        pass
