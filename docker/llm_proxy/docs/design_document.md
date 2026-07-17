# LLM Proxy - Design Document

**Date**: 2026-02-22
**Status**: Draft — Revised

## 1. Problem Statement

Several LLM aggregator services provide access to many models under a single subscription but do not offer official APIs. T3.chat is the first such service we want to integrate. It provides access to 50+ models (Claude, GPT, Gemini, Grok, DeepSeek, Llama, Kimi, etc.) but only through its web interface.

We need a local proxy that:

1. Exposes these services as OpenAI-compatible API endpoints
2. Works as a custom provider in OpenCode v1.2.10
3. Is modular so new provider adapters can be added easily — T3 is the first of many
4. Does not store any authentication credentials itself
5. Runs as a single Docker container with all provider adapters baked in at build time
6. Uses path-based routing so each provider gets its own URL prefix within a single container

## 2. Prior Art and Evidence

### 2.1 T3.chat Internal API (from HAR capture analysis)

A HAR capture of a T3.chat session (2026-02-22) revealed the following:

**Chat endpoint**: `POST https://t3.chat/api/chat`

**Request body shape**:

```json
{
  "messages": [
    {
      "id": "<uuid>",
      "parts": [{"type": "text", "text": "user message"}],
      "role": "user",
      "attachments": []
    }
  ],
  "threadMetadata": {"id": "<uuid>"},
  "responseMessageId": "<uuid>",
  "model": "gemini-3-flash",
  "convexSessionId": "<uuid>",
  "modelParams": {
    "reasoningEffort": "medium",
    "includeSearch": true,
    "searchLimit": 2
  },
  "preferences": {
    "name": "", "occupation": "",
    "selectedTraits": [], "additionalInfo": ""
  },
  "userInfo": {"timezone": "America/New_York", "locale": "en-US"},
  "isEphemeral": false
}
```

**Response**: Server-Sent Events (`text/event-stream`) with these event types in order:

- `start` - Response begins, includes `messageId`
- `start-step` - Processing step begins
- `reasoning-start` / `reasoning-delta` / `reasoning-end` - Reasoning/thinking tokens (for reasoning models)
- `text-start` / `text-delta` / `text-end` - Final text output tokens
- `finish-step` / `finish` - Completion signals
- `[DONE]` - Stream termination (raw string, not JSON)

**Authentication**:

- `Cookie` header containing `wos-session=<token>` (WorkOS session, rotated periodically)
- `convexSessionId` in the request body (Convex real-time backend session)
- Browser-like headers required (User-Agent, sec-ch-ua, sec-fetch-* etc.)

**Session refresh**: The `wos-session` cookie is rotated by the server. Calling `GET /api/trpc/auth.getActiveSessions` returns a new token in the `x-workos-session` response header.

### 2.2 t3router (Rust client library)

**Source**: https://github.com/vibheksoni/t3router

An existing Rust library that programmatically accesses T3.chat by borrowing browser cookies. Key observations from the source code:

- **Auth approach**: Copies `Cookie` header string and `convex-session-id` from browser DevTools. The cookie string is sent as-is on every request.
- **Session refresh**: Calls the tRPC `auth.getActiveSessions` endpoint and replaces the `wos-session=` value in the cookie string when a new `x-workos-session` header is returned (see `client.rs:68-101`).
- **Browser impersonation**: Sets Chrome User-Agent, `sec-ch-ua`, `sec-fetch-*`, `origin`, and other headers to appear as legitimate browser traffic (see `client.rs:37-53`).
- **Request format**: Mirrors the web frontend's JSON body exactly, including `messages` array with `parts` sub-structure, `threadMetadata`, `modelParams`, etc. (see `client.rs:389-411`).
- **Response parsing**: Buffers the entire SSE response then parses `data:` lines. Extracts text from `delta` (string), `delta.text`, `text`, or `content[].text` fields. Does not stream to caller (noted as planned feature).
- **Dynamic model discovery**: Scrapes T3.chat's frontend JavaScript bundles to find model definitions. First tries a known chunk URL, then falls back to discovering all `<script>` tags from the homepage and parsing each JS file with regex to extract model IDs, names, providers, and descriptions (see `models.rs:53-193`). Falls back to a hardcoded list of 6 models if scraping fails.
- **Limitation**: Library only, not an API server. Does not expose OpenAI-compatible endpoints.

