from pathlib import Path
import subprocess
import pytest

from cognitive_switchyard.agent_runtime import CodexCliRuntime, _default_subprocess_runner, _streaming_subprocess_runner


def test_codex_prompt_is_sent_on_stdin(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("system prompt")
    captured = {}

    def runner(*, command, cwd, input_text):
        captured.update(command=command, input_text=input_text)
        return subprocess.CompletedProcess(command, 0, stdout='{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n', stderr="")

    runtime = CodexCliRuntime(command="codex", subprocess_runner=runner)
    runtime._run_phase_once(phase="planning", model="synthetic", prompt_path=prompt,
                            session_root=tmp_path, input_text="x" * 200000)
    assert captured["command"][-1] == "-"
    assert captured["input_text"].endswith("x" * 200000)


def _tree_script(tmp_path: Path) -> Path:
    script = tmp_path / "tree.sh"
    marker = tmp_path / "survived"
    script.write_text("#!/bin/sh\n(trap '' TERM; sleep 1; touch '" + str(marker) + "') &\nwait\n")
    script.chmod(0o755)
    return script


def test_hook_timeout_kills_grandchild_with_open_pipe(tmp_path, monkeypatch):
    import time
    from cognitive_switchyard import agent_runtime
    from cognitive_switchyard.hook_runner import run_short_lived_hook
    monkeypatch.setattr(agent_runtime, "PROCESS_TIMEOUT_SECONDS", 0.2, raising=False)
    result = run_short_lived_hook(_tree_script(tmp_path))
    assert not result.ok
    time.sleep(1.1)
    assert not (tmp_path / "survived").exists()


@pytest.mark.parametrize("streaming", [False, True])
def test_verification_timeout_kills_grandchild_with_open_pipe(tmp_path, monkeypatch, streaming):
    import time
    from cognitive_switchyard import agent_runtime
    from cognitive_switchyard.verification_runtime import run_verification_command
    monkeypatch.setattr(agent_runtime, "PROCESS_TIMEOUT_SECONDS", 0.2, raising=False)
    callback = (lambda line: None) if streaming else None
    result = run_verification_command(session_root=tmp_path, verify_log_path=tmp_path / "verify.log", command=str(_tree_script(tmp_path)), output_line_callback=callback)
    assert not result.ok
    time.sleep(1.1)
    assert not (tmp_path / "survived").exists()


@pytest.mark.parametrize("streaming", [False, True])
def test_agent_timeout_kills_grandchild_with_open_pipe(tmp_path, monkeypatch, streaming):
    import time
    from cognitive_switchyard import agent_runtime
    monkeypatch.setattr(agent_runtime, "PROCESS_TIMEOUT_SECONDS", 0.2, raising=False)
    kwargs = dict(command=[str(_tree_script(tmp_path))], cwd=tmp_path, input_text="")
    result = (_streaming_subprocess_runner(**kwargs, line_callback=lambda line: None)
              if streaming else _default_subprocess_runner(**kwargs))
    assert result.returncode != 0
    time.sleep(1.1)
    assert not (tmp_path / "survived").exists()


def test_prerequisite_timeout_kills_grandchild_with_open_pipe(tmp_path, monkeypatch):
    import time
    from types import SimpleNamespace
    from cognitive_switchyard import agent_runtime
    from cognitive_switchyard.hook_runner import run_prerequisite_checks

    monkeypatch.setattr(agent_runtime, "PROCESS_TIMEOUT_SECONDS", 0.2)
    manifest = SimpleNamespace(root=tmp_path, prerequisites=[SimpleNamespace(name="synthetic", check=str(_tree_script(tmp_path)))])
    result = run_prerequisite_checks(manifest)
    assert not result.ok
    time.sleep(1.1)
    assert not (tmp_path / "survived").exists()


def test_agent_output_capture_is_bounded(tmp_path):
    from cognitive_switchyard import agent_runtime
    script = tmp_path / "output.sh"
    script.write_text("#!/bin/sh\nyes x | head -c 2000000\n")
    script.chmod(0o755)
    result = _default_subprocess_runner(command=[str(script)], cwd=tmp_path, input_text="")
    assert len(result.stdout.encode()) <= 1048576


def test_agent_runner_accepts_large_stdin(tmp_path):
    script = tmp_path / "count.sh"
    script.write_text("#!/bin/sh\nwc -c\n")
    script.chmod(0o755)
    result = _default_subprocess_runner(command=[str(script)], cwd=tmp_path, input_text="x" * 200000)
    assert result.returncode == 0
    assert int(result.stdout.strip()) == 200000


def test_worker_timeout_kills_grandchild_holding_pipe(tmp_path):
    import time
    from tests.test_worker_manager import _write_pack, _write_task_plan, _poll_until_finished
    from cognitive_switchyard.pack_loader import load_pack_manifest
    from cognitive_switchyard.worker_manager import WorkerManager

    script = _tree_script(tmp_path)
    manifest = load_pack_manifest(_write_pack(tmp_path, name="worker-pack", execute_script=script))
    task = _write_task_plan(tmp_path / "tasks")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WorkerManager(default_task_idle=0.1, kill_grace_period=0.1)
    manager.dispatch(slot_number=0, pack_manifest=manifest, task_plan_path=task,
                     workspace_path=workspace, log_path=tmp_path / "worker.log")
    started = time.monotonic()
    snapshot = _poll_until_finished(manager, 0)
    assert snapshot.timed_out
    assert time.monotonic() - started < 0.8
    time.sleep(1.1)
    assert not (tmp_path / "survived").exists()


def test_worker_caps_unterminated_output_and_pending_lines(tmp_path):
    from tests.test_worker_manager import _write_pack, _write_task_plan
    from cognitive_switchyard.pack_loader import load_pack_manifest
    from cognitive_switchyard.worker_manager import WorkerManager

    script = tmp_path / "output.sh"
    script.write_text("#!/bin/sh\nhead -c 2000000 /dev/zero\n")
    script.chmod(0o755)
    manifest = load_pack_manifest(_write_pack(tmp_path, name="output-pack", execute_script=script))
    task = _write_task_plan(tmp_path / "tasks")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log = tmp_path / "worker.log"
    manager = WorkerManager()
    manager.dispatch(slot_number=0, pack_manifest=manifest, task_plan_path=task,
                     workspace_path=workspace, log_path=log)
    worker = manager._workers[0]
    worker.process.wait(timeout=5)
    for reader in worker.readers:
        reader.join(timeout=5)
    snapshot = manager.poll(0)
    assert log.stat().st_size <= 1048576
    assert snapshot.new_output_lines
    assert sum(len(line.encode()) for line in snapshot.new_output_lines) <= 1048576
