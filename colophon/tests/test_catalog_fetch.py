"""Catalog requests use synthetic loopback servers and private temporary caches."""

import contextlib
import http.server
import json
import os
import socket
import stat
import threading
import time

import pytest


CATALOG = {"openai": {"id": "openai", "models": {
    "synthetic-model": {"id": "synthetic-model", "cost": {"input": 3, "output": 9}}
}}, "synthetic-other": {"models": {}}}
SUBSET = {"openai": CATALOG["openai"]}
NOW = 2030000000000


@pytest.fixture
def serve():
    servers = []

    def start(respond):
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            # Keep HTTP/1.0: getresponse clears conn.sock for closing responses.
            def do_GET(self):
                requests.append((self.path, dict(self.headers)))
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    respond(self)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}/synthetic-catalog.json", requests

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join()


def reply(handler, status=200, body=None, etag='"synthetic-etag"'):
    body = json.dumps(CATALOG).encode() if body is None else body
    handler.send_response(status)
    if etag is not None:
        handler.send_header("ETag", etag)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def write_cache(path, url, *, catalog=SUBSET, etag='"synthetic-etag"'):
    path.write_text(json.dumps({"schema": 1, "url": url, "etag": etag,
                                "fetched_at_ms": NOW - 1000, "catalog": catalog}))


def fetch(colophon, url, path, **kwargs):
    return colophon.fetch_catalog(url, path, offline=kwargs.get("offline", False),
                                 refresh=kwargs.get("refresh", False), now_ms=NOW)


def test_200_etag_subset_private_atomic_cache_and_http10(colophon, serve, tmp_path):
    url, requests = serve(reply)
    path = tmp_path / "pricing-cache.json"
    result = fetch(colophon, url + "?synthetic=1", path)
    assert result.status == "fetched"
    assert result.catalog == SUBSET
    assert (result.fetched_at_ms, result.checked_at_ms, result.messages) == (NOW, NOW, [])
    assert requests == [("/synthetic-catalog.json?synthetic=1", requests[0][1])]
    assert "If-None-Match" not in requests[0][1]
    assert json.loads(path.read_text()) == {"schema": 1, "etag": '"synthetic-etag"',
        "fetched_at_ms": NOW, "url": url + "?synthetic=1", "catalog": SUBSET}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_conditional_304_preserves_fetch_time_and_cache_bytes(colophon, serve, tmp_path):
    url, requests = serve(lambda h: reply(h, 304, b""))
    path = tmp_path / "pricing-cache.json"
    write_cache(path, url)
    before = path.read_bytes()
    result = fetch(colophon, url, path)
    assert requests[0][1]["If-None-Match"] == '"synthetic-etag"'
    assert result.status == "not_modified" and result.catalog == SUBSET
    assert result.fetched_at_ms == NOW - 1000 and result.checked_at_ms == NOW
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["refresh", "different_url", "no_etag"])
def test_unconditional_requests(colophon, serve, tmp_path, kind):
    url, requests = serve(reply)
    path = tmp_path / "pricing-cache.json"
    cached_url = "http://127.0.0.1:9/synthetic-old.json" if kind == "different_url" else url
    write_cache(path, cached_url, etag=None if kind == "no_etag" else '"synthetic-etag"')
    result = fetch(colophon, url, path, refresh=kind == "refresh")
    assert result.status == "fetched"
    assert "If-None-Match" not in requests[0][1]
    if kind == "different_url":
        assert any(url in message and cached_url in message for message in result.messages)


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("status,body", [(500, b"synthetic failure"), (200, b"{"),
    (200, b'{"synthetic-other": {}}'), (200, b"[]"), (200, b'{"openai": NaN}'),
    (204, b"")])
def test_failure_fallback(colophon, serve, tmp_path, cached, status, body):
    url, _ = serve(lambda h: reply(h, status, body))
    path = tmp_path / "pricing-cache.json"
    if cached:
        write_cache(path, url)
    before = path.read_bytes() if cached else None
    result = fetch(colophon, url, path)
    assert result.status == ("cached" if cached else "unavailable")
    assert result.catalog == (SUBSET if cached else None)
    assert result.fetched_at_ms == (NOW - 1000 if cached else None)
    assert result.checked_at_ms == NOW and result.messages
    assert (path.read_bytes() if path.exists() else None) == before


