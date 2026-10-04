"""Primary composition (A4#1), source cross-file keys and D8 attribution."""

import copy

import pytest

from fixturegen import CodexHome

BASE = 1_893_974_400_000
COMPONENTS = ('input', 'cached', 'cache_write', 'output', 'reasoning')


def parsed(colophon, log, *, mtime=BASE):
    file = log.write()
    return colophon.parse_log_file(file, size=file.stat().st_size, mtime_ns=mtime * 1_000_000,
                                   archived=False)


def compose(colophon, records, turns=None):
    corpus = colophon.build_corpus(records, colophon.CodexMetadata(), BASE + 3_600_000)
    colophon.link_subagents(corpus, colophon.CodexMetadata(), BASE + 3_600_000)
    before = copy.deepcopy(records)
    colophon.compose_usage(corpus, colophon.PriorityTurns(turns or {}, ['synthetic trace diagnostic']))
    assert records == before
    assert corpus.file_diagnostics['trace_db'] == ['synthetic trace diagnostic']
    return corpus


def counts(units):
    return tuple(sum(getattr(unit, field) or 0 for unit in units) for field in COMPONENTS)


def test_primary_dedup_foreign_threads_missing_response_and_compaction(colophon, tmp_path):
    # A4#1/D8: 10 (first response) +3+4 (no id) +5 (compaction) =22.
    source = CodexHome(tmp_path / 'synthetic-home')
    log = (source.log('synthetic-session').meta().turn_context(model='openai/gpt-5-2025-08-07')
        .task_started('synthetic-turn').usage_record(usage={'input_tokens': 10}, response_id='synthetic-shared')
        .usage_record(usage={'input_tokens': 900}, response_id='synthetic-shared')
        .usage_record(usage={'input_tokens': 700}, thread_id='synthetic-foreign')
        .usage_record(usage={'input_tokens': 3}, response_id=None)
        .usage_record(usage={'input_tokens': 4}, response_id=None)
        .usage_record(usage={'input_tokens': 5, 'cache_write_input_tokens': 6})
        ._emit('compacted', {'message': 'Synthetic compaction'}))
    units = compose(colophon, [parsed(colophon, log)]).sessions['synthetic-session'].units
    assert counts(units) == (22, 0, 6, 0, 0)
    assert len(units) == 4
    assert all(unit.source == 'record' and unit.model == 'gpt-5' for unit in units)
    assert all(unit.model_raw == 'openai/gpt-5-2025-08-07' for unit in units)
    assert all(unit.cost_usd is None and unit.period is None for unit in units)


def test_primary_token_totals_mapping_clamps_and_keeps_write(colophon, tmp_path):
    # tokenTotals Scanner.swift4977–4987: cached max, reasoning clamped to output.
    log = (CodexHome(tmp_path / 'synthetic-home').log('synthetic-session').meta()
        .task_started().usage_record(usage={'input_tokens': -3, 'cached_input_tokens': 8,
            'cache_read_input_tokens': 12, 'output_tokens': 4, 'reasoning_output_tokens': 9,
            'cache_write_input_tokens': -7}))
    unit = compose(colophon, [parsed(colophon, log)]).sessions['synthetic-session'].units[0]
    assert counts([unit]) == (0, 12, 0, 4, 4)
    assert unit.model == 'unknown'


def test_per_turn_selection_retains_fallback_after_primary(colophon, tmp_path):
    # Whole-file total progression 100→130; primary replaces only first turn.
    log = (CodexHome(tmp_path / 'synthetic-home').log('synthetic-session').meta()
        .task_started('synthetic-primary').usage_record(usage={'input_tokens': 12})
        .token_count(total={'input_tokens': 100}, last={'input_tokens': 100})
        .task_complete().task_started('synthetic-fallback')
        .token_count(total={'input_tokens': 130}, last={'input_tokens': 30}).task_complete())
    units = compose(colophon, [parsed(colophon, log)]).sessions['synthetic-session'].units
    assert [(unit.turn_id, unit.source, unit.input) for unit in units] == [
        ('synthetic-primary', 'record', 12), ('synthetic-fallback', 'token_count', 30)]


