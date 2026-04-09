#!/usr/bin/env bash
# Stop the Telegram bot (all matching processes).
set -euo pipefail
pkill -f telegram_bot.py 2>/dev/null || true
