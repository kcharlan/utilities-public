#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.16"
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
import tempfile
import tomllib
import urllib.error
import urllib.parse
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
VERSION = "0.3.0"

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

_DEPENDENCIES_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS dependencies (
  repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  manager TEXT NOT NULL,
  source_path TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  declared_spec TEXT,
  current_version TEXT,
  wanted_version TEXT,
  latest_version TEXT,
  severity TEXT DEFAULT 'unchecked',
  advisory_id TEXT,
  outdated_state TEXT DEFAULT 'unchecked',
  vuln_state TEXT DEFAULT 'unchecked',
  check_note TEXT,
  checked_at TEXT,
  PRIMARY KEY (repo_id, manager, source_path, name)
);
"""


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

""" + _DEPENDENCIES_TABLE_SQL + """

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
  dep_check_error      BOOLEAN DEFAULT FALSE,
  missing_dep_tools    TEXT DEFAULT '[]',
  dep_manifests        TEXT DEFAULT '[]'
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
    "ALTER TABLE working_state ADD COLUMN missing_dep_tools TEXT DEFAULT '[]'",
    "ALTER TABLE working_state ADD COLUMN dep_manifests TEXT DEFAULT '[]'",
    "ALTER TABLE dependencies ADD COLUMN source_path TEXT DEFAULT ''",
]


def normalize_dep_name(manager: str, name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower() if manager == "pip" else name


def dependency_identity_name(dep: dict) -> str:
    if dep.get("reference_identity"):
        return dep["name"]
    return normalize_dep_name(dep["manager"], dep["name"])


def _version_sort_key(value: str) -> tuple:
    from packaging.version import InvalidVersion, Version
    try:
        return (0, Version(value), value)
    except InvalidVersion:
        return (1, None, value)


def _migrate_dependencies_v2(conn: sqlite3.Connection) -> None:
    """Rebuild the historical package key as a manifest declaration key atomically."""
    info = conn.execute("PRAGMA table_info(dependencies)").fetchall()
    key = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
    if key == ["repo_id", "manager", "source_path", "name"]:
        return
    conn.execute("SAVEPOINT dependencies_v2")
    try:
        cursor = conn.execute("SELECT * FROM dependencies ORDER BY rowid")
        columns = [d[0] for d in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.execute("ALTER TABLE dependencies RENAME TO dependencies_legacy")
        conn.execute(_DEPENDENCIES_TABLE_SQL)
        for row in rows:
            note = (f"Legacy result: severity={row.get('severity')!r}; "
                    f"advisory={row.get('advisory_id')!r}. "
                    "Rescan dependencies to establish check coverage.")
            conn.execute(
                """INSERT INTO dependencies
                   (repo_id, manager, source_path, name, current_version,
                    wanted_version, latest_version, severity, advisory_id,
                    outdated_state, vuln_state, check_note, checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'unchecked', NULL,
                           'unchecked', 'unchecked', ?, ?)
                   ON CONFLICT(repo_id, manager, source_path, name) DO NOTHING""",
                (row["repo_id"], row["manager"], row.get("source_path") or "",
                 normalize_dep_name(row["manager"], row["name"]),
                 row.get("current_version"), row.get("wanted_version"),
                 row.get("latest_version"), note, row.get("checked_at")),
            )
        conn.execute("DROP TABLE dependencies_legacy")
        conn.execute("RELEASE SAVEPOINT dependencies_v2")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT dependencies_v2")
        conn.execute("RELEASE SAVEPOINT dependencies_v2")
        raise


def run_migrations(db_path: Path) -> None:
    """Apply additive migrations, then migrate the dependency declaration key."""
    conn = sqlite3.connect(str(db_path))
    try:
        for sql in _MIGRATION_SQL:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists
        _migrate_dependencies_v2(conn)
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


DEP_TOOL_REQUIREMENTS = {
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


@dataclass
class DepAnalysis:
    enriched: list[dict]
    any_error: bool
    missing_tools: list[dict]
    manifests: list[dict]


def analyze_repo_deps(repo_path: Path) -> DepAnalysis:
    """Run blocking manifest/tool work away from the server event loop."""
    manifests: list[dict] = []
    raw = parse_deps_for_repo(repo_path, manifests_out=manifests)
    managers = {d['manager'] for d in raw} | {('pip' if m['kind'] in ('requirements', 'pyproject', 'pep723') else
                 next(manager for filename, manager, _ in _DEP_FILE_PRIORITY if filename == m['kind']))
                for m in manifests}
    missing = []
    for manager in sorted(managers):
        for key, tool, description in DEP_TOOL_REQUIREMENTS.get(manager, []):
            if not TOOLS.get(key) and not any(m['tool'] == tool for m in missing):
                missing.append(dict(tool=tool, description=description))
                logger.info('Missing %s (%s)', tool, description)
    enriched = raw
    any_error = any(m.get('error') for m in manifests)
    for manager, checker in (
        ('pip', check_python_deps), ('npm', check_node_deps),
        ('gomod', check_go_deps), ('cargo', check_rust_deps),
        ('bundler', check_ruby_deps), ('composer', check_php_deps),
    ):
        try:
            enriched = checker(repo_path, enriched)
        except Exception as exc:
            any_error = True
            note = tool_failure_note(f'{manager} checker', exc)
            enriched = [mark_unchecked(dict(d), note) if d.get('manager') == manager else d
                        for d in enriched]
    enriched = finalize_dep_health(enriched)
    any_error |= bool(missing) or any('unchecked' in (d['outdated_state'], d['vuln_state'])
                                     for d in enriched)
    return DepAnalysis(enriched, any_error, missing, manifests)


async def run_dep_scan_for_repo(db, repo_id: str, repo_path: str) -> None:
    """Analyze in a worker thread; persist rows and metadata together."""
    analysis = await asyncio.to_thread(analyze_repo_deps, Path(repo_path))
    enriched = analysis.enriched
    await db.execute('SAVEPOINT dep_scan_snapshot')
    try:
        await db.execute(
            "INSERT INTO working_state (repo_id, dep_check_error, missing_dep_tools, dep_manifests) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(repo_id) DO UPDATE SET "
            "dep_check_error = excluded.dep_check_error, missing_dep_tools = excluded.missing_dep_tools, "
            "dep_manifests = excluded.dep_manifests",
            (repo_id, analysis.any_error, json.dumps(analysis.missing_tools), json.dumps(analysis.manifests)),
        )

        # 3. Upsert into dependencies table
        for dep in enriched:
            await db.execute(
                """INSERT OR REPLACE INTO dependencies
                   (repo_id, manager, name, current_version, wanted_version,
                    latest_version, severity, advisory_id, checked_at, source_path,
                    declared_spec, outdated_state, vuln_state, check_note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    dep.get("source_path") or "",
                    dep.get("declared_spec", dep.get("version")),
                    dep.get("outdated_state", "unchecked"),
                    dep.get("vuln_state", "unchecked"),
                    dep.get("check_note"),
                ),
            )

        # 4. Delete stale deps (in DB but no longer in manifest)
        current_keys = {(dep.get("manager", ""), dep.get("source_path") or "", dep.get("name", "")) for dep in enriched}
        cursor = await db.execute(
            "SELECT manager, source_path, name FROM dependencies WHERE repo_id = ?", (repo_id,)
        )
        db_keys = await cursor.fetchall()
        for manager, source_path, name in db_keys:
            if (manager, source_path, name) not in current_keys:
                await db.execute(
                    "DELETE FROM dependencies WHERE repo_id = ? AND manager = ? AND source_path = ? AND name = ?",
                    (repo_id, manager, source_path, name),
                )

    except BaseException:
        await db.execute('ROLLBACK TO SAVEPOINT dep_scan_snapshot')
        await db.execute('RELEASE SAVEPOINT dep_scan_snapshot')
        raise
    else:
        await db.execute('RELEASE SAVEPOINT dep_scan_snapshot')


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
# Python manifests coexist; other ecosystem filenames retain their choices.
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


_REQUIREMENTS_RE = re.compile(
    r"^requirements(?:[-_.][A-Za-z0-9_.-]+)?\.(?:txt|lock)$", re.IGNORECASE
)


