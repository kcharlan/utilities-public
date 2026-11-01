"""Shared test helpers for utility launchers and embedded browser apps."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit


def _install_browser_error_listeners(page):
    errors: list[str] = []

    def record_page_error(error) -> None:
        errors.append(str(error))

    def record_console_error(message) -> None:
        if message.type == "error":
            errors.append(message.text)

    listeners = (
        ("pageerror", record_page_error),
        ("console", record_console_error),
    )
    for event_name, listener in listeners:
        page.on(event_name, listener)
    return errors, listeners


def capture_browser_errors(page) -> list[str]:
    """Attach strict console/page error listeners to a Playwright page."""
    errors, _listeners = _install_browser_error_listeners(page)
    return errors


@contextmanager
def guard_browser_errors(page, expected: Sequence[str] = ()):
    """Fail a browser-test context on any unexpected console/page error."""
    errors, listeners = _install_browser_error_listeners(page)

    def detach() -> None:
        for event_name, listener in listeners:
            page.remove_listener(event_name, listener)

    def browser_failure() -> AssertionError | None:
        if errors == list(expected):
            return None
        return AssertionError(
            f"Unexpected browser errors: {errors}; expected: {list(expected)}"
        )

    try:
        yield errors
    except BaseException as body_error:
        detach()
        captured_browser_failure = browser_failure()
        if captured_browser_failure is not None:
            group_type = (
                ExceptionGroup
                if isinstance(body_error, Exception)
                else BaseExceptionGroup
            )
            raise group_type(
                "Guarded browser body and browser error checks both failed",
                [body_error, captured_browser_failure],
            ) from None
        raise
    else:
        detach()
        captured_browser_failure = browser_failure()
        if captured_browser_failure is not None:
            raise captured_browser_failure


def _probe(app, scope):
    async def run():
        messages = []
        ready = asyncio.Event()

        async def receive():
            if scope['type'] == 'websocket':
                return {'type': 'websocket.connect'}
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(message):
            messages.append(message)
            if message['type'] in ('http.response.start', 'websocket.accept', 'websocket.close'):
                ready.set()

        task = asyncio.create_task(app(scope, receive, send))
        waiter = asyncio.create_task(ready.wait())
        try:
            await asyncio.wait((task, waiter), return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                await task
        finally:
            for pending in (task, waiter):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, waiter, return_exceptions=True)
        return messages

    return asyncio.run(run())


def _probe_scope(kind, path, host, origin, port):
    parsed = urlsplit(path)
    headers = [(b'host', host.encode('latin-1'))]
    if origin is not None:
        headers.append((b'origin', origin.encode('latin-1')))
    return {'type': kind, 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'scheme': 'ws' if kind == 'websocket' else 'http', 'path': parsed.path,
            'raw_path': parsed.path.encode(), 'query_string': parsed.query.encode(),
            'headers': headers, 'server': ('127.0.0.1', port), 'client': ('127.0.0.1', 12345),
            'root_path': ''}


def probe_http(app, method, path, *, host, origin=None, port=8000) -> int:
    scope = _probe_scope('http', path, host, origin, port)
    scope['method'] = method
    return next(m['status'] for m in _probe(app, scope) if m['type'] == 'http.response.start')


def probe_websocket(app, path, *, host, origin=None, port=8000) -> str:
    scope = _probe_scope('websocket', path, host, origin, port)
    scope['subprotocols'] = []
    return next(m['type'].split('.')[1] for m in _probe(app, scope)
                if m['type'] in ('websocket.accept', 'websocket.close'))


def assert_local_server_guard(app, *, get_path='/', post_path, ws_path=None, port=8000):
    host = f'127.0.0.1:{port}'
    assert probe_http(app, 'GET', get_path, host=host, port=port) != 403
    assert probe_http(app, 'GET', get_path, host='evil.example', port=port) == 403
    for origin in (None, 'http://evil.example'):
        assert probe_http(app, 'POST', post_path, host=host, origin=origin, port=port) == 403
        if ws_path is not None:
            assert probe_websocket(app, ws_path, host=host, origin=origin, port=port) == 'close'



class ASGISyncClient:
    """Small synchronous facade over HTTPX's async ASGI transport for tests."""

    def __init__(
        self,
        app,
        *,
        base_url: str = "http://127.0.0.1:8000",
        raise_server_exceptions: bool = True,
    ) -> None:
        self.app = app
        self.base_url = base_url
        self.raise_server_exceptions = raise_server_exceptions
        self._runner: asyncio.Runner | None = None
        self._client = None

    def __enter__(self):
        if self._runner is not None:
            raise RuntimeError("ASGISyncClient cannot be entered more than once")
        self._runner = asyncio.Runner()

        async def open_client():
            import httpx

            transport = httpx.ASGITransport(
                app=self.app,
                raise_app_exceptions=self.raise_server_exceptions,
            )
            client = httpx.AsyncClient(
                transport=transport,
                base_url=self.base_url,
                headers={"Origin": self.base_url},
            )
            await client.__aenter__()
            return client

        self._client = self._runner.run(open_client())
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._runner is None or self._client is None:
            return None
        try:
            self._runner.run(self._client.__aexit__(exc_type, exc_value, traceback))
        finally:
            self._runner.close()
            self._runner = None
            self._client = None
        return None

    def request(self, method: str, url: str, **kwargs):
        if self._runner is not None and self._client is not None:
            return self._runner.run(self._client.request(method, url, **kwargs))

        async def send():
            import httpx

            transport = httpx.ASGITransport(
                app=self.app,
                raise_app_exceptions=self.raise_server_exceptions,
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url=self.base_url,
                headers={"Origin": self.base_url},
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(send())

    def websocket_url(self, path: str) -> str:
        """Build an absolute WebSocket URL for this client's origin."""
        from urllib.parse import urljoin

        url = urlsplit(urljoin(self.base_url.rstrip('/') + '/', path))
        return url._replace(scheme='wss' if url.scheme == 'https' else 'ws').geturl()

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)


