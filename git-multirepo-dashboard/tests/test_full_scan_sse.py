"""Packet 08 — Full Scan Orchestration & SSE: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_full_scan_sse.py -v
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import guard ───────────────────────────────────────────────────────────────
try:
    import aiosqlite  # noqa: F401
    import fastapi    # noqa: F401
except ImportError:
    pytest.skip(
        "aiosqlite/fastapi not installed — run tests inside the test venv: "
        ".venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


def _close_coro(coro, *args, **kwargs):
    """Mock side-effect for asyncio.create_task: close the coroutine to suppress warnings."""
    coro.close()
    return MagicMock()


async def _make_db_with_repos(db_path: Path, repo_count: int = 3, base_dir: Path | None = None) -> None:
    """Create schema + N repository rows in the given DB file.

    When base_dir is provided, creates real directories under it so the scan
    won't skip repos for missing paths.
    """
    git_dashboard.init_schema(db_path)
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for i in range(repo_count):
            repo_id = f"testrepo{i:012d}"
            if base_dir is not None:
                repo_dir = base_dir / f"repo-{i}"
                repo_dir.mkdir(exist_ok=True)
                repo_path = str(repo_dir)
            else:
                repo_path = f"/tmp/repo-{i}"
            await db.execute(
                "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
                (repo_id, f"repo-{i}", repo_path, "2026-01-01T00:00:00+00:00"),
            )
        await db.commit()


def _insert_scan_log(db_path: Path, status: str = "running") -> int:
    """Insert a scan_log row synchronously and return its id."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "INSERT INTO scan_log (scan_type, started_at, status) VALUES (?, ?, ?)",
        ("full", datetime.now(timezone.utc).isoformat(), status),
    )
    conn.commit()
    scan_id = cur.lastrowid
    conn.close()
    return scan_id


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_scan_state():
    """Reset module-level scan state before and after each test."""
    git_dashboard._active_scan_id = None
    git_dashboard._scan_queues.clear()
    git_dashboard._scan_task = None
    yield
    git_dashboard._active_scan_id = None
    git_dashboard._scan_queues.clear()
    git_dashboard._scan_task = None


# ─────────────────────────────────────────────────────────────────────────────
# 1. POST /api/fleet/scan creates a scan_log row
# ─────────────────────────────────────────────────────────────────────────────

def test_post_scan_creates_scan_log(test_app_raise):
    """POST /api/fleet/scan returns {scan_id: int} and creates a scan_log row."""
    client, db_path = test_app_raise

    with patch("asyncio.create_task", side_effect=_close_coro):
        response = client.post("/api/fleet/scan", json={"type": "full"})

    assert response.status_code == 200
    body = response.json()
    assert "scan_id" in body
    scan_id = body["scan_id"]
    assert isinstance(scan_id, int)

    # Verify scan_log row
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT scan_type, status, started_at FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()
    assert row is not None
    scan_type, status, started_at = row
    assert scan_type == "full"
    assert status == "running"
    assert started_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# 2. POST /api/fleet/scan rejects concurrent scans with 409
# ─────────────────────────────────────────────────────────────────────────────

def test_post_scan_rejects_concurrent(test_app_raise):
    """POST /api/fleet/scan returns 409 when a scan is already running."""
    client, db_path = test_app_raise

    # Simulate a running scan via the module-level variable
    git_dashboard._active_scan_id = 99

    response = client.post("/api/fleet/scan", json={"type": "full"})
    assert response.status_code == 409
    assert "running" in response.json()["detail"].lower()


def test_post_scan_rejects_concurrent_db_guard(test_app_raise):
    """POST /api/fleet/scan returns 409 via DB guard when _active_scan_id is None
    but a running row exists in scan_log (e.g. after server restart)."""
    client, db_path = test_app_raise

    # _active_scan_id is None (reset by fixture), but insert a running row in DB
    _insert_scan_log(db_path, status="running")

    response = client.post("/api/fleet/scan", json={"type": "full"})
    assert response.status_code == 409
    assert "running" in response.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 3. POST /api/fleet/scan rejects invalid type
# ─────────────────────────────────────────────────────────────────────────────

def test_post_scan_invalid_type(test_app_raise):
    """POST /api/fleet/scan with an invalid type returns 422 or 400."""
    client, _ = test_app_raise
    response = client.post("/api/fleet/scan", json={"type": "invalid"})
    assert response.status_code in (400, 422)


