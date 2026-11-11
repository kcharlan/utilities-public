"""Failure-path hardening: every bad input becomes a one-line message, never a traceback."""
import http.client
import json

import pytest

from helpers import model
from test_fetch import SECRET, Opener, Response, http_error


def write_config(ml, tmp_path, text):
    home = ml.ensure_runtime_home(tmp_path / "ml-home")
    (home / "config.json").write_text(text)


def test_invalid_json_config_names_the_file(ml, tmp_path):
    write_config(ml, tmp_path, "{not json")
    with pytest.raises(ValueError, match="config.json.*not valid JSON"):
        ml.load_config()


@pytest.mark.parametrize("key,bad", [
    ("op_item", 5), ("op_vault", None), ("op_field", ["x"]),
    ("max_age_hours", "12"), ("max_age_hours", True), ("max_age_hours", 0),
    ("max_age_hours", -3), ("max_age_hours", None), ("max_age_hours", float("inf")),
])
def test_config_value_types_are_validated(ml, tmp_path, key, bad):
    write_config(ml, tmp_path, json.dumps({key: bad}))
    with pytest.raises(ValueError, match=rf"config.json.*{key}"):
        ml.load_config()


def test_config_accepts_fractional_age(ml, tmp_path):
    write_config(ml, tmp_path, json.dumps({"max_age_hours": 0.5}))
    assert ml.load_config()["max_age_hours"] == 0.5


def test_rejects_non_object_evaluations_and_cost_blocks(ml):
    bad = model("Alpha Test 1", index=10)
    bad["evaluations"] = ["x"]
    with pytest.raises(ml.FetchError, match="alpha-test-1.*evaluations"):
        ml.validate_models([bad])
    bad = model("Alpha Test 1", index=10)
    bad["artificial_analysis_intelligence_index_cost"] = "x"
    with pytest.raises(ml.FetchError, match="alpha-test-1.*artificial_analysis_intelligence_index_cost"):
        ml.validate_models([bad])


class BrokenResponse(Response):
    def __init__(self, error):
        super().__init__({})
        self.error = error

    def read(self):
        raise self.error


def test_incomplete_read_is_a_fetch_error(ml):
    opener = Opener([BrokenResponse(http.client.IncompleteRead(b"ab", 10))])
    with pytest.raises(ml.FetchError, match="incomplete"):
        ml.fetch_all(SECRET, open_url=opener)


@pytest.mark.parametrize("body", [b"<html>not json", b"\xff\xfe"])
def test_non_json_body_is_a_fetch_error(ml, body):
    response = Response({})
    response._body = body
    with pytest.raises(ml.FetchError, match="not valid JSON"):
        ml.fetch_all(SECRET, open_url=Opener([response]))


@pytest.mark.parametrize("reset", ["99999999999999999999", "-99999999999999"])
def test_429_with_absurd_reset_falls_back(ml, reset):
    opener = Opener([http_error(429, {"x-ratelimit-reset": reset})])
    with pytest.raises(ml.FetchError, match="unknown time"):
        ml.fetch_all(SECRET, open_url=opener)


@pytest.mark.parametrize("value", ["   ", "\t\n"])
def test_whitespace_env_key_counts_as_unset(ml, value):
    with pytest.raises(ml.KeyUnavailable, match="No API key configured"):
        ml.get_api_key({"op_item": ""}, env={"MODEL_LADDER_AA_KEY": value})


def test_env_key_is_stripped(ml):
    assert ml.get_api_key({}, env={"MODEL_LADDER_AA_KEY": f"  {SECRET}\n"}) == SECRET


@pytest.mark.parametrize("text", ["1e300", "87600.5", "9" * 400])
def test_absurd_max_age_is_rejected(ml, tmp_path, text):
    write_config(ml, tmp_path, '{"max_age_hours": ' + text + "}")
    with pytest.raises(ValueError, match=r"config.json.*max_age_hours"):
        ml.load_config()


def test_ten_year_max_age_is_accepted(ml, tmp_path):
    write_config(ml, tmp_path, json.dumps({"max_age_hours": 87600}))
    assert ml.load_config()["max_age_hours"] == 87600


def test_no_key_message_names_full_config_path(ml):
    with pytest.raises(ml.KeyUnavailable) as info:
        ml.get_api_key({"op_item": ""}, env={})
    assert str(ml.runtime_home() / "config.json") in str(info.value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_index_is_rejected(ml, value):
    bad = model("Alpha Test 1", index=10, cost=1.0)
    bad["evaluations"]["artificial_analysis_intelligence_index"] = value
    with pytest.raises(ml.FetchError, match="alpha-test-1.*artificial_analysis_intelligence_index"):
        ml.validate_models([bad])


@pytest.mark.parametrize("value", ["bad", True, float("nan"), float("inf")])
def test_invalid_domain_index_names_field(ml, value):
    bad = model("Alpha Test 1", 50, scores={"finance": value})
    with pytest.raises(ml.FetchError, match="artificial_analysis_finance_and_accounting_index"):
        ml.validate_models([bad])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_cost_is_rejected(ml, value):
    bad = model("Alpha Test 1", index=10, cost=1.0)
    bad["artificial_analysis_intelligence_index_cost"]["cost_per_task"]["total_cost"] = value
    with pytest.raises(ml.FetchError, match="alpha-test-1.*cost_per_task.total_cost"):
        ml.validate_models([bad])
