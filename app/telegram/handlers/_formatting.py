"""Formatting helpers for the Telegram command handlers.

Pure functions that turn a ``Transaction`` (or parts of it) into the
display strings used by the plain-text fallback rendering. The rich-table
rendering lives in :mod:`app.telegram.handlers._tables` — these helpers
are the "no-rich-message" equivalent.
"""

from __future__ import annotations

from typing import Any

from app.services.merchant_normalizer import normalize_merchant
from app.utils.timezone import utc_to_sgt


def format_amount(amount: float) -> str:
    """Format amount for display."""
    return f"S${abs(amount):.2f}"


def describe_tag_for_display(txn: Any) -> str:
    """Return the tag string for user-facing display.

    Capitalizes the first letter so users see "Food" instead of the
    DB-stored lowercased form. Returns ``"-"`` when the tag is missing
    (LLM disabled or failed).
    """
    tag = getattr(txn, "tag", None) or "-"
    if tag == "-":
        return "-"
    return tag.capitalize()


def format_transaction(txn: Any, index: int) -> str:
    """Format a single transaction for plain-text display."""
    time_sgt = utc_to_sgt(txn.transaction_time)
    sign = "-" if txn.amount < 0 else "+"
    return (
        f"{index}. {sign}{format_amount(txn.amount)} at {txn.merchant}\n"
        f"   {time_sgt.strftime('%d %b %Y %H:%M')} | {txn.payment_method.value}\n"
        f"   Tag: {describe_tag_for_display(txn)}"
    )


def format_transactions(transactions: list, title: str = "Transactions") -> str:
    """Format a list of transactions as a plain-text block."""
    if not transactions:
        return f"{title}\n\nNo transactions found."

    lines = [title, ""]
    for i, txn in enumerate(transactions, 1):
        lines.append(format_transaction(txn, i))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers used by _tables (and exposed here for tests that import
# directly from the _helpers facade). Kept alongside formatting because
# they are purely about string -> string transformation.
# ---------------------------------------------------------------------------

_MERCHANT_TRUNCATE = 32
_TAG_TRUNCATE = 14
_METHOD_TRUNCATE = 22


def truncate(text: str, max_len: int) -> str:
    """Trim ``text`` to ``max_len`` chars, adding an ellipsis if cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def escape_html(text: str) -> str:
    """Escape the three characters Telegram's HTML parser special-cases."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def normalized_merchant_display(merchant: str) -> str:
    """Truncated, normalized merchant string for a table cell."""
    return truncate(normalize_merchant(merchant), _MERCHANT_TRUNCATE)


def tag_display_for_cell(txn: Any) -> str:
    """Tag value prepared for a table cell (capitalized, truncated, no '-' sentinel)."""
    displayed = describe_tag_for_display(txn)
    if displayed == "-":
        return ""
    return truncate(displayed, _TAG_TRUNCATE)


def method_display_for_cell(method_value: str) -> str:
    """Truncated payment-method value for a table cell."""
    return truncate(method_value, _METHOD_TRUNCATE)


__all__ = [
    "format_amount",
    "describe_tag_for_display",
    "format_transaction",
    "format_transactions",
    "truncate",
    "escape_html",
    "normalized_merchant_display",
    "tag_display_for_cell",
    "method_display_for_cell",
]
