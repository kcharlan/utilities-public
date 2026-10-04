"""Codex metadata and full/display titles from isolated synthetic homes."""
import json
import sqlite3
from contextlib import closing
from dataclasses import is_dataclass
from pathlib import Path

import pytest

from fixturegen import CodexHome, THREAD_COLUMNS


def api(module, name):
    value = getattr(module, name, None)
    assert callable(value), f'Task 9 interface {name} is missing'
    return value


def load(module, home):
    return api(module, 'load_codex_metadata')(home)


def select(module, meta=None, info=None, request=None, *, cwd=None, session_id='synthetic-id'):
    return api(module, 'select_title')(meta, info or {}, request, cwd=cwd,
        session_id=session_id, path=Path('/synthetic/logs/synthetic-file.jsonl'))


def database_snapshot(path):
    return path.read_bytes(), path.stat().st_mtime_ns


def test_empty_metadata_dataclass_and_independent_defaults(colophon, codex_home):
    first, second = load(colophon, codex_home), load(colophon, codex_home)
    assert is_dataclass(first)
    assert first.threads == first.index_titles == first.desktop_titles == {}
    assert first.spawn_parents == first.rollout_paths == {}
    assert first.errors == []
    first.errors.append('Synthetic error')
    assert second.errors == []


@pytest.mark.parametrize('chosen,source', list(enumerate([
    'database_name', 'session_index', 'desktop_title', 'rollout_title',
    'database_title', 'first_user_message', 'database_first_user_message'])))
def test_every_title_source_and_priority(colophon, chosen, source):
    candidates = ['Synthetic title '+str(n) for n in range(7)]
    candidates[:chosen] = [' \t\n'] * chosen
    info = dict(zip(('name','index_title','desktop_title','unused','title','unused2','first_user_message'), candidates))
    assert select(colophon, {'rollout_title':candidates[3]}, info, candidates[5]) == (candidates[chosen], source)


@pytest.mark.parametrize('value', [None, '', ' \n\t', 12, True, [], {}, b'Synthetic title'])
def test_invalid_title_candidates_are_not_text_evidence(colophon, value):
    info = dict.fromkeys(('name','index_title','desktop_title','title','first_user_message'),value)
    assert select(colophon, {'rollout_title':value}, info, value) == ('synthetic-id','session_id')


@pytest.mark.parametrize('cwd,session_id,expected', [
    ('/synthetic/projects/alpha/', 'synthetic-id', ('alpha','folder')),
    ('/', 'synthetic-id', ('synthetic-id','session_id')),
    ('/synthetic/ \t', 'synthetic-id', ('synthetic-id','session_id')),
    (None, 'synthetic-id', ('synthetic-id','session_id')),
    ('', None, ('synthetic-file','filename')),
    (' \t', ' ', ('synthetic-file','filename')),
    (123, False, ('synthetic-file','filename')),
])
def test_title_fallbacks(colophon, cwd, session_id, expected):
    assert select(colophon, cwd=cwd, session_id=session_id) == expected


def test_full_text_preserved_separately_from_display(colophon):
    full = '  Synthetic title\nSynthetic continuation'
    assert select(colophon, info={'name':full}) == (full,'database_name')
    assert api(colophon,'display_title')(full) == '  Synthetic title'


@pytest.mark.parametrize('text,expected', [
    ('x'*80, 'x'*80), ('x'*81, 'x'*80+'…'),
    ('Synthetic '*9, ('Synthetic '*8).rstrip()+'…'),
    ('x'*79+' '+'y'*8, 'x'*79+'…'),
    ('x'*80+' '+'y', 'x'*80+'…'),
    ('Synthetic\t'+'x'*80, 'Synthetic…'),
    ('Synthetic\u2003'+'x'*80, 'Synthetic…'),
    ('x'*81+'\nSynthetic next line', 'x'*80+'…'),
])
def test_display_title_boundaries(colophon, text, expected):
    full, source = select(colophon, info={'name':text})
    assert (full,source) == (text,'database_name')
    assert api(colophon,'display_title')(full) == expected


@pytest.mark.parametrize('path,expected', [
    ('/root/code_review','code review'), ('/root/synthetic-task','synthetic task'),
    ('synthetic_task','synthetic task'), (None,'subagent'), ('','subagent'),
    ('/root/','subagent'), ('   ','subagent'), (12,'subagent'),
])
def test_humanized_agent_path(colophon, path, expected):
    assert api(colophon,'humanize_agent_path')(path) == expected


