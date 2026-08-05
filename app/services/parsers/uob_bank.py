from datetime import datetime
from re import IGNORECASE, compile
from typing import Any

from app.services.parsers.base import BankParser, _strptime
from app.utils.timezone import SGT


class UOBBankParser(BankParser):
    """Parser for UOB bank-to-bank transfer emails.

    These come from `unialerts@uobgroup.com` and announce funds transfers
    to external bank accounts (DBS / POSB / GIRO / etc.) — distinct from
    UOB PayNow (which has its own parser) and from UOB card transactions.

    Sample body shape::

        You made/scheduled a funds transfer(s) of SGD 2500.00 to DBS BANK LTD
        a/c ending 5660 from your a/c ending 2929 at 12:35PM SGT, 14 Mar 26.
        If unauthorised, call UOB 24/7 Fraud Hotline.

    Returns ``UOB_BANK_TRANSFER_DEBIT`` for outgoing transfers (the only
    direction UOB sends bank-transfer emails for).
    """

    name = "UOB_BANK"
    _debit_method = "UOB_BANK_TRANSFER_DEBIT"

    # Merchant / counterparty: "to DBS BANK LTD a/c ending NNNN". The
    # body never starts with a preamble "To:" line (it's part of the
    # email header, not the body), so a simple `to ...` capture works.
    _merchant_re = compile(
        r"\bto\s+"
        r"([A-Z][A-Za-z0-9.&'/\-]+(?:\s+[A-Za-z0-9.&'/\-]+)*?"
        r"(?:\s+(?:a/c|account)\s+ending\s+\d+)?)"
        r"(?=\s+from\b|[.,;]|$)",
        IGNORECASE,
    )

    # Dates: "at 12:35PM SGT, 14 Mar 26" — 2-digit-year, month-name, time.
    # Time comes BEFORE the date in the body, so we capture both fields
    # separately and rebuild the datetime via a custom match.
    _date_patterns: list = []  # handled by `_extract_date` override below
    _date_re = compile(
        r"\bat\s+(\d{1,2}:\d{2}\s*[AP]M)\s+SGT,\s*(\d{1,2}\s+\w+\s+\d{2})",
    )

    def _extract_date(self, body: str, email: dict[str, Any] | None = None) -> datetime:
        # Prefer the in-body "at TIME SGT, DATE" form.
        m = self._date_re.search(body)
        if m:
            time_str = m.group(1)
            date_str = m.group(2)
            combined = f"{date_str} {time_str}"
            for fmt in ("%d %b %y %I:%M %p", "%d %B %y %I:%M %p"):
                parsed = _strptime(combined, fmt)
                if parsed is not None:
                    return parsed.replace(tzinfo=SGT)
        # Fall back to base for other shapes (year-patching included).
        return super()._extract_date(body, email)

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        if self._is_ignored(combined):
            return False

        # Only UOB traffic.
        if "uob" not in combined:
            return False

        # Exclude PayNow — that has its own parser.
        if "paynow" in combined:
            return False

        # Exclude card transactions — UOBCCParser owns those.
        if "uob card" in combined or "card transaction" in combined:
            return False

        # Must mention a funds-transfer signal.
        return "funds transfer" in combined
