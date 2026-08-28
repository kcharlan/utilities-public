"""Format-neutral parsing for provider-declared conditional pricing policies.

This module deliberately stops at validated structural evidence.  Weekly
coverage, precedence equivalence, price movement, absorption, accounting, and
human rendering are later semantic layers.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

from .change_render import resolve_price_rule
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
    "schedule_compilation_deferred",
    "missing_event_snapshot",
]
ComparisonInhibitionReason: TypeAlias = Literal[
    "comparison_deferred",
    "missing_event_snapshot",
    "missing_price_comparison_group",
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
    semantic_change: bool | None
    fallback_reason: FallbackReason | None
    grouping_inhibition_reasons: tuple[GroupingInhibitionReason, ...]
    comparison_inhibition_reasons: tuple[ComparisonInhibitionReason, ...]
    transition: PricingTransition
    old_policy: ConditionalPricingPolicy | None
    new_policy: ConditionalPricingPolicy | None
    absorbed_base_price_changes: tuple[SourceChangeReference, ...]
    comparison: Any | None
    accounting: Any | None
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
    return ConditionalPricingInterpretation(
        identity=event.identity,
        state="raw-fallback",
        semantic_change=None,
        fallback_reason=reason,
        grouping_inhibition_reasons=(),
        comparison_inhibition_reasons=(),
        transition=transition,
        old_policy=old_policy,
        new_policy=new_policy,
        absorbed_base_price_changes=(),
        comparison=None,
        accounting=None,
        source_changes=source_changes,
        structural_comparison=None,
        canonical_evidence_changed=any(
            source.reference.old_value_canonical_json
            != source.reference.new_value_canonical_json
            for source in source_changes
        ),
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


def _is_valid_numeric_assignment(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(numeric)


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
                price_rule = resolve_price_rule(price_path, profile)
                if (
                    price_rule.match_source == "unmatched"
                    or not price_rule.unit_label.strip()
                    or not _is_valid_numeric_assignment(raw_value)
                ):
                    raise _PolicyDataError("unresolved_price_dimension")
                explicit_prices.append(
                    ConditionalPriceAssignment(
                        field_name,
                        raw_value,
                        source_key_index,
                        price_rule,
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


def interpret_conditional_pricing(
    event: PricingComparisonEvent,
    profile: ProviderProfile,
) -> ConditionalPricingInterpretation | None:
    """Parse one exact comparison edge without deciding schedule semantics."""
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
        return _raw_fallback(
            event,
            parent_changes,
            "multiple_parent_changes",
            transition=_aggregate_parent_transition(parent_changes),
        )
    if first_parent.old_value is None and first_parent.new_value is None:
        return _raw_fallback(
            event,
            parent_changes,
            "malformed_parent_transition",
            transition=transition,
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
        return _raw_fallback(
            event,
            parent_changes,
            fallback_reason,
            transition=transition,
            old_policy=old_policy,
            new_policy=new_policy,
        )

    grouping_reasons: list[GroupingInhibitionReason] = [
        "schedule_compilation_deferred"
    ]
    comparison_reasons: list[ComparisonInhibitionReason] = ["comparison_deferred"]
    if any(
        assignment.price_rule.comparison_group is None
        for policy in (old_policy, new_policy)
        if policy is not None
        for rule in policy.rules
        for assignment in rule.explicit_prices
    ):
        comparison_reasons.append("missing_price_comparison_group")
    if event.old_model_metadata is None or event.new_model_metadata is None:
        grouping_reasons.append("missing_event_snapshot")
        comparison_reasons.append("missing_event_snapshot")
    structural = _structural_compare(old_policy, new_policy)
    return ConditionalPricingInterpretation(
        identity=event.identity,
        state="ordered-rules",
        semantic_change=None,
        fallback_reason=None,
        grouping_inhibition_reasons=tuple(grouping_reasons),
        comparison_inhibition_reasons=tuple(comparison_reasons),
        transition=transition,
        old_policy=old_policy,
        new_policy=new_policy,
        absorbed_base_price_changes=(),
        comparison=None,
        accounting=None,
        source_changes=parent_changes,
        structural_comparison=structural,
        canonical_evidence_changed=(
            first_parent.reference.old_value_canonical_json
            != first_parent.reference.new_value_canonical_json
        ),
    )