@pytest.mark.parametrize('orphan', [False,True])
@pytest.mark.parametrize('nickname', ['Agent-Alpha', None, '', ' \t', 123, {}])
def test_subagent_and_orphan_titles(colophon, orphan, nickname):
    meta = {'agent_path':'/root/code_review','agent_nickname':nickname,'orphaned':orphan,
            'rollout_title':'Synthetic title must not override path'}
    expected = 'code review · Agent-Alpha' if nickname == 'Agent-Alpha' else 'code review'
    assert api(colophon,'subagent_title')(meta) == (expected,'agent_path')


def test_subagent_missing_metadata(colophon):
    assert api(colophon,'subagent_title')(None) == ('subagent','agent_path')


def test_database_columns_null_empty_and_main_file_preservation(colophon, codex_home):
    row = {key:'Synthetic '+key for key in THREAD_COLUMNS}
    row.update(id='synthetic-thread', cwd='/synthetic/projects/alpha', archived=0,
               name=None, title='', rollout_path='/synthetic/logs/synthetic-rollout.jsonl')
    path = CodexHome(codex_home).state_db([row])
    before = database_snapshot(path)
    metadata = load(colophon,codex_home)
    assert metadata.threads == {'synthetic-thread':{k:v for k,v in row.items() if v is not None and v != ''}}
    assert metadata.rollout_paths == {'synthetic-thread':row['rollout_path']}
    assert metadata.errors == []
    assert database_snapshot(path) == before


def test_newest_numeric_database_wins_without_merging(colophon, codex_home):
    home = CodexHome(codex_home)
    home.state_db([{'id':'synthetic-old','name':'Synthetic old'}],version=9)
    home.state_db([{'id':'synthetic-new','name':'Synthetic new'}],version=10)
    (codex_home/'state_bad.sqlite').write_bytes(b'Synthetic invalid candidate')
    assert load(colophon,codex_home).threads == {'synthetic-new':{'id':'synthetic-new','name':'Synthetic new'}}


def test_empty_newest_database_is_authoritative(colophon, codex_home):
    home = CodexHome(codex_home)
    home.state_db([{'id':'synthetic-old'}],version=5)
    home.state_db([],version=6)
    metadata = load(colophon,codex_home)
    assert metadata.threads == {}
    assert metadata.errors == []


def test_corrupt_newest_database_falls_back_with_error(colophon, codex_home):
    CodexHome(codex_home).state_db([{'id':'synthetic-old'}],version=5)
    (codex_home/'state_6.sqlite').write_bytes(b'Synthetic corrupt SQLite')
    metadata = load(colophon,codex_home)
    assert metadata.threads == {'synthetic-old':{'id':'synthetic-old'}}
    assert len(metadata.errors) == 1
    assert 'state_6.sqlite' in metadata.errors[0]
    assert 'not a database' in metadata.errors[0]


@pytest.mark.parametrize('ddl', ['CREATE TABLE unrelated (id TEXT)', 'CREATE TABLE threads (name TEXT)'])
def test_missing_id_schema_falls_back(colophon, codex_home, ddl):
    CodexHome(codex_home).state_db([{'id':'synthetic-old'}],version=5)
    with closing(sqlite3.connect(codex_home/'state_6.sqlite')) as db, db:
        db.execute(ddl)
    metadata = load(colophon,codex_home)
    assert metadata.threads == {'synthetic-old':{'id':'synthetic-old'}}
    assert len(metadata.errors) == 1
    assert 'state_6.sqlite' in metadata.errors[0]


def test_partial_schema_and_extra_columns(colophon, codex_home):
    with closing(sqlite3.connect(codex_home/'state_5.sqlite')) as db, db:
        db.execute('CREATE TABLE threads (id TEXT, title TEXT, synthetic_extra TEXT)')
        db.execute("INSERT INTO threads VALUES ('synthetic-thread','Synthetic title','Synthetic excluded')")
    metadata = load(colophon,codex_home)
    assert metadata.threads == {'synthetic-thread':{'id':'synthetic-thread','title':'Synthetic title'}}


