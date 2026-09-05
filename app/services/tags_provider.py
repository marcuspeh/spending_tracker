"""Live tag-set provider backed by the sibling config_store service.

The list of tags the LLM is allowed to return is owned by config_store
(MongoDB → MySQL cache → HTTP). At boot we spin up a :class:`TagsProvider`
which polls config_store every ``config_store_poll_seconds`` and rebuilds
in-memory tuples whenever the underlying comma-separated values change.

Two tag lists are tracked:

* ``current()`` — the full allowed set. Drives ``/tag`` validation and
  breakdown rendering. Falls back to :data:`FALLBACK_TAGS` on outage.
* ``excluded()`` — the subset of tags that should be *hidden from the
  LLM prompt only*. Still a valid tag for users to assign manually.
  Empty tuple on outage/missing key.

The LLM-specific accessor :meth:`TagsProvider.llm_tags` (and the helper
:func:`llm_tags`) returns ``current() - excluded()``. If the subtraction
would leave the LLM with an empty set, the last tag of ``current()`` is
kept so the model always has somewhere to answer.

When config_store is unreachable or returns something we can't parse,
the provider stays on :data:`FALLBACK_TAGS` so the rest of the system
keeps working offline. The watcher keeps retrying in the background, so
a transient outage is self-healing.
"""

from __future__ import annotations

import logging
from typing import Final

from config_store import ClientWatcher, ConfigClient

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


#: Hard-coded fallback used when config_store is unreachable, hasn't been
#: polled yet, or returns something we can't parse.
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


#: Default for the exclude list before config_store has been polled or
#: when the key is missing/invalid.
EMPTY_EXCLUDED: Final[tuple[str, ...]] = ()


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
    """Holds the live allowed / excluded tag tuples and their watchers.

    Lifetime::

        provider = TagsProvider()
        await provider.start()           # begins polling config_store
        tags = provider.current()        # synchronous, cheap
        llm_set = provider.llm_tags()    # current() - excluded()
        ...
        await provider.stop()            # cancel polling + close client
    """

    def __init__(self) -> None:
        self._tags: tuple[str, ...] = FALLBACK_TAGS
        self._excluded: tuple[str, ...] = EMPTY_EXCLUDED
        self._client: ConfigClient | None = None
        self._tags_watcher: ClientWatcher | None = None
        self._excluded_watcher: ClientWatcher | None = None

    def current(self) -> tuple[str, ...]:
        """Return the current allowed-tag tuple.

        Always returns something usable: either the live value from
        config_store or :data:`FALLBACK_TAGS`. Never raises.
        """
        return self._tags

    def excluded(self) -> tuple[str, ...]:
        """Return the current excluded-tag tuple.

        These tags stay in :meth:`current` (so users can still assign
        them via ``/tag`` and they still appear in breakdowns) but must
        NOT appear in the LLM prompt.

        Returns an empty tuple when the exclude key is missing,
        invalid, or hasn't been polled yet — never the full tag list.
        """
        return self._excluded

    def llm_tags(self) -> tuple[str, ...]:
        """Return the tag set the LLM is allowed to return.

        Equals ``current()`` with every entry in ``excluded()`` filtered
        out. Ignored entries that aren't in ``current()`` are silently
        dropped (defensive against stale config_store rows).

        If the subtraction would yield an empty tuple we keep the last
        element of ``current()`` so the model always has at least one
        option to answer with — otherwise an empty prompt would be
        useless.
        """
        excluded_set = set(self._excluded)
        filtered = tuple(t for t in self._tags if t not in excluded_set)
        if filtered:
            return filtered
        return (self._tags[-1],)

    async def start(self) -> None:
        """Build the SDK client and start polling config_store.

        Always succeeds — config_store outages are non-fatal because the
        provider already has :data:`FALLBACK_TAGS` / :data:`EMPTY_EXCLUDED`
        ready and the SDK's :class:`ClientWatcher` logs and retries on
        every tick.
        """
        settings = get_settings()
        self._client = ConfigClient(
            project=settings.config_store_project,
            base_url=settings.config_store_url,
            cache_ttl=settings.config_store_poll_seconds,
        )

        initial_tags_raw = await self._safe_initial_fetch(
            settings.config_store_tags_key,
            label="tags",
        )
        if initial_tags_raw is not None:
            parsed = _parse_csv_tags(initial_tags_raw)
            if parsed is not None:
                self._tags = parsed
                logger.info(
                    "tags_provider_started tags=%s source=config_store",
                    list(self._tags),
                )
            else:
                logger.warning(
                    "tags_provider_invalid_initial_payload raw=%r fallback=%s",
                    initial_tags_raw,
                    list(FALLBACK_TAGS),
                )
        else:
            logger.info(
                "tags_provider_started tags=%s source=fallback",
                list(FALLBACK_TAGS),
            )

        self._tags_watcher = ClientWatcher(
            config_type=TagsConfig,
            init_client=_build_tags,
            client=self._client,
            key=settings.config_store_tags_key,
            poll_interval=settings.config_store_poll_seconds,
            initial_value=self._tags,
            initial_raw=initial_tags_raw,
        )
        self._tags_watcher.start()

        initial_excluded_raw = await self._safe_initial_fetch(
            settings.config_store_tags_excluded_key,
            label="excluded",
        )
        if initial_excluded_raw is not None:
            parsed = _parse_csv_tags(initial_excluded_raw)
            self._excluded = parsed if parsed is not None else EMPTY_EXCLUDED
            if parsed is not None:
                logger.info(
                    "tags_provider_started excluded=%s source=config_store",
                    list(self._excluded),
                )
            else:
                logger.warning(
                    "tags_provider_invalid_initial_excluded_payload "
                    "raw=%r fallback=%s",
                    initial_excluded_raw,
                    list(EMPTY_EXCLUDED),
                )
        else:
            logger.info(
                "tags_provider_started excluded=%s source=fallback",
                list(EMPTY_EXCLUDED),
            )

        self._excluded_watcher = ClientWatcher(
            config_type=ExcludedTagsConfig,
            init_client=_build_excluded,
            client=self._client,
            key=settings.config_store_tags_excluded_key,
            poll_interval=settings.config_store_poll_seconds,
            initial_value=self._excluded,
            initial_raw=initial_excluded_raw,
        )
        self._excluded_watcher.start()

    async def _safe_initial_fetch(self, key: str, *, label: str) -> str | None:
        """Try to fetch ``key`` during startup. Logs and returns None on
        any failure (the watcher will retry on the next tick).
        """
        client = self._client
        assert client is not None
        try:
            return await client.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "tags_provider_initial_fetch_failed key=%s label=%s err=%s",
                key,
                label,
                exc,
            )
            return None

    async def stop(self) -> None:
        """Cancel polling and close the underlying SDK client."""
        for watcher_attr in ("_tags_watcher", "_excluded_watcher"):
            watcher = getattr(self, watcher_attr)
            if watcher is not None:
                try:
                    await watcher.aclose()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "tags_provider_watcher_close_failed watcher=%s err=%s",
                        watcher_attr,
                        exc,
                    )
                setattr(self, watcher_attr, None)
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("tags_provider_client_close_failed err=%s", exc)
            self._client = None


