import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.services.parsers.base import BaseParser, ParsedTransaction, ParserError
from app.utils.timezone import SGT


_CREDIT_KEYWORDS = ("received", "incoming", "transfer from", "credited")
_REFUND_KEYWORDS = ("refund", "reversal")


class DBSParser(BaseParser):
    """Parser for DBS/POSB transaction emails.

    Handles two transaction types and returns bank-specific enum values:
      - Credit card: DBS_CC (purchase) / DBS_CC_REFUND (refund)
      - PayNow:      DBS_PAYNOW_DEBIT (sent) / DBS_PAYNOW_CREDIT (received)
      - PayLah:      PAYLAH_DEBIT (sent) — only outgoing; PayLah does not
                     send emails for incoming transfers, so there is no
                     PAYLAH_CREDIT value.
    """

    def can_parse(self, email: dict[str, Any]) -> bool:
        subject = email.get("subject", "")
        body = email.get("body", "")
        from_ = email.get("from", "") or ""
        combined = f"{subject} {body} {from_}".lower()
        subject_lower = subject.lower()
        # Reject UOB-sourced emails so they go to UOBParser instead.
        if "uob" in combined and "dbs" not in combined and "posb" not in combined:
            return False
        # Strong DBS signals: card-alert subjects always come from DBS.
        if "card transaction alert" in subject_lower or "card refund alert" in subject_lower:
            return True
        # Otherwise require both a DBS/POSB signal and a transactional signal
        # (card/paynow/paylah) so we don't claim unrelated @dbs.com mail.
        has_dbs = "dbs" in combined or "posb" in combined
        has_transaction_signal = (
            "card" in subject_lower
            or "paynow" in combined
            or "paylah" in combined
            or "posb" in combined
        )
        return has_dbs and has_transaction_signal

    def _classify(self, body_lower: str, subject_lower: str) -> tuple[str, bool]:
        """Return (payment_method, is_credit_negative)."""
        combined_lower = f"{subject_lower} {body_lower}"
        # PayLah — debit only (no PAYLAH_CREDIT; PayLah never sends incoming emails).
        if "paylah" in combined_lower:
            return "PAYLAH_DEBIT", False

        # PayNow
        if "paynow" in combined_lower:
            is_credit = any(kw in combined_lower for kw in _CREDIT_KEYWORDS)
            return ("DBS_PAYNOW_CREDIT" if is_credit else "DBS_PAYNOW_DEBIT"), is_credit

        # Credit card
        is_refund = any(kw in combined_lower for kw in _REFUND_KEYWORDS)
        return ("DBS_CC_REFUND" if is_refund else "DBS_CC"), is_refund

    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        body = email.get("body", "")
        body_lower = body.lower()
        subject = email.get("subject", "")
        subject_lower = subject.lower()

        # Accept "SGD3.98", "$45.20", "S$10.00"
        amount_match = re.search(r"(?:SGD|S\$|\$)\s*([\d,]+\.?\d*)", body)
        if not amount_match:
            raise ParserError("Missing amount in DBS email")

        amount_str = amount_match.group(1).replace(",", "")
        amount = Decimal(amount_str)

        # Merchant: real emails use "To: APPLE.COM/BILL". Skip email-style
        # recipients like "To: <HKMPEH@gmail.com>" from the forwarded header.
        merchant_match = re.search(
            r"^To:\s*([^\n\r<]+)$", body, re.MULTILINE | re.IGNORECASE
        )
        merchant = "DBS Transaction"
        if merchant_match:
            merchant = merchant_match.group(1).strip()

        # Date — accept "13/07/26", "13 JUL 15:30", "13 Jul 2026 15:30"
        transaction_time = datetime.now(SGT)
        date_patterns = [
            (r"(\d{1,2}/\d{1,2}/\d{2,4})", ["%d/%m/%y", "%d/%m/%Y"]),
            (
                r"(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2})",
                ["%d %b %Y %H:%M", "%d %B %Y %H:%M"],
            ),
        ]
        for pattern, formats in date_patterns:
            m = re.search(pattern, body)
            if m:
                for fmt in formats:
                    try:
                        transaction_time = datetime.strptime(m.group(1).strip(), fmt)
                        transaction_time = transaction_time.replace(tzinfo=SGT)
                        break
                    except ValueError:
                        continue
                if transaction_time != datetime.now(SGT):
                    break

        payment_method, flip_negative = self._classify(body_lower, subject_lower)
        if flip_negative:
            amount = -abs(amount)

        return ParsedTransaction(
            amount=amount,
            merchant=merchant,
            payment_method=payment_method,
            transaction_time=transaction_time,
        )