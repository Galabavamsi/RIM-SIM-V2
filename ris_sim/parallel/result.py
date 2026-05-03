"""Monte Carlo result aggregation — SNR CDFs, percentiles, plotting."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np


def _iq_pairs_to_complex(data_blocks: list[list[list[float]]]) -> np.ndarray:
    samples = []
    for block in data_blocks:
        for pair in block:
            samples.append(complex(float(pair[0]), float(pair[1])))
    return np.asarray(samples, dtype=np.complex128)


def compute_snr_from_output(output_entry: dict[str, Any]) -> float:
    data = output_entry.get("data", [])
    if not data:
        return -float("inf")
    samples = _iq_pairs_to_complex(data)
    if len(samples) < 2:
        return -float("inf")
    signal_power = float(np.abs(np.mean(samples)) ** 2)
    noise_power = float(np.var(samples))
    if noise_power <= 0:
        return float("inf") if signal_power > 0 else -float("inf")
    snr_linear = signal_power / noise_power
    if snr_linear <= 0:
        return -float("inf")
    return 10.0 * math.log10(snr_linear)


class MonteCarloResult:
    def __init__(self) -> None:
        self._snr_samples: list[float] = []
        self._errors: list[dict[str, Any]] = []

    def record(self, *, snr_db: float | None = None, error: dict[str, Any] | None = None) -> None:
        if error is not None:
            self._errors.append(error)
            return
        if snr_db is not None and math.isfinite(snr_db):
            self._snr_samples.append(snr_db)

    def record_snr(self, snr_db: float) -> None:
        self.record(snr_db=snr_db)

    @property
    def num_trials(self) -> int:
        return len(self._snr_samples) + len(self._errors)

    @property
    def num_errors(self) -> int:
        return len(self._errors)

    @property
    def snr_median(self) -> float:
        if not self._snr_samples:
            return float("nan")
        return float(np.median(self._snr_samples))

    @property
    def snr_mean(self) -> float:
        if not self._snr_samples:
            return float("nan")
        return float(np.mean(self._snr_samples))

    @property
    def snr_std(self) -> float:
        if not self._snr_samples:
            return float("nan")
        return float(np.std(self._snr_samples))

    @property
    def snr_p10(self) -> float:
        if not self._snr_samples:
            return float("nan")
        return float(np.percentile(self._snr_samples, 10))

    @property
    def snr_p90(self) -> float:
        if not self._snr_samples:
            return float("nan")
        return float(np.percentile(self._snr_samples, 90))

    def snr_cdf(self) -> tuple[np.ndarray, np.ndarray]:
        if not self._snr_samples:
            return np.array([]), np.array([])
        x = np.sort(self._snr_samples)
        y = np.arange(1, len(x) + 1) / len(x)
        return x, y

    def plot_snr_cdf(self, path: str | Path, *, title: str = "SNR CDF") -> None:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        x, y = self.snr_cdf()
        if len(x) == 0:
            return

        fig, ax = plt.subplots(figsize=(7, 5))
        ax.plot(x, y, linewidth=1.6, label="SNR")
        ax.axvline(self.snr_median, color="red", linestyle="--", alpha=0.5,
                   label=f"Median: {self.snr_median:.1f} dB")
        ax.axvline(self.snr_p10, color="orange", linestyle=":", alpha=0.5,
                   label=f"p10: {self.snr_p10:.1f} dB")
        ax.axvline(self.snr_p90, color="orange", linestyle=":", alpha=0.5,
                   label=f"p90: {self.snr_p90:.1f} dB")
        ax.set_xlabel("SNR (dB)")
        ax.set_ylabel("CDF")
        ax.set_title(title)
        ax.legend(loc="best")
        ax.grid(True, alpha=0.25)

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.tight_layout()
        fig.savefig(target, dpi=150)
        plt.close(fig)

    def summary(self) -> str:
        lines = [f"Monte Carlo: {self.num_trials} trials ({self.num_errors} errors)"]
        if self._snr_samples:
            lines.extend([
                f"  SNR mean:    {self.snr_mean:.2f} dB",
                f"  SNR median:  {self.snr_median:.2f} dB",
                f"  SNR std:     {self.snr_std:.2f} dB",
                f"  SNR p10-p90: {self.snr_p10:.1f} - {self.snr_p90:.1f} dB",
            ])
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"MonteCarloResult(trials={self.num_trials}, snr_median={self.snr_median:.1f})"
