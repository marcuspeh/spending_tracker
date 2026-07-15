from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.utils.timezone import SGT


@dataclass
class ParsedTransaction:
    """Represents a parsed transaction from an email."""

    amount: Decimal
    merchant: str
    payment_method: str
    transaction_time: datetime
    description: str | None = None


class ParserError(Exception):
    """Exception raised when parsing fails."""

    pass


class BaseParser(ABC):
    """Abstract base class for email parsers."""

    @abstractmethod
    def can_parse(self, email: dict[str, Any]) -> bool:
        """Check if this parser can handle the email.

        Args:
            email: Email dict with 'subject', 'body', 'from', etc.

        Returns:
            True if this parser can handle the email, False otherwise.
        """
        pass

    @abstractmethod
    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        """Parse the email and extract transaction details.

        Args:
            email: Email dict with 'subject', 'body', 'from', etc.

        Returns:
            ParsedTransaction with extracted data.

        Raises:
            ParserError: If parsing fails due to missing or invalid data.
        """
        pass


class BankParser(BaseParser):
    """Shared base for parsers that extract amount/date/merchant from bank
    notification emails.

    Concrete subclasses define:
      - `name`: short identifier (e.g. "UOB_CC")
      - `can_parse(email)`: True iff this parser claims the email
      - `_payment_methods`: enum values this parser may return
      - `_merchant_pattern`: regex used to extract the merchant from body

    Optional overrides:
      - `_extract_amount(body) -> Decimal | None`: default uses the shared
        amount regex.
      - `_extract_date(body) -> datetime | None`: default tries a list of
        common formats.
    """

    # Subclasses set these.
    name: str = ""
    _payment_methods: tuple[str, ...] = ()
    _merchant_pattern: str = r"(?:at|from|to|merchant)\s+([A-Za-z0-9\s&.'-]+?)(?:\s+on|\s+\d|$)"

    # Keywords that mark an incoming/credit transaction.
    _CREDIT_KEYWORDS: tuple[str, ...] = (
        "received",
        "incoming",
        "transfer from",
        "credited",
    )

    # Keywords that mark a refund/reversal.
    _REFUND_KEYWORDS: tuple[str, ...] = ("refund", "reversal")

    # ---------- helpers subclasses can reuse ----------

    def _combined_lower(self, email: dict[str, Any]) -> str:
        return f"{email.get('subject', '')} {email.get('body', '')}".lower()

    def _is_credit(self, body_lower: str) -> bool:
        return any(kw in body_lower for kw in self._CREDIT_KEYWORDS)

    def _is_refund(self, body_lower: str) -> bool:
        return any(kw in body_lower for kw in self._REFUND_KEYWORDS)

    def _extract_amount(self, body: str) -> Decimal:
        """Find the first SGD/S$/$ amount in the body. Raises ParserError."""
        import re

        match = re.search(r"(?:SGD|S\$|\$)\s*([\d,]+\.?\d*)", body)
        if not match:
            raise ParserError(f"Missing amount in {self.name or type(self).__name__} email")
        return Decimal(match.group(1).replace(",", ""))

    def _extract_merchant(self, body: str) -> str:
        """Extract a merchant string using `_merchant_pattern`. Falls back to
        a sensible default if nothing matches.
        """
        import re

        match = re.search(self._merchant_pattern, body, re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip() if match else (self.name or "Transaction")

    def _extract_date(self, body: str) -> datetime:
        """Try a list of date patterns. Falls back to now(SGT)."""
        import re

        # (regex, [strptime formats])
        # Slash/dash formats come BEFORE the 2-digit-year pattern to avoid
        # false matches like "13 JUL 15:30" being parsed as 2015-07-13.
        patterns: list[tuple[str, list[str]]] = [
            (r"(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2})", ["%d %b %Y %H:%M", "%d %B %Y %H:%M"]),
            (r"(\d{1,2}\s+\w+\s+\d{4})", ["%d %B %Y", "%d %b %Y"]),
            (r"(\d{1,2}/\d{1,2}/\d{2,4})", ["%d/%m/%y", "%d/%m/%Y"]),
            (r"(\d{1,2}-\d{1,2}-\d{2,4})", ["%d-%m-%y", "%d-%m-%Y"]),
            (r"(\d{1,2}\s+\w+\s+\d{2})\b", ["%d %b %y", "%d %B %y"]),
        ]
        now = datetime.now(SGT)
        for pattern, formats in patterns:
            m = re.search(pattern, body)
            if not m:
                continue
            for fmt in formats:
                try:
                    parsed = datetime.strptime(m.group(1).strip(), fmt)
                    return parsed.replace(tzinfo=SGT)
                except ValueError:
                    continue
        return now