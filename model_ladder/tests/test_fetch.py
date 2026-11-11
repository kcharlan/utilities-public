import email.message
import json
import subprocess
import urllib.error
from datetime import datetime

import pytest

from helpers import model

SECRET = "synthetic-secret-key-123"
CONFIG = {"op_item": "Synthetic Item", "op_vault": "", "op_field": "credential"}


class Response:
    def __init__(self, body, headers=None):
        self._body = json.dumps(body).encode()
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def page(models, has_more=False, version=5):
    return {"intelligence_index_version": version, "pagination": {"has_more": has_more}, "data": models}


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def http_error(code, headers=None):
    msg = email.message.Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    return urllib.error.HTTPError("https://example.invalid/x", code, "synthetic", msg, None)


@pytest.fixture
def op_file(tmp_path):
    path = tmp_path / "op"
    path.write_text("")
    return path


class Runner:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error:
            raise self.error
        return self.result


def completed(stdout, code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


def test_key_from_env_wins(ml, op_file):
    run = Runner()
    key = ml.get_api_key(CONFIG, env={"MODEL_LADDER_AA_KEY": SECRET}, op_paths=(str(op_file),), run=run)
    assert key == SECRET
    assert run.calls == []


def test_key_from_op(ml, op_file):
    run = Runner(completed(f" {SECRET}\n"))
    key = ml.get_api_key(CONFIG, env={}, op_paths=("/nonexistent/op", str(op_file)), run=run)
    assert key == SECRET
    argv, kwargs = run.calls[0]
    assert argv == [str(op_file), "--cache=false", "item", "get", "Synthetic Item",
                    "--fields", "label=credential", "--reveal"]
    assert kwargs["timeout"] == 20
    assert SECRET not in " ".join(argv)
    run = Runner(completed(SECRET))
    ml.get_api_key({**CONFIG, "op_vault": "Synthetic Vault"}, env={}, op_paths=(str(op_file),), run=run)
    assert run.calls[0][0][-2:] == ["--vault", "Synthetic Vault"]


def test_key_op_missing_binary(ml, tmp_path):
    with pytest.raises(ml.KeyUnavailable, match="1Password CLI not found"):
        ml.get_api_key(CONFIG, env={}, op_paths=(str(tmp_path / "none"),), run=Runner())


def test_key_op_timeout(ml, op_file):
    run = Runner(error=subprocess.TimeoutExpired([str(op_file), SECRET], 20))
    with pytest.raises(ml.KeyUnavailable, match="unlock 1Password") as info:
        ml.get_api_key(CONFIG, env={}, op_paths=(str(op_file),), run=run)
    assert SECRET not in str(info.value)


def test_key_op_nonzero(ml, op_file):
    run = Runner(completed(SECRET, code=1))
    with pytest.raises(ml.KeyUnavailable, match="unlock 1Password") as info:
        ml.get_api_key(CONFIG, env={}, op_paths=(str(op_file),), run=run)
    assert SECRET not in str(info.value)


def test_key_op_empty(ml, op_file):
    with pytest.raises(ml.KeyUnavailable):
        ml.get_api_key(CONFIG, env={}, op_paths=(str(op_file),), run=Runner(completed("  \n")))


def test_key_nothing_configured(ml):
    with pytest.raises(ml.KeyUnavailable) as info:
        ml.get_api_key({**CONFIG, "op_item": ""}, env={"MODEL_LADDER_AA_KEY": ""}, op_paths=(), run=Runner())
    assert "MODEL_LADDER_AA_KEY" in str(info.value) and "op_item" in str(info.value)


def test_fetch_follows_pagination(ml):
    a, b, c = model("A", 1), model("B", 2), model("C", 3)
    opener = Opener([Response(page([a], True)), Response(page([b], True)), Response(page([c]))])
    result = ml.fetch_all(SECRET, open_url=opener)
    assert [m["name"] for m in result["models"]] == ["A", "B", "C"]
    assert result["index_version"] == 5
    assert [r.full_url.rsplit("/", 1)[1] for r in opener.requests] == [
        "free?page=1", "free?page=2", "free?page=3"]
    assert all(r.get_header("X-api-key") == SECRET for r in opener.requests)
    assert set(opener.timeouts) == {30}


def test_fetch_reads_rate_limit_headers(ml):
    first = Response(page([], True), {"x-ratelimit-limit": "1", "x-ratelimit-remaining": "1", "x-ratelimit-reset": "1"})
    last = Response(page([]), {"x-ratelimit-limit": "100", "x-ratelimit-remaining": "96", "x-ratelimit-reset": "junk"})
    result = ml.fetch_all(SECRET, open_url=Opener([first, last]))
    assert result["rate_limit"] == {"limit": 100, "remaining": 96, "reset": None}


def test_fetch_stops_after_max_pages(ml):
    opener = Opener([Response(page([], True))])
    with pytest.raises(ml.FetchError, match="20"):
        ml.fetch_all(SECRET, open_url=opener)
    assert len(opener.requests) == 20


def test_fetch_429_reports_reset(ml):
    reset = 1_800_000_000
    opener = Opener([http_error(429, {"x-ratelimit-reset": str(reset)})])
    with pytest.raises(ml.FetchError) as info:
        ml.fetch_all(SECRET, open_url=opener)
    expected = datetime.fromtimestamp(reset).strftime("%Y-%m-%d %H:%M")
    assert expected in str(info.value) and "quota" in str(info.value)
    assert SECRET not in str(info.value)


def test_fetch_429_without_reset_header(ml):
    with pytest.raises(ml.FetchError, match="quota"):
        ml.fetch_all(SECRET, open_url=Opener([http_error(429)]))


@pytest.mark.parametrize("code", [401, 403])
def test_fetch_401(ml, code):
    with pytest.raises(ml.FetchError, match="rejected the API key") as info:
        ml.fetch_all(SECRET, open_url=Opener([http_error(code)]))
    assert SECRET not in str(info.value)


def test_fetch_network_error(ml):
    with pytest.raises(ml.FetchError, match="500"):
        ml.fetch_all(SECRET, open_url=Opener([http_error(500)]))
    with pytest.raises(ml.FetchError, match="no route") as info:
        ml.fetch_all(SECRET, open_url=Opener([urllib.error.URLError("no route")]))
    assert SECRET not in str(info.value)


def test_fetch_versions_must_agree(ml):
    opener = Opener([Response(page([], True, 5)), Response(page([], False, 6))])
    with pytest.raises(ml.FetchError, match="intelligence_index_version"):
        ml.fetch_all(SECRET, open_url=opener)


@pytest.mark.parametrize("field", ["data", "pagination.has_more", "intelligence_index_version"])
def test_envelope_missing_field(ml, field):
    body = page([])
    if field == "data":
        del body["data"]
    elif field == "intelligence_index_version":
        del body["intelligence_index_version"]
    else:
        body["pagination"] = {}
    with pytest.raises(ml.FetchError, match=field):
        ml.fetch_all(SECRET, open_url=Opener([Response(body)]))


def test_ignores_unused_fields(ml):
    base = model("Alpha Test 1", 10.0, 0.5)
    no_perf = {k: v for k, v in base.items() if k not in ("performance", "pricing")}
    null_perf = {**base, "performance": None}
    extra = {**base, "unknown_new_key": {"x": 1}}
    ml.validate_models([no_perf, null_perf, extra])
    ml.fetch_all(SECRET, open_url=Opener([Response(page([no_perf, null_perf, extra]))]))


@pytest.mark.parametrize("bad", ["12", True])
def test_rejects_non_numeric_index(ml, bad):
    item = model("Alpha Test 1", 1.0, slug="alpha-test-1")
    item["evaluations"]["artificial_analysis_intelligence_index"] = bad
    with pytest.raises(ml.FetchError, match="alpha-test-1.*artificial_analysis_intelligence_index"):
        ml.validate_models([item])


def test_null_cost_objects_accepted(ml):
    a = model("A", 1.0)
    a["artificial_analysis_intelligence_index_cost"] = None
    b = model("B", 1.0)
    b["artificial_analysis_intelligence_index_cost"]["cost_per_task"] = None
    c = model("C", 1.0)
    c["artificial_analysis_intelligence_index_cost"]["cost_per_task"] = {"total_cost": None}
    ml.validate_models([a, b, c])


def test_rejects_bad_identity_fields(ml):
    for mutate in (lambda m: m.update(name=""), lambda m: m.update(slug=None),
                   lambda m: m.update(model_creator={"name": 3})):
        item = model("Alpha Test 1", 1.0)
        mutate(item)
        with pytest.raises(ml.FetchError):
            ml.validate_models([item])
    with pytest.raises(ml.FetchError, match="model 1"):
        ml.validate_models(["junk"])
    bad_cost = model("B", 1.0, cost=0.5)
    bad_cost["artificial_analysis_intelligence_index_cost"]["cost_per_task"]["total_cost"] = "x"
    with pytest.raises(ml.FetchError, match="total_cost"):
        ml.validate_models([bad_cost])
