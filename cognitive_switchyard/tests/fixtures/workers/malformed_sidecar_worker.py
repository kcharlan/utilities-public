#!/usr/bin/env python3
import sys
from pathlib import Path

task_path = Path(sys.argv[1])
print("malformed sidecar", flush=True)
task_path.with_name(task_path.name.removesuffix(".plan.md") + ".status").write_text(
    "STATUS: blocked\nCOMMITS: none\nTEST_RESULT: skip\n",
    encoding="utf-8",
)
