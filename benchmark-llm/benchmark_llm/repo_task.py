from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from .execution import run_command
from .metrics import aggregate_metrics
from .reporting import write_report
from .storage import record_run, write_json, write_jsonl
from .util import (
    build_model_command_env,
    elapsed_milliseconds,
    expand_env_string,
    iso_timestamp,
    merge_environ,
    run_timestamp_slug,
    safe_slug,
    unique_child_name,
    utc_now,
)


@dataclass
class RepoTaskStep:
    phase: str
    command: str
    model_visible: bool = False
    timeout_sec: int | None = None
    inactivity_timeout_sec: int | None = None
    retry_max_attempts: int = 1
    retry_backoff_sec: int = 0


@dataclass(frozen=True)
class RepoTaskSettings:
    runs: int = 1
    run_order: str = "breadth"
    output_dir: str | None = None


RepoTaskProgressCallback = Callable[[dict[str, Any]], None]


class RetryableRepoTaskError(RuntimeError):
    def __init__(self, message: str, *, retry_reason: str) -> None:
        super().__init__(message)
        self.retry_reason = retry_reason


class RepoTaskRunError(RuntimeError):
    def __init__(self, message: str, *, run_dir: Path) -> None:
        super().__init__(message)
        self.run_dir = run_dir


_RETRYABLE_LLM_ERROR_PATTERNS = (
    "provider_unavailable",
    "network connection lost",
    "rate limit",
    "rate-limit",
    "throttle",
    '"code":502',
    '"code":503',
    '"code":504',
    '"code":429',
    " 502 ",
    " 503 ",
    " 504 ",
    " 429 ",
)


def _git(source_repo: Path, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=benchmark-llm",
            "-c",
            "user.email=synthetic-user@example.invalid",
            *args,
        ],
        cwd=cwd or source_repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_try(source_repo: Path, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=benchmark-llm",
            "-c",
            "user.email=synthetic-user@example.invalid",
            *args,
        ],
        cwd=cwd or source_repo,
        check=False,
        capture_output=True,
        text=True,
    )


def _pattern_strip_root(pattern: str) -> Path:
    parts = Path(pattern).parts
    prefix_parts: list[str] = []
    wildcard_found = False
    for part in parts:
        if any(marker in part for marker in ("*", "?", "[")):
            wildcard_found = True
            break
        prefix_parts.append(part)
    if not wildcard_found and prefix_parts:
        prefix_parts = prefix_parts[:-1]
    return Path(*prefix_parts) if prefix_parts else Path(".")


def _workspace_status(workspace: Path) -> str:
    return _git(workspace, ["status", "--short", "--untracked-files=all"], cwd=workspace).stdout.strip()


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _retry_settings(raw: dict[str, Any] | None) -> tuple[int, int]:
    if not raw:
        return 1, 0
    return int(raw.get("max_attempts", 1)), int(raw.get("backoff_sec", 0))


def _looks_like_retryable_llm_failure(record: dict[str, Any]) -> tuple[bool, str | None]:
    if record.get("timed_out"):
        return True, "timeout"
    if record.get("inactivity_timed_out"):
        return True, "inactivity_timeout"
    combined = f"{record.get('stdout', '')}\n{record.get('stderr', '')}".lower()
    for pattern in _RETRYABLE_LLM_ERROR_PATTERNS:
        if pattern in combined:
            return True, "provider_error"
    return False, None


def _write_attempt_metadata(attempt_dir: Path, payload: dict[str, Any]) -> None:
    write_json(attempt_dir / "attempt.json", payload)


def _command_failure_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": record.get("phase"),
        "command": record.get("command"),
        "exit_code": record.get("exit_code"),
        "retryable_failure": record.get("retryable_failure", False),
        "retry_reason": record.get("retry_reason"),
        "timed_out": record.get("timed_out", False),
        "inactivity_timed_out": record.get("inactivity_timed_out", False),
        "stdout_path": record.get("stdout_path"),
        "stderr_path": record.get("stderr_path"),
        "stdout_bytes": record.get("stdout_bytes"),
        "stderr_bytes": record.get("stderr_bytes"),
        "stdout_tail": record.get("stdout_tail", ""),
        "stderr_tail": record.get("stderr_tail", ""),
    }


