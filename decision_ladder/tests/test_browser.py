from datetime import datetime, timezone
from urllib.parse import quote

import pytest
from playwright.sync_api import expect, sync_playwright
from tools.testkit import assert_fonts_loaded, assert_no_external_resources, block_external_requests, guard_browser_errors


def test_chart_highlight_tracks_hover_and_focus_independently(dl, tmp_path):
    from helpers import feed, many_systems, snapshot
    payload = dl.build_payload(snapshot(feed(systems=many_systems(10))), None, {'max_age_hours': 24})
    path = tmp_path / 'highlight.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(service_workers='block'); context.set_offline(True)
        blocked = block_external_requests(context); page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri())
            first, second = page.locator('tr.system-row').nth(0), page.locator('tr.system-row').nth(1)
            first_name = first.locator('.name').get_attribute('title')
            second_name = second.locator('.name').get_attribute('title')
            first.focus(); second.hover()
            expect(page.locator('.mark.highlight title')).to_contain_text(second_name)
            page.mouse.move(0, 0)
            expect(page.locator('.mark.highlight title')).to_contain_text(first_name)
            first.hover(); page.mouse.move(0, 0)
            expect(page.locator('.mark.highlight title')).to_contain_text(first_name)
            second.hover(); page.get_by_label('Filter').focus()
            expect(page.locator('.mark.highlight title')).to_contain_text(second_name)
            page.mouse.move(0, 0)
            expect(page.locator('.mark.highlight')).to_have_count(0)
            assert_no_external_resources(page, blocked)
        context.close(); browser.close()


@pytest.mark.parametrize('scheme', ['light', 'dark'])
def test_large_board_navigation_and_chart(dl, tmp_path, scheme):
    from helpers import feed, many_systems, snapshot
    payload = dl.build_payload(snapshot(feed(systems=many_systems(300))), None, {'max_age_hours': 24})
    path = tmp_path / 'many.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(viewport={'width': 1280, 'height': 900}, color_scheme=scheme, service_workers='block')
        context.set_offline(True); blocked = block_external_requests(context); page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri())
            assert 25 <= page.locator('tr.system-row').count() <= 60
            assert page.evaluate('document.documentElement.scrollHeight') < 6000
            assert page.locator('.chart').bounding_box()['width'] >= 800
            row = page.locator('tr.system-row').first
            row.hover(); expect(page.locator('.mark.highlight')).to_have_count(1)
            row.focus(); expect(page.locator('.mark.highlight')).to_have_count(1)
            page.locator('.mark.highlight').click(force=True)
            expect(page.get_by_label('Filter')).to_have_value(row.locator('.name').get_attribute('title'))
            page.get_by_label('Filter').fill('')
            page.get_by_role('button', name='Collapse all').click()
            expect(page.locator('tr.system-row')).to_have_count(0)
            expect(page.locator('tr.tier-heading button').first).to_have_attribute('aria-expanded', 'false')
            page.locator('tr.tier-heading button').first.click()
            expect(page.locator('tr.tier-heading button').first).to_have_attribute('aria-expanded', 'true')
            page.get_by_role('button', name='Expand all').click()
            expect(page.locator('tr.system-row')).to_have_count(300)
            page.locator('.board-table').evaluate('(el) => { el.scrollTop = 400; }')
            assert page.locator('.board-table').evaluate('(el) => Math.abs(el.querySelector("thead th").getBoundingClientRect().top - el.getBoundingClientRect().top) < 2')
            page.get_by_role('columnheader', name='Price / 1,000').press('Space')
            expect(page.get_by_role('columnheader', name='Price / 1,000')).to_have_attribute('aria-sort', 'ascending')
            assert page.get_by_role('columnheader', name='Price / 1,000').evaluate('(el) => { const e = new KeyboardEvent("keydown", {key:" ", bubbles:true, cancelable:true}); el.dispatchEvent(e); return e.defaultPrevented; }')
            expect(page.locator('tr.tier-heading')).to_have_count(0)
            page.get_by_label('Filter').fill('no synthetic match')
            expect(page.get_by_text('No system matches “no synthetic match”.')).to_be_visible()
            expect(page.locator('.mark.dim')).to_have_count(300)
            page.get_by_role('button', name='Clear filter').click()
            expect(page.locator('tr.system-row')).to_have_count(300)
            page.get_by_label('Frontier only').check()
            assert 0 < page.locator('tr.system-row').count() < 300
            page.set_viewport_size({'width': 375, 'height': 844})
            expect(page.locator('.chart')).to_have_attribute('viewBox', '0 0 480 360')
            assert page.locator('.chart text').evaluate_all('(xs) => Math.min(...xs.map(x => x.getBoundingClientRect().height))') >= 10
            assert_no_external_resources(page, blocked)
        context.close(); browser.close()


