from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.paylah import PayLahParser


class TestPayLahParser:
    def setup_method(self):
        self.parser = PayLahParser()

    def _make_email(self, subject: str = "", body: str = "") -> dict:
        return {"subject": subject, "body": body}

    def test_can_parse_paylah_email(self):
        email = self._make_email(subject="DBS PayLah Transaction Alert")
        assert self.parser.can_parse(email) is True

    def test_can_parse_paylah_in_body(self):
        email = self._make_email(body="dbs paylah transaction")
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_other_email(self):
        email = self._make_email(subject="Random email", body="some content")
        assert self.parser.can_parse(email) is False

    def test_parse_valid_debit(self):
        email = self._make_email(
            subject="DBS PayLah Transaction Alert",
            body="You have made a payment of $8.50 at FairPrice on 25 June 2024 12:45."
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("8.50")
        assert result.payment_method == "PAYLAH"

    def test_parse_valid_refund(self):
        email = self._make_email(
            subject="DBS PayLah Refund Alert",
            body="You have received a refund credit of $3.00 on 24 June 2024 16:30."
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-3.00")
        assert result.payment_method == "PAYLAH"

    def test_parse_missing_amount_raises(self):
        email = self._make_email(
            subject="DBS PayLah",
            body="Some text without any amount"
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    def test_parse_with_comma_separated_amount(self):
        email = self._make_email(
            subject="DBS PayLah",
            body="Payment of $99.99 at merchant"
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("99.99")
