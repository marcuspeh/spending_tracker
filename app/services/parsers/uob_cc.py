from re import compile
from typing import Any

from app.services.parsers.base import BankParser


class UOBCCParser(BankParser):
    """Parser for UOB credit-card transaction emails.

    Sample body shapes::

        # Purchase
        A transaction of SGD 3.80 was made with your UOB Card ending 5522
        on 16/07/26 at BUS/MRT.

        # Refund
        A refund of SGD23.98 from SHOPEE APPLEPAY has been made to your UOB
        card ending 5522 on 06 Jul 2026.

        # Reversal
        A transaction of 2.73 SGD made with your UOB card ending 5522 on
        29 Jul 26, 10:55PM at SHOPEE SG MP has been reversed.

    Returns `UOB_CC` for purchases and `UOB_CC_REFUND` for refunds/reversals.
    """

    name = "UOB_CC"
    _debit_method = "UOB_CC"
    _refund_method = "UOB_CC_REFUND"

    # Amount appears as:
    #   "A transaction of SGD 3.80 ..."
    #   "A refund of SGD23.98 ..."
    #   "A transaction of 2.73 SGD ..."
    # We try two regexes (one for symbol-before, one for symbol-after) so
    # the captured numeric value is always in group 1.
    _amount_re = [
        compile(r"(?:SGD|S\$|\$)\s*([\d,]+\.?\d*)"),
        compile(r"([\d,]+\.?\d*)\s*(?:SGD|S\$|\$)"),
        compile(r"(?:SGD|S\$|\$)\s*(\.\d+)"),
    ]

    # Merchant: "from SHOPEE APPLEPAY" (refund) or "at BUS/MRT" / "at SHOPEE
    # SG MP" / "at TAMJAI SAM* TAMJAI MIX" / "at TikTok Shop Seller"
    # (purchase). Keyword is case-insensitive; capture allows mixed case but
    # the FIRST char must be uppercase so the lowercase "from your computer
    # system" in UOB's disclaimer footer doesn't sneak in. `*` is in the
    # class for card-network suffixes.
    _merchant_re = compile(
        r"\b(?i:at|from)\s+([A-Z][A-Za-z0-9][A-Za-z0-9\s&.'*/\-]*?)(?=\s+(?:has|is|on|at|to|with|in|by|for|the|a|an)\s|\s+\d|\.|,|$)",
    )

    # Dates: "on 16/07/26", "on 06 Jul 2026", "on 29 Jul 26, 10:55PM" or
    # "on 29 Jul 26 10:55PM" (no space before AM/PM). 4-digit-year form
    # is tried first so we land on the correct year.
    _date_patterns = [
        (
            compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)"),
            ["%d %b %Y %I:%M %p", "%d %B %Y %I:%M %p"],
        ),
        (compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4})"), ["%d %B %Y", "%d %b %Y"]),
        (
            compile(r"on\s+(\d{1,2}\s+\w+\s+\d{2},?\s*\d{1,2}:\d{2}\s*[AP]M)"),
            ["%d %b %y %I:%M %p", "%d %B %y %I:%M %p", "%d %b %y, %I:%M %p", "%d %B %y, %I:%M %p"],
        ),
        (compile(r"on\s+(\d{1,2}/\d{1,2}/\d{2,4})"), ["%d/%m/%y", "%d/%m/%Y"]),
        (compile(r"on\s+(\d{1,2}\s+\w+\s+\d{2})"), ["%d %b %y", "%d %B %y"]),
    ]

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        if self._is_ignored(combined):
            return False
        # UOB bank signal + card signal (card can appear in body for
        # forwarded emails where subject is just "UOB - Transaction Alert").
        # Reject PayNow traffic — that's UOBPayNowParser's territory.
        if "paynow" in combined:
            return False
        return "uob" in combined and "card" in combined
