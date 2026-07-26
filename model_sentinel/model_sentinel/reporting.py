from __future__ import annotations

import fnmatch
import html as html_module
import json
import re
from collections import OrderedDict, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

# Renderers in this module are pure formatters over `RenderedChange`: they call
# `classify_change` once per field change and format the result, instead of
# re-deriving price/count/numeric/list classification per output format.
#
# FIELD NAMES: every renderer here prints `RenderedChange.display_label`, NEVER
# `RenderedChange.label`. `label` is the field-label registry's lookup result
# with any bracketed segment already stripped, so it does not identify a row on
# its own: `pricing.prompt` and
# `pricing.overrides[min_prompt_tokens=200000].prompt` both resolve to `Input`.
# `display_label` re-attaches the stripped segment as a parenthetical, in one
# place, for all six renderers. JSON does not go through any of this --
# `_delta_to_json` serialises `FieldChange` and its raw dotted paths directly.
#
# `tests/test_reporting.py::test_every_field_change_entry_point_surfaces_the_qualifier`
# pins it, from the output rather than from this source text: it feeds one
# fixture whose base rate and conditional tier share a leaf through every
# public `render_*_report` that carries field changes, and requires the two
# rows to stay distinguishable in every human format. A companion test
# discovers the `render_*_report` inventory from this module, so a seventh
# renderer cannot be added without being triaged.
#
# `_numeric_value` is still called directly here by price-movement helpers.
# Provider-specific category and monetary-field decisions come from the
# profile carried by the enclosing scan/report context.
# `_list_diff_members` is imported for `_list_change_signature`, the bulk
# grouping key, which must share one member-stringification and one set
# difference with `classify_change`'s list branch without inheriting the
# cascade's noop-before-list ordering -- see both docstrings. The
# six other primitives that moved (`_both_numeric`, `_fmt_int`,
# `_fmt_price_per_m`, `_is_count_field`, `_normalize_price`, `_pct_change`)
# had no remaining call site here once the renderers were rewired, so their
# transitional re-export shims were dropped; import those from
# `model_sentinel.change_render` directly.
from .change_render import (
    ABSENT_DISPLAY,
    ABSENT_TEXT_DISPLAY,
    RenderedChange,
    _list_diff_members,
    _numeric_value,
    _scalar_display,
    classify_change,
    signed_pct_change,
)
from .models import FieldChange, HistoryEvent, ModelDelta, ProviderScanResult
from .provider_profiles import (
    GENERIC_PROFILE,
    ProviderProfile,
)
from .time_utils import to_local_human, to_local_iso

REPORT_DETAIL_MODES = ("default", "all", "squelched")
BULK_CHANGE_MIN_MODELS = 3

DEFAULT_REPORT_SHOW_FIELDS = (
    "pricing.*",
    "context_length",
    "top_provider.context_length",
    "top_provider.max_completion_tokens",
    "supported_parameters",
    "default_parameters",
    "default_parameters.*",
    "architecture.*",
    "reasoning",
    "reasoning.*",
    "expiration_date",
    "status",
    "deprecated",
    "knowledge_cutoff",
    "top_provider.is_moderated",
)

DEFAULT_REPORT_SQUELCH_FIELDS = (
    "benchmarks",
    "benchmarks.*",
)


@dataclass(frozen=True)
class ReportDetailPolicy:
    mode: str
    show_fields: tuple[str, ...]
    squelch_fields: tuple[str, ...]
    unclassified_limit: int


@dataclass(frozen=True)
class FilteredFieldChanges:
    shown: tuple[FieldChange, ...]
    squelched: tuple[FieldChange, ...]
    unclassified: tuple[FieldChange, ...]


@dataclass(frozen=True)
class _FieldDisplayPlan:
    visible: tuple[FieldChange, ...]
    squelched: tuple[FieldChange, ...]
    hidden_unclassified: tuple[FieldChange, ...]
    hidden_non_squelched: tuple[FieldChange, ...]
    unclassified_used: int
    # No-op field changes dropped by `_drop_noop_changes` (E1). Carried so the
    # provider-level rollup can account for them; deliberately NOT part of
    # `_has_hidden_details`, because a model whose every change is a no-op has
    # nothing to say and must not keep a card alive.
    noop: tuple[FieldChange, ...] = ()


@dataclass(frozen=True)
class _PlannedModelChange:
    delta: ModelDelta
    display: _FieldDisplayPlan


@dataclass(frozen=True)
class _BulkChangeGroup:
    members: tuple[_PlannedModelChange, ...]

    @property
    def visible(self) -> tuple[FieldChange, ...]:
        return self.members[0].display.visible

    @property
    def model_ids(self) -> tuple[str, ...]:
        return tuple(member.delta.provider_model_id for member in self.members)

    @property
    def label(self) -> str:
        """The one spelling of a bulk group's headline.

        Text, markdown, HTML and the Change Summary all name a bulk group the
        same way, differing only in the markup wrapped around it. Spelling it
        four times meant four places to keep the em dash, the wording and the
        count in step.
        """
        return f"Bulk change — {len(self.members)} models"


@dataclass(frozen=True)
class _HiddenRollups:
    """Provider-level accounting for everything a report chose not to render.

    One container for all three suppression reasons so every renderer emits the
    same set of rollups in the same order, instead of each rebuilding its own
    `hidden_squelched`/`hidden_non_squelched` lists inline.
    """

    squelched: list[tuple[str, tuple[FieldChange, ...]]]
    non_squelched: list[tuple[str, tuple[FieldChange, ...]]]
    noop: list[tuple[str, tuple[FieldChange, ...]]]

    @property
    def any_hidden(self) -> bool:
        return bool(self.squelched or self.non_squelched or self.noop)


@dataclass(frozen=True)
class _ProviderChangePlan:
    planned: tuple[_PlannedModelChange, ...]
    items: tuple[_PlannedModelChange | _BulkChangeGroup, ...]
    rollups: _HiddenRollups


@dataclass(frozen=True)
class _SummaryEntry:
    category: str
    provider: str
    model_id: str
    field: str
    detail: str
    grouped_model_ids: tuple[str, ...] = ()
    # N1: the card id this row's Model cell links to, or `""` for none. Empty
    # for every row of the `changes` report (which has no model cards at all),
    # for a grouped/presence/squelched row (which names no single card), and --
    # the load-bearing case -- for a scan-report row whose model card is in
    # TIER 2, because a fragment pointing inside a closed `<details>` is not
    # reliably navigable. Defaulted so the `changes` report's constructors need
    # not mention it and its output cannot move.
    anchor: str = ""


@dataclass(frozen=True)
class _PriceMovementModel:
    provider_id: str
    provider_label: str
    provider_model_id: str
    higher: int
    lower: int
    added: int
    removed: int
    # D1: the price field that moved this model FURTHEST in each direction, as
    # the classified change itself rather than a magnitude beside it. The
    # magnitude is `delta_abs` on that change, so it is read back through
    # `top_delta` and never stored twice -- a second copy is a second thing to
    # keep in step, and the card prints the change's OWN `delta_display`,
    # `pct_display` and operands, so a stored number that disagreed with them
    # would be invisible until it was wrong on screen.
    #
    # `None` on either side means this model has no two-sided move in that
    # direction: a one-sided add/remove carries no `delta_abs` (nothing to
    # subtract from) and so can never be a headline mover.
    top_increase: RenderedChange | None = None
    top_decrease: RenderedChange | None = None

    @property
    def bucket(self) -> Literal["higher", "lower", "mixed", "coverage"]:
        if self.higher and self.lower:
            return "mixed"
        if self.higher:
            return "higher"
        if self.lower:
            return "lower"
        return "coverage"

    @staticmethod
    def top_delta(rendered: RenderedChange | None) -> float:
        """The absolute per-1M magnitude of a headline candidate, 0.0 for none.

        Sorting only, exactly as `RenderedChange.delta_abs` requires: the card
        displays `delta_display`, never this.
        """
        return abs(rendered.delta_abs or 0.0) if rendered is not None else 0.0


@dataclass(frozen=True)
class _PriceMovementSummary:
    models: tuple[_PriceMovementModel, ...]

    def models_in(self, bucket: Literal["higher", "lower", "mixed", "coverage"]) -> tuple[_PriceMovementModel, ...]:
        return tuple(model for model in self.models if model.bucket == bucket)

    def _headline(
        self, attribute: Literal["top_increase", "top_decrease"]
    ) -> tuple[_PriceMovementModel, RenderedChange] | None:
        """The model whose single largest move in that direction is the report's.

        Selected across every price field of every affected model, by absolute
        per-1M delta. `models` is already sorted, and `max` returns the FIRST
        maximal element, so two models that moved by the same amount resolve to
        the same one on every run.

        `None` when nothing moved that way -- the caller omits the panel rather
        than rendering an empty one.
        """
        candidates = [
            (model, getattr(model, attribute))
            for model in self.models
            if getattr(model, attribute) is not None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda pair: _PriceMovementModel.top_delta(pair[1]))

    @property
    def headline_increase(self) -> tuple[_PriceMovementModel, RenderedChange] | None:
        return self._headline("top_increase")

    @property
    def headline_decrease(self) -> tuple[_PriceMovementModel, RenderedChange] | None:
        return self._headline("top_decrease")

    @property
    def provider_count(self) -> int:
        """Distinct providers with a price change (E5's condition)."""
        return len({model.provider_id for model in self.models})

    @property
    def higher_fields(self) -> int:
        return sum(model.higher for model in self.models)

    @property
    def lower_fields(self) -> int:
        return sum(model.lower for model in self.models)

    @property
    def added_fields(self) -> int:
        return sum(model.added for model in self.models)

    @property
    def removed_fields(self) -> int:
        return sum(model.removed for model in self.models)

    @property
    def field_total(self) -> int:
        return self.higher_fields + self.lower_fields + self.added_fields + self.removed_fields


def make_report_detail_policy(
    *,
    mode: str = "default",
    show_fields: tuple[str, ...] = DEFAULT_REPORT_SHOW_FIELDS,
    squelch_fields: tuple[str, ...] = DEFAULT_REPORT_SQUELCH_FIELDS,
    unclassified_limit: int = 20,
) -> ReportDetailPolicy:
    if mode not in REPORT_DETAIL_MODES:
        raise ValueError(f"report detail mode must be one of {', '.join(REPORT_DETAIL_MODES)}")
    if unclassified_limit < 0:
        raise ValueError("unclassified_limit must be >= 0")
    return ReportDetailPolicy(
        mode=mode,
        show_fields=tuple(pattern.strip() for pattern in show_fields if pattern.strip()),
        squelch_fields=tuple(pattern.strip() for pattern in squelch_fields if pattern.strip()),
        unclassified_limit=unclassified_limit,
    )


def classify_detail_visibility(
    field_name: str,
    policy: ReportDetailPolicy,
) -> Literal["shown", "squelched", "unclassified"]:
    if _matches_any(field_name, policy.show_fields):
        return "shown"
    if _matches_any(field_name, policy.squelch_fields):
        return "squelched"
    return "unclassified"


def filter_field_changes_for_detail(
    field_changes: tuple[FieldChange, ...],
    policy: ReportDetailPolicy,
) -> FilteredFieldChanges:
    shown: list[FieldChange] = []
    squelched: list[FieldChange] = []
    unclassified: list[FieldChange] = []
    for fc in field_changes:
        visibility = classify_detail_visibility(fc.field_name, policy)
        if visibility == "shown":
            shown.append(fc)
        elif visibility == "squelched":
            squelched.append(fc)
        else:
            unclassified.append(fc)
    return FilteredFieldChanges(tuple(shown), tuple(squelched), tuple(unclassified))


def _matches_any(field_name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(field_name, pattern) for pattern in patterns)


def _drop_noop_changes(
    field_changes: tuple[FieldChange, ...],
    profile: ProviderProfile,
) -> tuple[FieldChange, ...]:
    """THE render-time no-op filter (E1). One implementation, one call site.

    A change whose two sides are semantically identical -- both `null`, or
    equal values -- says nothing. `classify_change` already recognizes that as
    `kind == "noop"`; this drops those entries so no renderer has to know the
    rule. Deliberately NOT repeated per renderer: text, markdown, both HTML
    paths and the `changes` report all reach it through `_field_display_plan`,
    which is the single gate every non-JSON path passes through.

    Suppression is presentation-only. `noop` entries stay in
    `ModelDelta.field_changes`, in the database, and in JSON output, which is
    the audit path and must not silently drop records.

    Filtering here rather than at the grouping/rendering layer is also what
    keeps bulk consolidation coherent. `_list_change_signature` builds the
    bulk grouping key from `_list_diff_members`, not from `classify_change`,
    so it reports a difference for lists that compare equal but spell
    differently (`[1] == [True]` while the members spell `"1"` and `"True"`).
    A filter applied after grouping would let three such models consolidate on
    a key whose only member had been suppressed, producing a bulk card with a
    category header and no rows. Running before `_bulk_change_signature` sees
    anything makes the suppressed change invisible to key and card alike.

    Returns `(kept, dropped)`. The dropped tuple is not discarded: it feeds the
    provider-level `no-op` rollup, so a suppressed change is accounted for
    rather than silently vanishing from under a heading that still counts it.
    """
    kept: list[FieldChange] = []
    dropped: list[FieldChange] = []
    for field_change in field_changes:
        target = (
            dropped
            if classify_change(field_change, profile=profile).kind == "noop"
            else kept
        )
        target.append(field_change)
    return tuple(kept), tuple(dropped)


def _field_display_plan(
    field_changes: tuple[FieldChange, ...],
    policy: ReportDetailPolicy,
    profile: ProviderProfile,
    *,
    unclassified_remaining: int | None = None,
) -> _FieldDisplayPlan:
    # Expand first (a one-sided structure flattens into leaves, and some of
    # those leaves ARE no-ops -- a newly added object with a null member
    # produces `path: null -> null`), then drop no-ops, then apply the detail
    # policy. The filter sits above the `mode == "all"` early return on
    # purpose: E1 is a correctness fix, not a verbosity setting, so the
    # full-detail audit view drops them too.
    field_changes, noop = _drop_noop_changes(
        _expand_structured_field_changes(field_changes, profile),
        profile,
    )
    if policy.mode == "all":
        return _FieldDisplayPlan(field_changes, (), (), (), 0, noop)

    filtered = filter_field_changes_for_detail(field_changes, policy)
    if policy.mode == "squelched":
        visible = tuple(fc for fc in field_changes if fc in filtered.squelched)
        hidden = tuple(fc for fc in field_changes if fc not in filtered.squelched)
        return _FieldDisplayPlan(visible, (), (), hidden, 0, noop)

    visible: list[FieldChange] = []
    hidden_unclassified: list[FieldChange] = []
    unclassified_used = 0
    remaining = policy.unclassified_limit if unclassified_remaining is None else unclassified_remaining
    for fc in field_changes:
        visibility = classify_detail_visibility(fc.field_name, policy)
        if visibility == "shown":
            visible.append(fc)
            continue
        if visibility == "squelched":
            continue
        if remaining > 0:
            visible.append(fc)
            remaining -= 1
            unclassified_used += 1
        else:
            hidden_unclassified.append(fc)
    return _FieldDisplayPlan(
        tuple(visible),
        filtered.squelched,
        tuple(hidden_unclassified),
        (),
        unclassified_used,
        noop,
    )


def _expand_structured_field_changes(
    field_changes: tuple[FieldChange, ...],
    profile: ProviderProfile,
) -> tuple[FieldChange, ...]:
    """Expand newly added or removed JSON objects into readable leaf changes.

    Provider schemas can introduce a whole nested object or list in one change.
    The diff layer intentionally preserves that source payload, so human-readable
    reports flatten only one-sided structured values here. Existing list-to-list
    changes remain intact for membership-diff formatting, and JSON reports never
    call this presentation helper.
    """
    expanded: list[FieldChange] = []
    for field_change in field_changes:
        expanded.extend(_expand_structured_field_change(field_change, profile))
    return tuple(expanded)


def _expand_structured_field_change(
    field_change: FieldChange,
    profile: ProviderProfile,
) -> tuple[FieldChange, ...]:
    old_value = field_change.old_value
    new_value = field_change.new_value

    if (
        field_change.field_name == "pricing.overrides"
        and _is_structured_list(old_value)
        and _is_structured_list(new_value)
    ):
        expanded = _expand_pricing_override_changes(
            field_change.field_name,
            old_value,
            new_value,
            profile,
        )
        if expanded is not None:
            return expanded

    if old_value is None and isinstance(new_value, dict):
        return _flatten_one_sided_structure(field_change.field_name, new_value, added=True)
    if new_value is None and isinstance(old_value, dict):
        return _flatten_one_sided_structure(field_change.field_name, old_value, added=False)

    if old_value is None and _is_structured_list(new_value):
        return _flatten_one_sided_structure(field_change.field_name, new_value, added=True)
    if new_value is None and _is_structured_list(old_value):
        return _flatten_one_sided_structure(field_change.field_name, old_value, added=False)

    return (field_change,)


def _is_structured_list(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value)


def _expand_pricing_override_changes(
    field_name: str,
    old_value: list[Any],
    new_value: list[Any],
    profile: ProviderProfile,
) -> tuple[FieldChange, ...] | None:
    """Compare conditional-pricing tiers without treating dictionaries as list members.

    OpenRouter identifies conditional pricing entries by fields such as a prompt-token
    threshold or UTC window. Match unique entries on those conditions so reordering does
    not create noise. If the payload cannot be matched safely, return ``None`` and let
    the existing full-list fallback preserve the upstream values.
    """
    old_by_identity = _index_pricing_overrides(old_value, profile)
    new_by_identity = _index_pricing_overrides(new_value, profile)
    if old_by_identity is None or new_by_identity is None:
        return None

    identities = [
        *old_by_identity,
        *(identity for identity in new_by_identity if identity not in old_by_identity),
    ]
    changes: list[FieldChange] = []
    for identity in identities:
        path = _pricing_override_path(field_name, identity)
        old_item = old_by_identity.get(identity)
        new_item = new_by_identity.get(identity)
        if old_item is None:
            changes.extend(_flatten_one_sided_structure(path, new_item, added=True))
        elif new_item is None:
            changes.extend(_flatten_one_sided_structure(path, old_item, added=False))
        else:
            changes.extend(_diff_structured_values(path, old_item, new_item))
    return tuple(changes)


def _index_pricing_overrides(
    value: list[Any],
    profile: ProviderProfile,
) -> dict[tuple[tuple[str, Any], ...], dict[str, Any]] | None:
    indexed: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            return None
        identity = tuple(
            (field, item[field])
            for field in profile.pricing_override_condition_fields
            if field in item and not isinstance(item[field], (dict, list))
        )
        if not identity or identity in indexed:
            return None
        indexed[identity] = item
    return indexed


def _pricing_override_path(
    field_name: str,
    identity: tuple[tuple[str, Any], ...],
) -> str:
    condition = ",".join(f"{key}={_scalar_display(value)}" for key, value in identity)
    return f"{field_name}[{condition}]"


def _diff_structured_values(path: str, old_value: Any, new_value: Any) -> tuple[FieldChange, ...]:
    if isinstance(old_value, dict) and isinstance(new_value, dict):
        changes: list[FieldChange] = []
        for key in sorted(set(old_value) | set(new_value)):
            child_path = f"{path}.{key}"
            if key not in old_value:
                changes.extend(_flatten_one_sided_structure(child_path, new_value[key], added=True))
            elif key not in new_value:
                changes.extend(_flatten_one_sided_structure(child_path, old_value[key], added=False))
            else:
                changes.extend(_diff_structured_values(child_path, old_value[key], new_value[key]))
        return tuple(changes)
    if old_value != new_value:
        return (FieldChange(path, old_value, new_value),)
    return ()


def _flatten_one_sided_structure(
    field_name: str,
    value: Any,
    *,
    added: bool,
) -> tuple[FieldChange, ...]:
    leaves: list[FieldChange] = []

    def visit(path: str, current: Any) -> None:
        if isinstance(current, dict) and current:
            for key in sorted(current):
                visit(f"{path}.{key}", current[key])
            return
        if isinstance(current, list) and current and _is_structured_list(current):
            for index, item in enumerate(current):
                visit(f"{path}[{index}]", item)
            return
        old_value, new_value = (None, current) if added else (current, None)
        leaves.append(FieldChange(path, old_value, new_value))

    visit(field_name, value)
    return tuple(leaves)


