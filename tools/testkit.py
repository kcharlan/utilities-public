"""Shared helpers for tests that import extensionless Python launchers."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType


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
