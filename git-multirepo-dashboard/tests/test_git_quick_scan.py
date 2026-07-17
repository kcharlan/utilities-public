"""
Packet 01 — Git Quick Scan: Tests

Run from project root after bootstrapping:
    ~/.git_dashboard_venv/bin/python -m pytest tests/test_git_quick_scan.py -v
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

# git_dashboard.py is in the project root (parent of this tests/ directory)
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import guard: bootstrap() must pass without re-execing in test context ───
try:
    import fastapi  # noqa: F401
except ImportError:
    pytest.skip(
        "fastapi not installed — run tests inside the app venv: "
        "~/.git_dashboard_venv/bin/python -m pytest",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_git_repo(path: Path, *, empty: bool = False) -> Path:
    """Initialize a git repo at path. If not empty, add one commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "synthetic-user@example.invalid"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        check=True, capture_output=True,
    )
    if not empty:
        subprocess.run(
            ["git", "-C", str(path), "commit", "--allow-empty", "-m", "initial commit"],
            check=True, capture_output=True,
        )
    return path


def run(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# 1. run_git
# ─────────────────────────────────────────────────────────────────────────────

def test_run_git_returns_stdout(tmp_path):
    """run_git executes a git command and returns decoded stdout."""
    _make_git_repo(tmp_path)
    stdout, stderr, rc = run(git_dashboard.run_git(tmp_path, "rev-parse", "--is-inside-work-tree"))
    assert rc == 0
    assert "true" in stdout.lower()


def test_run_git_returns_stderr_on_error(tmp_path):
    """run_git returns non-zero returncode and stderr on failure."""
    _make_git_repo(tmp_path)
    # 'git show DEADBEEF' on a non-existent object → rc != 0
    stdout, stderr, rc = run(git_dashboard.run_git(tmp_path, "show", "DEADBEEF0000000000000000000000000000000000"))
    assert rc != 0


def test_run_git_path_with_spaces(tmp_path):
    """run_git works correctly when repo path contains spaces."""
    spaced = tmp_path / "my repo with spaces"
    spaced.mkdir()
    _make_git_repo(spaced)
    stdout, stderr, rc = run(git_dashboard.run_git(spaced, "rev-parse", "--is-inside-work-tree"))
    assert rc == 0
    assert "true" in stdout.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 2. is_valid_repo
# ─────────────────────────────────────────────────────────────────────────────

def test_is_valid_repo_true_for_git_repo(tmp_path):
    """is_valid_repo returns True for an initialized git repository."""
    _make_git_repo(tmp_path)
    assert run(git_dashboard.is_valid_repo(tmp_path)) is True


def test_is_valid_repo_false_for_nonexistent_path():
    """is_valid_repo returns False for a path that does not exist."""
    assert run(git_dashboard.is_valid_repo(Path("/tmp/nonexistent_xyz_abc_123"))) is False


def test_is_valid_repo_false_for_plain_directory(tmp_path):
    """is_valid_repo returns False for a directory that is not a git repo."""
    assert run(git_dashboard.is_valid_repo(tmp_path)) is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. parse_porcelain_status — clean repo
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_porcelain_status_empty():
    """Empty string (clean repo) yields all-zero counts and has_uncommitted=False."""
    result = git_dashboard.parse_porcelain_status("")
    assert result == {
        "modified_count": 0,
        "untracked_count": 0,
        "staged_count": 0,
        "has_uncommitted": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. parse_porcelain_status — dirty repo
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_porcelain_status_dirty():
    """Mixed status lines are classified correctly."""
    output = (
        " M file1.py\n"   # worktree modified, not staged
        "M  file2.py\n"   # staged modified
        "A  file3.py\n"   # staged new file
        "?? newfile.txt\n"
        "?? another.txt\n"
    )
    result = git_dashboard.parse_porcelain_status(output)
    assert result["modified_count"] == 1    # ' M': worktree only
    assert result["staged_count"] == 2      # 'M ' and 'A '
    assert result["untracked_count"] == 2   # '??'
    assert result["has_uncommitted"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. parse_porcelain_status — index vs worktree distinctions
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_porcelain_both_staged_and_modified():
    """MM means both staged AND worktree-modified."""
    result = git_dashboard.parse_porcelain_status("MM file.py\n")
    assert result["staged_count"] == 1
    assert result["modified_count"] == 1
    assert result["untracked_count"] == 0
    assert result["has_uncommitted"] is True


def test_parse_porcelain_staged_only():
    """'A  file.py' means staged only (index add, worktree clean)."""
    result = git_dashboard.parse_porcelain_status("A  file.py\n")
    assert result["staged_count"] == 1
    assert result["modified_count"] == 0
    assert result["untracked_count"] == 0


def test_parse_porcelain_modified_only():
    """' M file.py' means worktree modified, not staged."""
    result = git_dashboard.parse_porcelain_status(" M file.py\n")
    assert result["staged_count"] == 0
    assert result["modified_count"] == 1
    assert result["untracked_count"] == 0


def test_parse_porcelain_deleted_staged():
    """'D  file.py' is staged deletion."""
    result = git_dashboard.parse_porcelain_status("D  file.py\n")
    assert result["staged_count"] == 1
    assert result["modified_count"] == 0


def test_parse_porcelain_am_counts_in_both():
    """'AM file.py': staged add (index) AND worktree modification."""
    result = git_dashboard.parse_porcelain_status("AM file.py\n")
    assert result["staged_count"] == 1
    assert result["modified_count"] == 1


def test_parse_porcelain_unmerged():
    """'UU file.py' merge conflict: X='U' which is not ' ' or '?' → staged_count."""
    result = git_dashboard.parse_porcelain_status("UU file.py\n")
    assert result["staged_count"] == 1   # X='U' triggers staged
    assert result["has_uncommitted"] is True


def test_parse_porcelain_multiple_untracked():
    """Multiple '??' lines all go to untracked_count."""
    output = "?? a.txt\n?? b.txt\n?? c.txt\n"
    result = git_dashboard.parse_porcelain_status(output)
    assert result["untracked_count"] == 3
    assert result["staged_count"] == 0
    assert result["modified_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. parse_last_commit — valid output
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_last_commit_valid():
    """NUL-delimited format is split correctly."""
    raw = "abc123def456\x002026-03-09T14:23:00-06:00\x00fix: handle empty response"
    result = git_dashboard.parse_last_commit(raw)
    assert result == {
        "hash": "abc123def456",  # pragma: allowlist secret
        "date": "2026-03-09T14:23:00-06:00",
        "message": "fix: handle empty response",
    }


def test_parse_last_commit_message_with_spaces_and_colons():
    """Subject with colons, spaces, and specials is not truncated."""
    raw = "deadbeef\x002026-01-01T00:00:00+00:00\x00feat: add foo: bar (baz)"
    result = git_dashboard.parse_last_commit(raw)
    assert result["message"] == "feat: add foo: bar (baz)"


# ─────────────────────────────────────────────────────────────────────────────
# 7. parse_last_commit — empty repo (no commits)
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_last_commit_empty():
    """Empty string (no commits yet) returns all-None dict."""
    result = git_dashboard.parse_last_commit("")
    assert result == {"hash": None, "date": None, "message": None}


# ─────────────────────────────────────────────────────────────────────────────
# 8. quick_scan_repo — integration test
# ─────────────────────────────────────────────────────────────────────────────

def test_quick_scan_repo_basic(tmp_path):
    """quick_scan_repo returns a complete dict for a normal git repo."""
    _make_git_repo(tmp_path)
    # Add an uncommitted file
    (tmp_path / "dirty.txt").write_text("hello")
    result = run(git_dashboard.quick_scan_repo(tmp_path))
    assert result["has_uncommitted"] is True
    assert result["untracked_count"] >= 1
    assert result["current_branch"] is not None
    assert result["last_commit_hash"] is not None
    assert result["last_commit_date"] is not None
    # All required keys present
    for key in ("has_uncommitted", "modified_count", "untracked_count",
                "staged_count", "current_branch", "last_commit_hash",
                "last_commit_date", "last_commit_message"):
        assert key in result, f"Missing key: {key}"


def test_quick_scan_repo_clean(tmp_path):
    """quick_scan_repo on a clean repo reports has_uncommitted=False."""
    _make_git_repo(tmp_path)
    result = run(git_dashboard.quick_scan_repo(tmp_path))
    assert result["has_uncommitted"] is False
    assert result["modified_count"] == 0
    assert result["staged_count"] == 0
    assert result["untracked_count"] == 0


def test_quick_scan_repo_empty_repo(tmp_path):
    """quick_scan_repo handles a repo with zero commits gracefully."""
    _make_git_repo(tmp_path, empty=True)
    result = run(git_dashboard.quick_scan_repo(tmp_path))
    assert result["last_commit_hash"] is None
    assert result["last_commit_date"] is None
    assert result["last_commit_message"] is None
    # current_branch may be "HEAD" on empty repo — just verify it's a string or None
    assert result["current_branch"] is None or isinstance(result["current_branch"], str)


# ─────────────────────────────────────────────────────────────────────────────
# 9. upsert_working_state — writes and updates
# ─────────────────────────────────────────────────────────────────────────────

def test_upsert_working_state_creates_row():
    """upsert_working_state inserts a new row correctly."""
    import aiosqlite

    async def _run():
        async with aiosqlite.connect(":memory:") as db:
            await db.executescript(git_dashboard._SCHEMA_SQL)
            await db.execute(
                "INSERT INTO repositories (id, name, path, added_at) VALUES (?,?,?,?)",
                ("r1", "testrepo", "/tmp/testrepo", "2026-01-01T00:00:00+00:00"),
            )
            await db.commit()

            data = {
                "has_uncommitted": True,
                "modified_count": 2,
                "untracked_count": 3,
                "staged_count": 1,
                "current_branch": "main",
                "last_commit_hash": "abc123",
                "last_commit_message": "fix: something",
                "last_commit_date": "2026-03-09T00:00:00+00:00",
            }
            await git_dashboard.upsert_working_state(db, "r1", data)

            cursor = await db.execute("SELECT * FROM working_state WHERE repo_id = 'r1'")
            row = await cursor.fetchone()
            col_names = [d[0] for d in cursor.description]
            return dict(zip(col_names, row))

    result = run(_run())
    assert result["repo_id"] == "r1"
    assert result["has_uncommitted"] == 1   # SQLite stores booleans as int
    assert result["modified_count"] == 2
    assert result["untracked_count"] == 3
    assert result["staged_count"] == 1
    assert result["current_branch"] == "main"
    assert result["last_commit_hash"] == "abc123"
    assert result["last_commit_message"] == "fix: something"
    assert result["last_commit_date"] == "2026-03-09T00:00:00+00:00"
    assert result["checked_at"] is not None


def test_upsert_working_state_updates_existing():
    """A second upsert updates the row, not duplicates it."""
    import aiosqlite

    async def _run():
        async with aiosqlite.connect(":memory:") as db:
            await db.executescript(git_dashboard._SCHEMA_SQL)
            await db.execute(
                "INSERT INTO repositories (id, name, path, added_at) VALUES (?,?,?,?)",
                ("r1", "testrepo", "/tmp/testrepo", "2026-01-01T00:00:00+00:00"),
            )
            await db.commit()

            data_v1 = {
                "has_uncommitted": False,
                "modified_count": 0,
                "untracked_count": 0,
                "staged_count": 0,
                "current_branch": "main",
                "last_commit_hash": "hash1",
                "last_commit_message": "initial",
                "last_commit_date": "2026-01-01T00:00:00+00:00",
            }
            await git_dashboard.upsert_working_state(db, "r1", data_v1)

            data_v2 = {
                "has_uncommitted": True,
                "modified_count": 5,
                "untracked_count": 2,
                "staged_count": 3,
                "current_branch": "feature/foo",
                "last_commit_hash": "hash2",
                "last_commit_message": "feat: add foo",
                "last_commit_date": "2026-03-10T00:00:00+00:00",
            }
            await git_dashboard.upsert_working_state(db, "r1", data_v2)

            cursor = await db.execute("SELECT COUNT(*) FROM working_state WHERE repo_id = 'r1'")
            count = (await cursor.fetchone())[0]

            cursor2 = await db.execute("SELECT * FROM working_state WHERE repo_id = 'r1'")
            row = await cursor2.fetchone()
            col_names = [d[0] for d in cursor2.description]
            return count, dict(zip(col_names, row))

    count, result = run(_run())
    assert count == 1, "Should have exactly one row (upsert, not insert)"
    assert result["modified_count"] == 5
    assert result["current_branch"] == "feature/foo"
    assert result["last_commit_hash"] == "hash2"


# ─────────────────────────────────────────────────────────────────────────────
# 10. Detached HEAD state (gap 2 from 23A hardening)
# ─────────────────────────────────────────────────────────────────────────────

def test_quick_scan_detached_head(tmp_path):
    """quick_scan_repo returns valid data when repo is in detached HEAD state.

    current_branch must be None (not raise an exception), and all other fields
    must be present with appropriate values.
    """
    _make_git_repo(tmp_path)

    # Detach HEAD by checking out the commit hash directly
    stdout = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    subprocess.run(
        ["git", "-C", str(tmp_path), "checkout", "--detach", stdout],
        check=True, capture_output=True,
    )

    result = run(git_dashboard.quick_scan_repo(tmp_path))

    # Must not crash; all required keys must be present
    for key in ("has_uncommitted", "modified_count", "untracked_count",
                "staged_count", "current_branch", "last_commit_hash",
                "last_commit_date", "last_commit_message"):
        assert key in result, f"Missing key in detached-HEAD result: {key}"

    # Detached HEAD → current_branch is None (rev-parse returns "HEAD", not a branch name)
    assert result["current_branch"] is None, (
        f"Expected current_branch=None in detached HEAD, got {result['current_branch']!r}"
    )

    # last_commit_hash must still be populated (repo has commits)
    assert result["last_commit_hash"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# 11. run_git timeout handling (gap 4 from 23A hardening)
# ─────────────────────────────────────────────────────────────────────────────

def test_run_git_timeout_returns_sentinel(tmp_path):
    """run_git returns ("", "timeout", -1) when the subprocess exceeds the timeout.

    Uses asyncio.wait_for mocked to raise TimeoutError, verifying the kill/cleanup
    path is exercised and a stable sentinel value is returned instead of propagating
    the exception to callers.
    """
    _make_git_repo(tmp_path)

    async def _run():
        # Patch asyncio.wait_for to simulate a timeout on proc.communicate()
        original_wait_for = asyncio.wait_for

        call_count = [0]

        async def mock_wait_for(coro, timeout):
            call_count[0] += 1
            # Raise on the first call (the communicate() call inside run_git)
            if call_count[0] == 1:
                # Must still await the coro to avoid ResourceWarning
                import asyncio as _asyncio
                task = _asyncio.ensure_future(coro)
                task.cancel()
                try:
                    await task
                except _asyncio.CancelledError:
                    pass
                raise _asyncio.TimeoutError()
            return await original_wait_for(coro, timeout)

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "asyncio.wait_for", side_effect=mock_wait_for
        ):
            return await git_dashboard.run_git(tmp_path, "rev-parse", "HEAD")

    stdout, stderr, rc = run(_run())
    assert stdout == "", f"Expected empty stdout on timeout, got {stdout!r}"
    assert stderr == "timeout", f"Expected 'timeout' in stderr sentinel, got {stderr!r}"
    assert rc == -1, f"Expected rc=-1 on timeout, got {rc}"


# ─────────────────────────────────────────────────────────────────────────────
# 12. Filenames with spaces in git porcelain output (gap 6 from 23A hardening)
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_porcelain_status_quoted_filename_with_spaces():
    """parse_porcelain_status correctly counts lines with quoted filenames containing spaces.

    git --porcelain=v1 quotes filenames with special characters (spaces, unicode)
    as "my file with spaces.py". The parser classifies based on XY prefix only
    and must not fail or under-count when filenames are quoted.
    """
    # Real git porcelain v1 output with quoted filenames (spaces trigger quoting)
    output = (
        ' M "src/my module/app.py"\n'       # worktree modified, not staged
        'A  "tests/test my feature.py"\n'   # staged new file
        '?? "docs/release notes.md"\n'      # untracked
        '?? "README copy.md"\n'             # untracked with space
    )
    result = git_dashboard.parse_porcelain_status(output)

    assert result["modified_count"] == 1, f"Expected 1 modified, got {result['modified_count']}"
    assert result["staged_count"] == 1, f"Expected 1 staged, got {result['staged_count']}"
    assert result["untracked_count"] == 2, f"Expected 2 untracked, got {result['untracked_count']}"
    assert result["has_uncommitted"] is True
