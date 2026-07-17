# Cognitive Switchyard -- Implementation Plan

> **Superseded:** This historical implementation plan predates the uv-managed PEP 723 launcher. See `cognitive_switchyard_design.md` and `operator_guide.md` for the current runtime model.

**Date:** 2026-03-07
**Design doc:** `docs/cognitive_switchyard_design.md`
**Reference system:** `reference/` (read-only -- production orchestration this was extracted from)

---

## 0. How to Use This Plan

### 0.1 Audience

This plan targets a mid-reasoning coding agent (Sonnet 4.6 medium or Codex-5.3 medium). Every step includes:
- Exact file paths and key function signatures
- Dependencies on prior steps (do NOT skip ahead)
- A **verification gate** -- a test or command that MUST pass before proceeding
- Edge cases and gotchas called out explicitly

### 0.2 The Cardinal Rule: Verify Before Proceeding

**Do not advance to step N+1 until step N's verification gate passes.** If a gate fails, fix the issue before moving on. Racing ahead and delivering breakage across multiple steps creates compounding failures that are extremely expensive to debug. Each step builds on the last -- a defect in step 1.3 will cascade into steps 1.6, 1.8, and beyond.

The cost of stopping to fix one issue is low. The cost of delivering a broken system where five components each have subtle defects is "throw it all away and start over."

### 0.3 Reading Order Before Implementation

Before writing any code, read these files in order:
1. `docs/cognitive_switchyard_design.md` (full design spec -- ALL sections)
2. `reference/work/orchestrate.sh` (production dispatch loop, recovery, constraint enforcement)
3. `reference/work/SYSTEM.md` (pipeline rules, state-as-directory conventions)
4. `reference/work/execution/RESOLUTION.md` (real constraint graph output)
5. `reference/work/execution/WORKER.md` (worker agent protocol, progress markers)
6. Two sample `.plan.md` files from `reference/work/execution/done/` (plan metadata format)
7. Two sample `.status` files from `reference/work/execution/done/` (status sidecar format)

### 0.4 Key Architectural Decisions

These decisions are final. Do not revisit them during implementation.

**Entry point architecture:** A single self-bootstrapping script `switchyard` (no extension) at the project root handles venv creation and re-exec. The actual implementation lives in the `switchyard/` Python package. The bootstrap script adds the project directory to `sys.path` before importing from the package.

**Threading model:** The orchestrator runs in a background thread with a synchronous polling loop using standard `sqlite3`. The FastAPI server runs in the main thread's async event loop using `aiosqlite`. Both access the same SQLite database file with WAL mode enabled. This is safe because WAL mode allows concurrent readers and serializes writers.

**Thread-to-async bridge:** The orchestrator thread uses `asyncio.run_coroutine_threadsafe()` to schedule WebSocket broadcasts on the FastAPI event loop. The orchestrator holds a reference to the event loop (captured at startup).

**State transition protocol:** Every state change follows this order:
1. Move the file atomically (`os.rename()`)
2. Update SQLite (conditional `UPDATE WHERE status = expected_status`)
3. Broadcast via WebSocket

The filesystem is the source of truth. SQLite is a read-optimized projection. Recovery reconciles SQLite from the filesystem.

**Error handling philosophy:** Fail fast within a step, recover gracefully at the orchestrator level. Individual operations (file moves, DB writes) should raise on failure. The orchestrator loop catches exceptions per-task and moves failed tasks to blocked -- it never crashes the entire session due to a single task failure.

### 0.5 Conventions

- **Imports:** Group stdlib, then third-party, then local. No star imports.
- **Type hints:** Use them on all public function signatures. Use `from __future__ import annotations` at the top of every module.
- **Docstrings:** Only on public classes and non-obvious public methods. Keep brief.
- **Logging:** Use Python `logging` module. Logger per module: `logger = logging.getLogger(__name__)`.
- **Constants:** ALL_CAPS, defined in `config.py` or at module top.
- **Path handling:** Use `pathlib.Path` everywhere. Never string concatenation for paths.
- **SQLite:** All writes use parameterized queries (`?` placeholders). Never f-strings in SQL.

---

## 1. Project Scaffolding

### Step 1.0: Create Directory Structure

Create the following directory tree. Every `__init__.py` starts empty.

```
cognitive_switchyard/
  switchyard                  # Entry point script (no extension)
  switchyard/
    __init__.py
    cli.py                    # Argparse CLI, calls server or orchestrator
    config.py                 # Paths, defaults, config loading
    models.py                 # Dataclasses
    state.py                  # SQLite operations
    pack_loader.py            # Pack discovery, validation, hook invocation
    watcher.py                # Filesystem watcher
    scheduler.py              # Constraint graph, eligibility
    worker_manager.py         # Subprocess lifecycle
    orchestrator.py           # Main orchestration loop
    server.py                 # FastAPI app, routes, WebSocket
    html_template.py          # Embedded React SPA HTML string
  packs/
    test-echo/
      pack.yaml
      scripts/
        execute
      templates/
        intake.md
  tests/
    __init__.py
    conftest.py
    test_config.py
    test_models.py
    test_state.py
    test_scheduler.py
    test_worker_manager.py
    test_orchestrator.py
  docs/
    cognitive_switchyard_design.md   # (already exists)
    implementation_plan.md           # (this file)
  reference/                         # (already exists, read-only)
  .gitignore
  README.md                          # (already exists)
```

**Verification gate:** Run `python3 -c "import switchyard"` from the project root. It should succeed (empty package imports fine). Run `ls switchyard/*.py` and confirm all files exist (they can be empty stubs with just `from __future__ import annotations`).

---

## 2. Phase 1: Core Engine (CLI Only, No UI)

**Goal:** A working orchestrator that can dispatch tasks from `ready/` to worker slots, enforce constraints, handle completions, and recover from crashes. Tested with a trivial `test-echo` pack.

**Phase 1 does NOT include:** Planning phase, resolution phase, auto-fix, verification, web UI. These are Phase 2 and 3. Phase 1 assumes plans are already in `ready/` with a pre-built `resolution.json`.

### Step 1.1: config.py -- Paths, Defaults, Configuration

**Dependencies:** Step 1.0 (directory structure exists)

**Purpose:** Central place for all filesystem paths, default values, and global config loading. Every other module imports paths from here.

**File:** `switchyard/config.py`

```python
from __future__ import annotations
import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field

# --- Filesystem paths ---
SWITCHYARD_HOME = Path.home() / ".switchyard"
SWITCHYARD_VENV = Path.home() / ".switchyard_venv"
SWITCHYARD_DB = SWITCHYARD_HOME / "switchyard.db"
PACKS_DIR = SWITCHYARD_HOME / "packs"
SESSIONS_DIR = SWITCHYARD_HOME / "sessions"
CONFIG_FILE = SWITCHYARD_HOME / "config.yaml"

# --- Built-in pack source (ships with project) ---
BUILTIN_PACKS_DIR = Path(__file__).parent.parent / "packs"

# --- Default values ---
DEFAULT_POLL_INTERVAL = 5          # seconds
DEFAULT_MAX_WORKERS = 2
DEFAULT_MAX_PLANNERS = 3
DEFAULT_FULL_TEST_INTERVAL = 4
DEFAULT_TASK_IDLE_TIMEOUT = 300    # seconds
DEFAULT_TASK_MAX_TIMEOUT = 0       # 0 = disabled
DEFAULT_SESSION_MAX_TIMEOUT = 14400  # 4 hours
DEFAULT_MAX_FIX_ATTEMPTS = 2
DEFAULT_RETENTION_DAYS = 30

# --- Progress marker pattern ---
PROGRESS_PATTERN = "##PROGRESS##"


@dataclass
class GlobalConfig:
    """Global config loaded from ~/.switchyard/config.yaml"""
    retention_days: int = DEFAULT_RETENTION_DAYS
    default_planners: int = DEFAULT_MAX_PLANNERS
    default_workers: int = DEFAULT_MAX_WORKERS
    default_pack: str = ""

    @classmethod
    def load(cls) -> GlobalConfig:
        """Load from config.yaml. Returns defaults if file missing."""
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                data = yaml.safe_load(f) or {}
            return cls(
                retention_days=data.get("retention_days", DEFAULT_RETENTION_DAYS),
                default_planners=data.get("default_planners", DEFAULT_MAX_PLANNERS),
                default_workers=data.get("default_workers", DEFAULT_MAX_WORKERS),
                default_pack=data.get("default_pack", ""),
            )
        return cls()

    def save(self) -> None:
        """Write current config to config.yaml."""
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "retention_days": self.retention_days,
            "default_planners": self.default_planners,
            "default_workers": self.default_workers,
            "default_pack": self.default_pack,
        }
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(data, f, default_flow_style=False)


@dataclass
class SessionConfig:
    """Per-session configuration (set at session creation, stored in SQLite)."""
    pack_name: str
    session_name: str
    num_workers: int = DEFAULT_MAX_WORKERS
    num_planners: int = DEFAULT_MAX_PLANNERS
    poll_interval: int = DEFAULT_POLL_INTERVAL
    verification_interval: int = DEFAULT_FULL_TEST_INTERVAL
    auto_fix_enabled: bool = False
    auto_fix_max_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS
    task_idle_timeout: int = DEFAULT_TASK_IDLE_TIMEOUT
    task_max_timeout: int = DEFAULT_TASK_MAX_TIMEOUT
    session_max_timeout: int = DEFAULT_SESSION_MAX_TIMEOUT
    env_vars: dict[str, str] = field(default_factory=dict)


def ensure_directories() -> None:
    """Create the ~/.switchyard directory structure if it doesn't exist."""
    for d in [SWITCHYARD_HOME, PACKS_DIR, SESSIONS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def session_dir(session_id: str) -> Path:
    """Return the filesystem path for a session's working directory."""
    return SESSIONS_DIR / session_id


def session_subdirs(session_id: str) -> dict[str, Path]:
    """Return all standard subdirectory paths for a session."""
    base = session_dir(session_id)
    return {
        "intake": base / "intake",
        "claimed": base / "claimed",
        "staging": base / "staging",
        "review": base / "review",
        "ready": base / "ready",
        "workers": base / "workers",
        "done": base / "done",
        "blocked": base / "blocked",
        "logs": base / "logs",
        "logs_workers": base / "logs" / "workers",
    }
```

**Verification gate:** Create `tests/test_config.py`:

```python
from switchyard.config import (
    SWITCHYARD_HOME, GlobalConfig, SessionConfig,
    ensure_directories, session_dir, session_subdirs,
)
from pathlib import Path
import tempfile
import os

def test_paths_are_pathlib():
    assert isinstance(SWITCHYARD_HOME, Path)

def test_global_config_defaults():
    cfg = GlobalConfig()
    assert cfg.retention_days == 30
    assert cfg.default_workers == 2

def test_global_config_save_load(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr("switchyard.config.CONFIG_FILE", config_file)
    cfg = GlobalConfig(retention_days=7, default_workers=4)
    cfg.save()
    assert config_file.exists()
    loaded = GlobalConfig.load()
    assert loaded.retention_days == 7
    assert loaded.default_workers == 4

def test_session_config_defaults():
    cfg = SessionConfig(pack_name="test", session_name="run-1")
    assert cfg.num_workers == 2
    assert cfg.task_idle_timeout == 300

def test_session_subdirs():
    dirs = session_subdirs("abc-123")
    assert "intake" in dirs
    assert "ready" in dirs
    assert "done" in dirs
    assert dirs["intake"].name == "intake"

def test_ensure_directories(tmp_path, monkeypatch):
    home = tmp_path / ".switchyard"
    monkeypatch.setattr("switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("switchyard.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("switchyard.config.SESSIONS_DIR", home / "sessions")
    ensure_directories()
    assert (home / "packs").is_dir()
    assert (home / "sessions").is_dir()
```

Run: `cd /Users/example/source/utilities/cognitive_switchyard && python3 -m pytest tests/test_config.py -v`
All tests must pass before proceeding.

---

### Step 1.2: models.py -- Data Models

**Dependencies:** Step 1.1 (config.py exists and tested)

**Purpose:** Pure dataclasses representing all domain objects. No business logic, no I/O. These are used by every other module.

**File:** `switchyard/models.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SessionStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    RESOLVING = "resolving"
    RUNNING = "running"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    ABORTED = "aborted"


class TaskStatus(str, Enum):
    INTAKE = "intake"
    PLANNING = "planning"
    STAGED = "staged"
    REVIEW = "review"
    READY = "ready"
    ACTIVE = "active"
    DONE = "done"
    BLOCKED = "blocked"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    PROBLEM = "problem"


class EventType(str, Enum):
    SESSION_CREATED = "session_created"
    SESSION_STARTED = "session_started"
    SESSION_PAUSED = "session_paused"
    SESSION_RESUMED = "session_resumed"
    SESSION_COMPLETED = "session_completed"
    SESSION_ABORTED = "session_aborted"
    TASK_STATUS_CHANGE = "task_status_change"
    TASK_DISPATCHED = "task_dispatched"
    TASK_COMPLETED = "task_completed"
    TASK_BLOCKED = "task_blocked"
    WORKER_IDLE = "worker_idle"
    WORKER_ACTIVE = "worker_active"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    FIX_STARTED = "fix_started"
    FIX_SUCCEEDED = "fix_succeeded"
    FIX_FAILED = "fix_failed"
    TIMEOUT_WARNING = "timeout_warning"
    TIMEOUT_KILL = "timeout_kill"
    ERROR = "error"


@dataclass
class Session:
    id: str
    name: str
    pack_name: str
    config_json: str                  # JSON-serialized SessionConfig
    status: SessionStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    abort_reason: Optional[str] = None


@dataclass
class Task:
    id: str                           # e.g. "001", "023a"
    session_id: str
    title: str
    status: TaskStatus
    phase: Optional[str] = None       # Current execution phase name
    phase_num: Optional[int] = None   # Current phase number (1-based)
    phase_total: Optional[int] = None # Total phases
    detail: Optional[str] = None      # Latest detail progress message
    worker_slot: Optional[int] = None
    depends_on: list[str] = field(default_factory=list)
    anti_affinity: list[str] = field(default_factory=list)
    exec_order: int = 1
    plan_filename: Optional[str] = None
    blocked_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class WorkerSlot:
    session_id: str
    slot_number: int
    status: WorkerStatus = WorkerStatus.IDLE
    current_task_id: Optional[str] = None
    pid: Optional[int] = None


@dataclass
class Event:
    session_id: str
    timestamp: datetime
    event_type: EventType
    task_id: Optional[str] = None
    worker_slot: Optional[int] = None
    message: str = ""


@dataclass
class Constraint:
    """Parsed constraint for a single task from resolution.json."""
    task_id: str
    depends_on: list[str] = field(default_factory=list)
    anti_affinity: list[str] = field(default_factory=list)
    exec_order: int = 1


@dataclass
class StatusSidecar:
    """Parsed content of a .status sidecar file."""
    status: str = "blocked"       # "done" or "blocked"
    commits: str = "none"
    tests_ran: str = "none"       # "targeted", "full", "none"
    test_result: str = "skip"     # "pass", "fail", "skip"
    blocked_reason: str = ""
    notes: str = ""

    @classmethod
    def parse(cls, text: str) -> StatusSidecar:
        """Parse a key-value status sidecar file.

        Format (one key-value per line):
            STATUS: done
            COMMITS: abc123,def456
            TESTS_RAN: targeted
            TEST_RESULT: pass
            BLOCKED_REASON: (only if blocked)
            NOTES: optional freeform
        """
        result = cls()
        for line in text.strip().splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().upper()
            value = value.strip()
            if key == "STATUS":
                result.status = value.lower()
            elif key == "COMMITS":
                result.commits = value
            elif key == "TESTS_RAN":
                result.tests_ran = value.lower()
            elif key == "TEST_RESULT":
                result.test_result = value.lower()
            elif key == "BLOCKED_REASON":
                result.blocked_reason = value
            elif key == "NOTES":
                result.notes = value
        return result

    @classmethod
    def from_file(cls, path) -> StatusSidecar:
        """Read and parse a status sidecar file. Returns default (blocked) if unreadable."""
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            return cls.parse(p.read_text())
        except Exception:
            return cls()
```

**Verification gate:** Create `tests/test_models.py`:

```python
from switchyard.models import (
    SessionStatus, TaskStatus, WorkerStatus, EventType,
    Session, Task, WorkerSlot, Event, Constraint, StatusSidecar,
)
from datetime import datetime

def test_session_status_values():
    assert SessionStatus.CREATED == "created"
    assert SessionStatus.RUNNING == "running"
    assert SessionStatus.COMPLETED == "completed"

def test_task_defaults():
    t = Task(id="001", session_id="s1", title="Test", status=TaskStatus.READY)
    assert t.depends_on == []
    assert t.anti_affinity == []
    assert t.exec_order == 1
    assert t.worker_slot is None

def test_status_sidecar_parse_done():
    text = """STATUS: done
COMMITS: abc123,def456
TESTS_RAN: targeted
TEST_RESULT: pass
NOTES: All good"""
    s = StatusSidecar.parse(text)
    assert s.status == "done"
    assert s.commits == "abc123,def456"
    assert s.tests_ran == "targeted"
    assert s.test_result == "pass"
    assert s.notes == "All good"

def test_status_sidecar_parse_blocked():
    text = """STATUS: blocked
COMMITS: none
TESTS_RAN: targeted
TEST_RESULT: fail
BLOCKED_REASON: Tests failed after implementation"""
    s = StatusSidecar.parse(text)
    assert s.status == "blocked"
    assert s.blocked_reason == "Tests failed after implementation"

def test_status_sidecar_parse_empty():
    s = StatusSidecar.parse("")
    assert s.status == "blocked"  # default

def test_status_sidecar_parse_malformed():
    s = StatusSidecar.parse("garbage\nno colons here\n")
    assert s.status == "blocked"  # default

def test_status_sidecar_from_file(tmp_path):
    f = tmp_path / "test.status"
    f.write_text("STATUS: done\nCOMMITS: abc\nTESTS_RAN: full\nTEST_RESULT: pass\n")
    s = StatusSidecar.from_file(f)
    assert s.status == "done"

def test_status_sidecar_from_missing_file(tmp_path):
    s = StatusSidecar.from_file(tmp_path / "nonexistent.status")
    assert s.status == "blocked"

def test_constraint_defaults():
    c = Constraint(task_id="001")
    assert c.depends_on == []
    assert c.exec_order == 1
```

Run: `python3 -m pytest tests/test_models.py -v`
All tests must pass before proceeding.

---

### Step 1.3: state.py -- SQLite State Store

**Dependencies:** Steps 1.1, 1.2 (config and models exist and are tested)

**Purpose:** All SQLite operations. Two interfaces: synchronous (for orchestrator thread) and async (for FastAPI). Both operate on the same WAL-mode database file.

**Critical design constraint:** The filesystem is the source of truth. SQLite is a read-optimized projection. The `reconcile_from_filesystem()` method rebuilds DB state from the directory structure. This is called during crash recovery.

**File:** `switchyard/state.py`

Implement the following. Key points are noted inline; implement the full bodies.

