from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Iterable, TextIO

from .discovery import detect_benchmark_mode
from .plugin_runner import run_plugin_benchmark
from .prompt_batch import run_prompt_batch
from .repo_task import (
    expand_repo_task_models,
    load_repo_task_config,
    resolve_repo_task_output_dir,
    resolve_repo_task_settings,
    run_repo_task_final_summary,
    run_repo_task,
)
from .storage import ensure_runtime_layout, get_run, list_runs
from .util import runtime_home_from_environ


def _format_elapsed_compact(elapsed_ms: object) -> str:
    if elapsed_ms is None:
        return ""
    value = int(float(elapsed_ms))
    if value < 1000:
        return f"{value}ms"
    seconds = value / 1000.0
    if seconds < 60:
        return f"{seconds:.2f}s"
    return f"{seconds / 60.0:.2f}m"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("benchmark_dir")
    run_parser.add_argument(
        "-m",
        "--models",
        help="Comma-separated models, or @path/to/models.txt for a model list file.",
    )
    run_parser.add_argument(
        "--models-file",
        action="append",
        default=[],
        help="Path to a model list file. May be passed more than once.",
    )
    run_parser.add_argument("--executor-command")

    subparsers.add_parser("list")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("run_id")
    return parser


def _print_runs(rows: list[dict[str, object]], stdout: TextIO) -> None:
    if not rows:
        stdout.write("No benchmark runs found.\n")
        return
    stdout.write("RUN ID | BENCHMARK | MODE | MODEL | ELAPSED | COST | TOKENS | SCORE\n")
    for row in rows:
        stdout.write(
            f"{row['run_id']} | {row['benchmark_id']} | {row['benchmark_mode']} | "
            f"{row['model']} | {_format_elapsed_compact(row.get('elapsed_ms'))} | "
            f"{'' if row.get('cost_usd') is None else row.get('cost_usd')} | "
            f"{'' if row.get('total_tokens') is None else row.get('total_tokens')} | "
            f"{float(row['score_percent']):.1f}%\n"
        )


def _write_progress(event: dict[str, Any], stderr: TextIO) -> None:
    event_name = event.get("event")
    model = event.get("model")
    run_id = event.get("run_id")
    attempt = event.get("attempt")
    prefix_parts = ["[bench]"]
    if model:
        prefix_parts.append(str(model))
    if run_id:
        prefix_parts.append(str(run_id))
    if event.get("run_index") and event.get("run_total"):
        prefix_parts.append(f"run {event.get('run_index')}/{event.get('run_total')}")
    if attempt:
        prefix_parts.append(f"attempt {attempt}")
    prefix = " ".join(prefix_parts)

    if event_name == "run_start":
        stderr.write(f"{prefix} run started; artifacts: {event.get('run_dir')}\n")
    elif event_name == "attempt_start":
        stderr.write(
            f"{prefix} attempt started; workspace: {event.get('workspace')}; artifacts: {event.get('attempt_dir')}\n"
        )
    elif event_name == "command_start":
        stderr.write(
            f"{prefix} phase {event.get('phase')} started; "
            f"stdout: {event.get('stdout_path')}; stderr: {event.get('stderr_path')}\n"
        )
    elif event_name == "command_end":
        stderr.write(
            f"{prefix} phase {event.get('phase')} finished exit={event.get('exit_code')} "
            f"elapsed={_format_elapsed_compact(event.get('elapsed_ms'))} "
            f"stdout_bytes={event.get('stdout_bytes', 0)} stderr_bytes={event.get('stderr_bytes', 0)}\n"
        )
    elif event_name == "attempt_end":
        suffix = f"; retry_reason={event.get('retry_reason')}" if event.get("retry_reason") else ""
        stderr.write(f"{prefix} attempt {event.get('status')}{suffix}\n")
    elif event_name == "run_end":
        suffix = f"; retry_reason={event.get('retry_reason')}" if event.get("retry_reason") else ""
        stderr.write(
            f"{prefix} run {event.get('status')} "
            f"elapsed={_format_elapsed_compact(event.get('elapsed_ms'))}{suffix}\n"
        )
    stderr.flush()


def _normalize_executor_command(command: str | None) -> str | None:
    if not command:
        return None
    candidate = Path(command)
    if candidate.exists():
        return str(candidate.resolve())
    return command


def _dedupe_preserving_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _read_models_file(path_value: str) -> list[str]:
    path = Path(path_value).expanduser()
    models: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for token in line.split(","):
            model = token.strip()
            if model and not model.startswith("#"):
                models.append(model)
    return _dedupe_preserving_order(models)


