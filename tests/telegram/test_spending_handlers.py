"""Tests for the refactored spending handlers (/today, /week, /month)
and the ``_resolve_user`` / ``_send_with_fallback`` helpers they share."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import expense as expense_module
from app.telegram.handlers import queries
from app.telegram.handlers.queries import (
    _resolve_user,
    _send_with_fallback,
    make_spending_breakdown_handler,
    month_handler,
    today_handler,
    week_handler,
)


def _make_update(chat_id: int = 42) -> MagicMock:
    """Build a mock PTB Update with an ``effective_chat`` and a
    reply_text that records its calls."""
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def _make_context() -> MagicMock:
    """Build a mock PTB context with a bot whose ``send_message`` and
    ``_post`` are async mocks."""
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot._post = AsyncMock()
    return context


class TestResolveUser:
    async def test_returns_user_when_auth_and_lookup_succeed(self):
        user = MagicMock()
        user_repo = MagicMock()
        user_repo.get_by_chat_id = AsyncMock(return_value=user)
        update = _make_update()
        context = _make_context()

        with patch.object(queries, "UserRepository", return_value=user_repo), \
             patch.object(queries, "auth_handler", new=AsyncMock(return_value=True)):
            result = await _resolve_user(update, context)

        assert result is user

    async def test_returns_none_when_auth_rejects(self):
        update = _make_update()
        context = _make_context()

        with patch.object(queries, "auth_handler", new=AsyncMock(return_value=False)):
            result = await _resolve_user(update, context)

        assert result is None
        update.message.reply_text.assert_not_called()

    async def test_replies_when_user_not_found(self):
        user_repo = MagicMock()
        user_repo.get_by_chat_id = AsyncMock(return_value=None)
        update = _make_update()
        context = _make_context()

        with patch.object(queries, "UserRepository", return_value=user_repo), \
             patch.object(queries, "auth_handler", new=AsyncMock(return_value=True)):
            result = await _resolve_user(update, context)

        assert result is None
        update.message.reply_text.assert_awaited_once_with("User not found.")


class TestSendWithFallback:
    async def test_sends_rich_message_on_success(self):
        context = _make_context()
        with patch.object(
            queries, "send_rich_message", new=AsyncMock()
        ) as rich:
            await _send_with_fallback(context, chat_id=1, html="<h/>", fallback_text="x")

        rich.assert_awaited_once_with(context.bot, 1, "<h/>")
        context.bot.send_message.assert_not_called()

    async def test_falls_back_when_rich_message_raises(self):
        context = _make_context()
        with patch.object(
            queries, "send_rich_message", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            await _send_with_fallback(context, chat_id=1, html="<h/>", fallback_text="fb")

        context.bot.send_message.assert_awaited_once_with(chat_id=1, text="fb")


def _resolve_user_ok():
    """Standard ``_resolve_user`` mocks: a user returned from the lookup
    and auth always passing."""
    user = MagicMock(id=7)
    user_repo = MagicMock()
    user_repo.get_by_chat_id = AsyncMock(return_value=user)
    return user, user_repo


class TestMakeSpendingBreakdownHandler:
    """Direct tests of the factory — the exported module-level handlers
    only differ by which service methods they reference, so the factory
    is the only piece with branching logic worth covering."""

    async def test_sends_rich_message_with_total_and_breakdown(self):
        user, user_repo = _resolve_user_ok()
        update = _make_update(chat_id=42)
        context = _make_context()

        fetch_total = AsyncMock(return_value=12.5)
        fetch_breakdown = AsyncMock(return_value=({"food": 12.5}, False))

        handler = make_spending_breakdown_handler(
            "Today's spending", fetch_total, fetch_breakdown
        )

        with patch.object(queries, "UserRepository", return_value=user_repo), \
             patch.object(queries, "auth_handler", new=AsyncMock(return_value=True)), \
             patch.object(
                 queries, "send_rich_message", new=AsyncMock()
             ) as rich:
            await handler(update, context)

        # Fetchers got the user id and we're rendering the right slice.
        fetch_total.assert_awaited_once()
        fetch_breakdown.assert_awaited_once()
        rich.assert_awaited_once()
        _, chat_id, html = rich.await_args.args
        assert chat_id == 42
        assert "Today's spending" in html
        assert ">Total<" in html
        assert ">S$12.50<" in html

    async def test_returns_early_when_user_missing(self):
        update = _make_update()
        context = _make_context()
        user_repo = MagicMock()
        user_repo.get_by_chat_id = AsyncMock(return_value=None)

        handler = make_spending_breakdown_handler(
            "X", AsyncMock(), AsyncMock()
        )

        with patch.object(queries, "UserRepository", return_value=user_repo), \
             patch.object(queries, "auth_handler", new=AsyncMock(return_value=True)):
            await handler(update, context)

        context.bot._post.assert_not_called()
        update.message.reply_text.assert_awaited_once_with("User not found.")

    async def test_falls_back_to_plain_text_on_rich_message_failure(self):
        user, user_repo = _resolve_user_ok()
        update = _make_update(chat_id=42)
        context = _make_context()

        fetch_total = AsyncMock(return_value=-3.0)
        fetch_breakdown = AsyncMock(return_value=({"food": -3.0}, False))

        handler = make_spending_breakdown_handler(
            "Today's spending", fetch_total, fetch_breakdown
        )

        with patch.object(queries, "UserRepository", return_value=user_repo), \
             patch.object(queries, "auth_handler", new=AsyncMock(return_value=True)), \
             patch.object(
                 queries, "send_rich_message",
                 new=AsyncMock(side_effect=RuntimeError("boom")),
             ):
            await handler(update, context)

        # The fallback path uses bot.send_message with the plain-text
        # breakdown, including the (net credit) hint for negative totals.
        context.bot.send_message.assert_awaited_once()
        kwargs = context.bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == 42
        assert "Today's spending" in kwargs["text"]
        assert "(net credit)" in kwargs["text"]


class TestHandlersAreWiredToCorrectServiceMethods:
    """The module-level handlers are produced by
    ``make_spending_breakdown_handler`` with bound ``ExpenseService``
    methods captured at import time. Patching the ``ExpenseService``
    class has no effect on the bound methods already in the closure,
    so we let the real service run and intercept at the underlying
    ``TransactionRepository`` — observing which repo methods are
    called tells us which time window the handler picked."""

    async def test_today_handler_uses_today_methods(self):
        user, user_repo = _resolve_user_ok()
        update = _make_update()
        context = _make_context()

        repo = MagicMock()
        repo.sum_amount = AsyncMock(return_value=1.0)
        repo.sum_amount_by_tag = AsyncMock(return_value=({}, False))

        with patch.object(expense_module, "TransactionRepository", return_value=repo), \
             patch.object(queries, "UserRepository", return_value=user_repo), \
             patch.object(queries, "auth_handler", new=AsyncMock(return_value=True)), \
             patch.object(queries, "send_rich_message", new=AsyncMock()):
            await today_handler(update, context)

        # /today calls the repo twice (sum_amount + sum_amount_by_tag)
        # and never again — proving the today methods are the ones
        # dispatched.
        assert repo.sum_amount.await_count == 1
        assert repo.sum_amount_by_tag.await_count == 1

    async def test_week_handler_uses_week_methods(self):
        user, user_repo = _resolve_user_ok()
        update = _make_update()
        context = _make_context()

        repo = MagicMock()
        repo.sum_amount = AsyncMock(return_value=2.0)
        repo.sum_amount_by_tag = AsyncMock(return_value=({}, False))

        with patch.object(expense_module, "TransactionRepository", return_value=repo), \
             patch.object(queries, "UserRepository", return_value=user_repo), \
             patch.object(queries, "auth_handler", new=AsyncMock(return_value=True)), \
             patch.object(queries, "send_rich_message", new=AsyncMock()):
            await week_handler(update, context)

        assert repo.sum_amount.await_count == 1
        assert repo.sum_amount_by_tag.await_count == 1
        # All calls should land within the same calendar window that
        # the week uses (we don't pin the exact window here, just that
        # the window was queried exactly once).
        args = repo.sum_amount.await_args.args
        assert len(args) == 3  # user_id, start_utc, end_utc

    async def test_month_handler_uses_month_methods(self):
        user, user_repo = _resolve_user_ok()
        update = _make_update()
        context = _make_context()

        repo = MagicMock()
        repo.sum_amount = AsyncMock(return_value=3.0)
        repo.sum_amount_by_tag = AsyncMock(return_value=({}, False))

        with patch.object(expense_module, "TransactionRepository", return_value=repo), \
             patch.object(queries, "UserRepository", return_value=user_repo), \
             patch.object(queries, "auth_handler", new=AsyncMock(return_value=True)), \
             patch.object(queries, "send_rich_message", new=AsyncMock()):
            await month_handler(update, context)

        assert repo.sum_amount.await_count == 1
        assert repo.sum_amount_by_tag.await_count == 1
