"""Re-export facade for the transaction-management command handlers.

Grouped families of handlers live in sibling modules:

* :mod:`app.telegram.handlers.add_command` — ``/add``
* :mod:`app.telegram.handlers.edit_commands` — per-field edits (/amount, /merchant, /description, /time, /tag)
* :mod:`app.telegram.handlers.delete_commands` — two-step delete flow (/delete, /confirm, /cancel)

Each individual handler is re-exported from this module so the existing
public API (both ``from app.telegram.handlers import add_handler`` style
imports and the ``__init__.py`` re-exports) keeps working with no changes
to any call site.
"""

from app.telegram.handlers.add_command import add_handler
from app.telegram.handlers.delete_commands import (
    cancel_handler,
    confirm_handler,
    delete_handler,
)
from app.telegram.handlers.edit_commands import (
    amount_handler,
    description_handler,
    merchant_handler,
    tag_handler,
    time_handler,
)

__all__ = [
    "add_handler",
    "amount_handler",
    "cancel_handler",
    "confirm_handler",
    "delete_handler",
    "description_handler",
    "merchant_handler",
    "tag_handler",
    "time_handler",
]
