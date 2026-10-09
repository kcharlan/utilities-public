"""Offline UI acceptance using private, synthetic page and download artifacts."""
import csv
import io
import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect, sync_playwright

from taxkit.page import build_payload, render_page
from tests.test_page_build import REPO_ROOT, guard_browser_errors, synthetic_root
from tests.test_rules_v2 import synthetic_rules, write_synthetic
from tests.test_engine_parity import engine_page

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def built_browser(tmp_path, monkeypatch):
    assert not tmp_path.resolve().is_relative_to(REPO_ROOT.resolve())
    tmp_path.chmod(0o700)
    home = tmp_path / 'runtime'
    home.mkdir(mode=0o700)
    config = home / 'config.yaml'
    config.write_text('default_states: [GA]\nqif_overrides: {}\n')
    config.chmod(0o600)
    monkeypatch.setenv('TAX2_HOME', str(home))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        def open_page(payload=None, storage=None, blocked=False, width=1440, height=1000,
                      instant='2026-01-01T02:30:00Z'):
            payload = payload or build_payload(PROJECT / 'rules', rules_source='bundled',
                                              built_at='2025-12-01T00:00:00Z')
            snapshots.append((config.read_bytes(), config.stat().st_mtime_ns))
            path = tmp_path / f'page-{len(list(tmp_path.glob("page-*")))}.html'
            path.write_bytes(render_page(payload))
            path.chmod(0o600)
            context = browser.new_context(viewport={'width': width, 'height': height},
                                          timezone_id='America/New_York', service_workers='block')
            context.set_offline(True)
            requests = []
            context.on('request', lambda request: requests.append(request.url)
                       if not request.url.startswith('file:') else None)
            context.route('**/*', lambda route: route.continue_()
                          if route.request.url.startswith('file:') else route.abort())
            if blocked is True:
                context.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('blocked');}})")
            elif storage:
                context.add_init_script("if(!sessionStorage.getItem('tax2:test-seeded')) {for (const [k,v] of Object.entries(" + json.dumps(storage) + ")) localStorage.setItem(k,v); sessionStorage.setItem('tax2:test-seeded','1');}")
            if blocked == 'write':
                context.add_init_script("Storage.prototype.setItem = function() {throw new Error('blocked write');}")
            elif blocked in ['tax2:theme', 'tax2:selected-states']:
                context.add_init_script("const originalGet = Storage.prototype.getItem; Storage.prototype.getItem = function(key) {if(key === " + json.dumps(blocked) + ") throw new Error('blocked read'); return originalGet.call(this,key);}")
            page = context.new_page()
            page.clock.install(time=instant)
            contexts.append((context, requests))
            guards.append(guard_browser_errors(page))
            guards[-1].__enter__()
            page.goto(path.as_uri())
            expect(page.get_by_role('heading', name='Tax2', exact=True)).to_be_visible()
            return page
        contexts, guards, snapshots = [], [], []
        open_page.config = config
        yield open_page
        for guard in reversed(guards):
            guard.__exit__(None, None, None)
        for context, requests in contexts:
            assert requests == []
            context.close()
        browser.close()
        assert all((config.read_bytes(), config.stat().st_mtime_ns) == snapshot for snapshot in snapshots)


def income(page, text, earned='0'):
    page.get_by_label('Monthly Unearned Income', exact=True).fill(text)
    page.get_by_label('Monthly Earned Income', exact=True).fill(earned)


def download_text(page, label):
    with page.expect_download() as event:
        page.get_by_role('button', name=label).click()
    download = event.value
    return download.suggested_filename, Path(download.path()).read_text()


def test_parsers_exact_money_grammar_and_allocation(engine_page):
    page = engine_page
    valid = {'': 0, '   ': 0, '1,234.56': 123456, '12.': 1200, '.5': 50,
             '0': 0, ' 12 ': 1200, '999999999999.99': 99999999999999,
             '1,234,567,890.01': 123456789001}
    invalid = ['1.234', '-5', '1e5', 'Infinity', 'NaN', '12.3.4', '$12', '12,34',
               '1,2', '1000000000000', '1,234,567,890,123', '+12', '12 .3', '.']
    parsed = page.evaluate("""({valid,invalid}) => ({
        valid:valid.map(s => Tax2Engine.parseMoneyInput(s,42)),
        invalid:invalid.map(s => Tax2Engine.parseMoneyInput(s,42)),
        allocations:['100','-5','150','0','33.3',' 50 ','50','33.33','.5','5.','+7','','x','Infinity','NaN','0x10','0b11','0o7','1e1','5%','1,000'].map(Tax2Engine.parseAllocation)
    })""", {'valid': list(valid), 'invalid': invalid})
    assert parsed['valid'] == [{'cents': value, 'error': None, 'inProgress': False} for value in valid.values()]
    assert parsed['invalid'][:-1] == [{'cents': 42, 'error': 'Enter a dollar amount, up to 2 decimal places', 'inProgress': False}] * (len(invalid)-1)
    assert parsed['invalid'][-1] == {'cents': 42, 'error': None, 'inProgress': True}
    assert parsed['allocations'] == [{'value': n, 'error': None} for n in [100, 0, 100, 0, 33.3, 50, 50, 33.33, .5, 5, 7]] + [{'value': None, 'error': 'Enter 0–100'}] * 10


