"""Architecture diagram for RIS-SIM v2.

Three layered architecture rendered as boxes with matplotlib:
    - External Interfaces  (blue)   - 8 boxes
    - Emulator Core        (green)  - 5 boxes
    - Signal Models        (orange) - 6 boxes
    - Output / Metrics     (gray)   - 1 box

Vector PDF output sized to fit a single column of the paper.
"""

from __future__ import annotations

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from paper.figures_src._common import use_paper_style, save_pdf, write_meta

NAME = "architecture"


def _draw_layer(ax, y, height, label, items, header_color, box_face, box_edge):
    """Draw a layer: a header bar with `label`, then a row of boxes containing `items`.
    Each item is a tuple (title, subtitle) or just title.
    """
    n = len(items)
    left = 0.5
    right = 19.5
    width = right - left

    header_h = 0.55
    header = FancyBboxPatch(
        (left, y + height - header_h), width, header_h,
        boxstyle="round,pad=0.02,rounding_size=0.05",
        linewidth=0, facecolor=header_color,
    )
    ax.add_patch(header)
    ax.text(
        left + 0.2, y + height - header_h / 2, label,
        ha="left", va="center", color="white",
        fontsize=11, fontweight="bold",
    )

    box_h = height - header_h - 0.25
    box_w = width / n - 0.18
    box_y = y + 0.05

    centers_x = []
    for i, item in enumerate(items):
        if isinstance(item, tuple):
            title, subtitle = item
        else:
            title, subtitle = item, ""
        x = left + 0.09 + i * (box_w + 0.18)
        box = FancyBboxPatch(
            (x, box_y), box_w, box_h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            linewidth=1.0, facecolor=box_face, edgecolor=box_edge,
        )
        ax.add_patch(box)
        cx = x + box_w / 2
        centers_x.append(cx)
        if subtitle:
            ax.text(
                cx, box_y + box_h * 0.66, title,
                ha="center", va="center",
                fontsize=8.5, fontweight="bold", color="#1a1a1a",
            )
            ax.text(
                cx, box_y + box_h * 0.30, subtitle,
                ha="center", va="center",
                fontsize=7.0, color="#444",
            )
        else:
            ax.text(
                cx, box_y + box_h / 2, title,
                ha="center", va="center",
                fontsize=8.5, fontweight="bold", color="#1a1a1a",
            )
    return centers_x, box_y, box_y + box_h


