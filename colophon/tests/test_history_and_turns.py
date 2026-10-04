"""Owned history and logged turn timing, using only invented temporary logs."""
import json
import weakref

import pytest

from fixturegen import CodexHome, iso, uuid7

TURN_FIELDS = {'key', 'turn_id', 'start_ms', 'start_src', 'end_ms', 'end_src',
               'end_kind', 'reported_ms', 'ttft_ms', 'start_rec', 'last_ms'}


@pytest.fixture
def log(codex_home):
    builder = CodexHome(codex_home).log()
    return builder, builder.clock


def parse(module, builder):
    path = builder.write()
    stat = path.stat()
    return module.parse_log_file(path, size=stat.st_size, mtime_ns=stat.st_mtime_ns, archived=False)


def timing(module, record, index=0):
    helper = getattr(module, 'turn_timing', None)
    assert callable(helper), 'Task 4 turn_timing is missing'
    collapsed = record['wrapper_ts']['count'] > 1 and record['wrapper_ts']['distinct'] == 1
    return helper(record['turns'][index], collapsed=collapsed)


def test_path_a_own_lifecycle(colophon, log):
    b, t = log
    own = uuid7(t + 3000)
    r = parse(colophon, b.meta(at=t, forked_from_id='synthetic-parent')
              .world_state(at=t + 1000).task_started(own, at=t + 3000).task_complete(at=t + 8000))
    assert r['history'] == {'path': 'A', 'boundary_rec': 2, 'method': 'own_lifecycle',
                            'inherited_recs': [[1, 2]], 'inherited_lines': [[1, 2]]}
    assert [x['key'] for x in r['turns']] == [own]
    assert r['owned_span'] == {'first_ms': t, 'last_ms': t + 8000}


def test_path_a_last_synthetic_start_verified_by_completion(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t, forked_from_id='synthetic-parent')
              .task_started('rollout-synthetic-old', at=t, started_at=(t + 2000) / 1000)
              .world_state(at=t + 1000)
              .task_started('rollout-synthetic-new', at=t + 2000, started_at=(t + 2000) / 1000)
              .task_complete(uuid7(t + 2000), at=t + 5000, started_at=(t + 2000) / 1000))
    assert r['history']['boundary_rec'] == 3
    assert r['history']['method'] == 'synthetic_start_verified_by_completion'
    assert r['history']['inherited_recs'] == [[1, 3]]
    assert r['turns'][0]['key'] == 'rollout-synthetic-new'


def test_path_a_unresolved_has_no_turns(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t, forked_from_id='synthetic-parent')
              .task_started(uuid7(t - 10000), at=t).task_complete(at=t + 4000))
    assert r['history']['method'] == 'unresolved'
    assert r['history']['boundary_rec'] == 3
    assert r['history']['inherited_recs'] == [[1, 3]]
    assert r['turns'] == []


def test_path_a_started_at_vetoes_recent_uuid(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t, forked_from_id='synthetic-parent')
              .task_started(uuid7(t), at=t + 1000, started_at=(t - 1001) / 1000)
              .task_complete(at=t + 3000, started_at=(t - 1001) / 1000)
              .task_started(uuid7(t + 4000), at=t + 4000))
    assert r['history']['boundary_rec'] == 3
    assert r['history']['inherited_recs'] == [[1, 3]]


def test_path_a_non_uuid_start_overrides_started_at_veto(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t, forked_from_id='synthetic-parent')
              .task_started('synthetic-owned', at=t + 1000, started_at=(t - 5000) / 1000)
              .world_state(at=t + 2000))
    assert r['history']['boundary_rec'] == 1
    # The independent earlier-event-time rule still excludes this start.
    assert r['history']['inherited_recs'] == [[1, 2]]
    assert r['turns'] == []


@pytest.mark.parametrize('offset,expected', [(-1001, 'unresolved'), (-1000, 'own_lifecycle')])
def test_path_a_uuid_threshold_and_case(colophon, log, offset, expected):
    b, t = log
    r = parse(colophon, b.meta(at=t, forked_from_id='synthetic-parent')
              .task_started(uuid7(t + offset).upper(), at=t + 5000))
    assert r['history']['method'] == expected


