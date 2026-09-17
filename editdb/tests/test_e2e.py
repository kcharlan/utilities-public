"""Minimal real-browser smoke coverage for EditDB."""

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
    assert source.count("@babel/standalone@8.0.5/babel.min.js") == 1
    assert source.count("@tailwindcss/browser@4.3.3") == 1
    assert source.count("lucide@1.46.0/dist/umd/lucide.min.js") == 1
    assert "cdn.tailwindcss.com" not in source
    assert "tailwind.config" not in source
    assert '<style type="text/tailwindcss">' in source
    assert "@custom-variant dark (&:where(.dark, .dark *));" in source
    assert "--color-brand-dark-50: #f8fafc;" in source
    assert "--color-brand-dark-950: #020617;" in source
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
    user_guide = USER_GUIDE.read_text()

    for document in (readme, user_guide):
        normalized = " ".join(document.split())
        for dependency in (
            "React 19.3.0",
            "ReactDOM 19.3.0",
            "react-is 19.3.0",
            "Babel Standalone 8.0.5",
            "Tailwind CSS 4.3.3",
        ):
            assert dependency in normalized
        assert "exact-version import map" in normalized
        assert "module-aware inline JSX" in normalized
        assert "direct top-level package versions" in normalized
        assert "CDN-generated transitive dependencies are not fully locked" in normalized
        assert "not byte-immutable" in normalized
        assert "current Playwright Chromium" in normalized
        assert "Chrome 111" in document
        assert "Safari 16.4" in document
        assert "Firefox 128" in document

    assert (
        "Safari and Firefox are not covered by the automated browser test"
        in " ".join(readme.split())
    )
    assert "React 18 UMD" not in readme


def test_app_loads_without_browser_errors_and_opens_sql_console(server, page):
    with guard_browser_errors(page, expected=("__console_capture_probe__",)):
        page.add_init_script(
            "if (localStorage.getItem('editdb_theme') === null) "
            "localStorage.setItem('editdb_theme', 'light')"
        )
        page.goto(server, wait_until="networkidle")
        page.evaluate("console.error('__console_capture_probe__')")

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
        assert Counter(external_script_sources) == Counter(
            {
                "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3": 1,
                "https://unpkg.com/@babel/standalone@8.0.5/babel.min.js": 1,
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

        page.get_by_role("button", name="SQL Console").click()
        expect(page.get_by_text("Raw SQL Query")).to_be_visible()
        page.locator("textarea").fill("SELECT 7 AS synthetic_value;")
        page.get_by_role("button", name="Run Query").click()
        expect(page.get_by_role("columnheader", name="synthetic_value")).to_be_visible()
        expect(page.get_by_role("cell", name="7", exact=True)).to_be_visible()


def test_first_party_base_styles_survive_tailwind_cdn_failure(server, page):
    with guard_browser_errors(
        page,
        expected=(
            "Failed to load resource: net::ERR_FAILED",
            "__console_capture_probe__",
        ),
    ):
        page.add_init_script("localStorage.setItem('editdb_theme', 'light')")
        page.route(
            "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
            lambda route: route.abort(),
        )
        page.goto(server, wait_until="domcontentloaded")
        expect(page.get_by_role("button", name="SQL Console")).to_be_visible()
        page.evaluate("console.error('__console_capture_probe__')")
        assert page.locator("body").evaluate(
            "element => [getComputedStyle(element).backgroundColor, "
            "getComputedStyle(element).color]"
        ) == ["rgb(248, 250, 252)", "rgb(15, 23, 42)"]
