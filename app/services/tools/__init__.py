"""LLM-callable tools used by the categorizer agent loop.

Adding a new tool is three steps:

1. Subclass :class:`Tool` in a new module under this package,
   implementing :meth:`Tool.spec` (the OpenAI function-calling schema)
   and :meth:`Tool.run` (the actual side-effect).
2. Decorate it with :meth:`ToolRegistry.register` so it shows up in the
   catalog (see :func:`default_registry`).
3. Done — :mod:`app.services.categorizer` will expose the new tool to
   the model on the next call.

Tools run server-side in the categorizer's event loop; never trust raw
model output. Validate arguments inside ``run`` and return a JSON
string suitable for inlining as the ``content`` of a ``tool`` message.
"""

from __future__ import annotations

from app.services.tools.base import (
    Tool,
    ToolRegistry,
    ToolResult,
    default_registry,
    execute,
    specs,
)

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "default_registry",
    "execute",
    "specs",
]