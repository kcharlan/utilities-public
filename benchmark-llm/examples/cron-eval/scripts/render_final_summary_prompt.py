from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


_TABLE_ROW_RE = re.compile(r"^\|\s*(?P<field>[^|]+?)\s*\|\s*(?P<value>[^|]+?)\s*\|$")


def _extract_topline_fields(report_text: str) -> dict[str, str]:
    extracted: dict[str, str] = {}
    for line in report_text.splitlines():
        match = _TABLE_ROW_RE.match(line.strip())
        if not match:
            continue
        field = match.group("field").strip().lower()
        value = match.group("value").strip()
        if field in {"field", "---"}:
            continue
        extracted[field] = value
    return extracted


def _score_stats(runs: list[dict[str, Any]]) -> dict[str, float] | None:
    scores = [float(run["score_percent"]) for run in runs if run.get("score_percent") is not None]
    if not scores:
        return None
    return {
        "min": min(scores),
        "max": max(scores),
        "avg": round(sum(scores) / len(scores), 2),
    }


def _build_overview(summary_payload: dict[str, Any]) -> dict[str, Any]:
    runs = list(summary_payload.get("runs", []))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    retry_reason_counts: Counter[str] = Counter()
    for run in runs:
        grouped[str(run["model"])].append(run)
        for attempt in run.get("attempts", []):
            retry_reason = attempt.get("retry_reason")
            if retry_reason:
                retry_reason_counts[str(retry_reason)] += 1

    return {
        "configured_runs_per_model": summary_payload.get("settings", {}).get("runs"),
        "run_order": summary_payload.get("settings", {}).get("run_order"),
        "total_runs": len(runs),
        "successful_runs": sum(1 for run in runs if run.get("status") == "succeeded"),
        "failed_runs": sum(1 for run in runs if run.get("status") == "failed"),
        "model_count": len(grouped),
        "model_completion": {
            model: {
                "attempted_runs": len(model_runs),
                "successful_runs": sum(1 for run in model_runs if run.get("status") == "succeeded"),
                "failed_runs": sum(1 for run in model_runs if run.get("status") == "failed"),
            }
            for model, model_runs in sorted(grouped.items())
        },
        "retry_reason_counts": dict(sorted(retry_reason_counts.items())),
    }


def build_prompt(benchmark_dir: Path, summary_input_path: Path) -> str:
    summary_payload = json.loads(summary_input_path.read_text(encoding="utf-8"))
    benchmark_name = benchmark_dir.name
    runs = list(summary_payload.get("runs", []))
    grouped_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped_runs[str(run["model"])].append(run)

    sections = [
        f"You are writing the final synthesized benchmark summary for the `{benchmark_name}` benchmark.",
        "Return markdown only.",
        "",
        "Required output structure:",
        "1. An Executive Summary with the main takeaways, strongest models, weakest models, and major caveats.",
        "2. A Benchmark Run Overview that summarizes the benchmark execution itself: completion rates, retries, failure modes, API/tool dropouts, and any important harness observations.",
        "3. A Synthesized Narrative that compares the runs as a set while treating each run as an independent sample.",
        "4. A Model Commentary section organized by model, where each subsection summarizes that model across all of its runs.",
        "5. A Topline Results table at the end covering each run.",
        "",
        "Use supporting quotes or evidence from report.md only when they directly support a claim. Keep quotes short. Do not invent evidence.",
        "Treat each run as an independent sample from an isolated worktree. Do not imply that a model improved over time, learned across runs, or benefited from cross-run state unless the provided evidence explicitly proves that causal mechanism.",
        "Model Commentary must summarize each model across all of its runs. Do not write one commentary subsection per run.",
        "When a model has multiple runs, discuss spread, consistency, and outliers at the model level and cite representative runs as evidence.",
        "Use the benchmark run overview data directly, including configured runs per model and retry reason counts.",
        "The Topline Results table belongs at the end, after the narrative sections.",
        "",
        "Required headings:",
        "# Benchmark Summary",
        "## Executive Summary",
        "## Benchmark Run Overview",
        "## Synthesized Narrative",
        "## Model Commentary",
        "## Topline Results",
        "",
        "Benchmark run overview data:",
        json.dumps(_build_overview(summary_payload), indent=2, sort_keys=True),
        "",
        "Model aggregate context:",
    ]

    for model, model_runs in sorted(grouped_runs.items()):
        successful_runs = [run for run in model_runs if run.get("status") == "succeeded"]
        failed_runs = [run for run in model_runs if run.get("status") == "failed"]
        sections.extend(
            [
                "",
                f"Model: {model}",
                json.dumps(
                    {
                        "total_runs": len(model_runs),
                        "successful_runs": len(successful_runs),
                        "failed_runs": len(failed_runs),
                        "score_stats": _score_stats(successful_runs),
                        "retry_reason_counts": dict(
                            sorted(
                                Counter(
                                    str(attempt["retry_reason"])
                                    for run in model_runs
                                    for attempt in run.get("attempts", [])
                                    if attempt.get("retry_reason")
                                ).items()
                            )
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                ),
            ]
        )
        for run in model_runs:
            sections.extend(
                [
                    "",
                    f"Run ID: {run['run_id']}",
                    f"Status: {run.get('status', '')}",
                    f"Score percent: {run.get('score_percent', '')}",
                    "Attempt details:",
                    json.dumps(run.get("attempts", []), indent=2, sort_keys=True),
                ]
            )
            if run.get("report_path"):
                report_path = Path(run["report_path"])
                report_text = report_path.read_text(encoding="utf-8")
                sections.extend(
                    [
                        "Extracted topline fields from report.md:",
                        json.dumps(_extract_topline_fields(report_text), indent=2, sort_keys=True),
                        "Full report.md:",
                        report_text,
                    ]
                )
            else:
                sections.extend(
                    [
                        "Failure summary:",
                        json.dumps(run.get("failure_summary", {}), indent=2, sort_keys=True),
                    ]
                )

    return "\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    benchmark_dir = Path(argv[0])
    summary_input_path = Path(argv[1])
    sys.stdout.write(build_prompt(benchmark_dir, summary_input_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
