"""Table-driven (Go-style) parser tests.

Walks every `.txt` fixture under ``tests/fixtures/email_samples/`` and
asserts that:

1. Every fixture in ``<parser>/`` folders is claimed by exactly the
   matching parser, returning the expected amount / payment-method /
   transaction_time.
2. Every fixture in ``parse_failure/`` is rejected by all parsers.

This complements the per-fixture parametrised cases in
``test_real_email_fixtures.py`` — those cover each parser in isolation;
this test ensures the registry as a whole agrees on routing.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable

import pytest

from app.services.parsers.dbs_bank import DBSBankParser
from app.services.parsers.dbs_cc import DBSCCParser
from app.services.parsers.dbs_paynow import DBSPayNowParser
from app.services.parsers.paylah import PayLahParser
from app.services.parsers.registry import ParserRegistry
from app.services.parsers.uob_bank import UOBBankParser
from app.services.parsers.uob_cc import UOBCCParser
from app.services.parsers.uob_paynow import UOBPayNowParser
from app.utils.timezone import SGT
from tests.parsers.test_real_email_fixtures import load_email

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "email_samples"


def _make_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(UOBCCParser())
    registry.register(UOBPayNowParser())
    registry.register(UOBBankParser())
    registry.register(DBSBankParser())
    registry.register(DBSCCParser())
    registry.register(DBSPayNowParser())
    registry.register(PayLahParser())
    return registry


@pytest.fixture
def registry() -> ParserRegistry:
    return _make_registry()


@dataclass(frozen=True)
class ParseCase:
    name: str
    filename: str
    expected_amount: Decimal | None
    expected_method: str | None
    expected_time: datetime | None
    expected_merchant: str | None = None


PARSE_CASES: list[ParseCase] = [
    ParseCase(
        name="dbs_cc_direct",
        filename="dbs_cc/Card Transaction Alert.txt",
        expected_amount=Decimal("2.15"),
        expected_method="DBS_CC",
        expected_time=datetime(2026, 7, 16, 12, 39, tzinfo=SGT),
        expected_merchant="Inception SG Pte Ltd",
    ),
    ParseCase(
        name="dbs_bank_credit",
        filename="dbs_bank/digibank Alerts - You've received a transfer.txt",
        expected_amount=Decimal("-10.35"),
        expected_method="DBS_BANK_TRANSFER_CREDIT",
        expected_time=datetime(2026, 6, 3, 0, 13, tzinfo=SGT),
        expected_merchant="JANE DOE",
    ),
    ParseCase(
        name="dbs_bank_debit",
        filename="dbs_bank/iBanking Alerts.txt",
        expected_amount=Decimal("1.00"),
        expected_method="DBS_BANK_TRANSFER_DEBIT",
        expected_time=datetime(2026, 7, 31, 0, 13, tzinfo=SGT),
        expected_merchant="IBKR (A/C ending 0775)",
    ),
    ParseCase(
        name="dbs_paynow_debit",
        filename="dbs_paynow/iBanking Alerts.txt",
        expected_amount=Decimal("1.00"),
        expected_method="DBS_PAYNOW_DEBIT",
        expected_time=datetime(2026, 7, 31, 0, 13, tzinfo=SGT),
        expected_merchant="CHUA CHEW",
    ),
    ParseCase(
        name="dbs_paynow_credit",
        filename="dbs_paynow/digibank Alerts - Youve received a transfer.txt",
        expected_amount=Decimal("-0.50"),
        expected_method="DBS_PAYNOW_CREDIT",
        expected_time=datetime(2026, 7, 31, 0, 11, tzinfo=SGT),
        expected_merchant="TOM TAN",
    ),
    ParseCase(
        name="paylah_debit",
        filename="paylah/Transaction Alerts.txt",
        expected_amount=Decimal("2000.00"),
        expected_method="PAYLAH_DEBIT",
        expected_time=datetime(2026, 7, 16, 10, 35, tzinfo=SGT),
        expected_merchant="CHOCFIN PTE. LTD. - CHOCOLATE CLIENTS AC",
    ),
    ParseCase(
        name="uob_cc_direct",
        filename="uob_cc/UOB - Transaction Alert.txt",
        expected_amount=Decimal("3.80"),
        expected_method="UOB_CC",
        expected_time=datetime(2026, 7, 16, 0, 0, tzinfo=SGT),
        expected_merchant="BUS/MRT",
    ),
    ParseCase(
        name="uob_cc_refund",
        filename="uob_cc/Your transaction has been refunded.txt",
        expected_amount=Decimal("-23.98"),
        expected_method="UOB_CC_REFUND",
        expected_time=datetime(2026, 7, 6, 0, 0, tzinfo=SGT),
        expected_merchant="SHOPEE APPLEPAY",
    ),
    ParseCase(
        name="uob_cc_reversed",
        filename="uob_cc/Your transaction has been reversed.txt",
        expected_amount=Decimal("-2.73"),
        expected_method="UOB_CC_REFUND",
        expected_time=datetime(2026, 7, 29, 22, 55, tzinfo=SGT),
        expected_merchant="SHOPEE SG MP",
    ),
    ParseCase(
        name="uob_bank_debit",
        filename="uob_bank/UOB Personal Internet Banking Notification Alerts.txt",
        expected_amount=Decimal("2500.00"),
        expected_method="UOB_BANK_TRANSFER_DEBIT",
        expected_time=datetime(2026, 3, 14, 12, 35, tzinfo=SGT),
        expected_merchant="DBS BANK LTD a/c ending 5660",
    ),
    ParseCase(
        name="uob_paynow_debit",
        filename="uob_paynow/UOB Personal Internet Banking Notification Alerts.txt",
        expected_amount=Decimal("420.00"),
        expected_method="UOB_PAYNOW_DEBIT",
        expected_time=datetime(2026, 6, 12, 0, 0, tzinfo=SGT),
        expected_merchant="JOXX DOX",
    ),
    ParseCase(
        name="uob_paynow_credit",
        filename="uob_paynow/UOB-PayNow transfer received.txt",
        expected_amount=Decimal("-2000.00"),
        expected_method="UOB_PAYNOW_CREDIT",
        expected_time=datetime(2025, 9, 15, 23, 21, tzinfo=SGT),
        expected_merchant="UOB_PAYNOW",
    ),
]


def _make_parse_id(case: ParseCase) -> str:
    return case.name


@pytest.mark.parametrize(
    "case",
    PARSE_CASES,
    ids=_make_parse_id,
)
def test_parse_table_driven(registry, case: ParseCase):
    fixture_path = FIXTURES_DIR / case.filename
    assert fixture_path.exists(), f"Missing fixture: {fixture_path}"

    email = load_email(fixture_path)
    parser = registry.find_parser(email)
    assert parser is not None, f"[{case.name}] {case.filename}: no parser claimed the email"
    result = parser.parse(email)

    if case.expected_amount is not None:
        assert result.amount == case.expected_amount, (
            f"[{case.name}] amount: expected {case.expected_amount}, got {result.amount}"
        )
    if case.expected_method is not None:
        assert result.payment_method == case.expected_method, (
            f"[{case.name}] method: expected {case.expected_method}, got {result.payment_method}"
        )
    if case.expected_time is not None:
        assert result.transaction_time == case.expected_time, (
            f"[{case.name}] time: expected {case.expected_time}, got {result.transaction_time}"
        )
    if case.expected_merchant is not None:
        assert result.merchant == case.expected_merchant, (
            f"[{case.name}] merchant: expected {case.expected_merchant!r}, got {result.merchant!r}"
        )


@dataclass(frozen=True)
class RejectCase:
    name: str
    filename: str


REJECT_CASES: list[RejectCase] = [
    RejectCase(name="lock", filename="parse_failure/Your card is locked.txt"),
    RejectCase(name="still_lock", filename="parse_failure/Your card is still locked.txt"),
    RejectCase(name="still_lock_1", filename="parse_failure/Your card is still locked_1.txt"),
    RejectCase(name="unlock", filename="parse_failure/Your card is unlocked.txt"),
    RejectCase(name="edocs", filename="parse_failure/Your eDocuments are ready for viewing.txt"),
    RejectCase(name="ibanking_own", filename="parse_failure/iBanking Alerts.txt"),
]


@pytest.mark.parametrize("case", REJECT_CASES, ids=lambda c: c.name)
def test_reject_table_driven(registry, case: RejectCase):
    fixture_path = FIXTURES_DIR / case.filename
    assert fixture_path.exists(), f"Missing fixture: {fixture_path}"

    email = load_email(fixture_path)
    parser = registry.find_parser(email)
    assert parser is None, (
        f"[{case.name}] {case.filename}: should not be claimed, "
        f"but {type(parser).__name__} claimed it"
    )


def _make_should_parse_lookup() -> Callable[[Path], ParseCase | None]:
    by_filename = {c.filename: c for c in PARSE_CASES}

    def lookup(path: Path) -> ParseCase | None:
        rel = path.relative_to(FIXTURES_DIR).as_posix()
        return by_filename.get(rel)

    return lookup


def test_every_positive_fixture_is_in_the_table():
    parse_failures = FIXTURES_DIR / "parse_failure"
    discovered = sorted(
        str(p.relative_to(FIXTURES_DIR).as_posix())
        for p in FIXTURES_DIR.rglob("*.txt")
        if parse_failures not in p.parents
    )
    listed = sorted(c.filename for c in PARSE_CASES)
    assert discovered == listed, (
        "Fixtures added to email_samples/ but missing from PARSE_CASES:\n"
        f"  on disk only: {set(discovered) - set(listed)}\n"
        f"  in table only: {set(listed) - set(discovered)}"
    )


def test_every_negative_fixture_is_in_the_table():
    parse_failures = FIXTURES_DIR / "parse_failure"
    discovered = sorted(
        str(p.relative_to(FIXTURES_DIR).as_posix()) for p in parse_failures.glob("*.txt")
    )
    listed = sorted(c.filename for c in REJECT_CASES)
    assert discovered == listed, (
        "parse_failure/ fixtures missing from REJECT_CASES:\n"
        f"  on disk only: {set(discovered) - set(listed)}\n"
        f"  in table only: {set(listed) - set(discovered)}"
    )