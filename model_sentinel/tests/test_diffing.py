from model_sentinel.diffing import compare_models
from model_sentinel.models import NormalizedModel


def _model(model_id: str, *, display_name: str, payload: dict) -> NormalizedModel:
    from model_sentinel.models import canonical_json

    return NormalizedModel(
        provider_id="openrouter",
        provider_label="OpenRouter",
        provider_model_id=model_id,
        display_name=display_name,
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
        metadata_json=canonical_json(payload),
    )


def test_compare_models_detects_add_remove_and_field_changes() -> None:
    baseline = {
        "a": _model("a", display_name="A", payload={"id": "a", "pricing": {"input": "0.1"}}),
        "b": _model("b", display_name="B", payload={"id": "b"}),
    }
    current = {
        "a": _model("a", display_name="A", payload={"id": "a", "pricing": {"input": "0.2"}}),
        "c": _model("c", display_name="C", payload={"id": "c"}),
    }
    added, removed, changed = compare_models(baseline_models=baseline, current_models=current)
    assert [delta.provider_model_id for delta in added] == ["c"]
    assert [delta.provider_model_id for delta in removed] == ["b"]
    assert [delta.provider_model_id for delta in changed] == ["a"]
    assert changed[0].field_changes[0].field_name == "pricing.input"

