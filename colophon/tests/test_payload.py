"""Compiler contract checks with exclusively invented logs and prices."""
import json
import re
from types import SimpleNamespace

import pytest

from catalogs import catalog, model
from fixturegen import CodexHome

NOW = 1_894_622_400_000
RATES = dict(input=2, cached_input=.5, cache_write=3, output=7)
USAGE = {'input', 'cached_input', 'cache_write', 'output', 'reasoning', 'cost_usd', 'unpriced_tokens', 'priced_by'}
ROW = {'id', 'kind', 'title', 'title_full', 'title_source', 'archived', 'log_path', 'workspace', 'subfolder', 'cwd', 'branch', 'originator', 'forked_from', 'start_ms', 'end_ms', 'idle_ms', 'user_span_ms', 'flags', 'turns', 'session_voice', 'own_usage', 'outside_usage', 'buckets', 'tools', 'children'}
TURN = {'id', 'n', 'status', 'start_ms', 'end_ms', 'duration_ms', 'ttft_ms', 'flags', 'requests', 'final_answer', 'voice_replies', 'tools', 'usage', 'spawned', 'used'}
REQUEST = {'at_ms', 'text', 'kind', 'before_turn', 'images', 'time_unreliable', 'voice_reply'}
DIAGNOSTICS = {'skipped_files', 'malformed_lines', 'truncated_lines', 'recovered_lines', 'unknown_record_types', 'db_threads_without_logs', 'metadata_errors', 'orphaned_subagents', 'inferred_links', 'unresolved_history_boundaries', 'fork_baseline_unavailable', 'duplicate_session_ids', 'unpriced_models', 'history_begins', 'priority_without_multiplier', 'unrecorded_catalog_rates', 'untimed_usage', 'ledger', 'workspaces_file', 'catalog', 'trace_db', 'page_size_bytes', 'page_size_over_limit'}


def entry(key, *, at=None, priority=None, rate=2):
    result = dict(model=key, effective_from=at, source='curated' if at is None else 'manual', per_million=dict(RATES, input=rate))
    if priority is not None:
        result['priority'] = priority
    return result


def unit(c, *, raw='gpt-5.4', trace=None, at=NOW, clock=True, input=100, display='synthetic-turn-1'):
    return c.UsageUnit('synthetic-root', 0, 1, display, display, at, at if clock else None,
        raw, c.normalize_codex_model(raw), {'model': trace} if trace else None,
        'priority' if trace else 'standard', input, 20, 9, 10, 3, 'record')


def price(c, units, entries, index=None, available=True):
    corpus = SimpleNamespace(sessions={'synthetic-root': SimpleNamespace(units=units)})
    return c.price_units(corpus, c.PriceHistory(entries, []), index, costs_available=available)


@pytest.mark.parametrize('trace', ['gpt-5.5', 'gpt-5.5-2026-04-23', 'openai/gpt-5.5'])
def test_priority_trace_model_multiplier_and_normalized_history(colophon, trace):
    u = unit(colophon, trace=trace)
    report = price(colophon, [u], [entry('gpt-5.4', rate=99), entry('gpt-5.5', priority={'multiplier': 2.5, 'max_input_tokens': None})])
    assert u.cost_usd == pytest.approx(colophon.cost_usd(entry('gpt-5.5'), input=100, cached=20, output=10) * 2.5)
    assert u.period == ('gpt-5.5', 0)
    assert report.unpriced == {}


@pytest.mark.parametrize('prefix', ['', 'openai/'])
def test_priority_distinct_catalog_alias_rates_and_multiplier_roles(colophon, prefix):
    raw = prefix + 'gpt-5.5-2026-04-23'
    index = colophon.ModelsDevIndex.from_catalog(catalog({'gpt-5.5': model('gpt-5.5', input=2, output=7), 'gpt-5.5-2026-04-23': model('gpt-5.5-2026-04-23', input=11, output=13)}))
    u = unit(colophon, trace=raw)
    report = price(colophon, [u], [entry('gpt-5.5', priority={'multiplier': 2.5, 'max_input_tokens': None})], index)
    key = 'catalog:gpt-5.5-2026-04-23|gpt-5.5'
    assert u.period == (key, 0)
    assert u.cost_usd == pytest.approx(colophon.cost_usd(colophon.resolve_rates(raw, index), input=100, cached=20, output=10) * 2.5)
    assert report.unrecorded == {key}
    assert report.periods[key][0]['source'] == 'transient'


