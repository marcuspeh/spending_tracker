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

Tool calling
------------
The model is given the tools registered with
:func:`app.services.tools.default_registry` — currently just
``curl_website``, which lets it look up an ambiguous merchant's
domain (e.g. ``AMZN`` → ``amazon.com``). Tools execute server-side in
:func:`app.services.tools.execute` and only public http(s) GETs are
permitted.

Adding a new tool is straightforward — drop a new module under
:mod:`app.services.tools`, subclass :class:`~app.services.tools.Tool`,
and self-register on import. The agent loop picks it up automatically.

A hard cap of :data:`MAX_ITERATIONS` chat-completion round-trips keeps
the worst case bounded. After the cap the model MUST answer with a tag
in its next message (the system prompt enforces it); if it still emits
a tool_call we strip it and try to parse the trailing text instead,
falling back to ``None`` on total failure.
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
from app.services.tags_provider import FALLBACK_TAGS, get_tags_provider, llm_tags
from app.services.tools import execute as execute_tool
from app.services.tools import specs as tool_specs

logger = logging.getLogger(__name__)


#: Compatibility alias for the fallback tag list. Production code should
#: call :func:`current_tags` instead so it picks up live updates from
#: config_store. Kept exported because a few callers (Telegram handlers,
#: tests) still reference the constant directly.
DEFAULT_TAGS: Final[tuple[str, ...]] = FALLBACK_TAGS


#: Default tag used when the LLM fails or returns an out-of-set value.
DEFAULT_FALLBACK_TAG: Final[str] = "other"


#: Hard cap on chat-completion round-trips (user turn + N tool exchanges)
#: for a single :func:`tag_for` invocation. The system prompt tells the
#: model it MUST emit a tag after this many turns, so the call returns a
#: verdict or ``None`` in bounded time.
MAX_ITERATIONS: Final[int] = 5


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


def _build_prompt(
    merchant: str,
    allowed: tuple[str, ...],
) -> list[dict]:
    """Build the chat-completion messages.

    The system prompt is permissive about consulting tools but strict
    about the final answer — it MUST be exactly one allowed tag. The
    merchant is the only first-turn user input; subsequent turns carry
    tool-call / tool-result messages added by the agent loop.
    """
    allowed_str = ", ".join(allowed)
    return [
        {
            "role": "system",
            "content": (
                "You tag expense transactions.\n"
                "If the merchant is already recognisable, answer "
                "immediately without tools. Only research when the "
                "merchant name is genuinely unfamiliar.\n"
                "When you do research:\n"
                "- Use at most 2 tool calls, then answer. Do not keep "
                "searching.\n"
                "- Prefer the merchant's official site. If a URL fails, "
                "use a single search-engine query — never try a second "
                "search engine or another guessed domain.\n"
                "- Search results are often unusable. If the pages don't "
                "clearly identify the business, stop and answer with your "
                "best guess. An approximate tag is better than no answer.\n"
                "When torn between two tags, pick the more "
                "specific one (e.g. a specific venue over a broad "
                "category).\n"
                f"You have at most {MAX_ITERATIONS} turns total and your "
                "last turn must be the answer. Your final reply must be "
                "exactly one tag from this list, lowercase, no "
                "punctuation, no other text: "
                f"{allowed_str}"
            ),
        },
        {
            "role": "user",
            "content": merchant,
        },
    ]


def _normalize(raw: str, allowed: tuple[str, ...]) -> str | None:
    """Coerce the model's reply to a valid tag. Returns None if it
    doesn't match any of the allowed values.

    Some providers always wrap reasoning in ``<think>...</think>``
    (even when ``thinking: disabled`` is requested) before emitting the
    actual answer. We strip the block so the tag itself can be matched.
    """
    import re

    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    cleaned = cleaned.strip().lower().rstrip(".,;:\n\t")
    if cleaned in allowed:
        return cleaned
    return None


def _extract_assistant_message(data: dict) -> dict:
    """Pull the first choice's assistant message dict from an OpenAI-
    compatible chat-completion response. Raises KeyError/IndexError on
    shape mismatch — callers convert that into a "bad response" log.
    """
    return data["choices"][0]["message"]


