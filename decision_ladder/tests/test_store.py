from datetime import datetime, timedelta, timezone
import pytest
from helpers import feed


def test_unchanged_feed_only_refreshes_last_checked(dl, tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = {"feed": feed(), "sha256": "synthetic"}
    path = dl.save_snapshot(tmp_path, result, now)
    assert dl.save_snapshot(tmp_path, result, now + timedelta(hours=1)) == path
    snap = dl.read_snapshot(path)
    assert snap["fetched_at"] == now.isoformat()
    assert snap["last_checked"] == (now + timedelta(hours=1)).isoformat()
    assert len(dl.load_snapshots(tmp_path)) == 1


def test_distinct_fetches_within_same_second_preserve_all_history(dl, tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    paths = []
    for index, moment in enumerate((now, now + timedelta(microseconds=10), now + timedelta(microseconds=10))):
        data = feed(revision=f"synthetic {index}")
        paths.append(dl.save_snapshot(tmp_path, {"feed": data, "sha256": "synthetic"}, moment))
    assert len(set(paths)) == 3
    assert dl.load_snapshots(tmp_path) == list(reversed(paths))
    assert [dl.read_snapshot(path)["feed"]["revision"] for path in paths] == [
        "synthetic 0", "synthetic 1", "synthetic 2"
    ]


def test_same_second_retention_keeps_latest_snapshot(dl, tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(62):
        data = feed(revision=f"synthetic {index}")
        last = dl.save_snapshot(tmp_path, {"feed": data, "sha256": "synthetic"}, now)
    paths = dl.load_snapshots(tmp_path)
    assert len(paths) == 60
    assert paths[0] == last
    assert dl.read_snapshot(paths[0])["feed"]["revision"] == "synthetic 61"


def test_store_private_modes_retention_and_bad_snapshot(dl, tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(61):
        data = feed()
        data["revision"] = f"synthetic {i}"
        dl.save_snapshot(tmp_path, {"feed": data, "sha256": "synthetic"}, now + timedelta(seconds=i))
    paths = dl.load_snapshots(tmp_path)
    assert len(paths) == 60
    assert (tmp_path / "snapshots").stat().st_mode & 0o777 == 0o700
    assert paths[0].stat().st_mode & 0o777 == 0o600
    paths[0].write_bytes(b"not gzip")
    with pytest.raises(dl.StoreError, match="cannot read"):
        dl.read_snapshot(paths[0])


def test_bad_feed_in_snapshot_is_reported(dl, tmp_path):
    import gzip
    import json
    path = tmp_path / "broken.json.gz"
    path.write_bytes(gzip.compress(json.dumps({"schema": 1, "feed": {}, "fetched_at": "2026-01-01T00:00:00+00:00",
                                               "last_checked": "2026-01-01T00:00:00+00:00", "sha256": "synthetic"}).encode()))
    with pytest.raises(dl.StoreError, match="cannot read"):
        dl.read_snapshot(path)