@pytest.mark.parametrize('identifier', [None,'',' \t',123,b'synthetic-id'])
def test_invalid_database_ids_are_ignored(colophon, codex_home, identifier):
    with closing(sqlite3.connect(codex_home/'state_5.sqlite')) as db, db:
        db.execute('CREATE TABLE threads (id, name TEXT)')
        db.execute('INSERT INTO threads VALUES (?,?)',(identifier,'Synthetic ignored'))
    assert load(colophon,codex_home).threads == {}


def test_ambiguous_duplicate_database_ids_are_not_evidence(colophon, codex_home):
    CodexHome(codex_home).state_db([{'id':'synthetic-duplicate','name':'Synthetic first'},
        {'id':'synthetic-duplicate','name':'Synthetic second'},{'id':'synthetic-ok','name':'Synthetic kept'}])
    metadata = load(colophon,codex_home)
    assert metadata.threads == {'synthetic-ok':{'id':'synthetic-ok','name':'Synthetic kept'}}
    assert len(metadata.errors) == 1
    assert 'duplicate' in metadata.errors[0]


def test_identical_duplicate_database_rows_keep_unambiguous_evidence(colophon, codex_home):
    row = {'id':'synthetic-thread','name':'Synthetic title'}
    CodexHome(codex_home).state_db([row,row])
    metadata = load(colophon,codex_home)
    assert metadata.threads == {'synthetic-thread':row}
    assert metadata.errors == []


def test_locked_database_falls_back_to_log_title(colophon, codex_home):
    path = CodexHome(codex_home).state_db([{'id':'synthetic-thread','name':'Synthetic DB title'}])
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('BEGIN EXCLUSIVE')
        metadata = load(colophon,codex_home)
        assert metadata.threads == {}
        assert len(metadata.errors) == 1
        assert 'locked' in metadata.errors[0]
        assert select(colophon, {'rollout_title':'Synthetic log title'}, metadata.threads.get('synthetic-thread')) == ('Synthetic log title','rollout_title')
        writer.rollback()


def test_database_uri_escapes_legal_path_characters(colophon, tmp_path):
    home = tmp_path/'synthetic ?#% home'
    CodexHome(home).state_db([{'id':'synthetic-thread'}])
    assert load(colophon,home).threads == {'synthetic-thread':{'id':'synthetic-thread'}}


def test_sqlite_connect_contract_and_close(colophon, codex_home, monkeypatch):
    path = CodexHome(codex_home).state_db([{'id':'synthetic-thread'}])
    actual_connect = sqlite3.connect
    connections = []
    def connect(database_uri, **options):
        assert database_uri == path.absolute().as_uri()+'?mode=ro'
        assert options == {'uri':True,'timeout':1}
        connection = actual_connect(database_uri,**options)
        connections.append(connection)
        return connection
    monkeypatch.setattr(sqlite3,'connect',connect)
    load(colophon,codex_home)
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        connections[0].execute('SELECT 1')


def test_sqlite_connection_closes_on_schema_failure(colophon, codex_home, monkeypatch):
    (codex_home/'state_5.sqlite').write_bytes(b'Synthetic corrupt SQLite')
    actual_connect = sqlite3.connect
    connections = []
    def connect(database_uri, **options):
        connection = actual_connect(database_uri,**options)
        connections.append(connection)
        return connection
    monkeypatch.setattr(sqlite3,'connect',connect)
    metadata = load(colophon,codex_home)
    assert len(metadata.errors) == 1
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        connections[0].execute('SELECT 1')


def test_live_wal_reads_latest_data_without_modifying_main_or_non_sqlite_files(colophon, codex_home):
    path = CodexHome(codex_home).state_db([{'id':'synthetic-thread','name':'Synthetic old'}])
    sentinel = codex_home/'synthetic-sentinel.txt'
    sentinel.write_text('Synthetic non-SQLite data')
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("UPDATE threads SET name='Synthetic newest'")
        writer.commit()
        before, sentinel_before = database_snapshot(path), database_snapshot(sentinel)
        metadata = load(colophon,codex_home)
        assert metadata.threads['synthetic-thread']['name'] == 'Synthetic newest'
        assert database_snapshot(path) == before
        assert database_snapshot(sentinel) == sentinel_before


