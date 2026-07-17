import json

import httpx
import pytest
from fastapi import HTTPException

from llm_proxy.models import ChatCompletionRequest, ChatMessage
from llm_proxy.providers.t3chat import FALLBACK_MODELS, T3ChatAdapter


@pytest.fixture
def adapter():
    a = T3ChatAdapter()
    a._models = FALLBACK_MODELS
    return a


class TestProviderIdentity:
    def test_provider_id(self):
        adapter = T3ChatAdapter()
        assert adapter.provider_id == "t3chat"

    def test_display_name(self):
        adapter = T3ChatAdapter()
        assert adapter.display_name == "T3 Chat"


class TestInitialize:
    @pytest.mark.asyncio
    async def test_successful_scrape(self, httpx_mock):
        # Build a JS chunk with >10 model IDs in an array
        model_ids = [f"model-{i}" for i in range(12)]
        id_array = ", ".join(f'"{mid}"' for mid in model_ids)
        js_content = f'let models = [{id_array}]'

        # Mock homepage with a script tag
        httpx_mock.add_response(
            url="https://t3.chat/",
            html=f'<html><script src="/_next/static/chunks/abc123.js"></script></html>',
        )
        # Mock JS chunk
        httpx_mock.add_response(
            url="https://t3.chat/_next/static/chunks/abc123.js",
            text=js_content,
        )

        adapter = T3ChatAdapter()
        await adapter.initialize()
        assert len(adapter._models) == 12

    @pytest.mark.asyncio
    async def test_failed_scrape_uses_fallback(self, httpx_mock):
        httpx_mock.add_response(url="https://t3.chat/", status_code=500)

        adapter = T3ChatAdapter()
        await adapter.initialize()
        assert adapter._models == FALLBACK_MODELS


class TestGetModels:
    def test_returns_model_objects(self, adapter):
        models = adapter.get_models()
        assert len(models) == len(FALLBACK_MODELS)
        assert models[0].id == FALLBACK_MODELS[0]["id"]
        assert models[0].object == "model"


class TestValidateCredentials:
    def test_empty_credentials_raises(self, adapter):
        with pytest.raises(HTTPException) as exc_info:
            adapter._validate_credentials({})
        assert exc_info.value.status_code == 401

    def test_valid_credentials(self, adapter):
        cookies, sid = adapter._validate_credentials(
            {"cookies": "abc=123", "convex_session_id": "uuid-here"}
        )
        assert cookies == "abc=123"
        assert sid == "uuid-here"


class TestBuildRequestBody:
    def test_produces_correct_structure(self, adapter):
        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Hello"),
            ],
        )
        body = adapter._build_t3_request_body(request, "session-123", "thread-456")

        assert body["model"] == "gemini-3-flash"
        assert body["convexSessionId"] == "session-123"
        assert body["threadMetadata"]["id"] == "thread-456"
        assert body["isEphemeral"] is True
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][0]["parts"] == [{"type": "text", "text": "You are helpful."}]
        assert body["messages"][1]["role"] == "user"


class TestGetOpencodeModelConfig:
    def test_returns_correct_format(self, adapter):
        configs = adapter.get_opencode_model_config()
        assert isinstance(configs, dict)
        assert len(configs) == len(FALLBACK_MODELS)
        # Check first model entry
        first_id = next(iter(configs))
        first = configs[first_id]
        assert "name" in first
        assert "limit" in first
        assert "context" in first["limit"]
        assert "output" in first["limit"]


