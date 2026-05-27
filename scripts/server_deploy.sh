#!/usr/bin/env bash
# Run ON the server inside the repo root (e.g. /root/SerialTranslate).
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

echo "==> git pull"
git pull origin main

if [[ -d .venv ]]; then
  echo "==> pip install"
  .venv/bin/python -m pip install -U pip
  .venv/bin/pip install -U python-telegram-bot openai requests yt-dlp
fi

if systemctl list-unit-files serialtranslate-bot.service &>/dev/null; then
  echo "==> restart systemd"
  systemctl restart serialtranslate-bot.service
  systemctl status serialtranslate-bot.service --no-pager || true
else
  echo "No serialtranslate-bot.service — start manually:"
  echo "  cd $REPO_ROOT && source .venv/bin/activate && python3 telegram_bot.py"
fi

echo "==> done"