def _promote_attempt_artifacts(attempt_dir: Path, run_dir: Path) -> None:
    for child in attempt_dir.iterdir():
        if child.name == "attempt.json":
            continue
        destination = run_dir / child.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def _copy_pattern_matches(
    benchmark_dir: Path,
    destination_root: Path,
    patterns: list[str],
    require_match: bool = False,
) -> list[Path]:
    copied: list[Path] = []
    for pattern in patterns:
        strip_root = _pattern_strip_root(pattern)
        source_base = benchmark_dir if strip_root == Path(".") else benchmark_dir / strip_root
        for match in benchmark_dir.glob(pattern):
            if not match.is_file():
                continue
            relative = match.relative_to(source_base)
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(match, destination)
            copied.append(destination)
    if require_match and not copied:
        raise FileNotFoundError(f"No files matched configured patterns: {patterns}")
    return copied


def load_repo_task_config(benchmark_dir: Path) -> dict[str, Any]:
    return yaml.safe_load((benchmark_dir / "bench.yaml").read_text(encoding="utf-8"))


def resolve_repo_task_settings(config: dict[str, Any]) -> RepoTaskSettings:
    runs = int(config.get("runs", 1))
    if runs < 1:
        raise ValueError("bench.yaml runs must be at least 1.")
    run_order = str(config.get("run_order", "breadth"))
    if run_order not in {"breadth", "depth"}:
        raise ValueError("bench.yaml run_order must be breadth or depth.")
    output_dir = config.get("output_dir")
    if output_dir in (None, ""):
        raise ValueError("bench.yaml must define output_dir for repo_task benchmarks.")
    return RepoTaskSettings(runs=runs, run_order=run_order, output_dir=None if output_dir is None else str(output_dir))


def expand_repo_task_models(models: list[str], settings: RepoTaskSettings) -> list[str]:
    if settings.run_order == "depth":
        return [model for model in models for _ in range(settings.runs)]
    return [model for _ in range(settings.runs) for model in models]


