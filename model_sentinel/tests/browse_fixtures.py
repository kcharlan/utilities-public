from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from model_sentinel.config import ProviderConfig
from model_sentinel.diffing import compare_models
from model_sentinel.models import NormalizedModel
from model_sentinel.normalize import normalize_models
from model_sentinel.provider_profiles import resolve_profile
from model_sentinel.storage import Store
from model_sentinel.time_utils import local_date_for


@dataclass(frozen=True)
class FixtureFacts:
    provider_ids: tuple[str, ...]
    scrape_ids: tuple[int, ...]
    scrape_dates: tuple[date, ...]
    model_ids: tuple[str, ...]
    added_model: str
    added_at_scrape: int
    removed_model: str
    removed_at_scrape: int
    price_step: tuple[str, int, int, float, float, float, float]
    context_step: tuple[str, int, int, int, int]
    bool_flip: tuple[str, int, int, bool, bool]
    bulk_list_models: tuple[str, ...]
    benchmark_churn_model: str


EXAMPLE_PROVIDER = ProviderConfig(
    provider_id="example-provider",
    label="Example Provider",
    kind="openrouter",
    base_url="https://example.invalid/api/v1",
    models_path="/models",
    credential_env_var="EXAMPLE_PROVIDER_FAKE_TOKEN",
    price_multiplier=1_000_000,
    price_divisor=1,
    enabled=True,
)
OTHER_PROVIDER = ProviderConfig(
    provider_id="other-provider",
    label="Other Provider",
    kind="generic",
    base_url="https://other.invalid/api",
    models_path="/models",
    credential_env_var="OTHER_PROVIDER_FAKE_TOKEN",
    price_multiplier=1,
    price_divisor=1,
    enabled=True,
)


def _raw_model(model_id: str, scrape_number: int) -> dict[str, object]:
    suffix = model_id.rsplit("-", 1)[-1]
    supported = ["tools"]
    if scrape_number >= 6 and suffix in {"a", "b", "c"}:
        supported.append("reasoning_effort")
    prompt = 0.0000035 if suffix == "a" and scrape_number >= 3 else 0.000002
    context_length = 256_000 if suffix == "b" and scrape_number >= 4 else 128_000
    return {
        "id": model_id,
        "name": f"Synthetic Test Model {suffix.upper()}",
        "pricing": {"prompt": prompt, "completion": 0.000008},
        "context_length": context_length,
        "top_provider": {"max_completion_tokens": 16_384},
        "supported_parameters": supported,
        "reasoning": suffix == "c" and scrape_number >= 5,
        "benchmarks": {
            "design_arena": {
                "score": 1000 + scrape_number if suffix == "a" else 900,
            }
        },
    }


def _example_raw_models(scrape_number: int) -> list[dict[str, object]]:
    suffixes = ["a", "b", "c", "e"]
    if scrape_number >= 4:
        suffixes.append("d")
    if scrape_number >= 5:
        suffixes.remove("e")
    return [_raw_model(f"fake-org/test-model-{suffix}", scrape_number) for suffix in suffixes]


def _save_scrape(
    store: Store,
    provider: ProviderConfig,
    *,
    completed_at: str,
    raw_models: list[dict[str, object]],
    previous_id: int | None,
    previous_models: list[NormalizedModel],
) -> tuple[int, list[NormalizedModel]]:
    profile = resolve_profile(
        provider.kind,
        price_multiplier=provider.price_multiplier,
        price_divisor=provider.price_divisor,
    )
    models = normalize_models(provider, raw_models, profile)
    scrape_id = store.create_scrape(
        provider_id=provider.provider_id,
        started_at=completed_at,
        completed_at=completed_at,
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=previous_id,
        saved_snapshot=True,
        model_count=len(models),
        error_message=None,
    )
    store.save_snapshot_models(
        scrape_id=scrape_id,
        provider_id=provider.provider_id,
        models=models,
    )
    added, removed, changed = compare_models(
        baseline_models={model.provider_model_id: model for model in previous_models},
        current_models={model.provider_model_id: model for model in models},
    )
    store.record_field_changes(
        provider_id=provider.provider_id,
        from_scrape_id=previous_id,
        to_scrape_id=scrape_id,
        deltas=added + removed + changed,
        detected_at=completed_at,
    )
    return scrape_id, models


