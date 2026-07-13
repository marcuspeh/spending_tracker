import sys

import httpx
import structlog

from app.config.settings import get_settings

logger = structlog.get_logger()


def healthcheck() -> int:
    """Probe the in-process HTTP /health endpoint.

    The health server is started by `app.main` alongside the bot and poller.
    This CLI is a thin wrapper that does an HTTP GET and exits 0 on 200,
    non-zero otherwise. It does NOT contact the Telegram API and does NOT
    touch the database — those are not signals of whether the container
    is healthy, only signals of whether external services happen to be
    reachable right now.

    Returns:
        0 on success, non-zero on failure.
    """
    settings = get_settings()
    url = f"http://127.0.0.1:{settings.health_port}/health"

    try:
        response = httpx.get(url, timeout=5.0)
    except httpx.RequestError as e:
        logger.error("healthcheck_failed", step="connect", error=str(e))
        print(f"ERROR: Cannot reach health server at {url}: {e}", file=sys.stderr)
        return 1

    if response.status_code == 200:
        logger.info("healthcheck_success", payload=response.json())
        print("Healthcheck passed")
        return 0

    logger.error("healthcheck_failed", status=response.status_code, body=response.text)
    print(
        f"ERROR: Health endpoint returned {response.status_code}: {response.text}",
        file=sys.stderr,
    )
    return 1
