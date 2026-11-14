"""Shared pytest defaults for Model Ladder."""
import os
import sys
import urllib.request
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parent
LAUNCHER = PROJECT / "model_ladder"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.testkit import load_launcher  # noqa: E402

os.environ.setdefault("UTILITIES_TESTING", "1")


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network access in a test")
    monkeypatch.setattr(urllib.request, "urlopen", denied)


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    """Keep every test's runtime home in fresh private scratch storage."""
    assert not tmp_path.resolve().is_relative_to(REPO.resolve())
    monkeypatch.setenv("MODEL_LADDER_HOME", str(tmp_path / "ml-home"))


@pytest.fixture(scope="session")
def ml():
    """The launcher module, loaded once."""
    return load_launcher(LAUNCHER)
