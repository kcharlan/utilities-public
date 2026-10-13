import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote

import pytest

from model_sentinel import cli, credentials, providers
from tests.credential_fixtures import (
    synthetic_protocol_response, synthetic_provider_server, write_credential_config,
)


def seed_cache(home, text):
    path = home / "credentials.env"
    path.write_text(text)
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("failure", ["malformed_status", "truncated_body"])
@pytest.mark.parametrize("encoding", [str, json.dumps, quote])
def test_scan_protocol_error_persists_safe_failure_and_preserves_cache(tmp_path, failure, encoding):
    home = write_credential_config(tmp_path)
    secret = 'SYNTHETIC_NOT_A_REAL_SECRET_"\\protocol_echo'
    environment = {**os.environ, "MODEL_SENTINEL_HOME": str(home), "SYNTHETIC_ENABLED_KEY": secret}
    command = [sys.executable, "-m", "model_sentinel"]
    refresh = subprocess.run(
        command + ["credentials", "refresh", "--from-environment"],
        env=environment, capture_output=True, text=True, timeout=30, check=False,
    )
    assert refresh.returncode == 0, refresh.stderr
    cache = home / "credentials.env"
    before = cache.read_bytes(), cache.stat().st_mtime_ns
    report = home / "reports" / "synthetic_protocol_failure.txt"
    response = synthetic_protocol_response(failure, encoding(secret))
    with synthetic_provider_server(home, raw_response=response) as authorizations:
        result = subprocess.run(
            command + ["scan", "--save", "--no-notify", "--output", str(report)],
            env=environment, capture_output=True, text=True, timeout=30, check=False,
        )
    assert authorizations == [f"Bearer {secret}"]
    assert result.returncode == 1
    assert "Traceback" not in result.stdout + result.stderr
    with sqlite3.connect(home / "model_sentinel.db") as db:
        rows = db.execute(
            "SELECT provider_id, status, saved_snapshot, error_message FROM scrapes"
        ).fetchall()
        persisted = "\n".join(db.iterdump())
    assert len(rows) == 1
    assert rows[0][:3] == ("synthetic_enabled", "error", 0)
    assert "network error" in rows[0][3]
    visible = (
        result.stdout + result.stderr + persisted + report.read_text()
        + (home / "logs" / "model_sentinel.log").read_text()
    )
    for sentinel in (secret, json.dumps(secret), quote(secret), "SYNTHETIC_NOT_A_REAL_SECRET", "Traceback"):
        assert sentinel not in visible
    assert (cache.read_bytes(), cache.stat().st_mtime_ns) == before


@pytest.mark.parametrize("provider_id", [None, "synthetic_disabled"])
def test_file_scan_survives_unavailable_refresh_source(tmp_path, monkeypatch, capsys, provider_id):
    home = write_credential_config(tmp_path)
    mount = tmp_path / "synthetic_mount_without_writer"
    os.mkfifo(mount, 0o600)
    settings = home / "settings.env"
    settings.write_text(settings.read_text() + f"\nMODEL_SENTINEL_CREDENTIAL_REFRESH_FILE={mount}\n")
    seed_cache(home, "SYNTHETIC_ENABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_enabled\nSYNTHETIC_DISABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_disabled\n")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    monkeypatch.setenv("SYNTHETIC_ENABLED_KEY", "SYNTHETIC_NOT_A_REAL_SECRET_wrong_inherited")
    def no_reader(*a, **k):
        pytest.fail("scan acquired refresh credentials")
    monkeypatch.setattr(credentials, "read_refresh_values", no_reader)
    real_resolve = cli.resolve_credentials
    resolutions = []
    def resolve(*a, **k):
        resolutions.append(a[1])
        return real_resolve(*a, **k)
    monkeypatch.setattr(cli, "resolve_credentials", resolve)
    calls = []
    def fetch(provider, key, profile):
        calls.append((provider.provider_id, key))
        return []
    monkeypatch.setattr(cli, "fetch_raw_models", fetch)
    args = ["scan", "--save", "--no-notify"] + (["--provider", provider_id] if provider_id else [])
    assert cli.main(args) == 0
    suffix = "disabled" if provider_id else "enabled"
    assert calls == [("synthetic_" + suffix, "SYNTHETIC_NOT_A_REAL_SECRET_" + suffix)]
    assert len(resolutions) == 1
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["missing", "malformed", "unreadable", "invalid", "missing_key"])
def test_file_scan_cache_failure_uses_credential_error_flow(tmp_path, monkeypatch, capsys, failure):
    home = write_credential_config(tmp_path)
    if failure != "missing":
        contents = {
            "malformed": "not an assignment",
            "unreadable": "SYNTHETIC_ENABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_enabled\n",
            "invalid": "SYNTHETIC_ENABLED_KEY=op://SYNTHETIC_NOT_A_REAL_SECRET_invalid\n",
            "missing_key": "SYNTHETIC_DISABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_disabled\n",
        }
        path = seed_cache(home, contents[failure])
        if failure == "unreadable":
            path.chmod(0o644)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    monkeypatch.setenv("SYNTHETIC_ENABLED_KEY", "SYNTHETIC_NOT_A_REAL_SECRET_inherited")
    monkeypatch.setattr(cli, "fetch_raw_models", lambda *a, **k: pytest.fail("fetched without valid cache"))
    notifications = []
    monkeypatch.setattr(cli, "send_notification", lambda **k: notifications.append(k))
    output = home / "synthetic_error.txt"
    assert cli.main(["scan", "--notify", "--output", str(output)]) == 2
    assert output.read_text()
    assert notifications[0]["title"] == "Model Sentinel: credential error"
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in output.read_text() + capsys.readouterr().out