@pytest.mark.parametrize('pair', [('child_thread_id','parent_thread_id'),('child_id','parent_id')])
def test_spawn_edge_column_pairs(colophon, codex_home, pair):
    path = CodexHome(codex_home).state_db([{'id':'synthetic-child'}])
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(f'CREATE TABLE thread_spawn_edges ({pair[0]} TEXT, {pair[1]} TEXT)')
        db.execute('INSERT INTO thread_spawn_edges VALUES (?,?)',('synthetic-child','synthetic-parent'))
    assert load(colophon,codex_home).spawn_parents == {'synthetic-child':'synthetic-parent'}


def test_spawn_edges_fixture_and_absent_table(colophon, codex_home):
    home = CodexHome(codex_home)
    home.state_db([{'id':'synthetic-child'}],spawn_edges=[('synthetic-parent','synthetic-child')])
    assert load(colophon,codex_home).spawn_parents == {'synthetic-child':'synthetic-parent'}
    home.state_db([{'id':'synthetic-next'}],version=6)
    metadata = load(colophon,codex_home)
    assert metadata.spawn_parents == {}
    assert metadata.errors == []


def test_unrecognized_spawn_schema_keeps_threads_records_error(colophon, codex_home):
    path = CodexHome(codex_home).state_db([{'id':'synthetic-thread'}])
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE thread_spawn_edges (unknown TEXT)')
    metadata = load(colophon,codex_home)
    assert metadata.threads == {'synthetic-thread':{'id':'synthetic-thread'}}
    assert metadata.spawn_parents == {}
    assert len(metadata.errors) == 1
    assert 'thread_spawn_edges' in metadata.errors[0]


def test_invalid_and_conflicting_spawn_edges_are_not_evidence(colophon, codex_home):
    CodexHome(codex_home).state_db([],spawn_edges=[
        ('synthetic-parent','synthetic-child'),('synthetic-other','synthetic-child'),
        ('synthetic-parent','synthetic-child'),('', 'synthetic-empty-parent'),
        ('synthetic-parent',None),('synthetic-parent',' \t'),
        ('synthetic-valid-parent','synthetic-valid-child'),
        ('synthetic-valid-parent','synthetic-valid-child')])
    metadata = load(colophon,codex_home)
    assert metadata.spawn_parents == {'synthetic-valid-child':'synthetic-valid-parent'}
    assert len(metadata.errors) == 1
    assert 'conflicting' in metadata.errors[0]


def test_session_index_latest_timestamp_and_later_line_tie(colophon, codex_home):
    CodexHome(codex_home).session_index([
        {'id':'synthetic-id','thread_name':'Synthetic newest','updated_at':'2030-01-02T00:00:00Z'},
        {'id':'synthetic-id','thread_name':'Synthetic oldest','updated_at':'2030-01-01T00:00:00Z'},
        {'id':'synthetic-id','thread_name':'Synthetic tied','updated_at':'2030-01-02T00:00:00+00:00'},
        {'id':'synthetic-id','thread_name':'  ','updated_at':'2030-01-03T00:00:00Z'},
        {'id':'synthetic-offset','thread_name':'Synthetic UTC newest','updated_at':'2030-01-01T01:00:00Z'},
        {'id':'synthetic-offset','thread_name':'Synthetic local older','updated_at':'2030-01-01T02:00:00+02:00'},
    ])
    assert load(colophon,codex_home).index_titles == {'synthetic-id':'Synthetic tied','synthetic-offset':'Synthetic UTC newest'}


def test_session_index_fractional_precision_is_not_invented_tie(colophon, codex_home):
    CodexHome(codex_home).session_index([
        {'id':'synthetic-id','thread_name':'Synthetic newest','updated_at':'2030-01-01T00:00:00.000000002Z'},
        {'id':'synthetic-id','thread_name':'Synthetic older','updated_at':'2030-01-01T00:00:00.000000001Z'},
    ])
    assert load(colophon,codex_home).index_titles == {'synthetic-id':'Synthetic newest'}


def test_session_index_equivalent_fraction_is_later_line_tie(colophon, codex_home):
    CodexHome(codex_home).session_index([
        {'id':'synthetic-id','thread_name':'Synthetic first','updated_at':'2030-01-01T00:00:00.1Z'},
        {'id':'synthetic-id','thread_name':'Synthetic second','updated_at':'2030-01-01T00:00:00.100Z'}])
    assert load(colophon,codex_home).index_titles == {'synthetic-id':'Synthetic second'}


