import structlog

from telegram import Update
from telegram.ext import ContextTypes

from app.database.repositories.user import UserRepository
from app.services.expense import ExpenseService
from app.services.categorizer import DEFAULT_TAGS
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import (
    format_amount,
    format_transaction,
    format_transactions,
    remember_recent,
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


def _format_tag_breakdown(
    breakdown: dict[str, float],
    has_untagged: bool,
    total: float,
) -> str:
    """Render a per-tag breakdown as a plain-text block.

    ``breakdown`` maps ``tag -> signed_sum``. Tags are printed in
    fixed-enum order so the output stays stable run-to-run, with any
    unknown tags appended at the bottom (defensive — should never
    happen given the strict ``/tag`` validation).
    """
    if not breakdown and not has_untagged:
        return ""

    lines = ["By tag:"]
    seen: set[str] = set()
    for tag in DEFAULT_TAGS:
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


async def latest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /latest [count] command.

    Sends a Bot API 10.1 Rich Message with the transactions rendered as a
    native ``<table>``. Falls back to a plain text message if the API
    rejects the rich-message payload (e.g. on older clients / API).
    """
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id
    count = _parse_count(context.args, default_count=10, max_count=50)

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    transactions = await expense_service.get_latest_transactions(user.id, count)

    remember_recent(chat_id, [t.id for t in transactions])

    title = "Latest transactions"
    html = render_transactions_table(transactions, _title=title)
    try:
        await send_rich_message(context.bot, chat_id, html)
    except Exception as e:
        # Fall back to plain text if Rich Messages aren't supported
        # (older API version, network glitch, etc.).
        logger.warning("rich_message_send_failed", error=str(e))
        await update.message.reply_text(
            format_transactions(transactions, title)
        )


async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /today command."""
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    total = await expense_service.get_today_spending(user.id)
    breakdown, has_untagged = await expense_service.get_today_spending_by_tag(user.id)

    text = f"Today's spending: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
    breakdown_text = _format_tag_breakdown(breakdown, has_untagged, total)
    if breakdown_text:
        text += "\n\n" + breakdown_text
    await update.message.reply_text(text)


async def week_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /week command."""
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    total = await expense_service.get_week_spending(user.id)
    breakdown, has_untagged = await expense_service.get_week_spending_by_tag(user.id)

    text = f"This week's spending: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
    breakdown_text = _format_tag_breakdown(breakdown, has_untagged, total)
    if breakdown_text:
        text += "\n\n" + breakdown_text
    await update.message.reply_text(text)


async def month_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /month command."""
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    total = await expense_service.get_month_spending(user.id)
    breakdown, has_untagged = await expense_service.get_month_spending_by_tag(user.id)

    text = f"This month's spending: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
    breakdown_text = _format_tag_breakdown(breakdown, has_untagged, total)
    if breakdown_text:
        text += "\n\n" + breakdown_text
    await update.message.reply_text(text)


async def range_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /range <start> <end> command."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /range <start> <end>\n"
            "Example: /range 2024-01-01 2024-01-31"
        )
        return

    chat_id = update.effective_chat.id
    start_str, end_str = args[0], args[1]

    try:
        start_date = parse_date(start_str)
        end_date = parse_date(end_str)
    except ValueError:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
        return

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    transactions, total_count, is_truncated = await expense_service.get_range_transactions(
        user.id, start_date, end_date
    )

    title = f"Transactions from {start_str} to {end_str}"
    # Always remember the index before sending so /delete and /edit
    # work off the same numbering the user sees in the table.
    remember_recent(chat_id, [t.id for t in transactions])

    html = render_transactions_table(transactions, _title=title)
    try:
        await send_rich_message(context.bot, chat_id, html)
    except Exception as e:
        logger.warning("rich_message_send_failed", error=str(e))
        # Fall back to plain text.
        text = f"{title}:\n\n"
        if transactions:
            text += "\n".join(
                format_transaction(txn, i) for i, txn in enumerate(transactions, 1)
            )
        else:
            text += "No transactions found."
        text += f"\n\nTotal: {total_count}"
        if is_truncated:
            text += " (showing first 200, results truncated)"
        await update.message.reply_text(text)
        return

    # On the rich-message path we can't include a footer text, so if
    # there were truncated results we send a follow-up note.
    if is_truncated:
        await update.message.reply_text(
            f"Total: {total_count} (showing first 200, results truncated)"
        )


async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search <merchant> command."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /search <merchant>")
        return

    chat_id = update.effective_chat.id
    merchant = " ".join(args)

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    transactions = await expense_service.search_transactions(user.id, merchant)

    title = f'Search results for "{merchant}"'
    remember_recent(chat_id, [t.id for t in transactions])

    html = render_transactions_table(transactions, _title=title)
    try:
        await send_rich_message(context.bot, chat_id, html)
    except Exception as e:
        logger.warning("rich_message_send_failed", error=str(e))
        # Fall back to plain text.
        await update.message.reply_text(format_transactions(transactions, title))