"""Format-neutral semantics for provider-declared conditional pricing policies.

Parsing, bounded weekly UTC coverage, effective schedule compilation, policy
equality, format-neutral movement, sibling absorption decisions, and central
accounting live here. Storage and human rendering remain later layers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Literal, TypeAlias, TypeVar

from .change_render import (
    ResolvedPriceValue,
    _finite_fraction_projection,
    resolve_price_rule,
    resolve_price_value,
)
from .models import FieldChange, canonical_json
from .provider_profiles import ProviderProfile, ResolvedPriceRule


InterpretationState: TypeAlias = Literal[
    "grouped-schedule", "ordered-rules", "raw-fallback"
]
PricingTransition: TypeAlias = Literal["added", "removed", "changed"]
FallbackReason: TypeAlias = Literal[
    "multiple_parent_changes",
    "malformed_parent_transition",
    "invalid_policy_type",
    "missing_policy_semantics",
    "missing_condition_set_semantics",
    "malformed_rule",
    "empty_rule",
    "selector_semantics_unavailable",
    "unresolved_price_dimension",
    "unknown_rule_key",
    "missing_price_assignment",
    "invalid_selector_value",
    "missing_endpoint_pair",
    "equal_endpoints_unsupported",
    "multiple_policy_errors",
]
GroupingInhibitionReason: TypeAlias = Literal[
    "comparison_requires_ordered_rules",
    "duplicate_semantic_condition",
    "incomplete_base_vector",
    "missing_event_snapshot",
    "non_time_condition",
    "overlapping_weekly_coverage",
]
ComparisonInhibitionReason: TypeAlias = Literal[
    "incomplete_base_vector",
    "missing_event_snapshot",
    "missing_price_comparison_group",
    "ordered_rules",
    "raw_fallback",
    "partition_mismatch",
    "incompatible_price_basis",
    "incomplete_comparison_vector",
]
PriceMovementDirection: TypeAlias = Literal[
    "higher", "lower", "unchanged", "coverage", "unknown"
]
BandMovementDirection: TypeAlias = Literal[
    "higher", "lower", "mixed", "unchanged", "coverage", "unknown"
]
ComparisonMode: TypeAlias = Literal[
    "grouped-vs-default", "same-partition", "exact-regions"
]
ModelPriceBucket: TypeAlias = Literal[
    "higher", "lower", "mixed", "coverage", "conditional", "none"
]
_PARENT_FIELD = "pricing.overrides"
_ROLE_WEEKDAYS = "utc_weekdays"
_ROLE_START = "utc_start_inclusive"
_ROLE_END = "utc_end_exclusive"
_ROLE_STRICT_THRESHOLD = "integer_strictly_greater"
_ALL_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_WEEKDAY_INDEX = MappingProxyType(
    {weekday: index for index, weekday in enumerate(_ALL_WEEKDAYS)}
)
# Exact reorder proof is pairwise.  Above this rule count, conservatively report
# changed semantics instead of risking an unbounded quadratic scan.
MAX_EXACT_REORDERED_RULE_COUNT = 256


@dataclass(frozen=True, order=True)
class WeeklySegment:
    """One immutable half-open segment on a request-instant UTC civil day."""

    weekday_index: int
    start_minute: int
    end_minute: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.weekday_index, int)
            or isinstance(self.weekday_index, bool)
            or not 0 <= self.weekday_index < 7
        ):
            raise ValueError("weekday_index must be an integer from 0 through 6")
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in (self.start_minute, self.end_minute)
        ):
            raise ValueError("weekly segment minutes must be integers")
        if not 0 <= self.start_minute < self.end_minute <= 1440:
            raise ValueError("weekly segments must satisfy 0 <= start < end <= 1440")

    def contains(self, minute: int) -> bool:
        return self.start_minute <= minute < self.end_minute


WeeklyCoverage: TypeAlias = tuple[WeeklySegment, ...]


def compile_weekly_segments(
    utc_weekdays: tuple[str, ...],
    start_minute: int,
    end_minute: int,
) -> WeeklyCoverage:
    """Compile selected request-instant UTC days into canonical same-day segments."""
    try:
        weekday_indices = tuple(_WEEKDAY_INDEX[weekday] for weekday in utc_weekdays)
    except (KeyError, TypeError):
        raise ValueError("utc_weekdays must contain registered weekday names") from None
    if len(set(weekday_indices)) != len(weekday_indices):
        raise ValueError("utc_weekdays must not contain duplicates")
    if not weekday_indices:
        raise ValueError("utc_weekdays must not be empty")
    if any(
        not isinstance(value, int) or isinstance(value, bool)
        for value in (start_minute, end_minute)
    ):
        raise ValueError("weekly interval endpoints must be integers")
    if not (0 <= start_minute < 1440 and 0 <= end_minute <= 1440):
        raise ValueError("weekly interval endpoints are outside the UTC civil day")
    if start_minute == end_minute:
        raise ValueError("equal weekly interval endpoints are unsupported")

    segments: list[WeeklySegment] = []
    for weekday_index in sorted(weekday_indices):
        if start_minute < end_minute:
            segments.append(WeeklySegment(weekday_index, start_minute, end_minute))
            continue
        if end_minute > 0:
            segments.append(WeeklySegment(weekday_index, 0, end_minute))
        segments.append(WeeklySegment(weekday_index, start_minute, 1440))
    return tuple(segments)


def weekly_coverage_contains(
    coverage: WeeklyCoverage,
    weekday_index: int,
    minute: int,
) -> bool:
    """Return whether a UTC civil-day instant belongs to ``coverage``."""
    if (
        not isinstance(weekday_index, int)
        or isinstance(weekday_index, bool)
        or not 0 <= weekday_index < 7
    ):
        return False
    if not isinstance(minute, int) or isinstance(minute, bool) or not 0 <= minute < 1440:
        return False
    return any(
        segment.weekday_index == weekday_index and segment.contains(minute)
        for segment in coverage
    )


def weekly_segments_overlap(
    left: WeeklyCoverage,
    right: WeeklyCoverage,
) -> bool:
    """Detect positive-measure overlap; boundary adjacency is not overlap."""
    return _canonical_weekly_segments_overlap(
        tuple(sorted(left)),
        tuple(sorted(right)),
    )


def _canonical_weekly_segments_overlap(
    left: WeeklyCoverage,
    right: WeeklyCoverage,
) -> bool:
    """Detect overlap between already-normalized, sorted weekly coverages."""
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        left_segment = left[left_index]
        right_segment = right[right_index]
        if left_segment.weekday_index < right_segment.weekday_index:
            left_index += 1
            continue
        if right_segment.weekday_index < left_segment.weekday_index:
            right_index += 1
            continue
        if max(left_segment.start_minute, right_segment.start_minute) < min(
            left_segment.end_minute,
            right_segment.end_minute,
        ):
            return True
        if left_segment.end_minute <= right_segment.end_minute:
            left_index += 1
        else:
            right_index += 1
    return False


def _normalize_weekly_segments(coverage: WeeklyCoverage) -> WeeklyCoverage:
    normalized: list[WeeklySegment] = []
    for segment in sorted(coverage):
        if not isinstance(segment, WeeklySegment):
            raise TypeError("weekly coverage must contain WeeklySegment values")
        if (
            normalized
            and normalized[-1].weekday_index == segment.weekday_index
            and segment.start_minute <= normalized[-1].end_minute
        ):
            previous = normalized[-1]
            normalized[-1] = WeeklySegment(
                previous.weekday_index,
                previous.start_minute,
                max(previous.end_minute, segment.end_minute),
            )
        else:
            normalized.append(segment)
    return tuple(normalized)


def weekly_complement(coverage: WeeklyCoverage) -> WeeklyCoverage:
    """Return the canonical complement inside the bounded seven-day domain."""
    normalized = _normalize_weekly_segments(coverage)
    complement: list[WeeklySegment] = []
    by_day: dict[int, list[WeeklySegment]] = {day: [] for day in range(7)}
    for segment in normalized:
        by_day[segment.weekday_index].append(segment)
    for weekday_index in range(7):
        cursor = 0
        for segment in by_day[weekday_index]:
            if cursor < segment.start_minute:
                complement.append(
                    WeeklySegment(weekday_index, cursor, segment.start_minute)
                )
            cursor = segment.end_minute
        if cursor < 1440:
            complement.append(WeeklySegment(weekday_index, cursor, 1440))
    return tuple(complement)


def partition_weekly_segments(*coverages: WeeklyCoverage) -> WeeklyCoverage:
    """Partition the whole week at all supplied endpoints without intersections."""
    endpoints: dict[int, set[int]] = {
        weekday_index: {0, 1440} for weekday_index in range(7)
    }
    for coverage in coverages:
        for segment in coverage:
            if not isinstance(segment, WeeklySegment):
                raise TypeError("weekly coverage must contain WeeklySegment values")
            endpoints[segment.weekday_index].update(
                (segment.start_minute, segment.end_minute)
            )
    partition: list[WeeklySegment] = []
    for weekday_index in range(7):
        day_endpoints = sorted(endpoints[weekday_index])
        partition.extend(
            WeeklySegment(weekday_index, start, end)
            for start, end in zip(day_endpoints, day_endpoints[1:])
        )
    return tuple(partition)


def _validated_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _validated_scrape_id(value: Any, label: str, *, optional: bool) -> int | None:
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        qualifier = "integer or None" if optional else "integer"
        raise ValueError(f"{label} must be a {qualifier}")
    return value


@dataclass(frozen=True)
class LiveComparisonIdentity:
    provider_id: str
    provider_model_id: str
    baseline_scrape_id: int | None
    attempt_scrape_id: int

    def __post_init__(self) -> None:
        _validated_identifier(self.provider_id, "identity provider_id")
        _validated_identifier(self.provider_model_id, "identity provider_model_id")
        _validated_scrape_id(
            self.baseline_scrape_id, "identity baseline_scrape_id", optional=True
        )
        _validated_scrape_id(
            self.attempt_scrape_id, "identity attempt_scrape_id", optional=False
        )


@dataclass(frozen=True)
class StoredComparisonIdentity:
    provider_id: str
    provider_model_id: str
    from_scrape_id: int | None
    to_scrape_id: int

    def __post_init__(self) -> None:
        _validated_identifier(self.provider_id, "identity provider_id")
        _validated_identifier(self.provider_model_id, "identity provider_model_id")
        _validated_scrape_id(self.from_scrape_id, "identity from_scrape_id", optional=True)
        _validated_scrape_id(self.to_scrape_id, "identity to_scrape_id", optional=False)


ComparisonIdentity: TypeAlias = LiveComparisonIdentity | StoredComparisonIdentity
_ReasonT = TypeVar("_ReasonT")


def _freeze_json(value: Any) -> Any:
    """Return a source-order-preserving immutable copy of JSON-compatible data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            frozen[key] = _freeze_json(child)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(child) for child in value)
    raise TypeError(f"value is not canonical JSON data: {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(child) for child in value]
    return value


def _canonical_json(value: Any) -> str:
    return canonical_json(_thaw_json(value))


@dataclass(frozen=True)
class PricingComparisonEvent:
    identity: ComparisonIdentity
    provider_id: str
    provider_model_id: str
    display_name: str
    detected_at: str
    source_timestamp: str | None
    target_timestamp: str | None
    field_changes: tuple[FieldChange, ...]
    old_model_metadata: Mapping[str, Any] | None
    new_model_metadata: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, (LiveComparisonIdentity, StoredComparisonIdentity)):
            raise TypeError("identity must be a live or stored comparison identity")
        _validated_identifier(self.provider_id, "provider_id")
        _validated_identifier(self.provider_model_id, "provider_model_id")
        if self.identity.provider_id != self.provider_id:
            raise ValueError("identity provider does not match event provider")
        if self.identity.provider_model_id != self.provider_model_id:
            raise ValueError("identity model does not match event model")
        _validated_identifier(self.display_name, "display_name")
        _validated_identifier(self.detected_at, "detected_at")
        for label, value in (
            ("source_timestamp", self.source_timestamp),
            ("target_timestamp", self.target_timestamp),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{label} must be a non-empty string or None")

        copied_changes: list[FieldChange] = []
        for change in tuple(self.field_changes):
            if not isinstance(change, FieldChange):
                raise TypeError("field_changes must contain FieldChange values")
            copied_changes.append(
                FieldChange(
                    change.field_name,
                    _freeze_json(change.old_value),
                    _freeze_json(change.new_value),
                )
            )
        object.__setattr__(self, "field_changes", tuple(copied_changes))
        for name in ("old_model_metadata", "new_model_metadata"):
            metadata = getattr(self, name)
            if metadata is not None and not isinstance(metadata, Mapping):
                raise TypeError(f"{name} must be a mapping or None")
            object.__setattr__(self, name, None if metadata is None else _freeze_json(metadata))


@dataclass(frozen=True)
class SourceChangeReference:
    field_name: str
    old_value_canonical_json: str
    new_value_canonical_json: str
    occurrence: int
    source_index: int

    @property
    def transition_key(self) -> tuple[str, str, str, int]:
        return (
            self.field_name,
            self.old_value_canonical_json,
            self.new_value_canonical_json,
            self.occurrence,
        )

    def with_source_index(self, source_index: int) -> SourceChangeReference:
        return replace(self, source_index=source_index)


@dataclass(frozen=True)
class OccurrenceReferencedChange:
    reference: SourceChangeReference
    old_value: Any
    new_value: Any


@dataclass(frozen=True)
class DirectPriceMovementFact:
    """One exact scalar price movement retained independently of rendering."""

    field_path: str
    old_value: ResolvedPriceValue | None
    new_value: ResolvedPriceValue | None
    direction: PriceMovementDirection
    delta: float | None
    percentage: float | None
    unit_label: str
    comparison_group: str | None
    source_change: SourceChangeReference | None = None


@dataclass(frozen=True)
class PriceDimensionComparison:
    """One same-dimension old/new comparison with exact provider values."""

    dimension: str
    old_value: ResolvedPriceValue | None
    new_value: ResolvedPriceValue | None
    direction: PriceMovementDirection
    delta: float | None
    percentage: float | None
    normalized_movement_ratio: Fraction | None
    unit_label: str | None
    comparison_group: str | None


@dataclass(frozen=True)
class PriceBandComparison:
    """Movement over one proven region/band without summing its dimensions."""

    coverage: WeeklyCoverage
    dimensions: tuple[PriceDimensionComparison, ...]
    direction: BandMovementDirection
    percentage: float | None
    provenance: ComparisonMode
    is_peak: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage", tuple(self.coverage))
        object.__setattr__(self, "dimensions", tuple(self.dimensions))


@dataclass(frozen=True)
class ConditionalPricingComparison:
    """Only the bounded movement facts an exact comparison edge can prove."""

    mode: ComparisonMode
    bands: tuple[PriceBandComparison, ...]
    aggregate_direction: BandMovementDirection | None
    inhibition_reasons: tuple[ComparisonInhibitionReason, ...]
    peak_band_index: int | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bands", tuple(self.bands))
        object.__setattr__(
            self, "inhibition_reasons", tuple(self.inhibition_reasons)
        )
        if self.peak_band_index is not None and not (
            0 <= self.peak_band_index < len(self.bands)
        ):
            raise ValueError("peak_band_index must identify a comparison band")


@dataclass(frozen=True)
class AbsorbedBasePriceChange:
    """A pure consume-once decision for one proven sibling base-price row."""

    dimension: str
    source_change: SourceChangeReference
    movement: DirectPriceMovementFact


@dataclass(frozen=True)
class ModelPricingAccounting:
    """Disjoint immutable units for one exact changed-model comparison edge."""

    direct_price_facts: tuple[DirectPriceMovementFact, ...]
    direct_price_field_count: int
    conditional_policy_count: int
    source_rule_count: int
    schedule_dimensions: tuple[str, ...]
    schedule_dimension_count: int
    effective_band_count: int
    model_bucket: ModelPriceBucket

    def __post_init__(self) -> None:
        object.__setattr__(self, "direct_price_facts", tuple(self.direct_price_facts))
        object.__setattr__(self, "schedule_dimensions", tuple(self.schedule_dimensions))
        if self.direct_price_field_count != len(self.direct_price_facts):
            raise ValueError("direct price field count must equal retained facts")
        if self.schedule_dimension_count != len(self.schedule_dimensions):
            raise ValueError("schedule dimension count must equal the dimension union")
        for count in (
            self.direct_price_field_count,
            self.conditional_policy_count,
            self.source_rule_count,
            self.schedule_dimension_count,
            self.effective_band_count,
        ):
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("pricing accounting counts must be nonnegative integers")
        if self.conditional_policy_count not in (0, 1):
            raise ValueError("one comparison edge can change at most one conditional policy")


@dataclass(frozen=True)
class ConditionalPricingCondition:
    field_name: str
    family: str
    semantic_role: str
    canonical_value: Hashable
    display_value: str
    occurrence: int
    source_rule_index: int

    def matches(self, candidate: Any) -> bool:
        """Evaluate only the provider-declared scalar predicate supported in Task 2."""
        if self.semantic_role != _ROLE_STRICT_THRESHOLD:
            raise TypeError("this condition has no Task 2 scalar predicate")
        if not isinstance(candidate, int) or isinstance(candidate, bool):
            return False
        return candidate > self.canonical_value


@dataclass(frozen=True)
class ConditionalPriceAssignment:
    dimension: str
    raw_value: Any
    source_key_index: int
    price_rule: ResolvedPriceRule


@dataclass(frozen=True)
class EffectivePriceValue:
    """One resolved price dimension retaining its exact provider value."""

    dimension: str
    raw_value: Any
    price_rule: ResolvedPriceRule

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, str) or not self.dimension.strip():
            raise ValueError("effective price dimension must be non-empty")
        if not isinstance(self.price_rule, ResolvedPriceRule):
            raise TypeError("effective price value requires a ResolvedPriceRule")
        object.__setattr__(self, "raw_value", _freeze_json(self.raw_value))

    @property
    def canonical_identity(self) -> tuple[str, str, ResolvedPriceRule]:
        return (self.dimension, _canonical_json(self.raw_value), self.price_rule)


