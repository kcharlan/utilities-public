"""Read-only host matrix and saved host-history projections."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date
from statistics import median
from typing import Any, Mapping

from ..change_render import format_price_values, pricing_field_sort_key
from ..endpoint_report import endpoint_label_profile, endpoint_price_table, state_price_leaves
from ..endpoints import DOSSIER_ENDPOINT_CHANGE_LIMIT
from ..provider_profiles import ProviderProfile, quantization_bits
from . import queries
from .endpoints_api import EndpointDataIntegrityError, capture_status, endpoint_change_json
from .json_values import json_scrape


def host_name(provider_name: Any, name: Any, tag: Any, key: str) -> str:
    """The dossier EndpointTable's string-only display-name fallback."""
    return next((value for value in (provider_name, name, tag) if isinstance(value, str) and value), key)


def _strings(value: Any) -> list[str]:
    return sorted({item for item in value if isinstance(item, str)}) if isinstance(value, list) else []


def hosts_response(connection: sqlite3.Connection, *, provider_id: str,
                   scrape: Mapping[str, Any] | None, profile: ProviderProfile) -> dict[str, Any]:
    captures = queries.host_captures(connection, provider_id=provider_id)
    tables = queries.endpoint_tables_present(connection)
    telemetry_tables = queries.endpoint_telemetry_present(connection)
    sid = scrape["scrape_id"] if scrape is not None else None
    capture = queries.endpoint_capture_for_scrape(connection, scrape_id=sid) if tables and sid is not None else None
    if capture is not None and capture["provider_id"] != provider_id:
        raise EndpointDataIntegrityError("endpoint capture belongs to another provider")
    status = queries.capture_telemetry_status(connection, capture_id=capture["capture_id"]) if capture else {"available": False, "archive": False}
    response = {
        "provider_id": provider_id, "scrape_id": sid, "reason": None,
        "captures": [json_scrape(row) for row in captures],
        "capture": capture_status(capture) if capture else None,
        "telemetry": "available" if status["available"] else "pending" if telemetry_tables else "no_tables",
        "backfill_eligible": status["archive"] and not status["available"],
        "price_columns": [], "lists": [], "hosts": [],
        "vocab": {"parameters": [], "native_tools": [], "quantizations": [], "tiers": []},
        "endpoints": [],
    }
    if not tables:
        response["reason"] = "no_tables"
        return response
    if capture is None:
        response["reason"] = "not_captured"
        return response
    cid = capture["capture_id"]
    listings = queries.endpoint_capture_lists(connection, capture_id=cid)
    if not any(listing.succeeded for listing in listings):
        response["reason"] = "capture_error"
        return response
    mappings = queries.capture_list_models(connection, capture_id=cid)
    label_profile = endpoint_label_profile(profile)
    columns = {}
    paths = {}
    for listing in listings:
        if not listing.succeeded:
            continue
        paths[listing.list_path] = len(response["lists"])
        mapped = mappings.get(listing.list_path, [])
        response["lists"].append({"path": listing.list_path, "display_id": listing.display_id,
                                  "models": [item["model_id"] for item in mapped if item["outcome"] == "listed"],
                                  "aliases": [item["model_id"] for item in mapped if item["outcome"] == "alias"]})
        for column in endpoint_price_table(listing, label_profile).columns:
            columns.setdefault(column.path, {"path": column.path, "label": column.label,
                               "unit_label": column.unit_label, "comparison_group": column.comparison_group})
    response["price_columns"] = [columns[path] for path in sorted(columns, key=lambda p: pricing_field_sort_key(p, label_profile))]
    raw_rows = [row for row in queries.capture_endpoint_rows(connection, capture_id=cid) if row["list_path"] in paths]
    parameter_sets, tool_sets, leaves = [], [], []
    for row in raw_rows:
        state = row["state"]
        parameters = _strings(state.get("supported_parameters"))
        tools = sorted(state["native_tools"]) if isinstance(state.get("native_tools"), dict) else []
        parameter_sets.append(parameters)
        tool_sets.append(tools)
        leaves.append(state_price_leaves(state, label_profile))
        quantization = state.get("quantization")
        if not isinstance(quantization, str):
            quantization = "unknown"
        tier = state.get("service_tier")
        response["endpoints"].append({
            "list": paths[row["list_path"]], "key": row["endpoint_key"],
            "host": host_name(state.get("provider_name"), state.get("name"), state.get("tag"), row["endpoint_key"]),
            "tag": state.get("tag") if isinstance(state.get("tag"), str) else None,
            "status": row["status_code"], "quantization": quantization,
            "precision_bits": quantization_bits(quantization),
            "context_length": state.get("context_length"),
            "max_completion_tokens": state.get("max_completion_tokens"), "max_prompt_tokens": state.get("max_prompt_tokens"),
            "service_tier": tier if isinstance(tier, str) else None,
            "parameters": [], "native_tools": [], "implicit_caching": state.get("supports_implicit_caching") is True,
            "prices": {}, "uptime": {window: row[f"uptime_{window}"] if status["available"] else None for window in ("1d", "30m", "5m")},
        })
    endpoints = response["endpoints"]
    vocab = response["vocab"]
    vocab["parameters"] = sorted({value for values in parameter_sets for value in values})
    vocab["native_tools"] = sorted({value for values in tool_sets for value in values})
    vocab["quantizations"] = sorted({row["quantization"] for row in endpoints})
    vocab["tiers"] = sorted({row["service_tier"] for row in endpoints}, key=lambda value: (value is not None, value or ""))
    parameter_indexes = {value: index for index, value in enumerate(vocab["parameters"])}
    tool_indexes = {value: index for index, value in enumerate(vocab["native_tools"])}
    for row, parameters, tools in zip(endpoints, parameter_sets, tool_sets):
        row["parameters"] = [parameter_indexes[value] for value in parameters]
        row["native_tools"] = [tool_indexes[value] for value in tools]
    for column in response["price_columns"]:
        path = column["path"]
        present = [(index, row[path]) for index, row in enumerate(leaves) if path in row]
        displays = format_price_values([leaf.price for _, leaf in present], precision_basis=())
        for (index, leaf), display in zip(present, displays):
            exact = leaf.normalized_exact_value
            endpoints[index]["prices"][path] = {"exact": {"numerator_hex": format(exact.numerator, "x"), "denominator_hex": format(exact.denominator, "x")}, "display": display, "raw": leaf.raw_value}
    grouped = defaultdict(list)
    for row in endpoints:
        grouped[row["host"]].append(row)
    for name, rows in sorted(grouped.items()):
        samples = [row["uptime"]["1d"] for row in rows if row["uptime"]["1d"] is not None]
        response["hosts"].append({"name": name, "endpoint_count": len(rows), "list_count": len({row["list"] for row in rows}), "uptime_1d_median": median(samples) if samples else None})
    return response


