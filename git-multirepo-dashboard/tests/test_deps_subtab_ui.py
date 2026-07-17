"""
Packet 17 — Dependencies Sub-tab UI: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_deps_subtab_ui.py -v
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


def _insert_repo(db_path, repo_id="testrepo001", name="myrepo",
                 path="/tmp/myrepo", runtime="python", default_branch="main"):
    """Insert a repo row."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT OR IGNORE INTO repositories (id, name, path, runtime, default_branch, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (repo_id, name, path, runtime, default_branch, now),
        )
        conn.commit()


def _insert_dep(db_path, repo_id, manager, name, current_version, wanted_version,
                latest_version, severity, advisory_id=None,
                checked_at="2026-03-10T07:55:00"):
    """Insert a dependency row."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT OR REPLACE INTO dependencies "
            "(repo_id, manager, name, current_version, wanted_version, latest_version, "
            " severity, advisory_id, checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (repo_id, manager, name, current_version, wanted_version,
             latest_version, severity, advisory_id, checked_at),
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 1. GET /api/repos/{id}/deps — empty repo
# ─────────────────────────────────────────────────────────────────────────────

def test_get_deps_empty_repo(test_app):
    """Repo with no dependencies returns empty list []."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo001")

    resp = client.get("/api/repos/repo001/deps")
    assert resp.status_code == 200
    assert resp.json() == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET /api/repos/{id}/deps — single manager, sorted correctly
# ─────────────────────────────────────────────────────────────────────────────

def test_get_deps_single_manager(test_app):
    """Single manager group; packages sorted vulnerable → outdated → ok."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo002")
    _insert_dep(db_path, "repo002", "pip", "requests", "2.31.0", "2.31.0", "2.32.3",
                "vulnerable", "CVE-2024-35195")
    _insert_dep(db_path, "repo002", "pip", "flask", "2.0.0", "2.0.0", "3.0.0", "outdated")
    _insert_dep(db_path, "repo002", "pip", "click", "8.1.0", "8.1.0", "8.1.0", "ok")

    resp = client.get("/api/repos/repo002/deps")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["manager"] == "pip"
    pkgs = data[0]["packages"]
    assert len(pkgs) == 3
    assert pkgs[0]["severity"] == "vulnerable"
    assert pkgs[1]["severity"] == "outdated"
    assert pkgs[2]["severity"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# 3. GET /api/repos/{id}/deps — multiple managers
# ─────────────────────────────────────────────────────────────────────────────

def test_get_deps_multiple_managers(test_app):
    """Deps for pip and npm appear as separate manager groups."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo003")
    _insert_dep(db_path, "repo003", "pip", "requests", "2.31.0", "2.31.0", "2.32.3", "outdated")
    _insert_dep(db_path, "repo003", "npm", "lodash", "4.17.20", "4.17.20", "4.17.21", "outdated")

    resp = client.get("/api/repos/repo003/deps")
    assert resp.status_code == 200
    data = resp.json()
    managers = {g["manager"] for g in data}
    assert "pip" in managers
    assert "npm" in managers
    assert len(data) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 4. GET /api/repos/{id}/deps — all 4 severities sorted correctly
# ─────────────────────────────────────────────────────────────────────────────

