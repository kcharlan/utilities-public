"""Task 21 list/reader contract over exclusively synthetic compiler facts."""
import copy
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

import expected
from fixturegen import CodexHome
from tests.test_payload import compile_fixture, entry
from tests.test_usage import BASE, parsed, compose

NOW = 1_894_708_800_000
MINUTE = 60_000
ROOT = 'synthetic-root'


@pytest.fixture
def reader_payload(colophon, tmp_path):
    _, payload = compile_fixture(colophon, tmp_path / 'synthetic-source', family=True)
    root = payload['sessions'][0]
    root.update(title='Synthetic session title', title_full='Synthetic session title with its complete expanded detail',
        branch='synthetic-branch', originator='synthetic-originator', subfolder='src',
        start_ms=NOW-10*MINUTE, end_ms=NOW, idle_ms=2*MINUTE, user_span_ms=7*MINUTE,
        log_path='/synthetic/root.jsonl')
    payload['meta']['generated_at_ms'] = NOW
    root['turns'][0].update(start_ms=NOW-10*MINUTE, end_ms=NOW-2*MINUTE,
        duration_ms=8*MINUTE, ttft_ms=1200, spawned=['synthetic-child'], used=['synthetic-child'],
        final_answer=dict(text='Synthetic spoken final answer\n' + '\n'.join('Synthetic answer line '+str(n) for n in range(10)), voice=True))
    request = root['turns'][0]['requests'][0]
    root['turns'][0]['requests'] = [dict(request, text='Synthetic before request', before_turn=True),
        dict(request, text='Synthetic first request', before_turn=False),
        dict(request, text='Synthetic voice request', kind='voice', before_turn=False),
        dict(request, text='Synthetic follow-up three', before_turn=False),
        dict(request, text='Synthetic follow-up four\n' + '\n'.join('Synthetic line '+str(n) for n in range(10)), before_turn=False)]
    root['turns'][0]['tools'].update(shell=3, shell_failed=1, file_edits=2, web=1, image=1,
        mcp={'synthetic-server':2}, other={'synthetic-tool':1})
    for n, identifier in enumerate(('synthetic-child','synthetic-grandchild')):
        child = payload['subagents'][identifier]
        child.update(start_ms=NOW-(9-n)*MINUTE, end_ms=NOW-(3-n)*MINUTE,
            label='Synthetic '+('code review' if n == 0 else 'nested audit'), nickname='Agent-Alpha',
            forked=n == 0, link_method='inferred' if n == 0 else 'activity')
        child['turns'][0].update(start_ms=child['start_ms'], end_ms=child['end_ms'], duration_ms=6*MINUTE,
            final_answer=dict(text='Synthetic child final answer', voice=False))
    root['buckets'][0][0] = (NOW-10*MINUTE)//900000
    return payload


