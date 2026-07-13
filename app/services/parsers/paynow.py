import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.services.parsers.base import BaseParser, ParsedTransaction, ParserError
from app.utils.timezone import SGT


class PayNowParser(BaseParser):
    """Parser for PayNow transaction emails."""

    def can_parse(self, email: dict[str, Any]) -> bool:
        subject = email.get("subject", "")
        body = email.get("body", "")
        combined = f"{subject} {body}".lower()
        return "paynow" in combined

    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        body = email.get("body", "")

        # Try to extract amount
        amount_match = re.search(r"S?\$?\s*([\d,]+\.?\d*)", body)
        if not amount_match:
            raise ParserError("Missing amount in PayNow email")

        amount_str = amount_match.group(1).replace(",", "")
        amount = Decimal(amount_str)

        # Try to extract merchant
        # Look for "to <name>" or similar patterns
        merchant_match = re.search(r"(?:to|from|via|payment to)\s+([A-Za-z0-9\s]+?)(?:\s+on\s+|\s+\d|\s*$)", body, re.IGNORECASE)
        merchant = "PayNow Transaction"
        if merchant_match:
            merchant = merchant_match.group(1).strip()

        # Try to extract transaction time
        time_match = re.search(r"(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)", body)
        transaction_time = datetime.now(SGT)
        if time_match:
            try:
                transaction_time = datetime.strptime(time_match.group(1).strip(), "%d %B %Y %H:%M")
                transaction_time = transaction_time.replace(tzinfo=SGT)
            except ValueError:
                pass

        # Determine if it's a refund/incoming (negative) or payment/outgoing (positive)
        # Look for keywords indicating refund or credit
        is_refund = any(kw in body.lower() for kw in ["refund", "credit", "received", "incoming", "transfer from"])

        if is_refund:
            amount = -abs(amount)

        return ParsedTransaction(
            amount=amount,
            merchant=merchant,
            payment_method="PAYNOW",
            transaction_time=transaction_time,
        )
