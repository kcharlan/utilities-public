from __future__ import annotations

import ast
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

import model_sentinel.reporting as reporting
import model_sentinel.conditional_pricing as pricing_semantics
from model_sentinel.conditional_pricing import (
    LiveComparisonIdentity,
    PricingComparisonEvent,
    StoredComparisonIdentity,
)
from model_sentinel.models import (
    BaselineInfo,
    FieldChange,
    HistoryEvent,
    ModelDelta,
    ProviderScanResult,
)
from model_sentinel.provider_profiles import (
    GENERIC_PROFILE,
    OPENROUTER_PROFILE,
    ProviderProfile,
)
from model_sentinel.storage import StoredChangeRecord, StoredComparisonEvent


def _event(*, metadata: bool = True) -> PricingComparisonEvent:
    old = {
        "id": "synthetic/model",
        "pricing": {"prompt": "0.000002", "completion": "0.000008"},
    }
    new = {
        "id": "synthetic/model",
        "pricing": {
            "prompt": "0.000001",
            "completion": "0.000008",
            "overrides": [
                {
                    "utc_days": ["monday"],
                    "utc_start": 100,
                    "utc_end": 200,
                    "prompt": "0.000003",
                    "completion": "0.000009",
                }
            ],
        },
    }
    return PricingComparisonEvent(
        identity=LiveComparisonIdentity("openrouter", "synthetic/model", 10, 11),
        provider_id="openrouter",
        provider_model_id="synthetic/model",
        display_name="Synthetic Model",
        detected_at="2026-08-28T12:00:00+00:00",
        source_timestamp="2026-08-27T12:00:00+00:00",
        target_timestamp="2026-08-28T12:00:00+00:00",
        field_changes=(
            FieldChange("pricing.prompt", "0.000002", "0.000001"),
            FieldChange("pricing.overrides", None, new["pricing"]["overrides"]),
            FieldChange("status", "preview", "active"),
        ),
        old_model_metadata=old if metadata else None,
        new_model_metadata=new if metadata else None,
    )


def _scan_result(
    event: PricingComparisonEvent,
    profile: ProviderProfile = OPENROUTER_PROFILE,
) -> ProviderScanResult:
    return ProviderScanResult(
        provider_id=event.provider_id,
        provider_label="OpenRouter",
        status="success",
        current_count=1,
        saved=False,
        baseline=BaselineInfo(10, "2026-08-27T12:00:00+00:00"),
        baseline_message=None,
        scrape_id=11,
        added=(),
        removed=(),
        changed=(
            ModelDelta(
                "changed",
                event.provider_model_id,
                event.display_name,
                tuple(
                    FieldChange(
                        change.field_name,
                        reporting._mutable_json(change.old_value),
                        reporting._mutable_json(change.new_value),
                    )
                    for change in event.field_changes
                ),
            ),
        ),
        profile=profile,
    )


def _scan_report(
    event: PricingComparisonEvent,
    format_name: str,
    *,
    detail_mode: str = "default",
    profile: ProviderProfile = OPENROUTER_PROFILE,
) -> str:
    core = reporting.build_model_event_semantic_core(event, profile)
    return reporting.render_scan_report(
        generated_at="2026-08-28T12:00:00+00:00",
        command="scan",
        format_name=format_name,
        provider_results=[_scan_result(event, profile)],
        detail_policy=reporting.make_report_detail_policy(mode=detail_mode),
        semantic_cores={core.identity: core},
    )


def _evidence_only_event() -> PricingComparisonEvent:
    first = {
        "utc_days": ["monday"],
        "utc_start": 100,
        "utc_end": 200,
        "prompt": "0.000003",
    }
    second = {
        "utc_days": ["tuesday"],
        "utc_start": 300,
        "utc_end": 400,
        "prompt": "0.000004",
    }
    old_rules = [first, second]
    new_rules = [second, first]
    return replace(
        _event(),
        field_changes=(FieldChange("pricing.overrides", old_rules, new_rules),),
        old_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001", "overrides": old_rules},
        },
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001", "overrides": new_rules},
        },
    )


def test_semantic_core_precedes_detail_projection_and_accounts_absorbed_rows() -> None:
    core = reporting.build_model_event_semantic_core(_event(), OPENROUTER_PROFILE)

    assert core.interpretation is not None
    assert core.has_semantic_composite is True
    assert [change.field_name for change in core.remaining_field_changes] == ["status"]
    assert core.accounting.direct_price_field_count == 1
    assert core.accounting.model_bucket == "conditional"

    default = reporting.project_model_event_semantics(
        core, reporting.make_report_detail_policy(), OPENROUTER_PROFILE
    )
    all_detail = reporting.project_model_event_semantics(
        core, reporting.make_report_detail_policy(mode="all"), OPENROUTER_PROFILE
    )
    squelched = reporting.project_model_event_semantics(
        core, reporting.make_report_detail_policy(mode="squelched"), OPENROUTER_PROFILE
    )

    assert default is not all_detail
    assert default.core is all_detail.core is squelched.core is core
    assert default.accounting is all_detail.accounting is squelched.accounting
    assert default.show_conditional_panel is True
    assert all_detail.show_conditional_panel is True
    assert squelched.show_conditional_panel is False


def test_missing_side_raw_fallback_absorbs_nothing() -> None:
    core = reporting.build_model_event_semantic_core(_event(metadata=False), OPENROUTER_PROFILE)

    assert core.interpretation is not None
    assert core.interpretation.state in {"ordered-rules", "raw-fallback"}
    assert {change.field_name for change in core.remaining_field_changes} == {
        "pricing.prompt",
        "status",
    }


def test_nonconditional_event_still_has_universal_pricing_accounting() -> None:
    event = replace(
        _event(),
        field_changes=(FieldChange("pricing.prompt", "0.000002", "0.000001"),),
    )
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)

    assert core.interpretation is None
    assert core.accounting.direct_price_field_count == 1
    assert core.accounting.model_bucket == "lower"
    assert core.remaining_field_changes == event.field_changes


def test_semantic_builders_run_once_per_core_not_once_per_projection(
    monkeypatch,
) -> None:
    calls = {
        "interpreter": 0,
        "equality": 0,
        "absorption": 0,
        "interpreter_accounting": 0,
        "final_accounting": 0,
    }
    real_interpreter = reporting.interpret_conditional_pricing
    real_equality = pricing_semantics._semantic_change
    real_absorption = pricing_semantics.decide_sibling_base_price_absorption
    real_interpreter_accounting = pricing_semantics.build_model_pricing_accounting
    real_final_accounting = reporting.build_model_pricing_accounting

    def count_interpreter(*args, **kwargs):
        calls["interpreter"] += 1
        return real_interpreter(*args, **kwargs)

    def count_equality(*args, **kwargs):
        calls["equality"] += 1
        return real_equality(*args, **kwargs)

    def count_absorption(*args, **kwargs):
        calls["absorption"] += 1
        return real_absorption(*args, **kwargs)

    def count_interpreter_accounting(*args, **kwargs):
        calls["interpreter_accounting"] += 1
        return real_interpreter_accounting(*args, **kwargs)

    def count_final_accounting(*args, **kwargs):
        calls["final_accounting"] += 1
        return real_final_accounting(*args, **kwargs)

    monkeypatch.setattr(reporting, "interpret_conditional_pricing", count_interpreter)
    monkeypatch.setattr(pricing_semantics, "_semantic_change", count_equality)
    monkeypatch.setattr(
        pricing_semantics,
        "decide_sibling_base_price_absorption",
        count_absorption,
    )
    monkeypatch.setattr(
        pricing_semantics,
        "build_model_pricing_accounting",
        count_interpreter_accounting,
    )
    monkeypatch.setattr(
        reporting,
        "build_model_pricing_accounting",
        count_final_accounting,
    )

    core = reporting.build_model_event_semantic_core(_event(), OPENROUTER_PROFILE)
    for mode in ("default", "all", "squelched"):
        reporting.project_model_event_semantics(
            core,
            reporting.make_report_detail_policy(mode=mode),
            OPENROUTER_PROFILE,
        )

    assert calls == {
        "interpreter": 1,
        "equality": 1,
        "absorption": 1,
        "interpreter_accounting": 1,
        "final_accounting": 1,
    }


def test_semantic_composite_keeps_card_and_prevents_bulk_grouping() -> None:
    event = replace(
        _event(),
        field_changes=(
            _event().field_changes[0],
            _event().field_changes[1],
            FieldChange("supported_parameters", ["tools"], ["tools", "audio"]),
        ),
    )
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
    projection = reporting.project_model_event_semantics(
        core, reporting.make_report_detail_policy(), OPENROUTER_PROFILE
    )

    assert reporting._renders_anything(projection.display, core)
    assert [change.field_name for change in projection.display.visible] == [
        "supported_parameters"
    ]
    assert reporting._bulk_change_signature(projection.display, core) is None

    parent_only = replace(event, field_changes=event.field_changes[:2])
    absorbed = reporting.build_model_event_semantic_core(
        parent_only, OPENROUTER_PROFILE
    )
    absorbed_projection = reporting.project_model_event_semantics(
        absorbed, reporting.make_report_detail_policy(), OPENROUTER_PROFILE
    )
    assert absorbed_projection.display.visible == ()
    assert reporting._renders_anything(absorbed_projection.display, absorbed)


def test_evidence_only_reorder_neither_keeps_nor_promotes_card(monkeypatch) -> None:
    core = reporting.build_model_event_semantic_core(_event(), OPENROUTER_PROFILE)
    evidence = replace(
        core,
        interpretation=replace(
            core.interpretation,
            semantic_change=False,
            canonical_evidence_changed=True,
        ),
        remaining_field_changes=(
            FieldChange("supported_parameters", ["tools"], ["tools", "audio"]),
        ),
        has_semantic_composite=False,
        evidence_only=True,
    )
    visible_list = reporting._FieldDisplayPlan(
        evidence.remaining_field_changes, (), (), (), 0
    )
    empty = reporting._FieldDisplayPlan((), (), (), (), 0)

    assert reporting._renders_anything(empty, evidence) is False
    assert reporting._bulk_change_signature(visible_list, evidence) == (
        ("supported_parameters", ("audio",), ()),
    )


def test_projection_orders_only_final_pricing_rows() -> None:
    event = replace(
        _event(),
        field_changes=(
            FieldChange("status", "preview", "active"),
            FieldChange("pricing.completion", "0.1", "0.2"),
            FieldChange("pricing.prompt", "0.1", "0.2"),
        ),
    )
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
    projection = reporting.project_model_event_semantics(
        core, reporting.make_report_detail_policy(mode="all"), OPENROUTER_PROFILE
    )

    ordered = reporting._field_changes_with_pricing_order(
        projection.display.visible,
        reporting.make_report_detail_policy(mode="all"),
        OPENROUTER_PROFILE,
    )
    assert [change.field_name for change in ordered] == [
        "status",
        "pricing.prompt",
        "pricing.completion",
    ]


def _stored_schedule_event(
    *,
    from_scrape: int,
    to_scrape: int,
    old_rules,
    new_rules,
    detected_at: str,
) -> StoredComparisonEvent:
    identity = StoredComparisonIdentity(
        "openrouter", "synthetic/model", from_scrape, to_scrape
    )
    record = StoredChangeRecord(
        change_id=to_scrape,
        provider_id="openrouter",
        provider_model_id="synthetic/model",
        from_scrape_id=from_scrape,
        to_scrape_id=to_scrape,
        change_kind="field_changed",
        field_name="pricing.overrides",
        old_value=old_rules,
        new_value=new_rules,
        detected_at=detected_at,
    )
    old_metadata = {
        "id": "synthetic/model",
        "pricing": {"prompt": "0.000001", "overrides": old_rules},
    }
    new_metadata = {
        "id": "synthetic/model",
        "pricing": {"prompt": "0.000001", "overrides": new_rules},
    }
    return StoredComparisonEvent(
        identity=identity,
        provider_label="OpenRouter",
        display_name="Synthetic Model",
        detected_at=detected_at,
        from_completed_at=f"2026-08-{from_scrape:02d}T10:00:00+00:00",
        to_completed_at=f"2026-08-{to_scrape:02d}T10:00:00+00:00",
        source_rows=(record,),
        field_changes=(FieldChange("pricing.overrides", old_rules, new_rules),),
        old_model_metadata=old_metadata,
        new_model_metadata=new_metadata,
    )


def _stored_ordinary_event(
    *,
    from_scrape: int,
    to_scrape: int,
    detected_at: str,
    field_name: str,
    old_value,
    new_value,
) -> StoredComparisonEvent:
    identity = StoredComparisonIdentity(
        "openrouter", "synthetic/model", from_scrape, to_scrape
    )
    row = StoredChangeRecord(
        change_id=to_scrape,
        provider_id="openrouter",
        provider_model_id="synthetic/model",
        from_scrape_id=from_scrape,
        to_scrape_id=to_scrape,
        change_kind="field_changed",
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        detected_at=detected_at,
    )
    return StoredComparisonEvent(
        identity=identity,
        provider_label="OpenRouter",
        display_name="Synthetic Model",
        detected_at=detected_at,
        from_completed_at=detected_at,
        to_completed_at=detected_at,
        source_rows=(row,),
        field_changes=(FieldChange(field_name, old_value, new_value),),
        old_model_metadata={"id": "synthetic/model", field_name: old_value},
        new_model_metadata={"id": "synthetic/model", field_name: new_value},
    )


