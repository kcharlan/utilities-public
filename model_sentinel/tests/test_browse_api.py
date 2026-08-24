from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date
from types import SimpleNamespace

import pytest

from model_sentinel.browse import api
from model_sentinel.browse import queries
from model_sentinel.browse.aspects import Aspect, build_aspect_catalog
from model_sentinel.browse.readonly import open_readonly
from model_sentinel.models import FieldChange, ModelDelta
from model_sentinel.provider_profiles import profiles_for, resolve_profile
from model_sentinel.reporting import DEFAULT_REPORT_SHOW_FIELDS, DEFAULT_REPORT_SQUELCH_FIELDS
from model_sentinel.storage import Store, recent_change_rows
from tests.browse_fixtures import EXAMPLE_PROVIDER, OTHER_PROVIDER, _save_scrape, build_fixture_db


def _settings():
    return SimpleNamespace(
        report_detail="default",
        report_show_fields=DEFAULT_REPORT_SHOW_FIELDS,
        report_squelch_fields=DEFAULT_REPORT_SQUELCH_FIELDS,
        report_unclassified_limit=20,
    )


def _context(db, providers=(EXAMPLE_PROVIDER, OTHER_PROVIDER)):
    settings = _settings()
    db_provider_rows = tuple(queries.db_providers(db.connection()))
    profiles = profiles_for(providers)
    for row in db_provider_rows:
        profiles.setdefault(row["provider_id"], resolve_profile(row["kind"]))
    policy = api.detail_policy_from_settings(settings)
    aspects = build_aspect_catalog(db, profiles=profiles, policy=policy)
    return api.ApiContext(db, providers, db_provider_rows, profiles, settings, aspects)


RENDERED_KEYS = {
    "kind", "field_path", "label", "qualifier", "old_display", "new_display",
    "old_raw", "new_raw", "unit", "price_rule", "delta_display", "delta_abs",
    "pct_display", "pct_basis_zero", "direction", "semantic", "list_added", "list_removed",
}


@pytest.fixture
def browse_context(tmp_path):
    database_path = tmp_path / "fixture.db"
    facts = build_fixture_db(database_path)
    db = open_readonly(database_path)
    context = _context(db)
    yield context, facts
    db.close_all()


@pytest.mark.parametrize(
    ("params", "message"),
    (
        ({"from": "August 1"}, "from must be YYYY-MM-DD"),
        ({"from": "20260801"}, "from must be YYYY-MM-DD"),
        ({"to": "2026-02-30"}, "to must be YYYY-MM-DD"),
        ({"from": "2026-08-02", "to": "2026-08-01"}, "from cannot be later than to"),
        ({"providers": "unknown"}, "unknown provider: unknown"),
        ({"detail": "verbose"}, "detail must be one of default, all, squelched"),
    ),
)
def test_parse_common_rejects_bad_parameters(browse_context, params, message) -> None:
    context, _ = browse_context
    with pytest.raises(api.BadRequest) as raised:
        context.parse_common(params)
    assert raised.value.message == message


def test_parse_common_defaults_and_is_frozen(browse_context) -> None:
    context, _ = browse_context
    common = context.parse_common({})

    assert common.providers == (EXAMPLE_PROVIDER.provider_id, OTHER_PROVIDER.provider_id)
    assert common.since is None
    assert common.until is None
    assert common.detail == "default"
    with pytest.raises(FrozenInstanceError):
        common.detail = "all"


def test_meta_includes_configured_and_db_only_providers(tmp_path) -> None:
    path = tmp_path / "fixture.db"
    build_fixture_db(path)
    db = open_readonly(path)
    try:
        context = _context(db, (EXAMPLE_PROVIDER,))
        result = api.meta(context, {})
    finally:
        db.close_all()

    providers = {item["id"]: item for item in result["providers"]}
    assert set(result) == {
        "providers", "date_span", "scrapes", "aspects", "categories",
        "detail_default", "pin_limit", "bulk_min_models", "display_invocation",
    }
    assert all(set(provider) == {"id", "label", "kind", "enabled", "configured"} for provider in providers.values())
    assert providers[EXAMPLE_PROVIDER.provider_id]["configured"] is True
    assert providers[OTHER_PROVIDER.provider_id]["configured"] is False
    assert result["categories"] == [
        "Pricing", "Context & Limits", "Capabilities", "Parameters", "Benchmarks", "Other"
    ]
    assert result["pin_limit"] == 8
    assert result["bulk_min_models"] == 3
    assert result["display_invocation"] == "model-sentinel"


@pytest.mark.parametrize(
    "display_invocation",
    ("renamed-sentinel", "python -m model_sentinel"),
)
def test_meta_exposes_display_invocation(tmp_path, display_invocation) -> None:
    path = tmp_path / "empty.db"
    Store(path).initialize()
    db = open_readonly(path)
    try:
        context = _context(
            db,
            (EXAMPLE_PROVIDER,),
        )
        context.display_invocation = display_invocation
        result = api.meta(context, {})
    finally:
        db.close_all()

    assert result["display_invocation"] == display_invocation


def test_api_context_uses_explicit_prebuilt_dependencies(browse_context) -> None:
    context, _ = browse_context

    assert isinstance(context.db_providers, tuple)
    assert set(context.profiles) == {row["provider_id"] for row in context.db_providers}
    assert isinstance(context.aspects, tuple)


