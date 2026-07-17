# Packet 06: Git Full History Scan

## Why This Packet Exists

The dashboard needs historical commit data to power sparklines, activity charts, and KPI counters (commits this week/month, net LOC). This packet adds the git log parser and daily_stats aggregation engine — pure backend logic with no UI or API endpoints.

## Scope

- **`parse_git_log(output: str) -> list[dict]`**: Parse output from `git log --all --format='%H%x00%aI%x00%an%x00%s' --shortstat`. Each commit produces a dict with `hash`, `date` (ISO 8601), `author`, `subject`, `insertions`, `deletions`, `files_changed`. Commits without shortstat (e.g., merge commits with no file changes) get 0 for numeric fields.
- **`aggregate_daily_stats(commits: list[dict]) -> dict[str, dict]`**: Group parsed commits by YYYY-MM-DD (extracted from author date). For each date, sum `commits` (count), `insertions`, `deletions`, `files_changed`.
- **`scan_full_history(repo_path: str, since: str | None = None) -> list[dict]`**: Async function that runs the git log command via `run_git()`, passes output to `parse_git_log()`. When `since` is provided, appends `--after={since}` for incremental scanning.
- **`upsert_daily_stats(db, repo_id: str, daily_data: dict[str, dict]) -> None`**: Write aggregated daily stats to the `daily_stats` table using INSERT OR REPLACE (upsert on `(repo_id, date)` primary key).
- **`run_full_history_scan(db, repo_id: str, repo_path: str) -> int`**: Orchestrates a single-repo full history scan: reads `last_full_scan_at` from DB, calls `scan_full_history`, aggregates, upserts, updates `last_full_scan_at` on the `repositories` row. Returns count of commits parsed.

## Non-Goals

- Multi-repo orchestration or sequential scan loop (packet 08)
- SSE progress streaming (packet 08)
- API endpoints for history data (packet 10)
- Sparkline computation from daily_stats (packet 09)
- Branch scanning (packet 07)
- Author-level breakdown or per-author stats storage (the `author` field is parsed but not stored — daily_stats only aggregates by repo+date)

## Relevant Design Doc Sections

- §3.2 Full History Scan — git log format, shortstat parsing, incremental --after
- §2 SQLite Schema — `daily_stats` table definition, `repositories.last_full_scan_at` column
- §5.7 Scan Workflow — incremental history scanning flow (single-repo portion only)

## Allowed Files

- `git_dashboard.py` — add parsing, aggregation, and upsert functions
- `tests/test_git_full_history.py` — new test file

## Tests to Write First

1. **`test_parse_single_commit`**: Parse git log output with one commit (format line + blank line + shortstat line). Verify all fields extracted correctly: hash, date, author, subject, insertions, deletions, files_changed.

2. **`test_parse_multiple_commits`**: Parse output with 3+ commits. Verify correct count and all fields for each.

3. **`test_parse_merge_commit_no_shortstat`**: Parse a commit where the format line is followed directly by another format line (no shortstat). Verify insertions=0, deletions=0, files_changed=0 for the merge commit.

4. **`test_parse_empty_output`**: Parse empty string. Returns empty list, no crash.

5. **`test_parse_shortstat_variations`**: Handle all shortstat format variations:
   - "1 file changed, 2 insertions(+)" (no deletions)
   - "1 file changed, 3 deletions(-)" (no insertions)
   - "5 files changed, 10 insertions(+), 3 deletions(-)" (both)
   - "1 file changed" (possible for rename-only, 0 insertions/deletions)

6. **`test_aggregate_same_day`**: Two commits on the same date get summed into one daily_stats entry.

7. **`test_aggregate_different_days`**: Commits on different dates produce separate entries.

8. **`test_aggregate_empty_commits`**: Empty commit list produces empty dict.

9. **`test_upsert_daily_stats_insert`**: Upsert writes new rows to daily_stats table. Verify row count and values via SQL SELECT.

10. **`test_upsert_daily_stats_replace`**: Upsert overwrites existing rows on `(repo_id, date)` conflict. Verify the newer values replace old ones.

11. **`test_scan_full_history_uses_run_git`**: `scan_full_history` calls `run_git` with the correct git log command (verify `--all`, `--format`, `--shortstat` flags).

12. **`test_scan_full_history_incremental`**: When `since` is provided, the git command includes `--after={since}`.

13. **`test_scan_full_history_no_since`**: When `since` is None, the git command does NOT include `--after`.

14. **`test_run_full_history_scan_updates_last_full_scan_at`**: After `run_full_history_scan` completes, `repositories.last_full_scan_at` is non-null and is a valid ISO 8601 timestamp.

15. **`test_run_full_history_scan_returns_commit_count`**: Verify the function returns the count of commits parsed.

## Implementation Notes

### Git Log Command

```
git -C {path} log --all --format='%H%x00%aI%x00%an%x00%s' --shortstat [--after={since}]
```

Format fields (null-byte separated):
- `%H` — commit hash (40-char hex)
- `%aI` — author date, strict ISO 8601 (e.g., `2026-03-10T14:30:00-05:00`)
- `%an` — author name
- `%s` — subject (first line of commit message)

### Output Structure

