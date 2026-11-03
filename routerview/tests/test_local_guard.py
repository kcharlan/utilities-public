import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import sqlite3
from test_csv_import import build_client, load_module
from tools.testkit import assert_local_server_guard


def test_shared_guard_contract(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    build_client(module, tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(assert_local_server_guard, module.app, get_path='/api/health',
                        post_path='/api/purge').result()


def test_rejected_purge_requests_leave_rows_and_backups_untouched(monkeypatch, tmp_path):
    import asyncio
    import httpx
    module = load_module(monkeypatch, tmp_path / 'home')
    client, db_path = build_client(module, tmp_path)
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO generations (id, created_at, created_date, created_hour, model, model_short, ingested_at) VALUES ('fake-1', '2020-01-01', '2020-01-01', 0, 'fake-model', 'fake-model', '2020-01-01')")
    for headers in ({'host': 'evil.example'}, {'origin': 'https://evil.example'}):
        assert client.post('/api/purge?before=2099-01-01', headers=headers).status_code == 403
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app), base_url='http://127.0.0.1:8000') as client:
            return await client.post('/api/purge?before=2099-01-01')
    assert asyncio.run(request()).status_code == 403
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM generations').fetchone()[0] == 1
    assert not (tmp_path / 'home' / 'backups').exists()


def test_port_finder_binds_loopback(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    calls = []
    class Socket:
        def bind(self, address): calls.append(address)
        def close(self): pass
    monkeypatch.setattr(module.socket, 'socket', lambda *args: Socket())
    assert module.find_open_port(8123) == 8123
    assert calls == [('127.0.0.1', 8123)]


def test_get_does_not_create_or_harden_runtime(monkeypatch, tmp_path):
    import stat
    from tools.testkit import ASGISyncClient
    module = load_module(monkeypatch, tmp_path / 'missing')
    module._db_path = str(tmp_path / 'missing' / 'database.db')
    client = ASGISyncClient(module.app, raise_server_exceptions=False)
    assert client.get('/api/health').status_code == 500
    assert not (tmp_path / 'missing').exists()
    _, db_path = build_client(module, tmp_path)
    db_path.chmod(0o644)
    before = db_path.read_bytes()
    assert client.get('/api/health').status_code == 200
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o644
    assert db_path.read_bytes() == before


def test_get_rejects_database_symlink_without_changing_target(monkeypatch, tmp_path):
    import stat
    from tools.testkit import ASGISyncClient
    module = load_module(monkeypatch, tmp_path / 'home')
    _, target = build_client(module, tmp_path)
    target.chmod(0o644)
    before = target.read_bytes()
    link = tmp_path / 'link.db'
    link.symlink_to(target)
    module._db_path = str(link)
    response = ASGISyncClient(module.app, raise_server_exceptions=False).get('/api/health')
    assert response.status_code == 500
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert target.read_bytes() == before
