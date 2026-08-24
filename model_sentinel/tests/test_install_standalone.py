from __future__ import annotations

import json
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

from tests.browse_fixtures import build_fixture_db


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _copy_installer_project(tmp_path: Path) -> Path:
    project = tmp_path / "synthetic-model-sentinel-project"
    project.mkdir()
    for name in (
        "install_standalone.sh",
        "__main__.py",
        "providers.env.template",
        "settings.env.template",
        "launchd.env.template",
    ):
        shutil.copy2(PROJECT_ROOT / name, project / name)
    shutil.copytree(
        PROJECT_ROOT / "model_sentinel",
        project / "model_sentinel",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (project / "install_standalone.sh").chmod(0o755)
    return project


def _installer_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MODEL_SENTINEL_HOME"] = str(tmp_path / "synthetic-runtime-home")
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run_installer(
    project: Path,
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(project / "install_standalone.sh"), *args],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_installer_embeds_provenance_and_check_detects_source_drift(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    target = tmp_path / "synthetic-bin" / "model-sentinel"

    installed = _run_installer(project, env, str(target))

    assert installed.returncode == 0, installed.stderr
    version = subprocess.run(
        [str(target), "--version"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert version.returncode == 0, version.stderr
    assert "build=standalone" in version.stdout
    assert "revision=unknown" in version.stdout
    assert re.search(r"source_sha256=[0-9a-f]{64}(?:\s|$)", version.stdout)
    assert re.search(r"built=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", version.stdout)

    current = _run_installer(project, env, "--check", str(target))
    assert current.returncode == 0, current.stderr
    assert "current" in current.stdout.lower()

    original_bytes = target.read_bytes()
    original_mtime = target.stat().st_mtime_ns
    reporting_path = project / "model_sentinel" / "reporting.py"
    reporting_path.write_text(
        reporting_path.read_text(encoding="utf-8")
        + "\n# Synthetic source drift for installer freshness coverage.\n",
        encoding="utf-8",
    )

    stale = _run_installer(project, env, "--check", str(target))

    assert stale.returncode == 1
    assert "stale" in (stale.stdout + stale.stderr).lower()
    assert target.read_bytes() == original_bytes
    assert target.stat().st_mtime_ns == original_mtime


def test_standalone_contains_every_browse_runtime_asset(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    target = tmp_path / "synthetic-bin" / "model-sentinel"

    installed = _run_installer(project, env, str(target))

    assert installed.returncode == 0, installed.stderr
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
    expected_assets = {
        "model_sentinel/browse/assets/index.html",
        "model_sentinel/browse/assets/app.js",
        "model_sentinel/browse/assets/app.css",
        "model_sentinel/browse/assets/vendor/VERSIONS.md",
        "model_sentinel/browse/assets/vendor/hooks.umd.js",
        "model_sentinel/browse/assets/vendor/htm.LICENSE",
        "model_sentinel/browse/assets/vendor/htm.umd.js",
        "model_sentinel/browse/assets/vendor/preact.LICENSE",
        "model_sentinel/browse/assets/vendor/preact.umd.js",
        "model_sentinel/browse/assets/vendor/uPlot.iife.min.js",
        "model_sentinel/browse/assets/vendor/uPlot.min.css",
        "model_sentinel/browse/assets/vendor/uplot.LICENSE",
    }
    packaged_assets = {
        name
        for name in names
        if name.startswith("model_sentinel/browse/assets/")
        and not name.endswith("/")
    }
    assert packaged_assets == expected_assets
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)


def test_check_detects_browse_css_drift(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    target = tmp_path / "synthetic-bin" / "model-sentinel"

    installed = _run_installer(project, env, str(target))
    assert installed.returncode == 0, installed.stderr
    current = _run_installer(project, env, "--check", str(target))
    assert current.returncode == 0, current.stderr

    original_bytes = target.read_bytes()
    original_mtime = target.stat().st_mtime_ns
    css_path = project / "model_sentinel" / "browse" / "assets" / "app.css"
    css_path.write_text(
        css_path.read_text(encoding="utf-8")
        + "\n/* Synthetic stylesheet drift for installer freshness coverage. */\n",
        encoding="utf-8",
    )

    stale = _run_installer(project, env, "--check", str(target))

    assert stale.returncode == 1
    assert "stale" in (stale.stdout + stale.stderr).lower()
    assert target.read_bytes() == original_bytes
    assert target.stat().st_mtime_ns == original_mtime


def test_built_standalone_serves_packaged_browse_assets(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    runtime_home = Path(env["MODEL_SENTINEL_HOME"])
    target = tmp_path / "synthetic-bin" / "model-sentinel"

    installed = _run_installer(project, env, str(target))
    assert installed.returncode == 0, installed.stderr
    build_fixture_db(runtime_home / "model_sentinel.db")

    process = subprocess.Popen(
        [str(target), "browse", "--no-open", "--port", "0"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    assert process.stdout is not None
    lines: queue.Queue[str] = queue.Queue()

    def read_stdout() -> None:
        for line in process.stdout:
            lines.put(line)

    threading.Thread(target=read_stdout, daemon=True).start()
    try:
        try:
            line = lines.get(timeout=10)
        except queue.Empty as exc:
            returncode = process.poll()
            detail = "still running"
            if returncode is not None and process.stderr is not None:
                detail = f"exited {returncode}: {process.stderr.read()}"
            raise AssertionError(
                f"standalone did not print its browser URL ({detail})"
            ) from exc
        assert line.startswith("Model Sentinel browser: http://127.0.0.1:")
        base_url = line.removeprefix("Model Sentinel browser: ").strip()

        with urllib.request.urlopen(base_url, timeout=5) as response:
            assert response.status == 200
            assert b'id="app"' in response.read()
        with urllib.request.urlopen(f"{base_url}api/meta", timeout=5) as response:
            assert response.status == 200
            assert json.load(response)["pin_limit"] == 8
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_check_is_read_only_when_the_target_is_missing(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    target = tmp_path / "missing-bin" / "model-sentinel"
    runtime_home = Path(env["MODEL_SENTINEL_HOME"])

    result = _run_installer(project, env, "--check", str(target))

    assert result.returncode == 1
    assert "stale" in (result.stdout + result.stderr).lower()
    assert not target.parent.exists()
    assert not runtime_home.exists()


def test_installer_rejects_unknown_or_excess_arguments(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)

    unknown = _run_installer(project, env, "--unknown")
    excess = _run_installer(project, env, "one", "two")

    assert unknown.returncode == 2
    assert "usage:" in (unknown.stdout + unknown.stderr).lower()
    assert excess.returncode == 2
    assert "usage:" in (excess.stdout + excess.stderr).lower()


def test_failed_candidate_smoke_check_preserves_existing_target(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    target = tmp_path / "synthetic-bin" / "model-sentinel"
    target.parent.mkdir()
    target.write_bytes(b"#!/bin/sh\necho synthetic-existing-target\n")
    target.chmod(0o755)
    original_bytes = target.read_bytes()
    original_mode = stat.S_IMODE(target.stat().st_mode)

    cli_path = project / "model_sentinel" / "cli.py"
    cli_path.write_text(
        "raise RuntimeError('synthetic candidate failure')\n"
        + cli_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = _run_installer(project, env, str(target))

    assert result.returncode != 0
    assert "candidate" in (result.stdout + result.stderr).lower()
    assert "verification" in (result.stdout + result.stderr).lower()
    assert target.read_bytes() == original_bytes
    assert stat.S_IMODE(target.stat().st_mode) == original_mode
