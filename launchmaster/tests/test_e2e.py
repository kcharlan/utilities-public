"""
End-to-end tests using Playwright.

These tests start the real launchmaster server and exercise the React SPA
in a real Chromium browser. They catch rendering errors, broken CDN loads,
dead buttons, and layout issues that API-only tests miss entirely.

Run E2E tests only:
    pytest tests/test_e2e.py -v

The E2E tests can run alone or as part of the full suite.

Requires:
    pip install playwright pytest-playwright
    playwright install chromium
"""

import json
import os
import re
import urllib.request

import pytest

# ── Enforce UTILITIES_TESTING ─────────────────────────────────────────────────
os.environ["UTILITIES_TESTING"] = "1"

# ── Check playwright is installed ─────────────────────────────────────────────
try:
    from playwright.sync_api import expect
except ImportError:
    pytest.skip(
        "playwright not installed — run: pip install playwright pytest-playwright "
        "&& playwright install chromium",
        allow_module_level=True,
    )

pytestmark = pytest.mark.e2e

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Page Load & CDN Dependencies
# ═══════════════════════════════════════════════════════════════════════════════

class TestPageLoad:
    def test_page_loads_without_js_errors(self, server, page):
        """SPA loads with no JavaScript console errors."""
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(server, wait_until="networkidle")
        assert not errors, f"JavaScript errors on page load: {errors}"

    def test_title_is_launchmaster(self, server, page):
        page.goto(server, wait_until="networkidle")
        assert "launchmaster" in page.title().lower()

    def test_topbar_renders(self, server, page):
        page.goto(server, wait_until="networkidle")
        brand = page.locator(".topbar-brand")
        expect(brand).to_be_visible()
        expect(brand).to_contain_text("launchmaster")

    def test_react_mounts(self, server, page):
        """The React app mounts and renders content (not blank screen)."""
        page.goto(server, wait_until="networkidle")
        # The app-shell should exist and have child content
        shell = page.locator(".app-shell")
        expect(shell).to_be_visible()
        # Status cards should render
        cards = page.locator(".status-cards")
        expect(cards).to_be_visible()

    def test_no_babel_syntax_errors(self, server, page):
        """Babel compiles the JSX without syntax errors (regression for \\n bug)."""
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(server, wait_until="networkidle")
        syntax_errors = [e for e in errors if "SyntaxError" in e]
        assert not syntax_errors, (
            f"Babel syntax errors (likely unescaped \\n in template): {syntax_errors}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Status Cards
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatusCards:
    def test_status_cards_render(self, server, page):
        page.goto(server, wait_until="networkidle")
        cards = page.locator(".status-card")
        expect(cards.first).to_be_visible()
        count = cards.count()
        assert count == 5, f"Expected 5 status cards, got {count}"

    def test_status_cards_have_counts(self, server, page):
        page.goto(server, wait_until="networkidle")
        # Each card should have a numeric count
        counts = page.locator(".status-card-count")
        for i in range(counts.count()):
            text = counts.nth(i).text_content()
            assert text.strip().isdigit(), f"Status card {i} count is not numeric: {text}"

    def test_status_card_click_filters(self, server, page):
        page.goto(server, wait_until="networkidle")
        # Click "Running" card
        running_card = page.locator(".status-card.running")
        running_card.click()
        # Should become active
        expect(running_card).to_have_class(re.compile(r"active"))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Job Table
# ═══════════════════════════════════════════════════════════════════════════════

class TestJobTable:
    def test_job_table_renders(self, server, page):
        page.goto(server, wait_until="networkidle")
        table = page.locator(".job-table")
        expect(table).to_be_visible()

    def test_job_rows_exist(self, server, page):
        page.goto(server, wait_until="networkidle")
        rows = page.locator(".job-table tbody tr")
        count = rows.count()
        assert count > 0, "No job rows rendered"

    def test_job_row_has_status_dot(self, server, page):
        page.goto(server, wait_until="networkidle")
        first_row = page.locator(".job-table tbody tr").first
        dot = first_row.locator(".status-dot")
        expect(dot).to_be_visible()

    def test_job_row_click_opens_detail_panel(self, server, page):
        page.goto(server, wait_until="networkidle")
        first_row = page.locator(".job-table tbody tr").first
        first_row.click()
        panel = page.locator(".detail-panel")
        expect(panel).to_have_class(re.compile(r"open"))

    def test_pagination_visible_when_many_jobs(self, server, page):
        """If there are more than 25 jobs, pagination should appear."""
        page.goto(server, wait_until="networkidle")
        # Get the job count from the API
        resp = urllib.request.urlopen(f"{server}/api/jobs?include_apple=false")
        jobs = json.loads(resp.read().decode())
        if len(jobs) > 25:
            # Pagination should be visible
            pagination = page.get_by_text("Page", exact=False).first
            expect(pagination).to_be_visible()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Filter Bar
# ═══════════════════════════════════════════════════════════════════════════════

class TestFilterBar:
    def test_search_filters_jobs(self, server, page):
        page.goto(server, wait_until="networkidle")
        response = urllib.request.urlopen(f"{server}/api/jobs?include_apple=false")
        jobs = json.loads(response.read().decode())
        assert jobs, "Search test requires at least one discovered non-Apple job"
        query = jobs[0]["label"]

        search = page.locator(".filter-search")
        search.fill(query)
        page.wait_for_timeout(300)
        rows = page.locator(".job-table tbody tr")
        count = rows.count()
        assert count > 0, "Search should find the discovered job by exact label"
        # All visible labels should contain the search term
        for i in range(min(count, 5)):
            text = rows.nth(i).locator(".job-label-text").text_content()
            assert query.lower() in text.lower()

    def test_search_clear_button(self, server, page):
        page.goto(server, wait_until="networkidle")
        search = page.locator(".filter-search")
        search.fill("test-search")
        # Clear button should appear
        clear_btn = page.locator("button:has-text('clear')")
        expect(clear_btn).to_be_visible()
        clear_btn.click()
        # Search should be empty
        expect(search).to_have_value("")

    def test_domain_filter(self, server, page):
        page.goto(server, wait_until="networkidle")
        select = page.locator(".filter-select")
        select.select_option("user-agent")
        page.wait_for_timeout(300)
        # All visible domain badges should be user-agent
        badges = page.locator(".job-table tbody tr .domain-badge")
        for i in range(min(badges.count(), 5)):
            text = badges.nth(i).text_content().strip().lower()
            assert "user" in text, f"Expected user-agent domain, got: {text}"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Detail Panel
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetailPanel:
    def test_detail_panel_shows_info(self, server, page):
        page.goto(server, wait_until="networkidle")
        page.locator(".job-table tbody tr").first.click()
        panel = page.locator(".detail-panel")
        expect(panel).to_have_class(re.compile(r"open"))
        # Info tab should be active by default
        active_tab = panel.locator(".panel-tab.active")
        expect(active_tab).to_contain_text("Info")
        # Info grid should have label
        label_value = panel.locator(".info-grid .info-value").first
        expect(label_value).not_to_be_empty()

    def test_detail_panel_logs_tab(self, server, page):
        page.goto(server, wait_until="networkidle")
        page.locator(".job-table tbody tr").first.click()
        logs_tab = page.locator(".panel-tab:has-text('Logs')")
        logs_tab.click()
        # Log viewer should appear
        log_viewer = page.locator(".log-viewer")
        expect(log_viewer).to_be_visible()

    def test_detail_panel_edit_tab(self, server, page):
        page.goto(server, wait_until="networkidle")
        page.locator(".job-table tbody tr").first.click()
        edit_tab = page.locator(".panel-tab:has-text('Edit')")
        edit_tab.click()
        # Plist editor should appear
        editor = page.locator(".plist-editor")
        expect(editor).to_be_visible()

    def test_detail_panel_close(self, server, page):
        page.goto(server, wait_until="networkidle")
        page.locator(".job-table tbody tr").first.click()
        panel = page.locator(".detail-panel")
        expect(panel).to_have_class(re.compile(r"open"))
        # Close via X button
        page.locator(".panel-header .icon-btn").click()
        page.wait_for_timeout(500)
        # Panel is conditionally rendered — removed from DOM when closed
        expect(page.locator(".detail-panel.open")).to_have_count(0)

    def test_detail_panel_escape_closes(self, server, page):
        page.goto(server, wait_until="networkidle")
        page.locator(".job-table tbody tr").first.click()
        panel = page.locator(".detail-panel")
        expect(panel).to_have_class(re.compile(r"open"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        # Panel is conditionally rendered — removed from DOM when closed
        expect(page.locator(".detail-panel.open")).to_have_count(0)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Enabled/Disabled Display (Regression)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnabledDisplayRegression:
    """Verify that jobs don't all show as 'Disabled' in the UI.

    This catches the original bug where the backend never set 'enabled'
    field, causing the SPA's getJobStatus() to treat all jobs as disabled.
    """

    def test_not_all_jobs_show_disabled(self, server, page):
        """At least some jobs should show as Running or Idle, not all Disabled."""
        page.goto(server, wait_until="networkidle")
        disabled_card = page.locator(".status-card.disabled .status-card-count")
        running_card = page.locator(".status-card.running .status-card-count")
        idle_card = page.locator(".status-card.idle .status-card-count")

        disabled_count = int(disabled_card.text_content())
        running_count = int(running_card.text_content())
        idle_count = int(idle_card.text_content())

        assert running_count + idle_count > 0, (
            f"All jobs appear disabled ({disabled_count} disabled, "
            f"0 running, 0 idle) — regression: enabled field missing"
        )

    def test_running_status_dots_exist(self, server, page):
        """There should be green (running) status dots in the table."""
        page.goto(server, wait_until="networkidle")
        running_dots = page.locator(".status-dot.running")
        assert running_dots.count() > 0, (
            "No running status dots visible — likely all showing disabled"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Create Job Modal
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateJobModal:
    def test_new_job_button_opens_modal(self, server, page):
        page.goto(server, wait_until="networkidle")
        new_btn = page.locator("button:has-text('New Job')")
        new_btn.click()
        modal = page.locator(".modal")
        expect(modal).to_be_visible()

    def test_create_modal_has_form_fields(self, server, page):
        page.goto(server, wait_until="networkidle")
        page.locator("button:has-text('New Job')").click()
        modal = page.locator(".modal")
        # Should have label input
        label_input = modal.locator("input[placeholder*='com.']")
        expect(label_input).to_be_visible()
        # Should have domain select
        domain_select = modal.locator("select.form-input")
        expect(domain_select.first).to_be_visible()

    def test_create_modal_close(self, server, page):
        page.goto(server, wait_until="networkidle")
        page.locator("button:has-text('New Job')").click()
        modal = page.locator(".modal")
        expect(modal).to_be_visible()
        # Close via Cancel
        page.locator("button:has-text('Cancel')").click()
        expect(modal).not_to_be_visible()


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Settings Modal
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettingsModal:
    def test_settings_button_opens_modal(self, server, page):
        page.goto(server, wait_until="networkidle")
        # Settings is an icon button in the topbar
        settings_btn = page.locator(".topbar-right .icon-btn").last
        settings_btn.click()
        # Modal should appear with "Settings" title
        modal = page.locator(".modal")
        expect(modal).to_be_visible()
        expect(modal.locator(".modal-title")).to_contain_text("Settings")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Keyboard Shortcuts
# ═══════════════════════════════════════════════════════════════════════════════

class TestKeyboardShortcuts:
    def test_n_opens_create_modal(self, server, page):
        page.goto(server, wait_until="networkidle")
        page.keyboard.press("n")
        modal = page.locator(".modal")
        expect(modal).to_be_visible()

    def test_slash_focuses_search(self, server, page):
        page.goto(server, wait_until="networkidle")
        page.keyboard.press("/")
        search = page.locator(".filter-search")
        expect(search).to_be_focused()


# ═══════════════════════════════════════════════════════════════════════════════
# 10. WebSocket Connection
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocket:
    def test_websocket_connects(self, server, page):
        """WS indicator should show 'Live' when connected."""
        page.goto(server, wait_until="networkidle")
        ws_status = page.locator(".topbar-ws-status")
        expect(ws_status).to_contain_text("Live")
        # The dot should not have 'disconnected' class
        ws_dot = page.locator(".ws-dot")
        expect(ws_dot).not_to_have_class(re.compile(r"disconnected"))


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Apple Jobs Toggle
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppleJobsToggle:
    def test_apple_jobs_hidden_by_default(self, server, page):
        page.goto(server, wait_until="networkidle")
        apple_rows = page.locator(".job-table tbody tr.apple-row")
        assert apple_rows.count() == 0, "Apple rows should be hidden by default"

    def test_apple_toggle_shows_apple_jobs(self, server, page):
        page.goto(server, wait_until="networkidle")
        toggle = page.locator(".filter-toggle:has-text('Apple')")
        toggle.click()
        page.wait_for_timeout(500)
        apple_rows = page.locator(".job-table tbody tr.apple-row")
        assert apple_rows.count() > 0, "Apple rows should appear after toggle"

    def test_apple_rows_have_amber_styling(self, server, page):
        page.goto(server, wait_until="networkidle")
        toggle = page.locator(".filter-toggle:has-text('Apple')")
        toggle.click()
        page.wait_for_timeout(500)
        apple_row = page.locator(".job-table tbody tr.apple-row").first
        # Should have the amber left border
        border = apple_row.evaluate(
            "el => getComputedStyle(el).borderLeftColor"
        )
        # Amber/gold color in some form
        assert "232" in border or "160" in border or "rgba" in border, (
            f"Apple row border color doesn't look amber: {border}"
        )
