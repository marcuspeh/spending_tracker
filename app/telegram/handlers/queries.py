from typing import Awaitable, Callable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from app.database.models.user import User
from app.database.repositories.user import UserRepository
from app.services.categorizer import current_tags
from app.services.expense import ExpenseService
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import (
    format_amount,
    format_transaction,
    format_transactions,
    remember_recent,
    render_tag_breakdown_table,
    render_transactions_table,
    send_rich_message,
)
from app.utils.timezone import parse_date

logger = structlog.get_logger()


def _parse_count(
    args: list[str] | None,
    default_count: int = 10,
    max_count: int = 50,
) -> int:
    """Parse ``[count]`` from a command's args. Capped at ``max_count``."""
    if not args:
        return default_count
    try:
        return min(int(args[0]), max_count)
    except ValueError:
        return default_count


async def _resolve_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> User | None:
    """Run auth + ``UserRepository`` lookup. Returns ``None`` on failure
    (and replies to the user with the reason)."""
    if not await auth_handler(update, context):
        return None
    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(update.effective_chat.id)
    if not user:
        await update.message.reply_text("User not found.")
        return None
    return user


async def _send_with_fallback(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    html: str,
    fallback_text: str,
) -> None:
    """Send ``html`` as a Rich Message, falling back to ``fallback_text``
    on failure (older API / network glitch)."""
    try:
        await send_rich_message(context.bot, chat_id, html)
    except Exception as e:
        logger.warning("rich_message_send_failed", error=str(e))
        await context.bot.send_message(chat_id=chat_id, text=fallback_text)


def _format_tag_breakdown(
    breakdown: dict[str, float],
    has_untagged: bool,
    total: float,
) -> str:
    """Render a per-tag breakdown as a plain-text block.

    ``breakdown`` maps ``tag -> signed_sum``. Tags are printed in
    live-enum order (from config_store via :func:`current_tags`) so the
    output stays stable run-to-run, with any unknown tags appended at
    the bottom (defensive — should never happen given the strict
    ``/tag`` validation).
    """
    if not breakdown and not has_untagged:
        return ""

    lines = ["By tag:"]
    seen: set[str] = set()
    for tag in current_tags():
        if tag in breakdown:
            amount = breakdown[tag]
            sign = "+" if amount > 0 else "" if amount == 0 else "-"
            tag_display = tag.capitalize()
            lines.append(
                f"  {tag_display:<14} {sign}{format_amount(abs(amount))}"
            )
            seen.add(tag)
    leftover = sorted((t, a) for t, a in breakdown.items() if t not in seen)
    for tag, amount in leftover:
        sign = "+" if amount > 0 else "" if amount == 0 else "-"
        lines.append(f"  {tag:<14} {sign}{format_amount(abs(amount))}")

    if has_untagged:
        lines.append("  (some rows have no tag — use /tag <idx> <value>)")

    lines.append(f"  {'Total':<14} {format_amount(total)}")
    return "\n".join(lines)


def _plain_text_breakdown_message(
    title: str, total: float, breakdown: dict[str, float], has_untagged: bool
) -> str:
    """Build the plain-text fallback for the spending-breakdown handlers."""
    text = f"{title}: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
    breakdown_text = _format_tag_breakdown(breakdown, has_untagged, total)
    if breakdown_text:
        text += "\n\n" + breakdown_text
    return text


def make_spending_breakdown_handler(
    title: str,
    fetch_total: Callable[[ExpenseService, int], Awaitable[float]],
    fetch_breakdown: Callable[
        [ExpenseService, int], Awaitable[tuple[dict[str, float], bool]]
    ],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    """Build a handler that shows a per-tag spending breakdown.

    ``title`` is the headline shown above the table (e.g. "Today's
    spending"). ``fetch_total`` and ``fetch_breakdown`` are the two
    service methods used to pull the data — wired here so each handler
    names its own time window (today / week / month) without duplicating
    the render-and-send boilerplate.
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = await _resolve_user(update, context)
        if not user:
            return

        expense_service = ExpenseService()
        total = await fetch_total(expense_service, user.id)
        breakdown, has_untagged = await fetch_breakdown(expense_service, user.id)

        html = render_tag_breakdown_table(
            breakdown, has_untagged, total, _title=title
        )
        await _send_with_fallback(
            context,
            update.effective_chat.id,
            html,
            _plain_text_breakdown_message(title, total, breakdown, has_untagged),
        )

    return handler


async def latest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /latest [count] command.

    Sends the transactions as a Rich Message table; falls back to plain
    text on send failure.
    """
    user = await _resolve_user(update, context)
    if not user:
        return

    count = _parse_count(context.args, default_count=10, max_count=50)
    expense_service = ExpenseService()
    transactions = await expense_service.get_latest_transactions(user.id, count)

    chat_id = update.effective_chat.id
    remember_recent(chat_id, [t.id for t in transactions])

    title = "Latest transactions"
    html = render_transactions_table(transactions, _title=title)
    await _send_with_fallback(
        context, chat_id, html, format_transactions(transactions, title)
    )


today_handler = make_spending_breakdown_handler(
    "Today's spending",
    ExpenseService.get_today_spending,
    ExpenseService.get_today_spending_by_tag,
)

week_handler = make_spending_breakdown_handler(
    "This week's spending",
    ExpenseService.get_week_spending,
    ExpenseService.get_week_spending_by_tag,
)

month_handler = make_spending_breakdown_handler(
    "This month's spending",
    ExpenseService.get_month_spending,
    ExpenseService.get_month_spending_by_tag,
)


async def range_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /range <start> <end> command."""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /range <start> <end>\n"
            "Example: /range 2024-01-01 2024-01-31"
        )
        return

    start_str, end_str = args[0], args[1]
    try:
        start_date = parse_date(start_str)
        end_date = parse_date(end_str)
    except ValueError:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
        return

    user = await _resolve_user(update, context)
    if not user:
        return

    expense_service = ExpenseService()
    transactions, total_count, is_truncated = await expense_service.get_range_transactions(
        user.id, start_date, end_date
    )

    chat_id = update.effective_chat.id
    title = f"Transactions from {start_str} to {end_str}"
    # Always remember the index before sending so /delete and /edit
    # work off the same numbering the user sees in the table.
    remember_recent(chat_id, [t.id for t in transactions])

    fallback_text = f"{title}:\n\n"
    if transactions:
        fallback_text += "\n".join(
            format_transaction(txn, i) for i, txn in enumerate(transactions, 1)
        )
    else:
        fallback_text += "No transactions found."
    fallback_text += f"\n\nTotal: {total_count}"
    if is_truncated:
        fallback_text += " (showing first 200, results truncated)"

    html = render_transactions_table(transactions, _title=title)
    await _send_with_fallback(context, chat_id, html, fallback_text)

    # On the rich-message path we can't include a footer text, so if
    # there were truncated results we send a follow-up note.
    if is_truncated:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Total: {total_count} (showing first 200, results truncated)",
        )


async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search <merchant> command."""
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /search <merchant>")
        return

    user = await _resolve_user(update, context)
    if not user:
        return

    merchant = " ".join(args)
    expense_service = ExpenseService()
    transactions = await expense_service.search_transactions(user.id, merchant)

    chat_id = update.effective_chat.id
    title = f'Search results for "{merchant}"'
    remember_recent(chat_id, [t.id for t in transactions])

    html = render_transactions_table(transactions, _title=title)
    await _send_with_fallback(
        context, chat_id, html, format_transactions(transactions, title)
    )