@dataclass(frozen=True)
class EffectivePriceVector:
    """A complete, deterministic dimension vector for one event side."""

    entries: tuple[EffectivePriceValue, ...]

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        if any(not isinstance(entry, EffectivePriceValue) for entry in entries):
            raise TypeError("effective price vectors require EffectivePriceValue entries")
        if tuple(sorted(entry.dimension for entry in entries)) != tuple(
            entry.dimension for entry in entries
        ):
            raise ValueError("effective price vector dimensions must be sorted")
        if len({entry.dimension for entry in entries}) != len(entries):
            raise ValueError("effective price vector dimensions must be unique")
        object.__setattr__(self, "entries", entries)

    @property
    def canonical_identity(
        self,
    ) -> tuple[tuple[str, str, ResolvedPriceRule], ...]:
        return tuple(entry.canonical_identity for entry in self.entries)

    def value_for(self, dimension: str) -> EffectivePriceValue | None:
        return next(
            (entry for entry in self.entries if entry.dimension == dimension),
            None,
        )


CanonicalConditionIdentity: TypeAlias = tuple[tuple[str, Hashable], ...]


@dataclass(frozen=True)
class RuleOccurrenceIdentity:
    canonical_condition_identity: CanonicalConditionIdentity
    occurrence: int


@dataclass(frozen=True)
class ConditionalPricingRule:
    source_index: int
    source_value: Mapping[str, Any]
    conditions: tuple[ConditionalPricingCondition, ...]
    condition_combination: Literal["all_conditions"]
    explicit_prices: tuple[ConditionalPriceAssignment, ...]
    utc_weekdays: tuple[str, ...]
    start_minute: int
    end_minute: int
    canonical_condition_identity: CanonicalConditionIdentity
    condition_occurrence: int

    @property
    def occurrence_identity(self) -> RuleOccurrenceIdentity:
        return RuleOccurrenceIdentity(
            self.canonical_condition_identity,
            self.condition_occurrence,
        )


@dataclass(frozen=True)
class ConditionalPricingPolicy:
    source_value: tuple[Mapping[str, Any], ...]
    rules: tuple[ConditionalPricingRule, ...]


@dataclass(frozen=True)
class CompiledPricingRule:
    """A source-ordered parsed rule plus bounded coverage and proven vector."""

    source_rule: ConditionalPricingRule
    coverage: WeeklyCoverage
    effective_prices: EffectivePriceVector | None


