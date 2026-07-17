# Packet 16: Dep Scan Orchestration

## Why This Packet Exists

Packets 13–15 built pure-function health checkers for all six ecosystems (Python, Node, Go, Rust, Ruby, PHP). These functions accept dep lists and return enriched dicts — but nothing calls them during a scan, nothing writes results to the database, and the fleet endpoint still shows `dep_summary: null` and `vulnerable_deps: 0`. This packet wires the health-check functions into the scan loop, adds DB persistence, and populates the fleet endpoint's `dep_summary` and KPI counters.

## Scope

- `run_dep_scan_for_repo(db, repo_id: str, repo_path: str) -> None` — orchestrator that:
  1. Calls `parse_deps_for_repo(repo_path)` to get the raw dep list.
  2. Routes deps through the correct ecosystem health checker(s): `check_python_deps`, `check_node_deps`, `check_go_deps`, `check_rust_deps`, `check_ruby_deps`, `check_php_deps`.
  3. Upserts enriched results into the `dependencies` table (INSERT OR REPLACE on the composite PK `(repo_id, manager, name)`).
  4. Deletes stale deps from the table that no longer appear in the manifest (dep was removed from `requirements.txt`, etc.).
- Modify `run_fleet_scan()` to handle `scan_type="deps"`:
  - Iterate all repos sequentially (same pattern as `type="full"`).
  - Call `run_dep_scan_for_repo(db, repo_id, repo_path)` for each repo.
  - Emit SSE progress events after each repo.
  - Update `scan_log` with final status.
- Modify `run_fleet_scan()` to also run dep scans during `scan_type="full"`:
  - After history + branch scans per repo, also call `run_dep_scan_for_repo`.
- Modify `GET /api/fleet` to compute real `dep_summary` per repo from the `dependencies` table:
  - `dep_summary.total` = count of rows for that repo.
  - `dep_summary.outdated` = count where severity IN ('outdated', 'major').
  - `dep_summary.vulnerable` = count where severity = 'vulnerable'.
- Modify `GET /api/fleet` KPIs to compute real `vulnerable_deps` and `outdated_deps` from the `dependencies` table.

## Non-Goals

- `GET /api/repos/{id}/deps` endpoint — packet 17
- Dependencies sub-tab UI — packet 17
- "Check Now" button per repo — packet 17
- Analytics: Dep Overlap — packet 20
- Error state UI for scan failures — packet 22
- Caching or rate-limiting for external API/registry calls
- Parallel dep scanning (sequential is intentional to avoid hammering disk and network)

## Relevant Design Doc Sections

- §4.2 Full Scan Flow (lines 1193–1213) — sequential scan loop, SSE progress, `type="deps"` flow
- §2.3 `dependencies` table schema (lines 151–162) — composite PK, columns
- §3.1 GET /api/fleet response shape (lines 427–461) — `dep_summary` object, KPI `vulnerable_deps` and `outdated_deps`
- §3.5 Fallback Behavior (lines 409–418) — fail-open, continue-on-error per repo

## Allowed Files

- `git_dashboard.py`
- `tests/test_dep_scan_orchestration.py`

## Tests to Write First

### run_dep_scan_for_repo Tests

1. **run_dep_scan_for_repo — Python repo, deps written to DB**: Set up a repo with `requirements.txt`. Mock `parse_deps_for_repo` to return 2 pip deps. Mock `check_python_deps` to return enriched dicts with severities. Call `run_dep_scan_for_repo`. Assert 2 rows in `dependencies` table with correct `repo_id`, `manager`, `name`, `severity`, `checked_at`.

2. **run_dep_scan_for_repo — Node repo, deps written to DB**: Same as above but with npm deps and `check_node_deps` mock.

3. **run_dep_scan_for_repo — mixed repo (Python + Node)**: Mock `parse_deps_for_repo` returning both pip and npm deps. Assert both `check_python_deps` and `check_node_deps` are called. Assert all deps written to DB.

