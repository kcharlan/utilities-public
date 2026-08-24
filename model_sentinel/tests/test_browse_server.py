from __future__ import annotations

import errno
import hashlib
import http.client
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from model_sentinel.browse import api, queries, server as server_module
from model_sentinel.browse.aspects import build_aspect_catalog
from model_sentinel.browse.readonly import DatabaseBusyError, open_readonly
from model_sentinel.browse.server import find_free_port, make_server
from model_sentinel.provider_profiles import profiles_for, resolve_profile
from model_sentinel.reporting import (
    DEFAULT_REPORT_SHOW_FIELDS,
    DEFAULT_REPORT_SQUELCH_FIELDS,
    detail_policy_from_settings,
)
from tests.browse_fixtures import EXAMPLE_PROVIDER, OTHER_PROVIDER, build_fixture_db


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        report_detail="default",
        report_show_fields=DEFAULT_REPORT_SHOW_FIELDS,
        report_squelch_fields=DEFAULT_REPORT_SQUELCH_FIELDS,
        report_unclassified_limit=20,
    )


def _context(db):
    providers = (EXAMPLE_PROVIDER, OTHER_PROVIDER)
    db_providers = tuple(queries.db_providers(db.connection()))
    profiles = profiles_for(providers)
    for row in db_providers:
        profiles.setdefault(str(row["provider_id"]), resolve_profile(str(row["kind"])))
    settings = _settings()
    aspects = build_aspect_catalog(
        db,
        profiles=profiles,
        policy=detail_policy_from_settings(settings),
    )
    return api.ApiContext(db, providers, db_providers, profiles, settings, aspects)


