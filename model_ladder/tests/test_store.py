import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest

from helpers import model

T0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
RATE = {"limit": 100, "remaining": 95, "reset": 1_800_000_000}


def result(models=None, version=5, rate=RATE):
    models = [model("Alpha Test 1 (high)", 50, 1.0)] if models is None else models
    return {"models": models, "index_version": version, "rate_limit": rate}


@pytest.fixture
def home(ml, tmp_path):
    return ml.ensure_runtime_home(tmp_path / "ml-home")


def test_save_creates_private_gzip(ml, home):
    path = ml.save_snapshot(home, result(), T0)
    assert path.parent == home / "snapshots"
    assert path.name == "20261101T120000Z.json.gz"
    assert path.stat().st_mode & 0o777 == 0o600
    data = ml.read_snapshot(path)
    assert data["schema"] == 1 and data["index_version"] == 5
    assert data["fetched_at"] == data["last_checked"] == "2026-11-01T12:00:00+00:00"
    assert data["rate_limit"] == RATE
    assert data["models"] == result()["models"]


def test_identical_fetch_updates_last_checked_only(ml, home):
    first = ml.save_snapshot(home, result(), T0)
    later = T0 + timedelta(hours=13)
    second = ml.save_snapshot(home, result(rate={"limit": 100, "remaining": 90, "reset": 1}), later)
    assert second == first and len(ml.load_snapshots(home)) == 1
    data = ml.read_snapshot(first)
    assert data["fetched_at"] == "2026-11-01T12:00:00+00:00"
    assert data["last_checked"] == later.isoformat()
    assert data["rate_limit"]["remaining"] == 90
    assert first.stat().st_mode & 0o777 == 0o600


def test_new_index_version_makes_new_snapshot(ml, home):
    ml.save_snapshot(home, result(), T0)
    ml.save_snapshot(home, result(version=6), T0 + timedelta(hours=1))
    assert len(ml.load_snapshots(home)) == 2


def test_changed_fetch_creates_second_snapshot(ml, home):
    ml.save_snapshot(home, result(), T0)
    ml.save_snapshot(home, result([model("Alpha Test 1 (high)", 51, 1.0)]), T0 + timedelta(hours=1))
    paths = ml.load_snapshots(home)
    assert [p.name for p in paths] == ["20261101T130000Z.json.gz", "20261101T120000Z.json.gz"]


def test_prune_keeps_newest_60(ml, home):
    for n in range(62):
        ml.save_snapshot(home, result([model("Alpha Test 1 (high)", n, 1.0)]), T0 + timedelta(minutes=n))
    paths = ml.load_snapshots(home)
    assert len(paths) == 60 == ml.KEEP
    names = {p.name for p in paths}
    assert "20261101T120000Z.json.gz" not in names and "20261101T120100Z.json.gz" not in names
    assert "20261101T120200Z.json.gz" in names


def test_load_snapshots_empty(ml, home):
    assert ml.load_snapshots(home) == []


def test_newest_snapshot_skips_unreadable(ml, home):
    healthy = ml.save_snapshot(home, result(), T0)
    broken = healthy.parent / "20261101T130000Z.json.gz"
    broken.write_bytes(b"synthetic invalid")
    path, data, skipped = ml.newest_snapshot(home)
    assert path == healthy and data["models"] == result()["models"]
    assert len(skipped) == 1 and skipped[0][0] == broken
    assert str(broken) in skipped[0][1] and "cannot read" in skipped[0][1]


def test_newest_snapshot_none_readable(ml, home):
    directory = ml.snapshot_dir(home)
    older = directory / "20261101T120000Z.json.gz"
    newer = directory / "20261101T130000Z.json.gz"
    older.write_bytes(b"invalid older")
    newer.write_bytes(b"invalid newer")
    path, data, skipped = ml.newest_snapshot(home)
    assert path is None and data is None
    assert [item[0] for item in skipped] == [newer, older]
    assert all(str(path) in message for path, message in skipped)


def test_newest_snapshot_no_files(ml, home):
    assert ml.newest_snapshot(home) == (None, None, [])


def test_save_sets_aside_unreadable_newer_files(ml, home, capsys):
    healthy = ml.save_snapshot(home, result(), T0)
    broken = healthy.parent / "20261101T130000Z.json.gz"
    broken.write_bytes(b"invalid synthetic")
    assert ml.save_snapshot(home, result(), T0 + timedelta(hours=2)) == healthy
    retained = broken.with_name(broken.name + ".unreadable")
    assert retained.read_bytes() == b"invalid synthetic"
    assert retained.stat().st_mode & 0o777 == 0o600
    assert ml.load_snapshots(home) == [healthy]
    assert ml.read_snapshot(healthy)["last_checked"] == (T0 + timedelta(hours=2)).isoformat()
    assert "set aside an unreadable snapshot" in capsys.readouterr().err


