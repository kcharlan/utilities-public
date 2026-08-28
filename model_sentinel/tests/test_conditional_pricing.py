from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, get_args

import pytest

from model_sentinel.conditional_pricing import (
    ComparisonInhibitionReason,
    FallbackReason,
    GroupingInhibitionReason,
    LiveComparisonIdentity,
    PricingComparisonEvent,
    StoredComparisonIdentity,
    interpret_conditional_pricing,
)
from model_sentinel.models import FieldChange
from model_sentinel.provider_profiles import (
    OPENROUTER_PROFILE,
    ConditionalPricingConditionDescriptor,
    ConditionalPricingConditionSetSemantics,
    ConditionalPricingPolicySemantics,
    PriceDisplayRule,
    ProviderProfile,
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
def test_parent_transition_is_classified_without_deciding_semantic_equality(
    old_value: Any,
    new_value: Any,
    transition: str,
) -> None:
    result = _interpret(
        old_value,
        new_value,
        old_metadata=_complete_metadata(old_value),
        new_metadata=_complete_metadata(new_value),
    )

    assert result is not None
    assert result.transition == transition
    assert result.state == "ordered-rules"
    assert result.semantic_change is None
    assert result.comparison is None
    assert result.accounting is None
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
        "schedule_compilation_deferred",
        "missing_event_snapshot",
    }
    assert set(get_args(ComparisonInhibitionReason)) == {
        "comparison_deferred",
        "missing_event_snapshot",
        "missing_price_comparison_group",
    }
