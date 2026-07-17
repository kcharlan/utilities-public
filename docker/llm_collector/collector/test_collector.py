import importlib.util
import json
import signal
import uuid
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("collector.py")


def load_collector(tmp_path, monkeypatch, api_key=None):
    app_root = tmp_path / "app"
    monkeypatch.setenv("APP_ROOT", str(app_root))
    monkeypatch.setenv("STATE_PATH", str(app_root / "state.json"))
    monkeypatch.setenv("SNAP_DIR", str(app_root / "snapshots"))
    monkeypatch.setenv("LOG_PATH", str(app_root / "collector.log"))
    monkeypatch.setenv("BUCKET_TIMEZONE", "America/New_York")
    if api_key is None:
        monkeypatch.delenv("API_KEY", raising=False)
    else:
        monkeypatch.setenv("API_KEY", api_key)

    module_name = f"llm_collector_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None

    previous_handlers = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }
    try:
        spec.loader.exec_module(module)
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)

    module.app.config.update(TESTING=True)
    return module


def test_add_flow_and_reset_rollup(tmp_path, monkeypatch):
    module = load_collector(tmp_path, monkeypatch)
    client = module.app.test_client()

    assert client.get("/health").get_json() == {"ok": True}
    assert client.get("/counters").get_json() == {"counters": {}}

    response = client.post(
        "/add",
        json={
            "client_id": "client-1",
            "seq": 1,
            "deltas": {"chat.openai.com": 5},
            "ts": 1777174200000,
        },
    )
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "applied": 5, "last_seq": 1}

    response = client.post(
        "/add",
        json={"client_id": "client-1", "seq": 1, "deltas": {"chat.openai.com": 99}},
    )
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "applied": 0, "last_seq": 1}

    response = client.post(
        "/add",
        json={"client_id": "client-1", "seq": 3, "deltas": {"chat.openai.com": 1}},
    )
    assert response.status_code == 409
    assert response.get_json() == {"error": "out_of_order", "expected_next": 2}

    assert client.get("/counters").get_json() == {"counters": {"chat.openai.com": 5}}

    response = client.post("/reset")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True

    state_path = Path(module.STATE_PATH)
    snap_dir = Path(module.SNAP_DIR)
    csv_path = snap_dir / module.CSV_FILENAME
    written_state = json.loads(state_path.read_text())

    assert written_state == {"totals": {}, "daily_totals": {}, "clients": {}}
    assert client.get("/counters").get_json() == {"counters": {}}
    snapshots = list(snap_dir.glob("snapshot_*.json.bak"))
    assert snapshots
    snapshot_payload = json.loads(snapshots[0].read_text())
    assert snapshot_payload["daily_totals"] == {"2026-04-25": {"chat.openai.com": 5}}
    assert csv_path.exists()
    csv_text = csv_path.read_text()
    assert "date" in csv_text
    assert "chat.openai.com" in csv_text
    assert "2026-04-25,5" in csv_text


def test_add_buckets_by_payload_timestamp_date(tmp_path, monkeypatch):
    module = load_collector(tmp_path, monkeypatch)
    client = module.app.test_client()

    response = client.post(
        "/add",
        json={
            "client_id": "client-1",
            "seq": 1,
            "deltas": {"chat.openai.com": 2},
            "ts": 1777174200000,
        },
    )
    assert response.status_code == 200

    response = client.post(
        "/add",
        json={
            "client_id": "client-1",
            "seq": 2,
            "deltas": {"chat.openai.com": 3, "gemini.google.com": 4},
            "ts": 1777260600000,
        },
    )
    assert response.status_code == 200

    written_state = json.loads(Path(module.STATE_PATH).read_text())
    assert written_state["totals"] == {"chat.openai.com": 5, "gemini.google.com": 4}
    assert written_state["daily_totals"] == {
        "2026-04-25": {"chat.openai.com": 2},
        "2026-04-26": {"chat.openai.com": 3, "gemini.google.com": 4},
    }

    response = client.post("/reset")
    assert response.status_code == 200

    csv_text = (Path(module.SNAP_DIR) / module.CSV_FILENAME).read_text()
    assert "2026-04-25,2,0" in csv_text
    assert "2026-04-26,3,4" in csv_text


def test_api_key_is_enforced_when_configured(tmp_path, monkeypatch):
    module = load_collector(tmp_path, monkeypatch, api_key="secret-key")
    client = module.app.test_client()

    assert client.get("/health").status_code == 200
    assert client.get("/counters").status_code == 403
    assert client.post("/add", json={"client_id": "client-1", "seq": 1, "deltas": {}}).status_code == 403

    response = client.get("/counters", headers={"X-API-KEY": "secret-key"})
    assert response.status_code == 200
    assert response.get_json() == {"counters": {}}