```
<hash>\0<date>\0<author>\0<subject>
                                        ← blank line (may be absent)
 3 files changed, 45 insertions(+), 12 deletions(-)
<hash>\0<date>\0<author>\0<subject>
                                        ← blank line
 1 file changed, 2 insertions(+)
```

Key parsing rules:
- A line containing `\x00` is always a format line (new commit)
- A line matching `/^\s*\d+ files? changed/` is a shortstat line belonging to the preceding commit
- Blank lines between format and shortstat lines should be skipped
- A format line immediately following another format line means the previous commit had no file changes

### Shortstat Regex

```python
import re
_SHORTSTAT_RE = re.compile(
    r'(\d+) files? changed'
    r'(?:, (\d+) insertions?\(\+\))?'
    r'(?:, (\d+) deletions?\(-\))?'
)
```

Extract groups: files_changed (group 1, always present), insertions (group 2, may be None → 0), deletions (group 3, may be None → 0).

### Daily Aggregation

Extract date from ISO 8601 author date: `date_str[:10]` gives `YYYY-MM-DD`.

```python
def aggregate_daily_stats(commits):
    daily = {}
    for c in commits:
        day = c['date'][:10]  # YYYY-MM-DD from ISO 8601
        if day not in daily:
            daily[day] = {'commits': 0, 'insertions': 0, 'deletions': 0, 'files_changed': 0}
        daily[day]['commits'] += 1
        daily[day]['insertions'] += c['insertions']
        daily[day]['deletions'] += c['deletions']
        daily[day]['files_changed'] += c['files_changed']
    return daily
```

### Upsert Strategy

Use `INSERT OR REPLACE` on `daily_stats` table. Since the primary key is `(repo_id, date)`, this replaces existing rows for the same repo+date combination. This is correct for both fresh scans and incremental scans — incremental scans that overlap a date boundary will overwrite that day's totals with the re-counted values.

Note: For incremental scans, the `--after` date might fall in the middle of a day. In that edge case, the daily total for that boundary day may be incomplete (only counting commits after the timestamp, not all commits on that day). This is an acceptable approximation — the next full scan will correct it.

### Updating last_full_scan_at

After all daily_stats are upserted for a repo:

```python
await db.execute(
    "UPDATE repositories SET last_full_scan_at = ? WHERE id = ?",
    (datetime.now(timezone.utc).isoformat(), repo_id)
)
await db.commit()
```

### Function Placement

Add new functions after the existing quick-scan block (after `scan_fleet_quick`) and before the HTML_TEMPLATE. Suggested order:
1. `_SHORTSTAT_RE` — module-level compiled regex
2. `parse_git_log(output)` — pure function, no I/O
3. `aggregate_daily_stats(commits)` — pure function
4. `scan_full_history(repo_path, since=None)` — async, calls `run_git()`
5. `upsert_daily_stats(db, repo_id, daily_data)` — async, writes DB
6. `run_full_history_scan(db, repo_id, repo_path)` — async, orchestrates single-repo scan

### Performance Notes

- `--shortstat` is fast (git doesn't diff individual lines, just counts)
- For large repos (10k+ commits), first scan may take a few seconds; incremental scans are near-instant
- No concurrency concern in this packet — single-repo scanning only

## Acceptance Criteria

1. `parse_git_log` correctly parses multi-commit git log output with format+shortstat lines.
2. `parse_git_log` handles merge commits with no shortstat (0 insertions/deletions/files_changed).
3. `parse_git_log` handles all shortstat variations (insertions only, deletions only, both, neither).
4. `parse_git_log` returns an empty list for empty input.
5. `aggregate_daily_stats` sums commits, insertions, deletions, files_changed per YYYY-MM-DD.
6. `aggregate_daily_stats` correctly groups multiple commits on the same day.
7. `scan_full_history` invokes `run_git` with `git log --all --format='%H%x00%aI%x00%an%x00%s' --shortstat`.
8. `scan_full_history` includes `--after={since}` when the `since` parameter is provided.
9. `scan_full_history` omits `--after` when `since` is None.
10. `upsert_daily_stats` writes rows to the `daily_stats` table with correct values.
11. `upsert_daily_stats` replaces existing rows on `(repo_id, date)` conflict.
12. `run_full_history_scan` reads `last_full_scan_at` from the repo's DB row and passes it to `scan_full_history`.
13. `run_full_history_scan` updates `last_full_scan_at` to a valid UTC ISO 8601 timestamp after successful scan.
14. `run_full_history_scan` returns the count of commits parsed.
15. All existing tests (96+) continue to pass.

## Validation Focus Areas

- Verify the shortstat regex handles all edge cases (singular/plural "file"/"files", missing insertions or deletions groups)
- Verify parse_git_log correctly associates shortstat lines with the preceding commit (not the following one)
- Verify that commits with timezone offsets in the author date are handled correctly (the date[:10] extraction should work regardless of timezone)
- Verify upsert_daily_stats doesn't leave partial writes on error (should be in a single transaction)
- Verify empty repos (no commits) don't crash any function in the chain
- Verify `run_full_history_scan` with `last_full_scan_at = None` (first scan) does a full unrestricted scan