### 2.3 OpenCode Provider System

**Source**: OpenCode v1.2.10, installed via Homebrew. (Note: OpenCode was formerly known as "Crush" by Charmbracelet; the Crush name and its config schema are deprecated.)

OpenCode supports custom providers via JSON config. The provider registry at `https://catwalk.charm.sh` provides 97 known providers, cached at `~/.cache/opencode/models.json`. Custom providers are added via config file.

**Config file location** (checked in order):

1. Project-level: `opencode.json` or `.opencode.json` in working directory (walks up to root)
2. Global: `~/.config/opencode/opencode.json`

**Custom provider config format** (from OpenCode v1.2.10 schema at `https://opencode.ai/config.json` and docs at `https://opencode.ai/docs/providers/`):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "my-provider": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "My Provider",
      "options": {
        "baseURL": "http://localhost:4141/my-provider/v1",
        "apiKey": "{env:MY_PROVIDER_API_KEY}"
      },
      "models": {
        "model-id": {
          "name": "Model Name",
          "limit": {
            "context": 200000,
            "output": 16000
          }
        }
      }
    }
  }
}
```

**Key behaviors**:

- Custom OpenAI-compatible providers require `"npm": "@ai-sdk/openai-compatible"`
- `baseURL` and `apiKey` are nested under `options`
- `apiKey` supports `{env:VAR_NAME}` syntax for environment variable references
- Models are a map keyed by model ID (not an array), with `limit.context` and `limit.output`
- The top-level key is `provider` (singular), not `providers`

**Critical routing behavior**: OpenCode already distinguishes providers by `baseURL`. If you configure `t3chat` with `baseURL: http://localhost:4141/t3chat/v1` and `openrouter` with `baseURL: https://openrouter.ai/api/v1`, then selecting `t3chat/gemini-3-flash` in the OpenCode UI sends the request to the T3 proxy, while selecting `openrouter/google/gemini-3-flash` sends it to OpenRouter. The proxy does NOT need to inspect the model name to decide which adapter to use — the client has already made that choice. The URL path prefix is the routing mechanism.

**Existing provider examples** from `~/.cache/opencode/models.json`:

- Abacus: `api: https://routellm.abacus.ai/v1`, type `@ai-sdk/openai-compatible`, 55 models
- OpenRouter: `api: https://openrouter.ai/api/v1`, type `@openrouter/ai-sdk-provider`, 185 models

**Model entry structure** (from Abacus in models.json):

```json
{
  "id": "gpt-4.1-nano",
  "name": "GPT-4.1 Nano",
  "family": "gpt",
  "attachment": true,
  "reasoning": false,
  "tool_call": true,
  "temperature": true,
  "cost": {"input": 0.1, "output": 0.4},
  "limit": {"context": 1047576, "output": 32768}
}
```

## 3. Architecture

### 3.1 High-Level Design

A single Docker container runs one FastAPI server. Each provider adapter is mounted at its own path prefix. OpenCode (or any client) routes to the correct adapter by setting `base_url` to include the path prefix.

```
OpenCode provider: "t3chat"
  base_url: http://localhost:4141/t3chat/v1
      │
      │ POST /t3chat/v1/chat/completions
      │ Authorization: Bearer <base64 creds>
      ▼
┌─────────────────────────────────────────────────┐
│              LLM Proxy Container                │
│              (FastAPI, port 4141)               │
│                                                 │
│  /t3chat/v1/*    ──▶  T3ChatAdapter             │
│  /future/v1/*    ──▶  FutureAdapter             │
│  /another/v1/*   ──▶  AnotherAdapter            │
│                                                 │
│  /health         ──▶  health check              │
│  /providers      ──▶  list registered adapters  │
└────────────────────────┬────────────────────────┘
                         │
         Per-adapter upstream calls:
         │
         ├── T3ChatAdapter ──▶ POST https://t3.chat/api/chat
         ├── FutureAdapter ──▶ POST https://future.example.com/api/...
         └── ...
```

**Request flow**:

1. OpenCode sends `POST http://localhost:4141/t3chat/v1/chat/completions` with model `gemini-3-flash`
2. FastAPI routes to the T3 adapter based on the `/t3chat` path prefix
3. T3 adapter decodes credentials from the Authorization header
4. T3 adapter translates the OpenAI request to T3's native format
5. T3 adapter streams back OpenAI-compatible SSE chunks translated from T3's SSE events

