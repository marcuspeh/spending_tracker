"""Tests for the config_store-backed TagsProvider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tags_provider import (
    FALLBACK_TAGS,
    TagsConfig,
    TagsProvider,
    _build_tags,
    _parse_csv_tags,
    get_tags_provider,
    init_tags_provider,
    reset_tags_provider,
)


class TestParseCsv:
    def test_basic_csv(self):
        assert _parse_csv_tags("food,transport,other") == (
            "food",
            "transport",
            "other",
        )

    def test_strips_whitespace_and_lowercases(self):
        assert _parse_csv_tags("  Food , Transport , OTHER ") == (
            "food",
            "transport",
            "other",
        )

    def test_drops_empty_tokens(self):
        # Trailing comma, empty fields from doubled separators.
        assert _parse_csv_tags("food,,transport,") == ("food", "transport")

    def test_empty_string_returns_none(self):
        assert _parse_csv_tags("") is None

    def test_only_whitespace_returns_none(self):
        assert _parse_csv_tags("   ,  ,  ") is None

    def test_duplicates_returns_none(self):
        assert _parse_csv_tags("food,transport,food") is None


class TestBuildTags:
    @pytest.mark.asyncio
    async def test_returns_parsed_tuple(self):
        cfg = TagsConfig("food,transport,other")
        result = await _build_tags(MagicMock(), cfg)
        assert result == ("food", "transport", "other")

    @pytest.mark.asyncio
    async def test_returns_fallback_on_invalid_payload(self):
        cfg = TagsConfig("")  # empty → invalid
        result = await _build_tags(MagicMock(), cfg)
        assert result == FALLBACK_TAGS

    @pytest.mark.asyncio
    async def test_returns_fallback_on_duplicates(self):
        cfg = TagsConfig("food,food")
        result = await _build_tags(MagicMock(), cfg)
        assert result == FALLBACK_TAGS

    @pytest.mark.asyncio
    async def test_mirrors_swap_into_singleton(self):
        from app.services import tags_provider

        provider = TagsProvider()
        provider._tags = FALLBACK_TAGS
        tags_provider._provider = provider

        try:
            cfg = TagsConfig("coffee,food")
            await _build_tags(MagicMock(), cfg)
            assert provider.current() == ("coffee", "food")
        finally:
            tags_provider._provider = None


class TestTagsProviderFallback:
    def test_current_returns_fallback_before_start(self):
        provider = TagsProvider()
        assert provider.current() == FALLBACK_TAGS


class TestTagsProviderStart:
    @pytest.mark.asyncio
    async def test_start_uses_fallback_when_initial_fetch_fails(self):
        settings = MagicMock(
            config_store_url="http://cfg.test:6002",
            config_store_project="expense_tracker",
            config_store_tags_key="tags",
            config_store_poll_seconds=60.0,
        )
        client = AsyncMock()
        client.get = AsyncMock(side_effect=Exception("boom"))

        with patch(
            "app.services.tags_provider.get_settings", return_value=settings
        ):
            with patch(
                "app.services.tags_provider.ConfigClient", return_value=client
            ):
                with patch(
                    "app.services.tags_provider.ClientWatcher"
                ) as watcher_cls:
                    watcher = MagicMock()
                    watcher_cls.return_value = watcher

                    provider = TagsProvider()
                    await provider.start()

        assert provider.current() == FALLBACK_TAGS
        watcher.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_uses_live_tags_when_initial_fetch_succeeds(self):
        settings = MagicMock(
            config_store_url="http://cfg.test:6002",
            config_store_project="expense_tracker",
            config_store_tags_key="tags",
            config_store_poll_seconds=60.0,
        )
        client = AsyncMock()
        client.get = AsyncMock(return_value="coffee,food,transport")

        with patch(
            "app.services.tags_provider.get_settings", return_value=settings
        ):
            with patch(
                "app.services.tags_provider.ConfigClient", return_value=client
            ):
                with patch(
                    "app.services.tags_provider.ClientWatcher"
                ) as watcher_cls:
                    watcher = MagicMock()
                    watcher_cls.return_value = watcher

                    provider = TagsProvider()
                    await provider.start()

        assert provider.current() == ("coffee", "food", "transport")
        watcher.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_falls_back_when_initial_payload_invalid(self):
        settings = MagicMock(
            config_store_url="http://cfg.test:6002",
            config_store_project="expense_tracker",
            config_store_tags_key="tags",
            config_store_poll_seconds=60.0,
        )
        client = AsyncMock()
        client.get = AsyncMock(return_value="")  # empty / invalid

        with patch(
            "app.services.tags_provider.get_settings", return_value=settings
        ):
            with patch(
                "app.services.tags_provider.ConfigClient", return_value=client
            ):
                with patch(
                    "app.services.tags_provider.ClientWatcher"
                ) as watcher_cls:
                    watcher = MagicMock()
                    watcher_cls.return_value = watcher

                    provider = TagsProvider()
                    await provider.start()

        assert provider.current() == FALLBACK_TAGS
        watcher.start.assert_called_once()


class TestTagsProviderStop:
    @pytest.mark.asyncio
    async def test_stop_closes_watcher_and_client(self):
        provider = TagsProvider()
        watcher = AsyncMock()
        client = AsyncMock()
        provider._watcher = watcher
        provider._client = client

        await provider.stop()

        watcher.aclose.assert_awaited_once()
        client.aclose.assert_awaited_once()
        assert provider._watcher is None
        assert provider._client is None

    @pytest.mark.asyncio
    async def test_stop_swallows_close_errors(self):
        provider = TagsProvider()
        watcher = AsyncMock()
        watcher.aclose.side_effect = RuntimeError("boom")
        client = AsyncMock()
        client.aclose.side_effect = RuntimeError("boom")
        provider._watcher = watcher
        provider._client = client

        # Must not raise — close failures are best-effort.
        await provider.stop()
        assert provider._watcher is None
        assert provider._client is None

    @pytest.mark.asyncio
    async def test_stop_is_safe_when_never_started(self):
        provider = TagsProvider()
        await provider.stop()  # noop, must not raise


class TestSingleton:
    def test_get_provider_raises_before_init(self):
        reset_tags_provider()
        with pytest.raises(RuntimeError, match="TagsProvider not initialized"):
            get_tags_provider()

    def test_init_then_get_returns_same_instance(self):
        reset_tags_provider()
        provider = init_tags_provider()
        assert get_tags_provider() is provider
        reset_tags_provider()

    def test_init_is_idempotent(self):
        reset_tags_provider()
        first = init_tags_provider()
        second = init_tags_provider()
        assert first is second
        reset_tags_provider()