"""Minimal real-browser smoke coverage for jtree."""

from __future__ import annotations

import json
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
    assert_no_external_resources,
    assert_offline_page_source,
    block_external_requests,
    assert_frontend_vendor_current,
    assert_launcher_compiles_cleanly,
    assert_classes_styled,
    guard_browser_errors,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_ROOT / "jtree"
README = PROJECT_ROOT / "README.md"
USER_GUIDE = PROJECT_ROOT / "docs" / "USER_GUIDE.md"


def test_page_loads_offline(server, browser):
    context = browser.new_context()
    blocked = block_external_requests(context, allowed_origins=[server])
    page = context.new_page()
    with guard_browser_errors(page):
        page.goto(server, wait_until="domcontentloaded")
        expect(page.get_by_title("Toggle theme")).to_be_visible(timeout=15000)
        assert_no_external_resources(page, blocked)
        assert_offline_page_source(page.content())
    context.close()


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
    fixture = tmp_path_factory.mktemp("jtree-e2e") / "synthetic.json"
    fixture.write_text(json.dumps({"name": "synthetic", "items": [1, 2]}))
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
                "jtree E2E server failed to start.\n"
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


def test_frontend_contract():
    assert_frontend_vendor_current(LAUNCHER)
    assert_launcher_compiles_cleanly(LAUNCHER)
    source = LAUNCHER.read_text()
    for token in ("--color-blueprint-bg: #0a1628;", "--color-node-type-object: #4fc3f7;", "--font-sans: 'DM Sans', sans-serif;", "--font-mono: 'JetBrains Mono', monospace;"):
        assert token in source
    for document in (README.read_text(), USER_GUIDE.read_text()):
        normalized = ' '.join(document.split())
        for text in ('current Playwright Chromium', 'Chrome 111', 'Safari 16.4', 'Firefox 128'):
            assert text in normalized
    assert 'Safari and Firefox are not covered by the automated browser test' in ' '.join(README.read_text().split())


def test_app_persists_theme_and_opens_search(server, page):
    with guard_browser_errors(page, expected=("__console_capture_probe__",)):
        page.goto(server, wait_until="domcontentloaded")
        theme_toggle = page.get_by_title("Toggle theme")
        expect(theme_toggle).to_be_visible(timeout=15_000)
        page.evaluate("console.error('__console_capture_probe__')")

        page.evaluate("document.fonts.ready")
        assert_offline_page_source(page.content())

        title = page.locator(".text-node-type-object").filter(has_text="jtree").first
        page.wait_for_function(
            "getComputedStyle(document.querySelector('.text-node-type-object')).color === 'rgb(79, 195, 247)'"
        )
        assert title.evaluate("element => getComputedStyle(element).color") == "rgb(79, 195, 247)"
        assert page.locator(".font-mono").first.evaluate(
            "element => getComputedStyle(element).fontFamily"
        ).startswith('"JetBrains Mono"')
        assert page.locator("body").evaluate(
            "element => getComputedStyle(element).backgroundColor"
        ) == "rgb(10, 22, 40)"
        assert page.evaluate("document.documentElement.classList.contains('dark')")
        assert page.evaluate("localStorage.getItem('jtree-theme')") == "dark"

        theme_toggle.click()
        page.wait_for_function("!document.documentElement.classList.contains('dark')")
        assert page.locator("body").evaluate(
            "element => getComputedStyle(element).backgroundColor"
        ) == "rgb(241, 245, 249)"
        assert page.evaluate("localStorage.getItem('jtree-theme')") == "light"
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_title("Toggle theme")).to_be_visible(timeout=15_000)
        page.wait_for_function("!document.documentElement.classList.contains('dark')")
        assert page.evaluate("localStorage.getItem('jtree-theme')") == "light"

        search = page.get_by_title("Search (Ctrl+F)")
        expect(search).to_be_visible()
        search.click()
        expect(page.get_by_placeholder("Search keys and values...")).to_be_visible()
        assert_classes_styled(page)


def test_body_font_and_background(server, page):
    with guard_browser_errors(page):
        page.goto(server, wait_until="domcontentloaded")
        expect(page.get_by_title("Toggle theme")).to_be_visible(timeout=15_000)

        body_styles = page.locator("body").evaluate(
            """element => ({
                fontFamily: getComputedStyle(element).fontFamily,
                overflow: getComputedStyle(element).overflow,
                backgroundColor: getComputedStyle(element).backgroundColor,
            })"""
        )
        assert body_styles == {
            "fontFamily": '"DM Sans", sans-serif',
            "overflow": "hidden",
            "backgroundColor": "rgb(10, 22, 40)",
        }


