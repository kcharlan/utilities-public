from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
import shutil
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, NamedTuple

from benchsdk import BenchmarkPlugin
from benchmark_llm.util import build_model_command_env


REQUIRED_CELLS = {
    "design_orch.orchestration",
    "switchyard.planning",
    "switchyard.resolution",
    "switchyard.auto_fix",
    "codex.worker_execution",
    "codex_hybrid.worker_execution",
}
MINIMUM_TRIALS = 6
DEFAULT_TRIALS = 6
DEFAULT_REASONING_EFFORT = "high"
DEFAULT_MAX_ATTEMPTS = 2
ALLOWED_REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
}
_CANDIDATE_ENV_KEYS = {
    "HOME",
    "PATH",
    "SHELL",
    "TERM",
    "LANG",
    "TMPDIR",
    "TMP",
    "TEMP",
    "USER",
    "LOGNAME",
    "SSH_AUTH_SOCK",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
}
_CANDIDATE_PROVIDER_PREFIXES = (
    "OPENAI_",
    "OPENROUTER_",
    "ANTHROPIC_",
    "GOOGLE_",
    "GEMINI_",
    "AZURE_",
    "AWS_",
    "VERTEX_",
    "MISTRAL_",
    "XAI_",
    "TOGETHER_",
    "FIREWORKS_",
    "COHERE_",
    "CODEX_",
)
CELL_THRESHOLD = {
    "minimum_correctness_rate": 1.0,
    "minimum_mean_verification_score": 100.0,
    "maximum_paired_correctness_drop": 0.0,
    "maximum_paired_score_drop": 0.0,
}


class Task(NamedTuple):
    id: str
    cell: str
    context: str
    prompt: str
    expected_path: str
    expected_content: str
    source_dir: Path

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()


class ScheduleRow(NamedTuple):
    trial: int
    task: Task
    candidate: str


def _canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def validate_artifact_roots(runtime_home: Path, workspace_root: Path, source_checkout: Path) -> None:
    canonical_runtime = _canonical(runtime_home)
    canonical_workspace = _canonical(workspace_root)
    canonical_source = _canonical(source_checkout)
    if _inside(canonical_runtime, canonical_source):
        raise ValueError(
            "The runtime home resolves inside the source checkout; choose a private external directory."
        )
    if _inside(canonical_workspace, canonical_source):
        raise ValueError(
            "The disposable workspace root resolves inside the source checkout; refusing to continue."
        )
    if not _inside(canonical_workspace, canonical_runtime):
        raise ValueError("The disposable workspace root must resolve beneath BENCH_RUNTIME_HOME.")


def _source_checkout(benchmark_dir: Path) -> Path:
    for candidate in [benchmark_dir, *benchmark_dir.parents]:
        if (candidate / ".git").exists():
            return candidate.resolve()
    raise ValueError("Could not resolve the canonical source checkout containing the benchmark.")


def load_tasks(tasks_dir: Path) -> list[Task]:
    tasks: list[Task] = []
    for task_file in sorted(tasks_dir.glob("*/task.json")):
        payload = json.loads(task_file.read_text(encoding="utf-8"))
        expected = payload["expected"]
        task = Task(
            id=str(payload["id"]),
            cell=str(payload["cell"]),
            context=str(payload["context"]),
            prompt=str(payload["prompt"]),
            expected_path=str(expected["path"]),
            expected_content=str(expected["content"]),
            source_dir=task_file.parent,
        )
        expected_path = Path(task.expected_path)
        if expected_path.is_absolute() or ".." in expected_path.parts:
            raise ValueError(f"Task {task.id} has an unsafe expected output path.")
        if not (task.source_dir / "repo").is_dir():
            raise ValueError(f"Task {task.id} is missing its synthetic repo directory.")
        if any(path.is_symlink() for path in task.source_dir.rglob("*")):
            raise ValueError(f"Task {task.id} contains a symlink; fixtures must be self-contained.")
        tasks.append(task)
    cells = {task.cell for task in tasks}
    ids = {task.id for task in tasks}
    if cells != REQUIRED_CELLS or len(tasks) != len(REQUIRED_CELLS) or len(ids) != len(tasks):
        raise ValueError(
            "The paired corpus must contain exactly one uniquely named task for every required cell."
        )
    return tasks


