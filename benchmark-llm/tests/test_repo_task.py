import io
import json
import os
import subprocess
import time
from pathlib import Path

import benchmark_llm.cli as cli_module
from benchmark_llm.cli import main
from benchmark_llm.execution import run_command
from benchmark_llm.repo_task import _resolve_repo_steps


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Benchmark Tests",
            "-c",
            "user.email=synthetic-user@example.invalid",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Benchmark Tests",
            "-c",
            "user.email=synthetic-user@example.invalid",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _wait_for_pid_exit(pid: int, timeout_sec: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.05)
    return False


def test_run_command_returns_without_waiting_for_background_descendants(tmp_path: Path) -> None:
    started = time.monotonic()

    record = run_command(
        "sh -c 'sleep 2 & echo done'",
        cwd=tmp_path,
        env=os.environ.copy(),
        phase="demo",
    )

    elapsed = time.monotonic() - started
    assert record["exit_code"] == 0
    assert record["stdout"].strip() == "done"
    assert elapsed < 1.5


def test_run_command_records_bounded_output_tails_and_progress_events(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []

    record = run_command(
        "sh -c 'for i in $(seq 1 25); do echo line-$i; done'",
        cwd=tmp_path,
        env=os.environ.copy(),
        phase="tail_demo",
        progress_callback=events.append,
    )

    assert record["exit_code"] == 0
    assert record["stdout_bytes"] == len(record["stdout"].encode("utf-8"))
    assert "line-1" in record["stdout"]
    assert "line-1" not in record["stdout_tail"].splitlines()
    assert "line-25" in record["stdout_tail"].splitlines()
    assert [event["event"] for event in events] == ["command_start", "command_end"]
    assert events[0]["stdout_path"] == record["stdout_path"]
    assert events[1]["stdout_bytes"] == record["stdout_bytes"]


def test_run_command_marks_wall_clock_timeout(tmp_path: Path) -> None:
    started = time.monotonic()

    record = run_command(
        "sh -c 'sleep 5'",
        cwd=tmp_path,
        env=os.environ.copy(),
        phase="wall_timeout",
        timeout_sec=1,
    )

    elapsed = time.monotonic() - started
    assert record["exit_code"] == -15
    assert record["timed_out"] is True
    assert "inactivity_timed_out" not in record
    assert elapsed < 2.5


def test_run_command_marks_inactivity_timeout_after_output_stalls(tmp_path: Path) -> None:
    started = time.monotonic()

    record = run_command(
        "sh -c 'echo start; sleep 5'",
        cwd=tmp_path,
        env=os.environ.copy(),
        phase="inactivity_timeout",
        inactivity_timeout_sec=1,
    )

    elapsed = time.monotonic() - started
    assert record["exit_code"] == -15
    assert record["inactivity_timed_out"] is True
    assert "timed_out" not in record
    assert record["stdout"] == "start\n"
    assert elapsed < 2.5


def test_run_command_timeout_kills_spawned_child_processes(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    _write_text(
        tmp_path / "spawn_child.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "sleep 30 &",
                "child=$!",
                f"printf '%s' \"$child\" > '{child_pid_path}'",
                "wait \"$child\"",
            ]
        )
        + "\n",
    )
    os.chmod(tmp_path / "spawn_child.sh", 0o755)

    record = run_command(
        "./spawn_child.sh",
        cwd=tmp_path,
        env=os.environ.copy(),
        phase="process_group_timeout",
        timeout_sec=1,
    )

    assert record["exit_code"] == -15
    assert record["timed_out"] is True
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    assert _wait_for_pid_exit(child_pid)


def test_repo_task_resolves_execution_defaults_and_step_overrides() -> None:
    steps = _resolve_repo_steps(
        {
            "execution_defaults": {
                "timeout_sec": 111,
                "inactivity_timeout_sec": 222,
                "retries": {"max_attempts": 1, "backoff_sec": 9},
            },
            "executor": {"kind": "cli", "command": "./scripts/invoke_model.sh"},
            "steps": [
                {"name": "prepare", "run": "./scripts/prepare.sh"},
                {
                    "name": "execute",
                    "use_executor": True,
                    "timeout_sec": 333,
                    "retries": {"max_attempts": 4, "backoff_sec": 0},
                },
            ],
        }
    )

    assert steps[0].timeout_sec == 111
    assert steps[0].inactivity_timeout_sec == 222
    assert steps[0].retry_max_attempts == 1
    assert steps[0].retry_backoff_sec == 9
    assert steps[1].timeout_sec == 333
    assert steps[1].inactivity_timeout_sec == 222
    assert steps[1].retry_max_attempts == 4
    assert steps[1].retry_backoff_sec == 0


