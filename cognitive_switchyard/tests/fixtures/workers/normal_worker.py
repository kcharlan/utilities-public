#!/usr/bin/env python3
import sys
from pathlib import Path

task_path = Path(sys.argv[1])
workspace_path = Path(sys.argv[2])
assert workspace_path == Path.cwd()

print("worker starting", flush=True)
task_id = task_path.name.removesuffix(".plan.md")
print(f"##PROGRESS## {task_id} | Phase: implementing | 3/5", flush=True)
status_path = task_path.with_name(task_path.name.removesuffix(".plan.md") + ".status")
status_path.write_text(
    "STATUS: done\n"
    "COMMITS: abc1234\n"
    "TESTS_RAN: targeted\n"
    "TEST_RESULT: pass\n",
    encoding="utf-8",
)
print("worker completed", flush=True)
