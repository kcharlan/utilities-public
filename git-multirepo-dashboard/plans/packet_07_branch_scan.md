# Packet 07: Branch Scan

## Why This Packet Exists

The dashboard needs branch data to populate the "Stale Br" KPI, branch counts on fleet cards, and the future Branches sub-tab. This packet adds the git branch parser, stale detection logic, and branches table upsert — pure backend logic with no UI or API endpoints.

## Scope

- **`parse_branches(output: str, default_branch: str) -> list[dict]`**: Parse output from `git branch --format='%(refname:short)%x00%(committerdate:iso-strict)'`. Each line produces a dict with `name`, `last_commit_date` (ISO 8601), `is_default` (True if name matches `default_branch`), `is_stale` (True if `last_commit_date` is more than 30 days ago from now).
- **`scan_branches(repo_path: str) -> list[dict]`**: Async function that runs the git branch command via `run_git()`, resolves the default branch from `get_default_branch()` (already exists from packet 02), and passes output to `parse_branches()`. Returns the parsed branch list.
- **`upsert_branches(db, repo_id: str, branches: list[dict]) -> None`**: Write branch data to the `branches` table. Strategy: DELETE all existing rows for the repo_id, then INSERT the new set in a single transaction. This handles branch renames and deletions cleanly.
- **`run_branch_scan(db, repo_id: str, repo_path: str) -> int`**: Orchestrates a single-repo branch scan: calls `scan_branches`, calls `upsert_branches`, returns branch count.

## Non-Goals

- Multi-repo orchestration (packet 08)
- API endpoint for branch data — GET /api/repos/{id}/branches (packet 11)
- Branch count or stale count on fleet cards (already stubbed at 0; packet 08 will populate via full scan)
- Branch visualization or UI (packet 11)
- Remote branch tracking (only local branches)

## Relevant Design Doc Sections

- §3.3 Branch Scan — git branch format string, stale detection threshold, default branch identification
- §2 SQLite Schema — `branches` table definition (repo_id, name, last_commit_date, is_default, is_stale)

## Allowed Files

- `git_dashboard.py` — add branch parsing, scanning, and upsert functions
- `tests/test_branch_scan.py` — new test file

## Tests to Write First

1. **`test_parse_single_branch`**: Parse git branch output with one branch line (e.g., `main\x002026-03-09T14:30:00-05:00`). Verify name, last_commit_date, is_default=True (when default_branch="main"), is_stale=False (recent date).

2. **`test_parse_multiple_branches`**: Parse output with 3+ branches. Verify correct count and all fields for each.

3. **`test_parse_default_branch_detection`**: Given default_branch="main" and branches ["main", "feature/auth", "develop"], verify only "main" has is_default=True.

4. **`test_parse_stale_detection`**: Branch with last_commit_date more than 30 days ago gets is_stale=True. Branch with last_commit_date within 30 days gets is_stale=False. Branch with last_commit_date exactly 30 days ago gets is_stale=False (boundary: stale means strictly older than 30 days).

5. **`test_parse_empty_output`**: Parse empty string. Returns empty list, no crash.

6. **`test_parse_branch_no_commits`**: A branch line with an empty or missing committer date (can happen for orphan branches). Should not crash; `last_commit_date` should be None, `is_stale` should be True (unknown date treated as stale).

7. **`test_parse_branch_with_slashes`**: Branch names containing slashes (e.g., `feature/auth/v2`) are parsed correctly without splitting on `/`.

8. **`test_upsert_branches_insert`**: Upsert writes new rows to branches table. Verify row count and values via SQL SELECT.

9. **`test_upsert_branches_replaces_all`**: Call upsert with branches ["main", "dev"], then call again with ["main", "feature"]. Verify "dev" is gone and "feature" exists — DELETE+INSERT strategy replaces the full set.

10. **`test_upsert_branches_empty_list`**: Upserting an empty branch list for a repo clears all existing branch rows for that repo.

11. **`test_scan_branches_calls_run_git`**: `scan_branches` calls `run_git` with the correct git branch command (verify `--format` flag with `%(refname:short)%x00%(committerdate:iso-strict)`).

12. **`test_run_branch_scan_returns_count`**: Verify `run_branch_scan` returns the number of branches parsed.

13. **`test_run_branch_scan_cascade_delete`**: Delete the repo from `repositories`, verify all related `branches` rows are also deleted (CASCADE).

## Implementation Notes

### Git Branch Command

```
git -C {path} branch --format='%(refname:short)%x00%(committerdate:iso-strict)'
```

