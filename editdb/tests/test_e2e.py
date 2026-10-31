"""Browser coverage against an isolated, synthetic SQLite database."""
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from tools.testkit import (assert_classes_styled, assert_frontend_vendor_current,
    assert_launcher_compiles_cleanly, assert_no_external_resources,
    assert_offline_page_source, block_external_requests, guard_browser_errors)

LAUNCHER = REPO_ROOT / 'editdb' / 'editdb'
MARKUP = '<b>x</b> & ${y} `value` {{X}} &nbsp;'

@pytest.fixture
def server(tmp_path):
    database = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE samples (id INTEGER PRIMARY KEY, label TEXT)')
        conn.executemany('INSERT INTO samples VALUES (?, ?)', [(1, 'alpha'), (2, 'beta'), (3, MARKUP), (4, '漢字')])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, str(LAUNCHER), str(database), '--port', str(port)],
        env=dict(os.environ, UTILITIES_TESTING='1'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            process.kill()
            out, err = process.communicate(timeout=5)
            pytest.fail(f'Server failed to start: {out!r} {err!r}')
        yield f'http://127.0.0.1:{port}'
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

def test_frontend_contract():
    assert_frontend_vendor_current(LAUNCHER)
    assert_launcher_compiles_cleanly(LAUNCHER)

def test_page_loads_offline(server, browser):
    context = browser.new_context()
    blocked = block_external_requests(context, allowed_origins=[server])
    page = context.new_page()
    with guard_browser_errors(page):
        page.goto(server, wait_until='networkidle')
        expect(page.get_by_role('button', name='SQL Console')).to_be_visible()
        assert_no_external_resources(page, blocked)
        assert_offline_page_source(page.content())
    context.close()

def test_app_loads_without_browser_errors_and_opens_sql_console(server, page):
    with guard_browser_errors(page, expected=('__console_capture_probe__',)):
        page.add_init_script("if (localStorage.getItem('editdb_theme') === null) localStorage.setItem('editdb_theme', 'light')")
        page.goto(server, wait_until='networkidle')
        page.evaluate("console.error('__console_capture_probe__')")
        app = page.locator('#root > div').first
        expect(app).to_be_visible()
        assert page.locator('body').evaluate('e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).color]') == ['rgb(248, 250, 252)', 'rgb(15, 23, 42)']
        assert app.evaluate('e => getComputedStyle(e).backgroundColor') == 'rgb(248, 250, 252)'
        assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--color-brand-dark-50').trim()") == '#f8fafc'
        expect(page.get_by_text('alpha', exact=True)).to_be_visible()
        assert_classes_styled(page)
        page.get_by_role('button', name='Schema', exact=True).click()
        expect(page.get_by_text('Structure Design')).to_be_visible()
        assert_classes_styled(page)
        page.get_by_title('Toggle Theme').click()
        page.wait_for_function("getComputedStyle(document.querySelector('#root > div')).backgroundColor === 'rgb(2, 6, 23)'")
        assert page.evaluate("document.documentElement.classList.contains('dark') && localStorage.getItem('editdb_theme') === 'dark'")
        page.reload(wait_until='networkidle')
        expect(page.get_by_role('button', name='SQL Console')).to_be_visible()
        assert page.evaluate("document.documentElement.classList.contains('dark') && localStorage.getItem('editdb_theme') === 'dark'")
        assert page.locator('#root > div').first.evaluate('e => getComputedStyle(e).backgroundColor') == 'rgb(2, 6, 23)'
        page.get_by_role('button', name='SQL Console').click()
        expect(page.get_by_text('Raw SQL Query')).to_be_visible()
        assert_classes_styled(page)
        page.locator('textarea').fill('SELECT 7 AS synthetic_value;')
        page.get_by_role('button', name='Run Query').click()
        expect(page.get_by_role('columnheader', name='synthetic_value')).to_be_visible()
        expect(page.get_by_role('cell', name='7', exact=True)).to_be_visible()

def test_column_filter_updates_on_each_keystroke(server, page):
    with guard_browser_errors(page):
        page.goto(server)
        expect(page.get_by_text('alpha', exact=True)).to_be_visible()
        search = page.get_by_placeholder('Filter columns...')
        search.press_sequentially('b')
        expect(page.get_by_text('alpha', exact=True)).to_have_count(0)
        expect(page.get_by_text('beta', exact=True)).to_be_visible()
        search.press('Backspace')
        search.press_sequentially('al')
        expect(page.get_by_text('alpha', exact=True)).to_be_visible()
        expect(page.get_by_text('beta', exact=True)).to_have_count(0)
        search.press('Backspace')
        expect(page.get_by_text('beta', exact=True)).to_be_visible()

def test_double_click_opens_the_cell_editor_with_focus(server, page):
    with guard_browser_errors(page):
        page.goto(server)
        cell = page.get_by_role('cell', name='alpha', exact=True)
        expect(cell).to_be_visible()
        cell.dblclick()
        editor = page.locator('td input')
        expect(editor).to_be_focused()
        editor.fill('changed synthetic')
        editor.press('Enter')
        expect(page.get_by_role('cell', name='changed synthetic', exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role('cell', name='changed synthetic', exact=True)).to_be_visible()

def test_cell_values_with_markup_display_literally(server, page):
    with guard_browser_errors(page):
        page.goto(server)
        cell = page.get_by_role('cell', name=MARKUP, exact=True)
        expect(cell).to_be_visible()
        assert cell.inner_text() == MARKUP
        assert cell.locator('b').count() == 0
        expect(page.get_by_role('cell', name='漢字', exact=True)).to_be_visible()
