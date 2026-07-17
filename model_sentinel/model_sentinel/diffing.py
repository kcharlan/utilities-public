from __future__ import annotations

from typing import Any

from .models import FieldChange, ModelDelta, NormalizedModel
from .normalize import metadata_for_comparison


def compare_models(
    *,
    baseline_models: dict[str, NormalizedModel],
    current_models: dict[str, NormalizedModel],
) -> tuple[tuple[ModelDelta, ...], tuple[ModelDelta, ...], tuple[ModelDelta, ...]]:
    added: list[ModelDelta] = []
    removed: list[ModelDelta] = []
    changed: list[ModelDelta] = []

    baseline_ids = set(baseline_models)
    current_ids = set(current_models)

    for model_id in sorted(current_ids - baseline_ids):
        current = current_models[model_id]
        added.append(ModelDelta("added", model_id, current.display_name, ()))

    for model_id in sorted(baseline_ids - current_ids):
        baseline = baseline_models[model_id]
        removed.append(ModelDelta("removed", model_id, baseline.display_name, ()))

    for model_id in sorted(baseline_ids & current_ids):
        baseline = baseline_models[model_id]
        current = current_models[model_id]
        field_changes = tuple(
            FieldChange(path, old_value, new_value)
            for path, old_value, new_value in _diff_values(
                metadata_for_comparison(baseline),
                metadata_for_comparison(current),
            )
        )
        if field_changes:
            changed.append(ModelDelta("changed", model_id, current.display_name, field_changes))

    return tuple(added), tuple(removed), tuple(changed)


def _diff_values(old_value: Any, new_value: Any, prefix: str = "") -> list[tuple[str, Any, Any]]:
    if isinstance(old_value, dict) and isinstance(new_value, dict):
        changes: list[tuple[str, Any, Any]] = []
        for key in sorted(set(old_value) | set(new_value)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in old_value:
                changes.append((path, None, new_value[key]))
                continue
            if key not in new_value:
                changes.append((path, old_value[key], None))
                continue
            changes.extend(_diff_values(old_value[key], new_value[key], path))
        return changes
    if old_value != new_value:
        return [(prefix or "value", old_value, new_value)]
    return []

