import asyncio

import structlog
from telegram.ext import Application, CommandHandler

from app.config.settings import get_settings
from app.telegram.auth import auth_middleware
from app.telegram.handlers import (
    add_handler,
    confirm_handler,
    delete_handler,
    edit_handler,
    help_handler,
    latest_handler,
    month_handler,
    ping_handler,
    range_handler,
    search_handler,
    start_handler,
    today_handler,
    week_handler,
)

logger = structlog.get_logger()


class TelegramBot:
    """Telegram bot for expense tracking."""

    def __init__(self):
        self.settings = get_settings()
        self._app: Application | None = None
        self._running = False

    async def start(self) -> None:
        """Start the Telegram bot."""
        # Load whitelist
        await auth_middleware.load_whitelist()

        self._app = Application.builder().token(
            self.settings.telegram_bot_token
        ).build()

        # Register handlers
        self._app.add_handler(CommandHandler("start", start_handler))
        self._app.add_handler(CommandHandler("help", help_handler))
        self._app.add_handler(CommandHandler("ping", ping_handler))
        self._app.add_handler(CommandHandler("latest", latest_handler))
        
        self._app.add_handler(CommandHandler("today", today_handler))
        self._app.add_handler(CommandHandler("week", week_handler))
        self._app.add_handler(CommandHandler("thismonth", month_handler))
        self._app.add_handler(CommandHandler("range", range_handler))
        self._app.add_handler(CommandHandler("search", search_handler))
        self._app.add_handler(CommandHandler("add", add_handler))
        self._app.add_handler(CommandHandler("edit", edit_handler))
        self._app.add_handler(CommandHandler("delete", delete_handler))
        self._app.add_handler(CommandHandler("confirm", confirm_handler))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        self._running = True

        logger.info("telegram_bot_started")

        # Run until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        if self._app:
            await self._app.updater.stop_polling()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("telegram_bot_stopped")
