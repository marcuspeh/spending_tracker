"""Tests for the curl_website tool."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.tools import curl_website
from app.services.tools import execute as execute_tool


def _httpx_response(status: int, body: bytes) -> httpx.Response:
    """Build a real httpx.Response — needed so ``.raise_for_status``,
    ``.content`` and ``.encoding`` behave the way ``CurlWebsiteTool.run``
    expects.
    """
    request = httpx.Request("GET", "https://example.test")
    return httpx.Response(status, content=body, request=request)


class TestCurlWebsiteTool:
    @pytest.fixture
    def tool(self):
        # Construct a fresh instance per test so we never depend on
        # global registration state.
        return curl_website.CurlWebsiteTool()

    def test_spec_shape(self, tool):
        spec = tool.spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "curl_website"
        params = spec["function"]["parameters"]
        assert params["required"] == ["url"]
        assert params["properties"]["url"]["type"] == "string"
        assert params["additionalProperties"] is False

    def test_name_matches_spec(self, tool):
        # Guarded at registration time too, but a sanity check is cheap.
        assert tool.spec()["function"]["name"] == tool.name

    @pytest.mark.asyncio
    async def test_returns_text_body(self, tool):
        html = b"<html><body>Hello</body></html>"
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(return_value=_httpx_response(200, html))
        with patch.object(curl_website.httpx, "AsyncClient", return_value=client):
            result = await tool.run(json.dumps({"url": "https://x.example/"}))
        assert result["status"] == 200
        assert "Hello" in result["content"]
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_truncates_huge_responses(self, tool):
        big = b"x" * (curl_website.MAX_BYTES * 2)
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(return_value=_httpx_response(200, big))
        with patch.object(curl_website.httpx, "AsyncClient", return_value=client):
            result = await tool.run(json.dumps({"url": "https://huge.example/"}))
        assert result["truncated"] is True
        assert len(result["content"]) <= curl_website.MAX_BYTES

    @pytest.mark.asyncio
    async def test_rejects_non_http_scheme(self, tool):
        # No HTTP call should happen — the guard fails before fetching.
        result = await tool.run(json.dumps({"url": "file:///etc/passwd"}))
        assert "http(s)" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_missing_url(self, tool):
        result = await tool.run(json.dumps({}))
        assert "url" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_empty_arguments(self, tool):
        # The model sometimes emits an empty arguments string.
        result = await tool.run("")
        assert "url" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_malformed_json(self, tool):
        result = await tool.run("not-json")
        assert "invalid" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_non_object_arguments(self, tool):
        result = await tool.run(json.dumps(["not", "an", "object"]))
        assert "object" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_non_string_url(self, tool):
        result = await tool.run(json.dumps({"url": 123}))
        assert "url" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_error_envelope(self, tool):
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(side_effect=httpx.ConnectError("dns down"))
        with patch.object(curl_website.httpx, "AsyncClient", return_value=client):
            result = await tool.run(json.dumps({"url": "https://broken/"}))
        assert "fetch failed" in result["error"]
        assert result["url"] == "https://broken/"

    @pytest.mark.asyncio
    async def test_http_status_error_returns_error_envelope(self, tool):
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(return_value=_httpx_response(500, b"oops"))
        with patch.object(curl_website.httpx, "AsyncClient", return_value=client):
            result = await tool.run(json.dumps({"url": "https://x/"}))
        assert "fetch failed" in result["error"]

    def test_spec_tells_model_to_skip_when_no_domain(self, tool):
        """The tool description must hint that the call is optional —
        merchants without a homepage (cash, local stalls, apps) should
        not be looked up at all. The model needs this to avoid burning
        tool-call turns on a doomed URL.
        """
        spec = tool.spec()
        description = spec["function"]["description"].lower()
        url_description = spec["function"]["parameters"]["properties"]["url"]["description"].lower()
        assert "skip" in description or "optional" in description
        assert "don't call" in url_description or "don\u2019t call" in url_description or "no domain" in url_description


class TestRegistryDispatch:
    @pytest.mark.asyncio
    async def test_execute_dispatches_to_registered_tool(self):
        result = json.loads(
            await execute_tool("curl_website", json.dumps({"url": "https://x/"}))
        )
        # We can't predict whether the URL resolves from the test
        # machine; just check the envelope shape (status OR error
        # key, both prove dispatch worked).
        assert "status" in result or "error" in result

    @pytest.mark.asyncio
    async def test_execute_returns_error_for_unknown_tool(self):
        result = json.loads(await execute_tool("rm_rf", "{}"))
        assert "unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_catches_unhandled_tool_exceptions(self):
        from app.services.tools import base as base_mod
        from app.services.tools.base import Tool, ToolRegistry

        class Boom(Tool):
            name = "boom"

            def spec(self):
                return {
                    "type": "function",
                    "function": {"name": "boom", "description": "", "parameters": {}},
                }

            async def run(self, arguments):
                raise RuntimeError("intentional")

        reg = ToolRegistry()
        reg.register(Boom())

        with patch.object(base_mod, "default_registry", return_value=reg):
            result = json.loads(await base_mod.execute("boom", "{}"))

        assert "crashed" in result["error"]
        assert "intentional" in result["error"]

    def test_register_rejects_name_mismatch(self):
        from app.services.tools.base import Tool, ToolRegistry

        class WrongName(Tool):
            name = "alpha"

            def spec(self):
                return {
                    "type": "function",
                    "function": {"name": "beta", "description": "", "parameters": {}},
                }

            async def run(self, arguments):
                return {}

        with pytest.raises(ValueError, match="does not match"):
            ToolRegistry().register(WrongName())