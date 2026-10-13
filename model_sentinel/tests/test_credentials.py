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


def refresh(config, *, settings=None, providers=None, provider_id=None, values=None, from_environment=True):
    return credentials.refresh_credentials(
        settings or config.settings, config.providers if providers is None else providers,
        runtime_paths=config.runtime_paths, provider_id=provider_id,
        from_environment=from_environment, environ=values if values is not None else {KEY: SECRET},
    )


def test_refresh_populates_rotates_filters_and_preserves_disabled(config):
    snapshot = refresh(config, values={KEY: SECRET, "UNRELATED_KEY": OTHER, "SYNTHETIC_DISABLED_KEY": OTHER})
    assert snapshot.values == {KEY: SECRET}
    path = snapshot.path
    assert path.stat().st_mode & 0o777 == 0o600
    assert abs(snapshot.updated_at.timestamp() - path.stat().st_mtime) <= 0.000001
    assert resolve(config).values == {KEY: SECRET}
    refresh(config, provider_id="synthetic_disabled", values={"SYNTHETIC_DISABLED_KEY": OTHER})
    refresh(config, values={KEY: SECRET + "_rotated"})
    assert resolve(config).values == {KEY: SECRET + "_rotated", "SYNTHETIC_DISABLED_KEY": OTHER}
    assert "UNRELATED_KEY" not in path.read_text()


def test_refresh_provider_rename_removal_and_shared_key(config):
    refresh(config)
    refresh(config, provider_id="synthetic_disabled", values={"SYNTHETIC_DISABLED_KEY": OTHER})
    enabled = next(p for p in config.providers if p.enabled)
    renamed = replace(enabled, credential_env_var="SYNTHETIC_RENAMED_KEY")
    refresh(config, providers=(renamed,), values={"SYNTHETIC_RENAMED_KEY": SECRET})
    assert resolve(config, providers=(renamed,)).values == {"SYNTHETIC_RENAMED_KEY": SECRET}
    assert "SYNTHETIC_DISABLED_KEY" not in config.settings.credential_file.read_text()
    assert KEY not in config.settings.credential_file.read_text()
    shared = replace(renamed, provider_id="synthetic_shared", enabled=True)
    assert refresh(config, providers=(renamed, shared), values={"SYNTHETIC_RENAMED_KEY": OTHER}).values == {"SYNTHETIC_RENAMED_KEY": OTHER}


@pytest.mark.parametrize("suffix", ["'", '"', "\\", "=", "#", "$", " '\\=#$\" "])
def test_refresh_values_round_trip(config, suffix):
    refresh(config, values={KEY: SECRET + suffix})
    assert resolve(config).values == {KEY: SECRET + suffix}


def test_refresh_from_environment_ignores_nonexistent_mount(config):
    settings = replace(config.settings, credential_source="environment", credential_refresh_file=config.runtime_paths.runtime_home / "absent_mount")
    assert refresh(config, settings=settings).values == {KEY: SECRET}


def test_refresh_reads_mount_and_drops_unreferenced_cache_keys(config):
    seed(config, f"{KEY}='{SECRET}'\nUNREFERENCED_KEY='{OTHER}'\n".encode())
    source = config.runtime_paths.runtime_home / "synthetic_mount"
    source.write_text(f"{KEY}={OTHER!r}\nUNRELATED_KEY={SECRET!r}\n")
    source.chmod(0o600)
    result = refresh(config, settings=replace(config.settings, credential_refresh_file=source), from_environment=False)
    assert result.values == {KEY: OTHER}
    assert resolve(config).values == {KEY: OTHER}
    assert "UNREFERENCED" not in result.path.read_text()


def test_refresh_rejects_invalid_retained_credential(config):
    path = seed(config, f"{KEY}={SECRET!r}\nSYNTHETIC_DISABLED_KEY='op://SYNTHETIC_NOT_A_REAL_SECRET/item/key'\n".encode())
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with pytest.raises(credentials.CredentialError, match="retained"):
        refresh(config)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("kind", ["missing", "shared", "symlink", "git"])
