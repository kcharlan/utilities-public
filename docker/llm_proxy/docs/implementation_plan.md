# LLM Proxy - Implementation Plan

**Date**: 2026-02-22
**Prereqs**: Python 3.12+, Docker

---

## Phase 1: Project Scaffolding

### Step 1.1: Create `pyproject.toml`

**File**: `pyproject.toml`

```toml
[project]
name = "llm-proxy"
version = "0.1.0"
description = "Modular OpenAI-compatible proxy for non-standard LLM providers"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "httpx>=0.28.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.7.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.25.0",
    "pytest-httpx>=0.35.0",
    "ruff>=0.9.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.backends"

[tool.hatch.build.targets.wheel]
packages = ["src/llm_proxy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100
```

### Step 1.2: Create package structure

Create all directories and `__init__.py` files:

```
mkdir -p src/llm_proxy/providers
mkdir -p tests/providers
mkdir -p scripts
mkdir -p output
touch src/llm_proxy/__init__.py
touch src/llm_proxy/providers/__init__.py
touch tests/__init__.py
touch tests/providers/__init__.py
```

### Step 1.3: Create `.gitignore`

**File**: `.gitignore`

```
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
.ruff_cache/
.pytest_cache/
output/
.env
```

### Step 1.4: Create `.dockerignore`

**File**: `.dockerignore`

```
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
.ruff_cache/
.pytest_cache/
output/
docs/
tests/
.git/
.gitignore
README.md
```

---

## Phase 2: Core Data Models

### Step 2.1: Create Pydantic models for OpenAI request/response

**File**: `src/llm_proxy/models.py`

Define these Pydantic models. Each model must match the OpenAI API spec exactly because OpenCode's `openai-compat` type sends and expects this format.

**`ChatMessage`**:
- `role`: `Literal["system", "user", "assistant", "tool"]`
- `content`: `str | list[dict] | None = None`
- `name`: `str | None = None`
- `tool_calls`: `list[dict] | None = None`
- `tool_call_id`: `str | None = None`

**`ChatCompletionRequest`**:
- `model`: `str` (required)
- `messages`: `list[ChatMessage]` (required)
- `stream`: `bool = False`
- `temperature`: `float | None = None`
- `max_tokens`: `int | None = None`
- `top_p`: `float | None = None`
- `stop`: `str | list[str] | None = None`
- `frequency_penalty`: `float | None = None`
- `presence_penalty`: `float | None = None`
- `n`: `int | None = None`
- Use `model_config = ConfigDict(extra="allow")` to accept additional fields OpenCode may send (like `reasoning_effort`, etc.) without rejecting the request.

**`ChatCompletionChoice`**:
- `index`: `int`
- `message`: `ChatMessage`
- `finish_reason`: `str | None`

**`Usage`**:
- `prompt_tokens`: `int`
- `completion_tokens`: `int`
- `total_tokens`: `int`

**`ChatCompletionResponse`**:
- `id`: `str`
- `object`: `Literal["chat.completion"] = "chat.completion"`
- `created`: `int`
- `model`: `str`
- `choices`: `list[ChatCompletionChoice]`
- `usage`: `Usage | None = None`

**`ChatCompletionChunkDelta`**:
- `role`: `str | None = None`
- `content`: `str | None = None`
- `reasoning_content`: `str | None = None`

**`ChatCompletionChunkChoice`**:
- `index`: `int`
- `delta`: `ChatCompletionChunkDelta`
- `finish_reason`: `str | None = None`

**`ChatCompletionChunk`**:
- `id`: `str`
- `object`: `Literal["chat.completion.chunk"] = "chat.completion.chunk"`
- `created`: `int`
- `model`: `str`
- `choices`: `list[ChatCompletionChunkChoice]`

**`ModelObject`**:
- `id`: `str`
- `object`: `Literal["model"] = "model"`
- `created`: `int`
- `owned_by`: `str`

**`ModelListResponse`**:
- `object`: `Literal["list"] = "list"`
- `data`: `list[ModelObject]`

---

## Phase 3: Auth and Config

### Step 3.1: Create config module

**File**: `src/llm_proxy/config.py`

Use `pydantic-settings` `BaseSettings` class:

```python
class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 4141
    log_level: str = "info"
    output_dir: str = "/output"
```

Create a module-level `settings = Settings()` singleton.