def test_metadata_preserves_nonblank_identifier_and_title_spelling(colophon, codex_home):
    home = CodexHome(codex_home)
    home.state_db([{'id':' synthetic-id ','name':' Synthetic DB title '}])
    home.session_index([{'id':' synthetic-id ','thread_name':' Synthetic index title ',
                         'updated_at':'2030-01-01T00:00:00Z'}])
    home.global_state({' synthetic-id ':' Synthetic desktop title ','':'Synthetic invalid',' \t':'Synthetic invalid'})
    metadata = load(colophon,codex_home)
    assert metadata.threads == {' synthetic-id ':{'id':' synthetic-id ','name':' Synthetic DB title '}}
    assert metadata.index_titles == {' synthetic-id ':' Synthetic index title '}
    assert metadata.desktop_titles == {' synthetic-id ':' Synthetic desktop title '}


@pytest.mark.parametrize('invalid',[None,'',False,123,{},'synthetic-invalid-time','2030-02-30T00:00:00Z'])
def test_invalid_index_timestamp_is_not_ordering_evidence(colophon, codex_home, invalid):
    CodexHome(codex_home).session_index([
        {'id':'synthetic-id','thread_name':'Synthetic valid','updated_at':'2030-01-01T00:00:00Z'},
        {'id':'synthetic-id','thread_name':'Synthetic unusable','updated_at':invalid},
        {'id':'synthetic-invalid-only','thread_name':'Synthetic unusable','updated_at':invalid}])
    assert load(colophon,codex_home).index_titles == {'synthetic-id':'Synthetic valid'}


def test_malformed_index_lines_and_invalid_title_types_are_ignored(colophon, codex_home):
    path = CodexHome(codex_home).session_index([
        {'id':'synthetic-ok','thread_name':'Synthetic kept','updated_at':'2030-01-01T00:00:00Z'},
        {'id':'','thread_name':'Synthetic ignored','updated_at':'2030-01-01T00:00:00Z'},
        {'id':12,'thread_name':'Synthetic ignored','updated_at':'2030-01-01T00:00:00Z'},
        {'id':'synthetic-invalid','thread_name':{},'updated_at':'2030-01-01T00:00:00Z'}])
    with path.open('ab') as stream:
        stream.write(b'not synthetic JSON\n[]\nnull\n\xff\n')
    assert load(colophon,codex_home).index_titles == {'synthetic-ok':'Synthetic kept'}


@pytest.mark.parametrize('value',[None, [], 'Synthetic invalid', {},
    {'thread-titles':[]},{'thread-titles':{'titles':[]}},
    {'thread-titles':{'titles':{'synthetic-id':False,'synthetic-empty':' \t'}}}])
def test_malformed_global_state_ignored(colophon, codex_home, value):
    (codex_home/'.codex-global-state.json').write_text(json.dumps(value))
    assert load(colophon,codex_home).desktop_titles == {}


def test_invalid_global_json_and_utf8_ignored(colophon, codex_home):
    path = codex_home/'.codex-global-state.json'
    for raw in (b'not synthetic JSON',b'\xff'):
        path.write_bytes(raw)
        assert load(colophon,codex_home).desktop_titles == {}


def test_loaded_metadata_title_adapter_priority(colophon, codex_home):
    home = CodexHome(codex_home)
    home.state_db([{'id':'synthetic-id','title':'Synthetic DB title'}])
    home.session_index([{'id':'synthetic-id','thread_name':'Synthetic index title','updated_at':'2030-01-01T00:00:00Z'}])
    home.global_state({'synthetic-id':'Synthetic desktop title','synthetic-invalid':[], 'synthetic-blank':'  '})
    metadata = load(colophon,codex_home)
    assert metadata.desktop_titles == {'synthetic-id':'Synthetic desktop title'}
    info = {**metadata.threads['synthetic-id'],'index_title':metadata.index_titles.get('synthetic-id'),
            'desktop_title':metadata.desktop_titles.get('synthetic-id')}
    assert select(colophon, {'rollout_title':'Synthetic rollout'}, info, 'Synthetic request') == ('Synthetic index title','session_index')
    del info['index_title']
    assert select(colophon, {'rollout_title':'Synthetic rollout'}, info, 'Synthetic request') == ('Synthetic desktop title','desktop_title')