There is no model-name-based routing. The path prefix is the sole routing mechanism. This mirrors how OpenCode already works: each provider has its own `base_url`, and the user explicitly selects which provider to use in the UI.

### 3.2 Module Structure

```
llm_proxy/
├── README.md
├── docs/
│   ├── design_document.md
│   └── implementation_plan.md
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── src/
│   └── llm_proxy/
│       ├── __init__.py
│       ├── main.py              # FastAPI app, startup, mounts adapters
│       ├── config.py            # Settings via pydantic-settings
│       ├── models.py            # Pydantic models for OpenAI request/response
│       ├── auth.py              # Credential decoding from Authorization header
│       ├── provider_base.py     # Abstract base class for provider adapters
│       ├── provider_registry.py # Auto-discovers and mounts provider adapters
│       ├── config_generator.py  # Generates OpenCode config + update script to /output/
│       └── providers/
│           ├── __init__.py
│           └── t3chat.py        # T3.chat adapter
├── tests/
│   ├── __init__.py
│   ├── test_auth.py
│   ├── test_models.py
│   └── providers/
│       ├── __init__.py
│       └── test_t3chat.py
└── scripts/
    └── extract_t3_creds.sh      # Helper to extract cookies from browser
```

### 3.3 Provider Adapter Interface

Every provider adapter implements a simple abstract base class. Each adapter owns its own FastAPI `APIRouter`, which gets mounted at `/{provider_id}/v1`. This means the adapter controls its own routes and can add provider-specific endpoints if needed (e.g., a session refresh endpoint), while the base class enforces the required OpenAI-compatible routes.

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from fastapi import APIRouter
from llm_proxy.models import (
    ChatCompletionRequest, ChatCompletionChunk,
    ChatCompletionResponse, ModelObject,
)


