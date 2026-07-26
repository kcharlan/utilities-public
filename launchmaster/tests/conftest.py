"""
Shared fixtures for launchmaster tests.

Test categories:
    Unit tests:  pytest tests/ -v --ignore=tests/test_e2e.py
    E2E tests:   pytest tests/test_e2e.py -v
    All:         pytest tests/ -v
"""

import json
import os
import plistlib
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

import pytest

# ── Enforce UTILITIES_TESTING so browser-opening code is always suppressed ────
# Set it if not already set, so test runs never steal focus.
os.environ["UTILITIES_TESTING"] = "1"

PROJECT_ROOT = Path(__file__).parent.parent
LAUNCHMASTER_SCRIPT = PROJECT_ROOT / "launchmaster"


# ── Server fixture for integration/E2E tests ─────────────────────────────────

def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port, timeout=15):
    """Wait until the server responds to /api/health."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2)
            if resp.status == 200:
                return True
        except Exception:
            time.sleep(0.5)
    return False


def _synthetic_job(
    label: str,
    *,
    plist_path: str | None,
    domain: str,
    is_apple: bool,
    last_exit: int,
) -> Dict[str, Any]:
    """Build a complete, conspicuously fake launchd job response."""
    job = {
        "label": label,
        "plist_path": plist_path,
        "domain": domain,
        "is_apple": is_apple,
        "parse_error": None,
        "pid": None,
        "last_exit": last_exit,
        "loaded": True,
        "disabled": False,
        "enabled": True,
        "program": "/usr/bin/true" if plist_path else None,
        "program_arguments": ["/usr/bin/true"] if plist_path else None,
        "run_at_load": False,
        "keep_alive": False,
        "start_interval": None,
        "start_calendar_interval": None,
        "watch_paths": None,
        "stdout_path": None,
        "stderr_path": None,
        "working_directory": None,
        "environment_variables": None,
        "schedule_human": "Manual" if plist_path else "Unknown (no plist)",
    }
    job["status"] = "failed" if last_exit else "idle"
    return job


def _write_synthetic_jobs(runtime_home: Path) -> Path:
    """Create the E2E-only job manifest and its exportable fake plist."""
    plist_path = runtime_home / "com.example.synthetic-idle.plist"
    with plist_path.open("wb") as f:
        plistlib.dump(
            {
                "Label": "com.example.synthetic-idle",
                "ProgramArguments": ["/usr/bin/true"],
            },
            f,
        )

    synthetic_jobs = [
        _synthetic_job(
            "com.example.synthetic-idle",
            plist_path=str(plist_path),
            domain="user-agent",
            is_apple=False,
            last_exit=0,
        ),
        _synthetic_job(
            "com.apple.example-synthetic",
            plist_path=None,
            domain="unknown",
            is_apple=True,
            last_exit=0,
        ),
        _synthetic_job(
            "com.example.synthetic-failed",
            plist_path=None,
            domain="user-agent",
            is_apple=False,
            last_exit=78,
        ),
    ]
    manifest_path = runtime_home / "synthetic-jobs.json"
    manifest_path.write_text(json.dumps(synthetic_jobs, indent=2) + "\n")
    return manifest_path


@contextmanager
def _running_server(runtime_home: Path, *, with_synthetic_jobs: bool = False):
    """Run one isolated launchmaster server and always terminate it."""
    port = _find_free_port()
    env = dict(os.environ)
    env["UTILITIES_TESTING"] = "1"
    env["LAUNCHMASTER_HOME"] = str(runtime_home)
    env.pop("LAUNCHMASTER_SYNTHETIC_JOBS", None)
    if with_synthetic_jobs:
        env["LAUNCHMASTER_SYNTHETIC_JOBS"] = str(
            _write_synthetic_jobs(runtime_home)
        )

    proc = subprocess.Popen(
        [sys.executable, str(LAUNCHMASTER_SCRIPT), "--port", str(port), "--no-browser"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        if not _wait_for_server(port):
            proc.kill()
            stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
            stdout = stdout_bytes.decode(errors="replace")
            stderr = stderr_bytes.decode(errors="replace")
            pytest.fail(
                f"launchmaster failed to start on port {port}.\n"
                f"stdout: {stdout[:2000]}\nstderr: {stderr[:2000]}"
            )
        yield f"http://127.0.0.1:{port}"
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


@pytest.fixture(scope="session")
def server_url(tmp_path_factory):
    """Run the API/integration server with isolated runtime state."""
    with _running_server(tmp_path_factory.mktemp("launchmaster-api-home")) as url:
        yield url


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """Run a separate E2E server so browser tests cannot share API-suite state."""
    with _running_server(
        tmp_path_factory.mktemp("launchmaster-e2e-home"),
        with_synthetic_jobs=True,
    ) as url:
        yield url


@pytest.fixture
def restore_settings(server):
    """Restore the module-scoped E2E server settings after a mutating test."""
    import urllib.request

    with urllib.request.urlopen(f"{server}/api/settings") as response:
        snapshot = json.loads(response.read().decode())
    try:
        yield snapshot
    finally:
        request = urllib.request.Request(
            f"{server}/api/settings",
            data=json.dumps(snapshot).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(request):
            pass


@pytest.fixture(scope="session")
def api_jobs(server_url) -> list:
    """Fetch all jobs (including Apple) from the running server."""
    import urllib.request
    resp = urllib.request.urlopen(f"{server_url}/api/jobs?include_apple=true")
    return json.loads(resp.read().decode())


@pytest.fixture(scope="session")
def api_jobs_no_apple(server_url) -> list:
    """Fetch non-Apple jobs from the running server."""
    import urllib.request
    resp = urllib.request.urlopen(f"{server_url}/api/jobs?include_apple=false")
    return json.loads(resp.read().decode())


@pytest.fixture(scope="session")
def launchctl_state() -> Dict[str, Dict[str, Any]]:
    """Get the real launchctl list state for comparison."""
    result = subprocess.run(
        ["launchctl", "list"], capture_output=True, text=True, timeout=10
    )
    state = {}
    for line in result.stdout.splitlines()[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) == 3:
            pid_str, status_str, label = parts
            pid = int(pid_str) if pid_str != "-" else None
            last_exit = int(status_str) if status_str != "-" else None
            state[label] = {"pid": pid, "last_exit": last_exit}
    return state


@pytest.fixture(scope="session")
def disabled_labels() -> set:
    """Get the set of explicitly disabled job labels from launchctl."""
    uid = os.getuid()
    disabled = set()
    try:
        result = subprocess.run(
            ["launchctl", "print-disabled", f"gui/{uid}"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if "=>" in line:
                label_part, state_part = line.split("=>", 1)
                label = label_part.strip().strip('"')
                if "disabled" in state_part.lower():
                    disabled.add(label)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return disabled
