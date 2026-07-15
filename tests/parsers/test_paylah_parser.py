from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.paylah import PayLahParser


class TestPayLahParser:
    def setup_method(self):
        self.parser = PayLahParser()

    def _make_email(self, subject: str = "", body: str = "", from_: str = "") -> dict:
        return {"subject": subject, "body": body, "from": from_}

    # --- can_parse ---

    def test_can_parse_paylah(self):
        email = self._make_email(
            subject="Transaction Alerts",
            body="Your PayLah! transaction was completed",
            from_="paylah.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_dbs_paynow(self):
        # Pure PayNow (no PayLah mention) is DBSPayNowParser's territory.
        email = self._make_email(
            subject="PayNow Payment",
            body="DBS PayNow payment",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_paylah_funded_paynow(self):
        # When body says "PayNow Transfer", DBSPayNowParser wins — PayLahParser
        # must NOT also claim it.
        email = self._make_email(
            subject="Transaction Alerts",
            from_="paylah.alert@dbs.com",
            body="We refer to a PayNow Transfer dated 26 Jun.",
        )
        assert self.parser.can_parse(email) is False

    # --- parse ---

    def test_parse_debit(self):
        email = self._make_email(
            subject="Transaction Alerts",
            from_="paylah.alert@dbs.com",
            body=(
                "Amount: SGD2000.00\n"
                "From: PayLah! Wallet (Mobile ending 8352)\n"
                "To: JOHN DOE PTE. LTD."
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("2000.00")
        assert result.payment_method == "PAYLAH_DEBIT"

    def test_parse_amount_stays_positive_even_with_credit_keywords(self):
        # PayLah does NOT send incoming emails — even with "received"/"credit"
        # in body, the parser must NOT flip the sign or return a credit value.
        email = self._make_email(
            subject="PayLah! Transaction",
            from_="paylah.alert@dbs.com",
            body=(
                "You have received SGD 25.50 in your PayLah! Wallet\n"
                "Amount: SGD25.50"
            ),
        )
        result = self.parser.parse(email)
        assert result.payment_method == "PAYLAH_DEBIT"
        assert result.amount == Decimal("25.50")

    def test_parse_missing_amount_raises(self):
        email = self._make_email(
            subject="PayLah! Transaction",
            body="Some text without any amount",
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    def test_parse_real_polled_email(self):
        """Real DBS PayLah debit polled from Gmail (uid17)."""
        email = self._make_email(
            subject="Fwd: Transaction Alerts",
            from_="paylah.alert@dbs.com",
            body=(
                "We refer to your PayLah! Scan & Pay Transfer dated 13 Jul.\n"
                "Date & Time: 13 Jul 08:59 (SGT)\n"
                "Amount: SGD2000.00\n"
                "From: PayLah! Wallet (Mobile ending 8352)\n"
                "To: JOHN DOE PTE. LTD."
            ),
        )
        assert self.parser.can_parse(email) is True
        result = self.parser.parse(email)
        assert result.amount == Decimal("2000.00")
        assert result.payment_method == "PAYLAH_DEBIT"