from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from findings_io import append_finding, findings_path_for_run

EXCLUDED_PARTS = {".venv", "__pycache__", "tests"}


def run_command(command: list[str], cwd: Path) -> dict:
    started = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    ended = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "started_at": started,
        "ended_at": ended,
    }


def _is_source_candidate(path: Path, workspace: Path) -> bool:
    parts = set(path.relative_to(workspace).parts)
    return not parts.intersection(EXCLUDED_PARTS)


def find_mutation_target(workspace: Path) -> Path | None:
    candidates = sorted(path for path in workspace.rglob("*.py") if _is_source_candidate(path, workspace))

    preferred: list[Path] = []
    fallback: list[Path] = []
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "unmatched" not in text:
            continue
        if "match_status" in text:
            preferred.append(path)
        else:
            fallback.append(path)

    search_pool = preferred or fallback
    return search_pool[0] if search_pool else None


def _failed_test_count(command: dict) -> int | None:
    combined = "\n".join(part for part in (command["stdout"], command["stderr"]) if part)
    match = re.search(r"(\d+) failed", combined)
    if match:
        return int(match.group(1))
    return None


def run_mutation_test(workspace: Path) -> dict:
    target = find_mutation_target(workspace)
    if target is None:
        return {
            "phase": "mutation_probe",
            "kind": "test_finding",
            "label": "unmatched_branch_mutation",
            "status": "inconclusive",
            "summary": "No source file containing an unmatched branch was found for the mutation probe.",
            "details": {},
        }

    original_text = target.read_text(encoding="utf-8")
    mutated_text = original_text.replace("unmatched", "matched", 1)
    if mutated_text == original_text:
        return {
            "phase": "mutation_probe",
            "kind": "test_finding",
            "label": "unmatched_branch_mutation",
            "status": "inconclusive",
            "summary": f"Mutation replacement did not change {target.name}.",
            "details": {"target_file": str(target.relative_to(workspace))},
        }

    backup_path = target.with_suffix(target.suffix + ".bench-backup")
    backup_path.write_text(original_text, encoding="utf-8")
    try:
        target.write_text(mutated_text, encoding="utf-8")
        command = run_command([sys.executable, "-m", "pytest", "-q"], workspace)
    finally:
        target.write_text(original_text, encoding="utf-8")
        backup_path.unlink(missing_ok=True)

    failed_tests = _failed_test_count(command)
    target_name = str(target.relative_to(workspace))
    if command["exit_code"] != 0:
        count_text = f"{failed_tests} pytest failures" if failed_tests is not None else "pytest failures"
        summary = f"Mutating unmatched->matched in {target_name} caused {count_text}."
        status = "detected"
    else:
        summary = f"Mutating unmatched->matched in {target_name} did not fail pytest."
        status = "missed"

    return {
        "phase": "mutation_probe",
        "kind": "test_finding",
        "label": "unmatched_branch_mutation",
        "status": status,
        "summary": summary,
        "details": {
            "target_file": target_name,
            "pytest_exit_code": command["exit_code"],
            "failed_tests": failed_tests,
        },
        "command": command,
    }


def main() -> int:
    run_dir = Path(sys.argv[1])
    workspace = Path(sys.argv[2])
    finding = run_mutation_test(workspace)
    append_finding(findings_path_for_run(run_dir), finding)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
