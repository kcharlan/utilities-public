import os
import subprocess
import sys
from pathlib import Path

import pytest

from model_sentinel import cli
from tests.credential_fixtures import write_credential_config


@pytest.mark.parametrize("arguments", [["--help"], ["credentials", "--help"], ["credentials", "refresh", "--help"]])
@pytest.mark.parametrize("name,expected", [("synthetic-renamed", "synthetic-renamed"), ("/synthetic/model_sentinel/__main__.py", "python -m model_sentinel")])
def test_refresh_help_uses_invocation(arguments, name, expected, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [name])
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert expected in output
    assert "refresh" in output


@pytest.mark.parametrize("failure", [False, True])
def test_refresh_cli_has_safe_exit_and_no_unrelated_runtime_writes(tmp_path, monkeypatch, capsys, failure):
    home = write_credential_config(tmp_path, source="environment")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    monkeypatch.setenv("SYNTHETIC_ENABLED_KEY", "SYNTHETIC_NOT_A_REAL_SECRET_cli")
    args = ["credentials", "refresh", "--from-environment"]
    if failure:
        args += ["--provider", "synthetic_unknown"]
    assert cli.main(args) == (2 if failure else 0)
    output = capsys.readouterr()
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in output.out + output.err
    assert not (home / "logs").exists()
    assert not (home / "debug").exists()
    assert not (home / "reports").exists()
    assert not list(home.glob("*.sqlite*"))
    assert not (home / "model_sentinel.db").exists()
    if not failure:
        assert str(home / "credentials.env") in output.out
        assert "synthetic_enabled" in output.out
        assert "environment" in output.out


def test_no_command_scan_normalization_is_unchanged():
    assert cli._normalize_argv_for_default_scan([]) == ["scan"]
    assert cli._normalize_argv_for_default_scan(["--save"]) == ["scan", "--save"]
    assert cli._normalize_argv_for_default_scan(["credentials", "refresh"]) == ["credentials", "refresh"]


def test_refresh_cli_mount_success_and_acquisition_failure(tmp_path, monkeypatch, capsys):
    home = write_credential_config(tmp_path)
    source = home / "synthetic_mount"
    source.write_text("SYNTHETIC_DISABLED_KEY='SYNTHETIC_NOT_A_REAL_SECRET_cli_mount'\n")
    source.chmod(0o600)
    settings = home / "settings.env"
    settings.write_text(settings.read_text() + f"\nMODEL_SENTINEL_CREDENTIAL_REFRESH_FILE={source}\n")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    args = ["credentials", "refresh", "--provider", "synthetic_disabled"]
    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert "refresh mount" in output.out and "synthetic_disabled" in output.out
    source.unlink()
    before = (home / "credentials.env").read_bytes()
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.err and not output.out
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in output.err
    assert (home / "credentials.env").read_bytes() == before
    assert set(p.name for p in home.iterdir()) == {"settings.env", "providers.env", "credentials.env", "credentials.env.lock"}


def test_refresh_module_invocation(tmp_path):
    home = write_credential_config(tmp_path, source="environment")
    result = subprocess.run(
        [sys.executable, "-m", "model_sentinel", "credentials", "refresh", "--from-environment"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "MODEL_SENTINEL_HOME": str(home), "SYNTHETIC_ENABLED_KEY": "SYNTHETIC_NOT_A_REAL_SECRET_module"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Credential count: 1" in result.stdout
    assert not result.stderr
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in result.stdout
