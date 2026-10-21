import gzip
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import perf_counter
import time as time_module
from typing import Any

import pytest

from model_sentinel.config import ProviderConfig
from model_sentinel.endpoints import (
    ENDPOINT_ERROR_MESSAGE_LIMIT,
    build_endpoint_capture,
    build_endpoint_error_summary,
    endpoint_state,
)
from model_sentinel.models import (
    EndpointFetchResult,
    EndpointMapping,
    EndpointPathResult,
    FieldChange,
    ModelDelta,
    NormalizedModel,
    canonical_json,
)
from model_sentinel import storage
from model_sentinel.storage import Store
from model_sentinel.time_utils import local_date_for
from model_sentinel.reporting import render_changes_report, render_history_report
from model_sentinel.provider_profiles import OPENROUTER_PROFILE


def _model(
    model_id: str,
    *,
    provider_id: str = "openrouter",
    provider_label: str = "OpenRouter",
    display_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> NormalizedModel:
    return NormalizedModel(
        provider_id=provider_id,
        provider_label=provider_label,
        provider_model_id=model_id,
        display_name=display_name or model_id.upper(),
        description=None,
        model_family=None,
        created_at_provider=None,
        context_window=None,
        max_output_tokens=None,
        input_price=None,
        output_price=None,
        cache_read_price=None,
        cache_write_price=None,
        reasoning_supported=None,
        tool_calling_supported=None,
        vision_supported=None,
        audio_supported=None,
        image_supported=None,
        structured_output_supported=None,
        deprecated=None,
        status=None,
        metadata_json=canonical_json(metadata if metadata is not None else {"id": model_id}),
    )


def _provider(provider_id: str, label: str) -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        label=label,
        kind="generic",
        base_url=f"https://{provider_id}.invalid",
        models_path="/models",
        credential_env_var=f"FAKE_{provider_id.upper()}_TOKEN",
        price_multiplier=1,
        price_divisor=1,
        enabled=True,
    )


def _legacy_recent_changes(
    store: Store,
    *,
    provider_id: str | None = None,
    since: date | None = None,
    until: date | None = None,
) -> tuple[dict[str, Any], ...]:
    with store._connect() as connection:
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
        results.append(
            {
                "provider_id": row["provider_id"],
                "provider_label": row["provider_label"],
                "provider_model_id": row["provider_model_id"],
                "display_name": display_name,
                "change_kind": row["change_kind"],
                "field_name": row["field_name"],
                "old_value": json.loads(row["old_value_json"]) if row["old_value_json"] is not None else None,
                "new_value": json.loads(row["new_value_json"]) if row["new_value_json"] is not None else None,
                "detected_at": detected_at,
            }
        )
    return tuple(results)


def _build_recent_changes_store(tmp_path: Path) -> tuple[Store, date]:
    store = Store(tmp_path / "recent-changes.db")
    store.initialize()
    providers = (_provider("openrouter", "OpenRouter"), _provider("fakecloud", "Fake Cloud"))
    store.upsert_provider_configs(providers, updated_at="2026-08-20T00:00:00+00:00")

    local_zone = datetime.now().astimezone().tzinfo
    assert local_zone is not None
    boundary_date = date(2026, 8, 20)
    before_midnight = datetime.combine(boundary_date - timedelta(days=1), time(23, 59), local_zone)
    after_midnight = datetime.combine(boundary_date, time(0, 1), local_zone)

    scrape_ids: dict[str, tuple[int, int]] = {}
    for provider in providers:
        first = store.create_scrape(
            provider_id=provider.provider_id,
            started_at=(before_midnight - timedelta(minutes=10)).isoformat(),
            completed_at=(before_midnight - timedelta(minutes=5)).isoformat(),
            status="success",
            baseline_mode="previous",
            baseline_scrape_id=None,
            saved_snapshot=True,
            model_count=2,
            error_message=None,
        )
        second = store.create_scrape(
            provider_id=provider.provider_id,
            started_at=(after_midnight + timedelta(minutes=5)).isoformat(),
            completed_at=(after_midnight + timedelta(minutes=10)).isoformat(),
            status="success",
            baseline_mode="previous",
            baseline_scrape_id=first,
            saved_snapshot=True,
            model_count=2,
            error_message=None,
        )
        store.save_snapshot_models(
            scrape_id=first,
            provider_id=provider.provider_id,
            models=[
                _model(
                    "alpha",
                    provider_id=provider.provider_id,
                    provider_label=provider.label,
                    display_name=f"{provider.label} Alpha Old",
                ),
                _model("beta", provider_id=provider.provider_id, provider_label=provider.label),
            ],
        )
        store.save_snapshot_models(
            scrape_id=second,
            provider_id=provider.provider_id,
            models=[
                _model(
                    "alpha",
                    provider_id=provider.provider_id,
                    provider_label=provider.label,
                    display_name=f"{provider.label} Alpha Latest",
                ),
                _model("beta", provider_id=provider.provider_id, provider_label=provider.label),
            ],
        )
        scrape_ids[provider.provider_id] = (first, second)

    changes = (
        ("openrouter", "alpha", before_midnight, "context_window", 128_000, 256_000),
        ("fakecloud", "alpha", after_midnight, "status", "preview", "stable"),
        ("openrouter", "ghost", after_midnight + timedelta(minutes=1), "status", None, "available"),
        (
            "openrouter",
            "beta",
            after_midnight + timedelta(minutes=5),
            "tie_openrouter_beta_first",
            1,
            2,
        ),
        (
            "openrouter",
            "alpha",
            after_midnight + timedelta(minutes=5),
            "tie_openrouter_alpha",
            1,
            2,
        ),
        (
            "fakecloud",
            "alpha",
            after_midnight + timedelta(minutes=5),
            "tie_fakecloud_alpha",
            1,
            2,
        ),
        (
            "openrouter",
            "beta",
            after_midnight + timedelta(minutes=5),
            "tie_openrouter_beta_second",
            2,
            3,
        ),
        ("openrouter", "beta", after_midnight + timedelta(days=1), "deprecated", False, True),
    )
    for provider_id, model_id, detected_at, field_name, old_value, new_value in changes:
        first, second = scrape_ids[provider_id]
        store.record_field_changes(
            provider_id=provider_id,
            from_scrape_id=first,
            to_scrape_id=second,
            deltas=(
                ModelDelta(
                    kind="changed",
                    provider_model_id=model_id,
                    display_name=model_id,
                    field_changes=(FieldChange(field_name, old_value, new_value),),
                ),
            ),
            detected_at=detected_at.isoformat(),
        )
    return store, boundary_date


