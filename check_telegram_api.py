#!/usr/bin/env python3
"""
One-shot Telegram API check (no polling). Uses .env via env_config.

Usage:
  python3 check_telegram_api.py
"""
from __future__ import annotations

import asyncio
import sys

import env_config  # noqa: F401 — loads .env
import os


async def main() -> int:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("FAIL: TELEGRAM_BOT_TOKEN missing (set in .env)", flush=True)
        return 1
    try:
        from telegram import Bot
    except ImportError:
        print("FAIL: install python-telegram-bot (pip install python-telegram-bot)", flush=True)
        return 1

    try:
        bot = Bot(token)
        me = await bot.get_me()
    except Exception as e:
        print(f"FAIL: Telegram API error: {type(e).__name__}: {e}", flush=True)
        return 1

    print(f"OK: @{me.username} (id={me.id})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
