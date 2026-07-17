"""
Packet 02 — Repo Discovery & Registration API: Tests

Run from project root after bootstrapping:
    ~/.git_dashboard_venv/bin/python -m pytest tests/test_repo_discovery.py -v
"""

import asyncio
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

# git_dashboard.py is in the project root (parent of this tests/ directory)
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import guard: bootstrap() must pass without re-execing in test context ───
try:
    import fastapi  # noqa: F401
    import aiosqlite  # noqa: F401
except ImportError:
    pytest.skip(
        "fastapi/aiosqlite not installed — run tests inside the app venv: "
        "~/.git_dashboard_venv/bin/python -m pytest",
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
# 1. discover_repos — finds repos recursively
# ─────────────────────────────────────────────────────────────────────────────

def test_discover_repos_finds_git_repos(tmp_path):
    """discover_repos finds all git repos in a directory tree."""
    dir_a = tmp_path / "repo_a"
    dir_b = tmp_path / "repo_b"
    dir_c = tmp_path / "plain_dir"

    _make_git_repo(dir_a)
    _make_git_repo(dir_b)
    dir_c.mkdir()

    repos = run(git_dashboard.discover_repos(tmp_path))
    paths = {r["path"] for r in repos}

    assert str(dir_a.resolve()) in paths
    assert str(dir_b.resolve()) in paths
    assert len(repos) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 2. discover_repos — skips non-git directories
# ─────────────────────────────────────────────────────────────────────────────

def test_discover_repos_skips_non_git_directories(tmp_path):
    """discover_repos returns empty list when no .git dirs exist."""
    (tmp_path / "dir_a").mkdir()
    (tmp_path / "dir_b").mkdir()

    repos = run(git_dashboard.discover_repos(tmp_path))
    assert repos == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. discover_repos — deduplicates submodule-style nested repos
# ─────────────────────────────────────────────────────────────────────────────

def test_discover_repos_deduplicates_submodules(tmp_path):
    """discover_repos stops descending into a repo once found, excluding nested repos."""
    outer = tmp_path / "outer"
    _make_git_repo(outer)

    # Create a nested git repo (simulating a submodule inside outer/)
    inner = outer / "submodule"
    _make_git_repo(inner)

    repos = run(git_dashboard.discover_repos(tmp_path))
    paths = {r["path"] for r in repos}

    # outer is found; inner is NOT discovered (we stop descending at outer/.git)
    assert str(outer.resolve()) in paths
    assert str(inner.resolve()) not in paths
    assert len(repos) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. discover_repos — skips hidden dirs and common excludes
# ─────────────────────────────────────────────────────────────────────────────

def test_discover_repos_skips_hidden_and_exclude_dirs(tmp_path):
    """discover_repos skips .hidden, node_modules, .venv, venv, __pycache__."""
    skip_targets = [
        tmp_path / ".hidden_dir",
        tmp_path / "node_modules",
        tmp_path / ".venv",
        tmp_path / "venv",
        tmp_path / "__pycache__",
    ]
    for d in skip_targets:
        _make_git_repo(d)

    repos = run(git_dashboard.discover_repos(tmp_path))
    assert repos == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. generate_repo_id — deterministic and unique
# ─────────────────────────────────────────────────────────────────────────────

def test_generate_repo_id_is_deterministic():
    """generate_repo_id returns the same 16-char hex for the same path."""
    path = "/Users/example/repos/myapp"
    id1 = git_dashboard.generate_repo_id(path)
    id2 = git_dashboard.generate_repo_id(path)
    assert id1 == id2
    assert len(id1) == 16
    # Verify it matches sha256[:16] independently
    expected = hashlib.sha256(path.encode()).hexdigest()[:16]
    assert id1 == expected


def test_generate_repo_id_different_paths_differ():
    """Different paths produce different repo IDs."""
    id_a = git_dashboard.generate_repo_id("/repos/alpha")
    id_b = git_dashboard.generate_repo_id("/repos/beta")
    assert id_a != id_b


# ─────────────────────────────────────────────────────────────────────────────
# 6–9. detect_runtime
# ─────────────────────────────────────────────────────────────────────────────

def test_detect_runtime_python_pyproject(tmp_path):
    """pyproject.toml → runtime = 'python'."""
    (tmp_path / "pyproject.toml").touch()
    assert git_dashboard.detect_runtime(tmp_path) == "python"


def test_detect_runtime_python_requirements(tmp_path):
    """requirements.txt (without pyproject.toml) → runtime = 'python'."""
    (tmp_path / "requirements.txt").touch()
    assert git_dashboard.detect_runtime(tmp_path) == "python"


def test_detect_runtime_node(tmp_path):
    """package.json → runtime = 'node'."""
    (tmp_path / "package.json").touch()
    assert git_dashboard.detect_runtime(tmp_path) == "node"


def test_detect_runtime_mixed(tmp_path):
    """pyproject.toml + package.json → runtime = 'mixed'."""
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "package.json").touch()
    assert git_dashboard.detect_runtime(tmp_path) == "mixed"


