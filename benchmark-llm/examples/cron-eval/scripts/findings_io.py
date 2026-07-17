from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FINDINGS_FILENAME = "benchmark_findings.jsonl"


def findings_path_for_run(run_dir: Path) -> Path:
    return run_dir / FINDINGS_FILENAME


def append_finding(path: Path, finding: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(finding) + "\n")


def load_findings(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    findings: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        findings.append(json.loads(stripped))
    return findings
