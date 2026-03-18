# Telegram Bot for Subtitle Translation

A Telegram bot that provides word tier lists and translations from TV series subtitles.

## Features

- Ask for a series name
- Returns word tier lists with translations
- Shows examples from the series
- Currently returns Fallout Episode 1 results (will be expanded)

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the bot:**
   ```bash
   python3 telegram_bot.py
   ```

## Usage

1. Start a chat with the bot on Telegram
2. Send `/start` to begin
3. The bot will ask: "What series do you want to translate?"
4. Currently, any response returns Fallout Episode 1 results

## Commands

- `/start` - Start the bot and get welcome message
- `/full` - Get the complete tier list

## Current Status

**Phase 1 (Current):**
- ✅ Bot asks for series name
- ✅ Returns Fallout Episode 1 results
- ✅ Shows top 10 words with translations
- ✅ Shows examples from series

**Phase 2 (Next):**
- ⏳ Use ChatGPT to normalize series name
- ⏳ Search for existing subtitles
- ⏳ Download subtitles if not found
- ⏳ Analyze and translate new series

## Bot Token

The bot token is configured in `telegram_bot.py`. Make sure to keep it secure.

## Testing

To test the bot:
1. Find your bot on Telegram (search for the bot username)
2. Send `/start`
3. Send any message (e.g., "Fallout")
4. You should receive Fallout Episode 1 tier list
