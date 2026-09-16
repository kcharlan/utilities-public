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
README = PROJECT_ROOT / "README.md"


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
    assert "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3" in source
    assert "cdn.tailwindcss.com" not in source
    assert "tailwind.config" not in source
    assert '<style type="text/tailwindcss">' in source
    assert "@custom-variant dark (&:where(.dark, .dark *));" in source
    assert "--font-display: 'Fraunces', serif;" in source
    assert "--font-body: 'Work Sans', sans-serif;" in source
    assert "--font-mono: 'IBM Plex Mono', monospace;" in source
    assert "--shadow-docket: 0 24px 80px rgba(16, 24, 40, 0.18);" in source
    assert "--color-ledger-paper: #f7f0df;" in source
    assert "--color-ledger-sand: #dccfaf;" in source
    assert "lucide@1.46.0" in source


def test_tailwind_browser_support_is_documented():
    readme = README.read_text()
    normalized_readme = " ".join(readme.split())

    assert "@tailwindcss/browser" in readme
    assert "4.3.3" in readme
    assert "not byte-immutable" in readme
    assert "Playwright" in readme
    assert "Chromium" in readme
    assert "Chrome 111" in readme
    assert "Safari 16.4" in readme
    assert "Firefox 128" in readme
    assert "Safari and Firefox are not covered by the automated browser test" in normalized_readme


def test_app_loads_without_browser_errors_and_opens_setup(server, page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.add_init_script(
        "if (localStorage.getItem('expenseDockTheme') === null) "
        "localStorage.setItem('expenseDockTheme', 'light')"
    )
    page.goto(server, wait_until="networkidle")
    page.evaluate("console.error('__console_capture_probe__')")
    assert errors == ["__console_capture_probe__"]
    errors.clear()

    title = page.get_by_role("heading", name="Expense Dock")
    expect(title).to_be_visible()
    page.wait_for_function(
        "getComputedStyle(document.querySelector('h1')).fontFamily.includes('Fraunces')"
    )
    assert "Fraunces" in title.evaluate(
        "element => getComputedStyle(element).fontFamily"
    )

    script_sources = page.locator("script[src]").evaluate_all(
        "elements => elements.map(element => element.src)"
    )
    assert script_sources == [
        "https://unpkg.com/react@18.3.1/umd/react.development.js",
        "https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js",
        "https://unpkg.com/@babel/standalone@7.29.8/babel.min.js",
        "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
        "https://unpkg.com/lucide@1.46.0/dist/umd/lucide.min.js",
    ]

    dependency_resources = page.evaluate(
        """() => performance.getEntriesByType('resource')
            .map(entry => entry.name)
            .filter(name =>
                name.includes('@tailwindcss/browser') ||
                name.includes('@babel/standalone') ||
                name.includes('/lucide@') ||
                name.includes('/react@') ||
                name.includes('/react-dom@') ||
                name.includes('/react-is@')
            )
            .sort()"""
    )
    assert dependency_resources == sorted(
        [
            "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
            "https://unpkg.com/@babel/standalone@7.29.8/babel.min.js",
            "https://unpkg.com/lucide@1.46.0/dist/umd/lucide.min.js",
            "https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js",
            "https://unpkg.com/react@18.3.1/umd/react.development.js",
        ]
    )

    setup = page.get_by_role("button", name="Setup Connection and defaults")
    expect(setup).to_be_visible()
    setup.click()
    expect(page.get_by_text("OneDrive + workbook settings")).to_be_visible()

    client_id = page.get_by_role("textbox", name="Microsoft client ID")
    assert client_id.evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) == "rgb(255, 255, 255)"

    page.get_by_role("button", name="Dark").click()
    page.wait_for_function(
        "getComputedStyle(document.querySelector('input')).backgroundColor === 'rgb(26, 51, 39)'"
    )
    assert page.evaluate("document.documentElement.classList.contains('dark')")
    assert page.evaluate("localStorage.getItem('expenseDockTheme')") == "dark"
    assert client_id.evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) == "rgb(26, 51, 39)"

    page.reload(wait_until="networkidle")
    assert page.evaluate("document.documentElement.classList.contains('dark')")
    assert page.evaluate("localStorage.getItem('expenseDockTheme')") == "dark"
    expect(page.get_by_role("button", name="Light")).to_be_visible()
    assert errors == []