def main() -> None:
    use_paper_style()

    fig, ax = plt.subplots(figsize=(11.0, 6.6))
    ax.set_xlim(0, 20)
    ax.set_ylim(0, 12)
    ax.set_aspect("equal")
    ax.axis("off")

    # Layer 1: External Interfaces
    iface_items = [
        ("Python API", ""),
        ("CLI", ""),
        ("ZeroMQ", "server / client"),
        ("Web Dashboard", "FastAPI + WS @ 20 Hz"),
        ("Three.js 3D", "topology view"),
        ("Form ↔ JSON", "config editor"),
        ("Scenario Library", "6 paper-grounded"),
        ("Figure Pipeline", "+ Parallel MC"),
    ]
    iface_y, iface_h = 9.2, 2.5
    iface_centers, iface_bot, iface_top = _draw_layer(
        ax, iface_y, iface_h, "External Interfaces",
        iface_items,
        header_color="#1f4e8b",
        box_face="#dbe8ff",
        box_edge="#3b6fb8",
    )

    # Layer 2: Emulator Core
    core_items = [
        ("Discrete-Time Loop", "tick = τ"),
        ("Scenario Loader", "+ validator"),
        ("State Manager", "in-memory"),
        ("Channel Sounding", "h_los, h_ris, h_total"),
        ("Per-Tick Metrics", "instrumentation"),
    ]
    core_y, core_h = 5.8, 2.5
    core_centers, core_bot, core_top = _draw_layer(
        ax, core_y, core_h, "Emulator Core",
        core_items,
        header_color="#2e7d4a",
        box_face="#dff3e0",
        box_edge="#3b8b46",
    )

    # Layer 3: Signal Models
    sig_items = [
        ("LOS Channel", "free-space"),
        ("Per-Element RIS", "vectorized + visibility"),
        ("AWGN", "kTBNF"),
        ("Fading", "Rayleigh / Rician"),
        ("RF Impairments", "CFO · PN · IQ · SFO · PA"),
        ("Mobility", "models"),
    ]
    sig_y, sig_h = 2.4, 2.5
    sig_centers, sig_bot, sig_top = _draw_layer(
        ax, sig_y, sig_h, "Signal Models",
        sig_items,
        header_color="#a85b1e",
        box_face="#ffe7c9",
        box_edge="#c87b1b",
    )

    # Output node (centered, gray, smaller)
    out_w, out_h = 7.2, 1.3
    out_x = (20 - out_w) / 2
    out_y = 0.4
    out_box = FancyBboxPatch(
        (out_x, out_y), out_w, out_h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=1.0, facecolor="#ececec", edgecolor="#666",
    )
    ax.add_patch(out_box)
    ax.text(
        out_x + out_w / 2, out_y + out_h * 0.66, "Output / Metrics",
        ha="center", va="center", fontsize=10, fontweight="bold", color="#222",
    )
    ax.text(
        out_x + out_w / 2, out_y + out_h * 0.30,
        "IQ samples · CSV · meta.json sidecars",
        ha="center", va="center", fontsize=8, color="#444",
    )

    # Inter-layer arrows (centered, double-headed)
    arrow_kwargs = dict(
        arrowstyle="-|>,head_length=0.32,head_width=0.22",
        color="#333", linewidth=1.2,
        connectionstyle="arc3,rad=0",
    )
    # IF -> CORE  (down)
    ax.add_patch(FancyArrowPatch(
        (10, iface_bot - 0.05), (10, core_top + 0.05),
        **arrow_kwargs,
    ))
    ax.text(
        10.25, (iface_bot + core_top) / 2,
        "requests · scenarios · seeds",
        ha="left", va="center", fontsize=8, color="#333",
    )
    # CORE -> SIG  (down)
    ax.add_patch(FancyArrowPatch(
        (10, core_bot - 0.05), (10, sig_top + 0.05),
        **arrow_kwargs,
    ))
    ax.text(
        10.25, (core_bot + sig_top) / 2,
        "channel · impairments · noise",
        ha="left", va="center", fontsize=8, color="#333",
    )
    # SIG -> OUT  (down)
    ax.add_patch(FancyArrowPatch(
        (10, sig_bot - 0.05), (10, out_y + out_h + 0.05),
        **arrow_kwargs,
    ))
    ax.text(
        10.25, (sig_bot + out_y + out_h) / 2,
        r"$y[n]=(\sum \mathcal{I}_{TX}\,h_k\,\mathcal{F}_k)\,\mathcal{I}_{RX}+n$",
        ha="left", va="center", fontsize=8, color="#333",
    )
    # OUT -> IF  (return path, on the right side)
    return_arrow = FancyArrowPatch(
        (out_x + out_w + 0.05, out_y + out_h / 2),
        (19.6, iface_top - 0.2),
        arrowstyle="-|>,head_length=0.3,head_width=0.20",
        color="#888", linewidth=1.0,
        connectionstyle="arc3,rad=-0.35",
        linestyle="--",
    )
    ax.add_patch(return_arrow)
    ax.text(
        19.7, (out_y + out_h / 2 + iface_top - 0.2) / 2,
        "results /\nWS frames",
        ha="left", va="center", fontsize=7.5, color="#666", style="italic",
    )

    fig.suptitle(
        "RIS-SIM v2 - layered system architecture",
        fontsize=12, fontweight="bold", y=0.985,
    )

    pdf_path = save_pdf(fig, NAME)
    print(f"[fig_architecture] wrote {pdf_path}")

    write_meta(
        NAME,
        params={
            "layers": ["External Interfaces", "Emulator Core", "Signal Models", "Output / Metrics"],
            "n_interfaces": len(iface_items),
            "n_core": len(core_items),
            "n_signal_models": len(sig_items),
        },
    )


if __name__ == "__main__":
    main()
