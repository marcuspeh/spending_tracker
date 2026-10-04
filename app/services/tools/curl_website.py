"""``curl_website`` — fetch the text of a public HTTP(S) URL.

Lets the model look up ambiguous strings like ``AMZN`` by reading the
merchant's homepage. Restricted to public sites: only ``http(s)``
schemes with a host are accepted, and any non-2xx response is surfaced
as a JSON error envelope the model can react to.

Huge pages are capped at :data:`MAX_BYTES` so the chat-completion
request doesn't blow up; the truncation flag tells the model the body
was clipped.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from app.services.tools.base import Tool, ToolResult, default_registry


#: Per-HTTP-request timeout. Shared with the chat-completion client so
#: a slow site can't stall the whole agent loop.
TIMEOUT_SECONDS: float = 10.0

#: Maximum bytes of a tool response we forward back to the model.
MAX_BYTES: int = 16_000


class CurlWebsiteTool(Tool):
    """Fetch the text body of an HTTP(S) URL."""

    name: ClassVar[str] = "curl_website"

    def spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Fetch the raw text of a public web page (HTTP GET) to "
                    "identify an unfamiliar merchant (e.g. AMZN → "
                    "amazon.com) and choose the right tag. Only http(s) URLs "
                    "to public sites are allowed. Make at most 2 tool "
                    "calls for a merchant, then answer. Prefer the "
                    "merchant's official site; if a URL fails use a single "
                    "search-engine query rather than guessing more domains. "
                    "If no plausible homepage exists "
                    "(cash, local stalls, or app-only merchants), skip this "
                    "call and answer with the closest tag — the tool is "
                    "optional. On a fetch error you receive a JSON error; "
                    "pick a tag from the allowed list instead of retrying."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": (
                                "Absolute http(s) URL to fetch. Prefer the "
                                "merchant's official domain. If no domain "
                                "is plausible, don't call this tool at all."
                            ),
                        },
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
        }

    async def run(self, arguments: str) -> ToolResult:
        try:
            args = _parse_args(arguments)
        except ValueError as exc:
            return {"error": f"invalid tool arguments: {exc}"}

        url = args.get("url")
        if not isinstance(url, str) or not url:
            return {"error": "missing 'url' argument"}

        parsed = httpx.URL(url)
        if parsed.scheme not in ("http", "https") or not parsed.host:
            return {"error": "url must be an absolute http(s) URL"}

        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": "expense-tracker-categorizer/1.0"},
            ) as client:
                resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return {"error": f"fetch failed: {exc}", "url": url}

        body = resp.content[:MAX_BYTES]
        text = _decode(body, resp.encoding)
        truncated = len(resp.content) > MAX_BYTES
        return {
            "url": url,
            "status": resp.status_code,
            "content": text,
            "truncated": truncated,
        }


def _parse_args(arguments: str) -> dict:
    """Parse ``arguments`` JSON, normalising empty to ``{}``."""
    import json

    if not arguments:
        return {}
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError("arguments must be a JSON object")
    return value


def _decode(body: bytes, encoding: str | None) -> str:
    """Best-effort text decode — never lose data to a bad charset."""
    try:
        return body.decode(encoding or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


# Auto-register on import so ``default_registry()`` finds us without
# the categorizer having to know about every concrete tool module.
default_registry().register(CurlWebsiteTool())