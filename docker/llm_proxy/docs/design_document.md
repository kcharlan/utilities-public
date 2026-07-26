# LLM Proxy Design

**Original design date:** 2026-02-22

**Status:** Implemented; maintained as the architectural reference

## Purpose

The proxy makes selected web-only LLM services available through a small
OpenAI-compatible surface for local clients, especially OpenCode. It currently
adapts:

- **T3 Chat**, authenticated with credentials borrowed from a user's browser
  session.
- **ChatJimmy**, whose current upstream API does not require authentication.

The project deliberately does not attempt to implement the complete OpenAI API.
Each provider exposes `GET /v1/models` and `POST /v1/chat/completions` beneath a
provider-specific path.

## Architecture

```text
OpenCode or another local client
  ├── http://127.0.0.1:4141/t3chat/v1
  └── http://127.0.0.1:4141/chatjimmy/v1
                         │
                         ▼
                 FastAPI application
                 ├── provider registry
                 ├── T3ChatAdapter
                 ├── ChatJimmyAdapter
                 ├── GET /health
                 └── GET /providers
                         │
                         ▼
                 Provider upstream APIs
```

Docker Compose publishes port `4141` on `127.0.0.1` only and mounts
`./output` at `/output`. The application and all adapters are baked into one
image; provider code is not loaded from host volumes at runtime.

The main implementation is organized as follows:

```text
src/llm_proxy/
├── main.py
├── config.py
├── auth.py
├── models.py
├── provider_base.py
├── provider_registry.py
├── config_generator.py
├── tool_call_parser.py
└── providers/
    ├── chatjimmy.py
    └── t3chat.py
```

## Routing Contract

Routing is based only on the URL prefix:

- `/t3chat/v1/*` is handled by `T3ChatAdapter`.
- `/chatjimmy/v1/*` is handled by `ChatJimmyAdapter`.

The model name does not select an adapter. The client has already selected the
provider by choosing its configured `baseURL`; the requested model ID is passed
to that adapter.

`ProviderRegistry` discovers concrete `ProviderAdapter` subclasses in
`llm_proxy.providers` at application startup. It initializes each adapter,
mounts the router at `/{provider_id}`, and exposes the registry summary through
`GET /providers`. Adapters share one process, so a blocking or failing adapter
can affect the whole local service.

## Adapter Contract

Every provider supplies:

- `provider_id` and `display_name`
- optional `requires_auth` and `env_var_name` overrides
- asynchronous startup initialization
- OpenAI `ModelObject` entries and OpenCode model configuration
- streaming and non-streaming chat-completion implementations

The base router:

- validates incoming bodies with `ChatCompletionRequest`
- obtains credentials when `requires_auth` is true
- emits OpenAI-shaped SSE chunks followed by `data: [DONE]` for streaming
  requests
- returns a single `ChatCompletionResponse` for non-streaming requests
- returns the adapter's models from `GET /v1/models`

Request models allow unknown fields so clients can send provider options that
the adapter may inspect. This is a compatibility choice, not a promise that
every OpenAI option affects the upstream request.

## Credential Boundary

The proxy is stateless with respect to provider credentials:

- T3 credentials arrive on each request as
  `Authorization: Bearer <base64-json>`.
- The decoded JSON must contain `cookies` and `convex_session_id`.
- Base64 is transport encoding, not encryption. The bearer value must be
  handled as a secret.
- Credentials are neither written to disk nor stored in application state.
- ChatJimmy overrides `requires_auth` because its current upstream is public.

Before each T3 chat request, the adapter calls T3's active-session endpoint. If
T3 supplies a rotated `wos-session`, the adapter substitutes it in the cookie
string used for that upstream chat request. The refreshed value is not
persisted and is not returned to the caller; the next request repeats the
refresh from the credentials it receives.

The generated OpenCode provider configs use environment references such as
`{env:T3_CHAT_CREDS}` so the generated JSON does not contain credential values.

## Provider Translation

### T3 Chat

The T3 adapter:

1. Converts OpenAI messages to T3's message-part request shape.
2. Sends browser-like headers and the caller-supplied browser session.
3. Translates T3 SSE `text-delta` events to `delta.content`.
4. Translates `reasoning-delta` events to `delta.reasoning_content`.
5. Buffers the translated stream when the caller requests non-streaming mode.

T3 does not natively accept OpenAI tool definitions in this integration. The
adapter injects tool definitions into the system prompt, serializes prior tool
calls and results as `<tool_call>` and `<tool_result>` blocks, and uses
`ToolCallStreamParser` to turn valid streamed `<tool_call>` JSON into OpenAI
`tool_calls` deltas. The parser retains partial tags across chunks and falls
back to ordinary text for malformed tool-call JSON.

Some T3 models return `api_key_required` at higher reasoning tiers. When the
adapter observes that response, it remembers the model for the lifetime of the
process and retries at low reasoning. That cache is intentionally ephemeral.

### ChatJimmy

The ChatJimmy adapter converts OpenAI messages into the upstream request shape
and translates its streamed text response. It removes the optional `{}` prelude
and parses the `<|stats|>...<|/stats|>` trailer; non-streaming responses expose
those statistics as OpenAI usage fields when present.

ChatJimmy currently has no tool-call translation or reasoning-content mapping.

## Model Discovery

Both adapters discover models during startup and remain usable with fallback
lists when discovery fails:

- T3 fetches its home page, inspects JavaScript chunk URLs, and searches the
  chunks for model definitions.
- ChatJimmy requests its `/api/models` endpoint.

Discovery occurs only during application startup. Recreating the container
reruns it. Because upstream page and API formats are outside this project's
control, each adapter logs a warning and uses its embedded fallback instead of
preventing the proxy from starting.

## Generated OpenCode Configuration

After adapters initialize, `config_generator.py` writes:

- one `opencode_provider_<provider>.json` fragment per adapter
- one `update_opencode_config.sh` merge helper
- `t3chat_bookmarklet.html`

The files are regenerated in the mounted `output/` directory on each container
startup. The merge helper updates only matching entries under the target
config's singular `provider` key and preserves unrelated configuration. Its
default target is `~/.config/opencode/opencode.json`.

OpenCode model lists are generated because the tested client workflow expects
models to be declared in its configuration rather than relying only on the
proxy's `/v1/models` endpoints.

## Deployment and Operational Invariants

- Docker Compose is the supported runtime; there is no maintained bare-metal
  service workflow.
- The host binding remains loopback-only unless the operator deliberately
  changes it.
- Credentials must not be added to Compose, generated provider JSON, logs, or
  the repository.
- `output/` may be replaced on startup; only its README is tracked.
- A provider change requires an image rebuild and container recreation.
- `update.sh` is the explicit clean-refresh path for the moving Python base and
  allowed dependency ranges; `up.sh` performs a normal pull-aware build.
- `/health` proves that the process is serving requests, not that either
  external provider is currently healthy or authenticated.

## Extension Guidance

To add an adapter:

1. Add one module under `src/llm_proxy/providers/`.
2. Implement the `ProviderAdapter` contract and choose a unique, stable
   `provider_id`.
3. Keep provider-specific authentication, request translation, response
   parsing, discovery, and fallbacks inside that adapter.
4. Add tests for discovery fallback, auth behavior, streaming and
   non-streaming translation, upstream errors, and generated OpenCode config.
5. Rebuild the image and verify `/health`, `/providers`, both provider routes,
   and generated output.

Do not add model-name routing to the registry. Provider selection remains a URL
contract owned by the client's `baseURL`.
