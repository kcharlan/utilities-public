from contextlib import contextmanager
from pathlib import Path
import socket
import sys
import threading
import time

import pytest
from playwright.sync_api import sync_playwright
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import (
    assert_no_external_resources,
    assert_offline_page_source,
    block_external_requests,
    assert_classes_styled,
    assert_frontend_vendor_current,
    assert_launcher_compiles_cleanly,
    capture_browser_errors,
    guard_browser_errors,
    load_launcher,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_browser_home(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / "Library/Caches/ms-playwright"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def test_page_loads_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "storage_monitor")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        blocked = block_external_requests(context, allowed_origins=[url])
        page = context.new_page()
        with guard_browser_errors(page):
            route_dashboard_api(page)
            page.goto(url, wait_until="networkidle")
            page.get_by_text("Storage Monitor", exact=True).wait_for(timeout=5000)
            assert_no_external_resources(page, blocked)
            assert_offline_page_source(page.content())
        browser.close()


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


def route_dashboard_api(page, snapshots=None):
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
                    "snapshots": {"items": snapshots or []},
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


def test_controls_update_the_view_immediately(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "storage_monitor")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        route_dashboard_api(page, [
            {"snapshot_name": "synthetic-snapshot-a", "parsed_date": "2030-01-01T00:00:00Z", "action_token": "synthetic-a"},
            {"snapshot_name": "synthetic-snapshot-b", "parsed_date": "2030-01-02T00:00:00Z", "action_token": "synthetic-b"},
        ])
        with guard_browser_errors(page):
            page.goto(url, wait_until="networkidle")
            page.locator(".tab").filter(has_text="Snapshots").click()
            assert_classes_styled(page, ignore=["active"])
            select_all = page.get_by_label("Select all snapshots")
            select_all.check()
            assert page.get_by_label("Select snapshot 2030-01-01T00:00:00Z").is_checked()
            assert page.get_by_label("Select snapshot 2030-01-02T00:00:00Z").is_checked()
            select_all.uncheck()
            assert not page.get_by_label("Select snapshot 2030-01-01T00:00:00Z").is_checked()
        browser.close()


def test_dashboard_persists_theme_without_browser_errors(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "storage_monitor")
    assert_frontend_vendor_current(PROJECT_ROOT / "storage_monitor")
    assert_launcher_compiles_cleanly(PROJECT_ROOT / "storage_monitor")
    assert_offline_page_source(module.HTML_TEMPLATE)

    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        with guard_browser_errors(page):
            route_dashboard_api(page)
            page.goto(url, wait_until="networkidle")
            page.get_by_text("Storage Monitor", exact=True).wait_for()
            assert_classes_styled(page, ignore=["active"])

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


def test_dashboard_keeps_first_party_styles_offline(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "storage_monitor")

    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        with guard_browser_errors(page):
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
