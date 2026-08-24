from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any, Literal

from ..change_render import pricing_field_sort_key, resolve_field_label, resolve_price_rule
from ..normalize import profile_field_candidate
from ..provider_profiles import ProviderProfile
from ..reporting import ReportDetailPolicy, classify_detail_visibility
from .readonly import ReadOnlyDatabase


CATEGORIES = (
    "Pricing",
    "Context & Limits",
    "Capabilities",
    "Parameters",
    "Benchmarks",
    "Other",
)

_CANONICAL_COLUMNS = (
    "input_price",
    "output_price",
    "cache_read_price",
    "cache_write_price",
    "context_window",
    "max_output_tokens",
    "reasoning_supported",
    "tool_calling_supported",
    "vision_supported",
    "audio_supported",
    "image_supported",
    "structured_output_supported",
    "deprecated",
    "status",
)
_BOOLEAN_COLUMNS = frozenset(
    column for column in _CANONICAL_COLUMNS if column.endswith("_supported")
) | {"deprecated"}
_TOKEN_COLUMNS = frozenset({"context_window", "max_output_tokens"})
_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")
_LOG = logging.getLogger(__name__)

AspectSource = Literal["column", "path"]
AspectKind = Literal["price", "count", "numeric", "boolean", "list", "scalar"]


@dataclass(frozen=True)
class Aspect:
    """One provider-scoped canonical column or raw metadata path."""

    id: str
    provider_id: str
    source: AspectSource
    column: str | None
    path: str | None
    field_name: str
    label: str
    qualifier: str | None
    category: str
    kind: AspectKind
    unit: str | None
    multiplier: int
    divisor: int
    squelched: bool

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def build_aspect_catalog(
    db: ReadOnlyDatabase,
    *,
    profiles: dict[str, ProviderProfile],
    policy: ReportDetailPolicy,
) -> tuple[Aspect, ...]:
    """Build the deterministic set of time-series fields present in history."""
    connection = db.connection()
    latest_models = _latest_models_by_provider(connection, profiles)
    aspects: list[Aspect] = []
    canonical_identities: set[tuple[str, str]] = set()

    for provider_id, profile in profiles.items():
        raw_models = latest_models.get(provider_id, ())
        for column in _CANONICAL_COLUMNS:
            field_name = _representative_field_name(column, profile, raw_models)
            canonical_identities.add((provider_id, field_name))
            aspects.append(
                _make_aspect(
                    provider_id=provider_id,
                    source="column",
                    name=column,
                    field_name=field_name,
                    profile=profile,
                    policy=policy,
                    json_type=None,
                )
            )

    discovered = connection.execute(
        """SELECT DISTINCT provider_id, field_name
           FROM field_changes
           WHERE field_name IS NOT NULL
           ORDER BY provider_id, field_name"""
    ).fetchall()
    for row in discovered:
        provider_id = str(row["provider_id"])
        profile = profiles.get(provider_id)
        if profile is None:
            continue
        path = str(row["field_name"])
        if (provider_id, path) in canonical_identities:
            continue
        if not _safe_path(path):
            _LOG.debug("Skipping unsafe metadata aspect path %r for %s", path, provider_id)
            continue
        json_type = _sample_json_type(connection, provider_id, path)
        if json_type in (None, "object", "null"):
            continue
        aspects.append(
            _make_aspect(
                provider_id=provider_id,
                source="path",
                name=path,
                field_name=path,
                profile=profile,
                policy=policy,
                json_type=json_type,
            )
        )

    category_rank = {category: rank for rank, category in enumerate(CATEGORIES)}

    def sort_key(aspect: Aspect) -> tuple[Any, ...]:
        profile = profiles[aspect.provider_id]
        if aspect.category == "Pricing":
            field_key: tuple[Any, ...] = pricing_field_sort_key(aspect.field_name, profile)
        else:
            field_key = (aspect.label.casefold(), aspect.qualifier or "", aspect.field_name.casefold())
        return (
            category_rank.get(aspect.category, len(CATEGORIES)),
            field_key,
            aspect.provider_id.casefold(),
            aspect.source,
            aspect.id.casefold(),
        )

    return tuple(sorted(aspects, key=sort_key))


