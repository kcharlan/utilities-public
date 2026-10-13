"""Private credential resolution and bounded, explicit refresh acquisition."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import ConfigError, ProviderConfig, RuntimePaths, Settings, validate_selected_providers
from .envfile import EnvFileError, parse_env_text


MAX_CREDENTIAL_BYTES = 65536


class CredentialError(ConfigError):
    """A fixed, safe operator-facing credential failure."""


@dataclass(frozen=True)
class CredentialSnapshot:
    values: dict[str, str] = field(repr=False)
    source: str
    path: Path | None
    updated_at: datetime | None
    invalid_keys: tuple[str, ...] = ()


def _canonical_entry(path: Path) -> Path:
    # Resolve parent aliases, but retain the final entry for O_NOFOLLOW.
    return path.parent.resolve() / path.name


def validate_credential_cache_location(settings: Settings, runtime_paths: RuntimePaths) -> None:
    """Reject destinations that could publish credentials or replace runtime files."""
    _validated_cache_path(settings, runtime_paths)


def _validated_cache_path(settings: Settings, runtime_paths: RuntimePaths) -> Path:
    """Return the exact canonical entry checked by the placement policy."""
    if settings.credential_file is None:
        raise CredentialError("Credential cache location is not configured.")
    try:
        path = _canonical_entry(settings.credential_file)
        home = Path.home().resolve()
        reserved = {
            runtime_paths.providers_env.resolve(), runtime_paths.settings_env.resolve(),
            runtime_paths.database_path.resolve(), runtime_paths.log_file.resolve(),
            home / "Library/LaunchAgents/local.model_sentinel.scan.plist",
        }
        reserved.update(
            runtime_paths.runtime_home.resolve() / name for name in (
                "launchd.env", "install_launchd.sh", "run_model_sentinel_launchd.sh",
                "local.model_sentinel.scan.plist",
            )
        )
        forbidden_dirs = (
            runtime_paths.logs_dir.resolve(), runtime_paths.debug_dir.resolve(),
            runtime_paths.report_dir.resolve(), settings.report_dir.resolve(),
        )
        if path in reserved or path in (home, Path("/")) or path.parent in (home, Path("/")):
            raise CredentialError("Unsafe credential cache location.")
        if any(path == directory or directory in path.parents for directory in forbidden_dirs):
            raise CredentialError("Unsafe credential cache location.")
        if any(os.path.lexists(parent / ".git") for parent in (path.parent, *path.parent.parents)):
            raise CredentialError("Unsafe credential cache location inside a Git checkout.")
        return path
    except (OSError, RuntimeError, ValueError):
        raise CredentialError("Unable to validate credential cache location.") from None


def _private_descriptor(info: os.stat_result, *, directory: bool = False) -> bool:
    return (
        info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
        and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    )


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while size <= MAX_CREDENTIAL_BYTES:
        chunk = os.read(descriptor, min(8192, MAX_CREDENTIAL_BYTES + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    if size > MAX_CREDENTIAL_BYTES:
        raise CredentialError("Credential data exceeds the size limit.")
    return b"".join(chunks)


def _parse_values(data: bytes, *, source: Path) -> dict[str, str]:
    if len(data) > MAX_CREDENTIAL_BYTES:
        raise CredentialError("Credential data exceeds the size limit.")
    try:
        return parse_env_text(data.decode("utf-8"), source=source, strict=True)
    except (UnicodeError, EnvFileError):
        raise CredentialError("Credential data is not valid UTF-8 assignments.") from None


def _valid_credential(value: str) -> bool:
    return (
        bool(value.strip()) and value.isascii()
        and all(32 <= ord(character) <= 126 for character in value)
        and not value.strip().startswith("op://")
    )


def _read_cache(parent_fd: int, path: Path) -> tuple[dict[str, str], os.stat_result]:
    descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    try:
        info = os.fstat(descriptor)
        if not _private_descriptor(info):
            raise CredentialError("Credential cache must be a user-owned regular file with mode 0600.")
        return _parse_values(_read_bounded(descriptor), source=path), info
    finally:
        os.close(descriptor)


def resolve_credentials(
    settings: Settings, providers: tuple[ProviderConfig, ...], *,
    runtime_paths: RuntimePaths, environ: Mapping[str, str],
) -> CredentialSnapshot:
    updated_at = None
    path = None
    if settings.credential_source == "environment":
        available = environ
    elif settings.credential_source == "file":
        path = _validated_cache_path(settings, runtime_paths)
        parent_fd = None
        try:
            parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if not _private_descriptor(os.fstat(parent_fd), directory=True):
                raise CredentialError("Credential cache parent must be user-owned with mode 0700.")
            available, info = _read_cache(parent_fd, path)
            updated_at = datetime.fromtimestamp(info.st_mtime, tz=timezone.utc)
        except OSError:
            raise CredentialError("Unable to open credential cache safely.") from None
        finally:
            if parent_fd is not None:
                os.close(parent_fd)
    else:
        raise CredentialError("Unknown credential source.")
    selected = dict.fromkeys(provider.credential_env_var for provider in providers)
    values = {}
    invalid = []
    for key in selected:
        if key not in available:
            continue
        value = available[key]
        if _valid_credential(value):
            values[key] = value
        else:
            invalid.append(key)
    return CredentialSnapshot(values, settings.credential_source, path, updated_at, tuple(invalid))


def refresh_credentials(
    settings: Settings, providers: tuple[ProviderConfig, ...], *,
    runtime_paths: RuntimePaths, provider_id: str | None, from_environment: bool,
    environ: Mapping[str, str],
) -> CredentialSnapshot:
    """Publish a private cache atomically; replacement is the commit point.

    The sibling lock is retained so every writer locks the same inode. Handled
    failures remove temporary files. Abrupt process death may leave a private
    temporary file; replacement is not a promise of power-failure durability.
    """
    # Keep POSIX-only dependencies off the environment resolution path.
    import fcntl
    import secrets

    selected = validate_selected_providers(providers, provider_id=provider_id)
    path = _validated_cache_path(settings, runtime_paths)
    parent_fd = lock_fd = temp_fd = None
    temp_name = None
    try:
        if path.parent == runtime_paths.runtime_home.resolve():
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        parent_info = os.fstat(parent_fd)
        if path.parent == runtime_paths.runtime_home.resolve():
            if parent_info.st_uid != os.getuid():
                raise CredentialError("Credential cache parent must be user-owned with mode 0700.")
            os.fchmod(parent_fd, 0o700)
        if not _private_descriptor(os.fstat(parent_fd), directory=True):
            raise CredentialError("Credential cache parent must be user-owned with mode 0700.")
        lock_fd = os.open(
            path.name + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600, dir_fd=parent_fd,
        )
        if not _private_descriptor(os.fstat(lock_fd)):
            raise CredentialError("Credential refresh lock must be a user-owned regular file with mode 0600.")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CredentialError("Credential refresh already running.") from None
        try:
            existing, existing_info = _read_cache(parent_fd, path)
        except FileNotFoundError:
            existing, existing_info = {}, None
        if from_environment:
            acquired = environ
        else:
            source = settings.credential_refresh_file
            if source is None:
                raise CredentialError("Credential refresh source is not configured.")
            if _canonical_entry(source) == path:
                raise CredentialError("Credential refresh source and cache must differ.")
            if existing_info is not None:
                source_info = os.stat(source)
                if (source_info.st_dev, source_info.st_ino) == (existing_info.st_dev, existing_info.st_ino):
                    raise CredentialError("Credential refresh source and cache must differ.")
            acquired = read_refresh_values(source, timeout_seconds=settings.credential_refresh_timeout_seconds)
        selected_names = {provider.credential_env_var for provider in selected}
        for name in sorted(selected_names):
            if name not in acquired or not _valid_credential(acquired[name]):
                raise CredentialError(f"Missing or invalid selected credential: {name}.")
        allowed = {provider.credential_env_var for provider in providers}
        merged = {key: value for key, value in existing.items() if key in allowed}
        merged.update({key: acquired[key] for key in selected_names})
        for name, value in merged.items():
            if not _valid_credential(value):
                raise CredentialError(f"Invalid retained credential: {name}.")
        serialized = "".join(f"{key}={merged[key]!r}\n" for key in sorted(merged)).encode("utf-8")
        _parse_values(serialized, source=path)
        temp_name = f".{path.name}.{secrets.token_hex(16)}.tmp"
        temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
        # Raw descriptor writes have no userspace buffer to flush.
        os.fchmod(temp_fd, 0o600)
        remaining = memoryview(serialized)
        while remaining:
            written = os.write(temp_fd, remaining)
            if written <= 0:
                raise CredentialError("Unable to write credential cache safely.")
            remaining = remaining[written:]
        os.fsync(temp_fd)
        updated_at = datetime.fromtimestamp(os.fstat(temp_fd).st_mtime, tz=timezone.utc)
        result = CredentialSnapshot(merged, "file", path, updated_at)
        os.close(temp_fd)
        temp_fd = None
        os.replace(temp_name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temp_name = None
        return result
    except OSError:
        raise CredentialError("Unable to refresh credential cache safely.") from None
    finally:
        # Cleanup must not turn a committed replacement into a reported failure.
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_name is not None and parent_fd is not None:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except OSError:
                pass
        for descriptor in (lock_fd, parent_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


# Immutable stdlib-only child: no project imports, environment, diagnostics, or
# secret arguments. Blocking FIFO open/read is cancellable by subprocess.run.
READER_SOURCE = r'''
import os
import stat
import sys

def valid(info):
    return (info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
            and (stat.S_ISREG(info.st_mode) or stat.S_ISFIFO(info.st_mode)))

try:
    path = sys.argv[1]
    if not valid(os.lstat(path)):
        sys.exit(2)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not valid(os.fstat(fd)):
            sys.exit(2)
        chunks = []
        size = 0
        while size <= 65536:
            chunk = os.read(fd, min(8192, 65537 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > 65536:
            sys.exit(2)
        sys.stdout.buffer.write(b"".join(chunks))
    finally:
        os.close(fd)
except OSError:
    sys.exit(2)
'''


def read_refresh_values(path: Path, *, timeout_seconds: float) -> dict[str, str]:
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", READER_SOURCE, str(path)],
            env={}, capture_output=True, timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired:
        raise CredentialError("Credential acquisition timed out.") from None
    except OSError:
        raise CredentialError("Unable to start credential acquisition.") from None
    if result.returncode != 0:
        raise CredentialError("Unable to acquire credentials safely.")
    values = _parse_values(result.stdout, source=path)
    if not values:
        raise CredentialError("Credential acquisition returned no assignments.")
    return values


def redact_credential_values(message: str, values: Mapping[str, str]) -> str:
    """Mask known literal values; this cannot mask arbitrary encoded echoes."""
    for value in sorted({value for value in values.values() if value}, key=len, reverse=True):
        message = message.replace(value, "[REDACTED]")
    return message
