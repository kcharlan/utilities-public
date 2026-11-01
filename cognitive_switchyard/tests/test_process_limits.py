from pathlib import Path
import subprocess
import pytest

from cognitive_switchyard.agent_runtime import ClaudeCliRuntime, CodexCliRuntime, _default_subprocess_runner, _streaming_subprocess_runner


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
    for reader in worker.readers:
        reader.join(timeout=5)
    snapshot = manager.poll(0)
    assert log.stat().st_size <= 1048576
    assert snapshot.new_output_lines
    assert sum(len(line.encode()) for line in snapshot.new_output_lines) <= 1048576


@pytest.mark.parametrize("runtime_class", [
    ClaudeCliRuntime,
    CodexCliRuntime,
])
def test_agent_prompt_and_permissions_use_stdin_and_normal_settings(tmp_path, runtime_class):
    prompt = tmp_path / "prompt.md"
    instructions = "instruction " * 20000
    prompt.write_text(instructions)
    captured = {}

    def runner(*, command, cwd, input_text):
        captured.update(command=command, input_text=input_text)
        output = ('{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n'
                  if runtime_class is CodexCliRuntime else "ok")
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    runtime = runtime_class(command="synthetic-agent", subprocess_runner=runner)
    runtime._run_phase_once(phase="planning", model="synthetic", prompt_path=prompt,
                            session_root=tmp_path, input_text="synthetic context")
    assert max(map(len, captured["command"])) < 1000
    assert captured["input_text"] == instructions.strip() + "\n\nsynthetic context"
    assert not any(arg in {"--dangerously-skip-permissions", "--dangerously-bypass-approvals-and-sandbox"}
                   for arg in captured["command"])


