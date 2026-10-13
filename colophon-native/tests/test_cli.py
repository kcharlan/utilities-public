import json
import os
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from helpers import SESSION, REQUEST, extract_payload, row, usage
from browser_errors import guard_browser_errors

def mode(path):
    return stat.S_IMODE(path.stat().st_mode)

def private_runtime(native):
    assert mode(native.runtime) == 0o700
    for path in native.runtime.rglob("*"):
        assert mode(path) == (0o700 if path.is_dir() else 0o600), path

def test_help_and_version_create_no_runtime(native):
    help_result = native.invoke("--help")
    assert help_result.returncode == 0
    for text in ("--offline", "--codex-home", "cache-native/", "COLOPHON_HOME"):
        assert text in help_result.stdout
    version = native.invoke("--version")
    assert version.returncode == 0
    assert version.stdout == "colophon 0.1.0\n"
    assert not native.runtime.exists()

@pytest.mark.parametrize("args,diagnostic", [
    (["--not-synthetic-option"], "unrecognized arguments"),
    (["--output"], "expected one argument"),
    (["--offline", "--refresh-prices"], "cannot be combined"),
    (["--re"], "ambiguous option"),
])
def test_invalid_options_exit_two(native, args, diagnostic):
    result = native.invoke(*args)
    assert result.returncode == 2
    assert diagnostic in result.stderr
    assert "usage: colophon" in result.stderr
    assert not native.runtime.exists()

def test_missing_codex_home_exit_one(native):
    result = native.invoke("--codex-home", str(native.root / "absent"), "--offline", "--no-open")
    assert result.returncode == 1
    assert "colophon:" in result.stderr and "Codex" in result.stderr
    assert not native.page.exists()

def test_empty_offline_home_creates_private_page(native):
    result = native.build()
    assert result.returncode == 0, result.stderr
    assert "0 sessions" in result.stdout and "0 parsed, 0 cached" in result.stdout
    payload = native.payload()
    assert payload["schema"] == 1
    assert payload["sessions"] == []
    private_runtime(native)

def assert_session(payload):
    assert payload["schema"] == 1
    assert len(payload["sessions"]) == 1
    session = payload["sessions"][0]
    assert session["id"] == SESSION
    assert len(session["turns"]) == 1
    turn = session["turns"][0]
    assert turn["id"] == "synthetic-turn"
    assert turn["status"] == "completed"
    assert len(turn["requests"]) == 1
    assert turn["requests"][0]["text"] == REQUEST
    assert turn["requests"][0]["kind"] == "text"
    assert turn["requests"][0]["images"] == 0
    assert turn["final_answer"] == {"text": "Synthetic kite complete", "voice": False}
    return session

def test_nonempty_cold_warm_and_rebuild_preserve_session_usage(native):
    source = native.session()
    before = source.read_bytes()
    sessions = []
    for args, count in [((), "1 parsed, 0 cached"), ((), "0 parsed, 1 cached"), (("--rebuild",), "1 parsed, 0 cached")]:
        result = native.build(*args)
        assert result.returncode == 0, result.stderr
        assert count in result.stdout
        payload = native.payload()
        assert payload["meta"]["counts"] == {"logs": 1, "parsed": int("1 parsed" in count), "cached": int("1 cached" in count), "sessions": 1, "subagents": 0, "orphans": 0}
        sessions.append(assert_session(payload))
        assert source.read_bytes() == before
        private_runtime(native)
    assert sessions[0] == sessions[1] == sessions[2]
    usage = sessions[0]["own_usage"]
    assert usage["input"] == 120
    assert usage["cached_input"] == 20
    assert usage["output"] == 30
    assert usage["reasoning"] == 5

@pytest.mark.parametrize("status,diagnostic", [(0, "unstable sort is forbidden"), (1, ""), (2, "stable-sort search failed (status 2)")])
def test_build_sort_guard_preserves_search_status(tmp_path, status, diagnostic):
    project = Path(__file__).resolve().parents[1]
    rg = tmp_path / "rg"
    rg.write_text(f"#!/bin/sh\nexit {status}\n")
    rg.chmod(0o700)
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    result = subprocess.run(["make", "check-sort"], cwd=project, env=env, text=True, capture_output=True)
    assert (result.returncode == 0) == (status == 1)
    assert diagnostic in result.stderr

