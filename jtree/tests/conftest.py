"""Shared fixtures for jtree API tests."""
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("UTILITIES_TESTING", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import ASGISyncClient, load_launcher


_JTREE_PATH = Path(__file__).resolve().parents[1] / "jtree"
jtree_mod = load_launcher(_JTREE_PATH, "jtree_mod")

# Re-export handy references
app = jtree_mod.app
JSONManager = jtree_mod.JSONManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DATA = {
    "name": "jtree",
    "version": 1,
    "tags": ["json", "viewer", "editor"],
    "nested": {
        "a": 1,
        "b": [10, 20, 30],
        "c": {"deep": True}
    },
    "empty_obj": {},
    "empty_arr": [],
    "flag": False,
    "nothing": None,
}


@pytest.fixture()
def sample_json_file(tmp_path):
    """Write SAMPLE_DATA to a temp .json file and return its path."""
    p = tmp_path / "sample.json"
    p.write_text(json.dumps(SAMPLE_DATA, indent=2))
    return str(p)


@pytest.fixture()
def readonly_json_file(tmp_path):
    """Write SAMPLE_DATA to a temp .json file for readonly tests."""
    p = tmp_path / "readonly.json"
    p.write_text(json.dumps(SAMPLE_DATA, indent=2))
    return str(p)


@pytest.fixture(autouse=True)
def _reset_manager():
    """Reset the global json_manager before every test to avoid cross-test leakage."""
    jtree_mod.json_manager = None
    yield
    jtree_mod.json_manager = None


@pytest.fixture()
def client():
    """Synchronous HTTPX client wrapping the FastAPI app."""
    return ASGISyncClient(app)


@pytest.fixture()
def loaded_client(client, sample_json_file):
    """A TestClient with a file already loaded via /api/open."""
    resp = client.post("/api/open", json={"path": sample_json_file})
    assert resp.status_code == 200
    return client


@pytest.fixture()
def readonly_client(client, readonly_json_file):
    """A TestClient with a file loaded in readonly mode."""
    resp = client.post("/api/open", json={"path": readonly_json_file, "readonly": True})
    assert resp.status_code == 200
    return client
