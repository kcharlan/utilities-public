import sys
import sqlite3
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from urllib.parse import urlencode
from tools.testkit import load_launcher, probe_http

SCRIPT = Path(__file__).resolve().parents[1] / "storage_monitor"


def test_guard_blocks_foreign_hosts_and_origins(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT)
    monkeypatch.setattr(module, "start_scan", lambda: True)
    assert probe_http(module.app, "GET", "/api/state", host="foreign.example:8000") == 403
    assert probe_http(module.app, "POST", "/api/scan", host="127.0.0.1:8000", origin="http://foreign.example") == 403
    assert probe_http(module.app, "POST", "/api/scan", host="127.0.0.1:8000") == 403
    assert probe_http(module.app, "POST", "/api/scan", host="127.0.0.1:8000", origin="http://127.0.0.1:8000") == 200


def test_get_breakdown_does_not_modify_store(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT)
    module.ensure_runtime_dirs()
    root = tmp_path / "tree"
    root.mkdir()
    monkeypatch.setattr(module, "ALLOWED_BREAKDOWN_ROOTS", [root])
    monkeypatch.setattr(module, "choose_scan_id_for_path", lambda path: 1)
    monkeypatch.setattr(module, "fetch_breakdown_from_db", lambda *args: {"items": [], "total_bytes": 0})
    def write_store(*args):
        module.RUNTIME_PATHS.scan_db.write_bytes(b"modified")
        return {"items": [], "total_bytes": 0}
    monkeypatch.setattr(module, "store_breakdown_for_path", write_store)
    before = module.RUNTIME_PATHS.scan_db.read_bytes()
    status = probe_http(module.app, "GET", "/api/breakdown?" + urlencode({"path": str(root)}), host="127.0.0.1:8000")
    assert status == 200
    assert module.RUNTIME_PATHS.scan_db.read_bytes() == before


def test_get_breakdown_reads_cached_result_without_active_scan(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT)
    root = tmp_path / "tree"
    root.mkdir()
    monkeypatch.setattr(module, "ALLOWED_BREAKDOWN_ROOTS", [root])
    monkeypatch.setattr(module, "choose_scan_id_for_path", lambda path: None)
    expected = {"path": str(root), "items": [], "total_bytes": 0}
    module.set_cached_breakdown(str(root), expected)
    assert module.api_breakdown(str(root)) == expected


def test_get_indexed_breakdown_preserves_database_bytes(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT)
    module.ensure_runtime_dirs()
    root = tmp_path / "tree"
    root.mkdir()
    monkeypatch.setattr(module, "ALLOWED_BREAKDOWN_ROOTS", [root])
    scan_id = module.create_scan_run(module.iso_now())
    module.upsert_node_rows(scan_id, [{"path": str(root), "parent_path": str(root.parent), "name": root.name,
        "root_key": "home_root", "depth": 1, "allocated_bytes": 0, "children_indexed": True,
        "updated_at": module.iso_now()}])
    module.finalize_scan_run(scan_id, {})
    before = module.RUNTIME_PATHS.scan_db.read_bytes()
    status = probe_http(module.app, "GET", "/api/breakdown?" + urlencode({"path": str(root)}), host="127.0.0.1:8000")
    assert status == 200
    assert module.RUNTIME_PATHS.scan_db.read_bytes() == before


def test_database_context_closes_connection_after_commit(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_MONITOR_HOME", str(tmp_path / "runtime"))
    module = load_launcher(SCRIPT)
    module.ensure_runtime_dirs()
    with module.open_db_connection() as connection:
        connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