def test_post_scan_missing_type_field(test_app_raise):
    """POST /api/fleet/scan with empty body {} returns 422 (missing required field)."""
    client, _ = test_app_raise
    response = client.post("/api/fleet/scan", json={})
    assert response.status_code == 422


def test_post_scan_no_body(test_app_raise):
    """POST /api/fleet/scan with no JSON body returns 422."""
    client, _ = test_app_raise
    response = client.post("/api/fleet/scan")
    assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# 4. POST /api/fleet/scan allows a new scan after previous completed
# ─────────────────────────────────────────────────────────────────────────────

def test_post_scan_allows_after_previous_completed(test_app_raise):
    """No 409 when the previous scan has completed and _active_scan_id is None."""
    client, db_path = test_app_raise

    # Insert a completed scan in scan_log (no "running" row)
    _insert_scan_log(db_path, status="completed")

    # _active_scan_id is None (reset by fixture)
    with patch("asyncio.create_task", side_effect=_close_coro):
        response = client.post("/api/fleet/scan", json={"type": "full"})

    assert response.status_code == 200
    assert "scan_id" in response.json()


# ─────────────────────────────────────────────────────────────────────────────
# 5. run_fleet_scan calls history + branch scan for each repo
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_iterates_repos(tmp_path):
    """run_fleet_scan calls run_full_history_scan and run_branch_scan for each repo."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))

    # Insert a scan_log row so the UPDATE succeeds
    scan_id = _insert_scan_log(db_path, status="running")

    history_calls = []
    branch_calls = []

    async def mock_history(db, repo_id, repo_path):
        history_calls.append(repo_id)

    async def mock_branch(db, repo_id, repo_path):
        branch_calls.append(repo_id)

    with patch.object(git_dashboard, "run_full_history_scan", side_effect=mock_history), \
         patch.object(git_dashboard, "run_branch_scan", side_effect=mock_branch), \
         patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "full"))

    assert len(history_calls) == 3
    assert len(branch_calls) == 3
    # Same set of repo IDs for both
    assert set(history_calls) == set(branch_calls)


# ─────────────────────────────────────────────────────────────────────────────
# 6. run_fleet_scan processes repos sequentially
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_sequential_order(tmp_path):
    """run_fleet_scan processes repos one at a time (not concurrently).

    Verified by recording call order: history_N, branch_N must be interleaved,
    not batched as history_0,history_1,...,branch_0,branch_1,...
    """
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    call_log = []

    async def mock_history(db, repo_id, repo_path):
        call_log.append(("history", repo_id))

    async def mock_branch(db, repo_id, repo_path):
        call_log.append(("branch", repo_id))

    with patch.object(git_dashboard, "run_full_history_scan", side_effect=mock_history), \
         patch.object(git_dashboard, "run_branch_scan", side_effect=mock_branch), \
         patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "full"))

    # Verify pattern is always: history then branch for the same repo before moving on
    # call_log should be: (history,r0),(branch,r0),(history,r1),(branch,r1),(history,r2),(branch,r2)
    assert len(call_log) == 6
    for i in range(0, len(call_log), 2):
        kind_1, repo_1 = call_log[i]
        kind_2, repo_2 = call_log[i + 1]
        assert kind_1 == "history"
        assert kind_2 == "branch"
        assert repo_1 == repo_2, "history and branch must be called for the same repo before moving on"


# ─────────────────────────────────────────────────────────────────────────────
# 7. run_fleet_scan updates scan_log on completion
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_updates_scan_log(tmp_path):
    """After run_fleet_scan completes, scan_log has status='completed', non-null finished_at."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    async def noop(db, repo_id, repo_path):
        pass

    with patch.object(git_dashboard, "run_full_history_scan", side_effect=noop), \
         patch.object(git_dashboard, "run_branch_scan", side_effect=noop), \
         patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "full"))

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, finished_at, repos_scanned FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()

    assert row is not None
    status, finished_at, repos_scanned = row
    assert status == "completed"
    assert finished_at is not None
    assert repos_scanned == 3