def test_claude_preserves_context_whitespace_on_stdin(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("instructions")
    captured = {}

    def runner(*, command, cwd, input_text):
        captured["input_text"] = input_text
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    ClaudeCliRuntime(command="synthetic-agent", subprocess_runner=runner)._run_phase_once(
        phase="planning", model="synthetic", prompt_path=prompt, session_root=tmp_path,
        input_text="  context\n\n")
    assert captured["input_text"] == "instructions\n\n  context\n\n"


@pytest.mark.parametrize("streaming", [False, True])
def test_truncated_agent_stdout_is_reported_as_failure(tmp_path, streaming):
    script = tmp_path / "oversized.sh"
    script.write_text("#!/bin/sh\nhead -c 2000000 /dev/zero\n")
    script.chmod(0o755)
    kwargs = dict(command=[str(script)], cwd=tmp_path, input_text="")
    result = (_streaming_subprocess_runner(**kwargs, line_callback=lambda line: None)
              if streaming else _default_subprocess_runner(**kwargs))
    assert result.returncode != 0
    assert "truncated" in result.stderr.lower()


def test_interrupted_agent_runner_terminates_process_group(tmp_path, monkeypatch):
    import time
    from cognitive_switchyard import agent_runtime

    script = _tree_script(tmp_path)
    original_popen = subprocess.Popen
    launched = []

    def interrupting_popen(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        if args and args[0] == [str(script)]:
            launched.append(proc)
        return proc

    monkeypatch.setattr(agent_runtime.subprocess, "Popen", interrupting_popen)
    try:
        with monkeypatch.context() as interrupted:
            interrupted.setattr(agent_runtime.threading.Thread, "start", lambda self: (_ for _ in ()).throw(KeyboardInterrupt()))
            with pytest.raises(KeyboardInterrupt):
                _default_subprocess_runner(command=[str(script)], cwd=tmp_path, input_text="")
        time.sleep(1.1)
        assert not (tmp_path / "survived").exists()
    finally:
        if launched:
            try:
                launched[0].wait(timeout=2)
            except subprocess.TimeoutExpired:
                launched[0].kill()
                launched[0].wait(timeout=2)


def _closed_pipe_tree_script(tmp_path: Path) -> Path:
    script = tmp_path / "closed-tree.sh"
    marker = tmp_path / "closed-survivor"
    script.write_text("#!/bin/sh\n(trap '' TERM; exec >/dev/null 2>&1; sleep 1; touch '" + str(marker) + "') &\nwait\n")
    script.chmod(0o755)
    return script


@pytest.mark.parametrize("streaming", [False, True])
def test_agent_timeout_kills_descendant_that_closed_pipes(tmp_path, monkeypatch, streaming):
    import time
    from cognitive_switchyard import agent_runtime
    monkeypatch.setattr(agent_runtime, "PROCESS_TIMEOUT_SECONDS", 0.2)
    kwargs = dict(command=[str(_closed_pipe_tree_script(tmp_path))], cwd=tmp_path, input_text="")
    result = (_streaming_subprocess_runner(**kwargs, line_callback=lambda line: None)
              if streaming else _default_subprocess_runner(**kwargs))
    assert result.returncode != 0
    time.sleep(1.1)
    assert not (tmp_path / "closed-survivor").exists()


def test_worker_timeout_kills_descendant_that_closed_pipes(tmp_path):
    import time
    from tests.test_worker_manager import _write_pack, _write_task_plan, _poll_until_finished
    from cognitive_switchyard.pack_loader import load_pack_manifest
    from cognitive_switchyard.worker_manager import WorkerManager
    script = _closed_pipe_tree_script(tmp_path)
    manifest = load_pack_manifest(_write_pack(tmp_path, name="closed-worker", execute_script=script))
    task = _write_task_plan(tmp_path / "tasks")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WorkerManager(default_task_idle=0.1, kill_grace_period=0.1)
    manager.dispatch(slot_number=0, pack_manifest=manifest, task_plan_path=task,
                     workspace_path=workspace, log_path=tmp_path / "worker.log")
    assert _poll_until_finished(manager, 0).timed_out
    time.sleep(1.1)
    assert not (tmp_path / "closed-survivor").exists()


def test_inspect_owned_group_identifies_live_leader(tmp_path):
    from cognitive_switchyard.process_identity import OwnedProcessGroup, owned_group_members, process_identity
    proc = subprocess.Popen(["/bin/sleep", "5"], cwd=tmp_path, start_new_session=True)
    try:
        identity = process_identity(proc.pid)
        assert identity is not None
        members = owned_group_members(OwnedProcessGroup(proc, identity))
        assert any(pid == proc.pid and item_identity == identity for pid, item_identity, _ in members)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_inspect_owned_group_retains_unreaped_leader_identity(tmp_path):
    from cognitive_switchyard.process_identity import OwnedProcessGroup, owned_group_members, process_identity
    proc = subprocess.Popen(["/bin/sleep", "0.1"], cwd=tmp_path, start_new_session=True, stdout=subprocess.PIPE)
    try:
        identity = process_identity(proc.pid)
        assert identity is not None
        assert proc.stdout.read() == b""
        members = owned_group_members(OwnedProcessGroup(proc, identity))
        assert any(pid == proc.pid and item_identity == identity and status == 5 for pid, item_identity, status in members)
    finally:
        proc.wait(timeout=5)


def test_owned_group_signal_fails_closed_on_denial(monkeypatch):
    import importlib
    from types import SimpleNamespace
    identity_module = importlib.import_module("cognitive_switchyard.process_identity")
    group = SimpleNamespace(process=SimpleNamespace(pid=1001), check_unreaped=lambda: None)
    monkeypatch.setattr(identity_module, "owned_group_members", lambda group: ((1001, "one", 0), (1002, "two", 0)))
    monkeypatch.setattr(identity_module, "process_identity", lambda pid: {1001: "one", 1002: "two"}[pid])
    monkeypatch.setattr(identity_module.os, "getpgid", lambda pid: 1001)
    calls = []
    def denied(pid, sig):
        calls.append(pid)
        raise PermissionError("synthetic denial")
    monkeypatch.setattr(identity_module.os, "kill", denied)
    with pytest.raises(PermissionError):
        identity_module.signal_owned_group(group, 15)
    assert calls == [1001]


def test_owned_group_signal_rejects_changed_identity(monkeypatch):
    import importlib
    from types import SimpleNamespace
    identity_module = importlib.import_module("cognitive_switchyard.process_identity")
    group = SimpleNamespace(process=SimpleNamespace(pid=1001), check_unreaped=lambda: None)
    monkeypatch.setattr(identity_module, "owned_group_members", lambda group: ((1001, "original", 0),))
    monkeypatch.setattr(identity_module, "process_identity", lambda pid: "replacement")
    calls = []
    monkeypatch.setattr(identity_module.os, "kill", lambda pid, sig: calls.append(pid))
    with pytest.raises(identity_module.ProcessGroupInspectionError):
        identity_module.signal_owned_group(group, 15)
    assert not calls


def test_group_inspection_rechecks_member_that_exits_during_snapshot(monkeypatch):
    import importlib
    from types import SimpleNamespace
    identity_module = importlib.import_module("cognitive_switchyard.process_identity")
    group = SimpleNamespace(process=SimpleNamespace(pid=1001), leader_identity="leader", check_unreaped=lambda: None)
    monkeypatch.setattr(identity_module.sys, "platform", "darwin")
    snapshots = iter(["1001 1001 S\n1002 1001 S\n", "1001 1001 S\n"])
    monkeypatch.setattr(identity_module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=next(snapshots)))
    monkeypatch.setattr(identity_module, "process_identity", lambda pid: "leader" if pid == 1001 else None)
    assert identity_module.owned_group_members(group) == ((1001, "leader", 0),)


def test_linux_group_inspection_uses_process_group_selector(monkeypatch):
    import importlib
    from types import SimpleNamespace
    identity_module = importlib.import_module("cognitive_switchyard.process_identity")
    group = SimpleNamespace(process=SimpleNamespace(pid=1001), leader_identity="leader", check_unreaped=lambda: None)
    monkeypatch.setattr(identity_module.sys, "platform", "linux")
    commands = []
    def fake_run(command, **kwargs):
        commands.append(command)
        if command[0] == "/usr/bin/pgrep":
            return SimpleNamespace(returncode=0, stdout="1001\n")
        return SimpleNamespace(returncode=0, stdout="1001 1001 S\n")
    monkeypatch.setattr(identity_module.subprocess, "run", fake_run)
    monkeypatch.setattr(identity_module, "process_identity", lambda pid: "leader")
    assert identity_module.owned_group_members(group) == ((1001, "leader", 0),)
    assert commands == [["/usr/bin/pgrep", "-g", "1001"],
                        ["/bin/ps", "-p", "1001", "-o", "pid=,pgid=,stat="]]


def test_linux_group_inspection_fails_closed_for_empty_group(monkeypatch):
    import importlib
    from types import SimpleNamespace
    identity_module = importlib.import_module("cognitive_switchyard.process_identity")
    group = SimpleNamespace(process=SimpleNamespace(pid=1001), leader_identity="leader", check_unreaped=lambda: None)
    monkeypatch.setattr(identity_module.sys, "platform", "linux")
    monkeypatch.setattr(identity_module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""))
    with pytest.raises(identity_module.ProcessGroupInspectionError):
        identity_module.owned_group_members(group)


