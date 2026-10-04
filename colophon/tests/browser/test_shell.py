"""Task 19 shell behavior, URL history and viewer-local calendar arithmetic."""
import copy
import json
import re
from urllib.parse import quote

import pytest
from playwright.sync_api import expect

from fixturegen import CodexHome

NOW = 1_894_708_800_000


def logs(root):
    for identifier, title, request, archived in [
        ('synthetic-live', 'Synthetic title alpha', 'Synthetic needle request', False),
        ('synthetic-archived', 'Synthetic title beta', 'Synthetic other request', True),
    ]:
        CodexHome(root).log(identifier, archived=archived, day='2030-01-15').meta(title=title, at=NOW-3_600_000).task_started().user_item(request).task_complete().write(mtime=(NOW-1000)/1000)


def test_empty_topbar_font_and_offline(page_for, shell_payload):
    page = page_for(shell_payload)
    expect(page.get_by_text('No Codex sessions found in ' + shell_payload['meta']['codex_home'], exact=True)).to_be_visible()
    expect(page.get_by_text('COLOPHON', exact=True)).to_be_visible()
    expect(page.locator('#snapshot-meta')).to_contain_text('data as of')
    expect(page.locator('#snapshot-meta')).to_contain_text('0 logs')
    expect(page.locator('#snapshot-meta')).to_contain_text('prices unavailable')
    assert page.evaluate("getComputedStyle(document.body).fontFamily").startswith('"Martian Mono"')
    assert page.evaluate("document.fonts.ready.then(() => document.fonts.check(\"12px 'Martian Mono'\"))")
    expect(page.locator('footer')).to_contain_text('API-equivalent estimate (not billed)')


def test_catalog_metadata_is_viewer_local(page_for, shell_payload):
    shell_payload['meta']['catalog'].update(status='cached', source_host='prices.example.invalid', fetched_at_ms=NOW)
    shell_payload['meta']['counts']['logs'] = 7
    page = page_for(shell_payload, tz='Asia/Kolkata')
    expect(page.locator('#snapshot-meta')).to_contain_text('7 logs · prices prices.example.invalid')
    expect(page.locator('#snapshot-meta')).to_contain_text('17:30')


def test_period_navigation_back_reload_and_custom(page_for, shell_payload):
    page = page_for(shell_payload)
    expect(page).to_have_url(re.compile(r'#v=overview&p=90d&a=1&sort=newest$'))
    for period in ('7D', '30D'):
        page.get_by_role('button', name=period, exact=True).click()
        assert 'p=' + period.lower() in page.url
    page.go_back()
    assert 'p=7d' in page.url
    expect(page.get_by_role('button', name='7D', exact=True)).to_have_attribute('aria-pressed', 'true')
    page.reload()
    assert 'p=7d' in page.url
    for period in ('90D', 'MTD', 'ALL'):
        page.get_by_role('button', name=period, exact=True).click()
        assert 'p=' + period.lower() in page.url
    page.get_by_role('button', name='CUSTOM', exact=True).click()
    page.get_by_label('From date').fill('2030-01-02')
    page.get_by_label('To date').fill('2030-01-04')
    assert 'from=2030-01-02' in page.url and 'to=2030-01-04' in page.url


def test_search_and_archive_apply_in_every_shell_view(page_for, codex_home):
    logs(codex_home)
    page = page_for(codex_home)
    assert page.evaluate('''() => {const d=JSON.parse(document.getElementById('colophon-data').textContent); return d.sessions.every(s=>s.start_ms<=d.meta.generated_at_ms && s.end_ms<=d.meta.generated_at_ms);}''')
    expect(page.locator('[data-session-id]')).to_have_count(2)
    history = page.evaluate('history.length')
    page.get_by_role('searchbox').fill('NEEDLE')
    expect(page.locator('[data-session-id]')).to_have_count(1)
    assert page.evaluate('history.length') == history
    assert 'q=NEEDLE' in page.url
    page.get_by_role('searchbox').fill('')
    expect(page.locator('[data-session-id]')).to_have_count(2)
    page.get_by_role('button', name='archived: shown').click()
    expect(page.locator('[data-session-id]')).to_have_count(1)
    for view in ('list', 'session'):
        page.evaluate('(v) => {location.hash = location.hash.replace("v=overview", "v=" + v).replace("v=list", "v=" + v);}', view)
        expect(page.locator('[data-session-id]')).to_have_count(1)