def test_priority_folded_catalog_uses_normalized_history(colophon):
    index = colophon.ModelsDevIndex.from_catalog(catalog({'gpt-5.5': model('gpt-5.5', input=90, output=99)}))
    u = unit(colophon, trace='gpt-5.5-2026-04-23')
    price(colophon, [u], [entry('gpt-5.5', priority={'multiplier': 2.5, 'max_input_tokens': None})], index)
    assert u.period == ('gpt-5.5', 0)


def test_priority_new_alias_does_not_reprice_old_usage(colophon):
    raw = 'gpt-5.5-2026-04-23'
    key = 'catalog:' + raw + '|gpt-5.5'
    index = colophon.ModelsDevIndex.from_catalog(catalog({raw: model(raw, input=11, output=13), 'gpt-5.5': model('gpt-5.5', input=2, output=7)}))
    old, new = unit(colophon, trace=raw, at=NOW-1000), unit(colophon, trace=raw, at=NOW+1000)
    report = price(colophon, [old, new], [entry('gpt-5.5'), entry(key, at=colophon.format_rfc3339(NOW), rate=11)], index)
    assert old.period == ('gpt-5.5', 0)
    assert new.period == (key, 0)
    assert key not in report.history_begins


@pytest.mark.parametrize('trace', [None, 'gpt-5.6-sol'])
@pytest.mark.parametrize('clock', [True, False])
def test_historical_precedence_and_missing_pricing_clock(colophon, trace, clock):
    cutoff = colophon.HISTORICAL_CUTOFFS['gpt-5.6-sol']
    u = unit(colophon, raw='gpt-5.6-sol', trace=trace, at=cutoff-1000, clock=clock)
    price(colophon, [u], [entry('gpt-5.6-sol', rate=2), entry('gpt-5.6-sol', at=colophon.format_rfc3339(cutoff), rate=9)])
    assert u.period == ('gpt-5.6-sol', 0 if clock else 1)


@pytest.mark.parametrize('multiplier,cap,input,expected', [(.5,None,100,1),(2,100,101,1),(2,100,100,2),(None,None,100,1)])
def test_max_cap_and_missing_multiplier(colophon, multiplier, cap, input, expected):
    u = unit(colophon, trace='gpt-5.4', input=input)
    priority = None if multiplier is None else dict(multiplier=multiplier, max_input_tokens=cap)
    report = price(colophon, [u], [entry('gpt-5.4', priority=priority)])
    assert u.cost_usd == pytest.approx(colophon.cost_usd(entry('gpt-5.4'), input=input, cached=20, output=10) * expected)
    assert report.priority_without_multiplier == ({'gpt-5.4': input} if multiplier is None else {})


def test_invalid_ledger_null_costs_tokens_retained(colophon):
    u = unit(colophon)
    report = price(colophon, [u], [entry('gpt-5.4')], available=False)
    assert u.cost_usd is None
    assert u.input == 100
    assert report.unpriced == {}


@pytest.mark.parametrize('raw,trace,input,multiplier', [('gpt-5.6-sol',None,100,1),('gpt-5.4','gpt-5.5',100,2.5),('gpt-5.4','gpt-5.5',272001,1),('gpt-5.4','gpt-6-astra',272001,2)])
def test_unknown_time_current_transient_source_rates_not_dated_ledger(colophon, raw, trace, input, multiplier):
    u = unit(colophon,raw=raw,trace=trace,at=None,input=input)
    report = price(colophon,[u],[entry(colophon.normalize_codex_model(trace or raw),at='2031-01-01T00:00:00Z',rate=999)])
    current = colophon.resolve_rates(trace or raw,None)
    assert u.cost_usd == pytest.approx(colophon.cost_usd(current,input=input,cached=20,output=10)*multiplier)
    assert u.period[1] == 1
    assert report.periods[u.period[0]][u.period[1]]['source'] == 'transient'
    assert report.untimed == {u.model:input+10}
    assert u.at_ms is None