def host_history_response(connection: sqlite3.Connection, *, provider_id: str, host: str,
                          profile: ProviderProfile, since: date | None, until: date | None) -> dict[str, Any]:
    series = queries.host_series(connection, provider_id=provider_id, host=host, since=since, until=until)
    telemetry = "available" if queries.endpoint_telemetry_present(connection) else "no_tables"
    if telemetry == "available" and any(not queries.capture_telemetry_status(connection, capture_id=row["capture"]["capture_id"])["available"] for row in series):
        telemetry = "pending"
    for row in series:
        row["date"] = row["date"].isoformat()
        row["capture"] = capture_status(row["capture"])
    limit = DOSSIER_ENDPOINT_CHANGE_LIMIT
    rows = queries.host_changes(connection, provider_id=provider_id, host=host, since=since, until=until, limit=limit + 1)
    changes = []
    listings = {}
    label_profile = endpoint_label_profile(profile)
    for row in rows[:limit]:
        identity = row["to_capture_id"], row["list_path"]
        if identity not in listings:
            listing = queries.endpoint_capture_lists(connection, capture_id=identity[0], list_path=identity[1])
            if not listing:
                raise EndpointDataIntegrityError("endpoint change has no target list")
            listings[identity] = listing[0]
        listing = listings[identity]
        changes.append({**endpoint_change_json(row, listing, label_profile),
                        "list_path": listing.list_path, "display_id": listing.display_id})
    return {"host": host, "telemetry": telemetry, "series": series, "changes": changes,
            "limit": limit, "truncated": len(rows) > limit}
