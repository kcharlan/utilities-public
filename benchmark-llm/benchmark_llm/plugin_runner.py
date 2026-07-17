from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from .metrics import aggregate_metrics
from .plugin_api import BenchmarkPlugin, PluginContext
from .reporting import write_report
from .storage import record_run, write_json, write_jsonl
from .util import elapsed_milliseconds, iso_timestamp, run_timestamp_slug, safe_slug, unique_child_name, utc_now


def _load_plugin_class(plugin_file: Path) -> type[BenchmarkPlugin]:
    spec = importlib.util.spec_from_file_location("benchmark_plugin", plugin_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load plugin from {plugin_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for value in module.__dict__.values():
        if isinstance(value, type) and issubclass(value, BenchmarkPlugin) and value is not BenchmarkPlugin:
            return value
    raise LookupError(f"No BenchmarkPlugin subclass found in {plugin_file}")


def _run_plugin_phase(
    ctx: PluginContext,
    phase: str,
    cwd: Path,
    fn: Any,
    *args: Any,
) -> Any:
    started = utc_now()
    stderr = ""
    try:
        result = fn(*args)
    except Exception as exc:
        ended = utc_now()
        ctx.commands.append(
            {
                "phase": phase,
                "command": phase,
                "cwd": str(cwd),
                "exit_code": 1,
                "stdout": "",
                "stderr": str(exc),
                "started_at": iso_timestamp(started),
                "ended_at": iso_timestamp(ended),
                "elapsed_ms": elapsed_milliseconds(started, ended),
            }
        )
        raise
    ended = utc_now()
    ctx.commands.append(
        {
            "phase": phase,
            "command": phase,
            "cwd": str(cwd),
            "exit_code": 0,
            "stdout": "",
            "stderr": stderr,
            "started_at": iso_timestamp(started),
            "ended_at": iso_timestamp(ended),
            "elapsed_ms": elapsed_milliseconds(started, ended),
        }
    )
    return result


def run_plugin_benchmark(
    benchmark_dir: Path,
    runtime_home: Path,
    model: str,
    environ: dict[str, str],
) -> Path:
    started = utc_now()
    plugin_class = _load_plugin_class(benchmark_dir / "bench.py")
    plugin = plugin_class()
    bench_id = safe_slug(plugin.benchmark_id or benchmark_dir.name)
    run_id = unique_child_name(
        runtime_home / "runs",
        f"{run_timestamp_slug(started)}__{bench_id}__{safe_slug(model)}",
    )
    run_dir = runtime_home / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    ctx = PluginContext(
        benchmark_dir=benchmark_dir,
        runtime_home=runtime_home,
        run_dir=run_dir,
        model=model,
        environ=dict(environ),
    )
    _run_plugin_phase(ctx, "plugin_prepare", benchmark_dir, plugin.prepare, ctx)
    _run_plugin_phase(ctx, "plugin_execute", benchmark_dir, plugin.execute, ctx, model)
    score = _run_plugin_phase(ctx, "plugin_judge", benchmark_dir, plugin.judge, ctx)
    summary_payload = _run_plugin_phase(ctx, "plugin_summarize", benchmark_dir, plugin.summarize, ctx, score) or {}
    ended = utc_now()
    run_metrics = aggregate_metrics(ctx.commands)

    manifest = {
        "run_id": run_id,
        "benchmark": {
            "id": bench_id,
            "mode": "plugin",
            "path": str(benchmark_dir),
        },
        "model": model,
        "started_at": iso_timestamp(started),
        "ended_at": iso_timestamp(ended),
        "timing": {
            "elapsed_ms": elapsed_milliseconds(started, ended),
        },
        "metrics": run_metrics,
        "metadata": summary_payload,
        "artifacts": {
            "score": str(run_dir / "score.json"),
            "commands": str(run_dir / "commands.jsonl"),
            "report": str(run_dir / "report.md"),
        },
    }

    write_jsonl(run_dir / "commands.jsonl", ctx.commands)
    write_json(run_dir / "score.json", score)
    write_json(run_dir / "manifest.json", manifest)
    report_path = write_report(run_dir, manifest, score)
    record_run(
        runtime_home,
        {
            "run_id": run_id,
            "benchmark_id": bench_id,
            "benchmark_mode": "plugin",
            "model": model,
            "started_at": manifest["started_at"],
            "ended_at": manifest["ended_at"],
            "elapsed_ms": manifest["timing"]["elapsed_ms"],
            "cost_usd": manifest["metrics"].get("cost_usd"),
            "input_tokens": manifest["metrics"].get("input_tokens"),
            "output_tokens": manifest["metrics"].get("output_tokens"),
            "total_tokens": manifest["metrics"].get("total_tokens"),
            "score_percent": float(score["summary"]["score_percent"]),
            "run_dir": str(run_dir),
            "report_path": str(report_path),
            "manifest_path": str(run_dir / "manifest.json"),
        },
    )
    return run_dir