def test_shared_rate_percent_rounds_up(engine_page):
    assert engine_page.evaluate('Tax2Engine.ratePercent(12341,100000,1)') == 12.4
    assert engine_page.evaluate('Math.round(12341/100000*100*10)/10') == 12.3
    assert engine_page.evaluate('Tax2Engine.ratePercent(12341,100000,2)') == 12.35
    assert engine_page.evaluate('Math.round(12341/100000*100*100)/100') == 12.34
    assert engine_page.evaluate('Tax2Engine.ratePercent(10,0,2)') == 0
    # Percent scaling belongs to the shared engine helper; app.js must not
    # multiply by 100 (or 100.0, or *=) at any spacing. Self-check both ways first.
    multiply_by_100 = re.compile(r'(?<![\w.])100(?:\.0*)?\s*\*(?!\*)|\*=?\s*100(?:\.0*)?(?![\w.])')
    positives = ['x*100', 'x * 100', '100*x', 'x *= 100', 'x*100.0', '100.0 * x', 'x  *\t100;']
    negatives = ["text: '100'", 'value: 100', '?? 100', '!== 100', 'url), 1000)', 'x*1000', '1000*x',
                 'x*100.5', '100 ** 2']
    assert [sample for sample in positives if not multiply_by_100.search(sample)] == []
    assert [sample for sample in negatives if multiply_by_100.search(sample)] == []
    assert multiply_by_100.findall((PROJECT / 'web/app.js').read_text()) == []


def test_allocation_decimal_only_and_keyboard_recovery(built_browser):
    page = built_browser(instant='2026-10-08T12:00:00Z')
    field = page.get_by_label('Georgia allocation', exact=True)
    field.fill('0x10')
    expect(field).to_have_attribute('aria-invalid', 'true')
    described_ids = (field.get_attribute('aria-describedby') or '').split()
    assert described_ids
    described = [page.locator(f'#{error_id}') for error_id in described_ids]
    assert any(message.count() == 1 and message.is_visible() and message.text_content() == 'Enter 0–100'
               for message in described), described_ids
    expect(page.locator('.error-card')).to_be_visible()
    expect(page.locator('.result-card')).to_have_count(0)
    expect(page.get_by_role('button', name='Download QIF')).to_be_disabled()
    expect(page.locator('.income-sublabel')).to_have_text('Total $12,500.00 monthly = $150,000.00 annually')
    for value, key, expected in [('50','ArrowUp','51'),('33.3','ArrowUp','34'),
                                 ('33.3','ArrowDown','33'),('100','ArrowUp','100'),('0','ArrowDown','0')]:
        field.fill(value)
        field.press(key)
        expect(field).to_have_value(expected)
    field.fill('40')
    field.fill('abc')
    field.press('ArrowUp')
    expect(field).to_have_value('41')
    page.get_by_label('Pennsylvania', exact=True).check()
    page.get_by_label('Georgia', exact=True).uncheck()
    page.get_by_label('Georgia', exact=True).check()
    field.fill('abc')
    field.press('ArrowUp')
    expect(field).to_have_value('42')


def test_income_total_error_recovery_and_rate_display(built_browser):
    page = built_browser(instant='2026-10-08T12:00:00Z')
    expect(page.locator('.total .result-sublabel')).to_have_text('21.18% combined')
    income(page, '9000')
    # Federal annual: 1240 + 4560 + 9130 = 14930; monthly rounds to
    # 1244.17. Its 13.824111...% rate rounds up to 13.9, nearest is 13.8.
    expect(page.locator('.federal .result-amount')).to_have_text('$1,244.17')
    expect(page.locator('.federal .result-sublabel')).to_have_text('13.9% effective')
    field = page.get_by_label('Monthly Earned Income', exact=True)
    field.fill('1e5')
    expect(page.locator('.income-sublabel')).to_have_text('Total unavailable — fix the highlighted inputs.')
    field.fill('250')
    expect(page.locator('.income-sublabel')).to_have_text('Total $9,250.00 monthly = $111,000.00 annually')


def open_style_page(built_browser, dark, width=1440, height=1000):
    """Open a page for computed-style checks: transitions off, theme selected."""
    page = built_browser(width=width, height=height, instant='2026-10-08T12:00:00Z')
    page.add_style_tag(content='* {transition: none !important}')
    if dark:
        page.get_by_role('button', name='Toggle Theme').click()
        expect(page.locator('html')).to_have_class('dark')
    return page


def normalized_accent(field, token):
    """Resolve a CSS colour token in the field's own context to its computed form."""
    return field.evaluate('''(e, token) => {const probe = document.createElement('span');
        probe.style.color = `var(${token})`; e.after(probe);
        const colour = getComputedStyle(probe).color; probe.remove(); return colour;}''', token)


@pytest.mark.parametrize('dark', [False, True])
@pytest.mark.parametrize('label,invalid,valid', [('Monthly Earned Income','1e5','0'),
    ('Georgia allocation','0x10','100'),('Transaction Date','','2026-10-08')])
