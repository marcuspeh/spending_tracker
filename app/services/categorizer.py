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
                "Reply with exactly one category from this list, "
                "lowercase, no punctuation, no explanations: "
                f"{allowed}."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Merchant: {merchant}\n"
                "Category:"
            ),
        },
    ]


def _normalize(raw: str) -> str | None:
    """Coerce the model's reply to a valid category. Returns None if it
    doesn't match any of the allowed values."""
    cleaned = raw.strip().lower().rstrip(".,;:\n\t")
    if cleaned in DEFAULT_CATEGORIES:
        return cleaned
    return None


async def categorize(merchant: str) -> str | None:
    """Return a category for ``merchant``, or None if classification fails.

    Network errors, timeouts, malformed JSON, and out-of-set replies all
    result in ``None``. The caller can safely persist ``None`` to the
    ``category`` column.
    """
    settings = get_settings()
    if not settings.llm_api_key:
        # LLM is not configured — skip silently rather than spam logs.
        return None

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": _build_prompt(merchant),
        "max_tokens": 8,
        "temperature": 0.0,
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
    return category