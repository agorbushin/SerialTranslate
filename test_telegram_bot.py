#!/usr/bin/env python3
"""
Minimal Telegram bot for API connectivity testing.

Usage:
  TELEGRAM_BOT_TOKEN=... python3 test_telegram_bot.py
"""

import os
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


try:
    from telegram_bot import TELEGRAM_BOT_TOKEN as DEFAULT_BOT_TOKEN
except Exception:
    DEFAULT_BOT_TOKEN = ""

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", DEFAULT_BOT_TOKEN).strip()


async def on_post_init(app: Application) -> None:
    """Runs once after app init; verifies Telegram API with getMe."""
    try:
        me = await app.bot.get_me()
        print(
            f"[{datetime.now().isoformat(timespec='seconds')}] Connected as @{me.username} (id={me.id})",
            flush=True,
        )
    except Exception as e:
        # Do not fail startup here; polling bootstrap retries will continue.
        print(
            f"[{datetime.now().isoformat(timespec='seconds')}] getMe check failed at startup: {e}",
            flush=True,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Test bot is alive. Send /ping.")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    await update.message.reply_text(f"echo: {text}")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("Missing TELEGRAM_BOT_TOKEN env var.", flush=True)
        raise SystemExit(1)

    print(
        f"[{datetime.now().isoformat(timespec='seconds')}] Starting minimal test bot...",
        flush=True,
    )
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(on_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.run_polling(allowed_updates=Update.ALL_TYPES, bootstrap_retries=-1)


if __name__ == "__main__":
    main()
