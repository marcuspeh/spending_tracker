from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


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