# ─────────────────────────────────────────────────────────────────────────────
# 8. run_fleet_scan continues on per-repo error
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_continues_on_error(tmp_path):
    """If one repo fails, the others are still scanned."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    call_count = [0]

    async def mock_history(db, repo_id, repo_path):
        call_count[0] += 1
        if repo_id == "testrepo000000000001":  # second repo
            raise RuntimeError("simulated failure")

    async def mock_branch(db, repo_id, repo_path):
        pass

    with patch.object(git_dashboard, "run_full_history_scan", side_effect=mock_history), \
         patch.object(git_dashboard, "run_branch_scan", side_effect=mock_branch), \
         patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "full"))

    # All 3 repos were attempted (history called 3 times)
    assert call_count[0] == 3

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT repos_scanned, status FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()

    repos_scanned, status = row
    # 2 repos succeeded (first and third)
    assert repos_scanned == 2
    assert status == "completed"


# ─────────────────────────────────────────────────────────────────────────────
# 9. run_fleet_scan sets status="failed" when all repos fail
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_sets_failed_on_total_failure(tmp_path):
    """If ALL repos fail, scan_log.status is 'failed'."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    async def always_fail(db, repo_id, repo_path):
        raise RuntimeError("always fails")

    async def noop(db, repo_id, repo_path):
        pass

    with patch.object(git_dashboard, "run_full_history_scan", side_effect=always_fail), \
         patch.object(git_dashboard, "run_branch_scan", side_effect=noop), \
         patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "full"))

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, repos_scanned, finished_at FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()

    status, repos_scanned, finished_at = row
    assert status == "failed"
    assert repos_scanned == 0
    # finished_at must be populated even on failure
    assert finished_at is not None
    datetime.fromisoformat(finished_at)  # must parse as ISO 8601


def test_run_fleet_scan_empty_fleet(tmp_path):
    """With 0 repos, scan completes immediately with status='completed' and repos_scanned=0."""
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)
    scan_id = _insert_scan_log(db_path, status="running")

    with patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "full"))

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, repos_scanned, finished_at FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()

    status, repos_scanned, finished_at = row
    assert status == "completed"
    assert repos_scanned == 0
    assert finished_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# 10. SSE progress events have the expected shape
# ─────────────────────────────────────────────────────────────────────────────

def test_sse_progress_events_shape(tmp_path):
    """SSE events have the documented shape for in-progress and final events."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=2, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    async def _run():
        q = asyncio.Queue()
        git_dashboard._scan_queues[scan_id] = q

        async def noop(db, repo_id, repo_path):
            pass

        with patch.object(git_dashboard, "run_full_history_scan", side_effect=noop), \
             patch.object(git_dashboard, "run_branch_scan", side_effect=noop), \
             patch.object(git_dashboard, "DB_PATH", db_path):
            await git_dashboard.run_fleet_scan(scan_id, "full")

        events = []
        while not q.empty():
            events.append(await q.get())
        return events

    events = run(_run())

    # In-progress events (all but last)
    for ev in events[:-1]:
        assert "progress" in ev
        assert "total" in ev
        assert ev["status"] == "scanning"
    # Per-repo events (skip the initial progress=0 event) have "repo" and "step"
    per_repo_events = [e for e in events[:-1] if e.get("progress", 0) > 0]
    for ev in per_repo_events:
        assert "repo" in ev
        assert "step" in ev

    # Final event
    final = events[-1]
    assert "progress" in final
    assert "total" in final
    assert final["status"] in ("completed", "failed")
    # Final event does NOT include "repo" or "step"
    assert "repo" not in final
    assert "step" not in final


# ─────────────────────────────────────────────────────────────────────────────
# 11. SSE emits one progress event per repo plus a final event
# ─────────────────────────────────────────────────────────────────────────────

def test_sse_progress_event_per_repo(tmp_path):
    """For 3 repos, at least 3 progress events are emitted plus a final completion event."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    async def _run():
        q = asyncio.Queue()
        git_dashboard._scan_queues[scan_id] = q

        async def noop(db, repo_id, repo_path):
            pass

        with patch.object(git_dashboard, "run_full_history_scan", side_effect=noop), \
             patch.object(git_dashboard, "run_branch_scan", side_effect=noop), \
             patch.object(git_dashboard, "DB_PATH", db_path):
            await git_dashboard.run_fleet_scan(scan_id, "full")

        events = []
        while not q.empty():
            events.append(await q.get())
        return events

    events = run(_run())

    # 1 initial + 3 per-repo scanning events + 1 final event = 5 total
    assert len(events) >= 5

    scanning_events = [e for e in events if e.get("status") == "scanning"]
    final_events = [e for e in events if e.get("status") in ("completed", "failed")]

    assert len(scanning_events) == 4  # initial (progress=0) + 3 per-repo
    assert len(final_events) == 1

    # Progress values should increment: 0, 1, 2, 3
    progress_values = [e["progress"] for e in scanning_events]
    assert progress_values == sorted(progress_values)
    assert progress_values[-1] == 3


