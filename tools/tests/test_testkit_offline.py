import json
from pathlib import Path
import subprocess

import pytest

from tools import testkit


class FakePage:
    def __init__(self):
        self.listeners = {"pageerror": [], "console": []}

    def on(self, event_name, listener):
        self.listeners[event_name].append(listener)

    def remove_listener(self, event_name, listener):
        self.listeners[event_name].remove(listener)

    def emit(self, event_name, payload):
        for listener in tuple(self.listeners[event_name]):
            listener(payload)


class FakeConsoleMessage:
    def __init__(self, message_type, text):
        self.type = message_type
        self.text = text


def test_browser_error_guard_detaches_listeners_after_success():
    page = FakePage()
    existing_listener = lambda _payload: None
    page.on("console", existing_listener)
    with testkit.guard_browser_errors(page):
        assert len(page.listeners["pageerror"]) == 1
        assert len(page.listeners["console"]) == 2
    assert page.listeners == {
        "pageerror": [],
        "console": [existing_listener],
    }


def test_browser_error_guard_reports_browser_errors():
    page = FakePage()
    with pytest.raises(AssertionError, match="Unexpected browser errors"):
        with testkit.guard_browser_errors(page):
            page.emit("pageerror", RuntimeError("browser failed"))
    assert page.listeners == {"pageerror": [], "console": []}


def test_browser_error_guard_preserves_body_exception_and_traceback():
    page = FakePage()
    body_error = RuntimeError("body failed")

    def raise_body_error():
        raise body_error

    with pytest.raises(RuntimeError) as captured:
        with testkit.guard_browser_errors(page):
            raise_body_error()
    assert captured.value is body_error
    traceback_names = []
    traceback = captured.tb
    while traceback is not None:
        traceback_names.append(traceback.tb_frame.f_code.co_name)
        traceback = traceback.tb_next
    assert "raise_body_error" in traceback_names
    assert page.listeners == {"pageerror": [], "console": []}


def test_browser_error_guard_preserves_body_and_browser_failures():
    page = FakePage()
    body_error = RuntimeError("body failed")
    with pytest.raises(ExceptionGroup) as captured:
        with testkit.guard_browser_errors(page):
            page.emit("console", FakeConsoleMessage("error", "browser failed"))
            raise body_error
    assert captured.value.exceptions[0] is body_error
    assert isinstance(captured.value.exceptions[1], AssertionError)
    assert page.listeners == {"pageerror": [], "console": []}


def test_browser_error_guard_can_reuse_page_without_listener_leaks():
    page = FakePage()
    for _ in range(2):
        with testkit.guard_browser_errors(page):
            page.emit("console", FakeConsoleMessage("log", "allowed"))
        assert page.listeners == {"pageerror": [], "console": []}


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


