from contextlib import contextmanager
from pathlib import Path
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

from tools.testkit import load_launcher


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
        assert "@tailwindcss/browser" in document
        assert "4.3.3" in document
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
    page_errors = []
    console_errors = []

    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.emulate_media(color_scheme="light")
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(url, wait_until="networkidle")
        expect(page.get_by_text("Tax2", exact=True)).to_be_visible()
        expect(page.get_by_text("Total Monthly", exact=True)).to_be_visible()

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
        dependency_resources = page.evaluate(
            """() => performance.getEntriesByType('resource')
                .map(entry => entry.name)
                .filter(name =>
                    name.includes('@tailwindcss/browser') ||
                    name.includes('@babel/standalone') ||
                    name.includes('/lucide@') || name.includes('/lucide/') ||
                    name.includes('/react@') || name.includes('/react/') ||
                    name.includes('/react-dom@') || name.includes('/react-dom/') ||
                    name.includes('/react-is@') || name.includes('/react-is/')
                )
                .sort()"""
        )
        assert dependency_resources == sorted(script_sources)
        peer_resources = [
            resource
            for resource in dependency_resources
            if "/react@" in resource
            or "/react/" in resource
            or "/react-dom@" in resource
            or "/react-dom/" in resource
            or "/react-is@" in resource
            or "/react-is/" in resource
        ]
        assert peer_resources == sorted(
            [
                "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
                "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js",
            ]
        )

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
        page.reload(wait_until="networkidle")
        expect(page.get_by_text("Tax2", exact=True)).to_be_visible()
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
        browser.close()

    expected_error = "Computation error: Error: Synthetic compute failure"
    assert page_errors == []
    assert len(console_errors) == 1
    assert console_errors[0].splitlines()[0] == expected_error


def test_calculator_keeps_native_styles_when_tailwind_is_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "tax2")
    page_errors = []
    console_errors = []

    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.route(
            "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
            lambda route: route.abort(),
        )
        page.goto(url, wait_until="domcontentloaded")
        expect(page.get_by_text("Tax2", exact=True)).to_be_visible()
        assert page.locator("body").evaluate(
            "element => [getComputedStyle(element).backgroundColor, getComputedStyle(element).color]"
        ) == ["rgb(250, 250, 249)", "rgb(28, 25, 23)"]
        browser.close()

    assert page_errors == []
    assert console_errors == ["Failed to load resource: net::ERR_FAILED"]
