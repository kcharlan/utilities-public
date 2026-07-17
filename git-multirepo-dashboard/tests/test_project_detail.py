"""
Packet 10 — Project Detail View & Activity Chart: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_project_detail.py -v
"""

import asyncio
import sys
from datetime import date, timedelta
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


def _insert_repo(db_path, repo_id="testrepo001", name="myrepo",
                 path="/tmp/myrepo", runtime="python", default_branch="main"):
    """Insert a repo and a working_state row synchronously."""
    import sqlite3
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT OR IGNORE INTO repositories (id, name, path, runtime, default_branch, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (repo_id, name, path, runtime, default_branch, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO working_state "
            "(repo_id, has_uncommitted, modified_count, untracked_count, staged_count, "
            " current_branch, last_commit_hash, last_commit_message, last_commit_date, checked_at) "
            "VALUES (?, 0, 0, 0, 0, ?, NULL, NULL, NULL, ?)",
            (repo_id, default_branch, now),
        )
        conn.commit()


def _insert_daily_stats(db_path, repo_id, rows):
    """Insert daily_stats rows: rows = list of (date_str, commits, insertions, deletions, files_changed)."""
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executemany(
            "INSERT OR REPLACE INTO daily_stats "
            "(repo_id, date, commits, insertions, deletions, files_changed) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(repo_id, *row) for row in rows],
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET /api/repos/{id} — success
# ─────────────────────────────────────────────────────────────────────────────

def test_get_repo_detail_success(test_app):
    """GET /api/repos/{id} returns 200 with all expected fields."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="abc123", name="testrepo",
                 path="/tmp/testrepo", runtime="python", default_branch="main")

    resp = client.get("/api/repos/abc123")
    assert resp.status_code == 200

    data = resp.json()
    assert data["id"] == "abc123"
    assert data["name"] == "testrepo"
    assert data["path"] == "/tmp/testrepo"
    assert data["runtime"] == "python"
    assert data["default_branch"] == "main"
    assert "last_full_scan_at" in data
    assert "working_state" in data
    ws = data["working_state"]
    assert ws is not None
    # working_state must expose the expected keys
    for key in ("repo_id", "has_uncommitted", "modified_count", "untracked_count",
                "staged_count", "current_branch", "checked_at"):
        assert key in ws, f"working_state missing key: {key}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET /api/repos/{id} — 404 for non-existent repo
# ─────────────────────────────────────────────────────────────────────────────

def test_get_repo_detail_404(test_app):
    """GET /api/repos/nonexistent_id returns 404."""
    client, _ = test_app
    resp = client.get("/api/repos/nonexistent_id_xyz")
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 3. GET /api/repos/{id}/history — with data
# ─────────────────────────────────────────────────────────────────────────────

def test_get_repo_history_with_data(test_app):
    """GET /api/repos/{id}/history?days=30 returns correct shape with matching rows."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo001")

    today = date.today()
    rows = [
        ((today - timedelta(days=i)).isoformat(), 2, 50, 10, 3)
        for i in range(30)
    ]
    _insert_daily_stats(db_path, "repo001", rows)

    resp = client.get("/api/repos/repo001/history?days=30")
    assert resp.status_code == 200

    data = resp.json()
    assert data["repo_id"] == "repo001"
    assert data["days"] == 30
    assert isinstance(data["data"], list)
    assert len(data["data"]) == 30

    # Each entry must have the required fields
    for entry in data["data"]:
        for field in ("date", "commits", "insertions", "deletions", "files_changed"):
            assert field in entry, f"history entry missing field: {field}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. GET /api/repos/{id}/history — default days=90
# ─────────────────────────────────────────────────────────────────────────────

def test_get_repo_history_default_days(test_app):
    """GET /api/repos/{id}/history with no days param defaults to 90."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo002")

    resp = client.get("/api/repos/repo002/history")
    assert resp.status_code == 200
    assert resp.json()["days"] == 90


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET /api/repos/{id}/history — empty data
# ─────────────────────────────────────────────────────────────────────────────

def test_get_repo_history_empty(test_app):
    """Repo with no daily_stats returns data: []."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo003")

    resp = client.get("/api/repos/repo003/history?days=90")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. GET /api/repos/{id}/history — 404 for non-existent repo
# ─────────────────────────────────────────────────────────────────────────────

def test_get_repo_history_404(test_app):
    """History endpoint for non-existent repo returns 404."""
    client, _ = test_app
    resp = client.get("/api/repos/does_not_exist/history")
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 7. GET /api/repos/{id}/history — excludes old data
# ─────────────────────────────────────────────────────────────────────────────

