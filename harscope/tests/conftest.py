"""Shared fixtures for harscope API tests.

The main harscope file has no .py extension, so we import it via importlib
and expose the FastAPI ``app`` plus helper classes through fixtures.
"""

import json
import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("UTILITIES_TESTING", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


_HARSCOPE_PATH = Path(__file__).resolve().parents[1] / "harscope"
harscope_mod = load_launcher(_HARSCOPE_PATH, "harscope_mod")

# Re-export for direct import in test files
app = harscope_mod.app
HARManager = harscope_mod.HARManager
SecurityScanner = harscope_mod.SecurityScanner
ExportEngine = harscope_mod.ExportEngine


def _fixture_value(*parts: str) -> str:
    """Build intentional detector inputs without storing secret-shaped literals."""
    return "".join(parts)


PATTERN_SAMPLE_JWT = _fixture_value(
    "eyJhbGci", "OiJIUzI1", "NiJ9.", "eyJzdWIi", "OiIxMjM0",
    "NTY3ODkw", "In0.", "abc123", "def456",
)
PATTERN_SAMPLE_CLOUD = _fixture_value(
    "sk-proj-", "abc123", "def456", "ghi789", "jkl012", "mno345",
)
PATTERN_SAMPLE_OPAQUE = _fixture_value(
    "abc123", "xyz789", "def456", "ghi012", "jkl345",
    "mno678", "pqr901", "stu234", "vwx567",
)
PATTERN_SAMPLE_LOGIN = _fixture_value("s3cr", "et!")

# ---------------------------------------------------------------------------
# Minimal valid HAR content used across many tests
# ---------------------------------------------------------------------------
MINIMAL_HAR = {
    "log": {
        "version": "1.2",
        "creator": {"name": "test", "version": "1.0"},
        "entries": [
            {
                "startedDateTime": "2024-01-01T00:00:00.000Z",
                "time": 100,
                "request": {
                    "method": "GET",
                    "url": "https://example.com/api/data",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Host", "value": "example.com"},
                        {"name": "Authorization", "value": "Bearer " + PATTERN_SAMPLE_JWT},
                    ],
                    "queryString": [
                        {"name": "api_key", "value": PATTERN_SAMPLE_CLOUD},
                    ],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": -1,
                },
                "response": {
                    "status": 200,
                    "statusText": "OK",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Content-Type", "value": "application/json"},
                        {"name": "Set-Cookie", "value": "session=abc123xyz; Path=/; HttpOnly"},
                    ],
                    "cookies": [
                        {"name": "session_token", "value": PATTERN_SAMPLE_OPAQUE},
                    ],
                    "content": {
                        "size": 50,
                        "mimeType": "application/json",
                        "text": json.dumps(
                            {"user": "alice", "token": PATTERN_SAMPLE_JWT, "status": "ok"},
                            separators=(",", ":"),
                        ),
                    },
                    "redirectURL": "",
                    "headersSize": -1,
                    "bodySize": 50,
                },
                "cache": {},
                "timings": {
                    "blocked": 1,
                    "dns": 5,
                    "connect": 10,
                    "ssl": 8,
                    "send": 2,
                    "wait": 60,
                    "receive": 14,
                },
            },
            {
                "startedDateTime": "2024-01-01T00:00:00.200Z",
                "time": 50,
                "request": {
                    "method": "POST",
                    "url": "http://example.com/api/submit",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Content-Type", "value": "application/json"},
                    ],
                    "queryString": [],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": 30,
                    "postData": {
                        "mimeType": "application/json",
                        "text": json.dumps(
                            {
                                "username": "bob",
                                _fixture_value("pass", "word"): PATTERN_SAMPLE_LOGIN,
                                "action": "login",
                            },
                            separators=(",", ":"),
                        ),
                    },
                },
                "response": {
                    "status": 401,
                    "statusText": "Unauthorized",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Content-Type", "value": "application/json"},
                    ],
                    "cookies": [],
                    "content": {
                        "size": 30,
                        "mimeType": "application/json",
                        "text": '{"error":"Invalid credentials"}',
                    },
                    "redirectURL": "",
                    "headersSize": -1,
                    "bodySize": 30,
                },
                "cache": {},
                "timings": {
                    "blocked": 0,
                    "dns": 0,
                    "connect": 0,
                    "ssl": 0,
                    "send": 1,
                    "wait": 45,
                    "receive": 4,
                },
            },
        ],
    }
}


def _reset_global_state():
    """Reset the module-level singletons so tests don't leak state."""
    harscope_mod.har_manager.__init__()
    harscope_mod.security_scanner.__init__()
    harscope_mod.sequence_builder.__init__()


@pytest.fixture(autouse=True)
def _isolate_state():
    """Ensure every test starts with a clean slate."""
    _reset_global_state()
    yield
    _reset_global_state()


@pytest.fixture
def client():
    """Synchronous-style test client using httpx."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def minimal_har_json():
    """Return the minimal HAR content as a JSON string."""
    return json.dumps(MINIMAL_HAR)


@pytest.fixture
def minimal_har_dict():
    """Return the minimal HAR content as a dict (deep copy)."""
    import copy
    return copy.deepcopy(MINIMAL_HAR)


async def load_har(client: AsyncClient, har_dict: dict = None, filename: str = "test.har"):
    """Helper: load a HAR into the server via /api/open-content."""
    content = json.dumps(har_dict or MINIMAL_HAR)
    resp = await client.post("/api/open-content", json={"content": content, "filename": filename})
    assert resp.status_code == 200, f"Failed to load HAR: {resp.text}"
    return resp.json()