@pytest.mark.parametrize("format_name", ["json", "text", "markdown"])
def test_diagnostics_isolate_disabled_invalid_key(tmp_path, monkeypatch, capsys, format_name):
    home = write_credential_config(tmp_path)
    seed_cache(home, "SYNTHETIC_ENABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_enabled\nSYNTHETIC_DISABLED_KEY=op://SYNTHETIC_NOT_A_REAL_SECRET_invalid\n")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    real_resolve = cli.resolve_credentials
    selections = []
    def resolve(settings, selected, **kwargs):
        selections.append(tuple(p.provider_id for p in selected))
        return real_resolve(settings, selected, **kwargs)
    monkeypatch.setattr(cli, "resolve_credentials", resolve)
    assert cli.main(["providers", "--format", format_name]) == 0
    assert len(selections) == 1 and set(selections[0]) == {"synthetic_enabled", "synthetic_disabled"}
    output = capsys.readouterr().out
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in output
    assert "present" in output and "error" in output and "file" in output
    if format_name == "json":
        rows = {row["provider_id"]: row for row in json.loads(output)}
        assert rows["synthetic_enabled"]["credential_present"] is True
        assert rows["synthetic_disabled"]["credential_status"] == "error"
    assert cli.main(["healthcheck", "--format", format_name]) == 0
    assert selections[1:] == [("synthetic_enabled",)]
    output = capsys.readouterr().out
    assert "cache last updated" in output.lower()
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in output


@pytest.mark.parametrize("source", ["environment", "file"])
def test_retention_preserves_cache_after_report_directory_change(tmp_path, monkeypatch, source):
    home = write_credential_config(tmp_path, source=source)
    cache = home / "credentials.txt"
    cache.write_text("SYNTHETIC_ENABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_enabled\n")
    cache.chmod(0o600)
    expired = home / "expired.md"
    expired.write_text("synthetic expired report")
    os.utime(cache, (1, 1))
    os.utime(expired, (1, 1))
    before = cache.read_bytes(), cache.stat().st_mtime_ns
    settings = home / "settings.env"
    settings.write_text(settings.read_text() + f"\nMODEL_SENTINEL_CREDENTIAL_FILE={cache}\nMODEL_SENTINEL_REPORT_DIR={home}\n")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    monkeypatch.setenv("SYNTHETIC_ENABLED_KEY", "SYNTHETIC_NOT_A_REAL_SECRET_enabled")
    calls = []
    monkeypatch.setattr(cli, "fetch_raw_models", lambda *a: calls.append(a) or [])
    assert cli.main(["scan", "--save", "--no-notify"]) == (2 if source == "file" else 0)
    assert (cache.read_bytes(), cache.stat().st_mtime_ns) == before
    assert bool(calls) == (source == "environment")
    if source == "environment":
        assert not expired.exists()


