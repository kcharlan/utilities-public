from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import re
import socket
import sys
import threading
import time
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"


IMPORTS = [
    ("react", "https://esm.sh/react@19.3.0"),
    ("react/jsx-runtime", "https://esm.sh/react@19.3.0/jsx-runtime"),
    (
        "react/jsx-dev-runtime",
        "https://esm.sh/react@19.3.0/jsx-dev-runtime",
    ),
    ("react-dom", "https://esm.sh/react-dom@19.3.0?external=react"),
    (
        "react-dom/client",
        "https://esm.sh/react-dom@19.3.0/client?external=react",
    ),
    ("react-is", "https://esm.sh/react-is@19.3.0?external=react"),
]


def capture_browser_errors(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error"
        else None,
    )
    return errors


@contextmanager
def guard_browser_errors(page, expected=()):
    errors = capture_browser_errors(page)
    try:
        yield
    finally:
        assert errors == list(expected), f"Unexpected browser errors: {errors}"


def is_react_package_resource(resource_url):
    path = urlsplit(resource_url).path
    return re.search(
        r"(?:^|/)(?:react|react-dom|react-is)(?:@[^/]+)?(?:/|$)",
        path,
    ) is not None


def assert_react_peer_graph(resource_urls):
    required_wrappers = Counter(
        {
            ("/react@19.3.0", ""): 1,
            ("/react@19.3.0/jsx-runtime", ""): 1,
            ("/react-dom@19.3.0", "external=react"): 1,
            ("/react-dom@19.3.0/client", "external=react"): 1,
        }
    )
    wrapper_counts = Counter()
    compiled_counts = Counter()
    compiled_targets = {}
    react_dom_external_markers = {}

    for resource_url in resource_urls:
        parsed = urlsplit(resource_url)
        assert (parsed.scheme, parsed.netloc, parsed.fragment) == (
            "https",
            "esm.sh",
            "",
        ), f"unexpected React resource origin: {resource_url}"

        wrapper_signature = (parsed.path, parsed.query)
        if wrapper_signature in required_wrappers:
            wrapper_counts[wrapper_signature] += 1
            continue
        if parsed.query:
            raise AssertionError(f"unexpected React resource: {resource_url}")

        react_match = re.fullmatch(
            r"/react@19\.3\.0/([a-z][a-z0-9_-]{1,15})/"
            r"(react|jsx-runtime)\.mjs",
            parsed.path,
        )
        if react_match:
            target, module_name = react_match.groups()
            compiled_counts[module_name] += 1
            compiled_targets[module_name] = target
            continue

        react_dom_match = re.fullmatch(
            r"/react-dom@19\.3\.0/(X-[A-Za-z0-9_-]+)/"
            r"([a-z][a-z0-9_-]{1,15})/(react-dom|client)\.mjs",
            parsed.path,
        )
        if react_dom_match:
            marker, target, module_name = react_dom_match.groups()
            compiled_counts[module_name] += 1
            compiled_targets[module_name] = target
            react_dom_external_markers[module_name] = marker
            continue

        raise AssertionError(f"unexpected React resource: {resource_url}")

    assert wrapper_counts == required_wrappers
    assert compiled_counts == Counter(
        {"react": 1, "jsx-runtime": 1, "react-dom": 1, "client": 1}
    )
    assert len(set(compiled_targets.values())) == 1
    assert react_dom_external_markers == {
        "react-dom": react_dom_external_markers.get("client"),
        "client": react_dom_external_markers.get("react-dom"),
    }
    return next(iter(compiled_targets.values()))


def assert_non_react_resources(resource_urls, compiled_target):
    static_resources = {
        "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
        "https://unpkg.com/@babel/standalone@8.0.5/babel.min.js",
        "https://unpkg.com/lucide@1.46.0/dist/umd/lucide.min.js",
    }
    resource_counts = Counter(resource_urls)
    for static_resource in static_resources:
        assert resource_counts.pop(static_resource, 0) == 1
    scheduler_resources = sorted(resource_counts.elements())
    assert len(scheduler_resources) == 2

    wrapper = urlsplit(scheduler_resources[0])
    compiled = urlsplit(scheduler_resources[1])
    assert (wrapper.scheme, wrapper.netloc, wrapper.fragment) == (
        "https",
        "esm.sh",
        "",
    )
    assert (compiled.scheme, compiled.netloc, compiled.fragment) == (
        "https",
        "esm.sh",
        "",
    )
    wrapper_match = re.fullmatch(r"/scheduler@%5E(\d+\.\d+\.\d+)", wrapper.path)
    assert wrapper_match is not None
    assert wrapper.query == f"target={compiled_target}"
    scheduler_version = wrapper_match.group(1)
    assert compiled.path == (
        f"/scheduler@{scheduler_version}/{compiled_target}/scheduler.mjs"
    )
    assert compiled.query == ""


