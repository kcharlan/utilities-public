from __future__ import annotations

import json
import sys
from pathlib import Path


LABELS = {
    "field_validity_basic": "Field validity (basic)",
    "step_alignment": "Step alignment",
    "lists_and_ranges": "Lists and ranges",
    "dom_dow_interaction": "DOM/DOW interaction",
    "l_and_w": "L and W",
    "calendar_edges": "Calendar edges",
    "timezone_dst": "Timezone & DST",
    "errors": "Errors",
}


def fallback_report(run_dir: Path, model: str) -> str:
    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    breakdown = json.loads((run_dir / "category_breakdown.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "validation_summary.json").read_text(encoding="utf-8"))
    rows = "\n".join(
        f"| {LABELS[key]} | {value['earned']} | {value['max']} |"
        for key, value in breakdown.items()
    )
    if summary.get("failed_cases"):
        failures = "\n".join(f"- {case['id']}: {case['diff_summary']}" for case in summary["failed_cases"][:20])
    else:
        failures = "All categories clean. No failures to analyze."
    return f"""# Cron-Eval Run Report

| Field | Value |
| --- | --- |
| Model | {model} |
| Final score | {score['score']}/{score['max_score']} |

## Score Breakdown

| Category | Earned | Max |
| --- | ---: | ---: |
{rows}

## Failure Analysis

{failures}
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    run_dir = Path(argv[0])
    model = argv[1] if len(argv) > 1 else ""
    report_path = run_dir / "report.md"
    if not report_path.exists() or not report_path.read_text(encoding="utf-8").strip():
        report_path.write_text(fallback_report(run_dir, model), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