```python
from __future__ import annotations
import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from switchyard.config import SWITCHYARD_DB, session_dir, session_subdirs
from switchyard.models import (
    Session, SessionStatus, Task, TaskStatus,
    WorkerSlot, WorkerStatus, Event, EventType,
)

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    pack_name TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    abort_reason TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'intake',
    phase TEXT,
    phase_num INTEGER,
    phase_total INTEGER,
    detail TEXT,
    worker_slot INTEGER,
    depends_on TEXT NOT NULL DEFAULT '[]',
    anti_affinity TEXT NOT NULL DEFAULT '[]',
    exec_order INTEGER NOT NULL DEFAULT 1,
    plan_filename TEXT,
    blocked_reason TEXT,
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    PRIMARY KEY (id, session_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS worker_slots (
    session_id TEXT NOT NULL,
    slot_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    current_task_id TEXT,
    pid INTEGER,
    PRIMARY KEY (session_id, slot_number),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    task_id TEXT,
    worker_slot INTEGER,
    message TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
"""


class StateStore:
    """Synchronous SQLite state store for use in the orchestrator thread."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or SWITCHYARD_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if not self._conn:
            raise RuntimeError("StateStore not connected. Call connect() first.")
        return self._conn

    # --- Session CRUD ---

    def create_session(self, session: Session) -> None:
        self.conn.execute(
            """INSERT INTO sessions (id, name, pack_name, config_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session.id, session.name, session.pack_name,
             session.config_json, session.status.value,
             session.created_at.isoformat()),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> Optional[Session]:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_session(row)

    def list_sessions(self) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def update_session_status(
        self, session_id: str, new_status: SessionStatus,
        expected_status: Optional[SessionStatus] = None,
        **extra_fields,
    ) -> bool:
        """Conditionally update session status. Returns True if row was updated.

        If expected_status is provided, only updates if current status matches.
        This prevents race conditions.

        extra_fields can include: started_at, completed_at, abort_reason.
        """
        set_parts = ["status = ?"]
        params: list = [new_status.value]
        for key, val in extra_fields.items():
            if key in ("started_at", "completed_at"):
                set_parts.append(f"{key} = ?")
                params.append(val.isoformat() if isinstance(val, datetime) else val)
            elif key == "abort_reason":
                set_parts.append(f"{key} = ?")
                params.append(val)

        where = "id = ?"
        params.append(session_id)
        if expected_status is not None:
            where += " AND status = ?"
            params.append(expected_status.value)

        cursor = self.conn.execute(
            f"UPDATE sessions SET {', '.join(set_parts)} WHERE {where}",
            params,
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        """Delete session and all related rows. Returns True if deleted."""
        self.conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM worker_slots WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM tasks WHERE session_id = ?", (session_id,))
        cursor = self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # --- Task CRUD ---

    def create_task(self, task: Task) -> None:
        self.conn.execute(
            """INSERT INTO tasks
               (id, session_id, title, status, depends_on, anti_affinity,
                exec_order, plan_filename, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task.id, task.session_id, task.title, task.status.value,
             json.dumps(task.depends_on), json.dumps(task.anti_affinity),
             task.exec_order, task.plan_filename,
             task.created_at.isoformat() if task.created_at else None),
        )
        self.conn.commit()

    def get_task(self, session_id: str, task_id: str) -> Optional[Task]:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE session_id = ? AND id = ?",
            (session_id, task_id),
        ).fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def list_tasks(self, session_id: str, status: Optional[TaskStatus] = None) -> list[Task]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE session_id = ? AND status = ? ORDER BY exec_order, id",
                (session_id, status.value),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE session_id = ? ORDER BY exec_order, id",
                (session_id,),
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_task_status(
        self, session_id: str, task_id: str, new_status: TaskStatus,
        expected_status: Optional[TaskStatus] = None,
        **extra_fields,
    ) -> bool:
        """Conditionally update task status. Returns True if updated.

        extra_fields can include: worker_slot, phase, phase_num, phase_total,
        detail, blocked_reason, started_at, completed_at, plan_filename.
        """
        set_parts = ["status = ?"]
        params: list = [new_status.value]

        allowed_fields = {
            "worker_slot", "phase", "phase_num", "phase_total", "detail",
            "blocked_reason", "started_at", "completed_at", "plan_filename",
        }
        for key, val in extra_fields.items():
            if key not in allowed_fields:
                continue
            set_parts.append(f"{key} = ?")
            if key in ("started_at", "completed_at") and isinstance(val, datetime):
                params.append(val.isoformat())
            else:
                params.append(val)

        where = "session_id = ? AND id = ?"
        params.extend([session_id, task_id])
        if expected_status is not None:
            where += " AND status = ?"
            params.append(expected_status.value)

        cursor = self.conn.execute(
            f"UPDATE tasks SET {', '.join(set_parts)} WHERE {where}",
            params,
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # --- Worker Slots ---

    def create_worker_slots(self, session_id: str, num_workers: int) -> None:
        for i in range(num_workers):
            self.conn.execute(
                """INSERT OR REPLACE INTO worker_slots
                   (session_id, slot_number, status, current_task_id, pid)
                   VALUES (?, ?, 'idle', NULL, NULL)""",
                (session_id, i),
            )
        self.conn.commit()

    def get_worker_slots(self, session_id: str) -> list[WorkerSlot]:
        rows = self.conn.execute(
            "SELECT * FROM worker_slots WHERE session_id = ? ORDER BY slot_number",
            (session_id,),
        ).fetchall()
        return [
            WorkerSlot(
                session_id=row["session_id"],
                slot_number=row["slot_number"],
                status=WorkerStatus(row["status"]),
                current_task_id=row["current_task_id"],
                pid=row["pid"],
            )
            for row in rows
        ]

    def update_worker_slot(
        self, session_id: str, slot_number: int,
        status: WorkerStatus,
        current_task_id: Optional[str] = None,
        pid: Optional[int] = None,
    ) -> None:
        self.conn.execute(
            """UPDATE worker_slots
               SET status = ?, current_task_id = ?, pid = ?
               WHERE session_id = ? AND slot_number = ?""",
            (status.value, current_task_id, pid, session_id, slot_number),
        )
        self.conn.commit()

    # --- Events ---

    def add_event(self, event: Event) -> None:
        self.conn.execute(
            """INSERT INTO events (session_id, timestamp, event_type, task_id, worker_slot, message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event.session_id, event.timestamp.isoformat(),
             event.event_type.value, event.task_id,
             event.worker_slot, event.message),
        )
        self.conn.commit()

    def list_events(self, session_id: str, limit: int = 100) -> list[Event]:
        rows = self.conn.execute(
            """SELECT * FROM events WHERE session_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        return [
            Event(
                session_id=row["session_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                event_type=EventType(row["event_type"]),
                task_id=row["task_id"],
                worker_slot=row["worker_slot"],
                message=row["message"],
            )
            for row in rows
        ]

    # --- Pipeline counts (for dashboard/UI) ---

    def pipeline_counts(self, session_id: str) -> dict[str, int]:
        """Return task counts by status for a session."""
        rows = self.conn.execute(
            """SELECT status, COUNT(*) as cnt FROM tasks
               WHERE session_id = ? GROUP BY status""",
            (session_id,),
        ).fetchall()
        counts = {s.value: 0 for s in TaskStatus}
        for row in rows:
            counts[row["status"]] = row["cnt"]
        return counts

    # --- Reconciliation ---

    def reconcile_tasks_from_filesystem(self, session_id: str) -> None:
        """Rebuild task statuses from filesystem directory locations.

        The filesystem is the source of truth. For each task, check which
        directory its plan file is in and update the DB status to match.
        """
        dirs = session_subdirs(session_id)
        # Map directory -> TaskStatus
        dir_status_map = {
            dirs["intake"]: TaskStatus.INTAKE,
            dirs["claimed"]: TaskStatus.PLANNING,
            dirs["staging"]: TaskStatus.STAGED,
            dirs["review"]: TaskStatus.REVIEW,
            dirs["ready"]: TaskStatus.READY,
            dirs["done"]: TaskStatus.DONE,
            dirs["blocked"]: TaskStatus.BLOCKED,
        }

        # Check worker slot directories
        workers_base = dirs["workers"]

        for dir_path, status in dir_status_map.items():
            if not dir_path.exists():
                continue
            for plan_file in dir_path.glob("*.plan.md"):
                task_id = self._extract_task_id_from_filename(plan_file.name)
                if task_id:
                    self.conn.execute(
                        "UPDATE tasks SET status = ? WHERE session_id = ? AND id = ?",
                        (status.value, session_id, task_id),
                    )

        # Check worker slot directories for active tasks
        if workers_base.exists():
            for slot_dir in workers_base.iterdir():
                if not slot_dir.is_dir():
                    continue
                try:
                    slot_num = int(slot_dir.name)
                except ValueError:
                    continue
                for plan_file in slot_dir.glob("*.plan.md"):
                    task_id = self._extract_task_id_from_filename(plan_file.name)
                    if task_id:
                        self.conn.execute(
                            """UPDATE tasks SET status = ?, worker_slot = ?
                               WHERE session_id = ? AND id = ?""",
                            (TaskStatus.ACTIVE.value, slot_num, session_id, task_id),
                        )

        self.conn.commit()
        logger.info("Reconciled task statuses from filesystem for session %s", session_id)

    # --- Internal helpers ---

    @staticmethod
    def _extract_task_id_from_filename(filename: str) -> Optional[str]:
        """Extract task ID from plan filename.

        Handles: '001_some_slug.plan.md' -> '001'
                 '023a_some_slug.plan.md' -> '023a'
                 '023-b_some_slug.plan.md' -> '023b' (normalize dash variant)
        """
        # Take everything before the first underscore
        base = filename.split("_", 1)[0] if "_" in filename else filename.split(".", 1)[0]
        # Normalize dash-separated sub-IDs: "023-b" -> "023b"
        base = base.replace("-", "")
        return base if base else None

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            name=row["name"],
            pack_name=row["pack_name"],
            config_json=row["config_json"],
            status=SessionStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            abort_reason=row["abort_reason"],
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            status=TaskStatus(row["status"]),
            phase=row["phase"],
            phase_num=row["phase_num"],
            phase_total=row["phase_total"],
            detail=row["detail"],
            worker_slot=row["worker_slot"],
            depends_on=json.loads(row["depends_on"]) if row["depends_on"] else [],
            anti_affinity=json.loads(row["anti_affinity"]) if row["anti_affinity"] else [],
            exec_order=row["exec_order"],
            plan_filename=row["plan_filename"],
            blocked_reason=row["blocked_reason"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )
```

**Verification gate:** Create `tests/test_state.py`. This is the most critical test file in Phase 1 -- if the state store is broken, everything downstream fails.

```python
"""Tests for the synchronous StateStore.

These tests create a temporary in-memory or tmp_path DB. They validate
all CRUD operations, conditional updates, pipeline counts, filename parsing,
and filesystem reconciliation.
"""
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from switchyard.state import StateStore
from switchyard.models import (
    Session, SessionStatus, Task, TaskStatus,
    WorkerSlot, WorkerStatus, Event, EventType,
)


@pytest.fixture
def store(tmp_path):
    """Create a StateStore backed by a temporary database."""
    db = tmp_path / "test.db"
    s = StateStore(db_path=db)
    s.connect()
    yield s
    s.close()


@pytest.fixture
def session_id():
    return "test-session-001"


@pytest.fixture
def sample_session(session_id):
    return Session(
        id=session_id,
        name="Test Run",
        pack_name="test-echo",
        config_json="{}",
        status=SessionStatus.CREATED,
        created_at=datetime.now(timezone.utc),
    )


class TestSessionCRUD:
    def test_create_and_get(self, store, sample_session):
        store.create_session(sample_session)
        got = store.get_session(sample_session.id)
        assert got is not None
        assert got.name == "Test Run"
        assert got.status == SessionStatus.CREATED

    def test_get_nonexistent(self, store):
        assert store.get_session("nope") is None

    def test_list_sessions(self, store, sample_session):
        store.create_session(sample_session)
        sessions = store.list_sessions()
        assert len(sessions) == 1

    def test_update_status_unconditional(self, store, sample_session):
        store.create_session(sample_session)
        ok = store.update_session_status(sample_session.id, SessionStatus.RUNNING)
        assert ok
        got = store.get_session(sample_session.id)
        assert got.status == SessionStatus.RUNNING

    def test_update_status_conditional_match(self, store, sample_session):
        store.create_session(sample_session)
        ok = store.update_session_status(
            sample_session.id, SessionStatus.RUNNING,
            expected_status=SessionStatus.CREATED,
        )
        assert ok

    def test_update_status_conditional_mismatch(self, store, sample_session):
        store.create_session(sample_session)
        ok = store.update_session_status(
            sample_session.id, SessionStatus.RUNNING,
            expected_status=SessionStatus.PAUSED,  # wrong
        )
        assert not ok
        got = store.get_session(sample_session.id)
        assert got.status == SessionStatus.CREATED  # unchanged

    def test_delete_session(self, store, sample_session):
        store.create_session(sample_session)
        assert store.delete_session(sample_session.id)
        assert store.get_session(sample_session.id) is None


class TestTaskCRUD:
    def test_create_and_get(self, store, sample_session, session_id):
        store.create_session(sample_session)
        task = Task(
            id="001", session_id=session_id, title="Test Task",
            status=TaskStatus.READY, depends_on=["002"],
            anti_affinity=["003"], exec_order=1,
            plan_filename="001_test.plan.md",
            created_at=datetime.now(timezone.utc),
        )
        store.create_task(task)
        got = store.get_task(session_id, "001")
        assert got is not None
        assert got.title == "Test Task"
        assert got.depends_on == ["002"]
        assert got.anti_affinity == ["003"]

    def test_list_tasks_by_status(self, store, sample_session, session_id):
        store.create_session(sample_session)
        for tid, status in [("001", TaskStatus.READY), ("002", TaskStatus.DONE), ("003", TaskStatus.READY)]:
            store.create_task(Task(id=tid, session_id=session_id, title=f"Task {tid}", status=status))
        ready = store.list_tasks(session_id, status=TaskStatus.READY)
        assert len(ready) == 2
        all_tasks = store.list_tasks(session_id)
        assert len(all_tasks) == 3

    def test_update_task_conditional(self, store, sample_session, session_id):
        store.create_session(sample_session)
        store.create_task(Task(id="001", session_id=session_id, title="T", status=TaskStatus.READY))
        # Correct expected status
        ok = store.update_task_status(session_id, "001", TaskStatus.ACTIVE, expected_status=TaskStatus.READY, worker_slot=0)
        assert ok
        got = store.get_task(session_id, "001")
        assert got.status == TaskStatus.ACTIVE
        assert got.worker_slot == 0
        # Wrong expected status
        ok = store.update_task_status(session_id, "001", TaskStatus.DONE, expected_status=TaskStatus.READY)
        assert not ok  # still ACTIVE, not READY


class TestWorkerSlots:
    def test_create_and_get(self, store, sample_session, session_id):
        store.create_session(sample_session)
        store.create_worker_slots(session_id, 3)
        slots = store.get_worker_slots(session_id)
        assert len(slots) == 3
        assert all(s.status == WorkerStatus.IDLE for s in slots)

    def test_update_slot(self, store, sample_session, session_id):
        store.create_session(sample_session)
        store.create_worker_slots(session_id, 2)
        store.update_worker_slot(session_id, 0, WorkerStatus.ACTIVE, current_task_id="001", pid=12345)
        slots = store.get_worker_slots(session_id)
        assert slots[0].status == WorkerStatus.ACTIVE
        assert slots[0].current_task_id == "001"
        assert slots[0].pid == 12345


class TestEvents:
    def test_add_and_list(self, store, sample_session, session_id):
        store.create_session(sample_session)
        store.add_event(Event(
            session_id=session_id,
            timestamp=datetime.now(timezone.utc),
            event_type=EventType.TASK_DISPATCHED,
            task_id="001", worker_slot=0,
            message="Dispatched task 001 to slot 0",
        ))
        events = store.list_events(session_id)
        assert len(events) == 1
        assert events[0].event_type == EventType.TASK_DISPATCHED


class TestPipelineCounts:
    def test_counts(self, store, sample_session, session_id):
        store.create_session(sample_session)
        for tid, status in [("001", TaskStatus.READY), ("002", TaskStatus.READY),
                            ("003", TaskStatus.ACTIVE), ("004", TaskStatus.DONE)]:
            store.create_task(Task(id=tid, session_id=session_id, title=f"T{tid}", status=status))
        counts = store.pipeline_counts(session_id)
        assert counts["ready"] == 2
        assert counts["active"] == 1
        assert counts["done"] == 1
        assert counts["blocked"] == 0


class TestFilenameParser:
    @pytest.mark.parametrize("filename,expected", [
        ("001_some_slug.plan.md", "001"),
        ("023a_task_name.plan.md", "023a"),
        ("023-b_task_name.plan.md", "023b"),
        ("040_schema_editor.plan.md", "040"),
    ])
    def test_extract_task_id(self, filename, expected):
        assert StateStore._extract_task_id_from_filename(filename) == expected


class TestReconciliation:
    def test_reconcile_from_filesystem(self, store, sample_session, session_id, tmp_path, monkeypatch):
        """Create tasks in DB as READY, then put plan files in done/ directory.
        Reconciliation should update DB to DONE."""
        store.create_session(sample_session)

        # Create tasks in DB
        store.create_task(Task(id="001", session_id=session_id, title="T1", status=TaskStatus.READY, plan_filename="001_t1.plan.md"))
        store.create_task(Task(id="002", session_id=session_id, title="T2", status=TaskStatus.READY, plan_filename="002_t2.plan.md"))

        # Set up filesystem: put plan files in done/
        base = tmp_path / "sessions" / session_id
        done_dir = base / "done"
        ready_dir = base / "ready"
        done_dir.mkdir(parents=True)
        ready_dir.mkdir(parents=True)
        (done_dir / "001_t1.plan.md").write_text("plan content")
        (ready_dir / "002_t2.plan.md").write_text("plan content")

        # Monkeypatch session_subdirs to use tmp_path
        def mock_subdirs(sid):
            b = tmp_path / "sessions" / sid
            return {
                "intake": b / "intake",
                "claimed": b / "claimed",
                "staging": b / "staging",
                "review": b / "review",
                "ready": b / "ready",
                "workers": b / "workers",
                "done": b / "done",
                "blocked": b / "blocked",
                "logs": b / "logs",
                "logs_workers": b / "logs" / "workers",
            }
        monkeypatch.setattr("switchyard.state.session_subdirs", mock_subdirs)

        store.reconcile_tasks_from_filesystem(session_id)

        t1 = store.get_task(session_id, "001")
        assert t1.status == TaskStatus.DONE
        t2 = store.get_task(session_id, "002")
        assert t2.status == TaskStatus.READY  # still in ready/
```

Run: `python3 -m pytest tests/test_state.py -v`
**Every test must pass.** The state store is the foundation -- do not proceed with any failures.

---

### Step 1.4: pack_loader.py -- Pack Discovery and Validation

**Dependencies:** Steps 1.1, 1.2 (config, models)

**Purpose:** Discover packs in `~/.switchyard/packs/`, parse and validate `pack.yaml`, copy built-in packs on first run, invoke lifecycle hooks via subprocess.

**File:** `switchyard/pack_loader.py`

Key functions to implement:

