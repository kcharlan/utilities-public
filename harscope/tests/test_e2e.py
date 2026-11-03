"""Minimal real-browser smoke coverage for harscope."""

from __future__ import annotations

import json
import os
import re
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
    guard_browser_errors,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_ROOT / "harscope"
README = PROJECT_ROOT / "README.md"
USER_GUIDE = PROJECT_ROOT / "docs" / "USER_GUIDE.md"
TEST_README = PROJECT_ROOT / "tests" / "README.md"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 10) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _find_free_port()
    fixture = tmp_path_factory.mktemp("harscope-e2e") / "synthetic.har"
    fixture.write_text(
        json.dumps(
            {
                "log": {
                    "version": "1.2",
                    "creator": {"name": "synthetic-test", "version": "1.0"},
                    "entries": [],
                }
            }
        )
    )
    env = dict(os.environ, UTILITIES_TESTING="1")
    process = subprocess.Popen(
        [sys.executable, str(LAUNCHER), str(fixture), "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_server(port):
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            pytest.fail(
                "harscope E2E server failed to start.\n"
                f"stdout: {stdout.decode(errors='replace')}\n"
                f"stderr: {stderr.decode(errors='replace')}"
            )
        yield f"http://127.0.0.1:{port}"
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_embedded_frontend_is_current():
    from tools.testkit import assert_frontend_vendor_current, assert_launcher_compiles_cleanly
    assert_frontend_vendor_current(LAUNCHER)
    assert_launcher_compiles_cleanly(LAUNCHER)


def test_app_loads_without_browser_errors_and_opens_security(server, page):
    with guard_browser_errors(page):
        page.emulate_media(color_scheme="light")
        page.goto(server, wait_until="domcontentloaded")

        security = page.get_by_role("button", name="Security")
        expect(security).to_be_visible(timeout=15_000)

        app_shell = page.locator("#root > div").first
        expect(app_shell).to_be_visible()
        page.wait_for_function(
            "() => getComputedStyle(document.querySelector('#root > div')).color === 'rgb(26, 26, 26)'"
        )
        assert app_shell.evaluate("element => getComputedStyle(element).color") == "rgb(26, 26, 26)"
        assert 'DM Sans' in app_shell.evaluate("element => getComputedStyle(element).fontFamily")
        assert 'JetBrains Mono' in page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--font-mono')")
        assert page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--color-ink').trim()"
        ) == "#1a1a1a"

        light_header_background = page.locator("header").evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
        page.get_by_title("Toggle theme").click()
        page.wait_for_function("() => document.documentElement.classList.contains('dark')")
        assert page.evaluate("document.documentElement.classList.contains('dark')")
        assert app_shell.evaluate("""element => {
            const probe = document.createElement('span');
            probe.style.color = 'var(--color-gray-200)';
            document.body.appendChild(probe);
            const expected = getComputedStyle(probe).color;
            probe.remove();
            return getComputedStyle(element).color === expected;
        }""")
        assert page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--color-card-dark').trim()"
        ) == "#242424"
        assert page.locator("header").evaluate(
            "element => getComputedStyle(element).backgroundColor"
        ) != light_header_background

        security.click()
        expect(page.get_by_role("combobox", name="")).to_have_count(2)


def test_page_loads_offline(server, browser):
    from tools.testkit import assert_fonts_loaded, block_external_requests, assert_no_external_resources, assert_offline_page_source
    context = browser.new_context()
    blocked = block_external_requests(context, allowed_origins=[server])
    page = context.new_page()
    try:
        with guard_browser_errors(page):
            page.goto(server, wait_until='domcontentloaded')
            expect(page.get_by_role('button', name='Security')).to_be_visible(timeout=15000)
            assert_fonts_loaded(page, ['DM Sans', 'JetBrains Mono'])
            assert_no_external_resources(page, blocked)
            assert_offline_page_source(page.content())
    finally:
        context.close()


def _load_synthetic(page, server, har):
    result = page.request.post(server + '/api/open-content', data={
        'content': json.dumps(har), 'filename': 'synthetic.har',
    }, headers={'Origin': server})
    assert result.ok
    page.goto(server, wait_until='domcontentloaded')
    expect(page.get_by_placeholder('Search URLs...')).to_be_visible()


def test_url_search_updates_on_each_keystroke(server, page, minimal_har_dict):
    with guard_browser_errors(page):
        _load_synthetic(page, server, minimal_har_dict)
        search = page.get_by_placeholder('Search URLs...')
        expect(page.get_by_text('/api/data', exact=False).first).to_be_visible()
        for prefix in ['s', 'su', 'sub', 'subm', 'submi', 'submit']:
            search.press_sequentially(prefix[-1])
            expect(search).to_have_value(prefix)
            if prefix == 's':  # Both URLs contain the HTTPS scheme.
                expect(page.get_by_text('/api/data', exact=False).first).to_be_visible()
            else:
                expect(page.get_by_text('/api/data', exact=False)).to_have_count(0)
            expect(page.get_by_text('/api/submit', exact=False).first).to_be_visible()
        search.press('Backspace')
        expect(search).to_have_value('submi')
        expect(page.get_by_text('/api/submit', exact=False).first).to_be_visible()