4. **run_dep_scan_for_repo — stale dep removal**: First call writes deps A, B, C. Second call's `parse_deps_for_repo` returns only A, B (C was removed from manifest). Assert C is deleted from the `dependencies` table after the second call.

5. **run_dep_scan_for_repo — upsert on re-scan**: First call writes dep with `severity="ok"`. Second call returns same dep with `severity="outdated"`. Assert the row is updated, not duplicated.

6. **run_dep_scan_for_repo — no deps detected**: `parse_deps_for_repo` returns `[]`. Assert no crash, no rows written, any pre-existing deps for this repo are cleared.

7. **run_dep_scan_for_repo — health check fails gracefully**: Mock `check_python_deps` to raise an exception. Assert the function logs the error and does not crash. Deps from other ecosystems (if any) are still processed.

### run_fleet_scan with type="deps" Tests

8. **run_fleet_scan type=deps — scans all repos**: Register 2 repos. Mock `run_dep_scan_for_repo`. Trigger `run_fleet_scan(scan_id, "deps")`. Assert `run_dep_scan_for_repo` called once per repo.

9. **run_fleet_scan type=deps — SSE progress events**: Assert progress events emitted after each repo (progress increments from 1 to total).

10. **run_fleet_scan type=deps — scan_log updated**: Assert `scan_log` row has `status="completed"`, `repos_scanned` matches count, `finished_at` is set.

11. **run_fleet_scan type=deps — one repo fails, others continue**: Mock `run_dep_scan_for_repo` to raise on first repo, succeed on second. Assert `repos_scanned=1` (only successes counted), status="completed" (not all failed).

### run_fleet_scan with type="full" including deps Tests

12. **run_fleet_scan type=full — also runs dep scan**: Register 1 repo. Mock `run_full_history_scan`, `run_branch_scan`, and `run_dep_scan_for_repo`. Trigger `run_fleet_scan(scan_id, "full")`. Assert all three functions called for the repo.

### GET /api/fleet dep_summary Tests

13. **GET /api/fleet — dep_summary populated from DB**: Insert deps into `dependencies` table for a repo: 5 total, 2 with `severity="outdated"`, 1 with `severity="major"`, 1 with `severity="vulnerable"`, 1 with `severity="ok"`. Hit `GET /api/fleet`. Assert repo's `dep_summary = {"total": 5, "outdated": 3, "vulnerable": 1}`. (Note: `outdated` count includes both "outdated" and "major" severities.)

14. **GET /api/fleet — dep_summary null when no deps scanned**: Repo with no rows in `dependencies` table. Assert `dep_summary` is `null` (not `{"total": 0, ...}`).

15. **GET /api/fleet — KPI vulnerable_deps and outdated_deps**: Insert deps across multiple repos. Assert `kpis.vulnerable_deps` = total count of `severity="vulnerable"` across all repos. Assert `kpis.outdated_deps` = total count of `severity IN ("outdated", "major")` across all repos.

16. **GET /api/fleet — KPI counts zero when no deps**: No deps in DB. Assert `vulnerable_deps=0`, `outdated_deps=0`.

## Implementation Notes

### run_dep_scan_for_repo(db, repo_id: str, repo_path: str) -> None

