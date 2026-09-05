"""Abstract base types shared by all email parsers.

All concrete parsers inherit from :class:`BaseParser` and return
:class:`ParsedTransaction` instances. Separating these types into their own
module keeps :mod:`app.services.parsers.bankparser` focused on the bank-
email extraction logic and makes the type definitions easy to import from
tests and services without pulling in the bank-specific regex machinery.
"""

from __future__ import annotations

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
        """Return True iff this parser claims the email."""
        pass

    @abstractmethod
    def parse(self, email: dict[str, Any]) -> ParsedTransaction:
        """Parse the email and return a `ParsedTransaction`."""
        pass


__all__ = [
    "ParsedTransaction",
    "ParserError",
    "BaseParser",
]
