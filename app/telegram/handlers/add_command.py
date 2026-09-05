"""/add command handler.

The `/add` command lets a user manually record a transaction by typing
all fields directly in the chat. It's the manual counterpart to the
automatic email-ingestion pipeline; the two paths converge on
:class:`app.services.expense.ExpenseService` (and from there on the
same DB schema).

The command signature is intentionally simple:
``/add <amount> <merchant> [description...] [--date YYYY-MM-DD]``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from app.database.enums import PaymentMethod
from app.database.repositories.user import UserRepository
from app.services.expense import ExpenseService
from app.telegram.auth import auth_handler
from app.telegram.handlers._formatting import (
    describe_tag_for_display,
    format_amount,
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
        f"Tag: {describe_tag_for_display(txn)}"
    )


__all__ = ["add_handler"]
