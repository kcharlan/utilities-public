"""Format-independent endpoint and alias report model for scan reports.

Every scan renderer (text, Markdown, JSON and HTML) projects a provider's
endpoint capture and alias events through this module, so ordering, the
concise list cap, summary clauses, persisting-alias selection, squelched
omission and wording are decided once. Summary clauses always come from the
uncapped data; only the displayed lists are capped.

This module holds no I/O. Endpoint field changes are classified strictly
(`classify_change(..., allow_unmatched_prices=False)`) and price leaves come
from `endpoints.resolved_price_leaves`, never from recursive discovery.
Records may carry `RenderedChange` values for the human renderers; the JSON
helpers return only JSON-safe values (no `Fraction`). Endpoint data and alias
events never enter catalog change counts or Price Movement accounting.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final

from .alias_check import (
    ALIAS_EVENT_CHANGED,
    ALIAS_EVENT_NEW,
    ALIAS_EVENT_PERSISTING,
    ALIAS_EVENT_RESOLVED,
    ALIAS_EVENT_UNAVAILABLE,
    EVENT_ALIAS_MISSING,
    EVENT_LEAVES_UNAVAILABLE,
    EVENT_NOT_ALIAS,
    LADDER_ENDPOINT,
    LEAF_INCOMPATIBLE,
    LEAF_MISSING,
    LEAF_UNRESOLVED,
    MATCH_LIST_FAILED,
    MATCH_LIST_MISSING,
    MATCH_NO_COMPARABLE_LEAVES,
    MATCH_NOT_CAPTURED,
    UNPLACED_INCOMPATIBLE,
    UNPLACED_INVALID,
    UNPLACED_MISSING,
    UNPLACED_NEGATIVE,
    UNPLACED_ZERO,
    price_ladder,
)
from .change_render import (
    RenderedChange,
    classify_change,
    format_price_values,
    format_qualified_label,
    pricing_field_sort_key,
    resolve_field_label,
    resolve_price_rule,
)
from .endpoints import (
    ALIAS_CYCLE,
    ALIAS_TARGET_MISSING,
    COMPARISON_AVAILABLE,
    COMPARISON_MISSING_BASELINE_CAPTURE,
    COMPARISON_NO_SELECTED_BASELINE,
    COMPARISON_UNUSABLE_BASELINE,
    CONCISE_ENDPOINT_LIST_CAP,
    ENDPOINT_ADDED,
    ENDPOINT_ERROR_BUDGET_EXCEEDED,
    ENDPOINT_REMOVED,
    FIELD_CHANGED,
    GAP_AMBIGUOUS_MAPPING,
    GAP_BASELINE_OBSERVATION_FAILED,
    GAP_CURRENT_OBSERVATION_FAILED,
    GAP_NEW_PATH_UNPAIRED,
    GAP_REMOVED_PATH_UNPAIRED,
    MAPPING_INVALID_LINK,
    PRICING_OVERRIDES_FIELD,
    STATUS_CHANGED,
    PriceLeaf,
    resolve_price_leaf,
    resolved_price_leaves,
)
from .models import (
    AliasEndpointMatch,
    AliasEvent,
    AliasLeafComparison,
    AliasUnavailableLeaf,
    EndpointCaptureSummary,
    EndpointChangeRecord,
    EndpointListRecord,
    FieldChange,
    Ladder,
    LadderMarkInput,
    ProviderScanResult,
)
from .provider_profiles import ProviderProfile

# Alias events shown with the catalog result (after the Price Movement card in
# HTML, in the Alias check section of text and Markdown). Persisting events
# belong to the endpoint section; unavailable ones are full-detail evidence.
ALIAS_HEADLINE_KINDS: Final = (ALIAS_EVENT_NEW, ALIAS_EVENT_CHANGED, ALIAS_EVENT_RESOLVED)
_ALIAS_KIND_ORDER: Final = {
    ALIAS_EVENT_NEW: 0,
    ALIAS_EVENT_CHANGED: 1,
    ALIAS_EVENT_RESOLVED: 2,
    ALIAS_EVENT_PERSISTING: 3,
    ALIAS_EVENT_UNAVAILABLE: 4,
}
ALIAS_EVENT_TITLES: Final = {
    ALIAS_EVENT_NEW: "New alias price divergence",
    ALIAS_EVENT_CHANGED: "Alias price divergence changed",
    ALIAS_EVENT_PERSISTING: "Persisting alias price divergence",
    ALIAS_EVENT_RESOLVED: "Alias price divergence resolved",
    ALIAS_EVENT_UNAVAILABLE: "Alias price divergence cannot be checked",
}
_ALIAS_REASON_TEXT: Final = {
    EVENT_ALIAS_MISSING: "the alias is no longer in the catalog",
    EVENT_NOT_ALIAS: "the model no longer declares an alias target",
    EVENT_LEAVES_UNAVAILABLE: "the previously divergent prices are no longer comparable",
    ALIAS_TARGET_MISSING: "its alias target is not in the catalog",
    ALIAS_CYCLE: "its alias chain is a cycle",
    MAPPING_INVALID_LINK: "its alias declaration is malformed",
}
# Matching is also unavailable, with the same code, when the target is unresolved.
_MATCH_REASON_TEXT: Final = {
    MATCH_NO_COMPARABLE_LEAVES: "no price is comparable between the alias and its target",
    MATCH_NOT_CAPTURED: "no endpoint lists were captured in this scan",
    MATCH_LIST_MISSING: "the target has no captured endpoint list",
    MATCH_LIST_FAILED: "the target's endpoint list failed to fetch",
    ALIAS_TARGET_MISSING: _ALIAS_REASON_TEXT[ALIAS_TARGET_MISSING],
    ALIAS_CYCLE: _ALIAS_REASON_TEXT[ALIAS_CYCLE],
    MAPPING_INVALID_LINK: _ALIAS_REASON_TEXT[MAPPING_INVALID_LINK],
}
_GAP_TEXT: Final = {
    GAP_BASELINE_OBSERVATION_FAILED: "the baseline list failed to fetch; not compared",
    GAP_CURRENT_OBSERVATION_FAILED: "the current list failed to fetch; not compared",
    GAP_NEW_PATH_UNPAIRED: "new list with no baseline list; not compared",
    GAP_REMOVED_PATH_UNPAIRED: "list is no longer present; not compared",
    GAP_AMBIGUOUS_MAPPING: "models moved between lists ambiguously; not compared",
}
CONDITIONAL_PRICING_ROW_LABEL: Final = "Conditional pricing changed"
_UP: Final = "up"
_DOWN: Final = "down"
ROW_DIRECTION_MIXED: Final = "mixed"
ROW_DIRECTION_COVERAGE: Final = "coverage"

# Wraps an identifier (model ID, endpoint key, list path) for one format.
Quote = Callable[[str], str]


def plain_identifier(value: str) -> str:
    """The text-format `Quote`: identifiers are printed as they are."""
    return value


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _join_words(words: Sequence[str]) -> str:
    if len(words) <= 2:
        return " and ".join(words)
    return ", ".join(words[:-1]) + f" and {words[-1]}"


def _label(path: str, profile: ProviderProfile) -> str:
    return format_qualified_label(*resolve_field_label(path, profile))


def endpoint_label_profile(profile: ProviderProfile) -> ProviderProfile:
    """The profile to label and classify endpoint-state fields with.

    It is `profile` with `endpoint_field_path_labels` laid over the catalog's
    exact-path labels, so an endpoint's own `context_length` is not called
    `Context length (model)`. Price rules and every other behavior are the
    profile's own. Build it once per report: profiles are not hashable.
    """
    if not profile.endpoint_field_path_labels:
        return profile
    return dataclasses.replace(
        profile,
        field_path_labels={**profile.field_path_labels, **profile.endpoint_field_path_labels},
    )


# ---------------------------------------------------------------------------
# Alias events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AliasEventView:
    """One alias event as every scan format presents it.

    `target_model_id` is the target the leaves compare against (the baseline
    target for an `unavailable` event). `previous_target_model_id` is set
    only when the baseline and current targets differ, so the wording can
    name both. `endpoint_match` is the current evaluation's evidence, or None
    when there is nothing to show at this detail level; `target_list` is the
    captured list it was judged on, when one was found. `unavailable_leaves`
    are the current evaluation's uncompared leaves, kept for full detail only.
    """

    event: AliasEvent
    kind: str
    title: str
    alias_model_id: str
    target_model_id: str | None
    previous_target_model_id: str | None
    leaves: tuple[AliasLeafComparison, ...]
    endpoint_match: AliasEndpointMatch | None
    match_labels: tuple[str, ...]
    target_list: EndpointListRecord | None
    unavailable_leaves: tuple[AliasUnavailableLeaf, ...]


@dataclass(frozen=True)
class ProviderAliasReport:
    """One provider's displayed alias events (headline kinds, plus
    `unavailable` evidence in full detail), ordered by kind then alias ID."""

    provider_id: str
    provider_label: str
    full_detail: bool
    events: tuple[AliasEventView, ...]


def alias_match_labels(
    match: AliasEndpointMatch, compared_leaves: Sequence[AliasLeafComparison]
) -> tuple[str, ...]:
    """The labels of the leaves `match` compared, in its order."""
    by_path = {leaf.path: leaf.label for leaf in compared_leaves}
    return tuple(by_path.get(path, path) for path in match.compared_leaves)


def _alias_event_view(
    event: AliasEvent,
    lists: Sequence[EndpointListRecord],
    *,
    full_detail: bool,
) -> AliasEventView:
    current, baseline = event.current, event.baseline
    if event.kind == ALIAS_EVENT_UNAVAILABLE:
        target = baseline.target_model_id if baseline is not None else None
        previous = None
    else:
        target = current.target_model_id if current is not None else None
        before = baseline.target_model_id if baseline is not None else None
        previous = before if before is not None and target is not None and before != target else None
    match = current.endpoint_match if current is not None and event.kind != ALIAS_EVENT_UNAVAILABLE else None
    if match is not None and not full_detail and match.unavailable_reason == MATCH_NOT_CAPTURED:
        # Without any capture there is nothing to say outside full detail.
        match = None
    labels: tuple[str, ...] = ()
    if match is not None and current is not None:
        labels = alias_match_labels(match, current.compared_leaves)
    target_list = None
    if match is not None and match.list_path is not None:
        target_list = next((item for item in lists if item.list_path == match.list_path), None)
    return AliasEventView(
        event=event,
        kind=event.kind,
        title=ALIAS_EVENT_TITLES[event.kind],
        alias_model_id=event.alias_model_id,
        target_model_id=target,
        previous_target_model_id=previous,
        leaves=event.leaves,
        endpoint_match=match,
        match_labels=labels,
        target_list=target_list,
        unavailable_leaves=(
            current.unavailable_leaves if full_detail and current is not None else ()
        ),
    )


def _sorted_views(views: Iterable[AliasEventView]) -> tuple[AliasEventView, ...]:
    return tuple(sorted(views, key=lambda view: (_ALIAS_KIND_ORDER[view.kind], view.alias_model_id)))


def alias_check_report(result: ProviderScanResult, *, full_detail: bool) -> ProviderAliasReport | None:
    """The alias events shown with the catalog result, or None when there are none."""
    lists = result.endpoint_capture.lists if result.endpoint_capture is not None else ()
    shown = ALIAS_HEADLINE_KINDS + ((ALIAS_EVENT_UNAVAILABLE,) if full_detail else ())
    views = _sorted_views(
        _alias_event_view(event, lists, full_detail=full_detail)
        for event in result.alias_events
        if event.kind in shown
    )
    if not views:
        return None
    return ProviderAliasReport(result.provider_id, result.provider_label, full_detail, views)


def alias_event_heading(view: AliasEventView, quote: Quote = plain_identifier) -> str:
    """`alias -> target`, naming the previous target when it changed (Ruling 8)."""
    target = quote(view.target_model_id) if view.target_model_id is not None else "an unresolved target"
    heading = f"{quote(view.alias_model_id)} → {target}"
    if view.previous_target_model_id is not None:
        heading += f" (target changed from {quote(view.previous_target_model_id)})"
    return heading


def alias_event_reason(view: AliasEventView) -> str | None:
    """Why an `unavailable` event cannot show the prior divergence."""
    reason = view.event.unavailable_reason
    if reason is None:
        return None
    return alias_reason_text(reason)


def alias_reason_text(reason: str) -> str:
    """The words for an alias or alias-event `unavailable_reason` code."""
    return _ALIAS_REASON_TEXT.get(reason, reason)


def alias_leaf_sentence(leaf: AliasLeafComparison, kind: str, *, raw_first: bool) -> str:
    """A labelled alias-versus-target sentence with this leaf's own values and unit.

    Text and Markdown are audit formats and lead with the provider's raw
    value; HTML leads with the normalized figure.
    """
    if kind == ALIAS_EVENT_RESOLVED:
        return f"{leaf.label}: alias now matches target at {_alias_side(leaf, leaf.target_raw, leaf.target_display, raw_first)}"
    sentence = alias_divergence_sentence(leaf, raw_first=raw_first)
    if kind == ALIAS_EVENT_UNAVAILABLE:
        sentence += " at the baseline"
    return sentence


def alias_divergence_sentence(leaf: AliasLeafComparison, *, raw_first: bool) -> str:
    """`Label: alias <value> vs target <value>` for one compared leaf."""
    return (
        f"{leaf.label}: alias {_alias_side(leaf, leaf.alias_raw, leaf.alias_display, raw_first)}"
        f" vs target {_alias_side(leaf, leaf.target_raw, leaf.target_display, raw_first)}"
    )


def _alias_side(leaf: AliasLeafComparison, raw: Any, display: str, raw_first: bool) -> str:
    if raw_first:
        return f"{raw} ({display} {leaf.unit_label})"
    return f"{display} {leaf.unit_label} (raw {raw})"


def alias_match_sentence(view: AliasEventView, quote: Quote = plain_identifier) -> str | None:
    """Endpoint-match evidence as claims about the named comparison leaves.

    It never says that no endpoint matches while any candidate is unknown.
    """
    if view.endpoint_match is None:
        return None
    return endpoint_match_sentence(view.endpoint_match, view.match_labels, quote)


def endpoint_match_sentence(
    match: AliasEndpointMatch, labels: Sequence[str], quote: Quote = plain_identifier
) -> str:
    """`alias_match_sentence` for one evaluation's match and its leaf labels
    (`alias_match_labels`)."""
    if match.unavailable_reason is not None:
        reason = _MATCH_REASON_TEXT.get(match.unavailable_reason, match.unavailable_reason)
        return f"Endpoint matching unavailable: {reason}"
    noun = "price" if len(labels) == 1 else "prices"
    prices = f"the alias's {_join_words(labels)} {noun}"
    parts: list[str] = []
    if match.matching_keys:
        keys = ", ".join(quote(key) for key in match.matching_keys)
        if len(match.matching_keys) == 1:
            parts.append(f"Endpoint {keys} carries {prices}")
        else:
            parts.append(f"Endpoints {keys} carry {prices}")
    elif not match.unknown_keys:
        if match.differing_keys:
            parts.append(f"No endpoint in the target's list carries {prices}")
        else:
            parts.append("The target's endpoint list is empty")
    if match.unknown_keys:
        keys = ", ".join(quote(key) for key in match.unknown_keys)
        verb = "was" if len(match.unknown_keys) == 1 else "were"
        parts.append(
            f"{plural(len(match.unknown_keys), 'endpoint')} {verb} not checkable on every compared price: {keys}"
        )
    return "; ".join(parts)


def alias_unavailable_leaf_sentence(leaf: AliasUnavailableLeaf) -> str:
    """Neutral evidence for a catalog price leaf outside the comparison set."""
    if leaf.reason == LEAF_MISSING:
        sides = [
            name
            for name, state in (("alias", leaf.alias_state), ("target", leaf.target_state))
            if state == LEAF_MISSING
        ]
        detail = f"missing on the {' and '.join(sides)}"
    elif leaf.reason == LEAF_UNRESOLVED:
        sides = [
            name
            for name, state in (("alias", leaf.alias_state), ("target", leaf.target_state))
            if state == LEAF_UNRESOLVED
        ]
        detail = f"no strict price on the {' and '.join(sides)}"
    elif leaf.reason == LEAF_INCOMPATIBLE:
        detail = f"units differ (alias {leaf.alias_unit_label}, target {leaf.target_unit_label})"
    else:
        detail = leaf.reason
    return f"{leaf.label}: not compared ({detail})"


# ---------------------------------------------------------------------------
# Endpoint lists
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EndpointPriceColumn:
    """One resolved price leaf column of a list's endpoint-price table."""

    path: str
    label: str
    unit_label: str
    comparison_group: str | None


