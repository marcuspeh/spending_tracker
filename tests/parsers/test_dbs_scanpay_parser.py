from decimal import Decimal

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.dbs_scanpay import DBSScanPayParser


class TestDBSScanPayParser:
    def setup_method(self):
        self.parser = DBSScanPayParser()

    def _make_email(self, subject: str = "", body: str = "", from_: str = "") -> dict:
        return {"subject": subject, "body": body, "from": from_}

    def test_can_parse_scan_and_pay(self):
        email = self._make_email(
            subject="digibank alert",
            body=(
                "Your NETS Scan & Pay transaction on 03 Oct 12:26 SGT was successful.\n"
                "Amount: S$8.50"
            ),
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is True

    def test_can_parse_scan_and_pay_spelled_out(self):
        # Some DBS emails write "Scan and Pay" instead of "Scan & Pay".
        email = self._make_email(
            subject="digibank alert",
            body=(
                "Your NETS Scan and Pay transaction was successful.\n"
                "Amount: S$8.50"
            ),
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_paynow_only(self):
        # "PayNow" without "Scan & Pay" should be left to DBSPayNowParser.
        email = self._make_email(
            subject="PayNow Payment",
            body="You have received SGD 40.00 via PayNow on 07 Jul 2026 09:45 SGT.",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_dbs_credit_card(self):
        email = self._make_email(
            subject="Card Transaction Alert",
            body=(
                "Date & Time: 16 JUL 12:39 (SGT)\n"
                "Amount: SGD2.15\n"
                "From: DBS/POSB card ending 2453\n"
                "To: APPLE.COM/BILL"
            ),
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_uob(self):
        email = self._make_email(
            subject="UOB Transaction Alert",
            body="Your NETS Scan & Pay transaction was successful.",
            from_="uob-noreply@uobgroup.com",
        )
        assert self.parser.can_parse(email) is False

    def test_defers_paylah_wallet_to_paylah_parser(self):
        # PayLah-funded Scan & Pay transfers phrase the flow as
        # "PayLah! Scan & Pay Transfer" with the wallet as the funding
        # source. Even though both "scan & pay" and "dbs" appear, this
        # parser must defer to PayLahParser so the merchant extractor
        # sees the wallet and tags the payment as PAYLAH_DEBIT.
        email = self._make_email(
            subject="Transaction Alerts",
            body=(
                "We refer to your PayLah! Scan & Pay Transfer dated 26 Jun.\n"
                "Amount: SGD10.00\n"
                "From: PayLah! Wallet (Mobile ending 8352)\n"
                "To: JOHN DOE"
            ),
            from_="paylah.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_without_amount(self):
        email = self._make_email(
            subject="digibank alert",
            body="Your NETS Scan & Pay transaction was successful.",
            from_="ibanking.alert@dbs.com",
        )
        assert self.parser.can_parse(email) is False

    def test_parse_extracts_amount_and_merchant(self):
        email = self._make_email(
            subject="digibank alert",
            from_="ibanking.alert@dbs.com",
            body=(
                "Transaction Ref: 627609564051570\n"
                "Dear Customer,\n"
                "Your NETS Scan & Pay transaction on 03 Oct 12:26 SGT was successful.\n"
                "Date & Time: 03 Oct 12:26 SGT\n"
                "Amount: S$8.50\n"
                "From: DBS/POSB Account ending 5660\n"
                "To: MR BEAN\n"
            ),
        )
        result = self.parser.parse(email)
        assert result.amount == Decimal("8.50")
        assert result.merchant == "MR BEAN"
        assert result.payment_method == "DBS_PAYNOW_DEBIT"

    def test_parse_missing_amount_raises(self):
        email = self._make_email(
            subject="digibank alert",
            body="Your NETS Scan & Pay transaction was successful.",
            from_="ibanking.alert@dbs.com",
        )
        with pytest.raises(ParserError):
            self.parser.parse(email)
