from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.timezone import utc_to_sgt

# In-memory state for two-step delete confirmation, keyed by chat_id.
# Sets (not lists) so /delete 5 repeated 100 times stays a single entry.
_pending_deletes: dict[int, set[int]] = {}

# Last list shown to each chat_id: maps the 1-based index in /latest output
# to the real transaction id. Used so /delete <index> and /edit <index> work
# directly off the numbering the user just saw.
_recent_index: dict[int, dict[int, int]] = {}

# Pagination size for /latest table view.
LATEST_PAGE_SIZE = 10


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


def render_latest_table(
    transactions: list,
    page: int = 1,
    page_size: int = LATEST_PAGE_SIZE,
) -> tuple[str, InlineKeyboardMarkup]:
    """Render an interactive table view of ``transactions``.

    Each row of the rendered Markdown table is paired with an inline-keyboard
    button that triggers a per-row action menu. The bottom row of the
    keyboard carries Prev/Next pagination buttons.

    Returns:
        (markdown_text, InlineKeyboardMarkup) ready to be passed to
        ``send_message(..., reply_markup=keyboard, parse_mode="Markdown")``.
    """
    if not transactions:
        return "No transactions found.", InlineKeyboardMarkup([])

    total = len(transactions)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start = (page - 1) * page_size
    end = start + page_size
    page_txns = transactions[start:end]

    # Markdown monospace table.
    header = (
        f"*Latest transactions*  (page {page}/{total_pages}, showing {start + 1}"
        f"–{min(end, total)} of {total})\n"
        "```\n"
        f"{'#':>3}  {'DATE':<10}  {'AMOUNT':>10}  MERCHANT\n"
        f"{'─' * 3}  {'─' * 10}  {'─' * 10}  {'─' * 20}\n"
    )
    body_lines = []
    for offset, txn in enumerate(page_txns):
        global_index = start + offset + 1  # 1-based for the user
        time_sgt = utc_to_sgt(txn.transaction_time)
        sign = "-" if txn.amount < 0 else "+"
        amount = f"{sign}{format_amount(txn.amount)}"
        merchant = _truncate(txn.merchant or "", 20)
        body_lines.append(
            f"{global_index:>3}  {time_sgt.strftime('%d %b'):<10}  "
            f"{amount:>10}  {merchant}"
        )
    footer = "\n```"

    text = header + "\n".join(body_lines) + footer

    # Inline keyboard — one button per row, plus Prev/Next at the bottom.
    row_buttons = [
        [
            InlineKeyboardButton(
                _truncate(f"{i + 1}. {txn.merchant or '?'}", 30),
                callback_data=f"latest:row:{start + i + 1}",
            )
        ]
        for i, txn in enumerate(page_txns)
    ]
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton("« Prev", callback_data=f"latest:page:{page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(f"Page {page}/{total_pages}", callback_data="latest:noop")
    )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton("Next »", callback_data=f"latest:page:{page + 1}")
        )
    keyboard = InlineKeyboardMarkup(row_buttons + [nav_buttons])
    return text, keyboard
