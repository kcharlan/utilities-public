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
import shutil
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
        "fastapi/aiosqlite not installed — run from the repository root: "
        "UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet",
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
    for key, expected in {"has_uncommitted": False, "modified_count": 0,
                          "untracked_count": 0, "staged_count": 0,
                          "quick_scan_error": None}.items():
        assert matches[0][key] == expected


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

def test_fleet_exposes_and_clears_quick_scan_error(test_app, tmp_path):
    client, db_path = test_app
    repo = _make_git_repo(tmp_path / "corrupt")
    _insert_repo(db_path, "corrupt", str(repo))
    (repo / ".git" / "index").write_bytes(b"synthetic corrupt index")
    assert client.post("/api/fleet/refresh").status_code == 200
    failed = client.get("/api/fleet").json()["repos"][0]
    assert failed["quick_scan_error"]
    assert failed["has_uncommitted"] is None
    assert all(failed[key] is None for key in ("modified_count", "untracked_count", "staged_count"))
    (repo / ".git" / "index").unlink()
    subprocess.run(["git", "-C", str(repo), "reset"], check=True, capture_output=True)
    assert client.post("/api/fleet/refresh").status_code == 200
    restored = client.get("/api/fleet").json()["repos"][0]
    assert restored["quick_scan_error"] is None
    assert restored["has_uncommitted"] is False

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

@pytest.mark.parametrize("case, expected", [
    ("failed_and_recovered", (None, None, None, None, "error")),
    ("dirty", (True, 0, 1, 0, None)),
    ("clean", (False, 0, 0, 0, None)),
    ("missing_dirty", (False, 0, 0, 0, None)),
    ("missing_failed", (False, 0, 0, 0, None)),
    ("default_row", (False, 0, 0, 0, None)),
    ("explicit_null_row", (False, 0, 0, 0, None)),
    ("empty_error", (True, 2, 3, 4, "")),
])
def test_repo_detail_quick_status_matches_fleet(test_app, tmp_path, case, expected):
    client, db_path = test_app
    repo = _make_git_repo(tmp_path / "synthetic")
    repo_id = _insert_repo(db_path, "synthetic", str(repo))
    if case in ("dirty", "missing_dirty"):
        (repo / "untracked.txt").write_text("synthetic")
    if case in ("failed_and_recovered", "missing_failed"):
        (repo / ".git" / "index").write_bytes(b"synthetic corrupt index")
    if case in ("dirty", "clean", "missing_dirty", "missing_failed", "failed_and_recovered"):
        assert client.post("/api/fleet/refresh").status_code == 200
    elif case == "explicit_null_row":
        _set_ws(db_path, repo_id, has_uncommitted=None, modified_count=None,
                untracked_count=None, staged_count=None)
    elif case == "empty_error":
        _set_ws(db_path, repo_id, has_uncommitted=1, modified_count=2,
                untracked_count=3, staged_count=4, quick_scan_error="")
    else:
        _set_ws(db_path, repo_id)
    if case.startswith("missing_"):
        shutil.rmtree(repo)

    keys = ("has_uncommitted", "modified_count", "untracked_count", "staged_count", "quick_scan_error")

    def check(values):
        fleet_response = client.get("/api/fleet")
        detail_response = client.get(f"/api/repos/{repo_id}")
        assert fleet_response.status_code == detail_response.status_code == 200
        fleet = next(item for item in fleet_response.json()["repos"] if item["id"] == repo_id)
        detail = detail_response.json()["working_state"]
        for key, value in zip(keys, values):
            if key == "quick_scan_error" and value == "error":
                assert fleet[key]
                assert detail[key] == fleet[key]
            else:
                assert fleet[key] == value
                assert detail[key] == value

    check(expected)
    if case == "failed_and_recovered":
        (repo / ".git" / "index").unlink()
        subprocess.run(["git", "-C", str(repo), "reset"], check=True, capture_output=True)
        assert client.post("/api/fleet/refresh").status_code == 200
        check((False, 0, 0, 0, None))


def test_repo_detail_without_working_state(test_app, tmp_path):
    client, db_path = test_app
    repo = _make_git_repo(tmp_path / "no_state")
    repo_id = _insert_repo(db_path, "no_state", str(repo))
    detail = client.get(f"/api/repos/{repo_id}")
    fleet = client.get("/api/fleet")
    assert detail.status_code == fleet.status_code == 200
    assert detail.json()["working_state"] is None
    entry = next(item for item in fleet.json()["repos"] if item["id"] == repo_id)
    for key, value in {"has_uncommitted": False, "modified_count": 0, "untracked_count": 0,
                       "staged_count": 0, "quick_scan_error": None}.items():
        assert entry[key] == value


@pytest.mark.parametrize("missing", [False, True])
def test_repo_detail_status_presentation_preserves_metadata_and_storage(test_app, tmp_path, missing):
    client, db_path = test_app
    repo = _make_git_repo(tmp_path / "metadata")
    repo_id = _insert_repo(db_path, "metadata", str(repo))
    _set_ws(db_path, repo_id, has_uncommitted=1, modified_count=2, untracked_count=3,
            staged_count=4, quick_scan_error="synthetic failure", current_branch="sample",
            last_commit_hash="abc", last_commit_message="synthetic", last_commit_date="2026-01-01",
            checked_at="2026-01-02", dep_check_error=1,
            missing_dep_tools='[{"tool":"synthetic"}]', dep_manifests='[{"path":"synthetic"}]')
    columns = "has_uncommitted, modified_count, untracked_count, staged_count, quick_scan_error"
    with sqlite3.connect(db_path) as conn:
        before = conn.execute(f"SELECT {columns} FROM working_state WHERE repo_id=?", (repo_id,)).fetchone()
    if missing:
        shutil.rmtree(repo)
    fleet = client.get("/api/fleet")
    detail = client.get(f"/api/repos/{repo_id}")
    assert fleet.status_code == detail.status_code == 200
    entry = next(item for item in fleet.json()["repos"] if item["id"] == repo_id)
    ws = detail.json()["working_state"]
    expected = (False, 0, 0, 0, None) if missing else (None, None, None, None, "synthetic failure")
    for key, value in zip(("has_uncommitted", "modified_count", "untracked_count", "staged_count", "quick_scan_error"), expected):
        assert entry[key] == value
        assert ws[key] == value
    for key, value in {"current_branch": "sample", "last_commit_hash": "abc",
                       "last_commit_message": "synthetic", "last_commit_date": "2026-01-01",
                       "checked_at": "2026-01-02", "dep_check_error": True,
                       "missing_dep_tools": [{"tool": "synthetic"}],
                       "dep_manifests": [{"path": "synthetic"}]}.items():
        assert ws[key] == value
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(f"SELECT {columns} FROM working_state WHERE repo_id=?", (repo_id,)).fetchone() == before

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
        return [dict(d, outdated_state='checked', vuln_state='checked') for d in deps]

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            with (
                patch.object(git_dashboard, "TOOLS", dict(pip_audit='synthetic-tool')),
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


def test_migration_adds_quick_scan_error_to_existing_database(tmp_path):
    db_path = tmp_path / "legacy.db"
    git_dashboard.init_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE working_state DROP COLUMN quick_scan_error")
    git_dashboard.run_migrations(db_path)
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(working_state)")}
    assert "quick_scan_error" in columns


# ── HTML template tests ──────────────────────────────────────────────────────
