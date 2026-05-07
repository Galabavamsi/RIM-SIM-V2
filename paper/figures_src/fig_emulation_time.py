"""Figure A3 - Emulation-time profiling (paper Fig 3 reproduction).

Measures actual wall-clock time per simulation tick as the number of TX-RX
pairs grows, on this machine, for tau in {0.3, 0.5, 1.0} s and two pipeline
configurations:

  full     : LOS + RIS + AWGN + Rayleigh fading + per-node CFO + phase noise
  reduced  : LOS + RIS only  (the "selective disable" curve in paper Fig 3)

Output:
    paper/figures/emulation_time.pdf       2-panel: time vs N + speed-up factor
    paper/figures_data/emulation_time.csv  raw timings
    paper/figures_data/emulation_time.meta.json
"""

from __future__ import annotations

import csv
import platform
import time

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
N_PAIRS_LIST = [1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32]
TAU_VALUES = [0.3, 0.5, 1.0]      # seconds per simulated tick
SAMPLE_RATE_HZ = 10_000.0          # samples/second per stream
N_TICKS_TIMED = 3                  # ticks per measurement (averaged)
N_WARMUP = 1                       # ticks discarded for warm-up
SEED = 42

NAME = "emulation_time"

# 16x16 RIS panel — same elements for all measurements so the per-pair
# RIS workload is constant.
RIS_M, RIS_N = 16, 16


def build_scenario(n_pairs: int, *, full_pipeline: bool, tau: float) -> dict:
    """Build a scenario with N TX-RX pairs, each on its own carrier (no cross-talk),
    plus one shared 16x16 RIS panel."""
    fc_step = 5e6  # MHz spacing between pair channels
    nodes: list[dict] = []
    for i in range(n_pairs):
        rf_full = {
            "cfo_hz": 100.0 + i * 5.0,
            "phase_noise_dbc_hz": -85.0,
            "amplitude_imbalance_db": 0.3,
        }
        nodes.append({
            "id": f"TX_{i}",
            "location": [2.0, 4.0 + 0.1 * i, 2.0],
            "mobility": {"type": "static"},
            "rf": rf_full if full_pipeline else {},
        })
        nodes.append({
            "id": f"RX_{i}",
            "location": [8.0, 6.0 + 0.1 * i, 2.0],
            "mobility": {"type": "static"},
            "rf": rf_full if full_pipeline else {},
        })

    ris_configs = [{
        "id": "ris_main",
        "fc": 2.4e9,
        "type": "static",
        "plane": 5,
        "location": [5.0, 0.0, 2.0],
        "unit_cell_m_length": 0.05,
        "unit_cell_n_length": 0.05,
        "unit_cell_gap": 0.005,
        "array_size": [RIS_M, RIS_N],
        "phase_response": {"1": [0.707, 0.707]},
        "configuration_matrix": [[1] * RIS_N for _ in range(RIS_M)],
    }]

    channel_cfg = {
        "enable_noise": full_pipeline,
        "noise_figure_db": 10.0,
        "temperature_k": 290.0,
    }
    if full_pipeline:
        channel_cfg["small_scale"] = {
            "enabled": True,
            "model": "rayleigh",
            "max_doppler_hz": 50.0,
        }

    return {
        "room": {"length": 10.0, "width": 10.0, "height": 5.0},
        "ris": ris_configs,
        "nodes": nodes,
        "channel": channel_cfg,
        "tau": tau,
    }


def time_ticks(n_pairs: int, *, full_pipeline: bool, tau: float) -> float:
    """Return mean wall-clock seconds per tick after warm-up."""
    scenario = build_scenario(n_pairs, full_pipeline=full_pipeline, tau=tau)
    sim = Simulation.from_scenario(scenario, seed=SEED)

    samples_per_tick = int(SAMPLE_RATE_HZ * tau)
    n_total = samples_per_tick * (N_WARMUP + N_TICKS_TIMED)
    pilot = [[1.0, 0.0] for _ in range(n_total)]

    for i in range(n_pairs):
        fc_i = 2.4e9 + i * 5e6
        sim.queue_tx(f"TX_{i}", pilot, fc=fc_i, sample_rate=SAMPLE_RATE_HZ)
        sim.queue_rx(f"RX_{i}", num_samps=n_total, fc=fc_i, sample_rate=SAMPLE_RATE_HZ)

    # Warm-up
    for _ in range(N_WARMUP):
        sim.tick()

    # Timed ticks
    start = time.perf_counter()
    for _ in range(N_TICKS_TIMED):
        sim.tick()
    elapsed = time.perf_counter() - start
    return elapsed / float(N_TICKS_TIMED)


