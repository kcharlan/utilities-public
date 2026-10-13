"""Generated runner acceptance; never contact the real launchd service."""
import os
from pathlib import Path
import sys

from tests.credential_fixtures import (
    assert_synthetic_saved_snapshot, synthetic_provider_server, write_credential_config,
)
from tests.test_install_standalone import _copy_installer_project, _installer_env, _run_command


def test_generated_runner_scans_from_cache_without_refresh_mount(tmp_path: Path) -> None:
    project = _copy_installer_project(tmp_path)
    env = _installer_env(tmp_path)
    env["HOME"] = str(tmp_path / "synthetic-user-home")
    home = write_credential_config(tmp_path)
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
    with synthetic_provider_server(home) as authorizations:
        result = _run_command(["/bin/bash", str(home / "run_model_sentinel_launchd.sh")], env, tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert authorizations == ["Bearer SYNTHETIC_NOT_A_REAL_SECRET_cached"]
    assert not missing_mount.exists()
    assert_synthetic_saved_snapshot(home)
    assert launchd_env.read_bytes() == original
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in result.stdout + result.stderr