@pytest.mark.parametrize("format_name", ("text", "markdown"))
@pytest.mark.parametrize("detail_mode", ("default", "all", "squelched"))
def test_mixed_history_interleaves_legacy_rows_and_only_composites_conditional_edges(
    format_name: str,
    detail_mode: str,
) -> None:
    first = _stored_ordinary_event(
        from_scrape=7,
        to_scrape=8,
        detected_at="2026-08-08T08:00:00+00:00",
        field_name="status",
        old_value="preview",
        new_value="active",
    )
    rules = [
        {
            "utc_days": ["monday"],
            "utc_start": 100,
            "utc_end": 200,
            "prompt": "0.000002",
        }
    ]
    conditional = _stored_schedule_event(
        from_scrape=8,
        to_scrape=9,
        old_rules=None,
        new_rules=rules,
        detected_at="2026-08-09T09:00:00+00:00",
    )
    last = _stored_ordinary_event(
        from_scrape=9,
        to_scrape=10,
        detected_at="2026-08-10T10:00:00+00:00",
        field_name="benchmarks.synthetic_score",
        old_value=1,
        new_value=2,
    )
    stored = (first, conditional, last)
    events = tuple(
        HistoryEvent(
            row.detected_at,
            row.change_kind,
            row.field_name,
            row.old_value,
            row.new_value,
        )
        for event in stored
        for row in event.source_rows
    )
    cores = {
        event.identity: reporting.build_model_event_semantic_core(
            reporting.pricing_event_from_stored(event), OPENROUTER_PROFILE
        )
        for event in stored
    }

    report = reporting.render_history_report(
        provider_id="openrouter",
        model_id="synthetic/model",
        format_name=format_name,
        first_seen="2026-08-08T08:00:00+00:00",
        last_seen="2026-08-10T10:00:00+00:00",
        events=events,
        profile=OPENROUTER_PROFILE,
        detail_policy=reporting.make_report_detail_policy(mode=detail_mode),
        stored_events=stored,
        semantic_cores=cores,
    )

    status = "status preview -> active" if format_name == "text" else "| status | preview | active |"
    benchmark = (
        "benchmarks.synthetic_score 1 -> 2"
        if format_name == "text"
        else "| benchmarks.synthetic_score | 1 | 2 |"
    )
    assert status in report
    assert benchmark in report
    assert report.index(status) < report.index(benchmark)
    assert "Comparison detected" not in report.replace(
        "Comparison detected 2026-08-09", ""
    )
    if detail_mode == "squelched":
        assert "Comparison detected 2026-08-09" not in report
    else:
        conditional_heading = "Comparison detected 2026-08-09"
        assert conditional_heading in report
        assert report.index(status) < report.index(conditional_heading) < report.index(benchmark)


def test_stored_same_day_edges_remain_distinct_and_use_displayed_policy_side() -> None:
    one_rule = [
        {
            "utc_days": ["monday"],
            "utc_start": 100,
            "utc_end": 200,
            "prompt": "0.000002",
        }
    ]
    two_rules = [
        *one_rule,
        {
            "utc_days": ["tuesday"],
            "utc_start": 300,
            "utc_end": 400,
            "prompt": "0.000003",
        },
    ]
    detected = "2026-08-28T12:00:00+00:00"
    added = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=None,
        new_rules=one_rule,
        detected_at=detected,
    )
    removed = _stored_schedule_event(
        from_scrape=9,
        to_scrape=12,
        old_rules=two_rules,
        new_rules=None,
        detected_at=detected,
    )

    plans = reporting.plan_stored_comparison_events(
        (added, removed),
        {"openrouter": OPENROUTER_PROFILE},
        reporting.make_report_detail_policy(),
    )

    assert [plan.identity for plan in plans] == [added.identity, removed.identity]
    assert len({plan.identity for plan in plans}) == 2
    assert [plan.projection.accounting.source_rule_count for plan in plans] == [1, 2]
    assert all(plan.projection.accounting.model_bucket == "conditional" for plan in plans)
    assert [plan.projection.core.event.source_timestamp for plan in plans] == [
        added.from_completed_at,
        removed.from_completed_at,
    ]
    assert not hasattr(plans[0].projection.core, "anchor")
    assert [plan.comparison_label for plan in plans] == [
        "relative to selected baseline",
        "relative to selected baseline",
    ]
    assert [plan.anchor_identity for plan in plans] == [added.identity, removed.identity]

    aggregate = reporting.build_changes_semantic_core(
        (added, removed),
        {"openrouter": OPENROUTER_PROFILE},
    )
    assert len(aggregate.pricing_models) == 1
    folded = aggregate.pricing_models[0]
    assert folded.model_bucket == "conditional"
    assert folded.conditional_policy_count == 2
    assert aggregate.conditional_event_count == 2
    assert aggregate.change_summary_identities == (added.identity, removed.identity)
    assert folded.event_identities == (added.identity, removed.identity)


def test_changes_unclassified_budget_is_owned_by_local_date_and_provider() -> None:
    events = tuple(
        replace(
            _stored_schedule_event(
                from_scrape=20 + index,
                to_scrape=30 + index,
                old_rules=[],
                new_rules=[],
                detected_at="2026-08-28T12:00:00+00:00",
            ),
            field_changes=(FieldChange(f"synthetic.unknown_{index}", 1, 2),),
        )
        for index in range(2)
    )
    plans = reporting.plan_stored_comparison_events(
        events,
        {"openrouter": OPENROUTER_PROFILE},
        reporting.make_report_detail_policy(unclassified_limit=1),
    )

    assert len(plans[0].projection.display.visible) == 1
    assert len(plans[1].projection.display.hidden_unclassified) == 1


def test_scan_unclassified_budget_remains_provider_owned_across_event_cores() -> None:
    first_event = replace(
        _event(),
        field_changes=(FieldChange("synthetic.first", 1, 2),),
    )
    second_event = replace(
        _event(),
        identity=LiveComparisonIdentity("openrouter", "synthetic/other", 10, 11),
        provider_model_id="synthetic/other",
        display_name="Synthetic Other",
        field_changes=(FieldChange("synthetic.second", 1, 2),),
    )
    cores = {
        event.identity: reporting.build_model_event_semantic_core(
            event, OPENROUTER_PROFILE
        )
        for event in (first_event, second_event)
    }
    changed = tuple(
        ModelDelta(
            "changed",
            event.provider_model_id,
            event.display_name,
            event.field_changes,
        )
        for event in (first_event, second_event)
    )

    plan = reporting._plan_provider_changes(
        changed,
        reporting.make_report_detail_policy(unclassified_limit=1),
        OPENROUTER_PROFILE,
        cores,
        provider_id="openrouter",
    )

    assert len(plan.planned[0].display.visible) == 1
    assert len(plan.planned[1].display.hidden_unclassified) == 1


def test_html_artifacts_build_renderer_local_anchor_registries(monkeypatch) -> None:
    core = reporting.build_model_event_semantic_core(_event(), OPENROUTER_PROFILE)
    delta = ModelDelta(
        "changed",
        core.event.provider_model_id,
        core.event.display_name,
        core.event.field_changes,
    )
    result = ProviderScanResult(
        provider_id="openrouter",
        provider_label="OpenRouter",
        status="success",
        current_count=1,
        saved=False,
        baseline=None,
        baseline_message=None,
        scrape_id=11,
        added=(),
        removed=(),
        changed=(delta,),
        profile=OPENROUTER_PROFILE,
    )
    real_registry = reporting._CardAnchors
    registries = []

    class CountingRegistry(real_registry):
        def __init__(self):
            super().__init__()
            registries.append(self)

    monkeypatch.setattr(reporting, "_CardAnchors", CountingRegistry)
    cores = {core.identity: core}
    for mode in ("default", "all"):
        reporting.render_scan_report(
            generated_at="2026-08-28T12:00:00+00:00",
            command="scan",
            format_name="html",
            provider_results=[result],
            detail_policy=reporting.make_report_detail_policy(mode=mode),
            semantic_cores=cores,
        )

    assert len(registries) == 2
    assert registries[0] is not registries[1]


def test_repeated_nonconditional_edges_fold_directions_by_unique_model() -> None:
    base = _stored_schedule_event(
        from_scrape=40,
        to_scrape=41,
        old_rules=[],
        new_rules=[],
        detected_at="2026-08-28T12:00:00+00:00",
    )
    higher = replace(
        base,
        field_changes=(FieldChange("pricing.prompt", "0.000001", "0.000002"),),
    )
    lower = replace(
        base,
        identity=StoredComparisonIdentity(
            "openrouter", "synthetic/model", 41, 42
        ),
        field_changes=(FieldChange("pricing.prompt", "0.000002", "0.000001"),),
    )

    aggregate = reporting.build_changes_semantic_core(
        (higher, lower),
        {"openrouter": OPENROUTER_PROFILE},
    )

    assert len(aggregate.pricing_models) == 1
    assert aggregate.pricing_models[0].model_bucket == "mixed"
    assert aggregate.pricing_models[0].direct_price_field_count == 2
    assert aggregate.pricing_models[0].event_identities == (
        higher.identity,
        lower.identity,
    )


def test_internal_none_accounting_does_not_create_price_movement_membership() -> None:
    base = _stored_schedule_event(
        from_scrape=50,
        to_scrape=51,
        old_rules=[],
        new_rules=[],
        detected_at="2026-08-28T12:00:00+00:00",
    )
    unchanged = replace(
        base,
        field_changes=(FieldChange("pricing.prompt", "0.1", "0.10"),),
    )

    aggregate = reporting.build_changes_semantic_core(
        (unchanged,),
        {"openrouter": OPENROUTER_PROFILE},
    )

    assert len(aggregate.events) == 1
    assert aggregate.events[0].accounting.direct_price_field_count == 1
    assert aggregate.events[0].accounting.model_bucket == "none"
    assert aggregate.pricing_models == ()


def test_internal_none_edge_retains_accounting_but_folds_with_higher_as_higher() -> None:
    base = _stored_schedule_event(
        from_scrape=60,
        to_scrape=61,
        old_rules=[],
        new_rules=[],
        detected_at="2026-08-28T12:00:00+00:00",
    )
    unchanged = replace(
        base,
        field_changes=(FieldChange("pricing.prompt", "0.1", "0.10"),),
    )
    higher = replace(
        base,
        identity=StoredComparisonIdentity(
            "openrouter", "synthetic/model", 61, 62
        ),
        field_changes=(FieldChange("pricing.prompt", "0.1", "0.2"),),
    )

    aggregate = reporting.build_changes_semantic_core(
        (unchanged, higher),
        {"openrouter": OPENROUTER_PROFILE},
    )

    assert [event.accounting.direct_price_field_count for event in aggregate.events] == [
        1,
        1,
    ]
    assert len(aggregate.pricing_models) == 1
    assert aggregate.pricing_models[0].model_bucket == "higher"
    assert aggregate.pricing_models[0].direct_price_field_count == 2
    assert aggregate.pricing_models[0].event_identities == (
        unchanged.identity,
        higher.identity,
    )


def test_duplicate_stored_identity_is_rejected_before_any_interpretation(
    monkeypatch,
) -> None:
    event = _stored_schedule_event(
        from_scrape=70,
        to_scrape=71,
        old_rules=[],
        new_rules=[],
        detected_at="2026-08-28T12:00:00+00:00",
    )
    calls = []
    real_builder = reporting.build_model_event_semantic_core

    def count_builder(*args, **kwargs):
        calls.append(args[0].identity)
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(reporting, "build_model_event_semantic_core", count_builder)

    with pytest.raises(ValueError, match="duplicate stored comparison identity"):
        reporting.build_changes_semantic_core(
            (event, event),
            {"openrouter": OPENROUTER_PROFILE},
        )

    assert calls == []


def test_explicit_incomplete_stored_core_mapping_never_rebuilds(monkeypatch) -> None:
    first = _stored_schedule_event(
        from_scrape=80,
        to_scrape=81,
        old_rules=[],
        new_rules=[],
        detected_at="2026-08-28T12:00:00+00:00",
    )
    second = _stored_schedule_event(
        from_scrape=81,
        to_scrape=82,
        old_rules=[],
        new_rules=[],
        detected_at="2026-08-28T13:00:00+00:00",
    )

    def reject_rebuild(*args, **kwargs):
        raise AssertionError("explicit semantic-core mapping triggered interpretation")

    monkeypatch.setattr(reporting, "build_semantic_core_index", reject_rebuild)

    with pytest.raises(ValueError, match="has no semantic core"):
        reporting.plan_stored_comparison_events(
            (first,),
            {"openrouter": OPENROUTER_PROFILE},
            reporting.make_report_detail_policy(),
            semantic_cores={},
        )

    first_core = reporting.build_model_event_semantic_core(
        reporting.pricing_event_from_stored(first),
        OPENROUTER_PROFILE,
    )
    with pytest.raises(ValueError, match="has no semantic core"):
        reporting.plan_stored_comparison_events(
            (first, second),
            {"openrouter": OPENROUTER_PROFILE},
            reporting.make_report_detail_policy(),
            semantic_cores={first.identity: first_core},
        )


