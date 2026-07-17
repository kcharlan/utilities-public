from model_sentinel.config import ProviderConfig
from model_sentinel.normalize import normalize_models


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
    )
    model = models[0]
    assert model.input_price == 0.09
    assert model.output_price == 0.18