def test_linux_group_inspection_accepts_member_exiting_before_ps(monkeypatch):
    import importlib
    from types import SimpleNamespace
    identity_module = importlib.import_module("cognitive_switchyard.process_identity")
    group = SimpleNamespace(process=SimpleNamespace(pid=1001), leader_identity="leader", check_unreaped=lambda: None)
    monkeypatch.setattr(identity_module.sys, "platform", "linux")
    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="1001\n1002\n" if command[0] == "/usr/bin/pgrep" else "1001 1001 S\n")
    monkeypatch.setattr(identity_module.subprocess, "run", fake_run)
    monkeypatch.setattr(identity_module, "process_identity", lambda pid: "leader")
    assert identity_module.owned_group_members(group) == ((1001, "leader", 0),)


def test_worker_denial_is_latched_without_retry(tmp_path, monkeypatch):
    from tests.test_worker_manager import _write_pack, _write_task_plan
    from cognitive_switchyard import worker_manager
    from cognitive_switchyard.pack_loader import load_pack_manifest

    script = tmp_path / "sleep.sh"
    script.write_text("#!/bin/sh\nexec /bin/sleep 5\n")
    script.chmod(0o755)
    manifest = load_pack_manifest(_write_pack(tmp_path, name="denial-worker", execute_script=script))
    task = _write_task_plan(tmp_path / "tasks")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = worker_manager.WorkerManager()
    manager.dispatch(slot_number=0, pack_manifest=manifest, task_plan_path=task,
                     workspace_path=workspace, log_path=tmp_path / "worker.log")
    worker = manager._workers[0]
    calls = []
    def denied(*args):
        calls.append(args)
        raise PermissionError("synthetic denial")
    monkeypatch.setattr(worker_manager, "signal_owned_group", denied)
    try:
        with pytest.raises(PermissionError):
            manager.terminate(0, reason="synthetic test")
        with pytest.raises(PermissionError):
            manager.terminate(0, reason="synthetic test")
        assert len(calls) == 1
    finally:
        worker.process.terminate()
        worker.process.wait(timeout=5)
        for reader in worker.readers:
            reader.join(timeout=5)
        worker.log_handle.close()


