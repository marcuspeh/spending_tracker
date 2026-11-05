"""Tests for the SGT window/parsing helpers in :mod:`app.utils.timezone`."""

from datetime import datetime

import pytest

from app.utils.timezone import SGT, get_month_window, parse_year_month


class TestGetMonthWindow:
    def test_defaults_to_current_month(self):
        start, end = get_month_window()
        assert start.day == 1
        assert start.hour == 0 and start.minute == 0
        assert start.tzinfo is SGT
        # End is the 1st of the following month.
        assert (end.year, end.month) == (
            start.year + 1 if start.month == 12 else start.year,
            1 if start.month == 12 else start.month + 1,
        )
        assert end.day == 1

    def test_specific_month(self):
        start, end = get_month_window(2025, 10)
        assert start == datetime(2025, 10, 1, tzinfo=SGT)
        assert end == datetime(2025, 11, 1, tzinfo=SGT)

    def test_december_rolls_into_next_year(self):
        start, end = get_month_window(2025, 12)
        assert start == datetime(2025, 12, 1, tzinfo=SGT)
        assert end == datetime(2026, 1, 1, tzinfo=SGT)


class TestParseYearMonth:
    def test_valid(self):
        assert parse_year_month("2025-10") == (2025, 10)

    def test_strips_whitespace(self):
        assert parse_year_month("  2025-01 ") == (2025, 1)

    def test_invalid_month_raises(self):
        with pytest.raises(ValueError):
            parse_year_month("2025-13")

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_year_month("lastmonth")

    def test_full_date_is_rejected(self):
        with pytest.raises(ValueError):
            parse_year_month("2025-10-15")
