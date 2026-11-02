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

from fake_launchctl import read_line_within

# ── Enforce UTILITIES_TESTING so browser-opening code is always suppressed ────
# Set it if not already set, so test runs never steal focus.
os.environ["UTILITIES_TESTING"] = "1"

PROJECT_ROOT = Path(__file__).parent.parent
LAUNCHMASTER_SCRIPT = PROJECT_ROOT / "launchmaster"


@pytest.fixture(autouse=True)
def _refuse_native_launchd(monkeypatch):
    """Prevent in-process tests from invoking native launchd tools."""
    real_run = subprocess.run

    def guarded(argv, *args, **kwargs):
        first = argv[0] if isinstance(argv, (list, tuple)) else str(argv).split()[0]
        if os.path.basename(str(first)) in {"launchctl", "log"}:
            raise RuntimeError(f"native launchd tool refused in tests: {argv!r}")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)


@pytest.fixture(scope="session")
def base_url(pytestconfig):
    """Match Playwright's fallback without its deprecated instance fixture."""
    return pytestconfig.getoption("--base-url") or pytestconfig.getini("base_url") or None


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
    log_path = runtime_home / "synthetic.log"
    log_path.write_text("Synthetic log line\n")
    with plist_path.open("wb") as f:
        plistlib.dump(
            {
                "Label": "com.example.synthetic-idle",
                "ProgramArguments": ["/usr/bin/true"],
                "StandardOutPath": str(log_path),
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
        _synthetic_job(
            "com.example.synthetic-disabled",
            plist_path=None,
            domain="unknown",
            is_apple=False,
            last_exit=0,
        ),
    ]
    for suffix, schedule in (
        ("calendar", {"StartCalendarInterval": {"Weekday": 1, "Hour": 9, "Minute": 30}}),
        ("interval", {"StartInterval": 300}),
        ("running", {"KeepAlive": True}),
        ("watch", {"WatchPaths": ["/synthetic/input"]}),
    ):
        label = f"com.example.synthetic-{suffix}"
        path = runtime_home / f"{label}.plist"
        with path.open("wb") as f:
            plistlib.dump({"Label": label, "ProgramArguments": ["/usr/bin/true"], **schedule}, f)
        job = _synthetic_job(label, plist_path=str(path), domain="user-agent", is_apple=False, last_exit=0)
        if suffix == "running":
            job["pid"] = 424242
        synthetic_jobs.append(job)
    manifest_path = runtime_home / "synthetic-jobs.json"
    manifest_path.write_text(json.dumps(synthetic_jobs, indent=2) + "\n")
    return manifest_path


@contextmanager
def _running_server(runtime_home: Path, script: Path = LAUNCHMASTER_SCRIPT):
    """Run one isolated launchmaster server and always terminate it."""
    port = _find_free_port()
    env = dict(os.environ)
    env["UTILITIES_TESTING"] = "1"
    env["LAUNCHMASTER_HOME"] = str(runtime_home)
    env["LAUNCHMASTER_SYNTHETIC_JOBS"] = str(_write_synthetic_jobs(runtime_home))

    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "tests" / "synthetic_server.py"), str(script), str(port)],
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
    """Run the API/integration server with synthetic jobs and isolated state."""
    with _running_server(tmp_path_factory.mktemp("launchmaster-api-home")) as url:
        yield url


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """Run a separate E2E server so browser tests cannot share API-suite state."""
    with _running_server(tmp_path_factory.mktemp("launchmaster-e2e-home")) as url:
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
            headers={"Content-Type": "application/json", "Origin": server},
            method="PUT",
        )
        with urllib.request.urlopen(request):
            pass


@pytest.fixture
def synthetic_server_probe(tmp_path):
    """Serve a stand-in launcher through synthetic_server.py to test its guards."""
    script = tmp_path / "probe_launcher.py"
    script.write_text(
        "import subprocess\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "def build_job_list():\n"
        "    return []\n"
        "@app.get('/api/health')\n"
        "def health():\n"
        "    return {}\n"
        "@app.get('/api/probe')\n"
        "def probe():\n"
        "    try:\n"
        "        subprocess.run(['/usr/bin/true'])\n"
        "    except RuntimeError as exc:\n"
        "        return {'refused': str(exc)}\n"
        "    return {'refused': None}\n"
    )
    with _running_server(tmp_path, script) as url:
        yield url


@pytest.fixture
def faked_launchctl_main(tmp_path):
    """Boot the real main() in a child with launchctl faked and plists confined."""
    port = _find_free_port()
    env = dict(os.environ)
    env["UTILITIES_TESTING"] = "1"
    env["LAUNCHMASTER_HOME"] = str(tmp_path / "launchmaster-home")
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "tests" / "fake_launchctl.py"), str(LAUNCHMASTER_SCRIPT), str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        startup_output = read_line_within(proc.stdout, timeout=30)
        if startup_output is None or not _wait_for_server(port):
            proc.kill()
            stdout, stderr = proc.communicate(timeout=5)
            pytest.fail(f"main() did not serve.\nstdout: {stdout[:2000]}\nstderr: {stderr[:2000]}")
        yield f"http://127.0.0.1:{port}", startup_output
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate(timeout=5)


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
