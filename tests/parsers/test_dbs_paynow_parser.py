from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.dbs_paynow import DBSPayNowParser


class TestDBSPayNowParser:
    def setup_method(self):
        self.parser = DBSPayNowParser()

    def _make_email(self, subject: str = "", body: str = "", from_: str = "") -> dict:
        return {"subject": subject, "body": body, "from": from_}

    # --- can_parse ---

    def test_can_parse_dbs_paynow(self):
        email = self._make_email(
            subject="PayNow Payment",
            body="You have received SGD 40.00 via PayNow",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is True

    def test_can_parse_paylah_funded_paynow(self):
        # Some PayLah-funded transfers come from PayLah! Alerts but say
        # "PayNow Transfer" in the body — those are PayNow, not PayLah.
        email = self._make_email(
            subject="Transaction Alerts",
            from_="paylah.alert@dbs.com",
            body="We refer to a PayNow Transfer dated 26 Jun. Amount: SGD10.00",
        )
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_paylah_only(self):
        # Pure PayLah (no PayNow mention) is left for PayLahParser.
        email = self._make_email(
            subject="Transaction Alerts",
            body="We refer to your PayLah! Scan & Pay Transfer.",
            from_="paylah.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_uob_paynow(self):
        email = self._make_email(
            subject="PayNow Payment",
            body="UOB PayNow transfer",
            from_="uob-noreply@uobgroup.com",
        )
        assert self.parser.can_parse(email) is False

    # --- parse ---

    def test_parse_debit(self):
        email = self._make_email(
            subject="PayNow Payment Notification",
            from_="ibanking.alert@dbs.com",
            body=(
                "You have sent a PayNow payment of $25.00 to JOHN DOE on "
                "25 June 2024 14:30."
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("25.00")
        assert result.payment_method == "DBS_PAYNOW_DEBIT"

    def test_parse_credit(self):
        email = self._make_email(
            subject="digibank Alerts - You've received a transfer",
            from_="ibanking.alert@dbs.com",
            body=(
                "You have received SGD 40.00 via PayNow on 07 Jul 2026 09:45 SGT.\n"
                "From: JOHN DOE\n"
                "To: Your DBS/ POSB account ending 5630"
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-40.00")
        assert result.payment_method == "DBS_PAYNOW_CREDIT"
        assert result.transaction_time.year == 2026
        assert result.transaction_time.month == 7
        assert result.transaction_time.day == 7

    def test_parse_missing_amount_raises(self):
        email = self._make_email(
            subject="PayNow Payment",
            body="Some text without any amount",
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)

    def test_parse_real_polled_email(self):
        """Real DBS PayNow debit funded from PayLah wallet (uid26)."""
        email = self._make_email(
            subject="Fwd: Transaction Alerts",
            from_="paylah.alert@dbs.com",
            body=(
                "We refer to a PayNow Transfer dated 26 Jun.\n"
                "Amount: SGD10.00\n"
                "From: PayLah! Wallet (Mobile ending 8352)\n"
                "To: JOHN DOE (Mobile ending 2453)"
            ),
        )
        assert self.parser.can_parse(email) is True
        result = self.parser.parse(email)
        assert result.amount == Decimal("10.00")
        assert result.payment_method == "DBS_PAYNOW_DEBIT"
