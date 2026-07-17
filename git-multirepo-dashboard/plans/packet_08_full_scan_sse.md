# Packet 08: Full Scan Orchestration & SSE

## Why This Packet Exists

Packets 06 and 07 built single-repo scan functions for history and branches. This packet wires them into a multi-repo sequential scan loop triggered by POST /api/fleet/scan, with real-time progress via Server-Sent Events. After this packet, the "Scan" button in the UI header can trigger a full fleet scan and the frontend can track progress.

## Scope

- **`POST /api/fleet/scan`** endpoint: Accepts `{"type": "full"}` or `{"type": "deps"}`. Creates a `scan_log` entry with status `running`, returns `{"scan_id": <id>}`. Launches the scan as a background task via `asyncio.create_task()`. Rejects with HTTP 409 if a scan is already running.
- **`run_fleet_scan(scan_id: int, scan_type: str)`**: Background async function that iterates repos sequentially. For `type="full"`: runs `run_full_history_scan` then `run_branch_scan` for each repo. Sends SSE progress events after each repo completes. Updates `scan_log` (repos_scanned, status, finished_at) as it progresses. On error for a single repo, logs the error and continues to the next repo (continue-with-errors for batch).
- **`GET /api/fleet/scan/{scan_id}/progress`** SSE endpoint: Returns a `text/event-stream` response. Streams progress events from an `asyncio.Queue`. Sends a final `status: "completed"` or `status: "failed"` event, then closes.
- **SSE event bridge**: A module-level dict mapping `scan_id -> asyncio.Queue` for passing progress events from the scan task to the SSE endpoint. Queue is created when the scan starts and removed when the SSE stream closes or the scan completes.
- **`scan_log` table usage**: INSERT on scan start, UPDATE `repos_scanned` after each repo, UPDATE `status` and `finished_at` on completion/failure.

## Non-Goals

- `type="deps"` actual implementation — the endpoint accepts it and creates the scan_log entry, but the dep scan functions don't exist yet (packets 12–16). For now, a `type="deps"` scan completes immediately with repos_scanned=0.
- Sparkline computation or UI progress bar (packet 09)
- Concurrent multi-repo scanning (sequential is intentional per spec — avoids hammering disk)
- Scan cancellation
- Scan history UI or listing past scans
- Populating branch_count/stale_branch_count on fleet cards (the scan writes to the branches table; the fleet endpoint already queries from there — but the fleet endpoint currently returns hardcoded 0s; updating the fleet endpoint query is acceptable if trivial, otherwise defer)

## Relevant Design Doc Sections

- §3.4 Full Scan Flow — sequential repo loop, scan steps, SSE event shape
- §4.2 POST /api/fleet/scan — request/response shape, 409 on concurrent scan
- §4.3 GET /api/fleet/scan/{scan_id}/progress — SSE event format, step values
- §2 SQLite Schema — `scan_log` table definition
- §5.7 Scan Workflow — full scan flow (button click → POST → SSE → refresh)

## Allowed Files

- `git_dashboard.py` — add scan orchestration, SSE endpoint, and fleet scan function
- `tests/test_full_scan_sse.py` — new test file

## Tests to Write First

1. **`test_post_scan_creates_scan_log`**: POST /api/fleet/scan with `{"type": "full"}` returns 200 with `{"scan_id": <int>}`. Verify a row exists in `scan_log` with matching id, `scan_type="full"`, `status="running"`, non-null `started_at`.

2. **`test_post_scan_rejects_concurrent`**: Start a scan (set status to "running" in scan_log). POST /api/fleet/scan again. Verify HTTP 409 response with an error message.

3. **`test_post_scan_invalid_type`**: POST /api/fleet/scan with `{"type": "invalid"}` returns HTTP 422 or 400.

4. **`test_post_scan_allows_after_previous_completed`**: Complete a scan (status="completed"). POST /api/fleet/scan again. Verify 200 — no 409 because no scan is currently running.

5. **`test_run_fleet_scan_iterates_repos`**: Register 3 repos (mock git operations). Run `run_fleet_scan`. Verify `run_full_history_scan` and `run_branch_scan` were called for each repo.

