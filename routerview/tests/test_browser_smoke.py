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
DESIGN = PROJECT_ROOT / "docs" / "DESIGN.md"
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import (
    ASGISyncClient,
    capture_browser_errors,
    load_launcher,
)


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


def seed_synthetic_dashboard(module):
    csv_text = """generation_id,created_at,model_permaslug,provider_name,api_key_name,app_name,tokens_prompt,tokens_completion,tokens_reasoning,tokens_cached,cost_total,cost_cache,cost_web_search,cost_file_processing,generation_time_ms,finish_reason_normalized,streamed,cancelled,num_search_results,user,time_to_first_token_ms
synthetic-alpha-request,2026-09-15T12:00:00+00:00,synthetic/alpha,Synthetic Provider A,Synthetic Key,Synthetic App,10,20,3,1,0.12,0.01,0,0,123,stop,true,false,0,synthetic-user,50
synthetic-beta-request,2026-09-16T13:00:00+00:00,synthetic/beta,Synthetic Provider B,Synthetic Key,Synthetic App,15,25,4,2,0.34,0.02,0,0,234,stop,false,false,1,synthetic-user,80
"""
    response = ASGISyncClient(module.app).post(
        "/api/import/csv",
        files={"file": ("synthetic_activity.csv", csv_text, "text/csv")},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "inserted": 2, "skipped": 0}


def rendered_plot_bounds(wrapper):
    plot_parts = wrapper.locator(".rv-main-chart-plot")
    plot_parts.first.wait_for(state="attached")
    return plot_parts.evaluate_all(
        """parts => {
            const rects = parts.map(part => part.getBoundingClientRect());
            const left = Math.min(...rects.map(rect => rect.left));
            const right = Math.max(...rects.map(rect => rect.right));
            const top = Math.min(...rects.map(rect => rect.top));
            const bottom = Math.max(...rects.map(rect => rect.bottom));
            return {x:left, y:top, width:right-left, height:bottom-top};
        }"""
    )


def css_alpha(serialized_color):
    color = serialized_color.strip().lower()
    if color == "transparent":
        return 0.0

    slash_alpha = re.search(r"/\s*([0-9]*\.?[0-9]+)(%)?\s*\)$", color)
    if slash_alpha:
        alpha = float(slash_alpha.group(1))
        return alpha / 100 if slash_alpha.group(2) else alpha

    if color.startswith("rgba("):
        return float(color.removesuffix(")").rsplit(",", 1)[1].strip())

    return 1.0


@pytest.mark.parametrize(
    ("serialized_color", "expected_alpha"),
    [
        ("rgba(59, 130, 246, 0.2)", 0.2),
        ("rgb(59 130 246 / 20%)", 0.2),
        ("color(srgb 0.231 0.51 0.965 / 0.2)", 0.2),
        ("transparent", 0.0),
        ("rgb(59, 130, 246)", 1.0),
    ],
)
def test_css_alpha_accepts_legacy_and_modern_serialization(
    serialized_color, expected_alpha
):
    assert css_alpha(serialized_color) == pytest.approx(expected_alpha)


def test_embedded_frontend_contract():
    from tools.testkit import assert_frontend_vendor_current, assert_launcher_compiles_cleanly, assert_offline_page_source
    assert_frontend_vendor_current(PROJECT_ROOT / "routerview")
    assert_launcher_compiles_cleanly(PROJECT_ROOT / "routerview")
    assert_offline_page_source(load_launcher(PROJECT_ROOT / "routerview").HTML_TEMPLATE)


