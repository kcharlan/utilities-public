import asyncio
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
        db.execute('CREATE TABLE items (a TEXT, b INTEGER, value TEXT, raw BLOB, PRIMARY KEY(a,b))')
        db.executemany('INSERT INTO items VALUES (?, ?, ?, ?)', [('x', 1, 'first', b'\xff'), ('x', 2, 'second', b'\x00')])
    module.db_manager = module.DBManager(str(path))
    return ASGISyncClient(module.app), path


@pytest.mark.parametrize('method', ['update', 'delete'])
@pytest.mark.parametrize('where', [{'a': 'x'}, {'a': 'missing'}])
def test_non_single_row_mutation_rolls_back(client, method, where):
    http, path = client
    response = (http.put('/api/data/items', json={'where': where, 'values': {'value': 'changed'}})
                if method == 'update' else http.post('/api/data/items/delete', json=where))
    assert response.status_code == 409
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT value FROM items ORDER BY b').fetchall() == [('first',), ('second',)]


def test_string_key_and_non_utf8_blob(client):
    http, path = client
    response = http.get('/api/table/items/full')
    assert response.status_code == 200
    response = http.put('/api/data/items', json={'where': {'a': 'x', 'b': '2'}, 'values': {'value': 'changed'}})
    assert response.status_code == 200
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT value FROM items ORDER BY b').fetchall() == [('first',), ('changed',)]


def test_import_limits_read_before_allocating_oversized_file(monkeypatch):
    module = load_launcher(Path(__file__).resolve().parents[1] / 'editdb')
    monkeypatch.setattr(module, 'MAX_IMPORT_SIZE', 8)

    class Upload:
        filename = 'synthetic.csv'
        async def read(self, size=-1):
            assert size == 9
            return b'x' * size

    with pytest.raises(module.HTTPException) as error:
        asyncio.run(module.import_data('items', Upload()))
    assert error.value.status_code == 413
