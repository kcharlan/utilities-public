"""A1 cold trace scan, hand-derived from CodexPriority.swift @ 3bbf6bc48."""

import json
import sqlite3
import stat
from contextlib import closing

import pytest

from fixturegen import CodexHome


def homes(tmp_path):
    source = CodexHome(tmp_path / 'synthetic-codex-home')
    runtime = tmp_path / 'synthetic-runtime-home'
    runtime.mkdir()
    return source, runtime


def request(source, turn='synthetic-turn', model='gpt-5'):
    return source.priority_request_row(turn, thread_id='synthetic-thread', model=model, ts=12)


@pytest.mark.parametrize('before', [False, True])
def test_completed_model_maximum_rowid_overrides_request(colophon, tmp_path, before):
    source, runtime = homes(tmp_path)
    completed = [source.completed_row('synthetic-turn', 'gpt-5-mini', 99),
                 source.completed_row('synthetic-turn', 'gpt-5.4', 1)]
    source.trace_db(completed + [request(source)] if before else [request(source)] + completed)
    result = colophon.load_priority_turns(source.root, runtime)
    assert result.turns['synthetic-turn'] == {
        'thread_id': 'synthetic-thread', 'model': 'gpt-5.4', 'timestamp': '12',
        'first_seen_ms': result.turns['synthetic-turn']['first_seen_ms']}
    assert type(result.turns['synthetic-turn']['first_seen_ms']) is int
    assert result.messages == []