def resolve_repo_task_output_dir(settings: RepoTaskSettings, environ: dict[str, str]) -> Path:
    assert settings.output_dir is not None
    output_dir = Path(expand_env_string(settings.output_dir, environ)).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _resolve_repo_steps(config: dict[str, Any]) -> list[RepoTaskStep]:
    raw_steps = config.get("steps", [])
    executor_config = config.get("executor", {}) or {}
    executor_command = executor_config.get("command")
    execution_defaults = config.get("execution_defaults", {}) or {}
    default_timeout_sec = _int_or_none(execution_defaults.get("timeout_sec"))
    default_inactivity_timeout_sec = _int_or_none(execution_defaults.get("inactivity_timeout_sec"))
    default_retry_max_attempts, default_retry_backoff_sec = _retry_settings(
        execution_defaults.get("retries")
    )
    resolved: list[RepoTaskStep] = []
    executor_used = False

    for index, raw_step in enumerate(raw_steps, start=1):
        if isinstance(raw_step, str):
            phase = "execute" if executor_command and raw_step == executor_command else f"step_{index}"
            command = executor_command if phase == "execute" else raw_step
            executor_used = executor_used or phase == "execute"
            resolved.append(
                RepoTaskStep(
                    phase=phase,
                    command=str(command),
                    model_visible=phase == "execute",
                    timeout_sec=default_timeout_sec,
                    inactivity_timeout_sec=default_inactivity_timeout_sec,
                    retry_max_attempts=default_retry_max_attempts,
                    retry_backoff_sec=default_retry_backoff_sec,
                )
            )
            continue

        if not isinstance(raw_step, dict):
            raise TypeError(f"Unsupported repo-task step type: {type(raw_step)!r}")

        phase = str(raw_step.get("name") or f"step_{index}")
        use_executor = bool(raw_step.get("use_executor", False))
        run_command_value = raw_step.get("run")
        timeout_sec = _int_or_none(raw_step.get("timeout_sec", default_timeout_sec))
        inactivity_timeout_sec = _int_or_none(
            raw_step.get("inactivity_timeout_sec", default_inactivity_timeout_sec)
        )
        retry_max_attempts, retry_backoff_sec = _retry_settings(raw_step.get("retries"))
        if raw_step.get("retries") is None:
            retry_max_attempts = default_retry_max_attempts
            retry_backoff_sec = default_retry_backoff_sec

        if use_executor:
            if run_command_value is not None:
                raise ValueError(f"Step {phase!r} cannot set both run and use_executor.")
            if not executor_command:
                raise ValueError(f"Step {phase!r} requested use_executor but executor.command is missing.")
            resolved.append(
                RepoTaskStep(
                    phase=phase,
                    command=str(executor_command),
                    model_visible=True,
                    timeout_sec=timeout_sec,
                    inactivity_timeout_sec=inactivity_timeout_sec,
                    retry_max_attempts=retry_max_attempts,
                    retry_backoff_sec=retry_backoff_sec,
                )
            )
            executor_used = True
            continue

        if run_command_value is None:
            if phase == "execute" and executor_command:
                resolved.append(
                    RepoTaskStep(
                        phase=phase,
                        command=str(executor_command),
                        model_visible=True,
                        timeout_sec=timeout_sec,
                        inactivity_timeout_sec=inactivity_timeout_sec,
                        retry_max_attempts=retry_max_attempts,
                        retry_backoff_sec=retry_backoff_sec,
                    )
                )
                executor_used = True
                continue
            raise ValueError(f"Step {phase!r} must define run or use_executor.")

        resolved.append(
            RepoTaskStep(
                phase=phase,
                command=str(run_command_value),
                model_visible=bool(executor_command) and run_command_value == executor_command,
                timeout_sec=timeout_sec,
                inactivity_timeout_sec=inactivity_timeout_sec,
                retry_max_attempts=retry_max_attempts,
                retry_backoff_sec=retry_backoff_sec,
            )
        )
        executor_used = executor_used or (bool(executor_command) and run_command_value == executor_command)

    if executor_command and not executor_used:
        raise ValueError(
            "executor.command is configured but no step uses it. "
            "Add a string step with the same command or a named step with use_executor: true."
        )

    return resolved
    for pattern in patterns:
        for match in benchmark_dir.glob(pattern):
            if not match.is_file():
                continue
            relative = match.relative_to(benchmark_dir)
            if relative.parts and relative.parts[0] == "visible":
                relative = Path(*relative.parts[1:])
            destination = workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(match, destination)
def _commit_workspace(workspace: Path, message: str) -> str:
    status = _git(workspace, ["status", "--porcelain"], cwd=workspace).stdout.strip()
    if not status:
        return _git(workspace, ["rev-parse", "HEAD"], cwd=workspace).stdout.strip()
    _git(workspace, ["add", "-A"], cwd=workspace)
    _git(workspace, ["commit", "-m", message], cwd=workspace)
    return _git(workspace, ["rev-parse", "HEAD"], cwd=workspace).stdout.strip()


def _cleanup_worktree_checkout(source_repo: Path, workspace: Path) -> None:
    if not workspace.exists():
        return
    _git_try(source_repo, ["worktree", "remove", "--force", str(workspace)])
    shutil.rmtree(workspace, ignore_errors=True)


def _prune_empty_worktree_dirs(path: Path, stop_at: Path) -> None:
    current = path
    stop_real = stop_at.resolve()
    while current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        if current.resolve() == stop_real:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent


def _cleanup_failed_repo_task(source_repo: Path, workspace: Path, branch_name: str, run_dir: Path) -> None:
    if workspace.exists():
        _git_try(source_repo, ["worktree", "remove", "--force", str(workspace)])
        shutil.rmtree(workspace, ignore_errors=True)

    branch_result = _git_try(source_repo, ["branch", "--list", branch_name])
    if branch_result.stdout.strip():
        _git_try(source_repo, ["branch", "-D", branch_name])

    shutil.rmtree(run_dir, ignore_errors=True)