def test_activity_and_heatmap_use_fixture_facts(browse_context) -> None:
    context, facts = browse_context
    result = api.activity(context, {"providers": EXAMPLE_PROVIDER.provider_id})
    assert set(result) == {
        "total", "page", "page_size", "entries", "rollups", "rollups_by_date",
    }
    assert set(result["rollups"]) == {"squelched", "non_squelched", "noop"}
    assert result["rollups"] == {
        "squelched": [["benchmarks.design_arena.score", 5]],
        "non_squelched": [],
        "noop": [],
    }
    assert result["rollups_by_date"] == {
        day.isoformat(): {
            "squelched": [["benchmarks.design_arena.score", 1]],
            "non_squelched": [],
            "noop": [],
        }
        for day in facts.scrape_dates[1:]
    }
    bulk = next(entry for entry in result["entries"] if entry["kind"] == "bulk")
    assert result["total"] == 9
    assert [entry["kind"] for entry in result["entries"]].count("bulk") == 1
    assert [entry["kind"] for entry in result["entries"]].count("added") == 1
    assert [entry["kind"] for entry in result["entries"]].count("removed") == 1
    assert next(entry for entry in result["entries"] if entry["kind"] == "added")["model_id"] == facts.added_model
    assert next(entry for entry in result["entries"] if entry["kind"] == "removed")["model_id"] == facts.removed_model
    assert tuple(model["model_id"] for model in bulk["bulk_models"]) == facts.bulk_list_models
    assert len(bulk["changes"]) == 1
    assert len(bulk["change_ids"]) == 4
    assert len(set(bulk["change_ids"])) == 4
    bulk_details = [
        api.change(context, {"change_id": str(change_id)})
        for change_id in bulk["change_ids"]
    ]
    assert [detail["field"] for detail in bulk_details].count("supported_parameters") == 3
    assert [detail["field"] for detail in bulk_details].count("benchmarks.design_arena.score") == 1
    assert {detail["model_id"] for detail in bulk_details} == set(facts.bulk_list_models)
    assert len(bulk["change_ids_by_change"]) == 1
    assert len(bulk["change_ids_by_change"][0]) == len(facts.bulk_list_models)
    assert {
        api.change(context, {"change_id": str(change_id)})["field"]
        for change_id in bulk["change_ids_by_change"][0]
    } == {"supported_parameters"}
    assert set(bulk) == {
        "date", "provider_id", "model_id", "display_name", "kind", "changes",
        "hidden", "change_ids", "change_ids_by_change", "bulk_models",
    }
    assert set(bulk["hidden"]) == {"squelched", "unclassified", "noop"}
    assert any(entry["model_id"] == facts.price_step[0] for entry in result["entries"])
    assert result["total"] == len(result["entries"])
    source_ids = {
        row["change_id"]
        for row in recent_change_rows(
            context.db.connection(),
            provider_id=EXAMPLE_PROVIDER.provider_id,
            since=None,
            until=None,
        )
    }
    response_ids = [change_id for entry in result["entries"] for change_id in entry["change_ids"]]
    assert set(response_ids) == source_ids
    assert len(response_ids) == len(source_ids)
    for entry in result["entries"]:
        if entry["kind"] not in {"changed", "bulk"}:
            assert entry["change_ids_by_change"] == []
            continue
        for index, change in enumerate(entry["changes"]):
            assert entry["change_ids_by_change"][index]
            detail = api.change(
                context,
                {"change_id": str(entry["change_ids_by_change"][index][0])},
            )
            assert detail["field"] == change["field_path"]
    squelched_only = next(
        entry for entry in result["entries"]
        if entry["kind"] == "changed" and entry["hidden"]["squelched"] and not entry["changes"]
    )
    assert len(squelched_only["change_ids"]) == squelched_only["hidden"]["squelched"]

    heatmap = api.heatmap(context, {"providers": EXAMPLE_PROVIDER.provider_id})
    assert heatmap == [
        {"date": "2026-08-11", "changed": 0, "added": 0, "removed": 0, "squelched": 1},
        {"date": "2026-08-12", "changed": 1, "added": 0, "removed": 0, "squelched": 1},
        {"date": "2026-08-13", "changed": 1, "added": 1, "removed": 0, "squelched": 1},
        {"date": "2026-08-14", "changed": 1, "added": 0, "removed": 1, "squelched": 1},
        {"date": "2026-08-15", "changed": 3, "added": 0, "removed": 0, "squelched": 1},
    ]
    assert all(set(day) == {"date", "changed", "added", "removed", "squelched"} for day in heatmap)