@pytest.mark.parametrize("source", ["environment", "file"])
@pytest.mark.parametrize("encoding", [str, json.dumps, quote])
def test_scan_http_error_does_not_persist_encoded_credential(tmp_path, monkeypatch, capsys, source, encoding):
    home = write_credential_config(tmp_path, source=source)
    secret = 'SYNTHETIC_NOT_A_REAL_SECRET_"\\hostile'
    # Use the real writer to preserve quote/backslash parsing semantics.
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    monkeypatch.setenv("SYNTHETIC_ENABLED_KEY", secret)
    assert cli.main(["credentials", "refresh", "--from-environment"]) == 0
    cache = home / "credentials.env"
    before = cache.read_bytes(), cache.stat().st_mtime_ns
    def hostile(*args, **kwargs):
        raise HTTPError("http://127.0.0.1:1/models", 401, encoding(secret), {}, io.BytesIO(encoding(secret).encode()))
    monkeypatch.setattr(providers, "urlopen", hostile)
    report = home / "reports" / "synthetic_failure.txt"
    assert cli.main(["scan", "--save", "--no-notify", "--output", str(report)]) == 1
    output = capsys.readouterr()
    with sqlite3.connect(home / "model_sentinel.db") as db:
        rows = db.execute("SELECT error_message FROM scrapes WHERE status='error'").fetchall()
    assert len(rows) == 1 and "HTTP 401" in rows[0][0]
    visible = report.read_text() + (home / "logs" / "model_sentinel.log").read_text() + output.out + output.err + str(rows)
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in visible
    assert (cache.read_bytes(), cache.stat().st_mtime_ns) == before


@pytest.mark.parametrize("failure", ["missing", "invalid", "missing_key"])
@pytest.mark.parametrize("format_name", ["json", "text", "markdown"])
def test_file_diagnostics_never_fall_back_to_environment(tmp_path, monkeypatch, capsys, failure, format_name):
    home = write_credential_config(tmp_path)
    if failure != "missing":
        seed_cache(home, "SYNTHETIC_ENABLED_KEY=op://SYNTHETIC_NOT_A_REAL_SECRET_invalid\n" if failure == "invalid" else "SYNTHETIC_DISABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_disabled\n")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    monkeypatch.setenv("SYNTHETIC_ENABLED_KEY", "SYNTHETIC_NOT_A_REAL_SECRET_inherited")
    assert cli.main(["providers", "--format", format_name]) == 0
    output = capsys.readouterr().out
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in output
    if format_name == "json":
        enabled = next(row for row in json.loads(output) if row["enabled"])
        assert enabled["credential_present"] is False
        assert enabled["credential_status"] == ("missing" if failure == "missing_key" else "error")
    assert cli.main(["healthcheck", "--format", format_name]) == 1
    assert "SYNTHETIC_NOT_A_REAL_SECRET" not in capsys.readouterr().out


def test_future_cache_age_is_nonfatal_and_disabled_missing_key_is_nonfatal(tmp_path, monkeypatch, capsys):
    home = write_credential_config(tmp_path)
    cache = seed_cache(home, "SYNTHETIC_ENABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_enabled\n")
    import time
    os.utime(cache, (time.time() + 3600, time.time() + 3600))
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    assert cli.main(["healthcheck", "--format", "json"]) == 0
    checks = json.loads(capsys.readouterr().out)
    age = next(row for row in checks if row["check"] == "credential_cache_age")
    assert age["status"] == "warn" and "future" in age["detail"]
    assert "age: -" not in age["detail"]


def test_healthcheck_reports_cache_age_when_required_key_is_missing(tmp_path, monkeypatch, capsys):
    home = write_credential_config(tmp_path)
    seed_cache(home, "SYNTHETIC_DISABLED_KEY=SYNTHETIC_NOT_A_REAL_SECRET_disabled\n")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    assert cli.main(["healthcheck", "--format", "json"]) == 1
    checks = json.loads(capsys.readouterr().out)
    assert any(row["check"] == "credential_cache_age" for row in checks)
    cache = next(row for row in checks if row["check"] == "credential_cache")
    assert cache["status"] == "ok"


@pytest.mark.parametrize("args", [["--help"], ["--version"], ["history", "--provider", "synthetic_enabled", "--model", "synthetic/model"], ["changes"], ["browse", "--no-open"]])
def test_offline_commands_do_not_acquire_or_resolve_credentials(tmp_path, monkeypatch, capsys, args):
    home = write_credential_config(tmp_path)
    mount = tmp_path / "synthetic_mount_without_writer"
    os.mkfifo(mount, 0o600)
    settings = home / "settings.env"
    settings.write_text(settings.read_text() + f"\nMODEL_SENTINEL_CREDENTIAL_REFRESH_FILE={mount}\n")
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    def forbidden(*args, **kwargs):
        pytest.fail("offline command acquired or resolved credentials")
    monkeypatch.setattr(cli, "resolve_credentials", forbidden)
    monkeypatch.setattr(cli, "refresh_credentials", forbidden)
    monkeypatch.setattr(credentials, "read_refresh_values", forbidden)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in home.iterdir()}
    if args[0] in {"--help", "--version", "browse"}:
        with pytest.raises(SystemExit) as caught:
            cli.main(args)
        assert caught.value.code == (2 if args[0] == "browse" else 0)
    else:
        assert cli.main(args) == 0
    if args[0] == "browse":
        assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in home.iterdir()} == before


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
