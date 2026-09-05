"""Tests for the config_store-backed TagsProvider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tags_provider import (
    EMPTY_EXCLUDED,
    FALLBACK_TAGS,
    ExcludedTagsConfig,
    TagsConfig,
    TagsProvider,
    _build_excluded,
    _build_tags,
    _parse_csv_tags,
    get_tags_provider,
    init_tags_provider,
    llm_tags,
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


class TestBuildExcluded:
    @pytest.mark.asyncio
    async def test_returns_parsed_tuple(self):
        cfg = ExcludedTagsConfig("gym,health")
        result = await _build_excluded(MagicMock(), cfg)
        assert result == ("gym", "health")

    @pytest.mark.asyncio
    async def test_returns_empty_on_invalid_payload(self):
        cfg = ExcludedTagsConfig("")  # empty → invalid
        result = await _build_excluded(MagicMock(), cfg)
        assert result == EMPTY_EXCLUDED

    @pytest.mark.asyncio
    async def test_returns_empty_on_duplicates(self):
        cfg = ExcludedTagsConfig("gym,gym")
        result = await _build_excluded(MagicMock(), cfg)
        assert result == EMPTY_EXCLUDED

    @pytest.mark.asyncio
    async def test_mirrors_swap_into_singleton(self):
        from app.services import tags_provider

        provider = TagsProvider()
        provider._tags = FALLBACK_TAGS
        provider._excluded = EMPTY_EXCLUDED
        tags_provider._provider = provider

        try:
            cfg = ExcludedTagsConfig("gym,health")
            await _build_excluded(MagicMock(), cfg)
            assert provider.excluded() == ("gym", "health")
        finally:
            tags_provider._provider = None


class TestTagsProviderFallback:
    def test_current_returns_fallback_before_start(self):
        provider = TagsProvider()
        assert provider.current() == FALLBACK_TAGS

    def test_excluded_is_empty_before_start(self):
        provider = TagsProvider()
        assert provider.excluded() == EMPTY_EXCLUDED

    def test_llm_tags_falls_back_to_current_before_start(self):
        provider = TagsProvider()
        assert provider.llm_tags() == FALLBACK_TAGS


class TestLlmTagsSubtraction:
    def test_llm_tags_subtracts_excluded_from_current(self):
        provider = TagsProvider()
        provider._tags = ("food", "coffee", "transport", "other")
        provider._excluded = ("coffee",)
        # Order preserved; only "coffee" is gone.
        assert provider.llm_tags() == ("food", "transport", "other")

    def test_llm_tags_drops_excluded_not_in_current(self):
        # Stale config_store row that points at a tag that no longer
        # exists in the allowed set — must not raise, must not appear.
        provider = TagsProvider()
        provider._tags = ("food", "transport", "other")
        provider._excluded = ("ghost-tag",)
        assert provider.llm_tags() == ("food", "transport", "other")

    def test_llm_tags_keeps_last_current_when_all_excluded(self):
        # Admin excluded every tag by mistake — keep the last one so
        # the model still has somewhere to answer.
        provider = TagsProvider()
        provider._tags = ("food", "transport")
        provider._excluded = ("food", "transport")
        assert provider.llm_tags() == ("transport",)


class TestLlmTagsHelper:
    def test_module_helper_returns_fallback_when_uninitialized(self):
        reset_tags_provider()
        assert llm_tags() == FALLBACK_TAGS

    def test_module_helper_returns_live_llm_set(self):
        reset_tags_provider()
        provider = TagsProvider()
        provider._tags = ("a", "b", "c")
        provider._excluded = ("b",)
        try:
            from app.services import tags_provider

            tags_provider._provider = provider
            assert llm_tags() == ("a", "c")
        finally:
            reset_tags_provider()


class TestTagsProviderStart:
    @pytest.mark.asyncio
    async def test_start_uses_fallback_when_initial_fetch_fails(self):
        settings = MagicMock(
            config_store_url="http://cfg.test:6002",
            config_store_project="expense_tracker",
            config_store_tags_key="tags",
            config_store_tags_excluded_key="tags_excluded_from_llm",
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
        assert provider.excluded() == EMPTY_EXCLUDED
        # Two watchers started: one for the allowed list, one for the
        # excluded list.
        assert watcher.start.call_count == 2

    @pytest.mark.asyncio
    async def test_start_uses_live_tags_and_excluded(self):
        settings = MagicMock(
            config_store_url="http://cfg.test:6002",
            config_store_project="expense_tracker",
            config_store_tags_key="tags",
            config_store_tags_excluded_key="tags_excluded_from_llm",
            config_store_poll_seconds=60.0,
        )

        async def fake_get(key: str) -> str:
            if key == "tags":
                return "coffee,food,transport"
            if key == "tags_excluded_from_llm":
                return "food"
            raise AssertionError(f"unexpected key {key!r}")

        client = AsyncMock()
        client.get = AsyncMock(side_effect=fake_get)

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
        assert provider.excluded() == ("food",)
        assert provider.llm_tags() == ("coffee", "transport")
        assert watcher.start.call_count == 2

    @pytest.mark.asyncio
    async def test_start_falls_back_when_initial_payload_invalid(self):
        settings = MagicMock(
            config_store_url="http://cfg.test:6002",
            config_store_project="expense_tracker",
            config_store_tags_key="tags",
            config_store_tags_excluded_key="tags_excluded_from_llm",
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
        # An invalid excluded payload reduces to empty (not FALLBACK_TAGS).
        assert provider.excluded() == EMPTY_EXCLUDED
        assert watcher.start.call_count == 2

    @pytest.mark.asyncio
    async def test_start_tolerates_excluded_fetch_failure(self):
        # Allowed list fetched successfully; excluded fetch throws.
        # The provider must still start.
        settings = MagicMock(
            config_store_url="http://cfg.test:6002",
            config_store_project="expense_tracker",
            config_store_tags_key="tags",
            config_store_tags_excluded_key="tags_excluded_from_llm",
            config_store_poll_seconds=60.0,
        )

        async def fake_get(key: str) -> str:
            if key == "tags":
                return "coffee,food"
            raise Exception("excluded endpoint down")

        client = AsyncMock()
        client.get = AsyncMock(side_effect=fake_get)

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

        assert provider.current() == ("coffee", "food")
        assert provider.excluded() == EMPTY_EXCLUDED
        assert provider.llm_tags() == ("coffee", "food")


class TestTagsProviderStop:
    @pytest.mark.asyncio
    async def test_stop_closes_both_watchers_and_client(self):
        provider = TagsProvider()
        tags_watcher = AsyncMock()
        excluded_watcher = AsyncMock()
        client = AsyncMock()
        provider._tags_watcher = tags_watcher
        provider._excluded_watcher = excluded_watcher
        provider._client = client

        await provider.stop()

        tags_watcher.aclose.assert_awaited_once()
        excluded_watcher.aclose.assert_awaited_once()
        client.aclose.assert_awaited_once()
        assert provider._tags_watcher is None
        assert provider._excluded_watcher is None
        assert provider._client is None

    @pytest.mark.asyncio
    async def test_stop_swallows_close_errors(self):
        provider = TagsProvider()
        tags_watcher = AsyncMock()
        tags_watcher.aclose.side_effect = RuntimeError("boom")
        excluded_watcher = AsyncMock()
        excluded_watcher.aclose.side_effect = RuntimeError("boom")
        client = AsyncMock()
        client.aclose.side_effect = RuntimeError("boom")
        provider._tags_watcher = tags_watcher
        provider._excluded_watcher = excluded_watcher
        provider._client = client

        # Must not raise — close failures are best-effort.
        await provider.stop()
        assert provider._tags_watcher is None
        assert provider._excluded_watcher is None
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