def test_get_deps_sort_order(test_app):
    """Packages sorted: vulnerable → major → outdated → ok, then alphabetically."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo004")
    _insert_dep(db_path, "repo004", "pip", "z-ok", "1.0.0", "1.0.0", "1.0.0", "ok")
    _insert_dep(db_path, "repo004", "pip", "a-major", "1.0.0", "1.0.0", "2.0.0", "major")
    _insert_dep(db_path, "repo004", "pip", "b-outdated", "1.0.0", "1.0.0", "1.1.0", "outdated")
    _insert_dep(db_path, "repo004", "pip", "c-vuln", "1.0.0", "1.0.0", "1.1.0",
                "vulnerable", "CVE-2024-00001")

    resp = client.get("/api/repos/repo004/deps")
    assert resp.status_code == 200
    pkgs = resp.json()[0]["packages"]
    assert len(pkgs) == 4
    severities = [p["severity"] for p in pkgs]
    assert severities == ["vulnerable", "major", "outdated", "ok"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET /api/repos/{id}/deps — 404 for nonexistent repo
# ─────────────────────────────────────────────────────────────────────────────

def test_get_deps_404(test_app):
    """/api/repos/nonexistent/deps returns 404."""
    client, _ = test_app
    resp = client.get("/api/repos/nonexistent_repo_xyz/deps")
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 6. GET /api/repos/{id}/deps — response shape
# ─────────────────────────────────────────────────────────────────────────────

def test_get_deps_response_shape(test_app):
    """Each package object and manager group has all required fields."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo005")
    _insert_dep(db_path, "repo005", "pip", "fastapi", "0.109.0", "0.109.0", "0.115.0", "major")

    resp = client.get("/api/repos/repo005/deps")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    group = data[0]
    for key in ("manager", "packages", "checked_at"):
        assert key in group, f"Manager group missing key: {key}"
    pkg = group["packages"][0]
    for key in ("name", "current_version", "wanted_version", "latest_version",
                "severity", "advisory_id"):
        assert key in pkg, f"Package missing key: {key}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. POST /api/repos/{id}/scan/deps — check now endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_check_now_endpoint(test_app):
    """POST scan/deps calls run_dep_scan_for_repo and returns updated deps."""
    client, db_path = test_app
    _insert_repo(db_path, repo_id="repo006", path="/tmp/repo006")

    async def fake_dep_scan(db, repo_id, repo_path):
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO dependencies "
                "(repo_id, manager, name, current_version, wanted_version, latest_version, "
                " severity, advisory_id, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("repo006", "pip", "testpkg", "1.0.0", "1.0.0", "1.1.0",
                 "outdated", None, "2026-03-10T08:00:00"),
            )
            conn.commit()

    mock_scan = AsyncMock(side_effect=fake_dep_scan)
    with patch("git_dashboard.run_dep_scan_for_repo", mock_scan):
        resp = client.post("/api/repos/repo006/scan/deps")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert mock_scan.call_count == 1
    # Verify called with the correct repo_id (second positional arg)
    assert mock_scan.call_args[0][1] == "repo006"
    # Response contains the dep inserted during fake scan
    managers = {g["manager"] for g in data}
    assert "pip" in managers


# ─────────────────────────────────────────────────────────────────────────────
# 8. POST /api/repos/{id}/scan/deps — 404 for nonexistent repo
# ─────────────────────────────────────────────────────────────────────────────

def test_check_now_404(test_app):
    """POST scan/deps for nonexistent repo returns 404."""
    client, _ = test_app
    resp = client.post("/api/repos/nonexistent_repo_xyz/scan/deps")
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 9. HTML_TEMPLATE contains DepsTab component
# ─────────────────────────────────────────────────────────────────────────────

def test_deps_tab_component_exists():
    """HTML_TEMPLATE contains DepsTab component definition."""
    assert "function DepsTab" in git_dashboard.HTML_TEMPLATE


# ─────────────────────────────────────────────────────────────────────────────
# 10. DepsTab replaces PlaceholderTab for deps sub-tab
# ─────────────────────────────────────────────────────────────────────────────

def test_deps_tab_replaces_placeholder():
    """The deps sub-tab renders DepsTab, not PlaceholderTab."""
    tmpl = git_dashboard.HTML_TEMPLATE
    # DepsTab must be rendered for the deps sub-tab
    assert "activeSubTab === 'deps'" in tmpl
    assert "DepsTab" in tmpl
    # The line routing deps must use DepsTab, not PlaceholderTab
    deps_lines = [ln for ln in tmpl.split('\n') if "activeSubTab === 'deps'" in ln]
    assert len(deps_lines) >= 1
    assert "DepsTab" in deps_lines[0]
    assert "PlaceholderTab" not in deps_lines[0]


# ─────────────────────────────────────────────────────────────────────────────
# 11. HTML_TEMPLATE has correct severity → display text mapping
# ─────────────────────────────────────────────────────────────────────────────

def test_severity_status_text_mapping():
    """HTML_TEMPLATE contains all 4 severity display strings."""
    tmpl = git_dashboard.HTML_TEMPLATE
    assert "up to date" in tmpl
    assert "outdated" in tmpl
    assert "major update" in tmpl
    # Vulnerable shows advisory_id value — template must reference advisory_id for display
    assert "advisory_id" in tmpl
