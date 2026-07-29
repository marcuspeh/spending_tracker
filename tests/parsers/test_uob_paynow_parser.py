from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.uob_paynow import UOBPayNowParser


class TestUOBPayNowParser:
    def setup_method(self):
        self.parser = UOBPayNowParser()

    def _make_email(self, subject: str = "", body: str = "", from_: str = "") -> dict:
        return {"subject": subject, "body": body, "from": from_}

    # --- can_parse ---

    def test_can_parse_uob_paynow(self):
        email = self._make_email(
            subject="PayNow Payment Alert",
            body="You have sent a PayNow payment via UOB",
            from_="uob-noreply@uobgroup.com",
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
            body="DBS PayNow payment",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    # --- parse ---

    def test_parse_debit(self):
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

    def test_parse_credit(self):
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

    def test_parse_missing_amount_raises(self):
        email = self._make_email(
            subject="PayNow Payment Alert",
            body="Some text without any amount",
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    def test_parse_real_polled_email(self):
        """Real UOB PayNow debit polled from Gmail (uid25)."""
        email = self._make_email(
            subject="Fwd: UOB Personal Internet Banking Notification Alerts",
            from_="hkmpeh@gmail.com",
            body=(
                "You made a PayNow transfer of SGD 420.00 to JOHN DOE "
                "(Mobile ending 7630) on your a/c ending 2929 at 8:30PM SGT, "
                "12 Jun 26."
            ),
        )
        assert self.parser.can_parse(email) is True
        result = self.parser.parse(email)
        assert result.amount == Decimal("420.00")
        assert result.payment_method == "UOB_PAYNOW_DEBIT"
        assert result.transaction_time.month == 6
        assert result.transaction_time.day == 12
