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


def test_calculator_loads_and_recomputes_without_browser_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "tax2")
    assert "react@18.3.1/umd/react.production.min.js" in module.HTML_TEMPLATE
    assert "@babel/standalone@7.29.8/babel.min.js" in module.HTML_TEMPLATE
    assert "cdn.tailwindcss.com/3.4.17" in module.HTML_TEMPLATE
    assert "lucide@1.46.0/dist/umd/lucide.min.js" in module.HTML_TEMPLATE

    errors = []
    with live_server(module.app) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("Tax2", exact=True).wait_for()
        income = page.locator(".income-input").first
        income.fill("5000")
        page.get_by_text("Total Monthly", exact=True).wait_for()
        browser.close()
    assert errors == []
