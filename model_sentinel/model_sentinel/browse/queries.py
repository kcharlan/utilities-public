from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from ..endpoints import ENDPOINT_ERROR_BUDGET_EXCEEDED
from ..models import EndpointListRecord
from ..storage import _load_endpoint_gaps, _load_endpoint_lists, load_json_value
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
def model_presence(
    connection: sqlite3.Connection,
    *,
    provider_id: str,
    model_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT sm.scrape_id, s.completed_at, s.status,
                  COUNT(*) OVER () AS observations,
                  MIN(s.completed_at) OVER () AS first_seen,
                  MAX(s.completed_at) OVER () AS last_seen
           FROM snapshot_models AS sm
           JOIN scrapes AS s ON s.scrape_id = sm.scrape_id
           WHERE sm.provider_id = ? AND sm.provider_model_id = ?
             AND s.status = 'success' AND s.saved_snapshot = 1
           ORDER BY s.completed_at DESC, sm.scrape_id DESC
           LIMIT 1""",
        (provider_id, model_id),
    ).fetchone()
    if row is None:
        return None
    completed_at = str(row["completed_at"])
    return {
        "first_seen": str(row["first_seen"]),
        "last_seen": str(row["last_seen"]),
        "observations": int(row["observations"]),
        "latest_scrape": {
            "scrape_id": int(row["scrape_id"]),
            "date": local_date_for(completed_at),
            "completed_at": completed_at,
            "status": row["status"],
        },
    }


@_translate_busy
def snapshot_model_row(
    connection: sqlite3.Connection,
    *,
    scrape_id: int,
    provider_id: str,
    model_id: str,
    columns: Sequence[str],
    paths: Sequence[str],
) -> dict[str, Any] | None:
    columns, paths = _validated_identifiers(columns, paths)
    selections = ["display_name", "metadata_json"]
    selections.extend(f'"{column}"' for column in columns)
    parameters: list[Any] = []
    for path in paths:
        selections.append(f'json_extract(metadata_json, ?) AS "{path_value_key(path)}"')
        parameters.append(_json_path(path))
    parameters.extend((scrape_id, provider_id, model_id))
    row = connection.execute(
        f"""SELECT {', '.join(selections)}
            FROM snapshot_models
            WHERE scrape_id = ? AND provider_id = ? AND provider_model_id = ?""",
        parameters,
    ).fetchone()
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


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


@_translate_busy
def model_observation(
    connection: sqlite3.Connection,
    *,
    provider_id: str,
    model_id: str,
    scrape_id: int,
) -> dict[str, Any] | None:
    """The saved observation of this model at exactly `scrape_id`, if any.

    It qualifies a scrape as `model_presence` does (saved, successful, of
    this provider, containing the model) and has its `latest_scrape` shape.
    """
    row = connection.execute(
        """SELECT sm.scrape_id, s.completed_at, s.status
           FROM snapshot_models AS sm
           JOIN scrapes AS s ON s.scrape_id = sm.scrape_id
           WHERE sm.scrape_id = ? AND sm.provider_id = ? AND sm.provider_model_id = ?
             AND s.provider_id = ?
             AND s.status = 'success' AND s.saved_snapshot = 1""",
        (scrape_id, provider_id, model_id, provider_id),
    ).fetchone()
    if row is None:
        return None
    return _scrape_summary(row)


# ---------------------------------------------------------------------------
# Endpoint captures. These tables are optional: databases created before
# endpoint capture lack them (see `readonly._REQUIRED_SCHEMA`), so callers
# check `endpoint_tables_present` before any other endpoint query.
# ---------------------------------------------------------------------------

_ENDPOINT_TABLES = (
    "endpoint_captures",
    "endpoint_capture_models",
    "endpoint_lists",
    "endpoint_states",
    "endpoint_observations",
    "endpoint_comparison_gaps",
    "endpoint_changes",
)


@_translate_busy
def endpoint_tables_present(connection: sqlite3.Connection) -> bool:
    """Whether every endpoint table the dossier reads exists."""
    placeholders = ", ".join("?" for _ in _ENDPOINT_TABLES)
    rows = connection.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
        _ENDPOINT_TABLES,
    ).fetchall()
    return {row[0] for row in rows} == set(_ENDPOINT_TABLES)


@_translate_busy
def endpoint_capture_for_scrape(connection: sqlite3.Connection, *, scrape_id: int) -> dict[str, Any] | None:
    """The capture saved for exactly this catalog scrape, without its lists.

    `baseline_scrape_id` is the catalog scrape of the capture it was compared
    with (None when it has no baseline capture). `paths_unsent` counts its
    `budget_exceeded` lists, which `paths_failed` includes although they were
    never sent.
    """
    row = connection.execute(
        """SELECT c.capture_id, c.scrape_id, c.provider_id, c.started_at, c.completed_at,
                  c.status, c.paths_requested, c.paths_attempted, c.paths_failed,
                  c.mapping_failures, c.first_capture, c.comparison_state,
                  c.baseline_capture_id, b.scrape_id AS baseline_scrape_id, c.error_summary,
                  (SELECT COUNT(*) FROM endpoint_lists AS l
                   WHERE l.capture_id = c.capture_id AND l.outcome = 'error'
                     AND l.error_code = ?) AS paths_unsent
           FROM endpoint_captures AS c
           LEFT JOIN endpoint_captures AS b ON b.capture_id = c.baseline_capture_id
           WHERE c.scrape_id = ?""",
        (ENDPOINT_ERROR_BUDGET_EXCEEDED, scrape_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "capture_id": int(row["capture_id"]),
        "scrape_id": int(row["scrape_id"]),
        "provider_id": row["provider_id"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "status": row["status"],
        "paths_requested": int(row["paths_requested"]),
        "paths_attempted": int(row["paths_attempted"]),
        "paths_failed": int(row["paths_failed"]),
        "mapping_failures": int(row["mapping_failures"]),
        "first_capture": bool(row["first_capture"]),
        "comparison_state": row["comparison_state"],
        "baseline_capture_id": row["baseline_capture_id"],
        "baseline_scrape_id": row["baseline_scrape_id"],
        "error_summary": row["error_summary"],
        "paths_unsent": int(row["paths_unsent"]),
    }


@_translate_busy
def endpoint_model_list(
    connection: sqlite3.Connection,
    *,
    capture_id: int,
    model_id: str,
) -> dict[str, Any] | None:
    """Resolve one catalog model to its endpoint list in one capture.

    Returns the model's mapping (`outcome`, `list_path` — for an alias the
    path its chain resolved to — `alias_target_model_id`, `error_code`) and
    whether a list row exists for that path (`list_present`), or None when
    the capture has no mapping for the model.
    """
    row = connection.execute(
        """SELECT m.outcome, m.list_path, m.alias_target_model_id, m.error_code,
                  l.list_path IS NOT NULL AS list_present
           FROM endpoint_capture_models AS m
           LEFT JOIN endpoint_lists AS l
             ON l.capture_id = m.capture_id AND l.list_path = m.list_path
           WHERE m.capture_id = ? AND m.provider_model_id = ?""",
        (capture_id, model_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "outcome": row["outcome"],
        "list_path": row["list_path"],
        "alias_target_model_id": row["alias_target_model_id"],
        "error_code": row["error_code"],
        "list_present": bool(row["list_present"]),
    }


@_translate_busy
def endpoint_list_models(
    connection: sqlite3.Connection,
    *,
    capture_id: int,
    list_path: str,
) -> list[dict[str, Any]]:
    """Every catalog model that resolved to `list_path` in one capture.

    This reads the mappings (listed models and resolved aliases alike), never
    model-ID suffixes or the listed-only IDs carried by change records.
    """
    rows = connection.execute(
        """SELECT provider_model_id, outcome, alias_target_model_id
           FROM endpoint_capture_models
           WHERE capture_id = ? AND list_path = ? AND error_code IS NULL
           ORDER BY provider_model_id""",
        (capture_id, list_path),
    ).fetchall()
    return [
        {
            "model_id": row["provider_model_id"],
            "outcome": row["outcome"],
            "alias_target_model_id": row["alias_target_model_id"],
        }
        for row in rows
    ]


@_translate_busy
def endpoint_capture_has_records(connection: sqlite3.Connection, *, capture_id: int) -> bool:
    """Whether a capture saved any mapping or list (a minimal error capture has neither)."""
    row = connection.execute(
        """SELECT EXISTS (SELECT 1 FROM endpoint_capture_models WHERE capture_id = ?)
                  OR EXISTS (SELECT 1 FROM endpoint_lists WHERE capture_id = ?)""",
        (capture_id, capture_id),
    ).fetchone()
    return bool(row[0])


@_translate_busy
def endpoint_capture_lists(
    connection: sqlite3.Connection,
    *,
    capture_id: int,
    list_path: str | None = None,
) -> tuple[EndpointListRecord, ...]:
    """A capture's list records (all of them, or only `list_path`), as `Store.load_endpoint_lists` reads them."""
    return _load_endpoint_lists(connection, capture_id, list_path=list_path)


