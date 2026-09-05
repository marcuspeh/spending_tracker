"""Telegram Rich-API table renderers.

Two renderers shared by every command handlers that show users-facing table output:

- ``render_transactions_table`` — lists of transactions (``/latest``, ``/search``, ``/range``)
- ``render_tag_breakdown_table`` — per-tag spending breakdown (``/today``, ``/week``, ``/month``)

Both emit the Bot API 10.1 ``sendRichMessage`` HTML-style markup which
(``<table>``, ``<tr>``, ``<th>``, ``<td>``), plus a thin
``send_rich_message`` helper that posts through PTB's private HTTP layer because
``python-telegram-bot`` doesn't yet expose this top-level method natively.
"""

from __future__ import annotations

from typing import Any

from telegram import Bot

from app.services.categorizer import current_tags
from app.telegram.handlers._formatting import (
    escape_html,
    format_amount,
    method_display_for_cell,
    normalized_merchant_display,
    tag_display_for_cell,
    truncate,
)
from app.utils.timezone import utc_to_sgt

# ---------------------------------------------------------------------------
# Shared table helpers
# ---------------------------------------------------------------------------

def _cell(text: str, *, header: bool = False) -> str:
    tag = "th" if header else "td"
    return f"<{tag}>{escape_html(text)}</{tag}>"


# ---------------------------------------------------------------------------
# Transactions table
# ---------------------------------------------------------------------------

def render_transactions_table(transactions: list, _title: str = "Transactions") -> str:
    """Render a list of transactions as a Telegram Rich Message table.

    Used by every command that returns a list of transactions
    (``/latest``, ``/search``, ``/range``) so the visual layout is
    identical regardless of which command was invoked.

    Uses the Bot API 10.1 ``sendRichMessage`` HTML-style markup
    (``<table>``, ``<tr>``, ``<th>``, ``<td>``) which renders natively in
    modern Telegram clients — no code fences, no manual padding.

    When ``transactions`` is empty the title is rendered as a paragraph
    instead, so an empty filtered list still shows the user what they
    searched for.

    Returns the HTML string ready to pass to ``send_rich_message``.
    """
    if not transactions:
        return f"<p>{escape_html(_title)}</p><p>No transactions found.</p>"

    headers = ["#", "DATE", "TIME", "AMOUNT", "METHOD", "MERCHANT", "TAG"]
    head_row = "<tr>" + "".join(_cell(h, header=True) for h in headers) + "</tr>"

    body_rows = []
    for offset, txn in enumerate(transactions, 1):
        time_sgt = utc_to_sgt(txn.transaction_time)
        sign = "-" if txn.amount < 0 else "+"
        amount = f"{sign}{format_amount(txn.amount)}"
        row = (
            "<tr>"
            + _cell(str(offset))
            + _cell(time_sgt.strftime("%d %b"))
            + _cell(time_sgt.strftime("%H:%M"))
            + _cell(amount)
            + _cell(method_display_for_cell(txn.payment_method.value))
            + _cell(normalized_merchant_display(txn.merchant))
            + _cell(tag_display_for_cell(txn))
            + "</tr>"
        )
        body_rows.append(row)

    return (
        f"<h2>{escape_html(_title)}</h2>"
        "<table is_bordered=\"true\" is_striped=\"true\">"
        "<thead>" + head_row + "</thead>"
        "<tbody>" + "".join(body_rows) + "</tbody>"
        "</table>"
    )


# ---------------------------------------------------------------------------
# Tag breakdown table
# ---------------------------------------------------------------------------

def render_tag_breakdown_table(
    breakdown: dict[str, float],
    has_untagged: bool,
    total: float,
    _title: str,
) -> str:
    """Render a per-tag breakdown as a Telegram Rich Message table.

    Mirrors the styling of :func:`render_transactions_table` so the two
    outputs feel consistent. Tags are emitted in the live allowed-tag
    order (from config_store via :func:`current_tags`) with any unknown
    tags appended at the bottom (defensive — should never happen given
    the strict ``/tag`` validation). The Total row is always last.
    """
    if not breakdown and not has_untagged:
        return ""

    headers = ["TAG", "AMOUNT"]
    head_row = "<tr>" + "".join(_cell(h, header=True) for h in headers) + "</tr>"

    body_rows: list[str] = []
    seen: set[str] = set()
    for tag in current_tags():
        if tag not in breakdown:
            continue
        amount = breakdown[tag]
        sign = "+" if amount > 0 else "" if amount == 0 else "-"
        body_rows.append(
            "<tr>"
            + _cell(tag.capitalize())
            + _cell(f"{sign}{format_amount(abs(amount))}")
            + "</tr>"
        )
        seen.add(tag)
    for tag in sorted(breakdown):
        if tag in seen:
            continue
        amount = breakdown[tag]
        sign = "+" if amount > 0 else "" if amount == 0 else "-"
        body_rows.append(
            "<tr>"
            + _cell(tag.capitalize())
            + _cell(f"{sign}{format_amount(abs(amount))}")
            + "</tr>"
        )

    if has_untagged:
        body_rows.append(
            "<tr>"
            + _cell("(some rows have no tag — use /tag <idx> <value>)")
            + _cell("")
            + "</tr>"
        )

    body_rows.append(
        "<tr>"
        + _cell("Total", header=True)
        + _cell(format_amount(total), header=True)
        + "</tr>"
    )

    return (
        f"<h3>{escape_html(_title)}</h3>"
        "<table is_bordered=\"true\" is_striped=\"true\">"
        "<thead>" + head_row + "</thead>"
        "<tbody>" + "".join(body_rows) + "</tbody>"
        "</table>"
    )


# ---------------------------------------------------------------------------
# Sender helper
# ---------------------------------------------------------------------------

async def send_rich_message(bot: Bot, chat_id: int, html: str) -> Any:
    """Send a Bot API 10.1 Rich Message via ``sendRichMessage``.

    ``python-telegram-bot`` v22 doesn't yet expose this method (tracked in
    upstream issue #5261, targeting v23), so we hit the raw HTTP API
    through PTB's private ``Bot._post`` helper. This inherits PTB's base
    URL, retries, and token handling.

    The Bot API expects an ``InputRichMessage`` object as the
    ``rich_message`` field. We pass it as a Python dict; PTB's
    ``RequestParameter.json_value`` will JSON-encode non-string values
    correctly when sending the form-encoded request.
    """
    return await bot._post(  # type: ignore[attr-defined]
        "sendRichMessage",
        data={
            "chat_id": chat_id,
            "rich_message": {"html": html},
        },
    )


# Backwards-compat alias — some tests import these private helpers directly from
# the _helpers facade (and we re-export them there). Re-exporting here
# lets the facade stay lean.
_TRUNCATE_HELPERS = {
    "_truncate": truncate,
    "_escape_html": escape_html,
}


__all__ = [
    "render_transactions_table",
    "render_tag_breakdown_table",
    "send_rich_message",
]
