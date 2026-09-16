from contextlib import contextmanager
import socket
import threading
import time

from playwright.sync_api import sync_playwright
import uvicorn

import mls_tracker


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


def test_embedded_dashboard_loads_and_refreshes_without_browser_errors(monkeypatch):
    assert "react@18.3.1/umd/react.production.min.js" in mls_tracker.HTML_TEMPLATE
    assert "@babel/standalone@7.29.8/babel.min.js" in mls_tracker.HTML_TEMPLATE
    assert "cdn.tailwindcss.com/3.4.17" in mls_tracker.HTML_TEMPLATE
    assert "lucide@1.46.0/dist/umd/lucide.min.js" in mls_tracker.HTML_TEMPLATE

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
    monkeypatch.setattr(mls_tracker.cache, "get_standings", lambda _season: {"Eastern Conference": teams})
    monkeypatch.setattr(mls_tracker.cache, "get_teams", lambda: metadata)

    errors = []
    with live_server(mls_tracker.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("Current Points").wait_for()
        page.get_by_title("Refresh data").click()
        page.get_by_text("Current Points").wait_for()
        browser.close()
    assert errors == []
