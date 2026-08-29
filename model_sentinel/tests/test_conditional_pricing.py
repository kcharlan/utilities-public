from __future__ import annotations

import ast
import math
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from pathlib import Path
from typing import Any, get_args
from unittest.mock import patch

import pytest

import model_sentinel.conditional_pricing as conditional_pricing
from model_sentinel.conditional_pricing import (
    AbsorbedBasePriceChange,
    ComparisonInhibitionReason,
    ConditionalPricingComparison,
    DirectPriceMovementFact,
    EffectivePriceValue,
    EffectivePriceVector,
    FallbackReason,
    GroupingInhibitionReason,
    LiveComparisonIdentity,
    ModelPricingAccounting,
    PricingComparisonEvent,
    StoredComparisonIdentity,
    WeeklySegment,
    build_model_pricing_accounting,
    compile_weekly_segments,
    decide_sibling_base_price_absorption,
    interpret_conditional_pricing,
    partition_weekly_segments,
    resolve_direct_price_movement,
    weekly_complement,
    weekly_coverage_contains,
    weekly_segments_overlap,
)
from model_sentinel.models import FieldChange
from model_sentinel.provider_profiles import (
    GENERIC_PROFILE,
    OPENROUTER_PROFILE,
    ConditionalPricingConditionDescriptor,
    ConditionalPricingConditionSetSemantics,
    ConditionalPricingPolicySemantics,
    PriceDisplayRule,
    ProviderProfile,
)
from tests.conditional_pricing_fixtures import (
    SYNTHETIC_SCHEDULED_RATE_EXPECTED_ACCOUNTING,
    synthetic_scheduled_rate_models,
)


PROVIDER_ID = "synthetic-provider"
MODEL_ID = "synthetic/conditional-demo"
ALL_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _event(
    *changes: FieldChange,
    old_metadata: dict[str, Any] | None = None,
    new_metadata: dict[str, Any] | None = None,
    identity: LiveComparisonIdentity | StoredComparisonIdentity | None = None,
) -> PricingComparisonEvent:
    if identity is None:
        identity = LiveComparisonIdentity(PROVIDER_ID, MODEL_ID, 10, 11)
    return PricingComparisonEvent(
        identity=identity,
        provider_id=PROVIDER_ID,
        provider_model_id=MODEL_ID,
        display_name="Synthetic Conditional Demo",
        detected_at="2042-04-05T06:07:08Z",
        source_timestamp="2042-04-04T06:07:08Z",
        target_timestamp="2042-04-05T06:07:08Z",
        field_changes=changes,
        old_model_metadata=old_metadata,
        new_model_metadata=new_metadata,
    )


def _interpret(
    old_value: Any,
    new_value: Any,
    *,
    profile: ProviderProfile = OPENROUTER_PROFILE,
    old_metadata: dict[str, Any] | None = None,
    new_metadata: dict[str, Any] | None = None,
):
    return interpret_conditional_pricing(
        _event(
            FieldChange("pricing.overrides", old_value, new_value),
            old_metadata=old_metadata,
            new_metadata=new_metadata,
        ),
        profile,
    )


def _complete_metadata(overrides: list[dict[str, Any]] | None) -> dict[str, Any]:
    pricing: dict[str, Any] = {"prompt": "0.000001", "completion": "0.000002"}
    if overrides is not None:
        pricing["overrides"] = overrides
    return {"id": MODEL_ID, "pricing": pricing}


def _interpret_complete(
    old_value: Any,
    new_value: Any,
    *,
    profile: ProviderProfile = OPENROUTER_PROFILE,
    old_metadata: dict[str, Any] | None = None,
    new_metadata: dict[str, Any] | None = None,
):
    return _interpret(
        old_value,
        new_value,
        profile=profile,
        old_metadata=(
            _complete_metadata(old_value) if old_metadata is None else old_metadata
        ),
        new_metadata=(
            _complete_metadata(new_value) if new_metadata is None else new_metadata
        ),
    )


def test_parent_absence_is_the_only_none_result() -> None:
    event = _event(FieldChange("pricing.prompt", "0.1", "0.2"))

    assert interpret_conditional_pricing(event, OPENROUTER_PROFILE) is None


@pytest.mark.parametrize(
    ("old_value", "new_value", "transition"),
    (
        (None, [], "added"),
        ([], None, "removed"),
        ([], [{"prompt": "0.000001"}], "changed"),
    ),
)
def test_parent_transition_is_classified_with_final_semantic_equality(
    old_value: Any,
    new_value: Any,
    transition: str,
) -> None:
    result = _interpret_complete(
        old_value,
        new_value,
    )

    assert result is not None
    assert result.transition == transition
    assert result.state == "grouped-schedule"
    assert result.semantic_change is True
    assert isinstance(result.comparison, ConditionalPricingComparison)
    assert isinstance(result.accounting, ModelPricingAccounting)
    assert result.accounting.conditional_policy_count == 1
    assert result.absorbed_base_price_changes == ()


@pytest.mark.parametrize(
    ("old_value", "new_value", "reason"),
    (
        (None, None, "malformed_parent_transition"),
        ({"not": "a list"}, [], "invalid_policy_type"),
        ([], "not a list", "invalid_policy_type"),
    ),
)
def test_malformed_parent_returns_typed_raw_fallback_with_stable_reason(
    old_value: Any,
    new_value: Any,
    reason: str,
) -> None:
    result = _interpret(old_value, new_value)

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == reason
    assert len(result.source_changes) == 1


def test_multiple_parents_retain_every_occurrence_in_source_order() -> None:
    first = FieldChange("pricing.overrides", None, [{"prompt": 1}])
    middle = FieldChange("pricing.prompt", 1, 2)
    second = FieldChange("pricing.overrides", None, [{"prompt": 1}])

    result = interpret_conditional_pricing(_event(first, middle, second), OPENROUTER_PROFILE)

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "multiple_parent_changes"
    assert [change.reference.source_index for change in result.source_changes] == [0, 2]
    assert [change.reference.occurrence for change in result.source_changes] == [0, 1]
    assert result.transition == "added"
    assert (
        result.source_changes[0].reference.field_name,
        result.source_changes[0].reference.old_value_canonical_json,
        result.source_changes[0].reference.new_value_canonical_json,
    ) == (
        result.source_changes[1].reference.field_name,
        result.source_changes[1].reference.old_value_canonical_json,
        result.source_changes[1].reference.new_value_canonical_json,
    )


@pytest.mark.parametrize(
    "parents",
    (
        (
            FieldChange("pricing.overrides", None, [{"prompt": 1}]),
            FieldChange("pricing.overrides", [{"prompt": 1}], None),
        ),
        (
            FieldChange("pricing.overrides", [{"prompt": 1}], None),
            FieldChange("pricing.overrides", None, [{"prompt": 1}]),
        ),
        (
            FieldChange("pricing.overrides", [], [{"prompt": 1}]),
            FieldChange("pricing.overrides", None, [{"prompt": 1}]),
        ),
        (
            FieldChange("pricing.overrides", None, [{"prompt": 1}]),
            FieldChange("pricing.overrides", [], [{"prompt": 1}]),
        ),
    ),
)
def test_multiple_parent_mixed_transitions_are_order_independent(
    parents: tuple[FieldChange, FieldChange],
) -> None:
    result = interpret_conditional_pricing(_event(*parents), OPENROUTER_PROFILE)

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.transition == "changed"
    assert [source.reference.source_index for source in result.source_changes] == [0, 1]


@pytest.mark.parametrize("malformed_side", ["old", "new"])
def test_malformed_policy_side_does_not_discard_valid_opposite_side(
    malformed_side: str,
) -> None:
    valid = [{"utc_days": ["monday"], "prompt": 1}]
    malformed = [{}]
    old_value, new_value = (
        (malformed, valid) if malformed_side == "old" else (valid, malformed)
    )

    result = _interpret(old_value, new_value)

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "empty_rule"
    assert (result.old_policy is not None) is (malformed_side == "new")
    assert (result.new_policy is not None) is (malformed_side == "old")
    parsed = result.new_policy if malformed_side == "old" else result.old_policy
    assert parsed is not None
    assert parsed.rules[0].utc_weekdays == ("monday",)


@pytest.mark.parametrize("value", [True, False, 3.5, "3"])
def test_threshold_requires_json_integer_and_never_bool(value: Any) -> None:
    result = _interpret(None, [{"min_prompt_tokens": value, "prompt": 1}])

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "invalid_selector_value"


def test_threshold_display_and_predicate_are_strictly_greater() -> None:
    result = _interpret(None, [{"min_prompt_tokens": 8, "prompt": 1}])
    assert result is not None and result.new_policy is not None
    threshold = next(
        condition
        for condition in result.new_policy.rules[0].conditions
        if condition.semantic_role == "integer_strictly_greater"
    )

    assert threshold.display_value == "Prompt > 8 tokens"
    assert [threshold.matches(value) for value in (7, 8, 9)] == [False, False, True]


def test_absent_time_selectors_mean_all_weekdays_and_all_day() -> None:
    result = _interpret(None, [{"prompt": 1}])
    assert result is not None and result.new_policy is not None
    rule = result.new_policy.rules[0]

    assert rule.utc_weekdays == ALL_WEEKDAYS
    assert (rule.start_minute, rule.end_minute) == (0, 1440)
    assert rule.conditions == ()


def test_weekdays_are_canonicalized_monday_to_sunday_and_input_order_is_noise() -> None:
    old = [{"utc_days": ["sunday", "monday", "friday"], "prompt": 1}]
    new = [{"utc_days": ["friday", "sunday", "monday"], "prompt": 1}]
    result = _interpret(old, new)
    assert result is not None and result.old_policy and result.new_policy

    old_rule = result.old_policy.rules[0]
    new_rule = result.new_policy.rules[0]
    assert old_rule.utc_weekdays == ("monday", "friday", "sunday")
    assert old_rule.canonical_condition_identity == new_rule.canonical_condition_identity
    assert result.structural_comparison is not None
    assert len(result.structural_comparison.matches) == 1


def _day_rule(day: str, price: int = 1) -> dict[str, Any]:
    return {"utc_days": [day], "prompt": price}


@pytest.mark.parametrize(
    ("old", "new", "order_changed", "old_only", "new_only"),
    (
        (
            [_day_rule("monday"), _day_rule("tuesday")],
            [_day_rule("tuesday"), _day_rule("monday")],
            True,
            0,
            0,
        ),
        (
            [_day_rule("monday"), _day_rule("tuesday")],
            [_day_rule("monday"), _day_rule("wednesday")],
            False,
            1,
            1,
        ),
        (
            [_day_rule("monday"), _day_rule("tuesday")],
            [_day_rule("monday"), _day_rule("wednesday"), _day_rule("tuesday")],
            False,
            0,
            1,
        ),
        (
            [_day_rule("monday"), _day_rule("wednesday"), _day_rule("tuesday")],
            [_day_rule("monday"), _day_rule("tuesday")],
            False,
            1,
            0,
        ),
    ),
)
def test_structural_source_order_uses_only_relative_order_of_surviving_matches(
    old: list[dict[str, Any]],
    new: list[dict[str, Any]],
    order_changed: bool,
    old_only: int,
    new_only: int,
) -> None:
    result = _interpret(old, new)
    assert (
        result is not None
        and result.old_policy is not None
        and result.new_policy is not None
        and result.structural_comparison is not None
    )
    structural = result.structural_comparison
    old_identities = tuple(rule.occurrence_identity for rule in result.old_policy.rules)
    new_identities = tuple(rule.occurrence_identity for rule in result.new_policy.rules)

    assert structural.source_order_changed is order_changed
    assert structural.old_only == tuple(
        identity for identity in old_identities if identity not in new_identities
    )
    assert structural.new_only == tuple(
        identity for identity in new_identities if identity not in old_identities
    )
    assert len(structural.old_only) == old_only
    assert len(structural.new_only) == new_only


def test_price_only_rule_change_is_canonical_evidence_not_source_reorder() -> None:
    result = _interpret([_day_rule("monday", 1)], [_day_rule("monday", 2)])
    assert result is not None and result.structural_comparison is not None

    assert result.structural_comparison.matches[0].old_source_index == 0
    assert result.structural_comparison.matches[0].new_source_index == 0
    assert result.structural_comparison.old_only == ()
    assert result.structural_comparison.new_only == ()
    assert result.structural_comparison.source_order_changed is False
    assert result.structural_comparison.canonical_evidence_changed is True
    assert result.canonical_evidence_changed is True


