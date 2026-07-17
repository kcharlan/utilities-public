import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from llm_proxy.models import ChatCompletionRequest, ChatMessage
from llm_proxy.providers.chatjimmy import (
    CHATJIMMY_MODELS_URL,
    STATS_END,
    STATS_START,
    ChatJimmyAdapter,
)


@pytest.fixture
def adapter():
    a = ChatJimmyAdapter()
    # Pre-populate models so tests don't need network
    from llm_proxy.models import ModelObject

    a._models = [
        ModelObject(id="llama3.1-8B", created=1690000000, owned_by="Taalas Inc.")
    ]
    return a


def _make_request(content="Say hello.", model="llama3.1-8B", system=None):
    messages = []
    if system:
        messages.append(ChatMessage(role="system", content=system))
    messages.append(ChatMessage(role="user", content=content))
    return ChatCompletionRequest(model=model, messages=messages)


class TestBuildRequestBody:
    def test_basic_message(self, adapter):
        req = _make_request("Hello")
        body = adapter._build_request_body(req)

        assert body["messages"] == [{"role": "user", "content": "Hello"}]
        assert body["chatOptions"]["selectedModel"] == "llama3.1-8B"
        assert body["chatOptions"]["systemPrompt"] == ""
        assert body["chatOptions"]["topK"] == 8
        assert body["attachment"] is None

    def test_system_prompt_extracted(self, adapter):
        req = _make_request("Hello", system="You are helpful.")
        body = adapter._build_request_body(req)

        assert body["chatOptions"]["systemPrompt"] == "You are helpful."
        # System message should NOT appear in messages array
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"

    def test_multiple_system_messages_concatenated(self, adapter):
        req = ChatCompletionRequest(
            model="llama3.1-8B",
            messages=[
                ChatMessage(role="system", content="Rule 1"),
                ChatMessage(role="system", content="Rule 2"),
                ChatMessage(role="user", content="Hi"),
            ],
        )
        body = adapter._build_request_body(req)
        assert body["chatOptions"]["systemPrompt"] == "Rule 1\nRule 2"

    def test_multi_turn_conversation(self, adapter):
        req = ChatCompletionRequest(
            model="llama3.1-8B",
            messages=[
                ChatMessage(role="user", content="Hi"),
                ChatMessage(role="assistant", content="Hello!"),
                ChatMessage(role="user", content="How are you?"),
            ],
        )
        body = adapter._build_request_body(req)
        assert len(body["messages"]) == 3
        assert body["messages"][0] == {"role": "user", "content": "Hi"}
        assert body["messages"][1] == {"role": "assistant", "content": "Hello!"}
        assert body["messages"][2] == {"role": "user", "content": "How are you?"}