@pytest.mark.parametrize('end', ['settings', 'thread_id', 'started_at', 'event_time'])
def test_path_b_end_conditions(colophon, log, end):
    b, t = log
    b.meta(at=t).meta(at=t + 100, id='synthetic-ancestor').world_state(at=t + 200)
    if end == 'settings':
        b.thread_settings(at=t + 1000)
    elif end == 'thread_id':
        b.world_state(at=t + 1000, thread_id=b.session_id)
    elif end == 'started_at':
        # Less than 2 s from wrapper: event_time uses the owned wrapper time.
        b.task_started(at=t + 500, started_at=(t - 1000) / 1000)
    else:
        b.task_started(at=t + 1000, started_at=None)
    r = parse(colophon, b.world_state(at=t + 2000))
    assert r['history'] == {'path': 'B', 'boundary_rec': None, 'method': None,
                            'inherited_recs': [[1, 3]], 'inherited_lines': [[1, 3]]}


def test_path_b_two_runs_and_same_identity_header(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t).meta(at=t + 10).meta(at=t + 20, id='synthetic-ancestor')
              .thread_settings(at=t + 30).meta(at=t + 40, id='synthetic-other-ancestor')
              .world_state(at=t + 50).world_state(at=t + 60, thread_id=b.session_id))
    assert r['history']['inherited_recs'] == [[2, 3], [4, 6]]


INVALID_IDENTITIES = [
    pytest.param({}, id='missing'),
    pytest.param({'id': None}, id='null'),
    pytest.param({'id': True}, id='true'),
    pytest.param({'id': False}, id='false'),
    pytest.param({'id': 0}, id='zero'),
    pytest.param({'id': 7}, id='integer'),
    pytest.param({'id': []}, id='array'),
    pytest.param({'id': {}}, id='object'),
    pytest.param({'id': ''}, id='empty-string'),
]


@pytest.mark.parametrize('identity_fields', INVALID_IDENTITIES)
def test_path_b_invalid_later_identity_is_not_mismatch_evidence(colophon, log, identity_fields):
    b, t = log
    # Raw fields omit all five alternate D18 identity candidates.
    b.meta(at=t)._emit('session_meta', {'timestamp': iso(t + 1000), **identity_fields}, at=t + 1000)
    r = parse(colophon, b.world_state(at=t + 1500).task_complete('synthetic-owned', at=t + 2000))
    assert r['history']['inherited_recs'] == []
    assert r['history']['inherited_lines'] == []
    assert r['owned_span'] == {'first_ms': t, 'last_ms': t + 2000}
    assert [turn['key'] for turn in r['turns']] == ['synthetic-owned']
    assert r['extra_meta_count'] == 1


@pytest.mark.parametrize('identity_fields', INVALID_IDENTITIES)
def test_path_b_invalid_original_identity_is_not_mismatch_evidence(colophon, log, identity_fields):
    b, t = log
    b._emit('session_meta', {'timestamp': iso(t), **identity_fields}, at=t)
    b.meta(at=t + 1000, id='synthetic-ancestor')
    r = parse(colophon, b.world_state(at=t + 1500).task_complete('synthetic-owned', at=t + 2000))
    assert r['history']['inherited_recs'] == []
    assert r['history']['inherited_lines'] == []
    assert r['owned_span'] == {'first_ms': t, 'last_ms': t + 2000}
    assert [turn['key'] for turn in r['turns']] == ['synthetic-owned']
    # History validation must not alter true-first SessionMeta/D18 extraction.
    assert r['meta']['id'] == ('' if identity_fields.get('id') == '' else None)


