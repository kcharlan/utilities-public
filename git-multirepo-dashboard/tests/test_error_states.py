"""
Packet 22: Error States & Edge Cases

Tests for:
- path-not-found card state (scan_fleet_quick, fleet endpoint, repo detail)
- scan-error badge (run_fleet_scan sets/clears scan_error)
- offline dep indicator (run_dep_scan_for_repo sets/clears dep_check_error)
- PATCH /api/repos/{id}
- concurrent-scan 409 regression guard
- schema migration idempotency
- HTML template strings for UI components
"""
import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import aiosqlite
    import fastapi  # noqa: F401
except ImportError:
    pytest.skip(
        "fastapi/aiosqlite not installed — run tests inside the test venv: "
        ".venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402


# ── Helpers ─────────────────────────────────────────────────────────────────

def _insert_repo(db_path: Path, name: str, path: str) -> str:
    """Insert a repo row directly into the DB and return its id."""
    repo_id = git_dashboard.generate_repo_id(path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO repositories "
        "(id, name, path, runtime, default_branch, added_at) "
        "VALUES (?,?,?,?,?,?)",
        (repo_id, name, path, "python", "main", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()
    return repo_id


def _set_ws(db_path: Path, repo_id: str, **kwargs) -> None:
    """Insert or update working_state columns directly."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO working_state (repo_id) VALUES (?)", (repo_id,)
    )
    if kwargs:
        fields = ", ".join(f"{k} = ?" for k in kwargs)
        conn.execute(
            f"UPDATE working_state SET {fields} WHERE repo_id = ?",
            list(kwargs.values()) + [repo_id],
        )
    conn.commit()
    conn.close()


def _read_ws(db_path: Path, repo_id: str, col: str):
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        f"SELECT {col} FROM working_state WHERE repo_id = ?", (repo_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], capture_output=True)
    return path


# ── scan_fleet_quick tests ───────────────────────────────────────────────────

def test_scan_fleet_quick_includes_missing_path(test_app, tmp_path):
    """Repo with deleted path must appear in scan_fleet_quick with path_exists=False."""
    client, db_path = test_app
    repo_dir = tmp_path / "vanished"
    repo_dir.mkdir()
    repo_id = _insert_repo(db_path, "vanished", str(repo_dir))
    repo_dir.rmdir()  # delete after registration

    async def _check():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            return await git_dashboard.scan_fleet_quick(db)

    results = asyncio.run(_check())
    matches = [x for x in results if x["id"] == repo_id]
    assert len(matches) == 1, "Missing-path repo must appear in results"
    assert matches[0]["path_exists"] is False


def test_scan_fleet_quick_valid_path_has_path_exists_true(test_app, tmp_path):
    """Repo with a valid path must have path_exists=True in scan_fleet_quick."""
    client, db_path = test_app
    repo_dir = _make_git_repo(tmp_path / "valid_repo")
    repo_id = _insert_repo(db_path, "valid_repo", str(repo_dir))

    async def _check():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            return await git_dashboard.scan_fleet_quick(db)

    results = asyncio.run(_check())
    matches = [x for x in results if x["id"] == repo_id]
    assert len(matches) == 1
    assert matches[0]["path_exists"] is True


# ── Fleet endpoint tests ─────────────────────────────────────────────────────

def test_fleet_endpoint_includes_path_exists(test_app, tmp_path):
    """GET /api/fleet — deleted-path repo appears with path_exists=false."""
    client, db_path = test_app
    repo_dir = tmp_path / "del_fleet"
    repo_dir.mkdir()
    repo_id = _insert_repo(db_path, "del_fleet", str(repo_dir))
    repo_dir.rmdir()

    r = client.get("/api/fleet")
    assert r.status_code == 200
    match = next((x for x in r.json()["repos"] if x["id"] == repo_id), None)
    assert match is not None, "Deleted-path repo must appear in fleet"
    assert match["path_exists"] is False


def test_fleet_response_includes_scan_error(test_app, tmp_path):
    """GET /api/fleet — every repo has scan_error and dep_check_error keys (AC17)."""
    client, db_path = test_app
    repo_dir = tmp_path / "err_fleet"
    repo_dir.mkdir()
    _insert_repo(db_path, "err_fleet", str(repo_dir))

    r = client.get("/api/fleet")
    assert r.status_code == 200
    repos = r.json()["repos"]
    assert len(repos) >= 1
    for repo in repos:
        assert "scan_error" in repo, "scan_error key must be present in each fleet repo"
        assert "dep_check_error" in repo, "dep_check_error key must be present in each fleet repo"


# ── Repo detail tests ────────────────────────────────────────────────────────

def test_repo_detail_includes_path_exists_false(test_app, tmp_path):
    """GET /api/repos/{id} returns path_exists=false when path is deleted."""
    client, db_path = test_app
    repo_dir = tmp_path / "del_detail"
    repo_dir.mkdir()
    repo_id = _insert_repo(db_path, "del_detail", str(repo_dir))
    repo_dir.rmdir()

    r = client.get(f"/api/repos/{repo_id}")
    assert r.status_code == 200
    assert r.json()["path_exists"] is False


def test_repo_detail_valid_path_has_path_exists_true(test_app, tmp_path):
    """GET /api/repos/{id} returns path_exists=true for a valid path."""
    client, db_path = test_app
    repo_dir = tmp_path / "ok_detail"
    repo_dir.mkdir()
    repo_id = _insert_repo(db_path, "ok_detail", str(repo_dir))

    r = client.get(f"/api/repos/{repo_id}")
    assert r.status_code == 200
    assert r.json()["path_exists"] is True


# ── scan_error tests ─────────────────────────────────────────────────────────

def test_scan_error_set_on_failure(test_app, tmp_path):
    """run_fleet_scan sets scan_error in working_state when a scan function raises."""
    client, db_path = test_app
    repo_dir = tmp_path / "scan_fail_repo"
    repo_dir.mkdir()
    repo_id = _insert_repo(db_path, "scan_fail_repo", str(repo_dir))

    async def raise_scan_error(db, repo_id, repo_path):
        raise RuntimeError("simulated scan failure")

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute(
                "INSERT INTO scan_log (scan_type, started_at, status) VALUES (?,?,'running')",
                ("full", "2026-01-01T00:00:00"),
            )
            await db.commit()
            scan_id = cursor.lastrowid

        old = git_dashboard.DB_PATH
        git_dashboard.DB_PATH = db_path
        try:
            with patch.object(
                git_dashboard, "run_full_history_scan", side_effect=raise_scan_error
            ):
                await git_dashboard.run_fleet_scan(scan_id, "full")
        finally:
            git_dashboard.DB_PATH = old

    asyncio.run(_run())
    val = _read_ws(db_path, repo_id, "scan_error")
    assert val is not None, "scan_error must be set after scan failure"


def test_scan_error_cleared_on_success(test_app, tmp_path):
    """run_fleet_scan clears scan_error to NULL after a successful scan."""
    client, db_path = test_app
    repo_dir = _make_git_repo(tmp_path / "ok_scan")
    repo_id = _insert_repo(db_path, "ok_scan", str(repo_dir))
    _set_ws(db_path, repo_id, scan_error="old error")

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute(
                "INSERT INTO scan_log (scan_type, started_at, status) VALUES (?,?,'running')",
                ("full", "2026-01-01T00:00:00"),
            )
            await db.commit()
            scan_id = cursor.lastrowid

        old = git_dashboard.DB_PATH
        git_dashboard.DB_PATH = db_path
        try:
            await git_dashboard.run_fleet_scan(scan_id, "full")
        finally:
            git_dashboard.DB_PATH = old

    asyncio.run(_run())
    val = _read_ws(db_path, repo_id, "scan_error")
    assert val is None, "scan_error must be NULL after successful scan"


# ── PATCH /api/repos/{id} tests ──────────────────────────────────────────────

def test_patch_repo_path_success(test_app, tmp_path):
    """PATCH /api/repos/{id} with valid new path returns 200 and updates DB."""
    client, db_path = test_app
    orig_dir = tmp_path / "orig_path"
    orig_dir.mkdir()
    repo_id = _insert_repo(db_path, "patch_test", str(orig_dir))

    new_dir = tmp_path / "new_path"
    new_dir.mkdir()
    r = client.patch(f"/api/repos/{repo_id}", json={"path": str(new_dir)})
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == repo_id
    assert str(new_dir.resolve()) in data["path"]

    r2 = client.get(f"/api/repos/{repo_id}")
    assert r2.status_code == 200
    assert str(new_dir.resolve()) in r2.json()["path"]


def test_patch_repo_path_not_found(test_app, tmp_path):
    """PATCH /api/repos/{nonexistent} returns 404."""
    client, db_path = test_app
    some_dir = tmp_path / "nodir"
    some_dir.mkdir()
    r = client.patch("/api/repos/nonexistentid", json={"path": str(some_dir)})
    assert r.status_code == 404


def test_patch_repo_path_invalid(test_app, tmp_path):
    """PATCH /api/repos/{id} with a nonexistent directory returns 400."""
    client, db_path = test_app
    orig_dir = tmp_path / "orig_invalid"
    orig_dir.mkdir()
    repo_id = _insert_repo(db_path, "patch_invalid", str(orig_dir))

    r = client.patch(f"/api/repos/{repo_id}", json={"path": "/nonexistent/xyz/path"})
    assert r.status_code == 400


def test_patch_repo_path_traversal_resolves(test_app, tmp_path):
    """PATCH /api/repos/{id} with '../' in path resolves to the real absolute path,
    preventing the stored path from containing traversal sequences."""
    client, db_path = test_app
    orig_dir = tmp_path / "orig"
    orig_dir.mkdir()
    repo_id = _insert_repo(db_path, "traversal_test", str(orig_dir))

    # Create a valid directory reachable via traversal
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    traversal_path = str(tmp_path / "orig" / ".." / "target")

    r = client.patch(f"/api/repos/{repo_id}", json={"path": traversal_path})
    assert r.status_code == 200

    # The stored path must be the resolved absolute path, not the traversal string
    stored_path = r.json()["path"]
    assert ".." not in stored_path
    assert stored_path == str(target_dir.resolve())


def test_patch_repo_path_empty_body(test_app, tmp_path):
    """PATCH /api/repos/{id} with empty path string returns 400."""
    client, db_path = test_app
    orig_dir = tmp_path / "orig"
    orig_dir.mkdir()
    repo_id = _insert_repo(db_path, "empty_path", str(orig_dir))

    r = client.patch(f"/api/repos/{repo_id}", json={"path": ""})
    assert r.status_code == 400


def test_patch_repo_path_missing_field(test_app, tmp_path):
    """PATCH /api/repos/{id} with body missing 'path' key returns 400."""
    client, db_path = test_app
    orig_dir = tmp_path / "orig"
    orig_dir.mkdir()
    repo_id = _insert_repo(db_path, "missing_field", str(orig_dir))

    r = client.patch(f"/api/repos/{repo_id}", json={"wrong_key": str(orig_dir)})
    assert r.status_code == 400


def test_patch_repo_path_file_not_dir(test_app, tmp_path):
    """PATCH /api/repos/{id} with a path that is a file (not directory) returns 400."""
    client, db_path = test_app
    orig_dir = tmp_path / "orig"
    orig_dir.mkdir()
    repo_id = _insert_repo(db_path, "file_path", str(orig_dir))

    a_file = tmp_path / "just_a_file.txt"
    a_file.write_text("not a directory")

    r = client.patch(f"/api/repos/{repo_id}", json={"path": str(a_file)})
    assert r.status_code == 400


# ── Concurrent scan 409 regression ───────────────────────────────────────────

def test_concurrent_scan_409_regression(test_app, tmp_path):
    """POST /api/fleet/scan returns 409 when a scan is already running."""
    client, db_path = test_app
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO scan_log (scan_type, started_at, status) "
        "VALUES ('full','2026-01-01T00:00:00','running')"
    )
    conn.commit()
    conn.close()

    r = client.post("/api/fleet/scan", json={"type": "full"})
    assert r.status_code == 409


# ── dep_check_error tests ────────────────────────────────────────────────────

def test_dep_check_error_flag(test_app, tmp_path):
    """run_dep_scan_for_repo sets dep_check_error=True when an ecosystem check raises."""
    client, db_path = test_app
    repo_dir = tmp_path / "dep_err"
    repo_dir.mkdir()
    (repo_dir / "requirements.txt").write_text("requests==2.31.0\n")
    repo_id = _insert_repo(db_path, "dep_err", str(repo_dir))

    def raise_exc(*args, **kwargs):
        raise RuntimeError("forced failure")

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            with (
                patch.object(git_dashboard, "check_python_deps", raise_exc),
                patch.object(git_dashboard, "check_node_deps", raise_exc),
                patch.object(git_dashboard, "check_go_deps", raise_exc),
                patch.object(git_dashboard, "check_rust_deps", raise_exc),
                patch.object(git_dashboard, "check_ruby_deps", raise_exc),
                patch.object(git_dashboard, "check_php_deps", raise_exc),
            ):
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, str(repo_dir))
            await db.commit()

    asyncio.run(_run())
    val = _read_ws(db_path, repo_id, "dep_check_error")
    assert bool(val) is True, "dep_check_error must be True after all checks fail"


def test_dep_check_error_cleared_on_success(test_app, tmp_path):
    """dep_check_error is cleared to False after a successful dep scan."""
    client, db_path = test_app
    repo_dir = tmp_path / "dep_clear"
    repo_dir.mkdir()
    (repo_dir / "requirements.txt").write_text("requests==2.31.0\n")
    repo_id = _insert_repo(db_path, "dep_clear", str(repo_dir))
    _set_ws(db_path, repo_id, dep_check_error=1)

    def identity(repo_path, deps):
        return deps

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            with (
                patch.object(git_dashboard, "check_python_deps", identity),
                patch.object(git_dashboard, "check_node_deps", identity),
                patch.object(git_dashboard, "check_go_deps", identity),
                patch.object(git_dashboard, "check_rust_deps", identity),
                patch.object(git_dashboard, "check_ruby_deps", identity),
                patch.object(git_dashboard, "check_php_deps", identity),
            ):
                await git_dashboard.run_dep_scan_for_repo(db, repo_id, str(repo_dir))
            await db.commit()

    asyncio.run(_run())
    val = _read_ws(db_path, repo_id, "dep_check_error")
    assert bool(val) is False, "dep_check_error must be False after successful checks"


# ── Migration idempotency ────────────────────────────────────────────────────

def test_migration_idempotent(tmp_path):
    """run_migrations is idempotent — running twice does not raise."""
    db_path = tmp_path / "mig_test.db"
    git_dashboard.init_schema(db_path)
    git_dashboard.run_migrations(db_path)  # first run
    git_dashboard.run_migrations(db_path)  # second run — must not raise


# ── HTML template tests ──────────────────────────────────────────────────────

def test_card_path_not_found_ui(client):
    """GET / HTML contains 'Path not found' error text for cards."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Path not found" in r.text


def test_card_scan_failed_badge_ui(client):
    """GET / HTML contains 'scan failed' badge text."""
    r = client.get("/")
    assert r.status_code == 200
    assert "scan failed" in r.text


def test_detail_remove_update_buttons_ui(client):
    """GET / HTML contains both 'Remove' and 'Update Path' button strings."""
    r = client.get("/")
    assert r.status_code == 200
    assert "Remove" in r.text
    assert "Update Path" in r.text


def test_offline_indicator_ui(client):
    """GET / HTML contains 'offline' in the dep check indicator context."""
    r = client.get("/")
    assert r.status_code == 200
    assert "offline" in r.text
