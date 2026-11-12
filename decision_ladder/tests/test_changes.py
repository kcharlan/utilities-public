from copy import deepcopy
from datetime import datetime, timedelta, timezone
from helpers import feed


def test_diff_detects_displayed_changes_and_ignores_unused_fields(dl):
    old = {"fetched_at": "before", "feed": feed()}
    new = deepcopy(old)
    new["fetched_at"] = "after"
    new["feed"]["unused"] = "synthetic"
    assert not dl._shows_a_change(dl.diff_rows(old, new))
    new["feed"]["systems"][0]["price"] = {"usd_per_1000_decisions": 3}
    diff = dl.diff_rows(old, new)
    assert diff["changed"][0]["price"] == [None, 3]
    assert dl._shows_a_change(diff)
    new["feed"]["revision"] = "new synthetic revision"
    assert dl.diff_rows(old, new)["revision"] == ["synthetic", "new synthetic revision"]


def test_diff_reports_additions_and_removals(dl):
    old = {"fetched_at": "before", "feed": feed()}
    new = deepcopy(old)
    new["fetched_at"] = "after"
    new["feed"]["systems"][0].update(key="other", name="Other synthetic")
    diff = dl.diff_rows(old, new)
    assert diff["added"] == ["Other synthetic"]
    assert diff["removed"] == ["Synthetic"]


def test_last_real_change_skips_unused_fields(dl, tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    data = feed()
    first = dl.save_snapshot(tmp_path, {"feed": data, "sha256": "synthetic"}, now)
    data = deepcopy(data)
    data["revision"] = "new synthetic"
    second = dl.save_snapshot(tmp_path, {"feed": data, "sha256": "synthetic"}, now + timedelta(seconds=1))
    data = deepcopy(data)
    data["unused"] = "synthetic"
    third = dl.save_snapshot(tmp_path, {"feed": data, "sha256": "synthetic"}, now + timedelta(seconds=2))
    previous = dl._last_real_change([second, first], dl.read_snapshot(third))
    assert previous == dl.read_snapshot(first)
