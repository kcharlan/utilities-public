import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import ASGISyncClient, assert_local_server_guard, load_launcher, probe_websocket


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUNCHMASTER_HOME", str(tmp_path / "home"))
    module = load_launcher(Path(__file__).resolve().parents[1] / "launchmaster")
    monkeypatch.setattr(module, "PLIST_DIRS", {"user-agent": str(tmp_path)})
    return module


def test_guard_real_routes(app_module, tmp_path, monkeypatch):
    calls = []

    async def load(*args):
        calls.append(args)
        return {"success": True}

    monkeypatch.setattr(app_module, "load_job", load)
    def exercise():
        assert_local_server_guard(app_module.app, post_path="/api/jobs", ws_path="/ws")
        with ASGISyncClient(app_module.app) as client:
            assert client.websocket_url("/ws") == "ws://127.0.0.1:8000/ws"
            response = client.post("/api/jobs", json={"plist_data": {"Label": "com.example.guard"}},
                                   headers={"Origin": "http://evil.example"})
        assert response.status_code == 403
        assert probe_websocket(app_module.app, "/ws", host="127.0.0.1:8000",
                               origin="http://127.0.0.1:8000") == "accept"

    # Playwright can leave an event loop running on pytest's main thread.
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(exercise).result()
    assert not calls
    assert not (tmp_path / "com.example.guard.plist").exists()


def test_page_json_create_and_import(app_module, monkeypatch):
    async def create(data, domain):
        return {"success": False, "data": data, "domain": domain}

    async def import_(content, domain):
        return {"success": False, "content": content, "domain": domain}

    monkeypatch.setattr(app_module, "create_job", create)
    monkeypatch.setattr(app_module, "import_job", import_)
    def exercise():
        with ASGISyncClient(app_module.app) as client:
            create_response = client.post("/api/jobs", json={"plist_data": {"Label": "example"}, "domain": "user-agent"})
            import_response = client.post("/api/jobs/import", json={"content": "plist", "domain": "user-agent"})
            plain_response = client.post("/api/jobs", content='{"plist_data": {}}', headers={"Content-Type": "text/plain"})
        assert create_response.json()["data"] == {"Label": "example"}
        assert import_response.json()["content"] == "plist"
        assert plain_response.status_code == 422

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(exercise).result()


def test_host_option_is_rejected(app_module, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["launchmaster", "--host", "0.0.0.0"])
    with pytest.raises(SystemExit) as error:
        app_module.parse_args()
    assert error.value.code == 2
