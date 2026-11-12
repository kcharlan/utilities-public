from datetime import datetime, timezone

import pytest
from playwright.sync_api import expect, sync_playwright
from tools.testkit import assert_fonts_loaded, assert_no_external_resources, block_external_requests, guard_browser_errors


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
            expect(page.locator(".status img")).to_have_count(0)
            assert page.evaluate("JSON.parse(document.getElementById('payload').textContent).rows[0].name") == "Synthetic </script><img src=x>"
            assert_fonts_loaded(page, ["Hanken Grotesk"])
            assert_no_external_resources(page, blocked)
        context.close()
        browser.close()