def test_whitespace_turn_identity_selects_primary_and_preserves_attribution(colophon, tmp_path):
    # Task4 _identifier preserves nonempty ids verbatim; Task15 A4#1 selects
    # primary per identical turn id, so record4 replaces fallback10 (not14).
    turn_id = ' '
    log = (CodexHome(tmp_path / 'synthetic-home').log('synthetic-session').meta()
        .task_started(turn_id).usage_record(usage={'input_tokens': 4})
        .token_count(last={'input_tokens': 10}, total={'input_tokens': 10}))
    record = parsed(colophon, log)
    assert record['usage_records'][0]['turn_id'] == turn_id
    metadata = {'thread_id': 'synthetic-session', 'model': 'gpt-5',
                'timestamp': '1', 'first_seen_ms': 1}
    session = compose(colophon, [record], {turn_id: metadata}).sessions['synthetic-session']
    assert [turn.id for turn in session.turns] == [turn_id]
    assert [(unit.source, unit.input, unit.turn_id, unit.display_turn) for unit in session.units] == [
        ('record', 4, turn_id, turn_id)]
    assert session.units[0].tier == 'priority'
    assert session.units[0].priority == metadata
    assert counts(session.units) == (4, 0, 0, 0, 0)


def test_bare_primary_turn_discarded_and_no_turn_counted(colophon, tmp_path):
    # Scanner.swift4279–4307 emits bare rows; A4#1 replaces only owned turn's900.
    log = (CodexHome(tmp_path / 'synthetic-home').log('synthetic-session').meta()
        .bare_usage(usage={'input_tokens': 7}).task_started('synthetic-primary')
        .usage_record(usage={'input_tokens': 12}).bare_usage(usage={'input_tokens': 900}))
    units = compose(colophon, [parsed(colophon, log)]).sessions['synthetic-session'].units
    assert [(unit.source, unit.input) for unit in units] == [('record', 12), ('bare', 7)]
    assert units[1].turn_id is None and units[1].display_turn is None


def test_model_context_is_file_local_strictly_before_and_clear(colophon, tmp_path):
    source = CodexHome(tmp_path / 'synthetic-home')
    old = parsed(colophon, source.log('synthetic-session', name='synthetic-old.jsonl').meta()
        .turn_context(model='gpt-5-mini').task_started('synthetic-turn')
        .usage_record(usage={'input_tokens': 2}, response_id='synthetic-old-response'), mtime=BASE)
    new = parsed(colophon, source.log('synthetic-session', name='synthetic-new.jsonl').meta()
        .usage_record(usage={'input_tokens': 3})
        .turn_context(model='gpt-5').usage_record(usage={'input_tokens': 4})
        .turn_context(model=' ').usage_record(usage={'input_tokens': 5}), mtime=BASE+1)
    units = compose(colophon, [old, new]).sessions['synthetic-session'].units
    assert [(unit.input, unit.model) for unit in units] == [(3, 'unknown'), (4, 'gpt-5'), (5, 'unknown'), (2, 'gpt-5-mini')]


def test_pending_unconsumed_tail_primary_uses_context_observations(colophon, tmp_path):
    source = CodexHome(tmp_path / 'synthetic-home')
    log = (source.log('synthetic-child').meta(parent_thread_id='synthetic-parent')
        .turn_context(model='gpt-5-mini').usage_record(usage={'input_tokens': 7})
        .turn_context(model=' ').usage_record(usage={'input_tokens': 8}))
    log._lines.append(b'{"synthetic-incomplete":')
    record = parsed(colophon, log)
    assert record['token_stream']['unconsumed_tail']
    assert colophon.account_logs([record])[record['key']['path']].model_timeline == []
    units = compose(colophon, [record]).sessions['synthetic-child'].units
    assert [(unit.input, unit.model) for unit in units] == [(7, 'gpt-5-mini'), (8, 'unknown')]


