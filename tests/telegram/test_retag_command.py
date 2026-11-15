"""Tests for the /retag command (re-run the LLM tagger on a transaction)."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.telegram.handlers import edit_commands
from app.telegram.handlers.edit_commands import retag_handler


def _make_update(chat_id: int = 42) -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args: list[str] | None = None) -> MagicMock:
    context = MagicMock()
    context.args = args
    return context


def _patch_deps(update, user_repo, txn_repo, expense_service, tag):
    """Patch every collaborator /retag touches."""
    return (
        patch.object(edit_commands, "auth_handler", new=AsyncMock(return_value=True)),
        patch.object(edit_commands, "UserRepository", return_value=user_repo),
        patch.object(edit_commands, "TransactionRepository", return_value=txn_repo),
        patch.object(edit_commands, "ExpenseService", return_value=expense_service),
        patch.object(edit_commands, "tag_for", new=AsyncMock(return_value=tag)),
    )


class TestRetag:
    async def test_requeries_llm_and_writes_tag(self):
        user = MagicMock()
        user.id = 7
        user_repo = MagicMock()
        user_repo.get_by_chat_id = AsyncMock(return_value=user)

        txn = MagicMock()
        txn.id = 101
        txn.merchant = "STARBUCKS"
        txn_repo = MagicMock()
        txn_repo.get_by_id_for_user = AsyncMock(return_value=txn)

        expense_service = MagicMock()
        expense_service.edit_transaction = AsyncMock(return_value=txn)

        update = _make_update()
        context = _make_context(["1"])

        p_auth, p_user, p_txn, p_exp, p_tag = _patch_deps(
            update, user_repo, txn_repo, expense_service, "food"
        )
        with p_auth, p_user, p_txn, p_exp, p_tag as tag_mock, \
             patch.object(edit_commands, "resolve_recent", return_value=101):
            await retag_handler(update, context)

        # The LLM must be re-run, not served from the cache.
        tag_mock.assert_awaited_once_with("STARBUCKS", force=True)
        expense_service.edit_transaction.assert_awaited_once_with(
            101, 7, "tag", "food"
        )
        assert "food" in update.message.reply_text.await_args[0][0]

    async def test_replies_with_usage_when_index_missing(self):
        update = _make_update()
        context = _make_context([])

        with patch.object(edit_commands, "auth_handler", new=AsyncMock(return_value=True)):
            await retag_handler(update, context)

        assert "Usage: /retag" in update.message.reply_text.await_args[0][0]

    async def test_replies_when_index_unresolvable(self):
        update = _make_update()
        context = _make_context(["9"])

        with patch.object(edit_commands, "auth_handler", new=AsyncMock(return_value=True)), \
             patch.object(edit_commands, "resolve_recent", return_value=None):
            await retag_handler(update, context)

        assert "Invalid index" in update.message.reply_text.await_args[0][0]

    async def test_replies_when_llm_fails(self):
        user = MagicMock()
        user.id = 7
        user_repo = MagicMock()
        user_repo.get_by_chat_id = AsyncMock(return_value=user)

        txn = MagicMock()
        txn.id = 101
        txn.merchant = "STARBUCKS"
        txn_repo = MagicMock()
        txn_repo.get_by_id_for_user = AsyncMock(return_value=txn)

        expense_service = MagicMock()
        expense_service.edit_transaction = AsyncMock(return_value=txn)

        update = _make_update()
        context = _make_context(["1"])

        p_auth, p_user, p_txn, p_exp, p_tag = _patch_deps(
            update, user_repo, txn_repo, expense_service, None
        )
        with p_auth, p_user, p_txn, p_exp, p_tag, \
             patch.object(edit_commands, "resolve_recent", return_value=101):
            await retag_handler(update, context)

        expense_service.edit_transaction.assert_not_awaited()
        assert "Couldn't get a tag" in update.message.reply_text.await_args[0][0]
