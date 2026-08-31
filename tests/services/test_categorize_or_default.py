"""Tests for the tag_for / tag_for_or_default wrappers."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.categorizer import (
    DEFAULT_FALLBACK_TAG,
    DEFAULT_TAGS,
    current_tags,
    tag_for_or_default,
)
from app.services.tags_provider import (
    FALLBACK_TAGS,
    TagsProvider,
    reset_tags_provider,
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


class TestCurrentTagsIntegration:
    def test_current_tags_falls_back_when_provider_uninitialized(self):
        reset_tags_provider()
        assert current_tags() == FALLBACK_TAGS

    def test_current_tags_returns_live_value_when_provider_initialized(self):
        reset_tags_provider()
        provider = TagsProvider()
        provider._tags = ("coffee", "transport", "other")
        try:
            from app.services import tags_provider

            tags_provider._provider = provider
            assert current_tags() == ("coffee", "transport", "other")
        finally:
            reset_tags_provider()


class TestTagForOrDefaultUsesLiveSet:
    @pytest.mark.asyncio
    async def test_accepts_tag_only_when_in_live_set(self, settings, cache):
        reset_tags_provider()
        provider = TagsProvider()
        # Live set excludes "food".
        provider._tags = ("transport", "other")
        try:
            from app.services import tags_provider

            tags_provider._provider = provider
            with patch.object(
                __import__("app.services.categorizer", fromlist=["tag_for"]),
                "tag_for",
                AsyncMock(return_value=None),
            ):
                # "food" is in the legacy DEFAULT_TAGS but not in the
                # live set — must be rejected.
                result = await tag_for_or_default("MYSTERY", default="food")
            assert result is None
        finally:
            reset_tags_provider()

    @pytest.mark.asyncio
    async def test_accepts_tag_from_live_set(self, settings, cache):
        reset_tags_provider()
        provider = TagsProvider()
        # "live" only exists in the live set, not the fallback.
        provider._tags = ("live", "other")
        try:
            from app.services import tags_provider

            tags_provider._provider = provider
            with patch.object(
                __import__("app.services.categorizer", fromlist=["tag_for"]),
                "tag_for",
                AsyncMock(return_value=None),
            ):
                result = await tag_for_or_default("MYSTERY", default="live")
            assert result == "live"
        finally:
            reset_tags_provider()