from decimal import Decimal
from typing import Any

from app.services.parsers.base import BankParser, ParsedTransaction


class UOBPayNowParser(BankParser):
    """Parser for UOB PayNow transaction emails.

    Returns `UOB_PAYNOW_DEBIT` for outgoing and `UOB_PAYNOW_CREDIT` for
    incoming transfers.
    """

    name = "UOB_PAYNOW"
    _payment_methods = ("UOB_PAYNOW_DEBIT", "UOB_PAYNOW_CREDIT")
    _merchant_pattern = r"(?:to|from|via|payment to)\s+([A-Za-z0-9\s]+?)(?:\s+on\s+|\s+\d|\s*$)"

    def can_parse(self, email: dict[str, Any]) -> bool:
        subject = email.get("subject", "")
        body = email.get("body", "")
        from_ = email.get("from", "") or ""
        combined = f"{subject} {body} {from_}".lower()
        # UOB bank signal AND PayNow channel signal.
        return "uob" in combined and "paynow" in combined

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
            payment_method="UOB_PAYNOW_CREDIT" if is_credit else "UOB_PAYNOW_DEBIT",
            transaction_time=self._extract_date(body),
        )