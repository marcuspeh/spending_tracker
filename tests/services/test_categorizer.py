"""Tests for the LLM-backed categorizer."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.categorizer import categorize


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
        # Force an error
        resp.status_code = 599
    return resp


class _MockClient:
    """Async context manager that returns a stub client whose ``post``
    returns the supplied response."""

    def __init__(self, response: httpx.Response | None = None, error: Exception | None = None):
        self._response = response
        self._error = error

    async def __aenter__(self):
        client = MagicMock()
        if self._error is not None:
            client.post = AsyncMock(side_effect=self._error)
        else:
            client.post = AsyncMock(return_value=self._response)
        return client

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def settings():
    """Patch settings so LLM_BASE_URL / LLM_API_KEY / LLM_MODEL are set."""
    from app.config.settings import Settings

    fake = Settings(
        llm_base_url="https://example.test/v1",
        llm_api_key="dummy-key",
        llm_model="test-model",
    )
    with patch("app.services.categorizer.get_settings", return_value=fake):
        yield fake


class TestCategorize:
    @pytest.mark.asyncio
    async def test_returns_category_when_in_set(self, settings):
        resp = _mock_response("food")
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient(resp)):
            assert await categorize("STARBUCKS") == "food"

    @pytest.mark.asyncio
    async def test_lowercases_and_strips_punctuation(self, settings):
        resp = _mock_response("  Transport.\n")
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient(resp)):
            assert await categorize("GRAB") == "transport"

    @pytest.mark.asyncio
    async def test_out_of_set_returns_none(self, settings):
        resp = _mock_response("alien-thing")
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient(resp)):
            assert await categorize("MYSTERY") is None

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self, settings):
        with patch(
            "app.services.categorizer.httpx.AsyncClient",
            return_value=_MockClient(error=httpx.ConnectError("boom")),
        ):
            assert await categorize("STARBUCKS") is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, settings):
        with patch(
            "app.services.categorizer.httpx.AsyncClient",
            return_value=_MockClient(error=httpx.TimeoutException("slow")),
        ):
            assert await categorize("GRAB") is None

    @pytest.mark.asyncio
    async def test_bad_json_returns_none(self, settings):
        # Build a response whose body is valid JSON but missing keys.
        import json

        request = httpx.Request("POST", "https://example.test")
        resp = httpx.Response(200, content=b'{"bogus": true}', request=request)
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient(resp)):
            assert await categorize("GRAB") is None

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        from app.config.settings import Settings

        fake = Settings(llm_api_key="")
        with patch("app.services.categorizer.get_settings", return_value=fake):
            # Should not raise and should not call the network.
            assert await categorize("STARBUCKS") is None