@contextmanager
def live_server(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


def route_dashboard_api(page):
    page.route(
        "**/api/state",
        lambda route: route.fulfill(
            json={
                "scan_status": {"running": False, "phase": "complete", "progress": 1},
                "report": {
                    "generated_at": "2030-01-01T00:00:00Z",
                    "summary": {},
                    "breakdowns": {},
                    "findings": {"items": []},
                    "snapshots": {"items": []},
                    "large_files": {"items": []},
                    "providers": {"items": []},
                    "orphans": {"items": []},
                    "checks": [],
                },
            }
        ),
    )
    page.route(
        "**/api/events",
        lambda route: route.fulfill(status=200, content_type="text/event-stream", body=""),
    )


def test_dashboard_loads_tailwind_v4_and_persists_theme_without_browser_errors(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "storage_monitor")
    import_map_match = re.search(
        r'<script type="importmap">\s*(\{.*?\})\s*</script>',
        module.HTML_TEMPLATE,
        re.DOTALL,
    )
    assert import_map_match is not None
    assert list(json.loads(import_map_match.group(1))["imports"].items()) == IMPORTS
    assert "react@18.3.1" not in module.HTML_TEMPLATE
    assert "react-dom@18.3.1" not in module.HTML_TEMPLATE
    assert "@babel/standalone@8.0.5/babel.min.js" in module.HTML_TEMPLATE
    assert (
        '<script type="text/babel" data-type="module" '
        'data-presets="env,react">'
    ) in module.HTML_TEMPLATE
    assert "import * as React from 'react';" in module.HTML_TEMPLATE
    assert "import * as ReactDOM from 'react-dom';" in module.HTML_TEMPLATE
    assert (
        "import * as ReactDOMClient from 'react-dom/client';"
        in module.HTML_TEMPLATE
    )
    assert "ReactDOMClient.createRoot(" in module.HTML_TEMPLATE
    assert (
        "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3"
        in module.HTML_TEMPLATE
    )
    assert "cdn.tailwindcss.com" not in module.HTML_TEMPLATE
    assert "<style>\n    :root" in module.HTML_TEMPLATE
    assert '<style type="text/tailwindcss">' in module.HTML_TEMPLATE
    assert '@source inline("min-h-screen w-full");' in module.HTML_TEMPLATE
    assert "lucide@1.46.0/dist/umd/lucide.min.js" in module.HTML_TEMPLATE

    readme = " ".join(README.read_text().split())
    for dependency in (
        "React 19.3.0",
        "ReactDOM 19.3.0",
        "react-is 19.3.0",
        "Babel Standalone 8.0.5",
        "Tailwind CSS 4.3.3",
    ):
        assert dependency in readme
    assert "exact-version import map" in readme
    assert "module-aware inline JSX" in readme
    assert "direct top-level package versions" in readme
    assert "CDN-generated transitive dependencies are not fully locked" in readme
    assert "not byte-immutable" in readme
    assert "current Playwright Chromium" in readme

    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        with guard_browser_errors(page):
            route_dashboard_api(page)
            page.goto(url, wait_until="networkidle")
            page.get_by_text("Storage Monitor", exact=True).wait_for()
            assert page.evaluate("typeof window.lucide?.createIcons") == "function"

            root_styles = page.locator("#root").evaluate(
                "element => ({ minHeight: getComputedStyle(element).minHeight, "
                "width: getComputedStyle(element).width })"
            )
            viewport = page.viewport_size
            assert viewport is not None
            assert root_styles == {
                "minHeight": f"{viewport['height']}px",
                "width": f"{viewport['width']}px",
            }

            external_resources = page.evaluate(
                """() => performance.getEntriesByType('resource')
                    .map(entry => entry.name)
                    .filter(name => !name.startsWith(location.origin))
                    .sort()"""
            )
            dependency_resources = [
                url
                for url in external_resources
                if is_react_package_resource(url)
            ]
            compiled_target = assert_react_peer_graph(dependency_resources)
            non_react_resources = [
                url
                for url in external_resources
                if not is_react_package_resource(url)
            ]
            assert_non_react_resources(non_react_resources, compiled_target)

            for bad_resource in (
                "https://esm.sh/react",
                "https://esm.sh/react/jsx-runtime",
                "https://esm.sh/react-dom",
                "https://esm.sh/react-dom/client",
                "https://esm.sh/react-is",
                "https://esm.sh/react@19.2.0",
                "https://esm.sh/react-dom@19.2.0?external=react",
                "https://esm.sh/react-is@19.2.0?external=react",
                "https://esm.sh/react@19.3.0?dev",
                "https://cdn.example.invalid/react@19.3.0",
                dependency_resources[0],
            ):
                with pytest.raises(AssertionError):
                    assert_react_peer_graph([*dependency_resources, bad_resource])

            compiled_resources = [
                url
                for url in dependency_resources
                if urlsplit(url).path.endswith(".mjs")
            ]
            observed_target_match = re.search(
                r"/([a-z][a-z0-9_-]{1,15})/"
                r"(?:react|jsx-runtime|react-dom|client)\.mjs$",
                urlsplit(compiled_resources[0]).path,
            )
            assert observed_target_match is not None
            observed_target = observed_target_match.group(1)
            alternate_target = (
                "es2098" if observed_target == "es2099" else "es2099"
            )
            assert_react_peer_graph(
                [
                    url.replace(
                        f"/{observed_target}/",
                        f"/{alternate_target}/",
                    )
                    if url in compiled_resources
                    else url
                    for url in dependency_resources
                ]
            )
            with pytest.raises(AssertionError):
                assert_react_peer_graph(
                    [
                        url.replace(
                            f"/{observed_target}/",
                            "/target_name_far_too_long/",
                        )
                        if url in compiled_resources
                        else url
                        for url in dependency_resources
                    ]
                )

            assert page.evaluate("document.documentElement.dataset.theme") == "light"
            assert page.locator("body").evaluate(
                "element => [getComputedStyle(element).backgroundColor, "
                "getComputedStyle(element).color]"
            ) == ["rgb(244, 245, 247)", "rgb(26, 27, 30)"]
            page.get_by_label("Toggle dark mode").click()
            page.wait_for_function(
                "getComputedStyle(document.body).backgroundColor === "
                "'rgb(15, 17, 23)'"
            )
            assert page.evaluate("document.documentElement.dataset.theme") == "dark"
            assert page.evaluate("localStorage.getItem('sm-theme')") == "dark"
            assert page.locator("body").evaluate(
                "element => [getComputedStyle(element).backgroundColor, "
                "getComputedStyle(element).color]"
            ) == ["rgb(15, 17, 23)", "rgb(226, 228, 233)"]
            page.reload(wait_until="domcontentloaded")
            page.get_by_label("Scan details").wait_for()
            assert page.evaluate("document.documentElement.dataset.theme") == "dark"
            assert page.evaluate("localStorage.getItem('sm-theme')") == "dark"
            assert page.locator("body").evaluate(
                "element => [getComputedStyle(element).backgroundColor, "
                "getComputedStyle(element).color]"
            ) == ["rgb(15, 17, 23)", "rgb(226, 228, 233)"]
        browser.close()


def test_dashboard_keeps_first_party_styles_when_tailwind_cdn_fails(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "storage_monitor")

    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        with guard_browser_errors(
            page,
            expected=("Failed to load resource: net::ERR_FAILED",),
        ):
            page.route(
                "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
                lambda route: route.abort(),
            )
            route_dashboard_api(page)

            page.goto(url, wait_until="domcontentloaded")
            page.get_by_text("Storage Monitor", exact=True).wait_for()
            assert page.locator("body").evaluate(
                "element => [getComputedStyle(element).backgroundColor, "
                "getComputedStyle(element).color]"
            ) == ["rgb(244, 245, 247)", "rgb(26, 27, 30)"]
        browser.close()


def test_browser_error_capture_observes_console_and_page_errors():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = capture_browser_errors(page)
        page.evaluate("console.error('__console_error_capture__')")
        with page.expect_event("pageerror"):
            page.evaluate(
                "setTimeout(() => { throw new Error('__page_error_capture__'); }, 0)"
            )
        assert errors == ["__console_error_capture__", "__page_error_capture__"]
        browser.close()
