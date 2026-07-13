from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")
UTC = ZoneInfo("UTC")


def now_sgt() -> datetime:
    """Return current time in SGT timezone."""
    return datetime.now(SGT)


def sgt_to_utc(dt: datetime) -> datetime:
    """Convert a SGT datetime to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SGT)
    return dt.astimezone(UTC)


def utc_to_sgt(dt: datetime) -> datetime:
    """Convert a UTC datetime to SGT."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(SGT)


def get_today_window() -> tuple[datetime, datetime]:
    """Get the SGT day window for today (00:00 to 23:59:59.999999)."""
    today = now_sgt().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    return today, tomorrow


def get_week_window() -> tuple[datetime, datetime]:
    """Get the SGT week window (Monday to Sunday)."""
    today = now_sgt()
    # Monday is weekday 0
    days_since_monday = today.weekday()
    week_start = (today - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def get_month_window() -> tuple[datetime, datetime]:
    """Get the SGT month window (1st to end of month)."""
    today = now_sgt()
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Calculate end of month
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)
    return month_start, month_end


def get_range_window(start_date: datetime, end_date: datetime) -> tuple[datetime, datetime]:
    """Get the SGT window for a date range.

    Args:
        start_date: Start date (will be set to 00:00:00 in SGT)
        end_date: End date (will be set to 23:59:59.999999 in SGT)

    Returns:
        Tuple of (start_datetime, end_datetime) in SGT
    """
    start_dt = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start_dt, end_dt


def parse_date(date_str: str) -> datetime:
    """Parse a date string in YYYY-MM-DD format to SGT datetime at start of day."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.replace(tzinfo=SGT)