@pytest.mark.parametrize('fallback_position', ['original', 'later'])
def test_path_b_selected_fallback_identity_remains_mismatch_evidence(colophon, log, fallback_position):
    b, t = log
    if fallback_position == 'original':
        b._emit('session_meta', {'id': True, 'session_id': b.session_id, 'timestamp': iso(t)}, at=t)
        b.meta(at=t + 1000, id='synthetic-ancestor')
    else:
        b.meta(at=t)._emit('session_meta', {'id': None, 'session_id': 'synthetic-ancestor',
                                         'timestamp': iso(t + 1000)}, at=t + 1000)
    r = parse(colophon, b.world_state(at=t + 1500).thread_settings(at=t + 2000))
    assert r['meta']['id'] == b.session_id
    assert r['history']['inherited_recs'] == [[1, 3]]
    assert r['owned_span'] == {'first_ms': t, 'last_ms': t + 2000}


@pytest.mark.parametrize('position', ['original', 'later'])
@pytest.mark.parametrize('blank_id', [pytest.param(' ', id='space'),
                                    pytest.param('\t\r\n', id='ascii-whitespace'),
                                    pytest.param('\u00a0\u2003', id='unicode-whitespace')])
def test_path_b_whitespace_identity_is_not_mismatch_evidence(colophon, log, position, blank_id):
    b, t = log
    original = blank_id if position == 'original' else b.session_id
    later = blank_id if position == 'later' else 'synthetic-ancestor'
    b._emit('session_meta', {'id': original, 'timestamp': iso(t)}, at=t)
    b._emit('session_meta', {'id': later, 'timestamp': iso(t + 1000)}, at=t + 1000)
    r = parse(colophon, b.task_complete('synthetic-owned', at=t + 2000))
    assert r['meta']['id'] == original  # D18 extraction remains verbatim.
    assert r['history']['inherited_recs'] == []
    assert r['history']['inherited_lines'] == []
    assert r['owned_span'] == {'first_ms': t, 'last_ms': t + 2000}
    assert [turn['key'] for turn in r['turns']] == ['synthetic-owned']


def test_path_b_nonblank_identity_strings_are_not_trimmed(colophon, log):
    b, t = log
    original = ' \tsynthetic-session\n '
    later = 'synthetic-session'
    b._emit('session_meta', {'id': original, 'timestamp': iso(t)}, at=t)
    b._emit('session_meta', {'id': later, 'timestamp': iso(t + 1000)}, at=t + 1000)
    b.world_state(at=t + 2000, thread_id=later)
    r = parse(colophon, b.world_state(at=t + 3000, thread_id=original)
              .task_complete('synthetic-owned', at=t + 4000))
    assert r['meta']['id'] == original
    # The two nonblank IDs differ verbatim; only the exact original ends the run.
    assert r['history']['inherited_recs'] == [[1, 3]]
    assert r['owned_span'] == {'first_ms': t, 'last_ms': t + 4000}
    assert [turn['key'] for turn in r['turns']] == ['synthetic-owned']


@pytest.mark.parametrize('started,at', [(-1001, 10000), (None, 999)])
def test_path_b_rejects_non_owned_start(colophon, log, started, at):
    b, t = log
    r = parse(colophon, b.meta(at=t).meta(at=t + 10, id='synthetic-ancestor')
              .task_started(at=t + at, started_at=None if started is None else (t + started) / 1000)
              .world_state(at=t + 20000))
    assert r['history']['inherited_recs'] == [[1, 4]]
    assert r['turns'] == []


def test_earlier_event_time_and_physical_line_intervals(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t).raw(b'\nsynthetic malformed\n')
              .world_state(at=t - 1000).raw(b'\n')
              .world_state(at=t - 500).world_state(at=t + 2000).world_state(at=t - 100))
    assert r['history']['inherited_recs'] == [[1, 3], [4, 5]]
    assert r['history']['inherited_lines'] == [[3, 4], [5, 6], [7, 8]]
    assert r['owned_span'] == {'first_ms': t, 'last_ms': t + 2000}
    inherited = getattr(colophon, 'is_inherited', None)
    assert callable(inherited), 'Task 4 is_inherited is missing'
    assert [inherited(r, n) for n in range(5)] == [False, True, True, False, True]


