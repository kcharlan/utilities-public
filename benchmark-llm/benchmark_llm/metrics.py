from __future__ import annotations

from typing import Any


_SUMMABLE_KEYS = (
    "cost_usd",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "provider_latency_ms",
    "turns",
)


def normalize_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for key in _SUMMABLE_KEYS:
        value = normalized.get(key)
        if value is None:
            continue
        if key == "cost_usd":
            normalized[key] = round(float(value), 6)
        else:
            normalized[key] = int(value)
    if (
        normalized.get("total_tokens") is None
        and normalized.get("input_tokens") is not None
        and normalized.get("output_tokens") is not None
    ):
        normalized["total_tokens"] = int(normalized["input_tokens"]) + int(normalized["output_tokens"])
    return normalized


def aggregate_metrics(command_rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {}
    for row in command_rows:
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            continue
        normalized = normalize_metrics(metrics)
        for key in _SUMMABLE_KEYS:
            if key not in normalized:
                continue
            if key == "cost_usd":
                totals[key] = round(float(totals.get(key, 0.0)) + float(normalized[key]), 6)
            else:
                totals[key] = int(totals.get(key, 0)) + int(normalized[key])
    if not totals:
        return {}
    if (
        "total_tokens" not in totals
        and "input_tokens" in totals
        and "output_tokens" in totals
    ):
        totals["total_tokens"] = int(totals["input_tokens"]) + int(totals["output_tokens"])
    return totals
