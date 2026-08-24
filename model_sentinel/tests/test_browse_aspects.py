from __future__ import annotations

import sqlite3
from pathlib import Path

from model_sentinel.browse.aspects import build_aspect_catalog
from model_sentinel.browse.readonly import open_readonly
from model_sentinel.normalize import (
    _profile_field_candidate,
    normalize_models,
    profile_field_candidate,
)
from model_sentinel.provider_profiles import resolve_profile
from model_sentinel.reporting import make_report_detail_policy
from model_sentinel.storage import Store
from tests.browse_fixtures import EXAMPLE_PROVIDER, OTHER_PROVIDER, build_fixture_db


def _profiles():
    return {
        provider.provider_id: resolve_profile(
            provider.kind,
            price_multiplier=provider.price_multiplier,
            price_divisor=provider.price_divisor,
        )
        for provider in (EXAMPLE_PROVIDER, OTHER_PROVIDER)
    }


def _catalog(database_path: Path):
    database = open_readonly(database_path)
    try:
        return build_aspect_catalog(
            database,
            profiles=_profiles(),
            policy=make_report_detail_policy(
                squelch_fields=EXAMPLE_PROVIDER_PROFILE.default_squelch_fields,
            ),
        )
    finally:
        database.close_all()


EXAMPLE_PROVIDER_PROFILE = resolve_profile(
    EXAMPLE_PROVIDER.kind,
    price_multiplier=EXAMPLE_PROVIDER.price_multiplier,
    price_divisor=EXAMPLE_PROVIDER.price_divisor,
)


