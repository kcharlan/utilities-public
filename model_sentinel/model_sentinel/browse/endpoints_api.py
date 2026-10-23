"""The dossier's `/api/endpoints` projection of one saved model observation.

`browse.api.endpoints` validates the model identity and selects the exact
catalog observation; this module reads that observation's endpoint capture,
and only that one, through the read-only `queries` helpers. A capture of any
other scrape is never substituted, and changes are bounded by the
observation's catalog order, not by when captures completed.

Price and ladder projections come from `endpoint_report` (strict
classification, `resolved_price_leaves`, shared ladders), and the alias check
from `alias_check.evaluate_aliases` on the observation's exact catalog
snapshot, whether or not endpoint evidence exists. Every value returned is
JSON-safe.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from typing import Any, Final, Mapping

from ..alias_check import evaluate_aliases
from ..endpoints import (
    ALIAS_CYCLE,
    ALIAS_TARGET_MISSING,
    CAPTURE_ERROR,
    DOSSIER_ENDPOINT_CHANGE_LIMIT,
    MAPPING_INVALID_LINK,
    MAPPING_NO_LINK,
    alias_declaration,
)
from ..endpoint_report import (
    alias_divergence_sentence,
    alias_ladders,
    alias_match_labels,
    alias_reason_text,
    alias_unavailable_leaf_sentence,
    capture_counts_line,
    change_price_evidence,
    endpoint_change_label,
    endpoint_change_rendering,
    endpoint_gap_description,
    endpoint_label_profile,
    endpoint_match_sentence,
    endpoint_price_table,
    failed_list_label,
    failed_list_state_sentence,
    ladder_position_text,
    ladder_unplaced_text,
    list_comparison_line,
)
from ..models import AliasEvaluation, EndpointChangeRecord, EndpointListRecord, Ladder
from ..provider_profiles import ProviderProfile
from . import queries
from .json_values import json_scrape, rendered_change_to_json


REASON_NO_TABLES: Final = "no_tables"
REASON_NOT_CAPTURED: Final = "not_captured"
REASON_FETCH_ERROR: Final = "fetch_error"
REASON_CAPTURE_ERROR: Final = "capture_error"
# A mapping's own error code is its reason; an alias whose chain ends at a
# model without a usable link carries that model's `no_link`/`invalid_link`.
_MAPPING_REASONS: Final = frozenset({MAPPING_NO_LINK, MAPPING_INVALID_LINK, ALIAS_TARGET_MISSING, ALIAS_CYCLE})


class EndpointDataIntegrityError(RuntimeError):
    """Saved endpoint records contradict each other (never a reason state)."""


def endpoint_response(
    connection: sqlite3.Connection,
    *,
    provider_id: str,
    model_id: str,
    scrape: Mapping[str, Any],
    profile: ProviderProfile,
) -> dict[str, Any]:
    """The `/api/endpoints` response for the observation `scrape` of one model.

    `scrape` is a `model_presence`/`model_observation` scrape summary already
    validated as a saved observation of this model.

    Evidence is also worded here, by `endpoint_report`'s functions, so the
    page shows the reports' sentences rather than re-deriving them:
    `capture.status_line` (the reports' capture line),
    `capture.comparison_sentence` (whether this model's list was compared),
    `list_error.label` and `list_error.sentence` (a failed or unsent list),
    each list gap's `text`, the alias's `reason_text`,
    `divergence_sentences`, `match_sentence` and `unavailable_sentences`, and
    each ladder's `unplaced_text` and position `text`.
    """
    response = _endpoint_projection(
        connection, provider_id=provider_id, model_id=model_id, scrape=scrape, profile=profile
    )
    capture = response["capture"]
    list_error = response["list_error"]
    if list_error is not None:
        list_error["label"] = failed_list_label(list_error["code"])
        list_error["sentence"] = failed_list_state_sentence(list_error["code"])
    if capture is not None:
        capture.update(capture_status(capture))
        for gap in capture["list_gaps"]:
            gap["text"] = endpoint_gap_description(gap["reason"], gap["list_error_code"])
        succeeded = True if response["captured"] else False if response["reason"] == REASON_FETCH_ERROR else None
        capture["comparison_sentence"] = list_comparison_line(
            first_capture=bool(capture["first_capture"]),
            comparison_state=capture["comparison_state"],
            baseline_capture_id=capture["baseline_capture_id"],
            list_succeeded=succeeded,
            gap_reasons=[gap["reason"] for gap in capture["list_gaps"]],
            list_error_code=list_error["code"] if list_error is not None else None,
        )
    return response


def _endpoint_projection(
    connection: sqlite3.Connection,
    *,
    provider_id: str,
    model_id: str,
    scrape: Mapping[str, Any],
    profile: ProviderProfile,
) -> dict[str, Any]:
    scrape_id = int(scrape["scrape_id"])
    tables = queries.endpoint_tables_present(connection)
    capture = queries.endpoint_capture_for_scrape(connection, scrape_id=scrape_id) if tables else None
    if capture is not None and capture["provider_id"] != provider_id:
        raise EndpointDataIntegrityError("endpoint capture belongs to another provider")
    first_date = queries.first_usable_endpoint_capture_date(connection, provider_id=provider_id) if tables else None
    telemetry_tables = queries.endpoint_telemetry_present(connection)
    telemetry_status = queries.capture_telemetry_status(
        connection, capture_id=capture["capture_id"]
    ) if capture is not None else {"available": False, "archive": False}
    response: dict[str, Any] = {
        "provider_id": provider_id,
        "model_id": model_id,
        "scrape_id": scrape_id,
        "captured": False,
        "reason": None,
        "telemetry": "available" if telemetry_status["available"] else "pending" if telemetry_tables else "no_tables",
        "backfill_eligible": telemetry_status["archive"] and not telemetry_status["available"],
        "capture": None,
        "first_capture_date": first_date.isoformat() if first_date is not None else None,
        "list_path": None,
        "list_model_id": None,
        "shared_with": [],
        "alias": None,
        "list_outcome": None,
        "list_error": None,
        "endpoints": {"columns": [], "rows": []},
        "ladders": [],
        "changes": [],
        "limit": DOSSIER_ENDPOINT_CHANGE_LIMIT,
        "truncated": False,
    }

    evaluation, lists = _alias_evaluation(connection, provider_id, model_id, scrape_id, capture, profile)
    if evaluation is not None:
        response["alias"] = _alias_json(evaluation)
    if not tables:
        response["reason"] = REASON_NO_TABLES
        return response
    if capture is None:
        response["reason"] = REASON_NOT_CAPTURED
        return response

    capture_id = capture["capture_id"]
    response["capture"] = {**capture, "list_gaps": []}
    mapping = queries.endpoint_model_list(connection, capture_id=capture_id, model_id=model_id)
    if mapping is None:
        if capture["status"] == CAPTURE_ERROR and not queries.endpoint_capture_has_records(
            connection, capture_id=capture_id
        ):
            # A capture-wide failure (such as the minimal fallback) saved no
            # mapping or list; its evidence is `capture.error_summary`.
            response["reason"] = REASON_CAPTURE_ERROR
            return response
        raise EndpointDataIntegrityError("endpoint capture has no mapping for an observed catalog model")
    if mapping["error_code"] is not None:
        if mapping["error_code"] not in _MAPPING_REASONS:
            raise EndpointDataIntegrityError("endpoint mapping has an unknown error code")
        response["reason"] = mapping["error_code"]
        return response
    list_path = mapping["list_path"]
    if list_path is None or not mapping["list_present"]:
        raise EndpointDataIntegrityError("resolved endpoint mapping has no saved list")

    if lists is None:
        lists = queries.endpoint_capture_lists(connection, capture_id=capture_id, list_path=list_path)
    listing = next((item for item in lists if item.list_path == list_path), None)
    if listing is None:
        raise EndpointDataIntegrityError("resolved endpoint mapping has no saved list")
    response["capture"]["list_gaps"] = queries.endpoint_list_gaps(
        connection, capture_id=capture_id, list_path=list_path
    )
    response["list_path"] = list_path
    response["list_model_id"] = listing.list_model_id
    response["list_outcome"] = listing.outcome
    if not listing.succeeded:
        response["reason"] = REASON_FETCH_ERROR
        response["list_error"] = {"code": listing.error_code, "message": listing.error_message}
        return response

    label_profile = endpoint_label_profile(profile)
    response["captured"] = True
    response["shared_with"] = [
        entry
        for entry in queries.endpoint_list_models(connection, capture_id=capture_id, list_path=list_path)
        if entry["model_id"] != model_id
    ]
    response["endpoints"] = _plain_asdict(endpoint_price_table(listing, label_profile))
    samples = {
        row["endpoint_key"]: row
        for row in queries.capture_endpoint_rows(connection, capture_id=capture_id, list_path=list_path)
    }
    for row in response["endpoints"]["rows"]:
        sample = samples.get(row["endpoint_key"], {})
        row["uptime"] = {
            window: sample.get(f"uptime_{window}") if telemetry_status["available"] else None
            for window in ("1d", "30m", "5m")
        }
    if evaluation is not None and evaluation.divergence is not None:
        target_path = evaluation.endpoint_match.list_path
        target_list = next((item for item in lists if item.list_path == target_path), None)
        response["ladders"] = [
            _ladder_json(ladder) for ladder in alias_ladders(evaluation.divergence.leaves, target_list, profile)
        ]

    limit = DOSSIER_ENDPOINT_CHANGE_LIMIT
    rows = queries.endpoint_list_changes(
        connection,
        provider_id=provider_id,
        list_path=list_path,
        completed_at=str(scrape["completed_at"]),
        scrape_id=scrape_id,
        limit=limit + 1,
    )
    response["limit"] = limit
    response["truncated"] = len(rows) > limit
    response["changes"] = [endpoint_change_json(row, listing, label_profile) for row in rows[:limit]]
    return response


def _alias_evaluation(
    connection: sqlite3.Connection,
    provider_id: str,
    model_id: str,
    scrape_id: int,
    capture: Mapping[str, Any] | None,
    profile: ProviderProfile,
) -> tuple[AliasEvaluation | None, tuple[EndpointListRecord, ...] | None]:
    """This model's alias evaluation on the observation's catalog snapshot.

    Returns (None, None) when the model declares no alias. Otherwise the
    evaluation uses every list of the observation's capture as evidence
    (None without a capture), and those lists are returned for reuse.
    """
    row = queries.snapshot_model_row(
        connection, scrape_id=scrape_id, provider_id=provider_id, model_id=model_id, columns=(), paths=()
    )
    if row is None:
        raise EndpointDataIntegrityError("observed catalog model has no snapshot row")
    metadata = json.loads(row["metadata_json"])
    # Metadata that is not an object declares no alias (as in `evaluate_aliases`).
    if not isinstance(metadata, Mapping) or not alias_declaration(metadata)[0]:
        return None, None
    catalog = {
        catalog_id: json.loads(catalog_row["metadata_json"])
        for catalog_id, catalog_row in queries.catalog_rows(
            connection, scrape_id=scrape_id, columns=(), paths=()
        ).items()
    }
    lists = None
    if capture is not None:
        lists = queries.endpoint_capture_lists(connection, capture_id=capture["capture_id"])
    evaluation = next(
        (item for item in evaluate_aliases(catalog, profile, lists) if item.alias_model_id == model_id),
        None,
    )
    return evaluation, lists


def _alias_json(evaluation: AliasEvaluation) -> dict[str, Any]:
    match = evaluation.endpoint_match
    return {
        **_plain_asdict(evaluation),
        "reason_text": (
            alias_reason_text(evaluation.unavailable_reason) if evaluation.unavailable_reason is not None else None
        ),
        "divergence_sentences": [
            alias_divergence_sentence(leaf, raw_first=False)
            for leaf in (evaluation.divergence.leaves if evaluation.divergence is not None else ())
        ],
        "match_sentence": endpoint_match_sentence(match, alias_match_labels(match, evaluation.compared_leaves)),
        "unavailable_sentences": [alias_unavailable_leaf_sentence(leaf) for leaf in evaluation.unavailable_leaves],
    }


def _ladder_json(ladder: Ladder) -> dict[str, Any]:
    payload = _plain_asdict(ladder)
    for position, record in zip(payload["positions"], ladder.positions):
        position["text"] = ladder_position_text(record.entries)
    payload["unplaced_text"] = ladder_unplaced_text(ladder) if ladder.unplaced else None
    return payload


def endpoint_change_json(row: Mapping[str, Any], listing: EndpointListRecord, profile: ProviderProfile) -> dict[str, Any]:
    change = EndpointChangeRecord(
        from_capture_id=row["from_capture_id"],
        to_capture_id=row["to_capture_id"],
        from_list_path=row["from_list_path"],
        list_path=row["list_path"],
        endpoint_key=row["endpoint_key"],
        change_kind=row["change_kind"],
        field_name=row["field_name"],
        old_value=row["old_value"],
        new_value=row["new_value"],
        display_id=listing.display_id,
        model_ids=listing.model_ids,
    )
    rendered = endpoint_change_rendering(change, profile)
    return {
        **row,
        "from_scrape": json_scrape(row["from_scrape"]),
        "to_scrape": json_scrape(row["to_scrape"]),
        "label": endpoint_change_label(change, rendered),
        "rendered": _plain(rendered_change_to_json(rendered)) if rendered is not None else None,
        "price_evidence": change_price_evidence(change, profile),
    }


def _plain_asdict(record: Any) -> dict[str, Any]:
    """`dataclasses.asdict` with tuples as lists, so the response is plain JSON data."""
    return _plain(dataclasses.asdict(record))


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def capture_status(capture: Mapping[str, Any]) -> dict[str, Any]:
    """Shared capture evidence; dossier-only list comparison wording stays local."""
    return {
        **capture,
        "status_line": capture_counts_line(
            status=capture["status"], capture_id=capture["capture_id"],
            paths_requested=capture["paths_requested"], paths_attempted=capture["paths_attempted"],
            paths_failed=capture["paths_failed"], paths_unsent=capture["paths_unsent"],
            mapping_failures=capture["mapping_failures"], error_summary=capture["error_summary"],
        ),
    }
