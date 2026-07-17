import argparse
import json
import sqlite3
import stat
import sys
import webbrowser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import ASGISyncClient, assert_launcher_help, load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "routerview"


def load_module():
    return load_launcher(SCRIPT_PATH)


def test_help_does_not_create_runtime_state(tmp_path):
    runtime_home = tmp_path / "runtime_home"
    assert_launcher_help(
        SCRIPT_PATH,
        env_overrides={"ROUTERVIEW_HOME": str(runtime_home)},
    )

    assert not runtime_home.exists()


def test_announce_resolved_port_reports_fallback(capsys):
    module = load_module()

    module.announce_resolved_port(8100, 8101)

    out = capsys.readouterr().out
    assert "Port 8100 is in use; using port 8101 instead." in out


def test_announce_resolved_port_quiet_when_unchanged(capsys):
    module = load_module()

    module.announce_resolved_port(8100, 8100)

    assert capsys.readouterr().out == ""


def test_open_browser_when_ready_waits_for_health(monkeypatch):
    module = load_module()
    attempts = []
    opened = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def getcode(self):
            return self.status

    def fake_urlopen(url, timeout):
        attempts.append((url, timeout))
        if len(attempts) < 3:
            raise module.urllib.error.URLError("not ready")
        return FakeResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(webbrowser, "open", opened.append)

    module.open_browser_when_ready("http://127.0.0.1:8102", timeout_seconds=1.0)

    assert attempts[0][0] == "http://127.0.0.1:8102/api/health"
    assert opened == ["http://127.0.0.1:8102"]


def test_live_routes_are_not_registered():
    module = load_module()

    routes = {route.path for route in module.app.routes}
    assert "/v1/traces" not in routes
    assert "/api/import/poll" not in routes
    assert "/ws" not in routes


def test_health_endpoint_reports_zero_connected_clients_without_websocket_manager(tmp_path):
    module = load_module()
    db_path = tmp_path / "routerview.db"
    module.init_database(str(db_path))
    module._db_path = str(db_path)

    client = ASGISyncClient(module.app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["connected_clients"] == 0
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600


def test_main_hardens_existing_runtime_tree_and_new_mutable_state(
    tmp_path, monkeypatch
):
    runtime_home = tmp_path / "runtime_home"
    runtime_home.mkdir(mode=0o755)
    db_path = runtime_home / "routerview.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE synthetic (value TEXT)")
    mapping_path = runtime_home / "attribute_mapping.json"
    mapping_path.write_text(json.dumps({"_comment": "SYNTHETIC"}), encoding="utf-8")
    port_path = runtime_home / "last_port"
    port_path.write_text("8100", encoding="utf-8")
    backups = runtime_home / "backups"
    backups.mkdir(mode=0o755)
    backup_path = backups / "synthetic.db"
    backup_path.write_bytes(b"SYNTHETIC")
    for path in (db_path, mapping_path, port_path, backup_path):
        path.chmod(0o644)

    monkeypatch.setenv("ROUTERVIEW_HOME", str(runtime_home))
    module = load_module()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: argparse.Namespace(
            port=18100,
            db=str(db_path),
            debug=False,
            host="127.0.0.1",
        ),
    )
    monkeypatch.setattr(module, "find_open_port", lambda preferred: preferred)
    monkeypatch.setattr(module.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(module.uvicorn, "run", lambda *_args, **_kwargs: None)

    module.main()

    assert stat.S_IMODE(runtime_home.stat().st_mode) == 0o700
    assert stat.S_IMODE(backups.stat().st_mode) == 0o700
    for path in (db_path, mapping_path, port_path, backup_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_runtime_home_symlink_is_rejected_without_chmodding_target(
    tmp_path, monkeypatch
):
    target = tmp_path / "target-runtime"
    target.mkdir(mode=0o755)
    runtime_link = tmp_path / "runtime-link"
    runtime_link.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("ROUTERVIEW_HOME", str(runtime_link))
    module = load_module()

    with pytest.raises(RuntimeError, match="symbolic link"):
        module.secure_runtime_tree(runtime_link)

    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert not list(target.iterdir())
