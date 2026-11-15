"""Parser for Citibank Singapore credit-card transaction emails.

Citi sends a single alert template for both credit-card charges and
Ready Credit (loan) movements, so the subject line
``Citi Alerts - Credit Card/Ready Credit Transaction`` cannot be used to
tell them apart. The body can: only a card charge says "charge made on
your Citi ... Card".

Sample body shape (the plain-text alternative of the alert)::

    Dear Customer,
    We would like to inform you that there is a charge made on your Citi Rewards Card:

    Account Number           : XXXX-XXXX-XXXX-8673
    Transaction date         : 15/11/26
    Transaction time         : 14:29:10
    Transaction amount       : SGD9.87
    Transaction  details     : AMAZE* ALIPAYPROGRA    SINGAPORE     SGP

The ``Transaction details`` line holds three fields: the merchant
descriptor, the city and the country code. Only the descriptor is kept.

Returns ``CITI_CC`` for charges and ``CITI_CC_REFUND`` for reversals.
"""

from __future__ import annotations

from decimal import Decimal
from re import IGNORECASE, compile
from typing import Any

from app.services.parsers.base import BankParser
from app.services.parsers.dateparser import _strptime
from app.services.parsers.types import ParserError
from app.utils.fx import FxConverter
from app.utils.timezone import SGT


