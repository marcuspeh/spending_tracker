from re import IGNORECASE, compile
from typing import Any

from app.services.parsers.base import BankParser, ParsedTransaction, ParserError


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
    # SG MP" / "at TAMJAI SAM* TAMJAI MIX" / "at TikTok Shop Seller" /
    # "at MONSTER CURRY @ SUNTEC" / "at www trip com" /
    # "at Q &M DENTAL SURGERY-YEW T" (purchase). The keyword is
    # case-insensitive; the capture allows any alphanumeric start so
    # lowercase merchant names ("www trip com") and names whose second
    # character is punctuation ("Q &M ...") are not dropped. The capture
    # is "anything except period/newline" so future special chars
    # (?, !, +, parentheses, etc.) are picked up without needing to
    # enumerate them. Terminal anchors cover: refund connector keywords
    # (`has`, `is`, `on`, `at`, `with`, `to`), the `. If ` sentence break
    # used by purchase alerts, and a generic `.` / `,` / end-of-string.
    #
    # The standard UOB disclaimer also contains a lowercase
    # "from your computer system"; it can never be matched because
    # merchants are only searched inside a transaction chunk, which has
    # the disclaimer stripped off (see `_split_alerts`).
    _merchant_re = compile(
        r"\b(?i:at|from)\s+([A-Za-z0-9][^\.\n]*?)"
        r"(?=\s+(?:has|is|on|at|with|to)\b|\.\s*If\b|[.,]|$)",
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

    # Start of a transaction alert. UOB emails can carry more than one
    # alert (e.g. a Gmail forward carrying two bank emails), so the body
    # is cut on these boundaries and each chunk is parsed on its own.
    _alert_start_re = compile(r"\bA\s+(?:transaction|refund)\s+of\b", IGNORECASE)

    # Every UOB alert is followed by the standard legal disclaimer. It is
    # stripped from each chunk so the merchant regex can't pick up its
    # lowercase "from your computer system" boilerplate. The marker is
    # matched case-insensitively because forwarded emails sometimes
    # reflow it to "Uob Email Disclaimer".
    _disclaimer_re = compile(r"UOB\s+EMAIL\s+DISCLAIMER", IGNORECASE)

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

    def parse_all(self, email: dict[str, Any]) -> list[ParsedTransaction]:
        """Parse every transaction alert contained in the email.

        UOB sometimes delivers several card alerts in a single email.
        Each alert is a self-contained sentence trailed by the standard
        disclaimer, so we split the body on the alert boundaries and
        parse each chunk separately. Chunking also scopes the amount /
        merchant / date regexes to one alert — without it only the
        first transaction in the email would ever be extracted.
        """
        body = email.get("body", "") or ""
        chunks = self._split_alerts(body)
        if not chunks:
            return [self.parse(email)]

        parsed: list[ParsedTransaction] = []
        for chunk in chunks:
            try:
                parsed.append(self.parse({**email, "body": chunk}))
            except ParserError:
                # A chunk without a usable amount is not a transaction
                # we can record; skip it rather than dropping the
                # whole email.
                continue
        if not parsed:
            raise ParserError(
                f"No transaction could be parsed from {self.name} email"
            )
        return parsed

    def _extract_merchant(
        self,
        body: str,
        is_credit: bool = False,
        is_refund: bool = False,
    ) -> str:
        """Extract the merchant, ignoring the legal disclaimer footer.

        The disclaimer contains a lowercase "from your computer system"
        which the merchant regex would otherwise match.
        """
        return super()._extract_merchant(
            self._strip_disclaimer(body),
            is_credit=is_credit,
            is_refund=is_refund,
        )

    @classmethod
    def _strip_disclaimer(cls, body: str) -> str:
        """Cut the UOB legal disclaimer off the end of a body."""
        m = cls._disclaimer_re.search(body)
        if m is None:
            return body
        return body[: m.start()]

    def _split_alerts(self, body: str) -> list[str]:
        """Split a UOB body into its individual transaction alerts.

        Returns an empty list when the body doesn't follow the standard
        alert shape — the caller then parses the body as a single
        transaction.
        """
        starts = [m.start() for m in self._alert_start_re.finditer(body)]
        if not starts:
            return []

        chunks: list[str] = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(body)
            chunk = self._strip_disclaimer(body[start:end]).strip()
            if chunk:
                chunks.append(chunk)
        return chunks
