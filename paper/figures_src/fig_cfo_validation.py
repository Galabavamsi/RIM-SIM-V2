"""Figure A2 - CFO validation (paper Fig 2 reproduction).

Paper claim: with the engine's RX-side CFO impairment turned on, an external
receiver can recover the injected CFO from a known pilot. The original Fig 2
sweeps actual_cfo on x-axis vs estimated_cfo on y-axis; here we drive the engine
end-to-end and show the same sweep using a standard differential-phase estimator.

Setup:
  - 1 TX, 1 RX, LOS only (RIS disabled, fading off, AWGN configurable)
  - TX sends a constant-IQ (DC) pilot which the engine + RX-CFO rotates into
        y[n] = exp(j 2 pi f_cfo t[n])  *  h_los  *  pilot
  - estimator: f_hat = (fs / 2 pi) * angle( mean(y[n] * conj(y[n-1])) )

For each injected CFO in CFO_SWEEP_HZ we run a fresh sim, then plot actual vs
estimated and report RMSE.

Output:
    paper/figures/cfo_validation.pdf
    paper/figures_data/cfo_validation.csv
    paper/figures_data/cfo_validation.meta.json
"""

from __future__ import annotations

import csv
import math

import matplotlib.pyplot as plt
import numpy as np

from paper.figures_src._common import (
    DATA_DIR,
    save_pdf,
    use_paper_style,
    write_meta,
)
from ris_sim.core.engine import Simulation

# ── Sweep parameters ───────────────────────────────────────────────
CFO_SWEEP_HZ = np.linspace(-1500.0, 1500.0, 25).tolist()
FC_HZ = 2.4e9            # carrier; CFO behavior is independent of fc
SAMPLE_RATE_HZ = 50_000.0
PILOT_LENGTH = 2_000     # samples; long enough that 1 cycle of 1500 Hz is well-resolved
TAU = 0.002              # sec per tick; 100 samples/tick at fs=50 kHz
SEED = 42

# Two operating points: clean (high SNR -> validates engine math) and noisy
# (lower SNR -> shows the estimator under realistic conditions, like paper Fig 2).
# We control SNR via the pilot amplitude rather than warping link distance,
# so the geometry stays a normal 10 m room.
PILOT_AMP_CLEAN = 1.0       # link SNR ~ 90 dB after LOS path loss + noise floor
PILOT_AMP_NOISY = 1.0e-4    # link SNR ~ 17 dB after the same path

NF_DB = 10.0                # standard receiver noise figure for both runs

NAME = "cfo_validation"

ROOM = {"length": 10.0, "width": 10.0, "height": 5.0}
TX_LOC = (2.0, 5.0, 2.0)
RX_LOC = (8.0, 5.0, 2.0)


def build_scenario(cfo_hz: float, *, enable_noise: bool, nf_db: float = 0.0) -> dict:
    return {
        "room": ROOM,
        "ris": [],
        "nodes": [
            {"id": "TX", "location": list(TX_LOC), "mobility": {"type": "static"}, "rf": {}},
            {
                "id": "RX",
                "location": list(RX_LOC),
                "mobility": {"type": "static"},
                "rf": {"cfo_hz": float(cfo_hz)},
            },
        ],
        "channel": {"enable_noise": enable_noise, "noise_figure_db": float(nf_db)},
        "tau": TAU,
    }


def estimate_cfo_hz(samples: np.ndarray, fs: float) -> float:
    """Differential-phase CFO estimator: y[n] = A exp(j 2 pi f n / fs)
    -> mean(y[n] conj(y[n-1])) ~ A^2 exp(j 2 pi f / fs).
    """
    if samples.size < 2:
        return float("nan")
    diff = samples[1:] * np.conj(samples[:-1])
    avg_phase = np.angle(np.mean(diff))
    return float(fs * avg_phase / (2.0 * math.pi))


