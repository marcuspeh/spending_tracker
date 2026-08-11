"""Tests for the rich-message transaction table."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

from app.database.enums import PaymentMethod
from app.telegram.handlers._helpers import render_transactions_table


def _fake_txn(
    amount: str = "3.98",
    merchant: str = "STARBUCKS",
    category: str | None = None,
    tag: str | None = None,
) -> MagicMock:
    txn = MagicMock()
    txn.amount = Decimal(amount)
    txn.merchant = merchant
    txn.payment_method = PaymentMethod.DBS_CC
    txn.transaction_time = datetime(2026, 7, 16, 12, 39)
    txn.category = category
    txn.tag = tag
    return txn


class TestCategoryCapitalization:
    """The CATEGORY column capitalizes the first letter for display."""

    def test_capitalizes_lowercase(self):
        html = render_transactions_table([_fake_txn(category="food")])
        assert ">Food<" in html

    def test_capitalizes_uppercase(self):
        html = render_transactions_table([_fake_txn(category="FOOD")])
        assert ">Food<" in html

    def test_displays_empty_when_category_none(self):
        html = render_transactions_table([_fake_txn(category=None)])
        # Empty cell — no entry between the surrounding tags.
        assert "<td></td>" in html

    def test_db_stored_lowercase_remains_in_html(self):
        html = render_transactions_table([_fake_txn(category="shopping")])
        # The raw lowercase must NOT appear in the cell (otherwise the
        # bot would be storing the original form somewhere).
        assert ">Shopping<" in html
        assert ">shopping<" not in html


class TestNormalizeMerchantInTable:
    """The MERCHANT column passes through normalize_merchant (lowercase)."""

    def test_grab_code_collapses_to_grab(self):
        html = render_transactions_table([_fake_txn(merchant="Grab* 4-C8C2JJACBELYWA")])
        assert ">grab<" in html
        assert "C8C2JJACBELYWA" not in html

    def test_grab_subbrand_collapses_to_grab(self):
        html = render_transactions_table([_fake_txn(merchant="GrabFood")])
        assert ">grab<" in html

    def test_passthrough_merchant(self):
        # normalize_merchant lowercases; the table renderer uses the
        # lowercased form for the cell.
        html = render_transactions_table([_fake_txn(merchant="STARBUCKS")])
        assert ">starbucks<" in html


class TestColumns:
    """The column set / ordering is stable."""

    def test_always_shows_category_column(self):
        html = render_transactions_table([_fake_txn()])
        assert ">CATEGORY<" in html

    def test_omits_tag_column_when_no_tags(self):
        html = render_transactions_table([_fake_txn()])
        assert ">TAG<" not in html

    def test_shows_tag_column_when_any_tag_present(self):
        html = render_transactions_table(
            [_fake_txn(tag="coffee_daily"), _fake_txn()]
        )
        assert ">TAG<" in html

    def test_renders_index_1(self):
        html = render_transactions_table([_fake_txn()])
        assert ">1<" in html


class TestDescribeCategoryForDisplay:
    """The shared capitalize-for-display helper."""

    def test_capitalizes_lowercase(self):
        from app.telegram.handlers._helpers import describe_category_for_display

        assert describe_category_for_display(_fake_txn(category="food")) == "Food"

    def test_capitalizes_uppercase(self):
        from app.telegram.handlers._helpers import describe_category_for_display

        assert describe_category_for_display(_fake_txn(category="FOOD")) == "Food"

    def test_returns_dash_when_none(self):
        from app.telegram.handlers._helpers import describe_category_for_display

        assert describe_category_for_display(_fake_txn(category=None)) == "-"

    def test_returns_dash_when_empty_string(self):
        from app.telegram.handlers._helpers import describe_category_for_display

        assert describe_category_for_display(_fake_txn(category="")) == "-"
