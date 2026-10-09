from __future__ import annotations

import logging
import os
import contextlib
import tempfile
import stat
import subprocess
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)

CONFIG_FILENAME = "config.yaml"
DEFAULT_CONFIG = {
    "default_states": ["GA"],
    "qif_overrides": {},
}


def runtime_home() -> Path:
    override = os.environ.get("TAX2_HOME")
    return Path(override).expanduser() if override else Path.home() / ".tax2"


def config_path() -> Path:
    return runtime_home() / CONFIG_FILENAME


def _publication_entry(path: Path) -> Path:
    path = path.expanduser()
    return path.parent.resolve(strict=False) / path.name


def config_resolution_entries(config_entry: Path) -> list[Path]:
    """Record link entries and the final target without failing on unreadable chains."""
    original = config_entry.expanduser().absolute()
    entries = [original]
    pending = list(original.parts[1:])
    current = Path(original.anchor)
    expansions = 0
    seen = set()
    while pending:
        component = pending.pop(0)
        if component == '..':
            current = current.parent
            continue
        candidate = current / component
        try:
            is_link = stat.S_ISLNK(os.lstat(candidate).st_mode)
        except OSError:
            is_link = False
        if is_link:
            entries.append(candidate)
            state = (candidate, tuple(pending))
            if expansions >= 40 or state in seen:
                return entries
            seen.add(state)
            expansions += 1
            try:
                target = Path(os.readlink(candidate))
            except OSError:
                current = candidate
                continue
            if target.is_absolute():
                current = Path(target.anchor)
                pending = list(target.parts[1:]) + pending
            else:
                pending = list(target.parts) + pending
        else:
            current = candidate
    entries.append(current)
    return entries


def entry_matches(a: Path, b: Path) -> bool:
    """Compare entries by identity, then conservatively compare missing names."""
    def entry_stat(path):
        try:
            return os.lstat(path)
        except OSError:
            return None

    a_stat, b_stat = entry_stat(a), entry_stat(b)
    if a_stat is not None and b_stat is not None:
        return (a_stat.st_dev, a_stat.st_ino) == (b_stat.st_dev, b_stat.st_ino)
    fold = lambda value: unicodedata.normalize('NFC', value).casefold()
    if fold(a.name) != fold(b.name):
        return False
    try:
        if a.parent.exists() and b.parent.exists():
            return os.path.samefile(a.parent, b.parent)
        return fold(os.path.realpath(a.parent)) == fold(os.path.realpath(b.parent))
    except OSError:
        return False


def config_conflict(output: Path, config_entry: Path) -> bool:
    entry = _publication_entry(output)
    return any(entry_matches(entry, protected)
               for protected in config_resolution_entries(config_entry))


def _git_read(arguments: list[str]) -> bytes:
    # Repository/index/object-store and injected Git config overrides must not
    # redirect these local read-only identity checks.
    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    try:
        result = subprocess.run(['git', *arguments], env=environment, capture_output=True,
                                timeout=5, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('Destination safety: unable to classify Git-marked output ancestry') from error
    return result.stdout


def ensure_no_config_conflict(output: Path, config_entry: Path) -> None:
    """The single conflict-then-raise step shared by the early gate and pre-publish recheck."""
    if config_conflict(output, config_entry):
        raise ValueError('Output destination would replace config.yaml')


def validate_output_destination(output: Path, config_path: Path) -> None:
    """Read-only gate for physical publication entries, before private state access."""
    try:
        entry = _publication_entry(output)
        ensure_no_config_conflict(output, config_path)
        for candidate in (entry.parent, *entry.parent.parents):
            metadata = candidate / '.git'
            try:
                mode = metadata.lstat().st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode):
                metadata.stat()
            root_bytes = _git_read(['-C', str(candidate), 'rev-parse', '--show-toplevel'])
            root_text = os.fsdecode(root_bytes).rstrip('\n')
            if not root_text or not Path(root_text).is_absolute():
                raise ValueError('Destination safety: invalid Git source identity')
            root = Path(root_text).resolve(strict=True)
            if not candidate.is_relative_to(root):
                raise ValueError('Destination safety: inconsistent Git source identity')
            tracked = _git_read(['-C', str(root), 'ls-files', '--cached', '-z', '--',
                                 'tax2/tax2', 'tools/check_uv_headers.py']).split(b'\0')
            if {b'tax2/tax2', b'tools/check_uv_headers.py'}.issubset(tracked):
                raise ValueError('Destination safety: output is inside a utilities-public source checkout')
    except OSError as error:
        raise ValueError('Destination safety: unable to inspect output ancestry') from error


def ensure_runtime_home(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def _private_temp(path: Path, data: bytes, mode: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    fd_owned = True
    try:
        os.fchmod(fd, mode)
        stream = os.fdopen(fd, "wb")
        fd_owned = False
        with stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary
    except BaseException:
        if fd_owned:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Publish a complete same-directory private file, preserving the old file on failure."""
    temporary = _private_temp(path, data, mode)
    try:
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def create_config_if_missing(cfg: dict) -> None:
    """Publish missing config exclusively; another creator's file always wins."""
    path = config_path()
    ensure_runtime_home(path.parent)
    # Test the entry itself with lstat, never by following links: any existing
    # entry (including a dangling, looping or unreadable link chain) wins, and
    # an uninspectable entry is never created through. load_config reports the
    # unreadable config; Path.exists semantics differ across Python versions.
    try:
        os.lstat(path)
        return
    except FileNotFoundError:
        pass
    except OSError:
        return
    data = yaml.safe_dump(normalize_config(cfg), sort_keys=False).encode("utf-8")
    temporary = _private_temp(path, data, 0o600)
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def normalize_qif_overrides(raw: object) -> dict[str, dict[str, str]]:
    """Project recognized strings without logging arbitrary supplied keys or values."""
    result: dict[str, dict[str, str]] = {}
    if not isinstance(raw, Mapping):
        logger.warning("Ignoring malformed qif_overrides container")
        return result
    fields = ("state_expense", "state_transfer")
    for index, (key, entry) in enumerate(raw.items()):
        if not isinstance(key, str) or not key.strip() or not isinstance(entry, Mapping):
            logger.warning("Ignoring malformed qif_overrides entry %d", index)
            continue
        target = result.setdefault(key.strip().upper(), {})
        for field in fields:
            if field in entry:
                if isinstance(entry[field], str):
                    target[field] = entry[field]
                else:
                    logger.warning("Ignoring malformed qif_overrides entry %d field %s", index, field)
    return result


def default_config() -> dict[str, Any]:
    return {
        "default_states": list(DEFAULT_CONFIG["default_states"]),
        "qif_overrides": dict(DEFAULT_CONFIG["qif_overrides"]),
    }


def normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = default_config()
    if not isinstance(raw, dict):
        logger.warning('config.yaml is not a mapping; using defaults')
        return cfg

    default_states = raw.get("default_states")
    if isinstance(default_states, list) and default_states:
        cfg["default_states"] = [str(state).upper() for state in default_states]

    # The retired legacy_combined_alias is deliberately ignored on input.
    if "qif_overrides" in raw:
        cfg["qif_overrides"] = normalize_qif_overrides(raw["qif_overrides"])

    return cfg


def load_config() -> dict[str, Any]:
    path = config_path()
    create_config_if_missing(default_config())

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Unable to read config.yaml; using defaults")
        return default_config()

    return normalize_config(raw)
