from __future__ import annotations

import json
import sys
from pathlib import Path

from eval_helpers import render_template


def _status_value(adjudication: dict[str, object], new_key: str, old_key: str) -> str:
    value = adjudication.get(new_key)
    if value not in (None, ""):
        return str(value)
    legacy = adjudication.get(old_key, "")
    return "" if legacy is None else str(legacy)


def _finding_value(adjudication: dict[str, object], index: int) -> str:
    findings = adjudication.get("findings")
    if not isinstance(findings, list) or index >= len(findings):
        return ""
    value = findings[index]
    return "" if value is None else str(value)


def main() -> int:
    run_dir = Path(sys.argv[1])
    template_path = Path(sys.argv[2])
    adjudication = json.loads((run_dir / "adjudication.json").read_text(encoding="utf-8"))

    normalized = {
        "summary": {
            "score_percent": float(adjudication["score_percent"]),
        },
        "status_summaries": [
            {
                "name": "Visible set summary",
                "value": _status_value(adjudication, "visible_summary", "visible_pass_fail"),
            },
            {
                "name": "Hidden C summary",
                "value": _status_value(adjudication, "hidden_c_summary", "hidden_c_pass_fail"),
            },
            {
                "name": "Hidden D summary",
                "value": _status_value(adjudication, "hidden_d_summary", "hidden_d_pass_fail"),
            },
            {
                "name": "Mutation summary",
                "value": _status_value(adjudication, "mutation_summary", "mutation_result"),
            },
        ],
        "adjudication": adjudication,
    }
    (run_dir / "score.json").write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")

    template_text = template_path.read_text(encoding="utf-8")
    report_text = render_template(
        template_text,
        {
            "model": adjudication.get("model", ""),
            "provider": adjudication.get("provider", ""),
            "date": adjudication.get("date", ""),
            "time_started": adjudication.get("time_started", ""),
            "time_ended": adjudication.get("time_ended", ""),
            "elapsed_minutes": adjudication.get("elapsed_minutes", ""),
            "cost": adjudication.get("cost", "unknown"),
            "turns": adjudication.get("turns", ""),
            "interventions": adjudication.get("interventions", ""),
            "visible_summary": _status_value(adjudication, "visible_summary", "visible_pass_fail"),
            "hidden_c_summary": _status_value(adjudication, "hidden_c_summary", "hidden_c_pass_fail"),
            "hidden_d_summary": _status_value(adjudication, "hidden_d_summary", "hidden_d_pass_fail"),
            "mutation_summary": _status_value(adjudication, "mutation_summary", "mutation_result"),
            "final_score": adjudication.get("final_score", ""),
            "notes": adjudication.get("notes", ""),
            "finding_1": _finding_value(adjudication, 0),
            "finding_2": _finding_value(adjudication, 1),
            "finding_3": _finding_value(adjudication, 2),
            "score_visible": adjudication.get("score_breakdown", {}).get("visible", ""),
            "score_hidden_generalization": adjudication.get("score_breakdown", {}).get(
                "hidden_generalization", ""
            ),
            "score_hidden_robustness": adjudication.get("score_breakdown", {}).get(
                "hidden_robustness", ""
            ),
            "score_code_quality": adjudication.get("score_breakdown", {}).get("code_quality", ""),
            "score_cli": adjudication.get("score_breakdown", {}).get("cli_output_usability", ""),
            "score_tests_docs": adjudication.get("score_breakdown", {}).get("tests_docs", ""),
            "score_run_behavior": adjudication.get("score_breakdown", {}).get(
                "run_behavior_efficiency", ""
            ),
        },
    )
    (run_dir / "report.md").write_text(report_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
