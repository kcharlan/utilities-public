"""Measured line fragments, full synthetic stress, and safe keyboard access."""
import copy
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from tests.browser.test_list_reader import reader_payload, ROOT, NOW, MINUTE

WIDTHS = (360, 390, 899, 901, 1024, 1440)

# Do not substitute element boxes for line fragments or exempt view components.
LAYOUT_CHECK = r"""() => {
  const errors = [], fragments = [];
  const describe = n => n.tagName.toLowerCase() + (n.className ? '.' + String(n.className).replace(/\s+/g, '.') : '') + ': ' + n.textContent.trim().slice(0, 70);
  if (document.scrollingElement.scrollWidth > innerWidth + 1) errors.push('page overflow: ' + document.scrollingElement.scrollWidth + ' > ' + innerWidth);
  for (const n of document.querySelectorAll('*')) {
    const style = getComputedStyle(n);
    if (!n.getClientRects().length || style.visibility === 'hidden') continue;
    if (n.hasAttribute('data-scroll-region')) {
      if (!['auto', 'scroll'].includes(style.overflowX)) errors.push('scroll region not scrollable: ' + describe(n));
      if (n.scrollWidth > n.clientWidth + 1 && Math.abs(n.scrollLeft - (n.scrollWidth - n.clientWidth)) > 1) errors.push('scroll region not at far right: ' + describe(n));
    }
    if (!n.closest('[data-scroll-region]') && ['auto', 'scroll'].includes(style.overflowX)) errors.push('unmarked scroll: ' + describe(n));
    if (!n.closest('[data-scroll-region]') && n.scrollWidth > n.clientWidth + 1) {
      if (style.overflowX === 'visible') {if (n.clientWidth > 0) errors.push('visible overflow: ' + describe(n));}
      else if (style.textOverflow !== 'ellipsis' || !n.getAttribute('title')?.trim()) errors.push('clipped without ellipsis/title: ' + describe(n));
    }
    for (const node of n.childNodes) {
      if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) continue;
      const range = document.createRange(); range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        let clipped = {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom};
        // These are the direct text node's clipping ancestors, including n.
        for (let ancestor = n; ancestor; ancestor = ancestor.parentElement) {
          const css = getComputedStyle(ancestor), bounds = ancestor.getBoundingClientRect();
          if (css.overflowX !== 'visible') {clipped.left = Math.max(clipped.left, bounds.left); clipped.right = Math.min(clipped.right, bounds.right);}
          if (css.overflowY !== 'visible') {clipped.top = Math.max(clipped.top, bounds.top); clipped.bottom = Math.min(clipped.bottom, bounds.bottom);}
        }
        if (clipped.right > clipped.left && clipped.bottom > clipped.top) fragments.push({n, ...clipped});
      }
    }
  }
  // Vertical sweep preserves the prescribed all-pairs result for long readers.
  fragments.sort((a,b) => a.top-b.top);
  for (let i = 0; i < fragments.length; i++) for (let j = i+1; j < fragments.length && fragments[j].top < fragments[i].bottom-1; j++) {
    const a = fragments[i], b = fragments[j];
    if (a.n === b.n || a.n.contains(b.n) || b.n.contains(a.n)) continue;
    if (Math.min(a.right,b.right)-Math.max(a.left,b.left) > 1 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top) > 1)
      errors.push('overlap: ' + describe(a.n) + ' <> ' + describe(b.n));
  }
  return errors;
}"""


