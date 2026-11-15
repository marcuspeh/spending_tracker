"""Tests for /latest [tag] [count] — the tag filter on the listing command."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.telegram.handlers import queries
from app.telegram.handlers.queries import _parse_latest_args, latest_handler


def _make_txn(txn_id: int = 101, merchant: str = "STARBUCKS") -> MagicMock:
    txn = MagicMock()
    txn.id = txn_id
    txn.merchant = merchant
    txn.tag = "food"
    txn.amount = 5.0
    txn.transaction_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return txn


def _make_update(chat_id: int = 42) -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args: list[str] | None = None) -> MagicMock:
    context = MagicMock()
    context.args = args
    context.bot.send_message = AsyncMock()
    context.bot._post = AsyncMock()
    return context


class TestParseLatestArgs:
    def test_no_args(self):
        assert _parse_latest_args(None) == (None, 10)
        assert _parse_latest_args([]) == (None, 10)

    def test_numeric_first_arg_is_a_count(self):
        assert _parse_latest_args(["20"]) == (None, 20)

    def test_count_is_capped(self):
        assert _parse_latest_args(["500"]) == (None, 50)

    def test_tag_only(self):
        assert _parse_latest_args(["food"]) == ("food", 10)

    def test_tag_and_count(self):
        assert _parse_latest_args(["food", "20"]) == ("food", 20)

    def test_tag_is_lowercased(self):
        assert _parse_latest_args(["FOOD"]) == ("food", 10)

    def test_tag_with_non_numeric_count_falls_back_to_default(self):
        assert _parse_latest_args(["food", "abc"]) == ("food", 10)


class TestLatestHandler:
    async def test_filters_by_tag(self):
        user = MagicMock()
        user.id = 7
        txn = _make_txn()

        expense_service = MagicMock()
        expense_service.get_latest_transactions = AsyncMock(return_value=[txn])

        update = _make_update()
        context = _make_context(["food", "5"])

        with patch.object(queries, "_resolve_user", new=AsyncMock(return_value=user)), \
             patch.object(queries, "ExpenseService", return_value=expense_service), \
             patch.object(queries, "current_tags", return_value=("food", "other")), \
             patch.object(queries, "send_rich_message", new=AsyncMock()):
            await latest_handler(update, context)

        expense_service.get_latest_transactions.assert_awaited_once_with(
            7, 5, "food"
        )

    async def test_numeric_arg_keeps_old_behaviour(self):
        user = MagicMock()
        user.id = 7
        expense_service = MagicMock()
        expense_service.get_latest_transactions = AsyncMock(return_value=[])

        update = _make_update()
        context = _make_context(["20"])

        with patch.object(queries, "_resolve_user", new=AsyncMock(return_value=user)), \
             patch.object(queries, "ExpenseService", return_value=expense_service), \
             patch.object(queries, "send_rich_message", new=AsyncMock()):
            await latest_handler(update, context)

        expense_service.get_latest_transactions.assert_awaited_once_with(
            7, 20, None
        )

    async def test_unknown_tag_is_rejected(self):
        user = MagicMock()
        user.id = 7
        expense_service = MagicMock()
        expense_service.get_latest_transactions = AsyncMock(return_value=[])

        update = _make_update()
        context = _make_context(["bogus"])

        with patch.object(queries, "_resolve_user", new=AsyncMock(return_value=user)), \
             patch.object(queries, "ExpenseService", return_value=expense_service), \
             patch.object(queries, "current_tags", return_value=("food", "other")):
            await latest_handler(update, context)

        expense_service.get_latest_transactions.assert_not_awaited()
        assert "Invalid tag" in update.message.reply_text.await_args[0][0]
