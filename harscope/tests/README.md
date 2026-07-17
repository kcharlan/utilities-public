# harscope Tests

Integration tests for the harscope export engine, security scanner, and redaction workflows. Tests exercise the backend REST API directly — no browser or UI interaction needed.

## Files

| File | Description |
|---|---|
| `TEST_PLAN.md` | Detailed test plan with descriptions, coverage notes, and failure modes |
| `run_tests.sh` | Main test runner — starts a server, runs all 8 tests, reports results |
| `verify_redaction.py` | Python helper called by `run_tests.sh` to verify redaction state in HAR files |

## Quick Start

```bash
cd harscope/tests

# Run against a HAR file with WebSocket messages
./run_tests.sh ../t3.chat.GPT52Instant.har

# Run against a HAR file with HTTP-only traffic
./run_tests.sh ../chatgpt.com.GPT52.Instant.har

# Use a custom port (default: 8299)
./run_tests.sh ../some_file.har 8333
```

## What It Tests

1. **All auto-detected findings redacted in export** — every flagged value becomes `[REDACTED]`
2. **EDL export + CLI validation** — EDL round-trips cleanly with `--validate`
3. **Toggle finding to KEEP** — kept values are preserved (not redacted) in export
4. **Manual redact non-flagged value** — manually added redactions work and can be removed
5. **Bulk deselect by severity** — warnings can be bulk-deselected while criticals stay
6. **Mixed EDL round-trip** — keep + manual + auto decisions all validate correctly
7. **Reset and reapply** — reset clears overrides, reapply restores defaults
8. **Full round-trip** — sanitized HAR rescanned shows zero findings

## Requirements

- Python 3.8+
- `curl` (used by the shell script for API calls)
- A HAR file with security-relevant content (tokens, session IDs, JWTs, etc.)

The test runner starts its own harscope server instance and cleans up after itself. It uses port 8299 by default to avoid conflicting with a running development instance.

## Using Your Own HAR Files

Any HAR file with at least one security finding will work. For full coverage, test with:

- A HAR containing **WebSocket messages** with JSON payloads (exercises WS-specific container logic)
- A HAR containing **HTTP request/response bodies** with nested JSON (exercises array index path navigation)
- A HAR with both **critical and warning** severity findings (exercises bulk toggle)

The test runner automatically adapts: it discovers findings, picks non-flagged keys for manual redaction tests, and skips tests that don't apply (e.g., bulk severity test is skipped if the HAR only has one severity level).

## Exit Codes

- `0` — all tests passed
- `1` — one or more tests failed (details printed to stdout)

## Adding Tests

To add a new test:

1. Add a section to `run_tests.sh` following the existing pattern (API call, verify, `check` helper)
2. If the verification logic is complex, add a new mode to `verify_redaction.py`
3. Document the test in `TEST_PLAN.md`
