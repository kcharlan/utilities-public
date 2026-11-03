import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.testkit import ASGISyncClient, load_launcher


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT NOT NULL UNIQUE,
                                amount INTEGER CHECK(amount > 0), spare TEXT);
            CREATE INDEX items_amount ON items(amount);
            CREATE TABLE events (message TEXT);
            CREATE TRIGGER items_insert AFTER INSERT ON items BEGIN
                INSERT INTO events VALUES (NEW.label);
            END;
            CREATE VIEW item_view AS SELECT id, label FROM items;
            INSERT INTO items VALUES (1, 'one', 5, 'x');
        ''')
    module = load_launcher(Path(__file__).resolve().parents[1] / 'editdb')
    module.db_manager = module.DBManager(str(path))
    return ASGISyncClient(module.app), path


def migrate(client, columns):
    payload = {'columns': [
        {'old_name': old, 'new_name': new, 'type': typ, 'delete': delete}
        for old, new, typ, delete in columns
    ]}
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(client.post, '/api/migrate/items', json=payload).result()


def test_native_changes_keep_views_constraints_indexes_and_triggers(database):
    client, path = database
    response = migrate(client, [('id', 'id', 'INTEGER', False), ('label', 'title', 'TEXT', False),
                                ('amount', 'amount', 'INTEGER', False), ('spare', 'spare', 'TEXT', True),
                                ('', 'added', 'TEXT', False)])
    assert response.status_code == 200, response.text
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT title FROM item_view').fetchall() == [('one',)]
        db.execute("INSERT INTO items (id, title, amount) VALUES (2, 'two', 4)")
        assert db.execute('SELECT message FROM events ORDER BY rowid').fetchall() == [('one',), ('two',)]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='items_amount'").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO items (id, title, amount) VALUES (3, 'two', 1)")


def test_type_change_preserves_schema_objects_and_view(database):
    client, path = database
    response = migrate(client, [('id', 'id', 'INTEGER', False), ('label', 'label', 'TEXT', False),
                                ('amount', 'amount', 'REAL', False), ('spare', 'spare', 'TEXT', False)])
    assert response.status_code == 200, response.text
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT label FROM item_view').fetchall() == [('one',)]
        assert db.execute('SELECT type FROM pragma_table_info("items") WHERE name="amount"').fetchone() == ('REAL',)
        assert db.execute("SELECT name FROM sqlite_master WHERE name='items_amount'").fetchone()
        db.execute("INSERT INTO items VALUES (2, 'two', 2.5, NULL)")
        assert db.execute('SELECT message FROM events ORDER BY rowid').fetchall() == [('one',), ('two',)]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO items VALUES (3, 'two', -1, NULL)")


def test_failed_migration_restores_schema_exactly(database):
    client, path = database
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT * FROM sqlite_master ORDER BY rowid').fetchall()
    response = migrate(client, [('id', 'id', 'INTEGER', True), ('label', 'label', 'TEXT', True),
                                ('amount', 'amount', 'INTEGER', True), ('spare', 'spare', 'TEXT', True)])
    assert response.status_code == 400
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM sqlite_master ORDER BY rowid').fetchall() == before
        assert db.execute('SELECT label FROM item_view').fetchall() == [('one',)]


def test_drop_column_referenced_by_view_is_rejected_without_schema_changes(database):
    client, path = database
    with sqlite3.connect(path) as db:
        db.execute('CREATE VIEW spare_view AS SELECT spare FROM items')
        before = db.execute('SELECT * FROM sqlite_master ORDER BY rowid').fetchall()
    response = migrate(client, [('id', 'id', 'INTEGER', False), ('label', 'label', 'TEXT', False),
                                ('amount', 'amount', 'INTEGER', False), ('spare', 'spare', 'TEXT', True)])
    assert response.status_code == 400
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM sqlite_master ORDER BY rowid').fetchall() == before
        assert db.execute('SELECT spare FROM spare_view').fetchall() == [('x',)]


def test_failed_copy_rolls_back_earlier_rename_and_schema(database):
    client, path = database
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO items VALUES (2, '01', 3, NULL)")
        db.execute("INSERT INTO items VALUES (3, '1', 4, NULL)")
        before = db.execute('SELECT * FROM sqlite_master ORDER BY rowid').fetchall()
    response = migrate(client, [('id', 'id', 'INTEGER', False), ('label', 'title', 'INTEGER', False),
                                ('amount', 'amount', 'INTEGER', False), ('spare', 'spare', 'TEXT', False)])
    assert response.status_code == 400
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM sqlite_master ORDER BY rowid').fetchall() == before
        assert db.execute('SELECT label FROM item_view ORDER BY id').fetchall() == [('one',), ('01',), ('1',)]


def test_rebuild_preserves_autoincrement_high_water_mark(database):
    client, path = database
    with sqlite3.connect(path) as db:
        db.executescript('DROP VIEW item_view; DROP TABLE items; CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT); INSERT INTO items VALUES (100, "old"); DELETE FROM items;')
    response = migrate(client, [('id', 'id', 'INTEGER', False), ('label', 'label', 'BLOB', False)])
    assert response.status_code == 200, response.text
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO items(label) VALUES ('new')")
        assert db.execute('SELECT id FROM items').fetchone() == (101,)


def test_rebuild_preserves_hidden_rowid(database):
    client, path = database
    with sqlite3.connect(path) as db:
        db.executescript('DROP VIEW item_view; DROP TABLE items; CREATE TABLE items (label TEXT); INSERT INTO items(rowid, label) VALUES (47, "value");')
    response = migrate(client, [('label', 'label', 'BLOB', False)])
    assert response.status_code == 200, response.text
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT rowid, label FROM items').fetchall() == [(47, 'value')]


def test_rebuild_of_without_rowid_table_keeps_rows_and_key(database):
    client, path = database
    with sqlite3.connect(path) as db:
        db.executescript("""
            DROP VIEW item_view; DROP TABLE items;
            CREATE TABLE items (a TEXT, b INTEGER, label TEXT, PRIMARY KEY(a, b)) WITHOUT ROWID;
            INSERT INTO items VALUES ('x', 1, 'one'), ('x', 2, 'two');
        """)
    response = migrate(client, [('a', 'a', 'TEXT', False), ('b', 'b', 'INTEGER', False),
                                ('label', 'label', 'BLOB', False)])
    assert response.status_code == 200, response.text
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT a, b, label FROM items ORDER BY b').fetchall() == [('x', 1, 'one'), ('x', 2, 'two')]
        assert db.execute("SELECT wr FROM pragma_table_list WHERE name='items'").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO items VALUES ('x', 1, 'dup')")


def test_rebuild_of_referenced_parent_keeps_child_foreign_keys(database):
    client, path = database
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE notes (id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES items(id)); INSERT INTO notes VALUES (1, 1);')
    response = migrate(client, [('id', 'id', 'INTEGER', False), ('label', 'label', 'TEXT', False),
                                ('amount', 'amount', 'REAL', False), ('spare', 'spare', 'TEXT', False)])
    assert response.status_code == 200, response.text
    with sqlite3.connect(path) as db:
        assert [row[2] for row in db.execute('PRAGMA foreign_key_list(notes)')] == ['items']
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        db.execute('PRAGMA foreign_keys = ON')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO notes VALUES (2, 999)')
