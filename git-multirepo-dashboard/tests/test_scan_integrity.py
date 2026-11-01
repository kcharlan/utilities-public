"""Regression tests for persisted scan integrity."""
import asyncio
import sqlite3
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import git_dashboard as app


def test_failed_history_preserves_marker_and_stats(tmp_path):
    path = tmp_path / 'state.db'
    app.init_schema(path)
    async def check():
        async with aiosqlite.connect(path) as db:
            await db.execute("INSERT INTO repositories (id, name, path, added_at, last_full_scan_at) VALUES ('r', 'r', '/synthetic', 'x', 'old')")
            await db.execute("INSERT INTO daily_stats VALUES ('r', '2026-01-01', 2, 3, 4, 5)")
            await db.commit()
            with patch.object(app, 'run_git', new=AsyncMock(return_value=('', 'timeout', -1))):
                with pytest.raises(RuntimeError, match='timeout'):
                    await app.run_full_history_scan(db, 'r', '/synthetic')
            assert (await (await db.execute("SELECT last_full_scan_at FROM repositories")).fetchone())[0] == 'old'
            assert await (await db.execute('SELECT commits FROM daily_stats')).fetchall() == [(2,)]
    asyncio.run(check())


def test_history_recomputes_existing_day_and_removed_days(tmp_path):
    path = tmp_path / 'state.db'
    app.init_schema(path)
    async def check():
        async with aiosqlite.connect(path) as db:
            await db.execute("INSERT INTO repositories (id, name, path, added_at, last_full_scan_at) VALUES ('r', 'r', '/synthetic', 'x', '2026-01-01T12:00:00+00:00')")
            await db.executemany('INSERT INTO daily_stats VALUES (?, ?, ?, ?, ?, ?)', [('r','2026-01-01',1,2,0,1), ('r','2025-01-01',9,0,0,0)])
            await db.commit()
            commits = [{'date':'2026-01-01T10:00:00+00:00','insertions':2,'deletions':0,'files_changed':1}, {'date':'2026-01-01T14:00:00+00:00','insertions':3,'deletions':0,'files_changed':1}]
            with patch.object(app, 'scan_full_history', new=AsyncMock(return_value=commits)) as scan:
                await app.run_full_history_scan(db, 'r', '/synthetic')
            assert scan.await_args.kwargs.get('since') is None
            assert await (await db.execute('SELECT date, commits, insertions FROM daily_stats')).fetchall() == [('2026-01-01', 2, 5)]
    asyncio.run(check())


def test_failed_branch_scan_preserves_snapshot(tmp_path):
    path = tmp_path / 'state.db'
    app.init_schema(path)
    async def check():
        async with aiosqlite.connect(path) as db:
            await db.execute("INSERT INTO repositories (id, name, path, added_at) VALUES ('r', 'r', '/synthetic', 'x')")
            await db.execute("INSERT INTO branches (repo_id, name) VALUES ('r', 'main')")
            await db.commit()
            with patch.object(app, 'run_git', new=AsyncMock(return_value=('', 'timeout', -1))):
                with pytest.raises(RuntimeError, match='timeout'):
                    await app.run_branch_scan(db, 'r', '/synthetic')
            assert await (await db.execute('SELECT name FROM branches')).fetchall() == [('main',)]
    asyncio.run(check())


def test_startup_recovers_interrupted_scans(tmp_path):
    path = tmp_path / 'state.db'
    app.init_schema(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO scan_log (scan_type, started_at, status) VALUES ('full', 'x', 'running')")
        db.execute("INSERT INTO scan_log (scan_type, started_at, status) VALUES ('full', 'x', 'completed')")
    app.recover_interrupted_scans(path)
    with sqlite3.connect(path) as db:
        rows = db.execute('SELECT status, finished_at FROM scan_log ORDER BY id').fetchall()
    assert rows[0][0] == 'failed' and rows[0][1]
    assert rows[1] == ('completed', None)


def test_progress_stream_ends_when_queue_stalls():
    async def check():
        response = await app.scan_progress_sse(12345)
        async def timeout(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError
        with patch.object(app.asyncio, 'wait_for', side_effect=timeout):
            assert [chunk async for chunk in response.body_iterator] == []
        assert 12345 not in app._scan_queues
    asyncio.run(check())


def test_history_write_failure_rolls_back_snapshot(tmp_path):
    path = tmp_path / 'state.db'
    app.init_schema(path)
    async def check():
        async with aiosqlite.connect(path) as db:
            await db.execute("INSERT INTO repositories (id, name, path, added_at, last_full_scan_at) VALUES ('r', 'r', '/synthetic', 'x', 'old')")
            await db.execute("INSERT INTO daily_stats VALUES ('r', '2026-01-01', 2, 3, 4, 5)")
            await db.execute("CREATE TRIGGER reject_history BEFORE INSERT ON daily_stats BEGIN SELECT RAISE(ABORT, 'rejected'); END")
            await db.commit()
            commits = [{'date':'2026-01-02T00:00:00+00:00', 'insertions':1, 'deletions':0, 'files_changed':1}]
            with patch.object(app, 'scan_full_history', new=AsyncMock(return_value=commits)):
                with pytest.raises(sqlite3.IntegrityError, match='rejected'):
                    await app.run_full_history_scan(db, 'r', '/synthetic')
            assert await (await db.execute('SELECT date, commits FROM daily_stats')).fetchall() == [('2026-01-01', 2)]
            assert (await (await db.execute('SELECT last_full_scan_at FROM repositories')).fetchone())[0] == 'old'
    asyncio.run(check())


def test_fleet_scan_enables_foreign_keys(tmp_path, monkeypatch):
    path = tmp_path / 'state.db'
    app.init_schema(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO repositories (id, name, path, added_at) VALUES ('r', 'r', ?, 'x')", (str(tmp_path),))
        db.execute("INSERT INTO scan_log (scan_type, started_at, status) VALUES ('deps', 'x', 'running')")
    monkeypatch.setattr(app, 'DB_PATH', path)
    async def check_fk(db, *_):
        assert (await (await db.execute('PRAGMA foreign_keys')).fetchone())[0] == 1
    with patch.object(app, 'run_dep_scan_for_repo', side_effect=check_fk) as scan:
        asyncio.run(app.run_fleet_scan(1, 'deps'))
    assert scan.await_count == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT status FROM scan_log').fetchone() == ('completed',)
