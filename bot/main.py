import logging
import os

from telegram.ext import Application

from backend.database import Database
from bot.config import Settings
from bot.handlers import BotContext, register_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def main() -> None:
    settings = Settings.from_env()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    database = Database(database_url)
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["context"] = BotContext(
        settings=settings,
        db_factory=lambda: next(database.get_session()),
    )
    register_handlers(application)
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
