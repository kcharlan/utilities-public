import sqlite3
from unittest.mock import AsyncMock

import git_dashboard


def test_guard_rejects_foreign_host_and_origin(test_app):
    client, _ = test_app
    assert client.get('/api/status', headers={'host': 'foreign.invalid:8300'}).status_code == 403
    assert client.post('/api/fleet/scan', headers={'origin': 'http://foreign.invalid'}).status_code == 403


def test_fleet_get_is_read_only_and_refresh_requires_origin(test_app, tmp_path, monkeypatch):
    client, db = test_app
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO repositories (id,name,path,added_at) VALUES (?,?,?,?)',
                     ('synthetic', 'synthetic', str(tmp_path), '2026-01-01'))
        conn.execute('INSERT INTO working_state (repo_id,modified_count,checked_at) VALUES (?,?,?)',
                     ('synthetic', 7, 'synthetic-time'))
        before = list(conn.iterdump())
    scan = AsyncMock(return_value=[])
    monkeypatch.setattr(git_dashboard, 'scan_fleet_quick', scan)
    result = client.get('/api/fleet', headers={'origin': 'http://foreign.invalid'})
    assert result.status_code == 200
    assert result.json()['repos'][0]['modified_count'] == 7
    scan.assert_not_awaited()
    with sqlite3.connect(db) as conn:
        assert list(conn.iterdump()) == before
    assert client.post('/api/fleet/refresh', headers={'origin': 'http://foreign.invalid'}).status_code == 403
    scan.assert_not_awaited()
    assert client.post('/api/fleet/refresh').status_code == 200
    scan.assert_awaited_once()