The `output_dir` setting controls where the OpenCode config JSON and update script are written. Default is `/output` (the Docker volume mount point). Can be overridden via `OUTPUT_DIR` env var.

### Step 3.2: Create auth module

**File**: `src/llm_proxy/auth.py`

This module decodes credentials from the `Authorization: Bearer <token>` header.

**Function `decode_credentials(authorization: str) -> dict`**:
1. Strip the `Bearer ` prefix (case-insensitive match on "Bearer")
2. Base64-decode the remaining string
3. Parse as JSON
4. Return the resulting dict
5. Raise `HTTPException(401)` with message `"Invalid credentials format"` if any step fails (invalid base64, invalid JSON, missing header)

**Function `extract_authorization(request: Request) -> str`**:
1. Get the `Authorization` header from the request
2. If missing, raise `HTTPException(401)` with message `"Missing Authorization header"`
3. Return the header value

These will be used as FastAPI dependencies.

---

## Phase 4: Provider Adapter System

### Step 4.1: Create abstract base class

**File**: `src/llm_proxy/provider_base.py`

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from llm_proxy.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChunk,
    ModelObject,
    ModelListResponse,
)
from llm_proxy.auth import extract_authorization, decode_credentials


class ProviderAdapter(ABC):

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """URL path prefix and unique identifier, e.g. 't3chat'.
        The adapter will be mounted at /{provider_id}/v1/"""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. 'T3 Chat'."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """Called once at startup. Use for model discovery, connection
        setup, or any async initialization."""
        ...

    @abstractmethod
    def get_models(self) -> list[ModelObject]:
        """Return list of models in OpenAI ModelObject format."""
        ...

    @abstractmethod
    def get_opencode_model_config(self) -> list[dict]:
        """Return list of model dicts in OpenCode config format.
        Each dict has: id, name, can_reason, supports_attachments,
        context_window, default_max_tokens, cost_per_1m_in,
        cost_per_1m_out, cost_per_1m_in_cached, cost_per_1m_out_cached."""
        ...

    @abstractmethod
    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> ChatCompletionResponse:
        """Execute a non-streaming chat completion."""
        ...

    @abstractmethod
    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Execute a streaming chat completion."""
        ...

    def create_router(self) -> APIRouter:
        """Creates the FastAPI router with /v1/chat/completions and /v1/models.
        Subclasses can override to add provider-specific routes."""
        router = APIRouter()
        adapter = self

        @router.post("/v1/chat/completions")
        async def chat_completions(request: Request):
            # 1. Parse request body as ChatCompletionRequest
            # 2. Extract and decode credentials from Authorization header
            # 3. If request.stream: call adapter.chat_completion_stream(),
            #    return StreamingResponse with SSE format
            # 4. Else: call adapter.chat_completion(), return JSON
            ...

        @router.get("/v1/models")
        async def list_models():
            models = adapter.get_models()
            return ModelListResponse(data=models)

        return router
```

The `create_router()` method provides the default implementation. The `chat_completions` endpoint handles both streaming and non-streaming requests. Streaming returns a `StreamingResponse` with `media_type="text/event-stream"` that:
- For each `ChatCompletionChunk`, writes `data: {chunk.model_dump_json()}\n\n`
- After all chunks, writes `data: [DONE]\n\n`
- Sets headers: `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`

### Step 4.2: Create provider registry

**File**: `src/llm_proxy/provider_registry.py`

**Class `ProviderRegistry`**:
- `__init__(self)`: Initialize `self._adapters: dict[str, ProviderAdapter] = {}`
- `register(self, adapter: ProviderAdapter)`: Add adapter to `self._adapters` keyed by `adapter.provider_id`. Log at INFO: `"Registered provider: {adapter.display_name} ({adapter.provider_id}) with {n} models"`
- `get_adapter(self, provider_id: str) -> ProviderAdapter | None`: Return adapter by ID.
- `get_all_adapters(self) -> list[ProviderAdapter]`: Return all registered adapters.

**Function `async discover_and_register_providers(app: FastAPI) -> ProviderRegistry`**:
1. Create a new `ProviderRegistry` instance
2. Import the `llm_proxy.providers` package
3. Use `importlib` and `pkgutil.iter_modules()` on the `llm_proxy.providers` package path to find all submodules
4. For each submodule, import it
5. Inspect all attributes using `inspect.getmembers()`
6. For each class that is a subclass of `ProviderAdapter` and is NOT `ProviderAdapter` itself:
   - Instantiate with `cls()`
   - Call `await adapter.initialize()` (model discovery happens here)
   - Call `adapter.create_router()` to get the FastAPI router
   - Mount the router on the FastAPI app at `/{adapter.provider_id}` prefix using `app.include_router(router, prefix=f"/{adapter.provider_id}")`
   - Call `registry.register(adapter)`
7. Return the registry

---

## Phase 5: T3.chat Provider Adapter

### Step 5.1: Create T3 adapter — constants and model discovery

**File**: `src/llm_proxy/providers/t3chat.py`

This is the largest file. It handles: model discovery, request translation, SSE stream translation.

**Module-level constants**:

```python
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

