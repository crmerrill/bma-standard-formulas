#!/usr/bin/env bash
# Rebuild the Waterfall IR Design PDF from the markdown source.
#
# Requirements:
#   - pandoc (brew install pandoc)
#   - weasyprint (pip install weasyprint, plus brew install pango cairo)
#
# On macOS WeasyPrint can't find pango by default; we set
# DYLD_FALLBACK_LIBRARY_PATH to /opt/homebrew/lib so it picks up the
# Homebrew-installed native libs.
#
# Usage:
#   scripts/build_design_pdf.sh
#
# Output:
#   docs/architecture/waterfall_ir_design.pdf

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/docs/architecture/waterfall_ir_design.md"
DST="$REPO_ROOT/docs/architecture/waterfall_ir_design.pdf"
CSS="$REPO_ROOT/docs/architecture/_pdf_style.css"
TPL="$REPO_ROOT/docs/architecture/_pdf_template.html"

if [[ ! -f "$SRC" ]]; then
  echo "ERROR: source markdown not found: $SRC" >&2
  exit 1
fi

# WeasyPrint warnings about libpango paths on macOS — silenced; PDF still builds.
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib pandoc "$SRC" \
  -o "$DST" \
  --pdf-engine=weasyprint \
  --template="$TPL" \
  --css="$CSS" \
  -s --toc --toc-depth=3 \
  --highlight-style=tango \
  --metadata title="Waterfall IR Design" \
  --metadata subtitle="Research notes + IR reference" \
  --metadata author="BMA Standard Formulas" \
  --metadata date="$(date '+%B %d, %Y')" \
  2>&1 | grep -v "GLib" | grep -v "^$" || true

echo "Built: $DST"
ls -lh "$DST"
