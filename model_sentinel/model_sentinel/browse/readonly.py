from __future__ import annotations

import sqlite3
import threading
import weakref
from pathlib import Path


class MissingDatabaseError(FileNotFoundError):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(str(path))


class SchemaError(RuntimeError):
    def __init__(self, missing: str) -> None:
        self.missing = missing
        super().__init__(f"Missing database schema object: {missing}")


class DatabaseBusyError(RuntimeError):
    """Raised when a concurrent writer prevents a browser query."""


def is_database_busy_error(exc: sqlite3.OperationalError) -> bool:
    """Return whether ``exc`` represents SQLite's busy/locked condition."""
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    message = str(exc).casefold()
    return "locked" in message or "busy" in message


_REQUIRED_SCHEMA: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "providers",
        (
            "provider_id",
            "label",
            "kind",
            "base_url",
            "models_path",
            "credential_env_var",
            "enabled",
            "updated_at",
        ),
    ),
    (
        "scrapes",
        (
            "scrape_id",
            "provider_id",
            "started_at",
            "completed_at",
            "status",
            "baseline_mode",
            "baseline_scrape_id",
            "saved_snapshot",
            "model_count",
            "error_message",
        ),
    ),
    (
        "snapshot_models",
        (
            "scrape_id",
            "provider_id",
            "provider_model_id",
            "display_name",
            "description",
            "model_family",
            "created_at_provider",
            "context_window",
            "max_output_tokens",
            "input_price",
            "output_price",
            "cache_read_price",
            "cache_write_price",
            "reasoning_supported",
            "tool_calling_supported",
            "vision_supported",
            "audio_supported",
            "image_supported",
            "structured_output_supported",
            "deprecated",
            "status",
            "metadata_json",
        ),
    ),
    (
        "field_changes",
        (
            "change_id",
            "provider_id",
            "from_scrape_id",
            "to_scrape_id",
            "provider_model_id",
            "change_kind",
            "field_name",
            "old_value_json",
            "new_value_json",
            "detected_at",
        ),
    ),
)


def ensure_schema(connection: sqlite3.Connection) -> None:
    for table, required_columns in _REQUIRED_SCHEMA:
        rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        if not rows:
            raise SchemaError(table)
        available_columns = {str(row[1]) for row in rows}
        for column in required_columns:
            if column not in available_columns:
                raise SchemaError(f"{table}.{column}")


class _ConnectionOwner:
    __slots__ = ("connection", "_closed", "_lock", "__weakref__")

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._closed = False
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self.connection.close()
            self._closed = True

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class ReadOnlyDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        self._lock = threading.RLock()
        self._owners: dict[int, weakref.ReferenceType[_ConnectionOwner]] = {}
        self._generation = 0

    def connection(self) -> sqlite3.Connection:
        with self._lock:
            state = getattr(self._local, "connection_state", None)
            if state is not None and state[0] == self._generation:
                return state[1].connection

            connection = sqlite3.connect(
                f"{self.path.as_uri()}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
            try:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only = ON")
                connection.execute("PRAGMA busy_timeout = 5000")
            except Exception:
                connection.close()
                raise
            owner = _ConnectionOwner(connection)
            owner_key = id(owner)
            database_ref = weakref.ref(self)

            def discard_owner(
                owner_ref: weakref.ReferenceType[_ConnectionOwner],
                *,
                key: int = owner_key,
                database_ref: weakref.ReferenceType[ReadOnlyDatabase] = database_ref,
            ) -> None:
                database = database_ref()
                if database is None:
                    return
                with database._lock:
                    if database._owners.get(key) is owner_ref:
                        del database._owners[key]

            self._owners[owner_key] = weakref.ref(owner, discard_owner)
            self._local.connection_state = (self._generation, owner)
            return connection

    def close_all(self) -> None:
        with self._lock:
            owners = tuple(
                owner
                for owner_ref in self._owners.values()
                if (owner := owner_ref()) is not None
            )
            self._owners.clear()
            self._generation += 1
            for owner in owners:
                owner.close()


def open_readonly(database_path: Path) -> ReadOnlyDatabase:
    if not database_path.is_file():
        raise MissingDatabaseError(database_path)
    database = ReadOnlyDatabase(database_path)
    try:
        ensure_schema(database.connection())
    except Exception:
        database.close_all()
        raise
    return database