def test_dashboard_chart_interactions_and_offline_resources(tmp_path):
    module = load_launcher(Path(__file__).resolve().parents[1] / "routerview")
    from tools.testkit import assert_classes_styled, assert_offline_page_source
    assert_offline_page_source(module.HTML_TEMPLATE)
    module._db_path = str(tmp_path / "routerview.db")
    module.init_database(module._db_path)
    seed_synthetic_dashboard(module)

    requests = []
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = capture_browser_errors(page)
        page.on("request", lambda request: requests.append(request.url))
        page.goto(f"{url}?range=all", wait_until="domcontentloaded")
        page.get_by_text("RouterView", exact=True).wait_for(timeout=15_000)

        assert_classes_styled(page)

        kpi_card = page.locator(".bg-card").first
        page.wait_for_function(
            "getComputedStyle(document.querySelector('.bg-card')).backgroundColor === 'rgb(30, 41, 59)'"
        )
        assert kpi_card.evaluate(
            "element => getComputedStyle(element).backgroundColor"
        ) == "rgb(30, 41, 59)"
        page.evaluate("document.documentElement.classList.remove('dark')")
        page.wait_for_function(
            "getComputedStyle(document.querySelector('.bg-card')).backgroundColor === 'rgb(51, 65, 85)'"
        )
        requests.clear()
        page.reload(wait_until="domcontentloaded")
        page.get_by_text("RouterView", exact=True).wait_for(timeout=15_000)
        page.wait_for_function("document.documentElement.classList.contains('dark')")
        kpi_card.wait_for(state="visible", timeout=15_000)
        page.wait_for_function(
            "getComputedStyle(document.querySelector('.bg-card')).backgroundColor === 'rgb(30, 41, 59)'"
        )

        chart_heading = page.get_by_role("heading", name=re.compile(r"Cost over Time\s*by model"))
        chart_heading.wait_for()
        chart_wrapper = page.locator(".svgc-wrapper").first
        chart_wrapper.wait_for(state="visible")
        chart = chart_wrapper.locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
        chart_box = chart_wrapper.bounding_box()
        assert chart_box and chart_box["width"] > 200 and chart_box["height"] > 200

        tooltip = chart.locator(".svgc-tooltip")
        tooltip_text = ""
        for percent in range(5, 96, 2):
            page.mouse.move(
                chart_box["x"] + chart_box["width"] * percent / 100,
                chart_box["y"] + chart_box["height"] * 0.45,
            )
            if tooltip.is_visible():
                tooltip_text = tooltip.inner_text()
                if "$0.3400" in tooltip_text:
                    break
        assert "beta" in tooltip_text
        assert "$0.3400" in tooltip_text

        curves = chart.locator("path.svgc-curve")
        expect(curves).to_have_count(2)
        expect(curves.nth(0)).to_have_attribute("stroke-opacity", "1")
        expect(curves.nth(1)).to_have_attribute("stroke-opacity", "1")
        chart.locator(".svgc-legend-item", has_text="beta").click()
        expect(curves.nth(1)).to_have_attribute("stroke-opacity", "0")

        provider_heading = page.get_by_role("heading", name="Requests by Provider")
        provider_panel = provider_heading.locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
        sectors = provider_panel.locator("path.svgc-sector")
        expect(sectors).to_have_count(2)
        assert len({sectors.nth(i).get_attribute("fill") for i in range(2)}) == 2

        model_heading = page.get_by_role("heading", name="Cost by Model")
        model_panel = model_heading.locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
        bars = model_panel.locator(".svgc-bar")
        expect(bars).to_have_count(2)
        bars.first.click()
        page.get_by_text(re.compile(r"model:(?:alpha|beta)"), exact=False).wait_for()
        expect(page).to_have_url(re.compile(r"[?&]model=(?:alpha|beta)(?:&|$)"))
        filter_pill = page.locator(".bg-blue-500\\/20").first
        deadline = time.monotonic() + 5
        while True:
            filter_pill_background = filter_pill.evaluate(
                "element => getComputedStyle(element).backgroundColor"
            )
            if css_alpha(filter_pill_background) == pytest.approx(0.2):
                break
            if time.monotonic() >= deadline:
                pytest.fail(
                    "Tailwind did not compile bg-blue-500/20 within 5 seconds; "
                    f"last computed background was {filter_pill_background!r}"
                )
            page.wait_for_timeout(20)
        assert css_alpha(filter_pill_background) == pytest.approx(0.2)

        page.keyboard.press("?")
        page.get_by_text("Keyboard Shortcuts", exact=True).wait_for()
        assert browser.version
        browser.close()

    assert errors == []


def test_dashboard_keeps_body_colors_offline(tmp_path):
    from tools.testkit import block_external_requests, guard_browser_errors
    module = load_launcher(PROJECT_ROOT / "routerview")
    module._db_path = str(tmp_path / "routerview.db")
    module.init_database(module._db_path)
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        blocked = block_external_requests(context, allowed_origins=[url])
        page = context.new_page()
        with guard_browser_errors(page):
            page.goto(url, wait_until="domcontentloaded")
            page.get_by_text("RouterView", exact=True).wait_for()
            assert page.locator("body").evaluate(
                "element => [getComputedStyle(element).backgroundColor, getComputedStyle(element).color]"
            ) == ["rgb(15, 23, 42)", "rgb(241, 245, 249)"]
            assert not blocked
        browser.close()