@pytest.mark.parametrize('scores,decimal_expected', [
    ([8.0, 8.0, 8.0], 'price: 2 → 3.001'),
    ([7.9, 8.1, 8.2], 'capability: 8.1 → 8.2'),
    ([7.9, 8.123, 8.456], 'capability: 8.1 → 8.5'),
])
def test_history_uses_displayed_changes_for_each_mode(dl, tmp_path, scores, decimal_expected):
    from datetime import timedelta
    from helpers import feed, system
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, (score, price) in enumerate(zip(scores, [2, 3, 3.001])):
        data = feed(systems=[system(capability={'score': score, 'eligible': True, 'within_caps': True},
                                    price={'usd_per_1000_decisions': price}, latency={'p50_s_adjusted': 2})])
        dl.save_snapshot(tmp_path, {'feed': data, 'sha256': 'synthetic'}, now + timedelta(seconds=i))
    path = tmp_path / 'history.html'
    dl.build_page(tmp_path, path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(service_workers='block'); context.set_offline(True)
        blocked = block_external_requests(context); page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri()); page.get_by_text('Changes', exact=True).click()
            expect(page.locator('.changes')).to_contain_text('price: 3 → 3.001' if scores[-1] == 8.456 else 'price: 2 → 3.001')
            page.get_by_label('Scoring').select_option('decimal')
            expect(page.locator('.changes')).to_contain_text(decimal_expected)
            assert_no_external_resources(page, blocked)
        context.close(); browser.close()


def test_reference_and_unknown_boards_are_truthful(dl, tmp_path):
    from helpers import feed, system, snapshot
    systems = [system(key=board, name='Synthetic ' + board, board=board,
                      capability={'score': 8, 'eligible': True, 'within_caps': True},
                      price={'usd_per_1000_decisions': 2}, latency={'p50_s_adjusted': 2})
               for board in ['open', 'api', 'reference', 'synthetic-unknown']]
    payload = dl.build_payload(snapshot(feed(systems=systems)), None, {'max_age_hours': 24}); payload['built_at'] = 'synthetic'
    path = tmp_path / 'boards.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(service_workers='block'); context.set_offline(True)
        blocked = block_external_requests(context); page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri())
            expect(page.locator('tbody tr.system-row')).to_have_count(4)
            expect(page.locator('tbody tr.system-row').filter(has_text='Synthetic reference')).to_contain_text('Reference')
            expect(page.locator('tbody tr.system-row').filter(has_text='Synthetic synthetic-unknown')).to_contain_text('synthetic-unknown')
            expect(page.locator('circle.mark')).to_have_count(1)
            expect(page.locator('rect.mark')).to_have_count(1)
            expect(page.locator('polygon.mark')).to_have_count(2)
            expect(page.locator('.legend')).to_contain_text('Reference and other boards')
            page.get_by_label('Board').select_option('api')
            expect(page.locator('tbody tr.system-row')).to_have_count(1)
            expect(page.locator('tbody tr.system-row')).to_contain_text('Synthetic api')
            assert_no_external_resources(page, blocked)
        context.close(); browser.close()


