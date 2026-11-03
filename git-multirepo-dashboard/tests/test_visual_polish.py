"""
Packet 23: Visual Polish

Test the /api/status endpoint shape.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import fastapi    # noqa: F401
    import aiosqlite  # noqa: F401
except ImportError:
    pytest.skip(
        "fastapi/aiosqlite not installed — run from the repository root: "
        "UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py git_fleet",
        allow_module_level=True,
    )

import git_dashboard  # noqa: E402


def test_api_status_endpoint_shape(test_app):
    """GET /api/status must return {tools: {...}, version: '...'}."""
    client, _ = test_app
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "tools" in body
    assert "version" in body
    assert isinstance(body["tools"], dict)
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0
