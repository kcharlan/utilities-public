from __future__ import annotations

import fnmatch
import html as html_module
import json
from collections import OrderedDict, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Literal

# Renderers in this module are pure formatters over `RenderedChange`: they call
# `classify_change` once per field change and format the result, instead of
# re-deriving price/count/numeric/list classification per output format.
#
# `_classify_field`, `_is_price_amount_field`, and `_numeric_value` are still
# called directly here -- by the category grouping helpers and by
# `_price_movement_kind`, neither of which is a per-field renderer -- so they
# stay imported (and therefore re-exported for external call sites that
# imported them from reporting.py before the move to change_render.py). The
# six other primitives that moved (`_both_numeric`, `_fmt_int`,
# `_fmt_price_per_m`, `_is_count_field`, `_normalize_price`, `_pct_change`)
# had no remaining call site here once the renderers were rewired, so their
# transitional re-export shims were dropped; import those from
# `model_sentinel.change_render` directly.
from .change_render import (
    RenderedChange,
    _classify_field,
    _is_price_amount_field,
    _numeric_value,
    _scalar_display,
    classify_change,
)
from .models import FieldChange, HistoryEvent, ModelDelta, ProviderScanResult
from .time_utils import to_local_human, to_local_iso

REPORT_DETAIL_MODES = ("default", "all", "squelched")
BULK_CHANGE_MIN_MODELS = 3

_PRICING_OVERRIDE_CONDITION_FIELDS = (
    "min_prompt_tokens",
    "utc_start",
    "utc_end",
)

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


@dataclass(frozen=True)
class _ProviderChangePlan:
    planned: tuple[_PlannedModelChange, ...]
    items: tuple[_PlannedModelChange | _BulkChangeGroup, ...]


@dataclass(frozen=True)
class _SummaryEntry:
    category: str
    provider: str
    model_id: str
    field: str
    detail: str
    grouped_model_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PriceMovementModel:
    provider_id: str
    provider_label: str
    provider_model_id: str
    higher: int
    lower: int
    added: int
    removed: int

    @property
    def bucket(self) -> Literal["higher", "lower", "mixed", "coverage"]:
        if self.higher and self.lower:
            return "mixed"
        if self.higher:
            return "higher"
        if self.lower:
            return "lower"
        return "coverage"


@dataclass(frozen=True)
class _PriceMovementSummary:
    models: tuple[_PriceMovementModel, ...]

    def models_in(self, bucket: Literal["higher", "lower", "mixed", "coverage"]) -> tuple[_PriceMovementModel, ...]:
        return tuple(model for model in self.models if model.bucket == bucket)

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


def _field_display_plan(
    field_changes: tuple[FieldChange, ...],
    policy: ReportDetailPolicy,
    *,
    unclassified_remaining: int | None = None,
) -> _FieldDisplayPlan:
    field_changes = _expand_structured_field_changes(field_changes)
    if policy.mode == "all":
        return _FieldDisplayPlan(field_changes, (), (), (), 0)

    filtered = filter_field_changes_for_detail(field_changes, policy)
    if policy.mode == "squelched":
        visible = tuple(fc for fc in field_changes if fc in filtered.squelched)
        hidden = tuple(fc for fc in field_changes if fc not in filtered.squelched)
        return _FieldDisplayPlan(visible, (), (), hidden, 0)

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
    )


def _expand_structured_field_changes(
    field_changes: tuple[FieldChange, ...],
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
        expanded.extend(_expand_structured_field_change(field_change))
    return tuple(expanded)


def _expand_structured_field_change(field_change: FieldChange) -> tuple[FieldChange, ...]:
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
) -> tuple[FieldChange, ...] | None:
    """Compare conditional-pricing tiers without treating dictionaries as list members.

    OpenRouter identifies conditional pricing entries by fields such as a prompt-token
    threshold or UTC window. Match unique entries on those conditions so reordering does
    not create noise. If the payload cannot be matched safely, return ``None`` and let
    the existing full-list fallback preserve the upstream values.
    """
    old_by_identity = _index_pricing_overrides(old_value)
    new_by_identity = _index_pricing_overrides(new_value)
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
) -> dict[tuple[tuple[str, Any], ...], dict[str, Any]] | None:
    indexed: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            return None
        identity = tuple(
            (field, item[field])
            for field in _PRICING_OVERRIDE_CONDITION_FIELDS
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
    condition = ",".join(f"{key}={_render_value(value)}" for key, value in identity)
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
    old_values = {_list_item_text(value) for value in field_change.old_value}
    new_values = {_list_item_text(value) for value in field_change.new_value}
    return (
        field_change.field_name,
        tuple(sorted(new_values - old_values)),
        tuple(sorted(old_values - new_values)),
    )


def _list_item_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    return str(value)


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
) -> _ProviderChangePlan:
    planned: list[_PlannedModelChange] = []
    unclassified_remaining = policy.unclassified_limit
    for delta in changed:
        display = _field_display_plan(
            delta.field_changes,
            policy,
            unclassified_remaining=unclassified_remaining,
        )
        unclassified_remaining = max(0, unclassified_remaining - display.unclassified_used)
        planned.append(_PlannedModelChange(delta, display))

    if policy.mode != "default":
        return _ProviderChangePlan(tuple(planned), tuple(planned))

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
    return _ProviderChangePlan(tuple(planned), tuple(items))


def _has_hidden_details(plan: _FieldDisplayPlan) -> bool:
    return bool(plan.squelched or plan.hidden_unclassified or plan.hidden_non_squelched)


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