def test_browser_error_guard_fails_on_console_and_page_errors():
    class Page:
        def __init__(self):
            self.listeners = {}
        def on(self, event, listener):
            self.listeners[event] = listener
        def remove_listener(self, event, listener):
            assert self.listeners.pop(event) is listener
    page = Page()
    with pytest.raises(AssertionError, match="synthetic page error"):
        with guard_browser_errors(page):
            page.listeners["pageerror"]("synthetic page error")
    assert not page.listeners
    class Message:
        type = "error"
        text = "synthetic console error"
    with pytest.raises(AssertionError, match="synthetic console error"):
        with guard_browser_errors(page):
            page.listeners["console"](Message())
    assert not page.listeners

def test_output_override_and_existing_ledger_are_preserved(native):
    source = native.session()
    original = source.read_bytes()
    native.runtime.mkdir(mode=0o700)
    ledger = native.runtime / "price-history.json"
    content = b'{"schema":1,"entries":[{"model":"synthetic-ledger-model","effective_from":null,"per_million":{"input":1,"output":2,"cached_input":0.5,"cache_write":1},"source":"synthetic","note":"invented preservation sentinel"}]}\n'
    ledger.write_bytes(content)
    ledger.chmod(0o600)
    output = native.root / "synthetic-output.html"
    result = native.build("--output", str(output))
    assert result.returncode == 0, result.stderr
    assert_session(native.payload(output))
    assert mode(output) == 0o600
    assert not native.page.exists()
    assert ledger.read_bytes() == content
    assert source.read_bytes() == original
    private_runtime(native)

def test_loopback_catalog_fetch_uses_only_synthetic_endpoint(native):
    calls = []
    catalog = {"openai": {"models": {"synthetic-kite-model": {"id": "synthetic-kite-model", "name": "Synthetic Kite", "cost": {"input": 1, "output": 2}}}}}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            body = json.dumps(catalog).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        native.env["COLOPHON_PRICING_URL"] = f"http://127.0.0.1:{server.server_port}/synthetic-catalog.json"
        result = native.build("--refresh-prices", offline=False)
        assert result.returncode == 0, result.stderr
        assert calls == ["/synthetic-catalog.json"]
        assert native.payload()["meta"]["catalog"]["source_host"] == "127.0.0.1"
        assert native.payload()["meta"]["catalog"]["status"] == "fetched"
        assert "synthetic-kite-model" in (native.runtime / "pricing-cache.json").read_text()
        private_runtime(native)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

@pytest.mark.parametrize("html", ["<html></html>", '<script id="colophon-data">[]</script>', '<script id="colophon-data">broken</script>', '<script id="colophon-data">{}</script><script id="colophon-data">{}</script>'])
def test_payload_helper_rejects_corruption(html):
    with pytest.raises(ValueError):
        extract_payload(html)

def test_local_asset_checker_rejects_corruption_and_missing_asset(tmp_path):
    project = Path(__file__).resolve().parents[1]
    assets = tmp_path / "assets"
    assets.mkdir()
    for path in (project / "assets").iterdir():
        (assets / path.name).write_bytes(path.read_bytes())
    command = ["perl", str(project / "tools/check_assets.pl"), str(assets)]
    assert subprocess.run(command, capture_output=True).returncode == 0
    asset = assets / "page.js"
    original = asset.read_bytes()
    asset.write_bytes(original + b"synthetic corruption")
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0 and "digest mismatch: page.js" in result.stderr
    asset.write_bytes(original)
    asset.unlink()
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0 and "page.js" in result.stderr
    asset.write_bytes(original)
    assert subprocess.run(command, capture_output=True).returncode == 0

def test_long_context_threshold_prices_250k_request_at_standard_rates(native):
    turn = "synthetic-long-turn"
    native.write_session([
        row("session_meta", {"id": SESSION, "cwd": "/synthetic/kite", "source": "cli"}, 0),
        row("turn_context", {"model": "gpt-6.1-sol", "turn_id": turn}, 1),
        row("event_msg", {"type": "task_started", "turn_id": turn}, 1),
        row("event_msg", {"type": "token_count", "turn_id": turn, "info": {
            "last_token_usage": usage(250_000, 0, 1_000), "total_token_usage": usage(250_000, 0, 1_000)}}, 3),
    ])
    result = native.build()
    assert result.returncode == 0, result.stderr
    cost = native.payload()["sessions"][0]["own_usage"]["cost_usd"]
    # 250,000 × $2/M + 1,000 × $10/M; the 200K threshold would give 1.015.
    assert cost == pytest.approx(0.51)