def _latest_models_by_provider(
    connection: sqlite3.Connection,
    profiles: dict[str, ProviderProfile],
) -> dict[str, tuple[dict[str, Any], ...]]:
    result: dict[str, tuple[dict[str, Any], ...]] = {}
    for provider_id in profiles:
        rows = connection.execute(
            """SELECT sm.metadata_json
               FROM snapshot_models AS sm
               WHERE sm.provider_id = ?
                 AND sm.scrape_id = (
                     SELECT s.scrape_id
                     FROM scrapes AS s
                     WHERE s.provider_id = ?
                       AND s.status = 'success'
                       AND s.saved_snapshot = 1
                     ORDER BY s.completed_at DESC, s.scrape_id DESC
                     LIMIT 1
                 )
               ORDER BY sm.provider_model_id""",
            (provider_id, provider_id),
        ).fetchall()
        result[provider_id] = tuple(json.loads(row["metadata_json"]) for row in rows)
    return result


def _representative_field_name(
    column: str,
    profile: ProviderProfile,
    raw_models: tuple[dict[str, Any], ...],
) -> str:
    candidates = profile.normalized_fields.get(column, ())
    populated_paths: set[str] = set()
    for raw_model in raw_models:
        _, path = profile_field_candidate(raw_model, profile, column)
        if path is not None:
            populated_paths.add(path)
    for candidate in candidates:
        dotted = ".".join(candidate)
        if dotted in populated_paths:
            return dotted
    if candidates:
        return ".".join(candidates[0])
    return column


def _make_aspect(
    *,
    provider_id: str,
    source: AspectSource,
    name: str,
    field_name: str,
    profile: ProviderProfile,
    policy: ReportDetailPolicy,
    json_type: str | None,
) -> Aspect:
    label, qualifier = resolve_field_label(field_name, profile)
    category = profile.categorize(field_name)
    kind = _kind_for(
        source=source,
        name=name,
        field_name=field_name,
        profile=profile,
        json_type=json_type,
    )
    if kind == "price":
        rule = resolve_price_rule(field_name, profile)
        unit = rule.unit_label
        multiplier = 1 if source == "column" else rule.multiplier
        divisor = 1 if source == "column" else rule.divisor
    else:
        unit = "tokens" if source == "column" and name in _TOKEN_COLUMNS else None
        multiplier = divisor = 1
    return Aspect(
        id=f"{provider_id}:{name}" if source == "column" else f"{provider_id}:path:{name}",
        provider_id=provider_id,
        source=source,
        column=name if source == "column" else None,
        path=name if source == "path" else None,
        field_name=field_name,
        label=label,
        qualifier=qualifier,
        category=category,
        kind=kind,
        unit=unit,
        multiplier=multiplier,
        divisor=divisor,
        squelched=classify_detail_visibility(field_name, policy) == "squelched",
    )


def _kind_for(
    *,
    source: AspectSource,
    name: str,
    field_name: str,
    profile: ProviderProfile,
    json_type: str | None,
) -> AspectKind:
    if profile.is_price_amount_field(field_name):
        return "price"
    if field_name in profile.known_boolean_fields or (
        source == "column" and name in _BOOLEAN_COLUMNS
    ) or json_type in {"true", "false"}:
        return "boolean"
    if json_type == "array":
        return "list"
    if profile.is_count_field(field_name):
        return "count"
    if json_type in {"integer", "real"} or source == "column" and name in _TOKEN_COLUMNS:
        return "numeric"
    return "scalar"


def _safe_path(path: str) -> bool:
    segments = path.split(".")
    return bool(segments) and all(_PATH_SEGMENT.fullmatch(segment) for segment in segments)


def _sample_json_type(
    connection: sqlite3.Connection,
    provider_id: str,
    path: str,
) -> str | None:
    json_path = "$" + "".join(f'."{segment}"' for segment in path.split("."))
    row = connection.execute(
        """SELECT json_type(sm.metadata_json, ?) AS value_type
           FROM snapshot_models AS sm
           JOIN scrapes AS s ON s.scrape_id = sm.scrape_id
           WHERE sm.provider_id = ?
             AND s.status = 'success'
             AND s.saved_snapshot = 1
             AND json_extract(sm.metadata_json, ?) IS NOT NULL
           ORDER BY s.completed_at DESC, s.scrape_id DESC, sm.provider_model_id
           LIMIT 1""",
        (json_path, provider_id, json_path),
    ).fetchone()
    return None if row is None else row["value_type"]
