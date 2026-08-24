from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from ..storage import load_json_value
from ..time_utils import local_date_for
from .aspects import _CANONICAL_COLUMNS, _safe_path
from .readonly import DatabaseBusyError, is_database_busy_error


_P = ParamSpec("_P")
_R = TypeVar("_R")
_CANONICAL_COLUMN_SET = frozenset(_CANONICAL_COLUMNS)


def _translate_busy(function: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return function(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if is_database_busy_error(exc):
                raise DatabaseBusyError(str(exc)) from exc
            raise

    return wrapped


def _widened_bounds(since: date | None, until: date | None) -> tuple[str | None, str | None]:
    lower = None
    upper = None
    if since is not None:
        lower = (datetime.combine(since, time.min) - timedelta(days=1)).isoformat()
    if until is not None:
        upper = (datetime.combine(until, time.max) + timedelta(days=1)).isoformat()
    return lower, upper


def _in_local_range(value: str, since: date | None, until: date | None) -> bool:
    local_date = local_date_for(value)
    return not ((since is not None and local_date < since) or (until is not None and local_date > until))


def _validated_identifiers(
    columns: Sequence[str], paths: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    unique_columns = tuple(dict.fromkeys(columns))
    unique_paths = tuple(dict.fromkeys(paths))
    invalid_columns = [column for column in unique_columns if column not in _CANONICAL_COLUMN_SET]
    invalid_paths = [path for path in unique_paths if not _safe_path(path)]
    if invalid_columns or invalid_paths:
        invalid = ", ".join(repr(value) for value in (*invalid_columns, *invalid_paths))
        raise ValueError(f"Unsafe or unknown browse query identifier: {invalid}")
    return unique_columns, unique_paths


def _json_path(path: str) -> str:
    return "$" + "".join(f'."{segment}"' for segment in path.split("."))


def path_value_key(path: str) -> str:
    """Return the collision-free result key for a metadata-path value."""
    return f"path:{path.encode('utf-8').hex()}"


def path_type_key(path: str) -> str:
    """Return the collision-free result key for a metadata-path JSON type."""
    return f"path_type:{path.encode('utf-8').hex()}"


def _scrape_summary(row: sqlite3.Row, prefix: str = "") -> dict[str, Any] | None:
    scrape_id = row[f"{prefix}scrape_id"]
    if scrape_id is None:
        return None
    completed_at = str(row[f"{prefix}completed_at"])
    return {
        "scrape_id": int(scrape_id),
        "date": local_date_for(completed_at),
        "completed_at": completed_at,
        "status": row[f"{prefix}status"],
    }


@_translate_busy
def list_scrapes(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT scrape_id, provider_id, completed_at, status,
                  saved_snapshot, model_count
           FROM scrapes
           ORDER BY completed_at DESC, scrape_id DESC"""
    ).fetchall()
    return [
        {
            "scrape_id": int(row["scrape_id"]),
            "provider_id": row["provider_id"],
            "date": local_date_for(row["completed_at"]),
            "completed_at": row["completed_at"],
            "status": row["status"],
            "saved": bool(row["saved_snapshot"]),
            "model_count": int(row["model_count"]),
        }
        for row in rows
    ]


@_translate_busy
def date_span(connection: sqlite3.Connection) -> tuple[date, date] | None:
    rows = connection.execute(
        """SELECT completed_at
           FROM scrapes
           WHERE status = 'success' AND saved_snapshot = 1"""
    ).fetchall()
    if not rows:
        return None
    dates = [local_date_for(row["completed_at"]) for row in rows]
    return min(dates), max(dates)


@_translate_busy
def change_counts_by_date(
    connection: sqlite3.Connection,
    *,
    provider_ids: Sequence[str],
    since: date | None,
    until: date | None,
) -> list[dict[str, Any]]:
    if not provider_ids:
        return []
    placeholders = ", ".join("?" for _ in provider_ids)
    query = f"""SELECT detected_at, provider_id, change_kind, field_name, COUNT(*) AS count
                 FROM field_changes
                 WHERE from_scrape_id IS NOT NULL
                   AND provider_id IN ({placeholders})"""
    parameters: list[Any] = list(provider_ids)
    lower, upper = _widened_bounds(since, until)
    if lower is not None:
        query += " AND detected_at >= ?"
        parameters.append(lower)
    if upper is not None:
        query += " AND detected_at <= ?"
        parameters.append(upper)
    query += " GROUP BY detected_at, provider_id, change_kind, field_name"
    query += " ORDER BY detected_at, provider_id, change_kind, field_name"
    rows = connection.execute(query, parameters).fetchall()
    return [
        {
            "detected_at": row["detected_at"],
            "provider_id": row["provider_id"],
            "change_kind": row["change_kind"],
            "field_name": row["field_name"],
            "count": int(row["count"]),
        }
        for row in rows
        if _in_local_range(row["detected_at"], since, until)
    ]


@_translate_busy
def saved_scrape_ids(
    connection: sqlite3.Connection,
    *,
    provider_id: str,
    since: date | None,
    until: date | None,
) -> list[dict[str, Any]]:
    query = """SELECT scrape_id, provider_id, completed_at, model_count
               FROM scrapes
               WHERE provider_id = ? AND status = 'success' AND saved_snapshot = 1"""
    parameters: list[Any] = [provider_id]
    lower, upper = _widened_bounds(since, until)
    if lower is not None:
        query += " AND completed_at >= ?"
        parameters.append(lower)
    if upper is not None:
        query += " AND completed_at <= ?"
        parameters.append(upper)
    query += " ORDER BY completed_at, scrape_id"
    rows = connection.execute(query, parameters).fetchall()
    return [
        {
            "scrape_id": int(row["scrape_id"]),
            "provider_id": row["provider_id"],
            "date": local_date_for(row["completed_at"]),
            "completed_at": row["completed_at"],
            "model_count": int(row["model_count"]),
        }
        for row in rows
        if _in_local_range(row["completed_at"], since, until)
    ]


@_translate_busy
def series_rows(
    connection: sqlite3.Connection,
    *,
    provider_id: str,
    scrape_ids: Sequence[int],
    model_ids: Sequence[str],
    columns: Sequence[str],
    paths: Sequence[str],
) -> list[sqlite3.Row]:
    columns, paths = _validated_identifiers(columns, paths)
    if not scrape_ids or not model_ids:
        return []
    selections = ["scrape_id", "provider_model_id"]
    selections.extend(f'"{column}"' for column in columns)
    parameters: list[Any] = []
    for path in paths:
        selections.append(f'json_extract(metadata_json, ?) AS "{path_value_key(path)}"')
        parameters.append(_json_path(path))
        selections.append(f'json_type(metadata_json, ?) AS "{path_type_key(path)}"')
        parameters.append(_json_path(path))
    scrape_placeholders = ", ".join("?" for _ in scrape_ids)
    model_placeholders = ", ".join("?" for _ in model_ids)
    query = f"""SELECT {', '.join(selections)}
                 FROM snapshot_models
                 WHERE provider_id = ?
                   AND scrape_id IN ({scrape_placeholders})
                   AND provider_model_id IN ({model_placeholders})
                 ORDER BY scrape_id, provider_model_id"""
    parameters.extend((provider_id, *scrape_ids, *model_ids))
    return list(connection.execute(query, parameters).fetchall())


@_translate_busy
def events_for_models(
    connection: sqlite3.Connection,
    *,
    provider_id: str,
    model_ids: Sequence[str],
    since: date | None,
    until: date | None,
) -> list[dict[str, Any]]:
    if not model_ids:
        return []
    placeholders = ", ".join("?" for _ in model_ids)
    query = f"""SELECT change_id, detected_at, provider_model_id, change_kind,
                        field_name, old_value_json, new_value_json
                 FROM field_changes
                 WHERE from_scrape_id IS NOT NULL
                   AND provider_id = ? AND provider_model_id IN ({placeholders})"""
    parameters: list[Any] = [provider_id, *model_ids]
    lower, upper = _widened_bounds(since, until)
    if lower is not None:
        query += " AND detected_at >= ?"
        parameters.append(lower)
    if upper is not None:
        query += " AND detected_at <= ?"
        parameters.append(upper)
    query += " ORDER BY detected_at, provider_model_id, change_id"
    rows = connection.execute(query, parameters).fetchall()
    return [
        {
            "change_id": int(row["change_id"]),
            "detected_at": row["detected_at"],
            "provider_model_id": row["provider_model_id"],
            "change_kind": row["change_kind"],
            "field_name": row["field_name"],
            "old_value": load_json_value(row["old_value_json"]),
            "new_value": load_json_value(row["new_value_json"]),
        }
        for row in rows
        if _in_local_range(row["detected_at"], since, until)
    ]


@_translate_busy
def catalog_rows(
    connection: sqlite3.Connection,
    *,
    scrape_id: int,
    columns: Sequence[str],
    paths: Sequence[str],
) -> dict[str, dict[str, Any]]:
    columns, paths = _validated_identifiers(columns, paths)
    selections = ["provider_model_id", "display_name", "metadata_json"]
    selections.extend(f'"{column}"' for column in columns)
    parameters: list[Any] = []
    for path in paths:
        selections.append(f'json_extract(metadata_json, ?) AS "{path_value_key(path)}"')
        parameters.append(_json_path(path))
    parameters.append(scrape_id)
    rows = connection.execute(
        f"""SELECT {', '.join(selections)}
            FROM snapshot_models
            WHERE scrape_id = ?
            ORDER BY provider_model_id""",
        parameters,
    ).fetchall()
    return {
        row["provider_model_id"]: {key: row[key] for key in row.keys() if key != "provider_model_id"}
        for row in rows
    }


@_translate_busy
def search_models(
    connection: sqlite3.Connection,
    *,
    provider_ids: Sequence[str],
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    if not provider_ids or limit <= 0:
        return []
    placeholders = ", ".join("?" for _ in provider_ids)
    rows = connection.execute(
        f"""WITH latest AS (
                SELECT sm.provider_id, sm.provider_model_id, sm.display_name,
                       s.completed_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY sm.provider_id, sm.provider_model_id
                           ORDER BY s.completed_at DESC, s.scrape_id DESC
                       ) AS rn
                FROM snapshot_models AS sm
                JOIN scrapes AS s ON s.scrape_id = sm.scrape_id
                WHERE sm.provider_id IN ({placeholders})
                  AND s.status = 'success' AND s.saved_snapshot = 1
            )
            SELECT provider_id, provider_model_id, display_name, completed_at
            FROM latest
            WHERE rn = 1
              AND (
                  instr(lower(provider_model_id), lower(?)) > 0
                  OR instr(lower(display_name), lower(?)) > 0
              )
            ORDER BY completed_at DESC, provider_id, provider_model_id
            LIMIT ?""",
        (*provider_ids, query, query, limit),
    ).fetchall()
    return [
        {
            "provider_id": row["provider_id"],
            "model_id": row["provider_model_id"],
            "display_name": row["display_name"],
            "last_seen": row["completed_at"],
        }
        for row in rows
    ]


@_translate_busy
def change_by_id(connection: sqlite3.Connection, change_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT fc.change_id, fc.provider_id, fc.provider_model_id,
                  fc.change_kind, fc.field_name, fc.old_value_json,
                  fc.new_value_json, fc.detected_at,
                  fs.scrape_id AS from_scrape_id,
                  fs.completed_at AS from_completed_at,
                  fs.status AS from_status,
                  ts.scrape_id AS to_scrape_id,
                  ts.completed_at AS to_completed_at,
                  ts.status AS to_status
           FROM field_changes AS fc
           LEFT JOIN scrapes AS fs ON fs.scrape_id = fc.from_scrape_id
           JOIN scrapes AS ts ON ts.scrape_id = fc.to_scrape_id
           WHERE fc.change_id = ?""",
        (change_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "change_id": int(row["change_id"]),
        "provider_id": row["provider_id"],
        "provider_model_id": row["provider_model_id"],
        "change_kind": row["change_kind"],
        "field_name": row["field_name"],
        "old_value": load_json_value(row["old_value_json"]),
        "new_value": load_json_value(row["new_value_json"]),
        "detected_at": row["detected_at"],
        "from_scrape": _scrape_summary(row, "from_"),
        "to_scrape": _scrape_summary(row, "to_"),
    }


@_translate_busy
def db_providers(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT provider_id, label, kind, enabled
           FROM providers
           ORDER BY provider_id"""
    ).fetchall()
    return [
        {
            "provider_id": row["provider_id"],
            "label": row["label"],
            "kind": row["kind"],
            "enabled": bool(row["enabled"]),
        }
        for row in rows
    ]
