"""Per-field edit commands (/amount, /merchant, /description, /time, /tag).

All edit handlers share a common shape:

1. Parse the command-line arguments: ``/<field> <index> <value>``
2. Resolve ``<index>`` to a real transaction id via the recent-list cache.
3. Call :meth:`ExpenseService.edit_transaction` to apply the change.
4. Reply with a short success / failure message and drop the cached recent
   list so the user doesn't accidentally re-use a stale index.

The five per-field shortcuts plus the shared ``_apply_field_edit`` helper
live together here because they form a single cohesive feature area and
the shared helper is used by every one of them.
"""

from __future__ import annotations

from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from app.database.repositories.user import UserRepository
from app.services.categorizer import current_tags
from app.services.expense import ExpenseService, InvalidEditValue
from app.telegram.auth import auth_handler
from app.telegram.handlers._state import clear_recent, resolve_recent
from app.utils.timezone import SGT

# ---------------------------------------------------------------------------
# Shared edit primitive
# ---------------------------------------------------------------------------

async def _apply_field_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    field: str,
    value: str,
) -> None:
    """Resolve the index, fetch the user, and apply ``field=value``.

    Shared by every per-field edit shortcut. The ``field`` is the
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


# ---------------------------------------------------------------------------
# Individual field handlers
# ---------------------------------------------------------------------------

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

    Sets the tag on the transaction. The value MUST be one of the
    currently allowed tags (fetched live from config_store via
    :func:`app.services.categorizer.current_tags`) — free-form labels
    are rejected. Pass a single ``-`` to clear the tag.
    """
    if not await auth_handler(update, context):
        return
    args = context.args
    if len(args) < 2:
        allowed = current_tags()
        await update.message.reply_text(
            "Usage: /tag <index> <value>\n"
            f"Allowed values: {', '.join(allowed)}.\n"
            "Use /tag <index> - to clear."
        )
        return
    value = " ".join(args[1:])
    if value == "-":
        value = ""  # repo's _normalize_tag turns "" into None.
    else:
        allowed = current_tags()
        if value not in allowed:
            await update.message.reply_text(
                f"Invalid tag: {value!r}.\n"
                f"Allowed values: {', '.join(allowed)}."
            )
            return
    await _apply_field_edit(update, context, "tag", value)


__all__ = [
    "amount_handler",
    "merchant_handler",
    "description_handler",
    "time_handler",
    "tag_handler",
    "_apply_field_edit",
    "_parse_time_value",
]