def test_activity_associates_expanded_children_with_raw_origin_ids(tmp_path) -> None:
    path = tmp_path / "fixture.db"
    facts = build_fixture_db(path)
    model_id = facts.benchmark_churn_model
    store = Store(path)
    store.record_field_changes(
        provider_id=EXAMPLE_PROVIDER.provider_id,
        from_scrape_id=facts.scrape_ids[-2],
        to_scrape_id=facts.scrape_ids[-1],
        deltas=(
            ModelDelta(
                "changed",
                model_id,
                "Synthetic Test Model A",
                (
                    FieldChange("context_length", 128_000, 256_000),
                    FieldChange(
                        "default_parameters",
                        None,
                        {"alpha": {"leaf": 1}, "beta": 2, "gamma": 3},
                    ),
                    FieldChange(
                        "default_parameters.alpha", None, {"leaf": 4},
                    ),
                    FieldChange(
                        "default_parameters.alpha", None, {"leaf": 5},
                    ),
                    FieldChange("status", "active", "paused"),
                ),
            ),
        ),
        detected_at="2026-08-15T12:30:00+00:00",
    )
    db = open_readonly(path)
    try:
        context = _context(db)
        result = api.activity(
            context,
            {
                "providers": EXAMPLE_PROVIDER.provider_id,
                "from": "2026-08-15",
                "to": "2026-08-15",
                "models": model_id,
                "detail": "all",
            },
        )
        entry = next(
            item
            for item in result["entries"]
            if any(
                change["field_path"] == "default_parameters.beta"
                for change in item["changes"]
            )
        )
        raw_details = {
            change_id: api.change(context, {"change_id": str(change_id)})
            for change_id in entry["change_ids"]
        }
        source_ids = {
            row["change_id"]
            for row in recent_change_rows(
                context.db.connection(),
                provider_id=EXAMPLE_PROVIDER.provider_id,
                since=date(2026, 8, 15),
                until=date(2026, 8, 15),
            )
            if row["provider_model_id"] == model_id
        }
    finally:
        db.close_all()

    assert len(entry["change_ids_by_change"]) == len(entry["changes"])
    by_path = {}
    for change, associated in zip(
        entry["changes"], entry["change_ids_by_change"], strict=True
    ):
        by_path.setdefault(change["field_path"], []).append(associated)

    alpha_rows = [
        (change, associated)
        for change, associated in zip(
            entry["changes"], entry["change_ids_by_change"], strict=True
        )
        if change["field_path"] == "default_parameters.alpha.leaf"
    ]
    assert {
        (change["new_display"], raw_details[associated[0]]["field"])
        for change, associated in alpha_rows
    } == {
        ("1", "default_parameters"),
        ("4", "default_parameters.alpha"),
        ("5", "default_parameters.alpha"),
    }
    for change, associated in alpha_rows:
        assert len(associated) == 1
        evidence = raw_details[associated[0]]
        if evidence["field"] == "default_parameters":
            assert evidence["new_value"]["alpha"]["leaf"] == int(
                change["new_display"]
            )
        else:
            assert evidence["new_value"]["leaf"] == int(change["new_display"])
    parent_origin = None
    for child in ("default_parameters.beta", "default_parameters.gamma"):
        associated = by_path[child][0]
        assert len(associated) == 1
        assert raw_details[associated[0]]["field"] == "default_parameters"
        parent_origin = parent_origin or associated[0]
        assert associated[0] == parent_origin
    for exact in ("context_length", "status"):
        associated = by_path[exact][0]
        assert len(associated) == 1
        assert raw_details[associated[0]]["field"] == exact

    assert len(entry["change_ids"]) == len(set(entry["change_ids"]))
    assert set(entry["change_ids"]) == source_ids


def test_activity_associates_same_day_exact_transitions_by_value(tmp_path) -> None:
    path = tmp_path / "fixture.db"
    facts = build_fixture_db(path)
    model_id = facts.price_step[0]
    Store(path).record_field_changes(
        provider_id=EXAMPLE_PROVIDER.provider_id,
        from_scrape_id=facts.scrape_ids[1],
        to_scrape_id=facts.scrape_ids[2],
        deltas=(
            ModelDelta(
                "changed",
                model_id,
                "Synthetic Test Model A",
                (
                    FieldChange("pricing.prompt", 0.0000035, 0.000004),
                ),
            ),
        ),
        detected_at="2026-08-12T12:30:00+00:00",
    )
    db = open_readonly(path)
    try:
        context = _context(db)
        result = api.activity(
            context,
            {
                "providers": EXAMPLE_PROVIDER.provider_id,
                "from": "2026-08-12",
                "to": "2026-08-12",
                "models": model_id,
                "detail": "all",
            },
        )
        entry = next(
            item
            for item in result["entries"]
            if sum(
                change["field_path"] == "pricing.prompt"
                for change in item["changes"]
            ) == 2
        )
        price_rows = [
            (change, associated)
            for change, associated in zip(
                entry["changes"], entry["change_ids_by_change"], strict=True
            )
            if change["field_path"] == "pricing.prompt"
        ]
        evidence = [
            api.change(context, {"change_id": str(associated[0])})
            for _, associated in price_rows
        ]
    finally:
        db.close_all()

    assert [
        (change["old_display"], change["new_display"])
        for change, _ in price_rows
    ] == [("$2.00", "$3.50"), ("$3.50", "$4.00")]
    assert [
        (detail["rendered"]["old_display"], detail["rendered"]["new_display"])
        for detail in evidence
    ] == [("$2.00", "$3.50"), ("$3.50", "$4.00")]
    assert len({associated[0] for _, associated in price_rows}) == 2


def test_activity_pages_more_than_five_hundred_stable_entries(tmp_path) -> None:
    path = tmp_path / "fixture.db"
    facts = build_fixture_db(path)
    Store(path).record_field_changes(
        provider_id=EXAMPLE_PROVIDER.provider_id,
        from_scrape_id=facts.scrape_ids[-2],
        to_scrape_id=facts.scrape_ids[-1],
        deltas=tuple(
            ModelDelta(
                "changed",
                f"fake-org/paged-model-{index:03d}",
                f"Synthetic Paged Model {index:03d}",
                (FieldChange("status", "queued", "ready"),),
            )
            for index in range(501)
        ),
        detected_at="2026-08-19T12:00:00+00:00",
    )
    db = open_readonly(path)
    try:
        context = _context(db)
        common = {
            "providers": EXAMPLE_PROVIDER.provider_id,
            "from": "2026-08-19",
            "to": "2026-08-19",
            "page_size": "500",
        }
        first = api.activity(context, {**common, "page": "1"})
        second = api.activity(context, {**common, "page": "2"})
    finally:
        db.close_all()

    assert first["total"] == second["total"] == 501
    assert len(first["entries"]) == 500
    assert len(second["entries"]) == 1
    first_ids = {
        change_id
        for entry in first["entries"]
        for change_id in entry["change_ids"]
    }
    second_ids = {
        change_id
        for entry in second["entries"]
        for change_id in entry["change_ids"]
    }
    assert first_ids.isdisjoint(second_ids)
    assert len(first_ids | second_ids) == 501