@pytest.mark.parametrize('scheme', ['light', 'dark'])
def test_board_controls_and_responsive_layout(dl, tmp_path, scheme):
    systems = []
    for key, score, price, latency, board in [('a', 8.1, 1, 2, 'open'), ('b', 8.2, 2, 3, 'api'), ('c', 8.3, 3, 4, 'api')]:
        systems.append({'key': key, 'name': 'Synthetic ' + key + ' (Example lab)', 'board': board, 'ranked': True,
                        'capability': {'score': score, 'within_caps': True, 'eligible': True},
                        'price': {'kind': 'estimate', 'usd_per_1000_decisions': price},
                        'latency': {'p50_s_adjusted': latency, 'latency_basis': 'api-end-to-end'}})
    systems[0]['name'] = 'Synthetic ' + 'x' * 150 + '<b>'
    systems[0]['latency']['latency_basis'] = 'synthetic-assumption'
    feed = {'revision': 'synthetic', 'method': {'label': 'Synthetic'}, 'capability_policy': {'cost_cap_usd_per_1000': 5, 'median_latency_cap_s': 10}, 'systems': systems}
    snap = {'fetched_at': '2026-01-01T00:00:00+00:00', 'last_checked': '2026-01-01T00:00:00+00:00', 'feed': feed}
    payload = dl.build_payload(snap, None, {'max_age_hours': 24}); payload['built_at'] = 'synthetic'
    path = tmp_path / 'board.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(viewport={'width': 390, 'height': 844}, color_scheme=scheme, service_workers='block')
        context.set_offline(True); blocked = block_external_requests(context); page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri())
            expect(page.locator('tbody tr.system-row')).to_have_count(3)
            expect(page.locator('tbody tr.tier-heading')).to_have_count(1)
            page.set_viewport_size({'width': 1280, 'height': 900})
            assert page.locator('tr.system-row').first.bounding_box()['height'] <= 56
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.locator('tbody tr.tier-1')).to_have_count(3)
            names = page.locator('tbody .name')
            assert names.all_text_contents()[0].startswith('Synthetic ' + 'x' * 150)
            assert names.all_text_contents()[1].startswith('Synthetic b')
            assert names.all_text_contents()[2].startswith('Synthetic c')
            page.get_by_label('Cost cap').fill('1.5')
            expect(page.locator('tbody tr.system-row')).to_have_count(1)
            expect(page.locator('.mark.frontier')).to_have_count(1)
            page.get_by_label('Show systems outside the caps').check()
            expect(page.locator('tbody tr.outside')).to_have_count(2)
            page.get_by_label('Show systems outside the caps').uncheck()
            page.get_by_role('button', name='Use official caps').click()
            expect(page.locator('tbody tr.system-row')).to_have_count(3)
            page.get_by_label('Board').select_option('open')
            expect(page.locator('tbody tr.system-row')).to_have_count(1)
            page.reload(); expect(page.get_by_label('Board')).to_have_value('open')
            page.get_by_label('Board').select_option('all')
            expect(page.locator('.mark')).to_have_count(3)
            price_mark = page.locator('rect.mark').first.get_attribute('x')
            expect(page.locator('.cap-label')).to_have_text('Cap $5.00')
            page.get_by_label('Chart x-axis').select_option('latency')
            expect(page.locator('.cap-line')).to_have_count(1)
            expect(page.locator('.cap-label')).to_have_text('Cap 10.00 s')
            assert page.locator('rect.mark').first.get_attribute('x') != price_mark
            expect(page.locator('.mark.published')).to_have_count(2)
            page.get_by_label('Scoring').select_option('decimal')
            expect(page.locator('tbody tr.tier-1')).to_have_count(1)
            copied = page.url
            other_context = browser.new_context(service_workers='block'); other_context.set_offline(True)
            block_external_requests(other_context)
            other = other_context.new_page(); other.goto(copied)
            expect(other.get_by_label('Scoring')).to_have_value('decimal')
            other_context.close()
            page.get_by_label('Filter').fill('synthetic b')
            expect(page.locator('tbody tr.system-row')).to_have_count(1)
            page.get_by_label('Filter').fill('')
            page.get_by_label('Scoring').select_option('whole')
            page.get_by_role('columnheader', name='Price / 1,000').click()
            page.get_by_role('columnheader', name='Price / 1,000').click()
            assert page.locator('tbody .name').all_text_contents()[0].startswith('Synthetic c')
            page.get_by_role('button', name='Tier order').click()
            assert page.locator('tbody .name').all_text_contents()[0].startswith('Synthetic ' + 'x' * 150)
            for axis, label in [('price', 'Cost cap'), ('latency', 'Latency cap')]:
                page.get_by_label('Chart x-axis').select_option(axis)
                page.get_by_label(label).fill('0')
                expect(page.locator('.cap-label')).to_have_text('Cap ' + ('$0.0000' if axis == 'price' else '0 ms'))
                assert page.locator('.cap-line').get_attribute('x1') == '40'
                assert page.locator('.shade').get_attribute('width') == '420'
                page.get_by_role('button', name='Use official caps').click()
                page.get_by_label(label).fill('')
                expect(page.get_by_role('status')).to_have_count(0)
                expect(page.get_by_role('button', name='Use official caps')).to_be_disabled()
                for invalid in ['-1', '1e999']:
                    page.get_by_label(label).fill(invalid)
                    expect(page.locator('.cap-label')).to_have_text('Cap ' + ('$5.00' if axis == 'price' else '10.00 s'))
                    expect(page.get_by_role('status')).to_contain_text('official cap is used')
                    assert 'NaN' not in page.locator('.cap-line').get_attribute('x1')
                    assert 'NaN' not in page.locator('.shade').get_attribute('width')
                for extreme in ['1e308', '5e-324']:
                    page.get_by_label(label).fill(extreme)
                    assert float(page.locator('.cap-line').get_attribute('x1')) > 0
                    assert float(page.locator('.shade').get_attribute('width')) > 0
                page.get_by_role('button', name='Use official caps').click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('tbody b').count() == 0
            assert_no_external_resources(page, blocked)
        context.close(); browser.close()


