import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest

from model_sentinel.config import ProviderConfig
from model_sentinel.models import FieldChange, ModelDelta, NormalizedModel, canonical_json
from model_sentinel import storage
from model_sentinel.storage import Store
from model_sentinel.time_utils import local_date_for


def _model(
    model_id: str,
    *,
    provider_id: str = "openrouter",
    provider_label: str = "OpenRouter",
    display_name: str | None = None,
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
        metadata_json=canonical_json({"id": model_id}),
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
