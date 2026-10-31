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

import pytest

from tests.browse_fixtures import build_fixture_db
from tests.credential_fixtures import (
    assert_synthetic_saved_snapshot, synthetic_provider_server, write_credential_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _copy_installer_project(tmp_path: Path) -> Path:
    project = tmp_path / "synthetic-model-sentinel-project"
    project.mkdir()
    for name in (
        "install_standalone.sh",
        "build_standalone.py",
        "__main__.py",
        "providers.env.template",
        "settings.env.template",
        "launchd.env.template",
        "setup.sh",
        "setup_launchd.sh",
        "install_launchd.template.sh",
        "model-sentinel",
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
    env["MODEL_SENTINEL_BACKUP_ROOT"] = str(tmp_path / "synthetic-backups")
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    return env


def test_reinstall_backs_up_target_and_keeps_two(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    target = tmp_path / "synthetic-bin/model-sentinel"
    root = Path(env["MODEL_SENTINEL_BACKUP_ROOT"])
    assert _run_installer(project, env, str(target)).returncode == 0
    assert _run_installer(project, env, "--check", str(target)).returncode == 0
    assert not root.exists()
    previous = target.read_bytes()
    for name in ("copy-old one", "copy-old two"):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "model-sentinel").write_bytes(name.encode())
        os.utime(directory, (1, 1))
    readonly = root / "copy-old one" / "readonly"
    readonly.mkdir()
    (readonly / "data").write_text("synthetic")
    readonly.chmod(0o500)
    outside = tmp_path / "synthetic-outside"
    outside.mkdir(mode=0o500)
    (root / "copy-old one" / "outside").symlink_to(outside, target_is_directory=True)
    os.utime(root / "copy-old one", (1, 1))
    link = root / "copy-link"
    link.symlink_to(root / "copy-old one", target_is_directory=True)
    (root / "copy-regular").write_text("synthetic")
    assert _run_installer(project, env, str(target)).returncode == 0
    backups = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
    assert len(backups) == 2
    assert (root / "copy-old two").exists()
    assert not (root / "copy-old one").exists()
    assert link.is_symlink()
    assert stat.S_IMODE(outside.stat().st_mode) == 0o500
    assert (root / "copy-regular").read_text() == "synthetic"
    newest = next(p for p in backups if p.name.startswith("copy-") and "old" not in p.name)
    assert (newest / "model-sentinel").read_bytes() == previous


def test_reinstall_refuses_unsafe_backup_roots_without_changing_target(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    target = tmp_path / "synthetic-bin/model-sentinel"
    assert _run_installer(project, env, str(target)).returncode == 0
    before = target.read_bytes()
    root = Path(env["MODEL_SENTINEL_BACKUP_ROOT"])
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "marker"
    marker.write_text("synthetic")
    root.symlink_to(external, target_is_directory=True)
    result = _run_installer(project, env, str(target))
    assert result.returncode != 0
    assert target.read_bytes() == before and marker.read_text() == "synthetic"
    env["MODEL_SENTINEL_BACKUP_ROOT"] = str(root) + "/"
    result = _run_installer(project, env, str(target))
    assert result.returncode != 0
    assert target.read_bytes() == before and list(external.iterdir()) == [marker]
    env["MODEL_SENTINEL_BACKUP_ROOT"] = str(root)
    root.unlink()
    root.mkdir(mode=0o500)
    try:
        result = _run_installer(project, env, str(target))
        assert result.returncode != 0
        assert target.read_bytes() == before and list(root.iterdir()) == []
    finally:
        root.chmod(0o700)


@pytest.mark.parametrize("failure", ["chmod", "cleanup"])
def test_final_setup_failure_preserves_old_backups(tmp_path: Path, failure: str) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    target = tmp_path / "synthetic-bin/model-sentinel"
    assert _run_installer(project, env, str(target)).returncode == 0
    previous = target.read_bytes()
    home = Path(env["MODEL_SENTINEL_HOME"])
    bootstrap = home / "launchd.env"
    bootstrap.write_text("# synthetic bootstrap preserved\n")
    root = Path(env["MODEL_SENTINEL_BACKUP_ROOT"])
    originals = {}
    for name in ("copy-old-a", "copy-old-b", "copy-old-c"):
        folder = root / name
        folder.mkdir(parents=True)
        payload = f"synthetic {name}".encode()
        (folder / "model-sentinel").write_bytes(payload)
        os.utime(folder, (1, 1))
        originals[name] = payload
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    marker = tmp_path / "injected-failure"
    env["SYNTHETIC_FAILURE_MARKER"] = str(marker)
    env["SYNTHETIC_LAUNCHD_ENV"] = str(bootstrap)
    env["TMPDIR"] = str(tmp_path)
    env["PATH"] = f"{stubs}{os.pathsep}{env['PATH']}"
    if failure == "chmod":
        command = stubs / "chmod"
        command.write_text(
            '#!/bin/sh\nif [ "$2" = "$SYNTHETIC_LAUNCHD_ENV" ]; then\n'
            '  echo "synthetic final chmod failure" >&2; exit 9\nfi\nexec /bin/chmod "$@"\n'
        )
    else:
        command = stubs / "rm"
        command.write_text(
            '#!/bin/sh\ncase "${2:-}" in */model-sentinel-zipapp.*)\n'
            '  if [ ! -e "$SYNTHETIC_FAILURE_MARKER" ]; then\n'
            '    : > "$SYNTHETIC_FAILURE_MARKER"\n'
            '    echo "synthetic final cleanup failure" >&2; exit 9\n'
            '  fi;;\nesac\nexec /bin/rm "$@"\n'
        )
    command.chmod(0o755)
    result = _run_installer(project, env, str(target))
    assert result.returncode != 0
    assert f"synthetic final {failure} failure" in result.stderr
    assert not list(tmp_path.glob("model-sentinel-zipapp.*"))
    assert bootstrap.read_text() == "# synthetic bootstrap preserved\n"
    assert {p.name for p in root.iterdir()} >= set(originals)
    for name, payload in originals.items():
        assert (root / name / "model-sentinel").read_bytes() == payload
    new = [p for p in root.iterdir() if p.name not in originals]
    assert len(new) == 1 and (new[0] / "model-sentinel").read_bytes() == previous


def _run_command(command: list[str], env: dict[str, str], cwd: Path):
    return subprocess.run(
        command, env=env, cwd=cwd, text=True, capture_output=True,
        check=False, timeout=15,
    )


def test_installed_credentials_refresh_and_scan_without_checkout(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    target = tmp_path / "synthetic-bin" / "model-sentinel"
    # Exclusion checks need artifacts present in the external synthetic source.
    for relative in ("credentials.env", "synthetic-keys.env", "tests/test_synthetic.py",
                     "docs/synthetic-plan.md"):
        excluded = project / relative
        excluded.parent.mkdir(parents=True, exist_ok=True)
        excluded.write_text("# SYNTHETIC_NOT_A_REAL_SECRET_excluded_artifact\n")
    assert _run_installer(project, env, str(target)).returncode == 0
    # Freshness, version and all credential help levels need no configuration.
    env["MODEL_SENTINEL_HOME"] = str(tmp_path / "nonexistent-synthetic-home")
    assert _run_installer(project, env, "--check", str(target)).returncode == 0
    for args in (["--version"], ["--help"], ["credentials", "--help"],
                 ["credentials", "refresh", "--help"]):
        result = _run_command([str(target), *args], env, tmp_path)
        assert result.returncode == 0, result.stderr
    assert not Path(env["MODEL_SENTINEL_HOME"]).exists()
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert "model_sentinel/credentials.py" in names
        assert not any(name.startswith(("tests/", "docs/", ".superpowers/"))
                       or name.endswith(".env") for name in names)
        assert all(b"SYNTHETIC_NOT_A_REAL_SECRET" not in archive.read(name)
                   for name in names if not name.endswith("/"))
    shutil.rmtree(project)
    home = write_credential_config(tmp_path)
    env["MODEL_SENTINEL_HOME"] = str(home)
    env["SYNTHETIC_ENABLED_KEY"] = "SYNTHETIC_NOT_A_REAL_SECRET_wrong_inherited"
    mount = tmp_path / "synthetic-refresh-fifo"
    os.mkfifo(mount, 0o600)
    settings = home / "settings.env"
    settings.write_text(settings.read_text() + f"\nMODEL_SENTINEL_CREDENTIAL_REFRESH_FILE={mount}\n")
    writer = subprocess.Popen([
        "/bin/sh", "-c",
        'printf "%s\\n" "SYNTHETIC_ENABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_fifo" > "$1"',
        "synthetic-writer", str(mount),
    ])
    try:
        refreshed = _run_command([str(target), "credentials", "refresh"], env, tmp_path)
        assert refreshed.returncode == 0, refreshed.stderr
        assert writer.wait(timeout=5) == 0
    finally:
        if writer.poll() is None:
            writer.kill()
            writer.wait(timeout=5)
    mount.unlink()
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert stat.S_IMODE((home / "credentials.env").stat().st_mode) == 0o600
    with synthetic_provider_server(home) as authorizations:
        health = _run_command([str(target), "healthcheck"], env, tmp_path)
        assert health.returncode == 0, health.stdout + health.stderr
        scanned = _run_command([str(target), "scan", "--save", "--no-notify"], env, tmp_path)
        assert scanned.returncode == 0, scanned.stdout + scanned.stderr
        assert authorizations == ["Bearer SYNTHETIC_NOT_A_REAL_SECRET_fifo"]
    assert_synthetic_saved_snapshot(home)
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in refreshed.stdout + health.stdout + scanned.stdout


def test_reseeding_preserves_operator_configuration_and_bootstrap(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    home = write_credential_config(tmp_path)
    env["MODEL_SENTINEL_HOME"] = str(home)
    (home / "launchd.env").write_text(
        'export SYNTHETIC_OPERATOR_SETTING="synthetic-preserve"\n'
        'source "$HOME/synthetic-nonexistent-bootstrap.sh"\n'
    )
    (home / "install_launchd.sh").write_text("#!/bin/bash\n# synthetic operator schedule\n")
    original = {path.name: path.read_bytes() for path in home.iterdir()}
    for script in ("setup.sh", "setup_launchd.sh"):
        result = _run_command(["/bin/bash", str(project / script)], env, tmp_path)
        assert result.returncode == 0, result.stderr
        assert {name: (home / name).read_bytes() for name in original} == original
    installed = _run_installer(project, env, str(tmp_path / "synthetic-bin/model-sentinel"))
    assert installed.returncode == 0, installed.stderr
    assert {name: (home / name).read_bytes() for name in original} == original


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


def test_installer_builds_through_uv_and_never_on_path_python(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    real_uv = shutil.which("uv", path=env["PATH"])
    assert real_uv, "uv is a documented build prerequisite"
    # Spies first on PATH record every uv and python3 call, then delegate.
    spy_dir = tmp_path / "synthetic-spy-bin"
    spy_dir.mkdir()
    uv_log, python_log = tmp_path / "synthetic-uv.log", tmp_path / "synthetic-python3.log"
    for name, log, real in (("uv", uv_log, real_uv), ("python3", python_log, sys.executable)):
        spy = spy_dir / name
        spy.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexec "{real}" "$@"\n')
        spy.chmod(0o755)
    env["PATH"] = f"{spy_dir}{os.pathsep}{env['PATH']}"
    target = tmp_path / "synthetic-bin" / "model-sentinel"

    result = _run_installer(project, env, str(target))

    assert result.returncode == 0, result.stdout + result.stderr
    (call,) = uv_log.read_text().splitlines()
    assert call.startswith(f"run --no-python-downloads --script {project / 'build_standalone.py'} ")
    assert "zipapp" not in (python_log.read_text() if python_log.exists() else "")
    assert target.read_bytes().startswith(b"#!/usr/bin/env python3\n")


def test_installer_without_uv_fails_before_touching_the_target(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    assert shutil.which("uv", path=env["PATH"]) is None
    target = tmp_path / "synthetic-bin" / "model-sentinel"
    target.parent.mkdir()
    target.write_bytes(b"#!/bin/sh\necho synthetic-existing-target\n")
    original = target.read_bytes()

    result = _run_installer(project, env, str(target))

    assert result.returncode == 1
    assert "uv is required to build the standalone" in result.stderr
    assert target.read_bytes() == original
    assert list(target.parent.iterdir()) == [target]
    assert not Path(env["MODEL_SENTINEL_HOME"]).exists()


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
    old = Path(env["MODEL_SENTINEL_BACKUP_ROOT"]) / "copy-old"
    old.mkdir(parents=True)
    (old / "model-sentinel").write_bytes(b"synthetic backup")

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
    assert (old / "model-sentinel").read_bytes() == b"synthetic backup"
    assert list(old.parent.iterdir()) == [old]
