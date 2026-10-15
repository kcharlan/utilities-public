import pytest
from playwright.sync_api import sync_playwright, expect
from browser_errors import guard_browser_errors
from helpers import SESSION, REQUEST

@pytest.fixture
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        # Native action links remain inert even if a test accidentally clicks one.
        page.add_init_script("document.addEventListener('click', e => { const a=e.target.closest('a'); if(a && !/^(file:|#)/.test(a.getAttribute('href') || '')) { e.preventDefault(); e.stopImmediatePropagation(); } }, true)")
        try:
            yield page
        finally:
            context.close()
            browser.close()

def open_native(page, native_page):
    requests = []
    def intercept(route):
        if route.request.url.startswith("file://"):
            route.continue_()
        else:
            requests.append(route.request.url)
            route.abort()
    page.route("**/*", intercept)
    page.goto(native_page.as_uri() + "#v=list&p=all")
    return requests

def test_native_page_renders_and_filters_synthetic_session(page, native_page):
    with guard_browser_errors(page):
        requests = open_native(page, native_page)
        expect(page).to_have_title("Colophon")
        row = page.locator(f'[data-session-id="{SESSION}"]')
        expect(row).to_have_count(1)
        expect(row).to_contain_text("Synthetic violet kite")
        row.click()
        reader = page.locator(f'[data-reader="{SESSION}"]')
        expect(reader).to_be_visible()
        expect(reader).to_contain_text(REQUEST)
        expect(reader).to_contain_text("Synthetic kite complete")
        page.locator(".breadcrumb").get_by_role("button", name="sessions", exact=True).click()
        search = page.get_by_role("searchbox", name="Search titles and requests")
        search.fill("synthetic-does-not-match")
        expect(page.locator("[data-list-row]")).to_have_count(0)
        expect(page.get_by_text("No sessions match the active filters")).to_be_visible()
        search.fill("violet kite")
        expect(page.locator("[data-list-row]")).to_have_count(1)
        assert requests == []

def test_native_page_is_self_contained_and_error_free(page, native_page):
    html = native_page.read_text()
    for marker in ("@@FONTS@@", "@@CSS@@", "@@JS@@", "@@DATA@@"):
        assert marker not in html
    with guard_browser_errors(page):
        requests = open_native(page, native_page)
        expect(page.locator("#colophon-app")).not_to_be_empty()
        assert page.locator("script[src], link[rel=stylesheet][href]").count() == 0
        assert page.locator("#colophon-data").count() == 1
        page.wait_for_timeout(300)
        assert requests == []

def test_claude_reader_never_offers_codex_actions(page, native):
    native.claude_session()
    result = native.build()
    assert result.returncode == 0, result.stderr
    with guard_browser_errors(page):
        requests = open_native(page, native.page)
        page.locator('[data-session-id="synthetic-claude"]').click()
        reader = page.locator('[data-reader="synthetic-claude"]')
        expect(reader).to_be_visible()
        expect(reader).to_contain_text("Synthetic Claude kite complete")
        expect(reader.get_by_role("link", name="Open in Codex")).to_have_count(0)
        expect(reader.get_by_role("button", name="Copy Continue in CLI")).to_have_count(0)
        expect(reader.get_by_role("button", name="Copy session ID", exact=True)).to_have_count(1)
        assert requests == []
