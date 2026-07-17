"""Packet 16 — Dep Scan Orchestration: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_dep_scan_orchestration.py -v
"""

import asyncio
import sqlite3
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


def _make_dep(name: str, manager: str = "pip", severity: str = "ok",
              current: str = "1.0.0", latest: str = "1.0.0",
              advisory_id: str = None) -> dict:
    return {
        "manager": manager,
        "name": name,
        "current_version": current,
        "wanted_version": current,
        "latest_version": latest,
        "severity": severity,
        "advisory_id": advisory_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def _make_db_with_repo(db_path: Path, repo_id: str = "testrepo00000000",
                              repo_path: str = "/tmp/repo-0",
                              name: str = "repo-0") -> None:
    """Create schema + 1 repository row in the given DB file."""
    git_dashboard.init_schema(db_path)
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
            (repo_id, name, repo_path, "2026-01-01T00:00:00+00:00"),
        )
        await db.commit()


async def _make_db_with_repos(db_path: Path, repo_count: int = 2, base_dir: Path | None = None) -> list:
    """Create schema + N repos. Returns list of (id, name, path) tuples.

    When base_dir is provided, creates real directories so the scan
    won't skip repos for missing paths.
    """
    git_dashboard.init_schema(db_path)
    repos = []
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for i in range(repo_count):
            repo_id = f"testrepo{i:012d}"
            name = f"repo-{i}"
            if base_dir is not None:
                repo_dir = base_dir / f"repo-{i}"
                repo_dir.mkdir(exist_ok=True)
                path = str(repo_dir)
            else:
                path = f"/tmp/repo-{i}"
            await db.execute(
                "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
                (repo_id, name, path, "2026-01-01T00:00:00+00:00"),
            )
            repos.append((repo_id, name, path))
        await db.commit()
    return repos


def _insert_scan_log(db_path: Path, scan_type: str = "deps",
                     status: str = "running") -> int:
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "INSERT INTO scan_log (scan_type, started_at, status) VALUES (?, ?, ?)",
        (scan_type, datetime.now(timezone.utc).isoformat(), status),
    )
    conn.commit()
    scan_id = cur.lastrowid
    conn.close()
    return scan_id


def _get_deps_for_repo(db_path: Path, repo_id: str) -> list:
    """Fetch all dep rows for a repo as list of dicts."""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT manager, name, current_version, latest_version, severity, advisory_id, checked_at "
        "FROM dependencies WHERE repo_id = ? ORDER BY manager, name",
        (repo_id,),
    ).fetchall()
    conn.close()
    return [
        {"manager": r[0], "name": r[1], "current_version": r[2],
         "latest_version": r[3], "severity": r[4], "advisory_id": r[5],
         "checked_at": r[6]}
        for r in rows
    ]


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
# 1. run_dep_scan_for_repo — Python repo, deps written to DB
# ─────────────────────────────────────────────────────────────────────────────

def test_run_dep_scan_python_deps_written(tmp_path):
    """run_dep_scan_for_repo with Python deps writes 2 rows to dependencies table."""
    db_path = tmp_path / "test.db"
    repo_id = "testrepo00000000"
    run(_make_db_with_repo(db_path, repo_id))

    raw_deps = [_make_dep("requests", "pip"), _make_dep("flask", "pip")]
    enriched = [
        _make_dep("requests", "pip", severity="outdated", latest="2.0.0"),
        _make_dep("flask", "pip", severity="ok"),
    ]

    with patch.object(git_dashboard, "parse_deps_for_repo", return_value=raw_deps), \
         patch.object(git_dashboard, "check_python_deps", return_value=enriched), \
         patch.object(git_dashboard, "check_node_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_go_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_rust_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_ruby_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_php_deps", side_effect=lambda p, d: d):

        async def _run():
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, "/tmp/repo")

        run(_run())

    rows = _get_deps_for_repo(db_path, repo_id)
    assert len(rows) == 2
    names = {r["name"] for r in rows}
    assert names == {"requests", "flask"}
    managers = {r["manager"] for r in rows}
    assert managers == {"pip"}
    requests_row = next(r for r in rows if r["name"] == "requests")
    assert requests_row["severity"] == "outdated"
    assert requests_row["checked_at"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# 2. run_dep_scan_for_repo — Node repo, deps written to DB
# ─────────────────────────────────────────────────────────────────────────────

def test_run_dep_scan_node_deps_written(tmp_path):
    """run_dep_scan_for_repo with npm deps writes rows with correct manager."""
    db_path = tmp_path / "test.db"
    repo_id = "testrepo00000001"
    run(_make_db_with_repo(db_path, repo_id))

    raw_deps = [_make_dep("express", "npm"), _make_dep("lodash", "npm")]
    enriched = [
        _make_dep("express", "npm", severity="ok"),
        _make_dep("lodash", "npm", severity="major", latest="5.0.0"),
    ]

    with patch.object(git_dashboard, "parse_deps_for_repo", return_value=raw_deps), \
         patch.object(git_dashboard, "check_python_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_node_deps", return_value=enriched), \
         patch.object(git_dashboard, "check_go_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_rust_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_ruby_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_php_deps", side_effect=lambda p, d: d):

        async def _run():
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, "/tmp/repo")

        run(_run())

    rows = _get_deps_for_repo(db_path, repo_id)
    assert len(rows) == 2
    assert all(r["manager"] == "npm" for r in rows)
    lodash_row = next(r for r in rows if r["name"] == "lodash")
    assert lodash_row["severity"] == "major"


