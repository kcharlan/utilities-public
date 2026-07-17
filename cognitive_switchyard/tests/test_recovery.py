from __future__ import annotations

import os
import signal
import subprocess
import time
import unittest.mock
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.models import TaskPlan
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _write_script(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(contents).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def _write_pack(
    tmp_path: Path,
    *,
    name: str,
    isolation_type: str = "temp-directory",
    isolate_start: str | None = None,
    isolate_end: str | None = None,
    sidecar_format: str = "key-value",
    verification_enabled: bool = False,
    verification_interval: int = 4,
    verification_command: str | None = None,
    auto_fix_enabled: bool = False,
    execute_script_body: str | None = None,
) -> Path:
    pack_root = tmp_path / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    isolation_lines = ["isolation:", f"  type: {isolation_type}"]
    if isolate_start is not None:
        _write_script(scripts_dir / "isolate_start.py", isolate_start)
        isolation_lines.append("  setup: scripts/isolate_start.py")
    if isolate_end is not None:
        _write_script(scripts_dir / "isolate_end.py", isolate_end)
        isolation_lines.append("  teardown: scripts/isolate_end.py")

    execute_body = execute_script_body or """
    #!/usr/bin/env python3
    import sys
    from pathlib import Path

    task_path = Path(sys.argv[1])
    status_path = task_path.with_name(task_path.name.removesuffix('.plan.md') + '.status')
    status_path.write_text(
        'STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n',
        encoding='utf-8',
    )
    """
    _write_script(scripts_dir / "execute.py", execute_body)

    manifest_lines = [
        f"name: {name}",
        "description: Recovery test pack.",
        "version: 1.2.3",
        "",
        "status:",
        "  progress_format: '##PROGRESS##'",
        f"  sidecar_format: {sidecar_format}",
        "",
        "phases:",
        "  execution:",
        "    enabled: true",
        "    executor: shell",
        "    command: scripts/execute.py",
        "    max_workers: 1",
    ]
    if verification_enabled:
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
        prompts_dir = pack_root / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
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
            "  task_idle: 5",
            "  task_max: 0",
            "  session_max: 60",
            "",
            *isolation_lines,
            "",
        ]
    )
    (pack_root / "pack.yaml").write_text(
        "\n".join(manifest_lines),
        encoding="utf-8",
    )
    return pack_root


