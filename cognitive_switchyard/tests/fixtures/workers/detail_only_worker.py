#!/usr/bin/env python3
"""Fixture worker: emits one phase marker, then only detail lines, then sleeps forever.

Used to verify that detail-only progress lines do NOT reset the idle timer,
so the idle timeout fires even while the sampler is emitting output.
"""
import sys
import time
from pathlib import Path

task_id = Path(sys.argv[1]).name.removesuffix(".plan.md")
print(f"##PROGRESS## {task_id} | Phase: implementing | 3/5", flush=True)
while True:
    print(f"##PROGRESS## {task_id} | Detail: Still going...", flush=True)
    time.sleep(0.2)
