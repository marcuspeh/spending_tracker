from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from app.database.enums import PaymentMethod
from app.database.repositories.user import UserRepository
from app.services.expense import ExpenseService
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import _pending_deletes, format_amount
from app.utils.timezone import now_sgt, parse_date, utc_to_sgt


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add <amount> <merchant> [description] [date] command."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /add <amount> <merchant> [description] [date]\n"
            "Example: /add 25.50 Lunch at restaurant\n"
            "Note: Use negative amount for refunds (e.g., -10.00)"
        )
        return

    chat_id = update.effective_chat.id

    # Parse amount (keep sign as entered)
    try:
        amount = Decimal(args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount. Please enter a number.")
        return

    merchant = args[1]
    description = None
    transaction_date = None

    if len(args) > 2:
        # Check if third arg is a date
        try:
            transaction_date = parse_date(args[2])
            if len(args) > 3:
                description = " ".join(args[3:])
        except ValueError:
            description = " ".join(args[2:])
            transaction_date = None

    if transaction_date is None:
        transaction_date = now_sgt()

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    txn = await expense_service.add_transaction(
        user_id=user.id,
        amount=float(amount),
        merchant=merchant,
        payment_method=PaymentMethod.MANUAL,
        transaction_time=transaction_date,
        description=description,
    )

    time_sgt = utc_to_sgt(txn.transaction_time)
    await update.message.reply_text(
        f"Transaction added!\n"
        f"{format_amount(txn.amount)} at {txn.merchant}\n"
        f"Time: {time_sgt.strftime('%d %b %Y %H:%M')}"
    )


async def edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /edit <id> <field> <value> command."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: /edit <id> <field> <value>\n"
            "Fields: amount, merchant, description, transaction_time\n"
            "Example: /edit 5 amount 30.00"
        )
        return

    chat_id = update.effective_chat.id

    try:
        txn_id = int(args[0])
    except ValueError:
        await update.message.reply_text("Invalid transaction ID.")
        return

    field = args[1]
    value = " ".join(args[2:])

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    txn = await expense_service.edit_transaction(user.id, txn_id, field, value)

    if txn:
        await update.message.reply_text("Transaction updated!")
    else:
        await update.message.reply_text("Transaction not found.")


async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete <id> command (first step of two-step delete)."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /delete <id>")
        return

    chat_id = update.effective_chat.id

    try:
        txn_id = int(args[0])
    except ValueError:
        await update.message.reply_text("Invalid transaction ID.")
        return

    # Store pending delete
    if chat_id not in _pending_deletes:
        _pending_deletes[chat_id] = []
    _pending_deletes[chat_id].append(txn_id)

    await update.message.reply_text(
        f"To confirm deletion of transaction {txn_id}, send /confirm {txn_id}"
    )


async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /confirm <id> command (second step of two-step delete)."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /confirm <id>")
        return

    chat_id = update.effective_chat.id

    try:
        txn_id = int(args[0])
    except ValueError:
        await update.message.reply_text("Invalid transaction ID.")
        return

    # Check if this delete was pending
    pending = _pending_deletes.get(chat_id, [])
    if txn_id not in pending:
        await update.message.reply_text(
            f"No pending delete for transaction {txn_id}. Use /delete {txn_id} first."
        )
        return

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    success = await expense_service.delete_transaction(user.id, txn_id)

    if success:
        # Remove from pending
        _pending_deletes[chat_id].remove(txn_id)
        await update.message.reply_text(f"Transaction {txn_id} deleted.")
    else:
        await update.message.reply_text("Transaction not found or not owned by you.")
