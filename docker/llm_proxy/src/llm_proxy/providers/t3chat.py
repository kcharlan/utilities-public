import json
import logging
import re
import time
from typing import AsyncIterator
from uuid import uuid4

import httpx
from fastapi import HTTPException

from llm_proxy.models import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ModelObject,
)
from llm_proxy.provider_base import ProviderAdapter
from llm_proxy.tool_call_parser import ToolCallStreamParser

logger = logging.getLogger(__name__)

T3_CHAT_API_URL = "https://t3.chat/api/chat"
T3_SESSION_REFRESH_URL = (
    "https://t3.chat/api/trpc/auth.getActiveSessions"
    "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22includeLocation%22%3Afalse%7D%7D%7D"
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/144.0.0.0 Safari/537.36"
    ),
    "Origin": "https://t3.chat",
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

FALLBACK_MODELS = [
    {"id": "gemini-3-flash", "name": "Gemini 3 Flash", "owned_by": "google", "can_reason": False},
    {
        "id": "gemini-3-flash-thinking",
        "name": "Gemini 3 Flash Thinking",
        "owned_by": "google",
        "can_reason": True,
    },
    {
        "id": "gemini-3.1-pro",
        "name": "Gemini 3.1 Pro",
        "owned_by": "google",
        "can_reason": True,
    },
    {
        "id": "claude-4.6-opus",
        "name": "Claude 4.6 Opus",
        "owned_by": "anthropic",
        "can_reason": True,
    },
    {
        "id": "claude-4.6-sonnet",
        "name": "Claude 4.6 Sonnet",
        "owned_by": "anthropic",
        "can_reason": True,
    },
    {
        "id": "gpt-5.2-reasoning",
        "name": "GPT 5.2 Reasoning",
        "owned_by": "openai",
        "can_reason": True,
    },
    {
        "id": "gpt-5.2-instant",
        "name": "GPT 5.2 Instant",
        "owned_by": "openai",
        "can_reason": False,
    },
    {
        "id": "grok-4.1-fast",
        "name": "Grok 4.1 Fast",
        "owned_by": "xai",
        "can_reason": False,
    },
    {
        "id": "grok-4.1-fast-reasoning",
        "name": "Grok 4.1 Fast Reasoning",
        "owned_by": "xai",
        "can_reason": True,
    },
    {"id": "kimi-k2.5", "name": "Kimi K2.5", "owned_by": "moonshot", "can_reason": False},
    {
        "id": "kimi-k2.5-thinking",
        "name": "Kimi K2.5 Thinking",
        "owned_by": "moonshot",
        "can_reason": True,
    },
    {"id": "deepseek-r1", "name": "DeepSeek R1", "owned_by": "deepseek", "can_reason": True},
    {"id": "deepseek-v3", "name": "DeepSeek V3", "owned_by": "deepseek", "can_reason": False},
]


