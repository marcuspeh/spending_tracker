from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.uob_cc import UOBCCParser


class TestUOBCCParser:
    def setup_method(self):
        self.parser = UOBCCParser()

    def _make_email(self, subject: str = "", body: str = "", from_: str = "") -> dict:
        return {"subject": subject, "body": body, "from": from_}

    # --- can_parse ---

    def test_can_parse_uob_card_subject(self):
        email = self._make_email(subject="UOB Card Transaction Alert")
        assert self.parser.can_parse(email) is True

    def test_can_parse_uob_card_in_body(self):
        # Forwarded email: "UOB - Transaction Alert" subject, "Card" only in body
        email = self._make_email(
            subject="UOB - Transaction Alert",
            body="Your UOB Card ending 5522 was used.",
        )
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_dbs_card(self):
        email = self._make_email(
            subject="Card Transaction Alert",
            body="DBS card transaction",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_uob_paynow(self):
        email = self._make_email(
            subject="PayNow Payment",
            body="You made a PayNow transfer via UOB",
            from_="uob-noreply@uobgroup.com",
        )
        assert self.parser.can_parse(email) is False

    # --- parse ---

    def test_parse_purchase(self):
        email = self._make_email(
            subject="UOB Card Transaction Alert",
            body="A transaction of $45.20 was made at Cold Storage on 25 June 2024.",
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("45.20")
        assert result.payment_method == "UOB_CC"

    def test_parse_refund(self):
        email = self._make_email(
            subject="UOB Card Refund Alert",
            body="A refund of $15.00 has been credited to your UOB card on 24 June 2024.",
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-15.00")
        assert result.payment_method == "UOB_CC_REFUND"

    def test_parse_missing_amount_raises(self):
        email = self._make_email(
            subject="UOB Card",
            body="Some text without any amount",
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    def test_parse_with_comma_separated_amount(self):
        email = self._make_email(
            subject="UOB Card",
            body="Purchase of $1,234.56 at merchant",
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("1234.56")

    def test_parse_real_polled_email(self):
        """Real UOB card email polled from Gmail (uid16)."""
        email = self._make_email(
            subject="Fwd: UOB - Transaction Alert",
            from_="hkmpeh@gmail.com",
            body=(
                "A transaction of SGD 4.22 was made with your UOB Card ending 5522 "
                "on 14/07/26 at BUS/MRT."
            ),
        )
        assert self.parser.can_parse(email) is True
        result = self.parser.parse(email)
        assert result.amount == Decimal("4.22")
        assert result.payment_method == "UOB_CC"
        assert result.transaction_time.year == 2026
        assert result.transaction_time.month == 7
        assert result.transaction_time.day == 14
