from dataclasses import FrozenInstanceError

import pytest

from model_sentinel.provider_profiles import (
    GENERIC_PROFILE,
    OPENROUTER_PROFILE,
    default_categorize,
    default_is_price_amount_field,
    resolve_profile,
)


def test_resolve_openrouter_profile_with_bound_pricing() -> None:
    profile = resolve_profile(
        "OPENROUTER",
        price_multiplier=1_000_000,
        price_divisor=2,
    )

    assert profile.kind == OPENROUTER_PROFILE.kind
    assert profile.field_path_labels is OPENROUTER_PROFILE.field_path_labels
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


def test_default_heuristics_preserve_existing_behavior() -> None:
    assert default_categorize("pricing.prompt") == "Pricing"
    assert default_is_price_amount_field("input_token_rate") is False
