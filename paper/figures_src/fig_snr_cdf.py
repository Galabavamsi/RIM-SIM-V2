"""Figure A4 - SNR CDF via parallel Monte Carlo (paper Fig 5 reproduction).

Drives the engine through `parallel_run` to produce a per-trial SNR distribution
under Rayleigh fading, then plots the CDF of LOS-only vs LOS+RIS.

  - 1 TX, 1 RX, fixed positions (10 m link, 2.4 GHz)
  - Rayleigh small-scale fading (max Doppler 50 Hz)
  - Thermal AWGN, NF = 10 dB, T = 290 K
  - 8x8 RIS panel, single phase per element
  - 200 trials per scenario; each trial uses a fresh fading realisation

Per-trial SNR is computed as
        SNR = (mean |y[n]|^2  -  noise_power_analytic)  /  noise_power_analytic

where noise_power_analytic = k * T * B * NF and B = sample_rate / 2.

Output:
    paper/figures/snr_cdf.pdf       — CDFs + summary box
    paper/figures_data/snr_cdf.csv  — per-trial SNR values
    paper/figures_data/snr_cdf.meta.json
"""

from __future__ import annotations

import csv
import math
import os
import platform

import matplotlib.pyplot as plt
import numpy as np

from paper.figures_src._common import (
    DATA_DIR,
    save_pdf,
    use_paper_style,
    write_meta,
)
from ris_sim.core.engine import Simulation
from ris_sim.parallel import parallel_run

# ── Sweep parameters ───────────────────────────────────────────────
N_TRIALS = 200                 # Monte Carlo trials per scenario
SAMPLE_RATE_HZ = 10_000.0
PILOT_LENGTH = 500
PILOT_AMPLITUDE = 1.0
TAU = 0.002
FC_HZ = 2.4e9
NF_DB = 10.0
TEMPERATURE_K = 290.0
DOPPLER_HZ = 50.0
WORKERS = max(1, (os.cpu_count() or 1) - 1)

NAME = "snr_cdf"

# Geometry — TX and RX on the same side of the RIS panel so both are visible
# from the front face (cos_i > 0 and cos_r > 0). RIS sits on the y=0 wall
# (plane=6, normal = +Y) and TX/RX are both at y = +4 m.
ROOM = {"length": 12.0, "width": 8.0, "height": 4.0}
TX_LOC = (2.0, 4.0, 2.0)
RX_LOC = (10.0, 4.0, 2.0)
RIS_LOC = (5.5, 0.0, 1.7)
RIS_M, RIS_N = 16, 16


def base_traffic(num_samps: int) -> list[dict]:
    pilot_iq = [[PILOT_AMPLITUDE, 0.0] for _ in range(num_samps)]
    return [
        {
            "mode": "transmit",
            "node_id": "TX",
            "fc": FC_HZ,
            "sample_rate": SAMPLE_RATE_HZ,
            "waveform": {"kind": "iq_pairs", "samples": pilot_iq},
        },
        {
            "mode": "receive",
            "node_id": "RX",
            "fc": FC_HZ,
            "sample_rate": SAMPLE_RATE_HZ,
            "num_samps": num_samps,
        },
    ]