# ─────────────────────────────────────────────────────────────────────────────
# 12. type="deps" scan completes with status=completed (packet 16 implementation)
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_type_deps_completes(tmp_path):
    """type='deps' scan iterates all repos and completes with status=completed.

    Packet 08 tested a no-op placeholder (repos_scanned=0). Packet 16 implemented
    the real dep scan — repos with no manifest files are still scanned successfully
    (parse_deps_for_repo returns [] which clears stale deps and returns without error).
    So all 3 repos count as scanned.
    """
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    with patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "deps"))

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, repos_scanned, finished_at FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()

    status, repos_scanned, finished_at = row
    assert status == "completed"
    assert repos_scanned == 3  # All repos scanned (empty manifests handled gracefully)
    assert finished_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# 13. started_at and finished_at are valid ISO 8601 timestamps
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_log_started_at_is_iso8601(test_app_raise, tmp_path):
    """started_at is a valid ISO 8601 timestamp; finished_at is set after scan."""
    client, db_path = test_app_raise

    with patch("asyncio.create_task", side_effect=_close_coro):
        response = client.post("/api/fleet/scan", json={"type": "full"})

    assert response.status_code == 200
    scan_id = response.json()["scan_id"]

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT started_at FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()

    started_at = row[0]
    # Must parse as ISO 8601
    parsed = datetime.fromisoformat(started_at)
    assert parsed is not None
    assert parsed.tzinfo is not None  # must be timezone-aware


# ─────────────────────────────────────────────────────────────────────────────
# 14. GET /api/fleet returns branch_count and stale_branch_count from branches table
# ─────────────────────────────────────────────────────────────────────────────