def test_no_meta_has_no_history_filter(colophon, log):
    b, t = log
    r = parse(colophon, b.task_started(at=t).task_complete(at=t + 1000))
    assert r['history']['path'] == 'none'
    assert r['history']['inherited_recs'] == []
    assert r['owned_span'] == {'first_ms': t, 'last_ms': t + 1000}
    assert len(r['turns']) == 1


def test_missing_turn_id_gets_numbered_key(colophon, log):
    b, t = log
    b.meta(at=t)._event('task_started', {}, at=t + 1000)
    b.task_complete(at=t + 2000, turn_id='synthetic-turn-1')
    # An explicit id does not close the anonymous current turn.
    b._event('task_started', {'turn_id': ''}, at=t + 3000)
    r = parse(colophon, b)
    assert [x['key'] for x in r['turns']] == ['turn-1', 'synthetic-turn-1', 'turn-3']
    assert r['turns'][0]['end_kind'] == 'interrupted'


def test_idless_completion_closes_current_and_clears_it(colophon, log):
    b, t = log
    b.meta(at=t).task_started('synthetic-own', at=t + 1000)
    b._event('task_complete', {}, at=t + 2000).world_state(at=t + 9000)
    r = parse(colophon, b)
    assert len(r['turns']) == 1
    assert r['turns'][0]['end_kind'] == 'completed'
    assert r['turns'][0]['last_ms'] == t + 2000


def test_completion_only_embedded_start_and_ttft(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t).task_complete('synthetic-end-only', at=t + 5000,
              started_at=(t + 1000) / 1000, duration_ms=4000, time_to_first_token_ms=12.5))
    turn = r['turns'][0]
    assert set(turn) == TURN_FIELDS
    assert turn['start_ms'] == t + 1000 and turn['start_src'] == 'started_at'
    assert turn['start_rec'] is None
    assert turn['reported_ms'] == 4000 and turn['ttft_ms'] == 12.5
    assert timing(colophon, r) == {'start_ms': t + 1000, 'duration_ms': 4000,
                                   'flags': ['start_from_completion']}


@pytest.mark.parametrize('reported', [None, 3000])
def test_unknown_clock_start_record_prevents_completion_recovery(colophon, log, reported):
    b, t = log
    b.meta(at=t).raw((json.dumps({'type': 'event_msg', 'payload': {
        'type': 'task_started', 'turn_id': 'synthetic-unknown-start'}}) + '\n').encode())
    b.task_complete('synthetic-unknown-start', at=t + 5000,
                    started_at=(t + 1000) / 1000, duration_ms=reported)
    r = parse(colophon, b)
    turn = r['turns'][0]
    assert turn['key'] == turn['turn_id'] == 'synthetic-unknown-start'
    assert turn['start_rec'] == 1
    assert turn['start_ms'] is None
    assert turn['start_src'] == 'record_timestamp'
    expected = {'start_ms': None, 'duration_ms': None, 'flags': ['unknown_duration']} if reported is None else {
        'start_ms': t + 2000, 'duration_ms': 3000, 'flags': ['reported_duration']}
    assert timing(colophon, r) == expected


@pytest.mark.parametrize('value', [-1, True, '12', None, float('inf'), float('nan')])
def test_invalid_reported_timing_is_not_kept(colophon, log, value):
    b, t = log
    b.meta(at=t).task_started(at=t + 1000)
    b.raw((json.dumps({'timestamp': iso(t + 2000), 'type': 'event_msg', 'payload': {
        'type': 'task_complete', 'turn_id': b.turn_id, 'duration_ms': value,
        'time_to_first_token_ms': value}}) + '\n').encode())
    r = parse(colophon, b)
    assert r['turns'][0]['reported_ms'] is None
    assert r['turns'][0]['ttft_ms'] is None


