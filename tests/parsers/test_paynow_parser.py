from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.paynow import PayNowParser


class TestPayNowParser:
    def setup_method(self):
        self.parser = PayNowParser()

    def _make_email(self, subject: str = "", body: str = "") -> dict:
        return {"subject": subject, "body": body}

    def test_can_parse_paynow_email(self):
        email = self._make_email(subject="PayNow Payment Notification")
        assert self.parser.can_parse(email) is True

    def test_can_parse_paynow_in_body(self):
        email = self._make_email(body="paynow transaction")
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_other_email(self):
        email = self._make_email(subject="Random email", body="some content")
        assert self.parser.can_parse(email) is False

    def test_parse_valid_payment(self):
        email = self._make_email(
            subject="PayNow Payment",
            body="You have sent a PayNow payment of $25.00 to John on 25 June 2024 14:30."
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("25.00")
        assert result.payment_method == "PAYNOW"

    def test_parse_valid_refund(self):
        email = self._make_email(
            subject="PayNow Received",
            body="You have received a refund of $10.00 from Acme on 24 June 2024 10:15."
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-10.00")
        assert result.payment_method == "PAYNOW"

    def test_parse_missing_amount_raises(self):
        email = self._make_email(
            subject="PayNow",
            body="Some text without any amount"
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    def test_parse_with_comma_separated_amount(self):
        email = self._make_email(
            subject="PayNow",
            body="Payment of $1,234.56 to merchant"
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("1234.56")
