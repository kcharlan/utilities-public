import csv
import io
import json
import sqlite3
import socket
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

import httpx
import pytest
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import ASGISyncClient, load_launcher


@pytest.fixture
def client(tmp_path):
    module = load_launcher(Path(__file__).resolve().parents[1] / 'editdb')
    path = tmp_path / 'synthetic.sqlite'
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)')
    module.db_manager = module.DBManager(str(path))
    return ASGISyncClient(module.app), path


def upload(client, data):
    http, _ = client
    return http.post('/api/import/items', files={'file': ('synthetic.csv', data, 'text/csv')})


def rows(client):
    _, path = client
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT id, label FROM items ORDER BY id').fetchall()


@pytest.fixture
def console_client(client):
    _, path = client
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("DROP TABLE items; CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT UNIQUE); INSERT INTO items VALUES (1, 'one'), (2, 'two');")
    return client


def test_console_returning_update_persists(console_client):
    http, _ = console_client
    response = http.post('/api/query', json={'query': "UPDATE items SET label='changed' WHERE id=1 RETURNING label"})
    assert response.status_code == 200
    assert response.json() == {'columns': ['label'], 'rows': [{'label': 'changed'}]}
    assert rows(console_client) == [(1, 'changed'), (2, 'two')]


def test_console_failed_statement_changes_nothing(console_client):
    http, _ = console_client
    response = http.post('/api/query', json={'query': "UPDATE items SET label='two' WHERE id=1"})
    assert response.status_code == 400
    assert rows(console_client) == [(1, 'one'), (2, 'two')]


def test_console_rejects_multiple_statements(console_client):
    http, _ = console_client
    response = http.post('/api/query', json={'query': "UPDATE items SET label='x'; DELETE FROM items"})
    assert response.status_code == 400
    assert rows(console_client) == [(1, 'one'), (2, 'two')]


@pytest.fixture
def export_client(client):
    http, path = client
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE kinds (id INTEGER PRIMARY KEY, big INTEGER, raw BLOB, note TEXT)')
        db.execute('INSERT INTO kinds VALUES (?, ?, ?, ?)', (1, 9007199254740993, b'\x00\xff', '漢字'))
        db.execute('INSERT INTO kinds VALUES (2, NULL, NULL, NULL)')
    return http


def test_json_export_uses_documented_encodings(export_client):
    response = export_client.get('/api/export/kinds/json')
    assert response.status_code == 200
    assert response.headers['content-disposition'] == 'attachment; filename=kinds.json'
    assert json.loads(response.content) == [
        {'id': 1, 'big': '9007199254740993', 'raw': {'$blob': '00ff'}, 'note': '漢字'},
        {'id': 2, 'big': None, 'raw': None, 'note': None},
    ]


def test_csv_export_writes_blobs_as_blob_objects(export_client):
    response = export_client.get('/api/export/kinds/csv')
    assert response.status_code == 200
    exported = list(csv.DictReader(io.StringIO(response.text)))
    assert exported == [
        {'id': '1', 'big': '9007199254740993', 'raw': '{"$blob": "00ff"}', 'note': '漢字'},
        {'id': '2', 'big': '', 'raw': '', 'note': ''},
    ]


def test_import_rejects_non_utf8_csv(client):
    response = upload(client, b'id,label\n1,caf\xe9\n')
    assert response.status_code == 400
    assert 'UTF-8' in response.json()['detail']
    assert rows(client) == []


def test_import_accepts_utf8_bom(client):
    response = upload(client, '\ufeffid,label\n1,alpha\n'.encode('utf-8'))
    assert response.status_code == 200
    assert response.json()['rows_imported'] == 1
    assert rows(client) == [(1, 'alpha')]


def test_import_failure_rolls_back_its_batch(client):
    response = upload(client, b'id,label\n1,alpha\n2,beta\n1,dup\n')
    assert response.status_code == 400
    assert rows(client) == []


def test_import_keeps_committed_batches_before_a_failure(client):
    data = 'id,label\n' + ''.join(f'{i},alpha\n' for i in range(1, 1001)) + '1,dup\n'
    response = upload(client, data.encode('utf-8'))
    assert response.status_code == 400
    assert rows(client) == [(i, 'alpha') for i in range(1, 1001)]


def test_import_rejects_invalid_header(client):
    response = upload(client, b'bad-name\nx\n')
    assert response.status_code == 400
    assert rows(client) == []


def test_locked_database_fails_without_stalling_other_requests(tmp_path, monkeypatch):
    module = load_launcher(Path(__file__).resolve().parents[1] / 'editdb')
    path = tmp_path / 'synthetic.sqlite'
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)')
        db.execute("INSERT INTO items VALUES (1, 'one')")
    module.db_manager = module.DBManager(str(path))
    monkeypatch.setattr(module, 'SQLITE_BUSY_TIMEOUT_SECONDS', 1.0)
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute('BEGIN IMMEDIATE')
    write_started = threading.Event()
    real_connect = sqlite3.connect

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith('UPDATE '):
                write_started.set()
            return super().execute(sql, parameters)

    def observed_connect(*args, **kwargs):
        return real_connect(*args, factory=ObservedConnection, **kwargs)

    monkeypatch.setattr(module.sqlite3, 'connect', observed_connect)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen()
    url = f'http://127.0.0.1:{sock.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(module.app, log_level='error'))
    server_thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]})
    result = {}

    def put():
        try:
            result['response'] = httpx.put(url + '/api/data/items', json={
                'where': {'id': 1}, 'values': {'label': 'changed'}},
                headers={'Origin': url}, timeout=3.0)
        except Exception as exc:
            result['error'] = exc

    client_thread = threading.Thread(target=put)
    server_thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, 'server failed to start'
        client_thread.start()
        assert write_started.wait(3), f'write did not reach SQLite: {result}'
        started = time.monotonic()
        response = httpx.get(url + '/api/status', timeout=0.45)
        elapsed = time.monotonic() - started
        assert response.status_code == 200
        assert elapsed < 0.5
        assert client_thread.is_alive(), 'PUT completed before the status probe'
        client_thread.join(timeout=3)
        assert not client_thread.is_alive(), 'PUT did not finish'
        assert 'error' not in result, result.get('error')
        assert result['response'].status_code == 400
        assert 'locked' in result['response'].json()['detail'].lower()
    finally:
        blocker.rollback()
        blocker.close()
        if client_thread.ident is not None:
            client_thread.join(timeout=4)
        server.should_exit = True
        server_thread.join(timeout=5)
        sock.close()
        assert not client_thread.is_alive()
        assert not server_thread.is_alive()
    with closing(real_connect(path)) as db:
        assert db.execute('SELECT label FROM items WHERE id = 1').fetchone() == ('one',)
