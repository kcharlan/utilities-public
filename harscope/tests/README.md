# harscope Tests

Automated API tests plus an optional real-HAR integration workflow. Neither suite drives the browser UI.

## Files

| File | Description |
|---|---|
| `test_api.py` | Primary pytest suite for all 26 FastAPI routes, scanner behavior, exports, validation, and robustness cases |
| `conftest.py` | ASGI client, isolated application state, and conspicuously synthetic HAR fixtures |
| `TEST_PLAN.md` | Durable matrix and failure-mode reference for the optional real-HAR workflow |
| `run_tests.sh` | Starts a local server and runs eight real-HAR redaction scenarios |
| `verify_redaction.py` | Python helper called by `run_tests.sh` to verify redaction state in HAR files |

## Primary Pytest Suite

```bash
cd harscope
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The pytest suite imports the FastAPI application in-process and uses `httpx.AsyncClient` with `ASGITransport`, so it does not open a network port. Fixtures reset the launcher’s process-global state around every test.

## Optional Real-HAR Workflow

Use this workflow when you have a local HAR with security-relevant content and want to exercise the running server, export files, and CLI validation together:

```bash
cd harscope/tests
source ../.venv/bin/activate

# Default integration-test port: 8299
./run_tests.sh /path/to/synthetic_fixture.har

# Choose a different port
./run_tests.sh /path/to/synthetic_fixture.har 8333
```

The runner starts and cleans up its own harscope process. Its temporary exports and logs are removed on exit.

### What It Tests

1. **All auto-detected findings redacted in export** — every flagged value becomes `[REDACTED]`
2. **EDL export + CLI validation** — EDL round-trips cleanly with `--validate`
3. **Toggle finding to KEEP** — kept values are preserved (not redacted) in export
4. **Manual redact non-flagged value** — manually added redactions work and can be removed
5. **Bulk deselect by severity** — warnings can be bulk-deselected while criticals stay
6. **Mixed EDL round-trip** — keep + manual + auto decisions all validate correctly
7. **Reset and reapply** — reset clears overrides, reapply restores defaults
8. **Full round-trip** — sanitized HAR rescanned shows zero findings

### Requirements

- [uv](https://docs.astral.sh/uv/) for the harscope launcher and its Python 3.12+ runtime
- The project virtual environment activated so `python3` resolves inside `.venv`
- `curl` (used by the shell script for API calls)
- A local HAR file with at least one security finding

The current runner's reset/reapply and zero-finding rescan assertions assume the fixture has no info-only findings, because info findings are intentionally kept by default.

### Fixture Coverage

Any HAR file with at least one security finding will work. For full coverage, test with:

- A HAR containing **WebSocket messages** with JSON payloads (exercises WS-specific container logic)
- A HAR containing **HTTP request/response bodies** with nested JSON (exercises array index path navigation)
- A HAR with both **critical and warning** severity findings (exercises bulk toggle)

The runner discovers findings and a non-flagged manual-redaction target. It skips the manual-redaction scenario when no suitable JSON body key exists, and it skips the severity-specific bulk scenario unless both warning and critical findings exist.

### Exit Codes

- `0` — all tests passed
- `1` — one or more tests failed (details printed to stdout)

## Adding Tests

Add deterministic API and scanner coverage to `test_api.py` using the synthetic fixtures in `conftest.py`. For a scenario that specifically requires a running server and a representative local HAR:

1. Add a scenario to `run_tests.sh`.
2. Add a mode to `verify_redaction.py` if verification is too complex for the shell runner.
3. Update the durable matrix and failure modes in `TEST_PLAN.md`.