# Hardcoded fallback if dynamic discovery fails.
# Source: HAR capture + t3router fallback list + T3.chat UI (2026-02-22).
FALLBACK_MODELS = [
    {"id": "gemini-3-flash", "name": "Gemini 3 Flash", "owned_by": "google", "can_reason": False},
    {"id": "gemini-3-flash-thinking", "name": "Gemini 3 Flash Thinking", "owned_by": "google", "can_reason": True},
    {"id": "gemini-3.1-pro", "name": "Gemini 3.1 Pro", "owned_by": "google", "can_reason": True},
    {"id": "claude-4.6-opus", "name": "Claude 4.6 Opus", "owned_by": "anthropic", "can_reason": True},
    {"id": "claude-4.6-sonnet", "name": "Claude 4.6 Sonnet", "owned_by": "anthropic", "can_reason": True},
    {"id": "gpt-5.2-reasoning", "name": "GPT 5.2 Reasoning", "owned_by": "openai", "can_reason": True},
    {"id": "gpt-5.2-instant", "name": "GPT 5.2 Instant", "owned_by": "openai", "can_reason": False},
    {"id": "grok-4.1-fast", "name": "Grok 4.1 Fast", "owned_by": "xai", "can_reason": False},
    {"id": "grok-4.1-fast-reasoning", "name": "Grok 4.1 Fast Reasoning", "owned_by": "xai", "can_reason": True},
    {"id": "kimi-k2.5", "name": "Kimi K2.5", "owned_by": "moonshot", "can_reason": False},
    {"id": "kimi-k2.5-thinking", "name": "Kimi K2.5 Thinking", "owned_by": "moonshot", "can_reason": True},
    {"id": "deepseek-r1", "name": "DeepSeek R1", "owned_by": "deepseek", "can_reason": True},
    {"id": "deepseek-v3", "name": "DeepSeek V3", "owned_by": "deepseek", "can_reason": False},
]
```

**Class `T3ChatAdapter(ProviderAdapter)`**:

**Instance variable**: `self._models: list[dict] = []` — populated during `initialize()`.

**Properties**:
- `provider_id` → `"t3chat"`
- `display_name` → `"T3 Chat"`

**Method `async initialize(self) -> None`**:

Performs dynamic model discovery by scraping T3.chat's frontend JavaScript bundles. Based on the approach proven in t3router (`models.rs:53-193`).

1. Create an `httpx.AsyncClient` with `BROWSER_HEADERS` as default headers and a 30-second timeout
2. **Try fetching the T3.chat homepage** (`GET https://t3.chat/`)
3. Parse the HTML response to find all `<script>` tags with `src` attributes containing `/_next/static/chunks/`
   - Use regex: `r'<script[^>]+src="(/_next/static/chunks/[a-f0-9]+\.js[^"]*)"'`
   - Build full URLs: `https://t3.chat{path}`
4. **For each chunk URL**, download the JS content and attempt to parse model definitions:
   - Search for a model list pattern: `r'let\s+\w+\s*=\s*\[((?:"[^"]+",?\s*)+)\]'` to find arrays of model ID strings
   - If found, extract individual model IDs: `r'"([^"]+)"'`
   - For each model ID, search for its definition block using a regex like:
     `r'"{model_id}":\s*\{{.*?id:\s*"([^"]+)"(?:.*?name:\s*"([^"]+)")?(?:.*?provider:\s*"([^"]+)")?(?:.*?developer:\s*"([^"]+)")?'` (with `re.DOTALL`)
   - Build model dicts: `{"id": ..., "name": ..., "owned_by": provider or developer, "can_reason": "thinking" in id or "reasoning" in id}`
   - If more than 10 models are found from a chunk, accept this chunk's results and stop (same threshold as t3router)