def test_invalid_indicator_and_valid_style_restoration(built_browser, dark, label, invalid, valid):
    page = open_style_page(built_browser, dark)
    field = page.get_by_label(label, exact=True)
    def styles():
        return field.evaluate('''e => { const s=getComputedStyle(e); return [s.borderColor,s.borderWidth,s.outlineColor,s.outlineWidth,s.boxShadow,s.backgroundColor]; }''')
    baseline = {}
    for focused in [True, False]:
        field.focus() if focused else field.blur()
        baseline[focused] = styles()
    field.fill(invalid)
    expect(field).to_have_attribute('aria-invalid', 'true')
    accent = normalized_accent(field, '--accent-tax')
    for focused in [True, False]:
        field.focus() if focused else field.blur()
        assert field.evaluate('''(e, accent) => {const s=getComputedStyle(e);
            return (s.borderTopColor===accent && parseFloat(s.borderTopWidth)>0) ||
                (s.outlineColor===accent && parseFloat(s.outlineWidth)>0 && s.outlineStyle!=='none');
        }''', accent)
    if label != 'Monthly Earned Income':
        error_id = field.get_attribute('aria-describedby')
        assert error_id
        expect(page.locator(f'#{error_id}')).to_be_visible()
    field.fill(valid)
    for focused in [True, False]:
        field.focus() if focused else field.blur()
        assert styles() == baseline[focused]


DESKTOP_COLUMNS = ('.export-panel', '.main-panel', '.sidebar')


def test_title_empty_zero_focus_and_desktop_column_layout(built_browser):
    # Scrolling behaviour is proven with real wheel input in
    # test_desktop_wheel_scroll_never_moves_window; this keeps the layout facts.
    page = built_browser(width=1440, height=600, instant='2026-10-08T12:00:00Z')
    assert page.title() == 'Tax2 - Professional Tax Calculator'
    field = page.get_by_label('Monthly Earned Income', exact=True)
    field.focus()
    expect(field).to_have_value('')
    page.get_by_label('Pennsylvania', exact=True).check()
    metrics = page.evaluate('''columns => ({height:document.querySelector('.app-container').clientHeight,
        overflow:columns.map(s=>getComputedStyle(document.querySelector(s)).overflowY),
        exports:[document.querySelector('.export-panel').scrollHeight,document.querySelector('.export-panel').clientHeight]})''',
        list(DESKTOP_COLUMNS))
    assert metrics['height'] == 600
    assert all(value in ['auto','scroll'] for value in metrics['overflow'])
    assert metrics['exports'][0] > metrics['exports'][1]


def column_scroll_state(page):
    return page.evaluate('''columns => ({windowY: window.scrollY,
        columns: Object.fromEntries(columns.map(s => {const e = document.querySelector(s);
            return [s, {top: e.scrollTop, max: e.scrollHeight - e.clientHeight}];}))})''', list(DESKTOP_COLUMNS))


def test_desktop_wheel_scroll_never_moves_window(built_browser):
    page = built_browser(width=1440, height=600, instant='2026-10-08T12:00:00Z')
    page.get_by_label('Pennsylvania', exact=True).check()
    expect(page.locator('.state .result-label')).to_have_count(2)
    document = page.evaluate('({scroll: document.documentElement.scrollHeight, inner: innerHeight})')
    assert document['scroll'] <= document['inner'] + 1, document
    overflowing = [selector for selector, column in column_scroll_state(page)['columns'].items()
                   if column['max'] > 1]
    assert '.export-panel' in overflowing, column_scroll_state(page)
    for selector in overflowing:
        before = column_scroll_state(page)
        box = page.locator(selector).bounding_box()
        page.mouse.move(box['x'] + box['width'] / 2,
                        min(max(box['y'] + box['height'] / 2, 1), page.viewport_size['height'] - 1))
        for _ in range(20):
            page.mouse.wheel(0, 400)
            assert page.evaluate('window.scrollY') == 0, selector
        # Wheel scrolling is applied asynchronously; wait until the column
        # settles at its end (or the window moves), and fail loudly otherwise.
        try:
            page.wait_for_function('''s => {const e = document.querySelector(s);
                return window.scrollY !== 0 || e.scrollHeight - e.clientHeight - e.scrollTop <= 1;}''',
                arg=selector, timeout=5000)
        except PlaywrightTimeoutError:
            pytest.fail(f'{selector} did not reach its scroll end after wheel input: {column_scroll_state(page)}')
        after = column_scroll_state(page)
        assert after['windowY'] == 0, (selector, after)
        column = after['columns'][selector]
        assert abs(column['top'] - column['max']) <= 1, (selector, after)
        for other in DESKTOP_COLUMNS:
            if other != selector:
                assert after['columns'][other]['top'] == before['columns'][other]['top'], (selector, other, after)


def visible_edge(element, block):
    """Scroll one edge of the element into view; report its box and whether that edge is hit-testable."""
    return element.evaluate('''(e, block) => {e.scrollIntoView({block});
        const r = e.getBoundingClientRect(), y = block === 'start' ? r.top + 4 : r.bottom - 4;
        return {top: r.top, bottom: r.bottom, height: innerHeight,
                hit: e.contains(document.elementFromPoint(r.left + 4, y))};}''', block)


