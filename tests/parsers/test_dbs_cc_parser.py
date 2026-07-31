from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.dbs_cc import DBSCCParser


class TestDBSCCParser:
    def setup_method(self):
        self.parser = DBSCCParser()

    def _make_email(self, subject: str = "", body: str = "", from_: str = "") -> dict:
        return {"subject": subject, "body": body, "from": from_}

    # --- can_parse ---

    def test_can_parse_dbs_card_subject(self):
        # Card-alert subjects always come from DBS, so the parser should
        # claim any "Card Transaction Alert" / "Card Refund Alert" email
        # that has an amount — even without an explicit DBS signal in the
        # body.
        email = self._make_email(
            subject="Card Transaction Alert",
            from_="ibanking.alert@dbs.com",
            body="Amount: SGD3.98",
        )
        assert self.parser.can_parse(email) is True

    def test_can_parse_dbs_card_with_from(self):
        email = self._make_email(
            subject="Alert",
            body="Your card was used. Amount: SGD3.98",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_uob_card(self):
        email = self._make_email(
            subject="UOB Card Transaction Alert",
            body="UOB card transaction",
            from_="unialerts@uobgroup.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_dbs_paynow(self):
        email = self._make_email(
            subject="PayNow Payment",
            body="You have received SGD 40.00 via PayNow",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    # --- parse ---

    def test_parse_purchase(self):
        email = self._make_email(
            subject="Card Transaction Alert",
            from_="ibanking.alert@dbs.com",
            body=(
                "Date & Time: 13 JUL 15:30 (SGT)\n"
                "Amount: SGD3.98\n"
                "From: DBS/POSB card ending 2453\n"
                "To: APPLE.COM/BILL"
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("3.98")
        assert result.payment_method == "DBS_CC"
        assert result.merchant == "APPLE.COM/BILL"

    def test_parse_refund(self):
        email = self._make_email(
            subject="Card Refund Alert",
            from_="ibanking.alert@dbs.com",
            body="A refund of $25.50 has been credited to your DBS card on 10 June 2024.",
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-25.50")
        assert result.payment_method == "DBS_CC_REFUND"

    def test_parse_missing_amount_raises(self):
        email = self._make_email(
            subject="Card Transaction Alert",
            body="Some text without any amount",
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    def test_parse_real_polled_email(self):
        """Real DBS card email polled from Gmail (uid18)."""
        email = self._make_email(
            subject="Fwd: Card Transaction Alert",
            from_="hkmpeh@gmail.com",
            body=(
                "Date & Time: 13 JUL 15:30 (SGT)\n"
                "Amount: SGD3.98\n"
                "From: DBS/POSB card ending 2453\n"
                "To: APPLE.COM/BILL"
            ),
        )
        assert self.parser.can_parse(email) is True
        result = self.parser.parse(email)
        assert result.amount == Decimal("3.98")
        assert result.payment_method == "DBS_CC"
        assert result.merchant == "APPLE.COM/BILL"

    # --- can_parse negative tests: substring collisions ---

    def test_cannot_parse_substring_collision_cardiology(self):
        email = self._make_email(
            subject="Cardiology appointment reminder",
            body="Your cardiology visit is scheduled.",
            from_="clinic@example.com",
        )
        assert self.parser.can_parse(email) is False
