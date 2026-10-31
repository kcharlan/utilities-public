from pathlib import Path

import pytest

from tools import testkit


class Context:
    def route(self, pattern, callback):
        self.callback = callback


class Route:
    def __init__(self, url):
        self.request = type('Request', (), {'url': url})()
        self.action = None

    def continue_(self):
        self.action = 'continue'

    def abort(self):
        self.action = 'abort'


class Page:
    def __init__(self, result):
        self.result = result

    def evaluate(self, *args):
        if len(args) > 1:
            return [token for token in self.result if token not in args[1]]
        return self.result


def test_block_allows_listed_origin_file_data_blob_and_about():
    context = Context()
    blocked = testkit.block_external_requests(context, ['http://localhost:123'])
    for url in ['file:///a', 'data:text/plain,x', 'blob:abc', 'about:blank', 'http://localhost:123/a']:
        route = Route(url)
        context.callback(route)
        assert route.action == 'continue'
    assert blocked == []


def test_block_aborts_and_records_other_http_requests():
    context = Context()
    blocked = testkit.block_external_requests(context)
    route = Route('https://example.invalid/x')
    context.callback(route)
    assert route.action == 'abort'
    assert blocked == ['https://example.invalid/x']


def test_no_external_resources_fails_on_recorded_or_timed_external_entries():
    with pytest.raises(AssertionError):
        testkit.assert_no_external_resources(Page([]), ['https://example.invalid'])
    with pytest.raises(AssertionError):
        testkit.assert_no_external_resources(Page(['https://example.invalid']), [])


@pytest.mark.parametrize('html', ['<script src="https://example.invalid/x"></script>', '<link href="https://example.invalid/x">', '<script>import x from "https://example.invalid/x"</script>', '<style>x{background:url(https://example.invalid/x)}</style>'])
def test_offline_source_rejects_external_script_link_import_and_css_url(html):
    with pytest.raises(AssertionError):
        testkit.assert_offline_page_source(html)


@pytest.mark.parametrize('kind', ['importmap', 'text/babel', 'text/tailwindcss'])
def test_offline_source_rejects_importmap_text_babel_and_text_tailwindcss(kind):
    with pytest.raises(AssertionError):
        testkit.assert_offline_page_source(f'<script type="{kind}"></script>')


def test_offline_source_allows_tailwind_license_comment():
    testkit.assert_offline_page_source('<style>/*! tailwindcss v4 | MIT License | https://tailwindcss.com */</style>')


def test_offline_source_allows_svg_namespace_and_anchor_hrefs():
    testkit.assert_offline_page_source('<svg xmlns="http://www.w3.org/2000/svg"></svg><a href="https://example.invalid">link</a>')


def test_vendor_current_reports_the_stale_file(tmp_path):
    path = tmp_path / 'missing.py'
    path.write_text('x')
    with pytest.raises(AssertionError, match='missing.py'):
        testkit.assert_frontend_vendor_current(path)


def test_compiles_cleanly_fails_on_invalid_escape_sequence(tmp_path):
    path = tmp_path / 'bad.py'
    path.write_text('x = "\\q"\n')
    with pytest.raises((SyntaxError, SyntaxWarning)):
        testkit.assert_launcher_compiles_cleanly(path)


def test_classes_styled_reports_unstyled_tokens_and_honors_ignore():
    with pytest.raises(AssertionError, match='missing'):
        testkit.assert_classes_styled(Page(['missing']))
    testkit.assert_classes_styled(Page(['missing']), ignore=['missing'])




def test_offline_source_rejects_unquoted_remote_resource():
    with pytest.raises(AssertionError):
        testkit.assert_offline_page_source('<script src=https://example.invalid/x></script>')


def test_classes_styled_does_not_confuse_class_name_prefixes():
    import json
    import subprocess

    class JavaScriptPage:
        def evaluate(self, script, ignore):
            program = '''
                globalThis.CSS = {escape: x => x};
                globalThis.document = {
                    styleSheets: [{cssRules: [{selectorText: '.foobar'}]}],
                    querySelectorAll: () => [{classList: ['foo']}]
                };
                const run = (%s);
                console.log(JSON.stringify(run(%s)));
            ''' % (script, json.dumps(ignore))
            result = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
            return json.loads(result.stdout)

    with pytest.raises(AssertionError, match='foo'):
        testkit.assert_classes_styled(JavaScriptPage())


def test_no_external_resources_allows_explicitly_allowed_timed_origin():
    context = Context()
    blocked = testkit.block_external_requests(context, ['http://localhost:123'])
    testkit.assert_no_external_resources(Page(['http://localhost:123/asset.js']), blocked)
