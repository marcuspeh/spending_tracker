"""Auto-tag a transaction's merchant using an OpenAI-compatible LLM.

The model is sent a single piece of evidence (the merchant string) and
asked to pick one of the tags returned by
:func:`app.services.tags_provider.get_tags_provider().current()`. The
response is parsed defensively — any malformed output is treated as a
failure and the call returns ``None`` so the caller can fall back to the
default tag (``other``).

Network/timeout errors are also caught and logged; we never raise out
of this module because the LLM path is a soft dependency and a
catastrophic failure must not break transaction insertion.

The tag set is owned by the sibling config_store service and refreshed
in the background by :class:`app.services.tags_provider.TagsProvider`.
We keep :data:`DEFAULT_TAGS` exported as an alias for the fallback list
so existing tests and Telegram handlers keep working without
modification — production code should call :func:`current_tags` to
read the live value.
"""

from __future__ import annotations

import logging
from typing import Final

import httpx

from app.config.settings import get_settings
from app.database.repositories.merchant_category_cache import (
    MerchantTagCacheRepository,
)
from app.services.merchant_normalizer import normalize_merchant
from app.services.tags_provider import FALLBACK_TAGS, get_tags_provider

logger = logging.getLogger(__name__)


#: Compatibility alias for the fallback tag list. Production code should
#: call :func:`current_tags` instead so it picks up live updates from
#: config_store. Kept exported because a few callers (Telegram handlers,
#: tests) still reference the constant directly.
DEFAULT_TAGS: Final[tuple[str, ...]] = FALLBACK_TAGS


#: Default tag used when the LLM fails or returns an out-of-set value.
DEFAULT_FALLBACK_TAG: Final[str] = "other"


def current_tags() -> tuple[str, ...]:
    """Return the live allowed-tag tuple.

    Falls back to :data:`DEFAULT_TAGS` if the provider hasn't been
    initialized yet (e.g. inside a unit test that didn't set it up).
    Never raises.
    """
    try:
        return get_tags_provider().current()
    except RuntimeError:
        # Provider not initialized — caller is running outside the
        # normal app boot sequence (test, CLI tool). The fallback list
        # is always usable.
        return DEFAULT_TAGS


def _build_prompt(merchant: str, allowed: tuple[str, ...]) -> list[dict[str, str]]:
    """Build the chat-completion messages for the LLM.

    We use a tiny system prompt that constrains the model to reply with
    one of the live tags, and a single user prompt containing the
    merchant. No other context is sent — the merchant is the only
    signal we have.
    """
    allowed_str = ", ".join(allowed)
    return [
        {
            "role": "system",
            "content": (
                "You tag expense transactions. "
                "Reply with exactly one token from this list, lowercase, "
                "no punctuation, no explanations, no thinking, no prefix: "
                f"{allowed_str}.\n"
                "Output the single word only."
            ),
        },
        {
            "role": "user",
            "content": merchant,
        },
    ]


def _normalize(raw: str, allowed: tuple[str, ...]) -> str | None:
    """Coerce the model's reply to a valid tag. Returns None if it
    doesn't match any of the allowed values."""
    cleaned = raw.strip().lower().rstrip(".,;:\n\t")
    if cleaned in allowed:
        return cleaned
    return None


def _normalize_merchant_key(merchant: str) -> str:
    """Normalize a merchant string for use as a cache key."""
    return normalize_merchant(merchant)


async def tag_for(merchant: str) -> str | None:
    """Return a tag for ``merchant``, or None if classification fails.

    Network errors, timeouts, malformed JSON, and out-of-set replies all
    result in ``None``. The caller can safely persist ``None`` and
    fall back to ``other`` elsewhere.

    The merchant → tag mapping is cached in MySQL
    (``merchant_category_cache`` — kept under the old name so existing
    DBs don't have to rename). On a cache hit the LLM is not called.
    The cache is populated only on a successful LLM response; it is
    read-only from the bot's perspective — modify rows directly in MySQL
    if you want to override a tag.
    """
    settings = get_settings()
    if not merchant:
        return None

    # Read-through cache. Skip the LLM entirely on a hit.
    cache = MerchantTagCacheRepository()
    cache_key = _normalize_merchant_key(merchant)
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.llm_api_key:
        # LLM is not configured — skip silently rather than spam logs.
        return None

    allowed = current_tags()

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": _build_prompt(merchant, allowed),
        "max_tokens": 16,
        "temperature": 0.0,
        "thinking": {
            "type": "disabled"
        }
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("tag_for_llm_request_failed: %s merchant=%s", exc, merchant)
        return None

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning(
            "tag_for_llm_bad_response: %s merchant=%s body=%s",
            exc, merchant, resp.text[:200],
        )
        return None

    tag = _normalize(content, allowed)
    if tag is None:
        logger.warning(
            "tag_for_llm_out_of_set: merchant=%s reply=%r allowed=%s",
            merchant, content, list(allowed),
        )
        return None

    # Write-through: only successful + in-set responses get cached.
    try:
        await cache.upsert(cache_key, tag)
    except Exception as exc:
        # Cache write failures must not break the caller — log and
        # return the tag anyway.
        logger.warning(
            "tag_for_cache_upsert_failed: %s merchant=%s", exc, merchant
        )
    return tag


async def tag_for_or_default(
    merchant: str, default: str | None = None
) -> str | None:
    """Return a tag for ``merchant``, falling back to ``default``.

    Identical to :func:`tag_for` except that any failure (network
    error, timeout, bad JSON, out-of-set reply, missing API key, empty
    merchant) returns ``default`` instead of ``None``. The default value
    must be a member of the *currently allowed* tag set; if it isn't,
    the caller gets ``None`` (i.e. ``default`` is **not** persisted
    unvalidated — it has to be a real tag).

    Pass-through paths still return ``None`` when the LLM is genuinely
    unable to produce a valid tag AND ``default`` is not a real tag.
    The cache is **not** populated with the default — only genuine LLM
    answers get cached, so users can later retry and overwrite the
    default via /tag.

    If ``default`` is None, :data:`DEFAULT_FALLBACK_TAG` (``other``)
    is used.
    """
    allowed = current_tags()
    if default is None:
        default = DEFAULT_FALLBACK_TAG
    if default not in allowed:
        logger.warning(
            "tag_for_or_default_invalid_default: default=%r allowed=%s",
            default, list(allowed),
        )
        return None
    tag = await tag_for(merchant)
    if tag is not None:
        return tag
    return default