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

from .config import ConfigError, ProviderConfig, RuntimePaths, Settings
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
        file_fd = None
        try:
            parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if not _private_descriptor(os.fstat(parent_fd), directory=True):
                raise CredentialError("Credential cache parent must be user-owned with mode 0700.")
            file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
            info = os.fstat(file_fd)
            if not _private_descriptor(info):
                raise CredentialError("Credential cache must be a user-owned regular file with mode 0600.")
            data = _read_bounded(file_fd)
            updated_at = datetime.fromtimestamp(info.st_mtime, tz=timezone.utc)
        except OSError:
            raise CredentialError("Unable to open credential cache safely.") from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if parent_fd is not None:
                os.close(parent_fd)
        available = _parse_values(data, source=path)
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
