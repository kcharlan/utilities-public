from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
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


_MODEL_CHILD = r'''
import contextlib, importlib.util, json, resource, sys
from datetime import datetime
resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
inputs = json.load(sys.stdin)
try:
    with contextlib.redirect_stdout(sys.stderr):
        spec = importlib.util.spec_from_file_location("cron_eval_model", sys.argv[1])
        module = importlib.util.module_from_spec(spec)
        sys.modules["cron_eval_model"] = module
        spec.loader.exec_module(module)
        invalid = module.InvalidCronExpr
        results = []
        for item in inputs:
            item["after"] = datetime.fromisoformat(item["after"])
            try:
                value = module.next_fires(**item)
            except Exception as exc:
                results.append({"kind": "raises", "value": type(exc).__name__, "valid": isinstance(exc, invalid)})
            else:
                if isinstance(value, list) and all(isinstance(v, datetime) and v.tzinfo is not None and v.utcoffset() is not None for v in value):
                    results.append({"kind": "fires", "value": [v.isoformat() for v in value]})
                else:
                    results.append({"kind": "other", "value": "invalid result"})
    json.dump({"import_ok": True, "results": results}, sys.stdout)
except Exception as exc:
    json.dump({"import_ok": False, "error": str(exc)}, sys.stdout)
'''


def _run_model(workspace: Path, inputs: list[dict[str, Any]]) -> dict[str, Any]:
    helper_root_text = os.environ.get("BENCH_PROCESS_IDENTITY_ROOT", "")
    helper_root = Path(helper_root_text)
    if not helper_root_text or not helper_root.is_absolute() or not (helper_root / "cognitive_switchyard" / "process_identity.py").is_file():
        raise RuntimeError("BENCH_PROCESS_IDENTITY_ROOT must point to the checkout's cognitive_switchyard directory")
    sys.path.insert(0, str(helper_root))
    from cognitive_switchyard.process_identity import OwnedProcessGroup, ProcessGroupInspectionError, signal_owned_group

    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as input_file:
        input_file.write(json.dumps(inputs).encode())
        input_file.seek(0)
        process = None
        group = None
        termination_requested = False
        cleaning_up = False
        cleanup_allowed = True
        previous_handler = signal.getsignal(signal.SIGTERM)

        def terminate(signum, _frame):
            nonlocal termination_requested
            termination_requested = True
            # During Popen, defer the exception until its returned PID is owned.
            if group is not None and not cleaning_up:
                raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, terminate)
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-c", _MODEL_CHILD, str(workspace / "cron_eval.py")],
                stdin=input_file, stdout=output, stderr=subprocess.DEVNULL,
                env={key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR") if key in os.environ},
                start_new_session=True,
            )
            group = OwnedProcessGroup.capture(process)
            if termination_requested:
                raise SystemExit(128 + signal.SIGTERM)
            deadline = time.monotonic() + 60
            while os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(process.args, 60)
                select.select([], [], [], 0.05)
        except (PermissionError, ProcessGroupInspectionError):
            cleanup_allowed = False
            raise
        finally:
            cleaning_up = True
            try:
                if group is not None and cleanup_allowed:
                    signal_owned_group(group, signal.SIGKILL)
                    process.wait()
            finally:
                signal.signal(signal.SIGTERM, previous_handler)
        if termination_requested:
            raise SystemExit(128 + signal.SIGTERM)
        if process.returncode != 0:
            raise ValueError(f"model process exited {process.returncode}")
        output.seek(0)
        data = output.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("model output exceeds limit")
        payload = json.loads(data)
        if not isinstance(payload, dict) or not isinstance(payload.get("import_ok"), bool):
            raise ValueError("invalid model response")
        return payload


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
    score = {
        "score": 0,
        "max_score": 100,
        "category_breakdown": category_breakdown,
        "import_ok": False,
        "summary": {"passed": 0, "total": 0, "score_percent": 0.0},
    }
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

    fixtures = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((hidden_dir / "conformance").glob("*.json"))]
    try:
        response = _run_model(workspace, [dict(fixture["input"]) for fixture in fixtures])
        if not response["import_ok"]:
            raise ValueError(str(response.get("error", "model import failed")))
        results = response.get("results")
        if not isinstance(results, list) or len(results) != len(fixtures):
            raise ValueError("invalid model result count")
    except (OSError, ValueError, RecursionError, subprocess.TimeoutExpired) as exc:
        _write_zero_score(run_dir, str(exc))
        return 0

    category_earned: dict[str, float] = defaultdict(float)
    category_total: dict[str, float] = defaultdict(float)
    per_category: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0})
    failed_cases: list[dict[str, Any]] = []
    total_cases = 0
    passed_cases = 0

    for fixture, actual in zip(fixtures, results):
        total_cases += 1
        category = fixture["category"]
        weight = float(fixture["weight"])
        category_total[category] += weight
        expected = fixture["expected"]
        if not isinstance(actual, dict):
            actual = {"kind": "other", "value": "invalid response"}
        if actual.get("kind") == "raises" and not isinstance(actual.get("value"), str):
            actual = {"kind": "other", "value": "invalid response"}
        passed = False
        if actual.get("kind") == "raises":
            passed = expected["kind"] == "raises" and actual.get("valid") is True and actual.get("value") == expected["value"]
        elif actual.get("kind") == "fires" and isinstance(actual.get("value"), list):
            try:
                parsed = [datetime.fromisoformat(item) for item in actual["value"] if isinstance(item, str)]
                passed = len(parsed) == len(actual["value"]) and expected["kind"] == "fires" and _matches_expected_fires(parsed, expected["value"])
            except ValueError:
                pass
        else:
            actual = {"kind": "other", "value": "invalid response"}

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
        "summary": {"passed": passed_cases, "total": total_cases, "score_percent": float(score_value)},
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