def test_refresh_custom_parent_is_never_created_or_hardened(config, tmp_path, kind):
    parent = tmp_path / "custom_parent"
    if kind != "missing":
        parent.mkdir(mode=0o755 if kind == "shared" else 0o700)
    if kind == "git":
        (parent / ".git").write_text("synthetic Git marker")
    path = parent / "synthetic_credentials.env"
    if kind == "symlink":
        target = parent / "synthetic_target"
        target.write_text("SYNTHETIC_NOT_A_REAL_SECRET untouched")
        path.symlink_to(target)
    before_mode = parent.stat().st_mode if parent.exists() else None
    with pytest.raises(credentials.CredentialError):
        refresh(config, settings=replace(config.settings, credential_file=path))
    assert (parent.stat().st_mode if parent.exists() else None) == before_mode
    if kind == "symlink":
        assert target.read_text() == "SYNTHETIC_NOT_A_REAL_SECRET untouched"
    else:
        assert not path.exists()


def test_refresh_creates_and_hardens_only_runtime_parent(config):
    parent = config.runtime_paths.runtime_home
    parent.chmod(0o755)
    unrelated = parent / "synthetic_unrelated"
    unrelated.mkdir(mode=0o755)
    refresh(config)
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(unrelated.stat().st_mode) == 0o755
    missing = parent.parent / "synthetic_missing_runtime"
    settings = replace(config.settings, runtime_home=missing, credential_file=missing / "credentials.env")
    runtime_paths = replace(config.runtime_paths, runtime_home=missing)
    result = credentials.refresh_credentials(settings, config.providers, runtime_paths=runtime_paths, provider_id=None, from_environment=True, environ={KEY: SECRET})
    assert result.values == {KEY: SECRET}
    assert stat.S_IMODE(missing.stat().st_mode) == 0o700


@pytest.mark.parametrize("kind", ["symlink", "fifo", "mode"])
def test_refresh_rejects_unsafe_sibling_lock(config, kind):
    path = seed(config)
    lock = path.parent / (path.name + ".lock")
    if kind == "symlink":
        lock.symlink_to(path)
    elif kind == "fifo":
        os.mkfifo(lock, 0o600)
    else:
        lock.write_text("SYNTHETIC_NOT_A_REAL_SECRET unsafe lock")
        lock.chmod(0o644)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with pytest.raises(credentials.CredentialError):
        refresh(config)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_refresh_publishes_validated_canonical_path_after_alias_changes(config, tmp_path, monkeypatch):
    safe = tmp_path / "safe"
    safe.mkdir(mode=0o700)
    reports = config.runtime_paths.report_dir
    reports.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(safe, target_is_directory=True)
    settings = replace(config.settings, credential_file=alias / "credentials.txt")
    original_guard = credentials._validated_cache_path
    def retarget(settings, paths):
        validated = original_guard(settings, paths)
        alias.unlink()
        alias.symlink_to(reports, target_is_directory=True)
        return validated
    monkeypatch.setattr(credentials, "_validated_cache_path", retarget)
    result = refresh(config, settings=settings)
    assert result.path == safe / "credentials.txt"
    assert not (reports / "credentials.txt").exists()
    assert not (reports / "credentials.txt.lock").exists()


def test_refresh_releases_lock_after_failed_write_and_handles_short_writes(config, monkeypatch):
    seed(config)
    real_write = os.write
    def failed_write(*args, **kwargs):
        raise OSError("SYNTHETIC_NOT_A_REAL_SECRET write failure")
    with monkeypatch.context() as fault:
        fault.setattr(os, "write", failed_write)
        with pytest.raises(credentials.CredentialError):
            refresh(config, values={KEY: OTHER})
    with monkeypatch.context() as short:
        short.setattr(os, "write", lambda fd, data: real_write(fd, data[:7]))
        refresh(config, values={KEY: OTHER})
    assert resolve(config).values == {KEY: OTHER}