@dataclass(frozen=True)
class GroupedScheduleRegion:
    """One source-linked weekly segment with a proven complete vector."""

    segment: WeeklySegment
    source_rule_index: int
    explicit_prices: tuple[ConditionalPriceAssignment, ...]
    effective_prices: EffectivePriceVector


@dataclass(frozen=True)
class EffectivePriceBand:
    """Canonical union of all coverage carrying one complete vector."""

    coverage: WeeklyCoverage
    effective_prices: EffectivePriceVector
    source_rule_indices: tuple[int, ...]
    includes_default: bool


@dataclass(frozen=True)
class WeeklyEffectiveRegion:
    """One canonical effective-function cell for later side comparison."""

    segment: WeeklySegment
    effective_prices: EffectivePriceVector


PriceAssignmentIdentity: TypeAlias = tuple[
    tuple[str, str, ResolvedPriceRule], ...
]
PriceVectorIdentity: TypeAlias = tuple[tuple[str, str, ResolvedPriceRule], ...]


@dataclass(frozen=True)
class WeeklyGroupedSemanticRegion:
    """One canonical cell of effective prices and explicit policy intent."""

    segment: WeeklySegment
    effective_price_identity: PriceVectorIdentity
    explicit_assignment_identity: PriceAssignmentIdentity


@dataclass(frozen=True)
class CompiledConditionalPricingPolicy:
    """One event-side policy after format-neutral compilation."""

    source_policy: ConditionalPricingPolicy
    policy_present: bool
    base_prices: EffectivePriceVector | None
    ordered_rules: tuple[CompiledPricingRule, ...]
    grouped_regions: tuple[GroupedScheduleRegion, ...]
    default_coverage: WeeklyCoverage
    effective_bands: tuple[EffectivePriceBand, ...]
    effective_partition: tuple[WeeklyEffectiveRegion, ...]
    grouping_inhibition_reasons: tuple[GroupingInhibitionReason, ...]
    comparison_inhibition_reasons: tuple[ComparisonInhibitionReason, ...]


@dataclass(frozen=True)
class ConditionalRuleMatch:
    identity: RuleOccurrenceIdentity
    old_source_index: int
    new_source_index: int


@dataclass(frozen=True)
class ConditionalPricingStructuralComparison:
    matches: tuple[ConditionalRuleMatch, ...]
    old_only: tuple[RuleOccurrenceIdentity, ...]
    new_only: tuple[RuleOccurrenceIdentity, ...]
    source_order_changed: bool
    canonical_evidence_changed: bool


@dataclass(frozen=True)
class ConditionalPricingInterpretation:
    identity: ComparisonIdentity
    state: InterpretationState
    semantic_change: bool
    fallback_reason: FallbackReason | None
    grouping_inhibition_reasons: tuple[GroupingInhibitionReason, ...]
    comparison_inhibition_reasons: tuple[ComparisonInhibitionReason, ...]
    transition: PricingTransition
    old_policy: ConditionalPricingPolicy | None
    new_policy: ConditionalPricingPolicy | None
    old_compiled_policy: CompiledConditionalPricingPolicy | None
    new_compiled_policy: CompiledConditionalPricingPolicy | None
    absorbed_base_price_changes: tuple[SourceChangeReference, ...]
    comparison: ConditionalPricingComparison | None
    accounting: ModelPricingAccounting | None
    source_changes: tuple[OccurrenceReferencedChange, ...]
    structural_comparison: ConditionalPricingStructuralComparison | None
    canonical_evidence_changed: bool


class _PolicyDataError(ValueError):
    def __init__(self, reason: FallbackReason) -> None:
        super().__init__(reason)
        self.reason = reason


def _source_references(event: PricingComparisonEvent) -> tuple[OccurrenceReferencedChange, ...]:
    occurrences: Counter[tuple[str, str, str]] = Counter()
    references: list[OccurrenceReferencedChange] = []
    for source_index, change in enumerate(event.field_changes):
        old_json = _canonical_json(change.old_value)
        new_json = _canonical_json(change.new_value)
        key = (change.field_name, old_json, new_json)
        occurrence = occurrences[key]
        occurrences[key] += 1
        references.append(
            OccurrenceReferencedChange(
                SourceChangeReference(
                    field_name=change.field_name,
                    old_value_canonical_json=old_json,
                    new_value_canonical_json=new_json,
                    occurrence=occurrence,
                    source_index=source_index,
                ),
                change.old_value,
                change.new_value,
            )
        )
    return tuple(references)


def _transition(old_value: Any, new_value: Any) -> PricingTransition:
    if old_value is None and new_value is not None:
        return "added"
    if old_value is not None and new_value is None:
        return "removed"
    return "changed"


def _valid_parent_transition(
    old_value: Any,
    new_value: Any,
) -> PricingTransition | None:
    old_is_policy = isinstance(old_value, tuple)
    new_is_policy = isinstance(new_value, tuple)
    if old_value is None and new_is_policy:
        return "added"
    if old_is_policy and new_value is None:
        return "removed"
    if old_is_policy and new_is_policy:
        return "changed"
    return None


def _aggregate_parent_transition(
    parent_changes: tuple[OccurrenceReferencedChange, ...],
) -> PricingTransition:
    transitions = tuple(
        _valid_parent_transition(parent.old_value, parent.new_value)
        for parent in parent_changes
    )
    if transitions and transitions[0] is not None and all(
        transition == transitions[0] for transition in transitions
    ):
        return transitions[0]
    return "changed"


def _raw_fallback(
    event: PricingComparisonEvent,
    source_changes: tuple[OccurrenceReferencedChange, ...],
    reason: FallbackReason,
    *,
    transition: PricingTransition,
    old_policy: ConditionalPricingPolicy | None = None,
    new_policy: ConditionalPricingPolicy | None = None,
) -> ConditionalPricingInterpretation:
    canonical_evidence_changed = any(
        source.reference.old_value_canonical_json
        != source.reference.new_value_canonical_json
        for source in source_changes
    )
    return ConditionalPricingInterpretation(
        identity=event.identity,
        state="raw-fallback",
        semantic_change=canonical_evidence_changed,
        fallback_reason=reason,
        grouping_inhibition_reasons=(),
        comparison_inhibition_reasons=("raw_fallback",),
        transition=transition,
        old_policy=old_policy,
        new_policy=new_policy,
        old_compiled_policy=None,
        new_compiled_policy=None,
        absorbed_base_price_changes=(),
        comparison=None,
        accounting=None,
        source_changes=source_changes,
        structural_comparison=None,
        canonical_evidence_changed=canonical_evidence_changed,
    )


def _unknown_key_reason(
    field_name: str,
    value: Any,
    profile: ProviderProfile,
) -> FallbackReason:
    path = f"pricing.overrides.{field_name}"
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    numeric_text = isinstance(value, str) and bool(value.strip())
    if profile.is_price_amount_field(path) and (numeric or numeric_text):
        return "unresolved_price_dimension"
    return "unknown_rule_key"


def resolve_direct_price_movement(
    field_path: str,
    old_raw_value: Any,
    new_raw_value: Any,
    profile: ProviderProfile,
    *,
    source_change: SourceChangeReference | None = None,
) -> DirectPriceMovementFact | None:
    """Resolve one matched scalar movement without manufacturing invalid facts."""
    old_value = resolve_price_value(field_path, old_raw_value, profile)
    new_value = resolve_price_value(field_path, new_raw_value, profile)
    if old_raw_value is not None and old_value is None:
        return None
    if new_raw_value is not None and new_value is None:
        return None
    present = old_value or new_value
    if present is None:
        return None
    if old_value is None or new_value is None:
        return DirectPriceMovementFact(
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
            direction="coverage",
            delta=None,
            percentage=None,
            unit_label=present.price_rule.unit_label,
            comparison_group=present.price_rule.comparison_group,
            source_change=source_change,
        )

    if (
        old_value.price_rule.unit_label != new_value.price_rule.unit_label
        or old_value.price_rule.comparison_group is None
        or old_value.price_rule.comparison_group
        != new_value.price_rule.comparison_group
    ):
        return DirectPriceMovementFact(
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
            direction="unknown",
            delta=None,
            percentage=None,
            unit_label=old_value.price_rule.unit_label,
            comparison_group=None,
            source_change=source_change,
        )

    old_exact = old_value.normalized_exact_value
    new_exact = new_value.normalized_exact_value
    exact_delta = new_exact - old_exact
    direction: PriceMovementDirection
    if exact_delta > 0:
        direction = "higher"
    elif exact_delta < 0:
        direction = "lower"
    else:
        direction = "unchanged"
    ratio = None if old_exact == 0 else exact_delta / abs(old_exact)
    return DirectPriceMovementFact(
        field_path=field_path,
        old_value=old_value,
        new_value=new_value,
        direction=direction,
        delta=_finite_fraction_projection(exact_delta),
        percentage=(
            None
            if ratio is None
            else _finite_fraction_projection(ratio * 100)
        ),
        unit_label=old_value.price_rule.unit_label,
        comparison_group=old_value.price_rule.comparison_group,
        source_change=source_change,
    )