def sweep(*, pilot_amplitude: float, enable_noise: bool, nf_db: float = 0.0,
          n_trials: int = 1) -> list[dict]:
    """Run a CFO sweep. With n_trials > 1, average estimates across noise realisations."""
    rows: list[dict] = []
    for cfo_actual in CFO_SWEEP_HZ:
        ests: list[float] = []
        for trial in range(n_trials):
            scenario = build_scenario(cfo_actual, enable_noise=enable_noise, nf_db=nf_db)
            sim = Simulation.from_scenario(scenario, seed=SEED + trial)
            pilot = [[float(pilot_amplitude), 0.0] for _ in range(PILOT_LENGTH)]
            sim.queue_tx("TX", pilot, fc=FC_HZ, sample_rate=SAMPLE_RATE_HZ)
            sim.queue_rx("RX", num_samps=PILOT_LENGTH, fc=FC_HZ, sample_rate=SAMPLE_RATE_HZ)
            out = sim.run()
            samples = out.entries[-1].flatten_iq()
            ests.append(estimate_cfo_hz(samples, SAMPLE_RATE_HZ))
        cfo_est = float(np.mean(ests))
        cfo_std = float(np.std(ests)) if len(ests) > 1 else 0.0
        rows.append(
            {
                "cfo_actual_hz": float(cfo_actual),
                "cfo_estimated_hz": cfo_est,
                "cfo_estimated_std_hz": cfo_std,
                "error_hz": cfo_est - float(cfo_actual),
                "pilot_amplitude": pilot_amplitude,
                "n_samples_received": PILOT_LENGTH,
                "n_trials": n_trials,
                "noise_enabled": enable_noise,
                "noise_figure_db": nf_db,
            }
        )
    return rows


