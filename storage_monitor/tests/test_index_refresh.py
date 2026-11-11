import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import load_launcher

SCRIPT = Path(__file__).resolve().parents[1] / "storage_monitor"


@pytest.fixture
def indexed_tree(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT)
    module.ensure_runtime_dirs()
    root = (tmp_path / "root").resolve()
    for directory in (root / "a/b", root / "a/owner", root / "c", root / "d"):
        directory.mkdir(parents=True)
    (root / "a/b/f").write_bytes(b"a" * 8192)
    owner = root / "a/owner/hl"
    owner.write_bytes(b"b" * 16384)
    os.link(owner, root / "c/twin")
    (root / "d/plain").write_bytes(b"c" * 4096)
    monkeypatch.setattr(module, "DATA_VOLUME", root)
    monkeypatch.setitem(module.ROOT_PATHS, "data_root", root)
    monkeypatch.setattr(module, "ALLOWED_BREAKDOWN_ROOTS", [root])
    monkeypatch.setattr(module, "iso_now", lambda: "2026-01-01T00:00:00Z")
    scan_id = module.create_scan_run(module.iso_now())
    result, totals, changes = module.walk_with_ownership(root, scan_id=scan_id, excluded_paths=[])
    module.persist_full_walk(scan_id, result, totals, module.build_walk_translation(), changes)
    module.finalize_scan_run(scan_id, {})
    return module, root, scan_id


def node(module, scan_id, path):
    with module.open_db_connection() as connection:
        row = connection.execute("SELECT allocated_bytes FROM nodes WHERE scan_id=? AND path=?", (scan_id, str(path))).fetchone()
    assert row is not None, f"missing node: {path}"
    return row[0]


def du(path):
    return int(subprocess.check_output(["du", "-xsk", str(path)], text=True).split()[0]) * 1024


def test_subtree_refresh_tracks_growth(indexed_tree):
    module, root, scan_id = indexed_tree
    assert node(module, scan_id, root) == du(root)
    (root / "a/b/growth").write_bytes(b"d" * 65536)
    module.walk_subtree_and_store(scan_id, root / "a/b")
    assert node(module, scan_id, root) == du(root)
    assert node(module, scan_id, root / "a/b") == du(root / "a/b")
    with module.open_db_connection() as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM nodes WHERE scan_id=? ORDER BY path", (scan_id,))]
    module.walk_subtree_and_store(scan_id, root / "a/b")
    with module.open_db_connection() as connection:
        after = [tuple(row) for row in connection.execute("SELECT * FROM nodes WHERE scan_id=? ORDER BY path", (scan_id,))]
    assert after == before


def test_file_count_and_newest_time_refresh(indexed_tree):
    module, root, scan_id = indexed_tree
    paths = [root, *root.rglob("*")]
    expected_files = sum(path.is_file() for path in paths)
    expected_time = max(int(os.lstat(path).st_mtime) for path in paths)
    before = module.fetch_breakdown_from_db(scan_id, str(root))
    assert before["file_count"] == expected_files == 4
    assert before["newest_mtime"] == expected_time
    target = root / "a/b/f"
    os.utime(target, (2000000000, 2000000000))
    (root / "a/b/new").write_bytes(b"synthetic")
    module.walk_subtree_and_store(scan_id, root / "a/b")
    for directory in (root, root / "a", root / "a/b"):
        row = module.fetch_breakdown_from_db(scan_id, str(directory))
        assert row["newest_mtime"] >= 2000000000
    assert module.fetch_breakdown_from_db(scan_id, str(root))["file_count"] == expected_files + 1


def test_old_schema_migrates_with_unknown_time(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT)
    module.ensure_runtime_dirs()
    with module.open_db_connection() as connection:
        connection.execute("DROP TABLE nodes")
        connection.execute("CREATE TABLE nodes (scan_id INTEGER NOT NULL, path TEXT NOT NULL, parent_path TEXT, name TEXT NOT NULL, root_key TEXT NOT NULL, depth INTEGER NOT NULL, allocated_bytes INTEGER NOT NULL, children_indexed INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, PRIMARY KEY (scan_id,path))")
        connection.execute("INSERT INTO nodes VALUES (1, '/synthetic', NULL, 'synthetic', 'data_root', 0, 1, 1, 'now')")
    module.initialize_scan_db(module.RUNTIME_PATHS)
    row = module.fetch_breakdown_from_db(1, "/synthetic")
    assert row["file_count"] == 0 and row["newest_mtime"] is None


