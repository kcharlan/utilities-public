from datetime import datetime, timezone
from urllib.parse import quote

import pytest
from playwright.sync_api import expect, sync_playwright
from tools.testkit import assert_fonts_loaded, assert_no_external_resources, block_external_requests, guard_browser_errors


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
            expect(page.locator('tbody tr')).to_have_count(3)
            expect(page.locator('tbody tr.tier-1')).to_have_count(3)
            names = page.locator('tbody .name')
            assert names.all_text_contents()[0].startswith('Synthetic ' + 'x' * 150)
            assert names.all_text_contents()[1].startswith('Synthetic b')
            assert names.all_text_contents()[2].startswith('Synthetic c')
            page.get_by_label('Cost cap').fill('1.5')
            expect(page.locator('tbody tr')).to_have_count(1)
            expect(page.locator('.mark.frontier')).to_have_count(1)
            page.get_by_label('Show systems outside the caps').check()
            expect(page.locator('tbody tr.outside')).to_have_count(2)
            page.get_by_label('Show systems outside the caps').uncheck()
            page.get_by_role('button', name='Use official caps').click()
            expect(page.locator('tbody tr')).to_have_count(3)
            page.get_by_label('Board').select_option('open')
            expect(page.locator('tbody tr')).to_have_count(1)
            page.reload(); expect(page.get_by_label('Board')).to_have_value('open')
            page.get_by_label('Board').select_option('all')
            price_line = page.locator('.cap-line').get_attribute('x1')
            expect(page.locator('.cap-label')).to_have_text('Cap 5')
            page.get_by_label('Chart x-axis').select_option('latency')
            expect(page.locator('.cap-line')).to_have_count(1)
            expect(page.locator('.cap-label')).to_have_text('Cap 10')
            assert page.locator('.cap-line').get_attribute('x1') != price_line
            expect(page.locator('.mark.modelled')).to_have_count(1)
            page.get_by_label('Scoring').select_option('decimal')
            expect(page.locator('tbody tr.tier-1')).to_have_count(1)
            copied = page.url
            other_context = browser.new_context(service_workers='block'); other_context.set_offline(True)
            block_external_requests(other_context)
            other = other_context.new_page(); other.goto(copied)
            expect(other.get_by_label('Scoring')).to_have_value('decimal')
            other_context.close()
            page.get_by_label('Filter').fill('synthetic b')
            expect(page.locator('tbody tr')).to_have_count(1)
            page.get_by_label('Filter').fill('')
            page.get_by_label('Scoring').select_option('whole')
            page.get_by_text('Price / 1,000', exact=True).click()
            page.get_by_text('Price / 1,000', exact=True).click()
            assert page.locator('tbody .name').all_text_contents()[0].startswith('Synthetic c')
            page.get_by_role('button', name='Tier order').click()
            assert page.locator('tbody .name').all_text_contents()[0].startswith('Synthetic ' + 'x' * 150)
            for axis, label in [('price', 'Cost cap'), ('latency', 'Latency cap')]:
                page.get_by_label('Chart x-axis').select_option(axis)
                page.get_by_label(label).fill('0')
                expect(page.locator('.cap-label')).to_have_text('Cap 0')
                assert page.locator('.cap-line').get_attribute('x1') == '40'
                assert page.locator('.shade').get_attribute('width') == '500'
                page.get_by_role('button', name='Use official caps').click()
                for invalid in ['-1', '', '1e999']:
                    page.get_by_label(label).fill(invalid)
                    expect(page.locator('.cap-label')).to_have_text('Cap ' + ('5' if axis == 'price' else '10'))
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
            expect(page.get_by_label('Cost cap')).to_have_value('5')
            expect(page.get_by_label('Latency cap')).to_have_value('10')
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
            expect(page.locator(".status")).to_contain_text("$5 / 1,000 decisions; 10s")
            expect(page.locator(".status")).to_contain_text("1 ranked")
            expect(page.locator(".status")).to_contain_text("decision_ladder refresh")
            expect(page.get_by_role("link", name="JevBench by Benchmark Heaven")).to_have_attribute("href", "https://benchmarkheaven.com/")
            expect(page.locator(".status img")).to_have_count(0)
            assert page.evaluate("JSON.parse(document.getElementById('payload').textContent).rows[0].name") == "Synthetic </script><img src=x>"
            assert_fonts_loaded(page, ["Hanken Grotesk"])
            assert_no_external_resources(page, blocked)
        context.close()
        browser.close()


def test_compare_not_ranked_and_changes_offline(dl, tmp_path):
    from copy import deepcopy
    systems = [{'key': str(i), 'name': f'Synthetic system {i}', 'board': 'api', 'ranked': i != 9,
                'listing': 'Synthetic listing', 'not_ranked_because': 'Synthetic full reason',
                'source_url': 'javascript:alert(1)' if i == 1 else 'https://example.com/synthetic',
                'axes': {'intelligence': 45 if i == 0 else None, 'calibration': None, 'speed': 20, 'cost': 0},
                'capability': {'score': 8.1, 'rank': 2, 'eligible': True, 'within_caps': True},
                'rank': 3, 'price': {'kind': 'estimate', 'usd_per_1000_decisions': None if i == 1 else 2, 'basis': 'Synthetic price basis'},
                'latency': {'p50_s_adjusted': 3, 'p95_s_adjusted': 4, 'latency_basis': 'synthetic', 'adjustment': 'Synthetic adjustment'},
                'draw': {'measured_on': '2026-01-01'}} for i in range(10)]
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
            page.get_by_role('button', name='Compare', exact=True).click()
            page.get_by_label('Search systems').fill('system 0')
            expect(page.locator('.picker label')).to_have_count(1)
            page.get_by_label('Synthetic system 0', exact=True).check()
            page.get_by_label('Search systems').fill('')
            for i in range(1, 8): page.get_by_label(f'Synthetic system {i}', exact=True).check()
            expect(page.get_by_label('Synthetic system 8', exact=True)).to_be_disabled()
            expect(page.locator('.compare')).to_contain_text('45')
            expect(page.locator('.compare')).to_contain_text('Not measured')
            expect(page.locator('.compare')).to_contain_text('No price')
            expect(page.locator('.compare')).to_contain_text('Synthetic price basis')
            expect(page.locator('.compare')).to_contain_text('Synthetic adjustment')
            expect(page.locator('.compare progress[value="45"][max="100"]')).to_have_count(1)
            expect(page.locator('.compare progress[value="0"][max="100"]')).to_have_count(8)
            expect(page.locator('.compare')).to_contain_text('8.1')
            expect(page.locator('.compare')).to_contain_text('$2.00 estimate')
            expect(page.locator('.compare')).to_contain_text('3.00 s synthetic')
            expect(page.locator('.compare')).to_contain_text('4.00 s synthetic')
            expect(page.locator('.compare')).to_contain_text('2026-01-01')
            expect(page.locator('.compare a[href="https://example.com/synthetic"]')).to_have_count(7)
            expect(page.locator('.compare a[href^="javascript:"]')).to_have_count(0)
            page.reload()
            expect(page.get_by_label('Synthetic system 0', exact=True)).to_be_checked()
            expect(page.get_by_label('Synthetic system 8', exact=True)).to_be_disabled()
            page.get_by_role('button', name='Not ranked', exact=True).click()
            expect(page.locator('.not-ranked')).to_contain_text('Synthetic listing')
            expect(page.locator('.not-ranked')).to_contain_text('Synthetic full reason')
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
