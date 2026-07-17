from __future__ import annotations

import plistlib
import sys
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
