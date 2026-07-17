from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PluginContext:
    benchmark_dir: Path
    runtime_home: Path
    run_dir: Path
    model: str
    environ: dict[str, str]
    commands: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BenchmarkPlugin:
    benchmark_id: str | None = None

    def prepare(self, ctx: PluginContext) -> None:
        """Set up files and context before execution."""

    def execute(self, ctx: PluginContext, model: str) -> None:
        raise NotImplementedError

    def judge(self, ctx: PluginContext) -> dict[str, Any]:
        raise NotImplementedError

    def summarize(self, ctx: PluginContext, score: dict[str, Any]) -> dict[str, Any] | None:
        return None
