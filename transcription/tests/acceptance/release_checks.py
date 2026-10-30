import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mode", ["app", "divider"])
def test_shebang_launch_starts_and_stops(mode, tmp_path, server_cycle):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    launcher = Path(os.environ.get("TRANSCRIPTION_LAUNCHER", PROJECT_DIR / "transcription"))
    env = os.environ.copy()
    env["UV_PYTHON_DOWNLOADS"] = "never"
    server_cycle([str(launcher), mode, "--no-browser", "--port", str(port)], tmp_path, env)


def test_write_environment_freeze():
    destination = Path(os.environ["TRANSCRIPTION_ACCEPTANCE_DIR"]) / "freeze.txt"
    with destination.open("w") as output:
        subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], stdout=output, check=True)