def build_schedule(tasks: list[Task], candidates: list[str], trials: int) -> list[ScheduleRow]:
    if trials < MINIMUM_TRIALS:
        raise ValueError(f"at least {MINIMUM_TRIALS} paired trials are required; three is not sufficient.")
    if trials % len(tasks) != 0:
        raise ValueError(f"Trial count must be a multiple of {len(tasks)} for balanced task positions.")
    if len(candidates) < 2 or len(set(candidates)) != len(candidates):
        raise ValueError("Provide at least two distinct candidate model identifiers.")
    if trials % len(candidates) != 0:
        raise ValueError(
            "Trial count must be a multiple of the candidate count for balanced candidate positions."
        )

    schedule: list[ScheduleRow] = []
    for trial_index in range(trials):
        ordered_tasks = tasks[trial_index % len(tasks) :] + tasks[: trial_index % len(tasks)]
        for task in ordered_tasks:
            candidate_offset = trial_index % len(candidates)
            ordered_candidates = (
                candidates[candidate_offset:] + candidates[:candidate_offset]
            )
            schedule.extend(
                ScheduleRow(trial=trial_index + 1, task=task, candidate=candidate)
                for candidate in ordered_candidates
            )
    return schedule


def _parse_candidates(value: str | None) -> list[str]:
    candidates = [item.strip() for item in (value or "").split(",") if item.strip()]
    if any("\n" in item or "\r" in item for item in candidates):
        raise ValueError("Candidate identifiers must be single-line values.")
    return candidates


def _required_command(environ: dict[str, str], name: str) -> list[str]:
    value = environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be set explicitly; no live executor is selected by default.")
    command = shlex.split(value)
    if not command:
        raise ValueError(f"{name} did not contain an executable command.")
    return command


def _build_candidate_env(
    base: dict[str, str], extra: dict[str, str]
) -> dict[str, str]:
    broadly_cleaned = build_model_command_env(base, {})
    cleaned = {
        key: value
        for key, value in broadly_cleaned.items()
        if (
            key in _CANDIDATE_ENV_KEYS
            or key.startswith("LC_")
            or key in {"http_proxy", "https_proxy", "no_proxy", "all_proxy"}
            or key.startswith(_CANDIDATE_PROVIDER_PREFIXES)
        )
    }
    cleaned.update(extra)
    return cleaned


def _codex_version(command: list[str], environ: dict[str, str]) -> str:
    completed = subprocess.run(
        [*command, "--version"],
        cwd=Path.cwd(),
        env=environ,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Codex version command failed with exit {completed.returncode}: {completed.stderr.strip()}"
        )
    version = completed.stdout.strip()
    if not version:
        raise RuntimeError("Codex version command returned no version string.")
    return version


def _load_metrics(path: Path) -> dict[str, int | float]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Executor metrics must be a JSON object.")
    metrics: dict[str, int | float] = {}
    count_keys = {"input_tokens", "output_tokens", "total_tokens", "turns"}
    for key in (*sorted(count_keys), "cost_usd", "provider_latency_ms"):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Reported metric {key} must be numeric.")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError(f"Reported metric {key} must be finite and nonnegative.")
        if key in count_keys:
            if not numeric.is_integer():
                raise ValueError(f"Reported metric {key} must be integer-valued.")
            metrics[key] = int(numeric)
        else:
            metrics[key] = value
    if "total_tokens" not in metrics and {
        "input_tokens",
        "output_tokens",
    }.issubset(metrics):
        metrics["total_tokens"] = metrics["input_tokens"] + metrics["output_tokens"]
    return metrics


def _verify_task(task: Task, workspace: Path) -> tuple[bool, float, list[dict[str, Any]]]:
    output_path = workspace / task.expected_path
    actual = output_path.read_text(encoding="utf-8") if output_path.is_file() else None
    passed = actual == task.expected_content
    return (
        passed,
        100.0 if passed else 0.0,
        [
            {
                "name": "expected synthetic output matches exactly",
                "passed": passed,
                "path": task.expected_path,
            }
        ],
    )


