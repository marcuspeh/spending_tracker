"""Inline-keyboard callback handlers for the latest-transactions table.

The ``/latest`` command renders a paginated table whose rows and Prev/Next
buttons fire ``callback_query`` updates with ``callback_data`` strings of
the form ``latest:row:<index>``, ``latest:page:<n>``, or ``latest:noop``.

Tapping a row opens an Edit / Delete / Cancel submenu. Confirming a delete
re-uses the two-step logic from the management handlers so the user still
gets a ``/confirm`` prompt before the row is dropped.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.database.enums import PaymentMethod
from app.database.repositories.transaction import TransactionRepository
from app.database.repositories.user import UserRepository
from app.services.expense import ExpenseService
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import (
    LATEST_PAGE_SIZE,
    _pending_deletes,
    clear_recent,
    format_amount,
    remember_recent,
    render_latest_table,
    resolve_recent,
)
from app.utils.timezone import utc_to_sgt


async def _reply(query, text: str, **kwargs) -> None:
    """Answer the callback query (silences Telegram's spinner) and reply."""
    try:
        await query.answer()
    except Exception:
        pass
    await query.message.reply_text(text, **kwargs)


async def latest_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Dispatch inline-keyboard presses from the /latest table."""
    if not await auth_handler(update, context):
        return

    query = update.callback_query
    if query is None or not query.data:
        return

    chat_id = update.effective_chat.id
    parts = query.data.split(":")
    if len(parts) < 3 or parts[0] != "latest":
        return
    action = parts[1]
    arg = parts[2]

    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(chat_id)
    if not user:
        await _reply(query, "User not found.")
        return

    if action == "noop":
        await query.answer()
        return

    if action == "page":
        # Re-render the table at the requested page. We always pull 50 so
        # pagination across Prev/Next is consistent regardless of the
        # initial /latest <count> the user typed.
        page = max(1, int(arg))
        expense_service = ExpenseService()
        transactions = await expense_service.get_latest_transactions(user.id, 50)
        remember_recent(chat_id, [t.id for t in transactions])
        text, keyboard = render_latest_table(transactions, page=page)
        try:
            await query.edit_message_text(
                text=text, reply_markup=keyboard, parse_mode="Markdown"
            )
        except Exception:
            await query.answer()
        return

    if action == "row":
        # Show Edit / Delete / Cancel submenu for that row index.
        index = int(arg)
        txn_id = resolve_recent(chat_id, index)
        if txn_id is None:
            await _reply(
                query,
                "That row is no longer in the cache. Run /latest again.",
            )
            return

        txn_repo = TransactionRepository()
        txn = await txn_repo.get_by_id_for_user(txn_id, user.id)
        if not txn:
            await _reply(query, "Transaction not found.")
            return

        time_sgt = utc_to_sgt(txn.transaction_time)
        verb = "spent" if txn.amount >= 0 else "received"
        body = (
            f"Transaction {index}:\n"
            f"You {verb} {format_amount(txn.amount)} at {txn.merchant}\n"
            f"Time: {time_sgt.strftime('%d %b %Y %H:%M')}\n"
            f"Method: {txn.payment_method.value}"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Edit", callback_data=f"latest:edit:{index}"
                    ),
                    InlineKeyboardButton(
                        "Delete", callback_data=f"latest:delete:{index}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Cancel", callback_data="latest:cancel"
                    )
                ],
            ]
        )
        try:
            await query.edit_message_text(text=body, reply_markup=keyboard)
        except Exception:
            await query.answer()
        return

    if action == "edit":
        # Prompt the user for the next field/value via a free-text message.
        index = int(arg)
        txn_id = resolve_recent(chat_id, index)
        if txn_id is None:
            await _reply(query, "Run /latest again, the index expired.")
            return
        await _reply(
            query,
            f"Reply with: `/edit {index} <field> <value>`\n"
            f"Fields: amount, merchant, description, transaction_time\n"
            f"Example: `/edit {index} merchant \"Bus/MRT\"`",
            parse_mode="Markdown",
        )
        return

    if action == "delete":
        # Arm the two-step delete and confirm in the chat.
        index = int(arg)
        txn_id = resolve_recent(chat_id, index)
        if txn_id is None:
            await _reply(query, "Run /latest again, the index expired.")
            return
        _pending_deletes.setdefault(chat_id, set()).add(txn_id)
        await _reply(
            query,
            f"Pending delete for transaction {index}. "
            f"Send `/confirm {index}` to delete, or `/cancel {index}` to abort.",
            parse_mode="Markdown",
        )
        return

    if action == "cancel":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            await query.answer()
        return

    await query.answer()