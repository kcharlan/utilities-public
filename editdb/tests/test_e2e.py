"""Minimal real-browser smoke coverage for EditDB."""

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
LAUNCHER = PROJECT_ROOT / "editdb"
README = PROJECT_ROOT / "README.md"
USER_GUIDE = PROJECT_ROOT / "docs" / "USER_GUIDE.md"


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
    database = tmp_path_factory.mktemp("editdb-e2e") / "synthetic.sqlite"
    env = dict(os.environ, UTILITIES_TESTING="1")
    process = subprocess.Popen(
        [sys.executable, str(LAUNCHER), str(database), "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_server(port):
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail(
                "EditDB E2E server failed to start.\n"
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
    assert "--color-brand-dark-50: #f8fafc;" in source
    assert "--color-brand-dark-950: #020617;" in source
    assert "lucide@1.46.0" in source


def test_tailwind_browser_support_is_documented():
    readme = README.read_text()
    user_guide = USER_GUIDE.read_text()

    for document in (readme, user_guide):
        assert "@tailwindcss/browser" in document
        assert "4.3.3" in document
        assert "Chrome 111" in document
        assert "Safari 16.4" in document
        assert "Firefox 128" in document

    assert "Playwright" in readme
    assert "Chromium" in readme
    assert "Safari and Firefox are not covered by the automated browser test" in readme


def test_app_loads_without_browser_errors_and_opens_sql_console(server, page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.add_init_script(
        "if (localStorage.getItem('editdb_theme') === null) "
        "localStorage.setItem('editdb_theme', 'light')"
    )
    page.goto(server, wait_until="networkidle")
    page.evaluate("console.error('__console_capture_probe__')")
    assert errors == ["__console_capture_probe__"]
    errors.clear()

    app_shell = page.locator("#root > div").first
    expect(app_shell).to_be_visible()
    page.wait_for_function(
        "getComputedStyle(document.querySelector('#root > div')).backgroundColor === 'rgb(248, 250, 252)'"
    )
    assert app_shell.evaluate("element => getComputedStyle(element).backgroundColor") == "rgb(248, 250, 252)"
    assert page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--color-brand-dark-50').trim()"
    ) == "#f8fafc"

    external_script_sources = page.locator("script[src]").evaluate_all(
        """elements => elements
            .map(element => element.src)
            .filter(source => new URL(source).origin !== location.origin)"""
    )
    assert external_script_sources == [
        "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
        "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
        "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js",
        "https://unpkg.com/@babel/standalone@7.29.8/babel.min.js",
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
            "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js",
            "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
        ]
    )

    page.get_by_title("Toggle Theme").click()
    page.wait_for_function(
        "getComputedStyle(document.querySelector('#root > div')).backgroundColor === 'rgb(2, 6, 23)'"
    )
    assert page.evaluate("document.documentElement.classList.contains('dark')")
    assert page.evaluate("localStorage.getItem('editdb_theme')") == "dark"
    assert app_shell.evaluate("element => getComputedStyle(element).backgroundColor") == "rgb(2, 6, 23)"

    page.reload(wait_until="networkidle")
    expect(page.get_by_role("button", name="SQL Console")).to_be_visible()
    assert page.evaluate("document.documentElement.classList.contains('dark')")
    assert page.evaluate("localStorage.getItem('editdb_theme')") == "dark"
    assert page.locator("#root > div").first.evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) == "rgb(2, 6, 23)"

    sql_console = page.get_by_role("button", name="SQL Console")
    sql_console.click()
    expect(page.get_by_text("Raw SQL Query")).to_be_visible()
    assert errors == []
