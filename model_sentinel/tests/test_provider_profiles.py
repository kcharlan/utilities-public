from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType
from typing import Any

import pytest

from model_sentinel.config import ProviderConfig
from model_sentinel.provider_profiles import (
    GENERIC_PROFILE,
    OPENROUTER_PROFILE,
    PER_MILLION_TOKENS_TARGET,
    USD_PER_MILLION_TOKENS_GROUP,
    ConditionalPricingConditionDescriptor,
    ConditionalPricingConditionSetSemantics,
    ConditionalPricingPolicySemantics,
    PriceDisplayRule,
    ProviderProfile,
    default_categorize,
    default_is_price_amount_field,
    resolve_profile,
    profiles_for,
)
from model_sentinel.providers import ProviderFetchError, extract_model_list
from tests.conditional_pricing_fixtures import (
    SYNTHETIC_SCHEDULED_RATE_DIMENSIONS,
    SYNTHETIC_SCHEDULED_RATE_EXPECTED_ACCOUNTING,
    synthetic_scheduled_rate_models,
)


@pytest.fixture
def synthetic_provider() -> ProviderConfig:
    return ProviderConfig(
        provider_id="synthetic",
        label="Synthetic Provider",
        kind="synthetic",
        base_url="https://synthetic.invalid/v1",
        models_path="/models",
        credential_env_var="SYNTHETIC_API_KEY",
        price_multiplier=1,
        price_divisor=1,
        enabled=True,
    )


def test_resolve_openrouter_profile_with_bound_pricing() -> None:
    profile = resolve_profile(
        "OPENROUTER",
        price_multiplier=1_000_000,
        price_divisor=2,
    )

    assert profile.kind == OPENROUTER_PROFILE.kind
    assert profile.field_path_labels is OPENROUTER_PROFILE.field_path_labels
    assert profile.pricing_field_order == OPENROUTER_PROFILE.pricing_field_order
    assert profile.price_multiplier == 1_000_000
    assert profile.price_divisor == 2


def test_profiles_for_binds_each_provider_factors(synthetic_provider: ProviderConfig) -> None:
    profiles = profiles_for((synthetic_provider,))

    assert tuple(profiles) == (synthetic_provider.provider_id,)
    assert profiles[synthetic_provider.provider_id] == resolve_profile(
        synthetic_provider.kind,
        price_multiplier=synthetic_provider.price_multiplier,
        price_divisor=synthetic_provider.price_divisor,
    )


@pytest.mark.parametrize("kind", ("abacus", "never-heard-of-it"))
def test_resolve_unknown_kind_uses_generic_profile(kind: str) -> None:
    profile = resolve_profile(kind)

    assert profile.kind == "generic"
    assert profile.field_path_labels == {}
    assert profile.field_leaf_labels == {}


def test_with_pricing_returns_new_frozen_profile() -> None:
    bound = GENERIC_PROFILE.with_pricing(7, 3)

    assert bound is not GENERIC_PROFILE
    assert (bound.price_multiplier, bound.price_divisor) == (7, 3)
    assert (GENERIC_PROFILE.price_multiplier, GENERIC_PROFILE.price_divisor) == (1, 1)
    with pytest.raises(FrozenInstanceError):
        bound.price_multiplier = 8  # type: ignore[misc]


def test_openrouter_profile_contains_provider_vocabulary() -> None:
    assert "top_provider.is_moderated" in OPENROUTER_PROFILE.known_boolean_fields
    assert OPENROUTER_PROFILE.field_leaf_labels["prompt"] == "Input"
    assert OPENROUTER_PROFILE.envelope_keys == ("data",)


def test_profiles_define_provider_owned_pricing_field_order() -> None:
    assert GENERIC_PROFILE.pricing_field_order == ()
    assert OPENROUTER_PROFILE.pricing_field_order == (
        "prompt",
        "input_cache_read",
        "input_cache_write",
        "input_cache_write_1h",
        "input_audio_cache",
        "completion",
    )


def test_openrouter_pricing_order_uses_exact_raw_field_identities() -> None:
    order = OPENROUTER_PROFILE.pricing_field_order

    assert "Input" not in order
    assert "Output" not in order
    assert "cache" not in order


def test_default_heuristics_preserve_existing_behavior() -> None:
    assert default_categorize("pricing.prompt") == "Pricing"
    assert default_is_price_amount_field("input_token_rate") is False


