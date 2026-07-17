from __future__ import annotations

from pathlib import Path


def detect_benchmark_mode(benchmark_dir: Path) -> str:
    if (benchmark_dir / "bench.py").is_file():
        return "plugin"
    if (benchmark_dir / "bench.yaml").is_file():
        return "repo_task"
    if (benchmark_dir / "cases.jsonl").is_file():
        return "prompt_batch"
    raise FileNotFoundError(f"Could not detect benchmark mode in {benchmark_dir}")
