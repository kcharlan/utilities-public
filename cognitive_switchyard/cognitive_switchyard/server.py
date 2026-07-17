from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from .config import (
    GlobalConfig,
    RuntimePaths,
    ensure_global_config,
    load_global_config,
    write_global_config,
)
from .html_template import render_app_html
from .models import (
    BackendRuntimeEvent,
    build_effective_session_runtime_config,
    HookInvocationResult,
    PackManifest,
    PackPreflightResult,
    PersistedTask,
    PrerequisiteReport,
    ScriptPermissionReport,
    SessionRecord,
    parse_session_config_overrides,
    WorkerCardRuntimeState,
    apply_runtime_event_to_worker_card_state,
)
from .orchestrator import run_session_preflight, start_session
from .pack_loader import list_runtime_pack_names, load_pack_manifest
from .parsers import ArtifactParseError, parse_progress_line
from .planning_runtime import _INTAKE_META_FILES
from .state import StateStore, initialize_state_store

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    id: str
    name: str | None = None
    pack: str | None = None
    config: dict[str, Any] | None = None


class ResolvePathRequest(BaseModel):
    path: str


class CreateBranchRequest(BaseModel):
    repo_path: str
    branch_name: str
    from_branch: str = "main"


class UpdateSettingsRequest(BaseModel):
    retention_days: int = 30
    default_planners: int = 3
    default_workers: int = 3
    default_pack: str = "claude-code"
    terminal_app: str = "iTerm"


class MoveTaskRequest(BaseModel):
    target_status: str


VALID_TASK_TRANSITIONS: dict[str, set[str]] = {
    "blocked": {"ready", "intake"},
    "review": {"intake", "ready"},
    "done": {"intake", "ready"},
    "staged": {"intake", "review"},
    "planning": {"intake"},
    "ready": {"intake", "staged"},
}


