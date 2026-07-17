# Packet 08 Validation: Full Scan Orchestration & SSE

**Validator:** Claude Opus 4.6
**Date:** 2026-03-10
**Result:** PASS — validated

## Test Results

- Packet tests: 16/16 pass (originally 14, strengthened to 16)
- Full suite: 154/154 pass (was 152 before strengthening)
- No regressions

## Acceptance Criteria Verification

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | POST /api/fleet/scan returns `{"scan_id": <int>}` with HTTP 200 | PASS | `test_post_scan_creates_scan_log` |
| 2 | Creates scan_log row with scan_type, started_at (ISO 8601), status="running" | PASS | `test_post_scan_creates_scan_log`, `test_scan_log_started_at_is_iso8601` |
| 3 | Returns HTTP 409 when a scan is already running | PASS | `test_post_scan_rejects_concurrent` (in-memory), `test_post_scan_rejects_concurrent_db_guard` (DB fallback) |
| 4 | Invalid type returns HTTP 422 or 400 | PASS | `test_post_scan_invalid_type` — uses `Literal["full", "deps"]` → 422 |
| 5 | Succeeds after previous scan completed | PASS | `test_post_scan_allows_after_previous_completed` |
| 6 | Calls run_full_history_scan and run_branch_scan for each repo | PASS | `test_run_fleet_scan_iterates_repos` |
| 7 | Processes repos sequentially | PASS | `test_run_fleet_scan_sequential_order` — verifies interleaved history/branch pattern |
| 8 | Continues scanning when one repo fails | PASS | `test_run_fleet_scan_continues_on_error` |
| 9 | Updates scan_log.repos_scanned after each repo | PASS | Code verified at line 868-872; tested via final count assertions |
| 10 | Sets status="completed" and finished_at on success | PASS | `test_run_fleet_scan_updates_scan_log` |
| 11 | Sets status="failed" if zero repos succeeded | PASS | `test_run_fleet_scan_sets_failed_on_total_failure` |
| 12 | SSE endpoint returns text/event-stream | PASS | Code at line 2135 uses `media_type="text/event-stream"` |
| 13 | SSE events match documented shape | PASS | `test_sse_progress_events_shape` |
| 14 | type="deps" completes immediately with repos_scanned=0 | PASS | `test_scan_type_deps_completes_immediately` |
| 15 | GET /api/fleet returns branch_count/stale_branch_count from branches table | PASS | `test_fleet_endpoint_includes_branch_counts` |
| 16 | All existing tests continue to pass | PASS | 154/154 |

## Validation Focus Areas

| Focus Area | Status | Details |
|------------|--------|---------|
| 409 dual guard (module-level + DB) | PASS | Both paths tested. In-memory fast path at line 2088, DB fallback at lines 2092-2097. New test `test_post_scan_rejects_concurrent_db_guard` added during validation. |
| `_active_scan_id` cleared on crash | PASS | `finally` block at line 893-894 clears unconditionally |
| SSE format `data: {...}\n\n` | PASS | Line 2129: `f"data: {json.dumps(event)}\n\n"` |
| Background task opens own DB connection | PASS | Line 830: `aiosqlite.connect(str(DB_PATH))` — not using `get_db` dependency |
| No crash without SSE listener | PASS | `emit_scan_progress` checks `if q:` at line 815 before put |
| Empty repos list (0 repos) | PASS | Line 876: `if total == 0 or scanned > 0: status = "completed"`. New test `test_run_fleet_scan_empty_fleet` added. |
| finished_at populated for both completed and failed | PASS | Completed: line 881. Failed: same path. Assertion added to `test_run_fleet_scan_sets_failed_on_total_failure`. |
| No race condition on repo query | PASS | Repos queried inside background task (line 848-849), not before launch |

## Tests Strengthened During Validation

1. **`test_post_scan_rejects_concurrent_db_guard`** (new): Tests the DB fallback path for 409 rejection, where `_active_scan_id` is None but a running row exists in scan_log. Covers the server-restart scenario.
2. **`test_run_fleet_scan_empty_fleet`** (new): Tests 0 repos → immediate completion with status="completed".
3. **`test_run_fleet_scan_sets_failed_on_total_failure`** (strengthened): Added assertion for `finished_at` being populated and valid ISO 8601 on failure.

## Scope Creep Check

- No files outside allowed list modified
- No features from later packets added
- Fleet endpoint update (branch_count/stale_branch_count) is minimal and within packet scope
- No UI changes

## Code Quality Notes

- Clean implementation following the packet doc's pseudocode closely
- Proper use of `global` for module-level state mutation
- `logger.error` for per-repo failures (not silent swallowing)
- `StreamingResponse` imported from `fastapi.responses` (already available)
- `Literal["full", "deps"]` for type validation is clean and gives automatic 422
