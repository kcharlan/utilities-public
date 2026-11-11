from __future__ import annotations

import plistlib
import json
import os
import socket
import signal
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "storage_monitor"


def test_config_adds_watchlist_and_ignores_descendants(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    target = home / "synthetic-watch"
    target.mkdir(parents=True)
    config = {"watchlist": [{"slug": "synthetic", "label": "Synthetic", "path": "~/synthetic-watch", "category": "user_data", "risk": "high", "description": "Synthetic", "actionable": False, "cleanup_kind": None}], "ignore_paths": ["~/synthetic-watch"], "stale_days": {}}
    (module.RUNTIME_PATHS.home / "config.json").write_text(json.dumps(config))
    assert any(item["label"] == "Synthetic" for item in module.scan_watchlist()["items"])
    result = module.build_findings_section(module.scan_watchlist()["items"], discovered=[])
    assert all(item["path"] != str(target) for item in result["items"])
    assert result["ignored"] >= 1


def test_config_protects_runtime_and_recovers_from_malformed_json(monkeypatch, tmp_path, caplog):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    module.ensure_runtime_dirs()
    config_path = module.RUNTIME_PATHS.home / "config.json"
    assert config_path.stat().st_mode & 0o777 == 0o600
    protected = home / ".claude/synthetic"
    protected.mkdir(parents=True)
    config_path.write_text(json.dumps({"watchlist": [{"slug": "synthetic", "label": "Synthetic", "path": str(protected), "category": "user_data", "risk": "low", "description": "Synthetic", "actionable": True, "cleanup_kind": "trash_path"}]}))
    assert module.load_config()["watchlist"][0]["actionable"] is False
    assert not any(item["path"] == str(protected) for item in module.scan_watchlist()["items"])
    config_path.write_text(json.dumps({"watchlist": [{"slug": "synthetic", "label": "Synthetic", "path": str(home / "synthetic"), "category": "user_data", "risk": "low", "description": "Synthetic", "actionable": True}]}))
    assert module.load_config()["watchlist"][0]["actionable"] is False
    config_path.write_text("{")
    assert module.load_config()["watchlist"] == []
    assert "Invalid Storage Monitor config" in caplog.text
    assert "Invalid Storage Monitor config" in module.api_state()["config_warning"]


def test_config_stale_override_changes_discovery(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    monkeypatch.setattr(module, "DISCOVERY_RULES", [{"id": "synthetic_rule", "category": "dev_artifact", "names": ["synthetic-artifact"], "scope": "home_root", "min_bytes": 1, "action": "when_stale", "stale_days": 30, "risk": "low"}])
    scan_id = _insert_scan(module)
    artifact = home / "synthetic-artifact"
    _index_dirs(module, scan_id, [(artifact, 120)])
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=? AND path=?", (int(time.time()) - 10 * 86400, scan_id, str(artifact)))
    (module.RUNTIME_PATHS.home / "config.json").write_text(json.dumps({"stale_days": {"synthetic_rule": 5}}))
    assert module.discover_candidates(scan_id)[0]["stale"] is True


def test_ignore_outside_home_preserves_other_settings(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    ignored = tmp_path / "synthetic-external" / "child"
    config = {"ignore_paths": [str(ignored.parent)], "stale_days": {"synthetic": 5}, "watchlist": [{"slug": "synthetic", "label": "Synthetic", "path": str(home / "synthetic"), "category": "user_data", "risk": "high", "description": "Synthetic", "actionable": False, "cleanup_kind": None}]}
    (module.RUNTIME_PATHS.home / "config.json").write_text(json.dumps(config))
    loaded = module.load_config()
    assert len(loaded["watchlist"]) == 1 and loaded["stale_days"] == {"synthetic": 5}
    finding = {"path": str(ignored), "category": "temp", "allocated_bytes": 7}
    result = module.build_findings_section([], discovered=[finding])
    assert result["items"] == [] and result["ignored"] == 1


def test_ignore_hides_group_children_beyond_display_limit(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    (module.RUNTIME_PATHS.home / "config.json").write_text(json.dumps({"ignore_paths": ["~/synthetic-ignore"]}))
    children = [{"path": str(home / f"synthetic-{index}"), "allocated_bytes": 10} for index in range(10)]
    children.append({"path": str(home / "synthetic-ignore/child"), "allocated_bytes": 7})
    group = {"group": True, "path": None, "category": "dev_artifact", "label": "Synthetic group", "count": 11, "allocated_bytes": 107, "items": children}
    result = module.build_findings_section([], discovered=[group])
    assert result["ignored"] == 1
    assert result["items"][0]["count"] == 10
    assert result["items"][0]["allocated_bytes"] == 100
    assert len(result["items"][0]["items"]) == 10


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT_PATH)
    module.ensure_runtime_home(module.RUNTIME_PATHS)
    module.initialize_scan_db(module.RUNTIME_PATHS)
    return module


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [("6.8", "GB", 6_800_000_000), ("1.173", "GB", 1_173_000_000),
     ("0", "B", 0), ("34.6", "MB", 34_600_000)],
)
def test_parse_size_token(monkeypatch, tmp_path, value, unit, expected):
    module = load(monkeypatch, tmp_path)
    assert module.parse_size_token(value, unit) == expected
    with pytest.raises(ValueError):
        module.parse_size_token("1", "XB")


def test_brew_and_docker_probe_parsers(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    assert module.parse_brew_cleanup_estimate(
        "==> This operation would free approximately 6.8GB of disk space.\n"
    ) == 6_800_000_000
    assert module.parse_brew_cleanup_estimate("Nothing to do") is None
    docker = "\n".join([
        '{"Type":"Images","Reclaimable":"1.173GB (48%)"}',
        '{"Type":"Containers","Reclaimable":"0B"}',
        '{"Type":"Local Volumes","Reclaimable":"16.24MB (4%)"}',
        '{"Type":"Build Cache","Reclaimable":"0B"}',
        "malformed",
    ])
    assert module.parse_docker_reclaim_estimate(docker) == 1_173_000_000


def test_uv_provider_uses_index_and_missing_row_is_valid(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    scan_id = module.create_scan_run(module.iso_now())
    cache = tmp_path / "uv-cache"
    cache.mkdir()
    module.upsert_node_rows(scan_id, [{
        "path": str(cache), "parent_path": str(cache.parent), "name": cache.name,
        "root_key": "home_root", "depth": 2, "allocated_bytes": 1234,
        "children_indexed": True, "updated_at": module.iso_now(),
    }])
    monkeypatch.setattr(module.shutil, "which", lambda binary: "/bin/uv")
    monkeypatch.setattr(module, "run_command", lambda *a, **k: {
        "ok": True, "stdout": str(cache), "stderr": "", "duration_ms": 1,
    })
    assert module.probe_provider(scan_id, "uv-cache")["estimate_bytes"] == 1234
    monkeypatch.setattr(module, "run_command", lambda *a, **k: {
        "ok": True, "stdout": str(tmp_path / "missing-cache"), "stderr": "", "duration_ms": 1,
    })
    result = module.probe_provider(scan_id, "uv-cache")
    assert result["available"] is True
    assert result["estimate_bytes"] is None
    assert result["execution"] == "manual"
    assert result["action_token"] is None
    assert result["manual_command"] == "uv cache prune"
    with pytest.raises(HTTPException) as error:
        module.execute_provider("uv-cache")
    assert error.value.status_code == 400


def test_provider_token_must_be_in_report(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    token = module.encode_action_token({"kind": "provider_execute", "slug": "brew-cleanup"})
    module.STATE.report = {"providers": {"items": [{"action_token": token}]}}
    assert module.resolve_action(token)["slug"] == "brew-cleanup"
    forged = module.encode_action_token({"kind": "provider_execute", "slug": "docker-prune"})
    with pytest.raises(HTTPException) as error:
        module.resolve_action(forged)
    assert error.value.status_code == 400
    manual = module.encode_action_token({"kind": "provider_execute", "slug": "uv-cache"})
    with pytest.raises(HTTPException) as error:
        module.resolve_action(manual)
    assert error.value.status_code == 400


def test_provider_execution_and_targeted_refresh(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    module.STATE.report = {"providers": {"items": [{"slug": "brew-cleanup", "estimate_bytes": 99}]}}
    seen = []
    monkeypatch.setattr(module, "run_command", lambda args, timeout=0: (
        seen.append((args, timeout)) or {"ok": True, "stdout": "pruned", "stderr": ""}
    ))
    monkeypatch.setattr(module, "measure_free_space_delta", lambda operation: (operation(), 12))
    result = module.execute_provider("brew-cleanup")
    assert seen == [(["brew", "cleanup"], 600)]
    assert result["estimated_reclaim_bytes"] == 99
    assert result["observed_reclaimed_bytes"] == 12
    monkeypatch.setattr(module, "fetch_active_scan_id", lambda: 7)
    monkeypatch.setattr(module, "collect_metadata", lambda: {})
    monkeypatch.setattr(module, "rebuild_and_publish_report", lambda scan_id, metadata, provider_slug=None: provider_slug)
    assert module.refresh_after_action({"kind": "provider_execute", "slug": "brew-cleanup"}, result) == "brew-cleanup"


def test_snapshot_plist_and_tmutil_fallback(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    name = "com.apple.TimeMachine.2026-07-12-120000.local"
    payload = plistlib.dumps({"Snapshots": [{
        "SnapshotName": name, "SnapshotUUID": "uuid", "SnapshotXID": 42,
        "Purgeable": True, "LimitingContainerShrink": True,
    }]})
    parsed = module.parse_snapshot_plist(payload)
    assert parsed == [{"snapshot_name": name, "uuid": "uuid", "xid": 42,
                       "purgeable": True, "limiting_container_shrink": True}]
    calls = iter([
        {"ok": False, "stdout": "", "stderr": "failed", "duration_ms": 1},
        {"ok": True, "stdout": f"Snapshots for volume group /:\n{name}\n", "stderr": "", "duration_ms": 1},
    ])
    monkeypatch.setattr(module, "run_command", lambda *a, **k: next(calls))
    item = module.collect_snapshot_section()["items"][0]
    assert item["snapshot_name"] == name
    assert item["purgeable"] is None


@pytest.mark.parametrize(("token", "expected"), [
    ("2030-01-15-123456", "2030-01-15T17:34:56+00:00"),
    ("2030-07-15-123456", "2030-07-15T16:34:56+00:00"),
])
def test_snapshot_date_uses_local_offset_at_creation(monkeypatch, tmp_path, token, expected):
    module = load(monkeypatch, tmp_path)
    payload = plistlib.dumps({"Snapshots": [
        {"SnapshotName": f"com.apple.TimeMachine.{token}.local"},
    ]}).decode("utf-8")
    monkeypatch.setattr(module, "run_command", lambda *a, **k: {"ok": True, "stdout": payload})

    try:
        with monkeypatch.context() as timezone_env:
            timezone_env.setenv("TZ", "America/New_York")
            time.tzset()
            item = module.collect_snapshot_section()["items"][0]
    finally:
        time.tzset()

    assert item["parsed_date"] == expected
    assert item["token"] == token


def test_measured_reclaim_and_metadata_failure(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    values = iter([{"container_free_bytes": 100}, {"container_free_bytes": 175}])
    monkeypatch.setattr(module, "collect_metadata", lambda: next(values))
    result, delta = module.measure_free_space_delta(lambda: "ok")
    assert (result, delta) == ("ok", 75)
    monkeypatch.setattr(module, "collect_metadata", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert module.measure_free_space_delta(lambda: "ok") == ("ok", None)


def test_thin_endpoint_validation_and_command(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    for payload in ({"bytes": 0}, {"bytes": 1, "urgency": 5}):
        with pytest.raises(HTTPException):
            module.api_thin_snapshots(payload)
    seen = []
    monkeypatch.setattr(module, "collect_metadata", lambda: {"container_free_bytes": 100})
    monkeypatch.setattr(module, "fetch_active_scan_id", lambda: None)
    monkeypatch.setattr(module, "record_action", lambda *a: None)
    monkeypatch.setattr(module, "run_command", lambda args, timeout=0: (
        seen.append(args) or {"ok": True, "stdout": "com.apple.TimeMachine.2026-01-01-000000.local\n", "stderr": ""}
    ))
    result = module.api_thin_snapshots({"bytes": 1000, "urgency": 3})
    assert seen == [["tmutil", "thinlocalsnapshots", "/", "1000", "3"]]
    assert len(result["thinned"]) == 1


def _insert_scan(module, *, active=False):
    scan_id = module.create_scan_run(module.iso_now())
    if active:
        with module.open_db_connection() as connection:
            connection.execute("UPDATE scan_runs SET active=1, status='completed' WHERE id=?", (scan_id,))
            connection.commit()
    return scan_id


def test_growth_capture_prunes_nodes_after_history(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    old = _insert_scan(module)
    current = _insert_scan(module)
    for scan_id in (old, current):
        module.upsert_node_rows(scan_id, [
            {"path": f"/root-{scan_id}", "parent_path": "/", "name": "root", "root_key": "data_root", "depth": 1, "allocated_bytes": 1, "children_indexed": True, "updated_at": module.iso_now()},
            {"path": f"/keep-{scan_id}", "parent_path": "/", "name": "keep", "root_key": "data_root", "depth": 5, "allocated_bytes": module.GROWTH_HISTORY_MIN_BYTES, "children_indexed": True, "updated_at": module.iso_now()},
            {"path": f"/drop-{scan_id}", "parent_path": "/", "name": "drop", "root_key": "data_root", "depth": 5, "allocated_bytes": 1, "children_indexed": True, "updated_at": module.iso_now()},
        ])
    module.finalize_scan_run(current, {})
    with module.open_db_connection() as connection:
        paths = {row[0] for row in connection.execute("SELECT path FROM scan_dir_history WHERE scan_id=?", (current,))}
        old_nodes = connection.execute("SELECT COUNT(*) FROM nodes WHERE scan_id=?", (old,)).fetchone()[0]
    assert paths == {f"/root-{current}", f"/keep-{current}"}
    assert old_nodes == 0


def test_growth_join_statuses_and_order(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    baseline = _insert_scan(module)
    current = _insert_scan(module, active=True)
    rows = [
        (baseline, "/grown", 10), (current, "/grown", 40),
        (baseline, "/shrunk", 50), (current, "/shrunk", 40),
        (current, "/new", 20), (baseline, "/removed", 15),
        (baseline, "/same", 5), (current, "/same", 5),
    ]
    with module.open_db_connection() as connection:
        connection.executemany(
            "INSERT INTO scan_dir_history VALUES (?, ?, ?, 'home_root', 2, ?)",
            [(scan_id, module.iso_now(), path, size) for scan_id, path, size in rows],
        )
        connection.commit()
    report = module.build_growth_report(baseline)
    assert [item["path"] for item in report["items"]] == ["/grown", "/new", "/removed", "/shrunk"]
    assert {item["path"]: item["status"] for item in report["items"]} == {
        "/grown": "changed", "/new": "new", "/removed": "removed", "/shrunk": "changed"
    }


def test_growth_history_retains_sixty_scans(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    scan_ids = [_insert_scan(module) for _ in range(61)]
    with module.open_db_connection() as connection:
        connection.executemany(
            "INSERT INTO scan_dir_history VALUES (?, ?, ?, 'data_root', 1, 1)",
            [(scan_id, module.iso_now(), f"/scan-{scan_id}") for scan_id in scan_ids[:-1]],
        )
        connection.commit()
    latest = scan_ids[-1]
    module.upsert_node_rows(latest, [{
        "path": "/latest", "parent_path": "/", "name": "latest", "root_key": "data_root",
        "depth": 1, "allocated_bytes": 1, "children_indexed": True, "updated_at": module.iso_now(),
    }])
    module.finalize_scan_run(latest, {})
    with module.open_db_connection() as connection:
        retained = connection.execute("SELECT COUNT(DISTINCT scan_id) FROM scan_dir_history").fetchone()[0]
        oldest = connection.execute("SELECT MIN(scan_id) FROM scan_dir_history").fetchone()[0]
    assert retained == 60
    assert oldest == scan_ids[1]


def test_cache_discovery_watchlist_bundle_and_dedup(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(module, "HOME_DIR", home)
    monkeypatch.setattr(module, "TRASH_DIR", home / ".Trash")
    scan_id = _insert_scan(module)
    paths = [
        (home / "Library/Caches", "Caches", 200),
        (home / "Library/Caches/Google", "Google.cache", 300),
        (home / "Library/Caches/Homebrew/Caches", "Caches", 400),
        (home / "work/Caches", "Caches", 500),
        (home / "work/Caches/child.cache", "child.cache", 200),
        (home / "Photos.photoslibrary/.cache", ".cache", 600),
    ]
    module.WATCHLIST_SPECS = [
        {"path": "~/Library/Caches", "actionable": False},
        {"path": "~/Library/Caches/Homebrew", "actionable": True},
    ]
    monkeypatch.setattr(module, "expand_path", lambda value: Path(str(value).replace("~", str(home))).resolve())
    module.upsert_node_rows(scan_id, [{
        "path": str(path), "parent_path": str(path.parent), "name": name,
        "root_key": "home_root", "depth": len(path.parts),
        "allocated_bytes": size * 1024 * 1024, "children_indexed": True,
        "updated_at": module.iso_now(),
    } for path, name, size in paths])
    findings = module.discover_cache_candidates(scan_id)
    assert {item["path"] for item in findings} == {
        str(home / "Library/Caches/Google"), str(home / "work/Caches")
    }
    assert {item["risk"] for item in findings} == {"low", "medium"}


def _discovery_home(module, monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(module, "HOME_DIR", home)
    monkeypatch.setattr(module, "TRASH_DIR", home / ".Trash")
    monkeypatch.setattr(module, "expand_path", lambda value: Path(str(value).replace("~", str(home))).resolve())
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    return home


def _index_dirs(module, scan_id, entries):
    module.upsert_node_rows(scan_id, [{
        "path": str(path), "parent_path": str(path.parent), "name": path.name,
        "root_key": "home_root", "depth": len(path.parts),
        "allocated_bytes": size * 1024 * 1024, "children_indexed": True,
        "updated_at": module.iso_now(),
    } for path, size in entries])


def test_size_only_homes_never_expose_or_move_children(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    monkeypatch.setattr(module, "DATA_VOLUME", tmp_path)
    root = home / ".claude"
    child = root / "project" / "node_modules"
    child.mkdir(parents=True)
    (child.parent / "package.json").touch()
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [(root, 120), (child, 120)])
    findings = module.discover_candidates(scan_id)
    assert [item["path"] for item in findings if item.get("path", "").startswith(str(root))] == [str(root)]
    assert not next(item for item in findings if item["path"] == str(root))["actionable"]
    many = [{"path": str(home / f"synthetic-{i}"), "label": str(i), "category": "agent_residue", "allocated_bytes": 999999999} for i in range(81)]
    retained = module.build_findings_section([], discovered=[*findings, *many])["items"]
    assert any(item["path"] == str(root) for item in retained)
    with pytest.raises(HTTPException):
        module.execute_trash_path(child)
    assert module.cleanup_protection_reason(module.RUNTIME_PATHS.home.parent) is not None
    spec = {"path": "~/.claude/project/node_modules", "slug": "synthetic", "label": "Synthetic", "category": "cache", "risk": "low", "cleanup_kind": "trash_path", "description": "Synthetic", "actionable": True}
    assert module.scan_watchlist_entry(spec, scan_id)["exists"] is False


def test_temp_groups_recheck_entries_and_continue_after_refusal(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    root.mkdir()
    monkeypatch.setattr(module, "temp_roots", lambda: [root])
    monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "trash")
    monkeypatch.setattr(module, "DATA_VOLUME", tmp_path)
    old = int(time.time()) - 4 * 86400
    for name in ("old", "freshened", "refused", "com.apple.synthetic", "fresh"):
        path = root / name
        path.write_text("synthetic")
        os.utime(path, (old, old))
    os.utime(root / "fresh", None)
    os.mkfifo(root / "synthetic-fifo")
    (root / "TemporaryItems").write_text("synthetic")
    os.utime(root / "TemporaryItems", (old, old))
    assert module.temp_findings(None)[0]["stale"] is True
    sock = socket.socket(socket.AF_UNIX)
    monkeypatch.chdir(root)
    sock.bind("socket")
    try:
        scan_id = _insert_scan(module)
        group = module.temp_findings(scan_id)[0]
        assert group["count"] == 3
        os.utime(root / "freshened", None)
        real_rename = os.rename
        def rename(source, destination):
            if Path(source).name == "refused":
                raise PermissionError("synthetic refusal")
            real_rename(source, destination)
        monkeypatch.setattr(module.os, "rename", rename)
        result = module.execute_trash_group(module.decode_action_token(group["action_token"]))
        assert result["moved_count"] == 1 and len(result["failures"]) == 1
        assert (root / "freshened").exists() and (root / "refused").exists()
        assert not (root / "old").exists()
        module.record_action(module.decode_action_token(group["action_token"]), result)
        log = module.RUNTIME_PATHS.action_log.read_text()
        assert len(log.splitlines()) == 1 and str(root / "refused") not in log and str(root / "old") not in log
    finally:
        sock.close()


def test_temp_group_ignores_hidden_child_and_bulk_action_rechecks_config(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    _discovery_home(module, monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    root.mkdir()
    monkeypatch.setattr(module, "temp_roots", lambda: [root])
    monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "synthetic-trash")
    monkeypatch.setattr(module, "DATA_VOLUME", tmp_path / "synthetic-data")
    old = int(time.time()) - 4 * 86400
    for index in range(21):
        path = root / f"synthetic-{index:02}"
        path.write_bytes(b"x" * (8192 if index < 20 else 1))
        os.utime(path, (old, old))
    hidden = root / "synthetic-20"
    unfiltered = module.temp_findings(None)[0]
    assert unfiltered["count"] == 21 and len(unfiltered["items"]) == 20
    assert all(item["path"] != str(hidden) for item in unfiltered["items"])
    config_path = module.RUNTIME_PATHS.home / "config.json"
    config_path.write_text(json.dumps({"ignore_paths": [str(hidden)]}))
    scan_id = _insert_scan(module, active=True)
    result = module.build_findings_section([], scan_id, discovered=[])
    group = next(item for item in result["items"] if item["category"] == "temp")
    expected_bytes = sum((root / f"synthetic-{index:02}").stat().st_blocks * 512 for index in range(20))
    assert result["ignored"] == 1
    assert group["count"] == 20 and group["allocated_bytes"] == expected_bytes
    assert len(group["items"]) == 20 and all(item["path"] != str(hidden) for item in group["items"])
    newly_ignored = root / "synthetic-00"
    config_path.write_text(json.dumps({"ignore_paths": [str(hidden), str(newly_ignored)]}))
    action_result = module.execute_trash_group(module.decode_action_token(group["action_token"]))
    assert action_result["moved_count"] == 19
    assert hidden.exists() and newly_ignored.exists()


@pytest.mark.parametrize("configured_ignore", [False, True])
def test_unresolvable_temp_symlink_does_not_abort_report_or_action(monkeypatch, tmp_path, configured_ignore):
    module = load(monkeypatch, tmp_path)
    _discovery_home(module, monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    root.mkdir()
    loop = root / "synthetic-loop"
    loop.symlink_to(loop.name)
    candidate = root / "synthetic-old"
    candidate.write_text("synthetic")
    old = int(time.time()) - 4 * 86400
    os.utime(candidate, (old, old))
    monkeypatch.setattr(module, "temp_roots", lambda: [root])
    monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "synthetic-trash")
    monkeypatch.setattr(module, "DATA_VOLUME", tmp_path / "synthetic-data")
    if configured_ignore:
        (module.RUNTIME_PATHS.home / "config.json").write_text(json.dumps({"ignore_paths": [str(root / "synthetic-unrelated")]}))
    original_resolve = Path.resolve
    def resolve_with_legacy_loop_error(path, *args, **kwargs):
        if path == loop:
            raise RuntimeError("synthetic symlink loop")
        return original_resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolve_with_legacy_loop_error)
    scan_id = _insert_scan(module, active=True)
    report = module.build_findings_section([], scan_id, discovered=[])
    group = next(item for item in report["items"] if item["category"] == "temp")
    assert group["count"] == 1
    assert group["other_count"] == (0 if configured_ignore else 1)
    result = module.execute_trash_group(module.decode_action_token(group["action_token"]))
    assert result["moved_count"] == 1 and not candidate.exists()
    assert loop.is_symlink()


def test_temp_group_rejects_unknown_root_and_removes_empty_destination(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    root.mkdir()
    monkeypatch.setattr(module, "temp_roots", lambda: [root])
    monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "trash")
    token = {"kind": "trash_group", "rule": "temp_old", "root": str(root), "min_age_days": 3}
    result = module.execute_trash_group(token)
    assert result["moved_count"] == 0
    assert list(module.TRASH_DIR.iterdir()) == []
    with pytest.raises(HTTPException):
        module.execute_trash_group({**token, "root": str(tmp_path)})


def test_temp_directory_requires_indexed_age_and_current_owner(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    root.mkdir()
    directory = root / "synthetic-directory"
    directory.mkdir()
    old = int(time.time()) - 4 * 86400
    os.utime(directory, (old, old))
    data = tmp_path / "synthetic-data-volume"
    monkeypatch.setattr(module, "DATA_VOLUME", data)
    scan_id = _insert_scan(module)
    assert not module.temp_entries(root, scan_id)[0]["old"]
    indexed = data / str(directory).lstrip("/")
    _index_dirs(module, scan_id, [(indexed, 1)])
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=? AND path=?", (old, scan_id, str(indexed)))
        connection.commit()
    assert module.temp_entries(root, scan_id)[0]["old"]
    monkeypatch.setattr(module.os, "getuid", lambda: directory.stat().st_uid + 1)
    assert not module.temp_entries(root, scan_id)[0]["old"]


def test_temp_group_preserves_directory_when_existing_nested_file_was_edited(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    directory = root / "synthetic-entry"
    directory.mkdir(parents=True)
    payload = directory / "synthetic-file"
    payload.write_text("old synthetic content")
    old = int(time.time()) - 4 * 86400
    os.utime(payload, (old, old))
    os.utime(directory, (old, old))
    monkeypatch.setattr(module, "temp_roots", lambda: [root])
    monkeypatch.setattr(module, "DATA_VOLUME", tmp_path / "synthetic-data")
    monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "synthetic-trash")
    scan_id = _insert_scan(module, active=True)
    indexed = module.DATA_VOLUME / str(directory).lstrip("/")
    _index_dirs(module, scan_id, [(indexed, 1)])
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=? AND path=?", (old, scan_id, str(indexed)))
        connection.commit()
    group = module.temp_findings(scan_id)[0]
    assert group["count"] == 1
    payload.write_text("fresh synthetic content")
    result = module.execute_trash_group(module.decode_action_token(group["action_token"]))
    assert result["moved_count"] == 0 and payload.read_text() == "fresh synthetic content"


def test_enclosing_worktree_is_review_only_and_rechecked_before_moves(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    monkeypatch.setattr(module, "DATA_VOLUME", tmp_path)
    monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "synthetic-trash")
    workspace = home / "project/.superpowers"
    marker = workspace / ".worktrees"
    (marker / "synthetic-tree").mkdir(parents=True)
    old = int(time.time()) - 20 * 86400
    scan_id = _insert_scan(module, active=True)
    _index_dirs(module, scan_id, [(workspace, 1), (marker, 1)])
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=?", (old, scan_id))
        connection.commit()
    finding = next(item for item in module.discover_candidates(scan_id) if item["path"] == str(workspace))
    assert not finding["actionable"]
    spec = {"path": "~/project/.superpowers", "slug": "synthetic-workspace", "label": "Synthetic", "category": "cache", "risk": "low", "cleanup_kind": "trash_path", "description": "Synthetic", "actionable": True}
    assert not module.scan_watchlist_entry(spec, scan_id)["actionable"]
    with module.open_db_connection() as connection:
        connection.execute("DELETE FROM nodes WHERE scan_id=? AND path=?", (scan_id, str(marker)))
        connection.commit()
    with pytest.raises(HTTPException):
        module.execute_trash_path(workspace)
    assert marker.exists()


def test_temp_group_refuses_new_worktree_inside_old_directory(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    directory = root / "synthetic-entry"
    directory.mkdir(parents=True)
    old = int(time.time()) - 4 * 86400
    os.utime(directory, (old, old))
    monkeypatch.setattr(module, "temp_roots", lambda: [root])
    monkeypatch.setattr(module, "DATA_VOLUME", tmp_path / "synthetic-data")
    monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "synthetic-trash")
    scan_id = _insert_scan(module, active=True)
    indexed = module.DATA_VOLUME / str(directory).lstrip("/")
    _index_dirs(module, scan_id, [(indexed, 1)])
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=? AND path=?", (old, scan_id, str(indexed)))
        connection.commit()
    group = module.temp_findings(scan_id)[0]
    assert group["count"] == 1
    marker = directory / ".worktrees/synthetic-tree"
    marker.mkdir(parents=True)
    os.utime(marker, (old, old))
    os.utime(marker.parent, (old, old))
    os.utime(directory, (old, old))
    result = module.execute_trash_group(module.decode_action_token(group["action_token"]))
    assert result["moved_count"] == 0 and marker.exists()


def test_indexed_temp_worktree_makes_ancestor_review_only(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    directory = root / "synthetic-entry"
    marker = directory / ".worktrees/synthetic-tree"
    marker.mkdir(parents=True)
    old = int(time.time()) - 4 * 86400
    os.utime(directory, (old, old))
    data = tmp_path / "synthetic-data"
    monkeypatch.setattr(module, "DATA_VOLUME", data)
    monkeypatch.setattr(module, "temp_roots", lambda: [root])
    scan_id = _insert_scan(module)
    indexed = data / str(directory).lstrip("/")
    _index_dirs(module, scan_id, [(indexed, 1), (indexed / ".worktrees", 1)])
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=?", (old, scan_id))
        connection.commit()
    group = module.temp_findings(scan_id)[0]
    assert group["count"] == 0 and not group["actionable"]


def test_unverifiable_directory_is_not_moved(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    directory = root / "synthetic-entry"
    directory.mkdir(parents=True)
    old = int(time.time()) - 4 * 86400
    os.utime(directory, (old, old))
    monkeypatch.setattr(module, "DATA_VOLUME", tmp_path / "synthetic-data")
    monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "synthetic-trash")
    monkeypatch.setattr(module, "temp_roots", lambda: [root])
    scan_id = _insert_scan(module, active=True)
    indexed = module.DATA_VOLUME / str(directory).lstrip("/")
    _index_dirs(module, scan_id, [(indexed, 1)])
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=?", (old, scan_id))
        connection.commit()
    group = module.temp_findings(scan_id)[0]
    def fail_walk(*args, **kwargs):
        raise OSError("synthetic enumeration failure")
    monkeypatch.setattr(module, "walk_tree", fail_walk)
    result = module.execute_trash_group(module.decode_action_token(group["action_token"]))
    assert result["moved_count"] == 0 and result["failure_count"] == 1 and directory.exists()
    partial = module.WalkResult(dir_local={str(directory): 0}, hardlink_candidates=[], large_files=[], dir_count=1,
                                file_count=0, error_count=1, duration_ms=0, dir_mtime={str(directory): old},
                                unreadable=[(str(directory / "synthetic-unreadable"), 13)])
    monkeypatch.setattr(module, "walk_tree", lambda *args, **kwargs: partial)
    result = module.execute_trash_group(module.decode_action_token(group["action_token"]))
    assert result["moved_count"] == 0 and result["failure_count"] == 1 and directory.exists()
    with module.open_db_connection() as connection:
        connection.execute("INSERT INTO scan_errors (scan_id, path, errno) VALUES (?, ?, ?)",
                           (scan_id, str(indexed / "synthetic-unreadable"), 13))
        connection.commit()
    assert not module.temp_findings(scan_id)[0]["actionable"]


@pytest.mark.parametrize(("name", "expected"), [
    (".synthetic-task.aB3dEf", True), (".synthetic-task.abcdef", True),
    (".synthetic-review-aB3dEf9h", True), (".synthetic task.aB3dEf", True),
    (".synthetic-task.xY7zQ2", True), (".zshrc.backup", False),
    (".synthetic-review-abcdefgh", False), (".config", False),
])
def test_home_residue_name_cases_from_home_audit(monkeypatch, tmp_path, name, expected):
    module = load(monkeypatch, tmp_path)
    assert module.home_residue_name(name) is expected


def test_home_residue_reports_old_direct_entries_only(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    home.mkdir()
    stale = home / ".synthetic-task.abcdef"
    fresh = home / ".synthetic-review-aB3dEf9h"
    stale.write_text("synthetic")
    fresh.mkdir()
    old = time.time() - 2 * 86400
    os.utime(stale, (old, old))
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [(home, 1), (fresh, 1)])
    findings = module.additional_findings(scan_id)
    assert [item["path"] for item in findings] == [str(stale)]
    assert not findings[0]["actionable"] and findings[0]["age_days"] >= 1


def test_report_builder_uses_synthetic_temp_roots(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    scan_id = _insert_scan(module)
    findings = module.build_findings_section([], scan_id)["items"]
    groups = [item for item in findings if item.get("category") == "temp"]
    assert len(groups) == 1
    assert Path(groups[0]["path"]).name == "synthetic-user-temp"


def test_agent_residue_and_trash_are_reported_without_unsafe_actions(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    monkeypatch.setattr(module, "temp_roots", lambda: [])
    scan_id = _insert_scan(module)
    workspace = home / "project/.superpowers"
    tree = home / "project/.worktrees/synthetic-tree"
    trash = home / ".Trash"
    backup = home / "Library/Application Support/MobileSync/Backup/synthetic-backup"
    for path in (workspace, tree, trash, backup):
        path.mkdir(parents=True)
    _index_dirs(module, scan_id, [(workspace, 0), (tree, 1), (trash, 1), (backup, 1)])
    old = int(time.time()) - 15 * 86400
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=?", (old, scan_id))
        connection.commit()
    findings = module.build_findings_section([], scan_id)["items"]
    by_path = {item["path"]: item for item in findings}
    assert by_path[str(workspace)]["actionable"]
    assert not by_path[str(tree)]["actionable"]
    assert not by_path[str(backup)]["actionable"] and by_path[str(backup)]["risk"] == "high"
    assert not by_path[str(trash)]["actionable"]
    assert module.finding_summary({"items": findings})["trash_bytes"] == 1024 * 1024
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=? AND path=?", (int(time.time()), scan_id, str(workspace)))
        connection.commit()
    fresh = next(item for item in module.discover_candidates(scan_id) if item["path"] == str(workspace))
    assert not fresh["actionable"] and fresh["stale"] is False


@pytest.mark.parametrize(("relative", "marker", "marker_location"), [
    ("project/node_modules", "package.json", "sibling"),
    ("project/.venv", "pyvenv.cfg", "child"),
    ("project/venv", "pyvenv.cfg", "child"),
    ("project/.build", "Package.swift", "sibling"),
    ("project/target", "Cargo.toml", "sibling"),
    ("project/Pods", "Podfile", "sibling"),
    ("project/.next", "package.json", "sibling"),
    ("Library/Developer/Xcode/DerivedData/synthetic-project", None, None),
    (".gradle/caches", None, None),
])
def test_developer_artifact_requires_marker_and_staleness(monkeypatch, tmp_path, relative, marker, marker_location):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    path = home / relative
    path.mkdir(parents=True)
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [(path, 60)])
    now = int(module.time.time())
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=?", (now - 31 * 86400, scan_id))
        connection.commit()
    if marker:
        assert not any(item.get("path") == str(path) for item in module.discover_candidates(scan_id))
        (path.parent if marker_location == "sibling" else path).joinpath(marker).touch()
    finding = next(item for item in module.discover_candidates(scan_id) if item.get("path") == str(path))
    assert finding["actionable"] and finding["stale"] is True and finding["risk"] == "medium"
    assert "Rebuilt" in finding["description"]
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=?", (now, scan_id))
        connection.commit()
    finding = next(item for item in module.discover_candidates(scan_id) if item.get("path") == str(path))
    assert not finding["actionable"] and finding["stale"] is False


def test_developer_artifacts_deduplicate_and_respect_protection(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    outer = home / "project/node_modules"
    nested = outer / "synthetic/node_modules"
    protected = home / "Documents/project/node_modules"
    for path in (outer, nested, protected):
        path.mkdir(parents=True)
        (path.parent / "package.json").touch()
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [(outer, 100), (nested, 60), (protected, 60)])
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=?", (int(module.time.time()) - 31 * 86400, scan_id))
        connection.commit()
    findings = {item["path"]: item for item in module.discover_candidates(scan_id)}
    assert findings[str(outer)]["actionable"]
    assert str(nested) not in findings
    assert not findings[str(protected)]["actionable"]


def test_pycache_group_excludes_claimed_descendants(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    outer = home / "project/.venv"
    outer.mkdir(parents=True)
    (outer / "pyvenv.cfg").touch()
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [(outer, 100), (outer / "lib/__pycache__", 5),
                                  (home / "a/__pycache__", 2), (home / "b/__pycache__", 70),
                                  (home / "c/__pycache__", 0)])
    findings = module.discover_candidates(scan_id)
    groups = [item for item in findings if item.get("group") and item["category"] == "python_bytecode"]
    assert len(groups) == 1
    assert groups[0]["count"] == 3 and groups[0]["allocated_bytes"] == 72 * 1024 * 1024
    assert not groups[0]["actionable"] and not groups[0]["actions"]


def test_rule_discovery_names_bundles_and_small_groups(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [(home / name, size) for name, size in [
        ("work/cAcHe", 120), ("work/Code Cache", 130), ("work/notcache", 150),
        ("Library/Containers/synthetic.vendor.app/Data/Cache", 140),
        ("Synthetic.app/Contents/Cache", 160), ("small/GPUCache", 2),
    ]])
    findings = module.discover_candidates(scan_id)
    paths = {item.get("path") for item in findings}
    assert str(home / "work/cAcHe") in paths
    assert str(home / "work/Code Cache") in paths
    assert str(home / "Library/Containers/synthetic.vendor.app/Data/Cache") in paths
    assert str(home / "work/notcache") not in paths
    assert str(home / "Synthetic.app/Contents/Cache") not in paths
    group = next(item for item in findings if item.get("group"))
    assert group["count"] == 1 and group["allocated_bytes"] == 2 * 1024 * 1024
    assert group["items"][0]["path"] == str(home / "small/GPUCache")


def test_rule_markers_staleness_and_cross_rule_dedup(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    rules = [
        {"id": "outer", "category": "test", "label_prefix": "", "names": ["outer"], "scope": "home_root", "min_bytes": 1, "action": "when_stale", "stale_days": 10, "risk": "low", "review_risk": "medium", "marker": ("child", "marker")},
        {"id": "inner", "category": "test", "label_prefix": "", "names": ["inner"], "scope": "home_root", "min_bytes": 1, "action": "always", "risk": "low"},
    ]
    monkeypatch.setattr(module, "DISCOVERY_RULES", rules)
    scan_id = _insert_scan(module)
    paths = [home / "stale/outer", home / "fresh/outer", home / "unknown/outer", home / "missing/outer", home / "stale/outer/inner"]
    _index_dirs(module, scan_id, [(path, 120) for path in paths])
    for path in paths[:3]:
        path.mkdir(parents=True, exist_ok=True)
        (path / "marker").touch()
    now = int(module.time.time())
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=? AND path=?", (now - 11 * 86400, scan_id, str(paths[0])))
        connection.execute("UPDATE nodes SET newest_mtime=? WHERE scan_id=? AND path=?", (now, scan_id, str(paths[1])))
        connection.commit()
    findings = {item["path"]: item for item in module.discover_candidates(scan_id)}
    assert set(findings) == {str(path) for path in paths[:3]}
    assert findings[str(paths[0])]["actionable"] and findings[str(paths[0])]["stale"] is True
    assert not findings[str(paths[1])]["actionable"] and findings[str(paths[1])]["stale"] is False
    assert not findings[str(paths[2])]["actionable"] and findings[str(paths[2])]["stale"] is None


def test_findings_limit_is_per_category_and_reports_dropped_bytes(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "MAX_FINDINGS", 1)
    items = [{"category": category, "allocated_bytes": size, "estimated_reclaim_bytes": None} for category, size in [("a", 10), ("a", 5), ("b", 7), ("b", 3)]]
    result = module.build_findings_section([], discovered=items)
    assert [item["allocated_bytes"] for item in result["items"]] == [10, 7]
    assert result["truncated"] == {"a": {"count": 1, "bytes": 5}, "b": {"count": 1, "bytes": 3}}


def test_watchlist_findings_preserve_indexed_metadata(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    path = home / "synthetic-watch"
    path.mkdir(parents=True)
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [(path, 120)])
    with module.open_db_connection() as connection:
        connection.execute("UPDATE nodes SET file_count=7, newest_mtime=? WHERE scan_id=? AND path=?", (int(module.time.time()) - 86400, scan_id, str(path)))
        connection.commit()
    spec = {"path": "~/synthetic-watch", "slug": "synthetic", "label": "Synthetic", "category": "test", "risk": "low", "description": "Synthetic", "actionable": False, "cleanup_kind": None}
    item = module.scan_watchlist_entry(spec, scan_id)
    finding = module.build_findings_section([item], discovered=[])["items"][0]
    assert finding["file_count"] == 7
    assert finding["age_days"] == 1
    assert finding["stale"] is None


def test_path_rule_requires_sibling_marker_and_remains_review_only(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    monkeypatch.setattr(module, "DISCOVERY_RULES", [{"id": "fixed", "category": "test", "label_prefix": "", "paths": ["~/fixed"], "scope": "any", "min_bytes": 1, "marker": ("sibling", "marker"), "action": "never", "risk": "low", "review_risk": "high"}])
    scan_id = _insert_scan(module)
    path = home / "fixed/item"
    _index_dirs(module, scan_id, [(path, 120)])
    assert module.discover_candidates(scan_id) == []
    path.parent.mkdir(parents=True)
    (path.parent / "marker").touch()
    finding = module.discover_candidates(scan_id)[0]
    assert finding["path"] == str(path)
    assert finding["actionable"] is False and finding["risk"] == "high"


def test_small_nested_cache_does_not_hide_large_shared_entry(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    scan_id = _insert_scan(module)
    entry = home / ".cache/synthetic-app"
    _index_dirs(module, scan_id, [(entry, 200), (entry / "Cache", 2)])
    findings = module.discover_candidates(scan_id)
    assert any(item.get("path") == str(entry) and not item["actionable"] for item in findings)
    assert any(item.get("group") and item["count"] == 1 for item in findings)


def test_small_rule_match_uses_review_risk_and_neutral_description(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    monkeypatch.setattr(module, "DISCOVERY_RULES", [{"id": "synthetic", "category": "synthetic", "label_prefix": "", "names": ["artifact"], "scope": "home_root", "min_bytes": 100 * 1024 * 1024, "action": "always", "risk": "low", "review_risk": "high"}])
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [(home / "artifact", 2)])
    group = module.discover_candidates(scan_id)[0]
    item = group["items"][0]
    assert not item["actionable"] and item["risk"] == "high"
    assert "cache" not in item["description"].lower()
    assert "cache" not in group["label"].lower()


def test_null_time_cache_trashable_paths_match_baseline_plus_new_names(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [{"path": "~/managed", "actionable": True}])
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [(home / name, size) for name, size in [
        ("work/Cache", 120), ("work/Caches/child.cache", 110), ("work/Caches", 150),
        (".cache/synthetic/old.cache", 130), ("managed/Cache", 140),
        ("Synthetic.app/Contents/Cache", 160), ("small/Cache", 2),
        ("work/cAcHe", 170), ("work/GPUCache", 180), ("work/notcache", 190),
    ]])
    paths = {item["path"] for item in module.discover_candidates(scan_id) if item.get("actionable")}
    assert paths == {str(home / name) for name in ["work/Cache", "work/Caches", ".cache/synthetic/old.cache", "work/cAcHe", "work/GPUCache"]}


def test_shared_cache_folders_are_review_only_with_entries_listed(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    scan_id = _insert_scan(module)
    _index_dirs(module, scan_id, [
        (home / ".cache", 900),
        (home / ".cache/synthetic-prepared-data", 500),
        (home / ".cache/synthetic-small", 50),
        (home / ".cache/whisper", 300),
        (home / "Library/Caches", 2000),
        (home / "Library/Caches/synthetic-app", 400),
        (home / "Library/Caches/synthetic-browser", 700),
        (home / "Library/Caches/synthetic-browser/Default/Cache", 600),
    ])
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [
        {"path": "~/Library/Caches", "actionable": False},
        {"path": "~/.cache/whisper", "actionable": True},
    ])
    findings = {item["path"]: item for item in module.discover_cache_candidates(scan_id)}
    nested = str(home / "Library/Caches/synthetic-browser/Default/Cache")
    review_only = [str(home / relative) for relative in (
        ".cache", ".cache/synthetic-prepared-data", "Library/Caches/synthetic-app",
    )]
    assert set(findings) == {*review_only, nested}
    for path in review_only:
        assert findings[path]["actionable"] is False
        assert findings[path]["action_token"] is None
        assert [action["kind"] for action in findings[path]["actions"]] == ["reveal"]
    assert findings[nested]["actionable"] is True
    assert findings[nested]["risk"] == "low"


@pytest.mark.parametrize("relative", [
    "Library/Metadata/CoreSpotlight/index.spotlightV3/Cache",
    "Library/Containers/com.apple.Safari/Data/Library/Caches",
    "Library/Group Containers/group.com.apple.notes/Library/Caches",
    "Library/Messages/Caches",
    "Library/Mobile Documents/synthetic-app/Caches",
    "Library/CloudStorage/synthetic-drive/.cache",
    "Documents/synthetic-project/.cache",
    ".cache/uv/archive-v0/synthetic-package/Cache",
])
def test_cache_discovery_never_offers_protected_locations(monkeypatch, tmp_path, relative):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    scan_id = _insert_scan(module)
    third_party = home / "Library/Containers/synthetic.vendor.tool/Data/Library/Caches"
    _index_dirs(module, scan_id, [(home / relative, 300), (third_party, 300)])
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    findings = {item["path"]: item for item in module.discover_cache_candidates(scan_id)}
    protected = findings[str(home / relative)]
    assert protected["actionable"] is False
    assert protected["action_token"] is None
    assert protected["risk"] == "high"
    assert [action["kind"] for action in protected["actions"]] == ["reveal"]
    assert findings[str(third_party)]["actionable"] is True


def test_model_stores_and_extensions_are_review_only(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    stores = [home / ".lmstudio/models", home / ".ollama/models", home / ".vscode/extensions"]
    for store in stores:
        store.mkdir(parents=True)
        (store / "synthetic-payload").write_bytes(b"x" * 4096)
    findings = {
        item["path"]: item
        for item in module.build_findings_section(module.scan_watchlist()["items"])["items"]
    }
    # LM Studio is now size-only, so its model directory must not be listed.
    assert str(stores[0]) not in findings
    for store in stores[1:]:
        finding = findings[str(store)]
        assert finding["actionable"] is False
        assert finding["action_token"] is None
        assert [action["kind"] for action in finding["actions"]] == ["reveal"]


def test_orphan_normalization_and_classification(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(module, "HOME_DIR", home)
    containers = home / "Library/Containers"
    groups = home / "Library/Group Containers"
    containers.mkdir(parents=True)
    groups.mkdir(parents=True)
    for root, names in [(containers, ["com.1password.browser-support", "at.obdev.littlesnitchmini", "com.apple.Safari"]),
                        (groups, ["2BUA8C4S2C.com.1password", "group.com.1password.family", "group.com.apple.notes", "243LU875E5.groups.com.apple.podcasts", "group.net.whatsapp.family"])]:
        for name in names:
            (root / name).mkdir()
    scan_id = _insert_scan(module)
    result = module.collect_orphan_candidates(scan_id, {"com.1password.1password", "ai.perplexity.mac"})
    assert {item["name"] for item in result["items"]} == {
        "at.obdev.littlesnitchmini", "group.net.whatsapp.family"
    }


def test_additive_report_handles_old_base_and_preserves_new_sections(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    empty_breakdown = {"items": [], "total_bytes": 0, "updated_at": None}
    monkeypatch.setattr(module, "build_breakdowns_from_db", lambda scan_id: {
        key: dict(empty_breakdown) for key in ("data_root", "home_root", "library_root", "applications_root")
    })
    monkeypatch.setattr(module, "fetch_large_files_from_db", lambda scan_id: {"items": [], "updated_at": None})
    monkeypatch.setattr(module, "discover_cache_candidates", lambda scan_id, protection_snapshot=None: [])
    metadata = {key: 0 for key in (
        "container_size_bytes", "container_used_bytes", "container_free_bytes",
        "data_volume_used_bytes", "system_volume_used_bytes",
    )}
    report = module.build_updated_report(1, {}, metadata, [], {"items": [], "updated_at": None})
    assert "providers" not in report and "orphans" not in report
    base = {"providers": {"items": [{"slug": "uv-cache"}]}, "orphans": {"items": [{"name": "x"}]}}
    report = module.build_updated_report(1, base, metadata, [], {"items": [], "updated_at": None})
    assert report["providers"] == base["providers"]
    assert report["orphans"] == base["orphans"]


def test_history_keeps_newest_sixty_reports(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    for index in range(62):
        module.persist_report({"generated_at": f"2026-01-01T00:00:{index:02d}"})
    names = sorted(path.name for path in module.RUNTIME_PATHS.history_dir.glob("scan-*.json"))
    assert len(names) == 60
    assert names[0].endswith("02.json")
    assert names[-1].endswith("61.json")


def test_orphans_report_omitted_count_and_bytes(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    root = home / "Library/Containers"
    root.mkdir(parents=True, exist_ok=True)
    for index in range(42):
        (root / f"synthetic.app{index:02d}").mkdir()
    monkeypatch.setattr(module, "indexed_path_bytes", lambda scan, path: int(path.name[-2:]) + 1)
    result = module.collect_orphan_candidates(1, set())
    assert len(result["items"]) == 40
    assert result["truncated"] == {"count": 2, "bytes": 3}


def test_running_owner_and_unknown_cache_are_safe(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    def item(path):
        return {"path": str(home / path), "label": "Synthetic", "category": "cache", "allocated_bytes": 7, "actionable": True, "action_token": "token", "cleanup_kind": "trash_path", "actions": [{"kind": "execute"}]}
    running = {"org.example.app": "Synthetic App"}
    result = module.build_findings_section([], discovered=[item("Library/Caches/org.example.app/cache"), item("Library/Application Support/Synthetic App/cache")], running_apps=running)
    assert all(entry["owner_running"] for entry in result["items"])
    assert all(entry["owner_name"] == "Synthetic App" for entry in result["items"])
    assert not next(entry for entry in result["items"] if "/Caches/" in entry["path"])["actionable"]
    assert next(entry for entry in result["items"] if "/Application Support/" in entry["path"])["actionable"]
    unknown = module.build_findings_section([], discovered=[item("Library/Caches/org.example.app/cache")], running_apps=None)
    assert not unknown["items"][0]["actionable"]


def test_indexed_library_bucket_entries_require_stopped_owner_and_no_protection(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    scan_id = _insert_scan(module)
    library = home / "Library/Caches"
    entries = [library / name for name in ("org.example.stopped", "org.example.running", "com.apple.synthetic", "org.example.protected")]
    dot_entry = home / ".cache/org.example.synthetic"
    _index_dirs(module, scan_id, [(path, 120) for path in [*entries, dot_entry, entries[3] / ".worktrees"]])
    monkeypatch.setattr(module, "collect_installed_bundle_ids", lambda *args, **kwargs: {"org.example.stopped": "Synthetic Stopped"})
    result = module.build_findings_section([], scan_id=scan_id, running_apps={"org.example.running": "Synthetic Running"})
    items = {item["path"]: item for item in result["items"]}
    stopped = items[str(entries[0])]
    assert stopped["actionable"] is True
    assert stopped["risk"] == "low"
    assert stopped["estimated_reclaim_bytes"] == 120 * 1024 * 1024
    assert module.decode_action_token(stopped["action_token"]) == {"kind": "trash_path", "path": str(entries[0])}
    assert [action["kind"] for action in stopped["actions"]] == ["reveal", "execute"]
    for path in [*entries[1:], dot_entry]:
        assert items[str(path)]["actionable"] is False
        assert items[str(path)]["action_token"] is None
        assert [action["kind"] for action in items[str(path)]["actions"]] == ["reveal"]
    unknown = module.build_findings_section([], scan_id=scan_id, running_apps=None)
    assert not next(item for item in unknown["items"] if item["path"] == str(entries[0]))["actionable"]


def test_running_app_probe_parses_and_fails_closed(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "run_command", lambda args, timeout=120: {"ok": True, "stdout": '1) "Synthetic App" ASN:0x0-0x1:\n    bundleID="org.example.app"\n'})
    assert module.collect_running_apps() == {"org.example.app": "Synthetic App"}
    monkeypatch.setattr(module, "run_command", lambda args, timeout=120: {"ok": True, "stdout": "malformed"})
    assert module.collect_running_apps() is None
    monkeypatch.setattr(module, "run_command", lambda args, timeout=120: {"ok": False, "stdout": ""})
    assert module.collect_running_apps() is None


def test_running_app_probe_accepts_entries_without_bundle_id(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "run_command", lambda args, timeout=120: {"ok": True, "stdout": '1) "Synthetic daemon" ASN:0x0-0x1:\n    bundleID=[ NULL ]\n2) "Synthetic App" ASN:0x0-0x2:\n    bundleID="org.example.app"\n'})
    apps = module.collect_running_apps()
    assert apps is not None
    assert apps["org.example.app"] == "Synthetic App"
    assert "Synthetic daemon" in apps.values()


def test_real_darwin_temp_root_contract():
    import subprocess
    expected = Path(subprocess.check_output(["getconf", "DARWIN_USER_TEMP_DIR"], text=True).strip()).resolve()
    module = load_launcher(SCRIPT_PATH)
    assert expected in module.temp_roots()


def test_protection_snapshot_handles_similar_sibling_prefix(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    scan_id = _insert_scan(module)
    target = home / "foo"
    _index_dirs(module, scan_id, [(home / "foo-bar/.worktrees", 1), (target / ".worktrees", 1)])
    snapshot = module.load_cleanup_protection(scan_id)
    assert module.indexed_cleanup_protection(scan_id, target, snapshot) == module.indexed_cleanup_protection(scan_id, target)


def test_darwin_directory_falls_back_and_warns(monkeypatch, tmp_path, caplog):
    module = load(monkeypatch, tmp_path)
    def unsupported(_key):
        raise ValueError("synthetic unavailable confstr")
    monkeypatch.setattr(module.os, "confstr", unsupported)
    expected = tmp_path / "synthetic-temp"
    monkeypatch.setattr(module, "run_command", lambda args, timeout=120: {"ok": True, "stdout": str(expected) + "\n"})
    assert module.darwin_user_directory("CS_DARWIN_USER_TEMP_DIR") == expected.resolve()
    monkeypatch.setattr(module, "run_command", lambda args, timeout=120: {"ok": False, "stdout": ""})
    assert module.darwin_user_directory("CS_DARWIN_USER_CACHE_DIR") is None
    assert "DARWIN_USER_CACHE_DIR" in caplog.text


def test_large_index_discovery_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT_PATH)
    module.ensure_runtime_home(module.RUNTIME_PATHS)
    module.initialize_scan_db(module.RUNTIME_PATHS)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    scan_id = _insert_scan(module)
    now = module.iso_now()
    def rows():
        for i in range(400000):
            name = "__pycache__" if i < 15000 else "Cache" if i < 16000 else "synthetic"
            path = home / f"project-{i}" / name
            yield (scan_id, str(path), str(path.parent), name, "home_root", len(path.parts), 120 * 1024 * 1024, 1, now)
    with module.open_db_connection() as connection:
        connection.executemany("INSERT INTO nodes (scan_id,path,parent_path,name,root_key,depth,allocated_bytes,children_indexed,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", rows())
    start = time.monotonic()
    def timeout(_signum, _frame):
        raise AssertionError("discovery exceeded 5 seconds")
    previous_handler = signal.signal(signal.SIGALRM, timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 5)
    try:
        findings = module.discover_candidates(scan_id)
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)
    elapsed = time.monotonic() - start
    print(f"synthetic 400000-node discovery: {elapsed:.3f}s")
    group = next(item for item in findings if item.get("category") == "python_bytecode")
    assert group["count"] == 15000
    assert sum(item.get("category") == "discovered_cache" for item in findings) == 1000
    assert elapsed < 5, f"discovery took {elapsed:.3f}s"


def test_library_cache_eligibility_and_running_names(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "WATCHLIST_SPECS", [])
    scan_id = _insert_scan(module)
    root = home / "Library/Caches"
    paths = [root / name for name in ("Synthetic Installed", "org.example.installed", "Synthetic Unknown", "AppleUnknown", "Synthetic Running", "runningid")]
    nested = root / "Synthetic Nested Unknown" / "Cache"
    _index_dirs(module, scan_id, [(path, 120) for path in [*paths, nested]])
    monkeypatch.setattr(module, "collect_installed_bundle_ids", lambda *args, **kwargs: {"org.example.installed": "Synthetic Installed"})
    result = module.build_findings_section([], scan_id=scan_id, running_apps={"org.example.runningid": "Synthetic Running"})
    items = {item["path"]: item for item in result["items"]}
    assert items[str(paths[0])]["actionable"] and items[str(paths[1])]["actionable"]
    for path in paths[2:]:
        assert not items[str(path)]["actionable"]
    assert not items[str(nested)]["actionable"]


def test_installed_cache_identity_comes_from_synthetic_apps(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    apps = tmp_path / "synthetic-applications"
    monkeypatch.setattr(module, "APPLICATIONS_DIR", apps)
    for name, identifier in [("Synthetic Tool", "org.example.tool"), ("Synthetic Apple", "com.apple.synthetic")]:
        info = apps / f"{name}.app/Contents/Info.plist"
        info.parent.mkdir(parents=True)
        info.write_bytes(plistlib.dumps({"CFBundleIdentifier": identifier}))
    assert module.collect_installed_bundle_ids(include_names=True) == {"org.example.tool": "Synthetic Tool", "com.apple.synthetic": None}
    assert module.library_cache_eligible("synthetic tool", module.collect_installed_bundle_ids(include_names=True))
    assert not module.library_cache_eligible("Synthetic Apple", module.collect_installed_bundle_ids(include_names=True))


def test_running_name_and_identifier_suffix_protect_nested_cache(monkeypatch, tmp_path):
    module = load(monkeypatch, tmp_path)
    home = _discovery_home(module, monkeypatch, tmp_path)
    paths = [home / "Library/Caches/Synthetic Running/Cache", home / "Library/Caches/runningid/Cache",
             home / "Library/Application Support/runningid/Cache", home / "Library/Containers/org.example.runningid/Cache"]
    items = [{"path": str(path), "label": "Synthetic", "category": "cache", "allocated_bytes": 1,
              "actionable": True, "action_token": "token", "cleanup_kind": "trash_path", "actions": [{"kind": "execute"}]} for path in paths]
    monkeypatch.setattr(module, "collect_installed_bundle_ids", lambda *args, **kwargs: {})
    findings = module.build_findings_section([], discovered=items, running_apps={"org.example.runningid": "Synthetic Running"})["items"]
    assert all(item.get("owner_running") and item.get("owner_name") == "Synthetic Running" for item in findings)
    assert all(not item["actionable"] for item in findings if "/Library/Caches/" in item["path"])


@pytest.mark.parametrize("kind,depth", [("fifo", 1), ("socket", 2), ("fifo", 3), ("socket", 3)])
def test_temp_directory_refuses_nested_ipc(monkeypatch, tmp_path, kind, depth):
    module = load(monkeypatch, tmp_path)
    root = tmp_path / "synthetic-temp"
    target = root / "candidate"
    parent = target
    for _ in range(depth - 1):
        parent /= "nested"
    parent.mkdir(parents=True)
    ipc = parent / "ipc"
    sock = None
    if kind == "fifo":
        os.mkfifo(ipc)
    else:
        sock = socket.socket(socket.AF_UNIX)
        monkeypatch.chdir(parent)
        sock.bind("ipc")
    try:
        old = int(time.time()) - 4 * 86400
        for path in [target, *[p for p in ipc.parents if target in p.parents], ipc]:
            os.utime(path, (old, old))
        monkeypatch.setattr(module, "temp_roots", lambda: [root])
        monkeypatch.setattr(module, "TRASH_DIR", tmp_path / "synthetic-trash")
        monkeypatch.setattr(module, "DATA_VOLUME", tmp_path)
        scan_id = _insert_scan(module, active=True)
        _index_dirs(module, scan_id, [(tmp_path / str(target).lstrip("/"), 120)])
        with module.open_db_connection() as connection:
            connection.execute("UPDATE nodes SET newest_mtime=?", (old,))
        preview = module.temp_findings(scan_id)[0]
        assert preview["count"] == (0 if depth <= 2 else 1)
        result = module.execute_trash_group({"kind": "trash_group", "rule": "temp_old", "root": str(root), "min_age_days": 3})
        assert target.exists() and result["moved_count"] == 0
        assert result["failure_count"] == 1
        assert kind in result["failures"][0]["error"].lower()
    finally:
        if sock:
            sock.close()
