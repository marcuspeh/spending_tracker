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
    describe_tag_for_display,
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
        f"Tag: {describe_tag_for_display(txn)}"
    )


async def _apply_field_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    field: str,
    value: str,
) -> None:
    """Resolve the index, fetch the user, and apply ``field=value``.

    Shared by every per-field edit shortcut (:func:`amount_handler`,
    :func:`merchant_handler`, :func:`description_handler`,
    :func:`time_handler`, :func:`tag_handler`). The ``field`` is the
    database column name (``amount``, ``merchant``, ``description``,
    ``transaction_time``, ``tag``); ``value`` is the user-supplied
    string already validated by the caller.
    """
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            f"Usage: /{field} <index> <value>\n"
            f"Example: /{field} 2 {('12.50' if field == 'amount' else 'Bus/MRT')}\n"
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

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    expense_service = ExpenseService()
    try:
        txn = await expense_service.edit_transaction(txn_id, user.id, field, value)
    except InvalidEditValue as exc:
        await update.message.reply_text(str(exc))
        return

    if txn:
        await update.message.reply_text(
            f"Updated transaction {txn.id}: {field}={value}"
        )
        clear_recent(chat_id)
    else:
        await update.message.reply_text("Transaction not found.")


async def amount_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /amount <index> <value> command."""
    if not await auth_handler(update, context):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /amount <index> <value>\n"
            "Example: /amount 2 12.50\n"
            "Use a negative value for refunds, e.g. /amount 2 -5.00."
        )
        return
    await _apply_field_edit(update, context, "amount", args[1])


async def merchant_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /merchant <index> <value...> command."""
    if not await auth_handler(update, context):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /merchant <index> <merchant>\n"
            "Example: /merchant 2 Bus/MRT"
        )
        return
    value = " ".join(args[1:])
    await _apply_field_edit(update, context, "merchant", value)


async def description_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /description <index> <value...> command."""
    if not await auth_handler(update, context):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /description <index> <text>\n"
            "Use /description <index> - to clear."
        )
        return
    value = " ".join(args[1:])
    await _apply_field_edit(update, context, "description", value)


async def time_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /time <index> <value> command.

    Accepts ``YYYY-MM-DD`` (midnight SGT) or ``YYYY-MM-DD HH:MM``
    (24-hour SGT). Stored as UTC internally.
    """
    if not await auth_handler(update, context):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /time <index> <YYYY-MM-DD [HH:MM]>\n"
            "Example: /time 2 2026-04-04 16:00\n"
            "Default time when only a date is given: 00:00 SGT."
        )
        return
    value = " ".join(args[1:])

    # Parse here so we can accept both YYYY-MM-DD and YYYY-MM-DD HH:MM.
    # The bare ``edit_transaction`` path only accepts YYYY-MM-DD via
    # parse_date; we lift that restriction for /time.
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

    parsed_time = _parse_time_value(value)
    if parsed_time is None:
        await update.message.reply_text(
            f"Invalid time: {value!r}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM."
        )
        return

    expense_service = ExpenseService()
    txn = await expense_service.edit_transaction(
        txn_id, user.id, "transaction_time", parsed_time
    )
    if txn:
        await update.message.reply_text(
            f"Updated transaction {txn.id}: transaction_time={parsed_time.isoformat()}"
        )
        clear_recent(chat_id)
    else:
        await update.message.reply_text("Transaction not found.")


def _parse_time_value(value: str) -> datetime | None:
    """Parse a ``/time`` argument into a tz-aware SGT datetime.

    Accepts ``YYYY-MM-DD`` (midnight SGT) or ``YYYY-MM-DD HH:MM``
    (24-hour SGT). Returns ``None`` on any parse failure — the caller
    surfaces a friendly error message.
    """
    from app.utils.timezone import SGT

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=SGT)
        except ValueError:
            continue
    return None


async def tag_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /tag <index> <value...> command.

    Sets the LLM-driven tag on the transaction. Use one of the
    fixed tags (``food``, ``transport``, ``other``, …) or any
    free-form label — both are accepted.
    Pass a single ``-`` to clear the tag.
    """
    if not await auth_handler(update, context):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /tag <index> <value>\n"
            "Common tags: food, transport, groceries, shopping, "
            "subscriptions, health, entertainment, travel, transfers, "
            "fees, refunds, cash, other.\n"
            "Use /tag <index> - to clear."
        )
        return
    value = " ".join(args[1:])
    if value == "-":
        value = ""  # repo's _normalize_tag turns "" into None.
    await _apply_field_edit(update, context, "tag", value)


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
