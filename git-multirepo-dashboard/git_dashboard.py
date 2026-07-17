#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastapi",
#     "uvicorn[standard]",
#     "aiosqlite",
#     "packaging",
#     "pydantic",
# ]
# ///
"""Git Fleet — multi-repo git dashboard.

Usage:
    ./git_dashboard.py [--port N] [--no-browser] [--scan PATH]
"""

# ── stdlib imports ────────────────────────────────────────────────────────────
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import shutil
import socket
import signal
import argparse
import sqlite3
import subprocess
import tomllib
import urllib.request
import webbrowser
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from pathlib import Path
from threading import Timer
from typing import Literal

try:
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_PORT = 8300
VERSION = "0.1.0"

# Populated by build_tools_dict() during preflight; global so /api/status can
# return it without re-running which() on every request.
TOOLS: dict = {}

logger = logging.getLogger("git_dashboard")


def raise_fd_limit(minimum: int = 1024) -> None:
    """Raise the soft file descriptor limit on POSIX when the OS allows it."""
    if resource is None:
        return
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(max(soft, minimum), hard)
        if target > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except (OSError, ValueError):
        pass


raise_fd_limit()


# ── Runtime paths ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuntimePaths:
    home: Path
    db_path: Path


def build_runtime_paths() -> RuntimePaths:
    override = os.environ.get("GIT_DASHBOARD_HOME")
    home = Path(override).expanduser() if override else Path.home() / ".git_dashboard"
    db_path = Path(os.environ["GIT_DASHBOARD_DB"]) if "GIT_DASHBOARD_DB" in os.environ else home / "dashboard.db"
    return RuntimePaths(
        home=home,
        db_path=db_path,
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="git_dashboard",
        description="Git Fleet — multi-repo git dashboard",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        metavar="N",
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Skip opening a browser tab on startup",
    )
    parser.add_argument(
        "--scan",
        metavar="PATH",
        help="Register and scan a directory on startup",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Accepted for backward compatibility; currently a no-op",
    )
    return parser.parse_args(argv)


def testing_mode_enabled() -> bool:
    value = os.environ.get("UTILITIES_TESTING", "")
    return value.lower() not in {"", "0", "false", "no"}


RUNTIME_PATHS = build_runtime_paths()
DATA_DIR = RUNTIME_PATHS.home
DB_PATH = RUNTIME_PATHS.db_path


# ── Third-party imports ───────────────────────────────────────────────────────
import aiosqlite                     # noqa: E402
from fastapi import Body, Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, Response, StreamingResponse  # noqa: E402
from pydantic import BaseModel       # noqa: E402
import uvicorn                       # noqa: E402


# ── Preflight checks ──────────────────────────────────────────────────────────

def check_python_version() -> None:
    """Hard-fail if Python < 3.12, matching the launcher metadata."""
    if sys.version_info < (3, 12):
        print(
            f"Error: Python 3.12+ required. Found {sys.version}. "
            "Install from python.org.",
            file=sys.stderr,
        )
        sys.exit(1)


def check_git() -> None:
    """Hard-fail if git is not in PATH."""
    if shutil.which("git") is None:
        print(
            "Error: git not found in PATH. Install from https://git-scm.com/",
            file=sys.stderr,
        )
        sys.exit(1)


def build_tools_dict() -> dict:
    """Return a dict mapping tool names to their PATH location (or None)."""
    tools: dict = {}

    # Primary ecosystem tools — always checked
    for name, cmd in [
        ("npm", "npm"),
        ("go", "go"),
        ("cargo", "cargo"),
        ("bundle", "bundle"),
        ("composer", "composer"),
    ]:
        tools[name] = shutil.which(cmd)

    # Conditional tools — only checked when the parent tool is present
    tools["govulncheck"] = shutil.which("govulncheck") if tools["go"] else None
    tools["cargo_audit"] = shutil.which("cargo-audit") if tools["cargo"] else None
    tools["cargo_outdated"] = shutil.which("cargo-outdated") if tools["cargo"] else None
    tools["bundler_audit"] = shutil.which("bundler-audit") if tools["bundle"] else None

    # pip_audit: may live inside the venv; check unconditionally
    tools["pip_audit"] = shutil.which("pip-audit")

    return tools


def check_ecosystem_tools(tools: dict) -> None:
    """Hard-fail if no ecosystem dependency tools are found at all.

    Ecosystem tools: npm, go, cargo, bundle, composer, pip_audit.
    """
    ecosystem_keys = ["npm", "go", "cargo", "bundle", "composer", "pip_audit"]
    if not any(tools.get(k) for k in ecosystem_keys):
        print(
            "\nError: No dependency tools found. The dashboard requires at least one "
            "ecosystem tool to be useful. Install one or more of the tools listed "
            "above and try again.",
            file=sys.stderr,
        )
        sys.exit(1)


def run_preflight() -> None:
    """Run all preflight checks. Mutates the module-level TOOLS dict.

    Only hard-fails if git is missing or no ecosystem tools are found at all.
    Missing individual tools are handled per-repo at scan time.
    """
    global TOOLS

    check_python_version()
    check_git()

    TOOLS = build_tools_dict()

    # Hard-fail if no ecosystem tools at all (--yes does not override)
    check_ecosystem_tools(TOOLS)


# ── SQLite Schema ─────────────────────────────────────────────────────────────

_SCHEMA_SQL = """\
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS repositories (
  id                  TEXT PRIMARY KEY,
  name                TEXT NOT NULL,
  path                TEXT NOT NULL UNIQUE,
  default_branch      TEXT DEFAULT 'main',
  runtime             TEXT,
  added_at            TEXT NOT NULL,
  last_quick_scan_at  TEXT,
  last_full_scan_at   TEXT
);

CREATE TABLE IF NOT EXISTS daily_stats (
  repo_id        TEXT    NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  date           TEXT    NOT NULL,
  commits        INTEGER DEFAULT 0,
  insertions     INTEGER DEFAULT 0,
  deletions      INTEGER DEFAULT 0,
  files_changed  INTEGER DEFAULT 0,
  PRIMARY KEY (repo_id, date)
);

CREATE TABLE IF NOT EXISTS branches (
  repo_id           TEXT    NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  name              TEXT    NOT NULL,
  last_commit_date  TEXT,
  is_default        BOOLEAN DEFAULT FALSE,
  is_stale          BOOLEAN DEFAULT FALSE,
  PRIMARY KEY (repo_id, name)
);

CREATE TABLE IF NOT EXISTS dependencies (
  repo_id          TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  manager          TEXT NOT NULL,
  name             TEXT NOT NULL,
  current_version  TEXT,
  wanted_version   TEXT,
  latest_version   TEXT,
  severity         TEXT DEFAULT 'ok',
  advisory_id      TEXT,
  checked_at       TEXT,
  source_path      TEXT DEFAULT '',
  PRIMARY KEY (repo_id, manager, name)
);

CREATE TABLE IF NOT EXISTS working_state (
  repo_id              TEXT PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
  has_uncommitted      BOOLEAN DEFAULT FALSE,
  modified_count       INTEGER DEFAULT 0,
  untracked_count      INTEGER DEFAULT 0,
  staged_count         INTEGER DEFAULT 0,
  current_branch       TEXT,
  last_commit_hash     TEXT,
  last_commit_message  TEXT,
  last_commit_date     TEXT,
  checked_at           TEXT,
  scan_error           TEXT DEFAULT NULL,
  dep_check_error      BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS scan_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_type       TEXT NOT NULL,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  repos_scanned   INTEGER DEFAULT 0,
  status          TEXT DEFAULT 'running'
);
"""


def init_schema(db_path: Path) -> None:
    """Create all tables (idempotent) and enable WAL mode.

    Uses synchronous sqlite3 — called once at startup before uvicorn starts.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


_MIGRATION_SQL = [
    "ALTER TABLE working_state ADD COLUMN scan_error TEXT DEFAULT NULL",
    "ALTER TABLE working_state ADD COLUMN dep_check_error BOOLEAN DEFAULT FALSE",
    "ALTER TABLE dependencies ADD COLUMN source_path TEXT DEFAULT ''",
]


def run_migrations(db_path: Path) -> None:
    """Add new columns to working_state (idempotent — safe to run multiple times)."""
    conn = sqlite3.connect(str(db_path))
    try:
        for sql in _MIGRATION_SQL:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
    finally:
        conn.close()


# ── Git Quick Scan ────────────────────────────────────────────────────────────

async def run_git(repo_path, *args: str, timeout: float = 30.0) -> tuple:
    """Run a git command and return (stdout, stderr, returncode).

    Always uses asyncio.create_subprocess_exec (never shell=True).
    Decodes output with errors='replace' to handle non-UTF8 commit messages.
    On timeout, kills the process and returns ("", "timeout", -1).
    """
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_path), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return ("", "timeout", -1)
    return (
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
        proc.returncode,
    )


async def is_valid_repo(repo_path) -> bool:
    """Return True if repo_path is inside a git work tree, False otherwise."""
    try:
        _, _, rc = await run_git(repo_path, "rev-parse", "--is-inside-work-tree")
        return rc == 0
    except Exception:
        return False


def parse_porcelain_status(output: str) -> dict:
    """Parse 'git status --porcelain=v1' output into working-tree counts.

    Each line is 'XY filename' where:
      X = index (staging area) status
      Y = worktree status
      '??' = untracked

    Rules:
      - X not in (' ', '?') → staged_count += 1
      - Y == 'M'             → modified_count += 1
      - XY == '??'           → untracked_count += 1
      - any non-empty output → has_uncommitted = True
    """
    modified_count = 0
    untracked_count = 0
    staged_count = 0
    has_uncommitted = False

    for line in output.splitlines():
        if len(line) < 2:
            continue
        has_uncommitted = True
        x = line[0]
        y = line[1]
        if x == "?" and y == "?":
            untracked_count += 1
        else:
            if x not in (" ", "?"):
                staged_count += 1
            if y == "M":
                modified_count += 1

    return {
        "modified_count": modified_count,
        "untracked_count": untracked_count,
        "staged_count": staged_count,
        "has_uncommitted": has_uncommitted,
    }


def parse_last_commit(output: str) -> dict:
    """Parse 'git log -1 --format=%H%x00%aI%x00%s' output.

    Returns a dict with hash, date, message — all None if output is empty
    (repo has zero commits).
    """
    if not output:
        return {"hash": None, "date": None, "message": None}
    parts = output.split("\x00", 2)
    return {
        "hash": parts[0] if len(parts) > 0 else None,
        "date": parts[1] if len(parts) > 1 else None,
        "message": parts[2] if len(parts) > 2 else None,
    }


async def get_current_branch(repo_path) -> str | None:
    """Return the current branch name, or None if repo has no commits."""
    stdout, _, rc = await run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return None
    # "HEAD" means detached or empty repo
    if stdout == "HEAD":
        return None
    return stdout or None


async def quick_scan_repo(repo_path) -> dict:
    """Run the 4-command quick scan for a single repo.

    Returns a dict with all fields needed for working_state:
      has_uncommitted, modified_count, untracked_count, staged_count,
      current_branch, last_commit_hash, last_commit_date, last_commit_message.

    Runs commands sequentially (they're fast; parallelism across repos is in packet 03).
    """
    repo_path = str(repo_path)

    # 1. Status
    status_out, _, _ = await run_git(repo_path, "status", "--porcelain=v1")
    status = parse_porcelain_status(status_out)

    # 2. Last commit
    log_out, _, log_rc = await run_git(
        repo_path, "log", "-1", "--format=%H%x00%aI%x00%s"
    )
    # rc 128 means empty repo (no commits); handle gracefully
    commit = parse_last_commit(log_out if log_rc == 0 else "")

    # 3. Current branch
    branch = await get_current_branch(repo_path)

    return {
        "has_uncommitted": status["has_uncommitted"],
        "modified_count": status["modified_count"],
        "untracked_count": status["untracked_count"],
        "staged_count": status["staged_count"],
        "current_branch": branch,
        "last_commit_hash": commit["hash"],
        "last_commit_date": commit["date"],
        "last_commit_message": commit["message"],
    }


async def upsert_working_state(db, repo_id: str, data: dict) -> None:
    """Write quick-scan results to working_state table.

    Uses ON CONFLICT DO UPDATE so that scan_error and dep_check_error columns
    (written by run_fleet_scan / run_dep_scan_for_repo) are preserved across
    quick scans.
    """
    await db.execute(
        """
        INSERT INTO working_state
          (repo_id, has_uncommitted, modified_count, untracked_count,
           staged_count, current_branch, last_commit_hash,
           last_commit_message, last_commit_date, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo_id) DO UPDATE SET
          has_uncommitted    = excluded.has_uncommitted,
          modified_count     = excluded.modified_count,
          untracked_count    = excluded.untracked_count,
          staged_count       = excluded.staged_count,
          current_branch     = excluded.current_branch,
          last_commit_hash   = excluded.last_commit_hash,
          last_commit_message = excluded.last_commit_message,
          last_commit_date   = excluded.last_commit_date,
          checked_at         = excluded.checked_at
        """,
        (
            repo_id,
            data["has_uncommitted"],
            data["modified_count"],
            data["untracked_count"],
            data["staged_count"],
            data["current_branch"],
            data["last_commit_hash"],
            data["last_commit_message"],
            data["last_commit_date"],
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    await db.commit()


# ── Fleet Quick Scan ──────────────────────────────────────────────────────────

async def scan_fleet_quick(db) -> list:
    """Quick-scan all registered repos in parallel (semaphore=8), upsert working_state.

    Repos whose disk paths no longer exist are included with path_exists=False and
    null working-state fields (not silently skipped).
    Returns a list of dicts containing repo metadata + quick-scan data.
    """
    cursor = await db.execute(
        "SELECT id, name, path, runtime, default_branch FROM repositories"
    )
    rows = await cursor.fetchall()
    if not rows:
        return []

    sem = asyncio.Semaphore(8)

    async def scan_one(repo_row):
        repo_id, name, path, runtime, default_branch = repo_row
        async with sem:
            if not Path(path).is_dir():
                return {
                    "id": repo_id,
                    "name": name,
                    "path": path,
                    "runtime": runtime,
                    "default_branch": default_branch,
                    "path_exists": False,
                    "has_uncommitted": False,
                    "modified_count": 0,
                    "untracked_count": 0,
                    "staged_count": 0,
                    "current_branch": None,
                    "last_commit_hash": None,
                    "last_commit_message": None,
                    "last_commit_date": None,
                }
            data = await quick_scan_repo(path)
            await upsert_working_state(db, repo_id, data)
            return {
                "id": repo_id,
                "name": name,
                "path": path,
                "runtime": runtime,
                "default_branch": default_branch,
                "path_exists": True,
                **data,
            }

    results = await asyncio.gather(*(scan_one(r) for r in rows))
    return list(results)


# ── Git Full History Scan (packet 06) ─────────────────────────────────────────

_SHORTSTAT_RE = re.compile(
    r'(\d+) files? changed'
    r'(?:, (\d+) insertions?\(\+\))?'
    r'(?:, (\d+) deletions?\(-\))?'
)


def parse_git_log(output: str) -> list:
    """Parse 'git log --all --format=%H%x00%aI%x00%an%x00%s --shortstat' output.

    Each commit produces a dict with:
      hash, date, author, subject, insertions, deletions, files_changed.

    Merge commits (no shortstat) get 0 for numeric fields.
    """
    if not output:
        return []

    commits = []
    pending = None  # dict for the commit whose shortstat we are waiting for

    for line in output.splitlines():
        if "\x00" in line:
            # New format line — flush any pending commit first (it had no shortstat)
            if pending is not None:
                commits.append(pending)
            parts = line.split("\x00", 3)
            pending = {
                "hash": parts[0] if len(parts) > 0 else "",
                "date": parts[1] if len(parts) > 1 else "",
                "author": parts[2] if len(parts) > 2 else "",
                "subject": parts[3] if len(parts) > 3 else "",
                "insertions": 0,
                "deletions": 0,
                "files_changed": 0,
            }
        elif pending is not None:
            m = _SHORTSTAT_RE.search(line)
            if m:
                pending["files_changed"] = int(m.group(1))
                pending["insertions"] = int(m.group(2)) if m.group(2) else 0
                pending["deletions"] = int(m.group(3)) if m.group(3) else 0
                commits.append(pending)
                pending = None
            # blank lines between format line and shortstat are skipped silently

    # Flush trailing commit with no shortstat (e.g., merge commit at end of output)
    if pending is not None:
        commits.append(pending)

    return commits


def aggregate_daily_stats(commits: list) -> dict:
    """Group commits by YYYY-MM-DD and sum commits, insertions, deletions, files_changed."""
    daily = {}
    for c in commits:
        day = c["date"][:10]  # YYYY-MM-DD from ISO 8601 (safe regardless of timezone offset)
        if day not in daily:
            daily[day] = {"commits": 0, "insertions": 0, "deletions": 0, "files_changed": 0}
        daily[day]["commits"] += 1
        daily[day]["insertions"] += c["insertions"]
        daily[day]["deletions"] += c["deletions"]
        daily[day]["files_changed"] += c["files_changed"]
    return daily


async def scan_full_history(repo_path: str, since: str | None = None) -> list:
    """Run git log --all --shortstat for repo_path and return parsed commits.

    When since is provided, appends --after={since} for incremental scanning.
    """
    cmd = [
        "log",
        "--all",
        "--format=%H%x00%aI%x00%an%x00%s",
        "--shortstat",
    ]
    if since is not None:
        cmd.append(f"--after={since}")

    stdout, _stderr, _rc = await run_git(repo_path, *cmd)
    return parse_git_log(stdout)


async def upsert_daily_stats(db, repo_id: str, daily_data: dict) -> None:
    """Write aggregated daily stats to daily_stats table using INSERT OR REPLACE.

    All rows are written in a single transaction to prevent partial writes.
    """
    if not daily_data:
        return
    await db.executemany(
        """
        INSERT OR REPLACE INTO daily_stats (repo_id, date, commits, insertions, deletions, files_changed)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (repo_id, date, v["commits"], v["insertions"], v["deletions"], v["files_changed"])
            for date, v in daily_data.items()
        ],
    )
    await db.commit()


async def compute_sparklines(db) -> dict:
    """Bulk-compute 13-week commit sparklines for all repos.

    Returns a dict mapping repo_id to a list of 13 integers (index 0 = oldest week).
    Repos with no data in the 91-day window are absent from the dict.
    """
    import datetime as _dt
    today = _dt.date.today()
    start = today - _dt.timedelta(days=90)  # inclusive 91-day window

    cursor = await db.execute(
        "SELECT repo_id, date, commits FROM daily_stats WHERE date >= ?",
        (start.isoformat(),),
    )
    rows = await cursor.fetchall()

    sparklines: dict = {}
    for row in rows:
        repo_id, date_str, commits = row[0], row[1], row[2]
        d = _dt.date.fromisoformat(date_str)
        week_idx = min((d - start).days // 7, 12)
        if week_idx < 0:
            continue
        if repo_id not in sparklines:
            sparklines[repo_id] = [0] * 13
        sparklines[repo_id][week_idx] += int(commits)

    return sparklines


async def run_full_history_scan(db, repo_id: str, repo_path: str) -> int:
    """Orchestrate a full history scan for one repo.

    Reads last_full_scan_at from DB (used as --after for incremental scan),
    runs scan_full_history, aggregates, upserts daily_stats, and updates
    last_full_scan_at. Returns count of commits parsed.
    """
    cursor = await db.execute(
        "SELECT last_full_scan_at FROM repositories WHERE id = ?",
        (repo_id,),
    )
    row = await cursor.fetchone()
    since = row[0] if row else None

    commits = await scan_full_history(repo_path, since=since)
    daily_data = aggregate_daily_stats(commits)
    await upsert_daily_stats(db, repo_id, daily_data)

    await db.execute(
        "UPDATE repositories SET last_full_scan_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), repo_id),
    )
    await db.commit()

    return len(commits)


# ── Branch Scan ───────────────────────────────────────────────────────────────

STALE_THRESHOLD_DAYS = 30


def _is_stale(commit_date_str: str | None) -> bool:
    """Return True if commit_date_str is more than STALE_THRESHOLD_DAYS ago (or missing/invalid)."""
    if not commit_date_str:
        return True  # unknown date → treat as stale
    try:
        commit_date = datetime.fromisoformat(commit_date_str)
        cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_THRESHOLD_DAYS)
        return commit_date < cutoff
    except (ValueError, TypeError):
        return True


def parse_branches(output: str, default_branch: str) -> list[dict]:
    """Parse output from git branch --format='%(refname:short)%09%(committerdate:iso-strict)'.

    Each line produces a dict with:
      name, last_commit_date (ISO 8601 or None), is_default, is_stale.

    Empty input returns an empty list. Uses tab delimiter (%09) which git
    correctly interprets as a real tab character.
    """
    if not output:
        return []

    branches = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # Each line is: name<TAB>date (tab-separated)
        if "\t" in line:
            name, date_str = line.split("\t", 1)
            date_str = date_str.strip() or None
        else:
            # No tab — branch has no committer date (orphan branch or git quirk)
            name = line
            date_str = None

        name = name.strip()
        if not name:
            continue

        is_default = name == default_branch
        branches.append({
            "name": name,
            "last_commit_date": date_str,
            "is_default": is_default,
            "is_stale": False if is_default else _is_stale(date_str),
        })

    return branches


async def scan_branches(repo_path: str, default_branch: str) -> list[dict]:
    """Run git branch command and return parsed branch list.

    Uses %(refname:short)%09%(committerdate:iso-strict) format with tab
    delimiter. Git interprets %09 as a real tab character.
    """
    stdout, _stderr, _rc = await run_git(
        repo_path,
        "branch",
        "--format=%(refname:short)%09%(committerdate:iso-strict)",
    )
    return parse_branches(stdout, default_branch)


async def upsert_branches(db, repo_id: str, branches: list[dict]) -> None:
    """Write branch data to branches table using DELETE+INSERT in a single transaction.

    Handles branch renames and deletions by fully replacing the set for the repo.
    INSERT OR REPLACE is not used because it would not remove branches that no
    longer exist in git.
    """
    await db.execute("DELETE FROM branches WHERE repo_id = ?", (repo_id,))
    if branches:
        await db.executemany(
            "INSERT INTO branches (repo_id, name, last_commit_date, is_default, is_stale) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (repo_id, b["name"], b["last_commit_date"], b["is_default"], b["is_stale"])
                for b in branches
            ],
        )
    await db.commit()


async def run_branch_scan(db, repo_id: str, repo_path: str) -> int:
    """Orchestrate a single-repo branch scan.

    Reads default_branch from the repositories table, calls scan_branches,
    upserts the result, and returns the count of branches parsed.
    """
    cursor = await db.execute(
        "SELECT default_branch FROM repositories WHERE id = ?",
        (repo_id,),
    )
    row = await cursor.fetchone()
    default_branch = row[0] if row else "main"

    branches = await scan_branches(repo_path, default_branch)
    await upsert_branches(db, repo_id, branches)
    return len(branches)


# ── Full Scan Orchestration & SSE (packet 08) ──────────────────────────────────

# Module-level scan state
_active_scan_id: int | None = None       # Non-None while a scan is running
_scan_queues: dict = {}                  # scan_id -> asyncio.Queue (SSE bridge)
_scan_task = None                        # asyncio.Task reference (prevents GC)


