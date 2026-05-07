"""Figure A1 — Polar-grid RIS validation (paper §III-C reproduction).

Reproduces the §III-C lab measurement scenario in the emulator:
  - 1 TX, 30 RXs on a 45 deg polar sector, 30 cm radial spacing, 10 deg angular
  - 3 RIS panels of 5x8 elements arranged side-by-side
  - configuration {sigma_1^2, sigma_2^2, sigma_1^2} with
        sigma_1 = +49.64 deg,  sigma_2 = -153.77 deg
  - single-tone (DC) baseband pilot at fc = 3.5 GHz, no noise
  - measures gain of total received signal relative to LOS at every RX

Output:
    paper/figures/polar_grid_validation.pdf       — heatmap on polar axes
    paper/figures_data/polar_grid_validation.csv  — raw per-RX numbers
    paper/figures_data/polar_grid_validation.meta.json
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

# ── §III-C parameters ──────────────────────────────────────────────
FC_HZ = 3.5e9
SIGMA_1_DEG = 49.64
SIGMA_2_DEG = -153.77

PANEL_M = 5  # rows (z direction when plane=5)
PANEL_N = 8  # cols (y direction when plane=5)
UNIT_CELL_M = 0.0428  # m (lambda/2 at 3.5 GHz; lambda = 8.57 cm)
UNIT_CELL_GAP = 0.002  # m, small gap

# RX polar grid (paper §III-C: 45 deg sector, 30 cm radial, 10 deg angular -> 30 RX)
ANGLES_DEG = np.arange(0.0, 45.0, 10.0)        # 0, 10, 20, 30, 40  -> 5 angles
RADII_M = np.arange(0.3, 1.81, 0.3)            # 0.3 .. 1.8 m       -> 6 radii
N_RX = len(ANGLES_DEG) * len(RADII_M)          # 30 RXs, matches paper

# Engine driving knobs (do not affect the measured h coefficient,
# only how many ticks each measurement takes)
SAMPLE_RATE_HZ = 5_000.0
PILOT_LENGTH = 50
PILOT_AMPLITUDE = 1.0
SEED = 42

NAME = "polar_grid_validation"

# Geometry of the 3-panel array.
#   Each 5x8 panel spans approximately
#       width_y  = N * cell + (N+1) * gap
#       height_z = M * cell + (M+1) * gap
PANEL_WIDTH_Y = PANEL_N * UNIT_CELL_M + (PANEL_N + 1) * UNIT_CELL_GAP
PANEL_HEIGHT_Z = PANEL_M * UNIT_CELL_M + (PANEL_M + 1) * UNIT_CELL_GAP

ARRAY_CENTER_Y = 1.5 * PANEL_WIDTH_Y           # midpoint of the 3 panels in y
ARRAY_CENTER_Z = PANEL_HEIGHT_Z / 2.0
# TX placed far on broadside so RIS round-trip path-loss is comparable to TX-RX LOS,
# making the directional RIS pattern visible in the absolute received power.
TX_LOC = (3.0, ARRAY_CENTER_Y, ARRAY_CENTER_Z)


def phase_to_complex(phase_deg: float) -> list[float]:
    """Convert a phase in degrees to a complex coefficient [Re, Im] for the RIS lookup."""
    p = math.radians(phase_deg)
    return [math.cos(p), math.sin(p)]


def build_panel(panel_id: str, y_offset: float, phase_deg: float) -> dict:
    return {
        "id": panel_id,
        "fc": FC_HZ,
        "type": "static",
        "plane": 5,                            # YZ plane, normal = +X
        "location": [0.0, y_offset, 0.0],
        "unit_cell_m_length": UNIT_CELL_M,
        "unit_cell_n_length": UNIT_CELL_M,
        "unit_cell_gap": UNIT_CELL_GAP,
        "array_size": [PANEL_M, PANEL_N],
        "phase_response": {"1": phase_to_complex(phase_deg)},
        "configuration_matrix": [[1] * PANEL_N for _ in range(PANEL_M)],
    }


def rx_grid() -> list[tuple[str, float, float, tuple[float, float, float]]]:
    """Return [(rx_id, theta_deg, r_m, (x, y, z)), ...]."""
    out: list[tuple[str, float, float, tuple[float, float, float]]] = []
    for theta_deg in ANGLES_DEG:
        for r in RADII_M:
            theta = math.radians(float(theta_deg))
            x = r * math.cos(theta)
            y = ARRAY_CENTER_Y + r * math.sin(theta)
            z = ARRAY_CENTER_Z
            rx_id = f"RX_t{int(theta_deg):02d}_r{int(r * 100):03d}"
            out.append((rx_id, float(theta_deg), float(r), (x, y, z)))
    return out


def los_coefficient(fc_hz: float, tx: tuple[float, float, float], rx: tuple[float, float, float]) -> complex:
    """Free-space baseband coefficient between TX and RX (matches engine convention)."""
    c = 3e8
    lam = c / fc_hz
    d = math.sqrt(sum((a - b) ** 2 for a, b in zip(rx, tx)))
    if d == 0.0:
        return 0j
    return (lam / (4.0 * math.pi * d)) * complex(math.cos(-2.0 * math.pi * d / lam), math.sin(-2.0 * math.pi * d / lam))


def build_scenario(rx_positions) -> dict:
    panels = [
        build_panel("panel_sigma1_left", 0.0, SIGMA_1_DEG),
        build_panel("panel_sigma2_mid", PANEL_WIDTH_Y, SIGMA_2_DEG),
        build_panel("panel_sigma1_right", 2.0 * PANEL_WIDTH_Y, SIGMA_1_DEG),
    ]

    nodes = [
        {"id": "TX", "location": list(TX_LOC), "mobility": {"type": "static"}},
    ]
    for rx_id, _, _, (x, y, z) in rx_positions:
        nodes.append({"id": rx_id, "location": [x, y, z], "mobility": {"type": "static"}})

    # Room must contain everything; nothing actually moves so this is just bounds.
    room_length = 5.0                                   # x
    room_width = max(2.0 * ARRAY_CENTER_Y + 2.0, 5.0)   # y
    room_height = max(2.0 * ARRAY_CENTER_Z + 1.0, 2.0)  # z

    return {
        "room": {"length": room_length, "width": room_width, "height": room_height},
        "ris": panels,
        "nodes": nodes,
        "channel": {"enable_noise": False},
    }


def measure_h_total(scenario: dict, rx_positions) -> dict[str, complex]:
    """Run one sim with TX -> all 30 RX, return measured h_total per RX."""
    sim = Simulation.from_scenario(scenario, seed=SEED)

    pilot = [[PILOT_AMPLITUDE, 0.0] for _ in range(PILOT_LENGTH)]
    sim.queue_tx("TX", pilot, fc=FC_HZ, sample_rate=SAMPLE_RATE_HZ)
    for rx_id, *_ in rx_positions:
        sim.queue_rx(rx_id, num_samps=PILOT_LENGTH, fc=FC_HZ, sample_rate=SAMPLE_RATE_HZ)

    output = sim.run()

    by_node: dict[str, complex] = {}
    for entry in output.entries:
        samples = entry.flatten_iq()
        if samples.size == 0:
            by_node[entry.node_id] = 0j
            continue
        by_node[entry.node_id] = complex(np.mean(samples)) / complex(PILOT_AMPLITUDE)
    return by_node




def main() -> None:
    use_paper_style()

    rx_positions = rx_grid()
    scenario = build_scenario(rx_positions)

    print(f"[fig_polar_grid] building scenario: 1 TX + {len(rx_positions)} RX, 3 RIS panels (5x8)")
    print(f"[fig_polar_grid] panel width (y): {PANEL_WIDTH_Y * 1000:.1f} mm; array center y={ARRAY_CENTER_Y:.3f} m")
    print(f"[fig_polar_grid] TX at {TX_LOC}")

    h_total = measure_h_total(scenario, rx_positions)

    rows: list[dict] = []
    for rx_id, theta_deg, r, (x, y, z) in rx_positions:
        h_los = los_coefficient(FC_HZ, TX_LOC, (x, y, z))
        h_t = h_total.get(rx_id, 0j)
        h_ris = h_t - h_los

        mag_los = abs(h_los)
        mag_total = abs(h_t)

        if mag_los > 0:
            gain_db = 20.0 * math.log10(max(mag_total / mag_los, 1e-20))
        else:
            gain_db = float("nan")

        rows.append(
            {
                "rx_id": rx_id,
                "theta_deg": theta_deg,
                "r_m": r,
                "x_m": x,
                "y_m": y,
                "z_m": z,
                "h_los_re": h_los.real,
                "h_los_im": h_los.imag,
                "h_total_re": h_t.real,
                "h_total_im": h_t.imag,
                "h_ris_re": h_ris.real,
                "h_ris_im": h_ris.imag,
                "abs_h_los": mag_los,
                "abs_h_total": mag_total,
                "gain_vs_los_db": gain_db,
            }
        )

    # ── CSV (raw numbers reviewers can verify) ────────────────────
    csv_path = DATA_DIR / f"{NAME}.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[fig_polar_grid] wrote {csv_path}")

    # ── Build the matrices (rows = angle, cols = radius) ──────────
    Z_gain = np.array([r["gain_vs_los_db"] for r in rows]).reshape(len(ANGLES_DEG), len(RADII_M))

    # ── Polar mesh edges for pcolormesh ───────────────────────────
    theta_rad = np.radians(ANGLES_DEG)
    half_step_deg = float(ANGLES_DEG[1] - ANGLES_DEG[0]) / 2.0
    theta_edges = np.concatenate(
        [
            theta_rad - math.radians(half_step_deg),
            [theta_rad[-1] + math.radians(half_step_deg)],
        ]
    )
    r_step = float(RADII_M[1] - RADII_M[0])
    r_edges = np.concatenate([[RADII_M[0] - r_step / 2.0], RADII_M + r_step / 2.0])
    R_edges, T_edges = np.meshgrid(r_edges, theta_edges)

    # ── Two-panel figure: heatmap + directional cut ───────────────
    fig = plt.figure(figsize=(12.0, 5.4))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.0], wspace=0.30,
                           left=0.05, right=0.97, top=0.78, bottom=0.13)

    # (a) Polar heatmap of gain vs LOS
    ax_a = fig.add_subplot(gs[0, 0], projection="polar")
    vmax = max(abs(Z_gain.min()), abs(Z_gain.max()))
    pcm_a = ax_a.pcolormesh(T_edges, R_edges, Z_gain, shading="auto",
                             cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    ax_a.set_thetamin(float(ANGLES_DEG[0]) - half_step_deg)
    ax_a.set_thetamax(float(ANGLES_DEG[-1]) + half_step_deg)
    ax_a.set_rlim(0, RADII_M[-1] + r_step / 2.0)
    ax_a.set_rlabel_position(91)
    ax_a.set_thetagrids(ANGLES_DEG, labels=[f"{int(a)}°" for a in ANGLES_DEG])
    ax_a.tick_params(axis='y', labelsize=8)
    ax_a.tick_params(axis='x', labelsize=10)
    ax_a.set_title("(a) Gain vs LOS [dB] across the polar grid",
                    pad=18, fontsize=11)
    cbar = fig.colorbar(pcm_a, ax=ax_a, fraction=0.046, pad=0.14, shrink=0.85)
    cbar.set_label("dB", fontsize=10)
    cbar.ax.tick_params(labelsize=9)

    # (b) Directional cut: gain vs angle, one curve per radius
    ax_b = fig.add_subplot(gs[0, 1])
    cmap = plt.cm.viridis(np.linspace(0.1, 0.9, len(RADII_M)))
    for j, r in enumerate(RADII_M):
        ax_b.plot(ANGLES_DEG, Z_gain[:, j], marker="o", lw=2.0, ms=6,
                  color=cmap[j], label=f"r = {r:.1f} m", zorder=3)
    ax_b.axhline(0.0, color="k", lw=1.0, alpha=0.5, linestyle="--",
                  label="LOS only", zorder=1)
    ax_b.set_xlabel("RX angle from broadside  [deg]", fontsize=11)
    ax_b.set_ylabel("Gain vs LOS  [dB]", fontsize=11)
    ax_b.set_title("(b) Directional cut at each radius", fontsize=11)
    ax_b.set_xticks(ANGLES_DEG)
    ax_b.legend(loc="best", fontsize=9, ncol=2, framealpha=0.9)
    ax_b.grid(True, alpha=0.3)
    ax_b.tick_params(labelsize=9)

    fig.suptitle(
        "Polar-grid RIS validation — paper §III-C scenario\n"
        "$f_c$ = 3.5 GHz, three 5×8 panels in $\\{\\sigma_1^2\\,\\sigma_2^2\\,\\sigma_1^2\\}$ "
        "with $\\sigma_1$ = +49.64°, $\\sigma_2$ = −153.77°",
        fontsize=12,
        fontweight="bold",
        y=0.97,
    )
    pdf_path = save_pdf(fig, NAME)
    print(f"[fig_polar_grid] wrote {pdf_path}")

    # ── Reproducibility sidecar ───────────────────────────────────
    meta_path = write_meta(
        NAME,
        params={
            "fc_hz": FC_HZ,
            "sigma_1_deg": SIGMA_1_DEG,
            "sigma_2_deg": SIGMA_2_DEG,
            "panel_size": [PANEL_M, PANEL_N],
            "n_panels": 3,
            "configuration": "{sigma_1^2, sigma_2^2, sigma_1^2}",
            "unit_cell_m": UNIT_CELL_M,
            "unit_cell_gap_m": UNIT_CELL_GAP,
            "panel_width_y_m": PANEL_WIDTH_Y,
            "array_center": [0.0, ARRAY_CENTER_Y, ARRAY_CENTER_Z],
            "tx_location": list(TX_LOC),
            "angles_deg": ANGLES_DEG.tolist(),
            "radii_m": RADII_M.tolist(),
            "n_rx": N_RX,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "pilot_length": PILOT_LENGTH,
            "pilot_amplitude": PILOT_AMPLITUDE,
            "seed": SEED,
        },
    )
    print(f"[fig_polar_grid] wrote {meta_path}")

    # ── Summary printout ──────────────────────────────────────────
    finite = Z_gain[np.isfinite(Z_gain)]
    print(f"\n[fig_polar_grid] gain vs LOS (dB) summary over {finite.size} RX:")
    print(f"    min  = {finite.min():+.2f}")
    print(f"    max  = {finite.max():+.2f}")
    print(f"    mean = {finite.mean():+.2f}")
    print(f"    @broadside (theta=0): row = {Z_gain[0, :].round(2).tolist()}")
    peak_angle_idx, peak_radius_idx = np.unravel_index(np.argmax(Z_gain), Z_gain.shape)
    print(
        f"    peak gain = {Z_gain[peak_angle_idx, peak_radius_idx]:+.2f} dB "
        f"@ theta={ANGLES_DEG[peak_angle_idx]:.0f}deg, r={RADII_M[peak_radius_idx]:.1f} m  "
        f"(paper §III-C reports peak near 25°)"
    )


if __name__ == "__main__":
    main()