def test_generic_profile_accepts_guessed_models_envelope(
    synthetic_provider: ProviderConfig,
) -> None:
    models = [{"id": "synthetic/model-a"}]

    assert extract_model_list(
        synthetic_provider,
        {"models": models},
        GENERIC_PROFILE,
    ) == models


def test_openrouter_profile_only_accepts_its_data_envelope(
    synthetic_provider: ProviderConfig,
) -> None:
    models = [{"id": "synthetic/model-a"}]

    assert extract_model_list(
        synthetic_provider,
        {"data": models},
        OPENROUTER_PROFILE,
    ) == models
    with pytest.raises(ProviderFetchError, match="Synthetic Provider"):
        extract_model_list(
            synthetic_provider,
            {"models": models},
            OPENROUTER_PROFILE,
        )


@pytest.mark.parametrize("profile", (GENERIC_PROFILE, OPENROUTER_PROFILE))
def test_top_level_model_list_bypasses_envelope_search(
    synthetic_provider: ProviderConfig,
    profile,
) -> None:
    models = [{"id": "synthetic/model-a"}]

    assert extract_model_list(synthetic_provider, models, profile) == models


def test_price_display_rule_accepts_explicit_and_inherited_factors() -> None:
    explicit = PriceDisplayRule(
        unit_label="/synthetic operation",
        multiplier=7,
        divisor=3,
        comparison_group="usd_per_synthetic_operation",
    )
    inherited = PriceDisplayRule(
        unit_label="/1M",
        normalized_target=PER_MILLION_TOKENS_TARGET,
    )

    assert (explicit.multiplier, explicit.divisor) == (7, 3)
    assert (inherited.multiplier, inherited.divisor) == (None, None)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"unit_label": ""},
        {"unit_label": "   "},
        {"unit_label": "/unit", "multiplier": 1},
        {"unit_label": "/unit", "divisor": 1},
        {"unit_label": "/unit", "multiplier": 0, "divisor": 1},
        {"unit_label": "/unit", "multiplier": 1, "divisor": -1},
        {"unit_label": "/unit", "comparison_group": "  "},
        {"unit_label": "/unit", "normalized_target": "per_guess"},
    ),
)
def test_price_display_rule_rejects_invalid_declarations(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        PriceDisplayRule(**kwargs)  # type: ignore[arg-type]


def test_price_display_rule_is_frozen() -> None:
    rule = PriceDisplayRule(unit_label="/synthetic operation")

    with pytest.raises(FrozenInstanceError):
        rule.unit_label = "/changed"  # type: ignore[misc]


def test_generic_profile_declares_inherited_token_fallback_without_comparison() -> None:
    rule = GENERIC_PROFILE.unmatched_price_rule

    assert GENERIC_PROFILE.price_path_rules == {}
    assert GENERIC_PROFILE.price_leaf_rules == {}
    assert (rule.multiplier, rule.divisor) == (None, None)
    assert rule.unit_label == "/1M"
    assert rule.normalized_target == PER_MILLION_TOKENS_TARGET
    assert rule.comparison_group is None
    assert GENERIC_PROFILE.primary_price_comparison_group is None


def test_openrouter_profile_declares_exact_price_rule_registry() -> None:
    rules = OPENROUTER_PROFILE.price_leaf_rules

    assert set(rules) == {
        "prompt",
        "completion",
        "internal_reasoning",
        "input_cache_read",
        "input_cache_write",
        "web_search",
        "request",
        "image",
    }
    for leaf in (
        "prompt",
        "completion",
        "internal_reasoning",
        "input_cache_read",
        "input_cache_write",
    ):
        rule = rules[leaf]
        assert (rule.multiplier, rule.divisor) == (1_000_000, 1)
        assert rule.unit_label == "/1M tokens"
        assert rule.comparison_group == USD_PER_MILLION_TOKENS_GROUP
        assert rule.normalized_target == PER_MILLION_TOKENS_TARGET

    assert rules["web_search"] == PriceDisplayRule(
        unit_label="/1K searches",
        multiplier=1_000,
        divisor=1,
        comparison_group="usd_per_thousand_searches",
    )
    assert rules["request"] == PriceDisplayRule(
        unit_label="/request",
        multiplier=1,
        divisor=1,
        comparison_group="usd_per_request",
    )
    assert rules["image"] == PriceDisplayRule(
        unit_label="/image",
        multiplier=1,
        divisor=1,
        comparison_group="usd_per_image",
    )
    assert OPENROUTER_PROFILE.price_path_rules == {}
    assert OPENROUTER_PROFILE.primary_price_comparison_group == USD_PER_MILLION_TOKENS_GROUP


def test_openrouter_profile_unknown_price_rule_is_conservative() -> None:
    rule = OPENROUTER_PROFILE.unmatched_price_rule

    assert (rule.multiplier, rule.divisor) == (1, 1)
    assert rule.unit_label == "/unit unknown"
    assert rule.comparison_group is None
    assert rule.normalized_target is None


def test_price_rule_registries_are_immutable() -> None:
    with pytest.raises(TypeError):
        OPENROUTER_PROFILE.price_leaf_rules["synthetic"] = PriceDisplayRule(  # type: ignore[index]
            unit_label="/synthetic operation"
        )
    with pytest.raises(TypeError):
        OPENROUTER_PROFILE.price_path_rules["pricing.synthetic"] = PriceDisplayRule(  # type: ignore[index]
            unit_label="/synthetic operation"
        )


def test_price_rule_registries_do_not_alias_proxy_backing_mappings() -> None:
    backing = {"prompt": PriceDisplayRule(unit_label="/synthetic original")}
    profile = ProviderProfile(
        kind="synthetic",
        price_leaf_rules=MappingProxyType(backing),
    )

    backing["prompt"] = PriceDisplayRule(unit_label="/synthetic mutated")
    backing["completion"] = PriceDisplayRule(unit_label="/synthetic added")

    assert profile.price_leaf_rules == {
        "prompt": PriceDisplayRule(unit_label="/synthetic original")
    }


def test_with_pricing_preserves_price_rule_contract() -> None:
    bound = OPENROUTER_PROFILE.with_pricing(7, 3)

    assert bound.price_path_rules is OPENROUTER_PROFILE.price_path_rules
    assert bound.price_leaf_rules is OPENROUTER_PROFILE.price_leaf_rules
    assert bound.unmatched_price_rule is OPENROUTER_PROFILE.unmatched_price_rule
    assert bound.primary_price_comparison_group == OPENROUTER_PROFILE.primary_price_comparison_group
    assert (bound.price_multiplier, bound.price_divisor) == (7, 3)


def _synthetic_parse(value: Any) -> Any:
    return value


def _synthetic_identity(value: Any) -> Any:
    return value


def _synthetic_format(value: Any) -> str:
    return f"synthetic:{value}"


def _descriptor(
    field_name: str,
    family: str,
    semantic_role: str,
    *,
    grouped: bool,
) -> ConditionalPricingConditionDescriptor:
    return ConditionalPricingConditionDescriptor(
        field_name=field_name,
        family=family,  # type: ignore[arg-type]
        semantic_role=semantic_role,  # type: ignore[arg-type]
        parse_value=_synthetic_parse,
        canonical_identity=_synthetic_identity,
        format_value=_synthetic_format,
        participates_in_interval_grouping=grouped,
    )


def _synthetic_condition_set_semantics() -> ConditionalPricingConditionSetSemantics:
    return ConditionalPricingConditionSetSemantics(
        missing_weekdays="all_seven",
        missing_endpoints="all_day",
        endpoint_pairing="both_or_neither",
        equal_endpoints="unsupported",
    )


def _synthetic_policy_semantics() -> ConditionalPricingPolicySemantics:
    return ConditionalPricingPolicySemantics(
        condition_combination="all_conditions",
        rule_precedence="later_per_key",
        omitted_price_behavior="retain_prior_or_base",
        top_level_price_role="default_base",
    )


def test_conditional_pricing_descriptor_rejects_invalid_contracts() -> None:
    valid = dict(
        field_name="synthetic_selector",
        family="time",
        semantic_role="utc_start_inclusive",
        parse_value=_synthetic_parse,
        canonical_identity=_synthetic_identity,
        format_value=_synthetic_format,
        participates_in_interval_grouping=True,
    )

    with pytest.raises(ValueError):
        ConditionalPricingConditionDescriptor(**(valid | {"field_name": ""}))
    with pytest.raises(ValueError):
        ConditionalPricingConditionDescriptor(**(valid | {"family": "unknown"}))
    with pytest.raises(ValueError):
        ConditionalPricingConditionDescriptor(**(valid | {"semantic_role": "unknown"}))
    with pytest.raises(ValueError):
        ConditionalPricingConditionDescriptor(
            **(valid | {"semantic_role": "integer_strictly_greater"})
        )
    with pytest.raises(ValueError):
        ConditionalPricingConditionDescriptor(
            **(valid | {"parse_value": "not callable"})
        )


@pytest.mark.parametrize("callable_name", ("canonical_identity", "format_value"))
def test_conditional_pricing_descriptor_rejects_every_noncallable_stage(
    callable_name: str,
) -> None:
    valid = dict(
        field_name="synthetic_selector",
        family="time",
        semantic_role="utc_start_inclusive",
        parse_value=_synthetic_parse,
        canonical_identity=_synthetic_identity,
        format_value=_synthetic_format,
        participates_in_interval_grouping=True,
    )

    with pytest.raises(ValueError):
        ConditionalPricingConditionDescriptor(**(valid | {callable_name: None}))


@pytest.mark.parametrize(
    ("family", "semantic_role", "grouped"),
    (
        ("time", "utc_weekdays", False),
        ("time", "utc_start_inclusive", False),
        ("time", "utc_end_exclusive", False),
        ("threshold", "integer_strictly_greater", True),
        ("time", "utc_start_inclusive", 1),
    ),
)
def test_conditional_pricing_descriptor_rejects_invalid_role_grouping_contracts(
    family: str,
    semantic_role: str,
    grouped: object,
) -> None:
    with pytest.raises(ValueError):
        _descriptor(
            "synthetic_selector",
            family,
            semantic_role,
            grouped=grouped,  # type: ignore[arg-type]
        )


def test_conditional_pricing_descriptor_raw_pipeline_uses_parsed_then_canonical_values() -> None:
    start = OPENROUTER_PROFILE.pricing_override_condition_descriptor("utc_start")
    end = OPENROUTER_PROFILE.pricing_override_condition_descriptor("utc_end")
    weekdays = OPENROUTER_PROFILE.pricing_override_condition_descriptor("utc_days")
    threshold = OPENROUTER_PROFILE.pricing_override_condition_descriptor("min_prompt_tokens")

    assert start is not None
    assert end is not None
    assert weekdays is not None
    assert threshold is not None
    assert start.canonicalize_raw(100) == 60
    assert start.format_raw(100) == "01:00"
    assert end.canonicalize_raw(0) == 0
    assert end.format_raw(0) == "24:00"
    assert weekdays.canonicalize_raw(["sunday", "monday"]) == ("monday", "sunday")
    assert weekdays.format_raw(["sunday", "monday"]) == "Mon, Sun"
    assert threshold.canonicalize_raw(200_000) == 200_000
    assert threshold.format_raw(200_000) == "Prompt > 200,000 tokens"


def test_conditional_pricing_semantics_reject_undeclared_values() -> None:
    with pytest.raises(ValueError):
        ConditionalPricingConditionSetSemantics(
            missing_weekdays="not-all-days",  # type: ignore[arg-type]
            missing_endpoints="all_day",
            endpoint_pairing="both_or_neither",
            equal_endpoints="unsupported",
        )
    with pytest.raises(ValueError):
        ConditionalPricingPolicySemantics(
            condition_combination="all_conditions",
            rule_precedence="first-wins",  # type: ignore[arg-type]
            omitted_price_behavior="retain_prior_or_base",
            top_level_price_role="default_base",
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("missing_weekdays", "none"),
        ("missing_endpoints", "partial_day"),
        ("endpoint_pairing", "optional"),
        ("equal_endpoints", "all_day"),
    ),
)
def test_condition_set_semantics_rejects_every_invalid_field(
    field_name: str,
    invalid_value: str,
) -> None:
    values = dict(
        missing_weekdays="all_seven",
        missing_endpoints="all_day",
        endpoint_pairing="both_or_neither",
        equal_endpoints="unsupported",
    )

    with pytest.raises(ValueError):
        ConditionalPricingConditionSetSemantics(
            **(values | {field_name: invalid_value})  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("condition_combination", "any_condition"),
        ("rule_precedence", "first_per_key"),
        ("omitted_price_behavior", "reset_to_zero"),
        ("top_level_price_role", "override_base"),
    ),
)
def test_policy_semantics_rejects_every_invalid_field(
    field_name: str,
    invalid_value: str,
) -> None:
    values = dict(
        condition_combination="all_conditions",
        rule_precedence="later_per_key",
        omitted_price_behavior="retain_prior_or_base",
        top_level_price_role="default_base",
    )

    with pytest.raises(ValueError):
        ConditionalPricingPolicySemantics(
            **(values | {field_name: invalid_value})  # type: ignore[arg-type]
        )