def test_parent_canonical_evidence_exists_when_structural_comparison_is_deferred() -> None:
    result = _interpret(None, [_day_rule("monday")])

    assert result is not None
    assert result.structural_comparison is None
    assert result.canonical_evidence_changed is True


@pytest.mark.parametrize(
    "days",
    ([], ["monday", "monday"], ["monday", "funday"], ["Monday"]),
)
def test_invalid_weekday_lists_fall_back(days: list[str]) -> None:
    result = _interpret(None, [{"utc_days": days, "prompt": 1}])

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "invalid_selector_value"


def test_empty_policy_is_valid_but_empty_rule_is_not() -> None:
    empty_policy = _interpret(None, [])
    empty_rule = _interpret(None, [{}])

    assert empty_policy is not None and empty_policy.new_policy is not None
    assert empty_policy.new_policy.rules == ()
    assert empty_rule is not None
    assert empty_rule.state == "raw-fallback"
    assert empty_rule.fallback_reason == "empty_rule"


@pytest.mark.parametrize("selector", ["utc_start", "utc_end"])
def test_endpoints_must_be_present_as_a_pair(selector: str) -> None:
    result = _interpret(None, [{selector: 100, "prompt": 1}])

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "missing_endpoint_pair"


@pytest.mark.parametrize("value", [True, -1, 1260, 2400, "0100"])
def test_hhmm_validation_is_descriptor_owned(value: Any) -> None:
    result = _interpret(None, [{"utc_start": value, "utc_end": 200, "prompt": 1}])

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "invalid_selector_value"


@pytest.mark.parametrize(
    ("start", "end", "minutes", "display"),
    (
        (0, 100, (0, 60), ("00:00", "01:00")),
        (1000, 0, (600, 0), ("10:00", "24:00")),
        (2200, 200, (1320, 120), ("22:00", "02:00")),
    ),
)
def test_valid_endpoint_shapes_preserve_general_wrap_without_compiling_it(
    start: int,
    end: int,
    minutes: tuple[int, int],
    display: tuple[str, str],
) -> None:
    result = _interpret(None, [{"utc_start": start, "utc_end": end, "prompt": 1}])
    assert result is not None and result.new_policy is not None
    rule = result.new_policy.rules[0]

    assert (rule.start_minute, rule.end_minute) == minutes
    endpoint_conditions = [
        condition
        for condition in rule.conditions
        if condition.semantic_role in {"utc_start_inclusive", "utc_end_exclusive"}
    ]
    assert tuple(condition.display_value for condition in endpoint_conditions) == display


def test_equal_endpoints_are_unsupported() -> None:
    result = _interpret(None, [{"utc_start": 100, "utc_end": 100, "prompt": 1}])

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "equal_endpoints_unsupported"


def test_conditions_within_one_rule_are_an_explicit_conjunction() -> None:
    result = _interpret(
        None,
        [
            {
                "min_prompt_tokens": 10,
                "utc_days": ["monday"],
                "utc_start": 100,
                "utc_end": 200,
                "prompt": 1,
            }
        ],
    )
    assert result is not None and result.new_policy is not None
    rule = result.new_policy.rules[0]

    assert rule.condition_combination == "all_conditions"
    assert {condition.semantic_role for condition in rule.conditions} == {
        "integer_strictly_greater",
        "utc_weekdays",
        "utc_start_inclusive",
        "utc_end_exclusive",
    }


@pytest.mark.parametrize(
    ("rule", "reason"),
    (
        ({"synthetic_region_selector": ["region-a"], "prompt": 1}, "unknown_rule_key"),
        ({"synthetic_note": {"text": "not a condition"}, "prompt": 1}, "unknown_rule_key"),
        ({"unregistered_price": 7}, "unresolved_price_dimension"),
    ),
)
def test_unknown_rule_vocabulary_fails_closed_with_stable_codes(
    rule: dict[str, Any],
    reason: str,
) -> None:
    result = _interpret(None, [rule])

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == reason


def test_legacy_selector_is_consumed_as_nonmoney_but_has_no_borrowed_semantics() -> None:
    legacy_profile = ProviderProfile(
        kind="legacy-synthetic",
        pricing_override_condition_fields=("legacy_selector",),
        pricing_override_policy_semantics=ConditionalPricingPolicySemantics(
            condition_combination="all_conditions",
            rule_precedence="later_per_key",
            omitted_price_behavior="retain_prior_or_base",
            top_level_price_role="default_base",
        ),
        pricing_override_condition_set_semantics=ConditionalPricingConditionSetSemantics(
            missing_weekdays="all_seven",
            missing_endpoints="all_day",
            endpoint_pairing="both_or_neither",
            equal_endpoints="unsupported",
        ),
        pricing_override_base_paths={"prompt": "pricing.prompt"},
    )
    result = _interpret(None, [{"legacy_selector": 5, "prompt": 1}], profile=legacy_profile)

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "selector_semantics_unavailable"
    assert result.source_changes[0].new_value[0]["legacy_selector"] == 5


