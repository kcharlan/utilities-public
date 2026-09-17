from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import re
import socket
import sys
import threading
import time

import pytest
from playwright.sync_api import expect, sync_playwright
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"
USAGE_GUIDE = PROJECT_ROOT / "docs" / "Usage.md"
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import (
    assert_react_19_import_map,
    assert_react_esm_graph,
    capture_browser_errors,
    guard_browser_errors,
    is_react_package_resource,
    load_launcher,
)


@contextmanager
def live_server(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
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


def css_alpha(serialized_color):
    color = serialized_color.strip().lower()
    if color == "transparent":
        return 0.0
    if " / " in color and color.endswith(")"):
        alpha = color.removesuffix(")").rsplit(" / ", 1)[1]
        return float(alpha.removesuffix("%")) / (100 if alpha.endswith("%") else 1)
    if color.startswith("rgba("):
        return float(color.removesuffix(")").rsplit(",", 1)[1].strip())
    return 1.0


@pytest.mark.parametrize(
    ("serialized_color", "expected_alpha"),
    [
        ("rgba(124, 45, 18, 0.3)", 0.3),
        ("rgb(124 45 18 / 30%)", 0.3),
        ("oklab(0.408 0.123 0.109 / 0.3)", 0.3),
        ("transparent", 0.0),
        ("rgb(255, 237, 213)", 1.0),
    ],
)
def test_css_alpha_accepts_legacy_and_modern_serialization(
    serialized_color, expected_alpha
):
    assert css_alpha(serialized_color) == pytest.approx(expected_alpha)


def test_tailwind_v4_contract_and_browser_support_are_documented():
    module = load_launcher(PROJECT_ROOT / "tax2")
    source = module.HTML_TEMPLATE

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
    assert (
        '<script type="text/babel" data-type="module" '
        'data-presets="env,react">'
    ) in source
    assert "import * as React from 'react';" in source
    assert "import * as ReactDOM from 'react-dom';" not in source
    assert "import * as ReactDOMClient from 'react-dom/client';" in source
    assert "ReactDOMClient.createRoot(" in source

    assert source.count(
        "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3"
    ) == 1
    assert "cdn.tailwindcss.com" not in source
    assert "tailwind.config" not in source
    assert '<style type="text/tailwindcss">' in source
    assert "@custom-variant dark (&:where(.dark, .dark *));" in source
    assert "--font-display: 'Epilogue', sans-serif;" in source
    assert "--font-mono: 'IBM Plex Mono', monospace;" in source
    assert "--font-body: 'Public Sans', sans-serif;" in source
    assert "app-title font-display" in source
    assert "dark:bg-orange-900/30" in source

    for legacy_opacity_utility in (
        "bg-opacity-",
        "border-opacity-",
        "divide-opacity-",
        "placeholder-opacity-",
        "ring-opacity-",
        "text-opacity-",
    ):
        assert legacy_opacity_utility not in source

    readme = README.read_text()
    usage_guide = USAGE_GUIDE.read_text()
    normalized_readme = " ".join(readme.split())
    for document in (readme, usage_guide):
        normalized_document = " ".join(document.split())
        assert "@tailwindcss/browser" in normalized_document
        assert "4.3.3" in normalized_document
        for dependency in (
            "React 19.3.0",
            "ReactDOM 19.3.0",
            "react-is 19.3.0",
            "Babel Standalone 8.0.5",
        ):
            assert dependency in normalized_document
        assert "exact-version import map" in normalized_document
        assert "module-aware inline JSX" in normalized_document
        assert "direct top-level package versions" in normalized_document
        assert (
            "CDN-generated transitive dependencies are not fully locked"
            in normalized_document
        )
        assert "current Playwright Chromium" in normalized_document
    assert "not byte-immutable" in readme
    assert "Playwright" in readme
    assert "Chromium" in readme
    assert "Chrome 111" in readme
    assert "Safari 16.4" in readme
    assert "Firefox 128" in readme
    assert (
        "Safari and Firefox are not covered by the automated browser test"
        in normalized_readme
    )


def test_calculator_loads_tailwind_v4_recomputes_and_persists_dark_mode(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "tax2")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.emulate_media(color_scheme="light")
        browser_errors = capture_browser_errors(page)
        expected_error = "Computation error: Error: Synthetic compute failure"
        page.goto(url, wait_until="domcontentloaded")
        expect(page.get_by_text("Tax2", exact=True)).to_be_visible(timeout=15_000)
        expect(page.get_by_text("Total Monthly", exact=True)).to_be_visible()

        script_sources = page.locator("script[src]").evaluate_all(
            "elements => elements.map(element => element.src)"
        )
        assert Counter(script_sources) == Counter(
            [
                "https://unpkg.com/@babel/standalone@8.0.5/babel.min.js",
                "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
                "https://unpkg.com/lucide@1.46.0/dist/umd/lucide.min.js",
            ]
        )
        external_resources = page.evaluate(
            """() => performance.getEntriesByType('resource')
                .map(entry => entry.name)
                .filter(name => !name.startsWith(location.origin))"""
        )
        peer_resources = [
            resource
            for resource in external_resources
            if is_react_package_resource(resource)
        ]
        assert_react_esm_graph(
            peer_resources,
            react_dom_wrapper_policy="forbidden",
        )
        non_react_counts = Counter(
            resource
            for resource in external_resources
            if not is_react_package_resource(resource)
        )
        for direct_resource in script_sources:
            assert non_react_counts[direct_resource] == 1

        page.wait_for_function(
            "getComputedStyle(document.querySelector('.font-display')).fontFamily.startsWith('Epilogue')"
        )
        assert page.locator(".font-display").evaluate(
            "element => getComputedStyle(element).fontFamily"
        ).startswith("Epilogue")
        generated_font_rules = page.evaluate(
            """() => {
                const matches = [];
                const visit = rules => Array.from(rules || []).forEach(rule => {
                    if (rule.selectorText === '.font-display') matches.push(rule.cssText);
                    if (rule.cssRules) visit(rule.cssRules);
                });
                Array.from(document.styleSheets).forEach(sheet => {
                    try { visit(sheet.cssRules); } catch (error) {
                        if (error.name !== 'SecurityError') throw error;
                    }
                });
                return matches;
            }"""
        )
        assert len(generated_font_rules) == 1
        assert "font-family: var(--font-display)" in generated_font_rules[0]

        assert not page.evaluate("document.documentElement.classList.contains('dark')")
        assert page.evaluate("localStorage.getItem('tax2-dark-mode')") == "false"

        total_amount = page.locator(".result-card.total .result-amount")
        initial_total = total_amount.inner_text()
        income = page.locator(".income-input").first
        income.click()
        expect(income).to_have_value("12500")
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/compute")
        ) as compute_info:
            income.fill("5000")
        assert compute_info.value.status == 200
        assert compute_info.value.request.post_data_json["monthly_unearned"] == 5000
        expect(total_amount).not_to_have_text(initial_total)

        page.get_by_role("button", name="Toggle Theme").click()
        page.wait_for_function("document.documentElement.classList.contains('dark')")
        assert page.evaluate("localStorage.getItem('tax2-dark-mode')") == "true"
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_text("Tax2", exact=True)).to_be_visible(timeout=15_000)
        assert page.evaluate("document.documentElement.classList.contains('dark')")
        assert page.evaluate("localStorage.getItem('tax2-dark-mode')") == "true"

        page.get_by_role("button", name="Toggle Theme").click()
        page.wait_for_function("!document.documentElement.classList.contains('dark')")
        assert page.evaluate("localStorage.getItem('tax2-dark-mode')") == "false"

        page.evaluate(
            """() => {
                const realFetch = window.fetch.bind(window);
                window.fetch = (input, init) => {
                    const requestUrl = typeof input === 'string' ? input : input.url;
                    if (requestUrl.endsWith('/api/compute')) {
                        return Promise.resolve(new Response(
                            JSON.stringify({detail: 'Synthetic compute failure'}),
                            {
                                status: 422,
                                headers: {'Content-Type': 'application/json'},
                            }
                        ));
                    }
                    return realFetch(input, init);
                };
            }"""
        )
        income.click()
        expect(income).to_have_value("12500")
        income.fill("5100")
        banner = page.locator("div.bg-orange-100", has_text="Synthetic compute failure")
        expect(banner).to_be_visible()
        light_banner_background = banner.evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
        assert css_alpha(light_banner_background) == pytest.approx(1.0)

        page.get_by_role("button", name="Toggle Theme").click()
        page.wait_for_function("document.documentElement.classList.contains('dark')")
        page.wait_for_function(
            "(lightColor) => getComputedStyle(document.querySelector('div.bg-orange-100')).backgroundColor !== lightColor",
            arg=light_banner_background,
        )
        dark_banner_background = banner.evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
        assert dark_banner_background != light_banner_background
        assert css_alpha(dark_banner_background) == pytest.approx(0.3)
        assert page.evaluate("localStorage.getItem('tax2-dark-mode')") == "true"
        assert len(browser_errors) == 1
        assert browser_errors[0].splitlines()[0] == expected_error
        browser.close()


def test_calculator_keeps_native_styles_when_tailwind_is_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "tax2")
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
            page.goto(url, wait_until="domcontentloaded")
            expect(page.get_by_text("Tax2", exact=True)).to_be_visible(
                timeout=15_000
            )
            assert page.locator("body").evaluate(
                "element => [getComputedStyle(element).backgroundColor, getComputedStyle(element).color]"
            ) == ["rgb(250, 250, 249)", "rgb(28, 25, 23)"]
        browser.close()
