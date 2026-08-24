from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from ..change_render import classify_change, resolve_price_rule
from ..config import ProviderConfig
from ..models import FieldChange
from ..normalize import profile_field_candidate
from ..provider_profiles import ProviderProfile
from ..reporting import (
    BULK_CHANGE_MIN_MODELS,
    REPORT_DETAIL_MODES,
    ReportDetailPolicy,
    detail_policy_from_settings,
    group_planned_entries_by_bulk,
    plan_changes_provider,
    visibility_of,
)
from ..storage import recent_change_rows
from ..time_utils import local_date_for
from . import queries
from .aspects import CATEGORIES, Aspect
from .readonly import ReadOnlyDatabase


PIN_LIMIT = 8
ASPECT_LIMIT = 12
_MISSING = object()


class BadRequest(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFound(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Common:
    providers: tuple[str, ...]
    since: date | None
    until: date | None
    detail: str


@dataclass
class ApiContext:
    db: ReadOnlyDatabase
    providers: tuple[ProviderConfig, ...]
    db_providers: tuple[dict[str, Any], ...]
    profiles: dict[str, ProviderProfile]
    settings: Any
    aspects: tuple[Aspect, ...]

    def policy_for(self, detail: str | None) -> ReportDetailPolicy:
        return detail_policy_from_settings(self.settings, mode=detail)

    def parse_common(self, params: Mapping[str, str]) -> Common:
        return parse_common(self, params)


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _date_param(params: Mapping[str, str], name: str) -> date | None:
    value = params.get(name)
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BadRequest(f"{name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise BadRequest(f"{name} must be YYYY-MM-DD")
    return parsed


def parse_common(ctx: ApiContext, params: Mapping[str, str]) -> Common:
    known = {str(row["provider_id"]) for row in ctx.db_providers} | {
        provider.provider_id for provider in ctx.providers
    }
    requested = _csv(params.get("providers"))
    if not requested:
        requested = tuple(provider.provider_id for provider in ctx.providers)
        if not requested:
            requested = tuple(sorted(known))
    for provider_id in requested:
        if provider_id not in known:
            raise BadRequest(f"unknown provider: {provider_id}")
    since = _date_param(params, "from")
    until = _date_param(params, "to")
    if since is not None and until is not None and since > until:
        raise BadRequest("from cannot be later than to")
    detail = params.get("detail") or getattr(ctx.settings, "report_detail", "default")
    if detail not in REPORT_DETAIL_MODES:
        raise BadRequest("detail must be one of default, all, squelched")
    return Common(tuple(dict.fromkeys(requested)), since, until, detail)


def _integer(
    params: Mapping[str, str], name: str, default: int, *, minimum: int = 1, maximum: int | None = None
) -> int:
    raw = params.get(name)
    try:
        value = default if raw in (None, "") else int(raw)
    except ValueError as exc:
        raise BadRequest(f"{name} must be an integer") from exc
    if value < minimum or maximum is not None and value > maximum:
        bound = f" between {minimum} and {maximum}" if maximum is not None else f" at least {minimum}"
        raise BadRequest(f"{name} must be{bound}")
    return value


def rendered_change_to_json(rendered: Any) -> dict[str, Any]:
    return asdict(rendered)


def _render_presence_change(
    *,
    model_id: str,
    kind: str,
    profile: ProviderProfile,
) -> dict[str, Any]:
    old_value = model_id if kind == "removed" else None
    new_value = model_id if kind == "added" else None
    rendered = classify_change(
        FieldChange("model_presence", old_value, new_value),
        profile=profile,
    )
    return rendered_change_to_json(
        replace(rendered, semantic="coverage", direction=kind)
    )


def meta(ctx: ApiContext, params: Mapping[str, str]) -> dict[str, Any]:
    configured = {provider.provider_id: provider for provider in ctx.providers}
    db_rows = {str(row["provider_id"]): row for row in ctx.db_providers}
    provider_ids = tuple(configured) + tuple(sorted(set(db_rows) - set(configured)))
    provider_rows = []
    for provider_id in provider_ids:
        provider = configured.get(provider_id)
        row = db_rows.get(provider_id)
        provider_rows.append(
            {
                "id": provider_id,
                "label": provider.label if provider is not None else row["label"],
                "kind": provider.kind if provider is not None else row["kind"],
                "enabled": provider.enabled if provider is not None else bool(row["enabled"]),
                "configured": provider is not None,
            }
        )
    span = queries.date_span(ctx.db.connection())
    return {
        "providers": provider_rows,
        "date_span": None if span is None else {"first": span[0].isoformat(), "last": span[1].isoformat()},
        "scrapes": [_json_scrape(scrape) for scrape in queries.list_scrapes(ctx.db.connection())],
        "aspects": [aspect.to_json() for aspect in ctx.aspects],
        "categories": list(CATEGORIES),
        "detail_default": getattr(ctx.settings, "report_detail", "default"),
        "pin_limit": PIN_LIMIT,
        "bulk_min_models": BULK_CHANGE_MIN_MODELS,
    }


def _rollup_json(
    plans: Sequence[tuple[Any, ProviderProfile]],
    *,
    models: set[str],
    categories: set[str],
    kinds: set[str],
) -> dict[str, list[list[Any]]]:
    result: dict[str, list[list[Any]]] = {}
    for name in ("squelched", "non_squelched", "noop"):
        counts: Counter[str] = Counter()
        if not kinds or "changed" in kinds:
            for plan, profile in plans:
                for model_id, changes in getattr(plan.rollups, name):
                    if models and model_id not in models:
                        continue
                    counts.update(
                        change.field_name
                        for change in changes
                        if not categories
                        or profile.categorize(change.field_name) in categories
                    )
        result[name] = [[field_name, count] for field_name, count in sorted(counts.items())]
    return result


def _display_fields(display: Any) -> tuple[FieldChange, ...]:
    if display is None:
        return ()
    return (
        *display.visible,
        *display.squelched,
        *display.hidden_unclassified,
        *display.hidden_non_squelched,
        *display.noop,
    )


def _count_hidden(
    entries: Sequence[Any],
    profile: ProviderProfile,
    categories: set[str],
) -> dict[str, int]:
    def selected(changes: Sequence[FieldChange]) -> int:
        return sum(
            1
            for change in changes
            if not categories or profile.categorize(change.field_name) in categories
        )

    return {
        "squelched": sum(selected(entry.display.squelched) for entry in entries if entry.display),
        "unclassified": sum(
            selected(entry.display.hidden_unclassified) for entry in entries if entry.display
        ),
        "noop": sum(selected(entry.display.noop) for entry in entries if entry.display),
    }


def _change_ids_by_rendered_change(
    changes: Sequence[FieldChange],
    rows: Sequence[dict[str, Any]],
) -> list[list[int]]:
    candidates: list[tuple[Any, list[int]]] = []
    for change in changes:
        exact_rows = [
            row
            for row in rows
            if row["field_name"] == change.field_name
            and _same_value(row["old_value"], change.old_value)
            and _same_value(row["new_value"], change.new_value)
        ]
        if exact_rows:
            key = (
                "exact",
                change.field_name,
                _canonical_value(change.old_value),
                _canonical_value(change.new_value),
            )
            matching_rows = exact_rows
        else:
            structural_rows = [
                row
                for row in rows
                if row["field_name"]
                and (
                    change.field_name.startswith(row["field_name"] + ".")
                    or change.field_name.startswith(row["field_name"] + "[")
                )
                and _structural_row_matches(row, change)
            ]
            if structural_rows:
                longest = max(len(row["field_name"]) for row in structural_rows)
                matching_rows = [
                    row
                    for row in structural_rows
                    if len(row["field_name"]) == longest
                ]
                origin = matching_rows[0]["field_name"]
                key = (
                    "parent",
                    origin,
                    change.field_name,
                    _canonical_value(change.old_value),
                    _canonical_value(change.new_value),
                )
            else:
                key = None
                matching_rows = []
        candidates.append(
            (key, [row["change_id"] for row in matching_rows])
        )

    totals = Counter(key for key, _ in candidates if key is not None)
    cursors: Counter[Any] = Counter()
    associations: list[list[int]] = []
    for key, ids in candidates:
        if key is None or not ids:
            associations.append([])
            continue
        cursor = cursors[key]
        cursors[key] += 1
        if cursor >= len(ids):
            associations.append([])
        elif cursors[key] == totals[key]:
            associations.append(ids[cursor:])
        else:
            associations.append(ids[cursor : cursor + 1])
    return associations


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return (
            "dict",
            tuple(
                (key, _canonical_value(child))
                for key, child in sorted(value.items())
            ),
        )
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(_canonical_value(child) for child in value))
    return ("scalar", value)


def _same_value(left: Any, right: Any) -> bool:
    return _canonical_value(left) == _canonical_value(right)


def _relative_segments(relative: str) -> list[tuple[str, Any]] | None:
    segments: list[tuple[str, Any]] = []
    index = 0
    while index < len(relative):
        if relative[index] == ".":
            end = index + 1
            while end < len(relative) and relative[end] not in ".[":
                end += 1
            if end == index + 1:
                return None
            segments.append(("key", relative[index + 1 : end]))
            index = end
            continue
        if relative[index] == "[":
            end = relative.find("]", index + 1)
            if end < 0:
                return None
            content = relative[index + 1 : end]
            if content.isdecimal():
                segments.append(("index", int(content)))
            else:
                conditions = []
                for part in content.split(","):
                    if "=" not in part:
                        return None
                    key, expected = part.split("=", 1)
                    conditions.append((key, expected))
                segments.append(("condition", tuple(conditions)))
            index = end + 1
            continue
        return None
    return segments


def _extract_relative(value: Any, relative: str) -> Any:
    if value is None:
        return None
    segments = _relative_segments(relative)
    if segments is None:
        return _MISSING
    current = value
    for kind, selector in segments:
        if current is None:
            return None
        if kind == "key":
            if not isinstance(current, dict):
                return _MISSING
            if selector not in current:
                return None
            current = current[selector]
        elif kind == "index":
            if not isinstance(current, (list, tuple)):
                return _MISSING
            if selector >= len(current):
                return None
            current = current[selector]
        else:
            if isinstance(current, dict):
                possible = [current, *current.values()]
            elif isinstance(current, (list, tuple)):
                possible = list(current)
            else:
                return _MISSING
            selected = next(
                (
                    item
                    for item in possible
                    if isinstance(item, dict)
                    and all(
                        key in item and str(item[key]) == expected
                        for key, expected in selector
                    )
                ),
                _MISSING,
            )
            if selected is _MISSING:
                return None
            current = selected
    return current


def _structural_row_matches(
    row: Mapping[str, Any],
    change: FieldChange,
) -> bool:
    raw_field = row["field_name"]
    relative = change.field_name[len(raw_field) :]
    old_value = _extract_relative(row["old_value"], relative)
    new_value = _extract_relative(row["new_value"], relative)
    return (
        old_value is not _MISSING
        and new_value is not _MISSING
        and _same_value(old_value, change.old_value)
        and _same_value(new_value, change.new_value)
    )


def activity(ctx: ApiContext, params: Mapping[str, str]) -> dict[str, Any]:
    common = ctx.parse_common(params)
    page = _integer(params, "page", 1)
    page_size = _integer(params, "page_size", 100, maximum=500)
    model_filter = set(_csv(params.get("models")))
    category_filter = set(_csv(params.get("categories")))
    kind_filter = set(_csv(params.get("kinds")))
    unknown_categories = category_filter - set(CATEGORIES)
    if unknown_categories:
        raise BadRequest(f"unknown category: {sorted(unknown_categories)[0]}")
    if kind_filter - {"added", "removed", "changed"}:
        raise BadRequest(f"unknown kind: {sorted(kind_filter - {'added', 'removed', 'changed'})[0]}")

    source: dict[tuple[date, str], list[dict[str, Any]]] = defaultdict(list)
    for provider_id in common.providers:
        for row in recent_change_rows(
            ctx.db.connection(), provider_id=provider_id, since=common.since, until=common.until
        ):
            source[(local_date_for(row["detected_at"]), provider_id)].append(row)

    serialized: list[dict[str, Any]] = []
    plans = []
    plans_by_date: dict[date, list[tuple[Any, ProviderProfile]]] = defaultdict(list)
    for (day, provider_id), rows in source.items():
        by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
        rows_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_model[row["provider_model_id"]].append(row)
            rows_by_model[row["provider_model_id"]].append(row)
        profile = ctx.profiles[provider_id]
        plan = plan_changes_provider(by_model, ctx.policy_for(common.detail), profile)
        plans.append((plan, profile))
        plans_by_date[day].append((plan, profile))
        presence_offsets: Counter[tuple[str, str]] = Counter()
        for grouping in group_planned_entries_by_bulk(plan.entries):
            entries = list(grouping.entries)
            if model_filter:
                entries = [entry for entry in entries if entry.model_id in model_filter]
            if category_filter:
                entries = [
                    entry
                    for entry in entries
                    if any(
                        profile.categorize(change.field_name) in category_filter
                        for change in _display_fields(entry.display)
                    )
                ]
            if not entries:
                continue
            representative = entries[0]
            original_kind = representative.kind
            if kind_filter and original_kind not in kind_filter:
                continue
            if len(entries) > 1:
                changes = list(representative.display.visible if representative.display else ())
                kind = "bulk"
            else:
                changes = list(representative.display.visible if representative.display else ())
                kind = original_kind
            if category_filter:
                changes = [change for change in changes if profile.categorize(change.field_name) in category_filter]
            hidden = _count_hidden(entries, profile, category_filter)
            if original_kind == "changed" and not changes and not any(hidden.values()):
                continue
            if original_kind == "changed":
                eligible_rows = [
                    row
                    for entry in entries
                    for row in rows_by_model[entry.model_id]
                    if row["change_kind"] not in ("added", "removed")
                    and (
                        not category_filter
                        or row["field_name"] is not None
                        and profile.categorize(row["field_name"]) in category_filter
                    )
                ]
                change_ids_by_change = [[] for _ in changes]
                for entry in entries:
                    model_rows = [
                        row
                        for row in eligible_rows
                        if row["provider_model_id"] == entry.model_id
                    ]
                    entry_changes = list(
                        entry.display.visible if entry.display else ()
                    )
                    if category_filter:
                        entry_changes = [
                            change
                            for change in entry_changes
                            if profile.categorize(change.field_name)
                            in category_filter
                        ]
                    model_associations = _change_ids_by_rendered_change(
                        entry_changes,
                        model_rows,
                    )
                    for index, associated_ids in enumerate(
                        model_associations[: len(change_ids_by_change)]
                    ):
                        change_ids_by_change[index].extend(associated_ids)
                primary_ids: list[int] = []
                used_ids: set[int] = set()
                for associated_ids in change_ids_by_change:
                    matching = next(
                        (
                            change_id
                            for change_id in associated_ids
                            if change_id not in used_ids
                        ),
                        None,
                    )
                    if matching is not None:
                        primary_ids.append(matching)
                        used_ids.add(matching)
                change_ids = primary_ids + [
                    row["change_id"]
                    for row in eligible_rows
                    if row["change_id"] not in used_ids
                ]
            else:
                presence_rows = [
                    row["change_id"]
                    for row in rows_by_model[representative.model_id]
                    if row["change_kind"] == original_kind and row["field_name"] is None
                ]
                presence_key = (representative.model_id, original_kind)
                offset = presence_offsets[presence_key]
                change_ids = presence_rows[offset : offset + 1]
                presence_offsets[presence_key] += 1
                change_ids_by_change = []
            item = {
                "date": day.isoformat(),
                "provider_id": provider_id,
                "model_id": representative.model_id,
                "display_name": representative.display_name,
                "kind": kind,
                "changes": [rendered_change_to_json(classify_change(change, profile=profile)) for change in changes],
                "hidden": hidden,
                "change_ids": change_ids,
                "change_ids_by_change": change_ids_by_change,
            }
            if kind == "bulk":
                item["bulk_models"] = [
                    {"model_id": entry.model_id, "display_name": entry.display_name} for entry in entries
                ]
            serialized.append(item)
    serialized.sort(key=lambda item: (-date.fromisoformat(item["date"]).toordinal(), item["provider_id"], item["model_id"]))
    total = len(serialized)
    start = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "entries": serialized[start : start + page_size],
        "rollups": _rollup_json(
            plans,
            models=model_filter,
            categories=category_filter,
            kinds=kind_filter,
        ),
        "rollups_by_date": {
            day.isoformat(): _rollup_json(
                day_plans,
                models=model_filter,
                categories=category_filter,
                kinds=kind_filter,
            )
            for day, day_plans in sorted(plans_by_date.items())
        },
    }


def heatmap(ctx: ApiContext, params: Mapping[str, str]) -> list[dict[str, Any]]:
    common = ctx.parse_common(params)
    policy = ctx.policy_for(common.detail)
    rows = queries.change_counts_by_date(
        ctx.db.connection(), provider_ids=common.providers, since=common.since, until=common.until
    )
    visibility = {
        field_name: visibility_of(field_name, policy)
        for field_name in dict.fromkeys(row["field_name"] for row in rows)
    }
    buckets: dict[date, Counter[str]] = defaultdict(Counter)
    for row in rows:
        day = local_date_for(row["detected_at"])
        if row["change_kind"] in ("added", "removed"):
            buckets[day][row["change_kind"]] += row["count"]
        elif visibility[row["field_name"]] == "squelched":
            buckets[day]["squelched"] += row["count"]
        else:
            buckets[day]["changed"] += row["count"]
    return [
        {"date": day.isoformat(), **{name: counts[name] for name in ("changed", "added", "removed", "squelched")}}
        for day, counts in sorted(buckets.items())
    ]


def _pins(ctx: ApiContext, params: Mapping[str, str], *, required: bool = True) -> tuple[tuple[str, str], ...]:
    raw = _csv(params.get("models"))
    if required and not raw:
        raise BadRequest("models is required")
    if len(raw) > PIN_LIMIT:
        raise BadRequest(f"at most {PIN_LIMIT} models may be pinned")
    providers = sorted(ctx.profiles, key=len, reverse=True)
    result = []
    for pin in raw:
        provider_id = next((candidate for candidate in providers if pin.startswith(candidate + "/")), None)
        if provider_id is None:
            guessed = pin.split("/", 1)[0]
            raise BadRequest(f"unknown provider: {guessed}")
        model_id = pin[len(provider_id) + 1 :]
        if not model_id:
            raise BadRequest(f"invalid model pin: {pin}")
        exists = ctx.db.connection().execute(
            """SELECT 1 FROM snapshot_models
               WHERE provider_id = ? AND provider_model_id = ? LIMIT 1""",
            (provider_id, model_id),
        ).fetchone()
        if exists is None:
            raise BadRequest(f"unknown model: {pin}")
        result.append((provider_id, model_id))
    return tuple(dict.fromkeys(result))


def _selected_aspects(ctx: ApiContext, params: Mapping[str, str]) -> tuple[Aspect, ...]:
    ids = _csv(params.get("aspects"))
    if not ids:
        raise BadRequest("aspects is required")
    if len(ids) > ASPECT_LIMIT:
        raise BadRequest(f"at most {ASPECT_LIMIT} aspects may be selected")
    lookup = {aspect.id: aspect for aspect in ctx.aspects}
    for aspect_id in ids:
        if aspect_id not in lookup:
            raise BadRequest(f"unknown aspect: {aspect_id}")
    return tuple(lookup[aspect_id] for aspect_id in dict.fromkeys(ids))


def _decode_path_value(value: Any, value_type: str | None) -> Any:
    if value_type in ("array", "object") and isinstance(value, str):
        return json.loads(value)
    return value


def _series_value(aspect: Aspect, value: Any) -> tuple[Any, str | None]:
    if value is None:
        return None, None
    if aspect.kind == "boolean":
        return int(bool(value)), None
    if aspect.kind == "list":
        members = value if isinstance(value, list) else []
        encoded_members = sorted(
            json.dumps(
                member,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            for member in members
        )
        encoded_sequence = json.dumps(
            encoded_members,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return len(members), hashlib.sha1(encoded_sequence.encode("utf-8")).hexdigest()[:8]
    if aspect.kind == "price" and aspect.source == "path":
        return float(value) * aspect.multiplier / aspect.divisor, None
    return value, None


def series(ctx: ApiContext, params: Mapping[str, str]) -> dict[str, Any]:
    common = ctx.parse_common(params)
    pins = _pins(ctx, params)
    aspects = _selected_aspects(ctx, params)
    pin_providers = {provider_id for provider_id, _ in pins}
    for aspect in aspects:
        if aspect.provider_id not in pin_providers:
            raise BadRequest(f"aspect {aspect.id} is incompatible with selected models")
    scrapes_by_provider = {
        provider_id: queries.saved_scrape_ids(
            ctx.db.connection(), provider_id=provider_id, since=common.since, until=common.until
        )
        for provider_id in pin_providers
    }
    axis = sorted(
        (scrape for scrapes in scrapes_by_provider.values() for scrape in scrapes),
        key=lambda scrape: (scrape["completed_at"], scrape["scrape_id"]),
    )
    axis_json = [
        {
            "scrape_id": scrape["scrape_id"],
            "provider_id": scrape["provider_id"],
            "date": scrape["date"].isoformat(),
            "completed_at": scrape["completed_at"],
            "t": datetime.fromisoformat(scrape["completed_at"]).timestamp(),
        }
        for scrape in axis
    ]
    values_by_provider: dict[str, dict[tuple[int, str], Any]] = {}
    for provider_id in pin_providers:
        provider_aspects = [aspect for aspect in aspects if aspect.provider_id == provider_id]
        rows = queries.series_rows(
            ctx.db.connection(),
            provider_id=provider_id,
            scrape_ids=[scrape["scrape_id"] for scrape in scrapes_by_provider[provider_id]],
            model_ids=[model_id for pin_provider, model_id in pins if pin_provider == provider_id],
            columns=[aspect.column for aspect in provider_aspects if aspect.column],
            paths=[aspect.path for aspect in provider_aspects if aspect.path],
        )
        values_by_provider[provider_id] = {(int(row["scrape_id"]), row["provider_model_id"]): row for row in rows}
    output = []
    for provider_id, model_id in pins:
        for aspect in aspects:
            if aspect.provider_id != provider_id:
                continue
            values, hashes, members = [], [], []
            for point in axis:
                row = values_by_provider[provider_id].get((point["scrape_id"], model_id)) if point["provider_id"] == provider_id else None
                if row is None:
                    raw = None
                elif aspect.source == "column":
                    raw = row[aspect.column]
                else:
                    raw = _decode_path_value(row[queries.path_value_key(aspect.path)], row[queries.path_type_key(aspect.path)])
                value, value_hash = _series_value(aspect, raw)
                values.append(value)
                hashes.append(value_hash)
                members.append(list(raw) if aspect.kind == "list" and isinstance(raw, list) else None)
            output.append(
                {"model": f"{provider_id}/{model_id}", "aspect": aspect.id, "provider_id": provider_id, "kind": aspect.kind,
                 "unit": aspect.unit, "values": values, "list_hash": hashes, "members": members}
            )
    return {"axis": axis_json, "series": output}


def events(ctx: ApiContext, params: Mapping[str, str]) -> list[dict[str, Any]]:
    common = ctx.parse_common(params)
    pins = _pins(ctx, params)
    policy = ctx.policy_for(common.detail)
    output = []
    for provider_id in dict.fromkeys(provider for provider, _ in pins):
        model_ids = [model for provider, model in pins if provider == provider_id]
        profile = ctx.profiles[provider_id]
        for row in queries.events_for_models(
            ctx.db.connection(), provider_id=provider_id, model_ids=model_ids,
            since=common.since, until=common.until
        ):
            if row["field_name"] is None:
                semantic, direction = "coverage", row["change_kind"]
            else:
                rendered = classify_change(
                    FieldChange(row["field_name"], row["old_value"], row["new_value"]), profile=profile
                )
                semantic, direction = rendered.semantic, rendered.direction
            output.append(
                {"change_id": row["change_id"], "date": local_date_for(row["detected_at"]).isoformat(),
                 "model": f"{provider_id}/{row['provider_model_id']}",
                 "kind": row["change_kind"], "field": row["field_name"],
                 "semantic": semantic, "direction": direction,
                 "squelched": visibility_of(row["field_name"], policy) == "squelched"}
            )
    output.sort(key=lambda item: (item["date"], item["model"], item["change_id"]))
    return output


def _catalog_aspects(ctx: ApiContext, provider_id: str, params: Mapping[str, str]) -> tuple[Aspect, ...]:
    lookup = {aspect.id: aspect for aspect in ctx.aspects if aspect.provider_id == provider_id}
    ids = _csv(params.get("columns"))
    if not ids:
        ids = tuple(
            aspect.id for aspect in ctx.aspects
            if aspect.provider_id == provider_id and aspect.source == "column"
            and aspect.category in {"Pricing", "Context & Limits", "Capabilities"}
        )
    for aspect_id in ids:
        if aspect_id not in lookup:
            raise BadRequest(f"unknown aspect: {aspect_id}")
    return tuple(lookup[aspect_id] for aspect_id in dict.fromkeys(ids))


def _scrape_for_catalog(ctx: ApiContext, provider_id: str, raw: str | None, name: str) -> dict[str, Any]:
    if raw is None:
        raise BadRequest(f"{name} is required")
    try:
        scrape_id = int(raw)
    except ValueError as exc:
        raise BadRequest(f"{name} must be an integer") from exc
    scrape = next((item for item in queries.list_scrapes(ctx.db.connection()) if item["scrape_id"] == scrape_id), None)
    if scrape is None or scrape["provider_id"] != provider_id or not scrape["saved"] or scrape["status"] != "success":
        raise BadRequest(f"{name} must identify a saved successful scrape for {provider_id}")
    return scrape


def _present_path_value(raw_model: dict[str, Any], path: Sequence[str]) -> Any:
    current: Any = raw_model
    for segment in path:
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _catalog_profile_value(
    raw_model: dict[str, Any],
    profile: ProviderProfile,
    column: str,
) -> tuple[Any, str | None]:
    value, path = profile_field_candidate(raw_model, profile, column)
    if path is not None:
        return value, path
    for candidate in profile.normalized_fields.get(column, ()):
        value = _present_path_value(raw_model, candidate)
        if (
            value is not _MISSING
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value == 0
        ):
            return value, ".".join(candidate)
    return None, None


def _raw_aspect_value(row: dict[str, Any] | None, aspect: Aspect, profile: ProviderProfile) -> Any:
    if row is None:
        return None
    raw_model = json.loads(row["metadata_json"])
    if aspect.kind == "price" and aspect.source == "column":
        value, _ = _catalog_profile_value(raw_model, profile, aspect.column)
        return value
    if aspect.source == "column":
        return row[aspect.column]
    value = _present_path_value(raw_model, aspect.path.split("."))
    return None if value is _MISSING else value


def _json_scrape(scrape: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in scrape.items()
    }


def _catalog_machine_value(
    row: dict[str, Any] | None,
    aspect: Aspect,
    raw_value: Any,
    profile: ProviderProfile,
) -> Any:
    if row is None:
        return None
    if aspect.source != "column" or aspect.kind != "price":
        return raw_value
    stored = row[aspect.column]
    if stored is not None:
        return stored
    if (
        isinstance(raw_value, (int, float))
        and not isinstance(raw_value, bool)
        and raw_value == 0
    ):
        rule = resolve_price_rule(aspect.field_name, profile)
        return raw_value * rule.multiplier / rule.divisor
    return None


def _catalog_sort_key(value: Any) -> tuple[Any, ...]:
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return (1, value)
    if isinstance(value, float):
        if math.isfinite(value):
            return (1, value)
        return (5, type(value).__name__, repr(value))
    if isinstance(value, str):
        return (2, value.casefold(), value)
    if isinstance(value, list):
        return (
            3,
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        )
    if isinstance(value, dict):
        return (
            4,
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        )
    return (5, type(value).__name__, repr(value))


def catalog(ctx: ApiContext, params: Mapping[str, str]) -> dict[str, Any]:
    provider_id = params.get("provider")
    if not provider_id:
        raise BadRequest("provider is required")
    if provider_id not in ctx.profiles:
        raise BadRequest(f"unknown provider: {provider_id}")
    as_of = _scrape_for_catalog(ctx, provider_id, params.get("as_of"), "as_of")
    compare = None
    if params.get("compare"):
        compare = _scrape_for_catalog(ctx, provider_id, params.get("compare"), "compare")
        if (compare["completed_at"], compare["scrape_id"]) >= (as_of["completed_at"], as_of["scrape_id"]):
            raise BadRequest("compare must be earlier than as_of")
    aspects = _catalog_aspects(ctx, provider_id, params)
    columns = [aspect.column for aspect in aspects if aspect.column]
    paths = [aspect.path for aspect in aspects if aspect.path]
    current = queries.catalog_rows(ctx.db.connection(), scrape_id=as_of["scrape_id"], columns=columns, paths=paths)
    previous = {} if compare is None else queries.catalog_rows(
        ctx.db.connection(), scrape_id=compare["scrape_id"], columns=columns, paths=paths
    )
    profile = ctx.profiles[provider_id]
    q = params.get("q", "").casefold()
    output = []
    for model_id in set(current) | set(previous):
        new_row, old_row = current.get(model_id), previous.get(model_id)
        display_name = (new_row or old_row)["display_name"]
        if q and q not in model_id.casefold() and q not in display_name.casefold():
            continue
        if compare is None:
            presence = "present"
        elif old_row is None:
            presence = "added"
        elif new_row is None:
            presence = "removed"
        else:
            presence = "present"
        cells = {}
        for aspect in aspects:
            new_raw = _raw_aspect_value(new_row, aspect, profile)
            old_raw = _raw_aspect_value(old_row, aspect, profile)
            stored = _catalog_machine_value(new_row, aspect, new_raw, profile)
            rendered = classify_change(FieldChange(aspect.field_name, old_raw, new_raw), profile=profile)
            new_display = rendered.new_display
            old_display = rendered.old_display
            rendered_json = rendered_change_to_json(rendered)
            if aspect.kind == "boolean":
                old_display = "—" if old_raw is None else "on" if bool(old_raw) else "off"
                new_display = "—" if new_raw is None else "on" if bool(new_raw) else "off"
                rendered_json = {
                    **rendered_json,
                    "old_display": old_display,
                    "new_display": new_display,
                }
            elif compare is not None and _same_value(old_raw, new_raw):
                stable = classify_change(
                    FieldChange(aspect.field_name, None, new_raw),
                    profile=profile,
                )
                new_display = old_display = stable.new_display
            cell = {"value": stored, "display": new_display, "unit": aspect.unit}
            if compare is not None:
                cell.update({
                    "old_value": _catalog_machine_value(old_row, aspect, old_raw, profile),
                    "old_display": old_display,
                    "change": rendered_json,
                })
            cells[aspect.id] = cell
        output.append({"model_id": model_id, "display_name": display_name, "presence": presence, "cells": cells})
    sort = params.get("sort", "model_id")
    direction = params.get("dir", "asc")
    if direction not in ("asc", "desc"):
        raise BadRequest("dir must be asc or desc")
    if sort != "model_id" and sort not in {aspect.id for aspect in aspects}:
        raise BadRequest(f"unknown sort column: {sort}")
    def raw_sort_value(row: dict[str, Any]) -> Any:
        return row["model_id"] if sort == "model_id" else row["cells"][sort]["value"]

    def sort_value(row: dict[str, Any]) -> tuple[Any, ...]:
        return (*_catalog_sort_key(raw_sort_value(row)), row["model_id"])

    populated = [row for row in output if raw_sort_value(row) is not None]
    missing = [row for row in output if raw_sort_value(row) is None]
    populated.sort(key=sort_value, reverse=direction == "desc")
    missing.sort(key=lambda row: row["model_id"])
    output = populated + missing
    page = _integer(params, "page", 1)
    page_size = _integer(params, "page_size", 200, maximum=500)
    total = len(output)
    start = (page - 1) * page_size
    return {
        "as_of": _json_scrape(as_of),
        "compare": None if compare is None else _json_scrape(compare),
        "total": total,
        "rows": output[start:start + page_size],
    }


def change(ctx: ApiContext, params: Mapping[str, str]) -> dict[str, Any]:
    raw = params.get("change_id")
    try:
        change_id = int(raw) if raw is not None else None
    except ValueError as exc:
        raise BadRequest("change_id must be an integer") from exc
    if change_id is None:
        raise BadRequest("change_id is required")
    query_row = queries.change_by_id(ctx.db.connection(), change_id)
    if query_row is None:
        raise NotFound(f"change not found: {change_id}")
    row = dict(query_row)
    field_name = row.pop("field_name")
    model_id = row.pop("provider_model_id")
    kind = row.pop("change_kind")
    rendered = None
    if field_name is not None:
        rendered = rendered_change_to_json(
            classify_change(FieldChange(field_name, row["old_value"], row["new_value"]), profile=ctx.profiles[row["provider_id"]])
        )
    else:
        rendered = _render_presence_change(
            model_id=model_id,
            kind=kind,
            profile=ctx.profiles[row["provider_id"]],
        )
    row["from_scrape"] = None if row["from_scrape"] is None else _json_scrape(row["from_scrape"])
    row["to_scrape"] = None if row["to_scrape"] is None else _json_scrape(row["to_scrape"])
    return {**row, "model_id": model_id, "field": field_name, "kind": kind, "rendered": rendered}


def models(ctx: ApiContext, params: Mapping[str, str]) -> list[dict[str, Any]]:
    common = ctx.parse_common(params)
    limit = _integer(params, "limit", 50, maximum=500)
    return queries.search_models(
        ctx.db.connection(), provider_ids=common.providers, query=params.get("q", ""), limit=limit
    )
