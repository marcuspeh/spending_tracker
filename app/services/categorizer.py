"""Auto-categorize a transaction's merchant using an OpenAI-compatible LLM.

The model is sent a single piece of evidence (the merchant string) and
asked to pick one of the categories in :data:`DEFAULT_CATEGORIES`. The
response is parsed defensively — any malformed output is treated as a
failure and the call returns ``None`` so the caller can leave the
``category`` column NULL.

Network/timeout errors are also caught and logged; we never raise out
of this module because the LLM path is a soft dependency and a
catastrophic failure must not break transaction insertion.
"""

from __future__ import annotations

import logging
from typing import Final

import httpx

from app.config.settings import get_settings
from app.database.repositories.merchant_category_cache import (
    MerchantCategoryCacheRepository,
)
from app.services.merchant_normalizer import normalize_merchant

logger = logging.getLogger(__name__)


#: Default categories the LLM is allowed to return. Order is significant
#: only for prompts — the model is asked to reply with the exact value.
DEFAULT_CATEGORIES: Final[tuple[str, ...]] = (
    "food",
    "transport",
    "groceries",
    "shopping",
    "subscriptions",
    "health",
    "entertainment",
    "travel",
    "transfers",
    "fees",
    "refunds",
    "cash",
    "other",
)


def _build_prompt(merchant: str) -> list[dict[str, str]]:
    """Build the chat-completion messages for the LLM.

    We use a tiny system prompt that constrains the model to reply with
    one of the fixed categories, and a single user prompt containing the
    merchant. No other context is sent — the merchant is the only signal
    we have.
    """
    allowed = ", ".join(DEFAULT_CATEGORIES)
    return [
        {
            "role": "system",
            "content": (
                "You categorize expense transactions. "
                "Reply with exactly one token from this list, lowercase, "
                "no punctuation, no explanations, no thinking, no prefix: "
                f"{allowed}.\n"
                "Output the single word only."
            ),
        },
        {
            "role": "user",
            "content": merchant,
        },
    ]


def _normalize(raw: str) -> str | None:
    """Coerce the model's reply to a valid category. Returns None if it
    doesn't match any of the allowed values."""
    cleaned = raw.strip().lower().rstrip(".,;:\n\t")
    if cleaned in DEFAULT_CATEGORIES:
        return cleaned
    return None


def _normalize_merchant_key(merchant: str) -> str:
    """Normalize a merchant string for use as a cache key.

    Thin wrapper over :func:`app.services.merchant_normalizer.normalize_merchant`
    so the cache layer reads cleanly. Both names are kept for
    backwards-compatibility; prefer importing from the merchant_normalizer
    module in new code.
    """
    return normalize_merchant(merchant)


async def categorize(merchant: str) -> str | None:
    """Return a category for ``merchant``, or None if classification fails.

    Network errors, timeouts, malformed JSON, and out-of-set replies all
    result in ``None``. The caller can safely persist ``None`` to the
    ``category`` column.

    The merchant → category mapping is cached in MySQL
    (``merchant_category_cache``). On a cache hit the LLM is not
    called. The cache is populated only on a successful LLM response;
    it is read-only from the bot's perspective — modify rows directly
    in MySQL if you want to override a category.
    """
    settings = get_settings()
    if not merchant:
        return None

    # Read-through cache. Skip the LLM entirely on a hit.
    cache = MerchantCategoryCacheRepository()
    cache_key = _normalize_merchant_key(merchant)
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.llm_api_key:
        # LLM is not configured — skip silently rather than spam logs.
        return None

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": _build_prompt(merchant),
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
        logger.warning("categorize_llm_request_failed: %s merchant=%s", exc, merchant)
        return None

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning(
            "categorize_llm_bad_response: %s merchant=%s body=%s",
            exc, merchant, resp.text[:200],
        )
        return None

    category = _normalize(content)
    if category is None:
        logger.warning(
            "categorize_llm_out_of_set: merchant=%s reply=%r", merchant, content
        )
        return None

    # Write-through: only successful + in-set responses get cached.
    try:
        await cache.upsert(cache_key, category)
    except Exception as exc:
        # Cache write failures must not break the caller — log and
        # return the category anyway.
        logger.warning(
            "categorize_cache_upsert_failed: %s merchant=%s", exc, merchant
        )
    return category


async def categorize_or_default(
    merchant: str, default: str = "other"
) -> str | None:
    """Return a category for ``merchant``, falling back to ``default``.

    Identical to :func:`categorize` except that any failure (network
    error, timeout, bad JSON, out-of-set reply, missing API key, empty
    merchant) returns ``default`` instead of ``None``. The default value
    must be a member of :data:`DEFAULT_CATEGORIES`; if it isn't, the
    caller gets ``None`` (i.e. ``default`` is **not** persisted
    unvalidated — it has to be a real category).

    Pass-through paths still return ``None`` when the LLM is genuinely
    unable to produce a valid category AND ``default`` is not a real
    category. The cache is **not** populated with the default — only
    genuine LLM answers get cached, so users can later retry and
    overwrite the default via /edit.
    """
    if default not in DEFAULT_CATEGORIES:
        logger.warning(
            "categorize_or_default_invalid_default: default=%r", default
        )
        return None
    category = await categorize(merchant)
    if category is not None:
        return category
    return default