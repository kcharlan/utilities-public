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


def test_findings_groups_age_filter_and_scan_details(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "storage_monitor")
    rows = [
        {"path": "/synthetic/old", "label": "Old cache", "category": "cache", "risk": "low", "allocated_bytes": 1024, "actionable": True, "estimated_reclaim_bytes": 1024, "age_days": 412, "stale": True, "actions": []},
        {"path": "/synthetic/fresh", "label": "Fresh cache", "category": "cache", "risk": "medium", "allocated_bytes": 2048, "age_days": 0, "stale": False, "actions": []},
        {"path": None, "label": "Synthetic group", "category": "dev_artifact", "risk": "medium", "allocated_bytes": 512, "group": True, "items": [{"path": "/synthetic/child", "label": "Synthetic child", "allocated_bytes": 512}], "actions": []},
        *[{"path": f"/synthetic/{category}", "label": f"Synthetic {category}", "category": category, "risk": "high", "allocated_bytes": 256, "actions": []} for category in ("temp", "agent_residue", "trash", "user_data")],
    ]
    report = {**SYNTHETIC_REPORT_ROWS, "findings": {"items": rows, "truncated": {"cache": {"count": 2, "bytes": 3072}}}, "unreadable": {"count": 1, "items": [{"path": "/synthetic/denied", "reason": "Permission denied"}]}, "checks": []}
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        route_dashboard_api(page)
        page.route("**/api/state", lambda route: route.fulfill(json={"scan_status": {"running": False}, "report": report, "config_warning": "Invalid Storage Monitor config: synthetic error"}))
        with guard_browser_errors(page):
            page.goto(url, wait_until="networkidle")
            assert page.get_by_text("Invalid Storage Monitor config: synthetic error").is_visible()
            assert page.get_by_text("Caches", exact=False).count() > 0
            for heading in ("Caches · 3.0 KB", "Developer · 512 B", "Temp · 256 B", "Agent leftovers · 256 B", "Trash · 256 B", "Review-only user data · 256 B"):
                assert page.get_by_text(heading, exact=True).is_visible()
            assert page.get_by_text("2 more not shown (3.0 KB)").is_visible()
            assert page.get_by_text("412 d").is_visible()
            assert page.get_by_text("today", exact=True).is_visible()
            assert page.get_by_text("—", exact=True).count() > 0
            page.get_by_role("button", name="Age", exact=True).click()
            assert page.get_by_text("Old cache").bounding_box()["y"] < page.get_by_text("Fresh cache").bounding_box()["y"]
            page.get_by_text("Synthetic group").click()
            assert page.get_by_text("Synthetic child").is_visible()
            page.get_by_label("Stale only").check()
            assert not page.get_by_text("Fresh cache").is_visible()
            page.get_by_label("Scan details").click()
            assert page.get_by_text("/synthetic/denied: Permission denied").is_visible()
            assert page.get_by_text("Trashable now").is_visible()
            assert page.get_by_text("In Trash").is_visible()
            assert page.get_by_text("Review:", exact=False).is_visible()
            assert page.get_by_text("Trashable now: 1.0 KB").is_visible()
            assert page.get_by_text("In Trash: 256 B").is_visible()
            assert page.get_by_text("Review: 3.3 KB").is_visible()
        browser.close()


def test_equal_label_groups_expand_independently(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "storage_monitor")
    groups = [{"path": f"/synthetic/root-{name}", "label": "Equal group", "category": "temp", "risk": "low", "group": True, "allocated_bytes": 1, "items": [{"path": f"/synthetic/root-{name}/child", "label": f"Child {name}", "allocated_bytes": 1}], "actions": []} for name in ("a", "b")]
    report = {**SYNTHETIC_REPORT_ROWS, "findings": {"items": groups}}
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        route_dashboard_api(page)
        page.route("**/api/state", lambda route: route.fulfill(json={"scan_status": {"running": False}, "report": report}))
        with guard_browser_errors(page):
            page.goto(url, wait_until="networkidle")
            page.get_by_role("button", name="Equal group").first.click()
            assert page.get_by_text("Child a", exact=False).is_visible()
            assert page.get_by_text("Child b", exact=False).count() == 0
            page.get_by_role("button", name="Equal group").last.click()
            assert page.get_by_text("Child b", exact=False).is_visible()
        browser.close()


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