def test_refresh_committed_cache_is_successful_despite_cleanup_close_error(config, monkeypatch):
    real_close, real_replace = os.close, os.replace
    committed = False
    def replace_and_mark(*args, **kwargs):
        nonlocal committed
        real_replace(*args, **kwargs)
        committed = True
    def close_then_error(fd):
        real_close(fd)
        if committed:
            raise OSError("SYNTHETIC_NOT_A_REAL_SECRET cleanup failure")
    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", replace_and_mark)
        fault.setattr(os, "close", close_then_error)
        snapshot = refresh(config, values={KEY: OTHER})
    assert snapshot.values == {KEY: OTHER}
    assert resolve(config).values == {KEY: OTHER}


@pytest.mark.parametrize("providers,provider_id", [(None, "unknown_synthetic"), ((), None)])
def test_refresh_selection_failure_precedes_acquisition(config, monkeypatch, providers, provider_id):
    def forbidden(*args, **kwargs):
        pytest.fail("acquired before selection validation")
    monkeypatch.setattr(credentials, "read_refresh_values", forbidden)
    with pytest.raises(credentials.ConfigError):
        refresh(config, providers=providers, provider_id=provider_id, from_environment=False)
    assert not config.settings.credential_file.exists()


def test_refresh_then_report_dir_change_rejects_resolution(config, tmp_path):
    parent = tmp_path / "private_cache"
    parent.mkdir(mode=0o700)
    path = parent / "credentials.txt"
    settings_path = config.runtime_paths.settings_env
    settings_path.write_text(settings_path.read_text() + f"\nMODEL_SENTINEL_CREDENTIAL_FILE={path}\n")
    original = load_config(config.project_root)
    refresh(original)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    settings_path.write_text(settings_path.read_text() + f"\nMODEL_SENTINEL_REPORT_DIR={parent}\n")
    changed = load_config(config.project_root)
    with pytest.raises(credentials.CredentialError, match="location"):
        resolve(changed)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("target", ["providers.env", "settings.env", "model_sentinel.sqlite3", "launchd.env", "install_launchd.sh", "run_model_sentinel_launchd.sh", "local.model_sentinel.scan.plist", "reports/credentials.txt", "logs/credentials.txt", "debug/credentials.txt"])