def test_exact_official_caps_and_tab_state(dl, tmp_path):
    from helpers import feed, system, snapshot
    data = feed(systems=[system(name='Synthetic boundary', capability={'score': 8.123, 'eligible': True, 'within_caps': True}, price={'usd_per_1000_decisions': 0.00008}, latency={'p50_s_adjusted': 1}, axes={'intelligence': 34.567, 'calibration': 45.678})])
    data['capability_policy'] = {'cost_cap_usd_per_1000': 0.00007345678912345678, 'median_latency_cap_s': 2}
    payload = dl.build_payload(snapshot(data), None, {'max_age_hours': 24}); payload['built_at'] = '2026-01-02T03:04:05Z'
    path = tmp_path / 'caps.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(service_workers='block'); context.set_offline(True); block_external_requests(context)
        page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri())
            expect(page.locator('.status')).to_contain_text('$0.0001')
            expect(page.locator('tbody tr')).to_have_count(0)
            page.get_by_label('Show systems outside the caps').check()
            expect(page.locator('tbody tr.outside')).to_have_count(1)
            expect(page.locator('tbody tr.system-row td').nth(2)).to_have_text('34.6')
            expect(page.locator('tbody tr.system-row td').nth(3)).to_have_text('45.7')
            expect(page.get_by_role('tab', name='Board')).to_have_attribute('aria-selected', 'true')
            expect(page.get_by_role('tab', name='Compare')).to_have_attribute('aria-selected', 'false')
            expect(page.get_by_role('tab', name='Not ranked')).to_have_attribute('aria-selected', 'false')
            expect(page.get_by_label('Cost cap')).to_have_value('')
            page.get_by_label('Cost cap').fill('0.0001')
            expect(page.get_by_text('Custom caps')).to_be_visible()
            expect(page.locator('tbody tr.outside')).to_have_count(0)
            page.get_by_role('button', name='Use official caps').click()
            expect(page.get_by_text('Custom caps')).to_have_count(0)
            expect(page.locator('tbody tr.outside')).to_have_count(1)
            expect(page.locator('footer')).to_contain_text('2026-01-02 03:04 UTC')
            page.goto(path.as_uri() + '#' + quote('{"cost":0.00007345678912345678,"latency":2}'))
            page.reload()
            expect(page.get_by_label('Cost cap')).to_have_value('')
            expect(page.get_by_label('Latency cap')).to_have_value('')
            expect(page.get_by_role('button', name='Use official caps')).to_be_disabled()
        context.close(); browser.close()


