"""Delete command flow (/delete, /confirm, /cancel).

Deletes use a two-step protocol to avoid accidental data loss:

1. ``/delete <index>`` arms a pending delete — the bot shows the transaction
   details and prompts ``/confirm`` or ``/cancel``.
2. ``/confirm [index]`` executes the delete. With no argument when exactly
   one delete is pending it acts on that one; when multiple are armed
   the index disambiguates.
3. ``/cancel [index]`` aborts. No argument cancels every pending delete
   for this chat; with an index it cancels only that one.

All three commands share the ``_pending_deletes`` dict and the recent-index
cache in :mod:`app.telegram.handlers._state`, and both
``describe`` + ``_resolve_pending`` are helpers only used within this
module.
"""

from __future__ import annotations

from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from app.database.repositories.transaction import TransactionRepository
from app.database.repositories.user import UserRepository
from app.services.expense import ExpenseService
from app.telegram.auth import auth_handler
from app.telegram.handlers._formatting import (
    describe_tag_for_display,
    format_amount,
)
from app.telegram.handlers._state import (
    _pending_deletes,
    clear_recent,
    resolve_recent,
)
from app.utils.timezone import utc_to_sgt


def _describe(txn: Any) -> str:
    """Render a single transaction as a one-liner for the delete prompt."""
    time_sgt = utc_to_sgt(txn.transaction_time)
    sign = "-" if txn.amount < 0 else "+"
    return (
        f"You {('spent' if txn.amount >= 0 else 'received')} "
        f"{sign}{format_amount(txn.amount)} at {txn.merchant}\n"
        f"   {time_sgt.strftime('%d %b %Y %H:%M')} | {txn.payment_method.value}\n"
        f"   Tag: {describe_tag_for_display(txn)}"
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
        await update.message.reply_text("Transaction deleted.")
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


__all__ = [
    "delete_handler",
    "confirm_handler",
    "cancel_handler",
    "_describe",
    "_resolve_pending",
]