```python
async def run_dep_scan_for_repo(db, repo_id: str, repo_path: str) -> None:
    """Detect, parse, and health-check deps for one repo, then persist to DB."""
    repo_path_obj = Path(repo_path)

    # 1. Parse raw deps from manifest files
    raw_deps = parse_deps_for_repo(repo_path_obj)
    if not raw_deps:
        # Clear any stale deps if manifest was removed
        await db.execute("DELETE FROM dependencies WHERE repo_id = ?", (repo_id,))
        await db.commit()
        return

    # 2. Route through ecosystem health checkers
    enriched = list(raw_deps)  # copy
    try:
        enriched = check_python_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Python dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_node_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Node dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_go_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Go dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_rust_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Rust dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_ruby_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Ruby dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_php_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("PHP dep check failed for %s: %s", repo_id, exc)

    # 3. Upsert into dependencies table
    for dep in enriched:
        await db.execute(
            """INSERT OR REPLACE INTO dependencies
               (repo_id, manager, name, current_version, wanted_version,
                latest_version, severity, advisory_id, checked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                repo_id,
                dep.get("manager", ""),
                dep.get("name", ""),
                dep.get("current_version"),
                dep.get("wanted_version"),
                dep.get("latest_version"),
                dep.get("severity", "ok"),
                dep.get("advisory_id"),
                dep.get("checked_at"),
            ),
        )

    # 4. Delete stale deps (in DB but no longer in manifest)
    current_keys = {(dep.get("manager", ""), dep.get("name", "")) for dep in enriched}
    cursor = await db.execute(
        "SELECT manager, name FROM dependencies WHERE repo_id = ?", (repo_id,)
    )
    db_keys = await cursor.fetchall()
    for manager, name in db_keys:
        if (manager, name) not in current_keys:
            await db.execute(
                "DELETE FROM dependencies WHERE repo_id = ? AND manager = ? AND name = ?",
                (repo_id, manager, name),
            )

    await db.commit()
```

### Modify run_fleet_scan for type="deps"

Replace the current `type="deps"` no-op block with the same sequential scan pattern used for `type="full"`:

```python
if scan_type == "deps":
    cursor = await db.execute("SELECT id, name, path FROM repositories")
    repos = await cursor.fetchall()
    total = len(repos)
    scanned = 0

    for i, (repo_id, name, repo_path) in enumerate(repos):
        try:
            await run_dep_scan_for_repo(db, repo_id, repo_path)
            scanned += 1
        except Exception as exc:
            logger.error("Dep scan failed for %s: %s", name, exc)

        await emit_scan_progress(scan_id, {
            "repo": name,
            "step": "deps",
            "progress": i + 1,
            "total": total,
            "status": "scanning",
        })
        await db.execute(
            "UPDATE scan_log SET repos_scanned = ? WHERE id = ?",
            (scanned, scan_id),
        )
        await db.commit()

    # ... same final status logic as type="full" ...
```

### Modify run_fleet_scan for type="full" to include deps

Add `await run_dep_scan_for_repo(db, repo_id, repo_path)` after `run_branch_scan` in the per-repo loop:

```python
try:
    await run_full_history_scan(db, repo_id, repo_path)
    await run_branch_scan(db, repo_id, repo_path)
    await run_dep_scan_for_repo(db, repo_id, repo_path)
    scanned += 1
except Exception as exc:
    logger.error("Scan failed for %s: %s", name, exc)
```

### Modify GET /api/fleet for dep_summary

Replace `repo.setdefault("dep_summary", None)` with a DB query:

```python
cursor = await db.execute(
    "SELECT COUNT(*), "
    "SUM(CASE WHEN severity IN ('outdated', 'major') THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN severity = 'vulnerable' THEN 1 ELSE 0 END) "
    "FROM dependencies WHERE repo_id = ?",
    (repo["id"],),
)
total_deps, outdated_count, vuln_count = await cursor.fetchone()
if total_deps and total_deps > 0:
    repo["dep_summary"] = {
        "total": total_deps,
        "outdated": (outdated_count or 0),
        "vulnerable": (vuln_count or 0),
    }
else:
    repo["dep_summary"] = None
```

### Modify GET /api/fleet KPIs

Replace the hardcoded `vulnerable_deps: 0` and `outdated_deps: 0`:

```python
cursor = await db.execute(
    "SELECT COALESCE(SUM(CASE WHEN severity = 'vulnerable' THEN 1 ELSE 0 END), 0), "
    "COALESCE(SUM(CASE WHEN severity IN ('outdated', 'major') THEN 1 ELSE 0 END), 0) "
    "FROM dependencies"
)
vuln_total, outdated_total = await cursor.fetchone()

kpis = {
    ...
    "vulnerable_deps": vuln_total,
    "outdated_deps": outdated_total,
}
```

