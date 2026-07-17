# Packet 03: Fleet API & Quick Scan Orchestration

## Why This Packet Exists

The fleet overview is the primary entry point for the application. This packet delivers the backend API that quick-scans all registered repos in parallel (with bounded concurrency) and returns the fleet-level view data that all downstream UI packets depend on.

## Scope

- `GET /api/fleet` endpoint that returns the full fleet response shape
- `scan_fleet_quick(db)` coroutine: fetches all registered repos, quick-scans them in parallel via `asyncio.Semaphore(8)`, upserts `working_state` for each
- Fleet response builder that joins `repositories` + `working_state` into the per-repo objects
- KPI aggregation (only fields derivable from current data: `total_repos`, `repos_with_changes`)
- Placeholder/default values for fields that depend on later packets: `sparkline` (empty list), `dep_summary` (null), `branch_count` (0), `stale_branch_count` (0), `commits_this_week` (0), `commits_this_month` (0), `net_lines_this_week` (0), `stale_branches` (0), `vulnerable_deps` (0), `outdated_deps` (0)
- Graceful handling of repos whose paths no longer exist on disk (skip scan, mark in response)

## Non-Goals

- `POST /api/fleet/scan` — that is packet 08 (Full Scan Orchestration & SSE)
- SSE progress streaming — packet 08
- Full history scan / `daily_stats` population — packet 06
- Branch scan / `branches` table population — packet 07
- Any UI rendering of fleet data — packet 05
- Dependency scanning — packets 12–16
- Error states UI (card badges for scan-failed) — packet 22

## Relevant Design Doc Sections

- **§4.1** GET /api/fleet — response shape, field definitions, sparkline description
- **§6.1** Quick Scan Flow — concurrency model (`asyncio.Semaphore(8)`), working_state update, "returns fleet data with sparklines from cached daily_stats"

## Allowed Files

- `git_dashboard.py`
- `tests/test_fleet_api.py` (new)

## Tests to Write First

All tests go in `tests/test_fleet_api.py`. Use the same test patterns as `test_repo_discovery.py` (TestClient with isolated DB, `_make_git_repo` helper).

### 1. `test_scan_fleet_quick_parallel`
- Register 3 repos (via `register_repo`)
- Call `scan_fleet_quick(db)`
- Assert all 3 repos have `working_state` rows with `checked_at` set
- Verify returned list length == 3

### 2. `test_scan_fleet_quick_semaphore_limits_concurrency`
- Patch `quick_scan_repo` with an async mock that records concurrency (increment counter on entry, decrement on exit, track max)
- Register 12 repos
- Call `scan_fleet_quick(db)`
- Assert max observed concurrency ≤ 8

### 3. `test_scan_fleet_quick_skips_missing_path`
- Register a repo whose path does not exist on disk
- Call `scan_fleet_quick(db)`
- Assert no crash; the missing repo should appear in results with `scan_error` or be omitted gracefully

### 4. `test_get_fleet_response_shape`
- Register 2 repos via POST /api/repos
- GET /api/fleet
- Assert 200 status
- Assert response has keys: `repos`, `kpis`, `scanned_at`
- Assert `repos` is a list of length ≥ 1
- Assert each repo object has required keys: `id`, `name`, `path`, `runtime`, `default_branch`, `current_branch`, `last_commit_date`, `last_commit_message`, `has_uncommitted`, `modified_count`, `untracked_count`, `staged_count`, `branch_count`, `stale_branch_count`, `dep_summary`, `sparkline`

### 5. `test_get_fleet_empty_state`
- GET /api/fleet with no registered repos
- Assert 200 status
- Assert `repos` is empty list
- Assert `kpis.total_repos` == 0

### 6. `test_get_fleet_kpis`
- Register 3 repos; ensure at least 1 has uncommitted changes (create a modified file)
- GET /api/fleet
- Assert `kpis.total_repos` == 3
- Assert `kpis.repos_with_changes` ≥ 1

### 7. `test_get_fleet_updates_working_state`
- Register a repo
- GET /api/fleet
- Query `working_state` table directly
- Assert the repo has a `working_state` row with `checked_at` populated

### 8. `test_get_fleet_scanned_at_is_iso`
- GET /api/fleet
- Assert `scanned_at` is a valid ISO 8601 timestamp string

## Implementation Notes