@dataclass(frozen=True)
class EndpointPriceCell:
    """One endpoint's value for one price column, with its raw evidence.

    `rendered` is the leaf's strict change when the leaf itself changed. An
    unchanged leaf carries the current value on both sides; a presence row
    carries only the side where the endpoint exists. Displays are normalized
    prices; values in one column that are not a change share one precision.
    """

    path: str
    old_raw: Any
    new_raw: Any
    old_display: str | None
    new_display: str | None
    rendered: RenderedChange | None


@dataclass(frozen=True)
class EndpointPriceRow:
    """One endpoint's row in the endpoint-price table.

    `change_kind` is `field_changed` (a price leaf moved or appeared),
    `endpoint_added` or `endpoint_removed`. `direction` is `up`, `down`,
    `mixed` or `coverage` for a price change, else the presence kind
    (`added`/`removed`). `cells` align with the list's `price_columns`.
    """

    endpoint_key: str
    change_kind: str
    direction: str
    cells: tuple[EndpointPriceCell | None, ...]
    changes: tuple[EndpointChangeRecord, ...]


@dataclass(frozen=True)
class EndpointFieldRow:
    """A conditional, metadata or status change of one endpoint.

    `rendered` is the strict classification (`allow_unmatched_prices=False`)
    of a metadata or status change, for the field-card table; it is None for a
    conditional pricing change, whose evidence is the raw parent JSON.
    """

    endpoint_key: str
    label: str
    change: EndpointChangeRecord
    rendered: RenderedChange | None