def main() -> None:
    use_paper_style()

    print(f"[fig_cfo] sweeping {len(CFO_SWEEP_HZ)} CFO values, "
          f"pilot={PILOT_LENGTH} samples @ fs={SAMPLE_RATE_HZ/1e3:.0f} kHz")

    print(f"[fig_cfo] run 1: high-SNR  (pilot amp = {PILOT_AMP_CLEAN:g})")
    rows_clean = sweep(pilot_amplitude=PILOT_AMP_CLEAN, enable_noise=False)
    print(f"[fig_cfo] run 2: low-SNR  (pilot amp = {PILOT_AMP_NOISY:g}, NF = {NF_DB:.0f} dB, "
          f"3 trials averaged per point)")
    rows_noisy = sweep(pilot_amplitude=PILOT_AMP_NOISY, enable_noise=True, nf_db=NF_DB,
                       n_trials=3)

    # ── CSV (both runs interleaved by run_id) ─────────────────────
    csv_path = DATA_DIR / f"{NAME}.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["run", *list(rows_clean[0].keys())]
        )
        writer.writeheader()
        for r in rows_clean:
            writer.writerow({"run": "high_snr", **r})
        for r in rows_noisy:
            writer.writerow({"run": "low_snr", **r})
    print(f"[fig_cfo] wrote {csv_path}")

    actual = np.array([r["cfo_actual_hz"] for r in rows_clean])
    est_clean = np.array([r["cfo_estimated_hz"] for r in rows_clean])
    est_noisy = np.array([r["cfo_estimated_hz"] for r in rows_noisy])
    std_noisy = np.array([r["cfo_estimated_std_hz"] for r in rows_noisy])

    rmse_clean = float(np.sqrt(np.mean((est_clean - actual) ** 2)))
    rmse_noisy = float(np.sqrt(np.mean((est_noisy - actual) ** 2)))
    print(f"[fig_cfo] high-SNR RMSE : {rmse_clean:.3f} Hz")
    print(f"[fig_cfo] low-SNR  RMSE : {rmse_noisy:.3f} Hz")

    # ── Two-panel figure ──────────────────────────────────────────
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(11.5, 4.5),
                                       gridspec_kw={"width_ratios": [1.1, 1.0]})

    ideal = np.linspace(actual.min(), actual.max(), 200)
    ax_a.plot(ideal, ideal, "k--", lw=1.0, alpha=0.5, label="ideal (y = x)", zorder=1)
    ax_a.plot(actual, est_clean, "o-", color="#1f77b4", lw=1.3, ms=6,
              label=f"high SNR  (RMSE = {rmse_clean:.2f} Hz)", zorder=3)
    ax_a.errorbar(actual, est_noisy, yerr=std_noisy, fmt="s", color="#d62728",
                   ms=5, lw=0, elinewidth=1.0, capsize=2.5, alpha=0.9,
                   label=f"low SNR  (RMSE = {rmse_noisy:.2f} Hz)", zorder=2)
    ax_a.set_xlabel("Actual CFO injected by emulator [Hz]")
    ax_a.set_ylabel("Estimated CFO at RX [Hz]")
    ax_a.set_title("(a) Estimated vs actual CFO")
    ax_a.legend(loc="upper left", framealpha=0.9, fontsize=9)
    ax_a.grid(True, alpha=0.3)
    ax_a.set_xlim(actual.min() * 1.05, actual.max() * 1.05)
    ax_a.set_ylim(actual.min() * 1.10, actual.max() * 1.10)
    ax_a.set_aspect("equal", adjustable="box")

    width = 80.0
    ax_b.bar(actual - width / 2, est_clean - actual, width=width, color="#1f77b4",
              alpha=0.85, label="high SNR", edgecolor="#0d4a8c", linewidth=0.5)
    ax_b.bar(actual + width / 2, est_noisy - actual, width=width, color="#d62728",
              alpha=0.85, label="low SNR", edgecolor="#7a0e10", linewidth=0.5)
    ax_b.axhline(0.0, color="k", lw=0.8)
    ax_b.set_xlabel("Actual CFO [Hz]")
    ax_b.set_ylabel("Estimation error  (estimated − actual) [Hz]")
    ax_b.set_title("(b) Per-point estimation error")
    ax_b.legend(loc="best", framealpha=0.9, fontsize=9)
    ax_b.grid(True, alpha=0.3, axis="y")

    fig.suptitle(
        "CFO validation — emulator injects, RX recovers via differential-phase estimator\n"
        f"$f_c$ = {FC_HZ/1e9:.1f} GHz,  $f_s$ = {SAMPLE_RATE_HZ/1e3:.0f} kHz,  "
        f"pilot = {PILOT_LENGTH} samples,  LOS-only channel,  NF = {NF_DB:.0f} dB",
        fontsize=11.5,
        fontweight="bold",
        y=1.00,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    pdf_path = save_pdf(fig, NAME)
    print(f"[fig_cfo] wrote {pdf_path}")

    meta_path = write_meta(
        NAME,
        params={
            "fc_hz": FC_HZ,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "pilot_length": PILOT_LENGTH,
            "tau_s": TAU,
            "tx_location": list(TX_LOC),
            "rx_location": list(RX_LOC),
            "cfo_sweep_hz": [float(c) for c in CFO_SWEEP_HZ],
            "runs": [
                {"name": "high_snr", "pilot_amplitude": PILOT_AMP_CLEAN,
                 "noise_enabled": False, "nf_db": 0.0, "n_trials": 1},
                {"name": "low_snr", "pilot_amplitude": PILOT_AMP_NOISY,
                 "noise_enabled": True, "nf_db": NF_DB, "n_trials": 3},
            ],
            "estimator": "differential phase: f = fs/(2 pi) * angle(mean(y[n]*conj(y[n-1])))",
            "rmse_hz": {"high_snr": rmse_clean, "low_snr": rmse_noisy},
            "seed": SEED,
        },
    )
    print(f"[fig_cfo] wrote {meta_path}")


if __name__ == "__main__":
    main()