6. **`test_run_fleet_scan_sequential_order`**: Verify repos are scanned one at a time (not concurrently). This can be tested by checking that scan calls are interleaved with progress events, not batched.

7. **`test_run_fleet_scan_updates_scan_log`**: After `run_fleet_scan` completes, verify `scan_log` row has `status="completed"`, non-null `finished_at`, and `repos_scanned` equals the number of repos.

8. **`test_run_fleet_scan_continues_on_error`**: Register 3 repos. Make the second repo's scan fail (mock `run_git` to raise for that repo). Verify the first and third repos were still scanned. Verify `repos_scanned` reflects only successful scans.

9. **`test_run_fleet_scan_sets_failed_on_total_failure`**: If ALL repos fail, verify `scan_log.status` is `"failed"`.

10. **`test_sse_progress_events_shape`**: Verify SSE events have the expected shape: `{"repo": "<name>", "step": "<step>", "progress": <int>, "total": <int>, "status": "scanning"}` for in-progress events, and `{"progress": <int>, "total": <int>, "status": "completed"}` for the final event.

11. **`test_sse_progress_event_per_repo`**: For a scan with 3 repos, verify at least 3 progress events are emitted (one per repo completion), plus a final completion event.

12. **`test_scan_type_deps_completes_immediately`**: POST /api/fleet/scan with `{"type": "deps"}` creates a scan_log entry. Since no dep scan functions exist yet, the scan completes immediately with repos_scanned=0 and status="completed".

13. **`test_scan_log_started_at_is_iso8601`**: Verify `started_at` and `finished_at` are valid ISO 8601 timestamps.

14. **`test_fleet_endpoint_includes_branch_counts`**: After running a full scan (which calls `run_branch_scan`), GET /api/fleet returns repos with `branch_count` and `stale_branch_count` populated from the `branches` table (not hardcoded 0).

## Implementation Notes

### Concurrent Scan Guard

Use a module-level variable to track whether a scan is running:

```python
_active_scan_id: int | None = None
```

The POST endpoint checks this before creating a new scan. Alternatively, query `scan_log` for any row with `status='running'`. The module-level variable is simpler and avoids a DB round-trip, but must be cleared on scan completion (including on error).

Use both for belt-and-suspenders: check the module-level var first (fast path), and also query the DB (correct after server restart).

### SSE Event Bridge

```python
_scan_queues: dict[int, asyncio.Queue] = {}

async def emit_scan_progress(scan_id: int, event: dict):
    q = _scan_queues.get(scan_id)
    if q:
        await q.put(event)
```

The SSE endpoint creates the queue on connect:
```python
@app.get("/api/fleet/scan/{scan_id}/progress")
async def scan_progress_sse(scan_id: int):
    q = asyncio.Queue()
    _scan_queues[scan_id] = q
    async def event_generator():
        try:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("completed", "failed"):
                    break
        finally:
            _scan_queues.pop(scan_id, None)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### Full Scan Loop

```python
async def run_fleet_scan(scan_id: int, scan_type: str):
    global _active_scan_id
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            repos = await db.execute_fetchall("SELECT id, name, path FROM repositories")
            total = len(repos)
            scanned = 0
            for i, (repo_id, name, path) in enumerate(repos):
                try:
                    if scan_type == "full":
                        await run_full_history_scan(db, repo_id, path)
                        await run_branch_scan(db, repo_id, path)
                    # type="deps" is a no-op for now
                    scanned += 1
                except Exception as e:
                    logger.error(f"Scan failed for {name}: {e}")
                await emit_scan_progress(scan_id, {
                    "repo": name,
                    "step": "branches",  # last step completed
                    "progress": i + 1,
                    "total": total,
                    "status": "scanning"
                })
                await db.execute(
                    "UPDATE scan_log SET repos_scanned = ? WHERE id = ?",
                    (scanned, scan_id)
                )
                await db.commit()
            # Final status
            status = "completed" if scanned > 0 else "failed"
            await db.execute(
                "UPDATE scan_log SET status = ?, finished_at = ? WHERE id = ?",
                (status, datetime.now(timezone.utc).isoformat(), scan_id)
            )
            await db.commit()
            await emit_scan_progress(scan_id, {
                "progress": total,
                "total": total,
                "status": status
            })
    finally:
        _active_scan_id = None