@pytest.mark.parametrize('check', ['placeholder', 'typing'])
def test_subsecond_placeholder_and_sequential_cap_entry(dl, tmp_path, check):
    from helpers import feed, system, snapshot
    data = feed(systems=[system(name='Synthetic fractional', capability={'score': 8, 'eligible': True, 'within_caps': True}, price={'usd_per_1000_decisions': 0.2}, latency={'p50_s_adjusted': 0.2})])
    data['capability_policy'] = {'cost_cap_usd_per_1000': 1, 'median_latency_cap_s': 0.5}
    payload = dl.build_payload(snapshot(data), None, {'max_age_hours': 24}); payload['built_at'] = 'synthetic'
    path = tmp_path / 'fractions.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(service_workers='block'); context.set_offline(True); block_external_requests(context)
        page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri())
            if check == 'placeholder':
                expect(page.get_by_label('Latency cap')).to_have_attribute('placeholder', '0.5')
            else:
                for label in ['Cost cap', 'Latency cap']:
                    field = page.get_by_label(label)
                    field.press_sequentially('0.125')
                    expect(field).to_have_value('0.125')
                    expect(page.locator('tbody tr')).to_have_count(0)
                    page.get_by_role('button', name='Use official caps').click()
                    expect(page.locator('tbody tr.system-row')).to_have_count(1)
        context.close(); browser.close()


def test_invalid_state_and_blocked_storage(dl, tmp_path):
    feed = {'revision': 'synthetic', 'method': {'label': 'Synthetic'}, 'capability_policy': {'cost_cap_usd_per_1000': 5, 'median_latency_cap_s': 10}, 'systems': []}
    snap = {'fetched_at': '2026-01-01T00:00:00+00:00', 'last_checked': '2026-01-01T00:00:00+00:00', 'feed': feed}
    payload = dl.build_payload(snap, None, {'max_age_hours': 24}); payload['built_at'] = 'synthetic'
    path = tmp_path / 'state.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(service_workers='block')
        context.set_offline(True); block_external_requests(context)
        context.add_init_script("Object.defineProperty(Storage.prototype, 'setItem', {value(){throw new Error('blocked')}})")
        page = context.new_page()
        with guard_browser_errors(page):
            invalid = '{"query":null,"board":"bad","mode":[],"axis":"bad","cost":-1,"latency":null,"outside":"yes","sort":"bad","dir":0}'
            page.goto(path.as_uri() + '#' + quote(invalid))
            expect(page.get_by_label('Board')).to_have_value('all')
            expect(page.get_by_label('Scoring')).to_have_value('whole')
            expect(page.get_by_label('Chart x-axis')).to_have_value('price')
            expect(page.get_by_label('Filter')).to_have_value('')
            expect(page.get_by_label('Cost cap')).to_have_value('')
            expect(page.get_by_label('Latency cap')).to_have_value('')
            expect(page.get_by_label('Show systems outside the caps')).not_to_be_checked()
            page.get_by_label('Board').select_option('open')
            expect(page.get_by_label('Board')).to_have_value('open')
            assert 'open' in page.url
        context.close(); browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_offline_status_and_untrusted_text(dl, tmp_path, scheme):
    feed = {"revision": "synthetic </script><img src=x>", "method": {"label": "Synthetic method"},
            "capability_policy": {"cost_cap_usd_per_1000": 5, "median_latency_cap_s": 10},
            "systems": [{"key": "synthetic", "name": "Synthetic </script><img src=x>", "board": "api", "ranked": True,
                         "capability": {"score": 3, "eligible": True, "within_caps": True}}]}
    snap = {"fetched_at": "2026-01-01T00:00:00+00:00", "last_checked": "2026-01-01T00:00:00+00:00", "feed": feed}
    payload = dl.build_payload(snap, None, {"max_age_hours": 24})
    payload["built_at"] = "synthetic time"
    path = tmp_path / "page.html"
    path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(color_scheme=scheme, service_workers="block")
        context.set_offline(True)
        blocked = block_external_requests(context)
        page = context.new_page()
        page.clock.set_fixed_time(datetime(2026, 1, 3, tzinfo=timezone.utc))
        with guard_browser_errors(page):
            page.goto(path.as_uri())
            expect(page.locator("#status-age")).to_have_class("age stale")
            expect(page.locator(".status")).to_contain_text("Synthetic method")
            expect(page.locator(".status")).to_contain_text("1 measured")
            expect(page.locator(".status")).to_contain_text("synthetic </script><img src=x>")
            expect(page.locator(".status")).to_contain_text("$5.00 / 1,000 decisions; 10.00 s")
            expect(page.locator(".status")).to_contain_text("1 ranked")
            expect(page.locator(".status")).to_contain_text("decision_ladder refresh")
            expect(page.get_by_role("link", name="JevBench by Benchmark Heaven")).to_have_attribute("href", "https://benchmarkheaven.com/")
            expect(page.locator(".status img")).to_have_count(0)
            assert page.evaluate("JSON.parse(document.getElementById('payload').textContent).rows[0].name") == "Synthetic </script><img src=x>"
            assert_fonts_loaded(page, ["Hanken Grotesk"])
            assert_no_external_resources(page, blocked)
        context.close()
        browser.close()


