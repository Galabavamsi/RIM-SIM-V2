"""Regenerate every paper figure from the engine.

Each figure script under ``paper/figures_src/`` is fully self-contained and
writes a PDF + CSV + meta.json. Run with::

    python -m paper.figures_src.run_all

or::

    python paper/figures_src/run_all.py
"""

from __future__ import annotations

import importlib
import sys
import time
import traceback

FIGURES = [
    ("A1", "fig_polar_grid",       "paper/figures/polar_grid_validation.pdf"),
    ("A2", "fig_cfo_validation",   "paper/figures/cfo_validation.pdf"),
    ("A3", "fig_emulation_time",   "paper/figures/emulation_time.pdf"),
    ("A4", "fig_snr_cdf",          "paper/figures/snr_cdf.pdf"),
    ("A5", "fig_fm_coverage",      "paper/figures/fm_coverage.pdf"),
    ("A6", "fig_dashboard",        "paper/figures/dashboard.pdf"),
]


def main() -> int:
    started = time.time()
    failures: list[tuple[str, str, str]] = []

    for tag, name, output in FIGURES:
        print(f"\n{'=' * 72}\n  [{tag}]  {name}\n{'=' * 72}")
        t0 = time.time()
        try:
            mod = importlib.import_module(f"paper.figures_src.{name}")
            mod.main()
        except Exception as e:
            failures.append((tag, name, f"{type(e).__name__}: {e}"))
            traceback.print_exc()
            continue
        dt = time.time() - t0
        print(f"\n  [{tag}]  done in {dt:.1f} s  ->  {output}")

    print(f"\n{'=' * 72}")
    print(f"  TOTAL  {len(FIGURES) - len(failures)}/{len(FIGURES)} figures generated  "
          f"in {time.time() - started:.1f} s")
    if failures:
        print(f"  {len(failures)} failure(s):")
        for tag, name, err in failures:
            print(f"    [{tag}] {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