5. If discovery succeeds, set `self._models` to the discovered list
6. If discovery fails (no chunks found, no models parsed, network error, etc.):
   - Log a WARNING: `"T3 model discovery failed, using fallback list: {error}"`
   - Set `self._models = FALLBACK_MODELS`
7. Log INFO: `"T3 Chat: discovered {len(self._models)} models"`

**Method `get_models(self) -> list[ModelObject]`**:
- Return `[ModelObject(id=m["id"], created=0, owned_by=m.get("owned_by", "t3chat")) for m in self._models]`

**Method `get_opencode_model_config(self) -> list[dict]`**:
- Return a list of dicts, one per model, in OpenCode's config format:
```python
[
    {
        "id": m["id"],
        "name": m.get("name", m["id"]),
        "can_reason": m.get("can_reason", False),
        "supports_attachments": False,
        "context_window": 200000,  # safe default
        "default_max_tokens": 16000,
        "cost_per_1m_in": 0,
        "cost_per_1m_out": 0,
        "cost_per_1m_in_cached": 0,
        "cost_per_1m_out_cached": 0,
    }
    for m in self._models
]
```

### Step 5.2: Create T3 adapter — credential validation and session refresh

Continue in `src/llm_proxy/providers/t3chat.py`:

**Method `_validate_credentials(self, credentials: dict) -> tuple[str, str]`**:
- Extract `credentials.get("cookies")` and `credentials.get("convex_session_id")`
- If either is missing or empty, raise `HTTPException(401, "T3 credentials must include 'cookies' and 'convex_session_id'")`
- Return `(cookies, convex_session_id)`

**Method `async _refresh_session(self, client: httpx.AsyncClient, cookies: str) -> str`**:
- Send `GET` to `T3_SESSION_REFRESH_URL` with:
  - `Cookie: {cookies}`
  - `Content-Type: application/json`
  - `trpc-accept: application/jsonl`
- If response has `x-workos-session` header with a non-empty value:
  - Parse the cookie string, split on `; `
  - Remove any segment starting with `wos-session=`
  - Append `wos-session={new_value}`
  - Rejoin with `; ` and return the updated cookie string
- On any error (network, non-2xx status, etc.): log WARNING, return original cookies unchanged
- Session refresh failure must NOT prevent the chat request from proceeding

### Step 5.3: Create T3 adapter — request translation

Continue in `src/llm_proxy/providers/t3chat.py`:

**Method `_build_t3_request_body(self, request: ChatCompletionRequest, convex_session_id: str, thread_id: str) -> dict`**:

1. Generate a UUID for `responseMessageId`
2. Convert each message in `request.messages`:
   - If `content` is a string: `parts = [{"type": "text", "text": content}]`
   - If `content` is a list (multimodal): pass through as `parts`
   - If `content` is None: `parts = []`
   - Generate a UUID for each message `id`
   - Set `attachments: []`
   - Map `role` directly ("system", "user", "assistant")
3. Determine `reasoningEffort`: check `request` for extra field `reasoning_effort`. Default to `"medium"`.
4. Return:
```python
{
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
```

Note: `isEphemeral: True` avoids creating persistent threads in T3's Convex backend.

### Step 5.4: Create T3 adapter — SSE streaming and response

Continue in `src/llm_proxy/providers/t3chat.py`:

**Method `async _iter_t3_sse(self, client: httpx.AsyncClient, cookies: str, body: dict, thread_id: str) -> AsyncIterator[tuple[str, dict | None]]`**:

Private async generator that yields `(event_type, parsed_data)` tuples.

1. Send `POST` to `T3_CHAT_API_URL` with:
   - `Content-Type: application/json`
   - `Cookie: {cookies}`
   - `Referer: https://t3.chat/chat/{thread_id}`
   - `Accept: */*`
   - All `BROWSER_HEADERS`
   - Body: JSON-serialized `body`
   - Use `stream=True` on the httpx request
