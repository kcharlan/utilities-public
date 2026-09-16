from contextlib import contextmanager
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
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import ASGISyncClient, load_launcher


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


def test_dashboard_recharts_interactions_and_resource_graph(tmp_path):
    module = load_launcher(Path(__file__).resolve().parents[1] / "routerview")
    assert "react@18.3.1/umd/react.production.min.js" in module.HTML_TEMPLATE
    assert "@babel/standalone@7.29.8/babel.min.js" in module.HTML_TEMPLATE
    assert "cdn.tailwindcss.com/3.4.17" in module.HTML_TEMPLATE
    assert "react-is@18.3.1/umd/react-is.production.min.js" in module.HTML_TEMPLATE
    assert "recharts@3.10.1/umd/Recharts.js" in module.HTML_TEMPLATE
    module._db_path = str(tmp_path / "routerview.db")
    module.init_database(module._db_path)
    seed_synthetic_dashboard(module)

    errors = []
    requests = []
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: requests.append(request.url))
        page.goto(f"{url}?range=all", wait_until="networkidle")
        page.get_by_text("RouterView", exact=True).wait_for()
        assert errors == []

        chart_heading = page.get_by_role("heading", name=re.compile(r"Cost over Time\s*by model"))
        chart_heading.wait_for()
        chart_wrapper = page.locator(".recharts-wrapper").first
        chart_wrapper.wait_for(state="visible")
        chart = chart_wrapper.locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
        chart_box = chart_wrapper.bounding_box()
        assert chart_box and chart_box["width"] > 200 and chart_box["height"] > 200

        tooltip = chart.locator(".recharts-tooltip-wrapper")
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

        curves = chart.locator("path.recharts-area-curve")
        expect(curves).to_have_count(2)
        expect(curves.nth(0)).to_have_attribute("stroke-opacity", "1")
        expect(curves.nth(1)).to_have_attribute("stroke-opacity", "1")
        chart.locator(".recharts-legend-item", has_text="beta").click()
        expect(curves.nth(1)).to_have_attribute("stroke-opacity", "0")

        provider_heading = page.get_by_role("heading", name="Requests by Provider")
        provider_panel = provider_heading.locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
        sectors = provider_panel.locator("path.recharts-sector")
        expect(sectors).to_have_count(2)
        assert len({sectors.nth(i).get_attribute("fill") for i in range(2)}) == 2

        model_heading = page.get_by_role("heading", name="Cost by Model")
        model_panel = model_heading.locator("xpath=ancestor::div[contains(@class,'bg-slate-800')][1]")
        bars = model_panel.locator("path.recharts-rectangle")
        expect(bars).to_have_count(2)
        bars.first.click()
        page.get_by_text(re.compile(r"model:(?:alpha|beta)"), exact=False).wait_for()
        expect(page).to_have_url(re.compile(r"[?&]model=(?:alpha|beta)(?:&|$)"))

        page.keyboard.press("?")
        page.get_by_text("Keyboard Shortcuts", exact=True).wait_for()
        assert browser.version
        browser.close()

    package_requests = [
        request
        for request in requests
        if re.search(r"/(react(?:-dom|-is)?)(?:/|@)", request)
    ]
    assert [request for request in package_requests if re.search(r"/react(?:/|@)", request)] == [
        "https://unpkg.com/react@18.3.1/umd/react.production.min.js"
    ]
    assert [request for request in package_requests if re.search(r"/react-dom(?:/|@)", request)] == [
        "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"
    ]
    assert [request for request in package_requests if re.search(r"/react-is(?:/|@)", request)] == [
        "https://unpkg.com/react-is@18.3.1/umd/react-is.production.min.js"
    ]
    assert requests.count("https://unpkg.com/recharts@3.10.1/umd/Recharts.js") == 1
    assert errors == []


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
        page.goto(url, wait_until="networkidle")

        heading = page.get_by_role(
            "heading", name=re.compile(r"Cost over Time\s*by model")
        )
        panel = heading.locator(
            "xpath=ancestor::div[contains(@class,'bg-slate-800')][1]"
        )
        wrappers = panel.locator(".recharts-wrapper")
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
            lines = panel.locator(".recharts-reference-line-line")
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
        page.goto(url, wait_until="networkidle")
        page.locator('select:has(option[value="bar"])').select_option("bar")

        heading = page.get_by_role(
            "heading", name=re.compile(r"Cost over Time\s*by model")
        )
        panel = heading.locator(
            "xpath=ancestor::div[contains(@class,'bg-slate-800')][1]"
        )
        wrappers = panel.locator(".recharts-wrapper")
        expect(wrappers).to_have_count(2)
        bounds = rendered_plot_bounds(wrappers.nth(0))
        assert bounds and bounds["width"] > 200

        for position, source_index in ((0.24, 0), (0.26, 1), (0.74, 2), (0.76, 3)):
            page.mouse.move(
                bounds["x"] + bounds["width"] * position,
                bounds["y"] + bounds["height"] / 2,
            )
            lines = panel.locator(".recharts-reference-line-line")
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
        page.goto(url, wait_until="networkidle")

        heading = page.get_by_role(
            "heading", name=re.compile(r"Cost over Time\s*by model")
        )
        panel = heading.locator(
            "xpath=ancestor::div[contains(@class,'bg-slate-800')][1]"
        )
        wrappers = panel.locator(".recharts-wrapper")
        expect(wrappers).to_have_count(2)
        bounds = rendered_plot_bounds(wrappers.nth(0))
        assert bounds and bounds["width"] > 200

        page.mouse.move(
            bounds["x"] + bounds["width"] / 2,
            bounds["y"] + bounds["height"] / 2,
        )
        lines = panel.locator(".recharts-reference-line-line")
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
        page.goto(f"{url}?range=all", wait_until="networkidle")

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