def _integer(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("synthetic selector requires integer")
    return value


def _weekdays(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("synthetic weekdays require a list")
    if len(set(value)) != len(value) or any(day not in ALL_WEEKDAYS for day in value):
        raise ValueError("synthetic weekdays invalid")
    return tuple(day for day in ALL_WEEKDAYS if day in value)


def _minute(value: Any) -> int:
    raw = _integer(value)
    hour, minute = divmod(raw, 100)
    if raw < 0 or hour > 23 or minute > 59:
        raise ValueError("synthetic HHMM invalid")
    return hour * 60 + minute


def _alternate_profile() -> ProviderProfile:
    descriptors = {
        "minimum_input_units": ConditionalPricingConditionDescriptor(
            "minimum_input_units",
            "threshold",
            "integer_strictly_greater",
            _integer,
            _integer,
            lambda value: f"Input units > {value}",
            False,
        ),
        "days_utc": ConditionalPricingConditionDescriptor(
            "days_utc", "time", "utc_weekdays", _weekdays, tuple, lambda value: ",".join(value), True
        ),
        "from_utc": ConditionalPricingConditionDescriptor(
            "from_utc", "time", "utc_start_inclusive", _minute, _integer, lambda value: f"{value // 60:02d}:{value % 60:02d}", True
        ),
        "until_utc": ConditionalPricingConditionDescriptor(
            "until_utc", "time", "utc_end_exclusive", _minute, _integer, lambda value: "24:00" if value == 0 else f"{value // 60:02d}:{value % 60:02d}", True
        ),
    }
    return ProviderProfile(
        kind="alternate-synthetic",
        price_leaf_rules={
            "prompt_rate": PriceDisplayRule(
                unit_label="/synthetic input unit",
                multiplier=1,
                divisor=1,
                comparison_group="usd_per_synthetic_input_unit",
            )
        },
        pricing_override_condition_fields=(),
        pricing_override_condition_descriptors=descriptors,
        pricing_override_condition_set_semantics=ConditionalPricingConditionSetSemantics(
            "all_seven", "all_day", "both_or_neither", "unsupported"
        ),
        pricing_override_policy_semantics=ConditionalPricingPolicySemantics(
            "all_conditions", "later_per_key", "retain_prior_or_base", "default_base"
        ),
        pricing_override_base_paths={"prompt_rate": "pricing.prompt_rate"},
    )


def _same_basis_ratio_profile() -> ProviderProfile:
    """Two synthetic dimensions with one comparable basis and unlike factors."""
    profile = _alternate_profile()
    return replace(
        profile,
        price_leaf_rules={
            "prompt_rate": PriceDisplayRule(
                unit_label="/synthetic comparable unit",
                multiplier=1,
                divisor=1,
                comparison_group="usd_per_synthetic_comparable_unit",
            ),
            "completion_rate": PriceDisplayRule(
                unit_label="/synthetic comparable unit",
                multiplier=1_000,
                divisor=1,
                comparison_group="usd_per_synthetic_comparable_unit",
            ),
        },
        pricing_override_base_paths={
            "prompt_rate": "pricing.prompt_rate",
            "completion_rate": "pricing.completion_rate",
        },
    )


def _exact_price_profile(
    *, comparison_group: str | None = "synthetic_exact"
) -> ProviderProfile:
    return replace(
        OPENROUTER_PROFILE,
        price_leaf_rules={
            **OPENROUTER_PROFILE.price_leaf_rules,
            "prompt": PriceDisplayRule(
                unit_label="/synthetic exact unit",
                multiplier=1,
                divisor=1,
                comparison_group=comparison_group,
            ),
        },
    )


def _ratio_metadata(
    overrides: list[dict[str, Any]],
    *,
    prompt_rate: str = "1.0",
    completion_rate: str = "0.0010",
) -> dict[str, Any]:
    return {
        "id": MODEL_ID,
        "pricing": {
            "prompt_rate": prompt_rate,
            "completion_rate": completion_rate,
            "overrides": overrides,
        },
    }


def _profile_with_weekday_callbacks(
    *,
    parse_value=_weekdays,
    canonical_identity=tuple,
    format_value=lambda value: ",".join(value),
) -> ProviderProfile:
    profile = _alternate_profile()
    descriptors = dict(profile.pricing_override_condition_descriptors)
    descriptors["days_utc"] = ConditionalPricingConditionDescriptor(
        "days_utc",
        "time",
        "utc_weekdays",
        parse_value,
        canonical_identity,
        format_value,
        True,
    )
    return replace(profile, pricing_override_condition_descriptors=descriptors)


@pytest.mark.parametrize(
    ("exception_type", "message"),
    (
        (TypeError, "synthetic broken type"),
        (KeyError, "synthetic broken key"),
        (OverflowError, "synthetic broken overflow"),
    ),
)
def test_descriptor_callback_invariant_failures_propagate(
    exception_type: type[Exception],
    message: str,
) -> None:
    def broken_parse(_value: Any) -> Any:
        raise exception_type(message)

    with pytest.raises(exception_type, match=message):
        _interpret(
            None,
            [{"days_utc": ["monday"], "prompt_rate": 1}],
            profile=_profile_with_weekday_callbacks(parse_value=broken_parse),
        )


def test_unhashable_canonical_identity_is_a_programming_invariant_failure() -> None:
    with pytest.raises(TypeError, match="hashable"):
        _interpret(
            None,
            [{"days_utc": ["monday"], "prompt_rate": 1}],
            profile=_profile_with_weekday_callbacks(
                canonical_identity=lambda _value: ["synthetic-broken-identity"]
            ),
        )


def test_nonstring_formatted_selector_is_a_programming_invariant_failure() -> None:
    with pytest.raises(TypeError, match="formatted selector"):
        _interpret(
            None,
            [{"days_utc": ["monday"], "prompt_rate": 1}],
            profile=_profile_with_weekday_callbacks(format_value=lambda _value: 7),
        )


def test_price_rule_resolver_invariant_failure_is_not_raw_fallback() -> None:
    profile = replace(
        _alternate_profile(),
        price_multiplier=0,
        price_leaf_rules={
            "prompt_rate": PriceDisplayRule(
                unit_label="/synthetic input unit",
                comparison_group="usd_per_synthetic_input_unit",
            )
        },
    )

    with pytest.raises(ValueError, match="effective price factors"):
        _interpret(
            None,
            [{"days_utc": ["monday"], "prompt_rate": 1}],
            profile=profile,
        )


def test_alternate_raw_names_compile_through_semantic_roles() -> None:
    result = _interpret(
        None,
        [
            {
                "minimum_input_units": 10,
                "days_utc": ["friday", "monday"],
                "from_utc": 2200,
                "until_utc": 200,
                "prompt_rate": "0.000004",
            }
        ],
        profile=_alternate_profile(),
    )
    assert result is not None and result.new_policy is not None
    rule = result.new_policy.rules[0]

    assert rule.utc_weekdays == ("monday", "friday")
    assert (rule.start_minute, rule.end_minute) == (1320, 120)
    assert tuple(assignment.dimension for assignment in rule.explicit_prices) == ("prompt_rate",)
    assert tuple(condition.semantic_role for condition in rule.conditions) == (
        "integer_strictly_greater",
        "utc_weekdays",
        "utc_start_inclusive",
        "utc_end_exclusive",
    )


def test_base_path_without_resolved_price_rule_falls_back() -> None:
    profile = ProviderProfile(
        kind="unmatched-price-synthetic",
        pricing_override_condition_fields=(),
        pricing_override_condition_descriptors=(
            _alternate_profile().pricing_override_condition_descriptors
        ),
        pricing_override_condition_set_semantics=(
            _alternate_profile().pricing_override_condition_set_semantics
        ),
        pricing_override_policy_semantics=_alternate_profile().pricing_override_policy_semantics,
        pricing_override_base_paths={"prompt_rate": "pricing.prompt_rate"},
    )

    result = _interpret(
        None,
        [{"days_utc": ["monday"], "prompt_rate": "0.000004"}],
        profile=profile,
    )

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "unresolved_price_dimension"
    assert result.new_policy is None


def test_matched_exact_base_path_rule_without_comparison_group_stays_parsed() -> None:
    profile = replace(
        _alternate_profile(),
        price_leaf_rules={},
        price_path_rules={
            "pricing.prompt_rate": PriceDisplayRule(
                unit_label="/synthetic input unit",
                multiplier=1,
                divisor=1,
            )
        },
    )

    result = _interpret(
        None,
        [{"days_utc": ["monday"], "prompt_rate": "0.000004"}],
        profile=profile,
    )

    assert result is not None and result.new_policy is not None
    assert result.state == "ordered-rules"
    assignment = result.new_policy.rules[0].explicit_prices[0]
    assert assignment.price_rule.match_source == "path"
    assert assignment.price_rule.unit_label == "/synthetic input unit"
    assert assignment.price_rule.comparison_group is None
    assert result.comparison is None
    assert "missing_price_comparison_group" in result.comparison_inhibition_reasons


def test_matched_price_rule_with_nonnumeric_assignment_falls_back() -> None:
    result = _interpret(
        None,
        [{"days_utc": ["monday"], "prompt_rate": "not-a-number"}],
        profile=_alternate_profile(),
    )

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "unresolved_price_dimension"


@pytest.mark.parametrize(
    "raw_value",
    (
        "1e-1000000",
        "1." + ("2" * 1_000),
    ),
)
def test_resource_amplifying_price_assignment_falls_back_as_unresolved(
    raw_value: str,
) -> None:
    result = _interpret(
        None,
        [{"days_utc": ["monday"], "prompt_rate": raw_value}],
        profile=_alternate_profile(),
    )

    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "unresolved_price_dimension"
    assert result.new_policy is None
    assert result.comparison is None


def test_price_assignment_must_survive_complete_provider_normalization() -> None:
    policy = [{"utc_days": ["monday"], "prompt": "1e308"}]

    result = _interpret_complete(None, policy)

    assert conditional_pricing.resolve_price_value(
        "pricing.prompt", "1e308", OPENROUTER_PROFILE
    ) is None
    assert result is not None
    assert result.state == "raw-fallback"
    assert result.fallback_reason == "unresolved_price_dimension"
    assert result.new_policy is None
    assert result.new_compiled_policy is None
    assert result.comparison is None


def test_exact_underflow_assignment_survives_complete_provider_normalization() -> None:
    policy = [{"utc_days": ["monday"], "prompt": "1e-400"}]

    result = _interpret_complete(None, policy)

    assert result is not None and result.new_policy is not None
    assert result.state == "grouped-schedule"
    assignment = result.new_policy.rules[0].explicit_prices[0]
    assert assignment.raw_value == "1e-400"
    assert result.new_compiled_policy is not None
    assert len(result.new_compiled_policy.effective_bands) == 2


def test_missing_event_snapshot_inhibits_grouping_and_comparison_but_not_parsing() -> None:
    result = _interpret(
        None,
        [{"utc_days": ["monday"], "prompt": 1}],
        old_metadata=None,
        new_metadata=_complete_metadata([{"utc_days": ["monday"], "prompt": 1}]),
    )

    assert result is not None and result.new_policy is not None
    assert result.state == "ordered-rules"
    assert result.fallback_reason is None
    assert "missing_event_snapshot" in result.grouping_inhibition_reasons
    assert "missing_event_snapshot" in result.comparison_inhibition_reasons
    assert result.comparison is None
    assert result.absorbed_base_price_changes == ()


def test_duplicate_rules_match_by_canonical_condition_identity_and_occurrence() -> None:
    old = [
        {"utc_days": ["monday"], "prompt": 1},
        {"utc_days": ["monday"], "prompt": 2},
    ]
    new = [
        {"utc_days": ["monday"], "prompt": 3},
        {"utc_days": ["monday"], "prompt": 4},
    ]
    result = _interpret(old, new)
    assert result is not None and result.old_policy and result.new_policy

    assert [rule.condition_occurrence for rule in result.old_policy.rules] == [0, 1]
    assert [rule.condition_occurrence for rule in result.new_policy.rules] == [0, 1]
    assert [
        (match.identity.occurrence, match.old_source_index, match.new_source_index)
        for match in result.structural_comparison.matches  # type: ignore[union-attr]
    ] == [(0, 0, 0), (1, 1, 1)]


def test_selector_occurrence_and_rule_source_indices_are_preserved() -> None:
    result = _interpret(
        None,
        [
            {"utc_days": ["monday"], "prompt": 1},
            {"utc_days": ["monday"], "prompt": 2},
        ],
    )
    assert result is not None and result.new_policy is not None

    rules = result.new_policy.rules
    assert [rule.source_index for rule in rules] == [0, 1]
    weekday_conditions = [rule.conditions[0] for rule in rules]
    assert [condition.occurrence for condition in weekday_conditions] == [0, 1]
    assert [condition.source_rule_index for condition in weekday_conditions] == [0, 1]


def test_source_provenance_uses_canonical_values_and_value_transition_occurrence() -> None:
    first = FieldChange("pricing.overrides", None, [{"prompt": 1, "utc_days": ["monday"]}])
    distinct = FieldChange("pricing.overrides", None, [{"prompt": 2}])
    repeat = FieldChange("pricing.overrides", None, [{"utc_days": ["monday"], "prompt": 1}])
    result = interpret_conditional_pricing(_event(first, distinct, repeat), OPENROUTER_PROFILE)
    assert result is not None

    references = [source.reference for source in result.source_changes]
    assert [reference.occurrence for reference in references] == [0, 0, 1]
    assert references[0].new_value_canonical_json == references[2].new_value_canonical_json
    assert references[0].new_value_canonical_json == '[{"prompt":1,"utc_days":["monday"]}]'
    assert [reference.source_index for reference in references] == [0, 1, 2]


def test_event_identity_consistency_and_identity_types_are_frozen() -> None:
    live = LiveComparisonIdentity(PROVIDER_ID, MODEL_ID, None, 11)
    stored = StoredComparisonIdentity(PROVIDER_ID, MODEL_ID, None, 12)
    assert live != stored

    with pytest.raises(ValueError, match="identity provider"):
        _event(identity=LiveComparisonIdentity("other-provider", MODEL_ID, None, 11))
    with pytest.raises(ValueError, match="identity model"):
        _event(identity=StoredComparisonIdentity(PROVIDER_ID, "other/model", None, 12))
    with pytest.raises(FrozenInstanceError):
        live.provider_id = "changed"  # type: ignore[misc]


def test_event_and_result_defensively_freeze_input_json() -> None:
    rule = {"utc_days": ["monday"], "prompt": 1}
    old_metadata = _complete_metadata(None)
    new_metadata = _complete_metadata([rule])
    event = _event(
        FieldChange("pricing.overrides", None, [rule]),
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )
    rule["prompt"] = 999
    new_metadata["pricing"]["prompt"] = "changed"
    result = interpret_conditional_pricing(event, OPENROUTER_PROFILE)
    assert result is not None and result.new_policy is not None

    assert result.new_policy.rules[0].explicit_prices[0].raw_value == 1
    assert event.new_model_metadata["pricing"]["prompt"] == "0.000001"  # type: ignore[index]
    with pytest.raises(TypeError):
        event.new_model_metadata["pricing"]["prompt"] = "mutated"  # type: ignore[index]


def test_generic_parser_source_contains_no_openrouter_raw_selector_names() -> None:
    source = (Path(__file__).parents[1] / "model_sentinel" / "conditional_pricing.py").read_text()
    string_constants = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    forbidden_names = {"min_prompt_tokens", "utc_days", "utc_start", "utc_end"}
    assert string_constants.isdisjoint(forbidden_names)


def test_reason_code_types_cover_every_task_two_emission() -> None:
    assert set(get_args(FallbackReason)) == {
        "multiple_parent_changes",
        "malformed_parent_transition",
        "invalid_policy_type",
        "missing_policy_semantics",
        "missing_condition_set_semantics",
        "malformed_rule",
        "empty_rule",
        "selector_semantics_unavailable",
        "unresolved_price_dimension",
        "unknown_rule_key",
        "missing_price_assignment",
        "invalid_selector_value",
        "missing_endpoint_pair",
        "equal_endpoints_unsupported",
        "multiple_policy_errors",
    }
    assert set(get_args(GroupingInhibitionReason)) == {
        "comparison_requires_ordered_rules",
        "duplicate_semantic_condition",
        "incomplete_base_vector",
        "missing_event_snapshot",
        "non_time_condition",
        "overlapping_weekly_coverage",
    }
    assert set(get_args(ComparisonInhibitionReason)) == {
        "incomplete_base_vector",
        "missing_event_snapshot",
        "missing_price_comparison_group",
        "ordered_rules",
        "raw_fallback",
        "partition_mismatch",
        "incompatible_price_basis",
        "incomplete_comparison_vector",
    }


def _vector_raw_values(vector: EffectivePriceVector | None) -> dict[str, Any] | None:
    if vector is None:
        return None
    return {entry.dimension: entry.raw_value for entry in vector.entries}


def _window_rule(
    day: str,
    start: int,
    end: int,
    **prices: Any,
) -> dict[str, Any]:
    return {
        "utc_days": [day],
        "utc_start": start,
        "utc_end": end,
        **prices,
    }


def test_weekly_segments_are_half_open_and_wrap_on_the_same_selected_day() -> None:
    coverage = compile_weekly_segments(("friday",), 1320, 120)

    assert coverage == (
        WeeklySegment(4, 0, 120),
        WeeklySegment(4, 1320, 1440),
    )
    assert weekly_coverage_contains(coverage, 4, 0)
    assert weekly_coverage_contains(coverage, 4, 119)
    assert not weekly_coverage_contains(coverage, 4, 120)
    assert not weekly_coverage_contains(coverage, 4, 1319)
    assert weekly_coverage_contains(coverage, 4, 1320)
    assert weekly_coverage_contains(coverage, 4, 1439)
    assert not weekly_coverage_contains(coverage, 5, 60)


def test_each_selected_day_receives_its_own_wrapping_segments() -> None:
    coverage = compile_weekly_segments(("friday", "saturday"), 1320, 120)

    assert coverage == (
        WeeklySegment(4, 0, 120),
        WeeklySegment(4, 1320, 1440),
        WeeklySegment(5, 0, 120),
        WeeklySegment(5, 1320, 1440),
    )
    assert weekly_coverage_contains(coverage, 5, 60)


def test_weekly_segments_cover_sunday_all_days_and_selected_all_day() -> None:
    assert compile_weekly_segments(("sunday",), 60, 120) == (
        WeeklySegment(6, 60, 120),
    )
    assert compile_weekly_segments(ALL_WEEKDAYS, 0, 1440) == tuple(
        WeeklySegment(day, 0, 1440) for day in range(7)
    )
    assert compile_weekly_segments(("wednesday",), 0, 1440) == (
        WeeklySegment(2, 0, 1440),
    )


def test_weekly_overlap_excludes_adjacency_and_detects_positive_measure() -> None:
    first = (WeeklySegment(0, 0, 60),)
    adjacent = (WeeklySegment(0, 60, 240),)
    overlapping = (WeeklySegment(0, 59, 120),)
    other_day = (WeeklySegment(1, 30, 90),)

    assert not weekly_segments_overlap(first, adjacent)
    assert weekly_segments_overlap(first, overlapping)
    assert not weekly_segments_overlap(first, other_day)


def test_weekly_complement_is_complete_and_deterministic() -> None:
    covered = (
        WeeklySegment(0, 0, 60),
        WeeklySegment(0, 120, 1440),
        WeeklySegment(6, 0, 1440),
    )

    complement = weekly_complement(covered)

    assert complement == (
        WeeklySegment(0, 60, 120),
        *(WeeklySegment(day, 0, 1440) for day in range(1, 6)),
    )
    assert weekly_complement((*covered, *complement)) == ()


def test_weekly_partition_is_bounded_by_the_finite_minute_domain() -> None:
    coverage_sets = tuple(
        (WeeklySegment(day, minute, minute + 1),)
        for day in range(7)
        for minute in range(0, 1440, 3)
    )

    partition = partition_weekly_segments(*coverage_sets)

    assert partition == tuple(sorted(partition))
    assert len(partition) <= 7 * 1440


def test_weekly_partition_uses_exact_sorted_endpoints_and_is_contiguous() -> None:
    partition = partition_weekly_segments(
        (WeeklySegment(0, 60, 180),),
        (WeeklySegment(0, 120, 240), WeeklySegment(2, 600, 720)),
    )

    assert partition == (
        WeeklySegment(0, 0, 60),
        WeeklySegment(0, 60, 120),
        WeeklySegment(0, 120, 180),
        WeeklySegment(0, 180, 240),
        WeeklySegment(0, 240, 1440),
        WeeklySegment(1, 0, 1440),
        WeeklySegment(2, 0, 600),
        WeeklySegment(2, 600, 720),
        WeeklySegment(2, 720, 1440),
        *(WeeklySegment(day, 0, 1440) for day in range(3, 7)),
    )
    for left, right in zip(partition, partition[1:]):
        if left.weekday_index == right.weekday_index:
            assert left.end_minute == right.start_minute


def test_disjoint_complete_time_policy_compiles_grouped_schedule() -> None:
    new = [
        _window_rule("monday", 0, 100, prompt="0.000003"),
        _window_rule("monday", 100, 200, prompt="0.000004"),
    ]

    result = _interpret_complete(None, new)

    assert result is not None
    assert result.state == "grouped-schedule"
    assert result.fallback_reason is None
    assert result.grouping_inhibition_reasons == ()
    assert result.new_compiled_policy is not None
    compiled = result.new_compiled_policy
    assert [region.segment for region in compiled.grouped_regions] == [
        WeeklySegment(0, 0, 60),
        WeeklySegment(0, 60, 120),
    ]
    assert compiled.default_coverage[0] == WeeklySegment(0, 120, 1440)
    assert compiled.default_coverage[-1] == WeeklySegment(6, 0, 1440)


@pytest.mark.parametrize(
    ("rules", "reason"),
    (
        (
            [
                _window_rule("monday", 0, 200, prompt=3),
                _window_rule("monday", 100, 300, prompt=4),
            ],
            "overlapping_weekly_coverage",
        ),
        (
            [
                {"utc_days": ["monday"], "prompt": 3},
                {"utc_days": ["monday"], "prompt": 4},
            ],
            "duplicate_semantic_condition",
        ),
        ([{"min_prompt_tokens": 10, "prompt": 3}], "non_time_condition"),
        (
            [
                {
                    "utc_days": ["monday"],
                    "min_prompt_tokens": 10,
                    "prompt": 3,
                }
            ],
            "non_time_condition",
        ),
    ),
)
def test_understood_noncollapsible_policies_are_ordered_rules(
    rules: list[dict[str, Any]],
    reason: str,
) -> None:
    result = _interpret_complete(None, rules)

    assert result is not None
    assert result.state == "ordered-rules"
    assert result.fallback_reason is None
    assert reason in result.grouping_inhibition_reasons
    assert "ordered_rules" in result.comparison_inhibition_reasons
    assert result.new_compiled_policy is not None
    assert [
        compiled.source_rule.source_index
        for compiled in result.new_compiled_policy.ordered_rules
    ] == list(range(len(rules)))
    assert all(
        compiled.effective_prices is None
        for compiled in result.new_compiled_policy.ordered_rules
    )
    assert result.new_compiled_policy.grouped_regions == ()


def test_missing_snapshot_is_ordered_without_any_effective_vectors() -> None:
    new = [_window_rule("monday", 0, 100, prompt=3)]
    result = _interpret(
        None,
        new,
        old_metadata=None,
        new_metadata=_complete_metadata(new),
    )

    assert result is not None
    assert result.state == "ordered-rules"
    assert result.fallback_reason is None
    assert result.grouping_inhibition_reasons == ("missing_event_snapshot",)
    assert "missing_event_snapshot" in result.comparison_inhibition_reasons
    assert result.new_compiled_policy is not None
    assert result.new_compiled_policy.base_prices is None
    assert result.new_compiled_policy.effective_bands == ()
    assert result.new_compiled_policy.effective_partition == ()
    assert result.absorbed_base_price_changes == ()


def test_fallback_grouping_and_comparison_reasons_are_distinct_channels() -> None:
    raw = _interpret_complete(None, [{"synthetic_note": {"value": 3}, "prompt": 4}])
    ordered = _interpret_complete(None, [{"min_prompt_tokens": 10, "prompt": 4}])
    grouped = _interpret_complete(
        None,
        [_window_rule("monday", 0, 100, prompt=4)],
    )

    assert raw is not None and raw.state == "raw-fallback"
    assert raw.fallback_reason == "unknown_rule_key"
    assert raw.grouping_inhibition_reasons == ()
    assert raw.comparison_inhibition_reasons == ("raw_fallback",)
    assert ordered is not None and ordered.fallback_reason is None
    assert "non_time_condition" in ordered.grouping_inhibition_reasons
    assert "non_time_condition" not in ordered.comparison_inhibition_reasons
    assert grouped is not None and grouped.fallback_reason is None
    assert grouped.grouping_inhibition_reasons == ()
    assert grouped.comparison_inhibition_reasons == ()
    assert grouped.comparison is not None


def test_grouped_rules_preserve_explicit_and_base_inherited_effective_values() -> None:
    new = [
        _window_rule("monday", 0, 100, prompt="0.000003"),
        _window_rule("monday", 100, 200, completion="0.000004"),
    ]

    result = _interpret_complete(None, new)

    assert result is not None and result.new_compiled_policy is not None
    compiled = result.new_compiled_policy
    assert _vector_raw_values(compiled.base_prices) == {
        "completion": "0.000002",
        "prompt": "0.000001",
    }
    first, second = compiled.ordered_rules
    assert [assignment.dimension for assignment in first.source_rule.explicit_prices] == [
        "prompt"
    ]
    assert _vector_raw_values(first.effective_prices) == {
        "completion": "0.000002",
        "prompt": "0.000003",
    }
    assert _vector_raw_values(second.effective_prices) == {
        "completion": "0.000004",
        "prompt": "0.000001",
    }


def test_equal_effective_vectors_keep_regions_separate_but_share_one_band() -> None:
    new = [
        _window_rule("monday", 0, 100, prompt="0.000003"),
        _window_rule("tuesday", 0, 100, prompt="0.000003"),
    ]

    result = _interpret_complete(None, new)

    assert result is not None and result.new_compiled_policy is not None
    compiled = result.new_compiled_policy
    assert len(compiled.grouped_regions) == 2
    assert compiled.grouped_regions[0].effective_prices == compiled.grouped_regions[1].effective_prices
    rule_bands = [band for band in compiled.effective_bands if not band.includes_default]
    assert len(rule_bands) == 1
    assert rule_bands[0].coverage == (
        WeeklySegment(0, 0, 60),
        WeeklySegment(1, 0, 60),
    )


@pytest.mark.parametrize(
    ("left_value", "right_value", "canonically_distinct"),
    (
        (1, 1.0, True),
        (0.0, -0.0, True),
        (1.0, 1.0, False),
    ),
)
def test_effective_partition_bands_and_signature_use_canonical_numeric_identity(
    left_value: int | float,
    right_value: int | float,
    canonically_distinct: bool,
) -> None:
    old = [
        _window_rule("monday", 0, 100, prompt=left_value),
        _window_rule("monday", 100, 200, prompt=left_value),
    ]
    new = [
        _window_rule("monday", 0, 100, prompt=left_value),
        _window_rule("monday", 100, 200, prompt=right_value),
    ]

    result = _interpret_complete(old, new)

    assert result is not None and result.new_compiled_policy is not None
    compiled = result.new_compiled_policy
    monday_rule_cells = tuple(
        region
        for region in compiled.effective_partition
        if region.segment.weekday_index == 0 and region.segment.start_minute < 120
    )
    rule_bands = tuple(
        band for band in compiled.effective_bands if not band.includes_default
    )
    if canonically_distinct:
        assert tuple(cell.segment for cell in monday_rule_cells) == (
            WeeklySegment(0, 0, 60),
            WeeklySegment(0, 60, 120),
        )
        assert len(rule_bands) == 2
    else:
        assert tuple(cell.segment for cell in monday_rule_cells) == (
            WeeklySegment(0, 0, 120),
        )
        assert len(rule_bands) == 1
    assert result.semantic_change is canonically_distinct


def test_uncovered_default_counts_only_when_its_vector_is_distinct() -> None:
    distinct = _interpret_complete(
        None,
        [_window_rule("monday", 0, 100, prompt="0.000003")],
    )
    identical = _interpret_complete(
        None,
        [_window_rule("monday", 0, 100, prompt="0.000001")],
    )
    fully_covered = _interpret_complete(None, [{"prompt": "0.000003"}])

    assert distinct is not None and distinct.new_compiled_policy is not None
    assert len(distinct.new_compiled_policy.effective_bands) == 2
    assert identical is not None and identical.new_compiled_policy is not None
    assert len(identical.new_compiled_policy.effective_bands) == 1
    assert identical.new_compiled_policy.effective_bands[0].includes_default
    assert fully_covered is not None and fully_covered.new_compiled_policy is not None
    assert fully_covered.new_compiled_policy.default_coverage == ()
    assert len(fully_covered.new_compiled_policy.effective_bands) == 1


@pytest.mark.parametrize(
    "base_value",
    (None, True, False, "not-numeric", float("inf"), float("nan")),
)
def test_incomplete_or_invalid_exact_base_value_inhibits_grouping(
    base_value: Any,
) -> None:
    new = [_window_rule("monday", 0, 100, prompt=3)]
    pricing = {"completion": "0.000002", "overrides": new}
    if base_value is not None:
        pricing["prompt"] = base_value
    metadata = {"id": MODEL_ID, "pricing": pricing}

    result = _interpret_complete(None, new, new_metadata=metadata)

    assert result is not None and result.new_compiled_policy is not None
    assert result.state == "ordered-rules"
    assert result.fallback_reason is None
    assert result.grouping_inhibition_reasons == ("incomplete_base_vector",)
    assert "incomplete_base_vector" in result.comparison_inhibition_reasons
    assert result.new_compiled_policy.base_prices is None
    assert result.new_compiled_policy.effective_bands == ()


def test_empty_policy_compiles_a_full_week_empty_default_vector() -> None:
    result = _interpret_complete(None, [])

    assert result is not None and result.new_compiled_policy is not None
    compiled = result.new_compiled_policy
    assert result.state == "grouped-schedule"
    assert compiled.base_prices == EffectivePriceVector(())
    assert compiled.default_coverage == tuple(
        WeeklySegment(day, 0, 1440) for day in range(7)
    )
    assert len(compiled.effective_bands) == 1


def test_compiled_vector_keeps_each_dimension_unit_identity() -> None:
    profile = replace(
        _alternate_profile(),
        price_leaf_rules={
            "prompt_rate": PriceDisplayRule(
                unit_label="/synthetic input unit",
                multiplier=1,
                divisor=1,
                comparison_group="usd_per_synthetic_input_unit",
            ),
            "completion_rate": PriceDisplayRule(
                unit_label="/synthetic output unit",
                multiplier=1,
                divisor=1,
                comparison_group="usd_per_synthetic_output_unit",
            ),
        },
        pricing_override_base_paths={
            "prompt_rate": "pricing.prompt_rate",
            "completion_rate": "pricing.completion_rate",
        },
    )
    new = [
        {
            "days_utc": ["monday"],
            "prompt_rate": "0.000003",
            "completion_rate": "0.000004",
        }
    ]
    metadata = {
        "id": MODEL_ID,
        "pricing": {
            "prompt_rate": "0.000001",
            "completion_rate": "0.000002",
            "overrides": new,
        },
    }

    result = _interpret_complete(
        None,
        new,
        profile=profile,
        old_metadata={
            "id": MODEL_ID,
            "pricing": {
                "prompt_rate": "0.000001",
                "completion_rate": "0.000002",
            },
        },
        new_metadata=metadata,
    )

    assert result is not None and result.new_compiled_policy is not None
    assert [
        (entry.dimension, entry.price_rule.unit_label)
        for entry in result.new_compiled_policy.base_prices.entries  # type: ignore[union-attr]
    ] == [
        ("completion_rate", "/synthetic output unit"),
        ("prompt_rate", "/synthetic input unit"),
    ]


def test_disjoint_source_reorder_is_evidence_only_semantic_noise() -> None:
    old = [_day_rule("monday", 3), _day_rule("tuesday", 4)]
    new = [_day_rule("tuesday", 4), _day_rule("monday", 3)]

    result = _interpret_complete(old, new)

    assert result is not None and result.structural_comparison is not None
    assert result.state == "grouped-schedule"
    assert result.structural_comparison.source_order_changed
    assert result.canonical_evidence_changed
    assert result.semantic_change is False
    assert result.comparison is None
    assert result.accounting is not None
    assert result.accounting.conditional_policy_count == 0
    assert result.accounting.model_bucket == "none"
    assert result.absorbed_base_price_changes == ()


@pytest.mark.parametrize(
    "rules",
    (
        (
            _window_rule("monday", 0, 200, prompt=3),
            _window_rule("monday", 100, 300, completion=4),
        ),
        (
            _window_rule("monday", 0, 200, prompt=3),
            _window_rule("monday", 100, 300, prompt=3),
        ),
    ),
)
def test_commuting_overlap_reorder_is_evidence_only_semantic_noise(
    rules: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    old = list(rules)
    new = list(reversed(rules))

    result = _interpret_complete(old, new)

    assert result is not None
    assert result.state == "ordered-rules"
    assert result.canonical_evidence_changed
    assert result.semantic_change is False


@pytest.mark.parametrize(
    "rules",
    (
        (
            _window_rule("monday", 0, 200, prompt=3),
            _window_rule("monday", 100, 300, prompt=4),
        ),
        (
            _window_rule("monday", 0, 200, prompt=3, completion=5),
            _window_rule("monday", 100, 300, prompt=3, completion=6),
        ),
    ),
)
def test_noncommuting_overlap_reorder_is_semantic(
    rules: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    result = _interpret_complete(list(rules), list(reversed(rules)))

    assert result is not None
    assert result.state == "ordered-rules"
    assert result.semantic_change is True


@pytest.mark.parametrize(
    ("old", "new"),
    (
        ([_day_rule("monday", 3)], [_day_rule("monday", 3), _day_rule("tuesday", 3)]),
        ([_day_rule("monday", 3), _day_rule("tuesday", 3)], [_day_rule("monday", 3)]),
        ([_day_rule("monday", 3)], [_day_rule("tuesday", 3)]),
        ([_day_rule("monday", 3)], [_day_rule("monday", 4)]),
    ),
)
def test_policy_insert_delete_condition_replace_and_value_change_are_semantic(
    old: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> None:
    result = _interpret_complete(old, new)

    assert result is not None
    assert result.semantic_change is True


def test_weekday_list_order_noise_preserves_parent_evidence_only() -> None:
    old = [{"utc_days": ["tuesday", "monday"], "prompt": 3}]
    new = [{"utc_days": ["monday", "tuesday"], "prompt": 3}]

    result = _interpret_complete(old, new)

    assert result is not None
    assert result.canonical_evidence_changed
    assert result.semantic_change is False


def test_raw_fallback_semantics_use_canonical_parent_evidence_change() -> None:
    changed = _interpret(
        [{"synthetic_unknown": 3}],
        [{"synthetic_unknown": 4}],
    )
    unchanged = _interpret(
        [{"synthetic_unknown": 3}],
        [{"synthetic_unknown": 3}],
    )

    assert changed is not None and changed.state == "raw-fallback"
    assert changed.semantic_change is True
    assert unchanged is not None and unchanged.state == "raw-fallback"
    assert unchanged.semantic_change is False


def test_base_vectors_use_union_dimensions_across_both_policy_sides() -> None:
    old = [{"utc_days": ["monday"], "prompt": "0.000003"}]
    new = [
        {
            "utc_days": ["monday"],
            "prompt": "0.000003",
            "completion": "0.000005",
        }
    ]
    old_metadata = {
        "id": MODEL_ID,
        "pricing": {
            "prompt": "0.000001",
            "completion": "0.000002",
            "overrides": old,
        },
    }
    new_metadata = {
        "id": MODEL_ID,
        "pricing": {
            "prompt": "0.000001",
            "completion": "0.000004",
            "overrides": new,
        },
    }

    result = _interpret_complete(
        old,
        new,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )

    assert result is not None
    assert result.state == "grouped-schedule"
    assert result.old_compiled_policy is not None
    assert result.new_compiled_policy is not None
    assert _vector_raw_values(result.old_compiled_policy.base_prices) == {
        "completion": "0.000002",
        "prompt": "0.000001",
    }
    assert _vector_raw_values(
        result.old_compiled_policy.ordered_rules[0].effective_prices
    ) == {
        "completion": "0.000002",
        "prompt": "0.000003",
    }
    assert _vector_raw_values(result.new_compiled_policy.base_prices) == {
        "completion": "0.000004",
        "prompt": "0.000001",
    }


def test_missing_base_for_cross_side_union_dimension_inhibits_both_sides() -> None:
    old = [{"utc_days": ["monday"], "prompt": "0.000003"}]
    new = [
        {
            "utc_days": ["monday"],
            "prompt": "0.000003",
            "completion": "0.000005",
        }
    ]
    old_metadata = {
        "id": MODEL_ID,
        "pricing": {"prompt": "0.000001", "overrides": old},
    }

    result = _interpret_complete(old, new, old_metadata=old_metadata)

    assert result is not None
    assert result.state == "ordered-rules"
    assert "incomplete_base_vector" in result.grouping_inhibition_reasons
    for compiled in (result.old_compiled_policy, result.new_compiled_policy):
        assert compiled is not None
        assert compiled.base_prices is None
        assert compiled.grouped_regions == ()
        assert compiled.default_coverage == ()
        assert compiled.effective_bands == ()
        assert compiled.effective_partition == ()
        assert all(rule.effective_prices is None for rule in compiled.ordered_rules)


@pytest.mark.parametrize("transition", ("added", "removed"))
def test_absent_policy_side_compiles_complete_default_over_union_dimensions(
    transition: str,
) -> None:
    policy = [{"utc_days": ["monday"], "prompt": "0.000003"}]
    old, new = (None, policy) if transition == "added" else (policy, None)
    old_metadata = {
        "id": MODEL_ID,
        "pricing": {"prompt": "0.000001", **({} if old is None else {"overrides": old})},
    }
    new_metadata = {
        "id": MODEL_ID,
        "pricing": {"prompt": "0.000002", **({} if new is None else {"overrides": new})},
    }

    result = _interpret_complete(
        old,
        new,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )

    assert result is not None
    assert result.state == "grouped-schedule"
    absent = (
        result.old_compiled_policy
        if transition == "added"
        else result.new_compiled_policy
    )
    present = (
        result.new_compiled_policy
        if transition == "added"
        else result.old_compiled_policy
    )
    assert absent is not None and absent.policy_present is False
    assert present is not None and present.policy_present is True
    assert absent.ordered_rules == ()
    assert _vector_raw_values(absent.base_prices) == {
        "prompt": "0.000001" if transition == "added" else "0.000002"
    }
    assert absent.default_coverage == tuple(
        WeeklySegment(day, 0, 1440) for day in range(7)
    )
    assert len(absent.effective_partition) == 7


@pytest.mark.parametrize(
    ("first", "second", "semantic_change"),
    (
        (
            {"utc_days": ["monday"], "prompt": 3},
            {"utc_days": ["monday"], "completion": 4},
            False,
        ),
        (
            {"utc_days": ["monday"], "prompt": 3},
            {"utc_days": ["monday"], "prompt": 3, "completion": 4},
            False,
        ),
        (
            {"utc_days": ["monday"], "prompt": 3},
            {"utc_days": ["monday"], "prompt": 4},
            True,
        ),
    ),
)
def test_duplicate_condition_reorder_matches_assignment_permutations_before_commutativity(
    first: dict[str, Any],
    second: dict[str, Any],
    semantic_change: bool,
) -> None:
    result = _interpret_complete([first, second], [second, first])

    assert result is not None
    assert result.state == "ordered-rules"
    assert result.canonical_evidence_changed
    assert result.semantic_change is semantic_change
    assert result.old_policy is not None and result.new_policy is not None
    assert [rule.condition_occurrence for rule in result.old_policy.rules] == [0, 1]
    assert [rule.condition_occurrence for rule in result.new_policy.rules] == [0, 1]


@pytest.mark.parametrize(
    ("old_prices", "new_order", "semantic_change"),
    (
        (
            ({"prompt": 3}, {"prompt": 3}, {"completion": 4}),
            (1, 2, 0),
            False,
        ),
        (
            (
                {"prompt": 3},
                {"completion": 4},
                {"prompt": 3, "completion": 4},
            ),
            (1, 2, 0),
            False,
        ),
        (
            ({"prompt": 3}, {"completion": 4}, {"prompt": 5}),
            (1, 2, 0),
            True,
        ),
    ),
)
def test_three_rule_duplicate_condition_permutations(
    old_prices: tuple[dict[str, int], ...],
    new_order: tuple[int, ...],
    semantic_change: bool,
) -> None:
    old = [{"utc_days": ["monday"], **prices} for prices in old_prices]
    new = [old[index] for index in new_order]

    result = _interpret_complete(old, new)

    assert result is not None
    assert result.state == "ordered-rules"
    assert result.canonical_evidence_changed
    assert result.semantic_change is semantic_change


def test_large_commuting_reorder_is_conservatively_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_overlap_queries = 0

    def unexpected_exact_overlap_query(*_args: Any, **_kwargs: Any) -> bool:
        nonlocal exact_overlap_queries
        exact_overlap_queries += 1
        raise AssertionError("large reorder must not enter pairwise overlap proof")

    monkeypatch.setattr(
        conditional_pricing,
        "weekly_segments_overlap",
        unexpected_exact_overlap_query,
    )
    monkeypatch.setattr(
        conditional_pricing,
        "_canonical_weekly_segments_overlap",
        unexpected_exact_overlap_query,
        raising=False,
    )
    rule_count = conditional_pricing.MAX_EXACT_REORDERED_RULE_COUNT + 1
    old = [
        {"min_prompt_tokens": threshold, "prompt": 3}
        for threshold in range(rule_count)
    ]
    new = list(reversed(old))

    result = _interpret_complete(old, new)

    assert result is not None
    assert result.state == "ordered-rules"
    assert result.semantic_change is True
    assert exact_overlap_queries == 0


@pytest.mark.parametrize("ordered_side", ("old", "new"))
def test_overall_ordered_state_suppresses_grouped_evidence_on_both_sides(
    ordered_side: str,
) -> None:
    grouped_policy = [
        _window_rule("monday", 0, 100, prompt=3),
        _window_rule("monday", 100, 200, prompt=4),
    ]
    overlapping_policy = [
        _window_rule("monday", 0, 200, prompt=3),
        _window_rule("monday", 100, 300, prompt=4),
    ]
    old, new = (
        (overlapping_policy, grouped_policy)
        if ordered_side == "old"
        else (grouped_policy, overlapping_policy)
    )

    result = _interpret_complete(old, new)

    assert result is not None
    assert result.state == "ordered-rules"
    assert "overlapping_weekly_coverage" in result.grouping_inhibition_reasons
    compiled_by_side = {
        "old": result.old_compiled_policy,
        "new": result.new_compiled_policy,
    }
    for side, compiled in compiled_by_side.items():
        assert compiled is not None
        assert compiled.base_prices is None
        assert compiled.grouping_inhibition_reasons
        if side == ordered_side:
            assert "overlapping_weekly_coverage" in (
                compiled.grouping_inhibition_reasons
            )
        else:
            assert compiled.grouping_inhibition_reasons == (
                "comparison_requires_ordered_rules",
            )
        assert compiled.grouped_regions == ()
        assert compiled.default_coverage == ()
        assert compiled.effective_bands == ()
        assert compiled.effective_partition == ()
        assert all(rule.effective_prices is None for rule in compiled.ordered_rules)


@pytest.mark.parametrize("transition", ("split", "merge"))
def test_grouped_adjacent_split_merge_with_identical_explicit_maps_is_noise(
    transition: str,
) -> None:
    whole = [{"utc_days": ["monday"], "prompt": "0.000003"}]
    split = [
        _window_rule("monday", 0, 1200, prompt="0.000003"),
        _window_rule("monday", 1200, 0, prompt="0.000003"),
    ]
    old, new = (whole, split) if transition == "split" else (split, whole)

    result = _interpret_complete(old, new)

    assert result is not None
    assert result.state == "grouped-schedule"
    assert result.canonical_evidence_changed
    assert result.structural_comparison is not None
    assert result.structural_comparison.old_only
    assert result.structural_comparison.new_only
    assert result.semantic_change is False


@pytest.mark.parametrize("transition", ("added", "removed"))
def test_grouped_explicit_equal_to_base_differs_from_default_omission(
    transition: str,
) -> None:
    omitted: list[dict[str, Any]] = []
    explicit = [{"prompt": "0.000001"}]
    old, new = (omitted, explicit) if transition == "added" else (explicit, omitted)

    result = _interpret_complete(old, new)

    assert result is not None
    assert result.state == "grouped-schedule"
    assert result.semantic_change is True


def test_grouped_split_with_one_omitted_key_changes_explicit_assignment_function() -> None:
    whole = [
        {
            "utc_days": ["monday"],
            "prompt": "0.000001",
            "completion": "0.000004",
        }
    ]
    split = [
        _window_rule(
            "monday",
            0,
            1200,
            prompt="0.000001",
            completion="0.000004",
        ),
        _window_rule("monday", 1200, 0, completion="0.000004"),
    ]

    result = _interpret_complete(whole, split)

    assert result is not None
    assert result.state == "grouped-schedule"
    assert (
        result.old_compiled_policy is not None
        and result.new_compiled_policy is not None
    )
    assert (
        result.old_compiled_policy.effective_partition
        == result.new_compiled_policy.effective_partition
    )
    assert result.semantic_change is True


# ---------------------------------------------------------------------------
# Task 4: bounded movement, sibling absorption, and central accounting
# ---------------------------------------------------------------------------


def _interpret_event(
    old_policy: Any,
    new_policy: Any,
    *,
    old_metadata: dict[str, Any] | None,
    new_metadata: dict[str, Any] | None,
    siblings: tuple[FieldChange, ...] = (),
    profile: ProviderProfile = OPENROUTER_PROFILE,
):
    event = _event(
        FieldChange("pricing.overrides", old_policy, new_policy),
        *siblings,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )
    return event, interpret_conditional_pricing(event, profile)


def test_grouped_schedule_vs_complete_default_emits_exact_band_facts() -> None:
    old_metadata, new_metadata = synthetic_scheduled_rate_models()
    new_policy = new_metadata["pricing"]["overrides"]

    _event_value, result = _interpret_event(
        None,
        new_policy,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )

    assert result is not None
    assert isinstance(result.comparison, ConditionalPricingComparison)
    assert result.comparison.mode == "grouped-vs-default"
    assert result.comparison.aggregate_direction is None
    assert result.comparison.inhibition_reasons == ("incompatible_price_basis",)
    assert len(result.comparison.bands) == 2
    by_dimension_direction = {
        next(iter({fact.direction for fact in band.dimensions})): band
        for band in result.comparison.bands
    }
    assert set(by_dimension_direction) == {"higher", "lower"}
    for direction, expected_percentage in (
        ("lower", -41.1764705882),
        ("higher", 17.6470588235),
    ):
        band = by_dimension_direction[direction]
        assert band.direction == "unknown"
        assert band.percentage is None
        assert all(fact.direction == direction for fact in band.dimensions)
        assert all(
            fact.percentage == pytest.approx(expected_percentage)
            for fact in band.dimensions
        )
        assert len(
            {
                (fact.unit_label, fact.comparison_group)
                for fact in band.dimensions
            }
        ) == 2
    assert by_dimension_direction["higher"].is_peak is True
    assert by_dimension_direction["lower"].is_peak is False
    for band in result.comparison.bands:
        assert {fact.dimension for fact in band.dimensions} == {
            "completion",
            "prompt",
            "request",
        }
        assert all(fact.old_value is not None for fact in band.dimensions)
        assert all(fact.new_value is not None for fact in band.dimensions)
        assert all(fact.delta is not None for fact in band.dimensions)


def test_same_partition_grouped_schedules_compare_per_dimension() -> None:
    old = [
        _window_rule(
            "monday",
            0,
            100,
            prompt="0.000003",
            completion="0.000004",
        )
    ]
    new = [
        _window_rule(
            "monday",
            0,
            100,
            prompt="0.000004",
            completion="0.000002",
        )
    ]
    old_metadata = _complete_metadata(old)
    new_metadata = _complete_metadata(new)
    old_metadata["pricing"]["completion"] = "0.000004"
    new_metadata["pricing"]["completion"] = "0.000002"

    _event_value, result = _interpret_event(
        old,
        new,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )

    assert result is not None and result.comparison is not None
    assert result.comparison.mode == "same-partition"
    assert result.comparison.inhibition_reasons == ()
    assert any(
        {fact.direction for fact in band.dimensions} == {"higher", "lower"}
        and band.direction == "mixed"
        for band in result.comparison.bands
    )


def test_partition_mismatch_keeps_only_exact_region_facts_and_no_envelope() -> None:
    old = [_window_rule("monday", 0, 100, prompt="0.000003")]
    new = [_window_rule("monday", 0, 200, prompt="0.000004")]

    _event_value, result = _interpret_event(
        old,
        new,
        old_metadata=_complete_metadata(old),
        new_metadata=_complete_metadata(new),
    )

    assert result is not None
    assert "partition_mismatch" in result.comparison_inhibition_reasons
    assert result.comparison is not None
    assert result.comparison.mode == "exact-regions"
    assert result.comparison.aggregate_direction is None
    assert "partition_mismatch" in result.comparison.inhibition_reasons
    assert any(
        segment.weekday_index == 0
        for band in result.comparison.bands
        for segment in band.coverage
    )


@pytest.mark.parametrize(
    ("directions", "expected"),
    (
        (("unchanged", "higher"), "higher"),
        (("unchanged", "lower"), "lower"),
        (("higher", "lower"), "mixed"),
        (("coverage", "unchanged"), "coverage"),
        (("coverage", "higher"), "unknown"),
        (("unknown", "higher"), "unknown"),
        (("unchanged", "unchanged"), "unchanged"),
    ),
)
def test_band_direction_contract_is_bounded(
    directions: tuple[str, ...],
    expected: str,
) -> None:
    assert conditional_pricing._movement_direction(directions) == expected


@pytest.mark.parametrize(
    "new_rule",
    (
        replace(
            OPENROUTER_PROFILE.price_leaf_rules["prompt"],
            unit_label="/synthetic incompatible unit",
        ),
        replace(
            OPENROUTER_PROFILE.price_leaf_rules["prompt"],
            comparison_group="synthetic_incompatible_group",
        ),
    ),
)
def test_dimension_comparison_rejects_mixed_unit_or_group(
    new_rule: PriceDisplayRule,
) -> None:
    old_rule = conditional_pricing.resolve_price_rule(
        "pricing.prompt", OPENROUTER_PROFILE
    )
    effective_new_rule = replace(
        old_rule,
        unit_label=new_rule.unit_label,
        comparison_group=new_rule.comparison_group,
    )
    fact = conditional_pricing._compare_dimension(
        "prompt",
        EffectivePriceValue("prompt", "0.000001", old_rule),
        EffectivePriceValue("prompt", "0.000002", effective_new_rule),
        OPENROUTER_PROFILE,
    )

    assert fact.direction == "unknown"
    assert fact.delta is None
    assert fact.percentage is None


@pytest.mark.parametrize(
    ("old_policy", "new_policy", "metadata_mode", "reason"),
    (
        (
            [{"min_prompt_tokens": 10, "prompt": "0.000003"}],
            [{"min_prompt_tokens": 10, "prompt": "0.000004"}],
            "complete",
            "ordered_rules",
        ),
        ([{"unknown_selector": 1, "prompt": "0.000003"}], None, "complete", "raw_fallback"),
        (None, [_window_rule("monday", 0, 100, prompt="0.000003")], "missing", "missing_event_snapshot"),
    ),
)
def test_unprovable_states_inhibit_comparison_without_inventing_direction(
    old_policy: Any,
    new_policy: Any,
    metadata_mode: str,
    reason: str,
) -> None:
    old_metadata = _complete_metadata(old_policy) if metadata_mode == "complete" else None
    new_metadata = _complete_metadata(new_policy) if metadata_mode == "complete" else None

    _event_value, result = _interpret_event(
        old_policy,
        new_policy,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )

    assert result is not None
    assert result.comparison is None
    assert reason in result.comparison_inhibition_reasons


def test_zero_basis_knows_direction_but_never_divides_by_zero() -> None:
    policy = [_window_rule("monday", 0, 100, prompt="0.000001")]
    old_metadata = _complete_metadata(None)
    new_metadata = _complete_metadata(policy)
    old_metadata["pricing"]["prompt"] = -0.0
    new_metadata["pricing"]["prompt"] = 0

    _event_value, result = _interpret_event(
        None,
        policy,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )

    assert result is not None and result.comparison is not None
    higher = next(
        fact
        for band in result.comparison.bands
        for fact in band.dimensions
        if fact.dimension == "prompt" and fact.direction == "higher"
    )
    assert higher.old_value is not None and higher.old_value.raw_display == "-0.0"
    assert higher.new_value is not None
    assert higher.percentage is None


def test_equal_numeric_int_float_is_unchanged_but_raw_identity_is_preserved() -> None:
    fact = resolve_direct_price_movement(
        "pricing.request",
        1,
        1.0,
        OPENROUTER_PROFILE,
    )

    assert isinstance(fact, DirectPriceMovementFact)
    assert fact.direction == "unchanged"
    assert fact.old_value is not None and fact.old_value.raw_display == "1"
    assert fact.new_value is not None and fact.new_value.raw_display == "1.0"
    assert fact.delta == 0.0
    assert fact.percentage == 0.0


@pytest.mark.parametrize(
    ("old_value", "new_value"),
    ((None, "0.02"), ("0.02", None)),
)
def test_direct_one_sided_price_is_coverage_without_arithmetic(
    old_value: Any,
    new_value: Any,
) -> None:
    fact = resolve_direct_price_movement(
        "pricing.request", old_value, new_value, OPENROUTER_PROFILE
    )

    assert fact is not None
    assert fact.direction == "coverage"
    assert fact.delta is None
    assert fact.percentage is None


def test_unequal_dimension_percentages_do_not_emit_band_percentage() -> None:
    old = [_window_rule("monday", 0, 100, prompt="0.000002", completion="0.000004")]
    new = [_window_rule("monday", 0, 100, prompt="0.000004", completion="0.000006")]

    _event_value, result = _interpret_event(
        old,
        new,
        old_metadata=_complete_metadata(old),
        new_metadata=_complete_metadata(new),
    )

    assert result is not None and result.comparison is not None
    changed_band = next(
        band
        for band in result.comparison.bands
        if {fact.percentage for fact in band.dimensions} == {50.0, 100.0}
    )
    assert changed_band.direction == "higher"
    assert changed_band.percentage is None


@pytest.mark.parametrize(
    ("completion_new", "expected_band_percentage"),
    (
        ("0.002000", 100.0),
        ("0.0020000000000005001", None),
    ),
)
def test_band_percentage_requires_exact_normalized_ratio_identity(
    completion_new: str,
    expected_band_percentage: float | None,
) -> None:
    profile = _same_basis_ratio_profile()
    old = [
        {
            "days_utc": ["monday"],
            "prompt_rate": "1.0",
            "completion_rate": "0.00100",
        }
    ]
    new = [
        {
            "days_utc": ["monday"],
            "prompt_rate": "2.00",
            "completion_rate": completion_new,
        }
    ]

    _event_value, result = _interpret_event(
        old,
        new,
        old_metadata=_ratio_metadata(old),
        new_metadata=_ratio_metadata(new),
        profile=profile,
    )

    assert result is not None and result.comparison is not None
    changed_band = next(
        band
        for band in result.comparison.bands
        if band.dimensions
        and all(fact.direction == "higher" for fact in band.dimensions)
    )
    assert changed_band.direction == "higher"
    assert changed_band.percentage == expected_band_percentage
    facts = {fact.dimension: fact for fact in changed_band.dimensions}
    assert facts["prompt_rate"].percentage == 100.0
    if expected_band_percentage is None:
        assert facts["completion_rate"].percentage == 100.00000000005001
        assert (
            facts["completion_rate"].normalized_movement_ratio
            != facts["prompt_rate"].normalized_movement_ratio
        )
    else:
        assert facts["completion_rate"].percentage == 100.0
        assert (
            facts["completion_rate"].normalized_movement_ratio
            == facts["prompt_rate"].normalized_movement_ratio
        )


@pytest.mark.parametrize(
    (
        "old_raw",
        "new_raw",
        "expected_ratio",
        "expected_delta",
        "expected_percentage",
    ),
    (
        ("1e-400", "2e-400", Fraction(1, 1), "positive", 100.0),
        (
            "1e308",
            "1.0000000000000001e308",
            Fraction(1, 10**16),
            "positive",
            1e-14,
        ),
        ("-1e308", "1e308", Fraction(2, 1), None, 200.0),
    ),
)
def test_dimension_comparison_uses_exact_normalized_arithmetic(
    old_raw: str,
    new_raw: str,
    expected_ratio: Fraction,
    expected_delta: str | None,
    expected_percentage: float,
) -> None:
    profile = _exact_price_profile()
    rule = conditional_pricing.resolve_price_rule("pricing.prompt", profile)

    fact = conditional_pricing._compare_dimension(
        "prompt",
        EffectivePriceValue("prompt", old_raw, rule),
        EffectivePriceValue("prompt", new_raw, rule),
        profile,
    )

    assert fact.direction == "higher"
    assert fact.normalized_movement_ratio == expected_ratio
    assert fact.percentage == expected_percentage
    if expected_delta is None:
        assert fact.delta is None
    else:
        assert fact.delta is not None
        assert math.isfinite(fact.delta)
        assert fact.delta > 0
    assert fact.old_value is not None and fact.new_value is not None
    assert (
        fact.old_value.normalized_exact_value
        < fact.new_value.normalized_exact_value
    )
    assert math.isfinite(fact.percentage)

    direct = resolve_direct_price_movement(
        "pricing.prompt",
        old_raw,
        new_raw,
        profile,
    )
    assert direct is not None
    assert direct.direction == fact.direction
    assert direct.delta == fact.delta
    assert direct.percentage == fact.percentage


def test_direct_price_without_comparison_group_is_unknown_and_unbucketed() -> None:
    fact = resolve_direct_price_movement(
        "pricing.prompt",
        "1",
        "2",
        _exact_price_profile(comparison_group=None),
    )

    assert fact is not None
    assert fact.direction == "unknown"
    assert fact.delta is None
    assert fact.percentage is None
    assert fact.comparison_group is None
    accounting = build_model_pricing_accounting(None, direct_price_facts=(fact,))
    assert accounting.direct_price_field_count == 1
    assert accounting.model_bucket == "none"


@pytest.mark.parametrize(
    ("profile", "field_path"),
    (
        (GENERIC_PROFILE.with_pricing(7, 3), "pricing.synthetic_rate"),
        (OPENROUTER_PROFILE, "pricing.synthetic_unregistered"),
    ),
)
def test_unmatched_ordinary_price_is_accounted_but_never_compared_or_absorbed(
    profile: ProviderProfile,
    field_path: str,
) -> None:
    fact = resolve_direct_price_movement(field_path, "1", "2", profile)

    assert fact is not None
    assert fact.direction == "unknown"
    assert fact.delta is None
    assert fact.percentage is None
    assert fact.comparison_group is None
    assert fact.old_value is not None
    assert fact.new_value is not None
    assert fact.old_value.price_rule.match_source == "unmatched"
    accounting = build_model_pricing_accounting(None, direct_price_facts=(fact,))
    assert accounting.direct_price_field_count == 1
    assert accounting.model_bucket == "none"


def test_unmatched_ordinary_one_sided_price_is_safe_coverage() -> None:
    fact = resolve_direct_price_movement(
        "pricing.synthetic_unregistered", None, "2", OPENROUTER_PROFILE
    )

    assert fact is not None
    assert fact.direction == "coverage"
    assert fact.comparison_group is None


@pytest.mark.parametrize(
    ("profile", "selector_path"),
    (
        (OPENROUTER_PROFILE, "pricing.overrides[0].utc_start"),
        (OPENROUTER_PROFILE, "pricing.overrides[0].utc_end"),
        (OPENROUTER_PROFILE, "pricing.overrides[0].min_prompt_tokens"),
        (
            ProviderProfile(
                kind="legacy-selector-synthetic",
                pricing_override_condition_fields=("legacy_selector",),
            ),
            "pricing.overrides[0].legacy_selector",
        ),
    ),
)
@pytest.mark.parametrize(("old_value", "new_value"), ((100, 200), (None, 100)))
def test_override_selector_leaves_never_create_direct_price_facts(
    profile: ProviderProfile,
    selector_path: str,
    old_value: int | None,
    new_value: int,
) -> None:
    assert (
        resolve_direct_price_movement(
            selector_path, old_value, new_value, profile
        )
        is None
    )


def test_crossing_complete_vectors_never_receive_an_arbitrary_peak() -> None:
    old_metadata = _complete_metadata(None)
    new_policy = [
        _window_rule(
            "monday",
            0,
            100,
            prompt="0.000004",
            completion="0.000001",
        )
    ]
    new_metadata = _complete_metadata(new_policy)
    new_metadata["pricing"].update(prompt="0.000001", completion="0.000004")

    _event_value, result = _interpret_event(
        None,
        new_policy,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )

    assert result is not None and result.comparison is not None
    assert result.comparison.peak_band_index is None
    assert all(not band.is_peak for band in result.comparison.bands)


def test_dominant_displayed_vector_marks_every_aligned_comparison_row_peak() -> None:
    old = [_day_rule("monday", 2), _day_rule("tuesday", 3)]
    new = [_day_rule("monday", 4), _day_rule("tuesday", 4)]
    old_metadata = _complete_metadata(old)
    new_metadata = _complete_metadata(new)
    old_metadata["pricing"]["prompt"] = 1
    new_metadata["pricing"]["prompt"] = 1

    _event_value, result = _interpret_event(
        old,
        new,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
    )

    assert result is not None and result.comparison is not None
    peak_rows = tuple(band for band in result.comparison.bands if band.is_peak)
    neutral_rows = tuple(band for band in result.comparison.bands if not band.is_peak)
    assert len(peak_rows) == 2
    assert {
        segment.weekday_index
        for band in peak_rows
        for segment in band.coverage
    } == {0, 1}
    assert all(
        fact.new_value is not None and fact.new_value.raw_value == 4
        for band in peak_rows
        for fact in band.dimensions
    )
    assert neutral_rows
    assert all(
        fact.direction == "unchanged"
        for band in neutral_rows
        for fact in band.dimensions
    )


def test_peak_dominance_resolves_thousands_of_unique_vectors_linearly() -> None:
    policy = [_day_rule("monday", 2)]
    _event_value, result = _interpret_event(
        None,
        policy,
        old_metadata=_complete_metadata(None),
        new_metadata=_complete_metadata(policy),
    )
    assert result is not None and result.new_compiled_policy is not None
    rule = conditional_pricing.resolve_price_rule(
        "pricing.prompt", OPENROUTER_PROFILE
    )
    band_count = 1_000
    bands = tuple(
        conditional_pricing.EffectivePriceBand(
            coverage=(WeeklySegment(0, 0, 1),),
            effective_prices=EffectivePriceVector(
                (EffectivePriceValue("prompt", str(index + 1), rule),)
            ),
            source_rule_indices=(index,),
            includes_default=False,
        )
        for index in range(band_count)
    )
    compiled = replace(result.new_compiled_policy, effective_bands=bands)

    with patch.object(
        conditional_pricing,
        "resolve_price_value",
        wraps=conditional_pricing.resolve_price_value,
    ) as resolve_spy:
        peak_identity = conditional_pricing._dominant_band_identity(
            compiled,
            OPENROUTER_PROFILE,
        )

    assert peak_identity == bands[-1].effective_prices.canonical_identity
    dimension_count = len(bands[0].effective_prices.entries)
    assert resolve_spy.call_count <= 2 * band_count * dimension_count


def test_region_alignment_inspects_partition_cells_linearly() -> None:
    cell_count = 1_000

    def hhmm(minute_of_day: int) -> int:
        hour, minute = divmod(minute_of_day, 60)
        return hour * 100 + minute

    old = [
        _window_rule(
            "monday",
            hhmm(index),
            hhmm(index + 1),
            prompt="0.000002" if index % 2 == 0 else "0.000003",
        )
        for index in range(cell_count)
    ]
    new = [
        _window_rule(
            "monday",
            hhmm(index),
            hhmm(index + 1),
            prompt="0.000004" if index % 2 == 0 else "0.000005",
        )
        for index in range(cell_count)
    ]
    _event_value, result = _interpret_event(
        old,
        new,
        old_metadata=_complete_metadata(old),
        new_metadata=_complete_metadata(new),
    )
    assert result is not None
    assert result.old_compiled_policy is not None
    assert result.new_compiled_policy is not None

    class CountingRegions:
        def __init__(self, values: tuple[Any, ...]) -> None:
            self.values = values
            self.visits = 0

        def __len__(self) -> int:
            return len(self.values)

        def __iter__(self):
            for value in self.values:
                self.visits += 1
                yield value

        def __getitem__(self, index: int):
            self.visits += 1
            return self.values[index]

    old_values = result.old_compiled_policy.effective_partition
    new_values = result.new_compiled_policy.effective_partition
    counted_old = CountingRegions(old_values)
    counted_new = CountingRegions(new_values)
    old_compiled = replace(
        result.old_compiled_policy,
        effective_partition=counted_old,  # type: ignore[arg-type]
    )
    new_compiled = replace(
        result.new_compiled_policy,
        effective_partition=counted_new,  # type: ignore[arg-type]
    )

    comparison, reasons = conditional_pricing._build_conditional_comparison(
        result.transition,
        old_compiled,
        new_compiled,
        OPENROUTER_PROFILE,
    )

    assert comparison is not None
    assert reasons == ()
    linear_budget = 6 * (len(old_values) + len(new_values))
    assert counted_old.visits + counted_new.visits <= linear_budget


def test_absorption_uses_exact_path_values_and_one_occurrence_only() -> None:
    old = [{"utc_days": ["monday"], "prompt": "0.000003"}]
    new = [{"utc_days": ["monday"], "prompt": "0.000004"}]
    old_metadata = _complete_metadata(old)
    new_metadata = _complete_metadata(new)
    new_metadata["pricing"]["prompt"] = "0.000002"
    sibling = FieldChange("pricing.prompt", "0.000001", "0.000002")
    nested = FieldChange("nested.pricing.prompt", "0.000001", "0.000002")
    unrelated = (
        FieldChange("pricing.request", "0.01", "0.02"),
        FieldChange("pricing.image", "0.1", "0.2"),
        FieldChange("pricing.web_search", "0.01", "0.02"),
    )
    event, result = _interpret_event(
        old,
        new,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
        siblings=(sibling, sibling, nested, *unrelated),
    )

    assert result is not None
    assert len(result.absorbed_base_price_changes) == 1
    reference = result.absorbed_base_price_changes[0]
    assert reference.field_name == "pricing.prompt"
    assert reference.occurrence == 0
    assert tuple(change.field_name for change in event.field_changes) == (
        "pricing.overrides",
        "pricing.prompt",
        "pricing.prompt",
        "nested.pricing.prompt",
        "pricing.request",
        "pricing.image",
        "pricing.web_search",
    )
    assert old == [{"utc_days": ["monday"], "prompt": "0.000003"}]
    assert new == [{"utc_days": ["monday"], "prompt": "0.000004"}]
    assert result.accounting is not None
    assert result.accounting.direct_price_field_count == 1
    fact = result.accounting.direct_price_facts[0]
    assert fact.source_change == reference
    assert fact.old_value is not None and fact.old_value.raw_value == "0.000001"
    assert fact.new_value is not None and fact.new_value.raw_value == "0.000002"
    assert fact.direction == "higher"


def test_absorption_rejects_metadata_mismatch_and_missing_snapshot() -> None:
    policy = [{"utc_days": ["monday"], "prompt": "0.000003"}]
    old_metadata = _complete_metadata(policy)
    new_metadata = _complete_metadata(policy)
    mismatch = FieldChange("pricing.prompt", "0.000009", "0.000002")
    event, result = _interpret_event(
        policy,
        policy,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
        siblings=(mismatch,),
    )
    assert result is not None
    assert result.absorbed_base_price_changes == ()
    assert decide_sibling_base_price_absorption(event, OPENROUTER_PROFILE, result) == ()

    missing_event, missing_result = _interpret_event(
        None,
        policy,
        old_metadata=None,
        new_metadata=None,
        siblings=(FieldChange("pricing.prompt", None, "0.000001"),),
    )
    assert missing_result is not None
    assert missing_result.absorbed_base_price_changes == ()
    assert (
        decide_sibling_base_price_absorption(
            missing_event, OPENROUTER_PROFILE, missing_result
        )
        == ()
    )


def test_absorption_is_identity_bound_and_consume_once() -> None:
    old = [{"utc_days": ["monday"], "prompt": "0.000003"}]
    new = [{"utc_days": ["monday"], "prompt": "0.000004"}]
    old_metadata = _complete_metadata(old)
    new_metadata = _complete_metadata(new)
    new_metadata["pricing"]["prompt"] = "0.000002"
    sibling = FieldChange("pricing.prompt", "0.000001", "0.000002")
    event, result = _interpret_event(
        old,
        new,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
        siblings=(sibling, sibling),
    )
    assert result is not None
    decisions = decide_sibling_base_price_absorption(
        event,
        OPENROUTER_PROFILE,
        replace(result, absorbed_base_price_changes=(), accounting=None),
    )
    assert len(decisions) == 1
    assert isinstance(decisions[0], AbsorbedBasePriceChange)
    assert (
        decide_sibling_base_price_absorption(
            event,
            OPENROUTER_PROFILE,
            replace(result, absorbed_base_price_changes=(), accounting=None),
            consumed_references=(decisions[0].source_change,),
        )
        == ()
    )

    other_event = replace(
        event,
        identity=LiveComparisonIdentity(PROVIDER_ID, MODEL_ID, 10, 12),
    )
    assert (
        decide_sibling_base_price_absorption(
            other_event,
            OPENROUTER_PROFILE,
            replace(result, absorbed_base_price_changes=(), accounting=None),
        )
        == ()
    )


@pytest.mark.parametrize(
    ("metadata_case", "expected_absorptions"),
    (
        ("old-missing", 1),
        ("old-null", 0),
        ("new-missing", 1),
        ("new-null", 0),
        ("numeric", 1),
    ),
)
def test_absorption_distinguishes_missing_exact_path_from_json_null(
    metadata_case: str,
    expected_absorptions: int,
) -> None:
    old = [{"utc_days": ["monday"], "prompt": "0.000003"}]
    new = [{"utc_days": ["monday"], "prompt": "0.000004"}]
    old_metadata = _complete_metadata(old)
    new_metadata = _complete_metadata(new)
    old_metadata["pricing"]["prompt"] = "0.000001"
    new_metadata["pricing"]["prompt"] = "0.000002"
    old_row: Any = "0.000001"
    new_row: Any = "0.000002"
    if metadata_case == "old-missing":
        old_metadata["pricing"].pop("prompt")
        old_row = None
    elif metadata_case == "old-null":
        old_metadata["pricing"]["prompt"] = None
        old_row = None
    elif metadata_case == "new-missing":
        new_metadata["pricing"].pop("prompt")
        new_row = None
    elif metadata_case == "new-null":
        new_metadata["pricing"]["prompt"] = None
        new_row = None

    event, result = _interpret_event(
        old,
        new,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
        siblings=(FieldChange("pricing.prompt", old_row, new_row),),
    )

    assert result is not None
    assert len(result.absorbed_base_price_changes) == expected_absorptions
    decisions = decide_sibling_base_price_absorption(
        event,
        OPENROUTER_PROFILE,
        replace(result, absorbed_base_price_changes=(), accounting=None),
    )
    assert len(decisions) == expected_absorptions


@pytest.mark.parametrize(
    "profile",
    (
        replace(
            OPENROUTER_PROFILE,
            price_leaf_rules={
                key: value
                for key, value in OPENROUTER_PROFILE.price_leaf_rules.items()
                if key != "prompt"
            },
        ),
        replace(
            OPENROUTER_PROFILE,
            price_leaf_rules={
                **OPENROUTER_PROFILE.price_leaf_rules,
                "prompt": PriceDisplayRule(
                    unit_label="/synthetic mismatched unit",
                    multiplier=1_000_000,
                    divisor=1,
                    comparison_group="usd_per_million_tokens",
                ),
            },
        ),
        replace(
            OPENROUTER_PROFILE,
            price_leaf_rules={
                **OPENROUTER_PROFILE.price_leaf_rules,
                "prompt": PriceDisplayRule(
                    unit_label="/1M tokens",
                    multiplier=1_000_000,
                    divisor=1,
                    comparison_group="synthetic_incompatible_group",
                ),
            },
        ),
    ),
)
def test_absorption_rejects_unmatched_unit_and_group_rules(
    profile: ProviderProfile,
) -> None:
    old = [{"utc_days": ["monday"], "prompt": "0.000003"}]
    new = [{"utc_days": ["monday"], "prompt": "0.000004"}]
    old_metadata = _complete_metadata(old)
    new_metadata = _complete_metadata(new)
    new_metadata["pricing"]["prompt"] = "0.000002"
    event, result = _interpret_event(
        old,
        new,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
        siblings=(FieldChange("pricing.prompt", "0.000001", "0.000002"),),
    )
    assert result is not None

    assert (
        decide_sibling_base_price_absorption(
            event,
            profile,
            replace(result, absorbed_base_price_changes=(), accounting=None),
        )
        == ()
    )


def test_raw_fallback_absorbs_nothing_but_counts_one_conditional_policy() -> None:
    raw = [{"unknown_selector": "synthetic", "prompt": "0.000003"}]
    metadata = _complete_metadata(raw)
    event, result = _interpret_event(
        None,
        raw,
        old_metadata=_complete_metadata(None),
        new_metadata=metadata,
        siblings=(FieldChange("pricing.prompt", "0.000001", "0.000002"),),
    )

    assert result is not None and result.state == "raw-fallback"
    assert result.absorbed_base_price_changes == ()
    assert result.comparison is None
    assert "raw_fallback" in result.comparison_inhibition_reasons
    assert isinstance(result.accounting, ModelPricingAccounting)
    assert result.accounting.conditional_policy_count == 1
    assert result.accounting.source_rule_count == 1
    assert result.accounting.schedule_dimensions == ("prompt",)
    assert result.accounting.model_bucket == "conditional"
    assert result.accounting.effective_band_count == 0
    assert decide_sibling_base_price_absorption(event, OPENROUTER_PROFILE, result) == ()


def test_synthetic_schedule_accounting_reconciles_disjoint_units() -> None:
    old_metadata, new_metadata = synthetic_scheduled_rate_models()
    policy = new_metadata["pricing"]["overrides"]
    siblings = tuple(
        FieldChange(
            f"pricing.{dimension}",
            old_metadata["pricing"][dimension],
            new_metadata["pricing"][dimension],
        )
        for dimension in ("prompt", "completion", "request")
    )

    _event_value, result = _interpret_event(
        None,
        policy,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
        siblings=siblings,
    )

    assert result is not None and isinstance(result.accounting, ModelPricingAccounting)
    accounting = result.accounting
    assert accounting.conditional_policy_count == SYNTHETIC_SCHEDULED_RATE_EXPECTED_ACCOUNTING["policies"]
    assert accounting.source_rule_count == SYNTHETIC_SCHEDULED_RATE_EXPECTED_ACCOUNTING["source_rules"]
    assert accounting.schedule_dimensions == ("completion", "prompt", "request")
    assert accounting.schedule_dimension_count == SYNTHETIC_SCHEDULED_RATE_EXPECTED_ACCOUNTING["dimensions"]
    assert accounting.effective_band_count == SYNTHETIC_SCHEDULED_RATE_EXPECTED_ACCOUNTING["effective_bands"]
    assert accounting.direct_price_field_count == 3
    assert accounting.model_bucket == "conditional"
    assert not hasattr(accounting, "total_count")
    with pytest.raises(FrozenInstanceError):
        accounting.model_bucket = "mixed"  # type: ignore[misc]


def test_removed_policy_uses_old_display_side_and_missing_side_invents_no_bands() -> None:
    policy = [
        _window_rule("monday", 0, 100, prompt="0.000003"),
        _window_rule("tuesday", 0, 100, prompt="0.000004"),
    ]
    _event_value, removed = _interpret_event(
        policy,
        None,
        old_metadata=_complete_metadata(policy),
        new_metadata=_complete_metadata(None),
    )
    assert removed is not None and removed.accounting is not None
    assert removed.accounting.source_rule_count == 2
    assert removed.accounting.conditional_policy_count == 1
    assert removed.accounting.model_bucket == "conditional"

    _missing_event, missing = _interpret_event(
        None,
        policy,
        old_metadata=None,
        new_metadata=None,
    )
    assert missing is not None and missing.accounting is not None
    assert missing.accounting.conditional_policy_count == 1
    assert missing.accounting.source_rule_count == 2
    assert missing.accounting.schedule_dimensions == ("prompt",)
    assert missing.accounting.effective_band_count == 0
    assert missing.accounting.model_bucket == "conditional"


@pytest.mark.parametrize(
    ("rule_price", "expected_bands"),
    (("0.000001", 1), ("0.000003", 2)),
)
def test_accounting_counts_distinct_effective_vectors_and_uncovered_default(
    rule_price: str,
    expected_bands: int,
) -> None:
    policy = [_window_rule("monday", 0, 100, prompt=rule_price)]

    _event_value, result = _interpret_event(
        None,
        policy,
        old_metadata=_complete_metadata(None),
        new_metadata=_complete_metadata(policy),
    )

    assert result is not None and result.accounting is not None
    assert result.accounting.effective_band_count == expected_bands
    assert result.accounting.direct_price_field_count == 0


def test_evidence_only_reorder_has_zero_conditional_contribution() -> None:
    monday = _window_rule("monday", 0, 100, prompt="0.000003")
    tuesday = _window_rule("tuesday", 0, 100, prompt="0.000004")
    old = [monday, tuesday]
    new = [tuesday, monday]

    _event_value, result = _interpret_event(
        old,
        new,
        old_metadata=_complete_metadata(old),
        new_metadata=_complete_metadata(new),
    )

    assert result is not None and result.semantic_change is False
    assert result.accounting is not None
    assert result.accounting.conditional_policy_count == 0
    assert result.accounting.source_rule_count == 0
    assert result.accounting.schedule_dimension_count == 0
    assert result.accounting.effective_band_count == 0
    assert result.accounting.model_bucket == "none"
    assert result.absorbed_base_price_changes == ()


def test_accounting_constructor_merges_direct_facts_once_without_cross_unit_math() -> None:
    up = resolve_direct_price_movement(
        "pricing.prompt", "0.000001", "0.000002", OPENROUTER_PROFILE
    )
    down = resolve_direct_price_movement(
        "pricing.request", "0.02", "0.01", OPENROUTER_PROFILE
    )
    assert up is not None and down is not None

    accounting = build_model_pricing_accounting(
        None,
        direct_price_facts=(up, up, down),
    )

    assert accounting.direct_price_facts == (up, down)
    assert accounting.direct_price_field_count == 2
    assert accounting.conditional_policy_count == 0
    assert accounting.source_rule_count == 0
    assert accounting.schedule_dimension_count == 0
    assert accounting.effective_band_count == 0
    assert accounting.model_bucket == "mixed"
    assert not hasattr(accounting, "aggregate_delta")


def test_accounting_constructor_preserves_absorbed_facts_when_merging_ordinary() -> None:
    old_metadata, new_metadata = synthetic_scheduled_rate_models()
    policy = new_metadata["pricing"]["overrides"]
    siblings = tuple(
        FieldChange(
            f"pricing.{dimension}",
            old_metadata["pricing"][dimension],
            new_metadata["pricing"][dimension],
        )
        for dimension in ("prompt", "completion", "request")
    )
    _event_value, result = _interpret_event(
        None,
        policy,
        old_metadata=old_metadata,
        new_metadata=new_metadata,
        siblings=siblings,
    )
    ordinary = resolve_direct_price_movement(
        "pricing.image", "0.01", "0.02", OPENROUTER_PROFILE
    )

    assert result is not None and result.accounting is not None
    assert len(result.accounting.direct_price_facts) == 3
    assert ordinary is not None
    rebuilt = build_model_pricing_accounting(
        result,
        direct_price_facts=(result.accounting.direct_price_facts[1], ordinary),
    )

    assert rebuilt.direct_price_facts == (
        *result.accounting.direct_price_facts,
        ordinary,
    )
    assert rebuilt.direct_price_field_count == 4
    assert rebuilt.conditional_policy_count == 1
    assert rebuilt.model_bucket == "conditional"
