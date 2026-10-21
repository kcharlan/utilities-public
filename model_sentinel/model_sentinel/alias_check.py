"""Alias price checks, divergence events, and endpoint price ladders.

This module holds no I/O. An alias is a catalog model whose `alias_target`
names another catalog model; its chain is resolved by exact catalog ID with
`endpoints.resolve_alias_chain`, independently of link validity. An alias and
its target are compared on the scalar price leaves `endpoints`' collector
returns, and the target's captured endpoint list, when supplied, is checked for
endpoints that carry the alias's prices. Price ladders place one leaf's
endpoint prices and reference marks on a shared log scale for report and API
consumers. Every comparison uses exact normalized values; records carry only
JSON-safe values.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from fractions import Fraction
from typing import Any, Final

from .change_render import (
    ResolvedPriceValue,
    format_price_values,
    format_qualified_label,
    pricing_field_sort_key,
    resolve_field_label,
    resolve_price_rule,
)
from .endpoints import (
    MAPPING_INVALID_LINK,
    PriceLeaf,
    alias_declaration,
    resolve_alias_chain,
    resolve_price_leaf,
    resolved_price_leaves,
)
from .models import (
    AliasDivergence,
    AliasEndpointMatch,
    AliasEvaluation,
    AliasEvent,
    AliasLeafComparison,
    AliasUnavailableLeaf,
    EndpointListRecord,
    Ladder,
    LadderEntry,
    LadderMarkInput,
    LadderPosition,
    LadderUnplaced,
    NormalizedModel,
)
from .provider_profiles import ProviderProfile

ALIAS_EVENT_NEW: Final = "new"
ALIAS_EVENT_CHANGED: Final = "changed"
ALIAS_EVENT_PERSISTING: Final = "persisting"
ALIAS_EVENT_RESOLVED: Final = "resolved"
ALIAS_EVENT_UNAVAILABLE: Final = "unavailable"
ALIAS_EVENT_KINDS: Final = (
    ALIAS_EVENT_NEW,
    ALIAS_EVENT_CHANGED,
    ALIAS_EVENT_PERSISTING,
    ALIAS_EVENT_RESOLVED,
    ALIAS_EVENT_UNAVAILABLE,
)

# An evaluation's `unavailable_reason` (the target is unresolved) reuses the
# mapping codes `alias_target_missing` and `alias_cycle`, plus `invalid_link`
# for a malformed alias declaration on the alias or at the chain's end.

# Why endpoint matching is unavailable, besides an unresolved target's reason.
MATCH_NO_COMPARABLE_LEAVES: Final = "no_comparable_leaves"
MATCH_NOT_CAPTURED: Final = "not_captured"
MATCH_LIST_MISSING: Final = "list_missing"
MATCH_LIST_FAILED: Final = "list_failed"

# Why an `unavailable` event cannot show the prior divergence, besides an
# unresolved target's reason.
EVENT_ALIAS_MISSING: Final = "alias_missing"
EVENT_NOT_ALIAS: Final = "not_alias"
EVENT_LEAVES_UNAVAILABLE: Final = "leaves_unavailable"

LEAF_RESOLVED: Final = "resolved"
LEAF_UNRESOLVED: Final = "unresolved"
LEAF_MISSING: Final = "missing"
LEAF_INCOMPATIBLE: Final = "incompatible"

LADDER_ENDPOINT: Final = "endpoint"
LADDER_MARK: Final = "mark"
UNPLACED_ZERO: Final = "zero"
UNPLACED_NEGATIVE: Final = "negative"
UNPLACED_MISSING: Final = "missing"
UNPLACED_INVALID: Final = "invalid"
UNPLACED_INCOMPATIBLE: Final = "incompatible"

_CENTER: Final = 0.5
_MATCHING: Final = "matching"
_DIFFERING: Final = "differing"
_UNKNOWN: Final = "unknown"

# Catalog models keyed by catalog model ID: either `NormalizedModel` objects
# (a scan's catalog map) or their decoded metadata objects (a dossier read).
CatalogModels = Mapping[str, NormalizedModel | Mapping[str, Any]]


def evaluate_aliases(
    models: CatalogModels,
    profile: ProviderProfile,
    lists: Sequence[EndpointListRecord] | None = None,
) -> tuple[AliasEvaluation, ...]:
    """Evaluate every alias in one catalog snapshot, sorted by alias ID.

    Each alias is compared with the terminal model of its alias chain on the
    fixed set of price leaves both resolve with the same unit and comparison
    group; other leaves are kept as unavailable evidence. `lists` are the
    endpoint-list records of a capture of this same snapshot
    (`EndpointCaptureSummary.lists` or `Store.load_endpoint_lists`); the
    target's list is the one whose `model_ids` include the terminal model.
    None means no capture evidence, which makes endpoint matching unavailable
    rather than empty. A model whose metadata is not an object is treated as
    having none: it is no alias, and as a target it offers no price leaves.
    """
    metadata = {model_id: _metadata(model) for model_id, model in models.items()}
    declarations = {model_id: alias_declaration(value) for model_id, value in metadata.items()}
    alias_targets = {model_id: target for model_id, (_, target) in declarations.items()}
    list_index = None if lists is None else _list_index(lists)
    evaluations: list[AliasEvaluation] = []
    for model_id in sorted(declarations):
        declares_alias, direct_target = declarations[model_id]
        if not declares_alias:
            continue
        if direct_target is None:
            evaluations.append(_unresolved(model_id, None, MAPPING_INVALID_LINK))
            continue
        terminal, error_code = resolve_alias_chain(model_id, alias_targets)
        if terminal is not None and declarations[terminal][0]:
            # The chain ends at a malformed alias declaration, not a model.
            terminal, error_code = None, MAPPING_INVALID_LINK
        if terminal is None:
            evaluations.append(_unresolved(model_id, direct_target, error_code))
            continue
        evaluations.append(
            _evaluate(
                model_id,
                direct_target,
                terminal,
                metadata[model_id],
                metadata[terminal],
                list_index,
                profile,
            )
        )
    return tuple(evaluations)


def divergence_events(
    baseline_models: CatalogModels | None,
    current_models: CatalogModels,
    profile: ProviderProfile,
    lists: Sequence[EndpointListRecord] | None = None,
) -> tuple[AliasEvent, ...]:
    """Classify each alias divergence between two catalog snapshots.

    A current divergence is `new` without a baseline divergence, `persisting`
    when its semantic signature is unchanged, else `changed` (a changed target
    changes the signature). A baseline divergence without a current one is
    `resolved` only when the alias currently resolves to a target and every
    previously divergent leaf is comparable and equal; otherwise it is
    `unavailable`, never a claim that the prices match again. `lists` are the
    current capture's lists and inform only current evaluations. Events are
    sorted by alias ID; aliases without a divergence on either side produce
    none.
    """
    baseline = {
        evaluation.alias_model_id: evaluation
        for evaluation in evaluate_aliases(baseline_models or {}, profile)
    }
    current = {
        evaluation.alias_model_id: evaluation
        for evaluation in evaluate_aliases(current_models, profile, lists)
    }
    events: list[AliasEvent] = []
    for alias_id in sorted(baseline.keys() | current.keys()):
        before = baseline.get(alias_id)
        after = current.get(alias_id)
        prior = before.divergence if before is not None else None
        now = after.divergence if after is not None else None
        if now is not None:
            if prior is None:
                kind = ALIAS_EVENT_NEW
            elif prior.signature == now.signature:
                kind = ALIAS_EVENT_PERSISTING
            else:
                kind = ALIAS_EVENT_CHANGED
            events.append(AliasEvent(kind, alias_id, after, before, None, now.leaves))
            continue
        if prior is None:
            continue
        reason, leaves = _prior_divergence_now(prior, after, alias_id in current_models)
        kind = ALIAS_EVENT_RESOLVED if reason is None else ALIAS_EVENT_UNAVAILABLE
        events.append(AliasEvent(kind, alias_id, after, before, reason, leaves))
    return tuple(events)


def price_ladder(
    endpoints: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    leaf: str,
    marks: Iterable[LadderMarkInput | tuple[str, str, Any]],
    profile: ProviderProfile,
) -> Ladder | None:
    """Place one price leaf's endpoint values and reference marks on a log scale.

    `endpoints` are (endpoint key, endpoint state) pairs, such as
    `KeyedEndpoint`s or observations' `(endpoint_key, state)`; the value is the
    endpoint's direct `pricing` child named by `leaf`, through the shared
    collector. `marks` are labelled reference prices, each resolved at its own
    field path. Only values with the leaf's strict unit and comparison-group
    identity are compatible. The domain spans the strictly positive compatible
    values, so marks beyond the endpoint prices widen it; positions are linear
    in log10 of the exact value, 0.5 when the domain has one distinct value.
    Equal exact values share one position, which keeps every key and label.
    Zero, negative, missing, invalid and incompatible values are returned
    unplaced with their reason. Returns None when the leaf has no strict
    identity or no positive compatible value can be placed.
    """
    identity = _rule_identity(leaf, profile)
    if identity is None:
        return None
    placed: dict[Fraction, list[tuple[ResolvedPriceValue, LadderEntry]]] = {}
    unplaced: list[tuple[LadderEntry, str, ResolvedPriceValue | None]] = []

    def take(kind: str, label: str, price: PriceLeaf | None) -> None:
        if price is None:
            unplaced.append((LadderEntry(kind, label, None), UNPLACED_MISSING, None))
            return
        entry = LadderEntry(kind, label, price.raw_value)
        reason = _unplaced_reason(price, identity, profile)
        if reason is None:
            resolved = _resolved_price(price)
            placed.setdefault(resolved.normalized_exact_value, []).append((resolved, entry))
            return
        signed = _resolved_price(price) if reason in (UNPLACED_ZERO, UNPLACED_NEGATIVE) else None
        unplaced.append((entry, reason, signed))

    for key, endpoint in endpoints:
        take(LADDER_ENDPOINT, key, _endpoint_leaf(endpoint, leaf, profile))
    for label, field_path, raw_value in marks:
        take(
            LADDER_MARK,
            label,
            None if raw_value is None else resolve_price_leaf(field_path, raw_value, profile),
        )
    if not placed:
        return None

    values = sorted(placed)
    shown = [placed[value][0][0] for value in values]
    signed = [price for _, _, price in unplaced if price is not None]
    # Every price on one ladder is displayed together, so they share a precision.
    displays = format_price_values((*shown, *signed), precision_basis=())
    signed_displays = iter(displays[len(shown) :])
    low = _log10(values[0])
    span = _log10(values[-1]) - low
    positions = tuple(
        LadderPosition(
            position=_position(value, low, span, index, len(values)),
            exact_value=str(value),
            normalized_value=shown[index].normalized_value,
            display=displays[index],
            entries=tuple(entry for _, entry in placed[value]),
        )
        for index, value in enumerate(values)
    )
    return Ladder(
        leaf=leaf,
        label=_label(leaf, profile),
        unit_label=identity[0],
        comparison_group=identity[1],
        domain_min_exact=positions[0].exact_value,
        domain_max_exact=positions[-1].exact_value,
        domain_min_display=positions[0].display,
        domain_max_display=positions[-1].display,
        positions=positions,
        unplaced=tuple(
            LadderUnplaced(
                kind=entry.kind,
                label=entry.label,
                raw_value=entry.raw_value,
                reason=reason,
                display=None if signed_price is None else next(signed_displays),
            )
            for entry, reason, signed_price in unplaced
        ),
    )


def _metadata(model: NormalizedModel | Mapping[str, Any]) -> Mapping[str, Any]:
    value = model.metadata() if isinstance(model, NormalizedModel) else model
    return value if isinstance(value, Mapping) else {}


def _list_index(lists: Sequence[EndpointListRecord]) -> dict[str, EndpointListRecord]:
    index: dict[str, EndpointListRecord] = {}
    for listing in lists:
        for model_id in listing.model_ids:
            index.setdefault(model_id, listing)
    return index


def _unresolved(
    alias_id: str,
    direct_target: str | None,
    reason: str | None,
) -> AliasEvaluation:
    return AliasEvaluation(
        alias_model_id=alias_id,
        alias_target_model_id=direct_target,
        target_model_id=None,
        unavailable_reason=reason,
        compared_leaves=(),
        unavailable_leaves=(),
        divergence=None,
        endpoint_match=_unavailable_match((), reason),
    )


def _evaluate(
    alias_id: str,
    direct_target: str,
    target_id: str,
    alias_metadata: Mapping[str, Any],
    target_metadata: Mapping[str, Any],
    list_index: Mapping[str, EndpointListRecord] | None,
    profile: ProviderProfile,
) -> AliasEvaluation:
    alias_leaves = {leaf.path: leaf for leaf in resolved_price_leaves(alias_metadata, profile)}
    target_leaves = {leaf.path: leaf for leaf in resolved_price_leaves(target_metadata, profile)}
    compared: list[AliasLeafComparison] = []
    required: list[PriceLeaf] = []
    unavailable: list[AliasUnavailableLeaf] = []
    for path in sorted(
        alias_leaves.keys() | target_leaves.keys(),
        key=lambda path: pricing_field_sort_key(path, profile),
    ):
        alias_leaf = alias_leaves.get(path)
        target_leaf = target_leaves.get(path)
        if (
            alias_leaf is not None
            and target_leaf is not None
            and alias_leaf.resolved
            and target_leaf.resolved
            and _identity(alias_leaf) == _identity(target_leaf)
        ):
            compared.append(_comparison(alias_leaf, target_leaf, profile))
            required.append(alias_leaf)
        else:
            unavailable.append(_unavailable_leaf(path, alias_leaf, target_leaf, profile))
    differing = tuple(leaf for leaf in compared if not leaf.equal)
    return AliasEvaluation(
        alias_model_id=alias_id,
        alias_target_model_id=direct_target,
        target_model_id=target_id,
        unavailable_reason=None,
        compared_leaves=tuple(compared),
        unavailable_leaves=tuple(unavailable),
        divergence=AliasDivergence(target_id, differing) if differing else None,
        endpoint_match=_match_endpoints(required, target_id, list_index, profile),
    )


def _identity(leaf: PriceLeaf) -> tuple[str | None, str | None]:
    return leaf.unit_label, leaf.comparison_group


def _label(path: str, profile: ProviderProfile) -> str:
    return format_qualified_label(*resolve_field_label(path, profile))


def _comparison(
    alias_leaf: PriceLeaf,
    target_leaf: PriceLeaf,
    profile: ProviderProfile,
) -> AliasLeafComparison:
    alias_price = _resolved_price(alias_leaf)
    target_price = _resolved_price(target_leaf)
    # The two values are displayed together, so they share one precision.
    alias_display, target_display = format_price_values(
        (alias_price, target_price), precision_basis=()
    )
    return AliasLeafComparison(
        path=alias_leaf.path,
        label=_label(alias_leaf.path, profile),
        unit_label=alias_price.price_rule.unit_label,
        comparison_group=alias_leaf.comparison_group,
        alias_raw=alias_leaf.raw_value,
        target_raw=target_leaf.raw_value,
        alias_exact=str(alias_price.normalized_exact_value),
        target_exact=str(target_price.normalized_exact_value),
        alias_display=alias_display,
        target_display=target_display,
        equal=alias_price.normalized_exact_value == target_price.normalized_exact_value,
    )


def _leaf_state(leaf: PriceLeaf | None) -> str:
    if leaf is None:
        return LEAF_MISSING
    return LEAF_RESOLVED if leaf.resolved else LEAF_UNRESOLVED


def _unavailable_leaf(
    path: str,
    alias_leaf: PriceLeaf | None,
    target_leaf: PriceLeaf | None,
    profile: ProviderProfile,
) -> AliasUnavailableLeaf:
    states = (_leaf_state(alias_leaf), _leaf_state(target_leaf))
    if LEAF_MISSING in states:
        reason = LEAF_MISSING
    elif LEAF_UNRESOLVED in states:
        reason = LEAF_UNRESOLVED
    else:
        reason = LEAF_INCOMPATIBLE
    return AliasUnavailableLeaf(
        path=path,
        label=_label(path, profile),
        reason=reason,
        alias_state=states[0],
        target_state=states[1],
        alias_raw=None if alias_leaf is None else alias_leaf.raw_value,
        target_raw=None if target_leaf is None else target_leaf.raw_value,
        alias_unit_label=None if alias_leaf is None else alias_leaf.unit_label,
        target_unit_label=None if target_leaf is None else target_leaf.unit_label,
        alias_comparison_group=None if alias_leaf is None else alias_leaf.comparison_group,
        target_comparison_group=None if target_leaf is None else target_leaf.comparison_group,
    )


def _unavailable_match(
    compared_paths: tuple[str, ...],
    reason: str | None,
    listing: EndpointListRecord | None = None,
) -> AliasEndpointMatch:
    return AliasEndpointMatch(
        compared_leaves=compared_paths,
        matching_keys=(),
        differing_keys=(),
        unknown_keys=(),
        unavailable_reason=reason,
        list_path=None if listing is None else listing.list_path,
        list_outcome=None if listing is None else listing.outcome,
        list_error_code=None if listing is None else listing.error_code,
    )


def _match_endpoints(
    required: Sequence[PriceLeaf],
    target_id: str,
    list_index: Mapping[str, EndpointListRecord] | None,
    profile: ProviderProfile,
) -> AliasEndpointMatch:
    """Judge each endpoint of the target's list against the alias's leaves."""
    paths = tuple(leaf.path for leaf in required)
    if not required:
        return _unavailable_match(paths, MATCH_NO_COMPARABLE_LEAVES)
    if list_index is None:
        return _unavailable_match(paths, MATCH_NOT_CAPTURED)
    listing = list_index.get(target_id)
    if listing is None:
        return _unavailable_match(paths, MATCH_LIST_MISSING)
    if not listing.succeeded:
        return _unavailable_match(paths, MATCH_LIST_FAILED, listing)
    verdicts: dict[str, list[str]] = {_MATCHING: [], _DIFFERING: [], _UNKNOWN: []}
    for observation in listing.observations:
        verdicts[_candidate_verdict(required, observation.state, profile)].append(
            observation.endpoint_key
        )
    return AliasEndpointMatch(
        compared_leaves=paths,
        matching_keys=tuple(verdicts[_MATCHING]),
        differing_keys=tuple(verdicts[_DIFFERING]),
        unknown_keys=tuple(verdicts[_UNKNOWN]),
        unavailable_reason=None,
        list_path=listing.list_path,
        list_outcome=listing.outcome,
    )


def _candidate_verdict(
    required: Sequence[PriceLeaf],
    state: Mapping[str, Any],
    profile: ProviderProfile,
) -> str:
    """One proven inequality differs; otherwise all leaves equal match, else unknown."""
    leaves = {leaf.path: leaf for leaf in resolved_price_leaves(state, profile)}
    unknown = False
    for wanted in required:
        found = leaves.get(wanted.path)
        if found is None or not found.resolved or _identity(found) != _identity(wanted):
            unknown = True
            continue
        if found.normalized_exact_value != wanted.normalized_exact_value:
            return _DIFFERING
    return _UNKNOWN if unknown else _MATCHING


def _prior_divergence_now(
    prior: AliasDivergence,
    current: AliasEvaluation | None,
    alias_present: bool,
) -> tuple[str | None, tuple[AliasLeafComparison, ...]]:
    """Return (None, current leaves) when a prior divergence is resolved, else
    (reason, prior leaves)."""
    if current is None:
        return (EVENT_NOT_ALIAS if alias_present else EVENT_ALIAS_MISSING), prior.leaves
    if current.unavailable_reason is not None:
        return current.unavailable_reason, prior.leaves
    compared = {leaf.path: leaf for leaf in current.compared_leaves}
    now = tuple(compared.get(leaf.path) for leaf in prior.leaves)
    if any(leaf is None or not leaf.equal for leaf in now):
        return EVENT_LEAVES_UNAVAILABLE, prior.leaves
    return None, tuple(leaf for leaf in now if leaf is not None)


def _endpoint_leaf(
    endpoint: Mapping[str, Any],
    leaf: str,
    profile: ProviderProfile,
) -> PriceLeaf | None:
    """Return the endpoint's collected leaf, an unresolved stand-in for a
    container value, or None when the endpoint has no value there."""
    if not isinstance(endpoint, Mapping):
        return None
    for price in resolved_price_leaves(endpoint, profile):
        if price.path == leaf:
            return None if price.raw_value is None else price
    pricing = endpoint.get("pricing")
    prefix, _, name = leaf.partition(".")
    if prefix == "pricing" and isinstance(pricing, Mapping) and pricing.get(name) is not None:
        # The collector excludes object and array children; they are invalid here.
        return PriceLeaf(path=leaf, raw_value=pricing[name], resolved=False)
    return None


def _unplaced_reason(
    price: PriceLeaf,
    identity: tuple[str, str | None],
    profile: ProviderProfile,
) -> str | None:
    """None for a placeable value, else why it cannot be placed."""
    if not price.resolved:
        # A value at a path without the ladder's identity is incompatible
        # whatever its spelling; at a compatible path it is invalid.
        if _rule_identity(price.path, profile) != identity:
            return UNPLACED_INCOMPATIBLE
        return UNPLACED_INVALID
    if _identity(price) != identity:
        return UNPLACED_INCOMPATIBLE
    exact = _resolved_price(price).normalized_exact_value
    if exact == 0:
        return UNPLACED_ZERO
    if exact < 0:
        return UNPLACED_NEGATIVE
    return None


def _rule_identity(path: str, profile: ProviderProfile) -> tuple[str, str | None] | None:
    """The strict (unit, comparison group) identity of `path`, or None without one."""
    rule = resolve_price_rule(path, profile)
    if rule.match_source == "unmatched":
        return None
    return rule.unit_label, rule.comparison_group


def _resolved_price(leaf: PriceLeaf) -> ResolvedPriceValue:
    if leaf.price is None:
        raise ValueError(f"price leaf {leaf.path!r} is not resolved")
    return leaf.price


def _log10(value: Fraction) -> float:
    """log10 of a positive fraction without forming a float of the value.

    `math.log10` accepts arbitrarily large integers, so the numerator and
    denominator are taken separately and no projection can overflow or
    underflow.
    """
    return math.log10(value.numerator) - math.log10(value.denominator)


def _position(value: Fraction, low: float, span: float, index: int, count: int) -> float:
    if count == 1 or span <= 0:
        return _CENTER
    if index == 0:
        return 0.0
    if index == count - 1:
        return 1.0
    return min(1.0, max(0.0, (_log10(value) - low) / span))
