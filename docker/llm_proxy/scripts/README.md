# Scripts

Helper scripts for extracting T3.chat credentials and encoding them for use with the LLM Proxy.

## Authentication Overview

The proxy is stateless — no credentials are stored. Instead, credentials are passed per-request as an `Authorization: Bearer <token>` header, where the token is a base64-encoded JSON object:

```json
{"cookies": "<full cookie string>", "convex_session_id": "<uuid>"}
```

OpenCode sends this automatically when you configure `"apiKey": "{env:T3_CHAT_CREDS}"` in your provider config. The proxy decodes the token on each request and uses the cookies/session ID to authenticate against T3.chat's upstream API.

## Credential Extraction

You need two things from a live T3.chat browser session:

1. **Cookies** — the full cookie string (includes `wos-session`, `convex-session-id`, and others; ~3KB total)
2. **convex-session-id** — a UUID present both as a cookie and in request payloads

Both scripts below extract these values and output a base64-encoded `T3_CHAT_CREDS` export line ready for your shell profile.

### extract_from_curl.sh (Recommended)

Extracts credentials from a Chrome DevTools "Copy as cURL" command. Handles both `-b` (Chrome default) and `-H 'Cookie: ...'` cookie formats.

**From a file** (recommended for large cURL commands):

```bash
# 1. In Chrome DevTools Network tab, right-click a /api/chat request → Copy as cURL
# 2. Paste into a file (e.g. ~/t3_curl.txt)
./scripts/extract_from_curl.sh ~/t3_curl.txt
```

**Interactive mode** (reads from stdin):

```bash
./scripts/extract_from_curl.sh
# Paste the cURL command, press Enter, then Ctrl+D
```

**How to get the cURL command:**

1. Open https://t3.chat in Chrome and log in
2. Open DevTools (F12 or Cmd+Option+I)
3. Go to the **Network** tab
4. Type `/api/chat` in the filter bar
5. Send any message in T3.chat (e.g. type "hello")
6. Right-click the `chat` entry that appears → **Copy** → **Copy as cURL**
7. Save to a file or paste into the script

### extract_t3_creds.sh (Fallback)

Manual entry — prompts you to paste the Cookie header value and convexSessionId separately. Useful if the cURL approach doesn't work.

```bash
./scripts/extract_t3_creds.sh
# Follow the prompts to paste each value
```

## Applying Credentials

Both scripts output an export line like:

```bash
export T3_CHAT_CREDS='eyJjb29raWVzIjoi...'
```

Add this to your `~/.zshrc` or `~/.bashrc`, then reload your shell (`source ~/.zshrc`). OpenCode reads `$T3_CHAT_CREDS` from the environment and sends it as the Bearer token on every request.

## Credential Rotation

T3.chat rotates the `wos-session` cookie periodically. The proxy handles this automatically — it calls T3's `auth.getActiveSessions` endpoint before each request and updates the session cookie if it has rotated. However, if your cookies expire entirely (e.g. you log out or clear browser data), you'll need to re-run the extraction script.
