"""Generated runner acceptance; never contact the real launchd service."""
import os
import shutil
from pathlib import Path
import sys

from tests.credential_fixtures import (
    assert_synthetic_saved_snapshot, synthetic_provider_server, write_credential_config,
)
from tests.test_install_standalone import _copy_installer_project, _installer_env, _run_command, _run_installer


def test_launchd_install_and_runner_refuse_missing_zipapp(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    env["HOME"] = str(tmp_path / "synthetic-user-home")
    home = Path(env["MODEL_SENTINEL_HOME"])
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "calls"
    for name in ("launchctl", "plutil"):
        stub = stubs / name
        stub.write_text(f'#!/bin/sh\necho {name} >> "$SYNTHETIC_CALLS"\n')
        stub.chmod(0o755)
    env["SYNTHETIC_CALLS"] = str(calls)
    env["PATH"] = f"{stubs}{os.pathsep}{env['PATH']}"
    assert _run_command(["/bin/bash", str(project / "setup_launchd.sh")], env, tmp_path).returncode == 0
    installer = home / "install_launchd.sh"
    target = Path(env["HOME"]) / "Library/Scripts/model-sentinel"
    for mode in (None, 0o600):
        if mode is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("synthetic")
            target.chmod(mode)
        refused = _run_command(["/bin/bash", str(installer), "install"], env, tmp_path)
        assert refused.returncode == 2 and "install_standalone.sh" in refused.stderr
        assert not calls.exists() or "launchctl" not in calls.read_text()
        target.unlink(missing_ok=True)
    build_env = _installer_env(tmp_path)
    assert _run_installer(project, build_env, str(target)).returncode == 0
    assert _run_command(["/bin/bash", str(installer), "install"], env, tmp_path).returncode == 0
    runner = home / "run_model_sentinel_launchd.sh"
    for mode in (None, 0o600):
        if mode is None:
            target.unlink()
        else:
            target.write_text("synthetic")
            target.chmod(mode)
        refused = _run_command(["/bin/bash", str(runner)], env, tmp_path)
        assert refused.returncode == 2 and "install_standalone.sh" in refused.stderr


def test_generated_runner_scans_from_cache_without_refresh_mount(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    env["HOME"] = str(tmp_path / "synthetic-user-home")
    home = write_credential_config(tmp_path)
    target = Path(env["HOME"]) / "Library/Scripts/model-sentinel"
    build_env = _installer_env(tmp_path)
    build_env["MODEL_SENTINEL_HOME"] = str(home)
    built = _run_installer(project, build_env, str(target))
    assert built.returncode == 0, built.stderr
    env["MODEL_SENTINEL_HOME"] = str(home)
    env["SYNTHETIC_ENABLED_KEY"] = "SYNTHETIC_NOT_A_REAL_SECRET_cached"
    refreshed = _run_command(
        [sys.executable, "-m", "model_sentinel", "credentials", "refresh", "--from-environment"],
        env, project,
    )
    assert refreshed.returncode == 0, refreshed.stdout + refreshed.stderr
    env.pop("SYNTHETIC_ENABLED_KEY")
    settings = home / "settings.env"
    missing_mount = tmp_path / "synthetic-unavailable-refresh-source"
    settings.write_text(
        settings.read_text() + f"\nMODEL_SENTINEL_CREDENTIAL_REFRESH_FILE={missing_mount}\n"
        "MODEL_SENTINEL_NOTIFY_DEFAULT=0\n"
    )
    stubs = tmp_path / "synthetic-command-stubs"
    stubs.mkdir()
    calls = tmp_path / "synthetic-launchd-calls.txt"
    env["SYNTHETIC_LAUNCHD_CALLS"] = str(calls)
    for name in ("launchctl", "plutil"):
        command = stubs / name
        command.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$SYNTHETIC_LAUNCHD_CALLS"\n')
        command.chmod(0o755)
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{stubs}{os.pathsep}{env['PATH']}"
    seeded = _run_command(["/bin/bash", str(project / "setup_launchd.sh")], env, tmp_path)
    assert seeded.returncode == 0, seeded.stderr
    launchd_env = home / "launchd.env"
    launchd_env.write_text(
        f'export PATH="{Path(sys.executable).parent}:$PATH"\n'
        'export SYNTHETIC_OPERATOR_SETTING="synthetic-preserve"\n'
    )
    original = launchd_env.read_bytes()
    installed = _run_command(["/bin/bash", str(home / "install_launchd.sh"), "install"], env, tmp_path)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert "plutil -lint" in calls.read_text()
    assert "launchctl bootstrap" in calls.read_text()
    assert (Path(env["HOME"]) / "Library/LaunchAgents/local.model_sentinel.scan.plist").is_file()
    runner = home / "run_model_sentinel_launchd.sh"
    assert str(project) not in runner.read_text()
    assert str(project) not in (home / "local.model_sentinel.scan.plist").read_text()
    assert str(target) in runner.read_text()
    shutil.rmtree(project)
    with synthetic_provider_server(home) as authorizations:
        result = _run_command(["/bin/bash", str(home / "run_model_sentinel_launchd.sh")], env, tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert authorizations == ["Bearer SYNTHETIC_NOT_A_REAL_SECRET_cached"]
    assert not missing_mount.exists()
    assert_synthetic_saved_snapshot(home)
    assert launchd_env.read_bytes() == original
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in result.stdout + result.stderr
