#!/usr/bin/env bash
# Build a self-contained zip of Atif Assistant for offline install/run.
#
# The zip excludes private data (data/), the virtualenv and git metadata, so it
# is safe to copy to a phone or another machine. The recipient unpacks it and
# runs ./run.sh (first run creates .venv and installs from requirements.lock).
set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="dist"
STAMP="$(date +%Y%m%d)"
ZIP="${OUT_DIR}/atif-assistant-offline-${STAMP}.zip"

mkdir -p "$OUT_DIR"
rm -f "$ZIP"

zip -r "$ZIP" \
  atif_assistant \
  web \
  tests \
  scripts \
  docs \
  run.sh \
  pyproject.toml \
  requirements.lock \
  README.md \
  AGENTS.md \
  .env.example \
  -x "*/__pycache__/*" "*.pyc" "*/__pycache__" \
  >/dev/null

SIZE="$(du -h "$ZIP" | cut -f1)"
echo "Built ${ZIP} (${SIZE})"
unzip -l "$ZIP" | tail -1
