"""Browser coverage against an isolated, synthetic SQLite database."""
import json
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
from tools.testkit import (assert_classes_styled, assert_exact_text, assert_fonts_loaded, assert_frontend_vendor_current,
    assert_launcher_compiles_cleanly, assert_no_external_resources,
    assert_offline_page_source, block_external_requests, guard_browser_errors)

LAUNCHER = REPO_ROOT / 'editdb' / 'editdb'
MARKUP = '<b>x</b> & ${y} `value` {{X}} &nbsp;'

@pytest.fixture(scope='session')
def base_url(pytestconfig):
    return pytestconfig.getoption('--base-url') or pytestconfig.getini('base_url') or None

@pytest.fixture(scope='session')
def browser_type_launch_args():
    return {'headless': True}

@pytest.fixture
def server(tmp_path):
    database = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE samples (id INTEGER PRIMARY KEY, label TEXT, note TEXT)')
        conn.executemany('INSERT INTO samples VALUES (?, ?, NULL)', [(1, 'alpha'), (2, 'beta'), (3, MARKUP), (4, '漢字')])
        conn.execute('CREATE TABLE typed (id INTEGER PRIMARY KEY, code VARCHAR(20), stamp DATETIME, plain, title TEXT)')
        conn.execute('CREATE TABLE unkeyed (label TEXT)')
        conn.execute('CREATE TABLE stored_kinds (id INTEGER PRIMARY KEY, absent TEXT, big INTEGER, raw BLOB, loose, lines TEXT)')
        conn.execute('INSERT INTO stored_kinds VALUES (1, NULL, 9007199254740993, ?, 1.0, ?)', (b'ABC', 'first line\nsecond line'))
        conn.execute("INSERT INTO unkeyed VALUES ('keyless synthetic')")
        conn.execute('CREATE TABLE composite (a TEXT, b INTEGER, label TEXT, big INTEGER, real_value REAL, raw BLOB, PRIMARY KEY(a,b))')
        conn.executemany('INSERT INTO composite VALUES (?, ?, ?, ?, ?, ?)', [('same', 9007199254740992, 'sibling', 9007199254740993, 1.0, b'\xff'), ('same', 9007199254740993, 'target', 9007199254740993, 1.0, b'\xff')])
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
        assert_fonts_loaded(page, ['Inter'])
        assert_no_external_resources(page, blocked)
        assert_offline_page_source(page.content())
    context.close()

def test_composite_big_key_and_unchanged_types(server, page, tmp_path):
    page.goto(server)
    page.get_by_role('button', name='composite', exact=True).click()
    expect(page.get_by_role('columnheader', name='a TEXT').locator('svg')).to_have_count(1)
    expect(page.get_by_role('columnheader', name='b INTEGER').locator('svg')).to_have_count(1)
    row = page.get_by_role('row').filter(has=page.get_by_role('cell', name='target', exact=True))
    expect(row).to_be_visible()
    row.locator('button').first.click()
    editing = page.locator('tbody tr').nth(1)
    editing.locator('input').nth(2).fill('edited')
    with page.expect_response(lambda response: response.url == f'{server}/api/data/composite' and response.request.method == 'PUT') as saved:
        editing.locator('button').first.click()
    assert saved.value.ok
    expect(editing.locator('input')).to_have_count(0)
    expect(page.get_by_role('cell', name='edited', exact=True)).to_be_visible()
    with sqlite3.connect(tmp_path / 'synthetic.sqlite') as db:
        assert db.execute("SELECT b, label, typeof(big), quote(big), typeof(real_value), quote(real_value), typeof(raw), quote(raw) FROM composite ORDER BY b").fetchall() == [
            (9007199254740992, 'sibling', 'integer', '9007199254740993', 'real', '1.0', 'blob', "X'FF'"),
            (9007199254740993, 'edited', 'integer', '9007199254740993', 'real', '1.0', 'blob', "X'FF'")]
    page.on('dialog', lambda dialog: dialog.accept())
    page.get_by_role('row').filter(has=page.get_by_role('cell', name='edited', exact=True)).locator('button').last.click()
    expect(page.get_by_role('cell', name='edited', exact=True)).to_have_count(0)
    with sqlite3.connect(tmp_path / 'synthetic.sqlite') as db:
        assert db.execute('SELECT b, label FROM composite').fetchall() == [(9007199254740992, 'sibling')]