def make_scenario(*, with_ris: bool, ris_uniform_phase_deg: float = 0.0) -> dict:
    """Build the scenario. If with_ris, the panel uses a single uniform phase
    (the same complex coefficient for every element). Pass the optimal phase
    found by `optimal_uniform_phase_deg()` to make the panel constructively
    combine with the LOS path."""
    ris_configs: list[dict] = []
    if with_ris:
        p = math.radians(ris_uniform_phase_deg)
        ris_configs.append({
            "id": "ris_main",
            "fc": FC_HZ,
            "type": "static",
            "plane": 6,                       # XZ wall at y=0, normal = +Y
            "location": list(RIS_LOC),
            "unit_cell_m_length": 0.0625,    # ~lambda/2 at 2.4 GHz
            "unit_cell_n_length": 0.0625,
            "unit_cell_gap": 0.005,
            "array_size": [RIS_M, RIS_N],
            "phase_response": {"1": [math.cos(p), math.sin(p)]},
            "configuration_matrix": [[1] * RIS_N for _ in range(RIS_M)],
        })

    return {
        "room": ROOM,
        "ris": ris_configs,
        "nodes": [
            {"id": "TX", "location": list(TX_LOC), "mobility": {"type": "static"}, "rf": {}},
            {"id": "RX", "location": list(RX_LOC), "mobility": {"type": "static"}, "rf": {}},
        ],
        "channel": {
            "enable_noise": True,
            "noise_figure_db": NF_DB,
            "temperature_k": TEMPERATURE_K,
            "small_scale": {
                "enabled": True,
                "model": "rayleigh",
                "max_doppler_hz": DOPPLER_HZ,
            },
        },
        "tau": TAU,
        "traffic": base_traffic(PILOT_LENGTH),
    }


def _los_h(fc_hz: float, tx, rx) -> complex:
    c = 3e8
    lam = c / fc_hz
    d = math.sqrt(sum((a - b) ** 2 for a, b in zip(rx, tx)))
    if d == 0.0:
        return 0j
    return (lam / (4.0 * math.pi * d)) * complex(
        math.cos(-2.0 * math.pi * d / lam),
        math.sin(-2.0 * math.pi * d / lam),
    )


def optimal_uniform_phase_deg() -> float:
    """One-shot: build a noiseless, fading-off scenario with phase=0, channel-sound
    to recover h_ris(b=1), then choose b* on the unit circle that maximizes
    |h_los + b * h_ris(b=1)|. Since h_ris is linear in b for a uniform-phase panel,
    this gives a closed-form optimum."""
    cal_scenario = {
        "room": ROOM,
        "ris": [{
            "id": "ris_main",
            "fc": FC_HZ,
            "type": "static",
            "plane": 6,
            "location": list(RIS_LOC),
            "unit_cell_m_length": 0.0625,
            "unit_cell_n_length": 0.0625,
            "unit_cell_gap": 0.005,
            "array_size": [RIS_M, RIS_N],
            "phase_response": {"1": [1.0, 0.0]},   # b = 1 + 0j
            "configuration_matrix": [[1] * RIS_N for _ in range(RIS_M)],
        }],
        "nodes": [
            {"id": "TX", "location": list(TX_LOC), "mobility": {"type": "static"}},
            {"id": "RX", "location": list(RX_LOC), "mobility": {"type": "static"}},
        ],
        "channel": {"enable_noise": False},
        "tau": TAU,
    }
    sim = Simulation.from_scenario(cal_scenario, seed=0)
    sound = sim.channel_sound("TX", "RX", fc=FC_HZ, sample_rate=SAMPLE_RATE_HZ,
                                pilot_length=64)
    h_los = complex(sound["h_los"])
    h_ris_at_b1 = complex(sound["h_ris"])

    if abs(h_ris_at_b1) < 1e-30:
        return 0.0

    # |h_los + b * h_ris_at_b1| max  with  |b| = 1
    # achieved by b = h_los / |h_los| * conj(h_ris_at_b1) / |h_ris_at_b1|
    b_opt = (h_los / abs(h_los)) * (h_ris_at_b1.conjugate() / abs(h_ris_at_b1))
    phase_deg = math.degrees(math.atan2(b_opt.imag, b_opt.real))

    # Predicted gain (deterministic part only, before fading)
    gain_predicted = 20.0 * math.log10(abs(h_los + b_opt * h_ris_at_b1) / abs(h_los))
    print(f"[fig_snr_cdf] calibration: |h_los| = {abs(h_los):.3e},  "
          f"|h_ris| = {abs(h_ris_at_b1):.3e}")
    print(f"[fig_snr_cdf] optimal uniform RIS phase = {phase_deg:+.2f} deg  "
          f"(predicted deterministic gain = {gain_predicted:+.2f} dB)")
    return phase_deg