2. If response status is not 2xx, read the body and raise `HTTPException(502, f"T3.chat returned {status}: {body}")`
3. Iterate `response.aiter_lines()`:
   - Skip empty lines
   - For lines starting with `data: `:
     - Strip the `data: ` prefix
     - If data is `[DONE]`: yield `("done", None)` and return
     - Try to parse as JSON
     - Extract the `type` field
     - Yield `(type_str, parsed_dict)`
   - For lines that don't start with `data: `: skip

**Method `async chat_completion_stream(self, request, credentials) -> AsyncIterator[ChatCompletionChunk]`**:

1. `cookies, convex_session_id = self._validate_credentials(credentials)`
2. `thread_id = str(uuid4())`
3. Create `httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10), headers=BROWSER_HEADERS)`
   - Read timeout 300s for slow reasoning models
4. `cookies = await self._refresh_session(client, cookies)`
5. `body = self._build_t3_request_body(request, convex_session_id, thread_id)`
6. `completion_id = f"chatcmpl-{uuid4().hex[:24]}"`
7. `created = int(time.time())`
8. Iterate `self._iter_t3_sse(client, cookies, body, thread_id)`:
   - `type == "text-delta"`:
     - Extract text: try `event.get("delta")` — if string use directly, if dict try `event["delta"]["text"]`, else skip
     - Yield `ChatCompletionChunk` with `delta.content = text`, `finish_reason = None`
   - `type == "reasoning-delta"`:
     - Extract text same way as text-delta
     - Yield `ChatCompletionChunk` with `delta.reasoning_content = text`, `finish_reason = None`
   - `type == "finish"`:
     - Yield `ChatCompletionChunk` with empty delta, `finish_reason = "stop"`
   - `type == "done"`:
     - Return (stop iteration)
   - All other types: skip

**Method `async chat_completion(self, request, credentials) -> ChatCompletionResponse`**:

1. Accumulate text from `chat_completion_stream()` by concatenating all `delta.content` values
2. Build `ChatCompletionResponse`:
   - `id`: completion_id (generate one here)
   - `model`: `request.model`
   - `choices`: single choice with `message.role = "assistant"`, `message.content = accumulated_text`, `finish_reason = "stop"`
   - `usage`: `None` (T3 does not return token counts)

---

## Phase 6: OpenCode Config Generator

### Step 6.1: Create config generator module

**File**: `src/llm_proxy/config_generator.py`

This module is called after all adapters are initialized. It writes two files to the output directory for each registered adapter.

**Function `generate_opencode_configs(registry: ProviderRegistry, output_dir: str) -> None`**:

For each adapter in `registry.get_all_adapters()`:

1. **Generate the provider JSON file** (`{output_dir}/opencode_provider_{adapter.provider_id}.json`):

```python
provider_config = {
    adapter.provider_id: {
        "name": adapter.display_name,
        "base_url": f"http://localhost:4141/{adapter.provider_id}/v1",
        "type": "openai-compat",
        "api_key": f"${adapter.provider_id.upper()}_CREDS",
        "models": adapter.get_opencode_model_config(),
    }
}
```

Write as pretty-printed JSON (indent=2).

2. **Generate the update script** (`{output_dir}/update_opencode_config.sh`):

Write a bash script with these behaviors:
- `#!/usr/bin/env bash` with `set -euo pipefail`
- Determines its own directory via `SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"`
- Accepts optional argument for target `opencode.json` path; defaults to `~/.config/opencode/opencode.json`
- Uses Python (available on macOS) to merge: reads the generated JSON file from `$SCRIPT_DIR`, reads the target `opencode.json` (or creates `{"providers": {}}`), merges the provider entry under the `providers` key, writes back
- Preserves all other providers and config keys in the target file
- Prints a summary: which provider was updated, how many models, target file path
- Make the script executable (`chmod +x`)

3. Log INFO: `"Wrote OpenCode config for {adapter.display_name} to {output_dir}/"`

**Important**: The output directory may not exist at startup (first run before Docker volume is populated). Create it with `os.makedirs(output_dir, exist_ok=True)`.

---

## Phase 7: FastAPI Application

### Step 7.1: Create the main app

**File**: `src/llm_proxy/main.py`