def test_tier_switching_and_trace_canonical_turn_match(colophon, tmp_path):
    log = (CodexHome(tmp_path / 'synthetic-home').log('synthetic-session').meta()
        .task_started('synthetic-cafe\u0301').usage_record(usage={'input_tokens': 7}).task_complete()
        .task_started('synthetic-standard').token_count(last={'input_tokens': 5}, total={'input_tokens': 5}))
    metadata = {'synthetic-caf\u00e9': {'thread_id': 'synthetic-session', 'model': 'gpt-5',
                                     'timestamp': '1', 'first_seen_ms': 1}}
    units = compose(colophon, [parsed(colophon, log)], metadata).sessions['synthetic-session'].units
    assert [unit.tier for unit in units] == ['priority', 'standard']
    assert units[0].priority == metadata['synthetic-caf\u00e9']
    assert units[1].priority is None


def test_duplicate_files_union_primary_and_cross_file_fallback(colophon, tmp_path):
    # CacheHelpers.swift514–554: retain new10+5; old10 has same cross-file key.
    source = CodexHome(tmp_path / 'synthetic-home')
    def log(name, extra):
        builder = (source.log('synthetic-session', name=name).meta(at=BASE)
            .task_started('synthetic-primary', at=BASE+1)
            .usage_record(at=BASE+2, response_id='synthetic-shared', usage={'input_tokens': 9})
            .task_started('synthetic-fallback', at=BASE+3)
            .token_count(at=BASE+4, total={'input_tokens': 10}, last={'input_tokens': 10}))
        if extra:
            builder.token_count(at=BASE+5, total={'input_tokens': 15}, last={'input_tokens': 5})
        return builder
    old = parsed(colophon, log('synthetic-old.jsonl', False))
    new = parsed(colophon, log('synthetic-new.jsonl', True), mtime=BASE+1)
    corpus = compose(colophon, [old, new])
    units = corpus.sessions['synthetic-session'].units
    assert [(unit.source, unit.input) for unit in units] == [('record', 9), ('token_count', 10), ('token_count', 5)]
    assert corpus.file_diagnostics['duplicate_session_ids'] == [{
        'id': 'synthetic-session', 'paths': sorted([old['key']['path'], new['key']['path']])}]


def test_cross_file_key_preserves_event_index_and_timestamp_but_not_reasoning(colophon, tmp_path):
    source = CodexHome(tmp_path / 'synthetic-home')
    records = []
    for index in range(3):
        log = source.log('synthetic-session', name=f'synthetic-copy-{index}.jsonl').meta(at=BASE)
        if index == 2:
            log.task_started('synthetic-extra', at=BASE+1)
        log.bare_usage(at=BASE+2+index, model='gpt-5', usage={'input_tokens': 10})
        records.append(parsed(colophon, log, mtime=BASE+index))
    units = compose(colophon, records).sessions['synthetic-session'].units
    assert len(units) == 3


def test_same_file_duplicate_bare_rows_never_deduped(colophon, tmp_path):
    # CacheHelpers.swift514–531 adds accepted keys only after a file: 7+7=14.
    source = CodexHome(tmp_path / 'synthetic-home')
    log = source.log('synthetic-session').meta().bare_usage(usage={'input_tokens': 7}, at=BASE+10)
    log._lines.append(log._lines[-1])
    units = compose(colophon, [parsed(colophon, log)]).sessions['synthetic-session'].units
    assert counts(units)[0] == 14


def test_local_file_indices_and_inherited_attribution(colophon, tmp_path):
    source = CodexHome(tmp_path / 'synthetic-home')
    unrelated = parsed(colophon, source.log('synthetic-unrelated').meta().task_started().usage_record())
    old = parsed(colophon, source.log('synthetic-session', name='synthetic-old.jsonl').meta()
        .task_started('synthetic-turn').usage_record(usage={'input_tokens': 7}, response_id='synthetic-old-response'))
    new = parsed(colophon, source.log('synthetic-session', name='synthetic-new.jsonl').meta()
        .task_started('synthetic-turn').usage_record(usage={'input_tokens': 8}), mtime=BASE+1)
    old['history']['inherited_lines'] = [[0, 20]]
    units = compose(colophon, [unrelated, old, new]).sessions['synthetic-session'].units
    assert [(unit.file, unit.input, unit.display_turn) for unit in units] == [
        (0, 8, 'synthetic-turn'), (1, 7, None)]