@pytest.fixture
def stress_payload(reader_payload):
    p = copy.deepcopy(reader_payload)
    root = p['sessions'][0]
    title = 'Synthetic' + 'T'*391
    name = 'Synthetic' + 'W'*191
    folder = 'Synthetic' + 'F'*191
    root.update(title=title, title_full=title, subfolder=folder, branch='Synthetic'+'B'*191,
        flags=['live', 'aborted', 'interrupted', 'abandoned', 'uncertain_timing'], archived=True)
    p['workspaces'][root['workspace']]['name'] = name
    models = ['gpt-synthetic-model-'+str(n).zfill(2) for n in range(40)]
    pricing = copy.deepcopy(next(iter(p['models'].values())))
    p['models'] = {model: copy.deepcopy(pricing) for model in models}
    turn = root['turns'][0]
    turn['tools']['mcp'] = {'synthetic-server-'+ 'M'*200: 999999999999}
    for request in turn['requests']:
        request['text'] = 'Synthetic'+'R'*400+'\n'+'\n'.join('Synthetic request line '+str(n) for n in range(12))
    turn['final_answer']['text'] = 'Synthetic'+'A'*400+'\n'+'\n'.join('Synthetic answer line '+str(n) for n in range(12))
    turn['usage'].update(input=999999999999, cached_input=100000000000, cache_write=0, output=100000000000, reasoning=0, cost_usd=1234567890)
    turn['usage']['priced_by'] = [[model,0,'rates'] for model in models]
    root['own_usage'] = copy.deepcopy(turn['usage'])
    root['outside_usage'] = {**{k: 0 for k in ('input','cached_input','cache_write','output','reasoning','cost_usd','unpriced_tokens')}, 'priced_by': []}
    root['buckets'] = [[(NOW-10*MINUTE)//900000, model, 'standard', 999999999999//40 + (n < 39), 100000000000//40, 0, 100000000000//40, 0, 1234567890/40] for n, model in enumerate(models)]
    template = copy.deepcopy(p['subagents']['synthetic-child'])
    children = {}
    for n in range(300):
        child = copy.deepcopy(template)
        identifier = 'synthetic-colliding-child-'+str(n).zfill(3)
        child.update(id=identifier, parent_id=ROOT, depth=1, children=[],
            label='Synthetic colliding child '+str(n), nickname='Agent-Synthetic',
            forked=n%2 == 0, start_ms=NOW-9*MINUTE, end_ms=NOW-3*MINUTE)
        child['turns'][0].update(id=identifier+'-turn', spawned=[], used=[])
        for bucket in child['buckets']: bucket[1] = models[n%40]
        child['own_usage']['priced_by'] = [[models[n%40],0,'rates']]
        child['turns'][0]['usage']['priced_by'] = [[models[n%40],0,'rates']]
        children[identifier] = child
    root['children'] = list(children)
    turn.update(spawned=list(children), used=[])
    p['subagents'] = children
    old = copy.deepcopy(root)
    old.update(id='synthetic-ten-years-old', title='Synthetic old history', title_full='Synthetic old history',
        children=[], flags=[], archived=False, start_ms=1_579_089_600_000, end_ms=1_579_089_660_000)
    old['turns'][0].update(start_ms=old['start_ms'], end_ms=old['end_ms'], duration_ms=MINUTE, spawned=[], used=[])
    for b in old['buckets']: b[0] = old['start_ms']//900000
    p['sessions'].append(old)
    p['meta']['counts'].update(sessions=2, subagents=300)
    return p


def ready(page):
    page.evaluate('() => document.fonts.ready')
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def test_stress_fixture_has_exact_shape_and_conserved_usage(stress_payload):
    root = stress_payload['sessions'][0]
    assert len(root['title']) == len(root['title_full']) == 400
    assert len(stress_payload['workspaces'][root['workspace']]['name']) == len(root['subfolder']) == 200
    assert len(root['children']) == len(stress_payload['subagents']) == 300
    assert len(stress_payload['models']) == 40
    assert str(root['own_usage']['input']) == '999999999999'
    assert NOW-stress_payload['sessions'][1]['start_ms'] >= 3650*86400000
    for row in stress_payload['sessions']+list(stress_payload['subagents'].values()):
        for field, index in (('input',3),('cached_input',4),('cache_write',5),('output',6),('reasoning',7)):
            assert row['own_usage'][field] == sum(b[index] for b in row['buckets'])
            assert row['own_usage'][field] == row['outside_usage'][field]+sum(t['usage'][field] for t in row['turns'])


def test_fragment_checker_uses_per_line_rects_clipping_and_one_pixel_tolerance(page_for, reader_payload):
    page = page_for(reader_payload)
    css = '<style>body{margin:0;font:10px/12px monospace}div{position:absolute;overflow:visible}</style>'
    # The union box overlaps the second column, but the short second line does not.
    page.set_content(css+'<div style="width:61px">abcdefghij xy</div><div style="left:30px;top:12px">next</div>')
    assert page.evaluate(LAYOUT_CHECK) == []
    # Direct text is clipped by its own box and by a separate clipping ancestor.
    page.set_content(css+'<div title="synthetic clip" style="width:20px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><span>abcdefghij</span></div><div style="left:30px">next</div>')
    assert page.evaluate(LAYOUT_CHECK) == []
    page.locator('div').first.evaluate('(n)=>n.removeAttribute("title")')
    assert any('clipped without ellipsis/title' in error for error in page.evaluate(LAYOUT_CHECK))
    page.set_content(css+'<div id="a">synthetic</div><div id="b">synthetic</div>')
    page.evaluate('''() => {const range=document.createRange();range.selectNodeContents(document.querySelector('#a'));document.querySelector('#b').style.left=(range.getClientRects()[0].right-.75)+'px';}''')
    assert page.evaluate(LAYOUT_CHECK) == []
    page.locator('#b').evaluate('(n)=>n.style.left=(parseFloat(n.style.left)-1)+"px"')
    assert any('overlap:' in error for error in page.evaluate(LAYOUT_CHECK))
    page.set_content(css+'<div style="width:20px;overflow-x:auto;white-space:nowrap">synthetic-long-text</div>')
    assert any('unmarked scroll:' in error for error in page.evaluate(LAYOUT_CHECK))
    page.locator('div').evaluate('(n)=>n.setAttribute("data-scroll-region","calendar")')
    assert any('scroll region not at far right:' in error for error in page.evaluate(LAYOUT_CHECK))
    page.locator('div').evaluate('(n)=>n.scrollLeft=n.scrollWidth')
    assert page.evaluate(LAYOUT_CHECK) == []


@pytest.mark.parametrize('markup,wanted', [
    ('<div style="height:0">Synthetic text</div><div>Synthetic neighbor</div>', 'overlap:'),
    ('<div style="width:0;overflow:hidden;white-space:nowrap">Synthetic clipped text</div>', 'clipped without ellipsis/title:')], ids=('zero-height-visible','zero-width-clipped'))
def test_checker_includes_painted_or_clipped_text_in_zero_dimension_boxes(page_for, reader_payload, markup, wanted):
    page = page_for(reader_payload)
    page.set_content('<style>body{margin:0;font:10px/12px monospace}div{position:absolute}</style>'+markup)
    assert any(wanted in error for error in page.evaluate(LAYOUT_CHECK)), wanted


@pytest.mark.parametrize('width', WIDTHS)
@pytest.mark.parametrize('view', ('overview', 'list', 'session'))
def test_stress_has_no_overflow_or_fragment_overlap(page_for, stress_payload, width, view):
    hash = '#v='+view+'&p=all'+('&s='+ROOT if view == 'session' else '')
    page = page_for(stress_payload, width=width, hash=hash)
    ready(page)
    if view == 'overview':
        expect(page.locator('[data-model]')).to_have_count(40)
        expect(page.locator('[data-scroll-region]')).to_have_count(1)
        expect(page.locator('[data-scroll-region]')).to_have_attribute('data-scroll-region', 'calendar')
        assert page.locator('[data-day]').count() >= 3650
    if view == 'session':
        expect(page.locator('[data-timeline-lane]')).to_have_count(301)
        assert page.locator('[data-tooltip-only]').count() > 290
    errors = page.evaluate(LAYOUT_CHECK)
    assert errors == [], '\n'.join(errors)
    page.screenshot(path=f'/tmp/colophon-task22-{view}-{width}-viewport.png')
    if view == 'session':
        page.get_by_role('button', name='Expand full title', exact=True).click()
        page.locator('.followup-toggle').click()
        page.locator('.subagent-toggle').first.click()
        page.locator('.text-expander:visible').evaluate_all('(buttons)=>buttons.forEach(button=>button.click())')
        ready(page)
        errors = page.evaluate(LAYOUT_CHECK)
        assert errors == [], '\n'.join(errors)
    page.screenshot(path=f'/tmp/colophon-task22-{view}-{width}.png', full_page=True)


def tab_to(page, target, limit=1000):
    for _ in range(limit):
        page.keyboard.press('Tab')
        if target.evaluate('(n)=>n === document.activeElement'):
            assert target.evaluate('(n)=>n.matches(":focus-visible") && getComputedStyle(n).outlineStyle !== "none"')
            return
    pytest.fail('Tab did not reach '+target.evaluate('(n)=>n.outerHTML'))


SAFE_ACTIONS = r"""(() => {
  window.syntheticCopies = []; window.syntheticLinks = []; window.syntheticPushes = [];
  const push = history.pushState;
  history.pushState = function(...args) {window.syntheticPushes.push(args[2]); return push.apply(this,args);};
  Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => window.syntheticCopies.push(text)}});
  document.addEventListener('click', event => {
    const a = event.target.closest('a[href^="codex:"]');
    if (a) {event.preventDefault(); window.syntheticLinks.push(a.getAttribute('href'));}
  }, true);
})();"""


@pytest.mark.parametrize('key', ('Enter', 'Space'))
def test_keyboard_overview_controls_tiles_and_every_heat_cell(page_for, reader_payload, key):
    page = page_for(reader_payload, hash='#v=overview&p=7d', init_script=SAFE_ACTIONS)
    ready(page)
    for label in ('7D','30D','90D','MTD','ALL','CUSTOM'):
        button = page.get_by_role('button', name=label, exact=True)
        tab_to(page, button)
        page.keyboard.press(key)
        assert parse_qs(urlsplit(page.url).fragment)['p'] == [label.lower()]
    search = page.get_by_role('searchbox')
    tab_to(page, search)
    page.keyboard.type('Synthetic')
    expect(search).to_have_value('Synthetic')
    toggle = page.get_by_role('button', name='archived: shown')
    tab_to(page, toggle)
    page.keyboard.press(key)
    expect(page.get_by_role('button', name='archived: hidden')).to_be_visible()
    for index in range(7):
        page.goto(page.url.split('#')[0]+'#v=overview&p=7d')
        ready(page)
        tile = page.locator('.kpi-main').nth(index)
        tab_to(page, tile)
        page.keyboard.press(key)
        assert parse_qs(urlsplit(page.url).fragment)['v'] == ['list']
    page.goto(page.url.split('#')[0]+'#v=overview&p=7d')
    ready(page)
    cells = page.locator('button.heat-cell')
    total = cells.count()
    labels = cells.evaluate_all('(cells)=>cells.map(n=>n.getAttribute("aria-label"))')
    assert total == 7+7*24
    assert all(re.search(r'\d', label) and ' · ' in label for label in labels)
    for index in range(total):
        tab_to(page, cells.nth(index))
    # All cells were reached through Tab above. Activate each cell separately,
    # preserving the original date/hour identity across the resulting render.
    targets = cells.evaluate_all('(cells)=>cells.map(n=>n.hasAttribute("data-day") ? ["day",n.dataset.day] : ["how",n.dataset.how])')
    for field, value in targets:
        page.locator('[data-'+field+'="'+value+'"]').press(key)
        assert parse_qs(urlsplit(page.url).fragment)[field] == [value]
        page.goto(page.url.split('#')[0]+'#v=overview&p=7d')
        ready(page)


@pytest.mark.parametrize('key', ('Enter', 'Space'))
@pytest.mark.parametrize('width', (390,1440))
def test_keyboard_list_reader_buttons_and_expanders(page_for, reader_payload, key, width):
    parent = copy.deepcopy(reader_payload['sessions'][0])
    parent.update(id='synthetic-keyboard-parent', title='Synthetic keyboard parent', title_full='Synthetic keyboard parent', children=[])
    parent['turns'][0].update(spawned=[], used=[])
    reader_payload['sessions'][0]['forked_from'] = parent['id']
    reader_payload['sessions'].append(parent)
    page = page_for(reader_payload, width=width, hash='#v=list&p=all', init_script=SAFE_ACTIONS)
    for candidate in page.locator('[data-list-row]').all():
        identifier = candidate.get_attribute('data-session-id')
        tab_to(page, candidate)
        before = page.evaluate('window.syntheticPushes.length')
        page.keyboard.press(key)
        expect(page.locator('[data-reader]')).to_have_attribute('data-reader', identifier)
        assert page.evaluate('window.syntheticPushes.length') == before+1
        page.go_back()
        ready(page)
    row = page.locator('[data-list-row][data-session-id="'+ROOT+'"]')
    tab_to(page, row)
    page.keyboard.press(key)
    expect(page.locator('[data-reader]')).to_be_visible()
    title = page.get_by_role('button', name='Expand full title', exact=True)
    tab_to(page, title)
    page.keyboard.press(key)
    expect(title).to_have_attribute('aria-expanded','true')
    link = page.get_by_role('link', name='Open in Codex')
    tab_to(page, link)
    page.keyboard.press(key)
    assert page.evaluate('window.syntheticLinks') == ['codex://threads/'+ROOT]
    for label, copied in (('Copy Continue in CLI — continues this session','codex resume '+ROOT), ('Copy session ID',ROOT), ('Copy log path','/synthetic/root.jsonl')):
        button = page.get_by_role('button', name=label, exact=True)
        tab_to(page, button)
        page.keyboard.press(key)
        assert page.evaluate('window.syntheticCopies.at(-1)') == copied
    followup = page.locator('.followup-toggle')
    tab_to(page, followup)
    page.keyboard.press(key)
    expect(followup).to_have_attribute('aria-expanded','true')
    for child in page.locator('.subagent-toggle').all():
        tab_to(page, child)
        page.keyboard.press(key)
        expect(child).to_have_attribute('aria-expanded','true')
    for button in page.locator('.text-expander:visible').all():
        tab_to(page, button)
        page.keyboard.press(key)
        expect(button).to_have_attribute('aria-expanded','true')
    fork = page.get_by_role('button', name='forked from Synthetic keyboard parent', exact=True)
    tab_to(page, fork)
    page.keyboard.press(key)
    expect(page.locator('[data-reader]')).to_have_attribute('data-reader','synthetic-keyboard-parent')
    if width < 900:
        back = page.get_by_role('button', name='← sessions', exact=True)
        tab_to(page, back)
        page.keyboard.press(key)
        expect(page.locator('[data-session-list]')).to_be_visible()