# ─────────────────────────────────────────────────────────────────────────────
# 3. run_dep_scan_for_repo — mixed repo (Python + Node)
# ─────────────────────────────────────────────────────────────────────────────

def test_run_dep_scan_mixed_repo(tmp_path):
    """run_dep_scan_for_repo calls both check_python_deps and check_node_deps for mixed repos."""
    db_path = tmp_path / "test.db"
    repo_id = "testrepo00000002"
    run(_make_db_with_repo(db_path, repo_id))

    raw_deps = [_make_dep("requests", "pip"), _make_dep("express", "npm")]

    python_checker_called = []
    node_checker_called = []

    def mock_python(repo_path, deps):
        python_checker_called.append(True)
        return deps

    def mock_node(repo_path, deps):
        node_checker_called.append(True)
        return deps

    with patch.object(git_dashboard, "parse_deps_for_repo", return_value=raw_deps), \
         patch.object(git_dashboard, "check_python_deps", side_effect=mock_python), \
         patch.object(git_dashboard, "check_node_deps", side_effect=mock_node), \
         patch.object(git_dashboard, "check_go_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_rust_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_ruby_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_php_deps", side_effect=lambda p, d: d):

        async def _run():
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, "/tmp/repo")

        run(_run())

    assert python_checker_called, "check_python_deps was not called"
    assert node_checker_called, "check_node_deps was not called"

    rows = _get_deps_for_repo(db_path, repo_id)
    assert len(rows) == 2
    managers = {r["manager"] for r in rows}
    assert "pip" in managers
    assert "npm" in managers


# ─────────────────────────────────────────────────────────────────────────────
# 4. run_dep_scan_for_repo — stale dep removal
# ─────────────────────────────────────────────────────────────────────────────

def test_run_dep_scan_stale_dep_removed(tmp_path):
    """Deps no longer in the manifest are deleted on re-scan."""
    db_path = tmp_path / "test.db"
    repo_id = "testrepo00000003"
    run(_make_db_with_repo(db_path, repo_id))

    # First scan: A, B, C
    first_deps = [
        _make_dep("A", "pip"), _make_dep("B", "pip"), _make_dep("C", "pip")
    ]

    def _noop(repo_path, deps):
        return deps

    with patch.object(git_dashboard, "parse_deps_for_repo", return_value=first_deps), \
         patch.object(git_dashboard, "check_python_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_node_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_go_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_rust_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_ruby_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_php_deps", side_effect=_noop):

        async def _run1():
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, "/tmp/repo")

        run(_run1())

    rows_after_first = _get_deps_for_repo(db_path, repo_id)
    assert len(rows_after_first) == 3

    # Second scan: only A, B (C removed from manifest)
    second_deps = [_make_dep("A", "pip"), _make_dep("B", "pip")]

    with patch.object(git_dashboard, "parse_deps_for_repo", return_value=second_deps), \
         patch.object(git_dashboard, "check_python_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_node_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_go_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_rust_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_ruby_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_php_deps", side_effect=_noop):

        async def _run2():
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, "/tmp/repo")

        run(_run2())

    rows_after_second = _get_deps_for_repo(db_path, repo_id)
    assert len(rows_after_second) == 2
    names = {r["name"] for r in rows_after_second}
    assert "C" not in names
    assert names == {"A", "B"}