@_translate_busy
def endpoint_list_gaps(
    connection: sqlite3.Connection,
    *,
    capture_id: int,
    list_path: str,
) -> list[dict[str, Any]]:
    """The comparison gaps one capture recorded for `list_path`, as `Store` reads them."""
    return [
        {
            "list_path": gap.list_path,
            "reason": gap.reason,
            "from_list_path": gap.from_list_path,
            "list_error_code": gap.list_error_code,
        }
        for gap in _load_endpoint_gaps(connection, capture_id, list_path=list_path)
    ]


@_translate_busy
def endpoint_list_changes(
    connection: sqlite3.Connection,
    *,
    provider_id: str,
    list_path: str,
    completed_at: str,
    scrape_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Up to `limit` changes recorded under `list_path`, newest observation first.

    The bound and order are those of `model_presence`: a change's target
    capture belongs to a saved catalog scrape, which must not be later than
    the dossier's observation (`completed_at`, then `scrape_id`), whatever
    order the captures themselves completed in. Rows are ordered by that
    scrape descending, then by descending change ID.
    """
    rows = connection.execute(
        """SELECT ec.endpoint_change_id, ec.from_capture_id, ec.to_capture_id,
                  ec.from_list_path, ec.list_path, ec.endpoint_key, ec.change_kind,
                  ec.field_name, ec.old_value_json, ec.new_value_json, ec.detected_at,
                  fs.scrape_id AS from_scrape_id, fs.completed_at AS from_completed_at,
                  fs.status AS from_status,
                  ts.scrape_id AS to_scrape_id, ts.completed_at AS to_completed_at,
                  ts.status AS to_status
           FROM endpoint_changes AS ec
           JOIN endpoint_captures AS tc ON tc.capture_id = ec.to_capture_id
           JOIN scrapes AS ts ON ts.scrape_id = tc.scrape_id
           JOIN endpoint_captures AS fc ON fc.capture_id = ec.from_capture_id
           JOIN scrapes AS fs ON fs.scrape_id = fc.scrape_id
           WHERE ec.provider_id = ? AND ec.list_path = ?
             AND ts.provider_id = ?
             AND ts.status = 'success' AND ts.saved_snapshot = 1
             AND (ts.completed_at < ? OR (ts.completed_at = ? AND ts.scrape_id <= ?))
           ORDER BY ts.completed_at DESC, ts.scrape_id DESC, ec.endpoint_change_id DESC
           LIMIT ?""",
        (provider_id, list_path, provider_id, completed_at, completed_at, scrape_id, limit),
    ).fetchall()
    return [_endpoint_change_row(row) for row in rows]


def _endpoint_change_row(row: sqlite3.Row) -> dict[str, Any]:
    """The decoded change shape shared by dossier and host history queries."""
    return {
        "endpoint_change_id": int(row["endpoint_change_id"]),
        "from_capture_id": int(row["from_capture_id"]),
        "to_capture_id": int(row["to_capture_id"]),
        "from_list_path": row["from_list_path"],
        "list_path": row["list_path"],
        "endpoint_key": row["endpoint_key"],
        "change_kind": row["change_kind"],
        "field_name": row["field_name"],
        "old_value": load_json_value(row["old_value_json"]),
        "new_value": load_json_value(row["new_value_json"]),
        "detected_at": row["detected_at"],
        "from_scrape": _scrape_summary(row, "from_"),
        "to_scrape": _scrape_summary(row, "to_"),
    }


@_translate_busy
def first_usable_endpoint_capture_date(connection: sqlite3.Connection, *, provider_id: str) -> date | None:
    """The local date of the provider's first capture with a successful list.

    Only persisted `ok` or `empty` list observations count, so an error-only
    capture (failed lists, or a minimal error capture with none) never does.
    """
    row = connection.execute(
        """SELECT c.completed_at
           FROM endpoint_captures AS c
           WHERE c.provider_id = ?
             AND EXISTS (
                 SELECT 1 FROM endpoint_lists AS l
                 WHERE l.capture_id = c.capture_id AND l.outcome IN ('ok', 'empty')
             )
           ORDER BY c.completed_at, c.capture_id
           LIMIT 1""",
        (provider_id,),
    ).fetchone()
    if row is None:
        return None
    return local_date_for(str(row["completed_at"]))


@_translate_busy
def endpoint_telemetry_present(connection: sqlite3.Connection) -> bool:
    names = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('endpoint_telemetry', 'endpoint_telemetry_captures')"
    )}
    return names == {"endpoint_telemetry", "endpoint_telemetry_captures"}


@_translate_busy
def capture_telemetry_status(connection: sqlite3.Connection, *, capture_id: int) -> dict[str, bool]:
    """Read marker/archive existence without requiring optional legacy tables."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return {
        "available": endpoint_telemetry_present(connection) and bool(connection.execute(
            "SELECT 1 FROM endpoint_telemetry_captures WHERE capture_id = ?", (capture_id,)
        ).fetchone()),
        "archive": "endpoint_capture_archives" in tables and bool(connection.execute(
            "SELECT 1 FROM endpoint_capture_archives WHERE capture_id = ?", (capture_id,)
        ).fetchone()),
    }


