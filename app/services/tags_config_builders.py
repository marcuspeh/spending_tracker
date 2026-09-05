"""Config-store payload shapes and builder callbacks for TagsProvider.

Two concerns that were interleaved inside :mod:`app.services.tags_provider`:

- :class:`TagsConfig` / :class:`ExcludedTagsConfig` — the small typed
  payload shapes accepted by :class:`config_store.ClientWatcher`.
- :func:`_parse_csv_tags`, :func:`_build_tags`, :func:`_build_excluded`
  — the CSV-to-tuple parser plus the two ``init_client`` callbacks that
  the watcher invokes whenever config_store emits a new value (or on
  startup / poll ticks).

Splitting these out keeps the main :class:`TagsProvider` focused on
lifecycle (start/stop) and lookup (current/excluded/llm_tags).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config_store import ConfigClient

if TYPE_CHECKING:
    from app.services.tags_provider import TagsProvider

logger = logging.getLogger(__name__)


def _parse_csv_tags(raw: str) -> tuple[str, ...] | None:
    """Parse a comma-separated tag string into a normalized tuple.

    Returns ``None`` if the result is empty or contains duplicates — the
    caller falls back to the provider's hard-coded fallback in that case
    so the LLM prompt never offers the user an empty or duplicated set.

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


def _fallback_tags() -> tuple[str, ...]:
    """Return the hard-coded fallback tag tuple.

    Local import avoids a module-level import cycle with
    :mod:`app.services.tags_provider` (which imports ``TagsConfig`` etc.
    at import time).
    """
    from app.services.tags_provider import FALLBACK_TAGS

    return FALLBACK_TAGS


def _empty_excluded() -> tuple[str, ...]:
    """Return the hard-coded empty-excluded tuple.

    Local import for the same reason as :func:`_fallback_tags`.
    """
    from app.services.tags_provider import EMPTY_EXCLUDED

    return EMPTY_EXCLUDED


async def _build_tags(client: ConfigClient, cfg: TagsConfig) -> tuple[str, ...]:
    """SDK init_client for the allowed-list payload.

    Invalid payloads (empty / duplicates) fall back to
    :data:`FALLBACK_TAGS` so a typo never silently empties the allowed
    set.
    """
    parsed = _parse_csv_tags(cfg.tags)
    fallback_tags = _fallback_tags()
    if parsed is None:
        logger.warning(
            "tags_provider_invalid_payload raw=%r fallback=%s",
            cfg.tags,
            list(fallback_tags),
        )
        return fallback_tags
    provider: TagsProvider | None = _provider_singleton()
    if provider is not None:
        provider._tags = parsed  # noqa: SLF001
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
    empty_exc = _empty_excluded()
    if parsed is None:
        provider = _provider_singleton()
        if provider is not None:
            provider._excluded = empty_exc  # noqa: SLF001
        logger.warning(
            "tags_provider_invalid_excluded_payload raw=%r fallback=%s",
            cfg.tags,
            list(empty_exc),
        )
        return empty_exc
    provider = _provider_singleton()
    if provider is not None:
        provider._excluded = parsed  # noqa: SLF001
    logger.info(
        "tags_provider_updated excluded=%s source=config_store", list(parsed)
    )
    return parsed


def _provider_singleton() -> "TagsProvider | None":
    """Return the module-level provider, if initialized.

    Delegates to the same-name helper in :mod:`app.services.tags_provider`
    so there's only one place that reads ``_provider`` (keeps tests that
    monkey-patch the singleton working).
    """
    # Local import to avoid import cycles: tags_provider imports
    # TagsConfig and _build_* from us at import time.
    from app.services.tags_provider import _provider_singleton as _ps

    return _ps()


__all__ = [
    "TagsConfig",
    "ExcludedTagsConfig",
    "_parse_csv_tags",
    "_build_tags",
    "_build_excluded",
]
