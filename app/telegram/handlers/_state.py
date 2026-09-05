"""In-memory state caches used by the Telegram command handlers.

All state here is per-process (i.e. not shared between workers or between
bot restarts). That's fine because each of these caches is only an
optimization / convenience over the real state (transaction rows in the DB)
and losing them between restarts just means the user has to re-run /latest
before /delete or /edit again.
"""

from __future__ import annotations

# In-memory state for two-step delete confirmation, keyed by chat_id.
# Sets (not lists) so /delete 5 repeated 100 times stays a single entry.
_pending_deletes: dict[int, set[int]] = {}

# Last list shown to each chat_id: maps the 1-based index in /latest output
# to the real transaction id. Used so /delete <index> and /edit <index> work
# directly off the numbering the user just saw.
_recent_index: dict[int, dict[int, int]] = {}


def remember_recent(chat_id: int, txn_ids: list[int]) -> None:
    """Cache the ordering shown in the most recent list command.

    ``txn_ids[i]`` is the DB id of the transaction shown at 1-based index
    ``i + 1`` in the rendered list.
    """
    _recent_index[chat_id] = {i + 1: txn_id for i, txn_id in enumerate(txn_ids)}


def resolve_recent(chat_id: int, key: int | str) -> int | None:
    """Resolve a user's ``key`` (1-based index from /latest) to the
    real transaction id stored in the most-recent-list cache.

    Returns ``None`` if nothing is cached, the key isn't a valid integer,
    or the key isn't in the cached range.
    """
    cached = _recent_index.get(chat_id, {})
    try:
        key_int = int(key)
    except (TypeError, ValueError):
        return None
    return cached.get(key_int)


def clear_recent(chat_id: int) -> None:
    """Drop the cached list for a chat (call after the user has acted on it
    so they can't accidentally delete a stale index)."""
    _recent_index.pop(chat_id, None)


__all__ = [
    "_pending_deletes",
    "_recent_index",
    "remember_recent",
    "resolve_recent",
    "clear_recent",
]
