"""Minimal real-browser smoke coverage for Expense Dock."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_ROOT / "expense_dock"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 10) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _find_free_port()
    runtime_home = tmp_path_factory.mktemp("expense-dock-e2e")
    env = dict(
        os.environ,
        UTILITIES_TESTING="1",
        EXPENSE_DOCK_HOME=str(runtime_home),
    )
    process = subprocess.Popen(
        [sys.executable, str(LAUNCHER), "--port", str(port), "--no-browser"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_server(port):
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail(
                "Expense Dock E2E server failed to start.\n"
                f"stdout: {stdout.decode(errors='replace')}\n"
                f"stderr: {stderr.decode(errors='replace')}"
            )
        yield f"http://127.0.0.1:{port}"
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_supported_cdn_versions_are_pinned():
    source = LAUNCHER.read_text()
    assert "react@18.3.1" in source
    assert "react-dom@18.3.1" in source
    assert "@babel/standalone@7.29.8" in source
    assert "cdn.tailwindcss.com/3.4.17" in source
    assert "lucide@1.46.0" in source


def test_app_loads_without_browser_errors_and_opens_setup(server, page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.goto(server, wait_until="networkidle")
    page.evaluate("console.error('__console_capture_probe__')")
    assert errors == ["__console_capture_probe__"]
    errors.clear()

    setup = page.get_by_role("button", name="Setup Connection and defaults")
    expect(setup).to_be_visible()
    setup.click()
    expect(page.get_by_text("OneDrive + workbook settings")).to_be_visible()
    assert errors == []
