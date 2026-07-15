from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.dbs import DBSParser


class TestDBSParser:
    def setup_method(self):
        self.parser = DBSParser()

    def _make_email(
        self, subject: str = "", body: str = "", from_: str = ""
    ) -> dict:
        return {"subject": subject, "body": body, "from": from_}

    # --- can_parse ---

    def test_can_parse_dbs_card_subject(self):
        email = self._make_email(subject="Card Transaction Alert")
        assert self.parser.can_parse(email) is True

    def test_can_parse_dbs_paynow(self):
        email = self._make_email(
            subject="PayNow transfer",
            body="You have received SGD 40.00 via PayNow",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is True

    def test_can_parse_dbs_paylah(self):
        email = self._make_email(
            subject="PayLah! Alerts",
            body="Your PayLah! transaction was completed",
            from_="paylah.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_uob_email(self):
        email = self._make_email(
            subject="UOB Card Transaction Alert",
            body="UOB card transaction",
            from_="unialerts@uobgroup.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_unrelated(self):
        email = self._make_email(subject="Random email", body="some content")
        assert self.parser.can_parse(email) is False

    # --- CC ---

    def test_parse_dbs_cc_purchase(self):
        email = self._make_email(
            subject="Card Transaction Alert",
            from_="ibanking.alert@dbs.com",
            body=(
                "Date & Time: 13 JUL 15:30 (SGT)\n"
                "Amount: SGD3.98\n"
                "From: DBS/POSB card ending 9700\n"
                "To: APPLE.COM/BILL"
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("3.98")
        assert result.payment_method == "DBS_CC"
        assert "APPLE" in result.merchant

    def test_parse_dbs_cc_refund(self):
        email = self._make_email(
            subject="Card Refund Alert",
            from_="ibanking.alert@dbs.com",
            body="A refund of $25.50 has been credited to your DBS card on 10 June 2024.",
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-25.50")
        assert result.payment_method == "DBS_CC_REFUND"

    def test_parse_dbs_cc_missing_amount(self):
        email = self._make_email(
            subject="Card Transaction Alert",
            body="Some text without any amount",
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    # --- PayNow ---

    def test_parse_dbs_paynow_debit(self):
        email = self._make_email(
            subject="PayNow Payment Notification",
            from_="ibanking.alert@dbs.com",
            body=(
                "You have sent a PayNow payment of $25.00 to JOHN TAN on "
                "25 June 2024 14:30."
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("25.00")
        assert result.payment_method == "DBS_PAYNOW_DEBIT"

    def test_parse_dbs_paynow_credit(self):
        email = self._make_email(
            subject="digibank Alerts - You've received a transfer",
            from_="ibanking.alert@dbs.com",
            body=(
                "You have received SGD 40.00 via PayNow on 07 Jul 2026 09:45 SGT.\n"
                "From: TAN SZE YING\n"
                "To: Your DBS/ POSB account ending 5660"
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-40.00")
        assert result.payment_method == "DBS_PAYNOW_CREDIT"
        assert result.transaction_time.year == 2026
        assert result.transaction_time.month == 7
        assert result.transaction_time.day == 7

    # --- PayLah (debit only — no PAYLAH_CREDIT since PayLah doesn't send incoming emails) ---

    def test_parse_paylah_debit(self):
        email = self._make_email(
            subject="Transaction Alerts",
            from_="paylah.alert@dbs.com",
            body=(
                "Amount: SGD2000.00\n"
                "From: PayLah! Wallet (Mobile ending 8352)\n"
                "To: CHOCFIN PTE. LTD."
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("2000.00")
        assert result.payment_method == "PAYLAH_DEBIT"

    def test_paylah_amount_stays_positive_even_with_credit_keywords(self):
        # PayLah does NOT send incoming emails — even if body contains "received"
        # or "credit", the parser must NOT flip the sign or return PAYLAH_CREDIT.
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

    # --- real polled email ---

    def test_parse_real_polled_email(self):
        """Real DBS card email polled from Gmail (uid18) — forwarded, from
        ibanking.alert@dbs.com."""
        email = self._make_email(
            subject="Fwd: Card Transaction Alert",
            from_="hkmpeh@gmail.com",
            body=(
                "---------- Forwarded message ---------\n"
                "From: ibanking.alert@dbs.com\n"
                "Date: Mon, Jul 13, 2026 at 3:30 PM\n"
                "Subject: Card Transaction Alert\n\n"
                "Date & Time: 13 JUL 15:30 (SGT)\n"
                "Amount: SGD3.98\n"
                "From: DBS/POSB card ending 9700\n"
                "To: APPLE.COM/BILL"
            ),
        )
        assert self.parser.can_parse(email) is True
        result = self.parser.parse(email)
        assert result.amount == Decimal("3.98")
        assert result.payment_method == "DBS_CC"
        assert "APPLE" in result.merchant