@pytest.mark.parametrize('end_kind', ['task_complete', 'turn_aborted'])
def test_difference_duration_takes_precedence_over_reported(colophon, log, end_kind):
    b, t = log
    b.meta(at=t).task_started(at=t + 1000)
    b._event(end_kind, {'turn_id': b.turn_id, 'duration_ms': 999}, at=t + 3000)
    r = parse(colophon, b)
    assert r['turns'][0]['end_kind'] == ('completed' if end_kind == 'task_complete' else 'aborted')
    assert timing(colophon, r) == {'start_ms': t + 1000, 'duration_ms': 2000, 'flags': []}


def test_reported_duration_with_completed_at_end(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t).task_started(at=t + 1000)
              .task_complete(at=t + 2000, completed_at=(t + 9000) / 1000, duration_ms=2500))
    assert r['turns'][0]['end_src'] == 'completed_at'
    assert timing(colophon, r) == {'start_ms': t + 6500, 'duration_ms': 2500,
                                  'flags': ['reported_duration']}
    assert r['turns'][0]['start_ms'] == t + 1000


def test_completed_at_ms_does_not_force_reported_duration(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t).task_started(at=t + 1000)
              .task_complete(at=t + 2000, completed_at_ms=t + 9000, duration_ms=2500))
    assert r['turns'][0]['end_src'] == 'completed_at_ms'
    assert timing(colophon, r)['duration_ms'] == 8000


def test_reported_duration_without_start(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t).task_complete(at=t + 8000, duration_ms=0))
    assert r['turns'][0]['start_ms'] is None
    assert timing(colophon, r) == {'start_ms': t + 8000, 'duration_ms': 0,
                                  'flags': ['reported_duration']}


@pytest.mark.parametrize('reported', [None, 3000])
def test_collapsed_duration_rules(colophon, log, reported):
    b, t = log
    r = parse(colophon, b.meta(at=t).task_started(at=t, started_at=None)
              .task_complete(at=t, completed_at=None, duration_ms=reported))
    expected = {'start_ms': t, 'duration_ms': None, 'flags': ['collapsed']} if reported is None else {
        'start_ms': t - 3000, 'duration_ms': 3000, 'flags': ['reported_duration']}
    assert timing(colophon, r) == expected


def test_collapsed_embedded_clocks_remain_usable(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t).task_started(at=t, started_at_ms=t + 1000)
              .task_complete(at=t, completed_at_ms=t + 5000))
    assert timing(colophon, r) == {'start_ms': t + 1000, 'duration_ms': 4000, 'flags': []}


@pytest.mark.parametrize('start', [None, 9000])
def test_unknown_duration_missing_or_reversed_start(colophon, log, start):
    b, t = log
    b.meta(at=t)
    if start is not None:
        b.task_started(at=t + start)
    r = parse(colophon, b.task_complete(at=t + 4000))
    assert timing(colophon, r)['duration_ms'] is None
    assert timing(colophon, r)['flags'] == ['unknown_duration']


def test_interrupted_uses_latest_attributed_time_before_next_start(colophon, log):
    b, t = log
    b.meta(at=t).task_started('synthetic-first', at=t + 1000)
    b.world_state(at=t + 5000).world_state(at=t + 4000)
    b.world_state(at=t + 8000, turn_id='synthetic-other')
    b.task_started('synthetic-second', at=t + 10000)
    b.world_state(at=t + 11000, turn_id='synthetic-first')
    r = parse(colophon, b)
    assert r['turns'][0]['end_kind'] == 'interrupted'
    assert r['turns'][0]['end_ms'] == t + 5000
    assert timing(colophon, r)['duration_ms'] == 4000
    assert r['turns'][1]['end_kind'] == 'open'
    assert r['turns'][1]['end_ms'] is None
    assert all(set(x) == TURN_FIELDS for x in r['turns'])


def test_completion_of_other_turn_does_not_clear_current(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t).task_started('synthetic-first', at=t + 1000)
              .task_started('synthetic-second', at=t + 3000)
              .task_complete('synthetic-first', at=t + 4000).world_state(at=t + 5000))
    assert r['turns'][0]['end_kind'] == 'completed'
    assert r['turns'][1]['last_ms'] == t + 5000


