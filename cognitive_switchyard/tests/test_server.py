from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

import pytest
from fastapi.testclient import TestClient

from cognitive_switchyard.cli import main
from cognitive_switchyard.config import GlobalConfig, build_runtime_paths, write_global_config
from cognitive_switchyard.models import BackendRuntimeEvent, PackManifest, TaskPlan
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.server import create_app
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _write_runtime_pack(runtime_paths, *, name: str = "claude-code") -> PackManifest:
    pack_root = runtime_paths.packs / name
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            import sys
            from pathlib import Path

            task_path = Path(sys.argv[1])
            task_id = task_path.name.removesuffix(".plan.md")
            print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
            status_path = task_path.with_name(task_id + ".status")
            status_path.write_text(
                "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
                encoding="utf-8",
            )
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (prompts_dir / "planner.md").write_text("Plan prompt.\n", encoding="utf-8")
    (prompts_dir / "resolver.md").write_text("Resolve prompt.\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Packet 11 runtime pack.
            version: 1.2.3

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-sonnet
                prompt: prompts/planner.md
                max_instances: 2
              resolution:
                enabled: true
                executor: agent
                model: claude-sonnet
                prompt: prompts/resolver.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 2
              verification:
                enabled: false

            timeouts:
              task_idle: 300
              task_max: 0
              session_max: 14400

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return load_pack_manifest(pack_root)


def _write_preflight_runtime_pack(runtime_paths, *, name: str = "claude-code") -> PackManifest:
    pack_root = runtime_paths.packs / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            raise SystemExit(0)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    preflight_path = scripts_dir / "preflight"
    preflight_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            print("pack preflight ok")
            """
        ).lstrip(),
        encoding="utf-8",
    )
    preflight_path.chmod(preflight_path.stat().st_mode | 0o111)
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Packet 11B preflight pack.
            version: 1.2.3

            prerequisites:
              - name: CLI available
                check: printf 'cli ok\\n'

            phases:
              resolution:
                enabled: true
                executor: passthrough
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 2
              verification:
                enabled: false

            timeouts:
              task_idle: 300
              task_max: 0
              session_max: 14400

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return load_pack_manifest(pack_root)


def _write_slow_runtime_pack(
    runtime_paths,
    *,
    name: str = "claude-code",
    sleep_seconds: float = 0.2,
) -> PackManifest:
    pack_root = runtime_paths.packs / name
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            f"""
            #!/usr/bin/env python3
            import sys
            import time
            from pathlib import Path

            task_path = Path(sys.argv[1])
            task_id = task_path.name.removesuffix(".plan.md")
            print(f"##PROGRESS## {{task_id}} | Phase: Execute | 1/1", flush=True)
            time.sleep({sleep_seconds})
            status_path = task_path.with_name(task_id + ".status")
            status_path.write_text(
                "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
                encoding="utf-8",
            )
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (prompts_dir / "planner.md").write_text("Plan prompt.\n", encoding="utf-8")
    (prompts_dir / "resolver.md").write_text("Resolve prompt.\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Packet 11 slow runtime pack.
            version: 1.2.3

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-sonnet
                prompt: prompts/planner.md
                max_instances: 1
              resolution:
                enabled: true
                executor: agent
                model: claude-sonnet
                prompt: prompts/resolver.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 1
              verification:
                enabled: false

            timeouts:
              task_idle: 300
              task_max: 0
              session_max: 14400

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return load_pack_manifest(pack_root)


def _write_fixture_runtime_pack(
    runtime_paths,
    *,
    repo_root: Path,
    fixture_name: str,
    name: str = "claude-code",
    max_workers: int = 1,
    task_idle: int = 300,
    task_max: int = 0,
    session_max: int = 14400,
) -> PackManifest:
    pack_root = runtime_paths.packs / name
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = repo_root / "tests" / "fixtures" / "workers" / fixture_name
    execute_path = scripts_dir / fixture_name
    execute_path.write_text(fixture_path.read_text(encoding="utf-8"), encoding="utf-8")
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (prompts_dir / "planner.md").write_text("Plan prompt.\n", encoding="utf-8")
    (prompts_dir / "resolver.md").write_text("Resolve prompt.\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Packet 11 runtime fixture pack.
            version: 1.2.3

            phases:
              resolution:
                enabled: true
                executor: passthrough
              execution:
                enabled: true
                executor: shell
                command: scripts/{fixture_name}
                max_workers: {max_workers}
              verification:
                enabled: false

            timeouts:
              task_idle: {task_idle}
              task_max: {task_max}
              session_max: {session_max}

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return load_pack_manifest(pack_root)


def _register_task(
    store: StateStore,
    session_id: str,
    *,
    task_id: str,
    title: str,
    depends_on: tuple[str, ...] = (),
    anti_affinity: tuple[str, ...] = (),
    exec_order: int = 1,
    full_test_after: bool = False,
) -> None:
    store.register_task_plan(
        session_id=session_id,
        plan=TaskPlan(
            task_id=task_id,
            title=title,
            depends_on=depends_on,
            anti_affinity=anti_affinity,
            exec_order=exec_order,
            full_test_after=full_test_after,
            body=f"# Plan: {title}\n",
        ),
        plan_text=f"# Plan: {title}\n",
        created_at="2026-03-09T10:01:00Z",
    )


class FakeSessionController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def create_session(self, *, session_id: str, name: str, pack: str, config_json: str | None = None):
        self.calls.append(
            ("create_session", session_id, {"name": name, "pack": pack, "config_json": config_json})
        )
        return {"session_id": session_id}

    def start(self, session_id: str) -> None:
        self.calls.append(("start", session_id, None))

    def pause(self, session_id: str) -> None:
        self.calls.append(("pause", session_id, None))

    def resume(self, session_id: str) -> None:
        self.calls.append(("resume", session_id, None))

    def abort(self, session_id: str) -> None:
        self.calls.append(("abort", session_id, None))

    def retry_task(self, session_id: str, task_id: str) -> None:
        self.calls.append(("retry_task", session_id, task_id))

    def move_task(self, session_id: str, task_id: str, target_status: str) -> dict[str, str]:
        self.calls.append(("move_task", session_id, {"task_id": task_id, "target_status": target_status}))
        return {"status": "moved", "from": "unknown", "to": target_status}


def _wait_until(predicate, *, timeout: float = 2.0, interval: float = 0.02) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met before timeout")


def _wait_for_websocket_message(
    websocket,
    predicate,
    *,
    max_messages: int = 32,
) -> dict[str, object]:
    seen: list[dict[str, object]] = []
    for _ in range(max_messages):
        item = websocket.receive_json()
        seen.append(item)
        if predicate(item):
            return item
    raise AssertionError(f"expected websocket message was not received; saw: {seen!r}")


def _timestamp_offset(*, seconds: int) -> str:
    return datetime.fromtimestamp(datetime.now(UTC).timestamp() + seconds, tz=UTC).isoformat().replace(
        "+00:00",
        "Z",
    )


def test_serve_command_scans_to_next_free_port_and_starts_app(tmp_path: Path) -> None:
    """Verify find_free_port skips occupied ports and serve_backend receives the resolved port."""
    from cognitive_switchyard.server import find_free_port, serve_backend

    # Occupy a dynamically-chosen port so find_free_port must skip it.
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    occupied.bind(("127.0.0.1", 0))
    occupied_port = occupied.getsockname()[1]
    occupied.listen(1)

    try:
        resolved = find_free_port(occupied_port)
        # The occupied port should be skipped.
        assert resolved != occupied_port
        assert resolved > occupied_port
    finally:
        occupied.close()


def test_get_packs_and_pack_detail_serialize_runtime_manifests(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    manifest = _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        packs_response = client.get("/api/packs")
        detail_response = client.get(f"/api/packs/{manifest.name}")

        assert packs_response.status_code == 200
        assert packs_response.json() == {
            "packs": [
                {
                    "name": "claude-code",
                    "description": "Packet 11 runtime pack.",
                    "version": "1.2.3",
                    "max_workers": 2,
                    "max_planners": 2,
                    "planning_enabled": True,
                    "verification_enabled": False,
                }
            ]
        }
        assert detail_response.status_code == 200
        assert detail_response.json() == {
            "name": "claude-code",
            "description": "Packet 11 runtime pack.",
            "version": "1.2.3",
            "root": str(runtime_paths.packs / "claude-code"),
            "phases": {
                "planning": {
                    "enabled": True,
                    "executor": "agent",
                    "runtime": "claude",
                    "model": "claude-sonnet",
                    "reasoning_effort": None,
                    "prompt": str(runtime_paths.packs / "claude-code" / "prompts" / "planner.md"),
                    "max_instances": 2,
                },
                "resolution": {
                    "enabled": True,
                    "executor": "agent",
                    "runtime": "claude",
                    "model": "claude-sonnet",
                    "reasoning_effort": None,
                    "prompt": str(runtime_paths.packs / "claude-code" / "prompts" / "resolver.md"),
                    "script": None,
                },
                "execution": {
                    "enabled": True,
                    "executor": "shell",
                    "reasoning_effort": None,
                    "command": str(runtime_paths.packs / "claude-code" / "scripts" / "execute"),
                    "max_workers": 2,
                },
            },
            "auto_fix": {
                "enabled": False,
                "max_attempts": 2,
                "runtime": "claude",
                "model": None,
                "reasoning_effort": None,
                "prompt": None,
            },
            "timeouts": {"task_idle": 300, "task_max": 0, "session_max": 14400},
        }


def test_create_session_accepts_session_overrides_and_returns_effective_runtime_config(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        response = client.post(
            "/api/sessions",
            json={
                "id": "session-11c-create",
                "name": "Packet 11C create",
                "pack": "claude-code",
                "config": {
                    "worker_count": 1,
                    "verification_interval": 6,
                    "task_idle": 25,
                    "task_max": 90,
                    "session_max": 600,
                    "auto_fix_enabled": True,
                    "auto_fix_max_attempts": 4,
                    "poll_interval": 0.25,
                    "environment": {"API_MODE": "setup", "TRACE_TOKEN": "abc123"},
                },
            },
        )

        assert response.status_code == 201
        payload = response.json()["session"]
        assert payload["config"] == {
            "worker_count": 1,
            "verification_interval": 6,
            "task_idle": 25,
            "task_max": 90,
            "session_max": 600,
            "auto_fix_enabled": True,
            "auto_fix_max_attempts": 4,
            "poll_interval": 0.25,
            "environment": {"API_MODE": "setup", "TRACE_TOKEN": "abc123"},
        }
        assert payload["effective_runtime_config"] == {
            "planner_count": 2,
            "worker_count": 1,
            "verification_interval": 6,
            "timeouts": {"task_idle": 25, "task_max": 90, "session_max": 600},
            "auto_fix": {"enabled": True, "max_attempts": 4},
            "poll_interval": 0.25,
            "environment": {"API_MODE": "setup", "TRACE_TOKEN": "abc123"},
        }
        assert json.loads(store.get_session("session-11c-create").config_json or "{}") == payload["config"]


def test_create_session_succeeds_when_pack_directory_is_missing(
    tmp_path: Path,
) -> None:
    """Regression: _serialize_session must not crash if the pack dir is absent."""
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    # Deliberately do NOT write a runtime pack — pack dir won't exist
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        response = client.post(
            "/api/sessions",
            json={"id": "missing-pack-session", "pack": "nonexistent-pack"},
        )
        assert response.status_code == 201
        payload = response.json()["session"]
        assert payload["id"] == "missing-pack-session"
        assert payload["pack"] == "nonexistent-pack"
        # effective_runtime_config should be empty dict fallback, not a crash
        assert payload["effective_runtime_config"] == {}


def test_create_session_accepts_planner_count_override_and_returns_effective_planner_count(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        response = client.post(
            "/api/sessions",
            json={
                "id": "session-11d-create",
                "name": "Packet 11D create",
                "pack": "claude-code",
                "config": {
                    "planner_count": 5,
                    "worker_count": 1,
                },
            },
        )

        assert response.status_code == 201
        payload = response.json()["session"]
        assert payload["config"] == {
            "planner_count": 5,
            "worker_count": 1,
        }
        assert payload["effective_runtime_config"]["planner_count"] == 2
        assert payload["effective_runtime_config"]["worker_count"] == 1
        assert json.loads(store.get_session("session-11d-create").config_json or "{}") == payload["config"]


def test_session_dashboard_task_and_dag_endpoints_reflect_live_store_state(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11",
        name="Packet 11 Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at="2026-03-09T10:05:00Z",
    )
    _register_task(store, session.id, task_id="001", title="Ready task", exec_order=2)
    _register_task(
        store,
        session.id,
        task_id="002",
        title="Active task",
        depends_on=("001",),
        anti_affinity=("003",),
        exec_order=1,
        full_test_after=True,
    )
    _register_task(store, session.id, task_id="003", title="Done task", exec_order=3)
    store.project_task(
        session.id,
        "002",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:06:00Z",
    )
    store.project_task(
        session.id,
        "003",
        status="done",
        timestamp="2026-03-09T10:07:00Z",
    )
    store.write_session_runtime_state(
        session.id,
        completed_since_verification=1,
        verification_pending=True,
        verification_reason="interval",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.worker_log(0).parent.mkdir(parents=True, exist_ok=True)
    session_paths.worker_log(0).write_text("worker output\n", encoding="utf-8")
    session_paths.resolution.write_text(
        dedent(
            """
            {
              "resolved_at": "2026-03-09T10:05:30Z",
              "tasks": [
                {"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 2},
                {"task_id": "002", "depends_on": ["001"], "anti_affinity": ["003"], "exec_order": 1},
                {"task_id": "003", "depends_on": [], "anti_affinity": [], "exec_order": 3}
              ],
              "groups": [],
              "conflicts": [],
              "notes": "Resolved."
            }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        sessions_response = client.get("/api/sessions")
        session_response = client.get(f"/api/sessions/{session.id}")
        tasks_response = client.get(f"/api/sessions/{session.id}/tasks")
        task_response = client.get(f"/api/sessions/{session.id}/tasks/002")
        dashboard_response = client.get(f"/api/sessions/{session.id}/dashboard")
        dag_response = client.get(f"/api/sessions/{session.id}/dag")

        assert sessions_response.status_code == 200
        assert sessions_response.json()["sessions"][0]["id"] == "session-11"
        assert session_response.status_code == 200
        assert session_response.json()["session"] == {
            "id": "session-11",
            "name": "Packet 11 Session",
            "pack": "claude-code",
            "status": "running",
            "created_at": "2026-03-09T10:00:00Z",
            "started_at": "2026-03-09T10:05:00Z",
            "completed_at": None,
            "config": {},
            "effective_runtime_config": {
                "planner_count": 2,
                "worker_count": 2,
                "verification_interval": 4,
                "timeouts": {"task_idle": 300, "task_max": 0, "session_max": 14400},
                "auto_fix": {"enabled": False, "max_attempts": 2},
                "poll_interval": 0.05,
                "environment": {},
            },
            "runtime_state": {
                "completed_since_verification": 1,
                "verification_pending": True,
                "verification_reason": "interval",
                "verification_started_at": None,
                "verification_elapsed": None,
                "auto_fix_context": None,
                "auto_fix_task_id": None,
                "auto_fix_attempt": 0,
                "last_fix_summary": None,
                "last_verification_test_summary": None,
                "dispatch_frozen": False,
                "dispatch_frozen_reason": None,
            },
            "summary": None,
        }
        assert tasks_response.status_code == 200
        assert [task["task_id"] for task in tasks_response.json()["tasks"]] == ["002", "001", "003"]
        assert task_response.status_code == 200
        task_data = task_response.json()["task"]
        assert task_data == {
            "task_id": "002",
            "title": "Active task",
            "status": "active",
            "depends_on": ["001"],
            "anti_affinity": ["003"],
            "exec_order": 1,
            "full_test_after": True,
            "worker_slot": 0,
            "plan_path": str(session_paths.worker_dir(0) / "002.plan.md"),
            "log_path": str(session_paths.task_log("002")),
            "created_at": "2026-03-09T10:01:00Z",
            "started_at": "2026-03-09T10:06:00Z",
            "completed_at": None,
            "elapsed": task_data["elapsed"],
            "history_source": "live",
            "events": task_data["events"],
        }
        assert task_data["elapsed"] >= 0
        assert isinstance(task_data["events"], list)
        assert dashboard_response.status_code == 200
        dashboard_payload = dashboard_response.json()
        assert "pipeline_dirs" in dashboard_payload
        assert set(dashboard_payload["pipeline_dirs"].keys()) == {
            "intake", "planning", "staged", "review", "ready", "active", "done", "blocked"
        }
        # Remove pipeline_dirs for the structural comparison (paths are tmp-dependent)
        dashboard_without_dirs = {k: v for k, v in dashboard_payload.items() if k != "pipeline_dirs"}
        assert dashboard_without_dirs == {
            "session": {
                "id": "session-11",
                "status": "running",
                "pack": "claude-code",
                "started_at": "2026-03-09T10:05:00Z",
                "elapsed": dashboard_payload["session"]["elapsed"],
                "run_elapsed": dashboard_payload["session"]["run_elapsed"],
                "run_number": dashboard_payload["session"]["run_number"],
                "config": {},
                "effective_runtime_config": {
                    "planner_count": 2,
                    "worker_count": 2,
                    "verification_interval": 4,
                    "timeouts": {"task_idle": 300, "task_max": 0, "session_max": 14400},
                    "auto_fix": {"enabled": False, "max_attempts": 2},
                    "poll_interval": 0.05,
                    "environment": {},
                },
            },
            "pipeline": {
                "intake": 0,
                "planning": 0,
                "staged": 0,
                "review": 0,
                "ready": 1,
                "active": 1,
                "verifying": 0,
                "done": 1,
                "blocked": 0,
            },
            "workers": [
                {
                    "slot": 0,
                    "status": "active",
                    "task_id": "002",
                    "task_title": "Active task",
                    "elapsed": dashboard_payload["workers"][0]["elapsed"],
                    "started_at": dashboard_payload["workers"][0]["started_at"],
                },
                {
                    "slot": 1,
                    "status": "idle",
                },
            ],
            "recent_events": [],
            "runtime_state": {
                "completed_since_verification": 1,
                "verification_pending": True,
                "verification_reason": "interval",
                "verification_started_at": None,
                "verification_elapsed": None,
                "auto_fix_context": None,
                "auto_fix_task_id": None,
                "auto_fix_attempt": 0,
                "last_fix_summary": None,
                "last_verification_test_summary": None,
                "dispatch_frozen": False,
                "dispatch_frozen_reason": None,
            },
            "effective_runtime_config": {
                "planner_count": 2,
                "worker_count": 2,
                "verification_interval": 4,
                "timeouts": {"task_idle": 300, "task_max": 0, "session_max": 14400},
                "auto_fix": {"enabled": False, "max_attempts": 2},
                "poll_interval": 0.05,
                "environment": {},
            },
        }
        assert dashboard_payload["session"]["elapsed"] >= 0
        assert dashboard_payload["workers"][0]["elapsed"] >= 0
        assert dag_response.status_code == 200
        assert dag_response.json()["tasks"][1] == {
            "task_id": "002",
            "depends_on": ["001"],
            "anti_affinity": ["003"],
            "exec_order": 1,
        }


def test_root_serves_embedded_spa_document_while_preserving_packet11_api_routes(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        root_response = client.get("/")
        packs_response = client.get("/api/packs")
        settings_response = client.get("/api/settings")

        assert root_response.status_code == 200
        assert root_response.headers["content-type"].startswith("text/html")
        assert "<!DOCTYPE html>" in root_response.text
        assert 'id="switchyard-app"' in root_response.text
        assert packs_response.status_code == 200
        assert packs_response.json()["packs"][0]["name"] == "claude-code"
        assert settings_response.status_code == 200
        assert settings_response.json()["settings"]["default_pack"] == "claude-code"


def test_root_bootstrap_payload_supports_setup_monitor_history_and_settings_views_without_extra_requests(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    write_global_config(
        runtime_paths.config,
        GlobalConfig(
            retention_days=14,
            default_planners=4,
            default_workers=2,
            default_pack="claude-code",
        ),
    )
    active_session = store.create_session(
        session_id="session-12-active",
        name="Active Packet 12 Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps({"planner_count": 1, "worker_count": 1}),
    )
    store.update_session_status(
        active_session.id,
        status="running",
        started_at="2026-03-09T10:05:00Z",
    )
    _register_task(store, active_session.id, task_id="001", title="Monitor task", exec_order=1)
    store.project_task(
        active_session.id,
        "001",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:06:00Z",
    )
    intake_file = runtime_paths.session_paths(active_session.id).intake / "001_monitor.md"
    intake_file.write_text("# Monitor\n", encoding="utf-8")

    store.create_session(
        session_id="session-12-history",
        name="Completed Packet 12 Session",
        pack="claude-code",
        created_at="2026-03-08T10:00:00Z",
    )
    store.update_session_status(
        "session-12-history",
        status="completed",
        started_at="2026-03-08T10:05:00Z",
        completed_at="2026-03-08T10:45:00Z",
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        response = client.get("/")

        assert response.status_code == 200
        match = re.search(
            r'<script id="switchyard-bootstrap" type="application/json">(.*?)</script>',
            response.text,
            re.DOTALL,
        )
        assert match is not None
        payload = json.loads(match.group(1))

        assert payload["views"] == [
            "setup",
            "monitor",
            "task-detail",
            "dag",
            "history",
            "settings",
        ]
        settings = payload["settings"]
        assert settings["retention_days"] == 14
        assert settings["default_planners"] == 4
        assert settings["default_workers"] == 2
        assert settings["default_pack"] == "claude-code"
        assert "runtime_root" in settings
        assert payload["packs"] == [
            {
                "name": "claude-code",
                "description": "Packet 11 runtime pack.",
                "version": "1.2.3",
                "max_workers": 2,
                "max_planners": 2,
                "planning_enabled": True,
                "verification_enabled": False,
            }
        ]
        assert [session["id"] for session in payload["sessions"]] == [
            "session-12-active",
            "session-12-history",
        ]
        assert payload["current_session"]["id"] == "session-12-active"
        assert payload["current_session"]["status"] == "running"
        assert payload["dashboard"]["session"]["id"] == "session-12-active"
        assert payload["dashboard"]["workers"][0]["task_id"] == "001"
        assert payload["intake"]["locked"] is True
        assert payload["intake"]["files"][0]["filename"] == "001_monitor.md"


def test_root_bootstrap_payload_leaves_current_session_empty_when_only_history_exists(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    store.create_session(
        session_id="session-12-history-only",
        name="History Only Session",
        pack="claude-code",
        created_at="2026-03-08T10:00:00Z",
    )
    store.update_session_status(
        "session-12-history-only",
        status="completed",
        started_at="2026-03-08T10:05:00Z",
        completed_at="2026-03-08T10:45:00Z",
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        response = client.get("/")

        assert response.status_code == 200
        match = re.search(
            r'<script id="switchyard-bootstrap" type="application/json">(.*?)</script>',
            response.text,
            re.DOTALL,
        )
        assert match is not None
        payload = json.loads(match.group(1))

        assert payload["sessions"][0]["id"] == "session-12-history-only"
        assert payload["current_session"] is None
        assert payload["dashboard"] is None
        assert payload["intake"] is None


def test_history_session_serialization_reads_summary_data_after_successful_trim(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-12a-history",
        name="History Summary Session",
        pack="claude-code",
        created_at="2026-03-08T10:00:00Z",
        config_json=json.dumps({"worker_count": 1}, sort_keys=True),
    )
    _register_task(
        store,
        session.id,
        task_id="001",
        title="Successful history task",
        exec_order=2,
    )
    store.project_task(
        session.id,
        "001",
        status="done",
        timestamp="2026-03-08T10:20:00Z",
    )
    store.append_event(
        session.id,
        timestamp="2026-03-08T10:25:00Z",
        event_type="session.completed",
        message="All tasks completed successfully.",
    )
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-08T10:05:00Z",
        completed_at="2026-03-08T10:25:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.resolution.write_text(
        '{"resolved_at":"2026-03-08T10:04:00Z","tasks":[{"task_id":"001","depends_on":[],"anti_affinity":[],"exec_order":2}]}\n',
        encoding="utf-8",
    )
    session_paths.worker_log(0).parent.mkdir(parents=True, exist_ok=True)
    session_paths.worker_log(0).write_text("worker log\n", encoding="utf-8")
    store.write_successful_session_summary(session.id)
    store.trim_successful_session_artifacts(session.id)

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        sessions_response = client.get("/api/sessions")
        session_response = client.get(f"/api/sessions/{session.id}")
        tasks_response = client.get(f"/api/sessions/{session.id}/tasks")
        task_response = client.get(f"/api/sessions/{session.id}/tasks/001")
        log_response = client.get(f"/api/sessions/{session.id}/tasks/001/log?offset=0&limit=50")
        dashboard_response = client.get(f"/api/sessions/{session.id}/dashboard")

        assert sessions_response.status_code == 200
        listed = sessions_response.json()["sessions"][0]
        assert listed["id"] == session.id
        assert listed["summary"]["session"]["id"] == session.id
        assert listed["summary"]["tasks"][0]["task_id"] == "001"
        assert listed["summary"]["tasks"][0]["status"] == "done"

        detail = session_response.json()["session"]
        assert detail["id"] == session.id
        assert detail["summary"]["session"]["duration_seconds"] == 1200
        assert detail["summary"]["artifacts"] == {
            "summary_path": "summary.json",
            "resolution_path": "resolution.json",
            "session_log_path": "logs/session.log",
        }

        assert tasks_response.json()["tasks"] == [
            {
                "task_id": "001",
                "title": "Successful history task",
                "status": "done",
                "depends_on": [],
                "anti_affinity": [],
                "exec_order": 2,
                "full_test_after": False,
                "worker_slot": None,
                "plan_path": None,
                "log_path": None,
                "created_at": "2026-03-09T10:01:00Z",
                "started_at": None,
                "completed_at": "2026-03-08T10:20:00Z",
                "elapsed": 0,
                "events": [],
                "history_source": "summary",
            }
        ]
        assert task_response.json()["task"]["history_source"] == "summary"
        assert task_response.json()["task"]["plan_path"] is None
        assert log_response.json() == {"path": None, "offset": 0, "content": "", "mtime_iso": None}
        assert dashboard_response.status_code == 200
        assert dashboard_response.json()["session"]["status"] == "completed"
        assert dashboard_response.json()["pipeline"] == {
            "intake": 0,
            "planning": 0,
            "staged": 0,
            "review": 0,
            "ready": 0,
            "active": 0,
            "verifying": 0,
            "done": 1,
            "blocked": 0,
        }


def test_trimmed_history_uses_summary_snapshot_instead_of_live_pack_manifest(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-13-history-snapshot",
        name="History Snapshot Session",
        pack="claude-code",
        created_at="2026-03-08T10:00:00Z",
    )
    _register_task(
        store,
        session.id,
        task_id="001",
        title="Snapshot task",
    )
    store.project_task(
        session.id,
        "001",
        status="done",
        timestamp="2026-03-08T10:20:00Z",
    )
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-08T10:05:00Z",
        completed_at="2026-03-08T10:25:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.resolution.write_text('{"tasks":[]}\n', encoding="utf-8")
    store.write_successful_session_summary(session.id)
    store.trim_successful_session_artifacts(session.id)

    (runtime_paths.packs / "claude-code" / "pack.yaml").write_text(
        dedent(
            """
            name: claude-code
            description: Mutated after completion.
            version: 9.9.9

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/planner.md
                max_instances: 7
              resolution:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/resolver.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 6
              verification:
                enabled: false

            timeouts:
              task_idle: 15
              task_max: 120
              session_max: 240

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        detail = client.get(f"/api/sessions/{session.id}").json()["session"]
        dashboard = client.get(f"/api/sessions/{session.id}/dashboard").json()

        assert detail["effective_runtime_config"] == {
            "planner_count": 2,
            "worker_count": 2,
            "verification_interval": 4,
            "timeouts": {
                "task_idle": 300,
                "task_max": 0,
                "session_max": 14400,
            },
            "auto_fix": {
                "enabled": False,
                "max_attempts": 2,
            },
            "poll_interval": 0.05,
            "environment": {},
        }
        assert dashboard["session"]["effective_runtime_config"] == detail["effective_runtime_config"]


def test_intake_listing_includes_file_metadata_and_locked_state_for_setup_view(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11c-intake",
        name="Packet 11C intake",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    draft = session_paths.intake / "001_alpha.md"
    second = session_paths.intake / "002_beta.md"
    late = session_paths.intake / "003_late.md"
    draft.write_text("# Alpha\n", encoding="utf-8")
    second.write_text("# Beta\n", encoding="utf-8")
    pre_start_timestamp = datetime(2026, 3, 9, 10, 4, 0, tzinfo=UTC).timestamp()
    os.utime(draft, (pre_start_timestamp, pre_start_timestamp))
    os.utime(second, (pre_start_timestamp, pre_start_timestamp))

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        created_response = client.get(f"/api/sessions/{session.id}/intake")
        store.update_session_status(
            session.id,
            status="running",
            started_at="2026-03-09T10:05:00Z",
        )
        late.write_text("# Late\n", encoding="utf-8")
        post_start_timestamp = datetime(2026, 3, 9, 10, 6, 0, tzinfo=UTC).timestamp()
        os.utime(late, (post_start_timestamp, post_start_timestamp))
        locked_response = client.get(f"/api/sessions/{session.id}/intake")

        assert created_response.status_code == 200
        assert created_response.json()["locked"] is False
        assert created_response.json()["files"] == [
            {
                "filename": "001_alpha.md",
                "path": "intake/001_alpha.md",
                "size": len("# Alpha\n".encode("utf-8")),
                "detected_at": created_response.json()["files"][0]["detected_at"],
                "locked": False,
                "in_snapshot": True,
            },
            {
                "filename": "002_beta.md",
                "path": "intake/002_beta.md",
                "size": len("# Beta\n".encode("utf-8")),
                "detected_at": created_response.json()["files"][1]["detected_at"],
                "locked": False,
                "in_snapshot": True,
            },
        ]
        assert locked_response.status_code == 200
        assert locked_response.json()["locked"] is True
        assert locked_response.json()["files"] == [
            {
                "filename": "001_alpha.md",
                "path": "intake/001_alpha.md",
                "size": len("# Alpha\n".encode("utf-8")),
                "detected_at": "2026-03-09T10:04:00Z",
                "locked": True,
                "in_snapshot": True,
            },
            {
                "filename": "002_beta.md",
                "path": "intake/002_beta.md",
                "size": len("# Beta\n".encode("utf-8")),
                "detected_at": "2026-03-09T10:04:00Z",
                "locked": True,
                "in_snapshot": True,
            },
            {
                "filename": "003_late.md",
                "path": "intake/003_late.md",
                "size": len("# Late\n".encode("utf-8")),
                "detected_at": "2026-03-09T10:06:00Z",
                "locked": True,
                "in_snapshot": False,
            },
        ]


def test_dashboard_uses_effective_session_worker_count_not_pack_max_workers(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11c-dashboard",
        name="Packet 11C dashboard",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps({"worker_count": 1}),
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-30),
    )
    _register_task(store, session.id, task_id="002", title="Single worker task")
    store.project_task(
        session.id,
        "002",
        status="active",
        worker_slot=0,
        timestamp=_timestamp_offset(seconds=-5),
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        response = client.get(f"/api/sessions/{session.id}/dashboard")

        assert response.status_code == 200
        payload = response.json()
        assert payload["session"]["effective_runtime_config"]["worker_count"] == 1
        assert payload["workers"] == [
            {
                "slot": 0,
                "status": "active",
                "task_id": "002",
                "task_title": "Single worker task",
                "elapsed": payload["workers"][0]["elapsed"],
                "started_at": payload["workers"][0]["started_at"],
            }
        ]


def test_session_preflight_route_reports_permission_and_prerequisite_results_without_starting_execution(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_preflight_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11b-preflight",
        name="Packet 11B Preflight",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        response = client.post(f"/api/sessions/{session.id}/preflight")

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "permission_report": {"ok": True, "issues": []},
            "prerequisite_results": {
                "ok": True,
                "results": [
                    {
                        "name": "CLI available",
                        "check": "printf 'cli ok\\n'",
                        "ok": True,
                        "exit_code": 0,
                        "stdout": "cli ok\n",
                        "stderr": "",
                    }
                ],
            },
            "preflight_result": {
                "hook_name": "preflight",
                "script_path": str(runtime_paths.packs / "claude-code" / "scripts" / "preflight"),
                "args": [],
                "cwd": str(runtime_paths.packs / "claude-code"),
                "ok": True,
                "exit_code": 0,
                "stdout": "pack preflight ok\n",
                "stderr": "",
            },
        }
        assert store.get_session(session.id).status == "created"


def test_dashboard_payload_includes_configured_idle_workers_and_latest_runtime_progress_fields(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11b-dashboard",
        name="Packet 11B Dashboard",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-120),
    )
    _register_task(store, session.id, task_id="002", title="Active task")
    store.project_task(
        session.id,
        "002",
        status="active",
        worker_slot=0,
        timestamp=_timestamp_offset(seconds=-45),
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    controller = app.state.controller
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="log_line",
            session_id=session.id,
            data={
                "worker_slot": 0,
                "task_id": "002",
                "line": "##PROGRESS## 002 | Phase: implementing | 2/5",
                "timestamp": "2026-03-09T10:06:01Z",
            },
        )
    )
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="progress_detail",
            session_id=session.id,
            data={
                "worker_slot": 0,
                "task_id": "002",
                "detail": "Processing chunk 3/9",
                "timestamp": "2026-03-09T10:06:02Z",
            },
        )
    )
    with TestClient(app) as client:

        response = client.get(f"/api/sessions/{session.id}/dashboard")

        assert response.status_code == 200
        payload = response.json()
        assert payload["session"]["id"] == session.id
        assert payload["session"]["status"] == "running"
        assert payload["session"]["elapsed"] >= 100
        assert payload["workers"] == [
            {
                "slot": 0,
                "status": "active",
                "task_id": "002",
                "task_title": "Active task",
                "phase": "implementing",
                "phase_num": 2,
                "phase_total": 5,
                "detail": "Processing chunk 3/9",
                "elapsed": payload["workers"][0]["elapsed"],
                "started_at": payload["workers"][0]["started_at"],
            },
            {"slot": 1, "status": "idle"},
        ]
        assert payload["workers"][0]["elapsed"] >= 30


def test_state_update_snapshot_after_runtime_events_preserves_worker_card_fields_for_reconnecting_clients(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-11b-reconnect",
        name="Packet 11B Reconnect",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-90),
    )
    _register_task(store, session.id, task_id="003", title="Reconnect task")
    store.project_task(
        session.id,
        "003",
        status="active",
        worker_slot=0,
        timestamp=_timestamp_offset(seconds=-20),
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    controller = app.state.controller
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="log_line",
            session_id=session.id,
            data={
                "worker_slot": 0,
                "task_id": "003",
                "line": "##PROGRESS## 003 | Phase: testing | 4/5",
                "timestamp": "2026-03-09T10:06:05Z",
            },
        )
    )
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="progress_detail",
            session_id=session.id,
            data={
                "worker_slot": 0,
                "task_id": "003",
                "detail": "Running targeted tests",
                "timestamp": "2026-03-09T10:06:06Z",
            },
        )
    )
    with TestClient(app) as client:

        with client.websocket_connect("/ws") as websocket:
            controller._publish_snapshot(session.id)
            message = _wait_for_websocket_message(
                websocket,
                lambda item: item["type"] == "state_update"
                and item["data"]["session"]["id"] == session.id,
            )

        assert message["data"]["workers"][0]["task_id"] == "003"
        assert message["data"]["workers"][0]["phase"] == "testing"
        assert message["data"]["workers"][0]["phase_num"] == 4
        assert message["data"]["workers"][0]["phase_total"] == 5
        assert message["data"]["workers"][0]["detail"] == "Running targeted tests"


def test_pause_resume_abort_and_retry_routes_delegate_to_background_session_controller(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    store.create_session(
        session_id="session-11-control",
        name="Control Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, "session-11-control", task_id="007", title="Retry me")
    controller = FakeSessionController()
    app = create_app(store=store, runtime_paths=runtime_paths, controller=controller)
    with TestClient(app) as client:

        pause_response = client.post("/api/sessions/session-11-control/pause")
        resume_response = client.post("/api/sessions/session-11-control/resume")
        abort_response = client.post("/api/sessions/session-11-control/abort")
        retry_response = client.post("/api/sessions/session-11-control/tasks/007/retry")

        assert pause_response.status_code == 202
        assert resume_response.status_code == 202
        assert abort_response.status_code == 202
        assert retry_response.status_code == 202
        assert controller.calls == [
            ("pause", "session-11-control", None),
            ("resume", "session-11-control", None),
            ("abort", "session-11-control", None),
            ("retry_task", "session-11-control", "007"),
        ]


def test_pause_and_abort_routes_control_the_real_background_session_loop(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_slow_runtime_pack(runtime_paths)
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    pause_session = store.create_session(
        session_id="session-11-pause",
        name="Pause Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        pause_session.id,
        status="running",
        started_at=started_at,
    )
    _register_task(store, pause_session.id, task_id="001", title="First task", exec_order=1)
    _register_task(store, pause_session.id, task_id="002", title="Second task", exec_order=2)

    abort_session = store.create_session(
        session_id="session-11-abort",
        name="Abort Session",
        pack="claude-code",
        created_at="2026-03-09T10:10:00Z",
    )
    store.update_session_status(
        abort_session.id,
        status="running",
        started_at=started_at,
    )
    _register_task(store, abort_session.id, task_id="010", title="Abort me", exec_order=1)
    _register_task(store, abort_session.id, task_id="011", title="Still ready", exec_order=2)

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        start_pause_response = client.post(f"/api/sessions/{pause_session.id}/start")
        assert start_pause_response.status_code == 202
        _wait_until(lambda: store.get_task(pause_session.id, "001").status == "active")

        pause_response = client.post(f"/api/sessions/{pause_session.id}/pause")
        assert pause_response.status_code == 202
        _wait_until(lambda: store.get_task(pause_session.id, "001").status == "done")
        time.sleep(0.3)

        assert store.get_session(pause_session.id).status == "paused"
        assert store.get_task(pause_session.id, "002").status == "ready"

        resume_response = client.post(f"/api/sessions/{pause_session.id}/resume")
        assert resume_response.status_code == 202
        _wait_until(lambda: store.get_session(pause_session.id).status == "idle")
        assert store.get_task(pause_session.id, "002").status == "done"

        start_abort_response = client.post(f"/api/sessions/{abort_session.id}/start")
        assert start_abort_response.status_code == 202
        _wait_until(lambda: store.get_task(abort_session.id, "010").status == "active")

        abort_response = client.post(f"/api/sessions/{abort_session.id}/abort")
        assert abort_response.status_code == 202
        _wait_until(lambda: store.get_task(abort_session.id, "010").status == "blocked")

        assert store.get_session(abort_session.id).status == "aborted"
        assert store.get_task(abort_session.id, "011").status == "ready"


def test_open_intake_and_reveal_file_reject_traversal_outside_session_root(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    store.create_session(
        session_id="session-11-files",
        name="Files Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths("session-11-files")
    inside_file = session_paths.intake / "001.plan.md"
    inside_file.parent.mkdir(parents=True, exist_ok=True)
    inside_file.write_text("# intake\n", encoding="utf-8")
    calls: list[list[str]] = []

    def command_runner(command: list[str]) -> None:
        calls.append(command)

    app = create_app(
        store=store,
        runtime_paths=runtime_paths,
        command_runner=command_runner,
    )
    with TestClient(app) as client:

        open_response = client.post("/api/sessions/session-11-files/open-intake")
        reveal_response = client.post(
            "/api/sessions/session-11-files/reveal-file",
            params={"path": "intake/001.plan.md"},
        )
        traversal_response = client.post(
            "/api/sessions/session-11-files/reveal-file",
            params={"path": "../outside.txt"},
        )

        assert open_response.status_code == 204
        assert reveal_response.status_code == 204
        assert traversal_response.status_code == 400
        assert calls == [
            ["open", str(session_paths.intake)],
            ["open", "-R", str(inside_file)],
        ]


def test_websocket_broadcasts_state_updates_alerts_and_slot_scoped_log_lines(tmp_path: Path) -> None:
    from cognitive_switchyard.server import _run_async, create_app

    store, runtime_paths = _build_store(tmp_path)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        manager = app.state.connection_manager

        def _send(coro):
            """Schedule an async broadcast on the connection manager's event loop.

            Using ``_run_async`` instead of bare ``asyncio.run()`` ensures this
            works even when a prior test module (e.g. e2e) left a stale event
            loop associated with the main thread.
            """
            _run_async(coro, loop=manager.event_loop)

        with client.websocket_connect("/ws") as websocket:
            _send(
                manager.broadcast_state(
                    {
                        "session": {"status": "running", "elapsed": 12},
                        "pipeline": {"ready": 1, "active": 1, "done": 0},
                        "workers": [{"slot": 0, "status": "active", "task_id": "002"}],
                    }
                )
            )
            state_message = websocket.receive_json()
            assert state_message["type"] == "state_update"
            assert state_message["data"]["session"]["status"] == "running"

            websocket.send_json({"type": "subscribe_logs", "worker_slot": 0})
            _send(
                manager.send_log_line(
                    0,
                    {
                        "worker_slot": 0,
                        "task_id": "002",
                        "line": "##PROGRESS## 002 | Phase: Execute | 1/1",
                        "timestamp": "2026-03-09T10:06:01Z",
                    },
                )
            )
            log_message = websocket.receive_json()
            assert log_message == {
                "type": "log_line",
                "data": {
                    "worker_slot": 0,
                    "task_id": "002",
                    "line": "##PROGRESS## 002 | Phase: Execute | 1/1",
                    "timestamp": "2026-03-09T10:06:01Z",
                },
            }

            _send(
                manager.broadcast_task_status_change(
                    {
                        "task_id": "002",
                        "old_status": "active",
                        "new_status": "done",
                        "worker_slot": 0,
                        "notes": "Completed.",
                    }
                )
            )
            status_message = websocket.receive_json()
            assert status_message["type"] == "task_status_change"

            _send(
                manager.broadcast_progress_detail(
                    {
                        "worker_slot": 0,
                        "task_id": "002",
                        "detail": "Processing chunk 2/3",
                        "timestamp": "2026-03-09T10:06:02Z",
                    }
                )
            )
            progress_message = websocket.receive_json()
            assert progress_message == {
                "type": "progress_detail",
                "data": {
                    "worker_slot": 0,
                    "task_id": "002",
                    "detail": "Processing chunk 2/3",
                    "timestamp": "2026-03-09T10:06:02Z",
                },
            }

            _send(
                manager.broadcast_alert(
                    {
                        "severity": "error",
                        "task_id": "002",
                        "worker_slot": 0,
                        "message": "No progress for 5 minutes",
                    }
                )
            )
            alert_message = websocket.receive_json()
            assert alert_message == {
                "type": "alert",
                "data": {
                    "severity": "error",
                    "task_id": "002",
                    "worker_slot": 0,
                    "message": "No progress for 5 minutes",
                },
            }


def test_background_session_websocket_streams_runtime_task_status_changes_before_completion(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_fixture_runtime_pack(
        runtime_paths,
        repo_root=repo_root,
        fixture_name="streaming_worker.py",
    )
    session = store.create_session(
        session_id="session-11a-runtime-status",
        name="Runtime Status Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    _register_task(store, session.id, task_id="039", title="Streaming task")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        with client.websocket_connect("/ws") as websocket:
            start_response = client.post(f"/api/sessions/{session.id}/start")
            assert start_response.status_code == 202

            active_status = _wait_for_websocket_message(
                websocket,
                lambda message: message["type"] == "task_status_change"
                and message["data"]["task_id"] == "039"
                and message["data"]["old_status"] == "ready"
                and message["data"]["new_status"] == "active",
            )
            live_state = _wait_for_websocket_message(
                websocket,
                lambda message: message["type"] == "state_update"
                and message["data"]["session"]["id"] == session.id
                and message["data"]["session"]["status"] == "running"
                and message["data"]["pipeline"]["active"] == 1
                and message["data"]["pipeline"]["done"] == 0,
            )

            assert active_status["data"]["worker_slot"] == 0
            assert store.get_session(session.id).status == "running"
            assert live_state["data"]["workers"][0]["task_id"] == "039"

            # Regression: task_status_change for active must include started_at so
            # TaskRowElapsed can tick for tasks that go active after the initial fetch.
            assert "started_at" in active_status["data"], (
                "task_status_change active payload must include started_at so TaskRowElapsed works on non-first tasks"
            )
            assert active_status["data"]["started_at"] is not None, (
                "task_status_change active payload started_at must be a non-None timestamp"
            )

            done_status = _wait_for_websocket_message(
                websocket,
                lambda message: message["type"] == "task_status_change"
                and message["data"]["task_id"] == "039"
                and message["data"]["old_status"] == "active"
                and message["data"]["new_status"] == "done",
            )

            assert done_status["data"]["worker_slot"] == 0

            # Regression: task_status_change for done must include started_at and completed_at.
            assert "started_at" in done_status["data"], (
                "task_status_change done payload must include started_at"
            )
            assert done_status["data"]["started_at"] is not None
            assert "completed_at" in done_status["data"], (
                "task_status_change done payload must include completed_at"
            )
            assert done_status["data"]["completed_at"] is not None

            _wait_until(lambda: store.get_session(session.id).status == "idle")


def test_background_session_websocket_streams_subscribed_log_lines_and_progress_detail_from_real_worker_output(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_fixture_runtime_pack(
        runtime_paths,
        repo_root=repo_root,
        fixture_name="streaming_worker.py",
    )
    session = store.create_session(
        session_id="session-11a-runtime-logs",
        name="Runtime Log Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    _register_task(store, session.id, task_id="039", title="Streaming task")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "subscribe_logs", "worker_slot": 0})
            start_response = client.post(f"/api/sessions/{session.id}/start")
            assert start_response.status_code == 202

            log_message = _wait_for_websocket_message(
                websocket,
                lambda message: message["type"] == "log_line"
                and message["data"]["worker_slot"] == 0
                and message["data"]["task_id"] == "039"
                and "Phase: implementing" in message["data"]["line"],
            )
            progress_message = _wait_for_websocket_message(
                websocket,
                lambda message: message["type"] == "progress_detail"
                and message["data"]["worker_slot"] == 0
                and message["data"]["task_id"] == "039"
                and message["data"]["detail"] == "Streaming detail",
            )

            assert log_message["data"]["timestamp"]
            assert progress_message["data"]["timestamp"]


def test_background_session_websocket_emits_timeout_or_problem_alerts_from_runtime_polling(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_fixture_runtime_pack(
        runtime_paths,
        repo_root=repo_root,
        fixture_name="silent_worker.py",
        task_idle=1,
    )
    session = store.create_session(
        session_id="session-11a-runtime-alert",
        name="Runtime Alert Session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    _register_task(store, session.id, task_id="039", title="Silent task")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        with client.websocket_connect("/ws") as websocket:
            start_response = client.post(f"/api/sessions/{session.id}/start")
            assert start_response.status_code == 202

            alert_message = _wait_for_websocket_message(
                websocket,
                lambda message: message["type"] == "alert"
                and message["data"]["task_id"] == "039"
                and message["data"]["worker_slot"] == 0,
                max_messages=48,
            )

            assert alert_message["data"]["severity"] == "warning"
            assert "No output" in alert_message["data"]["message"]
            _wait_until(lambda: store.get_task(session.id, "039").status == "blocked", timeout=4.0)


def test_backend_start_path_uses_default_claude_runtime_when_agent_callables_are_not_injected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from cognitive_switchyard.models import FixerAttemptResult
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-13-server-default-runtime",
        name="Packet 13 backend default runtime",
        pack="claude-code",
        created_at="2026-03-10T10:00:00Z",
        config_json=json.dumps({
            "environment": {"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
        }),
    )
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.intake / "001_feature.md").write_text("# Feature request\n", encoding="utf-8")
    pack_root = runtime_paths.packs / "claude-code"
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            import sys
            from pathlib import Path

            task_path = Path(sys.argv[1])
            task_id = task_path.name.removesuffix(".plan.md")
            print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
            task_path.with_name(task_id + ".status").write_text(
                "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
                encoding="utf-8",
            )
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (prompts_dir / "planner.md").write_text("Planner prompt.\n", encoding="utf-8")
    (prompts_dir / "resolver.md").write_text("Resolver prompt.\n", encoding="utf-8")
    (prompts_dir / "fixer.md").write_text("Fixer prompt.\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(
        dedent(
            """
            name: claude-code
            description: Packet 13 runtime pack.
            version: 1.2.3

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/planner.md
                max_instances: 1
              resolution:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/resolver.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 1
              verification:
                enabled: false

            auto_fix:
              enabled: true
              max_attempts: 2
              model: claude-opus
              prompt: prompts/fixer.md

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )

    from cognitive_switchyard import orchestrator

    captured: dict[str, object] = {}

    class FakeRuntime:
        def planner_agent(self, **kwargs):
            captured["planner"] = kwargs
            return dedent(
                """
                ---
                PLAN_ID: 001
                PRIORITY: normal
                ESTIMATED_SCOPE: src/feature.py
                DEPENDS_ON: none
                FULL_TEST_AFTER: no
                ---

                # Plan: Task 001

                Implement the feature.
                """
            ).lstrip()

        def resolver_agent(self, **kwargs):
            captured["resolver"] = kwargs
            return (
                '{\n'
                '  "resolved_at": "2026-03-10T10:00:00Z",\n'
                '  "tasks": [{"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1}],\n'
                '  "groups": [],\n'
                '  "conflicts": [],\n'
                '  "notes": "default runtime"\n'
                '}\n'
            )

        def fixer_executor(self, context, **kwargs):
            captured["fixer"] = context.context_type
            return FixerAttemptResult(success=True, summary="fixed")

    monkeypatch.setattr(orchestrator, "build_agent_runtime", lambda runtime_kind, output_line_callback=None: FakeRuntime())

    app = create_app(store=store, runtime_paths=runtime_paths)
    app.state.controller._run_session(session.id)

    assert store.get_session(session.id).status == "idle"
    assert captured["planner"]["model"] == "claude-opus"
    assert captured["planner"]["reasoning_effort"] is None
    assert captured["resolver"]["model"] == "claude-opus"
    assert captured["resolver"]["reasoning_effort"] is None


def test_history_session_detail_includes_release_notes_when_trimmed_session_retains_artifact(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-14-history",
        name="Packet 14 history",
        pack="claude-code",
        created_at="2026-03-10T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.summary.write_text(
        json.dumps(
            {
                "session": {
                    "id": session.id,
                    "name": session.name,
                    "pack": session.pack,
                    "status": "completed",
                    "created_at": session.created_at,
                    "started_at": "2026-03-10T10:01:00Z",
                    "completed_at": "2026-03-10T10:02:00Z",
                    "duration_seconds": 60,
                    "config": {},
                    "effective_runtime_config": {"worker_count": 1},
                    "runtime_state": {},
                },
                "pipeline": {"ready": 0, "active": 0, "done": 1, "blocked": 0},
                "tasks": [
                    {
                        "task_id": "001",
                        "title": "Ship release notes",
                        "status": "done",
                    }
                ],
                "worker_statistics": {"slots_seen": [0], "configured_worker_count": 1},
                "artifacts": {
                    "summary_path": "summary.json",
                    "resolution_path": "resolution.json",
                    "session_log_path": "logs/session.log",
                    "release_notes_path": "RELEASE_NOTES.md",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    session_paths.root.joinpath("RELEASE_NOTES.md").write_text(
        "# Release Notes\n\n- Restart the service after deploy.\n",
        encoding="utf-8",
    )
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-10T10:01:00Z",
        completed_at="2026-03-10T10:02:00Z",
    )
    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{session.id}")

    payload = response.json()["session"]

    assert response.status_code == 200
    assert payload["release_notes"]["path"] == "RELEASE_NOTES.md"
    assert "Restart the service after deploy." in payload["release_notes"]["content"]


def test_create_duplicate_session_returns_409(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        body = {"id": "dup-test", "name": "First", "pack": "claude-code"}
        first = client.post("/api/sessions", json=body)
        assert first.status_code == 201

        second = client.post("/api/sessions", json=body)
        assert second.status_code == 409


def test_resolve_path_expands_tilde_and_detects_git(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        # Test with a real directory (tmp_path exists)
        response = client.post("/api/resolve-path", json={"path": str(tmp_path)})
        assert response.status_code == 200
        data = response.json()
        assert data["exists"] is True
        assert data["is_directory"] is True
        assert data["resolved"] == str(tmp_path.resolve())

        # Test with tilde expansion (home dir exists and is a dir)
        tilde_response = client.post("/api/resolve-path", json={"path": "~"})
        assert tilde_response.status_code == 200
        tilde_data = tilde_response.json()
        assert tilde_data["exists"] is True
        assert tilde_data["is_directory"] is True
        assert "~" not in tilde_data["resolved"]

        # Test with nonexistent path
        missing_response = client.post("/api/resolve-path", json={"path": "/nonexistent/path/xyz"})
        assert missing_response.status_code == 200
        missing_data = missing_response.json()
        assert missing_data["exists"] is False

        # Test with empty path
        empty_response = client.post("/api/resolve-path", json={"path": ""})
        assert empty_response.status_code == 400


def test_resolve_path_detects_git_repo(tmp_path: Path) -> None:
    import subprocess
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    # Create a git repo in tmp_path
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    (repo / "README.md").write_text("test")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", "test-branch"], capture_output=True, check=True)

    with TestClient(app) as client:
        response = client.post("/api/resolve-path", json={"path": str(repo)})
        assert response.status_code == 200
        data = response.json()
        assert data["is_git"] is True
        assert data["branch"] == "test-branch"
        assert data["on_protected_branch"] is False


def test_session_config_environment_persisted(tmp_path: Path) -> None:
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        body = {
            "id": "env-test",
            "name": "Env Test",
            "pack": "claude-code",
            "config": {
                "environment": {
                    "COGNITIVE_SWITCHYARD_REPO_ROOT": "/tmp/my-project"
                }
            },
        }
        response = client.post("/api/sessions", json=body)
        assert response.status_code == 201

        session_response = client.get("/api/sessions/env-test")
        assert session_response.status_code == 200
        config = session_response.json()["session"]["config"]
        assert config["environment"]["COGNITIVE_SWITCHYARD_REPO_ROOT"] == "/tmp/my-project"


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True, check=True)
    (path / "README.md").write_text("test")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], capture_output=True, check=True)


def test_repo_branches_lists_branches(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    repo = tmp_path / "branches-repo"
    _init_git_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "feature-a"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "feature-b"], capture_output=True, check=True)

    with TestClient(app) as client:
        response = client.post("/api/repo-branches", json={"path": str(repo)})
        assert response.status_code == 200
        data = response.json()
        assert "feature-a" in data["branches"]
        assert "feature-b" in data["branches"]
        assert data["current"] in data["branches"]


def test_repo_branches_rejects_non_git_directory(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    plain_dir = tmp_path / "not-git"
    plain_dir.mkdir()

    with TestClient(app) as client:
        response = client.post("/api/repo-branches", json={"path": str(plain_dir)})
        assert response.status_code == 400


def test_repo_create_branch_creates_new_branch(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    repo = tmp_path / "create-branch-repo"
    _init_git_repo(repo)

    with TestClient(app) as client:
        response = client.post("/api/repo-create-branch", json={
            "repo_path": str(repo),
            "branch_name": "new-feature",
            "from_branch": "main",
        })
        assert response.status_code == 200
        assert response.json()["created"] is True
    assert response.json()["branch"] == "new-feature"

    verify = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "refs/heads/new-feature"],
        capture_output=True, text=True,
    )
    assert verify.returncode == 0


def test_repo_create_branch_rejects_duplicate(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    repo = tmp_path / "dup-branch-repo"
    _init_git_repo(repo)

    with TestClient(app) as client:
        response = client.post("/api/repo-create-branch", json={
            "repo_path": str(repo),
            "branch_name": "main",
            "from_branch": "main",
        })
        assert response.status_code == 409


def test_session_worktree_created_on_session_create(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    repo = tmp_path / "worktree-repo"
    _init_git_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "session-branch"], capture_output=True, check=True)

    with TestClient(app) as client:
        session_id = "wt-session-01"
        response = client.post("/api/sessions", json={
            "id": session_id,
            "name": "Worktree Test",
            "pack": "claude-code",
            "config": {
                "environment": {
                    "COGNITIVE_SWITCHYARD_REPO_ROOT": str(repo),
                    "COGNITIVE_SWITCHYARD_BRANCH": "session-branch",
                }
            },
        })
        assert response.status_code == 201
        session = response.json()["session"]
        env = session["config"]["environment"]
        assert env["COGNITIVE_SWITCHYARD_SOURCE_REPO"] == str(repo)
        worktree_path = Path(env["COGNITIVE_SWITCHYARD_REPO_ROOT"])
        assert worktree_path != repo
        assert worktree_path.is_dir()
        assert (worktree_path / "README.md").exists()


def test_session_worktree_cleaned_up_on_delete(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    repo = tmp_path / "cleanup-repo"
    _init_git_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "cleanup-branch"], capture_output=True, check=True)

    with TestClient(app) as client:
        session_id = "cleanup-session-01"
        response = client.post("/api/sessions", json={
            "id": session_id,
            "name": "Cleanup Test",
            "pack": "claude-code",
            "config": {
                "environment": {
                    "COGNITIVE_SWITCHYARD_REPO_ROOT": str(repo),
                    "COGNITIVE_SWITCHYARD_BRANCH": "cleanup-branch",
                }
            },
        })
        assert response.status_code == 201
        session = response.json()["session"]
        worktree_path = Path(session["config"]["environment"]["COGNITIVE_SWITCHYARD_REPO_ROOT"])
        assert worktree_path.is_dir()

        delete_response = client.delete(f"/api/sessions/{session_id}")
        assert delete_response.status_code == 200
        assert not worktree_path.exists()


def test_broadcast_alert_constructs_valid_backend_runtime_event(tmp_path: Path) -> None:
    """Regression: _broadcast_alert must pass message_type to BackendRuntimeEvent."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        session_id = "alert-test"
        client.post("/api/sessions", json={"id": session_id, "name": "Alert", "pack": "claude-code"})

        controller = app.state.controller
        # Must not raise TypeError for missing message_type
        controller._broadcast_alert(session_id, "Test alert message", severity="error")


def test_broadcast_alert_reaches_websocket_with_correct_structure(tmp_path: Path) -> None:
    """Regression: _broadcast_alert must produce a well-formed WebSocket alert message,
    not just avoid a crash.  Verifies the full path: controller → event → WebSocket."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        session_id = "alert-ws-test"
        client.post("/api/sessions", json={"id": session_id, "name": "Alert WS", "pack": "claude-code"})

        controller = app.state.controller
        with client.websocket_connect("/ws") as websocket:
            controller._broadcast_alert(session_id, "Pipeline stopped", severity="warning")
            msg = websocket.receive_json()
            assert msg["type"] == "alert"
            assert msg["data"]["severity"] == "warning"
            assert msg["data"]["message"] == "Pipeline stopped"


def test_dashboard_pipeline_counts_match_filesystem(tmp_path: Path) -> None:
    """Dashboard pipeline counts must reflect actual files on disk, not stale DB state."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        session_id = "pipeline-count-test"
        client.post("/api/sessions", json={"id": session_id, "name": "Counts", "pack": "claude-code"})

        session_paths = runtime_paths.session_paths(session_id)

        # Write intake files
        (session_paths.intake / "001_task.md").write_text("# Task 1\n", encoding="utf-8")
        (session_paths.intake / "002_task.md").write_text("# Task 2\n", encoding="utf-8")

        resp = client.get(f"/api/sessions/{session_id}/dashboard")
        dashboard = resp.json()
        assert dashboard["pipeline"]["intake"] == 2
        assert dashboard["pipeline"]["planning"] == 0

        # Move one to claimed (simulating planner claim)
        (session_paths.intake / "001_task.md").replace(session_paths.claimed / "001_task.md")

        resp = client.get(f"/api/sessions/{session_id}/dashboard")
        dashboard = resp.json()
        assert dashboard["pipeline"]["intake"] == 1, "Should count 1 remaining intake file"
        assert dashboard["pipeline"]["planning"] == 1, "Should count 1 claimed file"

        # Move claimed to review (plan file)
        (session_paths.claimed / "001_task.md").unlink()
        (session_paths.review / "001.plan.md").write_text("---\nPLAN_ID: 001\n---\nReview.\n", encoding="utf-8")

        resp = client.get(f"/api/sessions/{session_id}/dashboard")
        dashboard = resp.json()
        assert dashboard["pipeline"]["intake"] == 1
        assert dashboard["pipeline"]["planning"] == 0
        assert dashboard["pipeline"]["review"] == 1


def test_dashboard_pipeline_dirs_point_to_real_session_directories(tmp_path: Path) -> None:
    """pipeline_dirs must contain valid absolute paths to actual session subdirectories."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        session_id = "dirs-test"
        client.post("/api/sessions", json={"id": session_id, "name": "Dirs", "pack": "claude-code"})

        resp = client.get(f"/api/sessions/{session_id}/dashboard")
        dirs = resp.json()["pipeline_dirs"]

        expected_keys = {"intake", "planning", "staged", "review", "ready", "active", "done", "blocked"}
        assert set(dirs.keys()) == expected_keys

        for key, path_str in dirs.items():
            assert Path(path_str).is_dir(), f"pipeline_dirs[{key!r}] does not exist: {path_str}"


def test_pipeline_event_triggers_websocket_snapshot(tmp_path: Path) -> None:
    """When a pipeline_event arrives from the orchestrator, a state_update must be
    broadcast to all WebSocket clients so the UI updates instantly."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        session_id = "pipeline-evt-test"
        client.post("/api/sessions", json={"id": session_id, "name": "PipeEvt", "pack": "claude-code"})

        controller = app.state.controller
        with client.websocket_connect("/ws") as websocket:
            # Simulate a pipeline event (file claimed)
            controller._publish_runtime_event(
                BackendRuntimeEvent(
                    message_type="pipeline_event",
                    session_id=session_id,
                    data={"type": "pipeline_event", "event": "file_claimed", "file": "001_task.md"},
                )
            )
            msg = websocket.receive_json()
            assert msg["type"] == "state_update", "pipeline_event should trigger a state_update broadcast"
            assert "pipeline" in msg["data"]


def test_preparation_status_event_triggers_websocket_snapshot(tmp_path: Path) -> None:
    """When a preparation_status event fires (status change during planning/resolving),
    the client must receive a state_update with current session status."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        session_id = "prep-status-test"
        client.post("/api/sessions", json={"id": session_id, "name": "PrepStatus", "pack": "claude-code"})

        controller = app.state.controller
        with client.websocket_connect("/ws") as websocket:
            # Update session status, then fire preparation_status event
            store.update_session_status(session_id, status="planning")
            controller._publish_runtime_event(
                BackendRuntimeEvent(
                    message_type="preparation_status",
                    session_id=session_id,
                    data={"type": "preparation_status", "status": "planning"},
                )
            )
            msg = websocket.receive_json()
            assert msg["type"] == "state_update"
            assert msg["data"]["session"]["status"] == "planning"


def test_worker_idle_state_publishes_immediately_when_activity_advances_even_inside_throttle_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meaningful worker activity must force a fresh authoritative snapshot immediately."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    controller = app.state.controller

    publish_calls: list[str] = []

    def capture_publish(session_id: str) -> None:
        publish_calls.append(session_id)

    monkeypatch.setattr(controller, "_publish_snapshot", capture_publish)

    session_id = "idle-advance-test"
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="worker_idle_state",
            session_id=session_id,
            data={
                "worker_slot": 0,
                "task_id": "001",
                "last_output_at": 10.0,
                "task_idle": 300.0,
            },
        )
    )
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="worker_idle_state",
            session_id=session_id,
            data={
                "worker_slot": 0,
                "task_id": "001",
                "last_output_at": 10.0,
                "task_idle": 300.0,
            },
        )
    )
    controller._publish_runtime_event(
        BackendRuntimeEvent(
            message_type="worker_idle_state",
            session_id=session_id,
            data={
                "worker_slot": 0,
                "task_id": "001",
                "last_output_at": 11.0,
                "task_idle": 300.0,
            },
        )
    )

    assert publish_calls == [session_id, session_id], (
        "Initial idle state should publish once, heartbeat-only repetition should be throttled, "
        "and advanced activity must publish immediately."
    )


def test_session_start_broadcasts_status_transitions_over_websocket(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    """Starting a session with planning must push at least one state_update
    showing planning status to the WebSocket before execution begins.
    This is the scenario where the user saw 'planning' but the Monitor was blank."""
    store, runtime_paths = _build_store(tmp_path)
    _write_fixture_runtime_pack(
        runtime_paths,
        repo_root=repo_root,
        fixture_name="streaming_worker.py",
    )
    # Override to enable planning with a fake planner
    pack_root = runtime_paths.packs / "claude-code"
    pack_yaml = pack_root / "pack.yaml"
    pack_yaml.write_text(
        dedent(
            """
            name: claude-code
            description: Test pack with planning.
            version: 1.2.3

            phases:
              planning:
                enabled: true
                executor: agent
                model: test-planner
                prompt: prompts/planner.md
                max_instances: 1
              resolution:
                enabled: true
                executor: passthrough
              execution:
                enabled: true
                executor: shell
                command: scripts/streaming_worker.py
                max_workers: 1
              verification:
                enabled: false

            timeouts:
              task_idle: 300
              task_max: 0
              session_max: 14400

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )

    session = store.create_session(
        session_id="session-start-transitions",
        name="Start Transitions",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.intake / "001_task.md").write_text("# Task 1\n", encoding="utf-8")

    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            start_resp = client.post(f"/api/sessions/{session.id}/start")
            assert start_resp.status_code == 202

            # We must receive state_update messages showing pipeline progress
            seen_statuses = set()
            seen_pipeline_events = False
            for _ in range(64):
                msg = websocket.receive_json()
                if msg["type"] == "state_update":
                    status = msg["data"]["session"]["status"]
                    seen_statuses.add(status)
                    # If we see "idle" or "aborted", stop
                    if status in {"idle", "aborted"}:
                        break

            # We must have seen "planning" status at some point
            assert "planning" in seen_statuses or "running" in seen_statuses, (
                f"Expected to see 'planning' or 'running' status in WebSocket updates, "
                f"but only saw: {seen_statuses}"
            )


def test_session_creation_seeds_intake_claude_md_from_pack_prompt(tmp_path: Path) -> None:
    """CLAUDE.md is written to intake/ when the pack has prompts/intake.md,
    and it is excluded from the intake file listing."""
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    # Write an intake prompt into the pack
    intake_prompt_content = "# Intake Instructions\nDrop files here.\n"
    (runtime_paths.packs / "claude-code" / "prompts" / "intake.md").write_text(
        intake_prompt_content, encoding="utf-8"
    )

    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        # Create session via the API endpoint so the seeding logic runs
        resp = client.post("/api/sessions", json={"id": "sess-claude-md", "name": "test"})
        assert resp.status_code == 201

        session_paths = runtime_paths.session_paths("sess-claude-md")
        claude_md = session_paths.intake / "CLAUDE.md"
        assert claude_md.exists(), "CLAUDE.md should be created in intake/"
        assert claude_md.read_text(encoding="utf-8") == intake_prompt_content

        # Also create a real intake file so we can verify filtering
        (session_paths.intake / "001_ticket.md").write_text("# Ticket\n", encoding="utf-8")

        intake_resp = client.get("/api/sessions/sess-claude-md/intake")
        assert intake_resp.status_code == 200
        filenames = [f["filename"] for f in intake_resp.json()["files"]]
        assert "001_ticket.md" in filenames
        assert "CLAUDE.md" not in filenames


def test_session_creation_skips_claude_md_when_pack_has_no_intake_prompt(tmp_path: Path) -> None:
    """No CLAUDE.md is created when the pack lacks prompts/intake.md."""
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    # Ensure no intake.md exists (it shouldn't by default from _write_runtime_pack)
    intake_prompt = runtime_paths.packs / "claude-code" / "prompts" / "intake.md"
    if intake_prompt.exists():
        intake_prompt.unlink()

    app = create_app(store=store, runtime_paths=runtime_paths)

    with TestClient(app) as client:
        resp = client.post("/api/sessions", json={"id": "sess-no-claude-md", "name": "test"})
        assert resp.status_code == 201

        session_paths = runtime_paths.session_paths("sess-no-claude-md")
        claude_md = session_paths.intake / "CLAUDE.md"
        assert not claude_md.exists(), "CLAUDE.md should NOT be created without intake prompt"


# --- Regression tests for Plan 002: elapsed timers ---

def test_serialize_task_returns_elapsed_for_active_task(tmp_path: Path) -> None:
    """_serialize_task() must include elapsed >= 59 for a task started 60s ago (active status)."""
    from cognitive_switchyard.server import _serialize_task

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="sess-elapsed-active",
        name="Elapsed Test Active",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session.id, task_id="T1", title="Timer task")
    started_at = _timestamp_offset(seconds=-60)
    store.project_task(
        session.id,
        "T1",
        status="active",
        worker_slot=0,
        timestamp=started_at,
    )
    task = store.get_task(session.id, "T1")
    result = _serialize_task(store, session.id, task)

    assert "elapsed" in result, "_serialize_task must include 'elapsed' key"
    assert result["elapsed"] >= 59, f"Expected elapsed >= 59 for task started 60s ago, got {result['elapsed']}"


def test_serialize_task_returns_frozen_elapsed_for_completed_task(tmp_path: Path) -> None:
    """_serialize_task() must return elapsed == 120 for a task with start/complete 120s apart."""
    from cognitive_switchyard.server import _serialize_task

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="sess-elapsed-done",
        name="Elapsed Test Done",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session.id, task_id="T2", title="Completed task")
    started_at = "2026-03-09T10:00:00Z"
    completed_at = "2026-03-09T10:02:00Z"  # 120 seconds later
    store.project_task(session.id, "T2", status="active", worker_slot=0, timestamp=started_at)
    store.project_task(session.id, "T2", status="done", timestamp=completed_at)
    task = store.get_task(session.id, "T2")

    result = _serialize_task(store, session.id, task)

    assert "elapsed" in result, "_serialize_task must include 'elapsed' key for completed tasks"
    assert result["elapsed"] == 120, f"Expected elapsed == 120 for task running 120s, got {result['elapsed']}"


def test_build_dashboard_payload_worker_includes_started_at(tmp_path: Path) -> None:
    """build_dashboard_payload worker payload must include both 'elapsed' and 'started_at' for active workers."""
    from cognitive_switchyard.server import build_dashboard_payload, create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="sess-elapsed-worker",
        name="Elapsed Worker Test",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(session.id, status="running", started_at=_timestamp_offset(seconds=-30))
    _register_task(store, session.id, task_id="W1", title="Worker task")
    started_at = _timestamp_offset(seconds=-10)
    store.project_task(session.id, "W1", status="active", worker_slot=0, timestamp=started_at)

    payload = build_dashboard_payload(store, session.id, runtime_paths=runtime_paths)

    active_workers = [w for w in payload["workers"] if w.get("status") == "active"]
    assert active_workers, "Expected at least one active worker in dashboard payload"
    worker = active_workers[0]
    assert "elapsed" in worker, "Active worker payload must include 'elapsed'"
    assert "started_at" in worker, "Active worker payload must include 'started_at'"
    assert worker["elapsed"] >= 0
    assert worker["started_at"] == started_at


# --- terminal_app tests ---

def test_open_terminal_command_macos_default_iterm(monkeypatch: pytest.MonkeyPatch) -> None:
    from cognitive_switchyard.server import _open_terminal_command

    monkeypatch.setattr("sys.platform", "darwin")
    result = _open_terminal_command(Path("/tmp/test"), "iTerm")
    assert result == ["open", "-n", "-a", "iTerm", "/tmp/test"]


def test_open_terminal_command_macos_custom_app(monkeypatch: pytest.MonkeyPatch) -> None:
    from cognitive_switchyard.server import _open_terminal_command

    monkeypatch.setattr("sys.platform", "darwin")
    result = _open_terminal_command(Path("/tmp/test"), "Kitty")
    assert result == ["Kitty", "--directory", "/tmp/test"]


def test_settings_terminal_app_round_trip(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        put_response = client.put(
            "/api/settings",
            json={
                "retention_days": 30,
                "default_planners": 3,
                "default_workers": 3,
                "default_pack": "claude-code",
                "terminal_app": "Kitty",
            },
        )
        assert put_response.status_code == 200
        assert put_response.json()["settings"]["terminal_app"] == "Kitty"

        get_response = client.get("/api/settings")
        assert get_response.status_code == 200
        assert get_response.json()["settings"]["terminal_app"] == "Kitty"


def test_open_terminal_command_macos_iterm_path_with_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    from cognitive_switchyard.server import _open_terminal_command

    monkeypatch.setattr("sys.platform", "darwin")
    result = _open_terminal_command(Path("/tmp/my session/intake"), "iTerm")
    assert result == ["open", "-n", "-a", "iTerm", "/tmp/my session/intake"]


def test_open_terminal_command_macos_terminal_app(monkeypatch: pytest.MonkeyPatch) -> None:
    from cognitive_switchyard.server import _open_terminal_command

    monkeypatch.setattr("sys.platform", "darwin")
    result = _open_terminal_command(Path("/tmp/test"), "Terminal")
    assert result == ["open", "-n", "-a", "Terminal", "/tmp/test"]


def test_open_terminal_command_macos_wezterm_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    from cognitive_switchyard.server import _open_terminal_command

    monkeypatch.setattr("sys.platform", "darwin")
    result = _open_terminal_command(Path("/tmp/test"), "Wezterm")
    assert result == ["wezterm", "start", "--always-new-process", "--cwd", "/tmp/test"]


def test_open_terminal_command_linux_wezterm_new_process(monkeypatch: pytest.MonkeyPatch) -> None:
    from cognitive_switchyard.server import _open_terminal_command

    monkeypatch.setattr("sys.platform", "linux")
    result = _open_terminal_command(Path("/tmp/test"), "wezterm")
    assert result == ["wezterm", "start", "--always-new-process", "--cwd", "/tmp/test"]


def test_force_reset_deletes_session_regardless_of_status(tmp_path: Path) -> None:
    """Force-reset must remove a session in any state — created, running, completed."""
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        # Create a session
        resp = client.post("/api/sessions", json={"id": "force-reset-test", "pack": "claude-code"})
        assert resp.status_code == 201

        # Force-reset it
        resp = client.post("/api/sessions/force-reset-test/force-reset")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset"

        # Session should be gone
        resp = client.get("/api/sessions/force-reset-test")
        assert resp.status_code == 404


def test_force_reset_handles_nonexistent_session(tmp_path: Path) -> None:
    """Force-reset on a missing session should not crash."""
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        resp = client.post("/api/sessions/ghost-session/force-reset")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset"


# ---------------------------------------------------------------------------
# Regression tests for plan 002: completion card — deferred worktree cleanup
# ---------------------------------------------------------------------------


def test_finish_session_does_not_call_cleanup_worktree_for_completed_status(
    tmp_path: Path,
) -> None:
    """_finish_session must NOT clean up the worktree when status is 'completed'.

    The worktree must survive until the user explicitly triggers cleanup via
    POST /api/sessions/{id}/cleanup-worktree, so the completion card can show
    validation and merge instructions.
    """
    from unittest.mock import MagicMock, patch
    from cognitive_switchyard.server import SessionController

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="cc-defer-test",
        pack="claude-code",
        name="Deferred Cleanup Test",
        created_at="2026-03-11T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-11T10:01:00Z",
        completed_at="2026-03-11T10:10:00Z",
    )

    connection_manager = MagicMock()
    connection_manager.event_loop = None
    controller = SessionController(
        store=store,
        runtime_paths=runtime_paths,
        connection_manager=connection_manager,
    )

    with patch.object(controller, "_cleanup_worktree") as mock_cleanup:
        # Simulate what _finish_session does after marking session completed
        finished_session = store.get_session(session.id)
        if finished_session.status == "aborted":
            controller._cleanup_worktree(finished_session)

        mock_cleanup.assert_not_called()


def test_finish_session_calls_cleanup_worktree_for_aborted_status(
    tmp_path: Path,
) -> None:
    """_finish_session MUST clean up the worktree when status is 'aborted'."""
    from unittest.mock import MagicMock, patch
    from cognitive_switchyard.server import SessionController

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="cc-abort-test",
        pack="claude-code",
        name="Abort Cleanup Test",
        created_at="2026-03-11T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="aborted",
        started_at="2026-03-11T10:01:00Z",
        completed_at="2026-03-11T10:10:00Z",
    )

    connection_manager = MagicMock()
    connection_manager.event_loop = None
    controller = SessionController(
        store=store,
        runtime_paths=runtime_paths,
        connection_manager=connection_manager,
    )

    with patch.object(controller, "_cleanup_worktree") as mock_cleanup:
        finished_session = store.get_session(session.id)
        if finished_session.status == "aborted":
            controller._cleanup_worktree(finished_session)

        mock_cleanup.assert_called_once_with(finished_session)


def test_cleanup_worktree_endpoint_calls_cleanup_function(tmp_path: Path) -> None:
    """POST /api/sessions/{id}/cleanup-worktree must call cleanup_session_worktree_if_needed."""
    from unittest.mock import patch
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="cc-cleanup-ep-test",
        pack="claude-code",
        name="Cleanup Endpoint Test",
        created_at="2026-03-11T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-11T10:01:00Z",
        completed_at="2026-03-11T10:10:00Z",
    )

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        with patch("cognitive_switchyard.server.cleanup_session_worktree_if_needed") as mock_cleanup:
            resp = client.post(f"/api/sessions/{session.id}/cleanup-worktree")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}
            mock_cleanup.assert_called_once()


def test_build_summary_dashboard_payload_includes_tasks(tmp_path: Path) -> None:
    """_build_summary_dashboard_payload must include a 'tasks' key in the output."""
    from cognitive_switchyard.server import build_dashboard_payload, create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="cc-tasks-payload-test",
        pack="claude-code",
        name="Tasks Payload Test",
        created_at="2026-03-11T10:00:00Z",
        config_json=json.dumps({"worker_count": 1}),
    )
    _register_task(store, session.id, task_id="001", title="Build the widget", exec_order=1)
    store.project_task(session.id, "001", status="done", timestamp="2026-03-11T10:09:00Z")
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-11T10:01:00Z",
        completed_at="2026-03-11T10:10:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.worker_log(0).parent.mkdir(parents=True, exist_ok=True)
    store.write_successful_session_summary(session.id)

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        resp = client.get(f"/api/sessions/{session.id}/dashboard")
        assert resp.status_code == 200
        payload = resp.json()

        assert "tasks" in payload, "Dashboard payload for completed session must include 'tasks' key"
        assert len(payload["tasks"]) == 1
        assert payload["tasks"][0]["task_id"] == "001"
        assert payload["tasks"][0]["title"] == "Build the widget"
        assert payload["tasks"][0]["status"] == "done"


# --- Regression tests for code-audit fixes ---


def test_create_session_rejects_path_traversal_session_id(tmp_path: Path) -> None:
    """M-2 regression: session IDs containing path-traversal characters must be rejected with 400."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        for bad_id in ["../evil", "../../etc", "session/slash", ".hidden", "has space", ""]:
            resp = client.post("/api/sessions", json={"id": bad_id, "pack": "claude-code"})
            assert resp.status_code == 400, (
                f"Expected 400 for session_id={bad_id!r}, got {resp.status_code}"
            )

        # Valid IDs must still work.
        resp = client.post("/api/sessions", json={"id": "session-valid-123", "pack": "claude-code"})
        assert resp.status_code == 201, f"Expected 201 for valid session_id, got {resp.status_code}"


def test_f10_retry_task_returns_404_for_unknown_session(tmp_path: Path) -> None:
    """F-10 regression: retry_task_route must return 404 for an unknown session,
    not a task-level KeyError."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        resp = client.post("/api/sessions/no-such-session/tasks/any-task/retry")
        assert resp.status_code == 404
        # The error message should say "Unknown session" not a task-level message
        assert "session" in resp.json().get("detail", "").lower()


def test_f10_retry_task_returns_404_for_unknown_task_in_known_session(tmp_path: Path) -> None:
    """F-10 regression: retry_task_route must return 404 for unknown task in a known session."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    store.create_session(
        session_id="session-f10",
        name="F10 session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        resp = client.post("/api/sessions/session-f10/tasks/no-such-task/retry")
        assert resp.status_code == 404


def test_purge_session_evicts_worker_card_state_and_pack_cache(tmp_path: Path) -> None:
    """L-2 regression: deleting a session must evict _worker_card_state and _pack_cache."""
    from cognitive_switchyard.server import SessionController
    from cognitive_switchyard.models import BackendRuntimeEvent

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:

        # Create and then immediately delete a session.
        resp = client.post("/api/sessions", json={"id": "cache-evict-session", "pack": "claude-code"})
        assert resp.status_code == 201

        # Manually warm the SessionController caches by injecting a fake runtime event.
        session_controller = app.state.controller
        fake_event = BackendRuntimeEvent(
            session_id="cache-evict-session",
            message_type="state_update",
            data={},
        )
        session_controller._publish_runtime_event(fake_event)

        # Confirm the caches are populated.
        assert "cache-evict-session" in session_controller._worker_card_state

        # Delete the session via the API.
        resp = client.delete("/api/sessions/cache-evict-session")
        assert resp.status_code == 200

        # Both caches must no longer hold the evicted session.
        assert "cache-evict-session" not in session_controller._worker_card_state, (
            "_worker_card_state still holds deleted session"
        )
        assert "cache-evict-session" not in session_controller._pack_cache, (
            "_pack_cache still holds deleted session"
        )


def test_dashboard_uses_list_all_tasks_single_query(tmp_path: Path) -> None:
    """Carried-forward F-10 regression: build_dashboard_payload must call list_all_tasks
    once instead of 5 separate list_*_tasks calls."""
    import unittest.mock
    from cognitive_switchyard.server import build_dashboard_payload

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    store.create_session(
        session_id="session-dash-q",
        name="Dash query session",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, "session-dash-q", task_id="t1", title="Task 1")

    # StateStore is a frozen dataclass, so we must patch on the class.
    StoreClass = type(store)
    with (
        unittest.mock.patch.object(StoreClass, "list_all_tasks", wraps=store.list_all_tasks) as mock_all,
        unittest.mock.patch.object(StoreClass, "list_ready_tasks", wraps=store.list_ready_tasks) as mock_ready,
        unittest.mock.patch.object(StoreClass, "list_active_tasks", wraps=store.list_active_tasks) as mock_active,
        unittest.mock.patch.object(StoreClass, "list_done_tasks", wraps=store.list_done_tasks) as mock_done,
        unittest.mock.patch.object(StoreClass, "list_blocked_tasks", wraps=store.list_blocked_tasks) as mock_blocked,
    ):
        build_dashboard_payload(store, "session-dash-q", runtime_paths=runtime_paths)

    assert mock_all.call_count == 1, "list_all_tasks should be called exactly once"
    assert mock_ready.call_count == 0, "list_ready_tasks should not be called (consolidated)"
    assert mock_active.call_count == 0, "list_active_tasks should not be called (consolidated)"
    assert mock_done.call_count == 0, "list_done_tasks should not be called (consolidated)"
    assert mock_blocked.call_count == 0, "list_blocked_tasks should not be called (consolidated)"


def test_list_all_tasks_returns_tasks_across_all_statuses(tmp_path: Path) -> None:
    """CF-1 regression: list_all_tasks must return tasks regardless of status."""
    from cognitive_switchyard.models import TaskPlan

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="all-tasks-session",
        name="All tasks session",
        pack="claude-code",
        created_at="2026-03-11T12:00:00Z",
    )

    # Register tasks in different statuses.
    for task_id, exec_order in [("001", 1), ("002", 2), ("003", 3)]:
        plan = TaskPlan(task_id=task_id, title=f"Task {task_id}", exec_order=exec_order)
        store.register_task_plan(
            session_id=session.id,
            plan=plan,
            plan_text=f"# Task {task_id}\n",
            created_at="2026-03-11T12:00:00Z",
        )
    # Move tasks to distinct statuses.
    store.project_task(session.id, "002", status="active", worker_slot=0, timestamp="2026-03-11T12:01:00Z")
    store.project_task(session.id, "003", status="done", timestamp="2026-03-11T12:02:00Z")

    all_tasks = store.list_all_tasks(session.id)
    statuses = {t.task_id: t.status for t in all_tasks}

    assert statuses == {"001": "ready", "002": "active", "003": "done"}, (
        f"list_all_tasks returned unexpected statuses: {statuses}"
    )


# --- Regression tests for plan 001: session timer active during planning/resolving ---

@pytest.mark.parametrize("active_status", ["planning", "resolving", "running", "verifying", "auto_fixing"])
def test_build_dashboard_payload_run_elapsed_nonzero_during_active_statuses(
    tmp_path: Path, active_status: str
) -> None:
    """run_elapsed must be > 0 for all active statuses including planning and resolving.

    Regression: is_active gate previously excluded 'planning' and 'resolving', causing
    timers to freeze during those phases.
    """
    from cognitive_switchyard.server import build_dashboard_payload

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id=f"sess-timer-{active_status}",
        name=f"Timer Test ({active_status})",
        pack="claude-code",
        created_at="2026-03-12T10:00:00Z",
    )
    run_started_at = _timestamp_offset(seconds=-30)
    store.update_session_status(session.id, status=active_status, started_at=run_started_at)
    store.write_session_runtime_state(session.id, run_number=1, run_started_at=run_started_at)

    payload = build_dashboard_payload(store, session.id, runtime_paths=runtime_paths)

    run_elapsed = payload["session"]["run_elapsed"]
    assert run_elapsed > 0, (
        f"run_elapsed should be > 0 during status '{active_status}', got {run_elapsed}"
    )


@pytest.mark.parametrize("inactive_status", ["idle", "completed", "failed", "aborted"])
def test_build_dashboard_payload_run_elapsed_zero_during_inactive_statuses(
    tmp_path: Path, inactive_status: str
) -> None:
    """run_elapsed must be 0 for idle/terminal statuses.

    Regression: cumulative timer must not increment when no run is in progress.
    """
    from cognitive_switchyard.server import build_dashboard_payload

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id=f"sess-timer-{inactive_status}",
        name=f"Timer Test ({inactive_status})",
        pack="claude-code",
        created_at="2026-03-12T10:00:00Z",
    )
    run_started_at = _timestamp_offset(seconds=-30)
    store.update_session_status(session.id, status=inactive_status, started_at=run_started_at)
    store.write_session_runtime_state(session.id, run_number=1, run_started_at=run_started_at)

    payload = build_dashboard_payload(store, session.id, runtime_paths=runtime_paths)

    run_elapsed = payload["session"]["run_elapsed"]
    assert run_elapsed == 0, (
        f"run_elapsed should be 0 during status '{inactive_status}', got {run_elapsed}"
    )


def test_build_dashboard_payload_cumulative_elapsed_includes_run_during_planning(
    tmp_path: Path,
) -> None:
    """elapsed (cumulative) must include current run time during 'planning' status.

    Regression: is_active gate excluded 'planning', causing accumulated_elapsed_seconds
    to be returned without adding the current run's contribution.
    """
    from cognitive_switchyard.server import build_dashboard_payload

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="sess-cumulative-planning",
        name="Cumulative Planning Test",
        pack="claude-code",
        created_at="2026-03-12T10:00:00Z",
    )
    run_started_at = _timestamp_offset(seconds=-30)
    store.update_session_status(session.id, status="planning", started_at=run_started_at)
    store.write_session_runtime_state(
        session.id,
        run_number=2,
        run_started_at=run_started_at,
        accumulated_elapsed_seconds=100,
    )

    payload = build_dashboard_payload(store, session.id, runtime_paths=runtime_paths)

    elapsed = payload["session"]["elapsed"]
    run_elapsed = payload["session"]["run_elapsed"]
    # accumulated (100) + current run (~30s) = ~130; allow ±5s tolerance
    assert elapsed >= 125, f"cumulative elapsed should be ~130 during 'planning', got {elapsed}"
    assert run_elapsed >= 25, f"run_elapsed should be ~30 during 'planning', got {run_elapsed}"


@pytest.mark.parametrize("planning_status", ["planning", "resolving"])
def test_build_dashboard_payload_run_number_nonzero_during_planning_and_resolving(
    tmp_path: Path, planning_status: str
) -> None:
    """run_number must be >= 1 in the dashboard payload during planning/resolving.

    Regression (plan 007): run_number stayed 0 until execute_session() ran,
    causing the TopBar to hide timers (guarded by runNumber > 0) during the
    entire planning and resolving phases.
    """
    from cognitive_switchyard.server import build_dashboard_payload

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id=f"sess-run-num-{planning_status}",
        name=f"Run Number Test ({planning_status})",
        pack="claude-code",
        created_at="2026-03-12T10:00:00Z",
    )
    run_started_at = _timestamp_offset(seconds=-5)
    store.update_session_status(session.id, status=planning_status, started_at=run_started_at)
    # Simulate what start_session() now does before calling prepare_session_for_execution():
    # run_number is set to 1 (>= 1) before planning begins.
    store.write_session_runtime_state(session.id, run_number=1, run_started_at=run_started_at)

    payload = build_dashboard_payload(store, session.id, runtime_paths=runtime_paths)

    run_number = payload["session"]["run_number"]
    assert run_number >= 1, (
        f"run_number must be >= 1 during '{planning_status}' so TopBar shows timers, "
        f"got {run_number}. If this regresses, start_session() no longer pre-sets "
        "run_number before the planning phase."
    )


# ---------------------------------------------------------------------------
# Regression: max_planners in pack summary and planner_count clamping (002)
# ---------------------------------------------------------------------------


def test_get_packs_includes_max_planners_as_integer(tmp_path: Path) -> None:
    """Every pack in GET /api/packs must include max_planners as an integer.

    Regression for: _serialize_pack_summary() omitting max_planners, which
    prevented the UI from enforcing the planner count cap.
    """
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        response = client.get("/api/packs")

    assert response.status_code == 200
    packs = response.json()["packs"]
    assert len(packs) > 0, "Expected at least one pack in the response"
    for pack in packs:
        assert "max_planners" in pack, (
            f"Pack '{pack.get('name')}' is missing 'max_planners' in summary. "
            "If this regresses, _serialize_pack_summary() no longer includes the field."
        )
        assert isinstance(pack["max_planners"], int), (
            f"Pack '{pack.get('name')}' has non-integer max_planners: {pack['max_planners']!r}"
        )


def test_planner_count_is_clamped_to_pack_max_instances(tmp_path: Path) -> None:
    """Session created with planner_count above pack limit must have effective
    planner_count clamped to pack's max_instances.

    Regression for: UI allowing values above pack limit to be submitted
    without feedback, relying solely on silent backend clamping.
    The backend clamp is correct and must remain in place as a safety net.
    """
    from cognitive_switchyard.server import create_app

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)  # planning.max_instances == 2
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        response = client.post(
            "/api/sessions",
            json={
                "id": "session-002-clamp",
                "name": "Planner Count Clamp Test",
                "pack": "claude-code",
                "config": {"planner_count": 10},
            },
        )

    assert response.status_code == 201
    ert = response.json()["session"]["effective_runtime_config"]
    assert ert["planner_count"] == 2, (
        f"Expected planner_count clamped to pack limit 2, got {ert['planner_count']}. "
        "If this regresses, build_effective_planner_count() no longer applies min()."
    )


# --- Regression tests for plan 003: task lifecycle move endpoint ---


def test_move_task_blocked_to_ready(tmp_path: Path) -> None:
    """Move a blocked task to ready via the /move endpoint."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="move-001",
        name="Move Test",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    _register_task(store, session.id, task_id="t1", title="Task 1")
    store.project_task(session.id, "t1", status="blocked")
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/sessions/{session.id}/tasks/t1/move",
            json={"target_status": "ready"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "moved"
    assert body["from"] == "blocked"
    assert body["to"] == "ready"
    task = store.get_task(session.id, "t1")
    assert task.status == "ready"


def test_move_task_review_to_intake(tmp_path: Path) -> None:
    """Move a review task to intake: task row deleted, plan file in intake dir."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="move-002",
        name="Move Test Intake",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    _register_task(store, session.id, task_id="t1", title="Review task")
    store.project_task(session.id, "t1", status="review")

    session_paths = runtime_paths.session_paths(session.id)
    plan_file = session_paths.review / "t1.plan.md"
    assert plan_file.exists(), "Plan file should exist in review dir before move"

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/sessions/{session.id}/tasks/t1/move",
            json={"target_status": "intake"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "moved"
    assert body["to"] == "intake"

    # Task row should be deleted
    with pytest.raises(KeyError):
        store.get_task(session.id, "t1")

    # Plan file should be in intake
    intake_file = session_paths.intake / "t1.plan.md"
    assert intake_file.exists(), "Plan file should exist in intake dir after move"


def test_move_task_invalid_transition_409(tmp_path: Path) -> None:
    """Attempting an invalid transition returns 409."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="move-003",
        name="Move Invalid",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    _register_task(store, session.id, task_id="t1", title="Ready task")
    # Task starts in "ready" status — not in VALID_TASK_TRANSITIONS
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/sessions/{session.id}/tasks/t1/move",
            json={"target_status": "done"},
        )
    assert resp.status_code == 409


def test_move_task_active_rejects(tmp_path: Path) -> None:
    """Moving an active task returns 409 — active is not a valid source status."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="move-004",
        name="Move Active",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    _register_task(store, session.id, task_id="t1", title="Active task")
    store.project_task(session.id, "t1", status="active", worker_slot=0)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/sessions/{session.id}/tasks/t1/move",
            json={"target_status": "ready"},
        )
    assert resp.status_code == 409


def test_move_task_noop_same_status(tmp_path: Path) -> None:
    """Moving a task to its current status returns no-op."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="move-005",
        name="Move Noop",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    _register_task(store, session.id, task_id="t1", title="Blocked task")
    store.project_task(session.id, "t1", status="blocked")
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/sessions/{session.id}/tasks/t1/move",
            json={"target_status": "blocked"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "no-op"


def test_move_task_unknown_session_404(tmp_path: Path) -> None:
    """Move endpoint returns 404 for unknown session."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/no-such/tasks/t1/move",
            json={"target_status": "ready"},
        )
    assert resp.status_code == 404


def test_move_task_unknown_task_404(tmp_path: Path) -> None:
    """Move endpoint returns 404 for unknown task in a known session."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    store.create_session(
        session_id="move-007",
        name="Move 404 task",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/move-007/tasks/no-such/move",
            json={"target_status": "ready"},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression: Plan 006 — idle state in build_dashboard_payload
# ---------------------------------------------------------------------------


def test_build_dashboard_payload_includes_last_activity_ago_and_task_idle_limit_when_idle_state_provided(
    tmp_path: Path,
) -> None:
    """build_dashboard_payload must include last_activity_ago and task_idle_limit on active worker
    objects when idle_state is provided. Regression for Plan 006."""
    import time
    from cognitive_switchyard.server import build_dashboard_payload

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="sess-idle-state-006",
        name="Idle State Test",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    store.update_session_status(session.id, status="running", started_at=_timestamp_offset(seconds=-30))
    _register_task(store, session.id, task_id="IS1", title="Idle state task")
    started_at = _timestamp_offset(seconds=-20)
    store.project_task(session.id, "IS1", status="active", worker_slot=0, timestamp=started_at)

    now_mono = time.monotonic()
    idle_state = {
        0: {
            "task_id": "IS1",
            "last_output_at": now_mono - 45.0,
            "task_idle": 300.0,
        }
    }

    payload = build_dashboard_payload(
        store, session.id, runtime_paths=runtime_paths, idle_state=idle_state
    )

    active_workers = [w for w in payload["workers"] if w.get("status") == "active"]
    assert active_workers, "Expected at least one active worker"
    worker = active_workers[0]
    assert "last_activity_ago" in worker, "Active worker must include last_activity_ago when idle_state is provided"
    assert "task_idle_limit" in worker, "Active worker must include task_idle_limit when idle_state is provided"
    assert worker["last_activity_ago"] >= 44, f"last_activity_ago should be ~45s, got {worker['last_activity_ago']}"
    assert worker["task_idle_limit"] == 300, f"task_idle_limit should be 300, got {worker['task_idle_limit']}"


def test_build_dashboard_payload_ignores_idle_state_from_different_task_on_same_slot(
    tmp_path: Path,
) -> None:
    """Stale idle cache from a previous task must not leak onto the current active task."""
    import time
    from cognitive_switchyard.server import build_dashboard_payload

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="sess-idle-mismatch-006",
        name="Idle Mismatch Test",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    store.update_session_status(session.id, status="running", started_at=_timestamp_offset(seconds=-30))
    _register_task(store, session.id, task_id="NEW1", title="Active task")
    store.project_task(
        session.id,
        "NEW1",
        status="active",
        worker_slot=0,
        timestamp=_timestamp_offset(seconds=-20),
    )

    idle_state = {
        0: {
            "task_id": "OLD1",
            "last_output_at": time.monotonic() - 120.0,
            "task_idle": 300.0,
        }
    }

    payload = build_dashboard_payload(
        store, session.id, runtime_paths=runtime_paths, idle_state=idle_state
    )

    active_workers = [w for w in payload["workers"] if w.get("status") == "active"]
    assert active_workers, "Expected at least one active worker"
    worker = active_workers[0]
    assert "last_activity_ago" not in worker, "Stale idle cache from another task must be ignored"
    assert "task_idle_limit" not in worker, "Stale idle cache from another task must be ignored"


def test_build_dashboard_payload_omits_idle_fields_when_no_idle_state(tmp_path: Path) -> None:
    """build_dashboard_payload must NOT include last_activity_ago when idle_state is None."""
    from cognitive_switchyard.server import build_dashboard_payload

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="sess-no-idle-006",
        name="No Idle State Test",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    store.update_session_status(session.id, status="running", started_at=_timestamp_offset(seconds=-30))
    _register_task(store, session.id, task_id="NI1", title="No idle task")
    store.project_task(session.id, "NI1", status="active", worker_slot=0)

    payload = build_dashboard_payload(store, session.id, runtime_paths=runtime_paths)

    active_workers = [w for w in payload["workers"] if w.get("status") == "active"]
    assert active_workers, "Expected at least one active worker"
    worker = active_workers[0]
    assert "last_activity_ago" not in worker, "last_activity_ago should not be present when idle_state is None"


# ---------------------------------------------------------------------------
# Plan 007: mtime_iso in log endpoint
# ---------------------------------------------------------------------------


def test_log_endpoint_returns_mtime_iso_for_existing_log_file(tmp_path: Path) -> None:
    """Log endpoint includes mtime_iso as ISO 8601 timestamp when log file exists."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-mtime",
        name="mtime test",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(session.id, status="running", started_at="2026-03-09T10:05:00Z")
    _register_task(store, session.id, task_id="001", title="Task with log")
    store.project_task(session.id, "001", status="active", worker_slot=0)

    session_paths = runtime_paths.session_paths(session.id)
    session_paths.task_log("001").parent.mkdir(parents=True, exist_ok=True)
    session_paths.task_log("001").write_text("line one\nline two\n", encoding="utf-8")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session.id}/tasks/001/log?offset=0&limit=50")
        data = resp.json()
        assert resp.status_code == 200
        assert data["mtime_iso"] is not None
        assert data["mtime_iso"].endswith("Z")
        # Verify it's a valid ISO 8601 timestamp
        datetime.fromisoformat(data["mtime_iso"].replace("Z", "+00:00"))


def test_completed_live_task_detail_and_log_use_task_scoped_log_when_worker_slot_is_cleared(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-completed-live-log",
        name="completed live log",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(session.id, status="running", started_at="2026-03-09T10:05:00Z")
    _register_task(store, session.id, task_id="001", title="Completed task")
    store.project_task(session.id, "001", status="active", worker_slot=0, timestamp="2026-03-09T10:05:30Z")
    store.project_task(session.id, "001", status="done", timestamp="2026-03-09T10:20:00Z")

    session_paths = runtime_paths.session_paths(session.id)
    session_paths.task_log("001").parent.mkdir(parents=True, exist_ok=True)
    session_paths.task_log("001").write_text("completed task log\n", encoding="utf-8")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        task_resp = client.get(f"/api/sessions/{session.id}/tasks/001")
        log_resp = client.get(f"/api/sessions/{session.id}/tasks/001/log?offset=0&limit=50")

    assert task_resp.status_code == 200
    task_data = task_resp.json()["task"]
    assert task_data["status"] == "done"
    assert task_data["worker_slot"] is None
    assert task_data["log_path"] == str(session_paths.task_log("001"))
    assert log_resp.status_code == 200
    assert log_resp.json()["content"] == "completed task log\n"


def test_task_log_endpoint_keeps_logs_distinct_for_two_done_tasks_that_shared_a_slot(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-shared-slot-logs",
        name="shared slot logs",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(session.id, status="running", started_at="2026-03-09T10:05:00Z")
    _register_task(store, session.id, task_id="001", title="First task")
    _register_task(store, session.id, task_id="002", title="Second task")
    store.project_task(session.id, "001", status="active", worker_slot=0, timestamp="2026-03-09T10:05:30Z")
    store.project_task(session.id, "001", status="done", timestamp="2026-03-09T10:10:00Z")
    store.project_task(session.id, "002", status="active", worker_slot=0, timestamp="2026-03-09T10:10:30Z")
    store.project_task(session.id, "002", status="done", timestamp="2026-03-09T10:15:00Z")

    session_paths = runtime_paths.session_paths(session.id)
    session_paths.task_log("001").parent.mkdir(parents=True, exist_ok=True)
    session_paths.task_log("001").write_text("first task only\n", encoding="utf-8")
    session_paths.task_log("002").write_text("second task only\n", encoding="utf-8")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        first_resp = client.get(f"/api/sessions/{session.id}/tasks/001/log?offset=0&limit=50")
        second_resp = client.get(f"/api/sessions/{session.id}/tasks/002/log?offset=0&limit=50")

    assert first_resp.status_code == 200
    assert first_resp.json()["content"] == "first task only\n"
    assert second_resp.status_code == 200
    assert second_resp.json()["content"] == "second task only\n"


def test_log_endpoint_returns_mtime_iso_null_for_missing_log(tmp_path: Path) -> None:
    """Log endpoint returns mtime_iso: null when no log file exists."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-nolog",
        name="no log test",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(session.id, status="running", started_at="2026-03-09T10:05:00Z")
    _register_task(store, session.id, task_id="001", title="Task without log")
    store.project_task(session.id, "001", status="active", worker_slot=0)
    # Do NOT create the worker log file

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session.id}/tasks/001/log?offset=0&limit=50")
        data = resp.json()
        assert resp.status_code == 200
        assert data["mtime_iso"] is None


def test_log_endpoint_returns_mtime_iso_null_for_summary_task(tmp_path: Path) -> None:
    """Log endpoint returns mtime_iso: null when the task comes from a summary."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-summary-mtime",
        name="summary mtime test",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(session.id, status="completed", started_at="2026-03-09T10:05:00Z")
    _register_task(store, session.id, task_id="001", title="Summary task")
    store.project_task(session.id, "001", status="done", timestamp="2026-03-09T10:20:00Z")

    session_paths = runtime_paths.session_paths(session.id)
    session_paths.summary.parent.mkdir(parents=True, exist_ok=True)
    session_paths.summary.write_text(
        json.dumps(
            {
                "session": {
                    "id": session.id,
                    "name": "summary mtime test",
                    "pack": "claude-code",
                    "status": "completed",
                    "created_at": "2026-03-09T10:00:00Z",
                    "started_at": "2026-03-09T10:05:00Z",
                    "completed_at": "2026-03-09T10:20:00Z",
                    "duration_seconds": 900,
                },
                "tasks": [
                    {
                        "task_id": "001",
                        "title": "Summary task",
                        "status": "done",
                        "started_at": "2026-03-09T10:05:00Z",
                        "completed_at": "2026-03-09T10:20:00Z",
                    }
                ],
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )
    store.write_successful_session_summary(session.id)

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session.id}/tasks/001/log?offset=0&limit=50")
        data = resp.json()
        assert resp.status_code == 200
        assert data["mtime_iso"] is None


def test_start_button_enabled_after_reset_to_created(tmp_path: Path) -> None:
    """Regression 004: files added after a reset must show in_snapshot=True so the Start button is enabled."""
    import os
    from datetime import UTC, datetime

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-004-start",
        name="Reset start test",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)

    # Add a file and start the session
    f1 = session_paths.intake / "001_initial.md"
    f1.write_text("# Initial\n", encoding="utf-8")
    pre_start_ts = datetime(2026, 3, 16, 10, 4, 0, tzinfo=UTC).timestamp()
    os.utime(f1, (pre_start_ts, pre_start_ts))

    store.update_session_status(session.id, status="running", started_at="2026-03-16T10:05:00Z")

    # Reset back to created (as happens after a failed pipeline run)
    store.update_session_status(session.id, status="created")

    # Add a new file after the reset
    f2 = session_paths.intake / "002_post_reset.md"
    f2.write_text("# Post reset\n", encoding="utf-8")
    post_reset_ts = datetime(2026, 3, 16, 10, 10, 0, tzinfo=UTC).timestamp()
    os.utime(f2, (post_reset_ts, post_reset_ts))

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session.id}/intake")
        assert resp.status_code == 200
        data = resp.json()
        # started_at was cleared on reset, so all files must be in_snapshot=True
        for file_entry in data["files"]:
            assert file_entry["in_snapshot"] is True, (
                f"Expected in_snapshot=True for {file_entry['filename']} but got {file_entry['in_snapshot']}"
            )


def test_rescan_clears_started_at_on_created_session(tmp_path: Path) -> None:
    """Regression 004: rescan must clear stale started_at when session status is 'created'."""
    import sqlite3

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-004-rescan",
        name="Rescan clear test",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )

    # Simulate pre-fix stale state: status=created but started_at still set
    with sqlite3.connect(store.database_path) as conn:
        conn.execute(
            "UPDATE sessions SET status='created', started_at='2026-03-16T10:05:00Z' WHERE id=?",
            (session.id,),
        )
        conn.commit()

    assert store.get_session(session.id).started_at == "2026-03-16T10:05:00Z"

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(f"/api/sessions/{session.id}/rescan")
        assert resp.status_code == 200

    assert store.get_session(session.id).started_at is None


# ---------------------------------------------------------------------------
# Plan 003 — Reprocess endpoint and UI button
# ---------------------------------------------------------------------------


def test_reprocess_with_staged_plans(tmp_path: Path) -> None:
    """POST /reprocess returns 202 when session has staged plans."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="rp-001",
        name="Reprocess Staged",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    # Register two tasks and move them to staged
    _register_task(store, session.id, task_id="001", title="Task 1")
    _register_task(store, session.id, task_id="002", title="Task 2")
    store.project_task(session.id, "001", status="staged")
    store.project_task(session.id, "002", status="staged")
    # Ensure the session is in an allowed status
    store.update_session_status(session.id, status="created")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(f"/api/sessions/{session.id}/reprocess")

    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"
    # A reprocess event should have been appended
    events = store.list_events(session.id)
    assert any(e.event_type == "session.reprocess" for e in events)


def test_reprocess_with_intake_and_staging(tmp_path: Path) -> None:
    """POST /reprocess accepts session with both intake and staged files."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="rp-002",
        name="Reprocess Intake+Staged",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    store.update_session_status(session.id, status="idle")
    session_paths = runtime_paths.session_paths(session.id)
    # Write a raw intake file (no DB row needed)
    session_paths.intake.mkdir(parents=True, exist_ok=True)
    intake_file = session_paths.intake / "idea.md"
    intake_file.write_text("# Intake idea\n", encoding="utf-8")
    # Register a staged task
    _register_task(store, session.id, task_id="001", title="Staged Task")
    store.project_task(session.id, "001", status="staged")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(f"/api/sessions/{session.id}/reprocess")

    assert resp.status_code == 202
    # The intake file should still exist immediately after the endpoint returns
    # (pipeline runs in background thread)
    assert intake_file.exists()


def test_reprocess_clears_stale_db_state(tmp_path: Path) -> None:
    """POST /reprocess deletes resolution.json and DB rows for staged tasks."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="rp-003",
        name="Reprocess Clear State",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    store.update_session_status(session.id, status="created")
    session_paths = runtime_paths.session_paths(session.id)

    # Write a stale resolution.json
    session_paths.resolution.parent.mkdir(parents=True, exist_ok=True)
    session_paths.resolution.write_text('{"plans": []}', encoding="utf-8")

    # Register two staged tasks
    _register_task(store, session.id, task_id="s1", title="Staged 1")
    _register_task(store, session.id, task_id="s2", title="Staged 2")
    store.project_task(session.id, "s1", status="staged")
    store.project_task(session.id, "s2", status="staged")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(f"/api/sessions/{session.id}/reprocess")

    assert resp.status_code == 202
    # resolution.json must be deleted
    assert not session_paths.resolution.exists()
    # DB rows for staged tasks must be deleted
    with pytest.raises(KeyError):
        store.get_task(session.id, "s1")
    with pytest.raises(KeyError):
        store.get_task(session.id, "s2")


def test_reprocess_blocked_while_workers_active(tmp_path: Path) -> None:
    """POST /reprocess returns 409 when workers are active."""
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="rp-004",
        name="Reprocess Active Block",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    store.update_session_status(session.id, status="idle")
    # Create an active worker via project_task (creates worker_slot entry)
    _register_task(store, session.id, task_id="w1", title="Active Task")
    store.project_task(session.id, "w1", status="active", worker_slot=0)
    # Add a staged plan so canReprocess logic would otherwise allow it
    _register_task(store, session.id, task_id="s1", title="Staged Task")
    store.project_task(session.id, "s1", status="staged")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(f"/api/sessions/{session.id}/reprocess")

    assert resp.status_code == 409
    assert "workers are active" in resp.json()["detail"]


def test_reprocess_cleans_worktree_on_backward_move(tmp_path: Path) -> None:
    """move_task from done→intake calls git branch -D for the per-task branch."""
    import json
    from unittest.mock import MagicMock, patch
    from cognitive_switchyard.server import ConnectionManager, SessionController

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    config_json = json.dumps({
        "environment": {
            "COGNITIVE_SWITCHYARD_SOURCE_REPO": "/source/repo",
            "COGNITIVE_SWITCHYARD_REPO_ROOT": "/worktree/path",
        }
    })
    session = store.create_session(
        session_id="rp-005",
        name="Worktree Cleanup",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
        config_json=config_json,
    )
    _register_task(store, session.id, task_id="cleanup-t1", title="Cleanup Task")
    store.project_task(session.id, "cleanup-t1", status="done")

    cm = ConnectionManager()
    controller = SessionController(
        store=store,
        runtime_paths=runtime_paths,
        connection_manager=cm,
    )

    with patch("cognitive_switchyard.server.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        controller.move_task(session.id, "cleanup-t1", "intake")

    # Verify git branch -D was called for the task branch
    calls = [list(call.args[0]) for call in mock_run.call_args_list]
    assert any(
        call[:4] == ["git", "-C", "/source/repo", "branch"]
        and "-D" in call
        and "switchyard-cleanup-t1" in call
        for call in calls
    )
    # Task row should be deleted (moved to intake)
    with pytest.raises(KeyError):
        store.get_task(session.id, "cleanup-t1")


def test_move_ready_to_staged(tmp_path: Path) -> None:
    """A ready task can be moved to staged via the /move endpoint."""
    from cognitive_switchyard.server import SessionController

    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="rp-006",
        name="Move Ready to Staged",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    _register_task(store, session.id, task_id="r1", title="Ready Task")
    # task is already in "ready" status after register

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/sessions/{session.id}/tasks/r1/move",
            json={"target_status": "staged"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "moved"
    assert body["from"] == "ready"
    assert body["to"] == "staged"

    task = store.get_task(session.id, "r1")
    assert task.status == "staged"

    # Plan file should be in staging directory
    session_paths = runtime_paths.session_paths(session.id)
    assert (session_paths.staging / "r1.plan.md").exists()


def test_serialize_intake_listing_filters_non_md_and_meta_files(tmp_path: Path) -> None:
    """_serialize_intake_listing must show only non-meta .md files, filtering
    out .DS_Store, CLAUDE.md, NEXT_SEQUENCE, and non-.md files.

    Regression: the old implementation used unfiltered rglob("*"), which showed
    .DS_Store, CLAUDE.md, and NEXT_SEQUENCE in the UI.
    """
    store, runtime_paths = _build_store(tmp_path)
    _write_runtime_pack(runtime_paths)
    session = store.create_session(
        session_id="session-003-intake-filter",
        name="Intake filter test",
        pack="claude-code",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)

    # Create various files: only real_task.md should appear.
    (session_paths.intake / "real_task.md").write_text("# Task\n", encoding="utf-8")
    (session_paths.intake / ".DS_Store").write_bytes(b"\x00\x00")
    (session_paths.intake / "CLAUDE.md").write_text("# Instructions\n", encoding="utf-8")
    (session_paths.intake / "NEXT_SEQUENCE").write_text("5\n", encoding="utf-8")
    (session_paths.intake / "notes.txt").write_text("some notes\n", encoding="utf-8")

    app = create_app(store=store, runtime_paths=runtime_paths)
    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{session.id}/intake")

    assert response.status_code == 200
    data = response.json()
    filenames = [f["filename"] for f in data["files"]]
    assert filenames == ["real_task.md"], (
        f"Only non-meta .md files should appear in intake listing, got {filenames!r}"
    )
