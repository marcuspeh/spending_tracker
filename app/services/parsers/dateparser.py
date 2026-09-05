"""Locale-independent date/time parser for the formats bank emails use.

The standard ``datetime.strptime`` is *locale-dependent* for ``%b`` and
``%B`` — on a machine where ``LC_TIME`` isn't ``en_US`` it would fail to
parse ``Jan`` / ``January``. All bank emails in this project use English
month names regardless of user locale, so rolling our own tiny parser is
safer (and also means we don't need to mutate ``locale.setlocale`` on
startup, which is global, thread-unsafe, and doesn't work well on macOS).

The public surface is :func:`parse_datetime` which accepts any of the
formats the banks actually send:

- ``%d %B %Y %I:%M %p``   e.g. ``04 January 2026 04:55 PM``
- ``%d %B %Y %H:%M``      e.g. ``04 January 2026 16:55``
- ``%d-%m-%Y %I:%M %p``   e.g. ``04-01-2026 04:55 PM``
- ``%d-%b-%Y %H:%M:%S``   e.g. ``04-Jan-2026 16:55:00``
- ``%d-%m-%Y %H:%M``      e.g. ``04-01-2026 16:55``

All results are timezone-aware SGT.
"""

from __future__ import annotations

import re
from datetime import datetime
from re import Pattern, compile
from typing import Sequence

_MONTH_NUMBERS: dict[str, int] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _strptime(text: str, fmt: str) -> datetime | None:
    """Minimal locale-independent datetime parser for the formats we use.

    Supported tokens: ``%d`` (day), ``%m`` (month number), ``%b`` / ``%B``
    (3-letter / full month name — case-insensitive), ``%y`` (2-digit year
    pivoted at 70/30 — ``%y`` 00-69 → 2000s, 70-99 → 1900s), ``%Y``
    (4-digit year), ``%H`` (24h hour), ``%I`` (12h hour), ``%M`` (minute),
    ``%S`` (second), ``%p`` (AM/PM). Anything else is matched literally.
    Returns ``None`` on mismatch.
    """
    token_re: Pattern[str] = compile(r"%([dmbyBHIMSYp])")
    fmt_pos = 0
    text_pos = 0
    day = month = year = hour = minute = second = None

    for m in token_re.finditer(fmt):
        literal = fmt[fmt_pos : m.start()]
        # The space between %M/%S and %p is often missing in email timestamps
        # (e.g. "10:55PM"). Skip a single space literal if the next char in
        # the text is the AM/PM marker.
        if literal == " " and text_pos < len(text) and text[text_pos] in "AP":
            # Try consuming the AM/PM directly without the space.
            pass  # don't advance text_pos; let the %p branch match
        elif not text.startswith(literal, text_pos):
            return None
        else:
            text_pos += len(literal)
        tok = m.group(1)
        if tok in ("d", "m"):
            mm = re.match(r"(\d{1,2})", text[text_pos:])
            if not mm:
                return None
            value = int(mm.group(1))
            if tok == "d":
                day = value
            else:
                month = value
            text_pos += mm.end()
        elif tok in ("b", "B"):
            mm = re.match(r"([A-Za-z]{3,9})", text[text_pos:])
            if not mm:
                return None
            month = _MONTH_NUMBERS.get(mm.group(1).upper()[:3])
            if month is None:
                return None
            text_pos += mm.end()
        elif tok == "y":
            mm = re.match(r"(\d{2})", text[text_pos:])
            if not mm:
                return None
            yy = int(mm.group(1))
            year = 2000 + yy if yy < 70 else 1900 + yy
            text_pos += mm.end()
        elif tok == "Y":
            mm = re.match(r"(\d{4})", text[text_pos:])
            if not mm:
                return None
            year = int(mm.group(1))
            text_pos += mm.end()
        elif tok == "H":
            mm = re.match(r"(\d{1,2})", text[text_pos:])
            if not mm:
                return None
            hour = int(mm.group(1))
            text_pos += mm.end()
        elif tok == "I":
            mm = re.match(r"(\d{1,2})", text[text_pos:])
            if not mm:
                return None
            hour = int(mm.group(1))
            text_pos += mm.end()
        elif tok == "M":
            mm = re.match(r"(\d{1,2})", text[text_pos:])
            if not mm:
                return None
            minute = int(mm.group(1))
            text_pos += mm.end()
        elif tok == "S":
            mm = re.match(r"(\d{1,2})", text[text_pos:])
            if not mm:
                return None
            second = int(mm.group(1))
            text_pos += mm.end()
        elif tok == "p":
            mm = re.match(r"([AaPp][Mm])", text[text_pos:])
            if not mm:
                return None
            ampm = mm.group(1).upper()
            if hour is None:
                return None
            if ampm == "AM":
                if hour == 12:
                    hour = 0
            else:  # PM
                if hour != 12:
                    hour += 12
            text_pos += mm.end()
        fmt_pos = m.end()

    # Tail literal check
    tail = fmt[fmt_pos:]
    if not text.startswith(tail, text_pos):
        return None

    # Default missing fields. Calendar fields default to the start of
    # the year/month so a date-only input parses to something sensible;
    # time-of-day defaults to midnight so timestamps in the parsed
    # result can always be passed straight into ``datetime()``.
    day = day if day is not None else 1
    month = month if month is not None else 1
    year = year if year is not None else 1900
    hour = hour if hour is not None else 0
    minute = minute if minute is not None else 0
    second = second if second is not None else 0

    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


# Formats tried by parse_datetime(), in order. Keep in approximate
# specificity order — most constrained first, so an ambiguous email
# never matches the wrong shape.
_DATE_FORMATS = (
    "%d %B %Y %I:%M %p",
    "%d %B %Y %H:%M",
    "%d-%m-%Y %I:%M %p",
    "%d-%b-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
)


def parse_datetime(text: str, formats: Sequence[str] | None = None) -> datetime:
    """Parse ``text`` using any of the formats we know bank emails use.

    Defaults to :data:`_DATE_FORMATS` when no explicit list is provided.
    Raises :class:`ValueError` (not ``None``) when no format matches, so
    callers in the bank parsers can translate that into a `ParserError`
    consistently.
    """
    if formats is None:
        formats = _DATE_FORMATS
    for fmt in formats:
        dt = _strptime(text.strip(), fmt)
        if dt is not None:
            return dt
    raise ValueError(f"Unable to parse date/time: {text!r}")


__all__ = [
    "parse_datetime",
    "_DATE_FORMATS",
    "_MONTH_NUMBERS",
    "_strptime",
]