def test_refresh_replaces_only_errors_in_subtree(indexed_tree, monkeypatch):
    module, root, scan_id = indexed_tree
    refreshed = root / "a"
    with module.open_db_connection() as connection:
        connection.executemany("INSERT INTO scan_errors VALUES (?,?,?)", [
            (scan_id, str(refreshed / "old"), 13), (scan_id, str(root / "c/other"), 13)])
    original = module.walk_tree
    def walk(*args, **kwargs):
        result = original(*args, **kwargs)
        result.unreadable = [(str(refreshed / "new"), 13)]
        return result
    monkeypatch.setattr(module, "walk_tree", walk)
    module.walk_subtree_and_store(scan_id, refreshed)
    with module.open_db_connection() as connection:
        errors = {tuple(row) for row in connection.execute("SELECT path, errno FROM scan_errors WHERE scan_id=?", (scan_id,))}
    assert errors == {(str(refreshed / "new"), 13), (str(root / "c/other"), 13)}


def test_alias_preserves_indexed_count_and_time(indexed_tree):
    module, root, scan_id = indexed_tree
    target = root / "a"
    alias = root / "synthetic-alias"
    module.mark_alias_path_cached(scan_id, alias, target, "data_root")
    original = module.fetch_breakdown_from_db(scan_id, str(target))
    copied = module.fetch_breakdown_from_db(scan_id, str(alias))
    assert copied["file_count"] == original["file_count"]
    assert copied["newest_mtime"] == original["newest_mtime"]


def test_refresh_after_owner_removal_reassigns_twin(indexed_tree):
    module, root, scan_id = indexed_tree
    inode = (root / "a/owner/hl").stat().st_ino
    with module.open_db_connection() as connection:
        owner = connection.execute("SELECT owner_path FROM hardlink_inodes WHERE scan_id=? AND ino=?", (scan_id, inode)).fetchone()
    assert owner is not None and owner[0] == str(root / "a/owner/hl")
    shutil.rmtree(root / "a/owner")
    module.walk_subtree_and_store(scan_id, root / "a")
    module.walk_subtree_and_store(scan_id, root / "c")
    assert node(module, scan_id, root) == du(root)
    with module.open_db_connection() as connection:
        assert connection.execute("SELECT 1 FROM hardlink_inodes WHERE scan_id=? AND ino=?", (scan_id, inode)).fetchone() is None
        paths = [row[0] for row in connection.execute("SELECT path FROM nodes WHERE scan_id=?", (scan_id,))]
    assert not any(path == str(root / "a/owner") or path.startswith(str(root / "a/owner") + os.sep) for path in paths)


def test_trash_action_refreshes_index(indexed_tree, monkeypatch, caplog):
    module, root, scan_id = indexed_tree
    monkeypatch.setattr(module, "TRASH_DIR", root / ".Trash")
    monkeypatch.setattr(module, "collect_metadata", lambda: {})
    monkeypatch.setattr(module, "rebuild_and_publish_report", lambda *args: None)
    token = module.encode_action_token({"kind": "trash_path", "path": str(root / "d")})
    module.STATE.report = {"findings": {"items": [{"actionable": True, "action_token": token}]}}
    result = module.api_execute_action({"action_token": token})
    moved = Path(result["trash_path"])
    assert result["ok"] and moved.parent == root / ".Trash"
    assert not (root / "d").exists()
    with module.open_db_connection() as connection:
        assert connection.execute("SELECT 1 FROM nodes WHERE scan_id=? AND path=?", (scan_id, str(root / "d"))).fetchone() is None
    assert node(module, scan_id, root) == du(root)
    assert node(module, scan_id, moved) == du(moved)
    records = [json.loads(line) for line in module.RUNTIME_PATHS.action_log.read_text().splitlines()]
    assert len(records) == 1 and records[0]["payload"]["path"] == str(root / "d")
    assert "Immediate post-action refresh failed" not in caplog.text


def test_walk_translation_maps_data_volume_aliases(monkeypatch, tmp_path):
    module = load_launcher(SCRIPT)
    data, home, apps = tmp_path / "Data", tmp_path / "Users/synthetic-user", tmp_path / "Applications"
    data_home, data_apps = data / "Users/synthetic-user", data / "Applications"
    for directory in (data_home, data_apps, home, apps):
        directory.mkdir(parents=True)
    monkeypatch.setattr(module, "DATA_VOLUME", data)
    monkeypatch.setattr(module, "HOME_DIR", home)
    monkeypatch.setattr(module, "APPLICATIONS_DIR", apps)
    monkeypatch.setattr(module, "samefile_or_false", lambda left, right: (left, right) in {(data_home, home), (data_apps, apps)})
    translation = module.build_walk_translation()
    for source, expected in [
        (data_home / "x", (str(home / "x"), "home_root")),
        (data_home, (str(home), "home_root")),
        (data / "Users/synthetic-user2/x", (str(data / "Users/synthetic-user2/x"), "data_root")),
        (data_apps / "A.app", (str(apps / "A.app"), "applications_root")),
        (data / "other", (str(data / "other"), "data_root")),
    ]:
        assert module.translate_walk_path(str(source), translation) == expected