def test_submission_priority_row(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    source.trace_db([source.submission_priority_row('synthetic-turn', thread_id='synthetic-thread', ts=42)])
    result = colophon.load_priority_turns(source.root, runtime)
    assert result.turns['synthetic-turn']['model'] is None
    assert result.turns['synthetic-turn']['timestamp'] == '42'


@pytest.mark.parametrize('others,model', [(4095, 'gpt-5-mini'), (4096, 'gpt-5')])
def test_pending_completion_fifo_boundary(colophon, tmp_path, others, model):
    # 889–921: insertion count >4096 evicts earliest pending turn, not >=4096.
    source, runtime = homes(tmp_path)
    source.trace_db([source.completed_row('synthetic-turn', 'gpt-5-mini', 0)] +
                    [source.completed_row(f'synthetic-other-{n}', 'gpt-5-mini', 0) for n in range(others)] +
                    [request(source)])
    assert colophon.load_priority_turns(source.root, runtime).turns['synthetic-turn']['model'] == model


def test_known_priority_completion_not_subject_to_pending_eviction(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    source.trace_db([request(source), source.completed_row('synthetic-turn', 'gpt-5-mini', 0)] +
                   [source.completed_row(f'synthetic-other-{n}', 'gpt-5', 0) for n in range(4100)] +
                   [request(source, model='gpt-5.4')])
    assert colophon.load_priority_turns(source.root, runtime).turns['synthetic-turn']['model'] == 'gpt-5-mini'


@pytest.mark.parametrize('body', [
    'turn.id=synthetic-turn websocket request: {"type":"response.create","service_tier":"standard"}',
    'turn.id=synthetic-turn websocket request: []',
    'turn.id=synthetic-turn websocket request: {"type":"response.create","service_tier":true}',
    'turn.id=synthetic-turn websocket request: {"type":"response.create","service_tier":"priority","model":"\\ud800"}',
    'websocket event: {"type":"response.completed","response":{"model":"gpt-5"}}',
    'Submission sub=Submission { id: "", service_tier: Some(Some("priority")) }',
    'websocket request: {} Submission sub=Submission { id: "synthetic-turn", service_tier: Some(Some("priority")) }',
])
def test_invalid_or_nonpriority_rows_are_not_evidence(colophon, tmp_path, body):
    source, runtime = homes(tmp_path)
    source.trace_db([{'feedback_log_body': body}])
    assert colophon.load_priority_turns(source.root, runtime).turns == {}


def test_prefix_precedence_first_duplicate_json_and_foundation_trim(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    source.trace_db([{'feedback_log_body': 'turn.id=synthetic-prefix, turn_id=synthetic-other thread_id=synthetic-thread] websocket request:\u200b{"type":"response.create","service_tier":"priority","service_tier":"standard","turn_id":"synthetic-json","model":5}\u200b'}])
    entry = colophon.load_priority_turns(source.root, runtime).turns['synthetic-prefix']
    assert entry['thread_id'] == 'synthetic-thread'
    assert entry['model'] is None


def test_priority_turn_canonical_equality_retains_first_spelling(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    source.trace_db([request(source, 'synthetic-cafe\u0301'),
                    source.completed_row('synthetic-caf\u00e9', 'gpt-5-mini', 5)])
    turns = colophon.load_priority_turns(source.root, runtime).turns
    assert list(turns) == ['synthetic-cafe\u0301']
    assert turns['synthetic-cafe\u0301']['model'] == 'gpt-5-mini'


def test_missing_trace_leaves_sticky_only_without_rewrite(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    saved = {'schema': 1, 'turns': {'synthetic-sticky': {
        'thread_id': None, 'model': None, 'timestamp': None, 'first_seen_ms': 7}}}
    file = runtime / 'priority-turns.json'
    file.write_text(json.dumps(saved))
    before = file.stat().st_mtime_ns
    result = colophon.load_priority_turns(source.root, runtime)
    assert result.turns == saved['turns']
    assert result.messages == []
    assert file.stat().st_mtime_ns == before
    assert not (source.root / 'logs_2.sqlite').exists()


def test_sticky_survives_pruning_database_wins_except_first_seen(colophon, tmp_path, monkeypatch):
    source, runtime = homes(tmp_path)
    dbpath = source.trace_db([request(source)])
    monkeypatch.setattr(colophon, 'now_ms', lambda: 1234)
    first = colophon.load_priority_turns(source.root, runtime)
    with closing(sqlite3.connect(dbpath)) as db, db:
        db.execute('DELETE FROM logs')
    assert colophon.load_priority_turns(source.root, runtime).turns == first.turns
    with closing(sqlite3.connect(dbpath)) as db, db:
        db.execute('INSERT INTO logs (ts, feedback_log_body) VALUES (?, ?)',
                   (55, request(source, model='gpt-5-mini')['feedback_log_body']))
    monkeypatch.setattr(colophon, 'now_ms', lambda: 9999)
    latest = colophon.load_priority_turns(source.root, runtime).turns['synthetic-turn']
    assert latest == {'thread_id': 'synthetic-thread', 'model': 'gpt-5-mini',
                      'timestamp': '55', 'first_seen_ms': 1234}
    assert stat.S_IMODE((runtime / 'priority-turns.json').stat().st_mode) == 0o600


def test_locked_database_keeps_sticky_and_reports_error(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    dbpath = source.trace_db([request(source)])
    sticky = colophon.load_priority_turns(source.root, runtime).turns
    with closing(sqlite3.connect(dbpath)) as db:
        db.execute('BEGIN EXCLUSIVE')
        result = colophon.load_priority_turns(source.root, runtime)
        assert result.turns == sticky
        assert any('locked' in message for message in result.messages)
        db.rollback()


@pytest.mark.parametrize('timestamp,expected', [(12, '12'), (12.5, '12.5'),
    (1e20, '1.0e+20'), (1.2345678901234567, '1.2345678901234567'
        if sqlite3.sqlite_version_info >= (3, 52, 0) else '1.23456789012346'),
    ('synthetic-ts\x00suffix', 'synthetic-ts'), (b'synthetic-blob\x00suffix', 'synthetic-blob')])
def test_sqlite_timestamp_column_text_contract(colophon, tmp_path, timestamp, expected):
    # vdbemem.c vdbeMemRenderNum: SQLite3.51 uses15 significant digits;
    # SQLite3.52+ default17. Synthetic Swift3.54 column_text corroborates17.
    source, runtime = homes(tmp_path)
    source.trace_db([{'ts': timestamp, 'feedback_log_body': request(source)['feedback_log_body']}])
    assert colophon.load_priority_turns(source.root, runtime).turns['synthetic-turn']['timestamp'] == expected


def test_sqlite_body_c_string_stops_at_nul(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    source.trace_db([{'feedback_log_body': 'synthetic\x00' + request(source)['feedback_log_body']}])
    assert colophon.load_priority_turns(source.root, runtime).turns == {}


def test_corrupt_sticky_is_not_priority_evidence(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    (runtime / 'priority-turns.json').write_text('{synthetic-invalid-json')
    result = colophon.load_priority_turns(source.root, runtime)
    assert result.turns == {}
    assert result.messages


def test_trace_connection_uses_readonly_uri_timeout_and_closes(colophon, tmp_path, monkeypatch):
    source, runtime = homes(tmp_path)
    source.trace_db([request(source)])
    real_connect = sqlite3.connect
    connections = []
    queries = []

    def capture(database, **kwargs):
        assert database == f'{(source.root / "logs_2.sqlite").as_uri()}?mode=ro'
        assert kwargs == {'uri': True, 'timeout': 0.25}
        db = real_connect(database, **kwargs)
        db.set_trace_callback(queries.append)
        connections.append(db)
        return db

    monkeypatch.setattr(colophon.sqlite3, 'connect', capture)
    colophon.load_priority_turns(source.root, runtime)
    assert len(queries) == 1
    assert 'rowid > 0 and ts >= 0' in queries[0]
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connections[0].execute('SELECT 1')


@pytest.mark.parametrize('number', [0.0, -0.0, 1e20, 1e-20, 1.2345678901234567,
                                   1.7976931348623157e308, 5e-324, float('inf')])
def test_real_text_matches_sqlite_column_cast(colophon, number):
    # Independent synthetic SQLite CAST validates column_text's REAL conversion.
    with closing(sqlite3.connect(':memory:')) as db:
        expected = db.execute('SELECT CAST(? AS TEXT)', (number,)).fetchone()[0]
    assert colophon._codex_sqlite_text(number) == expected


@pytest.mark.parametrize('decode_error', [False, True])
def test_native_sqlite_allocation_is_freed_on_every_exit(colophon, monkeypatch, decode_error):
    # A synthetic native buffer is held alive independently of the adapter.
    import ctypes
    buffer = ctypes.create_string_buffer(b'synthetic-real-text')
    pointer = ctypes.addressof(buffer)
    released = []

    class Formatter:
        def sqlite3_mprintf(self, format, value):
            assert format == (b'%!.17g' if sqlite3.sqlite_version_info >= (3, 52, 0) else b'%!.15g')
            assert value.value == 1.25
            return pointer

        def sqlite3_free(self, value):
            released.append(value)

    monkeypatch.setattr(colophon, '_codex_sqlite_formatter', lambda: Formatter())
    if decode_error:
        def fail_read(value):
            raise RuntimeError('synthetic native read failure')
        monkeypatch.setattr(colophon.ctypes, 'string_at', fail_read)
        with pytest.raises(RuntimeError, match='synthetic native read failure'):
            colophon._codex_sqlite_text(1.25)
    else:
        assert colophon._codex_sqlite_text(1.25) == 'synthetic-real-text'
    assert released == [pointer]


def test_native_sqlite_failed_allocation_is_not_freed(colophon, monkeypatch):
    class Formatter:
        def sqlite3_mprintf(self, format, value):
            return None

        def sqlite3_free(self, value):
            pytest.fail('failed allocation transfers no ownership')

    monkeypatch.setattr(colophon, '_codex_sqlite_formatter', lambda: Formatter())
    with pytest.raises(MemoryError, match='SQLite text allocation failed'):
        colophon._codex_sqlite_text(1.25)


def test_malformed_sticky_entries_never_establish_priority(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    valid = {'thread_id': None, 'model': None, 'timestamp': None, 'first_seen_ms': 5}
    (runtime / 'priority-turns.json').write_text(json.dumps({'schema': 1, 'turns': {
        'synthetic-valid': valid, 'synthetic-bad': {**valid, 'first_seen_ms': True},
        'synthetic-no-clock': {'model': 'gpt-5'}, '': valid}}))
    result = colophon.load_priority_turns(source.root, runtime)
    assert result.turns == {'synthetic-valid': valid}
    assert len(result.messages) == 3


def test_live_wal_trace_reads_latest_committed_row(colophon, tmp_path):
    source, runtime = homes(tmp_path)
    database = source.trace_db([request(source)])
    marker = source.root / 'synthetic-marker.txt'
    marker.write_text('Synthetic non-SQLite source must stay unchanged')
    with closing(sqlite3.connect(database)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('INSERT INTO logs (ts, feedback_log_body) VALUES (?,?)',
            (15, source.completed_row('synthetic-turn', 'gpt-5-mini', 15)['feedback_log_body']))
        writer.commit()
        before = database.read_bytes()
        assert colophon.load_priority_turns(source.root, runtime).turns['synthetic-turn']['model'] == 'gpt-5-mini'
        assert database.read_bytes() == before
        assert marker.read_text() == 'Synthetic non-SQLite source must stay unchanged'
