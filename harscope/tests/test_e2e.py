"""Minimal real-browser smoke coverage for harscope."""

from __future__ import annotations

import json
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
LAUNCHER = PROJECT_ROOT / "harscope"
README = PROJECT_ROOT / "README.md"
USER_GUIDE = PROJECT_ROOT / "docs" / "USER_GUIDE.md"
TEST_README = PROJECT_ROOT / "tests" / "README.md"
TEST_PLAN = PROJECT_ROOT / "tests" / "TEST_PLAN.md"


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
    fixture = tmp_path_factory.mktemp("harscope-e2e") / "synthetic.har"
    fixture.write_text(
        json.dumps(
            {
                "log": {
                    "version": "1.2",
                    "creator": {"name": "synthetic-test", "version": "1.0"},
                    "entries": [],
                }
            }
        )
    )
    env = dict(os.environ, UTILITIES_TESTING="1")
    process = subprocess.Popen(
        [sys.executable, str(LAUNCHER), str(fixture), "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_server(port):
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail(
                "harscope E2E server failed to start.\n"
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
    assert "--color-ink: #1a1a1a;" in source
    assert "--color-card-dark: #242424;" in source
    assert "--font-sans: 'DM Sans', system-ui, sans-serif;" in source
    assert "--font-mono: 'JetBrains Mono', monospace;" in source
    assert "lucide@1.46.0" in source


def test_tailwind_browser_support_is_documented():
    documents = [
        README.read_text(),
        USER_GUIDE.read_text(),
        TEST_README.read_text(),
        TEST_PLAN.read_text(),
    ]

    for document in documents:
        assert "@tailwindcss/browser" in document
        assert "4.3.3" in document

    readme = documents[0]
    normalized_readme = " ".join(readme.split())
    assert "not byte-immutable" in readme
    assert "Playwright" in readme
    assert "Chromium" in readme
    assert "Chrome 111" in readme
    assert "Safari 16.4" in readme
    assert "Firefox 128" in readme
    assert "Safari and Firefox are not covered by the automated browser test" in normalized_readme


def test_app_loads_without_browser_errors_and_opens_security(server, page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.emulate_media(color_scheme="light")
    page.goto(server, wait_until="networkidle")
    page.evaluate("console.error('__console_capture_probe__')")
    assert errors == ["__console_capture_probe__"]
    errors.clear()

    security = page.get_by_role("button", name="Security")
    expect(security).to_be_visible()

    app_shell = page.locator("#root > div").first
    expect(app_shell).to_be_visible()
    page.wait_for_function(
        "getComputedStyle(document.querySelector('#root > div')).color === 'rgb(26, 26, 26)'"
    )
    assert app_shell.evaluate("element => getComputedStyle(element).color") == "rgb(26, 26, 26)"
    assert page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--color-ink').trim()"
    ) == "#1a1a1a"

    script_sources = page.locator("script[src]").evaluate_all(
        "elements => elements.map(element => element.src)"
    )
    assert script_sources == [
        "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
        "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js",
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
    assert dependency_resources == sorted(script_sources)

    light_header_background = page.locator("header").evaluate(
        "element => getComputedStyle(element).backgroundColor"
    )
    page.get_by_title("Toggle theme").click()
    page.wait_for_function("document.documentElement.classList.contains('dark')")
    assert page.evaluate("document.documentElement.classList.contains('dark')")
    assert app_shell.evaluate("""element => {
        const probe = document.createElement('span');
        probe.style.color = 'var(--color-gray-200)';
        document.body.appendChild(probe);
        const expected = getComputedStyle(probe).color;
        probe.remove();
        return getComputedStyle(element).color === expected;
    }""")
    assert page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--color-card-dark').trim()"
    ) == "#242424"
    assert page.locator("header").evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) != light_header_background

    security.click()
    expect(page.get_by_role("combobox", name="")).to_have_count(2)
    assert errors == []