# ─────────────────────────────────────────────────────────────────────────────
# 5. run_dep_scan_for_repo — upsert on re-scan
# ─────────────────────────────────────────────────────────────────────────────

def test_run_dep_scan_upsert_updates_existing(tmp_path):
    """Re-scanning a repo updates existing dep rows rather than duplicating them."""
    db_path = tmp_path / "test.db"
    repo_id = "testrepo00000004"
    run(_make_db_with_repo(db_path, repo_id))

    first_deps = [_make_dep("requests", "pip", severity="ok")]
    second_deps = [_make_dep("requests", "pip", severity="outdated", latest="2.0.0")]

    def _noop(repo_path, deps):
        return deps

    with patch.object(git_dashboard, "parse_deps_for_repo", return_value=first_deps), \
         patch.object(git_dashboard, "check_python_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_node_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_go_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_rust_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_ruby_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_php_deps", side_effect=_noop):

        async def _run1():
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, "/tmp/repo")

        run(_run1())

    with patch.object(git_dashboard, "parse_deps_for_repo", return_value=second_deps), \
         patch.object(git_dashboard, "check_python_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_node_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_go_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_rust_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_ruby_deps", side_effect=_noop), \
         patch.object(git_dashboard, "check_php_deps", side_effect=_noop):

        async def _run2():
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, "/tmp/repo")

        run(_run2())

    rows = _get_deps_for_repo(db_path, repo_id)
    assert len(rows) == 1, "upsert should not duplicate rows"
    assert rows[0]["severity"] == "outdated"


# ─────────────────────────────────────────────────────────────────────────────
# 6. run_dep_scan_for_repo — no deps detected
# ─────────────────────────────────────────────────────────────────────────────

def test_run_dep_scan_no_deps_clears_stale(tmp_path):
    """Empty dep list clears all pre-existing deps for the repo and doesn't crash."""
    db_path = tmp_path / "test.db"
    repo_id = "testrepo00000005"
    run(_make_db_with_repo(db_path, repo_id))

    # Pre-populate some deps
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO dependencies (repo_id, manager, name, severity, checked_at) VALUES (?, ?, ?, ?, ?)",
        (repo_id, "pip", "old-dep", "ok", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    rows_before = _get_deps_for_repo(db_path, repo_id)
    assert len(rows_before) == 1

    # Scan with no deps returned
    with patch.object(git_dashboard, "parse_deps_for_repo", return_value=[]):

        async def _run():
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, "/tmp/repo")

        run(_run())

    rows_after = _get_deps_for_repo(db_path, repo_id)
    assert rows_after == [], "all stale deps should be cleared when manifest is empty"


# ─────────────────────────────────────────────────────────────────────────────
# 7. run_dep_scan_for_repo — health check fails gracefully
# ─────────────────────────────────────────────────────────────────────────────

def test_run_dep_scan_health_check_exception_does_not_crash(tmp_path):
    """A failing health-check does not crash run_dep_scan_for_repo."""
    db_path = tmp_path / "test.db"
    repo_id = "testrepo00000006"
    run(_make_db_with_repo(db_path, repo_id))

    raw_deps = [
        _make_dep("requests", "pip"),
        _make_dep("express", "npm"),
    ]

    def crash_python(repo_path, deps):
        raise RuntimeError("pip API unavailable")

    def ok_node(repo_path, deps):
        # Return node deps as-is (severity stays "ok")
        return deps

    with patch.object(git_dashboard, "parse_deps_for_repo", return_value=raw_deps), \
         patch.object(git_dashboard, "check_python_deps", side_effect=crash_python), \
         patch.object(git_dashboard, "check_node_deps", side_effect=ok_node), \
         patch.object(git_dashboard, "check_go_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_rust_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_ruby_deps", side_effect=lambda p, d: d), \
         patch.object(git_dashboard, "check_php_deps", side_effect=lambda p, d: d):

        async def _run():
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                # Must not raise
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, "/tmp/repo")

        run(_run())  # No exception should propagate

    # Deps still written (python checker crashed but deps were already in enriched list
    # from parse_deps_for_repo — the failed checker just doesn't enrich them further)
    rows = _get_deps_for_repo(db_path, repo_id)
    assert len(rows) == 2  # Both deps still written (unenriched from python)


