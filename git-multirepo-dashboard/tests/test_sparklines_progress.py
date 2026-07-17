"""Packet 09 — Sparklines & Scan Progress UI: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_sparklines_progress.py -v
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import guard ───────────────────────────────────────────────────────────────
try:
    import aiosqlite  # noqa: F401
    import fastapi    # noqa: F401
except ImportError:
    pytest.skip(
        "aiosqlite/fastapi not installed — run tests inside the test venv: "
        ".venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


async def _make_db():
    """Open an in-memory aiosqlite DB and apply the project schema."""
    db = await aiosqlite.connect(":memory:")
    await db.execute("PRAGMA foreign_keys = ON")
    await db.executescript(git_dashboard._SCHEMA_SQL)
    return db


async def _register_repo(db, repo_id: str, name: str = "test-repo"):
    """Insert a minimal repositories row."""
    await db.execute(
        "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
        (repo_id, name, f"/tmp/{name}", "2026-01-01T00:00:00+00:00"),
    )
    await db.commit()


async def _insert_daily_stat(db, repo_id: str, date_str: str, commits: int):
    """Insert a single daily_stats row."""
    await db.execute(
        "INSERT OR REPLACE INTO daily_stats (repo_id, date, commits) VALUES (?, ?, ?)",
        (repo_id, date_str, commits),
    )
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 1. compute_sparklines — empty table
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_sparklines_empty():
    """No daily_stats rows → returns empty dict (no repo keys)."""
    async def _run():
        db = await _make_db()
        result = await git_dashboard.compute_sparklines(db)
        await db.close()
        return result

    result = run(_run())
    assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# 2. compute_sparklines — single repo, 3 data points
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_sparklines_single_repo():
    """Single repo with data in 3 distinct weeks → 13-element list with correct sums."""
    async def _run():
        db = await _make_db()
        repo_id = "aabbccdd11223344"
        await _register_repo(db, repo_id, "myrepo")

        today = date.today()
        # start = today - timedelta(days=90), so:
        # week 0 covers days [start, start+6] → day offset ~0-6 from start
        # week 12 covers days [start+84, start+90] → today is in this range
        w0_date = (today - timedelta(days=88)).isoformat()   # near start of window → week 0
        w6_date = (today - timedelta(days=46)).isoformat()   # mid window → week ~6
        w12_date = today.isoformat()                          # today → week 12

        await _insert_daily_stat(db, repo_id, w0_date, 3)
        await _insert_daily_stat(db, repo_id, w6_date, 7)
        await _insert_daily_stat(db, repo_id, w12_date, 5)

        result = await git_dashboard.compute_sparklines(db)
        await db.close()
        return result

    result = run(_run())
    assert "aabbccdd11223344" in result
    arr = result["aabbccdd11223344"]
    assert len(arr) == 13
    assert all(isinstance(v, int) for v in arr)
    assert sum(arr) == 15  # 3 + 7 + 5


# ─────────────────────────────────────────────────────────────────────────────
# 3. compute_sparklines — multiple repos stay independent
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_sparklines_multiple_repos():
    """Two repos each get their own 13-element array with independent counts."""
    async def _run():
        db = await _make_db()
        repo_a = "aaaa111122223333"
        repo_b = "bbbb444455556666"
        await _register_repo(db, repo_a, "repo-a")
        await _register_repo(db, repo_b, "repo-b")

        today = date.today()
        d = today.isoformat()
        await _insert_daily_stat(db, repo_a, d, 10)
        await _insert_daily_stat(db, repo_b, d, 20)

        result = await git_dashboard.compute_sparklines(db)
        await db.close()
        return result

    result = run(_run())
    assert "aaaa111122223333" in result
    assert "bbbb444455556666" in result
    arr_a = result["aaaa111122223333"]
    arr_b = result["bbbb444455556666"]
    assert len(arr_a) == 13
    assert len(arr_b) == 13
    assert sum(arr_a) == 10
    assert sum(arr_b) == 20


# ─────────────────────────────────────────────────────────────────────────────
# 4. compute_sparklines — data older than 91 days excluded
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_sparklines_old_data_excluded():
    """daily_stats rows older than 91 days must not appear in sparklines."""
    async def _run():
        db = await _make_db()
        repo_id = "cccc777788889999"
        await _register_repo(db, repo_id, "old-repo")

        today = date.today()
        old_date = (today - timedelta(days=100)).isoformat()  # 100 days ago > 91-day window
        await _insert_daily_stat(db, repo_id, old_date, 50)

        result = await git_dashboard.compute_sparklines(db)
        await db.close()
        return result

    result = run(_run())
    # Old data excluded → repo either absent from dict or all zeros
    if "cccc777788889999" in result:
        assert sum(result["cccc777788889999"]) == 0, (
            "Data older than 91 days should not appear in sparklines"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Fleet endpoint — sparkline field is a 13-element list (not empty [])
# ─────────────────────────────────────────────────────────────────────────────

def test_fleet_endpoint_sparkline_populated(tmp_path):
    """GET /api/fleet returns sparkline as a list of 13 integers when daily_stats exist."""
    import subprocess
    import aiosqlite

    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    # Make a real git repo so quick_scan_repo doesn't fail
    repo_dir = tmp_path / "spark-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "synthetic-user@example.invalid"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "T"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "--allow-empty", "-m", "init"],
                   check=True, capture_output=True)

    # Register repo and insert daily_stats
    today = date.today()

    async def _setup():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            repo = await git_dashboard.register_repo(db, {
                "path": str(repo_dir.resolve()),
                "name": "spark-repo",
                "default_branch": "main",
                "runtime": "unknown",
            })
            repo_id = repo["id"]
            await db.execute(
                "INSERT OR REPLACE INTO daily_stats (repo_id, date, commits) VALUES (?, ?, ?)",
                (repo_id, today.isoformat(), 7),
            )
            await db.commit()
            return repo_id

    repo_id = run(_setup())

    # Call the fleet endpoint through the shared ASGI transport.
    from tools.testkit import ASGISyncClient

    async def override_get_db():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            yield db

    git_dashboard.app.dependency_overrides[git_dashboard.get_db] = override_get_db
    try:
        with ASGISyncClient(git_dashboard.app) as client:
            resp = client.get("/api/fleet")
            assert resp.status_code == 200
            data = resp.json()
            repos = data["repos"]
            assert len(repos) >= 1
            for r in repos:
                sparkline = r.get("sparkline")
                assert isinstance(sparkline, list), "sparkline must be a list"
                assert len(sparkline) == 13, f"sparkline must have 13 elements, got {len(sparkline)}"
                assert all(isinstance(v, int) for v in sparkline), "sparkline elements must be ints"
            # Our repo specifically should have a non-zero sparkline
            our_repo = next((r for r in repos if r["id"] == repo_id), None)
            assert our_repo is not None
            assert sum(our_repo["sparkline"]) == 7
    finally:
        git_dashboard.app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 6–10. Frontend / template presence tests
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_progress_bar_component_exists():
    """HTML_TEMPLATE contains a ScanProgressBar component."""
    assert "ScanProgressBar" in git_dashboard.HTML_TEMPLATE, (
        "ScanProgressBar component not found in HTML_TEMPLATE"
    )


def test_scan_toast_component_exists():
    """HTML_TEMPLATE contains a ScanToast component."""
    assert "ScanToast" in git_dashboard.HTML_TEMPLATE, (
        "ScanToast component not found in HTML_TEMPLATE"
    )


def test_full_scan_button_wired():
    """Full Scan button's onClick references a real scan-triggering function, not a no-op."""
    template = git_dashboard.HTML_TEMPLATE
    # The handler function must be defined
    assert "handleFullScan" in template, "handleFullScan function not found in HTML_TEMPLATE"
    # The region immediately before "Full Scan" button text must reference the handler
    idx = template.find("Full Scan")
    assert idx > 0, "Full Scan text not found in HTML_TEMPLATE"
    region = template[max(0, idx - 800):idx]
    # The button must use the onFullScan prop (not handleFullScan from outer scope)
    assert "onFullScan" in region, (
        "Full Scan button onClick not wired to onFullScan prop"
    )