@_translate_busy
def host_captures(connection: sqlite3.Connection, *, provider_id: str) -> list[dict[str, Any]]:
    """Usable saved captures in descending catalog order, including empty lists."""
    if not endpoint_tables_present(connection):
        return []
    rows = connection.execute(
        """SELECT s.scrape_id, s.provider_id, s.completed_at, s.status, s.saved_snapshot,
                  s.model_count, c.capture_id, c.status AS capture_status
           FROM scrapes s JOIN endpoint_captures c ON c.scrape_id = s.scrape_id
           WHERE s.provider_id = ? AND c.provider_id = s.provider_id
             AND s.status = 'success' AND s.saved_snapshot = 1
             AND EXISTS (SELECT 1 FROM endpoint_lists l WHERE l.capture_id = c.capture_id
                         AND l.outcome IN ('ok', 'empty'))
           ORDER BY s.completed_at DESC, s.scrape_id DESC""", (provider_id,)
    ).fetchall()
    return [{"scrape_id": row["scrape_id"], "provider_id": row["provider_id"],
             "completed_at": row["completed_at"], "date": local_date_for(row["completed_at"]),
             "status": row["status"], "saved": bool(row["saved_snapshot"]),
             "model_count": row["model_count"], "capture_id": row["capture_id"],
             "capture_status": row["capture_status"]} for row in rows]