@dataclass(frozen=True)
class EndpointListView:
    """One changed endpoint list as displayed at the report's detail level.

    `from_list_path` is the baseline path of a moved list, else None.
    `model_ids` are the catalog models whose `listed` mapping is this path.
    Default detail carries price, presence and conditional rows; full detail
    adds metadata and status rows.
    """

    list_path: str
    from_list_path: str | None
    display_id: str
    model_ids: tuple[str, ...]
    price_columns: tuple[EndpointPriceColumn, ...]
    price_rows: tuple[EndpointPriceRow, ...]
    conditional_rows: tuple[EndpointFieldRow, ...]
    metadata_rows: tuple[EndpointFieldRow, ...]
    status_rows: tuple[EndpointFieldRow, ...]


@dataclass(frozen=True)
class EndpointGapView:
    """A list that could not be compared, with its reason in words."""

    list_path: str
    from_list_path: str | None
    reason: str
    description: str


@dataclass(frozen=True)
class ProviderEndpointReport:
    """One provider's endpoint section, decided once for every format.

    `capture_line`, `baseline_line`, `summary_clauses` and `no_change_line`
    are format-independent wording; clauses are built from the uncapped data
    and zero counts are dropped. `persisting` alias events come first, then
    `lists` in price-presentation order, capped in default detail by
    `CONCISE_ENDPOINT_LIST_CAP` with `omitted_list_count` naming the rest.
    `detail_only_list_count` counts changed lists whose changes appear only
    in full detail. `gaps` and `failed_lists` are full-detail evidence.
    """

    provider_id: str
    provider_label: str
    full_detail: bool
    capture: EndpointCaptureSummary | None
    capture_line: str
    persistence_error: str | None
    baseline_line: str | None
    summary_clauses: tuple[str, ...]
    no_change_line: str | None
    persisting: tuple[AliasEventView, ...]
    lists: tuple[EndpointListView, ...]
    omitted_list_count: int
    detail_only_list_count: int
    gaps: tuple[EndpointGapView, ...]
    failed_lists: tuple[EndpointListRecord, ...]


