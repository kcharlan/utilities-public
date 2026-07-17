from __future__ import annotations

import os
import json
from pathlib import Path
from textwrap import dedent
from datetime import UTC, datetime, timedelta

import pytest

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.models import TaskPlan, reconstruct_worker_card_state
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _write_script(path: Path, contents: str, *, executable: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(contents).lstrip(), encoding="utf-8")
    mode = path.stat().st_mode
    if executable:
        path.chmod(mode | 0o111)
    else:
        path.chmod(mode & ~0o111)


def _write_pack(
    tmp_path: Path,
    *,
    name: str,
    max_workers: int = 2,
    task_idle: int = 5,
    task_max: int = 0,
    session_max: int = 60,
    isolation_type: str = "none",
    prerequisites: str = "",
    preflight: str | None = None,
    isolate_start: str | None = None,
    isolate_end: str | None = None,
    planning_enabled: bool = False,
    planning_max_instances: int = 1,
    resolution_executor: str | None = None,
    resolve_script_name: str = "resolve",
    resolve_script_body: str | None = None,
    verification_enabled: bool = False,
    verification_interval: int = 4,
    verification_command: str | None = None,
    auto_fix_enabled: bool = False,
    execute_script_name: str = "execute.py",
    execute_script_body: str,
) -> Path:
    pack_root = tmp_path / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True)
    prompts_dir = pack_root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    isolation_block = f"isolation:\n  type: {isolation_type}\n"
    if isolate_start is not None:
        _write_script(scripts_dir / "isolate_start.py", isolate_start)
        isolation_block += "  setup: scripts/isolate_start.py\n"
    if isolate_end is not None:
        _write_script(scripts_dir / "isolate_end.py", isolate_end)
        isolation_block += "  teardown: scripts/isolate_end.py\n"
    if preflight is not None:
        _write_script(scripts_dir / "preflight", preflight)

    _write_script(scripts_dir / execute_script_name, execute_script_body)

    manifest_lines = [
        f"name: {name}",
        "description: Orchestrator test pack.",
        "version: 1.2.3",
        "",
    ]
    if prerequisites.strip():
        manifest_lines.extend(dedent(prerequisites).strip().splitlines())
        manifest_lines.append("")
    manifest_lines.extend(
        [
            "phases:",
        ]
    )
    if planning_enabled:
        (prompts_dir / "planner.md").write_text("planner prompt\n", encoding="utf-8")
        manifest_lines.extend(
            [
                "  planning:",
                "    enabled: true",
                "    executor: agent",
                "    model: test-planner",
                "    prompt: prompts/planner.md",
                f"    max_instances: {planning_max_instances}",
            ]
        )
    if resolution_executor == "agent":
        (prompts_dir / "resolver.md").write_text("resolver prompt\n", encoding="utf-8")
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: agent",
                "    model: test-resolver",
                "    prompt: prompts/resolver.md",
            ]
        )
    elif resolution_executor == "script":
        _write_script(scripts_dir / resolve_script_name, resolve_script_body or "")
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: script",
                f"    script: scripts/{resolve_script_name}",
            ]
        )
    elif resolution_executor == "passthrough":
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: passthrough",
            ]
        )
    manifest_lines.extend(
        [
            "  execution:",
            "    enabled: true",
            "    executor: shell",
            f"    command: scripts/{execute_script_name}",
            f"    max_workers: {max_workers}",
        ]
    )
    if verification_enabled:
        assert verification_command is not None
        manifest_lines.extend(
            [
                "  verification:",
                "    enabled: true",
                "    command: >-",
                f"      {verification_command}",
                f"    interval: {verification_interval}",
            ]
        )
    manifest_lines.append("")
    if auto_fix_enabled:
        (prompts_dir / "fixer.md").write_text("fixer prompt\n", encoding="utf-8")
        manifest_lines.extend(
            [
                "auto_fix:",
                "  enabled: true",
                "  max_attempts: 2",
                "  model: test-fixer",
                "  prompt: prompts/fixer.md",
                "",
            ]
        )
    manifest_lines.extend(
        [
            "timeouts:",
            f"  task_idle: {task_idle}",
            f"  task_max: {task_max}",
            f"  session_max: {session_max}",
            "",
        ]
    )
    manifest_lines.extend(isolation_block.strip().splitlines())
    (pack_root / "pack.yaml").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return pack_root


