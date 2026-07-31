from re import IGNORECASE, compile
from typing import Any

from app.services.parsers.base import BankParser


class DBSCCParser(BankParser):
    """Parser for DBS/POSB credit-card transaction emails.

    Sample body shape::

        Date & Time: 16 JUL 12:39 (SGT)
        Amount: SGD2.15
        From: DBS/POSB card ending 2453
        To: APPLE.COM/BILL

    Returns `DBS_CC` for purchases and `DBS_CC_REFUND` for refunds/reversals.
    """

    name = "DBS_CC"
    _debit_method = "DBS_CC"
    _refund_method = "DBS_CC_REFUND"

    # Amount usually appears as "Amount: SGD2.15". Some refund bodies phrase
    # it as "A refund of $25.50 has been credited..." — no "Amount:" prefix.
    # Try the anchored form first, fall back to the shared generic matcher.
    _amount_re = [
        compile(r"Amount:\s*(?:SGD|S\$|\$)\s*([\d,]+\.?\d*)", IGNORECASE),
        compile(r"(?:SGD|S\$|\$)\s*([\d,]+\.?\d*)"),
    ]

    # Merchant line: "To: APPLE.COM/BILL". The body always has the merchant
    # "To:" line right after the "From: DBS/POSB card ending NNNN" line
    # (possibly with blank lines in between), so we anchor on that pattern
    # to skip the file-preamble's "To:" header. Capture only the first line
    # after "To:".
    _merchant_re = compile(
        r"card ending \d{4,5}[\s\S]*?To:\s*([^\n\r<][^\n\r]*)",
        IGNORECASE,
    )

    # Date appears as "Date & Time: 16 JUL 12:39 (SGT)" in the body. The
    # body has no year; the base _extract_date patches it from the email's
    # `Date:` header via _iso_date_re.
    _date_patterns = [
        (
            compile(r"Date\s*&\s*Time:\s*(\d{1,2}\s+\w+\s+\d{1,2}:\d{2})"),
            ["%d %b %H:%M", "%d %B %H:%M"],
        ),
    ]

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        if "dbs" not in combined and "posb" not in combined:
            return False
        if "paynow" in combined:
            return False

        # Own-account funds transfers ("iBanking Alerts") are not card
        # transactions even if the body mentions "card transaction request"
        # in passing.
        body_lower = body.lower()
        if self._is_ignored(body_lower):
            return False

        # Strong DBS-CC signals: card-alert subjects from DBS.
        subject_lower = email.get("subject", "").lower()
        if "card transaction alert" in subject_lower or "card refund alert" in subject_lower:
            return True

        # Otherwise require DBS/POSB + a card signal together.
        has_card_signal = (
            "card" in subject_lower
            or "card" in body_lower
            or "posb" in combined
            or "card transaction" in combined
        )
        return has_card_signal