@pytest.mark.parametrize(
    ("value", "relative", "expected"),
    (
        ([{"score": 7}], "[0].score", 7),
        (
            [
                {"tier": "small", "price": 2},
                {"tier": "large", "price": 4},
            ],
            "[tier=large].price",
            4,
        ),
        (
            {"primary": {"tier": "large", "price": 5}},
            "[tier=large].price",
            5,
        ),
        ({"known": 1}, ".missing", None),
    ),
)
def test_structural_provenance_extracts_supported_relative_paths(
    value, relative, expected
) -> None:
    assert api._extract_relative(value, relative) == expected


def test_heatmap_classifies_each_distinct_field_once(browse_context, monkeypatch) -> None:
    context, _ = browse_context
    calls = []
    real = api.visibility_of

    def counted(field_name, policy):
        calls.append(field_name)
        return real(field_name, policy)

    monkeypatch.setattr(api, "visibility_of", counted)
    rows = queries.change_counts_by_date(
        context.db.connection(), provider_ids=(EXAMPLE_PROVIDER.provider_id,), since=None, until=None
    )

    api.heatmap(context, {"providers": EXAMPLE_PROVIDER.provider_id})

    assert set(calls) == {row["field_name"] for row in rows}
    assert len(calls) == len(set(calls))


def test_activity_category_filter_keeps_matching_hidden_rows_and_ids(browse_context) -> None:
    context, _ = browse_context

    result = api.activity(
        context,
        {"providers": EXAMPLE_PROVIDER.provider_id, "categories": "Benchmarks"},
    )

    assert result["entries"]
    assert all(not entry["changes"] for entry in result["entries"])
    assert all(entry["hidden"]["squelched"] > 0 for entry in result["entries"])
    for entry in result["entries"]:
        assert entry["change_ids"]
        assert all(
            api.change(context, {"change_id": str(change_id)})["field"].startswith("benchmarks.")
            for change_id in entry["change_ids"]
        )


def test_activity_filters_rollups_after_planning(browse_context) -> None:
    context, facts = browse_context
    empty_rollups = {"squelched": [], "non_squelched": [], "noop": []}

    added_only = api.activity(
        context,
        {"providers": EXAMPLE_PROVIDER.provider_id, "models": facts.added_model},
    )
    context_only = api.activity(
        context,
        {"providers": EXAMPLE_PROVIDER.provider_id, "categories": "Context & Limits"},
    )
    added_kind = api.activity(
        context,
        {"providers": EXAMPLE_PROVIDER.provider_id, "kinds": "added"},
    )
    model_changes = api.activity(
        context,
        {
            "providers": EXAMPLE_PROVIDER.provider_id,
            "models": facts.benchmark_churn_model,
            "kinds": "changed",
        },
    )

    assert added_only["rollups"] == empty_rollups
    assert context_only["rollups"] == empty_rollups
    assert added_kind["rollups"] == empty_rollups
    assert model_changes["rollups"] == {
        "squelched": [["benchmarks.design_arena.score", 5]],
        "non_squelched": [],
        "noop": [],
    }


def test_series_union_axis_scaling_and_events(browse_context) -> None:
    context, facts = browse_context
    model = facts.price_step[0]
    pins = f"{EXAMPLE_PROVIDER.provider_id}/{model},{OTHER_PROVIDER.provider_id}/fake-org/other-test-model"
    aspects = (
        f"{EXAMPLE_PROVIDER.provider_id}:input_price,"
        f"{EXAMPLE_PROVIDER.provider_id}:path:pricing.prompt"
    )
    result = api.series(context, {"models": pins, "aspects": aspects})
    assert set(result) == {"axis", "series"}
    assert all(set(point) == {"scrape_id", "provider_id", "date", "completed_at", "t"} for point in result["axis"])
    assert all(
        set(item) == {"model", "aspect", "provider_id", "kind", "unit", "values", "list_hash", "members"}
        for item in result["series"]
    )
    assert {point["provider_id"] for point in result["axis"]} == set(facts.provider_ids)
    canonical, raw_path = result["series"]
    assert canonical["model"] == f"{EXAMPLE_PROVIDER.provider_id}/{model}"
    assert canonical["values"] == raw_path["values"]
    assert any(value is None for value in canonical["values"])
    assert any(value == facts.price_step[-2] for value in canonical["values"])

    list_result = api.series(
        context,
        {
            "models": f"{EXAMPLE_PROVIDER.provider_id}/{facts.bulk_list_models[0]}",
            "aspects": f"{EXAMPLE_PROVIDER.provider_id}:path:supported_parameters",
        },
    )
    assert any(value == 2 for value in list_result["series"][0]["values"])
    assert any(value_hash is not None for value_hash in list_result["series"][0]["list_hash"])
    list_series = list_result["series"][0]
    observed_members = [members for members in list_series["members"] if members is not None]
    assert observed_members
    assert all(isinstance(members, list) for members in observed_members)
    assert any("tools" in members for members in observed_members)
    assert [len(members) if members is not None else None for members in list_series["members"]] == list_series["values"]
    assert all(item["members"] == [None] * len(result["axis"]) for item in result["series"])

    events = api.events(context, {"models": f"{EXAMPLE_PROVIDER.provider_id}/{model}"})
    assert events
    assert set(events[0]) == {
        "change_id", "date", "model", "kind", "field", "semantic", "direction", "squelched"
    }
    assert events[0]["model"] == f"{EXAMPLE_PROVIDER.provider_id}/{model}"


