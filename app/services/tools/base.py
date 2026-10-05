"""Pluggable tool framework for the categorizer's LLM agent loop.

A :class:`Tool` is a thin wrapper around a single side-effect the model
can invoke (e.g. fetch a URL). The categorizer drives the chat-
completion loop, hands each model-requested tool call to
:func:`execute`, and feeds the returned JSON string back to the model.

The catalog is held in a :class:`ToolRegistry` singleton — production
code uses :func:`default_registry`; tests can construct a private
registry to avoid touching the real one.

All tool execution is server-side. Tools must:

* Validate their arguments defensively (the model's JSON is hostile).
* Catch their own exceptions and return a JSON error envelope rather
  than letting them propagate — the agent loop should never crash on
  a tool failure.
* Return :data:`ToolResult` so success and error responses look the
  same to the agent loop.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.logging_setup import client

#: Result of a tool run — always serialised to JSON before being sent
#: back to the model as the ``content`` of a ``tool`` message. Keep it
#: small; the model has to re-read the whole conversation.
ToolResult = dict[str, Any]

log = client()


class Tool(ABC):
    """Base class for a model-callable tool.

    Subclasses set :attr:`name` (must match the function name in
    :meth:`spec`) and implement :meth:`spec` and :meth:`run`.
    """

    #: Function name as it appears in the model's ``tool_calls`` payload
    #: and in :meth:`spec`. Keep it short and snake_case.
    name: ClassVar[str]

    @abstractmethod
    def spec(self) -> dict:
        """Return the OpenAI function-calling schema for this tool.

        Must include ``type: function`` and a ``function`` block with at
        minimum ``name``, ``description``, and ``parameters``.
        """

    @abstractmethod
    async def run(self, arguments: str) -> ToolResult:
        """Execute the tool and return a JSON-serialisable result.

        ``arguments`` is the raw JSON the model emitted; tools parse it
        themselves so they can return a structured error on malformed
        input. Never raise — catch everything and return an
        ``{"error": ...}`` envelope so the agent loop survives.
        """


class ToolRegistry:
    """In-memory catalog of :class:`Tool` instances keyed by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add ``tool`` to the catalog.

        Re-registration of the same name replaces the previous entry —
        handy for tests that want to swap a stub in. Raises
        ``ValueError`` if the tool's spec name and :attr:`Tool.name`
        disagree, since that would confuse the model.
        """
        if tool.spec().get("function", {}).get("name") != tool.name:
            raise ValueError(
                f"Tool.name={tool.name!r} does not match "
                f"spec function name={tool.spec().get('function', {}).get('name')!r}"
            )
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Drop ``name`` from the catalog. Returns True if it existed."""
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict]:
        """Return the ``tools`` payload to send with chat-completion.

        Order isn't guaranteed; callers shouldn't depend on it.
        """
        return [t.spec() for t in self._tools.values()]

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools.keys())


#: Process-wide default registry, initialised with the tools shipped by
#: this package. Tests can mutate it freely between cases.
_default_registry: ToolRegistry | None = None


def default_registry() -> ToolRegistry:
    """Return the process-wide tool catalog, initialising it lazily.

    Imported here (rather than at module top) so tests can patch the
    constructor and so the registry reflects whichever tool modules have
    imported this package's submodules.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
        # Importing the module triggers its self-registration side
        # effect (see curl_website.py).
        from app.services.tools import curl_website  # noqa: F401

    return _default_registry


def reset_default_registry() -> None:
    """Drop the process-wide registry. Tests use this between cases."""
    global _default_registry
    _default_registry = None


def specs() -> list[dict]:
    """Return the ``tools`` payload for the default registry."""
    return default_registry().specs()


async def execute(name: str, arguments: str) -> str:
    """Look up ``name`` in the registry and serialise the result to JSON.

    Unknown names return a JSON error envelope rather than raising so a
    misbehaving model can't crash the agent loop. ``arguments`` is
    forwarded verbatim to :meth:`Tool.run` — the tool is responsible
    for parsing + validating it.
    """
    tool = default_registry().get(name)
    if tool is None:
        return json.dumps({"error": f"unknown tool: {name!r}"})
    try:
        result = await tool.run(arguments)
    except Exception as exc:  # noqa: BLE001
        # A tool that raises is a bug, but the agent loop must keep
        # running so the model can react. Log + return an envelope.
        log.warn("tool_run_uncaught_exception tool=%s err=%s", name, exc)
        return json.dumps({"error": f"tool {name!r} crashed: {exc}"})
    return json.dumps(result)