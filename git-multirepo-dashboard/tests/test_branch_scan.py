"""Packet 07 — Branch Scan: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_branch_scan.py -v
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import guard ───────────────────────────────────────────────────────────────
try:
    import aiosqlite  # noqa: F401
except ImportError:
    pytest.skip(
        "aiosqlite not installed — run tests inside the test venv: "
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


async def _make_db_with_repo(repo_id: str = "testrepo00000001"):
    """Create an in-memory aiosqlite DB with schema + one repository row.

    Foreign key enforcement is enabled so CASCADE deletes work correctly.
    """
    db = await aiosqlite.connect(":memory:")
    await db.execute("PRAGMA foreign_keys = ON")
    await db.executescript(git_dashboard._SCHEMA_SQL)
    await db.execute(
        "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
        (repo_id, "test-repo", "/tmp/test-repo", "2026-01-01T00:00:00+00:00"),
    )
    await db.commit()
    return db


def _recent_iso() -> str:
    """Return an ISO 8601 date 1 day ago (definitely not stale)."""
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _old_iso() -> str:
    """Return an ISO 8601 date 60 days ago (definitely stale)."""
    return (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# 1. parse_single_branch
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_single_branch():
    """Parse one branch line; verify all fields extracted correctly."""
    recent = _recent_iso()
    output = f"main\t{recent}"
    result = git_dashboard.parse_branches(output, default_branch="main")

    assert len(result) == 1
    b = result[0]
    assert b["name"] == "main"
    assert b["last_commit_date"] == recent
    assert b["is_default"] is True
    assert b["is_stale"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. parse_multiple_branches
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_multiple_branches():
    """Parse 3 branch lines; verify correct count and fields for each."""
    recent = _recent_iso()
    old = _old_iso()
    output = "\n".join([
        f"main\t{recent}",
        f"feature/auth\t{old}",
        f"develop\t{recent}",
    ])
    result = git_dashboard.parse_branches(output, default_branch="main")

    assert len(result) == 3
    names = {b["name"] for b in result}
    assert names == {"main", "feature/auth", "develop"}

    main_branch = next(b for b in result if b["name"] == "main")
    assert main_branch["is_default"] is True
    assert main_branch["is_stale"] is False

    feature_branch = next(b for b in result if b["name"] == "feature/auth")
    assert feature_branch["is_default"] is False
    assert feature_branch["is_stale"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. parse_default_branch_detection
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_default_branch_detection():
    """Only the branch matching default_branch gets is_default=True."""
    recent = _recent_iso()
    output = "\n".join([
        f"main\t{recent}",
        f"feature/auth\t{recent}",
        f"develop\t{recent}",
    ])
    result = git_dashboard.parse_branches(output, default_branch="main")

    defaults = [b for b in result if b["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "main"

    non_defaults = [b for b in result if not b["is_default"]]
    assert len(non_defaults) == 2
    assert {b["name"] for b in non_defaults} == {"feature/auth", "develop"}


# ─────────────────────────────────────────────────────────────────────────────
# 4. parse_stale_detection
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_stale_detection():
    """Stale/fresh detection; default branch is never stale."""
    now = datetime.now(timezone.utc)

    old_date = (now - timedelta(days=60)).isoformat()        # definitely stale
    recent_date = (now - timedelta(days=1)).isoformat()      # definitely fresh
    # 30 days minus 1 second: just inside the not-stale zone.
    # Using exactly 30 days is racy because datetime.now() advances between test
    # and function, making the boundary_date appear stale by microseconds.
    boundary_date = (now - timedelta(days=30) + timedelta(seconds=1)).isoformat()  # NOT stale

    output = "\n".join([
        f"main\t{old_date}",
        f"stale-branch\t{old_date}",
        f"fresh-branch\t{recent_date}",
        f"boundary-branch\t{boundary_date}",
    ])
    result = git_dashboard.parse_branches(output, default_branch="main")

    stale_b = next(b for b in result if b["name"] == "stale-branch")
    main_b = next(b for b in result if b["name"] == "main")
    fresh_b = next(b for b in result if b["name"] == "fresh-branch")
    boundary_b = next(b for b in result if b["name"] == "boundary-branch")

    assert main_b["is_default"] is True
    assert main_b["is_stale"] is False
    assert stale_b["is_stale"] is True
    assert fresh_b["is_stale"] is False
    assert boundary_b["is_stale"] is False  # exactly 30 days = NOT stale


# ─────────────────────────────────────────────────────────────────────────────
# 5. parse_empty_output
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_empty_output():
    """Empty string input returns empty list without crashing."""
    result = git_dashboard.parse_branches("", default_branch="main")
    assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. parse_branch_no_commits (orphan branch with missing date)
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_branch_no_commits():
    """Branch line with empty committer date: last_commit_date=None, is_stale=True."""
    # git branch --format produces an empty string for committerdate when no commits
    output = "orphan\t"
    result = git_dashboard.parse_branches(output, default_branch="main")

    assert len(result) == 1
    b = result[0]
    assert b["name"] == "orphan"
    assert b["last_commit_date"] is None
    assert b["is_stale"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 7. parse_branch_with_slashes
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_branch_with_slashes():
    """Branch names containing slashes are parsed correctly."""
    recent = _recent_iso()
    output = f"feature/auth/v2\t{recent}"
    result = git_dashboard.parse_branches(output, default_branch="main")

    assert len(result) == 1
    assert result[0]["name"] == "feature/auth/v2"
    assert result[0]["last_commit_date"] == recent


# ─────────────────────────────────────────────────────────────────────────────
# 8. upsert_branches_insert
# ─────────────────────────────────────────────────────────────────────────────

def test_upsert_branches_insert():
    """Upsert writes new rows; verify count and values via SQL SELECT."""
    async def _run():
        repo_id = "testrepo00000001"
        db = await _make_db_with_repo(repo_id)
        recent = _recent_iso()
        branches = [
            {"name": "main", "last_commit_date": recent, "is_default": True, "is_stale": False},
            {"name": "dev", "last_commit_date": recent, "is_default": False, "is_stale": False},
        ]
        await git_dashboard.upsert_branches(db, repo_id, branches)

        cursor = await db.execute(
            "SELECT name, is_default FROM branches WHERE repo_id = ? ORDER BY name",
            (repo_id,),
        )
        rows = await cursor.fetchall()
        await db.close()
        return rows

    rows = run(_run())
    assert len(rows) == 2
    assert rows[0][0] == "dev"
    assert rows[1][0] == "main"
    assert rows[1][1] == 1  # is_default=True for main


# ─────────────────────────────────────────────────────────────────────────────
# 9. upsert_branches_replaces_all
# ─────────────────────────────────────────────────────────────────────────────

def test_upsert_branches_replaces_all():
    """Second upsert fully replaces first; old branches removed, new branches present."""
    async def _run():
        repo_id = "testrepo00000001"
        db = await _make_db_with_repo(repo_id)
        recent = _recent_iso()

        first_set = [
            {"name": "main", "last_commit_date": recent, "is_default": True, "is_stale": False},
            {"name": "dev", "last_commit_date": recent, "is_default": False, "is_stale": False},
        ]
        await git_dashboard.upsert_branches(db, repo_id, first_set)

        second_set = [
            {"name": "main", "last_commit_date": recent, "is_default": True, "is_stale": False},
            {"name": "feature", "last_commit_date": recent, "is_default": False, "is_stale": False},
        ]
        await git_dashboard.upsert_branches(db, repo_id, second_set)

        cursor = await db.execute(
            "SELECT name FROM branches WHERE repo_id = ? ORDER BY name",
            (repo_id,),
        )
        rows = await cursor.fetchall()
        await db.close()
        return [r[0] for r in rows]

    names = run(_run())
    assert "dev" not in names       # removed by second upsert
    assert "feature" in names       # added in second upsert
    assert "main" in names          # persisted across both


# ─────────────────────────────────────────────────────────────────────────────
# 10. upsert_branches_empty_list
# ─────────────────────────────────────────────────────────────────────────────

def test_upsert_branches_empty_list():
    """Upserting an empty list clears all existing branch rows for the repo."""
    async def _run():
        repo_id = "testrepo00000001"
        db = await _make_db_with_repo(repo_id)
        recent = _recent_iso()

        branches = [
            {"name": "main", "last_commit_date": recent, "is_default": True, "is_stale": False},
        ]
        await git_dashboard.upsert_branches(db, repo_id, branches)

        # Now upsert empty list — should clear all rows
        await git_dashboard.upsert_branches(db, repo_id, [])

        cursor = await db.execute(
            "SELECT COUNT(*) FROM branches WHERE repo_id = ?", (repo_id,)
        )
        row = await cursor.fetchone()
        await db.close()
        return row[0]

    count = run(_run())
    assert count == 0


# ─────────────────────────────────────────────────────────────────────────────
# 11. scan_branches_calls_run_git
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_branches_calls_run_git():
    """scan_branches calls run_git with the correct git branch --format flag."""
    captured_args = []

    async def fake_run_git(repo_path, *args):
        captured_args.extend(args)
        return ("", "", 0)

    with patch.object(git_dashboard, "run_git", side_effect=fake_run_git):
        run(git_dashboard.scan_branches("/tmp/test-repo", default_branch="main"))

    assert "branch" in captured_args
    # Verify the --format flag contains both refname:short and committerdate:iso-strict
    # separated by %09 (git format escape for tab character)
    format_arg = next((a for a in captured_args if a.startswith("--format=")), None)
    assert format_arg is not None
    assert "%(refname:short)" in format_arg
    assert "%09" in format_arg
    assert "%(committerdate:iso-strict)" in format_arg


# ─────────────────────────────────────────────────────────────────────────────
# 12. run_branch_scan_returns_count
# ─────────────────────────────────────────────────────────────────────────────

def test_run_branch_scan_returns_count():
    """run_branch_scan returns the number of branches parsed."""
    recent = _recent_iso()
    fake_branches = [
        {"name": "main", "last_commit_date": recent, "is_default": True, "is_stale": False},
        {"name": "dev", "last_commit_date": recent, "is_default": False, "is_stale": False},
        {"name": "feature/x", "last_commit_date": recent, "is_default": False, "is_stale": False},
    ]

    async def _run():
        repo_id = "testrepo00000001"
        db = await _make_db_with_repo(repo_id)

        with patch.object(git_dashboard, "scan_branches", new=AsyncMock(return_value=fake_branches)):
            with patch.object(git_dashboard, "upsert_branches", new=AsyncMock()):
                count = await git_dashboard.run_branch_scan(db, repo_id, "/tmp/test-repo")

        await db.close()
        return count

    assert run(_run()) == 3


# ─────────────────────────────────────────────────────────────────────────────
# 13. run_branch_scan_cascade_delete
# ─────────────────────────────────────────────────────────────────────────────

def test_run_branch_scan_cascade_delete():
    """Deleting a repo from repositories also deletes its branches (CASCADE)."""
    async def _run():
        repo_id = "testrepo00000001"
        db = await _make_db_with_repo(repo_id)
        recent = _recent_iso()

        branches = [
            {"name": "main", "last_commit_date": recent, "is_default": True, "is_stale": False},
            {"name": "dev", "last_commit_date": recent, "is_default": False, "is_stale": False},
        ]
        await git_dashboard.upsert_branches(db, repo_id, branches)

        # Verify branches exist before delete
        cursor = await db.execute(
            "SELECT COUNT(*) FROM branches WHERE repo_id = ?", (repo_id,)
        )
        before = (await cursor.fetchone())[0]

        # Delete the repo — CASCADE should remove branches
        await db.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
        await db.commit()

        cursor = await db.execute(
            "SELECT COUNT(*) FROM branches WHERE repo_id = ?", (repo_id,)
        )
        after = (await cursor.fetchone())[0]
        await db.close()
        return before, after

    before, after = run(_run())
    assert before == 2
    assert after == 0
