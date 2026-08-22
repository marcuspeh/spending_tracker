"""Unit tests for EmailIngestionService.process_email.

These mock the three repositories so we can exercise the dedup / parser /
ownership / insert paths without a real database.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.database.enums import ImportStatus
from app.services.email_ingestion import EmailIngestionService
from app.services.parsers.base import ParsedTransaction, ParserError
from app.services.parsers.registry import ParserRegistry


@pytest.fixture(autouse=True)
def _mock_tag(monkeypatch):
    """Stub the tagger so unit tests don't hit the network or DB."""
    import app.services.email_ingestion as ei

    monkeypatch.setattr(ei, "tag_for_or_default", AsyncMock(return_value=None))


@dataclass
class FakeUserEmail:
    user_id: int = 42


def _make_service(
    *,
    existing_import=None,
    user_email=None,
    parsed=None,
    parser_error: bool = False,
    notification_service=None,
) -> tuple[EmailIngestionService, dict[str, AsyncMock]]:
    """Build an EmailIngestionService whose repositories are AsyncMocks.

    Returns the service and a dict of the mocks so callers can assert calls.
    """
    registry = ParserRegistry()
    parser = MagicMock()
    parser.parse = MagicMock(side_effect=ParserError("bad") if parser_error else None)
    if parsed is not None:
        parser.parse = MagicMock(return_value=parsed)
    registry.register(parser)
    registry.find_parser = MagicMock(return_value=parser)

    imported_mock = MagicMock()
    imported_mock.exists_by_message_id = AsyncMock(return_value=existing_import is not None)
    imported_mock.get_by_message_id = AsyncMock(return_value=existing_import)
    imported_mock.insert = AsyncMock(return_value=MagicMock())

    user_email_mock = MagicMock()
    user_email_mock.find_by_email = AsyncMock(return_value=user_email)

    fake_txn = MagicMock()
    fake_txn.id = 1
    transaction_mock = MagicMock()
    transaction_mock.insert = AsyncMock(return_value=fake_txn)

    service = EmailIngestionService.__new__(EmailIngestionService)
    service.parser_registry = registry
    service.imported_email_repo = imported_mock
    service.user_email_repo = user_email_mock
    service.transaction_repo = transaction_mock
    service.notification_service = notification_service
    return service, {
        "imported": imported_mock,
        "user_email": user_email_mock,
        "transaction": transaction_mock,
        "parser": parser,
    }


def _parsed(payment_method: str = "DBS_CC", amount: str = "3.98") -> ParsedTransaction:
    return ParsedTransaction(
        amount=Decimal(amount),
        merchant="APPLE.COM/BILL",
        payment_method=payment_method,
        transaction_time=datetime(2026, 7, 16, 12, 39),
        description=None,
    )


def _email(**overrides: Any) -> dict:
    base = {
        "message_id": "<abc@example.com>",
        "subject": "Card Transaction Alert",
        "body": "Amount: SGD3.98",
        "from": "ibanking.alert@dbs.com",
        "to": ["user@example.com"],
        "cc": [],
    }
    if "from_" in overrides:
        overrides["from"] = overrides.pop("from_")
    base.update(overrides)
    return base


