import base64
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import load_launcher

SCRIPT = Path(__file__).resolve().parents[1] / "storage_monitor"


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT)
    module.ensure_runtime_home(module.RUNTIME_PATHS)
    return module


def test_stale_pid_does_not_signal_unrelated_sleeper(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    sleeper = subprocess.Popen(["/bin/sleep", "30"])
    try:
        module.RUNTIME_PATHS.pid_file.write_text(str(sleeper.pid))
        module.kill_prior_instance()
        assert sleeper.poll() is None
    finally:
        sleeper.terminate()
        sleeper.wait()


def test_second_instance_cannot_claim_held_lock(monkeypatch, tmp_path):
    first = load(monkeypatch, tmp_path)
    first.kill_prior_instance()
    first.write_pid_file()
    second = load(monkeypatch, tmp_path)
    try:
        with pytest.raises(SystemExit, match="already running"):
            second.kill_prior_instance()
    finally:
        first._pid_lock.close()


def test_action_tokens_are_authenticated_and_run_specific(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    token = module.encode_action_token({"kind": "trash_path", "path": "/synthetic/a"})
    forged = base64.urlsafe_b64encode(json.dumps({"kind": "trash_path", "path": "/synthetic/b"}).encode()).decode()
    with pytest.raises(Exception):
        module.decode_action_token(forged)
    other = load(monkeypatch, tmp_path)
    with pytest.raises(Exception):
        other.decode_action_token(token)


def test_nonactionable_finding_cannot_execute(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    token = module.encode_action_token({"kind": "trash_path", "path": str(tmp_path / "target")})
    module.STATE.report = {"findings": {"items": [{"actionable": False, "action_token": token}]}}
    with pytest.raises(HTTPException):
        module.resolve_action(token)


def test_trash_rejects_symlinked_target(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    target = tmp_path / "target"
    target.write_text("synthetic")
    link = tmp_path / "link"
    link.symlink_to(target)
    monkeypatch.setattr(module, "DATA_VOLUME", tmp_path)
    monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "trash")
    with pytest.raises(HTTPException):
        module.execute_trash_path(link)
    assert target.exists() and link.is_symlink()


def test_reveal_rejects_outside_roots_and_uses_finder_reveal(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setattr(module, "ALLOWED_BREAKDOWN_ROOTS", [root])
    calls = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda args: calls.append(args))
    module.reveal_path(str(root))
    assert calls == [["open", "-R", "--", str(root)]]
    with pytest.raises(HTTPException):
        module.reveal_path(str(tmp_path))


def test_reveal_rejects_excluded_mount(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "allowed"
    excluded = root / "Volumes"
    excluded.mkdir(parents=True)
    monkeypatch.setattr(module, "ALLOWED_BREAKDOWN_ROOTS", [root])
    monkeypatch.setattr(module, "EXCLUDED_BREAKDOWN_PATHS", [excluded])
    monkeypatch.setattr(module.subprocess, "Popen", lambda args: None)
    with pytest.raises(HTTPException):
        module.reveal_path(str(excluded))


def test_sse_initial_yield_does_not_hold_state_lock(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    module.STATE.report = {"synthetic": "report"}
    stream = module.sse_event_stream()
    next(stream)
    acquired = []
    def probe():
        locked = module.STATE.lock.acquire(timeout=0.2)
        acquired.append(locked)
        if locked:
            module.STATE.lock.release()
    thread = threading.Thread(target=probe)
    thread.start()
    thread.join()
    stream.close()
    assert acquired == [True]


def test_stalled_walker_is_terminated(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    walker = tmp_path / "stalled-walker"
    walker.write_text("#!/bin/sh\nexec /bin/sleep 30\n")
    walker.chmod(0o755)
    monkeypatch.setenv("STORAGE_MONITOR_WALKER", str(walker))
    monkeypatch.setattr(module, "WALKER_NO_PROGRESS_TIMEOUT", 0.2, raising=False)
    with pytest.raises(RuntimeError, match="progress|stalled|timeout"):
        module.walk_tree(tmp_path)


def test_stalled_walker_while_sending_inodes_is_terminated(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    walker = tmp_path / "stalled-walker"
    walker.write_text("#!/bin/sh\nexec /bin/sleep 3\n")
    walker.chmod(0o755)
    monkeypatch.setenv("STORAGE_MONITOR_WALKER", str(walker))
    monkeypatch.setattr(module, "WALKER_NO_PROGRESS_TIMEOUT", 0.2)
    with pytest.raises(RuntimeError, match="progress|stalled|timeout"):
        module.walk_tree(tmp_path, registered_inodes=set(range(100000)))


def test_runtime_home_is_private(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    assert module.RUNTIME_PATHS.home.stat().st_mode & 0o777 == 0o700
    assert module.RUNTIME_PATHS.history_dir.stat().st_mode & 0o777 == 0o700


def test_runtime_files_are_private(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    module.initialize_scan_db(module.RUNTIME_PATHS)
    module.atomic_write_json(module.RUNTIME_PATHS.latest_scan, {"synthetic": True})
    module.append_jsonl(module.RUNTIME_PATHS.action_log, {"synthetic": True})
    for path in (module.RUNTIME_PATHS.scan_db, module.RUNTIME_PATHS.latest_scan, module.RUNTIME_PATHS.action_log):
        assert path.stat().st_mode & 0o777 == 0o600