def test_catalog_raw_price_diff_and_change_lookup(browse_context) -> None:
    context, facts = browse_context
    model, old_scrape, new_scrape, *_ = facts.price_step
    aspect = f"{EXAMPLE_PROVIDER.provider_id}:input_price"
    reasoning_aspect = f"{EXAMPLE_PROVIDER.provider_id}:path:reasoning"
    canonical_reasoning = f"{EXAMPLE_PROVIDER.provider_id}:reasoning_supported"
    result = api.catalog(
        context,
        {
            "provider": EXAMPLE_PROVIDER.provider_id,
            "as_of": str(new_scrape),
            "compare": str(old_scrape),
            "columns": f"{aspect},{reasoning_aspect},{canonical_reasoning}",
        },
    )
    row = next(row for row in result["rows"] if row["model_id"] == model)
    assert set(result) == {"as_of", "compare", "total", "rows"}
    assert set(row) == {"model_id", "display_name", "presence", "cells"}
    cell = row["cells"][aspect]
    assert set(cell) == {"value", "display", "unit", "old_value", "old_display", "change"}
    assert cell["old_display"] == "$2.00"
    assert cell["display"] == "$3.50"
    assert cell["change"]["old_display"] == "$2.00"
    assert cell["change"]["new_display"] == "$3.50"
    unchanged = next(
        candidate for candidate in result["rows"]
        if candidate["presence"] == "present" and candidate["model_id"] != model
    )
    assert unchanged["cells"][aspect]["old_display"] == "$2.00"
    assert unchanged["cells"][aspect]["display"] == "$2.00"
    assert unchanged["cells"][reasoning_aspect]["old_display"] == "off"
    assert unchanged["cells"][reasoning_aspect]["display"] == "off"
    assert unchanged["cells"][canonical_reasoning]["old_display"] == "off"
    assert unchanged["cells"][canonical_reasoning]["display"] == "off"

    price_entry = next(
        entry
        for entry in api.activity(context, {"providers": EXAMPLE_PROVIDER.provider_id})["entries"]
        if entry.get("model_id") == model
        and any(change["field_path"] == "pricing.prompt" for change in entry["changes"])
    )
    detail = next(
        candidate
        for change_id in price_entry["change_ids"]
        if (candidate := api.change(context, {"change_id": str(change_id)}))["field"] == "pricing.prompt"
    )
    assert set(detail) == {
        "change_id", "provider_id", "model_id", "field", "kind", "old_value",
        "new_value", "detected_at", "from_scrape", "to_scrape", "rendered",
    }
    assert set(detail["rendered"]) == RENDERED_KEYS
    assert set(detail["from_scrape"]) == {"scrape_id", "date", "completed_at", "status"}
    assert set(detail["to_scrape"]) == {"scrape_id", "date", "completed_at", "status"}
    assert detail["model_id"] == model
    assert detail["rendered"]["field_path"] == detail["field"]
    assert cell["change"] == detail["rendered"]
    json.dumps(detail)
    with pytest.raises(api.NotFound):
        api.change(context, {"change_id": "999999"})

    added_catalog = api.catalog(
        context,
        {
            "provider": EXAMPLE_PROVIDER.provider_id,
            "as_of": str(facts.added_at_scrape),
            "compare": str(facts.added_at_scrape - 1),
            "columns": aspect,
        },
    )
    assert next(row for row in added_catalog["rows"] if row["model_id"] == facts.added_model)["presence"] == "added"
    removed_catalog = api.catalog(
        context,
        {
            "provider": EXAMPLE_PROVIDER.provider_id,
            "as_of": str(facts.removed_at_scrape),
            "compare": str(facts.removed_at_scrape - 1),
            "columns": aspect,
        },
    )
    assert next(row for row in removed_catalog["rows"] if row["model_id"] == facts.removed_model)["presence"] == "removed"
    json.dumps(result)


def test_catalog_price_resolver_preserves_present_zero_values(tmp_path) -> None:
    path = tmp_path / "fixture.db"
    model_id = "fake-org/zero-price-model"
    absent_model = "fake-org/absent-price-model"
    store = Store(path)
    store.initialize()
    store.upsert_provider_configs((EXAMPLE_PROVIDER,), updated_at="2026-08-20T10:00:00+00:00")
    scrape_ids = []
    previous_id = None
    previous_models = []
    for index, raw_price in enumerate((0.000002, 0, 0.0000035), start=1):
        raw_models = [
            {
                "id": model_id,
                "name": "Synthetic Zero Price Model",
                "pricing": {"input": None, "prompt": raw_price},
            },
            {
                "id": absent_model,
                "name": "Synthetic Absent Price Model",
                "pricing": {"input": None, "prompt": None},
            },
        ]
        scrape_id, previous_models = _save_scrape(
            store,
            EXAMPLE_PROVIDER,
            completed_at=f"2026-08-{20 + index:02d}T12:00:00+00:00",
            raw_models=raw_models,
            previous_id=previous_id,
            previous_models=previous_models,
        )
        scrape_ids.append(scrape_id)
        previous_id = scrape_id
    with sqlite3.connect(path) as connection:
        stored_zero = connection.execute(
            "SELECT input_price FROM snapshot_models WHERE scrape_id = ? AND provider_model_id = ?",
            (scrape_ids[1], model_id),
        ).fetchone()[0]
        change_ids = [
            row[0]
            for row in connection.execute(
                """SELECT change_id FROM field_changes
                   WHERE provider_model_id = ? AND field_name = 'pricing.prompt'
                   ORDER BY change_id""",
                (model_id,),
            )
        ]
    assert stored_zero is None
    db = open_readonly(path)
    try:
        context = _context(db, (EXAMPLE_PROVIDER,))
        aspect_id = f"{EXAMPLE_PROVIDER.provider_id}:input_price"
        rendered = []
        sorted_models = []
        absent_values = []
        descending_zero_models = None
        for from_scrape, to_scrape, change_id in zip(scrape_ids, scrape_ids[1:], change_ids):
            catalog_result = api.catalog(
                context,
                {
                    "provider": EXAMPLE_PROVIDER.provider_id,
                    "as_of": str(to_scrape),
                    "compare": str(from_scrape),
                    "columns": aspect_id,
                    "sort": aspect_id,
                },
            )
            cell = next(
                row["cells"][aspect_id]
                for row in catalog_result["rows"]
                if row["model_id"] == model_id
            )
            change_result = api.change(context, {"change_id": str(change_id)})
            rendered.append((cell, change_result["rendered"]))
            sorted_models.append([row["model_id"] for row in catalog_result["rows"]])
            absent_values.append(next(
                row["cells"][aspect_id]["value"]
                for row in catalog_result["rows"]
                if row["model_id"] == absent_model
            ))
            if to_scrape == scrape_ids[1]:
                descending_zero_models = [
                    row["model_id"]
                    for row in api.catalog(
                        context,
                        {
                            "provider": EXAMPLE_PROVIDER.provider_id,
                            "as_of": str(to_scrape),
                            "columns": aspect_id,
                            "sort": aspect_id,
                            "dir": "desc",
                        },
                    )["rows"]
                ]
    finally:
        db.close_all()

    assert rendered[0][0]["old_display"] == "$2.00"
    assert rendered[0][0]["display"] == "free"
    assert rendered[0][0]["old_value"] == 2
    assert rendered[0][0]["value"] == 0
    assert rendered[1][0]["old_display"] == "free"
    assert rendered[1][0]["display"] == "$3.50"
    assert rendered[1][0]["old_value"] == 0
    assert rendered[1][0]["value"] == 3.5
    assert all(cell["change"] == change_render for cell, change_render in rendered)
    assert all(models[-1] == absent_model for models in sorted_models)
    assert descending_zero_models == [model_id, absent_model]
    assert absent_values == [None, None]


