from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path


SOURCE_LIMIT = 10_000


def _read_json(path: Path) -> str:
    return json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2)


def _source_snapshot(workspace: Path) -> str:
    chunks: list[str] = []
    remaining = SOURCE_LIMIT
    for path in sorted(workspace.glob("*.py")):
        if remaining <= 0:
            break
        text = path.read_text(encoding="utf-8", errors="replace")
        block = f"# {path.name}\n{text}\n"
        chunks.append(block[:remaining])
        remaining -= len(chunks[-1])
    return "\n".join(chunks)


def render(benchmark_dir: Path, run_dir: Path, workspace: Path, model: str) -> str:
    template = (benchmark_dir / "hidden" / "adjudicator_prompt.md").read_text(encoding="utf-8")
    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    category_breakdown = _read_json(run_dir / "category_breakdown.json")
    validation_summary = _read_json(run_dir / "validation_summary.json")
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    replacements = {
        "{{ score }}": str(score.get("score", 0)),
        "{{ max_score }}": str(score.get("max_score", 100)),
        "{{ model }}": model,
        "{{ provider }}": model.split("/", 1)[0] if "/" in model else "unknown",
        "{{ date }}": now[:10],
        "{{ time_started }}": "",
        "{{ time_ended }}": now,
        "{{ elapsed_minutes }}": "",
        "{{ cost }}": "",
        "{{ score_json }}": _read_json(run_dir / "score.json"),
        "{{ category_breakdown_json }}": category_breakdown,
        "{{ validation_summary_json }}": validation_summary,
        "{{ source_code }}": _source_snapshot(workspace),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    benchmark_dir = Path(argv[0])
    run_dir = Path(argv[1])
    workspace = Path(argv[2])
    model = argv[3]
    sys.stdout.write(render(benchmark_dir, run_dir, workspace, model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
