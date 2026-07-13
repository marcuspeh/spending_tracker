import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.services.parsers.base import BaseParser, ParsedTransaction, ParserError
from app.utils.timezone import SGT


class PayLahParser(BaseParser):
    """Parser for PayLah transaction emails."""

    def can_parse(self, email: dict[str, Any]) -> bool:
        subject = email.get("subject", "")
        return "PayLah!" in subject

    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        body = email.get("body", "")

        # Try to extract amount
        amount_match = re.search(r"SGD([\d,]+\.?\d*)", body)
        if not amount_match:
            raise ParserError("Missing amount in PayLah email")

        amount_str = amount_match.group(1).replace(",", "")
        amount = Decimal(amount_str)

        # Try to extract merchant
        merchant_match = re.search(r"(?:at|from|to)\s+([A-Za-z0-9\s&]+?)(?:\s+on|\s+\d|$)", body, re.IGNORECASE)
        merchant = "PayLah Transaction"
        if merchant_match:
            merchant = merchant_match.group(1).strip()

        # Try to extract transaction time
        time_match = re.search(r"(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2})", body)
        transaction_time = datetime.now(SGT)
        if time_match:
            try:
                transaction_time = datetime.strptime(time_match.group(1).strip(), "%d %B %Y %H:%M")
                transaction_time = transaction_time.replace(tzinfo=SGT)
            except ValueError:
                pass

        # Determine if it's a refund/credit (negative) or debit (positive)
        is_refund = any(kw in body.lower() for kw in ["refund", "credit", "cashback", "voucher"])
        is_incoming = any(kw in body.lower() for kw in ["received", "incoming", "transfer from", "received from"])

        if is_refund or is_incoming:
            amount = -abs(amount)

        return ParsedTransaction(
            amount=amount,
            merchant=merchant,
            payment_method="PAYLAH",
            transaction_time=transaction_time,
        )