@pytest.mark.parametrize('available,raw',[(False,'gpt-5.4'),(True,'gpt-synthetic-unpriced')])
def test_unknown_time_does_not_claim_priced_when_unavailable(colophon,available,raw):
    u = unit(colophon,raw=raw,at=None)
    report = price(colophon,[u],[],available=available)
    assert u.cost_usd is None
    assert report.untimed == {}
    assert report.unpriced == ({raw:110} if available else {})


def extract(page):
    text = page.decode()
    return json.loads(re.search(r'<script type="application/json" id="colophon-data">(.*?)</script>', text, re.S)[1])


def compile_fixture(c, root, *, family=False):
    home = CodexHome(root)
    paths = []
    ids = ['synthetic-root', 'synthetic-child', 'synthetic-grandchild'] if family else ['synthetic-root']
    for n, identifier in enumerate(ids):
        fields = {'parent_thread_id': ids[n-1], 'depth': n} if n else {}
        paths.append(home.log(identifier).meta(**fields).task_started().turn_context(model='gpt-5.4').user_item().usage_record(usage={'input_tokens': 100+n, 'output_tokens': 10, 'cache_write_input_tokens': 9}).agent_item().task_complete().write())
    records = [c.parse_log_file(path, size=path.stat().st_size, mtime_ns=path.stat().st_mtime_ns, archived=False) for path in paths]
    metadata = c.CodexMetadata()
    corpus = c.build_corpus(records, metadata, NOW)
    c.link_subagents(corpus, metadata, NOW)
    workspaces = c.resolve_workspaces(corpus, [])
    c.compose_usage(corpus, c.PriorityTurns({}, []))
    report = c.price_units(corpus, c.PriceHistory([entry('gpt-5.4')], []), None, costs_available=True)
    payload = c.build_payload(corpus, workspaces, report, {'generated_at_ms': NOW, 'codex_home': root, 'logs': len(paths), 'parsed': len(paths), 'cached': 0, 'catalog': c.CatalogResult('offline', None, None, None, []), 'metadata_errors': [], 'costs_available': True, 'costs_reason': None, 'ledger': [], 'workspaces_file': []})
    return corpus, payload


def test_recursive_schema_and_usage_invariants(colophon, tmp_path):
    corpus, p = compile_fixture(colophon, tmp_path, family=True)
    assert set(p) == {'schema','meta','sessions','subagents','workspaces','models','diagnostics'}
    assert p['schema'] == 1
    assert set(p['meta']) == {'version','generated_at_ms','generated_tz','codex_home','counts','catalog','costs','live_quiet_ms','links'}
    assert set(p['meta']['counts']) == {'logs','parsed','cached','sessions','subagents','orphans'}
    assert set(p['meta']['catalog']) == {'status','fetched_at_ms','checked_at_ms','source_host'}
    assert set(p['meta']['costs']) == {'available','reason'}
    assert set(p['meta']['links']) == {'open_in_codex','continue_in_cli'}
    for link in p['meta']['links'].values():
        assert link == {'live': True,'archived': True,'subagent': True}
    assert set(p['diagnostics']) == DIAGNOSTICS
    for key in ('malformed_lines','truncated_lines','recovered_lines'):
        assert set(p['diagnostics'][key]) == {'total','files'}
        for item in p['diagnostics'][key]['files']:
            assert set(item) == {'path','count'}
    for ws in p['workspaces'].values():
        assert set(ws) == {'name','kind','keys','alias'}
    for pricing in p['models'].values():
        assert set(pricing) == {'priced','periods'}
        for period in pricing['periods']:
            assert set(period) == {'effective_from_ms','source','per_million','long_context','priority'}
            assert set(period['per_million']) == {'input','cached_input','cache_write','output'}
    for row in p['sessions'] + list(p['subagents'].values()):
        assert set(row) == (ROW if row in p['sessions'] else ROW-{'kind'} | {'parent_id','depth','agent_path','label','nickname','forked','spawn_turn','interaction_turns','link_method'})
        assert set(row['session_voice']) == {'requests','replies'}
        for request in row['session_voice']['requests']:
            assert set(request) == REQUEST
        for reply in row['session_voice']['replies']:
            assert set(reply) == {'at_ms','text'}
        assert set(row['tools']) == {'shell','shell_failed','file_edits','mcp','web','image','other'}
        for turn in row['turns']:
            assert set(turn) == TURN
            assert set(turn['usage']) == USAGE
            for reply in turn['voice_replies']:
                assert set(reply) == {'at_ms','text'}
            assert set(turn['tools']) == {'shell','shell_failed','file_edits','mcp','web','image','other'}
            if turn['final_answer']:
                assert set(turn['final_answer']) == {'text','voice'}
            for request in turn['requests']:
                assert set(request) == REQUEST
                assert request['voice_reply'] is None
        for usage in (row['own_usage'], row['outside_usage']):
            assert set(usage) == USAGE
        for component, column in [('input',3),('cached_input',4),('cache_write',5),('output',6),('reasoning',7),('cost_usd',8)]:
            assert row['own_usage'][component] == pytest.approx(sum(b[column] for b in row['buckets']))
            assert row['own_usage'][component] == pytest.approx(row['outside_usage'][component] + sum(t['usage'][component] for t in row['turns']))
    def tree_total(row,component):
        return row['own_usage'][component] + sum(tree_total(p['subagents'][child],component) for child in row['children'])
    for component,attribute in [('input','input'),('cached_input','cached'),('cache_write','cache_write'),('output','output'),('reasoning','reasoning'),('cost_usd','cost_usd')]:
        assert tree_total(p['sessions'][0],component) == pytest.approx(sum(getattr(u,attribute) or 0 for s in corpus.sessions.values() for u in s.units))
    assert tree_total(p['sessions'][0],'input') == 303


