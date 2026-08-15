from dataclasses import replace

from model_sentinel.config import ProviderConfig
from model_sentinel.normalize import normalize_models
from model_sentinel.provider_profiles import (
    GENERIC_PROFILE,
    OPENROUTER_PROFILE,
    resolve_profile,
)


def _provider(
    *,
    kind: str = "openrouter",
    multiplier: int = 1_000_000,
    divisor: int = 1,
) -> ProviderConfig:
    return ProviderConfig(
        provider_id="synthetic",
        label="Synthetic Provider",
        kind=kind,
        base_url="https://synthetic.invalid/v1",
        models_path="/models",
        credential_env_var="SYNTHETIC_API_KEY",
        price_multiplier=multiplier,
        price_divisor=divisor,
        enabled=True,
    )


def test_openrouter_pricing_fields_normalize_into_input_output_prices() -> None:
    provider = ProviderConfig(
        provider_id="openrouter",
        label="OpenRouter",
        kind="openrouter",
        base_url="https://openrouter.ai/api/v1",
        models_path="/models",
        credential_env_var="OPENROUTER_AI_CREDS",
        price_multiplier=1000000,
        price_divisor=1,
        enabled=True,
    )
    models = normalize_models(
        provider,
        [
            {
                "id": "openai/gpt-test",
                "name": "GPT Test",
                "pricing": {
                    "prompt": "0.000002",
                    "completion": "0.000008",
                    "input_cache_read": "0.000001",
                    "input_cache_write": "0.000003",
                },
            }
        ],
        resolve_profile(
            provider.kind,
            price_multiplier=provider.price_multiplier,
            price_divisor=provider.price_divisor,
        ),
    )
    model = models[0]
    assert model.input_price == 2
    assert model.output_price == 8
    assert model.cache_read_price == 1
    assert model.cache_write_price == 3


def test_abacus_token_rate_fields_normalize_into_input_output_prices() -> None:
    provider = ProviderConfig(
        provider_id="abacus",
        label="Abacus.AI",
        kind="abacus",
        base_url="https://routellm.abacus.ai/v1",
        models_path="/models",
        credential_env_var="ABACUS_AI_CREDS",
        price_multiplier=1,
        price_divisor=1,
        enabled=True,
    )
    models = normalize_models(
        provider,
        [
            {
                "id": "Qwen/Qwen3-32B",
                "name": "Qwen/Qwen3-32B",
                "input_token_rate": 0.09,
                "output_token_rate": 0.18,
            }
        ],
        resolve_profile(
            provider.kind,
            price_multiplier=provider.price_multiplier,
            price_divisor=provider.price_divisor,
        ),
    )
    model = models[0]
    assert model.input_price == 0.09
    assert model.output_price == 0.18


def test_profile_candidates_preserve_truthy_or_chain_semantics() -> None:
    provider = ProviderConfig(
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

    model = normalize_models(
        provider,
        [
            {
                "id": "synthetic/model-a",
                "context_length": 0,
                "context_window": 128,
            }
        ],
        GENERIC_PROFILE,
    )[0]

    assert model.context_window == 128


def test_openrouter_token_normalization_uses_explicit_field_rule() -> None:
    provider = _provider(multiplier=7, divisor=3)
    profile = resolve_profile(
        provider.kind,
        price_multiplier=provider.price_multiplier,
        price_divisor=provider.price_divisor,
    )

    model = normalize_models(
        provider,
        [
            {
                "id": "synthetic/model-token",
                "pricing": {
                    "prompt": "0.000002",
                    "completion": "0.000008",
                    "input_cache_read": "0.000001",
                    "input_cache_write": "0.000003",
                },
            }
        ],
        profile,
    )[0]

    assert model.input_price == 2
    assert model.output_price == 8
    assert model.cache_read_price == 1
    assert model.cache_write_price == 3


def test_operation_price_candidate_cannot_populate_token_snapshot_column() -> None:
    provider = _provider()
    profile = replace(
        OPENROUTER_PROFILE,
        normalized_fields={
            **OPENROUTER_PROFILE.normalized_fields,
            "input_price": (("pricing", "web_search"),),
        },
    )

    model = normalize_models(
        provider,
        [
            {
                "id": "synthetic/model-search",
                "pricing": {"web_search": "0.014"},
            }
        ],
        profile,
    )[0]

    assert model.input_price is None


def test_unknown_openrouter_price_cannot_populate_token_snapshot_column() -> None:
    provider = _provider()
    profile = replace(
        OPENROUTER_PROFILE,
        normalized_fields={
            **OPENROUTER_PROFILE.normalized_fields,
            "input_price": (("pricing", "input_cache_write_1h"),),
        },
    )

    model = normalize_models(
        provider,
        [
            {
                "id": "synthetic/model-unknown-unit",
                "pricing": {"input_cache_write_1h": "0.25"},
            }
        ],
        profile,
    )[0]

    assert model.input_price is None


def test_price_candidate_resolution_uses_the_selected_truthy_path() -> None:
    provider = _provider()
    profile = replace(
        OPENROUTER_PROFILE,
        normalized_fields={
            **OPENROUTER_PROFILE.normalized_fields,
            "input_price": (
                ("pricing", "web_search"),
                ("pricing", "prompt"),
            ),
        },
    )

    model = normalize_models(
        provider,
        [
            {
                "id": "synthetic/model-candidate-fallback",
                "pricing": {
                    "web_search": 0,
                    "prompt": "0.000002",
                },
            }
        ],
        profile,
    )[0]

    assert model.input_price == 2
