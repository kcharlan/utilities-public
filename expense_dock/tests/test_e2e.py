"""Minimal real-browser smoke coverage for Expense Dock."""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pytest
from playwright.sync_api import expect


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import (
    assert_react_19_import_map,
    assert_react_esm_graph,
    guard_browser_errors,
    is_react_package_resource,
)


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
    import_map_match = re.search(
        r'<script type="importmap">\s*(\{.*?\})\s*</script>',
        source,
        re.DOTALL,
    )
    assert import_map_match is not None
    imports = json.loads(import_map_match.group(1))["imports"]
    assert_react_19_import_map(imports)
    assert "react@18.3.1" not in source
    assert "react-dom@18.3.1" not in source
    assert "/umd/react" not in source
    assert source.count("@babel/standalone@8.0.5/babel.min.js") == 1
    assert source.count("@tailwindcss/browser@4.3.3") == 1
    assert source.count("lucide@1.46.0/dist/umd/lucide.min.js") == 1
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
    assert (
        '<script type="text/babel" data-type="module" '
        'data-presets="env,react">'
    ) in source
    assert "import * as React from 'react';" in source
    assert "import * as ReactDOM from 'react-dom';" not in source
    assert "import * as ReactDOMClient from 'react-dom/client';" in source
    assert "ReactDOMClient.createRoot(" in source


def test_frontend_dependency_contract_is_documented():
    readme = README.read_text()
    normalized_readme = " ".join(readme.split())

    for dependency in (
        "React 19.3.0",
        "ReactDOM 19.3.0",
        "react-is 19.3.0",
        "Babel Standalone 8.0.5",
        "Tailwind CSS 4.3.3",
    ):
        assert dependency in normalized_readme
    assert "exact-version import map" in normalized_readme
    assert "module-aware inline JSX" in normalized_readme
    assert "direct top-level package versions" in normalized_readme
    assert "CDN-generated transitive dependencies are not fully locked" in normalized_readme
    assert "not byte-immutable" in readme
    assert "current Playwright Chromium" in normalized_readme
    assert "Chrome 111" in readme
    assert "Safari 16.4" in readme
    assert "Firefox 128" in readme
    assert "Safari and Firefox are not covered by the automated browser test" in normalized_readme
    assert "React 18 UMD" not in readme


def test_app_loads_without_browser_errors_and_opens_setup(server, page):
    with guard_browser_errors(page, expected=("__console_capture_probe__",)):
        page.add_init_script(
            "if (localStorage.getItem('expenseDockTheme') === null) "
            "localStorage.setItem('expenseDockTheme', 'light')"
        )
        page.goto(server, wait_until="networkidle")
        page.evaluate("console.error('__console_capture_probe__')")

        title = page.get_by_role("heading", name="Expense Dock")
        expect(title).to_be_visible()
        page.wait_for_function(
            "getComputedStyle(document.querySelector('h1')).fontFamily.includes('Fraunces')"
        )
        assert "Fraunces" in title.evaluate(
            "element => getComputedStyle(element).fontFamily"
        )

        external_script_sources = page.locator("script[src]").evaluate_all(
            """elements => elements
                .map(element => element.src)
                .filter(source => new URL(source).origin !== location.origin)"""
        )
        assert Counter(external_script_sources) == Counter(
            {
                "https://unpkg.com/@babel/standalone@8.0.5/babel.min.js": 1,
                "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3": 1,
                "https://unpkg.com/lucide@1.46.0/dist/umd/lucide.min.js": 1,
            }
        )

        external_resources = page.evaluate(
            """() => performance.getEntriesByType('resource')
                .map(entry => entry.name)
                .filter(name => !name.startsWith(location.origin))"""
        )
        react_resources = [
            url for url in external_resources if is_react_package_resource(url)
        ]
        assert_react_esm_graph(
            react_resources,
            react_dom_wrapper_policy="forbidden",
        )
        non_react_counts = Counter(
            url for url in external_resources if not is_react_package_resource(url)
        )
        for direct_resource in external_script_sources:
            assert non_react_counts[direct_resource] == 1

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
