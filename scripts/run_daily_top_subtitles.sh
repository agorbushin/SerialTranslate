#!/usr/bin/env bash
# Download up to 80 new subtitles per local day for a local popular-title list.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON:-python3}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

exec "$PYTHON_BIN" daily_trending_subtitles.py \
  --media all \
  --source local \
  --title-file config/top_subtitle_titles.json \
  --max-downloads "${MAX_DOWNLOADS:-80}" \
  --max-shows "${MAX_SHOWS:-20}" \
  --max-movies "${MAX_MOVIES:-40}" \
  --base-dir Subtitle \
  --state-file daily_subtitle_state.json \
  --plan-file daily_top_subtitle_plan.json \
  "$@"
