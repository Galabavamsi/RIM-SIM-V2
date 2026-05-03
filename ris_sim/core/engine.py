"""RIS Emulator core engine — in-memory Simulation class."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any

import numpy as np

from ris_sim.core.state import NodeState, OutputBuffer, OutputEntry, RisController
from ris_sim.core.random import SeedSequence
from ris_sim.core.logging import get_logger
from ris_sim.core.metrics import SimulationMetrics
from ris_sim.modules import mobility_functions as mob
from ris_sim.modules import validation as val
from ris_sim.channel import fading as fad
from ris_sim.channel import noise as noise_mod
from ris_sim.radio import impairments as imp

_log = get_logger("engine")


@np.vectorize
def _free_space_coefficient_v(fc: float, distance: float) -> complex:
    """Vectorized baseband free-space field coefficient."""
    if distance <= 0 or not math.isfinite(distance):
        return 0j
    c = 3e8
    wavelength = c / fc
    amplitude = wavelength / (4.0 * math.pi * distance)
    phase = -2.0 * math.pi * distance / wavelength
    return amplitude * np.exp(1j * phase)


def _element_visibility_vectorized(
    tx_loc: np.ndarray,
    elements: np.ndarray,
    rx_loc: np.ndarray,
    normal: np.ndarray,
) -> np.ndarray:
    """Vectorized RIS angular visibility for all elements at once.

    Returns (M, N) array of sqrt(cos_i * cos_r) where both cosines > 0, else 0.
    Incidence vector is FROM element TO tx; reflection vector is FROM element TO rx.
    """
    to_tx = tx_loc - elements  # (M, N, 3) — from element to TX
    to_rx = rx_loc - elements  # (M, N, 3) — from element to RX

    r_in = np.linalg.norm(to_tx, axis=2)  # (M, N)
    r_out = np.linalg.norm(to_rx, axis=2)  # (M, N)

    # Avoid division by zero
    r_in = np.where(r_in == 0, np.inf, r_in)
    r_out = np.where(r_out == 0, np.inf, r_out)

    cos_i = np.sum(to_tx * normal, axis=2) / r_in  # (M, N)
    cos_r = np.sum(to_rx * normal, axis=2) / r_out  # (M, N)

    visible = (cos_i > 0) & (cos_r > 0)
    return np.sqrt(np.maximum(cos_i * cos_r, 0.0)) * visible  # (M, N)


def total_ris_gain_vectorized(
    fc: float,
    tx_location: list[float],
    rx_location: list[float],
    ris_controllers: list[RisController],
) -> complex:
    """Compute total RIS channel gain vectorized across all elements and RIS panels."""
    total = 0j
    tx = np.array(tx_location, dtype=np.float64)
    rx = np.array(rx_location, dtype=np.float64)

    for ris in ris_controllers:
        elements = ris.coordinates  # (M, N, 3)
        m, n = ris.array_size

        # Visibility mask
        visibility = _element_visibility_vectorized(tx, elements, rx, ris.normal)

        # Cascaded free-space: Tx→element + element→Rx
        r_in = np.linalg.norm(elements - tx, axis=2)  # (M, N)
        r_out = np.linalg.norm(rx - elements, axis=2)  # (M, N)
        h_in = _free_space_coefficient_v(fc, r_in)  # (M, N)
        h_out = _free_space_coefficient_v(fc, r_out)  # (M, N)

        # Element-wise gain: b_n * visibility * h_in * h_out
        element_gains = ris.reflection_coeffs * visibility * h_in * h_out  # (M, N)
        total += np.sum(element_gains)

    return complex(total)


def _process_samples_vectorized(
    data: list[list[float]],
    tx_location: list[float],
    rx_location: list[float],
    fc: float,
    ris_controllers: list[RisController],
) -> list[list[float]]:
    """Apply combined LOS + RIS channel to IQ samples. Vectorized per-sample."""
    if not data:
        return [[0, 0] for _ in range(len(data))]

    tx = np.array(tx_location, dtype=np.float64)
    rx = np.array(rx_location, dtype=np.float64)
    distance = float(np.linalg.norm(rx - tx))

    h_los = _free_space_coefficient_v(fc, distance)
    nlos_gain = total_ris_gain_vectorized(fc, tx_location, rx_location, ris_controllers)
    total_channel = complex(h_los) + nlos_gain

    samples = np.array([complex(s[0], s[1]) for s in data], dtype=np.complex128)
    result = samples * total_channel
    return [[float(v.real), float(v.imag)] for v in result]


@np.vectorize
def _apply_cfo_to_sample(sample: complex, cfo_hz: float, sample_rate: float, tick_index: int, tau: float) -> complex:
    """Apply CFO phase rotation to a single complex sample."""
    phase = 2.0 * math.pi * cfo_hz * tick_index * tau
    return sample * np.exp(1j * phase)


def apply_cfo(
    samples: list[list[float]],
    cfo_hz: float,
    sample_rate: float,
    tick_index: int,
    tau: float,
) -> list[list[float]]:
    """Apply carrier frequency offset as a rotating phasor."""
    if cfo_hz == 0.0:
        return samples
    complex_samples = np.array([complex(s[0], s[1]) for s in samples], dtype=np.complex128)
    phase = 2.0 * math.pi * cfo_hz * tick_index * tau
    rotated = complex_samples * np.exp(1j * phase)
    return [[float(v.real), float(v.imag)] for v in rotated]


class Simulation:
    """Discrete-time RIS-assisted wireless channel emulator.

    All state is held in memory during the run. Output is written to an
    :class:`OutputBuffer` which can be exported to NPZ/JSON after completion.

    Usage::

        sim = Simulation.from_scenario("scenario.json")
        sim.queue_tx(node_id="node_1", data=iq_samples, fc=2.4e9, sample_rate=5880)
        sim.queue_rx(node_id="node_2", num_samps=120, fc=2.4e9, sample_rate=5880)
        result = sim.run()
        result.save_npz("output.npz")
    """

    def __init__(
        self,
        room: dict[str, Any],
        ris_configs: list[dict[str, Any]],
        nodes_config: list[dict[str, Any]],
        tau: float = 0.002,
        seed: int | None = None,
        channel_config: dict[str, Any] | None = None,
    ):
        self.tau = tau
        self.counter = 0
        self.start_time: float | None = None
        self.elapsed: float | None = None

        if seed is not None:
            np.random.seed(seed)

        self._seeds = SeedSequence(seed)

        self.room_length = float(room["room"]["length"])
        self.room_width = float(room["room"]["width"])
        self.room_height = float(room["room"].get("height", self.room_length))

        self.ris_controllers = [RisController.from_config(r) for r in ris_configs]
        self.nodes = [self._init_node(n) for n in nodes_config]
        self.output = OutputBuffer()

        # Channel configuration
        ch_cfg = channel_config or {}
        self.noise_figure_db = float(ch_cfg.get("noise_figure_db", 0.0))
        self.temperature_k = float(ch_cfg.get("temperature_k", 290.0))
        self.enable_noise = bool(ch_cfg.get("enable_noise", True))
        self.fading_config = ch_cfg.get("small_scale", {})
        self.enable_fading = bool(self.fading_config.get("enabled", False))

        # Per-node full RF impairment configs
        self.node_rf: dict[str, dict[str, Any]] = {}
        for n in nodes_config:
            rf = n.get("rf", {})
            if rf:
                self.node_rf[n["id"]] = dict(rf)

        # Metrics & observability
        self.metrics = SimulationMetrics()
        self._progress_interval_s: float = 1.0
        self._show_progress: bool = False

        # Pending RIS reconfigurations: {ris_id: matrix} — applied on next tick
        self._pending_ris_configs: dict[str, np.ndarray] = {}

        _log.info(
            "simulation_initialized",
            nodes=len(self.nodes),
            ris_panels=len(self.ris_controllers),
            tau=tau,
            seed=seed,
            noise_enabled=self.enable_noise,
            fading_enabled=self.enable_fading,
        )

    @staticmethod
    def _init_node(config: dict[str, Any]) -> NodeState:
        return NodeState(
            id=config["id"],
            location=list(config["location"]),
            mobility=dict(config.get("mobility", {"type": "static", "speed": 0.0})),
            request={},
            current_mode="idle",
            fc=-1.0,
            sample_rate=-1.0,
            next_update=-1,
            req_time=0,
            current_counter=-1,
            data=[],
        )

    # ── public API ──────────────────────────────────────────────────

    def queue_tx(
        self,
        node_id: str,
        data: np.ndarray | list,
        fc: float,
        sample_rate: float,
        *,
        tau: float | None = None,
    ) -> str:
        """Enqueue a transmit request for a node. Returns request_id."""
        node = self._get_node(node_id)
        tau = tau or self.tau

        if isinstance(data, np.ndarray):
            if np.iscomplexobj(data):
                data_list = np.stack((data.real, data.imag), axis=-1).tolist()
            else:
                data_list = data.tolist()
        else:
            data_list = list(data)

        streams = val.normalize_transmit_data(data_list)
        val.validate_transmit_request(float(sample_rate), streams, tau=tau)

        node.request = {
            "request_id": str(uuid.uuid4()),
            "mode": "transmit",
            "fc": fc,
            "sample_rate": sample_rate,
            "data": streams,
        }
        return node.request["request_id"]

    def queue_rx(
        self,
        node_id: str,
        num_samps: int,
        fc: float,
        sample_rate: float,
        *,
        tau: float | None = None,
    ) -> str:
        """Enqueue a receive request for a node. Returns request_id."""
        node = self._get_node(node_id)
        tau = tau or self.tau
        val.validate_receive_request(float(sample_rate), num_samps, tau=tau)
        request_id = str(uuid.uuid4())
        node.request = {
            "request_id": request_id,
            "mode": "receive",
            "fc": fc,
            "sample_rate": sample_rate,
            "num_samps": int(num_samps),
        }
        return request_id

    def run(self, max_ticks: int = 1_000_000, *, show_progress: bool = False) -> OutputBuffer:
        """Execute the simulation loop until all nodes are idle or max_ticks reached.

        Args:
            max_ticks: Safety cap on total tick count.
            show_progress: If True, print a progress line every second.
        """
        self._show_progress = show_progress
        self.metrics.start_time = time.time()
        self.start_time = self.metrics.start_time
        last_progress = 0.0

        _log.info("simulation_started", max_ticks=max_ticks)

        while True:
            if self.counter >= max_ticks:
                _log.warning("max_ticks_exceeded", ticks=self.counter, max_ticks=max_ticks)
                break

            self._timed_tick()

            if self._all_idle():
                _log.info("all_nodes_idle", tick=self.counter)
                break

            # Progress reporting
            if self._show_progress:
                now = time.time()
                if now - last_progress >= self._progress_interval_s:
                    # Estimate total ticks from TX/RX req_time
                    max_req = max((n.req_time for n in self.nodes if n.req_time > 0), default=0)
                    estimated_total = self.counter + max_req + 1
                    print(f"\r{self.metrics.progress_line(self.counter, estimated_total)}", end="", flush=True)
                    last_progress = now

        if self._show_progress:
            print()  # newline after progress

        self.elapsed = time.time() - (self.start_time or time.time())
        self.metrics.end_time = time.time()
        self.metrics.total_wall_time_s = self.elapsed or 0.0

        _log.info(
            "simulation_complete",
            ticks=self.counter,
            elapsed_s=f"{self.elapsed:.3f}" if self.elapsed else "0",
            avg_tick_us=f"{self.metrics.avg_tick_us:.1f}",
        )
        return self.output

    def tick(self) -> bool:
        """Advance one tick. Returns True if simulation should continue."""
        return self._timed_tick()

    def _timed_tick(self) -> bool:
        """Advance one tick with per-stage timing instrumentation."""
        if self.counter == 0:
            self.start_time = time.time()
            self.metrics.start_time = self.start_time

        t0 = time.perf_counter()

        t1 = time.perf_counter()
        self._update_ris()
        t2 = time.perf_counter()

        self._advance_mobility()
        t3 = time.perf_counter()

        self._assign_requests()
        t4 = time.perf_counter()

        temp_data = self._collect_transmit_chunks()
        t5 = time.perf_counter()

        self._process_active_nodes(temp_data)
        t6 = time.perf_counter()

        self.counter += 1

        total_us = (t6 - t0) * 1e6
        self.metrics.record_tick(
            self.counter - 1,
            total_us,
            ris_update_us=(t2 - t1) * 1e6,
            mobility_us=(t3 - t2) * 1e6,
            assign_us=(t4 - t3) * 1e6,
            tx_collect_us=(t5 - t4) * 1e6,
            rx_process_us=(t6 - t5) * 1e6,
        )

        if self._all_idle():
            self.elapsed = time.time() - (self.start_time or time.time())
            return False
        return True

    # ── internal tick stages ─────────────────────────────────────────

    def _update_ris(self) -> None:
        """Apply any pending RIS reconfigurations.

        If no external config was set via :meth:`ris_set_config`, preserves
        the current configuration (no-op). To reset to all-ones, call
        ``ris_set_config(id, np.ones(...))`` explicitly.
        """
        for ris in self.ris_controllers:
            if ris.id in self._pending_ris_configs:
                new_matrix = self._pending_ris_configs.pop(ris.id)
                ris.update_configuration(new_matrix)
                _log.debug("ris_config_applied", ris_id=ris.id, shape=ris.array_size)

    def ris_set_config(self, ris_id: str, matrix: np.ndarray | list[list[float]]) -> None:
        """Queue a RIS configuration to take effect on the **next** tick.

        Args:
            ris_id: RIS panel identifier (e.g. ``"ris_1"``).
            matrix: (M, N) array of element states. Values are mapped through
                    the panel's ``phase_response`` lookup to complex gains,
                    or used directly as complex coefficients if no lookup exists.

        Raises:
            KeyError: If ``ris_id`` is not found.
            ValueError: If matrix shape doesn't match the panel's ``array_size``.
        """
        ris = self._get_ris(ris_id)
        m, n = ris.array_size
        mat = np.asarray(matrix, dtype=float)
        if mat.shape != (m, n):
            raise ValueError(
                f"RIS {ris_id!r}: expected configuration matrix shape {(m, n)}, got {mat.shape}."
            )
        self._pending_ris_configs[ris_id] = mat
        _log.debug("ris_config_queued", ris_id=ris_id, shape=mat.shape)

    def _advance_mobility(self) -> None:
        for node in self.nodes:
            node.location = mob.do_mobility(
                {"id": node.id, "mobility": node.mobility, "location": node.location},
                self.room_length,
                self.room_width,
                self.tau,
            )

    def _assign_requests(self) -> None:
        for node in self.nodes:
            if not node.is_idle or not node.request:
                continue

            request = node.request
            if request["mode"] == "transmit":
                streams = val.normalize_transmit_data(request["data"])
                sample_rate = float(request["sample_rate"])
                val.validate_transmit_request(sample_rate, streams, tau=self.tau)
                node.current_mode = "transmit"
                node.request_id = request.get("request_id") or str(uuid.uuid4())
                node.fc = request["fc"]
                node.sample_rate = sample_rate
                node.data = streams
                tx_len = len(node.data[0])
                node.req_time = val.transmit_ticks(tx_len, sample_rate, self.tau)
                node.next_update = self.counter + int(node.req_time) + 1
                node.current_counter = self.counter
                node.request = {}

            elif request["mode"] == "receive":
                sample_rate = float(request["sample_rate"])
                num_samps = int(request["num_samps"])
                val.validate_receive_request(sample_rate, num_samps, tau=self.tau)
                node.current_mode = "receive"
                node.request_id = request.get("request_id") or str(uuid.uuid4())
                node.fc = request["fc"]
                node.sample_rate = sample_rate
                node.req_time = val.receive_ticks(num_samps, sample_rate, self.tau)
                node.remaining_samples = num_samps
                node.next_update = self.counter + int(node.req_time) + 1
                node.current_counter = self.counter
                node.request = {}
                self.output.add_entry(
                    OutputEntry(
                        request_id=node.request_id,
                        node_id=node.id,
                        fc=node.fc,
                        sample_rate=node.sample_rate,
                        requested_num_samps=num_samps,
                    )
                )

    def _collect_transmit_chunks(self) -> dict[str, list[list[float]]]:
        temp_data: dict[str, list[list[float]]] = {}
        for node in self.nodes:
            if not node.is_transmit:
                continue

            tau_samp = val.samples_per_tick(node.sample_rate, self.tau)
            stream = node.data[0]
            if len(stream) >= tau_samp:
                temp_data[node.id] = stream[:tau_samp]
                node.data[0] = stream[tau_samp:]
            else:
                chunk = list(stream)
                chunk.extend([[0, 0] for _ in range(tau_samp - len(stream))])
                temp_data[node.id] = chunk
                node.data[0] = []

        return temp_data

    def _process_active_nodes(self, temp_data: dict[str, list[list[float]]]) -> None:
        # Pre-apply TX-side impairments to each TX chunk
        tx_impaired: dict[str, list[list[float]]] = {}
        for tx_id, chunk in temp_data.items():
            tx_node = self._get_node(tx_id)
            tx_rf = self.node_rf.get(tx_id, {})
            tx_impaired[tx_id] = imp.apply_tx_impairments(
                chunk,
                tx_node.sample_rate,
                tx_rf,
                tick_index=self.counter,
                tau=self.tau,
                seed=self._seeds.next_tick(self.counter),
            )

        # Generate fading coefficients once per tick if enabled
        fading_coeffs: np.ndarray | None = None
        if self.enable_fading:
            model = self.fading_config.get("model", "rayleigh")
            fd = float(self.fading_config.get("max_doppler_hz", 5.0))
            k_db = float(self.fading_config.get("k_factor_db", 10.0))
            max_samples = max(
                (int(val.samples_per_tick(n.sample_rate, self.tau)) for n in self.nodes if n.is_receive),
                default=1,
            )
            if model == "rician":
                fading_coeffs = fad.rician_fading(
                    max_samples, fd, 1.0 / self.tau, k_factor_db=k_db,
                    seed=self._seeds.next_tick(self.counter),
                )
            else:
                fading_coeffs = fad.rayleigh_fading(
                    max_samples, fd, 1.0 / self.tau,
                    seed=self._seeds.next_tick(self.counter),
                )

        # RX processing
        for rx_node in self.nodes:
            if not rx_node.is_receive:
                continue

            tau_samp = val.samples_per_tick(rx_node.sample_rate, self.tau)
            output_data: list[list[float]] = []

            for tx_node in self.nodes:
                if not tx_node.is_transmit or tx_node.fc != rx_node.fc or tx_node.id not in tx_impaired:
                    continue

                # Get TX-impaired chunk
                tx_chunk = tx_impaired[tx_node.id]

                # Apply channel (LOS + RIS)
                channel_out = _process_samples_vectorized(
                    tx_chunk,
                    tx_node.location,
                    rx_node.location,
                    rx_node.fc,
                    self.ris_controllers,
                )

                # Apply fading
                if fading_coeffs is not None:
                    channel_out = fad.apply_fading(channel_out, fading_coeffs)

                if not output_data:
                    output_data = channel_out
                else:
                    if len(output_data) < len(channel_out):
                        output_data.extend([[0, 0]] * (len(channel_out) - len(output_data)))
                    elif len(channel_out) < len(output_data):
                        channel_out.extend([[0, 0]] * (len(output_data) - len(channel_out)))
                    output_data = [
                        [a[0] + b[0], a[1] + b[1]]
                        for a, b in zip(output_data, channel_out)
                    ]

            if not output_data:
                output_data = [[0, 0] for _ in range(tau_samp)]

            # Apply RX-side impairments
            rx_rf = self.node_rf.get(rx_node.id, {})
            output_data = imp.apply_rx_impairments(
                output_data,
                rx_node.sample_rate,
                rx_rf,
                tick_index=self.counter,
                tau=self.tau,
                seed=self._seeds.next_tick(self.counter),
            )

            # Add AWGN noise
            if self.enable_noise:
                bw = float(rx_node.sample_rate) / 2.0
                output_data = noise_mod.add_awgn(
                    output_data,
                    bw,
                    noise_figure_db=self.noise_figure_db,
                    temperature_k=self.temperature_k,
                    seed=self._seeds.next_tick(self.counter),
                )

            remaining = int(rx_node.remaining_samples)
            output_data = val.trim_iq_block(output_data, remaining)
            rx_node.remaining_samples = max(0, remaining - len(output_data))

            entry = self.output.find_entry(rx_node.request_id or "")
            if entry:
                entry.append_chunk(output_data)

            # Track per-tick IQ samples
            self.metrics.total_iq_samples_processed += len(output_data)

            rx_node.req_time -= 1
            rx_node.current_counter += 1
            if rx_node.req_time <= 0:
                rx_node.reset()
                rx_node.remaining_samples = 0

        # Track RIS element evaluations per tick
        for ris in self.ris_controllers:
            self.metrics.total_ris_element_evaluations += ris.element_count

        # TX time advances every tick while transmitting, independent of RX presence
        for tx_node in self.nodes:
            if not tx_node.is_transmit:
                continue
            tx_node.req_time -= 1
            tx_node.current_counter += 1
            if tx_node.req_time <= 0:
                tx_node.reset()

    # ── helpers ──────────────────────────────────────────────────────

    def _get_node(self, node_id: str) -> NodeState:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(f"Node {node_id!r} not found.")

    def _get_ris(self, ris_id: str) -> RisController:
        for ris in self.ris_controllers:
            if ris.id == ris_id:
                return ris
        raise KeyError(f"RIS panel {ris_id!r} not found.")

    def _all_idle(self) -> bool:
        return all(node.is_idle for node in self.nodes)

    def channel_sound(
        self,
        tx_node: str,
        rx_node: str,
        fc: float,
        sample_rate: float = 5880.0,
        *,
        pilot_length: int = 100,
        pilot_amplitude: float = 1.0,
    ) -> dict[str, complex | float]:
        """Measure the complex channel coefficient between two nodes.

        Sends a known pilot signal (constant ``[amplitude, 0]`` IQ samples),
        runs the simulation, and computes h = mean(rx / tx) over the received
        samples. The Simulation is reset to idle afterward for reuse.

        Args:
            tx_node: Transmitter node ID.
            rx_node: Receiver node ID.
            fc: Center frequency in Hz.
            sample_rate: Sample rate in Hz.
            pilot_length: Number of pilot IQ samples to send.
            pilot_amplitude: Amplitude of each pilot sample.

        Returns:
            Dict with keys: ``h_total`` (complex), ``h_los`` (complex),
            ``h_ris`` (complex), ``path_loss_db`` (float), ``phase_deg`` (float).
        """
        # Build pilot signal
        pilot = [[float(pilot_amplitude), 0.0] for _ in range(pilot_length)]

        # Measure with RIS
        self.queue_tx(tx_node, pilot, fc=fc, sample_rate=sample_rate)
        self.queue_rx(rx_node, pilot_length, fc=fc, sample_rate=sample_rate)
        output = self.run()
        samples = output.entries[-1].flatten_iq()  # latest entry
        h_total = complex(np.mean(samples)) / complex(pilot_amplitude)

        # Measure without RIS (LOS only) by clearing RIS configs
        saved_configs = {}
        for ris in self.ris_controllers:
            saved_configs[ris.id] = ris.configuration_matrix.copy()
            # Set to zero to disable RIS
            ris.update_configuration(np.zeros(ris.array_size, dtype=float))

        self.queue_tx(tx_node, pilot, fc=fc, sample_rate=sample_rate)
        self.queue_rx(rx_node, pilot_length, fc=fc, sample_rate=sample_rate)
        output_los = self.run()
        samples_los = output_los.entries[-1].flatten_iq()
        h_los = complex(np.mean(samples_los)) / complex(pilot_amplitude)

        # Restore RIS configs
        for ris in self.ris_controllers:
            ris.update_configuration(saved_configs[ris.id])

        h_ris = h_total - h_los

        return {
            "h_total": h_total,
            "h_los": h_los,
            "h_ris": h_ris,
            "path_loss_db": 20.0 * math.log10(max(abs(h_total), 1e-20)),
            "phase_deg": math.degrees(float(np.angle(h_total))),
        }

    # ── convenience constructors ─────────────────────────────────────

    @classmethod
    def from_scenario(cls, scenario: dict[str, Any], *, seed: int | None = None) -> Simulation:
        return cls(
            room={"room": dict(scenario["room"])},
            ris_configs=list(scenario.get("ris", [])),
            nodes_config=[
                {
                    "id": n["id"],
                    "location": list(n["location"]),
                    "mobility": dict(n.get("mobility", {"type": "static", "speed": 0.0})),
                    "rf": dict(n.get("rf", {})),
                }
                for n in scenario.get("nodes", [])
            ],
            tau=float(scenario.get("tau", 0.002)),
            seed=seed,
            channel_config=dict(scenario.get("channel", {})),
        )

    @classmethod
    def from_scenario_file(cls, path: str, *, seed: int | None = None) -> Simulation:
        import json
        with open(path) as f:
            scenario = json.load(f)
        return cls.from_scenario(scenario, seed=seed)