class CitiCCParser(BankParser):
    """Parser for Citibank (Singapore) credit-card transaction emails."""

    name = "CITI_CC"
    _debit_method = "CITI_CC"
    _refund_method = "CITI_CC_REFUND"

    # Amount line: "Transaction amount       : SGD9.87". The currency
    # code may be glued to the digits ("SGD9.87") or separated by a
    # space ("USD 10.00"); the bare-amount form ("Transaction amount :
    # 9.87") is also accepted.
    _amount_code_re = compile(r"Transaction\s+amount\s*:\s*([A-Z]{3})\s*([\d,]+\.?\d*)", IGNORECASE)
    _amount_symbol_re = compile(
        r"Transaction\s+amount\s*:\s*(?:S\$|\$)\s*([\d,]+\.?\d*)", IGNORECASE
    )
    _amount_plain_re = compile(r"Transaction\s+amount\s*:\s*([\d,]+\.?\d*)")

    # Exposed for the base class' `_has_amount` guard. The group layout
    # differs per pattern, so `_extract_amount` is overridden below
    # instead of relying on the base implementation.
    _amount_re = [_amount_code_re, _amount_symbol_re, _amount_plain_re]

    # Merchant line: "Transaction  details     : AMAZE* ALIPAYPROGRA
    #    SINGAPORE     SGP". The label is inconsistently spaced
    # ("Transaction  details" vs "Transaction details"), so the label
    # separator is matched loosely and the value is captured up to the
    # end of the line.
    _merchant_re = compile(r"Transaction\s+details\s*:\s*([^\n\r]+)", IGNORECASE)

    # Charge gate. Citi uses the same subject ("Citi Alerts - Credit
    # Card/Ready Credit Transaction") for credit-card charges and Ready
    # Credit (loan) movements, so only the body tells them apart: the
    # sentence names the product that was charged.
    _charge_sentence_re = compile(r"charge\s+made\s+on\s+your([^\n\r]*)", IGNORECASE)
    _card_word_re = compile(r"\bcard\b", IGNORECASE)
    _ready_credit_re = compile(r"ready\s+credit", IGNORECASE)

    # The alert ends with a fixed legal boilerplate. The boilerplate
    # talks about "your credit/debit card" and "your Citi Mobile app",
    # so every body-wide signal is scoped to the part of the body above
    # it. The plain-text and HTML alternatives phrase the sign-off
    # differently, so both are listed.
    _boilerplate_re = compile(
        r"(?:Thank you for (?:using Citi Alerts|banking with Citi)\b"
        r"|Never provide your One-Time PIN"
        r"|Citibank Online"
        r"|Citibank Singapore Ltd"
        r"|Please do not reply to this email)",
        IGNORECASE,
    )

    # Date and time live on separate lines:
    #   "Transaction date         : 15/11/26"
    #   "Transaction time         : 14:29:10"
    _date_re = compile(r"Transaction\s+date\s*:\s*(\d{1,2}/\d{1,2}/\d{2,4})", IGNORECASE)
    _time_re = compile(r"Transaction\s+time\s*:\s*(\d{1,2}:\d{2}(?::\d{2})?)", IGNORECASE)
    _date_formats = ("%d/%m/%Y", "%d/%m/%y")

    def __init__(self, fx_converter: FxConverter | None = None):
        super().__init__()
        # None is allowed so tests can instantiate the parser without
        # arguments; a non-SGD amount then raises a ParserError.
        self._fx = fx_converter

    # ---------- can_parse ----------

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        # Citi bank signal: the sender domain (citibank.com.sg), the
        # "Citibank ..." sign-off in the body, or the "Citi Alerts"
        # subject. The body signal keeps forwarded emails working, where
        # `from` is the forwarder's own address.
        if "citibank" not in combined and "citi alerts" not in combined:
            return False
        if self._is_ignored(combined):
            return False
        # The body must name a card. The sentence "there is a charge made
        # on your <product>" names what was charged — a card for card
        # spending, the loan facility for a Ready Credit movement.
        section = self._transaction_section(body)
        charge_m = self._charge_sentence_re.search(section)
        if charge_m:
            target = charge_m.group(1)
            if self._ready_credit_re.search(target):
                return False
            if self._card_word_re.search(target):
                return True
        # No recognisable charge sentence — fall back to the transaction
        # section as a whole, as long as it never mentions the loan
        # facility.
        if self._ready_credit_re.search(section):
            return False
        return self._card_word_re.search(section) is not None

    @classmethod
    def _transaction_section(cls, body: str) -> str:
        """Return the part of the body above the legal boilerplate."""
        m = cls._boilerplate_re.search(body)
        if not m:
            return body
        return body[: m.start()]

    def _is_refund(self, body_lower: str) -> bool:
        """Detect a reversal, scoped to the transaction section.

        The base implementation scans the whole body, but Citi's
        boilerplate mentions refunds and reversals generically, so only
        the transaction part is inspected.
        """
        return super()._is_refund(self._transaction_section(body_lower).lower())

    # ---------- extraction overrides ----------

    def _extract_amount(self, body: str) -> Decimal:
        """Extract the amount (and currency code) from the amount line."""
        code: str | None = None
        digits: str | None = None

        m = self._amount_code_re.search(body)
        if m:
            code, digits = m.group(1), m.group(2)
        else:
            m = self._amount_symbol_re.search(body)
            if m:
                digits = m.group(1)
            else:
                m = self._amount_plain_re.search(body)
                if m:
                    digits = m.group(1)

        if digits is None:
            raise ParserError(f"Missing amount in {self.name or type(self).__name__} email")

        amount = Decimal(digits.replace(",", ""))
        currency = (code or "SGD").upper()
        if currency == "SGD":
            return amount
        if self._fx is None:
            raise ParserError(
                "Citi overseas transaction requires an FX converter but none was configured"
            )
        return self._fx.to_sgd(amount, currency)

    def _extract_merchant(
        self,
        body: str,
        is_credit: bool = False,
        is_refund: bool = False,
    ) -> str:
        """Extract the merchant descriptor from the details line.

        The details line holds three fields: the merchant descriptor,
        the city and the country code. Only the descriptor is kept —
        the city and country carry no extra information for the
        categorizer.
        """
        merchant = self._extract_merchant_descriptor(body)
        if merchant:
            return merchant
        return super()._extract_merchant(body, is_credit=is_credit, is_refund=is_refund)

    def _extract_merchant_descriptor(self, body: str) -> str:
        """Return the merchant descriptor from the details line.

        The plain-text alternative of the alert pads the three fields
        into aligned columns; the HTML alternative does the same but the
        HTML stripper collapses the padding. Both are handled by
        splitting on whitespace and dropping the trailing city and
        country tokens.
        """
        m = self._merchant_re.search(body)
        if not m:
            return ""
        tokens = m.group(1).split()
        tokens = self._trim_location_tokens(tokens)
        return " ".join(tokens)

    @staticmethod
    def _trim_location_tokens(tokens: list[str]) -> list[str]:
        """Drop the trailing country code and city from a details value.

        Citi renders the details as merchant / city / country code. The
        trailing pair is identified by shape: the country token is 2-3
        uppercase letters and the city token is a single uppercase word.

        The city is only dropped when at least two tokens remain
        afterwards, so a one-word merchant followed by a country code is
        not truncated to nothing.
        """
        tokens = list(tokens)
        if len(tokens) < 2:
            return tokens
        country = tokens[-1]
        if not (2 <= len(country) <= 3 and country.isalpha() and country.isupper()):
            return tokens
        tokens.pop()
        if len(tokens) >= 2:
            city = tokens[-1]
            if city.isalpha() and city.isupper() and len(city) > 3:
                tokens.pop()
        return tokens or [country]

    def _extract_date(self, body: str, email: dict[str, Any] | None = None):
        """Combine the separate transaction date and time lines.

        The body carries the date ("15/11/26") and the time ("14:29:10")
        on different lines. When the time line is missing, the time of
        day is taken from the email's ``Date:`` header so the row still
        sorts correctly against same-day transactions.
        """
        m = self._date_re.search(body)
        if not m:
            return super()._extract_date(body, email)

        parsed = None
        for fmt in self._date_formats:
            parsed = _strptime(m.group(1), fmt)
            if parsed is not None:
                break
        if parsed is None:
            return super()._extract_date(body, email)

        time_m = self._time_re.search(body)
        clock = None
        if time_m:
            for fmt in ("%H:%M:%S", "%H:%M"):
                clock = _strptime(time_m.group(1), fmt)
                if clock is not None:
                    break
        if clock is None:
            header_dt = self._email_date(email)
            if header_dt is not None:
                clock = header_dt

        if clock is not None:
            parsed = parsed.replace(hour=clock.hour, minute=clock.minute, second=clock.second)
        return parsed.replace(tzinfo=SGT)

    def parse(self, email: dict[str, Any]):
        """Parse the email, honouring subject-level reversal wording.

        The body of a reversal usually repeats "reversal" / "refund", but
        not always; when only the subject says so, the debit is flipped
        to a refund here.
        """
        result = super().parse(email)
        subject = (email.get("subject", "") or "").lower()
        if result.payment_method == self._debit_method and any(
            keyword in subject for keyword in ("reversal", "refund")
        ):
            result.amount = -abs(result.amount)
            result.payment_method = self._refund_method
        return result


__all__ = ["CitiCCParser"]
