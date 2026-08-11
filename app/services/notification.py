from decimal import Decimal

import structlog
from telegram.ext import Application

from app.database.models.transaction import Transaction
from app.database.repositories.user import UserRepository
from app.utils.timezone import utc_to_sgt

logger = structlog.get_logger()


def _format_amount(amount: float | Decimal) -> str:
    return f"S${abs(float(amount)):.2f}"


def format_transaction_notification(txn: Transaction) -> str:
    """Format a transaction for Telegram notification."""
    time_sgt = utc_to_sgt(txn.transaction_time)
    verb = "spent" if txn.amount >= 0 else "received"
    category = txn.category or "-"
    if category != "-":
        # Title-case the first letter so users see "Food" instead of
        # "food" in the alert. The DB stores it lowercased.
        category = category.capitalize()
    return (
        f"�� New transaction recorded\n"
        f"You {verb} {_format_amount(txn.amount)} at {txn.merchant}\n"
        f"Time: {time_sgt.strftime('%d %b %Y %H:%M')}\n"
        f"Method: {txn.payment_method.value}\n"
        f"Category: {category}"
    )


class NotificationService:
    """Sends transaction notifications to users via Telegram.

    Holds a reference to the bot's ``Application`` so it can push messages
    from background tasks (e.g. the email poller) without coupling the
    ingestion flow to the bot's lifecycle directly.
    """

    def __init__(self, application: Application, user_repo: UserRepository | None = None):
        self._application = application
        self._user_repo = user_repo or UserRepository()

    async def notify_transaction(self, user_id: int, txn: Transaction) -> bool:
        """Send a Telegram message to the owner of ``user_id`` announcing
        ``txn``. Returns True iff the message was sent successfully.

        Looks up the user's ``telegram_chat_id`` from the database; missing
        or inactive users are silently skipped (and logged) so a broken
        notification path can't prevent a transaction from being recorded.
        """
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            logger.warning("notify_user_not_found", user_id=user_id)
            return False

        text = format_transaction_notification(txn)
        try:
            await self._application.bot.send_message(
                chat_id=user.telegram_chat_id,
                text=text,
            )
        except Exception as e:
            logger.error(
                "notify_failed",
                user_id=user_id,
                chat_id=user.telegram_chat_id,
                error=str(e),
            )
            return False
        return True