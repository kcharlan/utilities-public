"""Minimal real-browser smoke coverage for jtree."""

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
LAUNCHER = PROJECT_ROOT / "jtree"
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
    fixture = tmp_path_factory.mktemp("jtree-e2e") / "synthetic.json"
    fixture.write_text(json.dumps({"name": "synthetic", "items": [1, 2]}))
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
                "jtree E2E server failed to start.\n"
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
    assert "--color-blueprint-bg: #0a1628;" in source
    assert "--color-node-type-object: #4fc3f7;" in source
    assert "--font-sans: 'DM Sans', sans-serif;" in source
    assert "--font-mono: 'JetBrains Mono', monospace;" in source
    assert "lucide@1.46.0" in source


def test_tailwind_browser_support_is_documented():
    readme = README.read_text()
    user_guide = USER_GUIDE.read_text()
    normalized_readme = " ".join(readme.split())

    for document in (readme, user_guide):
        assert "@tailwindcss/browser" in document
        assert "4.3.3" in document

    assert "not byte-immutable" in readme
    assert "Playwright" in readme
    assert "Chromium" in readme
    assert "Chrome 111" in readme
    assert "Safari 16.4" in readme
    assert "Firefox 128" in readme
    assert "Safari and Firefox are not covered by the automated browser test" in normalized_readme


def test_app_loads_tailwind_v4_persists_theme_and_opens_search(server, page):
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

    script_sources = page.locator("script[src]").evaluate_all(
        "elements => elements.map(element => element.src)"
    )
    assert script_sources == [
        "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
        "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
        "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js",
        "https://unpkg.com/@babel/standalone@7.29.8/babel.min.js",
        "https://unpkg.com/lucide@1.46.0/dist/umd/lucide.min.js",
    ]
    peer_resources = page.evaluate(
        """() => performance.getEntriesByType('resource')
            .map(entry => entry.name)
            .filter(name =>
                name.includes('/react@') ||
                name.includes('/react-dom@') ||
                name.includes('/react-is@')
            )
            .sort()"""
    )
    assert peer_resources == sorted(
        [
            "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
            "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js",
        ]
    )

    title = page.locator(".text-node-type-object").filter(has_text="jtree").first
    page.wait_for_function(
        "getComputedStyle(document.querySelector('.text-node-type-object')).color === 'rgb(79, 195, 247)'"
    )
    assert title.evaluate("element => getComputedStyle(element).color") == "rgb(79, 195, 247)"
    assert page.locator(".font-mono").first.evaluate(
        "element => getComputedStyle(element).fontFamily"
    ).startswith('"JetBrains Mono"')
    assert page.locator("body").evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) == "rgb(10, 22, 40)"
    assert page.evaluate("document.documentElement.classList.contains('dark')")
    assert page.evaluate("localStorage.getItem('jtree-theme')") == "dark"

    page.get_by_title("Toggle theme").click()
    page.wait_for_function("!document.documentElement.classList.contains('dark')")
    assert page.locator("body").evaluate(
        "element => getComputedStyle(element).backgroundColor"
    ) == "rgb(241, 245, 249)"
    assert page.evaluate("localStorage.getItem('jtree-theme')") == "light"
    page.reload(wait_until="networkidle")
    page.wait_for_function("!document.documentElement.classList.contains('dark')")
    assert page.evaluate("localStorage.getItem('jtree-theme')") == "light"

    search = page.get_by_title("Search (Ctrl+F)")
    expect(search).to_be_visible()
    search.click()
    expect(page.get_by_placeholder("Search keys and values...")).to_be_visible()
    assert errors == []


def test_native_css_retains_body_font_when_tailwind_is_unavailable(server, page):
    page.route(
        "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
        lambda route: route.abort(),
    )
    page.goto(server, wait_until="domcontentloaded")
    expect(page.get_by_title("Toggle theme")).to_be_visible()

    body_styles = page.locator("body").evaluate(
        """element => ({
            fontFamily: getComputedStyle(element).fontFamily,
            overflow: getComputedStyle(element).overflow,
            backgroundColor: getComputedStyle(element).backgroundColor,
        })"""
    )
    assert body_styles == {
        "fontFamily": '"DM Sans", sans-serif',
        "overflow": "hidden",
        "backgroundColor": "rgb(10, 22, 40)",
    }
