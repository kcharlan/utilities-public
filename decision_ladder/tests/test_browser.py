from datetime import datetime, timezone

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
            page.get_by_label('Chart x-axis').select_option('latency')
            expect(page.locator('.cap-line')).to_have_count(1)
            expect(page.locator('.mark.modelled')).to_have_count(1)
            page.get_by_label('Scoring').select_option('decimal')
            expect(page.locator('tbody tr.tier-1')).to_have_count(1)
            copied = page.url
            other = context.new_page(); other.goto(copied)
            expect(other.get_by_label('Scoring')).to_have_value('decimal')
            other.close()
            page.get_by_label('Filter').fill('synthetic b')
            expect(page.locator('tbody tr')).to_have_count(1)
            page.get_by_label('Filter').fill('')
            page.get_by_text('Price / 1,000', exact=True).click()
            page.get_by_role('button', name='Tier order').click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('tbody b').count() == 0
            assert_no_external_resources(page, blocked)
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
