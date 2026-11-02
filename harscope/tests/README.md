# harscope Tests

Automated API, CLI validation, and Playwright browser tests use synthetic HAR fixtures.

## Files

| File | Description |
|---|---|
| `test_api.py` | FastAPI routes, scanner behavior, exports, validation, and robustness cases |
| `test_cli_validate.py` | CLI validation and redaction workflow coverage |
| `test_e2e.py` | Chromium coverage for offline loading, page errors, and interaction |
| `test_redaction_matrix.py` | Synthetic redaction shapes across export formats and fail-closed checks |
| `test_token_tiers.py` | Token thresholds and WebSocket redaction and validation |
| `conftest.py` | ASGI client, isolated application state, and synthetic HAR fixtures |

## Running the Suite

From the repository root, run `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py harscope`. If Chromium is missing, install it once with `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py harscope --install-browsers`.

The API tests import the FastAPI application in-process and use `httpx.AsyncClient` with `ASGITransport`, so those tests do not open a network port. Their fixtures reset the launcher's process-global state around every test. CLI tests use the registered test interpreter. Playwright starts a separate local server on a free port and stops it after the module. The browser UI embeds its Preact runtime, icons, fonts and styles. Chromium tests verify offline loading, theme output, interaction, and browser error cleanliness. Safari and Firefox are not covered by the automated browser test.

## Adding Tests

Add deterministic API and scanner coverage with synthetic fixtures. Keep private captures outside the repository.
