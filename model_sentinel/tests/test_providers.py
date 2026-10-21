import io
import json
import traceback
from urllib.error import HTTPError, URLError
from urllib.parse import quote

import pytest

from model_sentinel import providers
from model_sentinel.config import load_config
from model_sentinel.provider_profiles import resolve_profile
from tests.credential_fixtures import (
    synthetic_protocol_response, synthetic_provider_server, write_credential_config,
)


SECRET = 'SYNTHETIC_NOT_A_REAL_SECRET_"\\echo'


@pytest.mark.parametrize("failure", ["malformed_status", "truncated_body"])
def test_provider_protocol_error_suppresses_actual_upstream_echo(tmp_path, monkeypatch, failure):
    home = write_credential_config(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    response = synthetic_protocol_response(failure, SECRET)
    with synthetic_provider_server(home, raw_response=response) as authorizations:
        provider = load_config(tmp_path).providers[0]
        with pytest.raises(providers.ProviderFetchError) as caught:
            providers.fetch_raw_models(provider, SECRET, resolve_profile(provider.kind))
    assert authorizations == [f"Bearer {SECRET}"]
    assert "network error" in str(caught.value)
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("encoding", [str, json.dumps, quote])
def test_provider_error_omits_escaped_credential_echoes(tmp_path, monkeypatch, encoding):
    home = write_credential_config(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    provider = load_config(tmp_path).providers[0]
    class UnreadBody(io.BytesIO):
        def read(self, *args):
            pytest.fail("HTTP error body read for diagnostics")
    body = UnreadBody(encoding(SECRET).encode())
    error = HTTPError(provider.models_url, 401, encoding(SECRET), {}, body)
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(providers, "urlopen", fail)
    with pytest.raises(providers.ProviderFetchError) as caught:
        providers.fetch_raw_models(provider, SECRET, resolve_profile(provider.kind))
    assert "HTTP 401" in str(caught.value)
    assert provider.label in str(caught.value)
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in "".join(traceback.format_exception(caught.value))
    assert body.closed


@pytest.mark.parametrize("category", ["network", "json"])
def test_provider_error_suppresses_unsafe_exception_chain(tmp_path, monkeypatch, category):
    home = write_credential_config(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    provider = load_config(tmp_path).providers[0]
    def fail(*args, **kwargs):
        if category == "network":
            raise URLError(SECRET)
        return io.BytesIO(SECRET.encode())
    monkeypatch.setattr(providers, "urlopen", fail)
    if category == "json":
        def invalid_json(*args):
            raise json.JSONDecodeError(SECRET, SECRET, 0)
        monkeypatch.setattr(providers.json, "loads", invalid_json)
    with pytest.raises(providers.ProviderFetchError) as caught:
        providers.fetch_raw_models(provider, SECRET, resolve_profile(provider.kind))
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in "".join(traceback.format_exception(caught.value))


# ---------------------------------------------------------------------------
# Endpoint-list capture transport. Every provider, model ID, host and price is
# invented; requests go to injected fakes or a loopback server only.
# ---------------------------------------------------------------------------

import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request

from model_sentinel import __version__, endpoints
from model_sentinel.config import ProviderConfig
from model_sentinel.endpoints import (
    ENDPOINT_FETCH_BUDGET_SECONDS,
    ENDPOINT_FETCH_TIMEOUT_SECONDS,
    ENDPOINT_FETCH_WORKERS,
    ENDPOINT_RETRY_DELAY_SECONDS,
    build_endpoint_mappings,
    endpoint_list_path,
    endpoint_origin,
)
from model_sentinel.models import EndpointFetchResult, EndpointMapping
from model_sentinel.normalize import normalize_models
from model_sentinel.provider_profiles import OPENROUTER_PROFILE

FAKE_PROVIDER = ProviderConfig(
    provider_id="fake_router",
    label="Fake Router",
    kind="openrouter",
    base_url="https://fake-router.invalid/api/v1",
    models_path="/models",
    credential_env_var="FAKE_ROUTER_NOT_A_REAL_KEY",
    price_multiplier=1,
    price_divisor=1,
    enabled=True,
)
FAKE_PREFIX = "/api/v1/models/"
FIXED_NOW = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
FAKE_ENDPOINT = {"name": "Fake Host A | fake-org/test-model-a", "pricing": {"prompt": "0.000001"}}


def _path(model_id: str) -> str:
    return f"{FAKE_PREFIX}{model_id}/endpoints"


def _listed(model_id: str, link: object = None) -> dict:
    return {"id": model_id, "links": {"details": _path(model_id) if link is None else link}}


def _alias(model_id: str, target: object) -> dict:
    return {"id": model_id, "alias_target": {"slug": target}}


def _catalog(*raw_models: dict) -> dict:
    models = normalize_models(FAKE_PROVIDER, list(raw_models), OPENROUTER_PROFILE)
    return {model.provider_model_id: model for model in models}


def _json_response(payload: object) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _list_body(model_id: str | None, *entries: object) -> dict:
    data: dict = {"endpoints": list(entries)}
    if model_id is not None:
        data["id"] = model_id
    return {"data": data}


def _http_error(request: Request, code: int) -> HTTPError:
    return HTTPError(request.full_url, code, "synthetic upstream reason", {}, io.BytesIO(b""))


class FakeClock:
    """Thread-safe monotonic clock that only moves when a test moves it."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start
        self._lock = threading.Lock()
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)


class Recorder:
    """Record each request with its timeout and answer from a per-path script."""

    def __init__(self, script=None) -> None:
        self.script = script or {}
        self.calls: list[tuple[str, float]] = []
        self.requests: list[Request] = []
        self._lock = threading.Lock()

    def __call__(self, request: Request, timeout: float):
        path = urlsplit(request.full_url).path
        with self._lock:
            self.calls.append((path, timeout))
            self.requests.append(request)
            attempt = sum(1 for called, _ in self.calls if called == path)
        steps = self.script.get(path, [lambda req: _json_response(_list_body(None, dict(FAKE_ENDPOINT)))])
        step = steps[min(attempt, len(steps)) - 1]
        result = step(request)
        if isinstance(result, BaseException):
            raise result
        return result


def _fetch(catalog: dict, respond, clock: FakeClock | None = None, *, sleep=None) -> EndpointFetchResult:
    clock = clock or FakeClock()
    return providers.fetch_endpoint_lists(
        FAKE_PROVIDER,
        catalog,
        clock=clock,
        sleep=sleep or clock.sleep,
        open_response=respond,
        now=lambda: FIXED_NOW,
    )


def _by_path(result: EndpointFetchResult) -> dict:
    return {item.list_path: item for item in result.paths}


def _by_model(mappings) -> dict[str, EndpointMapping]:
    return {item.provider_model_id: item for item in mappings}


def test_endpoint_mapping_outcomes() -> None:
    catalog = _catalog(
        _listed("fake-org/test-model-a"),
        _listed("fake-org/test-model-a-shared", _path("fake-org/test-model-a")),
        _listed("fake-org/test-model-b"),
        _alias("fake-org/alias-one", "fake-org/test-model-a"),
        _alias("fake-org/alias-two", "fake-org/alias-one"),
        {
            "id": "fake-org/alias-with-link",
            "alias_target": {"slug": "fake-org/test-model-b"},
            "links": {"details": _path("fake-org/alias-with-link")},
        },
        _alias("fake-org/alias-missing", "fake-org/not-in-catalog"),
        _alias("fake-org/alias-lookalike", "fake-org/test-model"),
        _alias("fake-org/cycle-x", "fake-org/cycle-y"),
        _alias("fake-org/cycle-y", "fake-org/cycle-x"),
        _alias("fake-org/self-alias", "fake-org/self-alias"),
        _alias("fake-org/alias-to-unlinked", "fake-org/no-link"),
        _alias("fake-org/alias-to-invalid", "fake-org/bad-path"),
        {"id": "fake-org/no-link"},
        {"id": "fake-org/null-links", "links": None, "alias_target": None},
        {"id": "fake-org/empty-links", "links": {}},
        {"id": "fake-org/null-details", "links": {"details": None}},
        {"id": "fake-org/links-string", "links": _path("fake-org/links-string")},
        {"id": "fake-org/details-number", "links": {"details": 42}},
        {"id": "fake-org/details-empty", "links": {"details": ""}},
        _listed("fake-org/bad-path", "/api/v1/other/fake-org/bad-path/endpoints"),
        {"id": "fake-org/alias-string", "alias_target": "fake-org/test-model-a"},
        _alias("fake-org/alias-empty-slug", ""),
        _alias("fake-org/alias-number-slug", 7),
        {"id": "fake-org/alias-no-slug", "alias_target": {}},
    )
    path_a = _path("fake-org/test-model-a")
    path_b = _path("fake-org/test-model-b")
    expected = {
        "fake-org/test-model-a": ("listed", path_a, None, None, None),
        "fake-org/test-model-a-shared": ("listed", path_a, None, None, None),
        "fake-org/test-model-b": ("listed", path_b, None, None, None),
        "fake-org/alias-one": ("alias", path_a, "fake-org/test-model-a", "fake-org/test-model-a", None),
        "fake-org/alias-two": ("alias", path_a, "fake-org/alias-one", "fake-org/test-model-a", None),
        "fake-org/alias-with-link": ("alias", path_b, "fake-org/test-model-b", "fake-org/test-model-b", None),
        "fake-org/alias-missing": ("alias", None, "fake-org/not-in-catalog", None, "alias_target_missing"),
        "fake-org/alias-lookalike": ("alias", None, "fake-org/test-model", None, "alias_target_missing"),
        "fake-org/cycle-x": ("alias", None, "fake-org/cycle-y", None, "alias_cycle"),
        "fake-org/cycle-y": ("alias", None, "fake-org/cycle-x", None, "alias_cycle"),
        "fake-org/self-alias": ("alias", None, "fake-org/self-alias", None, "alias_cycle"),
        "fake-org/alias-to-unlinked": ("alias", None, "fake-org/no-link", None, "no_link"),
        "fake-org/alias-to-invalid": ("alias", None, "fake-org/bad-path", None, "invalid_link"),
        "fake-org/no-link": ("no_link", None, None, None, "no_link"),
        "fake-org/null-links": ("no_link", None, None, None, "no_link"),
        "fake-org/empty-links": ("no_link", None, None, None, "no_link"),
        "fake-org/null-details": ("no_link", None, None, None, "no_link"),
        "fake-org/links-string": ("invalid_link", None, None, None, "invalid_link"),
        "fake-org/details-number": ("invalid_link", None, None, None, "invalid_link"),
        "fake-org/details-empty": ("invalid_link", None, None, None, "invalid_link"),
        "fake-org/bad-path": ("invalid_link", None, None, None, "invalid_link"),
        "fake-org/alias-string": ("invalid_link", None, None, None, "invalid_link"),
        "fake-org/alias-empty-slug": ("invalid_link", None, None, None, "invalid_link"),
        "fake-org/alias-number-slug": ("invalid_link", None, None, None, "invalid_link"),
        "fake-org/alias-no-slug": ("invalid_link", None, None, None, "invalid_link"),
    }

    mappings = build_endpoint_mappings(catalog, FAKE_PREFIX)

    assert [item.provider_model_id for item in mappings] == sorted(expected)
    assert {
        item.provider_model_id: (
            item.outcome, item.list_path, item.alias_target_model_id,
            item.resolved_target_model_id, item.error_code,
        )
        for item in mappings
    } == expected
    assert {item.provider_model_id for item in mappings if item.is_failure} == {
        model_id for model_id, row in expected.items() if row[4] is not None
    }

    recorder = Recorder()
    result = _fetch(catalog, recorder)

    assert result.mappings == mappings
    # Shared and alias-reached paths are fetched once; alias links add no request.
    assert sorted(path for path, _ in recorder.calls) == [path_a, path_b]
    assert [item.list_path for item in result.paths] == [path_a, path_b]
    assert (result.paths_requested, result.paths_attempted, result.paths_failed) == (2, 2, 0)
    assert result.mapping_failures == sum(1 for row in expected.values() if row[4] is not None)
    assert result.provider_id == "fake_router"
    assert result.started_at == result.completed_at == FIXED_NOW.isoformat()


def test_endpoint_mapping_outcomes_empty_catalog_plans_nothing() -> None:
    recorder = Recorder()
    result = _fetch({}, recorder)
    assert recorder.calls == []
    assert (result.mappings, result.paths, result.bodies) == ((), (), {})
    assert (result.paths_requested, result.paths_attempted, result.paths_failed, result.mapping_failures) == (0, 0, 0, 0)
    assert endpoints.aggregate_capture_status(
        paths_requested=result.paths_requested,
        paths_failed=result.paths_failed,
        mapping_failures=result.mapping_failures,
    ) == "complete"


@pytest.mark.parametrize(
    "link",
    [
        "/api/v1/models/fake-org/test-model-a/endpoints",
        "/api/v1/models/test-model-a/endpoints",
        "/api/v1/models/fake-org/test-model-a:free/endpoints",
        "/api/v1/models/fake-org/test%20model/endpoints",
        "/api/v1/models/fake-org/test-model.v2/endpoints",
    ],
)
def test_endpoint_path_validation_accepts(link: str) -> None:
    assert endpoint_list_path(link, FAKE_PREFIX) == link


@pytest.mark.parametrize(
    "link",
    [
        None,
        42,
        "",
        "https://fake-router.invalid/api/v1/models/fake-org/a/endpoints",
        "//fake-router.invalid/api/v1/models/fake-org/a/endpoints",
        "api/v1/models/fake-org/a/endpoints",
        "/api/v1/modelsx/fake-org/a/endpoints",
        "/api/v2/models/fake-org/a/endpoints",
        "/api/v1/models/endpoints",
        "/api/v1/models//endpoints",
        "/api/v1/models/fake-org/a",
        "/api/v1/models/fake-org/a/endpoints/",
        "/api/v1/models/fake-org/a/endpointsx",
        "/api/v1/models/fake-org//a/endpoints",
        "/api/v1/models/fake-org/./a/endpoints",
        "/api/v1/models/fake-org/../a/endpoints",
        "/api/v1/models/../../admin/endpoints",
        "/api/v1/models/fake-org\\a/endpoints",
        "/api/v1/models/fake-org/a/endpoints?x=1",
        "/api/v1/models/fake-org/a/endpoints#frag",
        "/api/v1/models/fake-org/a\n/endpoints",
        "/api/v1/models/fake-org/a\x7f/endpoints",
        "/api/v1/models/fake-org/a b/endpoints",
        "/api/v1/models/fake-org/é/endpoints",
        "/api/v1/models/fake-org%2fa/endpoints",
        "/api/v1/models/fake-org%2Fa/endpoints",
        "/api/v1/models/%2e%2e/fake-org/endpoints",
        "/api/v1/models/fake-org/%2E/endpoints",
        "/api/v1/models/fake-org%5ca/endpoints",
        "/api/v1/models/fake-org/a%3fx/endpoints",
        "/api/v1/models/fake-org/a%23x/endpoints",
        "/api/v1/models/fake-org/a%0a/endpoints",
        "/api/v1/models/fake-org/a%252e/endpoints",
        "/api/v1/models/fake-org/a%zz/endpoints",
        "/api/v1/models/fake-org/a%2/endpoints",
    ],
)
def test_endpoint_path_validation_rejects(link: object) -> None:
    assert endpoint_list_path(link, FAKE_PREFIX) is None


@pytest.mark.parametrize(
    ("base_url", "models_path", "origin", "prefix"),
    [
        ("https://fake-router.invalid/api/v1", "/models", "https://fake-router.invalid", "/api/v1/models/"),
        ("https://fake-router.invalid/api/v1/", "/models/", "https://fake-router.invalid", "/api/v1/models/"),
        ("https://fake-router.invalid", "/api/v1/models", "https://fake-router.invalid", "/api/v1/models/"),
        ("https://fake-router.invalid:8443", "models", "https://fake-router.invalid:8443", "/models/"),
    ],
)
def test_endpoint_path_validation_configured_origin(base_url, models_path, origin, prefix) -> None:
    provider = ProviderConfig(**{**FAKE_PROVIDER.__dict__, "base_url": base_url, "models_path": models_path})
    resolved = endpoint_origin(provider.models_url)
    assert (resolved.origin, resolved.path_prefix) == (origin, prefix)
    assert resolved.url(f"{prefix}fake-org/a/endpoints") == f"{origin}{prefix}fake-org/a/endpoints"


@pytest.mark.parametrize(
    "models_url",
    [
        "http://fake-router.invalid/api/v1/models",
        "ftp://fake-router.invalid/api/v1/models",
        "https:///api/v1/models",
        "https://synthetic-user:synthetic-pw@fake-router.invalid/api/v1/models",
        "https://synthetic-user@fake-router.invalid/api/v1/models",
        "https://fake-router.invalid/api/v1/models?x=1",
        "https://fake-router.invalid/api/v1/models#frag",
        "https://fake-router.invalid:notaport/api/v1/models",
        "https://fake-router.invalid/api/v1/catalog",
        "https://fake-router.invalid/api/v1/modelsx",
    ],
)
def test_endpoint_path_validation_rejects_configured_origin(models_url: str) -> None:
    with pytest.raises(ValueError) as caught:
        endpoint_origin(models_url)
    assert models_url not in str(caught.value)
    assert "synthetic-user" not in str(caught.value) and "synthetic-pw" not in str(caught.value)


def test_endpoint_path_validation_invalid_origin_sends_nothing() -> None:
    provider = ProviderConfig(**{**FAKE_PROVIDER.__dict__, "base_url": "http://fake-router.invalid/api/v1"})
    recorder = Recorder()
    with pytest.raises(ValueError):
        providers.fetch_endpoint_lists(
            provider, _catalog(_listed("fake-org/test-model-a")), open_response=recorder,
        )
    assert recorder.calls == []


@contextmanager
def _loopback(handler_body):
    """Serve `handler_body(handler)` on 127.0.0.1 and record request paths and headers."""
    seen: list[tuple[str, dict[str, str]]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, dict(self.headers.items())))
            handler_body(self)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server.server_port, seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _send_json(handler, payload: object, status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _via_loopback(port: int):
    """Send the real endpoint request through the real endpoint opener to loopback."""
    opener = providers.endpoint_opener()

    def open_response(request: Request, timeout: float):
        local = Request(
            f"http://127.0.0.1:{port}{urlsplit(request.full_url).path}",
            headers=dict(request.header_items()),
            method=request.get_method(),
        )
        return opener.open(local, timeout=timeout)

    return open_response


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("target", ["same_origin", "cross_origin"])
def test_endpoint_redirect_rejection(status: int, target: str) -> None:
    redirect_to = _path("fake-org/test-model-b")
    if target == "cross_origin":
        redirect_to = "https://elsewhere.invalid" + redirect_to

    def respond(handler):
        if handler.path == _path("fake-org/test-model-a"):
            handler.send_response(status)
            handler.send_header("Location", redirect_to)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        _send_json(handler, _list_body("fake-org/test-model-b", dict(FAKE_ENDPOINT)))

    with _loopback(respond) as (port, seen):
        result = _fetch(_catalog(_listed("fake-org/test-model-a")), _via_loopback(port))

    assert [path for path, _ in seen] == [_path("fake-org/test-model-a")]
    (item,) = result.paths
    assert (item.outcome, item.error_code, item.http_status) == ("error", "redirect", status)
    assert item.endpoints == ()
    assert result.bodies == {}
    assert (result.paths_attempted, result.paths_failed) == (1, 1)


def test_endpoint_redirect_rejection_from_injected_error() -> None:
    recorder = Recorder({_path("fake-org/test-model-a"): [lambda req: _http_error(req, 302)]})
    (item,) = _fetch(_catalog(_listed("fake-org/test-model-a")), recorder).paths
    assert (item.error_code, item.http_status) == ("redirect", 302)
    assert len(recorder.calls) == 1


def test_endpoint_anonymous_headers(monkeypatch) -> None:
    monkeypatch.setenv(FAKE_PROVIDER.credential_env_var, SECRET)
    recorder = Recorder()
    _fetch(_catalog(_listed("fake-org/test-model-a")), recorder)

    (request,) = recorder.requests
    assert request.full_url == "https://fake-router.invalid" + _path("fake-org/test-model-a")
    assert request.get_method() == "GET"
    assert request.data is None
    assert dict(request.header_items()) == {
        "Accept": "application/json",
        "User-agent": f"model_sentinel/{__version__}",
    }

    with _loopback(lambda handler: _send_json(handler, _list_body("fake-org/test-model-a"))) as (port, seen):
        (item,) = _fetch(_catalog(_listed("fake-org/test-model-a")), _via_loopback(port)).paths
    assert item.outcome == "empty"
    ((_, wire_headers),) = seen
    lowered = {name.lower(): value for name, value in wire_headers.items()}
    assert lowered["user-agent"] == f"model_sentinel/{__version__}"
    assert lowered["accept"] == "application/json"
    assert "authorization" not in lowered and "cookie" not in lowered
    assert SECRET not in json.dumps(wire_headers)


def test_endpoint_anonymous_headers_default_opener_policy() -> None:
    opener = providers.endpoint_opener()
    https = [handler for handler in opener.handlers if isinstance(handler, HTTPSHandler)]
    assert len(https) == 1
    context = https[0]._context
    assert context.verify_mode == providers.ssl.CERT_REQUIRED and context.check_hostname
    assert not any(isinstance(handler, HTTPCookieProcessor) for handler in opener.handlers)
    redirects = [handler for handler in opener.handlers if isinstance(handler, providers.HTTPRedirectHandler)]
    assert [type(handler) for handler in redirects] == [providers._RejectRedirects]


@pytest.mark.parametrize("status", [401, 403])
def test_endpoint_anonymous_headers_auth_failure_is_visible_without_retry(status: int) -> None:
    recorder = Recorder({_path("fake-org/test-model-a"): [lambda req: _http_error(req, status)]})
    clock = FakeClock()
    (item,) = _fetch(_catalog(_listed("fake-org/test-model-a")), recorder, clock).paths
    assert (item.outcome, item.error_code, item.http_status) == ("error", "http_status", status)
    assert len(recorder.requests) == 1 and clock.sleeps == []
    assert "Authorization" not in dict(recorder.requests[0].header_items())


def test_endpoint_retry_admission_retries_once_after_delay() -> None:
    path = _path("fake-org/test-model-a")
    ok = lambda req: _json_response(_list_body("fake-org/test-model-a", dict(FAKE_ENDPOINT)))
    recorder = Recorder({path: [lambda req: _http_error(req, 429), ok]})
    clock = FakeClock()
    result = _fetch(_catalog(_listed("fake-org/test-model-a")), recorder, clock)
    (item,) = result.paths
    assert item.outcome == "ok"
    assert clock.sleeps == [ENDPOINT_RETRY_DELAY_SECONDS]
    assert recorder.calls == [(path, ENDPOINT_FETCH_TIMEOUT_SECONDS)] * 2
    assert (result.paths_attempted, result.paths_failed) == (1, 0)


@pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
def test_endpoint_retry_admission_gives_up_after_one_retry(status: int) -> None:
    path = _path("fake-org/test-model-a")
    recorder = Recorder({path: [lambda req: _http_error(req, status)]})
    clock = FakeClock()
    result = _fetch(_catalog(_listed("fake-org/test-model-a")), recorder, clock)
    (item,) = result.paths
    assert (item.outcome, item.error_code, item.http_status) == ("error", "http_status", status)
    assert len(recorder.calls) == 2 and clock.sleeps == [ENDPOINT_RETRY_DELAY_SECONDS]
    assert (result.paths_attempted, result.paths_failed) == (1, 1)


@pytest.mark.parametrize(
    "failure",
    [
        lambda req: _http_error(req, 404),
        lambda req: _http_error(req, 400),
        lambda req: _http_error(req, 302),
        lambda req: URLError("synthetic"),
        lambda req: TimeoutError("synthetic"),
        lambda req: io.BytesIO(b"not json"),
        lambda req: _json_response({"data": []}),
    ],
)
def test_endpoint_retry_admission_never_retries_other_failures(failure) -> None:
    recorder = Recorder({_path("fake-org/test-model-a"): [failure]})
    clock = FakeClock()
    (item,) = _fetch(_catalog(_listed("fake-org/test-model-a")), recorder, clock).paths
    assert item.outcome == "error"
    assert len(recorder.calls) == 1 and clock.sleeps == []


def test_endpoint_retry_admission_bounds_retry_timeout_by_remaining_time() -> None:
    path = _path("fake-org/test-model-a")
    clock = FakeClock()

    def slow_failure(request):
        clock.advance(ENDPOINT_FETCH_BUDGET_SECONDS - 9.5)
        return _http_error(request, 503)

    ok = lambda req: _json_response(_list_body(None))
    recorder = Recorder({path: [slow_failure, ok]})
    (item,) = _fetch(_catalog(_listed("fake-org/test-model-a")), recorder, clock).paths
    assert item.outcome == "empty"
    assert recorder.calls == [(path, ENDPOINT_FETCH_TIMEOUT_SECONDS), (path, 8.5)]


@pytest.mark.parametrize("remaining", [ENDPOINT_RETRY_DELAY_SECONDS, 0.5, 0.0])
def test_endpoint_retry_admission_skips_retry_that_cannot_start_before_deadline(remaining: float) -> None:
    path = _path("fake-org/test-model-a")
    clock = FakeClock()

    def late_failure(request):
        clock.advance(ENDPOINT_FETCH_BUDGET_SECONDS - remaining)
        return _http_error(request, 503)

    recorder = Recorder({path: [late_failure]})
    result = _fetch(_catalog(_listed("fake-org/test-model-a")), recorder, clock)
    (item,) = result.paths
    assert (item.error_code, item.http_status) == ("http_status", 503)
    assert len(recorder.calls) == 1 and clock.sleeps == []
    assert (result.paths_attempted, result.paths_failed) == (1, 1)


def test_endpoint_retry_admission_rechecks_deadline_after_delay() -> None:
    path = _path("fake-org/test-model-a")
    clock = FakeClock()

    def oversleep(seconds: float) -> None:
        clock.sleeps.append(seconds)
        clock.advance(ENDPOINT_FETCH_BUDGET_SECONDS)

    recorder = Recorder({path: [lambda req: _http_error(req, 503)]})
    (item,) = _fetch(_catalog(_listed("fake-org/test-model-a")), recorder, clock, sleep=oversleep).paths
    assert (item.error_code, item.http_status) == ("http_status", 503)
    assert len(recorder.calls) == 1 and clock.sleeps == [ENDPOINT_RETRY_DELAY_SECONDS]


def test_endpoint_bounded_inflight_queue() -> None:
    model_ids = [f"fake-org/test-model-{index:02d}" for index in range(10)]
    catalog = _catalog(*(_listed(model_id) for model_id in model_ids))
    clock = FakeClock()
    lock = threading.Condition()
    started: list[str] = []
    finished: list[str] = []
    releases = {_path(model_id): threading.Event() for model_id in model_ids}
    in_flight = 0
    peak = 0

    def blocking(request: Request, timeout: float):
        nonlocal in_flight, peak
        path = urlsplit(request.full_url).path
        with lock:
            started.append(path)
            in_flight += 1
            peak = max(peak, in_flight)
            lock.notify_all()
        assert releases[path].wait(timeout=10), "test never released a started request"
        with lock:
            in_flight -= 1
            finished.append(path)
        return _json_response(_list_body(None, dict(FAKE_ENDPOINT)))

    outcome: dict = {}
    runner = threading.Thread(
        target=lambda: outcome.setdefault("result", _fetch(catalog, blocking, clock)), daemon=True
    )
    runner.start()

    def wait_started(count: int) -> None:
        with lock:
            assert lock.wait_for(lambda: len(started) >= count, timeout=10)

    wait_started(ENDPOINT_FETCH_WORKERS)
    with lock:
        first_wave = list(started)
    assert len(first_wave) == ENDPOINT_FETCH_WORKERS
    releases[first_wave[0]].set()
    wait_started(ENDPOINT_FETCH_WORKERS + 1)
    clock.advance(ENDPOINT_FETCH_BUDGET_SECONDS)
    for event in releases.values():
        event.set()
    runner.join(timeout=10)
    assert not runner.is_alive()

    result = outcome["result"]
    assert peak == ENDPOINT_FETCH_WORKERS
    assert len(started) == ENDPOINT_FETCH_WORKERS + 1
    assert sorted(finished) == sorted(started)
    by_path = _by_path(result)
    assert {path for path, item in by_path.items() if item.outcome == "ok"} == set(started)
    unsent = {path for path, item in by_path.items() if item.outcome == "error"}
    assert unsent == set(releases) - set(started)
    assert {by_path[path].error_code for path in unsent} == {"budget_exceeded"}
    assert all(by_path[path].http_status is None for path in unsent)
    assert (result.paths_requested, result.paths_attempted, result.paths_failed) == (10, 5, 5)
    assert set(result.bodies) == set(started)


def test_endpoint_bounded_inflight_queue_propagates_unexpected_worker_error() -> None:
    catalog = _catalog(*(_listed(f"fake-org/test-model-{index}") for index in range(6)))

    def broken(request: Request, timeout: float):
        raise RuntimeError("synthetic programming error")

    with pytest.raises(RuntimeError, match="synthetic programming error"):
        _fetch(catalog, broken)


@pytest.mark.parametrize(
    ("respond", "outcome", "list_model_id", "count"),
    [
        (lambda req: _json_response(_list_body("fake-org/test-model-a", dict(FAKE_ENDPOINT), {})), "ok", "fake-org/test-model-a", 2),
        (lambda req: _json_response(_list_body("fake-org/test-model-a")), "empty", "fake-org/test-model-a", 0),
        (lambda req: _json_response(_list_body(None, dict(FAKE_ENDPOINT))), "ok", None, 1),
        (lambda req: _json_response({"data": {"id": None, "endpoints": []}}), "empty", None, 0),
    ],
)
def test_endpoint_response_validation_success(respond, outcome, list_model_id, count) -> None:
    path = _path("fake-org/test-model-a")
    result = _fetch(_catalog(_listed("fake-org/test-model-a")), Recorder({path: [respond]}))
    (item,) = result.paths
    assert (item.outcome, item.list_model_id, item.endpoint_count) == (outcome, list_model_id, count)
    assert item.display_id == (list_model_id or path)
    assert (item.error_code, item.error_message, item.http_status) == (None, None, None)
    assert all(isinstance(entry, dict) for entry in item.endpoints)
    assert result.bodies == {path: json.loads(respond(None).read())}


@pytest.mark.parametrize(
    ("respond", "code", "status"),
    [
        (lambda req: io.BytesIO(SECRET.encode()), "invalid_json", None),
        (lambda req: io.BytesIO(b"\xff\xfe\x00"), "invalid_json", None),
        (lambda req: _json_response([{"endpoints": []}]), "invalid_envelope", None),
        (lambda req: _json_response({"endpoints": []}), "invalid_envelope", None),
        (lambda req: _json_response({"data": []}), "invalid_envelope", None),
        (lambda req: _json_response({"data": {"id": "fake-org/test-model-a"}}), "invalid_envelope", None),
        (lambda req: _json_response({"data": {"endpoints": {"a": {}}}}), "invalid_envelope", None),
        (lambda req: _json_response({"data": {"id": 7, "endpoints": []}}), "invalid_envelope", None),
        (lambda req: _json_response(_list_body(None, {}, SECRET)), "invalid_endpoint", None),
        (lambda req: _json_response(_list_body(None, None)), "invalid_endpoint", None),
        (lambda req: _http_error(req, 404), "http_status", 404),
        (lambda req: URLError(SECRET), "network", None),
        (lambda req: OSError(SECRET), "network", None),
        (lambda req: providers.HTTPException(SECRET), "network", None),
        (lambda req: TimeoutError(SECRET), "timeout", None),
        (lambda req: URLError(TimeoutError(SECRET)), "timeout", None),
    ],
)
def test_endpoint_response_validation_failure(respond, code, status) -> None:
    path = _path("fake-org/test-model-a")
    result = _fetch(_catalog(_listed("fake-org/test-model-a")), Recorder({path: [respond]}))
    (item,) = result.paths
    assert (item.outcome, item.error_code, item.http_status) == ("error", code, status)
    assert item.endpoints == () and item.list_model_id is None
    assert item.error_message and len(item.error_message) <= endpoints.ENDPOINT_ERROR_MESSAGE_LIMIT
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in item.error_message
    assert "synthetic upstream reason" not in item.error_message
    assert result.bodies == {}
    assert (result.paths_failed, result.paths_attempted) == (1, 1)


def test_endpoint_response_validation_reports_entry_index_and_closes_error_bodies() -> None:
    path = _path("fake-org/test-model-a")
    path_b = _path("fake-org/test-model-b")

    class UnreadBody(io.BytesIO):
        def read(self, *args):
            pytest.fail("HTTP error body read for diagnostics")

    body = UnreadBody(SECRET.encode())
    recorder = Recorder({
        path: [lambda req: _json_response(_list_body(None, {}, {}, "not an object"))],
        path_b: [lambda req: HTTPError(req.full_url, 410, SECRET, {}, body)],
    })
    result = _fetch(_catalog(_listed("fake-org/test-model-a"), _listed("fake-org/test-model-b")), recorder)
    by_path = _by_path(result)
    assert "index 2" in by_path[path].error_message
    assert by_path[path_b].error_message == "HTTP 410"
    assert body.closed


def test_endpoint_response_validation_message_sanitizer() -> None:
    sanitize = endpoints.sanitize_endpoint_error_message
    assert sanitize("HTTP\n503\x00 \t later") == "HTTP 503 later"
    bounded = sanitize("x" * 1000)
    assert len(bounded) == endpoints.ENDPOINT_ERROR_MESSAGE_LIMIT
    assert bounded.endswith("...")


@contextmanager
def _catalog_server():
    def respond(handler):
        if handler.path == "/api/v1/models":
            handler.send_response(302)
            handler.send_header("Location", "/api/v1/models-moved")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        _send_json(handler, {"data": [{"id": "fake-org/test-model-a"}]})

    with _loopback(respond) as (port, seen):
        yield ProviderConfig(**{**FAKE_PROVIDER.__dict__, "base_url": f"http://127.0.0.1:{port}/api/v1"}), seen


def test_catalog_transport_compatibility_follows_redirects_with_bearer() -> None:
    with _catalog_server() as (provider, seen):
        models = providers.fetch_raw_models(provider, "fake-bearer-not-a-secret", OPENROUTER_PROFILE)
    assert models == [{"id": "fake-org/test-model-a"}]
    assert [path for path, _ in seen] == ["/api/v1/models", "/api/v1/models-moved"]
    for _, headers in seen:
        lowered = {name.lower(): value for name, value in headers.items()}
        assert lowered["authorization"] == "Bearer fake-bearer-not-a-secret"
        assert lowered["accept"] == "application/json"
        assert lowered["user-agent"] == f"model_sentinel/{__version__}"


@pytest.mark.parametrize(
    ("failure", "message", "status"),
    [
        (lambda: _http_error(Request("https://fake-router.invalid"), 503), "Fake Router request failed with HTTP 503", 503),
        (lambda: _http_error(Request("https://fake-router.invalid"), 302), "Fake Router request failed with HTTP 302", 302),
        (lambda: URLError(SECRET), "Fake Router request failed: network error", None),
        (lambda: TimeoutError(SECRET), "Fake Router request failed: network error", None),
        (lambda: URLError(TimeoutError(SECRET)), "Fake Router request failed: network error", None),
        (lambda: providers.HTTPException(SECRET), "Fake Router request failed: network error", None),
        (lambda: io.BytesIO(b"\xff"), "Fake Router returned invalid JSON", None),
        (lambda: io.BytesIO(b"not json"), "Fake Router returned invalid JSON", None),
        (lambda: _json_response({"models": []}), "Fake Router response did not include a model list", None),
        (lambda: _json_response("text"), "Fake Router returned an unsupported payload shape", None),
    ],
)
def test_catalog_transport_compatibility_messages(monkeypatch, failure, message, status) -> None:
    def fake_urlopen(request, *, timeout, context):
        assert timeout == 30.0
        assert context.verify_mode == providers.ssl.CERT_REQUIRED
        result = failure()
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    with pytest.raises(providers.ProviderFetchError) as caught:
        providers.fetch_raw_models(FAKE_PROVIDER, SECRET, OPENROUTER_PROFILE)
    assert str(caught.value) == message
    assert caught.value.http_status == status
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in "".join(traceback.format_exception(caught.value))


def test_catalog_transport_compatibility_error_status_defaults_to_none() -> None:
    assert providers.ProviderFetchError("synthetic").http_status is None
    assert providers.ProviderFetchError("synthetic", http_status=418).http_status == 418


def test_endpoint_anonymous_headers_default_transport_uses_endpoint_opener(monkeypatch) -> None:
    opened: list[tuple[str, float]] = []

    class FakeOpener:
        def open(self, request: Request, *, timeout: float):
            opened.append((request.full_url, timeout))
            return _json_response(_list_body("fake-org/test-model-a"))

    monkeypatch.setattr(providers, "endpoint_opener", FakeOpener)
    clock = FakeClock()
    result = providers.fetch_endpoint_lists(
        FAKE_PROVIDER, _catalog(_listed("fake-org/test-model-a")), clock=clock, sleep=clock.sleep,
    )
    assert opened == [
        ("https://fake-router.invalid" + _path("fake-org/test-model-a"), ENDPOINT_FETCH_TIMEOUT_SECONDS)
    ]
    assert result.paths[0].outcome == "empty"
    assert result.started_at.endswith("+00:00")


def test_endpoint_mapping_outcomes_alias_chain_ignores_link_validity() -> None:
    assert endpoints.alias_declaration({"id": "fake-org/m"}) == (False, None)
    assert endpoints.alias_declaration({"alias_target": None}) == (False, None)
    assert endpoints.alias_declaration({"alias_target": {"slug": "fake-org/t"}}) == (True, "fake-org/t")
    assert endpoints.alias_declaration({"alias_target": {"slug": ""}}) == (True, None)
    assert endpoints.alias_declaration({"alias_target": "fake-org/t"}) == (True, None)
    targets = {
        "fake-org/a": "fake-org/b",
        "fake-org/b": "fake-org/c",
        # The terminal needs no usable link to end the chain.
        "fake-org/c": None,
        "fake-org/loop": "fake-org/loop",
        "fake-org/lost": "fake-org/nowhere",
    }
    assert endpoints.resolve_alias_chain("fake-org/a", targets) == ("fake-org/c", None)
    assert endpoints.resolve_alias_chain("fake-org/loop", targets) == (None, "alias_cycle")
    assert endpoints.resolve_alias_chain("fake-org/lost", targets) == (None, "alias_target_missing")
    with pytest.raises(ValueError):
        endpoints.resolve_alias_chain("fake-org/c", targets)
