"""Telegram command handlers, grouped by purpose.

Re-exports every handler so existing call sites can keep using
`from app.telegram.handlers import <name>_handler`.
"""

from app.telegram.handlers.general import (
    help_handler,
    ping_handler,
    start_handler,
)
from app.telegram.handlers.management import (
    add_handler,
    cancel_handler,
    categorize_handler,
    confirm_handler,
    delete_handler,
    edit_handler,
    tag_handler,
)
from app.telegram.handlers.queries import (
    latest_handler,
    month_handler,
    range_handler,
    search_handler,
    today_handler,
    week_handler,
)

__all__ = [
    "add_handler",
    "cancel_handler",
    "categorize_handler",
    "confirm_handler",
    "delete_handler",
    "edit_handler",
    "help_handler",
    "latest_handler",
    "month_handler",
    "ping_handler",
    "range_handler",
    "search_handler",
    "start_handler",
    "tag_handler",
    "today_handler",
    "week_handler",
]