@pytest.mark.parametrize('width,height', [(1440, 600), (1024, 700), (390, 844)])
def test_license_notices_reachable_at_all_widths(built_browser, width, height):
    page = built_browser(width=width, height=height, instant='2026-10-08T12:00:00Z')
    notices = page.locator('details', has=page.locator('summary', has_text='Software licenses'))
    expect(notices).to_have_count(1)
    text = notices.text_content()
    for name in ('preact.LICENSE', 'htm.LICENSE'):
        assert (PROJECT / 'web/vendor' / name).read_text().strip() in text, name
    notices.scroll_into_view_if_needed()
    expect(notices).to_be_in_viewport()
    notices.locator('summary').click()
    expect(notices).to_have_attribute('open', '')
    # The opened text must live in normal scrolling flow: no position: fixed on
    # the <pre> or any ancestor, and no position: sticky on the <pre>..<details>
    # chain. A pinned panel, even one that scrolls internally, overlays the
    # calculator instead of being reachable as part of the page.
    # Both ends must also scroll into view and be hit-testable, so a pinned
    # panel taller than the viewport fails here too.
    text_block = notices.locator('pre')
    pinned = text_block.evaluate('''e => {const found = [], notices = e.closest('details');
        let inNotices = true;
        for (let n = e; n; n = n.parentElement) {const position = getComputedStyle(n).position;
            if (position === 'fixed' || (inNotices && position === 'sticky')) found.push(`${n.tagName}:${position}`);
            if (n === notices) inNotices = false;}
        return found;}''')
    assert pinned == [], pinned
    start = visible_edge(text_block, 'start')
    assert -1 <= start['top'] < start['height'] and start['hit'], start
    end = visible_edge(text_block, 'end')
    assert 0 < end['bottom'] <= end['height'] + 1 and end['hit'], end
    if width == 1440:
        assert page.evaluate('window.scrollY') == 0


def box_shadow_colours(field):
    shadow = field.evaluate('e => getComputedStyle(e).boxShadow')
    return shadow, re.findall(r'rgba?\([^)]*\)', shadow)


def transparent_colour(colour):
    channels = re.findall(r'[\d.]+', colour)
    return len(channels) == 4 and float(channels[3]) == 0


@pytest.mark.parametrize('dark', [False, True])
@pytest.mark.parametrize('width', [1440, 1024, 390])
def test_invalid_focus_has_no_income_glow(built_browser, dark, width):
    page = open_style_page(built_browser, dark, width=width, height=900)
    allocation = page.get_by_label('Georgia allocation', exact=True)
    allocation.focus()
    glow = normalized_accent(allocation, '--accent-income-light')
    shadow, colours = box_shadow_colours(allocation)
    assert glow in colours, (shadow, glow)
    for label, invalid in [('Georgia allocation', '0x10'), ('Transaction Date', '')]:
        field = page.get_by_label(label, exact=True)
        field.fill(invalid)
        expect(field).to_have_attribute('aria-invalid', 'true')
        field.focus()
        allowed = {normalized_accent(field, '--accent-tax'), normalized_accent(field, '--accent-tax-light')}
        shadow, colours = box_shadow_colours(field)
        assert glow not in colours, (label, shadow, glow)
        assert shadow == 'none' or (colours and all(
            colour in allowed or transparent_colour(colour) for colour in colours)), (label, shadow, allowed)


def test_tablet_sidebar_spans_main_and_export(built_browser):
    page = built_browser(width=1024, height=600, instant='2026-10-08T12:00:00Z')
    boxes = page.evaluate("['.sidebar','.export-panel'].map(s=>document.querySelector(s).getBoundingClientRect().bottom)")
    assert boxes[0] >= boxes[1] - 1


def test_defaults_format_reconciliation_and_current_qif(built_browser):
    page = built_browser(instant='2026-10-08T12:00:00Z')
    expect(page.get_by_label('Tax Year', exact=True)).to_have_value('2026')
    assert page.get_by_label('Tax Year', exact=True).locator('option').all_text_contents() == ['2026', '2025']
    field = page.get_by_label('Monthly Unearned Income', exact=True)
    expect(field).to_have_value('12,500.00')
    field.focus()
    expect(field).to_have_value('12500')
    expect(page.get_by_label('Georgia allocation', exact=True)).to_be_visible()
    expect(page.get_by_label('Georgia', exact=True)).to_be_disabled()
    expect(page.locator('.built-at')).to_contain_text('2025-12-01T00:00:00Z')
    income(page, '5000')
    expect(page.locator('.total .result-amount')).to_have_text('$621.94')
    expect(page.locator('.net .result-amount')).to_have_text('$4,378.06')
    expect(page.locator('.federal .result-sublabel')).to_have_text('8.4% effective')
    page.get_by_label('Pennsylvania', exact=True).check()
    expect(page.locator('.net .result-amount')).to_have_text('$4,224.56')
    page.get_by_label('Pennsylvania allocation', exact=True).fill('50')
    expect(page.locator('.total .result-amount')).to_have_text('$698.69')
    income(page, '5000', '250')
    expect(page.locator('.total .result-amount')).to_have_text('$745.26')
    expect(page.locator('.net .result-amount')).to_have_text('$4,504.74')
    expect(page.locator('.income-sublabel')).to_have_text('Total $5,250.00 monthly = $63,000.00 annually')
    for value in ['8000', '3000', '5000']:
        income(page, value, '250')
        expected = page.evaluate("""v => Tax2Engine.computeMonthly({earnedCents:25000,unearnedCents:Number(v)*100,
            filingStatus:'single',year:2026,states:[{code:'GA',allocation_pct:100},{code:'PA',allocation_pct:50}]},
            JSON.parse(document.getElementById('tax2-data').textContent))""", value)
        expect(page.locator('.total .result-amount')).to_have_text(f"${expected['total_monthly_cents']/100:,.2f}")
        _, qif = download_text(page, 'Download QIF')
        assert f"T-{expected['federal_cents']/100:.2f}\n" in qif
        assert f"T-{expected['states'][1]['state_cents']/100:.2f}\n" in qif
    income(page, '.5', '12.')
    field.blur()
    expect(field).to_have_value('0.50')