async def _call_llm(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    payload: dict,
) -> dict:
    """POST to the chat-completion endpoint and return parsed JSON.

    Raises :class:`httpx.HTTPError` on transport problems and
    :class:`ValueError` / :class:`KeyError` / :class:`IndexError` on a
    bad body. Caller decides how to log + recover.
    """
    resp = await client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


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

    The agent loop runs up to :data:`MAX_ITERATIONS` chat-completion
    round-trips, executing each tool call the model emits. After the
    cap the model is forced to answer with a tag (or we give up and
    return ``None``).
    """
    settings = get_settings()
    if not merchant:
        return None

    # Read-through cache. Skip the LLM entirely on a hit.
    cache = MerchantTagCacheRepository()
    cache_key = normalize_merchant(merchant)
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.llm_api_key:
        # LLM is not configured — skip silently rather than spam logs.
        return None

    # The LLM prompt only lists ``llm_tags()`` (full allowed set minus
    # any tags the operator wants to hide from the model — see
    # app.services.tags_provider). Validation still accepts anything in
    # the full allowed set, so an excluded-but-valid reply from the
    # model (e.g. the model knew about it before the operator excluded
    # it) still round-trips correctly.
    prompt_tags = llm_tags()
    allowed = current_tags()

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    messages = _build_prompt(merchant, prompt_tags)
    tools = tool_specs()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for iteration in range(1, MAX_ITERATIONS + 1):
                payload = {
                    "model": settings.llm_model,
                    "messages": messages,
                    "tools": tools,
                    # 1024 leaves room for the model's <think>...</think>
                    # block plus the single-token tag answer. ``thinking:
                    # disabled`` is sent for providers that honour it; the
                    # MiniMax-M2.7 provider ignores it but its think blocks
                    # are stripped by ``_normalize``.
                    "max_tokens": 1024,
                    "temperature": 0.0,
                    "thinking": {"type": "disabled"},
                }
                try:
                    data = await _call_llm(client, url, headers, payload)
                    assistant = _extract_assistant_message(data)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "tag_for_llm_request_failed: %s merchant=%s iteration=%d",
                        exc, merchant, iteration,
                    )
                    return None
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    logger.warning(
                        "tag_for_llm_bad_response: %s merchant=%s iteration=%d",
                        exc, merchant, iteration,
                    )
                    return None

                tool_calls = assistant.get("tool_calls") or []

                if not tool_calls:
                    # Final-answer turn. Parse content as a tag.
                    content = assistant.get("content") or ""
                    tag = _normalize(content, allowed)
                    if tag is not None:
                        return await _persist(cache, cache_key, tag, merchant)

                    # Unparseable reply (e.g. the provider burned the
                    # whole token budget on a <think> block and never
                    # emitted the tag). While iterations remain, tell the
                    # model to retry rather than giving up — otherwise a
                    # single truncated turn fails the whole tag.
                    if iteration < MAX_ITERATIONS:
                        logger.warning(
                            "tag_for_llm_out_of_set_retry: merchant=%s "
                            "reply=%r iteration=%d allowed=%s",
                            merchant, content, iteration, list(allowed),
                        )
                        messages.append(assistant)
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "That reply was not a valid tag. Reply "
                                    "with exactly one tag from this list and "
                                    f"nothing else: {', '.join(allowed)}"
                                ),
                            }
                        )
                        continue
                    logger.warning(
                        "tag_for_llm_out_of_set: merchant=%s reply=%r "
                        "iteration=%d allowed=%s",
                        merchant, content, iteration, list(allowed),
                    )
                    return None

                # Tool-call turn. Append the assistant message verbatim
                # so the next request includes the call id, then execute
                # each tool and append a "tool" message in the same
                # order. Tool messages MUST immediately follow the
                # assistant turn that requested them.
                messages.append(assistant)
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = fn.get("name") or ""
                    raw_args = fn.get("arguments") or ""
                    call_id = call.get("id") or ""
                    logger.info(
                        "tag_for_tool_call: merchant=%s iteration=%d "
                        "tool=%s args=%s",
                        merchant, iteration, name, raw_args[:200],
                    )
                    result = await execute_tool(name, raw_args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": result,
                        }
                    )

                # If we just spent our last iteration on tool calls the
                # next loop will exit naturally. We don't force a final
                # tag here — the model gets one more turn, which the
                # system prompt told it to use as its final answer.
    except httpx.HTTPError as exc:
        logger.warning("tag_for_llm_request_failed: %s merchant=%s", exc, merchant)
        return None

    # Exhausted MAX_ITERATIONS without a tag answer. This should be
    # rare given the system prompt, but log so we notice if a model is
    # ignoring it.
    logger.warning(
        "tag_for_llm_iteration_cap: merchant=%s iterations=%d",
        merchant, MAX_ITERATIONS,
    )
    return None


async def _persist(
    cache: MerchantTagCacheRepository,
    cache_key: str,
    tag: str,
    merchant: str,
) -> str:
    """Write ``tag`` to the cache, swallowing write failures.

    Cache write failures must not break the caller — log and return the
    tag so the in-flight transaction can still proceed.
    """
    try:
        await cache.upsert(cache_key, tag)
    except Exception as exc:
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
    # ``default`` is validated against the *full* allowed set, not the
    # LLM-restricted one — ``/tag`` and the ingestion fallback both go
    # through here, and neither should reject an excluded tag since
    # excluded == hidden-from-LLM, not hidden-from-user.
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