from typing import Any

from telegram import Bot

from app.services.categorizer import DEFAULT_TAGS
from app.services.merchant_normalizer import normalize_merchant
from app.utils.timezone import utc_to_sgt

# In-memory state for two-step delete confirmation, keyed by chat_id.
# Sets (not lists) so /delete 5 repeated 100 times stays a single entry.
_pending_deletes: dict[int, set[int]] = {}

# Last list shown to each chat_id: maps the 1-based index in /latest output
# to the real transaction id. Used so /delete <index> and /edit <index> work
# directly off the numbering the user just saw.
_recent_index: dict[int, dict[int, int]] = {}


def remember_recent(chat_id: int, txn_ids: list[int]) -> None:
    """Cache the ordering shown in the most recent list command.

    ``txn_ids[i]`` is the DB id of the transaction shown at 1-based index
    ``i + 1`` in the rendered list.
    """
    _recent_index[chat_id] = {i + 1: txn_id for i, txn_id in enumerate(txn_ids)}


def resolve_recent(chat_id: int, key: int | str) -> int | None:
    """Resolve a user's ``key`` (1-based index from /latest) to the
    real transaction id stored in the most-recent-list cache.

    Returns ``None`` if nothing is cached, the key isn't a valid integer,
    or the key isn't in the cached range.
    """
    cached = _recent_index.get(chat_id, {})
    try:
        key_int = int(key)
    except (TypeError, ValueError):
        return None
    return cached.get(key_int)


def clear_recent(chat_id: int) -> None:
    """Drop the cached list for a chat (call after the user has acted on it
    so they can't accidentally delete a stale index)."""
    _recent_index.pop(chat_id, None)


def format_amount(amount: float) -> str:
    """Format amount for display."""
    return f"S${abs(amount):.2f}"


def format_transaction(txn: Any, index: int) -> str:
    """Format a transaction for display."""
    time_sgt = utc_to_sgt(txn.transaction_time)
    sign = "-" if txn.amount < 0 else "+"
    return (
        f"{index}. {sign}{format_amount(txn.amount)} at {txn.merchant}\n"
        f"   {time_sgt.strftime('%d %b %Y %H:%M')} | {txn.payment_method.value}\n"
        f"   Tag: {describe_tag_for_display(txn)}"
    )


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


def format_transactions(transactions: list, title: str = "Transactions") -> str:
    """Format a list of transactions for display."""
    if not transactions:
        return f"{title}\n\nNo transactions found."

    lines = [title, ""]
    for i, txn in enumerate(transactions, 1):
        lines.append(format_transaction(txn, i))
    return "\n".join(lines)


def _truncate(text: str, max_len: int) -> str:
    """Trim ``text`` to ``max_len`` chars, adding an ellipsis if cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _escape_html(text: str) -> str:
    """Escape the three characters Telegram's HTML parser special-cases."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


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
        return f"<p>{_escape_html(_title)}</p><p>No transactions found.</p>"

    def cell(text: str, *, header: bool = False) -> str:
        tag = "th" if header else "td"
        return f"<{tag}>{_escape_html(text)}</{tag}>"

    headers = ["#", "DATE", "TIME", "AMOUNT", "METHOD", "MERCHANT", "TAG"]
    head_row = "<tr>" + "".join(cell(h, header=True) for h in headers) + "</tr>"

    body_rows = []
    for offset, txn in enumerate(transactions, 1):
        time_sgt = utc_to_sgt(txn.transaction_time)
        sign = "-" if txn.amount < 0 else "+"
        amount = f"{sign}{format_amount(txn.amount)}"
        # Capitalize the first letter for display; the DB stores the
        # tag lowercased. Empty string when unset so the cell is blank
        # instead of "-".
        tag_display = describe_tag_for_display(txn)
        if tag_display == "-":
            tag_display = ""
        row = (
            "<tr>"
            + cell(str(offset))
            + cell(time_sgt.strftime("%d %b"))
            + cell(time_sgt.strftime("%H:%M"))
            + cell(amount)
            + cell(_truncate(txn.payment_method.value, 22))
            + cell(_truncate(normalize_merchant(txn.merchant), 32))
            + cell(_truncate(tag_display, 14))
            + "</tr>"
        )
        body_rows.append(row)

    return (
        f"<h2>{_escape_html(_title)}</h2>"
        "<table is_bordered=\"true\" is_striped=\"true\">"
        "<thead>" + head_row + "</thead>"
        "<tbody>" + "".join(body_rows) + "</tbody>"
        "</table>"
    )


def render_tag_breakdown_table(
    breakdown: dict[str, float],
    has_untagged: bool,
    total: float,
    _title: str,
) -> str:
    """Render a per-tag breakdown as a Telegram Rich Message table.

    Mirrors the styling of :func:`render_transactions_table` so the two
    outputs feel consistent. Tags are emitted in the fixed
    ``DEFAULT_TAGS`` order with any unknown tags appended at the bottom
    (defensive — should never happen given the strict ``/tag``
    validation). The Total row is always last.
    """
    if not breakdown and not has_untagged:
        return ""

    def cell(text: str, *, header: bool = False) -> str:
        tag = "th" if header else "td"
        return f"<{tag}>{_escape_html(text)}</{tag}>"

    headers = ["TAG", "AMOUNT"]
    head_row = "<tr>" + "".join(cell(h, header=True) for h in headers) + "</tr>"

    body_rows: list[str] = []
    seen: set[str] = set()
    for tag in DEFAULT_TAGS:
        if tag not in breakdown:
            continue
        amount = breakdown[tag]
        sign = "+" if amount > 0 else "" if amount == 0 else "-"
        body_rows.append(
            "<tr>"
            + cell(tag.capitalize())
            + cell(f"{sign}{format_amount(abs(amount))}")
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
            + cell(tag.capitalize())
            + cell(f"{sign}{format_amount(abs(amount))}")
            + "</tr>"
        )

    if has_untagged:
        body_rows.append(
            "<tr>"
            + cell("(some rows have no tag — use /tag <idx> <value>)")
            + cell("")
            + "</tr>"
        )

    body_rows.append(
        "<tr>"
        + cell("Total", header=True)
        + cell(format_amount(total), header=True)
        + "</tr>"
    )

    return (
        f"<h3>{_escape_html(_title)}</h3>"
        "<table is_bordered=\"true\" is_striped=\"true\">"
        "<thead>" + head_row + "</thead>"
        "<tbody>" + "".join(body_rows) + "</tbody>"
        "</table>"
    )


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
