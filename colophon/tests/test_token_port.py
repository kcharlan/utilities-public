"""Stage-by-stage parity with immutable CodexBar 3bbf6bc48 outputs."""
import json
import os
import time

import pytest

from token_cases import SCRUBBED, TOKEN_CASES, account_case, assert_case, load_case

NAMES = json.loads((TOKEN_CASES / 'index.json').read_text())
REAL_NAMES = json.loads((SCRUBBED / 'index.json').read_text())


@pytest.fixture
def case_timezone():
    original = os.environ.get('TZ')

    def set_zone(zone):
        os.environ['TZ'] = zone
        time.tzset()

    yield set_zone
    if original is None:
        os.environ.pop('TZ', None)
    else:
        os.environ['TZ'] = original
    time.tzset()


def check(colophon, root, name, tmp_path, case_timezone):
    case = load_case(root, name, tmp_path)
    case_timezone(case.expected['bucket_tz'])
    # Assert rather than raising AttributeError: each RED is missing behavior.
    assert callable(getattr(colophon, 'account_logs', None)), 'account_logs is not implemented'
    assert_case(case, account_case(colophon, case.home))


@pytest.mark.parametrize('name', [n for n in NAMES if n.startswith('a')])
def test_stage_a(colophon, name, tmp_path, case_timezone):
    check(colophon, TOKEN_CASES, name, tmp_path, case_timezone)


@pytest.mark.parametrize('name', [n for n in NAMES if n.startswith('b')])
def test_stage_b(colophon, name, tmp_path, case_timezone):
    check(colophon, TOKEN_CASES, name, tmp_path, case_timezone)


@pytest.mark.parametrize('name', [n for n in NAMES if n.startswith('c')])
def test_stage_c(colophon, name, tmp_path, case_timezone):
    check(colophon, TOKEN_CASES, name, tmp_path, case_timezone)


@pytest.mark.parametrize('name', REAL_NAMES)
def test_stage_d(colophon, name, tmp_path, case_timezone):
    check(colophon, SCRUBBED, name, tmp_path, case_timezone)


def test_model_timeline_owned_suffix_reset(colophon):
    assert callable(getattr(colophon, 'parse_codex_usage', None)), 'parse_codex_usage is not implemented'
    meta = {'session_id': 'synthetic-leaf', 'forked_from_id': None, 'fork_ts': None,
            'project_path': None, 'is_subagent': True, 'history_start_ordinal': 5,
            'history_base_thread_id': None}
    ts = '2030-01-07T12:00:00Z'
    stream = {'observations': [['P', meta], ['M', 0, 0, 0, meta],
        ['C', 1, 1, 1, ts, {'set': 'gpt-5.4'}],
        ['T', 4, 2, 2, ts, None, None, [10, 0, 1, None], [10, 0, 1, None]],
        ['T', 8, 3, 5, ts, None, None, [2, 0, 1, None], [12, 0, 2, None]],
        ['C', 9, 4, 6, ts, {'set': 'gpt-5.5'}]], 'unconsumed_tail': False}
    result = colophon.parse_codex_usage(stream, resolver=None)
    # Source EOF ownedSuffix reset precedes replay. Task15 uses position < line.
    assert result.model_timeline == [(7.5, None), (9, 'gpt-5.5')]
    assert [value for position, value in result.model_timeline if position < 8][-1] is None


def test_resolver_stream_key_must_equal_parsed_identity(colophon):
    assert callable(getattr(colophon, 'InheritedTotalsResolver', None)), 'InheritedTotalsResolver is not implemented'
    stream = {'observations': [['P', {'session_id': 'synthetic-other'}]], 'unconsumed_tail': False}
    with pytest.raises(AssertionError):
        colophon.InheritedTotalsResolver({'synthetic-requested': stream}).inherited_totals(
            'synthetic-requested', '2030-01-07T12:00:00Z')


def test_missing_cutoff_retains_prior_parent_dependency_resolution(colophon):
    ts = '2030-01-07T12:00:00Z'
    stream = {'observations': [['P', {'session_id': 'synthetic-parent'}],
        ['T', 1, 1, 1, ts, None, None, [10, 0, 1, None], [10, 0, 1, None]]],
        'unconsumed_tail': False}
    resolver = colophon.InheritedTotalsResolver({'synthetic-parent': stream})
    assert resolver.inherited_totals('synthetic-parent', ts) == (
        'resolved', colophon.Totals(10, 0, 1, None))
    # inheritedTotals 1698–1703 returns before resolvedDependencyKeys is updated.
    assert resolver.inherited_totals('synthetic-parent', '') == ('unresolved', None)
    assert resolver.dependency_keys['synthetic-parent'] == 'resolved'
    assert not resolver.resolving_session_ids