def test_payload_mixed_unpriced_null_buckets_outside_and_priority_roles(colophon, tmp_path):
    corpus,p = compile_fixture(colophon,tmp_path)
    session = next(iter(corpus.sessions.values()))
    trace = 'gpt-5.5-2026-04-23'
    key = 'catalog:'+trace+'|gpt-5.5'
    index = colophon.ModelsDevIndex.from_catalog(catalog({'gpt-5.5':model('gpt-5.5',input=2,output=7),trace:model(trace,input=11,output=13)}))
    units = [unit(colophon,trace=trace),unit(colophon,raw='gpt-synthetic-no-price'),unit(colophon,at=None,display=None)]
    session.units = units
    report = colophon.price_units(corpus,colophon.PriceHistory([entry('gpt-5.5',priority={'multiplier':2.5,'max_input_tokens':272000})],[]),index,costs_available=True)
    p = colophon.build_payload(corpus,{},report,{'codex_home':tmp_path,'generated_at_ms':NOW})
    row = p['sessions'][0]
    assert row['own_usage']['cost_usd'] is None
    assert row['own_usage']['unpriced_tokens'] == 110
    assert row['outside_usage']['input'] == 100
    assert row['outside_usage']['cost_usd'] == units[2].cost_usd
    assert [key,0,'rates'] in row['turns'][0]['usage']['priced_by']
    assert ['gpt-5.5',0,'priority'] in row['turns'][0]['usage']['priced_by']
    assert sum(b[3] for b in row['buckets']) == row['own_usage']['input'] == 300
    assert any(b[0] is None for b in row['buckets'])
    assert p['diagnostics']['untimed_usage'] == [{'model':'gpt-5.4','tokens':110}]
    assert set(p['models'][key]['periods'][0]) == {'effective_from_ms','source','per_million','long_context','priority'}


def test_priority_role_only_names_period_that_supplies_multiplier(colophon):
    u = unit(colophon,trace='gpt-5.4')
    price(colophon,[u],[entry('gpt-5.4')])
    usage = colophon._usage_payload([u],costs_available=True)
    assert usage['priced_by'] == [['gpt-5.4',0,'rates']]


def test_render_injection_surrogate_and_placeholder_roundtrip(colophon, tmp_path):
    _, p = compile_fixture(colophon, tmp_path)
    text = '</script><script>alert(1)</script>\ud800@@DATA@@/*@@CSS@@*/'
    p['sessions'][0]['turns'][0]['requests'][0]['text'] = text
    page = colophon.render_page(p)
    assert extract(page)['sessions'][0]['turns'][0]['requests'][0]['text'] == text
    data = page.split(b'id="colophon-data">')[1].split(b'</script>')[0]
    assert b'</script' not in data
    for placeholder in ('/*@@CSS@@*/','/*@@FONTS@@*/','/*@@JS@@*/','@@DATA@@'):
        assert colophon.PAGE_TEMPLATE.count(placeholder) == 1
        for asset in (colophon.PAGE_CSS, colophon.FONT_CSS, colophon.PAGE_JS):
            assert placeholder not in asset
            assert '"""' not in asset
    assert '</script' not in colophon.PAGE_JS.lower()
    assert '</style' not in colophon.PAGE_CSS.lower()