class TestStreamParsing:
    @pytest.mark.asyncio
    async def test_text_delta_chunks(self, adapter, httpx_mock):
        sse_lines = (
            'data: {"type": "text-delta", "delta": "Hello"}\n\n'
            'data: {"type": "text-delta", "delta": " world"}\n\n'
            'data: {"type": "finish"}\n\n'
            "data: [DONE]\n\n"
        )

        # Mock session refresh
        httpx_mock.add_response(url=httpx.URL(
            "https://t3.chat/api/trpc/auth.getActiveSessions"
            "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
        ))
        # Mock chat API
        httpx_mock.add_response(
            url="https://t3.chat/api/chat",
            text=sse_lines,
            headers={"content-type": "text/event-stream"},
        )

        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )
        creds = {"cookies": "test=1", "convex_session_id": "sid"}

        chunks = []
        async for chunk in adapter.chat_completion_stream(request, creds):
            chunks.append(chunk)

        # text-delta, text-delta, finish = 3 chunks
        assert len(chunks) == 3
        assert chunks[0].choices[0].delta.content == "Hello"
        assert chunks[1].choices[0].delta.content == " world"
        assert chunks[2].choices[0].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_reasoning_delta_chunks(self, adapter, httpx_mock):
        sse_lines = (
            'data: {"type": "reasoning-delta", "delta": "thinking..."}\n\n'
            'data: {"type": "text-delta", "delta": "answer"}\n\n'
            'data: {"type": "finish"}\n\n'
            "data: [DONE]\n\n"
        )

        httpx_mock.add_response(url=httpx.URL(
            "https://t3.chat/api/trpc/auth.getActiveSessions"
            "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
        ))
        httpx_mock.add_response(
            url="https://t3.chat/api/chat",
            text=sse_lines,
            headers={"content-type": "text/event-stream"},
        )

        request = ChatCompletionRequest(
            model="deepseek-r1",
            messages=[ChatMessage(role="user", content="think")],
            stream=True,
        )
        creds = {"cookies": "test=1", "convex_session_id": "sid"}

        chunks = []
        async for chunk in adapter.chat_completion_stream(request, creds):
            chunks.append(chunk)

        assert chunks[0].choices[0].delta.reasoning_content == "thinking..."
        assert chunks[1].choices[0].delta.content == "answer"

    @pytest.mark.asyncio
    async def test_chat_completion_non_streaming(self, adapter, httpx_mock):
        sse_lines = (
            'data: {"type": "text-delta", "delta": "Hello"}\n\n'
            'data: {"type": "text-delta", "delta": " there"}\n\n'
            'data: {"type": "finish"}\n\n'
            "data: [DONE]\n\n"
        )

        httpx_mock.add_response(url=httpx.URL(
            "https://t3.chat/api/trpc/auth.getActiveSessions"
            "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
        ))
        httpx_mock.add_response(
            url="https://t3.chat/api/chat",
            text=sse_lines,
            headers={"content-type": "text/event-stream"},
        )

        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[ChatMessage(role="user", content="hi")],
        )
        creds = {"cookies": "test=1", "convex_session_id": "sid"}

        response = await adapter.chat_completion(request, creds)
        assert response.choices[0].message.content == "Hello there"
        assert response.choices[0].finish_reason == "stop"
        assert response.object == "chat.completion"


class TestToolCallStreaming:
    @pytest.mark.asyncio
    async def test_tool_call_detected_in_stream(self, adapter, httpx_mock):
        """When tools are in the request and the model outputs <tool_call> XML,
        it should be parsed into structured tool_calls chunks."""
        sse_lines = (
            'data: {"type": "text-delta", "delta": "<tool_call>\\n'
            '{\\"name\\": \\"Bash\\", \\"arguments\\": {\\"command\\": \\"ls\\"}}\\n'
            '</tool_call>"}\n\n'
            'data: {"type": "finish"}\n\n'
            "data: [DONE]\n\n"
        )

        httpx_mock.add_response(
            url=httpx.URL(
                "https://t3.chat/api/trpc/auth.getActiveSessions"
                "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
            )
        )
        httpx_mock.add_response(
            url="https://t3.chat/api/chat",
            text=sse_lines,
            headers={"content-type": "text/event-stream"},
        )

        request = ChatCompletionRequest(
            model="claude-4.6-opus",
            messages=[ChatMessage(role="user", content="list files")],
            stream=True,
            tools=[{"type": "function", "function": {"name": "Bash", "parameters": {}}}],
        )
        creds = {"cookies": "test=1", "convex_session_id": "sid"}

        chunks = []
        async for chunk in adapter.chat_completion_stream(request, creds):
            chunks.append(chunk)

        # Should have a tool_calls chunk and a finish chunk
        tool_chunks = [c for c in chunks if c.choices[0].delta.tool_calls]
        assert len(tool_chunks) == 1
        tc = tool_chunks[0].choices[0].delta.tool_calls[0]
        assert tc["function"]["name"] == "Bash"
        assert json.loads(tc["function"]["arguments"]) == {"command": "ls"}

        # Finish chunk should have finish_reason="tool_calls"
        finish_chunks = [c for c in chunks if c.choices[0].finish_reason]
        assert finish_chunks[-1].choices[0].finish_reason == "tool_calls"

    @pytest.mark.asyncio
    async def test_no_tool_parsing_without_tools_in_request(self, adapter, httpx_mock):
        """When no tools are in the request, <tool_call> text passes through as content."""
        sse_lines = (
            'data: {"type": "text-delta", "delta": "<tool_call>test</tool_call>"}\n\n'
            'data: {"type": "finish"}\n\n'
            "data: [DONE]\n\n"
        )

        httpx_mock.add_response(
            url=httpx.URL(
                "https://t3.chat/api/trpc/auth.getActiveSessions"
                "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
            )
        )
        httpx_mock.add_response(
            url="https://t3.chat/api/chat",
            text=sse_lines,
            headers={"content-type": "text/event-stream"},
        )

        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )
        creds = {"cookies": "test=1", "convex_session_id": "sid"}

        chunks = []
        async for chunk in adapter.chat_completion_stream(request, creds):
            chunks.append(chunk)

        # Text should pass through as content, not parsed as tool call
        content = "".join(c.choices[0].delta.content or "" for c in chunks)
        assert "<tool_call>" in content
        # finish_reason should be "stop" not "tool_calls"
        finish_chunks = [c for c in chunks if c.choices[0].finish_reason]
        assert finish_chunks[-1].choices[0].finish_reason == "stop"


