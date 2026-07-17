"""
Packet 11 — Commits & Branches Sub-tabs: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_commits_branches_subtabs.py -v
"""

import asyncio
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

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

def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo with 15 commits; return (repo_path, n_commits)."""
    n_commits = 15
    repo = tmp_path / "git_repo"
    repo.mkdir()
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "synthetic-user@example.invalid",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "synthetic-user@example.invalid",
        "HOME": str(tmp_path),
    })
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "synthetic-user@example.invalid"],
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        check=True, capture_output=True, env=env,
    )
    for i in range(n_commits):
        f = repo / f"file{i}.txt"
        f.write_text(f"content {i}\n" * (i + 1))
        subprocess.run(
            ["git", "-C", str(repo), "add", f.name],
            check=True, capture_output=True, env=env,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", f"commit {i}: add file{i}"],
            check=True, capture_output=True, env=env,
        )
    return repo, n_commits


@pytest.fixture
def empty_git_repo(tmp_path):
    """Create an init-only git repo with zero commits."""
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    env = dict(os.environ)
    env.update({"HOME": str(tmp_path)})
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, env=env)
    return repo


def _insert_repo(db_path, repo_id="testrepo001", name="myrepo",
                 path="/tmp/myrepo", runtime="python", default_branch="main"):
    """Insert a repo row synchronously."""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT OR IGNORE INTO repositories (id, name, path, runtime, default_branch, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (repo_id, name, path, runtime, default_branch, now),
        )
        conn.commit()


def _insert_branches(db_path, repo_id, branches):
    """Insert branches rows: branches = list of (name, last_commit_date, is_default, is_stale)."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executemany(
            "INSERT OR REPLACE INTO branches "
            "(repo_id, name, last_commit_date, is_default, is_stale) "
            "VALUES (?, ?, ?, ?, ?)",
            [(repo_id, *row) for row in branches],
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET /api/repos/{id}/commits — basic response shape
# ─────────────────────────────────────────────────────────────────────────────

def test_commits_basic_shape(test_app, git_repo):
    """GET /api/repos/{id}/commits returns 200 with correct top-level and commit keys."""
    client, db_path = test_app
    repo_path, n_commits = git_repo
    _insert_repo(db_path, repo_id="repo001", path=str(repo_path))

    resp = client.get("/api/repos/repo001/commits")
    assert resp.status_code == 200

    data = resp.json()
    for key in ("commits", "page", "per_page", "total"):
        assert key in data, f"Missing top-level key: {key}"

    assert isinstance(data["commits"], list)
    assert len(data["commits"]) > 0

    c = data["commits"][0]
    for field in ("hash", "date", "author", "message", "insertions", "deletions", "files_changed"):
        assert field in c, f"Commit object missing field: {field}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET /api/repos/{id}/commits — pagination defaults
# ─────────────────────────────────────────────────────────────────────────────

def test_commits_pagination_defaults(test_app, git_repo):
    """Call without params; assert page==1, per_page==25."""
    client, db_path = test_app
    repo_path, _ = git_repo
    _insert_repo(db_path, repo_id="repo002", path=str(repo_path))

    resp = client.get("/api/repos/repo002/commits")
    assert resp.status_code == 200

    data = resp.json()
    assert data["page"] == 1
    assert data["per_page"] == 25


# ─────────────────────────────────────────────────────────────────────────────
# 3. GET /api/repos/{id}/commits — pagination params
# ─────────────────────────────────────────────────────────────────────────────

def test_commits_pagination_params(test_app, git_repo):
    """Call with ?page=2&per_page=5; assert page==2, per_page==5, commits length <= 5."""
    client, db_path = test_app
    repo_path, n_commits = git_repo  # 15 commits
    _insert_repo(db_path, repo_id="repo003", path=str(repo_path))

    resp = client.get("/api/repos/repo003/commits?page=2&per_page=5")
    assert resp.status_code == 200

    data = resp.json()
    assert data["page"] == 2
    assert data["per_page"] == 5
    assert len(data["commits"]) <= 5
    # With 15 commits and per_page=5, page 2 should have exactly 5 commits
    assert len(data["commits"]) == 5

    # Verify total reflects actual commit count
    assert data["total"] == n_commits

    # page 1 commits should not overlap with page 2 commits
    resp1 = client.get("/api/repos/repo003/commits?page=1&per_page=5")
    hashes_p1 = {c["hash"] for c in resp1.json()["commits"]}
    hashes_p2 = {c["hash"] for c in data["commits"]}
    assert hashes_p1.isdisjoint(hashes_p2), "Page 1 and page 2 commits must not overlap"


