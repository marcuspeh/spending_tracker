"""Live tag-set provider backed by the sibling config_store service.

The list of tags the LLM is allowed to return is owned by config_store
(MongoDB → MySQL cache → HTTP). At boot we spin up a :class:`TagsProvider`
which polls config_store every ``config_store_poll_seconds`` and rebuilds
an in-memory tuple of tag strings whenever the underlying comma-separated
value changes.

When config_store is unreachable or returns something we can't parse, the
provider stays on :data:`FALLBACK_TAGS` (the original hard-coded list) so
the rest of the system keeps working offline. The watcher keeps retrying
in the background, so a transient outage is self-healing.

The provider exposes a synchronous ``current()`` accessor for the
in-memory tuple and an async ``start()`` / ``stop()`` lifecycle to start
and stop the polling task. Lifecycle is wired from :func:`app.main.main`.
"""

from __future__ import annotations

import logging
from typing import Final

from config_store import ClientWatcher, ConfigClient

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


#: Hard-coded fallback used when config_store is unreachable, hasn't been
#: polled yet, or returns something we can't parse. Kept identical to the
#: old :data:`app.services.categorizer.DEFAULT_TAGS` constant so existing
#: DB rows and cached tag values stay valid after the upgrade.
FALLBACK_TAGS: Final[tuple[str, ...]] = (
    "food",
    "coffee",
    "transport",
    "groceries",
    "shopping",
    "subscriptions",
    "health",
    "entertainment",
    "travel",
    "transfers",
    "fees",
    "gym",
    "refunds",
    "cash",
    "other",
)


def _parse_csv_tags(raw: str) -> tuple[str, ...] | None:
    """Parse a comma-separated tag string into a normalized tuple.

    Returns ``None`` if the result is empty or contains duplicates — the
    caller falls back to :data:`FALLBACK_TAGS` in that case so the LLM
    prompt never offers the user an empty or duplicated set.

    Whitespace around each token is stripped; empty tokens (e.g. trailing
    comma) are dropped.
    """
    if not raw:
        return None
    parts = tuple(p.strip().lower() for p in raw.split(","))
    parts = tuple(p for p in parts if p)
    if not parts:
        return None
    if len(set(parts)) != len(parts):
        return None
    return parts


class TagsProvider:
    """Holds the current allowed-tag tuple and the background watcher.

    Lifetime::

        provider = TagsProvider()
        await provider.start()           # begins polling config_store
        tags = provider.current()        # synchronous, cheap
        ...
        await provider.stop()            # cancel polling + close client
    """

    def __init__(self) -> None:
        self._tags: tuple[str, ...] = FALLBACK_TAGS
        self._client: ConfigClient | None = None
        self._watcher: ClientWatcher | None = None

    def current(self) -> tuple[str, ...]:
        """Return the current allowed-tag tuple.

        Always returns something usable: either the live value from
        config_store or :data:`FALLBACK_TAGS`. Never raises.
        """
        return self._tags

    async def start(self) -> None:
        """Build the SDK client and start polling config_store.

        Always succeeds — config_store outages are non-fatal because the
        provider already has :data:`FALLBACK_TAGS` ready and the SDK's
        :class:`ClientWatcher` logs and retries on every tick.
        """
        settings = get_settings()
        self._client = ConfigClient(
            project=settings.config_store_project,
            base_url=settings.config_store_url,
            cache_ttl=settings.config_store_poll_seconds,
        )

        # Try an eager first fetch so a healthy config_store applies
        # before the first poll tick (default 60s).
        initial_raw: str | None = None
        try:
            initial_raw = await self._client.get(settings.config_store_tags_key)
        except Exception as exc:  # noqa: BLE001
            # Outages (connection errors, timeouts, 5xx, anything the
            # SDK or transport raises) must not block startup. We log
            # and let the watcher's background tick recover.
            logger.warning(
                "tags_provider_initial_fetch_failed err=%s fallback=%s",
                exc,
                list(FALLBACK_TAGS),
            )

        if initial_raw is not None:
            parsed = _parse_csv_tags(initial_raw)
            if parsed is not None:
                self._tags = parsed
                logger.info(
                    "tags_provider_started tags=%s source=config_store",
                    list(self._tags),
                )
            else:
                logger.warning(
                    "tags_provider_invalid_initial_payload raw=%r fallback=%s",
                    initial_raw,
                    list(FALLBACK_TAGS),
                )
        else:
            logger.info(
                "tags_provider_started tags=%s source=fallback",
                list(FALLBACK_TAGS),
            )

        # Always start the watcher so we self-heal after a transient
        # outage or invalid initial payload. ``ClientWatcher.new``
        # raises on the first fetch, so we drive construction manually
        # and seed it with the value we already have (or the fallback).
        self._watcher = ClientWatcher(
            config_type=TagsConfig,
            init_client=_build_tags,
            client=self._client,
            key=settings.config_store_tags_key,
            poll_interval=settings.config_store_poll_seconds,
            initial_value=self._tags,
            initial_raw=initial_raw,
        )
        self._watcher.start()

    async def stop(self) -> None:
        """Cancel polling and close the underlying SDK client."""
        if self._watcher is not None:
            try:
                await self._watcher.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("tags_provider_watcher_close_failed err=%s", exc)
            self._watcher = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("tags_provider_client_close_failed err=%s", exc)
            self._client = None


