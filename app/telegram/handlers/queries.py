import structlog

from telegram import Update
from telegram.ext import ContextTypes

from app.database.repositories.user import UserRepository
from app.services.expense import ExpenseService
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import (
    format_amount,
    format_transaction,
    format_transactions,
    remember_recent,
    render_latest_table,
    send_rich_message,
)
from app.utils.timezone import parse_date

logger = structlog.get_logger()


def _parse_count_and_tag(
    args: list[str] | None,
    default_count: int = 10,
    max_count: int = 50,
) -> tuple[int, str | None]:
    """Parse ``[count] [tag]`` from a command's args.

    Returns: ``(count, tag)``. The first arg is treated as a count if
    it parses as an integer; otherwise the first arg is the tag and the
    count falls back to ``default_count``. Any leftover args are joined
    with spaces as a single tag (so multi-word tags work, e.g. ``coffee
    daily``).
    """
    if not args:
        return default_count, None

    count = default_count
    rest = args
    try:
        count = min(int(args[0]), max_count)
        rest = args[1:]
    except ValueError:
        # First arg isn't a number — treat everything as a tag.
        pass

    tag = " ".join(rest).strip() or None
    return count, tag


async def latest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /latest [count] [tag] command.

    Sends a Bot API 10.1 Rich Message with the transactions rendered as a
    native ``<table>``. Falls back to a plain text message if the API
    rejects the rich-message payload (e.g. on older clients / API).
    """
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id
    count, tag = _parse_count_and_tag(context.args, default_count=10, max_count=50)

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    transactions = await expense_service.get_latest_transactions(user.id, count, tag=tag)

    remember_recent(chat_id, [t.id for t in transactions])

    title = "Latest transactions" if tag is None else f'Latest transactions (tag: {tag})'
    html = render_latest_table(transactions, _title=title)
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
    """Handle /today [tag] command."""
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id
    tag = context.args[0] if context.args else None

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    total = await expense_service.get_today_spending(user.id, tag=tag)

    prefix = "Today's spending" if tag is None else f"Today's spending (tag: {tag})"
    text = f"{prefix}: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
    await update.message.reply_text(text)


async def week_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /week [tag] command."""
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id
    tag = context.args[0] if context.args else None

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    total = await expense_service.get_week_spending(user.id, tag=tag)

    prefix = "This week's spending" if tag is None else f"This week's spending (tag: {tag})"
    text = f"{prefix}: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
    await update.message.reply_text(text)


async def month_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /thismonth [tag] command."""
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id
    tag = context.args[0] if context.args else None

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    total = await expense_service.get_month_spending(user.id, tag=tag)

    prefix = "This month's spending" if tag is None else f"This month's spending (tag: {tag})"
    text = f"{prefix}: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
    await update.message.reply_text(text)


async def range_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /range <start> <end> [tag] command."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /range <start> <end> [tag]\n"
            "Example: /range 2024-01-01 2024-01-31 coffee"
        )
        return

    chat_id = update.effective_chat.id
    start_str, end_str = args[0], args[1]
    tag = " ".join(args[2:]).strip() or None

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
        user.id, start_date, end_date, tag=tag
    )

    title = (
        f"Transactions from {start_str} to {end_str}"
        if tag is None
        else f'Transactions from {start_str} to {end_str} (tag: {tag})'
    )
    text = f"{title}:\n\n"
    if transactions:
        text += "\n".join(format_transaction(txn, i) for i, txn in enumerate(transactions, 1))
    else:
        text += "No transactions found."
    text += f"\n\nTotal: {total_count}"
    if is_truncated:
        text += " (showing first 200, results truncated)"
    remember_recent(chat_id, [t.id for t in transactions])

    await update.message.reply_text(text)


async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search <merchant> [tag] command."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /search <merchant> [tag]")
        return

    chat_id = update.effective_chat.id
    merchant = " ".join(args)
    tag = None
    # If last arg(s) parse as a tag (after the merchant phrase), treat
    # last whitespace-separated word as the tag. Simple heuristic — users
    # who want multi-word tags via /search will need to use the bot's
    # /tag command instead.
    parts = args
    if len(parts) >= 2:
        candidate = parts[-1]
        if candidate.replace("_", "").isalnum():
            tag = candidate
            merchant = " ".join(parts[:-1])

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    transactions = await expense_service.search_transactions(user.id, merchant, tag=tag)

    title = f'Search results for "{merchant}"'
    if tag:
        title += f' (tag: {tag})'
    text = format_transactions(transactions, title)
    remember_recent(chat_id, [t.id for t in transactions])
    await update.message.reply_text(text)
