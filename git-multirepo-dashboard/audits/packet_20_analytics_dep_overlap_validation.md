# Packet 20: Analytics: Dep Overlap — Validation Report

**Validator:** Opus 4.6
**Date:** 2026-03-10
**Status:** VALIDATED

## Test Results

- **Packet tests:** 12/12 pass (includes bonus `test_dep_overlap_null_versions_all_null`)
- **Full suite:** 394/394 pass — no regressions

## Acceptance Criteria Verification

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `GET /api/analytics/dep-overlap` returns 200 with `{"packages": [...]}` | PASS | `test_dep_overlap_empty_db`, `test_dep_overlap_two_repos_shared` |
| 2 | Each package entry has `name` (str), `manager` (str), `repos` (array), `version_spread` (str), `count` (int) | PASS | `test_dep_overlap_response_shape` |
| 3 | Each repo entry has `repo_id` (str), `name` (str), `version` (str or null) | PASS | `test_dep_overlap_response_shape` |
| 4 | Only packages in 2+ repos included | PASS | `test_dep_overlap_single_repo_excluded` |
| 5 | Sorted by `count` descending | PASS | `test_dep_overlap_sorted_by_count_desc` |
| 6 | `version_spread` shows `"min - max"` or empty string if all null | PASS | `test_dep_overlap_two_repos_shared`, `test_dep_overlap_version_spread_single_version`, `test_dep_overlap_null_versions_all_null` |
| 7 | Same package under different managers = separate entries | PASS | `test_dep_overlap_same_package_different_managers` |
| 8 | Empty database returns `{"packages": []}` | PASS | `test_dep_overlap_empty_db` |
| 9 | `DepOverlap` function component exists in HTML_TEMPLATE | PASS | `test_dep_overlap_component_exists` |
| 10 | Component renders table using global `data-table` CSS class | PASS | `test_dep_overlap_table_uses_global_styles`, line 4581 `className="data-table"` |
| 11 | "Used In" count clickable, expands to show per-repo version details | PASS | Line 4604-4609: onClick → toggleExpanded, expanded rows at lines 4615-4625 |
| 12 | Expanded rows show repo name and version, indented 24px | PASS | Line 4617 `paddingLeft: '24px'`, line 4620 `{repo.name} — {repo.version}` |
| 13 | Chevron indicator shows expand/collapse state | PASS | Line 4608 `{isExpanded ? '▾' : '▸'}` |
| 14 | Empty state message displayed when no shared deps | PASS | Line 4570-4573: "No shared dependencies found across repos." |
| 15 | All existing tests pass (no regressions) | PASS | 394/394 |

## Validation Focus Areas

- **2+ repo threshold:** Verified by `test_dep_overlap_single_repo_excluded` — packages in only 1 repo correctly excluded.
- **Grouping by (name, manager):** `test_dep_overlap_same_package_different_managers` — lodash under npm and pip are separate entries.
- **NULL version handling:** `test_dep_overlap_null_versions` — NULL version repos appear in repos array with `version: null`, excluded from spread. `test_dep_overlap_null_versions_all_null` — all-NULL → empty string spread.
- **Expand/collapse independence:** Component uses `Set` of keys (line 4538); toggling one key doesn't affect others.
- **Component NOT rendered in analytics tab:** Confirmed — `DepOverlap` appears only at its function definition (line 4535). Not referenced in ContentArea or any tab rendering. Correct for packet 20; wiring is packet 21 scope.
- **Global table styling:** Uses `className="data-table"` (line 4581), matching existing project convention.

## Implementation Quality

- **API:** Single JOIN query grouped with `itertools.groupby` in Python. Clean, efficient. `ORDER BY d.name, d.manager, r.name` ensures groupby correctness.
- **Component:** Proper React patterns — `useState` for expanded Set, `useEffect` for fetch, loading state, empty state. Expand key format `name:manager` is unique per entry.
- **Tests:** 12 tests covering all 11 specified scenarios + bonus all-NULL edge case. Assertions are specific and meaningful.
- **No scope creep:** No filtering, no severity indicators, no analytics tab wiring — all correctly deferred.

## Issues Found

None.

## Files Modified (Verified)

- `git_dashboard.py` — API endpoint (lines 5205-5239), DepOverlap component (lines 4534-4633)
- `tests/test_analytics_dep_overlap.py` — new, 12 tests

Both files are in the packet's Allowed Files list.
