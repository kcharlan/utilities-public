import hashlib
import http.client
import json
import urllib.error

import pytest
from helpers import feed


def test_fetch_checks_checksum_and_returns_feed(dl):
    body = json.dumps(feed()).encode()

    class Response:
        headers = {"X-Content-SHA256": hashlib.sha256(body).hexdigest()}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return body

    def open_url(request, timeout):
        assert request.full_url == dl.FEED_URL
        assert request.get_header("Accept") == "application/json"
        assert request.get_header("User-agent") == f"decision-ladder/{dl.VERSION}"
        assert timeout == 30
        return Response()

    assert dl.fetch_feed(open_url)["feed"] == feed()
    Response.headers["X-Content-SHA256"] = "wrong"
    with pytest.raises(dl.FetchError, match="checksum"):
        dl.fetch_feed(open_url)


@pytest.mark.parametrize("error", [urllib.error.HTTPError("https://example.invalid", 500, "error", {}, None),
                                   urllib.error.URLError("synthetic"), http.client.IncompleteRead(b"x"),
                                   OSError("synthetic"), TimeoutError("synthetic")])
def test_network_failures_are_reported_as_fetch_errors(dl, error):
    def fail(*args, **kwargs):
        raise error
    with pytest.raises(dl.FetchError, match="Benchmark Heaven"):
        dl.fetch_feed(fail)


def test_network_error_is_one_line(dl):
    def fail(*args, **kwargs):
        raise urllib.error.URLError("synthetic\nsecond line")
    with pytest.raises(dl.FetchError) as exc:
        dl.fetch_feed(fail)
    assert "\n" not in str(exc.value)


@pytest.mark.parametrize("mutate", [
    lambda f: f.update(schema_version=3),
    lambda f: f.update(revision=""),
    lambda f: f.update(method={"label": ""}),
    lambda f: f["capability_policy"].update(cost_cap_usd_per_1000=0),
    lambda f: f["capability_policy"].update(median_latency_cap_s=float("inf")),
    lambda f: f["capability_policy"].update(factor=float("inf")),
    lambda f: f["method"].update(decision_limit_s=True),
    lambda f: f.update(systems=[]),
    lambda f: f.update(systems=[None]),
    lambda f: f["systems"][0].update(key=""),
    lambda f: f["systems"][0].update(name=""),
    lambda f: f["systems"][0].update(board=None),
    lambda f: f["systems"][0].update(ranked=1),
    lambda f: f["systems"][0].update(capability={}),
    lambda f: f["systems"][0].update(price=[]),
    lambda f: f["systems"][0].update(latency=[]),
    lambda f: f["systems"][0].update(axes=[]),
    lambda f: f["systems"][0].update(draw="invalid"),
    lambda f: f["systems"][0].update(composite_score=float("nan")),
    lambda f: f["systems"].append(dict(f["systems"][0])),
])
def test_invalid_feed_rejected(dl, mutate):
    data = feed()
    mutate(data)
    with pytest.raises(dl.FetchError):
        dl.validate_feed(data)


def test_missing_checksum_accepted_and_body_limit_enforced(dl, monkeypatch):
    class Response:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps(feed()).encode()[:size]
    assert dl.fetch_feed(lambda *a, **k: Response())["feed"] == feed()
    monkeypatch.setattr(dl, "MAX_BYTES", 10)
    with pytest.raises(dl.FetchError, match="too large"):
        dl.fetch_feed(lambda *a, **k: Response())


@pytest.mark.parametrize("block,field", [
    (None, "composite_score"), (None, "rank"), ("capability", "score"), ("capability", "rank"),
    ("axes", "intelligence"), ("axes", "calibration"), ("axes", "speed"), ("axes", "cost"),
    ("price", "usd_per_1000_decisions"), ("latency", "p50_s_measured"),
    ("latency", "p50_s_adjusted"), ("latency", "p95_s_adjusted"),
])
def test_each_numeric_field_rejects_nonfinite_and_names_system(dl, block, field):
    data = feed()
    row = data["systems"][0]
    target = row if block is None else row.setdefault(block, {})
    target[field] = float("nan")
    with pytest.raises(dl.FetchError, match="synthetic"):
        dl.validate_feed(data)


def test_nullable_numeric_fields_remain_unavailable(dl):
    data = feed()
    data["method"]["decision_limit_s"] = None
    data["capability_policy"]["factor"] = None
    row = data["systems"][0]
    row.update(composite_score=None, rank=None, axes={"intelligence": None, "calibration": None, "speed": None, "cost": None},
               price={"usd_per_1000_decisions": None},
               latency={"p50_s_measured": None, "p50_s_adjusted": None, "p95_s_adjusted": None})
    row["capability"].update(score=None, rank=None)
    dl.validate_feed(data)
    result = dl.classify(data)[0]
    for field in ("intelligence", "calibration", "speed", "cost_axis", "capability", "capability_rank",
                  "composite", "composite_rank", "price", "latency", "latency_measured", "latency_p95"):
        assert result[field] is None


def test_oversized_integer_is_rejected_without_overflow(dl):
    data = feed()
    data["systems"][0]["composite_score"] = 10 ** 1000
    with pytest.raises(dl.FetchError, match="synthetic"):
        dl.validate_feed(data)