@dataclass(frozen=True)
class _ListAnalysis:
    view: EndpointListView
    # (comparison identity, sort key of the leaf, absolute exact movement) for
    # every two-sided resolved price movement in the list.
    movements: tuple[tuple[tuple[str, str | None], Any, Fraction], ...]
    has_price_change: bool


def _direct_price_path(field_name: str | None) -> bool:
    """A direct scalar `pricing` child other than the conditional policy."""
    if field_name is None or not field_name.startswith("pricing."):
        return False
    name = field_name[len("pricing.") :]
    return bool(name) and "." not in name and "[" not in name and field_name != PRICING_OVERRIDES_FIELD


def _strict_change(field_name: str, old: Any, new: Any, profile: ProviderProfile) -> RenderedChange:
    return classify_change(FieldChange(field_name, old, new), profile=profile, allow_unmatched_prices=False)


def endpoint_change_rendering(change: EndpointChangeRecord, profile: ProviderProfile) -> RenderedChange | None:
    """The strict classification of one endpoint change, as every view shows it.

    A status change is classified under the profile's status field and any
    other field change under its own path, with
    `allow_unmatched_prices=False`. Presence changes and conditional pricing
    changes (the neutral `Conditional pricing changed` row, whose evidence is
    the raw parent JSON) have none.
    """
    if change.change_kind in (ENDPOINT_ADDED, ENDPOINT_REMOVED):
        return None
    if change.change_kind == STATUS_CHANGED:
        return _strict_change(profile.endpoint_status_field or "status", change.old_value, change.new_value, profile)
    if change.field_name == PRICING_OVERRIDES_FIELD:
        return None
    return _strict_change(change.field_name or "", change.old_value, change.new_value, profile)


def endpoint_change_label(change: EndpointChangeRecord, rendered: RenderedChange | None) -> str | None:
    """The row label of a change given its `endpoint_change_rendering`; None for presence changes."""
    if change.change_kind == FIELD_CHANGED and change.field_name == PRICING_OVERRIDES_FIELD:
        return CONDITIONAL_PRICING_ROW_LABEL
    return rendered.display_label if rendered is not None else None


def _strict_leaf(path: str, raw: Any, profile: ProviderProfile) -> PriceLeaf | None:
    if raw is None:
        return None
    leaf = resolve_price_leaf(path, raw, profile)
    return leaf if leaf.resolved else None


def _state_leaves(state: Any, profile: ProviderProfile) -> dict[str, PriceLeaf]:
    if not isinstance(state, Mapping):
        return {}
    return {leaf.path: leaf for leaf in resolved_price_leaves(state, profile) if leaf.resolved}


def _row_direction(rendered: Sequence[RenderedChange]) -> str:
    moves = {change.direction for change in rendered} & {_UP, _DOWN}
    if moves == {_UP}:
        return _UP
    if moves == {_DOWN}:
        return _DOWN
    if moves:
        return ROW_DIRECTION_MIXED
    return ROW_DIRECTION_COVERAGE


