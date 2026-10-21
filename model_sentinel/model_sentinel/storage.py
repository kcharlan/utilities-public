from __future__ import annotations

import gzip
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .conditional_pricing import StoredComparisonIdentity
from .config import ProviderConfig
from .endpoints import (
    COMPARISON_AVAILABLE,
    ENDPOINT_ADDED,
    ENDPOINT_REMOVED,
    endpoint_state_hash,
    sanitize_endpoint_error_message,
)
from .models import (
    BaselineInfo,
    EndpointCaptureCandidate,
    EndpointCaptureSummary,
    EndpointChangeRecord,
    EndpointComparisonGap,
    EndpointListRecord,
    EndpointMapping,
    EndpointObservationRecord,
    FieldChange,
    HistoryEvent,
    ModelDelta,
    NormalizedModel,
    canonical_json,
)
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
    """
    CREATE TABLE IF NOT EXISTS endpoint_captures (
        capture_id INTEGER PRIMARY KEY AUTOINCREMENT,
        scrape_id INTEGER NOT NULL UNIQUE,
        provider_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('complete', 'partial', 'error')),
        paths_requested INTEGER NOT NULL CHECK (paths_requested >= 0),
        paths_attempted INTEGER NOT NULL
            CHECK (paths_attempted >= 0 AND paths_attempted <= paths_requested),
        paths_failed INTEGER NOT NULL
            CHECK (paths_failed >= 0 AND paths_failed <= paths_requested),
        mapping_failures INTEGER NOT NULL CHECK (mapping_failures >= 0),
        first_capture INTEGER NOT NULL CHECK (first_capture IN (0, 1)),
        comparison_state TEXT NOT NULL CHECK (comparison_state IN (
            'available', 'no_selected_baseline', 'missing_baseline_capture', 'unusable_baseline'
        )),
        baseline_capture_id INTEGER,
        error_summary TEXT,
        CHECK (
            (comparison_state IN ('available', 'unusable_baseline'))
            = (baseline_capture_id IS NOT NULL)
        ),
        FOREIGN KEY (scrape_id) REFERENCES scrapes(scrape_id),
        FOREIGN KEY (baseline_capture_id) REFERENCES endpoint_captures(capture_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS endpoint_lists (
        capture_id INTEGER NOT NULL,
        list_path TEXT NOT NULL,
        list_model_id TEXT,
        outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'empty', 'error')),
        endpoint_count INTEGER NOT NULL CHECK (endpoint_count >= 0),
        error_code TEXT,
        error_message TEXT,
        CHECK (
            (outcome = 'ok' AND endpoint_count > 0)
            OR (outcome IN ('empty', 'error') AND endpoint_count = 0)
        ),
        PRIMARY KEY (capture_id, list_path),
        FOREIGN KEY (capture_id) REFERENCES endpoint_captures(capture_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS endpoint_capture_models (
        capture_id INTEGER NOT NULL,
        provider_model_id TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK (outcome IN ('listed', 'alias', 'no_link', 'invalid_link')),
        list_path TEXT,
        alias_target_model_id TEXT,
        error_code TEXT,
        PRIMARY KEY (capture_id, provider_model_id),
        FOREIGN KEY (capture_id) REFERENCES endpoint_captures(capture_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS endpoint_states (
        state_hash TEXT PRIMARY KEY,
        state_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS endpoint_observations (
        capture_id INTEGER NOT NULL,
        list_path TEXT NOT NULL,
        endpoint_key TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        status_code INTEGER,
        PRIMARY KEY (capture_id, list_path, endpoint_key),
        FOREIGN KEY (capture_id, list_path) REFERENCES endpoint_lists(capture_id, list_path),
        FOREIGN KEY (state_hash) REFERENCES endpoint_states(state_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS endpoint_changes (
        endpoint_change_id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id TEXT NOT NULL,
        from_capture_id INTEGER NOT NULL,
        to_capture_id INTEGER NOT NULL,
        from_list_path TEXT NOT NULL,
        list_path TEXT NOT NULL,
        endpoint_key TEXT NOT NULL,
        change_kind TEXT NOT NULL CHECK (change_kind IN (
            'endpoint_added', 'endpoint_removed', 'field_changed', 'status_changed'
        )),
        field_name TEXT,
        old_value_json TEXT,
        new_value_json TEXT,
        detected_at TEXT NOT NULL,
        FOREIGN KEY (from_capture_id) REFERENCES endpoint_captures(capture_id),
        FOREIGN KEY (to_capture_id) REFERENCES endpoint_captures(capture_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS endpoint_comparison_gaps (
        capture_id INTEGER NOT NULL,
        list_path TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (reason IN (
            'baseline_observation_failed', 'current_observation_failed',
            'new_path_unpaired', 'removed_path_unpaired', 'ambiguous_mapping'
        )),
        from_list_path TEXT,
        PRIMARY KEY (capture_id, list_path, reason),
        FOREIGN KEY (capture_id) REFERENCES endpoint_captures(capture_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS endpoint_capture_archives (
        capture_id INTEGER PRIMARY KEY,
        body_gzip BLOB NOT NULL,
        FOREIGN KEY (capture_id) REFERENCES endpoint_captures(capture_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_endpoint_changes_provider_list_capture
        ON endpoint_changes (provider_id, list_path, to_capture_id)
    """,
)


@dataclass(frozen=True)
class StoredChangeRecord:
    """One exact persisted field-change row in source ``change_id`` order."""

    change_id: int
    provider_id: str
    provider_model_id: str
    from_scrape_id: int | None
    to_scrape_id: int
    change_kind: str
    field_name: str | None
    old_value: Any
    new_value: Any
    detected_at: str


