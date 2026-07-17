import json
import logging
import time
from typing import AsyncIterator
from uuid import uuid4

import httpx

from llm_proxy.models import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ModelObject,
    Usage,
)
from llm_proxy.provider_base import ProviderAdapter

logger = logging.getLogger(__name__)

CHATJIMMY_BASE_URL = "https://chatjimmy.ai"
CHATJIMMY_CHAT_URL = f"{CHATJIMMY_BASE_URL}/api/chat"
CHATJIMMY_MODELS_URL = f"{CHATJIMMY_BASE_URL}/api/models"

STATS_START = "<|stats|>"
STATS_END = "<|/stats|>"

# Lookahead buffer size — large enough to hold the full STATS_START sentinel
# so we never accidentally emit it as content when it arrives split across chunks.
_SENTINEL_LEN = len(STATS_START)

FALLBACK_MODELS = [
    {
        "id": "llama3.1-8B",
        "object": "model",
        "created": 1690000000,
        "owned_by": "Taalas Inc.",
    }
]


class ChatJimmyAdapter(ProviderAdapter):

    def __init__(self):
        self._models: list[ModelObject] = []

    @property
    def provider_id(self) -> str:
        return "chatjimmy"

    @property
    def display_name(self) -> str:
        return "ChatJimmy"

    @property
    def requires_auth(self) -> bool:
        return False

    async def initialize(self) -> None:
        """Discover available models from chatjimmy.ai."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(CHATJIMMY_MODELS_URL)
                resp.raise_for_status()
                data = resp.json()

            raw_models = data.get("data", [])
            if not raw_models:
                raise ValueError("Empty model list from API")

            self._models = [
                ModelObject(
                    id=m["id"],
                    created=m.get("created", 0),
                    owned_by=m.get("owned_by", "unknown"),
                )
                for m in raw_models
            ]
            logger.info(
                "ChatJimmy: discovered %d model(s): %s",
                len(self._models),
                [m.id for m in self._models],
            )
        except Exception as e:
            logger.warning(
                "ChatJimmy: model discovery failed (%s), using fallback", e
            )
            self._models = [
                ModelObject(
                    id=m["id"],
                    created=m["created"],
                    owned_by=m["owned_by"],
                )
                for m in FALLBACK_MODELS
            ]

    def get_models(self) -> list[ModelObject]:
        return self._models

    def get_opencode_model_config(self) -> dict:
        configs = {}
        for model in self._models:
            configs[model.id] = {
                "name": model.id,
                "limit": {"context": 128000, "output": 4096},
            }
        return configs

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> ChatCompletionResponse:
        """Non-streaming: accumulate all streamed chunks into a single response."""
        completion_id = f"chatcmpl-{uuid4().hex[:24]}"
        created = int(time.time())
        content_parts: list[str] = []
        finish_reason = None
        usage = None

        async for chunk in self._stream_response(request, completion_id, created):
            for choice in chunk.choices:
                if choice.delta.content:
                    content_parts.append(choice.delta.content)
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

        # Try to get usage from the stats that were parsed during streaming
        if hasattr(self, "_last_stats") and self._last_stats:
            stats = self._last_stats
            prompt_tokens = stats.get("prefill_tokens", 0)
            completion_tokens = stats.get("decode_tokens", 0)
            usage = Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=stats.get("total_tokens", prompt_tokens + completion_tokens),
            )
            self._last_stats = None

        return ChatCompletionResponse(
            id=completion_id,
            created=created,
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content="".join(content_parts),
                    ),
                    finish_reason=finish_reason or "stop",
                )
            ],
            usage=usage,
        )

    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> AsyncIterator[ChatCompletionChunk]:
        completion_id = f"chatcmpl-{uuid4().hex[:24]}"
        created = int(time.time())
        async for chunk in self._stream_response(request, completion_id, created):
            yield chunk

    async def _stream_response(
        self,
        request: ChatCompletionRequest,
        completion_id: str,
        created: int,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Core streaming logic: sends request to chatjimmy.ai and yields
        OpenAI-compatible chunks by parsing the custom stream format."""

        body = self._build_request_body(request)

        # Yield initial role chunk
        yield ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=request.model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(role="assistant"),
                )
            ],
        )

        self._last_stats = None

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            async with client.stream(
                "POST",
                CHATJIMMY_CHAT_URL,
                json=body,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    logger.error(
                        "ChatJimmy upstream error: status=%d body=%s",
                        response.status_code,
                        error_body[:500],
                    )
                    # Emit error as content so the client sees it
                    yield ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=request.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=ChatCompletionChunkDelta(
                                    content=f"[ChatJimmy error: HTTP {response.status_code}]"
                                ),
                            )
                        ],
                    )
                    yield ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=request.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=ChatCompletionChunkDelta(),
                                finish_reason="stop",
                            )
                        ],
                    )
                    return

                async for content_text in self._parse_stream(response):
                    yield ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=request.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=ChatCompletionChunkDelta(content=content_text),
                            )
                        ],
                    )

        # Final chunk with finish_reason
        yield ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=request.model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(),
                    finish_reason="stop",
                )
            ],
        )

    async def _parse_stream(
        self, response: httpx.Response
    ) -> AsyncIterator[str]:
        """Parse chatjimmy's custom stream format, yielding content text fragments.

        Stream format:
            [optional: "{}\\n"]
            <assistant text tokens...>
            <|stats|>{...json...}<|/stats|>[optional: "%"]

        Strategy: buffer incoming text, emit everything that is clearly content,
        hold back a lookahead buffer to avoid emitting partial sentinel markers.
        """
        buffer = ""
        first_chunk = True
        found_stats = False

        async for raw_chunk in response.aiter_text():
            buffer += raw_chunk

            # Strip the optional "{}\n" prelude from the very first chunk
            if first_chunk:
                first_chunk = False
                if buffer.startswith("{}\n"):
                    buffer = buffer[3:]
                elif buffer == "{}" or buffer == "{}":
                    # Might get "{}" without newline yet — wait for more data
                    continue

            # Check if the stats sentinel has arrived
            stats_pos = buffer.find(STATS_START)
            if stats_pos != -1:
                # Everything before the sentinel is content
                content = buffer[:stats_pos]
                if content:
                    yield content

                # Parse the stats JSON
                remainder = buffer[stats_pos + len(STATS_START):]
                end_pos = remainder.find(STATS_END)
                if end_pos != -1:
                    stats_json = remainder[:end_pos]
                    try:
                        self._last_stats = json.loads(stats_json)
                    except json.JSONDecodeError:
                        logger.warning("ChatJimmy: failed to parse stats JSON")
                found_stats = True
                break

            # No sentinel yet — emit content but hold back a lookahead buffer
            # in case the sentinel is split across chunks
            safe_len = len(buffer) - _SENTINEL_LEN
            if safe_len > 0:
                yield buffer[:safe_len]
                buffer = buffer[safe_len:]

        # If we never found stats (unexpected), flush remaining buffer as content
        if not found_stats and buffer:
            # Strip trailing "%" that sometimes appears
            if buffer.endswith("%"):
                buffer = buffer[:-1]
            if buffer:
                yield buffer

    def _build_request_body(self, request: ChatCompletionRequest) -> dict:
        """Convert OpenAI ChatCompletionRequest to chatjimmy.ai request format."""
        system_prompt = ""
        messages = []

        for msg in request.messages:
            if msg.role == "system":
                # chatjimmy uses a separate systemPrompt field
                content = msg.content if isinstance(msg.content, str) else ""
                if system_prompt:
                    system_prompt += "\n" + content
                else:
                    system_prompt = content
            else:
                content = msg.content if isinstance(msg.content, str) else ""
                messages.append({
                    "role": msg.role,
                    "content": content,
                })

        return {
            "messages": messages,
            "chatOptions": {
                "selectedModel": request.model,
                "systemPrompt": system_prompt,
                "topK": 8,
            },
            "attachment": None,
        }
