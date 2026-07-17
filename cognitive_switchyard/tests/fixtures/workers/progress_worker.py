#!/usr/bin/env python3
import sys
from pathlib import Path

task_path = Path(sys.argv[1])
workspace_path = Path(sys.argv[2])
assert workspace_path == Path.cwd()

task_id = task_path.name.removesuffix(".plan.md")
print("raw before markers", flush=True)
print(f"##PROGRESS## {task_id} | Phase: implementing | 3/5", flush=True)
print(f"##PROGRESS## {task_id} | Detail: Processing chunk 3/9", flush=True)
print("raw after markers", flush=True)
task_path.with_name(task_path.name.removesuffix(".plan.md") + ".status").write_text(
    "STATUS: done\n"
    "COMMITS: none\n"
    "TESTS_RAN: none\n"
    "TEST_RESULT: skip\n",
    encoding="utf-8",
)
