from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.paylah import PayLahParser


class TestPayLahParser:
    def setup_method(self):
        self.parser = PayLahParser()

    def _make_email(self, subject: str = "", body: str = "", from_: str = "") -> dict:
        return {"subject": subject, "body": body, "from": from_}

    def test_can_parse_paylah(self):
        email = self._make_email(
            subject="Transaction Alerts",
            body="Your PayLah! transaction was completed. Amount: SGD25.00",
            from_="paylah.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_dbs_paynow(self):
        email = self._make_email(
            subject="PayNow Payment",
            body="DBS PayNow payment",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_paylah_funded_paynow(self):
        email = self._make_email(
            subject="Transaction Alerts",
            from_="paylah.alert@dbs.com",
            body="We refer to a PayNow Transfer dated 26 Jun.",
        )
        assert self.parser.can_parse(email) is False

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
        email = self._make_email(
            subject="PayLah! Transaction",
            from_="paylah.alert@dbs.com",
            body=("You have received SGD 25.50 in your PayLah! Wallet\nAmount: SGD25.50"),
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


class TestPayLahParserRefunds:
    """PayLah refunds are inbound credits, not spending. They must be
    skipped rather than recorded as a debit."""

    def setup_method(self):
        self.parser = PayLahParser()

    def _make_email(self, body: str) -> dict:
        return {
            "subject": "Transaction Alerts",
            "body": body,
            "from": "paylah.alert@dbs.com",
        }

    _REFUND_BODY = (
        "Transaction Ref: 261026205359MC794321\n"
        "Dear Sir/Madam,\n"
        "We refer to your PayLah! refund transaction below and are pleased "
        "to confirm that the transaction was completed.\n"
        "Date & Time: 26 Oct20:53 (SGT) Amount: SGD 0.10 "
        "From: BCRS LTD To: PayLah! Wallet (Mobile ending 8352)\n"
        "To view your transactions, login to your PayLah! Wallet and select "
        '"History" at the bottom bar of the Home page.\n'
        "Please call DBS hotline immediately if this was an unauthorised "
        "transaction.\n"
        "Thank you for banking with us.\n"
        "Yours Faithfully, DBS Bank Ltd"
    )

    def test_refund_is_not_parsed(self):
        email = self._make_email(self._REFUND_BODY)
        assert self.parser.can_parse(email) is False

    def test_refund_with_wallet_as_recipient_is_not_parsed(self):
        # Even without the word "refund", a notification naming the
        # wallet as the recipient is money coming back in.
        email = self._make_email(
            "Date & Time: 26 Oct 20:53 (SGT)\n"
            "Amount: SGD 0.10\n"
            "From: BCRS LTD\n"
            "To: PayLah! Wallet (Mobile ending 8352)"
        )
        assert self.parser.can_parse(email) is False

    def test_genuine_debit_is_still_parsed(self):
        # The wallet as the *source* is a real outflow and must keep
        # being claimed.
        email = self._make_email(
            "We refer to your PayLah! Scan & Pay Transfer dated 16 Jul.\n"
            "Date & Time: 16 Jul 10:35 (SGT)\n"
            "Amount: SGD2000.00\n"
            "From: PayLah! Wallet (Mobile ending 8352)\n"
            "To: JOHN DOE PTE. LTD."
        )
        assert self.parser.can_parse(email) is True
        result = self.parser.parse(email)
        assert result.amount == Decimal("2000.00")
        assert result.payment_method == "PAYLAH_DEBIT"
        assert result.merchant == "JOHN DOE PTE. LTD."