"""Tests for the in-memory ``_recent_index`` mapping used by ``/latest``,
``/delete``, ``/confirm``, ``/edit`` and ``/cancel``."""

import pytest

from app.telegram.handlers._helpers import (
    _recent_index,
    clear_recent,
    remember_recent,
    resolve_recent,
)


@pytest.fixture(autouse=True)
def _reset():
    """Wipe the module-level cache between tests so they're hermetic."""
    _recent_index.clear()
    yield
    _recent_index.clear()


class TestRememberAndResolve:
    def test_remember_stores_1_based_mapping(self):
        remember_recent(chat_id=42, txn_ids=[101, 102, 103])
        assert resolve_recent(42, "1") == 101
        assert resolve_recent(42, "2") == 102
        assert resolve_recent(42, "3") == 103

    def test_resolve_int_key(self):
        remember_recent(chat_id=42, txn_ids=[101, 102])
        assert resolve_recent(42, 1) == 101

    def test_resolve_returns_db_id_not_index(self):
        remember_recent(chat_id=42, txn_ids=[9999])
        result = resolve_recent(42, "1")
        assert result == 9999
        assert result != 1

    def test_resolve_out_of_range_returns_none(self):
        remember_recent(chat_id=42, txn_ids=[101, 102])
        assert resolve_recent(42, "5") is None
        assert resolve_recent(42, "0") is None

    def test_resolve_no_cache_returns_none(self):
        assert resolve_recent(42, "1") is None

    def test_resolve_invalid_key_returns_none(self):
        remember_recent(chat_id=42, txn_ids=[101])
        assert resolve_recent(42, "abc") is None
        assert resolve_recent(42, None) is None

    def test_remember_replaces_previous_cache(self):
        remember_recent(chat_id=42, txn_ids=[101, 102])
        remember_recent(chat_id=42, txn_ids=[201])
        assert resolve_recent(42, "1") == 201
        assert resolve_recent(42, "2") is None


class TestClearRecent:
    def test_clear_drops_cache(self):
        remember_recent(chat_id=42, txn_ids=[101])
        clear_recent(42)
        assert resolve_recent(42, "1") is None

    def test_clear_is_idempotent(self):
        clear_recent(42)
        clear_recent(42)

    def test_clear_only_affects_target_chat(self):
        remember_recent(chat_id=42, txn_ids=[101])
        remember_recent(chat_id=99, txn_ids=[202])
        clear_recent(42)
        assert resolve_recent(42, "1") is None
        assert resolve_recent(99, "1") == 202


class TestChatIsolation:
    def test_different_chats_have_independent_indexes(self):
        remember_recent(chat_id=1, txn_ids=[555, 556])
        remember_recent(chat_id=2, txn_ids=[777])
        assert resolve_recent(1, "1") == 555
        assert resolve_recent(2, "1") == 777