# ─────────────────────────────────────────────────────────────────────────────
# 4. GET /api/repos/{id}/commits — 404 for unknown repo
# ─────────────────────────────────────────────────────────────────────────────

def test_commits_404_unknown_repo(test_app):
    """GET /api/repos/nonexistent/commits returns 404."""
    client, _ = test_app
    resp = client.get("/api/repos/does_not_exist_xyz/commits")
    assert resp.status_code == 404
    assert "detail" in resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET /api/repos/{id}/commits — empty repo (no commits)
# ─────────────────────────────────────────────────────────────────────────────

def test_commits_empty_repo(test_app, empty_git_repo):
    """Repo with zero commits returns commits==[], total==0."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo005", path=str(empty_git_repo))

    resp = client.get("/api/repos/repo005/commits")
    assert resp.status_code == 200

    data = resp.json()
    assert data["commits"] == []
    assert data["total"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. GET /api/repos/{id}/branches — basic response shape
# ─────────────────────────────────────────────────────────────────────────────

def test_branches_basic_shape(test_app):
    """GET /api/repos/{id}/branches returns 200 with branches list; each branch has required keys."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo006")
    _insert_branches(db_path, "repo006", [
        ("main", "2026-03-01", 1, 0),
        ("feature/auth", "2025-12-01", 0, 1),
    ])

    resp = client.get("/api/repos/repo006/branches")
    assert resp.status_code == 200

    data = resp.json()
    assert "branches" in data
    assert isinstance(data["branches"], list)
    assert len(data["branches"]) == 2

    b = data["branches"][0]
    for field in ("name", "last_commit_date", "is_default", "is_stale"):
        assert field in b, f"Branch object missing field: {field}"

    assert isinstance(b["is_default"], bool)
    assert isinstance(b["is_stale"], bool)


# ─────────────────────────────────────────────────────────────────────────────
# 7. GET /api/repos/{id}/branches — sort order
# ─────────────────────────────────────────────────────────────────────────────

