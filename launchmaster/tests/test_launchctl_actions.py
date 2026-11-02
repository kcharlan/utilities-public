"""Verify action commands without contacting launchd."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import load_launcher


@pytest.fixture
def launcher(monkeypatch):
    module = load_launcher(Path(__file__).resolve().parents[1] / "launchmaster")
    monkeypatch.setattr(module.os, "getuid", lambda: 501)
    return module


def threaded(coro):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


def test_native_tools_are_refused():
    for program in ("launchctl", "/usr/bin/log"):
        with pytest.raises(RuntimeError, match="native launchd tool refused"):
            subprocess.run([program, "list"])
    assert subprocess.run(["true"]).returncode == 0


@pytest.mark.parametrize("domain,prefix", [("user-agent", "gui/501"), ("system-daemon", "system")])
@pytest.mark.parametrize("action,codes,expected", [
    ("start_job", [0], [["kickstart", "-p", "T"]]),
    ("run_now_job", [0], [["kickstart", "T"]]),
    ("stop_job", [1, 0], [["kill", "SIGTERM", "T"], ["kill", "SIGKILL", "T"]]),
    ("enable_job", [0], [["enable", "T"]]),
    ("disable_job", [0], [["disable", "T"]]),
    ("reload_job", [0, 0], [["bootout", "T"], ["bootstrap", "P", "F"]]),
    ("load_job", [1, 0], [["bootstrap", "P", "F"], ["load", "F"]]),
    ("unload_job", [1, 0], [["bootout", "T"], ["unload", "F"]]),
])
def test_action_argv(launcher, monkeypatch, domain, prefix, action, codes, expected):
    calls = []
    codes = iter(codes)

    def record(argv, timeout=10):
        calls.append(argv)
        return {"returncode": next(codes), "stdout": "", "stderr": "synthetic failure"}

    async def no_sleep(_delay):
        pass

    monkeypatch.setattr(launcher, "_run_launchctl", record)
    monkeypatch.setattr(launcher.asyncio, "sleep", no_sleep)
    plist = "/synthetic/example.plist"
    args = (plist, domain) if action == "load_job" else ("L", domain)
    if action in {"reload_job", "unload_job"}:
        args += (plist,)
    result = threaded(getattr(launcher, action)(*args))
    values = {"T": f"{prefix}/L", "P": prefix, "F": plist}
    assert calls == [[values.get(part, part) for part in argv] for argv in expected]
    assert result["success"] is True


@pytest.mark.parametrize("domain,prefix", [("user-agent", "gui/501"), ("system-daemon", "system")])
def test_unload_without_plist_does_not_fall_back(launcher, monkeypatch, domain, prefix):
    calls = []

    def record(argv, timeout=10):
        calls.append(argv)
        return {"returncode": 1, "stdout": "", "stderr": "synthetic failure"}

    monkeypatch.setattr(launcher, "_run_launchctl", record)
    result = threaded(launcher.unload_job("L", domain, ""))
    assert calls == [["bootout", f"{prefix}/L"]]
    assert result["success"] is False
