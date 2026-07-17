from llm_proxy.models import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ModelListResponse,
    ModelObject,
    Usage,
)


class TestChatCompletionRequest:
    def test_valid_minimal_request(self):
        req = ChatCompletionRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
        )
        assert req.model == "gpt-4"
        assert len(req.messages) == 1
        assert req.stream is False

    def test_accepts_extra_fields(self):
        req = ChatCompletionRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
            reasoning_effort="high",
            custom_field="test",
        )
        assert req.model == "gpt-4"
        assert req.reasoning_effort == "high"


class TestChatCompletionChunk:
    def test_serializes_correctly(self):
        chunk = ChatCompletionChunk(
            id="chatcmpl-123",
            created=1234567890,
            model="gpt-4",
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(content="hello"),
                )
            ],
        )
        data = chunk.model_dump()
        assert data["object"] == "chat.completion.chunk"
        assert data["choices"][0]["delta"]["content"] == "hello"
        assert data["choices"][0]["finish_reason"] is None


class TestChatCompletionResponse:
    def test_serializes_correctly(self):
        resp = ChatCompletionResponse(
            id="chatcmpl-123",
            created=1234567890,
            model="gpt-4",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="hi"),
                    finish_reason="stop",
                )
            ],
            usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
        data = resp.model_dump()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "hi"
        assert data["usage"]["total_tokens"] == 15


class TestModelListResponse:
    def test_serializes_correctly(self):
        resp = ModelListResponse(
            data=[
                ModelObject(id="gpt-4", created=0, owned_by="openai"),
                ModelObject(id="gpt-3.5", created=0, owned_by="openai"),
            ]
        )
        data = resp.model_dump()
        assert data["object"] == "list"
        assert len(data["data"]) == 2
        assert data["data"][0]["id"] == "gpt-4"