def _build_large_recent_changes_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "large-recent-changes.db")
    store.initialize()
    store.upsert_provider_configs(
        (_provider("performance", "Performance Fixture"),),
        updated_at="2026-08-01T00:00:00+00:00",
    )
    with store._connect() as connection:
        scrape_rows = [
            (
                "performance",
                f"2026-08-{day:02d}T00:00:00+00:00",
                f"2026-08-{day:02d}T00:01:00+00:00",
                "success",
                "previous",
                None if day == 1 else day - 1,
                1,
                300,
            )
            for day in range(1, 21)
        ]
        connection.executemany(
            """
            INSERT INTO scrapes (
                provider_id, started_at, completed_at, status, baseline_mode,
                baseline_scrape_id, saved_snapshot, model_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            scrape_rows,
        )
        connection.executemany(
            """
            INSERT INTO snapshot_models (
                scrape_id, provider_id, provider_model_id, display_name, metadata_json
            )
            VALUES (?, 'performance', ?, ?, ?)
            """,
            (
                (scrape_id, f"model-{model_id:03d}", f"Model {model_id:03d}", "{}")
                for scrape_id in range(1, 21)
                for model_id in range(300)
            ),
        )
        connection.executemany(
            """
            INSERT INTO field_changes (
                provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                change_kind, field_name, old_value_json, new_value_json, detected_at
            )
            VALUES ('performance', 1, 20, ?, 'field_changed', 'status', ?, ?, ?)
            """,
            (
                (
                    f"model-{change_id % 300:03d}",
                    '"old"',
                    '"new"',
                    f"2026-08-{(change_id % 20) + 1:02d}T12:{change_id % 60:02d}:00+00:00",
                )
                for change_id in range(2_000)
            ),
        )
        connection.commit()
    return store


def test_store_saves_and_loads_baselines(tmp_path: Path) -> None:
    store = Store(tmp_path / "sentinel.db")
    store.initialize()
    store.create_scrape(
        provider_id="openrouter",
        started_at="2025-01-01T09:00:00-05:00",
        completed_at="2025-01-01T09:05:00-05:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=1,
        error_message=None,
    )
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2025-01-02T09:00:00-05:00",
        completed_at="2025-01-02T09:05:00-05:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=1,
        saved_snapshot=True,
        model_count=1,
        error_message=None,
    )
    store.save_snapshot_models(scrape_id=scrape_id, provider_id="openrouter", models=[_model("x")])
    latest = store.get_latest_saved_baseline("openrouter")
    assert latest is not None
    assert latest.scrape_id == 2
    prior_day = store.get_previous_day_baseline("openrouter", current_date=date(2025, 1, 3))
    assert prior_day is not None
    assert prior_day.scrape_id == 2
    loaded = store.load_saved_models(scrape_id)
    assert list(loaded) == ["x"]
    known_models = store.list_known_models(provider_id="openrouter", since=None, until=None)
    assert len(known_models) == 1
    assert known_models[0]["provider_model_id"] == "x"


def test_scrape_timestamps_are_normalized_to_utc(tmp_path: Path) -> None:
    store = Store(tmp_path / "sentinel.db")
    store.initialize()
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2025-01-01T09:00:00-05:00",
        completed_at="2025-01-01T09:05:00-05:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=0,
        error_message=None,
    )
    with store._connect() as connection:
        row = connection.execute(
            "SELECT started_at, completed_at FROM scrapes WHERE scrape_id = ?",
            (scrape_id,),
        ).fetchone()
    assert row["started_at"] == "2025-01-01T14:00:00+00:00"
    assert row["completed_at"] == "2025-01-01T14:05:00+00:00"


@pytest.mark.parametrize(
    ("provider_id", "since_offset", "until_offset"),
    (
        (None, None, None),
        ("openrouter", None, None),
        ("fakecloud", None, None),
        (None, 0, 0),
        ("openrouter", 0, 0),
        (None, 1, 1),
        (None, 0, None),
        ("openrouter", 0, None),
        (None, None, 0),
        ("fakecloud", None, 0),
    ),
)
def test_recent_changes_matches_legacy_results(
    tmp_path: Path,
    provider_id: str | None,
    since_offset: int | None,
    until_offset: int | None,
) -> None:
    store, boundary_date = _build_recent_changes_store(tmp_path)
    since = boundary_date + timedelta(days=since_offset) if since_offset is not None else None
    until = boundary_date + timedelta(days=until_offset) if until_offset is not None else None

    expected = _legacy_recent_changes(store, provider_id=provider_id, since=since, until=until)
    actual = store.recent_changes(provider_id=provider_id, since=since, until=until)

    assert actual == expected
    expected_keys = (
        "provider_id",
        "provider_label",
        "provider_model_id",
        "display_name",
        "change_kind",
        "field_name",
        "old_value",
        "new_value",
        "detected_at",
    )
    assert all(tuple(row) == expected_keys for row in actual)
    assert tuple(row["detected_at"] for row in actual) == tuple(
        sorted(row["detected_at"] for row in actual)
    )
    if provider_id == "openrouter" and since is None and until is None:
        ghost = next(row for row in actual if row["provider_model_id"] == "ghost")
        assert ghost["display_name"] == "ghost"


def test_recent_changes_matches_legacy_tie_break_order(tmp_path: Path) -> None:
    store, _ = _build_recent_changes_store(tmp_path)

    expected = _legacy_recent_changes(store)
    actual = store.recent_changes()
    tied_expected = tuple(row for row in expected if str(row["field_name"]).startswith("tie_"))
    tied_actual = tuple(row for row in actual if str(row["field_name"]).startswith("tie_"))

    assert tied_actual == tied_expected
    assert tuple(
        (row["provider_id"], row["provider_model_id"], row["field_name"]) for row in tied_actual
    ) == (
        ("fakecloud", "alpha", "tie_fakecloud_alpha"),
        ("openrouter", "alpha", "tie_openrouter_alpha"),
        ("openrouter", "beta", "tie_openrouter_beta_first"),
        ("openrouter", "beta", "tie_openrouter_beta_second"),
    )

    with store._connect() as connection:
        raw_tied = tuple(
            row
            for row in storage.recent_change_rows(connection, provider_id=None, since=None, until=None)
            if str(row["field_name"]).startswith("tie_")
        )
    beta_change_ids = tuple(
        row["change_id"]
        for row in raw_tied
        if row["provider_id"] == "openrouter" and row["provider_model_id"] == "beta"
    )
    assert beta_change_ids == tuple(sorted(beta_change_ids))


def test_recent_change_rows_exposes_change_id_without_changing_store_rows(tmp_path: Path) -> None:
    store, _ = _build_recent_changes_store(tmp_path)

    with store._connect() as connection:
        raw_rows = storage.recent_change_rows(connection, provider_id=None, since=None, until=None)
    store_rows = store.recent_changes()

    assert len(raw_rows) == len(store_rows)
    assert all(isinstance(row["change_id"], int) for row in raw_rows)
    assert set(store_rows[0]) == set(raw_rows[0]) - {"change_id"}
    assert tuple({key: value for key, value in row.items() if key != "change_id"} for row in raw_rows) == store_rows


def test_recent_change_rows_completes_large_query_under_two_seconds(tmp_path: Path) -> None:
    store = _build_large_recent_changes_store(tmp_path)

    with store._connect() as connection:
        started_at = perf_counter()
        rows = storage.recent_change_rows(connection, provider_id=None, since=None, until=None)
        elapsed = perf_counter() - started_at

    assert len(rows) == 2_000
    assert elapsed < 2.0


def test_load_json_value_is_public_with_private_compatibility_alias() -> None:
    assert storage.load_json_value('{"fake": [1, true]}') == {"fake": [1, True]}
    assert storage.load_json_value(None) is None
    assert storage._load_json_value is storage.load_json_value


def _build_legacy_metadata_fixture(tmp_path: Path) -> Store:
    """Build one valid synthetic edge whose snapshot metadata can be corrupted."""
    store = Store(tmp_path / "malformed-metadata.db")
    store.initialize()
    provider = _provider("synthetic", "Synthetic Provider")
    store.upsert_provider_configs((provider,), updated_at="2026-08-01T00:00:00+00:00")

    first = store.create_scrape(
        provider_id="synthetic",
        started_at="2026-08-01T00:00:00+00:00",
        completed_at="2026-08-01T00:01:00+00:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=1,
        error_message=None,
    )
    second = store.create_scrape(
        provider_id="synthetic",
        started_at="2026-08-02T00:00:00+00:00",
        completed_at="2026-08-02T00:01:00+00:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=first,
        saved_snapshot=True,
        model_count=1,
        error_message=None,
    )
    store.save_snapshot_models(
        scrape_id=first,
        provider_id="synthetic",
        models=[_model("synthetic/model", provider_id="synthetic", provider_label=provider.label, display_name="Old Name")],
    )
    store.save_snapshot_models(
        scrape_id=second,
        provider_id="synthetic",
        models=[_model("synthetic/model", provider_id="synthetic", provider_label=provider.label, display_name="New Name")],
    )
    store.record_field_changes(
        provider_id="synthetic",
        from_scrape_id=first,
        to_scrape_id=second,
        deltas=(
            ModelDelta(
                "changed",
                "synthetic/model",
                "New Name",
                (FieldChange("status", "old", "new"),),
            ),
        ),
        detected_at="2026-08-02T00:01:00+00:00",
    )
    return store


def _legacy_storage_projection(store: Store):
    """Read every legacy storage value used by history and changes reports."""
    first_seen, last_seen, history_events = store.history_events(
        provider_id="synthetic",
        model_id="synthetic/model",
        since=None,
        until=None,
    )
    changes = store.recent_changes(provider_id="synthetic")
    return first_seen, last_seen, history_events, changes


def _legacy_json_projection(store: Store, projection) -> tuple[str, str]:
    first_seen, last_seen, history_events, changes = projection
    history_json = render_history_report(
        provider_id="synthetic",
        model_id="synthetic/model",
        format_name="json",
        first_seen=first_seen,
        last_seen=last_seen,
        events=history_events,
        profile=OPENROUTER_PROFILE,
        latest_model=store.get_latest_model_snapshot(
            provider_id="synthetic", model_id="synthetic/model"
        ),
    )
    changes_json = render_changes_report(
        format_name="json",
        provider_id="synthetic",
        since=None,
        until=None,
        changes=changes,
    )
    return history_json, changes_json


def _corrupt_snapshot_metadata(store: Store) -> None:
    """Perform the real SQLite corruption used by both isolation assertions."""
    with store._connect() as connection:
        connection.execute(
            "UPDATE snapshot_models SET metadata_json = ?",
            ("{malformed synthetic metadata",),
        )
        connection.commit()


def test_legacy_storage_projections_ignore_malformed_snapshot_metadata(tmp_path: Path) -> None:
    store = _build_legacy_metadata_fixture(tmp_path)
    before = _legacy_storage_projection(store)
    _corrupt_snapshot_metadata(store)
    after = _legacy_storage_projection(store)

    # Every legacy storage value is independent of snapshot metadata.
    assert after == before
    first_seen, last_seen, history_events, changes = after
    assert (first_seen, last_seen) == (
        "2026-08-01T00:01:00+00:00",
        "2026-08-02T00:01:00+00:00",
    )
    assert history_events == (
        storage.HistoryEvent("2026-08-02T00:01:00+00:00", "field_changed", "status", "old", "new"),
    )
    assert changes == (
        {
            "provider_id": "synthetic",
            "provider_label": "Synthetic Provider",
            "provider_model_id": "synthetic/model",
            "display_name": "New Name",
            "change_kind": "field_changed",
            "field_name": "status",
            "old_value": "old",
            "new_value": "new",
            "detected_at": "2026-08-02T00:01:00+00:00",
        },
    )


def test_legacy_json_renderers_are_byte_identical_with_malformed_metadata(tmp_path: Path) -> None:
    store = _build_legacy_metadata_fixture(tmp_path)
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time_module.tzset()
    try:
        before_storage = _legacy_storage_projection(store)
        before_history_json, before_changes_json = _legacy_json_projection(
            store, before_storage
        )
        _corrupt_snapshot_metadata(store)
        after_storage = _legacy_storage_projection(store)
        after_history_json, after_changes_json = _legacy_json_projection(
            store, after_storage
        )
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time_module.tzset()

    assert after_storage == before_storage
    assert after_history_json == before_history_json
    assert after_changes_json == before_changes_json

    _, _, _, changes = after_storage
    history_json = json.loads(after_history_json)
    changes_json = json.loads(after_changes_json)
    assert history_json == {
        "events": [
            {
                "change_kind": "field_changed",
                "detected_at": "2026-08-02T00:01:00+00:00",
                "field_name": "status",
                "new_value": "new",
                "old_value": "old",
            }
        ],
        "first_seen": "2026-08-01T00:01:00+00:00",
        "last_seen": "2026-08-02T00:01:00+00:00",
        "latest_model": {
            "cache_read_price": None,
            "cache_write_price": None,
            "completed_at": "2026-08-02T00:01:00+00:00",
            "display_name": "New Name",
            "input_price": None,
            "output_price": None,
            "provider_id": "synthetic",
        },
        "model_id": "synthetic/model",
        "provider_id": "synthetic",
    }
    assert changes_json == {
        "changes": [changes[0]],
        "provider_id": "synthetic",
        "since": None,
        "until": None,
    }


def _insert_synthetic_change_row(
    store: Store,
    *,
    provider_id: str,
    model_id: str,
    from_scrape_id: int | None,
    to_scrape_id: int,
    detected_at: str,
    field_name: str | None,
    old_value: Any,
    new_value: Any,
    change_kind: str = "field_changed",
) -> None:
    with store._connect() as connection:
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
                model_id,
                change_kind,
                field_name,
                None if field_name is None else canonical_json(old_value),
                None if field_name is None else canonical_json(new_value),
                detected_at,
            ),
        )
        connection.commit()


def _build_comparison_event_store(tmp_path: Path) -> tuple[Store, dict[str, Any]]:
    """Build conspicuously synthetic exact edges, including a non-adjacent baseline."""
    store = Store(tmp_path / "comparison-events.db")
    store.initialize()
    provider = _provider("synthetic", "Synthetic Provider")
    store.upsert_provider_configs((provider,), updated_at="2026-08-20T00:00:00+00:00")

    local_zone = datetime.now().astimezone().tzinfo
    assert local_zone is not None
    selected_date = date(2026, 8, 20)
    scrape_ids: list[int] = []
    for hour, baseline_id in ((9, None), (11, 1), (15, 2), (17, 3)):
        completed = datetime.combine(selected_date, time(hour, 0), local_zone)
        scrape_ids.append(
            store.create_scrape(
                provider_id="synthetic",
                started_at=(completed - timedelta(minutes=1)).isoformat(),
                completed_at=completed.isoformat(),
                status="success",
                baseline_mode="previous",
                baseline_scrape_id=baseline_id,
                saved_snapshot=True,
                model_count=2,
                error_message=None,
            )
        )
    first, second, third, fourth = scrape_ids
    snapshots = (
        (first, "Source Exact", "source-exact"),
        (second, "Intermediate Name", "intermediate"),
        (third, "Target Exact", "target-exact"),
        (fourth, "Later Renamed Name", "later-rename"),
    )
    for scrape_id, display_name, marker in snapshots:
        models = [
            _model(
                "synthetic/model",
                provider_id="synthetic",
                provider_label=provider.label,
                display_name=display_name,
                metadata={"id": "synthetic/model", "marker": marker},
            )
        ]
        if scrape_id in {first, third, fourth}:
            models.append(
                _model(
                    "synthetic/missing-source",
                    provider_id="synthetic",
                    provider_label=provider.label,
                    display_name=f"Missing Source {marker}",
                    metadata={"id": "synthetic/missing-source", "marker": marker},
                )
            )
        store.save_snapshot_models(
            scrape_id=scrape_id,
            provider_id="synthetic",
            models=models,
        )

    timestamps = {
        "initial": datetime.combine(selected_date - timedelta(days=1), time(23, 59), local_zone).isoformat(),
        "edge_one": datetime.combine(selected_date, time(11, 30), local_zone).isoformat(),
        "edge_two": datetime.combine(selected_date, time(15, 30), local_zone).isoformat(),
        "missing": datetime.combine(selected_date, time(16, 0), local_zone).isoformat(),
    }
    _insert_synthetic_change_row(
        store,
        provider_id="synthetic",
        model_id="synthetic/model",
        from_scrape_id=None,
        to_scrape_id=first,
        detected_at=timestamps["initial"],
        field_name=None,
        old_value=None,
        new_value=None,
        change_kind="added",
    )
    for field_name, old_value, new_value in (
        ("pricing.prompt", "0.000001", "0.000002"),
        ("pricing.prompt", "0.000001", "0.000002"),
    ):
        _insert_synthetic_change_row(
            store,
            provider_id="synthetic",
            model_id="synthetic/model",
            from_scrape_id=first,
            to_scrape_id=second,
            detected_at=timestamps["edge_one"],
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
        )
    for field_name, old_value, new_value in (
        ("status", None, "available"),
        ("pricing.overrides", [], [{"utc_start": 900}]),
    ):
        _insert_synthetic_change_row(
            store,
            provider_id="synthetic",
            model_id="synthetic/model",
            from_scrape_id=first,
            to_scrape_id=third,
            detected_at=timestamps["edge_two"],
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
        )
    _insert_synthetic_change_row(
        store,
        provider_id="synthetic",
        model_id="synthetic/missing-source",
        from_scrape_id=second,
        to_scrape_id=third,
        detected_at=timestamps["missing"],
        field_name="status",
        old_value="hidden",
        new_value="available",
    )
    return store, {
        "date": selected_date,
        "scrapes": (first, second, third, fourth),
        "timestamps": timestamps,
    }


def test_history_comparison_events_load_exact_whole_edges(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, third, _ = fixture["scrapes"]

    events = store.history_comparison_events(
        provider_id="synthetic",
        model_id="synthetic/model",
        since=fixture["date"],
        until=fixture["date"],
    )

    assert tuple(event.identity for event in events) == (
        storage.StoredComparisonIdentity("synthetic", "synthetic/model", first, second),
        storage.StoredComparisonIdentity("synthetic", "synthetic/model", first, third),
    )
    assert tuple(len(event.source_rows) for event in events) == (2, 2)
    assert all(
        tuple(row.change_id for row in event.source_rows)
        == tuple(sorted(row.change_id for row in event.source_rows))
        for event in events
    )
    assert events[0].field_changes == (
        FieldChange("pricing.prompt", "0.000001", "0.000002"),
        FieldChange("pricing.prompt", "0.000001", "0.000002"),
    )
    # The second edge deliberately compares the first scrape to the third, not
    # the adjacent second scrape.
    assert events[1].old_model_metadata == {
        "id": "synthetic/model",
        "marker": "source-exact",
    }
    assert events[1].new_model_metadata == {
        "id": "synthetic/model",
        "marker": "target-exact",
    }
    assert events[1].display_name == "Target Exact"
    assert events[1].provider_label == "Synthetic Provider"
    assert events[1].field_changes[0] == FieldChange("status", None, "available")
    assert events[0].from_completed_at is not None
    assert events[0].to_completed_at is not None


def test_history_comparison_events_include_initial_edge_but_recent_excludes_it(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, _, _, _ = fixture["scrapes"]
    initial_date = fixture["date"] - timedelta(days=1)

    history = store.history_comparison_events(
        provider_id="synthetic",
        model_id="synthetic/model",
        since=initial_date,
        until=initial_date,
    )
    recent = store.recent_comparison_events(
        provider_id="synthetic",
        since=initial_date,
        until=fixture["date"],
    )

    assert len(history) == 1
    assert history[0].identity == storage.StoredComparisonIdentity(
        "synthetic", "synthetic/model", None, first
    )
    assert history[0].old_model_metadata is None
    assert all(event.identity.from_scrape_id is not None for event in recent)


def test_recent_comparison_events_keep_edges_separate_and_use_exact_names(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, third, _ = fixture["scrapes"]

    events = store.recent_comparison_events(
        provider_id="synthetic",
        since=fixture["date"],
        until=fixture["date"],
    )

    identities = tuple(event.identity for event in events)
    assert storage.StoredComparisonIdentity("synthetic", "synthetic/model", first, second) in identities
    assert storage.StoredComparisonIdentity("synthetic", "synthetic/model", first, third) in identities
    assert len([event for event in events if event.provider_model_id == "synthetic/model"]) == 2
    first_edge = next(event for event in events if event.identity.to_scrape_id == second)
    second_edge = next(
        event
        for event in events
        if event.provider_model_id == "synthetic/model" and event.identity.to_scrape_id == third
    )
    assert first_edge.display_name == "Intermediate Name"
    assert second_edge.display_name == "Target Exact"
    # Legacy changes intentionally retain their latest-snapshot name.
    assert {
        row["display_name"]
        for row in store.recent_changes(provider_id="synthetic")
        if row["provider_model_id"] == "synthetic/model"
    } == {"Later Renamed Name"}


def test_comparison_events_never_substitute_an_adjacent_snapshot(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    event = next(
        event
        for event in store.recent_comparison_events(
            provider_id="synthetic",
            since=fixture["date"],
            until=fixture["date"],
        )
        if event.provider_model_id == "synthetic/missing-source"
    )

    assert event.old_model_metadata is None
    assert event.new_model_metadata == {
        "id": "synthetic/missing-source",
        "marker": "target-exact",
    }
    assert event.display_name == "Missing Source target-exact"


def test_comparison_event_display_name_falls_back_from_target_to_source_to_id(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, _, _ = fixture["scrapes"]
    store.save_snapshot_models(
        scrape_id=first,
        provider_id="synthetic",
        models=[
            _model(
                "synthetic/source-only",
                provider_id="synthetic",
                provider_label="Synthetic Provider",
                display_name="Exact Source Name",
                metadata={"marker": "source-only"},
            )
        ],
    )
    for model_id in ("synthetic/source-only", "synthetic/no-sides"):
        _insert_synthetic_change_row(
            store,
            provider_id="synthetic",
            model_id=model_id,
            from_scrape_id=first,
            to_scrape_id=second,
            detected_at=fixture["timestamps"]["edge_one"],
            field_name="status",
            old_value="listed",
            new_value="removed",
        )

    events = {
        event.provider_model_id: event
        for event in store.recent_comparison_events(provider_id="synthetic")
    }

    assert events["synthetic/source-only"].display_name == "Exact Source Name"
    assert events["synthetic/source-only"].old_model_metadata == {"marker": "source-only"}
    assert events["synthetic/source-only"].new_model_metadata is None
    assert events["synthetic/no-sides"].display_name == "synthetic/no-sides"
    assert events["synthetic/no-sides"].old_model_metadata is None
    assert events["synthetic/no-sides"].new_model_metadata is None


def test_comparison_event_records_are_frozen_and_history_contract_stays_five_fields(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    event = store.recent_comparison_events(provider_id="synthetic")[0]

    with pytest.raises(FrozenInstanceError):
        event.display_name = "Mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        event.source_rows[0].field_name = "mutated"  # type: ignore[misc]
    assert tuple(storage.HistoryEvent.__dataclass_fields__) == (
        "detected_at",
        "change_kind",
        "field_name",
        "old_value",
        "new_value",
    )


def test_rich_metadata_corruption_is_selected_edge_scoped_and_safe(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, _, _, _ = fixture["scrapes"]
    secret_like_payload = "{synthetic-sensitive-marker-never-echo"
    with store._connect() as connection:
        connection.execute(
            "UPDATE snapshot_models SET metadata_json = ? WHERE scrape_id = ? AND provider_model_id = ?",
            (secret_like_payload, first, "synthetic/model"),
        )
        connection.commit()

    # The later missing-source edge does not decode the corrupted, unselected row.
    assert store.history_comparison_events(
        provider_id="synthetic",
        model_id="synthetic/missing-source",
        since=fixture["date"],
        until=fixture["date"],
    )
    with pytest.raises(storage.StoredComparisonDataError) as exc_info:
        store.history_comparison_events(
            provider_id="synthetic",
            model_id="synthetic/model",
            since=fixture["date"],
            until=fixture["date"],
        )
    message = str(exc_info.value)
    assert "synthetic/model" in message
    assert str(first) in message
    assert "metadata" in message
    assert secret_like_payload not in message
    # Independent legacy projections never decode exact-side metadata.
    assert store.history_events(
        provider_id="synthetic", model_id="synthetic/model", since=None, until=None
    )[2]
    assert store.recent_changes(provider_id="synthetic")


def test_comparison_event_rejects_inconsistent_edge_timestamps(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, _, _ = fixture["scrapes"]
    _insert_synthetic_change_row(
        store,
        provider_id="synthetic",
        model_id="synthetic/model",
        from_scrape_id=first,
        to_scrape_id=second,
        detected_at=datetime.combine(
            fixture["date"], time(12, 0), datetime.now().astimezone().tzinfo
        ).isoformat(),
        field_name="status",
        old_value="one",
        new_value="two",
    )

    with pytest.raises(storage.StoredComparisonDataError) as exc_info:
        store.recent_comparison_events(provider_id="synthetic")
    assert "detected_at" in str(exc_info.value)
    assert f"{first}" in str(exc_info.value)
    assert f"{second}" in str(exc_info.value)


def test_comparison_event_rejects_malformed_change_json_without_echoing_it(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, _, _ = fixture["scrapes"]
    malformed_value = "{synthetic-private-marker-never-echo"
    with store._connect() as connection:
        connection.execute(
            """
            UPDATE field_changes
            SET old_value_json = ?
            WHERE provider_id = 'synthetic'
              AND provider_model_id = 'synthetic/model'
              AND from_scrape_id = ?
              AND to_scrape_id = ?
            """,
            (malformed_value, first, second),
        )
        connection.commit()

    with pytest.raises(storage.StoredComparisonDataError) as exc_info:
        store.recent_comparison_events(provider_id="synthetic")
    message = str(exc_info.value)
    assert "change JSON" in message
    assert str(first) in message
    assert str(second) in message
    assert malformed_value not in message


def _build_bounded_comparison_store(tmp_path: Path, row_count: int) -> Store:
    store = Store(tmp_path / f"bounded-{row_count}.db")
    store.initialize()
    provider = _provider("bounded", "Bounded Synthetic")
    store.upsert_provider_configs((provider,), updated_at="2026-08-20T00:00:00+00:00")
    scrape_ids = []
    for hour in (1, 2):
        scrape_ids.append(
            store.create_scrape(
                provider_id="bounded",
                started_at=f"2026-08-20T0{hour}:00:00+00:00",
                completed_at=f"2026-08-20T0{hour}:01:00+00:00",
                status="success",
                baseline_mode="previous",
                baseline_scrape_id=None,
                saved_snapshot=True,
                model_count=1,
                error_message=None,
            )
        )
    for scrape_id, marker in zip(scrape_ids, ("old", "new"), strict=True):
        store.save_snapshot_models(
            scrape_id=scrape_id,
            provider_id="bounded",
            models=[
                _model(
                    "bounded/model",
                    provider_id="bounded",
                    provider_label=provider.label,
                    metadata={"marker": marker, "large": "x" * 10_000},
                )
            ],
        )
    with store._connect() as connection:
        connection.executemany(
            """
            INSERT INTO field_changes (
                provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                change_kind, field_name, old_value_json, new_value_json, detected_at
            ) VALUES ('bounded', ?, ?, 'bounded/model', 'field_changed', 'status', 'null', 'null',
                      '2026-08-20T02:01:00+00:00')
            """,
            ((scrape_ids[0], scrape_ids[1]) for _ in range(row_count)),
        )
        connection.commit()
    return store


@pytest.mark.parametrize("row_count", (100, 1_000))
def test_comparison_events_use_constant_queries_and_decode_each_side_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row_count: int
) -> None:
    store = _build_bounded_comparison_store(tmp_path, row_count)
    statements: list[str] = []
    original_connect = store._connect

    def traced_connect():
        connection = original_connect()
        connection.set_trace_callback(statements.append)
        return connection

    decode_calls: list[tuple[str, int | None]] = []
    original_decode = storage.load_model_metadata

    def counted_decode(value, *, identity, side):
        decode_calls.append((side, identity.from_scrape_id if side == "source" else identity.to_scrape_id))
        return original_decode(value, identity=identity, side=side)

    monkeypatch.setattr(store, "_connect", traced_connect)
    monkeypatch.setattr(storage, "load_model_metadata", counted_decode)

    events = store.recent_comparison_events(provider_id="bounded")

    assert len(events) == 1
    assert len(events[0].source_rows) == row_count
    read_statements = [statement for statement in statements if statement.lstrip().upper().startswith(("SELECT", "WITH"))]
    assert len(read_statements) == 2
    assert "metadata_json" in read_statements[0]
    assert "metadata_json" not in read_statements[1]
    assert decode_calls == [("source", events[0].identity.from_scrape_id), ("target", events[0].identity.to_scrape_id)]


def test_date_bounded_envelopes_do_not_fetch_out_of_range_field_rows(tmp_path: Path) -> None:
    store = _build_bounded_comparison_store(tmp_path, 10)
    third = store.create_scrape(
        provider_id="bounded",
        started_at="2026-07-01T03:00:00+00:00",
        completed_at="2026-07-01T03:01:00+00:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=2,
        saved_snapshot=True,
        model_count=1,
        error_message=None,
    )
    store.save_snapshot_models(
        scrape_id=third,
        provider_id="bounded",
        models=[
            _model(
                "bounded/model",
                provider_id="bounded",
                provider_label="Bounded Synthetic",
                metadata={"marker": "far-out-of-range", "large": "z" * 10_000},
            )
        ],
    )
    with store._connect() as connection:
        connection.executemany(
            """
            INSERT INTO field_changes (
                provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                change_kind, field_name, old_value_json, new_value_json, detected_at
            ) VALUES ('bounded', 2, ?, 'bounded/model', 'field_changed', 'status',
                      'null', 'null', '2026-07-01T03:01:00+00:00')
            """,
            ((third,) for _ in range(1_000)),
        )
        connection.commit()

    with store._connect() as connection:
        selected_date = local_date_for("2026-08-20T02:01:00+00:00")
        envelopes = storage._comparison_event_envelopes(
            connection,
            provider_id="bounded",
            model_id=None,
            since=selected_date,
            until=selected_date,
            exclude_initial=True,
        )
        selected_rows = storage._selected_comparison_change_rows(
            connection,
            tuple(envelope.identity for envelope in envelopes),
            provider_id="bounded",
            model_id=None,
            since=selected_date,
            until=selected_date,
            exclude_initial=True,
        )

    assert len(envelopes) == 1
    assert len(selected_rows) == 10
    assert envelopes[0].old_model_metadata["marker"] == "old"
    assert envelopes[0].new_model_metadata["marker"] == "new"


def _build_many_distinct_edge_store(tmp_path: Path, edge_count: int) -> Store:
    store = Store(tmp_path / f"distinct-edges-{edge_count}.db")
    store.initialize()
    provider = _provider("edge-scale", "Edge Scale Synthetic")
    store.upsert_provider_configs((provider,), updated_at="2026-08-20T00:00:00+00:00")
    scrape_ids = []
    for hour in (1, 2):
        scrape_ids.append(
            store.create_scrape(
                provider_id="edge-scale",
                started_at=f"2026-08-20T0{hour}:00:00+00:00",
                completed_at=f"2026-08-20T0{hour}:01:00+00:00",
                status="success",
                baseline_mode="previous",
                baseline_scrape_id=scrape_ids[-1] if scrape_ids else None,
                saved_snapshot=True,
                model_count=edge_count,
                error_message=None,
            )
        )
    for scrape_id, marker in zip(scrape_ids, ("source", "target"), strict=True):
        store.save_snapshot_models(
            scrape_id=scrape_id,
            provider_id="edge-scale",
            models=[
                _model(
                    f"edge-scale/model-{index:04d}",
                    provider_id="edge-scale",
                    provider_label=provider.label,
                    metadata={"marker": marker, "index": index},
                )
                for index in range(edge_count)
            ],
        )
    with store._connect() as connection:
        connection.executemany(
            """
            INSERT INTO field_changes (
                provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                change_kind, field_name, old_value_json, new_value_json, detected_at
            ) VALUES ('edge-scale', ?, ?, ?, 'field_changed', 'status',
                      '"old"', '"new"', '2026-08-20T12:00:00.123456+00:00')
            """,
            (
                (scrape_ids[0], scrape_ids[1], f"edge-scale/model-{index:04d}")
                for index in range(edge_count)
            ),
        )
        connection.commit()
    return store


@pytest.mark.parametrize("edge_count", (500, 1_000, 2_000))
def test_selected_edge_fetch_is_portable_and_linear_in_possible_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    edge_count: int,
) -> None:
    store = _build_many_distinct_edge_store(tmp_path, edge_count)
    statements: list[str] = []
    selection_calls = 0
    original_connect = store._connect
    original_order = storage._selected_identity_order

    def traced_connect():
        connection = original_connect()
        connection.set_trace_callback(statements.append)
        return connection

    def counted_order(row, selected_orders):
        nonlocal selection_calls
        selection_calls += 1
        return original_order(row, selected_orders)

    monkeypatch.setattr(store, "_connect", traced_connect)
    monkeypatch.setattr(storage, "_selected_identity_order", counted_order)

    events = store.recent_comparison_events(
        provider_id="edge-scale",
        since=date(2026, 8, 20),
        until=date(2026, 8, 20),
    )

    assert len(events) == edge_count
    assert selection_calls == edge_count
    read_statements = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    assert len(read_statements) == 2
    assert all("json_each" not in statement.lower() for statement in read_statements)
    assert all("json_tree" not in statement.lower() for statement in read_statements)
    assert "metadata_json" not in read_statements[1]
    with original_connect() as connection:
        query_plan = connection.execute(
            "EXPLAIN QUERY PLAN " + read_statements[1]
        ).fetchall()
    assert all("VIRTUAL TABLE" not in str(row).upper() for row in query_plan)


def _make_snapshot_metadata_nullable(store: Store) -> None:
    """Emulate a corrupted/legacy SQLite file that lacks the current NOT NULL guard."""
    with store._connect() as connection:
        connection.execute("CREATE TABLE snapshot_models_corrupt AS SELECT * FROM snapshot_models")
        connection.execute("DROP TABLE snapshot_models")
        connection.execute("ALTER TABLE snapshot_models_corrupt RENAME TO snapshot_models")
        connection.commit()


@pytest.mark.parametrize(("side", "scrape_index"), (("source", 0), ("target", 1)))
def test_present_snapshot_with_null_metadata_is_corruption_not_missing_side(
    tmp_path: Path, side: str, scrape_index: int
) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, _, _ = fixture["scrapes"]
    _make_snapshot_metadata_nullable(store)
    with store._connect() as connection:
        connection.execute(
            """
            UPDATE snapshot_models
            SET metadata_json = NULL
            WHERE scrape_id = ? AND provider_model_id = 'synthetic/model'
            """,
            ((first, second)[scrape_index],),
        )
        connection.commit()

    with pytest.raises(storage.StoredComparisonDataError) as exc_info:
        store.recent_comparison_events(
            provider_id="synthetic",
            since=fixture["date"],
            until=fixture["date"],
        )
    message = str(exc_info.value)
    assert side in message
    assert "NULL metadata" in message
    assert "synthetic/model" in message
    assert store.recent_changes(provider_id="synthetic")


@pytest.mark.parametrize(("column", "scrape_index"), (("from_completed_at", 0), ("to_completed_at", 1)))
def test_invalid_exact_side_scrape_timestamp_raises_safe_typed_error(
    tmp_path: Path, column: str, scrape_index: int
) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, _, _ = fixture["scrapes"]
    corrupt_timestamp = "synthetic-corrupt-completed-at-never-echo"
    with store._connect() as connection:
        connection.execute(
            "UPDATE scrapes SET completed_at = ? WHERE scrape_id = ?",
            (corrupt_timestamp, (first, second)[scrape_index]),
        )
        connection.commit()

    with pytest.raises(storage.StoredComparisonDataError) as exc_info:
        store.recent_comparison_events(
            provider_id="synthetic",
            since=fixture["date"],
            until=fixture["date"],
        )
    message = str(exc_info.value)
    assert column in message
    assert corrupt_timestamp not in message


def test_changed_edge_rejects_mixed_change_kinds(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, _, _ = fixture["scrapes"]
    with store._connect() as connection:
        connection.execute(
            """
            UPDATE field_changes
            SET change_kind = 'added', field_name = NULL,
                old_value_json = NULL, new_value_json = NULL
            WHERE change_id = (
                SELECT MIN(change_id) FROM field_changes
                WHERE provider_id = 'synthetic'
                  AND provider_model_id = 'synthetic/model'
                  AND from_scrape_id = ? AND to_scrape_id = ?
            )
            """,
            (first, second),
        )
        connection.commit()

    with pytest.raises(storage.StoredComparisonDataError) as exc_info:
        store.recent_comparison_events(provider_id="synthetic")
    assert "mixed change kinds" in str(exc_info.value)


def test_presence_edge_rejects_duplicate_rows(tmp_path: Path) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, _, _ = fixture["scrapes"]
    for _ in range(2):
        _insert_synthetic_change_row(
            store,
            provider_id="synthetic",
            model_id="synthetic/duplicate-presence",
            from_scrape_id=first,
            to_scrape_id=second,
            detected_at=fixture["timestamps"]["edge_one"],
            field_name=None,
            old_value=None,
            new_value=None,
            change_kind="removed",
        )

    with pytest.raises(storage.StoredComparisonDataError) as exc_info:
        store.recent_comparison_events(provider_id="synthetic")
    assert "presence row" in str(exc_info.value)


@pytest.mark.parametrize("payload_column", ("field_name", "old_value_json", "new_value_json"))
def test_presence_edge_rejects_non_null_payload_columns(
    tmp_path: Path, payload_column: str
) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, _, _, _ = fixture["scrapes"]
    corrupt_payload = "synthetic-presence-payload-never-echo"
    with store._connect() as connection:
        connection.execute(
            f"""
            UPDATE field_changes
            SET {payload_column} = ?
            WHERE provider_id = 'synthetic'
              AND provider_model_id = 'synthetic/model'
              AND from_scrape_id IS NULL
              AND to_scrape_id = ?
            """,
            (corrupt_payload, first),
        )
        connection.commit()

    with pytest.raises(storage.StoredComparisonDataError) as exc_info:
        store.history_comparison_events(
            provider_id="synthetic",
            model_id="synthetic/model",
            since=fixture["date"] - timedelta(days=1),
            until=fixture["date"] - timedelta(days=1),
        )
    message = str(exc_info.value)
    assert "presence payload" in message
    assert corrupt_payload not in message


@pytest.mark.parametrize(
    ("column", "corrupt_value", "invariant"),
    (
        ("to_scrape_id", "not-a-scrape-id", "identity"),
        ("detected_at", "not-a-timestamp", "detected_at"),
        ("change_kind", "", "change_kind"),
        ("field_name", None, "field_name"),
        ("field_name", "", "field_name"),
    ),
)
def test_malformed_comparison_row_shape_raises_safe_typed_error(
    tmp_path: Path,
    column: str,
    corrupt_value: Any,
    invariant: str,
) -> None:
    store, fixture = _build_comparison_event_store(tmp_path)
    first, second, _, _ = fixture["scrapes"]
    with store._connect() as connection:
        connection.execute(
            f"""
            UPDATE field_changes
            SET {column} = ?
            WHERE change_id = (
                SELECT MIN(change_id)
                FROM field_changes
                WHERE provider_id = 'synthetic'
                  AND provider_model_id = 'synthetic/model'
                  AND from_scrape_id = ?
                  AND to_scrape_id = ?
            )
            """,
            (corrupt_value, first, second),
        )
        connection.commit()

    with pytest.raises(storage.StoredComparisonDataError) as exc_info:
        store.recent_comparison_events(provider_id="synthetic")
    message = str(exc_info.value)
    assert invariant in message
    assert "not-a-scrape-id" not in message
    assert "not-a-timestamp" not in message


def test_comparison_events_preserve_subsecond_chronology(tmp_path: Path) -> None:
    store = Store(tmp_path / "subsecond-comparison-events.db")
    store.initialize()
    provider = _provider("subsecond", "Subsecond Synthetic")
    store.upsert_provider_configs((provider,), updated_at="2026-08-20T00:00:00+00:00")
    scrape_ids = []
    for minute in (1, 2, 3):
        scrape_id = store.create_scrape(
            provider_id="subsecond",
            started_at=f"2026-08-20T00:0{minute}:00+00:00",
            completed_at=f"2026-08-20T00:0{minute}:30+00:00",
            status="success",
            baseline_mode="previous",
            baseline_scrape_id=scrape_ids[-1] if scrape_ids else None,
            saved_snapshot=True,
            model_count=1,
            error_message=None,
        )
        scrape_ids.append(scrape_id)
        store.save_snapshot_models(
            scrape_id=scrape_id,
            provider_id="subsecond",
            models=[
                _model(
                    "subsecond/model",
                    provider_id="subsecond",
                    provider_label=provider.label,
                    metadata={"scrape": minute},
                )
            ],
        )

    # Insert the later edge first so a truncated timestamp sort would be wrong.
    for from_id, to_id, detected_at in (
        (scrape_ids[1], scrape_ids[2], "2026-08-20T12:00:00.900000+00:00"),
        (scrape_ids[0], scrape_ids[1], "2026-08-20T12:00:00.100000+00:00"),
    ):
        _insert_synthetic_change_row(
            store,
            provider_id="subsecond",
            model_id="subsecond/model",
            from_scrape_id=from_id,
            to_scrape_id=to_id,
            detected_at=detected_at,
            field_name="status",
            old_value="old",
            new_value="new",
        )

    events = store.recent_comparison_events(provider_id="subsecond")

    assert tuple(event.detected_at for event in events) == (
        "2026-08-20T12:00:00.100000+00:00",
        "2026-08-20T12:00:00.900000+00:00",
    )


# ---------------------------------------------------------------------------
# Endpoint capture storage and comparison. Every fixture is invented: the
# provider, model IDs, hosts and prices are synthetic.
# ---------------------------------------------------------------------------

# Literal `SCHEMA` from the migration-fixture revision
# d40cf3c063a2f7e13448eae412f0753371f6a68e (model_sentinel/model_sentinel/storage.py),
# extracted with `git show`. It is embedded, not imported, so the test does not
# depend on the implementation under test.
LEGACY_SCHEMA = (
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

_ENDPOINT_TABLES = (
    "endpoint_captures",
    "endpoint_lists",
    "endpoint_capture_models",
    "endpoint_states",
    "endpoint_observations",
    "endpoint_changes",
    "endpoint_comparison_gaps",
    "endpoint_capture_archives",
)
_FAKE_PROVIDER = "fake-router"
_OTHER_PROVIDER = "fake-router-two"


def _endpoint_path(slug: str) -> str:
    return f"/api/v1/models/{slug}/endpoints"


def _fake_endpoint(
    tag: str,
    *,
    prompt: str = "0.000001",
    status: Any = 0,
    uptime: float = 99.0,
    **extra: Any,
) -> dict[str, Any]:
    endpoint: dict[str, Any] = {
        "name": f"Fake Host {tag}",
        "tag": tag,
        "provider_name": f"Fake Host {tag}",
        "context_length": 8000,
        "pricing": {"prompt": prompt, "completion": "0.000002"},
        "status": status,
        "uptime_last_30m": uptime,
    }
    endpoint.update(extra)
    return endpoint


def _fake_fetch(
    *,
    lists: dict[str, Any],
    listed: dict[str, str],
    other_mappings: tuple[Any, ...] = (),
    list_ids: dict[str, str | None] | None = None,
    provider_id: str = _FAKE_PROVIDER,
    completed_at: str = "2026-09-01T12:00:05+00:00",
    error_messages: dict[str, str] | None = None,
):
    """Build an invented `EndpointFetchResult`.

    `lists` maps a path to a list of endpoint objects (ok/empty) or to an error
    code string. `listed` maps catalog model IDs to their listed path.
    """

    list_ids = list_ids or {}
    error_messages = error_messages or {}
    mappings = [
        EndpointMapping(model_id, "listed", path, None, None, None)
        for model_id, path in listed.items()
    ]
    mappings.extend(other_mappings)
    paths = []
    bodies: dict[str, Any] = {}
    for path in sorted(lists):
        value = lists[path]
        if isinstance(value, str):
            paths.append(
                EndpointPathResult(
                    path, None, "error", (), value, error_messages.get(path, "HTTP 503"), None
                )
            )
            continue
        list_id = list_ids.get(path, path.split("/")[4] + "/" + path.split("/")[5])
        endpoints = tuple(value)
        paths.append(
            EndpointPathResult(
                path, list_id, "ok" if endpoints else "empty", endpoints, None, None, None
            )
        )
        bodies[path] = {"data": {"id": list_id, "endpoints": list(endpoints)}}
    failed = sum(1 for path in paths if path.outcome == "error")
    return EndpointFetchResult(
        provider_id=provider_id,
        started_at="2026-09-01T12:00:00+00:00",
        completed_at=completed_at,
        mappings=tuple(sorted(mappings, key=lambda mapping: mapping.provider_model_id)),
        paths=tuple(paths),
        paths_requested=len(paths),
        paths_attempted=len(paths),
        paths_failed=failed,
        mapping_failures=sum(1 for mapping in mappings if mapping.is_failure),
        bodies=bodies,
    )


def _endpoint_store(tmp_path: Path, name: str = "endpoints.db") -> Store:
    store = Store(tmp_path / name)
    store.initialize()
    return store


def _saved_scrape(
    store: Store,
    *,
    provider_id: str = _FAKE_PROVIDER,
    baseline_scrape_id: int | None = None,
    status: str = "success",
    saved: bool = True,
    minute: int = 0,
) -> int:
    return store.create_scrape(
        provider_id=provider_id,
        started_at=f"2026-09-01T12:{minute:02d}:00+00:00",
        completed_at=f"2026-09-01T12:{minute:02d}:01+00:00",
        status=status,
        baseline_mode="previous",
        baseline_scrape_id=baseline_scrape_id,
        saved_snapshot=saved,
        model_count=1,
        error_message=None,
    )


def _capture(
    store: Store,
    fetch,
    *,
    scrape_id: int,
    baseline_scrape_id: int | None = None,
):

    baseline_capture = (
        store.get_endpoint_capture_for_scrape(baseline_scrape_id)
        if baseline_scrape_id is not None
        else None
    )
    candidate = build_endpoint_capture(
        fetch,
        profile=OPENROUTER_PROFILE,
        scrape_id=scrape_id,
        baseline_scrape_id=baseline_scrape_id,
        baseline_capture=baseline_capture,
    )
    return store.save_endpoint_capture(candidate)


def _scan_with_capture(
    store: Store,
    fetch,
    *,
    baseline_scrape_id: int | None = None,
    provider_id: str = _FAKE_PROVIDER,
    minute: int = 0,
):
    scrape_id = _saved_scrape(
        store, provider_id=provider_id, baseline_scrape_id=baseline_scrape_id, minute=minute
    )
    return scrape_id, _capture(
        store, fetch, scrape_id=scrape_id, baseline_scrape_id=baseline_scrape_id
    )


def _table_counts(store: Store) -> dict[str, int]:
    with store._connect() as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in _ENDPOINT_TABLES
        }


def _gap_tuples(summary) -> tuple[tuple[str, str, str | None], ...]:
    return tuple((gap.list_path, gap.reason, gap.from_list_path) for gap in summary.comparison_gaps)


def _change_tuples(summary) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            change.from_list_path,
            change.list_path,
            change.endpoint_key,
            change.change_kind,
            change.field_name,
            change.old_value,
            change.new_value,
        )
        for change in summary.changes
    )


def _legacy_snapshot(path: Path) -> dict[str, Any]:

    with sqlite3.connect(path) as connection:
        tables = ("providers", "scrapes", "snapshot_models", "field_changes")
        return {
            "sql": connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE tbl_name IN (?, ?, ?, ?) ORDER BY name",
                tables,
            ).fetchall(),
            **{
                table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in tables
            },
        }


def test_endpoint_legacy_schema_preservation(tmp_path: Path) -> None:

    assert storage.SCHEMA[: len(LEGACY_SCHEMA)] == LEGACY_SCHEMA
    added = storage.SCHEMA[len(LEGACY_SCHEMA) :]
    assert len(added) == len(_ENDPOINT_TABLES) + 1
    for statement in added:
        assert statement.count("CREATE ") == 1

    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        for statement in LEGACY_SCHEMA:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO providers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-fake",
                "Legacy Fake",
                "generic",
                "https://legacy-fake.invalid",
                "/models",
                "FAKE_LEGACY_TOKEN",
                1,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        for scrape_id, minute in ((1, 0), (2, 5)):
            connection.execute(
                "INSERT INTO scrapes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    scrape_id,
                    "legacy-fake",
                    f"2026-01-01T00:0{minute}:00+00:00",
                    f"2026-01-01T00:0{minute}:30+00:00",
                    "success",
                    "previous",
                    scrape_id - 1 or None,
                    1,
                    1,
                    None,
                ),
            )
            connection.execute(
                "INSERT INTO snapshot_models (scrape_id, provider_id, provider_model_id, "
                "display_name, input_price, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    scrape_id,
                    "legacy-fake",
                    "fake-org/legacy-model",
                    "Legacy Model",
                    1.5 * scrape_id,
                    canonical_json({"id": "fake-org/legacy-model", "scrape": scrape_id}),
                ),
            )
        connection.execute(
            "INSERT INTO field_changes (provider_id, from_scrape_id, to_scrape_id, "
            "provider_model_id, change_kind, field_name, old_value_json, new_value_json, "
            "detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-fake",
                1,
                2,
                "fake-org/legacy-model",
                "field_changed",
                "input_price",
                "1.5",
                "3.0",
                "2026-01-01T00:05:30+00:00",
            ),
        )
    before = _legacy_snapshot(database_path)

    store = Store(database_path)
    store.initialize()
    store.initialize()

    assert _legacy_snapshot(database_path) == before
    with sqlite3.connect(database_path) as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")
        }
    assert set(_ENDPOINT_TABLES) <= names
    assert "idx_endpoint_changes_provider_list_capture" in names
    assert store.get_latest_saved_baseline("legacy-fake").scrape_id == 2
    assert store.load_saved_models(2)["fake-org/legacy-model"].input_price == 3.0
    assert store.get_latest_endpoint_capture("legacy-fake") is None
    assert store.get_endpoint_capture_for_scrape(2) is None


def test_endpoint_transaction_rollback_including_changes(tmp_path: Path, monkeypatch) -> None:
    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    baseline_scrape, _ = _scan_with_capture(
        store,
        _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed={"fake-org/test-model-a": path}),
    )
    before = _table_counts(store)
    current = _fake_fetch(
        lists={path: [_fake_endpoint("host-a", prompt="0.000003"), _fake_endpoint("host-b")]},
        listed={"fake-org/test-model-a": path},
    )
    scrape_id = _saved_scrape(store, baseline_scrape_id=baseline_scrape, minute=1)

    real_write_changes = storage._write_endpoint_changes
    written: list[int] = []

    def write_then_fail(connection, **kwargs):
        real_write_changes(connection, **kwargs)
        written.append(
            connection.execute("SELECT COUNT(*) FROM endpoint_changes").fetchone()[0]
        )
        raise RuntimeError("injected change-write failure")

    monkeypatch.setattr(storage, "_write_endpoint_changes", write_then_fail)
    with pytest.raises(RuntimeError, match="injected change-write failure"):
        _capture(store, current, scrape_id=scrape_id, baseline_scrape_id=baseline_scrape)

    # The helper wrote change rows on the shared connection, and they vanished
    # with the rest of the capture: nothing was committed independently.
    assert written and written[0] > 0
    assert _table_counts(store) == before
    assert store.get_endpoint_capture_for_scrape(scrape_id) is None

    monkeypatch.setattr(storage, "_write_endpoint_changes", real_write_changes)
    persisted = _capture(store, current, scrape_id=scrape_id, baseline_scrape_id=baseline_scrape)
    assert {change.change_kind for change in persisted.changes} == {"field_changed", "endpoint_added"}
    assert _table_counts(store)["endpoint_changes"] == len(persisted.changes)


def test_endpoint_transaction_rollback_including_changes_on_late_constraint(tmp_path: Path) -> None:


    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    scrape_id = _saved_scrape(store)
    candidate = build_endpoint_capture(
        _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed={"fake-org/test-model-a": path}),
        profile=OPENROUTER_PROFILE,
        scrape_id=scrape_id,
        baseline_scrape_id=None,
        baseline_capture=None,
    )
    # A duplicated list path violates the endpoint_lists primary key after the
    # capture row and mappings were already written in the same transaction.
    broken = replace(
        candidate, summary=replace(candidate.summary, lists=candidate.summary.lists * 2)
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.save_endpoint_capture(broken)
    assert set(_table_counts(store).values()) == {0}


def test_endpoint_state_deduplication(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    path_a = _endpoint_path("fake-org/test-model-a")
    path_b = _endpoint_path("fake-org/test-model-b")
    listed = {"fake-org/test-model-a": path_a, "fake-org/test-model-b": path_b}
    # Same stable state on both lists; telemetry and status differ and must not
    # create a second state row.
    first = _fake_fetch(
        lists={
            path_a: [_fake_endpoint("host-a", uptime=99.0, status=0)],
            path_b: [_fake_endpoint("host-a", uptime=42.0, status=-1)],
        },
        listed=listed,
    )
    scrape_1, capture_1 = _scan_with_capture(store, first)
    assert _table_counts(store)["endpoint_states"] == 1
    assert _table_counts(store)["endpoint_observations"] == 2
    hashes = {obs.state_hash for listing in capture_1.lists for obs in listing.observations}
    assert len(hashes) == 1
    assert [obs.status_code for listing in capture_1.lists for obs in listing.observations] == [0, -1]

    scrape_2, capture_2 = _scan_with_capture(
        store, first, baseline_scrape_id=scrape_1, minute=1
    )
    assert _table_counts(store)["endpoint_states"] == 1
    assert _table_counts(store)["endpoint_observations"] == 4
    assert capture_2.changes == ()

    changed = _fake_fetch(
        lists={
            path_a: [_fake_endpoint("host-a", prompt="0.000005")],
            path_b: [_fake_endpoint("host-a", status=-1)],
        },
        listed=listed,
    )
    _, capture_3 = _scan_with_capture(store, changed, baseline_scrape_id=scrape_2, minute=2)
    assert _table_counts(store)["endpoint_states"] == 2
    with store._connect() as connection:
        rows = connection.execute("SELECT state_hash, state_json FROM endpoint_states").fetchall()
    for row in rows:
        state = json.loads(row["state_json"])
        assert "status" not in state and "uptime_last_30m" not in state
        assert row["state_json"] == canonical_json(state)
    assert _change_tuples(capture_3) == (
        (path_a, path_a, "host-a#0", "field_changed", "pricing.prompt", "0.000001", "0.000005"),
    )


def test_endpoint_state_deduplication_non_integer_status_is_not_stored(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    listed = {"fake-org/test-model-a": path}
    fetch = _fake_fetch(
        lists={
            path: [
                _fake_endpoint("host-a", status="degraded"),
                _fake_endpoint("host-b", status=True),
                _fake_endpoint("host-c", status=None),
            ]
        },
        listed=listed,
    )
    scrape_1, capture_1 = _scan_with_capture(store, fetch)
    assert [obs.status_code for obs in capture_1.lists[0].observations] == [None, None, None]
    with store._connect() as connection:
        stored = connection.execute(
            "SELECT status_code FROM endpoint_observations ORDER BY rowid"
        ).fetchall()
    assert [row[0] for row in stored] == [None, None, None]
    # The in-memory current side uses the same normalization, so repeating the
    # fetch produces no spurious status change.
    _, capture_2 = _scan_with_capture(store, fetch, baseline_scrape_id=scrape_1, minute=1)
    assert capture_2.changes == ()


def test_endpoint_selected_baseline_gaps_no_selected_baseline(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    _, summary = _scan_with_capture(
        store, _fake_fetch(lists={path: "http_status"}, listed={"fake-org/test-model-a": path})
    )
    assert summary.comparison_state == "no_selected_baseline"
    assert summary.baseline_capture_id is None
    assert summary.changes == () and summary.comparison_gaps == ()


def test_endpoint_selected_baseline_gaps_missing_baseline_capture(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    baseline_scrape = _saved_scrape(store)
    _, summary = _scan_with_capture(
        store,
        _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed={"fake-org/test-model-a": path}),
        baseline_scrape_id=baseline_scrape,
        minute=1,
    )
    assert summary.comparison_state == "missing_baseline_capture"
    assert summary.baseline_capture_id is None
    assert summary.changes == () and summary.comparison_gaps == ()


def test_endpoint_selected_baseline_gaps_unusable_baseline(tmp_path: Path) -> None:

    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    listed = {"fake-org/test-model-a": path}
    baseline_scrape = _saved_scrape(store)
    error_capture = store.save_endpoint_error_capture(
        build_endpoint_error_summary(
            provider_id=_FAKE_PROVIDER,
            scrape_id=baseline_scrape,
            completed_at="2026-09-01T12:00:02+00:00",
            error_summary="endpoint capture failed: RuntimeError",
        )
    )
    assert error_capture.persistence_error is None and error_capture.status == "error"
    _, summary = _scan_with_capture(
        store,
        _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed=listed),
        baseline_scrape_id=baseline_scrape,
        minute=1,
    )
    assert summary.comparison_state == "unusable_baseline"
    assert summary.baseline_capture_id == error_capture.capture_id
    assert summary.changes == () and summary.comparison_gaps == ()

    # A fetched capture whose every path failed is also an unusable `error` baseline.
    failed_scrape, failed = _scan_with_capture(
        store, _fake_fetch(lists={path: "timeout"}, listed=listed), minute=2
    )
    assert failed.status == "error"
    _, after_failed = _scan_with_capture(
        store,
        _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed=listed),
        baseline_scrape_id=failed_scrape,
        minute=3,
    )
    assert after_failed.comparison_state == "unusable_baseline"


def test_endpoint_selected_baseline_gaps_partial_baseline_is_usable(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    path_a = _endpoint_path("fake-org/test-model-a")
    path_b = _endpoint_path("fake-org/test-model-b")
    listed = {"fake-org/test-model-a": path_a, "fake-org/test-model-b": path_b}
    baseline_scrape, baseline = _scan_with_capture(
        store, _fake_fetch(lists={path_a: [_fake_endpoint("host-a")], path_b: "timeout"}, listed=listed)
    )
    assert baseline.status == "partial"
    _, summary = _scan_with_capture(
        store,
        _fake_fetch(
            lists={path_a: [_fake_endpoint("host-a", prompt="0.000009")], path_b: "http_status"},
            listed=listed,
        ),
        baseline_scrape_id=baseline_scrape,
        minute=1,
    )
    assert summary.comparison_state == "available"
    assert summary.baseline_capture_id == baseline.capture_id
    assert _change_tuples(summary) == (
        (path_a, path_a, "host-a#0", "field_changed", "pricing.prompt", "0.000001", "0.000009"),
    )
    # Failed observations on either side suppress the diff and record a gap.
    assert _gap_tuples(summary) == (
        (path_b, "baseline_observation_failed", path_b),
        (path_b, "current_observation_failed", path_b),
    )


def test_endpoint_selected_baseline_gaps_failed_current_observation(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    listed = {"fake-org/test-model-a": path}
    baseline_scrape, _ = _scan_with_capture(
        store, _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed=listed)
    )
    _, summary = _scan_with_capture(
        store,
        _fake_fetch(lists={path: "invalid_json"}, listed=listed),
        baseline_scrape_id=baseline_scrape,
        minute=1,
    )
    assert summary.comparison_state == "available"
    assert summary.changes == ()
    assert _gap_tuples(summary) == ((path, "current_observation_failed", path),)


def test_endpoint_selected_baseline_gaps_never_substitute_latest_capture(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    listed = {"fake-org/test-model-a": path}
    first_scrape, first = _scan_with_capture(
        store, _fake_fetch(lists={path: [_fake_endpoint("host-a", prompt="0.000001")]}, listed=listed)
    )
    _, latest = _scan_with_capture(
        store,
        _fake_fetch(lists={path: [_fake_endpoint("host-a", prompt="0.000002")]}, listed=listed),
        baseline_scrape_id=first_scrape,
        minute=1,
    )
    assert store.get_latest_endpoint_capture(_FAKE_PROVIDER).capture_id == latest.capture_id
    _, summary = _scan_with_capture(
        store,
        _fake_fetch(lists={path: [_fake_endpoint("host-a", prompt="0.000002")]}, listed=listed),
        baseline_scrape_id=first_scrape,
        minute=2,
    )
    assert summary.baseline_capture_id == first.capture_id
    assert [change.from_capture_id for change in summary.changes] == [first.capture_id]
    assert _change_tuples(summary) == (
        (path, path, "host-a#0", "field_changed", "pricing.prompt", "0.000001", "0.000002"),
    )


def test_endpoint_selected_baseline_gaps_reject_mismatched_baseline(tmp_path: Path) -> None:

    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    fetch = _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed={"fake-org/test-model-a": path})
    first_scrape, first = _scan_with_capture(store, fetch)
    with pytest.raises(ValueError, match="selected baseline"):
        build_endpoint_capture(
            fetch,
            profile=OPENROUTER_PROFILE,
            scrape_id=first_scrape + 1,
            baseline_scrape_id=first_scrape + 99,
            baseline_capture=first,
        )
    other = _fake_fetch(
        lists={path: [_fake_endpoint("host-a")]},
        listed={"fake-org/test-model-a": path},
        provider_id=_OTHER_PROVIDER,
    )
    with pytest.raises(ValueError, match="provider"):
        build_endpoint_capture(
            other,
            profile=OPENROUTER_PROFILE,
            scrape_id=first_scrape + 1,
            baseline_scrape_id=first_scrape,
            baseline_capture=first,
        )


def test_endpoint_shared_path_identity(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    shared = _endpoint_path("fake-org/test-model-a")
    own = _endpoint_path("fake-org/test-model-c")
    listed = {
        "fake-org/test-model-a": shared,
        "fake-org/test-model-b": shared,
        "fake-org/test-model-c": own,
    }
    baseline_scrape, baseline = _scan_with_capture(
        store,
        _fake_fetch(
            lists={
                shared: [_fake_endpoint("host-a"), _fake_endpoint("host-b")],
                own: [_fake_endpoint("host-c", status=0)],
            },
            listed=listed,
            list_ids={own: None},
        ),
    )
    current_scrape, summary = _scan_with_capture(
        store,
        _fake_fetch(
            lists={
                shared: [_fake_endpoint("host-a", prompt="0.000004"), _fake_endpoint("host-d")],
                own: [_fake_endpoint("host-c", status=-1)],
            },
            listed=listed,
            list_ids={own: None},
        ),
        baseline_scrape_id=baseline_scrape,
        minute=1,
    )
    removed_state = _endpoint_state_for_test(_fake_endpoint("host-b"))
    added_state = _endpoint_state_for_test(_fake_endpoint("host-d"))
    assert _change_tuples(summary) == (
        (shared, shared, "host-a#0", "field_changed", "pricing.prompt", "0.000001", "0.000004"),
        (shared, shared, "host-b#0", "endpoint_removed", None, removed_state, None),
        (shared, shared, "host-d#0", "endpoint_added", None, None, added_state),
        (own, own, "host-c#0", "status_changed", None, 0, -1),
    )
    by_path = {change.list_path: change for change in summary.changes}
    assert by_path[shared].display_id == "fake-org/test-model-a"
    assert by_path[shared].model_ids == ("fake-org/test-model-a", "fake-org/test-model-b")
    assert by_path[own].display_id == own
    assert by_path[own].model_ids == ("fake-org/test-model-c",)
    assert {(c.from_capture_id, c.to_capture_id) for c in summary.changes} == {
        (baseline.capture_id, summary.capture_id)
    }
    assert summary.comparison_gaps == ()
    assert summary.first_capture is False and summary.status == "complete"

    # The returned summary is the persisted one and every read path agrees.
    assert store.get_endpoint_capture_for_scrape(current_scrape) == summary
    assert store.get_latest_endpoint_capture(_FAKE_PROVIDER) == summary
    assert store.load_endpoint_lists(summary.capture_id) == summary.lists
    shared_list = next(listing for listing in summary.lists if listing.list_path == shared)
    assert [obs.endpoint_key for obs in shared_list.observations] == ["host-a#0", "host-d#0"]
    assert shared_list.list_model_id == "fake-org/test-model-a"
    assert shared_list.outcome == "ok" and shared_list.endpoint_count == 2

    with store._connect() as connection:
        rows = connection.execute(
            "SELECT provider_id, from_capture_id, to_capture_id, from_list_path, list_path, "
            "endpoint_key, change_kind, field_name, old_value_json, new_value_json, detected_at "
            "FROM endpoint_changes ORDER BY endpoint_change_id"
        ).fetchall()
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM endpoint_changes "
            "WHERE provider_id = ? AND list_path = ? ORDER BY to_capture_id",
            (_FAKE_PROVIDER, shared),
        ).fetchall()
    assert rows[0]["old_value_json"] == '"0.000001"'
    assert rows[1]["new_value_json"] is None and rows[2]["old_value_json"] is None
    assert rows[3]["old_value_json"] == "0" and rows[3]["new_value_json"] == "-1"
    assert {row["detected_at"] for row in rows} == {"2026-09-01T12:00:05+00:00"}
    assert {row["provider_id"] for row in rows} == {_FAKE_PROVIDER}
    assert any("idx_endpoint_changes_provider_list_capture" in str(tuple(row)) for row in plan)

    # The archive keeps the decoded bodies, telemetry included, keyed by path.
    with store._connect() as connection:
        blob = connection.execute(
            "SELECT body_gzip FROM endpoint_capture_archives WHERE capture_id = ?",
            (summary.capture_id,),
        ).fetchone()[0]
    archive = json.loads(gzip.decompress(blob))
    assert sorted(archive) == [shared, own]
    assert archive[shared]["data"]["endpoints"][0]["uptime_last_30m"] == 99.0
    assert archive[own]["data"]["id"] is None


def _endpoint_state_for_test(endpoint: dict[str, Any]) -> dict[str, Any]:

    return json.loads(canonical_json(endpoint_state(endpoint, OPENROUTER_PROFILE)))


def test_endpoint_shared_path_identity_takes_precedence_over_mapping_moves(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    path_o = _endpoint_path("fake-org/test-model-o")
    path_s = _endpoint_path("fake-org/test-model-s")
    baseline_scrape, _ = _scan_with_capture(
        store,
        _fake_fetch(
            lists={path_o: [_fake_endpoint("host-o")], path_s: [_fake_endpoint("host-s")]},
            listed={"fake-org/test-model-a": path_o, "fake-org/test-model-s": path_s},
        ),
    )
    # Model A moves from O to S while both paths stay present: both are still
    # compared as shared paths and no move or ambiguity is recorded.
    _, summary = _scan_with_capture(
        store,
        _fake_fetch(
            lists={
                path_o: [_fake_endpoint("host-o", prompt="0.000007")],
                path_s: [_fake_endpoint("host-s")],
            },
            listed={
                "fake-org/test-model-o": path_o,
                "fake-org/test-model-a": path_s,
                "fake-org/test-model-s": path_s,
            },
        ),
        baseline_scrape_id=baseline_scrape,
        minute=1,
    )
    assert _change_tuples(summary) == (
        (path_o, path_o, "host-o#0", "field_changed", "pricing.prompt", "0.000001", "0.000007"),
    )
    assert summary.comparison_gaps == ()


def _move_scenario(
    tmp_path: Path,
    *,
    baseline_lists: dict[str, Any],
    baseline_listed: dict[str, str],
    current_lists: dict[str, Any],
    current_listed: dict[str, str],
):
    store = _endpoint_store(tmp_path)
    baseline_scrape, _ = _scan_with_capture(
        store, _fake_fetch(lists=baseline_lists, listed=baseline_listed)
    )
    _, summary = _scan_with_capture(
        store,
        _fake_fetch(lists=current_lists, listed=current_listed),
        baseline_scrape_id=baseline_scrape,
        minute=1,
    )
    return store, summary


def test_endpoint_moves_splits_and_merges_unique_move(tmp_path: Path) -> None:
    old = _endpoint_path("fake-org/test-model-a")
    new = _endpoint_path("fake-org/test-model-a-v2")
    store, summary = _move_scenario(
        tmp_path,
        baseline_lists={old: [_fake_endpoint("host-a")]},
        # Two common models follow the same edge; they are deduplicated to one diff.
        baseline_listed={"fake-org/test-model-a": old, "fake-org/test-model-b": old},
        current_lists={new: [_fake_endpoint("host-a", prompt="0.000006")]},
        current_listed={"fake-org/test-model-a": new, "fake-org/test-model-b": new},
    )
    assert _change_tuples(summary) == (
        (old, new, "host-a#0", "field_changed", "pricing.prompt", "0.000001", "0.000006"),
    )
    assert summary.comparison_gaps == ()
    with store._connect() as connection:
        row = connection.execute("SELECT from_list_path, list_path FROM endpoint_changes").fetchone()
    assert tuple(row) == (old, new)


def test_endpoint_moves_splits_and_merges_split(tmp_path: Path) -> None:
    old = _endpoint_path("fake-org/test-model-a")
    new_1 = _endpoint_path("fake-org/test-model-a-v2")
    new_2 = _endpoint_path("fake-org/test-model-b-v2")
    _, summary = _move_scenario(
        tmp_path,
        baseline_lists={old: [_fake_endpoint("host-a")]},
        baseline_listed={"fake-org/test-model-a": old, "fake-org/test-model-b": old},
        current_lists={new_1: [_fake_endpoint("host-a")], new_2: [_fake_endpoint("host-a")]},
        current_listed={"fake-org/test-model-a": new_1, "fake-org/test-model-b": new_2},
    )
    assert summary.changes == ()
    # Gaps sort by path text, where "-v2/" sorts before "/".
    assert _gap_tuples(summary) == (
        (new_1, "ambiguous_mapping", None),
        (old, "ambiguous_mapping", old),
        (new_2, "ambiguous_mapping", None),
    )


def test_endpoint_moves_splits_and_merges_merge(tmp_path: Path) -> None:
    old_1 = _endpoint_path("fake-org/test-model-a")
    old_2 = _endpoint_path("fake-org/test-model-b")
    new = _endpoint_path("fake-org/test-model-ab")
    _, summary = _move_scenario(
        tmp_path,
        baseline_lists={old_1: [_fake_endpoint("host-a")], old_2: [_fake_endpoint("host-b")]},
        baseline_listed={"fake-org/test-model-a": old_1, "fake-org/test-model-b": old_2},
        current_lists={new: [_fake_endpoint("host-a")]},
        current_listed={"fake-org/test-model-a": new, "fake-org/test-model-b": new},
    )
    assert summary.changes == ()
    assert _gap_tuples(summary) == (
        (old_1, "ambiguous_mapping", old_1),
        (new, "ambiguous_mapping", None),
        (old_2, "ambiguous_mapping", old_2),
    )


def test_endpoint_moves_splits_and_merges_partial_move(tmp_path: Path) -> None:
    old = _endpoint_path("fake-org/test-model-a")
    new = _endpoint_path("fake-org/test-model-a-v2")
    _, summary = _move_scenario(
        tmp_path,
        baseline_lists={old: [_fake_endpoint("host-a")]},
        baseline_listed={"fake-org/test-model-a": old, "fake-org/test-model-b": old},
        current_lists={old: [_fake_endpoint("host-a")], new: [_fake_endpoint("host-a")]},
        current_listed={"fake-org/test-model-a": old, "fake-org/test-model-b": new},
    )
    # The old path is still present and compared in place; the partially moved
    # list starts a new baseline.
    assert summary.changes == ()
    assert _gap_tuples(summary) == ((new, "ambiguous_mapping", None),)


def test_endpoint_moves_splits_and_merges_merge_into_existing_path(tmp_path: Path) -> None:
    old = _endpoint_path("fake-org/test-model-a")
    kept = _endpoint_path("fake-org/test-model-s")
    _, summary = _move_scenario(
        tmp_path,
        baseline_lists={old: [_fake_endpoint("host-a")], kept: [_fake_endpoint("host-s")]},
        baseline_listed={"fake-org/test-model-a": old, "fake-org/test-model-s": kept},
        current_lists={kept: [_fake_endpoint("host-s")]},
        current_listed={"fake-org/test-model-a": kept, "fake-org/test-model-s": kept},
    )
    assert summary.changes == ()
    assert _gap_tuples(summary) == ((old, "ambiguous_mapping", old),)


def test_endpoint_moves_splits_and_merges_unpaired_paths(tmp_path: Path) -> None:

    kept = _endpoint_path("fake-org/test-model-a")
    gone = _endpoint_path("fake-org/test-model-b")
    fresh = _endpoint_path("fake-org/test-model-c")
    _, summary = _move_scenario(
        tmp_path,
        baseline_lists={kept: [_fake_endpoint("host-a")], gone: [_fake_endpoint("host-b")]},
        baseline_listed={"fake-org/test-model-a": kept, "fake-org/test-model-b": gone},
        current_lists={kept: [_fake_endpoint("host-a")], fresh: []},
        current_listed={"fake-org/test-model-a": kept, "fake-org/test-model-c": fresh},
    )
    # Newly appearing or disappearing paths produce no presence diff, only a
    # coverage disposition. A complete capture can still have gaps.
    assert summary.status == "complete"
    assert summary.changes == ()
    assert _gap_tuples(summary) == (
        (gone, "removed_path_unpaired", gone),
        (fresh, "new_path_unpaired", None),
    )


def test_endpoint_moves_splits_and_merges_move_with_failed_observation(tmp_path: Path) -> None:
    old = _endpoint_path("fake-org/test-model-a")
    new = _endpoint_path("fake-org/test-model-a-v2")
    _, summary = _move_scenario(
        tmp_path,
        baseline_lists={old: [_fake_endpoint("host-a")]},
        baseline_listed={"fake-org/test-model-a": old},
        current_lists={new: "http_status"},
        current_listed={"fake-org/test-model-a": new},
    )
    assert summary.changes == ()
    assert _gap_tuples(summary) == ((new, "current_observation_failed", old),)


def test_endpoint_first_capture_independent_of_baseline(tmp_path: Path) -> None:

    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    fetch = _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed={"fake-org/test-model-a": path})

    # The first persisted capture for a provider can be a minimal error capture.
    error_scrape = _saved_scrape(store)
    error_capture = store.save_endpoint_error_capture(
        build_endpoint_error_summary(
            provider_id=_FAKE_PROVIDER,
            scrape_id=error_scrape,
            completed_at="2026-09-01T12:00:02+00:00",
            error_summary="endpoint capture failed",
        )
    )
    assert error_capture.first_capture is True

    scrape_id = _saved_scrape(store, minute=1)
    candidate = build_endpoint_capture(
        fetch,
        profile=OPENROUTER_PROFILE,
        scrape_id=scrape_id,
        baseline_scrape_id=None,
        baseline_capture=None,
    )
    # first_capture is assigned only inside the persistence transaction.
    assert candidate.summary.first_capture is None
    no_baseline = store.save_endpoint_capture(candidate)
    assert no_baseline.comparison_state == "no_selected_baseline"
    assert no_baseline.first_capture is False

    _, missing = _scan_with_capture(store, fetch, baseline_scrape_id=_saved_scrape(store, minute=2), minute=3)
    assert missing.comparison_state == "missing_baseline_capture"
    assert missing.first_capture is False

    _, other_provider = _scan_with_capture(
        store,
        _fake_fetch(
            lists={path: [_fake_endpoint("host-a")]},
            listed={"fake-org/test-model-a": path},
            provider_id=_OTHER_PROVIDER,
        ),
        provider_id=_OTHER_PROVIDER,
        minute=4,
    )
    assert other_provider.first_capture is True
    with store._connect() as connection:
        rows = connection.execute(
            "SELECT provider_id, first_capture FROM endpoint_captures ORDER BY capture_id"
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        (_FAKE_PROVIDER, 1),
        (_FAKE_PROVIDER, 0),
        (_FAKE_PROVIDER, 0),
        (_OTHER_PROVIDER, 1),
    ]


def test_endpoint_sanitized_error_roundtrip(tmp_path: Path) -> None:

    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    baseline_scrape, baseline = _scan_with_capture(
        store, _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed={"fake-org/test-model-a": path})
    )
    scrape_id = _saved_scrape(store, baseline_scrape_id=baseline_scrape, minute=1)
    raw = "endpoint\ncapture\x00failed:\t" + "x" * 400
    summary = build_endpoint_error_summary(
        provider_id=_FAKE_PROVIDER,
        scrape_id=scrape_id,
        started_at="2026-09-01T12:01:01+00:00",
        completed_at="2026-09-01T12:01:02+00:00",
        error_summary=raw,
        baseline_scrape_id=baseline_scrape,
        baseline_capture=baseline,
    )
    assert summary.capture_id is None and summary.persistence_error is None
    assert summary.status == "error"
    assert summary.error_summary.startswith("endpoint capture failed: xxx")
    assert len(summary.error_summary) == ENDPOINT_ERROR_MESSAGE_LIMIT
    assert summary.error_summary.endswith("...")
    assert (summary.paths_requested, summary.paths_attempted, summary.paths_failed) == (0, 0, 0)
    assert summary.comparison_state == "available"
    assert summary.baseline_capture_id == baseline.capture_id
    assert summary.lists == () and summary.changes == () and summary.comparison_gaps == ()

    persisted = store.save_endpoint_error_capture(summary)
    assert persisted.persistence_error is None
    assert persisted.capture_id is not None
    assert persisted.error_summary == summary.error_summary
    assert persisted.started_at == "2026-09-01T12:01:01+00:00"
    assert persisted.first_capture is False
    assert store.get_endpoint_capture_for_scrape(scrape_id) == persisted
    with store._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM endpoint_capture_archives WHERE capture_id = ?",
            (persisted.capture_id,),
        ).fetchone()[0] == 0


def test_endpoint_sanitized_error_roundtrip_list_messages(tmp_path: Path) -> None:
    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    _, summary = _scan_with_capture(
        store,
        _fake_fetch(
            lists={path: "network"},
            listed={"fake-org/test-model-a": path},
            error_messages={path: "network\r\nfailure\x1b[31m " + "y" * 300},
        ),
    )
    message = summary.lists[0].error_message
    assert message.startswith("network failure [31m yyy")
    assert len(message) <= 200 and "\n" not in message and "\x1b" not in message
    assert summary.lists[0].error_code == "network"


def test_endpoint_sanitized_error_roundtrip_fallback_reuses_committed_capture(tmp_path: Path) -> None:

    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    scrape_id, committed = _scan_with_capture(
        store, _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed={"fake-org/test-model-a": path})
    )
    before = _table_counts(store)
    reused = store.save_endpoint_error_capture(
        build_endpoint_error_summary(
            provider_id=_FAKE_PROVIDER,
            scrape_id=scrape_id,
            completed_at="2026-09-01T12:00:09+00:00",
            error_summary="post-commit failure",
        )
    )
    assert reused == committed
    assert reused.status == "complete" and reused.error_summary is None
    assert _table_counts(store) == before


def test_endpoint_sanitized_error_roundtrip_fallback_failure_is_retained(tmp_path: Path) -> None:

    store = _endpoint_store(tmp_path)
    unsaved_scrape = _saved_scrape(store, saved=False)
    summary = build_endpoint_error_summary(
        provider_id=_FAKE_PROVIDER,
        scrape_id=unsaved_scrape,
        completed_at="2026-09-01T12:00:02+00:00",
        error_summary="endpoint capture failed",
    )
    result = store.save_endpoint_error_capture(summary)
    assert result.capture_id is None
    assert result.error_summary == "endpoint capture failed"
    assert result.persistence_error is not None
    assert "saved success" in result.persistence_error
    assert len(result.persistence_error) <= 200
    assert set(_table_counts(store).values()) == {0}

    broken = Store(tmp_path / "missing-dir" / "nested" / "endpoints.db")
    result = broken.save_endpoint_error_capture(summary)
    assert result.capture_id is None and result.persistence_error


def test_endpoint_foreign_key_enforcement_and_saved_scrape_identity(tmp_path: Path) -> None:

    store = _endpoint_store(tmp_path)
    with closing(store._connect_capture_writer()) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO endpoint_lists (capture_id, list_path, outcome, endpoint_count) "
                "VALUES (999, '/api/v1/models/fake-org/orphan/endpoints', 'empty', 0)"
            )
    # The policy is local to capture writes; other Store connections are unchanged.
    with store._connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0


def _rejected_capture(store: Store, scrape_id: int, *, provider_id: str = _FAKE_PROVIDER):

    path = _endpoint_path("fake-org/test-model-a")
    candidate = build_endpoint_capture(
        _fake_fetch(
            lists={path: [_fake_endpoint("host-a")]},
            listed={"fake-org/test-model-a": path},
            provider_id=provider_id,
        ),
        profile=OPENROUTER_PROFILE,
        scrape_id=scrape_id,
        baseline_scrape_id=None,
        baseline_capture=None,
    )
    with pytest.raises(storage.EndpointCaptureIntegrityError) as exc_info:
        store.save_endpoint_capture(candidate)
    return str(exc_info.value)


def test_endpoint_foreign_key_enforcement_and_saved_scrape_identity_rejects_scrapes(
    tmp_path: Path,
) -> None:
    store = _endpoint_store(tmp_path)
    assert "saved success" in _rejected_capture(store, _saved_scrape(store, saved=False))
    assert "saved success" in _rejected_capture(store, _saved_scrape(store, status="error", saved=False))
    assert "saved success" in _rejected_capture(store, _saved_scrape(store, provider_id=_OTHER_PROVIDER))
    assert "saved success" in _rejected_capture(store, 4242)
    assert set(_table_counts(store).values()) == {0}


def test_endpoint_foreign_key_enforcement_and_saved_scrape_identity_rejects_baselines(
    tmp_path: Path,
) -> None:


    store = _endpoint_store(tmp_path)
    path = _endpoint_path("fake-org/test-model-a")
    listed = {"fake-org/test-model-a": path}
    other_scrape, other_capture = _scan_with_capture(
        store,
        _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed=listed, provider_id=_OTHER_PROVIDER),
        provider_id=_OTHER_PROVIDER,
    )
    own_scrape, own_capture = _scan_with_capture(
        store, _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed=listed), minute=1
    )
    before = _table_counts(store)
    scrape_id = _saved_scrape(store, baseline_scrape_id=own_scrape, minute=2)
    candidate = build_endpoint_capture(
        _fake_fetch(lists={path: [_fake_endpoint("host-a", prompt="0.000008")]}, listed=listed),
        profile=OPENROUTER_PROFILE,
        scrape_id=scrape_id,
        baseline_scrape_id=own_scrape,
        baseline_capture=own_capture,
    )
    foreign_summary = replace(
        candidate.summary,
        baseline_capture_id=other_capture.capture_id,
        changes=tuple(
            replace(change, from_capture_id=other_capture.capture_id)
            for change in candidate.summary.changes
        ),
    )
    with pytest.raises(storage.EndpointCaptureIntegrityError, match="baseline capture"):
        store.save_endpoint_capture(replace(candidate, summary=foreign_summary))
    assert _table_counts(store) == before

    # A baseline capture of this provider that is not the selected baseline
    # scrape's capture is not substituted either.
    _, unselected = _scan_with_capture(
        store, _fake_fetch(lists={path: [_fake_endpoint("host-a")]}, listed=listed), minute=3
    )
    before = _table_counts(store)
    substituted = replace(
        candidate.summary,
        baseline_capture_id=unselected.capture_id,
        changes=tuple(
            replace(change, from_capture_id=unselected.capture_id)
            for change in candidate.summary.changes
        ),
    )
    with pytest.raises(storage.EndpointCaptureIntegrityError, match="selected baseline"):
        store.save_endpoint_capture(replace(candidate, summary=substituted))
    assert _table_counts(store) == before

    persisted = store.save_endpoint_capture(candidate)

    with pytest.raises(sqlite3.IntegrityError):
        store.save_endpoint_capture(candidate)
    assert store.get_endpoint_capture_for_scrape(scrape_id) == persisted


def test_endpoint_foreign_key_enforcement_and_saved_scrape_identity_requires_pragma(
    tmp_path: Path, monkeypatch
) -> None:

    class ForeignKeysUnavailable(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.strip().upper() == "PRAGMA FOREIGN_KEYS":
                return super().execute("SELECT 0")
            return super().execute(sql, *args)

    store = _endpoint_store(tmp_path)
    scrape_id = _saved_scrape(store)
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        storage.sqlite3,
        "connect",
        lambda *args, **kwargs: real_connect(*args, factory=ForeignKeysUnavailable, **kwargs),
    )
    message = _rejected_capture(store, scrape_id)
    assert "foreign key" in message
    monkeypatch.undo()
    assert set(_table_counts(store).values()) == {0}
