# Paper Compilation Instructions

This directory contains the RIS-SIM v2 paper for submission to CAISc 2026.

## Files

- `paper.tex` — Main LaTeX document
- `generate_figures.py` — Script to regenerate all figures
- `figures/` — Generated PDF figures

## Compilation

1. Download `caisc_2026.sty` from https://caisc2026.github.io/cfp.html
2. Place it in this directory
3. Compile with:
```bash
pdflatex paper.tex
pdflatex paper.tex  # second pass for references
```

## Regenerate Figures

```bash
python generate_figures.py
```
