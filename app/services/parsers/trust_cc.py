from decimal import Decimal
from re import IGNORECASE, compile
from typing import Any

from app.services.parsers.base import BankParser
from app.services.parsers.types import ParserError
from app.utils.fx import FxConverter


class TrustCCParser(BankParser):
    """Parser for Trust Bank credit-card transaction emails.

    Sample body shapes::

        # Local (SGD)
        You've spent SGD 3.00 at STARBUCKS COFFEE@ YTP SINGAPORE SG
        on 5 Sep 2026 15:03SGT with Trust Link card.

        # Overseas (any non-SGD currency)
        0% FX fees! You've spent MYR 5999.00 using Trust Link card at
        MACHINES SDN BHD KUALA LUMPUR MY on 24 Sep 2026 21:23SGT.

    Trust only sends debit notifications for its Link card, so this parser
    always returns `TRUST_CC` with a positive amount — no credit / refund
    branch is needed.

    Overseas amounts are converted to SGD using the injected
    :class:`FxConverter` so the stored `amount` is always in SGD.
    """

    name = "TRUST_CC"
    _debit_method = "TRUST_CC"

    # Amount regexes capture both the ISO currency code and the digits.
    # Trust phrases transactions as "SGD 3.00" / "MYR 5999.00" (code
    # first), with the rare "3.00 SGD" fallback. The base's
    # `_extract_amount` looks at group 1 only, so we override it to read
    # both groups and route through the FX converter. We still expose
    # them as a single-`_amount_re` sequence so the base's `_has_amount`
    # guard (which only checks for a match) keeps working.
    _amount_re_code_first = compile(r"\b([A-Z]{3})\s*([\d,]+\.?\d*)")
    _amount_re_number_first = compile(r"([\d,]+\.?\d*)\s*([A-Z]{3})\b")
    _amount_re = [_amount_re_code_first, _amount_re_number_first]

    # Merchant line. Trust uses two phrasings:
    #   Local:    "... at STARBUCKS COFFEE@ YTP SINGAPORE SG on 5 Sep 2026"
    #   Overseas: "... using Trust Link card at MACHINES SDN BHD ... MY on 24 Sep 2026"
    # Both end with a 2-letter country code immediately followed by the
    # " on " that introduces the date, so we anchor on that boundary.
    _merchant_re = compile(
        r"\bat\s+(.+?)\s+[A-Z]{2}\s+on\b",
        IGNORECASE,
    )

    # Date: "on 5 Sep 2026 15:03SGT" — the "SGT" suffix is glued to the
    # minutes with no space, so we capture "5 Sep 2026 15:03" and let the
    # regex's trailing `\s*SGT` swallow the suffix before strptime runs.
    _date_patterns = [
        (
            compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2})\s*SGT"),
            ["%d %b %Y %H:%M", "%d %B %Y %H:%M"],
        ),
    ]

    def __init__(self, fx_converter: FxConverter | None = None):
        super().__init__()
        # None is allowed at construction time so existing tests that
        # instantiate the parser without args keep working; parse() will
        # raise FxError only if a non-SGD currency comes through.
        self._fx = fx_converter

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        # Trust signals: sender domain + the in-app "Trust App" call-out
        # + the "Trust Link card" product name. All three appear in every
        # Trust CC alert, so requiring all of them keeps the parser from
        # claiming unrelated Trust emails (e.g. account notifications).
        if "trustbank.sg" not in combined and "trust bank" not in combined:
            return False
        if "trust app" not in combined:
            return False
        if "trust link card" not in combined:
            return False
        if self._is_ignored(combined):
            return False
        return True

    def _force_positive(self) -> bool:
        """Trust only sends outgoing debit notifications for its Link
        card, so we ignore any credit / refund keyword matches."""
        return True

    def _extract_amount(self, body: str) -> Decimal:
        """Pull the currency code AND digits out of the body, then convert
        any non-SGD amount to SGD via the configured FX converter. SGD
        passes through unchanged."""
        code, digits = self._find_amount(body)
        if code is None or digits is None:
            raise ParserError(
                f"Missing amount in {self.name or type(self).__name__} email"
            )
        amount = Decimal(digits.replace(",", ""))
        if code == "SGD":
            return amount
        if self._fx is None:
            raise ParserError(
                "Trust overseas transaction requires an FX converter but none was configured"
            )
        return self._fx.to_sgd(amount, code)

    def _find_amount(self, body: str) -> tuple[str | None, str | None]:
        """Locate the (currency, digits) pair in the body. Returns
        ``(None, None)`` when no match is found — caller turns that into
        a :class:`ParserError`."""
        m = self._amount_re_code_first.search(body)
        if m:
            return m.group(1), m.group(2)
        m = self._amount_re_number_first.search(body)
        if m:
            return m.group(2), m.group(1)
        return None, None