class TestParseStream:
    """Test the _parse_stream method with simulated httpx responses."""

    @staticmethod
    def _make_response(chunks: list[str]):
        """Create a mock httpx.Response that yields the given text chunks."""
        response = AsyncMock()

        async def aiter_text():
            for c in chunks:
                yield c

        response.aiter_text = aiter_text
        return response

    @pytest.mark.asyncio
    async def test_simple_response(self, adapter):
        stats = json.dumps({"done": True, "total_tokens": 10})
        chunks = [f"Hello world{STATS_START}{stats}{STATS_END}"]
        response = self._make_response(chunks)

        parts = []
        async for text in adapter._parse_stream(response):
            parts.append(text)

        assert "".join(parts) == "Hello world"

    @pytest.mark.asyncio
    async def test_prelude_stripped(self, adapter):
        stats = json.dumps({"done": True})
        chunks = [f"{{}}\nHello{STATS_START}{stats}{STATS_END}"]
        response = self._make_response(chunks)

        parts = []
        async for text in adapter._parse_stream(response):
            parts.append(text)

        assert "".join(parts) == "Hello"

    @pytest.mark.asyncio
    async def test_multi_chunk_response(self, adapter):
        stats = json.dumps({"done": True, "total_tokens": 5})
        chunks = ["Hello ", "world! ", f"How are you?{STATS_START}{stats}{STATS_END}"]
        response = self._make_response(chunks)

        parts = []
        async for text in adapter._parse_stream(response):
            parts.append(text)

        assert "".join(parts) == "Hello world! How are you?"

    @pytest.mark.asyncio
    async def test_stats_split_across_chunks(self, adapter):
        """Stats sentinel split across two chunks."""
        stats = json.dumps({"done": True})
        # Split "<|stats|>" across chunks
        chunks = ["Hello world<|sta", f"ts|>{stats}{STATS_END}"]
        response = self._make_response(chunks)

        parts = []
        async for text in adapter._parse_stream(response):
            parts.append(text)

        assert "".join(parts) == "Hello world"

    @pytest.mark.asyncio
    async def test_stats_parsed_for_usage(self, adapter):
        stats = json.dumps({
            "prefill_tokens": 14,
            "decode_tokens": 10,
            "total_tokens": 24,
            "done": True,
        })
        chunks = [f"Hi{STATS_START}{stats}{STATS_END}"]
        response = self._make_response(chunks)

        async for _ in adapter._parse_stream(response):
            pass

        assert adapter._last_stats is not None
        assert adapter._last_stats["prefill_tokens"] == 14
        assert adapter._last_stats["decode_tokens"] == 10

    @pytest.mark.asyncio
    async def test_no_stats_flushes_buffer(self, adapter):
        """If stream ends without stats (unusual), remaining buffer is emitted."""
        chunks = ["Hello world"]
        response = self._make_response(chunks)

        parts = []
        async for text in adapter._parse_stream(response):
            parts.append(text)

        assert "".join(parts) == "Hello world"

    @pytest.mark.asyncio
    async def test_trailing_percent_stripped(self, adapter):
        """Trailing '%' after stats (or without stats) should not appear in output."""
        chunks = ["Hello%"]
        response = self._make_response(chunks)

        parts = []
        async for text in adapter._parse_stream(response):
            parts.append(text)

        assert "".join(parts) == "Hello"

    @pytest.mark.asyncio
    async def test_prelude_split_across_chunks(self, adapter):
        """The '{}\\n' prelude arrives in its own chunk."""
        stats = json.dumps({"done": True})
        chunks = ["{}\n", f"Content{STATS_START}{stats}{STATS_END}"]
        response = self._make_response(chunks)

        parts = []
        async for text in adapter._parse_stream(response):
            parts.append(text)

        assert "".join(parts) == "Content"


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_success(self):
        adapter = ChatJimmyAdapter()
        mock_response = {
            "object": "list",
            "data": [
                {
                    "id": "llama3.1-8B",
                    "object": "model",
                    "created": 1690000000,
                    "owned_by": "Taalas Inc.",
                }
            ],
        }

        with patch("llm_proxy.providers.chatjimmy.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_client.get = AsyncMock(return_value=mock_resp)

            await adapter.initialize()

        assert len(adapter._models) == 1
        assert adapter._models[0].id == "llama3.1-8B"

    @pytest.mark.asyncio
    async def test_initialize_fallback_on_error(self):
        adapter = ChatJimmyAdapter()

        with patch("llm_proxy.providers.chatjimmy.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))

            await adapter.initialize()

        assert len(adapter._models) == 1
        assert adapter._models[0].id == "llama3.1-8B"


class TestProperties:
    def test_provider_id(self, adapter):
        assert adapter.provider_id == "chatjimmy"

    def test_display_name(self, adapter):
        assert adapter.display_name == "ChatJimmy"

    def test_requires_auth_false(self, adapter):
        assert adapter.requires_auth is False

    def test_opencode_model_config(self, adapter):
        config = adapter.get_opencode_model_config()
        assert "llama3.1-8B" in config
        assert config["llama3.1-8B"]["limit"]["context"] == 128000
