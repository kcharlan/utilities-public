"""
Packet 03 — Fleet API & Quick Scan Orchestration: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_fleet_api.py -v
"""

import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import guard ──────────────────────────────────────────────────────────────
try:
    import fastapi   # noqa: F401
    import aiosqlite # noqa: F401
except ImportError:
    pytest.skip(
        "fastapi/aiosqlite not installed — run tests inside the test venv: "
        ".venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_git_repo(path: Path) -> Path:
    """Initialize a git repo at path with one empty commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "synthetic-user@example.invalid"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "initial commit"],
        check=True, capture_output=True,
    )
    return path


def run(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# 1. scan_fleet_quick — parallel scan populates working_state for all repos
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_fleet_quick_parallel(tmp_path):
    """scan_fleet_quick scans all 3 repos and returns 3 results with working_state rows."""
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    repos = [_make_git_repo(tmp_path / f"repo_{i}") for i in range(3)]

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            for repo in repos:
                await git_dashboard.register_repo(db, {
                    "path": str(repo.resolve()),
                    "name": repo.name,
                    "default_branch": "main",
                    "runtime": "unknown",
                })
            return await git_dashboard.scan_fleet_quick(db)

    results = run(_run())
    assert len(results) == 3

    # Verify working_state rows were written
    async def _check_ws():
        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute("SELECT repo_id, checked_at FROM working_state")
            return await cursor.fetchall()

    ws_rows = run(_check_ws())
    assert len(ws_rows) == 3
    for _, checked_at in ws_rows:
        assert checked_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# 2. scan_fleet_quick — semaphore bounds concurrency to ≤ 8
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_fleet_quick_semaphore_limits_concurrency(tmp_path):
    """scan_fleet_quick never runs more than 8 quick_scan_repo calls at once."""
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    # 12 plain directories (is_dir() returns True; mock replaces quick_scan_repo)
    dirs = []
    for i in range(12):
        d = tmp_path / f"repo_{i}"
        d.mkdir()
        dirs.append(d)

    max_concurrent = 0
    current = 0

    async def mock_quick_scan(path):
        nonlocal max_concurrent, current
        current += 1
        max_concurrent = max(max_concurrent, current)
        await asyncio.sleep(0.02)  # enough to let other coroutines start
        current -= 1
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

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            for d in dirs:
                await git_dashboard.register_repo(db, {
                    "path": str(d.resolve()),
                    "name": d.name,
                    "default_branch": "main",
                    "runtime": "unknown",
                })
            with patch.object(git_dashboard, "quick_scan_repo", side_effect=mock_quick_scan):
                return await git_dashboard.scan_fleet_quick(db)

    results = run(_run())
    assert len(results) == 12
    assert max_concurrent <= 8


# ─────────────────────────────────────────────────────────────────────────────
# 3. scan_fleet_quick — includes missing-path repos with path_exists=False
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_fleet_quick_skips_missing_path(tmp_path):
    """scan_fleet_quick includes missing-path repos with path_exists=False (packet 22).

    Behavior changed in packet 22: repos with deleted paths are no longer omitted.
    They appear in results with path_exists=False and null working-state fields.
    """
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    missing_path = str((tmp_path / "nonexistent_repo").resolve())

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await git_dashboard.register_repo(db, {
                "path": missing_path,
                "name": "nonexistent",
                "default_branch": "main",
                "runtime": "unknown",
            })
            return await git_dashboard.scan_fleet_quick(db)

    results = run(_run())
    # No crash; missing-path repo is included with path_exists=False
    match = next((r for r in results if r["path"] == missing_path), None)
    assert match is not None, "Missing-path repo must appear in results"
    assert match["path_exists"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. GET /api/fleet — response shape
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_response_shape(test_app, tmp_path):
    """GET /api/fleet returns 200 with repos, kpis, scanned_at and all required per-repo fields."""
    client, _ = test_app

    _make_git_repo(tmp_path / "repo_a")
    _make_git_repo(tmp_path / "repo_b")
    client.post("/api/repos", json={"path": str(tmp_path)})

    response = client.get("/api/fleet")
    assert response.status_code == 200

    data = response.json()
    assert "repos" in data
    assert "kpis" in data
    assert "scanned_at" in data
    assert isinstance(data["repos"], list)
    assert len(data["repos"]) >= 1

    required_repo_keys = {
        "id", "name", "path", "runtime", "default_branch",
        "current_branch", "last_commit_date", "last_commit_message",
        "has_uncommitted", "modified_count", "untracked_count", "staged_count",
        "branch_count", "stale_branch_count", "dep_summary", "sparkline",
    }
    for repo in data["repos"]:
        missing = required_repo_keys - set(repo.keys())
        assert not missing, f"Repo object missing keys: {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET /api/fleet — empty state
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_empty_state(test_app):
    """GET /api/fleet with no registered repos returns empty repos list and total_repos=0."""
    client, _ = test_app

    response = client.get("/api/fleet")
    assert response.status_code == 200

    data = response.json()
    assert data["repos"] == []
    assert data["kpis"]["total_repos"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. GET /api/fleet — KPI fields and repos_with_changes
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_kpis(test_app, tmp_path):
    """GET /api/fleet returns correct KPI fields; repos_with_changes counts repos with uncommitted work."""
    client, _ = test_app

    _make_git_repo(tmp_path / "repo_a")
    _make_git_repo(tmp_path / "repo_b")
    repo_c = _make_git_repo(tmp_path / "repo_c")
    # Create an untracked file so has_uncommitted=True for repo_c
    (repo_c / "untracked.txt").write_text("hello")

    client.post("/api/repos", json={"path": str(tmp_path)})

    response = client.get("/api/fleet")
    data = response.json()

    assert data["kpis"]["total_repos"] == 3
    assert data["kpis"]["repos_with_changes"] >= 1

    # All KPI fields from spec §4.1 must be present
    required_kpi_keys = {
        "total_repos", "repos_with_changes",
        "commits_this_week", "commits_this_month",
        "net_lines_this_week", "stale_branches",
        "vulnerable_deps", "outdated_deps",
    }
    missing = required_kpi_keys - set(data["kpis"].keys())
    assert not missing, f"Missing KPI keys: {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. GET /api/fleet — updates working_state table
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_updates_working_state(test_app, tmp_path):
    """After GET /api/fleet, each scanned repo has a working_state row with checked_at set."""
    client, db_path = test_app

    _make_git_repo(tmp_path / "repo_a")
    client.post("/api/repos", json={"path": str(tmp_path)})

    client.get("/api/fleet")

    async def _check():
        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute("SELECT repo_id, checked_at FROM working_state")
            return await cursor.fetchall()

    rows = run(_check())
    assert len(rows) == 1
    assert rows[0][1] is not None  # checked_at is populated


# ─────────────────────────────────────────────────────────────────────────────
# 8. GET /api/fleet — scanned_at is valid ISO 8601 with timezone
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_scanned_at_is_iso(test_app):
    """GET /api/fleet returns a valid ISO 8601 UTC timestamp in scanned_at."""
    client, _ = test_app

    response = client.get("/api/fleet")
    data = response.json()

    scanned_at = data["scanned_at"]
    assert isinstance(scanned_at, str)

    # Must be parseable as ISO 8601 with timezone info
    dt = datetime.fromisoformat(scanned_at)
    assert dt.tzinfo is not None


# ─────────────────────────────────────────────────────────────────────────────
# 9. Non-git directory registered as repo (gap 1 from 23A hardening)
# ─────────────────────────────────────────────────────────────────────────────

def test_get_fleet_non_git_directory_does_not_crash(test_app, tmp_path):
    """Register a git repo, then delete its .git/ dir. GET /api/fleet must not crash.

    The directory still exists (path_exists=True), but git commands will fail.
    The scan should complete gracefully: the repo appears in results with null
    working-state fields rather than raising a 500 error.
    """
    client, _ = test_app

    # Create a real git repo and register it
    repo_path = _make_git_repo(tmp_path / "nongit_repo")
    client.post("/api/repos", json={"path": str(repo_path)})

    # Delete the .git directory so the path is still a dir but not a git repo
    import shutil as _shutil
    _shutil.rmtree(str(repo_path / ".git"))

    response = client.get("/api/fleet")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    assert isinstance(data["repos"], list)
    assert len(data["repos"]) >= 1

    # The repo must appear in results — scan must not skip or crash on a non-git dir
    match = next((r for r in data["repos"] if "nongit_repo" in r["path"]), None)
    assert match is not None, "Registered repo must appear in fleet results"

    # path_exists=True because the directory still exists
    assert match["path_exists"] is True

    # Git commands all failed → working-state fields are null/zero, not an exception
    assert match["current_branch"] is None
    assert match["last_commit_hash"] is None
    assert match["has_uncommitted"] is False
