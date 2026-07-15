from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.uob import UOBParser


class TestUOBParser:
    def setup_method(self):
        self.parser = UOBParser()

    def _make_email(
        self, subject: str = "", body: str = "", from_: str = ""
    ) -> dict:
        return {"subject": subject, "body": body, "from": from_}

    # --- can_parse ---

    def test_can_parse_uob_card(self):
        email = self._make_email(subject="UOB Card Transaction Alert")
        assert self.parser.can_parse(email) is True

    def test_can_parse_uob_paynow(self):
        email = self._make_email(
            subject="PayNow Payment Alert",
            body="You have sent a PayNow payment via UOB",
            from_="uob-noreply@uobgroup.com",
        )
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_uob_paylah(self):
        # UOB does not offer PayLah — emails mentioning both UOB and PayLah
        # should NOT be claimed by UOBParser.
        email = self._make_email(
            subject="PayLah! Transfer",
            body="PayLah! notification",
            from_="paylah.alerts@uobgroup.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_dbs_email(self):
        email = self._make_email(
            subject="Card Transaction Alert",
            body="DBS card transaction",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_unrelated(self):
        email = self._make_email(subject="Random email", body="some content")
        assert self.parser.can_parse(email) is False

    # --- CC ---

    def test_parse_uob_cc_purchase(self):
        email = self._make_email(
            subject="UOB Card Transaction Alert",
            body=(
                "A transaction of $45.20 was made at Cold Storage on 25 June 2024.\n"
                "Card ending in 1234"
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("45.20")
        assert result.payment_method == "UOB_CC"

    def test_parse_uob_cc_refund(self):
        email = self._make_email(
            subject="UOB Card Refund Alert",
            body=(
                "A refund of $15.00 has been credited to your UOB card on 24 June 2024."
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-15.00")
        assert result.payment_method == "UOB_CC_REFUND"

    def test_parse_uob_cc_missing_amount(self):
        email = self._make_email(
            subject="UOB Card Transaction Alert",
            body="Some text without any amount",
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    # --- PayNow ---

    def test_parse_uob_paynow_debit(self):
        email = self._make_email(
            subject="PayNow Payment Alert",
            from_="uob-noreply@uobgroup.com",
            body=(
                "You have sent a PayNow payment of $50.00 to ALICE WONG on "
                "20 May 2024 09:15."
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("50.00")
        assert result.payment_method == "UOB_PAYNOW_DEBIT"

    def test_parse_uob_paynow_credit(self):
        email = self._make_email(
            subject="PayNow Received Funds Notification",
            from_="uob-noreply@uobgroup.com",
            body=(
                "You have received a PayNow transfer of $80.00 from BOB LIM on "
                "22 May 2024 16:00."
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-80.00")
        assert result.payment_method == "UOB_PAYNOW_CREDIT"

    # --- real polled email ---

    def test_parse_real_polled_email(self):
        """Real UOB email polled from Gmail (uid16) — forwarded, dd/mm/yy date,
        SGD-prefixed amount, 'Card' only in body."""
        email = self._make_email(
            subject="Fwd: UOB - Transaction Alert",
            from_="hkmpeh@gmail.com",
            body=(
                "---------- Forwarded message ---------\n"
                "From: <unialerts@uobgroup.com>\n"
                "Date: Tue, Jul 14, 2026 at 6:01 AM\n"
                "Subject: UOB - Transaction Alert\n\n"
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