@pytest.fixture
def list_payload(reader_payload):
    payload = copy.deepcopy(reader_payload)
    root = payload['sessions'][0]
    root['flags'] = ['live', 'aborted', 'interrupted', 'abandoned', 'uncertain_timing']
    root['archived'] = True
    rows = [root]
    for n in (1, 2):
        row = copy.deepcopy(root)
        row.update(id='synthetic-list-'+str(n), title='Synthetic ranked '+str(n), title_full='Synthetic ranked '+str(n),
            start_ms=NOW-n*86400000, end_ms=NOW-n*86400000+n*MINUTE,
            children=[], flags=[], archived=False)
        row['turns'][0].update(start_ms=row['start_ms'], end_ms=row['end_ms'], duration_ms=n*MINUTE)
        row['own_usage'].update(input=n*1000, output=n*10, cost_usd=n*10)
        row['turns'][0]['usage'] = copy.deepcopy(row['own_usage'])
        u = row['own_usage']
        row['buckets'] = [[row['start_ms']//900000,'gpt-5.4','standard',u['input'],u['cached_input'],u['cache_write'],u['output'],u['reasoning'],u['cost_usd']]]
        rows.append(row)
    orphan = copy.deepcopy(root)
    orphan.update(id='synthetic-orphan', kind='orphan', children=[], flags=['orphaned'],
        start_ms=NOW-3*86400000, end_ms=NOW-3*86400000+8*MINUTE)
    orphan['turns'][0].update(start_ms=orphan['start_ms'],end_ms=orphan['end_ms'])
    orphan['buckets'][0][0] = orphan['start_ms']//900000
    payload['sessions'] = rows+[orphan]
    return payload


def open_reader(page_for, payload, **kwargs):
    return page_for(payload, hash='#v=session&p=all&s='+ROOT, **kwargs)


def row_ids(page):
    return page.locator('[data-list-row]').evaluate_all('(rows)=>rows.map(row=>row.dataset.sessionId)')


@pytest.mark.parametrize('tz,first', [('UTC','TUE JAN 15'), ('America/New_York','TUE JAN 15'), ('Asia/Kolkata','TUE JAN 15')])
def test_list_day_groups_rows_and_top_level_sessions_include_orphans(page_for, list_payload, tz, first):
    page = page_for(list_payload, tz=tz, hash='#v=list&p=all')
    expect(page.locator('[data-day-header]').first).to_have_text(first)
    assert row_ids(page) == [ROOT,'synthetic-list-1','synthetic-list-2','synthetic-orphan']
    expect(page.locator('[data-list-row]').last).to_contain_text('orphaned')
    row = page.locator('[data-list-row]').first
    expect(row).to_contain_text('ARCHIVED')
    expect(row).to_contain_text('2 sub')
    for text in ('LIVE','aborted','interrupted','abandoned','uncertain timing','src'):
        expect(row).to_contain_text(text)
    assert row.locator('.session-title').get_attribute('title') == list_payload['sessions'][0]['title_full']
    assert row.locator('.list-time').inner_text() == ('11:50' if tz=='UTC' else '06:50' if tz=='America/New_York' else '17:20')
    assert row.locator('.list-metrics').evaluate('(n)=>getComputedStyle(n).width') == '92px'
    assert row.locator('.session-title').evaluate('(n)=>getComputedStyle(n).textOverflow') == 'ellipsis'
    assert page.locator('[data-day-header]').first.evaluate('(n)=>getComputedStyle(n).color') == 'rgb(255, 181, 71)'


@pytest.mark.parametrize('sort,wanted', [('newest',[ROOT,'synthetic-list-1','synthetic-list-2','synthetic-orphan']),
    ('longest',[ROOT,'synthetic-orphan','synthetic-list-2','synthetic-list-1']), ('subtime',[ROOT,'synthetic-list-1','synthetic-list-2','synthetic-orphan']),
    ('tokens',['synthetic-list-2','synthetic-list-1',ROOT,'synthetic-orphan']), ('cost',['synthetic-list-2','synthetic-list-1',ROOT,'synthetic-orphan'])])
def test_each_sort_and_flat_ranked_list(page_for, list_payload, sort, wanted):
    page = page_for(list_payload, hash='#v=list&p=all')
    page.get_by_role('button', name={'subtime':'subagent time'}.get(sort,sort), exact=True).click()
    assert row_ids(page) == wanted
    expect(page.locator('[data-day-header]')).to_have_count(4 if sort=='newest' else 0)
    assert parse_qs(urlsplit(page.url).fragment)['sort'] == [sort]


def test_list_search_archive_row_selection_and_history(page_for, list_payload):
    page = page_for(list_payload, hash='#v=list&p=all')
    page.get_by_role('searchbox').fill('follow-up three')
    expect(page.locator('[data-list-row]')).to_have_count(4)
    page.get_by_role('button', name='archived: shown').click()
    expect(page.locator('[data-list-row]')).to_have_count(2)
    page.get_by_role('searchbox').fill('ranked 1')
    expect(page.locator('[data-list-row]')).to_have_count(1)
    history = page.evaluate('history.length')
    page.locator('[data-list-row] .list-metrics').click()
    assert 'v=session' in page.url and 's=synthetic-list-1' in page.url
    assert page.evaluate('history.length') == history+1
    expect(page.locator('[data-reader]')).to_be_visible()
    page.go_back()
    expect(page.locator('[data-reader]')).to_have_count(0)


def test_list_fixture_usage_and_clock_invariants(list_payload):
    for row in list_payload['sessions']+list(list_payload['subagents'].values()):
        for field,index in [('input',3),('cached_input',4),('cache_write',5),('output',6),('reasoning',7)]:
            assert row['own_usage'][field] == sum(b[index] for b in row['buckets'])
            assert row['own_usage'][field] == row['outside_usage'][field]+sum(t['usage'][field] for t in row['turns'])
        assert row['own_usage']['unpriced_tokens'] == row['outside_usage']['unpriced_tokens']+sum(t['usage']['unpriced_tokens'] for t in row['turns'])
        assert row['own_usage']['cost_usd'] == pytest.approx(sum(b[8] for b in row['buckets']),rel=0,abs=1e-12)
        for turn in row['turns']:
            assert turn['duration_ms'] == turn['end_ms']-turn['start_ms']


@pytest.mark.parametrize('sort,first',[('longest',ROOT),('tokens','synthetic-list-2'),('cost','synthetic-list-2')])
def test_list_ranking_and_figures_clip_to_active_period(page_for,list_payload,sort,first):
    row = list_payload['sessions'][1]
    old = copy.deepcopy(row['turns'][0])
    old.update(id='synthetic-old-ranked-turn',n=2,start_ms=NOW-30*86400000,
        end_ms=NOW-30*86400000+200*MINUTE,duration_ms=200*MINUTE)
    old['usage'].update(input=5000,output=50,cached_input=0,cache_write=0,reasoning=0,cost_usd=100)
    row['turns'].append(old)
    row['start_ms']=old['start_ms']
    row['buckets'].append([old['start_ms']//900000,'gpt-5.4','standard',5000,0,0,50,0,100])
    for field in ('input','output','cached_input','cache_write','reasoning','cost_usd','unpriced_tokens'):
        row['own_usage'][field] += old['usage'][field]
    page = page_for(list_payload,hash='#v=list&p=all&sort='+sort)
    assert row_ids(page)[0]=='synthetic-list-1'
    page.get_by_role('button',name='7D',exact=True).click()
    assert row_ids(page)[0]==first
    metric = page.locator('[data-list-row][data-session-id="synthetic-list-1"] .list-metrics')
    assert metric.get_attribute('data-active-ms')=='60000'
    assert metric.get_attribute('data-tokens')=='1010'
    assert float(metric.get_attribute('data-cost'))==10


@pytest.mark.parametrize('tz,day,time',[('UTC','TUE JAN 15','00:30'),('America/New_York','MON JAN 14','19:30'),('Asia/Kolkata','TUE JAN 15','06:00')])
def test_list_day_and_time_cross_viewer_midnight(page_for,list_payload,tz,day,time):
    root=list_payload['sessions'][0]
    root.update(start_ms=NOW-690*MINUTE,end_ms=NOW-682*MINUTE)
    root['turns'][0].update(start_ms=root['start_ms'],end_ms=root['end_ms'])
    root['buckets'][0][0]=root['start_ms']//900000
    page=page_for(list_payload,tz=tz,hash='#v=list&p=all')
    expect(page.locator('[data-day-header]').first).to_have_text(day)
    expect(page.locator('[data-list-row]').first.locator('.list-time')).to_have_text(time)


def test_unknown_list_start_is_last_with_unknown_day(page_for,list_payload):
    list_payload['sessions'][0].update(start_ms=None,end_ms=None)
    page=page_for(list_payload,hash='#v=list&p=all')
    assert row_ids(page)[-1]==ROOT
    expect(page.locator('[data-day-header]').last).to_have_text('UNKNOWN DAY')
    expect(page.locator('[data-list-row]').last.locator('.list-time')).to_have_text('unknown')


@pytest.mark.parametrize('width,split', [(390,False),(899,False),(900,True),(1440,True)])
def test_responsive_split_and_back(page_for, reader_payload, width, split):
    page = open_reader(page_for, reader_payload, width=width)
    expect(page.locator('[data-reader]')).to_be_visible()
    assert page.locator('[data-session-list]').is_visible() == split
    assert page.get_by_role('button', name='← sessions', exact=True).is_visible() == (not split)
    if not split:
        page.get_by_role('button', name='← sessions', exact=True).click()
        assert 'v=list' in page.url and '&s=' not in page.url
        expect(page.locator('[data-session-list]')).to_be_visible()


def test_reader_header_links_and_title_expansion(page_for, reader_payload):
    reader_payload['sessions'][0]['forked_from'] = 'synthetic-list-parent'
    parent = copy.deepcopy(reader_payload['sessions'][0])
    parent.update(id='synthetic-list-parent', title='Synthetic parent', forked_from=None)
    reader_payload['sessions'].append(parent)
    page = open_reader(page_for, reader_payload)
    header = page.locator('[data-reader-header]')
    for text in ('Synthetic session title','src','synthetic-branch','synthetic-originator','syntheti…tic-root','11:50','12:00'):
        expect(header).to_contain_text(text)
    expect(header.locator('[data-time-range]')).to_have_attribute('title','user-request span: 7.0m')
    page.get_by_role('button', name='Expand full title').click()
    expect(header).to_contain_text(reader_payload['sessions'][0]['title_full'])
    expect(page.get_by_role('link', name='Open in Codex')).to_have_attribute('href','codex://threads/'+ROOT)
    expect(page.get_by_role('button', name='Copy Continue in CLI — continues this session')).to_be_visible()
    page.get_by_role('button', name='forked from Synthetic parent', exact=True).click()
    assert 's=synthetic-list-parent' in page.url


@pytest.mark.parametrize('parent_kind', ['session', 'subagent'])
def test_fork_link_uses_known_title_outside_filtered_list_and_navigates_by_id(page_for, reader_payload, parent_kind):
    root = reader_payload['sessions'][0]
    parent_id = 'synthetic-list-parent' if parent_kind == 'session' else 'synthetic-child'
    root['forked_from'] = parent_id
    if parent_kind == 'session':
        parent = copy.deepcopy(root)
        parent.update(id=parent_id, title='Synthetic known parent title', title_full='Synthetic known parent title',
                      forked_from=None, archived=True)
        reader_payload['sessions'].append(parent)
    else:
        reader_payload['subagents'][parent_id]['title'] = 'Synthetic known parent title'
    page = page_for(reader_payload, hash='#v=session&p=all&a=0&s='+ROOT)
    assert parent_id not in row_ids(page)
    page.get_by_role('button', name='forked from Synthetic known parent title', exact=True).click()
    assert parse_qs(urlsplit(page.url).fragment)['s'] == [parent_id]


@pytest.mark.parametrize('title', [None, '', '   ', 42])
def test_fork_link_invalid_parent_title_falls_back_to_id(page_for, reader_payload, title):
    root = reader_payload['sessions'][0]
    root['forked_from'] = 'synthetic-child'
    reader_payload['subagents']['synthetic-child']['title'] = title
    page = open_reader(page_for, reader_payload)
    expect(page.locator('.fork-link')).to_have_text('forked from synthetic-child')


def test_fork_link_missing_parent_falls_back_to_id_and_preserves_navigation(page_for, reader_payload):
    reader_payload['sessions'][0]['forked_from'] = 'synthetic-missing-parent'
    page = open_reader(page_for, reader_payload)
    page.get_by_role('button', name='forked from synthetic-missing-parent', exact=True).click()
    assert parse_qs(urlsplit(page.url).fragment)['s'] == ['synthetic-missing-parent']


def test_fork_link_conflicting_parent_titles_fall_back_to_id(page_for, reader_payload):
    root = reader_payload['sessions'][0]
    root['forked_from'] = 'synthetic-ambiguous-parent'
    for title in ('Synthetic parent one', 'Synthetic parent two'):
        parent = copy.deepcopy(root)
        parent.update(id='synthetic-ambiguous-parent', title=title, forked_from=None)
        reader_payload['sessions'].append(parent)
    page = open_reader(page_for, reader_payload)
    expect(page.locator('.fork-link')).to_have_text('forked from synthetic-ambiguous-parent')


def test_reader_six_stats_and_depth_two_independent_overall(page_for, reader_payload):
    root = reader_payload['sessions'][0]
    want = expected.overall(root, reader_payload)
    # Independent fixture anchor: (100+101+102) input +3*10 output, writes3*9.
    assert want['tokens'] == 333 and want['cache_write'] == 27 and want['subagents'] == 2
    page = open_reader(page_for, reader_payload)
    expect(page.locator('[data-reader-stat]')).to_have_count(6)
    for key, value in [('active',8*MINUTE),('span',10*MINUTE),('turns',1),('subagents',2),('tokens',want['tokens']),('cost',want['cost_usd'])]:
        assert float(page.locator(f'[data-reader-stat="{key}"] [data-value]').get_attribute('data-value')) == pytest.approx(value,rel=0,abs=1e-12)
    expect(page.locator('[data-reader-stat="span"]')).to_contain_text('idle 2.0m')
    expect(page.locator('[data-reader-stat="tokens"]')).to_contain_text('total (yours + subagents)')
    expect(page.locator('[data-reader-stat="tokens"]')).to_contain_text('110 yours + 223 subagents')
    expect(page.locator('[data-reader-stat="subagents"]')).to_contain_text('12.0m agent time')
    expect(page.locator('[data-reader-stat="cost"]')).to_contain_text('API-equivalent estimate (not billed)')


def test_reader_cost_tooltip_preserves_recorded_sources_roles_and_unknown_period(page_for,reader_payload):
    pricing = reader_payload['models']['gpt-5.4']
    initial = pricing['periods'][0]
    pricing['periods'] = [copy.deepcopy(initial) for _ in range(4)]
    for index, source in enumerate(('curated','manual','catalog','transient')):
        pricing['periods'][index].update(source=source,effective_from_ms=None if index in (0,3) else NOW-index*86400000)
    root = reader_payload['sessions'][0]
    root['turns'][0]['usage']['priced_by'] = [['gpt-5.4',index,'priority' if index==2 else 'rates'] for index in range(4)]
    root['own_usage']['priced_by'] = copy.deepcopy(root['turns'][0]['usage']['priced_by'])
    page = open_reader(page_for,reader_payload)
    tooltip = page.locator('[data-turn-cost]').get_attribute('title')
    for source in ('curated','manual','catalog','transient'):
        assert 'source: '+source in tooltip
    assert '· priority ·' in tooltip and 'effective_from: unknown · source: transient' in tooltip
    root['turns'][0]['usage']['priced_by']=[['gpt-synthetic-missing',0,'rates']]
    page = open_reader(page_for,reader_payload)
    assert 'rate period unknown' in page.locator('[data-turn-cost]').get_attribute('title')
    reader_payload['meta']['costs']['available']=False
    page = open_reader(page_for,reader_payload)
    expect(page.locator('[data-reader-stat="cost"]')).to_contain_text('costs unavailable')
    assert page.locator('[data-turn-cost]').get_attribute('title')=='costs unavailable · API-equivalent estimate (not billed)'


def test_reader_partial_unknown_clock_never_asserts_complete_active_union(page_for,reader_payload):
    root = reader_payload['sessions'][0]
    extra = copy.deepcopy(root['turns'][0])
    extra.update(id='synthetic-clockless-turn',n=2,start_ms=None,end_ms=None,duration_ms=3000,flags=['reported_duration'],spawned=[],used=[])
    extra['usage'].update(input=0,output=0,cached_input=0,cache_write=0,reasoning=0,cost_usd=0,unpriced_tokens=0,priced_by=[])
    root['turns'].append(extra)
    root['idle_ms']=None
    page = open_reader(page_for,reader_payload)
    expect(page.locator('[data-reader-stat="active"]')).to_contain_text('unknown')
    expect(page.locator('[data-turn-card]').last.locator('[data-turn-header]')).to_contain_text('3.0s')
    expect(page.locator('[data-reader-stat="subagents"]')).to_contain_text('12.0m agent time')


def test_overall_oracle_counts_cycles_and_duplicates_once(page_for,reader_payload):
    root = reader_payload['sessions'][0]
    root['children'] += ['synthetic-grandchild','synthetic-child','synthetic-missing']
    reader_payload['subagents']['synthetic-grandchild']['children'] = [ROOT,'synthetic-child']
    assert expected.overall(root,reader_payload)['tokens'] == 333
    page=open_reader(page_for,reader_payload)
    expect(page.locator('[data-reader-stat="tokens"]')).to_contain_text('333')


def test_reader_overall_unsafe_sum_is_unknown_without_changing_own_counts(page_for,reader_payload):
    root=reader_payload['sessions'][0]
    root['own_usage']['input']=9007199254740791
    root['turns'][0]['usage']['input']=root['own_usage']['input']
    root['buckets'][0][3]=root['own_usage']['input']
    assert expected.overall(root,reader_payload)['tokens']==9007199254741024
    page=open_reader(page_for,reader_payload)
    expect(page.locator('[data-reader-stat="tokens"] .reader-stat-value')).to_have_text('unknown')


def test_reader_untimed_usage_unknown_span_and_reported_duration(page_for, reader_payload):
    row = reader_payload['sessions'][0]
    row.update(start_ms=None,end_ms=None,idle_ms=None,user_span_ms=None)
    row['buckets'][0][0] = None
    row['turns'][0].update(start_ms=None,end_ms=None,duration_ms=8*MINUTE,flags=['reported_duration'])
    # Child clocks still retain the parent in the existing filter path.
    page = open_reader(page_for,reader_payload)
    expect(page.locator('[data-reader-stat="span"]')).to_contain_text('unknown')
    expect(page.locator('[data-reader-stat="active"]')).to_contain_text('unknown')
    expect(page.locator('[data-reader-stat="tokens"]')).to_contain_text('333')
    expect(page.locator('[data-turn-header]')).to_contain_text('unknown — unknown')
    expect(page.locator('[data-turn-header]')).to_contain_text('8.0m')
    expect(page.locator('[data-timeline]')).to_contain_text('timeline unavailable: unknown session span')
    assert '1970' not in page.locator('[data-reader]').inner_text()


@pytest.mark.parametrize('width', [390, 1440])
def test_timeline_lanes_ticks_fork_badges_and_inferred_border(page_for, reader_payload, width):
    page = open_reader(page_for,reader_payload,width=width)
    page.evaluate('document.fonts.ready')
    expect(page.locator('[data-timeline-tick]')).to_have_count(5)
    expect(page.locator('[data-timeline-lane]')).to_have_count(3)
    expect(page.locator('[data-timeline-idle]')).to_be_visible()
    inferred = page.locator('[data-timeline-subagent="synthetic-child"]')
    assert inferred.evaluate('(n)=>getComputedStyle(n).borderStyle') == 'dashed'
    assert page.locator('[data-timeline-turn]').evaluate('(n)=>getComputedStyle(n).backgroundColor') == 'rgb(42, 122, 82)'
    badge = page.locator('[data-timeline-label] .tag')
    expect(badge).to_have_count(1)
    expect(badge).to_have_text('forked')
    expect(badge).to_be_visible()
    assert badge.evaluate('(n)=>getComputedStyle(n).borderStyle') == 'solid'
    assert badge.evaluate('(n)=>getComputedStyle(n).borderTopWidth') == '1px'
    assert 0 < badge.bounding_box()['height'] <= 10
    assert page.locator('[data-timeline]').bounding_box()['height'] == 74
    assert page.locator('.timeline-track').evaluate_all('(nodes)=>nodes.every(n=>n.getBoundingClientRect().height===14)')
    assert page.locator('.timeline-block').evaluate_all('(nodes)=>nodes.every(n=>n.getBoundingClientRect().height===12)')
    assert page.locator('[data-timeline-label-row]').evaluate_all('''nodes=>nodes.every(n=>{const r=n.getBoundingClientRect(),p=n.parentElement.getBoundingClientRect();return r.left>=p.left && r.right<=p.right+1;})''')
    rects = page.locator('[data-timeline-label-row]').evaluate_all('(nodes)=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};})')
    assert all(not(a['x'] < b['right'] and b['x'] < a['right'] and a['y'] < b['bottom'] and b['y'] < a['bottom']) for n,a in enumerate(rects) for b in rects[n+1:])


@pytest.mark.parametrize('width',[390,1440])
def test_three_lane_timeline_preserves_approved_74_pixel_height(page_for,reader_payload,width):
    page=open_reader(page_for,reader_payload,width=width)
    assert page.locator('[data-timeline]').bounding_box()['height']==74
    assert page.locator('.timeline-track').evaluate_all('(nodes)=>nodes.every(n=>n.getBoundingClientRect().height===14)')


@pytest.mark.parametrize('width',[390,1440])
def test_timeline_ticks_align_to_session_endpoints_and_quarters(page_for,reader_payload,width):
    page=open_reader(page_for,reader_payload,width=width)
    axis=page.locator('.timeline-ticks').bounding_box()
    ticks=page.locator('[data-timeline-tick]').all()
    assert ticks[0].bounding_box()['x']==pytest.approx(axis['x'],abs=1)
    for n in (1,2,3):
        tick=ticks[n].bounding_box()
        assert tick['x']+tick['width']/2==pytest.approx(axis['x']+axis['width']*n/4,abs=1)
    last=ticks[4].bounding_box()
    assert last['x']+last['width']==pytest.approx(axis['x']+axis['width'],abs=1)


def test_timeline_collision_labels_use_second_row_then_tooltip(page_for,reader_payload):
    row = reader_payload['sessions'][0]
    first = row['turns'][0]
    row['turns'] = [dict(copy.deepcopy(first), id='synthetic-collision-'+str(n), n=n+1,
        start_ms=NOW-10*MINUTE+n, end_ms=NOW-10*MINUTE+n+1,duration_ms=1) for n in range(6)]
    for turn in row['turns'][1:]:
        turn['usage'].update(input=0,output=0,cached_input=0,cache_write=0,reasoning=0,cost_usd=0,unpriced_tokens=0,priced_by=[])
    row['idle_ms']=10*MINUTE-6
    page = open_reader(page_for,reader_payload,width=390)
    assert page.locator('[data-timeline-label-row="1"]').count() >= 1
    assert page.locator('[data-timeline-turn][data-tooltip-only]').count() >= 1
    labels = page.locator('[data-timeline-label-row]').evaluate_all('(nodes)=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};})')
    assert all(not(a['x'] < b['right'] and b['x'] < a['right'] and a['y'] < b['bottom'] and b['y'] < a['bottom']) for n,a in enumerate(labels) for b in labels[n+1:])


def test_timeline_labels_remeasure_on_resize(page_for,reader_payload):
    row = reader_payload['sessions'][0]
    first = row['turns'][0]
    row['turns'] = [dict(copy.deepcopy(first),id='synthetic-resize-'+str(n),n=n+1,
        start_ms=row['start_ms']+n*35000,end_ms=row['start_ms']+n*35000+1000,duration_ms=1000) for n in range(12)]
    for turn in row['turns'][1:]:
        turn['usage'].update(input=0,output=0,cached_input=0,cache_write=0,reasoning=0,cost_usd=0,unpriced_tokens=0,priced_by=[])
    row['idle_ms']=10*MINUTE-12000
    page = open_reader(page_for,reader_payload,width=1920)
    page.evaluate('document.fonts.ready')
    assert page.locator('[data-label-kind="turn"][data-timeline-label-row="1"]').count()==0
    page.set_viewport_size(dict(width=390,height=900))
    expect(page.locator('[data-label-kind="turn"][data-timeline-label-row="1"]').first).to_be_visible()
    assert page.locator('[data-tooltip-only]').count()>0
    assert page.locator('[data-timeline-label-row]').evaluate_all('''nodes=>nodes.every(n=>{const r=n.getBoundingClientRect(),p=n.parentElement.getBoundingClientRect();return r.left>=p.left && r.right<=p.right+1;})''')
    rects = page.locator('[data-timeline-label-row]').evaluate_all('(nodes)=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};})')
    assert all(not(a['x'] < b['right'] and b['x'] < a['right'] and a['y'] < b['bottom'] and b['y'] < a['bottom']) for n,a in enumerate(rects) for b in rects[n+1:])


@pytest.mark.parametrize('bad',[None,True,-1,'synthetic-invalid',9007199254740992,.5,9007199254740991])
def test_malformed_token_components_remain_unknown_in_each_reader_surface(page_for,reader_payload,bad):
    root = reader_payload['sessions'][0]
    root['turns'][0]['usage']['input']=bad
    child = reader_payload['subagents']['synthetic-child']
    child['own_usage']['input']=bad
    root['outside_usage'].update(input=bad,output=10,cache_write=1)
    page = open_reader(page_for,reader_payload)
    expect(page.locator('[data-turn-header]')).to_contain_text('unknown tokens')
    subrow = page.locator('[data-subagent-id="synthetic-child"]')
    expect(subrow.locator('.subagent-metrics')).to_contain_text('unknown tokens')
    subrow.get_by_role('button',name='Expand Synthetic code review').click()
    expect(subrow.locator('[data-mini-card]')).to_contain_text('unknown tokens')
    expect(page.locator('[data-outside-usage]')).to_contain_text('tokens outside displayed turns: unknown')


def test_zero_token_components_are_known_zero(page_for,reader_payload):
    root = reader_payload['sessions'][0]
    root['turns'][0]['usage'].update(input=0,output=0)
    child = reader_payload['subagents']['synthetic-child']
    child['own_usage'].update(input=0,output=0)
    root['outside_usage'].update(input=0,output=0,cache_write=1)
    page = open_reader(page_for,reader_payload)
    expect(page.locator('[data-turn-header]')).to_contain_text('0 tokens')
    childrow = page.locator('[data-subagent-id="synthetic-child"]')
    expect(childrow.locator('.subagent-metrics')).to_contain_text('0 tokens')
    childrow.get_by_role('button',name='Expand Synthetic code review').click()
    expect(childrow.locator('[data-mini-card]')).to_contain_text('0 tokens')
    expect(page.locator('[data-outside-usage]')).to_contain_text('tokens outside displayed turns: 0')


def test_turn_requests_before_group_followups_voice_and_long_text(page_for,reader_payload):
    page = open_reader(page_for,reader_payload)
    card = page.locator('[data-turn-card]').first
    expect(card).to_contain_text('YOU ASKED · 4')
    expect(card.locator('[data-before-turn] .request-meta')).to_have_text('before this turn')
    expect(card.locator('[data-before-turn] [data-long-text]')).to_have_text('Synthetic before request')
    before = card.locator('[data-before-turn]').bounding_box()
    first = card.get_by_text('Synthetic first request',exact=True).bounding_box()
    assert before['y'] < first['y']
    expect(card.get_by_text('Synthetic follow-up three',exact=True)).to_be_hidden()
    card.get_by_role('button',name='+ 2 follow-ups sent while it worked').click()
    expect(card.get_by_text('Synthetic follow-up three',exact=True)).to_be_visible()
    long = card.locator('[data-request]').last
    assert long.locator('[data-long-text]').evaluate('(n)=>getComputedStyle(n).webkitLineClamp') == '6'
    long.get_by_role('button',name='more',exact=True).click()
    assert long.locator('[data-long-text]').evaluate('(n)=>getComputedStyle(n).webkitLineClamp') == 'none'
    expect(card).to_contain_text('voice request')
    expect(card).to_contain_text('voice reply')
    card.get_by_role('button',name='expand',exact=True).click()
    expect(card).to_contain_text('Synthetic answer line 9')


def test_turn_header_tools_rate_periods_and_subagent_expansion(page_for,reader_payload):
    page = open_reader(page_for,reader_payload)
    card = page.locator('[data-turn-card]').first
    for text in ('11:50','11:58','8.0m','first token 1.2s','110','completed','IT USED','SUBAGENTS · 1','FINAL ANSWER'):
        expect(card).to_contain_text(text)
    for text in ('shell 3','file edits 2','web 1','image 1','synthetic-server 2','synthetic-tool 1'):
        expect(card.locator('[data-tools]').first).to_contain_text(text)
    assert card.locator('[data-tool-failure]').evaluate('(n)=>getComputedStyle(n).color') == 'rgb(255, 181, 71)'
    tooltip = card.locator('[data-turn-cost]').get_attribute('title')
    assert 'gpt-5.4' in tooltip and 'source: curated' in tooltip and 'effective_from: initial' in tooltip
    child = card.locator('[data-subagent-id="synthetic-child"]')
    expect(child).to_contain_text('Synthetic code review · Agent-Alpha')
    expect(child).to_contain_text('forked')
    child.get_by_role('button',name='Expand Synthetic code review').click()
    expect(child.locator('[data-mini-card]')).to_contain_text('Synthetic child final answer')
    expect(child.locator('[data-mini-card]')).to_contain_text('tokens')
    expect(child.locator('[data-mini-card] [data-tools]')).to_be_visible()


def test_interaction_only_used_missing_links_and_model_highlight(page_for,reader_payload):
    root = reader_payload['sessions'][0]
    root['turns'][0]['spawned'] = ['synthetic-missing']
    root['turns'][0]['used'] = ['synthetic-child','synthetic-missing']
    page = open_reader(page_for,reader_payload)
    expect(page.locator('[data-turn-card]')).to_contain_text('also used: Synthetic code review')
    assert 'undefined' not in page.locator('[data-reader]').inner_text()
    child = reader_payload['subagents']['synthetic-child']
    child['buckets'][0][0] = (NOW-9*MINUTE)//900000
    child['buckets'][0][1] = 'gpt-synthetic-child-only'
    page = page_for(reader_payload,hash='#v=session&p=all&s='+ROOT+'&model=gpt-synthetic-child-only')
    expect(page.locator('[data-subagent-id="synthetic-child"]')).to_have_class('subagent-row matched')


def test_outside_tokens_from_task15_inherited_fallback_fixture(page_for,colophon,tmp_path):
    # Same Task15 fork reproduction: parent10, inherited15 ->5 outside, own20 ->5.
    source = CodexHome(tmp_path/'synthetic-home')
    parent = parsed(colophon,source.log('synthetic-parent').meta(at=BASE-100).token_count(at=BASE-90,total={'input_tokens':10},last={'input_tokens':10}))
    fork = parsed(colophon,source.log('synthetic-fork').meta(at=BASE,forked_from_id='synthetic-parent').meta(at=BASE+1,id='synthetic-parent')
        .token_count(at=BASE+2,turn_id='synthetic-owned',total={'input_tokens':15},last={'input_tokens':5})
        .task_started('synthetic-owned',at=BASE+1001).token_count(at=BASE+1002,total={'input_tokens':20},last={'input_tokens':5}))
    corpus = compose(colophon,[parent,fork])
    report = colophon.price_units(corpus,colophon.PriceHistory([entry('gpt-5.4')],[]),None,costs_available=True)
    p = colophon.build_payload(corpus,colophon.resolve_workspaces(corpus,[]),report,
        dict(generated_at_ms=BASE+3600000,codex_home=source.root,logs=2,parsed=2,cached=0,
            catalog=colophon.CatalogResult('offline',None,None,None,[]),metadata_errors=[],costs_available=True,costs_reason=None,ledger=[],workspaces_file=[]))
    row = next(s for s in p['sessions'] if s['id']=='synthetic-fork')
    assert row['own_usage']['input']==10 and row['outside_usage']['input']==5 and row['turns'][0]['usage']['input']==5
    page = page_for(p,hash='#v=session&p=all&s=synthetic-fork')
    expect(page.locator('[data-outside-usage]')).to_contain_text('tokens outside displayed turns: 5')


@pytest.mark.parametrize('method',['absent','reject','success'])
@pytest.mark.parametrize('button,value',[('Copy session ID',ROOT),('Copy log path','/synthetic/root.jsonl'),
    ('Copy Continue in CLI — continues this session','codex resume '+ROOT)])
def test_clipboard_stub_and_selected_readonly_fallback(page_for,reader_payload,method,button,value):
    clipboard = 'undefined' if method=='absent' else '{writeText: async value => {'+('throw new Error("Synthetic clipboard rejection")' if method=='reject' else 'window.syntheticCopied=value')+';}}'
    page = open_reader(page_for,reader_payload,init_script='Object.defineProperty(navigator,"clipboard",{value:'+clipboard+',configurable:true});')
    page.get_by_role('button',name=button,exact=True).click()
    if method=='success':
        assert page.evaluate('window.syntheticCopied') == value
        expect(page.locator('[data-copy-fallback]')).to_have_count(0)
    else:
        field = page.locator('[data-copy-fallback] input')
        expect(field).to_have_value(value)
        expect(field).to_have_attribute('readonly','')
        expect(field).to_be_focused()
        assert field.evaluate('(n)=>[n.selectionStart,n.selectionEnd]') == [0,len(value)]
        expect(page.locator('[data-copy-fallback]')).to_contain_text('press ⌘C')


@pytest.mark.parametrize('kind',['live','archived','subagent'])
def test_production_link_support_preserves_reader_actions(page_for,colophon,tmp_path,kind):
    _, payload = compile_fixture(colophon,tmp_path/'synthetic-production-links',family=True)
    row = payload['subagents']['synthetic-child'] if kind=='subagent' else payload['sessions'][0]
    if kind=='archived': row['archived']=True
    page = page_for(payload,hash='#v=session&p=all&s='+row['id'],
        init_script='Object.defineProperty(navigator,"clipboard",{value:{writeText:async value=>{window.syntheticCopied=value}},configurable:true});')
    reader = page.locator('[data-reader]')
    codex_link = reader.get_by_role('link',name='Open in Codex')
    if kind=='archived':
        expect(codex_link).to_have_count(0)
    else:
        expect(codex_link).to_have_attribute('href','codex://threads/'+row['id'])
    continuation = reader.get_by_role('button',name='Copy Continue in CLI — continues this session',exact=True)
    if kind=='subagent':
        expect(continuation).to_have_count(0)
    else:
        continuation.click()
        assert page.evaluate('window.syntheticCopied') == 'codex resume '+row['id']
    for button,value in [('Copy session ID',row['id']),('Copy log path',row['log_path'])]:
        reader.get_by_role('button',name=button,exact=True).click()
        assert page.evaluate('window.syntheticCopied') == value


def compile_action_fixture(colophon, root, kind, archived):
    home = CodexHome(root)
    ids = ['synthetic-root'] if kind=='primary' else ['synthetic-root','synthetic-child'] if kind=='linked' else ['synthetic-child']
    records = []
    selected_id = 'synthetic-root' if kind=='primary' else 'synthetic-child'
    for identifier in ids:
        fields = {} if identifier=='synthetic-root' else {'parent_thread_id':'synthetic-root','depth':1}
        path = (home.log(identifier).meta(**fields).task_started().turn_context(model='gpt-5.4')
            .user_item().usage_record(usage={'input_tokens':100,'output_tokens':10})
            .agent_item().task_complete().write())
        records.append(colophon.parse_log_file(path,size=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns,archived=archived and identifier==selected_id))
    metadata = colophon.CodexMetadata()
    corpus = colophon.build_corpus(records,metadata,NOW)
    colophon.link_subagents(corpus,metadata,NOW)
    workspaces = colophon.resolve_workspaces(corpus,[])
    colophon.compose_usage(corpus,colophon.PriorityTurns({},[]))
    report = colophon.price_units(corpus,colophon.PriceHistory([entry('gpt-5.4')],[]),None,costs_available=True)
    payload = colophon.build_payload(corpus,workspaces,report,{'generated_at_ms':NOW,'codex_home':root,
        'logs':len(records),'parsed':len(records),'cached':0,
        'catalog':colophon.CatalogResult('offline',None,None,None,[]),'metadata_errors':[],
        'costs_available':True,'costs_reason':None,'ledger':[],'workspaces_file':[]})
    row = payload['subagents'][selected_id] if kind=='linked' else next(row for row in payload['sessions'] if row['id']==selected_id)
    assert row['archived'] is archived
    assert row.get('kind') == {'primary':'session','linked':None,'orphan':'orphan'}[kind]
    return payload,row


@pytest.mark.parametrize('archived',[False,True],ids=['live','archived'])
@pytest.mark.parametrize('kind',['primary','linked','orphan'])
def test_production_actions_apply_archive_and_agent_restrictions(page_for,colophon,tmp_path,kind,archived):
    payload,row = compile_action_fixture(colophon,tmp_path/'synthetic-action-source',kind,archived)
    page = page_for(payload,hash='#v=session&p=all&s='+row['id'],
        init_script='Object.defineProperty(navigator,"clipboard",{value:{writeText:async value=>{window.syntheticCopied=value}},configurable:true});')
    reader = page.locator('[data-reader]')
    codex_link = reader.get_by_role('link',name='Open in Codex')
    if archived:
        expect(codex_link).to_have_count(0)
    else:
        expect(codex_link).to_have_attribute('href','codex://threads/'+row['id'])
    continuation = reader.get_by_role('button',name='Copy Continue in CLI — continues this session',exact=True)
    if kind!='primary':
        expect(continuation).to_have_count(0)
    else:
        continuation.click()
        assert page.evaluate('window.syntheticCopied') == 'codex resume '+row['id']
    for button,value in [('Copy session ID',row['id']),('Copy log path',row['log_path'])]:
        reader.get_by_role('button',name=button,exact=True).click()
        assert page.evaluate('window.syntheticCopied') == value


@pytest.mark.parametrize('action,constant,role,label',[
    ('open_in_codex','OPEN_IN_CODEX_SUPPORT','link','Open in Codex'),
    ('continue_in_cli','CONTINUE_IN_CLI_SUPPORT','button','Copy Continue in CLI — continues this session')])
@pytest.mark.parametrize('disabled',['lifecycle','subagent'])
@pytest.mark.parametrize('archived',[False,True],ids=['live','archived'])
@pytest.mark.parametrize('kind',['linked','orphan'])
def test_each_applicable_support_flag_can_hide_agent_action(page_for,colophon,tmp_path,monkeypatch,kind,archived,disabled,action,constant,role,label):
    support = dict(live=True,archived=True,subagent=True)
    support['subagent' if disabled=='subagent' else 'archived' if archived else 'live'] = False
    monkeypatch.setattr(colophon,constant,support)
    payload,row = compile_action_fixture(colophon,tmp_path/'synthetic-conflicting-support',kind,archived)
    assert payload['meta']['links'][action] == support
    page = page_for(payload,hash='#v=session&p=all&s='+row['id'])
    expect(page.locator('[data-reader]').get_by_role(role,name=label,exact=True)).to_have_count(0)


@pytest.mark.parametrize('kind',['live','archived','subagent'])
def test_link_support_constants_control_buttons_in_process(page_for,colophon,tmp_path,monkeypatch,kind):
    monkeypatch.setattr(colophon,'OPEN_IN_CODEX_SUPPORT',dict(live=True,archived=True,subagent=True,**{}))
    monkeypatch.setattr(colophon,'CONTINUE_IN_CLI_SUPPORT',dict(live=True,archived=True,subagent=True,**{}))
    _, p = compile_fixture(colophon,tmp_path/'synthetic-links',family=True)
    row = p['subagents']['synthetic-child'] if kind=='subagent' else p['sessions'][0]
    if kind=='archived': row['archived']=True
    page = page_for(p,hash='#v=session&p=all&s='+row['id'])
    expect(page.get_by_role('link',name='Open in Codex')).to_have_attribute('href','codex://threads/'+row['id'])
    colophon.OPEN_IN_CODEX_SUPPORT[kind]=False
    colophon.CONTINUE_IN_CLI_SUPPORT[kind]=False
    _, p = compile_fixture(colophon,tmp_path/'synthetic-links-disabled',family=True)
    row = p['subagents']['synthetic-child'] if kind=='subagent' else p['sessions'][0]
    if kind=='archived': row['archived']=True
    page = page_for(p,hash='#v=session&p=all&s='+row['id'])
    expect(page.get_by_role('link',name='Open in Codex')).to_have_count(0)
    expect(page.get_by_role('button',name='Copy Continue in CLI — continues this session')).to_have_count(0)


def test_history_unresolved_retains_header_links_tokens_withholds_turn_metrics(page_for,reader_payload):
    row = reader_payload['sessions'][0]
    row['flags']=['history_unresolved']
    row['turns']=[]
    row.update(start_ms=None,end_ms=None)
    page = open_reader(page_for,reader_payload)
    expect(page.locator('[data-reader]')).to_contain_text('history boundary unresolved — turn metrics withheld')
    expect(page.locator('[data-reader-stat="tokens"]')).to_contain_text('333')
    expect(page.locator('[data-reader-stat="turns"]')).to_contain_text('withheld')
    expect(page.get_by_role('link',name='Open in Codex')).to_have_attribute('href','codex://threads/'+ROOT)


def test_reader_archive_toggle_applies_to_descendant_totals(page_for,reader_payload):
    reader_payload['subagents']['synthetic-child']['archived']=True
    page = open_reader(page_for,reader_payload)
    page.get_by_role('button',name='archived: shown').click()
    expect(page.locator('[data-reader-stat="tokens"]')).to_contain_text('110')
    expect(page.locator('[data-reader-stat="subagents"]')).to_contain_text('0')