class TestProcessEmailSuccess:
    @pytest.mark.asyncio
    async def test_inserts_transaction_when_user_and_parser_match(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(user_id=42),
            parsed=_parsed(),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS
        mocks["transaction"].insert.assert_awaited_once()
        mocks["imported"].insert.assert_awaited_with("<abc@example.com>", ImportStatus.SUCCESS)

    @pytest.mark.asyncio
    async def test_user_email_string_form(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(),
        )
        status = await service.process_email(_email(to="user@example.com"))
        assert status == ImportStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_user_email_list_form(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(),
        )
        status = await service.process_email(_email(to=["a@example.com", "user@example.com"]))
        assert status == ImportStatus.SUCCESS


class TestProcessEmailFailure:
    @pytest.mark.asyncio
    async def test_parser_error_marks_failed(self):
        service, mocks = _make_service(parser_error=True)
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        mocks["imported"].insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.FAILED, "PARSE_ERROR"
        )
        mocks["transaction"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_user_email_marks_failed_with_unknown_forwarder(self):
        service, mocks = _make_service(
            user_email=None,
            parsed=_parsed(),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        mocks["imported"].insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.FAILED, "UNKNOWN_FORWARDER"
        )
        mocks["transaction"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_payment_method_marks_failed(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(payment_method="NOT_A_METHOD"),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        mocks["imported"].insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.FAILED, "UNKNOWN_PAYMENT_METHOD"
        )
        mocks["transaction"].insert.assert_not_awaited()


class TestProcessEmailDedup:
    @pytest.mark.asyncio
    async def test_returns_existing_status_when_already_imported(self):
        existing = MagicMock()
        existing.status = ImportStatus.SUCCESS
        existing.reason = None
        service, mocks = _make_service(existing_import=existing)
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS
        mocks["transaction"].insert.assert_not_awaited()
        mocks["imported"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_forwarder_on_repeat_returns_failed(self):
        existing = MagicMock()
        existing.status = ImportStatus.FAILED
        existing.reason = "UNKNOWN_FORWARDER"
        service, mocks = _make_service(existing_import=existing)
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        mocks["transaction"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_integrity_error_on_insert_treated_as_already_seen(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(),
        )
        mocks["imported"].insert = AsyncMock(return_value=None)
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS


class TestProcessEmailNoParser:
    @pytest.mark.asyncio
    async def test_no_parser_marks_skipped(self):
        registry = ParserRegistry()
        registry.find_parser = MagicMock(return_value=None)
        service = EmailIngestionService.__new__(EmailIngestionService)
        service.parser_registry = registry
        service.imported_email_repo = MagicMock()
        service.imported_email_repo.exists_by_message_id = AsyncMock(return_value=False)
        service.imported_email_repo.insert = AsyncMock(return_value=MagicMock())
        service.user_email_repo = MagicMock()
        service.transaction_repo = MagicMock()

        status = await service.process_email(_email())
        assert status == ImportStatus.SKIPPED
        service.imported_email_repo.insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.SKIPPED
        )


class TestProcessEmailBlacklist:
    """Merchants in the hardcoded blacklist are skipped after parsing —
    no transaction is inserted and no notification is sent."""

    # The merchant string the PayLah parser extracts from the
    # ChocFin → Chocolate Clients transfer email. Blacklisted because
    # those are internal savings transfers, not real spending.
    _BLACKLISTED_MERCHANT = "CHOCFIN PTE. LTD. - CHOCOLATE CLIENTS AC"

    @pytest.mark.asyncio
    async def test_blacklisted_merchant_marks_blacklisted(self):
        # Parser succeeds and returns a merchant in the blacklist. The
        # service should record BLACKLISTED and never touch the
        # transaction repo.
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=ParsedTransaction(
                amount=Decimal("3.98"),
                merchant=self._BLACKLISTED_MERCHANT,
                payment_method="DBS_CC",
                transaction_time=datetime(2026, 7, 16, 12, 39),
                description=None,
            ),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.BLACKLISTED
        mocks["imported"].insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.BLACKLISTED, "BLACKLISTED"
        )
        mocks["transaction"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blacklist_match_is_case_insensitive_and_trims_whitespace(self):
        # Real parsers can vary in casing/formatting; the blacklist
        # must still hit when the merchant is uppercase or padded.
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=ParsedTransaction(
                amount=Decimal("3.98"),
                merchant="  CHOCFIN   PTE.   LTD.   -   CHOCOLATE   CLIENTS   AC  ",
                payment_method="DBS_CC",
                transaction_time=datetime(2026, 7, 16, 12, 39),
                description=None,
            ),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.BLACKLISTED
        mocks["transaction"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_blacklisted_merchant_proceeds_normally(self):
        # Regression guard: the blacklist check must not interfere
        # with non-blacklisted merchants. APPLE.COM/BILL is not in the
        # blacklist.
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=ParsedTransaction(
                amount=Decimal("3.98"),
                merchant="APPLE.COM/BILL",
                payment_method="DBS_CC",
                transaction_time=datetime(2026, 7, 16, 12, 39),
                description=None,
            ),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS
        mocks["transaction"].insert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_blacklist_check_runs_before_payment_method_check(self):
        # A merchant in the blacklist should be BLACKLISTED rather than
        # failing with UNKNOWN_PAYMENT_METHOD when both apply.
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=ParsedTransaction(
                amount=Decimal("3.98"),
                merchant=self._BLACKLISTED_MERCHANT,
                payment_method="NOT_A_METHOD",
                transaction_time=datetime(2026, 7, 16, 12, 39),
                description=None,
            ),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.BLACKLISTED
        mocks["imported"].insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.BLACKLISTED, "BLACKLISTED"
        )

    @pytest.mark.asyncio
    async def test_blacklist_check_runs_before_user_email_check(self):
        # Even when no user email is registered for the forwarder, a
        # blacklisted merchant should record BLACKLISTED (the user
        # would never have owned the transaction anyway).
        service, mocks = _make_service(
            user_email=None,
            parsed=ParsedTransaction(
                amount=Decimal("3.98"),
                merchant=self._BLACKLISTED_MERCHANT,
                payment_method="DBS_CC",
                transaction_time=datetime(2026, 7, 16, 12, 39),
                description=None,
            ),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.BLACKLISTED
        mocks["imported"].insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.BLACKLISTED, "BLACKLISTED"
        )


class TestProcessEmailBlacklistDedup:
    @pytest.mark.asyncio
    async def test_returns_blacklisted_when_existing_record_was_blacklist(self):
        existing = MagicMock()
        existing.status = ImportStatus.BLACKLISTED
        existing.reason = "BLACKLISTED"
        service, mocks = _make_service(existing_import=existing)
        status = await service.process_email(_email())
        assert status == ImportStatus.BLACKLISTED
        mocks["transaction"].insert.assert_not_awaited()
        mocks["imported"].insert.assert_not_awaited()


class TestNotificationOnSuccess:
    @pytest.mark.asyncio
    async def test_notification_called_on_success(self):
        notification_mock = MagicMock()
        notification_mock.notify_transaction = AsyncMock()
        service, _ = _make_service(
            user_email=FakeUserEmail(user_id=42),
            parsed=_parsed(),
            notification_service=notification_mock,
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS
        notification_mock.notify_transaction.assert_awaited_once()
        args = notification_mock.notify_transaction.await_args.args
        assert args[0] == 42
        assert args[1].id == 1

    @pytest.mark.asyncio
    async def test_notification_not_called_on_failure(self):
        notification_mock = MagicMock()
        notification_mock.notify_transaction = AsyncMock()
        service, _ = _make_service(
            user_email=None,
            parsed=_parsed(),
            notification_service=notification_mock,
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        notification_mock.notify_transaction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_works_without_notification_service(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(),
            notification_service=None,
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS
        mocks["transaction"].insert.assert_awaited_once()


class TestUserAttributionTrust:
    @pytest.mark.asyncio
    async def test_does_not_match_from_field(self):
        service, mocks = _make_service(
            user_email=None,
            parsed=_parsed(),
        )
        mocks["user_email"].find_by_email = AsyncMock(return_value=None)
        status = await service.process_email(
            _email(from_="attacker-controlled-but-bank-domain@example.com")
        )
        assert status == ImportStatus.FAILED
        called_with = mocks["user_email"].find_by_email.await_args.args[0]
        assert called_with != "attacker-controlled-but-bank-domain@example.com"