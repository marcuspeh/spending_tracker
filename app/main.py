import asyncio
import signal

from app.config.settings import get_settings
from app.database.session import close_db, init_db
from app.health.server import start_health_server, stop_health_server
from app.logging_setup import client, setup_logging, shutdown_logging
from app.poller.gmail import GmailPoller
from app.services.tags_provider import (
    init_tags_provider,
    reset_tags_provider,
)
from app.telegram.bot import TelegramBot

setup_logging()
log = client()


async def main():
    """Main entry point."""
    settings = get_settings()
    log.info("app_starting timezone=%s", settings.timezone)

    await init_db()

    # Live tag set owned by config_store. Outages are non-fatal — the
    # provider falls back to the hard-coded list and self-heals once
    # config_store becomes reachable again.
    tags_provider = init_tags_provider()
    await tags_provider.start()

    bot = TelegramBot()
    poller = GmailPoller(telegram_bot=bot)

    shutdown_event = asyncio.Event()

    def signal_handler(sig):
        log.info("signal_received signal=%s", sig)
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, lambda s=sig: signal_handler(s))

    health_runner = await start_health_server(bot, poller)
    poller_task = asyncio.create_task(poller.start())
    bot_task = asyncio.create_task(bot.start())

    log.info("app_running")
    await shutdown_event.wait()

    log.info("app_stopping")
    await poller.stop()
    await bot.stop()
    await asyncio.gather(poller_task, bot_task, return_exceptions=True)
    await stop_health_server(health_runner)
    await tags_provider.stop()
    reset_tags_provider()
    await close_db()

    log.info("app_stopped")
    shutdown_logging()


if __name__ == "__main__":
    asyncio.run(main())