def test_fleet_endpoint_includes_branch_counts(test_app_raise):
    """GET /api/fleet returns branch_count and stale_branch_count from branches table."""
    client, db_path = test_app_raise

    # Register a real git repo (use the test repo itself if available, or skip)
    # Instead, insert directly into DB
    import sqlite3
    import hashlib
    from datetime import datetime, timezone

    repo_path = "/tmp/test-fleet-branch-repo"
    repo_id = hashlib.sha256(repo_path.encode()).hexdigest()[:16]
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
        (repo_id, "test-repo", repo_path, now),
    )
    # Insert working_state so scan_fleet_quick won't try to scan a non-existent path
    conn.execute(
        """INSERT OR IGNORE INTO working_state
           (repo_id, has_uncommitted, modified_count, untracked_count, staged_count, checked_at)
           VALUES (?, 0, 0, 0, 0, ?)""",
        (repo_id, now),
    )
    # Insert 6 branches: 3 normal, 2 stale non-defaults, and 1 stale default
    # row to verify fleet counts ignore default branches from older scans.
    branches = [
        ("main", 1, 1),
        ("branch-0", 0, 0),
        ("branch-1", 0, 0),
        ("branch-2", 0, 0),
        ("branch-3", 0, 1),
        ("branch-4", 0, 1),
    ]
    for name, is_default, is_stale in branches:
        conn.execute(
            "INSERT INTO branches (repo_id, name, is_default, is_stale) VALUES (?, ?, ?, ?)",
            (repo_id, name, is_default, is_stale),
        )
    conn.commit()
    conn.close()

    # Patch quick_scan_repo to avoid actual git subprocess calls
    async def mock_quick_scan(path):
        return {
            "has_uncommitted": False,
            "modified_count": 0,
            "untracked_count": 0,
            "staged_count": 0,
            "current_branch": "main",
            "last_commit_hash": None,
            "last_commit_date": None,
            "last_commit_message": None,
        }

    # Also patch Path.is_dir to return True for the fake repo path
    from unittest.mock import patch as mpatch
    orig_is_dir = Path.is_dir

    def patched_is_dir(self):
        if str(self) == repo_path:
            return True
        return orig_is_dir(self)

    with mpatch.object(git_dashboard, "quick_scan_repo", side_effect=mock_quick_scan), \
         mpatch.object(Path, "is_dir", patched_is_dir):
        response = client.get("/api/fleet")

    assert response.status_code == 200
    body = response.json()
    repos = body["repos"]
    assert len(repos) == 1

    repo = repos[0]
    assert repo["branch_count"] == 6
    assert repo["stale_branch_count"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Critical: _active_scan_id is reset even when run_fleet_scan crashes
# ─────────────────────────────────────────────────────────────────────────────

def test_active_scan_id_reset_after_crash(tmp_path):
    """If run_fleet_scan raises an unexpected exception, _active_scan_id must
    still be reset to None. Otherwise all future scans are permanently blocked
    with 409."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=1, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    # Set the active scan ID as the endpoint would
    git_dashboard._active_scan_id = scan_id

    async def exploding_scan(db, repo_id, repo_path):
        raise RuntimeError("simulated crash in full history scan")

    with patch.object(git_dashboard, "run_full_history_scan", side_effect=exploding_scan), \
         patch.object(git_dashboard, "run_branch_scan", AsyncMock()), \
         patch.object(git_dashboard, "DB_PATH", db_path):
        # run_fleet_scan should NOT propagate the exception out (it catches per-repo)
        # but even if it did, _active_scan_id must be None afterward
        try:
            run(git_dashboard.run_fleet_scan(scan_id, "full"))
        except Exception:
            pass

    assert git_dashboard._active_scan_id is None, (
        "_active_scan_id was not reset after scan crash — future scans would be permanently blocked"
    )


def test_active_scan_id_reset_after_db_connect_failure(tmp_path):
    """If the DB connection itself fails inside run_fleet_scan, _active_scan_id
    must still be reset to None via the finally block."""
    git_dashboard._active_scan_id = 999

    # Point DB_PATH to a path that will fail (directory, not file)
    bad_path = tmp_path / "not_a_db_dir"
    bad_path.mkdir()

    with patch.object(git_dashboard, "DB_PATH", bad_path):
        try:
            run(git_dashboard.run_fleet_scan(999, "full"))
        except Exception:
            pass

    assert git_dashboard._active_scan_id is None, (
        "_active_scan_id was not reset after DB connection failure"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Critical: POST /api/fleet/scan with type="deps" actually runs dep scans
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_type_deps_runs_dep_scans_only(tmp_path):
    """run_fleet_scan with type='deps' calls run_dep_scan_for_repo but NOT
    run_full_history_scan or run_branch_scan."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=2, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    dep_calls = []
    history_calls = []
    branch_calls = []

    async def mock_dep(db, repo_id, repo_path):
        dep_calls.append(repo_id)

    async def mock_history(db, repo_id, repo_path):
        history_calls.append(repo_id)

    async def mock_branch(db, repo_id, repo_path):
        branch_calls.append(repo_id)

    with patch.object(git_dashboard, "run_dep_scan_for_repo", side_effect=mock_dep), \
         patch.object(git_dashboard, "run_full_history_scan", side_effect=mock_history), \
         patch.object(git_dashboard, "run_branch_scan", side_effect=mock_branch), \
         patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "deps"))

    assert len(dep_calls) == 2, f"Expected 2 dep scan calls, got {len(dep_calls)}"
    assert len(history_calls) == 0, "Deps scan should NOT call run_full_history_scan"
    assert len(branch_calls) == 0, "Deps scan should NOT call run_branch_scan"


def test_scan_type_deps_updates_scan_log(tmp_path):
    """run_fleet_scan with type='deps' marks scan_log as completed with correct count."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    async def noop_dep(db, repo_id, repo_path):
        pass

    with patch.object(git_dashboard, "run_dep_scan_for_repo", side_effect=noop_dep), \
         patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "deps"))

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, repos_scanned, finished_at FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()

    status, repos_scanned, finished_at = row
    assert status == "completed"
    assert repos_scanned == 3
    assert finished_at is not None


def test_scan_type_deps_continues_on_error(tmp_path):
    """run_fleet_scan type='deps' continues scanning remaining repos when one fails."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, status="running")

    call_count = 0

    async def failing_dep(db, repo_id, repo_path):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated dep scan failure")

    with patch.object(git_dashboard, "run_dep_scan_for_repo", side_effect=failing_dep), \
         patch.object(git_dashboard, "DB_PATH", db_path):
        run(git_dashboard.run_fleet_scan(scan_id, "deps"))

    # All 3 repos should have been attempted even though first one failed
    assert call_count == 3

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, repos_scanned FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()

    status, repos_scanned = row
    assert status == "completed"  # 2 of 3 succeeded
    assert repos_scanned == 2
