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
