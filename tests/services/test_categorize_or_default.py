"""Tests for the tag_for / tag_for_or_default wrappers."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.categorizer import (
    DEFAULT_FALLBACK_TAG,
    DEFAULT_TAGS,
    tag_for,
    tag_for_or_default,
)


class _FakeCache:
    def __init__(self):
        self.upserts = []

    async def get(self, merchant_key):
        return None

    async def upsert(self, merchant_key, tag):
        self.upserts.append((merchant_key, tag))


@pytest.fixture
def settings():
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
    from app.services import categorizer as cat_module

    fake = _FakeCache()
    with patch.object(cat_module, "MerchantTagCacheRepository", return_value=fake):
        yield fake


@pytest.mark.asyncio
async def test_returns_tag_when_in_set(settings, cache):
    with patch.object(
        __import__("app.services.categorizer", fromlist=["tag_for"]),
        "tag_for",
        AsyncMock(return_value="food"),
    ):
        result = await tag_for_or_default("STARBUCKS")
    assert result == "food"


@pytest.mark.asyncio
async def test_falls_back_to_default_when_llm_returns_none(settings, cache):
    with patch.object(
        __import__("app.services.categorizer", fromlist=["tag_for"]),
        "tag_for",
        AsyncMock(return_value=None),
    ):
        result = await tag_for_or_default("MERCHANT")
    assert result == DEFAULT_FALLBACK_TAG
    assert result == "other"


@pytest.mark.asyncio
async def test_propagates_exception_from_tag_for(settings, cache):
    with patch.object(
        __import__("app.services.categorizer", fromlist=["tag_for"]),
        "tag_for",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await tag_for_or_default("MERCHANT")


@pytest.mark.asyncio
async def test_does_not_cache_default_value(settings, cache):
    with patch.object(
        __import__("app.services.categorizer", fromlist=["tag_for"]),
        "tag_for",
        AsyncMock(return_value=None),
    ):
        await tag_for_or_default("MYSTERY")
    assert cache.upserts == []


@pytest.mark.asyncio
async def test_rejects_invalid_default(settings, cache):
    with patch.object(
        __import__("app.services.categorizer", fromlist=["tag_for"]),
        "tag_for",
        AsyncMock(return_value=None),
    ):
        result = await tag_for_or_default("MYSTERY", default="not_a_real_tag")
    assert result is None


def test_default_is_in_default_tags():
    assert "other" in DEFAULT_TAGS


def test_default_fallback_constant_is_other():
    assert DEFAULT_FALLBACK_TAG == "other"