def test_linked_crosshair_uses_rendered_plot_bounds_for_many_buckets(tmp_path):
    module = load_launcher(Path(__file__).resolve().parents[1] / "routerview")
    module._db_path = str(tmp_path / "routerview.db")
    module.init_database(module._db_path)
    seed_synthetic_dashboard(module)

    primary_buckets = [f"2026-09-16T{hour:02d}:00" for hour in range(24)]
    comparison_buckets = [f"comparison-{index:02d}" for index in range(31)]
    timeseries = {
        "bucket_size": "hour",
        "buckets": primary_buckets,
        "series": [{"name": "synthetic", "data": list(range(1, 25))}],
        "comparison_buckets": comparison_buckets,
        "comparison_series": [
            {"name": "synthetic", "data": list(range(31, 0, -1))}
        ],
        "compare_range": "Synthetic comparison",
    }

    errors = []
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.route(
            "**/api/timeseries*",
            lambda route: route.fulfill(json=timeseries),
        )
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("RouterView", exact=True).wait_for(timeout=15_000)

        heading = page.get_by_role(
            "heading", name=re.compile(r"Cost over Time\s*by model")
        )
        panel = heading.locator(
            "xpath=ancestor::div[contains(@class,'bg-slate-800')][1]"
        )
        wrappers = panel.locator(".svgc-wrapper")
        expect(wrappers).to_have_count(2)
        primary_bounds = rendered_plot_bounds(wrappers.nth(0))
        comparison_bounds = rendered_plot_bounds(wrappers.nth(1))
        assert primary_bounds and primary_bounds["width"] > 200
        assert comparison_bounds and comparison_bounds["width"] > 200

        for primary_index in (0, 12, 23):
            fraction = primary_index / (len(primary_buckets) - 1)
            page.mouse.move(
                primary_bounds["x"] + primary_bounds["width"] * fraction,
                primary_bounds["y"] + primary_bounds["height"] / 2,
            )
            lines = panel.locator(".svgc-reference-line")
            expect(lines).to_have_count(2)

            linked_index = int(fraction * (len(comparison_buckets) - 1) + 0.5)
            expected_primary_x = (
                primary_bounds["x"] + primary_bounds["width"] * fraction
            )
            expected_comparison_x = comparison_bounds["x"] + (
                comparison_bounds["width"]
                * linked_index
                / (len(comparison_buckets) - 1)
            )
            expect(lines.nth(0)).to_have_attribute(
                "x", primary_buckets[primary_index]
            )
            expect(lines.nth(1)).to_have_attribute(
                "x", comparison_buckets[linked_index]
            )
            actual_x = lines.evaluate_all(
                "lines => lines.map(line => line.getBoundingClientRect().x)"
            )
            assert actual_x[0] == pytest.approx(expected_primary_x, abs=2)
            assert actual_x[1] == pytest.approx(expected_comparison_x, abs=2)

        browser.close()

    assert errors == []


def test_bar_crosshair_snaps_to_band_boundaries(tmp_path):
    module = load_launcher(Path(__file__).resolve().parents[1] / "routerview")
    module._db_path = str(tmp_path / "routerview.db")
    module.init_database(module._db_path)
    seed_synthetic_dashboard(module)
    source_buckets = [f"source-{index}" for index in range(4)]
    comparison_buckets = [f"comparison-{index}" for index in range(7)]
    timeseries = {
        "bucket_size": "day",
        "buckets": source_buckets,
        "series": [{"name": "synthetic", "data": [1, 2, 3, 4]}],
        "comparison_buckets": comparison_buckets,
        "comparison_series": [
            {"name": "synthetic", "data": [7, 6, 5, 4, 3, 2, 1]}
        ],
    }

    errors = []
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.route("**/api/timeseries*", lambda route: route.fulfill(json=timeseries))
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("RouterView", exact=True).wait_for(timeout=15_000)
        page.locator('select:has(option[value="bar"])').select_option("bar")

        heading = page.get_by_role(
            "heading", name=re.compile(r"Cost over Time\s*by model")
        )
        panel = heading.locator(
            "xpath=ancestor::div[contains(@class,'bg-slate-800')][1]"
        )
        wrappers = panel.locator(".svgc-wrapper")
        expect(wrappers).to_have_count(2)
        bounds = rendered_plot_bounds(wrappers.nth(0))
        assert bounds and bounds["width"] > 200

        for position, source_index in ((0.24, 0), (0.26, 1), (0.74, 2), (0.76, 3)):
            page.mouse.move(
                bounds["x"] + bounds["width"] * position,
                bounds["y"] + bounds["height"] / 2,
            )
            lines = panel.locator(".svgc-reference-line")
            expect(lines).to_have_count(2)
            linked_index = int(
                source_index
                / (len(source_buckets) - 1)
                * (len(comparison_buckets) - 1)
                + 0.5
            )
            expect(lines.nth(0)).to_have_attribute("x", source_buckets[source_index])
            expect(lines.nth(1)).to_have_attribute(
                "x", comparison_buckets[linked_index]
            )

        browser.close()

    assert errors == []


