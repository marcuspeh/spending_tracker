import asyncio
import signal

import structlog

from app.config.settings import get_settings
from app.database.session import close_db, init_db
from app.health.server import start_health_server, stop_health_server
from app.poller.gmail import GmailPoller
from app.telegram.bot import TelegramBot

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def main():
    """Main entry point."""
    settings = get_settings()
    logger.info("app_starting", timezone=settings.timezone)

    # Initialize database
    await init_db()

    # Create poller and bot
    poller = GmailPoller()
    bot = TelegramBot()

    # Handle shutdown signals
    shutdown_event = asyncio.Event()

    def signal_handler(sig):
        logger.info("signal_received", signal=sig)
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_event_loop().add_signal_handler(sig, lambda s=sig: signal_handler(s))

    # Start the health server first so probes can succeed as soon as the
    # bot and poller are scheduled.
    health_runner = await start_health_server(bot, poller)

    # Start services
    poller_task = asyncio.create_task(poller.start())
    bot_task = asyncio.create_task(bot.start())

    logger.info("app_running")

    # Wait for shutdown
    await shutdown_event.wait()

    logger.info("app_stopping")

    # Stop services
    await poller.stop()
    await bot.stop()

    # Wait for tasks to complete
    await asyncio.gather(poller_task, bot_task, return_exceptions=True)

    # Stop the health server
    await stop_health_server(health_runner)

    # Close database connections
    await close_db()

    logger.info("app_stopped")


if __name__ == "__main__":
    asyncio.run(main())