def test_repo_task_defaults_to_one_breadth_run_when_settings_are_absent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    benchmark_dir = tmp_path / "bench"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                f"output_dir: {tmp_path / 'results'}",
            ]
        )
        + "\n",
    )

    observed_models: list[str] = []

    def fake_run_repo_task(
        *,
        benchmark_dir: Path,
        runtime_home: Path,
        model: str,
        environ: dict[str, str],
        config: dict[str, object] | None = None,
        progress_callback=None,
    ) -> Path:
        observed_models.append(model)
        return runtime_home / "runs" / f"fake-{len(observed_models)}"

    monkeypatch.setattr(cli_module, "run_repo_task", fake_run_repo_task)

    exit_code = main(
        ["run", str(benchmark_dir), "-m", "model-a,model-b"],
        environ={"BENCH_RUNTIME_HOME": str(tmp_path / "runtime-home")},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert observed_models == ["model-a", "model-b"]


def test_repo_task_expands_runs_in_requested_breadth_or_depth_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "results"
    observed_models: list[str] = []

    def fake_run_repo_task(
        *,
        benchmark_dir: Path,
        runtime_home: Path,
        model: str,
        environ: dict[str, str],
        config: dict[str, object] | None = None,
        progress_callback=None,
    ) -> Path:
        observed_models.append(model)
        return runtime_home / "runs" / f"fake-{len(observed_models)}"

    monkeypatch.setattr(cli_module, "run_repo_task", fake_run_repo_task)

    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "runs: 3",
                "run_order: breadth",
                f"output_dir: {results_dir}",
            ]
        )
        + "\n",
    )

    exit_code = main(
        ["run", str(benchmark_dir), "-m", "model-a,model-b"],
        environ={"BENCH_RUNTIME_HOME": str(tmp_path / "runtime-home-breadth")},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert observed_models == ["model-a", "model-b", "model-a", "model-b", "model-a", "model-b"]

    observed_models.clear()
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "runs: 3",
                "run_order: depth",
                f"output_dir: {results_dir}",
            ]
        )
        + "\n",
    )

    exit_code = main(
        ["run", str(benchmark_dir), "-m", "model-a,model-b"],
        environ={"BENCH_RUNTIME_HOME": str(tmp_path / "runtime-home-depth")},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert observed_models == ["model-a", "model-a", "model-a", "model-b", "model-b", "model-b"]


def test_repo_task_requires_output_dir_before_starting_any_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    benchmark_dir = tmp_path / "bench"
    _write_text(benchmark_dir / "bench.yaml", "type: repo_task\n")

    called = False

    def fake_run_repo_task(**_: object) -> Path:
        nonlocal called
        called = True
        return tmp_path / "should-not-run"

    monkeypatch.setattr(cli_module, "run_repo_task", fake_run_repo_task)

    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        ["run", str(benchmark_dir), "-m", "model-a"],
        environ={"BENCH_RUNTIME_HOME": str(tmp_path / "runtime-home")},
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert called is False
    assert "output_dir" in stderr.getvalue()


def test_repo_task_writes_run_artifacts_under_configured_output_dir(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "seed.txt", "seed\n")
    _git(["add", "seed.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "nested" / "results" / "bench-output"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "id: output-root-check",
                f"output_dir: {results_dir}",
                "workspace:",
                "  kind: git_worktree",
                f"  source_repo: {source_repo}",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - name: prepare",
                "    run: ./scripts/prepare.sh",
                "  - name: execute",
                "    use_executor: true",
                "  - name: judge",
                "    run: python ./scripts/judge.py",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(benchmark_dir / "prompt.txt", "Do work.\n")
    _write_text(
        benchmark_dir / "scripts" / "prepare.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p \"$BENCH_WORKSPACE/output\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'done\\n' > \"$WORKSPACE_ROOT/output/result.txt\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "judge.py",
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "run_dir = Path(os.environ['BENCH_RUN_DIR'])",
                "workspace = Path(os.environ['BENCH_WORKSPACE'])",
                "assert (workspace / 'output' / 'result.txt').read_text(encoding='utf-8').strip() == 'done'",
                "with (run_dir / 'score.json').open('w', encoding='utf-8') as handle:",
                "    json.dump({'summary': {'passed': 1, 'total': 1, 'score_percent': 100.0}, 'checks': [{'name': 'ok', 'passed': True}]}, handle)",
            ]
        )
        + "\n",
    )
    os.chmod(benchmark_dir / "scripts" / "prepare.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"
    exit_code = main(
        ["run", str(benchmark_dir), "-m", "demo-model"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert results_dir.is_dir()
    run_dirs = sorted(results_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert run_dir.is_dir()
    assert not any((runtime_home / "runs").iterdir())

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert Path(manifest["artifacts"]["score"]).parent == run_dir
    assert Path(manifest["artifacts"]["report"]).parent == run_dir


def test_repo_task_invokes_one_final_summary_after_all_successful_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "results"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "runs: 2",
                "run_order: breadth",
                f"output_dir: {results_dir}",
                "steps:",
                "  - name: adjudicate",
                "    run: ./scripts/adjudicate.sh",
            ]
        )
        + "\n",
    )

    created_run_dirs: list[Path] = []
    summary_run_dirs: list[Path] = []

    def fake_run_repo_task(
        *,
        benchmark_dir: Path,
        runtime_home: Path,
        model: str,
        environ: dict[str, str],
        config: dict[str, object] | None = None,
        progress_callback=None,
    ) -> Path:
        run_dir = results_dir / f"{len(created_run_dirs) + 1:02d}__{model}"
        created_run_dirs.append(run_dir)
        return run_dir

    def fake_run_repo_task_final_summary(
        *,
        benchmark_dir: Path,
        runtime_home: Path,
        run_dirs: list[Path],
        environ: dict[str, str],
        config: dict[str, object] | None = None,
        progress_callback=None,
    ) -> Path:
        summary_run_dirs.extend(run_dirs)
        return results_dir / "summary.md"

    monkeypatch.setattr(cli_module, "run_repo_task", fake_run_repo_task)
    monkeypatch.setattr(
        cli_module,
        "run_repo_task_final_summary",
        fake_run_repo_task_final_summary,
        raising=False,
    )

    exit_code = main(
        ["run", str(benchmark_dir), "-m", "model-a,model-b"],
        environ={"BENCH_RUNTIME_HOME": str(tmp_path / "runtime-home")},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert created_run_dirs == [
        results_dir / "01__model-a",
        results_dir / "02__model-b",
        results_dir / "03__model-a",
        results_dir / "04__model-b",
    ]
    assert summary_run_dirs == created_run_dirs


def test_repo_task_final_summary_receives_attempted_failed_run_dirs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "results"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                f"output_dir: {results_dir}",
                "steps:",
                "  - name: adjudicate",
                "    run: ./scripts/adjudicate.sh",
            ]
        )
        + "\n",
    )

    attempted_run_dirs: list[Path] = []
    summary_run_dirs: list[Path] = []

    class FakeRunError(RuntimeError):
        def __init__(self, run_dir: Path) -> None:
            super().__init__("boom")
            self.run_dir = run_dir

    def fake_run_repo_task(
        *,
        benchmark_dir: Path,
        runtime_home: Path,
        model: str,
        environ: dict[str, str],
        config: dict[str, object] | None = None,
        progress_callback=None,
    ) -> Path:
        run_dir = results_dir / f"{len(attempted_run_dirs) + 1:02d}__{model}"
        attempted_run_dirs.append(run_dir)
        if model == "model-b":
            raise FakeRunError(run_dir)
        return run_dir

    def fake_run_repo_task_final_summary(
        *,
        benchmark_dir: Path,
        runtime_home: Path,
        run_dirs: list[Path],
        environ: dict[str, str],
        config: dict[str, object] | None = None,
        progress_callback=None,
    ) -> Path:
        summary_run_dirs.extend(run_dirs)
        return results_dir / "summary.md"

    monkeypatch.setattr(cli_module, "run_repo_task", fake_run_repo_task)
    monkeypatch.setattr(
        cli_module,
        "run_repo_task_final_summary",
        fake_run_repo_task_final_summary,
        raising=False,
    )

    exit_code = main(
        ["run", str(benchmark_dir), "-m", "model-a,model-b"],
        environ={"BENCH_RUNTIME_HOME": str(tmp_path / "runtime-home")},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 1
    assert attempted_run_dirs == [
        results_dir / "01__model-a",
        results_dir / "02__model-b",
    ]
    assert summary_run_dirs == attempted_run_dirs


def test_repo_task_run_cleans_up_successful_worktree_and_records_branch_provenance(
    tmp_path: Path,
) -> None:
    source_repo = tmp_path / "policy-engine-source"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "app.txt", "seed\n")
    _git(["add", "app.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    benchmark_dir = tmp_path / "policy-engine"
    results_dir = tmp_path / "results"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "id: policy-engine",
                f"output_dir: {results_dir}",
                "workspace:",
                "  kind: git_worktree",
                "  source_repo: ${BENCH_SOURCE_REPO}",
                "  keep_workspace: true",
                "  commit_outputs: true",
                "visibility:",
                "  expose:",
                "    - task-visible/**",
                "    - prompt.txt",
                "  hide:",
                "    - evaluator-only/**",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - name: prepare_visible",
                "    run: ./scripts/prepare.sh",
                "  - name: execute",
                "    use_executor: true",
                "  - name: judge_hidden",
                "    run: python ./scripts/judge.py",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(benchmark_dir / "prompt.txt", "Solve the repo task.\n")
    _write_text(benchmark_dir / "task-visible" / "visible-note.txt", "visible artifact\n")
    _write_text(benchmark_dir / "evaluator-only" / "expected.txt", "secret\n")
    _write_text(
        benchmark_dir / "scripts" / "prepare.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "test -f \"$BENCH_BENCHMARK_DIR/prompt.txt\"",
                "test -f \"$BENCH_WORKSPACE/visible-note.txt\"",
                "test ! -e \"$BENCH_WORKSPACE/evaluator-only/expected.txt\"",
                "mkdir -p \"$BENCH_WORKSPACE/output\"",
                "printf 'prepared\\n' > \"$BENCH_WORKSPACE/output/prepare.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "test -n \"$MODEL_ID\"",
                "test -n \"$WORKSPACE_ROOT\"",
                "test -n \"$TASK_PROMPT_PATH\"",
                "[[ -z ${BENCH_MODEL+x} ]]",
                "[[ -z ${BENCH_BENCHMARK_DIR+x} ]]",
                "[[ -z ${BENCH_WORKSPACE+x} ]]",
                "[[ -z ${PYTEST_CURRENT_TEST+x} ]]",
                "python - <<'PY'",
                "import json, os",
                "from pathlib import Path",
                "Path(os.environ['TASK_METRICS_PATH']).write_text(json.dumps({",
                "    'cost_usd': 0.33,",
                "    'input_tokens': 120,",
                "    'output_tokens': 45,",
                "    'provider_latency_ms': 987,",
                "}), encoding='utf-8')",
                "PY",
                "printf 'model=%s\\n' \"$MODEL_ID\" > \"$WORKSPACE_ROOT/output/result.txt\"",
                "cat \"$TASK_PROMPT_PATH\" >> \"$WORKSPACE_ROOT/output/result.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "judge.py",
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "",
                "workspace = Path(os.environ['BENCH_WORKSPACE'])",
                "run_dir = Path(os.environ['BENCH_RUN_DIR'])",
                "hidden_dir = Path(os.environ['BENCH_HIDDEN_DIR'])",
                "",
                "assert (workspace / 'visible-note.txt').read_text(encoding='utf-8').strip() == 'visible artifact'",
                "assert not (workspace / 'evaluator-only' / 'expected.txt').exists()",
                "assert (hidden_dir / 'expected.txt').read_text(encoding='utf-8').strip() == 'secret'",
                "command_rows = [json.loads(line) for line in (run_dir / 'commands.jsonl').read_text(encoding='utf-8').splitlines()]",
                "assert [row['phase'] for row in command_rows] == ['prepare_visible', 'execute']",
                "result_text = (workspace / 'output' / 'result.txt').read_text(encoding='utf-8')",
                "assert 'demo-model' in result_text",
                "score = {",
                "    'summary': {'passed': 3, 'total': 3, 'score_percent': 100.0},",
                "    'checks': [",
                "        {'name': 'visible copy', 'passed': True},",
                "        {'name': 'hidden isolation', 'passed': True},",
                "        {'name': 'executor output', 'passed': True},",
                "    ],",
                "}",
                "with (run_dir / 'score.json').open('w', encoding='utf-8') as handle:",
                "    json.dump(score, handle, indent=2)",
            ]
        )
        + "\n",
    )
    os.chmod(benchmark_dir / "scripts" / "prepare.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["run", str(benchmark_dir), "-m", "demo-model"],
        environ={
            "BENCH_RUNTIME_HOME": str(runtime_home),
            "BENCH_SOURCE_REPO": str(source_repo),
        },
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0, stderr.getvalue()
    run_dirs = sorted(results_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["benchmark"]["mode"] == "repo_task"
    assert manifest["timing"]["elapsed_ms"] >= 0
    assert manifest["metrics"]["cost_usd"] == 0.33
    assert manifest["metrics"]["input_tokens"] == 120
    assert manifest["metrics"]["output_tokens"] == 45
    assert manifest["metrics"]["total_tokens"] == 165
    workspace_path = Path(manifest["workspace"]["path"])
    assert not workspace_path.exists()
    assert manifest["workspace"]["keep_workspace"] is False
    assert manifest["workspace"]["commit_after_run"]
    branch_name = manifest["workspace"]["branch"]
    assert branch_name in _git_output(["branch", "--list"], cwd=source_repo)
    worktree_list = _git_output(["worktree", "list", "--porcelain"], cwd=source_repo)
    assert str(workspace_path) not in worktree_list

    command_rows = [
        json.loads(line)
        for line in (run_dir / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in command_rows] == [
        "prepare_visible",
        "execute",
        "judge_hidden",
    ]
    assert command_rows[1]["command"] == "./scripts/invoke_model.sh"
    assert all(row["exit_code"] == 0 for row in command_rows)
    assert all(row["elapsed_ms"] >= 0 for row in command_rows)
    assert command_rows[1]["metrics"]["cost_usd"] == 0.33

    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    assert score["summary"]["score_percent"] == 100.0


def test_repo_task_string_steps_still_honor_executor_command(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "seed.txt", "seed\n")
    _git(["add", "seed.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "results"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                f"output_dir: {results_dir}",
                "workspace:",
                "  kind: git_worktree",
                f"  source_repo: {source_repo}",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - ./scripts/prepare.sh",
                "  - ./scripts/invoke_model.sh",
                "  - python ./scripts/judge.py",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "prepare.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p \"$BENCH_WORKSPACE/output\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "test -n \"$WORKSPACE_ROOT\"",
                "[[ -z ${BENCH_WORKSPACE+x} ]]",
                "[[ -z ${PYTEST_CURRENT_TEST+x} ]]",
                "printf 'from executor\\n' > \"$WORKSPACE_ROOT/output/result.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "judge.py",
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "run_dir = Path(os.environ['BENCH_RUN_DIR'])",
                "workspace = Path(os.environ['BENCH_WORKSPACE'])",
                "assert (workspace / 'output' / 'result.txt').read_text(encoding='utf-8').strip() == 'from executor'",
                "with (run_dir / 'score.json').open('w', encoding='utf-8') as handle:",
                "    json.dump({'summary': {'passed': 1, 'total': 1, 'score_percent': 100.0}, 'checks': [{'name': 'ok', 'passed': True}]}, handle)",
            ]
        )
        + "\n",
    )
    os.chmod(benchmark_dir / "scripts" / "prepare.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"
    exit_code = main(
        ["run", str(benchmark_dir), "-m", "demo-model"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    run_dir = next(results_dir.iterdir())
    command_rows = [
        json.loads(line)
        for line in (run_dir / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in command_rows] == ["step_1", "execute", "step_3"]


def test_repo_task_retries_execute_in_fresh_workspace_and_preserves_attempts(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "seed.txt", "seed\n")
    _git(["add", "seed.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    counter_path = tmp_path / "attempt-counter.txt"
    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "results"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "id: retry-check",
                f"output_dir: {results_dir}",
                "workspace:",
                "  kind: git_worktree",
                f"  source_repo: {source_repo}",
                "  keep_workspace: true",
                "execution_defaults:",
                "  timeout_sec: 30",
                "  inactivity_timeout_sec: 30",
                "  retries:",
                "    max_attempts: 1",
                "    backoff_sec: 0",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - name: prepare",
                "    run: ./scripts/prepare.sh",
                "  - name: execute",
                "    use_executor: true",
                "    retries:",
                "      max_attempts: 2",
                "      backoff_sec: 0",
                "  - name: judge",
                "    run: python ./scripts/judge.py",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(benchmark_dir / "prompt.txt", "Do work.\n")
    _write_text(
        benchmark_dir / "scripts" / "prepare.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p \"$BENCH_WORKSPACE/output\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"COUNTER_PATH='{counter_path}'",
                "count=0",
                "if [ -f \"$COUNTER_PATH\" ]; then",
                "  count=$(cat \"$COUNTER_PATH\")",
                "fi",
                "count=$((count + 1))",
                "printf '%s' \"$count\" > \"$COUNTER_PATH\"",
                "if [ \"$count\" -eq 1 ]; then",
                "  printf 'contaminated\\n' > \"$WORKSPACE_ROOT/contamination.txt\"",
                "  printf '{\"type\":\"error\",\"error\":{\"message\":\"{\\\"code\\\":502,\\\"message\\\":\\\"Network connection lost.\\\",\\\"metadata\\\":{\\\"error_type\\\":\\\"provider_unavailable\\\"}}\"}}\\n'",
                "  exit 0",
                "fi",
                "printf 'success\\n' > \"$WORKSPACE_ROOT/output/result.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "judge.py",
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "",
                "run_dir = Path(os.environ['BENCH_RUN_DIR'])",
                "workspace = Path(os.environ['BENCH_WORKSPACE'])",
                "assert not (workspace / 'contamination.txt').exists()",
                "assert (workspace / 'output' / 'result.txt').read_text(encoding='utf-8').strip() == 'success'",
                "command_rows = [json.loads(line) for line in (run_dir / 'commands.jsonl').read_text(encoding='utf-8').splitlines()]",
                "assert [row['phase'] for row in command_rows] == ['prepare', 'execute']",
                "with (run_dir / 'score.json').open('w', encoding='utf-8') as handle:",
                "    json.dump({'summary': {'passed': 1, 'total': 1, 'score_percent': 100.0}, 'checks': [{'name': 'ok', 'passed': True}]}, handle)",
            ]
        )
        + "\n",
    )
    os.chmod(benchmark_dir / "scripts" / "prepare.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"
    exit_code = main(
        ["run", str(benchmark_dir), "-m", "demo-model"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    run_dir = next(results_dir.iterdir())
    attempts_root = run_dir / "attempts"
    attempt_dirs = sorted(attempts_root.iterdir())
    assert [path.name for path in attempt_dirs] == ["01", "02"]

    attempt_one_rows = [
        json.loads(line)
        for line in (attempt_dirs[0] / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in attempt_one_rows] == ["prepare", "execute"]
    assert "provider_unavailable" in attempt_one_rows[1]["stdout"]

    attempt_two_rows = [
        json.loads(line)
        for line in (attempt_dirs[1] / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in attempt_two_rows] == ["prepare", "execute", "judge"]

    final_rows = [
        json.loads(line)
        for line in (run_dir / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in final_rows] == ["prepare", "execute", "judge"]

    worktree_root = runtime_home / "worktrees" / "retry-check" / "demo-model"
    assert len(list(worktree_root.iterdir())) == 1


def test_repo_task_does_not_retry_successful_non_model_step_on_provider_like_output(
    tmp_path: Path,
) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "seed.txt", "seed\n")
    _git(["add", "seed.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "results"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "id: adjudicate-pattern-check",
                f"output_dir: {results_dir}",
                "workspace:",
                "  kind: git_worktree",
                f"  source_repo: {source_repo}",
                "  commit_outputs: true",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - name: prepare",
                "    run: ./scripts/prepare.sh",
                "  - name: execute",
                "    use_executor: true",
                "  - name: adjudicate",
                "    run: python ./scripts/judge.py",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(benchmark_dir / "prompt.txt", "Do work.\n")
    _write_text(
        benchmark_dir / "scripts" / "prepare.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p \"$BENCH_WORKSPACE/output\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "mkdir -p \"$WORKSPACE_ROOT/output\"",
                "printf 'success\\n' > \"$WORKSPACE_ROOT/output/result.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "judge.py",
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "",
                "run_dir = Path(os.environ['BENCH_RUN_DIR'])",
                "workspace = Path(os.environ['BENCH_WORKSPACE'])",
                "assert (workspace / 'output' / 'result.txt').read_text(encoding='utf-8').strip() == 'success'",
                "print('{\"error\": true, \"message\": \"example only\", \"code\":503, \"kind\":\"provider_unavailable\"}')",
                "with (run_dir / 'score.json').open('w', encoding='utf-8') as handle:",
                "    json.dump({'summary': {'passed': 1, 'total': 1, 'score_percent': 100.0}, 'checks': [{'name': 'ok', 'passed': True}]}, handle)",
            ]
        )
        + "\n",
    )
    os.chmod(benchmark_dir / "scripts" / "prepare.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        ["run", str(benchmark_dir), "-m", "demo-model"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0, stderr.getvalue()
    run_dir = next(results_dir.iterdir())
    assert not (run_dir / "failure.json").exists()

    command_rows = [
        json.loads(line)
        for line in (run_dir / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in command_rows] == ["prepare", "execute", "adjudicate"]
    assert command_rows[2]["exit_code"] == 0
    assert "retryable_failure" not in command_rows[2]


def test_repo_task_retries_execute_after_inactivity_timeout(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "seed.txt", "seed\n")
    _git(["add", "seed.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    counter_path = tmp_path / "attempt-counter.txt"
    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "results"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "id: timeout-retry-check",
                f"output_dir: {results_dir}",
                "workspace:",
                "  kind: git_worktree",
                f"  source_repo: {source_repo}",
                "  keep_workspace: true",
                "execution_defaults:",
                "  timeout_sec: 10",
                "  inactivity_timeout_sec: 1",
                "  retries:",
                "    max_attempts: 1",
                "    backoff_sec: 0",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - name: prepare",
                "    run: ./scripts/prepare.sh",
                "  - name: execute",
                "    use_executor: true",
                "    retries:",
                "      max_attempts: 2",
                "      backoff_sec: 0",
                "  - name: judge",
                "    run: python ./scripts/judge.py",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(benchmark_dir / "prompt.txt", "Do work.\n")
    _write_text(
        benchmark_dir / "scripts" / "prepare.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p \"$BENCH_WORKSPACE/output\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"COUNTER_PATH='{counter_path}'",
                "count=0",
                "if [ -f \"$COUNTER_PATH\" ]; then",
                "  count=$(cat \"$COUNTER_PATH\")",
                "fi",
                "count=$((count + 1))",
                "printf '%s' \"$count\" > \"$COUNTER_PATH\"",
                "if [ \"$count\" -eq 1 ]; then",
                "  printf 'start\\n'",
                "  sleep 5",
                "  exit 0",
                "fi",
                "printf 'success\\n' > \"$WORKSPACE_ROOT/output/result.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "judge.py",
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "",
                "run_dir = Path(os.environ['BENCH_RUN_DIR'])",
                "workspace = Path(os.environ['BENCH_WORKSPACE'])",
                "assert (workspace / 'output' / 'result.txt').read_text(encoding='utf-8').strip() == 'success'",
                "with (run_dir / 'score.json').open('w', encoding='utf-8') as handle:",
                "    json.dump({'summary': {'passed': 1, 'total': 1, 'score_percent': 100.0}, 'checks': [{'name': 'ok', 'passed': True}]}, handle)",
            ]
        )
        + "\n",
    )
    os.chmod(benchmark_dir / "scripts" / "prepare.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"
    exit_code = main(
        ["run", str(benchmark_dir), "-m", "demo-model"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    run_dir = next(results_dir.iterdir())
    attempts_root = run_dir / "attempts"
    attempt_dirs = sorted(attempts_root.iterdir())
    assert [path.name for path in attempt_dirs] == ["01", "02"]

    attempt_one_rows = [
        json.loads(line)
        for line in (attempt_dirs[0] / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in attempt_one_rows] == ["prepare", "execute"]
    assert attempt_one_rows[1]["inactivity_timed_out"] is True
    assert attempt_one_rows[1]["retry_reason"] == "inactivity_timeout"

    attempt_two_rows = [
        json.loads(line)
        for line in (attempt_dirs[1] / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in attempt_two_rows] == ["prepare", "execute", "judge"]


def test_run_continues_past_failed_repo_task_model_and_returns_nonzero(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "seed.txt", "seed\n")
    _git(["add", "seed.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "results"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "id: continue-on-failure-check",
                f"output_dir: {results_dir}",
                "workspace:",
                "  kind: git_worktree",
                f"  source_repo: {source_repo}",
                "  keep_workspace: true",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - name: prepare",
                "    run: ./scripts/prepare.sh",
                "  - name: execute",
                "    use_executor: true",
                "  - name: judge",
                "    run: python ./scripts/judge.py",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(benchmark_dir / "prompt.txt", "Do work.\n")
    _write_text(
        benchmark_dir / "scripts" / "prepare.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p \"$BENCH_WORKSPACE/output\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "if [ \"$MODEL_ID\" = 'fail-model' ]; then",
                "  echo 'simulated executor failure' >&2",
                "  exit 2",
                "fi",
                "printf 'success\\n' > \"$WORKSPACE_ROOT/output/result.txt\"",
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "judge.py",
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "",
                "run_dir = Path(os.environ['BENCH_RUN_DIR'])",
                "workspace = Path(os.environ['BENCH_WORKSPACE'])",
                "assert (workspace / 'output' / 'result.txt').read_text(encoding='utf-8').strip() == 'success'",
                "with (run_dir / 'score.json').open('w', encoding='utf-8') as handle:",
                "    json.dump({'summary': {'passed': 1, 'total': 1, 'score_percent': 100.0}, 'checks': [{'name': 'ok', 'passed': True}]}, handle)",
            ]
        )
        + "\n",
    )
    os.chmod(benchmark_dir / "scripts" / "prepare.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["run", str(benchmark_dir), "-m", "fail-model,ok-model"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    run_dirs = sorted(results_dir.iterdir())
    assert len(run_dirs) == 2

    failed_runs = [path for path in run_dirs if (path / "failure.json").exists()]
    succeeded_runs = [path for path in run_dirs if (path / "manifest.json").exists()]
    assert len(failed_runs) == 1
    assert len(succeeded_runs) == 1

    failure_payload = json.loads((failed_runs[0] / "failure.json").read_text(encoding="utf-8"))
    assert failure_payload["model"] == "fail-model"
    assert failure_payload["error"] == "simulated executor failure\n"
    assert failure_payload["failed_command"]["phase"] == "execute"
    assert failure_payload["failed_command"]["exit_code"] == 2
    assert failure_payload["failed_command"]["stderr_tail"] == "simulated executor failure\n"
    assert failure_payload["attempts"][0]["failed_command"]["stderr_path"].endswith(
        "02__execute.stderr.log"
    )
    success_manifest = json.loads((succeeded_runs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert success_manifest["model"] == "ok-model"
    stderr_text = stderr.getvalue()
    assert "fail-model" in stderr_text
    assert "[bench] plan:" in stderr_text
    assert "run 1/2" in stderr_text
    assert "phase execute started" in stderr_text
    assert "phase execute finished exit=2" in stderr_text
    assert "Created run:" in stdout.getvalue()


def test_repo_task_failure_preserves_run_dir_and_worktree(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(["init", "-b", "main"], cwd=source_repo)
    _write_text(source_repo / "seed.txt", "seed\n")
    _git(["add", "seed.txt"], cwd=source_repo)
    _git(["commit", "-m", "seed"], cwd=source_repo)

    benchmark_dir = tmp_path / "bench"
    results_dir = tmp_path / "results"
    _write_text(
        benchmark_dir / "bench.yaml",
        "\n".join(
            [
                "type: repo_task",
                "id: cleanup-check",
                f"output_dir: {results_dir}",
                "workspace:",
                "  kind: git_worktree",
                f"  source_repo: {source_repo}",
                "  keep_workspace: true",
                "executor:",
                "  kind: cli",
                "  command: ./scripts/invoke_model.sh",
                "steps:",
                "  - name: execute",
                "    use_executor: true",
                "  - name: fail",
                "    run: ./scripts/fail.sh",
                "scoring:",
                "  output: score.json",
            ]
        )
        + "\n",
    )
    _write_text(benchmark_dir / "prompt.txt", "Do work.\n")
    _write_text(
        benchmark_dir / "scripts" / "invoke_model.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'ok\\n' > \"$WORKSPACE_ROOT/result.txt\"\n",
    )
    _write_text(
        benchmark_dir / "scripts" / "fail.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\necho 'expected failure' >&2\nexit 2\n",
    )
    os.chmod(benchmark_dir / "scripts" / "invoke_model.sh", 0o755)
    os.chmod(benchmark_dir / "scripts" / "fail.sh", 0o755)

    runtime_home = tmp_path / "runtime-home"

    stderr = io.StringIO()
    exit_code = main(
        ["run", str(benchmark_dir), "-m", "demo-model"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert exit_code == 1
    assert "expected failure" in stderr.getvalue()

    run_dirs = list(results_dir.iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "attempts" / "01" / "commands.jsonl").exists()

    worktree_root = runtime_home / "worktrees" / "cleanup-check" / "demo-model"
    assert any(worktree_root.iterdir()) if worktree_root.exists() else False

    assert "bench/cleanup-check/demo-model" in _git_output(["branch", "--list"], cwd=source_repo)
    worktree_list = _git_output(["worktree", "list", "--porcelain"], cwd=source_repo)
    assert str(runtime_home / "worktrees") in worktree_list