def test_inherited_fallback_deltas_go_outside_and_component_invariants(colophon, tmp_path):
    # Scanner.swift4442–4654 +D8: own inputs4+3, child7, grandchild5 =19;
    # display attribution changes placement only, cache writes2 remain unbilled.
    source = CodexHome(tmp_path / 'synthetic-home')
    root = parsed(colophon, source.log('synthetic-root').meta()
        .task_started('synthetic-a').usage_record(usage={'input_tokens': 4, 'output_tokens': 2})
        .task_complete().task_started('synthetic-b').token_count(total={'input_tokens': 3}, last={'input_tokens': 3}))
    child = parsed(colophon, source.log('synthetic-child').meta(parent_thread_id='synthetic-root', depth=1)
        .task_started('synthetic-child-turn').token_count(total={'input_tokens': 7}, last={'input_tokens': 7}))
    grandchild = parsed(colophon, source.log('synthetic-grandchild').meta(parent_thread_id='synthetic-child', depth=2)
        .task_started('synthetic-grandchild-turn').usage_record(usage={'input_tokens': 5, 'cache_write_input_tokens': 2}))
    child['history']['inherited_lines'] = [[0, 20]]
    corpus = compose(colophon, [root, child, grandchild])
    assert corpus.sessions['synthetic-child'].units[0].display_turn is None
    for session in corpus.sessions.values():
        displayed = [unit for unit in session.units if unit.display_turn is not None]
        outside = [unit for unit in session.units if unit.display_turn is None]
        assert tuple(a+b for a,b in zip(counts(displayed), counts(outside))) == counts(session.units)
    def descendants(identifier):
        session = corpus.sessions[identifier]
        return [session] + [descendant for child_id in session.children for descendant in descendants(child_id)]
    family = descendants('synthetic-root')
    assert len(family) == 3
    assert tuple(sum(counts(session.units)[index] for session in family) for index in range(5)) == counts(
        [unit for session in family for unit in session.units]) == (19, 0, 2, 2, 0)


def test_missing_parent_baseline_flag_and_skipped_parent_accounting(colophon, tmp_path):
    source = CodexHome(tmp_path / 'synthetic-home')
    fork = parsed(colophon, source.log('synthetic-fork').meta(forked_from_id='synthetic-missing')
        .task_started().token_count(total={'input_tokens': 15}, last={'input_tokens': 5}))
    corpus = compose(colophon, [fork])
    assert corpus.file_diagnostics['fork_baseline_unavailable'] == ['synthetic-fork']
    assert 'fork_baseline_unavailable' in corpus.sessions['synthetic-fork'].flags
    assert corpus.sessions['synthetic-fork'].units == []
    parent = parsed(colophon, source.log('synthetic-missing').meta(at=BASE-1))
    assert parent['status'] == 'header_only'
    corpus = compose(colophon, [fork, parent])
    assert corpus.skipped_records == [parent]
    assert corpus.file_diagnostics['fork_baseline_unavailable'] == []


def test_duplicate_parent_uses_newest_copy(colophon, tmp_path):
    # A4#6 newest baseline20; codexTotalDelta Scanner.swift515–529 gives25−20=5.
    source = CodexHome(tmp_path / 'synthetic-home')
    old = parsed(colophon, source.log('synthetic-parent', name='synthetic-old.jsonl').meta(at=BASE-100)
        .token_count(at=BASE-90, total={'input_tokens': 10}, last={'input_tokens': 10}))
    new = parsed(colophon, source.log('synthetic-parent', name='synthetic-new.jsonl').meta(at=BASE-100)
        .token_count(at=BASE-90, total={'input_tokens': 20}, last={'input_tokens': 20}), mtime=BASE+1)
    fork = parsed(colophon, source.log('synthetic-fork').meta(at=BASE, forked_from_id='synthetic-parent')
        .task_started().token_count(at=BASE+1, total={'input_tokens': 25}, last={'input_tokens': 5}))
    corpus = compose(colophon, [old, fork, new])
    assert counts(corpus.sessions['synthetic-fork'].units)[0] == 5
    assert corpus.file_diagnostics['duplicate_session_ids'][0]['id'] == 'synthetic-parent'


