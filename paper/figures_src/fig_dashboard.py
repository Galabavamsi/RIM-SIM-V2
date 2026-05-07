"""Figure A6 - Real dashboard screenshot (replaces the old matplotlib mock).

Spins up the FastAPI dashboard in-process, drives it with a headless Chromium
via Playwright, captures three views, and assembles them into a single
publication-ready PDF:

    (a) Configuration tab — Scenario Library cards on top
    (b) Results tab — populated after running the Quickstart scenario
    (c) Room Topology tab — TX/RX/RIS placement visualization

All three are real screenshots of the live dashboard, not a matplotlib mock.

Output:
    paper/figures/dashboard.pdf
    paper/figures_data/dashboard_*.png  (raw screenshots)
    paper/figures_data/dashboard.meta.json
"""

from __future__ import annotations

import threading
import time
from io import BytesIO

import matplotlib.image as mpimg
import matplotlib.pyplot as plt

from paper.figures_src._common import (
    DATA_DIR,
    save_pdf,
    use_paper_style,
    write_meta,
)

NAME = "dashboard"
PORT = 8780
VIEWPORT = (1700, 950)


def _start_server() -> threading.Thread:
    import uvicorn
    from ris_sim.web.app import app

    def run() -> None:
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(2.0)
    return t


def _capture_three_views(out_dir) -> dict[str, str]:
    """Open the dashboard, drive it to capture three representative views.
    Uses the Indoor Corridor scenario because its 10x3x3 m layout reads
    cleanly in the 3D topology view.
    Returns dict of view name -> PNG path."""
    from playwright.sync_api import sync_playwright

    paths: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]})
        page.goto(f"http://127.0.0.1:{PORT}", wait_until="domcontentloaded")
        # Three.js + WebSocket connect — wait without depending on networkidle
        time.sleep(3.5)

        # Load the Indoor Corridor scenario, populating both forms and 3D
        page.evaluate('useScenario("indoor_corridor_2.4ghz", false)')
        time.sleep(0.8)

        # (a) Configuration tab — cards on top + form editor populated
        page.click('.tab-bar button[data-tab="config"]')
        time.sleep(0.5)
        cfg_path = str(out_dir / "dashboard_config.png")
        page.screenshot(path=cfg_path)
        paths["config"] = cfg_path
        print(f"  [config] saved {cfg_path}")

        # Run the Indoor Corridor scenario for Results
        page.evaluate('startSimulation()')
        time.sleep(3.0)

        page.click('.tab-bar button[data-tab="results"]')
        time.sleep(1.0)
        res_path = str(out_dir / "dashboard_results.png")
        page.screenshot(path=res_path)
        paths["results"] = res_path
        print(f"  [results] saved {res_path}")

        # (c) Topology tab in 3D mode (the new feature)
        page.click('.tab-bar button[data-tab="topology"]')
        time.sleep(0.5)
        page.click('#topo-3d-btn')
        time.sleep(2.5)  # let Three.js render a few frames before screenshot
        topo_path = str(out_dir / "dashboard_topology.png")
        page.screenshot(path=topo_path)
        paths["topology"] = topo_path
        print(f"  [topology] saved {topo_path}")

        browser.close()
    return paths


def _assemble_pdf(paths: dict[str, str]) -> None:
    use_paper_style()
    # 3-row layout so each screenshot keeps its 16:9-ish aspect.
    # Top row: full-width Configuration (the hero shot).
    # Middle row: Results (also wide).
    # Bottom row: Topology (wide).
    fig = plt.figure(figsize=(11.5, 14.0))
    gs = fig.add_gridspec(
        3, 1, hspace=0.18,
        left=0.02, right=0.98, top=0.955, bottom=0.01,
    )

    panels = [
        (paths["config"],
         "(a) Configuration — Scenario Library cards on top, "
         "form-based editor (Form/JSON toggle per panel) below"),
        (paths["results"],
         "(b) Results — Constellation, Channel breakdown (LOS/RIS/Total), "
         "FFT spectrum, Room heatmap"),
        (paths["topology"],
         "(c) Topology — interactive 3D view (orbit / pan / zoom) with "
         "wireframe room, TX/RX nodes and RIS panel"),
    ]
    for i, (img_path, title) in enumerate(panels):
        ax = fig.add_subplot(gs[i, 0])
        ax.imshow(mpimg.imread(img_path))
        ax.set_title(title, fontsize=10, pad=6, loc="left")
        ax.axis("off")

    fig.suptitle(
        "RIS-SIM v2 web dashboard — live screenshots via headless Chromium",
        fontsize=12,
        fontweight="bold",
        y=0.985,
    )
    pdf_path = save_pdf(fig, NAME)
    print(f"[fig_dashboard] wrote {pdf_path}")


def main() -> None:
    print("[fig_dashboard] starting in-process FastAPI server")
    _start_server()
    print(f"[fig_dashboard] capturing 3 views via headless Chromium")
    paths = _capture_three_views(DATA_DIR)
    print("[fig_dashboard] assembling combined PDF")
    _assemble_pdf(paths)
    write_meta(
        NAME,
        params={
            "viewport": list(VIEWPORT),
            "screenshots": list(paths.keys()),
            "browser": "Chromium (Playwright)",
            "panels": {
                "a_config": "Configuration tab with scenario library cards",
                "b_results": "Results after running Quickstart scenario",
                "c_topology": "Room topology view",
            },
        },
    )


if __name__ == "__main__":
    main()
