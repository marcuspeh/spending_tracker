from decimal import Decimal
from typing import Any

from app.services.parsers.base import BankParser, ParsedTransaction


class DBSPayNowParser(BankParser):
    """Parser for DBS/POSB PayNow transaction emails.

    Returns `DBS_PAYNOW_DEBIT` for outgoing and `DBS_PAYNOW_CREDIT` for
    incoming transfers.

    Note: PayNow wins over PayLah when both signals appear — some PayLah-
    funded transfers come from PayLah! Alerts but the body explicitly says
    "PayNow Transfer", and those are PayNow debits.
    """

    name = "DBS_PAYNOW"
    _payment_methods = ("DBS_PAYNOW_DEBIT", "DBS_PAYNOW_CREDIT")
    _merchant_pattern = r"(?:to|from|via|payment to)\s+([A-Za-z0-9\s]+?)(?:\s+on\s+|\s+\d|\s*$)"

    def can_parse(self, email: dict[str, Any]) -> bool:
        subject = email.get("subject", "")
        body = email.get("body", "")
        from_ = email.get("from", "") or ""
        combined = f"{subject} {body} {from_}".lower()
        # DBS bank signal AND PayNow channel signal.
        has_dbs = "dbs" in combined or "posb" in combined
        has_paynow = "paynow" in combined
        return has_dbs and has_paynow

    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        body = email.get("body", "")
        body_lower = body.lower()

        amount: Decimal = self._extract_amount(body)
        is_credit = self._is_credit(body_lower)
        if is_credit:
            amount = -abs(amount)

        return ParsedTransaction(
            amount=amount,
            merchant=self._extract_merchant(body),
            payment_method="DBS_PAYNOW_CREDIT" if is_credit else "DBS_PAYNOW_DEBIT",
            transaction_time=self._extract_date(body),
        )