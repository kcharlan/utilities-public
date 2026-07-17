"""
Packet 18 — Analytics: Heatmap: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_analytics_heatmap.py -v
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

def test_heatmap_empty_db(test_app):
    """No daily_stats rows → 200, {data: [], max_count: 0}."""
    client, _ = test_app
    resp = client.get("/api/analytics/heatmap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["max_count"] == 0


def test_heatmap_single_repo(test_app):
    """Single repo with 5 dates — response has correct entries and max_count."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001")

    today = date.today()
    dates_commits = [
        ((today - timedelta(days=5)).isoformat(), 2),
        ((today - timedelta(days=4)).isoformat(), 7),
        ((today - timedelta(days=3)).isoformat(), 1),
        ((today - timedelta(days=2)).isoformat(), 4),
        ((today - timedelta(days=1)).isoformat(), 9),
    ]
    for d, c in dates_commits:
        _insert_daily_stats(db_path, "repo001", d, c)

    resp = client.get("/api/analytics/heatmap")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 5
    assert body["max_count"] == 9


def test_heatmap_aggregates_across_repos(test_app):
    """Two repos on same date: counts summed. max_count reflects aggregated total."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001", "repoA", "/tmp/repoA")
    _insert_repo(db_path, "repo002", "repoB", "/tmp/repoB")

    target_date = (date.today() - timedelta(days=2)).isoformat()
    _insert_daily_stats(db_path, "repo001", target_date, 3)
    _insert_daily_stats(db_path, "repo002", target_date, 5)

    resp = client.get("/api/analytics/heatmap")
    assert resp.status_code == 200
    body = resp.json()
    matching = [e for e in body["data"] if e["date"] == target_date]
    assert len(matching) == 1
    assert matching[0]["count"] == 8
    assert body["max_count"] == 8


def test_heatmap_days_filter(test_app):
    """days parameter filters correctly: only entries within the window."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001")

    today = date.today()
    # Within 30 days
    near_date = (today - timedelta(days=15)).isoformat()
    # Beyond 30 days but within 365
    far_date = (today - timedelta(days=200)).isoformat()

    _insert_daily_stats(db_path, "repo001", near_date, 5)
    _insert_daily_stats(db_path, "repo001", far_date, 10)

    resp_30 = client.get("/api/analytics/heatmap?days=30")
    assert resp_30.status_code == 200
    body_30 = resp_30.json()
    dates_30 = [e["date"] for e in body_30["data"]]
    assert near_date in dates_30
    assert far_date not in dates_30

    resp_365 = client.get("/api/analytics/heatmap?days=365")
    assert resp_365.status_code == 200
    body_365 = resp_365.json()
    dates_365 = [e["date"] for e in body_365["data"]]
    assert near_date in dates_365
    assert far_date in dates_365


def test_heatmap_default_days(test_app):
    """No days param defaults to 365-day window."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001")

    today = date.today()
    within_365 = (today - timedelta(days=300)).isoformat()
    beyond_365 = (today - timedelta(days=400)).isoformat()

    _insert_daily_stats(db_path, "repo001", within_365, 3)
    _insert_daily_stats(db_path, "repo001", beyond_365, 7)

    resp = client.get("/api/analytics/heatmap")
    assert resp.status_code == 200
    body = resp.json()
    dates = [e["date"] for e in body["data"]]
    assert within_365 in dates
    assert beyond_365 not in dates


def test_heatmap_response_shape(test_app):
    """Each data entry has exactly 'date' (YYYY-MM-DD string) and 'count' (int)."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001")
    _insert_daily_stats(db_path, "repo001", (date.today() - timedelta(days=1)).isoformat(), 4)

    resp = client.get("/api/analytics/heatmap")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "max_count" in body
    assert isinstance(body["data"], list)
    assert isinstance(body["max_count"], int)

    for entry in body["data"]:
        assert set(entry.keys()) == {"date", "count"}
        # date is YYYY-MM-DD
        parts = entry["date"].split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4
        assert isinstance(entry["count"], int)


def test_heatmap_sorted_by_date(test_app):
    """Response data is sorted ascending by date regardless of insertion order."""
    client, db_path = test_app
    _insert_repo(db_path, "repo001")

    today = date.today()
    # Insert in reverse order
    for offset in [10, 2, 7, 1, 5]:
        _insert_daily_stats(db_path, "repo001", (today - timedelta(days=offset)).isoformat(), offset)

    resp = client.get("/api/analytics/heatmap")
    assert resp.status_code == 200
    body = resp.json()
    dates = [e["date"] for e in body["data"]]
    assert dates == sorted(dates)


def test_heatmap_component_exists(test_app):
    """GET / → HTML contains 'function Heatmap'."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    assert "function Heatmap" in resp.text


def test_heatmap_color_scale(test_app):
    """GET / → HTML contains 5 color scale values from the spec."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "var(--bg-secondary)" in html
    assert "rgba(76,141,255,0.2)" in html
    assert "rgba(76,141,255,0.4)" in html
    assert "rgba(76,141,255,0.65)" in html
    assert "rgba(76,141,255,0.9)" in html


def test_heatmap_tooltip_pattern(test_app):
    """GET / → HTML contains tooltip logic with date formatting and 'commits' text."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    # Tooltip should include date formatting and commit count label
    assert "commits" in html
    assert "toLocaleDateString" in html


def test_heatmap_root_attr(test_app):
    """data-heatmap-root attribute must exist on the container for tooltip positioning."""
    client, _ = test_app
    resp = client.get("/")
    assert resp.status_code == 200
    assert "data-heatmap-root" in resp.text


def test_heatmap_grid_dimensions(test_app):
    """Grid uses 52 columns × 7 rows of 12px cells (AC 9)."""
    client, _ = test_app
    resp = client.get("/")
    html = resp.text
    assert "repeat(52," in html
    assert "repeat(7," in html


def test_heatmap_hover_outline(test_app):
    """Hovered cell shows accent-blue outline (AC 14)."""
    client, _ = test_app
    resp = client.get("/")
    html = resp.text
    assert "2px solid var(--accent-blue)" in html


def test_heatmap_day_labels(test_app):
    """Mon, Wed, Fri day labels appear (AC 11)."""
    client, _ = test_app
    resp = client.get("/")
    html = resp.text
    for day in ["Mon", "Wed", "Fri"]:
        assert day in html


def test_heatmap_month_labels(test_app):
    """Month labels appear (AC 12) — at least Jan..Dec name array present."""
    client, _ = test_app
    resp = client.get("/")
    html = resp.text
    assert "'Jan'" in html
    assert "'Dec'" in html


# ─────────────────────────────────────────────────────────────────────────────
# (23A gap 7) Negative/zero days parameter — heatmap endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_heatmap_days_zero_returns_empty(test_app):
    """GET /api/analytics/heatmap?days=0 returns 200 with empty data, not a crash.

    days=0 sets cutoff=today, so only activity exactly today would appear.
    With an empty DB the response must be {"data": [], "max_count": 0}.
    """
    client, _ = test_app
    resp = client.get("/api/analytics/heatmap?days=0")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert "max_count" in data
    assert isinstance(data["data"], list)
    assert data["max_count"] == 0


def test_heatmap_days_negative_returns_empty(test_app):
    """GET /api/analytics/heatmap?days=-1 returns 200 with empty data.

    days=-1 sets cutoff=tomorrow, so no historical dates match.
    Must return gracefully with empty results, not crash.
    """
    client, _ = test_app
    resp = client.get("/api/analytics/heatmap?days=-1")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["data"], list)
    assert len(data["data"]) == 0
    assert data["max_count"] == 0
