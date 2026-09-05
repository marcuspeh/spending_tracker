"""Re-export facade for the Telegram-handler helper modules.

Callers can keep importing directly from this file just like before. All
concrete implementations live in the sibling modules:

* :mod:`app.telegram.handlers._state` — in-memory caches (recent-index, pending deletes)
* :mod:`app.telegram.handlers._formatting` — text/amount/tag formatting helpers
* :mod:`app.telegram.handlers._tables` — Rich-API table renderers + sender

The facade also preserves the original private-named helpers
(``_truncate``, ``_escape_html``, ``_pending_deletes``, ``_recent_index``)
so tests and internal code that reference them by those names don't need
to change.
"""

from app.telegram.handlers._formatting import (
    describe_tag_for_display,
    escape_html,
    format_amount,
    format_transaction,
    format_transactions,
    method_display_for_cell,
    normalized_merchant_display,
    tag_display_for_cell,
    truncate,
)
from app.telegram.handlers._state import (
    _pending_deletes,
    _recent_index,
    clear_recent,
    remember_recent,
    resolve_recent,
)
from app.telegram.handlers._tables import (
    render_tag_breakdown_table,
    render_transactions_table,
    send_rich_message,
)

# Backwards-compatible private names — some callers import these with
# leading underscores directly from _helpers.
_truncate = truncate
_escape_html = escape_html

__all__ = [
    "_pending_deletes",
    "_recent_index",
    "_truncate",
    "_escape_html",
    "clear_recent",
    "describe_tag_for_display",
    "format_amount",
    "format_transaction",
    "format_transactions",
    "truncate",
    "escape_html",
    "normalized_merchant_display",
    "tag_display_for_cell",
    "method_display_for_cell",
    "remember_recent",
    "render_tag_breakdown_table",
    "render_transactions_table",
    "resolve_recent",
    "send_rich_message",
]