def test_catalog_price_resolver_keeps_later_truthy_candidate(browse_context) -> None:
    context, _ = browse_context
    profile = context.profiles[EXAMPLE_PROVIDER.provider_id]
    raw = {"pricing": {"input": 0, "prompt": 0.000002}}

    assert api._catalog_profile_value(raw, profile, "input_price") == (0.000002, "pricing.prompt")

    earlier_none_later_zero = {"pricing": {"input": None, "prompt": 0}}
    assert api._catalog_profile_value(
        earlier_none_later_zero, profile, "input_price"
    ) == (0, "pricing.prompt")
    assert api._catalog_profile_value(
        {"pricing": {"input": False, "prompt": None}}, profile, "input_price"
    ) == (None, None)


def test_change_presence_records_have_rendered_coverage(browse_context) -> None:
    context, facts = browse_context
    activity = api.activity(context, {"providers": EXAMPLE_PROVIDER.provider_id})
    for kind, model_id, direction in (
        ("added", facts.added_model, "added"),
        ("removed", facts.removed_model, "removed"),
    ):
        entry = next(item for item in activity["entries"] if item["kind"] == kind)
        result = api.change(context, {"change_id": str(entry["change_ids"][0])})
        assert result["model_id"] == model_id
        assert result["rendered"]["semantic"] == "coverage"
        assert result["rendered"]["direction"] == direction
        assert result["rendered"]["field_path"] == "model_presence"
        assert set(result["rendered"]) == RENDERED_KEYS
        json.dumps(result)


def test_change_does_not_mutate_query_result(browse_context, monkeypatch) -> None:
    context, _ = browse_context
    source = {
        "change_id": 999,
        "provider_id": EXAMPLE_PROVIDER.provider_id,
        "provider_model_id": "fake-org/synthetic-model",
        "change_kind": "field_changed",
        "field_name": "status",
        "old_value": "old",
        "new_value": "new",
        "detected_at": "2026-08-20T12:00:00+00:00",
        "from_scrape": {
            "scrape_id": 1,
            "date": date(2026, 8, 19),
            "completed_at": "2026-08-19T12:00:00+00:00",
            "status": "success",
        },
        "to_scrape": {
            "scrape_id": 2,
            "date": date(2026, 8, 20),
            "completed_at": "2026-08-20T12:00:00+00:00",
            "status": "success",
        },
    }
    before = deepcopy(source)
    monkeypatch.setattr(api.queries, "change_by_id", lambda connection, change_id: source)

    result = api.change(context, {"change_id": "999"})

    assert source == before
    assert result["field"] == "status"