def test_stored_plan_indexes_supplied_edge_maps_once() -> None:
    class CountingMap(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.items_calls = 0

        def items(self):
            self.items_calls += 1
            return super().items()

    cores = {}
    projections = {}
    models = {}
    policy = reporting.make_report_detail_policy(mode="all")
    for index in range(200):
        model_id = f"synthetic/model-{index}"
        identity = StoredComparisonIdentity(
            "openrouter", model_id, 1000 + index, 2000 + index
        )
        event = PricingComparisonEvent(
            identity=identity,
            provider_id="openrouter",
            provider_model_id=model_id,
            display_name=f"Synthetic Model {index}",
            detected_at="2026-08-28T12:00:00+00:00",
            source_timestamp="2026-08-27T12:00:00+00:00",
            target_timestamp="2026-08-28T12:00:00+00:00",
            field_changes=(FieldChange("status", "preview", "active"),),
            old_model_metadata={"id": model_id, "status": "preview"},
            new_model_metadata={"id": model_id, "status": "active"},
        )
        core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
        cores[identity] = core
        projections[identity] = reporting.project_model_event_semantics(
            core, policy, OPENROUTER_PROFILE
        )
        edge_key = (
            identity.provider_id,
            identity.provider_model_id,
            identity.from_scrape_id,
            identity.to_scrape_id,
        )
        models[edge_key] = [
            {
                "provider_model_id": model_id,
                "display_name": event.display_name,
                "change_kind": "field_changed",
                "field_name": "status",
                "old_value": "preview",
                "new_value": "active",
                "_comparison_edge": edge_key,
            }
        ]
    counted_cores = CountingMap(cores)
    counted_projections = CountingMap(projections)

    plan = reporting.plan_changes_provider(
        models,
        policy,
        OPENROUTER_PROFILE,
        counted_cores,
        counted_projections,
    )

    assert len(plan.entries) == 200
    assert counted_cores.items_calls == 1
    assert counted_projections.items_calls == 1


@pytest.mark.parametrize("format_name", ("text", "html"))
def test_changes_artifact_indexes_global_edge_maps_once_across_blocks(
    format_name: str,
    monkeypatch,
) -> None:
    class CountingMap(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.items_calls = 0

        def items(self):
            self.items_calls += 1
            return super().items()

    events = []
    scrape_id = 3000
    for day_index, day in enumerate(("27", "28")):
        for provider_index, provider_id in enumerate(
            ("synthetic-provider-a", "synthetic-provider-b")
        ):
            model_id = f"synthetic/model-{day_index}-{provider_index}"
            identity = StoredComparisonIdentity(
                provider_id,
                model_id,
                scrape_id,
                scrape_id + 1,
            )
            record = StoredChangeRecord(
                change_id=scrape_id,
                provider_id=provider_id,
                provider_model_id=model_id,
                from_scrape_id=scrape_id,
                to_scrape_id=scrape_id + 1,
                change_kind="field_changed",
                field_name="status",
                old_value="preview",
                new_value="active",
                detected_at=f"2026-08-{day}T12:00:00+00:00",
            )
            events.append(
                StoredComparisonEvent(
                    identity=identity,
                    provider_label=f"Synthetic Provider {provider_index}",
                    display_name=f"Synthetic Model {day_index}-{provider_index}",
                    detected_at=record.detected_at,
                    from_completed_at=f"2026-08-{day}T11:00:00+00:00",
                    to_completed_at=record.detected_at,
                    source_rows=(record,),
                    field_changes=(
                        FieldChange("status", "preview", "active"),
                    ),
                    old_model_metadata={"id": model_id, "status": "preview"},
                    new_model_metadata={"id": model_id, "status": "active"},
                )
            )
            scrape_id += 2
    profiles = {
        "synthetic-provider-a": OPENROUTER_PROFILE,
        "synthetic-provider-b": OPENROUTER_PROFILE,
    }
    semantic = reporting.build_changes_semantic_core(events, profiles)
    counted_cores = CountingMap(semantic.by_identity)
    projection_index_calls = []
    real_projection_index = reporting._index_stored_semantic_projections

    def count_projection_index(source):
        projection_index_calls.append(len(source or ()))
        return real_projection_index(source)

    monkeypatch.setattr(
        reporting,
        "_index_stored_semantic_projections",
        count_projection_index,
    )

    report = reporting.render_changes_report(
        format_name=format_name,
        provider_id=None,
        since=None,
        until=None,
        changes=(),
        provider_profiles=profiles,
        stored_events=tuple(events),
        semantic_cores=counted_cores,
        changes_semantic_core=semantic,
    )

    assert "Synthetic Provider" in report
    assert counted_cores.items_calls == 1
    assert projection_index_calls == [4]


def test_artifact_semantics_requires_exact_edge_resolution() -> None:
    requested_edge = ("openrouter", "synthetic/missing", 9000, 9001)
    models = {
        requested_edge: [
            {
                "provider_model_id": "synthetic/missing",
                "display_name": "Synthetic Missing",
                "change_kind": "field_changed",
                "field_name": "status",
                "old_value": "preview",
                "new_value": "active",
                "_comparison_edge": requested_edge,
            }
        ]
    }
    empty_artifact = reporting._build_stored_semantic_artifact_index({}, {})

    with pytest.raises(ValueError, match="no exact semantic edge"):
        reporting.plan_changes_provider(
            models,
            reporting.make_report_detail_policy(),
            OPENROUTER_PROFILE,
            artifact_semantics=empty_artifact,
        )

    other_identity = StoredComparisonIdentity(
        "openrouter", "synthetic/other", 9100, 9101
    )
    other_event = PricingComparisonEvent(
        identity=other_identity,
        provider_id="openrouter",
        provider_model_id="synthetic/other",
        display_name="Synthetic Other",
        detected_at="2026-08-28T12:00:00+00:00",
        source_timestamp="2026-08-27T12:00:00+00:00",
        target_timestamp="2026-08-28T12:00:00+00:00",
        field_changes=(FieldChange("status", "preview", "active"),),
        old_model_metadata={"id": "synthetic/other", "status": "preview"},
        new_model_metadata={"id": "synthetic/other", "status": "active"},
    )
    other_core = reporting.build_model_event_semantic_core(
        other_event, OPENROUTER_PROFILE
    )
    incomplete_artifact = reporting._build_stored_semantic_artifact_index(
        {other_identity: other_core},
        {},
    )

    with pytest.raises(ValueError, match="no exact semantic edge"):
        reporting.plan_changes_provider(
            models,
            reporting.make_report_detail_policy(),
            OPENROUTER_PROFILE,
            artifact_semantics=incomplete_artifact,
        )


def test_legacy_changes_planner_without_semantic_sources_still_renders() -> None:
    models = {
        "synthetic/model": [
            {
                "provider_model_id": "synthetic/model",
                "display_name": "Synthetic Model",
                "change_kind": "field_changed",
                "field_name": "status",
                "old_value": "preview",
                "new_value": "active",
            }
        ]
    }

    plan = reporting.plan_changes_provider(
        models,
        reporting.make_report_detail_policy(),
        OPENROUTER_PROFILE,
    )

    assert len(plan.entries) == 1
    assert plan.entries[0].semantic_core is None
    assert plan.entries[0].display.visible == (
        FieldChange("status", "preview", "active"),
    )


@pytest.mark.parametrize("format_name", ("text", "markdown"))
def test_scan_grouped_schedule_is_one_compact_utc_block_in_provider_price_order(
    format_name: str,
) -> None:
    report = _scan_report(_event(), format_name)

    assert report.count("Pricing schedule added") == 1
    assert "UTC" in report
    assert "Mon 01:00-02:00 UTC" in report
    assert report.index("Input $1.00") < report.index("Output $8.00")
    assert (
        "Movement: base down (Input down 50.0%); peak up "
        "(Input up 50.0%, Output up 12.5%) versus the prior advertised rates"
        in report
    )
    assert "actual routing and billing can vary" in report.lower()
    assert '"utc_days"' not in report
    assert "Utc start" not in report


def test_movement_base_label_follows_base_vector_when_scheduled_band_sorts_first() -> None:
    base = _event()
    new_rules = [
        {
            "utc_days": ["monday"],
            "utc_start": 0,
            "utc_end": 100,
            "prompt": "0.000003",
            "completion": "0.000009",
        }
    ]
    event = replace(
        base,
        field_changes=(
            base.field_changes[0],
            FieldChange("pricing.overrides", None, new_rules),
        ),
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {
                "prompt": "0.000001",
                "completion": "0.000008",
                "overrides": new_rules,
            },
        },
    )

    report = _scan_report(event, "text")

    assert (
        "Movement: peak up (Input up 50.0%, Output up 12.5%); "
        "base down (Input down 50.0%) versus the prior advertised rates"
        in report
    )


def test_full_coverage_base_vector_band_is_rendered_as_base_windows_once() -> None:
    weekday_rule = {
        "utc_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
        "prompt": "0.0000010",
    }
    weekend_rule = {
        "utc_days": ["saturday", "sunday"],
        "prompt": "0.0000010",
    }
    rules = [weekday_rule, weekend_rule]
    base = _event()
    event = replace(
        base,
        field_changes=(FieldChange("pricing.overrides", None, rules),),
        old_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001"},
        },
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001", "overrides": rules},
        },
    )

    report = _scan_report(event, "text")

    assert report.count("Base/default: Input $1.00 /1M tokens") == 1
    assert "Base-rate windows: Mon-Sun all day" in report
    assert "Scheduled band" not in report
    assert "Rates:" not in report


def test_mixed_price_groups_do_not_share_precision_basis() -> None:
    def event_for(rules: list[dict], pricing: dict) -> PricingComparisonEvent:
        base = _event()
        old_pricing = {
            key: value for key, value in pricing.items() if key != "overrides"
        }
        return replace(
            base,
            field_changes=(FieldChange("pricing.overrides", None, rules),),
            old_model_metadata={"id": "synthetic/model", "pricing": old_pricing},
            new_model_metadata={
                "id": "synthetic/model",
                "pricing": {**pricing, "overrides": rules},
            },
        )

    prompt_rule = {
        "utc_days": ["monday"],
        "prompt": "0.00000123",
    }
    prompt_only = _scan_report(
        event_for([prompt_rule], {"prompt": "0.00000123"}), "text"
    )
    mixed_rule = {**prompt_rule, "request": "12.3456"}
    mixed = _scan_report(
        event_for(
            [mixed_rule],
            {"prompt": "0.00000123", "request": "12.3456"},
        ),
        "text",
    )

    assert "Input $1.23 /1M tokens" in prompt_only
    assert "Input $1.23 /1M tokens; Per request $12.3456 /request" in mixed
    assert "$1.2300" not in mixed


@pytest.mark.parametrize("format_name", ("text", "markdown"))
def test_scan_all_detail_includes_source_rules_and_parent_evidence_exactly_once(
    format_name: str,
) -> None:
    report = _scan_report(_event(), format_name, detail_mode="all")

    assert "Source-ordered rules" in report
    assert "Rule 1:" in report
    assert "Input $3.00 /1M tokens" in report
    assert "Output $9.00 /1M tokens" in report
    assert report.count("Canonical stored parent old:") == 1
    assert report.count("Canonical stored parent new:") == 1
    assert report.count('"utc_days"') == 1
    if format_name == "markdown":
        assert "Canonical stored parent old: ` null `" in report
        assert "Canonical stored parent new: ` [" in report


@pytest.mark.parametrize("format_name", ("text", "markdown"))
def test_evidence_only_reorder_is_concise_silent_but_retained_in_all_audit(
    format_name: str,
) -> None:
    event = _evidence_only_event()

    concise = _scan_report(event, format_name)
    all_detail = _scan_report(event, format_name, detail_mode="all")

    assert "Pricing schedule" not in concise
    assert "Conditional pricing evidence (semantically unchanged)" in all_detail
    assert all_detail.count("Canonical stored parent old:") == 1
    assert all_detail.count("Canonical stored parent new:") == 1


@pytest.mark.parametrize("detail_mode", ("default", "all"))
def test_evidence_only_reorder_is_concise_silent_and_full_audit_unpromoted(
    detail_mode: str,
) -> None:
    report = _scan_report(_evidence_only_event(), "html", detail_mode=detail_mode)

    if detail_mode == "default":
        assert "synthetic/model" not in report
        assert "CONDITIONAL PRICING EVIDENCE" not in report
    else:
        assert "synthetic/model" in report
        assert "CONDITIONAL PRICING EVIDENCE" in report
        assert "Canonical stored parent old" in report
        assert "Canonical stored parent new" in report
        assert 'id="price-movement"' not in report