def test_refresh_rejects_reserved_config_and_report_paths(config, target):
    path = config.runtime_paths.runtime_home / target
    path.parent.mkdir(exist_ok=True, mode=0o700)
    if target == "model_sentinel.sqlite3":
        path = config.runtime_paths.database_path
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(credentials.CredentialError, match="location"):
        refresh(config, settings=replace(config.settings, credential_file=path))
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("failure", ["missing_key", "invalid_key", "absent_source", "timeout", "malformed_cache", "unsafe_cache", "same_path", "same_inode", "oversized", "write", "fsync", "replace", "interrupt"])
def test_refresh_failures_preserve_cache(config, monkeypatch, failure):
    path = seed(config)
    settings = config.settings
    values = {KEY: OTHER}
    from_environment = True
    error = credentials.CredentialError
    if failure == "missing_key":
        values = {}
    elif failure == "invalid_key":
        values = {KEY: "op://SYNTHETIC_NOT_A_REAL_SECRET/item/key"}
    elif failure in {"absent_source", "timeout"}:
        source = path.parent / "synthetic_mount"
        if failure == "timeout":
            os.mkfifo(source, 0o600)
        settings = replace(settings, credential_refresh_file=source, credential_refresh_timeout_seconds=0.05)
        from_environment = False
    elif failure == "malformed_cache":
        path.write_text("SYNTHETIC_NOT_A_REAL_SECRET invalid assignments\n")
    elif failure == "unsafe_cache":
        path.chmod(0o644)
        settings = replace(settings, credential_source="environment")
    elif failure in {"same_path", "same_inode"}:
        source = path
        if failure == "same_inode":
            source = path.parent / "synthetic_hardlink"
            os.link(path, source)
        settings = replace(settings, credential_refresh_file=source)
        from_environment = False
    elif failure == "oversized":
        values = {KEY: SECRET + "x" * 65536}
    elif failure in {"write", "fsync", "replace", "interrupt"}:
        def fail(*args, **kwargs):
            if failure == "interrupt":
                raise KeyboardInterrupt
            raise OSError("SYNTHETIC_NOT_A_REAL_SECRET must not escape")
        monkeypatch.setattr(os, "replace" if failure == "interrupt" else failure, fail)
        if failure == "interrupt":
            error = KeyboardInterrupt
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with pytest.raises(error) as raised:
        refresh(config, settings=settings, values=values, from_environment=from_environment)
    assert SECRET not in str(raised.value)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_refresh_serializes_writers_without_losing_updates(config, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    errors = []
    def acquired(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {KEY: SECRET}
    monkeypatch.setattr(credentials, "read_refresh_values", acquired)
    settings = replace(config.settings, credential_refresh_file=config.runtime_paths.runtime_home / "synthetic_mount")
    def first():
        try:
            refresh(config, settings=settings, from_environment=False)
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=first)
    worker.start()
    try:
        assert entered.wait(5)
        with pytest.raises(credentials.CredentialError, match="already running"):
            refresh(config, provider_id="synthetic_disabled", values={"SYNTHETIC_DISABLED_KEY": OTHER})
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and not errors
    refresh(config, provider_id="synthetic_disabled", values={"SYNTHETIC_DISABLED_KEY": OTHER})
    assert resolve(config).values == {KEY: SECRET, "SYNTHETIC_DISABLED_KEY": OTHER}
    path = config.settings.credential_file
    assert (path.parent / (path.name + ".lock")).stat().st_mode & 0o777 == 0o600


def test_refresh_readers_observe_complete_old_or_new_cache(config, monkeypatch):
    seed(config)
    ready, release = threading.Event(), threading.Event()
    real_replace = os.replace
    errors = []
    def held_replace(*args, **kwargs):
        ready.set()
        assert release.wait(5)
        return real_replace(*args, **kwargs)
    monkeypatch.setattr(os, "replace", held_replace)
    def writer():
        try:
            refresh(config, values={KEY: OTHER})
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=writer)
    worker.start()
    try:
        assert ready.wait(5)
        for _ in range(20):
            assert resolve(config).values == {KEY: SECRET}
        release.set()
        while worker.is_alive():
            assert resolve(config).values in ({KEY: SECRET}, {KEY: OTHER})
    finally:
        release.set()
        worker.join(5)
    assert not errors
    assert resolve(config).values == {KEY: OTHER}


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


@pytest.mark.parametrize("forbidden_location", ["reports", "git"])
def test_cache_alias_switch_cannot_change_validated_destination(config, tmp_path, monkeypatch, forbidden_location):
    safe_parent = tmp_path / "synthetic_safe_parent"
    safe_parent.mkdir(mode=0o700)
    if forbidden_location == "reports":
        forbidden_parent = config.runtime_paths.report_dir
    else:
        forbidden_parent = tmp_path / "synthetic_git_checkout"
    forbidden_parent.mkdir(mode=0o700)
    if forbidden_location == "git":
        (forbidden_parent / ".git").write_text("synthetic git marker")
    forbidden_cache = forbidden_parent / "credentials.txt"
    forbidden_cache.write_text(f"{KEY}='{SECRET}'\n")
    forbidden_cache.chmod(0o600)
    alias = tmp_path / "synthetic_switching_alias"
    alias.symlink_to(safe_parent, target_is_directory=True)
    configured_path = alias / "credentials.txt"
    real_canonical_entry = credentials._canonical_entry
    switched = False
    def switch_alias_after_canonicalization(path):
        nonlocal switched
        canonical = real_canonical_entry(path)
        if path == configured_path and not switched:
            alias.unlink()
            alias.symlink_to(forbidden_parent, target_is_directory=True)
            switched = True
        return canonical
    monkeypatch.setattr(credentials, "_canonical_entry", switch_alias_after_canonicalization)
    # The checked private parent has no cache. Reading a cache from the new
    # forbidden target would turn this expected safe failure into success.
    with pytest.raises(credentials.CredentialError):
        resolve(config, settings=replace(config.settings, credential_file=configured_path))
    assert switched


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
