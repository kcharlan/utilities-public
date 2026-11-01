import os
import signal
import time

from benchmark_llm.execution import run_command


def test_timeout_stops_grandchild_that_ignores_term(tmp_path):
    pidfile = tmp_path / "child.pid"
    command = "sh -c 'trap \"\" TERM; echo $$ > \"$1\"; while :; do sleep 1; done' sh " + str(pidfile) + " & wait"
    pid = None
    try:
        result = run_command(command, tmp_path, os.environ.copy(), "execute", timeout_sec=1)
        pid = int(pidfile.read_text())
        assert result["timed_out"]
        for _ in range(30):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("grandchild survived timeout")
    finally:
        if pid is not None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


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
    try:
        with pytest.raises(KeyboardInterrupt):
            run_command(command, tmp_path, os.environ.copy(), "execute")
        pid = int(pidfile.read_text())
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            real_sleep(0.01)
        else:
            raise AssertionError("child survived interruption")
    finally:
        if pidfile.exists() and pidfile.read_text().strip():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
