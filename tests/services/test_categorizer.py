"""Tests for the LLM-backed tagger."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.categorizer import tag_for


def _mock_response(
    content: str,
    status_code: int = 200,
    *,
    raise_for_status: bool = False,
) -> httpx.Response:
    """Build a fake httpx.Response with the given JSON body."""
    import json

    body = json.dumps(
        {
            "choices": [{"message": {"content": content}}],
        }
    ).encode()
    request = httpx.Request("POST", "https://example.test")
    resp = httpx.Response(status_code, content=body, request=request)
    if raise_for_status:
        resp.status_code = 599
    return resp


class _MockClient:
    def __init__(self, response: httpx.Response | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.captured_payload: dict | None = None

    async def __aenter__(self):
        client = MagicMock()
        if self._error is not None:
            client.post = AsyncMock(side_effect=self._error)
        else:
            client.post = AsyncMock(side_effect=self._capture)
        return client

    async def _capture(self, url, headers=None, json=None, **kwargs):
        self.captured_payload = json
        return self._response

    async def __aexit__(self, *args):
        return None


class _MockCache:
    def __init__(self, *, hit: str | None = None, raise_on_upsert: bool = False):
        self._hit = hit
        self._raise_on_upsert = raise_on_upsert
        self.upserts: list[tuple[str, str]] = []
        self.get_calls: list[str] = []

    async def get(self, merchant_key: str) -> str | None:
        self.get_calls.append(merchant_key)
        return self._hit

    async def upsert(self, merchant_key: str, tag: str) -> None:
        if self._raise_on_upsert:
            raise RuntimeError("db down")
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
    from app.services import categorizer

    fake = _MockCache()
    with patch.object(
        categorizer, "MerchantTagCacheRepository", return_value=fake
    ):
        yield fake


class TestTagFor:
    @pytest.mark.asyncio
    async def test_returns_tag_when_in_set(self, settings, cache):
        resp = _mock_response("food")
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient(resp)):
            assert await tag_for("STARBUCKS") == "food"

    @pytest.mark.asyncio
    async def test_lowercases_and_strips_punctuation(self, settings, cache):
        resp = _mock_response("  Transport.\n")
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient(resp)):
            assert await tag_for("GRAB") == "transport"

    @pytest.mark.asyncio
    async def test_out_of_set_returns_none(self, settings, cache):
        resp = _mock_response("alien-thing")
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient(resp)):
            assert await tag_for("MYSTERY") is None

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self, settings, cache):
        with patch(
            "app.services.categorizer.httpx.AsyncClient",
            return_value=_MockClient(error=httpx.ConnectError("boom")),
        ):
            assert await tag_for("STARBUCKS") is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, settings, cache):
        with patch(
            "app.services.categorizer.httpx.AsyncClient",
            return_value=_MockClient(error=httpx.TimeoutException("slow")),
        ):
            assert await tag_for("GRAB") is None

    @pytest.mark.asyncio
    async def test_bad_json_returns_none(self, settings, cache):
        request = httpx.Request("POST", "https://example.test")
        resp = httpx.Response(200, content=b'{"bogus": true}', request=request)
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient(resp)):
            assert await tag_for("GRAB") is None

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self, cache):
        from app.config.settings import Settings

        fake = Settings(llm_api_key="")
        with patch("app.services.categorizer.get_settings", return_value=fake):
            assert await tag_for("STARBUCKS") is None


class TestCache:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_llm(self, settings):
        from app.services import categorizer

        cache = _MockCache(hit="food")
        with patch.object(
            categorizer, "MerchantTagCacheRepository", return_value=cache
        ):
            mock_client = _MockClient(_mock_response("transport"))
            with patch(
                "app.services.categorizer.httpx.AsyncClient",
                return_value=mock_client,
            ):
                result = await tag_for("STARBUCKS")

        assert result == "food"
        assert mock_client.captured_payload is None, "LLM should not be called on cache hit"
        assert cache.upserts == [], "no upsert on a hit"

    @pytest.mark.asyncio
    async def test_cache_miss_calls_llm_and_upserts(self, settings):
        from app.services import categorizer

        cache = _MockCache()
        with patch.object(
            categorizer, "MerchantTagCacheRepository", return_value=cache
        ):
            with patch(
                "app.services.categorizer.httpx.AsyncClient",
                return_value=_MockClient(_mock_response("shopping")),
            ):
                result = await tag_for("CHOCFIN")

        assert result == "shopping"
        assert cache.upserts == [("chocfin", "shopping")]

    @pytest.mark.asyncio
    async def test_cache_key_is_normalized(self, settings):
        from app.services import categorizer

        cache = _MockCache()
        with patch.object(
            categorizer, "MerchantTagCacheRepository", return_value=cache
        ):
            with patch(
                "app.services.categorizer.httpx.AsyncClient",
                return_value=_MockClient(_mock_response("food")),
            ):
                await tag_for("  Starbucks  ")

        assert cache.get_calls == ["starbucks"]
        assert cache.upserts == [("starbucks", "food")]

    @pytest.mark.asyncio
    async def test_cache_upsert_skipped_on_out_of_set(self, settings):
        from app.services import categorizer

        cache = _MockCache()
        with patch.object(
            categorizer, "MerchantTagCacheRepository", return_value=cache
        ):
            with patch(
                "app.services.categorizer.httpx.AsyncClient",
                return_value=_MockClient(_mock_response("alien-thing")),
            ):
                result = await tag_for("MYSTERY")

        assert result is None
        assert cache.upserts == []

    @pytest.mark.asyncio
    async def test_cache_upsert_failure_does_not_break_caller(self, settings):
        from app.services import categorizer

        cache = _MockCache(raise_on_upsert=True)
        with patch.object(
            categorizer, "MerchantTagCacheRepository", return_value=cache
        ):
            with patch(
                "app.services.categorizer.httpx.AsyncClient",
                return_value=_MockClient(_mock_response("shopping")),
            ):
                result = await tag_for("CHOCFIN")

        assert result == "shopping"

    @pytest.mark.asyncio
    async def test_empty_merchant_returns_none_no_cache_call(self, settings):
        from app.services import categorizer

        cache = _MockCache()
        with patch.object(
            categorizer, "MerchantTagCacheRepository", return_value=cache
        ):
            result = await tag_for("")

        assert result is None
        assert cache.get_calls == []


class TestPayload:
    @pytest.mark.asyncio
    async def test_payload_shape(self, settings, cache):
        mock_client = _MockClient(_mock_response("food"))
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
            await tag_for("STARBUCKS")

        payload = mock_client.captured_payload
        assert payload is not None, "tagger did not call the LLM"
        assert payload["model"] == "test-model"
        assert payload["max_tokens"] == 16
        assert payload["temperature"] == 0.0
        assert payload["thinking"] == {"type": "disabled"}
        assert "reasoning" not in payload

        msgs = payload["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert "food" in msgs[0]["content"]
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "STARBUCKS"

    @pytest.mark.asyncio
    async def test_payload_uses_settings(self, settings, cache):
        mock_client = _MockClient(_mock_response("shopping"))
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
            await tag_for("CHOCFIN")

        assert mock_client.captured_payload["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_payload_omits_excluded_tags(self, settings, cache):
        """Tags the operator excluded from the LLM must not appear in
        the system prompt sent to the model.
        """
        from app.services.tags_provider import TagsProvider, reset_tags_provider

        provider = TagsProvider()
        provider._tags = ("food", "coffee", "transport", "other")
        provider._excluded = ("coffee", "transport")
        try:
            from app.services import tags_provider as tp_module

            tp_module._provider = provider

            mock_client = _MockClient(_mock_response("food"))
            with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
                await tag_for("STARBUCKS")

            payload = mock_client.captured_payload
            assert payload is not None
            system = payload["messages"][0]["content"]
            # Excluded tags must not be offered to the LLM.
            assert "coffee" not in system
            assert "transport" not in system
            # Non-excluded tags must still be listed.
            assert "food" in system
            assert "other" in system
        finally:
            reset_tags_provider()

    @pytest.mark.asyncio
    async def test_excluded_tag_from_llm_is_still_accepted(self, settings, cache):
        """If the model emits an excluded-but-valid tag (e.g. it knew
        about it before the operator excluded it), we should still
        accept and cache the response — the exclusion is prompt-only.
        """
        from app.services.tags_provider import TagsProvider, reset_tags_provider

        provider = TagsProvider()
        provider._tags = ("food", "coffee", "other")
        provider._excluded = ("coffee",)  # hidden from the prompt
        try:
            from app.services import tags_provider as tp_module

            tp_module._provider = provider

            mock_client = _MockClient(_mock_response("coffee"))
            with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
                result = await tag_for("BLUE_BOTTLE")
            assert result == "coffee"
            # Cache write still happened — operator-excluded tags are
            # just prompt-side filtering, not validation.
            assert ("blue_bottle", "coffee") in cache.upserts
        finally:
            reset_tags_provider()