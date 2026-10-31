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


class ASGISyncClient:
    """Small synchronous facade over HTTPX's async ASGI transport for tests."""

    def __init__(
        self,
        app,
        *,
        base_url: str = "http://testserver",
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
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(send())

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


def assert_offline_page_source(html: str) -> None:
    """Reject remote executable resources and retired runtime compilers."""
    source = re.sub(r"/\*.*?\*/|<!--.*?-->", "", html, flags=re.S)
    patterns = (
        r"<\s*(?:script|link)\b[^>]*\b(?:src|href)\s*=\s*['\"]?(?:https?:)?//",
        r"\b(?:import|export)\s+(?:[^;\n]*?\s+from\s+)?['\"](?:https?:)?//",
        r"\bimport\s*\(\s*['\"](?:https?:)?//",
        r"\b(?:url\s*\(|@import\s+)(?:\s*['\"]?)?(?:https?:)?//",
        r"\btype\s*=\s*['\"](?:importmap|text/babel|text/tailwindcss)['\"]",
    )
    for pattern in patterns:
        assert not re.search(pattern, source, re.I), f"Offline source contains {pattern}"


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
