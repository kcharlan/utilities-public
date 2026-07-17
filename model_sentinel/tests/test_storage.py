from datetime import date
from pathlib import Path

from model_sentinel.models import NormalizedModel, canonical_json
from model_sentinel.storage import Store


def _model(model_id: str) -> NormalizedModel:
    return NormalizedModel(
        provider_id="openrouter",
        provider_label="OpenRouter",
        provider_model_id=model_id,
        display_name=model_id.upper(),
        description=None,
        model_family=None,
        created_at_provider=None,
        context_window=None,
        max_output_tokens=None,
        input_price=None,
        output_price=None,
        cache_read_price=None,
        cache_write_price=None,
        reasoning_supported=None,
        tool_calling_supported=None,
        vision_supported=None,
        audio_supported=None,
        image_supported=None,
        structured_output_supported=None,
        deprecated=None,
        status=None,
        metadata_json=canonical_json({"id": model_id}),
    )


def test_store_saves_and_loads_baselines(tmp_path: Path) -> None:
    store = Store(tmp_path / "sentinel.db")
    store.initialize()
    store.create_scrape(
        provider_id="openrouter",
        started_at="2025-01-01T09:00:00-05:00",
        completed_at="2025-01-01T09:05:00-05:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=1,
        error_message=None,
    )
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2025-01-02T09:00:00-05:00",
        completed_at="2025-01-02T09:05:00-05:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=1,
        saved_snapshot=True,
        model_count=1,
        error_message=None,
    )
    store.save_snapshot_models(scrape_id=scrape_id, provider_id="openrouter", models=[_model("x")])
    latest = store.get_latest_saved_baseline("openrouter")
    assert latest is not None
    assert latest.scrape_id == 2
    prior_day = store.get_previous_day_baseline("openrouter", current_date=date(2025, 1, 3))
    assert prior_day is not None
    assert prior_day.scrape_id == 2
    loaded = store.load_saved_models(scrape_id)
    assert list(loaded) == ["x"]
    known_models = store.list_known_models(provider_id="openrouter", since=None, until=None)
    assert len(known_models) == 1
    assert known_models[0]["provider_model_id"] == "x"


def test_scrape_timestamps_are_normalized_to_utc(tmp_path: Path) -> None:
    store = Store(tmp_path / "sentinel.db")
    store.initialize()
    scrape_id = store.create_scrape(
        provider_id="openrouter",
        started_at="2025-01-01T09:00:00-05:00",
        completed_at="2025-01-01T09:05:00-05:00",
        status="success",
        baseline_mode="previous",
        baseline_scrape_id=None,
        saved_snapshot=True,
        model_count=0,
        error_message=None,
    )
    with store._connect() as connection:
        row = connection.execute(
            "SELECT started_at, completed_at FROM scrapes WHERE scrape_id = ?",
            (scrape_id,),
        ).fetchone()
    assert row["started_at"] == "2025-01-01T14:00:00+00:00"
    assert row["completed_at"] == "2025-01-01T14:05:00+00:00"