def test_conditional_pricing_contract_records_are_frozen() -> None:
    descriptor = _descriptor("when_utc", "time", "utc_start_inclusive", grouped=True)
    condition_set = _synthetic_condition_set_semantics()
    policy = _synthetic_policy_semantics()

    with pytest.raises(FrozenInstanceError):
        descriptor.field_name = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        condition_set.equal_endpoints = "supported"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        policy.rule_precedence = "first_per_key"  # type: ignore[misc]


def test_provider_profile_defensively_copies_and_freezes_conditional_registries() -> None:
    descriptor = _descriptor("when_utc", "time", "utc_start_inclusive", grouped=True)
    descriptors = {"when_utc": descriptor}
    base_paths = {"prompt_rate": "pricing.prompt_rate"}
    profile = ProviderProfile(
        kind="synthetic",
        pricing_override_condition_descriptors=MappingProxyType(descriptors),
        pricing_override_base_paths=MappingProxyType(base_paths),
    )

    descriptors["later_utc"] = _descriptor(
        "later_utc", "time", "utc_end_exclusive", grouped=True
    )
    base_paths["completion_rate"] = "pricing.completion_rate"

    assert profile.pricing_override_condition_descriptors == {"when_utc": descriptor}
    assert profile.pricing_override_base_paths == {"prompt_rate": "pricing.prompt_rate"}
    with pytest.raises(TypeError):
        profile.pricing_override_condition_descriptors["other"] = descriptor  # type: ignore[index]
    with pytest.raises(TypeError):
        profile.pricing_override_base_paths["other"] = "pricing.other"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        profile.pricing_override_base_paths = {}  # type: ignore[misc]