def test_app_loads_without_browser_errors_and_opens_sql_console(server, page):
    with guard_browser_errors(page, expected=('__console_capture_probe__',)):
        page.add_init_script("if (localStorage.getItem('editdb_theme') === null) localStorage.setItem('editdb_theme', 'light')")
        page.goto(server, wait_until='networkidle')
        page.evaluate("console.error('__console_capture_probe__')")
        app = page.locator('#root > div').first
        expect(app).to_be_visible()
        assert page.locator('body').evaluate('e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).color]') == ['rgb(248, 250, 252)', 'rgb(15, 23, 42)']
        assert app.evaluate('e => getComputedStyle(e).backgroundColor') == 'rgb(248, 250, 252)'
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

def test_export_buttons_have_no_padding_between_icon_and_label(server, page):
    with guard_browser_errors(page):
        page.goto(server)
        expect(page.get_by_text('alpha', exact=True)).to_be_visible()
        for title, label in (('Export CSV', 'CSV'), ('Export JSON', 'JSON'), ('Export Schema (SQL)', 'SQL')):
            assert_exact_text(page.get_by_title(title), label)

NOTE_COLUMN = 3  # The grid's columns are: edit button, id, label, note, delete button.

def stored(tmp_path, row_id):
    with sqlite3.connect(tmp_path / 'synthetic.sqlite') as conn:
        return conn.execute('SELECT label, note FROM samples WHERE id = ?', (row_id,)).fetchone()

def record_writes(page):
    writes = []
    page.on('request', lambda request: request.method != 'GET' and writes.append((request.method, json.loads(request.post_data))))
    return writes

def hold_writes(page):
    """Hold every PUT until the test continues it, as a slow database would."""
    held = []
    page.route('**/api/data/samples', lambda route: held.append(route) if route.request.method == 'PUT' else route.continue_())
    return held

def wait_for_held(page, held, count=1):
    for _ in range(200):
        if len(held) >= count:
            return
        page.wait_for_timeout(10)
    pytest.fail(f'Expected {count} held writes, got {len(held)}')

def label_write(row_id, value):
    return ('PUT', {'where': {'id': row_id}, 'values': {'label': value}})

def note_cell(page, label):
    return page.get_by_role('row').filter(has=page.get_by_role('cell', name=label, exact=True)).get_by_role('cell').nth(NOTE_COLUMN)

def open_cell(page, cell):
    cell.dblclick()
    editor = page.locator('td input')
    expect(editor).to_be_focused()
    return editor

def test_escape_cancels_the_cell_editor_without_writing(server, page, tmp_path):
    with guard_browser_errors(page):
        writes = record_writes(page)
        page.goto(server)
        editor = open_cell(page, page.get_by_role('cell', name='alpha', exact=True))
        editor.fill('abandoned synthetic')
        editor.press('Escape')
        expect(editor).to_have_count(0)
        expect(page.get_by_role('cell', name='alpha', exact=True)).to_be_visible()
        page.wait_for_load_state('networkidle')
        assert writes == []
        assert stored(tmp_path, 1) == ('alpha', None)

def test_escape_on_a_null_cell_leaves_it_null(server, page, tmp_path):
    with guard_browser_errors(page):
        writes = record_writes(page)
        page.goto(server)
        expect(note_cell(page, 'alpha')).to_have_text('NULL')
        editor = open_cell(page, note_cell(page, 'alpha'))
        expect(editor).to_have_value('')
        editor.press('Escape')
        expect(editor).to_have_count(0)
        page.wait_for_load_state('networkidle')
        assert writes == []
        assert stored(tmp_path, 1) == ('alpha', None)
        page.reload()
        expect(note_cell(page, 'alpha')).to_have_text('NULL')