@pytest.mark.parametrize('html', [
    pytest.param('<script>a="/*"</script><script src="https://example.invalid/x"></script><script>b="*/"</script>', id='css-comment-strings'),
    pytest.param('<script>a="<!--"</script><script src="https://example.invalid/x"></script><script>b="-->"</script>', id='html-comment-strings'),
    pytest.param('<script>import(`https://example.invalid/x.js`)</script>', id='template-literal-import'),
    pytest.param('<script>import(`//example.invalid/x.js`)</script>', id='template-literal-relative-scheme-import'),
    pytest.param('<script type=importmap>{}</script>', id='unquoted-importmap'),
    pytest.param('<script type=text/babel></script>', id='unquoted-babel'),
    pytest.param('<img src="https://example.invalid/x.png">', id='img'),
    pytest.param('<img src=//example.invalid/x.png>', id='img-unquoted'),
    pytest.param('<img srcset="data:image/png;base64,AA 1x, https://example.invalid/x.png 2x">', id='img-srcset'),
    pytest.param('<iframe src="https://example.invalid/x"></iframe>', id='iframe'),
    pytest.param('<script>fetch("https://example.invalid/x")</script>', id='fetch'),
    pytest.param('<script>fetch(`https://example.invalid/${id}`)</script>', id='fetch-template-literal'),
    pytest.param('<script>importScripts("local.js", "https://example.invalid/x.js")</script>', id='importScripts'),
    pytest.param('<script>html`<img src="https://example.invalid/x.png" />`</script>', id='img-in-htm-template'),
    pytest.param('<script>html`<iframe src=${x} /><iframe src="https://example.invalid/x" />`</script>', id='iframe-in-htm-template'),
    pytest.param('<script>html`<img src=${"https://example.invalid/x.png"} />`</script>', id='img-htm-literal'),
    pytest.param('<script>html`<script src=${"//example.invalid/x.js"}>`</script>', id='script-htm-literal-relative-scheme'),
    pytest.param('<script>html`<link href=${"https://example.invalid/x.css"} />`</script>', id='link-htm-literal'),
    pytest.param('<script>html`<iframe src=${`https://example.invalid/x`} />`</script>', id='iframe-htm-template-literal'),
    pytest.param('<script>html`<img src=${`https://example.invalid/${id}.png`} />`</script>', id='img-htm-template-with-path-value'),
    pytest.param('<script>html`<image href="https://example.invalid/x.png" />`</script>', id='svg-image-href'),
    pytest.param('<script>html`<image href=${"https://example.invalid/x.png"} />`</script>', id='svg-image-href-htm-literal'),
    pytest.param('<script>html`<use xlink:href="https://example.invalid/x.svg#a" />`</script>', id='xlink-href'),
    pytest.param('<script>html`<meta http-equiv=refresh content="0;url=https://example.invalid/x" />`</script>', id='meta-refresh-in-code'),
    pytest.param('<script>html`<meta content="0; url=//example.invalid/x" http-equiv="Refresh" />`</script>', id='meta-refresh-in-code-reversed'),
    pytest.param('<meta http-equiv="refresh" content="0;url=https://example.invalid/x">', id='meta-refresh'),
    pytest.param('<body background="https://example.invalid/x.png"></body>', id='background'),
    pytest.param('<script>html`<body background=https://example.invalid/x.png>`</script>', id='background-in-code'),
    pytest.param('<script>html`<td background=${"https://example.invalid/x.png"} />`</script>', id='background-htm-literal'),
    pytest.param('<script>node.setAttribute("src", "https://example.invalid/x.png")</script>', id='setAttribute'),
    pytest.param('<script>node.setAttributeNS(null, "href", `https://example.invalid/x.png`)</script>', id='setAttributeNS'),
    pytest.param('<script>xhr.open("GET", "https://example.invalid/x")</script>', id='xhr-open'),
    pytest.param("<script>xhr.open('post', `//example.invalid/x`, true)</script>", id='xhr-open-template-literal'),
    pytest.param('<script>navigator.sendBeacon("https://example.invalid/x", data)</script>', id='sendBeacon'),
    pytest.param('<script>new WebSocket("wss://example.invalid/x")</script>', id='websocket'),
    pytest.param('<script>new WebSocket(`ws://example.invalid/${id}`)</script>', id='websocket-template-literal'),
    pytest.param('<style>@import "https://example.invalid/x.css";</style>', id='css-import'),
    pytest.param('<style>@import url(https://example.invalid/x.css);</style>', id='css-import-url'),
    pytest.param('<div style="background:url(https://example.invalid/x.png)"></div>', id='inline-style-url'),
])
def test_offline_source_rejects_bypasses(html):
    with pytest.raises(AssertionError, match='Offline source contains'):
        testkit.assert_offline_page_source(html)


@pytest.mark.parametrize('html', [
    pytest.param('<!-- <script src="https://example.invalid/x"></script> --><p>ok</p>', id='markup-comment'),
    pytest.param('<script>const a = "https://example.invalid/x"; fetch("/api/data")</script>', id='plain-url-string'),
    pytest.param('<script>// see https://example.invalid/docs\nimport("./local.js")</script>', id='comment-url'),
    pytest.param('<pre>import x from "https://example.invalid/x"</pre>', id='page-text'),
    pytest.param('<img src="data:image/png;base64,AA"><script src="/static/x.js"></script>', id='local-resources'),
    pytest.param('<script>html`<a href="https://example.invalid/x">link</a>`</script>', id='link-in-htm-template'),
    pytest.param('<script>html`<a href=${"https://example.invalid/x"}>link</a>`</script>', id='link-htm-literal'),
    pytest.param('<script>new WebSocket(`ws://${location.host}/ws`)</script>', id='same-host-websocket'),
    pytest.param('<script>new WebSocket(`${scheme}//${location.host}/ws`)</script>', id='same-host-websocket-scheme'),
    pytest.param('<script>fetch(`http://${location.host}/api/data`)</script>', id='same-host-fetch'),
    pytest.param('<script>html`<img src=${`http://${location.host}/x.png`} />`</script>', id='same-host-htm-template'),
    pytest.param('<script>xhr.open("GET", `http://${location.host}/api/data`)</script>', id='same-host-xhr'),
    pytest.param('<script>window.open("https://example.invalid/x", "_blank")</script>', id='link-in-new-tab'),
    pytest.param('<script>node.setAttributeNS("http://www.w3.org/1999/xlink", "href", "#local")</script>', id='svg-namespace'),
    pytest.param('<meta http-equiv="refresh" content="60">', id='meta-refresh-without-a-url'),
    pytest.param('<meta http-equiv="refresh" content="0;url=/local">', id='meta-refresh-to-the-same-host'),
    pytest.param('<meta name="description" content="url=https://example.invalid/x">', id='other-meta'),
    pytest.param('<script>const style = {background: "https://example.invalid/x"}</script>', id='background-style-key'),
])
def test_offline_source_allows_inert_text_and_local_resources(html):
    testkit.assert_offline_page_source(html)