def test_payload_relative_collision_ids_use_actual_home(colophon, tmp_path):
    root = tmp_path/'sessions'/'home'
    home = CodexHome(root)
    paths = []
    for day in ('2030-01-07','2030-01-08'):
        paths.append(home.log(day=day, name='synthetic-same.jsonl').task_started().turn_context(model='gpt-5.4').token_count(total={'input_tokens': 10}).task_complete().write())
    records = [colophon.parse_log_file(path,size=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns,archived=False) for path in paths]
    corpus = colophon.build_corpus(records,colophon.CodexMetadata(),NOW)
    colophon.link_subagents(corpus,colophon.CodexMetadata(),NOW)
    colophon.compose_usage(corpus,colophon.PriorityTurns({},[]))
    pricing = colophon.price_units(corpus,colophon.PriceHistory([entry('gpt-5.4')],[]),None,costs_available=True)
    p = colophon.build_payload(corpus,{},pricing,{'generated_at_ms':NOW,'codex_home':root})
    assert {row['id'] for row in p['sessions']} == {'file:'+str(path.relative_to(root)) for path in paths}


@pytest.mark.parametrize('before,unprompted,no_turn', [(True,False,False),(False,True,False),(False,False,True),(False,False,False)])
def test_voice_association_and_no_turn_session_replies(colophon, tmp_path, before, unprompted, no_turn):
    builder = CodexHome(tmp_path).log('synthetic-voice').meta()
    if not before and not no_turn:
        builder.task_started()
    if not unprompted:
        builder.realtime_segment('Synthetic voice question')
    builder.realtime_segment('Synthetic spoken reply',role='assistant')
    if before:
        builder.task_started()
    if not no_turn:
        builder.task_complete()
    path = builder.write()
    record = colophon.parse_log_file(path,size=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns,archived=False)
    corpus = colophon.build_corpus([record],colophon.CodexMetadata(),NOW)
    p = colophon.build_payload(corpus,{},colophon.PricingReport(),{'codex_home':tmp_path,'generated_at_ms':NOW})
    row = p['sessions'][0]
    if no_turn:
        assert row['session_voice']['requests'][0]['voice_reply'] == 'Synthetic spoken reply'
        assert row['session_voice']['replies'] == [{'at_ms':None,'text':'Synthetic spoken reply'}]
    else:
        assert row['session_voice']['replies'] == []
        turn = row['turns'][0]
        if unprompted:
            assert turn['voice_replies'] == [{'at_ms':record['voice']['replies'][0]['at_ms'],'text':'Synthetic spoken reply'}]
            assert turn['final_answer'] is None
        else:
            assert turn['requests'][0]['voice_reply'] == 'Synthetic spoken reply'
            assert turn['voice_replies'] == []
            assert (turn['final_answer'] is None) == before


def test_duplicate_voice_requests_unknown_clocks_keep_explicit_pairs(colophon,tmp_path):
    builder = CodexHome(tmp_path).log('synthetic-voice-pairs').meta().task_started()
    for reply in ('Synthetic first reply','Synthetic second reply'):
        builder.realtime_segment('Synthetic repeated question').realtime_segment(reply,role='assistant')
    path = builder.task_complete().write()
    record = colophon.parse_log_file(path,size=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns,archived=False)
    for request in record['voice']['requests']:
        request['at_ms'] = None
    corpus = colophon.build_corpus([record],colophon.CodexMetadata(),NOW)
    session = next(iter(corpus.sessions.values()))
    # Pairing is source association, independent of equality or output order.
    session.turns[0].requests.reverse()
    p = colophon.build_payload(corpus,{},colophon.PricingReport(),{'codex_home':tmp_path,'generated_at_ms':NOW})
    requests = p['sessions'][0]['turns'][0]['requests']
    assert [r['voice_reply'] for r in requests] == ['Synthetic second reply','Synthetic first reply']
    assert all(r['at_ms'] is None for r in requests)
