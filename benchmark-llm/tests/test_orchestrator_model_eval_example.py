from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from benchmark_llm.cli import main


EXAMPLE_DIR = (
    Path(__file__).resolve().parents[1] / "examples" / "orchestrator-model-eval"
)
EXPECTED_CELLS = {
    "design_orch.orchestration",
    "switchyard.planning",
    "switchyard.resolution",
    "switchyard.auto_fix",
    "codex.worker_execution",
    "codex_hybrid.worker_execution",
}


def _load_example_module():
    spec = importlib.util.spec_from_file_location(
        "orchestrator_model_eval_example", EXAMPLE_DIR / "bench.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fake_executor(tmp_path: Path) -> tuple[Path, Path]:
    executor = tmp_path / "fake_executor.py"
    executor.write_text(
        """\
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--reasoning-effort", required=True)
parser.add_argument("--task-id", required=True)
parser.add_argument("--prompt-file", required=True)
parser.add_argument("--workspace", required=True)
parser.add_argument("--metrics-file", required=True)
args = parser.parse_args()

workspace = Path(args.workspace)
metrics_path = Path(args.metrics_file)
assert os.environ["MODEL_ID"] == args.model
assert os.environ["TASK_ID"] == args.task_id
assert os.environ["TASK_PROMPT_PATH"] == args.prompt_file
assert os.environ["WORKSPACE_ROOT"] == args.workspace
assert os.environ["TASK_METRICS_PATH"] == args.metrics_file
assert os.environ["REASONING_EFFORT"] == args.reasoning_effort
assert os.environ["OPENAI_API_KEY"] == "synthetic-not-a-real-key"
for forbidden in (
    "PWD",
    "PYTEST_CURRENT_TEST",
    "BENCH_RUNTIME_HOME",
    "BENCH_HIDDEN_ANSWER_PATH",
    "UNRELATED_FRAMEWORK_SENTINEL",
    "DATABASE_URL",
    "GITHUB_TOKEN",
    "NPM_TOKEN",
):
    assert forbidden not in os.environ
attempt_marker = metrics_path.parent.parent / f".{args.task_id}-{args.model}.attempted"
if args.task_id == "switchyard-resolution" and args.model == "candidate-beta" and not attempt_marker.exists():
    metrics_path.write_text(json.dumps({
        "cost_usd": 0.0005,
        "input_tokens": 2,
        "output_tokens": 1,
        "total_tokens": 3,
        "provider_latency_ms": 1,
        "turns": 1,
    }) + "\\n", encoding="utf-8")
    attempt_marker.write_text("retry\\n", encoding="utf-8")
    (workspace / "attempt-poison.txt").write_text("must not survive\\n", encoding="utf-8")
    print("synthetic first-attempt failure containing /synthetic/private/raw-output", flush=True)
    raise SystemExit(7)

expected = {
    "design-orch": ("plan.json", '{"stages":["inspect","implement","verify"],"owner":"synthetic-orchestrator"}\\n'),
    "switchyard-planning": ("plan.json", '{"steps":["inventory","patch","test"],"risk":"synthetic-low"}\\n'),
    "switchyard-resolution": ("resolution.json", '{"choice":"amber-safe","reason":"meets-all-synthetic-constraints"}\\n'),
    "switchyard-auto-fix": ("calculator.py", 'def synthetic_total(left: int, right: int) -> int:\\n    return left + right\\n'),
    "codex-worker": ("slugger.py", 'def synthetic_slug(value: str) -> str:\\n    return "-".join(value.lower().split())\\n'),
    "codex-hybrid-worker": ("renderer.py", 'def render_synthetic_card(label: str) -> str:\\n    return f"<card>{label.strip()}</card>"\\n'),
}
assert not (workspace / "attempt-poison.txt").exists()
output_name, output_content = expected[args.task_id]
output_path = workspace / output_name
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(output_content, encoding="utf-8")
metrics_path.write_text(json.dumps({
    "cost_usd": 0.001,
    "input_tokens": 10,
    "output_tokens": 5,
    "total_tokens": 15,
    "provider_latency_ms": 2,
    "turns": 1,
}) + "\\n", encoding="utf-8")
print(f"raw output for {args.model} from {workspace}", flush=True)
""",
        encoding="utf-8",
    )
    codex = tmp_path / "fake_codex.py"
    codex.write_text(
        "import sys\nassert sys.argv[1:] == ['--version']\nprint('codex-cli 0.0.0-synthetic')\n",
        encoding="utf-8",
    )
    return executor, codex


def _fake_environment(tmp_path: Path) -> dict[str, str]:
    executor, codex = _write_fake_executor(tmp_path)
    return {
        "BENCH_RUNTIME_HOME": str(tmp_path / "external-runtime"),
        "BENCH_ORCHESTRATOR_EVAL_CANDIDATES": "candidate-alpha,candidate-beta",
        "BENCH_ORCHESTRATOR_EVAL_EXECUTOR": f"{sys.executable} {executor}",
        "BENCH_ORCHESTRATOR_CODEX_COMMAND": f"{sys.executable} {codex}",
        "BENCH_ORCHESTRATOR_EVAL_TRIALS": "6",
        "BENCH_ORCHESTRATOR_EVAL_REASONING_EFFORT": "high",
        "BENCH_ORCHESTRATOR_EVAL_MAX_ATTEMPTS": "2",
        "PWD": "/synthetic/source-hidden",
        "PYTEST_CURRENT_TEST": "synthetic-framework-leak",
        "BENCH_HIDDEN_ANSWER_PATH": "/synthetic/hidden/answers.json",
        "UNRELATED_FRAMEWORK_SENTINEL": "must-not-reach-executor",
        "DATABASE_URL": "synthetic-db-url-must-not-reach-executor",
        "GITHUB_TOKEN": "synthetic-github-token-must-not-reach-executor",
        "NPM_TOKEN": "synthetic-npm-token-must-not-reach-executor",
        "OPENAI_API_KEY": "synthetic-not-a-real-key",
        "GIT_DIR": str(tmp_path / "hostile-git-dir"),
        "GIT_WORK_TREE": str(tmp_path / "hostile-git-work-tree"),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": str(tmp_path / "hostile-hooks"),
    }


def _run_fake_matrix(tmp_path: Path) -> tuple[Path, str, str]:
    env = _fake_environment(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        ["run", str(EXAMPLE_DIR), "-m", "paired-matrix"],
        environ=env,
        stdout=stdout,
        stderr=stderr,
    )
    assert exit_code == 0, stderr.getvalue()
    run_dir = next((Path(env["BENCH_RUNTIME_HOME"]) / "runs").iterdir())
    return run_dir, stdout.getvalue(), stderr.getvalue()


def test_fixed_corpus_covers_each_role_with_distinct_hybrid_context() -> None:
    module = _load_example_module()
    tasks = module.load_tasks(EXAMPLE_DIR / "tasks")

    assert {task.cell for task in tasks} == EXPECTED_CELLS
    assert len(tasks) == len(EXPECTED_CELLS)
    codex = next(task for task in tasks if task.cell == "codex.worker_execution")
    hybrid = next(task for task in tasks if task.cell == "codex_hybrid.worker_execution")
    assert codex.prompt_sha256 != hybrid.prompt_sha256
    assert codex.context != hybrid.context
    assert all("synthetic" in task.context.lower() for task in tasks)
    assert all(task.expected_content.strip() not in task.prompt for task in tasks)


def test_runtime_and_workspace_containment_reject_direct_and_symlink_paths(
    tmp_path: Path,
) -> None:
    module = _load_example_module()
    source = tmp_path / "source"
    source.mkdir()
    external = tmp_path / "external"
    external.mkdir()

    with pytest.raises(ValueError, match="runtime home.*source checkout"):
        module.validate_artifact_roots(source / "runtime", source / "runtime/runs/x/workspaces", source)

    link_into_source = external / "runtime-link"
    link_into_source.symlink_to(source / "runtime", target_is_directory=True)
    with pytest.raises(ValueError, match="runtime home.*source checkout"):
        module.validate_artifact_roots(link_into_source, link_into_source / "runs/x/workspaces", source)

    external_runtime = external / "runtime"
    workspace_link = external / "workspace-link"
    workspace_link.symlink_to(source / "escaped", target_is_directory=True)
    with pytest.raises(ValueError, match="workspace.*source checkout"):
        module.validate_artifact_roots(external_runtime, workspace_link, source)

    with pytest.raises(ValueError, match="workspace root.*BENCH_RUNTIME_HOME"):
        module.validate_artifact_roots(external_runtime, external / "elsewhere", source)


@pytest.mark.parametrize("via_symlink", [False, True])
def test_cli_rejects_runtime_home_inside_checkout_before_creating_artifacts(
    tmp_path: Path, via_symlink: bool
) -> None:
    source = tmp_path / "synthetic-source"
    (source / ".git").mkdir(parents=True)
    copied_example = source / "benchmark-llm" / "examples" / EXAMPLE_DIR.name
    shutil.copytree(EXAMPLE_DIR, copied_example)
    inside_runtime = source / "runtime-home"
    if via_symlink:
        inside_runtime.mkdir()
        configured_runtime = tmp_path / "runtime-link"
        configured_runtime.symlink_to(inside_runtime, target_is_directory=True)
    else:
        configured_runtime = inside_runtime

    env = _fake_environment(tmp_path)
    env["BENCH_RUNTIME_HOME"] = str(configured_runtime)
    stderr = io.StringIO()
    exit_code = main(
        ["run", str(copied_example), "-m", "paired-matrix"],
        environ=env,
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert exit_code == 1
    assert "runtime home" in stderr.getvalue().lower()
    if via_symlink:
        assert list(inside_runtime.iterdir()) == []
    else:
        assert not inside_runtime.exists()


def test_task_schedule_is_interleaved_and_position_balanced() -> None:
    module = _load_example_module()
    tasks = module.load_tasks(EXAMPLE_DIR / "tasks")
    candidates = ["candidate-alpha", "candidate-beta"]
    schedule = module.build_schedule(tasks, candidates, trials=6)

    assert len(schedule) == 6 * len(tasks) * len(candidates)
    assert Counter((row.task.id, row.candidate) for row in schedule) == Counter(
        {(task.id, candidate): 6 for task in tasks for candidate in candidates}
    )
    by_trial: dict[int, list] = defaultdict(list)
    for row in schedule:
        by_trial[row.trial].append(row)
    for rows in by_trial.values():
        task_positions = defaultdict(list)
        for row in rows:
            task_positions[row.task.id].append(row.candidate)
        assert all(sorted(order) == sorted(candidates) for order in task_positions.values())
    first_candidate_counts = Counter(
        rows[index].candidate
        for rows in by_trial.values()
        for index in range(0, len(rows), len(candidates))
    )
    assert max(first_candidate_counts.values()) == min(first_candidate_counts.values())
    first_candidate_by_task = Counter()
    for rows in by_trial.values():
        for index in range(0, len(rows), len(candidates)):
            first_candidate_by_task[(rows[index].task.id, rows[index].candidate)] += 1
    assert set(first_candidate_by_task.values()) == {3}
    task_position_counts = Counter()
    for trial, rows in by_trial.items():
        ordered_task_ids = [rows[index].task.id for index in range(0, len(rows), len(candidates))]
        for position, task_id in enumerate(ordered_task_ids):
            task_position_counts[(task_id, position)] += 1
    assert set(task_position_counts.values()) == {1}


def test_scoring_reports_non_regression_failure_and_nonzero_dispersion() -> None:
    module = _load_example_module()
    candidates = ["candidate-alpha", "candidate-beta"]
    results = []
    for cell in sorted(EXPECTED_CELLS):
        for trial in range(1, 7):
            results.append(
                {
                    "cell": cell,
                    "trial": trial,
                    "candidate": "candidate-alpha",
                    "correct": True,
                    "verification_score": 100.0,
                    "retries": 0,
                    "elapsed_ms": 10.0,
                }
            )
            beta_correct = trial != 6
            results.append(
                {
                    "cell": cell,
                    "trial": trial,
                    "candidate": "candidate-beta",
                    "correct": beta_correct,
                    "verification_score": 100.0 if beta_correct else 0.0,
                    "retries": 1 if trial == 1 else 0,
                    "elapsed_ms": float(10 + trial),
                }
            )

    score = module._score_results(results, candidates)

    for cell in score["cells"].values():
        beta = cell["candidates"]["candidate-beta"]
        assert beta["correctness_rate"] == pytest.approx(5 / 6)
        assert beta["verification_score"]["stdev"] > 0
        assert beta["retry_count"] == 1
        assert cell["comparisons"]["candidate-beta"]["threshold_met"] is False
    assert len(score["paired_results"]) == len(EXPECTED_CELLS) * 6


def test_fake_plugin_run_keeps_every_artifact_external_and_records_provenance(
    tmp_path: Path,
) -> None:
    run_dir, _, _ = _run_fake_matrix(tmp_path)
    runtime_home = tmp_path / "external-runtime"
    source_checkout = EXAMPLE_DIR.parents[2].resolve()

    assert run_dir.is_relative_to(runtime_home.resolve())
    assert not run_dir.resolve().is_relative_to(source_checkout)
    assert (runtime_home / "index.sqlite3").is_file()
    assert (run_dir / "workspaces").is_dir()
    assert len(list((run_dir / "workspaces").iterdir())) == 72
    assert all(path.joinpath(".git").is_dir() for path in (run_dir / "workspaces").iterdir())
    assert all(not path.joinpath("task.json").exists() for path in (run_dir / "workspaces").iterdir())
    assert not any(path.is_file() for path in source_checkout.rglob("result.txt"))
    assert not (tmp_path / "hostile-git-dir").exists()
    assert not (tmp_path / "hostile-git-work-tree").exists()
    assert not (tmp_path / "hostile-hooks").exists()

    results = json.loads((run_dir / "evaluation-results.json").read_text(encoding="utf-8"))
    assert len(results["trials"]) == 72
    assert results["provenance"]["codex_version"] == "codex-cli 0.0.0-synthetic"
    assert results["provenance"]["execution_date"].endswith("Z")
    assert results["provenance"]["reasoning_effort"] == "high"
    assert results["provenance"]["task_order"] == [
        {
            "ordinal": index,
            "trial": row["trial"],
            "task_id": row["task_id"],
            "cell": row["cell"],
            "candidate": row["candidate"],
        }
        for index, row in enumerate(results["trials"], start=1)
    ]
    for row in results["trials"]:
        assert row["candidate"] in {"candidate-alpha", "candidate-beta"}
        assert re.fullmatch(r"[0-9a-f]{64}", row["prompt_sha256"])
        assert row["reasoning_effort"] == "high"
        assert row["correct"] is True
        assert row["verification_score"] == 100.0
        assert row["elapsed_ms"] >= 0
        assert row["attempts"] in {1, 2}
        assert row["retries"] == row["attempts"] - 1
        assert row["metrics"]["total_tokens"] == 15
        assert row["metrics"]["cost_usd"] == 0.001
    retried = [row for row in results["trials"] if row["retries"]]
    assert len(retried) == 6
    assert {row["task_id"] for row in retried} == {"switchyard-resolution"}
    assert {row["candidate"] for row in retried} == {"candidate-beta"}
    assert all(row["attempt_metadata"][0]["exit_code"] == 7 for row in retried)
    assert all(
        row["attempt_metadata"][0]["metrics"]["cost_usd"] == 0.0005
        for row in retried
    )
    assert all(
        not Path(row["workspace"], "attempt-poison.txt").exists() for row in retried
    )


def test_scoring_thresholds_dispersion_and_sanitized_summary(tmp_path: Path) -> None:
    run_dir, _, _ = _run_fake_matrix(tmp_path)
    module = _load_example_module()
    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    assert score["summary"] == {"passed": 72, "total": 72, "score_percent": 100.0}
    assert set(score["cells"]) == EXPECTED_CELLS
    for cell in score["cells"].values():
        assert cell["threshold"] == {
            "minimum_correctness_rate": 1.0,
            "minimum_mean_verification_score": 100.0,
            "maximum_paired_correctness_drop": 0.0,
            "maximum_paired_score_drop": 0.0,
        }
        assert set(cell["candidates"]) == {"candidate-alpha", "candidate-beta"}
        for candidate in cell["candidates"].values():
            assert candidate["sample_count"] == 6
            assert candidate["correctness_rate"] == 1.0
            assert candidate["verification_score"]["mean"] == 100.0
            assert candidate["verification_score"]["stdev"] == 0.0
            assert candidate["verification_score"]["min"] == 100.0
            assert candidate["verification_score"]["max"] == 100.0

    ordinary_usage = score["cells"]["design_orch.orchestration"]["candidates"][
        "candidate-alpha"
    ]["reported_usage"]
    assert ordinary_usage == {
        "trial_count": 6,
        "attempt_count": 6,
        "attempts_reporting_usage": 6,
        "cost_usd": 0.006,
        "input_tokens": 60,
        "output_tokens": 30,
        "total_tokens": 90,
        "provider_latency_ms": 12,
        "turns": 6,
    }

    resolution_beta = score["cells"]["switchyard.resolution"]["candidates"][
        "candidate-beta"
    ]["reported_usage"]
    assert resolution_beta == {
        "trial_count": 6,
        "attempt_count": 12,
        "attempts_reporting_usage": 12,
        "cost_usd": 0.009,
        "input_tokens": 72,
        "output_tokens": 36,
        "total_tokens": 108,
        "provider_latency_ms": 18,
        "turns": 12,
    }

    summary_path = run_dir / "commit-eligible-summary.json"
    summary_text = summary_path.read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    assert summary["artifact_policy"] == "sanitized_commit_eligible_only"
    assert summary["raw_output_included"] is False
    assert summary["sample_size_policy"]["statistically_sufficient"] is False
    assert "trials" not in summary
    assert str(tmp_path) not in summary_text
    assert str(EXAMPLE_DIR.parents[2]) not in summary_text
    assert "/synthetic/private/raw-output" not in summary_text
    assert "candidate-alpha" not in summary_text
    assert "candidate-beta" not in summary_text
    assert "codex-cli 0.0.0-synthetic" not in summary_text
    assert "cost_usd" not in summary_text
    assert summary["candidates"][0]["alias"] == "candidate_1"
    assert summary["candidates"][1]["alias"] == "candidate_2"
    assert not re.search(r"(?:^|[\s\"'])/(?:Users|home|private|tmp)/", summary_text)

    provenance = json.loads(
        (run_dir / "evaluation-results.json").read_text(encoding="utf-8")
    )["provenance"]
    adversarial_score = json.loads(
        json.dumps(score)
        .replace("candidate-alpha", "codex-/Users/example/bin")
        .replace("candidate-beta", "worker-C:\\\\Users\\\\example\\\\bin")
    )
    adversarial_provenance = json.loads(
        json.dumps(provenance)
        .replace("candidate-alpha", "codex-/Users/example/bin")
        .replace("candidate-beta", "worker-C:\\\\Users\\\\example\\\\bin")
    )
    adversarial_provenance["codex_version"] = (
        "codex-/Users/example/bin and C:\\Users\\example\\codex.exe"
    )
    adversarial_path = run_dir / "adversarial-summary.json"
    module._write_sanitized_summary(
        adversarial_path, adversarial_provenance, adversarial_score
    )
    adversarial_text = adversarial_path.read_text(encoding="utf-8")
    assert "/Users/example" not in adversarial_text
    assert "C:" not in adversarial_text
    assert "codex-/Users" not in adversarial_text
    assert "candidate_1" in adversarial_text
    assert "candidate_2" in adversarial_text


@pytest.mark.parametrize(
    "payload",
    [
        {"cost_usd": float("nan")},
        {"provider_latency_ms": float("inf")},
        {"cost_usd": -0.01},
        {"input_tokens": -1},
        {"output_tokens": 1.5},
        {"total_tokens": float("inf")},
        {"turns": 2.25},
    ],
)
def test_metrics_reject_nonfinite_negative_and_fractional_values(
    tmp_path: Path, payload: dict[str, float]
) -> None:
    module = _load_example_module()
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="metric"):
        module._load_metrics(metrics_path)


def test_metrics_normalize_nonnegative_integer_valued_counts(tmp_path: Path) -> None:
    module = _load_example_module()
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "cost_usd": 0.0,
                "input_tokens": 2.0,
                "output_tokens": 3,
                "turns": 1.0,
            }
        ),
        encoding="utf-8",
    )

    assert module._load_metrics(metrics_path) == {
        "cost_usd": 0.0,
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
        "turns": 1,
    }


def test_invalid_trial_count_and_missing_fake_executor_fail_before_execution(
    tmp_path: Path,
) -> None:
    module = _load_example_module()
    tasks = module.load_tasks(EXAMPLE_DIR / "tasks")
    with pytest.raises(ValueError, match="at least 6"):
        module.build_schedule(tasks, ["candidate-alpha", "candidate-beta"], trials=3)

    env = _fake_environment(tmp_path)
    del env["BENCH_ORCHESTRATOR_EVAL_EXECUTOR"]
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        ["run", str(EXAMPLE_DIR), "-m", "paired-matrix"],
        environ=env,
        stdout=stdout,
        stderr=stderr,
    )
    assert exit_code == 1
    assert "BENCH_ORCHESTRATOR_EVAL_EXECUTOR" in stderr.getvalue()
    assert not list((Path(env["BENCH_RUNTIME_HOME"]) / "runs").glob("*/workspaces/*"))