def test_search_title_session_voice_and_descendant_requests(page_for, codex_home):
    CodexHome(codex_home).log('synthetic-root', day='2030-01-15').meta(title='Synthetic full title needle', at=NOW-1000).task_started().user_item().task_complete().write(mtime=NOW/1000)
    source = page_for(codex_home)
    shell_payload = json.loads(source.locator('#colophon-data').text_content())
    root = shell_payload['sessions'][0]
    child = copy.deepcopy(root)
    child.pop('kind')
    child.update(id='synthetic-child', title='Synthetic child', title_full='Synthetic child',
        parent_id=root['id'], depth=1, agent_path='/synthetic/child', label='Synthetic child',
        nickname=None, forked=False, spawn_turn=None, interaction_turns=[], link_method=None)
    child['turns'][0]['requests'][0]['text'] = 'Synthetic child-only query'
    spoken = dict(root['turns'][0]['requests'][0], text='Synthetic spoken request', kind='voice')
    root['children'] = [child['id']]
    root['session_voice']['requests'] = [spoken]
    shell_payload.update(sessions=[root], subagents={'synthetic-child': child})
    page = page_for(shell_payload)
    for query in ('FULL TITLE NEEDLE', 'child-only', 'spoken'):
        page.get_by_role('searchbox').fill(query)
        expect(page.locator('[data-session-id]')).to_have_count(1)
        expect(page).to_have_url(re.compile('q=' + quote(query, safe='') + r'(?:&|$)'))
    page.get_by_role('searchbox').fill('unmatched synthetic text')
    expect(page.locator('[data-session-id]')).to_have_count(0)
    shell_payload['subagents']['synthetic-child']['archived'] = True
    page = page_for(shell_payload)
    page.get_by_role('button', name='archived: shown').click()
    page.get_by_role('searchbox').fill('child-only')
    expect(page.locator('[data-session-id]')).to_have_count(0)


def test_diagnostics_from_malformed_unknown_log(page_for, codex_home):
    CodexHome(codex_home).log('synthetic-damaged', day='2030-01-15').meta(at=NOW-1000).task_started().raw(b'Synthetic malformed line\n').raw(b'{"type":"synthetic_future_record"}\n').task_complete().write(mtime=NOW/1000)
    page = page_for(codex_home)
    expect(page.locator('details[data-diagnostic="malformed_lines"]')).to_be_visible()
    row = page.locator('details[data-diagnostic="unknown_record_types"]')
    row.locator('summary').click()
    expect(row).to_contain_text('synthetic_future_record')
    expect(row).to_contain_text("Codex's log format may have changed")


def test_every_nonzero_diagnostic_has_collapsible_details(page_for, shell_payload):
    diagnostics = shell_payload['diagnostics']
    for key, value in list(diagnostics.items()):
        if key == 'page_size_bytes':
            continue
        if isinstance(value, list):
            diagnostics[key] = [dict(model='gpt-synthetic', tokens=123)] if key == 'untimed_usage' else ['Synthetic diagnostic']
        elif isinstance(value, dict):
            diagnostics[key] = dict(total=1, files=[dict(path='/synthetic/log.jsonl', count=1)]) if 'total' in value else {'synthetic_record': 1}
        elif isinstance(value, bool):
            diagnostics[key] = True
        else:
            diagnostics[key] = 1
    page = page_for(shell_payload)
    assert set(page.locator('details[data-diagnostic]').evaluate_all('(rows) => rows.map(r => r.dataset.diagnostic)')) == set(diagnostics) - {'page_size_bytes'}
    row = page.locator('details[data-diagnostic="untimed_usage"]')
    row.locator('summary').click()
    expect(row).to_contain_text('priced at current rates: usage has no timestamp')
    expect(row).to_contain_text('gpt-synthetic')
    expect(row).to_contain_text('123')