def _field_changes_from_change_rows(model_changes: list[dict[str, Any]]) -> tuple[FieldChange, ...]:
    field_changes = []
    for change in model_changes:
        fn = change.get("field_name")
        if fn:
            field_changes.append(FieldChange(fn, change["old_value"], change["new_value"]))
    return tuple(field_changes)


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
) -> list[tuple[str, list[FieldChange]]]:
    grouped: dict[str, list[FieldChange]] = defaultdict(list)
    category_order = [*_CATEGORY_ORDER]
    if "Unclassified" not in category_order:
        category_order.append("Unclassified")
    for fc in field_changes:
        category = _classify_field(fc.field_name)
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
                f"{_render_value(event.old_value)} | {_render_value(event.new_value)} |"
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
            f"{event.field_name or ''} {_render_value(event.old_value)} -> {_render_value(event.new_value)}"
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


def render_changes_report(
    *,
    format_name: str,
    provider_id: str | None,
    since: str | None,
    until: str | None,
    changes: tuple[dict[str, Any], ...],
    provider_pricing: dict[str, tuple[int, int]] | None = None,
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

    # Group by detected_at date, then provider, then model
    by_date: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = OrderedDict()
    for change in changes:
        date_str = to_local_human(change["detected_at"]).split(" ")[0] if change["detected_at"] else "unknown"
        provider = change["provider_label"]
        model = change["provider_model_id"]
        by_date.setdefault(date_str, OrderedDict()).setdefault(provider, OrderedDict()).setdefault(model, []).append(change)

    if format_name == "html":
        return _render_changes_html(
            by_date=by_date,
            provider_id=provider_id,
            since=since,
            until=until,
            total_changes=len(changes),
            provider_pricing=provider_pricing,
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
        lines.append(f"  {date_str}")
        lines.append(f"  {'-' * 40}")
        for provider_label, models in providers.items():
            lines.append(f"    {provider_label}")
            hidden_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
            hidden_non_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
            unclassified_remaining = detail_policy.unclassified_limit
            for model_id, model_changes in models.items():
                display_name = model_changes[0].get("display_name", model_id)
                kind = model_changes[0]["change_kind"]
                if kind == "added":
                    lines.append(f"      + {model_id} ({display_name})")
                elif kind == "removed":
                    lines.append(f"      - {model_id} ({display_name})")
                else:
                    field_changes = _field_changes_from_change_rows(model_changes)
                    plan = _field_display_plan(
                        field_changes,
                        detail_policy,
                        unclassified_remaining=unclassified_remaining,
                    )
                    unclassified_remaining = max(0, unclassified_remaining - plan.unclassified_used)
                    if plan.squelched:
                        hidden_squelched.append((model_id, plan.squelched))
                    if plan.hidden_non_squelched:
                        hidden_non_squelched.append((model_id, plan.hidden_non_squelched))
                    if not plan.visible and not _has_hidden_details(plan):
                        continue
                    lines.append(f"      * {model_id} ({display_name})")
                    pm, pd = 1, 1
                    if provider_pricing:
                        pid = model_changes[0].get("provider_id", "")
                        pm, pd = provider_pricing.get(pid, (1, 1))
                    grouped = _group_field_changes_for_detail(plan.visible, detail_policy)
                    for category, fcs in grouped:
                        if len(grouped) > 1 or category == "Unclassified":
                            lines.append(f"          [{category}]")
                            indent = "            "
                        else:
                            indent = "          "
                        for fc in fcs:
                            lines.append(f"{indent}{_render_smart_change_text(fc, pm, pd)}")
                    lines.extend(_hidden_change_summary_lines(plan, indent="          ", model_ids=(model_id,)))
            lines.extend(_provider_hidden_summary_lines("squelched", hidden_squelched, detail_policy, indent="      "))
            lines.extend(_provider_hidden_summary_lines("non-squelched", hidden_non_squelched, detail_policy, indent="      "))
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


def _group_field_changes(field_changes: tuple[FieldChange, ...]) -> list[tuple[str, list[FieldChange]]]:
    grouped: dict[str, list[FieldChange]] = defaultdict(list)
    for fc in field_changes:
        grouped[_classify_field(fc.field_name)].append(fc)
    return [(cat, grouped[cat]) for cat in _CATEGORY_ORDER if cat in grouped]


def _price_movement_kind(
    field_change: FieldChange,
) -> Literal["higher", "lower", "added", "removed"] | None:
    if not _is_price_amount_field(field_change.field_name):
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


def _collect_price_movement_summary(
    planned_results: list[tuple[ProviderScanResult, _ProviderChangePlan]],
) -> _PriceMovementSummary:
    counts: dict[tuple[str, str], dict[str, int]] = {}
    identities: dict[tuple[str, str], tuple[str, str, str]] = {}

    for result, provider_plan in planned_results:
        for item in provider_plan.planned:
            key = (result.provider_id, item.delta.provider_model_id)
            for field_change in item.display.visible:
                movement = _price_movement_kind(field_change)
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

    models = []
    for key, model_counts in counts.items():
        provider_id, provider_label, provider_model_id = identities[key]
        models.append(
            _PriceMovementModel(
                provider_id=provider_id,
                provider_label=provider_label,
                provider_model_id=provider_model_id,
                higher=model_counts["higher"],
                lower=model_counts["lower"],
                added=model_counts["added"],
                removed=model_counts["removed"],
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


def _is_one_sided(rendered: RenderedChange) -> bool:
    """Whether only one side of a price/count change carries a value.

    `classify_change` records that as `direction="added"`/`"removed"`; the
    two-sided forms always use `up`/`down`/`none`.
    """
    return rendered.direction in ("added", "removed")


def _render_smart_change_text(fc: FieldChange, price_multiplier: int = 1, price_divisor: int = 1) -> str:
    return _render_change_text(
        classify_change(fc, price_multiplier=price_multiplier, price_divisor=price_divisor)
    )


def _render_change_text(rendered: RenderedChange) -> str:
    """Format a classified change as one plain-text line.

    Pure formatter: every classification decision was already made by
    `classify_change`. `noop` entries are NOT suppressed here -- suppression
    is a later, deliberate change with its own golden updates.
    """
    if rendered.kind == "list":
        return _render_list_diff_text(rendered)

    if rendered.kind == "price":
        if _is_one_sided(rendered):
            # `old_raw is None` <=> that side was absent; the price guard in
            # classify_change rejects a present-but-non-numeric side, so the
            # two conditions cannot come apart here.
            old_hint = "null" if rendered.old_raw is None else f"{rendered.old_raw} ({rendered.old_display} / 1M)"
            new_hint = "null" if rendered.new_raw is None else f"{rendered.new_raw} ({rendered.new_display} / 1M)"
            return f"{rendered.label}: {old_hint} \u2192 {new_hint}"
        price_hint = f"{rendered.old_display} \u2192 {rendered.new_display} / 1M"
        suffix = f", {rendered.pct_display}" if rendered.pct_display else ""
        return f"{rendered.label}: {rendered.old_raw} \u2192 {rendered.new_raw} ({price_hint}{suffix})"

    if rendered.kind in ("count", "numeric"):
        # A two-sided `count` is rendered EXACTLY like `numeric` -- same
        # `(+delta, pct)` suffix and no `tok` unit. classify_change routes
        # two-sided count fields (e.g. context_length) to `count` where the
        # renderer this replaced routed them to its numeric branch; see the
        # count guard comment in change_render.py. Emitting `unit` here, or
        # giving `count` its own suffix, would silently change output.
        if _is_one_sided(rendered):
            return f"{rendered.label}: {rendered.old_display} \u2192 {rendered.new_display}"
        body = f"{rendered.label}: {rendered.old_display} \u2192 {rendered.new_display}"
        if rendered.pct_display:
            return f"{body} ({rendered.delta_display}, {rendered.pct_display})"
        return f"{body} ({rendered.delta_display})"

    if rendered.kind == "boolean":
        old_sym = "\u2713" if rendered.old_display == "on" else "\u2717"
        new_sym = "\u2713" if rendered.new_display == "on" else "\u2717"
        return f"{rendered.label}: {old_sym} \u2192 {new_sym}"

    # scalar and noop share the generic form. `old_display`/`new_display` are
    # produced by change_render._scalar_display, which matches _render_value.
    return f"{rendered.label}: {rendered.old_display} \u2192 {rendered.new_display}"


def _render_list_diff_text(rendered: RenderedChange) -> str:
    parts = []
    if rendered.list_added:
        parts.append(", ".join(f"+{item}" for item in rendered.list_added))
    if rendered.list_removed:
        parts.append(", ".join(f"-{item}" for item in rendered.list_removed))
    # old_display/new_display carry the raw member counts for `list` changes.
    count_str = f"({rendered.old_display} \u2192 {rendered.new_display})"
    if parts:
        return f"{rendered.label}: {'; '.join(parts)} {count_str}"
    return f"{rendered.label}: {count_str}"


def _render_bulk_list_diff_text(fc: FieldChange) -> str:
    """Format a bulk-grouped list membership change.

    NOT routed through `RenderedChange.list_added`/`list_removed`, unlike the
    per-model list renderers. Bulk grouping keys models by
    `_list_change_signature`, which stringifies members through
    `_list_item_text` (JSON for dict/list members); `classify_change`'s list
    branch uses plain `str(x)`. For a list of dicts the two disagree
    (`{"a": 1}` vs `{'a': 1}`), so switching here would change output for
    bulk groups over structured lists. The group card must also keep showing
    the exact membership its grouping key was computed from.

    MEASURED (task 3b): unifying the two conventions on `_list_item_text` --
    i.e. changing `classify_change`'s list branch to JSON-encode dict/list
    members -- is NOT behavior-neutral. It changes three of the eight goldens
    in tests/test_render_characterization.py
    (`test_characterization_{text,markdown,html}_detail_all`), because that
    module's `benchmarks.example_suite` case is a two-sided list of dicts and
    its goldens pin today's `str(x)` spelling `{'score': 2}`. Unifying in the
    other direction (`_list_item_text` -> `str(x)`) leaves those goldens
    intact but changes bulk output instead, and additionally re-keys
    `_bulk_change_signature`. Either direction is a deliberate, user-visible
    output change that needs golden updates in both characterization modules;
    it is NOT something to slip into a refactor billed as neutral. Both
    spellings are pinned side by side in
    tests/test_render_bulk_characterization.py.
    """
    field_name, added, removed = _list_change_signature(fc)
    operations = [*(f"+{item}" for item in added), *(f"-{item}" for item in removed)]
    return f"{field_name}: {'; '.join(operations) if operations else 'membership changed'}"


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
    *,
    indent: str,
) -> list[str]:
    model_ids = tuple(sorted(group.model_ids))
    lines = [
        f"{indent}* Bulk change — {len(model_ids)} models",
        f"{indent}  models: {_format_model_list(model_ids, limit=12)}",
    ]
    grouped = _group_field_changes_for_detail(group.visible, policy)
    for category, changes in grouped:
        lines.append(f"{indent}  [{category}]")
        for field_change in changes:
            lines.append(f"{indent}    {_render_bulk_list_diff_text(field_change)}")

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


def _bulk_group_markdown_lines(group: _BulkChangeGroup, policy: ReportDetailPolicy) -> list[str]:
    model_ids = tuple(sorted(group.model_ids))
    lines = [
        f"- **Bulk change — {len(model_ids)} models**",
        f"  - Models: `{_format_model_list(model_ids, limit=12)}`",
    ]
    for category, changes in _group_field_changes_for_detail(group.visible, policy):
        lines.append(f"  - **{category}**")
        for field_change in changes:
            lines.append(f"    - `{_render_bulk_list_diff_text(field_change)}`")
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
        lines.append(f"  changed: {len(result.changed)}")
        provider_plan = _plan_provider_changes(result.changed, detail_policy)
        hidden_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
        hidden_non_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
        for item in provider_plan.planned:
            delta, plan = item.delta, item.display
            if plan.squelched:
                hidden_squelched.append((delta.provider_model_id, plan.squelched))
            if plan.hidden_non_squelched:
                hidden_non_squelched.append((delta.provider_model_id, plan.hidden_non_squelched))
        for item in provider_plan.items:
            if isinstance(item, _BulkChangeGroup):
                lines.extend(_bulk_group_text_lines(item, detail_policy, indent="    "))
                continue
            delta, plan = item.delta, item.display
            if _is_squelched_only(plan):
                continue
            if not plan.visible and not _has_hidden_details(plan):
                continue
            lines.append(f"    * {delta.provider_model_id} ({delta.display_name})")
            if not plan.visible:
                lines.extend(_hidden_change_summary_lines(plan, indent="      ", model_ids=(delta.provider_model_id,)))
                continue
            grouped = _group_field_changes_for_detail(plan.visible, detail_policy)
            pm, pd = result.price_multiplier, result.price_divisor
            if len(grouped) == 1 and len(grouped[0][1]) == 1 and grouped[0][0] != "Unclassified":
                # Single change — no category header needed
                lines.append(f"      {_render_smart_change_text(grouped[0][1][0], pm, pd)}")
            else:
                for category, changes in grouped:
                    lines.append(f"      [{category}]")
                    for fc in changes:
                        lines.append(f"        {_render_smart_change_text(fc, pm, pd)}")
            lines.extend(_hidden_change_summary_lines(plan, indent="      ", model_ids=(delta.provider_model_id,)))
        lines.extend(_provider_hidden_summary_lines("squelched", hidden_squelched, detail_policy, indent="  "))
        lines.extend(_provider_hidden_summary_lines("non-squelched", hidden_non_squelched, detail_policy, indent="  "))
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
        lines.append(f"### Changed ({len(result.changed)})")
        lines.append("")
        if result.changed:
            provider_plan = _plan_provider_changes(result.changed, detail_policy)
            hidden_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
            hidden_non_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
            for item in provider_plan.planned:
                delta, plan = item.delta, item.display
                if plan.squelched:
                    hidden_squelched.append((delta.provider_model_id, plan.squelched))
                if plan.hidden_non_squelched:
                    hidden_non_squelched.append((delta.provider_model_id, plan.hidden_non_squelched))
            for item in provider_plan.items:
                if isinstance(item, _BulkChangeGroup):
                    lines.extend(_bulk_group_markdown_lines(item, detail_policy))
                    continue
                delta, plan = item.delta, item.display
                if _is_squelched_only(plan):
                    continue
                if not plan.visible and not _has_hidden_details(plan):
                    continue
                lines.append(f"- `{delta.provider_model_id}` - {delta.display_name}")
                for field_change in plan.visible:
                    lines.append(f"  - `{_render_smart_change_text(field_change, result.price_multiplier, result.price_divisor)}`")
                if plan.squelched:
                    lines.append(f"  - Squelched: `{len(plan.squelched)}` field change(s) hidden by report detail policy")
                if plan.hidden_unclassified:
                    lines.append(
                        f"  - Unclassified: `{len(plan.hidden_unclassified)}` additional field change(s) hidden; "
                        "add patterns to show_fields or squelch_fields"
                    )
                if plan.hidden_non_squelched:
                    lines.append(f"  - Filtered: `{len(plan.hidden_non_squelched)}` non-squelched field change(s) omitted")
            lines.extend(_provider_hidden_summary_markdown("squelched", hidden_squelched, detail_policy))
            lines.extend(_provider_hidden_summary_markdown("non-squelched", hidden_non_squelched, detail_policy))
        else:
            lines.append("- None")
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
  margin-bottom: 0.65rem;
}
.price-movement-title .outcome {
  font-weight: 400;
}
.price-movement-model-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0;
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
.price-movement-model-summary > strong,
.price-movement-fields > strong {
  color: var(--text-bright);
  font-weight: 600;
  margin-right: 0.45rem;
}
.price-higher { color: var(--accent-red); }
.price-lower { color: var(--accent-green); }
.price-mixed { color: var(--accent-amber); }
.price-coverage { color: var(--accent-blue); }
.price-movement-fields {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.78rem;
  margin-top: 0.45rem;
}
.price-movement-model-summary span + span::before,
.price-movement-fields span + span::before {
  content: " · ";
  color: var(--text-dim);
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
  display: grid;
  grid-template-columns: minmax(90px, auto) 1fr;
  gap: 0.5rem;
  padding: 0.15rem 0;
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
.model-card-header {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-card-hover);
}
.model-card-header code {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  color: var(--accent-amber);
  font-weight: 600;
}
.model-card-header .display-name {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-left: 0.5rem;
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
.change-category {
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--border);
}
.change-category:last-child {
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
td.delta-decrease { color: var(--accent-red); }
td.delta-increase { color: var(--accent-green); }
td.delta-neutral { color: var(--accent-amber); }
td.delta-price-higher { color: var(--accent-red); }
td.delta-price-lower { color: var(--accent-green); }
td.delta-price-coverage { color: var(--accent-blue); }
.list-diff {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  padding: 0.35rem 0;
}
.list-added { color: var(--accent-green); }
.list-removed { color: var(--accent-red); }
.list-count { color: var(--text-dim); font-size: 0.8rem; }
.summary-section {
  margin-top: 2.5rem;
  border-top: 1px solid var(--border);
  padding-top: 1.5rem;
}
.summary-section h2 {
  font-family: var(--font-mono);
  font-size: 1.1rem;
  color: var(--text-bright);
  margin-bottom: 1rem;
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
.summary-table tr:nth-child(even) td {
  background: var(--bg-table-alt);
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


def _render_html_page(*, title: str, header_html: str, body_html: str, summary_html: str) -> str:
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
{summary_html}
<footer>Generated by Model Sentinel</footer>
</body>
</html>"""


def _build_html_summary_table(
    entries: list[_SummaryEntry],
) -> str:
    """Build the concise, selectively consolidated Change Summary."""
    if not entries:
        return ""
    h = html_module.escape
    rows = []
    for entry in sorted(entries, key=_summary_entry_sort_key):
        if entry.grouped_model_ids:
            model_list = "".join(f'<code>{h(model_id)}</code>' for model_id in entry.grouped_model_ids)
            model_cell = (
                f'<details class="summary-models"><summary>{len(entry.grouped_model_ids)} models</summary>'
                f'<div class="summary-model-list">{model_list}</div></details>'
            )
        else:
            model_cell = f'<code>{h(entry.model_id)}</code>'
        if entry.field:
            rows.append(
                f'<tr>'
                f'<td>{h(entry.category)}</td>'
                f'<td>{h(entry.provider)}</td>'
                f'<td>{model_cell}</td>'
                f'<td>{h(entry.field)}</td>'
                f'<td>{h(entry.detail)}</td>'
                f'</tr>'
            )
        else:
            rows.append(
                f'<tr><td>{h(entry.category)}</td><td>{h(entry.provider)}</td>'
                f'<td>{model_cell}</td>'
                f'<td colspan="2">{h(entry.detail)}</td></tr>'
            )
    return (
        '<section class="summary-section">'
        '<h2>Change Summary</h2>'
        '<table class="summary-table">'
        '<thead><tr><th>Category</th><th>Provider</th><th>Model</th><th>Field</th><th>Change</th></tr></thead>'
        '<tbody>' + "\n".join(rows) + '</tbody>'
        '</table></section>'
    )


def _summary_entry_sort_key(entry: _SummaryEntry) -> tuple[int, str, str, str, str]:
    return (
        _SUMMARY_CATEGORY_RANK.get(entry.category, len(_SUMMARY_CATEGORY_RANK)),
        entry.provider.casefold(),
        entry.model_id.casefold(),
        entry.field.casefold(),
        entry.detail.casefold(),
    )


def _build_summary_entries_from_fc(
    *,
    provider_label: str,
    model_id: str,
    display_name: str,
    field_changes: list[FieldChange],
    price_multiplier: int,
    price_divisor: int,
) -> list[_SummaryEntry]:
    """Build summary entry tuples for field-changed models."""
    entries = []
    for fc in field_changes:
        rendered = classify_change(fc, price_multiplier=price_multiplier, price_divisor=price_divisor)
        category = _classify_field(rendered.field_path)
        # Split the already-formatted line rather than assuming the label never
        # contains ": " -- dynamic paths such as
        # `pricing.overrides[min_prompt_tokens=200000].completion` are built
        # from provider payload values.
        change_desc = _render_change_text(rendered).split(": ", 1)
        field_part = change_desc[0] if len(change_desc) > 1 else rendered.label
        detail_part = change_desc[1] if len(change_desc) > 1 else change_desc[0]
        entries.append(_SummaryEntry(category, provider_label, model_id, field_part, detail_part))
    return entries


def _render_html_model_changes(
    delta: ModelDelta,
    price_multiplier: int = 1,
    price_divisor: int = 1,
    detail_policy: ReportDetailPolicy | None = None,
    unclassified_remaining: int | None = None,
    display_plan: _FieldDisplayPlan | None = None,
) -> tuple[str, _FieldDisplayPlan]:
    h = html_module.escape
    policy = detail_policy or make_report_detail_policy()
    plan = display_plan or _field_display_plan(
        delta.field_changes,
        policy,
        unclassified_remaining=unclassified_remaining,
    )
    parts = [
        '<div class="model-card">',
        f'<div class="model-card-header"><code>{h(delta.provider_model_id)}</code>'
        f'<span class="display-name">{h(delta.display_name)}</span></div>',
    ]

    grouped = _group_field_changes_for_detail(plan.visible, policy)
    for category, changes in grouped:
        parts.append(f'<div class="change-category"><div class="category-label">{h(category)}</div>')
        _append_html_field_changes(parts, changes, price_multiplier, price_divisor)
        parts.append('</div>')
    _append_html_hidden_summary(parts, plan, model_ids=(delta.provider_model_id,))

    parts.append('</div>')
    return "\n".join(parts), plan


def _html_model_details(label: str, model_ids: tuple[str, ...], *, preview_limit: int = 8) -> str:
    h = html_module.escape
    sorted_ids = tuple(sorted(model_ids))
    model_list = "".join(f'<code>{h(model_id)}</code>' for model_id in sorted_ids)
    return (
        f'<details class="bulk-models"><summary>{h(label)}: '
        f'{h(_format_model_list(sorted_ids, limit=preview_limit))}</summary>'
        f'<div class="bulk-model-list">{model_list}</div></details>'
    )


def _render_html_bulk_changes(group: _BulkChangeGroup, policy: ReportDetailPolicy) -> str:
    parts = [
        '<div class="model-card bulk-change-card">',
        f'<div class="model-card-header"><code>Bulk change — {len(group.members)} models</code></div>',
        _html_model_details("Models", group.model_ids, preview_limit=12),
    ]
    for category, changes in _group_field_changes_for_detail(group.visible, policy):
        parts.append(f'<div class="change-category"><div class="category-label">{html_module.escape(category)}</div>')
        for field_change in changes:
            parts.append(_render_html_bulk_list_diff(field_change))
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
    price_multiplier: int,
    price_divisor: int,
) -> None:
    """Append HTML for a group of field changes (table rows + list diffs) to parts."""
    rendered_changes = [
        classify_change(fc, price_multiplier=price_multiplier, price_divisor=price_divisor)
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


_PRICE_MOVEMENT_BUCKETS = (
    ("higher", "\u2191 Higher, no decreases", "with increases and no decreases", "price-higher"),
    ("lower", "\u2193 Lower, no increases", "with decreases and no increases", "price-lower"),
    ("mixed", "\u2195 Mixed directions", "mixed", "price-mixed"),
    ("coverage", "Fields added/removed only", "with fields added/removed only", "price-coverage"),
)


def _price_movement_outcome(summary: _PriceMovementSummary) -> tuple[str, str]:
    if summary.higher_fields and summary.lower_fields:
        if summary.higher_fields > summary.lower_fields:
            return "mostly higher", "price-higher"
        if summary.lower_fields > summary.higher_fields:
            return "mostly lower", "price-lower"
        return "mixed", "price-mixed"
    if summary.higher_fields:
        return "higher", "price-higher"
    if summary.lower_fields:
        return "lower", "price-lower"
    return "price fields added/removed", "price-coverage"


def _render_html_price_movement_summary(summary: _PriceMovementSummary) -> str:
    if not summary.models:
        return ""

    h = html_module.escape
    model_summary_parts = []
    group_parts = []
    populated_buckets = [
        (bucket, group_label, summary_label, css_class, summary.models_in(bucket))
        for bucket, group_label, summary_label, css_class in _PRICE_MOVEMENT_BUCKETS
        if summary.models_in(bucket)
    ]
    populated_buckets.sort(key=lambda item: -len(item[4]))
    for _, group_label, summary_label, css_class, models in populated_buckets:
        model_summary_parts.append(
            f'<span class="{css_class}">{len(models)} {h(summary_label)}</span>'
        )
        model_rows = "".join(
            f'<div class="price-movement-model">'
            f'<span class="price-movement-provider">{h(model.provider_label)}</span>'
            f'<code>{h(model.provider_model_id)}</code></div>'
            for model in models
        )
        group_parts.append(
            f'<div class="price-movement-group">'
            f'<div class="price-movement-group-label {css_class}">{h(group_label)} \u2014 {len(models)}</div>'
            f'{model_rows}</div>'
        )

    model_suffix = "" if len(summary.models) == 1 else "s"
    field_counts = (
        ("higher", summary.higher_fields, "price-higher"),
        ("lower", summary.lower_fields, "price-lower"),
    )
    if summary.lower_fields > summary.higher_fields:
        field_counts = tuple(reversed(field_counts))
    field_counts += (
        ("added", summary.added_fields, "price-coverage"),
        ("removed", summary.removed_fields, "price-coverage"),
    )
    field_parts = [
        f'<span class="{css_class}">{count} {label}</span>'
        for label, count, css_class in field_counts
        if count
    ]
    field_total = (
        summary.higher_fields
        + summary.lower_fields
        + summary.added_fields
        + summary.removed_fields
    )
    field_suffix = "" if field_total == 1 else "s"
    outcome, outcome_class = _price_movement_outcome(summary)
    return (
        '<section class="price-movement-summary">'
        f'<div class="price-movement-title">Price Movement '
        f'<span class="outcome {outcome_class}">\u2014 {h(outcome)}</span></div>'
        f'<div class="price-movement-model-summary"><strong>{len(summary.models)} affected model{model_suffix}:</strong>'
        f'{"".join(model_summary_parts)}</div>'
        f'<div class="price-movement-fields"><strong>{field_total} changed price field{field_suffix}:</strong>'
        f'{"".join(field_parts)}</div>'
        f'<details class="price-movement-models"><summary>View {len(summary.models)} affected model{model_suffix}</summary>'
        f'<div class="price-movement-model-groups">{"".join(group_parts)}</div>'
        '</details></section>'
    )


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
    total_changes = sum(r.change_count for r in provider_results)
    planned_results = [
        (result, _plan_provider_changes(result.changed, detail_policy))
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

    # Change detail sections
    change_sections = []
    for result, provider_plan in planned_results:
        if result.change_count == 0 and result.status != "error":
            continue
        section_parts = [f'<h2>{h(result.provider_label)} <span class="provider-id">({h(result.provider_id)})</span></h2>']
        if result.baseline:
            section_parts.append(
                f'<div class="baseline-info">Baseline: scrape {result.baseline.scrape_id} '
                f'at {h(to_local_human(result.baseline.completed_at))}</div>'
            )
        if result.error_message:
            section_parts.append(f'<div class="error-msg">{h(result.error_message)}</div>')
        if result.added:
            section_parts.append('<h3>Added</h3><ul class="model-list added-list">')
            for delta in result.added:
                section_parts.append(f'<li><code>{h(delta.provider_model_id)}</code> <span class="display-name">{h(delta.display_name)}</span></li>')
            section_parts.append('</ul>')
        if result.removed:
            section_parts.append('<h3>Removed</h3><ul class="model-list removed-list">')
            for delta in result.removed:
                section_parts.append(f'<li><code>{h(delta.provider_model_id)}</code> <span class="display-name">{h(delta.display_name)}</span></li>')
            section_parts.append('</ul>')
        if result.changed:
            section_parts.append('<h3>Changed</h3>')
            hidden_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
            hidden_non_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
            for item in provider_plan.planned:
                delta, plan = item.delta, item.display
                if plan.squelched:
                    hidden_squelched.append((delta.provider_model_id, plan.squelched))
                if plan.hidden_non_squelched:
                    hidden_non_squelched.append((delta.provider_model_id, plan.hidden_non_squelched))
            for item in provider_plan.items:
                if isinstance(item, _BulkChangeGroup):
                    section_parts.append(_render_html_bulk_changes(item, detail_policy))
                    continue
                delta, plan = item.delta, item.display
                if not _is_squelched_only(plan) and (plan.visible or _has_hidden_details(plan)):
                    html, _ = _render_html_model_changes(
                        delta,
                        result.price_multiplier,
                        result.price_divisor,
                        detail_policy,
                        display_plan=plan,
                    )
                    section_parts.append(html)
            _append_html_provider_summary(section_parts, "squelched", hidden_squelched, detail_policy)
            _append_html_provider_summary(section_parts, "non-squelched", hidden_non_squelched, detail_policy)
        change_sections.append('<section class="provider-section">' + "\n".join(section_parts) + '</section>')

    # Summary entries
    summary_entries: list[_SummaryEntry] = []
    for result, provider_plan in planned_results:
        prov = result.provider_label
        pm, pd = result.price_multiplier, result.price_divisor
        for item in provider_plan.items:
            if isinstance(item, _BulkChangeGroup):
                for field_change in item.visible:
                    category = _classify_field(field_change.field_name)
                    rendered = _render_bulk_list_diff_text(field_change).split(": ", 1)
                    summary_entries.append(_SummaryEntry(
                        category,
                        prov,
                        f"Bulk change — {len(item.members)} models",
                        rendered[0],
                        rendered[1] if len(rendered) > 1 else "membership changed",
                        tuple(sorted(item.model_ids)),
                    ))
                continue
            delta, plan = item.delta, item.display
            if _is_squelched_only(plan):
                continue
            summary_entries.extend(_build_summary_entries_from_fc(
                provider_label=prov, model_id=delta.provider_model_id,
                display_name=delta.display_name, field_changes=list(plan.visible),
                price_multiplier=pm, price_divisor=pd,
            ))
        squelched_entries = [
            (item.delta.provider_model_id, item.display.squelched)
            for item in provider_plan.planned
            if item.display.squelched
        ]
        squelched_count, squelched_models = _summarize_field_changes(squelched_entries)
        if squelched_count:
            summary_entries.append(_SummaryEntry(
                "Squelched",
                prov,
                f"{len(squelched_models)} models",
                ", ".join(detail_policy.squelch_fields) or "no patterns",
                f"{squelched_count} field change{'s' if squelched_count != 1 else ''} hidden by report detail policy",
                squelched_models,
            ))
        for delta in result.added:
            summary_entries.append(_SummaryEntry("Added", prov, delta.provider_model_id, "", delta.display_name))
        for delta in result.removed:
            summary_entries.append(_SummaryEntry("Removed", prov, delta.provider_model_id, "", delta.display_name))

    suffix = "s" if total_changes != 1 else ""
    count_span = f'<span class="count">\u2014 {total_changes} change{suffix}</span>' if total_changes else ""
    header_html = (
        f'<header>\n'
        f'  <h1>Model Sentinel {count_span}</h1>\n'
        f'  <div class="meta">{timestamp} &middot; {h(command)}</div>\n'
        f'</header>'
    )
    price_movement_html = _render_html_price_movement_summary(
        _collect_price_movement_summary(planned_results)
    )
    body_html = (
        f'<div class="provider-cards">\n  {"".join(provider_cards)}\n</div>\n\n'
        + (f'{price_movement_html}\n\n' if price_movement_html else "")
        + "".join(change_sections)
    )

    return _render_html_page(
        title=f"Model Sentinel \u2014 {to_local_human(generated_at)}",
        header_html=header_html,
        body_html=body_html,
        summary_html=_build_html_summary_table(summary_entries),
    )


# ---------------------------------------------------------------------------
# HTML changes report
# ---------------------------------------------------------------------------


def _render_changes_html(
    *,
    by_date: dict[str, dict[str, dict[str, list[dict[str, Any]]]]],
    provider_id: str | None,
    since: str | None,
    until: str | None,
    total_changes: int,
    provider_pricing: dict[str, tuple[int, int]] | None = None,
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
    summary_entries: list[tuple[str, str, str, str, str]] = []

    for date_str, providers in by_date.items():
        parts = [f'<h2 class="date-heading">{h(date_str)}</h2>']
        for provider_label, models in providers.items():
            parts.append(f'<h3>{h(provider_label)}</h3>')
            added_models = []
            removed_models = []
            changed_models = []
            hidden_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
            hidden_non_squelched: list[tuple[str, tuple[FieldChange, ...]]] = []
            unclassified_remaining = detail_policy.unclassified_limit
            for model_id, model_changes in models.items():
                display_name = model_changes[0].get("display_name", model_id)
                kind = model_changes[0]["change_kind"]
                if kind == "added":
                    added_models.append((model_id, display_name))
                    summary_entries.append(("Added", provider_label, model_id, "", display_name))
                elif kind == "removed":
                    removed_models.append((model_id, display_name))
                    summary_entries.append(("Removed", provider_label, model_id, "", display_name))
                else:
                    changed_models.append((model_id, display_name, model_changes))

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

            for model_id, display_name, model_changes in changed_models:
                field_changes = _field_changes_from_change_rows(model_changes)
                if not field_changes:
                    continue
                pm, pd = 1, 1
                if provider_pricing:
                    pid = model_changes[0].get("provider_id", "")
                    pm, pd = provider_pricing.get(pid, (1, 1))
                plan = _field_display_plan(
                    field_changes,
                    detail_policy,
                    unclassified_remaining=unclassified_remaining,
                )
                unclassified_remaining = max(0, unclassified_remaining - plan.unclassified_used)
                if plan.squelched:
                    hidden_squelched.append((model_id, plan.squelched))
                if plan.hidden_non_squelched:
                    hidden_non_squelched.append((model_id, plan.hidden_non_squelched))
                if not plan.visible and not _has_hidden_details(plan):
                    continue

                # Model change card
                parts.append('<div class="model-card">')
                parts.append(
                    f'<div class="model-card-header"><code>{h(model_id)}</code>'
                    f'<span class="display-name">{h(display_name)}</span></div>'
                )
                grouped = _group_field_changes_for_detail(plan.visible, detail_policy)
                for category, fcs in grouped:
                    parts.append(f'<div class="change-category"><div class="category-label">{h(category)}</div>')
                    _append_html_field_changes(parts, fcs, pm, pd)
                    parts.append('</div>')
                _append_html_hidden_summary(parts, plan, model_ids=(model_id,))
                parts.append('</div>')

                # Summary entries
                summary_entries.extend(_build_summary_entries_from_fc(
                    provider_label=provider_label, model_id=model_id,
                    display_name=display_name, field_changes=list(plan.visible),
                    price_multiplier=pm, price_divisor=pd,
                ))
                if plan.squelched:
                    summary_entries.append((
                        "Squelched",
                        provider_label,
                        model_id,
                        "",
                        f"{len(plan.squelched)} field change(s) hidden by report detail policy",
                    ))
            _append_html_provider_summary(parts, "squelched", hidden_squelched, detail_policy)
            _append_html_provider_summary(parts, "non-squelched", hidden_non_squelched, detail_policy)

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
        summary_html=_build_html_summary_table(summary_entries),
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
    entries are NOT suppressed here.
    """
    h = html_module.escape

    if rendered.kind == "price":
        old_str = "null" if rendered.old_raw is None else h(f"{rendered.old_raw} ({rendered.old_display} / 1M)")
        new_str = "null" if rendered.new_raw is None else h(f"{rendered.new_raw} ({rendered.new_display} / 1M)")
        if rendered.direction == "added":
            delta_cls, delta_text = "delta-price-coverage", "added"
        elif rendered.direction == "removed":
            delta_cls, delta_text = "delta-price-coverage", "removed"
        elif rendered.direction == "up":
            delta_cls, delta_text = "delta-price-higher", rendered.pct_display or ""
        elif rendered.direction == "down":
            delta_cls, delta_text = "delta-price-lower", rendered.pct_display or ""
        else:
            delta_cls, delta_text = "delta-neutral", "\u2014"
        return _html_change_row(
            label=rendered.label,
            old_cell=old_str,
            new_cell=new_str,
            delta_cls=delta_cls,
            delta_cell=h(delta_text),
        )

    if rendered.kind == "count" and _is_one_sided(rendered):
        delta_cls, delta_text = (
            ("delta-increase", "added") if rendered.direction == "added" else ("delta-decrease", "removed")
        )
        return _html_change_row(
            label=rendered.label,
            old_cell=h(rendered.old_display),
            new_cell=h(rendered.new_display),
            delta_cls=delta_cls,
            delta_cell=delta_text,
        )

    if rendered.kind in ("count", "numeric"):
        # Two-sided `count` renders exactly like `numeric` -- see the matching
        # note in _render_change_text and the count guard in change_render.py.
        # A zero basis means no percentage is defined, so the delta cell is
        # blank and reads as neutral regardless of which way the value moved.
        # Read `pct_basis_zero` (the cause) rather than inferring it from
        # `pct_display is None` (a derived display signal that a later change
        # could blank for unrelated reasons).
        if rendered.pct_basis_zero:
            delta_cls = "delta-neutral"
        elif rendered.direction == "down":
            delta_cls = "delta-decrease"
        else:
            delta_cls = "delta-increase"
        return _html_change_row(
            label=rendered.label,
            old_cell=h(rendered.old_display),
            new_cell=h(rendered.new_display),
            delta_cls=delta_cls,
            delta_cell=h(rendered.pct_display or ""),
        )

    if rendered.kind == "boolean":
        old_sym = "\u2713" if rendered.old_display == "on" else "\u2717"
        new_sym = "\u2713" if rendered.new_display == "on" else "\u2717"
        return _html_change_row(
            label=rendered.label,
            old_cell=old_sym,
            new_cell=new_sym,
            delta_cls="delta-increase" if rendered.direction == "up" else "delta-decrease",
            delta_cell=new_sym,
        )

    return _html_change_row(
        label=rendered.label,
        old_cell=h(rendered.old_display),
        new_cell=h(rendered.new_display),
        delta_cls="delta-neutral",
        delta_cell="\u2014",
    )


def _render_html_list_diff(rendered: RenderedChange) -> str:
    h = html_module.escape
    parts = ['<div class="list-diff">']
    parts.append(f'<span class="field-name">{h(rendered.label)}</span> ')
    # old_display/new_display carry the raw member counts for `list` changes.
    parts.append(f'<span class="list-count">({rendered.old_display} \u2192 {rendered.new_display})</span>')
    if rendered.list_added:
        parts.append('<div class="list-added">')
        for item in rendered.list_added:
            parts.append(f'&nbsp;&nbsp;+ {h(item)}')
        parts.append('</div>')
    if rendered.list_removed:
        parts.append('<div class="list-removed">')
        for item in rendered.list_removed:
            parts.append(f'&nbsp;&nbsp;\u2212 {h(item)}')
        parts.append('</div>')
    parts.append('</div>')
    return "\n".join(parts)


def _render_html_bulk_list_diff(fc: FieldChange) -> str:
    # Reads _list_change_signature rather than RenderedChange for the same
    # reason as _render_bulk_list_diff_text -- see that docstring.
    h = html_module.escape
    field_name, added, removed = _list_change_signature(fc)
    parts = [f'<div class="list-diff"><span class="field-name">{h(field_name)}</span>']
    if added:
        parts.append('<div class="list-added">')
        parts.extend(f'&nbsp;&nbsp;+ {h(item)}' for item in added)
        parts.append('</div>')
    if removed:
        parts.append('<div class="list-removed">')
        parts.extend(f'&nbsp;&nbsp;− {h(item)}' for item in removed)
        parts.append('</div>')
    if not added and not removed:
        parts.append('<div class="list-count">membership changed</div>')
    parts.append('</div>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Shared utility helpers
# ---------------------------------------------------------------------------


# `_render_value` was a byte-identical copy of change_render._scalar_display.
# Keeping two bodies made silent drift between them a neutrality hazard: the
# rewired renderers emit RenderedChange.old_display/new_display for scalar and
# noop changes, and those are produced by _scalar_display, so the two MUST
# agree. Aliasing collapses them to one implementation instead of a convention.
# The name stays for the history-report and pricing-override-path call sites.
_render_value = _scalar_display


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