def test_nonzero_cache_write_does_not_change_cost(colophon, tmp_path):
    log = (CodexHome(tmp_path / 'synthetic-home').log('synthetic-session').meta().turn_context(model='gpt-5')
        .usage_record(usage={'input_tokens': 10, 'cache_write_input_tokens': 900}))
    unit = compose(colophon, [parsed(colophon, log)]).sessions['synthetic-session'].units[0]
    rates = colophon.resolve_rates('gpt-5', colophon.ModelsDevIndex({}))
    assert unit.cache_write == 900
    # Task13 cost API intentionally has no cache_write argument (billed zero).
    assert colophon.cost_usd(rates, input=unit.input, cached=unit.cached,
                             output=unit.output) == 10 * (1.25 / 1_000_000)


def test_fallback_local_file_indices_and_non_display_turn_matching(colophon, tmp_path):
    source = CodexHome(tmp_path / 'synthetic-home')
    unrelated = parsed(colophon, source.log('synthetic-other').meta().task_started().usage_record())
    old = parsed(colophon, source.log('synthetic-session', name='synthetic-old.jsonl').meta()
        .task_started('synthetic-owned').token_count(last={'input_tokens': 7}, total={'input_tokens': 7})
        .task_started('synthetic-outside').token_count(last={'input_tokens': 2}, total={'input_tokens': 9}))
    new = parsed(colophon, source.log('synthetic-session', name='synthetic-new.jsonl').meta()
        .task_started('synthetic-owned').user_item(), mtime=BASE+1)
    # D8 checks old file's inherited ranges, never new file's same line numbers.
    new['history']['inherited_lines'] = [[0, 20]]
    corpus = compose(colophon, [unrelated, new, old])
    units = corpus.sessions['synthetic-session'].units
    assert [(unit.file, unit.input, unit.display_turn) for unit in units] == [
        (1, 7, 'synthetic-owned'), (1, 2, None)]


def test_pending_tail_xc_context_and_no_owned_suffix_reset(colophon, tmp_path):
    source = CodexHome(tmp_path / 'synthetic-home')
    log = source.log('synthetic-child').meta(parent_thread_id='synthetic-parent')
    log._emit('turn_context', {'model': 'gpt-5-mini', 'synthetic-padding': 'x' * 270_000})
    log.usage_record(usage={'input_tokens': 9})
    log._lines.append(b'{"synthetic-incomplete":')
    record = parsed(colophon, log)
    assert any(observation[0] == 'XC' for observation in record['token_stream']['observations'])
    assert compose(colophon, [record]).sessions['synthetic-child'].units[0].model == 'gpt-5-mini'


def test_primary_model_context_at_same_position_does_not_apply(colophon, tmp_path):
    # Primary contract says last position < line, not <= line.
    log = (CodexHome(tmp_path / 'synthetic-home').log('synthetic-session').meta()
        .turn_context(model='gpt-5').usage_record(usage={'input_tokens': 1}))
    record = parsed(colophon, log)
    record['usage_records'][0]['line'] = record['token_stream']['observations'][-1][1]
    assert compose(colophon, [record]).sessions['synthetic-session'].units[0].model == 'unknown'


def test_cross_file_key_exact_join_and_canonical_equality(colophon):
    # CacheHelpers.swift497–555 concatenates U+001F fields (not a tuple).
    row = colophon.UsageRow(8, 12, 2, 'synthetic-cafe\u0301', 'synthetic-clock',
        0, 123, '2030-01-07', 'gpt-5', 'gpt-5', 10, 3, 2, 1, 'token_count')
    key = colophon._codex_cross_file_row_key('synthetic-session', 'synthetic-file', row)
    assert key == '\x1f'.join(['session:synthetic-session', 'synthetic-caf\u00e9',
        '2', '2030-01-07', 'gpt-5', '10', '3', '2', '123'])
    from dataclasses import replace
    assert colophon._codex_cross_file_row_key('synthetic-session', 'synthetic-file',
        replace(row, reasoning=900, file=0, line=99, model_raw='synthetic-raw')) == key
    assert colophon._codex_cross_file_row_key('synthetic-session', 'synthetic-file',
        replace(row, event_index=3)) != key
    assert colophon._codex_cross_file_row_key('synthetic-session', 'synthetic-file',
        replace(row, timestamp_unix_ms=124)) != key