def test_picker_keyboard_navigation_keeps_focused_option_visible(dl, tmp_path):
    from helpers import feed, system, snapshot
    systems = [system(key=f'synthetic-{i:02}', name=f'Synthetic system {i:02}',
                      capability={'score': 20 - i, 'eligible': True, 'within_caps': True},
                      price={'usd_per_1000_decisions': 1}, latency={'p50_s_adjusted': 1}) for i in range(20)]
    payload = dl.build_payload(snapshot(feed(systems=systems)), None, {'max_age_hours': 24})
    path = tmp_path / 'picker.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(service_workers='block'); context.set_offline(True)
        blocked = block_external_requests(context); page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri()); page.get_by_role('tab', name='Compare', exact=True).click()
            page.get_by_role('button', name='Add system').click()
            page.get_by_label('Search systems').press('ArrowDown')
            for _ in range(12): page.keyboard.press('ArrowDown')
            active = page.locator('.pop li button:focus')
            expect(active).to_contain_text('Synthetic system 12')
            bounds = active.evaluate('(el) => { const a=el.getBoundingClientRect(), b=el.closest("ul").getBoundingClientRect(); return [a.top, a.bottom, b.top, b.bottom]; }')
            assert bounds[0] >= bounds[2] - 1 and bounds[1] <= bounds[3] + 1, bounds
            page.keyboard.press('Enter')
            expect(page.locator('.chip')).to_contain_text('Synthetic system 12')
            assert_no_external_resources(page, blocked)
        context.close(); browser.close()