def _register_task(
    store: StateStore,
    *,
    session_id: str,
    task_id: str,
    title: str | None = None,
    depends_on: tuple[str, ...] = (),
    anti_affinity: tuple[str, ...] = (),
    exec_order: int = 1,
    full_test_after: bool = False,
) -> None:
    plan = TaskPlan(
        task_id=task_id,
        title=title if title is not None else f"Task {task_id}",
        depends_on=depends_on,
        anti_affinity=anti_affinity,
        exec_order=exec_order,
        full_test_after=full_test_after,
    )
    store.register_task_plan(
        session_id=session_id,
        plan=plan,
        plan_text=dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            DEPENDS_ON: {", ".join(depends_on) if depends_on else "none"}
            ANTI_AFFINITY: {", ".join(anti_affinity) if anti_affinity else "none"}
            EXEC_ORDER: {exec_order}
            FULL_TEST_AFTER: {"yes" if full_test_after else "no"}
            ---

            # Plan: Task {task_id}
            """
        ).lstrip(),
        created_at="2026-03-09T10:00:00Z",
    )


def _timestamp_offset(*, seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def test_start_execution_runs_preflight_before_marking_session_running(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-preflight",
        name="Packet 06 preflight",
        pack="preflight-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")

    pack_root = _write_pack(
        tmp_path,
        name="preflight-pack",
        prerequisites="""
        prerequisites:
          - name: Missing dependency
            check: exit 7
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.started is False
    assert result.session_status == "created"
    assert result.startup_failure is not None
    assert result.startup_failure.reason == "preflight_failed"
    assert store.get_session(session.id).status == "created"
    assert store.list_events(session.id)[0].event_type == "session.preflight_failed"


def test_execute_session_can_publish_backend_runtime_events_without_changing_task_outcomes(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-11a-runtime-events",
        name="Packet 11A runtime events",
        pack="runtime-events-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="039")

    execute_body = (repo_root / "tests" / "fixtures" / "workers" / "streaming_worker.py").read_text(
        encoding="utf-8"
    )
    pack_root = _write_pack(
        tmp_path,
        name="runtime-events-pack",
        execute_script_name="streaming_worker.py",
        execute_script_body=execute_body,
    )

    captured_events: list[object] = []

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.05,
        runtime_event_sink=captured_events.append,
    )

    event_types = [event.message_type for event in captured_events]

    assert result.started is True
    assert result.session_status == "idle"
    assert store.get_task(session.id, "039").status == "done"
    assert event_types.count("task_status_change") >= 2
    assert "state_update" in event_types
    assert "log_line" in event_types
    assert "progress_detail" in event_types


def test_execute_session_runtime_events_are_sufficient_to_reconstruct_worker_card_state_without_changing_outcomes(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-11b-runtime-cache",
        name="Packet 11B runtime cache",
        pack="runtime-cache-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="039")

    execute_body = (repo_root / "tests" / "fixtures" / "workers" / "streaming_worker.py").read_text(
        encoding="utf-8"
    )
    pack_root = _write_pack(
        tmp_path,
        name="runtime-cache-pack",
        execute_script_name="streaming_worker.py",
        execute_script_body=execute_body,
    )

    captured_events: list[object] = []

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.05,
        runtime_event_sink=captured_events.append,
    )

    worker_state = reconstruct_worker_card_state(
        session_id=session.id,
        events=tuple(captured_events),
    )

    assert result.started is True
    assert result.session_status == "idle"
    assert store.get_task(session.id, "039").status == "done"
    assert worker_state[0].task_id == "039"
    assert worker_state[0].phase_name == "implementing"
    assert worker_state[0].phase_index == 1
    assert worker_state[0].phase_total == 2
    assert worker_state[0].detail_message == "Streaming detail"
    assert {event.message_type for event in captured_events} >= {
        "state_update",
        "task_status_change",
        "log_line",
        "progress_detail",
    }


def test_running_session_recovers_before_preflight_failure_returns_stranded_work_to_ready(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-running-preflight-failure",
        name="Packet 07 running preflight failure",
        pack="running-preflight-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="090")
    active_task = store.project_task(
        session.id,
        "090",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-5),
    )

    pack_root = _write_pack(
        tmp_path,
        name="running-preflight-pack",
        prerequisites="""
        prerequisites:
          - name: Broken dependency
            check: exit 9
        """,
        isolation_type="temp-directory",
        isolate_end="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
    )
    workspace_path = runtime_paths.session_paths(session.id).root / "workspace" / "090"
    workspace_path.mkdir(parents=True, exist_ok=True)
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="090",
        workspace_path=workspace_path,
        pid=None,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.started is True
    assert result.session_status == "running"
    assert result.startup_failure is not None
    assert store.get_task(session.id, "090").status == "ready"
    assert store.get_task(session.id, "090").plan_path == runtime_paths.session_paths(session.id).ready / "090.plan.md"
    assert not runtime_paths.session_paths(session.id).worker_recovery_path(0).exists()


def test_paused_session_recovers_without_dispatch_even_if_preflight_would_fail(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-paused-preflight-failure",
        name="Packet 07 paused preflight failure",
        pack="paused-preflight-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="091")
    store.project_task(
        session.id,
        "091",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(
        session.id,
        status="paused",
        started_at=_timestamp_offset(seconds=-5),
    )

    pack_root = _write_pack(
        tmp_path,
        name="paused-preflight-pack",
        prerequisites="""
        prerequisites:
          - name: Broken dependency
            check: exit 9
        """,
        isolation_type="temp-directory",
        isolate_end="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="091",
        workspace_path=runtime_paths.session_paths(session.id).root / "workspace" / "091",
        pid=None,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.started is True
    assert result.session_status == "paused"
    assert result.startup_failure is None
    assert store.get_session(session.id).status == "paused"
    assert store.get_task(session.id, "091").status == "ready"


def test_dispatch_respects_dependencies_anti_affinity_and_max_workers(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-dispatch",
        name="Packet 06 dispatch",
        pack="dispatch-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", exec_order=1)
    _register_task(store, session_id=session.id, task_id="002", anti_affinity=("003",), exec_order=1)
    _register_task(store, session_id=session.id, task_id="003", anti_affinity=("002",), exec_order=1)
    _register_task(store, session_id=session.id, task_id="004", depends_on=("001",), exec_order=1)

    pack_root = _write_pack(
        tmp_path,
        name="dispatch-pack",
        max_workers=2,
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        import time
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.split('.', 1)[0]
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        trace_path = Path(os.environ['ORCH_TRACE'])
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open('a', encoding='utf-8') as handle:
            handle.write(f"start:{task_id}\\n")
        time.sleep(0.25 if task_id == "002" else 0.12)
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        with trace_path.open('a', encoding='utf-8') as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )
    trace_path = tmp_path / "dispatch-trace.log"

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"ORCH_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    dispatch_events = [
        event.task_id
        for event in store.list_events(session.id)
        if event.event_type == "task.dispatched"
    ]
    trace_lines = trace_path.read_text(encoding="utf-8").splitlines()

    assert result.session_status == "idle"
    assert dispatch_events == ["001", "002", "004", "003"]
    assert set(trace_lines[:2]) == {"start:001", "start:002"}
    assert trace_lines.index("start:004") > trace_lines.index("end:001")
    assert trace_lines.index("start:003") > trace_lines.index("end:002")
    assert trace_lines.index("start:004") < trace_lines.index("start:003")


def test_successful_task_runs_isolation_worker_collection_and_done_projection(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-success",
        name="Packet 06 success",
        pack="isolation-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="010")

    marker_path = tmp_path / "isolation.log"
    pack_root = _write_pack(
        tmp_path,
        name="isolation-pack",
        isolation_type="temp-directory",
        isolate_start=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        slot, task_id, session_root = sys.argv[1:4]
        workspace = Path(session_root) / "isolated" / task_id
        workspace.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"start|{{slot}}|{{task_id}}|{{session_root}}\\n", encoding='utf-8')
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        slot, task_id, workspace, status = sys.argv[1:5]
        with marker.open('a', encoding='utf-8') as handle:
            handle.write(f"end|{{slot}}|{{task_id}}|{{workspace}}|{{status}}\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    task = store.get_task(session.id, "010")
    marker_lines = marker_path.read_text(encoding="utf-8").splitlines()
    expected_workspace = runtime_paths.session_paths(session.id).root / "isolated" / "010"

    assert result.session_status == "idle"
    assert task.status == "done"
    assert task.plan_path == runtime_paths.session_paths(session.id).done / "010.plan.md"
    assert marker_lines[0].startswith("start|0|010|")
    assert marker_lines[1] == f"end|0|010|{expected_workspace}|done"


def test_failed_or_timed_out_task_moves_to_blocked_and_calls_isolate_end_with_blocked_status(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-blocked",
        name="Packet 06 blocked",
        pack="blocked-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="011")

    marker_path = tmp_path / "blocked-isolation.log"
    pack_root = _write_pack(
        tmp_path,
        name="blocked-pack",
        task_idle=1,
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import time

        time.sleep(2)
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    task = store.get_task(session.id, "011")
    blocked_events = [event for event in store.list_events(session.id) if event.event_type == "task.blocked"]
    expected_workspace = runtime_paths.session_paths(session.id).root / "workspace" / "011"

    assert result.session_status == "running"
    assert result.blocked_tasks == ("011",)
    assert task.status == "blocked"
    assert task.plan_path == runtime_paths.session_paths(session.id).blocked / "011.plan.md"
    assert marker_path.read_text(encoding="utf-8").strip() == f"0|011|{expected_workspace}|blocked"
    assert "no output" in blocked_events[0].message


def test_invalid_status_sidecar_moves_task_to_blocked_and_calls_isolate_end_with_workspace(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-invalid-sidecar",
        name="Packet 06 invalid sidecar",
        pack="invalid-sidecar-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="012")

    marker_path = tmp_path / "invalid-sidecar-isolation.log"
    pack_root = _write_pack(
        tmp_path,
        name="invalid-sidecar-pack",
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: blocked\\nCOMMITS: none\\nTEST_RESULT: skip\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    task = store.get_task(session.id, "012")
    blocked_events = [event for event in store.list_events(session.id) if event.event_type == "task.blocked"]
    expected_workspace = runtime_paths.session_paths(session.id).root / "workspace" / "012"

    assert result.session_status == "running"
    assert result.blocked_tasks == ("012",)
    assert task.status == "blocked"
    assert marker_path.read_text(encoding="utf-8").strip() == f"0|012|{expected_workspace}|blocked"
    assert "invalid status sidecar" in blocked_events[0].message


def test_session_max_timeout_aborts_active_workers_and_marks_session_aborted(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-session-timeout",
        name="Packet 06 session timeout",
        pack="session-timeout-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="020")

    marker_path = tmp_path / "session-timeout-isolation.log"
    pack_root = _write_pack(
        tmp_path,
        name="session-timeout-pack",
        task_idle=0,
        session_max=1,
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import signal
        import time

        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            print("still running", flush=True)
            time.sleep(0.2)
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
        kill_grace_period=0.05,
    )

    task = store.get_task(session.id, "020")
    events = store.list_events(session.id)
    expected_workspace = runtime_paths.session_paths(session.id).root / "workspace" / "020"

    assert result.session_status == "aborted"
    assert store.get_session(session.id).status == "aborted"
    assert task.status == "blocked"
    assert marker_path.read_text(encoding="utf-8").strip() == f"0|020|{expected_workspace}|blocked"
    assert any(event.event_type == "session.aborted" for event in events)
    assert any(event.event_type == "task.blocked" and event.task_id == "020" for event in events)


def test_restart_honors_original_session_max_budget(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-session-max-restart",
        name="Packet 07 restart session max",
        pack="restart-session-max-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="021")
    store.update_session_status(
        session.id,
        status="running",
        started_at=_timestamp_offset(seconds=-2),
    )

    pack_root = _write_pack(
        tmp_path,
        name="restart-session-max-pack",
        session_max=1,
        execute_script_body="""
        #!/usr/bin/env python3
        from pathlib import Path
        import sys

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    assert result.session_status == "aborted"
    assert store.get_session(session.id).status == "aborted"
    assert store.list_done_tasks(session.id) == ()


def test_all_done_session_marks_completed_and_records_ordered_events(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-06-complete",
        name="Packet 06 complete",
        pack="complete-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="030")
    _register_task(store, session_id=session.id, task_id="031")

    pack_root = _write_pack(
        tmp_path,
        name="complete-pack",
        max_workers=1,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    events = store.list_events(session.id)

    assert result.session_status == "idle"
    assert [event.event_type for event in events] == [
        "session.running",
        "task.dispatched",
        "task.completed",
        "task.dispatched",
        "task.completed",
        "run.completed",
    ]


def test_execute_session_resumes_running_session_after_recovery_pass(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-running-resume",
        name="Packet 07 running resume",
        pack="resume-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="040")
    _register_task(store, session_id=session.id, task_id="041")
    stranded = store.project_task(
        session.id,
        "040",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="running")

    marker_path = tmp_path / "resume-isolation.log"
    trace_path = tmp_path / "resume-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="resume-pack",
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix('.plan.md')
        trace_path = Path(os.environ['ORCH_TRACE'])
        with trace_path.open('a', encoding='utf-8') as handle:
            handle.write(f"dispatch:{task_id}\\n")
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )
    _status_path = stranded.plan_path.with_name("040.status")
    _status_path.write_text(
        "STATUS: done\nCOMMITS: abc1234\nTESTS_RAN: targeted\nTEST_RESULT: pass\n",
        encoding="utf-8",
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="040",
        workspace_path=runtime_paths.session_paths(session.id).root / "workspace" / "040",
        pid=None,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"ORCH_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    assert result.session_status == "idle"
    assert store.get_task(session.id, "040").status == "done"
    assert store.get_task(session.id, "041").status == "done"
    assert trace_path.read_text(encoding="utf-8").splitlines() == ["dispatch:041"]
    assert marker_path.read_text(encoding="utf-8").splitlines()[0].endswith("|040|" + str(runtime_paths.session_paths(session.id).root / "workspace" / "040") + "|done")


def test_execute_session_recovers_paused_session_without_dispatching_new_work(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-paused-resume",
        name="Packet 07 paused recovery",
        pack="paused-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="050")
    _register_task(store, session_id=session.id, task_id="051")
    store.project_task(
        session.id,
        "050",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="paused")

    marker_path = tmp_path / "paused-isolation.log"
    trace_path = tmp_path / "paused-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="paused-pack",
        isolation_type="temp-directory",
        isolate_start="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        workspace = Path(sys.argv[3]) / "workspace" / sys.argv[2]
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        from pathlib import Path

        Path(os.environ['ORCH_TRACE']).write_text('unexpected dispatch\\n', encoding='utf-8')
        """,
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="050",
        workspace_path=runtime_paths.session_paths(session.id).root / "workspace" / "050",
        pid=None,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"ORCH_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    assert result.started is True
    assert result.session_status == "paused"
    assert store.get_session(session.id).status == "paused"
    assert store.get_task(session.id, "050").status == "ready"
    assert store.get_task(session.id, "051").status == "ready"
    assert marker_path.read_text(encoding="utf-8").strip() == (
        f"0|050|{runtime_paths.session_paths(session.id).root / 'workspace' / '050'}|blocked"
    )
    assert not trace_path.exists()


def test_start_session_runs_planning_resolution_then_hands_off_to_execution_when_no_review_items_exist(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import start_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-start",
        name="Packet 08 start session",
        pack="start-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.intake / "051_feature.md").write_text("# Feature request\n", encoding="utf-8")

    pack_root = _write_pack(
        tmp_path,
        name="start-pack",
        planning_enabled=True,
        resolution_executor="passthrough",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_plan_path = Path(sys.argv[1])
        task_id = task_plan_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
        status_path = task_plan_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    def planner_agent(*, model: str, prompt_path: Path, intake_path: Path, **_: object) -> str:
        assert model == "test-planner"
        assert prompt_path.name == "planner.md"
        assert intake_path.name == "051_feature.md"
        return dedent(
            """
            ---
            PLAN_ID: 051
            PRIORITY: normal
            ESTIMATED_SCOPE: src/feature.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task 051

            Implement the feature.
            """
        ).lstrip()

    result = start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        poll_interval=0.01,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result.started is True
    assert result.session_status == "idle"
    assert result.review_tasks == ()
    assert result.resolution_conflicts == ()
    assert not session_paths.summary.is_file()
    assert (session_paths.done / "051.plan.md").exists()
    assert store.list_done_tasks(session.id)[0].task_id == "051"


def test_start_session_routes_session_planner_count_into_planning_runtime_without_changing_execution_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cognitive_switchyard import orchestrator
    from cognitive_switchyard.models import OrchestratorResult, SessionPreparationResult

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-11d-start",
        name="Packet 11D start",
        pack="planning-pack",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps({"planner_count": 5}),
    )
    pack_root = _write_pack(
        tmp_path,
        name="planning-pack",
        planning_enabled=True,
        planning_max_instances=2,
        resolution_executor="passthrough",
        execute_script_body="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
    )

    captured: dict[str, object] = {}

    def fake_prepare_session_for_execution(**kwargs) -> SessionPreparationResult:
        captured["prepare"] = kwargs
        return SessionPreparationResult(session_id=kwargs["session_id"], ready_task_ids=("001",))

    def fake_execute_session(**kwargs) -> OrchestratorResult:
        captured["execute"] = kwargs
        return OrchestratorResult(
            session_id=kwargs["session_id"],
            started=True,
            session_status="running",
        )

    monkeypatch.setattr(orchestrator, "prepare_session_for_execution", fake_prepare_session_for_execution)
    monkeypatch.setattr(orchestrator, "execute_session", fake_execute_session)

    result = orchestrator.start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=object(),
        resolver_agent=object(),
        env={"PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    assert result.session_status == "running"
    assert captured["prepare"]["effective_planner_count"] == 2
    assert captured["execute"]["poll_interval"] == 0.01
    assert captured["execute"]["skip_preflight"] is True
    # env is now merged with session config environment and pack root
    assert captured["execute"]["env"]["PATH"] == os.environ["PATH"]
    assert "COGNITIVE_SWITCHYARD_PACK_ROOT" in captured["execute"]["env"]


@pytest.mark.parametrize("status", ["verifying", "auto_fixing"])
def test_start_session_resumes_verifying_and_auto_fixing_sessions_via_execute_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    from cognitive_switchyard.models import OrchestratorResult
    from cognitive_switchyard import orchestrator

    store, _runtime_paths = _build_store(tmp_path)
    pack_name = f"{status}-pack".replace("_", "-")
    session = store.create_session(
        session_id=f"session-10-resume-{status}",
        name=f"Packet 10 resume {status}",
        pack=pack_name,
        created_at="2026-03-09T10:00:00Z",
    )
    store.update_session_status(
        session.id,
        status=status,
        started_at=_timestamp_offset(seconds=-5),
    )

    captured: dict[str, object] = {}

    def fake_execute_session(**kwargs) -> OrchestratorResult:
        captured.update(kwargs)
        return OrchestratorResult(
            session_id=session.id,
            started=True,
            session_status=status,
        )

    monkeypatch.setattr(orchestrator, "execute_session", fake_execute_session)

    pack_root = _write_pack(
        tmp_path,
        name=pack_name,
        execute_script_body="""
        #!/usr/bin/env python3
        raise SystemExit(0)
        """,
    )

    result = orchestrator.start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    assert result.started is True
    assert result.session_status == status
    assert captured["session_id"] == session.id
    assert captured["store"] is store


def test_task_failure_with_auto_fix_success_reclassifies_task_done_and_resumes_dispatch(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.models import FixerAttemptResult
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-task-auto-fix",
        name="Packet 09 task auto-fix",
        pack="task-auto-fix-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002", depends_on=("001",))

    trace_path = tmp_path / "task-auto-fix-trace.log"
    verify_flag_path = runtime_paths.session_paths(session.id).root / "verify.ok"
    pack_root = _write_pack(
        tmp_path,
        name="task-auto-fix-pack",
        max_workers=1,
        verification_enabled=True,
        verification_interval=99,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os, sys; "
            "flag = Path(os.environ['VERIFY_FLAG']); "
            "print('verification-pass' if flag.exists() else 'verification-fail'); "
            "raise SystemExit(0 if flag.exists() else 1)\""
        ),
        auto_fix_enabled=True,
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["ORCH_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        status_path = task_path.with_name(task_id + ".status")
        if task_id == "001":
            status_path.write_text(
                "STATUS: blocked\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: fail\\nBLOCKED_REASON: worker failed\\n",
                encoding="utf-8",
            )
            raise SystemExit(1)
        status_path.write_text(
            "STATUS: done\\nCOMMITS: def5678\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )
    fixer_calls: list[tuple[str | None, int]] = []

    def fixer_executor(context):
        fixer_calls.append((context.task_id, context.attempt))
        verify_flag_path.write_text("ok\n", encoding="utf-8")
        return FixerAttemptResult(success=True, summary="Created verify flag.")

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={
            "ORCH_TRACE": str(trace_path),
            "PATH": os.environ["PATH"],
            "VERIFY_FLAG": str(verify_flag_path),
        },
        poll_interval=0.01,
        fixer_executor=fixer_executor,
    )

    assert result.session_status == "idle"
    assert store.get_task(session.id, "001").status == "done"
    assert store.get_task(session.id, "002").status == "done"
    assert fixer_calls == [("001", 1)]
    assert trace_path.read_text(encoding="utf-8").splitlines() == [
        "start:001",
        "start:002",
        "end:002",
    ]


def test_verification_failure_without_auto_fix_pauses_session_with_ready_frontier_preserved(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-verification-paused",
        name="Packet 09 verification paused",
        pack="verification-paused-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002", depends_on=("001",))

    pack_root = _write_pack(
        tmp_path,
        name="verification-paused-pack",
        max_workers=1,
        verification_enabled=True,
        verification_interval=1,
        verification_command="python3 -c \"print('verification failed'); raise SystemExit(1)\"",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    events = store.list_events(session.id)

    assert result.session_status == "paused"
    assert store.get_session(session.id).status == "paused"
    assert store.get_task(session.id, "001").status == "done"
    assert store.get_task(session.id, "002").status == "ready"
    assert any(event.event_type == "session.verification_failed" for event in events)


def test_execute_session_uses_session_runtime_overrides_for_worker_count_verification_interval_and_timeouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cognitive_switchyard.orchestrator import execute_session
    from cognitive_switchyard.worker_manager import WorkerManager

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-11c-runtime-overrides",
        name="Packet 11C runtime overrides",
        pack="runtime-overrides-pack",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps(
            {
                "worker_count": 1,
                "verification_interval": 1,
                "task_idle": 7,
                "task_max": 11,
                "session_max": 600,
                "poll_interval": 0.01,
            }
        ),
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002")

    trace_path = tmp_path / "runtime-overrides.trace"
    verify_log = tmp_path / "runtime-overrides.verify"
    pack_root = _write_pack(
        tmp_path,
        name="runtime-overrides-pack",
        max_workers=2,
        task_idle=300,
        task_max=99,
        session_max=999,
        verification_enabled=True,
        verification_interval=99,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "Path(os.environ['VERIFY_TRACE']).open('a', encoding='utf-8').write('verify\\n')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import time
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["TRACE_PATH"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        time.sleep(0.05)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    captured_timeouts: dict[str, float] = {}
    original_init = WorkerManager.__init__

    def capturing_init(self, *args, **kwargs):
        captured_timeouts["default_task_idle"] = kwargs.get("default_task_idle")
        captured_timeouts["default_task_max"] = kwargs.get("default_task_max")
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr("cognitive_switchyard.orchestrator.WorkerManager.__init__", capturing_init)

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={
            "PATH": os.environ["PATH"],
            "TRACE_PATH": str(trace_path),
            "VERIFY_TRACE": str(verify_log),
        },
        poll_interval=0.2,
    )

    assert result.session_status == "idle"
    assert trace_path.read_text(encoding="utf-8").splitlines() == [
        "start:001",
        "end:001",
        "start:002",
        "end:002",
    ]
    # With interval=1 (from session override), verification fires after each of the 2 tasks.
    # The second interval fires on the last task → verified_this_iteration=True suppresses final.
    # Total = 2 verifications.
    assert verify_log.read_text(encoding="utf-8").splitlines() == ["verify", "verify"]
    assert captured_timeouts == {"default_task_idle": 7, "default_task_max": 11}


def test_session_custom_environment_overrides_reach_worker_and_verification_commands(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-11c-env",
        name="Packet 11C env",
        pack="env-pack",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps(
            {
                "verification_interval": 1,
                "environment": {"SESSION_TOKEN": "from-session"},
            }
        ),
    )
    _register_task(store, session_id=session.id, task_id="001")

    worker_env_path = tmp_path / "worker-env.txt"
    verify_env_path = tmp_path / "verify-env.txt"
    pack_root = _write_pack(
        tmp_path,
        name="env-pack",
        max_workers=1,
        verification_enabled=True,
        verification_interval=99,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "Path(os.environ['VERIFY_ENV_PATH']).write_text(os.environ['SESSION_TOKEN'] + '\\n', encoding='utf-8')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        Path(os.environ["WORKER_ENV_PATH"]).write_text(
            os.environ["SESSION_TOKEN"] + "\\n",
            encoding="utf-8",
        )
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={
            "PATH": os.environ["PATH"],
            "SESSION_TOKEN": "from-call",
            "WORKER_ENV_PATH": str(worker_env_path),
            "VERIFY_ENV_PATH": str(verify_env_path),
        },
        poll_interval=0.01,
    )

    assert result.session_status == "idle"
    assert worker_env_path.read_text(encoding="utf-8") == "from-session\n"
    assert verify_env_path.read_text(encoding="utf-8") == "from-session\n"


def test_successful_session_completion_writes_summary_before_trimming_runtime_artifacts(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-12a-success",
        name="Packet 12A success",
        pack="trim-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.intake.joinpath("001.md").write_text("# intake\n", encoding="utf-8")
    session_paths.resolution.write_text('{"tasks":[{"task_id":"001"}]}\n', encoding="utf-8")

    pack_root = _write_pack(
        tmp_path,
        name="trim-pack",
        max_workers=1,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1", flush=True)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.05,
    )

    assert result.session_status == "idle"
    assert not (session_paths.root / "summary.json").exists()
    assert store.get_task(session.id, "001").status == "done"
    assert "Run #1 completed." in session_paths.session_log.read_text(encoding="utf-8")


def test_blocked_or_aborted_sessions_do_not_trim_history_debug_artifacts(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    blocked = store.create_session(
        session_id="session-12a-blocked",
        name="Packet 12A blocked",
        pack="blocked-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=blocked.id, task_id="001")
    blocked_paths = runtime_paths.session_paths(blocked.id)
    blocked_paths.resolution.write_text('{"tasks":[{"task_id":"001"}]}\n', encoding="utf-8")
    blocked_pack_root = _write_pack(
        tmp_path,
        name="blocked-pack",
        max_workers=1,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1", flush=True)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: blocked\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: fail\\nBLOCKED_REASON: packet 12A test\\n",
            encoding="utf-8",
        )
        """,
    )

    blocked_result = execute_session(
        store=store,
        session_id=blocked.id,
        pack_manifest=load_pack_manifest(blocked_pack_root),
        poll_interval=0.05,
    )

    assert blocked_result.session_status == "running"
    assert blocked_paths.blocked.joinpath("001.plan.md").exists()
    assert blocked_paths.worker_log(0).exists()
    assert not blocked_paths.root.joinpath("summary.json").exists()

    aborted = store.create_session(
        session_id="session-12a-aborted",
        name="Packet 12A aborted",
        pack="aborted-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=aborted.id, task_id="001")
    aborted_paths = runtime_paths.session_paths(aborted.id)
    aborted_paths.resolution.write_text('{"tasks":[{"task_id":"001"}]}\n', encoding="utf-8")
    aborted_pack_root = _write_pack(
        tmp_path,
        name="aborted-pack",
        max_workers=1,
        session_max=1,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        import time
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1", flush=True)
        time.sleep(1.2)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    aborted_result = execute_session(
        store=store,
        session_id=aborted.id,
        pack_manifest=load_pack_manifest(aborted_pack_root),
        poll_interval=0.05,
        kill_grace_period=0.05,
    )

    assert aborted_result.session_status == "aborted"
    assert aborted_paths.worker_log(0).exists()
    assert aborted_paths.worker_dir(0).exists()
    assert not aborted_paths.root.joinpath("summary.json").exists()


def test_successful_session_generates_release_notes_before_trim_and_retains_them_after_trim(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-14-release-notes",
        name="Packet 14 release notes",
        pack="release-notes-pack",
        created_at="2026-03-10T10:00:00Z",
    )
    store.register_task_plan(
        session_id=session.id,
        plan=TaskPlan(
            task_id="001",
            title="Ship release notes",
            body="",
        ),
        plan_text=dedent(
            """
            ---
            PLAN_ID: 001
            DEPENDS_ON: none
            ANTI_AFFINITY: none
            EXEC_ORDER: 1
            FULL_TEST_AFTER: no
            ---

            # Plan: Ship release notes

            Deliver the artifact handoff.

            ## Operator Actions

            - Restart the service after deploy.
            - Share the summary with operators.
            """
        ).lstrip(),
        created_at="2026-03-10T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.resolution.write_text('{"tasks":[{"task_id":"001"}]}\n', encoding="utf-8")
    pack_root = _write_pack(
        tmp_path,
        name="release-notes-pack",
        max_workers=1,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1", flush=True)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.05,
    )

    release_notes_path = session_paths.root / "RELEASE_NOTES.md"

    assert result.session_status == "idle"
    # Summary and release notes are deferred to explicit end_session, not written at idle.
    assert not (session_paths.root / "summary.json").exists()
    assert not release_notes_path.is_file()

def test_deadlock_detected_when_ready_tasks_depend_on_blocked_task(tmp_path: Path) -> None:
    """Regression: the main loop must not spin forever when ready tasks exist
    but none are eligible because they depend on a blocked (not done) task and
    no workers are active."""
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-deadlock",
        name="Deadlock detection",
        pack="deadlock-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    # Task A has no dependencies; Task B depends on A.
    _register_task(store, session_id=session.id, task_id="001", exec_order=1)
    _register_task(store, session_id=session.id, task_id="002", depends_on=("001",), exec_order=2)

    # Move task A to blocked *before* the orchestrator runs, so 002 can never
    # become eligible (its dependency 001 will never complete).
    store.project_task(session.id, "001", status="blocked", timestamp="2026-03-09T10:00:01Z")

    pack_root = _write_pack(
        tmp_path,
        name="deadlock-pack",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    # Should detect deadlock and return, not loop forever.
    assert result.started is True
    assert "002" in result.blocked_tasks

    deadlock_events = [
        event
        for event in store.list_events(session.id)
        if event.event_type == "session.deadlock"
    ]
    assert len(deadlock_events) == 1
    assert "Deadlock" in deadlock_events[0].message
    assert "002" in deadlock_events[0].message


def test_pipeline_events_are_persisted_to_event_store_via_on_pipeline_event(
    tmp_path: Path,
) -> None:
    """Regression: _on_pipeline_event in orchestrator must persist pipeline events
    (file_claimed, file_planned) to the event store so they appear in recent_events.
    """
    from cognitive_switchyard.orchestrator import start_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-reg-pipeline-events",
        name="Pipeline event persistence",
        pack="reg-events-pack",
        created_at="2026-03-11T00:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.intake / "060_task.md").write_text("# Task 060\n", encoding="utf-8")

    pack_root = _write_pack(
        tmp_path,
        name="reg-events-pack",
        planning_enabled=True,
        resolution_executor="passthrough",
        execute_script_body=dedent("""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path
        task_plan_path = Path(sys.argv[1])
        task_id = task_plan_path.name.removesuffix(".plan.md")
        status_path = task_plan_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """),
    )

    def planner_agent(*, intake_path: Path, **_: object) -> str:
        task_id = intake_path.stem.split("_", 1)[0]
        return dedent(f"""
            ---
            PLAN_ID: {task_id}
            PRIORITY: normal
            ESTIMATED_SCOPE: src/task.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task {task_id}

            Implement task {task_id}.
        """).lstrip()

    start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        poll_interval=0.01,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    event_types = [e.event_type for e in store.list_events(session.id)]
    # file_claimed and file_planned must appear in the event store
    assert "file_claimed" in event_types, f"file_claimed missing from events: {event_types}"
    assert "file_planned" in event_types, f"file_planned missing from events: {event_types}"
    # resolver events must also appear
    assert "resolver_started" in event_types, f"resolver_started missing from events: {event_types}"
    assert "resolver_finished" in event_types, f"resolver_finished missing from events: {event_types}"


def test_concurrent_planners_emit_distinct_per_planner_task_ids(
    tmp_path: Path,
) -> None:
    """Regression: When multiple planners run concurrently, each log line must
    carry a distinct task_id (e.g. __planner_060_task__ and __planner_061_task__),
    not the shared __phase_planning__ key.
    """
    from cognitive_switchyard.agent_runtime import ClaudeCliRuntime

    # Collect (task_id, line) pairs emitted via the output callback
    emitted: list[tuple[str, str]] = []

    def output_callback(task_id: str, line: str) -> None:
        emitted.append((task_id, line))

    # Simulate _streaming_subprocess_runner returning immediately with some output
    def fake_subprocess_runner(*, command, cwd, input_text):
        import subprocess
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="plan output\n", stderr="")

    runtime = ClaudeCliRuntime(
        subprocess_runner=fake_subprocess_runner,
        output_line_callback=output_callback,
    )

    # Run planner for two different intake files
    from pathlib import Path as _Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = _Path(tmpdir) / "planner.md"
        prompt_path.write_text("test prompt", encoding="utf-8")
        session_root = _Path(tmpdir)

        for stem in ("060_task", "061_other"):
            intake_path = _Path(tmpdir) / f"{stem}.md"
            intake_path.write_text(f"# Intake {stem}\n", encoding="utf-8")
            try:
                runtime.planner_agent(
                    model="test-model",
                    prompt_path=prompt_path,
                    intake_path=intake_path,
                    intake_text=intake_path.read_text(),
                    session_root=session_root,
                )
            except Exception:
                pass  # Output is minimal but that's OK; we just care about task_ids

    task_ids_used = {task_id for task_id, _ in emitted}
    # Each planner must get its own distinct __planner_<stem>__ task_id
    assert "__planner_060_task__" in task_ids_used, f"task IDs seen: {task_ids_used}"
    assert "__planner_061_other__" in task_ids_used, f"task IDs seen: {task_ids_used}"
    # The generic __phase_planning__ key must NOT appear for planner invocations
    assert "__phase_planning__" not in task_ids_used, (
        "planner agents must not use the shared __phase_planning__ task_id; "
        f"task IDs seen: {task_ids_used}"
    )


# ---------------------------------------------------------------------------
# Regression tests for final verification fix (plan 003)
# ---------------------------------------------------------------------------

def test_final_verification_runs_after_interval_verification_resets_counter(
    tmp_path: Path,
) -> None:
    """Final verification fires even when interval verification already ran and reset the counter."""
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-final-ver-after-interval",
        name="Final verification after interval",
        pack="final-after-interval-pack",
        created_at="2026-03-11T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", exec_order=1)
    _register_task(store, session_id=session.id, task_id="002", exec_order=2)

    verify_count_path = tmp_path / "verify_count.txt"
    pack_root = _write_pack(
        tmp_path,
        name="final-after-interval-pack",
        max_workers=1,
        verification_enabled=True,
        verification_interval=1,
        verification_command=(
            "python3 -c \""
            "from pathlib import Path; "
            f"p = Path('{verify_count_path}'); "
            "n = int(p.read_text()) + 1 if p.exists() else 1; "
            "p.write_text(str(n)); "
            "print(f'verification pass #' + str(n))"
            "\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    events = store.list_events(session.id)
    verification_started_events = [e for e in events if e.event_type == "session.verification_started"]
    verification_passed_events = [e for e in events if e.event_type == "session.verification_passed"]

    assert result.session_status == "idle", f"Expected idle, got {result.session_status}"
    # With interval=1 and 2 tasks (sequential, max_workers=1), interval verification fires
    # after each task (twice). The second interval fires on the last task, so
    # verified_this_iteration=True suppresses the final verification. Total = exactly 2.
    verify_count = int(verify_count_path.read_text())
    assert verify_count == 2, f"Expected exactly 2 verification runs (no double verification), got {verify_count}"
    run_completed_events = [e for e in events if e.event_type == "run.completed"]
    assert len(run_completed_events) == 1
    assert len(verification_passed_events) == 2, (
        f"Expected exactly 2 verification_passed events, got {len(verification_passed_events)}"
    )
    assert len(verification_started_events) == 2


def test_final_verification_runs_when_no_interval_verification_triggered(
    tmp_path: Path,
) -> None:
    """Final verification fires even when the interval threshold was never reached."""
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-final-ver-no-interval",
        name="Final verification no interval",
        pack="final-no-interval-pack",
        created_at="2026-03-11T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", exec_order=1)

    verify_count_path = tmp_path / "verify_count_no_interval.txt"
    pack_root = _write_pack(
        tmp_path,
        name="final-no-interval-pack",
        max_workers=1,
        verification_enabled=True,
        verification_interval=99,  # high — interval verification will NOT fire for 1 task
        verification_command=(
            "python3 -c \""
            "from pathlib import Path; "
            f"p = Path('{verify_count_path}'); "
            "n = int(p.read_text()) + 1 if p.exists() else 1; "
            "p.write_text(str(n)); "
            "print(f'verification pass #' + str(n))"
            "\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    events = store.list_events(session.id)

    assert result.session_status == "idle", f"Expected idle, got {result.session_status}"
    verify_count = int(verify_count_path.read_text())
    # Exactly 1 verification run: the final one (interval threshold=99 never reached with 1 task)
    assert verify_count == 1, f"Expected exactly 1 verification run, got {verify_count}"
    verification_started_events = [e for e in events if e.event_type == "session.verification_started"]
    verification_passed_events = [e for e in events if e.event_type == "session.verification_passed"]
    assert len(verification_started_events) == 1
    assert len(verification_passed_events) == 1


def test_final_verification_failure_engages_auto_fix(
    tmp_path: Path,
) -> None:
    """Final verification failure triggers auto-fix, which then re-verifies and completes."""
    from cognitive_switchyard.models import FixerAttemptResult
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-final-ver-autofix",
        name="Final verification auto-fix",
        pack="final-ver-autofix-pack",
        created_at="2026-03-11T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", exec_order=1)

    verify_flag_path = tmp_path / "final_verify_flag.txt"
    pack_root = _write_pack(
        tmp_path,
        name="final-ver-autofix-pack",
        max_workers=1,
        verification_enabled=True,
        verification_interval=99,
        verification_command=(
            "python3 -c \""
            "from pathlib import Path; "
            f"flag = Path('{verify_flag_path}'); "
            "import sys; "
            "print('pass' if flag.exists() else 'fail'); "
            "sys.exit(0 if flag.exists() else 1)"
            "\""
        ),
        auto_fix_enabled=True,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    fixer_calls: list[int] = []

    def fixer_executor(context):
        fixer_calls.append(context.attempt)
        verify_flag_path.write_text("ok\n", encoding="utf-8")
        return FixerAttemptResult(success=True, summary="Created verify flag.")

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
        fixer_executor=fixer_executor,
    )

    events = store.list_events(session.id)

    assert result.session_status == "idle", f"Expected idle, got {result.session_status}"
    assert len(fixer_calls) == 1, f"Expected 1 fixer call, got {fixer_calls}"
    assert any(e.event_type == "session.verification_failed" for e in events)
    assert any(e.event_type == "session.verification_passed" for e in events)
    assert any(e.event_type == "run.completed" for e in events)


def test_final_verification_failure_without_auto_fix_pauses_session(
    tmp_path: Path,
) -> None:
    """Final verification failure with auto-fix disabled pauses the session."""
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-final-ver-pause",
        name="Final verification pause",
        pack="final-ver-pause-pack",
        created_at="2026-03-11T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", exec_order=1)

    pack_root = _write_pack(
        tmp_path,
        name="final-ver-pause-pack",
        max_workers=1,
        verification_enabled=True,
        verification_interval=99,
        verification_command="python3 -c \"print('verification failed'); raise SystemExit(1)\"",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    events = store.list_events(session.id)

    assert result.session_status == "paused", f"Expected paused, got {result.session_status}"
    assert store.get_session(session.id).status == "paused"
    assert store.get_task(session.id, "001").status == "done"
    assert any(e.event_type == "session.verification_started" for e in events)
    assert any(e.event_type == "session.verification_failed" for e in events)
    assert not any(e.event_type == "session.completed" for e in events)


# --- Regression tests for audit findings ---

def test_dispatch_failure_marks_task_blocked_not_active(tmp_path: Path) -> None:
    """M-1 regression: if manager.dispatch() raises, the task must be blocked (not active)."""
    from unittest.mock import patch

    from cognitive_switchyard.orchestrator import execute_session
    from cognitive_switchyard.worker_manager import WorkerManagerError

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-dispatch-fail",
        name="Dispatch fail test",
        pack="dispatch-fail-pack",
        created_at="2026-03-11T12:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", exec_order=1)

    pack_root = _write_pack(
        tmp_path,
        name="dispatch-fail-pack",
        max_workers=1,
        execute_script_body="""#!/usr/bin/env python3\nimport sys; sys.exit(0)\n""",
    )

    with patch(
        "cognitive_switchyard.worker_manager.WorkerManager.dispatch",
        side_effect=WorkerManagerError("simulated dispatch failure"),
    ):
        result = execute_session(
            store=store,
            session_id=session.id,
            pack_manifest=load_pack_manifest(pack_root),
            poll_interval=0.01,
        )

    task = store.get_task(session.id, "001")
    events = store.list_events(session.id)

    # The task must NOT remain active — it must be blocked.
    assert task.status == "blocked", (
        f"Expected task to be blocked after dispatch failure, got {task.status!r}"
    )
    # A task.blocked event must have been recorded.
    assert any(e.event_type == "task.blocked" for e in events), (
        "Expected a task.blocked event after dispatch failure"
    )
    # The session must not be left with an orphaned active task.
    assert len(store.list_active_tasks(session.id)) == 0, (
        "Orphaned active task found after dispatch failure"
    )


# --- Regression tests for plan 007: timers visible from run start ---


def test_start_session_sets_run_number_and_run_started_at_before_planning_begins(
    tmp_path: Path,
) -> None:
    """run_number >= 1 and run_started_at is not None BEFORE the planner agent runs.

    Regression: previously run_number stayed 0 and run_started_at was None
    until execute_session() ran (after planning), causing TopBar timers to
    be hidden during the planning and resolving phases.
    """
    from cognitive_switchyard.orchestrator import start_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-007-timer-reg",
        name="Timer Regression 007",
        pack="timer-reg-pack",
        created_at="2026-03-12T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.intake / "t01_feature.md").write_text("# Feature\n", encoding="utf-8")

    pack_root = _write_pack(
        tmp_path,
        name="timer-reg-pack",
        planning_enabled=True,
        resolution_executor="passthrough",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_plan_path = Path(sys.argv[1])
        task_id = task_plan_path.name.removesuffix(".plan.md")
        status_path = task_plan_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    # Capture runtime state observed inside the planner agent.
    captured_runtime_state: dict[str, object] = {}

    def planner_agent(*, model: str, prompt_path: Path, intake_path: Path, **_: object) -> str:
        # Inspect runtime state NOW — before planning has returned.
        rs = store.get_session(session.id).runtime_state
        captured_runtime_state["run_number"] = rs.run_number
        captured_runtime_state["run_started_at"] = rs.run_started_at
        task_id = intake_path.stem.split("_")[0]
        return dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            PRIORITY: normal
            ESTIMATED_SCOPE: src/feature.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task {task_id}

            Implement the feature.
            """
        ).lstrip()

    start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        poll_interval=0.01,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert captured_runtime_state.get("run_number", 0) >= 1, (
        "run_number must be >= 1 before planning runs, "
        f"got {captured_runtime_state.get('run_number')!r}. "
        "If this regresses, run bookkeeping moved back to after planning."
    )
    assert captured_runtime_state.get("run_started_at") is not None, (
        "run_started_at must be set before planning runs, "
        f"got {captured_runtime_state.get('run_started_at')!r}. "
        "If this regresses, timers will be hidden during planning/resolving."
    )


def test_new_run_clears_stale_verification_and_auto_fix_fields(tmp_path: Path) -> None:
    """When a new run starts from idle, stale verification/auto-fix runtime fields must be cleared.

    Regression (plan 010): execute_session only reset run_number, run_started_at, and
    completed_since_verification. Stale verification_pending=True caused the pipeline strip
    to stay on "Verify" and the VerificationCard to render incorrectly at the start of a
    new run.
    """
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-010-new-run-reset",
        name="Plan 010 new run reset",
        pack="new-run-reset-pack",
        created_at="2026-03-12T10:00:00Z",
    )

    pack_root = _write_pack(
        tmp_path,
        name="new-run-reset-pack",
        max_workers=1,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path
        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding='utf-8',
        )
        """,
    )

    # Simulate stale state from a previous run: set verification/auto-fix fields as if
    # verification had been triggered and a fix attempt had been made.
    store.update_session_status(session.id, status="idle")
    store.write_session_runtime_state(
        session.id,
        run_number=1,
        run_started_at="2026-03-12T09:00:00Z",
        completed_since_verification=3,
        verification_pending=True,
        verification_reason="interval",
        verification_started_at="2026-03-12T09:05:00Z",
        auto_fix_context="some stale context",
        auto_fix_task_id="task-001",
        auto_fix_attempt=2,
        last_fix_summary="Fixed something in previous run.",
    )

    # Confirm the stale state is in place before calling execute_session.
    stale = store.get_session(session.id).runtime_state
    assert stale.verification_pending is True
    assert stale.auto_fix_attempt == 2

    # No tasks registered — the session immediately goes idle after incrementing the run counter.
    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    assert result.session_status == "idle"

    rs = store.get_session(session.id).runtime_state

    # Core regression assertions: stale verification/auto-fix fields must be cleared.
    assert rs.verification_pending is False, (
        f"verification_pending must be False after new run starts, got {rs.verification_pending!r}. "
        "If this regresses, the pipeline strip will stay on 'Verify' on new runs."
    )
    assert rs.verification_reason is None, f"verification_reason must be None, got {rs.verification_reason!r}"
    assert rs.verification_started_at is None, f"verification_started_at must be None, got {rs.verification_started_at!r}"
    assert rs.auto_fix_context is None, f"auto_fix_context must be None, got {rs.auto_fix_context!r}"
    assert rs.auto_fix_task_id is None, f"auto_fix_task_id must be None, got {rs.auto_fix_task_id!r}"
    assert rs.auto_fix_attempt == 0, f"auto_fix_attempt must be 0, got {rs.auto_fix_attempt!r}"
    assert rs.last_fix_summary is None, f"last_fix_summary must be None, got {rs.last_fix_summary!r}"

    # Run bookkeeping must advance correctly.
    assert rs.run_number == 2, f"run_number must be 2 (incremented from 1), got {rs.run_number!r}"
    assert rs.completed_since_verification == 0, (
        f"completed_since_verification must reset to 0, got {rs.completed_since_verification!r}"
    )


# ---------------------------------------------------------------------------
# Regression: _handle_failed_task must defer isolate_end until after auto-fix
# so the fixer receives a live worktree with partial commits intact.
# ---------------------------------------------------------------------------

def _make_pack_manifest_with_autofix(tmp_path: Path) -> "PackManifest":
    """Return a minimal PackManifest with verification and auto-fix enabled."""
    from cognitive_switchyard.models import (
        AutoFixConfig,
        ExecutionPhaseConfig,
        IsolationConfig,
        PackManifest,
        PhaseConfigSet,
        VerificationConfig,
    )

    return PackManifest(
        root=tmp_path,
        name="test-pack",
        description="regression test pack",
        version="0.0.1",
        phases=PhaseConfigSet(execution=ExecutionPhaseConfig(enabled=True)),
        verification=VerificationConfig(enabled=True, command="echo ok"),
        auto_fix=AutoFixConfig(enabled=True),
        isolation=IsolationConfig(type="none"),
    )


def _make_active_task(plan_path: Path) -> "PersistedTask":
    from cognitive_switchyard.models import PersistedTask

    return PersistedTask(
        session_id="session-reg-001",
        task_id="task-reg-001",
        title="Regression task",
        status="active",
        plan_path=plan_path,
        worker_slot=0,
    )


def _make_effective_runtime_config(*, auto_fix_enabled: bool) -> "EffectiveSessionRuntimeConfig":
    from cognitive_switchyard.models import EffectiveSessionRuntimeConfig

    return EffectiveSessionRuntimeConfig(
        worker_count=1,
        verification_interval=4,
        task_idle=420,
        task_max=0,
        session_max=14400,
        auto_fix_enabled=auto_fix_enabled,
        auto_fix_max_attempts=2,
        poll_interval=0.01,
    )


def test_handle_failed_task_defers_isolate_end_on_autofix_success(tmp_path: Path) -> None:
    """isolate_end must NOT be called before _attempt_task_auto_fix, and must be
    called with final_status='done' and plan_path set when auto-fix succeeds."""
    from unittest.mock import MagicMock, call, patch

    from cognitive_switchyard.orchestrator import _handle_failed_task

    plan_path = tmp_path / "task-reg-001.plan.md"
    plan_path.write_text("plan content\n", encoding="utf-8")

    pack_manifest = _make_pack_manifest_with_autofix(tmp_path)
    active_task = _make_active_task(plan_path)
    effective_runtime_config = _make_effective_runtime_config(auto_fix_enabled=True)

    call_order: list[str] = []
    mock_store = MagicMock()
    mock_store.project_task.return_value = active_task

    def recording_isolate_end(**kwargs):
        call_order.append("isolate_end")
        return True

    def recording_autofix(**kwargs):
        call_order.append("autofix")
        # Assert isolate_end has NOT been called yet — this is the regression guard.
        assert "isolate_end" not in call_order[:-1], (
            "_run_isolate_end was called BEFORE _attempt_task_auto_fix — worktree destroyed too early"
        )
        return True  # auto-fix succeeds

    with (
        patch(
            "cognitive_switchyard.orchestrator._run_isolate_end",
            side_effect=recording_isolate_end,
        ) as mock_isolate_end,
        patch(
            "cognitive_switchyard.orchestrator._attempt_task_auto_fix",
            side_effect=recording_autofix,
        ),
        patch("cognitive_switchyard.orchestrator._finalize_blocked_task") as mock_finalize,
    ):
        _handle_failed_task(
            store=mock_store,
            session_id="session-reg-001",
            pack_manifest=pack_manifest,
            effective_runtime_config=effective_runtime_config,
            active_task=active_task,
            slot_number=0,
            workspace_path=tmp_path / "workspace",
            reason="worker failed",
            log_path=None,
            status_path=None,
            env=None,
            fixer_executor=MagicMock(),
            runtime_event_sink=None,
        )

    # Call order: autofix must precede isolate_end
    assert call_order == ["autofix", "isolate_end"], (
        f"Expected ['autofix', 'isolate_end'], got {call_order}"
    )
    # isolate_end called exactly once with final_status='done' and plan_path set
    assert mock_isolate_end.call_count == 1
    kwargs = mock_isolate_end.call_args.kwargs
    assert kwargs["final_status"] == "done", f"Expected final_status='done', got {kwargs['final_status']!r}"
    assert kwargs["plan_path"] == plan_path, f"Expected plan_path={plan_path!r}, got {kwargs['plan_path']!r}"
    # _finalize_blocked_task must NOT be called when auto-fix succeeds
    mock_finalize.assert_not_called()


def test_handle_failed_task_defers_isolate_end_on_autofix_failure(tmp_path: Path) -> None:
    """isolate_end must NOT be called before _attempt_task_auto_fix, and must be
    called with final_status='blocked' when auto-fix fails; _finalize_blocked_task
    must be called with run_isolation_end=False."""
    from unittest.mock import MagicMock, patch

    from cognitive_switchyard.orchestrator import _handle_failed_task

    plan_path = tmp_path / "task-reg-001.plan.md"
    plan_path.write_text("plan content\n", encoding="utf-8")

    pack_manifest = _make_pack_manifest_with_autofix(tmp_path)
    active_task = _make_active_task(plan_path)
    effective_runtime_config = _make_effective_runtime_config(auto_fix_enabled=True)

    call_order: list[str] = []
    mock_store = MagicMock()
    mock_store.project_task.return_value = active_task

    def recording_isolate_end(**kwargs):
        call_order.append("isolate_end")
        return True

    def recording_autofix(**kwargs):
        call_order.append("autofix")
        assert "isolate_end" not in call_order[:-1], (
            "_run_isolate_end was called BEFORE _attempt_task_auto_fix — worktree destroyed too early"
        )
        return False  # auto-fix fails

    with (
        patch(
            "cognitive_switchyard.orchestrator._run_isolate_end",
            side_effect=recording_isolate_end,
        ) as mock_isolate_end,
        patch(
            "cognitive_switchyard.orchestrator._attempt_task_auto_fix",
            side_effect=recording_autofix,
        ),
        patch("cognitive_switchyard.orchestrator._finalize_blocked_task") as mock_finalize,
    ):
        _handle_failed_task(
            store=mock_store,
            session_id="session-reg-001",
            pack_manifest=pack_manifest,
            effective_runtime_config=effective_runtime_config,
            active_task=active_task,
            slot_number=0,
            workspace_path=tmp_path / "workspace",
            reason="worker failed",
            log_path=None,
            status_path=None,
            env=None,
            fixer_executor=MagicMock(),
            runtime_event_sink=None,
        )

    # Call order: autofix must precede isolate_end
    assert call_order == ["autofix", "isolate_end"], (
        f"Expected ['autofix', 'isolate_end'], got {call_order}"
    )
    # isolate_end called exactly once with final_status='blocked'
    assert mock_isolate_end.call_count == 1
    kwargs = mock_isolate_end.call_args.kwargs
    assert kwargs["final_status"] == "blocked", f"Expected final_status='blocked', got {kwargs['final_status']!r}"
    # _finalize_blocked_task called with run_isolation_end=False (no double-cleanup)
    mock_finalize.assert_called_once()
    finalize_kwargs = mock_finalize.call_args.kwargs
    assert finalize_kwargs.get("run_isolation_end") is False, (
        f"Expected run_isolation_end=False, got {finalize_kwargs.get('run_isolation_end')!r}"
    )


def test_handle_failed_task_no_autofix_calls_finalize_with_isolation(tmp_path: Path) -> None:
    """When auto-fix is disabled, _handle_failed_task delegates entirely to
    _finalize_blocked_task with the default run_isolation_end=True; it must NOT
    call _run_isolate_end directly."""
    from unittest.mock import MagicMock, patch

    from cognitive_switchyard.orchestrator import _handle_failed_task

    plan_path = tmp_path / "task-reg-001.plan.md"
    plan_path.write_text("plan content\n", encoding="utf-8")

    pack_manifest = _make_pack_manifest_with_autofix(tmp_path)
    active_task = _make_active_task(plan_path)
    # auto_fix_enabled=False — skips the auto-fix branch entirely
    effective_runtime_config = _make_effective_runtime_config(auto_fix_enabled=False)

    mock_store = MagicMock()

    with (
        patch("cognitive_switchyard.orchestrator._run_isolate_end") as mock_isolate_end,
        patch("cognitive_switchyard.orchestrator._finalize_blocked_task") as mock_finalize,
    ):
        _handle_failed_task(
            store=mock_store,
            session_id="session-reg-001",
            pack_manifest=pack_manifest,
            effective_runtime_config=effective_runtime_config,
            active_task=active_task,
            slot_number=0,
            workspace_path=tmp_path / "workspace",
            reason="worker failed",
            log_path=None,
            status_path=None,
            env=None,
            fixer_executor=None,
            runtime_event_sink=None,
        )

    # _run_isolate_end must NOT be called directly — it's delegated to _finalize_blocked_task
    mock_isolate_end.assert_not_called()
    # _finalize_blocked_task called once without run_isolation_end kwarg (defaults to True)
    mock_finalize.assert_called_once()
    finalize_kwargs = mock_finalize.call_args.kwargs
    assert "run_isolation_end" not in finalize_kwargs or finalize_kwargs["run_isolation_end"] is True, (
        f"Expected run_isolation_end to be absent or True, got {finalize_kwargs.get('run_isolation_end')!r}"
    )


def test_task_lifecycle_events_include_task_id_and_title(
    tmp_path: Path,
) -> None:
    """task.dispatched and task.completed messages must include task ID and title.

    Regression guard: ensures future refactors cannot silently revert to generic
    anonymous messages, breaking operator log correlation.
    """
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-reg-008",
        name="Regression 008 identity",
        pack="reg-008-pack",
        created_at="2026-03-16T00:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="008", title="Fix auth")

    pack_root = _write_pack(
        tmp_path,
        name="reg-008-pack",
        isolation_type="temp-directory",
        isolate_start=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        slot, task_id, session_root = sys.argv[1:4]
        workspace = Path(session_root) / "isolated" / task_id
        workspace.mkdir(parents=True, exist_ok=True)
        print(workspace)
        """,
        isolate_end="""
        #!/usr/bin/env python3
        """,
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
        status_path.write_text("STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n", encoding='utf-8')
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
    )

    assert result.session_status == "idle"

    events = store.list_events(session.id)
    dispatched_event = next(e for e in events if e.event_type == "task.dispatched")
    completed_event = next(e for e in events if e.event_type == "task.completed")

    assert "008" in dispatched_event.message, (
        f"task.dispatched message must contain the task ID '008', got: {dispatched_event.message!r}"
    )
    assert "Fix auth" in dispatched_event.message, (
        f"task.dispatched message must contain the task title 'Fix auth', got: {dispatched_event.message!r}"
    )
    assert "008" in completed_event.message, (
        f"task.completed message must contain the task ID '008', got: {completed_event.message!r}"
    )
    assert "Fix auth" in completed_event.message, (
        f"task.completed message must contain the task title 'Fix auth', got: {completed_event.message!r}"
    )


def test_idle_session_with_new_intake_runs_planning(tmp_path: Path) -> None:
    """When an idle session has new intake files and start_session is called,
    the planning phase must run and the intake file must be claimed and planned.

    Regression: idle was in the early-return set of start_session(), which
    short-circuited into execute_session() and bypassed planning entirely.
    """
    from cognitive_switchyard.orchestrator import start_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-003-idle-plan",
        name="Idle planning test",
        pack="idle-plan-pack",
        created_at="2026-03-09T10:00:00Z",
    )

    pack_root = _write_pack(
        tmp_path,
        name="idle-plan-pack",
        planning_enabled=True,
        resolution_executor="passthrough",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_plan_path = Path(sys.argv[1])
        task_id = task_plan_path.name.removesuffix(".plan.md")
        print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
        status_path = task_plan_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    # First run: complete a task to reach idle state.
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.intake / "070_first.md").write_text("# First\n", encoding="utf-8")

    def planner_agent(*, model: str, prompt_path: Path, intake_path: Path, **_: object) -> str:
        task_id = intake_path.stem.split("_")[0]
        return dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            PRIORITY: normal
            ESTIMATED_SCOPE: src/feature.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task {task_id}

            Implement the feature.
            """
        ).lstrip()

    result = start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        poll_interval=0.01,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )
    assert result.started is True
    assert result.session_status == "idle"

    # Now add new intake and call start_session again from idle.
    (session_paths.intake / "071_second.md").write_text("# Second\n", encoding="utf-8")

    result2 = start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        poll_interval=0.01,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result2.started is True, "idle session with new intake must start successfully"
    assert result2.session_status == "idle"
    assert (session_paths.done / "071.plan.md").exists(), "new intake file must be planned and executed"
    rs = store.get_session(session.id).runtime_state
    assert rs.run_number == 2, f"run_number must be 2 after second run, got {rs.run_number}"


def test_idle_session_with_no_intake_stays_idle(tmp_path: Path) -> None:
    """When an idle session has no new intake files, start_session must return
    started=False and the session must remain idle.

    Regression: idle sessions previously short-circuited into execute_session()
    which would find no tasks, increment run counters, and then go idle — wasting
    a run cycle.
    """
    from cognitive_switchyard.orchestrator import start_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-003-idle-noop",
        name="Idle noop test",
        pack="idle-noop-pack",
        created_at="2026-03-09T10:00:00Z",
    )

    pack_root = _write_pack(
        tmp_path,
        name="idle-noop-pack",
        planning_enabled=True,
        resolution_executor="passthrough",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_plan_path = Path(sys.argv[1])
        task_id = task_plan_path.name.removesuffix(".plan.md")
        status_path = task_plan_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    # Set session to idle with run_number=1, no intake files.
    store.update_session_status(session.id, status="idle")
    store.write_session_runtime_state(
        session.id,
        run_number=1,
        run_started_at="2026-03-09T10:00:00Z",
        completed_since_verification=0,
    )

    result = start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        poll_interval=0.01,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result.started is False, "idle session with no intake must not start"
    assert result.session_status == "idle", "session must remain idle"
    rs = store.get_session(session.id).runtime_state
    assert rs.run_number == 1, f"run_number must stay 1 when no work exists, got {rs.run_number}"


def test_idle_session_run_counter_increments(tmp_path: Path) -> None:
    """When an idle session starts a new run with intake files, the run_number
    must increment and run_started_at must be refreshed."""
    from cognitive_switchyard.orchestrator import start_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-003-idle-counter",
        name="Idle counter test",
        pack="idle-counter-pack",
        created_at="2026-03-09T10:00:00Z",
    )

    pack_root = _write_pack(
        tmp_path,
        name="idle-counter-pack",
        planning_enabled=True,
        resolution_executor="passthrough",
        execute_script_body="""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        task_plan_path = Path(sys.argv[1])
        task_id = task_plan_path.name.removesuffix(".plan.md")
        status_path = task_plan_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    # Set to idle with run_number=3 and an old timestamp.
    store.update_session_status(session.id, status="idle")
    store.write_session_runtime_state(
        session.id,
        run_number=3,
        run_started_at="2026-03-09T08:00:00Z",
        completed_since_verification=0,
    )
    old_run_started_at = store.get_session(session.id).runtime_state.run_started_at

    # Add intake file so planning will run.
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.intake / "080_counter.md").write_text("# Counter\n", encoding="utf-8")

    def planner_agent(*, model: str, prompt_path: Path, intake_path: Path, **_: object) -> str:
        task_id = intake_path.stem.split("_")[0]
        return dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            PRIORITY: normal
            ESTIMATED_SCOPE: src/feature.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task {task_id}

            Implement the feature.
            """
        ).lstrip()

    result = start_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        poll_interval=0.01,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result.started is True
    rs = store.get_session(session.id).runtime_state
    assert rs.run_number == 4, f"run_number must be 4 after incrementing from 3, got {rs.run_number}"
    assert rs.run_started_at != old_run_started_at, "run_started_at must be refreshed"
