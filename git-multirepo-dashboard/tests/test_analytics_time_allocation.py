"""
Packet 19 — Analytics: Time Allocation: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_analytics_time_allocation.py -v
"""

import sqlite3
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


def _insert_repo(db_path, repo_id="repo001", name="myrepo", path="/tmp/myrepo"):
    """Insert a minimal repo row."""
    from datetime import datetime, timezone
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


def _insert_daily_stats(db_path, repo_id, date_str, commits):
    """Insert a daily_stats row."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT OR REPLACE INTO daily_stats (repo_id, date, commits, insertions, deletions, files_changed) "
            "VALUES (?, ?, ?, 0, 0, 0)",
            (repo_id, date_str, commits),
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_allocation_empty_db(test_app):
    """No daily_stats rows → 200, {"series": []}."""
    client, _ = test_app
    resp = client.get("/api/analytics/allocation")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"series": []}


def test_allocation_single_repo(test_app):
    """Single repo with 3 dates → 1 series entry with correct shape."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001", "myrepo", "/tmp/myrepo")

    today = date.today()
    dates = [
        (today - timedelta(days=2)).isoformat(),
        (today - timedelta(days=1)).isoformat(),
        today.isoformat(),
    ]
    for d in dates:
        _insert_daily_stats(db_path, "repo001", d, 3)

    resp = client.get("/api/analytics/allocation")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["series"]) == 1

    series = body["series"][0]
    assert series["repo_id"] == "repo001"
    assert series["name"] == "myrepo"
    assert len(series["data"]) == 3

    for entry in series["data"]:
        assert "date" in entry
        assert "commits" in entry


def test_allocation_multiple_repos(test_app):
    """Two repos on overlapping dates → 2 series entries with correct repo data."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001", "alpha", "/tmp/alpha")
    _insert_repo(db_path, "repo002", "beta", "/tmp/beta")

    today = date.today()
    d1 = (today - timedelta(days=2)).isoformat()
    d2 = (today - timedelta(days=1)).isoformat()

    _insert_daily_stats(db_path, "repo001", d1, 5)
    _insert_daily_stats(db_path, "repo001", d2, 2)
    _insert_daily_stats(db_path, "repo002", d1, 7)

    resp = client.get("/api/analytics/allocation")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["series"]) == 2

    by_id = {s["repo_id"]: s for s in body["series"]}
    assert "repo001" in by_id
    assert "repo002" in by_id

    assert by_id["repo001"]["name"] == "alpha"
    assert len(by_id["repo001"]["data"]) == 2

    assert by_id["repo002"]["name"] == "beta"
    assert len(by_id["repo002"]["data"]) == 1

    # Verify commit counts
    alpha_dates = {e["date"]: e["commits"] for e in by_id["repo001"]["data"]}
    assert alpha_dates[d1] == 5
    assert alpha_dates[d2] == 2

    beta_dates = {e["date"]: e["commits"] for e in by_id["repo002"]["data"]}
    assert beta_dates[d1] == 7


def test_allocation_excludes_inactive_repos(test_app):
    """Repo with no daily_stats in the window does not appear in series."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001", "active", "/tmp/active")
    _insert_repo(db_path, "repo002", "inactive", "/tmp/inactive")

    today = date.today()
    _insert_daily_stats(db_path, "repo001", (today - timedelta(days=1)).isoformat(), 4)
    # repo002 has no stats

    resp = client.get("/api/analytics/allocation?days=30")
    assert resp.status_code == 200
    body = resp.json()

    repo_ids = [s["repo_id"] for s in body["series"]]
    assert "repo001" in repo_ids
    assert "repo002" not in repo_ids


