"""Runtime metrics for the RIS emulator."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TickMetrics:
    """Per-tick timing breakdown."""

    tick_index: int
    ris_update_us: float = 0.0
    mobility_us: float = 0.0
    assign_requests_us: float = 0.0
    tx_collect_us: float = 0.0
    rx_process_us: float = 0.0
    total_us: float = 0.0


@dataclass
class SimulationMetrics:
    """Aggregate metrics collected during a simulation run."""

    total_ticks: int = 0
    total_wall_time_s: float = 0.0
    avg_tick_us: float = 0.0
    max_tick_us: float = 0.0
    min_tick_us: float = float("inf")

    # Channel statistics
    total_ris_element_evaluations: int = 0
    total_iq_samples_processed: int = 0
    total_output_bytes: int = 0

    # Lifecycle
    start_time: float = 0.0
    end_time: float = 0.0

    # Per-tick breakdown (keeps last N ticks for debugging)
    tick_breakdown: list[TickMetrics] = field(default_factory=list)
    _max_breakdown: int = 1000

    # Running window
    _tick_times: list[float] = field(default_factory=list)
    _window_size: int = 100

    def record_tick(
        self,
        tick_index: int,
        total_us: float,
        *,
        ris_update_us: float = 0.0,
        mobility_us: float = 0.0,
        assign_us: float = 0.0,
        tx_collect_us: float = 0.0,
        rx_process_us: float = 0.0,
    ) -> None:
        self.total_ticks = tick_index + 1
        self._tick_times.append(total_us)

        if total_us > self.max_tick_us:
            self.max_tick_us = total_us
        if total_us < self.min_tick_us:
            self.min_tick_us = total_us

        # Rolling average
        if len(self._tick_times) > self._window_size:
            self._tick_times = self._tick_times[-self._window_size:]
        self.avg_tick_us = sum(self._tick_times) / len(self._tick_times)

        # Breakdown storage (fixed-size buffer)
        if len(self.tick_breakdown) < self._max_breakdown:
            self.tick_breakdown.append(
                TickMetrics(
                    tick_index=tick_index,
                    ris_update_us=ris_update_us,
                    mobility_us=mobility_us,
                    assign_requests_us=assign_us,
                    tx_collect_us=tx_collect_us,
                    rx_process_us=rx_process_us,
                    total_us=total_us,
                )
            )

    def report(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Simulation complete: {self.total_ticks} ticks in {self.total_wall_time_s:.3f}s",
            f"  avg tick: {self.avg_tick_us:.1f} us, max: {self.max_tick_us:.1f} us, min: {self.min_tick_us:.1f} us",
            f"  ticks/s: {self.total_ticks / self.total_wall_time_s:.1f}" if self.total_wall_time_s > 0 else "",
            f"  IQ samples processed: {self.total_iq_samples_processed:,}",
            f"  RIS element evaluations: {self.total_ris_element_evaluations:,}",
        ]
        return "\n".join(line for line in lines if line)

    def progress_line(self, tick: int, total_ticks: int) -> str:
        """One-line progress message."""
        pct = tick / max(total_ticks, 1) * 100
        elapsed = time.time() - self.start_time if self.start_time else 0
        rate = tick / elapsed if elapsed > 0 else 0
        eta = (total_ticks - tick) / rate if rate > 0 else 0
        return (
            f"tick {tick}/{total_ticks} ({pct:.0f}%) | "
            f"{rate:.0f} t/s | "
            f"ETA {eta:.1f}s | "
            f"avg {self.avg_tick_us:.0f}us/tick"
        )
