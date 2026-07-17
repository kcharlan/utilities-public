#!/usr/bin/env python3
import sys
import time
from pathlib import Path

task_path = Path(sys.argv[1])
workspace_path = Path(sys.argv[2])
assert workspace_path == Path.cwd()

task_id = task_path.name.removesuffix(".plan.md").split("_", 1)[0]

print("worker starting", flush=True)
print(f"##PROGRESS## {task_id} | Phase: implementing | 1/2", flush=True)
time.sleep(0.25)
print(f"##PROGRESS## {task_id} | Detail: Streaming detail", flush=True)
print("worker completed", flush=True)
time.sleep(0.25)
task_path.with_name(task_path.name.removesuffix(".plan.md") + ".status").write_text(
    "STATUS: done\n"
    "COMMITS: none\n"
    "TESTS_RAN: targeted\n"
    "TEST_RESULT: pass\n",
    encoding="utf-8",
)