def test_phase_one_compact_facts_no_payload_retention(colophon, log):
    b, t = log
    b.meta(at=t).task_started(at=t + 1000).world_state(at=t + 2000, synthetic_secret='discard me')
    phase = getattr(colophon, 'TurnBuilder', None)
    assert isinstance(phase, type), 'Task 4 TurnBuilder is missing'
    r = parse(colophon, b)
    assert 'discard me' not in json.dumps(r)
    assert 'facts' not in r
    assert set(r['turns'][0]) == TURN_FIELDS


def test_decoded_records_released_before_phase_two(colophon, log, monkeypatch):
    b, t = log
    b.meta(at=t).task_started(at=t + 1000).world_state(at=t + 2000)
    references = []
    decode = colophon.decode_line
    history = colophon._history

    class TrackedRecord(dict):
        pass

    def track(data):
        decoded = decode(data)
        if decoded.obj is None:
            return decoded
        record = TrackedRecord(decoded.obj)
        references.append(weakref.ref(record))
        return colophon.DecodedLine(record, decoded.status)

    def phase_two(meta, facts):
        assert references and all(ref() is None for ref in references)
        assert all(not isinstance(value, (dict, list)) for fact in facts for value in fact)
        return history(meta, facts)

    monkeypatch.setattr(colophon, 'decode_line', track)
    monkeypatch.setattr(colophon, '_history', phase_two)
    parse(colophon, b)


@pytest.mark.parametrize('value', [None, True, 'synthetic-invalid', float('inf'), float('nan')])
def test_path_a_invalid_synthetic_clocks_do_not_verify(colophon, log, value):
    b, t = log
    b.meta(at=t, forked_from_id='synthetic-parent')
    # No valid embedded clock: the UUIDv7 completion owns its own boundary.
    for kind, turn in [('task_started', 'rollout-synthetic'), ('task_complete', uuid7(t + 1000))]:
        payload = {'type': kind, 'turn_id': turn}
        if value is not None:
            payload['started_at'] = value
        b.raw((json.dumps({'timestamp': iso(t + 5000), 'type': 'event_msg',
                          'payload': payload}) + '\n').encode())
    r = parse(colophon, b)
    assert r['history']['method'] == 'own_lifecycle'
    assert r['history']['boundary_rec'] == 2
    assert r['history']['inherited_recs'] == [[1, 2]]


def test_path_a_synthetic_clocks_compare_numerically(colophon, log):
    b, t = log
    r = parse(colophon, b.meta(at=t, forked_from_id='synthetic-parent')
              .task_started('rollout-synthetic', at=t + 1000, started_at=(t + 1000) // 1000)
              .task_complete(uuid7(t + 1000), at=t + 3000, started_at=(t + 1000) / 1000))
    assert r['history']['method'] == 'synthetic_start_verified_by_completion'
    assert r['history']['boundary_rec'] == 1


@pytest.mark.parametrize('tail', [b'', b'synthetic malformed\n', b'synthetic partial',
                                 b'{"type":"world_state"}'])
def test_raw_lines_released_before_phase_two(colophon, log, monkeypatch, tail):
    b, t = log
    b.meta(at=t).task_started(at=t + 1000).raw(tail)
    references = []
    iterate = colophon.iter_log_lines
    history = colophon._history

    class TrackedRawLine:
        def __init__(self, raw):
            self.index, self.data, self.terminated = raw

    def track(fh, size):
        for raw in iterate(fh, size):
            line = TrackedRawLine(raw)
            references.append(weakref.ref(line))
            yield line

    def phase_two(meta, facts):
        assert references and all(ref() is None for ref in references)
        return history(meta, facts)

    monkeypatch.setattr(colophon, 'iter_log_lines', track)
    monkeypatch.setattr(colophon, '_history', phase_two)
    parse(colophon, b)