@pytest.mark.parametrize('invalid', ['100.005', '1e5', '-5', '$12', '12,34', '12.3.4', '1000000000000'])
def test_invalid_text_survives_blur_and_recovers(built_browser, invalid):
    page = built_browser(instant='2026-10-08T12:00:00Z')
    income(page, invalid)
    field = page.get_by_label('Monthly Unearned Income', exact=True)
    field.blur()
    expect(field).to_have_value(invalid)
    expect(page.get_by_text('Enter a dollar amount, up to 2 decimal places', exact=True)).to_be_visible()
    expect(page.locator('.error-card')).to_have_text('Error: Fix the highlighted inputs.')
    expect(page.locator('.result-card')).to_have_count(0)
    expect(page.get_by_role('button', name='Download QIF')).to_be_disabled()
    expect(page.get_by_role('button', name='Download rate schedule')).to_be_enabled()
    expect(page.get_by_role('button', name='Download lookup table')).to_be_enabled()
    field.fill('12.34')
    expect(page.locator('.result-card')).to_have_count(4)
    expect(page.get_by_role('button', name='Download QIF')).to_be_enabled()


def test_selection_theme_storage_and_retained_edits(built_browser):
    page = built_browser(storage={'tax2:selected-states': '["PA","GA","PA","unknown"]'}, instant='2026-10-08T12:00:00Z')
    assert page.locator('.state .result-label').all_text_contents() == ['Pennsylvania', 'Georgia']
    page.get_by_label('Georgia allocation', exact=True).fill('35')
    page.get_by_label('Georgia Expense Category', exact=True).fill('Synthetic edited category')
    page.get_by_label('Georgia', exact=True).uncheck()
    expect(page.get_by_label('Pennsylvania allocation', exact=True)).to_be_visible()
    page.get_by_label('Georgia', exact=True).check()
    expect(page.get_by_label('Georgia allocation', exact=True)).to_have_value('35')
    expect(page.get_by_label('Georgia Expense Category', exact=True)).to_have_value('Synthetic edited category')
    page.get_by_role('button', name='Toggle Theme').click()
    expect(page.locator('html')).to_have_class('dark')
    assert page.evaluate("localStorage.getItem('tax2:theme')") == 'dark'
    assert page.evaluate("localStorage.getItem('tax2:selected-states')") == '["PA","GA"]'
    # Stop the seed script from overwriting subsequent user preferences on reload.
    page.reload()
    expect(page.locator('html')).to_have_class('dark')
    assert page.locator('.state .result-label').all_text_contents() == ['Pennsylvania', 'Georgia']


@pytest.mark.parametrize('storage', ['["unknown"]', 'not json', '{}', '[]', 'null'])
def test_invalid_stored_selection_uses_config(built_browser, storage):
    page = built_browser(storage={'tax2:selected-states': storage, 'tax2:theme': 'invalid'})
    expect(page.get_by_label('Georgia', exact=True)).to_be_checked()
    expect(page.locator('html')).not_to_have_class('dark')


def test_changed_selection_survives_reload_without_legacy_theme_migration(built_browser):
    page = built_browser(storage={'tax2-dark-mode':'true'}, instant='2026-10-08T12:00:00Z')
    expect(page.locator('html')).not_to_have_class('dark')
    page.get_by_label('Pennsylvania', exact=True).check()
    page.get_by_label('Georgia', exact=True).uncheck()
    assert page.evaluate("localStorage.getItem('tax2:selected-states')") == '["PA"]'
    page.reload()
    expect(page.get_by_label('Pennsylvania', exact=True)).to_be_checked()
    expect(page.get_by_label('Pennsylvania', exact=True)).to_be_disabled()
    expect(page.get_by_label('Georgia', exact=True)).not_to_be_checked()
    expect(page.locator('.state .result-label')).to_have_text('Pennsylvania')


def test_blocked_storage_allows_calculation_and_theme(built_browser):
    page = built_browser(blocked=True, instant='2026-10-08T12:00:00Z')
    page.get_by_label('Pennsylvania', exact=True).check()
    income(page, '5000')
    expect(page.locator('.total .result-amount')).to_have_text('$775.44')
    page.get_by_role('button', name='Toggle Theme').click()
    expect(page.locator('html')).to_have_class('dark')