### Stale Dep Cleanup Logic

When a dep is removed from a manifest (e.g., user deletes a line from `requirements.txt`), the next dep scan should remove it from the DB. The implementation achieves this by:
1. After upserting all current deps, query the DB for all deps for this `repo_id`.
2. Any `(manager, name)` pair in the DB that is NOT in the current enriched list gets deleted.

This ensures the `dependencies` table always reflects the current state of the manifests.

### SSE Step Naming

For `type="deps"` scans, the SSE progress events use `"step": "deps"` (not `"step": "branches"`). For `type="full"` scans, the step after deps could be `"step": "deps"` or the existing `"step": "branches"` could remain (since deps runs after branches). The simplest approach: keep the existing SSE event emission point (after the per-repo try block) and don't add a second emission for deps within full scans.

## Acceptance Criteria

1. `run_dep_scan_for_repo()` calls `parse_deps_for_repo()` to detect and parse deps.
2. `run_dep_scan_for_repo()` routes deps through the correct ecosystem health checkers.
3. `run_dep_scan_for_repo()` upserts enriched results into the `dependencies` table.
4. `run_dep_scan_for_repo()` deletes deps from the DB that are no longer in the manifest.
5. `run_dep_scan_for_repo()` handles health-check exceptions gracefully (logs, does not crash).
6. `run_dep_scan_for_repo()` handles empty dep list (clears stale deps, no crash).
7. `run_fleet_scan(scan_id, "deps")` iterates all repos and calls `run_dep_scan_for_repo` for each.
8. `run_fleet_scan(scan_id, "deps")` emits SSE progress events after each repo.
9. `run_fleet_scan(scan_id, "deps")` updates `scan_log` with correct status, `repos_scanned`, and `finished_at`.
10. `run_fleet_scan(scan_id, "deps")` continues scanning remaining repos when one fails.
11. `run_fleet_scan(scan_id, "full")` also runs `run_dep_scan_for_repo` for each repo (after history + branches).
12. `GET /api/fleet` returns `dep_summary` with correct `total`, `outdated`, `vulnerable` counts from DB.
13. `GET /api/fleet` returns `dep_summary: null` when no deps have been scanned for a repo.
14. `GET /api/fleet` KPI `vulnerable_deps` reflects total vulnerable deps across all repos.
15. `GET /api/fleet` KPI `outdated_deps` reflects total outdated+major deps across all repos.
16. All existing tests (283+ from prior packets, plus packet 15 tests) still pass (no regressions).

## Validation Focus Areas

- **DB writes**: This is the first packet that writes to the `dependencies` table. Verify INSERT OR REPLACE works correctly with the composite PK `(repo_id, manager, name)`.
- **Stale dep cleanup**: Verify that deps removed from manifests get deleted from the DB. Edge case: all deps removed (manifest deleted) should clear all rows for that repo.
- **dep_summary null vs zero**: Verify that repos with no dep scan data get `dep_summary: null`, not `{"total": 0, "outdated": 0, "vulnerable": 0}`.
- **KPI aggregation**: Verify `outdated_deps` counts both `"outdated"` and `"major"` severities.
- **Scan type routing**: Verify `type="deps"` only runs dep scans (no history/branch scans), and `type="full"` runs all three (history, branches, deps).
- **Continue-on-error**: Verify that one repo's dep scan failure doesn't block remaining repos.
- **SSE events**: Verify progress events are emitted for dep scans (both `type="deps"` and within `type="full"`).
- **Mock isolation**: Tests should mock the health-check functions (`check_python_deps`, etc.) to avoid needing subprocess mocks. The health-check functions are already tested in packets 13–15.
- **Regression**: All prior tests pass without modification.