# ─────────────────────────────────────────────────────────────────────────────
# 8. run_fleet_scan type=deps — scans all repos
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_deps_calls_dep_scan_for_each_repo(tmp_path):
    """run_fleet_scan with type=deps calls run_dep_scan_for_repo once per repo."""
    db_path = tmp_path / "test.db"
    repos = run(_make_db_with_repos(db_path, repo_count=2, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, scan_type="deps")

    called_repo_ids = []

    async def mock_dep_scan(db, repo_id, repo_path):
        called_repo_ids.append(repo_id)

    with patch.object(git_dashboard, "DB_PATH", db_path), \
         patch.object(git_dashboard, "run_dep_scan_for_repo", side_effect=mock_dep_scan), \
         patch.object(git_dashboard, "emit_scan_progress", new=AsyncMock()):
        run(git_dashboard.run_fleet_scan(scan_id, "deps"))

    assert len(called_repo_ids) == 2
    expected_ids = {r[0] for r in repos}
    assert set(called_repo_ids) == expected_ids


# ─────────────────────────────────────────────────────────────────────────────
# 9. run_fleet_scan type=deps — SSE progress events emitted
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_deps_emits_sse_progress(tmp_path):
    """run_fleet_scan type=deps emits a progress event after each repo."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=3, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, scan_type="deps")

    emitted = []

    async def capture_progress(sid, event):
        emitted.append(event)

    with patch.object(git_dashboard, "DB_PATH", db_path), \
         patch.object(git_dashboard, "run_dep_scan_for_repo", new=AsyncMock()), \
         patch.object(git_dashboard, "emit_scan_progress", side_effect=capture_progress):
        run(git_dashboard.run_fleet_scan(scan_id, "deps"))

    # Should have 1 initial + 3 per-repo events + one final event
    progress_events = [e for e in emitted if e.get("status") == "scanning"]
    final_events = [e for e in emitted if e.get("status") == "completed"]
    assert len(progress_events) == 4  # initial (progress=0) + 3 per-repo
    assert len(final_events) == 1
    # Progress should increment: 0, 1, 2, 3
    progress_values = [e["progress"] for e in progress_events]
    assert progress_values == [0, 1, 2, 3]


# ─────────────────────────────────────────────────────────────────────────────
# 10. run_fleet_scan type=deps — scan_log updated
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_deps_updates_scan_log(tmp_path):
    """run_fleet_scan type=deps sets scan_log status=completed with correct counts."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=2, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, scan_type="deps")

    with patch.object(git_dashboard, "DB_PATH", db_path), \
         patch.object(git_dashboard, "run_dep_scan_for_repo", new=AsyncMock()), \
         patch.object(git_dashboard, "emit_scan_progress", new=AsyncMock()):
        run(git_dashboard.run_fleet_scan(scan_id, "deps"))

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, repos_scanned, finished_at FROM scan_log WHERE id = ?",
        (scan_id,),
    ).fetchone()
    conn.close()

    status, repos_scanned, finished_at = row
    assert status == "completed"
    assert repos_scanned == 2
    assert finished_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# 11. run_fleet_scan type=deps — one repo fails, others continue
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_deps_continues_after_repo_failure(tmp_path):
    """run_fleet_scan type=deps continues scanning when one repo's dep scan fails."""
    db_path = tmp_path / "test.db"
    repos = run(_make_db_with_repos(db_path, repo_count=2, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, scan_type="deps")

    call_count = [0]

    async def mock_dep_scan_first_fails(db, repo_id, repo_path):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("First repo dep scan failed")

    with patch.object(git_dashboard, "DB_PATH", db_path), \
         patch.object(git_dashboard, "run_dep_scan_for_repo",
                      side_effect=mock_dep_scan_first_fails), \
         patch.object(git_dashboard, "emit_scan_progress", new=AsyncMock()):
        run(git_dashboard.run_fleet_scan(scan_id, "deps"))

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, repos_scanned FROM scan_log WHERE id = ?", (scan_id,)
    ).fetchone()
    conn.close()

    status, repos_scanned = row
    assert status == "completed"
    assert repos_scanned == 1  # Only 1 succeeded
    assert call_count[0] == 2  # Both repos were attempted