def test_redirect_is_not_followed(colophon, serve, tmp_path):
    def redirect(h):
        h.send_response(302)
        h.send_header("Location", "/synthetic-target.json")
        h.end_headers()

    url, requests = serve(redirect)
    result = fetch(colophon, url, tmp_path / "pricing-cache.json")
    assert result.status == "unavailable" and len(requests) == 1
    assert any("302" in m for m in result.messages)


@pytest.mark.parametrize("cached", [False, True])
def test_offline_never_opens_socket(colophon, tmp_path, monkeypatch, cached):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline must not open any socket")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    url = "http://127.0.0.1:9/synthetic-catalog.json"
    path = tmp_path / "pricing-cache.json"
    if cached:
        write_cache(path, url)
    result = fetch(colophon, url, path, offline=True)
    assert result.status == ("offline" if cached else "unavailable")
    assert result.catalog == (SUBSET if cached else None)
    assert result.checked_at_ms is None


@pytest.mark.parametrize("style", ["sleep", "drip"])
def test_header_total_budget(colophon, serve, tmp_path, monkeypatch, style):
    def delayed(h):
        if style == "sleep":
            time.sleep(1)
            reply(h)
        else:
            h.wfile.write(b"HTTP/1.0 200 OK\r\n")
            h.wfile.flush()
            for _ in range(10):
                time.sleep(0.15)
                h.wfile.write(b"X-Synthetic: value\r\n")
                h.wfile.flush()
            h.wfile.write(b"\r\n{}")

    monkeypatch.setattr(colophon, "CONNECT_TIMEOUT_S", 0.5)
    url, _ = serve(delayed)
    started = time.monotonic()
    result = fetch(colophon, url, tmp_path / "pricing-cache.json")
    elapsed = time.monotonic() - started
    assert result.status == "unavailable" and elapsed < 0.9
    assert any("timeout" in m.lower() for m in result.messages)


def test_body_total_budget_uses_saved_http10_socket(colophon, serve, tmp_path, monkeypatch):
    def trickle(h):
        h.send_response(200)
        h.send_header("Content-Length", "20")
        h.end_headers()
        for _ in range(20):
            h.wfile.write(b" ")
            h.wfile.flush()
            time.sleep(0.1)

    monkeypatch.setattr(colophon, "BODY_TIMEOUT_S", 0.5)
    url, _ = serve(trickle)
    path = tmp_path / "pricing-cache.json"
    write_cache(path, url)
    started = time.monotonic()
    result = fetch(colophon, url, path)
    assert time.monotonic() - started < 0.9
    assert result.status == "cached" and result.catalog == SUBSET
    assert any("timeout" in m.lower() for m in result.messages)