def _analyse_list(
    changes: Sequence[EndpointChangeRecord],
    listing: EndpointListRecord | None,
    profile: ProviderProfile,
    *,
    full_detail: bool,
) -> _ListAnalysis:
    first = changes[0]
    current_states = {
        observation.endpoint_key: observation.state
        for observation in (listing.observations if listing is not None else ())
    }
    priced: dict[str, list[tuple[EndpointChangeRecord, RenderedChange]]] = {}
    presence: list[EndpointChangeRecord] = []
    conditional: list[EndpointFieldRow] = []
    metadata: list[EndpointFieldRow] = []
    status: list[EndpointFieldRow] = []
    movements: list[tuple[tuple[str, str | None], Any, Fraction]] = []
    row_order: list[tuple[str, str]] = []
    for change in changes:
        key = change.endpoint_key
        rendered = endpoint_change_rendering(change, profile)
        if change.change_kind in (ENDPOINT_ADDED, ENDPOINT_REMOVED):
            presence.append(change)
            row_order.append((change.change_kind, key))
        elif rendered is None:
            conditional.append(EndpointFieldRow(key, CONDITIONAL_PRICING_ROW_LABEL, change, None))
        elif change.change_kind == STATUS_CHANGED:
            status.append(EndpointFieldRow(key, rendered.display_label, change, rendered))
        else:
            field_name = change.field_name or ""
            if _direct_price_path(change.field_name) and rendered.kind == "price":
                if key not in priced:
                    row_order.append((FIELD_CHANGED, key))
                priced.setdefault(key, []).append((change, rendered))
                old_leaf = _strict_leaf(field_name, change.old_value, profile)
                new_leaf = _strict_leaf(field_name, change.new_value, profile)
                if (
                    old_leaf is not None
                    and new_leaf is not None
                    and rendered.direction in (_UP, _DOWN)
                    and rendered.price_rule is not None
                ):
                    movements.append(
                        (
                            (rendered.price_rule.unit_label, rendered.price_rule.comparison_group),
                            pricing_field_sort_key(field_name, profile),
                            abs(new_leaf.normalized_exact_value - old_leaf.normalized_exact_value),
                        )
                    )
            else:
                metadata.append(EndpointFieldRow(key, rendered.display_label, change, rendered))

    presence_states = {
        (change.change_kind, change.endpoint_key): (
            change.new_value if change.change_kind == ENDPOINT_ADDED else change.old_value
        )
        for change in presence
    }
    column_paths: set[str] = {
        rendered.field_path for entries in priced.values() for _, rendered in entries
    }
    for state in presence_states.values():
        column_paths.update(_state_leaves(state, profile))
    columns = tuple(
        EndpointPriceColumn(
            path=path,
            label=_label(path, profile),
            unit_label=rule.unit_label,
            comparison_group=rule.comparison_group,
        )
        for path in sorted(column_paths, key=lambda path: pricing_field_sort_key(path, profile))
        for rule in (resolve_price_rule(path, profile),)
        if rule.match_source != "unmatched"
    )

    # Values that are not themselves a change share one precision per column.
    pending: dict[str, list[tuple[tuple[int, int], str, PriceLeaf]]] = {}
    raw_rows: list[tuple[str, str, list[Any], tuple[EndpointChangeRecord, ...], str]] = []
    for row_index, (kind, key) in enumerate(row_order):
        cells: list[Any] = []
        if kind == FIELD_CHANGED:
            entries = priced[key]
            changed = {rendered.field_path: (change, rendered) for change, rendered in entries}
            current = _state_leaves(current_states.get(key), profile)
            for column_index, column in enumerate(columns):
                if column.path in changed:
                    change, rendered = changed[column.path]
                    cells.append(
                        EndpointPriceCell(
                            path=column.path,
                            old_raw=change.old_value,
                            new_raw=change.new_value,
                            old_display=None if change.old_value is None else rendered.old_display,
                            new_display=None if change.new_value is None else rendered.new_display,
                            rendered=rendered,
                        )
                    )
                elif column.path in current:
                    cells.append(None)
                    pending.setdefault(column.path, []).append(
                        ((row_index, column_index), "both", current[column.path])
                    )
                else:
                    cells.append(None)
            direction = _row_direction([rendered for _, rendered in entries])
            sources = tuple(change for change, _ in entries)
        else:
            leaves = _state_leaves(presence_states[(kind, key)], profile)
            side = "new" if kind == ENDPOINT_ADDED else "old"
            for column_index, column in enumerate(columns):
                cells.append(None)
                if column.path in leaves:
                    pending.setdefault(column.path, []).append(
                        ((row_index, column_index), side, leaves[column.path])
                    )
            direction = "added" if kind == ENDPOINT_ADDED else "removed"
            sources = tuple(change for change in presence if (change.change_kind, change.endpoint_key) == (kind, key))
        raw_rows.append((key, kind, cells, sources, direction))

    for path, entries in pending.items():
        # `_state_leaves` keeps only resolved leaves, which always carry a price.
        displays = format_price_values([leaf.price for _, _, leaf in entries], precision_basis=())
        for ((row_index, column_index), side, leaf), display in zip(entries, displays):
            raw_rows[row_index][2][column_index] = EndpointPriceCell(
                path=path,
                old_raw=leaf.raw_value if side in ("both", "old") else None,
                new_raw=leaf.raw_value if side in ("both", "new") else None,
                old_display=display if side in ("both", "old") else None,
                new_display=display if side in ("both", "new") else None,
                rendered=None,
            )

    price_rows = tuple(
        EndpointPriceRow(key, kind, direction, tuple(cells), sources)
        for key, kind, cells, sources, direction in raw_rows
    )
    view = EndpointListView(
        list_path=first.list_path,
        from_list_path=first.from_list_path if first.from_list_path != first.list_path else None,
        display_id=listing.display_id if listing is not None else first.display_id,
        model_ids=listing.model_ids if listing is not None else first.model_ids,
        price_columns=columns,
        price_rows=price_rows,
        conditional_rows=tuple(conditional),
        metadata_rows=tuple(metadata) if full_detail else (),
        status_rows=tuple(status) if full_detail else (),
    )
    return _ListAnalysis(view=view, movements=tuple(movements), has_price_change=bool(priced))


def _has_default_content(view: EndpointListView) -> bool:
    return bool(view.price_rows or view.conditional_rows)


def _order_endpoint_lists(analyses: Sequence[_ListAnalysis]) -> tuple[_ListAnalysis, ...]:
    """Price-presentation order for changed lists.

    Each list belongs to the comparison group of its first two-sided resolved
    price movement in `pricing_field_sort_key` order. Groups are ordered by
    that leaf's profile presentation order, then group identity; lists within
    a group by their largest absolute movement in that group, ties by path.
    Lists without a comparable price movement follow in path order. Dollar
    magnitudes are never ranked across groups, and each list appears once.
    """
    grouped: dict[tuple[str, str | None], list[tuple[Fraction, str, _ListAnalysis]]] = {}
    group_rank: dict[tuple[str, str | None], Any] = {}
    rest: list[_ListAnalysis] = []
    for analysis in analyses:
        if not analysis.movements:
            rest.append(analysis)
            continue
        identity, sort_key, _ = min(analysis.movements, key=lambda movement: movement[1])
        largest = max(amount for group, _, amount in analysis.movements if group == identity)
        grouped.setdefault(identity, []).append((largest, analysis.view.list_path, analysis))
        group_rank[identity] = min(group_rank.get(identity, sort_key), sort_key)
    ordered: list[_ListAnalysis] = []
    for identity in sorted(grouped, key=lambda group: (group_rank[group], group[1] or "", group[0])):
        ordered.extend(
            analysis
            for _, _, analysis in sorted(grouped[identity], key=lambda item: (-item[0], item[1]))
        )
    ordered.extend(sorted(rest, key=lambda analysis: analysis.view.list_path))
    return tuple(ordered)


