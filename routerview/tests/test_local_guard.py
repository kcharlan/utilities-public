import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import sqlite3
from test_csv_import import build_client, load_module


def test_purge_rejects_foreign_host_and_origin(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    client, db_path = build_client(module, tmp_path)
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO generations (id, created_at, created_date, created_hour, model, model_short, ingested_at) VALUES ('fake-1', '2020-01-01', '2020-01-01', 0, 'fake-model', 'fake-model', '2020-01-01')")
    for headers in ({'host': 'evil.example'}, {'origin': 'https://evil.example'}):
        assert client.post('/api/purge?before=2099-01-01', headers=headers).status_code == 403
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM generations').fetchone()[0] == 1


def test_port_finder_binds_loopback(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    calls = []
    class Socket:
        def bind(self, address): calls.append(address)
        def close(self): pass
    monkeypatch.setattr(module.socket, 'socket', lambda *args: Socket())
    assert module.find_open_port(8123) == 8123
    assert calls == [('127.0.0.1', 8123)]