def thermal_noise_power_per_component(sample_rate_hz: float, nf_db: float) -> float:
    """Noise power per I or Q component (k T B NF / 2)."""
    k = 1.380649e-23
    bandwidth = sample_rate_hz / 2.0
    nf_linear = 10.0 ** (nf_db / 10.0)
    return k * TEMPERATURE_K * bandwidth * nf_linear / 2.0


def _flatten_iq_dict(out: dict) -> np.ndarray:
    """Get the first RX entry's samples as a complex ndarray."""
    if not out.get("outputs"):
        return np.array([], dtype=np.complex128)
    blocks = out["outputs"][0].get("data", [])
    flat = []
    for block in blocks:
        for pair in block:
            flat.append(complex(float(pair[0]), float(pair[1])))
    return np.asarray(flat, dtype=np.complex128)


def trial_snr_db(out: dict, *, noise_per_component: float) -> float:
    samples = _flatten_iq_dict(out)
    if samples.size == 0:
        return float("nan")
    received_power = float(np.mean(np.abs(samples) ** 2))
    noise_total = 2.0 * noise_per_component
    signal_power = max(received_power - noise_total, 1e-30)
    return 10.0 * math.log10(signal_power / noise_total)


def run_scenario(label: str, scenario: dict) -> list[float]:
    print(f"[fig_snr_cdf] {label}: {N_TRIALS} trials on {WORKERS} workers")
    noise_per_comp = thermal_noise_power_per_component(SAMPLE_RATE_HZ, NF_DB)
    snrs: list[float] = []
    for out, _seed in parallel_run(scenario, trials=N_TRIALS, workers=WORKERS,
                                     show_progress=False):
        snrs.append(trial_snr_db(out, noise_per_component=noise_per_comp))
    return snrs


