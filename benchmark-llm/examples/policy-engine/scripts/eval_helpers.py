from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


def load_json_or_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    return json.loads(text)


def extract_output_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    if isinstance(payload, dict):
        for key in ("results", "rows", "output", "benefits"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value]
    raise ValueError("Could not locate output rows in policy engine payload.")


def normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip()).lower()
    return value


def compare_expected_rows(
    actual_rows: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    indexed_actual = {
        normalize_value(row.get("original_service_category", "")): row for row in actual_rows
    }
    failures: list[str] = []
    for expected in expected_rows:
        key = normalize_value(expected.get("original_service_category", ""))
        if key not in indexed_actual:
            failures.append(f"Missing row for original_service_category={expected.get('original_service_category')!r}")
            continue
        actual = indexed_actual[key]
        for field, expected_value in expected.items():
            if normalize_value(actual.get(field)) != normalize_value(expected_value):
                failures.append(
                    f"Row {expected.get('original_service_category')!r} field {field!r}: "
                    f"expected {expected_value!r}, got {actual.get(field)!r}"
                )
    return {
        "passed": not failures,
        "failures": failures,
    }


def render_template(template_text: str, values: dict[str, str]) -> str:
    rendered = template_text
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", str(value))
    return rendered
