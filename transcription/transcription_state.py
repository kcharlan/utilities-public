import contextlib
import fcntl
import json
import math
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

@dataclass(frozen=True)
class Counters:
    cumulative_seconds: float
    lifetime_seconds: float

@dataclass(frozen=True)
class CounterRead:
    counters: Counters
    warnings: tuple[str, ...]


def runtime_home() -> Path:
    return Path(os.environ.get("TRANSCRIPTION_HOME") or Path.home() / ".transcription").expanduser()


def cumulative_path() -> Path:
    return Path(os.environ.get("CUMULATIVE_JSON_PATH") or runtime_home() / "session_backup.json").expanduser()


def lifetime_path() -> Path:
    return Path(os.environ.get("LIFETIME_TXT_PATH") or runtime_home() / "transcription_odometer.txt").expanduser()


@contextlib.contextmanager
def _locked():
    home = runtime_home()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    home.chmod(0o700)
    fd = os.open(home / "counters.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _read_value(path: Path, cumulative: bool, warnings: list[str]) -> float:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return 0.0
    try:
        text = data.decode("utf-8")
        value = json.loads(text) if cumulative else text.strip()
        if cumulative:
            if not isinstance(value, dict) or "cumulative_seconds" not in value:
                raise ValueError("invalid counter shape")
            value = value["cumulative_seconds"]
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("invalid counter value")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError("invalid counter value")
        return number
    except (ValueError, TypeError, OverflowError):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        saved = path.with_name(f"{path.name}.unreadable-{stamp}-{uuid.uuid4().hex}")
        os.replace(path, saved)
        warnings.append(f"Invalid counter preserved at {saved}")
        return 0.0


def _read() -> CounterRead:
    warnings = []
    counters = Counters(_read_value(cumulative_path(), True, warnings),
                        _read_value(lifetime_path(), False, warnings))
    return CounterRead(counters, tuple(warnings))


def read_counters() -> CounterRead:
    try:
        with _locked():
            return _read()
    except OSError as error:
        return CounterRead(Counters(0.0, 0.0), (f"Could not read counters: {error}",))


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


def _publish(counters: Counters) -> None:
    _write(cumulative_path(), json.dumps({"cumulative_seconds": counters.cumulative_seconds}).encode())
    _write(lifetime_path(), f"{counters.lifetime_seconds}\n".encode())


def add_duration(seconds: float) -> Counters:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("duration must be finite and nonnegative")
    with _locked():
        old = _read().counters
        result = Counters(old.cumulative_seconds + seconds, old.lifetime_seconds + seconds)
        _publish(result)
        return result


def reset_cumulative() -> Counters:
    with _locked():
        old = _read().counters
        result = Counters(0.0, old.lifetime_seconds)
        _write(cumulative_path(), json.dumps({"cumulative_seconds": result.cumulative_seconds}).encode())
        return result
