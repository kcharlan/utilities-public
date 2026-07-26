# harscope

HAR (HTTP Archive) file analyzer and sanitizer. Combines rich visualization with integrated secret detection and sanitized export in a single-file tool.

## Features

- **Waterfall View** - Paginated request timeline with stacked timing bars (blocked/DNS/connect/SSL/send/wait/receive), domain/status/URL search filtering, and per-row security indicators (shield icons with red/amber severity coloring)
- **Inspector View** - Full request/response detail with headers, cookies, query params, body (JSON syntax-highlighted), timing breakdown, and WebSocket messages. Security findings are surfaced inline: red badges on Request/Response toggles and per sub-tab, flagged headers/cookies highlighted, body keys with findings shown in red with marked values
- **Security View** - Value-first secret detection across the entire HAR tree. Findings are consolidated per field (multiple detectors on the same value merge into one finding). Severity ratings, per-finding redact toggles, severity/category filtering
- **Sequence Diagram** - Interactive SVG canvas with pixel-perfect arrows and `<marker>` arrowheads, pan/zoom (scroll, Ctrl/Cmd+scroll, keyboard), minimap with viewport indicator, animated arrow draw-in, hover highlighting of request/response pairs, click-to-inspect navigation, domain/flow filtering, detected patterns (OAuth, redirect chains, API groups), and response toggle
- **Dashboard** - Summary cards (requests, size, load time, error rate), status code/domain/content type bar charts, timing percentiles
- **Inline Redaction** - Checkbox controls for headers, cookies, query parameters, and WebSocket messages, plus clickable keys in JSON bodies and JSON WebSocket payloads. Four visual states: auto-redact (red/FLAGGED), auto-kept (teal/KEPT), manual redact (amber/MANUAL), normal. Keyboard navigation with arrow keys and spacebar
- **Decisions View** - Table of all redaction decisions (auto + manual) with filters, toggle, and inspect actions
- **Export** - Sanitized HAR (redacted secrets with full value replacement), Edit Decision List (.edl.json), request-summary CSV, findings CSV, Markdown report, and HTML report with dark mode (system-theme detection, manual toggle, and localStorage persistence). The Export view also provides bulk redaction controls
- **EDL Validation** - Verify a sanitized HAR against its .edl.json to confirm all redact/keep decisions were applied correctly (GUI + CLI)

## Documentation

- **[User Guide](docs/USER_GUIDE.md)** — walkthrough of every view, the redaction workflow, export formats, and keyboard shortcuts

## Usage

```bash
./harscope [file.har] [--port 8200]
./harscope --validate sanitized.har --edl original.edl.json
```

### Examples

```bash
# Open a HAR file directly
./harscope capture.har

# Open on a custom port
./harscope capture.har --port 9000

# Launch without a file (use drag-and-drop or file picker in browser)
./harscope

# Multiple instances auto-select available ports starting from default
./harscope file1.har &
./harscope file2.har &

# Validate a sanitized HAR against its EDL (CLI, no server)
./harscope --validate sanitized_capture.har --edl capture.edl.json

# Validate with machine-readable JSON output
./harscope --validate sanitized_capture.har --edl capture.edl.json --format json
```

## Requirements

- [uv](https://docs.astral.sh/uv/) (`brew install uv`) — manages the Python interpreter and dependencies
- Internet connection to resolve Python dependencies on first run and to load browser assets from CDNs when they are not already cached

## First-Time Setup

harscope runs via uv using a PEP 723 inline-metadata header. The first run resolves its dependencies (fastapi, uvicorn, python-multipart, pydantic) into uv's shared cache — that invocation may briefly hit the network; subsequent runs reuse the cache. harscope does not create its own virtual environment or runtime-state directory; uv manages dependencies in its normal shared cache location.

## How to Capture a HAR File

1. Open Chrome DevTools (F12)
2. Go to the Network tab
3. Load/use the page you want to analyze
4. Right-click in the Network panel > "Save all as HAR with content"

## Security Scanner

The 2023 Okta breach demonstrated the danger of sharing unsanitized HAR files - attackers extracted session tokens from shared files. harscope automatically scans the entire HAR tree for secrets using a value-first approach:

### Detection Philosophy

Detection is **value-first, not key-first**. Key names boost confidence (lower thresholds) but never gate detection. Any long opaque string is evaluated regardless of its field name.

### 3-Tier Token Detection

| Tier | Condition | Severity |
|------|-----------|----------|
| 1 | Key name hints at secret + 32+ chars + 2+ char classes | Critical |
| 2 | Any key + 48+ chars + 2+ char classes | Warning |
| 3 | Any key + 80+ chars + 10+ unique chars | Warning |

### What It Catches

- **Critical**: Authorization headers, session cookies, JWT tokens, Bearer/Basic auth, API keys, sensitive URL parameters, opaque tokens in any field
- **Warning**: HTTP (non-HTTPS) requests, missing cookie security flags (httpOnly, secure), email addresses, and long opaque tokens without key hints
- **Info**: Private IP addresses

### Consolidation

Multiple detectors flagging the same field (e.g., JWT pattern + token heuristic on the same value) are consolidated into a single finding with merged descriptions and the highest severity.

### Redaction

Redaction replaces the **entire targeted value** with `[REDACTED]`. Direct HAR fields are replaced in place; structured JSON bodies are parsed, updated at the target key, and re-serialized. Previously redacted values (`[REDACTED]`) are skipped on rescan.

Review findings in the Security tab, toggle redaction per finding, then use the Export tab for bulk controls and sanitized output. You can also manually redact values in the Inspector, even if the scanner did not flag them.

### Edit Decision List (EDL)

Export an EDL alongside your sanitized HAR. The `.edl.json` file records every redaction decision (auto and manual) with entry index, location path, action (redact/keep), and request context. Use it to:

- **Validate** that a sanitized HAR was redacted correctly
- **Audit** what was redacted and what was kept
- **Automate** redaction workflows in CI/CD pipelines

### EDL Validation

Verify a sanitized HAR against its EDL to confirm all decisions were applied:

**GUI**: In the Export tab, click "Upload EDL to Validate". Results show pass/fail per decision.

**CLI**:
```bash
./harscope --validate sanitized.har --edl original.edl.json
# Exit code 0 = valid, 1 = failures found

# JSON output for scripting
./harscope --validate sanitized.har --edl original.edl.json --format json
```

Validation checks:
- `action: redact` → value in HAR must be `[REDACTED]`
- `action: keep` → value in HAR must NOT be `[REDACTED]`

## Architecture

Single-file Python application (uv-managed via a PEP 723 header) with:
- FastAPI backend with 26 REST routes
- Embedded React 18 SPA (CDN: React, Babel, Tailwind, Lucide Icons, Google Fonts)
- No build step, no npm, no node_modules
- Recursive whole-tree scanner with JSON body parsing, base64 decoding, and WebSocket message inspection

## Testing

The full suite exercises the backend API end-to-end: loading HAR files, scanning, toggling redactions, exporting, and validating EDLs.

```bash
cd harscope
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The optional `tests/run_tests.sh <har-file>` workflow exercises a real HAR fixture. See `tests/README.md` and `tests/TEST_PLAN.md` for details.

## Port

Default: 8200. Multiple instances auto-probe ports 8200-8219 to avoid conflicts.