def test_one_bucket_crosshair_links_to_first_bucket_and_clears_outside_plot(tmp_path):
    module = load_launcher(Path(__file__).resolve().parents[1] / "routerview")
    module._db_path = str(tmp_path / "routerview.db")
    module.init_database(module._db_path)
    seed_synthetic_dashboard(module)
    comparison_buckets = [f"comparison-{index}" for index in range(9)]
    timeseries = {
        "bucket_size": "day",
        "buckets": ["only-source-bucket"],
        "series": [{"name": "synthetic", "data": [4]}],
        "comparison_buckets": comparison_buckets,
        "comparison_series": [
            {"name": "synthetic", "data": list(range(1, 10))}
        ],
    }

    errors = []
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.route("**/api/timeseries*", lambda route: route.fulfill(json=timeseries))
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("RouterView", exact=True).wait_for(timeout=15_000)

        heading = page.get_by_role(
            "heading", name=re.compile(r"Cost over Time\s*by model")
        )
        panel = heading.locator(
            "xpath=ancestor::div[contains(@class,'bg-slate-800')][1]"
        )
        wrappers = panel.locator(".svgc-wrapper")
        expect(wrappers).to_have_count(2)
        bounds = rendered_plot_bounds(wrappers.nth(0))
        assert bounds and bounds["width"] > 200

        page.mouse.move(
            bounds["x"] + bounds["width"] / 2,
            bounds["y"] + bounds["height"] / 2,
        )
        lines = panel.locator(".svgc-reference-line")
        expect(lines).to_have_count(2)
        expect(lines.nth(0)).to_have_attribute("x", "only-source-bucket")
        expect(lines.nth(1)).to_have_attribute("x", comparison_buckets[0])

        page.mouse.move(
            bounds["x"] - 10,
            bounds["y"] + bounds["height"] / 2,
        )
        expect(lines).to_have_count(0)

        page.mouse.move(
            bounds["x"] + bounds["width"] / 2,
            bounds["y"] + bounds["height"] / 2,
        )
        expect(lines).to_have_count(2)
        page.mouse.move(
            bounds["x"] + bounds["width"] / 2,
            bounds["y"] - 10,
        )
        expect(lines).to_have_count(0)
        browser.close()

    assert errors == []


@pytest.mark.parametrize("activation_key", ["Enter", " "], ids=["enter", "space"])
def test_dimensional_bar_filter_is_keyboard_accessible(tmp_path, activation_key):
    module = load_launcher(Path(__file__).resolve().parents[1] / "routerview")
    module._db_path = str(tmp_path / "routerview.db")
    module.init_database(module._db_path)
    seed_synthetic_dashboard(module)

    errors = []
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(f"{url}?range=all", wait_until="domcontentloaded")
        page.get_by_text("RouterView", exact=True).wait_for(timeout=15_000)

        bar = page.get_by_role(
            "button", name=re.compile(r"Filter by model (?:alpha|beta)")
        ).first
        bar.focus()
        expect(bar).to_be_focused()
        page.evaluate(
            """() => {
                window.__barKeyDefaultPrevented = null;
                document.addEventListener('keydown', event => {
                    window.__barKeyDefaultPrevented = event.defaultPrevented;
                }, {once: true});
            }"""
        )
        action_name = bar.get_attribute("aria-label")
        assert action_name
        dimension = action_name.rsplit(" ", 1)[-1]
        bar.press(activation_key)

        page.get_by_text(f"model:{dimension}", exact=False).wait_for()
        expect(page).to_have_url(re.compile(rf"[?&]model={dimension}(?:&|$)"))
        assert page.evaluate("window.__barKeyDefaultPrevented") is True
        browser.close()

    assert errors == []


