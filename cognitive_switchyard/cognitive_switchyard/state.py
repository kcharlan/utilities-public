from __future__ import annotations

import collections.abc
import json
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cognitive_switchyard.config import RuntimePaths
from cognitive_switchyard.models import (
    PersistedTask,
    RecoveryResult,
    SessionEvent,
    SessionRecord,
    SessionRuntimeState,
    TaskPlan,
    WorkerRecoveryMetadata,
    WorkerSlotRecord,
)
from cognitive_switchyard.parsers import ArtifactParseError, extract_operator_actions_section, parse_task_plan


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        pack TEXT NOT NULL,
        status TEXT NOT NULL,
        config_json TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        runtime_state_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        session_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        worker_slot INTEGER,
        depends_on_json TEXT NOT NULL,
        anti_affinity_json TEXT NOT NULL,
        exec_order INTEGER NOT NULL,
        full_test_after INTEGER NOT NULL,
        plan_relpath TEXT NOT NULL,
        created_at TEXT,
        started_at TEXT,
        completed_at TEXT,
        PRIMARY KEY (session_id, task_id),
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_slots (
        session_id TEXT NOT NULL,
        slot_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        current_task_id TEXT,
        PRIMARY KEY (session_id, slot_number),
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        event_type TEXT NOT NULL,
        task_id TEXT,
        message TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """,
)

_UNSET = object()


@dataclass(frozen=True)
class StateStore:
    runtime_paths: RuntimePaths

    @property
    def database_path(self) -> Path:
        return self.runtime_paths.database

    def create_session(
        self,
        *,
        session_id: str,
        name: str,
        pack: str,
        created_at: str,
        config_json: str | None = None,
        pre_delete: collections.abc.Callable[[SessionRecord], None] | None = None,
    ) -> SessionRecord:
        # If a terminal (completed/aborted) session with this ID exists,
        # remove it so the ID can be reused without manual cleanup.
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is not None:
                if row[0] in ("completed", "aborted"):
                    if pre_delete is not None:
                        pre_delete(self.get_session(session_id))
                    self.delete_session(session_id)
                else:
                    raise KeyError(f"Session already exists: {session_id}")
        # Insert DB row first so a failed insert doesn't leave orphan directories.
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO sessions (
                        id,
                        name,
                        pack,
                        status,
                        config_json,
                        created_at,
                        started_at,
                        completed_at,
                        runtime_state_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, name, pack, "created", config_json, created_at, None, None, "{}"),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise KeyError(f"Session already exists: {session_id}") from exc
        # Materialize directories only after the DB row is committed.
        session_paths = self.runtime_paths.session_paths(session_id)
        session_paths.materialize()
        return SessionRecord(
            id=session_id,
            name=name,
            pack=pack,
            status="created",
            created_at=created_at,
            started_at=None,
            config_json=config_json,
            completed_at=None,
            runtime_state=SessionRuntimeState(),
        )

    def register_task_plan(
        self,
        *,
        session_id: str,
        plan: TaskPlan,
        plan_text: str,
        created_at: str,
    ) -> PersistedTask:
        session_paths = self.runtime_paths.session_paths(session_id)
        plan_path = session_paths.plan_path(plan.task_id, status="ready")
        with self._connect() as connection:
            if not self._session_exists(connection, session_id):
                raise KeyError(f"Unknown session: {session_id}")
            if self._task_exists(connection, session_id, plan.task_id):
                raise KeyError(f"Task already exists: {session_id}/{plan.task_id}")
        task = PersistedTask(
            session_id=session_id,
            task_id=plan.task_id,
            title=plan.title,
            depends_on=plan.depends_on,
            anti_affinity=plan.anti_affinity,
            exec_order=plan.exec_order,
            full_test_after=plan.full_test_after,
            status="ready",
            plan_path=plan_path,
            worker_slot=None,
            created_at=created_at,
            started_at=None,
            completed_at=None,
        )
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            plan_path.write_text(plan_text, encoding="utf-8")
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO tasks (
                        session_id,
                        task_id,
                        title,
                        status,
                        worker_slot,
                        depends_on_json,
                        anti_affinity_json,
                        exec_order,
                        full_test_after,
                        plan_relpath,
                        created_at,
                        started_at,
                        completed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        plan.task_id,
                        plan.title,
                        "ready",
                        None,
                        self._encode_tuple(plan.depends_on),
                        self._encode_tuple(plan.anti_affinity),
                        plan.exec_order,
                        int(plan.full_test_after),
                        self._relative_to_session(session_id, plan_path),
                        created_at,
                        None,
                        None,
                    ),
                )
                connection.commit()
        except Exception:
            if plan_path.exists():
                plan_path.unlink()
            raise
        return task

    def upsert_ready_task_plan(
        self,
        *,
        session_id: str,
        plan: TaskPlan,
        plan_text: str,
        created_at: str,
    ) -> PersistedTask:
        session_paths = self.runtime_paths.session_paths(session_id)
        plan_path = session_paths.plan_path(plan.task_id, status="ready")
        with self._connect() as connection:
            if not self._session_exists(connection, session_id):
                raise KeyError(f"Unknown session: {session_id}")
            existing = connection.execute(
                """
                SELECT created_at
                FROM tasks
                WHERE session_id = ? AND task_id = ?
                """,
                (session_id, plan.task_id),
            ).fetchone()
        task = PersistedTask(
            session_id=session_id,
            task_id=plan.task_id,
            title=plan.title,
            depends_on=plan.depends_on,
            anti_affinity=plan.anti_affinity,
            exec_order=plan.exec_order,
            full_test_after=plan.full_test_after,
            status="ready",
            plan_path=plan_path,
            worker_slot=None,
            created_at=existing["created_at"] if existing is not None else created_at,
            started_at=None,
            completed_at=None,
        )
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        previous_path: Path | None = None
        if existing is not None:
            previous_path = self.get_task(session_id, plan.task_id).plan_path
        try:
            if previous_path is not None and previous_path != plan_path and previous_path.exists():
                previous_path.replace(plan_path)
            plan_path.write_text(plan_text, encoding="utf-8")
            with self._connect() as connection:
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO tasks (
                            session_id,
                            task_id,
                            title,
                            status,
                            worker_slot,
                            depends_on_json,
                            anti_affinity_json,
                            exec_order,
                            full_test_after,
                            plan_relpath,
                            created_at,
                            started_at,
                            completed_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            plan.task_id,
                            plan.title,
                            "ready",
                            None,
                            self._encode_tuple(plan.depends_on),
                            self._encode_tuple(plan.anti_affinity),
                            plan.exec_order,
                            int(plan.full_test_after),
                            self._relative_to_session(session_id, plan_path),
                            created_at,
                            None,
                            None,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE tasks
                        SET title = ?, status = ?, worker_slot = ?, depends_on_json = ?,
                            anti_affinity_json = ?, exec_order = ?, full_test_after = ?,
                            plan_relpath = ?, started_at = ?, completed_at = ?
                        WHERE session_id = ? AND task_id = ?
                        """,
                        (
                            plan.title,
                            "ready",
                            None,
                            self._encode_tuple(plan.depends_on),
                            self._encode_tuple(plan.anti_affinity),
                            plan.exec_order,
                            int(plan.full_test_after),
                            self._relative_to_session(session_id, plan_path),
                            None,
                            None,
                            session_id,
                            plan.task_id,
                        ),
                    )
                connection.commit()
        except Exception:
            if plan_path.exists():
                plan_path.unlink()
            raise
        return task

    def project_task(
        self,
        session_id: str,
        task_id: str,
        *,
        status: str,
        worker_slot: int | None = None,
        timestamp: str | None = None,
    ) -> PersistedTask:
        normalized_worker_slot = self._normalize_worker_slot(
            status=status,
            worker_slot=worker_slot,
        )
        current = self.get_task(session_id, task_id)
        session_paths = self.runtime_paths.session_paths(session_id)
        target_path = session_paths.plan_path(
            task_id,
            status=status,
            worker_slot=normalized_worker_slot,
        )
        source_path = current.plan_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        started_at = current.started_at
        completed_at = current.completed_at
        if status == "active":
            started_at = timestamp if started_at is None else started_at
        if status in {"done", "blocked"}:
            completed_at = timestamp
        task = PersistedTask(
            session_id=current.session_id,
            task_id=current.task_id,
            title=current.title,
            depends_on=current.depends_on,
            anti_affinity=current.anti_affinity,
            exec_order=current.exec_order,
            full_test_after=current.full_test_after,
            status=status,
            plan_path=target_path,
            worker_slot=normalized_worker_slot,
            created_at=current.created_at,
            started_at=started_at,
            completed_at=completed_at,
        )
        # Perform the DB update BEFORE the file move. F-2 fix: this ensures the
        # filesystem state is a consequence of a committed DB state. If the
        # process crashes after commit but before the file move, reconcile_filesystem_projection
        # will repair the DB on recovery (the file is still in its old location).
        with self._connect() as connection:
            previous_slot = current.worker_slot
            if previous_slot is not None and previous_slot != normalized_worker_slot:
                self._upsert_worker_slot(
                    connection,
                    session_id,
                    previous_slot,
                    "idle",
                    None,
                )
            if status == "active":
                self._upsert_worker_slot(
                    connection,
                    session_id,
                    normalized_worker_slot,
                    "active",
                    task_id,
                )
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, worker_slot = ?, plan_relpath = ?, started_at = ?, completed_at = ?
                WHERE session_id = ? AND task_id = ?
                """,
                (
                    status,
                    normalized_worker_slot,
                    self._relative_to_session(session_id, target_path),
                    started_at,
                    completed_at,
                    session_id,
                    task_id,
                ),
            )
            connection.commit()
        if source_path != target_path:
            source_path.replace(target_path)
        return task

    def get_task(self, session_id: str, task_id: str) -> PersistedTask:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT session_id, task_id, title, status, worker_slot, depends_on_json,
                       anti_affinity_json, exec_order, full_test_after, plan_relpath,
                       created_at, started_at, completed_at
                FROM tasks
                WHERE session_id = ? AND task_id = ?
                """,
                (session_id, task_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown task: {session_id}/{task_id}")
        return self._task_from_row(row)

    def get_session(self, session_id: str) -> SessionRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, pack, status, config_json, created_at, started_at, completed_at
                       , runtime_state_json
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown session: {session_id}")
        return self._session_from_row(row)

    def update_session_status(
        self,
        session_id: str,
        *,
        status: str,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> SessionRecord:
        session = self.get_session(session_id)
        next_started_at = session.started_at if started_at is None else started_at
        # When resetting to "created", clear started_at so the session behaves
        # as a fresh draft (fixes stale in_snapshot blocking Start button).
        if status == "created" and next_started_at is not None:
            next_started_at = None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET status = ?, started_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, next_started_at, completed_at, session_id),
            )
            connection.commit()
        return SessionRecord(
            id=session.id,
            name=session.name,
            pack=session.pack,
            status=status,
            created_at=session.created_at,
            started_at=next_started_at,
            config_json=session.config_json,
            completed_at=completed_at,
            runtime_state=session.runtime_state,
        )

    def update_session_config(self, session_id: str, config_json: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET config_json = ? WHERE id = ?",
                (config_json, session_id),
            )
            connection.commit()

    def write_session_runtime_state(
        self,
        session_id: str,
        *,
        completed_since_verification: int | object = _UNSET,
        verification_pending: bool | object = _UNSET,
        verification_reason: str | None | object = _UNSET,
        verification_started_at: str | None | object = _UNSET,
        auto_fix_context: str | None | object = _UNSET,
        auto_fix_task_id: str | None | object = _UNSET,
        auto_fix_attempt: int | object = _UNSET,
        last_fix_summary: str | None | object = _UNSET,
        run_number: int | object = _UNSET,
        run_started_at: str | None | object = _UNSET,
        accumulated_elapsed_seconds: int | object = _UNSET,
        last_run_elapsed_seconds: int | object = _UNSET,
        dispatch_frozen: bool | object = _UNSET,
        dispatch_frozen_reason: str | None | object = _UNSET,
        last_verification_test_summary: str | None | object = _UNSET,
    ) -> SessionRuntimeState:
        current = self.get_session(session_id).runtime_state
        next_state = SessionRuntimeState(
            completed_since_verification=(
                current.completed_since_verification
                if completed_since_verification is _UNSET
                else int(completed_since_verification)
            ),
            verification_pending=(
                current.verification_pending
                if verification_pending is _UNSET
                else bool(verification_pending)
            ),
            verification_reason=(
                current.verification_reason
                if verification_reason is _UNSET
                else verification_reason
            ),
            verification_started_at=(
                current.verification_started_at
                if verification_started_at is _UNSET
                else verification_started_at
            ),
            auto_fix_context=(
                current.auto_fix_context
                if auto_fix_context is _UNSET
                else auto_fix_context
            ),
            auto_fix_task_id=(
                current.auto_fix_task_id
                if auto_fix_task_id is _UNSET
                else auto_fix_task_id
            ),
            auto_fix_attempt=(
                current.auto_fix_attempt
                if auto_fix_attempt is _UNSET
                else int(auto_fix_attempt)
            ),
            last_fix_summary=(
                current.last_fix_summary
                if last_fix_summary is _UNSET
                else last_fix_summary
            ),
            run_number=(
                current.run_number
                if run_number is _UNSET
                else int(run_number)
            ),
            run_started_at=(
                current.run_started_at
                if run_started_at is _UNSET
                else run_started_at
            ),
            accumulated_elapsed_seconds=(
                current.accumulated_elapsed_seconds
                if accumulated_elapsed_seconds is _UNSET
                else int(accumulated_elapsed_seconds)
            ),
            last_run_elapsed_seconds=(
                current.last_run_elapsed_seconds
                if last_run_elapsed_seconds is _UNSET
                else int(last_run_elapsed_seconds)
            ),
            dispatch_frozen=(
                current.dispatch_frozen
                if dispatch_frozen is _UNSET
                else bool(dispatch_frozen)
            ),
            dispatch_frozen_reason=(
                current.dispatch_frozen_reason
                if dispatch_frozen_reason is _UNSET
                else dispatch_frozen_reason
            ),
            last_verification_test_summary=(
                current.last_verification_test_summary
                if last_verification_test_summary is _UNSET
                else last_verification_test_summary
            ),
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET runtime_state_json = ?
                WHERE id = ?
                """,
                (self._encode_runtime_state(next_state), session_id),
            )
            connection.commit()
        return next_state

    def list_ready_tasks(self, session_id: str) -> tuple[PersistedTask, ...]:
        return self._list_tasks(session_id, status="ready")

    def list_active_tasks(self, session_id: str) -> tuple[PersistedTask, ...]:
        return self._list_tasks(session_id, status="active")

    def list_done_tasks(self, session_id: str) -> tuple[PersistedTask, ...]:
        return self._list_tasks(session_id, status="done")

    def list_blocked_tasks(self, session_id: str) -> tuple[PersistedTask, ...]:
        return self._list_tasks(session_id, status="blocked")

    def list_all_tasks(self, session_id: str) -> list[PersistedTask]:
        """Return all tasks for a session in a single query, ordered by exec_order then task_id."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, task_id, title, status, worker_slot, depends_on_json,
                       anti_affinity_json, exec_order, full_test_after, plan_relpath,
                       created_at, started_at, completed_at
                FROM tasks
                WHERE session_id = ?
                ORDER BY exec_order ASC, task_id ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def list_sessions(self) -> tuple[SessionRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, pack, status, config_json, created_at, started_at, completed_at,
                       runtime_state_json
                FROM sessions
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        return tuple(self._session_from_row(row) for row in rows)

    def write_successful_session_summary(self, session_id: str) -> dict[str, object]:
        session = self.get_session(session_id)
        session_paths = self.runtime_paths.session_paths(session_id)
        effective_runtime_config: dict[str, object] = {}
        pack_root = self.runtime_paths.packs / session.pack
        if pack_root.is_dir():
            from .models import build_effective_session_runtime_config
            from .pack_loader import load_pack_manifest

            effective_runtime_config = build_effective_session_runtime_config(
                session=session,
                pack_manifest=load_pack_manifest(pack_root),
                default_poll_interval=0.05,
            ).to_dict()
        tasks = sorted(
            (
                *self.list_ready_tasks(session_id),
                *self.list_active_tasks(session_id),
                *self.list_done_tasks(session_id),
                *self.list_blocked_tasks(session_id),
            ),
            key=lambda task: (task.exec_order, task.task_id),
        )
        done_count = sum(1 for task in tasks if task.status == "done")
        blocked_count = sum(1 for task in tasks if task.status == "blocked")
        active_count = sum(1 for task in tasks if task.status == "active")
        ready_count = sum(1 for task in tasks if task.status == "ready")
        started_reference = session.started_at or session.created_at
        completed_reference = session.completed_at or session.started_at or session.created_at
        summary: dict[str, object] = {
            "session": {
                "id": session.id,
                "name": session.name,
                "pack": session.pack,
                "status": session.status,
                "created_at": session.created_at,
                "started_at": session.started_at,
                "completed_at": session.completed_at,
                "duration_seconds": _duration_seconds(started_reference, completed_reference),
                "config": _decode_config_json(session.config_json),
                "effective_runtime_config": effective_runtime_config,
                "runtime_state": {
                    "completed_since_verification": session.runtime_state.completed_since_verification,
                    "verification_pending": session.runtime_state.verification_pending,
                    "verification_reason": session.runtime_state.verification_reason,
                    "auto_fix_context": session.runtime_state.auto_fix_context,
                    "auto_fix_task_id": session.runtime_state.auto_fix_task_id,
                    "auto_fix_attempt": session.runtime_state.auto_fix_attempt,
                    "last_fix_summary": session.runtime_state.last_fix_summary,
                },
            },
            "pipeline": {
                "intake": 0,
                "planning": 0,
                "staged": 0,
                "review": 0,
                "ready": ready_count,
                "active": active_count,
                "done": done_count,
                "blocked": blocked_count,
            },
            "tasks": [
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "status": task.status,
                    "depends_on": list(task.depends_on),
                    "anti_affinity": list(task.anti_affinity),
                    "exec_order": task.exec_order,
                    "full_test_after": task.full_test_after,
                    "created_at": task.created_at,
                    "started_at": task.started_at,
                    "completed_at": task.completed_at,
                }
                for task in tasks
            ],
            "worker_statistics": {
                "slots_seen": sorted(
                    slot.slot_number
                    for slot in self.list_worker_slots(session_id)
                ),
                "configured_worker_count": max(
                    (slot.slot_number for slot in self.list_worker_slots(session_id)),
                    default=-1,
                )
                + 1,
            },
            "artifacts": {
                "summary_path": "summary.json",
                "resolution_path": "resolution.json",
                "session_log_path": "logs/session.log",
            },
        }
        if session_paths.release_notes.is_file():
            summary["artifacts"]["release_notes_path"] = "RELEASE_NOTES.md"
        _atomic_write_text(session_paths.summary, json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return summary

    def read_session_summary(self, session_id: str) -> dict[str, object] | None:
        summary_path = self.runtime_paths.session_paths(session_id).summary
        if not summary_path.is_file():
            return None
        return json.loads(summary_path.read_text(encoding="utf-8"))

    def trim_successful_session_artifacts(self, session_id: str) -> None:
        session_paths = self.runtime_paths.session_paths(session_id)
        keep_files = {
            session_paths.summary.resolve(),
            session_paths.resolution.resolve(),
            session_paths.session_log.resolve(),
        }
        if session_paths.release_notes.is_file():
            keep_files.add(session_paths.release_notes.resolve())
        if not session_paths.root.exists():
            return
        for path in sorted(session_paths.root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
            resolved = path.resolve()
            if path.is_file():
                if resolved in keep_files:
                    continue
                path.unlink()
                continue
            if path in {session_paths.root, session_paths.logs}:
                continue
            if path.exists():
                try:
                    path.rmdir()
                except OSError:
                    continue

    def write_successful_session_release_notes(self, session_id: str) -> str | None:
        session = self.get_session(session_id)
        session_paths = self.runtime_paths.session_paths(session_id)
        done_tasks = sorted(
            self.list_done_tasks(session_id),
            key=lambda task: (task.exec_order, task.task_id),
        )
        sections: list[tuple[str, str, str]] = []
        for task in done_tasks:
            if not task.plan_path.is_file():
                continue
            try:
                plan = parse_task_plan(task.plan_path.read_text(encoding="utf-8"), source=task.plan_path)
            except ArtifactParseError:
                continue
            operator_actions = extract_operator_actions_section(plan.body)
            if operator_actions is None:
                continue
            sections.append((task.task_id, task.title, operator_actions))

        if not sections:
            if session_paths.release_notes.exists():
                session_paths.release_notes.unlink()
            return None

        lines = [
            "# Release Notes",
            "",
            f"Session: {session.name} ({session.id})",
            f"Pack: {session.pack}",
        ]
        if session.completed_at is not None:
            lines.append(f"Completed: {session.completed_at}")
        for task_id, title, operator_actions in sections:
            lines.extend(
                [
                    "",
                    f"## {task_id} {title}",
                    "",
                    operator_actions,
                ]
            )
        _atomic_write_text(session_paths.release_notes, "\n".join(lines).rstrip() + "\n")
        return "RELEASE_NOTES.md"

    def purge_expired_sessions(
        self,
        *,
        retention_days: int,
        now: str | None = None,
        pre_delete: collections.abc.Callable[[SessionRecord], None] | None = None,
    ) -> tuple[str, ...]:
        if retention_days <= 0:
            return ()
        reference_time = _parse_utc_timestamp(now) if now is not None else datetime.now(UTC)
        cutoff = reference_time - timedelta(days=retention_days)
        expired = [
            session
            for session in self.list_sessions()
            if session.status in {"completed", "aborted"}
            and session.completed_at is not None
            and _parse_utc_timestamp(session.completed_at) < cutoff
        ]
        for session in expired:
            if pre_delete is not None:
                pre_delete(session)
            self.delete_session(session.id)
        return tuple(s.id for s in expired)

    def list_worker_slots(self, session_id: str) -> tuple[WorkerSlotRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, slot_number, status, current_task_id
                FROM worker_slots
                WHERE session_id = ?
                ORDER BY slot_number ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(
            WorkerSlotRecord(
                session_id=row["session_id"],
                slot_number=row["slot_number"],
                status=row["status"],
                current_task_id=row["current_task_id"],
            )
            for row in rows
        )

    def append_event(
        self,
        session_id: str,
        *,
        timestamp: str,
        event_type: str,
        message: str,
        task_id: str | None = None,
    ) -> SessionEvent:
        # Write to session.log BEFORE committing to DB so that a crash between
        # the two leaves the log ahead of the DB (recoverable) rather than the
        # DB ahead of the log (undetectable divergence). F-1 fix.
        session_log_path = self.runtime_paths.session_paths(session_id).session_log
        session_log_path.parent.mkdir(parents=True, exist_ok=True)
        task_segment = f" [{task_id}]" if task_id is not None else ""
        with session_log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {event_type}{task_segment} {message}\n")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events (session_id, timestamp, event_type, task_id, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, timestamp, event_type, task_id, message),
            )
            connection.commit()
        return SessionEvent(
            session_id=session_id,
            timestamp=timestamp,
            event_type=event_type,
            task_id=task_id,
            message=message,
        )

    def list_events(self, session_id: str) -> tuple[SessionEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, timestamp, event_type, task_id, message
                FROM events
                WHERE session_id = ?
                ORDER BY timestamp ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(
            SessionEvent(
                session_id=row["session_id"],
                timestamp=row["timestamp"],
                event_type=row["event_type"],
                task_id=row["task_id"],
                message=row["message"],
            )
            for row in rows
        )

    def get_task_events(self, session_id: str, task_id: str) -> tuple[SessionEvent, ...]:
        """Return all events for a specific task, ordered by timestamp ASC, id ASC."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, timestamp, event_type, task_id, message
                FROM events
                WHERE session_id = ? AND task_id = ?
                ORDER BY timestamp ASC, id ASC
                """,
                (session_id, task_id),
            ).fetchall()
        return tuple(
            SessionEvent(
                session_id=row["session_id"],
                timestamp=row["timestamp"],
                event_type=row["event_type"],
                task_id=row["task_id"],
                message=row["message"],
            )
            for row in rows
        )

    def delete_task(self, session_id: str, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM tasks
                WHERE session_id = ? AND task_id = ?
                """,
                (session_id, task_id),
            )
            connection.commit()

    def delete_session(self, session_id: str) -> None:
        session_root = self.runtime_paths.session(session_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM worker_slots WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM tasks WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            connection.commit()
        if session_root.exists():
            shutil.rmtree(session_root)

    def write_worker_recovery_metadata(
        self,
        session_id: str,
        *,
        slot_number: int,
        task_id: str,
        workspace_path: Path,
        pid: int | None,
    ) -> WorkerRecoveryMetadata:
        metadata = WorkerRecoveryMetadata(
            session_id=session_id,
            slot_number=slot_number,
            task_id=task_id,
            workspace_path=workspace_path.resolve(),
            pid=pid,
        )
        recovery_path = self.runtime_paths.session_paths(session_id).worker_recovery_path(slot_number)
        # Use _atomic_write_text so a crash mid-write leaves the old file intact
        # rather than a truncated/missing file. F-6 fix.
        _atomic_write_text(
            recovery_path,
            json.dumps(
                {
                    "task_id": metadata.task_id,
                    "workspace_path": str(metadata.workspace_path),
                    "pid": metadata.pid,
                }
            )
            + "\n",
        )
        return metadata

    def read_worker_recovery_metadata(
        self,
        session_id: str,
        *,
        slot_number: int,
    ) -> WorkerRecoveryMetadata | None:
        recovery_path = self.runtime_paths.session_paths(session_id).worker_recovery_path(slot_number)
        if not recovery_path.is_file():
            return None
        payload = json.loads(recovery_path.read_text(encoding="utf-8"))
        return WorkerRecoveryMetadata(
            session_id=session_id,
            slot_number=slot_number,
            task_id=payload["task_id"],
            workspace_path=Path(payload["workspace_path"]),
            pid=payload.get("pid"),
        )

    def clear_worker_recovery_metadata(self, session_id: str, *, slot_number: int) -> None:
        recovery_path = self.runtime_paths.session_paths(session_id).worker_recovery_path(slot_number)
        if recovery_path.exists():
            recovery_path.unlink()

    def reconcile_filesystem_projection(
        self,
        session_id: str,
        *,
        session_status: str | None = None,
    ) -> dict[str, Any]:
        session_paths = self.runtime_paths.session_paths(session_id)
        filesystem_state: dict[str, tuple[str, Path, int | None]] = {}
        for status, directory in (
            ("planning", session_paths.claimed),
            ("staged", session_paths.staging),
            ("review", session_paths.review),
            ("ready", session_paths.ready),
            ("done", session_paths.done),
            ("blocked", session_paths.blocked),
        ):
            for plan_path in sorted(directory.glob("*.plan.md")):
                filesystem_state[plan_path.name.removesuffix(".plan.md")] = (status, plan_path, None)
        for worker_dir in sorted(path for path in session_paths.workers.iterdir() if path.is_dir()):
            if not worker_dir.name.isdigit():
                continue
            slot_number = int(worker_dir.name)
            for plan_path in sorted(worker_dir.glob("*.plan.md")):
                filesystem_state[plan_path.name.removesuffix(".plan.md")] = (
                    "active",
                    plan_path,
                    slot_number,
                )

        reconciled: list[dict[str, str]] = []
        orphaned: list[str] = []
        unchanged = 0

        with self._connect() as connection:
            task_rows = connection.execute(
                """
                SELECT task_id, status, worker_slot, plan_relpath, created_at, started_at, completed_at
                FROM tasks
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchall()
            old_statuses = {row["task_id"]: row["status"] for row in task_rows}
            for row in task_rows:
                task_id = row["task_id"]
                if task_id not in filesystem_state:
                    # Task exists in DB but plan file is missing from filesystem.
                    # Mark it blocked so the orchestrator doesn't try to operate on it.
                    if row["status"] not in ("done", "blocked"):
                        orphaned.append(task_id)
                        connection.execute(
                            """
                            UPDATE tasks
                            SET status = 'blocked', worker_slot = NULL, completed_at = ?
                            WHERE session_id = ? AND task_id = ? AND status NOT IN ('done', 'blocked')
                            """,
                            (datetime.now(UTC).isoformat(), session_id, task_id),
                        )
                    else:
                        unchanged += 1
                    continue
                status, plan_path, worker_slot = filesystem_state[task_id]
                old_status = old_statuses[task_id]
                completed_at = row["completed_at"]
                started_at = row["started_at"]
                if status in ("planning", "staged", "review", "ready"):
                    started_at = None
                    completed_at = None
                elif status not in ("done", "blocked"):
                    completed_at = None
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, worker_slot = ?, plan_relpath = ?, started_at = ?, completed_at = ?
                    WHERE session_id = ? AND task_id = ?
                    """,
                    (
                        status,
                        worker_slot,
                        self._relative_to_session(session_id, plan_path),
                        started_at,
                        completed_at,
                        session_id,
                        task_id,
                    ),
                )
                if old_status != status:
                    reconciled.append({"task_id": task_id, "old_status": old_status, "new_status": status})
                else:
                    unchanged += 1

            existing_slots = {
                row["slot_number"]
                for row in connection.execute(
                    "SELECT slot_number FROM worker_slots WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
            }
            active_slots = {
                worker_slot: task_id
                for task_id, (status, _path, worker_slot) in filesystem_state.items()
                if status == "active" and worker_slot is not None
            }
            for slot_number in sorted(existing_slots | set(active_slots)):
                if slot_number in active_slots:
                    self._upsert_worker_slot(
                        connection,
                        session_id,
                        slot_number,
                        "active",
                        active_slots[slot_number],
                    )
                else:
                    self._upsert_worker_slot(
                        connection,
                        session_id,
                        slot_number,
                        "idle",
                        None,
                    )

            if session_status is not None:
                connection.execute(
                    "UPDATE sessions SET status = ? WHERE id = ?",
                    (session_status, session_id),
                )
            connection.commit()

        return {"reconciled": reconciled, "orphaned": orphaned, "unchanged": unchanged}

    def _list_tasks(self, session_id: str, *, status: str) -> tuple[PersistedTask, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, task_id, title, status, worker_slot, depends_on_json,
                       anti_affinity_json, exec_order, full_test_after, plan_relpath,
                       created_at, started_at, completed_at
                FROM tasks
                WHERE session_id = ? AND status = ?
                ORDER BY exec_order ASC, task_id ASC
                """,
                (session_id, status),
            ).fetchall()
        return tuple(self._task_from_row(row) for row in rows)

    def _task_from_row(self, row: sqlite3.Row) -> PersistedTask:
        session_paths = self.runtime_paths.session(row["session_id"])
        return PersistedTask(
            session_id=row["session_id"],
            task_id=row["task_id"],
            title=row["title"],
            depends_on=tuple(json.loads(row["depends_on_json"])),
            anti_affinity=tuple(json.loads(row["anti_affinity_json"])),
            exec_order=row["exec_order"],
            full_test_after=bool(row["full_test_after"]),
            status=row["status"],
            plan_path=session_paths / row["plan_relpath"],
            worker_slot=row["worker_slot"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    def _session_from_row(self, row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            name=row["name"],
            pack=row["pack"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            config_json=row["config_json"],
            completed_at=row["completed_at"],
            runtime_state=self._decode_runtime_state(row["runtime_state_json"]),
        )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def _relative_to_session(self, session_id: str, path: Path) -> str:
        return str(path.relative_to(self.runtime_paths.session(session_id)))

    def _normalize_worker_slot(self, *, status: str, worker_slot: int | None) -> int | None:
        if status == "active":
            if worker_slot is None:
                raise ValueError("worker_slot is required when status is active")
            if worker_slot < 0:
                raise ValueError("worker_slot must be non-negative")
            return worker_slot
        if worker_slot is not None:
            raise ValueError("worker_slot is only valid when status is active")
        return None

    def _session_exists(self, connection: sqlite3.Connection, session_id: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return row is not None

    def _task_exists(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        task_id: str,
    ) -> bool:
        row = connection.execute(
            "SELECT 1 FROM tasks WHERE session_id = ? AND task_id = ?",
            (session_id, task_id),
        ).fetchone()
        return row is not None

    def _upsert_worker_slot(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        slot_number: int | None,
        status: str,
        current_task_id: str | None,
    ) -> None:
        if slot_number is None:
            return
        connection.execute(
            """
            INSERT INTO worker_slots (session_id, slot_number, status, current_task_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id, slot_number)
            DO UPDATE SET status = excluded.status, current_task_id = excluded.current_task_id
            """,
            (session_id, slot_number, status, current_task_id),
        )

    def _encode_tuple(self, values: tuple[str, ...]) -> str:
        return json.dumps(list(values))

    def _encode_runtime_state(self, runtime_state: SessionRuntimeState) -> str:
        return json.dumps(
            {
                "completed_since_verification": runtime_state.completed_since_verification,
                "verification_pending": runtime_state.verification_pending,
                "verification_reason": runtime_state.verification_reason,
                "verification_started_at": runtime_state.verification_started_at,
                "auto_fix_context": runtime_state.auto_fix_context,
                "auto_fix_task_id": runtime_state.auto_fix_task_id,
                "auto_fix_attempt": runtime_state.auto_fix_attempt,
                "last_fix_summary": runtime_state.last_fix_summary,
                "run_number": runtime_state.run_number,
                "run_started_at": runtime_state.run_started_at,
                "accumulated_elapsed_seconds": runtime_state.accumulated_elapsed_seconds,
                "last_run_elapsed_seconds": runtime_state.last_run_elapsed_seconds,
                "dispatch_frozen": runtime_state.dispatch_frozen,
                "dispatch_frozen_reason": runtime_state.dispatch_frozen_reason,
                "last_verification_test_summary": runtime_state.last_verification_test_summary,
            }
        )

    def _decode_runtime_state(self, payload: str | None) -> SessionRuntimeState:
        if not payload:
            return SessionRuntimeState()
        data = json.loads(payload)
        return SessionRuntimeState(
            completed_since_verification=int(data.get("completed_since_verification", 0)),
            verification_pending=bool(data.get("verification_pending", False)),
            verification_reason=data.get("verification_reason"),
            verification_started_at=data.get("verification_started_at"),
            auto_fix_context=data.get("auto_fix_context"),
            auto_fix_task_id=data.get("auto_fix_task_id"),
            auto_fix_attempt=int(data.get("auto_fix_attempt", 0)),
            last_fix_summary=data.get("last_fix_summary"),
            run_number=int(data.get("run_number", 0)),
            run_started_at=data.get("run_started_at"),
            accumulated_elapsed_seconds=int(data.get("accumulated_elapsed_seconds", 0)),
            last_run_elapsed_seconds=int(data.get("last_run_elapsed_seconds", 0)),
            dispatch_frozen=bool(data.get("dispatch_frozen", False)),
            dispatch_frozen_reason=data.get("dispatch_frozen_reason"),
            last_verification_test_summary=data.get("last_verification_test_summary"),
        )


def initialize_state_store(runtime_paths: RuntimePaths) -> StateStore:
    runtime_paths.home.mkdir(parents=True, exist_ok=True)
    runtime_paths.sessions.mkdir(parents=True, exist_ok=True)
    runtime_paths.packs.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(runtime_paths.database, timeout=10) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in _SCHEMA:
            connection.execute(statement)
        _ensure_column(connection, "sessions", "started_at", "TEXT")
        _ensure_column(connection, "sessions", "runtime_state_json", "TEXT NOT NULL DEFAULT '{}'")
        connection.commit()
    return StateStore(runtime_paths=runtime_paths)


def _parse_utc_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _duration_seconds(started_at: str | None, completed_at: str | None) -> int:
    if not started_at or not completed_at:
        return 0
    return max(0, int((_parse_utc_timestamp(completed_at) - _parse_utc_timestamp(started_at)).total_seconds()))


def _decode_config_json(config_json: str | None) -> dict[str, object]:
    if not config_json:
        return {}
    return json.loads(config_json)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing = {row[1] for row in rows}
    if column_name in existing:
        return
    connection.execute(
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
    )
