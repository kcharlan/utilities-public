# Packet 06 Validation: Git Full History Scan

**Validator:** Opus 4.6
**Date:** 2026-03-10
**Result:** PASS — all 15 acceptance criteria verified (after 1 critical bug fix)

## Bug Found and Fixed

**Embedded NUL bytes in git log format string** — `scan_full_history` passed `"--format=%H\x00%aI\x00%an\x00%s"` (literal NUL bytes) to `run_git`, which calls `asyncio.create_subprocess_exec`. Python's subprocess rejects embedded NUL bytes with `ValueError: embedded null byte`. The tests missed this because they all mock `run_git`.

**Fix:** Changed `\x00` to `%x00` (git's own format escape for NUL byte) at `git_dashboard.py:632`. Git interprets `%x00` and outputs literal NUL bytes, which `parse_git_log` correctly handles.

**Regression guard:** Added assertion to `test_scan_full_history_uses_run_git` that the format arg contains no literal `\x00` bytes.

**Verified fix:** `scan_full_history('.')` successfully parsed 255 commits from this repo after the fix.

## Test Results

- **Packet tests:** 15/15 pass (`tests/test_git_full_history.py`)
- **Full suite:** 125/125 pass (no regressions)

## Acceptance Criteria Verification

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `parse_git_log` correctly parses multi-commit git log output | PASS | `test_parse_multiple_commits` — 3 commits with all fields verified |
| 2 | `parse_git_log` handles merge commits with no shortstat (0/0/0) | PASS | `test_parse_merge_commit_no_shortstat` — merge commit followed immediately by format line gets zeros |
| 3 | `parse_git_log` handles all shortstat variations | PASS | `test_parse_shortstat_variations` — 5 cases: insertions only, deletions only, both, rename-only (no stats), singular "file" |
| 4 | `parse_git_log` returns empty list for empty input | PASS | `test_parse_empty_output` — `parse_git_log("")` returns `[]` |
| 5 | `aggregate_daily_stats` sums per YYYY-MM-DD | PASS | `test_aggregate_same_day` — 2 commits on 2026-03-10 summed correctly |
| 6 | `aggregate_daily_stats` groups multiple commits on same day | PASS | `test_aggregate_same_day` verifies single entry with summed values; `test_aggregate_different_days` verifies separate entries |
| 7 | `scan_full_history` invokes `run_git` with correct flags | PASS | `test_scan_full_history_uses_run_git` — verifies `--all`, `--format` (with `%H`, `%aI`, `%an`, `%s`), `--shortstat`, and no embedded NUL |
| 8 | `scan_full_history` includes `--after={since}` when since provided | PASS | `test_scan_full_history_incremental` — captured args contain `--after=2026-03-01T00:00:00+00:00` |
| 9 | `scan_full_history` omits `--after` when since is None | PASS | `test_scan_full_history_no_since` — no `--after` arg in captured args |
| 10 | `upsert_daily_stats` writes rows with correct values | PASS | `test_upsert_daily_stats_insert` — 2 dates written and verified via SQL SELECT |
| 11 | `upsert_daily_stats` replaces existing rows on conflict | PASS | `test_upsert_daily_stats_replace` — second upsert overwrites first; values verified |
| 12 | `run_full_history_scan` reads `last_full_scan_at` and passes to `scan_full_history` | PASS | Code at lines 669–674: reads from DB, assigns to `since`, passes to `scan_full_history` |
| 13 | `run_full_history_scan` updates `last_full_scan_at` to UTC ISO 8601 | PASS | `test_run_full_history_scan_updates_last_full_scan_at` — verifies non-null, parseable ISO 8601 with tzinfo |
| 14 | `run_full_history_scan` returns commit count | PASS | `test_run_full_history_scan_returns_commit_count` — 3-commit output returns 3 |
| 15 | All existing tests continue to pass | PASS | 125/125 (110 prior + 15 new) |

## Validation Focus Areas

| Area | Result | Notes |
|------|--------|-------|
| Shortstat regex edge cases | OK | `files?` handles singular/plural; optional groups handle missing insertions/deletions |
| Shortstat-to-commit association | OK | `pending` mechanism: format line sets pending, shortstat line completes it, next format line flushes pending with zeros |
| Timezone offsets in author date | OK | `date[:10]` extracts `YYYY-MM-DD` regardless of timezone suffix |
| Upsert transaction safety | OK | `executemany` + single `commit()` — all rows written atomically |
| Empty repos (no commits) | OK | `parse_git_log("")` → `[]` → `aggregate_daily_stats([])` → `{}` → `upsert_daily_stats` returns early |
| First scan (last_full_scan_at = None) | OK | `since = row[0]` is None when column is NULL → `scan_full_history(path, since=None)` does full unrestricted scan |

## Files Modified

- `git_dashboard.py` — packet 06 functions added (lines 555–686), `import re` added at line 12
- `tests/test_git_full_history.py` — new test file, 15 tests

## Scope Compliance

No scope creep. No API endpoints, no UI changes, no branch scanning, no multi-repo orchestration. Only allowed files modified.