@pytest.mark.parametrize("detail_mode", ("default", "all"))
def test_evidence_only_reorder_changes_html_is_audit_only_in_all(
    detail_mode: str,
) -> None:
    event = _evidence_only_event()
    old_rules = reporting._mutable_json(event.field_changes[0].old_value)
    new_rules = reporting._mutable_json(event.field_changes[0].new_value)
    stored = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=old_rules,
        new_rules=new_rules,
        detected_at=event.detected_at,
    )
    core = reporting.build_model_event_semantic_core(
        reporting.pricing_event_from_stored(stored), OPENROUTER_PROFILE
    )

    report = reporting.render_changes_report(
        format_name="html",
        provider_id=None,
        since=None,
        until=None,
        changes=(),
        provider_profiles={"openrouter": OPENROUTER_PROFILE},
        detail_policy=reporting.make_report_detail_policy(mode=detail_mode),
        stored_events=(stored,),
        semantic_cores={stored.identity: core},
    )

    if detail_mode == "default":
        assert "synthetic/model" not in report
        assert "CONDITIONAL PRICING EVIDENCE" not in report
    else:
        assert "synthetic/model" in report
        assert "CONDITIONAL PRICING EVIDENCE" in report
        assert "Canonical stored parent old" in report
        assert "Canonical stored parent new" in report
        assert 'id="price-movement"' not in report


@pytest.mark.parametrize("format_name", ("text", "markdown"))
def test_ordered_rules_show_explicit_and_not_set_cells(format_name: str) -> None:
    base = _event()
    new_rules = [
        {"min_prompt_tokens": 200000, "prompt": "0.000003"},
        {"utc_days": ["monday"], "utc_start": 100, "utc_end": 200, "completion": "0.000009"},
    ]
    new_metadata = {
        "id": "synthetic/model",
        "pricing": {
            "prompt": "0.000001",
            "completion": "0.000008",
            "overrides": new_rules,
        },
    }
    event = replace(
        base,
        field_changes=(FieldChange("pricing.overrides", None, new_rules),),
        new_model_metadata=new_metadata,
    )

    report = _scan_report(event, format_name)

    assert "Conditional pricing added" in report
    assert "Rules are evaluated in source order" in report
    assert "Prompt > 200,000 tokens" in report
    assert "not set by this rule" in report
    assert "inherited from base" not in report.lower()
    assert report.index("Input") < report.index("Output")

    all_detail = _scan_report(event, format_name, detail_mode="all")
    assert all_detail.count("Rule 1:") == 1
    assert all_detail.count("Rule 2:") == 1
    assert all_detail.count("Canonical stored parent old:") == 1
    assert all_detail.count("Canonical stored parent new:") == 1


@pytest.mark.parametrize("format_name", ("text", "markdown"))
def test_raw_fallback_is_self_contained_without_internal_exception_text(
    format_name: str,
) -> None:
    base = _event(metadata=False)
    malformed = {"unsupported": "synthetic"}
    event = replace(
        base,
        field_changes=(FieldChange("pricing.overrides", None, malformed),),
        old_model_metadata=None,
        new_model_metadata=None,
    )

    report = _scan_report(event, format_name)

    assert "Conditional pricing changed (stored conditions retained)" in report
    assert "No schedule direction was inferred" in report
    if format_name == "markdown":
        assert "Canonical stored parent old: ` null `" in report
        assert 'Canonical stored parent new: ` {"unsupported":"synthetic"} `' in report
    else:
        assert "Canonical stored parent old: null" in report
        assert 'Canonical stored parent new: {"unsupported":"synthetic"}' in report
    assert "invalid_policy_type" not in report


def test_markdown_canonical_json_is_literal_with_html_pipes_and_backtick_runs() -> None:
    hostile = {
        "payload": "</code><script>synthetic()</script>|`````",
    }
    event = replace(
        _event(metadata=False),
        field_changes=(FieldChange("pricing.overrides", None, hostile),),
        old_model_metadata=None,
        new_model_metadata=None,
    )
    canonical = '{"payload":"</code><script>synthetic()</script>|`````"}'
    literal = f"`````` {canonical} ``````"

    scan_markdown = _scan_report(event, "markdown")
    scan_text = _scan_report(event, "text")

    stored = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=None,
        new_rules=hostile,
        detected_at=event.detected_at,
    )
    core = reporting.build_model_event_semantic_core(
        reporting.pricing_event_from_stored(stored), OPENROUTER_PROFILE
    )
    history_markdown = reporting.render_history_report(
        provider_id="openrouter",
        model_id="synthetic/model",
        format_name="markdown",
        first_seen=None,
        last_seen=None,
        events=(HistoryEvent(event.detected_at, "changed", "pricing.overrides", None, hostile),),
        profile=OPENROUTER_PROFILE,
        detail_policy=reporting.make_report_detail_policy(mode="all"),
        stored_events=(stored,),
        semantic_cores={stored.identity: core},
    )

    for markdown in (scan_markdown, history_markdown):
        assert f"Canonical stored parent new: {literal}" in markdown
        assert f"Canonical stored parent new: {canonical}" not in markdown
    assert f"Canonical stored parent new: {canonical}" in scan_text
    assert literal not in scan_text


def test_history_and_changes_text_render_each_exact_edge_with_edge_timestamps() -> None:
    rules = [
        {
            "utc_days": ["monday"],
            "utc_start": 100,
            "utc_end": 200,
            "prompt": "0.000002",
        }
    ]
    added = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=None,
        new_rules=rules,
        detected_at="2026-08-28T12:00:00+00:00",
    )
    removed = _stored_schedule_event(
        from_scrape=11,
        to_scrape=12,
        old_rules=rules,
        new_rules=None,
        detected_at="2026-08-28T13:00:00+00:00",
    )
    stored = (added, removed)
    cores = reporting.build_changes_semantic_core(
        stored, {"openrouter": OPENROUTER_PROFILE}
    )
    legacy_history = tuple(
        HistoryEvent(
            event.detected_at,
            "changed",
            "pricing.overrides",
            event.field_changes[0].old_value,
            event.field_changes[0].new_value,
        )
        for event in stored
    )

    history = reporting.render_history_report(
        provider_id="openrouter",
        model_id="synthetic/model",
        format_name="text",
        first_seen="2026-08-01T00:00:00+00:00",
        last_seen="2026-08-28T13:00:00+00:00",
        events=legacy_history,
        profile=OPENROUTER_PROFILE,
        stored_events=stored,
        semantic_cores=cores.by_identity,
    )
    changes = reporting.render_changes_report(
        format_name="text",
        provider_id=None,
        since=None,
        until=None,
        changes=(),
        provider_profiles={"openrouter": OPENROUTER_PROFILE},
        stored_events=stored,
        semantic_cores=cores.by_identity,
        changes_semantic_core=cores,
    )

    for report in (history, changes):
        assert report.count("relative to selected baseline") == 2
        assert f"Source: {reporting.to_local_human(added.from_completed_at)}" in report
        assert f"Target: {reporting.to_local_human(added.to_completed_at)}" in report
        assert f"Source: {reporting.to_local_human(removed.from_completed_at)}" in report
        assert f"Target: {reporting.to_local_human(removed.to_completed_at)}" in report
        assert report.count("Pricing schedule added") == 1
        assert report.count("Pricing schedule removed") == 1
        assert "first appeared" not in report.lower()


def test_history_markdown_uses_the_same_exact_edge_conditional_block() -> None:
    rules = [
        {
            "utc_days": ["monday"],
            "utc_start": 100,
            "utc_end": 200,
            "prompt": "0.000002",
        }
    ]
    event = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=None,
        new_rules=rules,
        detected_at="2026-08-28T12:00:00+00:00",
    )
    core = reporting.build_model_event_semantic_core(
        reporting.pricing_event_from_stored(event), OPENROUTER_PROFILE
    )
    report = reporting.render_history_report(
        provider_id="openrouter",
        model_id="synthetic/model",
        format_name="markdown",
        first_seen=None,
        last_seen=None,
        events=(HistoryEvent(event.detected_at, "changed", "pricing.overrides", None, rules),),
        profile=OPENROUTER_PROFILE,
        detail_policy=reporting.make_report_detail_policy(mode="all"),
        stored_events=(event,),
        semantic_cores={event.identity: core},
    )

    assert "Pricing schedule added relative to selected baseline" in report
    assert "Mon 01:00-02:00 UTC" in report
    assert "Source:" in report and "Target:" in report
    assert "Canonical stored parent old: ` null `" in report
    assert "Canonical stored parent new: ` [" in report


def test_history_initial_presence_without_conditional_parent_keeps_legacy_shape() -> None:
    initial = replace(
        _stored_schedule_event(
            from_scrape=10,
            to_scrape=11,
            old_rules=None,
            new_rules=[],
            detected_at="2026-08-28T12:00:00+00:00",
        ),
        identity=StoredComparisonIdentity("openrouter", "synthetic/model", None, 11),
        source_rows=(
            replace(
                _stored_schedule_event(
                    from_scrape=10,
                    to_scrape=11,
                    old_rules=None,
                    new_rules=[],
                    detected_at="2026-08-28T12:00:00+00:00",
                ).source_rows[0],
                from_scrape_id=None,
                change_kind="added",
                field_name=None,
                old_value=None,
                new_value=None,
            ),
        ),
        field_changes=(),
        old_model_metadata=None,
    )
    core = reporting.build_model_event_semantic_core(
        reporting.pricing_event_from_stored(initial), OPENROUTER_PROFILE
    )

    report = reporting.render_history_report(
        provider_id="openrouter",
        model_id="synthetic/model",
        format_name="text",
        first_seen=initial.detected_at,
        last_seen=initial.detected_at,
        events=(HistoryEvent(initial.detected_at, "added", None, None, None),),
        profile=OPENROUTER_PROFILE,
        stored_events=(initial,),
        semantic_cores={initial.identity: core},
    )

    assert "[added]  null -> null" in report
    assert "+ synthetic/model (Synthetic Model)" not in report
    assert "Comparison detected" not in report


def test_conditional_semantics_do_not_change_any_public_json_payload() -> None:
    result = _scan_result(_event())
    event = _event()
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
    scan_without = reporting.render_scan_report(
        generated_at=event.detected_at,
        command="scan",
        format_name="json",
        provider_results=[result],
    )
    scan_with = reporting.render_scan_report(
        generated_at=event.detected_at,
        command="scan",
        format_name="json",
        provider_results=[result],
        semantic_cores={core.identity: core},
    )

    stored = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=None,
        new_rules=event.field_changes[1].new_value,
        detected_at=event.detected_at,
    )
    history_events = (
        HistoryEvent(
            event.detected_at,
            "changed",
            "pricing.overrides",
            None,
            reporting._mutable_json(event.field_changes[1].new_value),
        ),
    )
    history_without = reporting.render_history_report(
        provider_id="openrouter",
        model_id="synthetic/model",
        format_name="json",
        first_seen=None,
        last_seen=None,
        events=history_events,
        profile=OPENROUTER_PROFILE,
    )
    history_with = reporting.render_history_report(
        provider_id="openrouter",
        model_id="synthetic/model",
        format_name="json",
        first_seen=None,
        last_seen=None,
        events=history_events,
        profile=OPENROUTER_PROFILE,
        stored_events=(stored,),
        semantic_cores={stored.identity: reporting.build_model_event_semantic_core(reporting.pricing_event_from_stored(stored), OPENROUTER_PROFILE)},
    )
    legacy_change = ({
        "provider_id": "openrouter",
        "provider_label": "OpenRouter",
        "provider_model_id": "synthetic/model",
        "display_name": "Synthetic Model",
        "change_kind": "field_changed",
        "field_name": "pricing.overrides",
        "old_value": None,
        "new_value": reporting._mutable_json(event.field_changes[1].new_value),
        "detected_at": event.detected_at,
    },)
    changes_without = reporting.render_changes_report(
        format_name="json", provider_id=None, since=None, until=None, changes=legacy_change
    )
    changes_with = reporting.render_changes_report(
        format_name="json",
        provider_id=None,
        since=None,
        until=None,
        changes=legacy_change,
        stored_events=(stored,),
        semantic_cores={stored.identity: reporting.build_model_event_semantic_core(reporting.pricing_event_from_stored(stored), OPENROUTER_PROFILE)},
    )

    assert json.loads(scan_with) == json.loads(scan_without)
    assert json.loads(history_with) == json.loads(history_without)
    assert json.loads(changes_with) == json.loads(changes_without)
    for payload in (scan_with, history_with, changes_with):
        assert "from_scrape_id" not in payload
        assert "to_scrape_id" not in payload
        assert "old_model_metadata" not in payload
        assert "new_model_metadata" not in payload


def test_scan_html_renders_grouped_schedule_and_exclusive_conditional_bucket() -> None:
    report = _scan_report(_event(), "html")

    assert report.count('class="conditional-pricing') == 1
    assert "PRICING SCHEDULE ADDED" in report
    assert 'class="utc-badge">UTC</span>' in report
    assert "Mon 01:00-02:00 UTC" in report
    assert report.index("Input") < report.index("Output")
    assert "$1.00" in report and "$8.00" in report
    assert "base down (Input down 50.0%)" in report
    assert "peak up (Input up 50.0%, Output up 12.5%)" in report
    assert "provider-advertised catalog rates" in report
    assert "actual routing and billing can vary" in report
    assert "Utc start" not in report
    assert "Utc end" not in report

    movement = report.split('id="price-movement"', 1)[1].split("</section>", 1)[0]
    assert movement.count("Conditional / variable") == 1
    assert "Lower only" not in movement
    assert "conditional pricing changed" in movement
    assert "1 pricing schedule added" in movement
    assert "1 rule" in movement
    assert "2 price dimensions" in movement
    assert "2 effective rate bands" in movement

    assert report.count('title="pricing.prompt"') == 0
    assert 'title="status"' in report
    assert report.count("Pricing schedule added") == 1
    assert "Utc days" not in report


