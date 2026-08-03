from datetime import datetime
from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from app.database.enums import PaymentMethod
from app.database.repositories.user import UserRepository
from app.services.expense import ExpenseService
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import (
    _pending_deletes,
    clear_recent,
    format_amount,
    resolve_recent,
)
from app.utils.timezone import now_sgt, parse_date, utc_to_sgt


async def add_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add <amount> <merchant> [description...] [--date YYYY-MM-DD] command."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /add <amount> <merchant> [description...] [--date YYYY-MM-DD]\n"
            "Example: /add 25.50 Lunch\n"
            'Example: /add 25.50 Lunch "with colleagues" --date 2024-12-25\n'
            "Note: Use a negative amount for refunds (e.g., -10.00)."
        )
        return

    chat_id = update.effective_chat.id

    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /add <amount> <merchant> [description...] [--date YYYY-MM-DD]"
        )
        return

    # Parse amount (keep sign as entered)
    try:
        amount = Decimal(args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount. Please enter a number.")
        return

    transaction_date: datetime | None = None
    if len(args) >= 2 and args[-2] == "--date":
        try:
            transaction_date = parse_date(args[-1])
        except ValueError:
            await update.message.reply_text(
                "Invalid date. Use YYYY-MM-DD after --date, e.g. --date 2024-12-25"
            )
            return
        args = args[:-2]
    if transaction_date is None:
        transaction_date = now_sgt()

    merchant = args[1]
    description = " ".join(args[2:]) if len(args) > 2 else None
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
    """Handle /edit <index> <field> <value> command.

    ``index`` is the 1-based row number from the most recent /latest,
    /search, or /range result. If no list is cached (or the index is out
    of range) the user is told to run a list command first.
    """
    if not await auth_handler(update, context):
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: /edit <index> <field> <value>\n"
            "Fields: amount, merchant, description, transaction_time\n"
            "Example: /edit 2 merchant \"Bus/MRT\"\n"
            "Run /latest (or /search, /range) first to see the index."
        )
        return

    chat_id = update.effective_chat.id

    txn_id = resolve_recent(chat_id, args[0])
    if txn_id is None:
        await update.message.reply_text(
            "Invalid index. Run /latest, /search, or /range first to see "
            "the list, then use the number from that list."
        )
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
        await update.message.reply_text(
            f"Transaction {txn_id} updated!"
        )
        clear_recent(chat_id)
    else:
        await update.message.reply_text("Transaction not found.")


async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete <index> command (first step of two-step delete).

    ``index`` is the 1-based row number from the most recent /latest,
    /search, or /range result. A pending delete stays valid until
    /confirm or /cancel is sent.
    """
    if not await auth_handler(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /delete <index>\n"
            "Example: /delete 2   (deletes the 2nd row from the most recent "
            "/latest, /search, or /range)"
        )
        return

    chat_id = update.effective_chat.id

    txn_id = resolve_recent(chat_id, args[0])
    if txn_id is None:
        await update.message.reply_text(
            "Invalid index. Run /latest, /search, or /range first to see "
            "the list, then use the number from that list."
        )
        return

    _pending_deletes.setdefault(chat_id, set()).add(txn_id)
    await update.message.reply_text(
        f"To confirm deletion of transaction {txn_id}, send /confirm {txn_id}\n"
        f"Or /cancel {txn_id} to abort."
    )


async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /confirm <index> command (second step of two-step delete)."""
    if not await auth_handler(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /confirm <index>")
        return

    chat_id = update.effective_chat.id

    txn_id = resolve_recent(chat_id, args[0])
    if txn_id is None:
        await update.message.reply_text(
            "Invalid index. Run /latest, /search, or /range first to see "
            "the list, then use the number from that list."
        )
        return

    pending = _pending_deletes.get(chat_id, set())
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
        _pending_deletes[chat_id].discard(txn_id)
        if not _pending_deletes[chat_id]:
            _pending_deletes.pop(chat_id, None)
        clear_recent(chat_id)
        await update.message.reply_text(f"Transaction {txn_id} deleted.")
        return

    await update.message.reply_text("Transaction not found or not owned by you.")


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel <index> to abort a pending delete."""
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        # No index supplied: drop everything for this chat.
        had_pending = bool(_pending_deletes.pop(chat_id, None))
        if had_pending:
            await update.message.reply_text("All pending deletes cancelled.")
        else:
            await update.message.reply_text("No pending deletes.")
        return

    txn_id = resolve_recent(chat_id, args[0])
    if txn_id is None:
        await update.message.reply_text(
            "Invalid index. Run /latest, /search, or /range first to see "
            "the list, then use the number from that list."
        )
        return

    pending = _pending_deletes.get(chat_id)
    if pending and txn_id in pending:
        pending.discard(txn_id)
        if not pending:
            _pending_deletes.pop(chat_id, None)
        await update.message.reply_text(f"Pending delete for {txn_id} cancelled.")
    else:
        await update.message.reply_text(f"No pending delete for {txn_id}.")
