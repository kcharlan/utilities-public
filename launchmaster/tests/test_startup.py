from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

UTILITIES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(UTILITIES_ROOT))

from fake_launchctl import read_line_within
from tools.testkit import assert_launcher_help, load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "launchmaster"
RUNNING = "com.example.synthetic-running"
REQUEST_TIMEOUT = 15


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


def test_read_line_within_gives_up_on_a_silent_child():
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], stdout=subprocess.PIPE, text=True
    )
    try:
        started = time.monotonic()
        assert read_line_within(child.stdout, timeout=0.2) is None
        assert time.monotonic() - started < 5
    finally:
        child.kill()
        child.communicate(timeout=5)


def test_synthetic_server_refuses_a_subprocess_with_no_named_fake(synthetic_server_probe):
    with urllib.request.urlopen(f"{synthetic_server_probe}/api/probe", timeout=REQUEST_TIMEOUT) as response:
        assert "Subprocess refused" in json.load(response)["refused"]


def test_main_boots_and_serves_parsed_launchctl_output(faked_launchctl_main):
    url, startup_output = faked_launchctl_main

    assert startup_output.startswith(f"launchmaster v{load_launcher(SCRIPT_PATH).VERSION} starting at ")
    with urllib.request.urlopen(f"{url}/", timeout=REQUEST_TIMEOUT) as response:
        assert b"launchmaster" in response.read()
    with urllib.request.urlopen(f"{url}/api/jobs?include_apple=true", timeout=REQUEST_TIMEOUT) as response:
        jobs = {job["label"]: job for job in json.load(response)}
    assert jobs[RUNNING]["pid"] == 424242
    assert jobs[RUNNING]["status"] == "running"
    assert jobs["com.example.synthetic-failed"]["status"] == "failed"
    assert jobs["com.example.synthetic-disabled"]["status"] == "disabled"

    with urllib.request.urlopen(f"{url}/api/jobs/{RUNNING}", timeout=REQUEST_TIMEOUT) as response:
        job = json.load(response)
    assert job["detail"]["state"] == "running"
    assert job["detail"]["last_exit_code"] == 78
    assert job["blame"] == "speculative"
