"""Tests for the LLM-backed tagger."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.categorizer import MAX_ITERATIONS, tag_for


def _mock_response(
    content: str,
    status_code: int = 200,
    *,
    raise_for_status: bool = False,
    tool_calls: list[dict] | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response with the given JSON body.

    ``tool_calls`` lets the response simulate a tool-call turn. When
    non-empty the assistant ``content`` is empty and the model's reply
    is a list of tool invocations, matching OpenAI's wire format.
    """
    message: dict = {"role": "assistant"}
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = None
    else:
        message["content"] = content

    body = json.dumps(
        {
            "choices": [{"message": message}],
        }
    ).encode()
    request = httpx.Request("POST", "https://example.test")
    resp = httpx.Response(status_code, content=body, request=request)
    if raise_for_status:
        resp.status_code = 599
    return resp


class _MockClient:
    def __init__(
        self,
        responses: list[httpx.Response] | None = None,
        error: Exception | None = None,
    ):
        """Build a mock httpx client.

        ``responses`` is a queue of canned replies (one per chat-
        completion POST). Passing a single-element list works the same
        as the old behaviour. When the queue is exhausted the last
        response is replayed so tests that don't care about ordering
        don't need to think about it.
        """
        if responses is None:
            self._responses: list[httpx.Response] = []
        else:
            self._responses = list(responses)
        self._error = error
        self.captured_payloads: list[dict] = []
        self.calls = 0

    async def __aenter__(self):
        client = MagicMock()
        if self._error is not None:
            client.post = AsyncMock(side_effect=self._error)
        else:
            client.post = AsyncMock(side_effect=self._capture)
        return client

    async def _capture(self, url, headers=None, json=None, **kwargs):
        self.captured_payloads.append(json)
        self.calls += 1
        if not self._responses:
            raise AssertionError("no more canned responses queued")
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)

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


def _curl_call(call_id: str, url: str) -> dict:
    """Build a tool_call dict matching OpenAI's wire format."""
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "curl_website",
            "arguments": json.dumps({"url": url}),
        },
    }