```python
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from llm_proxy.config import settings
from llm_proxy.provider_registry import discover_and_register_providers, ProviderRegistry
from llm_proxy.config_generator import generate_opencode_configs

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)

registry: ProviderRegistry | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry
    registry = await discover_and_register_providers(app)
    adapters = registry.get_all_adapters()
    total_models = sum(len(a.get_models()) for a in adapters)
    logger.info(
        f"LLM Proxy started: {len(adapters)} providers, {total_models} models"
    )
    # Generate OpenCode config files to output directory
    generate_opencode_configs(registry, settings.output_dir)
    yield


app = FastAPI(title="LLM Proxy", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/providers")
async def list_providers():
    if registry is None:
        return {"providers": []}
    return {
        "providers": [
            {
                "id": a.provider_id,
                "name": a.display_name,
                "models": len(a.get_models()),
                "base_path": f"/{a.provider_id}/v1",
            }
            for a in registry.get_all_adapters()
        ]
    }
```

Use FastAPI's `lifespan` context manager (not the deprecated `@app.on_event("startup")`).

**Entrypoint** (bottom of `main.py`):
```python
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)
```

---

## Phase 8: Docker

### Step 8.1: Create Dockerfile

**File**: `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/

EXPOSE 4141

CMD ["uvicorn", "llm_proxy.main:app", "--host", "0.0.0.0", "--port", "4141"]
```

### Step 8.2: Create docker-compose.yml

**File**: `docker-compose.yml`

```yaml
services:
  llm-proxy:
    build: .
    ports:
      - "4141:4141"
    volumes:
      - ./output:/output
    restart: unless-stopped
```

The `./output` directory on the host is mounted to `/output` inside the container. On every container start, the OpenCode config JSON and update script are written there.

---

## Phase 9: Helper Scripts

### Step 9.1: Create cURL-based credential extractor (primary method)

**File**: `scripts/extract_from_curl.sh`

This is the recommended method. The user copies a request as cURL from DevTools and pastes it. The script parses out both credentials.

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== T3.chat Credential Extractor (from cURL) ==="
echo ""
echo "Steps to get your cURL command:"
echo "  1. Open https://t3.chat in Chrome and log in"
echo "  2. Open DevTools: press F12 (or Cmd+Option+I on Mac)"
echo "  3. Click the Network tab"
echo "  4. In the filter bar, type:  /api/chat"
echo "  5. Send any message in T3.chat (e.g. type 'hello' and press Enter)"
echo "  6. A 'chat' entry appears in the Network tab"
echo "  7. Right-click the 'chat' entry → Copy → Copy as cURL"
echo ""
echo "Paste your cURL command below, then press Enter and Ctrl+D:"
echo ""

curl_cmd=$(cat)

# Chrome uses -b for cookies, not -H 'Cookie: ...'
# Try -b first (Chrome default), then -H Cookie as fallback
cookies=$(echo "$curl_cmd" | grep -oP "(?<=-b ')[^']*" || \
          echo "$curl_cmd" | grep -oP '(?<=-b ")[^"]*' || \
          echo "$curl_cmd" | grep -oP "(?<=-H 'Cookie: )[^']*" || \
          echo "$curl_cmd" | grep -oP '(?<=-H "Cookie: )[^"]*' || \
          echo "")

if [ -z "$cookies" ]; then
    echo "ERROR: Could not find cookies in cURL command."
    echo "Expected -b '...' or -H 'Cookie: ...' flag."
    echo "Make sure you copied the full cURL command from DevTools."
    exit 1
fi

# convex-session-id is available both as a cookie AND in the JSON body.
# Extract from cookies first (more reliable), fall back to body.
convex_session_id=$(echo "$cookies" | \
    grep -oP '(?<=convex-session-id=)[^;]+' || \
    echo "$curl_cmd" | grep -oP '(?<="convexSessionId":")[^"]*' || \
    echo "")

if [ -z "$convex_session_id" ]; then
    echo "ERROR: Could not find convex-session-id in cookies or body."
    exit 1
fi

# Build and encode credentials
json=$(printf '{"cookies":"%s","convex_session_id":"%s"}' "$cookies" "$convex_session_id")
encoded=$(echo -n "$json" | base64)

