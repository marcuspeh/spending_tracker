from re import IGNORECASE, compile
from typing import Any

from app.services.parsers.base import BankParser


class UOBPayNowParser(BankParser):
    """Parser for UOB PayNow transaction emails.

    Sample body shapes::

        # Debit
        You made a PayNow transfer of SGD 420.00 to JOHN DOE
        (Mobile ending 7630) on your a/c ending 2929 at 8:30PM SGT, 12 Jun 26.

        # Debit (alternate)
        You have sent a PayNow payment of $50.00 to ALICE WONG on
        20 May 2024 09:15.

        # Credit
        You have received a PayNow transfer of $80.00 from BOB LIM on
        22 May 2024 16:00.

    Returns `UOB_PAYNOW_DEBIT` for outgoing and `UOB_PAYNOW_CREDIT` for
    incoming transfers.
    """

    name = "UOB_PAYNOW"
    _debit_method = "UOB_PAYNOW_DEBIT"
    _credit_method = "UOB_PAYNOW_CREDIT"

    # Merchant: "to JOHN DOE" or "from BOB LIM". Anchor on the amount
    # (SGD/$) so we don't pick up incidental "to ..." inside the disclaimer.
    _merchant_re = compile(
        r"(?:SGD|S\$|\$)\s*[\d,]+\.?\d*[\s\S]{0,200}?\b(?:to|from)\s+"
        r"([A-Z][A-Za-z0-9\s.&'/\-]*?)(?:\s+on\s+|\s+\(|\s*\.|,|$)",
        IGNORECASE,
    )

    # Dates: "on 20 May 2024 09:15", "at 8:30PM SGT, 12 Jun 26", "on 22 May
    # 2024 16:00", "on 15-SEP-2025 11:21PM". 4-digit-year form first.
    _date_patterns = [
        (
            compile(r"on\s+(\d{1,2}-\w+-\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)"),
            ["%d-%b-%Y %I:%M %p", "%d-%B-%Y %I:%M %p"],
        ),
        (
            compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2})"),
            ["%d %B %Y %H:%M", "%d %b %Y %H:%M"],
        ),
        (compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4})"), ["%d %B %Y", "%d %b %Y"]),
        (compile(r",\s*(\d{1,2}\s+\w+\s+\d{2})\b"), ["%d %b %y", "%d %B %y"]),
    ]

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        if self._is_ignored(combined):
            return False
        # UOB bank signal AND PayNow channel signal.
        return "uob" in combined and "paynow" in combined