class TestTagFor:
    @pytest.mark.asyncio
    async def test_returns_tag_when_in_set(self, settings, cache):
        resp = _mock_response("food")
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient([resp])):
            assert await tag_for("STARBUCKS") == "food"

    @pytest.mark.asyncio
    async def test_lowercases_and_strips_punctuation(self, settings, cache):
        resp = _mock_response("  Transport.\n")
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient([resp])):
            assert await tag_for("GRAB") == "transport"

    @pytest.mark.asyncio
    async def test_out_of_set_returns_none(self, settings, cache):
        resp = _mock_response("alien-thing")
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient([resp])):
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
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=_MockClient([resp])):
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
            mock_client = _MockClient([_mock_response("transport")])
            with patch(
                "app.services.categorizer.httpx.AsyncClient",
                return_value=mock_client,
            ):
                result = await tag_for("STARBUCKS")

        assert result == "food"
        assert mock_client.captured_payloads == [], "LLM should not be called on cache hit"
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
                return_value=_MockClient([_mock_response("shopping")]),
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
                return_value=_MockClient([_mock_response("food")]),
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
                return_value=_MockClient([_mock_response("alien-thing")]),
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
                return_value=_MockClient([_mock_response("shopping")]),
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
        mock_client = _MockClient([_mock_response("food")])
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
            await tag_for("STARBUCKS")

        payload = mock_client.captured_payloads[0]
        assert payload is not None, "tagger did not call the LLM"
        assert payload["model"] == "test-model"
        # 256 leaves room for the model's <think>...</think> block plus
        # a single-token tag answer (see app.services.categorizer).
        assert payload["max_tokens"] == 256
        assert payload["temperature"] == 0.0
        assert payload["thinking"] == {"type": "disabled"}
        assert "reasoning" not in payload

        # Tools payload: comes from app.services.tools.specs — must
        # include curl_website by default.
        tools = payload["tools"]
        assert isinstance(tools, list) and len(tools) >= 1
        names = {t["function"]["name"] for t in tools}
        assert "curl_website" in names

        msgs = payload["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert "food" in msgs[0]["content"]
        # System prompt mentions the iteration cap so the model knows
        # when to stop calling the tool.
        assert str(MAX_ITERATIONS) in msgs[0]["content"]
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "STARBUCKS"

    @pytest.mark.asyncio
    async def test_payload_uses_settings(self, settings, cache):
        mock_client = _MockClient([_mock_response("shopping")])
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
            await tag_for("CHOCFIN")

        assert mock_client.captured_payloads[0]["model"] == "test-model"

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

            mock_client = _MockClient([_mock_response("food")])
            with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
                await tag_for("STARBUCKS")

            payload = mock_client.captured_payloads[0]
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

            mock_client = _MockClient([_mock_response("coffee")])
            with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
                result = await tag_for("BLUE_BOTTLE")
            assert result == "coffee"
            # Cache write still happened — operator-excluded tags are
            # just prompt-side filtering, not validation.
            assert ("blue_bottle", "coffee") in cache.upserts
        finally:
            reset_tags_provider()


class TestToolCallingIntegration:
    """End-to-end tests for the tool-calling loop in categorizer.tag_for.

    curl_website's own behaviour (HTTP fetch, scheme guard, truncation)
    is covered in tests/services/tools/test_curl_website.py — these
    tests focus on how the agent loop wires tools into the conversation.
    """

    @pytest.mark.asyncio
    async def test_executes_curl_then_answers_with_tag(self, settings, cache):
        """First turn: model asks to curl amazon.com. Second turn:
        model answers 'shopping'. The tool response must be sent back
        and the final tag must be cached.
        """
        from app.services import categorizer as cat_module

        call_resp = _mock_response(
            "", tool_calls=[_curl_call("call_1", "https://amazon.com")]
        )
        answer_resp = _mock_response("shopping")
        mock_client = _MockClient([call_resp, answer_resp])

        envelope = json.dumps(
            {
                "url": "https://amazon.com",
                "status": 200,
                "content": "<html><body>Amazon sells everything</body></html>",
                "truncated": False,
            }
        )
        # Stub the registry's execute so we don't actually fetch.
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
            with patch.object(cat_module, "execute_tool", AsyncMock(return_value=envelope)):
                result = await tag_for("AMZN")

        assert result == "shopping"
        assert cache.upserts == [("amzn", "shopping")]
        # Two chat-completion POSTs happened — one tool-call turn and
        # one final-answer turn.
        assert mock_client.calls == 2

        # Second request must include the tool-call message + tool
        # result, in that order.
        second = mock_client.captured_payloads[1]["messages"]
        roles = [m["role"] for m in second]
        assert roles == ["system", "user", "assistant", "tool"]
        assert second[2].get("tool_calls"), "assistant turn must carry the tool call"
        assert second[3]["role"] == "tool"
        assert second[3]["tool_call_id"] == "call_1"
        # Tool result is the JSON envelope our stub returned.
        parsed = json.loads(second[3]["content"])
        assert parsed["status"] == 200
        assert "Amazon" in parsed["content"]

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_envelope(self, settings, cache):
        """A model asking for a tool we didn't register should get a
        JSON error back so the next turn can recover.
        """
        call_resp = _mock_response(
            "",
            tool_calls=[
                {
                    "id": "call_evil",
                    "type": "function",
                    "function": {"name": "rm_rf", "arguments": "{}"},
                }
            ],
        )
        answer_resp = _mock_response("food")
        mock_client = _MockClient([call_resp, answer_resp])
        # Re-use the real execute_tool — the unknown-name branch must
        # produce an error envelope, not raise.
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
            result = await tag_for("STARBUCKS")
        assert result == "food"

        tool_msg = mock_client.captured_payloads[1]["messages"][3]
        envelope = json.loads(tool_msg["content"])
        assert "unknown tool" in envelope["error"]

    @pytest.mark.asyncio
    async def test_curl_failure_then_tag_succeeds(self, settings, cache):
        """Realistic 'no website' path: the model tries to curl a
        merchant, the fetch fails, the model picks a tag anyway instead
        of burning more iterations retrying.
        """
        from app.services import categorizer as cat_module

        call_resp = _mock_response(
            "", tool_calls=[_curl_call("call_x", "https://nosuch.example/")]
        )
        answer_resp = _mock_response("cash")
        mock_client = _MockClient([call_resp, answer_resp])
        failed_envelope = json.dumps(
            {"error": "fetch failed: [Errno -2] Name does not exist", "url": "https://nosuch.example/"}
        )
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
            with patch.object(cat_module, "execute_tool", AsyncMock(return_value=failed_envelope)):
                result = await tag_for("UNIDENTIFIED_CASH_MERCHANT")

        assert result == "cash"
        assert cache.upserts == [("unidentified_cash_merchant", "cash")]
        # Two chat-completion POSTs — one curl, one final tag. The model
        # did NOT retry the curl.
        assert mock_client.calls == 2

    @pytest.mark.asyncio
    async def test_multiple_curls_then_tag_succeeds(self, settings, cache):
        """The system prompt permits multiple tool calls across turns —
        the model can follow links / fetch additional pages before
        answering. This test simulates two curls followed by a final
        tag.
        """
        from app.services import categorizer as cat_module

        call_1 = _mock_response(
            "", tool_calls=[_curl_call("call_1", "https://merchant.example/")]
        )
        call_2 = _mock_response(
            "",
            tool_calls=[_curl_call("call_2", "https://merchant.example/about")],
        )
        answer = _mock_response("food")
        mock_client = _MockClient([call_1, call_2, answer])

        pages = iter(
            [
                json.dumps(
                    {
                        "url": "https://merchant.example/",
                        "status": 200,
                        "content": "Welcome to Merchant Co",
                        "truncated": False,
                    }
                ),
                json.dumps(
                    {
                        "url": "https://merchant.example/about",
                        "status": 200,
                        "content": "We sell sandwiches",
                        "truncated": False,
                    }
                ),
            ]
        )

        async def fake_execute(name, arguments):
            return next(pages)

        with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
            with patch.object(cat_module, "execute_tool", AsyncMock(side_effect=fake_execute)):
                result = await tag_for("MERCHANT_CO")

        assert result == "food"
        assert cache.upserts == [("merchant_co", "food")]
        # Three POSTs: two tool-call turns + one final-answer turn.
        assert mock_client.calls == 3

        # Each tool turn appends its own assistant + tool messages, in
        # order. The final request must contain both tool results.
        final_msgs = mock_client.captured_payloads[2]["messages"]
        roles = [m["role"] for m in final_msgs]
        assert roles == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant",
            "tool",
        ]
        assert final_msgs[3]["tool_call_id"] == "call_1"
        assert final_msgs[5]["tool_call_id"] == "call_2"
        assert "sandwiches" in final_msgs[5]["content"]

    @pytest.mark.asyncio
    async def test_iteration_cap_returns_none_when_model_keeps_calling(
        self, settings, cache
    ):
        """If the model never answers with a tag within MAX_ITERATIONS
        we give up and return None — never spin forever.
        """
        from app.services import categorizer as cat_module

        call_resps = [
            _mock_response(
                "", tool_calls=[_curl_call(f"call_{i}", "https://x.example/")]
            )
            for i in range(MAX_ITERATIONS)
        ]
        mock_client = _MockClient(call_resps)
        with patch("app.services.categorizer.httpx.AsyncClient", return_value=mock_client):
            with patch.object(
                cat_module,
                "execute_tool",
                AsyncMock(return_value=json.dumps({"ok": True})),
            ):
                result = await tag_for("STUBBORN")

        assert result is None
        assert cache.upserts == []
        assert mock_client.calls == MAX_ITERATIONS