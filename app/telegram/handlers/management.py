from datetime import datetime
from decimal import Decimal
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from app.database.enums import PaymentMethod
from app.database.repositories.transaction import TransactionRepository
from app.database.repositories.user import UserRepository
from app.services.expense import ExpenseService, InvalidEditValue
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import (
    _pending_deletes,
    clear_recent,
    describe_category_for_display,
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
        f"Time: {time_sgt.strftime('%d %b %Y %H:%M')}\n"
        f"Category: {describe_category_for_display(txn)}"
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
    # Signature: edit_transaction(transaction_id, user_id, field, value) — txn first.
    try:
        txn = await expense_service.edit_transaction(txn_id, user.id, field, value)
    except InvalidEditValue as exc:
        await update.message.reply_text(str(exc))
        return

    if txn:
        await update.message.reply_text(
            "Transaction updated!"
        )
        clear_recent(chat_id)
    else:
        await update.message.reply_text("Transaction not found.")


def _describe(txn: Any) -> str:
    """Render a single transaction as a one-liner for the delete prompt."""
    time_sgt = utc_to_sgt(txn.transaction_time)
    sign = "-" if txn.amount < 0 else "+"
    return (
        f"You {('spent' if txn.amount >= 0 else 'received')} "
        f"{sign}{format_amount(txn.amount)} at {txn.merchant}\n"
        f"   {time_sgt.strftime('%d %b %Y %H:%M')} | {txn.payment_method.value}\n"
        f"   Category: {describe_category_for_display(txn)}"
    )


def _resolve_pending(chat_id: int, args: list[str]) -> int | None:
    """Pick the txn_id the user means.

    - No args + exactly one pending → that one.
    - No args + multiple pendings → None (caller should tell the user to be explicit).
    - One arg → resolve via the recent-index cache; must also be in the
      pending set.

    Returns ``None`` if the args were malformed or ambiguous.
    """
    pending = _pending_deletes.get(chat_id, set())
    if not args:
        return next(iter(pending)) if len(pending) == 1 else None
    txn_id = resolve_recent(chat_id, args[0])
    if txn_id is None or txn_id not in pending:
        return None
    return txn_id


async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete <index> command (first step of two-step delete).

    ``index`` is the 1-based row number from the most recent /latest,
    /search, or /range result. After arming the delete, the bot shows the
    transaction details so the user can verify what they're about to drop,
    then prompts them to send ``/confirm`` or ``/cancel`` (no index needed).
    """
    if not await auth_handler(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /delete <index>\n"
            "Example: /delete 2   (the 2nd row from the most recent "
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

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    txn = await TransactionRepository().get_by_id_for_user(txn_id, user.id)
    if txn is None:
        await update.message.reply_text("Transaction not found.")
        return

    _pending_deletes.setdefault(chat_id, set()).add(txn_id)
    await update.message.reply_text(
        f"About to delete:\n{_describe(txn)}\n\n"
        f"Send /confirm to delete, or /cancel to abort."
    )


async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /confirm (no args) to act on the most-recently-armed delete.

    An optional ``<index>`` arg is still accepted for the case where the
    user has armed multiple deletes and wants to disambiguate.
    """
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id

    if not _pending_deletes.get(chat_id):
        await update.message.reply_text(
            "Nothing to confirm. Use /delete <index> first."
        )
        return

    txn_id = _resolve_pending(chat_id, context.args)
    if txn_id is None:
        if context.args:
            await update.message.reply_text(
                "Invalid index or no pending delete for that row. "
                "Send /confirm alone to act on the only pending delete, "
                "or /cancel to abort."
            )
        else:
            await update.message.reply_text(
                "Multiple deletes are pending. Specify which one, e.g. "
                "/confirm <index>, or /cancel to abort them all."
            )
        return

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    # Signature: delete_transaction(transaction_id, user_id) — txn first.
    success = await expense_service.delete_transaction(txn_id, user.id)
    if success:
        _pending_deletes[chat_id].discard(txn_id)
        if not _pending_deletes[chat_id]:
            _pending_deletes.pop(chat_id, None)
        clear_recent(chat_id)
        await update.message.reply_text(f"Transaction deleted.")
        return

    await update.message.reply_text("Transaction not found or not owned by you.")


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel to abort pending delete(s).

    No args: cancels all pending deletes for this chat.
    With an index: cancels only the matching pending delete.
    """
    if not await auth_handler(update, context):
        return

    chat_id = update.effective_chat.id
    args = context.args

    if not args:
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
        await update.message.reply_text("Pending delete cancelled.")
    else:
        await update.message.reply_text("No pending delete for that row.")


async def categorize_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /categorize <index> command.

    Re-runs the LLM categorizer on a single transaction and updates
    the stored ``category``. Use when:
    - the LLM failed during insert (category is NULL),
    - the LLM picked the wrong category,
    - the merchant string has changed and you want a fresh pick.
    """
    if not await auth_handler(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /categorize <index>\n"
            "Re-runs the LLM categorizer on the transaction at that index."
        )
        return

    chat_id = update.effective_chat.id
    index_or_id = args[0]

    txn_id = resolve_recent(chat_id, index_or_id)
    if txn_id is None:
        try:
            txn_id = int(index_or_id)
        except ValueError:
            await update.message.reply_text(
                "Invalid index. Run /latest, /search, or /range first to see "
                "the list, then use the number from that list."
            )
            return

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    txn = await expense_service.recategorize(txn_id, user.id)
    if not txn:
        await update.message.reply_text("Transaction not found.")
        return

    # Reload to reflect the updated category.
    txn = await TransactionRepository().get_by_id_for_user(txn_id, user.id)
    if txn.category:
        await update.message.reply_text(
            f"Category: {describe_category_for_display(txn)}\n"
            f"Merchant: {txn.merchant}"
        )
    else:
        await update.message.reply_text(
            "Could not generate a category (LLM not configured or rejected). "
            "Set one manually with /edit <index> category <value>."
        )