def build_fixture_db(path: Path) -> FixtureFacts:
    store = Store(path)
    store.initialize()
    store.upsert_provider_configs(
        (EXAMPLE_PROVIDER, OTHER_PROVIDER),
        updated_at="2026-08-01T12:00:00+00:00",
    )

    example_times = tuple(f"2026-08-{day:02d}T12:00:00+00:00" for day in range(10, 16))
    example_ids: list[int] = []
    previous_id: int | None = None
    previous_models: list[NormalizedModel] = []
    for number, completed_at in enumerate(example_times, start=1):
        scrape_id, previous_models = _save_scrape(
            store,
            EXAMPLE_PROVIDER,
            completed_at=completed_at,
            raw_models=_example_raw_models(number),
            previous_id=previous_id,
            previous_models=previous_models,
        )
        example_ids.append(scrape_id)
        previous_id = scrape_id

    store.create_scrape(
        provider_id=EXAMPLE_PROVIDER.provider_id,
        started_at="2026-08-17T12:00:00+00:00",
        completed_at="2026-08-17T12:00:01+00:00",
        status="error",
        baseline_mode="previous",
        baseline_scrape_id=previous_id,
        saved_snapshot=False,
        model_count=0,
        error_message="Synthetic provider failure",
    )

    other_raw = [
        {
            "id": "fake-org/other-test-model",
            "name": "Synthetic Other Test Model",
            "pricing": {"prompt": 1, "completion": 2},
            "context_length": 4096,
            "top_provider": {"max_completion_tokens": 1024},
            "supported_parameters": [],
            "benchmarks": {"design_arena": {"score": 500}},
        }
    ]
    other_first, other_models = _save_scrape(
        store,
        OTHER_PROVIDER,
        completed_at="2026-08-18T12:00:00+00:00",
        raw_models=other_raw,
        previous_id=None,
        previous_models=[],
    )
    _save_scrape(
        store,
        OTHER_PROVIDER,
        completed_at="2026-08-18T12:20:00+00:00",
        raw_models=other_raw,
        previous_id=other_first,
        previous_models=other_models,
    )

    ids = tuple(example_ids)
    return FixtureFacts(
        provider_ids=(EXAMPLE_PROVIDER.provider_id, OTHER_PROVIDER.provider_id),
        scrape_ids=ids,
        scrape_dates=tuple(local_date_for(value) for value in example_times),
        model_ids=tuple(f"fake-org/test-model-{suffix}" for suffix in "abcde"),
        added_model="fake-org/test-model-d",
        added_at_scrape=ids[3],
        removed_model="fake-org/test-model-e",
        removed_at_scrape=ids[4],
        price_step=("fake-org/test-model-a", ids[1], ids[2], 0.000002, 0.0000035, 2.0, 3.5),
        context_step=("fake-org/test-model-b", ids[2], ids[3], 128_000, 256_000),
        bool_flip=("fake-org/test-model-c", ids[3], ids[4], False, True),
        bulk_list_models=tuple(f"fake-org/test-model-{suffix}" for suffix in "abc"),
        benchmark_churn_model="fake-org/test-model-a",
    )


def decoded_change_rows(path: Path) -> tuple[dict[str, object], ...]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM field_changes ORDER BY change_id").fetchall()
    return tuple(
        {
            **dict(row),
            "old_value": json.loads(row["old_value_json"]) if row["old_value_json"] is not None else None,
            "new_value": json.loads(row["new_value_json"]) if row["new_value_json"] is not None else None,
        }
        for row in rows
    )
