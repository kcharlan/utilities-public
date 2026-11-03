import os
import signal
import subprocess
import time

from benchmark_llm.execution import run_command


def _live(pid):
    result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    if result.returncode != 0:
        if result.returncode == 1 and not result.stderr.strip():
            return False
        raise RuntimeError(f"Cannot inspect recorded PID {pid}: {result.stderr.strip()}")
    return any(not line.strip().startswith("Z") for line in result.stdout.splitlines() if line.strip())


def test_timeout_stops_grandchild_that_ignores_term(tmp_path):
    pidfile = tmp_path / "child.pid"
    command = "sh -c 'trap \"\" TERM; echo $$ > \"$1\"; while :; do sleep 1; done' sh " + str(pidfile) + " & wait"
    pid = None
    result = run_command(command, tmp_path, os.environ.copy(), "execute", timeout_sec=1)
    pid = int(pidfile.read_text())
    assert result["timed_out"]
    for _ in range(30):
        if not _live(pid):
            break
        time.sleep(0.1)
    else:
        raise AssertionError(f"grandchild {pid} survived timeout")


def test_interrupted_attempt_removes_worktree_and_branch(tmp_path):
    import subprocess
    import pytest
    from benchmark_llm.repo_task import run_repo_task

    source = tmp_path / "source"
    source.mkdir()
    def git(*args):
        return subprocess.run(["git", "-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid", *args], cwd=source, check=True, capture_output=True, text=True).stdout
    git("init")
    (source / "seed").write_text("seed")
    git("add", "seed")
    git("commit", "-m", "seed")
    benchmark = tmp_path / "benchmark"
    benchmark.mkdir()
    config = {"id": "synthetic", "output_dir": str(tmp_path / "results"), "workspace": {"kind": "git_worktree", "source_repo": str(source)}, "steps": []}
    def interrupt(event):
        if event["event"] == "attempt_start":
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run_repo_task(benchmark, tmp_path / "runtime", "fake", {}, config=config, progress_callback=interrupt)
    assert len(git("worktree", "list", "--porcelain").split("worktree ")) == 2
    assert not git("branch", "--list", "bench/*").strip()
    assert not list((tmp_path / "results").iterdir())


