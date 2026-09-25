#!/usr/bin/env bash
# Build the manuscript. Regenerates tables and figures first, so the PDF can
# never quote a number that no longer matches the artifacts.
#
# Uses a TeX Live container when pdflatex is not installed locally.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> regenerating tables from artifacts"
python make_tables.py

echo "==> regenerating figures from artifacts"
python make_figures.py

echo "==> compiling"
if command -v pdflatex >/dev/null 2>&1; then
  pdflatex -interaction=nonstopmode -halt-on-error vitalsync_ieee.tex >/dev/null
  pdflatex -interaction=nonstopmode -halt-on-error vitalsync_ieee.tex >/dev/null
else
  echo "    pdflatex not found locally; using the texlive container"
  # MSYS_NO_PATHCONV stops Git Bash on Windows from rewriting /work into a
  # Windows path before Docker sees it.
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$(pwd -W 2>/dev/null || pwd):/work" -w /work \
    texlive/texlive:latest sh -c \
    "pdflatex -interaction=nonstopmode -halt-on-error vitalsync_ieee.tex >/dev/null && \
     pdflatex -interaction=nonstopmode -halt-on-error vitalsync_ieee.tex >/dev/null"
fi

if grep -q "undefined" vitalsync_ieee.log 2>/dev/null; then
  echo "    WARNING: unresolved references remain (see vitalsync_ieee.log)"
fi

pages=$(grep -o "Output written on vitalsync_ieee.pdf ([0-9]* pages" vitalsync_ieee.log \
        | grep -o "[0-9]*" | head -1)
echo "==> done: $(pwd)/vitalsync_ieee.pdf (${pages:-?} pages)"
