import os
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.testkit import load_launcher

os.environ.setdefault("UTILITIES_TESTING", "1")


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("DECISION_LADDER_HOME", str(tmp_path / "decision-home"))


@pytest.fixture(scope="session")
def dl():
    return load_launcher(PROJECT / "decision_ladder")
