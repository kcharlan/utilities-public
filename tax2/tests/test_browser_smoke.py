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
        expect(page.get_by_text("Total Monthly Tax", exact=True)).to_be_visible()

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
            expect(page.locator(".result-card.net")).to_be_visible(timeout=15_000)
            assert page.locator(".summary-grid").evaluate(
                "element => getComputedStyle(element).display"
            ) == "grid"
            assert page.locator(".result-card.net").evaluate(
                "element => getComputedStyle(element, '::before').backgroundColor"
            ) == "rgb(5, 150, 105)"
            assert page.locator("body").evaluate(
                "element => [getComputedStyle(element).backgroundColor, getComputedStyle(element).color]"
            ) == ["rgb(250, 250, 249)", "rgb(28, 25, 23)"]
        browser.close()


# All amounts in these scenarios are synthetic; real tax requests remain covered.
def fill_income_and_compute(page, index, value):
    income = page.locator(".income-input").nth(index)
    income.click()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/compute")
    ) as computation:
        income.fill(str(value))
    assert computation.value.status == 200
    return computation.value.json()


def test_net_income_reconciles_real_multistate_results_and_qif(monkeypatch, tmp_path):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "synthetic-runtime"))
    module = load_launcher(PROJECT_ROOT / "tax2")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        with guard_browser_errors(page):
            page.goto(url, wait_until="domcontentloaded")
            total = page.locator(".result-card.total .result-amount")
            net = page.locator(".result-card.net .result-amount")
            expect(total).to_be_visible(timeout=15_000)
            data = fill_income_and_compute(page, 0, 5000)
            assert data["total_monthly"] == 621.93
            expect(net).to_have_text("$4,378.07")
            with page.expect_response("**/api/compute"):
                page.get_by_label("Pennsylvania", exact=True).check()
            expect(net).to_have_text("$4,224.57")
            with page.expect_response("**/api/compute"):
                page.locator('input[type="number"]').nth(1).fill("50")
            expect(total).to_have_text("$698.68")
            expect(net).to_have_text("$4,301.32")
            data = fill_income_and_compute(page, 1, 250)
            expected_net = 5250 - data["total_monthly"]
            expect(net).to_have_text(f"${expected_net:,.2f}")
            expect(page.locator(".income-sublabel").first).to_contain_text("$5,250.00")
            with page.expect_request("**/api/export/qif") as export, page.expect_download():
                page.get_by_role("button", name="Download QIF").click()
            payload = export.value.post_data_json
            assert payload["federal_tax"] == data["federal_monthly"]
            assert [state["amount"] for state in payload["states"]] == [
                state["monthly"] for state in data["states"]
            ]
            assert not any("net" in key for key in payload)
            fill_income_and_compute(page, 1, 0)
            fill_income_and_compute(page, 0, 0)
            expect(net).to_have_text("$0.00")
            expect(page.locator(".results-grid")).not_to_contain_text("NaN")
        browser.close()


@pytest.mark.parametrize(
    ("gross", "tax", "expected"),
    [(100.005, 10, "$90.01"), (100, 125, "-$25.00"), (0, 10, "-$10.00")],
)
def test_net_income_uses_display_cents_and_table_result(
    monkeypatch, tmp_path, gross, tax, expected
):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "synthetic-runtime"))
    module = load_launcher(PROJECT_ROOT / "tax2")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        requests = []

        def synthetic_compute(route):
            payload = route.request.post_data_json
            requests.append(payload)
            route.fulfill(json={
                "federal_monthly": tax, "federal_annual": tax * 12,
                "states": [{"code": state["code"], "display_name": "Synthetic state",
                            "monthly": 0, "annual": 0,
                            "allocation_pct": state["allocation_pct"]}
                           for state in payload["states"]],
                "total_monthly": tax, "total_annual": tax * 12, "effective_rate": 0,
            })

        with guard_browser_errors(page):
            page.route("**/api/compute", synthetic_compute)
            page.goto(url, wait_until="domcontentloaded")
            expect(page.locator(".result-card.total")).to_be_visible(timeout=15_000)
            fill_income_and_compute(page, 0, gross)
            with page.expect_response("**/api/compute"):
                page.get_by_label("Lookup Table", exact=True).check()
            expect(page.locator(".result-card.net .result-amount")).to_have_text(expected)
            assert requests[-1]["mode"] == "table"
            assert requests[-1]["monthly_unearned"] == gross
            if gross == 100.005:
                expect(page.locator(".income-sublabel").first).to_contain_text("$100.01")
        browser.close()


