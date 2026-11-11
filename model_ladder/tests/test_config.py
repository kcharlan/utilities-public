import json
import os
from pathlib import Path

import pytest


def test_runtime_home_honours_override(ml, tmp_path):
    assert ml.runtime_home() == tmp_path / "ml-home"


def test_runtime_home_default(ml, monkeypatch):
    monkeypatch.delenv("MODEL_LADDER_HOME")
    assert ml.runtime_home() == Path.home() / ".model_ladder"


def test_first_load_creates_private_default_config(ml, tmp_path):
    assert ml.load_config() == ml.DEFAULT_CONFIG
    home = tmp_path / "ml-home"
    config = home / "config.json"
    assert json.loads(config.read_text()) == ml.DEFAULT_CONFIG
    assert config.stat().st_mode & 0o777 == 0o600
    assert home.stat().st_mode & 0o777 == 0o700


def test_partial_config_gets_defaults(ml, tmp_path):
    home = ml.ensure_runtime_home(tmp_path / "ml-home")
    (home / "config.json").write_text(json.dumps({"op_item": "synthetic"}))
    cfg = ml.load_config()
    assert cfg == {**ml.DEFAULT_CONFIG, "op_item": "synthetic"}


def test_non_object_config_names_the_file(ml, tmp_path):
    home = ml.ensure_runtime_home(tmp_path / "ml-home")
    (home / "config.json").write_text("[1]")
    with pytest.raises(ValueError, match="config.json"):
        ml.load_config()


def test_ensure_runtime_home_fixes_mode(ml, tmp_path):
    home = tmp_path / "ml-home"
    home.mkdir()
    home.chmod(0o755)
    assert ml.ensure_runtime_home(home).stat().st_mode & 0o777 == 0o700


def test_atomic_write_failure_preserves_old_file(ml, monkeypatch, tmp_path):
    home = ml.ensure_runtime_home(tmp_path / "ml-home")
    page = home / "page.html"
    ml.atomic_write_bytes(page, b"synthetic old")
    assert page.stat().st_mode & 0o777 == 0o600

    def fail(*args):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="synthetic replace failure"):
        ml.atomic_write_bytes(page, b"synthetic new")
    assert page.read_bytes() == b"synthetic old"
    assert list(home.iterdir()) == [page]