@pytest.fixture
def browse_server(tmp_path: Path):
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()
    db = open_readonly(database_path)
    server = make_server(_context(db), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, db, database_path, before
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    db.close_all()


def _request(
    server,
    method: str,
    target: str,
    *,
    host: str | None = None,
    timeout: float = 5,
):
    port = server.server_address[1]
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    headers = {} if host is None else {"Host": host}
    connection.request(method, target, headers=headers)
    response = connection.getresponse()
    body = response.read()
    result = response.status, dict(response.getheaders()), body
    connection.close()
    return result


def _request_without_host(server, target: str):
    port = server.server_address[1]
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.putrequest("GET", target, skip_host=True)
    connection.endheaders()
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def _mock_port_binds(monkeypatch, busy_ports: set[int]) -> list[int]:
    attempts: list[int] = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def bind(self, address: tuple[str, int]) -> None:
            attempts.append(address[1])
            if address[1] in busy_ports:
                raise OSError(errno.EADDRINUSE, "synthetic address in use")

    monkeypatch.setattr(
        server_module.socket,
        "socket",
        lambda *args, **kwargs: FakeSocket(),
    )
    return attempts


def test_find_free_port_returns_requested_free_port(monkeypatch) -> None:
    attempts = _mock_port_binds(monkeypatch, set())

    assert find_free_port(32000) == 32000
    assert attempts == [32000]


def test_find_free_port_skips_held_port_and_supports_ephemeral(monkeypatch) -> None:
    attempts = _mock_port_binds(monkeypatch, {32000})

    assert find_free_port(32000, max_attempts=2) == 32001
    assert attempts == [32000, 32001]
    attempts.clear()
    assert find_free_port(0) == 0
    assert attempts == []


def test_find_free_port_reports_exhausted_inclusive_range(monkeypatch) -> None:
    attempts = _mock_port_binds(monkeypatch, {32000, 32001})

    with pytest.raises(RuntimeError, match=r"32000.+32001"):
        find_free_port(32000, max_attempts=2)
    assert attempts == [32000, 32001]


def test_bind_server_retries_only_address_in_use(monkeypatch) -> None:
    attempts: list[int] = []
    bound = SimpleNamespace(server_address=("127.0.0.1", 32001))

    def fake_make_server(ctx, *, host="127.0.0.1", port):
        attempts.append(port)
        if port == 32000:
            raise OSError(errno.EADDRINUSE, "synthetic address in use")
        return bound

    monkeypatch.setattr(server_module, "make_server", fake_make_server)

    server, resolved_port = server_module._bind_server(
        object(), port=32000, max_attempts=2
    )

    assert server is bound
    assert resolved_port == 32001
    assert attempts == [32000, 32001]


def test_bind_server_reports_exhausted_inclusive_range(monkeypatch) -> None:
    attempts: list[int] = []

    def fake_make_server(ctx, *, host="127.0.0.1", port):
        attempts.append(port)
        raise OSError(errno.EADDRINUSE, "synthetic address in use")

    monkeypatch.setattr(server_module, "make_server", fake_make_server)

    with pytest.raises(RuntimeError, match=r"32000.+32001"):
        server_module._bind_server(object(), port=32000, max_attempts=2)
    assert attempts == [32000, 32001]


def test_bind_server_propagates_non_address_in_use_error(monkeypatch) -> None:
    def fake_make_server(ctx, *, host="127.0.0.1", port):
        raise OSError(errno.EACCES, "synthetic permission denied")

    monkeypatch.setattr(server_module, "make_server", fake_make_server)

    with pytest.raises(OSError) as raised:
        server_module._bind_server(object(), port=32000)
    assert raised.value.errno == errno.EACCES


@pytest.mark.parametrize("start", (-1, 65536))
def test_find_free_port_rejects_invalid_port(start: int) -> None:
    with pytest.raises(ValueError):
        find_free_port(start)


def test_static_assets_are_served_with_safe_paths_and_mime_types(browse_server) -> None:
    server, _, _, _ = browse_server
    status, headers, body = _request(server, "GET", "/")
    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert b"app.js" in body

    status, headers, _ = _request(server, "GET", "/app.css")
    assert status == 200
    assert headers["Content-Type"] == "text/css; charset=utf-8"

    vendor_dir = Path(__file__).parents[1] / "model_sentinel/browse/assets/vendor"
    for asset in vendor_dir.iterdir():
        status, _, body = _request(server, "GET", f"/vendor/{asset.name}")
        assert status == 200, asset.name
        assert body == asset.read_bytes()

    for target in (
        "/vendor/../cli.py",
        "/vendor/%2e%2e/cli.py",
        "/vendor/%2E%2E%2Fcli.py",
        "/vendor/nested/file.js",
    ):
        assert _request(server, "GET", target)[0] == 404


def test_api_routes_and_errors(browse_server) -> None:
    server, _, _, _ = browse_server
    status, headers, body = _request(server, "GET", "/api/meta")
    payload = json.loads(body)
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert payload["pin_limit"] == 8
    assert payload["aspects"]

    status, _, body = _request(server, "GET", "/api/activity?from=bad")
    assert status == 400
    assert json.loads(body) == {"error": "from must be YYYY-MM-DD"}
    assert _request(server, "GET", "/api/change/999999")[0] == 404
    assert _request(server, "GET", "/api/nope")[0] == 404


def test_duplicate_query_values_are_rejected(browse_server) -> None:
    server, _, _, _ = browse_server
    status, _, body = _request(server, "GET", "/api/activity?page=1&page=2")
    assert status == 400
    assert json.loads(body) == {"error": "duplicate query parameter: page"}


@pytest.mark.parametrize(
    "method",
    ("POST", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"),
)
def test_unsupported_methods_return_405(browse_server, method: str) -> None:
    server, _, _, _ = browse_server
    status, headers, body = _request(server, method, "/api/meta")
    assert status == 405
    assert headers["Cache-Control"] == "no-store"
    if method == "HEAD":
        assert body == b""


@pytest.mark.parametrize(
    ("host", "expected_status", "expected_body"),
    (
        (None, 405, {"error": "method not allowed"}),
        ("evil.example", 403, {"error": "forbidden"}),
    ),
)
def test_arbitrary_unsupported_method_uses_json_security_contract(
    browse_server,
    host: str | None,
    expected_status: int,
    expected_body: dict[str, str],
) -> None:
    server, _, _, _ = browse_server
    status, headers, body = _request(server, "PROPFIND", "/api/meta", host=host)

    assert status == expected_status
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert not any(name.casefold().startswith("access-control-") for name in headers)
    assert body == json.dumps(
        expected_body, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def test_host_header_must_match_loopback_listener(browse_server) -> None:
    server, _, _, _ = browse_server
    port = server.server_address[1]
    assert _request(server, "GET", "/api/meta", host=f"localhost:{port}")[0] == 200
    assert _request(server, "GET", "/api/meta", host="evil.example")[0] == 403
    assert _request(server, "GET", "/api/meta", host="127.0.0.1:9999")[0] == 403
    assert _request_without_host(server, "/api/meta")[0] == 403


def test_every_response_disables_caching_and_cors(browse_server) -> None:
    server, _, _, _ = browse_server
    for target in ("/", "/api/meta", "/api/nope"):
        _, headers, _ = _request(server, "GET", target)
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert not any(name.casefold().startswith("access-control-") for name in headers)


def test_busy_and_unexpected_exceptions_have_safe_json_errors(
    browse_server, monkeypatch
) -> None:
    server, _, _, _ = browse_server

    def busy(*args, **kwargs):
        raise DatabaseBusyError("synthetic locked detail")

    monkeypatch.setattr(api, "meta", busy)
    status, _, body = _request(server, "GET", "/api/meta")
    assert status == 503
    assert json.loads(body) == {
        "error": "The database is busy — a scan may be writing. Try again in a moment."
    }

    def invalid_query(*args, **kwargs):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("SELECT * FROM synthetic_busy_table")
        finally:
            connection.close()

    monkeypatch.setattr(api, "meta", invalid_query)
    status, _, body = _request(server, "GET", "/api/meta")
    assert status == 500
    assert json.loads(body) == {"error": "internal error: OperationalError"}

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic private detail")

    monkeypatch.setattr(api, "meta", explode)
    status, _, body = _request(server, "GET", "/api/meta")
    assert status == 500
    assert json.loads(body) == {"error": "internal error: RuntimeError"}
    assert b"private detail" not in body


def test_locked_database_returns_retryable_503_from_every_query_path(
    browse_server,
) -> None:
    targets = (
        "/api/activity",
        "/api/series?models=example-provider/fake-org/test-model-a&aspects=example-provider:input_price",
        "/api/events?models=example-provider/fake-org/test-model-a",
    )
    server, _, database_path, _ = browse_server
    writer = sqlite3.connect(database_path, timeout=0)
    try:
        writer.execute("BEGIN EXCLUSIVE")

        with ThreadPoolExecutor(max_workers=len(targets)) as pool:
            responses = list(
                pool.map(
                    lambda target: _request(server, "GET", target, timeout=10),
                    targets,
                )
            )

        for target, (status, _, body) in zip(targets, responses, strict=True):
            assert status == 503, target
            assert json.loads(body) == {
                "error": "The database is busy — a scan may be writing. Try again in a moment."
            }, target
    finally:
        writer.rollback()
        writer.close()


def test_concurrent_requests_use_distinct_thread_connections_and_do_not_write_fixture(
    browse_server, monkeypatch
) -> None:
    server, db, database_path, before = browse_server
    connection_ids: dict[int, int] = {}
    lock = threading.Lock()
    real_connection = db.connection
    real_meta = api.meta
    handler_barrier = threading.Barrier(4)

    def tracked_connection():
        connection = real_connection()
        with lock:
            connection_ids[threading.get_ident()] = id(connection)
        return connection

    monkeypatch.setattr(db, "connection", tracked_connection)

    def synchronized_meta(ctx, params):
        handler_barrier.wait(timeout=5)
        return real_meta(ctx, params)

    monkeypatch.setattr(api, "meta", synchronized_meta)

    def fetch() -> int:
        return _request(server, "GET", "/api/meta")[0]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: fetch(), range(4))) == [200, 200, 200, 200]

    assert len(connection_ids) >= 4
    assert len(set(connection_ids.values())) >= 4
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before


def test_run_browse_closes_database_when_server_creation_fails(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    db = open_readonly(database_path)
    close_calls = 0
    real_close = db.close_all

    def tracked_close() -> None:
        nonlocal close_calls
        close_calls += 1
        real_close()

    captured_context = None

    def reject_server(ctx, *args, **kwargs):
        nonlocal captured_context
        captured_context = ctx
        raise OSError(errno.EACCES, "synthetic bind failure")

    monkeypatch.setattr(db, "close_all", tracked_close)
    monkeypatch.setattr(server_module, "make_server", reject_server)
    loaded = SimpleNamespace(
        providers=(EXAMPLE_PROVIDER, OTHER_PROVIDER),
        settings=_settings(),
    )

    with pytest.raises(OSError, match="synthetic bind failure"):
        server_module.run_browse(
            db=db,
            loaded=loaded,
            port=0,
            open_browser=False,
            initial_provider=None,
            display_invocation="renamed-sentinel",
        )

    assert close_calls == 1
    assert captured_context.display_invocation == "renamed-sentinel"
