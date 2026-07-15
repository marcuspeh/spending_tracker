from decimal import Decimal
from typing import Any

from app.services.parsers.base import BankParser, ParsedTransaction


class DBSCCParser(BankParser):
    """Parser for DBS/POSB credit-card transaction emails.

    Returns `DBS_CC` for purchases and `DBS_CC_REFUND` for refunds.
    """

    name = "DBS_CC"
    _payment_methods = ("DBS_CC", "DBS_CC_REFUND")
    # "To: APPLE.COM/BILL" — but skip email-style recipients like
    # "To: <HKMPEH@gmail.com>" that appear in forwarded-message headers.
    _merchant_pattern = r"^To:\s*([^\n\r<]+)$"

    def can_parse(self, email: dict[str, Any]) -> bool:
        subject = email.get("subject", "")
        body = email.get("body", "")
        from_ = email.get("from", "") or ""
        combined = f"{subject} {body} {from_}".lower()
        subject_lower = subject.lower()
        body_lower = body.lower()

        # Reject UOB-sourced emails so they go to UOBCCParser instead.
        if "uob" in combined and "dbs" not in combined and "posb" not in combined:
            return False

        # Reject PayNow emails so they go to DBSPayNowParser.
        if "paynow" in combined:
            return False

        # Strong DBS signals: card-alert subjects always come from DBS.
        if "card transaction alert" in subject_lower or "card refund alert" in subject_lower:
            return True

        # Otherwise require DBS/POSB + card/POSB together.
        has_dbs = "dbs" in combined or "posb" in combined
        has_card_signal = (
            "card" in subject_lower
            or "card" in body_lower
            or "posb" in combined
            or "card transaction" in combined
        )
        return has_dbs and has_card_signal

    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        body = email.get("body", "")
        body_lower = body.lower()

        amount: Decimal = self._extract_amount(body)
        if self._is_refund(body_lower):
            amount = -abs(amount)

        return ParsedTransaction(
            amount=amount,
            merchant=self._extract_merchant(body),
            payment_method="DBS_CC_REFUND" if amount < 0 else "DBS_CC",
            transaction_time=self._extract_date(body),
        )