from telegram import Update
from telegram.ext import ContextTypes

from app.database.repositories.user import UserRepository
from app.services.expense import ExpenseService
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import format_amount, format_transaction, format_transactions
from app.utils.timezone import parse_date


async def latest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /latest [count] command."""
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id
    args = context.args

    # Parse count
    count = 10
    if args:
        try:
            count = min(int(args[0]), 50)
        except ValueError:
            count = 10

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    transactions = await expense_service.get_latest_transactions(user.id, count)

    text = format_transactions(transactions, f"Latest {len(transactions)} transactions")
    await update.message.reply_text(text)


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

    text = f"Today's spending: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
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

    text = f"This week's spending: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
    await update.message.reply_text(text)


async def month_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /thismonth command."""
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

    text = f"This month's spending: {format_amount(total)}"
    if total < 0:
        text += " (net credit)"
    await update.message.reply_text(text)


async def range_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /range <start> <end> command."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /range <start> <end>\nExample: /range 2024-01-01 2024-01-31")
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

    text = f"Transactions from {start_str} to {end_str}:\n\n"
    if transactions:
        text += "\n".join(format_transaction(txn, i) for i, txn in enumerate(transactions, 1))
    else:
        text += "No transactions found."
    text += f"\n\nTotal: {total_count}"
    if is_truncated:
        text += " (showing first 200, results truncated)"

    await update.message.reply_text(text)


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

    text = format_transactions(transactions, f'Search results for "{merchant}"')
    await update.message.reply_text(text)