def test_scan_html_all_detail_adds_ordered_audit_without_changing_semantics() -> None:
    concise = _scan_report(_event(), "html")
    full = _scan_report(_event(), "html", detail_mode="all")

    for fragment in (
        "Conditional / variable",
        "conditional pricing changed",
        "1 pricing schedule added",
        "2 price dimensions",
    ):
        assert fragment in concise
        assert fragment in full
    assert "Source-ordered rules" not in concise
    assert "Source-ordered rules" in full
    assert full.count("Rule 1") == 1
    assert full.count("Canonical stored parent old") == 1
    assert full.count("Canonical stored parent new") == 1
    assert full.count("&quot;utc_days&quot;") == 1
    assert 'id="show-raw" checked' in full


def test_scan_html_parent_only_card_survives_and_unrelated_price_stays_ordinary() -> None:
    base = _event()
    parent_only = replace(
        base,
        field_changes=(base.field_changes[1],),
    )
    parent_report = _scan_report(parent_only, "html")
    assert 'class="model-card"' in parent_report
    assert 'class="conditional-pricing grouped-schedule"' in parent_report
    assert 'class="card-table"' not in parent_report

    with_unrelated = replace(
        base,
        field_changes=(
            base.field_changes[0],
            base.field_changes[1],
            FieldChange("pricing.request", "1.0", "2.0"),
        ),
        old_model_metadata={
            **reporting._mutable_json(base.old_model_metadata),
            "pricing": {
                **reporting._mutable_json(base.old_model_metadata["pricing"]),
                "request": "1.0",
            },
        },
        new_model_metadata={
            **reporting._mutable_json(base.new_model_metadata),
            "pricing": {
                **reporting._mutable_json(base.new_model_metadata["pricing"]),
                "request": "2.0",
            },
        },
    )
    report = _scan_report(with_unrelated, "html")
    assert report.count('class="conditional-pricing') == 1
    assert 'title="pricing.request"' in report
    assert report.index('class="conditional-pricing') < report.index('title="pricing.request"')


def test_scan_html_mixed_price_groups_put_units_on_each_column() -> None:
    rule = {
        "utc_days": ["monday"],
        "prompt": "0.00000123",
        "request": "12.3456",
    }
    event = replace(
        _event(),
        field_changes=(FieldChange("pricing.overrides", None, [rule]),),
        old_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.00000123", "request": "12.3456"},
        },
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {
                "prompt": "0.00000123",
                "request": "12.3456",
                "overrides": [rule],
            },
        },
    )
    report = _scan_report(event, "html")
    schedule = report.split('class="conditional-pricing', 1)[1].split("</section>", 1)[0]
    assert "Input" in schedule and "/1M tokens" in schedule
    assert "Per request" in schedule and "/request" in schedule
    assert "$1.23" in schedule and "$12.3456" in schedule


def test_scan_html_ordinary_verdict_keeps_conditional_suffix_and_exclusive_group() -> None:
    conditional = _event()
    ordinary = replace(
        conditional,
        identity=LiveComparisonIdentity("openrouter", "synthetic/ordinary", 10, 11),
        provider_model_id="synthetic/ordinary",
        display_name="Synthetic Ordinary",
        field_changes=(FieldChange("pricing.prompt", "0.000001", "0.000002"),),
        old_model_metadata={"id": "synthetic/ordinary", "pricing": {"prompt": "0.000001"}},
        new_model_metadata={"id": "synthetic/ordinary", "pricing": {"prompt": "0.000002"}},
    )
    cores = {
        event.identity: reporting.build_model_event_semantic_core(
            event, OPENROUTER_PROFILE
        )
        for event in (conditional, ordinary)
    }
    result = replace(
        _scan_result(conditional),
        current_count=2,
        changed=tuple(
            ModelDelta(
                "changed",
                event.provider_model_id,
                event.display_name,
                tuple(
                    FieldChange(
                        change.field_name,
                        reporting._mutable_json(change.old_value),
                        reporting._mutable_json(change.new_value),
                    )
                    for change in event.field_changes
                ),
            )
            for event in (conditional, ordinary)
        ),
    )
    report = reporting.render_scan_report(
        generated_at=conditional.detected_at,
        command="scan",
        format_name="html",
        provider_results=[result],
        semantic_cores=cores,
    )
    movement = report.split('id="price-movement"', 1)[1].split("</section>", 1)[0]
    assert "higher — 1 up; conditional pricing also changed — 1 model" in movement
    assert movement.count("Conditional / variable") == 1
    assert movement.count("Higher only") == 1
    conditional_group = movement.split("Conditional / variable", 1)[1]
    assert "synthetic/model" in conditional_group
    assert "synthetic/ordinary" not in conditional_group


def test_model_price_impact_uses_accounting_not_detail_projection(monkeypatch) -> None:
    event = replace(
        _event(),
        field_changes=(FieldChange("pricing.prompt", "0.000001", "0.000002"),),
    )
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
    delta = ModelDelta(
        "changed", event.provider_model_id, event.display_name, event.field_changes
    )
    impacts = []
    for mode in ("default", "all", "squelched"):
        projection = reporting.project_model_event_semantics(
            core,
            reporting.make_report_detail_policy(mode=mode),
            OPENROUTER_PROFILE,
        )
        poisoned = replace(
            projection.display,
            visible=(FieldChange("status", "preview", "active"),),
        )
        item = reporting._PlannedModelChange(delta, poisoned, core)
        impacts.append(reporting._model_price_impact(item, profile=OPENROUTER_PROFILE))

    poisoned_item = reporting._PlannedModelChange(
        delta,
        replace(
            reporting.project_model_event_semantics(
                core,
                reporting.make_report_detail_policy(),
                OPENROUTER_PROFILE,
            ).display,
            visible=(FieldChange("status", "preview", "active"),),
        ),
        core,
    )
    monkeypatch.setattr(
        reporting,
        "classify_change",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tiering must not classify display rows")
        ),
    )
    assert reporting._model_price_impact(
        poisoned_item, profile=OPENROUTER_PROFILE
    ) == impacts[0]
    assert impacts[0] is not None
    assert impacts[0] == impacts[1] == impacts[2]
    assert impacts[0].primary_delta == 1.0


def test_semantic_price_impact_consumes_exact_core_accounting_without_rebuild(
    monkeypatch,
) -> None:
    event = replace(
        _event(),
        field_changes=(FieldChange("pricing.prompt", "0.000001", "0.000002"),),
    )
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
    projection = reporting.project_model_event_semantics(
        core, reporting.make_report_detail_policy(), OPENROUTER_PROFILE
    )
    item = reporting._PlannedModelChange(
        ModelDelta(
            "changed", event.provider_model_id, event.display_name, event.field_changes
        ),
        projection.display,
        core,
    )
    seen = []
    real_rank = reporting._impact_from_accounting

    def capture(accounting, model_id, profile):
        seen.append(accounting)
        return real_rank(accounting, model_id, profile)

    monkeypatch.setattr(reporting, "_impact_from_accounting", capture)
    monkeypatch.setattr(
        reporting,
        "build_model_pricing_accounting",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic tiering must not rebuild accounting")
        ),
    )
    monkeypatch.setattr(
        reporting,
        "_legacy_tiering_accounting",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic tiering must not enter legacy fallback")
        ),
    )

    impact = reporting._model_price_impact(item, profile=OPENROUTER_PROFILE)

    assert impact is not None and impact.primary_delta == 1.0
    assert seen == [core.accounting]
    assert seen[0] is core.accounting


def test_legacy_price_impact_fallback_is_isolated_to_missing_core(monkeypatch) -> None:
    delta = ModelDelta(
        "changed",
        "synthetic/legacy",
        "Synthetic Legacy",
        (FieldChange("pricing.prompt", "0.000001", "0.000002"),),
    )
    display = reporting._field_display_plan(
        delta.field_changes,
        reporting.make_report_detail_policy(),
        OPENROUTER_PROFILE,
    )
    calls = []
    real_fallback = reporting._legacy_tiering_accounting

    def capture(item, profile):
        calls.append(item.delta.provider_model_id)
        return real_fallback(item, profile)

    monkeypatch.setattr(reporting, "_legacy_tiering_accounting", capture)
    impact = reporting._model_price_impact(
        reporting._PlannedModelChange(delta, display, None),
        profile=OPENROUTER_PROFILE,
    )

    assert calls == ["synthetic/legacy"]
    assert impact is not None and impact.primary_delta == 1.0


def test_raw_fallback_html_discloses_safe_distinct_reason_labels() -> None:
    fixtures = (
        ({"unsupported": "synthetic"}, "Policy value is not a rule list."),
        ([{"unregistered_price": "7"}], "A price dimension has no registered unit or conversion."),
    )
    reports = []
    for raw_policy, reason_label in fixtures:
        event = replace(
            _event(metadata=False),
            field_changes=(FieldChange("pricing.overrides", None, raw_policy),),
            old_model_metadata=None,
            new_model_metadata=None,
        )
        report = _scan_report(event, "html")
        reports.append(report)
        assert reason_label in report
        assert "invalid_policy_type" not in report
        assert "unresolved_price_dimension" not in report
        assert "Traceback" not in report
    assert fixtures[0][1] not in reports[1]
    assert fixtures[1][1] not in reports[0]


def test_ordered_rule_units_include_override_only_dimensions() -> None:
    rules = [
        {"min_prompt_tokens": 200000, "prompt": "0.000003"},
        {"min_prompt_tokens": 300000, "request": "12.3456"},
    ]
    event = replace(
        _event(),
        field_changes=(FieldChange("pricing.overrides", None, rules),),
        old_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001"},
        },
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001", "overrides": rules},
        },
    )
    report = _scan_report(event, "html")
    block = report.split('class="conditional-pricing ordered-rules"', 1)[1].split(
        "</section>", 1
    )[0]
    assert "Input<span class=\"conditional-unit\">/1M tokens</span>" in block
    assert "Per request<span class=\"conditional-unit\">/request</span>" in block
    assert "$12.3456" in block


def test_utc_badge_requires_an_actual_time_selector() -> None:
    threshold_rules = [{"min_prompt_tokens": 200000, "prompt": "0.000003"}]
    threshold = replace(
        _event(),
        field_changes=(FieldChange("pricing.overrides", None, threshold_rules),),
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {
                "prompt": "0.000001",
                "completion": "0.000008",
                "overrides": threshold_rules,
            },
        },
    )
    assert 'class="utc-badge"' not in _scan_report(threshold, "html")

    time_rules = [
        {"min_prompt_tokens": 200000, "prompt": "0.000003"},
        {
            "utc_days": ["monday"],
            "utc_start": 100,
            "utc_end": 200,
            "completion": "0.000009",
        },
    ]
    with_time = replace(
        threshold,
        field_changes=(FieldChange("pricing.overrides", None, time_rules),),
        new_model_metadata={
            **reporting._mutable_json(threshold.new_model_metadata),
            "pricing": {
                **reporting._mutable_json(threshold.new_model_metadata["pricing"]),
                "overrides": time_rules,
            },
        },
    )
    assert 'class="utc-badge">UTC</span>' in _scan_report(with_time, "html")

    for format_name in ("text", "markdown"):
        assert "Conditional pricing added - UTC" not in _scan_report(
            threshold, format_name
        )
        assert "Conditional pricing added - UTC" in _scan_report(
            with_time, format_name
        )


def test_conditionless_grouped_schedule_is_still_a_utc_weekly_schedule() -> None:
    conditionless = [{"prompt": "0.000002"}]
    event = replace(
        _event(),
        field_changes=(FieldChange("pricing.overrides", None, conditionless),),
        old_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001"},
        },
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001", "overrides": conditionless},
        },
    )
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
    assert core.interpretation is not None
    assert core.interpretation.state == "grouped-schedule"

    report = _scan_report(event, "html")
    assert "Mon-Sun all day" in report
    assert 'class="utc-badge">UTC</span>' in report


def test_raw_fallback_utc_badge_follows_stored_selector_evidence() -> None:
    with_utc = [{"utc_days": ["synthetic-invalid-day"], "prompt": "0.000002"}]
    without_utc = {"unsupported": "synthetic"}
    reports = []
    for policy in (with_utc, without_utc):
        event = replace(
            _event(metadata=False),
            field_changes=(FieldChange("pricing.overrides", None, policy),),
            old_model_metadata=None,
            new_model_metadata=None,
        )
        reports.append(_scan_report(event, "html"))
    assert 'class="utc-badge">UTC</span>' in reports[0]
    assert 'class="utc-badge"' not in reports[1]


