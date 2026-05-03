"""Dashboard session — coordinates Simulation tick loop with WebSocket push."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from ris_sim.core.engine import Simulation
from ris_sim.core.logging import get_logger

_log = get_logger("dashboard")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
PUSH_INTERVAL_S = 0.05  # 50ms = 20 Hz max push rate


def list_templates() -> list[str]:
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(
        p.stem for p in TEMPLATES_DIR.glob("*.json")
    )


def load_template(name: str) -> dict[str, Any] | None:
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_template(name: str, scenario: dict[str, Any]) -> None:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMPLATES_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(scenario, f, indent=2)


def validate_scenario(scenario: dict[str, Any]) -> list[str]:
    errors = []
    try:
        from ris_sim.modules import validation as val
        room_data = {"room": dict(scenario["room"])}
        nodes_data = {"nodes": [{"id": n["id"], "location": list(n["location"]),
                                  "mobility": dict(n.get("mobility", {"type": "static"}))}
                                 for n in scenario.get("nodes", [])]}
        ris_data = {"ris": scenario.get("ris", [])}
        val.validate_startup_configs(room_data=room_data, ris_data=ris_data, nodes_data=nodes_data)
    except Exception as e:
        errors.append(str(e))
    return errors


class DashboardSession:
    def __init__(self):
        self.sim: Simulation | None = None
        self._running = False
        self._paused = False
        self._last_push = 0.0
        self._task: asyncio.Task | None = None

    async def start(self, scenario: dict[str, Any], websocket) -> None:
        self.sim = Simulation.from_scenario(scenario)
        self._running = True
        self._paused = False
        self._last_push = time.time()

        # Validate traffic node_ids match scenario nodes
        node_ids = {n["id"] for n in scenario.get("nodes", [])}
        for traffic in scenario.get("traffic", []):
            nid = traffic.get("node_id", "")
            if nid not in node_ids:
                raise ValueError(
                    f"Traffic references node_id {nid!r} which is not in the topology. "
                    f"Available nodes: {sorted(node_ids)}. "
                    f"Select a signal template that matches your topology."
                )

        # Queue traffic from scenario
        for traffic in scenario.get("traffic", []):
            node_id = traffic["node_id"]
            mode = traffic["mode"]
            if mode == "transmit":
                wf = traffic.get("waveform", {})
                iq_data = _waveform_to_iq(wf)
                self.sim.queue_tx(
                    node_id, iq_data,
                    fc=float(traffic["fc"]),
                    sample_rate=float(traffic["sample_rate"]),
                    tau=float(traffic.get("tau", self.sim.tau)),
                )
            elif mode == "receive":
                self.sim.queue_rx(
                    node_id,
                    num_samps=int(traffic["num_samps"]),
                    fc=float(traffic["fc"]),
                    sample_rate=float(traffic["sample_rate"]),
                    tau=float(traffic.get("tau", self.sim.tau)),
                )

        self._task = asyncio.create_task(self._run_loop(websocket))

        # Push initial state immediately so topology renders
        await self._send_state(websocket)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def pause(self) -> None:
        self._paused = True

    async def resume(self) -> None:
        self._paused = False

    async def step(self, websocket) -> None:
        if self.sim:
            self.sim.tick()
            await self._send_state(websocket)

    def _has_pending_requests(self) -> bool:
        if not self.sim:
            return False
        return any(node.request for node in self.sim.nodes)

    async def _run_loop(self, ws) -> None:
        try:
            while self._running and self.sim:
                active = not self.sim._all_idle() or self._has_pending_requests()
                if not active:
                    # All done — send final state and exit
                    break

                if not self._paused:
                    self.sim.tick()

                    now = time.time()
                    if now - self._last_push >= PUSH_INTERVAL_S:
                        await self._send_state(ws)
                        self._last_push = now

                await asyncio.sleep(0.001)  # yield to event loop

            # Final push
            if self.sim:
                self.sim.elapsed = time.time() - (self.sim.start_time or time.time())
                await self._send_state(ws)
                channel_data = self._compute_channel_data()
                await ws.send_json({
                    "type": "simulation_complete",
                    "tick": self.sim.counter,
                    "elapsed_s": round(self.sim.elapsed or 0, 3),
                    "channel": channel_data,
                })
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await ws.send_json({"type": "error", "message": str(exc)})

    def _compute_channel_data(self) -> dict[str, Any]:
        """Compute LOS, RIS, and total channel coefficients from received data."""
        import math
        import numpy as np
        from ris_sim.core.engine import _free_space_coefficient_v

        result: dict[str, Any] = {"h_los_mag_db": 0, "h_ris_mag_db": 0, "h_total_mag_db": 0, "boost_db": 0}
        if not self.sim or not self.sim.output.entries:
            return result

        entry = self.sim.output.entries[-1]
        samples = entry.flatten_iq()
        if len(samples) == 0:
            return result

        h_total = complex(np.mean(samples)) / 0.1

        tx_node = None
        rx_node = None
        for n in self.sim.nodes:
            if n.id == entry.node_id:
                rx_node = n
                break
        for n in self.sim.nodes:
            if n.is_transmit and n.fc == entry.fc:
                tx_node = n
                break
        if tx_node is None and len(self.sim.nodes) >= 2:
            tx_node = self.sim.nodes[0]
        if rx_node is None and len(self.sim.nodes) >= 2:
            rx_node = self.sim.nodes[1]

        h_los = 0j
        if tx_node and rx_node:
            tx_loc = np.array(tx_node.location, dtype=np.float64)
            rx_loc = np.array(rx_node.location, dtype=np.float64)
            distance = float(np.linalg.norm(rx_loc - tx_loc))
            h_los = complex(_free_space_coefficient_v(entry.fc, distance))

        h_ris = h_total - h_los

        return {
            "h_los_mag_db": round(20.0 * math.log10(max(abs(h_los), 1e-20)), 2),
            "h_ris_mag_db": round(20.0 * math.log10(max(abs(h_ris), 1e-20)), 2),
            "h_total_mag_db": round(20.0 * math.log10(max(abs(h_total), 1e-20)), 2),
            "boost_db": round(20.0 * math.log10(max(abs(h_total) / max(abs(h_los), 1e-20), 1e-20)), 2),
        }

    async def _send_state(self, ws) -> None:
        if not self.sim:
            return

        nodes_state = []
        for node in self.sim.nodes:
            nodes_state.append({
                "id": node.id,
                "mode": node.current_mode,
                "location": list(node.location),
                "fc": node.fc if node.fc > 0 else None,
            })

        ris_state = []
        for ris in self.sim.ris_controllers:
            ris_state.append({
                "id": ris.id,
                "plane": ris.plane,
                "location": list(ris.location),
                "array_size": list(ris.array_size),
                "config": ris.configuration_matrix.tolist()[:32],
            })

        # Latest IQ per receiver
        latest_iq: dict[str, list] = {}
        for entry in self.sim.output.entries:
            if entry.data:
                # Only send last block
                last_block = entry.data[-1]
                latest_iq[entry.node_id] = last_block

        max_req = max((n.req_time for n in self.sim.nodes if n.req_time > 0), default=0)
        estimated_total = self.sim.counter + max_req + 1
        elapsed = time.time() - (self.sim.metrics.start_time or time.time())
        rate = self.sim.counter / elapsed if elapsed > 0 else 0
        eta = (estimated_total - self.sim.counter) / rate if rate > 0 else 0

        await ws.send_json({
            "type": "state",
            "tick": self.sim.counter,
            "estimated_total": estimated_total,
            "nodes": nodes_state,
            "ris": ris_state,
            "latest_iq": latest_iq,
            "metrics": {
                "avg_tick_us": round(self.sim.metrics.avg_tick_us, 1),
                "max_tick_us": round(self.sim.metrics.max_tick_us, 1),
                "samples_processed": self.sim.metrics.total_iq_samples_processed,
                "ris_evaluations": self.sim.metrics.total_ris_element_evaluations,
                "tick_rate": round(rate, 0),
                "eta_s": round(eta, 1),
                "elapsed_s": round(elapsed, 3),
            },
        })


def _waveform_to_iq(wf: dict[str, Any]) -> list[list[float]]:
    kind = wf.get("kind", "iq_pairs")
    if kind == "iq_pairs":
        return [list(p) for p in wf.get("samples", [])]
    if kind == "bpsk_bits":
        bits = wf.get("bits", [])
        amp = float(wf.get("amplitude", 0.1))
        spp = int(wf.get("samples_per_symbol", 10))
        samples = []
        for bit in bits:
            symbol = amp if int(bit) == 1 else -amp
            samples.extend([[symbol, 0.0] for _ in range(spp)])
        return samples
    raise ValueError(f"Unknown waveform kind: {kind!r}")