def test_har_values_with_markup_display_literally(server, page, minimal_har_dict):
    sample = '<b>x</b> & ${y} `value` {{X}} &nbsp;'
    minimal_har_dict['log']['entries'][0]['response']['headers'].append(
        {'name': 'X-Synthetic-Markup', 'value': sample}
    )
    minimal_har_dict['log']['entries'][0]['response']['content'] = {'size': len(sample), 'mimeType': 'text/plain', 'text': sample}
    with guard_browser_errors(page):
        _load_synthetic(page, server, minimal_har_dict)
        page.get_by_text('/api/data', exact=False).first.click()
        page.get_by_role('button', name='Response', exact=False).first.click()
        expect(page.get_by_text(sample, exact=True)).to_be_visible()
        assert page.locator('b').filter(has_text='x').count() == 0
        page.get_by_role('button', name='Body', exact=False).click()
        expect(page.locator('pre')).to_have_text(sample)
        assert page.locator('pre b').count() == 0


def test_raw_view_text_is_the_exact_json(server, page, minimal_har_dict):
    with guard_browser_errors(page):
        _load_synthetic(page, server, minimal_har_dict)
        page.get_by_text('/api/data', exact=False).first.click()
        page.get_by_role('button', name='Raw', exact=True).click()
        text = page.locator('pre').evaluate('element => element.textContent')
        assert text.startswith('{\n')
        assert text.endswith('}')
        json.loads(text)


def test_sequence_wheel_and_pointer_pan(server, page, minimal_har_dict):
    with guard_browser_errors(page):
        _load_synthetic(page, server, minimal_har_dict)
        page.get_by_role('button', name='Sequence', exact=True).click()
        canvas = page.locator('.seq-canvas')
        expect(canvas.locator('svg').first).to_be_visible()
        assert canvas.locator("line[marker-end], line[marker-start]").count() > 0
        minimap = canvas.locator('.seq-minimap')
        expect(minimap).to_be_visible()
        expect(minimap).to_have_css('position', 'absolute')
        scene = canvas.locator('div[style*="transform"]').first
        before = scene.get_attribute('style')
        canvas.hover()
        page.mouse.wheel(0, 80)
        expect(scene).not_to_have_attribute('style', before)
        before = scene.get_attribute('style')
        page.evaluate("window.addEventListener('wheel', e => { window.wheelPrevented = e.defaultPrevented }, {once: true})")
        page.keyboard.down('Control')
        page.mouse.wheel(0, -80)
        page.keyboard.up('Control')
        page.wait_for_function('() => window.wheelPrevented === true')
        expect(scene).not_to_have_attribute('style', before)
        before = scene.get_attribute('style')
        box = canvas.bounding_box()
        page.mouse.move(box['x'] + box['width'] - 100, box['y'] + box['height'] - 100)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] - 50, box['y'] + box['height'] - 70, steps=5)
        page.mouse.up()
        expect(scene).not_to_have_attribute('style', before)


def test_sequence_zoom_stepper_and_typed_zoom(server, page, minimal_har_dict):
    """The -/+ buttons step by 1.15x within 20-300%; typed levels outside that range are ignored."""
    with guard_browser_errors(page):
        _load_synthetic(page, server, minimal_har_dict)
        page.get_by_role('button', name='Sequence', exact=True).click()
        expect(page.locator('.seq-canvas svg').first).to_be_visible()
        scene = page.locator('.seq-canvas div[style*="transform"]').first
        zoom_in = page.get_by_title('Zoom in (+)')
        zoom_out = page.get_by_title('Zoom out (-)')
        level = page.get_by_title('Type a zoom level (20-300) and press Enter')
        for button in (zoom_in, zoom_out):  # Lucide Plus and Minus icons render inside the buttons.
            expect(button.locator('svg path')).not_to_have_count(0)

        def assert_zoom(text, scale):
            expect(level).to_have_value(text)
            transform = scene.evaluate('element => element.style.transform')
            match = re.search(r'scale\(([\d.]+)\)', transform)
            assert match, transform
            assert float(match.group(1)) == pytest.approx(scale)

        def type_level(value, key='Enter'):
            shown = level.input_value()
            level.click()  # Focus swaps the label for the bare editable number.
            expect(level).to_have_value(shown.removesuffix('%'))
            level.fill(value)
            level.press(key)

        assert_zoom('100%', 1)
        zoom_in.click()
        assert_zoom('115%', 1.15)
        zoom_out.click()
        assert_zoom('100%', 1)
        zoom_out.click()
        assert_zoom('87%', 1 / 1.15)
        zoom_in.click()
        assert_zoom('100%', 1)

        type_level('250')
        assert_zoom('250%', 2.5)
        for rejected in ['301', '19', 'abc']:
            type_level(rejected)
            assert_zoom('250%', 2.5)
        type_level('120', key='Escape')  # Escape cancels the typed level.
        assert_zoom('250%', 2.5)

        for _ in range(3):  # 250% -> 287.5% -> capped at 300% -> stays 300%
            zoom_in.click()
        assert_zoom('300%', 3)

        type_level('20')
        assert_zoom('20%', 0.2)
        zoom_out.click()
        assert_zoom('20%', 0.2)
        type_level('300')
        assert_zoom('300%', 3)


