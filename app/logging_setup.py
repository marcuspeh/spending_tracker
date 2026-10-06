"""Logging setup and accessor for the logging-system SDK.

Centralised entry point for every log call in the app. Callers use the
returned :func:`client` (a thin facade over ``loggingsdk.Client``) instead
of structlog or ``logging.getLogger(__name__)`` so all events flow through
the Kafka pipeline configured for this service.

Three safety nets:

* If the SDK can't be imported (e.g. running tests without the SDK
  installed), every ``client.info(...)`` call is a no-op.
* If Kafka is unreachable, the SDK's async queue drops the oldest and the
  call still returns immediately.
* Third-party log records (tortoise, httpx, python-telegram-bot) reach
  Kafka via :class:`loggingsdk.LoggingHandler`, which
  :func:`setup_logging` attaches to the root logger.

Note that ``client.info(...)`` is dispatched straight to the producer and
does not go through the root logger, so the app's own events do not
appear on stderr — only third-party ones do. Set ``LOG_DISABLED=1`` to
run with stderr output locally.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterable, Iterator, Optional

from app.config.settings import get_settings

if TYPE_CHECKING:
    from app.config.settings import Settings

try:
    import loggingsdk
    from loggingsdk import (
        Client,
        LoggingHandler,
        ParseLevel,
        log_id_var,
        new_log_id,
    )
except Exception:  # pragma: no cover - SDK unavailable
    loggingsdk = None  # type: ignore[assignment]
    Client = None  # type: ignore[assignment]
    LoggingHandler = None  # type: ignore[assignment]
    ParseLevel = None  # type: ignore[assignment]
    log_id_var = None  # type: ignore[assignment]
    new_log_id = None  # type: ignore[assignment]


_client_instance: Optional["loggingsdk.Client"] = None
"""The shared loggingsdk.Client. ``None`` when the SDK is unavailable or
``log_disabled`` is set."""


class _NullClient:
    """Drop-in replacement for ``loggingsdk.Client`` when the SDK is
    unavailable or disabled. Every method is a no-op so callers can use
    ``client.info(...)`` unconditionally.
    """

    @property
    def project(self) -> str:  # pragma: no cover - read for tests
        return ""

    def debug(self, *_args, **_kwargs) -> None: pass
    def info(self, *_args, **_kwargs) -> None: pass
    def warn(self, *_args, **_kwargs) -> None: pass
    def error(self, *_args, **_kwargs) -> None: pass
    def fatal(self, *_args, **_kwargs) -> None: pass
    def close(self, *_args, **_kwargs) -> None: pass


def setup_logging() -> Optional["loggingsdk.Client"]:
    """Configure stdlib ``logging`` and build the SDK client.

    Returns the constructed :class:`loggingsdk.Client` (or ``None`` if
    the SDK is disabled). Idempotent — calling it twice returns the
    existing client.
    """
    global _client_instance

    settings = get_settings()

    # Stderr first so we always have *some* output, even if the SDK
    # can't be imported or Kafka isn't reachable yet.
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        ),
    )
    _install_filters(stderr_handler, settings)

    root = logging.getLogger()
    root.setLevel(_parse_level(settings.log_level))
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(stderr_handler)

    if settings.log_disabled or loggingsdk is None:
        return None

    if _client_instance is None:
        _client_instance = Client(
            bootstrap=settings.log_kafka_brokers,
            project=settings.log_project,
            topic=settings.log_topic,
            async_capacity=settings.log_async_capacity,
            flush_interval=settings.log_flush_interval,
            min_level=ParseLevel(settings.log_level.upper())[0],
        )

    # The handler is re-checked (not just added once) because the stderr
    # handler above clears root.handlers on every call — a module-level
    # ``client()`` during import can therefore strip a handler installed
    # by an earlier call.
    if not any(isinstance(h, LoggingHandler) for h in root.handlers):
        kafka_handler = LoggingHandler(_client_instance)
        _install_filters(kafka_handler, settings)
        root.addHandler(kafka_handler)
    return _client_instance


def client():
    """Return the shared SDK client (constructing one on first call).

    Falls back to a :class:`_NullClient` when the SDK is disabled or
    unavailable, so call sites never need to guard against ``None``.
    """
    if _client_instance is None:
        setup_logging()
    return _client_instance if _client_instance is not None else _NullClient()


def shutdown_logging() -> None:
    """Flush + close the SDK. Safe to call when the SDK is disabled."""
    global _client_instance
    if _client_instance is not None:
        try:
            _client_instance.close()
        finally:
            _client_instance = None


@contextmanager
def correlation_id(log_id: str | None = None) -> Iterator[str]:
    """Bind the SDK's correlation id for the duration of the block.

    Counterpart to config_store's ``CorrelationIdMiddleware``, which does
    the same thing per HTTP request. This service has no inbound request
    pipeline, so correlation is scoped to a unit of work instead — the
    poll cycle and each individual email. Every event logged inside the
    block carries the same ``logid``, so the logging collector can show
    the whole trace (fetch → parse → tag → insert → notify).

    Args:
        log_id: Reuse an existing id (e.g. the per-cycle id when scoping
            a single email). When omitted a fresh one is minted.

    Yields:
        The id in force for the block, so callers can include it in
        their own log lines. Yields ``"unknown"`` when the SDK is
        unavailable, which keeps callers free of None-checks.
    """
    if log_id is None:
        log_id = new_log_id() if new_log_id is not None else "unknown"

    if log_id_var is None:
        yield log_id
        return

    token = log_id_var.set(log_id)
    try:
        yield log_id
    finally:
        log_id_var.reset(token)


#: Settings whose values must never reach the log pipeline. The Telegram
#: bot token in particular leaks by default: python-telegram-bot talks to
#: ``https://api.telegram.org/bot<token>/getUpdates`` over httpx, and
#: httpx logs the full URL at INFO on the ``httpx`` logger, so the token
#: lands in Kafka in plaintext.
_REDACTED_SETTINGS = (
    "telegram_bot_token",
    "imap_password",
    "mysql_password",
    "llm_api_key",
)

REDACTED = "[REDACTED]"

#: Secrets shorter than this are not redacted. A 1-2 character password
#: would otherwise match that substring inside ordinary words and mangle
#: every line ("https" -> "htt[REDACTED]s"). Real credentials are long, so
#: anything this short is treated as unset.
_MIN_REDACTABLE_LEN = 8

#: Liveness endpoint served by ``app.health.server``. Kept here so the
#: access-log filter and the health server agree on the path.
HEALTH_PATH = "/health"


class RedactSecretsFilter(logging.Filter):
    """Replace known secret values with :data:`REDACTED`.

    Records that contain no secret short-circuit after a single substring
    check each, so the common case stays cheap.

    Attached to both the stderr handler and the SDK's
    :class:`~loggingsdk.LoggingHandler` so nothing escapes to Kafka.
    """

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        # Empty values would redact the empty string everywhere; values
        # too short to be real credentials would corrupt unrelated text.
        self._secrets = tuple(
            s for s in secrets if s and len(s) >= _MIN_REDACTABLE_LEN
        )

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True

        message = record.getMessage()
        if not any(secret in message for secret in self._secrets):
            return True

        for secret in self._secrets:
            message = message.replace(secret, REDACTED)

        # Rewrite rather than mutate: the same record can be handed to
        # several handlers (stderr + Kafka) and each needs the redacted
        # text, but getMessage() re-derives from msg/args every call.
        record.msg = message
        record.args = None
        return True


class DropHealthAccessFilter(logging.Filter):
    """Drop log records describing a ``/health`` request.

    The Docker healthcheck probes ``/health`` every 60s, which would
    otherwise emit ~1,440 events a day across two loggers:

    * ``aiohttp.access`` — the server-side access line, and
    * ``httpx`` — the probe's own client-side "HTTP Request: GET ..." line.

    Both are noise for a liveness check, so both are dropped. Other paths
    are untouched, so genuine traffic stays visible.
    """

    #: Loggers whose records describe an HTTP round trip. Only these are
    #: inspected; application logs that merely mention /health are kept.
    _HTTP_LOGGERS = frozenset({"aiohttp.access", "httpx", "httpcore"})

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name not in self._HTTP_LOGGERS:
            return True
        return HEALTH_PATH not in record.getMessage()


def _install_filters(handler: logging.Handler, settings: "Settings") -> None:
    """Attach the redaction + health filters to ``handler``.

    Filters must live on the *handler*, not the root logger: stdlib only
    runs a logger's own filters for records logged directly to it, so a
    filter on root never sees records that ``httpx`` or
    ``aiohttp.access`` emit — exactly the ones that leak.
    """
    secrets = [getattr(settings, name, "") for name in _REDACTED_SETTINGS]
    handler.addFilter(RedactSecretsFilter(secrets))
    handler.addFilter(DropHealthAccessFilter())


def _parse_level(name: str) -> int:
    """Map a level name (case-insensitive) to a stdlib level constant."""
    return {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "FATAL": logging.CRITICAL,
        "CRITICAL": logging.CRITICAL,
    }.get(name.upper(), logging.INFO)