@pytest.mark.parametrize('text,seconds,day', [
    ('2030-01-07t00:00:00Z', None, '2030-01-07'),
    ('1500-01-07T00:00:00Z', -14830473600.0, '1500-01-07'),
    ('0000-01-07T00:00:00Z', -62166873600.0, '0001-01-07'),
    ('1582-10-05T00:00:00Z', -12219292800.0, '1582-10-15'),
    ('2030-01-07T00:00:00.' + '9' * 35 + 'Z', 1893974400.0, '2030-01-07'),
    ('2030-1-7T0:0:0+5:30', 1893956400.0, '2030-01-06'),
    ('2030-1-7T0:0:0UTC+5:30', 1893954600.0, '2030-01-06'),
    ('2030-01-07T00:00:00+23:00', 1893891600.0, '2030-01-07'),
], ids=['lowercase-T', 'julian-calendar', 'era-year-zero', 'calendar-cutover',
        'fraction-divisor-zero', 'basic-short-zone', 'named-zone-offset', 'nil-fixed-zone'])
def test_accounting_timestamp_source_chain(colophon, case_timezone, text, seconds, day):
    case_timezone('UTC')
    # Timestamp.swift parseNativeRFC3339 35–84: uppercase T, year >=1900,
    # at most 9 fraction digits; otherwise historical ICU numeric/calendar slice.
    # Julian-day arithmetic gives the older epochs; .year omits BCE era.
    # The 35-digit fraction wraps the Int32 divisor to 0. Bare numeric +5 consumes
    # five hours; named UTC+5:30 consumes 5h30m. TimeZone rejects a 23h fixed zone
    # in dayKeyFromTimestamp, using local UTC, while parseISO retains the 23h offset.
    # Standalone Foundation-only probes corroborate; no runtime Swift dependency.
    assert colophon.date_from_timestamp(text) == seconds
    result = colophon.day_key_from_timestamp(text) or colophon.day_key_from_parsed_iso(text)
    assert result[0] == day


def test_bare_timestamp_fallback_only_uses_accepted_bare_rows(colophon, case_timezone):
    case_timezone('UTC')
    ts = '2030-01-07T12:00:00Z'
    stream = {'observations': [['C', 0, 0, 0, ts, {'set': 'gpt-5.4'}],
        ['T', 1, 1, 1, ts, None, None, [10, 0, 1, None], [10, 0, 1, None]],
        ['B', 2, 2, None, None, [2, 0, 1, None]],
        ['B', 3, 3, ts, None, [3, 0, 1, None]],
        ['B', 4, 4, None, None, [4, 0, 1, None]]], 'unconsumed_tail': False}
    # handleBareUsage 4279–4307 alone assigns lastAcceptedTokenTimestamp.
    result = colophon.parse_codex_usage(stream, resolver=None)
    assert [(row.line, row.event_index, row.input, row.ts) for row in result.rows] == [
        (1, 0, 10, ts), (3, 1, 3, ts), (4, 2, 4, ts)]


@pytest.mark.parametrize('newer,tied', [(True, False), (False, False), (False, True)])
def test_parent_copy_uses_native_mtime_then_path_without_size(colophon, newer, tied):
    ts = '2030-01-07T12:00:00Z'
    parent_meta = {'session_id': 'synthetic-parent'}
    child_meta = {'session_id': 'synthetic-child', 'forked_from_id': 'synthetic-parent', 'fork_ts': ts}

    def record(path, meta, tokens, mtime_ns, size):
        return {'key': {'path': path, 'mtime_ns': mtime_ns, 'size': size},
                'token_stream': {'observations': [['P', meta],
                    ['T', 1, 1, 1, ts, 'gpt-5.4', None, [tokens, 0, 1, None], [tokens, 0, 1, None]]],
                    'unconsumed_tail': False}}

    first = record('/synthetic/a.jsonl', parent_meta, 10, 1000001, 1000)
    second = record('/synthetic/b.jsonl', parent_meta, 20, 1000002 if newer else 1000001 if tied else 1000000, 1)
    child = record('/synthetic/child.jsonl', child_meta, 25, 2000000, 1)
    # A4#6 selects native ns; equal mtimes choose a.jsonl despite b's smaller size.
    for records in ([child, second, first], [first, second, child]):
        result = colophon.account_logs(records)['/synthetic/child.jsonl']
        assert [row.input for row in result.rows] == [5 if newer else 15]
        assert result.rows[0].file == records.index(child)