def test_owned_child_state_can_be_checked_without_reaping(tmp_path):
    import os
    proc = subprocess.Popen(["/bin/sleep", "0.1"], cwd=tmp_path, start_new_session=True, stdout=subprocess.PIPE)
    try:
        assert proc.stdout.read() == b""
        status = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        assert status is not None and status.si_pid == proc.pid
        assert proc.returncode is None
    finally:
        proc.wait(timeout=5)


def test_owned_group_rejects_reaped_leader_before_inspection(tmp_path, monkeypatch):
    from cognitive_switchyard.process_identity import OwnedProcessGroup, ProcessGroupInspectionError, owned_group_members
    proc = subprocess.Popen(["/bin/sleep", "0.1"], cwd=tmp_path, start_new_session=True)
    group = OwnedProcessGroup.capture(proc)
    proc.wait(timeout=5)
    calls = []
    monkeypatch.setattr("cognitive_switchyard.process_identity.subprocess.run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ProcessGroupInspectionError):
        owned_group_members(group)
    assert not calls


def test_owned_group_rejects_externally_reaped_child_before_inspection(tmp_path, monkeypatch):
    import os
    from cognitive_switchyard.process_identity import OwnedProcessGroup, ProcessGroupInspectionError, owned_group_members
    proc = subprocess.Popen(["/bin/sleep", "0.1"], cwd=tmp_path, start_new_session=True)
    group = OwnedProcessGroup.capture(proc)
    os.waitpid(proc.pid, 0)
    calls = []
    monkeypatch.setattr("cognitive_switchyard.process_identity.subprocess.run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ProcessGroupInspectionError):
        owned_group_members(group)
    assert not calls
    proc.returncode = 0


def test_explicit_deadline_cancels_owned_process_group(tmp_path):
    import os
    import time
    from cognitive_switchyard.agent_runtime import _run_bounded_process
    script = _tree_script(tmp_path)
    started = time.monotonic()
    result = _run_bounded_process([str(script)], cwd=tmp_path, env=os.environ.copy(), deadline=started + 0.2)
    assert result.returncode == 124
    assert time.monotonic() - started < 2
    time.sleep(1.1)
    assert not (tmp_path / "survived").exists()


@pytest.mark.parametrize("runtime_class", [ClaudeCliRuntime, CodexCliRuntime])
def test_planner_deadline_prevents_retry_after_budget(tmp_path, runtime_class):
    import time
    prompt = tmp_path / "prompt.md"
    prompt.write_text("synthetic")
    calls = []
    def runner(*, command, cwd, input_text, deadline):
        calls.append(deadline)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="synthetic failure")
    runtime = runtime_class(command="synthetic", subprocess_runner=runner)
    with pytest.raises(RuntimeError):
        runtime._run_phase(phase="planning", model="synthetic", prompt_path=prompt, session_root=tmp_path, input_text="synthetic", deadline=time.monotonic() + 0.1)
    assert len(calls) == 1


def test_expired_deadline_does_not_launch_process(tmp_path):
    import os
    import time
    from cognitive_switchyard.agent_runtime import _run_bounded_process
    marker = tmp_path / "launched"
    script = tmp_path / "synthetic.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    script.chmod(0o755)
    result = _run_bounded_process([str(script)], cwd=tmp_path, env=os.environ.copy(), deadline=time.monotonic() - 1)
    assert result.returncode == 124
    assert not marker.exists()