def main() -> None:
    use_paper_style()

    print(f"[fig_emulation_time] machine: {platform.processor()} | {platform.system()} {platform.release()}")
    print(f"[fig_emulation_time] node-pair sweep {N_PAIRS_LIST}")
    print(f"[fig_emulation_time] tau values {TAU_VALUES}")
    print(f"[fig_emulation_time] {N_TICKS_TIMED} ticks averaged per measurement, "
          f"{N_WARMUP} warm-up, fs={SAMPLE_RATE_HZ/1e3:.0f} kHz, RIS={RIS_M}x{RIS_N}")

    rows: list[dict] = []
    for tau in TAU_VALUES:
        for full in (False, True):
            mode = "full" if full else "reduced"
            print(f"  -> tau={tau}s  mode={mode}", end="")
            for n in N_PAIRS_LIST:
                t = time_ticks(n, full_pipeline=full, tau=tau)
                rows.append({
                    "tau_s": tau,
                    "n_pairs": n,
                    "n_nodes": 2 * n,
                    "mode": mode,
                    "tick_time_s": t,
                    "real_time": t <= tau,
                    "samples_per_tick_per_stream": int(SAMPLE_RATE_HZ * tau),
                })
                print(f"  {n}={t*1e3:.0f}ms", end="", flush=True)
            print()

    # ── CSV ───────────────────────────────────────────────────────
    csv_path = DATA_DIR / f"{NAME}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[fig_emulation_time] wrote {csv_path}")

    # ── Build matrices for plotting ───────────────────────────────
    n_arr = np.array(N_PAIRS_LIST)
    times = {}      # times[(tau, mode)] = ndarray of seconds
    for tau in TAU_VALUES:
        for mode in ("reduced", "full"):
            times[(tau, mode)] = np.array(
                [r["tick_time_s"] for r in rows if r["tau_s"] == tau and r["mode"] == mode]
            )

    # ── Two-panel figure ──────────────────────────────────────────
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(11.5, 4.5))

    # (a) Tick time vs node count, per tau and mode
    tau_colors = {0.3: "#1f77b4", 0.5: "#2ca02c", 1.0: "#d62728"}
    for tau in TAU_VALUES:
        c = tau_colors[tau]
        ax_a.plot(2 * n_arr, times[(tau, "full")], "o-", lw=2, ms=6, color=c,
                   label=f"$\\tau$ = {tau} s, full pipeline")
        ax_a.plot(2 * n_arr, times[(tau, "reduced")], "s--", lw=1.4, ms=5, color=c, alpha=0.7,
                   label=f"$\\tau$ = {tau} s, LOS+RIS only")
        # Real-time threshold line at this tau
        ax_a.axhline(tau, color=c, ls=":", lw=0.9, alpha=0.6)
        ax_a.text(2 * n_arr[-1], tau, f"  $\\tau$ = {tau}s real-time",
                   color=c, fontsize=8, va="bottom")
    ax_a.set_xlabel("Number of nodes  (= 2 × number of TX-RX pairs)")
    ax_a.set_ylabel("Wall-clock time per tick  [s]")
    ax_a.set_title("(a) Per-tick wall time vs node count")
    ax_a.set_yscale("log")
    ax_a.legend(loc="upper left", fontsize=8, framealpha=0.9, ncol=2)
    ax_a.grid(True, alpha=0.3, which="both")

    # (b) Speed-up factor of "reduced" over "full" pipeline
    for tau in TAU_VALUES:
        c = tau_colors[tau]
        speedup = times[(tau, "full")] / np.maximum(times[(tau, "reduced")], 1e-9)
        ax_b.plot(2 * n_arr, speedup, "o-", lw=2, ms=6, color=c,
                   label=f"$\\tau$ = {tau} s")
    ax_b.axhline(1.0, color="k", lw=0.8, alpha=0.5, ls="--")
    ax_b.set_xlabel("Number of nodes")
    ax_b.set_ylabel("Speed-up:  full / (LOS+RIS only)")
    ax_b.set_title("(b) Cost of the full RF + fading pipeline")
    ax_b.legend(loc="best", fontsize=9, framealpha=0.9)
    ax_b.grid(True, alpha=0.3)

    fig.suptitle(
        "Emulator runtime profile — wall-clock time per simulated tick "
        f"(measured on this machine, fs = {SAMPLE_RATE_HZ/1e3:.0f} kHz, RIS = {RIS_M}×{RIS_N})",
        fontsize=11.5,
        fontweight="bold",
        y=1.00,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    pdf_path = save_pdf(fig, NAME)
    print(f"[fig_emulation_time] wrote {pdf_path}")

    # ── Sidecar ───────────────────────────────────────────────────
    meta_path = write_meta(
        NAME,
        params={
            "n_pairs": N_PAIRS_LIST,
            "n_nodes": [2 * n for n in N_PAIRS_LIST],
            "tau_values_s": TAU_VALUES,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "n_ticks_timed": N_TICKS_TIMED,
            "n_warmup": N_WARMUP,
            "ris_size": [RIS_M, RIS_N],
            "machine": {
                "processor": platform.processor(),
                "system": platform.system(),
                "release": platform.release(),
                "python": platform.python_version(),
            },
            "modes": {
                "full": "noise + Rayleigh fading + per-node CFO + phase noise + IQ imbalance",
                "reduced": "LOS + RIS only (no noise, no fading, no impairments)",
            },
            "seed": SEED,
        },
    )
    print(f"[fig_emulation_time] wrote {meta_path}")

    # ── Summary printout ──────────────────────────────────────────
    print()
    for tau in TAU_VALUES:
        for mode in ("full", "reduced"):
            t = times[(tau, mode)]
            real_time_capable = (t <= tau)
            max_n = 2 * n_arr[real_time_capable].max() if real_time_capable.any() else 0
            print(f"  tau={tau}s {mode:7s}: max {max_n} nodes within real-time budget  "
                   f"(at N=32: {t[-1]*1e3:.1f} ms/tick)")


if __name__ == "__main__":
    main()
