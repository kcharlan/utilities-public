# harscope Test Plan

## Overview

These tests validate the harscope export engine, security scanner, and redaction workflow via the REST API. The server is started, a HAR file is loaded, and each test exercises a specific feature through API calls and verifies the result programmatically.

No UI interaction is needed — everything is tested through the backend API endpoints.

## Prerequisites

- Python 3.8+
- A HAR file with security-relevant content (tokens, session IDs, JWTs, etc.)
- HAR files with WebSocket messages are needed to test WS-specific redaction

## Test Matrix

### Test 1: Auto-detected findings redacted in export

- Load a HAR file
- Confirm security findings are detected (`GET /api/security`)
- Export sanitized HAR (`POST /api/export/har`)
- Parse exported HAR, navigate to each finding's location, verify value is `[REDACTED]`
- Covers: HTTP headers, HTTP body (parsed JSON, nested keys with array indices), WebSocket message body (parsed JSON, nested keys)

### Test 2: EDL export + CLI validation

- Export sanitized HAR and EDL (`POST /api/export/edl`)
- Run `./harscope --validate sanitized.har --edl sanitized.edl.json`
- Verify exit code 0 and `RESULT: VALID`
- Covers: EDL generation for all finding types, `_read_location_value` for all location formats

### Test 3: Toggle auto-redact finding to KEEP

- Pick a critical finding (e.g., a JWT token)
- Toggle it off (`POST /api/security/toggle` with finding ID)
- Export sanitized HAR
- Verify the toggled finding's value is NOT `[REDACTED]` (original value preserved)
- Toggle it back on
- Covers: Per-finding keep/redact toggle, selective export

### Test 4: Manual redact a non-flagged value

- Pick a value that the scanner did NOT flag (e.g., a benign field like `persona` or `connectionCount`)
- Add a manual redaction (`POST /api/redaction/manual`)
- Export sanitized HAR
- Verify the manually targeted value IS `[REDACTED]`
- Remove the manual redaction (`POST /api/redaction/remove-manual`)
- Export again and verify the value is restored (not redacted)
- Covers: Manual redaction add/remove, `_redact_body_value` for non-finding locations

### Test 5: Bulk deselect by severity

- Bulk deselect all warnings (`POST /api/security/bulk` with `action=deselect, severity=warning`)
- Verify via `/api/security` that all warnings have `redact=false`, all criticals still `redact=true`
- Export sanitized HAR
- Spot-check: a critical value is `[REDACTED]`, a warning value is NOT
- Re-select all (`POST /api/security/bulk` with `action=select`)
- Covers: Bulk toggle, severity-based filtering

### Test 6: Mixed EDL round-trip (keep + manual + auto)

- Toggle one finding to KEEP
- Add one manual redaction
- Export sanitized HAR and EDL
- Verify EDL contains the expected keep/redact/manual decisions
- Run CLI validation — all decisions should pass
- Covers: EDL with mixed decision types, validation of keep decisions, manual decisions in EDL

### Test 7: Reset and reapply

- Create mixed state (toggle a finding, add a manual redaction)
- Reset all (`POST /api/redaction/reset`)
- Verify: auto findings restored to severity defaults, manual redactions cleared
- Reapply auto (`POST /api/redaction/reapply-auto`)
- Verify: all findings redacting again
- Covers: State management, reset/reapply workflows

### Test 8: Full round-trip (sanitized HAR rescan)

- Export sanitized HAR with all defaults
- Export EDL and validate via CLI
- Reload the sanitized HAR as a new file (`POST /api/open`)
- Rescan — verify 0 findings (all secrets replaced with `[REDACTED]`, which the scanner skips)
- Covers: End-to-end redaction integrity, scanner skip-logic for `[REDACTED]` values

## WebSocket-Specific Coverage

Tests 1-8 should be run against at least one HAR file containing WebSocket messages to exercise:

- WS container detection in `_redact_body_value` (uses `data` key, not `text`)
- WS container detection in `_read_location_value` (EDL validation)
- Nested JSON paths with array indices inside WS messages (e.g., `modifications[0].args[0].sessionId`)
- Non-parsed WS data redaction (whole-message `_webSocketMessages[N].data` paths)

## Failure Modes to Watch For

- **Nested array paths**: Locations like `modifications[0].args[0].sessionId` require expanding `modifications[0]` into separate dict-lookup + array-index steps. A regression here means top-level keys redact but nested ones silently fail.
- **WS vs HTTP container mismatch**: WS messages store body text in `data`, HTTP stores in `text`. Using the wrong key silently reads empty string and returns without redacting.
- **EDL validation false positives**: `_read_location_value` must use the same container/key logic as `_redact_body_value`. If they diverge, export works but validation fails.