def _parse_policy(raw_policy: Any, profile: ProviderProfile) -> ConditionalPricingPolicy:
    if not isinstance(raw_policy, tuple):
        raise _PolicyDataError("invalid_policy_type")
    policy_semantics = profile.pricing_override_policy_semantics
    if policy_semantics is None:
        raise _PolicyDataError("missing_policy_semantics")
    condition_set = profile.pricing_override_condition_set_semantics
    if condition_set is None:
        raise _PolicyDataError("missing_condition_set_semantics")

    selector_occurrences: Counter[tuple[str, Hashable]] = Counter()
    condition_occurrences: Counter[CanonicalConditionIdentity] = Counter()
    parsed_rules: list[ConditionalPricingRule] = []

    for source_index, raw_rule in enumerate(raw_policy):
        if not isinstance(raw_rule, Mapping):
            raise _PolicyDataError("malformed_rule")
        if not raw_rule:
            raise _PolicyDataError("empty_rule")

        explicit_prices: list[ConditionalPriceAssignment] = []
        for source_key_index, (field_name, raw_value) in enumerate(raw_rule.items()):
            descriptor = profile.pricing_override_condition_descriptor(field_name)
            if descriptor is not None:
                continue
            if field_name in profile.pricing_override_selector_names:
                raise _PolicyDataError("selector_semantics_unavailable")
            if field_name in profile.pricing_override_base_paths:
                price_path = profile.pricing_override_base_paths[field_name]
                resolved_price = resolve_price_value(
                    price_path,
                    raw_value,
                    profile,
                )
                if (
                    resolved_price is None
                    or not resolved_price.price_rule.unit_label.strip()
                ):
                    raise _PolicyDataError("unresolved_price_dimension")
                explicit_prices.append(
                    ConditionalPriceAssignment(
                        field_name,
                        raw_value,
                        source_key_index,
                        resolved_price.price_rule,
                    )
                )
                continue
            raise _PolicyDataError(_unknown_key_reason(field_name, raw_value, profile))

        if not explicit_prices:
            raise _PolicyDataError("missing_price_assignment")

        conditions: list[ConditionalPricingCondition] = []
        role_values: dict[str, Hashable] = {}
        for descriptor in profile.pricing_override_condition_descriptors.values():
            if descriptor.field_name not in raw_rule:
                continue
            raw_value = raw_rule[descriptor.field_name]
            try:
                canonical_value = descriptor.canonicalize_raw(_thaw_json(raw_value))
            except ValueError:
                raise _PolicyDataError("invalid_selector_value") from None
            try:
                hash(canonical_value)
            except TypeError:
                raise TypeError(
                    "conditional pricing canonical selector identity must be hashable"
                ) from None
            display_value = descriptor.format_value(canonical_value)
            if not isinstance(display_value, str):
                raise TypeError("conditional pricing formatted selector must be a string")
            selector_key = (descriptor.semantic_role, canonical_value)
            selector_occurrence = selector_occurrences[selector_key]
            selector_occurrences[selector_key] += 1
            conditions.append(
                ConditionalPricingCondition(
                    field_name=descriptor.field_name,
                    family=descriptor.family,
                    semantic_role=descriptor.semantic_role,
                    canonical_value=canonical_value,
                    display_value=display_value,
                    occurrence=selector_occurrence,
                    source_rule_index=source_index,
                )
            )
            role_values[descriptor.semantic_role] = canonical_value

        threshold_value = role_values.get(_ROLE_STRICT_THRESHOLD)
        if threshold_value is not None and (
            not isinstance(threshold_value, int) or isinstance(threshold_value, bool)
        ):
            raise _PolicyDataError("invalid_selector_value")

        has_start = _ROLE_START in role_values
        has_end = _ROLE_END in role_values
        if has_start != has_end:
            raise _PolicyDataError("missing_endpoint_pair")

        weekdays_value = role_values.get(_ROLE_WEEKDAYS, _ALL_WEEKDAYS)
        if (
            not isinstance(weekdays_value, tuple)
            or not weekdays_value
            or any(not isinstance(day, str) for day in weekdays_value)
            or len(set(weekdays_value)) != len(weekdays_value)
        ):
            raise _PolicyDataError("invalid_selector_value")
        weekdays = tuple(weekdays_value)
        if has_start and any(
            not isinstance(role_values[role], int)
            or isinstance(role_values[role], bool)
            or not 0 <= role_values[role] < 1440
            for role in (_ROLE_START, _ROLE_END)
        ):
            raise _PolicyDataError("invalid_selector_value")
        start_minute = role_values[_ROLE_START] if has_start else 0
        end_minute = role_values[_ROLE_END] if has_end else 1440
        if has_start and start_minute == end_minute:
            raise _PolicyDataError("equal_endpoints_unsupported")

        identity_parts: list[tuple[str, Hashable]] = [
            (_ROLE_WEEKDAYS, weekdays),
            ("utc_interval", (start_minute, end_minute)),
        ]
        identity_parts.extend(
            (condition.semantic_role, condition.canonical_value)
            for condition in conditions
            if condition.semantic_role not in {_ROLE_WEEKDAYS, _ROLE_START, _ROLE_END}
        )
        canonical_identity = tuple(identity_parts)
        condition_occurrence = condition_occurrences[canonical_identity]
        condition_occurrences[canonical_identity] += 1
        parsed_rules.append(
            ConditionalPricingRule(
                source_index=source_index,
                source_value=raw_rule,
                conditions=tuple(conditions),
                condition_combination=policy_semantics.condition_combination,
                explicit_prices=tuple(explicit_prices),
                utc_weekdays=weekdays,
                start_minute=start_minute,
                end_minute=end_minute,
                canonical_condition_identity=canonical_identity,
                condition_occurrence=condition_occurrence,
            )
        )

    return ConditionalPricingPolicy(tuple(raw_policy), tuple(parsed_rules))


def _structural_compare(
    old_policy: ConditionalPricingPolicy | None,
    new_policy: ConditionalPricingPolicy | None,
) -> ConditionalPricingStructuralComparison | None:
    if old_policy is None or new_policy is None:
        return None
    old_by_identity = {rule.occurrence_identity: rule for rule in old_policy.rules}
    new_by_identity = {rule.occurrence_identity: rule for rule in new_policy.rules}
    matches = tuple(
        ConditionalRuleMatch(identity, rule.source_index, new_by_identity[identity].source_index)
        for identity, rule in old_by_identity.items()
        if identity in new_by_identity
    )
    old_only = tuple(identity for identity in old_by_identity if identity not in new_by_identity)
    new_only = tuple(identity for identity in new_by_identity if identity not in old_by_identity)
    matched_identities = old_by_identity.keys() & new_by_identity.keys()
    old_matched_order = tuple(
        rule.occurrence_identity
        for rule in old_policy.rules
        if rule.occurrence_identity in matched_identities
    )
    new_matched_order = tuple(
        rule.occurrence_identity
        for rule in new_policy.rules
        if rule.occurrence_identity in matched_identities
    )
    return ConditionalPricingStructuralComparison(
        matches=matches,
        old_only=old_only,
        new_only=new_only,
        source_order_changed=old_matched_order != new_matched_order,
        canonical_evidence_changed=(
            _canonical_json(old_policy.source_value) != _canonical_json(new_policy.source_value)
        ),
    )


_MISSING = object()


def _exact_metadata_entry(
    metadata: Mapping[str, Any], path: str
) -> tuple[bool, Any]:
    value: Any = metadata
    for component in path.split("."):
        if not isinstance(value, Mapping) or component not in value:
            return False, _MISSING
        value = value[component]
    return True, value


def _exact_metadata_value(metadata: Mapping[str, Any], path: str) -> Any:
    present, value = _exact_metadata_entry(metadata, path)
    return value if present else _MISSING


def _complete_base_vector(
    policy: ConditionalPricingPolicy,
    metadata: Mapping[str, Any],
    profile: ProviderProfile,
    dimensions: tuple[str, ...],
) -> EffectivePriceVector | None:
    entries: list[EffectivePriceValue] = []
    for dimension in dimensions:
        base_path = profile.pricing_override_base_paths.get(dimension)
        if base_path is None:
            return None
        raw_value = _exact_metadata_value(metadata, base_path)
        if raw_value is _MISSING:
            return None
        resolved_price = resolve_price_value(base_path, raw_value, profile)
        if (
            resolved_price is None
            or not resolved_price.price_rule.unit_label.strip()
        ):
            return None
        price_rule = resolved_price.price_rule
        assignments = (
            assignment
            for rule in policy.rules
            for assignment in rule.explicit_prices
            if assignment.dimension == dimension
        )
        if any(assignment.price_rule != price_rule for assignment in assignments):
            return None
        entries.append(EffectivePriceValue(dimension, raw_value, price_rule))
    return EffectivePriceVector(tuple(entries))


def _apply_explicit_prices(
    base_prices: EffectivePriceVector,
    assignments: tuple[ConditionalPriceAssignment, ...],
) -> EffectivePriceVector:
    values = {entry.dimension: entry for entry in base_prices.entries}
    for assignment in assignments:
        if assignment.dimension not in values:
            raise ValueError("explicit price dimension is absent from complete base vector")
        values[assignment.dimension] = EffectivePriceValue(
            assignment.dimension,
            assignment.raw_value,
            assignment.price_rule,
        )
    return EffectivePriceVector(tuple(values[dimension] for dimension in sorted(values)))


def _has_non_time_condition(rule: ConditionalPricingRule) -> bool:
    return any(condition.family != "time" for condition in rule.conditions)


def _rule_coverages_overlap(rule_coverages: tuple[WeeklyCoverage, ...]) -> bool:
    """Detect cross-rule overlap with a bounded interval sweep."""
    tagged_segments = sorted(
        (segment, rule_index)
        for rule_index, coverage in enumerate(rule_coverages)
        for segment in coverage
    )
    active_weekday = -1
    active_end = -1
    for segment, _rule_index in tagged_segments:
        if segment.weekday_index != active_weekday:
            active_weekday = segment.weekday_index
            active_end = segment.end_minute
            continue
        if segment.start_minute < active_end:
            return True
        active_end = max(active_end, segment.end_minute)
    return False


def _append_once(values: list[_ReasonT], value: _ReasonT) -> None:
    if value not in values:
        values.append(value)


def _build_effective_bands(
    regions: tuple[GroupedScheduleRegion, ...],
    default_coverage: WeeklyCoverage,
    base_prices: EffectivePriceVector,
) -> tuple[EffectivePriceBand, ...]:
    buckets: dict[
        tuple[tuple[str, str, ResolvedPriceRule], ...],
        tuple[EffectivePriceVector, list[WeeklySegment], set[int], bool],
    ] = {}
    for region in regions:
        identity = region.effective_prices.canonical_identity
        if identity not in buckets:
            buckets[identity] = (region.effective_prices, [], set(), False)
        vector, coverage, source_indices, includes_default = buckets[identity]
        coverage.append(region.segment)
        source_indices.add(region.source_rule_index)
        buckets[identity] = (vector, coverage, source_indices, includes_default)

    if default_coverage:
        identity = base_prices.canonical_identity
        if identity not in buckets:
            buckets[identity] = (base_prices, [], set(), False)
        vector, coverage, source_indices, _includes_default = buckets[identity]
        coverage.extend(default_coverage)
        buckets[identity] = (vector, coverage, source_indices, True)

    bands = [
        EffectivePriceBand(
            coverage=_normalize_weekly_segments(tuple(coverage)),
            effective_prices=vector,
            source_rule_indices=tuple(sorted(source_indices)),
            includes_default=includes_default,
        )
        for vector, coverage, source_indices, includes_default in buckets.values()
    ]
    bands.sort(
        key=lambda band: (
            band.coverage[0] if band.coverage else WeeklySegment(6, 1439, 1440),
            tuple(
                (
                    entry.dimension,
                    _canonical_json(entry.raw_value),
                    entry.price_rule.unit_label,
                    entry.price_rule.multiplier,
                    entry.price_rule.divisor,
                    entry.price_rule.comparison_group or "",
                    entry.price_rule.normalized_target or "",
                    entry.price_rule.match_source,
                )
                for entry in band.effective_prices.entries
            ),
        )
    )
    return tuple(bands)