def _compared_paths(capture: EndpointCaptureSummary) -> set[str]:
    """Current lists actually compared: successful, with no comparison gap."""
    if capture.comparison_state != COMPARISON_AVAILABLE:
        return set()
    gap_paths = {gap.list_path for gap in capture.comparison_gaps}
    return {listing.list_path for listing in capture.lists if listing.succeeded} - gap_paths


def _failed_and_unsent(capture: EndpointCaptureSummary) -> tuple[int, int]:
    """(lists that failed to fetch, lists never sent) for one capture.

    `paths_failed` also counts `budget_exceeded` paths, which were never sent
    after the admission deadline; they are not described as fetch failures.
    """
    unsent = sum(
        1
        for listing in capture.lists
        if not listing.succeeded and listing.error_code == ENDPOINT_ERROR_BUDGET_EXCEEDED
    )
    return max(capture.paths_failed - unsent, 0), unsent


def capture_status_line(capture: EndpointCaptureSummary | None) -> str:
    """The capture's status first, then its counts and any error."""
    if capture is None:
        return "not run in this scan"
    line = capture.status
    if capture.capture_id is not None:
        line += f" (capture {capture.capture_id})"
    failed, unsent = _failed_and_unsent(capture)
    line += (
        f": {plural(capture.paths_requested, 'list')} requested,"
        f" {capture.paths_attempted} attempted, {failed} failed"
    )
    if unsent:
        line += f", {unsent} not sent before the fetch budget ran out"
    line += f", {plural(capture.mapping_failures, 'mapping failure')}"
    if capture.error_summary:
        line += f"; error: {capture.error_summary}"
    return line


def baseline_comparison_line(capture: EndpointCaptureSummary | None) -> str | None:
    """The genuine first-capture message, or what the selected baseline allowed."""
    if capture is None:
        return None
    if capture.first_capture:
        return _FIRST_CAPTURE_LINE
    state = capture.comparison_state
    if state == COMPARISON_AVAILABLE:
        if _compared_paths(capture):
            return f"compared with endpoint capture {capture.baseline_capture_id}"
        return f"no current list could be compared with endpoint capture {capture.baseline_capture_id}"
    return _baseline_unavailable_line(state, capture.baseline_capture_id)


def list_comparison_line(
    *,
    first_capture: bool,
    comparison_state: str,
    baseline_capture_id: int | None,
    list_succeeded: bool | None,
    gap_reasons: Sequence[str],
) -> str:
    """Whether one model's list was compared with the selected baseline's
    capture, or why not, on the same terms as `_compared_paths`.

    `list_succeeded` is None when the capture saved no list for the model.
    """
    if first_capture:
        return _FIRST_CAPTURE_LINE
    if comparison_state != COMPARISON_AVAILABLE:
        return _baseline_unavailable_line(comparison_state, baseline_capture_id)
    if list_succeeded is None:
        return f"no endpoint list was saved for this model, so nothing was compared with endpoint capture {baseline_capture_id}"
    if not list_succeeded:
        return f"this list failed to fetch, so it was not compared with endpoint capture {baseline_capture_id}"
    if gap_reasons:
        return f"this list has a comparison gap, so it was not compared with endpoint capture {baseline_capture_id}"
    return f"compared with endpoint capture {baseline_capture_id}"


_FIRST_CAPTURE_LINE: Final = "first endpoint capture for this provider; there is no earlier capture to compare with"


def _baseline_unavailable_line(state: str, baseline_capture_id: int | None) -> str:
    """Why no list was compared when the selected baseline allowed no comparison."""
    if state == COMPARISON_NO_SELECTED_BASELINE:
        return "no catalog baseline was selected, so endpoint lists were not compared"
    if state == COMPARISON_MISSING_BASELINE_CAPTURE:
        return "the selected catalog baseline has no endpoint capture, so endpoint lists were not compared"
    if state == COMPARISON_UNUSABLE_BASELINE:
        return (
            f"the selected baseline's endpoint capture {baseline_capture_id} has no usable lists,"
            " so endpoint lists were not compared"
        )
    return f"endpoint lists were not compared ({state})"


def endpoint_gap_description(reason: str) -> str:
    return _GAP_TEXT.get(reason, reason)


_UNPLACED_TEXT: Final = {
    UNPLACED_MISSING: "no {label} price",
    UNPLACED_INVALID: "not a valid price",
    UNPLACED_INCOMPATIBLE: "a different unit",
}


def ladder_position_text(entries: Iterable) -> str:
    """`endpoints a#0 and b#0; alias price` for one ladder position."""
    entries = tuple(entries)
    keys = [entry.label for entry in entries if entry.kind == LADDER_ENDPOINT]
    parts = []
    if keys:
        parts.append(f"{'endpoint' if len(keys) == 1 else 'endpoints'} {_join_words(keys)}")
    parts.extend(f"{entry.label} price" for entry in entries if entry.kind != LADDER_ENDPOINT)
    return "; ".join(parts)


def ladder_unplaced_text(ladder: Ladder) -> str:
    """The ladder's unplaced values with why, e.g. `alias price (no Input price)`."""
    items = []
    for item in ladder.unplaced:
        if item.reason in (UNPLACED_ZERO, UNPLACED_NEGATIVE) and item.display:
            detail = item.display
        else:
            detail = _UNPLACED_TEXT.get(item.reason, item.reason).format(label=ladder.label)
        name = item.label if item.kind == LADDER_ENDPOINT else f"{item.label} price"
        items.append(f"{name} ({detail})")
    return ", ".join(items)


def omitted_lists_phrase(count: int) -> str:
    return f"{plural(count, 'more changed list')} not shown"


def detail_only_lists_phrase(count: int) -> str:
    verb = "has" if count == 1 else "have"
    return f"{plural(count, 'changed list')} {verb} only metadata or status changes"