def _register_task(
    store: StateStore,
    *,
    session_id: str,
    task_id: str,
    depends_on: tuple[str, ...] = (),
) -> None:
    store.register_task_plan(
        session_id=session_id,
        plan=TaskPlan(task_id=task_id, title=f"Task {task_id}", depends_on=depends_on),
        plan_text=dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            DEPENDS_ON: {", ".join(depends_on) if depends_on else "none"}
            ANTI_AFFINITY: none
            EXEC_ORDER: 1
            FULL_TEST_AFTER: no
            ---

            # Plan: Task {task_id}
            """
        ).lstrip(),
        created_at="2026-03-09T10:00:00Z",
    )


def _status_path(plan_path: Path) -> Path:
    return plan_path.with_name(plan_path.name.removesuffix(".plan.md") + ".status")


def _timestamp_offset(*, seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _wait_for_exit(pid: int, *, deadline_seconds: float = 3.0) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            waited_pid, _status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == pid:
                return
        except ChildProcessError:
            return
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.02)
    raise AssertionError(f"process {pid} did not exit before deadline")


def _spawn_reparented_sleeper() -> int:
    launcher = subprocess.run(
        [
            "python3",
            "-c",
            dedent(
                """
                import subprocess

                sleeper = subprocess.Popen(
                    ["python3", "-c", "import time; time.sleep(60)"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                print(sleeper.pid, flush=True)
                """
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(launcher.stdout.strip())


def _wait_for_non_child_exit(pid: int, *, deadline_seconds: float = 3.0) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.02)
    raise AssertionError(f"non-child process {pid} did not exit before deadline")


def test_recover_done_worker_promotes_task_to_done_and_runs_isolate_end(tmp_path: Path) -> None:
    from cognitive_switchyard.recovery import recover_execution_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-done",
        name="Packet 07 done recovery",
        pack="recovery-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="101")
    active_task = store.project_task(
        session.id,
        "101",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="running")

    marker_path = tmp_path / "recovery-done.log"
    workspace_path = runtime_paths.session_paths(session.id).root / "workspace" / "101"
    workspace_path.mkdir(parents=True, exist_ok=True)
    pack_root = _write_pack(
        tmp_path,
        name="recovery-pack",
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
    )
    status_path = _status_path(active_task.plan_path)
    status_path.write_text(
        "STATUS: done\nCOMMITS: abc1234\nTESTS_RAN: targeted\nTEST_RESULT: pass\n",
        encoding="utf-8",
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="101",
        workspace_path=workspace_path,
        pid=None,
    )

    result = recover_execution_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    recovered = store.get_task(session.id, "101")
    slot_rows = store.list_worker_slots(session.id)

    assert result.preserved_done_task_ids == ("101",)
    assert result.reverted_ready_task_ids == ()
    assert recovered.status == "done"
    assert recovered.plan_path == runtime_paths.session_paths(session.id).done / "101.plan.md"
    assert marker_path.read_text(encoding="utf-8").strip() == f"0|101|{workspace_path}|done"
    assert not runtime_paths.session_paths(session.id).worker_recovery_path(0).exists()
    assert slot_rows == (
        store.list_worker_slots(session.id)[0].__class__(
            session_id=session.id,
            slot_number=0,
            status="idle",
            current_task_id=None,
        ),
    )


def test_recover_done_worker_supports_json_status_sidecar(tmp_path: Path) -> None:
    from cognitive_switchyard.recovery import recover_execution_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-json-done",
        name="Packet 07 json done recovery",
        pack="json-recovery-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="111")
    active_task = store.project_task(
        session.id,
        "111",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="running")

    workspace_path = runtime_paths.session_paths(session.id).root / "workspace" / "111"
    workspace_path.mkdir(parents=True, exist_ok=True)
    pack_root = _write_pack(tmp_path, name="json-recovery-pack", sidecar_format="json")
    status_path = _status_path(active_task.plan_path)
    status_path.write_text(
        '{"status":"done","commits":"abc1234","tests_ran":"targeted","test_result":"pass"}',
        encoding="utf-8",
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="111",
        workspace_path=workspace_path,
        pid=None,
    )

    result = recover_execution_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.preserved_done_task_ids == ("111",)
    assert store.get_task(session.id, "111").status == "done"


def test_recover_incomplete_worker_returns_task_to_ready_and_clears_slot_projection(tmp_path: Path) -> None:
    from cognitive_switchyard.recovery import recover_execution_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-incomplete",
        name="Packet 07 incomplete recovery",
        pack="incomplete-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="102")
    store.project_task(
        session.id,
        "102",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="running")

    marker_path = tmp_path / "recovery-incomplete.log"
    workspace_path = runtime_paths.session_paths(session.id).root / "workspace" / "102"
    workspace_path.mkdir(parents=True, exist_ok=True)
    pack_root = _write_pack(
        tmp_path,
        name="incomplete-pack",
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
    )
    process = subprocess.Popen(
        ["python3", "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="102",
        workspace_path=workspace_path,
        pid=process.pid,
    )

    result = recover_execution_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        kill_grace_period=0.05,
    )

    _wait_for_exit(process.pid)
    recovered = store.get_task(session.id, "102")
    slot_row = store.list_worker_slots(session.id)[0]

    assert result.preserved_done_task_ids == ()
    assert result.reverted_ready_task_ids == ("102",)
    assert recovered.status == "ready"
    assert recovered.plan_path == runtime_paths.session_paths(session.id).ready / "102.plan.md"
    assert marker_path.read_text(encoding="utf-8").strip() == f"0|102|{workspace_path}|blocked"
    assert slot_row.status == "idle"
    assert slot_row.current_task_id is None
    assert not runtime_paths.session_paths(session.id).worker_recovery_path(0).exists()


def test_recover_incomplete_worker_terminates_reparented_orphan_process(tmp_path: Path) -> None:
    from cognitive_switchyard.recovery import recover_execution_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-orphan-pid",
        name="Packet 07 orphan pid recovery",
        pack="orphan-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="102b")
    store.project_task(
        session.id,
        "102b",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="running")

    marker_path = tmp_path / "recovery-orphan.log"
    workspace_path = runtime_paths.session_paths(session.id).root / "workspace" / "102b"
    workspace_path.mkdir(parents=True, exist_ok=True)
    pack_root = _write_pack(
        tmp_path,
        name="orphan-pack",
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
    )
    orphan_pid = _spawn_reparented_sleeper()
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="102b",
        workspace_path=workspace_path,
        pid=orphan_pid,
    )

    recover_execution_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        kill_grace_period=0.05,
    )

    _wait_for_non_child_exit(orphan_pid)
    assert store.get_task(session.id, "102b").status == "ready"
    assert marker_path.read_text(encoding="utf-8").strip() == f"0|102b|{workspace_path}|blocked"


def test_recover_blocked_or_malformed_sidecar_treats_work_as_incomplete_and_records_warning(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.recovery import recover_execution_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-warning",
        name="Packet 07 warning recovery",
        pack="warning-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="103")
    _register_task(store, session_id=session.id, task_id="104")
    blocked_task = store.project_task(
        session.id,
        "103",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    malformed_task = store.project_task(
        session.id,
        "104",
        status="active",
        worker_slot=1,
        timestamp="2026-03-09T10:01:05Z",
    )
    store.update_session_status(session.id, status="running")

    marker_path = tmp_path / "recovery-warning.log"
    pack_root = _write_pack(
        tmp_path,
        name="warning-pack",
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
    )
    _status_path(blocked_task.plan_path).write_text(
        "STATUS: blocked\nCOMMITS: none\nTESTS_RAN: targeted\nTEST_RESULT: skip\nBLOCKED_REASON: worker failed\n",
        encoding="utf-8",
    )
    _status_path(malformed_task.plan_path).write_text(
        "STATUS: done\nCOMMITS:\n",
        encoding="utf-8",
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="103",
        workspace_path=runtime_paths.session_paths(session.id).root / "workspace" / "103",
        pid=None,
    )
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=1,
        task_id="104",
        workspace_path=runtime_paths.session_paths(session.id).root / "workspace" / "104",
        pid=None,
    )

    result = recover_execution_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    events = store.list_events(session.id)
    warnings = [event for event in events if event.event_type == "session.recovery_warning"]

    assert result.reverted_ready_task_ids == ("103", "104")
    assert store.get_task(session.id, "103").status == "ready"
    assert store.get_task(session.id, "104").status == "ready"
    assert len(warnings) == 2
    assert "STATUS: blocked" in warnings[0].message
    assert "malformed" in warnings[1].message
    assert marker_path.read_text(encoding="utf-8").splitlines() == [
        f"0|103|{runtime_paths.session_paths(session.id).root / 'workspace' / '103'}|blocked",
        f"1|104|{runtime_paths.session_paths(session.id).root / 'workspace' / '104'}|blocked",
    ]


def test_reconcile_filesystem_resets_task_and_worker_rows_to_match_plan_locations(tmp_path: Path) -> None:
    from cognitive_switchyard.recovery import reconcile_filesystem_projection

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-07-reconcile",
        name="Packet 07 reconcile",
        pack="reconcile-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="201")
    _register_task(store, session_id=session.id, task_id="202")
    _register_task(store, session_id=session.id, task_id="203")

    store.project_task(
        session.id,
        "201",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.project_task(
        session.id,
        "202",
        status="done",
        timestamp="2026-03-09T10:01:00Z",
    )

    with store._connect() as connection:
        connection.execute(
            "UPDATE tasks SET status = ?, worker_slot = ?, plan_relpath = ? WHERE session_id = ? AND task_id = ?",
            ("active", 7, "workers/7/201.plan.md", session.id, "201"),
        )
        connection.execute(
            "UPDATE tasks SET status = ?, worker_slot = ?, plan_relpath = ? WHERE session_id = ? AND task_id = ?",
            ("active", 9, "workers/9/202.plan.md", session.id, "202"),
        )
        connection.execute(
            "INSERT INTO worker_slots (session_id, slot_number, status, current_task_id) VALUES (?, ?, ?, ?)",
            (session.id, 9, "active", "202"),
        )
        connection.commit()

    runtime_paths.session_paths(session.id).done.joinpath("202.plan.md").replace(
        runtime_paths.session_paths(session.id).ready / "202.plan.md"
    )
    (runtime_paths.session_paths(session.id).workers / "1").mkdir(parents=True, exist_ok=True)
    runtime_paths.session_paths(session.id).workers.joinpath("0", "201.plan.md").replace(
        runtime_paths.session_paths(session.id).workers / "1" / "201.plan.md"
    )
    runtime_paths.session_paths(session.id).ready.joinpath("203.plan.md").replace(
        runtime_paths.session_paths(session.id).done / "203.plan.md"
    )

    reconcile_filesystem_projection(
        store=store,
        session_id=session.id,
        session_status="running",
    )

    assert store.get_task(session.id, "201").status == "active"
    assert store.get_task(session.id, "201").worker_slot == 1
    assert store.get_task(session.id, "202").status == "ready"
    assert store.get_task(session.id, "202").worker_slot is None
    assert store.get_task(session.id, "203").status == "done"
    assert store.get_session(session.id).status == "running"
    assert [(slot.slot_number, slot.status, slot.current_task_id) for slot in store.list_worker_slots(session.id)] == [
        (0, "idle", None),
        (1, "active", "201"),
        (9, "idle", None),
    ]


def test_restart_from_verifying_or_auto_fixing_replays_verification_without_duplicate_done_projection(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-restart-verifying",
        name="Packet 09 restart verifying",
        pack="restart-verifying-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="301")
    _register_task(store, session_id=session.id, task_id="302")
    store.project_task(
        session.id,
        "301",
        status="done",
        timestamp="2026-03-09T10:02:00Z",
    )
    store.write_session_runtime_state(
        session.id,
        completed_since_verification=1,
        verification_pending=True,
        verification_reason="interval",
    )
    store.update_session_status(
        session.id,
        status="verifying",
        started_at=_timestamp_offset(seconds=-2),
    )

    verify_count_path = tmp_path / "verify-count.txt"
    pack_root = _write_pack(
        tmp_path,
        name="restart-verifying-pack",
        isolation_type="none",
        verification_enabled=True,
        verification_interval=1,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "count_path = Path(os.environ['VERIFY_COUNT']); "
            "count = int(count_path.read_text(encoding='utf-8') or '0') if count_path.exists() else 0; "
            "count += 1; count_path.write_text(str(count), encoding='utf-8'); "
            "print('verification ok')\""
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
        env={"VERIFY_COUNT": str(verify_count_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    events = store.list_events(session.id)

    assert result.session_status == "idle"
    assert {task.task_id for task in store.list_done_tasks(session.id)} == {"301", "302"}
    # With interval=1: (1) replayed pending interval verification, (2) interval verification
    # after task 302 completes. The second interval fires on the last task →
    # verified_this_iteration=True suppresses the final verification. Total = 2.
    assert verify_count_path.read_text(encoding="utf-8") == "2"
    assert [event.task_id for event in events if event.event_type == "task.completed"] == ["302"]


def test_restart_from_auto_fixing_task_failure_replays_verification_and_keeps_task_context(
    tmp_path: Path,
) -> None:
    from cognitive_switchyard.models import FixerAttemptResult
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-restart-auto-fixing-task",
        name="Packet 09 restart auto-fixing task failure",
        pack="restart-auto-fixing-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="401")
    _register_task(store, session_id=session.id, task_id="402", depends_on=("401",))
    store.write_session_runtime_state(
        session.id,
        verification_pending=True,
        verification_reason="task_auto_fix",
        auto_fix_context="task_failure",
        auto_fix_task_id="401",
        auto_fix_attempt=1,
        last_fix_summary="Attempted fix one.",
    )
    store.update_session_status(
        session.id,
        status="auto_fixing",
        started_at=_timestamp_offset(seconds=-2),
    )

    verify_flag_path = runtime_paths.session_paths(session.id).root / "verify.ok"
    trace_path = tmp_path / "restart-auto-fixing-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="restart-auto-fixing-pack",
        isolation_type="none",
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
        trace_path = Path(os.environ["RECOVERY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"run:{task_id}\\n")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        """,
    )

    fixer_contexts: list[tuple[str, str | None, int, str | None, str | None]] = []

    def fixer_executor(context):
        fixer_contexts.append(
            (
                context.context_type,
                context.task_id,
                context.attempt,
                context.previous_attempt_summary,
                context.verification_output,
            )
        )
        verify_flag_path.write_text("ok\n", encoding="utf-8")
        return FixerAttemptResult(success=True, summary="Created verify flag.")

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={
            "PATH": os.environ["PATH"],
            "VERIFY_FLAG": str(verify_flag_path),
            "RECOVERY_TRACE": str(trace_path),
        },
        poll_interval=0.01,
        fixer_executor=fixer_executor,
    )

    completed_events = [event.task_id for event in store.list_events(session.id) if event.event_type == "task.completed"]

    assert result.session_status == "idle"
    assert store.get_task(session.id, "401").status == "done"
    assert store.get_task(session.id, "402").status == "done"
    assert fixer_contexts == [
        (
            "task_failure",
            "401",
            2,
            "Previous fixer summary:\nAttempted fix one.\n\n"
            "Try a DIFFERENT approach. The previous fixer's changes are already committed.",
            "verification-fail\n",
        ),
    ]
    assert trace_path.read_text(encoding="utf-8").splitlines() == ["run:402"]
    assert completed_events == ["401", "402"]


def test_cleanup_orphaned_workspaces_removes_workspace_when_plan_file_missing(tmp_path: Path) -> None:
    """When recovery metadata exists but no plan file is in the worker slot,
    ``cleanup_orphaned_workspaces`` should run ``isolate_end`` with status
    ``blocked`` and clear the metadata."""
    from cognitive_switchyard.recovery import recover_execution_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-orphan-ws",
        name="Orphan workspace recovery",
        pack="orphan-ws-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="501")
    store.project_task(
        session.id,
        "501",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="running")

    marker_path = tmp_path / "orphan-ws-cleanup.log"
    workspace_path = runtime_paths.session_paths(session.id).root / "workspace" / "501"
    workspace_path.mkdir(parents=True, exist_ok=True)

    pack_root = _write_pack(
        tmp_path,
        name="orphan-ws-pack",
        isolate_end=f"""
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        marker = Path({str(marker_path)!r})
        with marker.open('a', encoding='utf-8') as handle:
            handle.write("|".join(sys.argv[1:5]) + "\\n")
        """,
    )

    # Write recovery metadata pointing to the workspace.  The plan file was
    # projected into the worker slot by ``project_task`` above; delete it to
    # simulate a hard crash where the plan was lost but the workspace and
    # recovery metadata survived.
    worker_dir = runtime_paths.session_paths(session.id).worker_dir(0)
    for plan in worker_dir.glob("*.plan.md"):
        plan.unlink()
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="501",
        workspace_path=workspace_path,
        pid=None,
    )
    # Verify there is NO plan file in the worker directory.
    assert list(worker_dir.glob("*.plan.md")) == []

    result = recover_execution_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    # isolate_end should have been called with "blocked"
    assert marker_path.exists()
    marker_lines = marker_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(marker_lines) == 1
    assert f"0|501|{workspace_path}|blocked" == marker_lines[0]

    # Recovery metadata should be cleared
    assert not runtime_paths.session_paths(session.id).worker_recovery_path(0).exists()

    # A warning should be recorded
    assert any("orphaned workspace" in w for w in result.warnings)

    events = store.list_events(session.id)
    orphan_events = [e for e in events if "orphaned workspace" in (e.message or "")]
    assert len(orphan_events) == 1


