import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import ASGISyncClient, load_launcher


@pytest.fixture
def client(tmp_path):
    module = load_launcher(Path(__file__).resolve().parents[1] / 'editdb')
    path = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)')
    module.db_manager = module.DBManager(str(path))
    return ASGISyncClient(module.app), path


def upload(client, data):
    http, _ = client
    return http.post('/api/import/items', files={'file': ('synthetic.csv', data, 'text/csv')})


def rows(client):
    _, path = client
    with sqlite3.connect(path) as db:
        return db.execute('SELECT id, label FROM items ORDER BY id').fetchall()


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
