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
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Literal
from urllib.parse import urlsplit


REACT_19_IMPORTS = (
    ("react", "https://esm.sh/react@19.3.0"),
    ("react/jsx-runtime", "https://esm.sh/react@19.3.0/jsx-runtime"),
    (
        "react/jsx-dev-runtime",
        "https://esm.sh/react@19.3.0/jsx-dev-runtime",
    ),
    ("react-dom", "https://esm.sh/react-dom@19.3.0?external=react"),
    (
        "react-dom/client",
        "https://esm.sh/react-dom@19.3.0/client?external=react",
    ),
    ("react-is", "https://esm.sh/react-is@19.3.0?external=react"),
)


def assert_react_19_import_map(imports: Mapping[str, str]) -> None:
    """Require the shared six-entry React 19 import-map contract exactly."""
    assert dict(imports) == dict(REACT_19_IMPORTS)


def is_react_package_resource(resource_url: str) -> bool:
    """Match bare and versioned React-family package URL path segments."""
    path = urlsplit(resource_url).path
    return re.search(
        r"(?:^|/)(?:react|react-dom|react-is)(?:@[^/]+)?(?:/|$)",
        path,
    ) is not None


def assert_react_esm_graph(
    resource_urls: Sequence[str],
    *,
    react_dom_wrapper_policy: Literal[
        "required",
        "forbidden",
        "optional",
    ] = "required",
) -> None:
    """Validate stable esm.sh React peer-graph boundaries.

    Direct wrappers are exact and unique. Generated resources must stay on
    the selected package versions, but their CDN-owned route layout is opaque.
    Unrelated transitive dependencies are deliberately outside this helper's
    contract.
    """
    if react_dom_wrapper_policy not in {"required", "forbidden", "optional"}:
        raise ValueError(
            "react_dom_wrapper_policy must be required, forbidden, or optional"
        )

    resources = list(resource_urls)
    assert len(resources) == len(set(resources)), "duplicate React resource request"

    wrapper_queries = {
        "/react@19.3.0": "",
        "/react@19.3.0/jsx-runtime": "",
        "/react@19.3.0/jsx-dev-runtime": "",
        "/react-dom@19.3.0": "external=react",
        "/react-dom@19.3.0/client": "external=react",
        "/react-is@19.3.0": "external=react",
    }
    wrapper_counts: Counter[str] = Counter()
    generated_packages: set[str] = set()

    for resource_url in resources:
        parsed = urlsplit(resource_url)
        assert (parsed.scheme, parsed.netloc, parsed.fragment) == (
            "https",
            "esm.sh",
            "",
        ), f"unexpected React resource origin: {resource_url}"

        if parsed.path in wrapper_queries:
            assert parsed.query == wrapper_queries[parsed.path], (
                f"unexpected direct React wrapper query: {resource_url}"
            )
            wrapper_counts[parsed.path] += 1
            continue

        package_match = re.match(
            r"^/(react(?:-dom|-is)?)@([^/]+)(?:/|$)",
            parsed.path,
        )
        assert package_match is not None, (
            f"unexpected React package resource: {resource_url}"
        )
        package, version = package_match.groups()
        assert version == "19.3.0", f"unexpected React version: {resource_url}"
        assert parsed.query == "", (
            f"unexpected generated React resource query: {resource_url}"
        )
        generated_packages.add(package)

    assert wrapper_counts["/react@19.3.0"] == 1
    assert wrapper_counts["/react@19.3.0/jsx-runtime"] == 1
    assert wrapper_counts["/react@19.3.0/jsx-dev-runtime"] == 0
    assert wrapper_counts["/react-dom@19.3.0/client"] == 1
    react_is_wrapper_present = wrapper_counts["/react-is@19.3.0"] == 1
    assert react_is_wrapper_present == ("react-is" in generated_packages)

    react_dom_wrapper_count = wrapper_counts["/react-dom@19.3.0"]
    if react_dom_wrapper_policy == "required":
        assert react_dom_wrapper_count == 1
    elif react_dom_wrapper_policy == "forbidden":
        assert react_dom_wrapper_count == 0
    else:
        assert react_dom_wrapper_count in {0, 1}


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