def _initialize_synthetic_repository(ctx, workspace: Path, task: Task, trial: int) -> None:
    started = time.monotonic()
    command = ["git", "init", "--quiet", "--template=", str(workspace)]
    isolated_git_config = workspace / ".benchmark-empty-gitconfig"
    isolated_git_config.write_text("", encoding="utf-8")
    git_env = {
        key: value
        for key, value in ctx.environ.items()
        if key in {"PATH", "LANG", "TMPDIR", "TMP", "TEMP"} or key.startswith("LC_")
    }
    git_env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(isolated_git_config),
        }
    )
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=git_env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        isolated_git_config.unlink(missing_ok=True)
    ctx.commands.append(
        {
            "phase": "workspace_prepare",
            "command": shlex.join(command),
            "cwd": str(workspace),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "elapsed_ms": (time.monotonic() - started) * 1000.0,
            "task_id": task.id,
            "cell": task.cell,
            "trial": trial,
        }
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Could not initialize disposable synthetic repository for {task.id}: "
            f"{completed.stderr.strip()}"
        )


def _dispersion(values: Iterable[float]) -> dict[str, float]:
    samples = list(values)
    return {
        "mean": statistics.fmean(samples),
        "stdev": statistics.pstdev(samples),
        "min": min(samples),
        "median": statistics.median(samples),
        "max": max(samples),
    }


def _reported_usage(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    attempts = [
        attempt
        for row in rows
        for attempt in row.get(
            "attempt_metadata", [{"metrics": row.get("metrics", {})}]
        )
    ]
    metric_rows = [
        attempt.get("metrics", {}) for attempt in attempts if attempt.get("metrics")
    ]
    totals: dict[str, int | float] = {
        "trial_count": len(rows),
        "attempt_count": len(attempts),
        "attempts_reporting_usage": len(metric_rows),
    }
    for key in (
        "cost_usd",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "provider_latency_ms",
        "turns",
    ):
        values = [metrics[key] for metrics in metric_rows if key in metrics]
        if values:
            totals[key] = (
                round(math.fsum(values), 12) if key == "cost_usd" else sum(values)
            )
    return totals


def _score_results(results: list[dict[str, Any]], candidates: list[str]) -> dict[str, Any]:
    baseline = candidates[0]
    cells: dict[str, Any] = {}
    pairs: list[dict[str, Any]] = []
    for cell in sorted(REQUIRED_CELLS):
        cell_rows = [row for row in results if row["cell"] == cell]
        candidate_stats: dict[str, Any] = {}
        for candidate in candidates:
            rows = [row for row in cell_rows if row["candidate"] == candidate]
            scores = [float(row["verification_score"]) for row in rows]
            candidate_stats[candidate] = {
                "sample_count": len(rows),
                "correctness_rate": sum(bool(row["correct"]) for row in rows) / len(rows),
                "verification_score": _dispersion(scores),
                "retry_count": sum(int(row["retries"]) for row in rows),
                "elapsed_ms": _dispersion(float(row["elapsed_ms"]) for row in rows),
                "reported_usage": _reported_usage(rows),
            }
        baseline_stats = candidate_stats[baseline]
        comparisons: dict[str, Any] = {}
        for candidate in candidates[1:]:
            stats = candidate_stats[candidate]
            correctness_drop = baseline_stats["correctness_rate"] - stats["correctness_rate"]
            score_drop = (
                baseline_stats["verification_score"]["mean"]
                - stats["verification_score"]["mean"]
            )
            comparisons[candidate] = {
                "baseline_candidate": baseline,
                "paired_correctness_drop": correctness_drop,
                "paired_score_drop": score_drop,
                "threshold_met": (
                    stats["correctness_rate"] >= CELL_THRESHOLD["minimum_correctness_rate"]
                    and stats["verification_score"]["mean"]
                    >= CELL_THRESHOLD["minimum_mean_verification_score"]
                    and correctness_drop
                    <= CELL_THRESHOLD["maximum_paired_correctness_drop"]
                    and score_drop <= CELL_THRESHOLD["maximum_paired_score_drop"]
                ),
            }
        cells[cell] = {
            "threshold": dict(CELL_THRESHOLD),
            "candidates": candidate_stats,
            "comparisons": comparisons,
        }
        for trial in sorted({int(row["trial"]) for row in cell_rows}):
            trial_rows = [row for row in cell_rows if int(row["trial"]) == trial]
            pairs.append(
                {
                    "cell": cell,
                    "trial": trial,
                    "results": {
                        row["candidate"]: {
                            "correct": row["correct"],
                            "verification_score": row["verification_score"],
                            "retries": row["retries"],
                            "elapsed_ms": row["elapsed_ms"],
                        }
                        for row in trial_rows
                    },
                }
            )

    passed = sum(bool(row["correct"]) for row in results)
    return {
        "summary": {
            "passed": passed,
            "total": len(results),
            "score_percent": 100.0 * passed / len(results),
        },
        "thresholds_predeclared": True,
        "baseline_candidate": baseline,
        "cells": cells,
        "paired_results": pairs,
        "checks": [
            {
                "name": f"{row['cell']} trial {row['trial']} {row['candidate']}",
                "passed": bool(row["correct"]),
            }
            for row in results
        ],
    }


_ABSOLUTE_PATH = re.compile(
    r"/(?:Users|home|private|tmp|opt|var|etc|usr|Library|System|Applications|Volumes)(?:/|\b)"
    r"|[A-Za-z]:[\\/]"
)


def _candidate_aliases(candidates: list[str]) -> dict[str, str]:
    return {
        candidate: f"candidate_{index}"
        for index, candidate in enumerate(candidates, start=1)
    }


def _without_private_financial_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_private_financial_data(item)
            for key, item in value.items()
            if key != "cost_usd" and not key.endswith(("_usd", "_eur", "_gbp"))
        }
    if isinstance(value, list):
        return [_without_private_financial_data(item) for item in value]
    return value