def test_raw_fallback_utc_badge_uses_active_profile_semantic_roles() -> None:
    alternate_weekdays = replace(
        OPENROUTER_PROFILE.pricing_override_condition_descriptors["utc_days"],
        field_name="days_utc",
    )
    profile = replace(
        OPENROUTER_PROFILE,
        kind="alternate-synthetic",
        pricing_override_condition_descriptors={"days_utc": alternate_weekdays},
    )
    rules = [{"days_utc": ["synthetic-invalid-day"], "prompt": "0.000002"}]
    event = replace(
        _event(metadata=False),
        field_changes=(FieldChange("pricing.overrides", None, rules),),
        old_model_metadata=None,
        new_model_metadata=None,
    )

    core = reporting.build_model_event_semantic_core(event, profile)
    assert core.interpretation is not None
    assert core.interpretation.state == "raw-fallback"
    assert core.interpretation.fallback_reason == "invalid_selector_value"
    assert 'class="utc-badge">UTC</span>' in _scan_report(
        event, "html", profile=profile
    )
    for format_name in ("text", "markdown"):
        assert "Conditional pricing changed (stored conditions retained) - UTC" in _scan_report(
            event, format_name, profile=profile
        )


def test_unregistered_utc_lookalike_does_not_invent_badge_semantics() -> None:
    rules = [{"days_utc": ["monday"], "prompt": "0.000002"}]
    event = replace(
        _event(metadata=False),
        field_changes=(FieldChange("pricing.overrides", None, rules),),
        old_model_metadata=None,
        new_model_metadata=None,
    )

    assert 'class="utc-badge"' not in _scan_report(event, "html")
    for format_name in ("text", "markdown"):
        assert "stored conditions retained) - UTC" not in _scan_report(
            event, format_name
        )


@pytest.mark.parametrize("format_name", ("text", "markdown", "html"))
@pytest.mark.parametrize("detail_mode", ("default", "all", "squelched"))
@pytest.mark.parametrize(
    ("profile", "field_name", "display_label"),
    (
        (
            OPENROUTER_PROFILE,
            "pricing.synthetic_unregistered",
            "Synthetic unregistered",
        ),
        (
            GENERIC_PROFILE.with_pricing(7, 3),
            "pricing.synthetic_rate",
            "Synthetic rate",
        ),
    ),
)
def test_unmatched_ordinary_prices_stay_visible_and_are_neutral_accounting(
    format_name: str,
    detail_mode: str,
    profile: ProviderProfile,
    field_name: str,
    display_label: str,
) -> None:
    event = replace(
        _event(metadata=False),
        field_changes=(
            FieldChange(field_name, "1", "2"),
        ),
        old_model_metadata={
            "id": "synthetic/model",
            "pricing": {"synthetic_unregistered": "1"},
        },
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {"synthetic_unregistered": "2"},
        },
    )
    core = reporting.build_model_event_semantic_core(event, profile)

    assert core.interpretation is None
    assert core.accounting.direct_price_field_count == 1
    assert core.accounting.model_bucket == "none"
    assert core.accounting.direct_price_facts[0].direction == "unknown"
    report = _scan_report(
        event, format_name, detail_mode=detail_mode, profile=profile
    )
    if detail_mode == "squelched":
        assert display_label not in report
        assert 'id="price-movement"' not in report
    else:
        assert display_label in report
        if format_name == "html":
            movement = report.split('id="price-movement"', 1)[1].split(
                "</section>", 1
            )[0]
            assert "no normalized rate movement" in movement
            assert "1 direct price field" in movement
            assert "1 unchanged/unknown" in movement
            assert "Higher only" not in movement
            assert "Lower only" not in movement
    assert "Conditional pricing" not in report


@pytest.mark.parametrize("include_raw_parent", (False, True))
@pytest.mark.parametrize(("old_value", "new_value"), ((100, 200), (None, 100)))
@pytest.mark.parametrize(
    ("profile", "selector_path"),
    (
        (OPENROUTER_PROFILE, "pricing.overrides[0].utc_start"),
        (
            replace(
                OPENROUTER_PROFILE,
                pricing_override_condition_fields=("start_utc",),
                pricing_override_condition_descriptors={},
            ),
            "pricing.overrides[0].start_utc",
        ),
        (
            ProviderProfile(
                kind="legacy-selector-synthetic",
                pricing_override_condition_fields=("legacy_selector",),
            ),
            "pricing.overrides[0].legacy_selector",
        ),
    ),
)
def test_selector_rows_never_pollute_direct_accounting_even_with_raw_fallback(
    profile: ProviderProfile,
    selector_path: str,
    old_value: int | None,
    new_value: int,
    include_raw_parent: bool,
) -> None:
    changes = [FieldChange(selector_path, old_value, new_value)]
    if include_raw_parent:
        changes.insert(
            0,
            FieldChange(
                "pricing.overrides",
                None,
                {"synthetic-malformed": True},
            ),
        )
    event = replace(
        _event(metadata=False),
        field_changes=tuple(changes),
        old_model_metadata=None,
        new_model_metadata=None,
    )

    core = reporting.build_model_event_semantic_core(event, profile)

    assert core.accounting.direct_price_field_count == 0
    assert core.accounting.direct_price_facts == ()
    if include_raw_parent:
        assert core.interpretation is not None
        assert core.interpretation.state == "raw-fallback"
    else:
        assert core.interpretation is None
    rendered = reporting.classify_change(
        FieldChange(selector_path, old_value, new_value), profile=profile
    )
    assert rendered.kind != "price"


def _stored_event_with_selector_row(
    event: StoredComparisonEvent,
    *,
    selector_path: str,
    old_value=100,
    new_value=200,
) -> StoredComparisonEvent:
    selector = StoredChangeRecord(
        change_id=event.source_rows[-1].change_id + 100,
        provider_id=event.identity.provider_id,
        provider_model_id=event.identity.provider_model_id,
        from_scrape_id=event.identity.from_scrape_id,
        to_scrape_id=event.identity.to_scrape_id,
        change_kind="field_changed",
        field_name=selector_path,
        old_value=old_value,
        new_value=new_value,
        detected_at=event.detected_at,
    )
    return replace(
        event,
        source_rows=(*event.source_rows, selector),
        field_changes=(
            *event.field_changes,
            FieldChange(selector_path, old_value, new_value),
        ),
    )


def _selector_render_cases():
    start = replace(
        OPENROUTER_PROFILE.pricing_override_condition_descriptors["utc_start"],
        field_name="start_utc",
    )
    end = replace(
        OPENROUTER_PROFILE.pricing_override_condition_descriptors["utc_end"],
        field_name="end_utc",
    )
    rich_descriptors = dict(
        OPENROUTER_PROFILE.pricing_override_condition_descriptors
    )
    rich_descriptors.pop("utc_start")
    rich_descriptors.pop("utc_end")
    rich_descriptors.update(start_utc=start, end_utc=end)
    rich = replace(
        OPENROUTER_PROFILE,
        pricing_override_condition_fields=(),
        pricing_override_condition_descriptors=rich_descriptors,
    )
    legacy = replace(
        OPENROUTER_PROFILE,
        pricing_override_condition_fields=("legacy_start",),
        pricing_override_condition_descriptors={},
    )
    return (
        (
            OPENROUTER_PROFILE,
            "pricing.overrides[0].utc_start",
            "Utc start",
            [{
                "utc_days": ["monday"],
                "utc_start": 100,
                "utc_end": 200,
                "prompt": "0.000002",
            }],
        ),
        (
            rich,
            "pricing.overrides[0].start_utc",
            "Start utc",
            [{
                "utc_days": ["monday"],
                "start_utc": 100,
                "end_utc": 200,
                "prompt": "0.000002",
            }],
        ),
        (
            legacy,
            "pricing.overrides[0].legacy_start",
            "Legacy start",
            [{"legacy_start": 100, "prompt": "0.000002"}],
        ),
    )


@pytest.mark.parametrize("detail_mode", ("default", "all", "squelched"))
@pytest.mark.parametrize("format_name", ("text", "markdown", "html"))
@pytest.mark.parametrize("with_parent", (False, True), ids=("orphan", "parent"))
@pytest.mark.parametrize(
    ("profile", "selector_path", "selector_label", "rules"),
    _selector_render_cases(),
    ids=("openrouter", "rich-alternate", "legacy-alternate"),
)
def test_scan_selector_evidence_is_kept_inside_policy_and_never_detached(
    detail_mode: str,
    format_name: str,
    with_parent: bool,
    profile: ProviderProfile,
    selector_path: str,
    selector_label: str,
    rules,
) -> None:
    changes = [FieldChange(selector_path, 100, 200)]
    if with_parent:
        changes.insert(0, FieldChange("pricing.overrides", None, rules))
    event = replace(
        _event(metadata=False),
        field_changes=tuple(changes),
        old_model_metadata=(
            {"id": "synthetic/model", "pricing": {"prompt": "0.000001"}}
            if with_parent
            else None
        ),
        new_model_metadata=(
            {
                "id": "synthetic/model",
                "pricing": {"prompt": "0.000001", "overrides": rules},
            }
            if with_parent
            else None
        ),
    )
    core = reporting.build_model_event_semantic_core(event, profile)

    assert tuple(change.field_name for change in core.remaining_field_changes) == ()
    assert event.field_changes[-1].field_name == selector_path
    report = _scan_report(
        event, format_name, detail_mode=detail_mode, profile=profile
    )
    assert selector_label not in report
    assert selector_path not in report
    if format_name == "html" and (
        not with_parent or detail_mode == "squelched"
    ):
        assert '<div class="model-card"' not in report
    if with_parent and detail_mode != "squelched":
        assert "pricing" in report.casefold()


@pytest.mark.parametrize("detail_mode", ("default", "all", "squelched"))
@pytest.mark.parametrize("format_name", ("text", "markdown"))
@pytest.mark.parametrize("with_parent", (False, True), ids=("orphan", "parent"))
@pytest.mark.parametrize(
    ("profile", "selector_path", "selector_label", "rules"),
    _selector_render_cases(),
    ids=("openrouter", "rich-alternate", "legacy-alternate"),
)
def test_history_selector_evidence_is_not_a_detached_legacy_row(
    detail_mode: str,
    format_name: str,
    with_parent: bool,
    profile: ProviderProfile,
    selector_path: str,
    selector_label: str,
    rules,
) -> None:
    base = (
        _stored_schedule_event(
            from_scrape=10,
            to_scrape=11,
            old_rules=None,
            new_rules=rules,
            detected_at="2026-08-28T12:00:00+00:00",
        )
        if with_parent
        else _stored_ordinary_event(
            from_scrape=10,
            to_scrape=11,
            detected_at="2026-08-28T12:00:00+00:00",
            field_name=selector_path,
            old_value=100,
            new_value=200,
        )
    )
    event = (
        _stored_event_with_selector_row(
            base, selector_path=selector_path
        )
        if with_parent
        else base
    )
    history_events = tuple(
        HistoryEvent(
            row.detected_at,
            row.change_kind,
            row.field_name,
            row.old_value,
            row.new_value,
        )
        for row in event.source_rows
    )
    core = reporting.build_model_event_semantic_core(
        reporting.pricing_event_from_stored(event), profile
    )

    report = reporting.render_history_report(
        provider_id="openrouter",
        model_id="synthetic/model",
        format_name=format_name,
        first_seen=event.detected_at,
        last_seen=event.detected_at,
        events=history_events,
        profile=profile,
        detail_policy=reporting.make_report_detail_policy(mode=detail_mode),
        stored_events=(event,),
        semantic_cores={event.identity: core},
    )

    assert selector_path not in report
    assert selector_label not in report
    assert "100 -> 200" not in report


@pytest.mark.parametrize("detail_mode", ("default", "all", "squelched"))
@pytest.mark.parametrize("format_name", ("text", "html"))
@pytest.mark.parametrize("with_parent", (False, True), ids=("orphan", "parent"))
@pytest.mark.parametrize(
    ("profile", "selector_path", "selector_label", "rules"),
    _selector_render_cases(),
    ids=("openrouter", "rich-alternate", "legacy-alternate"),
)
def test_changes_selector_evidence_never_creates_a_detached_row_or_empty_card(
    detail_mode: str,
    format_name: str,
    with_parent: bool,
    profile: ProviderProfile,
    selector_path: str,
    selector_label: str,
    rules,
) -> None:
    base = (
        _stored_schedule_event(
            from_scrape=10,
            to_scrape=11,
            old_rules=None,
            new_rules=rules,
            detected_at="2026-08-28T12:00:00+00:00",
        )
        if with_parent
        else _stored_ordinary_event(
            from_scrape=10,
            to_scrape=11,
            detected_at="2026-08-28T12:00:00+00:00",
            field_name=selector_path,
            old_value=100,
            new_value=200,
        )
    )
    event = (
        _stored_event_with_selector_row(
            base, selector_path=selector_path
        )
        if with_parent
        else base
    )
    core = reporting.build_model_event_semantic_core(
        reporting.pricing_event_from_stored(event), profile
    )
    aggregate = reporting.build_changes_semantic_core(
        (event,), {"openrouter": profile}
    )
    report = reporting.render_changes_report(
        format_name=format_name,
        provider_id=None,
        since=None,
        until=None,
        changes=(),
        provider_profiles={"openrouter": profile},
        detail_policy=reporting.make_report_detail_policy(mode=detail_mode),
        stored_events=(event,),
        semantic_cores={event.identity: core},
        changes_semantic_core=aggregate,
    )

    assert selector_label not in report
    assert selector_path not in report
    assert "100 → 200" not in report
    if format_name == "html" and (
        not with_parent or detail_mode == "squelched"
    ):
        assert '<div class="model-card"' not in report