class T3ChatAdapter(ProviderAdapter):
    def __init__(self):
        self._models: list[dict] = []
        self._byok_models: set[str] = set()  # models that need low reasoning to avoid BYOK

    @property
    def provider_id(self) -> str:
        return "t3chat"

    @property
    def display_name(self) -> str:
        return "T3 Chat"

    @property
    def env_var_name(self) -> str:
        return "T3_CHAT_CREDS"

    async def initialize(self) -> None:
        try:
            async with httpx.AsyncClient(
                headers=BROWSER_HEADERS, timeout=30.0
            ) as client:
                resp = await client.get("https://t3.chat/")
                resp.raise_for_status()
                html = resp.text

                chunk_urls = re.findall(
                    r'<script[^>]+src="(/_next/static/chunks/[a-f0-9]+\.js[^"]*)"', html
                )
                chunk_urls = [f"https://t3.chat{path}" for path in chunk_urls]

                discovered = []
                for url in chunk_urls:
                    try:
                        js_resp = await client.get(url)
                        js_resp.raise_for_status()
                        js_content = js_resp.text

                        # Look for arrays of model ID strings
                        array_matches = re.findall(
                            r'let\s+\w+\s*=\s*\[((?:"[^"]+",?\s*)+)\]', js_content
                        )
                        for array_str in array_matches:
                            model_ids = re.findall(r'"([^"]+)"', array_str)
                            models_from_chunk = []
                            for model_id in model_ids:
                                # Try to find model definition block
                                pattern = (
                                    rf'"{re.escape(model_id)}":\s*\{{.*?'
                                    rf'id:\s*"([^"]+)"'
                                    rf'(?:.*?name:\s*"([^"]+)")?'
                                    rf'(?:.*?provider:\s*"([^"]+)")?'
                                    rf'(?:.*?developer:\s*"([^"]+)")?'
                                )
                                defn = re.search(pattern, js_content, re.DOTALL)
                                name = model_id
                                owned_by = "t3chat"
                                if defn:
                                    name = defn.group(2) or model_id
                                    owned_by = defn.group(3) or defn.group(4) or "t3chat"

                                can_reason = "thinking" in model_id or "reasoning" in model_id
                                models_from_chunk.append(
                                    {
                                        "id": model_id,
                                        "name": name,
                                        "owned_by": owned_by,
                                        "can_reason": can_reason,
                                    }
                                )

                            if len(models_from_chunk) > 10:
                                discovered = models_from_chunk
                                break

                    except Exception:
                        continue

                    if discovered:
                        break

                if discovered:
                    self._models = discovered
                else:
                    logger.warning("T3 model discovery found no models, using fallback list")
                    self._models = FALLBACK_MODELS

        except Exception as e:
            logger.warning(f"T3 model discovery failed, using fallback list: {e}")
            self._models = FALLBACK_MODELS

        logger.info(f"T3 Chat: discovered {len(self._models)} models")

    def get_models(self) -> list[ModelObject]:
        return [
            ModelObject(id=m["id"], created=0, owned_by=m.get("owned_by", "t3chat"))
            for m in self._models
        ]

    def get_opencode_model_config(self) -> dict:
        return {
            m["id"]: {
                "name": m.get("name", m["id"]),
                "limit": {
                    "context": 200000,
                    "output": 16000,
                },
            }
            for m in self._models
        }

    def _validate_credentials(self, credentials: dict) -> tuple[str, str]:
        cookies = credentials.get("cookies")
        convex_session_id = credentials.get("convex_session_id")
        if not cookies or not convex_session_id:
            raise HTTPException(
                status_code=401,
                detail="T3 credentials must include 'cookies' and 'convex_session_id'",
            )
        return (cookies, convex_session_id)

    async def _refresh_session(self, client: httpx.AsyncClient, cookies: str) -> str:
        try:
            resp = await client.get(
                T3_SESSION_REFRESH_URL,
                headers={
                    "Cookie": cookies,
                    "Content-Type": "application/json",
                    "trpc-accept": "application/jsonl",
                },
            )
            new_session = resp.headers.get("x-workos-session")
            if new_session:
                parts = cookies.split("; ")
                parts = [p for p in parts if not p.startswith("wos-session=")]
                parts.append(f"wos-session={new_session}")
                return "; ".join(parts)
        except Exception as e:
            logger.warning(f"Session refresh failed: {e}")
        return cookies

    def _convert_messages_for_t3(
        self, messages: list[ChatMessage]
    ) -> list[ChatMessage]:
        """Convert OpenAI tool-calling message formats into plain text
        that T3.chat can handle.

        - role:"tool" messages -> role:"user" with <tool_result> XML
        - assistant messages with tool_calls -> assistant with <tool_call> XML
        """
        converted = []
        for msg in messages:
            if msg.role == "tool":
                tool_call_id = msg.tool_call_id or "unknown"
                content = msg.content or ""
                formatted = (
                    f"<tool_result>\n"
                    f'{{"tool_call_id": "{tool_call_id}", '
                    f'"content": {json.dumps(content)}}}\n'
                    f"</tool_result>"
                )
                converted.append(ChatMessage(role="user", content=formatted))
            elif msg.role == "assistant" and msg.tool_calls:
                parts = []
                if msg.content:
                    parts.append(msg.content)
                for tc in msg.tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args_raw = func.get("arguments", "{}")
                    if isinstance(args_raw, str):
                        try:
                            args = json.loads(args_raw)
                        except json.JSONDecodeError:
                            args = args_raw
                    else:
                        args = args_raw
                    tc_json = json.dumps({"name": name, "arguments": args})
                    parts.append(f"<tool_call>\n{tc_json}\n</tool_call>")
                converted.append(
                    ChatMessage(role="assistant", content="\n\n".join(parts))
                )
            else:
                converted.append(msg)
        return converted

    def _format_tools_for_prompt(self, tools: list[dict]) -> str:
        """Format OpenAI tool definitions as text to inject into the system prompt.

        T3.chat doesn't support the OpenAI `tools` parameter natively, so we
        describe the available tools in the system message so the model knows
        about them and can output <tool_call> XML when it wants to use one.
        """
        lines = [
            "# Available Tools",
            "",
            "You have access to the following tools. To use a tool, output a "
            "<tool_call> XML block with the tool name and arguments as JSON:",
            "",
            "```",
            "<tool_call>",
            '{"name": "tool_name", "arguments": {"param": "value"}}',
            "</tool_call>",
            "```",
            "",
        ]

        for tool in tools:
            if tool.get("type") != "function":
                continue
            func = tool.get("function", {})
            name = func.get("name", "")
            description = func.get("description", "")
            parameters = func.get("parameters", {})

            lines.append(f"## {name}")
            if description:
                lines.append(description)

            # Include parameter schema if present
            if parameters and parameters.get("properties"):
                lines.append("")
                lines.append("Parameters:")
                props = parameters.get("properties", {})
                required = set(parameters.get("required", []))
                for param_name, param_info in props.items():
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    req_marker = " (required)" if param_name in required else ""
                    lines.append(f"- `{param_name}` ({param_type}{req_marker}): {param_desc}")

            lines.append("")

        return "\n".join(lines)

    def _build_t3_request_body(
        self,
        request: ChatCompletionRequest,
        convex_session_id: str,
        thread_id: str,
        reasoning_override: str | None = None,
    ) -> dict:
        # Convert tool-related messages to plain text for T3
        messages = self._convert_messages_for_t3(request.messages)

        # Inject tool definitions into the system prompt if tools are present
        extra = request.model_extra or {}
        tools = extra.get("tools", [])
        if tools:
            tool_prompt = self._format_tools_for_prompt(tools)
            # Find existing system message to append to, or create one
            system_idx = None
            for idx, msg in enumerate(messages):
                if msg.role == "system":
                    system_idx = idx
                    break

            if system_idx is not None:
                existing = messages[system_idx].content or ""
                messages[system_idx] = ChatMessage(
                    role="system",
                    content=f"{existing}\n\n{tool_prompt}",
                )
            else:
                messages.insert(0, ChatMessage(role="system", content=tool_prompt))

        converted_messages = []
        for msg in messages:
            if isinstance(msg.content, str):
                parts = [{"type": "text", "text": msg.content}]
            elif isinstance(msg.content, list):
                parts = msg.content
            else:
                parts = []

            converted_messages.append(
                {
                    "id": str(uuid4()),
                    "role": msg.role,
                    "parts": parts,
                    "attachments": [],
                }
            )

        # Determine reasoning effort:
        #  1. Explicit override (used by BYOK retry logic)
        #  2. Value from the request (OpenCode's reasoningEffort model option)
        #  3. Default: "medium"
        if reasoning_override:
            reasoning_effort = reasoning_override
        else:
            reasoning_effort = "medium"
            extra = request.model_extra or {}
            if extra.get("reasoning_effort"):
                reasoning_effort = extra["reasoning_effort"]

        return {
            "messages": converted_messages,
            "threadMetadata": {"id": thread_id},
            "responseMessageId": str(uuid4()),
            "model": request.model,
            "convexSessionId": convex_session_id,
            "modelParams": {
                "reasoningEffort": reasoning_effort,
                "includeSearch": False,
            },
            "preferences": {
                "name": "",
                "occupation": "",
                "selectedTraits": [],
                "additionalInfo": "",
            },
            "userInfo": {
                "timezone": "America/New_York",
                "locale": "en-US",
            },
            "isEphemeral": True,
        }

    async def _iter_t3_sse(
        self, client: httpx.AsyncClient, cookies: str, body: dict, thread_id: str
    ) -> AsyncIterator[tuple[str, dict | None]]:
        resp = await client.send(
            client.build_request(
                "POST",
                T3_CHAT_API_URL,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Cookie": cookies,
                    "Referer": f"https://t3.chat/chat/{thread_id}",
                    "Accept": "*/*",
                },
            ),
            stream=True,
        )

        if resp.status_code < 200 or resp.status_code >= 300:
            error_body = await resp.aread()
            error_msg = error_body.decode(errors="replace")
            logger.error("T3.chat returned %d: %s", resp.status_code, error_msg)
            yield (
                "error",
                {"status_code": resp.status_code, "message": error_msg},
            )
            return

        async for line in resp.aiter_lines():
            if not line:
                continue
            if not line.startswith("data: "):
                continue

            data_str = line[6:]
            if data_str == "[DONE]":
                yield ("done", None)
                return

            try:
                parsed = json.loads(data_str)
                event_type = parsed.get("type", "")
                yield (event_type, parsed)
            except json.JSONDecodeError:
                continue

    def _is_byok_error(self, error_msg: str) -> bool:
        """Check if an error indicates BYOK (bring-your-own-key) is required."""
        return "api_key_required" in error_msg

    def _event_to_chunk(
        self,
        event_type: str,
        event: dict | None,
        completion_id: str,
        created: int,
        model: str,
    ) -> ChatCompletionChunk | None:
        """Convert a single T3 SSE event into an OpenAI chunk, or None to skip."""
        if event_type == "error":
            status = event.get("status_code", 502)
            msg = event.get("message", "Unknown upstream error")
            return ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(
                            content=f"\n\n[Upstream error {status}: {msg}]"
                        ),
                        finish_reason="stop",
                    )
                ],
            )

        if event_type == "text-delta":
            text = self._extract_delta_text(event)
            if text is None:
                return None
            return ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(content=text),
                        finish_reason=None,
                    )
                ],
            )

        if event_type == "reasoning-delta":
            text = self._extract_delta_text(event)
            if text is None:
                return None
            return ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(reasoning_content=text),
                        finish_reason=None,
                    )
                ],
            )

        if event_type == "finish":
            return ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(),
                        finish_reason="stop",
                    )
                ],
            )

        # "done" and unknown types — return None (caller handles "done")
        return None

    async def _stream_sse_events(
        self,
        client: httpx.AsyncClient,
        cookies: str,
        body: dict,
        thread_id: str,
        completion_id: str,
        created: int,
        model: str,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Convert T3 SSE events into OpenAI-compatible streaming chunks."""
        async for event_type, event in self._iter_t3_sse(client, cookies, body, thread_id):
            chunk = self._event_to_chunk(event_type, event, completion_id, created, model)
            if chunk is not None:
                yield chunk
            if event_type in ("error", "done"):
                return

    async def _stream_with_tool_parsing(
        self,
        event_iter: AsyncIterator[tuple[str, dict | None]],
        completion_id: str,
        created: int,
        model: str,
        has_tools: bool,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Wrap SSE event iteration with tool call detection.

        When has_tools is False, passes through unchanged (no overhead).
        When True, feeds text-delta events through ToolCallStreamParser to
        detect <tool_call> XML and emit structured tool_calls chunks.
        """
        if not has_tools:
            async for event_type, event in event_iter:
                chunk = self._event_to_chunk(event_type, event, completion_id, created, model)
                if chunk is not None:
                    yield chunk
                if event_type in ("error", "done"):
                    return
            return

        parser = ToolCallStreamParser()

        async for event_type, event in event_iter:
            if event_type == "text-delta":
                text = self._extract_delta_text(event)
                if text is None:
                    continue
                for action_type, action_value in parser.feed(text):
                    if action_type == "content":
                        yield ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=model,
                            choices=[
                                ChatCompletionChunkChoice(
                                    index=0,
                                    delta=ChatCompletionChunkDelta(content=action_value),
                                    finish_reason=None,
                                )
                            ],
                        )
                    elif action_type == "tool_call":
                        tc = action_value
                        yield ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=model,
                            choices=[
                                ChatCompletionChunkChoice(
                                    index=0,
                                    delta=ChatCompletionChunkDelta(
                                        tool_calls=[
                                            {
                                                "index": parser._tool_call_count - 1,
                                                "id": parser.generate_tool_call_id(),
                                                "type": "function",
                                                "function": {
                                                    "name": tc.name,
                                                    "arguments": tc.arguments,
                                                },
                                            }
                                        ]
                                    ),
                                    finish_reason=None,
                                )
                            ],
                        )

            elif event_type == "finish":
                # Flush any remaining buffered text
                for action_type, action_value in parser.flush():
                    if action_type == "content":
                        yield ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=model,
                            choices=[
                                ChatCompletionChunkChoice(
                                    index=0,
                                    delta=ChatCompletionChunkDelta(content=action_value),
                                    finish_reason=None,
                                )
                            ],
                        )

                finish_reason = "tool_calls" if parser.has_tool_calls else "stop"
                yield ChatCompletionChunk(
                    id=completion_id,
                    created=created,
                    model=model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(),
                            finish_reason=finish_reason,
                        )
                    ],
                )

            elif event_type in ("error", "done"):
                if event_type == "error":
                    chunk = self._event_to_chunk(event_type, event, completion_id, created, model)
                    if chunk:
                        yield chunk
                return

            else:
                # reasoning-delta and other events pass through unchanged
                chunk = self._event_to_chunk(event_type, event, completion_id, created, model)
                if chunk is not None:
                    yield chunk

    async def chat_completion_stream(
        self, request: ChatCompletionRequest, credentials: dict
    ) -> AsyncIterator[ChatCompletionChunk]:
        cookies, convex_session_id = self._validate_credentials(credentials)
        thread_id = str(uuid4())
        has_tools = bool((request.model_extra or {}).get("tools"))

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10),
            headers=BROWSER_HEADERS,
        ) as client:
            cookies = await self._refresh_session(client, cookies)

            # If this model previously required BYOK at the default tier,
            # go straight to "low" (unless the request explicitly set one).
            reasoning_override = None
            extra = request.model_extra or {}
            if request.model in self._byok_models and not extra.get("reasoning_effort"):
                reasoning_override = "low"

            body = self._build_t3_request_body(
                request, convex_session_id, thread_id,
                reasoning_override=reasoning_override,
            )
            completion_id = f"chatcmpl-{uuid4().hex[:24]}"
            created = int(time.time())

            # Peek at first event for BYOK error detection
            event_iter = self._iter_t3_sse(client, cookies, body, thread_id)
            first_event_type = None
            first_event = None

            async for et, ev in event_iter:
                first_event_type, first_event = et, ev
                break

            if first_event_type == "error":
                msg = first_event.get("message", "")
                if self._is_byok_error(msg) and reasoning_override is None:
                    self._byok_models.add(request.model)
                    logger.warning(
                        "Model %s requires BYOK at current reasoning tier, "
                        "retrying with low reasoning",
                        request.model,
                    )
                    retry_body = self._build_t3_request_body(
                        request, convex_session_id, thread_id,
                        reasoning_override="low",
                    )
                    retry_iter = self._iter_t3_sse(client, cookies, retry_body, thread_id)
                    async for chunk in self._stream_with_tool_parsing(
                        retry_iter, completion_id, created, request.model, has_tools
                    ):
                        yield chunk
                    return

            # Re-inject the first event into the stream
            async def _prepend_first():
                if first_event_type is not None:
                    yield (first_event_type, first_event)
                async for et, ev in event_iter:
                    yield (et, ev)

            async for chunk in self._stream_with_tool_parsing(
                _prepend_first(), completion_id, created, request.model, has_tools
            ):
                yield chunk

    def _extract_delta_text(self, event: dict) -> str | None:
        delta = event.get("delta")
        if isinstance(delta, str):
            return delta
        if isinstance(delta, dict):
            return delta.get("text")
        return None

    async def chat_completion(
        self, request: ChatCompletionRequest, credentials: dict
    ) -> ChatCompletionResponse:
        accumulated_text = ""
        accumulated_tool_calls: list[dict] = []
        finish_reason = "stop"
        completion_id = f"chatcmpl-{uuid4().hex[:24]}"

        async for chunk in self.chat_completion_stream(request, credentials):
            for choice in chunk.choices:
                if choice.delta.content:
                    accumulated_text += choice.delta.content
                if choice.delta.tool_calls:
                    accumulated_tool_calls.extend(choice.delta.tool_calls)
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

        return ChatCompletionResponse(
            id=completion_id,
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=accumulated_text if accumulated_text else None,
                        tool_calls=accumulated_tool_calls if accumulated_tool_calls else None,
                    ),
                    finish_reason=finish_reason,
                )
            ],
            usage=None,
        )
