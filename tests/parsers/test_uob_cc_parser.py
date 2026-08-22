from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.uob_cc import UOBCCParser


class TestUOBCCParser:
    def setup_method(self):
        self.parser = UOBCCParser()

    def _make_email(self, subject: str = "", body: str = "", from_: str = "") -> dict:
        return {"subject": subject, "body": body, "from": from_}

    def test_can_parse_uob_card_subject(self):
        email = self._make_email(
            subject="UOB Card Transaction Alert",
            body="A transaction of SGD 45.20 at Cold Storage.",
        )
        assert self.parser.can_parse(email) is True

    def test_can_parse_uob_card_in_body(self):
        email = self._make_email(
            subject="UOB - Transaction Alert",
            body="Your UOB Card ending 5522 was used. Amount: SGD4.22",
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

    def test_cannot_parse_uob_bill_payment(self):
        # Bill-payment notifications mention "UOB", "Cards", and an SGD
        # amount — superficially card-shaped, but they're actually
        # bank-to-card transfers the UOB bank parser doesn't claim.
        # Without this guard the parser was producing garbage rows
        # (merchant pulled from the disclaimer footer, time fallback
        # to now()).
        email = self._make_email(
            subject="UOB - Bill Payment Notification",
            body=(
                "You made/scheduled a bill payment(s) of SGD 432.62 to "
                "UOB Cards on your a/c ending 8404 at 8:56AM SGT, 20 Aug 26. "
                "Bill ref: ending 1395."
            ),
            from_="unialerts@uobgroup.com",
        )
        assert self.parser.can_parse(email) is False

    def test_parse_purchase(self):
        email = self._make_email(
            subject="UOB Card Transaction Alert",
            body="A transaction of $45.20 was made at Cold Storage on 25 June 2024.",
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("45.20")
        assert result.payment_method == "UOB_CC"

    def test_parse_less_than_1_dollar_purchase(self):
        email = self._make_email(
            subject="UOB Card Transaction Alert",
            body="A transaction of SGD .20 was made with your UOB Card ending 1395 on 13/08/26 at ATLAS VENDING. If unauthorised, call 24/7 Fraud Hotline now",
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal(".20")
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

    def test_parse_purchase_with_asterisk_merchant(self):
        # Card networks add a `*` to merchant names (e.g. "TAMJAI SAM*").
        # The capture class must include `*` so these merchants aren't
        # silently dropped to the parser-name fallback.
        email = self._make_email(
            subject="UOB - Transaction Alert",
            body=(
                "A transaction of SGD 32.61 was made with your UOB Card "
                "ending 1395 on 21/08/26 at TAMJAI SAM* TAMJAI MIX. "
                "If unauthorised, call 24/7 Fraud Hotline now"
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("32.61")
        assert result.merchant == "TAMJAI SAM* TAMJAI MIX"
        assert result.payment_method == "UOB_CC"

    def test_merchant_is_not_pulled_from_disclaimer_footer(self):
        # The UOB standard disclaimer contains "from your computer
        # system" in lowercase. If the regex runs under IGNORECASE the
        # captured merchant silently becomes that footer fragment.
        email = self._make_email(
            subject="UOB - Transaction Alert",
            body=(
                "A transaction of SGD 32.61 was made with your UOB Card "
                "ending 1395 on 21/08/26 at TAMJAI SAM* TAMJAI MIX. If "
                "unauthorised, call 24/7 Fraud Hotline now \n UOB EMAIL "
                "DISCLAIMER: If you are not the intended recipient, "
                "please delete all copies of this email from your "
                "computer system."
            ),
        )
        result = self.parser.parse(email)
        assert "computer system" not in result.merchant.lower()
        assert result.merchant == "TAMJAI SAM* TAMJAI MIX"

    def test_parse_with_comma_separated_amount(self):
        email = self._make_email(
            subject="UOB Card",
            body="Purchase of $1,234.56 at merchant",
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("1234.56")

    def test_parse_real_polled_email(self):
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