def _sanitize_score(score: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    cells: dict[str, Any] = {}
    for cell, cell_score in score["cells"].items():
        cells[cell] = {
            "threshold": cell_score["threshold"],
            "candidates": {
                aliases[candidate]: statistics_payload
                for candidate, statistics_payload in cell_score["candidates"].items()
            },
            "comparisons": {
                aliases[candidate]: {
                    **comparison,
                    "baseline_candidate": aliases[comparison["baseline_candidate"]],
                }
                for candidate, comparison in cell_score["comparisons"].items()
            },
        }
    paired_results = [
        {
            "cell": pair["cell"],
            "trial": pair["trial"],
            "results": {
                aliases[candidate]: result
                for candidate, result in pair["results"].items()
            },
        }
        for pair in score["paired_results"]
    ]
    return {"cells": cells, "paired_results": paired_results}


def _write_sanitized_summary(
    path: Path,
    provenance: dict[str, Any],
    score: dict[str, Any],
) -> dict[str, Any]:
    aliases = _candidate_aliases(provenance["candidates"])
    sanitized_score = _sanitize_score(score, aliases)
    summary = {
        "schema_version": 1,
        "artifact_policy": "sanitized_commit_eligible_only",
        "raw_output_included": False,
        "execution_date": provenance["execution_date"],
        "codex_version_sha256": hashlib.sha256(
            provenance["codex_version"].encode("utf-8")
        ).hexdigest(),
        "reasoning_effort": provenance["reasoning_effort"],
        "candidates": [
            {
                "alias": aliases[candidate],
                "identifier_sha256": hashlib.sha256(
                    candidate.encode("utf-8")
                ).hexdigest(),
            }
            for candidate in provenance["candidates"]
        ],
        "prompt_hashes": provenance["prompt_hashes"],
        "task_order": [
            {**row, "candidate": aliases[row["candidate"]]}
            for row in provenance["task_order"]
        ],
        "thresholds_predeclared": score["thresholds_predeclared"],
        "baseline_candidate": aliases[score["baseline_candidate"]],
        "cells": sanitized_score["cells"],
        "paired_results": sanitized_score["paired_results"],
        "sample_size_policy": {
            "trials_per_cell_and_candidate": provenance["trials"],
            "balanced_task_positions": True,
            "interleaved_candidates": True,
            "statistically_sufficient": False,
            "note": "Six paired repetitions provide descriptive dispersion, not statistical proof.",
        },
    }
    summary = _without_private_financial_data(summary)
    rendered = json.dumps(summary, indent=2, sort_keys=False) + "\n"
    if _ABSOLUTE_PATH.search(rendered):
        raise ValueError("Sanitized summary unexpectedly contains an absolute path.")
    path.write_text(rendered, encoding="utf-8")
    return summary


class OrchestratorModelEvaluation(BenchmarkPlugin):
    benchmark_id = "orchestrator-model-eval"

    @classmethod
    def preflight(
        cls,
        benchmark_dir: Path,
        runtime_home: Path,
        environ: dict[str, str],
    ) -> None:
        del environ
        source_checkout = _source_checkout(benchmark_dir)
        validate_artifact_roots(
            runtime_home,
            runtime_home / "runs" / "preflight" / "workspaces",
            source_checkout,
        )

    def prepare(self, ctx) -> None:
        if not ctx.environ.get("BENCH_RUNTIME_HOME", "").strip():
            raise ValueError(
                "BENCH_RUNTIME_HOME must be set explicitly to a private directory outside the source checkout."
            )
        candidates = _parse_candidates(
            ctx.environ.get("BENCH_ORCHESTRATOR_EVAL_CANDIDATES")
        )
        trials = int(ctx.environ.get("BENCH_ORCHESTRATOR_EVAL_TRIALS", DEFAULT_TRIALS))
        reasoning_effort = ctx.environ.get(
            "BENCH_ORCHESTRATOR_EVAL_REASONING_EFFORT", DEFAULT_REASONING_EFFORT
        ).strip()
        max_attempts = int(
            ctx.environ.get(
                "BENCH_ORCHESTRATOR_EVAL_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS
            )
        )
        if max_attempts < 1:
            raise ValueError("BENCH_ORCHESTRATOR_EVAL_MAX_ATTEMPTS must be at least 1.")
        if reasoning_effort not in ALLOWED_REASONING_EFFORTS:
            raise ValueError(
                "BENCH_ORCHESTRATOR_EVAL_REASONING_EFFORT must be a supported effort name."
            )
        executor_command = _required_command(
            ctx.environ, "BENCH_ORCHESTRATOR_EVAL_EXECUTOR"
        )
        codex_command = _required_command(
            ctx.environ, "BENCH_ORCHESTRATOR_CODEX_COMMAND"
        )
        tasks = load_tasks(ctx.benchmark_dir / "tasks")
        schedule = build_schedule(tasks, candidates, trials)
        source_checkout = _source_checkout(ctx.benchmark_dir)
        workspace_root = ctx.run_dir / "workspaces"
        validate_artifact_roots(ctx.runtime_home, workspace_root, source_checkout)

        workspace_root.mkdir(parents=True, exist_ok=False)
        (ctx.run_dir / "raw-attempts").mkdir(parents=True, exist_ok=False)
        ctx.metadata.update(
            {
                "candidates": candidates,
                "trials": trials,
                "reasoning_effort": reasoning_effort,
                "max_attempts": max_attempts,
                "executor_command": executor_command,
                "codex_command": codex_command,
                "tasks": tasks,
                "schedule": schedule,
                "workspace_root": workspace_root,
            }
        )

    def execute(self, ctx, model: str) -> None:
        del model  # The plugin owns the paired candidate matrix; the CLI value labels the outer run.
        execution_date = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        codex_version = _codex_version(ctx.metadata["codex_command"], ctx.environ)
        results: list[dict[str, Any]] = []

        for ordinal, scheduled in enumerate(ctx.metadata["schedule"], start=1):
            task = scheduled.task
            workspace = ctx.metadata["workspace_root"] / (
                f"{ordinal:03d}__trial-{scheduled.trial:02d}__{task.id}__"
                f"{hashlib.sha256(scheduled.candidate.encode()).hexdigest()[:10]}"
            )
            raw_trial_dir = ctx.run_dir / "raw-attempts" / f"{ordinal:03d}"
            raw_trial_dir.mkdir(parents=True, exist_ok=False)

            attempts: list[dict[str, Any]] = []
            final_metrics: dict[str, int | float] = {}
            started = time.monotonic()
            for attempt_number in range(1, ctx.metadata["max_attempts"] + 1):
                if workspace.is_symlink():
                    workspace.unlink()
                elif workspace.exists():
                    shutil.rmtree(workspace)
                shutil.copytree(task.source_dir / "repo", workspace, symlinks=False)
                (workspace / "prompt.txt").write_text(task.prompt, encoding="utf-8")
                _initialize_synthetic_repository(ctx, workspace, task, scheduled.trial)
                attempt_dir = raw_trial_dir / f"attempt-{attempt_number:02d}"
                attempt_dir.mkdir(parents=True, exist_ok=False)
                metrics_path = attempt_dir / "metrics.json"
                command = [
                    *ctx.metadata["executor_command"],
                    "--model",
                    scheduled.candidate,
                    "--reasoning-effort",
                    ctx.metadata["reasoning_effort"],
                    "--task-id",
                    task.id,
                    "--prompt-file",
                    str(workspace / "prompt.txt"),
                    "--workspace",
                    str(workspace),
                    "--metrics-file",
                    str(metrics_path),
                ]
                model_env = _build_candidate_env(
                    ctx.environ,
                    {
                        "MODEL_ID": scheduled.candidate,
                        "TASK_ID": task.id,
                        "TASK_PROMPT_PATH": str(workspace / "prompt.txt"),
                        "WORKSPACE_ROOT": str(workspace),
                        "TASK_METRICS_PATH": str(metrics_path),
                        "REASONING_EFFORT": ctx.metadata["reasoning_effort"],
                    },
                )
                attempt_started = time.monotonic()
                completed = subprocess.run(
                    command,
                    cwd=workspace,
                    env=model_env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                attempt_elapsed_ms = (time.monotonic() - attempt_started) * 1000.0
                (attempt_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
                (attempt_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
                metrics = _load_metrics(metrics_path)
                command_row = {
                    "phase": "candidate_execute",
                    "command": shlex.join(command),
                    "cwd": str(workspace),
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "elapsed_ms": attempt_elapsed_ms,
                    "metrics": metrics,
                    "candidate": scheduled.candidate,
                    "task_id": task.id,
                    "cell": task.cell,
                    "trial": scheduled.trial,
                    "attempt": attempt_number,
                }
                ctx.commands.append(command_row)
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "exit_code": completed.returncode,
                        "elapsed_ms": attempt_elapsed_ms,
                        "metrics": metrics,
                    }
                )
                if completed.returncode == 0:
                    final_metrics = metrics
                    break

            output_matches, verification_score, checks = _verify_task(task, workspace)
            executor_succeeded = bool(attempts and attempts[-1]["exit_code"] == 0)
            checks.insert(
                0,
                {
                    "name": "executor completed with zero exit status",
                    "passed": executor_succeeded,
                },
            )
            correct = executor_succeeded and output_matches
            if not correct:
                verification_score = 0.0
            results.append(
                {
                    "ordinal": ordinal,
                    "trial": scheduled.trial,
                    "task_id": task.id,
                    "cell": task.cell,
                    "candidate": scheduled.candidate,
                    "context": task.context,
                    "prompt_sha256": task.prompt_sha256,
                    "reasoning_effort": ctx.metadata["reasoning_effort"],
                    "correct": correct,
                    "verification_score": verification_score,
                    "verification_checks": checks,
                    "attempts": len(attempts),
                    "retries": len(attempts) - 1,
                    "attempt_metadata": attempts,
                    "metrics": final_metrics,
                    "elapsed_ms": (time.monotonic() - started) * 1000.0,
                    "workspace": str(workspace),
                }
            )

        provenance = {
            "execution_date": execution_date,
            "codex_version": codex_version,
            "reasoning_effort": ctx.metadata["reasoning_effort"],
            "candidates": ctx.metadata["candidates"],
            "trials": ctx.metadata["trials"],
            "prompt_hashes": {task.id: task.prompt_sha256 for task in ctx.metadata["tasks"]},
            "task_order": [
                {
                    "ordinal": row["ordinal"],
                    "trial": row["trial"],
                    "task_id": row["task_id"],
                    "cell": row["cell"],
                    "candidate": row["candidate"],
                }
                for row in results
            ],
        }
        payload = {"provenance": provenance, "trials": results}
        (ctx.run_dir / "evaluation-results.json").write_text(
            json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        ctx.metadata["results"] = results
        ctx.metadata["provenance"] = provenance

    def judge(self, ctx) -> dict[str, Any]:
        score = _score_results(ctx.metadata["results"], ctx.metadata["candidates"])
        ctx.metadata["score"] = score
        return score

    def summarize(self, ctx, score: dict[str, Any]) -> dict[str, Any]:
        summary = _write_sanitized_summary(
            ctx.run_dir / "commit-eligible-summary.json",
            ctx.metadata["provenance"],
            score,
        )
        return {
            "commit_eligible_summary": "commit-eligible-summary.json",
            "artifact_policy": summary["artifact_policy"],
            "candidate_count": len(summary["candidates"]),
            "trials_per_cell_and_candidate": summary["sample_size_policy"][
                "trials_per_cell_and_candidate"
            ],
        }
