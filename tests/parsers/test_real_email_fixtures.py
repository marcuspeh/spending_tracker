"""End-to-end parser tests driven by real .txt email fixtures.

Each fixture in `tests/fixtures/email_samples/<parser>/` follows a simple format::

    Subject: <subject line>
    <blank line>
    From: <from address>
    <blank line>
    <body>

`load_email(path)` parses that into the dict shape parsers expect, and the
parametrised cases below assert the right parser picks each one up and
extracts the right amount/payment-method/date.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

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

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "email_samples"


def load_email(path: Path) -> dict:
    """Parse a `.txt` fixture into the {subject, body, from} dict shape.

    The fixture format mirrors what the IMAP poller delivers:

    - Direct bank email:
        Subject: <bank subject>
        <blank>
        From: <bank address>
        <blank>
        <bank body>
    - Forwarded bank email (Gmail "Forward" action):
        Subject: Fwd: <bank subject>
        <blank>
        From: <forwarder's Gmail address>
        <blank>
        ---------- Forwarded message ----------
        From: <bank address>
        Date: ...
        Subject: <bank subject>
        To: <forwarder>

        <bank body>
    """
    raw = path.read_text(encoding="utf-8")
    subject = ""
    from_ = ""
    body_lines: list[str] = []
    state = "preamble"
    for line in raw.splitlines():
        if state == "preamble":
            if line.startswith("Subject:"):
                subject = line[len("Subject:") :].strip()
            elif line.startswith("From:"):
                from_ = line[len("From:") :].strip()
            elif line.strip() == "" and subject:
                state = "body"
        elif state == "body":
            body_lines.append(line)
    return {
        "subject": subject,
        "body": "\n".join(body_lines).strip(),
        "from": from_,
    }


def _make_registry() -> ParserRegistry:
    """Registry with the same parser order as the running app."""
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


PARSE_CASES = [
    pytest.param(
        "dbs_cc/Card Transaction Alert.txt",
        Decimal("2.15"),
        "DBS_CC",
        datetime(2026, 7, 16, 12, 39, tzinfo=SGT),
        id="dbs_cc_direct",
    ),
    pytest.param(
        "dbs_bank/digibank Alerts - You've received a transfer.txt",
        Decimal("-10.35"),
        "DBS_BANK_TRANSFER_CREDIT",
        datetime(2026, 6, 3, 0, 13, tzinfo=SGT),
        id="dbs_bank_transfer_credit",
    ),
    pytest.param(
        "dbs_bank/iBanking Alerts.txt",
        Decimal("1.00"),
        "DBS_BANK_TRANSFER_DEBIT",
        datetime(2026, 7, 31, 0, 13, tzinfo=SGT),
        id="dbs_bank_transfer_debit",
    ),
    pytest.param(
        "dbs_paynow/iBanking Alerts.txt",
        Decimal("1.00"),
        "DBS_PAYNOW_DEBIT",
        datetime(2026, 7, 31, 0, 13, tzinfo=SGT),
        id="dbs_paynow_debit",
    ),
    pytest.param(
        "dbs_paynow/digibank Alerts - Youve received a transfer.txt",
        Decimal("-0.50"),
        "DBS_PAYNOW_CREDIT",
        datetime(2026, 7, 31, 0, 11, tzinfo=SGT),
        id="dbs_paynow_credit",
    ),
    pytest.param(
        "paylah/Transaction Alerts.txt",
        Decimal("2000.00"),
        "PAYLAH_DEBIT",
        datetime(2026, 7, 16, 10, 35, tzinfo=SGT),
        id="paylah_debit",
    ),
    pytest.param(
        "uob_cc/UOB - Transaction Alert.txt",
        Decimal("3.80"),
        "UOB_CC",
        datetime(2026, 7, 16, 0, 0, tzinfo=SGT),
        id="uob_cc_direct",
    ),
    pytest.param(
        "uob_bank/UOB Personal Internet Banking Notification Alerts.txt",
        Decimal("2500.00"),
        "UOB_BANK_TRANSFER_DEBIT",
        datetime(2026, 3, 14, 12, 35, tzinfo=SGT),
        id="uob_bank_transfer_debit",
    ),
    pytest.param(
        "uob_cc/Your transaction has been refunded.txt",
        Decimal("-23.98"),
        "UOB_CC_REFUND",
        datetime(2026, 7, 6, 0, 0, tzinfo=SGT),
        id="uob_cc_refund",
    ),
    pytest.param(
        "uob_cc/Your transaction has been reversed.txt",
        Decimal("-2.73"),
        "UOB_CC_REFUND",
        datetime(2026, 7, 29, 22, 55, tzinfo=SGT),
        id="uob_cc_reversed",
    ),
    pytest.param(
        "uob_paynow/UOB Personal Internet Banking Notification Alerts.txt",
        Decimal("420.00"),
        "UOB_PAYNOW_DEBIT",
        datetime(2026, 6, 12, 0, 0, tzinfo=SGT),
        id="uob_paynow_debit",
    ),
    pytest.param(
        "uob_paynow/UOB-PayNow transfer received.txt",
        Decimal("-2000.00"),
        "UOB_PAYNOW_CREDIT",
        datetime(2025, 9, 15, 23, 21, tzinfo=SGT),
        id="uob_paynow_credit",
    ),
]


@pytest.mark.parametrize(
    "filename,expected_amount,expected_method,expected_time",
    PARSE_CASES,
)
def test_real_email_parses_correctly(
    registry, filename, expected_amount, expected_method, expected_time
):
    fixture_path = FIXTURES_DIR / filename
    email = load_email(fixture_path)

    parser = registry.find_parser(email)
    assert parser is not None, f"No parser claimed fixture {filename}"
    result = parser.parse(email)

    assert result.amount == expected_amount, (
        f"{filename}: expected {expected_amount}, got {result.amount}"
    )
    assert result.payment_method == expected_method, (
        f"{filename}: expected {expected_method}, got {result.payment_method}"
    )
    assert result.transaction_time == expected_time, (
        f"{filename}: expected {expected_time}, got {result.transaction_time}"
    )


REJECT_CASES = sorted(
    str(p.relative_to(FIXTURES_DIR)) for p in FIXTURES_DIR.glob("parse_failure/*.txt")
)


@pytest.mark.parametrize("filename", REJECT_CASES)
def test_parse_failure_fixtures_are_rejected(registry, filename):
    fixture_path = FIXTURES_DIR / filename
    email = load_email(fixture_path)

    parser = registry.find_parser(email)
    assert parser is None, (
        f"{filename} should not be claimed by any parser, but {type(parser).__name__} claimed it"
    )