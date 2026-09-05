"""Shared bank email parser base class.

All five concrete parsers (DBS/UOB credit card + PayNow, plus PayLah)
inherit from :class:`BankParser`, which provides a shared :meth:`parse`
method that delegates amount / merchant / date extraction to subclass
configuration and a set of small, overridable helpers.

The abstract types live in :mod:`app.services.parsers.types` and the
locale-independent date parser lives in
:mod:`app.services.parsers.dateparser` so either can be imported without
pulling in the rest of the bank-specific machinery.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from re import Pattern, compile
from typing import Any, Sequence

from app.services.parsers.dateparser import _strptime
from app.services.parsers.types import BaseParser, ParsedTransaction, ParserError
from app.utils.timezone import SGT


class BankParser(BaseParser):
    """Shared base for parsers that extract amount/date/merchant from bank
    notification emails.

    Each subclass defines regexes tailored to its specific email shape:

      - `name`           : short identifier (e.g. "UOB_CC")
      - `_amount_re`     : compiled regex that captures the transaction amount.
                           The first capture group must be the numeric value
                           (commas allowed). Defaults to ``SGD/S$/$`` matcher.
      - `_merchant_re`   : compiled regex that captures the merchant/payee
                           in its first group. Optional — falls back to
                           `name` if unset or no match.
      - `_date_patterns` : list of ``(compiled_regex, [strptime formats])``
                           tuples tried in order. Optional — falls back to
                           `now(SGT)` if none match.
      - `_debit_method`  : payment-method string for purchases.
      - `_credit_method` : (optional) for incoming transfers.
      - `_refund_method` : (optional) for refunds/reversals.

    A subclass MAY override `_force_positive()` to True for channels that
    never send credit notifications (e.g. PayLah), which makes `_is_credit`
    and `_is_refund` no-ops for sign-flipping.
    """

    name: str = ""
    _debit_method: str = ""
    _credit_method: str = ""
    _refund_method: str = ""

    # Subclasses override these; the defaults keep the base importable.
    _amount_re: Pattern[str] | Sequence[Pattern[str]] = compile(
        r"(?:SGD|S\$|\$)\s*([\d,]+\.?\d*)"
    )
    _merchant_re: Pattern[str] | None = None
    _date_patterns: list[tuple[Pattern[str], list[str]]] = []

    # Matches ISO-format date from email headers that may appear inline in
    # the body. Used to patch year-less dates parsed from the body.
    _iso_date_re: Pattern[str] = compile(r"\bDate:\s*(\d{4})-\d{2}-\d{2}")

    # Keywords that mark an incoming/credit transaction.
    _CREDIT_KEYWORDS: tuple[str, ...] = (
        "received",
        "incoming",
        "transfer from",
        "credited",
    )

    # Keywords that mark a refund/reversal.
    _REFUND_KEYWORDS: tuple[str, ...] = ("refund", "reversal", "reversed")

    # Keywords to ignore an email.
    _IGNORE_KEYWORDS: tuple[str, ...] = (
        "Your Funds Transfer to own account",
        "cancelled",
        "Funds Transfer Limit",
        "bill payment",
    )

    # ---------- helpers subclasses can reuse ----------

    def _combined_lower(self, email: dict[str, Any]) -> str:
        subject = email.get("subject", "") or ""
        body = email.get("body", "") or ""
        from_ = email.get("from", "") or ""
        return f"{subject} {body} {from_}".lower()

    def _is_credit(self, body_lower: str) -> bool:
        return any(kw in body_lower for kw in self._CREDIT_KEYWORDS)

    def _is_refund(self, body_lower: str) -> bool:
        return any(kw in body_lower for kw in self._REFUND_KEYWORDS)

    def _is_ignored(self, body_lower: str) -> bool:
        """True iff the email contains a phrase that means it isn't a real
        transaction we want to track (own-account transfers, cancellations,
        limit-alert notices, etc.). Subclasses consult this from
        ``can_parse`` to reject such emails before the amount / date
        extraction runs."""
        return any(kw.lower() in body_lower for kw in self._IGNORE_KEYWORDS)

    def _force_positive(self) -> bool:
        """Override to True for channels that only send outgoing notifications
        (e.g. PayLah). When True, refund/credit detection is ignored."""
        return False

    def _has_amount(self, body: str) -> bool:
        """True iff any amount regex matches. Used as a guard so notice /
        lock / eDocument emails that happen to mention "card" / "paynow"
        in passing don't get claimed."""
        regexes = (
            self._amount_re if isinstance(self._amount_re, Sequence) else [self._amount_re]
        )
        return any(r.search(body) is not None for r in regexes)

    def _extract_amount(self, body: str) -> Decimal:
        regexes = (
            self._amount_re if isinstance(self._amount_re, Sequence) else [self._amount_re]
        )
        for r in regexes:
            m = r.search(body)
            if m:
                return Decimal(m.group(1).replace(",", ""))
        raise ParserError(
            f"Missing amount in {self.name or type(self).__name__} email"
        )

    def _extract_merchant(
        self,
        body: str,
        is_credit: bool = False,
        is_refund: bool = False,
    ) -> str:
        """Extract the merchant / counterparty name from the body.

        Subclasses can pick a different ``_merchant_re`` based on
        ``is_credit`` / ``is_refund`` by overriding this method. The default
        uses the single ``_merchant_re`` attribute.
        """
        if self._merchant_re is None:
            return self.name or "Transaction"
        m = self._merchant_re.search(body)
        return m.group(1).strip() if m else (self.name or "Transaction")

    def _extract_date(
        self, body: str, email: dict[str, Any] | None = None
    ) -> datetime:
        """Extract the transaction's timestamp.

        Resolution order:
        1. Body regex matches with a time-of-day → use it as-is.
        2. Body regex matches but no time → keep the body's date and
           overlay the time-of-day from the email's `Date:` header (the
           body's date is the actual transaction date).
        3. No match → use the email's `Date:` header, fall back to now().
        """
        if not self._date_patterns:
            return self._fallback_date(email)
        for pattern, formats in self._date_patterns:
            m = pattern.search(body)
            if not m:
                continue
            text = m.group(1).strip()
            for fmt in formats:
                parsed = _strptime(text, fmt)
                if parsed is not None:
                    # Patch year when the body format omits it (e.g.
                    # "dated 16 Jul" → year 1900 placeholder). The
                    # body itself rarely contains a `Date:` header, so
                    # also fall back to the email's `Date:` header.
                    if parsed.year == 1900:
                        year = self._resolve_year(body, email)
                        if year is not None:
                            parsed = parsed.replace(year=year)
                    parsed = parsed.replace(tzinfo=SGT)
                    if self._has_no_time_component(parsed):
                        # Body has only a date. Overlay the time-of-day
                        # from the email's `Date:` header so the row
                        # sorts correctly against same-day transactions.
                        header_dt = self._email_date(email)
                        if header_dt is not None:
                            parsed = parsed.replace(
                                hour=header_dt.hour,
                                minute=header_dt.minute,
                                second=header_dt.second,
                            )
                    return parsed
        return self._fallback_date(email)

    def _resolve_year(self, body: str, email: dict[str, Any] | None) -> int | None:
        """Find the year to backfill a year-less body date.

        Sources, in order:
        1. ``Date: YYYY-MM-DD`` (or similar) in the body itself.
        2. The email's ``Date:`` header.
        """
        ym = self._iso_date_re.search(body)
        if ym:
            return int(ym.group(1))
        header_dt = self._email_date(email)
        if header_dt is not None:
            return header_dt.year
        return None

    @staticmethod
    def _has_no_time_component(parsed: datetime) -> bool:
        """True when the parsed timestamp has no meaningful time-of-day
        (i.e. it's sitting at 00:00:00, which is the strptime default)."""
        return (
            parsed.hour == 0
            and parsed.minute == 0
            and parsed.second == 0
            and parsed.microsecond == 0
        )

    @staticmethod
    def _email_date(email: dict[str, Any] | None) -> datetime | None:
        """Return the email's `Date:` header as a tz-aware SGT datetime,
        or None if it's missing / not a datetime."""
        if not email:
            return None
        raw = email.get("date")
        if not isinstance(raw, datetime):
            return None
        if raw.tzinfo is None:
            return raw.replace(tzinfo=SGT)
        return raw.astimezone(SGT)

    @staticmethod
    def _fallback_date(email: dict[str, Any] | None) -> datetime:
        """Last-resort timestamp when no date pattern matched: prefer the
        email's `Date:` header, otherwise now."""
        header = BankParser._email_date(email)
        return header if header is not None else datetime.now(SGT)

    # ---------- shared parse() ----------

    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        body = email.get("body", "")
        body_lower = body.lower()

        amount = self._extract_amount(body)

        # Decide direction (debit/credit/refund) up front so the merchant
        # extractor can pick the right counterparty line.
        is_credit = (
            not self._force_positive()
            and bool(self._credit_method)
            and self._is_credit(body_lower)
            and not (self._refund_method and self._is_refund(body_lower))
        )
        is_refund = (
            not self._force_positive()
            and bool(self._refund_method)
            and self._is_refund(body_lower)
        )

        if self._force_positive():
            method = self._debit_method
            amount = abs(amount)
        elif is_refund:
            amount = -abs(amount)
            method = self._refund_method
        elif is_credit:
            amount = -abs(amount)
            method = self._credit_method
        else:
            method = self._debit_method

        return ParsedTransaction(
            amount=amount,
            merchant=self._extract_merchant(
                body,
                is_credit=is_credit,
                is_refund=is_refund,
            ),
            payment_method=method,
            transaction_time=self._extract_date(body, email),
        )


__all__ = ["BankParser"]
