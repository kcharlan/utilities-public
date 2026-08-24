from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from model_sentinel.config import ProviderConfig
from model_sentinel.models import NormalizedModel
from model_sentinel.storage import Store
from tests.browse_fixtures import _save_scrape


VALIDATION_PROVIDER = ProviderConfig(
    provider_id="validation",
    label="Synthetic Validation Provider",
    kind="openrouter",
    base_url="https://synthetic-validation.example.invalid/api/v1",
    models_path="/models",
    credential_env_var="SYNTHETIC_MODEL_SENTINEL_TOKEN",
    price_multiplier=1_000_000,
    price_divisor=1,
    enabled=True,
)

_GIT_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SCRAPE_TIMESTAMPS = tuple(
    f"2040-02-{day:02d}T15:00:00+00:00" for day in range(1, 6)
)
_MODEL_IDS = tuple(
    f"synthetic-lab/comparator-{number:02d}" for number in range(1, 9)
)
_CHANGING_INPUT_PRICES = (
    1.000001,
    1.000002,
    1.000003,
    1.000004,
    1.000005,
)


def _prepare_empty_runtime_home(runtime_home: Path) -> Path:
    resolved = runtime_home.expanduser().resolve()
    if resolved == _GIT_REPOSITORY_ROOT or _GIT_REPOSITORY_ROOT in resolved.parents:
        raise ValueError(
            f"Synthetic validation runtime must be outside the git repository: {resolved}"
        )
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise ValueError(
                f"Synthetic validation runtime must be a new or empty directory: {resolved}"
            )
    else:
        resolved.mkdir(parents=True)
    return resolved


def _write_config(runtime_home: Path) -> None:
    (runtime_home / "providers.env").write_text(
        "MODEL_SENTINEL_PROVIDER_VALIDATION_ENABLED=1\n"
        "MODEL_SENTINEL_PROVIDER_VALIDATION_LABEL=Synthetic Validation Provider\n"
        "MODEL_SENTINEL_PROVIDER_VALIDATION_KIND=openrouter\n"
        "MODEL_SENTINEL_PROVIDER_VALIDATION_BASE_URL="
        "https://synthetic-validation.example.invalid/api/v1\n"
        "MODEL_SENTINEL_PROVIDER_VALIDATION_MODELS_PATH=/models\n"
        "MODEL_SENTINEL_PROVIDER_VALIDATION_API_KEY_ENV="
        "SYNTHETIC_MODEL_SENTINEL_TOKEN\n"
        "MODEL_SENTINEL_PROVIDER_VALIDATION_PRICE_MULTIPLIER=1000000\n"
        "MODEL_SENTINEL_PROVIDER_VALIDATION_PRICE_DIVISOR=1\n",
        encoding="utf-8",
    )
    (runtime_home / "settings.env").write_text(
        "MODEL_SENTINEL_LOG_MAX_BYTES=1048576\n"
        "MODEL_SENTINEL_LOG_KEEP_FILES=1\n"
        "MODEL_SENTINEL_REPORT_DIR=synthetic-reports\n"
        "MODEL_SENTINEL_NOTIFY_DEFAULT=0\n"
        "MODEL_SENTINEL_NOTIFY_ON=never\n"
        "MODEL_SENTINEL_NOTIFY_OPEN_TARGET=folder\n",
        encoding="utf-8",
    )


def _raw_models(scrape_index: int) -> list[dict[str, object]]:
    raw_models: list[dict[str, object]] = []
    for model_number, model_id in enumerate(_MODEL_IDS, start=1):
        if scrape_index == 2 and model_number == 8:
            continue
        input_price = (
            _CHANGING_INPUT_PRICES[scrape_index]
            if model_number == 1
            else 1 + model_number / 1_000_000
        )
        raw_models.append(
            {
                "id": model_id,
                "name": f"Synthetic Validation Comparator {model_number:02d}",
                "description": (
                    "Conspicuously synthetic model-view browser validation data."
                ),
                "model_family": "synthetic-validation-comparator",
                "pricing": {
                    "prompt": input_price / 1_000_000,
                    "completion": (2 + model_number / 1_000_000) / 1_000_000,
                },
                "context_length": 32_000 + model_number,
                "top_provider": {"max_completion_tokens": 4_000 + model_number},
                "supported_parameters": ["tools"],
                "status": "synthetic-validation-only",
            }
        )
    return raw_models


def build_model_view_validation_home(runtime_home: Path) -> Path:
    """Create an isolated runtime containing deterministic synthetic browse data."""
    runtime_home = _prepare_empty_runtime_home(runtime_home)
    _write_config(runtime_home)

    store = Store(runtime_home / "model_sentinel.db")
    store.initialize()
    store.upsert_provider_configs(
        (VALIDATION_PROVIDER,),
        updated_at=_SCRAPE_TIMESTAMPS[0],
    )

    previous_id: int | None = None
    previous_models: list[NormalizedModel] = []
    for scrape_index, completed_at in enumerate(_SCRAPE_TIMESTAMPS):
        previous_id, previous_models = _save_scrape(
            store,
            VALIDATION_PROVIDER,
            completed_at=completed_at,
            raw_models=_raw_models(scrape_index),
            previous_id=previous_id,
            previous_models=previous_models,
        )
    return runtime_home


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build isolated synthetic Model Sentinel browser validation data."
    )
    parser.add_argument("runtime_home", type=Path)
    args = parser.parse_args(argv)
    print(build_model_view_validation_home(args.runtime_home))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