def _build_effective_partition(
    regions: tuple[GroupedScheduleRegion, ...],
    default_coverage: WeeklyCoverage,
    base_prices: EffectivePriceVector,
) -> tuple[WeeklyEffectiveRegion, ...]:
    cells = [
        WeeklyEffectiveRegion(region.segment, region.effective_prices)
        for region in regions
    ]
    cells.extend(
        WeeklyEffectiveRegion(segment, base_prices) for segment in default_coverage
    )
    cells.sort(key=lambda cell: cell.segment)
    partition: list[WeeklyEffectiveRegion] = []
    for cell in cells:
        if (
            partition
            and partition[-1].effective_prices.canonical_identity
            == cell.effective_prices.canonical_identity
            and partition[-1].segment.weekday_index == cell.segment.weekday_index
            and partition[-1].segment.end_minute == cell.segment.start_minute
        ):
            previous = partition[-1]
            partition[-1] = WeeklyEffectiveRegion(
                WeeklySegment(
                    previous.segment.weekday_index,
                    previous.segment.start_minute,
                    cell.segment.end_minute,
                ),
                cell.effective_prices,
            )
        else:
            partition.append(cell)
    return tuple(partition)


def _compile_policy(
    policy: ConditionalPricingPolicy,
    metadata: Mapping[str, Any] | None,
    profile: ProviderProfile,
    dimensions: tuple[str, ...],
    *,
    policy_present: bool,
    snapshots_complete: bool,
) -> CompiledConditionalPricingPolicy:
    rule_coverages = tuple(
        compile_weekly_segments(
            rule.utc_weekdays,
            rule.start_minute,
            rule.end_minute,
        )
        for rule in policy.rules
    )
    grouping_reasons: list[GroupingInhibitionReason] = []
    if any(_has_non_time_condition(rule) for rule in policy.rules):
        _append_once(grouping_reasons, "non_time_condition")
    condition_counts = Counter(
        rule.canonical_condition_identity for rule in policy.rules
    )
    if any(count > 1 for count in condition_counts.values()):
        _append_once(grouping_reasons, "duplicate_semantic_condition")
    if _rule_coverages_overlap(rule_coverages):
        _append_once(grouping_reasons, "overlapping_weekly_coverage")

    base_prices: EffectivePriceVector | None = None
    if not snapshots_complete or metadata is None:
        _append_once(grouping_reasons, "missing_event_snapshot")
    else:
        base_prices = _complete_base_vector(policy, metadata, profile, dimensions)
        if base_prices is None:
            _append_once(grouping_reasons, "incomplete_base_vector")

    groupable = not grouping_reasons
    ordered_rules = tuple(
        CompiledPricingRule(
            source_rule=rule,
            coverage=coverage,
            effective_prices=(
                _apply_explicit_prices(base_prices, rule.explicit_prices)
                if groupable and base_prices is not None
                else None
            ),
        )
        for rule, coverage in zip(policy.rules, rule_coverages, strict=True)
    )

    grouped_regions: tuple[GroupedScheduleRegion, ...] = ()
    default_coverage: WeeklyCoverage = ()
    effective_bands: tuple[EffectivePriceBand, ...] = ()
    effective_partition: tuple[WeeklyEffectiveRegion, ...] = ()
    if groupable and base_prices is not None:
        grouped_regions = tuple(
            sorted(
                (
                    GroupedScheduleRegion(
                        segment=segment,
                        source_rule_index=compiled.source_rule.source_index,
                        explicit_prices=compiled.source_rule.explicit_prices,
                        effective_prices=compiled.effective_prices,
                    )
                    for compiled in ordered_rules
                    for segment in compiled.coverage
                    if compiled.effective_prices is not None
                ),
                key=lambda region: (region.segment, region.source_rule_index),
            )
        )
        default_coverage = weekly_complement(
            tuple(region.segment for region in grouped_regions)
        )
        effective_bands = _build_effective_bands(
            grouped_regions,
            default_coverage,
            base_prices,
        )
        effective_partition = _build_effective_partition(
            grouped_regions,
            default_coverage,
            base_prices,
        )

    comparison_reasons: list[ComparisonInhibitionReason] = []
    if any(
        assignment.price_rule.comparison_group is None
        for rule in policy.rules
        for assignment in rule.explicit_prices
    ):
        _append_once(comparison_reasons, "missing_price_comparison_group")
    if "missing_event_snapshot" in grouping_reasons:
        _append_once(comparison_reasons, "missing_event_snapshot")
    if "incomplete_base_vector" in grouping_reasons:
        _append_once(comparison_reasons, "incomplete_base_vector")
    if not groupable:
        _append_once(comparison_reasons, "ordered_rules")
    return CompiledConditionalPricingPolicy(
        source_policy=policy,
        policy_present=policy_present,
        base_prices=base_prices,
        ordered_rules=ordered_rules,
        grouped_regions=grouped_regions,
        default_coverage=default_coverage,
        effective_bands=effective_bands,
        effective_partition=effective_partition,
        grouping_inhibition_reasons=tuple(grouping_reasons),
        comparison_inhibition_reasons=tuple(comparison_reasons),
    )


def _comparison_partition(
    compiled: CompiledConditionalPricingPolicy,
) -> WeeklyCoverage:
    coverages = tuple(rule.coverage for rule in compiled.ordered_rules)
    return partition_weekly_segments(*coverages, compiled.default_coverage)


def _vectors_covering_segments(
    compiled: CompiledConditionalPricingPolicy,
    segments: WeeklyCoverage,
) -> tuple[EffectivePriceVector | None, ...]:
    """Align sorted partition cells with sorted target segments in one sweep."""
    regions = iter(compiled.effective_partition)
    region = next(regions, None)
    vectors: list[EffectivePriceVector | None] = []
    for segment in segments:
        while region is not None and (
            region.segment.weekday_index < segment.weekday_index
            or (
                region.segment.weekday_index == segment.weekday_index
                and region.segment.end_minute <= segment.start_minute
            )
        ):
            region = next(regions, None)
        if (
            region is not None
            and region.segment.weekday_index == segment.weekday_index
            and region.segment.start_minute <= segment.start_minute
            and segment.end_minute <= region.segment.end_minute
        ):
            vectors.append(region.effective_prices)
        else:
            vectors.append(None)
    return tuple(vectors)


def _resolved_effective_value(
    value: EffectivePriceValue | None,
    profile: ProviderProfile,
) -> ResolvedPriceValue | None:
    if value is None:
        return None
    field_path = profile.pricing_override_base_paths.get(value.dimension)
    if field_path is None:
        return None
    resolved = resolve_price_value(field_path, value.raw_value, profile)
    if resolved is None or resolved.price_rule != value.price_rule:
        return None
    return resolved


def _normalized_movement_ratio(
    old_value: ResolvedPriceValue,
    new_value: ResolvedPriceValue,
) -> Fraction | None:
    old_exact = old_value.normalized_exact_value
    if old_exact == 0:
        return None
    return (new_value.normalized_exact_value - old_exact) / abs(old_exact)


def _compare_dimension(
    dimension: str,
    old_entry: EffectivePriceValue | None,
    new_entry: EffectivePriceValue | None,
    profile: ProviderProfile,
) -> PriceDimensionComparison:
    old_value = _resolved_effective_value(old_entry, profile)
    new_value = _resolved_effective_value(new_entry, profile)
    if old_entry is not None and old_value is None:
        return PriceDimensionComparison(
            dimension,
            None,
            new_value,
            "unknown",
            None,
            None,
            None,
            None,
            None,
        )
    if new_entry is not None and new_value is None:
        return PriceDimensionComparison(
            dimension,
            old_value,
            None,
            "unknown",
            None,
            None,
            None,
            None,
            None,
        )
    present = old_value or new_value
    if present is None:
        return PriceDimensionComparison(
            dimension,
            None,
            None,
            "unknown",
            None,
            None,
            None,
            None,
            None,
        )
    if old_value is None or new_value is None:
        return PriceDimensionComparison(
            dimension=dimension,
            old_value=old_value,
            new_value=new_value,
            direction="coverage",
            delta=None,
            percentage=None,
            normalized_movement_ratio=None,
            unit_label=present.price_rule.unit_label,
            comparison_group=present.price_rule.comparison_group,
        )
    if (
        old_value.price_rule.unit_label != new_value.price_rule.unit_label
        or old_value.price_rule.comparison_group is None
        or old_value.price_rule.comparison_group
        != new_value.price_rule.comparison_group
    ):
        return PriceDimensionComparison(
            dimension=dimension,
            old_value=old_value,
            new_value=new_value,
            direction="unknown",
            delta=None,
            percentage=None,
            normalized_movement_ratio=None,
            unit_label=None,
            comparison_group=None,
        )
    old_exact = old_value.normalized_exact_value
    new_exact = new_value.normalized_exact_value
    exact_delta = new_exact - old_exact
    direction: PriceMovementDirection
    if exact_delta > 0:
        direction = "higher"
    elif exact_delta < 0:
        direction = "lower"
    else:
        direction = "unchanged"
    ratio = _normalized_movement_ratio(old_value, new_value)
    return PriceDimensionComparison(
        dimension=dimension,
        old_value=old_value,
        new_value=new_value,
        direction=direction,
        delta=_finite_fraction_projection(exact_delta),
        percentage=(
            None
            if ratio is None
            else _finite_fraction_projection(ratio * 100)
        ),
        normalized_movement_ratio=ratio,
        unit_label=old_value.price_rule.unit_label,
        comparison_group=old_value.price_rule.comparison_group,
    )