async def emit_scan_progress(scan_id: int, event: dict) -> None:
    """Put a progress event onto the SSE queue for scan_id, if a listener exists."""
    q = _scan_queues.get(scan_id)
    if q:
        await q.put(event)


async def run_dep_scan_for_repo(db, repo_id: str, repo_path: str) -> None:
    """Detect, parse, and health-check deps for one repo, then persist to DB."""
    repo_path_obj = Path(repo_path)

    # 1. Parse raw deps from manifest files
    raw_deps = parse_deps_for_repo(repo_path_obj)
    if not raw_deps:
        # Clear any stale deps if the manifest was removed.
        await db.execute("DELETE FROM dependencies WHERE repo_id = ?", (repo_id,))
        await db.commit()
        return

    # Determine which ecosystems this repo actually uses (from parsed deps)
    detected_managers = {d.get("manager", "") for d in raw_deps}

    # Map manager → tools needed for full analysis
    _MANAGER_TOOL_MAP = {
        "pip":      [("pip_audit", "pip-audit", "Python vulnerability scanning")],
        "npm":      [("npm", "npm", "Node.js dependency checks")],
        "gomod":    [("go", "go", "Go dependency checks"),
                     ("govulncheck", "govulncheck", "Go vulnerability scanning")],
        "cargo":    [("cargo", "cargo", "Rust dependency checks"),
                     ("cargo_outdated", "cargo-outdated", "Rust outdated checks"),
                     ("cargo_audit", "cargo-audit", "Rust vulnerability scanning")],
        "bundler":  [("bundle", "bundle", "Ruby dependency checks"),
                     ("bundler_audit", "bundler-audit", "Ruby vulnerability scanning")],
        "composer": [("composer", "composer", "PHP dependency checks")],
    }

    for mgr in detected_managers:
        for tool_key, display_name, description in _MANAGER_TOOL_MAP.get(mgr, []):
            if not TOOLS.get(tool_key):
                logger.info(
                    "Missing %s while scanning %s dependencies for %s (%s)",
                    display_name,
                    mgr,
                    repo_id,
                    description,
                )

    # 2. Route through ecosystem health checkers (each operates on the full list;
    #    only enriches deps matching its ecosystem)
    enriched = list(raw_deps)
    any_error = False
    try:
        enriched = check_python_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Python dep check failed for %s: %s", repo_id, exc)
        any_error = True
    try:
        enriched = check_node_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Node dep check failed for %s: %s", repo_id, exc)
        any_error = True
    try:
        enriched = check_go_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Go dep check failed for %s: %s", repo_id, exc)
        any_error = True
    try:
        enriched = check_rust_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Rust dep check failed for %s: %s", repo_id, exc)
        any_error = True
    try:
        enriched = check_ruby_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Ruby dep check failed for %s: %s", repo_id, exc)
        any_error = True
    try:
        enriched = check_php_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("PHP dep check failed for %s: %s", repo_id, exc)
        any_error = True

    # Update dep_check_error in working_state.
    await db.execute(
        "INSERT INTO working_state (repo_id, dep_check_error) VALUES (?, ?) "
        "ON CONFLICT(repo_id) DO UPDATE SET dep_check_error = excluded.dep_check_error",
        (repo_id, any_error),
    )

    # 3. Upsert into dependencies table
    for dep in enriched:
        await db.execute(
            """INSERT OR REPLACE INTO dependencies
               (repo_id, manager, name, current_version, wanted_version,
                latest_version, severity, advisory_id, checked_at, source_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                repo_id,
                dep.get("manager", ""),
                dep.get("name", ""),
                dep.get("current_version"),
                dep.get("wanted_version"),
                dep.get("latest_version"),
                dep.get("severity", "ok"),
                dep.get("advisory_id"),
                dep.get("checked_at"),
                dep.get("source_path", ""),
            ),
        )

    # 4. Delete stale deps (in DB but no longer in manifest)
    current_keys = {(dep.get("manager", ""), dep.get("name", "")) for dep in enriched}
    cursor = await db.execute(
        "SELECT manager, name FROM dependencies WHERE repo_id = ?", (repo_id,)
    )
    db_keys = await cursor.fetchall()
    for manager, name in db_keys:
        if (manager, name) not in current_keys:
            await db.execute(
                "DELETE FROM dependencies WHERE repo_id = ? AND manager = ? AND name = ?",
                (repo_id, manager, name),
            )

    await db.commit()


async def run_fleet_scan(scan_id: int, scan_type: str) -> None:
    """Background task: iterate all repos sequentially and scan each one.

    For scan_type="full": runs run_full_history_scan, run_branch_scan, and
        run_dep_scan_for_repo per repo.
    For scan_type="deps": runs run_dep_scan_for_repo per repo.

    Emits SSE progress events after each repo. Updates scan_log throughout.
    Clears _active_scan_id in finally, even on crash.
    """
    global _active_scan_id
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            if scan_type == "deps":
                # Iterate all repos sequentially, running dep scans only
                cursor = await db.execute("SELECT id, name, path FROM repositories")
                repos = await cursor.fetchall()
                total = len(repos)
                scanned = 0

                await emit_scan_progress(scan_id, {
                    "progress": 0,
                    "total": total,
                    "status": "scanning",
                })

                for i, (repo_id, name, repo_path) in enumerate(repos):
                    if not Path(repo_path).is_dir():
                        logger.warning("Skipping dep scan %s — path not found: %s", name, repo_path)
                        await emit_scan_progress(scan_id, {
                            "repo": name, "step": "skipped",
                            "progress": i + 1, "total": total, "status": "scanning",
                        })
                        continue

                    try:
                        await run_dep_scan_for_repo(db, repo_id, repo_path)
                        scanned += 1
                    except Exception as exc:
                        logger.error("Dep scan failed for %s: %s", name, exc)

                    await emit_scan_progress(scan_id, {
                        "repo": name,
                        "step": "deps",
                        "progress": i + 1,
                        "total": total,
                        "status": "scanning",
                    })
                    await db.execute(
                        "UPDATE scan_log SET repos_scanned = ? WHERE id = ?",
                        (scanned, scan_id),
                    )
                    await db.commit()

                # Determine final status
                if total == 0 or scanned > 0:
                    status = "completed"
                else:
                    status = "failed"

                finished_at = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    "UPDATE scan_log SET status = ?, finished_at = ?, repos_scanned = ? WHERE id = ?",
                    (status, finished_at, scanned, scan_id),
                )
                await db.commit()

                await emit_scan_progress(scan_id, {
                    "progress": total,
                    "total": total,
                    "status": status,
                })
                return

            # type == "full": iterate repos sequentially
            cursor = await db.execute("SELECT id, name, path FROM repositories")
            repos = await cursor.fetchall()
            total = len(repos)
            scanned = 0

            # Emit initial total so the progress bar can show "0 / N"
            # Queue is pre-created by POST handler, so events are buffered immediately.
            await emit_scan_progress(scan_id, {
                "progress": 0,
                "total": total,
                "status": "scanning",
            })

            for i, (repo_id, name, repo_path) in enumerate(repos):
                # Skip repos whose paths no longer exist on disk
                if not Path(repo_path).is_dir():
                    logger.warning("Skipping %s — path does not exist: %s", name, repo_path)
                    await db.execute(
                        "INSERT INTO working_state (repo_id, scan_error) VALUES (?, ?) "
                        "ON CONFLICT(repo_id) DO UPDATE SET scan_error = excluded.scan_error",
                        (repo_id, f"Path not found: {repo_path}"),
                    )
                    await db.commit()
                    await emit_scan_progress(scan_id, {
                        "repo": name,
                        "step": "skipped",
                        "progress": i + 1,
                        "total": total,
                        "status": "scanning",
                    })
                    continue

                try:
                    await run_full_history_scan(db, repo_id, repo_path)
                    await run_branch_scan(db, repo_id, repo_path)
                    await run_dep_scan_for_repo(db, repo_id, repo_path)
                    # Clear scan_error on success
                    await db.execute(
                        "INSERT INTO working_state (repo_id, scan_error) VALUES (?, NULL) "
                        "ON CONFLICT(repo_id) DO UPDATE SET scan_error = NULL",
                        (repo_id,),
                    )
                    scanned += 1
                except Exception as exc:
                    logger.error("Scan failed for %s: %s", name, exc)
                    # Set scan_error on failure
                    await db.execute(
                        "INSERT INTO working_state (repo_id, scan_error) VALUES (?, ?) "
                        "ON CONFLICT(repo_id) DO UPDATE SET scan_error = excluded.scan_error",
                        (repo_id, str(exc)),
                    )
                    await db.commit()

                await emit_scan_progress(scan_id, {
                    "repo": name,
                    "step": "deps",
                    "progress": i + 1,
                    "total": total,
                    "status": "scanning",
                })
                await db.execute(
                    "UPDATE scan_log SET repos_scanned = ? WHERE id = ?",
                    (scanned, scan_id),
                )
                await db.commit()

            # Determine final status
            # Empty fleet or ≥1 success → completed; all repos failed → failed
            if total == 0 or scanned > 0:
                status = "completed"
            else:
                status = "failed"

            finished_at = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "UPDATE scan_log SET status = ?, finished_at = ?, repos_scanned = ? WHERE id = ?",
                (status, finished_at, scanned, scan_id),
            )
            await db.commit()

            await emit_scan_progress(scan_id, {
                "progress": total,
                "total": total,
                "status": status,
            })
    finally:
        _active_scan_id = None


# ── Repo Discovery & Registration ─────────────────────────────────────────────

def generate_repo_id(absolute_path: str) -> str:
    """Return a 16-char hex ID derived from sha256 of the absolute path."""
    return hashlib.sha256(absolute_path.encode()).hexdigest()[:16]


def detect_runtime(repo_path: Path) -> str:
    """Classify the primary language/runtime for a repo by detecting ecosystem files.

    Checks files in priority order per spec section 3.4. Returns "mixed" when
    multiple language ecosystems are detected (docker does not count toward mixed).
    """
    # Priority 1–9: language/ecosystem files
    ecosystem_checks = [
        (["pyproject.toml"], "python"),
        (["requirements.txt"], "python"),
        (["setup.py", "setup.cfg"], "python"),
        (["package.json"], "node"),
        (["go.mod"], "go"),
        (["Cargo.toml"], "rust"),
        (["Gemfile"], "ruby"),
        (["composer.json"], "php"),
        (["Dockerfile", "docker-compose.yml", "docker-compose.yaml"], "docker"),
    ]

    found: set = set()
    try:
        dir_files = {p.name.lower() for p in repo_path.iterdir() if p.is_file()}
    except (OSError, PermissionError):
        return "unknown"

    for files, runtime in ecosystem_checks:
        for f in files:
            if f.lower() in dir_files:
                found.add(runtime)
                break

    if len(found) == 0:
        # Priority 10: shell-heavy (majority of files have shell extensions)
        shell_exts = {".sh", ".zsh", ".bat", ".ps1"}
        try:
            all_files = [p for p in repo_path.iterdir() if p.is_file()]
            if all_files:
                shell_count = sum(1 for f in all_files if f.suffix.lower() in shell_exts)
                if shell_count / len(all_files) > 0.5:
                    return "shell"
        except (OSError, PermissionError):
            pass
        # Priority 11: index.html at root
        if "index.html" in dir_files:
            return "html"
        return "unknown"

    if len(found) == 1:
        return found.pop()

    # Multiple ecosystems detected — filter out docker (it's packaging, not a runtime)
    non_docker = found - {"docker"}
    if not non_docker:
        return "docker"
    if len(non_docker) == 1:
        return non_docker.pop()
    return "mixed"


# ── Dependency Detection & Parsing (packet 12) ────────────────────────────────

# Detection priority table: (filename, manager, runtime)
# Within a runtime, only the highest-priority file is returned.
_DEP_FILE_PRIORITY: list[tuple[str, str, str]] = [
    ("pyproject.toml", "pip",      "python"),
    ("requirements.txt", "pip",    "python"),
    ("package.json",   "npm",      "node"),
    ("go.mod",         "gomod",    "go"),
    ("Cargo.toml",     "cargo",    "rust"),
    ("Gemfile",        "bundler",  "ruby"),
    ("composer.json",  "composer", "php"),
]


# Directories to skip when walking a repo tree for manifest files.
_DEP_WALK_SKIP = {
    ".git", ".venv", "venv", "env", ".env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".tox", "dist", "build", ".eggs",
    "vendor", "third_party", ".bundle",
}

# Maximum directory depth to search for manifest files (0 = root only).
_DEP_WALK_MAX_DEPTH = 3


def detect_dep_files(repo_path: Path) -> list[dict]:
    """Return a list of {file, manager, runtime, dir} for every manifest found.

    Walks the repo tree up to _DEP_WALK_MAX_DEPTH levels deep, skipping
    common vendored/generated directories.  Within a single directory and
    runtime, only the highest-priority manifest is returned (e.g. pyproject.toml
    wins over requirements.txt in the same dir).  Across different directories,
    all manifests are returned so monorepos are fully covered.
    """
    results: list[dict] = []

    dirs_to_walk: list[tuple[Path, int]] = [(repo_path, 0)]
    while dirs_to_walk:
        current_dir, depth = dirs_to_walk.pop()
        try:
            entries = list(current_dir.iterdir())
        except (OSError, PermissionError):
            continue

        dir_files: set[str] = set()
        for entry in entries:
            if entry.is_file():
                dir_files.add(entry.name.lower())
            elif entry.is_dir() and depth < _DEP_WALK_MAX_DEPTH:
                if entry.name not in _DEP_WALK_SKIP and not entry.name.startswith("."):
                    dirs_to_walk.append((entry, depth + 1))

        # Within this directory, apply the priority dedup per-runtime
        seen_runtimes: set[str] = set()
        for filename, manager, runtime in _DEP_FILE_PRIORITY:
            if filename.lower() in dir_files and runtime not in seen_runtimes:
                seen_runtimes.add(runtime)
                results.append({
                    "file": filename,
                    "manager": manager,
                    "runtime": runtime,
                    "dir": current_dir,
                })

    return results


def parse_requirements_txt(file_path: Path, _visited: set[str] | None = None) -> list[dict]:
    """Parse a requirements.txt file and return [{name, version, manager}].

    Handles:
    - Comments and blank lines (skip)
    - -e / --editable (skip)
    - -r / --requirement includes (one level, circular-safe)
    - Other flags (-i, --index-url, etc.) (skip)
    - name==version (exact pin → extract version)
    - name>=version or unpinned (version = None)
    """
    if _visited is None:
        _visited = set()

    resolved = str(file_path.resolve())
    if resolved in _visited:
        return []
    _visited.add(resolved)

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    deps: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-e") or line.startswith("--editable"):
            continue
        if line.startswith("-r") or line.startswith("--requirement"):
            # Extract the included file path
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            include_path = file_path.parent / parts[1].strip()
            deps.extend(parse_requirements_txt(include_path, _visited))
            continue
        if line.startswith("-"):
            # Other flags: -i, --index-url, -f, --find-links, etc.
            continue

        # Package line: may have extras [extra], env markers ; marker
        # Strip environment markers
        pkg_part = line.split(";")[0].strip()
        # Strip inline comments
        pkg_part = pkg_part.split(" #")[0].strip()

        # Match: name[extras]  op  version
        m = re.match(
            r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)"  # package name
            r"(\[[^\]]*\])?"                                   # optional extras
            r"\s*==\s*([^\s,;]+)",                             # == version
            pkg_part,
        )
        if m:
            deps.append({"name": m.group(1), "version": m.group(4), "manager": "pip"})
            continue

        # Unpinned or range constraint — just extract the name
        m2 = re.match(
            r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)(\[[^\]]*\])?",
            pkg_part,
        )
        if m2:
            deps.append({"name": m2.group(1), "version": None, "manager": "pip"})

    return deps


def parse_pyproject_toml(file_path: Path) -> list[dict]:
    """Parse pyproject.toml and return [{name, version, manager}].

    Supports:
    - PEP 621: [project].dependencies  (preferred if both sections exist)
    - Poetry:  [tool.poetry.dependencies]
    """
    try:
        with open(file_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    deps: list[dict] = []

    # PEP 621 takes priority
    project_deps = data.get("project", {}).get("dependencies", None)
    if project_deps is not None:
        for entry in project_deps:
            if not isinstance(entry, str):
                continue
            # Strip markers
            entry = entry.split(";")[0].strip()
            m = re.match(
                r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)(\[[^\]]*\])?"
                r"\s*==\s*([^\s,;]+)",
                entry,
            )
            if m:
                deps.append({"name": m.group(1), "version": m.group(4), "manager": "pip"})
            else:
                m2 = re.match(
                    r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)(\[[^\]]*\])?",
                    entry,
                )
                if m2:
                    deps.append({"name": m2.group(1), "version": None, "manager": "pip"})
        return deps

    # Poetry fallback
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", None)
    if poetry_deps is not None:
        for name, val in poetry_deps.items():
            if isinstance(val, str):
                version = val if val != "*" else None
            elif isinstance(val, dict):
                version = val.get("version") or None
            else:
                version = None
            deps.append({"name": name, "version": version, "manager": "pip"})
        return deps

    return []


def parse_package_json(file_path: Path) -> list[dict]:
    """Parse package.json and return [{name, version, manager}] for all deps."""
    try:
        data = json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    deps: list[dict] = []
    for section in ("dependencies", "devDependencies"):
        section_data = data.get(section, {})
        if not isinstance(section_data, dict):
            continue
        for name, version in section_data.items():
            deps.append({"name": name, "version": version if isinstance(version, str) else None, "manager": "npm"})
    return deps


def parse_go_mod(file_path: Path) -> list[dict]:
    """Parse go.mod and return [{name, version, manager}].

    Handles both require (...) blocks and single-line require statements.
    Indirect deps are included. Strips // indirect comments.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    deps: list[dict] = []
    in_require_block = False

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("require ("):
            in_require_block = True
            continue
        if in_require_block:
            if stripped == ")":
                in_require_block = False
                continue
            # Strip inline comments (e.g., "// indirect")
            stripped = re.sub(r"\s*//.*$", "", stripped).strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                deps.append({"name": parts[0], "version": parts[1], "manager": "gomod"})
            continue

        # Single-line: "require module/path vX.Y.Z"
        m = re.match(r"^require\s+(\S+)\s+(\S+)", stripped)
        if m:
            deps.append({"name": m.group(1), "version": m.group(2), "manager": "gomod"})

    return deps


def parse_cargo_toml(file_path: Path) -> list[dict]:
    """Parse Cargo.toml and return [{name, version, manager}].

    Reads [dependencies] and [dev-dependencies].
    Handles string values ("1.0") and table values ({version = "1.0", ...}).
    """
    try:
        with open(file_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    deps: list[dict] = []
    for section in ("dependencies", "dev-dependencies"):
        section_data = data.get(section, {})
        if not isinstance(section_data, dict):
            continue
        for name, val in section_data.items():
            if isinstance(val, str):
                version = val
            elif isinstance(val, dict):
                version = val.get("version") or None
            else:
                version = None
            deps.append({"name": name, "version": version, "manager": "cargo"})
    return deps


def parse_gemfile(file_path: Path) -> list[dict]:
    """Parse Gemfile and return [{name, version, manager}].

    Matches: gem 'name' and gem 'name', 'version_constraint'
    Also handles double-quoted gem names.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    deps: list[dict] = []
    # Match: gem 'name' or gem 'name', 'version'  (single or double quotes)
    pattern = re.compile(r"""gem\s+['"]([^'"]+)['"]\s*(?:,\s*['"]([^'"]+)['"])?""")
    for m in pattern.finditer(text):
        name = m.group(1)
        version = m.group(2) if m.group(2) else None
        deps.append({"name": name, "version": version, "manager": "bundler"})
    return deps


def parse_composer_json(file_path: Path) -> list[dict]:
    """Parse composer.json and return [{name, version, manager}].

    Reads require and require-dev. Skips php and ext-* platform requirements.
    """
    try:
        data = json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    deps: list[dict] = []
    for section in ("require", "require-dev"):
        section_data = data.get(section, {})
        if not isinstance(section_data, dict):
            continue
        for name, version in section_data.items():
            # Skip platform requirements
            if name == "php" or name.startswith("ext-"):
                continue
            deps.append({
                "name": name,
                "version": version if isinstance(version, str) else None,
                "manager": "composer",
            })
    return deps


def parse_deps_for_repo(repo_path: Path) -> list[dict]:
    """Detect manifest files in repo_path (including subdirectories) and parse them.

    Returns a merged list of {name, version, manager} dicts.
    Walks the repo tree via detect_dep_files(), so monorepos with manifests
    in subdirectories are fully covered.
    """
    manifest_entries = detect_dep_files(repo_path)
    if not manifest_entries:
        return []

    _parser_map = {
        "requirements.txt": parse_requirements_txt,
        "pyproject.toml":   parse_pyproject_toml,
        "package.json":     parse_package_json,
        "go.mod":           parse_go_mod,
        "Cargo.toml":       parse_cargo_toml,
        "Gemfile":          parse_gemfile,
        "composer.json":    parse_composer_json,
    }

    all_deps: list[dict] = []
    seen_dep_keys: set[tuple[str, str]] = set()  # (manager, name) dedup across dirs
    for entry in manifest_entries:
        filename = entry["file"]
        parser = _parser_map.get(filename)
        if parser is None:
            continue
        manifest_dir = entry["dir"]
        file_path = manifest_dir / filename
        # Compute relative path from repo root for display
        try:
            rel_dir = str(manifest_dir.relative_to(repo_path))
        except ValueError:
            rel_dir = str(manifest_dir)
        source = f"{rel_dir}/{filename}" if rel_dir != "." else filename
        try:
            parsed = parser(file_path)
        except Exception as exc:
            logger.warning("Error parsing %s in %s: %s", filename, manifest_dir, exc)
            parsed = []
        for dep in parsed:
            key = (dep.get("manager", ""), dep.get("name", ""))
            if key not in seen_dep_keys:
                seen_dep_keys.add(key)
                dep["source_path"] = source
                all_deps.append(dep)
    return all_deps


# ── Python dependency health (Packet 13) ──────────────────────────────────────

def classify_severity(current: str, latest: str) -> str:
    """Compare two PEP 440 version strings and return a severity label.

    Returns:
        "ok"       — current >= latest (up-to-date or ahead)
        "major"    — different major version (latest has higher major)
        "outdated" — same major, any other version difference
    """
    from packaging.version import parse as parse_version  # noqa: PLC0415

    cur = parse_version(current)
    lat = parse_version(latest)
    if cur >= lat:
        return "ok"
    if cur.major != lat.major:
        return "major"
    return "outdated"


def check_python_outdated(deps: list[dict]) -> list[dict]:
    """Query PyPI JSON API for each pinned pip dep and populate version/severity fields.

    Skips deps where:
      - manager != "pip"
      - version is None
      - version contains range operators (>=, ~=, <, !=, >, ^)

    On any network or parse error the dep is left with severity="ok" and
    latest_version=None (fail-open: don't block the rest of the scan).

    Returns a new list of dicts (input dicts are copied, not mutated in-place).
    """
    _RANGE_OPS = (">=", "<=", "~=", "!=", ">", "<", "^", "*")

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)  # shallow copy; only add new scalar fields
        if d.get("manager") != "pip" or d.get("version") is None:
            result.append(d)
            continue

        ver_str: str = d["version"]

        # Extract bare version from "name==version" or "==version" notation
        if "==" in ver_str:
            ver_str = ver_str.split("==")[-1].strip()

        # Skip range/unpinned specifiers
        if any(op in ver_str for op in _RANGE_OPS):
            result.append(d)
            continue

        name = d["name"]
        latest_version = None
        severity = "ok"
        try:
            url = f"https://pypi.org/pypi/{name}/json"
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
            latest_version = data["info"]["version"]
            severity = classify_severity(ver_str, latest_version)
        except Exception as exc:
            logger.warning("PyPI lookup failed for %s: %s", name, exc)

        d["latest_version"] = latest_version
        d["severity"] = severity
        result.append(d)

    return result


def check_python_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run pip-audit against the repo's requirements.txt (if present) and merge results.

    If pip-audit is not installed (TOOLS["pip_audit"] is None), returns deps unchanged.
    If the repo has no requirements.txt (only pyproject.toml), logs a warning and skips.
    On any subprocess or parse failure, returns deps unchanged (fail-open).

    Vulnerability severity overrides any prior severity (vuln > major > outdated > ok).
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = <first vuln ID>.
    """
    pip_audit = TOOLS.get("pip_audit")
    if not pip_audit:
        return deps

    # pip-audit --requirement only works with requirements.txt-style files
    manifest = repo_path / "requirements.txt"
    if not manifest.exists():
        logger.warning(
            "check_python_vulns: no requirements.txt in %s — skipping vuln check", repo_path
        )
        return deps

    try:
        proc = subprocess.run(
            [pip_audit, "--requirement", str(manifest), "--format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("pip-audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {package_name_lower: first_vuln_id}
    vuln_map: dict[str, str] = {}
    try:
        for entry in raw.get("dependencies", []):
            vuln_list = entry.get("vulns", [])
            if vuln_list:
                vuln_map[entry["name"].lower()] = vuln_list[0]["id"]
    except Exception as exc:
        logger.warning("pip-audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        key = d.get("name", "").lower()
        if key in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[key]
        result.append(d)
    return result


def check_python_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for pip deps in a repo.

    1. Splits deps into pip and non-pip groups.
    2. Runs check_python_outdated on pip deps.
    3. Runs check_python_vulns on pip deps (merges vuln severity).
    4. Stamps required health fields on all pip deps (fills defaults for skipped deps).
    5. Returns merged list (pip enriched + non-pip unchanged).
    """
    if not deps:
        return []

    pip_deps = [d for d in deps if d.get("manager") == "pip"]
    other_deps = [d for d in deps if d.get("manager") != "pip"]

    if not pip_deps:
        return other_deps

    pip_deps = check_python_outdated(pip_deps)
    pip_deps = check_python_vulns(repo_path, pip_deps)

    # Ensure all required fields are present (fill defaults for skipped/unpinned deps)
    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in pip_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── Node dependency health (Packet 14) ────────────────────────────────────────


def check_node_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run npm outdated --json and enrich each npm dep with version/severity fields.

    If npm is not available (TOOLS["npm"] is None), returns deps unchanged.
    Handles npm's non-zero exit code when outdated packages exist (this is normal).
    On any subprocess or JSON parse failure, returns deps unchanged (fail-open).
    """
    npm = TOOLS.get("npm")
    if not npm:
        return deps

    now = datetime.now(timezone.utc).isoformat()

    try:
        proc = subprocess.run(
            [npm, "outdated", "--json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        # npm outdated exits with code 1 when outdated packages exist — this is normal.
        # Only treat as error if stdout is empty/unparseable and returncode is non-zero.
        if not proc.stdout.strip() and proc.returncode != 0:
            logger.warning("npm outdated returned no output for %s (rc=%d)", repo_path, proc.returncode)
            return deps
        outdated_map = json.loads(proc.stdout)
    except subprocess.CalledProcessError as exc:
        logger.warning("npm outdated CalledProcessError for %s: %s", repo_path, exc)
        return deps
    except Exception as exc:
        logger.warning("npm outdated failed for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            d["current_version"] = info.get("current")
            d["wanted_version"] = info.get("wanted")
            d["latest_version"] = info.get("latest")
            current = info.get("current") or ""
            latest = info.get("latest") or ""
            if current and latest:
                d["severity"] = classify_severity(current, latest)
            else:
                d["severity"] = "outdated"
        else:
            # Not in npm outdated output → up to date
            d.setdefault("current_version", d.get("version"))
            d.setdefault("wanted_version", d.get("version"))
            d.setdefault("latest_version", None)
            d["severity"] = "ok"
        d["checked_at"] = now
        result.append(d)

    return result


def check_node_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run npm audit --json and merge vulnerability info into dep dicts.

    If npm is not available (TOOLS["npm"] is None), returns deps unchanged.
    Handles npm's non-zero exit code when vulnerabilities exist (normal behavior).
    If npm audit fails (e.g. missing package-lock.json), returns deps unchanged (fail-open).
    Vulnerability severity overrides any prior severity (vuln > major > outdated > ok).
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = "npm:<name>".
    """
    npm = TOOLS.get("npm")
    if not npm:
        return deps

    try:
        proc = subprocess.run(
            [npm, "audit", "--json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if not proc.stdout.strip():
            logger.warning("npm audit returned no output for %s (rc=%d)", repo_path, proc.returncode)
            return deps
        raw = json.loads(proc.stdout)
    except subprocess.CalledProcessError as exc:
        logger.warning("npm audit CalledProcessError for %s: %s", repo_path, exc)
        return deps
    except Exception as exc:
        logger.warning("npm audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {package_name_lower: True} for vulnerable packages
    vuln_names: set[str] = set()
    try:
        for name in raw.get("vulnerabilities", {}).keys():
            vuln_names.add(name.lower())
    except Exception as exc:
        logger.warning("npm audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name_lower = d.get("name", "").lower()
        if name_lower in vuln_names:
            d["severity"] = "vulnerable"
            d["advisory_id"] = f"npm:{d.get('name', name_lower)}"
        result.append(d)

    return result


def check_node_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for npm deps in a repo.

    1. Filters deps to npm-managed entries.
    2. Runs check_node_outdated on npm deps.
    3. Runs check_node_vulns on npm deps.
    4. Stamps required health fields on all npm deps (fills defaults for skipped deps).
    5. Returns merged list (npm enriched + non-npm unchanged).
    """
    if not deps:
        return []

    npm_deps = [d for d in deps if d.get("manager") == "npm"]
    other_deps = [d for d in deps if d.get("manager") != "npm"]

    if not npm_deps:
        return other_deps

    npm_deps = check_node_outdated(repo_path, npm_deps)
    npm_deps = check_node_vulns(repo_path, npm_deps)

    # Ensure all required fields are present
    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in npm_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── Go dependency health (Packet 15) ──────────────────────────────────────────


def _strip_v(version: str) -> str:
    """Strip leading 'v' from Go-style version strings for packaging.version comparison."""
    return version.lstrip("v") if version else version


def _parse_go_ndjson(stdout: str) -> list[dict]:
    """Parse go list -m -u -json all NDJSON output (one JSON object per line).

    Returns a list of parsed JSON objects.
    """
    decoder = json.JSONDecoder()
    pos = 0
    results: list[dict] = []
    text = stdout.strip()
    while pos < len(text):
        remaining = text[pos:]
        stripped = remaining.lstrip()
        if not stripped:
            break
        obj, end = decoder.raw_decode(stripped)
        results.append(obj)
        pos += (len(remaining) - len(stripped)) + end
    return results


def check_go_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run go list -m -u -json all and enrich gomod deps with version/severity fields.

    If go is not available (TOOLS["go"] is None), returns deps unchanged.
    Parses NDJSON output (one JSON object per line).
    Strips 'v' prefix from Go versions before calling classify_severity().
    On any subprocess or parse failure, returns deps unchanged (fail-open).
    """
    go = TOOLS.get("go")
    if not go:
        return deps

    try:
        proc = subprocess.run(
            [go, "list", "-m", "-u", "-json", "all"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        modules = _parse_go_ndjson(proc.stdout)
    except Exception as exc:
        logger.warning("go list failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {module_path: {"version": str, "update": str|None}}
    mod_map: dict[str, dict] = {}
    for mod in modules:
        path = mod.get("Path", "")
        version = mod.get("Version", "")
        update = mod.get("Update", {})
        update_version = update.get("Version") if update else None
        mod_map[path] = {"version": version, "update": update_version}

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in mod_map:
            info = mod_map[name]
            current = info["version"]
            update_ver = info["update"]
            d["current_version"] = current
            d["wanted_version"] = current  # Go has no "wanted" concept
            if update_ver:
                d["latest_version"] = update_ver
                d["severity"] = classify_severity(_strip_v(current), _strip_v(update_ver))
            else:
                d["latest_version"] = current
                d["severity"] = "ok"
        result.append(d)
    return result


def check_go_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run govulncheck -json ./... and merge vulnerability info into gomod dep dicts.

    If govulncheck is not available (TOOLS["govulncheck"] is None), returns deps unchanged.
    Parses the Vulns array from govulncheck JSON output.
    Vulnerability severity overrides any prior severity.
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = OSV ID.
    """
    govulncheck = TOOLS.get("govulncheck")
    if not govulncheck:
        return deps

    try:
        proc = subprocess.run(
            [govulncheck, "-json", "./..."],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=300,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("govulncheck failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {module_path: osv_id}
    vuln_map: dict[str, str] = {}
    try:
        for vuln in raw.get("Vulns", []):
            osv_id = vuln.get("OSV", {}).get("id", "")
            for mod in vuln.get("Modules", []):
                mod_path = mod.get("Path", "")
                if mod_path:
                    vuln_map[mod_path] = osv_id
    except Exception as exc:
        logger.warning("govulncheck output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        if d.get("name", "") in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[d["name"]]
        result.append(d)
    return result


def check_go_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for gomod deps in a repo.

    1. Filters deps to gomod-managed entries.
    2. Runs check_go_outdated on gomod deps.
    3. Runs check_go_vulns on gomod deps.
    4. Stamps required health fields on all gomod deps (fills defaults for skipped deps).
    5. Returns merged list (gomod enriched + non-gomod unchanged).
    """
    if not deps:
        return []

    go_deps = [d for d in deps if d.get("manager") == "gomod"]
    other_deps = [d for d in deps if d.get("manager") != "gomod"]

    if not go_deps:
        return other_deps

    go_deps = check_go_outdated(repo_path, go_deps)
    go_deps = check_go_vulns(repo_path, go_deps)

    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in go_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── Rust dependency health (Packet 15) ────────────────────────────────────────


def check_rust_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run cargo outdated --format json and enrich cargo deps with version/severity fields.

    If cargo-outdated is not available (TOOLS["cargo_outdated"] is None), returns deps unchanged.
    On any subprocess or parse failure, returns deps unchanged (fail-open).
    """
    cargo_outdated = TOOLS.get("cargo_outdated")
    if not cargo_outdated:
        return deps

    try:
        proc = subprocess.run(
            [cargo_outdated, "--format", "json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("cargo outdated failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {name: {"project": current, "latest": latest}}
    outdated_map: dict[str, dict] = {}
    try:
        for entry in raw.get("dependencies", []):
            name = entry.get("name", "")
            if name:
                outdated_map[name] = {
                    "project": entry.get("project", ""),
                    "latest": entry.get("latest", ""),
                }
    except Exception as exc:
        logger.warning("cargo outdated output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            current = info["project"]
            latest = info["latest"]
            d["current_version"] = current
            d["wanted_version"] = current  # cargo has no "wanted" concept
            d["latest_version"] = latest
            if current and latest:
                d["severity"] = classify_severity(current, latest)
            else:
                d["severity"] = "outdated"
        result.append(d)
    return result


def check_rust_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run cargo audit --json and merge vulnerability info into cargo dep dicts.

    If cargo-audit is not available (TOOLS["cargo_audit"] is None), returns deps unchanged.
    Vulnerability severity overrides any prior severity.
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = RUSTSEC ID.
    """
    cargo_audit = TOOLS.get("cargo_audit")
    if not cargo_audit:
        return deps

    try:
        proc = subprocess.run(
            [cargo_audit, "--json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("cargo audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {package_name: rustsec_id}
    vuln_map: dict[str, str] = {}
    try:
        for entry in raw.get("vulnerabilities", {}).get("list", []):
            advisory_id = entry.get("advisory", {}).get("id", "")
            pkg_name = entry.get("package", {}).get("name", "")
            if pkg_name and advisory_id:
                vuln_map[pkg_name] = advisory_id
    except Exception as exc:
        logger.warning("cargo audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        if d.get("name", "") in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[d["name"]]
        result.append(d)
    return result


def check_rust_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for cargo deps in a repo.

    1. Filters deps to cargo-managed entries.
    2. Runs check_rust_outdated on cargo deps.
    3. Runs check_rust_vulns on cargo deps (cargo-audit is independent of cargo-outdated).
    4. Stamps required health fields on all cargo deps.
    5. Returns merged list (cargo enriched + non-cargo unchanged).
    """
    if not deps:
        return []

    cargo_deps = [d for d in deps if d.get("manager") == "cargo"]
    other_deps = [d for d in deps if d.get("manager") != "cargo"]

    if not cargo_deps:
        return other_deps

    cargo_deps = check_rust_outdated(repo_path, cargo_deps)
    cargo_deps = check_rust_vulns(repo_path, cargo_deps)

    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in cargo_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── Ruby dependency health (Packet 15) ────────────────────────────────────────


def check_ruby_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run bundle outdated --parseable and enrich bundler deps with version/severity fields.

    If bundle is not available (TOOLS["bundle"] is None), returns deps unchanged.
    Parses line-by-line output: 'gem-name (newest X.Y.Z, installed A.B.C, ...)'.
    On any subprocess or parse failure, returns deps unchanged (fail-open).
    """
    bundle = TOOLS.get("bundle")
    if not bundle:
        return deps

    try:
        proc = subprocess.run(
            [bundle, "outdated", "--parseable"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        stdout = proc.stdout
    except Exception as exc:
        logger.warning("bundle outdated failed for %s: %s", repo_path, exc)
        return deps

    # Parse line-by-line: gem-name (newest X.Y.Z, installed A.B.C[, requested ~> A.B])
    _BUNDLE_LINE_RE = re.compile(
        r'^(\S+)\s+\(newest\s+([^,]+),\s+installed\s+([^,)]+)'
    )
    outdated_map: dict[str, dict] = {}
    for line in stdout.splitlines():
        m = _BUNDLE_LINE_RE.match(line.strip())
        if m:
            gem_name = m.group(1)
            newest = m.group(2).strip()
            installed = m.group(3).strip()
            outdated_map[gem_name] = {"installed": installed, "newest": newest}

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            current = info["installed"]
            latest = info["newest"]
            d["current_version"] = current
            d["wanted_version"] = current  # bundler has no "wanted" concept
            d["latest_version"] = latest
            d["severity"] = classify_severity(current, latest)
        result.append(d)
    return result


def check_ruby_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run bundler-audit check --format json and merge vulnerability info.

    If bundler-audit is not available (TOOLS["bundler_audit"] is None), returns deps unchanged.
    Vulnerability severity overrides any prior severity.
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = advisory ID.
    """
    bundler_audit = TOOLS.get("bundler_audit")
    if not bundler_audit:
        return deps

    try:
        proc = subprocess.run(
            [bundler_audit, "check", "--format", "json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("bundler-audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {gem_name_lower: advisory_id}
    vuln_map: dict[str, str] = {}
    try:
        for entry in raw.get("results", []):
            gem_name = entry.get("gem", {}).get("name", "")
            advisory_id = entry.get("advisory", {}).get("id", "")
            if gem_name and advisory_id:
                vuln_map[gem_name.lower()] = advisory_id
    except Exception as exc:
        logger.warning("bundler-audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        key = d.get("name", "").lower()
        if key in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[key]
        result.append(d)
    return result


def check_ruby_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for bundler deps in a repo.

    1. Filters deps to bundler-managed entries.
    2. Runs check_ruby_outdated on bundler deps.
    3. Runs check_ruby_vulns on bundler deps.
    4. Stamps required health fields on all bundler deps.
    5. Returns merged list (bundler enriched + non-bundler unchanged).
    """
    if not deps:
        return []

    ruby_deps = [d for d in deps if d.get("manager") == "bundler"]
    other_deps = [d for d in deps if d.get("manager") != "bundler"]

    if not ruby_deps:
        return other_deps

    ruby_deps = check_ruby_outdated(repo_path, ruby_deps)
    ruby_deps = check_ruby_vulns(repo_path, ruby_deps)

    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in ruby_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── PHP dependency health (Packet 15) ─────────────────────────────────────────


def check_php_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run composer outdated --format=json and enrich composer deps with version/severity fields.

    If composer is not available (TOOLS["composer"] is None), returns deps unchanged.
    Skips deps with latest-status == "up-to-date".
    On any subprocess or parse failure, returns deps unchanged (fail-open).
    """
    composer = TOOLS.get("composer")
    if not composer:
        return deps

    try:
        proc = subprocess.run(
            [composer, "outdated", "--format=json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("composer outdated failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {name: {"version": current, "latest": latest}}
    outdated_map: dict[str, dict] = {}
    try:
        for entry in raw.get("installed", []):
            status = entry.get("latest-status", "up-to-date")
            if status == "up-to-date":
                continue
            name = entry.get("name", "")
            if name:
                outdated_map[name] = {
                    "version": entry.get("version", ""),
                    "latest": entry.get("latest", ""),
                }
    except Exception as exc:
        logger.warning("composer outdated output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            current = info["version"]
            latest = info["latest"]
            d["current_version"] = current
            d["wanted_version"] = current  # composer has no "wanted" concept
            d["latest_version"] = latest
            if current and latest:
                d["severity"] = classify_severity(current, latest)
            else:
                d["severity"] = "outdated"
        result.append(d)
    return result


def check_php_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run composer audit --format=json and merge vulnerability info into composer dep dicts.

    If composer is not available (TOOLS["composer"] is None), returns deps unchanged.
    Audit is built-in since Composer 2.4 — same binary, different subcommand.
    Vulnerability severity overrides any prior severity.
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = advisory ID.
    """
    composer = TOOLS.get("composer")
    if not composer:
        return deps

    try:
        proc = subprocess.run(
            [composer, "audit", "--format=json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("composer audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {package_name: advisory_id}
    # composer audit JSON: {"advisories": {"pkg/name": [{"advisoryId": "...", ...}]}}
    vuln_map: dict[str, str] = {}
    try:
        for pkg_name, advisories in raw.get("advisories", {}).items():
            if advisories:
                advisory_id = advisories[0].get("advisoryId") or advisories[0].get("cve", "")
                if advisory_id:
                    vuln_map[pkg_name.lower()] = advisory_id
    except Exception as exc:
        logger.warning("composer audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        key = d.get("name", "").lower()
        if key in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[key]
        result.append(d)
    return result


def check_php_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for composer deps in a repo.

    1. Filters deps to composer-managed entries.
    2. Runs check_php_outdated on composer deps.
    3. Runs check_php_vulns on composer deps.
    4. Stamps required health fields on all composer deps.
    5. Returns merged list (composer enriched + non-composer unchanged).
    """
    if not deps:
        return []

    php_deps = [d for d in deps if d.get("manager") == "composer"]
    other_deps = [d for d in deps if d.get("manager") != "composer"]

    if not php_deps:
        return other_deps

    php_deps = check_php_outdated(repo_path, php_deps)
    php_deps = check_php_vulns(repo_path, php_deps)

    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in php_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


async def get_default_branch(repo_path: Path) -> str:
    """Return the current branch name from symbolic-ref, or 'main' as fallback."""
    stdout, _, rc = await run_git(repo_path, "symbolic-ref", "--short", "HEAD")
    if rc == 0 and stdout:
        return stdout
    return "main"


# Directories to skip when walking for git repos
_DISCOVERY_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".tox", ".eggs", "dist", "build",
}


async def discover_repos(root_path: Path) -> list:
    """Recursively walk root_path and return info dicts for all git repos found.

    Skips hidden directories (starting with '.') and known non-repo directories.
    Stops descending into a directory once a .git is found (avoids submodule traversal).
    Uses git rev-parse --show-toplevel for deduplication (belt-and-suspenders).

    Returns list of dicts with keys: path (str, resolved), name (str).
    """
    candidates: list = []

    # Synchronous walk — just checking directory existence, no git I/O
    for dirpath, dirnames, _ in os.walk(str(root_path)):
        # Prune hidden dirs and known skip dirs (in-place to affect os.walk descent)
        dirnames[:] = [
            d for d in dirnames
            if d not in _DISCOVERY_SKIP_DIRS and not d.startswith(".")
        ]

        git_dir = Path(dirpath) / ".git"
        if git_dir.exists():
            candidates.append(Path(dirpath))
            dirnames.clear()  # Don't descend further into this repo

    # Async deduplication via git rev-parse --show-toplevel
    repos: list = []
    seen_toplevel: set = set()
    for candidate in candidates:
        stdout, _, rc = await run_git(candidate, "rev-parse", "--show-toplevel")
        if rc != 0:
            continue
        try:
            toplevel = Path(stdout).resolve()
        except OSError:
            toplevel = Path(stdout)
        key = str(toplevel)
        if key not in seen_toplevel:
            seen_toplevel.add(key)
            repos.append({"path": key, "name": toplevel.name})

    return repos


async def register_repo(db, repo_info: dict) -> dict:
    """Insert a repo into the repositories table (idempotent via INSERT OR IGNORE).

    repo_info must have keys: path, name, default_branch, runtime.
    Returns dict with id, name, path.
    """
    repo_id = generate_repo_id(repo_info["path"])
    await db.execute(
        """INSERT OR IGNORE INTO repositories
             (id, name, path, default_branch, runtime, added_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            repo_id,
            repo_info["name"],
            repo_info["path"],
            repo_info.get("default_branch", "main"),
            repo_info.get("runtime", "unknown"),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    await db.commit()
    return {"id": repo_id, "name": repo_info["name"], "path": repo_info["path"]}


# ── Database dependency ────────────────────────────────────────────────────────

async def get_db():
    """FastAPI dependency: yield an aiosqlite connection for the request lifetime."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        yield db


# ── Port selection ────────────────────────────────────────────────────────────

def find_free_port(start_port: int, max_attempts: int = 20) -> int:
    """Return the first free TCP port at or after start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No free port found in range {start_port}–{start_port + max_attempts - 1}"
    )


# ── HTML Shell & Design System (packet 04) ────────────────────────────────────
# Full CSS custom properties, React shell, hash routing, nav tabs, ErrorBoundary.
# Content areas are placeholders filled by later packets (05, 10, etc.).

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Git Fleet</title>
  <!-- Google Fonts (JetBrains Mono + Geist) -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Geist:wght@400;500;600&display=swap" rel="stylesheet">
  <!-- CDN dependencies (pinned versions per spec §5.1) -->
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/prop-types/15.8.1/prop-types.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/recharts/2.12.7/Recharts.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg-primary);
      color: var(--text-primary);
      font-family: var(--font-body);
    }
    :root {
      /* Base */
      --bg-primary: #0f1117;
      --bg-secondary: #1a1d27;
      --bg-card: #1e2130;
      --bg-card-hover: #252838;
      --bg-input: #12141c;

      /* Borders */
      --border-default: #2a2d3a;
      --border-hover: #3a3d4a;

      /* Text */
      --text-primary: #e4e6ef;
      --text-secondary: #8b8fa3;
      --text-muted: #5a5e72;

      /* Accent */
      --accent-blue: #4c8dff;
      --accent-blue-dim: rgba(76,141,255,0.15);

      /* Status */
      --status-green: #34d399;
      --status-yellow: #fbbf24;
      --status-orange: #f97316;
      --status-red: #ef4444;
      --status-green-bg: rgba(52,211,153,0.12);
      --status-yellow-bg: rgba(251,191,36,0.12);
      --status-orange-bg: rgba(249,115,22,0.12);
      --status-red-bg: rgba(239,68,68,0.12);

      /* Freshness (card backgrounds + left border accents) */
      --fresh-this-week: var(--bg-card);
      --fresh-this-month: #1a1c28;
      --fresh-older: #16171f;
      --fresh-stale: #131420;

      /* Freshness left-border accents */
      --fresh-border-this-week: var(--accent-blue);
      --fresh-border-this-month: transparent;
      --fresh-border-older: transparent;
      --fresh-border-stale: var(--status-orange);

      /* Runtime colors (for badges/icons) */
      --runtime-python: #3776ab;
      --runtime-node: #339933;
      --runtime-go: #00add8;
      --runtime-rust: #dea584;
      --runtime-ruby: #cc342d;
      --runtime-php: #777bb4;
      --runtime-shell: #4eaa25;
      --runtime-docker: #2496ed;
      --runtime-html: #e34c26;

      /* Typography */
      --font-heading: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;
      --font-body: 'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      --font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;

      /* Sizing */
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 14px;

      /* Transitions */
      --transition-fast: 100ms ease-out;
      --transition-normal: 150ms ease-out;
      --transition-slow: 200ms ease-out;
    }
    @keyframes pulse {
      0%, 100% { opacity: 0.4; }
      50% { opacity: 0.7; }
    }
    @keyframes toastSlideIn {
      from { transform: translateX(100%); opacity: 0; }
      to   { transform: translateX(0);   opacity: 1; }
    }
    @keyframes toastSlideOut {
      from { transform: translateX(0);   opacity: 1; }
      to   { transform: translateX(100%); opacity: 0; }
    }
    /* ── Scrollbar styling ──────────────────────────────────────────────────── */
    /* Webkit (Chrome, Edge, Safari) */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: var(--bg-primary); }
    ::-webkit-scrollbar-thumb {
      background: var(--border-default);
      border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover { background: var(--border-hover); }
    /* Firefox */
    html {
      scrollbar-color: var(--border-default) var(--bg-primary);
      scrollbar-width: thin;
    }
    /* ── Global table styles (used by sub-tabs in packets 11, 17) ─────────── */
    .table-container { width: 100%; border-radius: var(--radius-md); overflow: hidden; }
    .table-header {
      background: var(--bg-secondary);
      display: grid;
      padding: 10px 16px;
      border-bottom: 1px solid var(--border-default);
      font-family: var(--font-body);
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .table-row {
      display: grid;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border-default);
      font-family: var(--font-body);
      font-size: 14px;
      color: var(--text-primary);
      transition: background var(--transition-fast);
    }
    .table-row:last-child { border-bottom: none; }
    .table-row:nth-child(even) { background: rgba(255,255,255,0.02); }
    .table-row:hover { background: var(--bg-card-hover); }
    .table-empty {
      padding: 40px 16px;
      text-align: center;
      font-family: var(--font-body);
      font-size: 14px;
      color: var(--text-muted);
    }
    /* ── Detail view styles ─────────────────────────────────────────────────── */
    .detail-view { padding: 0; }
    .detail-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      margin-bottom: 24px;
    }
    .detail-back-btn {
      display: flex;
      align-items: center;
      gap: 4px;
      background: none;
      border: none;
      cursor: pointer;
      font-family: var(--font-body);
      font-size: 13px;
      color: var(--text-secondary);
      padding: 4px 0;
      margin-bottom: 8px;
      transition: color var(--transition-fast);
    }
    .detail-back-btn:hover { color: var(--text-primary); }
    .detail-back-btn:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }
    .sub-tab-nav {
      display: flex;
      gap: 0;
      border-bottom: 1px solid var(--border-default);
      margin-bottom: 24px;
    }
    .sub-tab-btn {
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
      cursor: pointer;
      font-family: var(--font-heading);
      font-size: 13px;
      font-weight: 500;
      color: var(--text-secondary);
      padding: 8px 16px;
      transition: color var(--transition-fast), border-color var(--transition-fast);
    }
    .sub-tab-btn:hover { color: var(--text-primary); }
    .sub-tab-btn.active {
      color: var(--text-primary);
      border-bottom-color: var(--accent-blue);
    }
    .sub-tab-btn:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }
    .time-range-group {
      display: inline-flex;
      background: var(--bg-secondary);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      padding: 2px;
      gap: 2px;
      margin-bottom: 16px;
    }
    .time-range-btn {
      background: transparent;
      border: none;
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-family: var(--font-heading);
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary);
      padding: 4px 12px;
      transition: background var(--transition-fast), color var(--transition-fast);
    }
    .time-range-btn:hover { color: var(--text-primary); }
    .time-range-btn.active { background: var(--accent-blue); color: #fff; }
    .time-range-btn:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }
    /* ── Global keyboard focus styles (packet 24) ─────────────────────────── */
    button:focus-visible,
    [role="button"]:focus-visible,
    a:focus-visible,
    input:focus-visible {
      outline: 2px solid var(--accent-blue);
      outline-offset: 2px;
    }
    .project-card:focus-visible {
      outline: 2px solid var(--accent-blue);
      outline-offset: 2px;
      background: var(--bg-card-hover);
      border-color: var(--border-hover);
    }
    .project-card:hover {
      background: var(--bg-card-hover) !important;
      border-color: var(--border-hover) !important;
    }
    .project-card .card-delete-btn {
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.15s;
    }
    .project-card:hover .card-delete-btn,
    .project-card:focus-within .card-delete-btn {
      opacity: 1;
      pointer-events: auto;
    }
    .project-card .scan-failed-badge {
      transition: opacity 0.15s;
    }
    .project-card:hover .scan-failed-badge,
    .project-card:focus-within .scan-failed-badge {
      opacity: 0;
      pointer-events: none;
    }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    const { useState, useEffect, useRef, useLayoutEffect, useMemo } = React;

    // ── ErrorBoundary ────────────────────────────────────────────────────────
    class ErrorBoundary extends React.Component {
      constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
      }
      static getDerivedStateFromError(error) {
        return { hasError: true, error };
      }
      componentDidCatch(error, info) {
        console.error('ErrorBoundary caught:', error, info);
      }
      render() {
        if (this.state.hasError) {
          return (
            <div style={{
              padding: '48px',
              textAlign: 'center',
              color: 'var(--status-red)',
              fontFamily: 'var(--font-mono)',
            }}>
              <p style={{ fontSize: '16px', marginBottom: '8px' }}>Something went wrong</p>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                {this.state.error && this.state.error.toString()}
              </p>
            </div>
          );
        }
        return this.props.children;
      }
    }

    // ── Hash routing hook ────────────────────────────────────────────────────
    function useHashRoute() {
      const [route, setRoute] = useState(window.location.hash || '#/fleet');
      useEffect(() => {
        const handler = () => setRoute(window.location.hash || '#/fleet');
        window.addEventListener('hashchange', handler);
        return () => window.removeEventListener('hashchange', handler);
      }, []);
      return route;
    }

    function parseRoute(hash) {
      if (!hash || hash === '#/' || hash === '#/fleet') return { tab: 'fleet', repoId: null, subTab: null };
      if (hash.startsWith('#/repo/')) {
        const rest = hash.slice(7);
        const slashIdx = rest.indexOf('/');
        if (slashIdx === -1) return { tab: 'repo', repoId: rest, subTab: null };
        return { tab: 'repo', repoId: rest.slice(0, slashIdx), subTab: rest.slice(slashIdx + 1) || null };
      }
      if (hash === '#/analytics') return { tab: 'analytics', repoId: null, subTab: null };
      if (hash === '#/deps') return { tab: 'deps', repoId: null, subTab: null };
      return { tab: 'fleet', repoId: null, subTab: null };
    }

    // ── Header ───────────────────────────────────────────────────────────────
    function Header({ onFullScan, onScanDir, scanActive }) {
      return (
        <header style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          height: '56px',
          background: 'var(--bg-secondary)',
          borderBottom: '1px solid var(--border-default)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 24px',
          zIndex: 100,
        }}>
          <span style={{
            fontFamily: 'var(--font-heading)',
            fontSize: '18px',
            fontWeight: 700,
            color: 'var(--text-primary)',
          }}>
            Git Fleet
          </span>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              onClick={onScanDir}
              style={{
                background: 'transparent',
                border: '1px solid var(--border-default)',
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-body)',
                fontSize: '13px',
                fontWeight: 500,
                padding: '8px 16px',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
                transition: 'all var(--transition-fast)',
              }}
            >
              Scan Dir
            </button>
            <button
              onClick={onFullScan}
              disabled={scanActive}
              style={{
                background: scanActive ? 'var(--text-muted)' : 'var(--accent-blue)',
                border: 'none',
                color: '#fff',
                fontFamily: 'var(--font-body)',
                fontSize: '13px',
                fontWeight: 600,
                padding: '8px 16px',
                borderRadius: 'var(--radius-sm)',
                cursor: scanActive ? 'not-allowed' : 'pointer',
                transition: 'all var(--transition-fast)',
                opacity: scanActive ? 0.6 : 1,
              }}
            >
              Full Scan
            </button>
          </div>
        </header>
      );
    }

    // ── NavTabs ──────────────────────────────────────────────────────────────
    const TABS = [
      { id: 'fleet', label: 'Fleet Overview', hash: '#/fleet' },
      { id: 'analytics', label: 'Analytics', hash: '#/analytics' },
      { id: 'deps', label: 'Dependencies', hash: '#/deps' },
    ];

    function NavTabs({ activeTab }) {
      const tabRefs = useRef([]);
      const indicatorRef = useRef(null);

      useLayoutEffect(() => {
        const idx = TABS.findIndex(t => t.id === activeTab);
        const el = tabRefs.current[idx];
        const indicator = indicatorRef.current;
        if (el && indicator) {
          indicator.style.left = el.offsetLeft + 'px';
          indicator.style.width = el.offsetWidth + 'px';
        }
      }, [activeTab]);

      return (
        <nav style={{
          position: 'fixed',
          top: '56px',
          left: 0,
          right: 0,
          height: '44px',
          background: 'var(--bg-secondary)',
          borderBottom: '1px solid var(--border-default)',
          display: 'flex',
          alignItems: 'flex-end',
          padding: '0 24px',
          zIndex: 99,
        }}>
          <div style={{ position: 'relative', display: 'flex' }}>
            {TABS.map((tab, i) => (
              <a
                key={tab.id}
                href={tab.hash}
                ref={el => tabRefs.current[i] = el}
                style={{
                  display: 'block',
                  padding: '10px 16px',
                  fontFamily: 'var(--font-heading)',
                  fontSize: '14px',
                  fontWeight: 500,
                  color: activeTab === tab.id ? 'var(--accent-blue)' : 'var(--text-secondary)',
                  textDecoration: 'none',
                  transition: 'color var(--transition-fast)',
                  whiteSpace: 'nowrap',
                }}
              >
                {tab.label}
              </a>
            ))}
            <div
              ref={indicatorRef}
              style={{
                position: 'absolute',
                bottom: 0,
                height: '3px',
                background: 'var(--accent-blue)',
                borderRadius: '3px 3px 0 0',
                transition: 'left var(--transition-normal), width var(--transition-normal)',
                left: 0,
                width: 0,
              }}
            />
          </div>
        </nav>
      );
    }

    function ToolStatusBanner() {
      const [status, setStatus] = useState(null);
      const [dismissed, setDismissed] = useState(() => {
        try {
          return sessionStorage.getItem('git-fleet-status-banner-dismissed') === '1';
        } catch (_err) {
          return false;
        }
      });

      useEffect(() => {
        let active = true;
        fetch('/api/status')
          .then(res => res.json())
          .then(data => {
            if (active) setStatus(data);
          })
          .catch(() => {
            if (active) setStatus(null);
          });
        return () => {
          active = false;
        };
      }, []);

      if (dismissed || !status) return null;

      const toolCount = Object.values(status.tools || {}).filter(Boolean).length;
      return (
        <div style={{
          margin: '16px 24px 0',
          padding: '12px 16px',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border-default)',
          background: 'var(--bg-secondary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
        }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <strong style={{ fontFamily: 'var(--font-heading)', fontSize: '13px', color: 'var(--text-primary)' }}>
              Tool status
            </strong>
            <span style={{ fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-secondary)' }}>
              Version {status.version} with {toolCount} detected helper tool{toolCount === 1 ? '' : 's'}.
            </span>
          </div>
          <button
            onClick={() => {
              try {
                sessionStorage.setItem('git-fleet-status-banner-dismissed', '1');
              } catch (_err) {
                // Ignore browsers that block sessionStorage.
              }
              setDismissed(true);
            }}
            style={{
              background: 'transparent',
              border: '1px solid var(--border-default)',
              color: 'var(--text-secondary)',
              borderRadius: '999px',
              cursor: 'pointer',
              fontFamily: 'var(--font-body)',
              fontSize: '12px',
              padding: '6px 10px',
            }}
          >
            Dismiss
          </button>
        </div>
      );
    }

    // ── ScanProgressBar ───────────────────────────────────────────────────────
    // Slim 3px bar below nav tabs, visible during and just after scan.
    function ScanProgressBar({ scanState }) {
      const { active, status, progress, total } = scanState;
      if (!active && status !== 'completed') return null;
      const pct = total > 0 ? Math.min((progress / total) * 100, 100) : (status === 'completed' ? 100 : 0);
      const fillColor = status === 'completed' ? 'var(--status-green)' : 'var(--accent-blue)';
      return (
        <div style={{
          position: 'fixed',
          top: '100px',   // header(56) + nav(44)
          left: 0,
          right: 0,
          height: '3px',
          background: 'var(--border-default)',
          zIndex: 98,
        }}>
          <div style={{
            height: '3px',
            width: pct + '%',
            background: fillColor,
            transition: 'width 300ms ease-out, background 300ms ease-out',
          }} />
        </div>
      );
    }

    // ── DirectoryBrowser modal ─────────────────────────────────────────────────
    function DirectoryBrowser({ open, onClose, onSelect }) {
      const [currentPath, setCurrentPath] = useState('');
      const [dirs, setDirs] = useState([]);
      const [parentPath, setParentPath] = useState(null);
      const [loading, setLoading] = useState(false);
      const [error, setError] = useState(null);
      const [pathInput, setPathInput] = useState('');

      async function browse(dirPath) {
        setLoading(true);
        setError(null);
        try {
          const r = await fetch('/api/browse?path=' + encodeURIComponent(dirPath));
          const data = await r.json();
          if (!r.ok) { setError(data.detail || 'Failed to browse'); setLoading(false); return; }
          setCurrentPath(data.current);
          setParentPath(data.parent);
          setDirs(data.dirs);
          setPathInput(data.current);
        } catch (err) {
          setError(err.message);
        }
        setLoading(false);
      }

      useEffect(() => {
        if (open) browse('~');
      }, [open]);

      if (!open) return null;

      function handleKeyDown(e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          browse(pathInput);
        }
      }

      const overlayStyle = {
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
      };
      const modalStyle = {
        background: 'var(--bg-primary)', borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-default)', width: '560px', maxHeight: '80vh',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      };
      const headerStyle = {
        padding: '16px 20px', borderBottom: '1px solid var(--border-default)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      };
      const inputRowStyle = {
        padding: '12px 20px', borderBottom: '1px solid var(--border-default)',
        display: 'flex', gap: '8px',
      };
      const inputStyle = {
        flex: 1, background: 'var(--bg-secondary)', border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-sm)', padding: '8px 12px', color: 'var(--text-primary)',
        fontFamily: 'var(--font-mono)', fontSize: '13px', outline: 'none',
      };
      const listStyle = {
        flex: 1, overflowY: 'auto', padding: '8px 0',
      };
      const itemStyle = (isGit) => ({
        padding: '8px 20px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '10px',
        fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-primary)',
        borderLeft: isGit ? '3px solid var(--accent-blue)' : '3px solid transparent',
      });
      const footerStyle = {
        padding: '12px 20px', borderTop: '1px solid var(--border-default)',
        display: 'flex', justifyContent: 'flex-end', gap: '8px',
      };
      const btnBase = {
        padding: '8px 16px', borderRadius: 'var(--radius-sm)', fontSize: '13px',
        fontFamily: 'var(--font-body)', fontWeight: 500, cursor: 'pointer', border: 'none',
      };

      return (
        <div style={overlayStyle} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
          <div style={modalStyle}>
            <div style={headerStyle}>
              <span style={{ fontWeight: 600, fontSize: '15px', color: 'var(--text-primary)', fontFamily: 'var(--font-body)' }}>
                Select Directory to Scan
              </span>
              <button onClick={onClose} style={{ ...btnBase, background: 'none', color: 'var(--text-muted)', fontSize: '18px', padding: '4px 8px' }}>{'\u00d7'}</button>
            </div>
            <div style={inputRowStyle}>
              <input
                type="text"
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                onKeyDown={handleKeyDown}
                style={inputStyle}
                placeholder="/path/to/directory"
              />
              <button onClick={() => browse(pathInput)} style={{ ...btnBase, background: 'var(--bg-secondary)', color: 'var(--text-primary)', border: '1px solid var(--border-default)' }}>Go</button>
            </div>
            <div style={listStyle}>
              {error && <div style={{ padding: '12px 20px', color: 'var(--status-red)', fontSize: '13px' }}>{error}</div>}
              {loading && <div style={{ padding: '12px 20px', color: 'var(--text-muted)', fontSize: '13px' }}>Loading...</div>}
              {!loading && !error && (
                <>
                  {parentPath && (
                    <div
                      onClick={() => browse(parentPath)}
                      style={{ ...itemStyle(false), color: 'var(--text-muted)' }}
                      onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-secondary)'}
                      onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                    >
                      {'\u2190'} ..
                    </div>
                  )}
                  {dirs.length === 0 && !parentPath && (
                    <div style={{ padding: '12px 20px', color: 'var(--text-muted)', fontSize: '13px' }}>No subdirectories</div>
                  )}
                  {dirs.map(d => (
                    <div
                      key={d.path}
                      onClick={() => browse(d.path)}
                      style={itemStyle(d.is_git)}
                      onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-secondary)'}
                      onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                    >
                      <span style={{ fontFamily: 'monospace' }}>{d.is_git ? '[repo]' : '[dir]'}</span>
                      <span style={{ flex: 1 }}>{d.name}</span>
                      {d.is_git && <span style={{ fontSize: '11px', color: 'var(--accent-blue)', fontWeight: 500 }}>git</span>}
                    </div>
                  ))}
                </>
              )}
            </div>
            <div style={footerStyle}>
              <button onClick={onClose} style={{ ...btnBase, background: 'var(--bg-secondary)', color: 'var(--text-primary)', border: '1px solid var(--border-default)' }}>Cancel</button>
              <button
                onClick={() => { onSelect(currentPath); onClose(); }}
                style={{ ...btnBase, background: 'var(--accent-blue)', color: '#fff' }}
              >
                Scan This Directory
              </button>
            </div>
          </div>
        </div>
      );
    }

    // ── ScanToast ─────────────────────────────────────────────────────────────
    // Fixed bottom-right notification showing scan progress.
    function ScanToast({ scanState }) {
      const { active, status, progress, total, currentRepo } = scanState;
      const [visible, setVisible] = React.useState(false);
      const [slideOut, setSlideOut] = React.useState(false);

      React.useEffect(() => {
        if (active) {
          setVisible(true);
          setSlideOut(false);
        } else if (status === 'completed' || status === 'failed') {
          // Show completion/failure briefly, then slide out and hide
          setVisible(true);
          setSlideOut(false);
          const t = setTimeout(() => setSlideOut(true), 2000);
          return () => clearTimeout(t);
        } else if (status === 'idle') {
          // Reset complete — hide immediately
          setVisible(false);
          setSlideOut(false);
        }
      }, [active, status]);

      if (!visible) return null;

      const pct = total > 0 ? Math.min((progress / total) * 100, 100) : (status === 'completed' ? 100 : 0);
      const fillColor = status === 'completed' ? 'var(--status-green)' : 'var(--accent-blue)';
      const heading = status === 'completed' ? 'Scan complete'
        : status === 'failed' ? 'Scan failed'
        : 'Scanning...';

      return (
        <div style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          width: '320px',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)',
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
          padding: '16px',
          zIndex: 200,
          animation: slideOut
            ? 'toastSlideOut var(--transition-slow) forwards'
            : 'toastSlideIn var(--transition-slow) forwards',
        }}>
          <div style={{
            fontFamily: 'var(--font-heading)',
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: '6px',
          }}>
            {heading}
          </div>
          {currentRepo && (
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              color: 'var(--text-secondary)',
              marginBottom: '8px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {currentRepo}
            </div>
          )}
          <div style={{ marginBottom: '4px' }}>
            <div style={{
              height: '4px',
              background: 'var(--border-default)',
              borderRadius: '2px',
              overflow: 'hidden',
            }}>
              <div style={{
                height: '4px',
                width: pct + '%',
                background: fillColor,
                transition: 'width 300ms ease-out, background 300ms ease-out',
              }} />
            </div>
          </div>
          <div style={{
            fontFamily: 'var(--font-body)',
            fontSize: '12px',
            color: 'var(--text-muted)',
            textAlign: 'right',
          }}>
            {progress} / {total || '?'}
          </div>
        </div>
      );
    }

    // ── Fleet Overview UI ─────────────────────────────────────────────────────

    // Runtime badge label mapping (§5.4 Project Card)
    const RUNTIME_LABELS = {
      python: 'PY', node: 'JS', go: 'GO', rust: 'RS', ruby: 'RB',
      php: 'PHP', shell: 'SH', docker: 'DK', html: 'HTML', mixed: 'MIX', unknown: '??'
    };

    // Relative time formatter — converts ISO 8601 date to "Xm/h/d/mo/y ago" or "never"
    function timeAgo(isoDate) {
      if (!isoDate) return 'never';
      const diffMs = Date.now() - new Date(isoDate).getTime();
      if (isNaN(diffMs) || diffMs < 0) return 'just now';
      const mins = Math.floor(diffMs / 60000);
      if (mins < 60) return mins <= 1 ? 'just now' : `${mins}m ago`;
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return `${hrs}h ago`;
      const days = Math.floor(hrs / 24);
      if (days < 30) return `${days}d ago`;
      const mos = Math.floor(days / 30);
      if (mos < 12) return `${mos}mo ago`;
      return `${Math.floor(mos / 12)}y ago`;
    }

    // Freshness classification — returns CSS bg var and optional border-left style
    function freshnessStyle(isoDate) {
      if (!isoDate) {
        return {
          background: 'var(--fresh-stale)',
          borderLeft: '3px solid var(--fresh-border-stale)',
        };
      }
      const days = (Date.now() - new Date(isoDate).getTime()) / 86400000;
      if (days <= 7) {
        return {
          background: 'var(--fresh-this-week)',
          borderLeft: '3px solid var(--fresh-border-this-week)',
        };
      }
      if (days <= 30) return { background: 'var(--fresh-this-month)' };
      if (days <= 90) return { background: 'var(--fresh-older)' };
      return {
        background: 'var(--fresh-stale)',
        borderLeft: '3px solid var(--fresh-border-stale)',
      };
    }

    // RuntimeBadge — colored abbreviation square
    function RuntimeBadge({ runtime }) {
      const type = (runtime || 'unknown').toLowerCase();
      const label = RUNTIME_LABELS[type] || '??';
      const color = `var(--runtime-${type}, var(--text-muted))`;
      return (
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: '24px', height: '24px', flexShrink: 0,
          borderRadius: '4px',
          background: `color-mix(in srgb, ${color} 20%, transparent)`,
          color: color,
          fontFamily: 'var(--font-heading)',
          fontSize: '11px', fontWeight: 700,
        }}>
          {label}
        </span>
      );
    }

    // StatusPills — Clean or mod/new/staged pills
    function StatusPills({ repo }) {
      const { has_uncommitted, modified_count, untracked_count, staged_count } = repo;
      if (!has_uncommitted) {
        return (
          <span style={{
            fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500,
            padding: '2px 8px', borderRadius: '4px',
            color: 'var(--status-green)', background: 'var(--status-green-bg)',
          }}>Clean</span>
        );
      }
      const pills = [];
      if (modified_count > 0) pills.push({
        label: `${modified_count} mod`, color: 'var(--status-yellow)', bg: 'var(--status-yellow-bg)'
      });
      if (untracked_count > 0) pills.push({
        label: `${untracked_count} new`, color: 'var(--status-orange)', bg: 'var(--status-orange-bg)'
      });
      if (staged_count > 0) pills.push({
        label: `${staged_count} staged`, color: 'var(--accent-blue)', bg: 'var(--accent-blue-dim)'
      });
      return (
        <span style={{ display: 'inline-flex', gap: '4px', flexWrap: 'wrap' }}>
          {pills.map(p => (
            <span key={p.label} style={{
              fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500,
              padding: '2px 8px', borderRadius: '4px',
              color: p.color, background: p.bg,
            }}>{p.label}</span>
          ))}
        </span>
      );
    }

    // DepBadge — compact dep summary pill with coverage dot
    function DepBadge({ dep, missingTools }) {
      if (!dep) return null;
      const { total, outdated, vulnerable } = dep;
      if (!total && total !== 0) return null;

      const hasMissing = missingTools && missingTools.length > 0;
      // Status dot: green = full coverage, amber = partial (missing tools)
      const dotColor = hasMissing ? 'var(--status-orange)' : 'var(--status-green)';
      const dotTitle = hasMissing
        ? 'Incomplete: ' + missingTools.map(t => t.tool || t).join(', ')
        : 'Full tool coverage';

      let label = null;
      if (vulnerable > 0) {
        label = <span style={{
          fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 400,
          color: 'var(--status-red)',
        }}>{vulnerable} vuln</span>;
      } else if (outdated > 0) {
        label = <span style={{
          fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 400,
          color: 'var(--status-yellow)',
        }}>{outdated} out</span>;
      } else if (total > 0) {
        label = <span style={{
          fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 400,
          color: 'var(--text-muted)',
        }}>{total} deps</span>;
      }
      if (!label) return null;

      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
          <span
            title={dotTitle}
            style={{
              display: 'inline-block', width: '6px', height: '6px',
              borderRadius: '50%', background: dotColor, flexShrink: 0,
            }}
          />
          {label}
        </span>
      );
    }

    // SparklineOverlay — slides up from bottom on card hover
    function SparklineOverlay({ sparkline, visible }) {
      const { AreaChart, Area } = Recharts;
      const data = (sparkline || []).map((v, i) => ({ i, v }));
      return (
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0, height: '32px',
          overflow: 'hidden', pointerEvents: 'none',
          transform: visible ? 'translateY(0)' : 'translateY(100%)',
          transition: visible ? '150ms ease-out' : '100ms ease-in',
          background: 'linear-gradient(transparent, var(--bg-card) 30%)',
        }}>
          {data.length > 0 && (
            <AreaChart width={400} height={28} data={data}
              style={{ width: '100%' }}
              margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
              <Area type="monotone" dataKey="v"
                fill="var(--accent-blue-dim)" stroke="var(--accent-blue)"
                dot={false} isAnimationActive={false} />
            </AreaChart>
          )}
        </div>
      );
    }

    // ProjectCard — compact 3-row card
    function ProjectCard({ repo, onDelete }) {
      const [hovered, setHovered] = useState(false);
      const [focused, setFocused] = useState(false);
      const [tooltipVisible, setTooltipVisible] = useState(false);

      const pathMissing = repo.path_exists === false;
      const freshness = freshnessStyle(repo.last_commit_date);
      const active = hovered || focused;
      const cardStyle = {
        position: 'relative', overflow: 'hidden',
        borderRadius: 'var(--radius-md)',
        padding: '14px 16px',
        cursor: 'pointer',
        background: active ? 'var(--bg-card-hover)' : (pathMissing ? 'var(--bg-card)' : (freshness.background || 'var(--bg-card)')),
        border: `1px solid ${active ? 'var(--border-hover)' : 'var(--border-default)'}`,
        borderLeft: pathMissing
          ? '4px solid var(--status-red)'
          : (freshness.borderLeft || `1px solid ${active ? 'var(--border-hover)' : 'var(--border-default)'}`),
        transition: 'background var(--transition-fast), border-color var(--transition-fast)',
      };

      const branchColor = (repo.stale_branch_count || 0) > 0
        ? 'var(--status-orange)' : 'var(--text-muted)';

      function handleDelete(e) {
        e.stopPropagation();
        if (!confirm(`Remove "${repo.name}" from the fleet?`)) return;
        fetch('/api/repos/' + repo.id, { method: 'DELETE' })
          .then(r => {
            if (r.ok && onDelete) onDelete(repo.id);
          });
      }

      return (
        <div
          className="project-card"
          style={cardStyle}
          tabIndex={0}
          role="button"
          aria-label={`View ${repo.name} details`}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onClick={() => { window.location.hash = '#/repo/' + repo.id; }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              window.location.hash = '#/repo/' + repo.id;
            }
          }}
        >
          {/* Delete button — CSS :hover controls visibility */}
          <button
            className="card-delete-btn"
            onClick={handleDelete}
            title={`Remove ${repo.name}`}
            aria-label={`Remove ${repo.name}`}
            style={{
              position: 'absolute', top: '8px', right: '8px', zIndex: 5,
              background: 'var(--bg-secondary)', border: '1px solid var(--border-default)',
              color: 'var(--text-muted)', cursor: 'pointer',
              width: '22px', height: '22px', borderRadius: '4px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '14px', lineHeight: 1, padding: 0,
            }}
          >{'\u00d7'}</button>

          {/* Scan-failed badge — CSS :hover hides it when delete button is visible */}
          {repo.scan_error && (
            <div className="scan-failed-badge" style={{
              position: 'absolute', top: '8px', right: '8px',
              fontSize: '10px', fontFamily: 'var(--font-body)', fontWeight: 600,
              color: 'var(--status-red)', background: 'var(--status-red-bg)',
              padding: '2px 6px', borderRadius: '3px',
            }}>
              scan failed
            </div>
          )}

          {/* Row 1: RuntimeBadge + name (with tooltip) + time */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            <RuntimeBadge runtime={repo.runtime} />
            <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
              <span
                style={{
                  display: 'block',
                  fontFamily: 'var(--font-heading)', fontSize: '16px', fontWeight: 600,
                  color: 'var(--text-primary)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  cursor: 'pointer',
                }}
                onMouseEnter={() => setTooltipVisible(true)}
                onMouseLeave={() => setTooltipVisible(false)}
              >
                {repo.name}
              </span>
              {tooltipVisible && (
                <div style={{
                  position: 'absolute', bottom: '100%', left: 0, zIndex: 10,
                  background: 'var(--bg-secondary)', border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-sm)', padding: '6px 10px',
                  fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 400,
                  color: 'var(--text-secondary)', maxWidth: '500px',
                  whiteSpace: 'nowrap', pointerEvents: 'none',
                  marginBottom: '4px',
                }}>
                  {repo.path}
                </div>
              )}
            </div>
            <span style={{
              flexShrink: 0, fontSize: '13px',
              fontFamily: 'var(--font-body)', color: 'var(--text-secondary)',
            }}>
              {timeAgo(repo.last_commit_date)}
            </span>
          </div>

          {/* Row 2: Last commit message or path-not-found error */}
          <div style={{
            fontSize: '13px', fontFamily: 'var(--font-body)',
            color: pathMissing ? 'var(--status-red)' : 'var(--text-secondary)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            marginBottom: '8px', marginLeft: '32px',
            fontWeight: pathMissing ? 600 : 400,
          }}>
            {pathMissing
              ? 'Path not found'
              : (repo.last_commit_message || <span style={{ color: 'var(--text-muted)' }}>—</span>)}
          </div>

          {/* Row 3: Status pills + branch + branch count + dep badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <StatusPills repo={repo} />
            <span style={{ flex: 1 }} />
            <span style={{
              fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 400,
              color: 'var(--text-secondary)',
            }}>
              {repo.current_branch}
            </span>
            <span style={{
              fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 400,
              color: branchColor,
            }}>
              {repo.branch_count || 0}br
            </span>
            <DepBadge dep={repo.dep_summary} missingTools={repo.missing_dep_tools} />
          </div>

          <SparklineOverlay sparkline={repo.sparkline} visible={hovered} />
        </div>
      );
    }

    // KpiCard — single stat card
    function KpiCard({ value, label, color, tooltip }) {
      return (
        <div
          title={tooltip || ''}
          style={{
            flex: '1 1 140px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)',
            padding: '16px 20px',
            cursor: tooltip ? 'help' : undefined,
          }}
        >
          <div style={{
            fontFamily: 'var(--font-heading)', fontSize: '28px', fontWeight: 700,
            color: color || 'var(--text-primary)',
            lineHeight: 1.1,
          }}>{value}</div>
          <div style={{
            fontFamily: 'var(--font-body)', fontSize: '12px', fontWeight: 500,
            color: 'var(--text-secondary)',
            textTransform: 'uppercase', letterSpacing: '0.5px',
            marginTop: '4px',
          }}>{label}</div>
        </div>
      );
    }

    // KpiRow — row of 6 KPI cards
    function KpiRow({ kpis }) {
      if (!kpis) return null;
      const dirtyColor = kpis.repos_with_changes > 0 ? 'var(--status-yellow)' : undefined;
      const staleColor = kpis.stale_branches > 0 ? 'var(--status-orange)' : undefined;
      const vulnColor = kpis.vulnerable_deps > 0 ? 'var(--status-red)' : undefined;
      const commitValue = `${kpis.commits_this_week ?? 0} / ${kpis.commits_this_month ?? 0}`;
      const locValue = kpis.net_lines_this_week > 0
        ? `+${(kpis.net_lines_this_week || 0).toLocaleString()}`
        : String(kpis.net_lines_this_week ?? 0);
      const vulnValue = `${kpis.vulnerable_deps ?? 0} / ${kpis.outdated_deps ?? 0}`;
      return (
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
          <KpiCard value={kpis.total_repos ?? 0} label="Repos" tooltip="Total repositories tracked" />
          <KpiCard value={kpis.repos_with_changes ?? 0} label="Dirty" color={dirtyColor} tooltip="Repos with uncommitted changes (modified, untracked, or staged files)" />
          <KpiCard value={commitValue} label="Commits" tooltip="Commits this week / this month (across all repos)" />
          <KpiCard value={locValue} label="Net LOC" tooltip="Net lines of code changed this week (insertions minus deletions, across all repos)" />
          <KpiCard value={kpis.stale_branches ?? 0} label="Stale Branches" color={staleColor} tooltip="Branches with no commits in the last 30 days (across all repos)" />
          <KpiCard value={vulnValue} label="Vuln / Outdated" color={vulnColor} tooltip="Vulnerable dependencies / outdated dependencies (across all repos)" />
        </div>
      );
    }

    // SortDropdown — custom (not native <select>) dropdown
    function SortDropdown({ value, onChange }) {
      const [open, setOpen] = useState(false);
      const ref = useRef(null);
      const options = [
        { value: 'last_active', label: 'Last active' },
        { value: 'name_az',    label: 'Name A-Z' },
        { value: 'most_changes', label: 'Most changes' },
        { value: 'most_stale', label: 'Most stale branches' },
      ];
      const current = options.find(o => o.value === value) || options[0];

      useEffect(() => {
        if (!open) return;
        const handler = (e) => {
          if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
      }, [open]);

      return (
        <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
          <button
            onClick={() => setOpen(o => !o)}
            style={{
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', padding: '6px 12px',
              color: 'var(--text-primary)', fontFamily: 'var(--font-body)', fontSize: '13px',
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px',
              whiteSpace: 'nowrap',
            }}
          >
            {current.label}
            <svg width="10" height="6" viewBox="0 0 10 6" fill="none">
              <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
          {open && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, zIndex: 20, marginTop: '4px',
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', minWidth: '180px', overflow: 'hidden',
            }}>
              {options.map(opt => (
                <div
                  key={opt.value}
                  onClick={() => { onChange(opt.value); setOpen(false); }}
                  style={{
                    padding: '8px 12px', cursor: 'pointer',
                    fontFamily: 'var(--font-body)', fontSize: '13px',
                    color: opt.value === value ? 'var(--accent-blue)' : 'var(--text-primary)',
                    background: opt.value === value ? 'var(--accent-blue-dim)' : 'transparent',
                  }}
                  onMouseEnter={e => { if (opt.value !== value) e.currentTarget.style.background = 'var(--bg-card-hover)'; }}
                  onMouseLeave={e => { if (opt.value !== value) e.currentTarget.style.background = 'transparent'; }}
                >
                  {opt.label}
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }

    // GridControls — sort dropdown + filter input
    function GridControls({ sortBy, filterText, onSortChange, onFilterChange }) {
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
          <SortDropdown value={sortBy} onChange={onSortChange} />
          <input
            type="text"
            placeholder="Filter projects..."
            value={filterText}
            onChange={e => onFilterChange(e.target.value)}
            style={{
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', padding: '6px 12px',
              fontFamily: 'var(--font-body)', fontSize: '13px',
              color: 'var(--text-primary)', outline: 'none', width: '220px',
            }}
            onFocus={e => { e.target.style.borderColor = 'var(--accent-blue)'; }}
            onBlur={e => { e.target.style.borderColor = 'var(--border-default)'; }}
          />
        </div>
      );
    }

    // EmptyState — shown when no repos are registered
    function EmptyState() {
      return (
        <div style={{
          textAlign: 'center', padding: '64px 24px',
          color: 'var(--text-muted)',
        }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none"
            style={{ color: 'var(--text-muted)', marginBottom: '16px' }}>
            <path d="M3 3h18v18H3zM9 9h6M9 12h6M9 15h4"
              stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <p style={{ fontFamily: 'var(--font-heading)', fontSize: '16px', marginBottom: '8px' }}>
            No repositories registered
          </p>
          <p style={{ fontFamily: 'var(--font-body)', fontSize: '14px' }}>
            Use "Scan Dir" in the header to add repositories.
          </p>
        </div>
      );
    }

    // sortRepos — pure sort function applied after filtering
    function sortRepos(repos, sortBy) {
      const sorted = [...repos];
      if (sortBy === 'name_az') {
        sorted.sort((a, b) => (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase()));
      } else if (sortBy === 'most_changes') {
        sorted.sort((a, b) =>
          ((b.modified_count || 0) + (b.untracked_count || 0)) -
          ((a.modified_count || 0) + (a.untracked_count || 0))
        );
      } else if (sortBy === 'most_stale') {
        sorted.sort((a, b) => (b.stale_branch_count || 0) - (a.stale_branch_count || 0));
      } else {
        // last_active (default) — sort by last_commit_date desc, nulls last
        sorted.sort((a, b) => {
          if (!a.last_commit_date && !b.last_commit_date) return 0;
          if (!a.last_commit_date) return 1;
          if (!b.last_commit_date) return -1;
          return new Date(b.last_commit_date) - new Date(a.last_commit_date);
        });
      }
      return sorted;
    }

    // ── SkeletonCard ─────────────────────────────────────────────────────────
    function SkeletonCard() {
      const barStyle = (width) => ({
        background: 'var(--border-default)',
        borderRadius: '4px',
        height: '14px',
        width,
        animation: 'pulse 1.5s ease-in-out infinite',
      });
      return (
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)',
          padding: '14px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}>
          <div style={barStyle('60%')} />
          <div style={barStyle('80%')} />
          <div style={barStyle('50%')} />
        </div>
      );
    }

    // FleetOverview — main fleet tab component
    function FleetOverview({ refetchKey = 0 }) {
      const [data, setData] = useState(null);
      const [sortBy, setSortBy] = useState('last_active');
      const [filterText, setFilterText] = useState('');

      useEffect(() => {
        fetch('/api/fleet')
          .then(r => r.json())
          .then(d => setData(d))
          .catch(err => console.error('Fleet fetch error:', err));
      }, [refetchKey]);

      if (!data) {
        return (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
            gap: '16px',
            marginTop: '24px',
          }}>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        );
      }

      const { repos = [], kpis } = data;

      // Filter then sort
      const filtered = repos.filter(r =>
        (r.name || '').toLowerCase().includes(filterText.toLowerCase())
      );
      const sorted = sortRepos(filtered, sortBy);

      return (
        <div>
          <KpiRow kpis={kpis} />
          <div style={{ marginTop: '24px' }}>
            <GridControls
              sortBy={sortBy}
              filterText={filterText}
              onSortChange={setSortBy}
              onFilterChange={setFilterText}
            />
            {repos.length === 0
              ? <EmptyState />
              : (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
                  gap: '16px',
                }}>
                  {sorted.map(repo => <ProjectCard key={repo.id} repo={repo} onDelete={(id) => {
                    setData(prev => prev ? { ...prev, repos: prev.repos.filter(r => r.id !== id) } : prev);
                  }} />)}
                </div>
              )
            }
          </div>
        </div>
      );
    }

    // ── Project Detail Components ─────────────────────────────────────────────

    function DetailHeader({ repo, selectedBranch, onGoToBranches }) {
      const [showUpdatePath, setShowUpdatePath] = useState(false);
      const [newPath, setNewPath] = useState('');
      const [saving, setSaving] = useState(false);

      const scanAge = repo.working_state && repo.working_state.checked_at
        ? timeAgo(repo.working_state.checked_at)
        : (repo.last_full_scan_at ? timeAgo(repo.last_full_scan_at) : 'never');

      const pathMissing = repo.path_exists === false;

      function handleRemove() {
        fetch(`/api/repos/${repo.id}`, { method: 'DELETE' })
          .then(() => { window.location.hash = '#/fleet'; })
          .catch(() => {});
      }

      function handleSavePath() {
        if (!newPath.trim()) return;
        setSaving(true);
        fetch(`/api/repos/${repo.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: newPath.trim() }),
        })
          .then(r => {
            setSaving(false);
            if (r.ok) {
              setShowUpdatePath(false);
              setNewPath('');
              // Reload repo detail
              window.location.hash = `#/repo/${repo.id}`;
            }
          })
          .catch(() => setSaving(false));
      }

      return (
        <div className="detail-header">
          <div>
            <button
              className="detail-back-btn"
              onClick={() => { window.location.hash = '#/fleet'; }}
              aria-label="Back to fleet"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                <path d="M9 2L4 7L9 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              Back
            </button>
            <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '4px' }}>
              {repo.name}
            </h1>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: pathMissing ? 'var(--status-red)' : 'var(--text-muted)', marginBottom: '6px' }}>
              {repo.path}{pathMissing && ' — Path not found'}
            </p>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-secondary)' }}>
              <RuntimeBadge runtime={repo.runtime} />
              <span
                onClick={onGoToBranches}
                style={{ cursor: 'pointer', borderBottom: '1px dotted var(--text-muted)' }}
                title="Switch branch"
              >
                {selectedBranch || repo.default_branch}
              </span>
              <span>·</span>
              <span>Last scanned {scanAge}</span>
            </div>
            {pathMissing && (
              <div style={{ display: 'flex', gap: '8px', marginTop: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  className="btn btn-secondary"
                  style={{ color: 'var(--status-red)' }}
                  onClick={handleRemove}
                >
                  Remove
                </button>
                <button
                  className="btn btn-secondary"
                  onClick={() => setShowUpdatePath(v => !v)}
                >
                  Update Path
                </button>
                {showUpdatePath && (
                  <>
                    <input
                      type="text"
                      value={newPath}
                      onChange={e => setNewPath(e.target.value)}
                      placeholder="New absolute path…"
                      style={{
                        fontFamily: 'var(--font-mono)', fontSize: '13px',
                        background: 'var(--bg-input)', border: '1px solid var(--border-default)',
                        borderRadius: 'var(--radius-sm)', padding: '5px 10px',
                        color: 'var(--text-primary)', width: '320px',
                      }}
                    />
                    <button
                      className="btn btn-secondary"
                      onClick={handleSavePath}
                      disabled={saving}
                    >
                      {saving ? 'Saving…' : 'Save'}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          <button
            style={{
              background: 'none',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              fontFamily: 'var(--font-body)',
              fontSize: '13px',
              color: 'var(--text-secondary)',
              padding: '6px 14px',
              transition: 'border-color var(--transition-fast), color var(--transition-fast)',
              marginTop: '24px',
            }}
            onClick={() => {}}
            title="Scan Now (not yet wired)"
          >
            Scan Now
          </button>
        </div>
      );
    }

    const SUB_TABS = [
      { id: 'activity', label: 'Activity' },
      { id: 'deps', label: 'Dependencies' },
      { id: 'branches', label: 'Branches' },
      { id: 'commits', label: 'Commits' },
    ];

    function SubTabNav({ active, onChange }) {
      return (
        <nav className="sub-tab-nav" role="tablist">
          {SUB_TABS.map(t => (
            <button
              key={t.id}
              role="tab"
              aria-selected={active === t.id}
              className={'sub-tab-btn' + (active === t.id ? ' active' : '')}
              onClick={() => onChange(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      );
    }

    const TIME_RANGES = [
      { label: '30d', days: 30 },
      { label: '90d', days: 90 },
      { label: '180d', days: 180 },
      { label: '1y',  days: 365 },
      { label: 'All', days: 9999 },
    ];

    function TimeRangeSelector({ selected, onChange }) {
      return (
        <div className="time-range-group" role="group" aria-label="Time range">
          {TIME_RANGES.map(r => (
            <button
              key={r.days}
              className={'time-range-btn' + (selected === r.days ? ' active' : '')}
              onClick={() => onChange(r.days)}
            >
              {r.label}
            </button>
          ))}
        </div>
      );
    }

    function fillDateGaps(data, days) {
      const map = {};
      data.forEach(d => { map[d.date] = d; });
      const result = [];
      const today = new Date();
      const limit = days >= 9999 ? (data.length > 0 ? null : 90) : days;
      if (limit === null) {
        // "All" mode: just return sorted data without gap filling beyond first date
        if (data.length === 0) return [];
        // Fill from earliest date to today
        const earliest = data[0].date;
        const start = new Date(earliest + 'T00:00:00');
        const end = new Date();
        for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
          const dateStr = d.toISOString().slice(0, 10);
          result.push(map[dateStr] || { date: dateStr, commits: 0, insertions: 0, deletions: 0, files_changed: 0 });
        }
        return result;
      }
      for (let i = limit - 1; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        const dateStr = d.toISOString().slice(0, 10);
        result.push(map[dateStr] || { date: dateStr, commits: 0, insertions: 0, deletions: 0, files_changed: 0 });
      }
      return result;
    }

    function ActivityChart({ data }) {
      const { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } = Recharts;

      if (!data || data.length === 0) {
        return (
          <div style={{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '14px' }}>
            No activity data for this period
          </div>
        );
      }

      // Negate deletions so they plot downward; compute net
      const chartData = data.map(d => ({
        date: d.date,
        insertions: d.insertions,
        deletions: -d.deletions,
        net: d.insertions - d.deletions,
        commits: d.commits,
      }));

      function CustomTooltip({ active, payload, label }) {
        if (!active || !payload || !payload.length) return null;
        const ins = payload.find(p => p.dataKey === 'insertions');
        const del = payload.find(p => p.dataKey === 'deletions');
        const net = payload.find(p => p.dataKey === 'net');
        const cmt = payload.find(p => p.dataKey === 'commits');
        const rawDel = del ? Math.abs(del.value) : 0;
        const netVal = net ? net.value : 0;
        return (
          <div style={{
            background: 'var(--bg-card)', border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-sm)', padding: '10px 14px',
            fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-secondary)',
            lineHeight: '1.7',
          }}>
            <div style={{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: '4px' }}>{label}</div>
            <div style={{ color: 'var(--status-green)' }}>+{ins ? ins.value : 0} insertions</div>
            <div style={{ color: 'var(--status-red)' }}>-{rawDel} deletions</div>
            <div style={{ color: 'var(--accent-blue)' }}>net {netVal >= 0 ? '+' : ''}{netVal}</div>
            <div>{cmt ? cmt.value : 0} commits</div>
          </div>
        );
      }

      // Show a tick every 7 data points
      const tickInterval = Math.max(Math.floor(chartData.length / 10), 6);

      return (
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={chartData} stackOffset="sign" margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fontFamily: 'var(--font-mono)', fontSize: 11, fill: 'var(--text-muted)' }}
              interval={tickInterval}
              tickLine={false}
              axisLine={{ stroke: 'var(--border-default)' }}
            />
            <YAxis
              tick={{ fontFamily: 'var(--font-mono)', fontSize: 11, fill: 'var(--text-muted)' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={v => v < 0 ? String(-v) : String(v)}
            />
            <ReferenceLine y={0} stroke="var(--border-default)" strokeWidth={1} />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="insertions"
              stackId="stack"
              fill="var(--status-green)"
              fillOpacity={0.2}
              stroke="var(--status-green)"
              strokeWidth={1.5}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="deletions"
              stackId="stack"
              fill="var(--status-red)"
              fillOpacity={0.2}
              stroke="var(--status-red)"
              strokeWidth={1.5}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="net"
              fill="none"
              stroke="var(--accent-blue)"
              strokeWidth={2}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      );
    }

    function ActivityTab({ repoId }) {
      const [selectedDays, setSelectedDays] = useState(90);
      const [historyData, setHistoryData] = useState(null);

      useEffect(() => {
        setHistoryData(null);
        fetch(`/api/repos/${repoId}/history?days=${selectedDays}`)
          .then(r => r.json())
          .then(d => {
            const filled = fillDateGaps(d.data || [], selectedDays);
            setHistoryData(filled);
          })
          .catch(() => setHistoryData([]));
      }, [repoId, selectedDays]);

      return (
        <div>
          <TimeRangeSelector selected={selectedDays} onChange={setSelectedDays} />
          {historyData === null
            ? <div style={{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '14px' }}>Loading…</div>
            : <ActivityChart data={historyData} />
          }
        </div>
      );
    }

    function CommitsTab({ repoId, branch }) {
      const PER_PAGE = 25;
      const [commits, setCommits] = useState([]);
      const [page, setPage] = useState(1);
      const [total, setTotal] = useState(0);
      const [loading, setLoading] = useState(true);

      // Reset to page 1 when branch changes
      useEffect(() => { setPage(1); }, [branch]);

      useEffect(() => {
        setLoading(true);
        const branchParam = branch ? `&branch=${encodeURIComponent(branch)}` : '';
        fetch(`/api/repos/${repoId}/commits?page=${page}&per_page=${PER_PAGE}${branchParam}`)
          .then(r => r.json())
          .then(data => {
            setCommits(data.commits || []);
            setTotal(data.total || 0);
            setLoading(false);
          })
          .catch(() => setLoading(false));
      }, [repoId, page, branch]);

      const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

      function fmtDate(isoStr) {
        if (!isoStr) return '—';
        return isoStr.slice(0, 10);
      }

      if (loading) {
        return <div className="table-empty">Loading…</div>;
      }

      return (
        <div>
          {branch && (
            <div style={{
              fontSize: '12px', fontFamily: 'var(--font-heading)', fontWeight: 600,
              color: 'var(--accent-blue)', marginBottom: '10px',
              textTransform: 'uppercase', letterSpacing: '0.5px',
              display: 'flex', alignItems: 'center', gap: '6px',
            }}>
              <span style={{ color: 'var(--text-muted)' }}>Branch:</span>
              {branch}
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 400,
                color: 'var(--text-muted)', textTransform: 'none',
              }}>
                ({total} {total === 1 ? 'commit' : 'commits'})
              </span>
            </div>
          )}
          <div className="table-container">
            <div className="table-header" style={{ gridTemplateColumns: '120px 1fr 110px 70px' }}>
              <span>Date</span>
              <span>Message</span>
              <span>+/-</span>
              <span>Files</span>
            </div>
            {commits.length === 0 ? (
              <div className="table-empty">No commits found</div>
            ) : commits.map(c => (
              <div key={c.hash} className="table-row" style={{ gridTemplateColumns: '120px 1fr 110px 70px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}>
                  {fmtDate(c.date)}
                </span>
                <span style={{ fontFamily: 'var(--font-body)', fontSize: '14px', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {c.message && c.message.length > 80 ? c.message.slice(0, 80) + '…' : (c.message || '')}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}>
                  <span style={{ color: 'var(--status-green)' }}>+{c.insertions}</span>
                  {' '}
                  <span style={{ color: 'var(--status-red)' }}>-{c.deletions}</span>
                </span>
                <span style={{ fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)' }}>
                  {c.files_changed}
                </span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '12px' }}>
            <button
              className="btn btn-secondary"
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
            >Prev</button>
            <span style={{ fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-secondary)' }}>
              Page {page} of {totalPages}
            </span>
            <button
              className="btn btn-secondary"
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
            >Next</button>
          </div>
        </div>
      );
    }

    function BranchesTab({ repoId, selectedBranch, onSelectBranch }) {
      const [branches, setBranches] = useState([]);
      const [loading, setLoading] = useState(true);

      useEffect(() => {
        setLoading(true);
        fetch(`/api/repos/${repoId}/branches`)
          .then(r => r.json())
          .then(data => {
            setBranches(data.branches || []);
            setLoading(false);
          })
          .catch(() => setLoading(false));
      }, [repoId]);

      const STALE_THRESHOLD_DAYS = 30;
      function staleDays(dateStr) {
        if (!dateStr) return 0;
        const ms = Date.now() - new Date(dateStr).getTime();
        return Math.floor(ms / (1000 * 60 * 60 * 24));
      }
      function isStale(dateStr) {
        if (!dateStr) return true;
        return staleDays(dateStr) > STALE_THRESHOLD_DAYS;
      }

      function fmtDate(isoStr) {
        if (!isoStr) return '—';
        return isoStr.slice(0, 10);
      }

      if (loading) {
        return <div className="table-empty">Loading…</div>;
      }

      const gridCols = '1fr 80px 110px 70px 120px 130px';

      return (
        <div className="table-container">
          <div className="table-header" style={{ gridTemplateColumns: gridCols }}>
            <span>Branch</span>
            <span>Commits</span>
            <span>+/\u2212</span>
            <span>Files</span>
            <span>Last Commit</span>
            <span>Status</span>
          </div>
          {branches.length === 0 ? (
            <div className="table-empty">No branches found</div>
          ) : branches.map(b => {
            const isSelected = selectedBranch === b.name;
            return (
              <div
                key={b.name}
                className="table-row"
                style={{
                  gridTemplateColumns: gridCols,
                  cursor: 'pointer',
                  borderLeft: isSelected ? '2px solid var(--accent-blue)' : '2px solid transparent',
                  background: isSelected ? 'var(--accent-blue-dim)' : undefined,
                }}
                onClick={() => onSelectBranch(b.name)}
                title={'View commits for ' + b.name}
              >
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: '14px',
                  color: isSelected ? 'var(--accent-blue)' : 'var(--text-primary)',
                  fontWeight: isSelected ? 600 : 400,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {b.name}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}>
                  {b.is_default ? '\u2014' : (b.commits_ahead || 0)}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}>
                  {b.is_default ? (
                    <span style={{ color: 'var(--text-muted)' }}>\u2014</span>
                  ) : (b.insertions || b.deletions) ? (
                    <>
                      <span style={{ color: 'var(--status-green)' }}>+{b.insertions || 0}</span>
                      {' '}
                      <span style={{ color: 'var(--status-red)' }}>\u2212{b.deletions || 0}</span>
                    </>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>0</span>
                  )}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}>
                  {b.is_default ? '\u2014' : (b.files_changed || 0)}
                </span>
                <span style={{ fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-secondary)' }}>
                  {fmtDate(b.last_commit_date)}
                </span>
                <span>
                  {b.is_default ? (
                    <span style={{ color: 'var(--accent-blue)', background: 'var(--accent-blue-dim)', fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500, padding: '2px 8px', borderRadius: '4px' }}>
                      default
                    </span>
                  ) : isStale(b.last_commit_date) ? (
                    <span style={{ color: 'var(--status-orange)', background: 'var(--status-orange-bg)', fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500, padding: '2px 8px', borderRadius: '4px' }}>
                      stale ({staleDays(b.last_commit_date)}d)
                    </span>
                  ) : (
                    <span style={{ fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-muted)' }}>
                      active
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      );
    }

    function DepsTab({ repoId, depCheckError, missingDepTools }) {
      const [managerGroups, setManagerGroups] = useState([]);
      const [loading, setLoading] = useState(true);
      const [scanning, setScanning] = useState(false);

      function fetchDeps() {
        setLoading(true);
        fetch(`/api/repos/${repoId}/deps`)
          .then(r => r.json())
          .then(data => {
            setManagerGroups(Array.isArray(data) ? data : []);
            setLoading(false);
          })
          .catch(() => setLoading(false));
      }

      useEffect(() => { fetchDeps(); }, [repoId]);

      function handleCheckNow() {
        setScanning(true);
        fetch(`/api/repos/${repoId}/scan/deps`, { method: 'POST' })
          .then(r => r.json())
          .then(data => {
            setManagerGroups(Array.isArray(data) ? data : []);
            setScanning(false);
          })
          .catch(() => setScanning(false));
      }

      function severityColor(severity) {
        switch (severity) {
          case 'ok':         return 'var(--status-green)';
          case 'outdated':   return 'var(--status-yellow)';
          case 'major':      return 'var(--status-orange)';
          case 'vulnerable': return 'var(--status-red)';
          default:           return 'var(--text-muted)';
        }
      }

      function severityText(pkg) {
        switch (pkg.severity) {
          case 'ok':         return 'up to date';
          case 'outdated':   return 'outdated';
          case 'major':      return 'major update';
          case 'vulnerable': return pkg.advisory_id || 'vulnerable';
          default:           return pkg.severity || '—';
        }
      }

      // Collect all packages needing attention (anything not 'ok') across all groups
      const issuePackages = useMemo(() => {
        const sevOrder = { vulnerable: 0, major: 1, outdated: 2 };
        const items = [];
        for (const group of managerGroups) {
          for (const pkg of group.packages) {
            if (pkg.severity && pkg.severity !== 'ok') {
              items.push({ ...pkg, _manager: group.manager, _label: group.label || group.manager });
            }
          }
        }
        items.sort((a, b) => {
          const sa = sevOrder[a.severity] ?? 99;
          const sb = sevOrder[b.severity] ?? 99;
          if (sa !== sb) return sa - sb;
          return a.name.localeCompare(b.name);
        });
        return items;
      }, [managerGroups]);

      // Export helpers
      function downloadBlob(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }

      function handleExportJSON() {
        const json = JSON.stringify(managerGroups, null, 2);
        downloadBlob(json, 'deps-export.json', 'application/json');
      }

      function handleExportMD() {
        let md = '# Dependency Report\\n\\n';

        // Issues section
        if (issuePackages.length > 0) {
          md += '## Attention Required\\n\\n';
          md += '| Package | Current | Latest | Status | Source |\\n';
          md += '|---------|---------|--------|--------|--------|\\n';
          for (const pkg of issuePackages) {
            const status = pkg.severity === 'vulnerable'
              ? (pkg.advisory_id || 'vulnerable')
              : pkg.severity === 'major' ? 'major update' : 'outdated';
            md += `| ${pkg.name} | ${pkg.current_version || '—'} | ${pkg.latest_version || '—'} | ${status} | ${pkg._label} |\\n`;
          }
          md += '\\n';
        }

        // All dependencies by group
        md += '## All Dependencies\\n\\n';
        for (const group of managerGroups) {
          md += `### ${group.label || group.manager}\\n\\n`;
          md += '| Package | Current | Latest | Status |\\n';
          md += '|---------|---------|--------|--------|\\n';
          for (const pkg of group.packages) {
            md += `| ${pkg.name} | ${pkg.current_version || '—'} | ${pkg.latest_version || '—'} | ${severityText(pkg)} |\\n`;
          }
          md += '\\n';
        }

        downloadBlob(md, 'deps-export.md', 'text/markdown');
      }

      if (loading) {
        return <div className="table-empty">Loading…</div>;
      }

      if (managerGroups.length === 0) {
        return (
          <div className="table-container">
            <div className="table-empty">No dependencies detected</div>
          </div>
        );
      }

      return (
        <div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginBottom: '12px' }}>
            <button
              className="btn btn-secondary"
              onClick={handleExportMD}
              title="Export as Markdown"
            >
              Export MD
            </button>
            <button
              className="btn btn-secondary"
              onClick={handleExportJSON}
              title="Export as JSON"
            >
              Export JSON
            </button>
            <button
              className="btn btn-secondary"
              onClick={handleCheckNow}
              disabled={scanning}
            >
              {scanning ? 'Checking…' : 'Check Now'}
            </button>
          </div>

          {/* Missing tools notice */}
          {missingDepTools && missingDepTools.length > 0 && (
            <div style={{
              padding: '10px 14px', marginBottom: '16px',
              fontSize: '13px', fontFamily: 'var(--font-body)',
              color: 'var(--status-orange)',
              background: 'var(--status-orange-bg)',
              borderRadius: '6px',
              borderLeft: '2px solid var(--status-orange)',
              lineHeight: '1.5',
            }}>
              <span style={{ fontWeight: 600 }}>Incomplete analysis</span>
              <span style={{ color: 'var(--text-secondary)' }}> — missing tools for this repo:</span>
              <div style={{ marginTop: '4px' }}>
                {missingDepTools.map(t => (
                  <div key={t.tool || t} style={{
                    fontFamily: 'var(--font-mono)', fontSize: '12px',
                    color: 'var(--text-secondary)', paddingLeft: '8px',
                  }}>
                    <span style={{ color: 'var(--status-orange)' }}>{t.tool || t}</span>
                    {t.description && <span> — {t.description}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Attention Required section */}
          {issuePackages.length > 0 ? (
            <div style={{ marginBottom: '28px' }}>
              <div style={{
                fontSize: '12px', fontFamily: 'var(--font-heading)', fontWeight: 600,
                color: 'var(--status-red)', marginBottom: '8px',
                textTransform: 'uppercase', letterSpacing: '0.5px',
              }}>
                Attention Required
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 400,
                  color: 'var(--text-secondary)', textTransform: 'none',
                  marginLeft: '8px',
                }}>
                  {issuePackages.length} {issuePackages.length === 1 ? 'issue' : 'issues'}
                </span>
              </div>
              <div className="table-container" style={{
                borderLeft: '2px solid var(--status-red)',
              }}>
                <div className="table-header" style={{ gridTemplateColumns: 'minmax(120px, 1fr) 100px 100px 130px minmax(150px, 2fr)' }}>
                  <span>Package</span>
                  <span>Current</span>
                  <span>Latest</span>
                  <span>Status</span>
                  <span>Source</span>
                </div>
                {issuePackages.map(pkg => (
                  <div key={pkg.name + pkg._label} className="table-row"
                    style={{ gridTemplateColumns: 'minmax(120px, 1fr) 100px 100px 130px minmax(150px, 2fr)' }}>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '14px',
                      color: 'var(--text-primary)',
                    }}>
                      {pkg.name}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '13px',
                      color: 'var(--text-secondary)',
                    }}>
                      {pkg.current_version || '—'}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '13px',
                      color: 'var(--text-secondary)',
                      fontWeight: (pkg.current_version !== pkg.latest_version) ? 600 : 400,
                    }}>
                      {pkg.latest_version || '—'}
                    </span>
                    <span style={{
                      color: severityColor(pkg.severity), fontSize: '13px',
                      fontFamily: 'var(--font-body)',
                      fontWeight: pkg.severity === 'vulnerable' ? 600 : 400,
                    }}>
                      {severityText(pkg)}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '11px',
                      color: 'var(--text-muted)',
                    }}>
                      {pkg._label}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={{
              padding: '12px 16px', marginBottom: '24px',
              fontSize: '13px', fontFamily: 'var(--font-body)',
              color: 'var(--status-green)',
              background: 'var(--status-green-bg)',
              borderRadius: '6px',
              borderLeft: '2px solid var(--status-green)',
            }}>
              No issues found — all dependencies are up to date.
            </div>
          )}

          {/* All Dependencies section */}
          <div style={{
            fontSize: '12px', fontFamily: 'var(--font-heading)', fontWeight: 600,
            color: 'var(--text-muted)', marginBottom: '12px',
            textTransform: 'uppercase', letterSpacing: '0.5px',
          }}>
            All Dependencies
          </div>
          {managerGroups.map((group, gi) => (
            <div key={group.label || group.manager + gi} style={{ marginBottom: '24px' }}>
              <div style={{
                fontSize: '12px', fontFamily: 'var(--font-heading)', fontWeight: 600,
                color: 'var(--text-muted)', marginBottom: '8px',
                textTransform: 'uppercase', letterSpacing: '0.5px',
              }}>
                {group.label || group.manager}
                {group.source_path && (
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 400,
                    color: 'var(--text-secondary)', textTransform: 'none',
                    marginLeft: '8px',
                  }}>
                    {group.source_path}
                  </span>
                )}
              </div>
              <div className="table-container">
                <div className="table-header" style={{ gridTemplateColumns: '1fr 100px 100px 160px' }}>
                  <span>Package</span>
                  <span>Current</span>
                  <span>Latest</span>
                  <span>Status</span>
                </div>
                {group.packages.map(pkg => (
                  <div key={pkg.name} className="table-row"
                    style={{ gridTemplateColumns: '1fr 100px 100px 160px' }}>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '14px',
                      color: 'var(--text-primary)',
                    }}>
                      {pkg.name}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '13px',
                      color: 'var(--text-secondary)',
                    }}>
                      {pkg.current_version || '—'}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '13px',
                      color: 'var(--text-secondary)',
                      fontWeight: (pkg.current_version !== pkg.latest_version) ? 600 : 400,
                    }}>
                      {pkg.latest_version || '—'}
                    </span>
                    <span style={{
                      color: severityColor(pkg.severity), fontSize: '13px',
                      fontFamily: 'var(--font-body)',
                      fontWeight: pkg.severity === 'vulnerable' ? 600 : 400,
                    }}>
                      {severityText(pkg)}
                    </span>
                  </div>
                ))}
              </div>
              <div style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                fontSize: '13px', fontFamily: 'var(--font-body)',
                color: 'var(--text-muted)', marginTop: '6px',
              }}>
                Last checked: {timeAgo(group.checked_at)}
                {depCheckError && (
                  <>
                    <span style={{
                      display: 'inline-block', width: '6px', height: '6px',
                      borderRadius: '50%', background: 'var(--status-orange)',
                      flexShrink: 0,
                    }} />
                    <span style={{ color: 'var(--status-orange)', fontSize: '12px' }}>offline</span>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      );
    }

    function PlaceholderTab({ text }) {
      return (
        <div className="table-container">
          <div className="table-empty">{text} — coming in a later packet</div>
        </div>
      );
    }

    function ProjectDetail({ repoId, initialSubTab }) {
      const [repo, setRepo] = useState(null);
      const [activeSubTab, setActiveSubTab] = useState(initialSubTab || 'activity');
      const [selectedBranch, setSelectedBranch] = useState(null);

      useEffect(() => {
        setRepo(null);
        setSelectedBranch(null);
        fetch(`/api/repos/${repoId}`)
          .then(r => r.json())
          .then(data => {
            setRepo(data);
            // Initialize selected branch to current branch or default branch
            const ws = data.working_state;
            setSelectedBranch(
              (ws && ws.current_branch) || data.default_branch || 'main'
            );
          })
          .catch(() => {});
      }, [repoId]);

      useEffect(() => {
        const handler = (e) => {
          if (e.key === 'Escape' && !e.defaultPrevented) {
            window.location.hash = '#/fleet';
          }
        };
        document.addEventListener('keydown', handler);
        return () => document.removeEventListener('keydown', handler);
      }, []);

      function handleSubTabChange(tabId) {
        setActiveSubTab(tabId);
        window.location.hash = `#/repo/${repoId}/${tabId}`;
      }

      function handleSelectBranch(branchName) {
        setSelectedBranch(branchName);
        // Auto-navigate to commits tab after selecting a branch
        setActiveSubTab('commits');
        window.location.hash = `#/repo/${repoId}/commits`;
      }

      if (!repo) {
        return (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '14px' }}>
            Loading…
          </div>
        );
      }

      return (
        <div className="detail-view">
          <DetailHeader repo={repo} selectedBranch={selectedBranch} onGoToBranches={() => handleSubTabChange('branches')} />
          <SubTabNav active={activeSubTab} onChange={handleSubTabChange} />
          <div className="detail-content">
            {activeSubTab === 'activity'  && <ActivityTab repoId={repoId} />}
            {activeSubTab === 'deps'      && <DepsTab repoId={repoId} depCheckError={!!(repo.working_state && repo.working_state.dep_check_error)} missingDepTools={(repo.working_state && repo.working_state.missing_dep_tools) || []} />}
            {activeSubTab === 'branches'  && <BranchesTab repoId={repoId} selectedBranch={selectedBranch} onSelectBranch={handleSelectBranch} />}
            {activeSubTab === 'commits'   && <CommitsTab repoId={repoId} branch={selectedBranch} />}
          </div>
        </div>
      );
    }

    // ── Heatmap ───────────────────────────────────────────────────────────────
    function heatmapColor(count, maxCount) {
      if (count === 0) return 'var(--bg-secondary)';
      const pct = count / maxCount;
      if (pct <= 0.25) return 'rgba(76,141,255,0.2)';
      if (pct <= 0.50) return 'rgba(76,141,255,0.4)';
      if (pct <= 0.75) return 'rgba(76,141,255,0.65)';
      return 'rgba(76,141,255,0.9)';
    }

    function Heatmap({ data, maxCount, loading }) {
      const [internalData, setInternalData] = useState(data || []);
      const [internalMax, setInternalMax]   = useState(maxCount || 0);
      const [isLoading, setIsLoading]       = useState(loading !== undefined ? loading : !data);
      const [tooltip, setTooltip]           = useState(null);

      useEffect(() => {
        if (data !== undefined) {
          setInternalData(data);
          setInternalMax(maxCount || 0);
          setIsLoading(false);
          return;
        }
        setIsLoading(true);
        fetch('/api/analytics/heatmap?days=365')
          .then(r => r.json())
          .then(body => {
            setInternalData(body.data || []);
            setInternalMax(body.max_count || 0);
            setIsLoading(false);
          })
          .catch(() => setIsLoading(false));
      }, [data, maxCount]);

      if (isLoading) {
        return <div style={{ padding: '16px', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}>Loading…</div>;
      }

      // Build a Map<dateString, count> for O(1) lookups
      const countMap = new Map();
      for (const entry of internalData) {
        countMap.set(entry.date, entry.count);
      }

      // Build 52 weeks × 7 days grid.
      // today is the last cell (col 51, row today.getDay()).
      // We start from the Sunday of the week 51 weeks ago.
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const todayDay = today.getDay(); // 0=Sun … 6=Sat

      // Start of the leftmost week: Sunday, 51 weeks + todayDay days ago
      const gridStart = new Date(today);
      gridStart.setDate(gridStart.getDate() - (51 * 7 + todayDay));

      // cells[col][row] = Date
      const cells = [];
      for (let col = 0; col < 52; col++) {
        const week = [];
        for (let row = 0; row < 7; row++) {
          const d = new Date(gridStart);
          d.setDate(d.getDate() + col * 7 + row);
          week.push(d);
        }
        cells.push(week);
      }

      // Month labels: find which column each month first appears in
      const monthLabels = [];
      let lastMonth = -1;
      for (let col = 0; col < 52; col++) {
        const m = cells[col][0].getMonth();
        if (m !== lastMonth) {
          const names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
          monthLabels.push({ col, label: names[m] });
          lastMonth = m;
        }
      }

      const CELL = 12;
      const GAP  = 2;
      const step = CELL + GAP;

      const gridWidth  = 52 * step - GAP;
      const gridHeight = 7  * step - GAP;

      const dayLabelStyle = {
        fontFamily: 'var(--font-body)',
        fontSize: '11px',
        color: 'var(--text-muted)',
        height: `${CELL}px`,
        lineHeight: `${CELL}px`,
        marginBottom: `${GAP}px`,
        userSelect: 'none',
      };

      return (
        <div data-heatmap-root style={{ position: 'relative', display: 'inline-block' }}>
          {/* Month labels */}
          <div style={{ display: 'flex', marginLeft: '36px', marginBottom: '4px', position: 'relative', height: '16px' }}>
            {monthLabels.map(({ col, label }) => (
              <span
                key={col + '-' + label}
                style={{
                  position: 'absolute',
                  left: `${col * step}px`,
                  fontFamily: 'var(--font-body)',
                  fontSize: '11px',
                  color: 'var(--text-muted)',
                  userSelect: 'none',
                }}
              >{label}</span>
            ))}
          </div>

          <div style={{ display: 'flex', alignItems: 'flex-start' }}>
            {/* Day labels (Mon, Wed, Fri only) */}
            <div style={{ width: '30px', marginRight: '6px', flexShrink: 0 }}>
              {['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map((name, idx) => (
                <div key={idx} style={{ ...dayLabelStyle, visibility: (name === 'Mon' || name === 'Wed' || name === 'Fri') ? 'visible' : 'hidden' }}>
                  {name}
                </div>
              ))}
            </div>

            {/* Grid */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: `repeat(52, ${CELL}px)`,
                gridTemplateRows: `repeat(7, ${CELL}px)`,
                gap: `${GAP}px`,
              }}
            >
              {cells.map((week, col) =>
                week.map((cellDate, row) => {
                  const iso = cellDate.toISOString().slice(0, 10);
                  const count = countMap.get(iso) || 0;
                  const isFuture = cellDate > today;
                  const cellCount = isFuture ? 0 : count;
                  const bgColor = heatmapColor(cellCount, internalMax);
                  const isHovered = tooltip && tooltip.iso === iso;
                  return (
                    <div
                      key={iso}
                      style={{
                        width: `${CELL}px`,
                        height: `${CELL}px`,
                        backgroundColor: bgColor,
                        borderRadius: '2px',
                        cursor: 'default',
                        outline: isHovered ? '2px solid var(--accent-blue)' : 'none',
                        outlineOffset: '-1px',
                      }}
                      onMouseEnter={(e) => {
                        const rect = e.currentTarget.getBoundingClientRect();
                        const containerRect = e.currentTarget.closest('[data-heatmap-root]')?.getBoundingClientRect() || rect;
                        setTooltip({ iso, count: cellCount, x: rect.left - containerRect.left, y: rect.top - containerRect.top });
                      }}
                      onMouseLeave={() => setTooltip(null)}
                    />
                  );
                })
              )}
            </div>
          </div>

          {/* Tooltip */}
          {tooltip && (
            <div
              style={{
                position: 'fixed',
                left: tooltip.x + 16,
                top: tooltip.y,
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-sm)',
                padding: '8px 12px',
                pointerEvents: 'none',
                zIndex: 999,
                fontSize: '12px',
                fontFamily: 'var(--font-body)',
                color: 'var(--text-primary)',
                whiteSpace: 'nowrap',
              }}
            >
              {new Date(tooltip.iso + 'T12:00:00').toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}: {tooltip.count} commits
            </div>
          )}
        </div>
      );
    }

    // ── TimeAllocation ───────────────────────────────────────────────────────
    const ALLOC_COLORS = [
      '#4c8dff', '#34d399', '#fbbf24', '#f97316', '#ef4444',
      '#a78bfa', '#ec4899', '#06b6d4', '#84cc16', '#f43f5e'
    ];

    function aggregateWeekly(data) {
      const weeks = {};
      data.forEach(({ date, commits }) => {
        const d = new Date(date + 'T00:00:00');
        const day = d.getDay();
        const monday = new Date(d);
        monday.setDate(d.getDate() - ((day + 6) % 7));
        const key = monday.toISOString().slice(0, 10);
        weeks[key] = (weeks[key] || 0) + commits;
      });
      return Object.entries(weeks)
        .map(([date, commits]) => ({ date, commits }))
        .sort((a, b) => a.date.localeCompare(b.date));
    }

    function TimeAllocation() {
      const [selectedDays, setSelectedDays] = useState(90);
      const [series, setSeries] = useState([]);
      const [loading, setLoading] = useState(true);
      const [hidden, setHidden] = useState(new Set());

      useEffect(() => {
        setLoading(true);
        fetch('/api/analytics/allocation?days=' + selectedDays)
          .then(r => r.json())
          .then(body => {
            setSeries(body.series || []);
            setHidden(new Set());
            setLoading(false);
          })
          .catch(() => setLoading(false));
      }, [selectedDays]);

      // Process series: weekly aggregation when days >= 90
      const processedSeries = React.useMemo(() => {
        let s = series.map(repo => ({
          ...repo,
          data: selectedDays >= 90 ? aggregateWeekly(repo.data) : repo.data,
        }));

        // Sort by total commits descending for color assignment
        s = s.map(repo => ({
          ...repo,
          total: repo.data.reduce((sum, d) => sum + d.commits, 0),
        })).sort((a, b) => b.total - a.total);

        // Group beyond 10 into "Other"
        if (s.length > 10) {
          const top10 = s.slice(0, 10);
          const rest = s.slice(10);
          // Merge rest into a single "Other" series
          const otherMap = {};
          rest.forEach(repo => {
            repo.data.forEach(({ date, commits }) => {
              otherMap[date] = (otherMap[date] || 0) + commits;
            });
          });
          const otherData = Object.entries(otherMap)
            .map(([date, commits]) => ({ date, commits }))
            .sort((a, b) => a.date.localeCompare(b.date));
          top10.push({ repo_id: '__other__', name: 'Other', data: otherData, total: 0 });
          return top10;
        }
        return s;
      }, [series, selectedDays]);

      // Build merged chart data array for Recharts
      const chartData = React.useMemo(() => {
        if (processedSeries.length === 0) return [];
        const allDates = new Set();
        processedSeries.forEach(s => s.data.forEach(d => allDates.add(d.date)));
        return [...allDates].sort().map(date => {
          const entry = { date };
          processedSeries.forEach(s => {
            const match = s.data.find(d => d.date === date);
            entry[s.name] = match ? match.commits : 0;
          });
          return entry;
        });
      }, [processedSeries]);

      function toggleSeries(name) {
        setHidden(prev => {
          const next = new Set(prev);
          if (next.has(name)) next.delete(name);
          else next.add(name);
          return next;
        });
      }

      const { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } = Recharts;

      const axisTickStyle = { fontSize: 11, fontFamily: 'var(--font-mono)', fill: 'var(--text-muted)' };

      if (loading) {
        return (
          <div style={{ padding: '16px', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}>
            Loading…
          </div>
        );
      }

      return (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
            <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '14px', color: 'var(--text-primary)', margin: 0 }}>
              Time Allocation
            </h3>
            <TimeRangeSelector selected={selectedDays} onChange={setSelectedDays} />
          </div>

          {chartData.length === 0 ? (
            <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}>
              No commit data in this range.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={chartData} stackOffset="none" margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
                <XAxis dataKey="date" tick={axisTickStyle} tickLine={false} axisLine={false} />
                <YAxis tick={axisTickStyle} tickLine={false} axisLine={false} width={36} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'var(--bg-card)',
                    border: '1px solid var(--border-default)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '8px 12px',
                    fontSize: '12px',
                    fontFamily: 'var(--font-body)',
                  }}
                />
                {processedSeries.map((s, i) => {
                  const color = s.name === 'Other' ? 'var(--text-muted)' : ALLOC_COLORS[i % ALLOC_COLORS.length];
                  return (
                    <Area
                      key={s.name}
                      type="monotone"
                      dataKey={s.name}
                      stackId="1"
                      stroke={color}
                      fill={color}
                      fillOpacity={hidden.has(s.name) ? 0 : 0.75}
                      strokeOpacity={hidden.has(s.name) ? 0 : 1}
                      isAnimationActive={false}
                    />
                  );
                })}
              </AreaChart>
            </ResponsiveContainer>
          )}

          {/* Legend */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 20px', marginTop: '12px' }}>
            {processedSeries.map((s, i) => {
              const color = s.name === 'Other' ? 'var(--text-muted)' : ALLOC_COLORS[i % ALLOC_COLORS.length];
              const isHidden = hidden.has(s.name);
              return (
                <button
                  key={s.name}
                  onClick={() => toggleSeries(s.name)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: 0,
                    fontSize: '12px',
                    fontFamily: 'var(--font-body)',
                    color: isHidden ? 'var(--text-muted)' : 'var(--text-primary)',
                    opacity: isHidden ? 0.5 : 1,
                  }}
                >
                  <span style={{
                    display: 'inline-block',
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    backgroundColor: color,
                    flexShrink: 0,
                  }} />
                  {s.name}
                </button>
              );
            })}
          </div>
        </div>
      );
    }

    // ── DepOverlap ───────────────────────────────────────────────────────────
    function DepOverlap() {
      const [packages, setPackages] = useState([]);
      const [loading, setLoading] = useState(true);
      const [expanded, setExpanded] = useState(new Set());

      useEffect(() => {
        setLoading(true);
        fetch('/api/analytics/dep-overlap')
          .then(r => r.json())
          .then(body => {
            setPackages(body.packages || []);
            setLoading(false);
          })
          .catch(() => setLoading(false));
      }, []);

      function toggleExpanded(key) {
        setExpanded(prev => {
          const next = new Set(prev);
          if (next.has(key)) next.delete(key);
          else next.add(key);
          return next;
        });
      }

      if (loading) {
        return (
          <div style={{ padding: '16px', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}>
            Loading…
          </div>
        );
      }

      if (packages.length === 0) {
        return (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}>
            No shared dependencies found across repos.
          </div>
        );
      }

      return (
        <div>
          <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '14px', color: 'var(--text-primary)', margin: '0 0 12px 0' }}>
            Dependency Overlap
          </h3>
          <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Package</th>
                <th style={{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Manager</th>
                <th style={{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Used In</th>
                <th style={{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Version Spread</th>
              </tr>
            </thead>
            <tbody>
              {packages.map(pkg => {
                const key = pkg.name + ':' + pkg.manager;
                const isExpanded = expanded.has(key);
                return (
                  <React.Fragment key={key}>
                    <tr style={{ borderTop: '1px solid var(--border-default)' }}>
                      <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: '14px', color: 'var(--text-primary)' }}>
                        {pkg.name}
                      </td>
                      <td style={{ padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                        {pkg.manager}
                      </td>
                      <td style={{ padding: '8px 12px' }}>
                        <span
                          onClick={() => toggleExpanded(key)}
                          style={{ fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--accent-blue)', cursor: 'pointer' }}
                        >
                          {isExpanded ? '▾' : '▸'} {pkg.count} repos
                        </span>
                      </td>
                      <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}>
                        {pkg.version_spread}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr style={{ borderTop: '1px solid var(--border-default)' }}>
                        <td colSpan={4} style={{ paddingLeft: '24px', paddingBottom: '8px', paddingTop: '4px' }}>
                          {pkg.repos.map(repo => (
                            <div key={repo.repo_id} style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.6' }}>
                              {repo.name} — {repo.version !== null ? repo.version : '(unknown)'}
                            </div>
                          ))}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      );
    }

    // ── FleetDepsTab ──────────────────────────────────────────────────────────
    function FleetDepsTab() {
      const [repos, setRepos] = useState([]);
      const [loading, setLoading] = useState(true);

      useEffect(() => {
        setLoading(true);
        fetch('/api/fleet')
          .then(r => r.json())
          .then(data => {
            setRepos(data.repos || []);
            setLoading(false);
          })
          .catch(() => setLoading(false));
      }, []);

      const sectionHeaderStyle = {
        fontFamily: 'var(--font-heading)',
        fontSize: '18px',
        fontWeight: 600,
        color: 'var(--text-primary)',
        marginBottom: '16px',
      };

      const reposWithDeps = repos.filter(r => r.dep_summary && r.dep_summary.total > 0);
      const totalDeps = reposWithDeps.reduce((sum, r) => sum + (r.dep_summary?.total || 0), 0);
      const totalOutdated = reposWithDeps.reduce((sum, r) => sum + (r.dep_summary?.outdated || 0), 0);
      const totalVuln = reposWithDeps.reduce((sum, r) => sum + (r.dep_summary?.vulnerable || 0), 0);

      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
          {/* KPI summary */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px' }}>
            <KpiCard label="Total Deps" value={loading ? '...' : totalDeps} tooltip="Total dependencies detected across all repos" />
            <KpiCard label="Outdated" value={loading ? '...' : totalOutdated} tooltip="Dependencies with newer versions available (minor or major)" />
            <KpiCard label="Vulnerable" value={loading ? '...' : totalVuln} tooltip="Dependencies with known security vulnerabilities" />
            <KpiCard label="Repos w/ Deps" value={loading ? '...' : reposWithDeps.length} tooltip="Repos where at least one dependency manifest was detected" />
          </div>

          {/* Per-repo dep summaries */}
          <section>
            <h2 style={sectionHeaderStyle}>Per-Repo Health</h2>
            {loading ? (
              <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}>Loading...</div>
            ) : reposWithDeps.length === 0 ? (
              <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}>
                No dependencies detected. Run a Full Scan to discover dependencies in your repos.
              </div>
            ) : (
              <div className="table-container">
                <div className="table-header" style={{ gridTemplateColumns: '1fr 100px 100px 100px' }}>
                  <span>Repo</span>
                  <span>Total</span>
                  <span>Outdated</span>
                  <span>Vulnerable</span>
                </div>
                {reposWithDeps.map(r => (
                  <div
                    key={r.id}
                    className="table-row"
                    style={{ gridTemplateColumns: '1fr 100px 100px 100px', cursor: 'pointer' }}
                    onClick={() => { window.location.hash = '#/repo/' + r.id + '/deps'; }}
                  >
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', color: 'var(--text-primary)' }}>
                      {r.name}
                    </span>
                    <span style={{ fontSize: '13px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                      {r.dep_summary.total}
                    </span>
                    <span style={{ fontSize: '13px', fontFamily: 'var(--font-mono)', color: r.dep_summary.outdated > 0 ? 'var(--status-yellow)' : 'var(--text-muted)' }}>
                      {r.dep_summary.outdated}
                    </span>
                    <span style={{ fontSize: '13px', fontFamily: 'var(--font-mono)', color: r.dep_summary.vulnerable > 0 ? 'var(--status-red)' : 'var(--text-muted)' }}>
                      {r.dep_summary.vulnerable}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Dependency Overlap */}
          <section>
            <h2 style={sectionHeaderStyle}>Dependency Overlap</h2>
            <DepOverlap />
          </section>
        </div>
      );
    }

    // ── AnalyticsTab ─────────────────────────────────────────────────────────
    function AnalyticsTab() {
      const sectionHeaderStyle = {
        fontFamily: 'var(--font-heading)',
        fontSize: '18px',
        fontWeight: 600,
        color: 'var(--text-primary)',
        marginBottom: '16px',
      };

      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
          <section>
            <h2 style={sectionHeaderStyle}>Activity Heatmap</h2>
            <Heatmap />
          </section>
          <section>
            <h2 style={sectionHeaderStyle}>Time Allocation</h2>
            <TimeAllocation />
          </section>
          <section>
            <h2 style={sectionHeaderStyle}>Dependency Overlap</h2>
            <DepOverlap />
          </section>
        </div>
      );
    }

    // ── ContentArea ──────────────────────────────────────────────────────────
    function ContentArea({ route, refetchKey = 0 }) {
      const { tab, repoId } = route;
      const [visible, setVisible] = useState(false);

      useEffect(() => {
        setVisible(false);
        const t = setTimeout(() => setVisible(true), 10);
        return () => clearTimeout(t);
      }, [tab, repoId]);

      const areaStyle = {
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(8px)',
        transition: 'opacity var(--transition-fast), transform var(--transition-fast)',
        padding: '24px',
        maxWidth: '1400px',
        margin: '0 auto',
      };

      let content;
      if (tab === 'repo' && repoId) {
        content = <ProjectDetail key={repoId} repoId={repoId} initialSubTab={route.subTab} />;
      } else if (tab === 'analytics') {
        content = <AnalyticsTab />;
      } else if (tab === 'deps') {
        content = <FleetDepsTab />;
      } else {
        content = <FleetOverview refetchKey={refetchKey} />;
      }

      return <div style={areaStyle}>{content}</div>;
    }

    // ── App ──────────────────────────────────────────────────────────────────
    function App() {
      const hash = useHashRoute();
      const route = parseRoute(hash);
      const navTab = route.tab === 'repo' ? 'fleet' : route.tab;

      const [scanState, setScanState] = useState({
        active: false,
        scanId: null,
        progress: 0,
        total: 0,
        currentRepo: '',
        status: 'idle',
      });
      const [refetchKey, setRefetchKey] = useState(0);
      const [browseOpen, setBrowseOpen] = useState(false);
      const [scanResult, setScanResult] = useState(null);

      async function handleScanDir() {
        setBrowseOpen(true);
      }

      async function handleSelectDir(dirPath) {
        setScanResult(null);
        try {
          const res = await fetch('/api/repos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: dirPath }),
          });
          const data = await res.json();
          if (res.ok) {
            setRefetchKey(k => k + 1);
            setScanResult({ ok: true, message: `Registered ${data.registered} repo${data.registered !== 1 ? 's' : ''} from ${dirPath}` });
            setTimeout(() => setScanResult(null), 4000);
          } else {
            setScanResult({ ok: false, message: data.detail || 'Failed to scan directory' });
            setTimeout(() => setScanResult(null), 5000);
          }
        } catch (err) {
          setScanResult({ ok: false, message: 'Failed to scan directory: ' + err.message });
          setTimeout(() => setScanResult(null), 5000);
        }
      }

      async function handleFullScan() {
        if (scanState.active) return;
        let res;
        try {
          res = await fetch('/api/fleet/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'full' }),
          });
        } catch (err) {
          console.error('Full scan POST failed:', err);
          return;
        }
        if (res.status === 409) return; // already scanning
        const { scan_id } = await res.json();
        setScanState({ active: true, scanId: scan_id, progress: 0, total: 0, currentRepo: '', status: 'scanning' });

        const es = new EventSource(`/api/fleet/scan/${scan_id}/progress`);
        es.onmessage = (e) => {
          const data = JSON.parse(e.data);
          setScanState(prev => ({
            ...prev,
            progress: data.progress ?? prev.progress,
            total: data.total ?? prev.total,
            currentRepo: data.repo ?? prev.currentRepo,
            status: data.status ?? prev.status,
            active: data.status !== 'completed' && data.status !== 'failed',
          }));
          if (data.status === 'completed' || data.status === 'failed') {
            es.close();
            setRefetchKey(k => k + 1);
            setTimeout(() => setScanState({
              active: false, scanId: null, progress: 0, total: 0, currentRepo: '', status: 'idle',
            }), 2000);
          }
        };
        es.onerror = () => {
          es.close();
          setScanState(prev => ({ ...prev, active: false, status: 'failed' }));
          setRefetchKey(k => k + 1);
          setTimeout(() => setScanState({
            active: false, scanId: null, progress: 0, total: 0, currentRepo: '', status: 'idle',
          }), 3000);
        };
      }

      return (
        <div>
          <Header onFullScan={handleFullScan} onScanDir={handleScanDir} scanActive={scanState.active} />
          <NavTabs activeTab={navTab} />
          <ScanProgressBar scanState={scanState} />
          <ScanToast scanState={scanState} />
          <DirectoryBrowser open={browseOpen} onClose={() => setBrowseOpen(false)} onSelect={handleSelectDir} />
          {scanResult && (
            <div style={{
              position: 'fixed', bottom: '24px', right: '24px', zIndex: 300,
              padding: '12px 20px', borderRadius: 'var(--radius-sm)',
              background: scanResult.ok ? 'var(--status-green-bg)' : 'var(--status-red-bg)',
              color: scanResult.ok ? 'var(--status-green)' : 'var(--status-red)',
              fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500,
              border: scanResult.ok ? '1px solid var(--status-green)' : '1px solid var(--status-red)',
              boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
            }}>
              {scanResult.message}
            </div>
          )}
          <main style={{ paddingTop: '100px' }}>
            <ToolStatusBanner />
            <ContentArea route={route} refetchKey={refetchKey} />
          </main>
        </div>
      );
    }

    // ── Mount ────────────────────────────────────────────────────────────────
    ReactDOM.createRoot(document.getElementById('root')).render(
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    );
  </script>
</body>
</html>
"""


# ── FastAPI application ───────────────────────────────────────────────────────

app = FastAPI(title="Git Fleet")


@app.get("/", response_class=HTMLResponse)
async def get_ui():
    """Serve the SPA shell."""
    return HTML_TEMPLATE


@app.get("/api/status")
async def get_status():
    """Return tool availability and app version for the frontend banner."""
    return {"tools": TOOLS, "version": VERSION}


@app.get("/api/browse")
async def browse_directory(path: str = "~"):
    """List directories at a given path for the directory browser UI."""
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}")

    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

    dirs = []
    try:
        for entry in sorted(resolved.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                has_git = (entry / ".git").is_dir()
                dirs.append({"name": entry.name, "path": str(entry), "is_git": has_git})
    except PermissionError:
        pass  # return whatever we got

    parent = str(resolved.parent) if resolved != resolved.parent else None
    return {
        "current": str(resolved),
        "parent": parent,
        "dirs": dirs,
    }


# ── Repo registration endpoints ────────────────────────────────────────────────

class _RegisterRepoRequest(BaseModel):
    path: str


@app.get("/api/repos")
async def list_repos(db=Depends(get_db)):
    """List all registered repos (simple DB query, no scan)."""
    cursor = await db.execute(
        "SELECT id, name, path, runtime, default_branch, added_at FROM repositories"
    )
    cols = [d[0] for d in cursor.description]
    rows = await cursor.fetchall()
    return {"repos": [dict(zip(cols, row)) for row in rows]}


@app.post("/api/repos")
async def register_repos(body: _RegisterRepoRequest, db=Depends(get_db)):
    """Discover git repos under the given path and register them.

    Accepts: {"path": "/some/dir"}
    Returns: {"registered": N, "repos": [{id, name, path}, ...]}

    Idempotent — re-registering the same directory doesn't create duplicates.
    """
    try:
        root = Path(body.path).expanduser().resolve()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}")

    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Path not found or not a directory: {body.path}")

    discovered = await discover_repos(root)

    registered: list = []
    for repo_info in discovered:
        repo_path = Path(repo_info["path"])
        repo_info["runtime"] = detect_runtime(repo_path)
        repo_info["default_branch"] = await get_default_branch(repo_path)
        result = await register_repo(db, repo_info)
        registered.append(result)

    return {"registered": len(registered), "repos": registered}


@app.delete("/api/repos/{repo_id}", status_code=204)
async def delete_repo(repo_id: str, db=Depends(get_db)):
    """Remove a repo and all its cascading data. Returns 204 on success, 404 if not found."""
    cursor = await db.execute("SELECT id FROM repositories WHERE id = ?", (repo_id,))
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Repo not found")

    await db.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
    await db.commit()
    return Response(status_code=204)


@app.patch("/api/repos/{repo_id}")
async def update_repo(repo_id: str, body: dict = Body(...), db=Depends(get_db)):
    """Update a repo's path. Returns 200 with updated id+path, 404 if not found, 400 if invalid path."""
    cursor = await db.execute("SELECT id FROM repositories WHERE id = ?", (repo_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Repo not found")
    new_path = body.get("path", "").strip()
    if not new_path or not Path(new_path).is_dir():
        raise HTTPException(status_code=400, detail="Invalid path: directory does not exist")
    resolved = str(Path(new_path).resolve())
    await db.execute("UPDATE repositories SET path = ? WHERE id = ?", (resolved, repo_id))
    await db.commit()
    return {"id": repo_id, "path": resolved}


# ── Fleet Scan endpoints (packet 08) ──────────────────────────────────────────

class _ScanRequest(BaseModel):
    type: Literal["full", "deps"]


@app.post("/api/fleet/scan")
async def post_fleet_scan(body: _ScanRequest, db=Depends(get_db)):
    """Trigger a fleet scan. Returns immediately with a scan_id; progress via SSE.

    Rejects with 409 if a scan is already running (checked via module-level
    variable for fast path, and DB query for correctness after server restart).
    """
    global _active_scan_id, _scan_task

    # Fast-path in-memory check
    if _active_scan_id is not None:
        raise HTTPException(status_code=409, detail="A scan is already running")

    # Belt-and-suspenders DB check (correct after server restart)
    cursor = await db.execute(
        "SELECT id FROM scan_log WHERE status = 'running' LIMIT 1"
    )
    row = await cursor.fetchone()
    if row is not None:
        raise HTTPException(status_code=409, detail="A scan is already running")

    # Create scan_log entry
    now = datetime.now(timezone.utc).isoformat()
    cursor = await db.execute(
        "INSERT INTO scan_log (scan_type, started_at, status) VALUES (?, ?, 'running')",
        (body.type, now),
    )
    await db.commit()
    scan_id = cursor.lastrowid

    # Pre-create the SSE queue so events are buffered even before the
    # EventSource client connects.  The SSE endpoint will reuse this queue
    # if it already exists, or create a new one otherwise.
    _scan_queues[scan_id] = asyncio.Queue()

    # Mark active and launch background task
    _active_scan_id = scan_id
    _scan_task = asyncio.create_task(run_fleet_scan(scan_id, body.type))

    return {"scan_id": scan_id}


@app.get("/api/fleet/scan/{scan_id}/progress")
async def scan_progress_sse(scan_id: int):
    """SSE endpoint for real-time scan progress.

    Streams data events until the scan completes or fails.
    Event format: data: {<json>}\\n\\n
    """
    # Reuse the queue pre-created by POST /api/fleet/scan (which already
    # has buffered events from the scan task), or create one if somehow
    # this endpoint is hit without a prior POST.
    q = _scan_queues.get(scan_id)
    if q is None:
        q = asyncio.Queue()
        _scan_queues[scan_id] = q

    async def event_generator():
        try:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("completed", "failed"):
                    break
        finally:
            _scan_queues.pop(scan_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Project Detail API ────────────────────────────────────────────────────────

@app.get("/api/repos/{repo_id}")
async def get_repo_detail(repo_id: str, db=Depends(get_db)):
    """Return full detail for one repo: repositories row + working_state."""
    cursor = await db.execute(
        "SELECT id, name, path, runtime, default_branch, last_full_scan_at "
        "FROM repositories WHERE id = ?",
        (repo_id,),
    )
    repo = await cursor.fetchone()
    if not repo:
        raise HTTPException(status_code=404, detail="Repo not found")

    ws_cursor = await db.execute(
        "SELECT repo_id, has_uncommitted, modified_count, untracked_count, "
        "staged_count, current_branch, last_commit_hash, last_commit_message, "
        "last_commit_date, checked_at, dep_check_error "
        "FROM working_state WHERE repo_id = ?",
        (repo_id,),
    )
    ws_row = await ws_cursor.fetchone()
    ws = None
    if ws_row:
        ws = {
            "repo_id": ws_row[0],
            "has_uncommitted": bool(ws_row[1]),
            "modified_count": ws_row[2],
            "untracked_count": ws_row[3],
            "staged_count": ws_row[4],
            "current_branch": ws_row[5],
            "last_commit_hash": ws_row[6],
            "last_commit_message": ws_row[7],
            "last_commit_date": ws_row[8],
            "checked_at": ws_row[9],
            "dep_check_error": bool(ws_row[10]) if ws_row[10] is not None else False,
            "missing_dep_tools": [],
        }

    return {
        "id": repo[0],
        "name": repo[1],
        "path": repo[2],
        "runtime": repo[3],
        "default_branch": repo[4],
        "last_full_scan_at": repo[5],
        "path_exists": Path(repo[2]).is_dir(),
        "working_state": ws,
    }


@app.get("/api/repos/{repo_id}/history")
async def get_repo_history(repo_id: str, days: int = 90, db=Depends(get_db)):
    """Return daily_stats rows for the repo within the requested time window.

    Only dates with activity are included. Frontend fills date gaps with zeros.
    """
    import datetime as _dt_mod

    cursor = await db.execute(
        "SELECT id FROM repositories WHERE id = ?", (repo_id,)
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Repo not found")

    cutoff = (
        _dt_mod.date.today() - _dt_mod.timedelta(days=days)
    ).isoformat()

    cursor = await db.execute(
        "SELECT date, commits, insertions, deletions, files_changed "
        "FROM daily_stats WHERE repo_id = ? AND date >= ? ORDER BY date",
        (repo_id, cutoff),
    )
    rows = await cursor.fetchall()

    return {
        "repo_id": repo_id,
        "days": days,
        "data": [
            {
                "date": r[0],
                "commits": r[1],
                "insertions": r[2],
                "deletions": r[3],
                "files_changed": r[4],
            }
            for r in rows
        ],
    }


@app.get("/api/repos/{repo_id}/commits")
async def get_repo_commits(
    repo_id: str, page: int = 1, per_page: int = 25,
    branch: str | None = None, db=Depends(get_db),
):
    """Return paginated commit history for one repo via live git log query.

    If branch is provided, only commits reachable from that branch are shown.
    Otherwise, commits from all branches are shown (--all).
    """
    page = max(1, page)
    per_page = max(1, min(100, per_page))

    cursor = await db.execute(
        "SELECT path FROM repositories WHERE id = ?", (repo_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repo not found")

    repo_path = row[0]
    if not Path(repo_path).is_dir():
        raise HTTPException(status_code=404, detail="Repo path not found on disk")

    # Determine ref target: specific branch or --all
    ref_args = [branch] if branch else ["--all"]

    # Total commit count
    stdout, _, rc = await run_git(repo_path, "rev-list", "--count", *ref_args)
    total = int(stdout.strip()) if rc == 0 and stdout.strip().isdigit() else 0

    if total == 0:
        return {"commits": [], "page": page, "per_page": per_page, "total": 0, "branch": branch}

    skip = (page - 1) * per_page
    stdout, _, rc = await run_git(
        repo_path,
        "log", *ref_args,
        "--format=%H%x00%aI%x00%an%x00%s",
        "--shortstat",
        f"--skip={skip}",
        f"--max-count={per_page}",
    )

    parsed = parse_git_log(stdout) if rc == 0 else []
    commits = [
        {
            "hash": c["hash"],
            "date": c["date"],
            "author": c["author"],
            "message": c["subject"],
            "insertions": c["insertions"],
            "deletions": c["deletions"],
            "files_changed": c["files_changed"],
        }
        for c in parsed
    ]

    return {"commits": commits, "page": page, "per_page": per_page, "total": total, "branch": branch}


@app.get("/api/repos/{repo_id}/branches")
async def get_repo_branches(repo_id: str, db=Depends(get_db)):
    """Return branches for one repo, sorted default-first then by date.

    Includes per-branch stats (commits ahead, insertions, deletions, files changed)
    computed live via git log against the default branch.
    """
    cursor = await db.execute(
        "SELECT id, path, default_branch FROM repositories WHERE id = ?", (repo_id,)
    )
    repo_row = await cursor.fetchone()
    if not repo_row:
        raise HTTPException(status_code=404, detail="Repo not found")

    repo_path = repo_row[1]
    default_branch = repo_row[2] or "main"
    path_exists = Path(repo_path).is_dir()

    cursor = await db.execute(
        "SELECT name, last_commit_date, is_default, is_stale "
        "FROM branches "
        "WHERE repo_id = ? "
        "ORDER BY is_default DESC, last_commit_date DESC",
        (repo_id,),
    )
    rows = await cursor.fetchall()

    branches = []
    for r in rows:
        name, last_commit_date, is_default, is_stale = r
        entry = {
            "name": name,
            "last_commit_date": last_commit_date,
            "is_default": bool(is_default),
            "is_stale": False if is_default else bool(is_stale),
            "commits_ahead": 0,
            "insertions": 0,
            "deletions": 0,
            "files_changed": 0,
        }

        # Compute branch stats vs default branch (skip for default branch itself)
        if path_exists and not is_default:
            try:
                # Commits ahead of default
                count_out, _, rc = await run_git(
                    repo_path, "rev-list", "--count",
                    f"{default_branch}..{name}",
                )
                if rc == 0 and count_out.strip().isdigit():
                    entry["commits_ahead"] = int(count_out.strip())

                # Aggregate insertions/deletions/files via shortstat
                if entry["commits_ahead"] > 0:
                    stat_out, _, rc = await run_git(
                        repo_path, "diff", "--shortstat",
                        f"{default_branch}...{name}",
                    )
                    if rc == 0 and stat_out.strip():
                        m = _SHORTSTAT_RE.search(stat_out)
                        if m:
                            entry["files_changed"] = int(m.group(1))
                            entry["insertions"] = int(m.group(2)) if m.group(2) else 0
                            entry["deletions"] = int(m.group(3)) if m.group(3) else 0
            except Exception as exc:
                logger.warning("Branch stats failed for %s/%s: %s", repo_id, name, exc)

        branches.append(entry)

    return {"branches": branches}


# ── Deps API ──────────────────────────────────────────────────────────────────

async def _fetch_repo_deps(repo_id: str, db):
    """Shared helper: query and group dependency rows for one repo."""
    cursor = await db.execute(
        """
        SELECT manager, name, current_version, wanted_version, latest_version,
               severity, advisory_id, checked_at, COALESCE(source_path, '')
        FROM dependencies
        WHERE repo_id = ?
        ORDER BY source_path, manager,
          CASE severity
            WHEN 'vulnerable' THEN 0
            WHEN 'major' THEN 1
            WHEN 'outdated' THEN 2
            ELSE 3
          END,
          name
        """,
        (repo_id,),
    )
    rows = await cursor.fetchall()

    result = []
    group_key_index = {}
    for row in rows:
        mgr, name, cur_ver, wanted_ver, latest_ver, severity, advisory_id, checked_at, source_path = row
        # Group by (manager, source_path) so monorepo subdirs show separately
        gkey = (mgr, source_path)
        if gkey not in group_key_index:
            group_key_index[gkey] = len(result)
            label = f"{mgr} — {source_path}" if source_path else mgr
            result.append({"manager": mgr, "source_path": source_path, "label": label, "packages": [], "checked_at": checked_at})
        else:
            existing = result[group_key_index[gkey]]
            if checked_at and (
                not existing["checked_at"] or checked_at > existing["checked_at"]
            ):
                existing["checked_at"] = checked_at
        result[group_key_index[gkey]]["packages"].append(
            {
                "name": name,
                "current_version": cur_ver,
                "wanted_version": wanted_ver,
                "latest_version": latest_ver,
                "severity": severity,
                "advisory_id": advisory_id,
                "source_path": source_path,
            }
        )
    return result


@app.get("/api/repos/{repo_id}/deps")
async def get_repo_deps(repo_id: str, db=Depends(get_db)):
    """Return dependency groups for one repo, sorted by severity."""
    cursor = await db.execute("SELECT id FROM repositories WHERE id = ?", (repo_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Repo not found")
    return await _fetch_repo_deps(repo_id, db)


@app.post("/api/repos/{repo_id}/scan/deps")
async def scan_repo_deps(repo_id: str, db=Depends(get_db)):
    """Run a dep scan for one repo synchronously and return the updated deps list."""
    cursor = await db.execute(
        "SELECT id, path FROM repositories WHERE id = ?", (repo_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repo not found")
    repo_id_val, repo_path = row
    await run_dep_scan_for_repo(db, repo_id_val, repo_path)
    return await _fetch_repo_deps(repo_id_val, db)


# ── Analytics API ─────────────────────────────────────────────────────────────

@app.get("/api/analytics/heatmap")
async def get_analytics_heatmap(days: int = 365, db=Depends(get_db)):
    """Return aggregated daily commit counts across all repos for the heatmap."""
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    cursor = await db.execute(
        "SELECT date, SUM(commits) as count "
        "FROM daily_stats "
        "WHERE date >= ? "
        "GROUP BY date "
        "ORDER BY date ASC",
        (cutoff,),
    )
    rows = await cursor.fetchall()
    data = [{"date": row[0], "count": int(row[1])} for row in rows]
    max_count = max((entry["count"] for entry in data), default=0)
    return {"data": data, "max_count": max_count}


@app.get("/api/analytics/allocation")
async def get_analytics_allocation(days: int = 90, db=Depends(get_db)):
    """Return per-repo commit time series for the stacked area allocation chart."""
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    cursor = await db.execute(
        "SELECT ds.repo_id, r.name, ds.date, ds.commits "
        "FROM daily_stats ds "
        "JOIN repositories r ON r.id = ds.repo_id "
        "WHERE ds.date >= ? "
        "ORDER BY ds.repo_id, ds.date ASC",
        (cutoff,),
    )
    rows = await cursor.fetchall()

    # Group flat rows into per-repo series
    series = []
    current_id = None
    current_entry = None
    for row in rows:
        repo_id, name, date_str, commits = row[0], row[1], row[2], int(row[3])
        if repo_id != current_id:
            if current_entry is not None:
                series.append(current_entry)
            current_id = repo_id
            current_entry = {"repo_id": repo_id, "name": name, "data": []}
        current_entry["data"].append({"date": date_str, "commits": commits})
    if current_entry is not None:
        series.append(current_entry)

    return {"series": series}


@app.get("/api/analytics/dep-overlap")
async def get_analytics_dep_overlap(db=Depends(get_db)):
    """Return packages shared across 2+ repos, sorted by count descending."""
    cursor = await db.execute(
        "SELECT d.name, d.manager, d.repo_id, r.name as repo_name, d.current_version "
        "FROM dependencies d "
        "JOIN repositories r ON r.id = d.repo_id "
        "ORDER BY d.name, d.manager, r.name"
    )
    rows = await cursor.fetchall()

    # Group by (pkg_name, manager) in Python
    from itertools import groupby

    packages = []
    for (pkg_name, manager), group in groupby(rows, key=lambda r: (r[0], r[1])):
        row_list = list(group)
        if len(row_list) < 2:
            continue
        versions = [r[4] for r in row_list if r[4] is not None]
        versions_sorted = sorted(versions) if versions else []
        spread = f"{versions_sorted[0]} - {versions_sorted[-1]}" if versions_sorted else ""
        packages.append({
            "name": pkg_name,
            "manager": manager,
            "repos": [
                {"repo_id": r[2], "name": r[3], "version": r[4]}
                for r in row_list
            ],
            "version_spread": spread,
            "count": len(row_list),
        })

    packages.sort(key=lambda p: p["count"], reverse=True)
    return {"packages": packages}


# ── Fleet API ─────────────────────────────────────────────────────────────────

@app.get("/api/fleet")
async def get_fleet(db=Depends(get_db)):
    """Quick-scan all registered repos and return the fleet overview.

    Runs up to 8 scans in parallel (asyncio.Semaphore(8)), upserts working_state,
    and returns per-repo data with branch counts from the branches table and
    KPIs aggregated from daily_stats.
    """
    results = await scan_fleet_quick(db)

    # Bulk-compute sparklines once for all repos (packet 09)
    sparklines = await compute_sparklines(db)

    # Bulk-read scan_error and dep_check_error from working_state.
    if results:
        ids = [r["id"] for r in results]
        placeholders = ",".join("?" * len(ids))
        ws_cursor = await db.execute(
            f"SELECT repo_id, scan_error, dep_check_error "
            f"FROM working_state WHERE repo_id IN ({placeholders})",
            ids,
        )
        ws_map = {}
        for row in await ws_cursor.fetchall():
            ws_map[row[0]] = (row[1], bool(row[2]))
        for repo in results:
            scan_err, dep_err = ws_map.get(repo["id"], (None, False))
            repo["scan_error"] = scan_err
            repo["dep_check_error"] = dep_err
            repo["missing_dep_tools"] = []

    # Augment with branch counts from branches table (packet 08) and placeholders
    for repo in results:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM branches WHERE repo_id = ?", (repo["id"],)
        )
        (branch_count,) = await cursor.fetchone()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM branches "
            "WHERE repo_id = ? AND is_stale = 1 AND is_default = 0",
            (repo["id"],),
        )
        (stale_count,) = await cursor.fetchone()
        repo["branch_count"] = branch_count
        repo["stale_branch_count"] = stale_count
        # Compute dep_summary from dependencies table
        cursor = await db.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN severity IN ('outdated', 'major') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN severity = 'vulnerable' THEN 1 ELSE 0 END) "
            "FROM dependencies WHERE repo_id = ?",
            (repo["id"],),
        )
        total_deps, outdated_count, vuln_count = await cursor.fetchone()
        if total_deps and total_deps > 0:
            repo["dep_summary"] = {
                "total": total_deps,
                "outdated": (outdated_count or 0),
                "vulnerable": (vuln_count or 0),
            }
        else:
            repo["dep_summary"] = None
        repo["sparkline"] = sparklines.get(repo["id"], [0] * 13)

    # Compute KPIs from daily_stats (packets 06-08) and branches table (packet 07)
    now_utc = datetime.now(timezone.utc)
    week_ago = (now_utc - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now_utc - timedelta(days=30)).strftime("%Y-%m-%d")

    cursor = await db.execute(
        "SELECT COALESCE(SUM(commits), 0) FROM daily_stats WHERE date >= ?", (week_ago,)
    )
    commits_this_week = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COALESCE(SUM(commits), 0) FROM daily_stats WHERE date >= ?", (month_ago,)
    )
    commits_this_month = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COALESCE(SUM(insertions), 0) - COALESCE(SUM(deletions), 0) "
        "FROM daily_stats WHERE date >= ?",
        (week_ago,),
    )
    net_lines_this_week = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COALESCE(SUM(CASE WHEN severity = 'vulnerable' THEN 1 ELSE 0 END), 0), "
        "COALESCE(SUM(CASE WHEN severity IN ('outdated', 'major') THEN 1 ELSE 0 END), 0) "
        "FROM dependencies"
    )
    vuln_total, outdated_total = await cursor.fetchone()

    kpis = {
        "total_repos": len(results),
        "repos_with_changes": sum(1 for r in results if r.get("has_uncommitted")),
        "commits_this_week": commits_this_week,
        "commits_this_month": commits_this_month,
        "net_lines_this_week": net_lines_this_week,
        "stale_branches": sum(r.get("stale_branch_count", 0) for r in results),
        "vulnerable_deps": vuln_total,
        "outdated_deps": outdated_total,
    }

    return {
        "repos": results,
        "kpis": kpis,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Signal handling ───────────────────────────────────────────────────────────

def _shutdown_handler(sig, frame):
    print("\nGit Fleet: shutting down.", flush=True)
    sys.exit(0)


def register_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _shutdown_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _shutdown_handler)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    run_preflight()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_schema(DB_PATH)
    run_migrations(DB_PATH)

    if args.scan:
        scan_path = Path(args.scan).expanduser().resolve()
        if not scan_path.is_dir():
            print(f"Warning: --scan path does not exist or is not a directory: {args.scan}", file=sys.stderr)
        else:
            async def _startup_scan():
                async with aiosqlite.connect(str(DB_PATH)) as db:
                    repos = await discover_repos(scan_path)
                    for repo_info in repos:
                        repo_path = Path(repo_info["path"])
                        repo_info["runtime"] = detect_runtime(repo_path)
                        repo_info["default_branch"] = await get_default_branch(repo_path)
                        await register_repo(db, repo_info)
                    print(f"Registered {len(repos)} repos from {args.scan}", flush=True)

            asyncio.run(_startup_scan())

    port = find_free_port(args.port)
    if port != args.port:
        print(
            f"Warning: Port {args.port} is in use; using port {port} instead.",
            flush=True,
        )

    url = f"http://localhost:{port}"
    print(f"Git Fleet running at {url}", flush=True)

    if (
        not args.no_browser
        and not os.environ.get("GIT_DASHBOARD_NO_BROWSER")
        and not testing_mode_enabled()
    ):
        Timer(1.0, webbrowser.open, args=[url]).start()

    register_signal_handlers()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
