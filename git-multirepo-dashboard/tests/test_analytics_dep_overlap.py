"""
Packet 20 — Analytics: Dep Overlap: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_analytics_dep_overlap.py -v
"""

import sqlite3
import sys
from datetime import datetime, timezone
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


def _insert_repo(db_path, repo_id, name, path=None):
    """Insert a minimal repo row."""
    if path is None:
        path = f"/tmp/{name}"
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT OR IGNORE INTO repositories (id, name, path, runtime, default_branch, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (repo_id, name, path, "unknown", "main", now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO working_state "
            "(repo_id, has_uncommitted, modified_count, untracked_count, staged_count, "
            " current_branch, last_commit_hash, last_commit_message, last_commit_date, checked_at) "
            "VALUES (?, 0, 0, 0, 0, 'main', NULL, NULL, NULL, ?)",
            (repo_id, now),
        )
        conn.commit()


def _insert_dep(db_path, repo_id, name, manager, current_version=None):
    """Insert a dependency row."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT OR REPLACE INTO dependencies "
            "(repo_id, manager, name, current_version, severity) "
            "VALUES (?, ?, ?, ?, 'ok')",
            (repo_id, manager, name, current_version),
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_dep_overlap_empty_db(test_app):
    """No dependencies rows → 200, {"packages": []}."""
    client, _ = test_app
    resp = client.get("/api/analytics/dep-overlap")
    assert resp.status_code == 200
    assert resp.json() == {"packages": []}


def test_dep_overlap_single_repo_excluded(test_app):
    """Dependencies in only one repo → packages list is empty (requires 2+)."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001", "only-repo")
    _insert_dep(db_path, "repo001", "requests", "pip", "2.31.0")
    _insert_dep(db_path, "repo001", "flask", "pip", "3.0.0")

    resp = client.get("/api/analytics/dep-overlap")
    assert resp.status_code == 200
    assert resp.json() == {"packages": []}


def test_dep_overlap_two_repos_shared(test_app):
    """fastapi in repo A (0.109.0) and repo B (0.115.0) → 1 package entry."""
    client, db_path = test_app
    _insert_repo(db_path, "repoA", "routerview")
    _insert_repo(db_path, "repoB", "editdb")
    _insert_dep(db_path, "repoA", "fastapi", "pip", "0.109.0")
    _insert_dep(db_path, "repoB", "fastapi", "pip", "0.115.0")

    resp = client.get("/api/analytics/dep-overlap")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["packages"]) == 1
    pkg = body["packages"][0]
    assert pkg["name"] == "fastapi"
    assert pkg["manager"] == "pip"
    assert pkg["count"] == 2
    assert pkg["version_spread"] == "0.109.0 - 0.115.0"

    repos = {r["repo_id"]: r for r in pkg["repos"]}
    assert "repoA" in repos
    assert "repoB" in repos
    assert repos["repoA"]["name"] == "routerview"
    assert repos["repoA"]["version"] == "0.109.0"
    assert repos["repoB"]["name"] == "editdb"
    assert repos["repoB"]["version"] == "0.115.0"


def test_dep_overlap_sorted_by_count_desc(test_app):
    """Packages sorted by count descending: 4-repo > 3-repo > 2-repo."""
    client, db_path = test_app

    # Create 4 repos
    for i in range(1, 5):
        _insert_repo(db_path, f"repo{i:03d}", f"repo{i}")

    # "alpha" in 4 repos
    for i in range(1, 5):
        _insert_dep(db_path, f"repo{i:03d}", "alpha", "pip", f"1.{i}.0")

    # "beta" in 3 repos
    for i in range(1, 4):
        _insert_dep(db_path, f"repo{i:03d}", "beta", "pip", f"2.{i}.0")

    # "gamma" in 2 repos
    for i in range(1, 3):
        _insert_dep(db_path, f"repo{i:03d}", "gamma", "pip", f"3.{i}.0")

    resp = client.get("/api/analytics/dep-overlap")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["packages"]) == 3
    counts = [p["count"] for p in body["packages"]]
    assert counts == sorted(counts, reverse=True)
    assert body["packages"][0]["name"] == "alpha"
    assert body["packages"][0]["count"] == 4
    assert body["packages"][1]["name"] == "beta"
    assert body["packages"][1]["count"] == 3
    assert body["packages"][2]["name"] == "gamma"
    assert body["packages"][2]["count"] == 2


