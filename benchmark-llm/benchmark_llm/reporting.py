from __future__ import annotations

from pathlib import Path
from typing import Any


def _format_elapsed(elapsed_ms: Any) -> str:
    if elapsed_ms is None:
        return ""
    value = int(elapsed_ms)
    if value < 1000:
        return f"{value} ms"
    seconds = value / 1000.0
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes = seconds / 60.0
    return f"{minutes:.2f} min"


def build_markdown_report(manifest: dict[str, Any], score: dict[str, Any]) -> str:
    metrics = manifest.get("metrics", {})
    lines = [
        "# Benchmark Run Report",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Run ID | {manifest['run_id']} |",
        f"| Benchmark | {manifest['benchmark']['id']} |",
        f"| Mode | {manifest['benchmark']['mode']} |",
        f"| Model | {manifest['model']} |",
        f"| Started | {manifest['started_at']} |",
        f"| Ended | {manifest['ended_at']} |",
        f"| Elapsed | {_format_elapsed(manifest.get('timing', {}).get('elapsed_ms'))} |",
        f"| Cost (USD) | {metrics.get('cost_usd', '')} |",
        f"| Input Tokens | {metrics.get('input_tokens', '')} |",
        f"| Output Tokens | {metrics.get('output_tokens', '')} |",
        f"| Total Tokens | {metrics.get('total_tokens', '')} |",
        f"| Score | {score['summary']['score_percent']:.1f}% |",
        "",
    ]
    summary = score.get("summary", {})
    if "passed" in summary and "total" in summary:
        lines.extend(
            [
                "## Summary",
                "",
                f"- Passed: {summary['passed']}",
                f"- Total: {summary['total']}",
                f"- Score percent: {summary['score_percent']:.1f}%",
                "",
            ]
        )
    checks = score.get("checks", [])
    if checks:
        lines.extend(
            [
                "## Checks",
                "",
                "| Check | Passed |",
                "| --- | --- |",
            ]
        )
        for check in checks:
            lines.append(f"| {check['name']} | {'yes' if check['passed'] else 'no'} |")
        lines.append("")
    return "\n".join(lines)


def write_report(run_dir: Path, manifest: dict[str, Any], score: dict[str, Any]) -> Path:
    report_path = run_dir / "report.md"
    if report_path.exists():
        return report_path
    report_path.write_text(build_markdown_report(manifest, score), encoding="utf-8")
    return report_path