def test_page_loads_offline(tmp_path, monkeypatch):
    from tools.testkit import block_external_requests, guard_browser_errors, assert_no_external_resources, assert_offline_page_source
    monkeypatch.setenv('ROUTERVIEW_HOME', str(tmp_path / 'home'))
    module = load_launcher(PROJECT_ROOT / 'routerview')
    module._db_path = str(tmp_path / 'routerview.db')
    module.init_database(module._db_path)
    seed_synthetic_dashboard(module)
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        blocked = block_external_requests(context, allowed_origins=[url])
        page = context.new_page()
        with guard_browser_errors(page):
            page.goto(f'{url}?range=all', wait_until='domcontentloaded')
            page.get_by_text('RouterView', exact=True).wait_for(timeout=10000)
            assert_no_external_resources(page, blocked)
            assert_offline_page_source(page.content())
        browser.close()


@pytest.fixture
def synthetic_page(tmp_path, monkeypatch):
    monkeypatch.setenv('ROUTERVIEW_HOME', str(tmp_path / 'home'))
    module = load_launcher(PROJECT_ROOT / 'routerview')
    module._db_path = str(tmp_path / 'routerview.db')
    module.init_database(module._db_path)
    seed_synthetic_dashboard(module)
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = capture_browser_errors(page)
        page.goto(f'{url}?range=all', wait_until='domcontentloaded')
        page.get_by_text('RouterView', exact=True).wait_for()
        yield page
        browser.close()
        assert errors == []


def test_search_updates_on_each_keystroke(synthetic_page):
    from urllib.parse import parse_qs, urlsplit
    search = synthetic_page.locator('#log-search')
    search.focus()
    for character, prefix in zip('alp', ('a', 'al', 'alp')):
        with synthetic_page.expect_response(
            lambda response: '/api/generations?' in response.url
            and parse_qs(urlsplit(response.url).query).get('search') == [prefix]
        ):
            search.press_sequentially(character)
        expect(search).to_be_focused()
    rows = synthetic_page.locator('tbody tr')
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text('alpha')
    search.fill('')
    literal = '<b>x</b> & ${y} `value` {{X}} &nbsp;'
    typed = ''
    for character in literal:
        search.press_sequentially(character)
        typed += character
        assert search.input_value() == typed


def test_save_name_field_takes_focus_when_opened(synthetic_page):
    synthetic_page.get_by_role('button', name='Views').click()
    synthetic_page.get_by_role('button', name='Save current view').click()
    expect(synthetic_page.get_by_placeholder('View name...')).to_be_focused()


def test_bar_chart_type_renders_stacked_bars(synthetic_page):
    synthetic_page.route('**/api/timeseries*', lambda route: route.fulfill(json={
        'bucket_size': 'day', 'buckets': ['a', 'b'],
        'series': [{'name': 'synthetic A', 'data': [1, 2]},
                   {'name': 'synthetic B', 'data': [3, 4]}],
    }))
    synthetic_page.reload()
    synthetic_page.locator('select:has(option[value="bar"])').select_option('bar')
    panel = synthetic_page.get_by_role('heading', name=re.compile(r'Cost over Time')).locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    bars = panel.locator('.svgc-bar')
    expect(bars).to_have_count(4)
    geometry = bars.evaluate_all("nodes => nodes.map(n => Object.fromEntries(['x','y','width','height'].map(k => [k, Number(n.getAttribute(k))])))")
    for i in range(2):
        first, second = geometry[i], geometry[i + 2]
        assert first['width'] > 0 and first['height'] > 0 and second['height'] > 0
        assert first['x'] == pytest.approx(second['x'])
        assert first['y'] == pytest.approx(second['y'] + second['height'])