echo ""
echo "=== Success! ==="
echo ""
echo "Cookie: ${cookies:0:60}..."
echo "convexSessionId: $convex_session_id"
echo ""
echo "Add this to your shell profile (~/.zshrc or ~/.bashrc):"
echo ""
echo "export T3_CHAT_CREDS='$encoded'"
```

Make executable: `chmod +x scripts/extract_from_curl.sh`

### Step 9.2: Create manual credential encoder (fallback method)

**File**: `scripts/extract_t3_creds.sh`

For users who prefer to copy values individually from DevTools:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== T3.chat Manual Credential Encoder ==="
echo ""
echo "Finding the Cookie string:"
echo "  1. Open https://t3.chat → DevTools (F12) → Network tab"
echo "  2. Filter for '/api/chat', send a message"
echo "  3. Click the 'chat' entry → Headers tab"
echo "  4. Scroll to 'Request Headers' section"
echo "  5. Find 'Cookie:' — copy its full value"
echo ""
read -r -p "Paste Cookie value: " cookies
echo ""
echo "Finding the convexSessionId:"
echo "  1. Same 'chat' entry → click the Payload tab"
echo "  2. Find 'convexSessionId' in the tree"
echo "  3. Copy the UUID value"
echo ""
read -r -p "Paste convexSessionId: " convex_session_id
echo ""

json=$(printf '{"cookies":"%s","convex_session_id":"%s"}' "$cookies" "$convex_session_id")
encoded=$(echo -n "$json" | base64)

echo "=== Your T3_CHAT_CREDS ==="
echo ""
echo "export T3_CHAT_CREDS='$encoded'"
echo ""
echo "Add this to ~/.zshrc or ~/.bashrc"
```

Make executable: `chmod +x scripts/extract_t3_creds.sh`

### Step 9.3: Create bookmarklet HTML (generated at runtime)

The config generator (Phase 6, `config_generator.py`) also writes a bookmarklet HTML file to the output directory. This is NOT a separate script to create — it is generated by the `generate_opencode_configs()` function.

**File generated at runtime**: `{output_dir}/t3chat_bookmarklet.html`

The HTML file contains:
1. A draggable bookmarklet link
2. Instructions for use
3. The bookmarklet JavaScript that:
   - Monkey-patches `window.fetch` to intercept the next `/api/chat` POST
   - Extracts `convexSessionId` from the request body JSON
   - Cannot reliably access httpOnly cookies from JS — so it prompts the user to also paste their Cookie header from DevTools
   - Combines both values, base64-encodes, copies to clipboard
   - Shows an alert with the result and the `export` command
   - Restores the original `fetch` after one interception

Add this to the `generate_opencode_configs()` function in `config_generator.py`: after writing the JSON and shell script, also write `t3chat_bookmarklet.html`.

Both helper scripts (`extract_from_curl.sh` and `extract_t3_creds.sh`) live in the repo's `scripts/` directory. They are NOT baked into the Docker image.

---

## Phase 10: Tests

### Step 10.1: Test auth module

**File**: `tests/test_auth.py`

Test cases:
1. `decode_credentials` with valid base64 JSON → returns dict
2. `decode_credentials` with invalid base64 → raises 401
3. `decode_credentials` with valid base64 but invalid JSON → raises 401
4. `decode_credentials` with missing `Bearer ` prefix → raises 401
5. `extract_authorization` with missing header → raises 401
6. `extract_authorization` with valid header → returns header value

### Step 10.2: Test models

**File**: `tests/test_models.py`

Test cases:
1. `ChatCompletionRequest` accepts valid minimal request (model + messages)
2. `ChatCompletionRequest` accepts extra fields without error (`extra="allow"`)
3. `ChatCompletionChunk` serializes to correct JSON shape
4. `ChatCompletionResponse` serializes to correct JSON shape
5. `ModelListResponse` serializes correctly

### Step 10.3: Test T3 adapter

**File**: `tests/providers/test_t3chat.py`

Test cases:
1. `provider_id` returns `"t3chat"`
2. After `initialize()` with mocked successful scrape: `get_models()` returns discovered models
3. After `initialize()` with mocked failed scrape: `get_models()` returns fallback models
4. `_validate_credentials({})` raises 401
5. `_validate_credentials({"cookies": "...", "convex_session_id": "..."})` returns tuple
6. `_build_t3_request_body()` produces correct structure:
   - Messages converted to `parts` format
   - `convexSessionId` set correctly
   - `model` matches request
   - `isEphemeral` is True