```python
from __future__ import annotations
import logging
import os
import shutil
import subprocess
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from switchyard.config import PACKS_DIR, BUILTIN_PACKS_DIR

logger = logging.getLogger(__name__)


@dataclass
class PackConfig:
    """Parsed pack.yaml."""
    name: str
    description: str = ""
    version: str = "0.1.0"

    # Phase config
    planning_enabled: bool = False
    planning_executor: str = "agent"
    planning_model: str = "opus"
    planning_prompt: str = ""
    planning_max_instances: int = 1

    resolution_enabled: bool = True
    resolution_executor: str = "agent"  # agent | script | passthrough
    resolution_model: str = "opus"
    resolution_prompt: str = ""
    resolution_script: str = ""

    execution_executor: str = "shell"  # agent | shell
    execution_model: str = "sonnet"
    execution_prompt: str = ""
    execution_command: str = ""
    execution_max_workers: int = 2

    verification_enabled: bool = False
    verification_command: str = ""
    verification_interval: int = 4

    auto_fix_enabled: bool = False
    auto_fix_max_attempts: int = 2
    auto_fix_model: str = "opus"
    auto_fix_prompt: str = ""

    # Isolation
    isolation_type: str = "none"  # git-worktree | temp-directory | none
    isolation_setup: str = ""
    isolation_teardown: str = ""

    # Prerequisites
    prerequisites: list[dict] = field(default_factory=list)

    # Timeouts
    task_idle_timeout: int = 300
    task_max_timeout: int = 0
    session_max_timeout: int = 14400

    # Status/progress
    progress_format: str = "##PROGRESS##"
    sidecar_format: str = "key-value"


def bootstrap_packs() -> None:
    """Copy built-in packs to ~/.switchyard/packs/ if they don't already exist."""
    if not BUILTIN_PACKS_DIR.exists():
        logger.warning("No built-in packs directory found at %s", BUILTIN_PACKS_DIR)
        return

    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    for pack_dir in BUILTIN_PACKS_DIR.iterdir():
        if not pack_dir.is_dir():
            continue
        dest = PACKS_DIR / pack_dir.name
        if dest.exists():
            logger.debug("Pack '%s' already exists, skipping", pack_dir.name)
            continue
        logger.info("Installing built-in pack: %s", pack_dir.name)
        shutil.copytree(pack_dir, dest)


def reset_pack(name: str) -> bool:
    """Restore a single built-in pack to factory default. Returns True if successful."""
    src = BUILTIN_PACKS_DIR / name
    dest = PACKS_DIR / name
    if not src.exists():
        logger.error("No built-in pack named '%s'", name)
        return False
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    logger.info("Reset pack '%s' to factory default", name)
    return True


def list_packs() -> list[PackConfig]:
    """List all available packs."""
    packs = []
    if not PACKS_DIR.exists():
        return packs
    for pack_dir in sorted(PACKS_DIR.iterdir()):
        if not pack_dir.is_dir():
            continue
        yaml_path = pack_dir / "pack.yaml"
        if not yaml_path.exists():
            continue
        try:
            packs.append(load_pack(pack_dir.name))
        except Exception as e:
            logger.warning("Skipping invalid pack '%s': %s", pack_dir.name, e)
    return packs


def load_pack(name: str) -> PackConfig:
    """Load and validate a pack by name. Raises ValueError on invalid config."""
    pack_dir = PACKS_DIR / name
    yaml_path = pack_dir / "pack.yaml"
    if not yaml_path.exists():
        raise ValueError(f"Pack '{name}' not found (no pack.yaml at {yaml_path})")

    with open(yaml_path) as f:
        data = yaml.safe_load(f) or {}

    if not data.get("name"):
        raise ValueError(f"Pack '{name}': pack.yaml missing required 'name' field")

    # Parse phases
    phases = data.get("phases", {})
    planning = phases.get("planning", {})
    resolution = phases.get("resolution", {})
    execution = phases.get("execution", {})
    verification = phases.get("verification", {})
    auto_fix = data.get("auto_fix", {})
    isolation = data.get("isolation", {})
    timeouts = data.get("timeouts", {})
    status = data.get("status", {})

    config = PackConfig(
        name=data["name"],
        description=data.get("description", ""),
        version=data.get("version", "0.1.0"),
        planning_enabled=planning.get("enabled", False),
        planning_executor=planning.get("executor", "agent"),
        planning_model=planning.get("model", "opus"),
        planning_prompt=planning.get("prompt", ""),
        planning_max_instances=planning.get("max_instances", 1),
        resolution_enabled=resolution.get("enabled", True),
        resolution_executor=resolution.get("executor", "agent"),
        resolution_model=resolution.get("model", "opus"),
        resolution_prompt=resolution.get("prompt", ""),
        resolution_script=resolution.get("script", ""),
        execution_executor=execution.get("executor", "shell"),
        execution_model=execution.get("model", "sonnet"),
        execution_prompt=execution.get("prompt", ""),
        execution_command=execution.get("command", ""),
        execution_max_workers=execution.get("max_workers", 2),
        verification_enabled=verification.get("enabled", False),
        verification_command=verification.get("command", ""),
        verification_interval=verification.get("interval", 4),
        auto_fix_enabled=auto_fix.get("enabled", False),
        auto_fix_max_attempts=auto_fix.get("max_attempts", 2),
        auto_fix_model=auto_fix.get("model", "opus"),
        auto_fix_prompt=auto_fix.get("prompt", ""),
        isolation_type=isolation.get("type", "none"),
        isolation_setup=isolation.get("setup", ""),
        isolation_teardown=isolation.get("teardown", ""),
        prerequisites=data.get("prerequisites", []),
        task_idle_timeout=timeouts.get("task_idle", 300),
        task_max_timeout=timeouts.get("task_max", 0),
        session_max_timeout=timeouts.get("session_max", 14400),
        progress_format=status.get("progress_format", "##PROGRESS##"),
        sidecar_format=status.get("sidecar_format", "key-value"),
    )
    return config


def pack_dir(name: str) -> Path:
    """Return the filesystem path for a pack."""
    return PACKS_DIR / name


def check_scripts_executable(name: str) -> list[tuple[str, str]]:
    """Check all scripts in a pack's scripts/ dir for executable bit.

    Returns list of (script_path, fix_command) for non-executable scripts.
    Empty list means all scripts are executable.

    This is the orchestrator-enforced preflight check (design doc section 4.3).
    """
    scripts_dir = pack_dir(name) / "scripts"
    if not scripts_dir.exists():
        return []

    failures = []
    for script in scripts_dir.iterdir():
        if script.is_file() and not os.access(script, os.X_OK):
            failures.append((
                str(script.relative_to(pack_dir(name))),
                f"chmod +x {script}",
            ))
    return failures


def run_preflight(name: str) -> list[tuple[str, bool, str]]:
    """Run a pack's prerequisite checks.

    Returns list of (check_name, passed, detail).
    """
    config = load_pack(name)
    results = []
    for prereq in config.prerequisites:
        check_name = prereq.get("name", "unnamed")
        check_cmd = prereq.get("check", "")
        if not check_cmd:
            results.append((check_name, False, "No check command specified"))
            continue
        try:
            result = subprocess.run(
                check_cmd, shell=True, capture_output=True, text=True, timeout=30,
            )
            passed = result.returncode == 0
            detail = result.stdout.strip() if passed else result.stderr.strip()
            results.append((check_name, passed, detail))
        except subprocess.TimeoutExpired:
            results.append((check_name, False, "Check timed out (30s)"))
        except Exception as e:
            results.append((check_name, False, str(e)))
    return results


def invoke_hook(
    pack_name: str, script_relative_path: str,
    args: list[str] = None, cwd: str = None,
    capture_output: bool = True, timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Invoke a pack lifecycle hook script.

    Args:
        pack_name: Name of the pack
        script_relative_path: Path relative to pack dir (e.g., "scripts/execute")
        args: Positional arguments to pass
        cwd: Working directory for the script
        capture_output: Whether to capture stdout/stderr
        timeout: Timeout in seconds

    Returns:
        CompletedProcess result

    Raises:
        FileNotFoundError: If script doesn't exist
        PermissionError: If script isn't executable
        subprocess.TimeoutExpired: If script exceeds timeout
    """
    script_path = pack_dir(pack_name) / script_relative_path
    if not script_path.exists():
        raise FileNotFoundError(f"Hook script not found: {script_path}")
    if not os.access(script_path, os.X_OK):
        raise PermissionError(f"Hook script not executable: {script_path}")

    cmd = [str(script_path)] + (args or [])
    return subprocess.run(
        cmd, cwd=cwd, capture_output=capture_output,
        text=True, timeout=timeout,
    )
```

**Verification gate:** Create `tests/test_pack_loader.py`:

```python
import pytest
import yaml
from pathlib import Path
from switchyard.pack_loader import (
    load_pack, list_packs, bootstrap_packs, reset_pack,
    check_scripts_executable, PackConfig,
)


@pytest.fixture
def packs_dir(tmp_path, monkeypatch):
    """Set up a temporary packs directory."""
    pd = tmp_path / "packs"
    pd.mkdir()
    monkeypatch.setattr("switchyard.pack_loader.PACKS_DIR", pd)
    return pd


@pytest.fixture
def builtin_dir(tmp_path, monkeypatch):
    """Set up a temporary built-in packs directory."""
    bd = tmp_path / "builtin"
    bd.mkdir()
    monkeypatch.setattr("switchyard.pack_loader.BUILTIN_PACKS_DIR", bd)
    return bd


def _create_pack(base_dir: Path, name: str, extra_yaml: dict = None) -> Path:
    """Helper to create a minimal pack directory."""
    d = base_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "scripts").mkdir(exist_ok=True)
    yaml_data = {"name": name, "description": f"Test pack {name}", **(extra_yaml or {})}
    (d / "pack.yaml").write_text(yaml.dump(yaml_data))
    return d


class TestLoadPack:
    def test_load_minimal(self, packs_dir):
        _create_pack(packs_dir, "test-echo")
        cfg = load_pack("test-echo")
        assert cfg.name == "test-echo"
        assert cfg.planning_enabled is False
        assert cfg.execution_max_workers == 2

    def test_load_with_phases(self, packs_dir):
        _create_pack(packs_dir, "coding", {
            "phases": {
                "planning": {"enabled": True, "model": "opus", "max_instances": 3},
                "execution": {"executor": "agent", "model": "sonnet", "max_workers": 4},
                "verification": {"enabled": True, "command": "pytest", "interval": 3},
            },
            "auto_fix": {"enabled": True, "max_attempts": 3},
        })
        cfg = load_pack("coding")
        assert cfg.planning_enabled is True
        assert cfg.planning_max_instances == 3
        assert cfg.execution_max_workers == 4
        assert cfg.verification_enabled is True
        assert cfg.auto_fix_enabled is True

    def test_load_missing_pack(self, packs_dir):
        with pytest.raises(ValueError, match="not found"):
            load_pack("nonexistent")

    def test_load_missing_name(self, packs_dir):
        d = packs_dir / "bad"
        d.mkdir()
        (d / "pack.yaml").write_text("{}")
        with pytest.raises(ValueError, match="missing required"):
            load_pack("bad")


class TestBootstrap:
    def test_bootstrap_copies(self, packs_dir, builtin_dir):
        _create_pack(builtin_dir, "test-echo")
        bootstrap_packs()
        assert (packs_dir / "test-echo" / "pack.yaml").exists()

    def test_bootstrap_no_overwrite(self, packs_dir, builtin_dir):
        _create_pack(builtin_dir, "test-echo")
        _create_pack(packs_dir, "test-echo", {"description": "custom"})
        bootstrap_packs()
        with open(packs_dir / "test-echo" / "pack.yaml") as f:
            data = yaml.safe_load(f)
        assert data["description"] == "custom"  # not overwritten

    def test_reset_pack(self, packs_dir, builtin_dir):
        _create_pack(builtin_dir, "test-echo", {"description": "factory"})
        _create_pack(packs_dir, "test-echo", {"description": "custom"})
        reset_pack("test-echo")
        with open(packs_dir / "test-echo" / "pack.yaml") as f:
            data = yaml.safe_load(f)
        assert data["description"] == "factory"


class TestScriptChecks:
    def test_all_executable(self, packs_dir):
        pd = _create_pack(packs_dir, "good")
        script = pd / "scripts" / "execute"
        script.write_text("#!/bin/bash\necho hi")
        script.chmod(0o755)
        assert check_scripts_executable("good") == []

    def test_non_executable(self, packs_dir):
        pd = _create_pack(packs_dir, "bad")
        script = pd / "scripts" / "execute"
        script.write_text("#!/bin/bash\necho hi")
        script.chmod(0o644)
        failures = check_scripts_executable("bad")
        assert len(failures) == 1
        assert "execute" in failures[0][0]
        assert "chmod +x" in failures[0][1]
```

Run: `python3 -m pytest tests/test_pack_loader.py -v`
All tests must pass before proceeding.

---

### Step 1.5: scheduler.py -- Constraint Graph and Eligibility

**Dependencies:** Steps 1.2, 1.3 (models and state store)

**Purpose:** Determine which tasks are eligible for dispatch based on dependency constraints. This is the Python equivalent of the `plan_is_eligible()` and `find_eligible_plan()` functions in `reference/work/orchestrate.sh`.

**Critical correctness requirement:** Study `reference/work/orchestrate.sh` lines 270-320 carefully. The eligibility rules are:
1. Task must be in `ready` status
2. Task must NOT already be running
3. ALL `depends_on` tasks must be in `done` status
4. NO `anti_affinity` tasks can be currently `active`

Selection priority: lowest `exec_order` first, then lowest task ID (alphabetical).

**File:** `switchyard/scheduler.py`

```python
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from switchyard.models import Task, TaskStatus, Constraint

logger = logging.getLogger(__name__)


def load_resolution(resolution_path: Path) -> list[Constraint]:
    """Load constraint graph from resolution.json.

    Format (design doc section 5.3):
    {
        "resolved_at": "...",
        "tasks": [
            {"task_id": "038", "depends_on": [], "anti_affinity": [], "exec_order": 1},
            ...
        ],
        "groups": [...],
        "conflicts": [],
        "notes": "..."
    }
    """
    if not resolution_path.exists():
        logger.warning("No resolution.json found at %s", resolution_path)
        return []

    with open(resolution_path) as f:
        data = json.load(f)

    constraints = []
    for entry in data.get("tasks", []):
        constraints.append(Constraint(
            task_id=entry["task_id"],
            depends_on=entry.get("depends_on", []),
            anti_affinity=entry.get("anti_affinity", []),
            exec_order=entry.get("exec_order", 1),
        ))
    return constraints


def is_task_eligible(
    task: Task,
    all_tasks: list[Task],
) -> bool:
    """Check if a task is eligible for dispatch.

    A task is eligible when:
    1. It is in 'ready' status
    2. All DEPENDS_ON tasks are 'done'
    3. No ANTI_AFFINITY tasks are 'active'

    Args:
        task: The candidate task
        all_tasks: All tasks in the session (for checking dep/AA statuses)
    """
    if task.status != TaskStatus.READY:
        return False

    # Build lookup: task_id -> status
    status_map = {t.id: t.status for t in all_tasks}

    # All hard dependencies must be done
    for dep_id in task.depends_on:
        dep_status = status_map.get(dep_id)
        if dep_status != TaskStatus.DONE:
            return False

    # No anti-affinity tasks currently active
    for aa_id in task.anti_affinity:
        aa_status = status_map.get(aa_id)
        if aa_status == TaskStatus.ACTIVE:
            return False

    return True


def find_next_eligible(all_tasks: list[Task]) -> Optional[Task]:
    """Find the highest-priority eligible task.

    Priority: lowest exec_order, then lowest task ID (alphabetical).

    Returns None if no task is eligible.
    """
    best: Optional[Task] = None
    for task in all_tasks:
        if not is_task_eligible(task, all_tasks):
            continue
        if best is None:
            best = task
        elif (task.exec_order < best.exec_order) or \
             (task.exec_order == best.exec_order and task.id < best.id):
            best = task
    return best


def detect_deadlock(all_tasks: list[Task]) -> bool:
    """Detect if the remaining tasks are deadlocked.

    Deadlock occurs when:
    - No tasks are active (no workers running)
    - There are pending tasks (not done, not blocked)
    - No pending task is eligible for dispatch

    This typically happens when remaining tasks depend on blocked tasks.
    """
    has_active = any(t.status == TaskStatus.ACTIVE for t in all_tasks)
    if has_active:
        return False  # workers are running, not deadlocked

    pending = [t for t in all_tasks if t.status not in (TaskStatus.DONE, TaskStatus.BLOCKED)]
    if not pending:
        return False  # all tasks finished, not deadlocked

    has_eligible = any(is_task_eligible(t, all_tasks) for t in pending)
    return not has_eligible


def count_pending(all_tasks: list[Task]) -> int:
    """Count tasks that are neither done nor blocked."""
    return sum(1 for t in all_tasks if t.status not in (TaskStatus.DONE, TaskStatus.BLOCKED))
```

**Verification gate:** Create `tests/test_scheduler.py`:

```python
import json
import pytest
from pathlib import Path
from switchyard.models import Task, TaskStatus, Constraint
from switchyard.scheduler import (
    is_task_eligible, find_next_eligible, detect_deadlock,
    load_resolution, count_pending,
)


def _task(tid, status=TaskStatus.READY, depends=None, anti=None, order=1):
    """Helper to create a Task with minimal boilerplate."""
    return Task(
        id=tid, session_id="s1", title=f"Task {tid}", status=status,
        depends_on=depends or [], anti_affinity=anti or [], exec_order=order,
    )


class TestEligibility:
    def test_ready_no_constraints(self):
        t = _task("001")
        assert is_task_eligible(t, [t])

    def test_not_ready(self):
        t = _task("001", status=TaskStatus.DONE)
        assert not is_task_eligible(t, [t])

    def test_dep_satisfied(self):
        dep = _task("001", status=TaskStatus.DONE)
        t = _task("002", depends=["001"])
        assert is_task_eligible(t, [dep, t])

    def test_dep_not_satisfied(self):
        dep = _task("001", status=TaskStatus.READY)
        t = _task("002", depends=["001"])
        assert not is_task_eligible(t, [dep, t])

    def test_dep_blocked(self):
        dep = _task("001", status=TaskStatus.BLOCKED)
        t = _task("002", depends=["001"])
        assert not is_task_eligible(t, [dep, t])

    def test_anti_affinity_idle(self):
        aa = _task("001", status=TaskStatus.READY)
        t = _task("002", anti=["001"])
        assert is_task_eligible(t, [aa, t])

    def test_anti_affinity_active(self):
        aa = _task("001", status=TaskStatus.ACTIVE)
        t = _task("002", anti=["001"])
        assert not is_task_eligible(t, [aa, t])

    def test_anti_affinity_done(self):
        aa = _task("001", status=TaskStatus.DONE)
        t = _task("002", anti=["001"])
        assert is_task_eligible(t, [aa, t])

    def test_mixed_constraints(self):
        """Task depends on 001 (done) and has anti-affinity with 003 (active)."""
        dep = _task("001", status=TaskStatus.DONE)
        aa = _task("003", status=TaskStatus.ACTIVE)
        t = _task("002", depends=["001"], anti=["003"])
        assert not is_task_eligible(t, [dep, t, aa])

    def test_mixed_constraints_all_clear(self):
        dep = _task("001", status=TaskStatus.DONE)
        aa = _task("003", status=TaskStatus.DONE)
        t = _task("002", depends=["001"], anti=["003"])
        assert is_task_eligible(t, [dep, t, aa])


class TestFindNextEligible:
    def test_picks_lowest_exec_order(self):
        t1 = _task("001", order=2)
        t2 = _task("002", order=1)
        result = find_next_eligible([t1, t2])
        assert result.id == "002"

    def test_picks_lowest_id_on_tie(self):
        t1 = _task("002", order=1)
        t2 = _task("001", order=1)
        result = find_next_eligible([t1, t2])
        assert result.id == "001"

    def test_skips_ineligible(self):
        dep = _task("001", status=TaskStatus.READY)
        t = _task("002", depends=["001"])
        result = find_next_eligible([dep, t])
        assert result.id == "001"

    def test_none_eligible(self):
        dep = _task("001", status=TaskStatus.ACTIVE)
        t = _task("002", depends=["001"])
        result = find_next_eligible([dep, t])
        assert result is None


class TestDeadlock:
    def test_no_deadlock_workers_active(self):
        tasks = [_task("001", status=TaskStatus.ACTIVE)]
        assert not detect_deadlock(tasks)

    def test_no_deadlock_all_done(self):
        tasks = [_task("001", status=TaskStatus.DONE)]
        assert not detect_deadlock(tasks)

    def test_deadlock_pending_but_deps_blocked(self):
        dep = _task("001", status=TaskStatus.BLOCKED)
        t = _task("002", depends=["001"])
        assert detect_deadlock([dep, t])

    def test_no_deadlock_eligible_exists(self):
        tasks = [_task("001"), _task("002")]
        assert not detect_deadlock(tasks)


class TestLoadResolution:
    def test_load_resolution_json(self, tmp_path):
        data = {
            "resolved_at": "2026-03-05T14:16:45Z",
            "tasks": [
                {"task_id": "038", "depends_on": [], "anti_affinity": [], "exec_order": 1},
                {"task_id": "040", "depends_on": [], "anti_affinity": ["041", "042"], "exec_order": 1},
                {"task_id": "041", "depends_on": ["038"], "anti_affinity": ["040"], "exec_order": 2},
            ],
            "groups": [],
            "conflicts": [],
        }
        p = tmp_path / "resolution.json"
        p.write_text(json.dumps(data))
        constraints = load_resolution(p)
        assert len(constraints) == 3
        assert constraints[1].anti_affinity == ["041", "042"]
        assert constraints[2].depends_on == ["038"]
        assert constraints[2].exec_order == 2

    def test_load_missing_file(self, tmp_path):
        constraints = load_resolution(tmp_path / "missing.json")
        assert constraints == []


class TestCountPending:
    def test_counts(self):
        tasks = [
            _task("001", status=TaskStatus.READY),
            _task("002", status=TaskStatus.ACTIVE),
            _task("003", status=TaskStatus.DONE),
            _task("004", status=TaskStatus.BLOCKED),
            _task("005", status=TaskStatus.READY),
        ]
        assert count_pending(tasks) == 3  # 001, 002, 005
```