# --------------------------------------------------------------------- #
# SDK integration helpers
# --------------------------------------------------------------------- #


class TagsConfig:
    """Typed shape used by :class:`config_store.ClientWatcher`.

    The SDK parses the config_store JSON payload into this object and
    hands it to ``_build_tags`` to construct the live tags tuple.
    """

    def __init__(self, tags: str) -> None:
        self.tags = tags


async def _build_tags(client: ConfigClient, cfg: TagsConfig) -> tuple[str, ...]:
    """SDK init_client: turn the parsed config into the live tuple.

    Called by ClientWatcher on the initial fetch and on every change.
    Returns the new tuple — the watcher swaps it into the live state and
    also calls :func:`_apply_tags` so the process-wide singleton tracks
    the change.
    """
    parsed = _parse_csv_tags(cfg.tags)
    if parsed is None:
        logger.warning(
            "tags_provider_invalid_payload raw=%r fallback=%s",
            cfg.tags,
            list(FALLBACK_TAGS),
        )
        return FALLBACK_TAGS
    # Mirror the swap into the module-level singleton so readers that
    # only hold a reference to the provider still see the change. The
    # watcher keeps its own reference too; this is just belt + braces.
    provider = _provider_singleton()
    if provider is not None:
        provider._tags = parsed
    logger.info("tags_provider_updated tags=%s source=config_store", list(parsed))
    return parsed


def _provider_singleton() -> TagsProvider | None:
    """Return the module-level provider, if initialized.

    Defined as a helper so :func:`_build_tags` doesn't reach into module
    globals directly (cleaner for monkey-patching in tests).
    """
    return _provider


# Module-level singleton accessor. ``app.main`` calls
# ``await get_tags_provider().start()`` at boot and ``await .stop()`` on
# shutdown; everything else reads ``get_tags_provider().current()``.
_provider: TagsProvider | None = None


def get_tags_provider() -> TagsProvider:
    """Return the process-wide :class:`TagsProvider`.

    Raises if the provider hasn't been initialized yet (callers should
    start the provider in :func:`app.main.main` before serving
    traffic).
    """
    if _provider is None:
        raise RuntimeError(
            "TagsProvider not initialized; call init_tags_provider() first"
        )
    return _provider


def init_tags_provider() -> TagsProvider:
    """Construct the singleton provider without starting its poll loop.

    Use this in tests where you want to override the singleton before
    :meth:`TagsProvider.start` is called.
    """
    global _provider
    if _provider is None:
        _provider = TagsProvider()
    return _provider


def reset_tags_provider() -> None:
    """Drop the singleton. Tests use this between cases."""
    global _provider
    _provider = None