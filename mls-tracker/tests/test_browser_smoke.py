from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import re
import socket
import sys
import threading
import time

from playwright.sync_api import expect, sync_playwright
import uvicorn

import mls_tracker


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import (
    assert_react_19_import_map,
    assert_react_esm_graph,
    guard_browser_errors,
    is_react_package_resource,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"
USER_GUIDE = PROJECT_ROOT / "docs" / "USER_GUIDE.md"


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


def _install_synthetic_data(monkeypatch):
    state = {"refreshes": 0}
    teams = [
        {
            "position": index,
            "name": f"Synthetic Team {index}",
            "id": str(index),
            "gp": 20,
            "w": 10,
            "l": 6,
            "t": 4,
            "pts": 40 - index,
            "gf": 30,
            "ga": 20,
            "gd": 10,
            "ppg": 1.5,
        }
        for index in range(1, 11)
    ]
    metadata = [
        {
            "id": str(index),
            "name": f"Synthetic Team {index}",
            "abbreviation": f"S{index}",
            "colors": {"primary": "#336699", "secondary": "#112233", "accent": "#ffffff"},
            "logo": "",
        }
        for index in range(1, 11)
    ]

    def get_standings(_season):
        standings = [dict(team) for team in teams]
        if state["refreshes"]:
            standings[0].update(gp=33, w=0, l=32, t=1, pts=1, ppg=0.03)
            standings[8].update(gp=33, w=19, l=11, t=3, pts=60, ppg=1.818)
        return {"Eastern Conference": standings}

    def invalidate():
        state["refreshes"] += 1

    monkeypatch.setattr(mls_tracker.cache, "get_standings", get_standings)
    monkeypatch.setattr(mls_tracker.cache, "get_teams", lambda: metadata)
    monkeypatch.setattr(mls_tracker.cache, "invalidate", invalidate)
    return state


def test_tailwind_v4_contract_and_browser_support_are_documented():
    source = mls_tracker.HTML_TEMPLATE
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
    assert "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3" in source
    assert "cdn.tailwindcss.com" not in source
    assert "tailwind.config" not in source
    assert '<style type="text/tailwindcss">' in source
    assert "@custom-variant dark (&:where(.dark, .dark *));" in source
    assert "--color-team-primary: var(--team-primary);" in source
    assert "--color-surface-100: var(--surface-100);" in source
    assert "--font-display: 'Oswald', sans-serif;" in source
    assert "--font-body: 'Source Sans 3', sans-serif;" in source
    assert "bg-surface-100/95" in source
    assert "text-white/90" in source
    assert "bg-white/20" in source
    for legacy_opacity_utility in (
        "bg-opacity-",
        "border-opacity-",
        "divide-opacity-",
        "placeholder-opacity-",
        "ring-opacity-",
        "text-opacity-",
    ):
        assert legacy_opacity_utility not in source
    assert (
        '<script type="text/babel" data-type="module" '
        'data-presets="env,react">'
    ) in source
    assert "import * as React from 'react';" in source
    assert "import * as ReactDOM from 'react-dom';" not in source
    assert "import * as ReactDOMClient from 'react-dom/client';" in source
    assert "ReactDOMClient.createRoot(" in source

    readme = README.read_text()
    user_guide = USER_GUIDE.read_text()
    normalized_readme = " ".join(readme.split())
    for document in (readme, user_guide):
        assert "@tailwindcss/browser" in document
        assert "4.3.3" in document
        for dependency in (
            "React 19.3.0",
            "ReactDOM 19.3.0",
            "react-is 19.3.0",
            "Babel Standalone 8.0.5",
        ):
            assert dependency in " ".join(document.split())
    assert "not byte-immutable" in readme
    assert "exact-version import map" in normalized_readme
    assert "module-aware inline JSX" in normalized_readme
    assert "direct top-level package versions" in normalized_readme
    assert "CDN-generated transitive dependencies are not fully locked" in normalized_readme
    assert "React 18 UMD" not in readme
    assert "current Playwright Chromium" in normalized_readme
    assert "Chrome 111" in readme
    assert "Safari 16.4" in readme
    assert "Firefox 128" in readme
    assert "Safari and Firefox are not covered by the automated browser test" in normalized_readme


def test_embedded_dashboard_loads_tailwind_v4_and_persists_dark_mode(monkeypatch):
    synthetic_state = _install_synthetic_data(monkeypatch)

    with live_server(mls_tracker.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.emulate_media(color_scheme="light")
        with guard_browser_errors(page):
            page.goto(url, wait_until="domcontentloaded")
            expect(page.get_by_text("Current Points")).to_be_visible(timeout=15_000)

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
                resource
                for resource in external_resources
                if is_react_package_resource(resource)
            ]
            assert_react_esm_graph(
                react_resources,
                react_dom_wrapper_policy="forbidden",
            )
            non_react_counts = Counter(
                resource
                for resource in external_resources
                if not is_react_package_resource(resource)
            )
            for direct_resource in external_script_sources:
                assert non_react_counts[direct_resource] == 1

            title = page.locator("h1", has_text="Synthetic Team 1")
            page.wait_for_function(
                "getComputedStyle(document.querySelector('.font-display')).fontFamily.startsWith('Oswald')"
            )
            assert title.evaluate(
                "element => getComputedStyle(element).fontFamily"
            ).startswith("Oswald")
            assert page.locator(".text-team-primary").first.evaluate(
                "element => getComputedStyle(element).color"
            ) == "rgb(51, 102, 153)"
            assert page.locator("#root > div").evaluate(
                "element => getComputedStyle(element).backgroundColor"
            ) == "rgb(250, 250, 250)"
            settings_background = page.locator("#root > div > div").first.evaluate(
                "element => getComputedStyle(element).backgroundColor"
            )
            assert settings_background.endswith("/ 0.95)")
            status_description_color = page.get_by_text(
                "Destiny is in our hands. Results on the pitch determine playoff fate."
            ).evaluate("element => getComputedStyle(element).color")
            assert status_description_color.endswith("/ 0.9)")
            assert not page.evaluate(
                "document.documentElement.classList.contains('dark')"
            )
            assert page.evaluate("localStorage.getItem('mls-dark-mode')") == "false"

            page.get_by_title("Toggle dark mode").click()
            page.wait_for_function(
                "document.documentElement.classList.contains('dark')"
            )
            page.wait_for_function(
                "getComputedStyle(document.querySelector('#root > div')).backgroundColor === 'rgb(24, 24, 27)'"
            )
            dark_styles = page.locator("#root > div").evaluate(
                """element => ({
                    backgroundColor: getComputedStyle(element).backgroundColor,
                    surface: getComputedStyle(document.documentElement).getPropertyValue('--surface-50').trim(),
                    themeSurface: getComputedStyle(document.documentElement).getPropertyValue('--color-surface-50').trim(),
                })"""
            )
            assert dark_styles == {
                "backgroundColor": "rgb(24, 24, 27)",
                "surface": "#18181b",
                "themeSurface": "#18181b",
            }
            dark_settings_background = page.locator("#root > div > div").first.evaluate(
                "element => getComputedStyle(element).backgroundColor"
            )
            assert dark_settings_background.endswith("/ 0.95)")
            assert dark_settings_background != settings_background
            assert page.evaluate("localStorage.getItem('mls-dark-mode')") == "true"

            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_text("Current Points")).to_be_visible(timeout=15_000)
            assert page.evaluate("document.documentElement.classList.contains('dark')")
            assert page.evaluate("localStorage.getItem('mls-dark-mode')") == "true"

            refresh_button = page.get_by_title("Refresh data")
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith("/api/refresh")
            ) as refresh_info, page.expect_response(
                lambda response: response.request.method == "GET"
                and "/api/data?" in response.url
            ) as data_info, page.expect_response(
                lambda response: response.request.method == "GET"
                and "/api/scenarios?" in response.url
            ) as scenarios_info:
                refresh_button.click()
            assert refresh_info.value.status == 200
            assert refresh_info.value.json() == {"status": "ok"}
            assert data_info.value.status == 200
            assert "conferences" in data_info.value.json()
            assert scenarios_info.value.status == 200
            refreshed_scenarios = scenarios_info.value.json()
            assert refreshed_scenarios["status"] == "eliminated"
            assert refreshed_scenarios["target"]["pts"] == 1
            assert synthetic_state["refreshes"] == 1
            expect(refresh_button).to_be_enabled()
            expect(
                page.get_by_role("heading", name="Mathematically Eliminated")
            ).to_be_visible()
            expect(page.get_by_text("Not Possible", exact=True)).to_have_count(2)
            impossible_badge = page.get_by_text("Not Possible", exact=True).first
            badge_styles = impossible_badge.evaluate(
                """element => ({
                    backgroundColor: getComputedStyle(element).backgroundColor,
                    color: getComputedStyle(element).color,
                })"""
            )
            assert badge_styles["backgroundColor"].startswith("oklab(")
            assert badge_styles["backgroundColor"].endswith("/ 0.2)")
            assert badge_styles["color"] == "rgb(255, 255, 255)"
        browser.close()