def test_endpoint_validation_and_models(browse_context) -> None:
    context, facts = browse_context
    pin = f"{EXAMPLE_PROVIDER.provider_id}/{facts.model_ids[0]}"
    aspect = f"{EXAMPLE_PROVIDER.provider_id}:input_price"
    bad_calls = (
        (api.activity, {"page": "zero"}, "page must be an integer"),
        (api.activity, {"page": "0"}, "page must be at least 1"),
        (api.activity, {"page_size": "many"}, "page_size must be an integer"),
        (api.activity, {"page_size": "501"}, "page_size must be between 1 and 500"),
        (api.activity, {"categories": "Unknown"}, "unknown category: Unknown"),
        (api.activity, {"kinds": "updated"}, "unknown kind: updated"),
        (api.series, {"aspects": aspect}, "models is required"),
        (api.series, {"models": pin}, "aspects is required"),
        (api.series, {"models": ",".join([pin] * 9), "aspects": aspect}, "at most 8 models"),
        (api.series, {"models": pin, "aspects": "unknown"}, "unknown aspect: unknown"),
        (
            api.series,
            {"models": pin, "aspects": f"{OTHER_PROVIDER.provider_id}:input_price"},
            "is incompatible with selected models",
        ),
        (api.events, {}, "models is required"),
        (api.events, {"models": ",".join([pin] * 9)}, "at most 8 models"),
        (api.events, {"models": "bad/model"}, "unknown provider: bad"),
        (api.events, {"models": f"{EXAMPLE_PROVIDER.provider_id}/fake-org/missing"}, "unknown model"),
        (api.catalog, {}, "provider is required"),
        (api.catalog, {"provider": "unknown", "as_of": "1"}, "unknown provider: unknown"),
        (api.catalog, {"provider": EXAMPLE_PROVIDER.provider_id}, "as_of is required"),
        (api.catalog, {"provider": EXAMPLE_PROVIDER.provider_id, "as_of": "first"}, "as_of must be an integer"),
        (
            api.catalog,
            {"provider": EXAMPLE_PROVIDER.provider_id, "as_of": str(facts.scrape_ids[0]), "columns": "unknown"},
            "unknown aspect: unknown",
        ),
        (
            api.catalog,
            {"provider": EXAMPLE_PROVIDER.provider_id, "as_of": str(facts.scrape_ids[0]), "dir": "sideways"},
            "dir must be asc or desc",
        ),
        (
            api.catalog,
            {"provider": EXAMPLE_PROVIDER.provider_id, "as_of": str(facts.scrape_ids[0]), "sort": "unknown"},
            "unknown sort column: unknown",
        ),
        (api.change, {}, "change_id is required"),
        (api.change, {"change_id": "first"}, "change_id must be an integer"),
        (api.models, {"limit": "many"}, "limit must be an integer"),
        (api.models, {"limit": "0"}, "limit must be between 1 and 500"),
    )
    for endpoint, params, message in bad_calls:
        with pytest.raises(api.BadRequest) as raised:
            endpoint(context, params)
        assert message in raised.value.message

    with pytest.raises(api.BadRequest) as chronology:
        api.catalog(
            context,
            {
                "provider": EXAMPLE_PROVIDER.provider_id,
                "as_of": str(facts.scrape_ids[1]),
                "compare": str(facts.scrape_ids[2]),
            },
        )
    assert chronology.value.message == "compare must be earlier than as_of"

    rows = api.models(context, {"q": "test-model-a"})
    assert set(rows[0]) == {"provider_id", "model_id", "display_name", "last_seen"}
    assert rows[0]["model_id"] == facts.model_ids[0]


def test_series_allows_twelve_aspects_and_rejects_thirteen(browse_context) -> None:
    context, facts = browse_context
    pin = f"{EXAMPLE_PROVIDER.provider_id}/{facts.model_ids[0]}"
    aspect_ids = [aspect.id for aspect in context.aspects if aspect.provider_id == EXAMPLE_PROVIDER.provider_id]

    result = api.series(context, {"models": pin, "aspects": ",".join(aspect_ids[:12])})

    assert len(result["series"]) == 12
    with pytest.raises(api.BadRequest) as raised:
        api.series(context, {"models": pin, "aspects": ",".join(aspect_ids[:13])})
    assert raised.value.message == "at most 12 aspects may be selected"


def test_list_series_hash_canonicalizes_mixed_json_members(browse_context) -> None:
    context, _ = browse_context
    aspect = next(aspect for aspect in context.aspects if aspect.kind == "list")
    first = [{"b": 2, "a": 1}, 1, "1", True, None, {"nested": {"y": 2, "x": 1}}]
    reordered = [None, True, "1", 1, {"a": 1, "b": 2}, {"nested": {"x": 1, "y": 2}}]
    changed = [None, True, "1", 1, {"a": 1, "b": 3}, {"nested": {"x": 1, "y": 2}}]

    first_length, first_hash = api._series_value(aspect, first)
    reordered_length, reordered_hash = api._series_value(aspect, reordered)
    changed_length, changed_hash = api._series_value(aspect, changed)
    duplicate_length, duplicate_hash = api._series_value(aspect, [1, 1])
    single_length, single_hash = api._series_value(aspect, [1])

    assert first_length == reordered_length == changed_length == 6
    assert first_hash == reordered_hash
    assert changed_hash != first_hash
    assert (duplicate_length, single_length) == (2, 1)
    assert duplicate_hash != single_hash


def test_catalog_sort_totally_orders_heterogeneous_json_values(tmp_path) -> None:
    path = tmp_path / "fixture.db"
    facts = build_fixture_db(path)
    scrape_id = facts.added_at_scrape
    values = {
        facts.model_ids[0]: 2.5,
        facts.model_ids[1]: "Alpha",
        facts.model_ids[2]: True,
        facts.model_ids[3]: [2, 1],
        facts.model_ids[4]: None,
    }
    with sqlite3.connect(path) as connection:
        for model_id, value in values.items():
            raw = json.loads(connection.execute(
                "SELECT metadata_json FROM snapshot_models WHERE scrape_id = ? AND provider_model_id = ?",
                (scrape_id, model_id),
            ).fetchone()[0])
            raw["sort_value"] = value
            connection.execute(
                "UPDATE snapshot_models SET metadata_json = ? WHERE scrape_id = ? AND provider_model_id = ?",
                (json.dumps(raw), scrape_id, model_id),
            )
    db = open_readonly(path)
    try:
        context = _context(db, (EXAMPLE_PROVIDER,))
        aspect = Aspect(
            id=f"{EXAMPLE_PROVIDER.provider_id}:path:sort_value",
            provider_id=EXAMPLE_PROVIDER.provider_id,
            source="path",
            column=None,
            path="sort_value",
            field_name="sort_value",
            label="Sort value",
            qualifier=None,
            category="Other",
            kind="scalar",
            unit=None,
            multiplier=1,
            divisor=1,
            squelched=False,
        )
        context.aspects = (*context.aspects, aspect)
        base = {
            "provider": EXAMPLE_PROVIDER.provider_id,
            "as_of": str(scrape_id),
            "columns": aspect.id,
            "sort": aspect.id,
        }
        ascending = api.catalog(context, {**base, "dir": "asc"})
        descending = api.catalog(context, {**base, "dir": "desc"})
    finally:
        db.close_all()

    assert [row["model_id"] for row in ascending["rows"]] == [
        facts.model_ids[2], facts.model_ids[0], facts.model_ids[1], facts.model_ids[3], facts.model_ids[4]
    ]
    assert [row["model_id"] for row in descending["rows"]] == [
        facts.model_ids[3], facts.model_ids[1], facts.model_ids[0], facts.model_ids[2], facts.model_ids[4]
    ]
    assert ascending["rows"][3]["cells"][aspect.id]["value"] == [2, 1]
    assert api._catalog_sort_key(10**400) < api._catalog_sort_key("large")