@pytest.mark.parametrize("admin", [False, True])
def test_single_snapshot_delete_requires_confirmation(monkeypatch, tmp_path, admin):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "storage_monitor")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(timezone_id="UTC")
        route_dashboard_api(page, [{"snapshot_name": "synthetic-snapshot-a", "parsed_date": "2030-01-01T00:00:00Z", "action_token": "synthetic-a"}])
        requests = []
        dialogs = []

        def execute(route):
            requests.append(route.request.post_data_json)
            route.fulfill(json={"ok": True, "label": "Deleted Snapshot", "snapshot_name": "synthetic-snapshot-a"})

        def confirm(dialog):
            dialogs.append(dialog.message)
            if len(dialogs) == 1:
                dialog.dismiss()
            else:
                dialog.accept()

        page.route("**/api/actions/execute", execute)
        page.on("dialog", confirm)
        page.goto(url, wait_until="networkidle")
        page.locator(".tab").filter(has_text="Snapshots").click()
        button = page.get_by_title("Delete with admin privileges (password prompt)") if admin else page.get_by_role("button", name="Delete", exact=True)
        button.click()
        assert len(dialogs) == 1
        assert requests == []
        button.click()
        page.get_by_text("Deleted Snapshot", exact=True).wait_for()
        assert len(dialogs) == 2
        assert all("Jan 1, 2030" in message and "cannot be undone" in message for message in dialogs)
        assert requests == [{"action_token": "synthetic-a", "elevate": admin}]
        browser.close()


def test_finding_trash_requires_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(PROJECT_ROOT / "storage_monitor")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        route_dashboard_api(page)
        requests = []
        dialogs = []

        def execute(route):
            requests.append(route.request.post_data_json)
            route.fulfill(json={"ok": True, "label": "Moved to Trash", "source_path": "/synthetic/cache"})

        def confirm(dialog):
            dialogs.append(dialog.message)
            if len(dialogs) == 1:
                dialog.dismiss()
            else:
                dialog.accept()

        page.route("**/api/actions/execute", execute)
        page.on("dialog", confirm)
        with guard_browser_errors(page):
            page.goto(url, wait_until="networkidle")
            button = page.get_by_role("button", name="Trash", exact=True)
            button.click()
            assert len(dialogs) == 1
            assert requests == []
            button.click()
            page.get_by_text("Moved to Trash", exact=False).first.wait_for()
            assert len(dialogs) == 2
            assert all("/synthetic/cache" in message and "Trash" in message for message in dialogs)
            assert requests == [{"action_token": "synthetic-token", "elevate": False}]
        browser.close()


def test_temp_group_confirmation_shows_rule_and_only_sends_on_accept(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    monkeypatch.setitem(SYNTHETIC_REPORT_ROWS, "findings", {"items": [{
        "path": "/synthetic/temp", "label": "2 old entries", "category": "temp", "risk": "low",
        "count": 2, "cleanup_kind": "trash_group", "estimated_reclaim_bytes": 10,
        "actions": [{"kind": "execute", "label": "Move to Trash", "action_token": "synthetic-group"}],
    }]})
    module = load_launcher(PROJECT_ROOT / "storage_monitor")
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        route_dashboard_api(page)
        requests, dialogs = [], []
        def execute(route):
            requests.append(route.request.post_data_json)
            route.fulfill(json={"ok": True, "label": "Moved to Trash"})
        def confirm(dialog):
            dialogs.append(dialog.message)
            dialog.dismiss() if len(dialogs) == 1 else dialog.accept()
        page.route("**/api/actions/execute", execute)
        page.on("dialog", confirm)
        with guard_browser_errors(page):
            page.goto(url, wait_until="networkidle")
            button = page.get_by_role("button", name="Trash", exact=True)
            button.click()
            assert requests == []
            button.click()
            page.get_by_text("Moved to Trash", exact=False).first.wait_for()
            assert all("/synthetic/temp" in message and "2 entries" in message and "3 days" in message for message in dialogs)
            assert requests == [{"action_token": "synthetic-group", "elevate": False}]
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