@pytest.mark.parametrize('blocked', ['write', 'tax2:theme', 'tax2:selected-states'])
def test_independent_storage_errors(built_browser, blocked):
    storage = None if blocked == 'write' else {'tax2:theme':'dark', 'tax2:selected-states':'["PA"]'}
    page = built_browser(storage=storage, blocked=blocked, instant='2026-10-08T12:00:00Z')
    if blocked == 'tax2:theme':
        expect(page.get_by_label('Pennsylvania', exact=True)).to_be_checked()
        expect(page.locator('html')).not_to_have_class('dark')
    elif blocked == 'tax2:selected-states':
        expect(page.get_by_label('Georgia', exact=True)).to_be_checked()
        expect(page.locator('html')).to_have_class('dark')
    else:
        page.get_by_label('Pennsylvania', exact=True).check()
        page.get_by_role('button', name='Toggle Theme').click()
        expect(page.locator('html')).to_have_class('dark')
    income(page, '5000')
    expect(page.get_by_role('button', name='Download QIF')).to_be_enabled()


def test_all_blob_bytes_mime_and_url_cleanup(built_browser):
    page = built_browser(instant='2026-10-08T12:00:00Z')
    page.evaluate("""() => {
        window.blobs=[]; window.revoked=[];
        const create=URL.createObjectURL, revoke=URL.revokeObjectURL;
        URL.createObjectURL=function(blob) {const url=create.call(this,blob); window.blobs.push({url,type:blob.type});return url;};
        URL.revokeObjectURL=function(url) {window.revoked.push(url);revoke.call(this,url);};
    }""")
    income(page, '5000')
    expected = page.evaluate("""() => {
        const p=JSON.parse(document.getElementById('tax2-data').textContent),e=Tax2Engine;
        const result=e.computeMonthly({earnedCents:0,unearnedCents:500000,filingStatus:'single',year:2026,
            states:[{code:'GA',allocation_pct:100}]},p);
        return [e.buildQif(result,{txDate:'2026-10-08',payee:'Estimated Taxes Withholding',
            federalExpense:'Tax:Federal Income Tax Estimated Paid',federalTransfer:'[Federal Income Taxes]'}, {},p),
            e.buildRateSchedule(2026,p),e.buildLookupCsv(2026,'single',p)];
    }""")
    for label, text in zip(['Download QIF','Download rate schedule','Download lookup table'], expected):
        _, actual = download_text(page, label)
        assert actual == text
    assert page.evaluate('window.blobs.map(blob => blob.type)') == ['application/qif','text/markdown','text/csv']
    page.clock.run_for(1100)
    assert page.evaluate('window.revoked') == page.evaluate('window.blobs.map(blob => blob.url)')


def test_local_date_and_independent_invalid_date(built_browser):
    page = built_browser()
    expect(page.get_by_label('Transaction Date', exact=True)).to_have_value('2025-12-31')
    expect(page.get_by_label('Tax Year', exact=True)).to_have_value('2025')
    name, qif = download_text(page, 'Download QIF')
    assert name == 'tax_transactions.qif'
    assert 'D12/31/25\n' in qif and ' - 12/31/2025\n' in qif
    page.get_by_label('Transaction Date', exact=True).fill('')
    expect(page.get_by_role('button', name='Download QIF')).to_be_disabled()
    expect(page.locator('.result-card')).to_have_count(4)
    page.get_by_label('Transaction Date', exact=True).fill('2026-02-28')
    expect(page.get_by_role('button', name='Download QIF')).to_be_enabled()


def test_missing_state_year_preserves_selection_and_exports(built_browser, tmp_path):
    payload = build_payload(synthetic_root(tmp_path), rules_source='custom', built_at='2024-01-01T00:00:00Z')
    page = built_browser(payload, storage={'tax2:selected-states': '["XF"]'}, instant='2026-10-08T12:00:00Z')
    expect(page.get_by_label('Tax Year', exact=True)).to_have_value('2026')
    expect(page.locator('.error-card')).to_have_text('Error: State XF has no rules for 2026. Available years: [2025]')
    expect(page.locator('.result-card')).to_have_count(0)
    expect(page.get_by_role('button', name='Download QIF')).to_be_disabled()
    filename, markdown = download_text(page, 'Download rate schedule')
    assert filename == 'tax2_rate_schedule_2026.md'
    assert '### Single' in markdown and '### Married Filing Jointly' in markdown and '## XF' not in markdown
    filename, text = download_text(page, 'Download lookup table')
    assert filename == 'tax2_lookup_2026_single.csv'
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows[1:]) == 10001 and len(rows[0]) == 2
    assert rows[1][0] == '0.00' and rows[-1][0] == '500000.00'
    page.get_by_label('Tax Year', exact=True).select_option('2025')
    expect(page.locator('.result-card')).to_have_count(4)
    expect(page.get_by_role('button', name='Download QIF')).to_be_enabled()
    page.get_by_label('Tax Year', exact=True).select_option('2026')
    expect(page.locator('.result-card')).to_have_count(0)


