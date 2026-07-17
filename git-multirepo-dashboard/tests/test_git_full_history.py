"""
Packet 06 — Git Full History Scan: Tests

Run from project root:
    .venv/bin/python -m pytest tests/test_git_full_history.py -v
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import guard ──────────────────────────────────────────────────────────────
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


def _make_format_line(
    hash_="aabbccddeeff00112233445566778899aabbccdd",  # pragma: allowlist secret
    date="2026-03-10T14:30:00-05:00",
    author="Test User",
    subject="Add feature X",
):
    """Build a git log format line (null-byte separated fields)."""
    return f"{hash_}\x00{date}\x00{author}\x00{subject}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. parse_git_log — single commit with shortstat
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_single_commit():
    """Parse git log output with one commit; verify all fields extracted correctly."""
    output = (
        "aabbccddeeff00112233445566778899aabbccdd\x002026-03-10T14:30:00-05:00\x00Test User\x00Add feature X\n"
        "\n"
        " 3 files changed, 45 insertions(+), 12 deletions(-)"
    )
    commits = git_dashboard.parse_git_log(output)

    assert len(commits) == 1
    c = commits[0]
    assert c["hash"] == "aabbccddeeff00112233445566778899aabbccdd"  # pragma: allowlist secret
    assert c["date"] == "2026-03-10T14:30:00-05:00"
    assert c["author"] == "Test User"
    assert c["subject"] == "Add feature X"
    assert c["files_changed"] == 3
    assert c["insertions"] == 45
    assert c["deletions"] == 12


# ─────────────────────────────────────────────────────────────────────────────
# 2. parse_git_log — multiple commits
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_multiple_commits():
    """Parse output with 3 commits; verify correct count and all fields for each."""
    output = (
        "aaaa000000000000000000000000000000000001\x002026-03-08T10:00:00+00:00\x00Alice\x00First commit\n"
        "\n"
        " 1 file changed, 5 insertions(+), 2 deletions(-)\n"
        "aaaa000000000000000000000000000000000002\x002026-03-09T11:00:00+00:00\x00Bob\x00Second commit\n"
        "\n"
        " 2 files changed, 10 insertions(+)\n"
        "aaaa000000000000000000000000000000000003\x002026-03-10T12:00:00+00:00\x00Carol\x00Third commit\n"
        "\n"
        " 4 files changed, 3 deletions(-)"
    )
    commits = git_dashboard.parse_git_log(output)

    assert len(commits) == 3

    assert commits[0]["hash"] == "aaaa000000000000000000000000000000000001"
    assert commits[0]["author"] == "Alice"
    assert commits[0]["subject"] == "First commit"
    assert commits[0]["files_changed"] == 1
    assert commits[0]["insertions"] == 5
    assert commits[0]["deletions"] == 2

    assert commits[1]["hash"] == "aaaa000000000000000000000000000000000002"
    assert commits[1]["author"] == "Bob"
    assert commits[1]["files_changed"] == 2
    assert commits[1]["insertions"] == 10
    assert commits[1]["deletions"] == 0

    assert commits[2]["hash"] == "aaaa000000000000000000000000000000000003"
    assert commits[2]["author"] == "Carol"
    assert commits[2]["files_changed"] == 4
    assert commits[2]["insertions"] == 0
    assert commits[2]["deletions"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# 3. parse_git_log — merge commit with no shortstat
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_merge_commit_no_shortstat():
    """A commit followed immediately by another format line gets insertions=deletions=files_changed=0."""
    # The merge commit (first) has no shortstat — the next line is another format line
    output = (
        "merge000000000000000000000000000000001\x002026-03-10T09:00:00+00:00\x00Merger\x00Merge branch 'feat'\n"
        "normal00000000000000000000000000000001\x002026-03-09T08:00:00+00:00\x00Dev\x00Normal commit\n"
        "\n"
        " 2 files changed, 8 insertions(+), 1 deletions(-)"
    )
    commits = git_dashboard.parse_git_log(output)

    assert len(commits) == 2

    merge_commit = commits[0]
    assert merge_commit["hash"] == "merge000000000000000000000000000000001"
    assert merge_commit["insertions"] == 0
    assert merge_commit["deletions"] == 0
    assert merge_commit["files_changed"] == 0

    normal_commit = commits[1]
    assert normal_commit["hash"] == "normal00000000000000000000000000000001"
    assert normal_commit["files_changed"] == 2
    assert normal_commit["insertions"] == 8
    assert normal_commit["deletions"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. parse_git_log — empty output
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_empty_output():
    """parse_git_log("") returns empty list without crashing."""
    commits = git_dashboard.parse_git_log("")
    assert commits == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. parse_git_log — shortstat variations
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_shortstat_variations():
    """Handle all shortstat format variations correctly."""
    hash_base = "bbbb{i:035d}"

    def make_commit(i, shortstat):
        h = f"bbbb{i:035d}"
        return (
            f"{h}\x002026-03-10T10:00:00+00:00\x00User\x00Commit {i}\n"
            "\n"
            f" {shortstat}"
        )

    # Case 1: insertions only (no deletions)
    out1 = make_commit(1, "1 file changed, 2 insertions(+)")
    c1 = git_dashboard.parse_git_log(out1)[0]
    assert c1["files_changed"] == 1
    assert c1["insertions"] == 2
    assert c1["deletions"] == 0

    # Case 2: deletions only (no insertions)
    out2 = make_commit(2, "1 file changed, 3 deletions(-)")
    c2 = git_dashboard.parse_git_log(out2)[0]
    assert c2["files_changed"] == 1
    assert c2["insertions"] == 0
    assert c2["deletions"] == 3

    # Case 3: both insertions and deletions
    out3 = make_commit(3, "5 files changed, 10 insertions(+), 3 deletions(-)")
    c3 = git_dashboard.parse_git_log(out3)[0]
    assert c3["files_changed"] == 5
    assert c3["insertions"] == 10
    assert c3["deletions"] == 3

    # Case 4: rename-only — "1 file changed" with no insertions or deletions
    out4 = make_commit(4, "1 file changed")
    c4 = git_dashboard.parse_git_log(out4)[0]
    assert c4["files_changed"] == 1
    assert c4["insertions"] == 0
    assert c4["deletions"] == 0

    # Case 5: plural "files" (already covered by case 3, but explicit singular test)
    out5 = make_commit(5, "1 file changed, 1 insertions(+)")
    c5 = git_dashboard.parse_git_log(out5)[0]
    assert c5["files_changed"] == 1
    assert c5["insertions"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 6. aggregate_daily_stats — same-day commits are summed
# ─────────────────────────────────────────────────────────────────────────────

def test_aggregate_same_day():
    """Two commits on the same date produce one daily_stats entry with summed values."""
    commits = [
        {
            "hash": "aaa1", "date": "2026-03-10T09:00:00+00:00", "author": "A", "subject": "s1",
            "insertions": 10, "deletions": 2, "files_changed": 3,
        },
        {
            "hash": "aaa2", "date": "2026-03-10T15:00:00+00:00", "author": "B", "subject": "s2",
            "insertions": 5, "deletions": 1, "files_changed": 1,
        },
    ]
    daily = git_dashboard.aggregate_daily_stats(commits)

    assert len(daily) == 1
    day = daily["2026-03-10"]
    assert day["commits"] == 2
    assert day["insertions"] == 15
    assert day["deletions"] == 3
    assert day["files_changed"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# 7. aggregate_daily_stats — different-day commits produce separate entries
# ─────────────────────────────────────────────────────────────────────────────

def test_aggregate_different_days():
    """Commits on different dates produce separate daily_stats entries."""
    commits = [
        {
            "hash": "bbb1", "date": "2026-03-09T10:00:00+00:00", "author": "A", "subject": "s1",
            "insertions": 7, "deletions": 1, "files_changed": 2,
        },
        {
            "hash": "bbb2", "date": "2026-03-10T11:00:00+00:00", "author": "B", "subject": "s2",
            "insertions": 3, "deletions": 0, "files_changed": 1,
        },
    ]
    daily = git_dashboard.aggregate_daily_stats(commits)

    assert len(daily) == 2
    assert "2026-03-09" in daily
    assert "2026-03-10" in daily
    assert daily["2026-03-09"]["commits"] == 1
    assert daily["2026-03-09"]["insertions"] == 7
    assert daily["2026-03-10"]["commits"] == 1
    assert daily["2026-03-10"]["insertions"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# 8. aggregate_daily_stats — empty commit list
# ─────────────────────────────────────────────────────────────────────────────

def test_aggregate_empty_commits():
    """aggregate_daily_stats([]) returns an empty dict without crashing."""
    daily = git_dashboard.aggregate_daily_stats([])
    assert daily == {}


# ─────────────────────────────────────────────────────────────────────────────
# 9. upsert_daily_stats — inserts new rows
# ─────────────────────────────────────────────────────────────────────────────

def test_upsert_daily_stats_insert(tmp_path):
    """upsert_daily_stats writes new rows to daily_stats; verify via SQL SELECT."""
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    repo_id = "testrepo0000001"

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            # Insert repo row (FK requirement)
            await db.execute(
                "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
                (repo_id, "testrepo", "/tmp/testrepo", "2026-03-01T00:00:00+00:00"),
            )
            await db.commit()

            daily_data = {
                "2026-03-09": {"commits": 3, "insertions": 20, "deletions": 5, "files_changed": 7},
                "2026-03-10": {"commits": 1, "insertions": 4, "deletions": 0, "files_changed": 2},
            }
            await git_dashboard.upsert_daily_stats(db, repo_id, daily_data)

            cursor = await db.execute(
                "SELECT date, commits, insertions, deletions, files_changed FROM daily_stats WHERE repo_id = ? ORDER BY date",
                (repo_id,),
            )
            return await cursor.fetchall()

    rows = run(_run())
    assert len(rows) == 2

    assert rows[0] == ("2026-03-09", 3, 20, 5, 7)
    assert rows[1] == ("2026-03-10", 1, 4, 0, 2)


# ─────────────────────────────────────────────────────────────────────────────
# 10. upsert_daily_stats — replaces existing rows on conflict
# ─────────────────────────────────────────────────────────────────────────────

def test_upsert_daily_stats_replace(tmp_path):
    """upsert_daily_stats overwrites existing rows on (repo_id, date) conflict."""
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    repo_id = "testrepo0000002"

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(
                "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
                (repo_id, "testrepo2", "/tmp/testrepo2", "2026-03-01T00:00:00+00:00"),
            )
            await db.commit()

            # First upsert — original values
            first_data = {
                "2026-03-10": {"commits": 1, "insertions": 5, "deletions": 1, "files_changed": 2},
            }
            await git_dashboard.upsert_daily_stats(db, repo_id, first_data)

            # Second upsert — updated values for the same date
            second_data = {
                "2026-03-10": {"commits": 4, "insertions": 30, "deletions": 8, "files_changed": 6},
            }
            await git_dashboard.upsert_daily_stats(db, repo_id, second_data)

            cursor = await db.execute(
                "SELECT commits, insertions, deletions, files_changed FROM daily_stats WHERE repo_id = ? AND date = '2026-03-10'",
                (repo_id,),
            )
            return await cursor.fetchone()

    row = run(_run())
    assert row is not None
    # Values from second upsert must win
    assert row == (4, 30, 8, 6)


# ─────────────────────────────────────────────────────────────────────────────
# 11. scan_full_history — calls run_git with correct flags
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_full_history_uses_run_git():
    """scan_full_history invokes run_git with --all, --format, and --shortstat flags."""
    captured_args = []

    async def mock_run_git(repo_path, *args):
        captured_args.extend(args)
        return ("", "", 0)

    with patch.object(git_dashboard, "run_git", side_effect=mock_run_git):
        run(git_dashboard.scan_full_history("/tmp/repo"))

    assert "--all" in captured_args
    assert "--shortstat" in captured_args
    # --format value must contain the null-byte separator fields
    format_arg = next((a for a in captured_args if a.startswith("--format=")), None)
    assert format_arg is not None
    assert "%H" in format_arg
    assert "%aI" in format_arg
    assert "%an" in format_arg
    assert "%s" in format_arg
    # Must NOT contain literal NUL bytes — subprocess rejects them.
    # Use git's %x00 escape instead of Python \x00.
    assert "\x00" not in format_arg, (
        "format arg contains literal NUL bytes which crash subprocess; use %x00"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 12. scan_full_history — includes --after when since is provided
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_full_history_incremental():
    """When since is provided, the git command includes --after={since}."""
    captured_args = []

    async def mock_run_git(repo_path, *args):
        captured_args.extend(args)
        return ("", "", 0)

    since = "2026-03-01T00:00:00+00:00"
    with patch.object(git_dashboard, "run_git", side_effect=mock_run_git):
        run(git_dashboard.scan_full_history("/tmp/repo", since=since))

    after_args = [a for a in captured_args if a.startswith("--after=")]
    assert len(after_args) == 1
    assert after_args[0] == f"--after={since}"


# ─────────────────────────────────────────────────────────────────────────────
# 13. scan_full_history — omits --after when since is None
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_full_history_no_since():
    """When since is None, the git command does NOT include --after."""
    captured_args = []

    async def mock_run_git(repo_path, *args):
        captured_args.extend(args)
        return ("", "", 0)

    with patch.object(git_dashboard, "run_git", side_effect=mock_run_git):
        run(git_dashboard.scan_full_history("/tmp/repo", since=None))

    after_args = [a for a in captured_args if a.startswith("--after")]
    assert len(after_args) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 14. run_full_history_scan — updates last_full_scan_at
# ─────────────────────────────────────────────────────────────────────────────

def test_run_full_history_scan_updates_last_full_scan_at(tmp_path):
    """After run_full_history_scan, repositories.last_full_scan_at is a valid UTC ISO 8601 timestamp."""
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    repo_id = "testrepo0000003"
    repo_path = "/tmp/testrepo3"

    # Sample git log output for one commit
    sample_output = (
        "cccc000000000000000000000000000000000001\x002026-03-10T10:00:00+00:00\x00Dev\x00A commit\n"
        "\n"
        " 1 file changed, 5 insertions(+)"
    )

    async def mock_run_git(rp, *args):
        return (sample_output, "", 0)

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(
                "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
                (repo_id, "testrepo3", repo_path, "2026-03-01T00:00:00+00:00"),
            )
            await db.commit()

            with patch.object(git_dashboard, "run_git", side_effect=mock_run_git):
                await git_dashboard.run_full_history_scan(db, repo_id, repo_path)

            cursor = await db.execute(
                "SELECT last_full_scan_at FROM repositories WHERE id = ?",
                (repo_id,),
            )
            row = await cursor.fetchone()
            return row[0]

    last_scan_at = run(_run())

    assert last_scan_at is not None
    # Must be parseable as ISO 8601
    dt = datetime.fromisoformat(last_scan_at)
    assert dt.tzinfo is not None


# ─────────────────────────────────────────────────────────────────────────────
# 15. run_full_history_scan — returns commit count
# ─────────────────────────────────────────────────────────────────────────────

def test_run_full_history_scan_returns_commit_count(tmp_path):
    """run_full_history_scan returns the count of commits parsed from git log output."""
    db_path = tmp_path / "test.db"
    git_dashboard.init_schema(db_path)

    repo_id = "testrepo0000004"
    repo_path = "/tmp/testrepo4"

    # 3-commit output
    sample_output = (
        "dddd000000000000000000000000000000000001\x002026-03-08T09:00:00+00:00\x00Dev\x00Commit 1\n"
        "\n"
        " 1 file changed, 2 insertions(+)\n"
        "dddd000000000000000000000000000000000002\x002026-03-09T10:00:00+00:00\x00Dev\x00Commit 2\n"
        "\n"
        " 3 files changed, 15 insertions(+), 4 deletions(-)\n"
        "dddd000000000000000000000000000000000003\x002026-03-10T11:00:00+00:00\x00Dev\x00Commit 3\n"
        "\n"
        " 1 file changed, 1 deletions(-)"
    )

    async def mock_run_git(rp, *args):
        return (sample_output, "", 0)

    async def _run():
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(
                "INSERT INTO repositories (id, name, path, added_at) VALUES (?, ?, ?, ?)",
                (repo_id, "testrepo4", repo_path, "2026-03-01T00:00:00+00:00"),
            )
            await db.commit()

            with patch.object(git_dashboard, "run_git", side_effect=mock_run_git):
                return await git_dashboard.run_full_history_scan(db, repo_id, repo_path)

    count = run(_run())
    assert count == 3


# ─────────────────────────────────────────────────────────────────────────────
# (23A gap 3) parse_git_log — merge commits with no shortstat line
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_git_log_merge_commit_no_shortstat():
    """Merge commits produce no shortstat line; parse_git_log must include them
    with insertions=0, deletions=0, files_changed=0 rather than dropping them.
    """
    # A merge commit has the format line but no following shortstat
    merge_hash = "aaaa0000bbbb1111cccc2222dddd3333eeee4444"  # pragma: allowlist secret
    regular_hash = "1111222233334444555566667777888899990000"

    output = (
        f"{merge_hash}\x002026-03-10T12:00:00+00:00\x00Merger Bot\x00Merge branch 'feature/foo'\n"
        "\n"
        # No shortstat for the merge commit
        f"{regular_hash}\x002026-03-09T09:00:00+00:00\x00Dev User\x00Add feature foo\n"
        "\n"
        " 2 files changed, 30 insertions(+), 5 deletions(-)"
    )

    commits = git_dashboard.parse_git_log(output)

    assert len(commits) == 2, f"Expected 2 commits (including merge), got {len(commits)}"

    # First commit is the merge commit — must have zeros, not be dropped
    merge = commits[0]
    assert merge["hash"] == merge_hash
    assert merge["subject"] == "Merge branch 'feature/foo'"
    assert merge["insertions"] == 0, f"Merge commit insertions must be 0, got {merge['insertions']}"
    assert merge["deletions"] == 0, f"Merge commit deletions must be 0, got {merge['deletions']}"
    assert merge["files_changed"] == 0, f"Merge commit files_changed must be 0, got {merge['files_changed']}"

    # Second commit is a regular commit — must have real shortstat values
    regular = commits[1]
    assert regular["hash"] == regular_hash
    assert regular["insertions"] == 30
    assert regular["deletions"] == 5
    assert regular["files_changed"] == 2


def test_parse_git_log_all_merge_commits():
    """Output that is ONLY merge commits (no shortstat for any) must parse all of them."""
    output = (
        "aaaa000011112222333344445555666677778888\x002026-03-08T10:00:00+00:00\x00Bot\x00Merge A\n"
        "\n"
        "bbbb000011112222333344445555666677778888\x002026-03-07T10:00:00+00:00\x00Bot\x00Merge B\n"
        "\n"
        "cccc000011112222333344445555666677778888\x002026-03-06T10:00:00+00:00\x00Bot\x00Merge C\n"
    )

    commits = git_dashboard.parse_git_log(output)

    assert len(commits) == 3, f"Expected 3 merge commits, got {len(commits)}"
    for c in commits:
        assert c["insertions"] == 0
        assert c["deletions"] == 0
        assert c["files_changed"] == 0
