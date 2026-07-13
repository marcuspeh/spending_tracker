import structlog
from aiohttp import web

from app.config.settings import get_settings

logger = structlog.get_logger()


async def health_handler(request: web.Request) -> web.Response:
    """Return 200 OK if the bot and poller are still running.

    This handler is intentionally lightweight: it does not call the Telegram
    API, does not touch the database, and does not depend on any external
    service. It is a liveness signal only — proof that the asyncio event
    loop is alive and the long-running tasks are still scheduled.
    """
    bot = request.app.get("bot")
    poller = request.app.get("poller")

    healthy = True
    details: dict[str, bool] = {}

    if bot is not None:
        bot_alive = getattr(bot, "_running", False)
        details["bot"] = bot_alive
        healthy = healthy and bot_alive

    if poller is not None:
        poller_alive = getattr(poller, "_running", False)
        details["poller"] = poller_alive
        healthy = healthy and poller_alive

    status = 200 if healthy else 503
    return web.json_response({"healthy": healthy, "components": details}, status=status)


async def start_health_server(bot, poller) -> web.AppRunner:
    """Start the HTTP health server in the background.

    Returns the AppRunner so the caller can stop it on shutdown.
    """
    settings = get_settings()
    app = web.Application()
    app["bot"] = bot
    app["poller"] = poller
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.health_port)
    await site.start()
    logger.info("health_server_started", port=settings.health_port)
    return runner


async def stop_health_server(runner: web.AppRunner) -> None:
    """Stop the HTTP health server."""
    await runner.cleanup()
    logger.info("health_server_stopped")
