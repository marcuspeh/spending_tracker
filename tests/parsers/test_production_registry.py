"""Pin the live GmailPoller's parser registry.

The unit tests build their own registry (see `_make_registry` in
``test_real_email_fixtures.py``), but the running app uses the one wired
up in ``app/poller/gmail.py``. If those drift, transactions get
silently mis-routed or dropped.

This file asserts the production registry claims every fixture with the
right parser and rejects the parse_failure fixtures.
"""
from pathlib import Path

import pytest

from app.services.parsers.registry import ParserRegistry
from tests.parsers.test_real_email_fixtures import load_email

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "email_samples"


def _build_production_registry() -> ParserRegistry:
    """Mirror the registry setup in ``app.poller.gmail.GmailPoller.__init__``.

    We construct it directly (rather than instantiating ``GmailPoller``,
    which would pull in the whole Gmail/IMAP stack) so the test stays a
    pure routing test.
    """
    from app.services.parsers import (
        DBSCCParser,
        DBSPayNowParser,
        PayLahParser,
        UOBCCParser,
        UOBPayNowParser,
    )

    registry = ParserRegistry()
    registry.register(UOBCCParser())
    registry.register(UOBPayNowParser())
    registry.register(DBSCCParser())
    registry.register(DBSPayNowParser())
    registry.register(PayLahParser())
    return registry


@pytest.fixture
def production_registry() -> ParserRegistry:
    return _build_production_registry()


@pytest.mark.parametrize(
    "filename,expected_parser_name",
    [
        ("dbs_cc/Card Transaction Alert.txt", "DBS_CC"),
        ("dbs_paynow/iBanking Alerts.txt", "DBS_PAYNOW"),
        ("dbs_paynow/digibank Alerts - Youve received a transfer.txt", "DBS_PAYNOW"),
        ("paylah/Transaction Alerts.txt", "PAYLAH"),
        ("uob_cc/UOB - Transaction Alert.txt", "UOB_CC"),
        ("uob_cc/Your transaction has been refunded.txt", "UOB_CC"),
        ("uob_cc/Your transaction has been reversed.txt", "UOB_CC"),
        ("uob_paynow/UOB Personal Internet Banking Notification Alerts.txt", "UOB_PAYNOW"),
        ("uob_paynow/UOB-PayNow transfer received.txt", "UOB_PAYNOW"),
    ],
)
def test_production_registry_routes_to_correct_parser(
    production_registry, filename, expected_parser_name
):
    email = load_email(FIXTURES_DIR / filename)
    parser = production_registry.find_parser(email)
    assert parser is not None, f"{filename}: no parser claimed it"
    assert parser.name == expected_parser_name, (
        f"{filename}: expected {expected_parser_name}, got {parser.name}"
    )


@pytest.mark.parametrize(
    "filename",
    [
        "parse_failure/Your card is locked.txt",
        "parse_failure/Your card is still locked.txt",
        "parse_failure/Your card is still locked_1.txt",
        "parse_failure/Your card is unlocked.txt",
        "parse_failure/Your eDocuments are ready for viewing.txt",
        "parse_failure/iBanking Alerts.txt",  # Funds Transfer to own account
    ],
)
def test_production_registry_rejects_parse_failures(production_registry, filename):
    email = load_email(FIXTURES_DIR / filename)
    parser = production_registry.find_parser(email)
    assert parser is None, (
        f"{filename}: should be rejected, but {type(parser).__name__} claimed it"
    )


def test_production_registry_registers_all_five_parsers(production_registry):
    """Guard against dropping a parser from gmail.py again."""
    names = [p.name for p in production_registry.get_parsers()]
    expected = [
        "UOB_CC",
        "UOB_PAYNOW",
        "DBS_CC",
        "DBS_PAYNOW",
        "PAYLAH",
    ]
    assert names == expected, f"production registry order changed: got {names}"