# ─────────────────────────────────────────────────────────────────────────────
# 12. run_fleet_scan type=full — also runs dep scan
# ─────────────────────────────────────────────────────────────────────────────

def test_run_fleet_scan_full_also_runs_dep_scan(tmp_path):
    """run_fleet_scan type=full calls run_dep_scan_for_repo after history+branch scans."""
    db_path = tmp_path / "test.db"
    run(_make_db_with_repos(db_path, repo_count=1, base_dir=tmp_path))
    scan_id = _insert_scan_log(db_path, scan_type="full")

    history_called = []
    branch_called = []
    dep_called = []

    async def mock_history(db, repo_id, repo_path):
        history_called.append(repo_id)

    async def mock_branch(db, repo_id, repo_path):
        branch_called.append(repo_id)

    async def mock_dep(db, repo_id, repo_path):
        dep_called.append(repo_id)

    with patch.object(git_dashboard, "DB_PATH", db_path), \
         patch.object(git_dashboard, "run_full_history_scan", side_effect=mock_history), \
         patch.object(git_dashboard, "run_branch_scan", side_effect=mock_branch), \
         patch.object(git_dashboard, "run_dep_scan_for_repo", side_effect=mock_dep), \
         patch.object(git_dashboard, "emit_scan_progress", new=AsyncMock()):
        run(git_dashboard.run_fleet_scan(scan_id, "full"))

    assert len(history_called) == 1
    assert len(branch_called) == 1
    assert len(dep_called) == 1
    assert history_called[0] == branch_called[0] == dep_called[0]


