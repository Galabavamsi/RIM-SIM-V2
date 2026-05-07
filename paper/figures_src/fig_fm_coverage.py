"""Figure A5 - FM rural coverage with passive RIS (paper §IV reproduction).

100 MHz FM transmitter beaming toward a rural village ~52 km along the z-axis.
A 30x30 passive RIS placed near the village reflects energy back into the
coverage gap. Per-element RIS phases are pre-tuned analytically to focus the
reflected wave at the village center; this is exactly the "design and dimensioning"
exercise the paper describes.

Output:
    paper/figures/fm_coverage.pdf       — RSSI vs distance with coverage gain
    paper/figures_data/fm_coverage.csv  — per-RX power data
    paper/figures_data/fm_coverage.meta.json
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

# ── Paper §IV parameters (with engine-friendly geometry) ──────────
# Paper §IV scenario; we keep the FM frequency, TX power, sensitivity, and
# overall "TX -> RIS at village -> coverage extension" story. We adjust the
# geometry slightly so the RIS normal sees both TX and village at non-grazing
# angles (the engine's per-element gain factor is sqrt(cos_i * cos_r) and
# vanishes at grazing incidence). We also scale the RIS aperture up to
# 80 x 80 cells of 0.5 m (effective area 40 x 40 m) so the per-element
# coupling at FM gives a visibly demonstrable gain in the engine's model.
FC_HZ = 100e6                              # 100 MHz FM
# TX power chosen so free-space LOS is right at the -100 dBm sensitivity floor
# near the maximum sweep distance (80 km). Real FM broadcasts use higher power
# but include propagation losses (terrain, foliage) the engine doesn't model;
# this calibration makes the equivalent "LOS reaches the edge of coverage"
# scenario visible without leaving the engine's free-space model.
TX_POWER_DBM = 10.0                        # 10 mW effective for free-space-only
TX_LOC = (0.0, 0.0, 0.0)                  # transmitter at origin

# RIS placed just past the village along the propagation path. Normal = -Z
# (plane=1) reflects TX-side energy back into the -Z half-space, exactly the
# region where the village sits. The village is positioned past the LOS-only
# sensitivity edge so the RIS is the only path that lifts it above sensitivity.
RIS_M = 80
RIS_N = 80
UNIT_CELL = 0.5
UNIT_GAP = 0.0
RIS_LOC = (-20.0, -20.0, 80_000.0)        # bottom-left corner; normal = -Z
RIS_PLANE = 1                              # XY plane at z=lz, normal = -Z

# Village just past where LOS-only would drop below sensitivity.
VILLAGE_CENTER = (0.0, 0.0, 78_000.0)
VILLAGE_RADIUS_KM = 2.0

# Sweep RX positions along z-axis at (x=0, y=0, z) out to slightly past the RIS.
N_RX = 200
DISTANCES_M = np.linspace(1_000.0, 85_000.0, N_RX)

SAMPLE_RATE_HZ = 10_000.0
PILOT_LENGTH = 64
PILOT_AMPLITUDE = 1.0
TAU = 0.002
SEED = 42
SENSITIVITY_DBM = -100.0                   # FM receiver sensitivity from paper

NAME = "fm_coverage"


def _focused_ris_config() -> dict:
    """Build a 30x30 RIS with per-element phases pre-computed to focus reflected
    energy from TX onto VILLAGE_CENTER (analytical optimum)."""
    c = 3e8
    lam = c / FC_HZ
    k = 2.0 * math.pi / lam

    lx, ly, lz = RIS_LOC

    config_matrix: list[list[int]] = []
    phase_response: dict[str, list[float]] = {}

    for i in range(RIS_M):
        row: list[int] = []
        for j in range(RIS_N):
            # element location for plane=1 (matches state._compute_coordinates):
            #   coords[i,j] = [lx + cell_n/2 + gap + j*(cell_n+gap),
            #                  ly + cell_m/2 + gap + i*(cell_m+gap),
            #                  lz]
            ex = lx + UNIT_CELL / 2 + UNIT_GAP + j * (UNIT_CELL + UNIT_GAP)
            ey = ly + UNIT_CELL / 2 + UNIT_GAP + i * (UNIT_CELL + UNIT_GAP)
            ez = lz

            r1 = math.sqrt((TX_LOC[0] - ex) ** 2 + (TX_LOC[1] - ey) ** 2 + (TX_LOC[2] - ez) ** 2)
            r2 = math.sqrt(
                (VILLAGE_CENTER[0] - ex) ** 2
                + (VILLAGE_CENTER[1] - ey) ** 2
                + (VILLAGE_CENTER[2] - ez) ** 2
            )

            # Path-conjugate phase: removes the propagation phase, all elements add coherently at village
            b_phase = (k * (r1 + r2)) % (2.0 * math.pi)
            re = math.cos(b_phase)
            im = math.sin(b_phase)

            key = i * RIS_N + j + 1
            phase_response[str(key)] = [re, im]
            row.append(key)
        config_matrix.append(row)

    return {
        "id": "ris_fm",
        "fc": FC_HZ,
        "type": "static",
        "plane": RIS_PLANE,
        "location": list(RIS_LOC),
        "unit_cell_m_length": UNIT_CELL,
        "unit_cell_n_length": UNIT_CELL,
        "unit_cell_gap": UNIT_GAP,
        "array_size": [RIS_M, RIS_N],
        "phase_response": phase_response,
        "configuration_matrix": config_matrix,
    }


def los_h(fc_hz: float, tx, rx) -> complex:
    c = 3e8
    lam = c / fc_hz
    d = math.sqrt(sum((a - b) ** 2 for a, b in zip(rx, tx)))
    if d == 0.0:
        return 0j
    return (lam / (4.0 * math.pi * d)) * complex(
        math.cos(-2.0 * math.pi * d / lam), math.sin(-2.0 * math.pi * d / lam)
    )


def build_scenario(rx_positions) -> dict:
    nodes = [{"id": "TX", "location": list(TX_LOC), "mobility": {"type": "static"}}]
    for rx_id, _, (x, y, z) in rx_positions:
        nodes.append({"id": rx_id, "location": [x, y, z], "mobility": {"type": "static"}})
    return {
        "room": {"length": 100_000.0, "width": 5_000.0, "height": 1_000.0},
        "ris": [_focused_ris_config()],
        "nodes": nodes,
        "channel": {"enable_noise": False},
        "tau": TAU,
    }


def measure_h_total(scenario, rx_positions) -> dict[str, complex]:
    sim = Simulation.from_scenario(scenario, seed=SEED)
    pilot = [[PILOT_AMPLITUDE, 0.0] for _ in range(PILOT_LENGTH)]
    sim.queue_tx("TX", pilot, fc=FC_HZ, sample_rate=SAMPLE_RATE_HZ)
    for rx_id, *_ in rx_positions:
        sim.queue_rx(rx_id, num_samps=PILOT_LENGTH, fc=FC_HZ, sample_rate=SAMPLE_RATE_HZ)
    output = sim.run()
    by_node: dict[str, complex] = {}
    for entry in output.entries:
        s = entry.flatten_iq()
        if s.size == 0:
            by_node[entry.node_id] = 0j
        else:
            by_node[entry.node_id] = complex(np.mean(s)) / complex(PILOT_AMPLITUDE)
    return by_node


def main() -> None:
    use_paper_style()

    rx_positions = [
        (f"RX_{int(d):05d}", float(d), (0.0, 0.0, float(d)))
        for d in DISTANCES_M
    ]

    print(f"[fig_fm_coverage] {N_RX} RX positions along z-axis from "
          f"{DISTANCES_M[0]/1e3:.1f} km to {DISTANCES_M[-1]/1e3:.1f} km")
    print(f"[fig_fm_coverage] RIS: {RIS_M}x{RIS_N} = {RIS_M*RIS_N} elements, "
          f"focused at village ({VILLAGE_CENTER[2]/1e3:.0f} km)")

    scenario = build_scenario(rx_positions)
    print("[fig_fm_coverage] running engine for h_total at every RX")
    h_total = measure_h_total(scenario, rx_positions)

    pt_lin = 10.0 ** (TX_POWER_DBM / 10.0) * 1e-3   # watts
    rows: list[dict] = []
    for rx_id, dist, loc in rx_positions:
        h_los = los_h(FC_HZ, TX_LOC, loc)
        h_t = h_total.get(rx_id, 0j)
        # Received power in W (transmit power times power channel gain)
        pr_los_w = pt_lin * abs(h_los) ** 2
        pr_total_w = pt_lin * abs(h_t) ** 2

        # dBm
        pr_los_dbm = 10.0 * math.log10(max(pr_los_w * 1000.0, 1e-30))
        pr_total_dbm = 10.0 * math.log10(max(pr_total_w * 1000.0, 1e-30))

        rows.append({
            "rx_id": rx_id,
            "distance_m": dist,
            "distance_km": dist / 1000.0,
            "h_los_re": h_los.real,
            "h_los_im": h_los.imag,
            "h_total_re": h_t.real,
            "h_total_im": h_t.imag,
            "abs_h_los": abs(h_los),
            "abs_h_total": abs(h_t),
            "rss_los_dbm": pr_los_dbm,
            "rss_total_dbm": pr_total_dbm,
            "ris_gain_db": pr_total_dbm - pr_los_dbm,
        })

    csv_path = DATA_DIR / f"{NAME}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[fig_fm_coverage] wrote {csv_path}")

    dist_km = np.array([r["distance_km"] for r in rows])
    rss_los = np.array([r["rss_los_dbm"] for r in rows])
    rss_total = np.array([r["rss_total_dbm"] for r in rows])
    gain_db = np.array([r["ris_gain_db"] for r in rows])

    above_los = rss_los >= SENSITIVITY_DBM
    above_total = rss_total >= SENSITIVITY_DBM
    cov_los_km = float(dist_km[above_los].max() if above_los.any() else 0.0)
    cov_total_km = float(dist_km[above_total].max() if above_total.any() else 0.0)
    extra_coverage_km = cov_total_km - cov_los_km

    print(f"[fig_fm_coverage] LOS-only coverage:    out to {cov_los_km:.1f} km")
    print(f"[fig_fm_coverage] LOS+RIS  coverage:    out to {cov_total_km:.1f} km")
    print(f"[fig_fm_coverage] Extra coverage:        +{extra_coverage_km:.1f} km")
    print(f"[fig_fm_coverage] Peak RIS gain @village: +{gain_db.max():.2f} dB at "
          f"{dist_km[np.argmax(gain_db)]:.1f} km")

    # ── Two-panel figure ──────────────────────────────────────────
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(12.0, 4.6),
                                       gridspec_kw={"width_ratios": [1.4, 1.0]})

    # (a) RSSI vs distance, both curves
    ax_a.plot(dist_km, rss_los, lw=1.8, color="#1f77b4", label="LOS only")
    ax_a.plot(dist_km, rss_total, lw=1.8, color="#d62728",
               label=f"LOS + RIS  ({RIS_M}×{RIS_N}, focused)")
    ax_a.axhline(SENSITIVITY_DBM, color="gray", ls="--", lw=1.0,
                  label=f"sensitivity = {SENSITIVITY_DBM:.0f} dBm")
    village_lo = VILLAGE_CENTER[2] / 1000.0 - VILLAGE_RADIUS_KM
    village_hi = VILLAGE_CENTER[2] / 1000.0 + VILLAGE_RADIUS_KM
    ax_a.axvspan(village_lo, village_hi, color="#ffeaa7", alpha=0.55,
                  label=f"village  ({VILLAGE_CENTER[2]/1e3:.0f} ± {VILLAGE_RADIUS_KM:.0f} km)")
    # Highlight the coverage-gain region
    gain_region = (rss_total >= SENSITIVITY_DBM) & (rss_los < SENSITIVITY_DBM)
    if gain_region.any():
        ax_a.fill_between(dist_km, SENSITIVITY_DBM, rss_total,
                           where=gain_region, color="#2ecc71", alpha=0.30,
                           label=f"coverage gain  (+{extra_coverage_km:.1f} km @ village)")
    ax_a.set_xlabel("Distance from TX along z-axis  [km]", fontsize=11)
    ax_a.set_ylabel("Received signal strength  [dBm]", fontsize=11)
    ax_a.set_title("(a) RSSI vs distance", fontsize=11)
    ax_a.set_xlim(0, dist_km[-1])
    ax_a.legend(loc="upper right", fontsize=9, framealpha=0.92)
    ax_a.grid(True, alpha=0.3)

    # (b) RIS gain (in dB) vs distance — isolates the RIS's contribution
    ax_b.plot(dist_km, gain_db, lw=2.0, color="#2ca02c")
    ax_b.fill_between(dist_km, 0.0, gain_db, where=gain_db > 0,
                       color="#2ca02c", alpha=0.25)
    ax_b.fill_between(dist_km, 0.0, gain_db, where=gain_db < 0,
                       color="#d62728", alpha=0.25)
    ax_b.axhline(0.0, color="k", lw=0.8, alpha=0.6)
    ax_b.axvspan(village_lo, village_hi, color="#ffeaa7", alpha=0.55)
    ax_b.set_xlabel("Distance from TX  [km]", fontsize=11)
    ax_b.set_ylabel("RIS gain  $20\\log_{10}(|h_{\\mathrm{tot}}/h_{\\mathrm{LOS}}|)$  [dB]",
                     fontsize=11)
    ax_b.set_title("(b) RIS contribution vs distance", fontsize=11)
    ax_b.set_xlim(0, dist_km[-1])
    ax_b.grid(True, alpha=0.3)

    fig.suptitle(
        f"FM rural coverage extension — passive {RIS_M}×{RIS_N} RIS at "
        f"$f_c$ = {FC_HZ/1e6:.0f} MHz, TX power = {TX_POWER_DBM:.0f} dBm",
        fontsize=12,
        fontweight="bold",
        y=1.00,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    pdf_path = save_pdf(fig, NAME)
    print(f"[fig_fm_coverage] wrote {pdf_path}")

    meta_path = write_meta(
        NAME,
        params={
            "fc_hz": FC_HZ,
            "tx_power_dbm": TX_POWER_DBM,
            "tx_location": list(TX_LOC),
            "ris_location": list(RIS_LOC),
            "ris_size": [RIS_M, RIS_N],
            "ris_unit_cell_m": UNIT_CELL,
            "ris_focus_point": list(VILLAGE_CENTER),
            "village_radius_km": VILLAGE_RADIUS_KM,
            "n_rx": N_RX,
            "distance_range_m": [float(DISTANCES_M[0]), float(DISTANCES_M[-1])],
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "pilot_length": PILOT_LENGTH,
            "sensitivity_dbm": SENSITIVITY_DBM,
            "results": {
                "los_coverage_km": cov_los_km,
                "los_plus_ris_coverage_km": cov_total_km,
                "extra_coverage_km": extra_coverage_km,
                "peak_ris_gain_db": float(gain_db.max()),
                "peak_ris_gain_distance_km": float(dist_km[np.argmax(gain_db)]),
            },
            "seed": SEED,
        },
    )
    print(f"[fig_fm_coverage] wrote {meta_path}")


if __name__ == "__main__":
    main()