Run: `python3 -m pytest tests/test_scheduler.py -v`
All tests must pass before proceeding.

---

---

### Step 1.6: watcher.py -- Filesystem Watcher

**Dependencies:** Step 1.1 (config.py)

**Purpose:** Poll filesystem directories for changes -- new intake files, status sidecar files written by executors, and plan file moves. This is NOT inotify/watchfiles -- it is simple polling with diffing, which is more portable and sufficient for our poll intervals.

**File:** `switchyard/watcher.py`

```python
from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DirectoryWatcher:
    """Polls a directory for file changes between calls to check().

    Tracks the set of files (by name) seen on the previous check.
    Returns new files, removed files, and the current file set.
    """

    def __init__(self, directory: Path, glob_pattern: str = "*"):
        self._directory = directory
        self._pattern = glob_pattern
        self._previous: set[str] = set()
        self._initialized = False

    @property
    def directory(self) -> Path:
        return self._directory

    def check(self) -> tuple[list[Path], list[str]]:
        """Check for changes since last call.

        Returns:
            (new_files, removed_names)
            - new_files: list of Path objects for newly appeared files
            - removed_names: list of filenames that disappeared since last check
        """
        if not self._directory.exists():
            if self._previous:
                removed = list(self._previous)
                self._previous = set()
                return [], removed
            return [], []

        current_files = {
            f.name: f for f in self._directory.glob(self._pattern)
            if f.is_file()
        }
        current_names = set(current_files.keys())

        if not self._initialized:
            # First check: treat all files as "new" but don't report removals
            self._previous = current_names
            self._initialized = True
            return [current_files[n] for n in sorted(current_names)], []

        new_names = current_names - self._previous
        removed_names = self._previous - current_names

        self._previous = current_names

        new_files = [current_files[n] for n in sorted(new_names)]
        return new_files, sorted(removed_names)

    def current_files(self) -> list[Path]:
        """Return all files currently in the directory."""
        if not self._directory.exists():
            return []
        return sorted(
            f for f in self._directory.glob(self._pattern) if f.is_file()
        )

    def reset(self) -> None:
        """Reset watcher state. Next check() will re-initialize."""
        self._previous = set()
        self._initialized = False


class StatusFileWatcher:
    """Watches a specific directory for .status sidecar files.

    Used by the orchestrator to detect when an executor has finished
    writing its status file in a worker slot directory.
    """

    def __init__(self, directory: Path):
        self._directory = directory

    def find_status_file(self) -> Optional[Path]:
        """Look for a .status file in the directory.

        Returns the path if exactly one is found, None otherwise.
        """
        if not self._directory.exists():
            return None
        status_files = list(self._directory.glob("*.status"))
        if len(status_files) == 1:
            return status_files[0]
        if len(status_files) > 1:
            logger.warning(
                "Multiple .status files in %s: %s",
                self._directory,
                [f.name for f in status_files],
            )
            # Return the most recently modified one
            return max(status_files, key=lambda f: f.stat().st_mtime)
        return None
```

**Verification gate:** Create `tests/test_watcher.py`:

```python
import pytest
from pathlib import Path
from switchyard.watcher import DirectoryWatcher, StatusFileWatcher


class TestDirectoryWatcher:
    def test_first_check_returns_all(self, tmp_path):
        d = tmp_path / "intake"
        d.mkdir()
        (d / "001_task.md").write_text("content")
        (d / "002_task.md").write_text("content")
        w = DirectoryWatcher(d, "*.md")
        new, removed = w.check()
        assert len(new) == 2
        assert removed == []

    def test_new_file_detected(self, tmp_path):
        d = tmp_path / "intake"
        d.mkdir()
        (d / "001_task.md").write_text("content")
        w = DirectoryWatcher(d, "*.md")
        w.check()  # initialize
        (d / "002_task.md").write_text("content")
        new, removed = w.check()
        assert len(new) == 1
        assert new[0].name == "002_task.md"

    def test_removed_file_detected(self, tmp_path):
        d = tmp_path / "intake"
        d.mkdir()
        f = d / "001_task.md"
        f.write_text("content")
        w = DirectoryWatcher(d, "*.md")
        w.check()  # initialize
        f.unlink()
        new, removed = w.check()
        assert new == []
        assert removed == ["001_task.md"]

    def test_no_changes(self, tmp_path):
        d = tmp_path / "intake"
        d.mkdir()
        (d / "001_task.md").write_text("content")
        w = DirectoryWatcher(d, "*.md")
        w.check()  # initialize
        new, removed = w.check()
        assert new == []
        assert removed == []

    def test_nonexistent_directory(self, tmp_path):
        w = DirectoryWatcher(tmp_path / "nope", "*.md")
        new, removed = w.check()
        assert new == []
        assert removed == []

    def test_current_files(self, tmp_path):
        d = tmp_path / "dir"
        d.mkdir()
        (d / "a.txt").write_text("a")
        (d / "b.txt").write_text("b")
        w = DirectoryWatcher(d, "*.txt")
        files = w.current_files()
        assert len(files) == 2

    def test_reset(self, tmp_path):
        d = tmp_path / "dir"
        d.mkdir()
        (d / "a.md").write_text("a")
        w = DirectoryWatcher(d, "*.md")
        w.check()  # initialize
        w.reset()
        new, _ = w.check()  # re-initialize, treats all as new
        assert len(new) == 1


class TestStatusFileWatcher:
    def test_find_single_status(self, tmp_path):
        (tmp_path / "001_task.status").write_text("STATUS: done")
        w = StatusFileWatcher(tmp_path)
        result = w.find_status_file()
        assert result is not None
        assert result.name == "001_task.status"

    def test_find_no_status(self, tmp_path):
        w = StatusFileWatcher(tmp_path)
        assert w.find_status_file() is None

    def test_find_nonexistent_dir(self, tmp_path):
        w = StatusFileWatcher(tmp_path / "nope")
        assert w.find_status_file() is None

    def test_find_multiple_returns_newest(self, tmp_path):
        import time
        (tmp_path / "old.status").write_text("STATUS: blocked")
        time.sleep(0.05)
        (tmp_path / "new.status").write_text("STATUS: done")
        w = StatusFileWatcher(tmp_path)
        result = w.find_status_file()
        assert result.name == "new.status"
```

Run: `python3 -m pytest tests/test_watcher.py -v`
All tests must pass before proceeding.

---

### Step 1.7: worker_manager.py -- Subprocess Lifecycle

**Dependencies:** Steps 1.1, 1.2, 1.4, 1.6 (config, models, pack_loader, watcher)

**Purpose:** Manage worker slot subprocesses. Each slot holds at most one running subprocess. The manager handles launching (via pack hooks), monitoring (PID alive check, stdout/stderr capture, idle detection), and killing (SIGTERM then SIGKILL).

**Critical reference:** Study `reference/work/orchestrate.sh` lines 350-420 (dispatch_plan) and 647-758 (handle_worker_completion). Note how:
- The plan file is moved from `ready/` to `workers/<slot>/` atomically
- The worktree is created before launching the executor
- The subprocess runs in the background with stdout piped to a log file
- Completion is detected by checking if the PID is still alive
- Status sidecar is read from the worker slot directory after completion

**File:** `switchyard/worker_manager.py`

```python
from __future__ import annotations
import logging
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, IO

from switchyard.config import session_subdirs
from switchyard.models import Task, WorkerSlot, WorkerStatus, StatusSidecar
from switchyard.watcher import StatusFileWatcher

logger = logging.getLogger(__name__)

# Grace period after SIGTERM before SIGKILL (seconds)
KILL_GRACE_PERIOD = 5


class ManagedWorker:
    """Represents one worker slot and its running subprocess (if any)."""

    def __init__(self, session_id: str, slot_number: int, log_dir: Path):
        self.session_id = session_id
        self.slot_number = slot_number
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.process: Optional[subprocess.Popen] = None
        self.task: Optional[Task] = None
        self.task_started_at: Optional[datetime] = None
        self.last_output_at: Optional[datetime] = None
        self.log_file_handle: Optional[IO] = None
        self.log_path: Optional[Path] = None
        self.workspace_path: Optional[Path] = None

    @property
    def is_idle(self) -> bool:
        return self.process is None

    @property
    def is_alive(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    @property
    def elapsed_seconds(self) -> float:
        if self.task_started_at is None:
            return 0.0
        return (datetime.now(timezone.utc) - self.task_started_at).total_seconds()

    @property
    def idle_seconds(self) -> float:
        """Seconds since last output was captured."""
        if self.last_output_at is None:
            return self.elapsed_seconds
        return (datetime.now(timezone.utc) - self.last_output_at).total_seconds()

    def launch(
        self, task: Task, cmd: list[str], cwd: Path,
        workspace_path: Optional[Path] = None,
        env: Optional[dict] = None,
    ) -> None:
        """Launch a subprocess for a task in this worker slot.

        Args:
            task: The task being executed
            cmd: Command and arguments for subprocess
            cwd: Working directory for the subprocess
            workspace_path: Isolation workspace path (for cleanup later)
            env: Environment variables (merged with os.environ)
        """
        if not self.is_idle:
            raise RuntimeError(
                f"Worker slot {self.slot_number} is not idle "
                f"(running task {self.task.id if self.task else '?'})"
            )

        self.task = task
        self.workspace_path = workspace_path
        now = datetime.now(timezone.utc)
        self.task_started_at = now
        self.last_output_at = now

        # Open log file
        log_name = f"{task.id}_{task.plan_filename.replace('.plan.md', '')}.log" if task.plan_filename else f"{task.id}.log"
        self.log_path = self.log_dir / log_name
        self.log_file_handle = open(self.log_path, "w")

        # Merge environment
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

        logger.info(
            "Slot %d: launching task %s (cmd=%s, cwd=%s)",
            self.slot_number, task.id, cmd[0] if cmd else "?", cwd,
        )

        self.process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=self.log_file_handle,
            stderr=subprocess.STDOUT,
            env=proc_env,
            start_new_session=True,  # so we can kill the process group
        )

    def poll_output(self) -> list[str]:
        """Read new lines from the log file.

        Updates last_output_at if any lines are read.
        Returns the new lines (for progress parsing and WebSocket broadcast).
        """
        if self.log_path is None or not self.log_path.exists():
            return []

        # Flush the log file so we can read what's been written
        if self.log_file_handle and not self.log_file_handle.closed:
            try:
                self.log_file_handle.flush()
            except (ValueError, OSError):
                pass

        # Read new content from log file
        # We track position with a separate read handle
        if not hasattr(self, '_read_handle') or self._read_handle is None:
            self._read_handle = open(self.log_path, "r")
            self._read_pos = 0

        self._read_handle.seek(self._read_pos)
        new_content = self._read_handle.read()
        self._read_pos = self._read_handle.tell()

        if not new_content:
            return []

        self.last_output_at = datetime.now(timezone.utc)
        return new_content.splitlines()

    def check_finished(self) -> bool:
        """Check if the subprocess has exited. Does NOT block."""
        if self.process is None:
            return True
        return self.process.poll() is not None

    def exit_code(self) -> Optional[int]:
        if self.process is None:
            return None
        return self.process.poll()

    def kill(self, reason: str = "") -> None:
        """Kill the worker subprocess. SIGTERM first, then SIGKILL after grace period."""
        if self.process is None or not self.is_alive:
            logger.debug("Slot %d: kill() called but process not alive", self.slot_number)
            return

        pid = self.process.pid
        logger.warning(
            "Slot %d: killing task %s (PID %d, reason: %s)",
            self.slot_number, self.task.id if self.task else "?", pid, reason,
        )

        try:
            # Kill the entire process group (catches child processes)
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

        # Wait for grace period
        deadline = time.monotonic() + KILL_GRACE_PERIOD
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                logger.info("Slot %d: process exited after SIGTERM", self.slot_number)
                return
            time.sleep(0.5)

        # Force kill
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        self.process.wait(timeout=5)
        logger.info("Slot %d: process killed with SIGKILL", self.slot_number)

    def cleanup(self) -> None:
        """Clean up after task completion or kill. Resets slot to idle state."""
        if self.log_file_handle and not self.log_file_handle.closed:
            self.log_file_handle.close()
        if hasattr(self, '_read_handle') and self._read_handle and not self._read_handle.closed:
            self._read_handle.close()
            self._read_handle = None
            self._read_pos = 0

        self.process = None
        self.task = None
        self.task_started_at = None
        self.last_output_at = None
        self.log_file_handle = None
        self.workspace_path = None
        # Keep self.log_path set so it can be moved to done/ or blocked/

    def read_status_sidecar(self, slot_dir: Path) -> StatusSidecar:
        """Read the status sidecar file from the worker slot directory."""
        watcher = StatusFileWatcher(slot_dir)
        status_path = watcher.find_status_file()
        if status_path is None:
            return StatusSidecar()  # defaults to blocked
        return StatusSidecar.from_file(status_path)


class WorkerManager:
    """Manages all worker slots for a session."""

    def __init__(self, session_id: str, num_workers: int, base_log_dir: Path):
        self.session_id = session_id
        self.workers: list[ManagedWorker] = []
        for i in range(num_workers):
            slot_log_dir = base_log_dir / "workers"
            self.workers.append(ManagedWorker(session_id, i, slot_log_dir))

    def idle_slots(self) -> list[ManagedWorker]:
        return [w for w in self.workers if w.is_idle]

    def active_slots(self) -> list[ManagedWorker]:
        return [w for w in self.workers if not w.is_idle]

    def finished_slots(self) -> list[ManagedWorker]:
        """Return active workers whose subprocess has exited."""
        return [w for w in self.workers if not w.is_idle and w.check_finished()]

    def kill_all(self, reason: str = "session abort") -> None:
        """Kill all active worker subprocesses."""
        for w in self.active_slots():
            w.kill(reason)

    def cleanup_all(self) -> None:
        """Cleanup all slots (after kill or completion)."""
        for w in self.workers:
            if not w.is_idle:
                w.cleanup()
```

**Verification gate:** Create `tests/test_worker_manager.py`:

```python
import os
import sys
import time
import pytest
from pathlib import Path
from datetime import datetime, timezone

from switchyard.worker_manager import ManagedWorker, WorkerManager
from switchyard.models import Task, TaskStatus, StatusSidecar


@pytest.fixture
def log_dir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def worker(log_dir):
    return ManagedWorker(session_id="s1", slot_number=0, log_dir=log_dir)


@pytest.fixture
def sample_task():
    return Task(
        id="001", session_id="s1", title="Echo Test",
        status=TaskStatus.ACTIVE, plan_filename="001_echo.plan.md",
    )


class TestManagedWorker:
    def test_starts_idle(self, worker):
        assert worker.is_idle
        assert not worker.is_alive

    def test_launch_and_complete(self, worker, sample_task, tmp_path):
        """Launch a simple echo command and verify it completes."""
        worker.launch(
            task=sample_task,
            cmd=[sys.executable, "-c", "print('hello from worker')"],
            cwd=tmp_path,
        )
        assert not worker.is_idle
        # Wait for completion (should be near-instant)
        for _ in range(20):
            if worker.check_finished():
                break
            time.sleep(0.1)
        assert worker.check_finished()
        assert worker.exit_code() == 0

        # Check log was written
        lines = worker.poll_output()
        assert any("hello from worker" in l for l in lines)

        worker.cleanup()
        assert worker.is_idle

    def test_launch_when_busy_raises(self, worker, sample_task, tmp_path):
        worker.launch(
            task=sample_task,
            cmd=[sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path,
        )
        with pytest.raises(RuntimeError, match="not idle"):
            worker.launch(task=sample_task, cmd=["echo"], cwd=tmp_path)
        worker.kill("test cleanup")
        worker.cleanup()

    def test_kill(self, worker, sample_task, tmp_path):
        """Launch a long-running process and verify kill works."""
        worker.launch(
            task=sample_task,
            cmd=[sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
        )
        assert worker.is_alive
        worker.kill("test")
        assert worker.check_finished()
        worker.cleanup()
        assert worker.is_idle

    def test_elapsed_seconds(self, worker, sample_task, tmp_path):
        worker.launch(
            task=sample_task,
            cmd=[sys.executable, "-c", "import time; time.sleep(0.2)"],
            cwd=tmp_path,
        )
        time.sleep(0.1)
        assert worker.elapsed_seconds >= 0.1
        worker.kill("cleanup")
        worker.cleanup()

    def test_read_status_sidecar(self, worker, tmp_path):
        (tmp_path / "001_echo.status").write_text(
            "STATUS: done\nCOMMITS: abc123\nTESTS_RAN: targeted\nTEST_RESULT: pass\n"
        )
        sidecar = worker.read_status_sidecar(tmp_path)
        assert sidecar.status == "done"
        assert sidecar.commits == "abc123"

    def test_read_status_sidecar_missing(self, worker, tmp_path):
        sidecar = worker.read_status_sidecar(tmp_path)
        assert sidecar.status == "blocked"  # default


class TestWorkerManager:
    def test_initial_state(self, tmp_path):
        mgr = WorkerManager("s1", 3, tmp_path / "logs")
        assert len(mgr.workers) == 3
        assert len(mgr.idle_slots()) == 3
        assert len(mgr.active_slots()) == 0

    def test_launch_reduces_idle(self, tmp_path):
        mgr = WorkerManager("s1", 2, tmp_path / "logs")
        task = Task(id="001", session_id="s1", title="T", status=TaskStatus.ACTIVE, plan_filename="001_t.plan.md")
        mgr.workers[0].launch(
            task=task,
            cmd=[sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=tmp_path,
        )
        assert len(mgr.idle_slots()) == 1
        assert len(mgr.active_slots()) == 1
        mgr.kill_all("test cleanup")
        mgr.cleanup_all()

    def test_kill_all(self, tmp_path):
        mgr = WorkerManager("s1", 2, tmp_path / "logs")
        for i in range(2):
            task = Task(id=f"00{i}", session_id="s1", title=f"T{i}", status=TaskStatus.ACTIVE, plan_filename=f"00{i}_t.plan.md")
            mgr.workers[i].launch(
                task=task,
                cmd=[sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=tmp_path,
            )
        assert len(mgr.active_slots()) == 2
        mgr.kill_all("abort")
        mgr.cleanup_all()
        assert len(mgr.idle_slots()) == 2
```