def embedded_pages():
    root = Path(__file__).resolve().parents[2]
    found = subprocess.run(
        ['git', '-C', str(root), 'grep', '-lzE', '^[[:space:]]*(# |<!-- )frontend-vendor:begin ', '--', ':!tools'],
        capture_output=True, text=True, check=True,
    ).stdout
    return [root / name for name in found.split('\0') if name]


def test_offline_source_accepts_every_embedded_page():
    pages = embedded_pages()
    # A floor, so a broken search fails here and adding a page doesn't.
    assert len(pages) >= 14
    for page in pages:
        testkit.assert_offline_page_source(page.read_text())


def test_vendor_current_reports_a_missing_region(tmp_path):
    path = tmp_path / 'unmarked.py'
    path.write_text('x')
    with pytest.raises(AssertionError, match='unmarked.py: no frontend-vendor region'):
        testkit.assert_frontend_vendor_current(path)


def test_vendor_current_reports_the_stale_file(tmp_path):
    path = tmp_path / 'marked.py'
    path.write_text('# frontend-vendor:begin kit\n# frontend-vendor:end\n')
    with pytest.raises(AssertionError, match='marked.py: stale frontend-vendor region'):
        testkit.assert_frontend_vendor_current(path)
    tool = Path(__file__).resolve().parents[1] / 'sync_frontend_vendor.mjs'
    subprocess.run(['node', str(tool), str(path)], capture_output=True, check=True)
    testkit.assert_frontend_vendor_current(path)


def test_compiles_cleanly_fails_on_invalid_escape_sequence(tmp_path):
    path = tmp_path / 'bad.py'
    path.write_text('x = "\\q"\n')
    with pytest.raises((SyntaxError, SyntaxWarning)):
        testkit.assert_launcher_compiles_cleanly(path)


def test_exact_text_rejects_padding_that_normalized_matchers_hide():
    testkit.assert_exact_text(Page('Copy'), 'Copy')
    with pytest.raises(AssertionError, match="' Copy '"):
        testkit.assert_exact_text(Page(' Copy '), 'Copy')



def test_offline_source_rejects_unquoted_remote_resource():
    with pytest.raises(AssertionError):
        testkit.assert_offline_page_source('<script src=https://example.invalid/x></script>')


class FontPage:
    """Run the helper's page script in Node against synthetic font faces."""

    def __init__(self, faces):
        self.faces = faces

    def evaluate(self, script, families):
        program = '''
            globalThis.document = {fonts: Object.assign(%s, {ready: Promise.resolve()})};
            (%s)(%s).then(result => console.log(JSON.stringify(result)));
        ''' % (json.dumps(self.faces), script, json.dumps(families))
        result = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)


def test_fonts_loaded_accepts_a_loaded_face_with_or_without_quotes():
    testkit.assert_fonts_loaded(FontPage([
        {'family': '"SYNTHETIC Sans"', 'status': 'loaded'},
        {'family': 'SYNTHETIC Mono', 'status': 'unloaded'},
        {'family': 'SYNTHETIC Mono', 'status': 'loaded'},
    ]), ['SYNTHETIC Sans', 'SYNTHETIC Mono'])


@pytest.mark.parametrize('faces', [
    pytest.param([], id='no-face-only-a-css-stack'),
    pytest.param([{'family': 'SYNTHETIC Sans', 'status': 'unloaded'}], id='never-used'),
    pytest.param([{'family': 'SYNTHETIC Sans', 'status': 'error'}], id='failed'),
    pytest.param([
        {'family': 'SYNTHETIC Sans', 'status': 'loaded'},
        {'family': 'SYNTHETIC Sans', 'status': 'error'},
    ], id='one-weight-failed'),
    pytest.param([{'family': 'SYNTHETIC Mono', 'status': 'loaded'}], id='other-family'),
])
def test_fonts_loaded_rejects_a_family_without_a_loaded_face(faces):
    with pytest.raises(AssertionError, match='SYNTHETIC Sans'):
        testkit.assert_fonts_loaded(FontPage(faces), ['SYNTHETIC Sans'])


