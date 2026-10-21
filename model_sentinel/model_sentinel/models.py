from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .provider_profiles import ProviderProfile


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class NormalizedModel:
    provider_id: str
    provider_label: str
    provider_model_id: str
    display_name: str
    description: str | None
    model_family: str | None
    created_at_provider: str | None
    context_window: int | None
    max_output_tokens: int | None
    input_price: float | None
    output_price: float | None
    cache_read_price: float | None
    cache_write_price: float | None
    reasoning_supported: bool | None
    tool_calling_supported: bool | None
    vision_supported: bool | None
    audio_supported: bool | None
    image_supported: bool | None
    structured_output_supported: bool | None
    deprecated: bool | None
    status: str | None
    metadata_json: str

    def metadata(self) -> dict[str, Any]:
        return json.loads(self.metadata_json)


@dataclass(frozen=True)
class FieldChange:
    field_name: str
    old_value: Any
    new_value: Any


@dataclass(frozen=True)
class ModelDelta:
    kind: str
    provider_model_id: str
    display_name: str
    field_changes: tuple[FieldChange, ...]


@dataclass(frozen=True)
class BaselineInfo:
    scrape_id: int
    completed_at: str


@dataclass(frozen=True)
class ProviderScanResult:
    provider_id: str
    provider_label: str
    status: str
    current_count: int
    saved: bool
    baseline: BaselineInfo | None
    baseline_message: str | None
    scrape_id: int | None
    added: tuple[ModelDelta, ...]
    removed: tuple[ModelDelta, ...]
    changed: tuple[ModelDelta, ...]
    profile: ProviderProfile
    error_message: str | None = None

    @property
    def change_count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed)


@dataclass(frozen=True)
class HistoryEvent:
    detected_at: str
    change_kind: str
    field_name: str | None
    old_value: Any
    new_value: Any


@dataclass(frozen=True)
class EndpointChange:
    """One difference between two captures of a single provider endpoint.

    `change_kind` is one of `endpoint_added`, `endpoint_removed`,
    `field_changed`, or `status_changed`. `field_name` is a dotted path for
    `field_changed` and None for the other kinds. For `endpoint_added` and
    `endpoint_removed` the added or removed side carries the endpoint's stable
    state and the other side is None; for `status_changed` the values are the
    two status values.
    """

    endpoint_key: str
    change_kind: str
    field_name: str | None
    old_value: Any
    new_value: Any