```

### SSE Response Type

Use `StreamingResponse` from `starlette.responses` (already available via FastAPI):

```python
from starlette.responses import StreamingResponse
```

### Updating Fleet Endpoint for Branch Counts

The current GET /api/fleet returns hardcoded `branch_count: 0` and `stale_branch_count: 0`. After this packet, update the fleet endpoint query to join with the `branches` table:

```sql
SELECT COUNT(*) FROM branches WHERE repo_id = ?
SELECT COUNT(*) FROM branches WHERE repo_id = ? AND is_stale = TRUE
```

Or use subqueries in the main fleet query. Keep this minimal — just replace the hardcoded 0s.

### Background Task

Use `asyncio.create_task()` to launch `run_fleet_scan` as a fire-and-forget background task. Store a reference to prevent garbage collection:

```python
_scan_task: asyncio.Task | None = None
```

### Function Placement

Add new functions after the branch scan block (after `run_branch_scan`) and before the HTML_TEMPLATE:
1. `_active_scan_id` — module-level variable
2. `_scan_queues` — module-level dict
3. `_scan_task` — module-level task reference
4. `emit_scan_progress()` — async helper
5. `run_fleet_scan()` — async background task

Add new endpoints after the existing DELETE /api/repos/{repo_id} endpoint:
1. `POST /api/fleet/scan`
2. `GET /api/fleet/scan/{scan_id}/progress`

### Database Connection Handling

The background task (`run_fleet_scan`) must open its own database connection since it runs independently of any request lifecycle. Use `aiosqlite.connect(DB_PATH)` directly rather than the FastAPI `get_db` dependency.

## Acceptance Criteria

1. POST /api/fleet/scan with `{"type": "full"}` returns `{"scan_id": <int>}` with HTTP 200.
2. POST /api/fleet/scan creates a `scan_log` row with `scan_type`, `started_at` (ISO 8601), and `status="running"`.
3. POST /api/fleet/scan returns HTTP 409 when a scan is already running.
4. POST /api/fleet/scan with an invalid type returns HTTP 422 or 400.
5. POST /api/fleet/scan succeeds after a previous scan has completed.
6. `run_fleet_scan` with `type="full"` calls `run_full_history_scan` and `run_branch_scan` for each registered repo.
7. `run_fleet_scan` processes repos sequentially (not concurrently).
8. `run_fleet_scan` continues scanning remaining repos when one repo fails.
9. `run_fleet_scan` updates `scan_log.repos_scanned` after each repo.
10. `run_fleet_scan` sets `scan_log.status` to `"completed"` and populates `finished_at` on success.
11. `run_fleet_scan` sets `scan_log.status` to `"failed"` if zero repos scanned successfully.
12. GET /api/fleet/scan/{scan_id}/progress returns `text/event-stream` content type.
13. SSE events match the documented shape: `{"repo", "step", "progress", "total", "status"}` for in-progress, `{"progress", "total", "status"}` for final.
14. `type="deps"` scan creates a scan_log entry and completes immediately with repos_scanned=0.
15. GET /api/fleet returns `branch_count` and `stale_branch_count` populated from the `branches` table (not hardcoded 0).
16. All existing tests (125+) continue to pass.

## Validation Focus Areas

- Verify the 409 guard works correctly: both the module-level variable and the DB check should agree
- Verify the `_active_scan_id` is always cleared, even if the scan crashes unexpectedly (try/finally)
- Verify SSE events are valid `text/event-stream` format (each event is `data: {...}\n\n`)
- Verify the background task doesn't hold a stale DB connection (it should open its own)
- Verify `run_fleet_scan` doesn't crash if `_scan_queues` has no listener (SSE endpoint not connected yet)
- Verify the scan loop handles an empty repos list gracefully (0 repos → immediate completion)
- Verify `finished_at` is populated for both completed and failed scans
- Verify no race condition between the POST endpoint creating the scan_log row and the background task reading repos (the task should query repos after being launched, not before)