def test_compare_not_ranked_and_changes_offline(dl, tmp_path):
    from copy import deepcopy
    systems = [{'key': str(i), 'name': f'Synthetic system {i}', 'board': 'api', 'ranked': i != 9,
                'listing': 'Synthetic listing', 'not_ranked_because': 'Synthetic full reason',
                'source_url': 'javascript:alert(1)' if i == 1 else 'https://example.com/synthetic',
                'axes': {'intelligence': 45.123456789 if i == 0 else None, 'calibration': None, 'speed': 20, 'cost': 0},
                'capability': {'score': 8.123456789, 'rank': 2, 'eligible': True, 'within_caps': True},
                'rank': 3, 'price': {'kind': 'estimate', 'usd_per_1000_decisions': None if i == 1 else 2, 'basis': 'Synthetic price basis ' + 'x' * 1300},
                'latency': {'p50_s_adjusted': 3, 'p95_s_adjusted': 4, 'latency_basis': 'synthetic', 'adjustment': 'Synthetic adjustment'},
                'draw': {'measured_on': None if i == 9 else '2026-01-01'}} for i in range(10)]
    feed = {'revision': 'new synthetic', 'method': {'label': 'Synthetic method'}, 'capability_policy': {'cost_cap_usd_per_1000': 5, 'median_latency_cap_s': 10}, 'systems': systems}
    old = deepcopy(feed); old['revision'] = 'old synthetic'; old['systems'][0]['capability']['score'] = 8.2
    snap = {'fetched_at': '2026-01-02', 'last_checked': '2026-01-02', 'feed': feed}
    prior = {'fetched_at': '2026-01-01', 'feed': old}
    payload = dl.build_payload(snap, prior, {'max_age_hours': 24}); payload['built_at'] = 'synthetic'
    path = tmp_path / 'compare.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(service_workers='block'); context.set_offline(True)
        blocked = block_external_requests(context); page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri()); page.get_by_text('Changes', exact=True).click()
            expect(page.locator('.changes')).to_contain_text('old synthetic')
            expect(page.locator('.changes')).not_to_contain_text('Synthetic system 0')
            page.get_by_label('Scoring').select_option('decimal')
            expect(page.locator('.changes')).to_contain_text('Synthetic system 0')
            page.get_by_role('tab', name='Compare', exact=True).click()
            page.get_by_role('button', name='Add system').click()
            assert page.locator('.pop li button').all_text_contents()[-1].startswith('Synthetic system 9')
            page.get_by_label('Search systems').fill('system 0')
            page.locator('.pop li button').click()
            expect(page.locator('.pop li button')).to_be_disabled()
            expect(page.locator('.pop li button')).to_contain_text('Added')
            page.get_by_label('Search systems').fill('')
            for i in range(1, 3): page.locator('.pop li button').filter(has_text=f'Synthetic system {i}').click()
            page.locator('.chip').get_by_role('button', name='Remove Synthetic system 1').click()
            expect(page.get_by_text('2 of 8 selected')).to_be_visible()
            page.reload()
            expect(page.get_by_text('2 of 8 selected')).to_be_visible()
            page.get_by_role('button', name='Add system').click()
            for i in range(1, 8):
                if i != 2: page.locator('.pop li button').filter(has_text=f'Synthetic system {i}').click()
            expect(page.get_by_role('button', name='Limit of 8 reached')).to_be_disabled()
            expect(page.locator('.chip')).to_have_count(8)
            widths = page.locator('.compare thead th').evaluate_all('(xs) => xs.map(x => x.getBoundingClientRect().width)')
            page.get_by_text('Price basis and latency adjustment', exact=True).click()
            assert page.locator('.compare thead th').evaluate_all('(xs) => xs.map(x => x.getBoundingClientRect().width)') == widths
            assert widths[0] >= 150 and min(widths[1:]) >= 150 and max(widths[1:]) - min(widths[1:]) < 1
            page.locator('.compare').evaluate('(el) => { el.scrollTop = el.scrollHeight; }')
            assert page.locator('.compare').evaluate('(el) => el.scrollTop > 0')
            assert page.locator('.compare').evaluate('(el) => Math.abs(el.querySelector("thead th").getBoundingClientRect().top - el.getBoundingClientRect().top) < 2')
            expect(page.locator('.compare tbody tr').filter(has=page.get_by_text('Intelligence', exact=True)).locator('.pill')).to_have_count(1)
            expect(page.locator('.compare tbody tr').filter(has=page.get_by_text('Capability', exact=True)).locator('.pill')).to_have_count(8)
            expect(page.locator('.compare tbody tr').filter(has=page.get_by_text('Price / 1,000 decisions', exact=True)).locator('.pill')).to_have_count(7)
            expect(page.locator('.compare tbody tr').filter(has=page.get_by_text('Capability rank', exact=True)).locator('.pill')).to_have_count(7)
            expect(page.locator('.compare tbody tr').filter(has=page.get_by_text('Capability rank', exact=True))).to_contain_text('Not ranked: no price')
            expect(page.locator('.compare tbody tr').filter(has=page.get_by_text('Composite rank', exact=True))).to_contain_text('Not ranked: no price')
            expect(page.locator('.compare')).to_contain_text('45')
            expect(page.locator('.compare')).to_contain_text('Not measured')
            expect(page.locator('.compare')).to_contain_text('No price')
            expect(page.locator('.compare-details')).to_contain_text('Synthetic price basis')
            expect(page.locator('.compare-details')).to_contain_text('Synthetic adjustment')
            expect(page.locator('.compare')).to_contain_text('45.1')
            expect(page.locator('.compare')).not_to_contain_text('45.123456789')
            expect(page.locator('.compare')).not_to_contain_text('8.123456789')
            expect(page.locator('.compare progress[value="45.123456789"][max="100"]')).to_have_count(1)
            expect(page.locator('.compare progress[value="0"][max="100"]')).to_have_count(8)
            expect(page.locator('.compare')).to_contain_text('8.1')
            expect(page.locator('.compare')).to_contain_text('$2.00 estimate')
            expect(page.locator('.compare')).to_contain_text('3.00 s synthetic')
            expect(page.locator('.compare')).to_contain_text('4.00 s synthetic')
            expect(page.locator('.compare')).to_contain_text('2026-01-01')
            expect(page.locator('.compare a[href="https://example.com/synthetic"]')).to_have_count(7)
            expect(page.locator('.compare a[href^="javascript:"]')).to_have_count(0)
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('.compare').evaluate('(el) => el.scrollWidth > el.clientWidth')
            page.get_by_role('button', name='Clear all').click()
            expect(page.locator('.compare table')).to_have_count(0)
            expect(page.get_by_text('No systems selected. Add up to 8 to compare them side by side.')).to_be_visible()
            page.get_by_role('button', name='Add system').click()
            page.get_by_label('Search systems').fill('system 9')
            page.get_by_label('Search systems').press('ArrowDown')
            page.get_by_label('Search systems').press('ArrowUp')
            page.get_by_label('Search systems').press('Enter')
            page.get_by_label('Search systems').press('Escape')
            expect(page.get_by_role('button', name='Add system')).to_be_focused()
            for rank in ['Capability rank', 'Composite rank']:
                expect(page.locator('.compare tbody tr').filter(has=page.get_by_text(rank, exact=True))).to_contain_text('Not ranked: Synthetic full reason')
            expect(page.locator('.compare')).to_contain_text('Not given')
            expect(page.locator('.compare .pill')).to_have_count(0)
            page.get_by_role('tab', name='Not ranked', exact=True).click()
            expect(page.locator('.not-ranked')).to_contain_text('Synthetic listing')
            expect(page.locator('.not-ranked')).to_contain_text('Synthetic full reason')
            expect(page.locator('.not-ranked table tbody tr')).to_have_count(1)
            expect(page.locator('.not-ranked')).to_contain_text('1 system')
            page.get_by_label('Filter not ranked systems').fill('no match')
            expect(page.locator('.not-ranked table tbody tr')).to_have_count(0)
            expect(page.locator('.not-ranked')).to_contain_text('0 systems')
            assert_no_external_resources(page, blocked)
        context.close(); browser.close()