def test_interrupt_stops_command_group(tmp_path, monkeypatch):
    import pytest
    import benchmark_llm.execution as execution

    pidfile = tmp_path / "child.pid"
    command = "sh -c 'echo $$ > \"$1\"; exec sleep 30' sh " + str(pidfile) + " & wait"
    real_sleep = time.sleep
    def interrupt(_seconds):
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text().strip():
                raise KeyboardInterrupt
            real_sleep(0.01)
        raise AssertionError("child did not start")
    monkeypatch.setattr(execution.time, "sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run_command(command, tmp_path, os.environ.copy(), "execute")
    pid = int(pidfile.read_text())
    for _ in range(100):
        if not _live(pid):
            break
        real_sleep(0.01)
    else:
        raise AssertionError(f"child {pid} survived interruption")


def test_outer_timeout_stops_detached_validator_child_and_grandchild(tmp_path):
    import shlex
    import sys
    from pathlib import Path

    project = Path(__file__).resolve().parents[1]
    validator = project / "examples/cron-eval/scripts/run_checks.py"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pidfile = tmp_path / "pids"
    (workspace / "cron_eval.py").write_text(
        "import os, subprocess, time\n"
        "child = subprocess.Popen(['sh', '-c', 'trap \"\" TERM; exec sleep 60'])\n"
        "time.sleep(0.2)\n"
        f"open({str(pidfile)!r}, 'w').write(f'{{os.getpid()}} {{child.pid}}')\n"
        "time.sleep(60)\n"
    )
    wrapper = (
        "import importlib.util; "
        f"s=importlib.util.spec_from_file_location('validator', {str(validator)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        f"m._run_model(__import__('pathlib').Path({str(workspace)!r}), [])"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(wrapper)}"
    result = run_command(command, tmp_path, os.environ.copy(), "validate", timeout_sec=2)
    assert result.get("timed_out")
    pids = [int(value) for value in pidfile.read_text().split()]
    assert len(pids) == 2
    for _ in range(40):
        survivors = [pid for pid in pids if _live(pid)]
        if not survivors:
            break
        time.sleep(0.05)
    assert not survivors, f"validator descendants survived: {survivors}"


def test_validator_handles_sigterm_during_child_spawn(tmp_path, monkeypatch):
    import importlib.util
    import subprocess
    from pathlib import Path
    import pytest

    validator_path = Path(__file__).resolve().parents[1] / "examples/cron-eval/scripts/run_checks.py"
    spec = importlib.util.spec_from_file_location("synthetic_validator_spawn", validator_path)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "cron_eval.py").write_text("import time\ntime.sleep(60)\n")
    previous_handler = signal.getsignal(signal.SIGTERM)
    real_popen = subprocess.Popen
    children = []

    def interrupt_spawn(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        if not children:
            children.append(child)
            os.kill(os.getpid(), signal.SIGTERM)
        return child

    monkeypatch.setattr(validator.subprocess, "Popen", interrupt_spawn)
    with pytest.raises(SystemExit) as exc:
        validator._run_model(workspace, [])
    assert exc.value.code == 128 + signal.SIGTERM
    assert children[0].poll() is not None
    assert signal.getsignal(signal.SIGTERM) == previous_handler


def test_timeout_allows_descendant_to_finish_term_cleanup(tmp_path, monkeypatch):
    import shlex
    import benchmark_llm.execution as execution

    ready = tmp_path / "ready"
    finished = tmp_path / "finished"
    calls = []
    real_signal = execution.signal_owned_group

    def record_signal(group, signum):
        calls.append((group.process.pid, signum))
        return real_signal(group, signum)

    monkeypatch.setattr(execution, "signal_owned_group", record_signal)
    script = (
        f"trap 'sleep 0.3; echo done > {shlex.quote(str(finished))}; exit' TERM; "
        f"echo ready > {shlex.quote(str(ready))}; while :; do sleep 1; done"
    )
    command = f"sh -c {shlex.quote(script)} & wait"
    result = run_command(command, tmp_path, os.environ.copy(), "validate", timeout_sec=2)
    assert ready.exists()
    assert result.get("timed_out")
    assert finished.read_text().strip() == "done", f"group signals: {calls}"
    assert [signum for _, signum in calls] == [signal.SIGTERM, signal.SIGKILL], calls


def test_cleanup_permission_denial_is_not_retried(tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace
    import benchmark_llm.execution as execution

    class SyntheticProcess:
        pid = 987654321
        returncode = None
        def poll(self):
            return None
        def wait(self, timeout=None):
            return 0

    attempts = []
    process = SyntheticProcess()
    monkeypatch.setattr(execution.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(execution.OwnedProcessGroup, "capture", lambda child: SimpleNamespace(process=child))
    monkeypatch.setattr(execution.os, "waitid", lambda *args: None)
    def deny(group, sig):
        attempts.append((group.process.pid, sig))
        raise PermissionError("synthetic signal denial")
    monkeypatch.setattr(execution, "signal_owned_group", deny)
    with pytest.raises(PermissionError, match="synthetic signal denial") as exc:
        run_command("unused", tmp_path, {}, "validate", timeout_sec=0)
    assert attempts == [(987654321, signal.SIGTERM)]
    assert "987654321" in exc.value.__notes__[0]


import pytest


@pytest.mark.parametrize("interrupt_at", ["poll", "command_start", "command_end"])
def test_interrupted_command_removes_its_temporary_output_logs(tmp_path, monkeypatch, interrupt_at):
    import tempfile
    import benchmark_llm.execution as execution

    private_tmp = tmp_path / "private-tmp"
    private_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private_tmp))
    if interrupt_at == "poll":
        def interrupt(_seconds):
            raise KeyboardInterrupt
        monkeypatch.setattr(execution.time, "sleep", interrupt)
        callback = None
    else:
        def callback(event):
            if event["event"] == interrupt_at:
                raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run_command(
            "sleep 30" if interrupt_at == "poll" else "true",
            tmp_path,
            os.environ.copy(),
            "execute",
            progress_callback=callback,
        )
    assert sorted(path.name for path in private_tmp.glob("benchmark-llm-std*")) == []