class ProviderAdapter(ABC):
    """Base class for all provider adapters."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """URL path prefix and unique identifier, e.g. 't3chat'.
        The adapter will be mounted at /{provider_id}/v1/"""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. 'T3 Chat'."""

    @abstractmethod
    async def initialize(self) -> None:
        """Called once at startup. Use for model discovery, connection
        setup, or any async initialization."""

    @abstractmethod
    def get_models(self) -> list[ModelObject]:
        """Return list of models in OpenAI ModelObject format."""

    @abstractmethod
    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> ChatCompletionResponse:
        """Non-streaming completion."""

    @abstractmethod
    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        credentials: dict,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Streaming completion yielding SSE chunks."""

    def create_router(self) -> APIRouter:
        """Creates the FastAPI router for this adapter.
        The base class provides a default implementation that wires up
        /v1/chat/completions and /v1/models. Subclasses can override
        to add provider-specific routes."""
        # Default implementation provided by base class (not abstract)
        ...
```

**Key change from prior design**: The `accepts_model()` method has been removed. The proxy does not need to match models to adapters — the URL path prefix does that. When OpenCode sends a request to `/t3chat/v1/chat/completions`, only the T3 adapter handles it. The model name in the request body is passed through to T3's backend as-is.

### 3.4 Provider Auto-Discovery

Provider adapters are auto-discovered at startup. The discovery process:

1. Scan all Python files in `src/llm_proxy/providers/`
2. Find all classes that inherit from `ProviderAdapter`
3. Instantiate each one
4. Call `adapter.initialize()` (async — this is where model discovery happens)
5. Call `adapter.create_router()` to get the FastAPI router
6. Mount the router at `/{adapter.provider_id}/v1`
7. Log the registered adapter and its model count

To add a new provider: create a new `.py` file in `providers/`, implement the `ProviderAdapter` interface, rebuild the Docker image. No other changes needed.

## 4. Key Design Decisions

### 4.1 Path-Based Routing in a Single Container

**Decision**: All provider adapters run in a single Docker container. Each adapter is mounted at its own URL path prefix (`/{provider_id}/v1/`). OpenCode selects the adapter by setting `base_url` in the provider config.

**Rationale**: Running one container per provider would complicate infrastructure (multiple containers, ports, compose entries). Since OpenCode already routes by `baseURL`, path-based routing is a natural fit. Each provider in `opencode.json` simply points to a different path on the same host:

```json
{
  "provider": {
    "t3chat": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://localhost:4141/t3chat/v1",
        "apiKey": "{env:T3_CHAT_CREDS}"
      },
      ...
    },
    "future-provider": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://localhost:4141/future/v1",
        "apiKey": "{env:FUTURE_CREDS}"
      },
      ...
    }
  }
}
```

**Trade-off**: All adapters share a process. A misbehaving adapter could affect others. Acceptable for a local dev tool.

### 4.2 Auth: Pass-through, not stored

**Decision**: Credentials are encoded in the `Authorization: Bearer <token>` header on every request. The proxy never stores, caches, or persists credentials.

**Mechanism**: The bearer token is a base64-encoded JSON object containing provider-specific credentials. Each provider defines its own credential shape. For T3.chat:

```json
{
  "cookies": "wos-session=abc123; other-cookie=xyz",
  "convex_session_id": "uuid-here"
}
```

A future provider might need:

```json
{
  "credential": "provider-value-here",
  "org_id": "org-..."
}
```

Same mechanism, different payload. The proxy decodes the base64 JSON and passes the resulting dict to the adapter, which knows how to interpret its own credential shape.

**OpenCode integration**: The `apiKey` field in OpenCode's provider config becomes the bearer token. Set it as an environment variable:

```bash
export T3_CHAT_CREDS=$(echo -n '{"cookies":"wos-session=...","convex_session_id":"..."}' | base64)
```

Then in `opencode.json`:

```json
"options": {
  "apiKey": "{env:T3_CHAT_CREDS}"
}
```

**Trade-off**: Credentials must be refreshed externally when the `wos-session` rotates. The proxy returns updated credentials in `X-Updated-Credentials` response header after performing a session refresh, but persisting them is the caller's responsibility.

### 4.3 Session Refresh Strategy

**Decision**: The T3 adapter performs a session refresh (calls `auth.getActiveSessions`) before each chat request and returns any updated `wos-session` in the `X-Updated-Credentials` response header.

**Evidence**: The t3router library (`client.rs:68-101`) calls `refresh_session()` at the top of every `send()` call. The T3 backend rotates the `wos-session` cookie via the `x-workos-session` response header on the tRPC endpoint.

**Behavior**:

1. Before forwarding to T3, call `GET /api/trpc/auth.getActiveSessions` with the provided cookies
2. If `x-workos-session` header is present in the response, update the cookie string
3. Use the (possibly updated) cookies for the chat request
4. Return the updated credentials in `X-Updated-Credentials` response header so the caller can persist them if desired

### 4.4 Browser Impersonation

**Decision**: The T3 adapter sends browser-like headers on all requests to T3.chat.

**Evidence**: The t3router library (`client.rs:37-53`) sets Chrome User-Agent, `sec-ch-ua`, `sec-fetch-*`, `origin`, and other headers. The HAR capture confirms T3.chat's frontend sends identical headers. Without these, the server may reject requests.

**Headers sent**:

```
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36
Origin: https://t3.chat
Referer: https://t3.chat/chat/<thread-id>
sec-ch-ua: "Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "macOS"
sec-fetch-dest: empty
sec-fetch-mode: cors
sec-fetch-site: same-origin
```

### 4.5 Streaming SSE Translation

**Decision**: Stream T3.chat's SSE events in real time, translating each `text-delta` and `reasoning-delta` event into an OpenAI-compatible `chat.completion.chunk` SSE event as it arrives. Do not buffer the entire response.

**Evidence**: The t3router library buffers the full response before parsing (`client.rs:423` calls `response.text().await`), which adds latency. The HAR capture shows T3 streams individual `data:` lines. Real-time translation is both feasible and preferred for interactive coding tools.

**T3 SSE event to OpenAI SSE chunk mapping**:

| T3 Event          | OpenAI Chunk                         | Notes                                     |
| ----------------- | ------------------------------------ | ----------------------------------------- |
| `start`           | (no output)                          | Internal bookkeeping, extract `messageId` |
| `start-step`      | (no output)                          |                                           |
| `reasoning-start` | (no output)                          | Begin accumulating reasoning              |
| `reasoning-delta` | chunk with `delta.reasoning_content` | If client supports reasoning              |
| `reasoning-end`   | (no output)                          |                                           |
| `text-start`      | (no output)                          |                                           |
| `text-delta`      | chunk with `delta.content`           | Main content tokens                       |
| `text-end`        | (no output)                          |                                           |
| `finish-step`     | (no output)                          |                                           |
| `finish`          | chunk with `finish_reason: "stop"`   |                                           |
| `[DONE]`          | `data: [DONE]`                       | Pass through directly                     |

**OpenAI SSE chunk format**:

```json
{
  "id": "chatcmpl-<messageId>",
  "object": "chat.completion.chunk",
  "created": 1709123456,
  "model": "gemini-3-flash",
  "choices": [{
    "index": 0,
    "delta": {"content": "token text"},
    "finish_reason": null
  }]
}
```

### 4.6 Dynamic Model Discovery

**Decision**: The T3 adapter discovers available models dynamically at container startup by scraping T3.chat's frontend JavaScript bundles. A hardcoded fallback list is used if scraping fails.

**Evidence**: The t3router library (`models.rs:53-193`) demonstrates this approach works:

1. Try a known chunk URL (`/_next/static/chunks/<hash>.js`)
2. If that fails, fetch the T3.chat homepage HTML
3. Extract all `<script src="/_next/static/chunks/...">` URLs via regex
4. Download each JS chunk and parse model definitions using regex patterns that match property structures like `id: "...", name: "...", provider: "..."`
5. Fall back to a hardcoded list if all dynamic discovery fails

**Startup behavior**: The `initialize()` method on the T3 adapter performs model discovery. This runs once at container startup. If it fails, the fallback model list is used and a warning is logged. The container still starts — it does not fail hard on discovery failure.

**Model metadata extracted**: `id`, `name`, `provider`, `developer`, `short_description`. These are mapped to OpenAI's `ModelObject` format for the `/v1/models` endpoint.

### 4.7 Model Naming

**Decision**: T3 model IDs are used as-is (e.g., `gemini-3-flash`, `claude-4.6-sonnet`, `gpt-5.2-reasoning`). No prefix is added.

**Rationale**: OpenCode already namespaces models by provider (e.g., `t3chat/gemini-3-flash`). Adding a prefix in the proxy would create double-namespacing. The model name in the request body is passed through to T3's backend verbatim.

### 4.8 Python + FastAPI

**Decision**: Python 3.12+ with FastAPI and httpx.

**Rationale**:

- FastAPI has first-class SSE streaming support via `StreamingResponse`
- httpx provides async HTTP client with streaming response iteration
- Faster to iterate than Go for a project of this scope
- The proxy is I/O-bound (waiting on upstream LLM responses), not CPU-bound, so Python's performance is not a concern
- Pydantic provides type-safe request/response models that match OpenAI's schema

### 4.9 Docker-Only Deployment

**Decision**: The proxy runs exclusively as a Docker container. There is no supported bare-metal / `python -m` workflow. `docker compose up` is the primary interface.

**Rationale**: Container isolates all dependencies. Adding or updating provider adapters is done by rebuilding the image — all adapter modules are baked in at build time. No runtime plugin loading, no volume-mounting of adapter code. A new adapter or an updated adapter means a new image version.

**Port**: 4141 (chosen to avoid conflicts with common dev ports).

**Lifecycle**:

- `docker compose up -d` — start the proxy
- `docker compose down` — stop the proxy
- `docker compose build` — rebuild after adding/updating a provider adapter
- `docker compose logs -f` — view logs

### 4.10 Non-streaming Fallback

**Decision**: Support `"stream": false` in the request by buffering the full streamed response from T3 and returning it as a single JSON response.

**Rationale**: OpenCode primarily uses streaming, but non-streaming mode is part of the OpenAI spec and may be needed by other clients.

### 4.11 OpenCode Config Generation on Container Startup

**Decision**: On every container startup, after model discovery completes, the proxy writes two files to a volume-mounted output directory (`/output/`):

1. **`opencode_provider_t3chat.json`** — A complete OpenCode provider stanza with all dynamically discovered models, ready to merge into `opencode.json`
2. **`update_opencode_config.sh`** — A shell script that reads the JSON file from the same directory and merges the provider stanza into the user's `opencode.json`

Both files land side-by-side in the mounted volume. The user can then `cd` to that directory and run the script whenever they want to sync models.

**Rationale**: OpenCode does not dynamically fetch models from custom providers. It only uses models explicitly listed in `opencode.json`. Since there are no startup hooks or plugin mechanisms in OpenCode, the proxy must generate the config externally. Writing it on every container start ensures the output always reflects the latest scraped model list.

**The script (`update_opencode_config.sh`)**:
- Reads `opencode_provider_t3chat.json` from the same directory it lives in
- Merges the `t3chat` entry into the `provider` key of the target `opencode.json`
- Defaults to `~/.config/opencode/opencode.json` but accepts an override path as argument
- Preserves all other providers and config in the target file
- Creates the target file if it doesn't exist
- The script is NOT part of the Docker image build — it is generated at runtime by the Python config generator and written to the output volume alongside the JSON

**docker-compose.yml** mounts a host directory to `/output/`:
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

**Workflow**:
```bash
# Start the container — models are scraped, config files are written to ./output/
docker compose up -d

# When you want to sync models into OpenCode:
cd output
./update_opencode_config.sh

# Or target a specific config file:
./update_opencode_config.sh /path/to/project/opencode.json

# Restart OpenCode to pick up changes
```

**Generated JSON format** (`opencode_provider_t3chat.json`):
```json
{
  "t3chat": {
    "npm": "@ai-sdk/openai-compatible",
    "name": "T3 Chat",
    "options": {
      "baseURL": "http://localhost:4141/t3chat/v1",
      "apiKey": "{env:T3_CHAT_CREDS}"
    },
    "models": {
      "gemini-3-flash": {
        "name": "Gemini 3 Flash",
        "limit": {
          "context": 200000,
          "output": 16000
        }
      }
    }
  }
}
```

Each adapter contributes its own config fragment. Future adapters generate their own `opencode_provider_<id>.json` and corresponding update script.

## 5. Credential Extraction

T3.chat requires two credential values:

1. **Cookie string** — contains `wos-session=<token>` (plus other cookies). This is an httpOnly cookie, meaning `document.cookie` in JavaScript **cannot** access it. It is only visible in the browser's Network tab request headers.
2. **`convexSessionId`** — a UUID generated by the Convex client SDK in the browser. It appears in the JSON body of every `/api/chat` request.

### Method 1: Copy as cURL (Recommended)

This is the easiest method. The cURL command contains both values.

**Step-by-step**:

1. Open **https://t3.chat** in Chrome and log in
2. Open DevTools: press **F12** (or **Cmd+Option+I** on Mac)
3. Click the **Network** tab at the top of DevTools
4. In the filter bar (below the Network tab label), type **`/api/chat`** to filter requests
5. Go back to the T3.chat window and **send any message** in any chat (e.g., type "hello" and press Enter)
6. A new entry appears in the Network tab — it will show `chat` with method `POST`
7. **Right-click** on that `chat` entry
8. Select **Copy** → **Copy as cURL**
9. Paste the result somewhere (a text file, your terminal, etc.)

The pasted cURL command will contain:
- A `-b '...'` flag (Chrome's format for cookies) — this is your cookie string. It contains both `wos-session=...` and `convex-session-id=...`
- A `--data-raw '{"messages":...,"convexSessionId":"a60446fb-...",...}'` section — the same `convexSessionId` also appears here in the JSON body

Note: The `convex-session-id` value is present in both the cookie string and the JSON body, so the extraction script can get it from either source.

A helper script (`scripts/extract_from_curl.sh`) will parse the pasted cURL command and output the base64-encoded credential string. Usage:

```bash
./scripts/extract_from_curl.sh
# Paste your cURL command, press Enter, then Ctrl+D
# Output: export T3_CHAT_CREDS='<base64>'
```

### Method 2: Manual extraction from DevTools

If you prefer to copy values individually:

**Finding the Cookie string**:

1. Open DevTools → Network tab, filter for `/api/chat`, send a message (same as steps 1-6 above)
2. **Click** on the `chat` entry (don't right-click, just left-click to select it)
3. A detail panel opens on the right side. Click the **Headers** tab
4. Scroll down to the **Request Headers** section (not "Response Headers")
5. Find the line that says **`Cookie:`** — it will have a long value like `wos-session=eyJ...; __cf_bm=...; ...`
6. **Double-click** the cookie value to select it, then copy

**Finding the convexSessionId**:

1. With the same `chat` entry selected, click the **Payload** tab (next to Headers)
2. You will see the request body as a tree. Look for **`convexSessionId`**
3. It will be a UUID like `a60446fb-5f56-48d5-9152-1f047419c3c9`
4. Click the value to select it, then copy

Then run the manual encoder script:

```bash
./scripts/extract_t3_creds.sh
# Paste cookie string when prompted
# Paste convexSessionId when prompted
# Output: export T3_CHAT_CREDS='<base64>'
```

### Method 3: JavaScript bookmarklet

A bookmarklet that monkey-patches `fetch()` to intercept the next `/api/chat` request and captures both the Cookie header and `convexSessionId` from the request body. Since `wos-session` is httpOnly, the bookmarklet cannot read it from `document.cookie` — it must intercept the actual outgoing fetch request.

**How it works**: The bookmarklet replaces `window.fetch` with a wrapper. When T3.chat's frontend calls `fetch('/api/chat', ...)`, the wrapper:
1. Reads the `convexSessionId` from the JSON request body
2. Lets the real `fetch()` proceed (so the chat still works)
3. Reads the `Cookie` header from the browser's request (via the `Request` object)
4. Formats both values as the base64-encoded credential JSON
5. Copies the result to clipboard and shows an alert

**Limitation**: The `Request` object in a fetch interceptor may not expose httpOnly cookies. If this approach cannot access the Cookie header, it will fall back to prompting the user to paste it from the Network tab. This method is provided as a convenience but Method 1 (copy as cURL) is more reliable.

The bookmarklet code is generated and written to `/output/t3chat_bookmarklet.html` on container startup alongside the config files. The HTML file contains the bookmarklet link and usage instructions.

## 6. OpenCode Configuration

Once the proxy container is running at `http://localhost:4141`, the simplest approach is to run the generated update script:

```bash
./output/update_opencode_config.sh
```

This merges the T3 provider and all discovered models into `~/.config/opencode/opencode.json`. The resulting config looks like:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "t3chat": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "T3 Chat",
      "options": {
        "baseURL": "http://localhost:4141/t3chat/v1",
        "apiKey": "{env:T3_CHAT_CREDS}"
      },
      "models": {
        "gemini-3-flash": {
          "name": "Gemini 3 Flash",
          "limit": {"context": 200000, "output": 16000}
        },
        "claude-4.6-sonnet": {
          "name": "Claude 4.6 Sonnet",
          "limit": {"context": 200000, "output": 16000}
        },
        "gpt-5.2-reasoning": {
          "name": "GPT 5.2 Reasoning",
          "limit": {"context": 200000, "output": 16000}
        }
      }
    }
  }
}
```

Verify with `opencode models t3chat` to confirm all models are visible.

**Note**: OpenCode only uses models explicitly listed in `opencode.json` — it does not fetch from the provider's `/v1/models` endpoint. The proxy generates a ready-to-use config file (`output/opencode_provider_t3chat.json`) and an update script (`output/update_opencode_config.sh`) on every container startup. Run the script to sync the dynamically discovered models into your `opencode.json`. See section 4.11 for details.

## 7. Risks and Mitigations

| Risk                                           | Impact                    | Mitigation                                                                                                           |
| ---------------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| T3.chat changes their API format               | Proxy breaks              | The adapter isolates all T3-specific logic. Fix is contained to one file (`providers/t3chat.py`). Rebuild container. |
| `wos-session` cookie expires frequently        | Auth fails mid-session    | Session refresh on every request (matches t3router behavior). Return updated creds in response header.               |
| T3.chat rate-limits or blocks automated access | Service denied            | Browser impersonation headers. Respect natural usage patterns.                                                       |
| T3.chat adds CAPTCHA or bot detection          | Service denied            | Out of scope — would require manual intervention.                                                                    |
| Model discovery scraping fails                 | No models listed          | Hardcoded fallback list ensures the proxy still works. Warning logged.                                               |
| T3.chat changes JS bundle structure            | Discovery finds no models | Fallback list. The scraping regex patterns may need updating.                                                        |

## 8. Future Enhancements

- **Credential auto-refresh daemon**: A background task within the container that periodically refreshes `wos-session` and exposes updated creds via an endpoint
- **Tool use / function calling**: Map T3's tool-related SSE events to OpenAI's `tool_calls` format
- **File attachments**: Support image/file uploads via T3's UploadThing flow
- **Metrics and logging**: Structured logging with request/response timing, token counts, error rates
- **Model discovery refresh**: Periodic re-scraping to pick up new models without container restart