def _movement_direction(
    directions: tuple[PriceMovementDirection | BandMovementDirection, ...],
) -> BandMovementDirection:
    if not directions or "unknown" in directions:
        return "unknown"
    has_coverage = "coverage" in directions
    monetary = {direction for direction in directions if direction != "coverage"}
    if has_coverage:
        return "coverage" if monetary <= {"unchanged"} else "unknown"
    has_higher = "higher" in monetary
    has_lower = "lower" in monetary
    if has_higher and has_lower:
        return "mixed"
    if has_higher and monetary <= {"higher", "unchanged"}:
        return "higher"
    if has_lower and monetary <= {"lower", "unchanged"}:
        return "lower"
    return "unchanged"


def _common_percentage(
    dimensions: tuple[PriceDimensionComparison, ...],
) -> float | None:
    comparable = tuple(
        fact
        for fact in dimensions
        if fact.direction in {"higher", "lower", "unchanged"}
    )
    if not comparable or len(comparable) != len(dimensions):
        return None
    if any(
        fact.unit_label is None or fact.comparison_group is None
        for fact in comparable
    ):
        return None
    bases = {(fact.unit_label, fact.comparison_group) for fact in comparable}
    if len(bases) != 1:
        return None
    ratios = tuple(fact.normalized_movement_ratio for fact in comparable)
    if any(value is None for value in ratios):
        return None
    first_ratio = ratios[0]
    if all(value == first_ratio for value in ratios[1:]):
        return comparable[0].percentage
    return None


def _has_single_comparison_basis(
    dimensions: tuple[PriceDimensionComparison, ...],
) -> bool:
    if not dimensions or any(
        fact.unit_label is None or fact.comparison_group is None
        for fact in dimensions
    ):
        return False
    return len(
        {(fact.unit_label, fact.comparison_group) for fact in dimensions}
    ) == 1


def _compare_vectors(
    old_vector: EffectivePriceVector | None,
    new_vector: EffectivePriceVector | None,
    profile: ProviderProfile,
) -> tuple[PriceDimensionComparison, ...]:
    old_entries = (
        {}
        if old_vector is None
        else {entry.dimension: entry for entry in old_vector.entries}
    )
    new_entries = (
        {}
        if new_vector is None
        else {entry.dimension: entry for entry in new_vector.entries}
    )
    return tuple(
        _compare_dimension(
            dimension,
            old_entries.get(dimension),
            new_entries.get(dimension),
            profile,
        )
        for dimension in sorted(old_entries.keys() | new_entries.keys())
    )


def _band_comparison(
    coverage: WeeklyCoverage,
    old_vector: EffectivePriceVector | None,
    new_vector: EffectivePriceVector | None,
    profile: ProviderProfile,
    provenance: ComparisonMode,
) -> PriceBandComparison:
    dimensions = _compare_vectors(old_vector, new_vector, profile)
    direction = (
        _movement_direction(tuple(fact.direction for fact in dimensions))
        if _has_single_comparison_basis(dimensions)
        else "unknown"
    )
    return PriceBandComparison(
        coverage=_normalize_weekly_segments(coverage),
        dimensions=dimensions,
        direction=direction,
        percentage=(
            _common_percentage(dimensions)
            if direction in {"higher", "lower", "unchanged"}
            else None
        ),
        provenance=provenance,
    )


def _dominant_band_identity(
    compiled: CompiledConditionalPricingPolicy,
    profile: ProviderProfile,
) -> PriceVectorIdentity | None:
    bands = compiled.effective_bands
    if len(bands) < 2:
        return None

    dimensions = tuple(
        entry.dimension for entry in bands[0].effective_prices.entries
    )
    if not dimensions:
        return None

    expected_bases: tuple[tuple[str, str], ...] | None = None
    normalized_vectors: list[tuple[Fraction, ...]] = []
    maxima: list[Fraction] | None = None
    for band in bands:
        entries = band.effective_prices.entries
        if tuple(entry.dimension for entry in entries) != dimensions:
            return None

        resolved_values = tuple(
            _resolved_effective_value(entry, profile) for entry in entries
        )
        if any(value is None for value in resolved_values):
            return None
        complete_values = tuple(
            value for value in resolved_values if value is not None
        )
        if any(
            value.price_rule.unit_label is None
            or value.price_rule.comparison_group is None
            for value in complete_values
        ):
            return None
        bases = tuple(
            (
                value.price_rule.unit_label,
                value.price_rule.comparison_group,
            )
            for value in complete_values
        )
        if expected_bases is None:
            expected_bases = bases
        elif bases != expected_bases:
            return None

        normalized = tuple(
            value.normalized_exact_value for value in complete_values
        )
        normalized_vectors.append(normalized)
        if maxima is None:
            maxima = list(normalized)
        else:
            for index, value in enumerate(normalized):
                if value > maxima[index]:
                    maxima[index] = value

    if maxima is None:
        return None
    maximum_vector = tuple(maxima)
    candidate_indices = tuple(
        index
        for index, vector in enumerate(normalized_vectors)
        if vector == maximum_vector
    )
    if len(candidate_indices) != 1:
        return None

    candidate_index = candidate_indices[0]
    if not any(
        any(
            candidate_value > other_value
            for candidate_value, other_value in zip(
                maximum_vector, other_vector, strict=True
            )
        )
        for index, other_vector in enumerate(normalized_vectors)
        if index != candidate_index
    ):
        return None
    return bands[candidate_index].effective_prices.canonical_identity


def _aggregate_band_direction(
    bands: tuple[PriceBandComparison, ...],
) -> BandMovementDirection:
    return _movement_direction(tuple(band.direction for band in bands))


def _build_conditional_comparison(
    transition: PricingTransition,
    old_compiled: CompiledConditionalPricingPolicy,
    new_compiled: CompiledConditionalPricingPolicy,
    profile: ProviderProfile,
) -> tuple[
    ConditionalPricingComparison | None,
    tuple[ComparisonInhibitionReason, ...],
]:
    reasons: list[ComparisonInhibitionReason] = []
    for compiled in (old_compiled, new_compiled):
        for reason in compiled.comparison_inhibition_reasons:
            _append_once(reasons, reason)
    if reasons:
        return None, tuple(reasons)
    if old_compiled.base_prices is None or new_compiled.base_prices is None:
        return None, ("incomplete_comparison_vector",)

    displayed = old_compiled if transition == "removed" else new_compiled
    peak_identity = _dominant_band_identity(displayed, profile)
    compared: list[
        tuple[PriceBandComparison, EffectivePriceVector | None]
    ] = []
    mode: ComparisonMode
    aggregate_allowed = True
    if old_compiled.policy_present != new_compiled.policy_present:
        mode = "grouped-vs-default"
        scheduled = new_compiled if new_compiled.policy_present else old_compiled
        default = old_compiled if new_compiled.policy_present else new_compiled
        for band in scheduled.effective_bands:
            old_vector, new_vector = (
                (default.base_prices, band.effective_prices)
                if new_compiled.policy_present
                else (band.effective_prices, default.base_prices)
            )
            compared.append(
                (
                    _band_comparison(
                        band.coverage,
                        old_vector,
                        new_vector,
                        profile,
                        mode,
                    ),
                    band.effective_prices,
                )
            )
    else:
        old_partition = _comparison_partition(old_compiled)
        new_partition = _comparison_partition(new_compiled)
        if old_partition == new_partition:
            mode = "same-partition"
            segments = old_partition
        else:
            mode = "exact-regions"
            # A common finite refinement preserves exact old/new vector facts
            # without pretending the different policy partitions are one
            # comparable envelope.
            segments = partition_weekly_segments(old_partition, new_partition)
            aggregate_allowed = False
            _append_once(reasons, "partition_mismatch")
        buckets: dict[
            tuple[PriceVectorIdentity, PriceVectorIdentity],
            tuple[EffectivePriceVector, EffectivePriceVector, list[WeeklySegment]],
        ] = {}
        old_vectors = _vectors_covering_segments(old_compiled, segments)
        new_vectors = _vectors_covering_segments(new_compiled, segments)
        for segment, old_vector, new_vector in zip(
            segments,
            old_vectors,
            new_vectors,
            strict=True,
        ):
            if old_vector is None or new_vector is None:
                _append_once(reasons, "incomplete_comparison_vector")
                continue
            key = (old_vector.canonical_identity, new_vector.canonical_identity)
            if key not in buckets:
                buckets[key] = (old_vector, new_vector, [])
            buckets[key][2].append(segment)
        for old_vector, new_vector, coverage in buckets.values():
            compared.append(
                (
                    _band_comparison(
                        tuple(coverage), old_vector, new_vector, profile, mode
                    ),
                    old_vector if transition == "removed" else new_vector,
                )
            )

    for band, _displayed_vector in compared:
        if (
            any(fact.direction == "unknown" for fact in band.dimensions)
            or not _has_single_comparison_basis(band.dimensions)
        ):
            _append_once(reasons, "incompatible_price_basis")
    peak_matches = tuple(
        index
        for index, (_band, displayed_vector) in enumerate(compared)
        if peak_identity is not None
        and displayed_vector is not None
        and displayed_vector.canonical_identity == peak_identity
    )
    peak_index = peak_matches[0] if len(peak_matches) == 1 else None
    peak_match_set = set(peak_matches)
    bands = tuple(
        replace(band, is_peak=index in peak_match_set)
        for index, (band, _displayed_vector) in enumerate(compared)
    )
    if not bands:
        return None, tuple(reasons)
    aggregate_direction = (
        _aggregate_band_direction(bands)
        if aggregate_allowed and "incompatible_price_basis" not in reasons
        else None
    )
    return (
        ConditionalPricingComparison(
            mode=mode,
            bands=bands,
            aggregate_direction=aggregate_direction,
            inhibition_reasons=tuple(reasons),
            peak_band_index=peak_index,
        ),
        tuple(reasons),
    )


def _explicit_assignment_identity(
    rule: ConditionalPricingRule,
) -> PriceAssignmentIdentity:
    return _price_assignments_identity(rule.explicit_prices)


def _price_assignments_identity(
    assignments: tuple[ConditionalPriceAssignment, ...],
) -> PriceAssignmentIdentity:
    return tuple(
        sorted(
            (
                assignment.dimension,
                _canonical_json(assignment.raw_value),
                assignment.price_rule,
            )
            for assignment in assignments
        )
    )