def main() -> None:
    use_paper_style()

    optimal_phase = optimal_uniform_phase_deg()
    snrs_los = run_scenario("LOS only", make_scenario(with_ris=False))
    snrs_ris = run_scenario(
        f"LOS + RIS (phase = {optimal_phase:+.1f} deg)",
        make_scenario(with_ris=True, ris_uniform_phase_deg=optimal_phase),
    )

    arr_los = np.array(snrs_los, dtype=float)
    arr_ris = np.array(snrs_ris, dtype=float)
    arr_los = arr_los[np.isfinite(arr_los)]
    arr_ris = arr_ris[np.isfinite(arr_ris)]

    # ── CSV ───────────────────────────────────────────────────────
    csv_path = DATA_DIR / f"{NAME}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trial", "snr_db_los_only", "snr_db_los_plus_ris"])
        for i in range(N_TRIALS):
            a = snrs_los[i] if i < len(snrs_los) else ""
            b = snrs_ris[i] if i < len(snrs_ris) else ""
            w.writerow([i, a, b])
    print(f"[fig_snr_cdf] wrote {csv_path}")

    median_los = float(np.median(arr_los))
    median_ris = float(np.median(arr_ris))
    p10_los, p90_los = float(np.percentile(arr_los, 10)), float(np.percentile(arr_los, 90))
    p10_ris, p90_ris = float(np.percentile(arr_ris, 10)), float(np.percentile(arr_ris, 90))
    median_gain = median_ris - median_los
    p10_gain = p10_ris - p10_los

    print(f"[fig_snr_cdf] LOS only : median {median_los:.2f} dB  "
          f"p10 {p10_los:.2f}  p90 {p90_los:.2f}")
    print(f"[fig_snr_cdf] LOS+RIS  : median {median_ris:.2f} dB  "
          f"p10 {p10_ris:.2f}  p90 {p90_ris:.2f}")
    print(f"[fig_snr_cdf] Median gain : {median_gain:+.2f} dB  "
          f"(10th-percentile gain: {p10_gain:+.2f} dB)")

    # ── Two-panel figure: CDF + box-and-whisker ───────────────────
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(11.5, 4.5),
                                       gridspec_kw={"width_ratios": [1.4, 1.0]})

    # (a) CDF
    for arr, label, color in [
        (arr_los, "LOS only",                       "#d62728"),
        (arr_ris, f"LOS + RIS ({RIS_M}×{RIS_N})", "#2ca02c"),
    ]:
        x = np.sort(arr)
        y = np.arange(1, len(x) + 1) / len(x)
        ax_a.plot(x, y, lw=2.0, color=color, label=label)
        ax_a.axvline(np.median(arr), color=color, lw=1.0, ls="--", alpha=0.5)

    ax_a.set_xlabel("SNR  [dB]")
    ax_a.set_ylabel("CDF  $F(\\mathrm{SNR})$")
    ax_a.set_title("(a) Empirical SNR CDF over 200 fading realisations")
    ax_a.legend(loc="upper left", framealpha=0.9, fontsize=10)
    ax_a.grid(True, alpha=0.3)
    ax_a.set_ylim(0, 1)
    summary = (
        f"Median gain:  {median_gain:+.2f} dB\n"
        f"10%ile gain:  {p10_gain:+.2f} dB\n"
        f"LOS  median: {median_los:+.2f} dB\n"
        f"LOS+RIS med: {median_ris:+.2f} dB"
    )
    ax_a.text(0.985, 0.05, summary, transform=ax_a.transAxes,
              ha="right", va="bottom", fontsize=9, family="monospace",
              bbox=dict(boxstyle="round,pad=0.4", fc="#fff8dc",
                        ec="#999", alpha=0.85))

    # (b) Box-and-whisker comparison
    bp = ax_b.boxplot(
        [arr_los, arr_ris],
        labels=["LOS only", "LOS + RIS"],
        patch_artist=True,
        widths=0.55,
        showfliers=True,
        medianprops=dict(color="black", lw=2),
    )
    for patch, color in zip(bp["boxes"], ["#d62728", "#2ca02c"]):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax_b.set_ylabel("SNR  [dB]")
    ax_b.set_title("(b) Distribution summary")
    ax_b.grid(True, alpha=0.3, axis="y")

    fig.suptitle(
        f"Monte Carlo SNR distribution — {N_TRIALS} fading trials per scenario "
        f"($f_c$ = {FC_HZ/1e9:.1f} GHz, NF = {NF_DB:.0f} dB, $f_d$ = {DOPPLER_HZ:.0f} Hz)",
        fontsize=11.5,
        fontweight="bold",
        y=1.00,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    pdf_path = save_pdf(fig, NAME)
    print(f"[fig_snr_cdf] wrote {pdf_path}")

    # ── Sidecar ───────────────────────────────────────────────────
    meta_path = write_meta(
        NAME,
        params={
            "n_trials": N_TRIALS,
            "workers": WORKERS,
            "fc_hz": FC_HZ,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "pilot_length": PILOT_LENGTH,
            "pilot_amplitude": PILOT_AMPLITUDE,
            "tau_s": TAU,
            "tx_location": list(TX_LOC),
            "rx_location": list(RX_LOC),
            "ris_location": list(RIS_LOC),
            "ris_size": [RIS_M, RIS_N],
            "noise_figure_db": NF_DB,
            "temperature_k": TEMPERATURE_K,
            "fading_model": "rayleigh",
            "max_doppler_hz": DOPPLER_HZ,
            "ris_uniform_phase_deg": optimal_phase,
            "machine": platform.processor(),
            "results": {
                "los_only": {"median_db": median_los, "p10_db": p10_los, "p90_db": p90_los},
                "los_plus_ris": {"median_db": median_ris, "p10_db": p10_ris, "p90_db": p90_ris},
                "median_gain_db": median_gain,
                "p10_gain_db": p10_gain,
            },
            "snr_metric": "(mean|y|^2 - kTBNF) / kTBNF",
        },
    )
    print(f"[fig_snr_cdf] wrote {meta_path}")


if __name__ == "__main__":
    main()
