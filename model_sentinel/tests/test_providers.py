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
