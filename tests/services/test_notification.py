"""Unit tests for the NotificationService.

The service looks up a user's chat_id and forwards a formatted message via
the Telegram bot's Application. Both legs are mocked here.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.database.enums import PaymentMethod
from app.database.models.transaction import Transaction
from app.database.models.user import User
from app.services.notification import NotificationService, format_transaction_notification


def _fake_user(user_id: int = 42, chat_id: int = 9999) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.telegram_chat_id = chat_id
    user.deleted_at = None
    return user


def _fake_txn(
    amount: str = "3.98",
    merchant: str = "STARBUCKS",
    tag: str | None = None,
) -> MagicMock:
    txn = MagicMock()
    txn.amount = Decimal(amount)
    txn.merchant = merchant
    txn.payment_method = PaymentMethod.DBS_CC
    txn.transaction_time = datetime(2026, 7, 16, 12, 39)
    txn.tag = tag
    return txn


class TestFormatTransactionNotification:
    def test_purchase_uses_spent(self):
        text = format_transaction_notification(_fake_txn())
        assert "spent" in text
        assert "S$3.98" in text
        assert "STARBUCKS" in text
        assert "DBS_CC" in text

    def test_refund_uses_received_and_abs_amount(self):
        text = format_transaction_notification(_fake_txn(amount="-25.50", merchant="GRAB"))
        assert "received" in text
        assert "S$25.50" in text
        assert "GRAB" in text

    def test_includes_tag_when_present(self):
        text = format_transaction_notification(_fake_txn(tag="food"))
        assert "Tag: Food" in text

    def test_shows_dash_when_tag_null(self):
        text = format_transaction_notification(_fake_txn(tag=None))
        assert "Tag: -" in text

    def test_capitalizes_only_first_letter(self):
        text = format_transaction_notification(_fake_txn(tag="shopping"))
        assert "Tag: Shopping" in text
        text = format_transaction_notification(_fake_txn(tag="FOOD"))
        assert "Tag: Food" in text


class TestNotifyTransaction:
    @pytest.mark.asyncio
    async def test_sends_to_users_chat_id(self):
        send_message = AsyncMock()
        app = MagicMock()
        app.bot.send_message = send_message
        user_repo = MagicMock()
        user_repo.get_by_id = AsyncMock(return_value=_fake_user(user_id=42, chat_id=7777))

        service = NotificationService(application=app, user_repo=user_repo)
        ok = await service.notify_transaction(42, _fake_txn())

        assert ok is True
        send_message.assert_awaited_once()
        kwargs = send_message.await_args.kwargs
        assert kwargs["chat_id"] == 7777
        assert "STARBUCKS" in kwargs["text"]

    @pytest.mark.asyncio
    async def test_returns_false_when_user_missing(self):
        send_message = AsyncMock()
        app = MagicMock()
        app.bot.send_message = send_message
        user_repo = MagicMock()
        user_repo.get_by_id = AsyncMock(return_value=None)

        service = NotificationService(application=app, user_repo=user_repo)
        ok = await service.notify_transaction(42, _fake_txn())

        assert ok is False
        send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_when_send_raises(self):
        send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
        app = MagicMock()
        app.bot.send_message = send_message
        user_repo = MagicMock()
        user_repo.get_by_id = AsyncMock(return_value=_fake_user())

        service = NotificationService(application=app, user_repo=user_repo)
        ok = await service.notify_transaction(42, _fake_txn())

        assert ok is False