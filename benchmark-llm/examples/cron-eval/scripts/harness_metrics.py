from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
OPENCODE_SESSION_PATTERN = re.compile(r"\bses_[A-Za-z0-9]+\b")

FIELD_ALIASES = {
    "input_tokens": {"input_tokens", "inputtokens", "prompt_tokens", "prompttokens"},
    "output_tokens": {"output_tokens", "outputtokens", "completion_tokens", "completiontokens"},
    "total_tokens": {"total_tokens", "totaltokens"},
    "cost_usd": {"cost_usd", "costusd", "total_cost_usd", "totalcostusd", "cost"},
    "provider_latency_ms": {"provider_latency_ms", "providerlatencyms", "latency_ms", "duration_ms"},
    "turns": {"turns", "turn_count", "turncount", "message_count", "messagecount", "num_turns"},
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _collect_candidates(payload: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    found: list[tuple[tuple[str, ...], Any]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            next_path = (*path, str(key))
            found.append((next_path, value))
            found.extend(_collect_candidates(value, next_path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(_collect_candidates(value, (*path, str(index))))
    return found


def _normalize_metric_value(field: str, value: Any) -> float | int | None:
    try:
        if field == "cost_usd":
            return round(float(value), 6)
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_opencode_step_totals(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        return {}

    totals: dict[str, Any] = {}
    step_count = 0
    for row in payload:
        if not isinstance(row, dict) or row.get("type") != "step_finish":
            continue
        part = row.get("part")
        if not isinstance(part, dict):
            continue
        step_count += 1

        cost = _normalize_metric_value("cost_usd", part.get("cost"))
        if cost is not None:
            totals["cost_usd"] = round(float(totals.get("cost_usd", 0.0)) + float(cost), 6)

        tokens = part.get("tokens")
        if isinstance(tokens, dict):
            for source, target in (
                ("input", "input_tokens"),
                ("output", "output_tokens"),
                ("total", "total_tokens"),
            ):
                value = _normalize_metric_value(target, tokens.get(source))
                if value is not None:
                    totals[target] = int(totals.get(target, 0)) + int(value)

    if step_count:
        totals["turns"] = step_count
    return totals


def extract_metrics_from_payload(payload: Any) -> dict[str, Any]:
    collected: dict[str, float | int] = {}
    for path, value in _collect_candidates(payload):
        key = path[-1].replace("-", "_").lower()
        parent = path[-2].replace("-", "_").lower() if len(path) > 1 else ""
        for canonical, aliases in FIELD_ALIASES.items():
            if key not in aliases:
                continue
            if key == "cost" and parent not in {"info", "part", "result", "usage"}:
                continue
            normalized = _normalize_metric_value(canonical, value)
            if normalized is None:
                continue
            current = collected.get(canonical)
            if current is None or normalized > current:
                collected[canonical] = normalized

        if parent == "tokens" and key in {"input", "output", "total"}:
            canonical = {
                "input": "input_tokens",
                "output": "output_tokens",
                "total": "total_tokens",
            }[key]
            normalized = _normalize_metric_value(canonical, value)
            if normalized is not None:
                current = collected.get(canonical)
                if current is None or normalized > current:
                    collected[canonical] = normalized

        if key == "time" and isinstance(value, dict):
            created = value.get("created")
            completed = value.get("completed")
            if created is not None and completed is not None:
                normalized = _normalize_metric_value(
                    "provider_latency_ms",
                    float(completed) - float(created),
                )
                if normalized is not None:
                    current = collected.get("provider_latency_ms")
                    if current is None or normalized > current:
                        collected["provider_latency_ms"] = normalized
    if (
        "total_tokens" not in collected
        and "input_tokens" in collected
        and "output_tokens" in collected
    ):
        collected["total_tokens"] = int(collected["input_tokens"]) + int(collected["output_tokens"])

    step_totals = _extract_opencode_step_totals(payload)
    if step_totals:
        collected.update(step_totals)
    return collected


def extract_opencode_session_id(payload: Any) -> str | None:
    for path, value in _collect_candidates(payload):
        key = path[-1].replace("-", "_").lower()
        if key not in {"sessionid", "session_id"}:
            continue
        if isinstance(value, str):
            match = OPENCODE_SESSION_PATTERN.search(value)
            if match:
                return match.group(0)
            match = UUID_PATTERN.search(value)
            if match:
                return match.group(0)
    for _, value in _collect_candidates(payload):
        if isinstance(value, str):
            match = OPENCODE_SESSION_PATTERN.search(value)
            if match:
                return match.group(0)
            match = UUID_PATTERN.search(value)
            if match:
                return match.group(0)
    return None


def command_opencode_session_id(events_path: Path) -> int:
    session_id = extract_opencode_session_id(_read_jsonl(events_path))
    if not session_id:
        return 1
    sys.stdout.write(session_id)
    return 0


def command_extract_metrics(paths: list[Path]) -> int:
    merged: dict[str, Any] = {}
    for path in paths:
        if not path.exists():
            continue
        payload = _read_jsonl(path) if path.suffix == ".jsonl" else _read_json(path)
        metrics = extract_metrics_from_payload(payload)
        for key, value in metrics.items():
            current = merged.get(key)
            if current is None or value > current:
                merged[key] = value
    sys.stdout.write(json.dumps(merged, indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        raise SystemExit("usage: harness_metrics.py <command> [args...]")
    command = argv[0]
    if command == "opencode-session-id":
        return command_opencode_session_id(Path(argv[1]))
    if command in {"extract-opencode-metrics", "extract-codex-metrics", "extract-claude-metrics"}:
        return command_extract_metrics([Path(item) for item in argv[1:]])
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
