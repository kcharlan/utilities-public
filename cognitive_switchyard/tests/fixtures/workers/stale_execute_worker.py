#!/usr/bin/env python3
"""Fixture worker: writes a result line to the NDJSON output file, then sleeps forever.

Simulates a zombie execute script where the AI process has exited (result line
present) but the execute script is still alive — the defense-in-depth staleness
check should terminate it.
"""
import json
import sys
import time
from pathlib import Path

task_path = Path(sys.argv[1])
task_id = task_path.name.removesuffix(".plan.md")

# Simulate Claude having finished — write a result line to the NDJSON file
ndjson_path = task_path.with_name(task_id + ".claude_output")
ndjson_path.write_text(
    json.dumps({"type": "result", "result": "done"}) + "\n",
    encoding="utf-8",
)
print(f"##PROGRESS## {task_id} | Phase: implementing | 3/5", flush=True)

# Simulate a hung execute script — sleep forever
while True:
    time.sleep(60)
