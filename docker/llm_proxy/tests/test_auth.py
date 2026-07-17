import base64
import json

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from llm_proxy.auth import decode_credentials, extract_authorization


class TestDecodeCredentials:
    def test_valid_base64_json(self):
        payload = {"cookies": "abc", "convex_session_id": "123"}
        token = base64.b64encode(json.dumps(payload).encode()).decode()
        result = decode_credentials(f"Bearer {token}")
        assert result == payload

    def test_invalid_base64(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_credentials("Bearer !!!not-base64!!!")
        assert exc_info.value.status_code == 401

    def test_valid_base64_invalid_json(self):
        token = base64.b64encode(b"not json at all").decode()
        with pytest.raises(HTTPException) as exc_info:
            decode_credentials(f"Bearer {token}")
        assert exc_info.value.status_code == 401

    def test_missing_bearer_prefix(self):
        payload = {"key": "value"}
        token = base64.b64encode(json.dumps(payload).encode()).decode()
        with pytest.raises(HTTPException) as exc_info:
            decode_credentials(f"Token {token}")
        assert exc_info.value.status_code == 401


class TestExtractAuthorization:
    def test_missing_header(self):
        from starlette.requests import Request
        from starlette.datastructures import Headers

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
        }
        request = Request(scope)
        with pytest.raises(HTTPException) as exc_info:
            extract_authorization(request)
        assert exc_info.value.status_code == 401

    def test_valid_header(self):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", b"Bearer abc123")],
        }
        request = Request(scope)
        result = extract_authorization(request)
        assert result == "Bearer abc123"