def test_truncated_context_has_no_ordinal_in_explicit_subagent_suffix(colophon):
    ts = '2030-01-07T12:00:00Z'
    meta = {'session_id': 'synthetic-leaf', 'is_subagent': True, 'history_start_ordinal': 5}
    stream = {'observations': [['P', meta], ['M', 0, 0, 0, meta],
        ['XC', 3, 1, {'set': 'gpt-5.4'}],
        ['T', 4, 2, 2, ts, None, None, [10, 0, 1, None], [10, 0, 1, None]],
        ['T', 8, 3, 5, ts, None, None, [2, 0, 1, None], [12, 0, 2, None]]],
        'unconsumed_tail': False}
    # Truncated onLine routes .turnContext with ordinal:nil (Scanner.swift4783–4795).
    # The explicit suffix's inferred baseline is total-last=10; only 2 input is owned.
    result = colophon.parse_codex_usage(stream, resolver=None)
    assert [(row.input, row.model, row.line) for row in result.rows] == [(2, 'unknown', 8)]
    assert result.model_timeline == [(7.5, None)]


def _withholding_stream(identity, tokens, output, parent=None, fork_ts=None):
    ts = '2030-01-07T12:00:00Z'
    meta = {'session_id': identity, 'forked_from_id': parent, 'fork_ts': fork_ts}
    return {'observations': [['P', meta], ['M', 0, 0, 0, meta],
        ['T', 1, 1, 1, ts, 'gpt-5.4', None, [tokens, 0, output, None], [tokens, 0, output, None]]],
        'unconsumed_tail': False}


def test_normalized_session_id_retains_trimmed_source_spelling(colophon):
    # RolloutShape.swift 222–227 trims only; Swift canonical equality belongs
    # to comparisons, rather than rewriting the returned source string.
    assert colophon.normalized_session_id(' synthetic-cafe\u0301\n') == 'synthetic-cafe\u0301'
    assert colophon.normalized_session_id(None) is None
    assert colophon.normalized_session_id(' \n') is None


@pytest.mark.parametrize('first,second', [
    ('synthetic-cafe\u0301', 'synthetic-caf\u00e9'),
    ('synthetic-caf\u00e9', 'synthetic-cafe\u0301'),
])
def test_classifier_canonical_ancestors_retain_first_spelling(colophon, first, second):
    # RolloutShape.swift 44–57: Set compares canonical identity, while its
    # sole representative retains the first inserted, trimmed ancestor string.
    shape = colophon.classify_subagent_session_ids(
        'synthetic-leaf', ['synthetic-leaf', ' ' + first + '\n', second])
    assert shape.counter_semantics == 'copied_prefix'
    assert shape.inferred_parent_session_id == first


def test_classifier_canonical_leaf_is_not_an_ancestor(colophon):
    shape = colophon.classify_subagent_session_ids(
        'synthetic-caf\u00e9', [' synthetic-cafe\u0301 ', 'synthetic-caf\u00e9'])
    assert shape.counter_semantics == 'independent'
    assert shape.inferred_parent_session_id is None
    assert colophon.same_concrete_session_id('synthetic-caf\u00e9', ' synthetic-cafe\u0301 ')


def test_classifier_and_usage_result_retain_inferred_parent_spelling(colophon):
    leaf = {'session_id': 'synthetic-leaf', 'is_subagent': True}
    ancestor = 'synthetic-cafe\u0301'
    observations = [['M', 0, 0, 0, leaf],
                    ['M', 1, 1, 1, {'session_id': ' ' + ancestor + '\n'}]]
    # Both classify overloads and parseCodexFileCancellable expose the source
    # normalizedSessionID, so inferred fork metadata retains this spelling.
    shape = colophon.classify_subagent_rollout('synthetic-leaf', observations, False)
    result = colophon.parse_codex_usage(
        {'observations': [['P', leaf]] + observations, 'unconsumed_tail': False}, resolver=None)
    assert shape.counter_semantics == 'copied_prefix'
    assert shape.inferred_parent_session_id == ancestor
    assert result.forked_from_id == ancestor


def test_classifier_canonical_leaf_metadata_preserves_suffix_candidate(colophon):
    ts = '2030-01-07T12:00:00Z'
    observations = [['M', 0, 0, 0, {'session_id': 'synthetic-caf\u00e9'}],
                    ['T', 1, 1, 1, ts, None, None, [0, 0, 0, None], [10, 0, 1, None]],
                    ['M', 2, 2, 2, {'session_id': ' synthetic-cafe\u0301 '}]]
    # RolloutShape.swift 109–113 must not treat canonically equal leaf metadata
    # as an embedded ancestor and erase the inherited-opening boundary.
    shape = colophon.classify_subagent_rollout('synthetic-caf\u00e9', observations, True)
    assert shape.counter_semantics == 'independent'
    candidate = shape.owned_suffix_candidate
    assert candidate is not None
    assert candidate.owned_suffix.start_line_index == 1
    assert candidate.parent_totals_at_boundary == colophon.Totals(10, 0, 1, None)
    assert candidate.is_locally_confirmed