Run: `python3 -m pytest tests/test_worker_manager.py -v`
All tests must pass. Pay special attention to the `test_kill` test -- if the process is not properly killed, this test will hang. If it hangs, debug the kill logic before proceeding.

---

### Step 1.8: orchestrator.py -- Main Orchestration Loop

**Dependencies:** ALL prior steps (1.1-1.7). This is the integration point.

**Purpose:** The orchestrator is the brain. It runs in a background thread (for Phase 3 web UI) or in the main thread (for Phase 1 CLI). It implements the main polling loop from `reference/work/orchestrate.sh`:

1. Recovery pass (on startup)
2. Main loop:
   a. Check for finished workers, collect results
   b. Move plan files to `done/` or `blocked/`
   c. Run pack `isolate_end` hook if applicable
   d. Check if verification is due (Phase 2 -- stub for now)
   e. Dispatch eligible tasks to idle slots
   f. Timeout enforcement (idle timeout, task max timeout, session max timeout)
   g. Check exit conditions (all done? deadlock?)
   h. Sleep for poll interval

**Critical correctness:** The state transition protocol (Section 0.4) must be followed for EVERY state change: filesystem move first, then DB update, then WebSocket broadcast.

**Recovery logic** (design doc Section 10): Before entering the main loop, scan the filesystem and reconcile. This is the Python equivalent of `recover_from_crash()` in `reference/work/orchestrate.sh` (lines 114-162).

**File:** `switchyard/orchestrator.py`

This is a large module. Implement it in this order:

**Part A: Recovery and initialization**

```python
from __future__ import annotations
import asyncio
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

from switchyard.config import (
    session_dir, session_subdirs, SessionConfig,
    PROGRESS_PATTERN,
)
from switchyard.models import (
    Session, SessionStatus, Task, TaskStatus,
    WorkerSlot, WorkerStatus, Event, EventType,
    StatusSidecar, Constraint,
)
from switchyard.state import StateStore
from switchyard.scheduler import (
    find_next_eligible, detect_deadlock, count_pending,
    load_resolution,
)
from switchyard.worker_manager import WorkerManager, ManagedWorker
from switchyard.pack_loader import load_pack, pack_dir, invoke_hook, PackConfig

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestration engine. Runs the dispatch loop.

    Can run in foreground (blocking) or be started in a background thread
    for web UI mode.
    """

    def __init__(
        self,
        session_id: str,
        store: StateStore,
        event_loop: Optional[asyncio.AbstractEventLoop] = None,
        ws_broadcast: Optional[Callable] = None,
    ):
        self.session_id = session_id
        self.store = store
        self._event_loop = event_loop  # for async bridge to WebSocket
        self._ws_broadcast = ws_broadcast
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Loaded at start
        self._session: Optional[Session] = None
        self._config: Optional[SessionConfig] = None
        self._pack: Optional[PackConfig] = None
        self._worker_mgr: Optional[WorkerManager] = None
        self._dirs: Optional[dict[str, Path]] = None

        # Session stats
        self._completed_since_verify = 0
        self._total_completed = 0
        self._total_blocked = 0

    # --- Lifecycle ---

    def start_background(self) -> threading.Thread:
        """Start the orchestrator in a background thread."""
        self._thread = threading.Thread(
            target=self._run_with_error_handling,
            name=f"orchestrator-{self.session_id}",
            daemon=True,
        )
        self._thread.start()
        return self._thread

    def stop(self, timeout: float = 30) -> None:
        """Signal the orchestrator to stop and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def run_foreground(self) -> None:
        """Run the orchestrator in the calling thread (blocking)."""
        self._run_with_error_handling()

    def _run_with_error_handling(self) -> None:
        """Top-level error handler for the orchestration loop."""
        try:
            self._initialize()
            self._run_recovery()
            self._dispatch_loop()
        except Exception:
            logger.exception("Orchestrator crashed for session %s", self.session_id)
            self._add_event(EventType.ERROR, message="Orchestrator crashed unexpectedly")
            # Mark session as aborted if it was running
            self.store.update_session_status(
                self.session_id, SessionStatus.ABORTED,
                abort_reason="Orchestrator crash (check logs)",
                completed_at=datetime.now(timezone.utc),
            )
        finally:
            if self._worker_mgr:
                self._worker_mgr.kill_all("orchestrator shutdown")
                self._worker_mgr.cleanup_all()

    def _initialize(self) -> None:
        """Load session, config, pack, create worker manager."""
        self._session = self.store.get_session(self.session_id)
        if not self._session:
            raise ValueError(f"Session {self.session_id} not found")

        self._config = SessionConfig(**json.loads(self._session.config_json))
        self._pack = load_pack(self._config.pack_name)
        self._dirs = session_subdirs(self.session_id)

        # Ensure directories exist
        for d in self._dirs.values():
            d.mkdir(parents=True, exist_ok=True)

        # Create worker slots directory structure
        workers_base = self._dirs["workers"]
        for i in range(self._config.num_workers):
            (workers_base / str(i)).mkdir(parents=True, exist_ok=True)

        # Initialize worker manager
        self._worker_mgr = WorkerManager(
            self.session_id,
            self._config.num_workers,
            self._dirs["logs"],
        )

        # Update DB worker slots
        self.store.create_worker_slots(self.session_id, self._config.num_workers)

        logger.info(
            "Orchestrator initialized: session=%s, pack=%s, workers=%d",
            self.session_id, self._config.pack_name, self._config.num_workers,
        )

    def _run_recovery(self) -> None:
        """Recovery pass: reconcile filesystem with DB, clean up orphans.

        Design doc Section 10.2: Detect orphaned worker slots, check for
        completed-but-not-collected work, revert incomplete work.

        Reference: orchestrate.sh lines 114-162 (recover_from_crash).
        """
        logger.info("Running recovery pass for session %s", self.session_id)

        workers_base = self._dirs["workers"]
        ready_dir = self._dirs["ready"]

        # Check each worker slot directory for orphaned plan files
        for slot_dir in sorted(workers_base.iterdir()):
            if not slot_dir.is_dir():
                continue
            try:
                slot_num = int(slot_dir.name)
            except ValueError:
                continue

            plan_files = list(slot_dir.glob("*.plan.md"))
            if not plan_files:
                continue

            for plan_file in plan_files:
                task_id = self.store._extract_task_id_from_filename(plan_file.name)
                logger.info(
                    "Recovery: found orphaned plan %s in slot %d",
                    plan_file.name, slot_num,
                )

                # Check for completed-but-not-collected work
                status_file = None
                for sf in slot_dir.glob("*.status"):
                    status_file = sf
                    break

                if status_file:
                    sidecar = StatusSidecar.from_file(status_file)
                    if sidecar.status == "done":
                        # Completed work: move to done/
                        logger.info(
                            "Recovery: task %s completed but not collected, moving to done/",
                            task_id,
                        )
                        self._move_to_done(plan_file, status_file, slot_dir)
                        continue

                # Incomplete work: move plan back to ready/
                logger.info(
                    "Recovery: task %s incomplete, returning to ready/",
                    task_id,
                )
                dest = ready_dir / plan_file.name
                os.rename(str(plan_file), str(dest))

                # Clean up status and log files from the slot
                for f in slot_dir.glob("*.status"):
                    f.unlink()
                for f in slot_dir.glob("*.log"):
                    f.unlink()

        # Reconcile DB from filesystem
        self.store.reconcile_tasks_from_filesystem(self.session_id)
        logger.info("Recovery pass complete")

    # --- Main dispatch loop ---

    def _dispatch_loop(self) -> None:
        """The main polling loop.

        Reference: orchestrate.sh lines 962-1056.
        """
        # Mark session as running
        self.store.update_session_status(
            self.session_id, SessionStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        self._add_event(EventType.SESSION_STARTED, message="Dispatch loop started")

        logger.info(
            "Dispatch loop started: workers=%d, poll=%ds, idle_timeout=%ds",
            self._config.num_workers, self._config.poll_interval,
            self._config.task_idle_timeout,
        )

        while not self._stop_event.is_set():
            session = self.store.get_session(self.session_id)
            if session.status == SessionStatus.PAUSED:
                time.sleep(self._config.poll_interval)
                continue
            if session.status in (SessionStatus.COMPLETED, SessionStatus.ABORTED):
                break

            # Step 1: Check for finished workers
            self._collect_finished_workers()

            # Step 2: Timeout enforcement
            self._enforce_timeouts()

            # Step 3: Dispatch eligible tasks to idle slots
            self._dispatch_eligible()

            # Step 4: Check exit conditions
            all_tasks = self.store.list_tasks(self.session_id)
            pending = count_pending(all_tasks)
            active_count = len(self._worker_mgr.active_slots())

            if pending == 0 and active_count == 0:
                # All done
                self._complete_session()
                break

            if active_count == 0 and pending > 0:
                if detect_deadlock(all_tasks):
                    logger.error(
                        "Deadlock detected: %d pending tasks, no eligible, no active workers",
                        pending,
                    )
                    self._add_event(
                        EventType.ERROR,
                        message=f"Deadlock: {pending} tasks pending but none eligible",
                    )
                    self.store.update_session_status(
                        self.session_id, SessionStatus.ABORTED,
                        abort_reason=f"Deadlock: {pending} pending tasks depend on blocked tasks",
                        completed_at=datetime.now(timezone.utc),
                    )
                    break

            # Step 5: Broadcast state update via WebSocket
            self._broadcast_state()

            # Sleep
            self._stop_event.wait(timeout=self._config.poll_interval)

    def _collect_finished_workers(self) -> None:
        """Check each active worker and collect results for any that finished."""
        for worker in self._worker_mgr.finished_slots():
            self._handle_worker_completion(worker)

    def _handle_worker_completion(self, worker: ManagedWorker) -> None:
        """Process a completed worker: read sidecar, move files, update state.

        Reference: orchestrate.sh lines 647-758 (handle_worker_completion).
        """
        task = worker.task
        slot = worker.slot_number
        slot_dir = self._dirs["workers"] / str(slot)

        logger.info("Slot %d finished: task %s (exit code %s)", slot, task.id, worker.exit_code())

        # Read status sidecar
        sidecar = worker.read_status_sidecar(slot_dir)

        if sidecar.status == "done":
            # Success path
            logger.info("Task %s succeeded", task.id)

            # Move files: filesystem first, then DB
            plan_files = list(slot_dir.glob("*.plan.md"))
            status_files = list(slot_dir.glob("*.status"))
            log_files = list(slot_dir.glob("*.log"))

            done_dir = self._dirs["done"]
            for f in plan_files + status_files + log_files:
                dest = done_dir / f.name
                os.rename(str(f), str(dest))

            # Also move the worker's main log file
            if worker.log_path and worker.log_path.exists():
                dest = done_dir / worker.log_path.name
                # Close handle first
                worker.cleanup()
                if worker.log_path.exists():
                    shutil.move(str(worker.log_path), str(dest))
            else:
                worker.cleanup()

            # Update DB
            now = datetime.now(timezone.utc)
            self.store.update_task_status(
                self.session_id, task.id, TaskStatus.DONE,
                expected_status=TaskStatus.ACTIVE,
                completed_at=now, worker_slot=None,
            )
            self.store.update_worker_slot(
                self.session_id, slot, WorkerStatus.IDLE,
            )
            self._add_event(
                EventType.TASK_COMPLETED, task_id=task.id,
                worker_slot=slot,
                message=f"Task completed (commits: {sidecar.commits})",
            )
            self._total_completed += 1
            self._completed_since_verify += 1
        else:
            # Failure path
            reason = sidecar.blocked_reason or f"Task failed (exit code {worker.exit_code()})"
            logger.warning("Task %s failed: %s", task.id, reason)

            # Move files to blocked/
            blocked_dir = self._dirs["blocked"]
            for f in list(slot_dir.glob("*.plan.md")) + list(slot_dir.glob("*.status")):
                dest = blocked_dir / f.name
                os.rename(str(f), str(dest))

            if worker.log_path and worker.log_path.exists():
                dest = blocked_dir / worker.log_path.name
                worker.cleanup()
                if worker.log_path.exists():
                    shutil.move(str(worker.log_path), str(dest))
            else:
                worker.cleanup()

            # Update DB
            now = datetime.now(timezone.utc)
            self.store.update_task_status(
                self.session_id, task.id, TaskStatus.BLOCKED,
                expected_status=TaskStatus.ACTIVE,
                completed_at=now, worker_slot=None,
                blocked_reason=reason,
            )
            self.store.update_worker_slot(
                self.session_id, slot, WorkerStatus.IDLE,
            )
            self._add_event(
                EventType.TASK_BLOCKED, task_id=task.id,
                worker_slot=slot, message=reason,
            )
            self._total_blocked += 1

    def _dispatch_eligible(self) -> None:
        """Dispatch eligible tasks to idle worker slots.

        Reference: orchestrate.sh lines 980-989.
        """
        for worker in self._worker_mgr.idle_slots():
            all_tasks = self.store.list_tasks(self.session_id)
            eligible = find_next_eligible(all_tasks)
            if eligible is None:
                break  # no more eligible tasks

            try:
                self._dispatch_task(worker, eligible)
            except Exception:
                logger.exception("Failed to dispatch task %s to slot %d", eligible.id, worker.slot_number)
                break

    def _dispatch_task(self, worker: ManagedWorker, task: Task) -> None:
        """Dispatch a single task to a worker slot.

        1. Move plan file from ready/ to workers/<slot>/ (filesystem first)
        2. Invoke pack's isolate_start hook (if isolation enabled)
        3. Build the executor command
        4. Launch subprocess
        5. Update DB
        """
        slot = worker.slot_number
        slot_dir = self._dirs["workers"] / str(slot)
        ready_dir = self._dirs["ready"]

        # Find plan file in ready/
        plan_file = None
        for f in ready_dir.glob("*.plan.md"):
            fid = self.store._extract_task_id_from_filename(f.name)
            if fid == task.id:
                plan_file = f
                break

        if plan_file is None:
            raise FileNotFoundError(f"Plan file for task {task.id} not found in {ready_dir}")

        # Step 1: Move plan file to worker slot (atomic filesystem operation)
        dest_plan = slot_dir / plan_file.name
        os.rename(str(plan_file), str(dest_plan))
        logger.info("Moved %s to slot %d", plan_file.name, slot)

        # Step 2: Isolation setup (if configured)
        workspace = slot_dir  # default: work in the slot directory
        if self._pack.isolation_type != "none" and self._pack.isolation_setup:
            try:
                result = invoke_hook(
                    self._pack.name, self._pack.isolation_setup,
                    args=[str(slot), task.id, str(session_dir(self.session_id))],
                    timeout=60,
                )
                if result.returncode == 0 and result.stdout.strip():
                    workspace = Path(result.stdout.strip())
                    logger.info("Isolation workspace for task %s: %s", task.id, workspace)
                else:
                    logger.error("isolate_start failed for task %s: %s", task.id, result.stderr)
                    # Return plan to ready
                    os.rename(str(dest_plan), str(plan_file))
                    return
            except Exception:
                logger.exception("isolate_start hook failed for task %s", task.id)
                os.rename(str(dest_plan), str(plan_file))
                return

        # Step 3: Build executor command
        if self._pack.execution_executor == "shell":
            if not self._pack.execution_command:
                raise ValueError(f"Pack {self._pack.name} has shell executor but no command")
            script_path = pack_dir(self._pack.name) / self._pack.execution_command
            cmd = [str(script_path), str(dest_plan), str(workspace)]
        elif self._pack.execution_executor == "agent":
            # Agent executor: build claude CLI command (Phase 2)
            # For now, fall back to shell
            raise NotImplementedError("Agent executor not yet implemented (Phase 2)")
        else:
            raise ValueError(f"Unknown executor type: {self._pack.execution_executor}")

        # Step 4: Launch subprocess
        env_vars = self._config.env_vars.copy()
        worker.launch(
            task=task, cmd=cmd, cwd=workspace,
            workspace_path=workspace, env=env_vars,
        )

        # Step 5: Update DB
        now = datetime.now(timezone.utc)
        self.store.update_task_status(
            self.session_id, task.id, TaskStatus.ACTIVE,
            expected_status=TaskStatus.READY,
            worker_slot=slot, started_at=now,
        )
        self.store.update_worker_slot(
            self.session_id, slot, WorkerStatus.ACTIVE,
            current_task_id=task.id, pid=worker.process.pid,
        )
        self._add_event(
            EventType.TASK_DISPATCHED, task_id=task.id,
            worker_slot=slot,
            message=f"Dispatched to slot {slot}",
        )

    def _enforce_timeouts(self) -> None:
        """Check each active worker for idle and hard timeouts.

        Design doc Section 7.4.
        Reference: orchestrate.sh lines (timeout logic in the main loop).
        """
        for worker in self._worker_mgr.active_slots():
            if worker.task is None:
                continue

            idle_secs = worker.idle_seconds
            wall_secs = worker.elapsed_seconds
            task_idle = self._config.task_idle_timeout
            task_max = self._config.task_max_timeout

            # Poll output to update last_output_at
            new_lines = worker.poll_output()
            if new_lines:
                self._parse_progress(worker, new_lines)
                idle_secs = worker.idle_seconds  # recalculate after poll

            # Idle timeout
            if task_idle > 0 and idle_secs >= task_idle:
                reason = f"Killed: no output for {int(idle_secs)}s (timeout: {task_idle}s)"
                worker.kill(reason)
                self._add_event(
                    EventType.TIMEOUT_KILL, task_id=worker.task.id,
                    worker_slot=worker.slot_number, message=reason,
                )
            elif task_idle > 0 and idle_secs >= task_idle * 0.8:
                # Warning at 80% threshold
                self._add_event(
                    EventType.TIMEOUT_WARNING, task_id=worker.task.id,
                    worker_slot=worker.slot_number,
                    message=f"No output for {int(idle_secs)}s (timeout at {task_idle}s)",
                )

            # Hard timeout
            if task_max > 0 and wall_secs >= task_max:
                reason = f"Killed: exceeded max task time {task_max}s"
                worker.kill(reason)
                self._add_event(
                    EventType.TIMEOUT_KILL, task_id=worker.task.id,
                    worker_slot=worker.slot_number, message=reason,
                )

        # Session timeout
        session_max = self._config.session_max_timeout
        if session_max > 0:
            session = self.store.get_session(self.session_id)
            if session.started_at:
                session_elapsed = (datetime.now(timezone.utc) - session.started_at).total_seconds()
                if session_elapsed >= session_max:
                    logger.error("Session timeout exceeded (%ds)", session_max)
                    self._worker_mgr.kill_all("session timeout")
                    self.store.update_session_status(
                        self.session_id, SessionStatus.ABORTED,
                        abort_reason=f"Session timeout exceeded ({session_max}s)",
                        completed_at=datetime.now(timezone.utc),
                    )
                    self._stop_event.set()

    def _parse_progress(self, worker: ManagedWorker, lines: list[str]) -> None:
        """Parse progress markers from log output.

        Format: ##PROGRESS## <task_id> | Phase: <name> | <N>/<total>
        Detail: ##PROGRESS## <task_id> | Detail: <message>
        """
        for line in lines:
            if PROGRESS_PATTERN not in line:
                continue
            try:
                # Strip everything before the marker
                _, _, payload = line.partition(PROGRESS_PATTERN)
                parts = [p.strip() for p in payload.split("|")]
                if len(parts) < 2:
                    continue

                task_id = parts[0]

                if "Phase:" in parts[1]:
                    phase_name = parts[1].split("Phase:")[1].strip()
                    if len(parts) >= 3 and "/" in parts[2]:
                        num_str, total_str = parts[2].split("/")
                        phase_num = int(num_str.strip())
                        phase_total = int(total_str.strip())
                    else:
                        phase_num = None
                        phase_total = None

                    self.store.update_task_status(
                        self.session_id, task_id, TaskStatus.ACTIVE,
                        phase=phase_name, phase_num=phase_num, phase_total=phase_total,
                    )

                elif "Detail:" in parts[1]:
                    detail_msg = parts[1].split("Detail:")[1].strip()
                    self.store.update_task_status(
                        self.session_id, task_id, TaskStatus.ACTIVE,
                        detail=detail_msg,
                    )

            except (ValueError, IndexError):
                logger.debug("Failed to parse progress line: %s", line)

    def _complete_session(self) -> None:
        """Mark session as completed and run post-completion trimming."""
        now = datetime.now(timezone.utc)
        self.store.update_session_status(
            self.session_id, SessionStatus.COMPLETED,
            completed_at=now,
        )
        self._add_event(
            EventType.SESSION_COMPLETED,
            message=f"Completed: {self._total_completed} done, {self._total_blocked} blocked",
        )

        # Post-completion trimming (design doc Section 5.1)
        if self._total_blocked == 0:
            self._trim_session_directory()

        logger.info(
            "Session %s completed: %d done, %d blocked",
            self.session_id, self._total_completed, self._total_blocked,
        )

    def _trim_session_directory(self) -> None:
        """Trim successful session to minimal metadata.

        Design doc Section 5.1: Keep summary.json, resolution.json, logs/session.log.
        Delete everything else.
        """
        base = session_dir(self.session_id)

        # Write summary.json
        session = self.store.get_session(self.session_id)
        tasks = self.store.list_tasks(self.session_id)
        summary = {
            "session_id": session.id,
            "name": session.name,
            "pack": session.pack_name,
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            "total_tasks": len(tasks),
            "completed": self._total_completed,
            "blocked": self._total_blocked,
            "tasks": [
                {"id": t.id, "title": t.title, "status": t.status.value}
                for t in tasks
            ],
        }
        (base / "summary.json").write_text(json.dumps(summary, indent=2))

        # Keep: summary.json, resolution.json, logs/session.log
        # Delete: everything else
        keep = {"summary.json", "resolution.json", "logs"}
        for item in base.iterdir():
            if item.name in keep:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        # In logs/, keep only session.log
        logs_dir = base / "logs"
        if logs_dir.exists():
            for item in logs_dir.iterdir():
                if item.name == "session.log":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        logger.info("Trimmed session directory for %s", self.session_id)

    def _move_to_done(self, plan_file: Path, status_file: Path, slot_dir: Path) -> None:
        """Move plan + status + logs from a worker slot to done/."""
        done_dir = self._dirs["done"]
        os.rename(str(plan_file), str(done_dir / plan_file.name))
        os.rename(str(status_file), str(done_dir / status_file.name))
        for log_file in slot_dir.glob("*.log"):
            shutil.move(str(log_file), str(done_dir / log_file.name))

    # --- Helpers ---

    def _add_event(self, event_type: EventType, task_id: str = None,
                   worker_slot: int = None, message: str = "") -> None:
        self.store.add_event(Event(
            session_id=self.session_id,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            task_id=task_id,
            worker_slot=worker_slot,
            message=message,
        ))

    def _broadcast_state(self) -> None:
        """Broadcast current state via WebSocket (if connected)."""
        if self._ws_broadcast and self._event_loop:
            try:
                # Build state dict for WebSocket push
                session = self.store.get_session(self.session_id)
                counts = self.store.pipeline_counts(self.session_id)
                slots = self.store.get_worker_slots(self.session_id)

                state = {
                    "type": "state_update",
                    "data": {
                        "session": {
                            "status": session.status.value,
                            "elapsed": (
                                datetime.now(timezone.utc) - session.started_at
                            ).total_seconds() if session.started_at else 0,
                        },
                        "pipeline": counts,
                        "workers": [
                            {
                                "slot": s.slot_number,
                                "status": s.status.value,
                                "task_id": s.current_task_id,
                            }
                            for s in slots
                        ],
                    },
                }
                asyncio.run_coroutine_threadsafe(
                    self._ws_broadcast(state), self._event_loop,
                )
            except Exception:
                logger.debug("Failed to broadcast state update", exc_info=True)
```

