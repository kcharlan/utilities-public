from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .execution import run_command
from .metrics import aggregate_metrics
from .reporting import write_report
from .storage import record_run, write_json, write_jsonl
from .util import (
    build_model_command_env,
    elapsed_milliseconds,
    iso_timestamp,
    merge_environ,
    run_timestamp_slug,
    safe_slug,
    unique_child_name,
    utc_now,
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _apply_normalizers(value: str, normalize: list[str]) -> str:
    result = value
    for operation in normalize:
        if operation == "strip":
            result = result.strip()
        elif operation == "lowercase":
            result = result.lower()
    return result


def _judge_row(response_text: str, answer_text: str, judge: dict[str, Any]) -> dict[str, Any]:
    judge_type = judge.get("type", "exact_match")
    normalize = judge.get("normalize", [])
    normalized_response = _apply_normalizers(response_text, normalize)
    normalized_answer = _apply_normalizers(answer_text, normalize)
    if judge_type == "exact_match":
        passed = normalized_response == normalized_answer
    elif judge_type == "regex":
        import re

        passed = bool(re.search(answer_text, response_text))
    else:
        raise ValueError(f"Unsupported judge type: {judge_type}")
    return {
        "passed": passed,
        "normalized_response": normalized_response,
        "normalized_answer": normalized_answer,
    }


def _judge_with_llm_command(
    benchmark_dir: Path,
    run_dir: Path,
    environ: dict[str, str],
    command_rows: list[dict[str, Any]],
    case_id: str,
    prompt_text: str,
    response_text: str,
    answer_text: str,
    judge: dict[str, Any],
) -> dict[str, Any]:
    judge_command = judge.get("judge_command")
    if not judge_command:
        raise ValueError("llm_judge requires judge_command in judge.yaml")
    rubric = str(judge.get("rubric", "")).strip()
    judge_prompt = "\n\n".join(
        part
        for part in [
            rubric,
            f"Prompt:\n{prompt_text}",
            f"Expected answer:\n{answer_text}",
            f"Model response:\n{response_text}",
            "Return JSON with keys passed (boolean) and reason (string).",
        ]
        if part
    )
    judge_env = merge_environ(
        environ,
        {
            "BENCH_JUDGE_CASE_ID": case_id,
            "BENCH_JUDGE_PROMPT": judge_prompt,
            "BENCH_CASE_PROMPT": prompt_text,
            "BENCH_EXPECTED_ANSWER": answer_text,
            "BENCH_RESPONSE_TEXT": response_text,
            "BENCH_COMMAND_METRICS_PATH": str(
                run_dir / "command-metrics" / f"judge_case__{safe_slug(case_id)}.json"
            ),
        },
    )
    metrics_path = Path(str(judge_env["BENCH_COMMAND_METRICS_PATH"]))
    record = run_command(
        str(judge_command),
        cwd=benchmark_dir,
        env=judge_env,
        phase="judge_case",
        metrics_path=metrics_path,
    )
    record["case_id"] = case_id
    command_rows.append(record)
    if record["exit_code"] != 0:
        raise RuntimeError(record["stderr"] or record["stdout"] or "LLM judge failed.")
    payload = json.loads(record["stdout"])
    return {
        "passed": bool(payload["passed"]),
        "normalized_response": response_text,
        "normalized_answer": answer_text,
        "judge_reason": payload.get("reason", ""),
    }


def run_prompt_batch(
    benchmark_dir: Path,
    runtime_home: Path,
    model: str,
    executor_command: str,
    environ: dict[str, str],
) -> Path:
    bench_id = safe_slug(benchmark_dir.name)
    started = utc_now()
    run_id = unique_child_name(
        runtime_home / "runs",
        f"{run_timestamp_slug(started)}__{bench_id}__{safe_slug(model)}",
    )
    run_dir = runtime_home / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    cases = _load_jsonl(benchmark_dir / "cases.jsonl")
    answers = {row["id"]: row["answer"] for row in _load_jsonl(benchmark_dir / "answers.jsonl")}
    judge = yaml.safe_load((benchmark_dir / "judge.yaml").read_text(encoding="utf-8"))
    fixture_responses = "{}"
    responses_fixture_path = benchmark_dir / "responses.jsonl"
    if responses_fixture_path.is_file():
        fixture_responses = json.dumps(
            {
                str(row["id"]): str(row["response"])
                for row in _load_jsonl(responses_fixture_path)
            }
        )

    command_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    judged_rows: list[dict[str, Any]] = []

    for case in cases:
        metrics_path = run_dir / "command-metrics" / f"execute_case__{safe_slug(str(case['id']))}.json"
        env = build_model_command_env(
            environ,
            {
                "MODEL_ID": model,
                "CASE_ID": str(case["id"]),
                "TASK_PROMPT_TEXT": str(case["prompt"]),
                "TASK_RESPONSE_FIXTURES_JSON": fixture_responses,
                "TASK_METRICS_PATH": str(metrics_path),
            },
        )
        command_record = run_command(
            executor_command,
            cwd=benchmark_dir,
            env=env,
            phase="execute_case",
            metrics_path=metrics_path,
        )
        command_record["case_id"] = case["id"]
        command_rows.append(command_record)
        if command_record["exit_code"] != 0:
            raise RuntimeError(command_record["stderr"] or command_record["stdout"] or "Executor failed.")
        response_text = command_record["stdout"].strip()
        raw_rows.append(
            {
                "case_id": case["id"],
                "prompt": case["prompt"],
                "response_text": response_text,
            }
        )
        if judge.get("type") == "llm_judge":
            judged = _judge_with_llm_command(
                benchmark_dir=benchmark_dir,
                run_dir=run_dir,
                environ=env,
                command_rows=command_rows,
                case_id=str(case["id"]),
                prompt_text=str(case["prompt"]),
                response_text=response_text,
                answer_text=str(answers[case["id"]]),
                judge=judge,
            )
        else:
            judged = _judge_row(response_text, str(answers[case["id"]]), judge)
        judged_rows.append(
            {
                "case_id": case["id"],
                "prompt": case["prompt"],
                "expected_answer": answers[case["id"]],
                "response_text": response_text,
                **judged,
            }
        )

    passed = sum(1 for row in judged_rows if row["passed"])
    total = len(judged_rows)
    score = {
        "summary": {
            "passed": passed,
            "total": total,
            "score_percent": round((passed / total) * 100.0 if total else 0.0, 1),
        },
        "checks": [
            {"name": f"case {row['case_id']}", "passed": row["passed"]}
            for row in judged_rows
        ],
    }

    ended = utc_now()
    run_metrics = aggregate_metrics(command_rows)
    manifest = {
        "run_id": run_id,
        "benchmark": {
            "id": bench_id,
            "mode": "prompt_batch",
            "path": str(benchmark_dir),
        },
        "model": model,
        "started_at": iso_timestamp(started),
        "ended_at": iso_timestamp(ended),
        "timing": {
            "elapsed_ms": elapsed_milliseconds(started, ended),
        },
        "metrics": run_metrics,
        "artifacts": {
            "raw_responses": str(run_dir / "raw_responses.jsonl"),
            "judged": str(run_dir / "judged.jsonl"),
            "score": str(run_dir / "score.json"),
            "commands": str(run_dir / "commands.jsonl"),
            "report": str(run_dir / "report.md"),
        },
    }

    write_jsonl(run_dir / "commands.jsonl", command_rows)
    write_jsonl(run_dir / "raw_responses.jsonl", raw_rows)
    write_jsonl(run_dir / "judged.jsonl", judged_rows)
    write_json(run_dir / "score.json", score)
    write_json(run_dir / "manifest.json", manifest)
    report_path = write_report(run_dir, manifest, score)

    record_run(
        runtime_home,
        {
            "run_id": run_id,
            "benchmark_id": bench_id,
            "benchmark_mode": "prompt_batch",
            "model": model,
            "started_at": manifest["started_at"],
            "ended_at": manifest["ended_at"],
            "elapsed_ms": manifest["timing"]["elapsed_ms"],
            "cost_usd": manifest["metrics"].get("cost_usd"),
            "input_tokens": manifest["metrics"].get("input_tokens"),
            "output_tokens": manifest["metrics"].get("output_tokens"),
            "total_tokens": manifest["metrics"].get("total_tokens"),
            "score_percent": score["summary"]["score_percent"],
            "run_dir": str(run_dir),
            "report_path": str(report_path),
            "manifest_path": str(run_dir / "manifest.json"),
        },
    )
    return run_dir
