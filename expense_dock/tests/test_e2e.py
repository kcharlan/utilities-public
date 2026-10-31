"""Isolated browser coverage for Expense Dock."""
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from tools.testkit import (
    assert_classes_styled,
    assert_frontend_vendor_current,
    assert_launcher_compiles_cleanly,
    assert_no_external_resources,
    assert_offline_page_source,
    block_external_requests,
    guard_browser_errors,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_ROOT / 'expense_dock'

@pytest.fixture(scope='module')
def server(tmp_path_factory):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    home = tmp_path_factory.mktemp('expense-dock-e2e')
    env = dict(os.environ, UTILITIES_TESTING='1', EXPENSE_DOCK_HOME=str(home))
    process = subprocess.Popen(
        [sys.executable, str(LAUNCHER), '--port', str(port), '--no-browser'],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=1):
                    break
            except OSError:
                time.sleep(.2)
        else:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail(f'Server failed: {stdout!r} {stderr!r}')
        yield f'http://127.0.0.1:{port}'
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

def test_vendor_contract():
    assert_frontend_vendor_current(LAUNCHER)
    assert_launcher_compiles_cleanly(LAUNCHER)
    source = LAUNCHER.read_text()
    for token in (
        "--font-display: 'Fraunces', serif;",
        "--font-body: 'Work Sans', sans-serif;",
        "--font-mono: 'IBM Plex Mono', monospace;",
        '--shadow-docket: 0 24px 80px rgba(16, 24, 40, 0.18);',
        '--color-ledger-paper: #f7f0df;',
        '--color-ledger-sand: #dccfaf;',
    ):
        assert token in source

def test_page_loads_offline(server, browser):
    context = browser.new_context()
    blocked = block_external_requests(context, allowed_origins=[server])
    page = context.new_page()
    page.route('**/api/auth/**', lambda route: route.abort())
    with guard_browser_errors(page):
        page.goto(server, wait_until='networkidle')
        expect(page.get_by_role('heading', name='Expense Dock')).to_be_visible()
        assert_no_external_resources(page, blocked)
        assert_offline_page_source(page.content())
    context.close()

def test_config_field_updates_on_each_keystroke(server, page):
    page.route('**/api/auth/**', lambda route: route.abort())
    with guard_browser_errors(page):
        page.goto(server, wait_until='networkidle')
        page.get_by_role('button', name='Setup Connection and defaults').click()
        field = page.get_by_role('textbox', name='Default paid by')
        assert page.request.get(server + '/api/status').json()['lookups']['paid_by'] == []
        saves = []

        def capture_save(route):
            expect(field).to_be_focused()
            saves.append(route.request.post_data_json)
            route.continue_()

        page.route('**/api/config', capture_save)
        for index, char in enumerate('SYNTHETIC', 1):
            field.focus()
            field.press_sequentially(char)
            expect(field).to_be_focused()
            with page.expect_response('**/api/config'):
                page.get_by_role('button', name='Save config').evaluate('(button) => button.click()')
            assert saves[-1]['defaults']['paid_by'] == 'SYNTHETIC'[:index]
            expect(field).to_have_value('SYNTHETIC'[:index])

def test_footer_shows_the_running_version(server, page):
    page.route('**/api/auth/**', lambda route: route.abort())
    with guard_browser_errors(page):
        page.goto(server, wait_until='networkidle')
        version = page.request.get(server + '/api/status').json()['version']
        expect(page.locator('.fixed').get_by_text('v' + version)).to_be_visible()

def test_app_loads_without_browser_errors_and_opens_setup(server, page):
    page.route('**/api/auth/**', lambda route: route.abort())
    with guard_browser_errors(page, expected=('__console_capture_probe__',)):
        page.add_init_script("if (localStorage.getItem('expenseDockTheme') === null) localStorage.setItem('expenseDockTheme', 'light')")
        page.goto(server, wait_until='networkidle')
        page.evaluate("console.error('__console_capture_probe__')")
        title = page.get_by_role('heading', name='Expense Dock')
        expect(title).to_be_visible()
        page.evaluate('document.fonts.ready')
        assert 'Fraunces' in title.evaluate('element => getComputedStyle(element).fontFamily')
        setup = page.get_by_role('button', name='Setup Connection and defaults')
        expect(setup).to_be_visible()
        setup.click()
        expect(page.get_by_text('OneDrive + workbook settings')).to_be_visible()
        client_id = page.get_by_role('textbox', name='Microsoft client ID')
        assert client_id.evaluate('e => getComputedStyle(e).backgroundColor') == 'rgb(255, 255, 255)'
        page.get_by_role('button', name='Dark').click()
        page.wait_for_function("getComputedStyle(document.querySelector('input')).backgroundColor === 'rgb(26, 51, 39)'")
        assert page.evaluate("document.documentElement.classList.contains('dark')")
        assert page.evaluate("localStorage.getItem('expenseDockTheme')") == 'dark'
        assert client_id.evaluate('e => getComputedStyle(e).backgroundColor') == 'rgb(26, 51, 39)'
        page.reload(wait_until='networkidle')
        assert page.evaluate("document.documentElement.classList.contains('dark')")
        assert page.evaluate("localStorage.getItem('expenseDockTheme')") == 'dark'
        expect(page.get_by_role('button', name='Light')).to_be_visible()
        for name in ('Submit Primary intake form', 'Setup Connection and defaults', 'Queue No pending retries', 'Lookups Not refreshed yet'):
            page.get_by_role('button', name=name).click()
            assert_classes_styled(page)