**Verification gate:** Create `tests/test_orchestrator.py`. This is the critical integration test for Phase 1.

```python
"""Integration tests for the Orchestrator.

These tests create a real session with filesystem directories and a SQLite DB,
run the orchestrator, and verify correct behavior end-to-end.
"""
import json
import os
import sys
import time
import pytest
from datetime import datetime, timezone
from pathlib import Path

from switchyard.config import SessionConfig, session_subdirs
from switchyard.models import (
    Session, SessionStatus, Task, TaskStatus, EventType,
)
from switchyard.state import StateStore
from switchyard.orchestrator import Orchestrator


@pytest.fixture
def setup_session(tmp_path, monkeypatch):
    """Create a fully set up session with DB, directories, and test-echo pack."""
    # Paths
    home = tmp_path / ".switchyard"
    sessions = home / "sessions"
    packs = home / "packs"
    db_path = home / "switchyard.db"

    # Monkeypatch all config paths
    monkeypatch.setattr("switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("switchyard.config.SESSIONS_DIR", sessions)
    monkeypatch.setattr("switchyard.config.PACKS_DIR", packs)
    monkeypatch.setattr("switchyard.config.SWITCHYARD_DB", db_path)

    # Create test-echo pack
    pack_dir = packs / "test-echo"
    (pack_dir / "scripts").mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "name: test-echo\n"
        "description: Test pack\n"
        "phases:\n"
        "  execution:\n"
        "    executor: shell\n"
        "    command: scripts/execute\n"
        "    max_workers: 2\n"
    )
    # Create execute script that echoes and writes a status file
    execute_script = pack_dir / "scripts" / "execute"
    execute_script.write_text(
        '#!/bin/bash\n'
        'PLAN_FILE="$1"\n'
        'WORKSPACE="$2"\n'
        'PLAN_ID=$(basename "$PLAN_FILE" | cut -d_ -f1)\n'
        'echo "##PROGRESS## $PLAN_ID | Phase: executing | 1/1"\n'
        'echo "Executing task $PLAN_ID"\n'
        'sleep 0.5\n'
        '# Write status sidecar next to plan file\n'
        'STATUS_FILE="${PLAN_FILE%.plan.md}.status"\n'
        'echo "STATUS: done" > "$STATUS_FILE"\n'
        'echo "COMMITS: none" >> "$STATUS_FILE"\n'
        'echo "TESTS_RAN: none" >> "$STATUS_FILE"\n'
        'echo "TEST_RESULT: skip" >> "$STATUS_FILE"\n'
    )
    execute_script.chmod(0o755)

    # Create session
    session_id = "test-001"
    config = SessionConfig(
        pack_name="test-echo",
        session_name="Test Run",
        num_workers=2,
        poll_interval=1,
        task_idle_timeout=30,
        task_max_timeout=0,
        session_max_timeout=60,
    )

    store = StateStore(db_path=db_path)
    store.connect()

    session = Session(
        id=session_id,
        name="Test Run",
        pack_name="test-echo",
        config_json=json.dumps(config.__dict__),
        status=SessionStatus.CREATED,
        created_at=datetime.now(timezone.utc),
    )
    store.create_session(session)

    # Create session directories
    dirs = session_subdirs(session_id)
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    for i in range(2):
        (dirs["workers"] / str(i)).mkdir(exist_ok=True)

    return store, session_id, dirs, config


class TestOrchestratorBasic:
    def test_no_tasks_completes_immediately(self, setup_session):
        store, session_id, dirs, config = setup_session
        # No tasks created -- orchestrator should complete immediately
        orch = Orchestrator(session_id, store)
        orch.run_foreground()

        session = store.get_session(session_id)
        assert session.status == SessionStatus.COMPLETED

    def test_single_task_dispatch_and_complete(self, setup_session):
        store, session_id, dirs, config = setup_session

        # Create a task in ready/
        plan_content = "---\nPLAN_ID: 001\n---\n# Plan 001: Echo Test\n"
        plan_file = dirs["ready"] / "001_echo_test.plan.md"
        plan_file.write_text(plan_content)

        # Create resolution.json
        resolution = {
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "tasks": [{"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1}],
            "groups": [], "conflicts": [],
        }
        (dirs["ready"].parent / "resolution.json").write_text(json.dumps(resolution))

        # Register task in DB
        store.create_task(Task(
            id="001", session_id=session_id, title="Echo Test",
            status=TaskStatus.READY, plan_filename="001_echo_test.plan.md",
            created_at=datetime.now(timezone.utc),
        ))

        orch = Orchestrator(session_id, store)
        orch.run_foreground()

        # Verify task completed
        task = store.get_task(session_id, "001")
        assert task.status == TaskStatus.DONE

        # Verify session completed
        session = store.get_session(session_id)
        assert session.status == SessionStatus.COMPLETED

        # Verify plan file moved to done/
        assert not plan_file.exists()
        done_plans = list(dirs["done"].glob("*.plan.md"))
        assert len(done_plans) == 1

    def test_two_tasks_parallel(self, setup_session):
        store, session_id, dirs, config = setup_session

        # Create two independent tasks
        for tid in ["001", "002"]:
            plan = dirs["ready"] / f"{tid}_echo.plan.md"
            plan.write_text(f"---\nPLAN_ID: {tid}\n---\n# Plan {tid}\n")
            store.create_task(Task(
                id=tid, session_id=session_id, title=f"Task {tid}",
                status=TaskStatus.READY, plan_filename=f"{tid}_echo.plan.md",
                created_at=datetime.now(timezone.utc),
            ))

        resolution = {
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "tasks": [
                {"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1},
                {"task_id": "002", "depends_on": [], "anti_affinity": [], "exec_order": 1},
            ],
            "groups": [], "conflicts": [],
        }
        (dirs["ready"].parent / "resolution.json").write_text(json.dumps(resolution))

        orch = Orchestrator(session_id, store)
        orch.run_foreground()

        for tid in ["001", "002"]:
            task = store.get_task(session_id, tid)
            assert task.status == TaskStatus.DONE

        session = store.get_session(session_id)
        assert session.status == SessionStatus.COMPLETED

    def test_dependency_ordering(self, setup_session):
        store, session_id, dirs, config = setup_session

        # Task 002 depends on 001
        for tid in ["001", "002"]:
            plan = dirs["ready"] / f"{tid}_echo.plan.md"
            plan.write_text(f"---\nPLAN_ID: {tid}\n---\n# Plan {tid}\n")
            deps = ["001"] if tid == "002" else []
            store.create_task(Task(
                id=tid, session_id=session_id, title=f"Task {tid}",
                status=TaskStatus.READY, plan_filename=f"{tid}_echo.plan.md",
                depends_on=deps, created_at=datetime.now(timezone.utc),
            ))

        resolution = {
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "tasks": [
                {"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1},
                {"task_id": "002", "depends_on": ["001"], "anti_affinity": [], "exec_order": 2},
            ],
            "groups": [], "conflicts": [],
        }
        (dirs["ready"].parent / "resolution.json").write_text(json.dumps(resolution))

        orch = Orchestrator(session_id, store)
        orch.run_foreground()

        # Both should complete
        for tid in ["001", "002"]:
            task = store.get_task(session_id, tid)
            assert task.status == TaskStatus.DONE

        # Check events to verify 001 completed before 002 was dispatched
        events = store.list_events(session_id, limit=100)
        dispatch_events = [
            e for e in events if e.event_type == EventType.TASK_DISPATCHED
        ]
        complete_events = [
            e for e in events if e.event_type == EventType.TASK_COMPLETED
        ]
        # 001 must have a completion event before 002's dispatch event
        t1_complete = next(e for e in complete_events if e.task_id == "001")
        t2_dispatch = next(e for e in dispatch_events if e.task_id == "002")
        assert t1_complete.timestamp <= t2_dispatch.timestamp


class TestOrchestratorRecovery:
    def test_recovery_returns_orphaned_plan_to_ready(self, setup_session):
        """Simulate a crash: plan file left in workers/0/, no status file.
        Recovery should move it back to ready/."""
        store, session_id, dirs, config = setup_session

        # Place a plan file in workers/0/ (simulating crash mid-execution)
        slot_dir = dirs["workers"] / "0"
        plan = slot_dir / "001_orphan.plan.md"
        plan.write_text("---\nPLAN_ID: 001\n---\n# Plan 001\n")

        store.create_task(Task(
            id="001", session_id=session_id, title="Orphan",
            status=TaskStatus.ACTIVE, plan_filename="001_orphan.plan.md",
            created_at=datetime.now(timezone.utc),
        ))

        orch = Orchestrator(session_id, store)
        orch._initialize()
        orch._run_recovery()

        # Plan should be back in ready/
        assert (dirs["ready"] / "001_orphan.plan.md").exists()
        assert not plan.exists()

        # DB should reflect ready status
        task = store.get_task(session_id, "001")
        assert task.status == TaskStatus.READY

    def test_recovery_collects_completed_orphan(self, setup_session):
        """Simulate a crash after worker finished but before collection:
        plan file + status file (STATUS: done) in workers/0/.
        Recovery should move to done/."""
        store, session_id, dirs, config = setup_session

        slot_dir = dirs["workers"] / "0"
        plan = slot_dir / "001_done.plan.md"
        plan.write_text("---\nPLAN_ID: 001\n---\n# Plan 001\n")
        status = slot_dir / "001_done.status"
        status.write_text("STATUS: done\nCOMMITS: abc\nTESTS_RAN: targeted\nTEST_RESULT: pass\n")

        store.create_task(Task(
            id="001", session_id=session_id, title="Done Orphan",
            status=TaskStatus.ACTIVE, plan_filename="001_done.plan.md",
            created_at=datetime.now(timezone.utc),
        ))

        orch = Orchestrator(session_id, store)
        orch._initialize()
        orch._run_recovery()

        # Should be in done/
        assert (dirs["done"] / "001_done.plan.md").exists()
        assert not plan.exists()
```

Run: `python3 -m pytest tests/test_orchestrator.py -v`

**All tests must pass.** The orchestrator integration tests are the most important tests in Phase 1. They validate the entire pipeline: dispatch, execution, completion collection, dependency ordering, and crash recovery.

**Known timing sensitivity:** The `test_single_task_dispatch_and_complete` and `test_two_tasks_parallel` tests depend on the `test-echo` pack's execute script finishing quickly. The script sleeps 0.5s; the poll interval is 1s; the test should complete within 10s. If tests hang, check that the execute script is correctly writing the status sidecar file and that the orchestrator is detecting finished subprocesses.

---

### Step 1.9: CLI Entry Point and Self-Bootstrapping

**Dependencies:** All Phase 1 steps (1.1-1.8)

**Purpose:** Create the self-bootstrapping entry point and CLI argument parser.

**File 1:** `switchyard` (project root, no extension) -- the bootstrap script

```python
#!/usr/bin/env python3
"""Cognitive Switchyard -- self-bootstrapping entry point.

On first run, creates ~/.switchyard_venv, installs dependencies, then
re-executes itself with the venv's Python. On subsequent runs, the venv
already exists and startup is instant.
"""
import importlib
import os
import subprocess
import sys
from pathlib import Path

VENV_DIR = Path.home() / ".switchyard_venv"
DEPENDENCIES = ["fastapi", "uvicorn", "aiosqlite", "pyyaml"]

def bootstrap():
    """Ensure all dependencies are available. Create venv if needed."""
    # Check if we're already in the venv
    if sys.prefix == str(VENV_DIR):
        return  # already running in venv

    # Check if deps are importable
    try:
        for dep in ["fastapi", "uvicorn", "aiosqlite", "yaml"]:
            importlib.import_module(dep)
        return  # all deps available
    except ImportError:
        pass

    # Check if venv exists and has python
    venv_python = VENV_DIR / "bin" / "python3"
    if venv_python.exists():
        # Re-exec with venv python
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)

    # Create venv and install deps
    print(f"First run: creating virtual environment at {VENV_DIR}")
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])

    pip = VENV_DIR / "bin" / "pip"
    print(f"Installing dependencies: {', '.join(DEPENDENCIES)}")
    subprocess.check_call([str(pip), "install", "--quiet"] + DEPENDENCIES)

    # Re-exec with venv python
    print("Setup complete. Starting Cognitive Switchyard...\n")
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)


bootstrap()

# Add project root to path so we can import the switchyard package
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from switchyard.cli import main
main()
```

Make executable: `chmod +x switchyard`

**File 2:** `switchyard/cli.py` -- argparse CLI