@_translate_busy
def capture_endpoint_rows(connection: sqlite3.Connection, *, capture_id: int,
                          list_path: str | None = None) -> list[dict[str, Any]]:
    """Exact capture samples, optionally bounded to a dossier's resolved list."""
    telemetry = endpoint_telemetry_present(connection)
    columns = "t.uptime_1d, t.uptime_30m, t.uptime_5m" if telemetry else "NULL AS uptime_1d, NULL AS uptime_30m, NULL AS uptime_5m"
    join = """LEFT JOIN endpoint_telemetry t ON t.capture_id = o.capture_id
              AND t.list_path = o.list_path AND t.endpoint_key = o.endpoint_key
              AND EXISTS (SELECT 1 FROM endpoint_telemetry_captures m WHERE m.capture_id = o.capture_id)""" if telemetry else ""
    restriction = " AND o.list_path = ?" if list_path is not None else ""
    parameters = (capture_id, list_path) if list_path is not None else (capture_id,)
    rows = connection.execute(
        f"""SELECT o.list_path, o.endpoint_key, o.status_code, s.state_json, {columns}
            FROM endpoint_observations o JOIN endpoint_states s ON s.state_hash = o.state_hash
            {join} WHERE o.capture_id = ?{restriction} ORDER BY o.list_path, o.rowid""", parameters
    ).fetchall()
    return [{**dict(row), "state": load_json_value(row["state_json"])} for row in rows]