def test_comparison_series_are_dashed(synthetic_page):
    synthetic_page.route('**/api/timeseries*', lambda route: route.fulfill(json={
        'bucket_size': 'day', 'buckets': ['a', 'b'],
        'series': [{'name': 'synthetic', 'data': [1, 2]}],
        'comparison_buckets': ['c', 'd'],
        'comparison_series': [{'name': 'synthetic', 'data': [2, 1]}],
    }))
    synthetic_page.reload()
    curves = synthetic_page.locator('.rv-main-chart-plot').locator('xpath=..').locator('.svgc-curve')
    expect(curves).to_have_count(2)
    expect(curves.nth(1)).to_have_attribute('stroke-dasharray', '5 3')


def test_donut_sector_click_filters(synthetic_page):
    panel = synthetic_page.get_by_role('heading', name='Requests by Provider').locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    svg = panel.locator('.svgc-wrapper svg')
    svg.scroll_into_view_if_needed()

    box = svg.bounding_box()
    assert box
    synthetic_page.mouse.click(box['x'] + box['width'] / 2 + 65, box['y'] + box['height'] / 2)
    expect(synthetic_page).to_have_url(re.compile(r'[?&]provider='))


@pytest.mark.parametrize('buckets', [[], ['single']])
def test_charts_render_with_empty_and_single_bucket_data(synthetic_page, buckets):
    synthetic_page.route('**/api/timeseries*', lambda route: route.fulfill(json={
        'bucket_size': 'day', 'buckets': buckets,
        'series': [{'name': 'synthetic', 'data': [1] if buckets else []}],
    }))
    synthetic_page.reload()
    if buckets:
        expect(synthetic_page.locator('.rv-main-chart-plot')).to_have_count(1)
        assert 'NaN' not in synthetic_page.locator('.svgc-wrapper').first.inner_html()
    else:
        expect(synthetic_page.get_by_role('heading', name='Cost by Model')).to_be_visible()


def test_breakdown_axes_and_donut_geometry(synthetic_page):
    model = synthetic_page.get_by_role('heading', name='Cost by Model').locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    expect(model.locator('.svgc-hbar-axis')).to_have_count(1)
    ticks = model.locator('.svgc-hbar-tick')
    assert ticks.count() >= 2
    assert all(text.startswith('$') for text in ticks.all_text_contents())
    provider = synthetic_page.get_by_role('heading', name='Requests by Provider').locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    sector = provider.locator('.svgc-sector').first
    expect(sector).to_have_attribute('stroke', 'var(--color-white)')
    expect(sector).to_have_attribute('stroke-width', '1')
    path = sector.get_attribute('d')
    assert path and re.match(r'^M[\d.]+,100A85,85 0 [01] 0 ', path)
    assert provider.locator('.svgc-legend-item').count() == 0


@pytest.mark.parametrize('kind', ['area', 'line'])
def test_single_bucket_has_visible_value_and_readable_ticks(synthetic_page, kind):
    synthetic_page.route('**/api/timeseries*', lambda route: route.fulfill(json={
        'bucket_size': 'day', 'buckets': ['single'],
        'series': [{'name': 'synthetic', 'data': [1]}],
    }))
    synthetic_page.reload()
    synthetic_page.locator('select:has(option[value="bar"])').select_option(kind)
    chart = synthetic_page.get_by_role('heading', name=re.compile(r'Cost over Time')).locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    point = chart.locator('.svgc-point')
    expect(point).to_have_count(1)
    assert point.bounding_box()['width'] > 0
    labels = chart.locator('.svgc-wrapper svg text').evaluate_all("nodes => nodes.map(node => ({text:node.textContent, rect:node.getBoundingClientRect().toJSON()})).filter(x => x.text.startsWith('$'))")
    ordered = sorted(labels, key=lambda item: item['rect']['y'])
    for first, second in zip(ordered, ordered[1:]):
        assert first['rect']['bottom'] <= second['rect']['top']


def test_timeseries_tooltip_stays_readable_at_plot_corners(synthetic_page):
    chart = synthetic_page.get_by_role('heading', name=re.compile(r'Cost over Time')).locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    plot = chart.locator('.rv-main-chart-plot')
    plot.scroll_into_view_if_needed()
    bounds = plot.bounding_box()
    assert bounds
    for x_fraction, y_fraction in ((.01, .01), (.99, .01), (.01, .99), (.99, .99)):
        synthetic_page.mouse.move(bounds['x'] + bounds['width'] * x_fraction, bounds['y'] + bounds['height'] * y_fraction)
        tooltip = chart.locator('.svgc-tooltip')
        expect(tooltip).to_be_visible()
        assert 'Total' in tooltip.inner_text()
        box = tooltip.bounding_box()
        viewport = synthetic_page.viewport_size
        assert box and viewport
        assert box['x'] >= 0 and box['y'] >= 0
        assert box['x'] + box['width'] <= viewport['width'] + 1
        assert box['y'] + box['height'] <= viewport['height'] + 1