CommandRunner = Callable[[list[str]], None]


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self.log_subscriptions: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._event_loop = asyncio.get_running_loop()
        _debug(
            "ConnectionManager.connect: captured event_loop=%s thread=%s",
            self._event_loop,
            threading.current_thread().name,
        )
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            for subscribers in self.log_subscriptions.values():
                subscribers.discard(websocket)

    async def subscribe_logs(self, websocket: WebSocket, worker_slot: int) -> None:
        async with self._lock:
            self.log_subscriptions.setdefault(worker_slot, set()).add(websocket)

    async def unsubscribe_logs(self, websocket: WebSocket, worker_slot: int) -> None:
        async with self._lock:
            self.log_subscriptions.setdefault(worker_slot, set()).discard(websocket)

    async def broadcast_state(self, state: dict[str, Any]) -> None:
        _debug(
            "broadcast_state: connections=%d thread=%s loop=%s",
            len(self.active_connections),
            threading.current_thread().name,
            id(asyncio.get_running_loop()) if asyncio.get_running_loop() else "none",
        )
        await self._broadcast({"type": "state_update", "data": state})
        _debug("broadcast_state: done")

    async def send_log_line(self, slot: int, payload: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = tuple(self.log_subscriptions.get(slot, set()))
        await self._send_many(subscribers, {"type": "log_line", "data": payload})

    async def broadcast_task_status_change(self, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": "task_status_change", "data": payload})

    async def broadcast_phase_log(self, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": "log_line", "data": payload})

    async def broadcast_progress_detail(self, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": "progress_detail", "data": payload})

    async def broadcast_alert(self, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": "alert", "data": payload})

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            connections = tuple(self.active_connections)
        await self._send_many(connections, payload)

    async def _send_many(self, connections: tuple[WebSocket, ...], payload: dict[str, Any]) -> None:
        _debug("_send_many: sending to %d connections, thread=%s", len(connections), threading.current_thread().name)
        stale: list[WebSocket] = []
        for connection in connections:
            try:
                _debug("_send_many: sending to connection %s", id(connection))
                await connection.send_json(payload)
                _debug("_send_many: sent successfully")
            except Exception as exc:
                _debug("_send_many: send failed: %s", exc)
                stale.append(connection)
        for connection in stale:
            await self.disconnect(connection)
        _debug("_send_many: complete")

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop | None:
        return self._event_loop


def _build_session_env(
    session: SessionRecord,
    pack_manifest: PackManifest,
    poll_interval: float = 0.05,
) -> dict[str, str]:
    """Build the environment dict for a session from its config overrides.

    Mirrors the env-building logic in ``start_session`` so that preflight
    and other pre-start operations see the same variables (e.g.
    COGNITIVE_SWITCHYARD_REPO_ROOT) that execution will use.
    """
    effective = build_effective_session_runtime_config(
        session=session,
        pack_manifest=pack_manifest,
        default_poll_interval=poll_interval,
    )
    env: dict[str, str] = {}
    env.update(effective.environment)
    env["COGNITIVE_SWITCHYARD_PACK_ROOT"] = str(pack_manifest.root)
    return env


class SessionController:
    def __init__(
        self,
        *,
        store: StateStore,
        runtime_paths: RuntimePaths,
        connection_manager: ConnectionManager,
    ) -> None:
        self.store = store
        self.runtime_paths = runtime_paths
        self.connection_manager = connection_manager
        self._threads: dict[str, threading.Thread] = {}
        self._worker_card_state: dict[str, dict[int, WorkerCardRuntimeState]] = {}
        self._idle_state_cache: dict[str, dict[int, dict]] = {}  # session_id -> {slot -> idle fields}
        self._last_idle_snapshot: dict[str, float] = {}  # session_id -> monotonic time of last idle snapshot
        self._planning_agents: dict[str, dict[str, Any]] = {}  # session_id -> {planner_task_id -> info}
        self._pack_cache: dict[str, PackManifest] = {}
        self._lock = threading.Lock()

    def has_active_thread(self, session_id: str) -> bool:
        with self._lock:
            thread = self._threads.get(session_id)
            return thread is not None and thread.is_alive()

    def create_session(
        self,
        *,
        session_id: str,
        name: str,
        pack: str,
        config_json: str | None = None,
    ) -> SessionRecord:
        return self.store.create_session(
            session_id=session_id,
            name=name,
            pack=pack,
            created_at=_timestamp(),
            config_json=config_json,
            pre_delete=cleanup_session_worktree_if_needed,
        )

    def start(self, session_id: str) -> None:
        self._launch_background_session(session_id)

    def preflight(self, session_id: str) -> PackPreflightResult:
        session = self.store.get_session(session_id)
        pack_manifest = load_pack_manifest(self.runtime_paths.packs / session.pack)
        env = _build_session_env(session, pack_manifest)
        return run_session_preflight(
            store=self.store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=env,
        )

    def pause(self, session_id: str) -> None:
        self.store.update_session_status(session_id, status="paused")
        self._publish_snapshot(session_id)

    def resume(self, session_id: str) -> None:
        session = self.store.get_session(session_id)
        if session.status == "idle":
            # Starting a new run from idle — launch background session
            # (execute_session handles idle→running transition and run tracking)
            self._launch_background_session(session_id)
            self._publish_snapshot(session_id)
            return
        if session.status in ("verifying", "auto_fixing"):
            # Interrupted mid-verification/fix — preserve real status so
            # execute_session triggers recovery verification replay.
            self._launch_background_session(session_id)
            self._publish_snapshot(session_id)
            return
        self.store.update_session_status(session_id, status="running")
        self._publish_snapshot(session_id)
        self._launch_background_session(session_id)

    def abort(self, session_id: str) -> None:
        self.store.update_session_status(
            session_id,
            status="aborted",
            completed_at=_timestamp(),
        )
        self._publish_snapshot(session_id)

    def end_session(self, session_id: str) -> None:
        """Explicitly end an idle session: write summary, trim artifacts, cleanup worktree."""
        session = self.store.get_session(session_id)
        if session.status != "idle":
            raise ValueError(f"Can only end idle sessions, got {session.status!r}")
        completed_at = _timestamp()
        self.store.update_session_status(
            session_id,
            status="completed",
            completed_at=completed_at,
        )
        self.store.append_event(
            session_id,
            timestamp=completed_at,
            event_type="session.completed",
            message="Session ended by operator.",
        )
        self.store.write_successful_session_release_notes(session_id)
        self.store.write_successful_session_summary(session_id)
        self.store.trim_successful_session_artifacts(session_id)
        self._cleanup_worktree(self.store.get_session(session_id))
        self._publish_snapshot(session_id)

    def reprocess(self, session_id: str) -> None:
        """Re-run the planning→resolution→execution pipeline on existing filesystem state."""
        session = self.store.get_session(session_id)

        allowed_statuses = {"created", "idle", "paused"}
        if session.status not in allowed_statuses:
            raise ValueError(
                f"Cannot reprocess session in status '{session.status}'; "
                f"must be one of {sorted(allowed_statuses)}"
            )

        for slot in self.store.list_worker_slots(session_id):
            if slot.status == "active":
                raise ValueError("Cannot reprocess while workers are active")

        session_paths = self.runtime_paths.session_paths(session_id)

        # Delete resolution.json so the resolver re-runs
        session_paths.resolution.unlink(missing_ok=True)

        # Delete DB task rows for tasks in staging/ and intake/ so they
        # can be re-created cleanly by the planning and resolution phases
        for plan_path in session_paths.staging.glob("*.plan.md"):
            task_id = plan_path.name.removesuffix(".plan.md")
            try:
                self.store.delete_task(session_id, task_id)
            except Exception:
                pass

        for plan_path in session_paths.intake.glob("*.md"):
            task_id = plan_path.name.removesuffix(".plan.md").removesuffix(".md")
            try:
                self.store.delete_task(session_id, task_id)
            except Exception:
                pass

        # Reconcile filesystem state into DB before launching
        self.store.reconcile_filesystem_projection(session_id)

        # Reset to 'created' so prepare_session_for_execution's status guard allows entry
        self.store.update_session_status(session_id, status="created")

        self.store.append_event(
            session_id,
            timestamp=_timestamp(),
            event_type="session.reprocess",
            message="Reprocessing pipeline from current filesystem state.",
        )

        self._publish_snapshot(session_id)
        self._launch_background_session(session_id)

    def retry_task(self, session_id: str, task_id: str) -> PersistedTask:
        task = self.store.get_task(session_id, task_id)
        if task.status == "ready":
            return task
        retried = self.store.project_task(
            session_id,
            task_id,
            status="ready",
        )
        self._publish_snapshot(session_id)
        return retried

    def _cleanup_task_worktree(self, session_id: str, task_id: str) -> None:
        """Remove per-task isolation branch, if any."""
        session = self.store.get_session(session_id)
        try:
            config = parse_session_config_overrides(session.config_json)
            env = config.environment or {}
        except (ValueError, Exception):
            return
        source_repo = env.get("COGNITIVE_SWITCHYARD_SOURCE_REPO", "")
        repo_root = env.get("COGNITIVE_SWITCHYARD_REPO_ROOT", "")
        if not source_repo or not repo_root or source_repo == repo_root:
            return
        branch_name = f"switchyard-{task_id}"
        try:
            subprocess.run(
                ["git", "-C", source_repo, "branch", "-D", branch_name],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            pass

    def move_task(self, session_id: str, task_id: str, target_status: str) -> dict[str, str]:
        task = self.store.get_task(session_id, task_id)
        if task.status == target_status:
            return {"status": "no-op", "from": task.status, "to": target_status}

        allowed = VALID_TASK_TRANSITIONS.get(task.status)
        if allowed is None or target_status not in allowed:
            raise ValueError(f"Cannot move task from '{task.status}' to '{target_status}'")

        # Guard against moving active worker tasks
        if task.status == "active":
            for slot in self.store.list_worker_slots(session_id):
                if slot.current_task_id == task_id and slot.status == "active":
                    raise ValueError("Task is currently being executed by a worker")

        # Clean up per-task worktree when moving backward from done/blocked
        backward_from = {"done", "blocked"}
        backward_to = {"intake", "staged"}
        if task.status in backward_from and target_status in backward_to:
            self._cleanup_task_worktree(session_id, task_id)

        session_paths = self.runtime_paths.session_paths(session_id)

        if target_status == "intake":
            dest = session_paths.intake / task.plan_path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            task.plan_path.replace(dest)
            self.store.delete_task(session_id, task_id)
        else:
            self.store.project_task(session_id, task_id, status=target_status)

        self._publish_snapshot(session_id)
        return {"status": "moved", "from": task.status, "to": target_status}

    def _launch_background_session(self, session_id: str) -> None:
        with self._lock:
            thread = self._threads.get(session_id)
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._run_session,
                args=(session_id,),
                name=f"switchyard-session-{session_id}",
                daemon=True,
            )
            self._threads[session_id] = thread
            thread.start()

    def _run_session(self, session_id: str) -> None:
        try:
            session = self.store.get_session(session_id)
            pack_manifest = load_pack_manifest(self.runtime_paths.packs / session.pack)
            result = start_session(
                store=self.store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                env=None,
                poll_interval=0.05,
                runtime_event_sink=self._publish_runtime_event,
            )
            if not result.started:
                parts: list[str] = []
                if result.review_tasks:
                    parts.append(f"Tasks sent to review: {', '.join(result.review_tasks)}")
                if result.resolution_conflicts:
                    parts.append(f"Resolution conflicts: {', '.join(result.resolution_conflicts)}")
                reason = "; ".join(parts) if parts else "Pipeline stopped before execution"
                self.store.append_event(
                    session_id,
                    timestamp=_timestamp(),
                    event_type="pipeline_stopped",
                    message=reason,
                )
                self._broadcast_alert(session_id, reason, severity="warning")
        except Exception:
            import logging
            import traceback
            logging.getLogger(__name__).exception(
                "Session %s crashed with unhandled exception", session_id
            )
            error_detail = traceback.format_exc()
            try:
                self.store.update_session_status(
                    session_id,
                    status="aborted",
                    completed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                )
                self.store.append_event(
                    session_id,
                    timestamp=_timestamp(),
                    event_type="session_error",
                    message=error_detail[-500:],
                )
            except Exception:
                pass
        # Clean up worktree when session finishes.
        # Idle sessions: keep worktree for further runs.
        # Aborted sessions: clean up immediately.
        # Completed sessions: defer — the completion card needs the worktree for
        # validation/merge instructions; cleanup is triggered via
        # POST /api/sessions/{id}/cleanup-worktree or on session purge.
        try:
            finished_session = self.store.get_session(session_id)
            if finished_session.status == "aborted":
                self._cleanup_worktree(finished_session)
        except Exception:
            pass
        self._publish_snapshot(session_id)

    def _cleanup_worktree(self, session: SessionRecord) -> None:
        """Remove the git worktree for a finished session."""
        cleanup_session_worktree_if_needed(session)

    def _broadcast_alert(self, session_id: str, message: str, *, severity: str = "warning") -> None:
        event = BackendRuntimeEvent(
            message_type="alert",
            session_id=session_id,
            data={"severity": severity, "message": message},
        )
        self._publish_runtime_event(event)

    def _publish_snapshot(self, session_id: str) -> None:
        _debug(
            "_publish_snapshot: session=%s connections=%d event_loop=%s",
            session_id,
            len(self.connection_manager.active_connections),
            self.connection_manager.event_loop,
        )
        try:
            state = build_dashboard_payload(
                self.store,
                session_id,
                runtime_paths=self.runtime_paths,
                worker_card_state=self.get_worker_card_state(session_id),
                planning_agents=self.get_planning_agents(session_id),
                pack_manifest=self._get_cached_pack_manifest(session_id),
                idle_state=self.get_idle_state(session_id),
            )
        except KeyError:
            _debug("_publish_snapshot: KeyError for session %s, skipping", session_id)
            return
        _run_async(
            self.connection_manager.broadcast_state(state),
            loop=self.connection_manager.event_loop,
        )

    def _publish_runtime_event(self, event: BackendRuntimeEvent) -> None:
        if event.message_type == "worker_idle_state":
            activity_advanced = self._update_idle_state_cache(event)
            # Keep the idle timer server-authoritative. Publish immediately when
            # meaningful activity advanced last_output_at; otherwise throttle to
            # one snapshot per second so the UI timer keeps moving without
            # flooding clients on heartbeat-only polls.
            now = time.monotonic()
            last = self._last_idle_snapshot.get(event.session_id, 0.0)
            if activity_advanced or now - last >= 1.0:
                self._last_idle_snapshot[event.session_id] = now
                self._publish_snapshot(event.session_id)
            return

        self._update_worker_card_state(event)
        if event.message_type == "state_update":
            self._publish_snapshot(event.session_id)
            return
        if event.message_type == "task_status_change":
            _run_async(
                self.connection_manager.broadcast_task_status_change(event.data),
                loop=self.connection_manager.event_loop,
            )
            return
        if event.message_type == "progress_detail":
            _run_async(
                self.connection_manager.broadcast_progress_detail(event.data),
                loop=self.connection_manager.event_loop,
            )
            return
        if event.message_type == "alert":
            _run_async(
                self.connection_manager.broadcast_alert(event.data),
                loop=self.connection_manager.event_loop,
            )
            return
        if event.message_type == "preparation_status":
            self._publish_snapshot(event.session_id)
            return
        if event.message_type == "pipeline_event":
            evt_name = event.data.get("event")
            if evt_name == "planner_started":
                with self._lock:
                    agents = self._planning_agents.setdefault(event.session_id, {})
                    agents[event.data["planner_task_id"]] = {
                        "file": event.data["file"],
                        "started_at": _timestamp(),
                    }
            elif evt_name in ("planner_finished", "file_unclaimed"):
                ptid = event.data.get("planner_task_id")
                if ptid:
                    with self._lock:
                        self._planning_agents.get(event.session_id, {}).pop(ptid, None)
            self._publish_snapshot(event.session_id)
            return
        if event.message_type == "log_line":
            worker_slot = event.data.get("worker_slot")
            if isinstance(worker_slot, int):
                if worker_slot < 0:
                    # Phase-level log lines (planning, resolution, auto-fix)
                    # go to all connected clients, not slot subscribers.
                    _run_async(
                        self.connection_manager.broadcast_phase_log(event.data),
                        loop=self.connection_manager.event_loop,
                    )
                else:
                    _run_async(
                        self.connection_manager.send_log_line(worker_slot, event.data),
                        loop=self.connection_manager.event_loop,
                    )

    def get_planning_agents(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._planning_agents.get(session_id, {}))

    def get_worker_card_state(self, session_id: str) -> dict[int, WorkerCardRuntimeState]:
        with self._lock:
            return dict(self._worker_card_state.get(session_id, {}))

    def get_idle_state(self, session_id: str) -> dict[int, dict]:
        with self._lock:
            return dict(self._idle_state_cache.get(session_id, {}))

    def _update_idle_state_cache(self, event: BackendRuntimeEvent) -> bool:
        with self._lock:
            slot = event.data.get("worker_slot")
            if slot is None:
                return False
            session_idle = self._idle_state_cache.setdefault(event.session_id, {})
            previous = session_idle.get(slot)
            current = {
                "task_id": event.data.get("task_id"),
                "last_output_at": event.data.get("last_output_at", 0.0),
                "task_idle": event.data.get("task_idle", 0.0),
            }
            session_idle[slot] = current

            if previous is None:
                return True

            previous_task_id = previous.get("task_id")
            current_task_id = current.get("task_id")
            if current_task_id is not None and current_task_id != previous_task_id:
                return True

            try:
                return float(current["last_output_at"]) > float(previous.get("last_output_at", 0.0))
            except (TypeError, ValueError):
                return True

    def _update_worker_card_state(self, event: BackendRuntimeEvent) -> None:
        with self._lock:
            session_cache = self._worker_card_state.setdefault(event.session_id, {})
            apply_runtime_event_to_worker_card_state(
                session_cache,
                self._phase_enriched_log_event(event),
            )

    def _get_cached_pack_manifest(self, session_id: str) -> PackManifest:
        cached = self._pack_cache.get(session_id)
        if cached is not None:
            return cached
        session = self.store.get_session(session_id)
        manifest = load_pack_manifest(self.runtime_paths.packs / session.pack)
        self._pack_cache[session_id] = manifest
        return manifest

    def _evict_session_cache(self, session_id: str) -> None:
        """Remove in-memory caches for a completed or deleted session."""
        with self._lock:
            self._worker_card_state.pop(session_id, None)
            self._idle_state_cache.pop(session_id, None)
            self._last_idle_snapshot.pop(session_id, None)
            self._pack_cache.pop(session_id, None)

    def _phase_enriched_log_event(self, event: BackendRuntimeEvent) -> BackendRuntimeEvent:
        if event.message_type != "log_line":
            return event
        line = event.data.get("line")
        task_id = event.data.get("task_id")
        if not isinstance(line, str) or not isinstance(task_id, str):
            return event
        pack_manifest = self._get_cached_pack_manifest(event.session_id)
        try:
            progress = parse_progress_line(line, progress_format=pack_manifest.status.progress_format)
        except ArtifactParseError:
            return event
        if progress.kind != "phase" or progress.task_id != task_id:
            return event
        payload = dict(event.data)
        payload["phase"] = progress.phase_name
        payload["phase_num"] = progress.phase_index
        payload["phase_total"] = progress.phase_total
        return BackendRuntimeEvent(
            message_type=event.message_type,
            session_id=event.session_id,
            data=payload,
        )


def _create_session_worktree(repo_root: str, branch: str, worktree_path: Path) -> Path:
    repo = Path(repo_root)
    if not repo.is_dir():
        raise HTTPException(status_code=400, detail=f"Repository path does not exist: {repo_root}")
    git_check = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True, timeout=5,
    )
    if git_check.returncode != 0:
        raise HTTPException(status_code=400, detail=f"Not a git repository: {repo_root}")
    # Remove stale worktree at the target path if it exists from a prior session.
    if worktree_path.exists():
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree_path)],
            capture_output=True, text=True, timeout=15,
        )
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
    # Prune stale worktree entries left by prior sessions that crashed or were
    # cleaned up without calling `git worktree remove`.
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "prune"],
        capture_output=True, text=True, timeout=10,
    )
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(worktree_path), branch],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to create worktree: {result.stderr.strip()}",
        )
    return worktree_path