def load_launcher(path: str | Path, module_name: str | None = None) -> ModuleType:
    """Load an extensionless launcher without executing its ``__main__`` block."""
    launcher_path = Path(path).resolve()
    if not launcher_path.is_file():
        raise FileNotFoundError(launcher_path)

    resolved_name = module_name or f"{launcher_path.stem}_launcher_{uuid.uuid4().hex}"
    loader = importlib.machinery.SourceFileLoader(resolved_name, str(launcher_path))
    spec = importlib.util.spec_from_file_location(
        resolved_name,
        launcher_path,
        loader=loader,
    )
    if spec is None:
        raise ImportError(f"Could not create an import spec for {launcher_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[resolved_name] = module
    try:
        loader.exec_module(module)
    except BaseException:
        sys.modules.pop(resolved_name, None)
        raise
    return module


def run_launcher(
    path: str | Path,
    *args: str,
    cwd: str | Path | None = None,
    env_overrides: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a launcher with the active test interpreter and a controlled environment."""
    launcher_path = Path(path).resolve()
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(launcher_path), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def assert_launcher_help(
    path: str | Path,
    *,
    cwd: str | Path | None = None,
    env_overrides: Mapping[str, str] | None = None,
    expected_markers: Sequence[str] = ("usage:",),
) -> subprocess.CompletedProcess[str]:
    """Assert the shared subprocess contract for a launcher's ``--help`` command."""
    result = run_launcher(path, "--help", cwd=cwd, env_overrides=env_overrides)
    assert result.returncode == 0, result.stderr
    for marker in expected_markers:
        assert marker in result.stdout
    assert "Traceback" not in result.stderr
    return result


class _BlockedRequests(list[str]):
    def __init__(self, allowed_origins: Sequence[str]) -> None:
        super().__init__()
        self.allowed_origins = frozenset(allowed_origins)


def block_external_requests(context, allowed_origins: Sequence[str] = ()) -> list[str]:
    """Block external requests and return the URLs that were blocked."""
    blocked = _BlockedRequests(allowed_origins)

    def route_request(route):
        url = route.request.url
        parsed = urlsplit(url)
        if parsed.scheme in {"file", "data", "blob", "about"} or (
            parsed.scheme in {"http", "https"}
            and f"{parsed.scheme}://{parsed.netloc}" in blocked.allowed_origins
        ):
            route.continue_()
        else:
            blocked.append(url)
            route.abort()

    context.route("**/*", route_request)
    return blocked


def assert_no_external_resources(page, blocked: list[str]) -> None:
    """Check both intercepted requests and the browser's resource timings."""
    resources = page.evaluate("""() => performance.getEntriesByType('resource')
        .map(entry => entry.name)
        .filter(url => /^https?:/i.test(url) && new URL(url).origin !== location.origin)""")
    allowed = getattr(blocked, "allowed_origins", ())
    resources = [
        url for url in resources
        if f"{urlsplit(url).scheme}://{urlsplit(url).netloc}" not in allowed
    ]
    assert not blocked and not resources, f"External resources: blocked={blocked}, timed={resources}"


# A host that starts with an interpolation is the page's own, as in `ws://${location.host}/ws`.
_REMOTE_URL = r"(?:https?:)?//(?!\$\{)"
_QUOTED_REMOTE = rf"['\"`]\s*{_REMOTE_URL}"
# The codemod writes attributes in htm templates as attr=${"literal"} or attr=${`literal`}.
_REMOTE_VALUE = rf"(?:\$\{{\s*)?(?:{_QUOTED_REMOTE}|https?://)"
_RETIRED_TYPES = r"(?:importmap|text/babel|text/tailwindcss)"
_REFRESH_URL = rf"\burl\s*=\s*['\"]?\s*{_REMOTE_URL}"
# Script and style text can build markup and load resources itself, so these run on
# its raw text. Comments stay in: skipping them needs a real lexer, and a comment
# matches only if it holds commented-out loading code.
_OFFLINE_CODE_PATTERNS = (
    rf"<\s*(?!a\b|area\b)[a-z][\w:-]*\b[^>]*\b(?:xlink:)?href\s*=\s*{_REMOTE_VALUE}",
    rf"\b(?:src|srcset|poster)\s*[:=]\s*{_REMOTE_VALUE}",
    rf"\bbackground\s*=\s*{_REMOTE_VALUE}",
    rf"<\s*meta\b(?=[^>]*\bhttp-equiv\s*=\s*\W*refresh\b)[^>]*{_REFRESH_URL}",
    rf"\b(?:import|export)\b(?:[^;\n]*?\bfrom)?\s*{_QUOTED_REMOTE}",
    rf"\bimport\s*\(\s*{_QUOTED_REMOTE}",
    rf"\b(?:fetch|Worker|SharedWorker|EventSource|sendBeacon)\s*\(\s*{_QUOTED_REMOTE}",
    rf"\bWebSocket\s*\(\s*['\"`]\s*(?:(?:https?|wss?):)?//(?!\$\{{)",
    rf"\.open\s*\(\s*['\"`][a-z]+['\"`]\s*,\s*{_QUOTED_REMOTE}",
    rf"\bsetAttribute(?:NS)?\s*\([^)]*?,\s*{_QUOTED_REMOTE}",
    rf"\bimportScripts\s*\([^)]*?{_QUOTED_REMOTE}",
    rf"\burl\s*\(\s*['\"`]?\s*{_REMOTE_URL}",
    rf"@import\s+(?:url\s*\(\s*)?['\"`]?\s*{_REMOTE_URL}",
    rf"\btype\s*=\s*['\"`]?{_RETIRED_TYPES}\b",
)


class _OfflineMarkup(HTMLParser):
    """Check live markup attributes and collect script and style text."""

    def __init__(self) -> None:
        super().__init__()
        self.violations: list[str] = []
        self.code: list[str] = []
        self._in_code = False

    @staticmethod
    def _rejected(tag: str, name: str, value: str) -> bool:
        if name == "type":
            return bool(re.fullmatch(_RETIRED_TYPES, value, re.I))
        if name == "srcset":
            return bool(re.search(rf"(?:^|,)\s*{_REMOTE_URL}", value, re.I))
        if name in {"src", "poster", "background"} or (name == "data" and tag == "object") or (
            name in {"href", "xlink:href"} and tag not in {"a", "area"}
        ):
            return bool(re.match(_REMOTE_URL, value, re.I))
        return False

    def handle_starttag(self, tag, attrs) -> None:
        for name, value in attrs:
            value = (value or "").strip()
            if name == "style":
                self.code.append(value)
            elif self._rejected(tag, name, value):
                self.violations.append(f"<{tag} {name}={value!r}>")
        fields = {name: (value or "") for name, value in attrs}
        if (tag == "meta" and fields.get("http-equiv", "").strip().lower() == "refresh"
                and re.search(_REFRESH_URL, fields.get("content", ""), re.I)):
            self.violations.append(f"<meta refresh {fields['content']!r}>")
        self._in_code = tag in {"script", "style"}

    def handle_endtag(self, tag) -> None:
        self._in_code = False

    def handle_data(self, data) -> None:
        if self._in_code:
            self.code.append(data)


def assert_offline_page_source(html: str) -> None:
    """Reject remote resources and retired runtime compilers in a page's source."""
    markup = _OfflineMarkup()
    markup.feed(html)
    markup.close()
    code = "".join(markup.code)
    found = markup.violations + [
        match.group(0)[:120]
        for pattern in _OFFLINE_CODE_PATTERNS
        for match in re.finditer(pattern, code, re.I)
    ]
    assert not found, f"Offline source contains: {found}"


def assert_frontend_vendor_current(path: str | Path) -> None:
    script = Path(__file__).resolve().parent / "sync_frontend_vendor.mjs"
    result = subprocess.run(["node", str(script), "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, f"{path}: {result.stdout}{result.stderr}"


def assert_launcher_compiles_cleanly(path: str | Path) -> None:
    import warnings

    path = Path(path)
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        warnings.simplefilter("error", DeprecationWarning)
        compile(path.read_bytes(), str(path), "exec")


def assert_exact_text(locator, expected: str) -> None:
    """Compare raw DOM text; Playwright's to_have_text and inner_text normalize whitespace."""
    actual = locator.evaluate("element => element.textContent")
    assert actual == expected, f"Expected exact text {expected!r}, got {actual!r}"


def assert_fonts_loaded(page, families: Sequence[str]) -> None:
    """Require a loaded FontFace per family; computed styles pass on the CSS stack alone."""
    faces = page.evaluate(r"""async (families) => {
        await document.fonts.ready;
        const faces = [...document.fonts];
        return Object.fromEntries(families.map(family => [family, faces
            .filter(face => face.family.replace(/^['"]|['"]$/g, '') === family)
            .map(face => face.status)]));
    }""", list(families))
    failed = {
        family: statuses for family, statuses in faces.items()
        if "loaded" not in statuses or "error" in statuses
    }
    assert not failed, f"Fonts without a loaded FontFace: {failed}"


def assert_classes_styled(page, ignore: Sequence[str] = ()) -> None:
    missing = page.evaluate(r"""(ignore) => {
        const selectors = [];
        function visit(rules) {
            for (const rule of rules) {
                if (rule.selectorText) selectors.push(rule.selectorText);
                if (rule.cssRules) visit(rule.cssRules);
            }
        }
        for (const sheet of document.styleSheets) visit(sheet.cssRules);
        const tokens = new Set();
        for (const element of document.querySelectorAll('[class]'))
            for (const token of element.classList) tokens.add(token);
        function containsClass(selector, token) {
            const needle = '.' + CSS.escape(token);
            let offset = -1;
            while ((offset = selector.indexOf(needle, offset + 1)) !== -1) {
                const next = selector[offset + needle.length];
                if (next === undefined || !/[\w\-\\\u0080-\uFFFF]/.test(next)) return true;
            }
            return false;
        }
        return [...tokens].filter(token => !ignore.includes(token) &&
            !selectors.some(selector => containsClass(selector, token)));
    }""", list(ignore))
    assert not missing, f"Unstyled classes: {missing}"
