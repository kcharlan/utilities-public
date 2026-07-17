from __future__ import annotations

import json
from pathlib import Path

from benchsdk import BenchmarkPlugin


class AdvancedExampleBenchmark(BenchmarkPlugin):
    benchmark_id = "plugin-advanced"

    def prepare(self, ctx) -> None:
        (ctx.run_dir / "inputs").mkdir(parents=True, exist_ok=True)
        (ctx.run_dir / "inputs" / "task.json").write_text(
            json.dumps({"goal": "Demonstrate plugin control flow"}, indent=2) + "\n",
            encoding="utf-8",
        )

    def execute(self, ctx, model: str) -> None:
        (ctx.run_dir / "execution.json").write_text(
            json.dumps({"model": model, "status": "completed"}, indent=2) + "\n",
            encoding="utf-8",
        )
        ctx.commands.append(
            {
                "phase": "execute",
                "command": "plugin.execute",
                "cwd": str(ctx.benchmark_dir),
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
            }
        )

    def judge(self, ctx) -> dict:
        payload = json.loads((ctx.run_dir / "execution.json").read_text(encoding="utf-8"))
        passed = payload["status"] == "completed"
        return {
            "summary": {
                "passed": 1 if passed else 0,
                "total": 1,
                "score_percent": 100.0 if passed else 0.0,
            },
            "checks": [
                {
                    "name": "plugin execution finished",
                    "passed": passed,
                }
            ],
        }

    def summarize(self, ctx, score: dict) -> dict:
        return {
            "message": "Example plugin benchmark completed.",
            "score_percent": score["summary"]["score_percent"],
        }