def cleanup_session_worktree_if_needed(session: SessionRecord) -> None:
    """Remove the git worktree created for a session, if any.

    Safe to call on any session — silently returns if no worktree was configured.
    """
    try:
        config = parse_session_config_overrides(session.config_json)
        env = config.environment or {}
    except (ValueError, Exception):
        return
    source_repo = env.get("COGNITIVE_SWITCHYARD_SOURCE_REPO", "")
    worktree_root = env.get("COGNITIVE_SWITCHYARD_REPO_ROOT", "")
    if source_repo and worktree_root and source_repo != worktree_root:
        _cleanup_session_worktree(source_repo, worktree_root)


def _cleanup_session_worktree(source_repo: str, worktree_path: str) -> None:
    try:
        subprocess.run(
            ["git", "-C", source_repo, "worktree", "remove", "--force", worktree_path],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        pass
    wt = Path(worktree_path)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    # Prune stale worktree entries from git's internal tracking so the branch
    # can be reused immediately by a new session.
    try:
        subprocess.run(
            ["git", "-C", source_repo, "worktree", "prune"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass
    # Delete per-task isolation branches (switchyard-*) that isolate_end may
    # have failed to clean up (e.g. if isolate_end itself failed).
    try:
        result = subprocess.run(
            ["git", "-C", source_repo, "branch", "--list", "switchyard-*"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if branch:
                subprocess.run(
                    ["git", "-C", source_repo, "branch", "-D", branch],
                    capture_output=True, text=True, timeout=5,
                )
    except Exception:
        pass


def create_app(
    *,
    store: StateStore,
    runtime_paths: RuntimePaths,
    controller: SessionController | Any | None = None,
    command_runner: CommandRunner | None = None,
) -> FastAPI:
    app = FastAPI(title="Cognitive Switchyard Backend")
    connection_manager = ConnectionManager()
    session_controller = controller or SessionController(
        store=store,
        runtime_paths=runtime_paths,
        connection_manager=connection_manager,
    )
    app.state.store = store
    app.state.runtime_paths = runtime_paths
    app.state.connection_manager = connection_manager
    app.state.controller = session_controller
    app.state.command_runner = command_runner or _default_command_runner

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/")
    def read_root() -> HTMLResponse:
        return HTMLResponse(
            render_app_html(_build_root_bootstrap_payload(store, runtime_paths=runtime_paths))
        )

    @app.get("/api/packs")
    def get_packs() -> dict[str, list[dict[str, Any]]]:
        packs = []
        for pack_name in list_runtime_pack_names(runtime_paths.packs):
            manifest = load_pack_manifest(runtime_paths.packs / pack_name)
            packs.append(_serialize_pack_summary(manifest))
        return {"packs": packs}

    @app.get("/api/packs/{name}")
    def get_pack_detail(name: str) -> dict[str, Any]:
        manifest = _load_runtime_pack(runtime_paths, name)
        return _serialize_pack_detail(manifest)

    @app.post("/api/browse-directory")
    async def browse_directory() -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_folder_picker)
        return result

    @app.post("/api/resolve-path")
    def resolve_path(payload: ResolvePathRequest) -> dict[str, Any]:
        raw = payload.path.strip()
        if not raw:
            raise HTTPException(status_code=400, detail="Path must not be empty")
        resolved = Path(raw).expanduser().resolve()
        info: dict[str, Any] = {
            "resolved": str(resolved),
            "exists": resolved.exists(),
            "is_directory": resolved.is_dir(),
            "is_git": False,
            "branch": None,
            "on_protected_branch": False,
        }
        if resolved.is_dir():
            try:
                git_check = subprocess.run(
                    ["git", "-C", str(resolved), "rev-parse", "--is-inside-work-tree"],
                    capture_output=True, text=True, timeout=5,
                )
                if git_check.returncode == 0:
                    info["is_git"] = True
                    branch_result = subprocess.run(
                        ["git", "-C", str(resolved), "rev-parse", "--abbrev-ref", "HEAD"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if branch_result.returncode == 0:
                        branch = branch_result.stdout.strip()
                        info["branch"] = branch
                        info["on_protected_branch"] = branch in ("main", "master")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        return info

    @app.post("/api/repo-branches")
    def repo_branches(payload: ResolvePathRequest) -> dict[str, Any]:
        resolved = Path(payload.path.strip()).expanduser().resolve()
        if not resolved.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")
        try:
            git_check = subprocess.run(
                ["git", "-C", str(resolved), "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=5,
            )
            if git_check.returncode != 0:
                raise HTTPException(status_code=400, detail="Path is not a git repository")
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail="Unable to verify git repository") from exc
        branch_list = subprocess.run(
            ["git", "-C", str(resolved), "branch", "--list", "--format=%(refname:short)"],
            capture_output=True, text=True, timeout=5,
        )
        branches = [b for b in branch_list.stdout.strip().splitlines() if b]
        current_result = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        current = current_result.stdout.strip() if current_result.returncode == 0 else ""
        return {"branches": branches, "current": current}

    @app.post("/api/repo-create-branch")
    def repo_create_branch(payload: CreateBranchRequest) -> dict[str, Any]:
        resolved = Path(payload.repo_path.strip()).expanduser().resolve()
        if not resolved.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")
        try:
            git_check = subprocess.run(
                ["git", "-C", str(resolved), "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=5,
            )
            if git_check.returncode != 0:
                raise HTTPException(status_code=400, detail="Path is not a git repository")
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail="Unable to verify git repository") from exc
        existing = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "--verify", f"refs/heads/{payload.branch_name}"],
            capture_output=True, text=True, timeout=5,
        )
        if existing.returncode == 0:
            raise HTTPException(status_code=409, detail=f"Branch already exists: {payload.branch_name}")
        result = subprocess.run(
            ["git", "-C", str(resolved), "branch", payload.branch_name, payload.from_branch],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"Failed to create branch: {result.stderr.strip()}")
        return {"created": True, "branch": payload.branch_name}

    @app.post("/api/sessions", status_code=201)
    def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
        session_id = payload.id
        if not _SESSION_ID_RE.match(session_id):
            raise HTTPException(
                status_code=400,
                detail=(
                    "session_id must be 1–64 alphanumeric, dash, or underscore characters, "
                    "starting with alphanumeric."
                ),
            )
        name = payload.name or session_id
        pack = payload.pack or ensure_global_config(runtime_paths.config).default_pack
        config = payload.config
        try:
            config_json = None if config is None else json.dumps(
                parse_session_config_overrides(config).to_dict(),
                sort_keys=True,
            )
        except ValueError as exc:
            _logger.warning("Invalid session config for %s: %s (payload: %s)", session_id, exc, config)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            if hasattr(session_controller, "create_session"):
                created = session_controller.create_session(
                    session_id=session_id,
                    name=name,
                    pack=pack,
                    config_json=config_json,
                )
            else:
                created = store.create_session(
                    session_id=session_id,
                    name=name,
                    pack=pack,
                    created_at=_timestamp(),
                    config_json=config_json,
                    pre_delete=cleanup_session_worktree_if_needed,
                )
        except KeyError:
            raise HTTPException(status_code=409, detail=f"Session already exists: {session_id}")
        # Post-creation steps (intake seeding, worktree setup) can fail.
        # If they do, clean up the DB row and directories so the user isn't
        # stuck with a ghost session that blocks re-creation.
        try:
            # Seed intake/CLAUDE.md from the pack's intake prompt if available
            intake_prompt = runtime_paths.packs / pack / "prompts" / "intake.md"
            if intake_prompt.is_file():
                session_paths = runtime_paths.session_paths(created.id)
                session_paths.intake.mkdir(parents=True, exist_ok=True)
                (session_paths.intake / "CLAUDE.md").write_text(
                    intake_prompt.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            config_overrides = parse_session_config_overrides(config) if config else None
            env = config_overrides.environment if config_overrides else {}
            repo_root = env.get("COGNITIVE_SWITCHYARD_REPO_ROOT", "")
            branch = env.get("COGNITIVE_SWITCHYARD_BRANCH", "")
            if repo_root and branch:
                # Resolve to the main worktree so the session worktree is a peer
                # of the real repo, not nested inside a Claude/other worktree.
                main_worktree = subprocess.run(
                    ["git", "-C", repo_root, "worktree", "list", "--porcelain"],
                    capture_output=True, text=True,
                )
                if main_worktree.returncode == 0:
                    for line in main_worktree.stdout.splitlines():
                        if line.startswith("worktree "):
                            repo_parent = Path(line.removeprefix("worktree ")).parent
                            break
                    else:
                        repo_parent = Path(repo_root).parent
                else:
                    repo_parent = Path(repo_root).parent
                worktree_path = repo_parent / created.id
                _create_session_worktree(repo_root, branch, worktree_path)
                env["COGNITIVE_SWITCHYARD_SOURCE_REPO"] = repo_root
                env["COGNITIVE_SWITCHYARD_REPO_ROOT"] = str(worktree_path)
                updated_config = config_overrides.to_dict() if config_overrides else {}
                updated_config["environment"] = env
                updated_config_json = json.dumps(updated_config, sort_keys=True)
                store.update_session_config(created.id, updated_config_json)
                created = store.get_session(created.id)
        except Exception:
            # Roll back: remove DB row + directories so the session ID is free.
            _logger.exception("Post-creation setup failed for session %s; rolling back", session_id)
            try:
                store.delete_session(session_id)
            except Exception:
                _logger.exception("Rollback cleanup also failed for session %s", session_id)
            raise
        return {
            "session": _serialize_session(
                created,
                runtime_paths=runtime_paths,
            )
        }

    @app.get("/api/sessions")
    def list_sessions() -> dict[str, list[dict[str, Any]]]:
        return {
            "sessions": [
                _serialize_session(session, runtime_paths=runtime_paths)
                for session in store.list_sessions()
            ]
        }

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        session = store.get_session(session_id)
        all_events = store.list_events(session_id)
        recent_events = all_events[-25:] if all_events else ()
        return {
            "session": _serialize_session(
                session,
                runtime_paths=runtime_paths,
            ),
            "recent_events": [
                {"timestamp": e.timestamp, "type": e.event_type, "message": e.message}
                for e in recent_events
            ],
        }

    @app.post("/api/sessions/{session_id}/start", status_code=202)
    def start_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        session_controller.start(session_id)
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/reprocess", status_code=202)
    def reprocess_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        try:
            session_controller.reprocess(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/pause", status_code=202)
    def pause_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        session_controller.pause(session_id)
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/resume", status_code=202)
    def resume_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        session_controller.resume(session_id)
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/abort", status_code=202)
    def abort_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        session_controller.abort(session_id)
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/cleanup-worktree", status_code=200)
    def cleanup_worktree_route(session_id: str) -> dict[str, bool]:
        _ensure_session_exists(store, session_id)
        session = store.get_session(session_id)
        cleanup_session_worktree_if_needed(session)
        return {"ok": True}

    @app.post("/api/sessions/{session_id}/end", status_code=202)
    def end_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        session = store.get_session(session_id)
        if session.status != "idle":
            raise HTTPException(status_code=409, detail="Session must be idle to end.")
        session_controller.end_session(session_id)
        return {"status": "accepted"}

    @app.get("/api/sessions/{session_id}/tasks")
    def get_tasks(session_id: str) -> dict[str, list[dict[str, Any]]]:
        _ensure_session_exists(store, session_id)
        tasks = _serialize_session_tasks(store, session_id)
        return {"tasks": tasks}

    @app.get("/api/sessions/{session_id}/tasks/{task_id}")
    def get_task_detail(session_id: str, task_id: str) -> dict[str, Any]:
        _ensure_session_exists(store, session_id)
        summary_task = _summary_task_payload(store, session_id, task_id)
        if summary_task is not None:
            return {"task": summary_task}
        return {"task": _serialize_task(store, session_id, store.get_task(session_id, task_id))}

    @app.get("/api/sessions/{session_id}/tasks/{task_id}/log")
    def get_task_log(
        session_id: str,
        task_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(200, ge=1),
    ) -> dict[str, Any]:
        if _summary_task_payload(store, session_id, task_id) is not None:
            return {"path": None, "offset": offset, "content": "", "mtime_iso": None}
        task = store.get_task(session_id, task_id)
        log_path = _task_log_path(runtime_paths, task)
        if log_path is None or not log_path.is_file():
            return {"path": None, "offset": offset, "content": "", "mtime_iso": None}
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z")
        selected: list[str] = []
        with open(log_path, encoding="utf-8") as f:
            for i, raw_line in enumerate(f):
                if i < offset:
                    continue
                if i >= offset + limit:
                    break
                selected.append(raw_line.rstrip("\n"))
        return {
            "path": str(log_path),
            "offset": offset,
            "limit": limit,
            "content": "\n".join(selected) + ("\n" if selected else ""),
            "mtime_iso": mtime,
        }

    @app.get("/api/sessions/{session_id}/dag")
    def get_dag(session_id: str) -> dict[str, Any]:
        _ensure_session_exists(store, session_id)
        session_paths = runtime_paths.session_paths(session_id)
        if session_paths.resolution.is_file():
            return json.loads(session_paths.resolution.read_text(encoding="utf-8"))
        return {
            "resolved_at": None,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "depends_on": list(task.depends_on),
                    "anti_affinity": list(task.anti_affinity),
                    "exec_order": task.exec_order,
                }
                for task in _list_session_tasks(store, session_id)
            ],
            "groups": [],
            "conflicts": [],
            "notes": None,
        }

    @app.get("/api/sessions/{session_id}/dashboard")
    def get_dashboard(session_id: str) -> dict[str, Any]:
        _ensure_session_exists(store, session_id)
        worker_card_state = {}
        idle_state: dict[int, dict] = {}
        if hasattr(session_controller, "get_worker_card_state"):
            worker_card_state = session_controller.get_worker_card_state(session_id)
        if hasattr(session_controller, "get_idle_state"):
            idle_state = session_controller.get_idle_state(session_id)
        return build_dashboard_payload(
            store,
            session_id,
            runtime_paths=runtime_paths,
            worker_card_state=worker_card_state,
            idle_state=idle_state,
        )

    @app.post("/api/sessions/{session_id}/preflight")
    def run_preflight(session_id: str) -> dict[str, Any]:
        _ensure_session_exists(store, session_id)
        if hasattr(session_controller, "preflight"):
            result = session_controller.preflight(session_id)
        else:
            session = store.get_session(session_id)
            result = run_session_preflight(
                store=store,
                session_id=session_id,
                pack_manifest=load_pack_manifest(runtime_paths.packs / session.pack),
            )
        return _serialize_preflight_result(result)

    @app.post("/api/sessions/{session_id}/tasks/{task_id}/retry", status_code=202)
    def retry_task_route(session_id: str, task_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)  # F-10 fix: validate session before task
        store.get_task(session_id, task_id)
        session_controller.retry_task(session_id, task_id)
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/tasks/{task_id}/move")
    def move_task_route(session_id: str, task_id: str, body: MoveTaskRequest) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        store.get_task(session_id, task_id)
        try:
            return session_controller.move_task(session_id, task_id, body.target_status)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/sessions/{session_id}/rescan", status_code=200)
    def rescan_session(session_id: str) -> dict[str, Any]:
        _ensure_session_exists(store, session_id)
        result = store.reconcile_filesystem_projection(session_id)
        session = store.get_session(session_id)
        if session.status == "created" and session.started_at is not None:
            store.update_session_status(session_id, status="created")
        timestamp = datetime.now(UTC).isoformat()
        reconciled_count = len(result["reconciled"])
        orphaned_count = len(result["orphaned"])
        detail_parts = []
        if reconciled_count:
            detail_parts.append(f"{reconciled_count} reconciled")
        if orphaned_count:
            detail_parts.append(f"{orphaned_count} orphaned")
        detail = ", ".join(detail_parts) if detail_parts else "no changes"
        store.append_event(
            session_id,
            timestamp=timestamp,
            event_type="session.rescan",
            message=f"Filesystem rescan: {detail}.",
        )
        session_controller._publish_snapshot(session_id)
        return result

    @app.get("/api/sessions/{session_id}/intake")
    def get_intake(session_id: str) -> dict[str, Any]:
        session = store.get_session(session_id)
        session_paths = runtime_paths.session_paths(session_id)
        locked = session.status != "created"
        started_at = (
            None
            if session.started_at is None
            else datetime.fromisoformat(session.started_at.replace("Z", "+00:00"))
        )
        files = []
        if not session_paths.intake.is_dir():
            return {"files": files, "locked": locked}
        for path in sorted(session_paths.intake.iterdir()):
            if not path.is_file():
                continue
            if path.suffix != ".md" or path.name in _INTAKE_META_FILES:
                continue
            stat = path.stat()
            detected_at = datetime.fromtimestamp(
                stat.st_mtime,
                tz=UTC,
            )
            files.append(
                {
                    "filename": path.name,
                    "path": str(path.relative_to(session_paths.root)),
                    "size": stat.st_size,
                    "detected_at": detected_at.isoformat().replace("+00:00", "Z"),
                    "locked": locked,
                    "in_snapshot": started_at is None or detected_at <= started_at,
                }
            )
        return {"locked": locked, "files": files}

    @app.post("/api/sessions/{session_id}/open-intake", status_code=204)
    def open_intake(session_id: str) -> Response:
        _ensure_session_exists(store, session_id)
        command = _open_command(runtime_paths.session_paths(session_id).intake)
        app.state.command_runner(command)
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/open-intake-terminal", status_code=204)
    def open_intake_terminal(session_id: str) -> Response:
        _ensure_session_exists(store, session_id)
        config = ensure_global_config(runtime_paths.config)
        command = _open_terminal_command(
            runtime_paths.session_paths(session_id).intake,
            config.terminal_app,
        )
        app.state.command_runner(command)
        return Response(status_code=204)

    @app.post("/api/sessions/{session_id}/reveal-file", status_code=204)
    def reveal_file(session_id: str, path: str) -> Response:
        _ensure_session_exists(store, session_id)
        session_root = runtime_paths.session(session_id)
        target = _resolve_relative_path(session_root, path)
        command = _reveal_command(target)
        app.state.command_runner(command)
        return Response(status_code=204)

    @app.delete("/api/sessions/{session_id}")
    def purge_session(session_id: str) -> dict[str, int]:
        session = store.get_session(session_id)
        if session.status not in {"created", "idle", "completed", "aborted"}:
            raise HTTPException(status_code=409, detail="Session is still active.")
        if hasattr(session_controller, "has_active_thread") and session_controller.has_active_thread(session_id):
            raise HTTPException(status_code=409, detail="Session thread is still running.")
        cleanup_session_worktree_if_needed(session)
        store.delete_session(session_id)
        if hasattr(session_controller, "_evict_session_cache"):
            session_controller._evict_session_cache(session_id)
        return {"deleted": 1}

    @app.post("/api/sessions/{session_id}/force-reset", status_code=200)
    def force_reset_session(session_id: str) -> dict[str, str]:
        """Nuclear reset: abort if running, tear down worktree + branches, delete
        all DB rows and directories.  Works regardless of session status."""
        try:
            session = store.get_session(session_id)
        except KeyError:
            # Session not in DB — try to clean up orphaned dirs on disk.
            session_root = runtime_paths.session(session_id)
            if session_root.exists():
                shutil.rmtree(session_root, ignore_errors=True)
            return {"status": "reset", "detail": "Cleaned orphaned directory."}
        # Abort if active — signal the background thread to stop.
        if session.status not in {"created", "completed", "aborted"}:
            try:
                session_controller.abort(session_id)
            except Exception:
                pass
            # Give the background thread a moment to notice the abort.
            import time
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if not session_controller.has_active_thread(session_id):
                    break
                time.sleep(0.25)
        # Clean up worktree and per-task branches.
        try:
            cleanup_session_worktree_if_needed(session)
        except Exception:
            _logger.exception("force-reset: worktree cleanup failed for %s", session_id)
        # Delete all DB rows + session directory.
        try:
            store.delete_session(session_id)
        except Exception:
            _logger.exception("force-reset: DB cleanup failed for %s", session_id)
            # Last resort: nuke the directory even if DB delete failed.
            session_root = runtime_paths.session(session_id)
            if session_root.exists():
                shutil.rmtree(session_root, ignore_errors=True)
        return {"status": "reset"}

    @app.delete("/api/sessions")
    def purge_completed_sessions() -> dict[str, int]:
        deleted = 0
        for session in store.list_sessions():
            if session.status in {"idle", "completed", "aborted"}:
                cleanup_session_worktree_if_needed(session)
                store.delete_session(session.id)
                deleted += 1
        return {"deleted": deleted}

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        config = ensure_global_config(runtime_paths.config)
        return {"settings": _serialize_settings(config, runtime_paths=runtime_paths)}

    @app.put("/api/settings")
    def update_settings(payload: UpdateSettingsRequest) -> dict[str, Any]:
        config = GlobalConfig(
            retention_days=payload.retention_days,
            default_planners=payload.default_planners,
            default_workers=payload.default_workers,
            default_pack=payload.default_pack,
            terminal_app=payload.terminal_app,
        )
        write_global_config(runtime_paths.config, config)
        return {"settings": _serialize_settings(config, runtime_paths=runtime_paths)}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await connection_manager.connect(websocket)
        try:
            while True:
                try:
                    payload = await websocket.receive_json()
                except (json.JSONDecodeError, ValueError):
                    continue
                message_type = payload.get("type")
                worker_slot = payload.get("worker_slot")
                if message_type == "subscribe_logs" and isinstance(worker_slot, int):
                    await connection_manager.subscribe_logs(websocket, worker_slot)
                elif message_type == "unsubscribe_logs" and isinstance(worker_slot, int):
                    await connection_manager.unsubscribe_logs(websocket, worker_slot)
        except WebSocketDisconnect:
            await connection_manager.disconnect(websocket)
        except Exception:
            await connection_manager.disconnect(websocket)

    return app


def testing_mode_enabled() -> bool:
    value = os.environ.get("UTILITIES_TESTING", "")
    return value.lower() not in {"", "0", "false", "no"}


def serve_backend(
    *,
    runtime_paths: RuntimePaths,
    builtin_packs_root: Path,
    host: str,
    port: int,
) -> int:
    del builtin_packs_root
    resolved_port = find_free_port(port)
    store = initialize_state_store(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    import uvicorn

    url = f"http://{host}:{resolved_port}"
    if not os.environ.get("COGNITIVE_SWITCHYARD_NO_BROWSER") and not testing_mode_enabled():
        import webbrowser

        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(app, host=host, port=resolved_port, ws="wsproto")
    return resolved_port


def find_free_port(start_port: int, max_attempts: int = 20) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No free port found in range {start_port}-{start_port + max_attempts - 1}"
    )


def build_dashboard_payload(
    store: StateStore,
    session_id: str,
    *,
    runtime_paths: RuntimePaths | None = None,
    worker_card_state: dict[int, WorkerCardRuntimeState] | None = None,
    planning_agents: dict[str, Any] | None = None,
    pack_manifest: PackManifest | None = None,
    idle_state: dict[int, dict] | None = None,
) -> dict[str, Any]:
    session = store.get_session(session_id)
    summary = store.read_session_summary(session_id) if session.status == "completed" else None
    if summary is not None:
        return _build_summary_dashboard_payload(session, summary, store=store)
    session_paths = store.runtime_paths.session_paths(session_id)
    resolved_runtime_paths = runtime_paths or store.runtime_paths
    if pack_manifest is None:
        pack_manifest = load_pack_manifest(resolved_runtime_paths.packs / session.pack)
    effective_runtime_config = build_effective_session_runtime_config(
        session=session,
        pack_manifest=pack_manifest,
        default_poll_interval=0.05,
    )
    # Fetch all tasks in a single DB query and partition in Python.
    all_tasks = store.list_all_tasks(session_id)
    by_status: dict[str, list] = {}
    for task in all_tasks:
        by_status.setdefault(task.status, []).append(task)
    ready_tasks = by_status.get("ready", [])
    active_tasks = by_status.get("active", [])
    done_tasks = by_status.get("done", [])
    blocked_tasks = by_status.get("blocked", [])
    pipeline = {
        "intake": _count_md_files(session_paths.intake),
        "planning": _count_md_files(session_paths.claimed),
        "staged": _count_plans(session_paths.staging),
        "review": _count_plans(session_paths.review),
        "ready": len(ready_tasks),
        "active": len(active_tasks),
        "verifying": 1 if session.status in {"verifying", "auto_fixing"} else 0,
        "done": len(done_tasks),
        "blocked": len(blocked_tasks),
    }
    pipeline_dirs = {
        "intake": str(session_paths.intake),
        "planning": str(session_paths.claimed),
        "staged": str(session_paths.staging),
        "review": str(session_paths.review),
        "ready": str(session_paths.ready),
        "active": str(session_paths.workers),
        "done": str(session_paths.done),
        "blocked": str(session_paths.blocked),
    }
    active_tasks_by_slot = {
        task.worker_slot: task
        for task in active_tasks
        if task.worker_slot is not None
    }
    slot_rows = {slot.slot_number: slot for slot in store.list_worker_slots(session_id)}
    runtime_state_by_slot = worker_card_state or {}
    now_epoch = time.time()
    now_mono = time.monotonic()
    workers = []
    for slot_number in range(effective_runtime_config.worker_count):
        active_task = active_tasks_by_slot.get(slot_number)
        slot = slot_rows.get(slot_number)
        worker_payload: dict[str, Any] = {
            "slot": slot_number,
            "status": "active" if active_task is not None else (slot.status if slot is not None else "idle"),
        }
        if active_task is not None:
            task = active_task
            worker_payload["task_id"] = task.task_id
            worker_payload["task_title"] = task.title
            worker_payload["elapsed"] = int(_elapsed_seconds(task.started_at))
            worker_payload["started_at"] = task.started_at
            runtime_worker = runtime_state_by_slot.get(slot_number)
            if runtime_worker is not None and runtime_worker.task_id == task.task_id:
                if runtime_worker.phase_name is not None:
                    worker_payload["phase"] = runtime_worker.phase_name
                if runtime_worker.phase_index is not None:
                    worker_payload["phase_num"] = runtime_worker.phase_index
                if runtime_worker.phase_total is not None:
                    worker_payload["phase_total"] = runtime_worker.phase_total
                if runtime_worker.detail_message is not None:
                    worker_payload["detail"] = runtime_worker.detail_message
            if idle_state and slot_number in idle_state:
                ws = idle_state[slot_number]
                if ws.get("task_id") == task.task_id:
                    worker_payload["last_activity_ago"] = max(0, int(now_mono - ws["last_output_at"]))
                    worker_payload["task_idle_limit"] = int(ws["task_idle"])
        workers.append(worker_payload)
    all_events = store.list_events(session_id)
    recent_events = all_events[-25:] if all_events else ()
    rs = session.runtime_state
    # Active-only elapsed: accumulated time from completed runs + current run time (if running)
    is_active = session.status in {"planning", "resolving", "running", "verifying", "auto_fixing"}
    # Fall back to started_at if run_started_at not yet set (e.g. pre-multi-run sessions)
    run_start_ref = rs.run_started_at or session.started_at
    current_run_elapsed = int(_elapsed_seconds(run_start_ref)) if is_active else 0
    session_elapsed = rs.accumulated_elapsed_seconds + current_run_elapsed
    run_elapsed = current_run_elapsed if is_active else rs.last_run_elapsed_seconds
    return {
        "session": {
            "id": session.id,
            "status": session.status,
            "pack": session.pack,
            "started_at": session.started_at,
            "elapsed": session_elapsed,
            "run_elapsed": run_elapsed,
            "run_number": rs.run_number,
            "config": parse_session_config_overrides(session.config_json).to_dict(),
            "effective_runtime_config": effective_runtime_config.to_dict(),
        },
        "pipeline": pipeline,
        "pipeline_dirs": pipeline_dirs,
        "workers": workers,
        "recent_events": [
            {"timestamp": e.timestamp, "type": e.event_type, "message": e.message}
            for e in recent_events
        ],
        "runtime_state": {
            "completed_since_verification": session.runtime_state.completed_since_verification,
            "verification_pending": session.runtime_state.verification_pending,
            "verification_reason": session.runtime_state.verification_reason,
            "verification_started_at": session.runtime_state.verification_started_at,
            "verification_elapsed": (
                int(_elapsed_seconds(session.runtime_state.verification_started_at))
                if session.runtime_state.verification_started_at
                else None
            ),
            "auto_fix_context": session.runtime_state.auto_fix_context,
            "auto_fix_task_id": session.runtime_state.auto_fix_task_id,
            "auto_fix_attempt": session.runtime_state.auto_fix_attempt,
            "last_fix_summary": session.runtime_state.last_fix_summary,
            "last_verification_test_summary": session.runtime_state.last_verification_test_summary,
            "dispatch_frozen": session.runtime_state.dispatch_frozen,
            "dispatch_frozen_reason": session.runtime_state.dispatch_frozen_reason,
        },
        "effective_runtime_config": effective_runtime_config.to_dict(),
        **(
            {
                "planning_agents": [
                    {
                        "planner_task_id": ptid,
                        "file": info["file"],
                        "started_at": info["started_at"],
                        "elapsed": int(_elapsed_seconds(info["started_at"])),
                    }
                    for ptid, info in sorted((planning_agents or {}).items())
                ]
            }
            if session.status in ("planning", "resolving")
            else {}
        ),
    }


def _serialize_pack_summary(manifest: PackManifest) -> dict[str, Any]:
    return {
        "name": manifest.name,
        "description": manifest.description,
        "version": manifest.version,
        "max_workers": manifest.phases.execution.max_workers,
        "max_planners": manifest.phases.planning.max_instances,
        "planning_enabled": manifest.phases.planning.enabled,
        "verification_enabled": manifest.verification.enabled,
    }


def _serialize_pack_detail(manifest: PackManifest) -> dict[str, Any]:
    return {
        "name": manifest.name,
        "description": manifest.description,
        "version": manifest.version,
        "root": str(manifest.root),
        "phases": {
            "planning": {
                "enabled": manifest.phases.planning.enabled,
                "executor": manifest.phases.planning.executor,
                "runtime": manifest.phases.planning.runtime,
                "model": manifest.phases.planning.model,
                "reasoning_effort": manifest.phases.planning.reasoning_effort,
                "prompt": (
                    str(manifest.phases.planning.prompt)
                    if manifest.phases.planning.prompt is not None
                    else None
                ),
                "max_instances": manifest.phases.planning.max_instances,
            },
            "resolution": {
                "enabled": manifest.phases.resolution.enabled,
                "executor": manifest.phases.resolution.executor,
                "runtime": manifest.phases.resolution.runtime,
                "model": manifest.phases.resolution.model,
                "reasoning_effort": manifest.phases.resolution.reasoning_effort,
                "prompt": (
                    str(manifest.phases.resolution.prompt)
                    if manifest.phases.resolution.prompt is not None
                    else None
                ),
                "script": (
                    str(manifest.phases.resolution.script)
                    if manifest.phases.resolution.script is not None
                    else None
                ),
            },
            "execution": {
                "enabled": manifest.phases.execution.enabled,
                "executor": manifest.phases.execution.executor,
                "reasoning_effort": manifest.phases.execution.reasoning_effort,
                "command": (
                    str(manifest.phases.execution.command)
                    if manifest.phases.execution.command is not None
                    else None
                ),
                "max_workers": manifest.phases.execution.max_workers,
            },
        },
        "auto_fix": {
            "enabled": manifest.auto_fix.enabled,
            "max_attempts": manifest.auto_fix.max_attempts,
            "runtime": manifest.auto_fix.runtime,
            "model": manifest.auto_fix.model,
            "reasoning_effort": manifest.auto_fix.reasoning_effort,
            "prompt": (
                str(manifest.auto_fix.prompt)
                if manifest.auto_fix.prompt is not None
                else None
            ),
        },
        "timeouts": {
            "task_idle": manifest.timeouts.task_idle,
            "task_max": manifest.timeouts.task_max,
            "session_max": manifest.timeouts.session_max,
        },
    }


def _serialize_preflight_result(result: PackPreflightResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "permission_report": _serialize_permission_report(result.permission_report),
        "prerequisite_results": _serialize_prerequisite_report(result.prerequisite_results),
        "preflight_result": (
            None if result.preflight_result is None else _serialize_hook_result(result.preflight_result)
        ),
    }


def _serialize_permission_report(report: ScriptPermissionReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "issues": [
            {
                "relative_path": issue.relative_path,
                "fix_command": issue.fix_command,
            }
            for issue in report.issues
        ],
    }


def _serialize_prerequisite_report(report: PrerequisiteReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "results": [
            {
                "name": result.name,
                "check": result.check,
                "ok": result.ok,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in report.results
        ],
    }


def _serialize_hook_result(result: HookInvocationResult) -> dict[str, Any]:
    return {
        "hook_name": result.hook_name,
        "script_path": str(result.script_path),
        "args": list(result.args),
        "cwd": str(result.cwd),
        "ok": result.ok,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _serialize_session(
    session: SessionRecord,
    *,
    runtime_paths: RuntimePaths,
) -> dict[str, Any]:
    config = parse_session_config_overrides(session.config_json).to_dict()
    summary = None
    if session.status == "completed":
        summary = _read_summary(runtime_paths, session.id)
    effective_runtime_config: dict[str, Any] | None = None
    if summary is not None:
        payload = summary.get("session", {}).get("effective_runtime_config", {})
        if payload:
            effective_runtime_config = dict(payload)
    if effective_runtime_config is None:
        try:
            pack_manifest = load_pack_manifest(runtime_paths.packs / session.pack)
            effective_runtime_config = build_effective_session_runtime_config(
                session=session,
                pack_manifest=pack_manifest,
                default_poll_interval=0.05,
            ).to_dict()
        except Exception:
            effective_runtime_config = {}
    payload = {
        "id": session.id,
        "name": session.name,
        "pack": session.pack,
        "status": session.status,
        "created_at": session.created_at,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "config": config,
        "effective_runtime_config": effective_runtime_config,
        "runtime_state": {
            "completed_since_verification": session.runtime_state.completed_since_verification,
            "verification_pending": session.runtime_state.verification_pending,
            "verification_reason": session.runtime_state.verification_reason,
            "verification_started_at": session.runtime_state.verification_started_at,
            "verification_elapsed": (
                int(_elapsed_seconds(session.runtime_state.verification_started_at))
                if session.runtime_state.verification_started_at
                else None
            ),
            "auto_fix_context": session.runtime_state.auto_fix_context,
            "auto_fix_task_id": session.runtime_state.auto_fix_task_id,
            "auto_fix_attempt": session.runtime_state.auto_fix_attempt,
            "last_fix_summary": session.runtime_state.last_fix_summary,
            "last_verification_test_summary": session.runtime_state.last_verification_test_summary,
            "dispatch_frozen": session.runtime_state.dispatch_frozen,
            "dispatch_frozen_reason": session.runtime_state.dispatch_frozen_reason,
        },
        "summary": summary,
    }
    release_notes = _read_release_notes(runtime_paths, session.id, summary=summary)
    if release_notes is not None:
        payload["release_notes"] = release_notes
    return payload


def _serialize_task(store: StateStore, session_id: str, task: PersistedTask) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": task.task_id,
        "title": task.title,
        "status": task.status,
        "depends_on": list(task.depends_on),
        "anti_affinity": list(task.anti_affinity),
        "exec_order": task.exec_order,
        "full_test_after": task.full_test_after,
        "worker_slot": task.worker_slot,
        "plan_path": str(task.plan_path),
        "log_path": (
            str(log_path)
            if (log_path := _task_log_path(store.runtime_paths, task)) is not None
            else None
        ),
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "elapsed": (
            _elapsed_seconds(task.started_at) if task.status == "active"
            else (
                int(
                    (
                        datetime.fromisoformat(task.completed_at.replace("Z", "+00:00"))
                        - datetime.fromisoformat(task.started_at.replace("Z", "+00:00"))
                    ).total_seconds()
                )
                if task.started_at and task.completed_at
                else 0
            )
        ),
        "history_source": "live",
    }
    task_events = store.get_task_events(session_id, task.task_id)
    payload["events"] = [
        {"timestamp": e.timestamp, "type": e.event_type, "message": e.message}
        for e in task_events
    ]
    return payload


def _serialize_settings(config: GlobalConfig, runtime_paths: RuntimePaths | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "retention_days": config.retention_days,
        "default_planners": config.default_planners,
        "default_workers": config.default_workers,
        "default_pack": config.default_pack,
        "terminal_app": config.terminal_app,
    }
    if runtime_paths is not None:
        payload["runtime_root"] = str(runtime_paths.home)
    return payload


def _build_root_bootstrap_payload(
    store: StateStore,
    *,
    runtime_paths: RuntimePaths,
) -> dict[str, Any]:
    sessions = [
        _serialize_session(session, runtime_paths=runtime_paths)
        for session in store.list_sessions()
    ]
    settings = _serialize_settings(ensure_global_config(runtime_paths.config), runtime_paths=runtime_paths)
    packs = [
        _serialize_pack_summary(load_pack_manifest(runtime_paths.packs / pack_name))
        for pack_name in list_runtime_pack_names(runtime_paths.packs)
    ]
    current_session = _select_bootstrap_session(sessions)
    dashboard = None
    intake = None
    if current_session is not None:
        dashboard = build_dashboard_payload(store, current_session["id"], runtime_paths=runtime_paths)
        intake = _serialize_intake_listing(store.get_session(current_session["id"]), runtime_paths)
    return {
        "views": [
            "setup",
            "monitor",
            "task-detail",
            "dag",
            "history",
            "settings",
        ],
        "packs": packs,
        "settings": settings,
        "sessions": sessions,
        "current_session": current_session,
        "dashboard": dashboard,
        "intake": intake,
    }


def _list_session_tasks(store: StateStore, session_id: str) -> tuple[PersistedTask, ...]:
    return (
        *store.list_active_tasks(session_id),
        *store.list_ready_tasks(session_id),
        *store.list_done_tasks(session_id),
        *store.list_blocked_tasks(session_id),
    )


def _serialize_session_tasks(store: StateStore, session_id: str) -> list[dict[str, Any]]:
    summary = _read_summary(store.runtime_paths, session_id)
    if summary is not None:
        return [
            _serialize_summary_task(task_payload)
            for task_payload in summary.get("tasks", [])
        ]
    return [_serialize_task(store, session_id, task) for task in _list_session_tasks(store, session_id)]


def _summary_task_payload(
    store: StateStore,
    session_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    summary = _read_summary(store.runtime_paths, session_id)
    if summary is None:
        return None
    for task_payload in summary.get("tasks", []):
        if task_payload.get("task_id") == task_id:
            return _serialize_summary_task(task_payload)
    raise HTTPException(status_code=404, detail=f"Unknown task: {session_id}/{task_id}")


def _serialize_summary_task(task_payload: dict[str, Any]) -> dict[str, Any]:
    started = task_payload.get("started_at")
    completed = task_payload.get("completed_at")
    if started and completed:
        try:
            elapsed = int(
                (
                    datetime.fromisoformat(completed.replace("Z", "+00:00"))
                    - datetime.fromisoformat(started.replace("Z", "+00:00"))
                ).total_seconds()
            )
        except (ValueError, TypeError):
            elapsed = 0
    else:
        elapsed = 0
    return {
        "task_id": task_payload["task_id"],
        "title": task_payload["title"],
        "status": task_payload["status"],
        "depends_on": list(task_payload.get("depends_on", [])),
        "anti_affinity": list(task_payload.get("anti_affinity", [])),
        "exec_order": int(task_payload.get("exec_order", 1)),
        "full_test_after": bool(task_payload.get("full_test_after", False)),
        "worker_slot": None,
        "plan_path": None,
        "log_path": None,
        "created_at": task_payload.get("created_at"),
        "started_at": started,
        "completed_at": completed,
        "elapsed": elapsed,
        "events": list(task_payload.get("events", [])),
        "history_source": "summary",
    }


def _select_bootstrap_session(sessions: list[dict[str, Any]]) -> dict[str, Any] | None:
    for preferred_status in ("running", "paused", "created", "idle"):
        for session in sessions:
            if session["status"] == preferred_status:
                return session
    return None


def _serialize_intake_listing(session: SessionRecord, runtime_paths: RuntimePaths) -> dict[str, Any]:
    session_paths = runtime_paths.session_paths(session.id)
    locked = session.status != "created"
    started_at = (
        None
        if session.started_at is None
        else datetime.fromisoformat(session.started_at.replace("Z", "+00:00"))
    )
    files = []
    for path in sorted(session_paths.intake.iterdir()):
        if not path.is_file():
            continue
        if path.suffix != ".md" or path.name in _INTAKE_META_FILES:
            continue
        stat = path.stat()
        detected_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        files.append(
            {
                "filename": path.name,
                "path": str(path.relative_to(session_paths.root)),
                "size": stat.st_size,
                "detected_at": detected_at.isoformat().replace("+00:00", "Z"),
                "locked": locked,
                "in_snapshot": started_at is None or detected_at <= started_at,
            }
        )
    return {"locked": locked, "files": files}


def _task_log_path(runtime_paths: RuntimePaths, task: PersistedTask) -> Path | None:
    return runtime_paths.session_paths(task.session_id).task_log(task.task_id)


def _read_summary(runtime_paths: RuntimePaths, session_id: str) -> dict[str, Any] | None:
    summary_path = runtime_paths.session_paths(session_id).summary
    if not summary_path.is_file():
        return None
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _read_release_notes(
    runtime_paths: RuntimePaths,
    session_id: str,
    *,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    artifacts = {} if summary is None else dict(summary.get("artifacts", {}))
    release_notes_relpath = artifacts.get("release_notes_path", "RELEASE_NOTES.md")
    if not isinstance(release_notes_relpath, str):
        return None
    release_notes_path = runtime_paths.session_paths(session_id).root / release_notes_relpath
    if not release_notes_path.is_file():
        return None
    return {
        "path": release_notes_relpath,
        "content": release_notes_path.read_text(encoding="utf-8"),
    }


def _build_summary_dashboard_payload(
    session: SessionRecord,
    summary: dict[str, Any],
    store: StateStore | None = None,
) -> dict[str, Any]:
    session_payload = dict(summary.get("session", {}))
    return {
        "session": {
            "id": session.id,
            "status": session.status,
            "pack": session.pack,
            "started_at": session.started_at,
            "elapsed": int(session_payload.get("duration_seconds", 0)),
            "config": dict(session_payload.get("config", {})),
            "effective_runtime_config": dict(
                session_payload.get("effective_runtime_config", {})
            ),
        },
        "pipeline": {
            "intake": 0,
            "planning": 0,
            "staged": 0,
            "review": 0,
            "ready": int(summary.get("pipeline", {}).get("ready", 0)),
            "active": int(summary.get("pipeline", {}).get("active", 0)),
            "verifying": 0,
            "done": int(summary.get("pipeline", {}).get("done", 0)),
            "blocked": int(summary.get("pipeline", {}).get("blocked", 0)),
        },
        "workers": [],
        "tasks": [
            _serialize_summary_task(t) for t in summary.get("tasks", [])
        ],
        "runtime_state": {
            "completed_since_verification": 0,
            "verification_pending": False,
            "verification_reason": None,
            "verification_started_at": None,
            "verification_elapsed": None,
            "auto_fix_context": None,
            "auto_fix_task_id": None,
            "auto_fix_attempt": 0,
            "last_fix_summary": None,
        },
        "effective_runtime_config": dict(
            session_payload.get("effective_runtime_config", {})
        ),
        "recent_events": (
            [
                {"timestamp": e.timestamp, "type": e.event_type, "message": e.message}
                for e in (store.list_events(session.id) if store else [])
            ]
        ),
    }


def _load_runtime_pack(runtime_paths: RuntimePaths, name: str) -> PackManifest:
    pack_path = runtime_paths.packs / name
    if not pack_path.is_dir():
        raise HTTPException(status_code=404, detail="Unknown pack.")
    return load_pack_manifest(pack_path)


def _ensure_session_exists(store: StateStore, session_id: str) -> None:
    try:
        store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown session.") from exc


def _resolve_relative_path(session_root: Path, relative_path: str) -> Path:
    candidate = (session_root / relative_path).resolve()
    try:
        candidate.relative_to(session_root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path escapes session root.") from exc
    return candidate


def _run_folder_picker() -> dict[str, Any]:
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select repository root")'],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return {"path": result.stdout.strip().rstrip("/")}
            return {"cancelled": True}
        except subprocess.TimeoutExpired:
            return {"cancelled": True}
    return {"error": "Directory browsing is only supported on macOS"}


def _open_command(target: Path) -> list[str]:
    if sys.platform == "darwin":
        return ["open", str(target)]
    return ["xdg-open", str(target)]


_LINUX_DIR_FLAGS: dict[str, list[str]] = {
    "kitty": ["--directory"],
    "alacritty": ["--working-directory"],
    "wezterm": ["start", "--always-new-process", "--cwd"],
    "xterm": [],  # special handling below
    "x-terminal-emulator": ["--working-directory"],
}


def _open_terminal_command(target: Path, terminal_app: str) -> list[str]:
    """Return a command that opens a terminal at the given directory."""
    if sys.platform == "darwin":
        app_lower = terminal_app.lower()
        if app_lower in ("iterm", "terminal"):
            # open -n -a <App> <path>: idiomatic macOS launch, new instance
            app_name = "iTerm" if app_lower == "iterm" else "Terminal"
            return ["open", "-n", "-a", app_name, str(target)]
        # Other macOS apps (kitty, alacritty, wezterm): use Linux-style CLI flags
        # Fall through to the Linux branch below

    app_lower = terminal_app.lower()
    if app_lower in _LINUX_DIR_FLAGS:
        dir_flags = _LINUX_DIR_FLAGS[app_lower]
        if app_lower == "xterm":
            return ["xterm", "-e", f"cd {shlex.quote(str(target))} && exec $SHELL"]
        if app_lower == "wezterm":
            return ["wezterm", "start", "--always-new-process", "--cwd", str(target)]
        return [terminal_app] + dir_flags + [str(target)]
    return [terminal_app, "--working-directory", str(target)]


def _reveal_command(target: Path) -> list[str]:
    if sys.platform == "darwin":
        return ["open", "-R", str(target)]
    return ["xdg-open", str(target.parent)]


def _default_command_runner(command: list[str]) -> None:
    # start_new_session=True detaches the child process so the OS reaps it without
    # Python GC involvement, preventing zombie accumulation. F-11 fix.
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _count_plans(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return len(tuple(directory.glob("*.plan.md")))


def _count_md_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return len([p for p in directory.glob("*.md") if p.name not in _INTAKE_META_FILES])


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _elapsed_seconds(timestamp: str | None) -> int:
    if not timestamp:
        return 0
    started_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return max(0, int((datetime.now(UTC) - started_at).total_seconds()))


_logger = __import__("logging").getLogger(__name__)

# Session IDs are used directly in filesystem paths; restrict to safe characters
# to prevent path traversal attacks (e.g. "../evil").
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")

# Toggle with COGNITIVE_SWITCHYARD_DEBUG=1 or logging level DEBUG
_debug_enabled: bool = os.environ.get("COGNITIVE_SWITCHYARD_DEBUG", "") == "1"


def _debug(msg: str, *args: object) -> None:
    """Emit debug trace when COGNITIVE_SWITCHYARD_DEBUG=1 or logger is at DEBUG."""
    if _debug_enabled or _logger.isEnabledFor(__import__("logging").DEBUG):
        _logger.debug(msg, *args)


def _log_async_exception(completed) -> None:
    exc = completed.exception()
    if exc is not None:
        _logger.debug("Async broadcast error: %s", exc)


def _run_async(awaitable, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
    _debug(
        "_run_async called: thread=%s loop=%s loop_running=%s loop_closed=%s",
        threading.current_thread().name,
        loop,
        loop.is_running() if loop is not None else "N/A",
        loop.is_closed() if loop is not None else "N/A",
    )
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    # Determine the target loop: prefer the explicit ``loop`` (the event loop
    # that owns the WebSocket connections) over whatever the current thread
    # reports as "running".  A stale thread-local running loop (e.g. left over
    # from a prior uvicorn server in tests) would silently swallow tasks
    # scheduled via ``create_task`` because it is not actually processing in
    # this thread.
    target = loop if (loop is not None and loop.is_running() and not loop.is_closed()) else None

    if target is not None:
        if running_loop is target:
            # Already executing inside the target loop — schedule directly.
            _debug("_run_async: scheduling on current running loop via create_task")
            running_loop.create_task(awaitable)
            return
        # Different thread or stale running_loop — use thread-safe dispatch.
        try:
            future = asyncio.run_coroutine_threadsafe(awaitable, target)
        except RuntimeError:
            _debug("_run_async: run_coroutine_threadsafe failed, closing awaitable")
            awaitable.close()
            return
        _debug("_run_async: scheduled via run_coroutine_threadsafe on target loop")
        future.add_done_callback(_log_async_exception)
        return

    # No explicit target loop available.
    if running_loop is not None and not running_loop.is_closed():
        _debug("_run_async: scheduling on running loop via create_task (no target)")
        running_loop.create_task(awaitable)
        return

    # No loop at all — create a temporary one (e.g. during startup / tests
    # before any WebSocket connects).
    _debug("_run_async: no usable loop, using asyncio.run()")
    asyncio.run(awaitable)
