# Bot Management Guide

## Starting the Bot

```bash
python3 telegram_bot.py
```

Or run in background:
```bash
nohup python3 telegram_bot.py > bot.log 2>&1 &
```

## Stopping the Bot

### Method 1: Using the stop script (Recommended)
```bash
./stop_bot.sh
```

### Method 2: Find and kill manually
```bash
# Find the process
ps aux | grep telegram_bot.py

# Kill by PID (replace XXXX with the actual PID)
kill XXXX

# Or kill all matching processes
pkill -f telegram_bot.py

# Force kill if needed
pkill -9 -f telegram_bot.py
```

### Method 3: Using process name
```bash
# Graceful termination
pkill -f telegram_bot.py

# Force termination
pkill -9 -f telegram_bot.py
```

## Checking if Bot is Running

```bash
ps aux | grep telegram_bot.py | grep -v grep
```

If you see output, the bot is running. If no output, the bot is not running.

## Viewing Bot Logs

If running in background with nohup:
```bash
tail -f bot.log
```

## Restarting the Bot

1. Stop the bot:
   ```bash
   ./stop_bot.sh
   ```

2. Start the bot:
   ```bash
   python3 telegram_bot.py
   ```

Or in one command:
```bash
./stop_bot.sh && python3 telegram_bot.py
```

## Troubleshooting

### Bot won't stop
If the bot doesn't stop with `pkill`, use force kill:
```bash
pkill -9 -f telegram_bot.py
```

### Multiple instances running
Check for multiple instances:
```bash
ps aux | grep telegram_bot.py | grep -v grep
```

Kill all instances:
```bash
pkill -9 -f telegram_bot.py
```

### Port already in use
The Telegram bot uses polling, so it shouldn't have port conflicts. If you see errors, make sure no other instance is running.