def test_breakdown_user_text_displays_literally(synthetic_page):
    literal = '<b>x</b> & ${y} `value` {{X}} &nbsp;'
    def respond(route):
        if 'group_by=provider' in route.request.url:
            route.fulfill(json={'data': [{'dimension': literal, 'value': 1}]})
        else:
            route.continue_()
    synthetic_page.route('**/api/breakdown*', respond)
    synthetic_page.reload()
    panel = synthetic_page.get_by_role('heading', name='Requests by Provider').locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    expect(panel.locator("span").filter(has_text=literal).last).to_be_visible()
    assert panel.locator('b').count() == 0


@pytest.mark.parametrize('kind', ['area', 'line', 'bar'])
def test_all_zero_chart_has_finite_geometry(synthetic_page, kind):
    synthetic_page.route('**/api/timeseries*', lambda route: route.fulfill(json={
        'bucket_size': 'day', 'buckets': ['a', 'b'],
        'series': [{'name': 'synthetic', 'data': [0, 0]}],
    }))
    synthetic_page.reload()
    synthetic_page.locator('select:has(option[value="bar"])').select_option(kind)
    chart = synthetic_page.get_by_role('heading', name=re.compile(r'Cost over Time')).locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    expect(chart.locator('.svgc-wrapper')).to_have_count(1)
    html = chart.locator('.svgc-wrapper').inner_html()
    assert 'NaN' not in html and 'Infinity' not in html


def test_dense_minute_ticks_remain_readable_after_resize(synthetic_page):
    page = synthetic_page
    page.set_viewport_size({'width': 600, 'height': 900})
    buckets = [f'2026-09-16T12:{i:02d}:00' for i in range(60)]
    page.route('**/api/timeseries*', lambda route: route.fulfill(json={
        'bucket_size': 'minute', 'buckets': buckets,
        'series': [{'name': 'synthetic', 'data': list(range(60))}],
    }))
    page.reload()
    chart = page.get_by_role('heading', name=re.compile(r'Cost over Time')).locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    def tick_boxes():
        return chart.locator('.svgc-wrapper svg text').evaluate_all("""nodes => nodes.filter(n => /^12:\\d\\d$/.test(n.textContent))
            .map(n => ({text:n.textContent, rect:n.getBoundingClientRect().toJSON()}))""")
    page.wait_for_function("""() => [...document.querySelectorAll('.svgc-wrapper svg text')].some(n => /^12:\\d\\d$/.test(n.textContent))""")
    narrow = tick_boxes()
    assert 2 <= len(narrow) < 60
    for first, second in zip(narrow, narrow[1:]):
        assert first['rect']['right'] <= second['rect']['left']
    plot = chart.locator('.rv-main-chart-plot')
    bounds = plot.bounding_box()
    assert bounds
    page.mouse.move(bounds['x'] + bounds['width'] * 30 / 59, bounds['y'] + bounds['height'] / 2)
    expect(chart.locator('.svgc-tooltip')).to_contain_text('12:30')
    page.set_viewport_size({'width': 1200, 'height': 900})
    page.wait_for_function("""width => document.querySelector('.rv-main-chart-plot').getBoundingClientRect().width > width""", arg=bounds['width'] + 200)
    wide = tick_boxes()
    assert len(wide) > len(narrow)
    for first, second in zip(wide, wide[1:]):
        assert first['rect']['right'] <= second['rect']['left']


