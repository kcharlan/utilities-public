"""Task 20: independent arithmetic and every Overview navigation surface."""
import copy
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

import expected
from fixturegen import CodexHome
from tests.test_payload import ROW, TURN, REQUEST, USAGE

NOW = 1_894_708_800_000
MINUTE = 60_000


def ms(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture
def overview_payload(page_for, codex_home):
    CodexHome(codex_home).log('synthetic-template', day='2030-01-15').meta(at=NOW-MINUTE).task_started(at=NOW-MINUTE).user_item().task_complete(at=NOW).write(mtime=NOW/1000)
    page = page_for(codex_home)
    payload = json.loads(page.locator('#colophon-data').text_content())
    template = payload['sessions'][0]

    def row(identifier, workspace, turns, archived=False, children=()):
        result = copy.deepcopy(template)
        result.update(id=identifier, title='Synthetic ' + identifier, title_full='Synthetic ' + identifier,
            workspace=workspace, subfolder='src', archived=archived, children=list(children),
            start_ms=min(t[0] for t in turns), end_ms=max(t[1] for t in turns), buckets=[],
            cwd='/synthetic/' + workspace + '/src', log_path='/synthetic/' + identifier + '.jsonl')
        result['turns'] = []
        for index, (start, end, status, tokens) in enumerate(turns):
            turn = copy.deepcopy(template['turns'][0])
            turn.update(id=identifier + '-turn-' + str(index), n=index+1, status=status,
                start_ms=start, end_ms=end, duration_ms=end-start if status != 'abandoned' else None)
            for request in turn['requests']:
                request.update(at_ms=start,text='Synthetic request ' + identifier)
            result['turns'].append(turn)
            result['buckets'].append([start//900_000, 'gpt-synthetic-alpha', 'priority' if identifier == 'synthetic-a' else 'standard', tokens, tokens//4, 0, tokens//2, 0, tokens/1000])
        return result

    rows = [
        row('synthetic-a', 'synthetic-ws-a', [(ms('2030-01-14T23:30'), ms('2030-01-15T00:30'), 'completed', 100)], children=['synthetic-child']),
        row('synthetic-b', 'synthetic-ws-b', [(ms('2030-01-15T00:00'), ms('2030-01-15T01:00'), 'aborted', 200), (NOW-30*MINUTE, NOW, 'running', 300)]),
        row('synthetic-c', 'synthetic-ws-c', [(ms('2030-01-13T10:00'), ms('2030-01-13T10:20'), 'interrupted', 80), (ms('2030-01-13T11:00'), ms('2030-01-13T11:10'), 'abandoned', 40)]),
        row('synthetic-archived', 'synthetic-ws-c', [(ms('2030-01-12T09:00'), ms('2030-01-12T09:40'), 'aborted', 400)], archived=True),
        row('synthetic-prior', 'synthetic-ws-b', [(ms('2029-09-01T09:00'), ms('2029-09-01T09:10'), 'completed', 60)]),
        row('synthetic-old', 'synthetic-ws-a', [(ms('2029-01-01T09:00'), ms('2029-01-01T09:10'), 'completed', 20)]),
    ]
    child = row('synthetic-child', 'synthetic-ws-b', [(ms('2030-01-14T23:45'), ms('2030-01-15T00:45'), 'completed', 600)])
    child.pop('kind')
    child.update(parent_id='synthetic-a', agent_path='/synthetic/child', label='Synthetic child', depth=1,
        nickname=None, forked=False, spawn_turn=None, interaction_turns=[], link_method='activity')
    child['buckets'][0][1] = 'gpt-synthetic-beta'
    child['buckets'][0][8] = None
    payload.update(sessions=rows, subagents={child['id']: child},
        workspaces={key: dict(name='Synthetic workspace ' + key, kind='alias', keys=['/synthetic/' + key], alias='Synthetic ' + key) for key in ('synthetic-ws-a', 'synthetic-ws-b', 'synthetic-ws-c')},
        # Deliberately invented rates: every input token costs .001, including
        # cached input; output is free, and synthetic priority has multiplier 1.
        models={'gpt-synthetic-alpha': dict(priced=True, periods=[dict(effective_from_ms=None, source='curated', per_million=dict(input=1000, cached_input=1000,cache_write=0,output=0),long_context=None,priority=dict(multiplier=1,max_input_tokens=None))]), 'gpt-synthetic-beta': dict(priced=False, periods=[])})
    for item in rows + [child]:
        item['own_usage'] = usage(item['buckets'])
        item['outside_usage'] = usage([])
        for turn, bucket in zip(item['turns'], item['buckets']):
            turn['usage'] = usage([bucket])
        item['flags'] = sorted({'live' if t['status'] == 'running' else t['status'] for t in item['turns'] if t['status'] != 'completed'})
    payload['meta']['counts'].update(logs=7,parsed=7,cached=0,sessions=6,subagents=1,orphans=0)
    payload['meta']['costs']['available'] = True
    return payload


def usage(buckets):
    fields = ('input','cached_input','cache_write','output','reasoning')
    periods = {('gpt-synthetic-alpha',0,'rates') for b in buckets if b[8] is not None}
    if any(b[2] == 'priority' for b in buckets): periods.add(('gpt-synthetic-alpha',0,'priority'))
    return dict({field:sum(b[n+3] for b in buckets) for n,field in enumerate(fields)},
        cost_usd=None if any(b[8] is None for b in buckets) else sum(b[8] for b in buckets),
        unpriced_tokens=sum(b[3]+b[6] for b in buckets if b[8] is None), priced_by=[list(p) for p in sorted(periods)])


def test_overview_corpus_retains_complete_schema_and_usage_invariants(overview_payload):
    for workspace in overview_payload['workspaces'].values():
        assert set(workspace)=={'name','kind','keys','alias'}
    for pricing in overview_payload['models'].values():
        assert set(pricing)=={'priced','periods'}
        for period in pricing['periods']:
            assert set(period)=={'effective_from_ms','source','per_million','long_context','priority'}
    for row in overview_payload['sessions']+list(overview_payload['subagents'].values()):
        extras={'parent_id','depth','agent_path','label','nickname','forked','spawn_turn','interaction_turns','link_method'}
        assert set(row)==(ROW if 'kind' in row else ROW-{'kind'}|extras)
        assert set(row['own_usage'])==USAGE
        assert row['own_usage']==usage(row['buckets'])
        for turn in row['turns']:
            assert set(turn)==TURN
            assert all(set(request)==REQUEST for request in turn['requests'])
        for component in ('input','cached_input','cache_write','output','reasoning','unpriced_tokens'):
            assert row['own_usage'][component]==row['outside_usage'][component]+sum(t['usage'][component] for t in row['turns'])


def state(page):
    return {k: v[0] for k, v in parse_qs(urlsplit(page.url).fragment).items()}


def values(page, panel, payload):
    return page.evaluate('''([panel, payload]) => window.__colophonTest.aggregates[panel](payload.sessions, window.__colophonTest.state.readState(), payload.meta.generated_at_ms)''', [panel, payload])


@pytest.mark.parametrize('period', ['all', '90d'])
@pytest.mark.parametrize('tz', ['UTC', 'America/New_York', 'Asia/Kolkata'])
def test_every_kpi_and_panel_equals_independent_oracle(page_for, overview_payload, period, tz):
    page = page_for(overview_payload, tz=tz, hash='#p=' + period)
    wanted = expected.kpis(overview_payload, state(page), NOW, tz)
    got = values(page, 'kpis', overview_payload)
    for key, value in wanted.items():
        assert got[key] == pytest.approx(value,rel=0,abs=1e-12) if key == 'cost' else got[key] == value
    if tz == 'UTC':
        anchors = dict(sessions=6,turns=8,active_ms=200*MINUTE,agent_ms=60*MINUTE,tokens=2700,cost=1.20) if period == 'all' else dict(sessions=4,turns=6,active_ms=180*MINUTE,agent_ms=60*MINUTE,tokens=2580,cost=1.12)
        for key,value in anchors.items(): assert got[key] == pytest.approx(value,rel=0,abs=1e-12) if key == 'cost' else got[key] == value
    for key in ('sessions', 'active_ms', 'agent_ms', 'turns', 'tokens', 'cost', 'aborted'):
        actual=float(page.locator(f'[data-kpi="{key}"] .kpi-value').get_attribute('data-value'))
        assert actual == pytest.approx(wanted[key],rel=0,abs=1e-12) if key == 'cost' else actual == wanted[key]
    actual_days = values(page, 'calendar', overview_payload)
    expected_days = expected.calendar(overview_payload, state(page), NOW, tz)
    assert len(actual_days) == len(expected_days)
    for actual, wanted_day in zip(actual_days, expected_days):
        # JS left-fold and Python's compensated sum can differ by a few ulps.
        assert actual['cost'] == pytest.approx(wanted_day['cost'], rel=0, abs=1e-12)
        assert {k:v for k,v in actual.items() if k != 'cost'} == {k:v for k,v in wanted_day.items() if k != 'cost'}
    assert values(page, 'hourWeekday', overview_payload) == expected.hour_weekday(overview_payload, state(page), NOW, tz)
    ws, models = expected.rollups(overview_payload, state(page), NOW, tz)
    assert {r['key']: {k:r[k] for k in ('active_ms', 'tokens')} for r in values(page, 'workspaces', overview_payload)} == ws
    assert {r['model']: {k:r[k] for k in ('tokens', 'cost', 'unpriced')} for r in values(page, 'models', overview_payload)} == models
    assert [r['id'] for r in values(page, 'recent', overview_payload)] == expected.recent(overview_payload, state(page), NOW, tz)
    wanted_notable=expected.notable(overview_payload,state(page),NOW,tz)
    if wanted_notable['streak']:
        wanted_notable['streak']['from']=wanted_notable['streak'].pop('from_')
    actual_notable=values(page,'notable',overview_payload)
    assert actual_notable['fanout']==wanted_notable['fanout'] and actual_notable['streak']==wanted_notable['streak']
    for key in ('busiest','active'):
        assert actual_notable[key]['cost']==pytest.approx(wanted_notable[key]['cost'],rel=0,abs=1e-12)
        assert {k:v for k,v in actual_notable[key].items() if k!='cost'}=={k:v for k,v in wanted_notable[key].items() if k!='cost'}


@pytest.mark.parametrize(('tile', 'sort', 'status'), [('sessions','newest',None), ('active_ms','longest',None), ('agent_ms','subtime',None), ('turns','newest',None), ('tokens','tokens',None), ('cost','cost',None), ('aborted','newest','aborted')])
def test_tile_drills_preserve_scope_and_sort(page_for, overview_payload, tile, sort, status):
    page = page_for(overview_payload)
    page.locator(f'[data-kpi="{tile}"] .kpi-main').click()
    assert state(page)['v'] == 'list' and state(page)['sort'] == sort
    assert state(page).get('st') == status
    assert set(page.locator('[data-session-id]').evaluate_all('(rows)=>rows.map(r=>r.dataset.sessionId)')) == {r['id'] for r in expected.selected(overview_payload, state(page), NOW)}


def test_deltas_live_cost_and_separate_status_links(page_for, overview_payload):
    page = page_for(overview_payload)
    expect(page.locator('[data-kpi="active_ms"]')).to_contain_text('LIVE · includes 1 running')
    expect(page.locator('[data-kpi="cost"]')).to_contain_text('+ unpriced')
    expect(page.locator('.kpi-delta')).to_have_count(7)
    assert any('▲' in s for s in page.locator('.kpi-delta').all_text_contents())
    for key,value in dict(sessions=3,active_ms=170*MINUTE,agent_ms=60*MINUTE,turns=5,tokens=2490,cost=1.06,aborted=2).items():
        actual=float(page.locator(f'[data-kpi="{key}"] .kpi-delta').get_attribute('data-value'))
        assert actual == pytest.approx(value,rel=0,abs=1e-12) if key == 'cost' else actual == value
    prior=expected.kpis(overview_payload,state(page),NOW,bounds=expected.previous_window(state(page),NOW))
    totals=expected.kpis(overview_payload,state(page),NOW)
    for key in ('sessions','active_ms','agent_ms','turns','tokens','cost','aborted'):
        actual=float(page.locator(f'[data-kpi="{key}"] .kpi-delta').get_attribute('data-value'))
        wanted=totals[key]-prior[key]
        assert actual == pytest.approx(wanted,rel=0,abs=1e-12) if key == 'cost' else actual == wanted
    for status in ('interrupted', 'abandoned'):
        page.locator('[data-status="' + status + '"]').click()
        assert state(page)['st'] == status
        expect(page.locator('[data-session-id="synthetic-c"]')).to_be_visible()
        page.get_by_role('button', name='Remove status filter').click()
        page.get_by_role('button', name='overview', exact=True).click()
    for period in ('ALL', 'CUSTOM'):
        page.get_by_role('button', name=period, exact=True).click()
        expect(page.locator('.kpi-delta')).to_have_count(0)
    overview_payload['meta']['costs']['available'] = False
    page = page_for(overview_payload)
    expect(page.locator('[data-kpi="cost"]')).to_contain_text('costs unavailable')
    expect(page.locator('[data-kpi="cost"] .live')).to_have_count(0)
    expect(page.locator('[data-kpi="cost"] .kpi-delta')).to_have_count(0)
    for tooltip in page.locator('[data-model]').evaluate_all('(rows)=>rows.map(row=>row.title)'):
        assert tooltip == 'costs unavailable'


def test_calendar_split_heat_workspace_model_and_reader_drills(page_for, overview_payload):
    page = page_for(overview_payload)
    page.get_by_role('button', name='Calendar active time', exact=True).click()
    cell = page.locator('[data-day="2030-01-15"]')
    assert float(cell.get_attribute('data-value')) == 90 * MINUTE  # own overlapping intervals union, plus running
    cell.click()
    assert state(page)['day'] == '2030-01-15'
    page.get_by_role('button', name='Remove day filter').click()
    page.get_by_role('button', name='overview', exact=True).click()
    page.locator('[data-how="1-11"]').click()
    assert state(page)['how'] == '1-11'
    expect(page.locator('[data-session-id="synthetic-b"]')).to_be_visible()
    page.get_by_role('button', name='Remove weekday/hour filter').click()
    page.get_by_role('button', name='overview', exact=True).click()
    page.locator('[data-workspace="synthetic-ws-b"]').click()
    assert state(page)['ws'] == 'synthetic-ws-b'
    expect(page.locator('[data-session-id="synthetic-a"]')).to_be_visible()
    page.get_by_role('button', name='Remove workspace filter').click()
    page.get_by_role('button', name='overview', exact=True).click()
    page.locator('[data-model="gpt-synthetic-beta"]').click()
    assert state(page)['model'] == 'gpt-synthetic-beta'
    expect(page.locator('[data-session-id]')).to_have_count(1)
    page.locator('[data-session-id="synthetic-a"] button.session-title').click()
    expect(page.locator('[data-subagent-id="synthetic-child"]')).to_have_class(re.compile('.*matched.*'))


def test_notable_recent_archive_changes_every_panel(page_for, overview_payload):
    page = page_for(overview_payload)
    expect(page.locator('[data-notable]')).to_have_count(4)
    expect(page.locator('[data-notable="streak"]')).to_contain_text('2030-01-12 — 2030-01-15')
    for notable in ('busiest', 'active', 'fanout', 'streak'):
        page.locator('[data-notable="' + notable + '"]').click()
        assert state(page)['v'] in ('list', 'session')
        if notable == 'streak':
            assert state(page)['p'] == 'custom' and state(page)['from'] == '2030-01-12' and state(page)['to'] == '2030-01-15'
        page.get_by_role('button', name='overview', exact=True).click()
        page.get_by_role('button', name='90D', exact=True).click()
        for label in ('day',):
            button = page.get_by_role('button', name='Remove ' + label + ' filter')
            if button.count(): button.click()
    assert page.locator('[data-recent] [data-session-id]').count() == 4
    page.locator('[data-view-all]').click()
    assert state(page)['v'] == 'list'
    page.get_by_role('button', name='overview', exact=True).click()
    before = {p: values(page, p, overview_payload) for p in ('kpis','calendar','hourWeekday','workspaces','models','notable','recent')}
    page.get_by_role('button', name='archived: shown').click()
    after = {p: values(page, p, overview_payload) for p in before}
    assert all(before[p] != after[p] for p in before)


def test_unknown_times_half_open_membership_and_own_agent_union(page_for, overview_payload):
    row = copy.deepcopy(overview_payload['sessions'][0])
    row.update(id='synthetic-unknown', start_ms=None, end_ms=None, children=[], buckets=[[None,'gpt-synthetic-alpha','standard',99999,0,0,99999,0,999]])
    row['turns'][0].update(start_ms=None,end_ms=None,duration_ms=None)
    row['turns'][0]['usage']=usage(row['buckets'])
    row['own_usage']=usage(row['buckets'])
    overview_payload['sessions'].append(row)
    page = page_for(overview_payload, hash='#p=all')
    assert values(page,'kpis',overview_payload)['sessions'] == 6
    assert values(page,'kpis',overview_payload)['tokens'] == expected.kpis(overview_payload,state(page),NOW)['tokens']
    page = page_for(overview_payload, hash='#p=custom&from=2030-01-15&to=2030-01-15')
    for key,wanted in dict(sessions=2,turns=2,active_ms=90*MINUTE,agent_ms=45*MINUTE,tokens=750,cost=.50).items():
        assert values(page,'kpis',overview_payload)[key] == wanted
    assert values(page,'calendar',overview_payload)[0]['sessions']==1
    assert page.locator('.calendar-grid').evaluate('(r)=>parseFloat(r.style.getPropertyValue("--cell-size"))') == 13


def test_calendar_only_scroll_region_and_top_six_expand(page_for, overview_payload):
    extra = []
    for n in range(7):
        row = copy.deepcopy(overview_payload['sessions'][0])
        row.update(id=f'synthetic-extra-{n}', workspace=f'synthetic-extra-ws-{n}',children=[])
        overview_payload['workspaces'][row['workspace']]=dict(name='Synthetic workspace '+str(n),kind='cwd',keys=['/synthetic/extra/'+str(n)],alias=None)
        extra.append(row)
    overview_payload['sessions'] += extra
    overview_payload['sessions'][-1]['turns'][0]['start_ms'] = ms('2020-01-01T09:00')
    overview_payload['sessions'][-1]['start_ms'] = ms('2020-01-01T09:00')
    page = page_for(overview_payload, width=900, hash='#p=all')
    expect(page.locator('[data-workspace]')).to_have_count(6)
    page.get_by_role('button', name='+ 4 more', exact=True).click()
    expect(page.locator('[data-workspace]')).to_have_count(10)
    expect(page.locator('[data-scroll-region]')).to_have_count(1)
    assert page.locator('[data-scroll-region]').evaluate('(r)=>r.scrollLeft>0 && r.scrollLeft+r.clientWidth>=r.scrollWidth-1')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_workspace_metric_and_model_period_tooltip_and_quartiles(page_for, overview_payload):
    page = page_for(overview_payload)
    tooltip=page.locator('[data-model="gpt-synthetic-alpha"]').get_attribute('title')
    assert 'Recorded rate periods in matching sessions (all dates)' in tooltip
    assert 'gpt-synthetic-alpha · rates · effective_from: initial · source: curated' in tooltip
    expect(page.locator('[data-model="gpt-synthetic-beta"] .warning')).to_contain_text('unpriced')
    page.get_by_role('button',name='Workspaces tokens',exact=True).click()
    wanted,_ = expected.rollups(overview_payload,state(page),NOW)
    for key,values_ in wanted.items():
        assert float(page.locator(f'[data-workspace="{key}"] .bar-number').get_attribute('data-value')) == values_['tokens']
    assert page.evaluate('window.__colophonTest.levels([0,1,2,3,4,5,6,7,8])') == [0,1,1,2,2,3,3,4,4]
    assert page.evaluate('window.__colophonTest.levels([0,4,4,4])') == [0,1,1,1]


@pytest.mark.parametrize('case',['unused','outside-window','override','unknown-reference'])
def test_model_tooltip_uses_recorded_refs_without_inventing_bucket_attribution(page_for,overview_payload,case):
    alpha=overview_payload['models']['gpt-synthetic-alpha']
    alpha['periods'] += [dict(alpha['periods'][0],effective_from_ms=ms('2028-01-01T00:00'),source='manual'),
        dict(alpha['periods'][0],effective_from_ms=ms('2031-01-01T00:00'),source='catalog')]
    row=overview_payload['sessions'][0]
    if case=='outside-window':
        row['own_usage']['priced_by'].append(['gpt-synthetic-alpha',1,'rates'])
    if case=='override':
        key='catalog:gpt-synthetic-alias|gpt-synthetic-alpha'
        overview_payload['models'][key]=dict(priced=True,periods=[dict(alpha['periods'][0],source='transient')])
        row['own_usage']['priced_by']=[[key,0,'rates'],['gpt-synthetic-alpha',0,'priority']]
    if case=='unknown-reference':
        row['own_usage']['priced_by']=[['gpt-synthetic-alpha',999,'rates']]
    page=page_for(overview_payload,hash='#model=gpt-synthetic-beta')
    tooltip=page.locator('[data-model="gpt-synthetic-alpha"]').get_attribute('title')
    assert 'Recorded rate periods in matching sessions (all dates)' in tooltip
    assert 'source: catalog' not in tooltip  # unused future ledger entry
    if case=='outside-window':
        assert '2028-01-01T00:00:00.000Z · source: manual' in tooltip
    elif case=='override':
        assert 'catalog:gpt-synthetic-alias|gpt-synthetic-alpha · rates' in tooltip
        assert 'gpt-synthetic-alias (catalog rate used for priority turns of gpt-synthetic-alpha)' in tooltip
        assert 'gpt-synthetic-alpha · priority' in tooltip
        assert 'source: transient' in tooltip
        assert 'effective_from: unknown · source: transient' in tooltip
        assert 'effective_from: initial · source: curated' in tooltip
    elif case=='unknown-reference':
        assert 'rate period unknown' in tooltip and 'unpriced' not in tooltip
        expect(page.locator('[data-model="gpt-synthetic-alpha"]')).to_contain_text('$0.10')
    else:
        assert 'source: manual' not in tooltip


def test_combined_filters_need_one_component_with_all_evidence(page_for,overview_payload):
    page=page_for(overview_payload,hash='#ws=synthetic-ws-a&model=gpt-synthetic-beta')
    assert values(page,'kpis',overview_payload)['sessions']==0
    assert page.evaluate('''() => {
        const p=JSON.parse(document.getElementById('colophon-data').textContent);
        const match=window.__colophonTest.filters.matchSession(p.sessions[0],window.__colophonTest.state.readState(),p.subagents);
        return [match.match,[...match.matchedSubagents]];
    }''') == [False,[]]
    page.get_by_role('button',name='Remove workspace filter').click()
    assert values(page,'kpis',overview_payload)['sessions']==1
    assert page.evaluate('''() => {
        const p=JSON.parse(document.getElementById('colophon-data').textContent);
        return [...window.__colophonTest.filters.matchSession(p.sessions[0],window.__colophonTest.state.readState(),p.subagents).matchedSubagents];
    }''') == ['synthetic-child']


def test_live_usage_tiles_require_running_usage_evidence(page_for,overview_payload):
    row=overview_payload['sessions'][1]
    bucket=row['buckets'][1]
    bucket[3:9]=[0,0,0,0,0,0]
    row['own_usage']=usage(row['buckets'])
    row['turns'][1]['usage']=usage([bucket])
    page=page_for(overview_payload)
    expect(page.locator('[data-kpi="active_ms"] .live')).to_be_visible()
    expect(page.locator('[data-kpi="sessions"] .live')).to_be_visible()
    expect(page.locator('[data-kpi="turns"] .live')).to_be_visible()
    expect(page.locator('[data-kpi="tokens"] .live')).to_have_count(0)
    expect(page.locator('[data-kpi="cost"] .live')).to_have_count(0)


def test_running_usage_outside_window_does_not_mark_completed_window_usage_live(page_for, overview_payload):
    row = overview_payload['sessions'][1]
    completed, running = row['turns']
    completed.update(start_ms=ms('2030-01-15T09:00'), end_ms=ms('2030-01-15T09:10'), status='completed', duration_ms=10*MINUTE)
    running.update(start_ms=ms('2030-01-14T11:00'), end_ms=NOW, duration_ms=25*60*MINUTE)
    row.update(start_ms=running['start_ms'], end_ms=NOW)
    row['buckets'] = [
        [completed['start_ms']//900_000,'gpt-synthetic-alpha','standard',100,25,0,50,0,.1],
        [running['start_ms']//900_000,'gpt-synthetic-alpha','standard',200,50,0,100,0,.2],
    ]
    completed['usage'] = usage([row['buckets'][0]])
    running['usage'] = usage([row['buckets'][1]])
    row['own_usage'] = usage(row['buckets'])
    overview_payload.update(sessions=[row], subagents={})
    page = page_for(overview_payload,hash='#p=custom&from=2030-01-15&to=2030-01-15')
    totals = values(page,'kpis',overview_payload)
    assert totals['tokens'] == 150 and totals['cost'] == .1
    expect(page.locator('[data-kpi="active_ms"] .live')).to_be_visible()
    assert totals['live']['tokens'] == 0 and totals['live']['cost'] == 0


def test_running_untimed_usage_does_not_mark_completed_timed_usage_live(page_for,overview_payload):
    row = overview_payload['sessions'][1]
    completed, running = row['turns']
    row['buckets'][0] = [completed['start_ms']//900_000,'gpt-synthetic-alpha','standard',100,25,0,50,0,.1]
    row['buckets'][1] = [None,'gpt-synthetic-alpha','standard',200,50,0,100,0,.2]
    completed['usage'] = usage([row['buckets'][0]])
    running['usage'] = usage([row['buckets'][1]])
    row['own_usage'] = usage(row['buckets'])
    overview_payload.update(sessions=[row], subagents={})
    page = page_for(overview_payload,hash='#p=custom&from=2030-01-15&to=2030-01-15')
    totals=values(page,'kpis',overview_payload)
    assert totals['tokens'] == 150 and totals['cost'] == .1
    assert totals['live']['tokens'] == 0 and totals['live']['cost'] == 0


@pytest.mark.parametrize(('entries','token_live','cost_live'), [
    ([('completed',100,.1,'inside'),('running',200,0,'inside')],1,0),
    ([('running',100,.1,'inside'),('running',100,.1,'outside')],0,0),
    ([('running',200,.2,'inside'),('running',100,.1,'outside')],1,1),
    ([('running',100,.1,'inside'),('running',200,.2,'inside')],2,2),
    ([('completed',100,.1,'outside'),('running',200,None,'inside')],1,1),
    ([('completed',100,None,'inside'),('running',200,None,'outside')],0,0),
    ([('completed',100,None,'inside'),('running',200,None,'untimed')],0,0),
    ([('completed',100,None,'inside'),('running',200,.2,'outside')],0,0),
    ([('completed',100,None,'inside'),('running',200,.2,'inside')],1,0),
], ids=['zero-price-running','ambiguous-two-runners','one-proven-runner','two-proven-runners',
    'proven-unpriced','outside-unpriced','untimed-unpriced','closed-unpriced','unknown-own-cost'])
def test_live_usage_requires_proof_for_each_running_turn(page_for,overview_payload,entries,token_live,cost_live):
    row=overview_payload['sessions'][1]
    template=copy.deepcopy(row['turns'][1])
    row.update(turns=[],buckets=[],start_ms=ms('2030-01-14T11:00'),end_ms=NOW)
    for n,(status,tokens,cost,location) in enumerate(entries):
        turn=copy.deepcopy(template)
        turn.update(id=f'synthetic-proof-turn-{n}',n=n+1,status=status,start_ms=row['start_ms'],end_ms=NOW,duration_ms=25*60*MINUTE)
        at=ms('2030-01-15T09:00') if location=='inside' else ms('2030-01-14T11:00') if location=='outside' else None
        bucket=[at//900_000 if at is not None else None,'gpt-synthetic-alpha','standard',tokens,0,0,0,0,cost]
        turn['usage']=usage([bucket])
        row['turns'].append(turn)
        row['buckets'].append(bucket)
    row['own_usage']=usage(row['buckets'])
    overview_payload.update(sessions=[row],subagents={})
    page=page_for(overview_payload,hash='#p=custom&from=2030-01-15&to=2030-01-15')
    totals=values(page,'kpis',overview_payload)
    inside=[b for b in row['buckets'] if b[0] is not None and b[0]*900_000>=ms('2030-01-15T00:00')]
    assert totals['tokens']==sum(b[3] for b in inside)
    assert totals['cost']==pytest.approx(sum(b[8] for b in inside if b[8] is not None),rel=0,abs=1e-12)
    assert totals['unpriced']==any(b[8] is None for b in inside)
    assert totals['live']['tokens']==token_live and totals['live']['cost']==cost_live
    for key,count in [('tokens',token_live),('cost',cost_live)]:
        expect(page.locator(f'[data-kpi="{key}"] .live')).to_have_count(int(count>0))
        if count: expect(page.locator(f'[data-kpi="{key}"] .live')).to_contain_text(f'includes {count} running')


@pytest.mark.parametrize('case',['ieee-boundary','null-running-cost','null-own-cost','negative','nonfinite','unsafe-tokens','exceeds-own-capacity'])
def test_live_usage_unknown_evidence_and_cost_roundoff_do_not_prove_contribution(page_for,overview_payload,case):
    row=overview_payload['sessions'][1]
    row['buckets']=[
        [ms('2030-01-15T09:00')//900_000,'gpt-synthetic-alpha','standard',100,0,0,0,0,.1],
        [ms('2030-01-14T11:00')//900_000,'gpt-synthetic-alpha','standard',200,0,0,0,0,.2],
    ]
    row['own_usage']=usage(row['buckets'])
    for turn,bucket in zip(row['turns'],row['buckets']): turn['usage']=usage([bucket])
    # A compiler's decimal total may have the .3 representation. Subtraction
    # makes .1 > (.3 - .2) true although the entire window cost is closed usage.
    row['own_usage']['cost_usd']=.3
    if case=='null-running-cost': row['turns'][1]['usage']['cost_usd']=None
    if case=='null-own-cost': row['own_usage']['cost_usd']=None
    if case=='negative': row['own_usage'].update(input=-1,cost_usd=-1,unpriced_tokens=-1)
    if case=='unsafe-tokens': row['own_usage']['input']=2**53+2
    if case=='exceeds-own-capacity':
        row['own_usage'].update(input=50,cost_usd=.05)
        row['turns'][1]['usage'].update(input=20,cost_usd=.02)
    overview_payload.update(sessions=[row],subagents={})
    page=page_for(overview_payload,hash='#p=custom&from=2030-01-15&to=2030-01-15')
    if case=='nonfinite':
        # Corrupt only the aggregate argument, keeping the embedded JSON valid.
        totals=page.evaluate('''() => {
            const payload=JSON.parse(document.getElementById('colophon-data').textContent);
            payload.sessions[0].own_usage.input=Infinity;
            payload.sessions[0].own_usage.cost_usd=Infinity;
            return window.__colophonTest.aggregates.kpis(payload.sessions,window.__colophonTest.state.readState(),payload.meta.generated_at_ms);
        }''')
    else:
        totals=values(page,'kpis',overview_payload)
    assert totals['tokens']==100 and totals['cost']==.1
    assert totals['live']['tokens']==0 and totals['live']['cost']==0


def test_proven_running_usage_needs_no_invented_turn_timestamp(page_for,overview_payload):
    row=overview_payload['sessions'][1]
    row['turns'][1].update(start_ms=None,end_ms=None,duration_ms=None)
    overview_payload.update(sessions=[row],subagents={})
    page=page_for(overview_payload)
    totals=values(page,'kpis',overview_payload)
    assert totals['tokens']==750 and totals['cost']==.5
    assert totals['live']['tokens']==1 and totals['live']['cost']==1
    assert totals['live']['active_ms']==0 and totals['live']['sessions']==0 and totals['live']['turns']==0
    expect(page.locator('[data-kpi="tokens"] .live')).to_be_visible()
    expect(page.locator('[data-kpi="cost"] .live')).to_be_visible()


@pytest.mark.parametrize('unit_count',[1000,10000])
def test_live_cost_rejects_compiler_unit_accumulation_roundoff(page_for,overview_payload,unit_count):
    row=overview_payload['sessions'][1]
    closed_cost=running_cost=own_cost=0.0
    # Mirror _usage_payload's independent per-unit += folds: unit counts are
    # not stored in the payload, so bucket/turn counts cannot bound this error.
    for _ in range(unit_count):
        closed_cost+=.1
        own_cost+=.1
    for _ in range(unit_count):
        running_cost+=.2
        own_cost+=.2
    assert closed_cost-(own_cost-running_cost)>0
    row['buckets']=[
        [ms('2030-01-15T09:00')//900_000,'gpt-synthetic-alpha','standard',unit_count,0,0,0,0,closed_cost],
        [ms('2030-01-14T11:00')//900_000,'gpt-synthetic-alpha','standard',unit_count,0,0,0,0,running_cost],
    ]
    row['own_usage']=usage(row['buckets'])
    row['own_usage']['cost_usd']=own_cost
    for turn,bucket in zip(row['turns'],row['buckets']): turn['usage']=usage([bucket])
    overview_payload.update(sessions=[row],subagents={})
    page=page_for(overview_payload,hash='#p=custom&from=2030-01-15&to=2030-01-15')
    totals=values(page,'kpis',overview_payload)
    assert totals['tokens']==unit_count and totals['cost']==closed_cost
    assert totals['live']['tokens']==0 and totals['live']['cost']==0
    expect(page.locator('[data-kpi="cost"] .live')).to_have_count(0)


@pytest.mark.parametrize('target',['tile-subline','tile-delta','recent-metrics'])
def test_complete_tile_and_recent_row_hit_areas_drill(page_for,overview_payload,target):
    page=page_for(overview_payload)
    if target.startswith('tile'):
        selector='.kpi-sub' if target=='tile-subline' else '.kpi-delta'
        page.locator('[data-kpi="turns"] '+selector).click()
        assert state(page)['v']=='list' and state(page)['sort']=='newest'
    else:
        page.locator('[data-recent] [data-session-id="synthetic-b"] .recent-metrics').click()
        assert state(page)['v']=='session' and state(page)['s']=='synthetic-b'