class TagsConfig:
    """Typed shape used by :class:`config_store.ClientWatcher` for the
    full allowed-tag payload.
    """

    def __init__(self, tags: str) -> None:
        self.tags = tags


class ExcludedTagsConfig:
    """Typed shape used by :class:`config_store.ClientWatcher` for the
    excluded-from-LLM tag payload.
    """

    def __init__(self, tags: str) -> None:
        self.tags = tags


async def _build_tags(client: ConfigClient, cfg: TagsConfig) -> tuple[str, ...]:
    """SDK init_client for the allowed-list payload."""
    parsed = _parse_csv_tags(cfg.tags)
    if parsed is None:
        logger.warning(
            "tags_provider_invalid_payload raw=%r fallback=%s",
            cfg.tags,
            list(FALLBACK_TAGS),
        )
        return FALLBACK_TAGS
    provider = _provider_singleton()
    if provider is not None:
        provider._tags = parsed
    logger.info("tags_provider_updated tags=%s source=config_store", list(parsed))
    return parsed


async def _build_excluded(
    client: ConfigClient, cfg: ExcludedTagsConfig
) -> tuple[str, ...]:
    """SDK init_client for the excluded-list payload.

    Invalid payloads (empty / duplicates) reduce to :data:`EMPTY_EXCLUDED`
    so a typo never silently hides every tag from the LLM.
    """
    parsed = _parse_csv_tags(cfg.tags)
    if parsed is None:
        provider = _provider_singleton()
        if provider is not None:
            provider._excluded = EMPTY_EXCLUDED
        logger.warning(
            "tags_provider_invalid_excluded_payload raw=%r fallback=%s",
            cfg.tags,
            list(EMPTY_EXCLUDED),
        )
        return EMPTY_EXCLUDED
    provider = _provider_singleton()
    if provider is not None:
        provider._excluded = parsed
    logger.info(
        "tags_provider_updated excluded=%s source=config_store", list(parsed)
    )
    return parsed


def _provider_singleton() -> TagsProvider | None:
    """Return the module-level provider, if initialized.

    Defined as a helper so the watcher callbacks don't reach into module
    globals directly (cleaner for monkey-patching in tests).
    """
    return _provider


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


def llm_tags() -> tuple[str, ...]:
    """Return the tag set the LLM is allowed to return.

    Convenience wrapper around :meth:`TagsProvider.llm_tags` that falls
    back to :data:`FALLBACK_TAGS` when the provider hasn't been
    initialized yet (e.g. inside a unit test that didn't set it up).
    Never raises.
    """
    try:
        return get_tags_provider().llm_tags()
    except RuntimeError:
        return FALLBACK_TAGS


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