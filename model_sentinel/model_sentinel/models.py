from __future__ import annotations

import json
from collections.abc import Mapping
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


@dataclass(frozen=True)
class EndpointMapping:
    """How one catalog model reaches its endpoint list in one capture.

    `outcome` is `listed`, `alias`, `no_link`, or `invalid_link`. `list_path` is
    the model's own validated path when listed, or the final listed path an
    alias chain resolves to, else None. `alias_target_model_id` is an alias's
    direct target; `resolved_target_model_id` is the listed catalog model its
    chain ends at. `error_code` is None for a listed model or resolved alias;
    otherwise it names why no list is available: `no_link` or `invalid_link`
    for those outcomes, and `alias_target_missing`, `alias_cycle`, or the
    terminal model's `no_link`/`invalid_link` for an unresolved alias.
    """

    provider_model_id: str
    outcome: str
    list_path: str | None
    alias_target_model_id: str | None
    resolved_target_model_id: str | None
    error_code: str | None

    @property
    def is_failure(self) -> bool:
        """True when this mapping counts toward a capture's `mapping_failures`."""
        return self.error_code is not None


@dataclass(frozen=True)
class EndpointPathResult:
    """The fetch outcome for one distinct endpoint-list path.

    `outcome` is `ok` (nonempty endpoint array), `empty` (valid empty array),
    or `error`. `list_model_id` is the response's `data.id` when supplied.
    `error_code`, a bounded sanitized `error_message`, and `http_status` (for
    HTTP and redirect errors) are set only for errors.
    """

    list_path: str
    list_model_id: str | None
    outcome: str
    endpoints: tuple[dict[str, Any], ...]
    error_code: str | None
    error_message: str | None
    http_status: int | None

    @property
    def endpoint_count(self) -> int:
        return len(self.endpoints)

    @property
    def display_id(self) -> str:
        """The response model ID, or the path when the response did not supply one."""
        return self.list_model_id or self.list_path


@dataclass(frozen=True)
class EndpointFetchResult:
    """One provider's endpoint-list capture before persistence.

    `mappings` holds one record per catalog model and `paths` one record per
    distinct planned path, both sorted. `paths_requested` counts planned paths
    (including unsent `budget_exceeded` ones), `paths_attempted` counts paths
    actually sent (retries excluded), `paths_failed` counts `error` paths, and
    `mapping_failures` counts failed mappings. `bodies` holds the decoded
    response body of each `ok`/`empty` path, keyed by path, for the archive.
    Timestamps are UTC ISO-8601 strings.
    """

    provider_id: str
    started_at: str
    completed_at: str
    mappings: tuple[EndpointMapping, ...]
    paths: tuple[EndpointPathResult, ...]
    paths_requested: int
    paths_attempted: int
    paths_failed: int
    mapping_failures: int
    bodies: dict[str, Any]


@dataclass(frozen=True)
class EndpointObservationRecord:
    """One endpoint in a saved list: its key, stable state and status.

    `state` is the decoded stable state (telemetry and status removed) and
    `state_hash` its SHA-256 identity. `status_code` is the endpoint's status
    when it is an integer, else None.
    """

    endpoint_key: str
    state_hash: str
    state: dict[str, Any]
    status_code: int | None


@dataclass(frozen=True)
class EndpointListRecord:
    """One endpoint-list path in a capture, with its outcome and observations.

    `model_ids` are the catalog models whose `listed` mapping is this path,
    sorted. `list_model_id` is the response `data.id` when supplied.
    `error_code` and `error_message` are set only for an `error` outcome.
    `observations` keep response order and are empty for an error.
    """

    list_path: str
    list_model_id: str | None
    outcome: str
    endpoint_count: int
    error_code: str | None
    error_message: str | None
    model_ids: tuple[str, ...]
    observations: tuple[EndpointObservationRecord, ...]

    @property
    def display_id(self) -> str:
        """The response model ID, or the path when the response did not supply one."""
        return self.list_model_id or self.list_path

    @property
    def succeeded(self) -> bool:
        """True for an `ok` or `empty` observation, which is evidence of the list."""
        return self.outcome in ("ok", "empty")


@dataclass(frozen=True)
class EndpointChangeRecord:
    """One endpoint change between the selected baseline capture and this one.

    The comparison identity is (`from_capture_id`, `to_capture_id`,
    `from_list_path`, `list_path`, `endpoint_key`, `change_kind`,
    `field_name`). `from_list_path` equals `list_path` for a shared path and
    preserves the old path for a moved one. `to_capture_id` is None until the
    capture is persisted. `display_id` and `model_ids` describe the current
    list; values are decoded.
    """

    from_capture_id: int
    to_capture_id: int | None
    from_list_path: str
    list_path: str
    endpoint_key: str
    change_kind: str
    field_name: str | None
    old_value: Any
    new_value: Any
    display_id: str
    model_ids: tuple[str, ...]


@dataclass(frozen=True)
class EndpointComparisonGap:
    """A list whose comparison could not be made, and why.

    `list_path` is the current path, or the baseline path for a path that
    disappeared. `from_list_path` is the baseline path involved, when one is.
    """

    list_path: str
    reason: str
    from_list_path: str | None


@dataclass(frozen=True)
class EndpointCaptureSummary:
    """One provider's endpoint capture, in memory or as persisted.

    Identity and status fields mirror `endpoint_captures`. `capture_id` is
    None before persistence or when persistence failed, and `first_capture` is
    None until persistence assigns it. `persistence_error` is set only on an
    in-memory summary that could not be saved.
    """

    capture_id: int | None
    scrape_id: int
    provider_id: str
    started_at: str
    completed_at: str
    status: str
    paths_requested: int
    paths_attempted: int
    paths_failed: int
    mapping_failures: int
    first_capture: bool | None
    comparison_state: str
    baseline_capture_id: int | None
    error_summary: str | None
    persistence_error: str | None = None
    changes: tuple[EndpointChangeRecord, ...] = ()
    comparison_gaps: tuple[EndpointComparisonGap, ...] = ()
    lists: tuple[EndpointListRecord, ...] = ()


@dataclass(frozen=True)
class EndpointCaptureCandidate:
    """Everything `Store.save_endpoint_capture` writes for one capture.

    `summary` is the in-memory summary; `mappings` are the capture's catalog
    mapping records; `archive` holds the decoded response bodies keyed by path.
    """

    summary: EndpointCaptureSummary
    mappings: tuple[EndpointMapping, ...]
    archive: Mapping[str, Any]
