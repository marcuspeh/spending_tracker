"""Tests for ExpenseService.edit_transaction input coercion.

The /edit command is conversational — users can pass arbitrary strings.
We need to surface bad input as a friendly error rather than letting
``Decimal.InvalidOperation`` crash the handler.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.database.enums import PaymentMethod
from app.database.models.transaction import Transaction
from app.services.expense import ExpenseService, InvalidEditValue


def _make_service() -> tuple[ExpenseService, MagicMock]:
    txn_repo = MagicMock()
    txn = MagicMock(spec=Transaction)
    txn.id = 99
    txn_repo.get_by_id_for_user = AsyncMock(return_value=txn)
    txn_repo.update_field = AsyncMock(return_value=None)
    svc = ExpenseService.__new__(ExpenseService)
    svc.transaction_repo = txn_repo
    return svc, txn_repo


class TestEditAmountCoercion:
    @pytest.mark.asyncio
    async def test_valid_amount(self):
        svc, repo = _make_service()
        result = await svc.edit_transaction(99, 1, "amount", "12.50")
        assert result is not None
        repo.update_field.assert_awaited_once()
        args = repo.update_field.await_args.args
        assert args[1] == "amount"
        assert args[2] == pytest.approx(12.50)

    @pytest.mark.asyncio
    async def test_negative_amount_allowed(self):
        svc, repo = _make_service()
        await svc.edit_transaction(99, 1, "amount", "-5.00")
        args = repo.update_field.await_args.args
        assert args[2] == pytest.approx(-5.00)

    @pytest.mark.asyncio
    async def test_non_numeric_amount_raises_invalid_edit_value(self):
        svc, _ = _make_service()
        with pytest.raises(InvalidEditValue) as excinfo:
            await svc.edit_transaction(99, 1, "amount", "hello")
        assert "hello" in str(excinfo.value)
        assert "amount" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_garbage_amount_with_special_chars_raises(self):
        svc, _ = _make_service()
        with pytest.raises(InvalidEditValue):
            await svc.edit_transaction(99, 1, "amount", "$%@!")


class TestEditMerchant:
    @pytest.mark.asyncio
    async def test_string_passes_through(self):
        svc, repo = _make_service()
        await svc.edit_transaction(99, 1, "merchant", "Bus/MRT")
        args = repo.update_field.await_args.args
        assert args[2] == "Bus/MRT"


class TestEditTransactionTime:
    @pytest.mark.asyncio
    async def test_invalid_date_raises_invalid_edit_value(self):
        svc, _ = _make_service()
        with pytest.raises(InvalidEditValue) as excinfo:
            await svc.edit_transaction(99, 1, "transaction_time", "yesterday")
        assert "yesterday" in str(excinfo.value)


class TestEditFieldValidation:
    @pytest.mark.asyncio
    async def test_unknown_field_raises_value_error(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError) as excinfo:
            await svc.edit_transaction(99, 1, "rating", "5")
        assert "Field must be one of" in str(excinfo.value)


class TestEditNotFound:
    @pytest.mark.asyncio
    async def test_returns_none_when_transaction_missing(self):
        svc, repo = _make_service()
        repo.get_by_id_for_user = AsyncMock(return_value=None)
        result = await svc.edit_transaction(99, 1, "merchant", "X")
        assert result is None
        repo.update_field.assert_not_awaited()