class TestToolMessageConversion:
    def test_tool_role_converted_to_user(self, adapter):
        """role:'tool' messages should become role:'user' with formatted content."""
        messages = [
            ChatMessage(role="user", content="list files"),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "Bash",
                            "arguments": '{"command": "ls"}',
                        },
                    }
                ],
            ),
            ChatMessage(
                role="tool",
                content="file1.txt\nfile2.txt",
                tool_call_id="call_abc",
            ),
        ]
        converted = adapter._convert_messages_for_t3(messages)

        # First message unchanged
        assert converted[0].role == "user"
        assert converted[0].content == "list files"

        # Assistant with tool_calls -> plain text with XML
        assert converted[1].role == "assistant"
        assert "<tool_call>" in converted[1].content
        assert "Bash" in converted[1].content

        # Tool result -> user message with XML
        assert converted[2].role == "user"
        assert "<tool_result>" in converted[2].content
        assert "call_abc" in converted[2].content
        assert "file1.txt" in converted[2].content

    def test_regular_messages_unchanged(self, adapter):
        """Messages without tool-related fields pass through unchanged."""
        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
        ]
        converted = adapter._convert_messages_for_t3(messages)

        assert len(converted) == 3
        assert converted[0].role == "system"
        assert converted[0].content == "You are helpful."
        assert converted[1].role == "user"
        assert converted[2].role == "assistant"
        assert converted[2].content == "Hi there!"

    def test_assistant_with_content_and_tool_calls(self, adapter):
        """Assistant message with both content and tool_calls preserves both."""
        messages = [
            ChatMessage(
                role="assistant",
                content="Let me check that for you.",
                tool_calls=[
                    {
                        "id": "call_xyz",
                        "type": "function",
                        "function": {
                            "name": "Read",
                            "arguments": '{"path": "/tmp/test.txt"}',
                        },
                    }
                ],
            ),
        ]
        converted = adapter._convert_messages_for_t3(messages)

        assert converted[0].role == "assistant"
        assert "Let me check that for you." in converted[0].content
        assert "<tool_call>" in converted[0].content
        assert "Read" in converted[0].content


class TestToolPromptInjection:
    def test_tools_injected_into_existing_system_message(self, adapter):
        """Tool definitions should be appended to the existing system prompt."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "convert_document",
                    "description": "Convert a document to text",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to the document",
                            }
                        },
                        "required": ["path"],
                    },
                },
            }
        ]
        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Hello"),
            ],
            tools=tools,
        )
        body = adapter._build_t3_request_body(request, "session-123", "thread-456")

        # System message should contain both original content and tool definitions
        system_parts = body["messages"][0]["parts"]
        system_text = system_parts[0]["text"]
        assert "You are helpful." in system_text
        assert "convert_document" in system_text
        assert "Convert a document to text" in system_text
        assert "`path`" in system_text
        assert "(required)" in system_text

    def test_tools_create_system_message_when_none_exists(self, adapter):
        """When no system message exists, a new one should be created."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "Bash",
                    "description": "Run a bash command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The command"},
                        },
                        "required": ["command"],
                    },
                },
            }
        ]
        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[
                ChatMessage(role="user", content="Hello"),
            ],
            tools=tools,
        )
        body = adapter._build_t3_request_body(request, "session-123", "thread-456")

        # First message should be the injected system message
        assert body["messages"][0]["role"] == "system"
        system_text = body["messages"][0]["parts"][0]["text"]
        assert "Bash" in system_text
        assert "Run a bash command" in system_text
        # User message should follow
        assert body["messages"][1]["role"] == "user"

    def test_no_injection_without_tools(self, adapter):
        """When no tools are in the request, system message should be unchanged."""
        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Hello"),
            ],
        )
        body = adapter._build_t3_request_body(request, "session-123", "thread-456")

        system_text = body["messages"][0]["parts"][0]["text"]
        assert system_text == "You are helpful."
        assert "Available Tools" not in system_text

    def test_multiple_tools_injected(self, adapter):
        """Multiple tool definitions should all be present."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "Bash",
                    "description": "Run a command",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "convert_document",
                    "description": "Convert a doc",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                        },
                        "required": ["path"],
                    },
                },
            },
        ]
        request = ChatCompletionRequest(
            model="gemini-3-flash",
            messages=[
                ChatMessage(role="system", content="System prompt."),
                ChatMessage(role="user", content="Hello"),
            ],
            tools=tools,
        )
        body = adapter._build_t3_request_body(request, "session-123", "thread-456")

        system_text = body["messages"][0]["parts"][0]["text"]
        assert "Bash" in system_text
        assert "convert_document" in system_text
        assert "Convert a doc" in system_text