def run_repo_task_final_summary(
    benchmark_dir: Path,
    runtime_home: Path,
    run_dirs: list[Path],
    environ: dict[str, str],
    config: dict[str, Any] | None = None,
    progress_callback: RepoTaskProgressCallback | None = None,
) -> Path | None:
    del runtime_home
    if not run_dirs:
        return None

    config = config or load_repo_task_config(benchmark_dir)
    settings = resolve_repo_task_settings(config)
    output_root = resolve_repo_task_output_dir(settings, environ)
    if not (benchmark_dir / "scripts" / "render_final_summary_prompt.py").exists():
        return None
    steps = _resolve_repo_steps(config)
    adjudicate_step = next((step for step in steps if step.phase == "adjudicate"), None)
    if adjudicate_step is None:
        return None

    summary_report_path = output_root / "summary.md"
    summary_input_path = output_root / "summary_runs.json"
    summary_command_path = output_root / "summary_command.json"
    metrics_path = output_root / "summary_metrics.json"

    def _attempt_details(run_dir: Path, attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for attempt in attempts:
            number = attempt.get("attempt")
            if not isinstance(number, int):
                continue
            detail = dict(attempt)
            attempt_meta_path = run_dir / "attempts" / f"{number:02d}" / "attempt.json"
            if attempt_meta_path.exists():
                attempt_meta = json.loads(attempt_meta_path.read_text(encoding="utf-8"))
                if attempt_meta.get("error"):
                    detail["error"] = attempt_meta["error"]
            details.append(detail)
        return details

    run_payload = []
    seen_run_dirs: set[Path] = set()
    for run_dir in run_dirs:
        if run_dir in seen_run_dirs:
            continue
        seen_run_dirs.add(run_dir)
        manifest_path = run_dir / "manifest.json"
        score_path = run_dir / "score.json"
        report_path = run_dir / "report.md"
        failure_path = run_dir / "failure.json"
        if manifest_path.exists() and score_path.exists() and report_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            score = json.loads(score_path.read_text(encoding="utf-8"))
            run_payload.append(
                {
                    "run_id": manifest["run_id"],
                    "model": manifest["model"],
                    "status": "succeeded",
                    "run_dir": str(run_dir),
                    "report_path": str(report_path),
                    "manifest_path": str(manifest_path),
                    "score_path": str(score_path),
                    "score_percent": score.get("summary", {}).get("score_percent"),
                    "attempts": _attempt_details(run_dir, manifest.get("attempts", [])),
                }
            )
            continue
        if failure_path.exists():
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            attempts = _attempt_details(run_dir, failure.get("attempts", []))
            run_payload.append(
                {
                    "run_id": failure["run_id"],
                    "model": failure["model"],
                    "status": "failed",
                    "run_dir": str(run_dir),
                    "failure_path": str(failure_path),
                    "attempts": attempts,
                    "failure_summary": {
                        "retry_reasons": [
                            attempt["retry_reason"]
                            for attempt in attempts
                            if attempt.get("retry_reason") not in (None, "")
                        ],
                        "errors": [
                            attempt["error"]
                            for attempt in attempts
                            if attempt.get("error") not in (None, "")
                        ],
                    },
                }
            )
    write_json(
        summary_input_path,
        {
            "settings": {
                "runs": settings.runs,
                "run_order": settings.run_order,
                "output_dir": str(output_root),
            },
            "runs": run_payload,
        },
    )

    record = run_command(
        adjudicate_step.command,
        cwd=benchmark_dir,
        env=merge_environ(
            environ,
            {
                "BENCH_FINAL_SUMMARY_MODE": "1",
                "BENCH_RUN_DIR": str(output_root),
                "BENCH_BENCHMARK_DIR": str(benchmark_dir),
                "BENCH_WORKSPACE": str(output_root),
                "BENCH_COMMAND_METRICS_PATH": str(metrics_path),
                "BENCH_SUMMARY_INPUT_PATH": str(summary_input_path),
                "BENCH_SUMMARY_REPORT_PATH": str(summary_report_path),
            },
        ),
        phase="final_summary",
        metrics_path=metrics_path,
        stdout_path=output_root / "summary.stdout.log",
        stderr_path=output_root / "summary.stderr.log",
        progress_callback=progress_callback,
    )
    write_json(summary_command_path, record)
    if record["exit_code"] != 0:
        raise RuntimeError(record["stderr"] or record["stdout"] or "Final summary adjudication failed.")
    if not summary_report_path.exists():
        raise RuntimeError(
            f"Final summary adjudication did not create {summary_report_path.name}."
        )
    return summary_report_path


def run_repo_task(
    benchmark_dir: Path,
    runtime_home: Path,
    model: str,
    environ: dict[str, str],
    config: dict[str, Any] | None = None,
    progress_callback: RepoTaskProgressCallback | None = None,
) -> Path:
    config = config or load_repo_task_config(benchmark_dir)
    settings = resolve_repo_task_settings(config)
    output_root = resolve_repo_task_output_dir(settings, environ)
    bench_id = safe_slug(str(config.get("id", benchmark_dir.name)))
    started = utc_now()
    timestamp_slug = run_timestamp_slug(started)
    base_run_id = f"{timestamp_slug}__{bench_id}__{safe_slug(model)}"
    run_id = unique_child_name(output_root, base_run_id)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    if progress_callback is not None:
        progress_callback(
            {
                "event": "run_start",
                "model": model,
                "run_id": run_id,
                "run_dir": str(run_dir),
                "started_at": iso_timestamp(started),
            }
        )

    workspace_config = config["workspace"]
    if workspace_config["kind"] != "git_worktree":
        raise ValueError("Only git_worktree repo tasks are currently supported.")
    source_repo = Path(
        expand_env_string(str(workspace_config["source_repo"]), environ)
    ).expanduser().resolve()
    run_suffix = run_id[len(base_run_id) :]
    steps = _resolve_repo_steps(config)
    attempts_root = run_dir / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    attempt_summaries: list[dict[str, Any]] = []
    workspace_root = runtime_home / "worktrees" / bench_id / safe_slug(model)
    workspace_root.mkdir(parents=True, exist_ok=True)

    try:
        attempt_number = 0
        while True:
            attempt_number += 1
            attempt_started = utc_now()
            attempt_dir = attempts_root / f"{attempt_number:02d}"
            attempt_dir.mkdir(parents=True, exist_ok=False)
            worktree_leaf = f"{attempt_started.strftime('%Y%m%dT%H%M%S%fZ')}{run_suffix}__a{attempt_number:02d}"
            branch_name = f"bench/{bench_id}/{safe_slug(model)}/{worktree_leaf}"
            workspace = workspace_root / worktree_leaf
            hidden_stage_dir = attempt_dir / "hidden"
            hidden_stage_dir.mkdir(parents=True, exist_ok=True)

            attempt_status = "failed"
            commit_after_run = ""
            command_rows: list[dict[str, Any]] = []
            last_error = ""
            last_retry_reason: str | None = None
            last_record: dict[str, Any] | None = None

            _git(source_repo, ["worktree", "add", "-b", branch_name, str(workspace), "HEAD"])
            if progress_callback is not None:
                progress_callback(
                    {
                        "event": "attempt_start",
                        "model": model,
                        "run_id": run_id,
                        "attempt": attempt_number,
                        "attempt_dir": str(attempt_dir),
                        "workspace": str(workspace),
                        "branch": branch_name,
                        "started_at": iso_timestamp(attempt_started),
                    }
                )

            visibility = config.get("visibility", {})
            _copy_pattern_matches(benchmark_dir, workspace, visibility.get("expose", []))
            hidden_patterns = visibility.get("hide", [])
            if hidden_patterns:
                _copy_pattern_matches(
                    benchmark_dir,
                    hidden_stage_dir,
                    hidden_patterns,
                    require_match=True,
                )

            try:
                for index, step in enumerate(steps, start=1):
                    metrics_path = attempt_dir / "command-metrics" / f"{index:02d}__{safe_slug(step.phase)}.json"
                    stdout_path = attempt_dir / "command-output" / f"{index:02d}__{safe_slug(step.phase)}.stdout.log"
                    stderr_path = attempt_dir / "command-output" / f"{index:02d}__{safe_slug(step.phase)}.stderr.log"
                    if step.model_visible:
                        env = build_model_command_env(
                            environ,
                            {
                                "MODEL_ID": model,
                                "WORKSPACE_ROOT": str(workspace),
                                "TASK_PROMPT_PATH": str(workspace / "prompt.txt"),
                                "TASK_METRICS_PATH": str(metrics_path),
                            },
                        )
                    else:
                        env = merge_environ(
                            environ,
                            {
                                "BENCH_MODEL": model,
                                "BENCH_RUN_DIR": str(attempt_dir),
                                "BENCH_BENCHMARK_DIR": str(benchmark_dir),
                                "BENCH_WORKSPACE": str(workspace),
                                "BENCH_HIDDEN_DIR": str(hidden_stage_dir),
                                "BENCH_COMMAND_METRICS_PATH": str(metrics_path),
                            },
                        )

                    before_status = _workspace_status(workspace) if step.model_visible else None
                    record = run_command(
                        step.command,
                        cwd=benchmark_dir,
                        env=env,
                        phase=step.phase,
                        metrics_path=metrics_path,
                        timeout_sec=step.timeout_sec,
                        inactivity_timeout_sec=step.inactivity_timeout_sec,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        progress_callback=(
                            (
                                lambda event, *, _model=model, _run_id=run_id, _attempt=attempt_number: progress_callback(
                                    {
                                        "model": _model,
                                        "run_id": _run_id,
                                        "attempt": _attempt,
                                        **event,
                                    }
                                )
                            )
                            if progress_callback is not None
                            else None
                        ),
                    )
                    last_record = record
                    after_status = _workspace_status(workspace) if step.model_visible else None

                    should_check_retryable_patterns = step.model_visible or record["exit_code"] != 0
                    retryable = False
                    retry_reason = None
                    if should_check_retryable_patterns or record.get("timed_out") or record.get(
                        "inactivity_timed_out"
                    ):
                        retryable, retry_reason = _looks_like_retryable_llm_failure(record)
                    if not retryable and step.model_visible and before_status == after_status:
                        retryable, retry_reason = True, "missing_required_outputs"
                    if retryable:
                        record["retryable_failure"] = True
                        record["retry_reason"] = retry_reason

                    command_rows.append(record)
                    write_jsonl(attempt_dir / "commands.jsonl", command_rows)

                    if record["exit_code"] != 0 or retryable:
                        last_error = (
                            record["stderr"]
                            or record["stdout"]
                            or f"Step failed: {step.command}"
                        )
                        last_retry_reason = retry_reason
                        if retryable and attempt_number < step.retry_max_attempts:
                            attempt_status = "retryable_failure"
                            raise RetryableRepoTaskError(last_error, retry_reason=retry_reason or "retryable")
                        raise RepoTaskRunError(last_error, run_dir=run_dir)

                if workspace_config.get("commit_outputs", False):
                    commit_after_run = _commit_workspace(workspace, f"bench: capture outputs for {run_id}")

                attempt_status = "succeeded"
                _write_attempt_metadata(
                    attempt_dir,
                    {
                        "attempt": attempt_number,
                        "status": attempt_status,
                        "started_at": iso_timestamp(attempt_started),
                        "ended_at": iso_timestamp(utc_now()),
                        "workspace": {
                            "branch": branch_name,
                            "path": str(workspace),
                            "commit_after_run": commit_after_run,
                        },
                    },
                )
                attempt_summaries.append(
                    {
                        "attempt": attempt_number,
                        "status": attempt_status,
                        "branch": branch_name,
                        "path": str(workspace),
                    }
                )
                if progress_callback is not None:
                    progress_callback(
                        {
                            "event": "attempt_end",
                            "model": model,
                            "run_id": run_id,
                            "attempt": attempt_number,
                            "status": attempt_status,
                        }
                    )

                _promote_attempt_artifacts(attempt_dir, run_dir)
                score_path = run_dir / str(config.get("scoring", {}).get("output", "score.json"))
                score = json.loads(score_path.read_text(encoding="utf-8"))
                ended = utc_now()
                run_metrics = aggregate_metrics(command_rows)
                manifest = {
                    "run_id": run_id,
                    "benchmark": {
                        "id": bench_id,
                        "mode": "repo_task",
                        "path": str(benchmark_dir),
                    },
                    "model": model,
                    "started_at": iso_timestamp(started),
                    "ended_at": iso_timestamp(ended),
                    "timing": {
                        "elapsed_ms": elapsed_milliseconds(started, ended),
                    },
                    "metrics": run_metrics,
                    "workspace": {
                        "kind": "git_worktree",
                        "source_repo": str(source_repo),
                        "branch": branch_name,
                        "path": str(workspace),
                        "keep_workspace": False,
                        "commit_after_run": commit_after_run,
                    },
                    "attempts": attempt_summaries,
                    "artifacts": {
                        "commands": str(run_dir / "commands.jsonl"),
                        "score": str(score_path),
                        "report": str(run_dir / "report.md"),
                    },
                }

                write_json(run_dir / "manifest.json", manifest)
                report_path = write_report(run_dir, manifest, score)
                record_run(
                    runtime_home,
                    {
                        "run_id": run_id,
                        "benchmark_id": bench_id,
                        "benchmark_mode": "repo_task",
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
                _cleanup_worktree_checkout(source_repo, workspace)
                _prune_empty_worktree_dirs(workspace_root, runtime_home / "worktrees")
                if progress_callback is not None:
                    progress_callback(
                        {
                            "event": "run_end",
                            "model": model,
                            "run_id": run_id,
                            "run_dir": str(run_dir),
                            "status": "succeeded",
                            "elapsed_ms": manifest["timing"]["elapsed_ms"],
                        }
                    )
                return run_dir
            except RetryableRepoTaskError:
                attempt_payload = {
                    "attempt": attempt_number,
                    "status": attempt_status,
                    "started_at": iso_timestamp(attempt_started),
                    "ended_at": iso_timestamp(utc_now()),
                    "workspace": {
                        "branch": branch_name,
                        "path": str(workspace),
                        "commit_after_run": commit_after_run,
                    },
                    "retry_reason": last_retry_reason,
                    "error": last_error,
                }
                if last_record is not None:
                    attempt_payload["failed_command"] = _command_failure_summary(last_record)
                _write_attempt_metadata(attempt_dir, attempt_payload)
                attempt_summaries.append(
                    {
                        "attempt": attempt_number,
                        "status": attempt_status,
                        "branch": branch_name,
                        "path": str(workspace),
                        "retry_reason": last_retry_reason,
                        "error": last_error,
                        "failed_command": _command_failure_summary(last_record) if last_record is not None else None,
                    }
                )
                if progress_callback is not None:
                    progress_callback(
                        {
                            "event": "attempt_end",
                            "model": model,
                            "run_id": run_id,
                            "attempt": attempt_number,
                            "status": attempt_status,
                            "retry_reason": last_retry_reason,
                            "error": last_error,
                        }
                    )
                if steps[min(len(command_rows), len(steps)) - 1].retry_backoff_sec > 0:
                    time.sleep(steps[min(len(command_rows), len(steps)) - 1].retry_backoff_sec)
                continue
            except Exception:
                attempt_payload = {
                    "attempt": attempt_number,
                    "status": attempt_status,
                    "started_at": iso_timestamp(attempt_started),
                    "ended_at": iso_timestamp(utc_now()),
                    "workspace": {
                        "branch": branch_name,
                        "path": str(workspace),
                        "commit_after_run": commit_after_run,
                    },
                    "retry_reason": last_retry_reason,
                    "error": last_error,
                }
                if last_record is not None:
                    attempt_payload["failed_command"] = _command_failure_summary(last_record)
                _write_attempt_metadata(attempt_dir, attempt_payload)
                attempt_summaries.append(
                    {
                        "attempt": attempt_number,
                        "status": attempt_status,
                        "branch": branch_name,
                        "path": str(workspace),
                        "retry_reason": last_retry_reason,
                        "error": last_error,
                        "failed_command": _command_failure_summary(last_record) if last_record is not None else None,
                    }
                )
                write_json(
                    run_dir / "failure.json",
                    {
                        "run_id": run_id,
                        "benchmark_id": bench_id,
                        "model": model,
                        "attempts": attempt_summaries,
                        "error": last_error,
                        "failed_command": _command_failure_summary(last_record) if last_record is not None else None,
                    },
                )
                if progress_callback is not None:
                    progress_callback(
                        {
                            "event": "run_end",
                            "model": model,
                            "run_id": run_id,
                            "run_dir": str(run_dir),
                            "status": "failed",
                            "retry_reason": last_retry_reason,
                            "error": last_error,
                        }
                    )
                raise
    except Exception:
        raise
