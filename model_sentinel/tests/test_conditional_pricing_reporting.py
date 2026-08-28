from __future__ import annotations

import json
from dataclasses import replace

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
from model_sentinel.provider_profiles import OPENROUTER_PROFILE
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


def _scan_result(event: PricingComparisonEvent) -> ProviderScanResult:
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
        profile=OPENROUTER_PROFILE,
    )


def _scan_report(
    event: PricingComparisonEvent,
    format_name: str,
    *,
    detail_mode: str = "default",
) -> str:
    core = reporting.build_model_event_semantic_core(event, OPENROUTER_PROFILE)
    return reporting.render_scan_report(
        generated_at="2026-08-28T12:00:00+00:00",
        command="scan",
        format_name=format_name,
        provider_results=[_scan_result(event)],
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
def test_evidence_only_reorder_does_not_create_pre_task8_scan_html_card(
    detail_mode: str,
) -> None:
    report = _scan_report(_evidence_only_event(), "html", detail_mode=detail_mode)

    assert "synthetic/model" not in report
    assert "Conditional pricing evidence" not in report


@pytest.mark.parametrize("detail_mode", ("default", "all"))
def test_evidence_only_reorder_does_not_create_pre_task8_changes_html_card(
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

    assert "synthetic/model" not in report
    assert "Conditional pricing evidence" not in report


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


def test_history_rich_event_keeps_initial_presence_record_visible() -> None:
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

    assert "+ synthetic/model (Synthetic Model)" in report


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