def test_with_pricing_preserves_conditional_registry_identity_after_validation() -> None:
    bound = OPENROUTER_PROFILE.with_pricing(7, 3)

    assert (
        bound.pricing_override_condition_descriptors
        is OPENROUTER_PROFILE.pricing_override_condition_descriptors
    )
    assert (
        bound.pricing_override_base_paths
        is OPENROUTER_PROFILE.pricing_override_base_paths
    )
    assert bound.pricing_override_condition_set_semantics is (
        OPENROUTER_PROFILE.pricing_override_condition_set_semantics
    )
    assert bound.pricing_override_policy_semantics is OPENROUTER_PROFILE.pricing_override_policy_semantics


def test_provider_profile_rejects_descriptor_registry_key_mismatch() -> None:
    descriptor = _descriptor("synthetic_selector", "threshold", "integer_strictly_greater", grouped=False)

    with pytest.raises(ValueError, match="key"):
        ProviderProfile(
            kind="synthetic",
            pricing_override_condition_descriptors={"wrong_name": descriptor},
        )


@pytest.mark.parametrize(
    "descriptors",
    (
        {"synthetic_selector": "not a descriptor"},
        {
            "first_selector": _descriptor(
                "first_selector", "time", "utc_start_inclusive", grouped=True
            ),
            "second_selector": _descriptor(
                "second_selector", "time", "utc_start_inclusive", grouped=True
            ),
        },
    ),
)
def test_provider_profile_rejects_invalid_descriptor_registries(descriptors: dict) -> None:
    with pytest.raises(ValueError):
        ProviderProfile(
            kind="synthetic",
            pricing_override_condition_descriptors=descriptors,
        )


