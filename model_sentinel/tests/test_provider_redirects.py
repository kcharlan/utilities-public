from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
from urllib.request import HTTPSHandler

import pytest

from model_sentinel import providers
from model_sentinel.config import ProviderConfig
from model_sentinel.provider_profiles import OPENROUTER_PROFILE
from model_sentinel import __version__
from model_sentinel.config import load_config
from tests.credential_fixtures import synthetic_provider_server, write_credential_config


def test_catalog_redirect_does_not_send_bearer_to_destination(monkeypatch):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization"), self.headers.get("Accept"), self.headers.get("User-Agent")))
            self.send_response(302 if self.path == "/models" else 200)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/destination")
            self.end_headers()

        def log_message(self, *args):
            pass

    class LoopbackHTTPSHandler(HTTPSHandler):
        def https_open(self, request):
            return self.do_open(HTTPConnection, request)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(providers, "HTTPSHandler", LoopbackHTTPSHandler)
    provider = ProviderConfig("fake", "Fake", "openrouter", f"https://127.0.0.1:{server.server_port}", "/models", "FAKE_KEY", 1, 1, True)
    try:
        with pytest.raises(providers.ProviderFetchError) as caught:
            providers.fetch_raw_models(provider, "SYNTHETIC_KEY", OPENROUTER_PROFILE)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert caught.value.http_status == 302
    assert seen == [("/models", "Bearer SYNTHETIC_KEY", "application/json", f"model_sentinel/{__version__}")]


def test_catalog_rejects_http_before_opening(monkeypatch):
    provider = ProviderConfig("fake", "Fake", "openrouter", "http://example.invalid", "/models", "FAKE_KEY", 1, 1, True)
    def unexpected(*args, **kwargs):
        pytest.fail("insecure request was opened")
    monkeypatch.setattr(providers, "_open_catalog", unexpected)
    with pytest.raises(providers.ProviderFetchError):
        providers.fetch_raw_models(provider, "SYNTHETIC_KEY", OPENROUTER_PROFILE)


def test_catalog_rejects_untrusted_tls_certificate(tmp_path, monkeypatch):
    home = write_credential_config(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    with synthetic_provider_server(home) as authorizations:
        certificate = os.environ["SSL_CERT_FILE"]
        try:
            os.environ["SSL_CERT_FILE"] = str(tmp_path / "missing-ca.pem")
            provider = load_config(tmp_path).providers[0]
            with pytest.raises(providers.ProviderFetchError, match="network error"):
                providers.fetch_raw_models(provider, "SYNTHETIC_KEY", OPENROUTER_PROFILE)
            assert authorizations == []
        finally:
            os.environ["SSL_CERT_FILE"] = certificate