def test_connection_failure_and_unknown_scheme(colophon, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    path = tmp_path / "pricing-cache.json"
    result = fetch(colophon, f"http://127.0.0.1:{port}/synthetic.json", path)
    assert result.status == "unavailable" and result.checked_at_ms == NOW and result.messages
    result = fetch(colophon, "file:///synthetic/catalog.json", path)
    assert result.status == "unavailable" and result.checked_at_ms is None
    assert any("scheme" in m for m in result.messages)


def test_304_without_matching_cache_is_failure(colophon, serve, tmp_path):
    url, _ = serve(lambda h: reply(h, 304, b""))
    path = tmp_path / "pricing-cache.json"
    result = fetch(colophon, url, path)
    assert result.status == "unavailable" and result.messages
    old_url = "http://127.0.0.1:9/synthetic-old.json"
    write_cache(path, old_url)
    result = fetch(colophon, url, path)
    assert result.status == "cached" and result.catalog == SUBSET
    assert any(old_url in m and url in m for m in result.messages)


@pytest.mark.parametrize("damaged", ["{", '{"schema": true}',
    '{"schema": 1, "url": "synthetic", "fetched_at_ms": true, "catalog": {"openai": {}}}'])
def test_invalid_cache_is_not_evidence(colophon, tmp_path, damaged):
    path = tmp_path / "pricing-cache.json"
    path.write_text(damaged)
    result = fetch(colophon, "http://127.0.0.1:9/synthetic.json", path, offline=True)
    assert result.status == "unavailable" and result.catalog is None and result.messages


@pytest.mark.parametrize("lexeme,integer", [
    # Foundation JSONDecoder fixed-width slow path: Double below 2^53,
    # UInt128 Decimal compaction then UInt64 sizing before scaling above it.
    ("1.0000000000000001", 1), ("9007199254740993.0", 9007199254740993),
    ("9007199254740993.00000000000000000001", None),
    ("9007199254740993.00000000000000000000001", 9007199254740993),
    ("9007199254740993.1", 9007199254740993),
    ("-9223372036854775807.0", -9223372036854775807),
    ("9223372036854775807.0", None), ("-9223372036854775808.0", None),
    ("-9223372036854775808", -9223372036854775808), ("9223372036854775808", None),
    ("true", None), ("1.5", None), ("1e999", None),
])
def test_raw_context_acceptance_survives_network_and_cache(colophon, serve, tmp_path, lexeme, integer):
    raw = ('{"openai":{"models":{"synthetic-model":{"id":"synthetic-model",'
           '"cost":{"input":1.0000000000000001,"output":9},'
           '"limit":{"context":' + lexeme + '}}}}}').encode()
    url, _ = serve(lambda h: reply(h, body=raw))
    path = tmp_path / "pricing-cache.json"
    result = fetch(colophon, url, path)
    assert result.status == "fetched"
    for catalog in (result.catalog, fetch(colophon, url, path, offline=True).catalog):
        pricing = colophon.ModelsDevIndex.from_catalog(catalog).pricing("openai", "synthetic-model")
        assert (pricing is not None) == (integer is not None)
        if integer is not None:
            assert catalog["openai"]["models"]["synthetic-model"]["limit"]["context"] == integer
            assert pricing["per_million"]["input"] == 1.0  # source Double semantics
    # Raw cache ingestion also preserves spelling before float conversion.
    path.write_text('{"schema":1,"url":' + json.dumps(url) + ',"fetched_at_ms":' +
                    str(NOW) + ',"etag":null,"catalog":' + raw.decode() + '}')
    cached = fetch(colophon, url, path, offline=True)
    pricing = colophon.ModelsDevIndex.from_catalog(cached.catalog).pricing("openai", "synthetic-model")
    assert (pricing is not None) == (integer is not None)


def test_runtime_home_removes_only_old_direct_regular_hidden_temps(colophon, home, tmp_path, monkeypatch):
    home.mkdir()
    monkeypatch.setattr(colophon.time, "time", lambda: NOW / 1000)
    old = home / ".pricing-cache.json.synthetic.tmp"
    young = home / ".pricing-cache.json.concurrent.tmp"
    boundary = home / ".boundary.tmp"
    visible = home / "synthetic.tmp"
    directory = home / ".directory.tmp"
    directory.mkdir()
    target = tmp_path / "synthetic-link-target"
    target.write_text("Synthetic keep")
    link = home / ".link.tmp"
    link.symlink_to(target)
    for path, age in ((old, 3601), (young, 10), (boundary, 3600), (visible, 4000)):
        path.write_text("Synthetic temp")
        os.utime(path, (NOW / 1000 - age,) * 2)
    os.utime(link, (NOW / 1000 - 4000,) * 2, follow_symlinks=False)
    colophon.ensure_runtime_home(home)
    assert not old.exists()
    assert all(p.exists() for p in (young, boundary, visible, directory, link, target))


def test_cache_write_failure_returns_existing_fallback(colophon, serve, tmp_path, monkeypatch):
    url, _ = serve(reply)
    path = tmp_path / "pricing-cache.json"
    write_cache(path, url)
    before = path.read_bytes()

    def failed(*args, **kwargs):
        raise OSError("Synthetic cache replace failure")

    monkeypatch.setattr(colophon.os, "replace", failed)
    result = fetch(colophon, url, path)
    assert result.status == "cached" and result.fetched_at_ms == NOW - 1000
    assert result.messages and path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_nonfinite_typed_model_is_skipped_without_poisoning_cache(colophon, serve, tmp_path):
    # ModelsDevProvider.init skips invalid Double children while retaining peers.
    raw = (b'{"openai":{"models":{"synthetic-invalid":{"id":"synthetic-invalid",'
           b'"cost":{"input":3,"output":9,"cache_read":1e999}},'
           b'"synthetic-valid":{"id":"synthetic-valid","cost":{"input":3,"output":9}}}}}')
    url, _ = serve(lambda h: reply(h, body=raw))
    path = tmp_path / "pricing-cache.json"
    result = fetch(colophon, url, path)
    assert result.status == "fetched"
    for catalog in (result.catalog, fetch(colophon, url, path, offline=True).catalog):
        assert catalog is not None
        index = colophon.ModelsDevIndex.from_catalog(catalog)
        assert index.pricing("openai", "synthetic-invalid") is None
        assert index.pricing("openai", "synthetic-valid") is not None
    assert b"Infinity" not in path.read_bytes()


def test_complete_multichunk_body_with_distinct_body_socket_budget(colophon, serve, tmp_path, monkeypatch):
    raw = json.dumps(CATALOG | {"synthetic-ignored": "x" * 140000}).encode()

    def respond(h):
        h.send_response(200)
        h.send_header("Content-Length", str(len(raw)))
        h.end_headers()
        time.sleep(0.3)
        h.wfile.write(raw)

    monkeypatch.setattr(colophon, "CONNECT_TIMEOUT_S", 0.2)
    monkeypatch.setattr(colophon, "BODY_TIMEOUT_S", 1)
    url, _ = serve(respond)
    result = fetch(colophon, url, tmp_path / "pricing-cache.json")
    assert result.status == "fetched" and result.catalog == SUBSET


def test_incomplete_content_length_is_failure(colophon, serve, tmp_path):
    def incomplete(h):
        h.send_response(200)
        h.send_header("Content-Length", "10000")
        h.end_headers()
        h.wfile.write(json.dumps(CATALOG).encode())

    url, _ = serve(incomplete)
    result = fetch(colophon, url, tmp_path / "pricing-cache.json")
    assert result.status == "unavailable" and result.messages


def test_run_cleans_stale_temps_before_runtime_writes(colophon, home, codex_home):
    home.mkdir()
    stale = home / ".pricing-cache.json.synthetic.tmp"
    stale.write_text("Synthetic abandoned write")
    os.utime(stale, (time.time() - 4000,) * 2)
    args = colophon.build_arg_parser().parse_args(["--offline", "--no-open", "--codex-home", str(codex_home)])
    assert colophon.run(args) == 0
    assert not stale.exists() and (home / "price-history.json").exists()


def test_cleanup_failure_preserves_runtime_recovery(colophon, home, monkeypatch):
    home.mkdir()
    stale = home / ".pricing-cache.json.synthetic.tmp"
    stale.write_text("Synthetic abandoned write")
    os.utime(stale, (time.time() - 4000,) * 2)
    original = type(stale).unlink

    def failed(path, *args, **kwargs):
        if path == stale:
            raise OSError("Synthetic stale temp removal failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(type(stale), "unlink", failed)
    assert colophon.ensure_runtime_home(home) == home
    assert stale.exists()


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_watchdog_firing_during_cancel_is_not_forgotten(colophon, serve, tmp_path, monkeypatch, phase):
    timers = []

    class SyntheticTimer:
        def __init__(self, timeout, callback):
            self.callback = callback
            self.index = len(timers)
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            if self.index == (0 if phase == "headers" else 1):
                self.callback()

        def join(self):
            pass

    monkeypatch.setattr(colophon.threading, "Timer", SyntheticTimer)
    url, _ = serve(reply)
    path = tmp_path / "pricing-cache.json"
    result = fetch(colophon, url, path)
    assert result.status == "unavailable" and not path.exists()
    assert any("timeout" in m for m in result.messages)
