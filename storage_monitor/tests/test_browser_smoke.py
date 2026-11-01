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


def test_same_origin_browser_post_reaches_real_server(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "storage_monitor")
    monkeypatch.setattr(module, "start_scan", lambda: True)
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route("**/api/events", lambda route: route.fulfill(status=200, content_type="text/event-stream", body=""))
        page.goto(url)
        result = page.evaluate("async () => { const r = await fetch('/api/scan', {method: 'POST'}); return [r.status, await r.json()]; }")
        assert result[0] == 200
        assert result[1]["started"] is True
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


GIGABYTE = 1024 ** 3
SYNTHETIC_REPORT_ROWS = {
    "summary": {
        "container_size_bytes": 1000 * GIGABYTE,
        "container_used_bytes": 400 * GIGABYTE,
        "container_free_bytes": 600 * GIGABYTE,
    },
    "breakdowns": {
        "data_root": {
            "total_bytes": 3 * GIGABYTE,
            "updated_at": "2030-01-01T00:00:00Z",
            "items": [
                {
                    "path": "/synthetic/data/folder",
                    "label": "synthetic-folder",
                    "allocated_bytes": 2 * GIGABYTE,
                    "is_file": False,
                    "is_cached": True,
                },
                {
                    "path": "/synthetic/data/file.bin",
                    "label": "synthetic-file.bin",
                    "allocated_bytes": GIGABYTE,
                    "is_file": True,
                },
            ],
        },
    },
    "findings": {
        "updated_at": "2030-01-01T00:00:00Z",
        "items": [
            {
                "path": "/synthetic/cache",
                "label": "Synthetic finding",
                "category": "cache",
                "risk": "low",
                "estimated_reclaim_bytes": GIGABYTE,
                "actions": [
                    {"kind": "execute", "label": "Move to Trash", "action_token": "synthetic-token"},
                ],
            },
        ],
    },
    "large_files": {
        "updated_at": "2030-01-01T00:00:00Z",
        "items": [
            {
                "path": "/synthetic/large.bin",
                "label": "Synthetic large file",
                "allocated_bytes": 2 * GIGABYTE,
            },
        ],
    },
    "providers": {
        "items": [
            {
                "slug": "synthetic-manual",
                "label": "Synthetic manual provider",
                "available": True,
                "risk": "medium",
                "estimate_bytes": GIGABYTE,
                "estimate_kind": "upper_bound",
                "execution": "manual",
                "description": "Synthetic description",
                "manual_command": "synthetic-command --clean",
                "manual_instruction": "Synthetic instruction",
            },
            {
                "slug": "synthetic-unavailable",
                "label": "Synthetic unavailable provider",
                "available": False,
                "risk": "low",
                "estimate_bytes": None,
                "execution": "execute",
                "action_token": "synthetic-provider",
                "unavailable_reason": "Synthetic reason",
            },
        ],
    },
    "orphans": {
        "items": [
            {
                "path": "/synthetic/orphan",
                "name": "Synthetic leftover",
                "source": "group_containers",
                "allocated_bytes": GIGABYTE,
            },
        ],
    },
}
SYNTHETIC_GROWTH = {
    "baselines": [
        {"scan_id": 3, "completed_at": "2030-01-03T00:00:00Z"},
        {"scan_id": 2, "completed_at": "2030-01-02T00:00:00Z"},
    ],
    "baseline_scan_id": 2,
    "current_scan_id": 3,
    "items": [
        {
            "path": "/synthetic/growing",
            "delta_bytes": GIGABYTE,
            "current_bytes": 2 * GIGABYTE,
            "baseline_bytes": GIGABYTE,
        },
    ],
    "updated_at": "2030-01-03T00:00:00Z",
}
TAB_ROWS = {
    "Findings": "Synthetic finding",
    "Snapshots": None,
    "Large Files": "Synthetic large file",
    "Providers": "Synthetic manual provider",
    "Growth": "/synthetic/growing",
    "App Leftovers": "Synthetic leftover",
}


def assert_every_tab_styled(page):
    assert_classes_styled(page, ignore=["active"])
    for tab, row in TAB_ROWS.items():
        page.locator(".tab").filter(has_text=tab).click()
        if row:
            page.get_by_text(row, exact=True).first.wait_for()
        assert_classes_styled(page, ignore=["active"])


def route_dashboard_api(page, snapshots=None, growth=SYNTHETIC_GROWTH):
    page.route(
        "**/api/state",
        lambda route: route.fulfill(
            json={
                "scan_status": {"running": False, "phase": "complete", "progress": 1},
                "report": {
                    **SYNTHETIC_REPORT_ROWS,
                    "generated_at": "2030-01-01T00:00:00Z",
                    "snapshots": {"items": snapshots or []},
                    "checks": [],
                },
            }
        ),
    )
    page.route("**/api/growth*", lambda route: route.fulfill(json=growth))
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
            assert_every_tab_styled(page)

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


def test_growth_baseline_select_never_renders_blank(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "storage_monitor")
    unresolved = {**SYNTHETIC_GROWTH, "baseline_scan_id": None, "current_scan_id": None, "items": []}
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        with guard_browser_errors(page):
            route_dashboard_api(page, growth=unresolved)
            page.goto(url, wait_until="networkidle")
            page.locator(".tab").filter(has_text="Growth").click()
            select = page.locator("select")
            select.locator("option").first.wait_for(state="attached")
            assert select.evaluate("element => element.selectedIndex") == 0
            assert select.input_value() == "3"
        browser.close()


def test_dashboard_keeps_first_party_styles_offline(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "storage_monitor")

    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        blocked = block_external_requests(context, allowed_origins=[url])
        page = context.new_page()
        with guard_browser_errors(page):
            route_dashboard_api(page)

            page.goto(url, wait_until="domcontentloaded")
            page.get_by_text("Storage Monitor", exact=True).wait_for()
            assert page.locator("body").evaluate(
                "element => [getComputedStyle(element).backgroundColor, "
                "getComputedStyle(element).color]"
            ) == ["rgb(244, 245, 247)", "rgb(26, 27, 30)"]
            assert_no_external_resources(page, blocked)
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