def _grouped_semantic_signature(
    compiled: CompiledConditionalPricingPolicy,
) -> tuple[WeeklyGroupedSemanticRegion, ...]:
    """Partition one grouped side by effective value and explicit assignment."""
    if compiled.base_prices is None:
        return ()

    cells = [
        WeeklyGroupedSemanticRegion(
            segment=region.segment,
            effective_price_identity=region.effective_prices.canonical_identity,
            explicit_assignment_identity=_price_assignments_identity(
                region.explicit_prices
            ),
        )
        for region in compiled.grouped_regions
    ]
    cells.extend(
        WeeklyGroupedSemanticRegion(
            segment=segment,
            effective_price_identity=compiled.base_prices.canonical_identity,
            explicit_assignment_identity=(),
        )
        for segment in compiled.default_coverage
    )
    cells.sort(key=lambda cell: cell.segment)

    signature: list[WeeklyGroupedSemanticRegion] = []
    for cell in cells:
        if (
            signature
            and signature[-1].effective_price_identity
            == cell.effective_price_identity
            and signature[-1].explicit_assignment_identity
            == cell.explicit_assignment_identity
            and signature[-1].segment.weekday_index
            == cell.segment.weekday_index
            and signature[-1].segment.end_minute == cell.segment.start_minute
        ):
            previous = signature[-1]
            signature[-1] = WeeklyGroupedSemanticRegion(
                segment=WeeklySegment(
                    previous.segment.weekday_index,
                    previous.segment.start_minute,
                    cell.segment.end_minute,
                ),
                effective_price_identity=cell.effective_price_identity,
                explicit_assignment_identity=cell.explicit_assignment_identity,
            )
        else:
            signature.append(cell)
    return tuple(signature)


def _assignments_commute(
    left: ConditionalPricingRule,
    right: ConditionalPricingRule,
) -> bool:
    left_assignments = {
        assignment.dimension: assignment for assignment in left.explicit_prices
    }
    right_assignments = {
        assignment.dimension: assignment for assignment in right.explicit_prices
    }
    for dimension in left_assignments.keys() & right_assignments.keys():
        left_assignment = left_assignments[dimension]
        right_assignment = right_assignments[dimension]
        if (
            _canonical_json(left_assignment.raw_value)
            != _canonical_json(right_assignment.raw_value)
            or left_assignment.price_rule != right_assignment.price_rule
        ):
            return False
    return True


def _semantic_rule_sequence(
    policy: ConditionalPricingPolicy,
) -> tuple[tuple[tuple[Any, ...], ConditionalPricingRule], ...]:
    """Match duplicate conditions by assignments without changing provenance IDs."""
    occurrences: Counter[tuple[Any, ...]] = Counter()
    sequence: list[tuple[tuple[Any, ...], ConditionalPricingRule]] = []
    for rule in policy.rules:
        semantic_key = (
            rule.canonical_condition_identity,
            _explicit_assignment_identity(rule),
        )
        occurrence = occurrences[semantic_key]
        occurrences[semantic_key] += 1
        sequence.append(((semantic_key, occurrence), rule))
    return tuple(sequence)


def _semantic_change(
    transition: PricingTransition,
    old_policy: ConditionalPricingPolicy | None,
    new_policy: ConditionalPricingPolicy | None,
    old_compiled: CompiledConditionalPricingPolicy | None,
    new_compiled: CompiledConditionalPricingPolicy | None,
    structural: ConditionalPricingStructuralComparison | None,
) -> bool:
    if transition != "changed":
        return True
    if (
        old_policy is None
        or new_policy is None
        or old_compiled is None
        or new_compiled is None
        or structural is None
    ):
        return True

    if (
        not old_compiled.grouping_inhibition_reasons
        and not new_compiled.grouping_inhibition_reasons
    ):
        return _grouped_semantic_signature(
            old_compiled
        ) != _grouped_semantic_signature(new_compiled)

    if structural.old_only or structural.new_only:
        return True

    old_sequence = _semantic_rule_sequence(old_policy)
    new_sequence = _semantic_rule_sequence(new_policy)
    old_tokens = tuple(token for token, _rule in old_sequence)
    new_tokens = tuple(token for token, _rule in new_sequence)
    if set(old_tokens) != set(new_tokens):
        return True
    if old_tokens == new_tokens:
        return False
    if max(len(old_tokens), len(new_tokens)) > MAX_EXACT_REORDERED_RULE_COUNT:
        return True

    old_positions = {token: index for index, token in enumerate(old_tokens)}
    new_positions = {token: index for index, token in enumerate(new_tokens)}
    old_rules = {token: rule for token, rule in old_sequence}
    coverage_by_source_index = {
        compiled.source_rule.source_index: compiled.coverage
        for compiled in old_compiled.ordered_rules
    }
    for left_index, left_token in enumerate(old_tokens):
        for right_token in old_tokens[left_index + 1 :]:
            order_reversed = (
                old_positions[left_token] < old_positions[right_token]
            ) != (new_positions[left_token] < new_positions[right_token])
            if not order_reversed:
                continue
            left_rule = old_rules[left_token]
            right_rule = old_rules[right_token]
            if _canonical_weekly_segments_overlap(
                coverage_by_source_index[left_rule.source_index],
                coverage_by_source_index[right_rule.source_index],
            ) and not _assignments_commute(left_rule, right_rule):
                return True
    return False


def _explicit_only_compiled_policy(
    compiled: CompiledConditionalPricingPolicy,
) -> CompiledConditionalPricingPolicy:
    """Suppress inherited/effective claims for an overall ordered comparison."""
    grouping_reasons = compiled.grouping_inhibition_reasons
    if not grouping_reasons:
        grouping_reasons = ("comparison_requires_ordered_rules",)
    return replace(
        compiled,
        base_prices=None,
        ordered_rules=tuple(
            replace(rule, effective_prices=None) for rule in compiled.ordered_rules
        ),
        grouped_regions=(),
        default_coverage=(),
        effective_bands=(),
        effective_partition=(),
        grouping_inhibition_reasons=grouping_reasons,
    )


def _policy_dimensions(
    interpretation: ConditionalPricingInterpretation,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                assignment.dimension
                for policy in (interpretation.old_policy, interpretation.new_policy)
                if policy is not None
                for rule in policy.rules
                for assignment in rule.explicit_prices
            }
        )
    )


def _dimension_column_rule(
    interpretation: ConditionalPricingInterpretation,
    dimension: str,
) -> ResolvedPriceRule | None:
    rules = tuple(
        assignment.price_rule
        for policy in (interpretation.old_policy, interpretation.new_policy)
        if policy is not None
        for rule in policy.rules
        for assignment in rule.explicit_prices
        if assignment.dimension == dimension
    )
    if not rules:
        return None
    first = rules[0]
    if (
        first.match_source == "unmatched"
        or first.comparison_group is None
        or not first.unit_label.strip()
        or any(
            rule.unit_label != first.unit_label
            or rule.comparison_group != first.comparison_group
            for rule in rules[1:]
        )
    ):
        return None
    return first


def decide_sibling_base_price_absorption(
    event: PricingComparisonEvent,
    profile: ProviderProfile,
    interpretation: ConditionalPricingInterpretation,
    *,
    consumed_references: tuple[SourceChangeReference, ...] = (),
) -> tuple[AbsorbedBasePriceChange, ...]:
    """Return pure occurrence-aware sibling decisions; never mutate the edge."""
    if event.identity != interpretation.identity:
        return ()
    if (
        not interpretation.semantic_change
        or interpretation.state == "raw-fallback"
        or event.old_model_metadata is None
        or event.new_model_metadata is None
        or "missing_event_snapshot" in interpretation.comparison_inhibition_reasons
    ):
        return ()

    sources = _source_references(event)
    consumed = set(consumed_references)
    decisions: list[AbsorbedBasePriceChange] = []
    for dimension in _policy_dimensions(interpretation):
        field_path = profile.pricing_override_base_paths.get(dimension)
        column_rule = _dimension_column_rule(interpretation, dimension)
        if field_path is None or column_rule is None:
            continue
        sibling_rule = resolve_price_rule(field_path, profile)
        if (
            sibling_rule.match_source == "unmatched"
            or sibling_rule.comparison_group is None
            or sibling_rule.unit_label != column_rule.unit_label
            or sibling_rule.comparison_group != column_rule.comparison_group
        ):
            continue
        old_present, expected_old = _exact_metadata_entry(
            event.old_model_metadata, field_path
        )
        new_present, expected_new = _exact_metadata_entry(
            event.new_model_metadata, field_path
        )
        # A sibling row uses ``None`` for an absent side.  A stored JSON null
        # is present but has no resolvable monetary value, so treating it as
        # absence would manufacture an absorption decision.
        if (old_present and expected_old is None) or (
            new_present and expected_new is None
        ):
            continue
        expected_old_value = expected_old if old_present else None
        expected_new_value = expected_new if new_present else None
        expected_old_json = _canonical_json(expected_old_value)
        expected_new_json = _canonical_json(expected_new_value)
        matching = tuple(
            source
            for source in sources
            if source.reference.field_name == field_path
            and source.reference.old_value_canonical_json == expected_old_json
            and source.reference.new_value_canonical_json == expected_new_json
        )
        if not matching:
            continue
        # One schedule/base fact justifies one occurrence. If that canonical
        # occurrence is already consumed, a repeated duplicate is not a second
        # independent justification and remains ordinary.
        source = matching[0]
        if source.reference in consumed:
            continue
        movement = resolve_direct_price_movement(
            field_path,
            source.old_value,
            source.new_value,
            profile,
            source_change=source.reference,
        )
        if (
            movement is None
            or movement.unit_label != column_rule.unit_label
            or movement.comparison_group != column_rule.comparison_group
        ):
            continue
        decisions.append(
            AbsorbedBasePriceChange(
                dimension=dimension,
                source_change=source.reference,
                movement=movement,
            )
        )
        consumed.add(source.reference)
    return tuple(decisions)


def _displayed_policy(
    interpretation: ConditionalPricingInterpretation,
) -> ConditionalPricingPolicy | None:
    return (
        interpretation.old_policy
        if interpretation.transition == "removed"
        else interpretation.new_policy
    )


def _displayed_compiled_policy(
    interpretation: ConditionalPricingInterpretation,
) -> CompiledConditionalPricingPolicy | None:
    return (
        interpretation.old_compiled_policy
        if interpretation.transition == "removed"
        else interpretation.new_compiled_policy
    )


