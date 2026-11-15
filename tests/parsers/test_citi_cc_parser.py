from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.citi_cc import CitiCCParser

CARD_BODY = (
    "Dear Customer,\n"
    "We would like to inform you that there is a charge made on your Citi Rewards Card:\n"
    "\n"
    "\n"
    "Account Number           : XXXX-XXXX-XXXX-8673\n"
    "Transaction date         : 15/11/26\n"
    "Transaction time         : 14:29:10\n"
    "Transaction amount       : SGD9.87\n"
    "Transaction  details     : AMAZE* ALIPAYPROGRA    SINGAPORE     SGP\n"
    "\n"
    "\n"
    "Thank you for using Citi Alerts.\n"
    "\n"
    "Citibank Online\n"
    "Citibank Singapore Ltd\n"
    "Co.Reg. No. 200309485K\n"
)


class TestCitiCCParser:
    def setup_method(self):
        self.parser = CitiCCParser()

    def _make_email(self, subject: str = "", body: str = "", from_: str = "") -> dict:
        return {"subject": subject, "body": body, "from": from_}

    def _card_email(self, **overrides) -> dict:
        email = self._make_email(
            subject="Citi Alerts - Credit Card/Ready Credit Transaction",
            from_="Citibank Singapore <alerts@citibank.com.sg>",
            body=CARD_BODY,
        )
        email.update(overrides)
        return email

    # ---------- can_parse ----------

    def test_can_parse_citi_card_alert(self):
        assert self.parser.can_parse(self._card_email()) is True

    def test_can_parse_forwarded_citi_email(self):
        """Forwarded emails keep the Citi body but swap the sender."""
        email = self._make_email(
            subject="Fwd: Citi Alerts - Credit Card/Ready Credit Transaction",
            from_="hkmpeh@gmail.com",
            body=CARD_BODY,
        )
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_other_bank(self):
        email = self._make_email(
            subject="Card Transaction Alert",
            from_="ibanking.alert@dbs.com",
            body="Amount: SGD3.98\nFrom: DBS/POSB card ending 2453",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_citi_ready_credit(self):
        """Ready Credit loan movements share the subject template."""
        body = CARD_BODY.replace(
            "charge made on your Citi Rewards Card:",
            "charge made on your Citi Ready Credit:",
        )
        email = self._card_email(body=body)
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_citi_non_transaction_alert(self):
        email = self._make_email(
            subject="Citi Alerts - Your Card Has Been Locked",
            from_="alerts@citibank.com.sg",
            body="Your card has been locked. Please call us.",
        )
        assert self.parser.can_parse(email) is False

    # ---------- parse ----------

    def test_parse_purchase(self):
        result = self.parser.parse(self._card_email())
        assert result.amount == Decimal("9.87")
        assert result.payment_method == "CITI_CC"
        assert result.merchant == "AMAZE* ALIPAYPROGRA"

    def test_parse_transaction_time(self):
        result = self.parser.parse(self._card_email())
        assert result.transaction_time.strftime("%Y-%m-%d %H:%M:%S") == ("2026-11-15 14:29:10")
        assert result.transaction_time.tzinfo is not None

    def test_parse_html_flattened_body(self):
        """The HTML alternative flattens the column-aligned details line."""
        body = CARD_BODY.replace(
            "Transaction  details     : AMAZE* ALIPAYPROGRA    SINGAPORE     SGP",
            "Transaction details : AMAZE* ALIPAYPROGRA SINGAPORE SGP",
        )
        result = self.parser.parse(self._card_email(body=body))
        assert result.merchant == "AMAZE* ALIPAYPROGRA"
        assert result.amount == Decimal("9.87")

    def test_parse_missing_amount_raises(self):
        email = self._card_email(body="Dear Customer,\nNo amount here.\n")
        with pytest.raises(ParserError):
            self.parser.parse(email)

    def test_parse_amount_with_space_and_symbol(self):
        body = CARD_BODY.replace("Transaction amount       : SGD9.87", "Transaction amount: S$9.87")
        result = self.parser.parse(self._card_email(body=body))
        assert result.amount == Decimal("9.87")

    def test_parse_reversal_in_body_is_refund(self):
        body = CARD_BODY.replace(
            "Transaction  details     : AMAZE* ALIPAYPROGRA    SINGAPORE     SGP",
            "Transaction  details     : AMAZE* ALIPAYPROGRA    SINGAPORE     SGP\n"
            "This transaction has been reversed.",
        )
        result = self.parser.parse(self._card_email(body=body))
        assert result.amount == Decimal("-9.87")
        assert result.payment_method == "CITI_CC_REFUND"

    def test_boilerplate_mentioning_refund_is_not_a_refund(self):
        """The legal boilerplate must not turn a charge into a refund."""
        body = CARD_BODY.replace(
            "Thank you for using Citi Alerts.",
            "Thank you for using Citi Alerts. Refunds are processed within 5 days.",
        )
        result = self.parser.parse(self._card_email(body=body))
        assert result.amount == Decimal("9.87")
        assert result.payment_method == "CITI_CC"

    def test_parse_reversal_in_subject_is_refund(self):
        email = self._card_email(
            subject="Citi Alerts - Credit Card Transaction Reversal",
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("-9.87")
        assert result.payment_method == "CITI_CC_REFUND"

    def test_parse_uses_email_date_when_time_missing(self):
        from datetime import datetime

        from app.utils.timezone import SGT

        body = "\n".join(line for line in CARD_BODY.splitlines() if "Transaction time" not in line)
        email = self._card_email(body=body)
        email["date"] = datetime(2026, 11, 15, 6, 29, 14, tzinfo=SGT)
        result = self.parser.parse(email)
        assert result.transaction_time.strftime("%Y-%m-%d %H:%M:%S") == ("2026-11-15 06:29:14")

    def test_parse_foreign_currency_requires_fx_converter(self):
        from tests.parsers._fx_stub import StubFxConverter

        body = CARD_BODY.replace(
            "Transaction amount       : SGD9.87", "Transaction amount: USD 10.00"
        )
        email = self._card_email(body=body)

        with pytest.raises(ParserError):
            CitiCCParser().parse(email)

        parser = CitiCCParser(fx_converter=StubFxConverter(rates={"USD": Decimal("1.30")}))
        result = parser.parse(email)
        assert result.amount == Decimal("13.07")
