# Output Directory

This directory is volume-mounted from the Docker container (`./output:/output`). The proxy regenerates its files at every container startup based on the providers and models it discovers. Generated files are intentionally ignored by Git so running the service never modifies tracked source; this README is the only tracked file in the directory.

## Files

| File | Purpose |
|------|---------|
| `opencode_provider_<provider>.json` | One generated provider + model config per discovered adapter (currently T3 Chat and ChatJimmy) |
| `update_opencode_config.sh` | Script that merges the provider JSON into your OpenCode config |
| `t3chat_bookmarklet.html` | Browser bookmarklet for credential extraction (alternative to the shell scripts) |

## Setup Steps

### Prerequisites

1. The proxy container is running (`docker compose up -d`)
2. To use T3 Chat, you have `T3_CHAT_CREDS` exported in your shell (see [`../scripts/README.md`](../scripts/README.md)); ChatJimmy itself does not require credentials

### 1. Merge models into OpenCode

The update script merges the provider and model definitions into your OpenCode config file. It creates the file if it doesn't exist.

```bash
# Default target: ~/.config/opencode/opencode.json
./output/update_opencode_config.sh

# Or specify a custom path:
./output/update_opencode_config.sh /path/to/opencode.json
```

This adds or updates every generated proxy provider under the `provider` key, using the model set discovered at container startup. It does not modify unrelated providers already in your config.

### 2. Verify the config

After running the update script, your `opencode.json` will contain a provider block like:

```json
{
  "provider": {
    "t3chat": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "T3 Chat",
      "options": {
        "baseURL": "http://localhost:4141/t3chat/v1",
        "apiKey": "{env:T3_CHAT_CREDS}"
      },
      "models": {
        "gemini-3-flash": {"name": "Gemini 3 Flash", "limit": {"context": 200000, "output": 16000}},
        ...
      }
    }
  }
}
```

For example, verify that OpenCode sees the T3 models:

```bash
opencode models t3chat
```

### 3. Verify the proxy is reachable

```bash
# Health check
curl http://localhost:4141/health

# List registered providers
curl http://localhost:4141/providers

# List T3 models (no auth required)
curl http://localhost:4141/t3chat/v1/models
```

### 4. Test with credentials

```bash
curl -X POST http://localhost:4141/t3chat/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $T3_CHAT_CREDS" \
  -d '{"model": "gemini-3-flash", "messages": [{"role": "user", "content": "hello"}], "stream": false}'
```

## Refreshing Models

If an upstream provider adds or removes models, restart the container to re-run discovery:

```bash
docker compose restart
```

The output files are regenerated on every startup. Run `update_opencode_config.sh` again afterward to sync the new model list into OpenCode.
