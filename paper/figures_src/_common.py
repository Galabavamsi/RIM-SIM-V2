"""Shared helpers for paper figure scripts.

Each `fig_*.py` script under `paper/figures_src/` should:
  - actually drive the `ris_sim.core.engine.Simulation` (no canned numpy data),
  - write a PDF to `paper/figures/<name>.pdf`,
  - write the underlying numbers to `paper/figures_data/<name>.csv`,
  - write a sidecar `paper/figures_data/<name>.meta.json` with seed + commit + params,
so reviewers can re-run and verify.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib as mpl
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = REPO_ROOT / "paper" / "figures"
DATA_DIR = REPO_ROOT / "paper" / "figures_data"
FIG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Make `import ris_sim` work whether or not the package is pip-installed.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def use_paper_style() -> None:
    """Apply a consistent serif, conference-ready matplotlib style."""
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 10,
            "axes.labelsize": 10,
            "axes.titlesize": 11,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "axes.grid": True,
            "grid.alpha": 0.3,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def write_meta(name: str, params: dict[str, Any]) -> Path:
    """Write `<name>.meta.json` next to the figure CSV with reproducibility info."""
    meta = {
        "figure": name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "python": sys.version.split()[0],
        "params": params,
    }
    path = DATA_DIR / f"{name}.meta.json"
    path.write_text(json.dumps(meta, indent=2))
    return path


def save_pdf(fig: plt.Figure, name: str) -> Path:
    path = FIG_DIR / f"{name}.pdf"
    fig.savefig(path)
    plt.close(fig)
    return path