# ─────────────────────────────────────────────────────────────────────────────
# 13. GET /api/fleet — dep_summary populated from DB
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_dep_summary_from_db(test_app_raise, tmp_path):
    """GET /api/fleet returns correct dep_summary counts from dependencies table."""
    client, db_path = test_app_raise

    # Register a repo
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    repo_id = "deptest0000000001"
    conn.execute(
        "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
        (repo_id, "dep-repo", "/tmp/dep-repo", "2026-01-01T00:00:00+00:00"),
    )
    # Insert 5 deps: 2 outdated, 1 major, 1 vulnerable, 1 ok
    for name, severity in [
        ("A", "outdated"), ("B", "outdated"), ("C", "major"),
        ("D", "vulnerable"), ("E", "ok"),
    ]:
        conn.execute(
            "INSERT INTO dependencies (repo_id, manager, name, severity, checked_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (repo_id, "pip", name, severity, "2026-01-01T00:00:00+00:00"),
        )
    conn.commit()
    conn.close()

    with patch.object(git_dashboard, "scan_fleet_quick", new=AsyncMock(return_value=[{
        "id": repo_id, "name": "dep-repo", "path": "/tmp/dep-repo",
        "current_branch": "main", "has_uncommitted": False,
        "modified_count": 0, "untracked_count": 0, "staged_count": 0,
        "last_commit_hash": None, "last_commit_message": None,
        "last_commit_date": None, "runtime": "python", "default_branch": "main",
    }])):
        response = client.get("/api/fleet")

    assert response.status_code == 200
    body = response.json()
    repos = body["repos"]
    assert len(repos) == 1
    ds = repos[0]["dep_summary"]
    assert ds is not None
    assert ds["total"] == 5
    assert ds["outdated"] == 3  # 2 "outdated" + 1 "major"
    assert ds["vulnerable"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 14. GET /api/fleet — dep_summary null when no deps scanned
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_dep_summary_null_when_no_deps(test_app_raise):
    """GET /api/fleet returns dep_summary: null when no deps have been scanned."""
    client, db_path = test_app_raise

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    repo_id = "nodeps000000000001"
    conn.execute(
        "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
        (repo_id, "no-deps-repo", "/tmp/no-deps", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    with patch.object(git_dashboard, "scan_fleet_quick", new=AsyncMock(return_value=[{
        "id": repo_id, "name": "no-deps-repo", "path": "/tmp/no-deps",
        "current_branch": "main", "has_uncommitted": False,
        "modified_count": 0, "untracked_count": 0, "staged_count": 0,
        "last_commit_hash": None, "last_commit_message": None,
        "last_commit_date": None, "runtime": "unknown", "default_branch": "main",
    }])):
        response = client.get("/api/fleet")

    assert response.status_code == 200
    repos = response.json()["repos"]
    assert len(repos) == 1
    assert repos[0]["dep_summary"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 15. GET /api/fleet — KPI vulnerable_deps and outdated_deps
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_kpis_dep_counts(test_app_raise):
    """GET /api/fleet KPI counters reflect total vulnerable and outdated deps across all repos."""
    client, db_path = test_app_raise

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    for i, (rname, rpath) in enumerate([("repo-A", "/tmp/A"), ("repo-B", "/tmp/B")]):
        rid = f"kpitest{i:012d}"
        conn.execute(
            "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
            (rid, rname, rpath, "2026-01-01T00:00:00+00:00"),
        )
        # repo-A: 2 vulnerable, 1 major; repo-B: 1 vulnerable, 3 outdated
        if i == 0:
            for n, sev in [("v1", "vulnerable"), ("v2", "vulnerable"), ("m1", "major")]:
                conn.execute(
                    "INSERT INTO dependencies (repo_id, manager, name, severity, checked_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (rid, "pip", n, sev, "2026-01-01T00:00:00+00:00"),
                )
        else:
            for n, sev in [("v3", "vulnerable"), ("o1", "outdated"), ("o2", "outdated"), ("o3", "outdated")]:
                conn.execute(
                    "INSERT INTO dependencies (repo_id, manager, name, severity, checked_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (rid, "npm", n, sev, "2026-01-01T00:00:00+00:00"),
                )

    conn.commit()
    conn.close()

    rids = [f"kpitest{i:012d}" for i in range(2)]
    mock_results = [
        {"id": rids[0], "name": "repo-A", "path": "/tmp/A",
         "current_branch": "main", "has_uncommitted": False,
         "modified_count": 0, "untracked_count": 0, "staged_count": 0,
         "last_commit_hash": None, "last_commit_message": None,
         "last_commit_date": None, "runtime": "python", "default_branch": "main"},
        {"id": rids[1], "name": "repo-B", "path": "/tmp/B",
         "current_branch": "main", "has_uncommitted": False,
         "modified_count": 0, "untracked_count": 0, "staged_count": 0,
         "last_commit_hash": None, "last_commit_message": None,
         "last_commit_date": None, "runtime": "python", "default_branch": "main"},
    ]

    with patch.object(git_dashboard, "scan_fleet_quick", new=AsyncMock(return_value=mock_results)):
        response = client.get("/api/fleet")

    assert response.status_code == 200
    kpis = response.json()["kpis"]
    # 3 total vulnerable (v1, v2, v3)
    assert kpis["vulnerable_deps"] == 3
    # 4 total outdated+major (m1, o1, o2, o3)
    assert kpis["outdated_deps"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# 16. GET /api/fleet — KPI counts zero when no deps
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_kpis_zero_when_no_deps(test_app_raise):
    """GET /api/fleet returns vulnerable_deps=0, outdated_deps=0 when no deps in DB."""
    client, db_path = test_app_raise

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
        ("nodeps000000000002", "empty-repo", "/tmp/empty", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    with patch.object(git_dashboard, "scan_fleet_quick", new=AsyncMock(return_value=[{
        "id": "nodeps000000000002", "name": "empty-repo", "path": "/tmp/empty",
        "current_branch": "main", "has_uncommitted": False,
        "modified_count": 0, "untracked_count": 0, "staged_count": 0,
        "last_commit_hash": None, "last_commit_message": None,
        "last_commit_date": None, "runtime": "unknown", "default_branch": "main",
    }])):
        response = client.get("/api/fleet")

    assert response.status_code == 200
    kpis = response.json()["kpis"]
    assert kpis["vulnerable_deps"] == 0
    assert kpis["outdated_deps"] == 0