def test_changes_method_and_caps_notices(dl, tmp_path):
    from copy import deepcopy
    feed = {'revision': 'new', 'method': {'label': 'New synthetic method'}, 'capability_policy': {'cost_cap_usd_per_1000': 5, 'median_latency_cap_s': 10}, 'systems': [{'key': 'a', 'name': 'Synthetic changed', 'board': 'api', 'ranked': True, 'capability': {'score': 9, 'eligible': True, 'within_caps': True}}]}
    old = deepcopy(feed); old['method']['label'] = 'Old synthetic method'; old['capability_policy']['cost_cap_usd_per_1000'] = 3; old['systems'][0]['capability']['score'] = 2
    payload = dl.build_payload({'fetched_at': 'new', 'last_checked': 'new', 'feed': feed}, {'fetched_at': 'old', 'feed': old}, {'max_age_hours': 24}); payload['built_at'] = 'synthetic'
    path = tmp_path / 'method.html'; path.write_bytes(dl.render_page(payload))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(); context = browser.new_context(service_workers='block'); context.set_offline(True); block_external_requests(context)
        page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri()); page.get_by_text('Changes', exact=True).click()
            expect(page.locator('.changes')).to_contain_text('Scoring method changed from Old synthetic method to New synthetic method; scores before and after are not comparable')
            expect(page.locator('.changes')).to_contain_text('$3 / 1,000 decisions; 10s → $5 / 1,000 decisions; 10s')
            expect(page.locator('.changes')).not_to_contain_text('Synthetic changed')
        context.close(); browser.close()