def test_partial_missing_year_and_selected_year_names(built_browser):
    page = built_browser(storage={'tax2:selected-states': '["GA","PA"]'}, instant='2026-10-08T12:00:00Z')
    page.get_by_label('Tax Year', exact=True).select_option('2025')
    expect(page.locator('.error-card')).to_have_text('Error: State PA has no rules for 2025. Available years: [2026]')
    expect(page.get_by_label('Georgia', exact=True)).to_be_checked()
    expect(page.get_by_label('Pennsylvania', exact=True)).to_be_checked()
    page.get_by_label('Pennsylvania', exact=True).uncheck()
    expect(page.locator('.state .result-label')).to_have_text('Georgia')


def test_available_years_multi_year_format(built_browser, tmp_path):
    root = tmp_path / 'multi-year-rules'
    for year in (2024, 2025, 2026):
        data = synthetic_rules()
        data['year'] = year
        write_synthetic(root / 'federal' / f'{year}.yaml', data)
        if year != 2024:
            write_synthetic(root / 'states' / 'XM' / f'{year}.yaml', data)
    payload = build_payload(root, rules_source='custom')
    payload['config']['default_states'] = ['XM']
    message = 'State XM has no rules for 2024. Available years: [2025, 2026]'
    page = built_browser(payload, instant='2026-10-08T12:00:00Z')
    actual = page.evaluate('''rules => {
        try {Tax2Engine.computeAnnual(0, 0, 'single', 2024,
            [{code:'XM', allocation_pct:100}], rules); return null;}
        catch (error) {return error.message;}
    }''', payload)
    assert actual == message
    page.get_by_label('Tax Year', exact=True).select_option('2024')
    expect(page.locator('.error-card')).to_have_text('Error: ' + message)


def test_allocation_validation_clamping_and_independent_exports(built_browser):
    page = built_browser(instant='2026-10-08T12:00:00Z')
    field = page.get_by_label('Georgia allocation', exact=True)
    for raw, clamped in [('150','100'),('-1','0')]:
        field.fill(raw)
        expect(field).to_have_value(clamped)
        expect(page.locator('.state .result-label')).to_have_text('Georgia' if clamped == '100' else 'Georgia (0%)')
    for raw in ['', 'invalid', 'Infinity']:
        field.fill(raw)
        expect(page.get_by_text('Enter 0–100', exact=True)).to_be_visible()
        expect(page.locator('.result-card')).to_have_count(0)
        expect(page.get_by_role('button', name='Download QIF')).to_be_disabled()
        _, text = download_text(page, 'Download rate schedule')
        assert '## GA' in text and '## PA' in text
    field.fill('33.3')
    expect(page.locator('.state .result-label')).to_have_text('Georgia (33.3%)')
    income(page, 'invalid')
    _, text = download_text(page, 'Download lookup table')
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 10002 and any('PA' in value for value in rows[0])
    page.get_by_label('Married Filing Jointly', exact=True).check()
    filename, _ = download_text(page, 'Download lookup table')
    assert filename == 'tax2_lookup_2026_married_joint.csv'


def test_late_qif_defaults_custom_code_and_empty_fallback(built_browser, tmp_path):
    built_browser.config.write_text('''default_states: [GA]
qif_overrides:
  " xtest ": {state_expense: "Synthetic override", state_transfer: 17}
  XTEST: {state_expense: 22, state_transfer: ""}
  PA: {state_expense: "Synthetic PA override"}
''')
    root = synthetic_root(tmp_path)
    for code in ['GA', 'PA', 'XTEST']:
        data = synthetic_rules()
        data.update(display_name=f'Synthetic {code}', qif={'state_expense': 'Synthetic YAML', 'state_transfer': '[Synthetic YAML account]'})
        write_synthetic(root / 'states' / code / '2026.yaml', data)
    payload = build_payload(root, rules_source='custom')
    page = built_browser(payload, instant='2026-10-08T12:00:00Z')
    page.get_by_label('Synthetic XTEST', exact=True).check()
    expect(page.get_by_label('Synthetic XTEST Expense Category', exact=True)).to_have_value('Synthetic override')
    expect(page.get_by_label('Synthetic XTEST Transfer Account', exact=True)).to_have_value('[Synthetic YAML account]')
    page.get_by_label('Synthetic PA', exact=True).check()
    expect(page.get_by_label('Synthetic PA Expense Category', exact=True)).to_have_value('Synthetic PA override')
    for code in ['GA','PA','XTEST']:
        page.get_by_label(f'Synthetic {code} Expense Category', exact=True).fill('')
        page.get_by_label(f'Synthetic {code} Transfer Account', exact=True).fill('')
    _, qif = download_text(page, 'Download QIF')
    assert 'LSynthetic YAML\n' in qif and 'LSynthetic PA override\n' in qif and 'LSynthetic override\n' in qif
    assert qif.count('L[Synthetic YAML account]\n') == 3
    page.get_by_label('Synthetic XTEST Expense Category', exact=True).fill('Synthetic edit')
    page.get_by_label('Synthetic XTEST', exact=True).uncheck()
    page.get_by_label('Synthetic XTEST', exact=True).check()
    expect(page.get_by_label('Synthetic XTEST Expense Category', exact=True)).to_have_value('Synthetic edit')