def endpoint_list_heading(view: EndpointListView, quote: Quote = plain_identifier) -> str:
    heading = quote(view.display_id)
    if view.from_list_path is not None:
        heading += f" (moved from {quote(view.from_list_path)})"
    if view.model_ids:
        heading += " — models: " + ", ".join(quote(model_id) for model_id in view.model_ids)
    return heading


def endpoint_report(
    result: ProviderScanResult,
    *,
    full_detail: bool,
    list_cap: int = CONCISE_ENDPOINT_LIST_CAP,
) -> ProviderEndpointReport | None:
    """One provider's endpoint section, or None without a capture or a
    persisting alias divergence."""
    capture = result.endpoint_capture
    lists = capture.lists if capture is not None else ()
    persisting = _sorted_views(
        _alias_event_view(event, lists, full_detail=full_detail)
        for event in result.alias_events
        if event.kind == ALIAS_EVENT_PERSISTING
    )
    if capture is None and not persisting:
        return None
    profile = endpoint_label_profile(result.profile)
    by_path: dict[str, list[EndpointChangeRecord]] = {}
    for change in capture.changes if capture is not None else ():
        by_path.setdefault(change.list_path, []).append(change)
    listings = {listing.list_path: listing for listing in lists}
    analyses = _order_endpoint_lists(
        [
            _analyse_list(changes, listings.get(path), profile, full_detail=full_detail)
            for path, changes in by_path.items()
        ]
    )
    if full_detail:
        shown = [analysis.view for analysis in analyses]
        omitted = detail_only = 0
    else:
        eligible = [analysis.view for analysis in analyses if _has_default_content(analysis.view)]
        shown = eligible[:list_cap]
        omitted = len(eligible) - len(shown)
        detail_only = len(analyses) - len(eligible)

    summary_clauses: tuple[str, ...] = ()
    no_change_line = None
    gaps: tuple[EndpointGapView, ...] = ()
    failed: tuple[EndpointListRecord, ...] = ()
    if capture is not None:
        all_changes = capture.changes
        failed_count, unsent = _failed_and_unsent(capture)
        counts = (
            (sum(1 for analysis in analyses if analysis.has_price_change), "list", " with price changes"),
            (sum(1 for c in all_changes if c.change_kind == ENDPOINT_ADDED), "endpoint", " added"),
            (sum(1 for c in all_changes if c.change_kind == ENDPOINT_REMOVED), "endpoint", " removed"),
            (
                sum(1 for c in all_changes if c.change_kind == FIELD_CHANGED and c.field_name == PRICING_OVERRIDES_FIELD),
                "conditional pricing change",
                "",
            ),
            (sum(1 for c in all_changes if c.change_kind == STATUS_CHANGED), "status change", ""),
            (len(persisting), "persisting alias divergence", ""),
            (failed_count, "list", " failed to fetch"),
            (unsent, "list", " not requested before the endpoint fetch budget ran out"),
            (capture.mapping_failures, "mapping failure", ""),
            (len(capture.comparison_gaps), "comparison gap", ""),
        )
        summary_clauses = tuple(plural(count, noun) + suffix for count, noun, suffix in counts if count)
        compared = _compared_paths(capture)
        unchanged = len(compared - by_path.keys())
        if compared and not all_changes:
            no_change_line = f"no endpoint changes in {plural(len(compared), 'compared list')}"
        elif compared and unchanged:
            no_change_line = f"no endpoint changes in the other {plural(unchanged, 'compared list')}"
        if full_detail:
            gaps = tuple(
                EndpointGapView(gap.list_path, gap.from_list_path, gap.reason, endpoint_gap_description(gap.reason))
                for gap in capture.comparison_gaps
            )
            failed = tuple(listing for listing in lists if not listing.succeeded)
    elif persisting:
        summary_clauses = (plural(len(persisting), "persisting alias divergence"),)

    return ProviderEndpointReport(
        provider_id=result.provider_id,
        provider_label=result.provider_label,
        full_detail=full_detail,
        capture=capture,
        capture_line=capture_status_line(capture),
        persistence_error=capture.persistence_error if capture is not None else None,
        baseline_line=baseline_comparison_line(capture),
        summary_clauses=summary_clauses,
        no_change_line=no_change_line,
        persisting=persisting,
        lists=tuple(shown),
        omitted_list_count=omitted,
        detail_only_list_count=detail_only,
        gaps=gaps,
        failed_lists=failed,
    )


# ---------------------------------------------------------------------------
# One captured list as it stands, and alias price ladders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EndpointPriceValue:
    """One endpoint's strictly resolved price for one column, with its raw value."""

    path: str
    raw_value: Any
    display: str
    unit_label: str
    comparison_group: str | None


@dataclass(frozen=True)
class EndpointTableRow:
    """One endpoint of a captured list, in response order.

    `tag`, `name` and `provider_name` are the endpoint's own strings (None
    when absent or not a string); `status` is its stored status code.
    `prices` align with the table's columns; None where the endpoint has no
    resolved price for that column.
    """

    endpoint_key: str
    tag: str | None
    name: str | None
    provider_name: str | None
    status: int | None
    prices: tuple[EndpointPriceValue | None, ...]


@dataclass(frozen=True)
class EndpointPriceTable:
    """A captured list's endpoints and their resolved price columns.

    Columns are every resolved direct `pricing` leaf of any endpoint, in
    `pricing_field_sort_key` order; unresolved leaves are left out. The
    values in one column share one precision. Every value is JSON-safe.
    """

    columns: tuple[EndpointPriceColumn, ...]
    rows: tuple[EndpointTableRow, ...]


def _optional_string(state: Mapping[str, Any], name: str) -> str | None:
    value = state.get(name)
    return value if isinstance(value, str) else None


