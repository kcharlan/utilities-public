from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


CATEGORY_MAX = {
    "field_validity_basic": 20,
    "step_alignment": 15,
    "lists_and_ranges": 10,
    "dom_dow_interaction": 15,
    "l_and_w": 10,
    "calendar_edges": 15,
    "timezone_dst": 10,
    "errors": 5,
}


def _load_model(workspace: Path):
    module_path = workspace / "cron_eval.py"
    spec = importlib.util.spec_from_file_location("cron_eval_model", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cron_eval_model"] = module
    spec.loader.exec_module(module)
    return module


def _parse_after(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _serialize_dt(value: Any) -> str:
    if not isinstance(value, datetime):
        return repr(value)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.isoformat()
    return value.isoformat()


def _serialize_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, list):
        return {"kind": "other", "value": repr(result)}
    return {"kind": "fires", "value": [_serialize_dt(item) for item in result]}


def _matches_expected_fires(actual: Any, expected: list[str]) -> bool:
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    for item, expected_text in zip(actual, expected):
        if not isinstance(item, datetime):
            return False
        if item.tzinfo is None or item.utcoffset() is None:
            return False
        expected_dt = datetime.fromisoformat(expected_text)
        if (
            item.year,
            item.month,
            item.day,
            item.hour,
            item.minute,
            item.utcoffset(),
        ) != (
            expected_dt.year,
            expected_dt.month,
            expected_dt.day,
            expected_dt.hour,
            expected_dt.minute,
            expected_dt.utcoffset(),
        ):
            return False
    return True


def _diff_summary(expected: dict[str, Any], actual: dict[str, Any]) -> str:
    if expected["kind"] == "raises":
        if actual["kind"] == "raises":
            return f"expected {expected['value']}; got {actual['value']}"
        return f"expected {expected['value']}; got {actual['kind']}"
    if actual["kind"] != "fires":
        return f"expected fires list; got {actual['kind']}"
    expected_values = expected.get("value", [])
    actual_values = actual.get("value", [])
    if len(expected_values) != len(actual_values):
        return f"expected {len(expected_values)} fires, got {len(actual_values)}"
    for index, (left, right) in enumerate(zip(expected_values, actual_values), start=1):
        if left != right:
            return f"fire {index} mismatch: expected {left}, got {right}"
    return "values did not match"


def _write_zero_score(run_dir: Path, reason: str) -> None:
    category_breakdown = {
        category: {"earned": 0, "max": maximum} for category, maximum in CATEGORY_MAX.items()
    }
    score = {"score": 0, "max_score": 100, "category_breakdown": category_breakdown, "import_ok": False}
    summary = {
        "total_cases": 0,
        "passed_cases": 0,
        "failed_cases": [
            {
                "id": "import_error",
                "category": "import",
                "weight": 100,
                "expected": {"kind": "import_ok", "value": True},
                "actual": {"kind": "import_error", "value": reason},
                "diff_summary": reason,
            }
        ],
        "per_category": {},
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "score.json").write_text(json.dumps(score, indent=2) + "\n", encoding="utf-8")
    (run_dir / "category_breakdown.json").write_text(
        json.dumps(category_breakdown, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "validation_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    run_dir = Path(argv[0])
    workspace = Path(argv[1])
    hidden_dir = Path(argv[2])
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        model = _load_model(workspace)
        invalid_cron_expr = model.InvalidCronExpr
    except Exception:
        _write_zero_score(run_dir, traceback.format_exc())
        return 0

    category_earned: dict[str, float] = defaultdict(float)
    category_total: dict[str, float] = defaultdict(float)
    per_category: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0})
    failed_cases: list[dict[str, Any]] = []
    total_cases = 0
    passed_cases = 0

    for path in sorted((hidden_dir / "conformance").glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        total_cases += 1
        category = fixture["category"]
        weight = float(fixture["weight"])
        category_total[category] += weight
        payload = dict(fixture["input"])
        payload["after"] = _parse_after(payload["after"])
        expected = fixture["expected"]
        try:
            result = model.next_fires(**payload)
        except Exception as exc:
            actual = {"kind": "raises", "value": type(exc).__name__}
            passed = (
                expected["kind"] == "raises"
                and isinstance(exc, invalid_cron_expr)
                and type(exc).__name__ == expected["value"]
            )
        else:
            actual = _serialize_result(result)
            passed = expected["kind"] == "fires" and _matches_expected_fires(result, expected["value"])

        if passed:
            passed_cases += 1
            category_earned[category] += weight
            per_category[category]["passed"] += 1
        else:
            per_category[category]["failed"] += 1
            failed_cases.append(
                {
                    "id": fixture["id"],
                    "category": category,
                    "weight": weight,
                    "expected": expected,
                    "actual": actual,
                    "diff_summary": _diff_summary(expected, actual),
                }
            )

    category_breakdown = {}
    for category, maximum in CATEGORY_MAX.items():
        earned = int(round(category_earned.get(category, 0.0)))
        category_breakdown[category] = {"earned": earned, "max": maximum}
        per_category.setdefault(category, {"passed": 0, "failed": 0})

    score_value = sum(item["earned"] for item in category_breakdown.values())
    score = {
        "score": score_value,
        "max_score": 100,
        "category_breakdown": category_breakdown,
        "import_ok": True,
    }
    summary = {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": failed_cases,
        "per_category": dict(per_category),
    }
    (run_dir / "score.json").write_text(json.dumps(score, indent=2) + "\n", encoding="utf-8")
    (run_dir / "category_breakdown.json").write_text(
        json.dumps(category_breakdown, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "validation_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
