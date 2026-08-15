from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from model_sentinel.config import ProviderConfig
from model_sentinel.provider_profiles import (
    GENERIC_PROFILE,
    OPENROUTER_PROFILE,
    PER_MILLION_TOKENS_TARGET,
    USD_PER_MILLION_TOKENS_GROUP,
    PriceDisplayRule,
    ProviderProfile,
    default_categorize,
    default_is_price_amount_field,
    resolve_profile,
)
from model_sentinel.providers import ProviderFetchError, extract_model_list


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
