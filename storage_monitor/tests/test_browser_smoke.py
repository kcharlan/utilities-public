from contextlib import contextmanager
from pathlib import Path
import socket
import sys
import threading
import time

from playwright.sync_api import sync_playwright
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


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


def test_dashboard_loads_tailwind_v4_and_persists_theme_without_browser_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "storage_monitor")
    assert "react@18.3.1/umd/react.development.js" in module.HTML_TEMPLATE
    assert "@babel/standalone@7.29.8/babel.min.js" in module.HTML_TEMPLATE
    assert "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3" in module.HTML_TEMPLATE
    assert "cdn.tailwindcss.com" not in module.HTML_TEMPLATE
    assert "<style>\n    :root" in module.HTML_TEMPLATE
    assert '<style type="text/tailwindcss">' in module.HTML_TEMPLATE
    assert '@source inline("min-h-screen w-full");' in module.HTML_TEMPLATE
    assert "lucide@1.46.0/dist/umd/lucide.min.js" in module.HTML_TEMPLATE

    errors = []
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        route_dashboard_api(page)
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("Storage Monitor", exact=True).wait_for()
        assert page.evaluate("typeof window.lucide?.createIcons") == "function"

        root_styles = page.locator("#root").evaluate(
            "element => ({ minHeight: getComputedStyle(element).minHeight, width: getComputedStyle(element).width })"
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
        assert external_resources == sorted(
            [
                "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3",
                "https://unpkg.com/@babel/standalone@7.29.8/babel.min.js",
                "https://unpkg.com/lucide@1.46.0/dist/umd/lucide.min.js",
                "https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js",
                "https://unpkg.com/react@18.3.1/umd/react.development.js",
            ]
        )

        assert page.evaluate("document.documentElement.dataset.theme") == "light"
        assert page.locator("body").evaluate(
            "element => [getComputedStyle(element).backgroundColor, getComputedStyle(element).color]"
        ) == ["rgb(244, 245, 247)", "rgb(26, 27, 30)"]
        page.get_by_label("Toggle dark mode").click()
        page.wait_for_function(
            "getComputedStyle(document.body).backgroundColor === 'rgb(15, 17, 23)'"
        )
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert page.evaluate("localStorage.getItem('sm-theme')") == "dark"
        assert page.locator("body").evaluate(
            "element => [getComputedStyle(element).backgroundColor, getComputedStyle(element).color]"
        ) == ["rgb(15, 17, 23)", "rgb(226, 228, 233)"]
        page.reload(wait_until="domcontentloaded")
        page.get_by_label("Scan details").wait_for()
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert page.evaluate("localStorage.getItem('sm-theme')") == "dark"
        assert page.locator("body").evaluate(
            "element => [getComputedStyle(element).backgroundColor, getComputedStyle(element).color]"
        ) == ["rgb(15, 17, 23)", "rgb(226, 228, 233)"]
        browser.close()
    assert errors == []


def test_dashboard_keeps_first_party_styles_when_tailwind_cdn_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "storage_monitor")

    page_errors = []
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3", lambda route: route.abort())
        route_dashboard_api(page)

        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("Storage Monitor", exact=True).wait_for()
        assert page.locator("body").evaluate(
            "element => [getComputedStyle(element).backgroundColor, getComputedStyle(element).color]"
        ) == ["rgb(244, 245, 247)", "rgb(26, 27, 30)"]
        browser.close()

    assert page_errors == []
