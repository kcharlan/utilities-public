# Packet 10 Validation: Project Detail View & Activity Chart

**Status: VALIDATED**
**Date: 2026-03-10**
**Tests: 13/13 packet, 178/178 full suite**

## Acceptance Criteria Verification

| # | Criterion | Result |
|---|-----------|--------|
| 1 | `GET /api/repos/{valid_id}` returns 200 with id, name, path, runtime, default_branch, working_state, last_full_scan_at | PASS — all fields present, working_state includes repo_id, has_uncommitted, modified_count, untracked_count, staged_count, current_branch, checked_at |
| 2 | `GET /api/repos/{invalid_id}` returns 404 | PASS — returns `{"detail": "Repo not found"}` |
| 3 | `GET /api/repos/{id}/history?days=90` returns 200 with repo_id, days, data | PASS — data entries contain date, commits, insertions, deletions, files_changed |
| 4 | History defaults to 90 days when days param omitted | PASS — response `days` field is 90 |
| 5 | History excludes dates outside requested window | PASS — 120-day-old row excluded when days=90 |
| 6 | History returns 404 for non-existent repos | PASS |
| 7 | Card click navigates to `#/repo/{id}` and renders ProjectDetail | PASS — ContentArea dispatches `tab === 'repo'` to `<ProjectDetail repoId={repoId} />` |
| 8 | Detail header shows name, path, runtime badge, default branch, last scan time | PASS — DetailHeader renders all fields with RuntimeBadge reuse |
| 9 | Back button navigates to `#/fleet` | PASS — `onClick={() => { window.location.hash = '#/fleet'; }}` |
| 10 | Sub-tab navigation shows Activity, Commits, Branches, Dependencies | PASS — SUB_TABS constant has all 4 entries |
| 11 | Activity sub-tab is default | PASS — `useState('activity')` in ProjectDetail |
| 12 | Activity chart renders diverging area chart (insertions green up, deletions red down, net blue line) | PASS — AreaChart with `stackOffset="sign"`, deletions negated, net via `<Area fill="none">` (avoids Line-inside-AreaChart gotcha) |
| 13 | TimeRangeSelector renders 5 options (30d, 90d, 180d, 1y, All), defaults to 90d | PASS — TIME_RANGES constant, ActivityTab `useState(90)` |
| 14 | Changing time range refetches history data | PASS — useEffect depends on `[repoId, selectedDays]` |
| 15 | Tooltip shows date, insertions, deletions, net, commits | PASS — CustomTooltip renders all five fields with color coding |
| 16 | Global table CSS styles defined | PASS — .table-container, .table-header, .table-row, .table-empty all present |
| 17 | Commits, Branches, Dependencies sub-tabs render placeholder empty states | PASS — PlaceholderTab component used for all three |
| 18 | All tests pass, no regressions | PASS — 178/178 |

## Validation Focus Area Review

- **Diverging chart**: `stackOffset="sign"` used correctly. Deletions negated (`-d.deletions`). Insertions and deletions share `stackId="stack"`, net line has no stackId (overlays independently). Correct.
- **Recharts container**: Uses `<AreaChart>` with `<Area fill="none">` for net line, correctly avoiding the `<Line>` inside `<AreaChart>` silent-ignore gotcha.
- **Date gap filling**: `fillDateGaps` fills missing dates with zeros. "All" mode (days=9999) fills from earliest data date to today. Empty data in All mode returns `[]` — no crash.
- **Empty history**: ActivityChart shows "No activity data for this period" — safe handling.
- **Back button**: Sets `window.location.hash = '#/fleet'` — works correctly.
- **parseRoute**: Extracts repo ID via `hash.slice(7)` from `#/repo/...` — correct.

## Issues Found and Fixed

1. **Unused import** (minor): `get_repo_detail` at line 2752 imported `datetime as _dt_mod` but never used it. Only `get_repo_history` needs this import. Removed the unnecessary import.

2. **Weak test** (test strength): `test_global_table_styles` only checked `.table-header` and `.table-row`. Strengthened to also verify `.table-container` and `.table-empty` — all four CSS classes specified in the packet scope.

## Scope Compliance

- Only `git_dashboard.py` and `tests/test_project_detail.py` were modified — matches allowed files.
- No features from later packets introduced (Scan Now is placeholder no-op, sub-tabs render PlaceholderTab).
- No scope creep detected.

## Regressions

None. Full suite 178/178 passes before and after validation fixes.
