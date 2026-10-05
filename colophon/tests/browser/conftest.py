"""Guarded Chromium over private synthetic file pages, with a frozen snapshot."""
import json
import re
from contextlib import ExitStack
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from tools.testkit import guard_browser_errors

FIXTURE_NOW_MS = 1_894_708_800_000  # 2030-01-15 12:00 UTC


@pytest.fixture(scope='session')
def browser():
    with sync_playwright() as driver:
        chromium = driver.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def page_for(browser, colophon, tmp_path, monkeypatch):
    with ExitStack() as stack:
        page_number = 0
        def open_page(payload_or_codex_home, *, tz='UTC', width=1440, hash='', init_script=None):
            nonlocal page_number
            output = tmp_path / f'synthetic-page-{page_number}.html'
            page_number += 1
            if isinstance(payload_or_codex_home, dict):
                output.write_bytes(colophon.render_page(payload_or_codex_home))
            else:
                root = Path(payload_or_codex_home)
                monkeypatch.setenv('COLOPHON_HOME', str(tmp_path / 'synthetic-runtime'))
                args = colophon.build_arg_parser().parse_args(['--offline', '--no-open', '--codex-home', str(root), '--output', str(output)])
                assert colophon.run(args, now_ms=FIXTURE_NOW_MS, stderr_tty=False) == 0
            context = browser.new_context(timezone_id=tz, viewport={'width': width, 'height': 900})
            stack.callback(context.close)
            page = context.new_page()
            if init_script:
                page.add_init_script(init_script)
            page.set_default_timeout(3000)
            stack.enter_context(guard_browser_errors(page))
            forbidden = []
            def route_request(route):
                if route.request.url.split('#')[0] == output.as_uri():
                    route.continue_()
                else:
                    forbidden.append(route.request.url)
                    route.abort()
            page.route('**/*', route_request)
            stack.callback(lambda: _assert_no_requests(forbidden))
            page.goto(output.as_uri() + hash)
            return page
        yield open_page


def _assert_no_requests(forbidden):
    assert forbidden == [], f'Unexpected page requests: {forbidden}'


@pytest.fixture
def shell_payload(colophon, codex_home, tmp_path, monkeypatch):
    monkeypatch.setenv('COLOPHON_HOME', str(tmp_path / 'synthetic-runtime'))
    output = tmp_path / 'synthetic-base.html'
    args = colophon.build_arg_parser().parse_args(['--offline', '--no-open', '--codex-home', str(codex_home), '--output', str(output)])
    assert colophon.run(args, now_ms=FIXTURE_NOW_MS, stderr_tty=False) == 0
    text = re.search(r'<script type="application/json" id="colophon-data">(.*?)</script>', output.read_text(), re.S).group(1)
    return json.loads(text)