7. `get_opencode_model_config()` returns list of dicts with all required OpenCode fields
8. Mock SSE stream tests for `chat_completion_stream()`:
   - Feed `text-delta` events → verify yielded chunks have `delta.content`
   - Feed `reasoning-delta` events → verify `delta.reasoning_content`
   - Feed `finish` → verify `finish_reason = "stop"`
   - Feed `[DONE]` → verify iteration stops
9. Mock SSE stream test for `chat_completion()`:
   - Verify accumulated text is correct
   - Verify response shape matches `ChatCompletionResponse`

Use `pytest-httpx` to mock httpx requests. Create fixture data based on actual HAR capture SSE events.

### Step 10.4: Test config generator

**File**: `tests/test_config_generator.py`

Test cases:
1. `generate_opencode_configs()` creates JSON file with correct structure
2. `generate_opencode_configs()` creates executable shell script
3. Generated JSON contains all models from adapter
4. Generated JSON has correct `base_url` with provider_id prefix
5. Output directory is created if it doesn't exist

---

## Phase 11: Integration Testing

**Important**: All non-Docker testing and execution MUST use a Python virtual environment. The host environment is Homebrew-managed and libraries must not be installed globally.

### Step 11.1: Create virtual environment and run all tests

```bash
cd llm_proxy
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

All tests must pass.

### Step 11.2: Build and start container

```bash
docker compose build
docker compose up -d
docker compose logs -f  # verify startup, model discovery
```

### Step 11.3: Verify output files

```bash
ls -la output/
cat output/opencode_provider_t3chat.json  # verify model list
cat output/update_opencode_config.sh      # verify script
```

### Step 11.4: Smoke test endpoints

```bash
# Health check
curl http://localhost:4141/health

# Provider list
curl http://localhost:4141/providers

# Model list
curl http://localhost:4141/t3chat/v1/models

# Chat (requires real T3 credentials)
export T3_CHAT_CREDS=$(echo -n '{"cookies":"YOUR_COOKIES","convex_session_id":"YOUR_SESSION_ID"}' | base64)

curl -X POST http://localhost:4141/t3chat/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $T3_CHAT_CREDS" \
  -d '{
    "model": "gemini-3-flash",
    "messages": [{"role": "user", "content": "Say hello in one sentence."}],
    "stream": true
  }'
```

### Step 11.5: Sync models to OpenCode

```bash
cd output
./update_opencode_config.sh
# Verify:
cat ~/.config/opencode/opencode.json | python3 -m json.tool
```

### Step 11.6: OpenCode integration test

1. Restart OpenCode
2. Run `opencode models t3chat` — verify models appear
3. Launch `opencode`, select `t3chat/gemini-3-flash`
4. Send a message, verify streaming response

---

## File Creation Order

To respect dependencies between files, create them in this order:

1. `pyproject.toml` + directory structure + `__init__.py` files + `.gitignore` + `.dockerignore`
2. `src/llm_proxy/config.py` (no internal deps)
3. `src/llm_proxy/models.py` (no internal deps)
4. `src/llm_proxy/auth.py` (no internal deps)
5. `src/llm_proxy/provider_base.py` (depends on `models.py`, `auth.py`)
6. `src/llm_proxy/provider_registry.py` (depends on `provider_base.py`)
7. `src/llm_proxy/providers/t3chat.py` (depends on `provider_base.py`, `models.py`)
8. `src/llm_proxy/config_generator.py` (depends on `provider_registry.py`)
9. `src/llm_proxy/main.py` (depends on `config.py`, `provider_registry.py`, `config_generator.py`)
10. `Dockerfile` + `docker-compose.yml`
11. `scripts/extract_t3_creds.sh`
12. Tests (all files)

## Dependency Summary

| Package | Version | Purpose |
|---|---|---|
| fastapi | >=0.115.0 | Web framework, SSE streaming |
| uvicorn[standard] | >=0.34.0 | ASGI server |
| httpx | >=0.28.0 | Async HTTP client with streaming |
| pydantic | >=2.10.0 | Request/response models |
| pydantic-settings | >=2.7.0 | Settings from env vars |
| pytest | >=8.0.0 | Test framework |
| pytest-asyncio | >=0.25.0 | Async test support |
| pytest-httpx | >=0.35.0 | Mock httpx requests |
| ruff | >=0.9.0 | Linter/formatter |