def test_allocation_days_filter(test_app):
    """days parameter filters: only data within the window is returned."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001", "myrepo", "/tmp/myrepo")

    today = date.today()
    near_date = (today - timedelta(days=15)).isoformat()
    far_date = (today - timedelta(days=100)).isoformat()

    _insert_daily_stats(db_path, "repo001", near_date, 3)
    _insert_daily_stats(db_path, "repo001", far_date, 7)

    # With days=30: only near_date should appear
    resp_30 = client.get("/api/analytics/allocation?days=30")
    assert resp_30.status_code == 200
    body_30 = resp_30.json()
    assert len(body_30["series"]) == 1
    dates_30 = [e["date"] for e in body_30["series"][0]["data"]]
    assert near_date in dates_30
    assert far_date not in dates_30

    # With days=200: both should appear
    resp_200 = client.get("/api/analytics/allocation?days=200")
    assert resp_200.status_code == 200
    body_200 = resp_200.json()
    assert len(body_200["series"]) == 1
    dates_200 = [e["date"] for e in body_200["series"][0]["data"]]
    assert near_date in dates_200
    assert far_date in dates_200


def test_allocation_default_days(test_app):
    """No days param defaults to 90 days."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001", "myrepo", "/tmp/myrepo")

    today = date.today()
    within_90 = (today - timedelta(days=60)).isoformat()
    beyond_90 = (today - timedelta(days=120)).isoformat()

    _insert_daily_stats(db_path, "repo001", within_90, 5)
    _insert_daily_stats(db_path, "repo001", beyond_90, 9)

    resp = client.get("/api/analytics/allocation")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["series"]) == 1
    dates = [e["date"] for e in body["series"][0]["data"]]
    assert within_90 in dates
    assert beyond_90 not in dates


def test_allocation_response_shape(test_app):
    """Each series entry has repo_id (str), name (str), data (list).
    Each data entry has date (YYYY-MM-DD) and commits (int)."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001", "myrepo", "/tmp/myrepo")
    today = date.today()
    _insert_daily_stats(db_path, "repo001", (today - timedelta(days=1)).isoformat(), 2)

    resp = client.get("/api/analytics/allocation")
    assert resp.status_code == 200
    body = resp.json()
    assert "series" in body
    assert isinstance(body["series"], list)
    assert len(body["series"]) == 1

    series = body["series"][0]
    assert isinstance(series["repo_id"], str)
    assert isinstance(series["name"], str)
    assert isinstance(series["data"], list)

    for entry in series["data"]:
        assert set(entry.keys()) == {"date", "commits"}
        # date is YYYY-MM-DD
        parts = entry["date"].split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4
        assert isinstance(entry["commits"], int)


def test_allocation_data_sorted_by_date(test_app):
    """data array is sorted ascending by date regardless of insertion order."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001", "myrepo", "/tmp/myrepo")

    today = date.today()
    # Insert in reverse order
    for offset in [10, 2, 7, 1, 5]:
        _insert_daily_stats(db_path, "repo001", (today - timedelta(days=offset)).isoformat(), offset)

    resp = client.get("/api/analytics/allocation")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["series"]) == 1
    dates = [e["date"] for e in body["series"][0]["data"]]
    assert dates == sorted(dates)


def test_allocation_component_exists(test_app):
    """GET / → HTML contains 'function TimeAllocation'."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    assert "function TimeAllocation" in resp.text


def test_allocation_color_palette(test_app):
    """GET / → HTML contains at least the first 5 colors from the spec palette."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    for color in ["#4c8dff", "#34d399", "#fbbf24", "#f97316", "#ef4444"]:
        assert color in html


def test_allocation_uses_recharts_area_chart(test_app):
    """GET / → HTML contains AreaChart and stackOffset references in TimeAllocation."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "AreaChart" in html
    assert "stackOffset" in html


# ─────────────────────────────────────────────────────────────────────────────
# (23A gap 7) Negative/zero days parameter — allocation endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_allocation_days_zero_returns_empty(test_app):
    """GET /api/analytics/allocation?days=0 returns 200 with empty series, not a crash.

    days=0 → cutoff=today; no historical data matches → series must be [].
    """
    client, _ = test_app
    resp = client.get("/api/analytics/allocation?days=0")
    assert resp.status_code == 200
    data = resp.json()
    assert "series" in data
    assert isinstance(data["series"], list)
    assert data["series"] == []


def test_allocation_days_negative_returns_empty(test_app):
    """GET /api/analytics/allocation?days=-1 returns 200 with empty series.

    days=-1 → cutoff=tomorrow; no historical date can match → must not crash.
    """
    client, _ = test_app
    resp = client.get("/api/analytics/allocation?days=-1")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["series"], list)
    assert data["series"] == []