def test_selector_suppression_is_human_only_and_outside_lookalike_stays_ordinary() -> None:
    selector = FieldChange("pricing.overrides[0].utc_start", 100, 200)
    outside = FieldChange("pricing.metadata.utc_start", 100, 200)
    event = replace(
        _event(metadata=False),
        field_changes=(selector, outside),
        old_model_metadata=None,
        new_model_metadata=None,
    )
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)

    assert tuple(change.field_name for change in core.remaining_field_changes) == (
        "pricing.metadata.utc_start",
    )
    human = _scan_report(event, "text", detail_mode="all")
    payload = json.loads(_scan_report(event, "json", detail_mode="all"))
    assert "Utc start" in human
    assert "pricing.overrides[0].utc_start" not in human
    assert [
        change["field_name"]
        for change in payload["providers"][0]["changed"][0]["field_changes"]
    ] == [
        "pricing.overrides[0].utc_start",
        "pricing.metadata.utc_start",
    ]


def test_generic_reporting_has_no_provider_raw_utc_selector_constants() -> None:
    source = (
        Path(__file__).parents[1] / "model_sentinel" / "reporting.py"
    ).read_text()
    string_constants = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert string_constants.isdisjoint({"utc_days", "utc_start", "utc_end"})


def test_changes_edge_anchors_disambiguate_full_stored_identities() -> None:
    rules = [{"utc_days": ["monday"], "prompt": "0.000002"}]
    base = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=None,
        new_rules=rules,
        detected_at="2026-08-28T12:00:00+00:00",
    )
    events = []
    for model_id in ("synthetic/a.b", "synthetic/a/b"):
        identity = StoredComparisonIdentity("openrouter", model_id, 10, 11)
        events.append(
            replace(
                base,
                identity=identity,
                display_name=f"Synthetic {model_id[-1]}",
                source_rows=tuple(
                    replace(row, provider_model_id=model_id) for row in base.source_rows
                ),
                old_model_metadata={"id": model_id, "pricing": {"prompt": "0.000001"}},
                new_model_metadata={
                    "id": model_id,
                    "pricing": {"prompt": "0.000001", "overrides": rules},
                },
            )
        )
    cores = {
        event.identity: reporting.build_model_event_semantic_core(
            reporting.pricing_event_from_stored(event), OPENROUTER_PROFILE
        )
        for event in events
    }
    aggregate = reporting.build_changes_semantic_core(
        events, {"openrouter": OPENROUTER_PROFILE}
    )

    def render() -> str:
        return reporting.render_changes_report(
            format_name="html",
            provider_id=None,
            since=None,
            until=None,
            changes=(),
            provider_profiles={"openrouter": OPENROUTER_PROFILE},
            stored_events=events,
            semantic_cores=cores,
            changes_semantic_core=aggregate,
        )

    first = render()
    second = render()
    edge_ids = re.findall(r'id="(edge-[^"]+)"', first)
    edge_hrefs = re.findall(r'href="#(edge-[^"]+)"', first)

    assert first == second
    assert len(edge_ids) == len(set(edge_ids)) == 2
    assert set(edge_hrefs) == set(edge_ids)
    assert all(edge_hrefs.count(anchor) == 2 for anchor in edge_ids)
    assert edge_ids[1] == f"{edge_ids[0]}-2"


def test_changes_edge_anchors_are_owned_only_by_rendered_cards_in_document_order() -> None:
    first_rule = {"utc_days": ["monday"], "prompt": "0.000002"}
    second_rule = {"utc_days": ["tuesday"], "prompt": "0.000003"}
    hidden_base = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=[first_rule, second_rule],
        new_rules=[second_rule, first_rule],
        detected_at="2026-08-28T12:00:00+00:00",
    )
    hidden_model = "synthetic/a.b"
    hidden = replace(
        hidden_base,
        identity=StoredComparisonIdentity("openrouter", hidden_model, 10, 11),
        display_name="Synthetic Hidden",
        source_rows=tuple(
            replace(row, provider_model_id=hidden_model)
            for row in hidden_base.source_rows
        ),
        old_model_metadata={
            "id": hidden_model,
            "pricing": {
                "prompt": "0.000001",
                "overrides": [first_rule, second_rule],
            },
        },
        new_model_metadata={
            "id": hidden_model,
            "pricing": {
                "prompt": "0.000001",
                "overrides": [second_rule, first_rule],
            },
        },
    )
    visible_model = "synthetic/a/b"
    visible_base = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=None,
        new_rules=[first_rule],
        detected_at="2026-08-28T12:00:00+00:00",
    )
    visible = replace(
        visible_base,
        identity=StoredComparisonIdentity("openrouter", visible_model, 10, 11),
        display_name="Synthetic Visible",
        source_rows=tuple(
            replace(row, provider_model_id=visible_model)
            for row in visible_base.source_rows
        ),
        old_model_metadata={"id": visible_model, "pricing": {"prompt": "0.000001"}},
        new_model_metadata={
            "id": visible_model,
            "pricing": {"prompt": "0.000001", "overrides": [first_rule]},
        },
    )
    events = (hidden, visible)
    cores = {
        event.identity: reporting.build_model_event_semantic_core(
            reporting.pricing_event_from_stored(event), OPENROUTER_PROFILE
        )
        for event in events
    }
    assert cores[hidden.identity].evidence_only
    aggregate = reporting.build_changes_semantic_core(
        events, {"openrouter": OPENROUTER_PROFILE}
    )

    def render(mode: str) -> str:
        return reporting.render_changes_report(
            format_name="html",
            provider_id=None,
            since=None,
            until=None,
            changes=(),
            provider_profiles={"openrouter": OPENROUTER_PROFILE},
            detail_policy=reporting.make_report_detail_policy(mode=mode),
            stored_events=events,
            semantic_cores=cores,
            changes_semantic_core=aggregate,
        )

    concise = render("default")
    concise_ids = re.findall(r'id="(edge-[^"]+)"', concise)
    concise_hrefs = re.findall(r'href="#(edge-[^"]+)"', concise)
    assert concise_ids == ["edge-m-synthetic-a-b-from-10-to-11"]
    assert set(concise_hrefs) == set(concise_ids)

    full = render("all")
    assert full == render("all")
    full_ids = re.findall(r'id="(edge-[^"]+)"', full)
    full_hrefs = re.findall(r'href="#(edge-[^"]+)"', full)
    assert full_ids == [
        "edge-m-synthetic-a-b-from-10-to-11",
        "edge-m-synthetic-a-b-from-10-to-11-2",
    ]
    assert set(full_hrefs).issubset(set(full_ids))


def test_changes_price_movement_tallies_direct_fields_from_unique_model_folds() -> None:
    conditional = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=None,
        new_rules=[{"utc_days": ["monday"], "prompt": "0.000002"}],
        detected_at="2026-08-28T12:00:00+00:00",
    )
    ordinary = replace(
        conditional,
        identity=StoredComparisonIdentity("openrouter", "synthetic/model", 11, 12),
        field_changes=(FieldChange("pricing.prompt", "0.000001", "0.000002"),),
        old_model_metadata={"id": "synthetic/model", "pricing": {"prompt": "0.000001"}},
        new_model_metadata={"id": "synthetic/model", "pricing": {"prompt": "0.000002"}},
    )

    def movement(events) -> str:
        cores = {
            event.identity: reporting.build_model_event_semantic_core(
                reporting.pricing_event_from_stored(event), OPENROUTER_PROFILE
            )
            for event in events
        }
        aggregate = reporting.build_changes_semantic_core(
            events, {"openrouter": OPENROUTER_PROFILE}
        )
        report = reporting.render_changes_report(
            format_name="html",
            provider_id=None,
            since=None,
            until=None,
            changes=(),
            provider_profiles={"openrouter": OPENROUTER_PROFILE},
            stored_events=events,
            semantic_cores=cores,
            changes_semantic_core=aggregate,
        )
        return report.split('id="price-movement"', 1)[1].split("</section>", 1)[0]

    assert "1 direct price field" in movement((ordinary,))
    assert "0 direct price fields" in movement((conditional,))
    mixed = movement((conditional, ordinary))
    assert "1 direct price field" in mixed
    assert "2 pricing schedule events" not in mixed
    assert "1 pricing schedule event" in mixed


def test_ordered_rules_canonical_parent_evidence_is_always_one_disclosure() -> None:
    rules = [{"min_prompt_tokens": 200000, "prompt": "0.000003"}]
    event = replace(
        _event(),
        field_changes=(FieldChange("pricing.overrides", None, rules),),
        old_model_metadata={"id": "synthetic/model", "pricing": {"prompt": "0.000001"}},
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001", "overrides": rules},
        },
    )
    concise = _scan_report(event, "html")
    full = _scan_report(event, "html", detail_mode="all")

    for report in (concise, full):
        assert report.count('class="conditional-audit"') == 1
        assert report.count("Canonical stored parent old") == 1
        assert report.count("Canonical stored parent new") == 1
        assert "&quot;min_prompt_tokens&quot;" in report
    assert '<details class="conditional-audit">' in concise
    assert '<details class="conditional-audit" open>' not in concise
    assert '<details class="conditional-audit" open>' in full


def test_scan_price_tally_reconciles_all_semantic_direct_facts_neutrally() -> None:
    mixed_event = replace(
        _event(),
        field_changes=(
            FieldChange("pricing.prompt", "0.000001", "0.000002"),
            FieldChange("pricing.completion", "0.000008", "0.0000080"),
        ),
        old_model_metadata=None,
        new_model_metadata=None,
    )
    mixed_core = reporting.build_model_event_semantic_core(
        mixed_event, OPENROUTER_PROFILE
    )
    unknown_fact = replace(
        mixed_core.accounting.direct_price_facts[0],
        direction="unknown",
        delta=None,
        percentage=None,
        comparison_group=None,
    )
    unknown_core = replace(
        mixed_core,
        accounting=reporting.build_model_pricing_accounting(
            None, direct_price_facts=(unknown_fact,)
        ),
    )

    for mode in ("default", "all"):
        mixed_report = _scan_report(mixed_event, "html", detail_mode=mode)
        movement = mixed_report.split('id="price-movement"', 1)[1].split(
            "</section>", 1
        )[0]
        assert "2 direct price fields" in movement
        assert "1 unchanged/unknown" in movement

        unknown_report = reporting.render_scan_report(
            generated_at=mixed_event.detected_at,
            command="scan",
            format_name="html",
            provider_results=[_scan_result(mixed_event)],
            detail_policy=reporting.make_report_detail_policy(mode=mode),
            semantic_cores={unknown_core.identity: unknown_core},
        )
        unknown_movement = unknown_report.split('id="price-movement"', 1)[1].split(
            "</section>", 1
        )[0]
        assert "1 direct price field" in unknown_movement
        assert "1 unchanged/unknown" in unknown_movement
        assert "Higher only" not in unknown_movement
        assert "Lower only" not in unknown_movement


@pytest.mark.parametrize(
    ("field_name", "old_value", "new_value", "chip"),
    (
        ("pricing.request", None, "1.0", "+1 added"),
        ("pricing.image", "2.0", None, "−1 removed"),
    ),
)
def test_semantic_coverage_fact_preserves_added_or_removed_chip(
    field_name, old_value, new_value, chip
) -> None:
    rules = [{"utc_days": ["monday"], "prompt": "0.000002"}]
    event = replace(
        _event(),
        field_changes=(
            FieldChange(field_name, old_value, new_value),
            FieldChange("pricing.overrides", None, rules),
        ),
        old_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001", field_name.removeprefix("pricing."): old_value},
        },
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {
                "prompt": "0.000001",
                field_name.removeprefix("pricing."): new_value,
                "overrides": rules,
            },
        },
    )
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
    assert core.accounting.direct_price_facts[0].direction == "coverage"

    movement = _scan_report(event, "html").split('id="price-movement"', 1)[1].split(
        "</section>", 1
    )[0]
    assert "1 direct price field" in movement
    assert chip in movement
    assert "unchanged/unknown" not in movement