@pytest.mark.parametrize("obsolete_failure", [False, True])
def test_only_current_computation_can_publish_results(monkeypatch, tmp_path, obsolete_failure):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "synthetic-runtime"))
    module = load_launcher(PROJECT_ROOT / "tax2")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        browser_errors = capture_browser_errors(page)
        try:
            page.goto(url, wait_until="domcontentloaded")
            total = page.locator(".result-card.total .result-amount")
            expect(total).to_be_visible(timeout=15_000)
            # Deliberately ignore AbortSignal: obsolete promises must be guarded
            # even if fetch cancellation does not prevent their completion.
            page.evaluate("""() => {
                const realFetch = window.fetch.bind(window);
                window.syntheticRequests = [];
                window.fetch = (input, init) => {
                    if (!String(input).endsWith('/api/compute')) return realFetch(input, init);
                    return new Promise(resolve => {
                        window.syntheticRequests.push({payload: JSON.parse(init.body), resolve});
                    });
                };
                window.finishSynthetic = (index, failure, tax) => {
                    const request = window.syntheticRequests[index];
                    const payload = request.payload;
                    request.resolve(new Response(JSON.stringify(failure ? {detail: failure} : {
                        federal_monthly: tax, federal_annual: tax * 12,
                        states: payload.states.map(state => ({...state, display_name: 'Synthetic state',
                            monthly: 0, annual: 0})),
                        total_monthly: tax, total_annual: tax * 12, effective_rate: 0
                    }), {status: failure ? 422 : 200,
                         headers: {'Content-Type': 'application/json'}}));
                };
            }""")
            income = page.locator(".income-input").first
            income.click()
            income.fill("5000")
            # Assert before the 300ms fetch debounce, after React shows new gross.
            expect(page.locator(".income-sublabel").first).to_contain_text("$5,000.00")
            assert page.locator(".result-card").count() == 0
            expect(page.get_by_role("button", name="Download QIF")).to_be_disabled()
            page.wait_for_function("window.syntheticRequests.length === 1")
            income.fill("6000")
            page.wait_for_function("window.syntheticRequests.length === 2")
            # Repeat A's request key while its first generation is still unresolved.
            income.fill("5000")
            page.wait_for_function("window.syntheticRequests.length === 3")
            assert page.evaluate("window.syntheticRequests.map(request => request.payload.monthly_unearned)") == [5000, 6000, 5000]
            page.evaluate("window.finishSynthetic(1, null, 888)")
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            expect(page.get_by_text("Calculating...", exact=True)).to_be_visible()
            expect(page.locator(".result-card")).to_have_count(0)
            page.evaluate("window.finishSynthetic(2, null, 30)")
            expect(total).to_have_text("$30.00")
            expect(page.locator(".result-card.net .result-amount")).to_have_text("$4,970.00")
            page.evaluate("""failure => {
                window.finishSynthetic(0, failure, 999);
            }""", "Synthetic obsolete failure" if obsolete_failure else None)
            # Flush response publication and React rendering, without a sleep.
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            expect(total).to_have_text("$30.00")
            expect(page.get_by_text("Synthetic obsolete failure", exact=False)).not_to_be_visible()
            expect(page.get_by_role("button", name="Download QIF")).to_be_enabled()
            income.fill("7000")
            page.wait_for_function("window.syntheticRequests.length === 4")
            page.evaluate("window.finishSynthetic(3, 'Synthetic current failure', 0)")
            expect(page.get_by_text("Synthetic current failure", exact=False)).to_be_visible()
            expect(page.locator(".result-card")).to_have_count(0)
            expect(page.get_by_role("button", name="Download QIF")).to_be_disabled()
            income.fill("8000")
            page.wait_for_function("window.syntheticRequests.length === 5")
            page.evaluate("window.finishSynthetic(4, null, 40)")
            expect(page.locator(".result-card.net .result-amount")).to_have_text("$7,960.00")
            expect(page.get_by_text("Synthetic current failure", exact=False)).not_to_be_visible()
            expect(page.get_by_role("button", name="Download QIF")).to_be_enabled()
            assert len(browser_errors) == 1
            assert browser_errors[0].splitlines()[0] == "Computation error: Error: Synthetic current failure"
        finally:
            browser.close()


def test_summary_layout_fits_available_space_in_both_themes(monkeypatch, tmp_path):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "synthetic-runtime"))
    module = load_launcher(PROJECT_ROOT / "tax2")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        with guard_browser_errors(page):
            page.goto(url, wait_until="domcontentloaded")
            expect(page.locator(".result-card.net")).to_be_visible(timeout=15_000)
            fill_income_and_compute(page, 0, 987654321)
            for dark in (False, True):
                if dark:
                    page.get_by_role("button", name="Toggle Theme").click()
                for width in (1440, 1280, 1201, 1200, 900, 768, 390):
                    page.set_viewport_size({"width": width, "height": 1000})
                    geometry = page.evaluate("""() => {
                        const total = document.querySelector('.result-card.total').getBoundingClientRect();
                        const net = document.querySelector('.result-card.net').getBoundingClientRect();
                        return {
                            overflow: document.documentElement.scrollWidth > innerWidth,
                            cardsFit: [...document.querySelectorAll('.result-card, .result-amount')]
                                .every(el => el.scrollWidth <= el.clientWidth + 1),
                            paired: Math.abs(total.top - net.top) < 1,
                            ordered: net.top > total.top || net.left > total.left,
                            accent: getComputedStyle(document.querySelector('.result-card.net'), '::before').backgroundColor
                        };
                    }""")
                    assert not geometry["overflow"], (width, dark, geometry)
                    assert geometry["cardsFit"], (width, dark, geometry)
                    assert geometry["accent"] == ("rgb(16, 185, 129)" if dark else "rgb(5, 150, 105)")
                    assert geometry["ordered"]
                    assert geometry["paired"] == (width > 768)
                # A halved desktop CSS viewport approximates the layout at 200% zoom.
                page.set_viewport_size({"width": 720, "height": 500})
                expect(page.locator(".result-card.net")).to_be_visible()
        browser.close()
