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
    assert tuple(imports.items()) == REACT_19_IMPORTS


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
    require_react_dom_wrapper: bool = True,
) -> str:
    """Validate stable esm.sh React peer-graph boundaries.

    Direct wrappers and compiled React modules are exact and unique. All
    compiled modules must use one CDN target, and ReactDOM modules must carry
    the same peer-externalization marker. Unrelated transitive dependencies
    are deliberately outside this helper's contract.
    """
    required_wrappers = Counter(
        {
            ("/react@19.3.0", ""): 1,
            ("/react@19.3.0/jsx-runtime", ""): 1,
            ("/react-dom@19.3.0/client", "external=react"): 1,
        }
    )
    if require_react_dom_wrapper:
        required_wrappers[("/react-dom@19.3.0", "external=react")] = 1

    wrapper_counts: Counter[tuple[str, str]] = Counter()
    compiled_counts: Counter[str] = Counter()
    compiled_targets: dict[str, str] = {}
    react_dom_external_markers: dict[str, str] = {}
    react_is_seen = False

    for resource_url in resource_urls:
        parsed = urlsplit(resource_url)
        assert (parsed.scheme, parsed.netloc, parsed.fragment) == (
            "https",
            "esm.sh",
            "",
        ), f"unexpected React resource origin: {resource_url}"

        wrapper_signature = (parsed.path, parsed.query)
        if wrapper_signature in required_wrappers:
            wrapper_counts[wrapper_signature] += 1
            continue
        if wrapper_signature == (
            "/react-is@19.3.0",
            "external=react",
        ):
            react_is_seen = True
            wrapper_counts[wrapper_signature] += 1
            continue
        if parsed.query:
            raise AssertionError(f"unexpected React resource: {resource_url}")

        react_match = re.fullmatch(
            r"/react@19\.3\.0/([A-Za-z0-9][A-Za-z0-9._-]*)/"
            r"(react|jsx-runtime)\.mjs",
            parsed.path,
        )
        if react_match:
            target, module_name = react_match.groups()
            compiled_counts[module_name] += 1
            compiled_targets[module_name] = target
            continue

        react_dom_match = re.fullmatch(
            r"/react-dom@19\.3\.0/(X-[A-Za-z0-9_-]+)/"
            r"([A-Za-z0-9][A-Za-z0-9._-]*)/(react-dom|client)\.mjs",
            parsed.path,
        )
        if react_dom_match:
            marker, target, module_name = react_dom_match.groups()
            compiled_counts[module_name] += 1
            compiled_targets[module_name] = target
            react_dom_external_markers[module_name] = marker
            continue

        react_is_match = re.fullmatch(
            r"/react-is@19\.3\.0/(X-[A-Za-z0-9_-]+)/"
            r"([A-Za-z0-9][A-Za-z0-9._-]*)/react-is\.mjs",
            parsed.path,
        )
        if react_is_match:
            react_is_seen = True
            compiled_counts["react-is"] += 1
            compiled_targets["react-is"] = react_is_match.group(2)
            continue

        raise AssertionError(f"unexpected React resource: {resource_url}")

    expected_wrappers = required_wrappers.copy()
    expected_compiled = Counter(
        {"react": 1, "jsx-runtime": 1, "react-dom": 1, "client": 1}
    )
    if react_is_seen:
        expected_wrappers[(
            "/react-is@19.3.0",
            "external=react",
        )] = 1
        expected_compiled["react-is"] = 1

    assert wrapper_counts == expected_wrappers
    assert compiled_counts == expected_compiled
    assert len(set(compiled_targets.values())) == 1
    assert react_dom_external_markers == {
        "react-dom": react_dom_external_markers.get("client"),
        "client": react_dom_external_markers.get("react-dom"),
    }
    return next(iter(compiled_targets.values()))


def capture_browser_errors(page) -> list[str]:
    """Attach strict console/page error listeners to a Playwright page."""
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error"
        else None,
    )
    return errors


@contextmanager
def guard_browser_errors(page, expected: Sequence[str] = ()):
    """Fail a browser-test context on any unexpected console/page error."""
    errors = capture_browser_errors(page)
    try:
        yield errors
    finally:
        assert errors == list(expected), f"Unexpected browser errors: {errors}"


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
