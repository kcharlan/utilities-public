from __future__ import annotations

import plistlib
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "storage_monitor"


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
    for store in stores:
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
    monkeypatch.setattr(module, "discover_cache_candidates", lambda scan_id: [])
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
