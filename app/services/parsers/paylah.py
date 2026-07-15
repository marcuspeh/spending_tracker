from decimal import Decimal
from typing import Any

from app.services.parsers.base import BankParser, ParsedTransaction


class PayLahParser(BankParser):
    """Parser for DBS PayLah transaction emails.

    PayLah only sends outgoing payment notifications (no incoming email), so
    this parser always returns `PAYLAH_DEBIT` with a positive amount — even
    when the body contains words like "received" or "credit", PayLah is
    never the destination.
    """

    name = "PAYLAH"
    _payment_methods = ("PAYLAH_DEBIT",)

    def can_parse(self, email: dict[str, Any]) -> bool:
        subject = email.get("subject", "")
        body = email.get("body", "")
        from_ = email.get("from", "") or ""
        combined = f"{subject} {body} {from_}".lower()
        # PayLah channel signal — but reject when PayNow is also present, since
        # PayLah-funded PayNow transfers ("We refer to a PayNow Transfer") are
        # claimed by DBSPayNowParser, not this one.
        if "paynow" in combined:
            return False
        return "paylah" in combined

    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        body = email.get("body", "")
        amount: Decimal = self._extract_amount(body)

        return ParsedTransaction(
            amount=abs(amount),  # always positive — PayLah doesn't send incoming emails
            merchant=self._extract_merchant(body),
            payment_method="PAYLAH_DEBIT",
            transaction_time=self._extract_date(body),
        )