def test_enter_sends_exactly_one_write(server, page, tmp_path):
    with guard_browser_errors(page):
        writes = record_writes(page)
        page.goto(server)
        editor = open_cell(page, page.get_by_role('cell', name='beta', exact=True))
        editor.fill('beta2')
        editor.press('Enter')
        expect(page.get_by_role('cell', name='beta2', exact=True)).to_be_visible()
        page.wait_for_load_state('networkidle')
        assert writes == [label_write(2, 'beta2')]
        assert stored(tmp_path, 2) == ('beta2', None)

def test_enter_on_a_primary_key_cell_sends_exactly_one_write(server, page, tmp_path):
    with guard_browser_errors(page):
        writes = record_writes(page)
        page.goto(server)
        editor = open_cell(page, page.get_by_role('cell', name='2', exact=True))
        editor.fill('22')
        editor.press('Enter')
        expect(page.get_by_role('cell', name='22', exact=True)).to_be_visible()
        page.wait_for_load_state('networkidle')
        assert writes == [('PUT', {'where': {'id': 2}, 'values': {'id': '22'}})]
        assert stored(tmp_path, 22) == ('beta', None)

def test_clicking_another_cell_saves_the_open_cell_once(server, page, tmp_path):
    with guard_browser_errors(page):
        writes = record_writes(page)
        page.goto(server)
        editor = open_cell(page, page.get_by_role('cell', name='alpha', exact=True))
        editor.fill('alpha2')
        page.get_by_role('cell', name='beta', exact=True).click()
        expect(page.get_by_role('cell', name='alpha2', exact=True)).to_be_visible()
        page.wait_for_load_state('networkidle')
        assert writes == [label_write(1, 'alpha2')]
        assert stored(tmp_path, 1) == ('alpha2', None)
        assert stored(tmp_path, 2) == ('beta', None)

def test_cell_opened_during_a_save_is_not_written_when_the_save_closes_it(server, page, tmp_path):
    with guard_browser_errors(page):
        writes = record_writes(page)
        held = hold_writes(page)
        page.goto(server)
        editor = open_cell(page, page.get_by_role('cell', name='alpha', exact=True))
        editor.fill('alpha2')
        note_cell(page, 'beta').dblclick()
        wait_for_held(page, held)
        expect(page.locator('td input')).to_be_focused()
        held[0].continue_()
        expect(page.get_by_role('cell', name='alpha2', exact=True)).to_be_visible()
        page.wait_for_load_state('networkidle')
        assert writes == [label_write(1, 'alpha2')]
        assert stored(tmp_path, 2) == ('beta', None)
        expect(note_cell(page, 'beta')).to_have_text('NULL')

def test_leaving_the_cell_during_its_save_sends_no_second_write(server, page, tmp_path):
    with guard_browser_errors(page):
        writes = record_writes(page)
        held = hold_writes(page)
        page.goto(server)
        editor = open_cell(page, page.get_by_role('cell', name='beta', exact=True))
        editor.fill('beta2')
        editor.press('Enter')
        wait_for_held(page, held)
        page.get_by_role('cell', name='alpha', exact=True).click()
        expect(editor).not_to_be_focused()
        page.wait_for_timeout(100)
        assert len(held) == 1
        held[0].continue_()
        expect(page.get_by_role('cell', name='beta2', exact=True)).to_be_visible()
        page.wait_for_load_state('networkidle')
        assert writes == [label_write(2, 'beta2')]

def test_editor_stays_usable_when_a_table_cannot_be_updated(server, page):
    messages = []
    with guard_browser_errors(page):
        page.on('dialog', lambda dialog: (messages.append(dialog.message), dialog.accept()))
        writes = record_writes(page)
        page.goto(server)
        page.get_by_role('button', name='unkeyed').click()
        editor = open_cell(page, page.get_by_role('cell', name='keyless synthetic', exact=True))
        editor.press('Enter')
        editor.press('Enter')
        editor.press('Escape')
        expect(editor).to_have_count(0)
        assert messages == ['Updating requires a Primary Key.'] * 2
        assert writes == []