def test_classes_styled_does_not_confuse_class_name_prefixes():
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
    testkit.assert_classes_styled(JavaScriptPage(), ignore=['foo'])


def test_no_external_resources_allows_explicitly_allowed_timed_origin():
    context = Context()
    blocked = testkit.block_external_requests(context, ['http://localhost:123'])
    testkit.assert_no_external_resources(Page(['http://localhost:123/asset.js']), blocked)


def test_asgi_probes_and_guard_assertion():
    from tools.local_server_guard import LocalOriginGuard
    seen = []
    async def app(scope, receive, send):
        seen.append(scope)
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.accept'})
        else:
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})
    guarded = LocalOriginGuard(app)
    assert testkit.probe_http(guarded, 'GET', '/x?a=1', host='127.0.0.1:8000') == 200
    assert seen[-1]['path'] == '/x' and seen[-1]['query_string'] == b'a=1'
    assert testkit.probe_websocket(guarded, '/ws', host='localhost:8000', origin='http://localhost:8000') == 'accept'
    testkit.assert_local_server_guard(guarded, get_path='/x', post_path='/write', ws_path='/ws')
    assert all(s.get('method') != 'POST' for s in seen)


@pytest.mark.parametrize('protection', ['none', 'host-only', 'http-only'])
def test_guard_assertion_fails_on_unguarded_apps(protection):
    from tools.local_server_guard import LocalOriginGuard

    async def raw_app(scope, receive, send):
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.accept'})
        else:
            host = dict(scope['headers']).get(b'host')
            status = 403 if protection == 'host-only' and host == b'evil.example' else 200
            await send({'type': 'http.response.start', 'status': status, 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})

    guarded_http = LocalOriginGuard(raw_app)

    async def app(scope, receive, send):
        if protection == 'http-only' and scope['type'] == 'http':
            await guarded_http(scope, receive, send)
        else:
            await raw_app(scope, receive, send)

    with pytest.raises(AssertionError):
        testkit.assert_local_server_guard(app, get_path='/x', post_path='/write', ws_path='/ws')


def test_asgi_sync_client_defaults_and_websocket_url():
    client = testkit.ASGISyncClient(None)
    assert client.base_url == 'http://127.0.0.1:8000'
    assert client.websocket_url('/ws?x=1') == 'ws://127.0.0.1:8000/ws?x=1'
    assert testkit.ASGISyncClient(None, base_url='https://localhost:123').websocket_url('/ws') == 'wss://localhost:123/ws'


def test_asgi_sync_client_sends_origin_in_both_lifecycles(monkeypatch):
    import sys
    from types import SimpleNamespace
    captured = []
    class Client:
        def __init__(self, **kwargs):
            captured.append(kwargs)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def request(self, *args, **kwargs):
            return 200
    monkeypatch.setitem(sys.modules, 'httpx', SimpleNamespace(ASGITransport=lambda **kw: kw, AsyncClient=Client))
    client = testkit.ASGISyncClient(None)
    assert client.get('/') == 200
    with client:
        assert client.get('/') == 200
    assert [item['headers'] for item in captured] == [{'Origin': 'http://127.0.0.1:8000'}] * 2


def test_websocket_probe_returns_after_accept_for_live_connection():
    import asyncio
    async def app(scope, receive, send):
        await send({'type': 'websocket.accept'})
        await asyncio.Event().wait()
    assert testkit.probe_websocket(app, '/ws', host='localhost:8000', origin='http://localhost:8000') == 'accept'


def test_websocket_probe_blocks_after_connect_and_cancels_live_receive():
    import sys
    program = '''
from tools.testkit import probe_websocket

async def app(scope, receive, send):
    try:
        assert await receive() == {"type": "websocket.connect"}
        await send({"type": "websocket.accept"})
        message = await receive()
        raise AssertionError(f"unexpected second event: {message}")
    finally:
        print("cleaned up")

assert probe_websocket(app, "/ws", host="localhost:8000", origin="http://localhost:8000") == "accept"
'''
    result = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True, timeout=3)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'cleaned up'
