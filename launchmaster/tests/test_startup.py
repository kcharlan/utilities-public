from __future__ import annotations

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
