from __future__ import annotations

import os
import stat
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from tests.credential_fixtures import write_credential_config
from model_sentinel.config import load_config
from model_sentinel import credentials


SECRET = "SYNTHETIC_NOT_A_REAL_SECRET_enabled"
OTHER = "SYNTHETIC_NOT_A_REAL_SECRET_disabled"
KEY = "SYNTHETIC_ENABLED_KEY"


@pytest.fixture
def config(tmp_path, monkeypatch):
    home = write_credential_config(tmp_path)
    monkeypatch.setenv("MODEL_SENTINEL_HOME", str(home))
    return load_config(Path(__file__).resolve().parents[1])


def seed(config, payload=None):
    path = config.settings.credential_file
    path.write_bytes(payload if payload is not None else f"{KEY}='{SECRET}'\n".encode())
    path.chmod(0o600)
    path.parent.chmod(0o700)
    return path


def resolve(config, *, settings=None, providers=None, environ=None):
    return credentials.resolve_credentials(
        settings or config.settings,
        config.providers if providers is None else providers,
        runtime_paths=config.runtime_paths, environ=environ or {},
    )


def test_environment_resolution_never_accesses_files(config, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("environment resolution accessed a file")
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    snapshot = resolve(config, settings=replace(config.settings, credential_source="environment"), environ={KEY: SECRET})
    assert snapshot.values == {KEY: SECRET}
    assert snapshot.path is None and snapshot.updated_at is None
    assert snapshot.source == "environment"
    assert SECRET not in repr(snapshot)


def test_file_resolution_is_authoritative_and_never_acquires(config, monkeypatch):
    path = seed(config)
    os.utime(path, (1700000000, 1700000000))
    def forbidden(*args, **kwargs):
        pytest.fail("cache resolution started acquisition")
    monkeypatch.setattr(subprocess, "run", forbidden)
    snapshot = resolve(config, environ={KEY: OTHER})
    assert snapshot.values == {KEY: SECRET}
    assert snapshot.source == "file" and snapshot.path == path
    assert snapshot.updated_at.timestamp() == path.stat().st_mtime
    assert snapshot.updated_at.utcoffset().total_seconds() == 0
    assert SECRET not in repr(snapshot)


def test_missing_selected_keys_remain_absent(config):
    seed(config, b"# synthetic empty cache\n")
    assert resolve(config).values == {}
    assert resolve(config).invalid_keys == ()


def test_disabled_provider_needs_only_its_selected_key(config):
    seed(config, f"SYNTHETIC_DISABLED_KEY='{OTHER}'\n".encode())
    disabled = next(provider for provider in config.providers if provider.provider_id == "synthetic_disabled")
    snapshot = resolve(config, providers=(disabled,))
    assert snapshot.values == {"SYNTHETIC_DISABLED_KEY": OTHER}
    assert snapshot.invalid_keys == ()


@pytest.mark.parametrize("value", ["", "  ", SECRET + "é", SECRET + "\x00", SECRET + "\t", SECRET + "\n", "op://SYNTHETIC_NOT_A_REAL_SECRET/item/key"])
@pytest.mark.parametrize("source", ["environment", "file"])
def test_invalid_selected_values_are_omitted(config, value, source):
    if source == "file":
        seed(config, f"{KEY}={value!r}\nSYNTHETIC_DISABLED_KEY='{OTHER}'\n".encode())
    snapshot = resolve(config, settings=replace(config.settings, credential_source=source), environ={KEY: value, "SYNTHETIC_DISABLED_KEY": OTHER})
    assert snapshot.values == {"SYNTHETIC_DISABLED_KEY": OTHER}
    assert snapshot.invalid_keys == (KEY,)


@pytest.mark.parametrize("source", ["environment", "file"])
def test_valid_values_preserve_surrounding_spaces(config, source):
    value = f" {SECRET} "
    seed(config, f"{KEY}='{value}'\n".encode())
    assert resolve(config, settings=replace(config.settings, credential_source=source), environ={KEY: value}).values == {KEY: value}


@pytest.mark.parametrize("kind", ["missing", "fifo", "directory", "symlink", "file_mode", "parent_mode", "owner", "device"])
def test_cache_rejects_unsafe_entry(config, monkeypatch, kind):
    path = config.settings.credential_file
    if kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "directory":
        path.mkdir(mode=0o700)
    elif kind == "symlink":
        target = path.parent / "synthetic_target"
        target.write_text(f"{KEY}={SECRET}\n")
        path.symlink_to(target)
    elif kind != "missing":
        seed(config)
    if kind == "file_mode":
        path.chmod(0o644)
    if kind == "parent_mode":
        path.parent.chmod(0o755)
    if kind == "owner":
        monkeypatch.setattr(os, "getuid", lambda: -1)
    if kind == "device":
        config = replace(config, settings=replace(config.settings, credential_file=Path("/dev/null")))
    started = time.monotonic()
    with pytest.raises(credentials.CredentialError):
        resolve(config)
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("name", ["providers.env", "settings.env", "model_sentinel.db", "launchd.env", "install_launchd.sh", "run_model_sentinel_launchd.sh", "local.model_sentinel.scan.plist", "logs/key.env", "debug/key.env", "reports/key.env"])
def test_reserved_runtime_cache_locations(config, name):
    settings = replace(config.settings, credential_file=config.settings.runtime_home / name)
    with pytest.raises(credentials.CredentialError, match="location"):
        credentials.validate_credential_cache_location(settings, config.runtime_paths)


def test_resolution_rechecks_cache_location_after_report_dir_change(config, tmp_path, monkeypatch):
    parent = tmp_path / "synthetic_private_cache"
    parent.mkdir(mode=0o700)
    path = parent / "credentials.txt"
    path.write_text(f"{KEY}='{SECRET}'\n")
    path.chmod(0o600)
    with config.runtime_paths.settings_env.open("a") as stream:
        stream.write(f"\nMODEL_SENTINEL_CREDENTIAL_FILE={path}\n")
    original = load_config(config.project_root)
    assert resolve(original).values == {KEY: SECRET}
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with config.runtime_paths.settings_env.open("a") as stream:
        stream.write(f"\nMODEL_SENTINEL_REPORT_DIR={path.parent}\n")
    changed = load_config(config.project_root)
    def forbidden(*args, **kwargs):
        pytest.fail("unsafe cache was opened")
    monkeypatch.setattr(os, "open", forbidden)
    with pytest.raises(credentials.CredentialError, match="location"):
        resolve(changed)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_cache_parent_alias_rechecks_canonical_report_location(config, tmp_path):
    config.runtime_paths.report_dir.mkdir(mode=0o700)
    alias = tmp_path / "synthetic_report_alias"
    alias.symlink_to(config.runtime_paths.report_dir, target_is_directory=True)
    with pytest.raises(credentials.CredentialError, match="location"):
        credentials.validate_credential_cache_location(replace(config.settings, credential_file=alias / "credentials.txt"), config.runtime_paths)


def test_unselected_invalid_values_do_not_block_valid_selected_key(config):
    seed(config, f"{KEY}='{SECRET}'\nSYNTHETIC_DISABLED_KEY='op://SYNTHETIC_NOT_A_REAL_SECRET/key'\n".encode())
    enabled = next(provider for provider in config.providers if provider.enabled)
    snapshot = resolve(config, providers=(enabled,))
    assert snapshot.values == {KEY: SECRET}
    assert snapshot.invalid_keys == ()


@pytest.mark.parametrize("location", ["home", "root", "checkout", "git_parent", "parent_alias"])
def test_cache_location_rejects_home_root_and_git(config, tmp_path, location):
    if location == "home":
        path = Path.home()
    elif location == "root":
        path = Path("/")
    elif location == "checkout":
        path = config.project_root / "synthetic_credentials.env"
    else:
        parent = tmp_path / "synthetic_git"
        parent.mkdir()
        (parent / ".git").write_text("synthetic git marker")
        path = parent / "synthetic_credentials.env"
        if location == "parent_alias":
            alias = tmp_path / "synthetic_alias"
            alias.symlink_to(parent, target_is_directory=True)
            path = alias / path.name
    with pytest.raises(credentials.CredentialError, match="location"):
        credentials.validate_credential_cache_location(replace(config.settings, credential_file=path), config.runtime_paths)


@pytest.mark.parametrize("payload", [b"\xffSYNTHETIC_NOT_A_REAL_SECRET", f"invalid-{SECRET}=value\n".encode(), b"x" * 65537])
def test_cache_parse_errors_are_safe(config, payload):
    seed(config, payload)
    with pytest.raises(credentials.CredentialError) as error:
        resolve(config)
    assert SECRET not in str(error.value)
    assert error.value.__cause__ is None


def test_cache_rejects_wrong_file_owner_after_open(config, monkeypatch):
    seed(config)
    real_fstat = os.fstat
    def wrong_file_owner(descriptor):
        info = real_fstat(descriptor)
        if stat.S_ISREG(info.st_mode):
            fields = list(info)
            fields[4] = -1
            return os.stat_result(fields)
        return info
    monkeypatch.setattr(os, "fstat", wrong_file_owner)
    with pytest.raises(credentials.CredentialError):
        resolve(config)


def test_cache_reads_content_and_mtime_from_same_descriptor(config, monkeypatch):
    path = seed(config)
    os.utime(path, (1700000000, 1700000000))
    replacement = path.parent / "synthetic_replacement"
    replacement.write_text(f"{KEY}='{OTHER}'\n")
    replacement.chmod(0o600)
    os.utime(replacement, (1710000000, 1710000000))
    real_read = os.read
    replaced = False
    def replace_before_read(descriptor, count):
        nonlocal replaced
        if not replaced:
            os.replace(replacement, path)
            replaced = True
        return real_read(descriptor, count)
    monkeypatch.setattr(os, "read", replace_before_read)
    snapshot = resolve(config)
    assert snapshot.values == {KEY: SECRET}
    assert snapshot.updated_at.timestamp() == 1700000000
    assert path.stat().st_mtime == 1710000000


def test_cache_accepts_exact_byte_limit(config):
    payload = f"{KEY}={SECRET}\n".encode()
    seed(config, payload + b"#" + b"x" * (65536 - len(payload) - 1))
    assert resolve(config).values == {KEY: SECRET}


def fifo_writer(path, payload, stop, *, hold_open=False):
    deadline = time.monotonic() + 4
    descriptor = None
    while not stop.is_set() and time.monotonic() < deadline:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            break
        except OSError:
            stop.wait(0.005)
    if descriptor is None:
        return
    try:
        # Switch to blocking writes; reader drains, or termination closes its end.
        os.set_blocking(descriptor, True)
        try:
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
        except BrokenPipeError:
            pass
        if hold_open:
            stop.wait(4)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("case", ["success", "no_writer", "missing_eof", "empty", "utf8", "assignment", "overflow"])
def test_refresh_fifo_is_bounded_and_safe(tmp_path, case):
    path = tmp_path / "synthetic_mount"
    os.mkfifo(path, 0o600)
    payload = {
        "success": f"{KEY}='{SECRET}'\n".encode(),
        "missing_eof": f"{KEY}='{SECRET}'\n".encode(),
        "empty": b"", "utf8": b"\xffSYNTHETIC_NOT_A_REAL_SECRET",
        "assignment": f"invalid-{SECRET}=value\n".encode(), "overflow": b"x" * 65537,
    }.get(case, b"")
    stop = threading.Event()
    worker = None
    if case != "no_writer":
        worker = threading.Thread(target=fifo_writer, args=(path, payload, stop), kwargs={"hold_open": case == "missing_eof"})
        worker.start()
    started = time.monotonic()
    try:
        if case == "success":
            assert credentials.read_refresh_values(path, timeout_seconds=0.5) == {KEY: SECRET}
        else:
            with pytest.raises(credentials.CredentialError) as error:
                credentials.read_refresh_values(path, timeout_seconds=0.5)
            assert SECRET not in str(error.value)
            assert error.value.__cause__ is None
        assert time.monotonic() - started < 3
    finally:
        stop.set()
        if worker:
            worker.join(timeout=3)
            assert not worker.is_alive()


@pytest.mark.parametrize("kind", ["symlink", "directory", "mode", "device", "missing"])
def test_refresh_rejects_unsafe_sources(tmp_path, kind):
    path = tmp_path / "synthetic_mount"
    if kind == "symlink":
        target = tmp_path / "synthetic_target"
        target.write_text(f"{KEY}={SECRET}\n")
        target.chmod(0o600)
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    elif kind == "mode":
        path.write_text(f"{KEY}={SECRET}\n")
        path.chmod(0o644)
    elif kind == "device":
        path = Path("/dev/null")
    with pytest.raises(credentials.CredentialError):
        credentials.read_refresh_values(path, timeout_seconds=0.5)


def test_refresh_regular_file_and_byte_boundary(tmp_path):
    path = tmp_path / "synthetic_mount"
    payload = f"{KEY}={SECRET}\n".encode()
    path.write_bytes(payload + b"#" + b"x" * (65536 - len(payload) - 1))
    path.chmod(0o600)
    assert credentials.read_refresh_values(path, timeout_seconds=1) == {KEY: SECRET}


def test_refresh_timeout_does_not_echo_captured_values(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic reader", 0.1, output=SECRET.encode(), stderr=OTHER.encode())
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(credentials.CredentialError) as error:
        credentials.read_refresh_values(tmp_path / "synthetic_mount", timeout_seconds=0.1)
    assert SECRET not in str(error.value) and OTHER not in str(error.value)
    assert error.value.__cause__ is None


def test_redaction_masks_literals_longest_first():
    assert credentials.redact_credential_values(SECRET + " " + SECRET + "_suffix", {"a": SECRET, "b": SECRET + "_suffix", "c": ""}) == "[REDACTED] [REDACTED]"