def _add_out_of_order_saved_scrapes(database_path: Path) -> None:
    store = Store(database_path)

    def save(completed_at: str, raw_model: dict[str, object]) -> int:
        scrape_id = store.create_scrape(
            provider_id=EXAMPLE_PROVIDER.provider_id,
            started_at=completed_at,
            completed_at=completed_at,
            status="success",
            baseline_mode="previous",
            baseline_scrape_id=None,
            saved_snapshot=True,
            model_count=1,
            error_message=None,
        )
        store.save_snapshot_models(
            scrape_id=scrape_id,
            provider_id=EXAMPLE_PROVIDER.provider_id,
            models=normalize_models(
                EXAMPLE_PROVIDER,
                [raw_model],
                EXAMPLE_PROVIDER_PROFILE,
            ),
        )
        return scrape_id

    newer_scrape = save(
        "2026-08-21T12:00:00+00:00",
        {
            "id": "fake-org/chronology-test-model",
            "name": "Synthetic Chronology Test Model",
            "pricing": {"input": 0.000004},
            "chronology_probe": 42,
        },
    )
    older_scrape = save(
        "2026-08-20T12:00:00+00:00",
        {
            "id": "fake-org/chronology-test-model",
            "name": "Synthetic Chronology Test Model",
            "pricing": {"prompt": 0.000005},
            "chronology_probe": "older text",
        },
    )
    assert newer_scrape < older_scrape
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """INSERT INTO field_changes (
                   provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                   change_kind, field_name, old_value_json, new_value_json, detected_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    EXAMPLE_PROVIDER.provider_id,
                    older_scrape,
                    newer_scrape,
                    "fake-org/chronology-test-model",
                    "changed",
                    "chronology_probe",
                    '"older text"',
                    "42",
                    "2026-08-21T12:00:00+00:00",
                ),
                (
                    EXAMPLE_PROVIDER.provider_id,
                    older_scrape,
                    newer_scrape,
                    "fake-org/chronology-test-model",
                    "removed",
                    "pricing.prompt",
                    "0.000005",
                    None,
                    "2026-08-21T12:00:00+00:00",
                ),
            ),
        )


def test_profile_field_candidate_is_published_without_removing_private_alias() -> None:
    assert profile_field_candidate is _profile_field_candidate


def test_catalog_resolves_column_price_path_and_does_not_rescale_canonical_value(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)

    by_id = {aspect.id: aspect for aspect in _catalog(database_path)}
    aspect = by_id["example-provider:input_price"]

    assert aspect.kind == "price"
    assert aspect.category == "Pricing"
    assert aspect.unit == "/1M tokens"
    assert aspect.multiplier == 1
    assert aspect.divisor == 1
    assert aspect.field_name == "pricing.prompt"


def test_catalog_omits_discovered_paths_represented_by_canonical_aspects(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)

    by_id = {aspect.id: aspect for aspect in _catalog(database_path)}

    assert by_id["example-provider:input_price"].field_name == "pricing.prompt"
    assert "example-provider:path:pricing.prompt" not in by_id
    assert by_id["example-provider:context_window"].field_name == "context_length"
    assert "example-provider:path:context_length" not in by_id

    assert "example-provider:path:supported_parameters" in by_id
    assert "example-provider:path:benchmarks.design_arena.score" in by_id


def test_representative_path_uses_completion_chronology_not_insertion_order(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    _add_out_of_order_saved_scrapes(database_path)

    by_id = {aspect.id: aspect for aspect in _catalog(database_path)}

    assert by_id["example-provider:input_price"].field_name == "pricing.input"


def test_sampled_json_type_uses_completion_chronology_not_insertion_order(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    _add_out_of_order_saved_scrapes(database_path)

    by_id = {aspect.id: aspect for aspect in _catalog(database_path)}

    assert by_id["example-provider:path:chronology_probe"].kind == "numeric"


def test_catalog_retains_same_label_price_at_a_distinct_path(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)
    _add_out_of_order_saved_scrapes(database_path)

    by_id = {aspect.id: aspect for aspect in _catalog(database_path)}
    canonical = by_id["example-provider:input_price"]
    discovered = by_id["example-provider:path:pricing.prompt"]

    assert canonical.field_name == "pricing.input"
    assert discovered.label == canonical.label
    assert discovered.kind == "price"
    assert discovered.unit == "/1M tokens"
    assert discovered.multiplier == 1_000_000
    assert discovered.divisor == 1


def test_catalog_classifies_benchmarks_lists_and_token_columns(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)

    catalog = _catalog(database_path)
    by_id = {aspect.id: aspect for aspect in catalog}

    benchmark = by_id["example-provider:path:benchmarks.design_arena.score"]
    assert benchmark.squelched is True
    assert benchmark.category == "Benchmarks"
    assert benchmark.kind == "numeric"

    parameters = by_id["example-provider:path:supported_parameters"]
    assert parameters.kind == "list"
    assert parameters.category == "Parameters"

    context = by_id["example-provider:context_window"]
    assert context.kind == "count"
    assert context.unit == "tokens"
    assert all(
        aspect.unit != "/unit unknown" for aspect in catalog if aspect.kind != "price"
    )


def test_catalog_skips_unsafe_paths_and_object_leaves(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)
    with sqlite3.connect(database_path) as connection:
        for field_name in ("pricing.$unsafe", "benchmarks.design_arena"):
            connection.execute(
                """INSERT INTO field_changes (
                       provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                       change_kind, field_name, old_value_json, new_value_json, detected_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "example-provider",
                    facts.scrape_ids[-2],
                    facts.scrape_ids[-1],
                    facts.model_ids[0],
                    "changed",
                    field_name,
                    None,
                    None,
                    "2026-08-15T12:00:00+00:00",
                ),
            )

    ids = {aspect.id for aspect in _catalog(database_path)}
    assert "example-provider:path:pricing.$unsafe" not in ids
    assert "example-provider:path:benchmarks.design_arena" not in ids


def test_catalog_order_and_json_are_deterministic(tmp_path: Path) -> None:
    database_path = tmp_path / "fixture.db"
    build_fixture_db(database_path)

    first = _catalog(database_path)
    second = _catalog(database_path)

    assert first == second
    assert tuple(aspect.to_json() for aspect in first) == tuple(
        aspect.to_json() for aspect in second
    )
    category_rank = {
        category: rank
        for rank, category in enumerate(
            (
                "Pricing",
                "Context & Limits",
                "Capabilities",
                "Parameters",
                "Benchmarks",
                "Other",
            )
        )
    }
    assert [category_rank[aspect.category] for aspect in first] == sorted(
        category_rank[aspect.category] for aspect in first
    )
    ids = [aspect.id for aspect in first]
    assert ids.index("example-provider:input_price") < ids.index(
        "example-provider:output_price"
    )