def test_save_collision_preserves_healthy_snapshot_and_evidence(ml, home):
    healthy = ml.save_snapshot(home, result(), T0 - timedelta(hours=1))
    broken = healthy.parent / "20261101T120000Z.json.gz"
    broken.write_bytes(b"invalid synthetic")
    first = ml.save_snapshot(home, result(version=6), T0)
    second = ml.save_snapshot(home, result(version=7), T0)
    assert first.name == "20261101T120000Z_000001.json.gz"
    assert second.name == "20261101T120000Z_000002.json.gz"
    assert ml.load_snapshots(home) == [second, first, healthy]
    assert ml.read_snapshot(healthy)["index_version"] == 5
    assert broken.with_name(broken.name + ".unreadable").read_bytes() == b"invalid synthetic"


def test_set_aside_collision_preserves_existing_evidence(ml, home):
    healthy = ml.save_snapshot(home, result(), T0)
    broken = healthy.parent / "20261101T130000Z.json.gz"
    broken.write_bytes(b"new evidence")
    retained = broken.with_name(broken.name + ".unreadable")
    retained.write_bytes(b"old evidence")
    ml.save_snapshot(home, result(), T0 + timedelta(hours=2))
    assert retained.read_bytes() == b"old evidence"
    assert broken.with_name(broken.name + ".1.unreadable").read_bytes() == b"new evidence"


def test_failed_save_leaves_unreadable_files(ml, home, monkeypatch, capsys):
    healthy = ml.save_snapshot(home, result(), T0)
    broken = healthy.parent / "20261101T130000Z.json.gz"
    broken.write_bytes(b"invalid synthetic")
    def fail(*args):
        raise OSError("synthetic write failure")
    monkeypatch.setattr(ml, "_write_snapshot", fail)
    with pytest.raises(OSError, match="synthetic write failure"):
        ml.save_snapshot(home, result(version=6), T0 + timedelta(hours=2))
    assert broken.read_bytes() == b"invalid synthetic"
    assert "set aside" not in capsys.readouterr().err


def test_snapshot_ordinal_exhaustion_preserves_existing(ml, home):
    healthy = ml.save_snapshot(home, result(), T0)
    last = healthy.with_name("20261101T120000Z_999999.json.gz")
    last.write_bytes(b"synthetic invalid")
    with pytest.raises(ml.StoreError, match="ordinals exhausted"):
        ml.save_snapshot(home, result(version=6), T0)
    assert last.read_bytes() == b"synthetic invalid" and healthy.exists()


def test_new_snapshot_remains_active_when_timestamp_is_older(ml, home):
    for n in range(60):
        ml.save_snapshot(home, result(version=n), T0 + timedelta(minutes=n + 1))
    new = ml.save_snapshot(home, result(version=100), T0)
    assert new in ml.load_snapshots(home)
    assert len(ml.load_snapshots(home)) == 60


def test_other_source_snapshots_are_separate(ml, home):
    item = result(version="2.0")
    path = ml.save_snapshot(home, item, T0, source="fc")
    assert path.parent == home / "snapshots" / "fc"
    assert ml.load_snapshots(home) == []
    assert ml.load_snapshots(home, "fc") == [path]
    assert ml.read_snapshot(path, "fc")["index_version"] == "2.0"
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.parent.parent.stat().st_mode & 0o777 == 0o700


def test_not_modified_updates_metadata_without_new_file(ml, home):
    path = ml.save_snapshot(home, {**result(), "etag": "old"}, T0)
    later = T0 + timedelta(hours=1)
    assert ml.save_snapshot(home, {"not_modified": True, "etag": "new", "published": {"date": "2026-01-01", "note": "synthetic"}}, later) == path
    data = ml.read_snapshot(path)
    assert data["last_checked"] == later.isoformat()
    assert data["fetched_at"] == T0.isoformat()
    assert data["etag"] == "new"
    assert data["published"]["note"] == "synthetic"
    assert len(ml.load_snapshots(home)) == 1


def test_not_modified_without_snapshot_raises(ml, home):
    with pytest.raises(ml.StoreError, match="not modified, but there is no snapshot to keep"):
        ml.save_snapshot(home, {"not_modified": True}, T0)


def test_status_round_trip_and_mode(ml, home):
    ml.write_status(home, "aa", T0, "synthetic error")
    assert ml.read_status(home)["aa"] == {"last_attempt": T0.isoformat(), "error": "synthetic error"}
    assert (home / "status.json").stat().st_mode & 0o777 == 0o600


def test_unreadable_status_reads_empty(ml, home, capsys):
    (home / "status.json").write_text("invalid")
    assert ml.read_status(home) == {}
    assert len(capsys.readouterr().err.splitlines()) == 1


@pytest.mark.parametrize("entry", [None, "invalid", [], {},
                                   {"last_attempt": None, "error": None},
                                   {"last_attempt": "invalid", "error": None},
                                   {"last_attempt": "2026-11-01T12:00:00+00:00", "error": []}])
def test_invalid_source_status_reads_empty(ml, home, capsys, entry):
    (home / "status.json").write_text(json.dumps({"fc": entry}))
    assert ml.read_status(home) == {}
    diagnostic = capsys.readouterr().err
    assert "status.json" in diagnostic and len(diagnostic.splitlines()) == 1


