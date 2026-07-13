from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.uob import UOBParser


class TestUOBParser:
    def setup_method(self):
        self.parser = UOBParser()

    def _make_email(self, subject: str = "", body: str = "") -> dict:
        return {"subject": subject, "body": body}

    def test_can_parse_uob_card_email(self):
        email = self._make_email(subject="UOB Card Transaction Alert")
        assert self.parser.can_parse(email) is True

    def test_can_parse_uob_in_body(self):
        email = self._make_email(body="uob card transaction")
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_other_email(self):
        email = self._make_email(subject="Random email", body="some content")
        assert self.parser.can_parse(email) is False

    def test_parse_valid_purchase(self):
        email = self._make_email(
            subject="UOB Card Transaction Alert",
            body="A transaction of $45.20 was made at Cold Storage on 25 June 2024."
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("45.20")
        assert result.payment_method == "UOB_CARD"

    def test_parse_valid_refund(self):
        email = self._make_email(
            subject="UOB Card Refund Alert",
            body="A refund of $15.00 has been credited to your UOB card on 24 June 2024."
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-15.00")
        assert result.payment_method == "UOB_CARD"

    def test_parse_missing_amount_raises(self):
        email = self._make_email(
            subject="UOB Card",
            body="Some text without any amount"
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    def test_parse_with_comma_separated_amount(self):
        email = self._make_email(
            subject="UOB Card",
            body="Purchase of $1,234.56 at merchant"
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("1234.56")
