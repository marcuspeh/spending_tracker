from typing import Any

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
    """Resolve a user's ``key`` (1-based index from /latest, or raw id) to
    a real transaction id. Returns ``None`` if nothing is cached or the key
    is invalid.
    """
    cached = _recent_index.get(chat_id, {})
    try:
        key_int = int(key)
    except (TypeError, ValueError):
        return None
    if key_int in cached:
        return key_int
    return None


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
        f"   {time_sgt.strftime('%d %b %Y %H:%M')} | {txn.payment_method.value}"
    )


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


def render_latest_table(transactions: list) -> str:
    """Render ``transactions`` as a Markdown monospace table.

    Returns a single string ready to send via ``send_message(text, parse_mode="Markdown")``.
    No inline keyboard — rows are static; users act on them via the
    existing /edit <index>, /delete <index>, /confirm <index> flow.
    """
    if not transactions:
        return "No transactions found."

    header = "*Latest transactions*\n```\n"
    rule = (
        f"{'#':>3}  {'DATE':<10}  {'TIME':<5}  {'AMOUNT':>10}  "
        f"{'METHOD':<22}  MERCHANT\n"
        f"{'─' * 3}  {'─' * 10}  {'─' * 5}  {'─' * 10}  "
        f"{'─' * 22}  {'─' * 24}\n"
    )
    body_lines = []
    for offset, txn in enumerate(transactions, 1):
        time_sgt = utc_to_sgt(txn.transaction_time)
        sign = "-" if txn.amount < 0 else "+"
        amount = f"{sign}{format_amount(txn.amount)}"
        method = _truncate(txn.payment_method.value, 22)
        merchant = _truncate(txn.merchant or "", 24)
        body_lines.append(
            f"{offset:>3}  {time_sgt.strftime('%d %b'):<10}  "
            f"{time_sgt.strftime('%H:%M'):<5}  {amount:>10}  "
            f"{method:<22}  {merchant}"
        )
    footer = "\n```"
    return header + rule + "\n".join(body_lines) + footer