def _parse_models_argument(models_arg: str | None) -> list[str]:
    if not models_arg:
        return []
    models: list[str] = []
    for token in str(models_arg).split(","):
        value = token.strip()
        if not value:
            continue
        if value.startswith("@"):
            models.extend(_read_models_file(value[1:]))
        else:
            models.append(value)
    return models


def _resolve_models(
    parser: argparse.ArgumentParser,
    models_arg: str | None,
    models_files: list[str] | None,
) -> list[str]:
    resolved: list[str] = []
    try:
        for path_value in models_files or []:
            resolved.extend(_read_models_file(path_value))
        resolved.extend(_parse_models_argument(models_arg))
    except OSError as exc:
        parser.error(str(exc))
    if not resolved:
        parser.error("at least one model must be provided via -m/--models or --models-file")
    return resolved


def main(
    argv: list[str] | None = None,
    environ: dict[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    argv = list(argv or sys.argv[1:])
    env = dict(os.environ)
    env.update(environ or {})
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    parser = _build_parser()
    args = parser.parse_args(argv)
    runtime_home = runtime_home_from_environ(env)
    ensure_runtime_layout(runtime_home)

    if args.command == "run":
        benchmark_dir = Path(args.benchmark_dir).resolve()
        mode = detect_benchmark_mode(benchmark_dir)
        models = _resolve_models(parser, args.models, args.models_file)
        repo_task_config = None
        if mode == "repo_task":
            try:
                repo_task_config = load_repo_task_config(benchmark_dir)
                repo_task_settings = resolve_repo_task_settings(repo_task_config)
                resolve_repo_task_output_dir(repo_task_settings, env)
            except Exception as exc:
                stderr.write(f"{str(exc).rstrip()}\n")
                return 1
            models = expand_repo_task_models(models, repo_task_settings)
            stderr.write(
                f"[bench] plan: benchmark={benchmark_dir.name} runs={len(models)} "
                f"configured_runs_per_model={repo_task_settings.runs} "
                f"run_order={repo_task_settings.run_order}\n"
            )
            stderr.flush()
        created: list[Path] = []
        attempted: list[Path] = []
        summary_path: Path | None = None
        failed = False
        for run_index, model in enumerate(models, start=1):
            try:
                if mode == "prompt_batch":
                    executor_command = _normalize_executor_command(args.executor_command)
                    if not executor_command:
                        raise SystemExit("--executor-command is required for prompt-batch runs.")
                    created.append(
                        run_prompt_batch(
                            benchmark_dir=benchmark_dir,
                            runtime_home=runtime_home,
                            model=model,
                            executor_command=str(executor_command),
                            environ=env,
                        )
                    )
                elif mode == "repo_task":
                    run_dir = run_repo_task(
                        benchmark_dir=benchmark_dir,
                        runtime_home=runtime_home,
                        model=model,
                        environ=env,
                        config=repo_task_config,
                        progress_callback=lambda event, _run_index=run_index: _write_progress(
                            {
                                "run_index": _run_index,
                                "run_total": len(models),
                                **event,
                            },
                            stderr,
                        ),
                    )
                    created.append(run_dir)
                    attempted.append(run_dir)
                else:
                    created.append(
                        run_plugin_benchmark(
                            benchmark_dir=benchmark_dir,
                            runtime_home=runtime_home,
                            model=model,
                            environ=env,
                        )
                    )
            except Exception as exc:
                failed = True
                run_dir = getattr(exc, "run_dir", None)
                if isinstance(run_dir, Path):
                    attempted.append(run_dir)
                    stderr.write(
                        f"Model failed: {model} ({run_dir.name})\n"
                        f"{str(exc).rstrip()}\n"
                    )
                else:
                    stderr.write(f"Model failed: {model}\n{str(exc).rstrip()}\n")
        if mode == "repo_task" and attempted:
            try:
                summary_path = run_repo_task_final_summary(
                    benchmark_dir=benchmark_dir,
                    runtime_home=runtime_home,
                    run_dirs=attempted,
                    environ=env,
                    config=repo_task_config,
                    progress_callback=lambda event: _write_progress(event, stderr),
                )
            except Exception as exc:
                failed = True
                stderr.write(f"Final summary failed\n{str(exc).rstrip()}\n")
        for run_dir in created:
            stdout.write(f"Created run: {run_dir.name}\n")
        if summary_path is not None:
            stdout.write(f"Created summary: {summary_path.name}\n")
        return 1 if failed else 0

    if args.command == "list":
        _print_runs(list_runs(runtime_home), stdout)
        return 0

    if args.command == "report":
        row = get_run(runtime_home, args.run_id)
        stdout.write(Path(str(row["report_path"])).read_text(encoding="utf-8"))
        return 0

    stderr.write(f"Unknown command: {args.command}\n")
    return 1
