#!/usr/bin/env bash
# Stop then start telegram_bot.py in the background (append to bot.log).
# Repo-root .env is loaded inside Python (env_config); this check uses the same rules.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if ! python3 -c "import env_config; import os, sys; sys.exit(0 if (os.environ.get('TELEGRAM_BOT_TOKEN') or '').strip() else 1)"; then
  echo "restart_bot.sh: TELEGRAM_BOT_TOKEN is missing." >&2
  echo "Add it to $ROOT/.env (copy from .env.example) or export TELEGRAM_BOT_TOKEN in your shell." >&2
  exit 1
fi
"$ROOT/stop_bot.sh"
sleep 2
nohup python3 "$ROOT/telegram_bot.py" >>"$ROOT/bot.log" 2>&1 &
echo "Bot started in background (PID $!). Log: $ROOT/bot.log"
