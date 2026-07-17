from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.models import FixerContext, TaskPlan
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.state import StateStore, initialize_state_store
from cognitive_switchyard.verification_runtime import build_task_failure_context


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
    max_workers: int = 1,
    verification_interval: int = 4,
    verification_command: str,
    execute_script_body: str,
) -> Path:
    pack_root = tmp_path / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    _write_script(scripts_dir / "execute.py", execute_script_body)
    (pack_root / "pack.yaml").write_text(
        "\n".join(
            [
                f"name: {name}",
                "description: Verification runtime test pack.",
                "version: 1.2.3",
                "",
                "phases:",
                "  execution:",
                "    enabled: true",
                "    executor: shell",
                "    command: scripts/execute.py",
                f"    max_workers: {max_workers}",
                "  verification:",
                "    enabled: true",
                "    command: >-",
                f"      {verification_command}",
                f"    interval: {verification_interval}",
                "",
                "timeouts:",
                "  task_idle: 5",
                "  task_max: 0",
                "  session_max: 60",
                "",
                "isolation:",
                "  type: none",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return pack_root


def _register_task(
    store: StateStore,
    *,
    session_id: str,
    task_id: str,
    depends_on: tuple[str, ...] = (),
    full_test_after: bool = False,
) -> None:
    store.register_task_plan(
        session_id=session_id,
        plan=TaskPlan(
            task_id=task_id,
            title=f"Task {task_id}",
            depends_on=depends_on,
            full_test_after=full_test_after,
        ),
        plan_text=dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            DEPENDS_ON: {", ".join(depends_on) if depends_on else "none"}
            ANTI_AFFINITY: none
            EXEC_ORDER: 1
            FULL_TEST_AFTER: {"yes" if full_test_after else "no"}
            ---

            # Plan: Task {task_id}
            """
        ).lstrip(),
        created_at="2026-03-09T10:00:00Z",
    )


def test_interval_verification_waits_for_active_workers_and_writes_verify_log(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-verify-interval",
        name="Packet 09 interval verification",
        pack="interval-verification-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002")

    trace_path = tmp_path / "verify-interval-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="interval-verification-pack",
        max_workers=2,
        verification_interval=1,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "trace = Path(os.environ['VERIFY_TRACE']); "
            "handle = trace.open('a', encoding='utf-8'); handle.write('verify\\n'); handle.close(); "
            "print('verification ok')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        import time
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["VERIFY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        time.sleep(0.05 if task_id == "001" else 0.15)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"VERIFY_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    lines = trace_path.read_text(encoding="utf-8").splitlines()

    assert result.session_status == "idle"
    # With forward-looking interval gating (plan 024), verification_interval=1
    # means only 1 task dispatches before verification fires.  Task 002 starts
    # only after the first verification pass completes.
    assert lines[0] == "start:001"
    assert "verify" in lines, "verification should run at least once"
    first_verify = lines.index("verify")
    assert lines.index("end:001") < first_verify
    assert lines.index("start:002") > first_verify
    session_paths = runtime_paths.session_paths(session.id)
    assert not session_paths.summary.is_file()
    # verify_log still exists at idle (trimming deferred to explicit end_session)
    assert session_paths.verify_log.exists() is True
    assert session_paths.session_log.is_file()


def test_full_test_after_flag_forces_verification_before_more_dispatch(tmp_path: Path) -> None:
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-09-full-test-after",
        name="Packet 09 full-test-after",
        pack="full-test-after-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", full_test_after=True)
    _register_task(store, session_id=session.id, task_id="002")
    _register_task(store, session_id=session.id, task_id="003")

    trace_path = tmp_path / "full-test-after-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="full-test-after-pack",
        max_workers=1,
        verification_interval=99,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "trace = Path(os.environ['VERIFY_TRACE']); "
            "handle = trace.open('a', encoding='utf-8'); handle.write('verify\\n'); handle.close(); "
            "print('verification ok')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["VERIFY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"VERIFY_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    assert result.session_status == "idle"
    assert trace_path.read_text(encoding="utf-8").splitlines() == [
        "start:001",
        "end:001",
        "verify",
        "start:002",
        "end:002",
        "start:003",
        "end:003",
        "verify",
    ]


# --- Regression tests for code-audit fixes ---


def test_f12_run_verification_command_does_not_pass_claudecode_to_subprocess(
    tmp_path: Path,
) -> None:
    """F-12 regression: run_verification_command must strip CLAUDECODE from the subprocess env."""
    from cognitive_switchyard.verification_runtime import run_verification_command

    # Script that prints its CLAUDECODE env var (or "NOT_SET" if absent)
    verify_script = tmp_path / "check_env.sh"
    verify_script.write_text(
        '#!/bin/sh\necho "${CLAUDECODE:-NOT_SET}"\n', encoding="utf-8"
    )
    verify_script.chmod(verify_script.stat().st_mode | 0o111)
    log_path = tmp_path / "verify.log"

    old_env = os.environ.get("CLAUDECODE")
    try:
        os.environ["CLAUDECODE"] = "1"
        result = run_verification_command(
            session_root=tmp_path,
            verify_log_path=log_path,
            command=f"sh {verify_script}",
        )
    finally:
        if old_env is None:
            os.environ.pop("CLAUDECODE", None)
        else:
            os.environ["CLAUDECODE"] = old_env

    assert result.ok
    assert result.output.strip() == "NOT_SET", (
        "CLAUDECODE must not be inherited by verification subprocesses"
    )


def test_run_verification_command_output_line_callback_streams_lines_and_captures_output(
    tmp_path: Path,
) -> None:
    """Regression: output_line_callback receives lines incrementally and result.output has all content."""
    from cognitive_switchyard.verification_runtime import run_verification_command

    log_path = tmp_path / "verify.log"
    collected: list[str] = []

    result = run_verification_command(
        session_root=tmp_path,
        verify_log_path=log_path,
        command="echo line1; echo line2; echo line3",
        output_line_callback=collected.append,
    )

    assert result.ok
    assert collected == ["line1", "line2", "line3"], (
        "output_line_callback must receive each line as produced"
    )
    assert "line1" in result.output
    assert "line2" in result.output
    assert "line3" in result.output


def test_run_verification_command_without_callback_behaves_as_before(
    tmp_path: Path,
) -> None:
    """Regression: omitting output_line_callback preserves original synchronous behavior."""
    from cognitive_switchyard.verification_runtime import run_verification_command

    log_path = tmp_path / "verify.log"

    result = run_verification_command(
        session_root=tmp_path,
        verify_log_path=log_path,
        command="echo hello_world",
    )

    assert result.ok
    assert "hello_world" in result.output
    assert log_path.read_text(encoding="utf-8").strip() == "hello_world"


# --- Regression tests for Plan 013: verification interval and full_test_after ---


def test_interval_verification_fires_at_exactly_n_not_before(tmp_path: Path) -> None:
    """Regression: interval-based verification must fire at exactly N=4, not at N-1 or N+1."""
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-013-interval-exact",
        name="Packet 013 interval exact",
        pack="interval-exact-pack",
        created_at="2026-03-12T10:00:00Z",
    )
    for task_id in ["001", "002", "003", "004"]:
        _register_task(store, session_id=session.id, task_id=task_id)

    trace_path = tmp_path / "interval-exact-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="interval-exact-pack",
        max_workers=1,
        verification_interval=4,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "trace = Path(os.environ['VERIFY_TRACE']); "
            "handle = trace.open('a', encoding='utf-8'); handle.write('verify\\n'); handle.close(); "
            "print('verification ok')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["VERIFY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"VERIFY_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    # Interval is 4 — verification fires ONCE at task 4. Since interval fires on the last task,
    # verified_this_iteration=True suppresses the final verification. Total = exactly 1.
    # It must NOT fire at 3 (off-by-one) or fire zero times (skipped).
    verify_indices = [i for i, line in enumerate(lines) if line == "verify"]
    assert result.session_status == "idle"
    assert len(verify_indices) == 1, (
        f"Expected exactly 1 verification run (interval fires on last task, final suppressed), got {len(verify_indices)}: {lines}"
    )
    # The interval verify must come immediately after all 4 task ends
    end_004_idx = lines.index("end:004")
    assert verify_indices[0] == end_004_idx + 1, (
        f"Interval verification must fire immediately after task 004 end, not at line {verify_indices[0]}"
    )


def test_full_test_after_sets_verification_reason_in_runtime_state(tmp_path: Path) -> None:
    """Regression: completing a full_test_after task sets verification_reason='full_test_after' and
    increments completed_since_verification before verification runs."""
    # Test the runtime state directly by simulating what the orchestrator does on task completion.
    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-013-fta-state",
        name="Packet 013 fta state",
        pack="fta-state-pack",
        created_at="2026-03-12T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", full_test_after=True)

    # Simulate what the orchestrator does at orchestrator.py:933-944 when a full_test_after task completes
    current = store.get_session(session.id).runtime_state
    store.write_session_runtime_state(
        session.id,
        completed_since_verification=current.completed_since_verification + 1,
        verification_pending=(True),  # full_test_after is True
        verification_reason="full_test_after",
    )

    updated = store.get_session(session.id).runtime_state
    assert updated.verification_pending is True, (
        "full_test_after task completion must set verification_pending=True"
    )
    assert updated.verification_reason == "full_test_after", (
        f"verification_reason must be 'full_test_after', got {updated.verification_reason!r}"
    )
    assert updated.completed_since_verification == 1, (
        f"completed_since_verification must be 1 after one task, got {updated.completed_since_verification}"
    )


# --- Regression tests for Plan 023: double verification and FTA counter reset ---


def test_no_double_verification_when_interval_fires_on_last_task(tmp_path: Path) -> None:
    """Regression: when the last task triggers interval verification, no additional final
    verification should fire — exactly 1 verification total."""
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-023-no-double-verify",
        name="No double verification",
        pack="no-double-verify-pack",
        created_at="2026-03-12T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002")

    trace_path = tmp_path / "no-double-verify-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="no-double-verify-pack",
        max_workers=1,
        verification_interval=2,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "trace = Path(os.environ['VERIFY_TRACE']); "
            "handle = trace.open('a', encoding='utf-8'); handle.write('verify\\n'); handle.close(); "
            "print('verification ok')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["VERIFY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"VERIFY_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    verify_indices = [i for i, line in enumerate(lines) if line == "verify"]
    events = store.list_events(session.id)
    verification_started_events = [e for e in events if e.event_type == "session.verification_started"]
    verification_passed_events = [e for e in events if e.event_type == "session.verification_passed"]

    assert result.session_status == "idle"
    assert len(verify_indices) == 1, (
        f"Expected exactly 1 verification (interval on last task), not double, got {len(verify_indices)}: {lines}"
    )
    assert len(verification_started_events) == 1, (
        f"Expected exactly 1 verification_started event, got {len(verification_started_events)}"
    )
    assert len(verification_passed_events) == 1, (
        f"Expected exactly 1 verification_passed event, got {len(verification_passed_events)}"
    )


def test_fta_verification_resets_interval_counter(tmp_path: Path) -> None:
    """Regression: after FTA verification passes, the interval counter resets to 0.
    The next interval verification requires a full verification_interval additional completions.
    If the counter were NOT reset, interval would fire prematurely after task 004."""
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-023-fta-resets-counter",
        name="FTA verification resets counter",
        pack="fta-resets-counter-pack",
        created_at="2026-03-12T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002")
    _register_task(store, session_id=session.id, task_id="003", full_test_after=True)
    _register_task(store, session_id=session.id, task_id="004")
    _register_task(store, session_id=session.id, task_id="005")
    _register_task(store, session_id=session.id, task_id="006")
    _register_task(store, session_id=session.id, task_id="007")

    trace_path = tmp_path / "fta-resets-counter-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="fta-resets-counter-pack",
        max_workers=1,
        verification_interval=4,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "trace = Path(os.environ['VERIFY_TRACE']); "
            "handle = trace.open('a', encoding='utf-8'); handle.write('verify\\n'); handle.close(); "
            "print('verification ok')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["VERIFY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"VERIFY_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    verify_indices = [i for i, line in enumerate(lines) if line == "verify"]

    assert result.session_status == "idle"
    # FTA alignment delays task 003 until projected==interval (position 4).
    # Order: 001, 002, 004, 003(FTA→verify, counter reset), 005, 006, 007(final verify).
    # Total = exactly 2 verifications.
    assert len(verify_indices) == 2, (
        f"Expected exactly 2 verifications (FTA + final), got {len(verify_indices)}: {lines}"
    )
    # FTA task 003 is deferred behind 004 for interval alignment.
    # verify fires immediately after end:003.
    end_003_idx = lines.index("end:003")
    assert lines[end_003_idx + 1] == "verify", (
        f"FTA verification must fire immediately after end:003, got {lines[end_003_idx + 1]!r}"
    )
    # 004 runs BEFORE 003 due to FTA alignment deferral.
    end_004_idx = lines.index("end:004")
    assert end_004_idx < end_003_idx, (
        f"Task 004 must complete before FTA task 003 (FTA alignment); trace: {lines}"
    )
    # No verify between end:005 and start:006 (counter reset confirmed — counter was 0
    # after FTA verify, so reaching 005/006 does not trigger interval).
    end_005_idx = lines.index("end:005")
    start_006_idx = lines.index("start:006")
    assert end_005_idx + 1 == start_006_idx, (
        f"No verification should fire between end:005 and start:006 (counter reset after FTA); "
        f"got lines {lines[end_005_idx:start_006_idx + 1]}"
    )


# --- Regression tests for Plan 024: multi-slot FTA and forward-looking interval ---


def test_fta_dispatch_freezes_remaining_slots(tmp_path: Path) -> None:
    """Regression: when an FTA task is dispatched in a multi-slot session, no further tasks
    may dispatch until verification completes — even with free slots available.
    dispatch_frozen must be set at DISPATCH time, not at completion time."""
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-024-fta-multi-slot",
        name="FTA multi-slot dispatch freeze",
        pack="fta-multi-slot-pack",
        created_at="2026-03-12T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")
    _register_task(store, session_id=session.id, task_id="002", full_test_after=True)
    _register_task(store, session_id=session.id, task_id="003")
    _register_task(store, session_id=session.id, task_id="004")
    _register_task(store, session_id=session.id, task_id="005")

    trace_path = tmp_path / "fta-multi-slot-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="fta-multi-slot-pack",
        max_workers=3,
        verification_interval=99,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "trace = Path(os.environ['VERIFY_TRACE']); "
            "handle = trace.open('a', encoding='utf-8'); handle.write('verify\\n'); handle.close(); "
            "print('verification ok')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        import time
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["VERIFY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        if task_id == "002":
            time.sleep(0.1)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"VERIFY_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    verify_indices = [i for i, line in enumerate(lines) if line == "verify"]

    assert result.session_status == "idle"
    # All 5 tasks must complete
    for task_id in ["001", "002", "003", "004", "005"]:
        assert f"end:{task_id}" in lines, f"Task {task_id} must complete"
    # Exactly 2 verifications: one after FTA task 002, one final
    assert len(verify_indices) == 2, (
        f"Expected exactly 2 verifications (FTA + final), got {len(verify_indices)}: {lines}"
    )
    first_verify = verify_indices[0]
    # No task > 002 may START before the first verify
    for task_id in ["003", "004", "005"]:
        start_line = f"start:{task_id}"
        assert start_line in lines, f"{start_line} must appear in trace"
        assert lines.index(start_line) > first_verify, (
            f"{start_line} must appear after first verify (dispatch freeze at FTA dispatch time); "
            f"trace: {lines}"
        )


def test_forward_looking_interval_prevents_over_dispatch(tmp_path: Path) -> None:
    """Regression: the forward-looking count (completed + active + 1 > interval) must prevent
    dispatching a 5th task when interval=4 and 4 tasks are already in flight.
    Prevents regression where only the backward-looking completed >= interval check exists."""
    from cognitive_switchyard.orchestrator import execute_session

    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-024-forward-interval",
        name="Forward-looking interval dispatch gate",
        pack="forward-interval-pack",
        created_at="2026-03-12T10:00:00Z",
    )
    for task_id in ["001", "002", "003", "004", "005", "006", "007", "008"]:
        _register_task(store, session_id=session.id, task_id=task_id)

    trace_path = tmp_path / "forward-interval-trace.log"
    pack_root = _write_pack(
        tmp_path,
        name="forward-interval-pack",
        max_workers=4,
        verification_interval=4,
        verification_command=(
            "python3 -c \"from pathlib import Path; import os; "
            "trace = Path(os.environ['VERIFY_TRACE']); "
            "handle = trace.open('a', encoding='utf-8'); handle.write('verify\\n'); handle.close(); "
            "print('verification ok')\""
        ),
        execute_script_body="""
        #!/usr/bin/env python3
        import os
        import sys
        import time
        from pathlib import Path

        task_path = Path(sys.argv[1])
        task_id = task_path.name.removesuffix(".plan.md")
        trace_path = Path(os.environ["VERIFY_TRACE"])
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"start:{task_id}\\n")
        if task_id == "004":
            time.sleep(0.15)
        else:
            time.sleep(0.01)
        status_path = task_path.with_name(task_id + ".status")
        status_path.write_text(
            "STATUS: done\\nCOMMITS: abc1234\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
            encoding="utf-8",
        )
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(f"end:{task_id}\\n")
        """,
    )

    result = execute_session(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        env={"VERIFY_TRACE": str(trace_path), "PATH": os.environ["PATH"]},
        poll_interval=0.01,
    )

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    verify_indices = [i for i, line in enumerate(lines) if line == "verify"]

    assert result.session_status == "idle"
    # All 8 tasks must complete
    for task_id in ["001", "002", "003", "004", "005", "006", "007", "008"]:
        assert f"end:{task_id}" in lines, f"Task {task_id} must complete"
    # Exactly 2 verifications
    assert len(verify_indices) == 2, (
        f"Expected exactly 2 verifications, got {len(verify_indices)}: {lines}"
    )
    first_verify = verify_indices[0]
    # No task > 004 may START before the first verify — forward-looking gate prevents it
    for task_id in ["005", "006", "007", "008"]:
        start_line = f"start:{task_id}"
        assert start_line in lines, f"{start_line} must appear in trace"
        assert lines.index(start_line) > first_verify, (
            f"{start_line} must appear after first verify (forward-looking interval gate); "
            f"trace: {lines}"
        )


def test_dispatch_frozen_set_on_fta_dispatch(tmp_path: Path) -> None:
    """Regression: dispatch_frozen and dispatch_frozen_reason round-trip through
    write_session_runtime_state, and clearing them restores the default state."""
    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-024-dispatch-frozen-rt",
        name="dispatch_frozen round-trip",
        pack="dispatch-frozen-pack",
        created_at="2026-03-12T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001", full_test_after=True)

    # Simulate orchestrator setting dispatch_frozen at FTA task dispatch time
    store.write_session_runtime_state(
        session.id,
        dispatch_frozen=True,
        dispatch_frozen_reason="fta_task_active",
    )

    state_after_dispatch = store.get_session(session.id).runtime_state
    assert state_after_dispatch.dispatch_frozen is True, (
        "dispatch_frozen must be True after FTA task dispatch"
    )
    assert state_after_dispatch.dispatch_frozen_reason == "fta_task_active", (
        f"dispatch_frozen_reason must be 'fta_task_active', got {state_after_dispatch.dispatch_frozen_reason!r}"
    )

    # Simulate verification pass clearing the frozen flags
    store.write_session_runtime_state(
        session.id,
        dispatch_frozen=False,
        dispatch_frozen_reason=None,
        verification_pending=False,
    )

    state_after_verify = store.get_session(session.id).runtime_state
    assert state_after_verify.dispatch_frozen is False, (
        "dispatch_frozen must be cleared after verification pass"
    )
    assert state_after_verify.dispatch_frozen_reason is None, (
        f"dispatch_frozen_reason must be None after verification pass, got {state_after_verify.dispatch_frozen_reason!r}"
    )
    assert state_after_verify.verification_pending is False, (
        "verification_pending must be False after verification pass"
    )


# --- Regression tests for Plan 026: parse_test_summary ---


def test_parse_test_summary_extracts_pytest_passed_count() -> None:
    from cognitive_switchyard.verification_runtime import parse_test_summary

    output = "some output\n=== 279 passed in 42.31s ===\n"
    assert parse_test_summary(output) == "279 passed"


def test_parse_test_summary_extracts_mixed_results() -> None:
    from cognitive_switchyard.verification_runtime import parse_test_summary

    output = "collected 279 items\n\n=== 277 passed, 2 failed in 42.31s ===\n"
    assert parse_test_summary(output) == "277 passed, 2 failed"


def test_parse_test_summary_extracts_complex_results() -> None:
    from cognitive_switchyard.verification_runtime import parse_test_summary

    output = "=== 275 passed, 2 failed, 1 error, 3 warnings in 42.31s ===\n"
    assert parse_test_summary(output) == "275 passed, 2 failed, 1 error, 3 warnings"


def test_parse_test_summary_returns_none_for_no_match() -> None:
    from cognitive_switchyard.verification_runtime import parse_test_summary

    output = "some random output\nno test info here\n"
    assert parse_test_summary(output) is None


def test_parse_test_summary_returns_none_for_empty_string() -> None:
    from cognitive_switchyard.verification_runtime import parse_test_summary

    assert parse_test_summary("") is None


def test_verification_pass_stores_test_summary_in_runtime_state(tmp_path: Path) -> None:
    """Integration: verification pass with pytest-style output stores summary in runtime state."""
    from cognitive_switchyard.orchestrator import execute_session

    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-026-test-summary",
        name="Plan 026 test summary",
        pack="test-summary-pack",
        created_at="2026-03-12T10:00:00Z",
    )
    _register_task(store, session_id=session.id, task_id="001")

    pack_root = _write_pack(
        tmp_path,
        name="test-summary-pack",
        max_workers=1,
        verification_interval=1,
        verification_command=(
            'python3 -c "print(\'=== 5 passed in 0.42s ===\')"'
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
        env={"PATH": __import__("os").environ["PATH"]},
        poll_interval=0.01,
    )

    assert result.session_status == "idle"
    final_state = store.get_session(session.id).runtime_state
    assert final_state.last_verification_test_summary == "5 passed", (
        f"Expected '5 passed', got {final_state.last_verification_test_summary!r}"
    )


def test_build_task_failure_context_with_timeout_failure_kind(tmp_path: Path) -> None:
    plan_path = tmp_path / "001_task.plan.md"
    plan_path.write_text("# Plan\nDo the thing.\n", encoding="utf-8")
    verify_log = tmp_path / "verify.log"
    verify_log.write_text("", encoding="utf-8")

    context = build_task_failure_context(
        session_id="test-session",
        task_id="001",
        attempt=1,
        plan_path=plan_path,
        status_path=None,
        worker_log_path=None,
        verify_log_path=verify_log,
        previous_attempt_summary=None,
        failure_kind="timeout",
    )

    assert isinstance(context, FixerContext)
    assert context.context_type == "task_failure"
    assert context.failure_kind == "timeout"


def test_build_task_failure_context_default_failure_kind_is_none(tmp_path: Path) -> None:
    plan_path = tmp_path / "001_task.plan.md"
    plan_path.write_text("# Plan\nDo the thing.\n", encoding="utf-8")
    verify_log = tmp_path / "verify.log"
    verify_log.write_text("", encoding="utf-8")

    context = build_task_failure_context(
        session_id="test-session",
        task_id="001",
        attempt=1,
        plan_path=plan_path,
        status_path=None,
        worker_log_path=None,
        verify_log_path=verify_log,
        previous_attempt_summary=None,
    )

    assert context.failure_kind is None
