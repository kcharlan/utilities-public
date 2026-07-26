from __future__ import annotations

import json
import sys
from pathlib import Path

UTILITIES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(UTILITIES_ROOT))

from tools.testkit import assert_launcher_help, load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "launchmaster"


def test_home_override_controls_runtime_paths_without_eager_creation(monkeypatch, tmp_path):
    runtime_home = tmp_path / "launchmaster-home"
    monkeypatch.setenv("LAUNCHMASTER_HOME", str(runtime_home))

    module = load_launcher(SCRIPT_PATH)

    assert Path(module.DATA_DIR) == runtime_home
    assert Path(module.CONFIG_FILE) == runtime_home / "config.json"
    assert not runtime_home.exists()


def test_help_does_not_create_overridden_runtime_home(tmp_path):
    runtime_home = tmp_path / "launchmaster-home"

    assert_launcher_help(
        SCRIPT_PATH,
        env_overrides={"LAUNCHMASTER_HOME": str(runtime_home)},
    )

    assert not runtime_home.exists()


def test_load_config_migrates_all_legacy_frontend_keys(monkeypatch, tmp_path):
    runtime_home = tmp_path / "launchmaster-home"
    runtime_home.mkdir()
    monkeypatch.setenv("LAUNCHMASTER_HOME", str(runtime_home))
    (runtime_home / "config.json").write_text(json.dumps({
        "pollInterval": 17,
        "showApple": True,
        "darkMode": False,
        "confirmDestructive": False,
        "confirmApple": False,
    }))
    module = load_launcher(SCRIPT_PATH)

    loaded = module._load_config()

    assert loaded == {
        "poll_interval": 17,
        "show_apple_jobs": True,
        "dark_mode": False,
        "confirm_destructive": False,
        "confirm_apple_modify": False,
    }
    module._save_config(loaded)
    saved = json.loads((runtime_home / "config.json").read_text())
    assert saved == loaded


def test_load_config_prefers_canonical_key_over_legacy_key(
    monkeypatch, tmp_path
):
    runtime_home = tmp_path / "launchmaster-home"
    runtime_home.mkdir()
    monkeypatch.setenv("LAUNCHMASTER_HOME", str(runtime_home))
    (runtime_home / "config.json").write_text(json.dumps({
        "showApple": True,
        "show_apple_jobs": False,
    }))
    module = load_launcher(SCRIPT_PATH)

    loaded = module._load_config()

    assert loaded["show_apple_jobs"] is False
    assert "showApple" not in loaded