def test_selected_year_metadata_and_latest_qif_defaults(built_browser, tmp_path):
    root = synthetic_root(tmp_path)
    older = synthetic_rules()
    older.update(year=2025, display_name='Synthetic Older', qif={'state_expense':'Synthetic old'})
    write_synthetic(root / 'states' / 'XF' / '2025.yaml', older)
    newer = synthetic_rules()
    newer.update(display_name='Synthetic Latest', qif={'state_expense':'Synthetic latest'})
    write_synthetic(root / 'states' / 'XF' / '2026.yaml', newer)
    payload = build_payload(root, rules_source='custom')
    payload['config']['default_states'] = ['unknown']
    # The first discovered XE has no rules; discovery order remains authoritative.
    page = built_browser(payload, instant='2027-10-08T12:00:00Z')
    expect(page.get_by_label('Tax Year', exact=True)).to_have_value('2026')
    expect(page.get_by_label('XE', exact=True)).to_be_checked()
    page.get_by_label('Synthetic Latest', exact=True).check()
    page.get_by_label('XE', exact=True).uncheck()
    page.get_by_label('Tax Year', exact=True).select_option('2025')
    expect(page.locator('.state .result-label')).to_have_text('Synthetic Older')
    expect(page.get_by_label('Synthetic Latest Expense Category', exact=True)).to_have_value('Synthetic latest')


@pytest.mark.parametrize('rate,deduction,income_text,total,net', [(1.25,0,'100','$125.00','-$25.00'),(1,-120,'0','$10.00','-$10.00'),(1,0,'100','$100.00','$0.00'),(0,0,'0','$0.00','$0.00')])
def test_negative_zero_net_and_rate_formatting(built_browser, tmp_path, rate, deduction, income_text, total, net):
    root = synthetic_root(tmp_path)
    for code in ['federal','states/XF']:
        data = synthetic_rules()
        data['components'][0]['standard_deduction'] = dict.fromkeys(['single','married_joint'], deduction if code == 'federal' else 0)
        data['components'][0]['brackets'] = {status:[{'up_to':None,'rate':rate if code == 'federal' else 0}] for status in ['single','married_joint']}
        write_synthetic(root / code / '2026.yaml', data)
    payload = build_payload(root, rules_source='custom')
    payload['config']['default_states'] = ['XF']
    page = built_browser(payload, instant='2026-10-08T12:00:00Z')
    income(page, income_text)
    expect(page.locator('.total .result-amount')).to_have_text(total)
    expect(page.locator('.net .result-amount')).to_have_text(net)
    expected_rate = '0' if income_text == '0' else str(rate * 100).removesuffix('.0')
    expect(page.locator('.total .result-sublabel')).to_have_text(f'{expected_rate}% combined')
    expect(page.locator('.federal .result-sublabel')).to_have_text(f'{float(expected_rate):.1f}% effective')
    _, qif = download_text(page, 'Download QIF')
    assert 'T-0.00\n' in qif and 'NaN' not in page.locator('.main-panel').inner_text()


@pytest.mark.parametrize('dark', [False, True])
@pytest.mark.parametrize('width,height', [(1440,1000),(1280,1000),(1201,1000),(1200,1000),
                                          (900,1000),(768,1000),(390,844),(720,500)])
def test_responsive_geometry_and_export_reachability(built_browser, tmp_path, width, height, dark):
    page = built_browser(width=width, height=height, instant='2026-10-08T12:00:00Z')
    if dark:
        page.get_by_role('button', name='Toggle Theme').click()
    income(page, '987654321')
    page.get_by_label('Monthly Unearned Income', exact=True).blur()
    geometry = page.evaluate("""() => {
        const rect = s => document.querySelector(s).getBoundingClientRect().toJSON();
        return {main:rect('.main-panel'), exports:rect('.export-panel'),
            total:rect('.total'),net:rect('.net'), width:innerWidth,
            scrollWidth:document.documentElement.scrollWidth,
            cards:[...document.querySelectorAll('.result-amount')].map(e => ({client:e.clientWidth,scroll:e.scrollWidth})),
            netAccent:getComputedStyle(document.querySelector('.net'),'::before').backgroundColor};
    }""")
    assert geometry['scrollWidth'] <= width
    assert all(card['scroll'] <= card['client'] for card in geometry['cards']), geometry
    assert geometry['netAccent'] == ('rgb(16, 185, 129)' if dark else 'rgb(5, 150, 105)')
    if width <= 1200:
        assert geometry['exports']['top'] >= geometry['main']['bottom'] - 1
    if width <= 768:
        assert geometry['net']['top'] > geometry['total']['top']
    else:
        assert geometry['net']['top'] == geometry['total']['top']
    for label in ['Download QIF', 'Download rate schedule', 'Download lookup table']:
        button = page.get_by_role('button', name=label)
        button.scroll_into_view_if_needed()
        expect(button).to_be_in_viewport()
        expect(button).to_be_enabled()
    if width in (1440,390):
        screenshot = tmp_path / f'tax2-responsive-{width}-{"dark" if dark else "light"}.png'
        assert not screenshot.resolve().is_relative_to(REPO_ROOT.resolve())
        page.screenshot(path=str(screenshot), full_page=True)
        screenshot.chmod(0o600)
