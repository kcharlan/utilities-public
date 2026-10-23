from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple

from .provider_profiles import ProviderProfile


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def mutable_json_value(value: Any) -> Any:
    """Detach JSON operands from mutable or frozen source containers."""
    if isinstance(value, Mapping):
        return {key: mutable_json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [mutable_json_value(child) for child in value]
    return value


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
    # This scan's endpoint capture, success or failure, when one was eligible.
    # It never contributes to `change_count`.
    endpoint_capture: EndpointCaptureSummary | None = None
    # Alias divergence events between the selected baseline snapshot and this
    # catalog, for capable profiles. Like `endpoint_capture`, they never
    # contribute to `change_count`, notifications or Price Movement.
    alias_events: tuple[AliasEvent, ...] = ()

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
    `list_error_code` is the error code of the list an `*_observation_failed`
    gap names: the current list, or the baseline list at `from_list_path`. It
    tells a list never sent (`budget_exceeded`) from one that failed to fetch.
    It is not stored; storage reads it from that saved list.
    """

    list_path: str
    reason: str
    from_list_path: str | None
    list_error_code: str | None = None


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
class EndpointTelemetryRecord:
    """Rolling-window samples and present raw telemetry for one keyed endpoint."""

    list_path: str
    endpoint_key: str
    uptime_5m: int | float | None
    uptime_30m: int | float | None
    uptime_1d: int | float | None
    telemetry: Mapping[str, Any]


@dataclass(frozen=True)
class EndpointCaptureCandidate:
    """Everything `Store.save_endpoint_capture` writes for one capture.

    `summary` is the in-memory summary; `mappings` are the capture's catalog
    mapping records; `archive` holds the decoded response bodies keyed by path.
    """

    summary: EndpointCaptureSummary
    mappings: tuple[EndpointMapping, ...]
    archive: Mapping[str, Any]
    telemetry: tuple[EndpointTelemetryRecord, ...] = ()


@dataclass(frozen=True)
class AliasLeafComparison:
    """One price leaf an alias and its target both resolve to one identity.

    Both sides resolve strictly with the same `unit_label` and
    `comparison_group`. Values are kept JSON-safe: `*_raw` are the provider
    spellings, `*_exact` the exact normalized values as reduced fraction
    strings (for example `"3"` or `"1/2"`), and `*_display` the normalized
    prices formatted together at one shared precision. `equal` compares the
    exact values.
    """

    path: str
    label: str
    unit_label: str
    comparison_group: str | None
    alias_raw: Any
    target_raw: Any
    alias_exact: str
    target_exact: str
    alias_display: str
    target_display: str
    equal: bool


@dataclass(frozen=True)
class AliasUnavailableLeaf:
    """A catalog price leaf that is outside an alias's comparison set.

    `alias_state` and `target_state` are each `resolved`, `unresolved`, or
    `missing`. `reason` is `missing` when either side lacks the leaf,
    `unresolved` when either side has no strict price identity, and
    `incompatible` when both resolve with different unit or comparison-group
    identities. Raw values are None for a missing side; unit and group are set
    only for a resolved side.
    """

    path: str
    label: str
    reason: str
    alias_state: str
    target_state: str
    alias_raw: Any
    target_raw: Any
    alias_unit_label: str | None
    target_unit_label: str | None
    alias_comparison_group: str | None
    target_comparison_group: str | None


@dataclass(frozen=True)
class AliasDivergence:
    """The compared leaves where an alias's price differs from its target's."""

    target_model_id: str
    leaves: tuple[AliasLeafComparison, ...]

    @property
    def signature(self) -> tuple[str, tuple[tuple[str, str, str, str, str | None], ...]]:
        """The semantic identity of this divergence.

        It is the target ID plus, for each differing leaf sorted by path, the
        exact normalized alias and target values with their unit and group.
        Raw spelling and endpoint-match evidence play no part.
        """
        return (
            self.target_model_id,
            tuple(
                sorted(
                    (
                        leaf.path,
                        leaf.alias_exact,
                        leaf.target_exact,
                        leaf.unit_label,
                        leaf.comparison_group,
                    )
                    for leaf in self.leaves
                )
            ),
        )


@dataclass(frozen=True)
class AliasEndpointMatch:
    """Which endpoints of an alias's target list carry the alias's prices.

    Each candidate is judged on the fixed `compared_leaves` paths: one proven
    unequal leaf puts its key in `differing_keys`; otherwise it is in
    `matching_keys` only when every leaf is resolved, compatible and equal, and
    in `unknown_keys` when any is missing, unresolved or incompatible. Keys
    keep list order. A match is a claim about the named leaves only.
    `unavailable_reason` is None when the list was evaluated (a successful
    empty list has no candidates); `list_path`, `list_outcome` and
    `list_error_code` describe the list used, when one was found.
    """

    compared_leaves: tuple[str, ...]
    matching_keys: tuple[str, ...]
    differing_keys: tuple[str, ...]
    unknown_keys: tuple[str, ...]
    unavailable_reason: str | None
    list_path: str | None
    list_outcome: str | None
    list_error_code: str | None = None


@dataclass(frozen=True)
class AliasEvaluation:
    """One catalog alias compared with the model its alias chain resolves to.

    `alias_target_model_id` is the direct target (None for a malformed
    declaration) and `target_model_id` the terminal catalog model of the
    chain, or None with `unavailable_reason` set when the chain is unresolved.
    `compared_leaves` is the fixed comparison set in profile price order;
    `unavailable_leaves` keeps the other catalog leaves as evidence.
    `divergence` is set when any compared leaf differs.
    """

    alias_model_id: str
    alias_target_model_id: str | None
    target_model_id: str | None
    unavailable_reason: str | None
    compared_leaves: tuple[AliasLeafComparison, ...]
    unavailable_leaves: tuple[AliasUnavailableLeaf, ...]
    divergence: AliasDivergence | None
    endpoint_match: AliasEndpointMatch


@dataclass(frozen=True)
class AliasEvent:
    """How one alias's divergence moved between the baseline and current catalog.

    `kind` is `new`, `changed`, `persisting`, `resolved`, or `unavailable`.
    `current` and `baseline` are the evaluations on each side, None where the
    alias was not evaluated there. `leaves` are the leaves the event is about:
    the current divergent leaves for `new`, `changed` and `persisting`, the
    current (now equal) comparisons of the previously divergent leaves for
    `resolved`, and the baseline divergent leaves for `unavailable`, whose
    `unavailable_reason` says why the current catalog cannot show them.
    """

    kind: str
    alias_model_id: str
    current: AliasEvaluation | None
    baseline: AliasEvaluation | None
    unavailable_reason: str | None
    leaves: tuple[AliasLeafComparison, ...]


class LadderMarkInput(NamedTuple):
    """A labelled reference price (such as a catalog alias or target price)."""

    label: str
    field_path: str
    raw_value: Any


@dataclass(frozen=True)
class LadderEntry:
    """One endpoint (`kind="endpoint"`, `label` its key) or mark at a position."""

    kind: str
    label: str
    raw_value: Any


@dataclass(frozen=True)
class LadderPosition:
    """All entries with one exact normalized value, placed on the ladder.

    `position` is in [0, 1], linear in log10 of the value across the domain.
    `exact_value` is the reduced fraction string, `normalized_value` its float
    projection and `display` the formatted price. Entries list endpoints in
    input order, then marks in input order.
    """

    position: float
    exact_value: str
    normalized_value: float
    display: str
    entries: tuple[LadderEntry, ...]


@dataclass(frozen=True)
class LadderUnplaced:
    """A value that cannot be placed, with why.

    `reason` is `zero`, `negative`, `missing`, `invalid`, or `incompatible`.
    `display` is the formatted price for `zero` and `negative`, else None.
    """

    kind: str
    label: str
    raw_value: Any
    reason: str
    display: str | None


@dataclass(frozen=True)
class Ladder:
    """The shared log-scale projection of one price leaf across endpoints.

    Consumers render `positions` as given and never recompute the scale. The
    domain spans the smallest and largest placed values, endpoint or mark.
    """

    leaf: str
    label: str
    unit_label: str
    comparison_group: str | None
    domain_min_exact: str
    domain_max_exact: str
    domain_min_display: str
    domain_max_display: str
    positions: tuple[LadderPosition, ...]
    unplaced: tuple[LadderUnplaced, ...]