def test_detect_runtime_unknown(tmp_path):
    """No known ecosystem files → runtime = 'unknown'."""
    (tmp_path / "somefile.txt").touch()
    assert git_dashboard.detect_runtime(tmp_path) == "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# 10. POST /api/repos — registers repos
# ─────────────────────────────────────────────────────────────────────────────

def test_post_repos_registers_repos(test_app, tmp_path):
    """POST /api/repos discovers git repos and returns registered list."""
    client, _ = test_app

    _make_git_repo(tmp_path / "repo_a")
    _make_git_repo(tmp_path / "repo_b")

    response = client.post("/api/repos", json={"path": str(tmp_path)})
    assert response.status_code == 200

    data = response.json()
    assert data["registered"] == 2
    assert len(data["repos"]) == 2

    for repo in data["repos"]:
        assert "id" in repo
        assert "name" in repo
        assert "path" in repo


# ─────────────────────────────────────────────────────────────────────────────
# 11. POST /api/repos — idempotent
# ─────────────────────────────────────────────────────────────────────────────

def test_post_repos_is_idempotent(test_app, tmp_path):
    """Registering the same directory twice doesn't create duplicates."""
    client, _ = test_app

    _make_git_repo(tmp_path / "repo_a")
    _make_git_repo(tmp_path / "repo_b")

    client.post("/api/repos", json={"path": str(tmp_path)})
    client.post("/api/repos", json={"path": str(tmp_path)})

    response = client.get("/api/repos")
    assert response.status_code == 200
    assert len(response.json()["repos"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 12. DELETE /api/repos/{id} — removes a repo
# ─────────────────────────────────────────────────────────────────────────────

def test_delete_repo_removes_it(test_app, tmp_path):
    """DELETE /api/repos/{id} returns 204 and the repo is gone from GET."""
    client, _ = test_app

    _make_git_repo(tmp_path / "repo_a")
    _make_git_repo(tmp_path / "repo_b")

    post_resp = client.post("/api/repos", json={"path": str(tmp_path)})
    repos = post_resp.json()["repos"]
    target_id = repos[0]["id"]

    del_resp = client.delete(f"/api/repos/{target_id}")
    assert del_resp.status_code == 204

    get_resp = client.get("/api/repos")
    remaining_ids = {r["id"] for r in get_resp.json()["repos"]}
    assert target_id not in remaining_ids
    assert len(remaining_ids) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 13. DELETE /api/repos/{id} — cascades to related tables
# ─────────────────────────────────────────────────────────────────────────────

def test_delete_cascades_to_working_state(test_app, tmp_path):
    """Deleting a repo also removes its working_state row (CASCADE)."""
    client, db_path = test_app

    _make_git_repo(tmp_path / "repo_a")

    post_resp = client.post("/api/repos", json={"path": str(tmp_path)})
    repo_id = post_resp.json()["repos"][0]["id"]

    # Insert a working_state row for this repo
    async def insert_ws():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(
                "INSERT OR REPLACE INTO working_state (repo_id, checked_at) VALUES (?, ?)",
                (repo_id, "2026-01-01T00:00:00Z"),
            )
            await db.commit()

    run(insert_ws())

    # Verify the row exists
    async def fetch_ws():
        async with aiosqlite.connect(str(db_path)) as db:
            cursor = await db.execute(
                "SELECT repo_id FROM working_state WHERE repo_id = ?", (repo_id,)
            )
            return await cursor.fetchone()

    assert run(fetch_ws()) is not None

    # Delete the repo
    client.delete(f"/api/repos/{repo_id}")

    # working_state row should be gone (CASCADE)
    assert run(fetch_ws()) is None


# ─────────────────────────────────────────────────────────────────────────────
# 13b. DELETE /api/repos/{id} — cascades to ALL child tables
# ─────────────────────────────────────────────────────────────────────────────

def test_delete_cascades_to_all_child_tables(test_app, tmp_path):
    """Deleting a repo removes rows from daily_stats, branches, dependencies,
    and working_state — not just the repositories row."""
    client, db_path = test_app

    _make_git_repo(tmp_path / "repo_a")
    post_resp = client.post("/api/repos", json={"path": str(tmp_path)})
    repo_id = post_resp.json()["repos"][0]["id"]

    # Insert child rows in every FK table
    async def seed_child_rows():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(
                "INSERT OR REPLACE INTO working_state (repo_id, checked_at) "
                "VALUES (?, '2026-01-01T00:00:00Z')",
                (repo_id,),
            )
            await db.execute(
                "INSERT INTO daily_stats (repo_id, date, commits, insertions, deletions, files_changed) "
                "VALUES (?, '2026-01-01', 5, 100, 50, 10)",
                (repo_id,),
            )
            await db.execute(
                "INSERT INTO branches (repo_id, name, last_commit_date, is_default, is_stale) "
                "VALUES (?, 'main', '2026-01-01', 1, 0)",
                (repo_id,),
            )
            await db.execute(
                "INSERT INTO dependencies (repo_id, manager, name, current_version) "
                "VALUES (?, 'pip', 'flask', '2.3.0')",
                (repo_id,),
            )
            await db.commit()

    run(seed_child_rows())

    # Verify child rows exist
    async def count_children():
        async with aiosqlite.connect(str(db_path)) as db:
            counts = {}
            for table in ("working_state", "daily_stats", "branches", "dependencies"):
                cursor = await db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE repo_id = ?", (repo_id,)
                )
                counts[table] = (await cursor.fetchone())[0]
            return counts

    before = run(count_children())
    assert all(v >= 1 for v in before.values()), f"Seed failed: {before}"

    # Delete the repo
    del_resp = client.delete(f"/api/repos/{repo_id}")
    assert del_resp.status_code == 204

    # All child rows must be gone
    after = run(count_children())
    assert all(v == 0 for v in after.values()), (
        f"CASCADE delete left orphaned rows: {after}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 14. POST /api/repos — nonexistent path returns 400
# ─────────────────────────────────────────────────────────────────────────────

def test_post_repos_nonexistent_path_returns_400(test_app):
    """POST /api/repos with a nonexistent path returns 400."""
    client, _ = test_app

    response = client.post("/api/repos", json={"path": "/nonexistent/path/that/does/not/exist"})
    assert response.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 15. DELETE /api/repos/{id} — 404 for nonexistent repo
# ─────────────────────────────────────────────────────────────────────────────

def test_delete_nonexistent_repo_returns_404(test_app):
    """DELETE /api/repos/{id} returns 404 when the ID doesn't exist."""
    client, _ = test_app

    response = client.delete("/api/repos/0000000000000000")
    assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 16. POST /api/repos — file path (not directory) returns 400
# ─────────────────────────────────────────────────────────────────────────────

def test_post_repos_file_path_returns_400(test_app, tmp_path):
    """POST /api/repos with a file path (not a directory) returns 400."""
    client, _ = test_app

    file_path = tmp_path / "not_a_directory.txt"
    file_path.write_text("hello")

    response = client.post("/api/repos", json={"path": str(file_path)})
    assert response.status_code == 400
    assert "not a directory" in response.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 17. POST /api/repos — error message includes the invalid path
# ─────────────────────────────────────────────────────────────────────────────

def test_post_repos_400_error_message_includes_path(test_app):
    """POST /api/repos 400 error includes the path in the detail message."""
    client, _ = test_app

    bad_path = "/nonexistent/path/that/does/not/exist"
    response = client.post("/api/repos", json={"path": bad_path})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert bad_path in detail, f"Error message should include the path, got: {detail}"


# ─────────────────────────────────────────────────────────────────────────────
# 18. POST /api/repos — directory with no repos returns 0 registered
# ─────────────────────────────────────────────────────────────────────────────

def test_post_repos_empty_dir_returns_zero(test_app, tmp_path):
    """POST /api/repos on a directory with no git repos returns registered=0, repos=[]."""
    client, _ = test_app

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    response = client.post("/api/repos", json={"path": str(empty_dir)})
    assert response.status_code == 200
    data = response.json()
    assert data["registered"] == 0
    assert data["repos"] == []
