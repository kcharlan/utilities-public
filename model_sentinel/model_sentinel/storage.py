from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from .config import ProviderConfig
from .models import BaselineInfo, HistoryEvent, ModelDelta, NormalizedModel
from .time_utils import local_date_for, to_storage_timestamp


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS providers (
        provider_id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        kind TEXT NOT NULL,
        base_url TEXT NOT NULL,
        models_path TEXT NOT NULL,
        credential_env_var TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scrapes (
        scrape_id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        status TEXT NOT NULL,
        baseline_mode TEXT,
        baseline_scrape_id INTEGER,
        saved_snapshot INTEGER NOT NULL,
        model_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshot_models (
        scrape_id INTEGER NOT NULL,
        provider_id TEXT NOT NULL,
        provider_model_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        description TEXT,
        model_family TEXT,
        created_at_provider TEXT,
        context_window INTEGER,
        max_output_tokens INTEGER,
        input_price REAL,
        output_price REAL,
        cache_read_price REAL,
        cache_write_price REAL,
        reasoning_supported INTEGER,
        tool_calling_supported INTEGER,
        vision_supported INTEGER,
        audio_supported INTEGER,
        image_supported INTEGER,
        structured_output_supported INTEGER,
        deprecated INTEGER,
        status TEXT,
        metadata_json TEXT NOT NULL,
        PRIMARY KEY (scrape_id, provider_model_id),
        FOREIGN KEY (scrape_id) REFERENCES scrapes(scrape_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS field_changes (
        change_id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id TEXT NOT NULL,
        from_scrape_id INTEGER,
        to_scrape_id INTEGER NOT NULL,
        provider_model_id TEXT NOT NULL,
        change_kind TEXT NOT NULL,
        field_name TEXT,
        old_value_json TEXT,
        new_value_json TEXT,
        detected_at TEXT NOT NULL
    )
    """,
)


class Store:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            for statement in SCHEMA:
                connection.execute(statement)
            connection.commit()

    def upsert_provider_configs(self, providers: tuple[ProviderConfig, ...], *, updated_at: str) -> None:
        updated_at = to_storage_timestamp(updated_at)
        with self._connect() as connection:
            for provider in providers:
                connection.execute(
                    """
                    INSERT INTO providers (
                        provider_id, label, kind, base_url, models_path,
                        credential_env_var, enabled, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider_id) DO UPDATE SET
                        label=excluded.label,
                        kind=excluded.kind,
                        base_url=excluded.base_url,
                        models_path=excluded.models_path,
                        credential_env_var=excluded.credential_env_var,
                        enabled=excluded.enabled,
                        updated_at=excluded.updated_at
                    """,
                    (
                        provider.provider_id,
                        provider.label,
                        provider.kind,
                        provider.base_url,
                        provider.models_path,
                        provider.credential_env_var,
                        int(provider.enabled),
                        updated_at,
                    ),
                )
            connection.commit()

    def create_scrape(
        self,
        *,
        provider_id: str,
        started_at: str,
        completed_at: str,
        status: str,
        baseline_mode: str | None,
        baseline_scrape_id: int | None,
        saved_snapshot: bool,
        model_count: int,
        error_message: str | None,
    ) -> int:
        started_at = to_storage_timestamp(started_at)
        completed_at = to_storage_timestamp(completed_at)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO scrapes (
                    provider_id, started_at, completed_at, status, baseline_mode,
                    baseline_scrape_id, saved_snapshot, model_count, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_id,
                    started_at,
                    completed_at,
                    status,
                    baseline_mode,
                    baseline_scrape_id,
                    int(saved_snapshot),
                    model_count,
                    error_message,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def save_snapshot_models(self, *, scrape_id: int, provider_id: str, models: list[NormalizedModel]) -> None:
        with self._connect() as connection:
            for model in models:
                connection.execute(
                    """
                    INSERT INTO snapshot_models (
                        scrape_id, provider_id, provider_model_id, display_name, description,
                        model_family, created_at_provider, context_window, max_output_tokens,
                        input_price, output_price, cache_read_price, cache_write_price,
                        reasoning_supported, tool_calling_supported, vision_supported,
                        audio_supported, image_supported, structured_output_supported,
                        deprecated, status, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scrape_id,
                        provider_id,
                        model.provider_model_id,
                        model.display_name,
                        model.description,
                        model.model_family,
                        model.created_at_provider,
                        model.context_window,
                        model.max_output_tokens,
                        model.input_price,
                        model.output_price,
                        model.cache_read_price,
                        model.cache_write_price,
                        _maybe_int(model.reasoning_supported),
                        _maybe_int(model.tool_calling_supported),
                        _maybe_int(model.vision_supported),
                        _maybe_int(model.audio_supported),
                        _maybe_int(model.image_supported),
                        _maybe_int(model.structured_output_supported),
                        _maybe_int(model.deprecated),
                        model.status,
                        model.metadata_json,
                    ),
                )
            connection.commit()

    def record_field_changes(
        self,
        *,
        provider_id: str,
        from_scrape_id: int | None,
        to_scrape_id: int,
        deltas: tuple[ModelDelta, ...],
        detected_at: str,
    ) -> None:
        detected_at = to_storage_timestamp(detected_at)
        with self._connect() as connection:
            for delta in deltas:
                if delta.kind in {"added", "removed"}:
                    connection.execute(
                        """
                        INSERT INTO field_changes (
                            provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                            change_kind, field_name, old_value_json, new_value_json, detected_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            provider_id,
                            from_scrape_id,
                            to_scrape_id,
                            delta.provider_model_id,
                            delta.kind,
                            None,
                            None,
                            None,
                            detected_at,
                        ),
                    )
                    continue
                for field_change in delta.field_changes:
                    connection.execute(
                        """
                        INSERT INTO field_changes (
                            provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                            change_kind, field_name, old_value_json, new_value_json, detected_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            provider_id,
                            from_scrape_id,
                            to_scrape_id,
                            delta.provider_model_id,
                            "field_changed",
                            field_change.field_name,
                            json.dumps(field_change.old_value, sort_keys=True, ensure_ascii=True),
                            json.dumps(field_change.new_value, sort_keys=True, ensure_ascii=True),
                            detected_at,
                        ),
                    )
            connection.commit()

    def get_latest_saved_baseline(self, provider_id: str) -> BaselineInfo | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT scrape_id, completed_at
                FROM scrapes
                WHERE provider_id = ? AND status = 'success' AND saved_snapshot = 1
                ORDER BY datetime(completed_at) DESC, scrape_id DESC
                LIMIT 1
                """,
                (provider_id,),
            ).fetchone()
        if row is None:
            return None
        return BaselineInfo(scrape_id=int(row["scrape_id"]), completed_at=row["completed_at"])

    def get_latest_successful_scrape_time(self, provider_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT completed_at
                FROM scrapes
                WHERE provider_id = ? AND status = 'success'
                ORDER BY datetime(completed_at) DESC, scrape_id DESC
                LIMIT 1
                """,
                (provider_id,),
            ).fetchone()
        if row is None:
            return None
        return row["completed_at"]

    def get_previous_day_baseline(self, provider_id: str, *, current_date: date) -> BaselineInfo | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT scrape_id, completed_at
                FROM scrapes
                WHERE provider_id = ? AND status = 'success' AND saved_snapshot = 1
                ORDER BY datetime(completed_at) DESC, scrape_id DESC
                """,
                (provider_id,),
            ).fetchall()
        for row in rows:
            if local_date_for(row["completed_at"]) < current_date:
                return BaselineInfo(scrape_id=int(row["scrape_id"]), completed_at=row["completed_at"])
        return None

    def get_baseline_for_date(self, provider_id: str, *, target_date: date) -> BaselineInfo | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT scrape_id, completed_at
                FROM scrapes
                WHERE provider_id = ? AND status = 'success' AND saved_snapshot = 1
                ORDER BY datetime(completed_at) ASC, scrape_id ASC
                """,
                (provider_id,),
            ).fetchall()
        for row in rows:
            if local_date_for(row["completed_at"]) == target_date:
                return BaselineInfo(scrape_id=int(row["scrape_id"]), completed_at=row["completed_at"])
        return None

    def nearest_saved_dates(self, provider_id: str, *, target_date: date) -> tuple[str | None, str | None]:
        prior: str | None = None
        subsequent: str | None = None
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT completed_at
                FROM scrapes
                WHERE provider_id = ? AND status = 'success' AND saved_snapshot = 1
                ORDER BY datetime(completed_at) ASC, scrape_id ASC
                """,
                (provider_id,),
            ).fetchall()
        for row in rows:
            completed_at = row["completed_at"]
            completed_date = local_date_for(completed_at)
            if completed_date < target_date:
                prior = completed_at
            elif completed_date > target_date and subsequent is None:
                subsequent = completed_at
        return prior, subsequent

    def load_saved_models(self, scrape_id: int) -> dict[str, NormalizedModel]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM snapshot_models
                WHERE scrape_id = ?
                ORDER BY provider_model_id ASC
                """,
                (scrape_id,),
            ).fetchall()
        models: dict[str, NormalizedModel] = {}
        for row in rows:
            model = NormalizedModel(
                provider_id=row["provider_id"],
                provider_label="",
                provider_model_id=row["provider_model_id"],
                display_name=row["display_name"],
                description=row["description"],
                model_family=row["model_family"],
                created_at_provider=row["created_at_provider"],
                context_window=row["context_window"],
                max_output_tokens=row["max_output_tokens"],
                input_price=row["input_price"],
                output_price=row["output_price"],
                cache_read_price=row["cache_read_price"],
                cache_write_price=row["cache_write_price"],
                reasoning_supported=_from_db_bool(row["reasoning_supported"]),
                tool_calling_supported=_from_db_bool(row["tool_calling_supported"]),
                vision_supported=_from_db_bool(row["vision_supported"]),
                audio_supported=_from_db_bool(row["audio_supported"]),
                image_supported=_from_db_bool(row["image_supported"]),
                structured_output_supported=_from_db_bool(row["structured_output_supported"]),
                deprecated=_from_db_bool(row["deprecated"]),
                status=row["status"],
                metadata_json=row["metadata_json"],
            )
            models[model.provider_model_id] = model
        return models

    def history_events(
        self,
        *,
        provider_id: str,
        model_id: str,
        since: date | None,
        until: date | None,
    ) -> tuple[str | None, str | None, tuple[HistoryEvent, ...]]:
        with self._connect() as connection:
            snapshot_rows = connection.execute(
                """
                SELECT s.completed_at
                FROM snapshot_models sm
                JOIN scrapes s ON s.scrape_id = sm.scrape_id
                WHERE sm.provider_id = ? AND sm.provider_model_id = ?
                ORDER BY datetime(s.completed_at) ASC, s.scrape_id ASC
                """,
                (provider_id, model_id),
            ).fetchall()
            change_rows = connection.execute(
                """
                SELECT detected_at, change_kind, field_name, old_value_json, new_value_json
                FROM field_changes
                WHERE provider_id = ? AND provider_model_id = ?
                ORDER BY datetime(detected_at) ASC, change_id ASC
                """,
                (provider_id, model_id),
            ).fetchall()
        first_seen = snapshot_rows[0]["completed_at"] if snapshot_rows else None
        last_seen = snapshot_rows[-1]["completed_at"] if snapshot_rows else None
        events: list[HistoryEvent] = []
        for row in change_rows:
            detected_at = row["detected_at"]
            detected_date = local_date_for(detected_at)
            if since and detected_date < since:
                continue
            if until and detected_date > until:
                continue
            events.append(
                HistoryEvent(
                    detected_at=detected_at,
                    change_kind=row["change_kind"],
                    field_name=row["field_name"],
                    old_value=_load_json_value(row["old_value_json"]),
                    new_value=_load_json_value(row["new_value_json"]),
                )
            )
        return first_seen, last_seen, tuple(events)

    def list_known_models(
        self,
        *,
        provider_id: str,
        since: date | None,
        until: date | None,
    ) -> tuple[dict[str, str | None], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    sm.provider_model_id,
                    MAX(sm.display_name) AS display_name,
                    MIN(s.completed_at) AS first_seen,
                    MAX(s.completed_at) AS last_seen
                FROM snapshot_models sm
                JOIN scrapes s ON s.scrape_id = sm.scrape_id
                WHERE sm.provider_id = ?
                GROUP BY sm.provider_model_id
                ORDER BY sm.provider_model_id ASC
                """,
                (provider_id,),
            ).fetchall()
        models: list[dict[str, str | None]] = []
        for row in rows:
            first_seen = row["first_seen"]
            last_seen = row["last_seen"]
            if first_seen is None or last_seen is None:
                continue
            first_date = local_date_for(first_seen)
            last_date = local_date_for(last_seen)
            if since and last_date < since:
                continue
            if until and first_date > until:
                continue
            latest = self.get_latest_model_snapshot(provider_id=provider_id, model_id=row["provider_model_id"])
            models.append(
                {
                    "provider_model_id": row["provider_model_id"],
                    "provider_id": provider_id,
                    "display_name": latest["display_name"] if latest else row["display_name"],
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                    "input_price": latest["input_price"] if latest else None,
                    "output_price": latest["output_price"] if latest else None,
                    "cache_read_price": latest["cache_read_price"] if latest else None,
                    "cache_write_price": latest["cache_write_price"] if latest else None,
                }
            )
        return tuple(models)

    def get_latest_model_snapshot(self, *, provider_id: str, model_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    sm.display_name,
                    sm.input_price,
                    sm.output_price,
                    sm.cache_read_price,
                    sm.cache_write_price,
                    s.completed_at
                FROM snapshot_models sm
                JOIN scrapes s ON s.scrape_id = sm.scrape_id
                WHERE sm.provider_id = ? AND sm.provider_model_id = ?
                ORDER BY datetime(s.completed_at) DESC, s.scrape_id DESC
                LIMIT 1
                """,
                (provider_id, model_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "provider_id": provider_id,
            "display_name": row["display_name"],
            "input_price": row["input_price"],
            "output_price": row["output_price"],
            "cache_read_price": row["cache_read_price"],
            "cache_write_price": row["cache_write_price"],
            "completed_at": row["completed_at"],
        }

    def recent_changes(
        self,
        *,
        provider_id: str | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            query = """
                SELECT fc.provider_id, fc.provider_model_id, fc.change_kind,
                       fc.field_name, fc.old_value_json, fc.new_value_json,
                       fc.detected_at, p.label AS provider_label,
                       (
                           SELECT sm.display_name
                           FROM snapshot_models sm
                           JOIN scrapes s ON s.scrape_id = sm.scrape_id
                           WHERE sm.provider_id = fc.provider_id
                             AND sm.provider_model_id = fc.provider_model_id
                           ORDER BY datetime(s.completed_at) DESC, s.scrape_id DESC
                           LIMIT 1
                       ) AS display_name
                FROM field_changes fc
                JOIN providers p ON p.provider_id = fc.provider_id
                WHERE fc.from_scrape_id IS NOT NULL
                ORDER BY datetime(fc.detected_at) ASC, fc.provider_id,
                         fc.provider_model_id, fc.change_id
            """
            rows = connection.execute(query).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            detected_at = row["detected_at"]
            detected_date = local_date_for(detected_at)
            if since and detected_date < since:
                continue
            if until and detected_date > until:
                continue
            if provider_id and row["provider_id"] != provider_id:
                continue

            display_name = row["display_name"] or row["provider_model_id"]

            results.append({
                "provider_id": row["provider_id"],
                "provider_label": row["provider_label"],
                "provider_model_id": row["provider_model_id"],
                "display_name": display_name,
                "change_kind": row["change_kind"],
                "field_name": row["field_name"],
                "old_value": _load_json_value(row["old_value_json"]),
                "new_value": _load_json_value(row["new_value_json"]),
                "detected_at": detected_at,
            })
        return tuple(results)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _maybe_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _from_db_bool(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _load_json_value(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)
