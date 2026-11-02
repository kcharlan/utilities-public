import json
import re
from urllib.request import urlopen

from playwright.sync_api import expect
from test_e2e import server, _load_synthetic
from tools.testkit import guard_browser_errors


def test_json_markup_is_literal_in_body_and_websocket(server, page, minimal_har_dict):
    value = '\\"<img src=x onerror="window.syntheticExecuted=1">'
    key = '<b>x</b> & ${y} `value` {{X}} &nbsp;'
    expected = {key: key, 'synthetic': value}
    body = json.dumps(expected)
    entry = minimal_har_dict['log']['entries'][0]
    entry['response']['content'] = {'size': len(body), 'mimeType': 'application/json', 'text': body}
    entry['_webSocketMessages'] = [{'type': 'receive', 'time': 0, 'opcode': 1, 'data': body}]
    with guard_browser_errors(page):
        _load_synthetic(page, server, minimal_har_dict)
        page.get_by_text('/api/data', exact=False).first.click()
        page.get_by_role('button', name='Response', exact=False).first.click()
        page.get_by_role('button', name='Body', exact=False).click()
        pre = page.locator('pre')
        expect(pre).to_contain_text('<img')
        assert json.loads(pre.inner_text()) == expected
        assert pre.locator('img').count() == 0
        assert set(pre.locator('*').evaluate_all('elements => elements.map(element => element.tagName)')) <= {'SPAN', 'INPUT'}
        page.get_by_role('button', name='WebSocket', exact=False).click()
        page.get_by_role('button', name=re.compile('RECV')).click()
        pre = page.locator('pre')
        expect(pre).to_contain_text('<img')
        assert json.loads(pre.inner_text()) == expected
        assert pre.locator('img').count() == 0
        assert set(pre.locator('*').evaluate_all('elements => elements.map(element => element.tagName)')) <= {'SPAN', 'INPUT'}
        assert page.evaluate('window.syntheticExecuted') is None


def test_page_has_csp_and_runs_inline_assets(server, page):
    with urlopen(server + '/api/status', timeout=2) as health:
        assert health.status == 200
        assert json.load(health)['loaded'] is True
    with guard_browser_errors(page):
        response = page.goto(server)
        assert 'content-security-policy' in response.headers
        expect(page.get_by_role('button', name='Security')).to_be_visible()