def test_search_updates_on_each_keystroke(server, page):
    with guard_browser_errors(page):
        page.goto(server)
        page.get_by_title('Search (Ctrl+F)').click()
        field = page.get_by_placeholder('Search keys and values...')
        for character, expected in [('n', 'n'), ('a', 'na'), ('m', 'nam'), ('e', 'name')]:
            field.press(character)
            expect(field).to_have_value(expected)
        expect(page.locator('.search-panel').get_by_text('name', exact=True)).to_be_visible()


def test_inline_editor_takes_focus_when_opened(server, page):
    with guard_browser_errors(page):
        page.goto(server)
        page.locator('.graph-node').filter(has_text='synthetic').dblclick()
        field = page.locator('.modal-box input')
        expect(field).to_be_focused()
        expect(field).to_have_value('synthetic')


def open_synthetic_data(page, server, tmp_path, data):
    fixture = tmp_path / 'invented.json'
    fixture.write_text(json.dumps(data, ensure_ascii=False))
    assert page.request.post(server + '/api/open', data={'path': str(fixture)}).ok
    page.goto(server)


def test_values_with_markup_display_literally(server, page, tmp_path):
    value = '<b>x</b> & ${y} `value` {{X}} &nbsp;'
    with guard_browser_errors(page):
        open_synthetic_data(page, server, tmp_path, {'literal': value})
        node = page.locator('.graph-node').filter(has_text='literal')
        expect(node.locator('[title]').last).to_have_attribute('title', value)
        expect(node.locator('[title]').last).to_have_text('"' + value + '"')
        assert node.locator('b').count() == 0


def test_non_latin_keys_and_values_render_with_fallback_fonts(server, page, tmp_path):
    with guard_browser_errors(page):
        open_synthetic_data(page, server, tmp_path, {'Ж': '漢', 'Ł': 'Ж'})
        page.evaluate('document.fonts.ready')
        for glyph in ('Ł', 'Ж'):
            expect(page.get_by_title(glyph).first).to_have_text(glyph)
        expect(page.get_by_title('漢').first).to_have_text('"漢"')
        page.evaluate("""() => {
            const holder = document.createElement('div');
            holder.id = 'font-probes';
            holder.style.cssText = 'position:fixed;top:100px;left:100px;background:white;color:black;font-size:48px;z-index:9999';
            for (const glyph of ['Ł', 'Ж', '漢']) {
                const span = document.createElement('span');
                span.textContent = glyph; span.style.fontFamily = 'JetBrains Mono, monospace';
                holder.appendChild(span);
            }
            document.body.appendChild(holder);
        }""")
        page.locator('#font-probes').screenshot(path=tmp_path / 'glyphs.png')
        session = page.context.new_cdp_session(page)
        session.send('DOM.enable')
        session.send('CSS.enable')
        root = session.send('DOM.getDocument')['root']['nodeId']
        for index in range(1, 4):
            node_id = session.send('DOM.querySelector', {'nodeId': root, 'selector': f'#font-probes span:nth-child({index})'})['nodeId']
            fonts = session.send('CSS.getPlatformFontsForNode', {'nodeId': node_id})['fonts']
            assert any(not font['isCustomFont'] and font['glyphCount'] > 0 for font in fonts), fonts
        if os.environ.get('JTREE_GLYPH_SCREENSHOT'):
            page.locator('#font-probes').screenshot(path=os.environ['JTREE_GLYPH_SCREENSHOT'])


def test_wheel_pan_zoom_and_image_export(server, page, tmp_path):
    with guard_browser_errors(page):
        open_synthetic_data(page, server, tmp_path, {'shape': 'synthetic'})
        canvas = page.locator('.blueprint-grid').last
        node = page.locator('.graph-node').filter(has_text='shape')
        expect(node).to_be_visible()
        before = node.bounding_box()
        canvas.hover(position={'x': 500, 'y': 350})
        page.mouse.wheel(0, 90)
        page.wait_for_function("before => document.querySelectorAll('.graph-node')[1].getBoundingClientRect().y !== before", arg=before['y'])
        assert page.evaluate('window.scrollY') == 0
        page.keyboard.down('Control')
        page.mouse.wheel(0, -100)
        page.keyboard.up('Control')
        expect(page.get_by_text('110%', exact=True)).to_be_visible()
        page.get_by_title('Export view').click()
        with page.expect_download() as download:
            page.get_by_text('PNG', exact=True).click()
        path = download.value.path()
        assert path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
