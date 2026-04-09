#!/usr/bin/env bash
# Shared helper: if diff between two refs touches Python or dependency files, restart the bot.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT"
old_ref="${1:-}"
new_ref="${2:-}"
[[ -n "$old_ref" && -n "$new_ref" ]] || exit 0
git rev-parse --verify "$old_ref" >/dev/null 2>&1 || exit 0
git rev-parse --verify "$new_ref" >/dev/null 2>&1 || exit 0
if [[ "$(git rev-parse "$old_ref")" == "$(git rev-parse "$new_ref")" ]]; then
  exit 0
fi
if git diff --name-only "$old_ref" "$new_ref" | grep -qE '\.py$|(^|/)requirements\.txt$|(^|/)pyproject\.toml$'; then
  echo "[SerialTranslate] Code or dependency files changed; restarting bot..."
  exec "$ROOT/restart_bot.sh"
fi