def test_cleanup_orphaned_workspaces_falls_back_to_rmtree_when_isolate_end_fails(
    tmp_path: Path,
) -> None:
    """When ``isolate_end`` fails for an orphaned workspace, the workspace
    should be forcibly removed via ``shutil.rmtree`` if it is under the
    session root."""
    from cognitive_switchyard.recovery import recover_execution_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-orphan-rmtree",
        name="Orphan workspace rmtree fallback",
        pack="orphan-rmtree-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="601")
    store.project_task(
        session.id,
        "601",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )
    store.update_session_status(session.id, status="running")

    workspace_path = runtime_paths.session_paths(session.id).root / "workspace" / "601"
    workspace_path.mkdir(parents=True, exist_ok=True)
    (workspace_path / "leftover.txt").write_text("data\n", encoding="utf-8")

    pack_root = _write_pack(
        tmp_path,
        name="orphan-rmtree-pack",
        isolate_end="""
        #!/usr/bin/env python3
        import sys
        sys.exit(1)
        """,
    )

    worker_dir = runtime_paths.session_paths(session.id).worker_dir(0)
    # Remove plan file projected by project_task to simulate lost plan.
    for plan in worker_dir.glob("*.plan.md"):
        plan.unlink()
    store.write_worker_recovery_metadata(
        session.id,
        slot_number=0,
        task_id="601",
        workspace_path=workspace_path,
        pid=None,
    )

    result = recover_execution_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    # Workspace should have been removed by rmtree fallback
    assert not workspace_path.exists()

    # Recovery metadata should be cleared
    assert not runtime_paths.session_paths(session.id).worker_recovery_path(0).exists()

    # Warning should mention both orphaned workspace and forcible removal
    assert any("orphaned workspace" in w and "forcibly removed" in w for w in result.warnings)