@pytest.mark.parametrize(
    "base_paths",
    (
        {"": "pricing.prompt"},
        {"   ": "pricing.prompt"},
        {"prompt": ""},
        {"prompt": "   "},
        {"prompt": None},
        {None: "pricing.prompt"},
    ),
)
def test_provider_profile_rejects_invalid_conditional_base_paths(base_paths: dict) -> None:
    with pytest.raises(ValueError):
        ProviderProfile(kind="synthetic", pricing_override_base_paths=base_paths)


def test_provider_profile_rejects_nonsemantic_conditional_policy_contracts() -> None:
    with pytest.raises(ValueError):
        ProviderProfile(
            kind="synthetic",
            pricing_override_condition_set_semantics="all-day",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        ProviderProfile(
            kind="synthetic",
            pricing_override_policy_semantics="later-wins",  # type: ignore[arg-type]
        )


def test_rich_descriptor_takes_precedence_over_legacy_selector_identity() -> None:
    descriptor = _descriptor(
        "legacy_selector", "threshold", "integer_strictly_greater", grouped=False
    )
    profile = ProviderProfile(
        kind="synthetic",
        pricing_override_condition_fields=("legacy_selector", "fallback_selector"),
        pricing_override_condition_descriptors={"legacy_selector": descriptor},
    )

    assert profile.pricing_override_condition_descriptor("legacy_selector") is descriptor
    assert profile.pricing_override_condition_descriptor("fallback_selector") is None
    assert profile.pricing_override_selector_names == ("legacy_selector", "fallback_selector")


def test_legacy_only_profile_has_selector_identity_without_rich_policy_authority() -> None:
    profile = ProviderProfile(
        kind="legacy-synthetic",
        pricing_override_condition_fields=("legacy_only",),
    )

    assert profile.pricing_override_condition_descriptor("legacy_only") is None
    assert profile.pricing_override_selector_names == ("legacy_only",)
    assert profile.pricing_override_condition_set_semantics is None
    assert profile.pricing_override_policy_semantics is None
    assert profile.pricing_override_base_paths == {}


def test_selector_paths_require_exact_override_rule_namespace_and_active_names() -> None:
    alternate = replace(
        OPENROUTER_PROFILE.pricing_override_condition_descriptors["utc_start"],
        field_name="start_utc",
    )
    rich = replace(
        OPENROUTER_PROFILE,
        pricing_override_condition_fields=(),
        pricing_override_condition_descriptors={"start_utc": alternate},
    )
    legacy = ProviderProfile(
        kind="legacy-selector-synthetic",
        pricing_override_condition_fields=("legacy_selector",),
    )

    assert rich.is_pricing_override_selector_path(
        "pricing.overrides[0].start_utc"
    )
    assert rich.is_pricing_override_selector_path(
        "pricing.overrides[start_utc=100].start_utc"
    )
    assert rich.is_pricing_override_selector_path("pricing.overrides.start_utc")
    assert not rich.is_pricing_override_selector_path("pricing.start_utc")
    assert not rich.is_pricing_override_selector_path(
        "other.pricing.overrides[0].start_utc"
    )
    assert not rich.is_pricing_override_selector_path(
        "pricing.overrides_backup[0].start_utc"
    )
    assert not rich.is_pricing_override_selector_path(
        "pricing.overrides[0].nested.start_utc"
    )
    assert not rich.is_pricing_override_selector_path(
        "pricing.overrides[0].utc_start"
    )
    assert legacy.is_pricing_override_selector_path(
        "pricing.overrides[2].legacy_selector"
    )
    assert OPENROUTER_PROFILE.is_pricing_override_selector_path(
        "pricing.overrides[0].min_prompt_tokens"
    )


def test_openrouter_registers_complete_conditional_pricing_contract() -> None:
    descriptors = OPENROUTER_PROFILE.pricing_override_condition_descriptors

    assert tuple(descriptors) == ("min_prompt_tokens", "utc_days", "utc_start", "utc_end")
    assert {
        name: (descriptor.family, descriptor.semantic_role, descriptor.participates_in_interval_grouping)
        for name, descriptor in descriptors.items()
    } == {
        "min_prompt_tokens": ("threshold", "integer_strictly_greater", False),
        "utc_days": ("time", "utc_weekdays", True),
        "utc_start": ("time", "utc_start_inclusive", True),
        "utc_end": ("time", "utc_end_exclusive", True),
    }
    assert descriptors["min_prompt_tokens"].parse_value(200_000) == 200_000
    assert descriptors["min_prompt_tokens"].canonical_identity(200_000) == 200_000
    assert descriptors["min_prompt_tokens"].format_value(200_000) == "Prompt > 200,000 tokens"
    with pytest.raises(ValueError):
        descriptors["min_prompt_tokens"].parse_value(True)

    weekdays = descriptors["utc_days"]
    parsed_weekdays = weekdays.parse_value(["sunday", "monday", "friday"])
    assert parsed_weekdays == ("monday", "friday", "sunday")
    assert weekdays.canonical_identity(parsed_weekdays) == ("monday", "friday", "sunday")
    assert weekdays.format_value(parsed_weekdays) == "Mon, Fri, Sun"
    for invalid in ([], ["monday", "monday"], ["monday", "funday"], ("monday",)):
        with pytest.raises(ValueError):
            weekdays.parse_value(invalid)

    assert descriptors["utc_start"].parse_value(2359) == 1439
    assert descriptors["utc_start"].format_value(60) == "01:00"
    assert (
        descriptors["utc_start"].canonical_identity(
            descriptors["utc_start"].parse_value(100)
        )
        == 60
    )
    assert descriptors["utc_end"].parse_value(0) == 0
    assert descriptors["utc_start"].format_value(0) == "00:00"
    assert descriptors["utc_end"].format_value(0) == "24:00"
    assert descriptors["utc_end"].format_value(60) == "01:00"
    for invalid in (True, -1, 1260, 2400, "0100"):
        with pytest.raises(ValueError):
            descriptors["utc_start"].parse_value(invalid)

    assert OPENROUTER_PROFILE.pricing_override_condition_set_semantics == _synthetic_condition_set_semantics()
    assert OPENROUTER_PROFILE.pricing_override_policy_semantics == _synthetic_policy_semantics()
    assert OPENROUTER_PROFILE.pricing_override_base_paths == {
        dimension: f"pricing.{dimension}"
        for dimension in OPENROUTER_PROFILE.price_leaf_rules
    }


def test_alternate_raw_selector_profile_uses_only_semantic_roles() -> None:
    profile = ProviderProfile(
        kind="alternate-synthetic",
        pricing_override_condition_fields=(),
        pricing_override_condition_descriptors={
            "minimum_input_units": _descriptor(
                "minimum_input_units", "threshold", "integer_strictly_greater", grouped=False
            ),
            "days_utc": _descriptor("days_utc", "time", "utc_weekdays", grouped=True),
            "from_utc": _descriptor("from_utc", "time", "utc_start_inclusive", grouped=True),
            "until_utc": _descriptor("until_utc", "time", "utc_end_exclusive", grouped=True),
        },
        pricing_override_condition_set_semantics=_synthetic_condition_set_semantics(),
        pricing_override_policy_semantics=_synthetic_policy_semantics(),
        pricing_override_base_paths={"prompt_rate": "pricing.prompt_rate"},
    )

    assert {
        descriptor.semantic_role
        for descriptor in profile.pricing_override_condition_descriptors.values()
    } == {
        "integer_strictly_greater",
        "utc_weekdays",
        "utc_start_inclusive",
        "utc_end_exclusive",
    }
    assert "min_prompt_tokens" not in profile.pricing_override_selector_names
    assert profile.pricing_override_condition_descriptor("from_utc").semantic_role == "utc_start_inclusive"  # type: ignore[union-attr]


def test_synthetic_scheduled_rate_fixture_derives_the_two_exact_movements() -> None:
    old_model, new_model = synthetic_scheduled_rate_models()
    old_pricing = old_model["pricing"]
    new_pricing = new_model["pricing"]
    rules = new_pricing["overrides"]

    assert old_model["id"] == "synthetic/scheduled-rate-demo"
    assert "overrides" not in old_pricing
    assert len(rules) == 6
    assert SYNTHETIC_SCHEDULED_RATE_DIMENSIONS == ("prompt", "completion", "request")
    assert SYNTHETIC_SCHEDULED_RATE_EXPECTED_ACCOUNTING == {
        "policies": 1,
        "source_rules": 6,
        "dimensions": 3,
        "effective_bands": 2,
    }
    with pytest.raises(TypeError):
        SYNTHETIC_SCHEDULED_RATE_EXPECTED_ACCOUNTING["policies"] = 2  # type: ignore[index]

    effective_vectors = {
        tuple(rule.get(dimension, new_pricing[dimension]) for dimension in SYNTHETIC_SCHEDULED_RATE_DIMENSIONS)
        for rule in rules
    }
    assert len(effective_vectors) == 2

    movements_by_dimension = {
        dimension: {
            round(
                (effective_value / old_pricing[dimension] - 1) * 100,
                1,
            )
            for vector in effective_vectors
            for effective_value in (vector[index],)
        }
        for index, dimension in enumerate(SYNTHETIC_SCHEDULED_RATE_DIMENSIONS)
    }
    assert movements_by_dimension == {
        "prompt": {-41.2, 17.6},
        "completion": {-41.2, 17.6},
        "request": {-41.2, 17.6},
    }
    assert rules[0] == {"utc_days": ["saturday", "sunday"], "prompt": 0.00000066}
