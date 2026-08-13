"""Tests for the categorize_or_default fallback wrapper."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.categorizer import (
    DEFAULT_CATEGORIES,
    categorize,
    categorize_or_default,
)


@pytest.fixture
def settings():
    """Settings are required by the inner categorize() call."""
    from app.config.settings import Settings

    fake = Settings(
        llm_base_url="https://example.test/v1",
        llm_api_key="dummy-key",
        llm_model="test-model",
    )
    with patch("app.services.categorizer.get_settings", return_value=fake):
        yield fake


@pytest.fixture
def cache():
    """Stub the cache to miss every time so the inner LLM is called."""
    from app.services import categorizer as cat_module

    fake = MagicMock = _FakeCache()
    with patch.object(cat_module, "MerchantCategoryCacheRepository", return_value=fake):
        yield fake


from datetime import datetime


class _FakeCache:
    def __init__(self):
        self.upserts = []

    async def get(self, merchant_key):
        return None

    async def upsert(self, merchant_key, category):
        self.upserts.append((merchant_key, category))


@pytest.mark.asyncio
async def test_returns_llm_category_when_in_set(settings, cache):
    """Happy path: LLM returns a valid category → returned as-is."""
    with patch.object(
        categorizer_module := __import__(
            "app.services.categorizer", fromlist=["categorize"]
        ),
        "categorize",
        AsyncMock(return_value="food"),
    ):
        result = await categorize_or_default("STARBUCKS", default="other")
    assert result == "food"


@pytest.mark.asyncio
async def test_falls_back_to_default_when_llm_returns_none(settings, cache):
    with patch.object(
        __import__("app.services.categorizer", fromlist=["categorize"]),
        "categorize",
        AsyncMock(return_value=None),
    ):
        result = await categorize_or_default("MERCHANT", default="other")
    assert result == "other"


@pytest.mark.asyncio
async def test_propagates_exception_from_categorize(settings, cache):
    """Exceptions from ``categorize`` are NOT caught — they propagate so
    the caller (email ingestion / add_transaction) can decide what to do
    (currently they wrap the call in try/except)."""
    with patch.object(
        __import__("app.services.categorizer", fromlist=["categorize"]),
        "categorize",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await categorize_or_default("MERCHANT", default="other")


@pytest.mark.asyncio
async def test_does_not_cache_default_value(settings, cache):
    """The fallback must NOT be persisted to the cache — only genuine
    LLM answers get cached, so /edit can later overwrite the default."""
    with patch.object(
        __import__("app.services.categorizer", fromlist=["categorize"]),
        "categorize",
        AsyncMock(return_value=None),
    ):
        await categorize_or_default("MYSTERY", default="other")
    assert cache.upserts == []


@pytest.mark.asyncio
async def test_rejects_invalid_default(settings, cache):
    """If ``default`` is not in DEFAULT_CATEGORIES, return None."""
    with patch.object(
        __import__("app.services.categorizer", fromlist=["categorize"]),
        "categorize",
        AsyncMock(return_value=None),
    ):
        result = await categorize_or_default("MYSTERY", default="not_a_real_cat")
    assert result is None


def test_default_is_in_default_categories():
    """The shipped default ``"other"`` must be a valid category."""
    assert "other" in DEFAULT_CATEGORIES