def test_cleanup_orphaned_workspaces_noop_for_isolation_none(tmp_path: Path) -> None:
    """When isolation type is ``none``, orphan cleanup should be a no-op."""
    from cognitive_switchyard.recovery import recover_execution_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-orphan-noop",
        name="Orphan noop for isolation none",
        pack="orphan-noop-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="701")
    store.update_session_status(session.id, status="running")

    pack_root = _write_pack(
        tmp_path,
        name="orphan-noop-pack",
        isolation_type="none",
    )

    result = recover_execution_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.warnings == ()


# --- Regression tests for code-audit fixes ---


def test_f7_recovery_continues_when_metadata_clear_fails(
    tmp_path: Path,
) -> None:
    """F-7 regression: clear_worker_recovery_metadata failure must not abort the recovery loop;
    the task must still be moved to the correct target status."""
    from cognitive_switchyard.recovery import recover_execution_session

    store, runtime_paths = _build_store(tmp_path)
    pack_root = _write_pack(tmp_path, name="f7-pack", isolation_type="none")
    session = store.create_session(
        session_id="session-f7",
        name="F7 session",
        pack="f7-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    # Place a task in worker slot 0 with a valid "done" status sidecar
    _register_task(store, session_id="session-f7", task_id="f7-task")
    store.project_task("session-f7", "f7-task", status="active", worker_slot=0)
    worker_dir = runtime_paths.session_paths("session-f7").worker_dir(0)
    plan_path = worker_dir / "f7-task.plan.md"
    _status_path(plan_path).write_text(
        "STATUS: done\nCOMMITS: abc123\nTESTS_RAN: full\nTEST_RESULT: pass\n",
        encoding="utf-8",
    )
    store.write_worker_recovery_metadata(
        "session-f7",
        slot_number=0,
        task_id="f7-task",
        workspace_path=worker_dir,
        pid=None,
    )

    # Patch clear_worker_recovery_metadata on the class to raise an OSError.
    # StateStore is a frozen dataclass so instance-level patching is not possible.
    with unittest.mock.patch.object(
        type(store), "clear_worker_recovery_metadata", side_effect=OSError("disk full")
    ):
        result = recover_execution_session(
            store=store,
            session_id="session-f7",
            pack_manifest=load_pack_manifest(pack_root),
        )

    # Task must have been preserved as done despite the clear failure
    assert "f7-task" in result.preserved_done_task_ids
    task = store.get_task("session-f7", "f7-task")
    assert task.status == "done"
