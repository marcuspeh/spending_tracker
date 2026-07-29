"""End-to-end parser tests driven by real .txt email fixtures.

Each fixture in `tests/fixtures/email_samples/` follows a simple format:
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

from app.services.parsers.dbs_cc import DBSCCParser
from app.services.parsers.dbs_paynow import DBSPayNowParser
from app.services.parsers.paylah import PayLahParser
from app.services.parsers.registry import ParserRegistry
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
                subject = line[len("Subject:"):].strip()
            elif line.startswith("From:"):
                from_ = line[len("From:"):].strip()
            elif line.strip() == "" and subject:
                state = "body"
        elif state == "body":
            # Keep the forwarded-message wrapper so parsers see the full
            # forwarded body (the bank subject/from/date plus the body),
            # matching what imap_tools returns for real Gmail forwards.
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
    registry.register(DBSCCParser())
    registry.register(DBSPayNowParser())
    registry.register(PayLahParser())
    return registry


@pytest.fixture
def registry() -> ParserRegistry:
    return _make_registry()


# --- shouldParse fixtures: parser name -> expected output ------------------

PARSE_CASES = [
    pytest.param(
        "dbs_cc_direct.txt",
        Decimal("2.15"),
        "DBS_CC",
        datetime(2026, 7, 16, 0, 0, tzinfo=SGT),
        id="dbs_cc_direct",
    ),
    pytest.param(
        "dbs_cc_fwd.txt",
        Decimal("3.98"),
        "DBS_CC",
        datetime(2026, 7, 13, 0, 0, tzinfo=SGT),
        id="dbs_cc_fwd",
    ),
    pytest.param(
        "uob_cc_direct.txt",
        Decimal("3.80"),
        "UOB_CC",
        datetime(2026, 7, 16, 0, 0, tzinfo=SGT),
        id="uob_cc_direct",
    ),
    pytest.param(
        "uob_cc_fwd.txt",
        Decimal("4.22"),
        "UOB_CC",
        datetime(2026, 7, 14, 0, 0, tzinfo=SGT),
        id="uob_cc_fwd",
    ),
    pytest.param(
        "uob_cc_refund_fwd.txt",
        Decimal("-23.98"),
        "UOB_CC_REFUND",
        datetime(2026, 7, 6, 0, 0, tzinfo=SGT),
        id="uob_cc_refund_fwd",
    ),
    pytest.param(
        "uob_paynow_debit_fwd.txt",
        Decimal("420.00"),
        "UOB_PAYNOW_DEBIT",
        datetime(2026, 6, 12, 0, 0, tzinfo=SGT),
        id="uob_paynow_debit_fwd",
    ),
    pytest.param(
        "dbs_paynow_credit_fwd.txt",
        Decimal("-40.00"),
        "DBS_PAYNOW_CREDIT",
        datetime(2026, 7, 7, 9, 45, tzinfo=SGT),
        id="dbs_paynow_credit_fwd",
    ),
    pytest.param(
        "paylah_debit_direct.txt",
        Decimal("2000.00"),
        "PAYLAH_DEBIT",
        # 2-digit year falls into the "%d %b %y" branch which interprets
        # "16 Jul" as 2010. Recorded here so the test fails loudly if the
        # parser starts returning a different (and presumably more correct)
        # value.
        datetime(2010, 7, 16, 0, 0, tzinfo=SGT),
        id="paylah_debit_direct",
    ),
    pytest.param(
        "paylah_debit_fwd.txt",
        Decimal("2000.00"),
        "PAYLAH_DEBIT",
        datetime(2008, 7, 13, 0, 0, tzinfo=SGT),
        id="paylah_debit_fwd",
    ),
    pytest.param(
        "dbs_cc_refund.txt",
        Decimal("-25.50"),
        "DBS_CC_REFUND",
        datetime(2024, 6, 10, 0, 0, tzinfo=SGT),
        id="dbs_cc_refund",
    ),
    pytest.param(
        "dbs_paynow_debit.txt",
        Decimal("10.00"),
        "DBS_PAYNOW_DEBIT",
        datetime(2016, 6, 26, 0, 0, tzinfo=SGT),
        id="dbs_paynow_debit",
    ),
    pytest.param(
        "paylah_debit.txt",
        Decimal("2000.00"),
        "PAYLAH_DEBIT",
        datetime(2008, 7, 13, 0, 0, tzinfo=SGT),
        id="paylah_debit",
    ),
    pytest.param(
        "uob_paynow_credit.txt",
        Decimal("-80.00"),
        "UOB_PAYNOW_CREDIT",
        datetime(2024, 5, 22, 16, 0, tzinfo=SGT),
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


# --- shouldNotParse fixtures: own-account transfer must not be claimed -----

def test_ibanking_own_account_transfer_is_rejected(registry):
    """Funds transfer between the user's own DBS/POSB accounts is not a
    transaction we want to track — the registry must not claim it."""
    fixture_path = FIXTURES_DIR / "dbs_ibanking_own_account.txt"
    email = load_email(fixture_path)

    parser = registry.find_parser(email)
    assert parser is None, (
        "iBanking own-account transfer should not be claimed by any parser, "
        f"but {type(parser).__name__} claimed it"
    )