@dataclass(frozen=True)
class StoredComparisonEvent:
    """Exact source/target snapshot envelope for one persisted comparison edge."""

    identity: StoredComparisonIdentity
    provider_label: str
    display_name: str
    detected_at: str
    from_completed_at: str | None
    to_completed_at: str | None
    source_rows: tuple[StoredChangeRecord, ...]
    field_changes: tuple[FieldChange, ...]
    old_model_metadata: dict[str, Any] | None
    new_model_metadata: dict[str, Any] | None

    @property
    def provider_id(self) -> str:
        return self.identity.provider_id

    @property
    def provider_model_id(self) -> str:
        return self.identity.provider_model_id


@dataclass(frozen=True)
class _StoredEdgeEnvelope:
    identity: StoredComparisonIdentity
    provider_label: str
    display_name: str
    detected_at: str
    from_completed_at: str | None
    to_completed_at: str | None
    old_model_metadata: dict[str, Any] | None
    new_model_metadata: dict[str, Any] | None


class StoredComparisonDataError(RuntimeError):
    """Exact-side persisted data cannot form a deterministic comparison event."""


class EndpointCaptureIntegrityError(RuntimeError):
    """An endpoint capture write was refused before anything was saved.

    Raised when foreign-key enforcement cannot be enabled on the write
    connection, or when the capture does not reference a saved success scrape
    of its provider and that scrape's selected baseline capture.
    """


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

    def history_comparison_events(
        self,
        *,
        provider_id: str,
        model_id: str,
        since: date | None,
        until: date | None,
    ) -> tuple[StoredComparisonEvent, ...]:
        """Load exact persisted comparison edges for a model's human history."""
        with self._connect() as connection:
            envelopes = _comparison_event_envelopes(
                connection,
                provider_id=provider_id,
                model_id=model_id,
                since=since,
                until=until,
                exclude_initial=False,
            )
            rows = _selected_comparison_change_rows(
                connection,
                tuple(envelope.identity for envelope in envelopes),
                provider_id=provider_id,
                model_id=model_id,
                since=since,
                until=until,
                exclude_initial=False,
            )
        return _build_comparison_events(envelopes, rows)

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
            rows = recent_change_rows(
                connection,
                provider_id=provider_id,
                since=since,
                until=until,
            )
        return tuple({key: value for key, value in row.items() if key != "change_id"} for row in rows)

    def recent_comparison_events(
        self,
        *,
        provider_id: str | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> tuple[StoredComparisonEvent, ...]:
        """Load exact non-initial comparison edges for human changes reports."""
        with self._connect() as connection:
            envelopes = _comparison_event_envelopes(
                connection,
                provider_id=provider_id,
                model_id=None,
                since=since,
                until=until,
                exclude_initial=True,
            )
            rows = _selected_comparison_change_rows(
                connection,
                tuple(envelope.identity for envelope in envelopes),
                provider_id=provider_id,
                model_id=None,
                since=since,
                until=until,
                exclude_initial=True,
            )
        return _build_comparison_events(envelopes, rows)

    def save_endpoint_capture(self, candidate: EndpointCaptureCandidate) -> EndpointCaptureSummary:
        """Persist one endpoint capture and return it as persisted.

        Inside one `BEGIN IMMEDIATE` transaction on a foreign-key-enforcing
        connection this validates the referenced scrape and baseline capture,
        assigns `first_capture` from the provider's persisted captures, and
        writes the capture, mappings, lists, states, observations, archive,
        comparison gaps and changes, then commits once. Any failure rolls the
        whole capture back and is re-raised; the summary is returned only
        after the commit succeeded. A second capture for the same scrape is
        rejected by the unique `scrape_id`.
        """
        summary = candidate.summary
        _validate_capture_summary(summary)
        with closing(self._connect_capture_writer()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _validate_capture_references(connection, summary)
                capture_id = _insert_capture_row(connection, summary)
                _write_capture_models(connection, capture_id=capture_id, mappings=candidate.mappings)
                _write_endpoint_lists(connection, capture_id=capture_id, lists=summary.lists)
                connection.execute(
                    "INSERT INTO endpoint_capture_archives (capture_id, body_gzip) VALUES (?, ?)",
                    (capture_id, _capture_archive_blob(candidate.archive)),
                )
                _write_comparison_gaps(connection, capture_id=capture_id, gaps=summary.comparison_gaps)
                _write_endpoint_changes(
                    connection,
                    provider_id=summary.provider_id,
                    to_capture_id=capture_id,
                    detected_at=to_storage_timestamp(summary.completed_at),
                    changes=summary.changes,
                )
                connection.execute("COMMIT")
            except BaseException:
                _rollback(connection)
                raise
            return _load_capture_summary(connection, capture_id)

    def save_endpoint_error_capture(self, summary: EndpointCaptureSummary) -> EndpointCaptureSummary:
        """Persist a minimal error capture; never raises.

        `summary` comes from `endpoints.build_endpoint_error_summary`. In a new
        transaction, a capture already committed for the scrape is reused and
        returned unchanged rather than replaced. Otherwise only the capture row
        is written, under the same reference validation and `first_capture`
        rule as `save_endpoint_capture`. When persistence fails, the
        in-memory summary is returned with `capture_id` None and a sanitized
        `persistence_error`; the caller logs it.
        """
        try:
            _validate_capture_summary(summary)
            if summary.lists or summary.changes or summary.comparison_gaps:
                raise ValueError("a minimal error capture has no lists, changes or gaps")
            with closing(self._connect_capture_writer()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT capture_id FROM endpoint_captures WHERE scrape_id = ?",
                        (summary.scrape_id,),
                    ).fetchone()
                    if existing is not None:
                        capture_id = int(existing["capture_id"])
                    else:
                        _validate_capture_references(connection, summary)
                        capture_id = _insert_capture_row(connection, summary)
                    connection.execute("COMMIT")
                except BaseException:
                    _rollback(connection)
                    raise
                return _load_capture_summary(connection, capture_id)
        except Exception as exc:
            return replace(
                summary,
                capture_id=None,
                persistence_error=sanitize_endpoint_error_message(
                    f"endpoint error capture was not saved: {type(exc).__name__}: {exc}"
                ),
            )

    def get_endpoint_capture_for_scrape(self, scrape_id: int) -> EndpointCaptureSummary | None:
        """Return the capture saved for exactly this catalog scrape, if any."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM endpoint_captures WHERE scrape_id = ?",
                (scrape_id,),
            ).fetchone()
            if row is None:
                return None
            return _capture_summary_from_row(connection, row)

    def get_latest_endpoint_capture(self, provider_id: str) -> EndpointCaptureSummary | None:
        """Return the provider's most recently completed capture, if any."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM endpoint_captures
                WHERE provider_id = ?
                ORDER BY datetime(completed_at) DESC, capture_id DESC
                LIMIT 1
                """,
                (provider_id,),
            ).fetchone()
            if row is None:
                return None
            return _capture_summary_from_row(connection, row)

    def load_endpoint_lists(self, capture_id: int) -> tuple[EndpointListRecord, ...]:
        """Return a capture's lists with their mapped models and observations."""
        with self._connect() as connection:
            return _load_endpoint_lists(connection, capture_id)

    def _connect_capture_writer(self) -> sqlite3.Connection:
        """Open a capture-write connection with verified foreign-key enforcement.

        The connection is in autocommit mode so the caller issues its own
        `BEGIN IMMEDIATE` and single `COMMIT`. This policy is local to
        capture writes; other Store connections are unchanged.
        """
        connection = sqlite3.connect(self.database_path, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            enabled = connection.execute("PRAGMA foreign_keys").fetchone()
            if enabled is None or enabled[0] != 1:
                raise EndpointCaptureIntegrityError(
                    "SQLite foreign key enforcement could not be enabled for an endpoint capture write"
                )
        except BaseException:
            connection.close()
            raise
        return connection

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _rollback(connection: sqlite3.Connection) -> None:
    """Roll back an open transaction without masking the error being handled."""
    if not connection.in_transaction:
        return
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass  # Closing the connection discards the transaction anyway.


def _validate_capture_summary(summary: EndpointCaptureSummary) -> None:
    """Check the in-memory summary is a new capture whose comparison is consistent."""
    if summary.capture_id is not None:
        raise ValueError("endpoint capture has already been persisted")
    if (summary.changes or summary.comparison_gaps) and summary.comparison_state != COMPARISON_AVAILABLE:
        raise ValueError("endpoint changes and gaps require an available comparison")
    if any(change.from_capture_id != summary.baseline_capture_id for change in summary.changes):
        raise ValueError("endpoint changes must come from the selected baseline capture")


def _validate_capture_references(connection: sqlite3.Connection, summary: EndpointCaptureSummary) -> None:
    """Require a saved success scrape of the provider and its selected baseline capture."""
    scrape = connection.execute(
        "SELECT provider_id, status, saved_snapshot, baseline_scrape_id FROM scrapes WHERE scrape_id = ?",
        (summary.scrape_id,),
    ).fetchone()
    if (
        scrape is None
        or scrape["provider_id"] != summary.provider_id
        or scrape["status"] != "success"
        or scrape["saved_snapshot"] != 1
    ):
        raise EndpointCaptureIntegrityError(
            "endpoint capture must reference a saved success scrape of the same provider"
        )
    if summary.baseline_capture_id is None:
        return
    baseline = connection.execute(
        "SELECT provider_id, scrape_id FROM endpoint_captures WHERE capture_id = ?",
        (summary.baseline_capture_id,),
    ).fetchone()
    if baseline is None or baseline["provider_id"] != summary.provider_id:
        raise EndpointCaptureIntegrityError("baseline capture must belong to the same provider")
    if baseline["scrape_id"] != scrape["baseline_scrape_id"]:
        raise EndpointCaptureIntegrityError(
            "baseline capture must belong to the scrape's selected baseline scrape"
        )


def _insert_capture_row(connection: sqlite3.Connection, summary: EndpointCaptureSummary) -> int:
    """Insert the capture row, assigning `first_capture` from persisted captures."""
    earlier = connection.execute(
        "SELECT 1 FROM endpoint_captures WHERE provider_id = ? LIMIT 1",
        (summary.provider_id,),
    ).fetchone()
    cursor = connection.execute(
        """
        INSERT INTO endpoint_captures (
            scrape_id, provider_id, started_at, completed_at, status,
            paths_requested, paths_attempted, paths_failed, mapping_failures,
            first_capture, comparison_state, baseline_capture_id, error_summary
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            summary.scrape_id,
            summary.provider_id,
            to_storage_timestamp(summary.started_at),
            to_storage_timestamp(summary.completed_at),
            summary.status,
            summary.paths_requested,
            summary.paths_attempted,
            summary.paths_failed,
            summary.mapping_failures,
            int(earlier is None),
            summary.comparison_state,
            summary.baseline_capture_id,
            None if summary.error_summary is None else sanitize_endpoint_error_message(summary.error_summary),
        ),
    )
    return int(cursor.lastrowid)


def _write_capture_models(
    connection: sqlite3.Connection,
    *,
    capture_id: int,
    mappings: Sequence[EndpointMapping],
) -> None:
    connection.executemany(
        """
        INSERT INTO endpoint_capture_models (
            capture_id, provider_model_id, outcome, list_path, alias_target_model_id, error_code
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                capture_id,
                mapping.provider_model_id,
                mapping.outcome,
                mapping.list_path,
                mapping.alias_target_model_id,
                mapping.error_code,
            )
            for mapping in mappings
        ],
    )


def _write_endpoint_lists(
    connection: sqlite3.Connection,
    *,
    capture_id: int,
    lists: Sequence[EndpointListRecord],
) -> None:
    """Write lists, their deduplicated stable states, and observations in response order."""
    for listing in lists:
        connection.execute(
            """
            INSERT INTO endpoint_lists (
                capture_id, list_path, list_model_id, outcome, endpoint_count, error_code, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capture_id,
                listing.list_path,
                listing.list_model_id,
                listing.outcome,
                listing.endpoint_count,
                listing.error_code,
                None if listing.error_message is None else sanitize_endpoint_error_message(listing.error_message),
            ),
        )
        for observation in listing.observations:
            if endpoint_state_hash(observation.state) != observation.state_hash:
                raise ValueError("endpoint observation state does not match its state hash")
            connection.execute(
                "INSERT OR IGNORE INTO endpoint_states (state_hash, state_json) VALUES (?, ?)",
                (observation.state_hash, canonical_json(observation.state)),
            )
            connection.execute(
                """
                INSERT INTO endpoint_observations (capture_id, list_path, endpoint_key, state_hash, status_code)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    listing.list_path,
                    observation.endpoint_key,
                    observation.state_hash,
                    observation.status_code,
                ),
            )


def _capture_archive_blob(archive: Mapping[str, Any]) -> bytes:
    """Gzip the canonical JSON of the decoded response bodies, keyed by path."""
    return gzip.compress(canonical_json(dict(archive)).encode("utf-8"), mtime=0)


def _write_comparison_gaps(
    connection: sqlite3.Connection,
    *,
    capture_id: int,
    gaps: Sequence[EndpointComparisonGap],
) -> None:
    connection.executemany(
        """
        INSERT INTO endpoint_comparison_gaps (capture_id, list_path, reason, from_list_path)
        VALUES (?, ?, ?, ?)
        """,
        [(capture_id, gap.list_path, gap.reason, gap.from_list_path) for gap in gaps],
    )


def _write_endpoint_changes(
    connection: sqlite3.Connection,
    *,
    provider_id: str,
    to_capture_id: int,
    detected_at: str,
    changes: Sequence[EndpointChangeRecord],
) -> None:
    """Insert change rows on the caller's transaction; never commits.

    The absent side of an added or removed endpoint is NULL; every other value
    is stored as JSON, so a change to or from null keeps the literal `null`.
    """
    connection.executemany(
        """
        INSERT INTO endpoint_changes (
            provider_id, from_capture_id, to_capture_id, from_list_path, list_path,
            endpoint_key, change_kind, field_name, old_value_json, new_value_json, detected_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                provider_id,
                change.from_capture_id,
                to_capture_id,
                change.from_list_path,
                change.list_path,
                change.endpoint_key,
                change.change_kind,
                change.field_name,
                None if change.change_kind == ENDPOINT_ADDED else _change_value_json(change.old_value),
                None if change.change_kind == ENDPOINT_REMOVED else _change_value_json(change.new_value),
                detected_at,
            )
            for change in changes
        ],
    )


def _change_value_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def _load_capture_summary(connection: sqlite3.Connection, capture_id: int) -> EndpointCaptureSummary:
    row = connection.execute(
        "SELECT * FROM endpoint_captures WHERE capture_id = ?",
        (capture_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("persisted endpoint capture could not be read back")
    return _capture_summary_from_row(connection, row)


def _capture_summary_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> EndpointCaptureSummary:
    capture_id = int(row["capture_id"])
    lists = _load_endpoint_lists(connection, capture_id)
    lists_by_path = {listing.list_path: listing for listing in lists}
    gaps = tuple(
        EndpointComparisonGap(gap["list_path"], gap["reason"], gap["from_list_path"])
        for gap in connection.execute(
            """
            SELECT list_path, reason, from_list_path
            FROM endpoint_comparison_gaps
            WHERE capture_id = ?
            ORDER BY list_path, reason
            """,
            (capture_id,),
        )
    )
    changes: list[EndpointChangeRecord] = []
    for change in connection.execute(
        "SELECT * FROM endpoint_changes WHERE to_capture_id = ? ORDER BY endpoint_change_id",
        (capture_id,),
    ):
        listing = lists_by_path.get(change["list_path"])
        changes.append(
            EndpointChangeRecord(
                from_capture_id=int(change["from_capture_id"]),
                to_capture_id=capture_id,
                from_list_path=change["from_list_path"],
                list_path=change["list_path"],
                endpoint_key=change["endpoint_key"],
                change_kind=change["change_kind"],
                field_name=change["field_name"],
                old_value=load_json_value(change["old_value_json"]),
                new_value=load_json_value(change["new_value_json"]),
                display_id=listing.display_id if listing is not None else change["list_path"],
                model_ids=listing.model_ids if listing is not None else (),
            )
        )
    return EndpointCaptureSummary(
        capture_id=capture_id,
        scrape_id=int(row["scrape_id"]),
        provider_id=row["provider_id"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        status=row["status"],
        paths_requested=int(row["paths_requested"]),
        paths_attempted=int(row["paths_attempted"]),
        paths_failed=int(row["paths_failed"]),
        mapping_failures=int(row["mapping_failures"]),
        first_capture=bool(row["first_capture"]),
        comparison_state=row["comparison_state"],
        baseline_capture_id=row["baseline_capture_id"],
        error_summary=row["error_summary"],
        changes=tuple(changes),
        comparison_gaps=gaps,
        lists=lists,
    )


def _load_endpoint_lists(
    connection: sqlite3.Connection,
    capture_id: int,
    *,
    list_path: str | None = None,
) -> tuple[EndpointListRecord, ...]:
    """Load lists in path order with listed model IDs and response-ordered observations.

    Observations have no position column; their insertion order is the
    response order, read back through `rowid`. `list_path` limits the load to
    that one list (an empty result when the capture has no such list).
    """
    path_filter = (list_path, list_path)
    model_ids: dict[str, list[str]] = {}
    for mapping in connection.execute(
        """
        SELECT list_path, provider_model_id
        FROM endpoint_capture_models
        WHERE capture_id = ? AND outcome = 'listed'
          AND (? IS NULL OR list_path = ?)
        ORDER BY provider_model_id
        """,
        (capture_id, *path_filter),
    ):
        model_ids.setdefault(mapping["list_path"], []).append(mapping["provider_model_id"])
    observations: dict[str, list[EndpointObservationRecord]] = {}
    for observation in connection.execute(
        """
        SELECT o.list_path, o.endpoint_key, o.state_hash, o.status_code, s.state_json
        FROM endpoint_observations o
        JOIN endpoint_states s ON s.state_hash = o.state_hash
        WHERE o.capture_id = ?
          AND (? IS NULL OR o.list_path = ?)
        ORDER BY o.list_path, o.rowid
        """,
        (capture_id, *path_filter),
    ):
        observations.setdefault(observation["list_path"], []).append(
            EndpointObservationRecord(
                endpoint_key=observation["endpoint_key"],
                state_hash=observation["state_hash"],
                state=json.loads(observation["state_json"]),
                status_code=observation["status_code"],
            )
        )
    return tuple(
        EndpointListRecord(
            list_path=listing["list_path"],
            list_model_id=listing["list_model_id"],
            outcome=listing["outcome"],
            endpoint_count=int(listing["endpoint_count"]),
            error_code=listing["error_code"],
            error_message=listing["error_message"],
            model_ids=tuple(model_ids.get(listing["list_path"], ())),
            observations=tuple(observations.get(listing["list_path"], ())),
        )
        for listing in connection.execute(
            """
            SELECT list_path, list_model_id, outcome, endpoint_count, error_code, error_message
            FROM endpoint_lists
            WHERE capture_id = ?
              AND (? IS NULL OR list_path = ?)
            ORDER BY list_path
            """,
            (capture_id, *path_filter),
        )
    )


def _maybe_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _from_db_bool(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _coarse_comparison_filter(
    *,
    alias: str,
    provider_id: str | None,
    model_id: str | None,
    since: date | None,
    until: date | None,
    exclude_initial: bool,
) -> tuple[str, list[str]]:
    """Build the shared conservative UTC envelope used by both rich queries."""
    predicates: list[str] = []
    parameters: list[str] = []
    if provider_id is not None:
        predicates.append(f"{alias}.provider_id = ?")
        parameters.append(provider_id)
    if model_id is not None:
        predicates.append(f"{alias}.provider_model_id = ?")
        parameters.append(model_id)
    if exclude_initial:
        predicates.append(f"{alias}.from_scrape_id IS NOT NULL")
    if since is not None:
        lower_bound = (datetime.combine(since, time.min) - timedelta(days=1)).isoformat()
        predicates.append(
            f"({alias}.detected_at >= ? OR {alias}.detected_at IS NULL "
            f"OR datetime({alias}.detected_at) IS NULL)"
        )
        parameters.append(lower_bound)
    if until is not None:
        upper_bound = (datetime.combine(until, time.max) + timedelta(days=1)).isoformat()
        predicates.append(
            f"({alias}.detected_at <= ? OR {alias}.detected_at IS NULL "
            f"OR datetime({alias}.detected_at) IS NULL)"
        )
        parameters.append(upper_bound)
    if not predicates:
        return "", parameters
    return "WHERE " + " AND ".join(predicates), parameters


def _comparison_event_envelopes(
    connection: sqlite3.Connection,
    *,
    provider_id: str | None,
    model_id: str | None,
    since: date | None,
    until: date | None,
    exclude_initial: bool,
) -> tuple[_StoredEdgeEnvelope, ...]:
    """Load one exact-side envelope per loosely date-bounded edge."""
    where_clause, parameters = _coarse_comparison_filter(
        alias="bounded",
        provider_id=provider_id,
        model_id=model_id,
        since=since,
        until=until,
        exclude_initial=exclude_initial,
    )

    rows = connection.execute(
        f"""
        WITH bounded_edges AS (
            SELECT DISTINCT
                   bounded.provider_id,
                   bounded.provider_model_id,
                   bounded.from_scrape_id,
                   bounded.to_scrape_id
            FROM field_changes bounded
            {where_clause}
        ),
        candidate_edges AS (
            SELECT
                fc.provider_id,
                fc.provider_model_id,
                fc.from_scrape_id,
                fc.to_scrape_id,
                MIN(fc.change_id) AS first_change_id,
                MIN(fc.detected_at) AS detected_at,
                COUNT(*) AS row_count,
                COUNT(fc.detected_at) AS nonnull_detected_at_count,
                COUNT(DISTINCT fc.detected_at) AS distinct_detected_at_count,
                SUM(CASE WHEN fc.change_kind IN ('added', 'removed') THEN 1 ELSE 0 END)
                    AS presence_row_count,
                SUM(CASE WHEN fc.change_kind = 'field_changed' THEN 1 ELSE 0 END)
                    AS changed_row_count,
                SUM(CASE
                    WHEN fc.change_kind IN ('added', 'removed', 'field_changed') THEN 0
                    ELSE 1
                END) AS invalid_kind_count,
                SUM(CASE
                    WHEN fc.change_kind IN ('added', 'removed')
                     AND (fc.field_name IS NOT NULL
                          OR fc.old_value_json IS NOT NULL
                          OR fc.new_value_json IS NOT NULL)
                    THEN 1 ELSE 0
                END) AS invalid_presence_payload_count
            FROM bounded_edges bounded
            JOIN field_changes fc
              ON fc.provider_id IS bounded.provider_id
             AND fc.provider_model_id IS bounded.provider_model_id
             AND fc.from_scrape_id IS bounded.from_scrape_id
             AND fc.to_scrape_id IS bounded.to_scrape_id
            GROUP BY fc.provider_id, fc.provider_model_id,
                     fc.from_scrape_id, fc.to_scrape_id
        )
        SELECT
            candidate.*,
            provider.label AS provider_label,
            source_scrape.completed_at AS from_completed_at,
            target_scrape.completed_at AS to_completed_at,
            CASE WHEN source_model.rowid IS NULL THEN 0 ELSE 1 END AS source_model_count,
            CASE WHEN target_model.rowid IS NULL THEN 0 ELSE 1 END AS target_model_count,
            source_model.display_name AS source_display_name,
            target_model.display_name AS target_display_name,
            source_model.metadata_json AS source_metadata_json,
            target_model.metadata_json AS target_metadata_json
        FROM candidate_edges candidate
        LEFT JOIN providers provider
          ON provider.provider_id = candidate.provider_id
        LEFT JOIN scrapes source_scrape
          ON source_scrape.scrape_id = candidate.from_scrape_id
         AND source_scrape.provider_id = candidate.provider_id
        LEFT JOIN scrapes target_scrape
          ON target_scrape.scrape_id = candidate.to_scrape_id
         AND target_scrape.provider_id = candidate.provider_id
        LEFT JOIN snapshot_models source_model
          ON source_model.scrape_id = candidate.from_scrape_id
         AND source_model.provider_id = candidate.provider_id
         AND source_model.provider_model_id = candidate.provider_model_id
        LEFT JOIN snapshot_models target_model
          ON target_model.scrape_id = candidate.to_scrape_id
         AND target_model.provider_id = candidate.provider_id
         AND target_model.provider_model_id = candidate.provider_model_id
        ORDER BY candidate.detected_at ASC,
                 candidate.provider_id ASC,
                 candidate.provider_model_id ASC,
                 candidate.first_change_id ASC
        """,
        parameters,
    ).fetchall()

    envelopes: list[_StoredEdgeEnvelope] = []
    seen_identities: set[StoredComparisonIdentity] = set()
    for row in rows:
        identity = _identity_from_values(
            row["provider_id"],
            row["provider_model_id"],
            row["from_scrape_id"],
            row["to_scrape_id"],
        )
        if identity in seen_identities:
            raise StoredComparisonDataError(
                f"stored comparison edge {_edge_description(identity)} has duplicate exact-side snapshot rows"
            )
        seen_identities.add(identity)
        if (
            row["row_count"] != row["nonnull_detected_at_count"]
            or row["distinct_detected_at_count"] != 1
        ):
            raise StoredComparisonDataError(
                f"stored comparison edge {_edge_description(identity)} has inconsistent detected_at values"
            )
        detected_at = _validated_detected_at(row["detected_at"], identity=identity)
        detected_date = _local_date_for_edge(detected_at, identity=identity)
        if since is not None and detected_date < since:
            continue
        if until is not None and detected_date > until:
            continue

        _validate_stored_edge_shape(row, identity=identity)
        from_completed_at = _validated_optional_completed_at(
            row["from_completed_at"],
            identity=identity,
            field_name="from_completed_at",
        )
        to_completed_at = _validated_optional_completed_at(
            row["to_completed_at"],
            identity=identity,
            field_name="to_completed_at",
        )

        old_metadata = _exact_side_metadata(
            count=row["source_model_count"],
            value=row["source_metadata_json"],
            identity=identity,
            side="source",
        )
        new_metadata = _exact_side_metadata(
            count=row["target_model_count"],
            value=row["target_metadata_json"],
            identity=identity,
            side="target",
        )
        envelopes.append(
            _StoredEdgeEnvelope(
                identity=identity,
                provider_label=row["provider_label"] or identity.provider_id,
                display_name=(
                    row["target_display_name"]
                    or row["source_display_name"]
                    or identity.provider_model_id
                ),
                detected_at=detected_at,
                from_completed_at=from_completed_at,
                to_completed_at=to_completed_at,
                old_model_metadata=old_metadata,
                new_model_metadata=new_metadata,
            )
        )
    return tuple(envelopes)


def _selected_comparison_change_rows(
    connection: sqlite3.Connection,
    identities: tuple[StoredComparisonIdentity, ...],
    *,
    provider_id: str | None,
    model_id: str | None,
    since: date | None,
    until: date | None,
    exclude_initial: bool,
) -> tuple[tuple[int, sqlite3.Row], ...]:
    """Refetch possible bounded rows and select exact identities in linear time."""
    where_clause, parameters = _coarse_comparison_filter(
        alias="possible",
        provider_id=provider_id,
        model_id=model_id,
        since=since,
        until=until,
        exclude_initial=exclude_initial,
    )
    rows = connection.execute(
        f"""
        SELECT
            possible.change_id,
            possible.provider_id,
            possible.provider_model_id,
            possible.from_scrape_id,
            possible.to_scrape_id,
            possible.change_kind,
            possible.field_name,
            possible.old_value_json,
            possible.new_value_json,
            possible.detected_at
        FROM field_changes possible
        {where_clause}
        ORDER BY possible.detected_at ASC,
                 possible.provider_id ASC,
                 possible.provider_model_id ASC,
                 possible.change_id ASC
        """,
        parameters,
    ).fetchall()
    selected_orders = {
        (
            identity.provider_id,
            identity.provider_model_id,
            identity.from_scrape_id,
            identity.to_scrape_id,
        ): edge_order
        for edge_order, identity in enumerate(identities)
    }
    selected_rows: list[tuple[int, sqlite3.Row]] = []
    for row in rows:
        edge_order = _selected_identity_order(row, selected_orders)
        if edge_order is not None:
            selected_rows.append((edge_order, row))
    return tuple(selected_rows)


def _selected_identity_order(
    row: sqlite3.Row,
    selected_orders: dict[tuple[str, str, int | None, int], int],
) -> int | None:
    return selected_orders.get(
        (
            row["provider_id"],
            row["provider_model_id"],
            row["from_scrape_id"],
            row["to_scrape_id"],
        )
    )


def _build_comparison_events(
    envelopes: tuple[_StoredEdgeEnvelope, ...],
    rows: tuple[tuple[int, sqlite3.Row], ...],
) -> tuple[StoredComparisonEvent, ...]:
    grouped_rows: list[list[sqlite3.Row]] = [[] for _ in envelopes]
    for edge_order, row in rows:
        if not isinstance(edge_order, int) or not 0 <= edge_order < len(envelopes):
            raise StoredComparisonDataError(
                "stored comparison result has invalid selected-edge row ordering"
            )
        grouped_rows[edge_order].append(row)

    events: list[StoredComparisonEvent] = []
    for envelope, edge_rows in zip(envelopes, grouped_rows, strict=True):
        if not edge_rows:
            raise StoredComparisonDataError(
                f"stored comparison edge {_edge_description(envelope.identity)} has no source rows"
            )
        source_rows = tuple(
            _stored_change_record(row, identity=envelope.identity) for row in edge_rows
        )
        if any(row.detected_at != envelope.detected_at for row in source_rows):
            raise StoredComparisonDataError(
                f"stored comparison edge {_edge_description(envelope.identity)} has inconsistent detected_at values"
            )
        events.append(
            StoredComparisonEvent(
                identity=envelope.identity,
                provider_label=envelope.provider_label,
                display_name=envelope.display_name,
                detected_at=envelope.detected_at,
                from_completed_at=envelope.from_completed_at,
                to_completed_at=envelope.to_completed_at,
                source_rows=source_rows,
                field_changes=tuple(
                    FieldChange(row.field_name, row.old_value, row.new_value)
                    for row in source_rows
                    if row.change_kind == "field_changed"
                ),
                old_model_metadata=envelope.old_model_metadata,
                new_model_metadata=envelope.new_model_metadata,
            )
        )
    return tuple(events)


def _stored_change_record(
    row: sqlite3.Row,
    *,
    identity: StoredComparisonIdentity,
) -> StoredChangeRecord:
    row_identity = _identity_from_values(
        row["provider_id"],
        row["provider_model_id"],
        row["from_scrape_id"],
        row["to_scrape_id"],
    )
    if row_identity != identity:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has a mismatched source-row identity"
        )
    change_id = row["change_id"]
    if not isinstance(change_id, int) or isinstance(change_id, bool) or change_id <= 0:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has an invalid change_id"
        )
    change_kind = row["change_kind"]
    if change_kind not in {"added", "removed", "field_changed"}:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has an invalid change_kind"
        )
    field_name = row["field_name"]
    if change_kind == "field_changed":
        if not isinstance(field_name, str) or not field_name:
            raise StoredComparisonDataError(
                f"stored comparison edge {_edge_description(identity)} has an invalid field_name"
            )
        if row["old_value_json"] is None or row["new_value_json"] is None:
            raise StoredComparisonDataError(
                f"stored comparison edge {_edge_description(identity)} has missing change JSON "
                f"at change_id {change_id}"
            )
    elif field_name is not None:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has an invalid field_name"
        )
    detected_at = _validated_detected_at(row["detected_at"], identity=identity)
    _local_date_for_edge(detected_at, identity=identity)
    return StoredChangeRecord(
        change_id=change_id,
        provider_id=identity.provider_id,
        provider_model_id=identity.provider_model_id,
        from_scrape_id=identity.from_scrape_id,
        to_scrape_id=identity.to_scrape_id,
        change_kind=change_kind,
        field_name=field_name,
        old_value=_load_stored_change_value(
            row["old_value_json"], identity=identity, change_id=change_id
        ),
        new_value=_load_stored_change_value(
            row["new_value_json"], identity=identity, change_id=change_id
        ),
        detected_at=detected_at,
    )


def _load_stored_change_value(
    value: str | None,
    *,
    identity: StoredComparisonIdentity,
    change_id: int,
) -> Any:
    try:
        return load_json_value(value)
    except (json.JSONDecodeError, TypeError):
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has malformed change JSON "
            f"at change_id {change_id}"
        ) from None


def load_model_metadata(
    value: str | None,
    *,
    identity: StoredComparisonIdentity,
    side: str,
) -> dict[str, Any] | None:
    """Decode one exact side without exposing persisted metadata on failure."""
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has malformed {side} metadata"
        ) from None
    if not isinstance(decoded, dict):
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has non-object {side} metadata"
        )
    return decoded


def _exact_side_metadata(
    *,
    count: Any,
    value: str | None,
    identity: StoredComparisonIdentity,
    side: str,
) -> dict[str, Any] | None:
    if count == 0:
        return None
    if count != 1:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has duplicate {side} snapshot rows"
        )
    if value is None:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has present {side} snapshot with NULL metadata"
        )
    return load_model_metadata(value, identity=identity, side=side)


def _identity_from_values(
    provider_id: Any,
    provider_model_id: Any,
    from_scrape_id: Any,
    to_scrape_id: Any,
) -> StoredComparisonIdentity:
    raw_description = _raw_edge_description(
        provider_id, provider_model_id, from_scrape_id, to_scrape_id
    )
    try:
        if (
            not isinstance(provider_id, str)
            or not provider_id
            or not isinstance(provider_model_id, str)
            or not provider_model_id
        ):
            raise ValueError
        if from_scrape_id is not None and (
            not isinstance(from_scrape_id, int)
            or isinstance(from_scrape_id, bool)
            or from_scrape_id <= 0
        ):
            raise ValueError
        if (
            not isinstance(to_scrape_id, int)
            or isinstance(to_scrape_id, bool)
            or to_scrape_id <= 0
        ):
            raise ValueError
        return StoredComparisonIdentity(
            provider_id=provider_id,
            provider_model_id=provider_model_id,
            from_scrape_id=from_scrape_id,
            to_scrape_id=to_scrape_id,
        )
    except (TypeError, ValueError):
        raise StoredComparisonDataError(
            f"stored comparison edge {raw_description} has an invalid identity"
        ) from None


def _validated_detected_at(
    value: Any,
    *,
    identity: StoredComparisonIdentity,
) -> str:
    if not isinstance(value, str) or not value:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has an invalid detected_at"
        )
    return value


def _validate_stored_edge_shape(
    row: sqlite3.Row,
    *,
    identity: StoredComparisonIdentity,
) -> None:
    row_count = row["row_count"]
    presence_count = row["presence_row_count"]
    changed_count = row["changed_row_count"]
    if row["invalid_kind_count"]:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has an invalid change_kind"
        )
    if presence_count:
        if changed_count:
            raise StoredComparisonDataError(
                f"stored comparison edge {_edge_description(identity)} has mixed change kinds"
            )
        if presence_count != 1 or row_count != 1:
            raise StoredComparisonDataError(
                f"stored comparison edge {_edge_description(identity)} must contain exactly one presence row"
            )
        if row["invalid_presence_payload_count"]:
            raise StoredComparisonDataError(
                f"stored comparison edge {_edge_description(identity)} has a non-NULL presence payload"
            )
        return
    if changed_count != row_count:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has invalid changed-row shape"
        )


def _validated_optional_completed_at(
    value: Any,
    *,
    identity: StoredComparisonIdentity,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has an invalid {field_name}"
        )
    try:
        local_date_for(value)
    except (TypeError, ValueError, OverflowError):
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has an invalid {field_name}"
        ) from None
    return value


def _local_date_for_edge(value: str, *, identity: StoredComparisonIdentity) -> date:
    try:
        return local_date_for(value)
    except (TypeError, ValueError, OverflowError):
        raise StoredComparisonDataError(
            f"stored comparison edge {_edge_description(identity)} has an invalid detected_at"
        ) from None


def _raw_edge_description(
    provider_id: Any,
    provider_model_id: Any,
    from_scrape_id: Any,
    to_scrape_id: Any,
) -> str:
    safe_provider = provider_id if isinstance(provider_id, str) and provider_id else "<invalid-provider-id>"
    safe_model = (
        provider_model_id
        if isinstance(provider_model_id, str) and provider_model_id
        else "<invalid-model-id>"
    )
    safe_from = (
        from_scrape_id
        if from_scrape_id is None
        or (isinstance(from_scrape_id, int) and not isinstance(from_scrape_id, bool) and from_scrape_id > 0)
        else "<invalid-from-scrape-id>"
    )
    safe_to = (
        to_scrape_id
        if isinstance(to_scrape_id, int)
        and not isinstance(to_scrape_id, bool)
        and to_scrape_id > 0
        else "<invalid-to-scrape-id>"
    )
    return f"({safe_provider}, {safe_model}, {safe_from}, {safe_to})"


def _edge_description(identity: StoredComparisonIdentity) -> str:
    return (
        f"({identity.provider_id}, {identity.provider_model_id}, "
        f"{identity.from_scrape_id}, {identity.to_scrape_id})"
    )


def recent_change_rows(
    connection: sqlite3.Connection,
    *,
    provider_id: str | None,
    since: date | None,
    until: date | None,
) -> tuple[dict[str, Any], ...]:
    query = """
        WITH latest AS (
            SELECT sm.provider_id, sm.provider_model_id, sm.display_name,
                   ROW_NUMBER() OVER (
                       PARTITION BY sm.provider_id, sm.provider_model_id
                       ORDER BY s.completed_at DESC, s.scrape_id DESC
                   ) AS rn
            FROM snapshot_models sm
            JOIN scrapes s ON s.scrape_id = sm.scrape_id
        )
        SELECT fc.change_id, fc.provider_id, fc.provider_model_id, fc.change_kind,
               fc.field_name, fc.old_value_json, fc.new_value_json, fc.detected_at,
               p.label AS provider_label, l.display_name
        FROM field_changes fc
        JOIN providers p ON p.provider_id = fc.provider_id
        LEFT JOIN latest l
               ON l.provider_id = fc.provider_id
              AND l.provider_model_id = fc.provider_model_id
              AND l.rn = 1
        WHERE fc.from_scrape_id IS NOT NULL
    """
    parameters: list[str] = []
    if provider_id is not None:
        query += " AND fc.provider_id = ?"
        parameters.append(provider_id)
    if since is not None:
        lower_bound = (datetime.combine(since, time.min) - timedelta(days=1)).isoformat()
        query += " AND fc.detected_at >= ?"
        parameters.append(lower_bound)
    if until is not None:
        upper_bound = (datetime.combine(until, time.max) + timedelta(days=1)).isoformat()
        query += " AND fc.detected_at <= ?"
        parameters.append(upper_bound)
    query += " ORDER BY fc.detected_at ASC, fc.provider_id, fc.provider_model_id, fc.change_id"

    rows = connection.execute(query, parameters).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        detected_at = row["detected_at"]
        detected_date = local_date_for(detected_at)
        if since is not None and detected_date < since:
            continue
        if until is not None and detected_date > until:
            continue

        results.append(
            {
                "change_id": int(row["change_id"]),
                "provider_id": row["provider_id"],
                "provider_label": row["provider_label"],
                "provider_model_id": row["provider_model_id"],
                "display_name": row["display_name"] or row["provider_model_id"],
                "change_kind": row["change_kind"],
                "field_name": row["field_name"],
                "old_value": load_json_value(row["old_value_json"]),
                "new_value": load_json_value(row["new_value_json"]),
                "detected_at": detected_at,
            }
        )
    return tuple(results)


def load_json_value(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


_load_json_value = load_json_value
