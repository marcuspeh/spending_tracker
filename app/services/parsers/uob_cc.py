from decimal import Decimal
from typing import Any

from app.services.parsers.base import BankParser, ParsedTransaction


class UOBCCParser(BankParser):
    """Parser for UOB credit-card transaction emails.

    Returns `UOB_CC` for purchases and `UOB_CC_REFUND` for refunds.
    """

    name = "UOB_CC"
    _payment_methods = ("UOB_CC", "UOB_CC_REFUND")

    def can_parse(self, email: dict[str, Any]) -> bool:
        subject = email.get("subject", "")
        body = email.get("body", "")
        from_ = email.get("from", "") or ""
        combined = f"{subject} {body} {from_}".lower()
        # UOB bank signal + card signal (card can appear in body for forwarded
        # emails where subject is just "UOB - Transaction Alert").
        return "uob" in combined and "card" in combined

    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        body = email.get("body", "")
        body_lower = body.lower()

        amount: Decimal = self._extract_amount(body)
        if self._is_refund(body_lower):
            amount = -abs(amount)

        return ParsedTransaction(
            amount=amount,
            merchant=self._extract_merchant(body),
            payment_method="UOB_CC_REFUND" if amount < 0 else "UOB_CC",
            transaction_time=self._extract_date(body),
        )