@pytest.mark.parametrize('kind', ['area', 'line', 'bar'])
@pytest.mark.parametrize('dark', [True, False])
def test_main_legend_preserves_compact_symbols_and_order(synthetic_page, kind, dark):
    page = synthetic_page
    page.set_viewport_size({'width': 600, 'height': 900})
    names = ['zulu-model', 'alpha-model', 'mike-model', 'beta-model', 'gamma-model', 'delta-model', 'epsilon-model', 'omega-model']
    page.route('**/api/timeseries*', lambda route: route.fulfill(json={
        'bucket_size': 'day', 'buckets': ['a', 'b'],
        'series': [{'name': name, 'data': [1, 2]} for name in names],
    }))
    page.reload()
    if not dark:
        page.evaluate("document.documentElement.classList.remove('dark')")
    page.locator('select:has(option[value="bar"])').select_option(kind)
    chart = page.get_by_role('heading', name=re.compile(r'Cost over Time')).locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    buttons = chart.locator('.svgc-legend-item')
    expect(buttons).to_have_count(len(names))
    assert buttons.all_text_contents() == sorted(names)
    assert buttons.first.evaluate("n => getComputedStyle(n).fontSize") == '11px'
    assert chart.locator('.svgc-legend').evaluate("n => getComputedStyle(n).paddingTop") == '8px'
    assert buttons.locator('svg[aria-hidden="true"]').count() == len(names)
    symbol = buttons.first.locator('svg rect' if kind == 'bar' else 'svg line')
    expect(symbol).to_have_count(1)
    if kind != 'bar':
        expect(buttons.first.locator('svg circle')).to_have_count(1)
    color = symbol.get_attribute('fill' if kind == 'bar' else 'stroke')
    assert color == chart.locator('.svgc-curve' if kind != 'bar' else '.svgc-bar').nth(1 if kind != 'bar' else 2).get_attribute('stroke')
    positions = buttons.evaluate_all("nodes => nodes.map(n => n.getBoundingClientRect().top)")
    assert len(set(positions)) > 1
    buttons.first.focus()
    expect(buttons.first).to_be_focused()
    buttons.first.press('Enter')
    expect(buttons.first).to_have_attribute('aria-pressed', 'false')


def test_main_axes_and_reference_match_original_styling(synthetic_page):
    chart = synthetic_page.get_by_role('heading', name=re.compile(r'Cost over Time')).locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    expect(chart.locator('.svgc-y-axis-line')).to_have_attribute('stroke', '#475569')
    expect(chart.locator('.svgc-curve').first).to_have_attribute('stroke-width', '1')
    bounds = chart.locator('.rv-main-chart-plot').bounding_box()
    assert bounds
    synthetic_page.mouse.move(bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2)
    expect(chart.locator('.svgc-reference-line')).to_have_attribute('stroke-opacity', '0.5')


def test_wrapped_legend_keeps_chart_budget_after_resize(synthetic_page):
    page = synthetic_page
    page.set_viewport_size({'width': 600, 'height': 900})
    names = ['zulu-model', 'alpha-model', 'mike-model', 'beta-model', 'gamma-model', 'delta-model', 'epsilon-model', 'omega-model']
    page.route('**/api/timeseries*', lambda route: route.fulfill(json={
        'bucket_size': 'day', 'buckets': ['a', 'b'],
        'series': [{'name': name, 'data': [1, 2]} for name in names],
    }))
    page.reload()
    chart = page.get_by_role('heading', name=re.compile(r'Cost over Time')).locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    legend = chart.locator('.svgc-legend')
    expect(legend.locator('button')).to_have_count(8)
    assert len(set(legend.locator('button').evaluate_all('nodes => nodes.map(n => n.getBoundingClientRect().top)'))) > 1
    def chart_budget():
        return chart.locator('.svgc-responsive').bounding_box()['height'] + legend.bounding_box()['height']
    assert chart_budget() == pytest.approx(380, abs=1)
    page.set_viewport_size({'width': 1200, 'height': 900})
    page.wait_for_function("""() => document.querySelector('.rv-main-chart-plot').getBoundingClientRect().width > 800""")
    assert chart_budget() == pytest.approx(380, abs=1)


def test_donut_legend_is_sorted_without_reordering_sectors(synthetic_page):
    panel = synthetic_page.get_by_role('heading', name='Requests by Provider').locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
    sectors = panel.locator('.svgc-sector')
    expect(sectors).to_have_count(2)
    assert sectors.locator('title').all_text_contents() == ['Synthetic Provider B', 'Synthetic Provider A']
    legend = panel.locator('.rv-donut-legend')
    expect(legend.locator(':scope > span')).to_have_count(2)
    assert legend.locator(':scope > span').all_text_contents() == ['Synthetic Provider A', 'Synthetic Provider B']
