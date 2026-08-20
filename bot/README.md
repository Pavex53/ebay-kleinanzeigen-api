# Telegram Bot

Start it from the repository root after installing the backend and bot dependencies:

```bash
export DATABASE_URL='postgresql://user:password@localhost:5432/kleinanzeigen_saas'
export TELEGRAM_BOT_TOKEN='replace-me'
export BACKEND_URL='http://localhost:8000'
python -m bot.main
```

Never commit a Telegram bot token. If it was posted in a chat, rotate it immediately via BotFather and update your local `.env` / server secret.