def test_semantic_direct_tally_reconciles_movement_coverage_and_neutral_facts() -> None:
    rules = [{"utc_days": ["monday"], "prompt": "0.000002"}]
    event = replace(
        _event(),
        field_changes=(
            FieldChange("pricing.completion", "0.000008", "0.000009"),
            FieldChange("pricing.request", None, "1.0"),
            FieldChange("pricing.image", "2.0", None),
            FieldChange("pricing.input_cache_read", "0.0000040", "0.000004"),
            FieldChange("pricing.overrides", None, rules),
        ),
        old_model_metadata={
            "id": "synthetic/model",
            "pricing": {
                "prompt": "0.000001",
                "completion": "0.000008",
                "image": "2.0",
                "input_cache_read": "0.0000040",
            },
        },
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {
                "prompt": "0.000001",
                "completion": "0.000009",
                "request": "1.0",
                "input_cache_read": "0.000004",
                "overrides": rules,
            },
        },
    )
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
    assert core.accounting.direct_price_field_count == 4
    assert [fact.direction for fact in core.accounting.direct_price_facts] == [
        "higher",
        "coverage",
        "coverage",
        "unchanged",
    ]

    movement = _scan_report(event, "html").split('id="price-movement"', 1)[1].split(
        "</section>", 1
    )[0]
    assert "4 direct price fields" in movement
    assert '<span class="price-tally-chip price-higher">↑ 1</span>' in movement
    assert '<span class="price-tally-chip price-coverage">+1 added</span>' in movement
    assert '<span class="price-tally-chip price-coverage">−1 removed</span>' in movement
    assert '<span class="price-tally-chip price-neutral">1 unchanged/unknown</span>' in movement


def test_mixed_band_colors_only_each_comparable_dimension_subfact() -> None:
    event = _event()
    mixed_rule = {
        "utc_days": ["monday"],
        "utc_start": 100,
        "utc_end": 200,
        "prompt": "0.000003",
        "completion": "0.000004",
    }
    event = replace(
        event,
        field_changes=(
            event.field_changes[0],
            FieldChange("pricing.overrides", None, [mixed_rule]),
        ),
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {
                "prompt": "0.000001",
                "completion": "0.000008",
                "overrides": [mixed_rule],
            },
        },
    )
    report = _scan_report(event, "html")

    assert '<span class="price-higher">Input up 50.0%</span>' in report
    assert '<span class="price-lower">Output down 50.0%</span>' in report
    assert 'conditional-movement price-higher">band' not in report
    assert 'conditional-movement price-lower">band' not in report
    for neutral in ("UTC", "Mon 01:00-02:00 UTC"):
        assert f'price-higher">{neutral}' not in report
        assert f'price-lower">{neutral}' not in report


def test_change_summary_uses_utc_band_only_for_time_window_semantics() -> None:
    threshold_rules = [{"min_prompt_tokens": 200000, "prompt": "0.000003"}]
    threshold = replace(
        _event(),
        field_changes=(FieldChange("pricing.overrides", None, threshold_rules),),
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001", "overrides": threshold_rules},
        },
    )
    raw = replace(
        _event(metadata=False),
        field_changes=(
            FieldChange(
                "pricing.overrides",
                None,
                [{"utc_days": ["synthetic-invalid-day"], "prompt": "0.000002"}],
            ),
        ),
        old_model_metadata=None,
        new_model_metadata=None,
    )

    threshold_report = _scan_report(threshold, "html")
    raw_report = _scan_report(raw, "html")
    grouped_report = _scan_report(_event(), "html")
    assert "effective rate band" in threshold_report
    assert "UTC rate band" not in threshold_report
    assert "effective rate band" in raw_report
    assert "UTC rate band" not in raw_report
    assert "UTC rate band" in grouped_report


def test_changes_neutral_direct_accounting_survives_without_a_model_bucket() -> None:
    base = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=[],
        new_rules=[],
        detected_at="2026-08-28T12:00:00+00:00",
    )

    def direct_edge(from_scrape, to_scrape, old_value, new_value):
        identity = StoredComparisonIdentity(
            "openrouter", "synthetic/model", from_scrape, to_scrape
        )
        return replace(
            base,
            identity=identity,
            source_rows=(
                replace(
                    base.source_rows[0],
                    from_scrape_id=from_scrape,
                    to_scrape_id=to_scrape,
                    field_name="pricing.prompt",
                    old_value=old_value,
                    new_value=new_value,
                ),
            ),
            field_changes=(FieldChange("pricing.prompt", old_value, new_value),),
            old_model_metadata={
                "id": "synthetic/model",
                "pricing": {"prompt": old_value},
            },
            new_model_metadata={
                "id": "synthetic/model",
                "pricing": {"prompt": new_value},
            },
        )

    unchanged = direct_edge(10, 11, "0.1", "0.10")
    unchanged_core = reporting.build_model_event_semantic_core(
        reporting.pricing_event_from_stored(unchanged), OPENROUTER_PROFILE
    )
    assert unchanged_core.accounting.model_bucket == "none"
    aggregate = reporting.build_changes_semantic_core(
        (unchanged,), {"openrouter": OPENROUTER_PROFILE}
    )
    assert aggregate.pricing_models == ()
    assert aggregate.direct_price_field_count == 1
    assert aggregate.neutral_direct_price_field_count == 1

    def render(events, cores, semantic, mode="default"):
        return reporting.render_changes_report(
            format_name="html",
            provider_id=None,
            since=None,
            until=None,
            changes=(),
            provider_profiles={"openrouter": OPENROUTER_PROFILE},
            detail_policy=reporting.make_report_detail_policy(mode=mode),
            stored_events=events,
            semantic_cores=cores,
            changes_semantic_core=semantic,
        )

    unchanged_cores = {unchanged.identity: unchanged_core}
    for mode in ("default", "all"):
        report = render((unchanged,), unchanged_cores, aggregate, mode)
        movement = report.split('id="price-movement"', 1)[1].split(
            "</section>", 1
        )[0]
        assert "no normalized rate movement" in movement
        assert "1 direct price field" in movement
        assert "1 unchanged/unknown" in movement
        assert "Higher only" not in movement
        assert "Conditional / variable" not in movement
    assert 'id="price-movement"' not in render(
        (unchanged,), unchanged_cores, aggregate, "squelched"
    )

    unknown_fact = replace(
        unchanged_core.accounting.direct_price_facts[0],
        direction="unknown",
        delta=None,
        percentage=None,
        comparison_group=None,
    )
    unknown_core = replace(
        unchanged_core,
        accounting=reporting.build_model_pricing_accounting(
            None, direct_price_facts=(unknown_fact,)
        ),
    )
    unknown_aggregate = replace(
        aggregate,
        events=(unknown_core,),
    )
    unknown_report = render(
        (unchanged,), {unchanged.identity: unknown_core}, unknown_aggregate
    )
    assert "no normalized rate movement" in unknown_report
    assert "1 direct price field" in unknown_report
    assert "1 unchanged/unknown" in unknown_report

    higher = direct_edge(11, 12, "0.1", "0.2")
    mixed_events = (unchanged, higher)
    mixed_cores = {
        event.identity: reporting.build_model_event_semantic_core(
            reporting.pricing_event_from_stored(event), OPENROUTER_PROFILE
        )
        for event in mixed_events
    }
    mixed_aggregate = reporting.build_changes_semantic_core(
        mixed_events, {"openrouter": OPENROUTER_PROFILE}
    )
    assert len(mixed_aggregate.pricing_models) == 1
    assert mixed_aggregate.pricing_models[0].model_bucket == "higher"
    assert mixed_aggregate.direct_price_field_count == 2
    assert mixed_aggregate.neutral_direct_price_field_count == 1
    mixed_report = render(mixed_events, mixed_cores, mixed_aggregate)
    mixed_movement = mixed_report.split('id="price-movement"', 1)[1].split(
        "</section>", 1
    )[0]
    assert mixed_movement.count("Higher only") == 1
    assert "2 direct price fields" in mixed_movement
    assert "1 unchanged/unknown" in mixed_movement


def test_composite_price_cells_reuse_raw_value_tooltips() -> None:
    grouped_rule = {"utc_days": ["monday"], "prompt": "0.0000010"}
    grouped = replace(
        _event(),
        field_changes=(FieldChange("pricing.overrides", None, [grouped_rule]),),
        old_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001"},
        },
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {"prompt": "0.000001", "overrides": [grouped_rule]},
        },
    )
    grouped_html = _scan_report(grouped, "html")
    assert 'title="0.0000010 (1.0e-6) × 1,000,000 = $1.00"' in grouped_html

    ordered_rule = {"min_prompt_tokens": 200000, "prompt": "0.0000030"}
    ordered = replace(
        _event(),
        field_changes=(FieldChange("pricing.overrides", None, [ordered_rule]),),
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {
                "prompt": "0.000001",
                "completion": "0.000008",
                "overrides": [ordered_rule],
            },
        },
    )
    ordered_html = _scan_report(ordered, "html")
    assert 'title="0.0000030 (3.0e-6) × 1,000,000 = $3.00"' in ordered_html


def test_scan_html_ordered_rules_and_raw_fallback_are_self_contained() -> None:
    base = _event()
    ordered_rules = [
        {"min_prompt_tokens": 200000, "prompt": "0.000003"},
        {
            "utc_days": ["monday"],
            "utc_start": 100,
            "utc_end": 200,
            "completion": "0.000009",
        },
    ]
    ordered = replace(
        base,
        field_changes=(FieldChange("pricing.overrides", None, ordered_rules),),
        new_model_metadata={
            "id": "synthetic/model",
            "pricing": {
                "prompt": "0.000001",
                "completion": "0.000008",
                "overrides": ordered_rules,
            },
        },
    )
    ordered_html = _scan_report(ordered, "html")
    assert "CONDITIONAL PRICING ADDED" in ordered_html
    assert ordered_html.index("Rule 1") < ordered_html.index("Rule 2")
    assert "Prompt &gt; 200,000 tokens" in ordered_html
    assert 'class="not-set"' in ordered_html
    assert "not set by this rule" in ordered_html
    assert "later matching rules win per price key" in ordered_html
    assert "inherited from base" not in ordered_html.lower()

    malformed = {"unsupported": "synthetic"}
    fallback = replace(
        _event(metadata=False),
        field_changes=(FieldChange("pricing.overrides", None, malformed),),
        old_model_metadata=None,
        new_model_metadata=None,
    )
    fallback_html = _scan_report(fallback, "html")
    assert "CONDITIONAL PRICING CHANGED" in fallback_html
    assert "No schedule direction was inferred" in fallback_html
    assert "Canonical stored parent old" in fallback_html
    assert "Canonical stored parent new" in fallback_html
    assert "invalid_policy_type" not in fallback_html


def test_scan_html_squelched_omits_semantic_panels_and_conditional_colors_are_cost_only() -> None:
    normal = _scan_report(_event(), "html")
    squelched = _scan_report(_event(), "html", detail_mode="squelched")

    assert 'class="conditional-pricing' not in squelched
    assert 'id="price-movement"' not in squelched
    assert "Conditional / variable" not in squelched

    assert 'class="conditional-movement price-lower"' in normal
    assert 'class="conditional-movement price-higher"' in normal
    for neutral in ("UTC", "Mon 01:00-02:00 UTC", "1 rule", "2 price dimensions"):
        assert f'price-higher">{neutral}' not in normal
        assert f'price-lower">{neutral}' not in normal


def test_html_change_summary_contains_wide_tables_at_narrow_widths() -> None:
    """A wide changes summary scrolls locally instead of widening the page."""
    report = _scan_report(_event(), "html")
    css = report.split("<style>", 1)[1].split("</style>", 1)[0]
    summary_rule = css.split(".summary-section {", 1)[1].split("}", 1)[0]

    assert "overflow-x: auto;" in summary_rule


def test_changes_html_keeps_repeated_stored_edges_distinct_with_edge_links() -> None:
    one_rule = [{"utc_days": ["monday"], "prompt": "0.000002"}]
    two_rules = [
        *one_rule,
        {"utc_days": ["tuesday"], "prompt": "0.000003"},
    ]
    detected = "2026-08-28T12:00:00+00:00"
    first = _stored_schedule_event(
        from_scrape=10,
        to_scrape=11,
        old_rules=None,
        new_rules=one_rule,
        detected_at=detected,
    )
    second = _stored_schedule_event(
        from_scrape=9,
        to_scrape=12,
        old_rules=two_rules,
        new_rules=None,
        detected_at=detected,
    )
    cores = {
        event.identity: reporting.build_model_event_semantic_core(
            reporting.pricing_event_from_stored(event), OPENROUTER_PROFILE
        )
        for event in (first, second)
    }
    aggregate = reporting.build_changes_semantic_core(
        (first, second), {"openrouter": OPENROUTER_PROFILE}
    )

    report = reporting.render_changes_report(
        format_name="html",
        provider_id=None,
        since=None,
        until=None,
        changes=(),
        provider_profiles={"openrouter": OPENROUTER_PROFILE},
        detail_policy=reporting.make_report_detail_policy(),
        stored_events=(first, second),
        semantic_cores=cores,
        changes_semantic_core=aggregate,
    )

    assert report.count('class="conditional-pricing') == 2
    assert report.count("relative to selected baseline") == 2
    assert report.count('class="edge-timestamps"') == 2
    assert report.count('class="conditional-summary-row"') == 2
    assert report.count('class="edge-link"') == 2
    assert report.count('id="edge-m-synthetic-model-') == 2
    assert "2 pricing schedule events" in report
    assert report.count("Pricing schedule added") == 1
    assert report.count("Pricing schedule removed") == 1
    assert "from-10-to-11" in report
    assert "from-9-to-12" in report
    assert report.count("synthetic/model") >= 4
    assert "Utc days" not in report
