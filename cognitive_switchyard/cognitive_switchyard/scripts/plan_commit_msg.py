#!/usr/bin/env python3
"""Generate a git commit message from a plan file.

Usage: python3 plan_commit_msg.py <plan_file_path> <task_id> <slot_number>

Prints the commit message to stdout and exits 0. Never exits non-zero —
this must never block a merge.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add package root to path so this script can be called directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cognitive_switchyard.parsers import (  # noqa: E402
    ArtifactParseError,
    extract_commit_description,
    parse_task_plan,
)


def _fallback_message(task_id: str, slot_number: str) -> str:
    return f"feat: merge task {task_id} from slot {slot_number}"


def main() -> None:
    if len(sys.argv) < 4:
        print(_fallback_message("unknown", "unknown"))
        sys.exit(0)

    plan_file_path = sys.argv[1]
    task_id = sys.argv[2]
    slot_number = sys.argv[3]

    fallback = _fallback_message(task_id, slot_number)

    try:
        plan_text = Path(plan_file_path).read_text(encoding="utf-8")
    except OSError:
        print(fallback)
        sys.exit(0)

    try:
        plan = parse_task_plan(plan_text)
    except ArtifactParseError:
        print(fallback)
        sys.exit(0)

    title = plan.title
    description = extract_commit_description(plan.body)

    # Subject line: "feat: <title>" truncated to 72 chars
    subject = f"feat: {title}"
    if len(subject) > 72:
        subject = subject[:69] + "..."

    parts = [subject]
    if description:
        parts.append("")
        parts.append(description)
    parts.append("")
    parts.append(f"Task: {task_id} (slot {slot_number})")

    print("\n".join(parts))
    sys.exit(0)


if __name__ == "__main__":
    main()