def test_class_dark_variant_styles_the_error_banner(monkeypatch):
    _install_synthetic_data(monkeypatch)

    with live_server(mls_tracker.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.emulate_media(color_scheme="light")
        with guard_browser_errors(page):
            page.add_init_script(
                """(() => {
                    const realFetch = window.fetch.bind(window);
                    window.fetch = (input, init) => {
                        const requestUrl = typeof input === 'string' ? input : input.url;
                        if (requestUrl.includes('/api/scenarios?')) {
                            return Promise.resolve(new Response('{}', {status: 500}));
                        }
                        return realFetch(input, init);
                    };
                })()"""
            )
            page.goto(url, wait_until="domcontentloaded")
            banner = page.get_by_text("API error: 500").locator("..")
            expect(banner).to_be_visible(timeout=15_000)
            light_background = banner.evaluate(
                "element => getComputedStyle(element).backgroundColor"
            )
            assert light_background not in {"rgba(0, 0, 0, 0)", "transparent"}

            page.get_by_title("Toggle dark mode").click()
            page.wait_for_function(
                "document.documentElement.classList.contains('dark')"
            )
            assert banner.evaluate(
                "element => getComputedStyle(element).backgroundColor"
            ) != light_background
        browser.close()


def test_native_body_baseline_remains_when_tailwind_is_unavailable(monkeypatch):
    _install_synthetic_data(monkeypatch)

    with live_server(mls_tracker.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        with guard_browser_errors(page, expected=("Failed to load resource: net::ERR_FAILED",)):
            page.route(
                "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
                lambda route: route.abort(),
            )
            page.goto(url, wait_until="domcontentloaded")
            expect(page.get_by_title("Toggle dark mode")).to_be_visible(
                timeout=15_000
            )
            body_styles = page.locator("body").evaluate(
                """element => ({
                    fontFamily: getComputedStyle(element).fontFamily,
                    backgroundColor: getComputedStyle(element).backgroundColor,
                    color: getComputedStyle(element).color,
                })"""
            )
            assert body_styles == {
                "fontFamily": '\"Source Sans 3\", sans-serif',
                "backgroundColor": "rgb(250, 250, 250)",
                "color": "rgb(24, 24, 27)",
            }
        browser.close()
