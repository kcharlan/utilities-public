"""Shared pytest defaults for tax2."""

import os
from pathlib import Path

import pytest


os.environ.setdefault("UTILITIES_TESTING", "1")


@pytest.fixture(autouse=True)
def isolated_tax2_home(monkeypatch, tmp_path):
    """Keep implicit config access in fresh scratch storage for every test."""
    assert not tmp_path.resolve().is_relative_to(Path(__file__).resolve().parents[2])
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "tax2-home"))