def test_dep_overlap_same_package_different_managers(test_app):
    """lodash under npm and pip for different repos → two separate entries."""
    client, db_path = test_app
    _insert_repo(db_path, "repoA", "frontend")
    _insert_repo(db_path, "repoB", "backend")
    _insert_repo(db_path, "repoC", "scripts")

    # lodash/npm in repoA and repoB
    _insert_dep(db_path, "repoA", "lodash", "npm", "4.17.21")
    _insert_dep(db_path, "repoB", "lodash", "npm", "4.17.21")

    # lodash/pip in repoB and repoC
    _insert_dep(db_path, "repoB", "lodash", "pip", "0.1.0")
    _insert_dep(db_path, "repoC", "lodash", "pip", "0.2.0")

    resp = client.get("/api/analytics/dep-overlap")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["packages"]) == 2
    entries = {(p["name"], p["manager"]): p for p in body["packages"]}
    assert ("lodash", "npm") in entries
    assert ("lodash", "pip") in entries


def test_dep_overlap_version_spread_single_version(test_app):
    """express 4.18.0 in 3 repos → version_spread is '4.18.0 - 4.18.0'."""
    client, db_path = test_app
    for i in range(1, 4):
        _insert_repo(db_path, f"repo{i:03d}", f"app{i}")
        _insert_dep(db_path, f"repo{i:03d}", "express", "npm", "4.18.0")

    resp = client.get("/api/analytics/dep-overlap")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["packages"]) == 1
    assert body["packages"][0]["version_spread"] == "4.18.0 - 4.18.0"


def test_dep_overlap_null_versions(test_app):
    """NULL current_version: repo still appears in repos array but is excluded from spread."""
    client, db_path = test_app
    _insert_repo(db_path, "repoA", "alpha")
    _insert_repo(db_path, "repoB", "beta")
    _insert_repo(db_path, "repoC", "gamma")

    _insert_dep(db_path, "repoA", "requests", "pip", "2.31.0")
    _insert_dep(db_path, "repoB", "requests", "pip", None)   # NULL version
    _insert_dep(db_path, "repoC", "requests", "pip", "2.28.0")

    resp = client.get("/api/analytics/dep-overlap")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["packages"]) == 1
    pkg = body["packages"][0]
    assert pkg["count"] == 3

    # NULL version repo is still in repos array
    repo_ids = [r["repo_id"] for r in pkg["repos"]]
    assert "repoB" in repo_ids
    null_repo = next(r for r in pkg["repos"] if r["repo_id"] == "repoB")
    assert null_repo["version"] is None

    # version_spread excludes NULLs: min=2.28.0, max=2.31.0
    assert pkg["version_spread"] == "2.28.0 - 2.31.0"


def test_dep_overlap_null_versions_all_null(test_app):
    """All current_versions NULL → version_spread is empty string."""
    client, db_path = test_app
    _insert_repo(db_path, "repoA", "alpha")
    _insert_repo(db_path, "repoB", "beta")

    _insert_dep(db_path, "repoA", "wheel", "pip", None)
    _insert_dep(db_path, "repoB", "wheel", "pip", None)

    resp = client.get("/api/analytics/dep-overlap")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["packages"]) == 1
    assert body["packages"][0]["version_spread"] == ""


def test_dep_overlap_response_shape(test_app):
    """Each package entry has correct key types; each repo entry has correct key types."""
    client, db_path = test_app
    _insert_repo(db_path, "repoA", "alpha")
    _insert_repo(db_path, "repoB", "beta")
    _insert_dep(db_path, "repoA", "numpy", "pip", "1.26.0")
    _insert_dep(db_path, "repoB", "numpy", "pip", "1.25.0")

    resp = client.get("/api/analytics/dep-overlap")
    assert resp.status_code == 200
    body = resp.json()

    assert "packages" in body
    assert isinstance(body["packages"], list)
    assert len(body["packages"]) == 1

    pkg = body["packages"][0]
    assert isinstance(pkg["name"], str)
    assert isinstance(pkg["manager"], str)
    assert isinstance(pkg["repos"], list)
    assert isinstance(pkg["version_spread"], str)
    assert isinstance(pkg["count"], int)

    for repo_entry in pkg["repos"]:
        assert isinstance(repo_entry["repo_id"], str)
        assert isinstance(repo_entry["name"], str)
        # version is string or None
        assert repo_entry["version"] is None or isinstance(repo_entry["version"], str)


def test_dep_overlap_component_exists(test_app):
    """GET / → HTML contains 'function DepOverlap'."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    assert "function DepOverlap" in resp.text


def test_dep_overlap_table_uses_global_styles(test_app):
    """GET / → HTML contains 'data-table' class reference in DepOverlap component."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    assert "data-table" in resp.text


def test_dep_overlap_expand_pattern(test_app):
    """GET / → HTML contains expand/collapse state logic in DepOverlap component."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    # Must have some expand/collapse state variable
    assert "expanded" in html or "toggle" in html