def _source_path(repo_path: Path, file_path: Path) -> str:
    resolved = file_path.resolve()
    try:
        return resolved.relative_to(repo_path.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def detect_dep_files(repo_path: Path) -> list[dict]:
    """Discover coexisting Python manifests and other ecosystem manifests."""
    results = []
    dirs_to_walk = [(repo_path, 0)]
    while dirs_to_walk:
        current_dir, depth = dirs_to_walk.pop()
        try:
            entries = sorted(current_dir.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if depth < _DEP_WALK_MAX_DEPTH and entry.name not in _DEP_WALK_SKIP and not entry.name.startswith('.'):
                    dirs_to_walk.append((entry, depth + 1))
                continue
            if not entry.is_file():
                continue
            known = next(((filename, manager, runtime) for filename, manager, runtime
                          in _DEP_FILE_PRIORITY if runtime != 'python'
                          and filename.lower() == entry.name.lower()), None)
            if known:
                filename, manager, runtime = known
                results.append(dict(file=entry.name, kind=filename, manager=manager, runtime=runtime, dir=current_dir))
                continue
            kind = None
            if entry.name.lower() == 'pyproject.toml':
                kind = 'pyproject'
            elif _REQUIREMENTS_RE.fullmatch(entry.name):
                kind = 'requirements'
            elif entry.suffix.lower() in ('.py', '.pyw'):
                kind = 'pep723'
            elif not entry.suffix:
                try:
                    with entry.open('rb') as candidate:
                        first_line = candidate.readline()
                    if first_line.startswith(b'#!'):
                        kind = 'pep723'
                except OSError:
                    continue
            if kind:
                results.append(dict(file=entry.name, kind=kind, manager='pip', runtime='python', dir=current_dir))
                continue
    return results


def _manifest_record(inventory: dict | None, path: Path, kind: str) -> dict:
    record = dict(kind=kind, dependencies=0, error=None)
    if inventory is not None:
        inventory[path.resolve()] = record
    return record


def _find_pep723_block(script: str) -> str | None:
    """Apply PEP 723's reference grammar only to the leading comment prelude."""
    prelude = []
    for line in script.splitlines(keepends=True):
        if line.strip() and not line.lstrip().startswith('#'):
            break
        prelude.append(line)
    # https://peps.python.org/pep-0723/#reference-implementation
    regex = r'(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$'
    blocks = [m for m in re.finditer(regex, ''.join(prelude)) if m.group('type') == 'script']
    if len(blocks) > 1:
        raise ValueError('Multiple script blocks found')
    if not blocks:
        return None
    return ''.join(line[2:] if line.startswith('# ') else line[1:]
                   for line in blocks[0].group('content').splitlines(keepends=True))


def parse_pep723_script(file_path: Path, *, manifests_out: dict | None = None) -> list[dict]:
    # An explicit requirements include owns its resolved file, even if its
    # filename also makes it a script candidate. Never reread or replace it.
    if manifests_out is not None and file_path.resolve() in manifests_out:
        return []
    record = _manifest_record(manifests_out, file_path, 'pep723')
    try:
        block = _find_pep723_block(file_path.read_text(encoding='utf-8'))
        if block is None:
            if manifests_out is not None:
                manifests_out.pop(file_path.resolve(), None)
            return []
        data = tomllib.loads(block)
        declarations = data.get('dependencies', [])
        if not isinstance(declarations, list) or not all(isinstance(d, str) for d in declarations):
            raise ValueError('dependencies must be a list of strings')
        deps = []
        for text in declarations:
            dep = parse_python_requirement(text)
            if dep is None:
                raise ValueError('invalid dependency declaration')
            deps.append(dep)
        record['dependencies'] = len(deps)
        return deps
    except (OSError, UnicodeError, ValueError) as exc:
        record['error'] = str(exc)
        return []


_VCS_SCHEMES = ("git+", "hg+", "svn+", "bzr+")
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
NOTE_DIRECT_REF = "direct VCS/URL reference; not compared with PyPI or audited"


def _direct_reference(name: str | None, url: str, declared: str) -> dict:
    vcs = next((scheme[:-1] for scheme in _VCS_SCHEMES
                if url.startswith(scheme)), None)
    target = url[len(vcs) + 1:] if vcs else url
    parts = urllib.parse.urlsplit(target)
    path = parts.path
    revision = None
    if vcs and "@" in path:
        path, _, revision = path.rpartition("@")
    egg = urllib.parse.parse_qs(parts.fragment).get("egg", [None])[0]
    if name is None and egg:
        from packaging.requirements import Requirement
        name = Requirement(egg).name
    current = None
    if name is None and not vcs and path.endswith(".whl"):
        from packaging.utils import parse_wheel_filename
        wheel_name, wheel_version, _, _ = parse_wheel_filename(path.rsplit("/", 1)[-1])
        name, current = str(wheel_name), str(wheel_version)
    reference_identity = name is None
    if reference_identity:
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        name = host + path.removesuffix(".git").rstrip("/")
    else:
        name = normalize_dep_name("pip", name)
    if vcs:
        current = f"{vcs}:{revision}" if revision else f"{vcs}:default branch"
    return {
        "name": name, "manager": "pip", "declared_spec": declared,
        "version": None, "current_version": current, "direct_ref": True,
        "reference_identity": reference_identity,
    }


def parse_python_requirement(text: str) -> dict | None:
    """Parse PEP 508 or pip's bare URL form without evaluating markers."""
    from packaging.requirements import InvalidRequirement, Requirement
    text = text.strip()
    try:
        if text.startswith(_VCS_SCHEMES) or _URL_RE.match(text):
            return _direct_reference(None, text, text)
        requirement = Requirement(text)
        if requirement.url:
            return _direct_reference(requirement.name, requirement.url, text)
        pins = [spec.version for spec in requirement.specifier
                if spec.operator in ('==', '===') and '*' not in spec.version
                and _exact_pip_version(spec.version)]
        version = pins[0] if len(pins) == 1 else None
        return dict(name=requirement.name, manager='pip', version=version,
                    declared_spec=text)
    except (InvalidRequirement, ValueError):
        return None


def parse_requirements_txt(file_path: Path, _visited: set[str] | None = None, *, manifests_out: dict | None = None) -> list[dict]:
    """Parse PEP 508 declarations and direct URLs with circular-safe includes.

    Join continuations and remove comments/options while preserving extras and
    markers in declared_spec. Editable/local requirements remain unsupported.
    """
    if _visited is None:
        _visited = set()

    resolved = str(file_path.resolve())
    if resolved in _visited:
        return []
    _visited.add(resolved)
    record = _manifest_record(manifests_out, file_path, 'requirements')

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        record['error'] = str(exc)
        return []

    deps: list[dict] = []
    for line in re.sub(r"\\\r?\n", " ", text).splitlines():
        line = re.split(r"\s+#", line, maxsplit=1)[0]
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
            deps.extend(parse_requirements_txt(include_path, _visited, manifests_out=manifests_out))
            continue
        if line.startswith("-"):
            # Other flags: -i, --index-url, -f, --find-links, etc.
            continue

        requirement_text = re.split(r"\s+--(?:hash|config-settings|global-option|install-option)\b", line, maxsplit=1)[0].strip()
        dep = parse_python_requirement(requirement_text)
        if dep is not None:
            dep['source_file'] = file_path.resolve()
            deps.append(dep)
            record['dependencies'] += 1
        else:
            record['error'] = 'invalid dependency declaration'

    return deps


def parse_pyproject_toml(file_path: Path, *, manifests_out: dict | None = None) -> list[dict]:
    """Parse pyproject.toml and return [{name, version, manager}].

    Supports:
    - PEP 621: [project].dependencies  (preferred if both sections exist)
    - Poetry:  [tool.poetry.dependencies]
    """
    record = _manifest_record(manifests_out, file_path, 'pyproject')
    try:
        with open(file_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        record['error'] = str(exc)
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    deps: list[dict] = []

    project = data.get('project', {})
    declarations = list(project.get('dependencies', []))
    for optional in project.get('optional-dependencies', {}).values():
        declarations.extend(optional)
    for group in data.get('dependency-groups', {}).values():
        declarations.extend(entry for entry in group if isinstance(entry, str))
    for entry in declarations:
        dep = parse_python_requirement(entry) if isinstance(entry, str) else None
        if dep is not None:
            deps.append(dep)
        else:
            record['error'] = 'invalid dependency declaration'
    if 'dependencies' in project:
        _apply_uv_lock_versions(file_path, deps, record)
        record['dependencies'] = len(deps)
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
            declared = val if isinstance(val, str) else json.dumps(val, sort_keys=True)
            deps.append({"name": name, "version": version, "manager": "pip", "declared_spec": declared})
        _apply_uv_lock_versions(file_path, deps, record)
        record['dependencies'] = len(deps)
        return deps

    _apply_uv_lock_versions(file_path, deps, record)
    record['dependencies'] = len(deps)
    return deps


def _load_uv_lock_versions(lock_path: Path) -> dict[str, set[str]]:
    with lock_path.open('rb') as stream:
        data = tomllib.load(stream)
    versions: dict[str, set[str]] = {}
    for package in data.get('package', []):
        if isinstance(package.get('source'), dict) and 'registry' in package['source'] and package.get('version'):
            name = normalize_dep_name('pip', package['name'])
            versions.setdefault(name, set()).add(package['version'])
    return versions


def _apply_uv_lock_versions(file_path: Path, deps: list[dict], record: dict) -> None:
    lock = file_path.with_name('uv.lock')
    if not lock.exists():
        return
    try:
        versions = _load_uv_lock_versions(lock)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        record['error'] = f'uv.lock: {exc}'
        return
    for dep in deps:
        if dep.get('direct_ref'):
            continue
        locked = versions.get(normalize_dep_name('pip', dep['name']), set())
        if len(locked) == 1:
            dep['version'] = next(iter(locked))
            dep['version_source'] = str(lock.resolve())
            add_check_note(dep, 'version from adjacent uv.lock')
        elif len(locked) > 1:
            dep['resolution_blocked'] = True
            mark_unchecked(dep, 'ambiguous uv.lock registry versions; resolution blocked')


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


def parse_deps_for_repo(repo_path: Path, manifests_out: list[dict] | None = None) -> list[dict]:
    """Parse declarations with a shared inventory of attempted manifest reads."""
    inventory: dict[Path, dict] = {}
    visited: set[str] = set()
    parsers = {'pyproject': parse_pyproject_toml, 'pep723': parse_pep723_script,
               'package.json': parse_package_json, 'go.mod': parse_go_mod,
               'Cargo.toml': parse_cargo_toml, 'Gemfile': parse_gemfile,
               'composer.json': parse_composer_json}
    all_deps = []
    seen = set()
    # Parse explicit manifests/includes before probing script candidates. This
    # gives arbitrary include filenames stable ownership regardless of walk order.
    entries = sorted(detect_dep_files(repo_path), key=lambda entry: entry['kind'] == 'pep723')
    for entry in entries:
        file_path = entry['dir'] / entry['file']
        kind = entry['kind']
        try:
            if kind == 'requirements':
                parsed = parse_requirements_txt(file_path, visited, manifests_out=inventory)
            elif kind in ('pyproject', 'pep723'):
                parsed = parsers[kind](file_path, manifests_out=inventory)
            else:
                record = _manifest_record(inventory, file_path, kind)
                # Validate structured manifests here because legacy parsers return
                # [] for errors as well as valid empty files.
                text = file_path.read_text(encoding='utf-8')
                if kind in ('package.json', 'composer.json'):
                    json.loads(text)
                elif kind == 'Cargo.toml':
                    tomllib.loads(text)
                parsed = parsers[kind](file_path)
                record['dependencies'] = len(parsed)
        except Exception as exc:
            logger.warning('Error parsing %s: %s', file_path, exc)
            inventory.setdefault(file_path.resolve(), dict(kind=kind, dependencies=0))['error'] = str(exc)
            parsed = []
        for dep in parsed:
            source = _source_path(repo_path, Path(dep.pop('source_file', file_path)))
            dep['name'] = dependency_identity_name(dep)
            key = (dep['manager'], source, dep['name'])
            if key not in seen:
                seen.add(key)
                dep['source_path'] = source
                if dep.get('version_source'):
                    dep['version_source'] = _source_path(repo_path, Path(dep['version_source']))
                all_deps.append(dep)
    if manifests_out is not None:
        manifests_out.extend(dict(path=_source_path(repo_path, path), **record)
                             for path, record in inventory.items())
    return all_deps


# ── Python dependency health (Packet 13) ──────────────────────────────────────

def _validate_tool_result(proc, tool: str, allowed: tuple[int, ...]) -> None:
    if proc.returncode not in allowed:
        detail = (proc.stderr or '').strip()
        raise ValueError(f'{tool} exited {proc.returncode}: {detail}')


def _check_failed(deps: list[dict], tool: str, error, field: str) -> list[dict]:
    reason = tool_failure_note(tool, error)
    return [mark_unchecked(dict(d), reason, field) for d in deps]


def add_check_note(dep: dict, reason: str) -> dict:
    """Append distinct incomplete-coverage reasons without multiplying on finalize."""
    existing = dep.get('check_note') or ''
    if reason and f'; {reason}; ' not in f'; {existing}; ':
        existing = f'{existing}; {reason}' if existing else reason
    dep['check_note'] = existing or None
    return dep


def mark_unchecked(dep: dict, reason: str, field: str | None = None) -> dict:
    for key in ((field,) if field else ('outdated_state', 'vuln_state')):
        dep[key] = 'unchecked'
    add_check_note(dep, reason)
    dep['severity'] = derive_severity(dep)
    return dep


def tool_failure_note(tool: str, error) -> str:
    detail = getattr(error, 'stderr', None) or str(error)
    if isinstance(detail, bytes):
        detail = detail.decode('utf-8', errors='replace')
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    note = f"{tool}: {(lines[-1] if lines else 'check failed')[:240]}"
    logger.warning('%s', note)
    return note


def derive_severity(dep: dict) -> str:
    if dep.get("advisory_id"):
        return "vulnerable"
    if (dep.get("outdated_state") in ("checked", "floating")
            and dep.get("severity") in ("major", "outdated")):
        return dep["severity"]
    if "unchecked" in (
        dep.get("outdated_state", "unchecked"),
        dep.get("vuln_state", "unchecked"),
    ):
        return "unchecked"
    return "ok"


def _exact_pip_version(value: str | None) -> str | None:
    from packaging.version import InvalidVersion, Version
    if not value:
        return None
    try:
        Version(value)
    except InvalidVersion:
        return None
    return value


def finalize_dep_health(deps: list[dict]) -> list[dict]:
    result = []
    now = datetime.now(timezone.utc).isoformat()
    for dep in deps:
        d = dict(dep)
        d.setdefault('declared_spec', d.get('version'))
        current = (_exact_pip_version(d.get('version')) if d.get('manager') == 'pip'
                   else d.get('version') if d.get('manager') == 'gomod' else None)
        d.setdefault('current_version', current)
        if not d.get('wanted_version'):
            d['wanted_version'] = d.get('current_version')
        d.setdefault('latest_version', None)
        d.setdefault('advisory_id', None)
        d.setdefault('checked_at', now)
        for field, valid in (('outdated_state', ('checked', 'floating', 'unchecked')),
                             ('vuln_state', ('checked', 'unchecked'))):
            missing_evidence = d.get(field) not in valid
            if missing_evidence:
                d[field] = 'unchecked'
            if missing_evidence or (d[field] == 'unchecked' and not d.get('check_note')):
                add_check_note(d, f'{field}: no evaluation evidence')
        d.setdefault('check_note', None)
        d['severity'] = derive_severity(d)
        result.append(d)
    return result


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


_PYPI_MAX_CONSECUTIVE_FAILURES = 3


def _floating_specifier(dep: dict) -> str:
    """Extract supported PEP 508/440 constraints without interpreting Poetry syntax."""
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.specifiers import SpecifierSet

    text = (dep.get('declared_spec') or dep.get('version') or '').strip()
    if text in ('', '*'):
        return ''
    try:
        requirement = Requirement(text)
    except InvalidRequirement:
        return str(SpecifierSet(text))
    if (requirement.url or normalize_dep_name('pip', requirement.name)
            != normalize_dep_name('pip', dep['name'])):
        raise ValueError('unsupported Python declaration')
    return str(requirement.specifier)


def resolve_floating_version(payload: dict, constraint: str) -> str | None:
    """Select the highest allowed release with at least one non-yanked file."""
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    releases = payload.get('releases')
    if isinstance(releases, dict):
        versions = [Version(version) for version, files in releases.items()
                    if _exact_pip_version(version) and isinstance(files, list)
                    and any(isinstance(file, dict) and not file.get('yanked', False)
                            for file in files)]
    else:
        fallback = _exact_pip_version(payload.get('info', {}).get('version'))
        versions = [Version(fallback)] if fallback else []
    selected = max(SpecifierSet(constraint).filter(versions), default=None)
    return str(selected) if selected is not None else None


def check_python_outdated(deps: list[dict]) -> list[dict]:
    """Evaluate exact or floating declarations, caching registry results per scan."""
    cache: dict[str, tuple[dict | None, str | None]] = {}
    connection_failures = 0
    result = []
    for dep in deps:
        d = dict(dep)
        result.append(d)
        if d.get('manager') != 'pip' or d.get('resolution_blocked'):
            continue
        if d.get('direct_ref'):
            mark_unchecked(d, NOTE_DIRECT_REF)
            continue
        current = (_exact_pip_version(d.get('current_version'))
                   or _exact_pip_version(d.get('version')))
        d['current_version'] = current
        d['wanted_version'] = current
        d['latest_version'] = None
        try:
            constraint = _floating_specifier(d) if current is None else None
        except (ValueError, TypeError) as exc:
            mark_unchecked(d, f'unsupported Python constraint: {exc}', 'outdated_state')
            continue
        name = normalize_dep_name('pip', d['name'])
        if name not in cache:
            if connection_failures >= _PYPI_MAX_CONSECUTIVE_FAILURES:
                cache[name] = (None, 'PyPI lookup: connection failure limit reached')
            else:
                try:
                    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/json', timeout=15) as resp:
                        payload = json.loads(resp.read())
                    if not isinstance(payload, dict):
                        raise ValueError('invalid registry result')
                    if not _exact_pip_version(payload.get('info', {}).get('version')):
                        raise ValueError('missing or invalid registry latest version')
                    cache[name] = (payload, None)
                    connection_failures = 0
                except Exception as exc:
                    if (isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError))
                            and not isinstance(exc, urllib.error.HTTPError)):
                        connection_failures += 1
                    cache[name] = (None, tool_failure_note('PyPI lookup', exc))
        payload, note = cache[name]
        if note:
            mark_unchecked(d, note, 'outdated_state')
            continue
        try:
            evaluated = current or resolve_floating_version(payload, constraint)
            if evaluated is None:
                raise ValueError('no usable release satisfies the declaration')
            d['wanted_version'] = evaluated
            d['latest_version'] = payload['info']['version']
            d['severity'] = classify_severity(evaluated, d['latest_version'])
            d['outdated_state'] = 'checked' if current else 'floating'
        except Exception as exc:
            mark_unchecked(d, tool_failure_note('PyPI lookup', exc), 'outdated_state')
    return result


def _pip_audit_batches(pins: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Deduplicate pins, separating conflicting versions of the same distribution."""
    batches: list[list[tuple[str, str]]] = []
    seen = set()
    for name, version in pins:
        pin = (normalize_dep_name('pip', name), version)
        if pin in seen:
            continue
        seen.add(pin)
        for batch in batches:
            if all(existing_name != pin[0] for existing_name, _ in batch):
                batch.append(pin)
                break
        else:
            batches.append([pin])
    return batches


def _audit_python_pins(pip_audit: str, batch: list[tuple[str, str]]) -> dict:
    def failed(note):
        return {pin: {"vuln_state": "unchecked", "note": note} for pin in batch}

    proc = None
    try:
        with tempfile.TemporaryDirectory(prefix="git-fleet-audit-") as tmp:
            path = Path(tmp) / "pins.txt"
            path.write_text("".join(f"{name}=={version}\n"
                                    for name, version in batch), encoding="utf-8")
            proc = subprocess.run(
                [pip_audit, "--requirement", str(path), "--no-deps", "--disable-pip",
                 "--format", "json", "--progress-spinner", "off"],
                capture_output=True, text=True, timeout=300,
            )
        if proc.returncode not in (0, 1):
            return failed(tool_failure_note(
                "pip-audit", proc.stderr or f"exit status {proc.returncode}"
            ))
        raw = json.loads(proc.stdout)
        if not isinstance(raw, dict) or not isinstance(raw.get("dependencies"), list):
            raise ValueError("missing dependencies result")
        entries = {}
        for entry in raw["dependencies"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                raise ValueError("invalid dependency result")
            name = normalize_dep_name("pip", entry["name"])
            if name in entries:
                raise ValueError("duplicate dependency result")
            entries[name] = entry
        results = {}
        for pin in batch:
            name, version = pin
            entry = entries.get(name)
            if entry is None:
                results[pin] = {"vuln_state": "unchecked", "note": "not in pip-audit output"}
                continue
            if entry.get("skip_reason"):
                results[pin] = {"vuln_state": "unchecked",
                                "note": f"pip-audit skipped: {entry['skip_reason']}"}
                continue
            vulns = entry.get("vulns")
            if (not isinstance(vulns, list)
                    or any(not isinstance(v, dict) or not isinstance(v.get("id"), str)
                           or not v["id"] for v in vulns)):
                raise ValueError("missing or invalid vulnerability result")
            if entry.get("version") is not None and entry["version"] != version:
                raise ValueError("audit version differs from requested pin")
            if proc.returncode == 0 and vulns:
                raise ValueError("audit exit status contradicts advisories")
            results[pin] = {"vuln_state": "checked",
                            "advisory_id": vulns[0]["id"] if vulns else None}
        if proc.returncode == 1 and not any(
            result.get("advisory_id") for result in results.values()
        ):
            raise ValueError("advisory exit status without a requested advisory")
        return results
    except Exception as exc:
        detail = proc.stderr if proc is not None and proc.stderr else str(exc)
        return failed(tool_failure_note("pip-audit", detail))


def check_python_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Audit concrete evaluated declarations across manifests without resolving deps."""
    pip_audit = TOOLS.get('pip_audit')
    result = []
    rows_by_pin: dict[tuple[str, str], list[dict]] = {}
    for dep in deps:
        d = dict(dep)
        result.append(d)
        if d.get('manager') != 'pip' or d.get('resolution_blocked'):
            continue
        if d.get('direct_ref'):
            mark_unchecked(d, NOTE_DIRECT_REF)
            continue
        version = (_exact_pip_version(d.get('current_version'))
                   or _exact_pip_version(d.get('version'))
                   or _exact_pip_version(d.get('wanted_version')))
        if version is None:
            mark_unchecked(d, 'no concrete Python version to audit', 'vuln_state')
        elif not pip_audit:
            mark_unchecked(d, 'pip-audit: tool unavailable', 'vuln_state')
        else:
            pin = (normalize_dep_name('pip', d['name']), version)
            rows_by_pin.setdefault(pin, []).append(d)
    for batch in _pip_audit_batches(list(rows_by_pin)):
        for pin, audit in _audit_python_pins(pip_audit, batch).items():
            for row in rows_by_pin[pin]:
                row['vuln_state'] = audit['vuln_state']
                if audit['vuln_state'] == 'unchecked':
                    mark_unchecked(row, audit['note'], 'vuln_state')
                else:
                    row['advisory_id'] = audit['advisory_id']
                    row['severity'] = derive_severity(row)
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

    blocked = [d for d in pip_deps if d.get('resolution_blocked')]
    pip_deps = [d for d in pip_deps if not d.get('resolution_blocked')]
    if pip_deps:
        pip_deps = check_python_outdated(pip_deps)
        pip_deps = check_python_vulns(repo_path, pip_deps)

    return finalize_dep_health(pip_deps + blocked) + other_deps


# ── Node dependency health (Packet 14) ────────────────────────────────────────


def _group_by_manifest_dir(repo_path: Path, deps: list[dict]) -> dict[Path, list[dict]]:
    """Keep independent declaration projects in their physically declaring directory."""
    groups: dict[Path, list[dict]] = {}
    for dep in deps:
        source = dep.get('source_path')
        directory = ((repo_path / source).resolve().parent if source else repo_path.resolve())
        groups.setdefault(directory, []).append(dep)
    return groups


def _tool_version(value) -> str | None:
    """Accept concrete comparable versions, never ranges or tool sentinels."""
    if not isinstance(value, str) or not re.match(r'^v?\d', value):
        return None
    return _exact_pip_version(value)


def _npm_lock_versions(manifest_dir: Path) -> dict[str, str]:
    """Read direct v1–v3 lock entries, honoring npm's shrinkwrap precedence."""
    try:
        lock = manifest_dir / 'npm-shrinkwrap.json'
        if not lock.exists():
            lock = manifest_dir / 'package-lock.json'
        raw = json.loads(lock.read_text())
        if not isinstance(raw, dict):
            return {}
        layout = raw.get('lockfileVersion', 1)
        if layout == 1:
            entries = raw.get('dependencies', {})
        elif layout in (2, 3):
            entries = {path[len('node_modules/'):]: entry
                       for path, entry in raw.get('packages', {}).items()
                       if path.startswith('node_modules/') and '/node_modules/' not in path}
        else:
            return {}
        return {name: entry['version'] for name, entry in entries.items()
                if isinstance(entry, dict) and not entry.get('link') and _tool_version(entry.get('version'))}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _npm_installed_version(manifest_dir: Path, name: str) -> str | None:
    """Read package metadata only; never load JavaScript or execute lifecycle code."""
    if not re.fullmatch(r'(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
        return None
    try:
        raw = json.loads((manifest_dir / 'node_modules' / name / 'package.json').read_text())
        if isinstance(raw, dict) and raw.get('name') == name:
            return _tool_version(raw.get('version'))
    except (OSError, ValueError):
        pass
    return None


def _npm_latest_version(npm: str, manifest_dir: Path, name: str) -> str:
    proc = subprocess.run([npm, 'view', name, 'version', '--json'], cwd=str(manifest_dir),
                          capture_output=True, text=True, timeout=30)
    _validate_tool_result(proc, 'npm view', (0,))
    version = _tool_version(json.loads(proc.stdout))
    if not version:
        raise ValueError('registry comparison did not return a concrete version')
    return version


def _required_text(row: dict, key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'missing or invalid {key}')
    return value


def _version_finding(dep: dict, current: str, latest: str, tool: str) -> None:
    try:
        severity = classify_severity(current, latest)
    except Exception as exc:
        mark_unchecked(dep, tool_failure_note(tool, exc), 'outdated_state')
        return
    dep.update(current_version=current, wanted_version=current, latest_version=latest,
               outdated_state='checked', severity=severity)


def _merge_vulnerability_report(deps: list[dict], findings: dict[str, str], tool: str,
                                evaluated: set[str] | None = None,
                                finding_versions: dict[str, dict[str, str]] | None = None) -> list[dict]:
    """A findings-only report does not by itself prove an absent declaration was audited."""
    result = []
    for dep in deps:
        d = dict(dep)
        name = d.get('name', '')
        if name in findings:
            versions = finding_versions.get(name, {}) if finding_versions is not None else None
            current = d.get('current_version')
            if versions is not None and ((current and current not in versions)
                                         or (not current and len(versions) != 1)):
                mark_unchecked(d, f'{tool}: finding version does not match current version', 'vuln_state')
            else:
                if versions is not None and not current:
                    current = d['current_version'] = next(iter(versions))
                advisory = versions[current] if versions is not None else findings[name]
                d.update(severity='vulnerable', advisory_id=advisory, vuln_state='checked')
        elif evaluated is not None and name in evaluated:
            d['vuln_state'] = 'checked'
        else:
            mark_unchecked(d, f'{tool}: report does not establish declaration evaluation', 'vuln_state')
        result.append(d)
    return result


def check_node_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run npm outdated --json and enrich each npm dep with version/severity fields.

    If npm is not available (TOOLS["npm"] is None), returns deps unchanged.
    Handles npm's non-zero exit code when outdated packages exist (this is normal).
    Missing version or comparison evidence remains unchecked with a reason.
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
        _validate_tool_result(proc, 'npm outdated', (0, 1))
        # npm outdated exits with code 1 when outdated packages exist — this is normal.
        # Only treat as error if stdout is empty/unparseable and returncode is non-zero.
        if not proc.stdout.strip() and proc.returncode != 0:
            logger.warning("npm outdated returned no output for %s (rc=%d)", repo_path, proc.returncode)
            return _check_failed(deps, 'npm outdated', ValueError('no tool output'), 'outdated_state')
        outdated_map = json.loads(proc.stdout)
        if not isinstance(outdated_map, dict) or 'error' in outdated_map:
            raise ValueError('invalid npm outdated result')
        if not all(isinstance(info, dict) for info in outdated_map.values()):
            raise ValueError('invalid npm outdated row')
        if proc.returncode == 1 and not outdated_map:
            raise ValueError('outdated exit status without findings')
    except subprocess.CalledProcessError as exc:
        return _check_failed(deps, 'npm outdated', exc, 'outdated_state')
    except Exception as exc:
        return _check_failed(deps, 'npm outdated', exc, 'outdated_state')

    versions = _npm_lock_versions(repo_path)
    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        info = outdated_map.get(name, {})
        current = (_tool_version(info.get('current')) or versions.get(name)
                   or _npm_installed_version(repo_path, name))
        d['current_version'] = current
        d['wanted_version'] = _tool_version(info.get('wanted'))
        d['latest_version'] = _tool_version(info.get('latest'))
        d["checked_at"] = now
        if not current:
            mark_unchecked(d, 'npm outdated: no concrete current or locked version', 'outdated_state')
        else:
            try:
                latest = d['latest_version']
                if name not in outdated_map:
                    latest = _npm_latest_version(npm, repo_path, name)
                    d['latest_version'] = latest
                if not latest:
                    raise ValueError('missing latest version comparison')
                d['outdated_state'] = 'checked'
                d['severity'] = classify_severity(current, latest)
            except Exception as exc:
                mark_unchecked(d, tool_failure_note('npm outdated comparison', exc), 'outdated_state')
        result.append(d)

    return result


def check_node_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run npm audit --json and merge vulnerability info into dep dicts.

    If npm is not available (TOOLS["npm"] is None), returns deps unchanged.
    Handles npm's non-zero exit code when vulnerabilities exist (normal behavior).
    A failed audit or missing declaration coverage remains unchecked.
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
            return _check_failed(deps, 'npm audit', ValueError('no tool output'), 'vuln_state')
        raw = json.loads(proc.stdout)
        if isinstance(raw, dict) and 'error' in raw:
            error = raw['error']
            if isinstance(error, dict) and error.get('code') == 'ENOLOCK':
                raise ValueError('lockfile required (ENOLOCK)')
            raise ValueError('tool returned an error object')
        _validate_tool_result(proc, 'npm audit', (0, 1))
        if not isinstance(raw, dict) or not isinstance(raw.get('vulnerabilities'), dict):
            raise ValueError('invalid npm audit result')
        for name, entry in raw['vulnerabilities'].items():
            if (not isinstance(entry, dict) or entry.get('name') != name
                    or not isinstance(entry.get('severity'), str)
                    or not isinstance(entry.get('via'), list) or not entry['via']
                    or not isinstance(entry.get('nodes'), list) or not entry['nodes']
                    or not all(isinstance(node, str) and node for node in entry['nodes'])
                    or not all(isinstance(via, (str, dict)) and via for via in entry['via'])):
                raise ValueError('invalid npm audit vulnerability row')
        if proc.returncode == 1 and not raw['vulnerabilities']:
            raise ValueError('audit exit status without vulnerability findings')
    except subprocess.CalledProcessError as exc:
        return _check_failed(deps, 'npm audit', exc, 'vuln_state')
    except Exception as exc:
        return _check_failed(deps, 'npm audit', exc, 'vuln_state')

    # npm audits the virtual lock tree, while outdated may describe node_modules.
    # Reuse direct lock evidence and match the finding's affected node location.
    versions = _npm_lock_versions(repo_path)
    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get('name', '')
        audited_version = versions.get(name)
        current = d.get('current_version')
        if not audited_version:
            mark_unchecked(d, 'npm audit: declaration absent from audited lock evidence', 'vuln_state')
        elif current and current != audited_version:
            mark_unchecked(d, f'npm audit: audited lock version {audited_version} does not match current version {current}', 'vuln_state')
        else:
            if not current:
                d['current_version'] = audited_version
            d['vuln_state'] = 'checked'
            finding = raw['vulnerabilities'].get(name)
            if finding and f'node_modules/{name}' in finding['nodes']:
                d.update(severity='vulnerable', advisory_id=f'npm:{name}')
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

    npm_deps = [d for directory, group in _group_by_manifest_dir(repo_path, npm_deps).items()
                for d in check_node_vulns(directory, check_node_outdated(directory, group))]

    return finalize_dep_health(npm_deps) + other_deps


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
    On subprocess or parse failure, marks the affected check unchecked with a reason.
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
        _validate_tool_result(proc, 'go list', (0,))
        modules = _parse_go_ndjson(proc.stdout)
        if not all(isinstance(m, dict) for m in modules):
            raise ValueError('invalid module result')
        mod_map: dict[str, dict] = {}
        for mod in modules:
            path = _required_text(mod, 'Path')
            if mod.get('Error'):
                raise ValueError('module evaluation error')
            if mod.get('Main') is True:
                continue
            version = _required_text(mod, 'Version')
            if mod.get('Replace'):
                # Replacement versions/paths may have a different comparison target.
                continue
            update = mod.get('Update')
            update_version = None
            if 'Update' in mod:
                if not isinstance(update, dict) or update.get('Error'):
                    raise ValueError('invalid module update')
                update_version = _required_text(update, 'Version')
            if path in mod_map:
                raise ValueError('duplicate module result')
            mod_map[path] = {'version': version, 'update': update_version}
    except Exception as exc:
        return _check_failed(deps, 'go list', exc, 'outdated_state')

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in mod_map:
            info = mod_map[name]
            current = info["version"]
            update_ver = info["update"]
            _version_finding(d, current, update_ver or current, 'go list')
        else:
            mark_unchecked(d, 'go list: declaration absent from evaluated module rows', 'outdated_state')
        result.append(d)
    return result


def check_go_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run govulncheck -json ./... and merge vulnerability info into gomod dep dicts.

    If govulncheck is not available (TOOLS["govulncheck"] is None), returns deps unchanged.
    Parses the v1 streaming config/SBOM/finding protocol. OSV entries alone
    describe possible advisories, not findings for the scanned version.
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
        # JSON output reports findings in the stream and exits zero; nonzero is failure.
        _validate_tool_result(proc, 'govulncheck', (0,))
        messages = _parse_go_ndjson(proc.stdout)
        if (not messages or not isinstance(messages[0], dict)
                or messages[0].get('config', {}).get('protocol_version') != 'v1.0.0'):
            raise ValueError('missing supported govulncheck protocol config')
        evaluated_versions: set[tuple[str, str]] = set()
        versioned_findings: dict[tuple[str, str], str] = {}
        for message in messages:
            if not isinstance(message, dict) or len(message) != 1:
                raise ValueError('invalid govulncheck message')
            kind, entry = next(iter(message.items()))
            if kind not in ('config', 'progress', 'SBOM', 'osv', 'finding') or not isinstance(entry, dict):
                raise ValueError('invalid govulncheck message type')
            if kind == 'SBOM':
                modules = entry.get('modules', [])
                if not isinstance(modules, list):
                    raise ValueError('invalid govulncheck SBOM modules')
                for module in modules:
                    name = _required_text(module, 'path')
                    version = module.get('version')
                    if isinstance(version, str) and version:
                        evaluated_versions.add((name, version))
            elif kind == 'finding':
                advisory = _required_text(entry, 'osv')
                trace = entry.get('trace')
                if not isinstance(trace, list) or not trace or not isinstance(trace[0], dict):
                    raise ValueError('invalid govulncheck finding trace')
                name = _required_text(trace[0], 'module')
                version = _required_text(trace[0], 'version')
                evaluated_versions.add((name, version))
                versioned_findings[name, version] = advisory
            elif kind == 'osv':
                _required_text(entry, 'id')
    except Exception as exc:
        return _check_failed(deps, 'govulncheck', exc, 'vuln_state')
    evaluated = {d['name'] for d in deps if (d['name'], d.get('current_version') or d.get('version'))
                 in evaluated_versions}
    findings = {d['name']: versioned_findings[d['name'], d.get('current_version') or d.get('version')]
                for d in deps if (d['name'], d.get('current_version') or d.get('version')) in versioned_findings}
    return _merge_vulnerability_report(deps, findings, 'govulncheck', evaluated)


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

    go_deps = [d for directory, group in _group_by_manifest_dir(repo_path, go_deps).items()
               for d in check_go_vulns(directory, check_go_outdated(directory, group))]

    return finalize_dep_health(go_deps) + other_deps


# ── Rust dependency health (Packet 15) ────────────────────────────────────────


def check_rust_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run cargo outdated --format json and enrich cargo deps with version/severity fields.

    If cargo-outdated is not available (TOOLS["cargo_outdated"] is None), returns deps unchanged.
    On subprocess or parse failure, marks the affected check unchecked with a reason.
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
        _validate_tool_result(proc, 'cargo outdated', (0,))
        raw = json.loads(proc.stdout)
        if not isinstance(raw, dict) or 'error' in raw or not isinstance(raw.get('dependencies'), list):
            raise ValueError('invalid cargo outdated result')
    except Exception as exc:
        return _check_failed(deps, 'cargo outdated', exc, 'outdated_state')

    # Build lookup: {name: {"project": current, "latest": latest}}
    outdated_map: dict[str, dict] = {}
    try:
        for entry in raw.get("dependencies", []):
            name = _required_text(entry, 'name')
            if name in outdated_map:
                raise ValueError('duplicate cargo outdated row')
            outdated_map[name] = {'project': _required_text(entry, 'project'),
                                  'latest': _required_text(entry, 'latest')}
    except Exception as exc:
        return _check_failed(deps, 'cargo outdated', exc, 'outdated_state')

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            _version_finding(d, info['project'], info['latest'], 'cargo outdated')
        else:
            mark_unchecked(d, 'cargo outdated: report does not establish declaration evaluation', 'outdated_state')
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
        _validate_tool_result(proc, 'cargo audit', (0, 1))
        raw = json.loads(proc.stdout)
        if (not isinstance(raw, dict) or 'error' in raw
                or not isinstance(raw.get('vulnerabilities'), dict)
                or not isinstance(raw['vulnerabilities'].get('list'), list)):
            raise ValueError('invalid cargo audit result')
    except Exception as exc:
        return _check_failed(deps, 'cargo audit', exc, 'vuln_state')

    # Build lookup: {package_name: rustsec_id}
    vuln_map: dict[str, str] = {}
    finding_versions: dict[str, dict[str, str]] = {}
    try:
        for entry in raw.get("vulnerabilities", {}).get("list", []):
            advisory_id = _required_text(entry.get('advisory', {}), 'id')
            pkg_name = _required_text(entry.get('package', {}), 'name')
            version = _required_text(entry.get('package', {}), 'version')
            if not _tool_version(version):
                raise ValueError('invalid cargo audit package version')
            vuln_map[pkg_name] = advisory_id
            finding_versions.setdefault(pkg_name, {})[version] = advisory_id
        if proc.returncode == 1 and not vuln_map:
            raise ValueError('cargo audit failed without vulnerability findings')
    except Exception as exc:
        return _check_failed(deps, 'cargo audit', exc, 'vuln_state')

    return _merge_vulnerability_report(deps, vuln_map, 'cargo audit', finding_versions=finding_versions)


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

    cargo_deps = [d for directory, group in _group_by_manifest_dir(repo_path, cargo_deps).items()
                  for d in check_rust_vulns(directory, check_rust_outdated(directory, group))]

    return finalize_dep_health(cargo_deps) + other_deps


# ── Ruby dependency health (Packet 15) ────────────────────────────────────────


def check_ruby_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run bundle outdated --parseable and enrich bundler deps with version/severity fields.

    If bundle is not available (TOOLS["bundle"] is None), returns deps unchanged.
    Parses line-by-line output: 'gem-name (newest X.Y.Z, installed A.B.C, ...)'.
    On subprocess or parse failure, marks the affected check unchecked with a reason.
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
        _validate_tool_result(proc, 'bundle outdated', (0, 1))
        stdout = proc.stdout
        if stdout.strip() and not any(' (newest ' in line for line in stdout.splitlines()):
            raise ValueError('unrecognized bundle outdated output')
    except Exception as exc:
        return _check_failed(deps, 'bundle outdated', exc, 'outdated_state')

    # Parse line-by-line: gem-name (newest X.Y.Z, installed A.B.C[, requested ~> A.B])
    _BUNDLE_LINE_RE = re.compile(
        r'^(\S+)\s+\(newest\s+([^,]+),\s+installed\s+([^,)]+)(?:, requested [^)]+)?\)$'
    )
    outdated_map: dict[str, dict] = {}
    try:
        for line in stdout.splitlines():
            if not line.strip():
                continue
            m = _BUNDLE_LINE_RE.fullmatch(line.strip())
            if not m or m.group(1) in outdated_map:
                raise ValueError('invalid bundle outdated row')
            gem_name = m.group(1)
            newest = m.group(2).strip()
            installed = m.group(3).strip()
            outdated_map[gem_name] = {"installed": installed, "newest": newest}
        if proc.returncode == 1 and not outdated_map:
            raise ValueError('bundle outdated failed without findings')
    except Exception as exc:
        return _check_failed(deps, 'bundle outdated', exc, 'outdated_state')

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            _version_finding(d, info['installed'], info['newest'], 'bundle outdated')
        else:
            mark_unchecked(d, 'bundle outdated: report does not establish declaration evaluation', 'outdated_state')
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
        _validate_tool_result(proc, 'bundler-audit', (0, 1))
        raw = json.loads(proc.stdout)
        if not isinstance(raw, dict) or 'error' in raw or not isinstance(raw.get('results'), list):
            raise ValueError('invalid bundler-audit result')
    except Exception as exc:
        return _check_failed(deps, 'bundler-audit', exc, 'vuln_state')

    # Build lookup: {gem_name: advisory_id}, retaining audited-version attribution.
    vuln_map: dict[str, str] = {}
    finding_versions: dict[str, dict[str, str]] = {}
    try:
        for entry in raw.get("results", []):
            if entry.get('type') != 'unpatched_gem':
                raise ValueError('unsupported bundler-audit finding type')
            gem_name = _required_text(entry.get('gem', {}), 'name')
            version = _required_text(entry.get('gem', {}), 'version')
            if not _tool_version(version):
                raise ValueError('invalid bundler-audit gem version')
            advisory_id = _required_text(entry.get('advisory', {}), 'id')
            vuln_map[gem_name] = advisory_id
            finding_versions.setdefault(gem_name, {})[version] = advisory_id
        if proc.returncode == 1 and not vuln_map:
            raise ValueError('bundler-audit failed without vulnerability findings')
    except Exception as exc:
        return _check_failed(deps, 'bundler-audit', exc, 'vuln_state')

    return _merge_vulnerability_report(deps, vuln_map, 'bundler-audit', finding_versions=finding_versions)


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

    ruby_deps = [d for directory, group in _group_by_manifest_dir(repo_path, ruby_deps).items()
                 for d in check_ruby_vulns(directory, check_ruby_outdated(directory, group))]

    return finalize_dep_health(ruby_deps) + other_deps


# ── PHP dependency health (Packet 15) ─────────────────────────────────────────


def check_php_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run composer outdated --format=json and enrich composer deps with version/severity fields.

    If composer is not available (TOOLS["composer"] is None), returns deps unchanged.
    Requests all installed rows, including up-to-date packages, for explicit coverage.
    On subprocess or parse failure, marks the affected check unchecked with a reason.
    """
    composer = TOOLS.get("composer")
    if not composer:
        return deps

    try:
        proc = subprocess.run(
            [composer, "outdated", "--all", "--format=json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        _validate_tool_result(proc, 'composer outdated', (0,))
        raw = json.loads(proc.stdout)
        if not isinstance(raw, dict) or 'error' in raw or not isinstance(raw.get('installed'), list):
            raise ValueError('invalid composer outdated result')
    except Exception as exc:
        return _check_failed(deps, 'composer outdated', exc, 'outdated_state')

    # Build lookup: {name: {"version": current, "latest": latest}}
    outdated_map: dict[str, dict] = {}
    try:
        for entry in raw.get("installed", []):
            status = _required_text(entry, 'latest-status')
            if status not in ('up-to-date', 'semver-safe-update', 'update-possible'):
                raise ValueError('invalid composer latest-status')
            name = _required_text(entry, 'name')
            if name in outdated_map:
                raise ValueError('duplicate composer outdated row')
            outdated_map[name] = {'version': _required_text(entry, 'version'),
                                  'latest': _required_text(entry, 'latest')}
    except Exception as exc:
        return _check_failed(deps, 'composer outdated', exc, 'outdated_state')

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            _version_finding(d, info['version'], info['latest'], 'composer outdated')
        else:
            mark_unchecked(d, 'composer outdated: declaration absent from evaluated package rows', 'outdated_state')
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
        _validate_tool_result(proc, 'composer audit', (0, 1))
        raw = json.loads(proc.stdout)
        if not isinstance(raw, dict) or 'error' in raw or not isinstance(raw.get('advisories'), dict):
            raise ValueError('invalid composer audit result')
    except Exception as exc:
        return _check_failed(deps, 'composer audit', exc, 'vuln_state')

    # Build lookup: {package_name: advisory_id}
    # composer audit JSON: {"advisories": {"pkg/name": [{"advisoryId": "...", ...}]}}
    vuln_map: dict[str, str] = {}
    try:
        for pkg_name, advisories in raw.get("advisories", {}).items():
            if not isinstance(advisories, list) or not advisories:
                raise ValueError('invalid composer advisory list')
            for advisory in advisories:
                if _required_text(advisory, 'packageName') != pkg_name:
                    raise ValueError('composer advisory package mismatch')
                advisory_id = _required_text(advisory, 'advisoryId')
                vuln_map[pkg_name] = advisory_id
        if proc.returncode == 1 and not vuln_map:
            raise ValueError('composer audit failed without vulnerability findings')
    except Exception as exc:
        return _check_failed(deps, 'composer audit', exc, 'vuln_state')

    return _merge_vulnerability_report(deps, vuln_map, 'composer audit')


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

    php_deps = [d for directory, group in _group_by_manifest_dir(repo_path, php_deps).items()
                for d in check_php_vulns(directory, check_php_outdated(directory, group))]

    return finalize_dep_health(php_deps) + other_deps


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
  <!-- frontend-vendor -->
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
    .activity-chart .svgc-wrapper svg text,
    .allocation-chart .svgc-wrapper svg text {
      font-family: var(--font-mono);
      font-size: 11px;
      fill: var(--text-muted);
    }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="module">
/* Delete button — CSS :hover controls visibility */
/* Scan-failed badge — CSS :hover hides it when delete button is visible */
/* Row 1: RuntimeBadge + name (with tooltip) + time */
/* Row 2: Last commit message or path-not-found error */
/* Row 3: Status pills + branch + branch count + dep badge */
/* Month labels */
/* Day labels (Mon, Wed, Fri only) */
/* Grid */
/* Tooltip */
/* Legend */
/* KPI summary */
/* Per-repo dep summaries */
/* Dependency Overlap */
const htmlTag = htm.bind(preact.h);
    const {useState, useEffect, useRef, useLayoutEffect, useMemo} = preactHooks;

    // ── ErrorBoundary ────────────────────────────────────────────────────────
    class ErrorBoundary extends preact.Component {
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
            htmlTag`<div style=${{
              padding: '48px',
              textAlign: 'center',
              color: 'var(--status-red)',
              fontFamily: 'var(--font-mono)',
            }}> <p style=${{ fontSize: '16px', marginBottom: '8px' }}>Something went wrong</p> <p style=${{ fontSize: '13px', color: 'var(--text-muted)' }}> ${this.state.error && this.state.error.toString()} </p> </div>`
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
        htmlTag`<header style=${{
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
        }}> <span style=${{
            fontFamily: 'var(--font-heading)',
            fontSize: '18px',
            fontWeight: 700,
            color: 'var(--text-primary)',
          }}> Git Fleet </span> <div style=${{ display: 'flex', gap: '8px', alignItems: 'center' }}> <button onClick=${onScanDir} style=${{
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
              }}> Scan Dir </button> <button onClick=${onFullScan} disabled=${scanActive} style=${{
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
              }}> Full Scan </button> </div> </header>`
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
        htmlTag`<nav style=${{
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
        }}> <div style=${{ position: 'relative', display: 'flex' }}> ${TABS.map((tab, i) => (
              htmlTag`<a key=${tab.id} href=${tab.hash} ref=${el => tabRefs.current[i] = el} style=${{
                  display: 'block',
                  padding: '10px 16px',
                  fontFamily: 'var(--font-heading)',
                  fontSize: '14px',
                  fontWeight: 500,
                  color: activeTab === tab.id ? 'var(--accent-blue)' : 'var(--text-secondary)',
                  textDecoration: 'none',
                  transition: 'color var(--transition-fast)',
                  whiteSpace: 'nowrap',
                }}> ${tab.label} </a>`
            ))} <div ref=${indicatorRef} style=${{
                position: 'absolute',
                bottom: 0,
                height: '3px',
                background: 'var(--accent-blue)',
                borderRadius: '3px 3px 0 0',
                transition: 'left var(--transition-normal), width var(--transition-normal)',
                left: 0,
                width: 0,
              }} /> </div> </nav>`
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
        htmlTag`<div style=${{
          margin: '16px 24px 0',
          padding: '12px 16px',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border-default)',
          background: 'var(--bg-secondary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
        }}> <div style=${{ display: 'flex', flexDirection: 'column', gap: '2px' }}> <strong style=${{ fontFamily: 'var(--font-heading)', fontSize: '13px', color: 'var(--text-primary)' }}> Tool status </strong> <span style=${{ fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-secondary)' }}> Version ${status.version} with ${toolCount} detected helper tool${toolCount === 1 ? '' : 's'}. </span> </div> <button onClick=${() => {
              try {
                sessionStorage.setItem('git-fleet-status-banner-dismissed', '1');
              } catch (_err) {
                // Ignore browsers that block sessionStorage.
              }
              setDismissed(true);
            }} style=${{
              background: 'transparent',
              border: '1px solid var(--border-default)',
              color: 'var(--text-secondary)',
              borderRadius: '999px',
              cursor: 'pointer',
              fontFamily: 'var(--font-body)',
              fontSize: '12px',
              padding: '6px 10px',
            }}> Dismiss </button> </div>`
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
        htmlTag`<div style=${{
          position: 'fixed',
          top: '100px',   // header(56) + nav(44)
          left: 0,
          right: 0,
          height: '3px',
          background: 'var(--border-default)',
          zIndex: 98,
        }}> <div style=${{
            height: '3px',
            width: pct + '%',
            background: fillColor,
            transition: 'width 300ms ease-out, background 300ms ease-out',
          }} /> </div>`
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
        htmlTag`<div style=${overlayStyle} onClick=${(e) => { if (e.target === e.currentTarget) onClose(); }}> <div style=${modalStyle}> <div style=${headerStyle}> <span style=${{ fontWeight: 600, fontSize: '15px', color: 'var(--text-primary)', fontFamily: 'var(--font-body)' }}> Select Directory to Scan </span> <button onClick=${onClose} style=${{ ...btnBase, background: 'none', color: 'var(--text-muted)', fontSize: '18px', padding: '4px 8px' }}>${'\u00d7'}</button> </div> <div style=${inputRowStyle}> <input type=${"text"} value=${pathInput} onInput=${(e) => setPathInput(e.target.value)} onKeyDown=${handleKeyDown} style=${inputStyle} placeholder=${"/path/to/directory"} /> <button onClick=${() => browse(pathInput)} style=${{ ...btnBase, background: 'var(--bg-secondary)', color: 'var(--text-primary)', border: '1px solid var(--border-default)' }}>Go</button> </div> <div style=${listStyle}> ${error && htmlTag`<div style=${{ padding: '12px 20px', color: 'var(--status-red)', fontSize: '13px' }}>${error}</div>`} ${loading && htmlTag`<div style=${{ padding: '12px 20px', color: 'var(--text-muted)', fontSize: '13px' }}>Loading...</div>`} ${!loading && !error && (
                htmlTag` ${parentPath && (
                    htmlTag`<div onClick=${() => browse(parentPath)} style=${{ ...itemStyle(false), color: 'var(--text-muted)' }} onMouseEnter=${(e) => e.currentTarget.style.background = 'var(--bg-secondary)'} onMouseLeave=${(e) => e.currentTarget.style.background = 'transparent'}> ${'\u2190'} .. </div>`
                  )} ${dirs.length === 0 && !parentPath && (
                    htmlTag`<div style=${{ padding: '12px 20px', color: 'var(--text-muted)', fontSize: '13px' }}>No subdirectories</div>`
                  )} ${dirs.map(d => (
                    htmlTag`<div key=${d.path} onClick=${() => browse(d.path)} style=${itemStyle(d.is_git)} onMouseEnter=${(e) => e.currentTarget.style.background = 'var(--bg-secondary)'} onMouseLeave=${(e) => e.currentTarget.style.background = 'transparent'}> <span style=${{ fontFamily: 'monospace' }}>${d.is_git ? '[repo]' : '[dir]'}</span> <span style=${{ flex: 1 }}>${d.name}</span> ${d.is_git && htmlTag`<span style=${{ fontSize: '11px', color: 'var(--accent-blue)', fontWeight: 500 }}>git</span>`} </div>`
                  ))} `
              )} </div> <div style=${footerStyle}> <button onClick=${onClose} style=${{ ...btnBase, background: 'var(--bg-secondary)', color: 'var(--text-primary)', border: '1px solid var(--border-default)' }}>Cancel</button> <button onClick=${() => { onSelect(currentPath); onClose(); }} style=${{ ...btnBase, background: 'var(--accent-blue)', color: '#fff' }}> Scan This Directory </button> </div> </div> </div>`
      );
    }

    // ── ScanToast ─────────────────────────────────────────────────────────────
    // Fixed bottom-right notification showing scan progress.
    function ScanToast({ scanState }) {
      const { active, status, progress, total, currentRepo } = scanState;
      const [visible, setVisible] = useState(false);
      const [slideOut, setSlideOut] = useState(false);

      useEffect(() => {
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
        htmlTag`<div style=${{
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
        }}> <div style=${{
            fontFamily: 'var(--font-heading)',
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: '6px',
          }}> ${heading} </div> ${currentRepo && (
            htmlTag`<div style=${{
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              color: 'var(--text-secondary)',
              marginBottom: '8px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}> ${currentRepo} </div>`
          )} <div style=${{ marginBottom: '4px' }}> <div style=${{
              height: '4px',
              background: 'var(--border-default)',
              borderRadius: '2px',
              overflow: 'hidden',
            }}> <div style=${{
                height: '4px',
                width: pct + '%',
                background: fillColor,
                transition: 'width 300ms ease-out, background 300ms ease-out',
              }} /> </div> </div> <div style=${{
            fontFamily: 'var(--font-body)',
            fontSize: '12px',
            color: 'var(--text-muted)',
            textAlign: 'right',
          }}> ${progress} / ${total || '?'} </div> </div>`
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
        htmlTag`<span style=${{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: '24px', height: '24px', flexShrink: 0,
          borderRadius: '4px',
          background: `color-mix(in srgb, ${color} 20%, transparent)`,
          color: color,
          fontFamily: 'var(--font-heading)',
          fontSize: '11px', fontWeight: 700,
        }}> ${label} </span>`
      );
    }

    // StatusPills — Clean or mod/new/staged pills
    function StatusPills({ repo }) {
      const { has_uncommitted, modified_count, untracked_count, staged_count } = repo;
      if (!has_uncommitted) {
        return (
          htmlTag`<span style=${{
            fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500,
            padding: '2px 8px', borderRadius: '4px',
            color: 'var(--status-green)', background: 'var(--status-green-bg)',
          }}>Clean</span>`
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
        htmlTag`<span style=${{ display: 'inline-flex', gap: '4px', flexWrap: 'wrap' }}> ${pills.map(p => (
            htmlTag`<span key=${p.label} style=${{
              fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500,
              padding: '2px 8px', borderRadius: '4px',
              color: p.color, background: p.bg,
            }}>${p.label}</span>`
          ))} </span>`
      );
    }

    // DepBadge — compact dep summary pill with coverage dot
    function DepBadge({ dep, missingTools, analysisError }) {
      if (!dep && !missingTools?.length && !analysisError) return null;
      dep = dep || {total: 0};
      const { total, outdated, vulnerable } = dep;
      if (!total && total !== 0) return null;

      const hasMissing = missingTools && missingTools.length > 0;
      const incomplete = analysisError || hasMissing || dep.unchecked > 0;
      const dotColor = incomplete ? 'var(--status-orange)' : 'var(--status-green)';
      const dotTitle = incomplete
        ? 'Incomplete coverage: ' + (dep.unchecked || 0) + ' not checked' + (analysisError ? '; analysis error — see repository dependencies' : '') + (hasMissing ? '; missing tools: ' + missingTools.map(t => t.tool || t).join(', ') : '')
        : 'All declarations fully checked';

      let label = null;
      if (vulnerable > 0) {
        label = htmlTag`<span style=${{
          fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 400,
          color: 'var(--status-red)',
        }}>${vulnerable} vuln</span>`;
      } else if (outdated > 0) {
        label = htmlTag`<span style=${{
          fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 400,
          color: 'var(--status-yellow)',
        }}>${outdated} out</span>`;
      } else if (total > 0) {
        label = htmlTag`<span style=${{
          fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 400,
          color: 'var(--text-muted)',
        }}>${total} deps</span>`;
      }
      if (!label && hasMissing) label = htmlTag`<span>Missing tools</span>`;
      if (!label && analysisError) label = htmlTag`<span>Analysis error</span>`;
      if (!label) return null;

      return (
        htmlTag`<span style=${{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}> <span title=${dotTitle} style=${{
              display: 'inline-block', width: '6px', height: '6px',
              borderRadius: '50%', background: dotColor, flexShrink: 0,
            }} /> ${label} ${total > 0 && analysisError && htmlTag`<span style=${{color: 'var(--status-orange)'}}>Analysis error</span>`} </span>`
      );
    }

    // SparklineOverlay — slides up from bottom on card hover
    function SparklineOverlay({ sparkline, visible }) {
      const data = (sparkline || []).map((v, i) => ({ i, v }));
      return (
        htmlTag`<div style=${{
          position: 'absolute', bottom: 0, left: 0, right: 0, height: '32px',
          overflow: 'hidden', pointerEvents: 'none',
          transform: visible ? 'translateY(0)' : 'translateY(100%)',
          transition: visible ? '150ms ease-out' : '100ms ease-in',
          background: 'linear-gradient(transparent, var(--bg-card) 30%)',
        }}> ${data.length > 0 && (
            htmlTag`<${svgCharts.CartesianChart} kind=${"area"} compact=${true} height=${28} data=${data} xKey=${"i"} margin=${{ top: 0, right: 0, bottom: 0, left: 0 }} series=${[{key:'v', color:'var(--accent-blue)', fill:'var(--accent-blue-dim)', strokeWidth:1}]} />`
          )} </div>`
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
        htmlTag`<div class=${"project-card"} style=${cardStyle} tabIndex=${0} role=${"button"} aria-label=${`View ${repo.name} details`} onMouseEnter=${() => setHovered(true)} onMouseLeave=${() => setHovered(false)} onFocusIn=${() => setFocused(true)} onFocusOut=${e => { if (!e.currentTarget.contains(e.relatedTarget)) setFocused(false); }} onClick=${() => { window.location.hash = '#/repo/' + repo.id; }} onKeyDown=${(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              window.location.hash = '#/repo/' + repo.id;
            }
          }}>  <button class=${"card-delete-btn"} onClick=${handleDelete} title=${`Remove ${repo.name}`} aria-label=${`Remove ${repo.name}`} style=${{
              position: 'absolute', top: '8px', right: '8px', zIndex: 5,
              background: 'var(--bg-secondary)', border: '1px solid var(--border-default)',
              color: 'var(--text-muted)', cursor: 'pointer',
              width: '22px', height: '22px', borderRadius: '4px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '14px', lineHeight: 1, padding: 0,
            }}>${'\u00d7'}</button>  ${repo.scan_error && (
            htmlTag`<div class=${"scan-failed-badge"} style=${{
              position: 'absolute', top: '8px', right: '8px',
              fontSize: '10px', fontFamily: 'var(--font-body)', fontWeight: 600,
              color: 'var(--status-red)', background: 'var(--status-red-bg)',
              padding: '2px 6px', borderRadius: '3px',
            }}> scan failed </div>`
          )}  <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}> <${RuntimeBadge} runtime=${repo.runtime} /> <div style=${{ position: 'relative', flex: 1, minWidth: 0 }}> <span style=${{
                  display: 'block',
                  fontFamily: 'var(--font-heading)', fontSize: '16px', fontWeight: 600,
                  color: 'var(--text-primary)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  cursor: 'pointer',
                }} onMouseEnter=${() => setTooltipVisible(true)} onMouseLeave=${() => setTooltipVisible(false)}> ${repo.name} </span> ${tooltipVisible && (
                htmlTag`<div style=${{
                  position: 'absolute', bottom: '100%', left: 0, zIndex: 10,
                  background: 'var(--bg-secondary)', border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-sm)', padding: '6px 10px',
                  fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 400,
                  color: 'var(--text-secondary)', maxWidth: '500px',
                  whiteSpace: 'nowrap', pointerEvents: 'none',
                  marginBottom: '4px',
                }}> ${repo.path} </div>`
              )} </div> <span style=${{
              flexShrink: 0, fontSize: '13px',
              fontFamily: 'var(--font-body)', color: 'var(--text-secondary)',
            }}> ${timeAgo(repo.last_commit_date)} </span> </div>  <div style=${{
            fontSize: '13px', fontFamily: 'var(--font-body)',
            color: pathMissing ? 'var(--status-red)' : 'var(--text-secondary)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            marginBottom: '8px', marginLeft: '32px',
            fontWeight: pathMissing ? 600 : 400,
          }}> ${pathMissing
              ? 'Path not found'
              : (repo.last_commit_message || htmlTag`<span style=${{ color: 'var(--text-muted)' }}>—</span>`)} </div>  <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}> <${StatusPills} repo=${repo} /> <span style=${{ flex: 1 }} /> <span style=${{
              fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 400,
              color: 'var(--text-secondary)',
            }}> ${repo.current_branch} </span> <span style=${{
              fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 400,
              color: branchColor,
            }}> ${repo.branch_count || 0}br </span> <${DepBadge} dep=${repo.dep_summary} missingTools=${repo.missing_dep_tools} analysisError=${repo.dep_check_error} /> </div> <${SparklineOverlay} sparkline=${repo.sparkline} visible=${active} /> </div>`
      );
    }

    // KpiCard — single stat card
    function KpiCard({ value, label, color, tooltip }) {
      return (
        htmlTag`<div title=${tooltip || ''} style=${{
            flex: '1 1 140px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)',
            padding: '16px 20px',
            cursor: tooltip ? 'help' : undefined,
          }}> <div style=${{
            fontFamily: 'var(--font-heading)', fontSize: '28px', fontWeight: 700,
            color: color || 'var(--text-primary)',
            lineHeight: 1.1,
          }}>${value}</div> <div style=${{
            fontFamily: 'var(--font-body)', fontSize: '12px', fontWeight: 500,
            color: 'var(--text-secondary)',
            textTransform: 'uppercase', letterSpacing: '0.5px',
            marginTop: '4px',
          }}>${label}</div> </div>`
      );
    }

    // KpiRow — fleet activity, findings, and independent coverage
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
        htmlTag`<div style=${{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}> <${KpiCard} value=${kpis.total_repos ?? 0} label=${"Repos"} tooltip=${"Total repositories tracked"} /> <${KpiCard} value=${kpis.repos_with_changes ?? 0} label=${"Dirty"} color=${dirtyColor} tooltip=${"Repos with uncommitted changes (modified, untracked, or staged files)"} /> <${KpiCard} value=${commitValue} label=${"Commits"} tooltip=${"Commits this week / this month (across all repos)"} /> <${KpiCard} value=${locValue} label=${"Net LOC"} tooltip=${"Net lines of code changed this week (insertions minus deletions, across all repos)"} /> <${KpiCard} value=${kpis.stale_branches ?? 0} label=${"Stale Branches"} color=${staleColor} tooltip=${"Branches with no commits in the last 30 days (across all repos)"} /> <${KpiCard} value=${vulnValue} label=${"Vuln / Outdated"} color=${vulnColor} tooltip=${"Vulnerable dependencies / outdated dependencies (across all repos)"} /> <${KpiCard} value=${kpis.unchecked_deps ?? 0} label=${"Not Checked"} color=${kpis.unchecked_deps > 0 ? 'var(--status-orange)' : undefined} tooltip=${"Declarations with incomplete outdated or vulnerability coverage, including those with findings"} /> </div>`
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
        htmlTag`<div ref=${ref} style=${{ position: 'relative', display: 'inline-block' }}> <button onClick=${() => setOpen(o => !o)} style=${{
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', padding: '6px 12px',
              color: 'var(--text-primary)', fontFamily: 'var(--font-body)', fontSize: '13px',
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px',
              whiteSpace: 'nowrap',
            }}> ${current.label} <svg width=${"10"} height=${"6"} viewBox=${"0 0 10 6"} fill=${"none"}> <path d=${"M1 1l4 4 4-4"} stroke=${"currentColor"} stroke-width=${"1.5"} stroke-linecap=${"round"} /> </svg> </button> ${open && (
            htmlTag`<div style=${{
              position: 'absolute', top: '100%', left: 0, zIndex: 20, marginTop: '4px',
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', minWidth: '180px', overflow: 'hidden',
            }}> ${options.map(opt => (
                htmlTag`<div key=${opt.value} onClick=${() => { onChange(opt.value); setOpen(false); }} style=${{
                    padding: '8px 12px', cursor: 'pointer',
                    fontFamily: 'var(--font-body)', fontSize: '13px',
                    color: opt.value === value ? 'var(--accent-blue)' : 'var(--text-primary)',
                    background: opt.value === value ? 'var(--accent-blue-dim)' : 'transparent',
                  }} onMouseEnter=${e => { if (opt.value !== value) e.currentTarget.style.background = 'var(--bg-card-hover)'; }} onMouseLeave=${e => { if (opt.value !== value) e.currentTarget.style.background = 'transparent'; }}> ${opt.label} </div>`
              ))} </div>`
          )} </div>`
      );
    }

    // GridControls — sort dropdown + filter input
    function GridControls({ sortBy, filterText, onSortChange, onFilterChange }) {
      return (
        htmlTag`<div style=${{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}> <${SortDropdown} value=${sortBy} onChange=${onSortChange} /> <input type=${"text"} placeholder=${"Filter projects..."} value=${filterText} onInput=${e => onFilterChange(e.target.value)} style=${{
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', padding: '6px 12px',
              fontFamily: 'var(--font-body)', fontSize: '13px',
              color: 'var(--text-primary)', outline: 'none', width: '220px',
            }} onFocus=${e => { e.target.style.borderColor = 'var(--accent-blue)'; }} onBlur=${e => { e.target.style.borderColor = 'var(--border-default)'; }} /> </div>`
      );
    }

    // EmptyState — shown when no repos are registered
    function EmptyState() {
      return (
        htmlTag`<div style=${{
          textAlign: 'center', padding: '64px 24px',
          color: 'var(--text-muted)',
        }}> <svg width=${"48"} height=${"48"} viewBox=${"0 0 24 24"} fill=${"none"} style=${{ color: 'var(--text-muted)', marginBottom: '16px' }}> <path d=${"M3 3h18v18H3zM9 9h6M9 12h6M9 15h4"} stroke=${"currentColor"} stroke-width=${"1.5"} stroke-linecap=${"round"} /> </svg> <p style=${{ fontFamily: 'var(--font-heading)', fontSize: '16px', marginBottom: '8px' }}> No repositories registered </p> <p style=${{ fontFamily: 'var(--font-body)', fontSize: '14px' }}> Use "Scan Dir" in the header to add repositories. </p> </div>`
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
        htmlTag`<div style=${{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)',
          padding: '14px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}> <div style=${barStyle('60%')} /> <div style=${barStyle('80%')} /> <div style=${barStyle('50%')} /> </div>`
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
          htmlTag`<div style=${{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
            gap: '16px',
            marginTop: '24px',
          }}> <${SkeletonCard} /> <${SkeletonCard} /> <${SkeletonCard} /> </div>`
        );
      }

      const { repos = [], kpis } = data;

      // Filter then sort
      const filtered = repos.filter(r =>
        (r.name || '').toLowerCase().includes(filterText.toLowerCase())
      );
      const sorted = sortRepos(filtered, sortBy);

      return (
        htmlTag`<div> <${KpiRow} kpis=${kpis} /> <div style=${{ marginTop: '24px' }}> <${GridControls} sortBy=${sortBy} filterText=${filterText} onSortChange=${setSortBy} onFilterChange=${setFilterText} /> ${repos.length === 0
              ? htmlTag`<${EmptyState} />`
              : (
                htmlTag`<div style=${{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
                  gap: '16px',
                }}> ${sorted.map(repo => htmlTag`<${ProjectCard} key=${repo.id} repo=${repo} onDelete=${(id) => {
                    setData(prev => prev ? { ...prev, repos: prev.repos.filter(r => r.id !== id) } : prev);
                  }} />`)} </div>`
              )} </div> </div>`
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
        htmlTag`<div class=${"detail-header"}> <div> <button class=${"detail-back-btn"} onClick=${() => { window.location.hash = '#/fleet'; }} aria-label=${"Back to fleet"}> <svg width=${"14"} height=${"14"} viewBox=${"0 0 14 14"} fill=${"none"} aria-hidden=${"true"}> <path d=${"M9 2L4 7L9 12"} stroke=${"currentColor"} stroke-width=${"1.5"} stroke-linecap=${"round"} stroke-linejoin=${"round"} /> </svg> Back </button> <h1 style=${{ fontFamily: 'var(--font-heading)', fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '4px' }}> ${repo.name} </h1> <p style=${{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: pathMissing ? 'var(--status-red)' : 'var(--text-muted)', marginBottom: '6px' }}> ${repo.path}${pathMissing && ' — Path not found'} </p> <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-secondary)' }}> <${RuntimeBadge} runtime=${repo.runtime} /> <span onClick=${onGoToBranches} style=${{ cursor: 'pointer', borderBottom: '1px dotted var(--text-muted)' }} title=${"Switch branch"}> ${selectedBranch || repo.default_branch} </span> <span>·</span> <span>Last scanned ${scanAge}</span> </div> ${pathMissing && (
              htmlTag`<div style=${{ display: 'flex', gap: '8px', marginTop: '12px', alignItems: 'center', flexWrap: 'wrap' }}> <button class=${"btn btn-secondary"} style=${{ color: 'var(--status-red)' }} onClick=${handleRemove}> Remove </button> <button class=${"btn btn-secondary"} onClick=${() => setShowUpdatePath(v => !v)}> Update Path </button> ${showUpdatePath && (
                  htmlTag` <input type=${"text"} value=${newPath} onInput=${e => setNewPath(e.target.value)} placeholder=${"New absolute path…"} style=${{
                        fontFamily: 'var(--font-mono)', fontSize: '13px',
                        background: 'var(--bg-input)', border: '1px solid var(--border-default)',
                        borderRadius: 'var(--radius-sm)', padding: '5px 10px',
                        color: 'var(--text-primary)', width: '320px',
                      }} /> <button class=${"btn btn-secondary"} onClick=${handleSavePath} disabled=${saving}> ${saving ? 'Saving…' : 'Save'} </button> `
                )} </div>`
            )} </div> <button style=${{
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
            }} onClick=${() => {}} title=${"Scan Now (not yet wired)"}> Scan Now </button> </div>`
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
        htmlTag`<nav class=${"sub-tab-nav"} role=${"tablist"}> ${SUB_TABS.map(t => (
            htmlTag`<button key=${t.id} role=${"tab"} aria-selected=${active === t.id} class=${'sub-tab-btn' + (active === t.id ? ' active' : '')} onClick=${() => onChange(t.id)}> ${t.label} </button>`
          ))} </nav>`
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
        htmlTag`<div class=${"time-range-group"} role=${"group"} aria-label=${"Time range"}> ${TIME_RANGES.map(r => (
            htmlTag`<button key=${r.days} class=${'time-range-btn' + (selected === r.days ? ' active' : '')} onClick=${() => onChange(r.days)}> ${r.label} </button>`
          ))} </div>`
      );
    }

    function fillDateGaps(data, days) {
      const map = {};
      data.forEach(d => { map[d.date] = d; });
      const result = [];
      const today = new Date();
      const localDateKey = d => [
        d.getFullYear(),
        String(d.getMonth() + 1).padStart(2, '0'),
        String(d.getDate()).padStart(2, '0'),
      ].join('-');
      const limit = days >= 9999 ? (data.length > 0 ? null : 90) : days;
      if (limit === null) {
        // "All" mode: just return sorted data without gap filling beyond first date
        if (data.length === 0) return [];
        // Fill from earliest date to today
        const earliest = data[0].date;
        const start = new Date(earliest + 'T00:00:00');
        const end = new Date();
        for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
          const dateStr = localDateKey(d);
          result.push(map[dateStr] || { date: dateStr, commits: 0, insertions: 0, deletions: 0, files_changed: 0 });
        }
        return result;
      }
      for (let i = limit - 1; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        const dateStr = localDateKey(d);
        result.push(map[dateStr] || { date: dateStr, commits: 0, insertions: 0, deletions: 0, files_changed: 0 });
      }
      return result;
    }

    function ActivityChart({ data }) {

      if (!data || data.length === 0) {
        return (
          htmlTag`<div style=${{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '14px' }}> No activity data for this period </div>`
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
        const commits = payload[0]?.payload?.commits ?? 0;
        const rawDel = del ? Math.abs(del.value) : 0;
        const netVal = net ? net.value : 0;
        return (
          htmlTag`<div style=${{
            background: 'var(--bg-card)', border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-sm)', padding: '10px 14px',
            fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-secondary)',
            lineHeight: '1.7',
          }}> <div style=${{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: '4px' }}>${label}</div> <div style=${{ color: 'var(--status-green)' }}>+${ins ? ins.value : 0} insertions</div> <div style=${{ color: 'var(--status-red)' }}>-${rawDel} deletions</div> <div style=${{ color: 'var(--accent-blue)' }}>net ${netVal >= 0 ? '+' : ''}${netVal}</div> <div>${commits} commits</div> </div>`
        );
      }

      // Show a tick every 7 data points
      const tickInterval = Math.max(Math.floor(chartData.length / 10), 6);

      return (
        htmlTag`<div class="activity-chart"><${svgCharts.CartesianChart} kind=${"area"} data=${chartData} xKey=${"date"} height=${300} margin=${{top:10, right:40, bottom:30, left:60}} grid=${{horizontal:true, vertical:false}} xAxisLine=${true} stackOffset=${"sign"} tickEvery=${tickInterval + 1} yDomain=${chartData.every(d => d.insertions === 0 && d.deletions === 0) ? [0, 4] : undefined} yFormat=${v => String(Math.abs(v))} referenceY=${0} tooltip=${props => htmlTag`<${CustomTooltip} ...${props} />`} series=${[
          {key:'insertions', stack:true, color:'var(--status-green)', fillOpacity:0.2, strokeWidth:1.5},
          {key:'deletions', stack:true, color:'var(--status-red)', fillOpacity:0.2, strokeWidth:1.5},
          {key:'net', color:'var(--accent-blue)', fill:'none', strokeWidth:2},
        ]} /></div>`
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
        htmlTag`<div> <${TimeRangeSelector} selected=${selectedDays} onChange=${setSelectedDays} /> ${historyData === null
            ? htmlTag`<div style=${{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '14px' }}>Loading…</div>`
            : htmlTag`<${ActivityChart} data=${historyData} />`} </div>`
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
        return htmlTag`<div class=${"table-empty"}>Loading…</div>`;
      }

      return (
        htmlTag`<div> ${branch && (
            htmlTag`<div style=${{
              fontSize: '12px', fontFamily: 'var(--font-heading)', fontWeight: 600,
              color: 'var(--accent-blue)', marginBottom: '10px',
              textTransform: 'uppercase', letterSpacing: '0.5px',
              display: 'flex', alignItems: 'center', gap: '6px',
            }}> <span style=${{ color: 'var(--text-muted)' }}>Branch:</span> ${branch} <span style=${{
                fontFamily: 'var(--font-mono)', fontSize: '11px', fontWeight: 400,
                color: 'var(--text-muted)', textTransform: 'none',
              }}> (${total} ${total === 1 ? 'commit' : 'commits'}) </span> </div>`
          )} <div class=${"table-container"}> <div class=${"table-header"} style=${{ gridTemplateColumns: '120px 1fr 110px 70px' }}> <span>Date</span> <span>Message</span> <span>+/-</span> <span>Files</span> </div> ${commits.length === 0 ? (
              htmlTag`<div class=${"table-empty"}>No commits found</div>`
            ) : commits.map(c => (
              htmlTag`<div key=${c.hash} class=${"table-row"} style=${{ gridTemplateColumns: '120px 1fr 110px 70px' }}> <span style=${{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}> ${fmtDate(c.date)} </span> <span style=${{ fontFamily: 'var(--font-body)', fontSize: '14px', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}> ${c.message && c.message.length > 80 ? c.message.slice(0, 80) + '…' : (c.message || '')} </span> <span style=${{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}> <span style=${{ color: 'var(--status-green)' }}>+${c.insertions}</span> ${' '} <span style=${{ color: 'var(--status-red)' }}>-${c.deletions}</span> </span> <span style=${{ fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)' }}> ${c.files_changed} </span> </div>`
            ))} </div> <div style=${{ marginTop: '16px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '12px' }}> <button class=${"btn btn-secondary"} disabled=${page <= 1} onClick=${() => setPage(p => p - 1)}>Prev</button> <span style=${{ fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-secondary)' }}> Page ${page} of ${totalPages} </span> <button class=${"btn btn-secondary"} disabled=${page >= totalPages} onClick=${() => setPage(p => p + 1)}>Next</button> </div> </div>`
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
        return htmlTag`<div class=${"table-empty"}>Loading…</div>`;
      }

      const gridCols = '1fr 80px 110px 70px 120px 130px';

      return (
        htmlTag`<div class=${"table-container"}> <div class=${"table-header"} style=${{ gridTemplateColumns: gridCols }}> <span>Branch</span> <span>Commits</span> <span>+/−</span> <span>Files</span> <span>Last Commit</span> <span>Status</span> </div> ${branches.length === 0 ? (
            htmlTag`<div class=${"table-empty"}>No branches found</div>`
          ) : branches.map(b => {
            const isSelected = selectedBranch === b.name;
            return (
              htmlTag`<div key=${b.name} class=${"table-row"} style=${{
                  gridTemplateColumns: gridCols,
                  cursor: 'pointer',
                  borderLeft: isSelected ? '2px solid var(--accent-blue)' : '2px solid transparent',
                  background: isSelected ? 'var(--accent-blue-dim)' : undefined,
                }} onClick=${() => onSelectBranch(b.name)} title=${'View commits for ' + b.name}> <span style=${{
                  fontFamily: 'var(--font-mono)', fontSize: '14px',
                  color: isSelected ? 'var(--accent-blue)' : 'var(--text-primary)',
                  fontWeight: isSelected ? 600 : 400,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}> ${b.name} </span> <span style=${{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}> ${b.is_default ? '\u2014' : (b.commits_ahead || 0)} </span> <span style=${{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}> ${b.is_default ? (
                    htmlTag`<span style=${{ color: 'var(--text-muted)' }}>—</span>`
                  ) : (b.insertions || b.deletions) ? (
                    htmlTag` <span style=${{ color: 'var(--status-green)' }}>+${b.insertions || 0}</span> ${' '} <span style=${{ color: 'var(--status-red)' }}>−${b.deletions || 0}</span> `
                  ) : (
                    htmlTag`<span style=${{ color: 'var(--text-muted)' }}>0</span>`
                  )} </span> <span style=${{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}> ${b.is_default ? '\u2014' : (b.files_changed || 0)} </span> <span style=${{ fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-secondary)' }}> ${fmtDate(b.last_commit_date)} </span> <span> ${b.is_default ? (
                    htmlTag`<span style=${{ color: 'var(--accent-blue)', background: 'var(--accent-blue-dim)', fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500, padding: '2px 8px', borderRadius: '4px' }}> default </span>`
                  ) : isStale(b.last_commit_date) ? (
                    htmlTag`<span style=${{ color: 'var(--status-orange)', background: 'var(--status-orange-bg)', fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500, padding: '2px 8px', borderRadius: '4px' }}> stale (${staleDays(b.last_commit_date)}d) </span>`
                  ) : (
                    htmlTag`<span style=${{ fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-muted)' }}> active </span>`
                  )} </span> </div>`
            );
          })} </div>`
      );
    }

    function fullyChecked(pkg) {
      return ['checked', 'floating'].includes(pkg.outdated_state) && pkg.vuln_state === 'checked';
    }

    function summarizeDeps(groups, manifests = []) {
      const summary = { declarations: 0, manifests: manifests.length, ok: 0, outdated: 0, major: 0, vulnerable: 0, unchecked: 0, fullyChecked: 0 };
      for (const group of groups) for (const pkg of group.packages) {
        summary.declarations++;
        if (['ok', 'outdated', 'major', 'vulnerable'].includes(pkg.severity)) summary[pkg.severity]++;
        if (fullyChecked(pkg)) summary.fullyChecked++; else summary.unchecked++;
      }
      return summary;
    }

    function currentText(pkg) {
      if (pkg.current_version) return pkg.current_version;
      if (pkg.wanted_version && pkg.outdated_state === 'floating') return 'evaluated ' + pkg.wanted_version + ' (floating)';
      return 'unresolved';
    }

    function statusText(pkg) {
      const headline = ({ok: 'up to date', outdated: 'outdated', major: 'major update', vulnerable: pkg.advisory_id || 'vulnerable', unchecked: 'not checked'})[pkg.severity] || 'not checked';
      return headline + (pkg.severity !== 'unchecked' && !fullyChecked(pkg) ? ' — incomplete coverage' : '');
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

    function DepsTab({ repoId }) {
      const [managerGroups, setManagerGroups] = useState([]);
      const [repo, setRepo] = useState(null);
      const [appStatus, setAppStatus] = useState(null);
      const [loading, setLoading] = useState(true);
      const [scanning, setScanning] = useState(false);
      const [error, setError] = useState(null);

      async function fetchDeps(scan = false) {
        setError(null);
        if (scan) setScanning(true); else setLoading(true);
        try {
          const depsResponse = await fetch(scan ? '/api/repos/' + repoId + '/scan/deps' : '/api/repos/' + repoId + '/deps', scan ? { method: 'POST' } : undefined);
          if (!depsResponse.ok) throw new Error('Dependency request failed: ' + depsResponse.status);
          const groups = await depsResponse.json();
          // Fetch persisted metadata after the scan transaction has completed.
          const responses = await Promise.all([fetch('/api/repos/' + repoId), fetch('/api/status')]);
          if (responses.some(r => !r.ok)) throw new Error('Coverage metadata request failed');
          const [detail, status] = await Promise.all(responses.map(r => r.json()));
          setManagerGroups(Array.isArray(groups) ? groups : []);
          setRepo(detail);
          setAppStatus(status);
        } catch (e) {
          setError(e.message);
        } finally {
          setLoading(false);
          setScanning(false);
        }
      }
      useEffect(() => { fetchDeps(); }, [repoId]);

      const ws = repo?.working_state || {};
      const manifests = ws.dep_manifests || [];
      const missingTools = ws.missing_dep_tools || [];
      const summary = summarizeDeps(managerGroups, manifests);
      const packages = managerGroups.flatMap(group => group.packages.map(pkg => ({...pkg, _manager: group.manager, _label: group.label || group.manager})));
      const severityOrder = {vulnerable: 0, major: 1, outdated: 2};
      const issues = packages.filter(pkg => pkg.severity in severityOrder).sort((a, b) =>
        severityOrder[a.severity] - severityOrder[b.severity] || a.name.localeCompare(b.name));
      const unchecked = packages.filter(pkg => !fullyChecked(pkg));
      const incomplete = summary.unchecked > 0 || missingTools.length > 0 || manifests.some(m => m.error) || ws.dep_check_error;
      const newestScan = packages.map(p => p.checked_at).filter(Boolean).sort().at(-1) || null;

      function downloadBlob(content, filename, mimeType) {
        const url = URL.createObjectURL(new Blob([content], { type: mimeType }));
        const a = document.createElement('a');
        a.href = url; a.download = filename;
        document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      }
      function report() {
        return {format: 'git-fleet-dependency-report', format_version: 2, generated_at: new Date().toISOString(),
          git_fleet_version: appStatus?.version, repo: {id: repoId, name: repo?.name}, missing_tools: missingTools,
          summary, scope: appStatus?.dependency_scope, manifests, groups: managerGroups};
      }
      function handleExportJSON() {
        downloadBlob(JSON.stringify(report(), null, 2), 'deps-export.json', 'application/json');
      }
      function handleExportMD() {
        const data = report();
        const cell = value => String(value ?? '—').replace(/\\|/g, '\\\\|').replace(/[\\r\\n]+/g, ' ');
        const table = rows => '| Package | Declared | Version | Latest | Outdated check | Vulnerability check | Status | Source | Reasons |\\n' +
          '|---|---|---|---|---|---|---|---|---|\\n' + rows.map(p => '| ' + [p.name, p.declared_spec, currentText(p), p.latest_version,
            p.outdated_state, p.vuln_state, statusText(p), p.source_path, p.check_note].map(cell).join(' | ') + ' |\\n').join('');
        let md = '# Dependency Report\\n\\nRepository: ' + cell(data.repo.name) + ' (' + cell(repoId) + ')\\n\\n' +
          'Generated: ' + data.generated_at + '\\n\\nGit Fleet version: ' + data.git_fleet_version + '\\n\\nNewest declaration check: ' + (newestScan || 'No declaration check timestamp available') + '\\n\\n' +
          'Declarations: ' + summary.declarations + '; Manifests: ' + summary.manifests + '; Fully checked: ' + summary.fullyChecked + '; Not checked: ' + summary.unchecked + '\\n\\n' +
          'Vulnerable: ' + summary.vulnerable + '; Major: ' + summary.major + '; Outdated: ' + summary.outdated + '; Up to date: ' + summary.ok + '\\n\\n' +
          'Coverage: ' + (incomplete ? 'Incomplete' : 'Complete') + '\\n\\nMissing tools: ' + (missingTools.map(t => cell(t.tool) + ' — ' + cell(t.description)).join('; ') || 'None') + '\\n\\n' +
          '## Scope\\n\\n' + JSON.stringify(data.scope, null, 2) + '\\n\\n' +
          '## Attention Required\\n\\n' + table(issues) + '\\n## Not Checked\\n\\n' + table(unchecked) + '\\n## All Dependencies\\n\\n' + table(packages) +
          '\\n## Manifests Scanned\\n\\n| File | Kind | Declarations | Error |\\n|---|---|---|---|\\n' +
          manifests.map(m => '| ' + [m.path, m.kind, m.dependencies, m.error].map(cell).join(' | ') + ' |\\n').join('');
        downloadBlob(md, 'deps-export.md', 'text/markdown');
      }
      function dependencyTable(rows) {
        return htmlTag`<div class=${"table-container"} style=${{overflowX: 'auto'}}> <table class=${"data-table"} style=${{width: '100%', textAlign: 'left', fontSize: '13px'}}> <thead><tr>${['Package', 'Declared', 'Version', 'Latest', 'Status / Coverage', 'Source / Reasons'].map(h => htmlTag`<th key=${h} style=${{padding: '8px'}}>${h}</th>`)}</tr></thead> <tbody>${rows.map(pkg => htmlTag`<tr key=${JSON.stringify([pkg._manager, pkg.source_path, pkg.name])}> <td style=${{padding: '8px'}}>${pkg.name}</td><td>${pkg.declared_spec || '—'}</td><td>${currentText(pkg)}</td><td>${pkg.latest_version || '—'}</td> <td style=${{color: severityColor(pkg.severity)}}>${statusText(pkg)}<br /><small>outdated: ${pkg.outdated_state || 'unchecked'}; vulnerability: ${pkg.vuln_state || 'unchecked'}</small></td> <td>${pkg._label}<br />${pkg.check_note}</td> </tr>`)}</tbody> </table> </div>`;
      }
      if (loading) return htmlTag`<div class=${"table-empty"}>Loading…</div>`;
      return htmlTag`<div> <div style=${{display: 'flex', justifyContent: 'flex-end', gap: '8px', marginBottom: '12px'}}> <button class=${"btn btn-secondary"} onClick=${handleExportMD} disabled=${!repo || !appStatus}>Export MD</button> <button class=${"btn btn-secondary"} onClick=${handleExportJSON} disabled=${!repo || !appStatus}>Export JSON</button> <button class=${"btn btn-secondary"} onClick=${() => fetchDeps(true)} disabled=${scanning}>${scanning ? 'Checking…' : 'Check Now'}</button> </div> ${error && htmlTag`<div role=${"alert"}>${error}</div>`} <div data-testid=${"dep-coverage"} style=${{padding: '12px', marginBottom: '16px', color: incomplete ? 'var(--status-orange)' : 'var(--text-secondary)'}}> ${incomplete && htmlTag`<strong>Incomplete coverage — </strong>`}${summary.declarations} declarations; ${summary.manifests} manifests; ${summary.fullyChecked} fully checked; ${summary.unchecked} not checked. ${missingTools.map(t => htmlTag`<div key=${t.tool}>${t.tool} — ${t.description}</div>`)} </div> ${issues.length > 0 && htmlTag`<section><h3>Attention Required</h3>${dependencyTable(issues)}</section>`} ${unchecked.length > 0 && htmlTag`<section data-testid=${"dep-not-checked"}><h3>Not Checked</h3>${dependencyTable(unchecked)}</section>`} ${summary.declarations > 0 && issues.length === 0 && summary.fullyChecked === summary.declarations && !incomplete &&
          htmlTag`<div style=${{color: 'var(--status-green)'}}>No issues found — all dependencies are up to date.</div>`} <section data-testid=${"dep-all"}><h3>All Dependencies</h3>${managerGroups.map(group => htmlTag`<div key=${JSON.stringify([group.manager, group.source_path])} style=${{marginBottom: '16px'}}> <h4>${group.label || group.manager}</h4>${dependencyTable(packages.filter(pkg => pkg._manager === group.manager && pkg.source_path === group.source_path))} </div>`)}${!packages.length && htmlTag`<div>No dependencies detected</div>`}</section> <section><h3>Manifests Scanned</h3>${manifests.map(m => htmlTag`<div key=${m.path}>${m.path} — ${m.kind} — ${m.dependencies} declarations${m.error ? ' — ' + m.error : ''}</div>`)}</section> <div style=${{marginTop: '12px', color: 'var(--text-muted)'}}>Newest declaration check: ${newestScan ? timeAgo(newestScan) : 'No declaration check timestamp available'} · Git Fleet ${appStatus?.version}</div> </div>`;
    }

    function PlaceholderTab({ text }) {
      return (
        htmlTag`<div class=${"table-container"}> <div class=${"table-empty"}>${text} — coming in a later packet</div> </div>`
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
          htmlTag`<div style=${{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '14px' }}> Loading… </div>`
        );
      }

      return (
        htmlTag`<div class=${"detail-view"}> <${DetailHeader} repo=${repo} selectedBranch=${selectedBranch} onGoToBranches=${() => handleSubTabChange('branches')} /> <${SubTabNav} active=${activeSubTab} onChange=${handleSubTabChange} /> <div class=${"detail-content"}> ${activeSubTab === 'activity'  && htmlTag`<${ActivityTab} repoId=${repoId} />`} ${activeSubTab === 'deps'      && htmlTag`<${DepsTab} repoId=${repoId} />`} ${activeSubTab === 'branches'  && htmlTag`<${BranchesTab} repoId=${repoId} selectedBranch=${selectedBranch} onSelectBranch=${handleSelectBranch} />`} ${activeSubTab === 'commits'   && htmlTag`<${CommitsTab} repoId=${repoId} branch=${selectedBranch} />`} </div> </div>`
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
        return htmlTag`<div style=${{ padding: '16px', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}>Loading…</div>`;
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
        htmlTag`<div data-heatmap-root style=${{ position: 'relative', display: 'inline-block' }}>  <div style=${{ display: 'flex', marginLeft: '36px', marginBottom: '4px', position: 'relative', height: '16px' }}> ${monthLabels.map(({ col, label }) => (
              htmlTag`<span key=${col + '-' + label} style=${{
                  position: 'absolute',
                  left: `${col * step}px`,
                  fontFamily: 'var(--font-body)',
                  fontSize: '11px',
                  color: 'var(--text-muted)',
                  userSelect: 'none',
                }}>${label}</span>`
            ))} </div> <div style=${{ display: 'flex', alignItems: 'flex-start' }}>  <div style=${{ width: '30px', marginRight: '6px', flexShrink: 0 }}> ${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map((name, idx) => (
                htmlTag`<div key=${idx} style=${{ ...dayLabelStyle, visibility: (name === 'Mon' || name === 'Wed' || name === 'Fri') ? 'visible' : 'hidden' }}> ${name} </div>`
              ))} </div>  <div style=${{
                display: 'grid',
                gridTemplateColumns: `repeat(52, ${CELL}px)`,
                gridTemplateRows: `repeat(7, ${CELL}px)`,
                gap: `${GAP}px`,
              }}> ${cells.map((week, col) =>
                week.map((cellDate, row) => {
                  const iso = cellDate.toISOString().slice(0, 10);
                  const count = countMap.get(iso) || 0;
                  const isFuture = cellDate > today;
                  const cellCount = isFuture ? 0 : count;
                  const bgColor = heatmapColor(cellCount, internalMax);
                  const isHovered = tooltip && tooltip.iso === iso;
                  return (
                    htmlTag`<div key=${iso} style=${{
                        width: `${CELL}px`,
                        height: `${CELL}px`,
                        backgroundColor: bgColor,
                        borderRadius: '2px',
                        cursor: 'default',
                        outline: isHovered ? '2px solid var(--accent-blue)' : 'none',
                        outlineOffset: '-1px',
                      }} onMouseEnter=${(e) => {
                        const rect = e.currentTarget.getBoundingClientRect();
                        const containerRect = e.currentTarget.closest('[data-heatmap-root]')?.getBoundingClientRect() || rect;
                        setTooltip({ iso, count: cellCount, x: rect.left - containerRect.left, y: rect.top - containerRect.top });
                      }} onMouseLeave=${() => setTooltip(null)} />`
                  );
                })
              )} </div> </div>  ${tooltip && (
            htmlTag`<div style=${{
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
              }}> ${new Date(tooltip.iso + 'T12:00:00').toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}: ${tooltip.count} commits </div>`
          )} </div>`
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
      const processedSeries = useMemo(() => {
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

      // Build merged chart data array for the allocation chart
      const chartData = useMemo(() => {
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

      if (loading) {
        return (
          htmlTag`<div style=${{ padding: '16px', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}> Loading… </div>`
        );
      }

      return (
        htmlTag`<div> <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}> <h3 style=${{ fontFamily: 'var(--font-heading)', fontSize: '14px', color: 'var(--text-primary)', margin: 0 }}> Time Allocation </h3> <${TimeRangeSelector} selected=${selectedDays} onChange=${setSelectedDays} /> </div> ${chartData.length === 0 ? (
            htmlTag`<div style=${{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}> No commit data in this range. </div>`
          ) : (
            htmlTag`<div class="allocation-chart"><${svgCharts.CartesianChart} kind=${"area"} data=${chartData} xKey=${"date"} height=${260} margin=${{top:10, right:40, bottom:30, left:36}} grid=${{horizontal:true, vertical:true}} tickEvery=${Math.max(1, Math.ceil(chartData.length / 10))} yDomain=${[0, Math.max(1, ...chartData.map(row => processedSeries.reduce((sum, s) => sum + (row[s.name] || 0), 0)))]} series=${processedSeries.map((s, i) => ({
              key:s.name, stack:true, color:s.name === 'Other' ? 'var(--text-muted)' : ALLOC_COLORS[i % ALLOC_COLORS.length],
              fillOpacity:hidden.has(s.name) ? 0 : 0.75, strokeOpacity:hidden.has(s.name) ? 0 : 1,
            }))} tooltip=${({label, payload}) => htmlTag`<div style=${{background:'var(--bg-card)', border:'1px solid var(--border-default)', borderRadius:'var(--radius-sm)', padding:'8px 12px', fontSize:'12px', fontFamily:'var(--font-body)'}}><div>${label}</div>${payload.filter(p => !hidden.has(p.dataKey)).map(p => htmlTag`<div style=${{color:p.color}}>${p.name}: ${p.value}</div>`)}</div>`} /></div>`
          )}  <div style=${{ display: 'flex', flexWrap: 'wrap', gap: '12px 20px', marginTop: '12px' }}> ${processedSeries.map((s, i) => {
              const color = s.name === 'Other' ? 'var(--text-muted)' : ALLOC_COLORS[i % ALLOC_COLORS.length];
              const isHidden = hidden.has(s.name);
              return (
                htmlTag`<button key=${s.name} onClick=${() => toggleSeries(s.name)} style=${{
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
                  }}> <span style=${{
                    display: 'inline-block',
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    backgroundColor: color,
                    flexShrink: 0,
                  }} /> ${s.name} </button>`
              );
            })} </div> </div>`
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
          htmlTag`<div style=${{ padding: '16px', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}> Loading… </div>`
        );
      }

      if (packages.length === 0) {
        return (
          htmlTag`<div style=${{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}> No shared dependencies found across repos. </div>`
        );
      }

      return (
        htmlTag`<div> <h3 style=${{ fontFamily: 'var(--font-heading)', fontSize: '14px', color: 'var(--text-primary)', margin: '0 0 12px 0' }}> Dependency Overlap </h3> <table class=${"data-table"} style=${{ width: '100%', borderCollapse: 'collapse' }}> <thead> <tr> <th style=${{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Package</th> <th style=${{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Manager</th> <th style=${{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Used In</th> <th style=${{ textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>Version Spread</th> </tr> </thead> <tbody> ${packages.map(pkg => {
                const key = pkg.name + ':' + pkg.manager;
                const isExpanded = expanded.has(key);
                return (
                  htmlTag`<${preact.Fragment} key=${key}> <tr style=${{ borderTop: '1px solid var(--border-default)' }}> <td style=${{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: '14px', color: 'var(--text-primary)' }}> ${pkg.name} </td> <td style=${{ padding: '8px 12px', fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase' }}> ${pkg.manager} </td> <td style=${{ padding: '8px 12px' }}> <span onClick=${() => toggleExpanded(key)} style=${{ fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--accent-blue)', cursor: 'pointer' }}> ${isExpanded ? '▾' : '▸'} ${pkg.count} uses in ${pkg.repo_count} repos </span> </td> <td style=${{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}> ${pkg.version_spread} </td> </tr> ${isExpanded && (
                      htmlTag`<tr style=${{ borderTop: '1px solid var(--border-default)' }}> <td colSpan=${4} style=${{ paddingLeft: '24px', paddingBottom: '8px', paddingTop: '4px' }}> ${pkg.repos.map(repo => (
                            htmlTag`<div key=${JSON.stringify([repo.repo_id, repo.source_path])} style=${{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.6' }}> ${repo.name} — ${repo.source_path} — ${repo.version !== null ? repo.version : '(unknown)'} </div>`
                          ))} </td> </tr>`
                    )} <//>`
                );
              })} </tbody> </table> </div>`
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
      const reposWithCoverage = repos.filter(r => r.dep_summary?.total > 0 || r.dep_check_error || r.missing_dep_tools?.length);
      const totalDeps = reposWithDeps.reduce((sum, r) => sum + (r.dep_summary?.total || 0), 0);
      const totalOutdated = reposWithDeps.reduce((sum, r) => sum + (r.dep_summary?.outdated || 0), 0);
      const totalVuln = reposWithDeps.reduce((sum, r) => sum + (r.dep_summary?.vulnerable || 0), 0);
      const totalUnchecked = reposWithDeps.reduce((sum, r) => sum + (r.dep_summary?.unchecked || 0), 0);

      return (
        htmlTag`<div style=${{ display: 'flex', flexDirection: 'column', gap: '32px' }}>  <div style=${{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px' }}> <${KpiCard} label=${"Total Deps"} value=${loading ? '...' : totalDeps} tooltip=${"Total dependencies detected across all repos"} /> <${KpiCard} label=${"Outdated"} value=${loading ? '...' : totalOutdated} tooltip=${"Dependencies with newer versions available (minor or major)"} /> <${KpiCard} label=${"Vulnerable"} value=${loading ? '...' : totalVuln} tooltip=${"Dependencies with known security vulnerabilities"} /> <${KpiCard} label=${"Not Checked"} value=${loading ? '...' : totalUnchecked} tooltip=${"Declarations with incomplete check coverage, including findings"} /> <${KpiCard} label=${"Repos w/ Deps"} value=${loading ? '...' : reposWithDeps.length} tooltip=${"Repos where at least one dependency manifest was detected"} /> </div>  <section> <h2 style=${sectionHeaderStyle}>Per-Repo Health</h2> ${loading ? (
              htmlTag`<div style=${{ color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}>Loading...</div>`
            ) : reposWithCoverage.length === 0 ? (
              htmlTag`<div style=${{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '13px' }}> No dependencies detected. Run a Full Scan to discover dependencies in your repos. </div>`
            ) : (
              htmlTag`<div class=${"table-container"}> <div class=${"table-header"} style=${{ gridTemplateColumns: '1fr repeat(4, 100px)' }}> <span>Repo</span> <span>Total</span> <span>Outdated</span> <span>Vulnerable</span> <span>Not Checked</span> </div> ${reposWithCoverage.map(r => (
                  htmlTag`<div key=${r.id} class=${"table-row"} style=${{ gridTemplateColumns: '1fr repeat(4, 100px)', cursor: 'pointer' }} onClick=${() => { window.location.hash = '#/repo/' + r.id + '/deps'; }}> <span style=${{ fontFamily: 'var(--font-mono)', fontSize: '14px', color: 'var(--text-primary)' }}> <span>${r.name}</span> <span style=${{display: 'block', fontSize: '11px'}}><${DepBadge} dep=${r.dep_summary} missingTools=${r.missing_dep_tools} analysisError=${r.dep_check_error} /></span> </span> <span style=${{ fontSize: '13px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}> ${r.dep_summary?.total || 0} </span> <span style=${{ fontSize: '13px', fontFamily: 'var(--font-mono)', color: r.dep_summary?.outdated > 0 ? 'var(--status-yellow)' : 'var(--text-muted)' }}> ${r.dep_summary?.outdated || 0} </span> <span style=${{ fontSize: '13px', fontFamily: 'var(--font-mono)', color: r.dep_summary?.vulnerable > 0 ? 'var(--status-red)' : 'var(--text-muted)' }}> ${r.dep_summary?.vulnerable || 0} </span> <span style=${{color: 'var(--status-orange)'}}>${r.dep_summary?.unchecked || 0}</span> </div>`
                ))} </div>`
            )} </section>  <section> <h2 style=${sectionHeaderStyle}>Dependency Overlap</h2> <${DepOverlap} /> </section> </div>`
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
        htmlTag`<div style=${{ display: 'flex', flexDirection: 'column', gap: '32px' }}> <section> <h2 style=${sectionHeaderStyle}>Activity Heatmap</h2> <${Heatmap} /> </section> <section> <h2 style=${sectionHeaderStyle}>Time Allocation</h2> <${TimeAllocation} /> </section> <section> <h2 style=${sectionHeaderStyle}>Dependency Overlap</h2> <${DepOverlap} /> </section> </div>`
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
        content = htmlTag`<${ProjectDetail} key=${repoId} repoId=${repoId} initialSubTab=${route.subTab} />`;
      } else if (tab === 'analytics') {
        content = htmlTag`<${AnalyticsTab} />`;
      } else if (tab === 'deps') {
        content = htmlTag`<${FleetDepsTab} />`;
      } else {
        content = htmlTag`<${FleetOverview} refetchKey=${refetchKey} />`;
      }

      return htmlTag`<div style=${areaStyle}>${content}</div>`;
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
        htmlTag`<div> <${Header} onFullScan=${handleFullScan} onScanDir=${handleScanDir} scanActive=${scanState.active} /> <${NavTabs} activeTab=${navTab} /> <${ScanProgressBar} scanState=${scanState} /> <${ScanToast} scanState=${scanState} /> <${DirectoryBrowser} open=${browseOpen} onClose=${() => setBrowseOpen(false)} onSelect=${handleSelectDir} /> ${scanResult && (
            htmlTag`<div style=${{
              position: 'fixed', bottom: '24px', right: '24px', zIndex: 300,
              padding: '12px 20px', borderRadius: 'var(--radius-sm)',
              background: scanResult.ok ? 'var(--status-green-bg)' : 'var(--status-red-bg)',
              color: scanResult.ok ? 'var(--status-green)' : 'var(--status-red)',
              fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500,
              border: scanResult.ok ? '1px solid var(--status-green)' : '1px solid var(--status-red)',
              boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
            }}> ${scanResult.message} </div>`
          )} <main style=${{ paddingTop: '100px' }}> <${ToolStatusBanner} /> <${ContentArea} route=${route} refetchKey=${refetchKey} /> </main> </div>`
      );
    }

    // ── Mount ────────────────────────────────────────────────────────────────
    preact.render(htmlTag`<${ErrorBoundary}> <${App} /> <//>`, document.getElementById('root'));
  </script>
</body>
</html>
"""

# frontend-vendor:begin preact hooks htm kit svg-charts font:jetbrains-mono font:geist
FRONTEND_VENDOR_HTML = r"""<!--
The MIT License (MIT)

Copyright (c) 2015-present Jason Miller

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

-->
<!--

                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright 2018 Google Inc.

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
-->
<!--
Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono) JetBrainsMono-Italic[wght].ttf: Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)

This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.

-->
<!--
Copyright 2024 The Geist Project Authors (https://github.com/vercel/geist-font) Geist-Italic[wght].ttf: Copyright 2024 The Geist Project Authors (https://github.com/vercel/geist-font)

This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.

-->
<script>
!function(n,t){"object"==typeof exports&&"undefined"!=typeof module?t(exports):"function"==typeof define&&define.amd?define(["exports"],t):t((n||self).preact={})}(this,function(n){var t,i,e,r,f,o,u,c,s,a,h,l,p,y,v,d,w="http://www.w3.org/2000/svg",_="http://www.w3.org/1999/xhtml",g=null,m=void 0,b={},k=[],x=/acit|ex(?:s|g|n|p|$)|rph|grid|ows|mnc|ntw|ine[ch]|zoo|^ord|itera/i,M=Array.isArray;function S(n,t){for(var i in t)n[i]=t[i];return n}function T(n){n&&n.parentNode&&n.parentNode.removeChild(n)}function $(n,i,e){var r,f,o,u={};for(o in i)"key"==o?r=i[o]:"ref"==o?f=i[o]:u[o]=i[o];if(arguments.length>2&&(u.children=arguments.length>3?t.call(arguments,2):e),"function"==typeof n&&n.defaultProps!=g)for(o in n.defaultProps)u[o]===m&&(u[o]=n.defaultProps[o]);return C(n,u,r,f,g)}function C(n,t,r,f,o){var u={type:n,props:t,key:r,ref:f,__k:g,__:g,__b:0,__e:g,__c:g,constructor:m,__v:o==g?++e:o,__i:-1,__u:0};return o==g&&i.vnode!=g&&i.vnode(u),u}function I(n){return n.children}function P(n,t){this.props=n,this.context=t}function j(n,t){if(t==g)return n.__?j(n.__,n.__i+1):g;for(var i;t<n.__k.length;t++)if((i=n.__k[t])!=g&&i.__e!=g)return i.__e;return"function"==typeof n.type?j(n):g}function A(n){if(n.__P&&n.__d){var t=n.__v,e=t.__e,r=[],f=[],o=S({},t);o.__v=t.__v+1,i.vnode&&i.vnode(o),E(n.__P,o,t,n.__n,n.__P.namespaceURI,32&t.__u?[e]:g,r,e==g?j(t):e,!!(32&t.__u),f),o.__v=t.__v,o.__.__k[o.__i]=o,J(r,o,f),t.__e=t.__=null,o.__e!=e&&H(o)}}function H(n){if((n=n.__)!=g&&n.__c!=g)return n.__e=n.__c.base=g,n.__k.some(function(t){if(t!=g&&t.__e!=g)return n.__e=n.__c.base=t.__e}),H(n)}function L(n){(!n.__d&&(n.__d=!0)&&f.push(n)&&!F.__r++||o!=i.debounceRendering)&&((o=i.debounceRendering)||u)(F)}function F(){try{for(var n,t=1;f.length;)f.length>t&&f.sort(c),n=f.shift(),t=f.length,A(n)}finally{f.length=F.__r=0}}function O(n,t,i,e,r,f,o,u,c,s,a){var h,l,p,y,v,d,w=e&&e.__k||k,_=t.length;for(c=z(i,t,w,c,_),h=0;h<_;h++)(p=i.__k[h])!=g&&(l=-1!=p.__i&&w[p.__i]||b,p.__i=h,d=E(n,p,l,r,f,o,u,c,s,a),y=p.__e,p.ref&&l.ref!=p.ref&&(l.ref&&R(l.ref,g,p),a.push(p.ref,p.__c||y,p)),v==g&&y!=g&&(v=y),4&p.__u?(c=N(p,c,n),l.__e&&(l.__e=g)):"function"==typeof p.type&&d!==m?c=d:y&&(c=y.nextSibling),p.__u&=-7);return i.__e=v,c}function z(n,t,i,e,r){var f,o,u,c,s,a=i.length,h=a,l=0;for(n.__k=new Array(r),f=0;f<r;f++)(o=t[f])!=g&&"boolean"!=typeof o&&"function"!=typeof o?("string"==typeof o||"number"==typeof o||"bigint"==typeof o||o.constructor==String?o=n.__k[f]=C(g,o,g,g,g):M(o)?o=n.__k[f]=C(I,{children:o},g,g,g):o.constructor===m&&o.__b>0?o=n.__k[f]=C(o.type,o.props,o.key,o.ref?o.ref:g,o.__v):n.__k[f]=o,c=f+l,o.__=n,o.__b=n.__b+1,s=o.__i=V(o,i,c,h),u=g,-1!=s&&(h--,(u=i[s])&&(u.__u|=2)),u==g||u.__v==g?(-1==s&&(r>a?l--:r<a&&l++),"function"!=typeof o.type&&(o.__u|=4)):s!=c&&(s==c-1?l--:s==c+1?l++:(s>c?l--:l++,o.__u|=4))):n.__k[f]=g;if(h)for(f=0;f<a;f++)(u=i[f])!=g&&0==(2&u.__u)&&(u.__e==e&&(e=j(u)),U(u,u));return e}function N(n,t,i){var e,r;if("function"==typeof n.type){for(e=n.__k,r=0;e&&r<e.length;r++)e[r]&&(e[r].__=n,t=N(e[r],t,i));return t}n.__e!=t&&(t&&n.type&&!t.parentNode&&(t=j(n)),t=i.insertBefore(n.__e,t||g));do{t=t&&t.nextSibling}while(t!=g&&8==t.nodeType);return t}function V(n,t,i,e){var r,f,o,u=n.key,c=n.type,s=t[i],a=s!=g&&0==(2&s.__u);if(s===g&&null==u||a&&u==s.key&&c==s.type)return i;if(e>(a?1:0))for(r=i-1,f=i+1;r>=0||f<t.length;)if((s=t[o=r>=0?r--:f++])!=g&&0==(2&s.__u)&&u==s.key&&c==s.type)return o;return-1}function q(n,t,i){"-"==t[0]?n.setProperty(t,i==g?"":i):n[t]=i==g?"":"number"!=typeof i||x.test(t)?i:i+"px"}function B(n,t,i,e,r){var f,o;n:if("style"==t)if("string"==typeof i)n.style.cssText=i;else{if("string"==typeof e&&(n.style.cssText=e=""),e)for(t in e)i&&t in i||q(n.style,t,"");if(i)for(t in i)e&&i[t]==e[t]||q(n.style,t,i[t])}else if("o"==t[0]&&"n"==t[1])f=t!=(t=t.replace(l,"$1")),o=t.toLowerCase(),t=o in n||"onFocusOut"==t||"onFocusIn"==t?o.slice(2):t.slice(2),n.l||(n.l={}),n.l[t+f]=i,i?e?i[h]=e[h]:(i[h]=p,n.addEventListener(t,f?v:y,f)):n.removeEventListener(t,f?v:y,f);else{if(r==w)t=t.replace(/xlink(H|:h)/,"h").replace(/sName$/,"s");else if("width"!=t&&"height"!=t&&"href"!=t&&"list"!=t&&"form"!=t&&"tabIndex"!=t&&"download"!=t&&"rowSpan"!=t&&"colSpan"!=t&&"role"!=t&&"popover"!=t&&t in n)try{n[t]=i==g?"":i;break n}catch(n){}"function"==typeof i||(i==g||!1===i&&"-"!=t[4]?n.removeAttribute(t):n.setAttribute(t,"popover"==t&&1==i?"":i))}}function D(n){return function(t){if(this.l){var e=this.l[t.type+n];if(t[a]==g)t[a]=p++;else if(t[a]<e[h])return;return e(i.event?i.event(t):t)}}}function E(n,t,e,r,f,o,u,c,s,a){var h,l,p,y,v,d,w,_,b,x,$,C,A,H,L,F,z=t.type;if(t.constructor!==m)return g;128&e.__u&&(s=!!(32&e.__u),o=[c=t.__e=e.__e]),(h=i.__b)&&h(t);n:if("function"==typeof z){l=u.length;try{if(b=t.props,x=z.prototype&&z.prototype.render,$=(h=z.contextType)&&r[h.__c],C=h?$?$.props.value:h.__:r,e.__c?_=(p=t.__c=e.__c).__=p.__E:(x?t.__c=p=new z(b,C):(t.__c=p=new P(b,C),p.constructor=z,p.render=W),$&&$.sub(p),p.state||(p.state={}),p.__n=r,y=p.__d=!0,p.__h=[],p._sb=[]),x&&p.__s==g&&(p.__s=p.state),x&&z.getDerivedStateFromProps!=g&&(p.__s==p.state&&(p.__s=S({},p.__s)),S(p.__s,z.getDerivedStateFromProps(b,p.__s))),v=p.props,d=p.state,p.__v=t,y)x&&z.getDerivedStateFromProps==g&&p.componentWillMount!=g&&p.componentWillMount(),x&&p.componentDidMount!=g&&p.__h.push(p.componentDidMount);else{if(x&&z.getDerivedStateFromProps==g&&b!==v&&p.componentWillReceiveProps!=g&&p.componentWillReceiveProps(b,C),t.__v==e.__v||!p.__e&&p.shouldComponentUpdate!=g&&!1===p.shouldComponentUpdate(b,p.__s,C)){t.__v!=e.__v&&(p.props=b,p.state=p.__s,p.__d=!1),t.__e=e.__e,t.__k=e.__k,t.__k.some(function(n){n&&(n.__=t)}),k.push.apply(p.__h,p._sb),p._sb=[],p.__h.length&&u.push(p),c=j(e);break n}p.componentWillUpdate!=g&&p.componentWillUpdate(b,p.__s,C),x&&p.componentDidUpdate!=g&&p.__h.push(function(){p.componentDidUpdate(v,d,w)})}if(p.context=C,p.props=b,p.__P=n,p.__e=!1,A=i.__r,H=0,x)p.state=p.__s,p.__d=!1,A&&A(t),h=p.render(p.props,p.state,p.context),k.push.apply(p.__h,p._sb),p._sb=[];else do{p.__d=!1,A&&A(t),h=p.render(p.props,p.state,p.context),p.state=p.__s}while(p.__d&&++H<25);p.state=p.__s,p.getChildContext!=g&&(r=S(S({},r),p.getChildContext())),x&&!y&&p.getSnapshotBeforeUpdate!=g&&(w=p.getSnapshotBeforeUpdate(v,d)),L=h!=g&&h.type===I&&h.key==g?K(h.props.children):h,c=O(n,M(L)?L:[L],t,e,r,f,o,u,c,s,a),p.base=t.__e,t.__u&=-161,p.__h.length&&u.push(p),_&&(p.__E=p.__=g)}catch(n){if(u.length=l,t.__v=g,s||o!=g){if(n.then){for(t.__u|=s?160:128;c&&8==c.nodeType&&c.nextSibling;)c=c.nextSibling;o!=g&&(o[o.indexOf(c)]=g),t.__e=c}else if(o!=g)for(F=o.length;F--;)T(o[F])}else t.__e=e.__e;t.__k==g&&(t.__k=e.__k||[]),n.then||G(t),i.__e(n,t,e)}}else o==g&&t.__v==e.__v?(t.__k=e.__k,t.__e=e.__e):c=t.__e=Q(e.__e,t,e,r,f,o,u,s,a);return(h=i.diffed)&&h(t),128&t.__u?void 0:c}function G(n){n&&(n.__c&&(n.__c.__e=!0),n.__k&&n.__k.some(G))}function J(n,t,e){for(var r=0;r<e.length;r++)R(e[r],e[++r],e[++r]);i.__c&&i.__c(t,n),n.some(function(t){try{n=t.__h,t.__h=[],n.some(function(n){n.call(t)})}catch(n){i.__e(n,t.__v)}})}function K(n){return"object"!=typeof n||n==g||n.__b>0?n:M(n)?n.map(K):n.constructor!==m?null:S({},n)}function Q(n,e,r,f,o,u,c,s,a){var h,l,p,y,v,d,k,x=r.props||b,S=e.props,$=e.type;if("svg"==$?o=w:"math"==$?o="http://www.w3.org/1998/Math/MathML":o||(o=_),u!=g)for(h=0;h<u.length;h++)if((v=u[h])&&"setAttribute"in v==!!$&&($?v.localName==$:3==v.nodeType)){n=v,u[h]=g;break}if(n==g){if($==g)return document.createTextNode(S);n=document.createElementNS(o,$,S.is&&S),s&&(i.__m&&i.__m(e,u),s=!1),u=g}if($==g)x===S||s&&n.data==S||(n.data=S);else{if(u="textarea"==$&&S.defaultValue!=g?g:u&&t.call(n.childNodes),!s&&u!=g)for(x={},h=0;h<n.attributes.length;h++)x[(v=n.attributes[h]).name]=v.value;for(h in x)v=x[h],"dangerouslySetInnerHTML"==h?p=v:"children"==h||h in S||"value"==h&&"defaultValue"in S||"checked"==h&&"defaultChecked"in S||B(n,h,g,v,o);for(h in S)v=S[h],"children"==h?y=v:"dangerouslySetInnerHTML"==h?l=v:"value"==h?d=v:"checked"==h?k=v:s&&"function"!=typeof v||x[h]===v||B(n,h,v,x[h],o);if(l)s||p&&(l.__html==p.__html||l.__html==n.innerHTML)||(n.innerHTML=l.__html),e.__k=[];else if(p&&(n.innerHTML=""),O("template"==e.type?n.content:n,M(y)?y:[y],e,r,f,"foreignObject"==$?_:o,u,c,u?u[0]:r.__k&&j(r,0),s,a),u!=g)for(h=u.length;h--;)T(u[h]);s&&"textarea"!=$||(h="value","progress"==$&&d==g?n.removeAttribute("value"):d!=m&&(d!==n[h]||"progress"==$&&!d||"option"==$&&d!=x[h])&&B(n,h,d,x[h],o),h="checked",k!=m&&k!=n[h]&&B(n,h,k,x[h],o))}return n}function R(n,t,e){try{if("function"==typeof n){var r="function"==typeof n.__u;r&&n.__u(),r&&t==g||(n.__u=n(t))}else n.current=t}catch(n){i.__e(n,e)}}function U(n,t,e){var r,f;if(i.unmount&&i.unmount(n),(r=n.ref)&&(r.current&&r.current!=n.__e||R(r,g,t)),(r=n.__c)!=g){if(r.componentWillUnmount)try{r.componentWillUnmount()}catch(n){i.__e(n,t)}r.base=r.__P=r.__n=g}if(r=n.__k)for(f=0;f<r.length;f++)r[f]&&U(r[f],t,e||"function"!=typeof n.type);e||T(n.__e),n.__c=n.__=n.__e=m}function W(n,t,i){return this.constructor(n,i)}function X(n,e,r){var f,o,u,c;e==document&&(e=document.documentElement),i.__&&i.__(n,e),o=(f="function"==typeof r)?g:r&&r.__k||e.__k,u=[],c=[],E(e,n=(!f&&r||e).__k=$(I,g,[n]),o||b,b,e.namespaceURI,!f&&r?[r]:o?g:e.firstChild?t.call(e.childNodes):g,u,!f&&r?r:o?o.__e:e.firstChild,f,c),J(u,n,c),n.props.children=g}t=k.slice,i={__e:function(n,t,i,e){for(var r,f,o;t=t.__;)if((r=t.__c)&&!r.__)try{if((f=r.constructor)&&f.getDerivedStateFromError!=g&&(r.setState(f.getDerivedStateFromError(n)),o=r.__d),r.componentDidCatch!=g&&(r.componentDidCatch(n,e||{}),o=r.__d),o)return r.__E=r}catch(t){n=t}throw n}},e=0,r=function(n){return n!=g&&n.constructor===m},P.prototype.setState=function(n,t){var i;i=this.__s!=g&&this.__s!=this.state?this.__s:this.__s=S({},this.state),"function"==typeof n&&(n=n(S({},i),this.props)),n&&S(i,n),n!=g&&this.__v&&(t&&this._sb.push(t),L(this))},P.prototype.forceUpdate=function(n){this.__v&&(this.__e=!0,n&&this.__h.push(n),L(this))},P.prototype.render=I,f=[],u="function"==typeof Promise?Promise.prototype.then.bind(Promise.resolve()):setTimeout,c=function(n,t){return n.__v.__b-t.__v.__b},F.__r=0,s=Math.random().toString(8),a="__d"+s,h="__a"+s,l=/(PointerCapture)$|Capture$/i,p=0,y=D(!1),v=D(!0),d=0,n.Component=P,n.Fragment=I,n.cloneElement=function(n,i,e){var r,f,o,u,c=S({},n.props);for(o in n.type&&n.type.defaultProps&&(u=n.type.defaultProps),i)"key"==o?r=i[o]:"ref"==o?f=i[o]:c[o]=i[o]===m&&u!=m?u[o]:i[o];return arguments.length>2&&(c.children=arguments.length>3?t.call(arguments,2):e),C(n.type,c,r||n.key,f||n.ref,g)},n.createContext=function(n){function t(n){var i,e;return this.getChildContext||(i=new Set,(e={})[t.__c]=this,this.getChildContext=function(){return e},this.componentWillUnmount=function(){i=g},this.shouldComponentUpdate=function(n){this.props.value!=n.value&&i.forEach(function(n){n.__e=!0,L(n)})},this.sub=function(n){i.add(n);var t=n.componentWillUnmount;n.componentWillUnmount=function(){i&&i.delete(n),t&&t.call(n)}}),n.children}return t.__c="__cC"+d++,t.__=n,t.Provider=t.__l=(t.Consumer=function(n,t){return n.children(t)}).contextType=t,t},n.createElement=$,n.createRef=function(){return{current:g}},n.h=$,n.hydrate=function n(t,i){X(t,i,n)},n.isValidElement=r,n.options=i,n.render=X,n.toChildArray=function n(t,i){return i=i||[],t==g||"boolean"==typeof t||(M(t)?t.some(function(t){n(t,i)}):i.push(t)),i}});
//# sourceMappingURL=preact.umd.js.map

</script>
<script>
!function(n,t){"object"==typeof exports&&"undefined"!=typeof module?t(exports,require("preact")):"function"==typeof define&&define.amd?define(["exports","preact"],t):t((n||self).preactHooks={},n.preact)}(this,function(n,t){var u,i,r,o,f=0,c=[],e=t.options,a=e.__b,v=e.__r,l=e.diffed,d=e.__c,p=e.unmount,s=e.__;function y(n,t){e.__h&&e.__h(i,n,f||t),f=0;var u=i.__H||(i.__H={__:[],__h:[]});return n>=u.__.length&&u.__.push({}),u.__[n]}function h(n){return f=1,m(j,n)}function m(n,t,r){var o=y(u++,2);if(o.t=n,!o.__c&&(o.__=[r?r(t):j(void 0,t),function(n){var t=o.__N?o.__N[0]:o.__[0],u=o.t(t,n);t!==u&&(o.__N=[u,o.__[1]],o.__c.setState({}))}],o.__c=i,!i.__f)){var f=function(n,t,u){if(!o.__c.__H)return!0;var i=!1,r=o.__c.props!==n;if(o.__c.__H.__.some(function(n){if(n.__N){i=!0;var t=n.__[0];n.__=n.__N,n.__N=void 0,t!==n.__[0]&&(r=!0)}}),c){var f=c.call(this,n,t,u);return i?f||r:f}return!i||r};i.__f=!0;var c=i.shouldComponentUpdate,e=i.componentWillUpdate;i.componentWillUpdate=function(n,t,u){if(this.__e){var i=c;c=void 0,f(n,t,u),c=i}e&&e.call(this,n,t,u)},i.shouldComponentUpdate=f}return o.__N||o.__}function T(n,t){var r=y(u++,4);!e.__s&&g(r.__H,t)&&(r.__=n,r.u=t,i.__h.push(r))}function _(n,t){var i=y(u++,7);return g(i.__H,t)&&(i.__=n(),i.__H=t,i.__h=n),i.__}function b(){for(var n;n=c.shift();){var t=n.__H;if(n.__P&&t)try{t.__h.some(A),t.__h.some(F),t.__h=[]}catch(u){t.__h=[],e.__e(u,n.__v)}}}e.__b=function(n){i=null,a&&a(n)},e.__=function(n,t){n&&t.__k&&t.__k.__m&&(n.__m=t.__k.__m),s&&s(n,t)},e.__r=function(n){v&&v(n),u=0;var t=(i=n.__c).__H;t&&(r===i?(t.__h=[],i.__h=[],t.__.some(function(n){n.__N&&(n.__=n.__N),n.u=n.__N=void 0})):(t.__h.some(A),t.__h.some(F),t.__h=[],u=0)),r=i},e.diffed=function(n){l&&l(n);var t=n.__c;t&&t.__H&&(t.__H.__h.length&&(1!==c.push(t)&&o===e.requestAnimationFrame||((o=e.requestAnimationFrame)||x)(b)),t.__H.__.some(function(n){n.u&&(n.__H=n.u,n.u=void 0)})),r=i=null},e.__c=function(n,t){t.some(function(n){try{n.__h.some(A),n.__h=n.__h.filter(function(n){return!n.__||F(n)})}catch(u){t.some(function(n){n.__h&&(n.__h=[])}),t=[],e.__e(u,n.__v)}}),d&&d(n,t)},e.unmount=function(n){p&&p(n);var t,u=n.__c;u&&u.__H&&(u.__H.__.some(function(n){try{A(n)}catch(n){t=n}}),u.__H=void 0,t&&e.__e(t,u.__v))};var q="function"==typeof requestAnimationFrame;function x(n){var t,u=function(){clearTimeout(i),q&&cancelAnimationFrame(t),setTimeout(n)},i=setTimeout(u,35);q&&(t=requestAnimationFrame(u))}function A(n){var t=i,u=n.__c;"function"==typeof u&&(n.__c=void 0,u()),i=t}function F(n){var t=i;n.__c=n.__(),i=t}function g(n,t){return!n||n.length!==t.length||t.some(function(t,u){return t!==n[u]})}function j(n,t){return"function"==typeof t?t(n):t}n.useCallback=function(n,t){return f=8,_(function(){return n},t)},n.useContext=function(n){var t=i.context[n.__c],r=y(u++,9);return r.c=n,t?(null==r.__&&(r.__=!0,t.sub(i)),t.props.value):n.__},n.useDebugValue=function(n,t){e.useDebugValue&&e.useDebugValue(t?t(n):n)},n.useEffect=function(n,t){var r=y(u++,3);!e.__s&&g(r.__H,t)&&(r.__=n,r.u=t,i.__H.__h.push(r))},n.useErrorBoundary=function(n){var t=y(u++,10),r=h();return t.__=n,i.componentDidCatch||(i.componentDidCatch=function(n,u){t.__&&t.__(n,u),r[1](n)}),[r[0],function(){r[1](void 0)}]},n.useId=function(){var n=y(u++,11);if(!n.__){for(var t=i.__v;null!==t&&!t.__m&&null!==t.__;)t=t.__;var r=t.__m||(t.__m=[0,0]);n.__="P"+r[0]+"-"+r[1]++}return n.__},n.useImperativeHandle=function(n,t,u){f=6,T(function(){if("function"==typeof n){var u=n(t());return function(){n(null),u&&"function"==typeof u&&u()}}if(n)return n.current=t(),function(){return n.current=null}},null==u?u:u.concat(n))},n.useLayoutEffect=T,n.useMemo=_,n.useReducer=m,n.useRef=function(n){return f=5,_(function(){return{current:n}},[])},n.useState=h});
//# sourceMappingURL=hooks.umd.js.map

</script>
<script>
!function(n,e){"object"==typeof exports&&"undefined"!=typeof module?module.exports=e():"function"==typeof define&&define.amd?define(e):n.htm=e()}(this,function(){var n=function(e,t,u,s){var r;t[0]=0;for(var p=1;p<t.length;p++){var h=t[p++],o=t[p]?(t[0]|=h?1:2,u[t[p++]]):t[++p];3===h?s[0]=o:4===h?s[1]=Object.assign(s[1]||{},o):5===h?(s[1]=s[1]||{})[t[++p]]=o:6===h?s[1][t[++p]]+=o+"":h?(r=e.apply(o,n(e,o,u,["",null])),s.push(r),o[0]?t[0]|=2:(t[p-2]=0,t[p]=r)):s.push(o)}return s},e=new Map;return function(t){var u=e.get(this);return u||(u=new Map,e.set(this,u)),(u=n(this,u.get(t)||(u.set(t,u=function(n){for(var e,t,u=1,s="",r="",p=[0],h=function(n){1===u&&(n||(s=s.replace(/^\s*\n\s*|\s*\n\s*$/g,"")))?p.push(0,n,s):3===u&&(n||s)?(p.push(3,n,s),u=2):2===u&&"..."===s&&n?p.push(4,n,0):2===u&&s&&!n?p.push(5,0,!0,s):u>=5&&((s||!n&&5===u)&&(p.push(u,0,s,t),u=6),n&&(p.push(u,n,0,t),u=6)),s=""},o=0;o<n.length;o++){o&&(1===u&&h(),h(o));for(var f=0;f<n[o].length;f++)e=n[o][f],1===u?"<"===e?(h(),p=[p],u=3):s+=e:4===u?"--"===s&&">"===e?(u=1,s=""):s=e+s[0]:r?e===r?r="":s+=e:'"'===e||"'"===e?r=e:">"===e?(h(),u=1):u&&("="===e?(u=5,t=s,s=""):"/"===e&&(u<5||">"===n[o][f+1])?(h(),3===u&&(p=p[0]),u=p,(p=p[0]).push(2,0,u),u=0):" "===e||"\t"===e||"\n"===e||"\r"===e?(h(),u=2):s+=e),3===u&&"!--"===s&&(u=4,p=p[0])}return h(),p}(t)),u),arguments,[])).length>1?u:u[0]}});

</script>
<script>
(function () {
  const { h, render, Component } = window.preact;
  const { useMemo, useLayoutEffect } = window.preactHooks;
  function Icon({ name, size = 16, strokeWidth = 2, ...rest }) {
    const nodes = Object.hasOwn(window.lucideIcons || {}, name) ? window.lucideIcons[name] : null;
    if (!nodes) { console.error(`Unknown Lucide icon: ${name}`); return null; }
    return h('svg', { xmlns: 'http://www.w3.org/2000/svg', width: size, height: size,
      viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
      'stroke-width': strokeWidth, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', ...rest },
      nodes.map(([tag, attrs]) => h(tag, attrs)));
  }
  function Portal({ children }) {
    const host = useMemo(() => document.createElement('div'), []);
    useLayoutEffect(() => {
      document.body.appendChild(host);
      return () => { render(null, host); host.remove(); };
    }, [host]);
    useLayoutEffect(() => { render(children, host); }, [children, host]);
    return null;
  }
  function shallowEqual(a, b) {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every(key => Object.is(a[key], b[key]));
  }
  function memo(Inner, areEqual = shallowEqual) {
    return class extends Component {
      shouldComponentUpdate(next) { return !areEqual(this.props, next); }
      render(props) { return h(Inner, props); }
    };
  }
  function focusOnMount(element) { if (element) element.focus(); }
  window.frontendKit = { Icon, Portal, memo, focusOnMount };
})();

</script>
<script>
(function () {
  'use strict';
  const {h} = window.preact;
  const {useState, useRef, useEffect, useLayoutEffect} = window.preactHooks;
  const number = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  function linearScale(domain, range) {
    const [a,b]=domain.map(number), [c,d]=range.map(number);
    return value => a===b ? (c+d)/2 : c+(number(value)-a)*(d-c)/(b-a);
  }
  function niceTicks(min,max,count=5) {
    min=number(min); max=number(max); count=Math.max(1,number(count));
    if(min>max) [min,max]=[max,min];
    if(min===max) {const pad=Math.abs(min)*0.1||1;min-=pad;max+=pad;}
    const raw=(max-min)/count, magnitude=10**Math.floor(Math.log10(raw));
    const factor=raw/magnitude, step=(factor<=1?1:factor<=2?2:factor<=5?5:10)*magnitude;
    const start=Math.floor(min/step), end=Math.ceil(max/step), result=[];
    for(let i=start;i<=end && result.length<1000;i++) result.push(Number((i*step).toPrecision(14)));
    return result;
  }
  function stack(rows,keys,offset='none') {
    const result=keys.map(()=>[]);
    rows.forEach(row=>{let pos=0,neg=0,total=0;keys.forEach((key,i)=>{
      const value=number(row[key]);let start;
      if(offset==='sign') {start=value<0?neg:pos;if(value<0)neg+=value;else pos+=value;}
      else {start=total;total+=value;}
      result[i].push([start,start+value]);
    });});return result;
  }
  const xy=p=>Array.isArray(p)?[number(p[0]),number(p[1])]:[number(p.x),number(p.y)];
  function monotonePath(points) {
    const p=points.map(xy);if(!p.length)return '';
    let path=`M${p[0][0]},${p[0][1]}`;if(p.length===1)return path;
    const slopes=p.slice(1).map((v,i)=>v[0]===p[i][0]?0:(v[1]-p[i][1])/(v[0]-p[i][0]));
    const tangents=p.map((_,i)=>i===0?slopes[0]:i===p.length-1?slopes.at(-1):slopes[i-1]*slopes[i]<=0?0:2/(1/slopes[i-1]+1/slopes[i]));
    for(let i=0;i<p.length-1;i++) {const dx=(p[i+1][0]-p[i][0])/3;path+=`C${p[i][0]+dx},${p[i][1]+dx*tangents[i]} ${p[i+1][0]-dx},${p[i+1][1]-dx*tangents[i+1]} ${p[i+1][0]},${p[i+1][1]}`;}
    return path;
  }
  function areaPath(top,bottom) {if(!top.length||!bottom.length)return '';return monotonePath(top)+monotonePath([...bottom].reverse()).replace(/^M/,'L')+'Z';}
  function arcPath(cx,cy,inner,outer,start,end) {
    cx=number(cx);cy=number(cy);inner=Math.max(0,number(inner));outer=Math.max(0,number(outer));start=number(start);end=number(end);
    const delta=Math.max(-2*Math.PI,Math.min(2*Math.PI,end-start)), sweep=delta>=0?1:0;
    const point=(r,a)=>`${cx+r*Math.cos(a)},${cy+r*Math.sin(a)}`;
    const arcs=(r,a,d,s)=>{const n=Math.abs(d)>=2*Math.PI-1e-9?2:1;let out='';for(let i=1;i<=n;i++)out+=`A${r},${r} 0 ${Math.abs(d/n)>Math.PI?1:0} ${s} ${point(r,a+d*i/n)}`;return out;};
    return `M${point(outer,start)}${arcs(outer,start,delta,sweep)}L${point(inner,start+delta)}${arcs(inner,start+delta,-delta,1-sweep)}Z`;
  }
  function useWidth(width) {
    const ref=useRef(null), [measured,setMeasured]=useState(number(width)||400);
    useEffect(()=>{if(width || !ref.current)return;const node=ref.current;const update=()=>setMeasured(node.getBoundingClientRect().width||400);update();if(typeof ResizeObserver==='undefined')return;const observer=new ResizeObserver(update);observer.observe(node);return()=>observer.disconnect();},[width]);
    return [ref,number(width)||measured];
  }
  const selectable=(item,onSelect)=>onSelect?{role:'button',tabindex:0,onClick:()=>onSelect(item),onKeyDown:event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelect(item);}}}:{};
  const style={position:'relative',width:'100%'};
  function tooltipPosition(point,size,chart,viewport) {
    const left=Math.max(chart.left,viewport.left)-chart.left;
    const top=Math.max(chart.top,viewport.top)-chart.top;
    const right=Math.max(left,Math.min(chart.right,viewport.right)-chart.left);
    const bottom=Math.max(top,Math.min(chart.bottom,viewport.bottom)-chart.top);
    const place=(value,extent,min,max)=>{
      const forward=value+10, flipped=value-10-extent;
      const preferred=forward+extent<=max?forward:flipped;
      return Math.max(min,Math.min(preferred,Math.max(min,max-extent)));
    };
    return {left:place(point.x,size.width,left,right),top:place(point.y,size.height,top,bottom)};
  }
  function Tooltip({children,position,onDismiss}) {
    const ref=useRef(null);
    useLayoutEffect(()=>{
      const node=ref.current, chart=node?.parentElement;
      if(!node||!chart) return;
      const update=()=>{
        const bounds=chart.getBoundingClientRect();
        const viewport={left:0,top:0,right:window.innerWidth,bottom:window.innerHeight};
        const availableWidth=Math.max(0,Math.min(bounds.right,viewport.right)-Math.max(bounds.left,viewport.left));
        const availableHeight=Math.max(0,Math.min(bounds.bottom,viewport.bottom)-Math.max(bounds.top,viewport.top));
        node.style.maxWidth=`${availableWidth}px`;
        node.style.maxHeight=`${availableHeight}px`;
        const size=node.getBoundingClientRect();
        const constrained=node.scrollWidth>node.clientWidth || node.scrollHeight>node.clientHeight;
        node.style.pointerEvents=constrained?'auto':'none';
        if(constrained) {
          node.setAttribute('tabindex','0');
          node.setAttribute('role','region');
          node.setAttribute('aria-label','Chart tooltip');
        } else {
          node.removeAttribute('tabindex');
          node.removeAttribute('role');
          node.removeAttribute('aria-label');
        }
        const placed=tooltipPosition(position,size,bounds,viewport);
        node.style.left=`${placed.left}px`;
        node.style.top=`${placed.top}px`;
        node.style.visibility='visible';
      };
      update();
      const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(update);
      observer?.observe(chart);
      window.addEventListener('resize',update);
      window.addEventListener('scroll',update,true);
      return ()=>{observer?.disconnect();window.removeEventListener('resize',update);window.removeEventListener('scroll',update,true);};
    },[position.x,position.y,children]);
    return h('div',{ref,class:'svgc-tooltip',
      onMouseMove:event=>event.stopPropagation(),
      onFocusOut:event=>{if(!event.currentTarget.contains(event.relatedTarget)) onDismiss();}
    },children);
  }
  function tooltipNode(tooltip,payload,position,onDismiss) {
    if(!tooltip||!payload) return null;
    return h(Tooltip,{position,onDismiss},typeof tooltip==='function'?tooltip(payload):tooltip);
  }
  function spacedTicks(ticks,scale,minSpacing=20) {
    if(ticks.length<2) return ticks;
    const first=ticks[0], last=ticks.at(-1);
    if(Math.abs(scale(first)-scale(last))<minSpacing) return [first];
    const shown=[first];
    for(const tick of ticks.slice(1,-1)) {
      if(Math.abs(scale(tick)-scale(shown.at(-1)))>=minSpacing &&
         Math.abs(scale(tick)-scale(last))>=minSpacing) shown.push(tick);
    }
    return [...shown,last];
  }
  const leaveChart=(event,setHover)=>{
    const tooltip=event.currentTarget.querySelector('.svgc-tooltip');
    if(!tooltip?.contains(window.document?.activeElement)) setHover(null);
  };
  function itemHover(event,item) {
    const bounds=event.currentTarget?.ownerSVGElement?.parentElement?.getBoundingClientRect();
    return {item,x:bounds?event.clientX-bounds.left:event.offsetX,
      y:bounds?event.clientY-bounds.top:event.offsetY};
  }
  function CartesianChart({
    kind='area', data=[], xKey, series=[], stackOffset='none', height=300,
    width, margin={}, yFormat=String, xFormat=String, tickEvery, yDomain,
    referenceX, referenceY, referenceOpacity=1, grid=true, xAxisLine=false,
    yAxisLine=false, plotClass='', tooltip,
    compact=false
  }) {
    const [ref,w]=useWidth(width), [hover,setHover]=useState(null);
    const m={top:10,right:10,bottom:compact?0:25,left:compact?0:55,...margin};
    const left=m.left, right=Math.max(left,w-m.right), top=m.top;
    const bottom=Math.max(top,height-m.bottom), pw=right-left;
    const stacked=stack(data,series.filter(s=>s.stack).map(s=>s.key),stackOffset);
    let si=0;
    const bands=series.map(s=>s.stack?stacked[si++]:data.map(row=>[0,number(row[s.key])]));
    let slotCount=0, stackSlot;
    const slots=series.map(s=>{
      if(!s.stack) return slotCount++;
      if(stackSlot===undefined) stackSlot=slotCount++;
      return stackSlot;
    });
    const values=bands.flat(2).concat([0]);
    let lo=Math.min(...values), hi=Math.max(...values);
    const explicitDomain=Array.isArray(yDomain) && yDomain.length>=2 &&
      Number.isFinite(yDomain[0]) && Number.isFinite(yDomain[1]);
    if(Array.isArray(yDomain)) {
      if(Number.isFinite(yDomain[0])) lo=yDomain[0];
      if(Number.isFinite(yDomain[1])) hi=yDomain[1];
    }
    let ticks=niceTicks(lo,hi,4);
    if(explicitDomain) {
      const min=Math.min(lo,hi), max=Math.max(lo,hi);
      ticks=[min,...ticks.filter(t=>t>min && t<max),...(min===max?[]:[max])];
    } else if(!yDomain) {
      lo=ticks[0]; hi=ticks.at(-1);
    }
    const y=linearScale([lo,hi],[bottom,top]);
    const renderedTicks=spacedTicks(ticks,y);
    const x=i=>data.length<=1?(left+right)/2:kind==='bar'
      ?left+(i+.5)*pw/data.length:left+i*pw/(data.length-1);
    const marks=series.map((s,j)=>{
      const b=bands[j], color=s.color||'currentColor';
      if(kind==='bar') {
        const groupWidth=data.length?pw/data.length*.8:0;
        const barWidth=slotCount?groupWidth/slotCount:0;
        return b.map((pair,i)=>h('rect',{
          class:'svgc-bar',x:x(i)-groupWidth/2+slots[j]*barWidth,
          y:Math.min(y(pair[0]),y(pair[1])),width:barWidth,
          height:Math.abs(y(pair[1])-y(pair[0])),fill:s.fill||color,
          'fill-opacity':s.fillOpacity??1,stroke:color,
          'stroke-opacity':s.strokeOpacity??1,'stroke-width':s.strokeWidth??2,
          'stroke-dasharray':s.strokeDasharray
        }));
      }
      const upper=b.map((v,i)=>[x(i),y(v[1])]);
      const lower=b.map((v,i)=>[x(i),y(v[0])]);
      return h('g',null,
        kind==='area'&&s.fill!=='none'&&h('path',{
          class:'svgc-area',d:areaPath(upper,lower),fill:s.fill||color,
          'fill-opacity':s.fillOpacity??.3
        }),
        h('path',{
          class:'svgc-curve',d:monotonePath(upper),fill:'none',stroke:color,
          'stroke-opacity':s.strokeOpacity??1,'stroke-width':s.strokeWidth??2,
          'stroke-dasharray':s.strokeDasharray
        }),
        upper.length===1&&h('circle',{class:'svgc-point',cx:upper[0][0],cy:upper[0][1],
          r:3,fill:color,opacity:s.strokeOpacity??1})
      );
    });
    const move=e=>{
      if(!data.length) return;
      const rect=e.currentTarget.getBoundingClientRect(), local=e.clientX-rect.left;
      const fraction=pw?Math.max(0,Math.min(1,(local-left)/pw)):0;
      const index=data.length===1?0:kind==='bar'
        ?Math.min(data.length-1,Math.floor(fraction*data.length))
        :Math.round(fraction*(data.length-1));
      setHover({index,x:local,y:e.clientY-rect.top});
    };
    const row=hover&&data[hover.index];
    const payload=row&&{
      active:true,label:row[xKey],row,index:hover.index,
      payload:series.map(s=>({dataKey:s.key,name:s.label||s.key,
        value:row[s.key],color:s.color,payload:row}))
    };
    const refIndex=data.findIndex(row=>row[xKey]===referenceX);
    const options=typeof grid==='object' && grid!==null?grid:{};
    const horizontal=typeof grid==='object'?options.horizontal!==false:!!grid;
    const vertical=typeof grid==='object'&&options.vertical===true;
    const gridStroke=options.stroke??'var(--border-default, #334155)';
    const gridDash=options.strokeDasharray??'3 3';
    const xLabels=data.map((row,i)=>({i,label:xFormat(row[xKey])}));
    const maxLabelWidth=Math.max(0,...xLabels.map(({label})=>Array.from(String(label??'')).length*9+12));
    const categoryGap=data.length>1?pw/(kind==='bar'?data.length:data.length-1):pw;
    const interval=Number.isFinite(tickEvery)?Math.max(1,Math.floor(tickEvery)):
      Math.max(1,categoryGap>0?Math.ceil(maxLabelWidth/categoryGap):data.length);
    const shownX=xLabels.filter(({i})=>i%interval===0);
    return h('div',{ref,class:'svgc-responsive',style:{...style,height,width:width||'100%'}},
      h('div',{class:'svgc-wrapper',style:{...style,height},
        onMouseMove:move,onMouseLeave:event=>leaveChart(event,setHover)},
        h('svg',{width:w,height,viewBox:`0 0 ${w} ${height}`},
          h('rect',{class:plotClass,x:left,y:top,width:pw,height:bottom-top,fill:'transparent'}),
          !compact&&renderedTicks.map(t=>h('g',null,
            horizontal&&h('line',{class:'svgc-grid-horizontal',x1:left,x2:right,
              y1:y(t),y2:y(t),stroke:gridStroke,'stroke-dasharray':gridDash}),
            h('text',{x:left-6,y:y(t),fill:'var(--text-muted, #94a3b8)',
              'text-anchor':'end','font-size':11},yFormat(t))
          )),
          !compact&&vertical&&shownX.map(({i})=>h('line',{
            class:'svgc-grid-vertical',x1:x(i),x2:x(i),y1:top,y2:bottom,
            stroke:gridStroke,'stroke-dasharray':gridDash
          })),
          !compact&&shownX.map(({label,i})=>h('text',{
            x:x(i),y:height-4,fill:'var(--text-muted, #94a3b8)',
            'text-anchor':'middle','font-size':11
          },label)),
          !compact&&xAxisLine&&h('line',{
            class:'svgc-x-axis-line',x1:left,x2:right,y1:bottom,y2:bottom,
            stroke:typeof xAxisLine==='string'?xAxisLine:'var(--border-default, #334155)'
          }),
          !compact&&yAxisLine&&h('line',{
            class:'svgc-y-axis-line',x1:left,x2:left,y1:top,y2:bottom,
            stroke:typeof yAxisLine==='string'?yAxisLine:'var(--border-default, #334155)'
          }),
          marks,
          refIndex>=0&&h('line',{class:'svgc-reference-line',x:referenceX,
            x1:x(refIndex),x2:x(refIndex),y1:top,y2:bottom,
            stroke:'#94a3b8','stroke-opacity':referenceOpacity,'stroke-dasharray':'3 3'}),
          referenceY!=null&&h('line',{class:'svgc-reference-line',x:referenceY,
            x1:left,x2:right,y1:y(referenceY),y2:y(referenceY),
            stroke:'var(--border-default, #94a3b8)','stroke-opacity':referenceOpacity})
        ),
        tooltipNode(tooltip,payload,hover||{},()=>setHover(null))
      )
    );
  }
  function DonutChart({items=[],height=250,innerRadius=50,outerRadius=85,tooltip,onSelect,
    startAngle=-Math.PI/2,clockwise=true,stroke,strokeWidth}) {
    const [ref,w]=useWidth(),[hover,setHover]=useState(null);
    const total=items.reduce((sum,item)=>sum+Math.max(0,number(item.value)),0);
    let angle=number(startAngle);
    const sectors=items.map(item=>{
      const start=angle;
      angle+=total?(clockwise?1:-1)*Math.max(0,number(item.value))/total*2*Math.PI:0;
      return h('path',{class:'svgc-sector',d:arcPath(w/2,height/2,innerRadius,outerRadius,start,angle),
        fill:item.color,stroke,'stroke-width':strokeWidth,...selectable(item,onSelect),
        onMouseMove:e=>setHover(itemHover(e,item))},h('title',null,item.label));
    });
    return h('div',{ref,class:'svgc-responsive',style:{...style,height}},
      h('div',{class:'svgc-wrapper',style:{...style,height},onMouseLeave:event=>leaveChart(event,setHover)},
        h('svg',{width:w,height},sectors),
        tooltipNode(tooltip,hover&&{active:true,label:hover.item.label,payload:[{dataKey:'value',name:hover.item.label,value:hover.item.value,color:hover.item.color,payload:hover.item}]},hover||{},()=>setHover(null))));
  }
  function HBarChart({items=[],height=250,valueFormat=String,labelWidth=130,labelMaxChars=Infinity,onSelect,tooltip}) {
    const [ref,w]=useWidth(),[hover,setHover]=useState(null);
    const max=Math.max(0,...items.map(i=>number(i.value)));
    const plotHeight=Math.max(0,height-24), rowHeight=plotHeight/Math.max(1,items.length);
    const plotWidth=Math.max(0,w-labelWidth-8);
    const ticks=max?niceTicks(0,max,4):[0], axisMax=ticks.at(-1);
    const bars=items.map((item,i)=>{
      const label=String(item.label??'');
      const short=label.length>labelMaxChars?label.slice(0,Math.max(0,labelMaxChars-1))+'…':label;
      return h('g',null,
        h('text',{x:labelWidth-6,y:(i+.5)*rowHeight,'text-anchor':'end',
          'dominant-baseline':'middle',fill:'var(--text-muted, #94a3b8)','font-size':10},h('title',null,label),short),
        h('rect',{class:'svgc-bar',x:labelWidth,y:i*rowHeight+rowHeight*.15,
          width:axisMax?plotWidth*Math.max(0,number(item.value))/axisMax:0,height:rowHeight*.7,rx:4,
          fill:item.color,'aria-label':item.ariaLabel||`${label}: ${valueFormat(item.value)}`,
          ...selectable(item,onSelect),onMouseMove:e=>setHover(itemHover(e,item))})
      );
    });
    return h('div',{ref,class:'svgc-responsive',style:{...style,height}},
      h('div',{class:'svgc-wrapper',style:{...style,height},onMouseLeave:event=>leaveChart(event,setHover)},
        h('svg',{width:w,height},bars,
          h('line',{class:'svgc-hbar-axis',x1:labelWidth,x2:labelWidth+plotWidth,y1:plotHeight,y2:plotHeight,stroke:'var(--border-default, #475569)'}),
          ticks.map((t,i)=>h('text',{class:'svgc-hbar-tick',x:labelWidth+(axisMax?t/axisMax*plotWidth:0),y:height-4,
            'text-anchor':i===0?'start':i===ticks.length-1?'end':'middle',
            fill:'var(--text-muted, #94a3b8)','font-size':11},valueFormat(t)))
        ),
        tooltipNode(tooltip,hover&&{active:true,label:hover.item.label,payload:[{dataKey:'value',name:hover.item.label,value:hover.item.value,color:hover.item.color,payload:hover.item}]},hover||{},()=>setHover(null))));
  }
  function Legend({series=[],hidden=new Set(),onToggle,kind='area'}) {
    return h('div',{class:'svgc-legend'},series.map(s=>{
      const color=s.color||'currentColor';
      const symbol=kind==='bar'
        ?h('rect',{x:1,y:1,width:14,height:8,fill:s.fill||color,stroke:color,'stroke-dasharray':s.strokeDasharray})
        :[h('line',{x1:1,y1:5,x2:15,y2:5,stroke:color,'stroke-width':2,'stroke-dasharray':s.strokeDasharray}),
          h('circle',{cx:8,cy:5,r:3,fill:color})];
      return h('button',{type:'button',class:'svgc-legend-item',
        'aria-pressed':!hidden.has(s.key),onClick:()=>onToggle?.(s.key),
        style:{color:s.color,opacity:hidden.has(s.key)?.45:1}},
        h('svg',{'aria-hidden':'true',width:16,height:10,viewBox:'0 0 16 10'},symbol),s.label||s.key);
    }));
  }
  window.svgCharts={geometry:{linearScale,niceTicks,stack,monotonePath,areaPath,arcPath,tooltipPosition},CartesianChart,DonutChart,HBarChart,Legend};
})();

</script>
<style>
/* SVG charts: keep overlays and controls usable in either theme. */
.svgc-responsive, .svgc-wrapper { min-width: 0; }
.svgc-tooltip { position: absolute; z-index: 2; width: max-content; box-sizing: border-box; overflow: auto; pointer-events: none; visibility: hidden; }
.svgc-legend { display: flex; flex-wrap: wrap; justify-content: center; gap: .75rem; }
.svgc-legend-item { display: inline-flex; align-items: center; gap: .3em; background: transparent; border: 0; cursor: pointer; font: inherit; }
.svgc-bar[role="button"], .svgc-sector[role="button"] { cursor: pointer; }

</style>
<style>@font-face{font-family:"JetBrains Mono";font-style:normal;font-weight:100 800;src:url(data:font/woff2;base64,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) format('woff2');}</style>
<style>@font-face{font-family:"Geist";font-style:normal;font-weight:100 900;src:url(data:font/woff2;base64,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) format('woff2');}</style>"""
# frontend-vendor:end
HTML_TEMPLATE = HTML_TEMPLATE.replace("<!-- frontend-vendor -->", FRONTEND_VENDOR_HTML)


# ── FastAPI application ───────────────────────────────────────────────────────

app = FastAPI(title="Git Fleet")


@app.get("/", response_class=HTMLResponse)
async def get_ui():
    """Serve the SPA shell."""
    return HTML_TEMPLATE


@app.get("/api/status")
async def get_status():
    """Return tool availability and app version for the frontend banner."""
    return {"tools": TOOLS, "version": VERSION, "dependency_scope": dependency_report_scope()}


def dependency_report_scope() -> dict:
    """Describe the implemented declaration scan; reuse discovery's runtime limits."""
    return {
        "python": "Declaration evaluation, not installed-environment inspection or full dependency resolution. "
                  "Markers, requires-python and inter-package compatibility are not evaluated. "
                  "Undeclared transitive Python dependencies are not audited. Exact declared or unique adjacent-lock versions are evaluated; "
                  "supported PEP 440 constraints select the highest allowed non-yanked release using SpecifierSet.filter prerelease rules. "
                  "The selection is compared with registry latest even beyond a declaration cap. Unsupported Poetry constraints without concrete versions and ambiguous lock versions remain unchecked. "
                  "Floating selections are evaluated versions, not installed versions.",
        "direct_references": "Direct VCS/URL references are not compared with PyPI or audited; "
                             "remote metadata and VCS commit resolution are excluded.",
        "discovery": {
            "max_depth": _DEP_WALK_MAX_DEPTH,
            "skip_directories": sorted(_DEP_WALK_SKIP),
            "hidden_directories": "Skipped",
            "pep723": "Python .py/.pyw and suffixless shebang candidates; metadata only in the leading comment/blank-line prelude. "
                      "PEP 723 reference grammar; unclosed blocks ignored; duplicate script blocks, malformed TOML and invalid dependencies reported as inventory errors.",
        },
        "groups": "Python manifest kinds coexist. Requirements includes retain physical source paths (including external includes). "
                  "PEP 621 optional dependencies and string dependency-group entries are included; include-group tables and Poetry groups are not expanded. "
                  "Adjacent uv.lock supplies unique registry versions only, not declarations. "
                  "Node dependencies/devDependencies, Cargo dependencies/dev-dependencies, Composer require/require-dev (excluding platform entries), Go requirements and conventional Bundler gem declarations are included.",
    }


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
        "last_commit_date, checked_at, dep_check_error, missing_dep_tools, dep_manifests "
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
            "missing_dep_tools": json.loads(ws_row[11] or "[]"),
            "dep_manifests": json.loads(ws_row[12] or "[]"),
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
               severity, advisory_id, checked_at, source_path,
               declared_spec, outdated_state, vuln_state, check_note
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
        (mgr, name, cur_ver, wanted_ver, latest_ver, severity, advisory_id,
         checked_at, source_path, declared_spec, outdated_state, vuln_state, check_note) = row
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
                "declared_spec": declared_spec,
                "outdated_state": outdated_state,
                "vuln_state": vuln_state,
                "check_note": check_note,
                "checked_at": checked_at,
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
    """Return repeated declarations, including multiple manifests in one repo."""
    cursor = await db.execute(
        "SELECT d.name, d.manager, d.repo_id, r.name as repo_name, d.current_version, d.source_path "
        "FROM dependencies d "
        "JOIN repositories r ON r.id = d.repo_id "
        "ORDER BY d.name, d.manager, r.name, d.source_path"
    )
    rows = await cursor.fetchall()

    # Group by (pkg_name, manager) in Python
    from itertools import groupby

    packages = []
    for (pkg_name, manager), group in groupby(rows, key=lambda r: (r[0], r[1])):
        row_list = list(group)
        if len(row_list) < 2:
            continue
        versions = {r[4] for r in row_list if r[4] is not None}
        versions_sorted = sorted(versions, key=_version_sort_key)
        spread = f"{versions_sorted[0]} - {versions_sorted[-1]}" if versions_sorted else ""
        packages.append({
            "name": pkg_name,
            "manager": manager,
            "repos": [
                {"repo_id": r[2], "name": r[3], "version": r[4], "source_path": r[5]}
                for r in row_list
            ],
            "version_spread": spread,
            "count": len(row_list),
            "repo_count": len({r[2] for r in row_list}),
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
            f"SELECT repo_id, scan_error, dep_check_error, missing_dep_tools "
            f"FROM working_state WHERE repo_id IN ({placeholders})",
            ids,
        )
        ws_map = {}
        for row in await ws_cursor.fetchall():
            ws_map[row[0]] = (row[1], bool(row[2]), json.loads(row[3] or "[]"))
        for repo in results:
            scan_err, dep_err, missing_tools = ws_map.get(repo["id"], (None, False, []))
            repo["scan_error"] = scan_err
            repo["dep_check_error"] = dep_err
            repo["missing_dep_tools"] = missing_tools

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
            "SUM(CASE WHEN severity = 'vulnerable' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN outdated_state IN ('checked', 'floating') AND vuln_state = 'checked' THEN 0 ELSE 1 END) "
            "FROM dependencies WHERE repo_id = ?",
            (repo["id"],),
        )
        total_deps, outdated_count, vuln_count, unchecked_count = await cursor.fetchone()
        if total_deps and total_deps > 0:
            repo["dep_summary"] = {
                "total": total_deps,
                "outdated": (outdated_count or 0),
                "vulnerable": (vuln_count or 0),
                "unchecked": (unchecked_count or 0),
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
        "COALESCE(SUM(CASE WHEN severity IN ('outdated', 'major') THEN 1 ELSE 0 END), 0), "
        "COALESCE(SUM(CASE WHEN outdated_state IN ('checked', 'floating') AND vuln_state = 'checked' THEN 0 ELSE 1 END), 0) "
        "FROM dependencies"
    )
    vuln_total, outdated_total, unchecked_total = await cursor.fetchone()

    kpis = {
        "total_repos": len(results),
        "repos_with_changes": sum(1 for r in results if r.get("has_uncommitted")),
        "commits_this_week": commits_this_week,
        "commits_this_month": commits_this_month,
        "net_lines_this_week": net_lines_this_week,
        "stale_branches": sum(r.get("stale_branch_count", 0) for r in results),
        "vulnerable_deps": vuln_total,
        "outdated_deps": outdated_total,
        "unchecked_deps": unchecked_total,
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