def test_branches_sort_order(test_app):
    """Default branch first regardless of date, then by last_commit_date desc."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo007")
    # Insert main with a very old date but is_default=1
    _insert_branches(db_path, "repo007", [
        ("main",          "2020-01-01", 1, 1),   # default, very old
        ("feature/new",   "2026-03-09", 0, 0),   # most recent
        ("feature/old",   "2025-06-01", 0, 1),   # stale
    ])

    resp = client.get("/api/repos/repo007/branches")
    assert resp.status_code == 200

    branches = resp.json()["branches"]
    assert len(branches) == 3

    # Default branch must be first
    assert branches[0]["name"] == "main"
    assert branches[0]["is_default"] is True
    assert branches[0]["is_stale"] is False

    # Remaining sorted by last_commit_date desc
    assert branches[1]["name"] == "feature/new"
    assert branches[2]["name"] == "feature/old"


# ─────────────────────────────────────────────────────────────────────────────
# 8. GET /api/repos/{id}/branches — 404 for unknown repo
# ─────────────────────────────────────────────────────────────────────────────

def test_branches_404_unknown_repo(test_app):
    """GET /api/repos/nonexistent/branches returns 404."""
    client, _ = test_app
    resp = client.get("/api/repos/nonexistent_xyz/branches")
    assert resp.status_code == 404
    assert "detail" in resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# 9. GET /api/repos/{id}/branches — no branches in DB
# ─────────────────────────────────────────────────────────────────────────────

def test_branches_empty(test_app):
    """Repo registered but no branch rows returns branches==[]."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo009")

    resp = client.get("/api/repos/repo009/branches")
    assert resp.status_code == 200
    assert resp.json()["branches"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 10. CommitsTab component exists in HTML_TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────

def test_commits_tab_component_exists():
    """HTML_TEMPLATE contains CommitsTab function definition."""
    assert "function CommitsTab" in git_dashboard.HTML_TEMPLATE


# ─────────────────────────────────────────────────────────────────────────────
# 11. BranchesTab component exists in HTML_TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────

def test_branches_tab_component_exists():
    """HTML_TEMPLATE contains BranchesTab function definition."""
    assert "function BranchesTab" in git_dashboard.HTML_TEMPLATE


# ─────────────────────────────────────────────────────────────────────────────
# 12. PlaceholderTab not used for Commits or Branches
# ─────────────────────────────────────────────────────────────────────────────

def test_placeholder_tab_not_used_for_commits_branches():
    """PlaceholderTab text="Commits" and PlaceholderTab text="Branches" must not appear."""
    tmpl = git_dashboard.HTML_TEMPLATE
    assert 'PlaceholderTab text="Commits"' not in tmpl, \
        "Commits subtab still uses PlaceholderTab"
    assert 'PlaceholderTab text="Branches"' not in tmpl, \
        "Branches subtab still uses PlaceholderTab"


# ─────────────────────────────────────────────────────────────────────────────
# 13. Pagination UI exists in HTML_TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────

def test_pagination_ui_exists():
    """HTML_TEMPLATE contains pagination display text pattern 'Page '."""
    assert "Page " in git_dashboard.HTML_TEMPLATE


# ─────────────────────────────────────────────────────────────────────────────
# 14. Hash routing — parseRoute handles sub-tab segments
# ─────────────────────────────────────────────────────────────────────────────

def test_hash_routing_subtab_in_template():
    """HTML_TEMPLATE contains sub-tab hash routing patterns."""
    tmpl = git_dashboard.HTML_TEMPLATE
    # The routing must handle /commits and /branches sub-tab segments
    assert "#/repo/" in tmpl
    # ProjectDetail must receive an initialSubTab prop
    assert "initialSubTab" in tmpl


# ─────────────────────────────────────────────────────────────────────────────
# 15. Commits total matches actual git commit count
# ─────────────────────────────────────────────────────────────────────────────

def test_commits_total_accurate(test_app, git_repo):
    """total field in response matches the actual git commit count."""
    client, db_path = test_app
    repo_path, n_commits = git_repo
    _insert_repo(db_path, repo_id="repo015", path=str(repo_path))

    resp = client.get("/api/repos/repo015/commits")
    assert resp.status_code == 200
    assert resp.json()["total"] == n_commits


# ─────────────────────────────────────────────────────────────────────────────
# 16. Pagination clamping (23A gap 8)
# ─────────────────────────────────────────────────────────────────────────────

def test_commits_page_zero_clamped_to_one(test_app, git_repo):
    """page=0 must be clamped to page=1 — the response page field must equal 1."""
    client, db_path = test_app
    repo_path, _ = git_repo
    _insert_repo(db_path, repo_id="repo016", path=str(repo_path))

    resp = client.get("/api/repos/repo016/commits?page=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1, f"page=0 should be clamped to 1, got {data['page']}"


def test_commits_page_negative_clamped_to_one(test_app, git_repo):
    """page=-5 must be clamped to page=1."""
    client, db_path = test_app
    repo_path, _ = git_repo
    _insert_repo(db_path, repo_id="repo017", path=str(repo_path))

    resp = client.get("/api/repos/repo017/commits?page=-5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1, f"page=-5 should be clamped to 1, got {data['page']}"


def test_commits_per_page_zero_clamped_to_one(test_app, git_repo):
    """per_page=0 must be clamped to per_page=1 — at most 1 commit returned."""
    client, db_path = test_app
    repo_path, _ = git_repo
    _insert_repo(db_path, repo_id="repo018", path=str(repo_path))

    resp = client.get("/api/repos/repo018/commits?per_page=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["per_page"] == 1, f"per_page=0 should be clamped to 1, got {data['per_page']}"
    assert len(data["commits"]) <= 1


def test_commits_per_page_over_limit_clamped_to_100(test_app, git_repo):
    """per_page=200 must be clamped to per_page=100."""
    client, db_path = test_app
    repo_path, _ = git_repo
    _insert_repo(db_path, repo_id="repo019", path=str(repo_path))

    resp = client.get("/api/repos/repo019/commits?per_page=200")
    assert resp.status_code == 200
    data = resp.json()
    assert data["per_page"] == 100, f"per_page=200 should be clamped to 100, got {data['per_page']}"


# ─────────────────────────────────────────────────────────────────────────────
# 17. Page beyond total pages returns empty commits list
# ─────────────────────────────────────────────────────────────────────────────

def test_commits_page_beyond_total_returns_empty(test_app, git_repo):
    """page=100 with only 15 commits (1 page at per_page=25) returns commits=[], total=15."""
    client, db_path = test_app
    repo_path, n_commits = git_repo
    _insert_repo(db_path, repo_id="repo020", path=str(repo_path))

    resp = client.get("/api/repos/repo020/commits?page=100")
    assert resp.status_code == 200
    data = resp.json()
    assert data["commits"] == [], "Page beyond total should return empty list"
    assert data["total"] == n_commits, "Total must still reflect actual commit count"
    assert data["page"] == 100
