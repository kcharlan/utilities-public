"""Minimal real-browser smoke coverage for harscope."""

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
    assert source.count("https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3") == 1
    assert source.count("lucide@1.46.0/dist/umd/lucide.min.js") == 1
    assert "cdn.tailwindcss.com" not in source
    assert "tailwind.config" not in source
    assert '<style type="text/tailwindcss">' in source
    assert "@custom-variant dark (&:where(.dark, .dark *));" in source
    assert "--color-ink: #1a1a1a;" in source
    assert "--color-card-dark: #242424;" in source
    assert "--font-sans: 'DM Sans', system-ui, sans-serif;" in source
    assert "--font-mono: 'JetBrains Mono', monospace;" in source
    assert (
        '<script type="text/babel" data-type="module" '
        'data-presets="env,react">'
    ) in source
    assert "import * as React from 'react';" in source
    assert "import * as ReactDOM from 'react-dom';" not in source
    assert "import * as ReactDOMClient from 'react-dom/client';" in source
    assert "ReactDOMClient.createRoot(" in source


def test_frontend_dependency_contract_is_documented():
    documents = [
        README.read_text(),
        USER_GUIDE.read_text(),
        TEST_README.read_text(),
        TEST_PLAN.read_text(),
    ]

    for document in documents:
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

    readme = documents[0]
    normalized_readme = " ".join(readme.split())
    assert "Safari and Firefox are not covered by the automated browser test" in normalized_readme
    assert "React 18 UMD" not in readme


def test_app_loads_without_browser_errors_and_opens_security(server, page):
    with guard_browser_errors(page):
        page.emulate_media(color_scheme="light")
        page.goto(server, wait_until="domcontentloaded")

        security = page.get_by_role("button", name="Security")
        expect(security).to_be_visible(timeout=15_000)

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
            """elements => elements
                .map(element => element.src)
                .filter(source => new URL(source).origin !== location.origin)"""
        )
        assert Counter(script_sources) == Counter(
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
        for direct_resource in script_sources:
            assert non_react_counts[direct_resource] == 1

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