def test_full_scan_button_uses_prop_not_closure():
    """Regression: Header must call onFullScan prop, not handleFullScan from App scope.

    handleFullScan is defined inside App(), so Header cannot access it via closure.
    The button must use the onFullScan prop that App passes to Header.
    Fixed in drift_audit_after_packet_09.
    """
    template = git_dashboard.HTML_TEMPLATE
    # Find the Header component body (between its declaration and the next top-level function)
    header_start = template.find("function Header(")
    assert header_start > 0, "Header component not found"
    # Find the Full Scan button region within Header
    full_scan_idx = template.find("Full Scan", header_start)
    assert full_scan_idx > 0, "Full Scan text not found after Header definition"
    # Look at the onClick in the 800 chars before "Full Scan" (style block is large)
    region = template[max(header_start, full_scan_idx - 800):full_scan_idx]
    assert "onClick={onFullScan}" in region, (
        "Header's Full Scan button must use onClick={onFullScan} (the prop), "
        "not onClick={handleFullScan} (which is out of scope)"
    )


def test_scan_progress_uses_sse_endpoint():
    """HTML_TEMPLATE references EventSource and the SSE progress endpoint path."""
    template = git_dashboard.HTML_TEMPLATE
    assert "EventSource" in template, "EventSource not found in HTML_TEMPLATE"
    assert "/api/fleet/scan/" in template, (
        "SSE endpoint path (/api/fleet/scan/) not found in HTML_TEMPLATE"
    )


def test_fleet_refetch_on_completion():
    """HTML_TEMPLATE contains a refetch mechanism triggered on scan completion."""
    template = git_dashboard.HTML_TEMPLATE
    # refetchKey pattern: App holds a counter; FleetOverview re-fetches when it changes
    assert "refetchKey" in template, (
        "refetchKey not found in HTML_TEMPLATE — fleet refetch mechanism missing"
    )
    assert "setRefetchKey" in template, (
        "setRefetchKey not found in HTML_TEMPLATE — fleet refetch mechanism missing"
    )