def endpoint_price_table(listing: EndpointListRecord, profile: ProviderProfile) -> EndpointPriceTable:
    """The endpoint-price table of one captured list (empty for a failed or empty list)."""
    leaves = [_state_leaves(observation.state, profile) for observation in listing.observations]
    paths = sorted({path for row in leaves for path in row}, key=lambda path: pricing_field_sort_key(path, profile))
    columns = tuple(
        EndpointPriceColumn(
            path=path,
            label=_label(path, profile),
            unit_label=rule.unit_label,
            comparison_group=rule.comparison_group,
        )
        for path in paths
        for rule in (resolve_price_rule(path, profile),)
    )
    cells: list[list[EndpointPriceValue | None]] = [[None] * len(columns) for _ in leaves]
    for column_index, column in enumerate(columns):
        present = [(row_index, row[column.path]) for row_index, row in enumerate(leaves) if column.path in row]
        # `_state_leaves` keeps only resolved leaves, which always carry a price.
        displays = format_price_values([leaf.price for _, leaf in present], precision_basis=())
        for (row_index, leaf), display in zip(present, displays):
            cells[row_index][column_index] = EndpointPriceValue(
                path=column.path,
                raw_value=leaf.raw_value,
                display=display,
                unit_label=leaf.unit_label or column.unit_label,
                comparison_group=leaf.comparison_group,
            )
    rows = tuple(
        EndpointTableRow(
            endpoint_key=observation.endpoint_key,
            tag=_optional_string(observation.state, "tag"),
            name=_optional_string(observation.state, "name"),
            provider_name=_optional_string(observation.state, "provider_name"),
            status=observation.status_code,
            prices=tuple(row_cells),
        )
        for observation, row_cells in zip(listing.observations, cells)
    )
    return EndpointPriceTable(columns=columns, rows=rows)


def alias_ladders(
    leaves: Sequence[AliasLeafComparison],
    listing: EndpointListRecord | None,
    profile: ProviderProfile,
) -> tuple[Ladder, ...]:
    """A ladder per divergent leaf, when the target's list has endpoints.

    Each ladder places the list's endpoints with the target and alias
    catalog prices as marks. A ladder on which no endpoint could be placed
    would only restate the two catalog prices, so it is left out.
    """
    if listing is None or not listing.succeeded or not listing.observations:
        return ()
    endpoints = [(observation.endpoint_key, observation.state) for observation in listing.observations]
    ladders = []
    for leaf in leaves:
        ladder = price_ladder(
            endpoints,
            leaf=leaf.path,
            marks=(
                LadderMarkInput("target", leaf.path, leaf.target_raw),
                LadderMarkInput("alias", leaf.path, leaf.alias_raw),
            ),
            profile=profile,
        )
        if ladder is not None and any(
            entry.kind == LADDER_ENDPOINT for position in ladder.positions for entry in position.entries
        ):
            ladders.append(ladder)
    return tuple(ladders)


@dataclass(frozen=True)
class ScanEndpointSections:
    """The alias and endpoint sections of one scan report, per provider."""

    alias_reports: tuple[ProviderAliasReport, ...]
    endpoint_reports: tuple[ProviderEndpointReport, ...]


def scan_endpoint_sections(
    provider_results: Iterable[ProviderScanResult],
    *,
    detail_mode: str,
) -> ScanEndpointSections:
    """Both sections for a human scan report; empty in `squelched` mode."""
    if detail_mode == "squelched":
        return ScanEndpointSections((), ())
    full_detail = detail_mode == "all"
    results = tuple(provider_results)
    alias_reports = tuple(
        report
        for report in (alias_check_report(result, full_detail=full_detail) for result in results)
        if report is not None
    )
    endpoint_reports = tuple(
        report
        for report in (endpoint_report(result, full_detail=full_detail) for result in results)
        if report is not None
    )
    return ScanEndpointSections(alias_reports, endpoint_reports)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def _price_evidence_entry(
    path: str,
    old_leaf: PriceLeaf | None,
    new_leaf: PriceLeaf | None,
    profile: ProviderProfile,
) -> dict[str, Any] | None:
    present = [leaf for leaf in (old_leaf, new_leaf) if leaf is not None and leaf.price is not None]
    if not present:
        return None
    # The sides of one change are displayed together, so they share a precision.
    displays = iter(format_price_values([leaf.price for leaf in present], precision_basis=()))
    old_display = next(displays) if old_leaf is not None and old_leaf.price is not None else None
    new_display = next(displays) if new_leaf is not None and new_leaf.price is not None else None
    return {
        "path": path,
        "label": _label(path, profile),
        "unit_label": present[0].unit_label,
        "comparison_group": present[0].comparison_group,
        "old_display": old_display,
        "new_display": new_display,
    }


def change_price_evidence(change: EndpointChangeRecord, profile: ProviderProfile) -> list[dict[str, Any]]:
    """Normalized display/unit metadata for a change's strictly resolved prices."""
    entries: list[dict[str, Any] | None] = []
    if change.change_kind == FIELD_CHANGED and _direct_price_path(change.field_name):
        path = change.field_name or ""
        entries.append(
            _price_evidence_entry(
                path,
                _strict_leaf(path, change.old_value, profile),
                _strict_leaf(path, change.new_value, profile),
                profile,
            )
        )
    elif change.change_kind in (ENDPOINT_ADDED, ENDPOINT_REMOVED):
        added = change.change_kind == ENDPOINT_ADDED
        leaves = _state_leaves(change.new_value if added else change.old_value, profile)
        for path in sorted(leaves, key=lambda path: pricing_field_sort_key(path, profile)):
            leaf = leaves[path]
            entries.append(
                _price_evidence_entry(path, None if added else leaf, leaf if added else None, profile)
            )
    return [entry for entry in entries if entry is not None]


def endpoint_capture_json(capture: EndpointCaptureSummary, profile: ProviderProfile) -> dict[str, Any]:
    """The summary's fields except `lists`, with uncapped changes and gaps.

    Each change keeps its decoded raw values and gains `price_evidence`: the
    normalized display, unit and comparison group of its strictly resolved
    price leaves. Every value is JSON-safe.
    """
    payload = {
        field.name: getattr(capture, field.name)
        for field in dataclasses.fields(capture)
        if field.name not in ("lists", "changes", "comparison_gaps")
    }
    payload["changes"] = [
        {**dataclasses.asdict(change), "price_evidence": change_price_evidence(change, profile)}
        for change in capture.changes
    ]
    payload["comparison_gaps"] = [dataclasses.asdict(gap) for gap in capture.comparison_gaps]
    return payload


def alias_check_json(events: Sequence[AliasEvent]) -> dict[str, Any]:
    """Every alias event, uncapped and at full fidelity (records are JSON-safe)."""
    return {"events": [dataclasses.asdict(event) for event in events]}
