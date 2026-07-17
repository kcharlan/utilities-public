# Packet 07: Branch Scan — Validation Audit

**Validator:** Opus 4.6
**Date:** 2026-03-10
**Status:** PASS — all 13 acceptance criteria verified

## Test Results

- **Packet tests:** 13/13 passed
- **Full suite:** 138/138 passed (no regressions)

## Acceptance Criteria Verification

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `parse_branches` correctly parses multi-line git branch format output with null-byte delimiters | PASS | `split("\x00", 1)` at line 726; tested by `test_parse_multiple_branches` |
| 2 | `parse_branches` identifies the default branch by matching against the `default_branch` parameter | PASS | `name == default_branch` at line 740; tested by `test_parse_default_branch_detection` |
| 3 | `parse_branches` marks branches with `last_commit_date` older than 30 days as `is_stale=True` | PASS | `_is_stale()` uses `timedelta(days=30)` cutoff; tested by `test_parse_stale_detection` |
| 4 | `parse_branches` marks branches with missing/invalid dates as `is_stale=True` | PASS | `_is_stale()` returns True for falsy/unparseable dates; tested by `test_parse_branch_no_commits` |
| 5 | `parse_branches` returns an empty list for empty input without crashing | PASS | Early return at line 715-716; tested by `test_parse_empty_output` |
| 6 | `parse_branches` handles branch names containing slashes (e.g., `feature/auth/v2`) | PASS | Null-byte delimiter avoids slash ambiguity; tested by `test_parse_branch_with_slashes` |
| 7 | `scan_branches` invokes `run_git` with `git branch --format='%(refname:short)%x00%(committerdate:iso-strict)'` | PASS | Line 756 uses `%x00` (git format escape, not literal `\x00`); tested by `test_scan_branches_calls_run_git` |
| 8 | `upsert_branches` writes correct rows to the `branches` table | PASS | DELETE+INSERT at lines 768-777; tested by `test_upsert_branches_insert` |
| 9 | `upsert_branches` fully replaces existing branches for a repo (DELETE+INSERT) | PASS | Tested by `test_upsert_branches_replaces_all` — "dev" removed, "feature" added |
| 10 | `upsert_branches` handles empty branch lists (clears all rows for the repo) | PASS | `if branches:` guard at line 769; tested by `test_upsert_branches_empty_list` |
| 11 | `run_branch_scan` returns the count of branches parsed | PASS | `return len(branches)` at line 796; tested by `test_run_branch_scan_returns_count` |
| 12 | CASCADE delete from `repositories` removes related `branches` rows | PASS | Schema: `REFERENCES repositories(id) ON DELETE CASCADE`; tested by `test_run_branch_scan_cascade_delete` with `PRAGMA foreign_keys = ON` |
| 13 | All existing tests (125+) continue to pass | PASS | 138/138 full suite passes |

## Validation Focus Area Checks

| Focus Area | Result | Notes |
|------------|--------|-------|
| `%x00` git format escape (not literal `\x00`) | PASS | Line 756 — same lesson learned from packet 06 applied correctly |
| Timezone-aware ISO 8601 dates | PASS | `datetime.fromisoformat()` handles offsets like `-05:00` |
| 30-day boundary (exactly 30d = NOT stale) | PASS | Test uses `30d - 1s` margin to avoid race condition on exact boundary |
| DELETE+INSERT in single transaction | PASS | aiosqlite autocommit=off by default; single `await db.commit()` at line 778 commits both operations |
| Branch names with slashes | PASS | `split("\x00", 1)` splits only on first null byte; slash in name preserved |
| Empty repos (no branches) | PASS | `parse_branches("")` returns `[]`; `upsert_branches(db, id, [])` clears rows cleanly |

## Files Modified (Allowed Files Check)

| File | Allowed? | Change Type |
|------|----------|-------------|
| `git_dashboard.py` | Yes | Added branch scan functions (lines 689-796) |
| `tests/test_branch_scan.py` | Yes | New test file (13 tests) |

No files outside the allowed list were modified.

## Implementation Quality Notes

- **Function placement:** After full-history scan, before repo discovery — matches packet spec
- **`run_branch_scan` reads `default_branch` from DB:** Falls back to `"main"` if no row found (defensive)
- **`_is_stale` handles `ValueError` and `TypeError`:** Robust against malformed date strings
- **Test helper `_make_db_with_repo`:** Enables `PRAGMA foreign_keys = ON` for CASCADE testing
- **No scope creep:** No API endpoints, no UI, no multi-repo orchestration — all deferred to later packets