def _raw_displayed_rule_count(
    interpretation: ConditionalPricingInterpretation,
) -> int:
    if not interpretation.source_changes:
        return 0
    source = interpretation.source_changes[0]
    raw = (
        source.old_value
        if interpretation.transition == "removed"
        else source.new_value
    )
    return len(raw) if isinstance(raw, tuple) else 0


def _fact_identity(fact: DirectPriceMovementFact) -> tuple[Any, ...]:
    if fact.source_change is not None:
        return ("source", fact.source_change.transition_key)

    def resolved_identity(
        value: ResolvedPriceValue | None,
    ) -> tuple[Any, ...] | None:
        if value is None:
            return None
        return (
            value.field_path,
            _canonical_json(value.raw_value),
            value.raw_display,
            value.normalized_value,
            value.price_rule,
        )

    return (
        "value",
        fact.field_path,
        resolved_identity(fact.old_value),
        resolved_identity(fact.new_value),
        fact.direction,
        fact.delta,
        fact.percentage,
        fact.unit_label,
        fact.comparison_group,
    )


def _ordinary_model_bucket(
    facts: tuple[DirectPriceMovementFact, ...],
) -> ModelPriceBucket:
    directions = {fact.direction for fact in facts}
    if "higher" in directions and "lower" in directions:
        return "mixed"
    if "higher" in directions:
        return "higher"
    if "lower" in directions:
        return "lower"
    if "coverage" in directions:
        return "coverage"
    return "none"


def build_model_pricing_accounting(
    interpretation: ConditionalPricingInterpretation | None,
    *,
    direct_price_facts: tuple[DirectPriceMovementFact, ...] = (),
) -> ModelPricingAccounting:
    """Build one immutable pre-filter record, ready for later ordinary facts."""
    unique_facts: list[DirectPriceMovementFact] = []
    seen_facts: set[tuple[Any, ...]] = set()
    existing_facts = (
        ()
        if interpretation is None or interpretation.accounting is None
        else interpretation.accounting.direct_price_facts
    )
    for fact in (*existing_facts, *direct_price_facts):
        if not isinstance(fact, DirectPriceMovementFact):
            raise TypeError("direct_price_facts must contain DirectPriceMovementFact values")
        identity = _fact_identity(fact)
        if identity not in seen_facts:
            seen_facts.add(identity)
            unique_facts.append(fact)

    conditional_changed = bool(
        interpretation is not None and interpretation.semantic_change
    )
    policy_count = 1 if conditional_changed else 0
    if conditional_changed and interpretation is not None:
        displayed_policy = _displayed_policy(interpretation)
        source_rule_count = (
            len(displayed_policy.rules)
            if displayed_policy is not None
            else _raw_displayed_rule_count(interpretation)
        )
        dimensions = _policy_dimensions(interpretation)
        if not dimensions and interpretation.accounting is not None:
            # A finalized raw fallback can retain a safely recognized explicit
            # dimension union even though selector parsing did not yield a
            # ConditionalPricingPolicy. Rebuilding with later ordinary facts
            # must preserve that contribution.
            dimensions = interpretation.accounting.schedule_dimensions
        displayed_compiled = _displayed_compiled_policy(interpretation)
        effective_band_count = (
            len(displayed_compiled.effective_bands)
            if displayed_compiled is not None
            else 0
        )
        model_bucket: ModelPriceBucket = "conditional"
    else:
        source_rule_count = 0
        dimensions = ()
        effective_band_count = 0
        model_bucket = _ordinary_model_bucket(tuple(unique_facts))

    return ModelPricingAccounting(
        direct_price_facts=tuple(unique_facts),
        direct_price_field_count=len(unique_facts),
        conditional_policy_count=policy_count,
        source_rule_count=source_rule_count,
        schedule_dimensions=dimensions,
        schedule_dimension_count=len(dimensions),
        effective_band_count=effective_band_count,
        model_bucket=model_bucket,
    )


def _raw_registered_dimensions(
    interpretation: ConditionalPricingInterpretation,
    profile: ProviderProfile,
) -> tuple[str, ...]:
    dimensions: set[str] = set()
    for source in interpretation.source_changes:
        for raw_policy in (source.old_value, source.new_value):
            if not isinstance(raw_policy, tuple):
                continue
            for raw_rule in raw_policy:
                if not isinstance(raw_rule, Mapping):
                    continue
                dimensions.update(
                    key
                    for key in raw_rule
                    if key in profile.pricing_override_base_paths
                )
    return tuple(sorted(dimensions))


def _finalize_interpretation(
    event: PricingComparisonEvent,
    profile: ProviderProfile,
    interpretation: ConditionalPricingInterpretation,
) -> ConditionalPricingInterpretation:
    decisions = decide_sibling_base_price_absorption(
        event,
        profile,
        interpretation,
    )
    accounting = build_model_pricing_accounting(
        interpretation,
        direct_price_facts=tuple(decision.movement for decision in decisions),
    )
    if interpretation.semantic_change and not accounting.schedule_dimensions:
        raw_dimensions = _raw_registered_dimensions(interpretation, profile)
        if raw_dimensions:
            accounting = replace(
                accounting,
                schedule_dimensions=raw_dimensions,
                schedule_dimension_count=len(raw_dimensions),
            )
    return replace(
        interpretation,
        absorbed_base_price_changes=tuple(
            decision.source_change for decision in decisions
        ),
        accounting=accounting,
    )


def interpret_conditional_pricing(
    event: PricingComparisonEvent,
    profile: ProviderProfile,
) -> ConditionalPricingInterpretation | None:
    """Interpret one exact comparison edge through bounded schedule semantics."""
    if not isinstance(event, PricingComparisonEvent):
        raise TypeError("event must be a PricingComparisonEvent")
    if not isinstance(profile, ProviderProfile):
        raise TypeError("profile must be a ProviderProfile")

    all_source_changes = _source_references(event)
    parent_changes = tuple(
        change for change in all_source_changes if change.reference.field_name == _PARENT_FIELD
    )
    if not parent_changes:
        return None
    first_parent = parent_changes[0]
    transition = _transition(first_parent.old_value, first_parent.new_value)
    if len(parent_changes) > 1:
        return _finalize_interpretation(
            event,
            profile,
            _raw_fallback(
                event,
                parent_changes,
                "multiple_parent_changes",
                transition=_aggregate_parent_transition(parent_changes),
            ),
        )
    if first_parent.old_value is None and first_parent.new_value is None:
        return _finalize_interpretation(
            event,
            profile,
            _raw_fallback(
                event,
                parent_changes,
                "malformed_parent_transition",
                transition=transition,
            ),
        )
    old_policy: ConditionalPricingPolicy | None = None
    new_policy: ConditionalPricingPolicy | None = None
    side_errors: list[FallbackReason] = []
    if first_parent.old_value is not None:
        try:
            old_policy = _parse_policy(first_parent.old_value, profile)
        except _PolicyDataError as exc:
            side_errors.append(exc.reason)
    if first_parent.new_value is not None:
        try:
            new_policy = _parse_policy(first_parent.new_value, profile)
        except _PolicyDataError as exc:
            side_errors.append(exc.reason)
    if side_errors:
        fallback_reason = (
            side_errors[0]
            if all(reason == side_errors[0] for reason in side_errors)
            else "multiple_policy_errors"
        )
        return _finalize_interpretation(
            event,
            profile,
            _raw_fallback(
                event,
                parent_changes,
                fallback_reason,
                transition=transition,
                old_policy=old_policy,
                new_policy=new_policy,
            ),
        )

    snapshots_complete = (
        event.old_model_metadata is not None and event.new_model_metadata is not None
    )
    dimensions = tuple(
        sorted(
            {
                assignment.dimension
                for policy in (old_policy, new_policy)
                if policy is not None
                for rule in policy.rules
                for assignment in rule.explicit_prices
            }
        )
    )
    old_compiled = _compile_policy(
        old_policy if old_policy is not None else ConditionalPricingPolicy((), ()),
        event.old_model_metadata,
        profile,
        dimensions,
        policy_present=old_policy is not None,
        snapshots_complete=snapshots_complete,
    )
    new_compiled = _compile_policy(
        new_policy if new_policy is not None else ConditionalPricingPolicy((), ()),
        event.new_model_metadata,
        profile,
        dimensions,
        policy_present=new_policy is not None,
        snapshots_complete=snapshots_complete,
    )
    grouping_reasons: list[GroupingInhibitionReason] = []
    comparison_reasons: list[ComparisonInhibitionReason] = []
    for compiled in (old_compiled, new_compiled):
        if compiled is None:
            continue
        for reason in compiled.grouping_inhibition_reasons:
            _append_once(grouping_reasons, reason)
        for reason in compiled.comparison_inhibition_reasons:
            _append_once(comparison_reasons, reason)
    state: InterpretationState = (
        "ordered-rules" if grouping_reasons else "grouped-schedule"
    )
    if state == "ordered-rules":
        comparison_reasons = [
            reason for reason in comparison_reasons if reason != "comparison_deferred"
        ]
        _append_once(comparison_reasons, "ordered_rules")
    structural = _structural_compare(old_policy, new_policy)
    semantic_change = _semantic_change(
        transition,
        old_policy,
        new_policy,
        old_compiled,
        new_compiled,
        structural,
    )
    comparison: ConditionalPricingComparison | None = None
    if state == "grouped-schedule" and semantic_change:
        comparison, bounded_reasons = _build_conditional_comparison(
            transition,
            old_compiled,
            new_compiled,
            profile,
        )
        comparison_reasons = list(bounded_reasons)
    if state == "ordered-rules":
        old_compiled = _explicit_only_compiled_policy(old_compiled)
        new_compiled = _explicit_only_compiled_policy(new_compiled)
    return _finalize_interpretation(
        event,
        profile,
        ConditionalPricingInterpretation(
            identity=event.identity,
            state=state,
            semantic_change=semantic_change,
            fallback_reason=None,
            grouping_inhibition_reasons=tuple(grouping_reasons),
            comparison_inhibition_reasons=tuple(comparison_reasons),
            transition=transition,
            old_policy=old_policy,
            new_policy=new_policy,
            old_compiled_policy=old_compiled,
            new_compiled_policy=new_compiled,
            absorbed_base_price_changes=(),
            comparison=comparison,
            accounting=None,
            source_changes=parent_changes,
            structural_comparison=structural,
            canonical_evidence_changed=(
                first_parent.reference.old_value_canonical_json
                != first_parent.reference.new_value_canonical_json
            ),
        ),
    )
