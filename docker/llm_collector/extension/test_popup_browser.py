"""Exercise the real unpacked popup using synthetic loopback-only data."""
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import sys
import threading
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.testkit import guard_browser_errors


class StubCollector:
    def __init__(self, port):
        self.port = port
        self.counters = {"chatgpt.com": 42, "gemini.google.com": 17}
        self.sequences = {}
        self.server = None

    def start(self):
        collector = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, status, body):
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self.reply(200, {"ok": True})
                elif self.headers.get("X-API-KEY") != "synthetic-popup-test-key":
                    self.reply(403, {"error": "synthetic key mismatch"})
                elif parsed.path == "/counters":
                    self.reply(200, {"counters": collector.counters})
                elif parsed.path == "/client_status":
                    client = parse_qs(parsed.query)["client_id"][0]
                    self.reply(200, {"client_id": client, "last_seq": collector.sequences.get(client, 0)})
                else:
                    self.reply(404, {"error": "synthetic unknown route"})

            def do_POST(self):
                if self.headers.get("X-API-KEY") != "synthetic-popup-test-key":
                    self.reply(403, {"error": "synthetic key mismatch"})
                    return
                if self.path != "/add":
                    self.reply(404, {"error": "synthetic unknown route"})
                    return
                batch = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                client, seq = batch["client_id"], batch["seq"]
                applied = 0
                if seq > collector.sequences.get(client, 0):
                    for host, count in batch["deltas"].items():
                        collector.counters[host] = collector.counters.get(host, 0) + count
                        applied += count
                    collector.sequences[client] = seq
                self.reply(200, {"ok": True, "last_seq": collector.sequences[client], "applied": applied})

        class Server(ThreadingHTTPServer):
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture(scope="module")
def collector():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    stub = StubCollector(port)
    stub.start()
    yield stub
    stub.stop()


@pytest.fixture(scope="module")
def extension(tmp_path_factory, collector):
    target = tmp_path_factory.mktemp("synthetic-popup-extension") / "extension"
    shutil.copytree(Path(__file__).parent, target, ignore=shutil.ignore_patterns("config.local.js", "__pycache__", ".pytest_cache"))
    (target / "config.local.js").write_text(
        "globalThis.LLM_USAGE_CONFIG = " + json.dumps({
            "collectorUrl": collector.url, "apiKey": "synthetic-popup-test-key"
        }) + ";\n"
    )
    return target


@contextmanager
def open_popup(extension, collector, profile, color_scheme):
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=profile, channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
            viewport={"width": 360, "height": 600}, color_scheme=color_scheme,
        )
        requests = []
        context.on("request", lambda request: requests.append(request.url))
        try:
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
            extension_id = urlparse(worker.url).netloc
            page = context.new_page()
            with guard_browser_errors(page):
                page.goto(f"chrome-extension://{extension_id}/popup.html")
                expect(page.locator("#status")).to_have_attribute("data-state", "connected")
                yield page
            assert all(url.startswith((f"chrome-extension://{extension_id}/", collector.url + "/")) for url in requests), requests
        finally:
            context.close()


@pytest.fixture
def popup(extension, collector, tmp_path, color_scheme):
    with open_popup(extension, collector, tmp_path / "profile", color_scheme) as page:
        yield page


def screenshot(page, tmp_path, case):
    path = tmp_path / f"{case}.png"
    page.screenshot(path=path, full_page=True)
    print(f"Popup screenshot: {path}")


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_connected(popup, tmp_path):
    expect(popup.locator("#registerHeading")).to_have_text("Requests since last reset")
    expect(popup.locator("#register > .row")).to_have_count(2)
    expect(popup.locator("#registerTotal")).to_have_text("59")
    assert popup.locator("body").evaluate("node => getComputedStyle(node).fontSize") == "13px"
    screenshot(popup, tmp_path, "connected")


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_collector_down(popup, collector, tmp_path):
    collector.stop()
    try:
        popup.locator("#reload").click()
        expect(popup.locator("#status")).to_have_attribute("data-state", "error")
        expect(popup.locator("#registerHeading")).to_have_text("Waiting to send")
        screenshot(popup, tmp_path, "collector-down")
    finally:
        collector.start()


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_no_horizontal_scroll(popup, tmp_path):
    assert popup.evaluate("document.documentElement.scrollWidth") <= 360
    screenshot(popup, tmp_path, "width")


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_footer_stays_visible(popup, tmp_path):
    for fold in ["deliveryFold", "captureFold", "logFold"]:
        popup.locator(f"#{fold} > summary").click()
    popup.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    box = popup.locator("footer").bounding_box()
    assert box["y"] >= 0 and box["y"] + box["height"] <= 600
    assert popup.locator("#logList > .none").evaluate("node => getComputedStyle(node).display") == "block"
    screenshot(popup, tmp_path, "folds-open")


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_poll_preserves_fold(popup, tmp_path):
    popup.locator("#deliveryFold > summary").click()
    popup.evaluate("refresh({showChecking:false})")
    assert popup.locator("#deliveryFold").evaluate("node => node.open")
    screenshot(popup, tmp_path, "preserved-fold")


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_capture_switch(popup, tmp_path):
    popup.locator("#captureFold > summary").click()
    toggle = popup.locator("#captureToggle")
    was_checked = toggle.is_checked()
    toggle.click()
    expect(toggle).to_be_checked(checked=not was_checked)
    expect(popup.locator("#captureState")).to_have_text("Off" if was_checked else "On, 0 held")
    screenshot(popup, tmp_path, "capture-switch")


def test_system_appearance_changes_background(extension, collector, tmp_path):
    backgrounds = []
    for color_scheme in ["light", "dark"]:
        with open_popup(extension, collector, tmp_path / color_scheme, color_scheme) as page:
            backgrounds.append(page.locator("body").evaluate("node => getComputedStyle(node).backgroundColor"))
            screenshot(page, tmp_path, f"system-{color_scheme}")
    assert backgrounds[0] != backgrounds[1]
