#!/usr/bin/env python3
"""Fixture worker: alternates real output and detail lines, then exits cleanly.

Used to verify that real (non-detail) output still resets the idle timer,
preventing false idle timeouts when genuine work is being done.
"""
import sys
import time
from pathlib import Path

task_path = Path(sys.argv[1])
task_id = task_path.name.removesuffix(".plan.md")
status_path = task_path.with_name(task_id + ".status")

print(f"##PROGRESS## {task_id} | Phase: implementing | 3/5", flush=True)
print(f"##PROGRESS## {task_id} | Detail: background check", flush=True)
time.sleep(0.4)
print("doing real work", flush=True)
print(f"##PROGRESS## {task_id} | Detail: another check", flush=True)
time.sleep(0.4)
print("more real work", flush=True)
status_path.write_text(
    "STATUS: done\nCOMMITS: none\nTESTS_RAN: none\nTEST_RESULT: skip\n",
    encoding="utf-8",
)