def test_view_classes_have_styles(server, page, minimal_har_dict):
    from tools.testkit import assert_classes_styled
    with guard_browser_errors(page):
        _load_synthetic(page, server, minimal_har_dict)
        for tab in ['Waterfall', 'Inspector', 'Security', 'Decisions', 'Sequence', 'Dashboard', 'Export']:
            page.get_by_role('button', name=tab, exact=False).first.click()
            if tab == 'Inspector':
                page.get_by_role('button', name='Waterfall', exact=True).click()
                page.get_by_text('/api/data', exact=False).first.click()
            page.wait_for_timeout(200)
            assert_classes_styled(page, ignore=['dark'])


def test_websocket_plain_text_with_markup_displays_literally(server, page, minimal_har_dict):
    sample = '<b>x</b> & ${y} `value` {{X}} &nbsp;'
    minimal_har_dict['log']['entries'][0]['_webSocketMessages'] = [
        {'type': 'receive', 'time': 0, 'opcode': 1, 'data': sample},
    ]
    with guard_browser_errors(page):
        _load_synthetic(page, server, minimal_har_dict)
        page.get_by_text('/api/data', exact=False).first.click()
        page.get_by_role('button', name='WebSocket', exact=False).click()
        page.get_by_role('button', name=re.compile('RECV')).click()
        payload = page.locator('pre')
        expect(payload).to_have_text(sample)
        assert payload.locator('b').count() == 0


TOGGLE_REQUESTS = re.compile(r'/api/(security/toggle|redaction/(manual|remove-manual))$')


def test_failed_redaction_toggles_leave_every_checkbox_on_the_server_state(server, page, minimal_har_dict):
    entry = minimal_har_dict['log']['entries'][0]
    entry['_webSocketMessages'] = [{'type': 'receive', 'time': 0, 'opcode': 1, 'data': 'plain synthetic text'}]
    entry['response']['content'] = {'size': 5, 'mimeType': 'text/plain', 'text': 'plain'}
    failing = {'on': False}
    requests = []

    def forced_failure(route):
        requests.append(route.request.url)
        if failing['on']:
            route.fulfill(status=500, json={'detail': 'forced synthetic failure'})
        else:
            route.continue_()

    def check(errors, checkbox):
        before = checkbox.is_checked()
        failing['on'] = True
        requests.clear()
        checkbox.click()
        page.wait_for_timeout(100)
        assert len(requests) == 1
        assert checkbox.is_checked() == before
        assert any('forced synthetic failure' in error for error in errors)
        errors.clear()
        failing['on'] = False
        checkbox.click()
        expect(checkbox).to_be_checked(checked=not before)

    with guard_browser_errors(page) as errors:
        _load_synthetic(page, server, minimal_har_dict)
        page.route(TOGGLE_REQUESTS, forced_failure)
        page.get_by_text('/api/data', exact=False).first.click()
        row_checkbox = page.locator('tbody input[type=checkbox]').first
        check(errors, row_checkbox)  # Headers
        page.get_by_role('button', name='Query', exact=False).click()
        check(errors, row_checkbox)
        page.get_by_role('button', name='WebSocket', exact=False).click()
        check(errors, page.locator('input[type=checkbox].redact-cb').first)
        page.get_by_role('button', name='Response', exact=False).first.click()
        page.get_by_role('button', name='Cookies', exact=False).click()
        check(errors, row_checkbox)
        page.get_by_role('button', name='Body', exact=False).click()
        check(errors, page.locator('button input[type=checkbox]').first)
        page.get_by_role('button', name='Security').first.click()
        check(errors, page.get_by_label('Redact').first)


def test_decisions_area_filter_falls_back_when_its_area_disappears(server, page, minimal_har_dict):
    entry = minimal_har_dict['log']['entries'][0]
    entry['request']['cookies'] = [{'name': 'flavour', 'value': 'plain'}]
    entry['response']['cookies'] = []
    with guard_browser_errors(page):
        _load_synthetic(page, server, minimal_har_dict)
        page.get_by_text('/api/data', exact=False).first.click()
        page.get_by_role('button', name='Cookies', exact=False).click()
        page.locator('tbody input[type=checkbox]').first.click()
        expect(page.locator('tbody input[type=checkbox]').first).not_to_be_checked()
        page.get_by_role('button', name='Decisions', exact=False).first.click()
        area = page.locator('select').nth(2)
        area.select_option('cookies')
        rows = page.locator('tbody tr')
        expect(rows).to_have_count(1)
        rows.get_by_role('button', name='Keep').click()
        expect(area).to_have_value('')
        expect(area.locator('option:checked')).to_have_text('All areas')
        expect(page.get_by_text('No decisions match the current filters')).to_have_count(0)
        expect(rows.first).to_contain_text('REDACT')
