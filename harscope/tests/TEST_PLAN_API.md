# harscope API Test Plan

## Overview

Pytest-based test suite exercising all 25 backend API endpoints via `httpx.AsyncClient` with `ASGITransport` (no real HTTP server, no network calls).

## Test Infrastructure

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Fixtures, module import, state isolation, minimal HAR data |
| `tests/test_api.py` | 163 test cases across 34 test classes |
| `requirements-dev.txt` | Dev-only deps: pytest, httpx, pytest-cov, anyio |
| `pytest.ini` | Pytest configuration |

## Endpoint Inventory & Coverage

| # | Method | Route | Test Class | Tests |
|---|--------|-------|------------|-------|
| 1 | GET | `/` | `TestIndex` | HTML response, React mount |
| 2 | GET | `/api/status` | `TestStatus` | No file, loaded file, security summary shape |
| 3 | POST | `/api/open` | `TestOpen` | Missing path, nonexistent file, valid file |
| 4 | POST | `/api/open-content` | `TestOpenContent` | Valid HAR, invalid JSON, no-log JSON, missing fields, empty entries, malformed body |
| 5 | POST | `/api/upload` | `TestUpload` | Valid upload, invalid JSON, no file |
| 6 | GET | `/api/entries` | `TestEntries` | No file, pagination, offsets, domain/status/search filters, validation (negative offset, limit 0, limit >200), entry shape |
| 7 | GET | `/api/entry/{index}` | `TestEntryDetail` | No file, valid/second/OOR/negative index, response structure |
| 8 | GET | `/api/waterfall` | `TestWaterfall` | No file, basic data, timing phases, pagination, domain filter |
| 9 | GET | `/api/domains` | `TestDomains` | No file, domain list |
| 10 | GET | `/api/stats` | `TestStats` | No file, shape validation, error rate |
| 11 | GET | `/api/security` | `TestSecurity` | No file, findings exist, JWT/auth/HTTP/password detection, finding shape, internal fields stripped |
| 12 | POST | `/api/security/toggle` | `TestSecurityToggle` | Toggle on/off, nonexistent ID, missing field |
| 13 | POST | `/api/security/bulk` | `TestSecurityBulk` | Deselect all, select all, filter by severity, missing action |
| 14 | POST | `/api/redaction/manual` | `TestManualRedaction` | No file, add/remove manual, remove nonexistent, missing fields |
| 15 | POST | `/api/redaction/remove-manual` | (in TestManualRedaction) | Remove existing, remove nonexistent |
| 16 | POST | `/api/redaction/reset` | `TestRedactionReset` | No file, reset restores defaults & clears manual |
| 17 | POST | `/api/redaction/reapply-auto` | `TestReapplyAuto` | No file, reapply after deselect |
| 18 | GET | `/api/redaction/decisions` | `TestDecisions` | No file, structure, decision shape, manual decisions included |
| 19 | GET | `/api/sequence` | `TestSequence` | No file, basic sequence, domain filter, nonexistent domain |
| 20 | GET | `/api/sequence/flows` | (in TestSequence) | No file, flows list |
| 21 | POST | `/api/export/har` | `TestExportHar` | No file, valid HAR output, critical redacted, non-redacted preserved |
| 22 | POST | `/api/export/edl` | `TestExportEdl` | No file, EDL structure, decision shape, summary counts |
| 23 | POST | `/api/validate` | `TestValidate` | No file, invalid JSON, roundtrip validation, empty EDL, OOR entry |
| 24 | POST | `/api/export/csv` | `TestExportCsv` | No file, CSV content |
| 25 | POST | `/api/export/report` | `TestExportReport` | No file, MD report, HTML report, default format |

## Additional Test Groups

| Class | Focus |
|-------|-------|
| `TestSecurityDetection` | Pattern-specific detection: JWT, AWS keys, GitHub tokens, private keys, connection strings, opaque tokens, redacted-value skip, cookie flags |
| `TestRedactionWorkflow` | End-to-end: toggle→export, manual→EDL, manual→HAR export, reload clears state |
| `TestEdgeCases` | Empty entries, missing timings, null body size, very long URLs, non-UTF8 upload, large offset, multiple reloads |
| `TestOpenPathValidation` | Path validation: rejects non-.har, device paths, .txt files |
| `TestBulkToggleValidation` | Rejects invalid action values (Literal constraint) |
| `TestReportFormatValidation` | Rejects invalid report formats (Literal constraint) |
| `TestHtmlReportXss` | HTML report escapes filenames and domains (XSS prevention) |
| `TestMarkdownReportEscaping` | Markdown report escapes pipes in domain names |
| `TestUploadSizeLimit` | Rejects oversized content, explicit UTF-8 error on binary upload |
| `TestEdlSizeLimit` | Rejects oversized EDL uploads |
| `TestContentDisposition` | Filename sanitization in Content-Disposition headers |
| `TestPercentiles` | Correct p50 calculation with off-by-one fix |
| `TestFmtNegative` | _fmt_size and _fmt_time return 'unknown' for negative values |
| `TestScannerDepthGuard` | Nested JSON-in-JSON scans correctly with proper depth tracking |
| `TestNavigateJsonNull` | Handles null JSON values without breaking navigation |
| `TestCsvFindings` | CSV findings export: no-file, structure, includes manual redactions |
| `TestSecurityPatterns` | Bearer token, Basic auth, private IP info severity detection |
| `TestBulkToggleCategory` | Bulk toggle by category filters correctly |
| `TestReapplyPreservesManual` | Reapply auto preserves manual redactions |
| `TestResetClearsManual` | Reset clears manual redactions |
| `TestInfoSeverityHandling` | Info findings not redacted by default, reapply doesn't redact info |

## Assumptions

- The test HAR fixture contains known secrets (JWT, Bearer token, password field, API key, HTTP request) to verify detection coverage.
- Scanner consolidation merges multiple findings at the same (entryIndex, location) into a single finding with the highest severity.
- `_require_file()` returns HTTP 400 for all data endpoints when no file is loaded.
- Query parameter validation (`ge=0`, `le=200`, etc.) is enforced by FastAPI and returns 422.

## Running Tests

```bash
cd harscope
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install fastapi uvicorn python-multipart anyio

# Run all tests
.venv/bin/python -m pytest tests/test_api.py -v

# Run with coverage
.venv/bin/python -m pytest tests/test_api.py --cov=harscope_mod --cov-report=term-missing

# Run a single test class
.venv/bin/python -m pytest tests/test_api.py::TestExportHar -v
```