def _list_change_signature(field_change: FieldChange) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Bulk grouping key for one list field change.

    Derived from `change_render._list_diff_members` -- the exact helper
    `classify_change`'s list branch uses -- rather than from a private set
    difference of its own, so the key a group is formed on and the membership
    its card displays come from one implementation. This used to hand-roll the
    difference over a local `_list_item_text` while the per-model renderers
    went through `RenderedChange.list_added`/`list_removed` over `str(x)`; the
    two stringified `dict` members differently.

    Calls `_list_diff_members` and not `classify_change`, deliberately: the
    cascade's `noop` branch would shadow the list branch for lists that compare
    equal but spell differently (`[1] == [True]`), which would change the key.
    See that helper's docstring. Grouping is byte-identical to its
    pre-unification behavior for every input.
    """
    added, removed = _list_diff_members(field_change.old_value, field_change.new_value)
    return (field_change.field_name, added, removed)


def _bulk_change_signature(plan: _FieldDisplayPlan) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] | None:
    """Return a safe bulk-grouping signature for repetitive list changes.

    Scalar values remain model-specific so pricing, limits, cutoffs, and other
    high-signal changes always retain individual model cards. List cardinality
    is intentionally excluded: adding the same parameter is the same semantic
    change whether a model's list grows from 9 to 10 or from 19 to 20.
    """
    if not plan.visible or plan.hidden_unclassified or plan.hidden_non_squelched:
        return None
    if not all(isinstance(fc.old_value, list) and isinstance(fc.new_value, list) for fc in plan.visible):
        return None
    return tuple(sorted(_list_change_signature(fc) for fc in plan.visible))


def _plan_provider_changes(
    changed: tuple[ModelDelta, ...],
    policy: ReportDetailPolicy,
    profile: ProviderProfile,
) -> _ProviderChangePlan:
    planned: list[_PlannedModelChange] = []
    unclassified_remaining = policy.unclassified_limit
    for delta in changed:
        display = _field_display_plan(
            delta.field_changes,
            policy,
            profile,
            unclassified_remaining=unclassified_remaining,
        )
        unclassified_remaining = max(0, unclassified_remaining - display.unclassified_used)
        planned.append(_PlannedModelChange(delta, display))

    rollups = _collect_hidden_rollups(
        (item.delta.provider_model_id, item.display) for item in planned
    )

    if policy.mode != "default":
        return _ProviderChangePlan(tuple(planned), _prune_empty_items(planned), rollups)

    by_signature: dict[
        tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...],
        list[_PlannedModelChange],
    ] = defaultdict(list)
    signatures: dict[str, tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]] = {}
    for item in planned:
        signature = _bulk_change_signature(item.display)
        if signature is None:
            continue
        by_signature[signature].append(item)
        signatures[item.delta.provider_model_id] = signature

    groups = {
        signature: _BulkChangeGroup(tuple(members))
        for signature, members in by_signature.items()
        if len(members) >= BULK_CHANGE_MIN_MODELS
    }
    emitted: set[tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]] = set()
    items: list[_PlannedModelChange | _BulkChangeGroup] = []
    for item in planned:
        signature = signatures.get(item.delta.provider_model_id)
        if signature in groups:
            if signature not in emitted:
                items.append(groups[signature])
                emitted.add(signature)
            continue
        items.append(item)
    return _ProviderChangePlan(tuple(planned), _prune_empty_items(items), rollups)


def _has_hidden_details(plan: _FieldDisplayPlan) -> bool:
    return bool(plan.squelched or plan.hidden_unclassified or plan.hidden_non_squelched)


def _renders_anything(plan: _FieldDisplayPlan) -> bool:
    """THE "does this model still say something?" rule.

    A model earns a card when it has a visible row, or a hidden-detail rollup
    of its own to explain. `noop` is deliberately absent: no-op changes are
    accounted for once at provider level, never on a card, so a model whose
    every change was a no-op renders nothing at all.

    One implementation, consulted by `_prune_empty_items` (scan) and
    `_plan_changes_report_provider` (changes report), so no renderer repeats
    the rule -- and so a heading is emitted only when this predicate said yes
    for at least one model beneath it.

    The scan path additionally drops squelched-only models via
    `_is_squelched_only`; the `changes` report has always kept them (they get a
    model line carrying only their hidden-detail summary). That difference is
    pre-existing and preserved here, which is why the extra rule composes at
    the call site instead of being folded into this predicate.
    """
    return bool(plan.visible or _has_hidden_details(plan))


def _prune_empty_items(
    items: Sequence[_PlannedModelChange | _BulkChangeGroup],
) -> tuple[_PlannedModelChange | _BulkChangeGroup, ...]:
    """Drop planned models that would render an empty card.

    Applied once here rather than repeated as a guard inside each scan
    renderer, so `provider_plan.items` is already exactly what gets rendered
    and every renderer can decide whether to emit its enclosing heading by
    asking whether that tuple (plus the rollups) is empty.
    """
    return tuple(
        item
        for item in items
        if isinstance(item, _BulkChangeGroup)
        or (_renders_anything(item.display) and not _is_squelched_only(item.display))
    )


def _collect_hidden_rollups(
    entries: Iterable[tuple[str, _FieldDisplayPlan]],
) -> _HiddenRollups:
    """Gather every provider-level suppression rollup in one pass.

    Replaces the per-renderer `hidden_squelched`/`hidden_non_squelched`
    accumulation loops that scan text, scan markdown, scan HTML, changes text
    and changes HTML each carried a copy of, and adds `no-op` to all five at
    once.
    """
    squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
    non_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
    noop: list[tuple[str, tuple[FieldChange, ...]]] = []
    for model_id, plan in entries:
        if plan.squelched:
            squelched.append((model_id, plan.squelched))
        if plan.hidden_non_squelched:
            non_squelched.append((model_id, plan.hidden_non_squelched))
        if plan.noop:
            noop.append((model_id, plan.noop))
    return _HiddenRollups(squelched, non_squelched, noop)


def _is_squelched_only(plan: _FieldDisplayPlan) -> bool:
    """Whether a default-detail model has no reportable content of its own.

    Squelched changes are retained in the provider-level rollup, but a model
    that has only those changes should not consume an individual detail card
    or summary row.
    """
    return bool(plan.squelched) and not (
        plan.visible or plan.hidden_unclassified or plan.hidden_non_squelched
    )


def _hidden_change_summary_lines(
    plan: _FieldDisplayPlan,
    *,
    indent: str,
    model_ids: tuple[str, ...],
) -> list[str]:
    lines: list[str] = []
    if plan.squelched:
        lines.append(f"{indent}[Squelched]")
        lines.append(f"{indent}  {len(plan.squelched)} field change{'s' if len(plan.squelched) != 1 else ''} hidden by report detail policy")
    if plan.hidden_unclassified:
        lines.append(f"{indent}[Unclassified]")
        lines.append(
            f"{indent}  {len(plan.hidden_unclassified)} additional unclassified field change"
            f"{'s' if len(plan.hidden_unclassified) != 1 else ''} hidden; add patterns to show_fields or squelch_fields"
        )
    if plan.hidden_non_squelched:
        lines.append(f"{indent}[Filtered]")
        lines.append(
            f"{indent}  {len(plan.hidden_non_squelched)} non-squelched field change"
            f"{'s' if len(plan.hidden_non_squelched) != 1 else ''} omitted in squelched detail mode"
        )
    return lines


def _summarize_field_changes(
    entries: list[tuple[str, tuple[FieldChange, ...]]],
) -> tuple[int, tuple[str, ...]]:
    count = sum(len(changes) for _, changes in entries)
    model_ids = tuple(sorted({model_id for model_id, changes in entries if changes}))
    return count, model_ids


def _format_model_list(model_ids: tuple[str, ...], *, limit: int = 8) -> str:
    if not model_ids:
        return "none"
    shown = list(model_ids[:limit])
    suffix = ""
    if len(model_ids) > limit:
        suffix = f", ... +{len(model_ids) - limit} more"
    return ", ".join(shown) + suffix


def _provider_hidden_summary_lines(
    label: str,
    entries: list[tuple[str, tuple[FieldChange, ...]]],
    policy: ReportDetailPolicy,
    *,
    indent: str,
) -> list[str]:
    count, model_ids = _summarize_field_changes(entries)
    if count == 0:
        return []
    lines = [
        f"{indent}{label}: {count} field change{'s' if count != 1 else ''} across "
        f"{len(model_ids)} model{'s' if len(model_ids) != 1 else ''}",
    ]
    if label == "squelched":
        lines.append(f"{indent}  patterns: {', '.join(policy.squelch_fields) or 'none'}")
    lines.append(f"{indent}  models: {_format_model_list(model_ids)}")
    return lines


def _provider_hidden_summary_markdown(
    label: str,
    entries: list[tuple[str, tuple[FieldChange, ...]]],
    policy: ReportDetailPolicy,
) -> list[str]:
    count, model_ids = _summarize_field_changes(entries)
    if count == 0:
        return []
    lines = [
        f"- {label}: `{count}` field change{'s' if count != 1 else ''} across "
        f"`{len(model_ids)}` model{'s' if len(model_ids) != 1 else ''}",
    ]
    if label == "squelched":
        lines.append(f"- Squelch patterns: `{', '.join(policy.squelch_fields) or 'none'}`")
    lines.append(f"- {label.capitalize()} models: `{_format_model_list(model_ids)}`")
    return lines


def _ordered_rollups(
    rollups: _HiddenRollups,
) -> tuple[tuple[str, list[tuple[str, tuple[FieldChange, ...]]]], ...]:
    """The rollup labels paired with their entries, in emission order.

    One ordering for every format, so text, markdown and HTML cannot drift.
    `no-op` comes last: it is the least policy-driven reason and reads as a
    footnote to the two detail-policy rollups above it.
    """
    return (
        ("squelched", rollups.squelched),
        ("non-squelched", rollups.non_squelched),
        ("no-op", rollups.noop),
    )


def _hidden_rollup_lines(
    rollups: _HiddenRollups,
    policy: ReportDetailPolicy,
    *,
    indent: str,
) -> list[str]:
    lines: list[str] = []
    for label, entries in _ordered_rollups(rollups):
        lines.extend(_provider_hidden_summary_lines(label, entries, policy, indent=indent))
    return lines


def _hidden_rollup_markdown(rollups: _HiddenRollups, policy: ReportDetailPolicy) -> list[str]:
    lines: list[str] = []
    for label, entries in _ordered_rollups(rollups):
        lines.extend(_provider_hidden_summary_markdown(label, entries, policy))
    return lines


def _hidden_rollup_cards(
    rollups: _HiddenRollups,
    policy: ReportDetailPolicy,
) -> list[str]:
    """One HTML string per provider-level rollup that has anything to report.

    ONE element per card, not one per markup fragment. F1's disclosure states
    how many rollups it is hiding, and the previous shape -- a flat list of
    six or seven `<div>`s per card, appended in place -- made `len(parts)`
    read as a count of rollups when it was a count of lines. The first draft
    of that summary line announced "13 report-detail rollups" over two.

    Both HTML renderers join their parts with a newline, so a card assembled
    here and joined there is byte-identical to the fragments this replaced.
    """
    cards = []
    for label, entries in _ordered_rollups(rollups):
        parts: list[str] = []
        _append_html_provider_summary(parts, label, entries, policy)
        if parts:
            cards.append("\n".join(parts))
    return cards


def _field_changes_from_change_rows(model_changes: list[dict[str, Any]]) -> tuple[FieldChange, ...]:
    field_changes = []
    for change in model_changes:
        fn = change.get("field_name")
        if fn:
            field_changes.append(FieldChange(fn, change["old_value"], change["new_value"]))
    return tuple(field_changes)


@dataclass(frozen=True)
class _PlannedChangeEntry:
    """One renderable row group inside a `changes` report provider block.

    Not one per model. A model contributes one entry per presence event it
    recorded in the bucket, plus at most one `changed` entry carrying all of
    its field changes. A model that was added and then removed on the same date
    therefore produces two entries, and both renderers -- which already dispatch
    a flat entry list on `kind` -- render both without knowing they share a
    model.

    Deliberately carries NO raw source rows. It used to, and `entry.rows[0]`
    was how both renderers recovered a `provider_id` to price with -- which is
    precisely how one provider's prices came to be converted with another's
    factors once two providers merged into one block. Provider identity is the
    grouping key now and is known to the caller; an entry that cannot offer a
    "just look at the first row" shortcut cannot be misused as one again.
    """

    model_id: str
    display_name: str
    kind: str
    display: _FieldDisplayPlan | None  # None for added/removed models


@dataclass(frozen=True)
class _ChangesProviderPlan:
    entries: tuple[_PlannedChangeEntry, ...]
    rollups: _HiddenRollups

    @property
    def renders_nothing(self) -> bool:
        """Whether this provider block would be a heading with nothing under it."""
        return not self.entries and not self.rollups.any_hidden


def _plan_changes_report_provider(
    models: dict[str, list[dict[str, Any]]],
    policy: ReportDetailPolicy,
    profile: ProviderProfile,
) -> _ChangesProviderPlan:
    """Plan one provider block of the `changes` report, for text and HTML alike.

    Both renderers previously walked `models` themselves, built their own
    `_field_display_plan`, threaded `unclassified_remaining` by hand, and
    carried their own copy of the "skip a model that renders nothing" guard.
    That is one rule, so it lives here once; the renderers only decide markup.

    Entries come back in source order with anything that renders nothing already
    pruned, so a caller emits its provider (and date) heading only when
    `renders_nothing` is False. One model may contribute several entries; see
    `_PlannedChangeEntry`.
    """
    entries: list[_PlannedChangeEntry] = []
    planned_displays: list[tuple[str, _FieldDisplayPlan]] = []
    unclassified_remaining = policy.unclassified_limit
    for model_id, model_changes in models.items():
        display_name = model_changes[0].get("display_name", model_id)
        # One model can hold several records inside one date bucket -- more than
        # one scan a day is routine. Reading `model_changes[0]["change_kind"]`
        # for the whole model discarded every record after the first: a model
        # added and removed the same day claimed to be merely added, and one
        # added then field-changed lost all of its field changes. Presence
        # events and field changes are independent row groups; plan them so,
        # and every recorded event reaches a renderer.
        presence_rows = [row for row in model_changes if row["change_kind"] in ("added", "removed")]
        field_rows = [row for row in model_changes if row["change_kind"] not in ("added", "removed")]
        # Presence entries lead, matching the HTML renderer, which hoists its
        # added/removed lists above the change cards regardless of row order.
        # Within them, recorded order is kept: added-then-removed is not the
        # same story as removed-then-added.
        for row in presence_rows:
            entries.append(_PlannedChangeEntry(model_id, display_name, row["change_kind"], None))
        field_changes = _field_changes_from_change_rows(field_rows)
        if not field_changes:
            continue
        plan = _field_display_plan(
            field_changes,
            policy,
            profile,
            unclassified_remaining=unclassified_remaining,
        )
        unclassified_remaining = max(0, unclassified_remaining - plan.unclassified_used)
        planned_displays.append((model_id, plan))
        if not _renders_anything(plan):
            continue
        entries.append(_PlannedChangeEntry(model_id, display_name, "changed", plan))
    return _ChangesProviderPlan(tuple(entries), _collect_hidden_rollups(planned_displays))


def _visible_history_events(
    events: tuple[HistoryEvent, ...],
    policy: ReportDetailPolicy,
) -> tuple[HistoryEvent, ...]:
    if policy.mode == "all":
        return events
    visible: list[HistoryEvent] = []
    unclassified_remaining = policy.unclassified_limit
    for event in events:
        if event.change_kind != "changed" or not event.field_name:
            visible.append(event)
            continue
        visibility = classify_detail_visibility(event.field_name, policy)
        if policy.mode == "squelched":
            if visibility == "squelched":
                visible.append(event)
            continue
        if visibility == "shown":
            visible.append(event)
        elif visibility == "unclassified" and unclassified_remaining > 0:
            visible.append(event)
            unclassified_remaining -= 1
    return tuple(visible)


def _history_hidden_counts(
    events: tuple[HistoryEvent, ...],
    policy: ReportDetailPolicy,
) -> tuple[int, int, int]:
    squelched = 0
    hidden_unclassified = 0
    hidden_non_squelched = 0
    unclassified_remaining = policy.unclassified_limit
    for event in events:
        if event.change_kind != "changed" or not event.field_name:
            continue
        visibility = classify_detail_visibility(event.field_name, policy)
        if policy.mode == "squelched":
            if visibility != "squelched":
                hidden_non_squelched += 1
            continue
        if policy.mode == "default":
            if visibility == "squelched":
                squelched += 1
            elif visibility == "unclassified":
                if unclassified_remaining > 0:
                    unclassified_remaining -= 1
                else:
                    hidden_unclassified += 1
    return squelched, hidden_unclassified, hidden_non_squelched


def _history_summary_text(events: tuple[HistoryEvent, ...], policy: ReportDetailPolicy) -> list[str]:
    squelched, hidden_unclassified, hidden_non_squelched = _history_hidden_counts(events, policy)
    lines = []
    if squelched:
        lines.append(f"- [squelched] {squelched} field change(s) hidden by report detail policy")
    if hidden_unclassified:
        lines.append(f"- [unclassified] {hidden_unclassified} additional field change(s) hidden by report detail policy limit")
    if hidden_non_squelched:
        lines.append(f"- [filtered] {hidden_non_squelched} non-squelched field change(s) omitted in squelched detail mode")
    return lines


def _history_summary_markdown(events: tuple[HistoryEvent, ...], policy: ReportDetailPolicy) -> list[str]:
    squelched, hidden_unclassified, hidden_non_squelched = _history_hidden_counts(events, policy)
    lines = []
    if squelched or hidden_unclassified or hidden_non_squelched:
        lines.append("")
    if squelched:
        lines.append(f"`{squelched}` squelched field change(s) hidden by report detail policy.")
    if hidden_unclassified:
        lines.append(f"`{hidden_unclassified}` additional unclassified field change(s) hidden by report detail policy limit.")
    if hidden_non_squelched:
        lines.append(f"`{hidden_non_squelched}` non-squelched field change(s) omitted in squelched detail mode.")
    return lines


def _group_field_changes_for_detail(
    field_changes: tuple[FieldChange, ...],
    policy: ReportDetailPolicy,
    profile: ProviderProfile,
) -> list[tuple[str, list[FieldChange]]]:
    grouped: dict[str, list[FieldChange]] = defaultdict(list)
    category_order = [*_CATEGORY_ORDER]
    if "Unclassified" not in category_order:
        category_order.append("Unclassified")
    for fc in field_changes:
        category = profile.categorize(fc.field_name)
        if policy.mode == "default" and classify_detail_visibility(fc.field_name, policy) == "unclassified":
            category = "Unclassified"
        grouped[category].append(fc)
    return [(cat, grouped[cat]) for cat in category_order if cat in grouped]


def render_scan_report(
    *,
    generated_at: str,
    command: str,
    format_name: str,
    provider_results: list[ProviderScanResult],
    detail_policy: ReportDetailPolicy | None = None,
) -> str:
    detail_policy = detail_policy or make_report_detail_policy()
    if format_name == "json":
        return json.dumps(
            {
                "generated_at": to_local_iso(generated_at),
                "command": command,
                "providers": [_provider_result_json(result) for result in provider_results],
            },
            indent=2,
            sort_keys=True,
        )
    if format_name == "markdown":
        return _render_scan_markdown(
            generated_at=generated_at,
            command=command,
            provider_results=provider_results,
            detail_policy=detail_policy,
        )
    if format_name == "html":
        return _render_scan_html(
            generated_at=generated_at,
            command=command,
            provider_results=provider_results,
            detail_policy=detail_policy,
        )
    return _render_scan_text(
        generated_at=generated_at,
        command=command,
        provider_results=provider_results,
        detail_policy=detail_policy,
    )


def render_history_report(
    *,
    provider_id: str,
    model_id: str,
    format_name: str,
    first_seen: str | None,
    last_seen: str | None,
    events: tuple[HistoryEvent, ...],
    profile: ProviderProfile,
    latest_model: dict[str, Any] | None = None,
    detail_policy: ReportDetailPolicy | None = None,
) -> str:
    detail_policy = detail_policy or make_report_detail_policy()
    if format_name == "json":
        return json.dumps(
            {
                "provider_id": provider_id,
                "model_id": model_id,
                "first_seen": to_local_iso(first_seen),
                "last_seen": to_local_iso(last_seen),
                "latest_model": _normalize_latest_model_json(latest_model),
                "events": [
                    {
                        **asdict(event),
                        "detected_at": to_local_iso(event.detected_at),
                    }
                    for event in events
                ],
            },
            indent=2,
            sort_keys=True,
        )
    if format_name == "markdown":
        lines = [
            f"# History: {provider_id} / {model_id}",
            "",
            f"- First seen: {to_local_human(first_seen)}",
            f"- Last seen: {to_local_human(last_seen)}",
        ]
        if latest_model:
            lines.append(f"- Display name: {latest_model.get('display_name') or model_id}")
            lines.append(f"- Latest price in/out: {_format_price_pair(latest_model)}")
            cache_summary = _format_cache_prices(latest_model)
            if cache_summary:
                lines.append(f"- Latest cache pricing: {cache_summary}")
        lines.append("")
        if not events:
            lines.append("No saved change events matched the requested range.")
            return "\n".join(lines)
        lines.append("| Detected At | Kind | Field | Old | New |")
        lines.append("|---|---|---|---|---|")
        for event in _visible_history_events(events, detail_policy):
            lines.append(
                f"| {to_local_human(event.detected_at)} | {event.change_kind} | {event.field_name or ''} | "
                f"{_scalar_display(event.old_value)} | {_scalar_display(event.new_value)} |"
            )
        lines.extend(_history_summary_markdown(events, detail_policy))
        return "\n".join(lines)
    lines = [
        f"History for {provider_id} / {model_id}",
        f"First seen: {to_local_human(first_seen)}",
        f"Last seen: {to_local_human(last_seen)}",
    ]
    if latest_model:
        lines.append(f"Display name: {latest_model.get('display_name') or model_id}")
        lines.append(f"Latest price in/out: {_format_price_pair(latest_model)}")
        cache_summary = _format_cache_prices(latest_model)
        if cache_summary:
            lines.append(f"Latest cache pricing: {cache_summary}")
    lines.append("")
    if not events:
        lines.append("No saved change events matched the requested range.")
        return "\n".join(lines)
    for event in _visible_history_events(events, detail_policy):
        lines.append(
            f"- {to_local_human(event.detected_at)} [{event.change_kind}] "
            f"{event.field_name or ''} {_scalar_display(event.old_value)} -> {_scalar_display(event.new_value)}"
        )
    lines.extend(_history_summary_text(events, detail_policy))
    return "\n".join(lines)


def render_model_list_report(
    *,
    provider_id: str,
    format_name: str,
    models: tuple[dict[str, Any], ...],
) -> str:
    if format_name == "json":
        return json.dumps(
            {
                "provider_id": provider_id,
                "models": [
                    {
                        **row,
                        "first_seen": to_local_iso(row["first_seen"]),
                        "last_seen": to_local_iso(row["last_seen"]),
                    }
                    for row in models
                ],
            },
            indent=2,
            sort_keys=True,
        )
    if format_name == "markdown":
        lines = [
            f"# Models for {provider_id}",
            "",
            "| Model ID | Display Name | In Price | Out Price | First Seen | Last Seen |",
            "|---|---|---|---|---|---|",
        ]
        if not models:
            lines.append("| _none_ |  |  |  |  |  |")
            return "\n".join(lines)
        for row in models:
            lines.append(
                f"| {row['provider_model_id']} | {row['display_name'] or ''} | "
                f"{_format_number(row.get('input_price'))} | {_format_number(row.get('output_price'))} | "
                f"{to_local_human(row['first_seen']) if row['first_seen'] else ''} | "
                f"{to_local_human(row['last_seen']) if row['last_seen'] else ''} |"
            )
        return "\n".join(lines)
    lines = [f"Known models for {provider_id}", ""]
    if not models:
        lines.append("No saved models found for this provider.")
        return "\n".join(lines)
    grouped = _group_models_by_prefix(models)
    for prefix, rows in grouped:
        if prefix is None:
            for row in rows:
                lines.extend(_render_inline_model_row(row))
            continue
        if len(rows) == 1:
            lines.extend(_render_inline_model_row(rows[0]))
            continue
        lines.append(f"{prefix}/")
        for row in rows:
            suffix = row["provider_model_id"][len(prefix) + 1:]
            lines.append(f"  - {suffix}")
            price_summary = _format_price_pair(row)
            if price_summary != "n/a":
                lines.append(f"    price: {price_summary}")
            lines.append(f"    first: { _short_ts(row['first_seen']) }")
            lines.append(f"    last:  { _short_ts(row['last_seen']) }")
        lines.append("")
    return "\n".join(lines)


def render_providers_report(
    *,
    format_name: str,
    provider_rows: list[dict[str, Any]],
) -> str:
    if format_name == "json":
        normalized_rows = [
            {
                **row,
                "last_successful_scan": to_local_iso(row["last_successful_scan"]),
            }
            for row in provider_rows
        ]
        return json.dumps(normalized_rows, indent=2, sort_keys=True)
    if format_name == "markdown":
        lines = [
            "| Provider ID | Label | Kind | Enabled | Base URL | Models Path | Credential Env | Present | Last Successful Scan |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for row in provider_rows:
            lines.append(
                f"| {row['provider_id']} | {row['label']} | {row['kind']} | {row['enabled']} | "
                f"{row['base_url']} | {row['models_path']} | {row['credential_env_var']} | "
                f"{row['credential_present']} | {to_local_iso(row['last_successful_scan']) or 'none'} |"
            )
        return "\n".join(lines)
    lines = []
    for row in provider_rows:
        lines.extend(
            [
                f"{row['provider_id']} ({row['label']})",
                f"  kind: {row['kind']}",
                f"  enabled: {row['enabled']}",
                f"  base_url: {row['base_url']}",
                f"  models_path: {row['models_path']}",
                f"  credential_env_var: {row['credential_env_var']}",
                f"  credential_present: {row['credential_present']}",
                f"  last_successful_scan: {to_local_iso(row['last_successful_scan']) or 'none'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def render_healthcheck_report(*, format_name: str, checks: list[dict[str, Any]]) -> str:
    if format_name == "json":
        return json.dumps(checks, indent=2, sort_keys=True)
    if format_name == "markdown":
        lines = ["| Check | Status | Detail |", "|---|---|---|"]
        for check in checks:
            lines.append(f"| {check['check']} | {check['status']} | {check['detail']} |")
        return "\n".join(lines)
    return "\n".join(f"{check['status'].upper():7} {check['check']}: {check['detail']}" for check in checks)


def _changes_provider_display_labels(changes: tuple[dict[str, Any], ...]) -> dict[str, str]:
    """Map each `provider_id` in the report to the heading text it renders under.

    Grouping is by identity, so two providers sharing a label now render as two
    adjacent sections. Two adjacent sections spelled identically are worse than
    useless, so when a label is claimed by more than one `provider_id` anywhere
    in the report, every section using it is disambiguated as
    `Label (provider_id)` -- the same form the scan report already uses for its
    provider headings (`_render_scan_html`, and the text report's provider
    line). A label claimed by exactly one provider renders bare, unchanged.

    The map is built once over all `changes`, not per date, so a provider is
    spelled the same way on every date it appears on.

    First label wins per `provider_id`: a provider renamed between two recorded
    scans is one provider with one heading, not two.
    """
    labels: dict[str, str] = {}
    for change in changes:
        labels.setdefault(change.get("provider_id", ""), change.get("provider_label", ""))
    claimants: dict[str, int] = defaultdict(int)
    for label in labels.values():
        claimants[label] += 1
    return {
        pid: (f"{label} ({pid})" if claimants[label] > 1 else label)
        for pid, label in labels.items()
    }


def render_changes_report(
    *,
    format_name: str,
    provider_id: str | None,
    since: str | None,
    until: str | None,
    changes: tuple[dict[str, Any], ...],
    provider_profiles: dict[str, ProviderProfile] | None = None,
    detail_policy: ReportDetailPolicy | None = None,
) -> str:
    detail_policy = detail_policy or make_report_detail_policy()
    if format_name == "json":
        return json.dumps(
            {
                "provider_id": provider_id,
                "since": since,
                "until": until,
                "changes": list(changes),
            },
            indent=2,
            sort_keys=True,
        )

    if not changes:
        period_parts = []
        if since:
            period_parts.append(f"since {since}")
        if until:
            period_parts.append(f"until {until}")
        period = " ".join(period_parts) if period_parts else "in recorded history"
        scope = f"provider {provider_id}" if provider_id else "all providers"
        return f"No changes found for {scope} {period}."

    # Group by detected_at date, then provider IDENTITY, then model.
    #
    # The grouping key is `provider_id`, never `provider_label`. Labels are
    # user-authored display text and nothing constrains two providers from
    # sharing one, but provider identity is first-class here: OpenRouter and
    # Abacus.AI are tracked independently even when they expose the same
    # upstream model id. Keying on the label merged two distinct providers into
    # one section, and where both listed the same `provider_model_id` it merged
    # their rows into one list -- after which `rows[0]` alone decided the
    # display name and, worse, the price multiplier/divisor applied to every
    # row in it. One provider's prices were converted with the other's
    # conversion factors, silently and with no error. See
    # `_changes_provider_display_labels` for how the label is put back for
    # display only.
    by_date: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = OrderedDict()
    for change in changes:
        date_str = to_local_human(change["detected_at"]).split(" ")[0] if change["detected_at"] else "unknown"
        provider = change.get("provider_id", "")
        model = change["provider_model_id"]
        by_date.setdefault(date_str, OrderedDict()).setdefault(provider, OrderedDict()).setdefault(model, []).append(change)

    display_labels = _changes_provider_display_labels(changes)

    if format_name == "html":
        return _render_changes_html(
            by_date=by_date,
            display_labels=display_labels,
            provider_id=provider_id,
            since=since,
            until=until,
            total_changes=len(changes),
            provider_profiles=provider_profiles,
            detail_policy=detail_policy,
        )

    lines = ["Model Sentinel \u2014 Change Log", ""]
    scope_parts = []
    if provider_id:
        scope_parts.append(f"Provider: {provider_id}")
    if since:
        scope_parts.append(f"Since: {since}")
    if until:
        scope_parts.append(f"Until: {until}")
    if scope_parts:
        lines.append("  ".join(scope_parts))
        lines.append("")

    total_changes = len(changes)
    lines.append(f"{total_changes} change{'s' if total_changes != 1 else ''} across {len(by_date)} date{'s' if len(by_date) != 1 else ''}")
    lines.append("=" * 60)
    lines.append("")

    for date_str, providers in by_date.items():
        # Build every provider block first: a date heading and its rule are
        # emitted only if something survives beneath them.
        date_lines: list[str] = []
        for group_provider_id, models in providers.items():
            profile = (provider_profiles or {}).get(
                group_provider_id,
                GENERIC_PROFILE,
            )
            plan = _plan_changes_report_provider(
                models,
                detail_policy,
                profile,
            )
            if plan.renders_nothing:
                continue
            date_lines.append(f"    {display_labels.get(group_provider_id, group_provider_id)}")
            # Conversion factors come from the group key, i.e. from the provider
            # whose rows these are -- not from `rows[0]`, which only happened to
            # agree while the grouping key was the label.
            for entry in plan.entries:
                if entry.kind == "added":
                    date_lines.append(f"      + {entry.model_id} ({entry.display_name})")
                    continue
                if entry.kind == "removed":
                    date_lines.append(f"      - {entry.model_id} ({entry.display_name})")
                    continue
                assert entry.display is not None  # `changed` entries always carry a plan
                date_lines.append(f"      * {entry.model_id} ({entry.display_name})")
                grouped = _group_field_changes_for_detail(
                    entry.display.visible,
                    detail_policy,
                    profile,
                )
                for category, fcs in grouped:
                    if len(grouped) > 1 or category == "Unclassified":
                        date_lines.append(f"          [{category}]")
                        indent = "            "
                    else:
                        indent = "          "
                    for fc in fcs:
                        date_lines.append(
                            f"{indent}{_render_smart_change_text(fc, profile)}"
                        )
                date_lines.extend(
                    _hidden_change_summary_lines(
                        entry.display, indent="          ", model_ids=(entry.model_id,)
                    )
                )
            date_lines.extend(_hidden_rollup_lines(plan.rollups, detail_policy, indent="      "))
        if not date_lines:
            continue
        lines.append(f"  {date_str}")
        lines.append(f"  {'-' * 40}")
        lines.extend(date_lines)
        lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _provider_result_json(result: ProviderScanResult) -> dict[str, Any]:
    return {
        "provider_id": result.provider_id,
        "provider_label": result.provider_label,
        "status": result.status,
        "current_count": result.current_count,
        "saved": result.saved,
        "baseline": asdict(result.baseline) if result.baseline else None,
        "baseline_message": result.baseline_message,
        "scrape_id": result.scrape_id,
        "error_message": result.error_message,
        "added": [_delta_to_json(delta) for delta in result.added],
        "removed": [_delta_to_json(delta) for delta in result.removed],
        "changed": [_delta_to_json(delta) for delta in result.changed],
    }


def _delta_to_json(delta: Any) -> dict[str, Any]:
    return {
        "kind": delta.kind,
        "provider_model_id": delta.provider_model_id,
        "display_name": delta.display_name,
        "field_changes": [asdict(change) for change in delta.field_changes],
    }


# ---------------------------------------------------------------------------
# Smart field-change formatting (shared by text and HTML renderers)
# ---------------------------------------------------------------------------

_CATEGORY_ORDER = ["Pricing", "Context & Limits", "Parameters", "Capabilities", "Benchmarks", "Other"]
_SUMMARY_CATEGORY_ORDER = [*_CATEGORY_ORDER, "Added", "Removed", "Squelched"]
_SUMMARY_CATEGORY_RANK = {category: index for index, category in enumerate(_SUMMARY_CATEGORY_ORDER)}


def _price_movement_kind(
    field_change: FieldChange,
    profile: ProviderProfile,
) -> Literal["higher", "lower", "added", "removed"] | None:
    if not profile.is_price_amount_field(field_change.field_name):
        return None

    old_numeric = _numeric_value(field_change.old_value)
    new_numeric = _numeric_value(field_change.new_value)
    if field_change.old_value is None and new_numeric is not None:
        return "added"
    if old_numeric is not None and field_change.new_value is None:
        return "removed"
    if old_numeric is None or new_numeric is None:
        return None
    if new_numeric > old_numeric:
        return "higher"
    if new_numeric < old_numeric:
        return "lower"
    return None


# Which `_PriceMovementModel` slot a classified change competes for. Only the
# two-sided directions appear: `added`/`removed`/`none` carry no `delta_abs` and
# so can never be a headline mover.
_PRICE_MOVEMENT_SLOTS = {"up": "top_increase", "down": "top_decrease"}


def _collect_price_movement_summary(
    planned_results: list[tuple[ProviderScanResult, _ProviderChangePlan]],
) -> _PriceMovementSummary:
    counts: dict[tuple[str, str], dict[str, int]] = {}
    identities: dict[tuple[str, str], tuple[str, str, str]] = {}
    movers: dict[tuple[str, str], dict[str, RenderedChange]] = {}

    for result, provider_plan in planned_results:
        for item in provider_plan.planned:
            key = (result.provider_id, item.delta.provider_model_id)
            for field_change in item.display.visible:
                movement = _price_movement_kind(field_change, result.profile)
                if movement is None:
                    continue
                identities[key] = (
                    result.provider_id,
                    result.provider_label,
                    item.delta.provider_model_id,
                )
                model_counts = counts.setdefault(
                    key,
                    {"higher": 0, "lower": 0, "added": 0, "removed": 0},
                )
                model_counts[movement] += 1
                # D1's magnitudes, tracked in the pass that was already here.
                # `_price_movement_kind` stays THE gate for the counts above --
                # it is what `test_change_render.py` pins and what decides which
                # fields this card is about -- and `classify_change` supplies
                # what that gate has no opinion on: how far the price moved and
                # how the row is spelled. A one-sided add/remove has no
                # `delta_abs`, so it is counted and then skipped here.
                rendered = classify_change(
                    field_change,
                    profile=result.profile,
                )
                slot = _PRICE_MOVEMENT_SLOTS.get(rendered.direction)
                if slot is None or rendered.delta_abs is None:
                    continue
                model_movers = movers.setdefault(key, {})
                incumbent = model_movers.get(slot)
                if _PriceMovementModel.top_delta(rendered) > _PriceMovementModel.top_delta(incumbent):
                    model_movers[slot] = rendered

    models = []
    for key, model_counts in counts.items():
        provider_id, provider_label, provider_model_id = identities[key]
        model_movers = movers.get(key, {})
        models.append(
            _PriceMovementModel(
                provider_id=provider_id,
                provider_label=provider_label,
                provider_model_id=provider_model_id,
                higher=model_counts["higher"],
                lower=model_counts["lower"],
                added=model_counts["added"],
                removed=model_counts["removed"],
                top_increase=model_movers.get("top_increase"),
                top_decrease=model_movers.get("top_decrease"),
            )
        )
    models.sort(
        key=lambda model: (
            model.provider_label.casefold(),
            model.provider_id.casefold(),
            model.provider_model_id.casefold(),
        )
    )
    return _PriceMovementSummary(tuple(models))


# F2's primary key is rounded to CENTS before comparison, and that rounding is
# load-bearing rather than cosmetic. Compared raw, two per-1M deltas are equal
# only by float coincidence, so tiebreaker 2 (percent) would never run and would
# sit in this module as dead code that no test could reach. At cents, two models
# that both moved ~$1.40 genuinely tie on "how many dollars" and are then ranked
# by relative impact, which is the ordering the design asked for.
#
# Accepted consequence, stated in the design: every sub-cent move rounds to
# $0.00 and ties, so those models are ordered by percent, then coverage, then
# alphabetically. Their mutual order carries no meaning, and neither does the
# size of the move that produced it.
_IMPACT_DELTA_PLACES = 2


@dataclass(frozen=True)
class _ModelImpact:
    """Where one model card sits in F2's impact order.

    Built only by `_model_price_impact`, which returns `None` for a model with
    no price movement at all -- that `None` is also F1's tier test, so the
    "which tier" and "how far up the tier" questions cannot answer from two
    different notions of "has a price change".
    """

    delta: float
    """Largest absolute per-1M movement on this model, ROUNDED TO CENTS."""

    pct: float
    """Absolute percent of the field that produced `delta`; 0.0 when none did."""

    coverage: int
    """Price fields added or removed -- movements with no delta to rank."""

    model_id: str

    @property
    def sort_key(self) -> tuple[float, float, int, str]:
        """Descending on impact, ascending on model id, as one sortable tuple.

        Negation rather than `reverse=True` because the four levels do not all
        run the same way: `reverse=True` would also reverse the model id and
        order two equally-unimportant models Z before A.
        """
        return (-self.delta, -self.pct, -self.coverage, self.model_id.casefold())


def _model_price_impact(
    item: _PlannedModelChange,
    *,
    profile: ProviderProfile,
) -> _ModelImpact | None:
    """F2's sort key for one planned model, or `None` if it has no price move.

    The gate is `_price_movement_kind`, the SAME predicate the Price Movement
    card counts with, so the set of cards promoted to tier 1 is exactly the set
    of models that card names. Deciding it here on `_is_price_amount_field`
    alone would promote a model whose price field was rewritten without moving.

    A one-sided addition or removal carries no `delta_abs` (there is no second
    operand to subtract), so it contributes to `coverage` and leaves the
    primary key at 0.00 -- the design's stated behavior for a model whose only
    price change is a field appearing or disappearing.

    The percent is the percent of the field that produced the primary key, so
    the two are chosen TOGETHER as one maximum over `(delta, pct)` rather than
    independently: taking the largest delta and then the largest percent from
    anywhere on the card would report a percentage that belongs to a different
    field than the dollar figure ranked above it.
    """
    best = (0.0, 0.0)
    coverage = 0
    moved = False
    for field_change in item.display.visible:
        movement = _price_movement_kind(field_change, profile)
        if movement is None:
            continue
        moved = True
        if movement in ("added", "removed"):
            coverage += 1
            continue
        rendered = classify_change(
            field_change,
            profile=profile,
        )
        # `_price_movement_kind` returned a two-sided direction, so both
        # operands are numeric and `signed_pct_change` can only be `None`
        # for a zero basis -- which is a real "no relative reading", ranked as
        # 0.0 rather than allowed to crash the sort.
        percent = signed_pct_change(
            _numeric_value(field_change.old_value),
            _numeric_value(field_change.new_value),
        )
        candidate = (
            round(abs(rendered.delta_abs or 0.0), _IMPACT_DELTA_PLACES),
            abs(percent or 0.0),
        )
        best = max(best, candidate)
    if not moved:
        return None
    return _ModelImpact(best[0], best[1], coverage, item.delta.provider_model_id)


def _is_one_sided(rendered: RenderedChange) -> bool:
    """Whether only one side of a price/count change carries a value.

    `classify_change` records that as `direction="added"`/`"removed"`; the
    two-sided forms always use `up`/`down`/`none`.
    """
    return rendered.direction in ("added", "removed")


def _render_smart_change_text(
    fc: FieldChange,
    profile: ProviderProfile,
) -> str:
    return _render_change_text(classify_change(fc, profile=profile))


def _render_change_text(rendered: RenderedChange) -> str:
    """Format a classified change as one plain-text line.

    Pure formatter: every classification decision was already made by
    `classify_change`. `noop` entries never reach any renderer -- E1 drops
    them once, in `_drop_noop_changes`. This function still formats one if
    handed it directly, rather than growing a second copy of the rule.
    """
    if rendered.kind == "list":
        return _render_list_diff_text(rendered)

    if rendered.kind == "price":
        if _is_one_sided(rendered):
            # `old_raw is None` <=> that side was absent; the price guard in
            # classify_change rejects a present-but-non-numeric side, so the
            # two conditions cannot come apart here.
            old_hint = (
                ABSENT_TEXT_DISPLAY if rendered.old_raw is None
                else f"{rendered.old_raw} ({rendered.old_display} / 1M)"
            )
            new_hint = (
                ABSENT_TEXT_DISPLAY if rendered.new_raw is None
                else f"{rendered.new_raw} ({rendered.new_display} / 1M)"
            )
            return f"{rendered.display_label}: {old_hint} \u2192 {new_hint}"
        price_hint = f"{rendered.old_display} \u2192 {rendered.new_display} / 1M"
        suffix = f", {rendered.pct_display}" if rendered.pct_display else ""
        return f"{rendered.display_label}: {rendered.old_raw} \u2192 {rendered.new_raw} ({price_hint}{suffix})"

    if rendered.kind in ("count", "numeric"):
        # A two-sided `count` is rendered EXACTLY like `numeric` -- same
        # `(+delta, pct)` suffix and no `tok` unit. classify_change routes
        # two-sided count fields (e.g. context_length) to `count` where the
        # renderer this replaced routed them to its numeric branch; see the
        # count guard comment in change_render.py. Emitting `unit` here, or
        # giving `count` its own suffix, would silently change output.
        if _is_one_sided(rendered):
            return f"{rendered.display_label}: {rendered.old_display} \u2192 {rendered.new_display}"
        body = f"{rendered.display_label}: {rendered.old_display} \u2192 {rendered.new_display}"
        if rendered.pct_display:
            return f"{body} ({rendered.delta_display}, {rendered.pct_display})"
        return f"{body} ({rendered.delta_display})"

    # boolean, scalar and noop share the generic `old -> new` form.
    #
    # boolean (E2): `old_display`/`new_display` already carry `on`/`off` (or
    # an em dash for the absent side of a one-sided change), so no
    # translation is needed here. There is deliberately no `(delta)` suffix:
    # `delta_display` for a boolean is the `enabled`/`disabled` (or
    # `added`/`removed`) pill, which occupies the HTML delta column and has
    # no place in a line that already reads `off -> on`. No percent is
    # reachable either -- `pct_display` is always None for this kind.
    #
    # scalar/noop: `old_display`/`new_display` are produced by
    # change_render._scalar_display, which every other renderer also calls.
    return f"{rendered.display_label}: {rendered.old_display} \u2192 {rendered.new_display}"


def _list_diff_body(rendered: RenderedChange) -> str:
    """A list change WITHOUT its label -- `+logit_bias (1 \u2192 2)`.

    Split out of `_render_list_diff_text` so the Change Summary can ask for the
    body directly instead of building the labelled line and splitting it back
    apart on `": "`. That split was never safe: a dynamic field path such as
    `pricing.overrides[min_prompt_tokens=200000].completion` puts provider
    payload text into the label, and `": "` is not reserved there.
    """
    parts = []
    if rendered.list_added:
        parts.append(", ".join(f"+{item}" for item in rendered.list_added))
    if rendered.list_removed:
        parts.append(", ".join(f"-{item}" for item in rendered.list_removed))
    # old_display/new_display carry the raw member counts for `list` changes.
    count_str = f"({rendered.old_display} \u2192 {rendered.new_display})"
    if parts:
        return f"{'; '.join(parts)} {count_str}"
    return count_str


def _render_list_diff_text(rendered: RenderedChange) -> str:
    return f"{rendered.display_label}: {_list_diff_body(rendered)}"


def _render_bulk_list_diff_text(rendered: RenderedChange) -> str:
    """Format a bulk-grouped list membership change.

    Routed through `RenderedChange.list_added`/`list_removed`, exactly like the
    per-model `_render_list_diff_text`. This previously read
    `_list_change_signature` directly, because that helper JSON-encoded
    `dict`/`list` members while `classify_change`'s list branch used plain
    `str(x)` -- so the same shape of change rendered as `+{"name": "alpha"}` on
    a bulk card and `+{'name': 'beta'}` on a per-model card in one report. That
    divergence is now removed (both go through `change_render._list_item_text`,
    JSON), so the group card shows the membership its grouping key was computed
    from while sharing one code path with the per-model renderers.

    One boundary: the card reads `classify_change`, whose `noop` branch
    precedes its list branch, while the key calls `_list_diff_members`
    directly. They part company only for lists that compare equal but spell
    differently (`[1] == [True]`), where the card would say `membership
    changed` and the key would report `+True; -1`. No such FieldChange is
    produced -- both diff passes emit one only when `old_value != new_value` --
    and the key was kept on the direct helper precisely so grouping stays
    byte-identical there. See `_list_diff_members`.

    Differs from `_render_list_diff_text` only in presentation, not in data:
    no `(old -> new)` member counts (cardinality is deliberately excluded from
    the grouping key, so it is not a property of the group), and an explicit
    `membership changed` fallback for a group whose added and removed sets are
    both empty -- reachable when multiplicity or order changed but the set did
    not, e.g. `["a", "a", "b"] -> ["a", "b", "b"]`.
    """
    return f"{rendered.display_label}: {_bulk_list_diff_body(rendered)}"


def _bulk_list_diff_body(rendered: RenderedChange) -> str:
    """A bulk list change WITHOUT its label -- `+seed; -logprobs`.

    Same split, and for the same reason, as `_list_diff_body`: the Change
    Summary wants the body and used to obtain it by splitting the labelled line
    on `": "`, a token a dynamic path's qualifier is free to contain.
    """
    operations = [
        *(f"+{item}" for item in rendered.list_added),
        *(f"-{item}" for item in rendered.list_removed),
    ]
    return "; ".join(operations) if operations else "membership changed"


def _bulk_hidden_entries(
    group: _BulkChangeGroup,
    attribute: Literal["squelched", "hidden_unclassified", "hidden_non_squelched"],
) -> list[tuple[str, tuple[FieldChange, ...]]]:
    return [
        (member.delta.provider_model_id, getattr(member.display, attribute))
        for member in group.members
        if getattr(member.display, attribute)
    ]


def _bulk_group_text_lines(
    group: _BulkChangeGroup,
    policy: ReportDetailPolicy,
    profile: ProviderProfile,
    *,
    indent: str,
) -> list[str]:
    model_ids = tuple(sorted(group.model_ids))
    lines = [
        f"{indent}* {group.label}",
        f"{indent}  models: {_format_model_list(model_ids, limit=12)}",
    ]
    grouped = _group_field_changes_for_detail(group.visible, policy, profile)
    for category, changes in grouped:
        lines.append(f"{indent}  [{category}]")
        for field_change in changes:
            lines.append(
                f"{indent}    "
                f"{_render_bulk_list_diff_text(classify_change(field_change, profile=profile))}"
            )

    squelched = _bulk_hidden_entries(group, "squelched")
    count, affected_models = _summarize_field_changes(squelched)
    if count:
        lines.extend(
            [
                f"{indent}  [Squelched]",
                f"{indent}    {count} field change{'s' if count != 1 else ''} across "
                f"{len(affected_models)} of these models",
                f"{indent}    patterns: {', '.join(policy.squelch_fields) or 'none'}",
                f"{indent}    affected models: {_format_model_list(affected_models)}",
            ]
        )
    return lines


def _bulk_group_markdown_lines(
    group: _BulkChangeGroup,
    policy: ReportDetailPolicy,
    profile: ProviderProfile,
) -> list[str]:
    model_ids = tuple(sorted(group.model_ids))
    lines = [
        f"- **{group.label}**",
        f"  - Models: `{_format_model_list(model_ids, limit=12)}`",
    ]
    for category, changes in _group_field_changes_for_detail(
        group.visible,
        policy,
        profile,
    ):
        lines.append(f"  - **{category}**")
        for field_change in changes:
            rendered = classify_change(field_change, profile=profile)
            lines.append(f"    - `{_render_bulk_list_diff_text(rendered)}`")
    squelched = _bulk_hidden_entries(group, "squelched")
    count, affected_models = _summarize_field_changes(squelched)
    if count:
        lines.extend(
            [
                "  - **Squelched**",
                f"    - `{count}` field change{'s' if count != 1 else ''} across "
                f"`{len(affected_models)}` of these models",
                f"    - Patterns: `{', '.join(policy.squelch_fields) or 'none'}`",
                f"    - Affected models: `{_format_model_list(affected_models)}`",
            ]
        )
    return lines


# ---------------------------------------------------------------------------
# Text scan report (enhanced)
# ---------------------------------------------------------------------------


def _render_scan_text(
    *,
    generated_at: str,
    command: str,
    provider_results: list[ProviderScanResult],
    detail_policy: ReportDetailPolicy,
) -> str:
    lines = [
        "Model Sentinel report",
        f"Generated at: {to_local_human(generated_at)}",
        f"Command: {command}",
        "",
    ]
    for result in provider_results:
        lines.append(f"{result.provider_label} ({result.provider_id})")
        lines.append(f"  status: {result.status}")
        lines.append(f"  current_count: {result.current_count}")
        if result.baseline:
            lines.append(f"  baseline: scrape {result.baseline.scrape_id} at {to_local_human(result.baseline.completed_at)}")
        elif result.baseline_message:
            lines.append(f"  baseline: {result.baseline_message}")
        if result.error_message:
            lines.append(f"  error: {result.error_message}")
        lines.append(f"  added: {len(result.added)}")
        for delta in result.added:
            lines.append(f"    + {delta.provider_model_id} ({delta.display_name})")
        lines.append(f"  removed: {len(result.removed)}")
        for delta in result.removed:
            lines.append(f"    - {delta.provider_model_id} ({delta.display_name})")
        # The counter stays a record count -- it is the number of changed
        # models the scan detected, the same number the JSON payload, the HTML
        # provider badge and the Summary block report. Rows that never render
        # are accounted for by the rollup lines below, exactly as squelched
        # rows always have been.
        lines.append(f"  changed: {len(result.changed)}")
        provider_plan = _plan_provider_changes(
            result.changed,
            detail_policy,
            result.profile,
        )
        for item in provider_plan.items:
            if isinstance(item, _BulkChangeGroup):
                lines.extend(
                    _bulk_group_text_lines(
                        item,
                        detail_policy,
                        result.profile,
                        indent="    ",
                    )
                )
                continue
            delta, plan = item.delta, item.display
            lines.append(f"    * {delta.provider_model_id} ({delta.display_name})")
            if not plan.visible:
                lines.extend(_hidden_change_summary_lines(plan, indent="      ", model_ids=(delta.provider_model_id,)))
                continue
            grouped = _group_field_changes_for_detail(
                plan.visible,
                detail_policy,
                result.profile,
            )
            if len(grouped) == 1 and len(grouped[0][1]) == 1 and grouped[0][0] != "Unclassified":
                # Single change — no category header needed
                lines.append(
                    f"      "
                    f"{_render_smart_change_text(grouped[0][1][0], result.profile)}"
                )
            else:
                for category, changes in grouped:
                    lines.append(f"      [{category}]")
                    for fc in changes:
                        lines.append(
                            f"        {_render_smart_change_text(fc, result.profile)}"
                        )
            lines.extend(_hidden_change_summary_lines(plan, indent="      ", model_ids=(delta.provider_model_id,)))
        lines.extend(_hidden_rollup_lines(provider_plan.rollups, detail_policy, indent="  "))
        lines.append("")

    # Summary table when there are changes across providers
    total_added = sum(len(r.added) for r in provider_results)
    total_removed = sum(len(r.removed) for r in provider_results)
    total_changed = sum(len(r.changed) for r in provider_results)
    if total_added or total_removed or total_changed:
        lines.append("Summary")
        lines.append("-" * 60)
        for result in provider_results:
            if result.change_count == 0:
                lines.append(f"  {result.provider_label}: no changes")
            else:
                parts = []
                if result.added:
                    parts.append(f"{len(result.added)} added")
                if result.removed:
                    parts.append(f"{len(result.removed)} removed")
                if result.changed:
                    parts.append(f"{len(result.changed)} changed")
                lines.append(f"  {result.provider_label}: {', '.join(parts)}")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Markdown scan report
# ---------------------------------------------------------------------------


def _render_scan_markdown(
    *,
    generated_at: str,
    command: str,
    provider_results: list[ProviderScanResult],
    detail_policy: ReportDetailPolicy,
) -> str:
    lines = [
        "# Model Sentinel Report",
        "",
        f"- Generated at: {to_local_human(generated_at)}",
        f"- Command: {command}",
        "",
    ]
    for result in provider_results:
        lines.append(f"## {result.provider_label} (`{result.provider_id}`)")
        lines.append("")
        lines.append(f"- Status: `{result.status}`")
        lines.append(f"- Current models: `{result.current_count}`")
        if result.baseline:
            lines.append(f"- Baseline: scrape `{result.baseline.scrape_id}` at `{to_local_human(result.baseline.completed_at)}`")
        elif result.baseline_message:
            lines.append(f"- Baseline: {result.baseline_message}")
        if result.error_message:
            lines.append(f"- Error: `{result.error_message}`")
        lines.append("")
        lines.append(f"### Added ({len(result.added)})")
        lines.append("")
        if result.added:
            for delta in result.added:
                lines.append(f"- `{delta.provider_model_id}` - {delta.display_name}")
        else:
            lines.append("- None")
        lines.append("")
        lines.append(f"### Removed ({len(result.removed)})")
        lines.append("")
        if result.removed:
            for delta in result.removed:
                lines.append(f"- `{delta.provider_model_id}` - {delta.display_name}")
        else:
            lines.append("- None")
        lines.append("")
        # The count stays a record count (see `_render_scan_text`); the body is
        # built first so the heading is never left standing over nothing. When
        # every changed model was suppressed the rollup lines explain why, and
        # `- None` is the last-resort fallback so the section is never empty.
        lines.append(f"### Changed ({len(result.changed)})")
        lines.append("")
        changed_lines: list[str] = []
        if result.changed:
            provider_plan = _plan_provider_changes(
                result.changed,
                detail_policy,
                result.profile,
            )
            for item in provider_plan.items:
                if isinstance(item, _BulkChangeGroup):
                    changed_lines.extend(
                        _bulk_group_markdown_lines(
                            item,
                            detail_policy,
                            result.profile,
                        )
                    )
                    continue
                delta, plan = item.delta, item.display
                changed_lines.append(f"- `{delta.provider_model_id}` - {delta.display_name}")
                for field_change in plan.visible:
                    changed_lines.append(
                        f"  - `{_render_smart_change_text(field_change, result.profile)}`"
                    )
                if plan.squelched:
                    changed_lines.append(f"  - Squelched: `{len(plan.squelched)}` field change(s) hidden by report detail policy")
                if plan.hidden_unclassified:
                    changed_lines.append(
                        f"  - Unclassified: `{len(plan.hidden_unclassified)}` additional field change(s) hidden; "
                        "add patterns to show_fields or squelch_fields"
                    )
                if plan.hidden_non_squelched:
                    changed_lines.append(f"  - Filtered: `{len(plan.hidden_non_squelched)}` non-squelched field change(s) omitted")
            changed_lines.extend(_hidden_rollup_markdown(provider_plan.rollups, detail_policy))
        lines.extend(changed_lines or ["- None"])
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Unified HTML rendering
# ---------------------------------------------------------------------------

_HTML_CSS = """\
:root {
  --bg: #0f1419;
  --bg-card: #1a1f2e;
  --bg-card-hover: #1e2536;
  --bg-table-row: #151a24;
  --bg-table-alt: #1a2030;
  --border: #2a3040;
  --border-accent: #3a4050;
  --text: #c5cdd8;
  --text-dim: #6b7a8d;
  --text-bright: #e8edf4;
  --accent-green: #34d399;
  --accent-green-dim: rgba(52, 211, 153, 0.12);
  --accent-red: #f87171;
  --accent-red-dim: rgba(248, 113, 113, 0.12);
  --accent-amber: #fbbf24;
  --accent-amber-dim: rgba(251, 191, 36, 0.12);
  --accent-blue: #60a5fa;
  --font-mono: "SF Mono", "Cascadia Code", "Fira Code", "JetBrains Mono", "Consolas", monospace;
  --font-body: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  font-size: 14px;
  line-height: 1.6;
  padding: 2rem;
  max-width: 1100px;
  margin: 0 auto;
}
header {
  border-bottom: 1px solid var(--border);
  padding-bottom: 1.5rem;
  margin-bottom: 2rem;
}
header h1 {
  font-family: var(--font-mono);
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-bright);
  letter-spacing: -0.02em;
}
header h1 .count {
  color: var(--accent-amber);
  font-weight: 400;
}
.meta {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-top: 0.4rem;
  font-family: var(--font-mono);
}
.raw-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.5rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.78rem;
  cursor: pointer;
}
.raw-toggle input { cursor: pointer; }
.provider-cards {
  display: flex;
  gap: 1rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
}
.provider-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  min-width: 200px;
  flex: 1;
  border-left: 3px solid var(--border);
}
.provider-card.status-clean { border-left-color: var(--accent-green); }
.provider-card.status-changed { border-left-color: var(--accent-amber); }
.provider-card.status-error { border-left-color: var(--accent-red); }
.provider-name {
  font-weight: 600;
  color: var(--text-bright);
  font-size: 1rem;
}
.provider-stats {
  color: var(--text-dim);
  font-size: 0.8rem;
  font-family: var(--font-mono);
  margin-top: 0.2rem;
}
.provider-badge {
  margin-top: 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.status-clean .provider-badge { color: var(--accent-green); }
.status-changed .provider-badge { color: var(--accent-amber); }
.status-error .provider-badge { color: var(--accent-red); }
.price-movement-summary {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 2rem;
}
.price-movement-title {
  font-family: var(--font-mono);
  color: var(--text-bright);
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  margin-bottom: 0.65rem;
}
.price-movement-title .outcome {
  font-weight: 400;
  letter-spacing: 0;
}
.price-movement-title .outcome::before {
  content: "· ";
  color: var(--text-dim);
}
.price-higher { color: var(--accent-red); }
.price-lower { color: var(--accent-green); }
.price-mixed { color: var(--accent-amber); }
.price-coverage { color: var(--accent-blue); }
.price-movement-headlines {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}
.price-headline {
  background: var(--bg-table-row);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.6rem 0.75rem;
  font-family: var(--font-mono);
  min-width: 0;
}
.price-headline-label {
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.price-headline-model {
  display: block;
  color: var(--text-bright);
  font-size: 0.85rem;
  margin-top: 0.15rem;
  overflow-wrap: anywhere;
}
.price-headline-field {
  color: var(--text-dim);
  font-size: 0.78rem;
  overflow-wrap: anywhere;
}
.price-headline-values {
  color: var(--text);
  font-size: 0.82rem;
  font-variant-numeric: tabular-nums;
  margin-top: 0.3rem;
  overflow-wrap: anywhere;
}
.price-headline-unit {
  color: var(--text-dim);
  margin-left: 0.3rem;
}
.price-headline-figures {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.1rem;
}
.price-headline-delta {
  font-size: 1.5rem;
  font-weight: 600;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.price-headline-pct {
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}
.price-movement-tallies {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 2rem;
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.price-tally-group {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem;
}
.price-tally-label {
  color: var(--text-bright);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-right: 0.1rem;
}
.price-tally-chip {
  background: var(--bg-table-alt);
  border-radius: 4px;
  padding: 0.05rem 0.4rem;
  white-space: nowrap;
}
.price-movement-models {
  border-top: 1px solid var(--border);
  margin-top: 0.75rem;
  padding-top: 0.55rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.price-movement-models summary {
  cursor: pointer;
  color: var(--text);
}
.price-movement-model-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem 1.5rem;
  margin-top: 0.75rem;
}
.price-movement-group-label {
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 0.3rem;
}
.price-movement-model {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.15rem 0;
}
.price-movement-model .price-movement-provider {
  flex: 0 0 auto;
  min-width: 90px;
}
.price-movement-provider { color: var(--text-dim); }
.price-movement-model code {
  color: var(--text);
  overflow-wrap: anywhere;
}
.date-heading {
  font-family: var(--font-mono);
  font-size: 1.15rem;
  color: var(--text-bright);
  margin: 1.5rem 0 0.75rem 0;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}
.provider-section {
  margin-bottom: 2.5rem;
}
.provider-section h2 {
  font-family: var(--font-mono);
  font-size: 1.15rem;
  color: var(--text-bright);
  margin-bottom: 0.75rem;
  font-weight: 600;
}
.provider-id {
  color: var(--text-dim);
  font-weight: 400;
  font-size: 0.9rem;
}
.baseline-info {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
  margin-bottom: 1rem;
}
.error-msg {
  background: var(--accent-red-dim);
  color: var(--accent-red);
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  margin-bottom: 1rem;
}
h3 {
  font-size: 0.9rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 1.25rem 0 0.5rem 0;
  font-weight: 600;
}
.model-list {
  list-style: none;
  padding-left: 0;
}
.model-list li {
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  margin-bottom: 0.2rem;
}
.added-list li {
  background: var(--accent-green-dim);
  color: var(--accent-green);
}
.removed-list li {
  background: var(--accent-red-dim);
  color: var(--accent-red);
}
.model-list .display-name {
  color: var(--text-dim);
  font-family: var(--font-body);
}
.model-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 1rem;
  overflow: hidden;
}
.model-card:target {
  border-color: var(--accent-amber);
  animation: card-landing 1.8s ease-out 1;
}
@keyframes card-landing {
  from { background: var(--accent-amber-dim); }
  to { background: var(--bg-card); }
}
/* The landing flash is a nicety; the amber border already says "you are here".
   A reader who has asked the OS to reduce motion keeps the border and loses
   the 1.8s fade. */
@media (prefers-reduced-motion: reduce) {
  .model-card:target { animation: none; }
}
.model-card-header {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-card-hover);
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.model-card-header .hidden-count,
.model-card-header .card-back {
  margin-left: auto;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  white-space: nowrap;
}
.model-card-header .card-back { text-decoration: none; }
.model-card-header .card-back:hover { color: var(--text-bright); }
.model-card-header .hidden-count + .card-back { margin-left: 0; }
a.model-link { color: inherit; text-decoration: none; }
a.model-link code {
  text-decoration: underline dotted var(--border-accent);
  text-underline-offset: 0.18em;
}
a.model-link:hover code {
  color: var(--text-bright);
  text-decoration-color: var(--text-bright);
}
.price-headline a.model-link { display: block; }
.model-card-header code {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  color: var(--accent-amber);
  font-weight: 600;
}
.model-card-header .display-name {
  color: var(--text-dim);
  font-size: 0.85rem;
}
.bulk-change-card {
  border-left: 3px solid var(--accent-amber);
}
.bulk-models, .summary-models {
  padding: 0.55rem 1rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.bulk-models summary, .summary-models summary {
  cursor: pointer;
  color: var(--text);
}
.bulk-model-list, .summary-model-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 0.25rem 1rem;
  margin-top: 0.6rem;
}
.bulk-model-list code, .summary-model-list code {
  color: var(--text-dim);
  overflow-wrap: anywhere;
}
.change-category,
.card-table-wrap {
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--border);
}
.card-table-wrap {
  overflow-x: auto;
}
.change-category:last-child,
.card-table-wrap:last-child {
  border-bottom: none;
}
.category-label {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.4rem;
  font-weight: 600;
}
.change-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.change-table th {
  text-align: left;
  color: var(--text-dim);
  font-weight: 500;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.3rem 0.5rem;
  border-bottom: 1px solid var(--border);
}
.change-table td {
  padding: 0.4rem 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.82rem;
  vertical-align: top;
}
.change-table tr:nth-child(even) td {
  background: var(--bg-table-alt);
}
.field-name { color: var(--text); }
td.old-val { color: var(--text-dim); }
td.new-val { color: var(--text-bright); }
td.change-delta { font-weight: 600; }
/* The `changes` table's Change cell takes its colour from the `sem-*` rules
   below, the same ones the scan card's delta and percent cells take theirs
   from. The six `delta-increase`/`delta-decrease`/`delta-neutral`/
   `delta-price-*` rules that used to sit here are deleted, not merely unused:
   they were a second colour vocabulary keyed on DIRECTION, and leaving them in
   the stylesheet would leave the next renderer a working way to paint a bigger
   context window green. */
.card-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.card-table col.col-category { width: 7.5rem; }
.card-table col.col-arrow { width: 1.25rem; }
.card-table col.col-old,
.card-table col.col-new { width: 7rem; }
.card-table col.col-unit { width: 2.75rem; }
.card-table col.col-delta { width: 7rem; }
.card-table col.col-pct { width: 5.5rem; }
.card-table td {
  padding: 0.35rem 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.82rem;
  vertical-align: top;
  border-top: 1px solid transparent;
}
.card-table tr.row-alt td {
  background: var(--bg-table-alt);
}
.card-table tr.group-start td {
  border-top: 1px solid var(--border-accent);
}
.card-table tr:first-child td {
  border-top: 1px solid transparent;
}
.card-table td.old-val,
.card-table td.new-val,
.card-table td.delta,
.card-table td.pct {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.card-table td.num,
.card-table td.delta,
.card-table td.pct {
  white-space: nowrap;
}
.card-table td.old-val,
.card-table td.new-val {
  overflow-wrap: break-word;
}
.card-table td.arrow,
.card-table td.unit {
  color: var(--text-dim);
}
.card-table td.delta,
.card-table td.pct {
  font-weight: 600;
}
.card-table td.cat-chip {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;
}
.card-table tr.list-members td {
  border-top: 1px solid transparent;
  padding-top: 0;
}
.card-table tr.raw-line { display: none; }
body:has(#show-raw:checked) .card-table tr.raw-line { display: table-row; }
/* Structural, so it covers the leading spacer cell too: without `padding-top`
   on BOTH cells the empty first column would set a taller row than the values
   it sits beside. */
.card-table tr.raw-line td {
  border-top: 1px solid transparent;
  padding-top: 0;
}
/* Presentational, and scoped to the cell that actually holds the text. The
   point of R3 is a value you can drag-select and paste, so the class naming
   that cell is the class carrying its rule rather than a bare test hook. */
.card-table tr.raw-line td.raw-values {
  color: var(--text-dim);
  font-size: 0.75rem;
  user-select: text;
}
td.sem-cost-up { color: var(--accent-red); }
td.sem-cost-down { color: var(--accent-green); }
td.sem-capacity { color: var(--accent-amber); }
td.sem-capability { color: var(--accent-blue); }
td.sem-capability-off { color: var(--text-dim); }
td.sem-coverage { color: var(--accent-blue); }
td.sem-neutral { color: var(--text-dim); }
.list-diff {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  padding: 0.35rem 0;
}
/* Membership takes `capability`'s pair -- blue for a member arriving, dim for
   one leaving -- matching the `sem-capability` / `sem-capability-off` cells
   beside it, because a list gaining `logit_bias` IS a capability change. The
   `+` and `−` glyphs already carry the add-vs-remove distinction, so losing the
   green/red contrast costs nothing.

   ONE rule, global. Fix pass 3, blocker 1(b): the blue/dim pair used to be a
   `.card-table` override sitting above a green/red global, so the same
   membership change read blue inside a model card and GREEN inside a
   bulk-change card in the same document -- the same green the Price Movement
   card two screens up uses for a price cut -- and green/red again in the
   `changes` report's standalone list-diff block. Scoping the fix per card type
   would have meant a third copy of one decision and would still have left the
   `changes` report out; there is no card type or document for which green here
   is correct, so the global rule carries the colour and no override exists to
   drift from it. */
.list-added { color: var(--accent-blue); }
.list-removed { color: var(--text-dim); }
.list-count { color: var(--text-dim); font-size: 0.8rem; }
.secondary-changes {
  margin-top: 2.5rem;
  border-top: 1px solid var(--border);
  padding-top: 1.5rem;
}
.secondary-changes > summary {
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 0.9rem;
  color: var(--text-dim);
  font-weight: 600;
}
.secondary-changes > summary:hover {
  color: var(--text-bright);
}
.secondary-changes .provider-section {
  margin-top: 1rem;
}
.summary-section {
  margin-top: 2.5rem;
  border-top: 1px solid var(--border);
  padding-top: 1.5rem;
}
.secondary-changes .summary-section {
  margin-top: 1.5rem;
}
.summary-section h2,
.summary-section > summary {
  font-family: var(--font-mono);
  font-size: 1.1rem;
  color: var(--text-bright);
  margin-bottom: 1rem;
}
.summary-section > summary {
  cursor: pointer;
  font-size: 0.9rem;
}
.summary-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.summary-table th {
  text-align: left;
  color: var(--text-dim);
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.5rem 0.75rem;
  border-bottom: 2px solid var(--border-accent);
  background: var(--bg-card);
}
.summary-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
.summary-table:not(.grouped) tr:nth-child(even) td {
  background: var(--bg-table-alt);
}
.summary-table.grouped tr.row-alt td {
  background: var(--bg-table-alt);
}
.summary-table tr.summary-group td {
  background: var(--bg-card);
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.72rem;
  font-weight: 600;
  padding-top: 0.7rem;
}
.summary-table .summary-models {
  padding: 0;
}
footer {
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 0.75rem;
  font-family: var(--font-mono);
}"""


def _render_html_page(*, title: str, header_html: str, body_html: str, tail_html: str) -> str:
    """The page shell. `tail_html` is whatever sits between the body and the footer.

    Named for its POSITION rather than its contents since F1: the `changes`
    report still passes its Change Summary table here, but the scan report now
    passes the whole tier-2 disclosure, which CONTAINS that table. A parameter
    called `summary_html` holding a disclosure holding a summary would have
    read as a bug at both call sites.
    """
    h = html_module.escape
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h(title)}</title>
<style>
{_HTML_CSS}
</style>
</head>
<body>
{header_html}
{body_html}
{tail_html}
<footer>Generated by Model Sentinel</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# N1: anchors and the links into them
#
# The whole navigation feature is three strings -- a card `id`, an `href` that
# names it, and the back-link -- and every one of them is minted here so the
# report cannot end up with a link whose target does not exist, or two cards
# claiming the same fragment.
# ---------------------------------------------------------------------------

# The Price Movement card's own id, and the target of every card's back-link.
# Not slugified from anything: it is a fixed landmark, so it is spelled once and
# read by both the section that carries it and the links that point at it.
PRICE_MOVEMENT_ANCHOR = "price-movement"

# The raw-value checkbox's id. Read by `_HTML_CSS` (`body:has(#show-raw:checked)`)
# and emitted by the scan header. R3 is CSS-only, so this id IS the wiring: a
# rename in one place and not the other silently turns the toggle into a
# checkbox that does nothing, with no error anywhere.
_RAW_TOGGLE_ID = "show-raw"

# Every run of characters that cannot appear in a fragment identifier we are
# willing to hand-write. Model ids carry `/`, `.`, `:` and `~`, and a run of
# them collapses to ONE `-` so `a//b` and `a/b` do not differ by a hyphen that
# carries no meaning.
_ANCHOR_SEPARATOR_RUN = re.compile(r"[^a-z0-9]+")


def _model_anchor_base(model_id: str) -> str:
    """A model id's slug, BEFORE collision handling.

    Lowercase, every non-alphanumeric run to `-`, stripped of leading and
    trailing `-`, prefixed `m-`. The prefix is not decoration: a slug that
    began with a digit would be a valid fragment but an invalid CSS identifier,
    so `#m-4o` can be selected and `#4o` cannot.

    This deliberately maps `~vendor/model-latest` and `vendor/model-latest` to
    the SAME string. Providers emit `~`-prefixed alias entries alongside their
    base ids, so both appear in one report; the collision is resolved by
    `_CardAnchors`, in render order, rather than by inventing a rule that
    encodes `~` and would have to be re-invented for the next punctuation mark.

    A model id with no alphanumeric character at all would strip to nothing, so
    it falls back to `m-model` and is then disambiguated like any other repeat.
    """
    slug = _ANCHOR_SEPARATOR_RUN.sub("-", model_id.lower()).strip("-")
    return f"m-{slug or 'model'}"


class _CardAnchors:
    """The one place a model card's `id` is minted, and the tier it landed in.

    Two questions, one object, because they have to agree: "what fragment does
    this card carry" and "may anything link to it". The second is N1's hard
    constraint -- fragment navigation INTO a closed `<details>` is unreliable
    across browsers, so nothing may link to a tier-2 card -- and a renderer
    that answered it from its own notion of tiering could drift from the
    renderer that decided the tiering.

    `assign` mints a slug that is unique within the report by construction: the
    used set is checked before the slug is handed out, so the second and later
    occurrences of a colliding base get `-2`, `-3`, ... in the order they were
    assigned. Callers must render the slug `assign` RETURNS rather than looking
    it up afterwards, so that even a repeated `(provider_id, model_id)` key --
    which would be a defect elsewhere -- cannot produce two cards with one id.
    """

    def __init__(self) -> None:
        self._assigned: dict[tuple[str, str], tuple[str, int]] = {}
        self._used: set[str] = set()

    def assign(self, provider_id: str, model_id: str, *, tier: int) -> str:
        """Mint and record this card's id. Returns the id to render."""
        base = _model_anchor_base(model_id)
        slug = base
        occurrence = 1
        while slug in self._used:
            occurrence += 1
            slug = f"{base}-{occurrence}"
        self._used.add(slug)
        self._assigned.setdefault((provider_id, model_id), (slug, tier))
        return slug

    def link(self, provider_id: str, model_id: str) -> str:
        """The id a link may point at, or `""` when it may not.

        Empty for an unknown model (nothing to point at) and for a TIER-2 one
        (the target is inside a closed disclosure). Callers render plain text
        on `""` rather than an `href` that lands nowhere.
        """
        entry = self._assigned.get((provider_id, model_id))
        return entry[0] if entry is not None and entry[1] == 1 else ""


def _model_code_link(model_id: str, anchor: str, *, css_class: str = "") -> str:
    """A model id as `<code>`, wrapped in a link to its card when it has one.

    THE spelling of every into-a-card link in the report -- the Price Movement
    headline panels, its affected-model list, and the Change Summary's Model
    column. Written once because "link when there is a target, plain text when
    there is not" is the rule N1's tier-2 constraint turns on, and three copies
    of it would be three places for one of them to start emitting a link into
    the disclosure.
    """
    h = html_module.escape
    attrs = f' class="{css_class}"' if css_class else ""
    code = f'<code{attrs}>{h(model_id)}</code>'
    if not anchor:
        return code
    return f'<a class="model-link" href="#{h(anchor)}">{code}</a>'


def _build_html_summary_table(
    entries: list[_SummaryEntry],
    *,
    concise: bool = False,
    show_provider: bool = True,
) -> str:
    """Build the concise, selectively consolidated Change Summary.

    `concise` selects the scan report's E5/E6 presentation and defaults to off,
    so the `changes` report -- which the design's cross-renderer matrix scopes
    E3-E6 away from -- keeps the table it has, byte for byte. The row bodies are
    shared either way; only which cells a row carries and what wraps the table
    differ, which is why this is a flag rather than a second builder.

    Under `concise`:

    * E6 -- the table is closed by default and the Category column becomes a
      group heading row, so a category is named once instead of once per row.
    * E5 -- the Provider column is dropped when every row names the same
      provider. Repeating one provider label down a whole column says nothing;
      the moment two providers appear it is load-bearing and comes back.

    `show_provider` is E5's decision, and it is made by the CALLER so that the
    document makes it exactly once. This function used to re-derive it as
    `len({entry.provider for entry in ordered}) > 1`, which is a different
    question from the one `_render_scan_html` asks of the same document: a
    provider whose every change is a no-op contributes a tier-2 rollup -- and
    therefore an `<h3>` naming it -- while producing no summary ROW at all. The
    two answers then disagreed, and the disclosure showed an `<h3>Provider B</h3>`
    inside a summary that had just dropped its Provider column on the grounds
    that only one provider was present. The `changes` report keeps the column
    unconditionally, which is the default.
    """
    if not entries:
        return ""
    h = html_module.escape
    ordered = sorted(entries, key=_summary_entry_sort_key)
    # E5 is scoped to the concise presentation; the `changes` report's table is
    # out of E3-E6's scope and keeps every column it has.
    show_provider = show_provider or not concise
    headings = (
        ([] if concise else ["Category"])
        + (["Provider"] if show_provider else [])
        + ["Model", "Field", "Change"]
    )
    # A group heading names the category for every row beneath it, so it spans
    # the whole table -- however many columns E5 left standing. (The earlier
    # comment here reasoned about presence rows merging the Field and Change
    # columns, which is true of DATA rows and has nothing to do with this line.)
    group_span = len(headings)

    rows = []
    open_category: str | None = None
    # Zebra striping for the GROUPED table is counted here, over data rows only,
    # for the same reason `_render_html_card_table` counts its own: an
    # interleaved non-data row shifts CSS `:nth-child` parity for everything
    # after it. E6's group headings did exactly that, so the alternation
    # restarted at each category and stopped meaning anything. The ungrouped
    # (`changes`) table has no such rows and keeps the plain `:nth-child(even)`
    # rule, which is still correct there and leaves that report untouched.
    data_row_index = 0
    for entry in ordered:
        if concise and entry.category != open_category:
            open_category = entry.category
            rows.append(
                f'<tr class="summary-group"><td colspan="{group_span}">{h(entry.category)}</td></tr>'
            )
        if entry.grouped_model_ids:
            model_list = "".join(f'<code>{h(model_id)}</code>' for model_id in entry.grouped_model_ids)
            model_cell = (
                f'<details class="summary-models"><summary>{len(entry.grouped_model_ids)} models</summary>'
                f'<div class="summary-model-list">{model_list}</div></details>'
            )
        else:
            model_cell = _model_code_link(entry.model_id, entry.anchor)
        cells = [] if concise else [f'<td>{h(entry.category)}</td>']
        if show_provider:
            cells.append(f'<td>{h(entry.provider)}</td>')
        cells.append(f'<td>{model_cell}</td>')
        if entry.field:
            cells.append(f'<td>{h(entry.field)}</td><td>{h(entry.detail)}</td>')
        else:
            cells.append(f'<td colspan="2">{h(entry.detail)}</td>')
        row_class = ' class="row-alt"' if concise and data_row_index % 2 else ""
        data_row_index += 1
        rows.append(f"<tr{row_class}>" + "".join(cells) + "</tr>")

    head = "".join(f'<th>{heading}</th>' for heading in headings)
    table_class = "summary-table grouped" if concise else "summary-table"
    table = (
        f'<table class="{table_class}">'
        f'<thead><tr>{head}</tr></thead>'
        '<tbody>' + "\n".join(rows) + '</tbody>'
        '</table>'
    )
    if not concise:
        return '<section class="summary-section"><h2>Change Summary</h2>' + table + '</section>'
    row_suffix = "" if len(ordered) == 1 else "s"
    return (
        '<details class="summary-section">'
        f'<summary>Change Summary — {len(ordered)} row{row_suffix}</summary>'
        + table
        + '</details>'
    )


def _summary_entry_sort_key(entry: _SummaryEntry) -> tuple[int, str, str, str, str]:
    return (
        _SUMMARY_CATEGORY_RANK.get(entry.category, len(_SUMMARY_CATEGORY_RANK)),
        entry.provider.casefold(),
        entry.model_id.casefold(),
        entry.field.casefold(),
        entry.detail.casefold(),
    )


# ---------------------------------------------------------------------------
# Change Summary entry constructors.
#
# `_SummaryEntry` is built ONLY by the four functions below, one per row shape.
# The scan report and the changes report each walk their own plan, so the
# construction used to be open-coded at both -- and the changes report drifted
# into appending raw 5-tuples, which crashed `_summary_entry_sort_key` for
# every added model, removed model and squelched change. Route both renderers
# through these and that class of drift cannot recur: there is nowhere else to
# build a row.
# ---------------------------------------------------------------------------


def _presence_summary_entry(
    *,
    category: Literal["Added", "Removed"],
    provider_label: str,
    model_id: str,
    display_name: str,
) -> _SummaryEntry:
    """One row for a model that appeared in, or disappeared from, a provider."""
    return _SummaryEntry(category, provider_label, model_id, "", display_name)


def _squelched_summary_entry(
    *,
    provider_label: str,
    squelched: list[tuple[str, tuple[FieldChange, ...]]],
    policy: ReportDetailPolicy,
) -> _SummaryEntry | None:
    """One provider-level row accounting for squelched field changes.

    `None` when nothing was squelched, so callers append conditionally. This
    mirrors the provider-level squelched rollup card `_hidden_rollup_cards`
    already builds for the body of both reports.
    """
    count, model_ids = _summarize_field_changes(squelched)
    if not count:
        return None
    return _SummaryEntry(
        "Squelched",
        provider_label,
        f"{len(model_ids)} models",
        ", ".join(policy.squelch_fields) or "no patterns",
        f"{count} field change{'s' if count != 1 else ''} hidden by report detail policy",
        model_ids,
    )


def _build_summary_entries_from_bulk(
    *,
    provider_label: str,
    group: _BulkChangeGroup,
    profile: ProviderProfile,
) -> list[_SummaryEntry]:
    """Rows for one bulk-change group: one per shared visible field change."""
    entries = []
    for field_change in group.visible:
        rendered = classify_change(field_change, profile=profile)
        entries.append(_SummaryEntry(
            profile.categorize(field_change.field_name),
            provider_label,
            group.label,
            rendered.display_label,
            _bulk_list_diff_body(rendered),
            tuple(sorted(group.model_ids)),
        ))
    return entries


def _summary_change_detail(rendered: RenderedChange) -> str:
    """The Change Summary's `Change` cell: `old → new unit (delta, pct)`.

    Fix pass 3, blocker 2. This cell used to be built by rendering the TEXT
    report's line and splitting it on `": "`, which imported the text report's
    A1-free convention wholesale: the concise HTML report showed
    `$2.00 → $3.00  /1M  +$1.00  ↑ 50.0%` in the model card and
    `2e-06 → 3e-06 ($2.00 → $3.00 / 1M, ↑ 50.0%)` in the summary index a few
    inches below it. The six-leading-zero figure A1 exists to demote led the
    row -- unconditionally, with no relationship to the "Show raw values"
    toggle that governs every other appearance of a raw value in this document.
    A concise report that hides raw values in the card and prints them in the
    index is not concise; it is inconsistent.

    So the cell is composed from `RenderedChange` instead, from the same
    operands and in the same order as the card's columns:

    * the sides through `_html_side_display`, which is what makes an absent
      side read `—` here (the reason `_summary_detail_with_absent_sides` --
      which respelled `null` after the fact -- is gone rather than adapted:
      composing from the operands means the token is never produced);
    * `unit` in the card's unit position;
    * the delta through `_card_delta_cell`, so a one-sided change reads
      `added` / `removed` exactly as the card's delta column does;
    * `pct_display` last.

    The parenthetical is dropped when it would be empty, and `_card_delta_cell`'s
    em-dash fallback is filtered rather than printed -- a scalar change has no
    delta, and `alpha → beta (—)` states nothing.

    A `list` change keeps its own spelling, from `_list_diff_body`: its operands
    are member COUNTS, so the generic form would render `1 → 2` and drop the
    member names that are the whole content of the row. It carries no raw
    provider value either, so blocker 2 does not reach it.

    Text, markdown and JSON are deliberately untouched -- `_SummaryEntry` feeds
    `_build_html_summary_table` and nothing else. See the design's Amendment 8.
    """
    if rendered.kind == "list":
        return _list_diff_body(rendered)
    old = _html_side_display(rendered.old_display, rendered.old_raw)
    new = _html_side_display(rendered.new_display, rendered.new_raw)
    unit = f" {rendered.unit}" if rendered.unit else ""
    annotations = [
        part
        for part in (_card_delta_cell(rendered), rendered.pct_display)
        if part and part != ABSENT_DISPLAY
    ]
    suffix = f" ({', '.join(annotations)})" if annotations else ""
    return f"{old} → {new}{unit}{suffix}"


def _build_summary_entries_from_fc(
    *,
    provider_label: str,
    model_id: str,
    display_name: str,
    field_changes: list[FieldChange],
    profile: ProviderProfile,
    anchor: str = "",
) -> list[_SummaryEntry]:
    """Rows for one model's visible field changes, one per change.

    `anchor` is N1's link target for this model's card, already reduced to `""`
    by `_CardAnchors.link` when the card is in tier 2. This constructor does
    not decide that -- it only carries what the caller was given -- so the
    tier-2 rule stays in the one object that knows the tiering.
    """
    entries = []
    for fc in field_changes:
        rendered = classify_change(fc, profile=profile)
        category = profile.categorize(rendered.field_path)
        # Both cells come from the classification, not from splitting a
        # rendered line: `display_label` IS the Field cell, and
        # `_summary_change_detail` composes the Change cell from the same
        # operands the card's columns use. The split this replaced also had to
        # guess where the label ended, on paths such as
        # `pricing.overrides[min_prompt_tokens=200000].completion` whose text
        # comes from a provider payload.
        entries.append(
            _SummaryEntry(
                category,
                provider_label,
                model_id,
                rendered.display_label,
                _summary_change_detail(rendered),
                anchor=anchor,
            )
        )
    return entries


def _render_html_model_changes(
    delta: ModelDelta,
    profile: ProviderProfile,
    detail_policy: ReportDetailPolicy | None = None,
    unclassified_remaining: int | None = None,
    display_plan: _FieldDisplayPlan | None = None,
    anchor: str = "",
    back_link: bool = False,
) -> tuple[str, _FieldDisplayPlan]:
    """One model's card. `anchor` is its N1 id; `back_link` adds the `↑`.

    Both default off so a caller that has no anchor registry -- and no Price
    Movement card to point back at -- renders exactly the card it rendered
    before. `back_link` is a separate flag rather than being inferred from
    `anchor`, because the two answer different questions: `anchor` is "can this
    card be linked TO", and `back_link` is "does the document contain the
    landmark this card would link FROM". A report with no price change at all
    still gives its cards ids and must not sprout a link to a `#price-movement`
    section that was never rendered.
    """
    h = html_module.escape
    policy = detail_policy or make_report_detail_policy()
    plan = display_plan or _field_display_plan(
        delta.field_changes,
        policy,
        profile,
        unclassified_remaining=unclassified_remaining,
    )
    back = (
        f'<a class="card-back" href="#{PRICE_MOVEMENT_ANCHOR}" '
        f'title="Back to price movement">↑</a>'
        if back_link
        else ""
    )
    card_id = f' id="{h(anchor)}"' if anchor else ""
    parts = [
        f'<div class="model-card"{card_id}>',
        f'<div class="model-card-header"><code>{h(delta.provider_model_id)}</code>'
        f'<span class="display-name">{h(delta.display_name)}</span>'
        f'{_html_hidden_chip(plan)}{back}</div>',
    ]

    # C1: ONE table for the whole card, not one per category. Per-category
    # tables size their columns independently, which is why a card's decimal
    # points did not line up from one category to the next.
    table_html = _render_html_card_table(
        _group_field_changes_for_detail(plan.visible, policy, profile),
        profile,
    )
    if table_html:
        parts.append(f'<div class="card-table-wrap">{table_html}</div>')

    parts.append('</div>')
    return "\n".join(parts), plan


# The three reasons a card can be hiding a field, paired with the word the chip
# uses for each. Ordered as `_append_html_hidden_summary` emitted its sections,
# so the tooltip reads the way the sections it replaces read.
_HIDDEN_CHIP_REASONS = (
    ("squelched", "squelched"),
    ("hidden_unclassified", "unclassified"),
    ("hidden_non_squelched", "filtered"),
)


def _html_hidden_chip(plan: _FieldDisplayPlan) -> str:
    """E3: one dim `+N hidden` chip in the card header, or nothing.

    Replaces the three stacked `<div class="change-category">` blocks that
    `_append_html_hidden_summary` still emits for the `changes` report. On a
    scan card those blocks were routinely taller than the change they were
    hiding: an uppercase SQUELCHED heading plus a full sentence, to report that
    one benchmark row was not shown.

    The count is AGGREGATED across all three reasons, because the reader's
    question is "is this card showing me everything?" and not "under which of
    three policy clauses was each field withheld". The breakdown is not
    discarded -- it moves into the `title`, so nothing the removed sections
    said is now unavailable, it is one hover away.

    Empty string, not an empty chip, when nothing is hidden: `+0 hidden` on
    every card is exactly the clutter this is removing.
    """
    counted = [
        (len(getattr(plan, attribute)), word)
        for attribute, word in _HIDDEN_CHIP_REASONS
        if getattr(plan, attribute)
    ]
    total = sum(count for count, _ in counted)
    if not total:
        return ""
    breakdown = ", ".join(f"{count} {word}" for count, word in counted)
    return (
        f'<span class="hidden-count" title="{html_module.escape(breakdown)}">'
        f'+{total} hidden</span>'
    )


def _html_model_details(label: str, model_ids: tuple[str, ...], *, preview_limit: int = 8) -> str:
    h = html_module.escape
    sorted_ids = tuple(sorted(model_ids))
    model_list = "".join(f'<code>{h(model_id)}</code>' for model_id in sorted_ids)
    return (
        f'<details class="bulk-models"><summary>{h(label)}: '
        f'{h(_format_model_list(sorted_ids, limit=preview_limit))}</summary>'
        f'<div class="bulk-model-list">{model_list}</div></details>'
    )


def _render_html_bulk_changes(
    group: _BulkChangeGroup,
    policy: ReportDetailPolicy,
    profile: ProviderProfile,
) -> str:
    parts = [
        '<div class="model-card bulk-change-card">',
        f'<div class="model-card-header"><code>{html_module.escape(group.label)}</code></div>',
        _html_model_details("Models", group.model_ids, preview_limit=12),
    ]
    for category, changes in _group_field_changes_for_detail(
        group.visible,
        policy,
        profile,
    ):
        parts.append(f'<div class="change-category"><div class="category-label">{html_module.escape(category)}</div>')
        for field_change in changes:
            parts.append(
                _render_html_bulk_list_diff(
                    classify_change(field_change, profile=profile)
                )
            )
        parts.append('</div>')

    squelched = _bulk_hidden_entries(group, "squelched")
    count, affected_models = _summarize_field_changes(squelched)
    if count:
        parts.append('<div class="change-category"><div class="category-label">Squelched</div>')
        parts.append(
            f'<div class="list-diff">{count} field change{"s" if count != 1 else ""} across '
            f'{len(affected_models)} of these models</div>'
        )
        parts.append(
            f'<div class="list-count">patterns: '
            f'{html_module.escape(", ".join(policy.squelch_fields) or "none")}</div>'
        )
        parts.append(_html_model_details("Affected models", affected_models))
        parts.append('</div>')
    parts.append('</div>')
    return "\n".join(parts)


def _append_html_hidden_summary(parts: list[str], plan: _FieldDisplayPlan, *, model_ids: tuple[str, ...]) -> None:
    """The `changes` report's per-model hidden-detail sections.

    The scan report's cards used to share this and now carry `_html_hidden_chip`
    instead (E3). The split is deliberate and matches the design's cross-renderer
    matrix, which scopes E3 to the concise HTML report only: the `changes` report
    lists a model as a heading with loose blocks beneath it, not as a card with a
    header row, so it has nowhere to put a chip.
    """
    if plan.squelched:
        parts.append('<div class="change-category"><div class="category-label">Squelched</div>')
        parts.append(
            f'<div class="list-diff">{len(plan.squelched)} field change'
            f'{"s" if len(plan.squelched) != 1 else ""} hidden by report detail policy</div>'
        )
        parts.append('</div>')
    if plan.hidden_unclassified:
        parts.append('<div class="change-category"><div class="category-label">Unclassified</div>')
        parts.append(
            f'<div class="list-diff">{len(plan.hidden_unclassified)} additional unclassified field change'
            f'{"s" if len(plan.hidden_unclassified) != 1 else ""} hidden; add patterns to show_fields or squelch_fields</div>'
        )
        parts.append('</div>')
    if plan.hidden_non_squelched:
        parts.append('<div class="change-category"><div class="category-label">Filtered</div>')
        parts.append(
            f'<div class="list-diff">{len(plan.hidden_non_squelched)} non-squelched field change'
            f'{"s" if len(plan.hidden_non_squelched) != 1 else ""} omitted in squelched detail mode</div>'
        )
        parts.append('</div>')


def _append_html_provider_summary(
    parts: list[str],
    label: str,
    entries: list[tuple[str, tuple[FieldChange, ...]]],
    policy: ReportDetailPolicy,
) -> None:
    count, model_ids = _summarize_field_changes(entries)
    if count == 0:
        return
    h = html_module.escape
    parts.append('<div class="model-card">')
    parts.append(f'<div class="model-card-header"><code>{h(label)}</code><span class="display-name">report detail summary</span></div>')
    parts.append(f'<div class="change-category"><div class="category-label">{h(label)}</div>')
    parts.append(
        f'<div class="list-diff">{count} field change{"s" if count != 1 else ""} across '
        f'{len(model_ids)} model{"s" if len(model_ids) != 1 else ""}</div>'
    )
    if label == "squelched":
        parts.append(f'<div class="list-count">patterns: {h(", ".join(policy.squelch_fields) or "none")}</div>')
    parts.append(f'<div class="list-count">models: {h(_format_model_list(model_ids))}</div>')
    parts.append('</div></div>')


def _append_html_field_changes(
    parts: list[str],
    field_changes: list[FieldChange],
    profile: ProviderProfile,
) -> None:
    """Append HTML for a group of field changes (table rows + list diffs) to parts.

    The `changes` report's layout, and only that report's: the scan report's
    model cards render through `_render_html_card_table` instead. The two are
    deliberately different documents -- the scan card is a triage surface (C1's
    single aligned table) and the change log stays on the four-column
    per-category table it has always used. Both consume `RenderedChange`, so no
    classification, labelling or value formatting is duplicated between them;
    what differs is markup.
    """
    rendered_changes = [
        classify_change(fc, profile=profile)
        for fc in field_changes
    ]
    list_changes = [rendered for rendered in rendered_changes if rendered.kind == "list"]
    table_changes = [rendered for rendered in rendered_changes if rendered.kind != "list"]

    if table_changes:
        parts.append(
            '<table class="change-table"><thead><tr>'
            '<th>Field</th><th>Old</th><th>New</th><th>Change</th>'
            '</tr></thead><tbody>'
        )
        for rendered in table_changes:
            parts.append(_render_html_table_row(rendered))
        parts.append('</tbody></table>')

    for rendered in list_changes:
        parts.append(_render_html_list_diff(rendered))


# A1: the model card's eight columns, fixed for the whole card by one
# `<colgroup>`. The colgroup is what makes the alignment a property of the CARD
# rather than of each category -- widths live in `_HTML_CSS` keyed off these
# class names, so a column is re-sized in one place.
_CARD_TABLE_COLGROUP = (
    '<colgroup>'
    '<col class="col-category">'
    '<col class="col-field">'
    '<col class="col-old">'
    '<col class="col-arrow">'
    '<col class="col-new">'
    '<col class="col-unit">'
    '<col class="col-delta">'
    '<col class="col-pct">'
    '</colgroup>'
)

# A CONTINUATION row sits under its field's label row and spans every column
# except the category chip's. Fix pass 1: a list change's members used to be an
# inline `(1 -> 2)` count plus a BLOCK-level `<div>` crammed into one
# `colspan="6"` cell starting at the `old` column, so the members began
# mid-table, left-aligned under the right-aligned numeric columns of the rows
# above and below. No CSS fixes that -- the shape was wrong. The label row now
# stays in the grid (chip + label + the count in the DELTA column, where it
# lands under the other deltas) and the members get a band of their own.
#
# Named for the SHAPE rather than for list members because R3's raw-value
# sub-line is the second row to take it, and a second literal `7` beside this
# one would be a second place to change when the colgroup does.
_CARD_CONTINUATION_SPAN = 7

# The kinds whose value cells hold a number, and so may be `nowrap`. Opt-IN on
# purpose: `scalar` values are arbitrary-length provider strings (a real
# `supported_parameters` list, an endpoint URL), and `nowrap` on those widened
# the 7rem column HINT -- `col` widths are not a maximum -- until the card
# overflowed horizontally, defeating the alignment this layout exists to
# deliver. A kind added later gets the safe, wrapping treatment unless someone
# deliberately names it numeric here.
#
# Right-alignment is deliberately NOT scoped this way: every value cell keeps
# it, because the column's shared right edge IS the alignment, and left-aligning
# `off`/`on` against a right-aligned `$2.00` two rows above put the two operands
# of the same column in different places. Verified in a browser both ways.
_CARD_NUMERIC_KINDS = frozenset({"price", "count", "numeric"})

# B1: colour is a function of `semantic` and `direction`, NEVER of `direction`
# alone. Keyed on the pair rather than branched on in a renderer so that the
# design's colour table is one readable object -- the whole point being that
# `up` means red under `cost` and amber under `capacity`, and a renderer that
# looks only at `up` cannot express that.
#
# Absent keys fall through to `sem-neutral` (dim), which covers `neutral` in
# both directions, `capability` on a list membership change (direction `none`),
# and a `cost`/`capacity` change that netted to zero. Every mapped class is
# defined in `_HTML_CSS` against an existing `:root` custom property; this
# introduces no colour values.
_CARD_SEMANTIC_CLASSES = {
    ("cost", "up"): "sem-cost-up",            # higher price: red
    ("cost", "down"): "sem-cost-down",        # lower price: green
    ("capacity", "up"): "sem-capacity",       # amber BOTH ways -- a bigger
    ("capacity", "down"): "sem-capacity",     # context window is not "good"
    ("capability", "up"): "sem-capability",   # on: blue
    ("capability", "down"): "sem-capability-off",  # off: dim
    ("coverage", "added"): "sem-coverage",    # field appeared: blue
    ("coverage", "removed"): "sem-coverage",  # field disappeared: blue
}
_CARD_NEUTRAL_CLASS = "sem-neutral"


def _card_semantic_class(rendered: RenderedChange) -> str:
    """The CSS class the card's delta and percent cells carry for this change."""
    return _CARD_SEMANTIC_CLASSES.get((rendered.semantic, rendered.direction), _CARD_NEUTRAL_CLASS)


def _html_side_display(display: str, raw: str | None) -> str:
    """One side of a change as HTML spells it, absent sides included.

    `classify_change` spells the absent side of a one-sided boolean `—` but the
    absent side of a one-sided price, count or scalar `null` -- three renderers
    inherited that split. HTML closes it: `raw is None` is what "this side was
    absent" MEANS (`_raw_value` returns `None` for exactly that), so it is read
    here rather than string-matching `"null"`, which is also a legitimate
    rendering of the literal string `"null"` arriving from a provider payload.

    THE spelling for every HTML value cell in either document -- the scan
    report's model card (`_render_html_card_row`) and the `changes` report's
    four-column change table (`_render_html_table_row`) alike. Fix pass 2,
    finding 1: it was scoped to the card, while the summary helper below was
    scoped to neither, so the `changes` report ended up with `null` in its card
    and `—` in its summary -- the same contradiction the card's fix removed
    from the scan report, relocated to the document nobody had a golden for.
    The design's cross-renderer matrix already asked for this ("A1 price
    layout: `changes` HTML = yes"), so widening the helper closes a gap rather
    than papering over one.

    Text and markdown are deliberately NOT changed here. They are the formats
    whose goldens are the audit trail for this branch, `null` is what
    `change_render` produces for an absent side, and respelling it in the text
    renderer would move every text and markdown golden for a fix whose whole
    scope is HTML. See the design's Amendment 8.
    """
    return ABSENT_DISPLAY if raw is None else display


def _html_raw_and_normalized(raw: str | None, display: str) -> str:
    """`<raw> (<normalized> / 1M)` for a present price side, the absent token else.

    Takes the OPERANDS, not the composed string. The `changes` table used to
    build `f"{raw} ({display} / 1M)"` unconditionally and hand it to
    `_html_side_display`, which threw it away whenever `raw` was `None` -- so
    the literal text `None (null / 1M)` existed in the source, was constructed
    on every one-sided price row, and was one refactor of that helper away from
    reaching a cell. Composing after the absence check makes the string
    unconstructible instead of merely unused.

    The `raw is None` rule itself is still `_html_side_display`'s and is not
    restated here, so both spellings of an absent side keep coming from one
    place.
    """
    return _html_side_display(f"{raw} ({display} / 1M)" if raw is not None else "", raw)


def _card_delta_cell(rendered: RenderedChange) -> str:
    """The delta column's text: an absolute movement, a pill, or an em dash.

    This is the column that makes A1 visible. Until now no renderer read
    `delta_display` on a price change at all (text prints the two prices and a
    percentage; the `changes` table puts the percentage in its one Change
    column), so a price row's absolute movement -- the "by how much" -- was
    computed on every scan and shown nowhere. It has its own column here,
    bounded sentinels (`+<$0.0001`) included.
    """
    if rendered.delta_display is not None:
        return rendered.delta_display
    if rendered.direction in ("added", "removed"):
        return rendered.direction
    return ABSENT_DISPLAY


def _scientific_notation(raw: str) -> str | None:
    """`0.000002` -> `2.0e-6`. `None` when `raw` is not a finite number.

    Built from `Decimal`, not `float`, and from the STRING the provider sent:
    `Decimal("0.0000035")` is exact where `float` is not, and no formatting
    spec (`:.1e`, `:e`) is used, so nothing here can round a raw value into a
    mantissa that disagrees with the literal value printed beside it in the
    same tooltip. R1 exists to remove zero-counting, and a lossy rendering of
    the magnitude would replace one arithmetic hazard with another.

    Always one digit after the point at minimum (`2.0e-6`, not `2e-6`) so a
    column of tooltips has one shape.
    """
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not value.is_finite():
        return None
    sign, digits, exponent = value.normalize().as_tuple()
    mantissa_digits = "".join(str(digit) for digit in digits)
    # `normalize` strips trailing zeros, so `digits` is the significand and
    # `exponent` places its LAST digit. The scientific exponent places its
    # first, which is `len(digits) - 1` places further left.
    adjusted = int(exponent) + len(mantissa_digits) - 1
    mantissa = f"{mantissa_digits[0]}.{mantissa_digits[1:] or '0'}"
    return f"{'-' if sign else ''}{mantissa}e{adjusted}"


def _price_conversion_factor(profile: ProviderProfile) -> str:
    """`× 1,000,000`, `÷ 1,000`, both, or `""` when the provider needs neither.

    Thousands-separated because the whole point of R1 is that the reader should
    not have to count zeros -- including the zeros in the factor.
    """
    parts = []
    if profile.price_multiplier != 1:
        parts.append(f"× {profile.price_multiplier:,}")
    if profile.price_divisor != 1:
        parts.append(f"÷ {profile.price_divisor:,}")
    return " ".join(parts)


def _card_raw_title(
    rendered: RenderedChange,
    raw: str | None,
    display: str,
    *,
    profile: ProviderProfile,
) -> str:
    """R1: a price cell's `title`, showing the whole derivation, else `""`.

    `0.000002 (2.0e-6) × 1,000,000 = $2.00` -- the literal provider value, its
    magnitude as a parenthetical aside, and the arithmetic that produced the
    figure in the cell. The title used to be the raw value alone, which answered
    "what did the provider say" but left "is this really $2.00 and not $0.20" to
    be done in the reader's head against a number with six leading zeros.

    The scientific notation is parenthesised rather than joined with a middle
    dot. `2.0e-6 · 0.000002 × 1,000,000 = $2.00` reads as a product of a
    mantissa and the raw value -- an expression that evaluates to 4e-6, not
    $2.00 -- and with no conversion factor it degrades to `2.5e0 · 2.5 = $2.50`,
    a bare `A · B = C` whose C is neither. A tooltip that exists so a reader can
    check a price without doing arithmetic cannot use a separator that can be
    read as an operator.

    Absent sides carry no tooltip: there is no raw value to show, and an empty
    `title` is a tooltip that opens onto nothing. A provider whose prices are
    already per-1M (`multiplier == divisor == 1`) gets no factor clause rather
    than a `× 1` that would read as a conversion, leaving `2.5 (2.5e0) = $2.50`.
    """
    if rendered.kind != "price" or raw is None:
        return ""
    scientific = _scientific_notation(raw)
    lead = f"{raw} ({scientific})" if scientific is not None else raw
    factor = _price_conversion_factor(profile)
    derivation = f"{lead} {factor} = {display}" if factor else f"{lead} = {display}"
    return f' title="{html_module.escape(derivation)}"'


def _pricing_rows_by_impact(rendered_changes: list[RenderedChange]) -> list[RenderedChange]:
    """Pricing rows, largest absolute movement first.

    `delta_abs` is `None` on a one-sided change (nothing to subtract from), which
    sorts as 0 -- the same treatment the design gives such models in the F2 card
    sort. Python's sort is stable, so equal-impact rows keep their arrival order.
    """
    return sorted(rendered_changes, key=lambda rendered: -abs(rendered.delta_abs or 0.0))


def _render_html_card_table(
    grouped: list[tuple[str, list[FieldChange]]],
    profile: ProviderProfile,
) -> str:
    """C1: one `<table>` for a whole model card, grouped by category.

    The category name is a dim chip in column 1 on the FIRST row of each group
    only; later rows in the group leave that cell empty and the group's first
    row carries a stronger top border. Returns `""` when nothing is visible, so
    a card with no rows emits no empty table.

    Zebra striping is emitted as a `row-alt` class rather than left to CSS
    `:nth-child(even)`, and counted over FIELD rows only. A list change now adds
    a second `<tr>` for its members, which shifted `nth-child` parity for every
    row after it -- two adjacent rows came out the same shade -- and left the
    members on a different background from the label they belong to. Counting
    here fixes both: the stripe follows the field, and a continuation row takes
    its label row's shade, so the pair reads as one band.
    """
    rows: list[str] = []
    field_row_index = 0
    for category, field_changes in grouped:
        rendered_changes = [
            classify_change(fc, profile=profile)
            for fc in field_changes
        ]
        if category == "Pricing":
            rendered_changes = _pricing_rows_by_impact(rendered_changes)
        for index, rendered in enumerate(rendered_changes):
            rows.append(
                _render_html_card_row(
                    rendered,
                    category=category if index == 0 else None,
                    alternate=field_row_index % 2 == 1,
                    profile=profile,
                )
            )
            field_row_index += 1
    if not rows:
        return ""
    return (
        f'<table class="card-table">{_CARD_TABLE_COLGROUP}<tbody>\n'
        + "\n".join(rows)
        + '\n</tbody></table>'
    )


def _card_raw_line_row(rendered: RenderedChange, *, alternate: bool) -> str:
    """R3: the selectable `old -> new` raw sub-line under a price row, or `""`.

    Always emitted for a price row that has a raw value on either side, and
    hidden by CSS until the header's checkbox is ticked. It exists because a
    `title` cannot be selected or copied: R1's tooltip is for reading, this row
    is for pasting into a spreadsheet, and the two are not substitutes.

    Rendered rather than toggled by script -- the report has no JavaScript, and
    the `<tr>` has to be in the document for `:has()` to reveal it.

    Takes its LABEL row's stripe, for the same reason the list-members row
    does: the two rows are one field, and shading them differently splits the
    band. Absent sides are spelled through `_html_side_display`, so this line
    and the value cell above it cannot disagree about what "absent" looks like.
    """
    if rendered.kind != "price":
        return ""
    if rendered.old_raw is None and rendered.new_raw is None:
        return ""
    h = html_module.escape
    old = _html_side_display(rendered.old_raw or "", rendered.old_raw)
    new = _html_side_display(rendered.new_raw or "", rendered.new_raw)
    row_class = "raw-line row-alt" if alternate else "raw-line"
    return (
        f'<tr class="{row_class}"><td></td>'
        f'<td class="raw-values" colspan="{_CARD_CONTINUATION_SPAN}">'
        f'{h(old)} → {h(new)}</td></tr>'
    )


def _render_html_card_row(
    rendered: RenderedChange,
    *,
    category: str | None,
    alternate: bool = False,
    profile: ProviderProfile,
) -> str:
    """One field's `<tr>` -- plus a members `<tr>` for a list change.

    `category` is the group's name on the group's first row and `None` on every
    later row -- passing it is how a caller says "this row starts a group", so
    the chip and the group border cannot disagree about where a group begins.
    `alternate` is the zebra stripe, decided by the caller because only the
    caller knows the row's position among the card's FIELDS.
    """
    h = html_module.escape
    chip = f'<td class="cat-chip">{h(category)}</td>' if category is not None else '<td></td>'
    classes = ([] if category is None else ["group-start"]) + (["row-alt"] if alternate else [])
    row_class = f' class="{" ".join(classes)}"' if classes else ""
    label = (
        f'<td class="field-name" title="{h(rendered.field_path)}">'
        f'{h(rendered.display_label)}</td>'
    )

    if rendered.kind == "list":
        # A membership change has no operands to align, so the four value
        # columns stay empty and the member COUNT takes the delta column --
        # the only number this row has, in the column the card's other numbers
        # are in. The members follow as a continuation row, built from the same
        # helper the standalone list-diff block uses so the two spellings of a
        # member cannot drift apart.
        label_row = (
            f'<tr{row_class}>{chip}{label}'
            f'<td></td><td></td><td></td><td></td>'
            f'<td class="delta list-count">'
            f'({h(rendered.old_display)} → {h(rendered.new_display)})</td>'
            f'<td class="pct"></td></tr>'
        )
        members = _html_list_members(rendered, separator="")
        if not members:
            return label_row
        # The continuation row takes its LABEL row's stripe, not its own: the
        # two rows are one field, and shading them differently split the band
        # this fix exists to create.
        members_class = "list-members row-alt" if alternate else "list-members"
        return (
            f'{label_row}\n<tr class="{members_class}"><td></td>'
            f'<td colspan="{_CARD_CONTINUATION_SPAN}">{members}</td></tr>'
        )

    semantic_cls = _card_semantic_class(rendered)
    # Fix pass 1: `num` is what earns a cell right-alignment, tabular figures
    # and `nowrap`. See `_CARD_NUMERIC_KINDS`.
    value_cls = " num" if rendered.kind in _CARD_NUMERIC_KINDS else ""
    # Raw-value tooltips on the PRICE columns only. A price cell is the one that
    # no longer shows its provider value: A1 promotes the normalized per-1M
    # figure and drops the `2e-06 ($2.00 / 1M)` pair the old row led with, so
    # without the tooltip the raw would be unreachable from the card. Every
    # other kind already prints its value verbatim, and a tooltip repeating it
    # would be noise. The whole raw value is available in `_full.html`, JSON and
    # the text report regardless.
    old_title = _card_raw_title(
        rendered,
        rendered.old_raw,
        rendered.old_display,
        profile=profile,
    )
    new_title = _card_raw_title(
        rendered,
        rendered.new_raw,
        rendered.new_display,
        profile=profile,
    )
    field_row = (
        f'<tr{row_class}>{chip}{label}'
        f'<td class="old-val{value_cls}"{old_title}>{h(_html_side_display(rendered.old_display, rendered.old_raw))}</td>'
        f'<td class="arrow">→</td>'
        f'<td class="new-val{value_cls}"{new_title}>{h(_html_side_display(rendered.new_display, rendered.new_raw))}</td>'
        f'<td class="unit">{h(rendered.unit or "")}</td>'
        f'<td class="delta {semantic_cls}">{h(_card_delta_cell(rendered))}</td>'
        f'<td class="pct {semantic_cls}">{h(rendered.pct_display or "")}</td></tr>'
    )
    raw_row = _card_raw_line_row(rendered, alternate=alternate)
    return f"{field_row}\n{raw_row}" if raw_row else field_row


# The four model buckets, each with the label its column in the affected-model
# list carries, the label its tally chip carries, and its colour class. One
# table rather than three parallel ones: bucket order, wording and colour are
# the same decision in all three places, and a list that disagreed with the
# chip beside it is precisely the class of defect D3 exists to remove.
#
# FOURTH BUCKET, WHERE THE DESIGN SPECIFIES THREE (design Amendment 7).
# `coverage` is deliberately kept alongside the design's three directional
# buckets (`↑ Higher only`, `↓ Lower only`, `↕ Both directions`). A model whose
# only price change is a field appearing or disappearing has no direction, so
# the design's three columns have nowhere to put it -- and dropping its bucket
# would drop the model from the affected-model list while still counting it in
# the "N MODELS" tally directly above, leaving a total that does not match the
# rows beneath it. `_price_movement_verdict` carries the matching fourth
# outcome, `price fields added/removed`, for the same reason: a report whose
# every price change is a coverage change has no direction to be "mixed" about,
# and "mixed" would assert one.
_PRICE_MOVEMENT_BUCKETS = (
    ("higher", "\u2191 Higher only", "\u2191 {count} higher", "price-higher"),
    ("lower", "\u2193 Lower only", "\u2193 {count} lower", "price-lower"),
    ("mixed", "\u2195 Both directions", "\u2195 {count} both", "price-mixed"),
    ("coverage", "\u00b1 Added/removed only", "\u00b1 {count} added/removed only", "price-coverage"),
)

# The price-FIELD tally, in the design's fixed order. Fixed, not sorted by
# magnitude as it used to be: the chips sit under a "N PRICE FIELDS" label that
# names their unit, so their order no longer has to carry the verdict, and a
# stable order is one less thing for a reader comparing two reports to decode.
_PRICE_MOVEMENT_FIELD_CHIPS = (
    ("lower_fields", "\u2193 {count}", "price-lower"),
    ("higher_fields", "\u2191 {count}", "price-higher"),
    ("added_fields", "+{count} added", "price-coverage"),
    ("removed_fields", "\u2212{count} removed", "price-coverage"),
)


def _price_movement_outcome(summary: _PriceMovementSummary) -> tuple[str, str]:
    """D3: the verdict, derived from MODEL buckets and carrying their counts.

    The counts are appended because the verdict is a summary of them and the
    reader should not have to take it on faith -- `mixed \u2014 4 up, 4 down, 3
    both` states its own evidence.

    Derived from models, not fields, which is the fix. The previous
    implementation compared `higher_fields` against `lower_fields` and printed
    the MODEL tally directly beneath, so a report whose models were tied 4/4/3
    announced "mostly lower" over a body that showed no such thing. Units now
    match on both lines.

    Coverage-only reports keep their own verdict: with no directional model at
    all, "mixed" would be a claim about a direction that nothing here has.

    "mostly" is dropped when the population is UNANIMOUS -- every directional
    model in the leading bucket, the other two empty. The design's rule ("one
    bucket strictly largest -> mostly higher / mostly lower") was written with
    a genuine mixture in mind and says nothing about the unanimous case, where
    it hedges against evidence that does not exist: one model up and nothing
    down is not "mostly higher — 1 up", it is `higher — 1 up`, and
    five models up with nothing falling is no less unanimous for being larger.
    The qualifier returns the moment any other bucket holds a model. This is a
    deliberate amendment to the approved design (design Amendment 3), as is the
    coverage-only verdict above (design Amendment 7).
    """
    buckets = [
        ("up", len(summary.models_in("higher")), "price-higher"),
        ("down", len(summary.models_in("lower")), "price-lower"),
        ("both", len(summary.models_in("mixed")), "price-mixed"),
    ]
    counts = ", ".join(f"{count} {name}" for name, count, _ in buckets if count)
    if not counts:
        return "price fields added/removed", "price-coverage"

    ranked = sorted(buckets, key=lambda bucket: -bucket[1])
    leader_name, leader_count, leader_class = ranked[0]
    strictly_largest = leader_count > ranked[1][1]
    # Every model outside the leading bucket, summed: zero means unanimous.
    # Summed rather than testing `ranked[1]` alone so the check does not lean
    # on the sort order to imply that the third bucket is empty too, and drop
    # the qualifier for the wrong population if that sort is ever changed.
    # Unanimity implies `strictly_largest`: a non-empty leader beats a zero.
    qualifier = "" if sum(count for _, count, _ in ranked[1:]) == 0 else "mostly "
    if strictly_largest and leader_name == "up":
        return f"{qualifier}higher \u2014 {counts}", leader_class
    if strictly_largest and leader_name == "down":
        return f"{qualifier}lower \u2014 {counts}", leader_class
    return f"mixed \u2014 {counts}", "price-mixed"


def _render_price_movement_headline(
    model: _PriceMovementModel,
    rendered: RenderedChange,
    *,
    label: str,
    css_class: str,
    anchor: str = "",
) -> str:
    """One headline mover panel: who moved, on what field, and by how much.

    D1's whole point is the last of those. The card used to say which models
    moved and how many fields moved without ever naming a dollar figure, so the
    biggest move in a scan could only be found by opening every card.

    Values, unit, delta and percent all come off the `RenderedChange`, so this
    panel and the model card's Pricing row are formatting the same numbers from
    the same source and cannot disagree.
    """
    h = html_module.escape
    return (
        f'<div class="price-headline">'
        f'<div class="price-headline-label {css_class}">{h(label)}</div>'
        f'{_model_code_link(model.provider_model_id, anchor, css_class="price-headline-model")}'
        f'<div class="price-headline-field" title="{h(rendered.field_path)}">'
        f'{h(rendered.display_label)}</div>'
        f'<div class="price-headline-values">'
        f'{h(_html_side_display(rendered.old_display, rendered.old_raw))} \u2192 '
        f'{h(_html_side_display(rendered.new_display, rendered.new_raw))}'
        f'<span class="price-headline-unit">{h(rendered.unit or "")}</span></div>'
        f'<div class="price-headline-figures">'
        f'<span class="price-headline-delta {css_class}">{h(_card_delta_cell(rendered))}</span>'
        f'<span class="price-headline-pct {css_class}">{h(rendered.pct_display or "")}</span>'
        f'</div></div>'
    )


def _render_html_price_movement_summary(
    summary: _PriceMovementSummary,
    anchors: _CardAnchors | None = None,
) -> str:
    """D1 + D3: the report's price triage card.

    Order: verdict, the two headline movers, the two tallies, then the
    affected-model list. Dollars first, counts second, names last -- the
    reverse of what this card used to lead with.

    N1: every model named here links to its card, via `anchors`. Every model
    this card can name is in TIER 1 by construction -- `_model_price_impact`
    promotes a card on exactly the predicate (`_price_movement_kind`) that puts
    a model in this summary -- so the links are into the open part of the page.
    That is an invariant of two functions agreeing, not of this one, so the
    lookup still goes through `_CardAnchors.link`, which returns `""` for a
    tier-2 or unknown model and makes the entry plain text. If the two ever
    disagree, this card loses a link; it cannot gain a broken one.
    """
    if not summary.models:
        return ""

    h = html_module.escape
    registry = anchors or _CardAnchors()

    headline_parts = []
    for headline, label, css_class in (
        (summary.headline_increase, "Biggest increase", "price-higher"),
        (summary.headline_decrease, "Biggest decrease", "price-lower"),
    ):
        # Omitted, not emptied: a "Biggest decrease" panel over a blank space
        # reads as a rendering failure, and a scan where nothing got cheaper
        # has nothing to put there.
        if headline is None:
            continue
        model, rendered = headline
        headline_parts.append(
            _render_price_movement_headline(
                model,
                rendered,
                label=label,
                css_class=css_class,
                anchor=registry.link(model.provider_id, model.provider_model_id),
            )
        )

    # E5: the provider label is noise when every affected model came from the
    # same provider, and load-bearing the moment two providers ship a model ID
    # that looks alike.
    show_provider = summary.provider_count > 1

    # Fixed bucket order, in both the chips and the list beneath them, exactly
    # as the field chips are fixed and for the same reason. This used to sort
    # by count descending so the biggest bucket led -- a way of making the
    # order carry the verdict. D3 gives that job to the verdict string itself,
    # which now names the leading bucket AND prints every bucket's count, so
    # the sort is redundant; and a report whose columns move around between
    # runs is a report the reader has to re-parse each time.
    populated_buckets = [
        (group_label, chip_label, css_class, models)
        for bucket, group_label, chip_label, css_class in _PRICE_MOVEMENT_BUCKETS
        if (models := summary.models_in(bucket))
    ]
    model_chip_parts = []
    group_parts = []
    for group_label, chip_label, css_class, models in populated_buckets:
        model_chip_parts.append(
            f'<span class="price-tally-chip {css_class}">'
            f'{h(chip_label.format(count=len(models)))}</span>'
        )
        model_rows = "".join(
            f'<div class="price-movement-model">'
            + (
                f'<span class="price-movement-provider">{h(model.provider_label)}</span>'
                if show_provider
                else ""
            )
            + _model_code_link(
                model.provider_model_id,
                registry.link(model.provider_id, model.provider_model_id),
            )
            + '</div>'
            for model in models
        )
        group_parts.append(
            f'<div class="price-movement-group">'
            f'<div class="price-movement-group-label {css_class}">{h(group_label)} \u2014 {len(models)}</div>'
            f'{model_rows}</div>'
        )

    field_chip_parts = [
        f'<span class="price-tally-chip {css_class}">{h(chip_label.format(count=count))}</span>'
        for attribute, chip_label, css_class in _PRICE_MOVEMENT_FIELD_CHIPS
        if (count := getattr(summary, attribute))
    ]

    model_suffix = "" if len(summary.models) == 1 else "s"
    field_suffix = "" if summary.field_total == 1 else "s"
    outcome, outcome_class = _price_movement_outcome(summary)
    return (
        f'<section class="price-movement-summary" id="{PRICE_MOVEMENT_ANCHOR}">'
        f'<div class="price-movement-title">PRICE MOVEMENT '
        f'<span class="outcome {outcome_class}">{h(outcome)}</span></div>'
        + (
            f'<div class="price-movement-headlines">{"".join(headline_parts)}</div>'
            if headline_parts
            else ""
        )
        # Both tallies name their own unit. They used to read `4 affected
        # models: ...` and `8 changed price fields: ...` in different type
        # sizes, which put two counts of two different things beside each
        # other and left the reader to work out which was which.
        + f'<div class="price-movement-tallies">'
        f'<div class="price-tally-group">'
        f'<span class="price-tally-label">{len(summary.models)} model{model_suffix}</span>'
        f'{"".join(model_chip_parts)}</div>'
        f'<div class="price-tally-group">'
        f'<span class="price-tally-label">{summary.field_total} price field{field_suffix}</span>'
        f'{"".join(field_chip_parts)}</div></div>'
        f'<details class="price-movement-models"><summary>View {len(summary.models)} affected model{model_suffix}</summary>'
        f'<div class="price-movement-model-groups">{"".join(group_parts)}</div>'
        '</details></section>'
    )


# ---------------------------------------------------------------------------
# F1: the concise scan report's two tiers
#
# Everything between here and `_render_scan_html` exists so that function does
# not grow. The design's own risk note says the tiering "belongs in a separate
# builder function rather than inline" the moment the renderer gets longer, and
# it would have: F1 turns one loop over providers into two interleaved passes
# with a sort, a partition and a disclosure between them.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ScanChangeTiers:
    """The rendered halves of F1's split, plus what the disclosure must say.

    `primary` is everything above the fold: per-provider headings, baselines,
    errors, added and removed models, and the model cards that carry a price
    change, in F2's impact order.

    `secondary` is everything the reader asked for only if they ask: model
    cards with no price change (alphabetical), bulk-change cards, and the
    provider-level hidden-detail rollups.
    """

    primary: str
    secondary: str
    secondary_models: int
    """How many MODELS are behind the disclosure, not how many cards.

    Named for the unit deliberately. A bulk-change card is one card standing
    for three or more models, so the two counts differ whenever a group is
    present, and the disclosure line quotes this one because "should I open
    this?" is a question about models. Counting cards and printing `model` was
    the defect this name exists to prevent recurring.
    """
    secondary_rollups: int


def _provider_lead_html(result: ProviderScanResult) -> list[str]:
    """A provider's identification block: heading, baseline, error.

    Stays in tier 1 even for a provider whose every card went to tier 2. The
    heading is what carries the provider id and the baseline scrape the whole
    section is diffed against, and burying that behind a disclosure would leave
    a report whose provenance is only visible after a click.
    """
    h = html_module.escape
    parts = [
        f'<h2>{h(result.provider_label)} '
        f'<span class="provider-id">({h(result.provider_id)})</span></h2>'
    ]
    if result.baseline:
        parts.append(
            f'<div class="baseline-info">Baseline: scrape {result.baseline.scrape_id} '
            f'at {h(to_local_human(result.baseline.completed_at))}</div>'
        )
    if result.error_message:
        parts.append(f'<div class="error-msg">{h(result.error_message)}</div>')
    return parts


def _presence_list_html(heading: str, css_class: str, deltas: tuple[ModelDelta, ...]) -> list[str]:
    h = html_module.escape
    if not deltas:
        return []
    parts = [f'<h3>{heading}</h3><ul class="model-list {css_class}">']
    parts.extend(
        f'<li><code>{h(delta.provider_model_id)}</code> '
        f'<span class="display-name">{h(delta.display_name)}</span></li>'
        for delta in deltas
    )
    parts.append('</ul>')
    return parts


@dataclass(frozen=True)
class _ProviderTierSplit:
    """One provider's cards, partitioned and ordered but not yet rendered.

    N1 forced the split into two passes. Ids have to be handed out in DOCUMENT
    order -- every provider's tier-1 cards, then every provider's tier-2 cards,
    which is how the page lays them out -- while rendering is naturally
    per-provider. Partitioning first, assigning ids across all providers, then
    rendering is the only order in which a report with two providers gets its
    `-2` suffixes in the sequence a reader meets the cards.
    """

    result: ProviderScanResult
    plan: _ProviderChangePlan
    primary: tuple[_PlannedModelChange, ...]
    """Tier-1 model cards, already in F2's impact order."""
    secondary: tuple[_PlannedModelChange | _BulkChangeGroup, ...]
    """Tier-2 cards and bulk groups, already alphabetical."""


def _split_provider_tiers(
    result: ProviderScanResult,
    provider_plan: _ProviderChangePlan,
) -> _ProviderTierSplit:
    """Partition one provider's items into F1's two tiers, each in its order.

    The gate is `_model_price_impact` returning `None`, unchanged: "has no
    price movement" is both the tier test and the sort key, so the two cannot
    answer from different notions of a price change.

    A bulk-change group is always secondary. Groups are formed only from models
    whose every visible change is a list diff (`_bulk_change_signature`), so a
    group can never hold a price change and can never earn tier 1.
    """
    ranked: list[tuple[tuple[float, float, int, str], _PlannedModelChange]] = []
    deferred: list[tuple[str, _PlannedModelChange | _BulkChangeGroup]] = []
    for item in provider_plan.items:
        if isinstance(item, _BulkChangeGroup):
            deferred.append((item.label.casefold(), item))
            continue
        impact = _model_price_impact(
            item,
            profile=result.profile,
        )
        if impact is None:
            deferred.append((item.delta.provider_model_id.casefold(), item))
        else:
            ranked.append((impact.sort_key, item))
    # Keyed sorts, not tuple comparisons: the second element is a dataclass
    # with no ordering, so a tie on the key would raise rather than fall
    # through to it.
    ranked.sort(key=lambda entry: entry[0])
    deferred.sort(key=lambda entry: entry[0])
    return _ProviderTierSplit(
        result=result,
        plan=provider_plan,
        primary=tuple(item for _, item in ranked),
        secondary=tuple(item for _, item in deferred),
    )


def _model_card_html(
    item: _PlannedModelChange,
    anchor: str,
    result: ProviderScanResult,
    policy: ReportDetailPolicy,
    *,
    back_link: bool,
) -> str:
    """One model's card, discarding the squelch count `_render_html_model_changes` also returns.

    Module level, taking `result` as an argument, rather than a closure defined
    inside `_build_scan_change_tiers`'s per-provider loop. The closure read
    `result` from the enclosing scope, which was correct only because every call
    happened in the iteration that bound it -- the late-binding shape ruff's
    B023 flags, and one refactor away from a card rendered against the wrong
    provider's price scale.
    """
    card, _ = _render_html_model_changes(
        item.delta,
        result.profile,
        policy,
        display_plan=item.display,
        anchor=anchor,
        back_link=back_link,
    )
    return card


def _build_scan_change_tiers(
    planned_results: list[tuple[ProviderScanResult, _ProviderChangePlan]],
    policy: ReportDetailPolicy,
    *,
    show_provider: bool,
    anchors: _CardAnchors,
    back_link: bool,
) -> _ScanChangeTiers:
    """Render every provider's changes, split into F1's two tiers.

    `show_provider` is E5 applied outside the movement list: in a report where
    exactly one provider has anything to say, repeating its label at the head of
    the tier-2 block says nothing the tier-1 heading has not already said. With
    two or more providers it comes back, because a bare list of model ids from
    two providers is ambiguous.

    `anchors` is filled in here and read afterwards by the Price Movement card
    and the Change Summary, which is why this runs BEFORE either of them: a
    link can only be minted once its target exists.

    `back_link` says whether the document will contain a Price Movement card
    for the cards to point back at.
    """
    splits = [
        _split_provider_tiers(result, provider_plan)
        for result, provider_plan in planned_results
        if result.change_count or result.status == "error"
    ]

    # N1's id pass, in DOCUMENT order: all of tier 1, then all of tier 2. The
    # `~vendor/model` and `vendor/model` alias collision resolves in the order
    # a reader meets the two cards, so the card that reads `-2` is the second
    # one down the page rather than the second one this loop happened to reach.
    # Bulk groups are skipped: they name a set of models, not one card, and
    # nothing links to them.
    primary_anchors = [
        [anchors.assign(split.result.provider_id, item.delta.provider_model_id, tier=1)
         for item in split.primary]
        for split in splits
    ]
    secondary_anchors = [
        [
            anchors.assign(split.result.provider_id, item.delta.provider_model_id, tier=2)
            if isinstance(item, _PlannedModelChange)
            else ""
            for item in split.secondary
        ]
        for split in splits
    ]

    primary_sections: list[str] = []
    secondary_sections: list[str] = []
    secondary_models = 0
    secondary_rollups = 0

    for split, primary_ids, secondary_ids in zip(splits, primary_anchors, secondary_anchors):
        result, provider_plan = split.result, split.plan

        ranked = [
            _model_card_html(item, anchor, result, policy, back_link=back_link)
            for item, anchor in zip(split.primary, primary_ids)
        ]
        deferred = [
            _render_html_bulk_changes(item, policy, result.profile)
            if isinstance(item, _BulkChangeGroup)
            else _model_card_html(item, anchor, result, policy, back_link=back_link)
            for item, anchor in zip(split.secondary, secondary_ids)
        ]

        rollup_cards = _hidden_rollup_cards(provider_plan.rollups, policy)

        lead = _provider_lead_html(result)
        # The lead is held OUT of this list, and `has_primary` asks whether the
        # list is empty. Measuring `len(lead + body) > 1` instead made the test
        # depend on how many elements the lead happened to have -- one without a
        # baseline, two with -- so the "lead travels into tier 2" rule fired
        # only for baseline-less results, and every real scan (storage.py always
        # builds a `BaselineInfo`) left an `<h2>` and a baseline line presiding
        # over nothing whenever the provider's cards were all secondary.
        primary_body = [
            *_presence_list_html("Added", "added-list", result.added),
            *_presence_list_html("Removed", "removed-list", result.removed),
        ]
        # `<h3>Changed</h3>` is emitted only when a card survives beneath it,
        # the rule this renderer has always had -- now applied per tier, so
        # neither tier can end up with a heading over nothing.
        if ranked:
            primary_body.append('<h3>Changed</h3>')
            primary_body.extend(ranked)
        # A provider heading with nothing beneath it is not a section. Error
        # providers are the exception: the provider card above says ERROR and
        # this section is where a reader looks for the message.
        has_primary = bool(primary_body) or result.status == "error"
        primary_parts = [*lead, *primary_body]

        secondary_parts: list[str] = []
        if deferred or rollup_cards:
            if not has_primary:
                # Every one of this provider's cards is secondary, so its
                # identification travels with them rather than being left
                # behind as a bare `<h2>` over nothing.
                secondary_parts.extend(lead)
            elif show_provider:
                secondary_parts.append(
                    f'<h3>{html_module.escape(result.provider_label)}</h3>'
                )
            secondary_parts.extend(deferred)
            secondary_parts.extend(rollup_cards)
            # Counted over the ITEMS, not over `deferred`'s rendered cards: a
            # `_BulkChangeGroup` is one card standing for `BULK_CHANGE_MIN_MODELS`
            # or more models, so `len(deferred)` understates the disclosure's
            # contents by the size of every group it holds.
            secondary_models += sum(
                len(item.model_ids) if isinstance(item, _BulkChangeGroup) else 1
                for item in split.secondary
            )
            secondary_rollups += len(rollup_cards)

        if has_primary:
            primary_sections.append(
                '<section class="provider-section">' + "\n".join(primary_parts) + '</section>'
            )
        if secondary_parts:
            secondary_sections.append(
                '<section class="provider-section">' + "\n".join(secondary_parts) + '</section>'
            )

    return _ScanChangeTiers(
        primary="".join(primary_sections),
        secondary="".join(secondary_sections),
        secondary_models=secondary_models,
        secondary_rollups=secondary_rollups,
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _render_scan_disclosure(tiers: _ScanChangeTiers, summary_html: str) -> str:
    """F1's one disclosure, wrapping tier 2 and the Change Summary.

    The summary line states its contents WITH COUNTS. A `<details>` labelled
    only "Other changes" asks the reader to open it to find out whether it was
    worth opening, which is the same cost the sections it replaced imposed by
    being open.

    Zero-count clauses are dropped rather than printed as `0 models`: the point
    of the line is what is actually in there.
    """
    if not (tiers.secondary or summary_html):
        return ""
    clauses = []
    if tiers.secondary_models:
        clauses.append(f"{_plural(tiers.secondary_models, 'model')} with no price change")
    if tiers.secondary_rollups:
        clauses.append(_plural(tiers.secondary_rollups, "report-detail rollup"))
    if summary_html:
        clauses.append("the Change Summary")
    return (
        '<details class="secondary-changes">'
        f'<summary>Other changes — {" · ".join(clauses)}</summary>'
        + tiers.secondary
        + summary_html
        + '</details>'
    )


def _scan_header_counts(
    planned_results: list[tuple[ProviderScanResult, _ProviderChangePlan]],
) -> tuple[int, int, int]:
    """E4: (models changed, models scanned, field changes squelched).

    Three numbers in TWO units, which is the whole defect this fixes. The
    header used to read `7 changes · 3 squelched`, where `7` was
    `ProviderScanResult.change_count` -- added plus removed plus changed
    MODELS -- and `3` was a count of FIELDS. Both are returned here so the one
    caller labels each with its own unit rather than letting the reader assume
    they share one.

    The scanned population is the current model count plus the models that
    disappeared, since a removed model was scanned and is no longer current.
    The floor against `change_count` is not a fudge: it keeps a provider that
    reported an inconsistent `current_count` from printing an impossible
    fraction such as `3 of 2 models changed`.
    """
    changed = 0
    scanned = 0
    squelched = 0
    for result, provider_plan in planned_results:
        changed += result.change_count
        scanned += max(result.current_count + len(result.removed), result.change_count)
        count, _ = _summarize_field_changes(provider_plan.rollups.squelched)
        squelched += count
    return changed, scanned, squelched


# ---------------------------------------------------------------------------
# HTML scan report
# ---------------------------------------------------------------------------


def _render_scan_html(
    *,
    generated_at: str,
    command: str,
    provider_results: list[ProviderScanResult],
    detail_policy: ReportDetailPolicy,
) -> str:
    h = html_module.escape
    timestamp = h(to_local_human(generated_at))
    planned_results = [
        (
            result,
            _plan_provider_changes(
                result.changed,
                detail_policy,
                result.profile,
            ),
        )
        for result in provider_results
    ]

    # Provider status cards
    provider_cards = []
    for result in provider_results:
        if result.status == "error":
            status_cls = "status-error"
            badge = "ERROR"
        elif result.change_count > 0:
            status_cls = "status-changed"
            badge = f"{result.change_count} change{'s' if result.change_count != 1 else ''}"
        else:
            status_cls = "status-clean"
            badge = "No changes"
        provider_cards.append(
            f'<div class="provider-card {status_cls}">'
            f'<div class="provider-name">{h(result.provider_label)}</div>'
            f'<div class="provider-stats">{result.current_count} models</div>'
            f'<div class="provider-badge">{badge}</div>'
            f'</div>'
        )

    # F1's two tiers. E5's condition -- more than one provider actually saying
    # something -- is decided ONCE, here, and passed to both consumers: the
    # tier-2 provider headings and the Change Summary's Provider column. The
    # summary table used to answer it a second time from its own rows, which is
    # a narrower population (a provider can contribute a rollup and no row), so
    # one disclosure could carry a Provider heading and a provider-less table.
    # "Which providers said anything" is the reader's question in both places,
    # so it gets one answer.
    contributing = sum(
        1 for result in provider_results
        if result.change_count or result.status == "error"
    )
    # N1 fixes the order of the next three statements. The movement summary is
    # collected first because whether it produces a card decides whether the
    # cards get a back-link; the tiers are built second because that is where
    # ids are assigned; the card itself is rendered last, once there are ids
    # for it to link to.
    movement = _collect_price_movement_summary(planned_results)
    anchors = _CardAnchors()
    tiers = _build_scan_change_tiers(
        planned_results,
        detail_policy,
        show_provider=contributing > 1,
        anchors=anchors,
        back_link=bool(movement.models),
    )

    # Summary entries
    summary_entries: list[_SummaryEntry] = []
    for result, provider_plan in planned_results:
        prov = result.provider_label
        for item in provider_plan.items:
            if isinstance(item, _BulkChangeGroup):
                summary_entries.extend(_build_summary_entries_from_bulk(
                    provider_label=prov,
                    group=item,
                    profile=result.profile,
                ))
                continue
            delta, plan = item.delta, item.display
            summary_entries.extend(_build_summary_entries_from_fc(
                provider_label=prov, model_id=delta.provider_model_id,
                display_name=delta.display_name, field_changes=list(plan.visible),
                profile=result.profile,
                anchor=anchors.link(result.provider_id, delta.provider_model_id),
            ))
        squelched_entry = _squelched_summary_entry(
            provider_label=prov, squelched=provider_plan.rollups.squelched, policy=detail_policy,
        )
        if squelched_entry:
            summary_entries.append(squelched_entry)
        for delta in result.added:
            summary_entries.append(_presence_summary_entry(
                category="Added", provider_label=prov,
                model_id=delta.provider_model_id, display_name=delta.display_name,
            ))
        for delta in result.removed:
            summary_entries.append(_presence_summary_entry(
                category="Removed", provider_label=prov,
                model_id=delta.provider_model_id, display_name=delta.display_name,
            ))

    # E4: two units, each named. `changed` counts MODELS, `squelched` counts
    # FIELD CHANGES; the header this replaces printed them side by side as
    # though they were the same thing.
    changed, scanned, squelched = _scan_header_counts(planned_results)
    counts = f"{changed} of {_plural(scanned, 'model')} changed" if changed else ""
    if counts and squelched:
        counts += f" \u00b7 {_plural(squelched, 'field change')} squelched"
    count_span = f'<span class="count">\u2014 {counts}</span>' if counts else ""
    # R3, plus the controller decision the `_full.html` report forced. `cli.py`
    # builds that document by calling THIS renderer with `mode="all"`, so it
    # inherits A1's move of raw provider values into tooltips -- a real loss for
    # an audit view, where the raw numbers are the point. Rather than a second
    # renderer or a new flag, the toggle starts CHECKED whenever the detail
    # policy is the full-detail one, so the audit report shows raw values inline
    # by default and the concise report does not. Inferred from the mode so the
    # two documents cannot be configured inconsistently by a caller.
    raw_checked = " checked" if detail_policy.mode == "all" else ""
    header_html = (
        f'<header>\n'
        f'  <h1>Model Sentinel {count_span}</h1>\n'
        f'  <div class="meta">{timestamp} &middot; {h(command)}</div>\n'
        f'  <label class="raw-toggle"><input type="checkbox" id="{_RAW_TOGGLE_ID}"'
        f'{raw_checked}> Show raw values</label>\n'
        f'</header>'
    )
    price_movement_html = _render_html_price_movement_summary(movement, anchors)
    body_html = (
        f'<div class="provider-cards">\n  {"".join(provider_cards)}\n</div>\n\n'
        + (f'{price_movement_html}\n\n' if price_movement_html else "")
        + tiers.primary
    )

    return _render_html_page(
        title=f"Model Sentinel \u2014 {to_local_human(generated_at)}",
        header_html=header_html,
        body_html=body_html,
        tail_html=_render_scan_disclosure(
            tiers,
            _build_html_summary_table(
                summary_entries, concise=True, show_provider=contributing > 1
            ),
        ),
    )


# ---------------------------------------------------------------------------
# HTML changes report
# ---------------------------------------------------------------------------


def _render_changes_html(
    *,
    by_date: dict[str, dict[str, dict[str, list[dict[str, Any]]]]],
    display_labels: dict[str, str],
    provider_id: str | None,
    since: str | None,
    until: str | None,
    total_changes: int,
    provider_profiles: dict[str, ProviderProfile] | None = None,
    detail_policy: ReportDetailPolicy | None = None,
) -> str:
    h = html_module.escape
    detail_policy = detail_policy or make_report_detail_policy()

    scope_parts = []
    if provider_id:
        scope_parts.append(f"Provider: {provider_id}")
    if since:
        scope_parts.append(f"Since: {since}")
    if until:
        scope_parts.append(f"Until: {until}")
    meta_line = " &middot; ".join(h(p) for p in scope_parts) if scope_parts else "All providers"

    date_sections = []
    summary_entries: list[_SummaryEntry] = []

    for date_str, providers in by_date.items():
        # Provider blocks are built before the date heading is committed, so a
        # date whose every model was suppressed emits no section at all.
        provider_parts: list[str] = []
        for group_provider_id, models in providers.items():
            profile = (provider_profiles or {}).get(
                group_provider_id,
                GENERIC_PROFILE,
            )
            provider_plan = _plan_changes_report_provider(
                models,
                detail_policy,
                profile,
            )
            if provider_plan.renders_nothing:
                continue
            provider_label = display_labels.get(group_provider_id, group_provider_id)
            parts: list[str] = [f'<h3>{h(provider_label)}</h3>']
            added_models = []
            removed_models = []
            changed_entries = []
            for entry in provider_plan.entries:
                if entry.kind == "added":
                    added_models.append((entry.model_id, entry.display_name))
                    summary_entries.append(_presence_summary_entry(
                        category="Added", provider_label=provider_label,
                        model_id=entry.model_id, display_name=entry.display_name,
                    ))
                elif entry.kind == "removed":
                    removed_models.append((entry.model_id, entry.display_name))
                    summary_entries.append(_presence_summary_entry(
                        category="Removed", provider_label=provider_label,
                        model_id=entry.model_id, display_name=entry.display_name,
                    ))
                else:
                    changed_entries.append(entry)

            if added_models:
                parts.append('<ul class="model-list added-list">')
                for mid, dname in added_models:
                    parts.append(f'<li><code>{h(mid)}</code> <span class="display-name">{h(dname)}</span></li>')
                parts.append('</ul>')
            if removed_models:
                parts.append('<ul class="model-list removed-list">')
                for mid, dname in removed_models:
                    parts.append(f'<li><code>{h(mid)}</code> <span class="display-name">{h(dname)}</span></li>')
                parts.append('</ul>')

            for entry in changed_entries:
                model_id, display_name = entry.model_id, entry.display_name
                plan = entry.display
                assert plan is not None  # `changed` entries always carry a plan

                # Model change card
                parts.append('<div class="model-card">')
                parts.append(
                    f'<div class="model-card-header"><code>{h(model_id)}</code>'
                    f'<span class="display-name">{h(display_name)}</span></div>'
                )
                grouped = _group_field_changes_for_detail(
                    plan.visible,
                    detail_policy,
                    profile,
                )
                for category, fcs in grouped:
                    parts.append(f'<div class="change-category"><div class="category-label">{h(category)}</div>')
                    _append_html_field_changes(parts, fcs, profile)
                    parts.append('</div>')
                _append_html_hidden_summary(parts, plan, model_ids=(model_id,))
                parts.append('</div>')

                # Summary entries
                summary_entries.extend(_build_summary_entries_from_fc(
                    provider_label=provider_label, model_id=model_id,
                    display_name=display_name, field_changes=list(plan.visible),
                    profile=profile,
                ))
            # Squelched changes are accounted for once per provider, from the
            # same rollup the body's squelched card is built from -- not once
            # per model, which double-counted against that card.
            squelched_entry = _squelched_summary_entry(
                provider_label=provider_label,
                squelched=provider_plan.rollups.squelched,
                policy=detail_policy,
            )
            if squelched_entry:
                summary_entries.append(squelched_entry)
            parts.extend(_hidden_rollup_cards(provider_plan.rollups, detail_policy))
            provider_parts.extend(parts)

        if not provider_parts:
            continue
        parts = [f'<h2 class="date-heading">{h(date_str)}</h2>', *provider_parts]
        date_sections.append('<section class="provider-section">' + "\n".join(parts) + '</section>')

    header_html = (
        f'<header>\n'
        f'  <h1>Model Sentinel <span class="count">\u2014 Change Log</span></h1>\n'
        f'  <div class="meta">{meta_line} &middot; {total_changes} change{"s" if total_changes != 1 else ""}'
        f' across {len(by_date)} date{"s" if len(by_date) != 1 else ""}</div>\n'
        f'</header>'
    )

    return _render_html_page(
        title="Model Sentinel \u2014 Change Log",
        header_html=header_html,
        body_html="".join(date_sections),
        tail_html=_build_html_summary_table(summary_entries),
    )


# ---------------------------------------------------------------------------
# HTML component helpers
# ---------------------------------------------------------------------------


def _html_change_row(*, label: str, old_cell: str, new_cell: str, delta_cls: str, delta_cell: str) -> str:
    """Assemble one four-column change row. Cells arrive already escaped."""
    return (
        f'<tr><td class="field-name">{html_module.escape(label)}</td>'
        f'<td class="old-val">{old_cell}</td>'
        f'<td class="new-val">{new_cell}</td>'
        f'<td class="change-delta {delta_cls}">{delta_cell}</td></tr>'
    )


def _render_html_table_row(rendered: RenderedChange) -> str:
    """Format a classified change as one `<tr>` of the four-column change table.

    Pure formatter, mirroring `_render_change_text` branch for branch. `noop`
    entries never reach here -- E1 drops them once, in `_drop_noop_changes`.

    Every value cell goes through `_html_side_display`, the same helper the scan
    report's card uses, so an absent side reads `—` here too. Fix pass 2,
    finding 1: this renderer kept printing `null` while the Change Summary a few
    inches below it -- built by `_build_summary_entries_from_fc`, which both HTML
    documents share -- had started printing `—`, so the `changes` report
    contradicted itself. Escaping is applied AFTER the helper rather than before
    because `html.escape` leaves an em dash untouched, which lets one call site
    spell both outcomes.

    COLOUR COMES FROM `_card_semantic_class`, not from this function. Until fix
    pass 3 the branches below each picked their own class from a private
    `delta-increase`/`delta-decrease`/`delta-neutral` set whose meaning was
    DIRECTION, so this document painted a context window growing green, a max
    output shrinking red, and an informational scalar amber -- while the scan
    report's card, three files' worth of tests away, painted the same three
    changes amber, amber and dim. B1 says colour carries cost and nothing else,
    so the one table that maps a change onto a colour has to be the one table,
    and the direction-named classes are gone rather than left as a second
    vocabulary for a future branch to reach for. Only the delta TEXT is decided
    here; that genuinely differs between the two documents, because this table
    has one Change column where the card has separate delta and percent columns.
    """
    h = html_module.escape
    delta_cls = _card_semantic_class(rendered)

    if rendered.kind == "price":
        old_str = h(_html_raw_and_normalized(rendered.old_raw, rendered.old_display))
        new_str = h(_html_raw_and_normalized(rendered.new_raw, rendered.new_display))
        if rendered.direction in ("added", "removed"):
            delta_text = rendered.direction
        elif rendered.direction in ("up", "down"):
            delta_text = rendered.pct_display or ""
        else:
            delta_text = "\u2014"
        return _html_change_row(
            label=rendered.display_label,
            old_cell=old_str,
            new_cell=new_str,
            delta_cls=delta_cls,
            delta_cell=h(delta_text),
        )

    if rendered.kind == "count" and _is_one_sided(rendered):
        return _html_change_row(
            label=rendered.display_label,
            old_cell=h(_html_side_display(rendered.old_display, rendered.old_raw)),
            new_cell=h(_html_side_display(rendered.new_display, rendered.new_raw)),
            delta_cls=delta_cls,
            delta_cell=h(rendered.direction),
        )

    if rendered.kind in ("count", "numeric"):
        # Two-sided `count` renders exactly like `numeric` -- see the matching
        # note in _render_change_text and the count guard in change_render.py.
        # A zero basis means no percentage is defined, so the delta cell is
        # blank. It is no longer RE-COLOURED for that: `pct_basis_zero` says
        # the percentage is undefined, which is a fact about the arithmetic and
        # not about what kind of change this is, and the amber it used to force
        # collided with capacity's amber for a reason a reader could not see.
        return _html_change_row(
            label=rendered.display_label,
            old_cell=h(_html_side_display(rendered.old_display, rendered.old_raw)),
            new_cell=h(_html_side_display(rendered.new_display, rendered.new_raw)),
            delta_cls=delta_cls,
            delta_cell=h(rendered.pct_display or ""),
        )

    if rendered.kind == "boolean":
        # E2. Old/new carry `on`/`off` (or an em dash for the absent side of a
        # one-sided change); the delta column carries the pill -- `enabled`/
        # `disabled` for a toggle, `added`/`removed` for a one-sided change.
        # No percent branch exists, which is the point: `_pct_change` returns
        # "" for a zero basis, so the old numeric path left this cell blank on
        # every `0 -> 1` flag.
        return _html_change_row(
            label=rendered.display_label,
            old_cell=h(_html_side_display(rendered.old_display, rendered.old_raw)),
            new_cell=h(_html_side_display(rendered.new_display, rendered.new_raw)),
            delta_cls=delta_cls,
            delta_cell=h(rendered.delta_display or ""),
        )

    return _html_change_row(
        label=rendered.display_label,
        old_cell=h(_html_side_display(rendered.old_display, rendered.old_raw)),
        new_cell=h(_html_side_display(rendered.new_display, rendered.new_raw)),
        delta_cls=delta_cls,
        delta_cell="\u2014",
    )


def _html_list_members(rendered: RenderedChange, *, separator: str = "\n") -> str:
    """The `+ member` / `- member` blocks of a list change.

    THE spelling of a changed list member in HTML, shared by the standalone
    list-diff block (`changes` report, provider rollups) and the model card's
    list row. Two copies would be two places for the glyphs, the escaping and
    the added-before-removed order to drift.
    """
    h = html_module.escape
    parts: list[str] = []
    if rendered.list_added:
        parts.append('<div class="list-added">')
        parts.extend(f'&nbsp;&nbsp;+ {h(item)}' for item in rendered.list_added)
        parts.append('</div>')
    if rendered.list_removed:
        parts.append('<div class="list-removed">')
        parts.extend(f'&nbsp;&nbsp;\u2212 {h(item)}' for item in rendered.list_removed)
        parts.append('</div>')
    return separator.join(parts)


def _render_html_list_diff(rendered: RenderedChange) -> str:
    h = html_module.escape
    parts = ['<div class="list-diff">']
    parts.append(f'<span class="field-name">{h(rendered.display_label)}</span> ')
    # old_display/new_display carry the raw member counts for `list` changes.
    parts.append(f'<span class="list-count">({rendered.old_display} \u2192 {rendered.new_display})</span>')
    members = _html_list_members(rendered)
    if members:
        parts.append(members)
    parts.append('</div>')
    return "\n".join(parts)


def _render_html_bulk_list_diff(rendered: RenderedChange) -> str:
    # Reads RenderedChange, like every other renderer in this module -- see
    # _render_bulk_list_diff_text's docstring for what that unified.
    h = html_module.escape
    parts = [f'<div class="list-diff"><span class="field-name">{h(rendered.display_label)}</span>']
    members = _html_list_members(rendered)
    parts.append(members if members else '<div class="list-count">membership changed</div>')
    parts.append('</div>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Shared utility helpers
# ---------------------------------------------------------------------------


def _group_models_by_prefix(models: tuple[dict[str, Any], ...]) -> list[tuple[str | None, list[dict[str, Any]]]]:
    grouped: dict[str | None, list[dict[str, Any]]] = {}
    order: list[str | None] = []
    for row in models:
        model_id = row["provider_model_id"]
        prefix = model_id.split("/", 1)[0] if "/" in model_id else None
        if prefix not in grouped:
            grouped[prefix] = []
            order.append(prefix)
        grouped[prefix].append(row)
    return [(prefix, grouped[prefix]) for prefix in order]


def _render_inline_model_row(row: dict[str, Any]) -> list[str]:
    model_id = row["provider_model_id"]
    display_name = row["display_name"] or model_id
    lines = [f"- {model_id}"]
    if display_name != model_id:
        lines.append(f"    name:  {display_name}")
    price_summary = _format_price_pair(row)
    if price_summary != "n/a":
        lines.append(f"    price: {price_summary}")
    cache_summary = _format_cache_prices(row)
    if cache_summary:
        lines.append(f"    cache: {cache_summary}")
    lines.append(f"    first: {_short_ts(row['first_seen'])}")
    lines.append(f"    last:  {_short_ts(row['last_seen'])}")
    lines.append("")
    return lines


def _short_ts(value: Any) -> str:
    return to_local_human(value)


def _format_number(value: Any) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return format(numeric, "g")


def _format_price_pair(row: dict[str, Any]) -> str:
    input_price = _format_price_value(row.get("input_price"))
    output_price = _format_price_value(row.get("output_price"))
    if not input_price and not output_price:
        return "n/a"
    return f"{input_price or '?'} / {output_price or '?'}"


def _format_cache_prices(row: dict[str, Any]) -> str:
    read_price = _format_price_value(row.get("cache_read_price"))
    write_price = _format_price_value(row.get("cache_write_price"))
    if not read_price and not write_price:
        return ""
    return f"{read_price or '?'} / {write_price or '?'}"


def _normalize_latest_model_json(latest_model: dict[str, Any] | None) -> dict[str, Any] | None:
    if latest_model is None:
        return None
    return {
        **latest_model,
        "completed_at": to_local_iso(latest_model.get("completed_at")),
    }


def _format_price_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return format(numeric, "g")
