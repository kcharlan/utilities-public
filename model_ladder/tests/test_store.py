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


def test_unchanged_fetch_refreshes_published_and_etag(ml, home):
    path = ml.save_snapshot(home, {**result(), "etag": "old", "published": None}, T0)
    ml.save_snapshot(home, {**result(), "etag": "new", "published": {"date": "2026-01-01", "note": "synthetic"}}, T0 + timedelta(hours=1))
    assert ml.read_snapshot(path)["etag"] == "new"
    assert ml.read_snapshot(path)["published"]["note"] == "synthetic"
    assert len(ml.load_snapshots(home)) == 1


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