def test_schema_type_select_shows_each_columns_declared_type(server, page, tmp_path):
    with guard_browser_errors(page):
        page.on('dialog', lambda dialog: dialog.accept())
        writes = record_writes(page)
        page.goto(server)
        page.get_by_role('button', name='typed').click()
        page.get_by_role('button', name='Schema', exact=True).click()
        selects = page.locator('select')
        expect(selects).to_have_count(5)
        assert [selects.nth(index).input_value() for index in range(5)] == ['INTEGER', 'VARCHAR(20)', 'DATETIME', '', 'TEXT']
        expect(selects.nth(1).locator('option:checked')).to_have_text('VARCHAR(20)')
        expect(selects.nth(3).locator('option:checked')).to_have_text('(none)')
        expect(selects.nth(4).locator('option')).to_have_count(4)
        selects.nth(1).select_option('INTEGER')
        selects.nth(1).select_option('VARCHAR(20)')
        expect(selects.nth(1)).to_have_value('VARCHAR(20)')
        selects.nth(4).select_option('BLOB')
        page.get_by_role('button', name='Apply Changes').click()
        expect(selects.nth(4)).to_have_value('BLOB')
        page.wait_for_load_state('networkidle')
        assert [(column['new_name'], column['type']) for column in writes[0][1]['columns']] == [
            ('id', 'INTEGER'), ('code', 'VARCHAR(20)'), ('stamp', 'DATETIME'), ('plain', ''), ('title', 'BLOB')]
        with sqlite3.connect(tmp_path / 'synthetic.sqlite') as conn:
            assert [row[1:3] for row in conn.execute('PRAGMA table_info(typed)')] == [
                ('id', 'INTEGER'), ('code', 'VARCHAR(20)'), ('stamp', 'DATETIME'), ('plain', ''), ('title', 'BLOB')]

def test_type_change_warns_before_rebuild_and_cancel_prevents_write(server, page):
    messages = []
    with guard_browser_errors(page):
        writes = record_writes(page)
        page.on('dialog', lambda dialog: (messages.append(dialog.message), dialog.dismiss()))
        page.goto(server)
        page.get_by_role('button', name='typed').click()
        page.get_by_role('button', name='Schema', exact=True).click()
        page.locator('select').nth(4).select_option('BLOB')
        page.get_by_role('button', name='Apply Changes').click()
        assert len(messages) == 1
        assert 'rebuild' in messages[0].lower()
        assert 'back up' in messages[0].lower()
        assert writes == []

def test_enter_on_an_untouched_null_cell_writes_an_empty_string(server, page, tmp_path):
    with guard_browser_errors(page):
        writes = record_writes(page)
        page.goto(server)
        open_cell(page, note_cell(page, 'alpha')).press('Enter')
        expect(note_cell(page, 'alpha')).to_have_text('')
        page.wait_for_load_state('networkidle')
        assert writes == [('PUT', {'where': {'id': 1}, 'values': {'note': ''}})]
        assert stored(tmp_path, 1) == ('alpha', '')

@pytest.mark.parametrize('column, position, kind, literal', [
    ('absent', 2, 'null', 'NULL'),
    ('big', 3, 'integer', '9007199254740993'),
    ('raw', 4, 'blob', "X'414243'"),
    ('loose', 5, 'real', '1.0'),
    ('lines', 6, 'text', "'first line\nsecond line'"),
])
def test_clicking_away_from_an_unchanged_cell_writes_nothing(server, page, tmp_path, column, position, kind, literal):
    def stored_value():
        with sqlite3.connect(tmp_path / 'synthetic.sqlite') as conn:
            return conn.execute(f'SELECT typeof({column}), quote({column}) FROM stored_kinds').fetchone()

    with guard_browser_errors(page):
        writes = record_writes(page)
        page.goto(server)
        page.get_by_role('button', name='stored_kinds').click()
        assert stored_value() == (kind, literal)
        editor = open_cell(page, page.locator('tbody tr').first.get_by_role('cell').nth(position))
        page.get_by_role('heading', name='stored_kinds').click()
        expect(editor).to_have_count(0)
        page.wait_for_load_state('networkidle')
        assert writes == []
        assert stored_value() == (kind, literal)
