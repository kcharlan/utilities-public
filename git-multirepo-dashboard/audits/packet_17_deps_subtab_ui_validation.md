# Packet 17 Validation: Dependencies Sub-tab UI

**Validator:** Claude Opus 4.6
**Date:** 2026-03-10
**Status:** VALIDATED

## Test Results

- **Packet tests:** 11/11 pass
- **Full suite:** 356/356 pass (no regressions)

## Acceptance Criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | GET /api/repos/{id}/deps returns 200 with manager groups array | PASS — `_fetch_repo_deps` returns list of `{manager, packages, checked_at}` dicts |
| 2 | Each manager group has `manager`, `packages`, `checked_at` | PASS — built at line 4619, tested by `test_get_deps_response_shape` |
| 3 | Each package has `name`, `current_version`, `wanted_version`, `latest_version`, `severity`, `advisory_id` | PASS — lines 4629–4635, tested by `test_get_deps_response_shape` |
| 4 | Packages sorted: vulnerable → major → outdated → ok, then alphabetical | PASS — SQL CASE lines 4601–4607, tested by `test_get_deps_sort_order` |
| 5 | Empty deps returns `[]` | PASS — tested by `test_get_deps_empty_repo` |
| 6 | Nonexistent repo returns 404 | PASS — existence check at line 4643, tested by `test_get_deps_404` |
| 7 | POST scan/deps calls `run_dep_scan_for_repo` and returns updated deps | PASS — line 4659 calls function, returns `_fetch_repo_deps`; tested by `test_check_now_endpoint` with mock |
| 8 | POST nonexistent repo returns 404 | PASS — tested by `test_check_now_404` |
| 9 | DepsTab component exists in HTML_TEMPLATE | PASS — `function DepsTab` at line 3966, tested by `test_deps_tab_component_exists` |
| 10 | Table columns: Package, Current, Latest, Status | PASS — lines 4049–4052 |
| 11 | Severity color mapping uses CSS vars | PASS — `severityColor()` at lines 3996–4002 uses `var(--status-green/yellow/orange/red)` |
| 12 | "Last checked: X ago" appears below each manager section | PASS — line 4090 renders `Last checked: {timeAgo(group.checked_at)}` |
| 13 | "Check Now" button present, secondary style, disabled while scanning | PASS — lines 4030–4036, `className="btn btn-secondary"`, `disabled={scanning}` |
| 14 | Empty state shows "No dependencies detected" | PASS — lines 4019–4024, uses `.table-empty` class |
| 15 | All existing tests pass | PASS — 356/356 |

## Validation Focus Area Review

- **Sort order:** SQL CASE correctly orders vulnerable(0) → major(1) → outdated(2) → else(3), then name. Test covers all 4 severities.
- **Null safety:** `checked_at` max-tracking handles null via `if checked_at and (not existing["checked_at"] or ...)`. Version fields use `|| '—'` fallback in JSX. `advisory_id` falls back to `'vulnerable'` text.
- **PlaceholderTab replaced:** Only one `PlaceholderTab` definition remains (for future tabs). Line 4139 routes `activeSubTab === 'deps'` to `<DepsTab>`, not `PlaceholderTab`.
- **Check Now calls real function:** Line 4659 calls `run_dep_scan_for_repo(db, repo_id_val, repo_path)` — real implementation, not a no-op.
- **CSS vars match spec:** `--status-green`, `--status-yellow`, `--status-orange`, `--status-red` — all correct per design system.

## Code Quality Notes

- `_fetch_repo_deps` helper is properly shared between GET and POST endpoints (DRY).
- Manager grouping uses an index dict for O(n) performance.
- Version fontWeight comparison (`pkg.current_version !== pkg.latest_version`) correctly highlights when latest differs.
- Vulnerable severity uses `fontWeight: 600` as specified.

## Issues Found

None. Implementation is clean and complete.