def test_history_excludes_old_data(test_app):
    """Rows outside the requested window (120 days ago with days=90) are excluded."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo004")

    today = date.today()
    recent = (today - timedelta(days=5)).isoformat()
    old = (today - timedelta(days=120)).isoformat()

    _insert_daily_stats(db_path, "repo004", [
        (recent, 3, 100, 20, 5),
        (old, 10, 500, 100, 20),
    ])

    resp = client.get("/api/repos/repo004/history?days=90")
    assert resp.status_code == 200
    data = resp.json()["data"]

    dates = [d["date"] for d in data]
    assert recent in dates
    assert old not in dates


# ─────────────────────────────────────────────────────────────────────────────
# 8. HTML_TEMPLATE contains ProjectDetail component
# ─────────────────────────────────────────────────────────────────────────────

def test_project_detail_component_exists():
    """HTML_TEMPLATE contains ProjectDetail component definition."""
    assert "ProjectDetail" in git_dashboard.HTML_TEMPLATE


# ─────────────────────────────────────────────────────────────────────────────
# 9. HTML_TEMPLATE contains ActivityChart component
# ─────────────────────────────────────────────────────────────────────────────

def test_activity_chart_component_exists():
    """HTML_TEMPLATE contains ActivityChart component definition."""
    assert "ActivityChart" in git_dashboard.HTML_TEMPLATE


# ─────────────────────────────────────────────────────────────────────────────
# 10. HTML_TEMPLATE contains TimeRangeSelector with expected options
# ─────────────────────────────────────────────────────────────────────────────

def test_time_range_selector_exists():
    """HTML_TEMPLATE contains TimeRangeSelector with 30, 90, 180, 365 day options."""
    tmpl = git_dashboard.HTML_TEMPLATE
    assert "TimeRangeSelector" in tmpl
    # All five time range values must appear
    for value in ("30", "90", "180", "365"):
        assert value in tmpl, f"TimeRangeSelector missing days value: {value}"


# ─────────────────────────────────────────────────────────────────────────────
# 11. HTML_TEMPLATE contains sub-tab labels
# ─────────────────────────────────────────────────────────────────────────────

def test_detail_sub_tabs_exist():
    """HTML_TEMPLATE contains the four sub-tab labels: Activity, Commits, Branches, Dependencies."""
    tmpl = git_dashboard.HTML_TEMPLATE
    for label in ("Activity", "Commits", "Branches", "Dependencies"):
        assert label in tmpl, f"Sub-tab label missing: {label}"


# ─────────────────────────────────────────────────────────────────────────────
# 12. Routing maps #/repo/ prefix to ProjectDetail
# ─────────────────────────────────────────────────────────────────────────────

def test_detail_route_renders_component():
    """HTML_TEMPLATE routing logic maps the repo tab to ProjectDetail."""
    tmpl = git_dashboard.HTML_TEMPLATE
    # ContentArea must render ProjectDetail when tab === 'repo'
    assert "ProjectDetail" in tmpl
    # The routing block must reference repoId and ProjectDetail together
    assert "repoId" in tmpl


# ─────────────────────────────────────────────────────────────────────────────
# 13. HTML_TEMPLATE contains global table CSS
# ─────────────────────────────────────────────────────────────────────────────

def test_global_table_styles():
    """HTML_TEMPLATE CSS contains global table styling classes."""
    tmpl = git_dashboard.HTML_TEMPLATE
    for cls in (".table-container", ".table-header", ".table-row", ".table-empty"):
        assert cls in tmpl, f"Missing global table CSS class: {cls}"


# ─────────────────────────────────────────────────────────────────────────────
# (23A gap 7) Negative/zero days parameter — repo history endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_repo_history_days_zero_returns_empty(test_app, tmp_path):
    """GET /api/repos/{id}/history?days=0 returns 200 with empty data list.

    days=0 → cutoff=today; unless there is activity today the data must be [].
    Must not crash or return 500.
    """
    client, db_path = test_app
    _insert_repo(db_path, repo_id="hist001", path="/tmp/hist_repo_zero")

    resp = client.get("/api/repos/hist001/history?days=0")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert isinstance(data["data"], list)
    # days value echoed back must equal what was requested
    assert data["days"] == 0


def test_repo_history_days_negative_returns_empty(test_app, tmp_path):
    """GET /api/repos/{id}/history?days=-1 returns 200 with empty data list.

    days=-1 → cutoff=tomorrow; no historical date can match → data must be [].
    Must not crash.
    """
    client, db_path = test_app
    _insert_repo(db_path, repo_id="hist002", path="/tmp/hist_repo_neg")

    resp = client.get("/api/repos/hist002/history?days=-1")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["data"], list)
    assert len(data["data"]) == 0
    assert data["days"] == -1