def test_events_distinguish_same_model_id_across_providers(tmp_path) -> None:
    path = tmp_path / "fixture.db"
    facts = build_fixture_db(path)
    shared_model = facts.model_ids[0]
    with sqlite3.connect(path) as connection:
        other_scrapes = connection.execute(
            "SELECT scrape_id FROM scrapes WHERE provider_id = ? ORDER BY scrape_id",
            (OTHER_PROVIDER.provider_id,),
        ).fetchall()
        source = connection.execute(
            "SELECT * FROM snapshot_models WHERE provider_id = ? AND provider_model_id = ? LIMIT 1",
            (EXAMPLE_PROVIDER.provider_id, shared_model),
        ).fetchone()
        columns = [row[1] for row in connection.execute("PRAGMA table_info(snapshot_models)")]
        values = list(source)
        values[columns.index("scrape_id")] = other_scrapes[-1][0]
        values[columns.index("provider_id")] = OTHER_PROVIDER.provider_id
        connection.execute(
            f"INSERT INTO snapshot_models ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
        connection.execute(
            """INSERT INTO field_changes (
                   provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                   change_kind, field_name, old_value_json, new_value_json, detected_at
               ) VALUES (?, ?, ?, ?, 'field_changed', 'status', '"old"', '"new"', ?)""",
            (
                OTHER_PROVIDER.provider_id,
                other_scrapes[0][0],
                other_scrapes[-1][0],
                shared_model,
                "2026-08-18T12:20:00+00:00",
            ),
        )
    db = open_readonly(path)
    try:
        context = _context(db)
        result = api.events(
            context,
            {
                "models": (
                    f"{EXAMPLE_PROVIDER.provider_id}/{shared_model},"
                    f"{OTHER_PROVIDER.provider_id}/{shared_model}"
                )
            },
        )
    finally:
        db.close_all()

    identities = {row["model"] for row in result}
    assert f"{EXAMPLE_PROVIDER.provider_id}/{shared_model}" in identities
    assert f"{OTHER_PROVIDER.provider_id}/{shared_model}" in identities
    assert all(set(row) == {
        "change_id", "date", "model", "kind", "field", "semantic", "direction", "squelched"
    } for row in result)


def test_activity_preserves_multiple_same_day_change_ids(tmp_path) -> None:
    path = tmp_path / "fixture.db"
    facts = build_fixture_db(path)
    with sqlite3.connect(path) as connection:
        original = connection.execute(
            """SELECT provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                      change_kind, field_name, old_value_json, new_value_json, detected_at
               FROM field_changes
               WHERE provider_model_id = ? AND field_name = 'pricing.prompt'
               LIMIT 1""",
            (facts.price_step[0],),
        ).fetchone()
        connection.execute(
            """INSERT INTO field_changes (
                   provider_id, from_scrape_id, to_scrape_id, provider_model_id,
                   change_kind, field_name, old_value_json, new_value_json, detected_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            original,
        )
    db = open_readonly(path)
    try:
        context = _context(db, (EXAMPLE_PROVIDER,))
        result = api.activity(context, {"providers": EXAMPLE_PROVIDER.provider_id})
        price = next(
            entry for entry in result["entries"]
            if entry["model_id"] == facts.price_step[0]
            and any(change["field_path"] == "pricing.prompt" for change in entry["changes"])
        )
        matching = [
            change_id for change_id in price["change_ids"]
            if api.change(context, {"change_id": str(change_id)})["field"] == "pricing.prompt"
        ]
    finally:
        db.close_all()
    assert len(set(matching)) == 2


def test_endpoint_payloads_are_json_serializable(browse_context) -> None:
    context, facts = browse_context
    pin = f"{EXAMPLE_PROVIDER.provider_id}/{facts.model_ids[0]}"
    payloads = (
        api.meta(context, {}),
        api.activity(context, {}),
        api.heatmap(context, {}),
        api.series(context, {"models": pin, "aspects": f"{EXAMPLE_PROVIDER.provider_id}:input_price"}),
        api.events(context, {"models": pin}),
        api.models(context, {}),
    )
    for payload in payloads:
        json.dumps(payload)


def test_empty_history_endpoint_responses(tmp_path) -> None:
    path = tmp_path / "empty.db"
    Store(path).initialize()
    db = open_readonly(path)
    try:
        context = _context(db, (EXAMPLE_PROVIDER,))
        metadata = api.meta(context, {})
        activity = api.activity(context, {})
        heatmap = api.heatmap(context, {})
        model_rows = api.models(context, {})
    finally:
        db.close_all()

    assert metadata["date_span"] is None
    assert metadata["scrapes"] == []
    assert activity == {
        "total": 0,
        "page": 1,
        "page_size": 100,
        "entries": [],
        "rollups": {"squelched": [], "non_squelched": [], "noop": []},
        "rollups_by_date": {},
    }
    assert heatmap == []
    assert model_rows == []