Output format (one line per branch, null-byte separated):
```
main\x002026-03-09T14:30:00-05:00
feature/auth\x002025-12-01T10:00:00-06:00
develop\x002026-03-01T09:15:00-05:00
```

### Default Branch Resolution

Use the `default_branch` column already stored in the `repositories` table (populated by `get_default_branch()` during registration in packet 02). Pass this value into `parse_branches()` rather than running a separate git command. For `scan_branches()`, accept `default_branch` as a parameter.

Alternatively, if `scan_branches()` needs to be self-contained, call `get_default_branch(repo_path)` which already exists and uses:
```
git -C {path} symbolic-ref --short HEAD
```

Choose the simpler approach: accept `default_branch` as a parameter to keep `scan_branches()` focused.

### Stale Detection

```python
from datetime import datetime, timezone, timedelta

STALE_THRESHOLD_DAYS = 30

def _is_stale(commit_date_str: str | None) -> bool:
    if not commit_date_str:
        return True  # unknown date → treat as stale
    try:
        commit_date = datetime.fromisoformat(commit_date_str)
        cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_THRESHOLD_DAYS)
        return commit_date < cutoff
    except (ValueError, TypeError):
        return True
```

The threshold of 30 days comes from §3.3 of the design doc.

### Upsert Strategy

Use DELETE+INSERT in a transaction rather than INSERT OR REPLACE:

```python
async def upsert_branches(db, repo_id, branches):
    await db.execute("DELETE FROM branches WHERE repo_id = ?", (repo_id,))
    await db.executemany(
        "INSERT INTO branches (repo_id, name, last_commit_date, is_default, is_stale) VALUES (?, ?, ?, ?, ?)",
        [(repo_id, b['name'], b['last_commit_date'], b['is_default'], b['is_stale']) for b in branches]
    )
    await db.commit()
```

This correctly handles branch deletions and renames. INSERT OR REPLACE wouldn't remove branches that no longer exist.

### Function Placement

Add new functions after the full-history scan block (after `run_full_history_scan`) and before the HTML_TEMPLATE. Suggested order:
1. `STALE_THRESHOLD_DAYS` — module-level constant
2. `parse_branches(output, default_branch)` — pure function, no I/O
3. `scan_branches(repo_path, default_branch)` — async, calls `run_git()`
4. `upsert_branches(db, repo_id, branches)` — async, writes DB
5. `run_branch_scan(db, repo_id, repo_path)` — async, orchestrates single-repo scan

### Edge Cases

- New repo with only one branch (main): should still work.
- Repo with hundreds of branches: no special handling needed, git branch is fast.
- Branch name containing special characters or spaces: null-byte delimiter in format string avoids ambiguity.
- Empty repo (no branches, no commits): `git branch` returns empty output. `parse_branches` returns empty list. `upsert_branches` clears any stale rows.

## Acceptance Criteria

1. `parse_branches` correctly parses multi-line git branch format output with null-byte delimiters.
2. `parse_branches` identifies the default branch by matching against the `default_branch` parameter.
3. `parse_branches` marks branches with `last_commit_date` older than 30 days as `is_stale=True`.
4. `parse_branches` marks branches with missing/invalid dates as `is_stale=True`.
5. `parse_branches` returns an empty list for empty input without crashing.
6. `parse_branches` handles branch names containing slashes (e.g., `feature/auth/v2`).
7. `scan_branches` invokes `run_git` with `git branch --format='%(refname:short)%x00%(committerdate:iso-strict)'`.
8. `upsert_branches` writes correct rows to the `branches` table.
9. `upsert_branches` fully replaces existing branches for a repo (DELETE+INSERT), removing branches that no longer exist.
10. `upsert_branches` handles empty branch lists (clears all rows for the repo).
11. `run_branch_scan` returns the count of branches parsed.
12. CASCADE delete from `repositories` removes related `branches` rows.
13. All existing tests (125+) continue to pass.

## Validation Focus Areas

- Verify the null-byte delimiter in the git branch format string works correctly (use `%x00` which is the git format escape, not literal `\x00` — same lesson learned from packet 06)
- Verify stale detection handles timezone-aware ISO 8601 dates correctly (dates with offsets like `-05:00`)
- Verify the 30-day boundary: a branch exactly 30 days old is NOT stale (strictly older than 30 days)
- Verify DELETE+INSERT is wrapped in a single transaction (no partial state if crash occurs between DELETE and INSERT)
- Verify branch names with slashes don't get corrupted by the null-byte parsing
- Verify empty repos (no commits, no branches) don't crash any function in the chain