def test_url_normalization_encoding_and_removable_filters(page_for, shell_payload):
    page = page_for(shell_payload, hash='#v=bogus&p=nope&a=bad&from=2030-02-31&how=7-24&day=2030-99-01&st=bad&sort=bad&junk=x&q=%E0%A4%A&ws=synthetic%26key&model=gpt-synthetic')
    assert 'junk=' not in page.url and 'bogus' not in page.url and '2030-02-31' not in page.url
    assert 'how=' not in page.url and 'st=' not in page.url and 'day=' not in page.url and 'q=' not in page.url
    assert 'ws=synthetic%26key' in page.url
    page.get_by_role('button', name='Remove workspace filter').click()
    assert 'ws=' not in page.url
    page.get_by_role('button', name='Remove model filter').click()
    assert 'model=' not in page.url


@pytest.mark.parametrize('tz', ['America/New_York', 'Asia/Kolkata'])
def test_time_local_midnight_split_days_and_hours(page_for, shell_payload, tz):
    page = page_for(shell_payload, tz=tz)
    result = page.evaluate('''() => {
      const t = window.__colophonTest.time;
      const start = +new Date(2030, 0, 14, 23, 30), end = +new Date(2030, 0, 15, 0, 30);
      return [t.localDayKey(start), t.localDayKey(end), t.splitByLocalDay(start, end),
        t.mondayIndex(start), t.localHour(end), [0,1,2,3].map(n => t.localHour(+new Date(2030,0,15,9,0) + n*900000))];
    }''')
    assert result == ['2030-01-14', '2030-01-15', [{'day':'2030-01-14','ms':1_800_000}, {'day':'2030-01-15','ms':1_800_000}], 0, 0, [9,9,9,9]]


def test_dst_days_and_period_windows(page_for, shell_payload):
    page = page_for(shell_payload, tz='America/New_York')
    result = page.evaluate('''() => {
      const t = window.__colophonTest.time;
      const spring = +new Date(2030,2,10), fall = +new Date(2030,10,3), now = +new Date(2030,2,15,12);
      const w=t.periodWindow('7d', now);
      const m=t.periodWindow('mtd', now), prev=t.previousWindow('mtd',m,now);
      return [t.addLocalDays(spring,1)-spring, t.addLocalDays(fall,1)-fall,
        t.localDayKey(w.from), w.to===now+1, t.previousWindow('7d',w,now).to===w.from,
        t.previousWindow('7d',w,now).from===w.from-(w.to-w.from),
        t.localDayKey(prev.from),prev.to-prev.from===m.to-m.from,
        t.periodWindow('custom',now,{from:'2030-03-10',to:'2030-03-10'}).to-spring,
        t.previousWindow('all',w,now), t.previousWindow('custom',w,now)];
    }''')
    assert result == [23*3_600_000,25*3_600_000,'2030-03-09',True,True,True,'2030-02-01',True,23*3_600_000,None,None]


def test_time_unknown_invalid_intervals_and_custom_are_not_epoch(page_for, shell_payload):
    page = page_for(shell_payload)
    assert page.evaluate('''() => {const t=window.__colophonTest.time;return [t.localDayKey(null),t.localHour(null),t.splitByLocalDay(null,100),t.splitByLocalDay(100,0),t.periodWindow('custom',100,{from:'bad',to:'bad'})];}''') == [None,None,[],[],None]


