# Packet 11 Validation: Commits & Branches Sub-tabs

**Validator:** Claude Opus 4.6
**Date:** 2026-03-10
**Result:** PASS — all 21 acceptance criteria verified

## Test Results

- **Packet tests:** 15/15 pass
- **Full suite:** 193/193 pass (0 regressions)

## Acceptance Criteria Verification

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | GET /api/repos/{id}/commits returns 200 with keys: commits, page, per_page, total | PASS | test_commits_basic_shape |
| 2 | Each commit has hash, date, author, message, insertions, deletions, files_changed | PASS | test_commits_basic_shape; subject→message mapping at line 3035 |
| 3 | Pagination works: ?page=2&per_page=10 skips first 10, returns up to 10 | PASS | test_commits_pagination_params (also verifies non-overlapping pages) |
| 4 | total reflects actual commit count via git rev-list --count --all | PASS | test_commits_total_accurate |
| 5 | GET /api/repos/{id}/commits returns 404 for unknown repo | PASS | test_commits_404_unknown_repo |
| 6 | GET /api/repos/{id}/branches returns 200 with key: branches | PASS | test_branches_basic_shape |
| 7 | Each branch has name, last_commit_date, is_default, is_stale | PASS | test_branches_basic_shape (includes bool type assertions) |
| 8 | Branches sorted: default first, then by last_commit_date desc | PASS | test_branches_sort_order (very-old default branch still first) |
| 9 | GET /api/repos/{id}/branches returns 404 for unknown repo | PASS | test_branches_404_unknown_repo |
| 10 | CommitsTab renders table with Date, Message, +/-, Files columns | PASS | Code verified at lines 2471-2496 + test_commits_tab_component_exists |
| 11 | Pagination controls (Prev, page indicator, Next) below table | PASS | Code at lines 2498-2512 + test_pagination_ui_exists |
| 12 | Insertions green (--status-green), deletions red (--status-red) | PASS | Code at lines 2488, 2490 |
| 13 | BranchesTab renders Branch, Last Commit, Status columns | PASS | Code at lines 2549-2553 + test_branches_tab_component_exists |
| 14 | Default branch shows blue "default" badge | PASS | Code at line 2566 (--accent-blue, --accent-blue-dim) |
| 15 | Stale branches show orange "stale (N days)" badge | PASS | Code at lines 2570-2571; days computed client-side via staleDays() |
| 16 | Active branches show "active" in muted text | PASS | Code at line 2574 (--text-muted) |
| 17 | PlaceholderTab not used for Commits or Branches | PASS | test_placeholder_tab_not_used_for_commits_branches; code uses CommitsTab/BranchesTab at lines 2624-2625 |
| 18 | #/repo/{id}/commits opens Commits sub-tab | PASS | parseRoute (line 1398) extracts subTab; passed as initialSubTab (line 2654) |
| 19 | #/repo/{id}/branches opens Branches sub-tab | PASS | Same parseRoute mechanism |
| 20 | Clicking sub-tab updates window.location.hash | PASS | handleSubTabChange at line 2607 |
| 21 | All existing tests (178+) still pass | PASS | 193/193 (15 new + 178 prior) |

## Validation Focus Area Review

- **Commit pagination accuracy:** Verified via test with 15-commit repo, page=2/per_page=5 returns non-overlapping commits. --skip and --max-count correctly computed as `(page-1)*per_page` (line 3019).
- **Git subprocess calls:** Format string uses `%x00` (git escape), not literal `\x00`. Correct from prior packet 06 validation.
- **Branch sort order:** test_branches_sort_order inserts default branch with 2020 date, still sorted first. ORDER BY is_default DESC, last_commit_date DESC (line 3059).
- **Stale day calculation:** Client-side `staleDays()` function at line 2532 computes days from `last_commit_date` — not sent by server.
- **Hash routing:** parseRoute at line 1398 correctly extracts optional sub-tab segment after repo ID. ProjectDetail receives `initialSubTab` prop, `key={repoId}` forces remount on repo change.
- **Empty states:** Both components show "No commits found" / "No branches found" in table-empty div. Tested via test_commits_empty_repo and test_branches_empty.
- **Regression:** Full suite 193/193 — no impact on Activity sub-tab or fleet overview.

## Code Quality Notes

- Parameter clamping: `page = max(1, page)`, `per_page = max(1, min(100, per_page))` — correct.
- Disk path check before git subprocess (line 3009) — good defensive coding.
- `is_default` and `is_stale` correctly cast from SQLite 0/1 to Python `bool()` (line 3069-3070).
- CSS vars `--accent-blue-dim` and `--status-orange-bg` already existed in the design system.
- No scope creep detected — no features from later packets introduced.

## Files Modified

- `git_dashboard.py` — commits/branches endpoints + CommitsTab/BranchesTab components + parseRoute sub-tab extension
- `tests/test_commits_branches_subtabs.py` — 15 tests (new file)

Both files are in the packet's Allowed Files list.
