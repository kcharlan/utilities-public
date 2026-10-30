import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
UTILITIES_ROOT = PROJECT_DIR.parent
sys.path.insert(0, str(UTILITIES_ROOT))
sys.path.insert(0, str(PROJECT_DIR))


@pytest.fixture(autouse=True)
def isolation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("TRANSCRIPTION_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CUMULATIVE_JSON_PATH", str(tmp_path / "session.json"))
    monkeypatch.setenv("LIFETIME_TXT_PATH", str(tmp_path / "lifetime.txt"))


@pytest.fixture
def server_cycle():
    def cycle(argv, cwd, env):
        port = int(argv[argv.index("--port") + 1])
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        pgid = process.pid
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail(f"server exited early: {process.returncode}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        assert response.status == 200
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                        assert response.status == 200 and response.read() == b"ok"
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                pytest.fail("server did not become healthy")
            os.killpg(pgid, signal.SIGINT)
            assert process.wait(timeout=15) == 0
            with pytest.raises(ProcessLookupError):
                os.killpg(pgid, 0)
        finally:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)
    return cycle
