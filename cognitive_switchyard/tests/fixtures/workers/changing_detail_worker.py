#!/usr/bin/env python3
"""Fixture worker: emits detail lines with changing content forever.

Used to verify that changing detail lines DO reset the idle timer,
preventing false idle kills on workers with real progress.
"""
import sys
import time
from pathlib import Path

task_id = Path(sys.argv[1]).name.removesuffix(".plan.md")
print(f"##PROGRESS## {task_id} | Phase: implementing | 3/5", flush=True)
tools = ["Bash", "Grep", "Read", "Edit", "Agent", "Write"]
i = 0
while True:
    print(f"##PROGRESS## {task_id} | Detail: Using: {tools[i % len(tools)]}", flush=True)
    i += 1
    time.sleep(0.2)
