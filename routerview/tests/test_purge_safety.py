import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import sqlite3
from test_csv_import import build_client, load_module


def test_purge_creates_readable_backup_first(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    client, db_path = build_client(module, tmp_path)
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO generations (id, created_at, created_date, created_hour, model, model_short, ingested_at) VALUES ('fake-1', '2020-01-01', '2020-01-01', 0, 'fake-model', 'fake-model', '2020-01-01')")
    assert client.post('/api/purge?before=2099-01-01').status_code == 200
    backups = list((tmp_path / 'home' / 'backups').glob('*.db'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute('SELECT COUNT(*) FROM generations').fetchone()[0] == 1


def test_failed_backup_prevents_purge(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    client, db_path = build_client(module, tmp_path)
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO generations (id, created_at, created_date, created_hour, model, model_short, ingested_at) VALUES ('fake-1', '2020-01-01', '2020-01-01', 0, 'fake', 'fake', '2020-01-01')")
    def fail(_):
        raise OSError('synthetic backup failure')
    monkeypatch.setattr(module, '_snapshot_db_to_backups', fail)
    import pytest
    with pytest.raises(OSError, match='synthetic backup failure'):
        client.post('/api/purge?before=2099-01-01')
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM generations').fetchone()[0] == 1


def test_import_database_failure_is_not_reported_as_skipped(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / 'home')
    client, db_path = build_client(module, tmp_path)
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON generations BEGIN SELECT RAISE(ABORT, 'synthetic database failure'); END")
    import pytest
    with pytest.raises(sqlite3.IntegrityError, match='synthetic database failure'):
        client.post('/api/import/csv', files={'file': ('fake.csv', 'generation_id,created_at,model_permaslug\nfake-1,2024-01-01,fake\n', 'text/csv')})