```python
from __future__ import annotations
import argparse
import json
import logging
import sys
import uuid
from datetime import datetime, timezone

from switchyard.config import (
    ensure_directories, GlobalConfig, SessionConfig,
    session_dir, session_subdirs,
)
from switchyard.models import Session, SessionStatus, Task, TaskStatus
from switchyard.state import StateStore
from switchyard.pack_loader import (
    bootstrap_packs, load_pack, list_packs, reset_pack,
    check_scripts_executable, run_preflight,
)
from switchyard.scheduler import load_resolution
from switchyard.orchestrator import Orchestrator


def main():
    parser = argparse.ArgumentParser(
        prog="switchyard",
        description="Cognitive Switchyard -- Task Orchestration Engine",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )

    sub = parser.add_subparsers(dest="command")

    # --- start command ---
    start_p = sub.add_parser("start", help="Start a new orchestration session")
    start_p.add_argument("--pack", required=True, help="Pack name")
    start_p.add_argument("--name", help="Session name (auto-generated if omitted)")
    start_p.add_argument("--workers", type=int, help="Number of worker slots")
    start_p.add_argument("--poll", type=int, default=5, help="Poll interval (seconds)")
    start_p.add_argument("--intake", help="Path to intake directory (default: session intake/)")

    # --- list-packs command ---
    sub.add_parser("list-packs", help="List available packs")

    # --- reset-pack command ---
    reset_p = sub.add_parser("reset-pack", help="Reset a pack to factory default")
    reset_p.add_argument("name", help="Pack name to reset")

    # --- reset-all-packs command ---
    sub.add_parser("reset-all-packs", help="Reset all packs to factory defaults")

    # --- history command ---
    sub.add_parser("history", help="List past sessions")

    args = parser.parse_args()

    # Set up logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Bootstrap
    ensure_directories()
    bootstrap_packs()

    if args.command == "list-packs":
        _cmd_list_packs()
    elif args.command == "reset-pack":
        _cmd_reset_pack(args.name)
    elif args.command == "reset-all-packs":
        _cmd_reset_all_packs()
    elif args.command == "history":
        _cmd_history()
    elif args.command == "start":
        _cmd_start(args)
    else:
        parser.print_help()


def _cmd_list_packs():
    packs = list_packs()
    if not packs:
        print("No packs installed.")
        return
    for p in packs:
        print(f"  {p.name:20s} {p.description}")


def _cmd_reset_pack(name: str):
    if reset_pack(name):
        print(f"Pack '{name}' reset to factory default.")
    else:
        print(f"Error: no built-in pack named '{name}'.", file=sys.stderr)
        sys.exit(1)


def _cmd_reset_all_packs():
    from switchyard.config import BUILTIN_PACKS_DIR
    if not BUILTIN_PACKS_DIR.exists():
        print("No built-in packs directory found.")
        return
    count = 0
    for d in BUILTIN_PACKS_DIR.iterdir():
        if d.is_dir() and (d / "pack.yaml").exists():
            reset_pack(d.name)
            count += 1
    print(f"Reset {count} pack(s) to factory defaults.")


def _cmd_history():
    store = StateStore()
    store.connect()
    sessions = store.list_sessions()
    store.close()
    if not sessions:
        print("No sessions.")
        return
    for s in sessions:
        elapsed = ""
        if s.started_at and s.completed_at:
            secs = (s.completed_at - s.started_at).total_seconds()
            elapsed = f" ({int(secs)}s)"
        print(f"  {s.id[:8]}  {s.name:30s} {s.status.value:12s} {s.pack_name}{elapsed}")


def _cmd_start(args):
    """Start a new session and run the orchestrator."""
    # Load and validate pack
    try:
        pack_config = load_pack(args.pack)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Check scripts executable
    failures = check_scripts_executable(args.pack)
    if failures:
        print(f"ERROR: Pack '{args.pack}' has non-executable scripts:\n")
        for path, fix in failures:
            print(f"  {path}  -- Run: {fix}")
        print("\nFix the permissions above and re-run.")
        sys.exit(1)

    # Run preflight checks
    preflight_results = run_preflight(args.pack)
    all_passed = True
    for name, passed, detail in preflight_results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            print(f"         {detail}")
            all_passed = False
    if not all_passed:
        print("\nPreflight checks failed. Fix the issues above and re-run.")
        sys.exit(1)

    # Create session
    session_id = str(uuid.uuid4())[:8]
    session_name = args.name or f"{args.pack}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    num_workers = args.workers or pack_config.execution_max_workers

    config = SessionConfig(
        pack_name=args.pack,
        session_name=session_name,
        num_workers=num_workers,
        poll_interval=args.poll,
        task_idle_timeout=pack_config.task_idle_timeout,
        task_max_timeout=pack_config.task_max_timeout,
        session_max_timeout=pack_config.session_max_timeout,
    )

    store = StateStore()
    store.connect()

    session = Session(
        id=session_id,
        name=session_name,
        pack_name=args.pack,
        config_json=json.dumps(config.__dict__),
        status=SessionStatus.CREATED,
        created_at=datetime.now(timezone.utc),
    )
    store.create_session(session)

    # Set up session directories
    dirs = session_subdirs(session_id)
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    # Load tasks from ready/ directory (for Phase 1, tasks are pre-staged)
    ready_dir = dirs["ready"]
    resolution_path = session_dir(session_id) / "resolution.json"

    # If an intake directory was specified, copy files
    if args.intake:
        from pathlib import Path as P
        intake_src = P(args.intake)
        if intake_src.exists():
            for f in sorted(intake_src.glob("*.plan.md")):
                dest = ready_dir / f.name
                import shutil
                shutil.copy2(f, dest)

    # Register tasks from plan files in ready/
    constraints_map = {}
    if resolution_path.exists():
        from switchyard.scheduler import load_resolution
        for c in load_resolution(resolution_path):
            constraints_map[c.task_id] = c

    for plan_file in sorted(ready_dir.glob("*.plan.md")):
        task_id = store._extract_task_id_from_filename(plan_file.name)
        if not task_id:
            continue
        constraint = constraints_map.get(task_id)
        title = _extract_title_from_plan(plan_file)

        store.create_task(Task(
            id=task_id,
            session_id=session_id,
            title=title,
            status=TaskStatus.READY,
            plan_filename=plan_file.name,
            depends_on=constraint.depends_on if constraint else [],
            anti_affinity=constraint.anti_affinity if constraint else [],
            exec_order=constraint.exec_order if constraint else 1,
            created_at=datetime.now(timezone.utc),
        ))

    task_count = len(store.list_tasks(session_id))
    print(f"\nSession: {session_name} ({session_id})")
    print(f"Pack: {args.pack}")
    print(f"Workers: {num_workers}")
    print(f"Tasks: {task_count}")

    if task_count == 0:
        print("\nNo tasks found. Place .plan.md files in the ready/ directory.")
        print(f"  {ready_dir}")
        store.close()
        return

    print(f"\nStarting orchestrator...")
    orch = Orchestrator(session_id, store)
    try:
        orch.run_foreground()
    except KeyboardInterrupt:
        print("\nInterrupted. Stopping workers...")
        orch.stop()
    finally:
        store.close()

    # Print summary
    store2 = StateStore()
    store2.connect()
    final_session = store2.get_session(session_id)
    tasks = store2.list_tasks(session_id)
    store2.close()

    done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
    blocked = sum(1 for t in tasks if t.status == TaskStatus.BLOCKED)
    print(f"\nSession {final_session.status.value}: {done} done, {blocked} blocked")


def _extract_title_from_plan(plan_path) -> str:
    """Extract the title from a plan file (first H1 heading)."""
    try:
        with open(plan_path) as f:
            in_frontmatter = False
            for line in f:
                line = line.strip()
                if line == "---":
                    in_frontmatter = not in_frontmatter
                    continue
                if in_frontmatter:
                    continue
                if line.startswith("# "):
                    # Strip "# Plan NNN: " prefix if present
                    title = line[2:].strip()
                    if title.lower().startswith("plan"):
                        parts = title.split(":", 1)
                        if len(parts) > 1:
                            return parts[1].strip()
                    return title
    except Exception:
        pass
    return plan_path.stem
```

**Verification gate:** Run the following sequence:

```bash
# 1. Verify the entry point works
cd /Users/example/source/utilities/cognitive_switchyard
chmod +x switchyard
python3 switchyard --help

# 2. Verify list-packs (should show test-echo after bootstrap)
python3 switchyard list-packs

# 3. Run all tests to confirm nothing broke
python3 -m pytest tests/ -v
```

All commands should succeed and all tests should pass.

---

### Step 1.10: Test Echo Pack

**Dependencies:** Step 1.9 (CLI exists)

**Purpose:** The `test-echo` pack is a minimal pack for testing the core engine. No LLM, no complex isolation. Tasks execute a simple shell script that echoes output and writes a status sidecar.

**File:** `packs/test-echo/pack.yaml`

```yaml
name: test-echo
description: Minimal test pack -- executes echo commands (no LLM required)
version: "0.1.0"

phases:
  planning:
    enabled: false
  resolution:
    enabled: false
    executor: passthrough
  execution:
    executor: shell
    command: scripts/execute
    max_workers: 2
  verification:
    enabled: false

auto_fix:
  enabled: false

isolation:
  type: none

prerequisites: []

timeouts:
  task_idle: 30
  task_max: 60
  session_max: 300
```

**File:** `packs/test-echo/scripts/execute` (must be chmod +x)

```bash
#!/bin/bash
set -euo pipefail

# Test Echo Pack -- execute hook
# Args: $1 = plan file path, $2 = workspace path

PLAN_FILE="$1"
WORKSPACE="$2"

# Extract plan ID from filename (e.g., "001_some_task.plan.md" -> "001")
PLAN_BASENAME=$(basename "$PLAN_FILE")
PLAN_ID=$(echo "$PLAN_BASENAME" | cut -d_ -f1)

# Emit progress marker
echo "##PROGRESS## $PLAN_ID | Phase: executing | 1/1"
echo "Executing task $PLAN_ID from plan $PLAN_BASENAME"

# Simulate some work
sleep 1

# Read the plan content and echo it
echo "--- Plan content ---"
cat "$PLAN_FILE"
echo "--- End plan ---"

echo "##PROGRESS## $PLAN_ID | Detail: Task complete"

# Write status sidecar (same directory as plan file, .status extension)
STATUS_FILE="${PLAN_FILE%.plan.md}.status"
cat > "$STATUS_FILE" <<EOF
STATUS: done
COMMITS: none
TESTS_RAN: none
TEST_RESULT: skip
NOTES: Executed by test-echo pack
EOF

echo "Status written to $STATUS_FILE"
```

**File:** `packs/test-echo/templates/intake.md`

```markdown
---
TITLE: <short task title>
PRIORITY: normal
---

## Description

<What this task should do>
```

**Verification gate:**

```bash
# Ensure execute script is executable
chmod +x packs/test-echo/scripts/execute

# Test the script directly
echo "# Plan 001: Test" > /tmp/001_test.plan.md
bash packs/test-echo/scripts/execute /tmp/001_test.plan.md /tmp
# Should output progress markers and create /tmp/001_test.status
cat /tmp/001_test.status
# Should show "STATUS: done"

# Clean up
rm -f /tmp/001_test.plan.md /tmp/001_test.status
```

---

### Step 1.11: Phase 1 End-to-End Integration Test

**Dependencies:** All Phase 1 steps (1.1-1.10)

**Purpose:** Run the full pipeline end-to-end via CLI with the test-echo pack. This is the definitive test that Phase 1 works.

**Create test fixture:** `tests/fixtures/echo_session/`

```bash
mkdir -p tests/fixtures/echo_session/ready
```

Create `tests/fixtures/echo_session/ready/001_hello_world.plan.md`:
```markdown
---
PLAN_ID: 001
PRIORITY: normal
ESTIMATED_SCOPE: none
DEPENDS_ON: none
EXEC_ORDER: 1
FULL_TEST_AFTER: no
---

# Plan 001: Hello World

## Overview
A simple test task that echoes a greeting.
```

Create `tests/fixtures/echo_session/ready/002_goodbye.plan.md`:
```markdown
---
PLAN_ID: 002
PRIORITY: normal
ESTIMATED_SCOPE: none
DEPENDS_ON: 001
EXEC_ORDER: 2
FULL_TEST_AFTER: no
---

# Plan 002: Goodbye

## Overview
A second test task that depends on 001.
```

Create `tests/fixtures/echo_session/resolution.json`:
```json
{
    "resolved_at": "2026-03-07T00:00:00Z",
    "tasks": [
        {"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1},
        {"task_id": "002", "depends_on": ["001"], "anti_affinity": [], "exec_order": 2}
    ],
    "groups": [],
    "conflicts": [],
    "notes": "Test fixture"
}
```

**Integration test:** `tests/test_e2e_phase1.py`

```python
"""End-to-end integration test for Phase 1.

Creates a real session with the test-echo pack, runs the orchestrator,
and verifies the full pipeline from ready/ to done/.
"""
import json
import shutil
import pytest
from datetime import datetime, timezone
from pathlib import Path

from switchyard.config import (
    SessionConfig, session_dir, session_subdirs, SWITCHYARD_DB,
)
from switchyard.models import Session, SessionStatus, Task, TaskStatus
from switchyard.state import StateStore
from switchyard.orchestrator import Orchestrator
from switchyard.pack_loader import bootstrap_packs


@pytest.fixture
def e2e_env(tmp_path, monkeypatch):
    """Set up a complete end-to-end test environment."""
    home = tmp_path / ".switchyard"
    monkeypatch.setattr("switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("switchyard.config.SESSIONS_DIR", home / "sessions")
    monkeypatch.setattr("switchyard.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("switchyard.config.SWITCHYARD_DB", home / "switchyard.db")

    # Bootstrap packs (copies test-echo to tmp)
    project_root = Path(__file__).parent.parent
    monkeypatch.setattr("switchyard.config.BUILTIN_PACKS_DIR", project_root / "packs")
    from switchyard.config import ensure_directories
    ensure_directories()
    bootstrap_packs()

    # Create session
    session_id = "e2e-test-001"
    config = SessionConfig(
        pack_name="test-echo", session_name="E2E Test",
        num_workers=2, poll_interval=1,
        task_idle_timeout=30, session_max_timeout=60,
    )

    store = StateStore(db_path=home / "switchyard.db")
    store.connect()
    store.create_session(Session(
        id=session_id, name="E2E Test", pack_name="test-echo",
        config_json=json.dumps(config.__dict__),
        status=SessionStatus.CREATED,
        created_at=datetime.now(timezone.utc),
    ))

    # Set up directories
    dirs = session_subdirs(session_id)
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    # Copy fixtures
    fixtures = project_root / "tests" / "fixtures" / "echo_session"
    if fixtures.exists():
        for f in (fixtures / "ready").glob("*.plan.md"):
            shutil.copy2(f, dirs["ready"])
        res = fixtures / "resolution.json"
        if res.exists():
            shutil.copy2(res, session_dir(session_id) / "resolution.json")

    # Register tasks
    from switchyard.scheduler import load_resolution
    resolution_path = session_dir(session_id) / "resolution.json"
    constraints_map = {}
    if resolution_path.exists():
        for c in load_resolution(resolution_path):
            constraints_map[c.task_id] = c

    for plan_file in sorted(dirs["ready"].glob("*.plan.md")):
        task_id = store._extract_task_id_from_filename(plan_file.name)
        c = constraints_map.get(task_id)
        store.create_task(Task(
            id=task_id, session_id=session_id,
            title=plan_file.stem, status=TaskStatus.READY,
            plan_filename=plan_file.name,
            depends_on=c.depends_on if c else [],
            anti_affinity=c.anti_affinity if c else [],
            exec_order=c.exec_order if c else 1,
            created_at=datetime.now(timezone.utc),
        ))

    yield store, session_id, dirs
    store.close()


class TestEndToEndPhase1:
    def test_full_pipeline(self, e2e_env):
        """Run both tasks through the pipeline. Task 002 depends on 001."""
        store, session_id, dirs = e2e_env

        # Verify initial state
        tasks = store.list_tasks(session_id)
        assert len(tasks) == 2
        assert all(t.status == TaskStatus.READY for t in tasks)

        # Run orchestrator
        orch = Orchestrator(session_id, store)
        orch.run_foreground()

        # Verify final state
        session = store.get_session(session_id)
        assert session.status == SessionStatus.COMPLETED

        for tid in ["001", "002"]:
            task = store.get_task(session_id, tid)
            assert task.status == TaskStatus.DONE, f"Task {tid} status: {task.status}"

        # Verify done/ has the plan and status files
        done_files = list(dirs["done"].glob("*"))
        plan_files = [f for f in done_files if f.suffix == ".md"]
        status_files = [f for f in done_files if f.name.endswith(".status")]
        assert len(plan_files) == 2
        assert len(status_files) == 2

        # Verify ready/ is empty
        assert list(dirs["ready"].glob("*.plan.md")) == []

    def test_session_trimming(self, e2e_env):
        """Verify successful session directory is trimmed."""
        store, session_id, dirs = e2e_env

        orch = Orchestrator(session_id, store)
        orch.run_foreground()

        base = session_dir(session_id)
        # summary.json should exist
        assert (base / "summary.json").exists()
        # intake/, ready/, workers/ should be removed
        assert not (base / "intake").exists()
        assert not (base / "ready").exists()
        assert not (base / "workers").exists()
```

Run: `python3 -m pytest tests/test_e2e_phase1.py -v`

**This is the final gate for Phase 1.** If these tests pass, the core engine is working: session creation, task dispatch, constraint enforcement, completion collection, crash recovery, and session trimming are all verified.

Also run the full test suite one final time:

```bash
python3 -m pytest tests/ -v
```

**Every single test must pass before moving to Phase 2.**

---

## 3. Phase 2: Full Pack System, Planning, Resolution, Verification, Auto-Fix

**Goal:** Implement all optional pipeline phases (planning, resolution, verification, auto-fix) and build the Claude Code reference pack.

**Phase 2 builds on Phase 1's verified core.** The orchestrator, scheduler, state store, and worker manager are proven working. Phase 2 adds the LLM-driven phases that wrap around the execution core.

### Step 2.1: Planning Phase

**Dependencies:** Phase 1 complete and tested

**Purpose:** Implement the planning phase where LLM agents convert intake items into execution plans. The orchestrator launches 1-N planner agents in parallel. Each planner claims an intake item, produces a plan in `staging/`, or sends it to `review/` for human input.

**Reference:** `reference/work/plan.sh` (planner launcher), `reference/work/planning/PLANNER.md` (planner prompt).

**Changes to `switchyard/orchestrator.py`:**

Add a `_run_planning_phase()` method that:

1. Reads the pack config for `planning_enabled`, `planning_model`, `planning_prompt`, `planning_max_instances`
2. Updates session status to `PLANNING`
3. Launches N planner subprocesses (each running the pack's planner -- for agent executors, this means launching `claude` CLI with the planner prompt)
4. Monitors planners: waits for all to finish, reports which intake items ended up in `staging/` vs `review/`
5. If any items are in `review/`, pauses and waits for human input (session stays in `planning` state until all review items are resolved)
6. When all items are in `staging/` (or `staging/` + `ready/` for passthrough resolution), advances to the resolution phase

**Key implementation details:**

- Planner subprocesses run in parallel, each with its own log file in `logs/planners/`
- Intake item claiming uses atomic `os.rename()` from `intake/` to `claimed/` (same pattern as reference `plan.sh`)
- If the pack uses an agent executor for planning, the command is: `claude --dangerously-skip-permissions --model <model> -p "<prompt>" --allowedTools "Edit,Read,Write,Bash,Glob,Grep"`
- The planner prompt file is read from the pack directory and the intake item path is injected into it
- Plan ID collision check (reference `plan.sh` lines 39-57): before launching planners, verify no intake item's numeric prefix collides with existing done/ plan IDs

**This step does not need its own execute script** -- it extends the orchestrator. Create a helper module `switchyard/planner.py` if the logic grows large enough to warrant separation.

**Verification gate:** Create a test that:
1. Creates intake items in `intake/`
2. Creates a test pack with a simple planner script (not LLM -- just reads intake, writes a plan to staging)
3. Runs the planning phase
4. Verifies plans appear in `staging/` and intake items are consumed

```bash
python3 -m pytest tests/test_planning.py -v
```

### Step 2.2: Resolution Phase

**Dependencies:** Step 2.1 (planning phase)

**Purpose:** Implement the resolution phase that analyzes all staged plans and determines constraints. Three modes: `agent` (LLM reads plans), `script` (pack provides a script), `passthrough` (trust user declarations).

**Reference:** `reference/work/stage.sh` (resolver launcher), `reference/work/execution/RESOLVER.md` (resolver prompt), `reference/work/execution/RESOLUTION.md` (output format).

**Key implementation:**

1. Read all plans from `staging/`
2. For `passthrough` mode: read each plan's YAML front matter for DEPENDS_ON, ANTI_AFFINITY, EXEC_ORDER. Write `resolution.json`. Move plans to `ready/`.
3. For `script` mode: invoke the pack's resolution script with the staging directory path. Script writes `resolution.json` and moves plans to `ready/`.
4. For `agent` mode: launch the resolver agent (claude CLI with resolver prompt). Agent reads all plans, writes `resolution.json`, moves resolved plans to `ready/`.

**resolution.json format** (design doc Section 5.3, validated against `reference/work/execution/RESOLUTION.md`):

```json
{
    "resolved_at": "ISO timestamp",
    "tasks": [
        {"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1}
    ],
    "groups": [
        {"name": "group-name", "type": "anti_affinity", "members": ["001", "002"], "shared_resources": ["file.py"]}
    ],
    "conflicts": [],
    "notes": "free text"
}
```

**Passthrough resolution implementation** (most testable, implement first):

```python
def resolve_passthrough(staging_dir: Path, ready_dir: Path, resolution_path: Path) -> None:
    """Read YAML front matter from each plan, build resolution.json, move to ready/."""
    tasks = []
    for plan_file in sorted(staging_dir.glob("*.plan.md")):
        metadata = _parse_plan_frontmatter(plan_file)
        task_id = metadata.get("PLAN_ID", StateStore._extract_task_id_from_filename(plan_file.name))
        depends_on = _parse_list_field(metadata.get("DEPENDS_ON", "none"))
        anti_affinity = _parse_list_field(metadata.get("ANTI_AFFINITY", "none"))
        exec_order = int(metadata.get("EXEC_ORDER", "1"))

        tasks.append({
            "task_id": task_id,
            "depends_on": depends_on,
            "anti_affinity": anti_affinity,
            "exec_order": exec_order,
        })

        # Move plan to ready/
        os.rename(str(plan_file), str(ready_dir / plan_file.name))

    resolution = {
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "tasks": tasks,
        "groups": [],
        "conflicts": [],
        "notes": "Passthrough resolution (user-declared constraints only)",
    }
    resolution_path.write_text(json.dumps(resolution, indent=2))
```

**YAML front matter parser:**

```python
def _parse_plan_frontmatter(plan_path: Path) -> dict:
    """Parse YAML front matter from a plan file.

    Format:
        ---
        PLAN_ID: 001
        DEPENDS_ON: none
        ANTI_AFFINITY: 002, 003
        EXEC_ORDER: 1
        ---
    """
    lines = plan_path.read_text().splitlines()
    in_frontmatter = False
    yaml_lines = []
    for line in lines:
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter:
            yaml_lines.append(line)
    if yaml_lines:
        return yaml.safe_load("\n".join(yaml_lines)) or {}
    return {}
```

**Verification gate:** Test passthrough resolution with plans that have DEPENDS_ON and ANTI_AFFINITY in their front matter. Verify resolution.json output matches expected constraints and all plans are moved to ready/.

```bash
python3 -m pytest tests/test_resolution.py -v
```

### Step 2.3: Verification Phase

**Dependencies:** Phase 1 complete

**Purpose:** Run a global verification suite (e.g., full test suite) after a configurable number of tasks complete. Pauses dispatch, waits for active workers, runs verification, then resumes or enters auto-fix.

**Reference:** `reference/work/orchestrate.sh` lines 764-847 (run_full_test_suite_with_pause).

**Key pattern from reference:**
1. Set orchestrator phase to "waiting for workers before test"
2. Wait for ALL active workers to finish (keep collecting results)
3. Run the pack's verification command
4. If it passes, reset counter, resume dispatch
5. If it fails, enter auto-fix loop (Step 2.4) or halt

**Changes to `switchyard/orchestrator.py`:**

Add `_check_verification()` call in the dispatch loop after `_collect_finished_workers()`. Implement:

```python
def _check_verification(self) -> None:
    """Check if verification is due and run it if so."""
    if not self._pack.verification_enabled:
        return
    if self._completed_since_verify < self._config.verification_interval:
        return

    # Also check FULL_TEST_AFTER on recently completed tasks
    # (design doc: if a task has FULL_TEST_AFTER: yes, force verification)

    self._run_verification()

def _run_verification(self) -> None:
    """Pause dispatch, wait for workers, run verification."""
    # ... implementation
```

**Verification gate:** Test with a pack that has a simple verification command (e.g., `true` for pass, `false` for fail). Verify the orchestrator pauses dispatch during verification and resumes after.

### Step 2.4: Auto-Fix Loop

**Dependencies:** Steps 2.3 (verification phase)

**Purpose:** When a task fails or verification fails, launch a fixer agent to diagnose and fix the problem. Independent verification after each fix attempt. Context enrichment between attempts.

**Reference:** `reference/work/orchestrate.sh` lines 437-645 (build_error_context, run_fixer_agent, attempt_fix_with_retry).

**Critical patterns from reference:**

1. **Error context building:** Includes status files, last 200 lines of worker log, and plan files
2. **Independent verification:** After the fixer runs, the orchestrator independently re-runs tests. It does NOT trust the fixer's self-reported success.
3. **Context enrichment between attempts:** When a fix attempt fails, the NEXT attempt gets: original error context + independent verification output (actual test failures) + git diff of what the previous fixer changed. Critically, it does NOT include the fixer's log (which contains misleading self-reported "all tests pass" claims).

**Implementation:** Add `_attempt_auto_fix()` method to the orchestrator. This is called from `_handle_worker_completion()` when a task fails and `auto_fix_enabled` is True.

**Verification gate:** Test with a pack that has a simple fixer (echo script). Verify the retry loop runs the correct number of times and enriches context between attempts.

### Step 2.5: Claude Code Pack

**Dependencies:** Steps 2.1-2.4 (all optional phases implemented)

**Purpose:** Build the reference Claude Code pack that implements the full coding workflow from the reference system.

**Pack structure:**

```
packs/claude-code/
  pack.yaml
  prompts/
    planner.md       # From reference/work/planning/PLANNER.md
    resolver.md      # From reference/work/execution/RESOLVER.md
    worker.md        # From reference/work/execution/WORKER.md
    fixer.md         # Extracted from orchestrate.sh fixer prompts
    system.md        # From reference/work/SYSTEM.md
  scripts/
    isolate_start    # Git worktree creation
    isolate_end      # Git worktree merge/cleanup
    execute          # Launch claude CLI for worker
    verify           # Run test suite
    preflight        # Check claude CLI, git, etc.
  templates/
    intake.md        # From reference/work/planning/INTAKE_PROMPT.md
    plan.md
    status.md
```

**pack.yaml:**

```yaml
name: claude-code
description: Coding workflow using Claude Code CLI with git worktree isolation
version: "0.1.0"

phases:
  planning:
    enabled: true
    executor: agent
    model: opus
    prompt: prompts/planner.md
    max_instances: 3
  resolution:
    enabled: true
    executor: agent
    model: opus
    prompt: prompts/resolver.md
  execution:
    executor: agent
    model: sonnet
    prompt: prompts/worker.md
    max_workers: 4
  verification:
    enabled: true
    command: scripts/verify
    interval: 4

auto_fix:
  enabled: true
  max_attempts: 2
  model: opus
  prompt: prompts/fixer.md

isolation:
  type: git-worktree
  setup: scripts/isolate_start
  teardown: scripts/isolate_end

prerequisites:
  - name: Claude CLI
    check: "which claude"
  - name: Git
    check: "which git"

timeouts:
  task_idle: 300
  task_max: 0
  session_max: 14400
```

**Key scripts to implement:**

`scripts/isolate_start`: Create a git worktree for the task. Print the worktree path to stdout.

`scripts/isolate_end`: If status is "done", squash merge the worktree branch. If "blocked", cleanup without merging.

`scripts/execute`: Launch `claude --dangerously-skip-permissions --model <model> -p "<prompt>"` with the worker prompt and plan file.

`scripts/verify`: Run the project's test suite.

`scripts/preflight`: Check that `claude` CLI is installed and authenticated, `git` is available, not on main branch.

**Port prompts from reference:** Copy `reference/work/planning/PLANNER.md`, `reference/work/execution/WORKER.md`, `reference/work/execution/RESOLVER.md`, and `reference/work/SYSTEM.md` into the pack's `prompts/` directory. Adapt path references (e.g., change `work/planning/intake/` to the session's intake directory).

**Verification gate:** Run the preflight checks against the local machine. Verify the pack loads and validates correctly.

```bash
python3 switchyard list-packs  # Should show both test-echo and claude-code
```

### Step 2.6: Phase 2 Tests

Run the **full test suite** after implementing all Phase 2 steps:

```bash
python3 -m pytest tests/ -v
```

All Phase 1 tests must still pass (no regressions). All new Phase 2 tests must pass.

---

## 4. Phase 3: Web UI

**Goal:** Build the FastAPI server and embedded React SPA with all views specified in design doc Section 6.

**IMPORTANT:** Before implementing Phase 3, read the design doc Sections 6.1-6.6 in their entirety. The UI specification is extremely detailed with exact CSS values, animation keyframes, component specifications, and WebSocket protocol. Follow the spec precisely.

### Step 3.1: server.py -- FastAPI Application

**Dependencies:** Phase 1 and Phase 2 complete

**Purpose:** FastAPI app with REST endpoints, WebSocket handler, and the embedded HTML template served at `/`.

**File:** `switchyard/server.py`

Key structure:

```python
from __future__ import annotations
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from switchyard.config import (
    SWITCHYARD_DB, session_dir, session_subdirs,
    GlobalConfig, SessionConfig, ensure_directories,
)
from switchyard.models import SessionStatus, TaskStatus
from switchyard.state import StateStore
from switchyard.orchestrator import Orchestrator
from switchyard.html_template import get_html

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket connection manager.

    Design doc Section 7.5.
    """
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.log_subscriptions: dict[int, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active_connections.remove(ws)
        for slot_subs in self.log_subscriptions.values():
            slot_subs.discard(ws)

    async def broadcast(self, message: dict):
        """Broadcast to all connected clients."""
        text = json.dumps(message)
        disconnected = []
        for ws in self.active_connections:
            try:
                await ws.send_text(text)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)

    async def send_to_log_subscribers(self, slot: int, message: dict):
        """Send to clients subscribed to a specific worker slot's logs."""
        subs = self.log_subscriptions.get(slot, set())
        text = json.dumps(message)
        for ws in subs:
            try:
                await ws.send_text(text)
            except Exception:
                pass


# Global state
ws_manager = ConnectionManager()
orchestrator_instance: Optional[Orchestrator] = None
sync_store: Optional[StateStore] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: setup and teardown."""
    global sync_store
    ensure_directories()
    sync_store = StateStore()
    sync_store.connect()
    yield
    if orchestrator_instance:
        orchestrator_instance.stop()
    if sync_store:
        sync_store.close()


app = FastAPI(title="Cognitive Switchyard", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return get_html()


# --- REST API endpoints (design doc Section 6.6) ---
# Implement each endpoint from the table in Section 6.6.
# Use sync_store for DB queries (it's thread-safe for reads with WAL mode).
# For mutations that affect the orchestrator, coordinate via the orchestrator instance.

@app.get("/api/packs")
async def list_packs():
    from switchyard.pack_loader import list_packs as _list_packs
    packs = _list_packs()
    return [{"name": p.name, "description": p.description, "version": p.version} for p in packs]

# ... implement remaining endpoints per Section 6.6 ...


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket handler. Design doc Section 6.5."""
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "subscribe_logs":
                slot = msg.get("worker_slot")
                if slot is not None:
                    ws_manager.log_subscriptions.setdefault(slot, set()).add(ws)
            elif msg.get("type") == "unsubscribe_logs":
                slot = msg.get("worker_slot")
                if slot is not None:
                    ws_manager.log_subscriptions.get(slot, set()).discard(ws)
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
```

**Implement ALL REST endpoints from design doc Section 6.6.** The full list:

| Method | Path | Implementation notes |
|--------|------|---------------------|
| GET | `/api/packs` | Call pack_loader.list_packs() |
| GET | `/api/packs/{name}` | Call pack_loader.load_pack() |
| POST | `/api/sessions` | Create session, directories, return ID |
| GET | `/api/sessions` | List from DB |
| GET | `/api/sessions/{id}` | Get from DB with pipeline counts |
| POST | `/api/sessions/{id}/start` | Launch orchestrator in background thread |
| POST | `/api/sessions/{id}/pause` | Update session status to PAUSED |
| POST | `/api/sessions/{id}/resume` | Update session status to RUNNING |
| POST | `/api/sessions/{id}/abort` | Kill workers, mark ABORTED |
| GET | `/api/sessions/{id}/tasks` | List tasks with constraints |
| GET | `/api/sessions/{id}/tasks/{tid}` | Task detail |
| GET | `/api/sessions/{id}/tasks/{tid}/log` | Read log file with offset/limit |
| GET | `/api/sessions/{id}/dag` | Read resolution.json |
| GET | `/api/sessions/{id}/dashboard` | Aggregate counts + worker states |
| POST | `/api/sessions/{id}/tasks/{tid}/retry` | Move blocked task back to ready |
| GET | `/api/sessions/{id}/intake` | List intake directory |
| GET | `/api/sessions/{id}/open-intake` | subprocess.Popen(['open', path]) |
| GET | `/api/sessions/{id}/reveal-file` | Validate path, open -R |
| DELETE | `/api/sessions/{id}` | Delete session (409 if active) |
| DELETE | `/api/sessions` | Purge all completed sessions |
| GET | `/api/settings` | Load GlobalConfig |
| PUT | `/api/settings` | Save GlobalConfig |

**Verification gate:** After implementing all endpoints, test them:

```python
# tests/test_server.py
from fastapi.testclient import TestClient
from switchyard.server import app

def test_index():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Cognitive Switchyard" in resp.text

def test_list_packs():
    client = TestClient(app)
    resp = client.get("/api/packs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

# ... test each endpoint ...
```

```bash
python3 -m pytest tests/test_server.py -v
```

### Step 3.2: html_template.py -- Embedded React SPA

**Dependencies:** Step 3.1 (server exists)

**Purpose:** A single Python file containing the entire React SPA as an HTML string. This is the frontend.

**File:** `switchyard/html_template.py`

The `get_html()` function returns a complete HTML document with:
- Google Fonts import (design doc Section 6.3.0.1)
- CSS custom properties / design tokens (Section 6.3.0)
- Background texture (Section 6.3.0.2)
- Animation keyframes (Section 6.3.0.3)
- CDN script tags: React 18, ReactDOM 18, Babel Standalone, React Flow v11
- Tailwind CSS CDN with custom config
- Lucide React CDN
- The React application code in a `<script type="text/babel">` block

**React component hierarchy:**

```
App
  TopBar
  {currentView === 'setup' && <SetupView />}
  {currentView === 'monitor' && <MonitorView />}
  {currentView === 'taskDetail' && <TaskDetailView />}
  {currentView === 'dag' && <DAGView />}
  {currentView === 'history' && <HistoryView />}
  {currentView === 'settings' && <SettingsView />}
```

**State management:**

```javascript
// Top-level state
const [currentView, setCurrentView] = useState('setup');
const [session, setSession] = useState(null);
const [pipeline, setPipeline] = useState({});
const [workers, setWorkers] = useState([]);
const [tasks, setTasks] = useState([]);
const [selectedTaskId, setSelectedTaskId] = useState(null);

// WebSocket connection
useEffect(() => {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'state_update') {
            setSession(msg.data.session);
            setPipeline(msg.data.pipeline);
            setWorkers(msg.data.workers);
        }
        // ... handle other message types
    };
    return () => ws.close();
}, []);
```

**Implementation order for views** (each must be individually verified):

1. **SetupView** -- Pack selector, session config, preflight checks, intake list, Start button
2. **MonitorView** -- Pipeline strip, worker cards, task feed (the main operational view)
3. **TaskDetailView** -- Two-column layout with plan content and streaming log
4. **DAGView** -- React Flow interactive dependency graph
5. **HistoryView** -- Past sessions list with purge controls
6. **SettingsView** -- Retention, default workers/planners/pack

Follow the design doc Section 6.3.0.4 for exact component specifications (heights, fonts, colors, animations, hover states). Do not deviate from the spec.

**Verification gate:** After implementing each view, manually verify it by running the server:

```bash
python3 switchyard serve  # Add a 'serve' subcommand to cli.py
# Open browser to http://localhost:8100
```

For automated testing, verify the HTML template renders without errors:

```python
def test_html_template():
    from switchyard.html_template import get_html
    html = get_html()
    assert "COGNITIVE SWITCHYARD" in html
    assert "react" in html.lower()
    assert "ReactDOM" in html
```

### Step 3.3: CLI serve Command

Add a `serve` subcommand to `switchyard/cli.py` that starts the FastAPI server:

```python
# In the argparse setup:
serve_p = sub.add_parser("serve", help="Start the web UI server")
serve_p.add_argument("--port", type=int, default=8100, help="Preferred port")

# In the command handler:
def _cmd_serve(args):
    import uvicorn
    from switchyard.config import find_free_port  # implement this helper
    port = find_free_port(args.port)
    if port != args.port:
        logger.warning("Port %d in use; using %d instead", args.port, port)

    import webbrowser
    import threading
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    uvicorn.run("switchyard.server:app", host="127.0.0.1", port=port)
```

Add `find_free_port()` to `switchyard/config.py` per the pattern in the repo CLAUDE.md.

### Step 3.4: Phase 3 Integration Tests

After all views are implemented, run:

```bash
# Full test suite
python3 -m pytest tests/ -v

# Manual smoke test
python3 switchyard serve
# In browser: create a session with test-echo pack, add intake items, start, observe
```

---

## 5. Phase 4: Additional Packs (Proof of Generality)

**Goal:** Prove the engine is truly generic by implementing non-coding packs.

### Step 4.1: ffmpeg Transcode Pack

A pack that uses shell executor, temp-directory isolation, and ffprobe verification. No LLM.

### Step 4.2: Pack Author Guide

Write `docs/pack_author_guide.md` documenting how to create, test, and distribute custom packs.

### Step 4.3: Pack Scaffolding Tool

Implement `switchyard init-pack <name>` CLI command that generates a skeleton pack directory.

### Step 4.4: Pack Validation Tool

Implement `switchyard validate-pack <path>` CLI command that checks a pack for common errors.

---

## 6. Cross-Cutting Concerns

### 6.1 Testing Strategy Summary

| Layer | What is tested | When to run |
|-------|---------------|-------------|
| Unit tests (test_config, test_models) | Individual functions, data parsing | After each step |
| Component tests (test_state, test_scheduler, test_worker_manager) | Module behavior with mocked dependencies | After each step |
| Integration tests (test_orchestrator) | Multi-module interaction with real DB | After Steps 1.8, 2.4 |
| End-to-end tests (test_e2e_phase1) | Full pipeline with real pack and subprocesses | After Steps 1.11, 2.6 |
| API tests (test_server) | REST endpoints and WebSocket | After Step 3.1 |
| Manual smoke tests | Full UI workflow | After Step 3.4 |

### 6.2 Regression Prevention

Every bug fix during implementation must include a test that would catch the same bug if reintroduced. If a test was passing and starts failing after a change, the code is wrong -- fix the code, not the test (unless the test is genuinely testing a changed interface).

### 6.3 File Tracking Checklist

Before declaring any phase complete, run:

```bash
git status
git ls-files --others --exclude-standard  # check for untracked files
```

Ensure all new files are tracked. `.gitignore` rules can silently drop files.

### 6.4 Lessons Learned File

Create `docs/LESSONS_LEARNED.md` after Phase 1 is complete. Update it after every bug fix with:
- What went wrong
- What pattern caused it
- What pattern to follow instead