def test_retained_parent_key_offers_snapshots(colophon):
    ts = '2030-01-07T12:00:00Z'
    parent = _withholding_stream('synthetic-parent', 10, 1)
    fork = _withholding_stream('synthetic-fork', 20, 1, 'synthetic-parent', '')
    resolver = colophon.InheritedTotalsResolver({'synthetic-parent': parent, 'synthetic-fork': fork})
    resolver.inherited_totals('synthetic-parent', ts)
    parsed, _, offered = resolver.snapshot_resolution('synthetic-fork')
    # Empty fork_ts parses unresolved, yet the primed parent key stays 'resolved'
    # (CacheHelpers.swift 1297–1308 returns dependencyKeyUsed; the empty-cutoff guard at
    # Scanner.swift 1692–1697 does not clear it). isUnresolvedMissingParentFork
    # (ForkCoverage.swift 43–46) reads only that key, so the source offers snapshots.
    assert resolver.dependency_keys['synthetic-parent'] == 'resolved'
    assert parsed.has_unresolved_fork_baseline
    assert offered


def test_retained_parent_key_resolves_grandchild_usage(colophon):
    ts = '2030-01-07T12:00:00Z'
    parent = _withholding_stream('synthetic-parent', 10, 1)
    primer = _withholding_stream('synthetic-primer', 15, 2, 'synthetic-parent', ts)
    fork = _withholding_stream('synthetic-fork', 20, 1, 'synthetic-parent', '')
    child = _withholding_stream('synthetic-child', 25, 2, 'synthetic-fork', ts)
    records = [{'key': {'path': f'/synthetic/{name}.jsonl', 'mtime_ns': 1}, 'token_stream': stream}
               for name, stream in [('primer', primer), ('fork', fork), ('child', child), ('parent', parent)]]
    result = colophon.account_logs(records)['/synthetic/child.jsonl']
    # The fork's retry buffer makes it incomplete, but its final snapshot (20/0/1) covers
    # the cutoff (Scanner.swift 1716–1723), so the child owns 25-20 input and 2-1 output.
    assert [(row.input, row.cached, row.output) for row in result.rows] == [(5, 0, 1)]


@pytest.mark.parametrize('parent_id,fork_id', [
    ('synthetic-caf\u00e9', 'synthetic-cafe\u0301'),
    ('synthetic-cafe\u0301', 'synthetic-caf\u00e9'),
])
def test_canonical_equivalent_parent_lookup(colophon, parent_id, fork_id):
    ts = '2030-01-07T12:00:00Z'
    parent = _withholding_stream(parent_id, 20, 1)
    child = _withholding_stream('synthetic-child', 25, 1, fork_id, ts)
    records = [{'key': {'path': f'/synthetic/{name}.jsonl', 'mtime_ns': 1}, 'token_stream': stream}
               for name, stream in [('child', child), ('parent', parent)]]
    results = colophon.account_logs(records)
    # Scanner.swift 1172–1235 indexes Swift String keys; 1692–1734 resolves the
    # equivalent spelling. The child owns 25-20 input, with output already inherited.
    result = results['/synthetic/child.jsonl']
    assert [(row.input, row.cached, row.output) for row in result.rows] == [(5, 0, 0)]
    assert results['/synthetic/parent.jsonl'].session_id == parent_id
    assert result.forked_from_id == fork_id
    assert result.fork_accounting_state['metadata']['forked_from_id'] == fork_id


@pytest.mark.parametrize('tied', [False, True])
def test_canonical_duplicate_parent_newest_mtime(colophon, tied):
    ts = '2030-01-07T12:00:00Z'
    composed, decomposed = 'synthetic-caf\u00e9', 'synthetic-cafe\u0301'
    selected = {'key': {'path': '/synthetic/a.jsonl', 'mtime_ns': 1000002},
                'token_stream': _withholding_stream(decomposed, 20, 1)}
    other = {'key': {'path': '/synthetic/b.jsonl', 'mtime_ns': 1000002 if tied else 1000001},
             'token_stream': _withholding_stream(composed, 10, 1)}
    child = {'key': {'path': '/synthetic/child.jsonl', 'mtime_ns': 2000000},
             'token_stream': _withholding_stream('synthetic-child', 25, 1, composed, ts)}
    # A4#6 applies once per Swift String identity: newest ns, then ascending path.
    # The selected copy contributes baseline 20, so the child owns 25-20=5 input.
    for records in ([child, other, selected], [selected, other, child]):
        result = colophon.account_logs(records)['/synthetic/child.jsonl']
        assert [(row.input, row.cached, row.output) for row in result.rows] == [(5, 0, 0)]