def test_state_roundtrip_preserves_full_encoded_navigation(page_for, shell_payload):
    fragment = '#v=session&p=custom&from=2030-01-01&to=2030-01-15&a=0&q=Synthetic%20%26%20%2B&day=2030-01-03&how=0-23&ws=synthetic%26key&sub=%2Fsynthetic%2Fsub&model=gpt-synthetic&st=aborted&sort=cost&s=synthetic-id'
    page = page_for(shell_payload, hash=fragment)
    page.get_by_role('button', name='30D', exact=True).click()
    assert page.url.endswith(fragment.replace('p=custom', 'p=30d'))
    page.go_back()
    expect(page).to_have_url(re.compile(re.escape(fragment) + '$'))
    page.reload()
    expect(page.get_by_role('searchbox')).to_have_value('Synthetic & +')
    expect(page.get_by_role('button', name='archived: hidden')).to_be_visible()
    expect(page.get_by_label('From date')).to_have_value('2030-01-01')


def test_mtd_previous_window_clips_and_crosses_year_boundary(page_for, shell_payload):
    page = page_for(shell_payload)
    result = page.evaluate('''() => {
      const t=window.__colophonTest.time;
      return [[2030,0,15], [2030,2,31]].map(([y,m,d])=>{
        const now=+new Date(y,m,d,12), w=t.periodWindow('mtd',now), prev=t.previousWindow('mtd',w,now);
        return [t.localDayKey(prev.from), t.localDayKey(prev.to), prev.to===w.from];
      });
    }''')
    assert result == [['2029-12-01','2029-12-15',False], ['2030-02-01','2030-03-01',True]]


def test_debounce_preserves_focus_and_pending_typing_on_navigation(page_for, shell_payload):
    page = page_for(shell_payload)
    search = page.get_by_role('searchbox')
    search.fill('Synthetic first')
    expect(page).to_have_url(re.compile('q=Synthetic%20first'))
    expect(search).to_be_focused()
    search.fill('Synthetic second')
    page.get_by_role('button', name='7D', exact=True).click()
    assert 'q=Synthetic%20second' in page.url
    page.go_back()
    expect(search).to_have_value('Synthetic first')


def test_conflicting_duplicate_state_is_unknown_and_bad_unicode_is_removed(page_for, shell_payload):
    page = page_for(shell_payload, hash='#p=30d&p=7d&q=%ED%A0%80&from=2030-01-15&to=2030-01-01&ws=synthetic%00key')
    assert 'p=90d' in page.url
    assert 'q=' not in page.url and 'ws=' not in page.url
    assert 'from=' not in page.url and 'to=' not in page.url


def test_conflicting_filters_drop_but_identical_and_malformed_repeats_do_not(page_for, shell_payload):
    page = page_for(shell_payload, hash='#q=Synthetic&%71=conflicting&ws=synthetic-one&ws=synthetic-two&day=2030-01-01&day=2030-01-02&model=gpt-synthetic&model=gpt-synthetic&sub=%2Fsynthetic&sub=%E0%A4%A')
    assert all(key+'=' not in page.url for key in ('q','ws','day'))
    assert 'model=gpt-synthetic' in page.url and 'sub=%2Fsynthetic' in page.url


def test_search_waits_two_hundred_ms_and_replaces_history(page_for, shell_payload):
    page = page_for(shell_payload)
    page.clock.install()
    count = page.evaluate('history.length')
    page.get_by_role('searchbox').fill('Synthetic clock test')
    page.clock.run_for(199)
    assert 'q=' not in page.url
    page.clock.run_for(1)
    assert 'q=Synthetic%20clock%20test' in page.url
    assert page.evaluate('history.length') == count


@pytest.mark.parametrize('width', [390, 1440])
def test_shell_wraps_without_horizontal_page_overflow(page_for, shell_payload, width):
    page = page_for(shell_payload, width=width, hash='#v=list&ws=' + 'synthetic-long-key-'*30)
    page.get_by_role('button', name='CUSTOM', exact=True).click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
