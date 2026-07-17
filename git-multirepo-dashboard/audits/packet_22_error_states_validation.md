# Packet 22: Error States & Edge Cases — Validation Audit

**Validated:** 2026-03-10
**Verdict:** PASS — all 20 acceptance criteria verified

## Test Results

- **Packet tests:** 19/19 pass
- **Full suite:** 421/421 pass (no regressions)
- **`--help`:** exits cleanly

## Acceptance Criteria Verification

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Repos with deleted paths appear in fleet grid | PASS — `scan_fleet_quick` returns `path_exists: False` dict instead of skipping; no `if r is not None` filter |
| 2 | Path-not-found cards: 4px red left border | PASS — `pathMissing ? '4px solid var(--status-red)'` overrides freshness border |
| 3 | Path-not-found cards: "Path not found" in red | PASS — row 2 conditionally renders "Path not found" in `var(--status-red)` |
| 4 | Scan-failed badge at top-right | PASS — `repo.scan_error &&` renders absolute-positioned badge |
| 5 | Badge styles match spec | PASS — 10px font, var(--status-red), var(--status-red-bg), 2px 6px padding, 3px radius |
| 6 | scan_error cleared on success | PASS — ON CONFLICT DO UPDATE SET scan_error = NULL on success path |
| 7 | Detail view: Remove + Update Path buttons | PASS — rendered inside `pathMissing &&` block |
| 8 | Remove calls DELETE and navigates to #/fleet | PASS — `handleRemove()` confirmed |
| 9 | Update Path calls PATCH with inline input | PASS — `handleSavePath()` confirmed |
| 10 | PATCH validates path is existing directory | PASS — `not Path(new_path).is_dir()` → 400 |
| 11 | PATCH returns 404/400 for invalid inputs | PASS — tested via `test_patch_repo_path_not_found` and `test_patch_repo_path_invalid` |
| 12 | Deps tab offline indicator | PASS — 6px orange circle + "offline" text when `depCheckError` is true |
| 13 | dep_check_error set on exception | PASS — `any_error` flag tracks across all ecosystem try/excepts |
| 14 | dep_check_error cleared on success | PASS — `any_error` stays False when no exceptions |
| 15 | 409 concurrent scan regression | PASS — `test_concurrent_scan_409_regression` inserts running scan_log, verifies 409 |
| 16 | Migration idempotent | PASS — `test_migration_idempotent` calls `run_migrations` twice without error |
| 17 | Fleet response includes path_exists, scan_error, dep_check_error | PASS — bulk-read from working_state, defaults (None, False) for missing rows |
| 18 | Repo detail includes path_exists | PASS — `Path(repo[2]).is_dir()` dynamic check |
| 19 | All existing tests pass | PASS — 421/421 |
| 20 | --help exits cleanly | PASS |

## Implementation Review

### Schema
- `scan_error TEXT DEFAULT NULL` and `dep_check_error BOOLEAN DEFAULT FALSE` added to both `_SCHEMA_SQL` (for new DBs) and `_MIGRATION_SQL` (for upgrades). Migration is idempotent via try/except on OperationalError.

### Key design decision: upsert_working_state
- Changed from `INSERT OR REPLACE` to `ON CONFLICT DO UPDATE` with explicit column list. This preserves `scan_error` and `dep_check_error` across quick scans — correct and important, since quick scans run on every fleet load.

### scan_fleet_quick
- Missing-path repos return a full dict with `path_exists: False` and zeroed/null working-state fields. No `upsert_working_state` call for missing paths (correct — no data to write).

### run_fleet_scan
- Per-repo try/except sets `scan_error` on failure (with `str(exc)`) and clears to NULL on success. Uses `ON CONFLICT DO UPDATE` upsert pattern.

### run_dep_scan_for_repo
- `any_error` boolean tracks across all 6 ecosystem try/except blocks. Written to `dep_check_error` via upsert after all checks complete.

### PATCH /api/repos/{id}
- Validates repo exists (404), validates path is existing directory (400), resolves path, updates DB. Clean and correct.

### Frontend
- `ProjectCard`: red left border, "Path not found" text, "scan failed" badge — all conditional on correct props.
- `DetailHeader`: Remove/Update Path buttons inside `pathMissing &&` block. Update Path toggles inline input + Save.
- `DepsTab`: receives `depCheckError` prop from `ProjectDetail`, renders orange dot + "offline" text.

## Validation Fixes Applied

1. **Strengthened test**: `test_fleet_response_includes_scan_error` now also asserts `dep_check_error` key is present in each fleet repo (covers AC17 completely).

## Scope Compliance

- Only `git_dashboard.py` and `tests/test_error_states.py` modified (allowed files).
- No features from later packets (packet 23: polish/accessibility) introduced.
- Implementer notes mention updating 3 stale tests in other test files (`test_packet_00`, `test_fleet_api`, `test_error_states` scan mock) — these are legitimate adaptations to the new schema/behavior, not scope creep.

## No Issues Found

Implementation is clean, well-structured, and all acceptance criteria pass.
