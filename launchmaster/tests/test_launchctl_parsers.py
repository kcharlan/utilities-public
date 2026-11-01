"""Feed synthetic launchctl output through the launcher's real readers."""
from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

UTILITIES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(UTILITIES_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_launchctl
from tools.testkit import load_launcher

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "launchmaster"
RUNNING = "com.example.synthetic-running"


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    monkeypatch.setenv("LAUNCHMASTER_HOME", str(tmp_path / "launchmaster-home"))
    module = load_launcher(SCRIPT_PATH)
    monkeypatch.setattr(module.os, "getuid", lambda: 501)
    monkeypatch.setattr(module, "PLIST_DIRS", {"user-agent": str(tmp_path)})
    return module


@pytest.fixture
def calls(launcher, monkeypatch):
    """Record every launchctl call; the fake refuses anything but queries."""
    recorded = []

    def recording_run(argv, **kwargs):
        recorded.append(argv)
        return fake_launchctl.fake_run(argv, **kwargs)

    monkeypatch.setattr(launcher.subprocess, "run", recording_run)
    return recorded


def _replace_run(launcher, monkeypatch, *, returncode=0, stdout="", stderr="", error=None):
    def replacement(argv, **kwargs):
        if error is not None:
            raise error
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(launcher.subprocess, "run", replacement)


def test_launchctl_state_parses_pid_exit_and_placeholders(launcher, calls):
    state = launcher.get_launchctl_state()

    assert calls == [["launchctl", "list"]]
    assert state == {
        RUNNING: {"pid": 424242, "last_exit": 0},
        "com.example.synthetic-failed": {"pid": None, "last_exit": 78},
        "com.example.synthetic-signalled": {"pid": None, "last_exit": -15},
        "com.example.synthetic-never-ran": {"pid": None, "last_exit": None},
        "com.example.synthetic-unparsable": {"pid": None, "last_exit": None},
        "com.example.synthetic-disabled": {"pid": None, "last_exit": 0},
        "com.apple.example-synthetic": {"pid": None, "last_exit": 0},
    }


@pytest.mark.parametrize(
    "failure",
    [
        {"returncode": 1, "stdout": fake_launchctl.LIST_OUTPUT},
        {"error": subprocess.TimeoutExpired("launchctl", 10)},
        {"error": OSError("synthetic launchctl failure")},
    ],
)
def test_launchctl_state_is_empty_when_list_fails(launcher, monkeypatch, failure):
    _replace_run(launcher, monkeypatch, **failure)

    assert launcher.get_launchctl_state() == {}


def test_disabled_labels_keep_only_disabled_services(launcher, calls):
    disabled = launcher.get_disabled_labels()

    assert calls == [["launchctl", "print-disabled", "gui/501"]]
    assert disabled == {"com.example.synthetic-disabled", "com.example.synthetic-upper"}


@pytest.mark.parametrize(
    "error",
    [subprocess.TimeoutExpired("launchctl", 10), OSError("synthetic launchctl failure")],
)
def test_disabled_labels_are_empty_when_launchctl_fails(launcher, monkeypatch, error):
    _replace_run(launcher, monkeypatch, error=error)

    assert launcher.get_disabled_labels() == set()


def test_job_detail_parses_print_fields(launcher, calls):
    detail = launcher.get_job_detail(RUNNING, "user-agent")

    assert calls == [["launchctl", "print", f"gui/501/{RUNNING}"]]
    assert detail == {
        "raw_output": fake_launchctl.PRINT_OUTPUT,
        "state": "running",
        "print_pid": 424242,
        "last_exit_code": 78,
        "print_path": "/synthetic/LaunchAgents/com.example.synthetic-running.plist",
    }


def test_job_detail_targets_the_system_domain_for_daemons(launcher, calls):
    launcher.get_job_detail("com.example.synthetic-daemon", "system-daemon")

    assert calls == [["launchctl", "print", "system/com.example.synthetic-daemon"]]


@pytest.mark.parametrize(
    "failure",
    [
        {"returncode": 113, "stdout": fake_launchctl.PRINT_OUTPUT},
        {"error": subprocess.TimeoutExpired("launchctl", 10)},
        {"error": OSError("synthetic launchctl failure")},
    ],
)
def test_job_detail_has_no_fields_when_print_fails(launcher, monkeypatch, failure):
    _replace_run(launcher, monkeypatch, **failure)

    assert launcher.get_job_detail(RUNNING, "user-agent") == {"raw_output": None}


def test_job_blame_returns_the_stripped_reason(launcher, calls):
    blame = launcher.get_job_blame(RUNNING, "user-agent")

    assert calls == [["launchctl", "blame", f"gui/501/{RUNNING}"]]
    assert blame == "speculative"


@pytest.mark.parametrize(
    "failure",
    [
        {"returncode": 113, "stdout": "speculative"},
        {"stdout": "  \n"},
        {"error": subprocess.TimeoutExpired("launchctl", 10)},
        {"error": OSError("synthetic launchctl failure")},
    ],
)
def test_job_blame_is_none_without_a_reason(launcher, monkeypatch, failure):
    _replace_run(launcher, monkeypatch, **failure)

    assert launcher.get_job_blame(RUNNING, "user-agent") is None


def test_run_launchctl_returns_stripped_output(launcher, monkeypatch):
    _replace_run(launcher, monkeypatch, returncode=3, stdout=" out\n", stderr=" err\n")

    assert launcher._run_launchctl(["kickstart", "-p", "gui/501/synthetic"]) == {
        "returncode": 3,
        "stdout": "out",
        "stderr": "err",
    }


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (subprocess.TimeoutExpired("launchctl", 10), "Command timed out"),
        (OSError("synthetic launchctl failure"), "synthetic launchctl failure"),
    ],
)
def test_run_launchctl_reports_failures(launcher, monkeypatch, error, message):
    _replace_run(launcher, monkeypatch, error=error)

    assert launcher._run_launchctl(["list"]) == {
        "returncode": -1,
        "stdout": "",
        "stderr": message,
    }


def test_job_list_merges_parsed_launchctl_state(launcher, calls, tmp_path):
    for label, extra in (
        (RUNNING, {"KeepAlive": True}),
        ("com.example.synthetic-disabled", {}),
        ("com.example.synthetic-unloaded", {}),
    ):
        with (tmp_path / f"{label}.plist").open("wb") as plist:
            plistlib.dump({"Label": label, "ProgramArguments": ["/usr/bin/true"], **extra}, plist)

    jobs = {job["label"]: job for job in launcher.build_job_list(include_apple=True)}

    running = jobs[RUNNING]
    assert (running["pid"], running["status"], running["enabled"]) == (424242, "running", True)
    disabled = jobs["com.example.synthetic-disabled"]
    assert (disabled["status"], disabled["enabled"]) == ("disabled", False)
    assert jobs["com.example.synthetic-unloaded"]["status"] == "unloaded"
    orphan = jobs["com.example.synthetic-failed"]
    assert (orphan["plist_path"], orphan["status"], orphan["last_exit"]) == (None, "failed", 78)
    assert jobs["com.apple.example-synthetic"]["is_apple"] is True


def test_job_list_hides_apple_labels_unless_requested(launcher, calls):
    labels = {job["label"] for job in launcher.build_job_list(include_apple=False)}

    assert RUNNING in labels
    assert "com.apple.example-synthetic" not in labels
