"""Tests for the catch-all handler that answers unregistered commands."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.telegram.handlers import general
from app.telegram.handlers.general import unknown_command_handler


def _make_update(text: str = "/nope", chat_id: int = 42) -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context() -> MagicMock:
    context = MagicMock()
    context.args = []
    return context


class TestUnknownCommand:
    async def test_replies_with_command_not_found(self):
        update = _make_update("/nope")
        context = _make_context()

        with patch.object(general, "auth_handler", new=AsyncMock(return_value=True)):
            await unknown_command_handler(update, context)

        text = update.message.reply_text.await_args[0][0]
        assert "Command not found: /nope" in text
        assert "/help" in text

    async def test_keeps_arguments_out_of_the_command_name(self):
        update = _make_update("/nope some args")
        context = _make_context()

        with patch.object(general, "auth_handler", new=AsyncMock(return_value=True)):
            await unknown_command_handler(update, context)

        text = update.message.reply_text.await_args[0][0]
        assert "Command not found: /nope\n" in text

    async def test_unauthorized_user_gets_no_reply(self):
        update = _make_update("/nope")
        context = _make_context()

        with patch.object(general, "auth_handler", new=AsyncMock(return_value=False)):
            await unknown_command_handler(update, context)

        update.message.reply_text.assert_not_awaited()
