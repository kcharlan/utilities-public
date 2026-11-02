"""Schedule descriptions derived from synthetic launchd plist values."""
from pathlib import Path
import plistlib
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import load_launcher


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    monkeypatch.setenv("LAUNCHMASTER_HOME", str(tmp_path / "home"))
    return load_launcher(Path(__file__).resolve().parents[1] / "launchmaster")


@pytest.mark.parametrize(("plist", "expected"), [
    ({"StartCalendarInterval": {"Weekday": 1, "Hour": 9, "Minute": 30}}, "Mon at 9:30 AM"),
    ({"StartCalendarInterval": [{"Weekday": 1, "Hour": 9, "Minute": 0}, {"Weekday": 3, "Hour": 9, "Minute": 0}]}, "Mon, Wed at 9:00 AM"),
    ({"StartCalendarInterval": [{"Hour": 9, "Minute": 0}, {"Hour": 17, "Minute": 30}]}, "at 9:00 AM; at 5:30 PM"),
    ({"StartCalendarInterval": {"Weekday": 7, "Hour": 9, "Minute": 0}}, "Sun at 9:00 AM"),
    ({"StartCalendarInterval": {"Weekday": 0, "Hour": 9, "Minute": 0}}, "Sun at 9:00 AM"),
    ({"StartCalendarInterval": {"Day": 1, "Month": 6, "Hour": 8, "Minute": 0}}, "Jun 1 at 8:00 AM"),
    ({"StartCalendarInterval": {"Month": 6}}, "In Jun"),
    ({"StartCalendarInterval": [{"Weekday": 1, "Hour": 9}, {"Weekday": 3, "Hour": 17}]}, "Mon at 9:00 AM; Wed at 5:00 PM"),
    ({"StartCalendarInterval": [{"Weekday": 1, "Month": 6}, {"Weekday": 3, "Month": 7}]}, "Mon in Jun; Wed in Jul"),
    ({"StartCalendarInterval": [{"Weekday": 1, "Hour": 9}, {"Hour": 17}, {"Weekday": 3, "Hour": 9}]}, "Mon, Wed at 9:00 AM; at 5:00 PM"),
    ({"StartCalendarInterval": {"Day": 4}}, "Day 4 of month"),
    ({"StartCalendarInterval": {"Minute": 5}}, "at :05 past every hour"),
    ({"KeepAlive": True}, "Always running (KeepAlive)"),
    ({"KeepAlive": {"SuccessfulExit": False}}, "Conditional KeepAlive"),
    ({"StartInterval": 300}, "Every 5 minutes"),
    ({"StartInterval": 3600}, "Every 1 hour"),
    ({"StartInterval": 1}, "Every 1 second"),
    ({"RunAtLoad": True}, "Run at load"),
    ({"WatchPaths": ["/synthetic/input"]}, "Watching: /synthetic/input"),
    ({}, "Manual"),
])
def test_schedule_description(launcher, plist, expected):
    assert launcher.humanize_schedule(plist) == expected


def test_discovery_preserves_schedule_fields(launcher, monkeypatch, tmp_path):
    schedule = {"StartInterval": 300, "KeepAlive": True, "WatchPaths": ["/synthetic/input"]}
    with (tmp_path / "synthetic.plist").open("wb") as output:
        plistlib.dump({"Label": "com.example.synthetic", **schedule}, output)
    monkeypatch.setattr(launcher, "PLIST_DIRS", {"user-agent": str(tmp_path)})
    job = launcher.discover_plists()[0]
    assert job["start_interval"] == 300
    assert job["keep_alive"] is True
    assert job["watch_paths"] == ["/synthetic/input"]
