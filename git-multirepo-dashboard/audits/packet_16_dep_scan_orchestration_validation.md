# Packet 16: Dep Scan Orchestration — Validation Audit

**Validated:** 2026-03-10
**Validator:** Opus (high)
**Result:** PASS — all 16 acceptance criteria verified, 345/345 tests pass

## Test Results

- **Packet tests:** 16/16 pass (`tests/test_dep_scan_orchestration.py`)
- **Full suite:** 345/345 pass (329 prior + 16 new, zero regressions)

## Acceptance Criteria Verification

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `run_dep_scan_for_repo()` calls `parse_deps_for_repo()` | PASS | Line 856; test 1 mocks and verifies |
| 2 | Routes deps through correct ecosystem health checkers | PASS | Lines 866–889; test 3 verifies both Python+Node called for mixed repo |
| 3 | Upserts enriched results into `dependencies` table | PASS | Lines 892–909 INSERT OR REPLACE; tests 1, 2 verify rows written |
| 4 | Deletes stale deps no longer in manifest | PASS | Lines 911–922; test 4 verifies C removed after second scan |
| 5 | Handles health-check exceptions gracefully | PASS | try/except per checker; test 7 verifies no crash when Python check raises |
| 6 | Handles empty dep list (clears stale, no crash) | PASS | Lines 857–861; test 6 verifies pre-existing deps cleared |
| 7 | `run_fleet_scan(scan_id, "deps")` iterates all repos | PASS | Lines 940–965; test 8 verifies called once per repo |
| 8 | SSE progress events emitted after each repo | PASS | Lines 954–960; test 9 verifies 3 events with progress 1,2,3 |
| 9 | `scan_log` updated with correct status, repos_scanned, finished_at | PASS | Lines 967–978; test 10 verifies completed/2/not-null |
| 10 | Continues scanning remaining repos when one fails | PASS | Lines 948–952 continue-on-error; test 11 verifies repos_scanned=1, call_count=2 |
| 11 | `run_fleet_scan(scan_id, "full")` also runs dep scan | PASS | Line 997; test 12 verifies all three functions called |
| 12 | `GET /api/fleet` dep_summary with correct counts | PASS | Lines 4487–4503; test 13 verifies total=5, outdated=3, vulnerable=1 |
| 13 | dep_summary null when no deps scanned | PASS | Line 4503; test 14 verifies null |
| 14 | KPI vulnerable_deps reflects total across repos | PASS | Lines 4528–4543; test 15 verifies vulnerable_deps=3 |
| 15 | KPI outdated_deps reflects total outdated+major | PASS | Lines 4528–4543; test 15 verifies outdated_deps=4 |
| 16 | All existing tests still pass (no regressions) | PASS | 345/345 |

## Validation Focus Areas

- **DB writes**: INSERT OR REPLACE correctly uses composite PK `(repo_id, manager, name)`. Test 5 verifies upsert updates severity without duplication.
- **Stale dep cleanup**: After upserts, DB is queried for all repo deps; those not in the enriched list are deleted. Test 4 (partial removal) and test 6 (full clear) both verified.
- **dep_summary null vs zero**: `total_deps > 0` guard ensures null when no rows exist, not `{"total": 0, ...}`. Test 14 confirms.
- **KPI aggregation**: `outdated_deps` counts both `"outdated"` and `"major"` severities via `severity IN ('outdated', 'major')`. Test 15 confirms with mixed data across 2 repos.
- **Scan type routing**: `type="deps"` only calls `run_dep_scan_for_repo` (test 8); `type="full"` calls history + branch + dep (test 12).
- **Continue-on-error**: Exception in one repo's dep scan is caught; remaining repos still processed (test 11).
- **SSE events**: Progress events emitted for `type="deps"` with incremental progress values (test 9).
- **Mock isolation**: All tests mock health-check functions; no subprocess or network calls needed.
- **Regression**: Zero test modifications to prior packet tests. One legitimate update to packet 08's `test_scan_type_deps_completes` (renamed from `test_scan_type_deps_completes_immediately`): assertion changed from `repos_scanned == 0` (no-op placeholder) to `repos_scanned == 3` (real implementation). This is correct — the no-op was replaced.

## Files Modified

- `git_dashboard.py` — added `run_dep_scan_for_repo()`, modified `run_fleet_scan()` for type="deps" and type="full", modified `GET /api/fleet` for dep_summary and KPIs
- `tests/test_dep_scan_orchestration.py` — new, 16 tests
- `tests/test_full_scan_sse.py` — updated 1 test (no-op → real implementation assertion)

## Scope Creep Check

No features from later packets (17–23) were introduced. No extra endpoints, UI components, or analytics. Clean packet boundary.
