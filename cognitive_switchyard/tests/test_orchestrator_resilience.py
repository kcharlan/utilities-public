"""Regressions for safe Switchyard orchestration."""

import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("pack,agent", [("codex", "codex"), ("codex-hybrid", "codex"), ("claude-code", "claude")])
def test_builtin_execute_preserves_agent_permission_defaults(tmp_path: Path, pack: str, agent: str) -> None:
    root = Path(__file__).resolve().parents[1]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "args"
    stub = bin_dir / agent
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n')
    stub.chmod(0o755)
    plan = tmp_path / "synthetic.plan.md"
    plan.write_text("Synthetic plan\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "CAPTURE": str(capture)}
    subprocess.run([str(root / "cognitive_switchyard" / "builtin_packs" / pack / "scripts" / "execute"), str(plan), str(tmp_path)], env=env, check=True, capture_output=True, text=True, timeout=15)
    args = capture.read_text().splitlines()
    assert "--dangerously-bypass-approvals-and-sandbox" not in args
    assert "--dangerously-skip-permissions" not in args


def test_compare_and_set_transitions_have_one_winner(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.models import TaskPlan
    from cognitive_switchyard.state import initialize_state_store

    store = initialize_state_store(build_runtime_paths(home=tmp_path))
    store.create_session(session_id="synthetic", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    store.register_task_plan(session_id="synthetic", plan=TaskPlan(task_id="task", title="Synthetic"), plan_text="Synthetic", created_at="2026-01-01T00:00:00Z")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: store.try_transition_task("synthetic", "task", expected="ready", status="blocked"), range(2)))
    assert sorted(outcomes) == [False, True]
    assert store.get_task("synthetic", "task").status == "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: store.try_transition_session("synthetic", expected="created", status="paused"), range(2)))
    assert sorted(outcomes) == [False, True]


def test_worker_collection_failure_propagates_without_repolling() -> None:
    from cognitive_switchyard.orchestrator import _collect_finished_workers
    from cognitive_switchyard.process_identity import ProcessGroupInspectionError

    class FailedManager:
        def __init__(self):
            self.polls = 0
        def active_slot_numbers(self):
            return [0]
        def poll(self, slot):
            self.polls += 1
            raise ProcessGroupInspectionError("synthetic inspection failure")

    manager = FailedManager()
    with pytest.raises(ProcessGroupInspectionError, match="synthetic inspection failure"):
        _collect_finished_workers(store=None, session_id="synthetic", pack_manifest=None, effective_runtime_config=None, manager=manager, env=None, fixer_executor=None, runtime_event_sink=None)
    assert manager.polls == 1


def test_session_crash_pauses_and_preserves_workspace(tmp_path: Path, monkeypatch) -> None:
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.state import initialize_state_store
    from cognitive_switchyard import server

    paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(paths)
    store.create_session(session_id="synthetic", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    workspace = paths.session_paths("synthetic").root / "workspace"
    workspace.mkdir()
    (workspace / "uncommitted").write_text("synthetic work")
    monkeypatch.setattr(server, "load_pack_manifest", lambda _: object())
    monkeypatch.setattr(server, "start_session", lambda **_: (_ for _ in ()).throw(RuntimeError("synthetic crash")))
    controller = server.SessionController(store=store, runtime_paths=paths, connection_manager=server.ConnectionManager())
    monkeypatch.setattr(controller, "_publish_snapshot", lambda _: None)
    controller._run_session("synthetic")
    assert store.get_session("synthetic").status == "paused"
    assert (workspace / "uncommitted").read_text() == "synthetic work"


def test_retry_rejects_active_task(tmp_path: Path) -> None:
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.models import TaskPlan
    from cognitive_switchyard.server import ConnectionManager, SessionController
    from cognitive_switchyard.state import initialize_state_store

    paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(paths)
    store.create_session(session_id="synthetic", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    store.register_task_plan(session_id="synthetic", plan=TaskPlan(task_id="task", title="Synthetic"), plan_text="Synthetic", created_at="2026-01-01T00:00:00Z")
    store.project_task("synthetic", "task", status="active", worker_slot=0)
    controller = SessionController(store=store, runtime_paths=paths, connection_manager=ConnectionManager())
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        controller.retry_task("synthetic", "task")
    assert exc.value.status_code == 409
    assert store.get_task("synthetic", "task").status == "active"


def test_second_orchestrator_cannot_take_session_lock(tmp_path: Path) -> None:
    import fcntl
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.orchestrator import execute_session
    from cognitive_switchyard.state import initialize_state_store

    paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(paths)
    store.create_session(session_id="synthetic", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    lock_path = paths.session_paths("synthetic").root / ".orchestrator.lock"
    with lock_path.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="already running"):
            execute_session(store=store, session_id="synthetic", pack_manifest=None)


def test_lock_conflict_does_not_pause_running_session(tmp_path: Path, monkeypatch) -> None:
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.state import initialize_state_store
    from cognitive_switchyard import server
    from cognitive_switchyard.orchestrator import SessionAlreadyRunning

    paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(paths)
    store.create_session(session_id="synthetic", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    store.update_session_status("synthetic", status="running")
    monkeypatch.setattr(server, "load_pack_manifest", lambda _: object())
    monkeypatch.setattr(server, "start_session", lambda **_: (_ for _ in ()).throw(SessionAlreadyRunning("already running")))
    controller = server.SessionController(store=store, runtime_paths=paths, connection_manager=server.ConnectionManager())
    monkeypatch.setattr(controller, "_publish_snapshot", lambda _: None)
    controller._run_session("synthetic")
    assert store.get_session("synthetic").status == "running"


@pytest.mark.parametrize("family,command", [("codex", "stub-codex"), ("claude", "stub-claude")])
def test_packet_loop_preserves_agent_permission_defaults(tmp_path: Path, family: str, command: str) -> None:
    source = Path(__file__).resolve().parents[1] / "scripts" / "codex_packet_loop.zsh"
    script_text = source.read_text()
    script_text = script_text.rsplit('main "$@"', 1)[0]
    script = tmp_path / "loop.zsh"
    script.write_text(script_text + '\nmonitor_stage_heartbeat() { :; }\nrun_agent_exec synthetic high "$PROMPT_FILE" "$OUTPUT_FILE"\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    agent = bin_dir / command
    agent.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n')
    agent.chmod(0o755)
    fake_parser = bin_dir / "python3"
    fake_parser.write_text('#!/bin/sh\ncat >/dev/null\n')
    fake_parser.chmod(0o755)
    parser = tmp_path / "parser"
    parser.touch()
    prompt = tmp_path / "prompt"
    prompt.write_text("synthetic")
    capture = tmp_path / "captured"
    env = {**os.environ, "HOME": str(tmp_path), "ROOT_DIR": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}", "AGENT_CLI": family, "CODEX_COMMAND": command, "CLAUDE_OPUS_COMMAND": command, "CLAUDE_SONNET_COMMAND": command, "JSON_PROGRESS_PARSER": str(parser), "PROMPT_FILE": str(prompt), "OUTPUT_FILE": str(tmp_path / "output"), "CAPTURE": str(capture)}
    subprocess.run(["/bin/zsh", str(script)], env=env, check=True, capture_output=True, text=True, timeout=15)
    args = capture.read_text().splitlines()
    assert "--dangerously-bypass-approvals-and-sandbox" not in args
    assert "--dangerously-skip-permissions" not in args
    assert "bypassPermissions" not in args


def test_claim_does_not_overwrite_concurrent_task_move(tmp_path: Path) -> None:
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.models import TaskPlan
    from cognitive_switchyard.state import initialize_state_store
    store = initialize_state_store(build_runtime_paths(home=tmp_path))
    store.create_session(session_id="synthetic", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    store.register_task_plan(session_id="synthetic", plan=TaskPlan(task_id="task", title="Synthetic"), plan_text="Synthetic", created_at="2026-01-01T00:00:00Z")
    store.project_task("synthetic", "task", status="blocked")
    assert store.try_claim_task("synthetic", "task", worker_slot=0, timestamp="2026-01-01T00:00:01Z") is None
    assert store.get_task("synthetic", "task").status == "blocked"


def test_planning_checkpoints_active_time_while_blocked(tmp_path: Path, monkeypatch) -> None:
    import threading
    import time
    from cognitive_switchyard import orchestrator
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.models import SessionPreparationResult
    from cognitive_switchyard.pack_loader import load_pack_manifest
    from cognitive_switchyard.state import initialize_state_store
    from tests.test_orchestrator import _write_pack

    store = initialize_state_store(build_runtime_paths(home=tmp_path))
    store.create_session(session_id="synthetic", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    pack = load_pack_manifest(_write_pack(tmp_path, name="checkpoint-planning", execute_script_body="#!/bin/sh\nexit 0\n"))
    entered, release = threading.Event(), threading.Event()
    errors = []
    def prepare(**kwargs):
        store.update_session_status("synthetic", status="planning")
        entered.set()
        assert release.wait(8)
        return SessionPreparationResult(session_id=kwargs["session_id"])
    def run():
        try:
            orchestrator.start_session(store=store, session_id="synthetic", pack_manifest=pack)
        except BaseException as exc:
            errors.append(exc)
    monkeypatch.setattr(orchestrator, "prepare_session_for_execution", prepare)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(4)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and store.get_session("synthetic").runtime_state.accumulated_elapsed_seconds < 1:
            threading.Event().wait(0.05)
        assert store.get_session("synthetic").runtime_state.accumulated_elapsed_seconds >= 1
    finally:
        release.set()
        thread.join(timeout=8)
    assert not thread.is_alive()
    assert errors == []


def test_planning_checkpoint_survives_process_loss(tmp_path: Path) -> None:
    import sys
    import threading
    import time
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.state import initialize_state_store
    from tests.test_orchestrator import _write_pack

    store = initialize_state_store(build_runtime_paths(home=tmp_path))
    store.create_session(session_id="synthetic", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    pack = _write_pack(tmp_path, name="crash-planning", execute_script_body="#!/bin/sh\nexit 0\n")
    ready = tmp_path / "planning-ready"
    script = '''
import sys, threading
from pathlib import Path
from cognitive_switchyard import orchestrator
from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.state import initialize_state_store
store = initialize_state_store(build_runtime_paths(home=Path(sys.argv[1])))
def prepare(**kwargs):
    store.update_session_status("synthetic", status="planning")
    Path(sys.argv[3]).write_text("ready")
    threading.Event().wait(30)
orchestrator.prepare_session_for_execution = prepare
orchestrator.start_session(store=store, session_id="synthetic", pack_manifest=load_pack_manifest(Path(sys.argv[2])))
'''
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    process = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), str(pack), str(ready)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(process.communicate()[1])
            if ready.exists() and store.get_session("synthetic").runtime_state.accumulated_elapsed_seconds >= 1:
                break
            threading.Event().wait(0.05)
        assert ready.exists()
        assert store.get_session("synthetic").runtime_state.accumulated_elapsed_seconds >= 1
        process.kill()
        process.communicate(timeout=5)
        saved = store.get_session("synthetic").runtime_state.accumulated_elapsed_seconds
        assert saved >= 1
        assert store.session_clock_version("synthetic") == 1
        assert store.get_session("synthetic").runtime_state.accumulated_elapsed_seconds == saved
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_legacy_active_clock_migration_discards_stale_run_counter(tmp_path: Path) -> None:
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.state import initialize_state_store
    store = initialize_state_store(build_runtime_paths(home=tmp_path))
    store.create_session(session_id="legacy", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    store.write_session_runtime_state("legacy", accumulated_elapsed_seconds=32, last_run_elapsed_seconds=12, auto_fix_context="task_failure")
    first = store.advance_session_clock("legacy", seconds=2, timestamp="2026-01-01T00:00:02Z")
    assert (first.accumulated_elapsed_seconds, first.last_run_elapsed_seconds) == (34, 2)
    assert first.auto_fix_context == "task_failure"
    assert store.session_clock_version("legacy") == 1
    second = store.advance_session_clock("legacy", seconds=3, timestamp="2026-01-01T00:00:05Z")
    assert (second.accumulated_elapsed_seconds, second.last_run_elapsed_seconds) == (37, 5)
    assert second.auto_fix_context == "task_failure"


def test_clock_and_runtime_updates_do_not_overwrite_each_other(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.state import initialize_state_store
    store = initialize_state_store(build_runtime_paths(home=tmp_path))
    store.create_session(session_id="synthetic", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    def advance():
        for _ in range(25):
            store.advance_session_clock("synthetic", seconds=1, timestamp="2026-01-01T00:00:00Z")
    def update():
        for _ in range(25):
            store.write_session_runtime_state("synthetic", verification_pending=True, auto_fix_context="task_failure")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), [advance, update]))
    state = store.get_session("synthetic").runtime_state
    assert state.accumulated_elapsed_seconds == 25
    assert state.last_run_elapsed_seconds == 25
    assert state.verification_pending is True
    assert state.auto_fix_context == "task_failure"


def test_short_legacy_resume_does_not_reuse_previous_run_timer(tmp_path: Path) -> None:
    from cognitive_switchyard.config import build_runtime_paths
    from cognitive_switchyard.orchestrator import execute_session
    from cognitive_switchyard.pack_loader import load_pack_manifest
    from cognitive_switchyard.state import initialize_state_store
    from tests.test_orchestrator import _write_pack
    store = initialize_state_store(build_runtime_paths(home=tmp_path))
    store.create_session(session_id="legacy", name="Synthetic", pack="test", created_at="2026-01-01T00:00:00Z")
    store.write_session_runtime_state("legacy", accumulated_elapsed_seconds=32, last_run_elapsed_seconds=12, run_started_at="2026-01-01T00:00:00Z")
    store.update_session_status("legacy", status="running", started_at="2026-01-01T00:00:00Z")
    pack = load_pack_manifest(_write_pack(tmp_path, name="short-legacy", session_max=60, execute_script_body="#!/bin/sh\nexit 0\n"))
    result = execute_session(store=store, session_id="legacy", pack_manifest=pack)
    state = store.get_session("legacy").runtime_state
    assert result.session_status == "idle"
    assert state.accumulated_elapsed_seconds == 32
    assert state.last_run_elapsed_seconds == 1
    assert store.session_clock_version("legacy") == 1