def test_metadataless_files_remain_separate_accounting_units(colophon, tmp_path):
    # CacheHelpers.swift503 uses file:<path> when session identity is absent.
    source = CodexHome(tmp_path / 'synthetic-home')
    records = [parsed(colophon, source.log(name=f'synthetic-idless-{n}.jsonl')
        .bare_usage(at=BASE, usage={'input_tokens': 7})) for n in range(2)]
    corpus = compose(colophon, records)
    assert len(corpus.sessions) == 2
    assert [counts(session.units)[0] for session in corpus.sessions.values()] == [7, 7]
    assert corpus.file_diagnostics['duplicate_session_ids'] == []


def test_recomposition_does_not_accumulate_units_or_diagnostics(colophon, tmp_path):
    record = parsed(colophon, CodexHome(tmp_path / 'synthetic-home').log('synthetic-session')
        .meta().usage_record(usage={'input_tokens': 7}))
    corpus = compose(colophon, [record])
    first = copy.deepcopy(corpus.sessions['synthetic-session'].units)
    colophon.compose_usage(corpus, colophon.PriorityTurns())
    assert corpus.sessions['synthetic-session'].units == first
    assert corpus.file_diagnostics['trace_db'] == []


def test_duplicate_prepass_diagnostic_includes_differing_display_ids(colophon, tmp_path):
    # Spec5.1: prepass ignores >256KiB meta, true-first display identity does not.
    source = CodexHome(tmp_path / 'synthetic-home')
    records = []
    for index in range(2):
        log = source.log(f'synthetic-display-{index}').meta(synthetic_padding='x' * 270_000)
        log.meta(id='synthetic-prepass').bare_usage(usage={'input_tokens': 1})
        records.append(parsed(colophon, log))
    assert [record['token_stream']['observations'][0][1]['session_id'] for record in records] == [
        'synthetic-prepass', 'synthetic-prepass']
    diagnostic = compose(colophon, records).file_diagnostics['duplicate_session_ids']
    assert diagnostic == [
        {'id': 'synthetic-display-0', 'paths': [records[0]['key']['path']]},
        {'id': 'synthetic-display-1', 'paths': [records[1]['key']['path']]},
        {'id': 'synthetic-prepass', 'paths': sorted([record['key']['path'] for record in records])}]


def test_real_fork_counted_inherited_delta_is_outside_displayed_turn(colophon, tmp_path):
    # Scanner.swift4442–4654 subtracts parent10: inherited15 yields5, own20 yields5.
    # D8 sends the first counted row outside even though its id matches owned turn.
    source = CodexHome(tmp_path / 'synthetic-home')
    parent = parsed(colophon, source.log('synthetic-parent').meta(at=BASE-100)
        .token_count(at=BASE-90, total={'input_tokens': 10}, last={'input_tokens': 10}))
    fork = parsed(colophon, source.log('synthetic-fork').meta(at=BASE, forked_from_id='synthetic-parent')
        .meta(at=BASE+1, id='synthetic-parent')
        .token_count(at=BASE+2, turn_id='synthetic-owned', total={'input_tokens': 15}, last={'input_tokens': 5})
        .task_started('synthetic-owned', at=BASE+1001)
        .token_count(at=BASE+1002, total={'input_tokens': 20}, last={'input_tokens': 5}))
    assert fork['history']['inherited_lines']
    units = compose(colophon, [parent, fork]).sessions['synthetic-fork'].units
    assert [(unit.input, unit.turn_id, unit.display_turn) for unit in units] == [
        (5, 'synthetic-owned', None), (5, 'synthetic-owned', 'synthetic-owned')]