@_translate_busy
def capture_list_models(connection: sqlite3.Connection, *, capture_id: int) -> dict[str, list[dict[str, Any]]]:
    rows = connection.execute(
        """SELECT list_path, provider_model_id, outcome, alias_target_model_id FROM endpoint_capture_models
           WHERE capture_id = ? AND list_path IS NOT NULL AND error_code IS NULL
           ORDER BY provider_model_id""", (capture_id,)
    ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row["list_path"], []).append({"model_id": row["provider_model_id"], "outcome": row["outcome"], "alias_target_model_id": row["alias_target_model_id"]})
    return result


@_translate_busy
def host_series(connection: sqlite3.Connection, *, provider_id: str, host: str,
                since: date | None = None, until: date | None = None) -> list[dict[str, Any]]:
    from statistics import median
    from .hosts_api import host_name
    result = []
    for scrape in reversed(host_captures(connection, provider_id=provider_id)):
        if not _in_local_range(scrape["completed_at"], since, until):
            continue
        capture = endpoint_capture_for_scrape(connection, scrape_id=scrape["scrape_id"])
        rows = [row for row in capture_endpoint_rows(connection, capture_id=capture["capture_id"])
                if host_name(row["state"].get("provider_name"), row["state"].get("name"), row["state"].get("tag"), row["endpoint_key"]) == host]
        samples = [row["uptime_1d"] for row in rows if row["uptime_1d"] is not None]
        unknown = not rows and capture["status"] != "complete"
        result.append({"scrape_id": scrape["scrape_id"], "date": scrape["date"],
                       "lists": None if unknown else len({row["list_path"] for row in rows}),
                       "endpoints": None if unknown else len(rows),
                       "not_normal": None if unknown else sum(row["status_code"] != 0 for row in rows),
                       "uptime_1d_median": median(samples) if samples else None,
                       "uptime_1d_min": min(samples) if samples else None, "capture": capture})
    return result


@_translate_busy
def host_changes(connection: sqlite3.Connection, *, provider_id: str, host: str,
                 since: date | None = None, until: date | None = None, limit: int) -> list[dict[str, Any]]:
    from .hosts_api import host_name
    if not endpoint_tables_present(connection):
        return []
    connection.create_function("sentinel_host", 4, host_name, deterministic=True)
    # Removals use the baseline observation, including its original list path;
    # every other change uses the target observation. Serialization still uses
    # the target list, loaded by the response layer.
    fields = [f"CASE WHEN json_type(st.state_json, '$.{key}') = 'text' THEN json_extract(st.state_json, '$.{key}') END" for key in ("provider_name", "name", "tag")]
    rows = connection.execute(
        f"""SELECT ec.*, fs.scrape_id AS from_scrape_id, fs.completed_at AS from_completed_at,
                   fs.status AS from_status, ts.scrape_id AS to_scrape_id,
                   ts.completed_at AS to_completed_at, ts.status AS to_status
            FROM endpoint_changes ec
            JOIN endpoint_captures fc ON fc.capture_id = ec.from_capture_id
            JOIN endpoint_captures tc ON tc.capture_id = ec.to_capture_id
            JOIN scrapes fs ON fs.scrape_id = fc.scrape_id
            JOIN scrapes ts ON ts.scrape_id = tc.scrape_id
            JOIN endpoint_observations o ON o.endpoint_key = ec.endpoint_key
              AND o.capture_id = CASE WHEN ec.change_kind = 'endpoint_removed' THEN ec.from_capture_id ELSE ec.to_capture_id END
              AND o.list_path = CASE WHEN ec.change_kind = 'endpoint_removed' THEN ec.from_list_path ELSE ec.list_path END
            JOIN endpoint_states st ON st.state_hash = o.state_hash
            WHERE ec.provider_id = ? AND ts.provider_id = ? AND ts.status = 'success' AND ts.saved_snapshot = 1
              AND sentinel_host({', '.join(fields)}, ec.endpoint_key) = ?
            ORDER BY ts.completed_at DESC, ts.scrape_id DESC, ec.endpoint_change_id DESC""", (provider_id, provider_id, host)
    )
    result = []
    for row in rows:
        if not _in_local_range(row["to_completed_at"], since, until):
            continue
        result.append(_endpoint_change_row(row))
        if len(result) >= limit:
            break
    return result