def test_unchanged_fetch_refreshes_published_and_etag(ml, home):
    path = ml.save_snapshot(home, {**result(), "etag": "old", "published": None}, T0)
    ml.save_snapshot(home, {**result(), "etag": "new", "published": {"date": "2026-01-01", "note": "synthetic"}}, T0 + timedelta(hours=1))
    assert ml.read_snapshot(path)["etag"] == "new"
    assert ml.read_snapshot(path)["published"]["note"] == "synthetic"
    assert len(ml.load_snapshots(home)) == 1


def test_changed_feed_carries_published_forward(ml, home):
    metadata = {"published": {"date": "2026-01-01", "note": "synthetic"}, "current_version": "2.1"}
    ml.save_snapshot(home, {**result(version="2.0"), **metadata}, T0, "fc")
    path = ml.save_snapshot(home, result([model("Example (high)", 51, 1.0)], version="2.0"), T0 + timedelta(hours=1), "fc")
    saved = ml.read_snapshot(path, "fc")
    assert {key: saved[key] for key in metadata} == metadata


def test_carry_forward_adds_no_keys(ml, home):
    ml.save_snapshot(home, result(), T0)
    path = ml.save_snapshot(home, result(version=6), T0 + timedelta(hours=1))
    saved = ml.read_snapshot(path)
    assert "published" not in saved and "current_version" not in saved


def test_page_failure_keeps_published(ml, home):
    metadata = {"published": {"date": "2026-01-01", "note": "synthetic"}, "current_version": "2.1"}
    path = ml.save_snapshot(home, {**result(version="2.0"), **metadata}, T0, "fc")
    assert ml.save_snapshot(home, {"not_modified": True}, T0 + timedelta(hours=1), "fc") == path
    saved = ml.read_snapshot(path, "fc")
    assert {key: saved[key] for key in metadata} == metadata


@pytest.mark.parametrize("changed", [False, True])
def test_page_without_changelog_clears_published(ml, home, changed):
    metadata = {"published": {"date": "2026-01-01", "note": "synthetic"}, "current_version": "2.1"}
    first = ml.save_snapshot(home, {**result(version="2.0"), **metadata}, T0, "fc")
    models = [model("Example (high)", 51, 1.0)] if changed else None
    path = ml.save_snapshot(home, {**result(models, version="2.0"), "published": None, "current_version": None}, T0 + timedelta(hours=1), "fc")
    assert (path != first) == changed
    saved = ml.read_snapshot(path, "fc")
    assert saved["published"] is None and saved["current_version"] is None


def test_maximum_changes_snapshot_identity(ml, home):
    ml.save_snapshot(home, {**result(), "index_maxima": {"intelligence": 100}}, T0)
    ml.save_snapshot(home, {**result(), "index_maxima": {"intelligence": 120}}, T0 + timedelta(hours=1))
    assert ml.read_snapshot(ml.load_snapshots(home)[0])["index_maxima"] == {"intelligence": 120}
    assert len(ml.load_snapshots(home)) == 2


def test_read_truncated_snapshot(ml, home):
    path = ml.save_snapshot(home, result(), T0)
    path.write_bytes(path.read_bytes()[:20])
    with pytest.raises(ml.StoreError) as info:
        ml.read_snapshot(path)
    assert str(path) in str(info.value)


@pytest.mark.parametrize("payload", [
    b"not gzip",
    gzip.compress(b"not json"),
    gzip.compress(b"[1]"),
    gzip.compress(json.dumps({"schema": 1}).encode()),
    gzip.compress(json.dumps({"schema": 2, "models": []}).encode()),
])
def test_read_bad_snapshots(ml, home, payload):
    path = home / "snapshots" / "20261101T120000Z.json.gz"
    path.parent.mkdir()
    path.write_bytes(payload)
    with pytest.raises(ml.StoreError, match="cannot read"):
        ml.read_snapshot(path)


def test_snapshot_directory_is_private(ml, home):
    path = ml.save_snapshot(home, result(), T0)
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_snapshot_directory_mode_is_fixed(ml, home):
    (home / "snapshots").mkdir()
    (home / "snapshots").chmod(0o755)
    ml.save_snapshot(home, result(), T0)
    assert (home / "snapshots").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("version", ["missing", "5", True, None, [5]])
def test_read_snapshot_needs_numeric_index_version(ml, home, version):
    data = {"schema": 1, "fetched_at": "2026-11-01T12:00:00+00:00",
            "last_checked": "2026-11-01T12:00:00+00:00", "rate_limit": RATE, "models": []}
    if version != "missing":
        data["index_version"] = version
    path = home / "snapshots" / "20261101T120000Z.json.gz"
    path.parent.mkdir()
    path.write_bytes(gzip.compress(json.dumps(data).encode()))
    with pytest.raises(ml.StoreError, match="index_version") as info:
        ml.read_snapshot(path)
    assert str(path) in str(info.value)
