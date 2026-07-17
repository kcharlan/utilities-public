from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import assert_launcher_help, load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "storage_monitor"


def test_help_exits_without_creating_runtime_state(tmp_path):
    runtime_home = tmp_path / "runtime_home"
    assert_launcher_help(
        SCRIPT_PATH,
        env_overrides={"STORAGE_MONITOR_HOME": str(runtime_home)},
    )

    assert not runtime_home.exists()


def test_launcher_loads_fastapi_app(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime_home"))
    module = load_launcher(SCRIPT_PATH)

    assert module.app.title == "Storage Monitor"


def test_parse_diskutil_info_extracts_byte_counts(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime_home"))
    module = load_launcher(SCRIPT_PATH)

    parsed = module.parse_diskutil_info(
        "Volume Used Space:  1.0 GB (1000 Bytes)\n"
        "Container Free Space:  2.0 GB (2000 Bytes)\n"
        "Disk Size:  3.0 GB (3000 Bytes)\n"
    )

    assert parsed == {
        "volume_used_bytes": 1000,
        "container_free_bytes": 2000,
        "disk_size_bytes": 3000,
        "container_total_space_bytes": None,
    }