@pytest.mark.parametrize('padding', ['', ' '])
def test_canonical_resolver_keys_share_memo_and_preserve_spelling(colophon, padding):
    ts = '2030-01-07T12:00:00Z'
    composed = padding + 'synthetic-caf\u00e9' + padding
    decomposed = padding + 'synthetic-cafe\u0301' + padding
    stream = _withholding_stream(composed, 10, 1)
    resolver = colophon.InheritedTotalsResolver({decomposed: stream})
    # Scanner.swift 1909–1932 compares Swift String identity, without trimming.
    assert resolver.inherited_totals(decomposed, ts) == ('resolved', colophon.Totals(10, 0, 1, None))
    assert resolver.inherited_totals(composed, ts) == ('resolved', colophon.Totals(10, 0, 1, None))
    assert resolver.snapshot_resolution(composed) is resolver.snapshot_resolution(decomposed)
    assert len(resolver.memo) == len(resolver.dependency_keys) == 1
    assert resolver.snapshot_resolution(decomposed)[0].session_id == composed
    assert resolver.inherited_totals(decomposed, '') == ('unresolved', None)
    assert resolver.diagnostics == [('missing-cutoff', decomposed)]
    assert not resolver.resolving_session_ids
    if padding:
        assert resolver.inherited_totals('synthetic-caf\u00e9', ts) == ('unresolved', None)
        assert resolver.diagnostics[-1] == ('missing', 'synthetic-caf\u00e9')


def test_canonical_resolver_recursion_guard_stops_equivalent_identity(colophon):
    ts = '2030-01-07T12:00:00Z'
    composed, decomposed = 'synthetic-caf\u00e9', 'synthetic-cafe\u0301'
    resolver = colophon.InheritedTotalsResolver({composed: _withholding_stream(composed, 10, 1)})
    resolver.resolving_session_ids.add(composed)
    # inheritedTotals 1692–1697 uses Set<String>: an alternate spelling of an
    # active parent cannot enter snapshot resolution or acquire a missing key.
    assert resolver.inherited_totals(decomposed, ts) == ('unresolved', None)
    assert resolver.diagnostics == []
    assert resolver.memo == resolver.dependency_keys == {}
    assert resolver.resolving_session_ids == {composed}


def test_canonical_parent_dependency_retains_offered_snapshots(colophon):
    ts = '2030-01-07T12:00:00Z'
    composed, decomposed = 'synthetic-caf\u00e9', 'synthetic-cafe\u0301'
    parent = _withholding_stream(composed, 10, 1)
    fork = _withholding_stream('synthetic-fork', 20, 1, decomposed, '')
    resolver = colophon.InheritedTotalsResolver({composed: parent, 'synthetic-fork': fork})
    assert resolver.inherited_totals(composed, ts)[0] == 'resolved'
    parsed, _, offered = resolver.snapshot_resolution('synthetic-fork')
    # dependencyKeyUsed 1814–1816 uses the same Swift dictionary identity as
    # the primed parent. Empty cutoff retains that key, so snapshots are offered.
    assert parsed.has_unresolved_fork_baseline
    assert offered
    assert parsed.forked_from_id == decomposed


def test_canonical_parent_dependency_resolves_grandchild_usage(colophon):
    ts = '2030-01-07T12:00:00Z'
    composed, decomposed = 'synthetic-caf\u00e9', 'synthetic-cafe\u0301'
    parent = _withholding_stream(composed, 10, 1)
    primer = _withholding_stream('synthetic-primer', 15, 2, composed, ts)
    fork = _withholding_stream('synthetic-fork', 20, 1, decomposed, '')
    child = _withholding_stream('synthetic-child', 25, 2, 'synthetic-fork', ts)
    records = [{'key': {'path': f'/synthetic/{name}.jsonl', 'mtime_ns': 1}, 'token_stream': stream}
               for name, stream in [('primer', primer), ('fork', fork), ('child', child), ('parent', parent)]]
    result = colophon.account_logs(records)['/synthetic/child.jsonl']
    # cachedSnapshotResolution 1995 offers the fork's covered snapshot; canonical
    # parent identity must not withhold it. The grandchild owns 25-20 and 2-1.
    assert [(row.input, row.cached, row.output) for row in result.rows] == [(5, 0, 1)]
