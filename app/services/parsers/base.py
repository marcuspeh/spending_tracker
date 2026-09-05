"""Re-export facade for all parser primitives.

Callers can keep importing directly from this module just like before —
the concrete implementations live in three smaller files:

* :mod:`app.services.parsers.types` — ``ParsedTransaction`` / ``ParserError`` / ``BaseParser``
* :mod:`app.services.parsers.dateparser` — ``parse_datetime`` and its locale-independent helpers
* :mod:`app.services.parsers.bankparser` — ``BankParser`` base class shared by every bank parser

The private helpers previously defined here (``_strptime``,
``_MONTH_NUMBERS``, ``_DATE_FORMATS``) are still exported so any code
reaching into ``_helpers``-style private names keeps working.
"""

from app.services.parsers.bankparser import BankParser
from app.services.parsers.dateparser import (
    _DATE_FORMATS,
    _MONTH_NUMBERS,
    _strptime,
    parse_datetime,
)
from app.services.parsers.types import BaseParser, ParsedTransaction, ParserError

__all__ = [
    "BankParser",
    "BaseParser",
    "ParsedTransaction",
    "ParserError",
    "_DATE_FORMATS",
    "_MONTH_NUMBERS",
    "_strptime",
    "parse_datetime",
]