### `scan_fleet_quick(db) -> list[dict]`

```python
async def scan_fleet_quick(db) -> list[dict]:
    """Quick-scan all registered repos in parallel, upsert working_state, return results."""
    repos = await db.execute_fetchall("SELECT id, name, path, runtime, default_branch FROM repositories")
    if not repos:
        return []

    sem = asyncio.Semaphore(8)

    async def scan_one(repo_row):
        repo_id, name, path, runtime, default_branch = repo_row
        async with sem:
            if not Path(path).is_dir():
                return None  # skip missing repos
            data = await quick_scan_repo(path)
            await upsert_working_state(db, repo_id, data)
            return {
                "id": repo_id,
                "name": name,
                "path": path,
                "runtime": runtime,
                "default_branch": default_branch,
                **data,
            }

    results = await asyncio.gather(*(scan_one(r) for r in repos))
    return [r for r in results if r is not None]
```

### Fleet response builder

The `GET /api/fleet` handler calls `scan_fleet_quick(db)`, then augments each result with placeholder fields and builds KPIs:

```python
# Per-repo augmentation (fields from later packets get defaults)
for repo in results:
    repo.setdefault("branch_count", 0)
    repo.setdefault("stale_branch_count", 0)
    repo.setdefault("dep_summary", None)
    repo.setdefault("sparkline", [])

# KPIs
kpis = {
    "total_repos": len(results),
    "repos_with_changes": sum(1 for r in results if r.get("has_uncommitted")),
    "commits_this_week": 0,     # populated by packet 06
    "commits_this_month": 0,    # populated by packet 06
    "net_lines_this_week": 0,   # populated by packet 06
    "stale_branches": 0,        # populated by packet 07
    "vulnerable_deps": 0,       # populated by packet 16
    "outdated_deps": 0,         # populated by packet 16
}
```

### Concurrency concern

This is the first packet introducing `asyncio.Semaphore`. The semaphore bounds concurrent git subprocesses to avoid overwhelming the OS. The semaphore object should be created per-call (not module-level) to avoid sharing across requests.

### `scanned_at`

ISO 8601 timestamp of when the scan completed (UTC). Use `datetime.now(timezone.utc).isoformat()`.

### Database connection sharing

The `db` connection from `get_db()` is shared across the `asyncio.gather` calls. Since aiosqlite serializes writes internally, this is safe. The `upsert_working_state` function already commits after each write — this is fine for quick scan since writes are small and fast.

## Acceptance Criteria

1. `GET /api/fleet` returns 200 with JSON body containing `repos`, `kpis`, and `scanned_at` keys.
2. Each repo object in `repos` contains all fields from spec §4.1: `id`, `name`, `path`, `runtime`, `default_branch`, `current_branch`, `last_commit_date`, `last_commit_message`, `has_uncommitted`, `modified_count`, `untracked_count`, `staged_count`, `branch_count`, `stale_branch_count`, `dep_summary`, `sparkline`.
3. `kpis` contains all fields from spec §4.1: `total_repos`, `repos_with_changes`, `commits_this_week`, `commits_this_month`, `net_lines_this_week`, `stale_branches`, `vulnerable_deps`, `outdated_deps`.
4. Quick scan runs in parallel with concurrency bounded to 8 (`asyncio.Semaphore(8)`).
5. After `GET /api/fleet`, each scanned repo has an updated `working_state` row in the database.
6. Repos whose disk paths no longer exist are handled gracefully (no crash, omitted from response or flagged).
7. Empty fleet (no registered repos) returns `repos: []` and `kpis.total_repos: 0`.
8. `scanned_at` is a valid ISO 8601 UTC timestamp.
9. All new tests pass. All existing tests (78) continue to pass with no regressions.
10. `python git_dashboard.py --help` does not crash.

## Validation Focus Areas

- **Concurrency**: Verify the semaphore actually bounds parallelism (the mock-based test).
- **Response shape completeness**: Every field from §4.1 must be present, even if defaulted. The UI in packet 05 will destructure these fields directly.
- **Database integrity**: Confirm `working_state` rows are created/updated correctly and `checked_at` reflects the scan time.
- **Missing-path resilience**: Test with a repo whose directory was deleted after registration.
- **No scope creep**: No SSE, no POST /api/fleet/scan, no full scan, no branch scan.
