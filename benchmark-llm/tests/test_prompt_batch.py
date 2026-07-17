import io
import json
import os
from pathlib import Path

from benchmark_llm.cli import main


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_prompt_batch_run_creates_expected_artifacts(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "logic-mini"
    _write_text(
        benchmark_dir / "cases.jsonl",
        "\n".join(
            [
                json.dumps({"id": "p1", "prompt": "What comes next: 2, 3, 5, 8, ?"}),
                json.dumps({"id": "p2", "prompt": "2 + 2 = ?"}),
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "answers.jsonl",
        "\n".join(
            [
                json.dumps({"id": "p1", "answer": "13"}),
                json.dumps({"id": "p2", "answer": "4"}),
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "judge.yaml",
        "type: exact_match\nnormalize:\n  - strip\n  - lowercase\n",
    )
    executor = tmp_path / "fake_executor.py"
    _write_text(
        executor,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import os",
                "assert 'BENCH_PROMPT_TEXT' not in os.environ",
                "assert 'PYTEST_CURRENT_TEST' not in os.environ",
                "prompt = os.environ['TASK_PROMPT_TEXT']",
                "if '2 + 2' in prompt:",
                "    print('4')",
                "else:",
                "    print('13')",
            ]
        )
        + "\n",
    )
    executor.chmod(0o755)

    runtime_home = tmp_path / "runtime-home"
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "run",
            str(benchmark_dir),
            "-m",
            "demo-model",
            "--executor-command",
            str(executor),
        ],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0, stderr.getvalue()
    run_dirs = sorted((runtime_home / "runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["benchmark"]["id"] == "logic-mini"
    assert manifest["benchmark"]["mode"] == "prompt_batch"
    assert manifest["model"] == "demo-model"
    assert manifest["timing"]["elapsed_ms"] >= 0

    raw_responses = [
        json.loads(line)
        for line in (run_dir / "raw_responses.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["response_text"] for row in raw_responses] == ["13", "4"]

    judged_rows = [
        json.loads(line)
        for line in (run_dir / "judged.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(row["passed"] for row in judged_rows)

    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    assert score["summary"]["passed"] == 2
    assert score["summary"]["total"] == 2
    assert score["summary"]["score_percent"] == 100.0

    report_text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "logic-mini" in report_text
    assert "demo-model" in report_text
    assert "100.0%" in report_text
    assert "Elapsed" in report_text


def test_list_and_report_use_saved_run_index(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "logic-mini"
    _write_text(
        benchmark_dir / "cases.jsonl",
        json.dumps({"id": "p1", "prompt": "Say yes"}) + "\n",
    )
    _write_text(
        benchmark_dir / "answers.jsonl",
        json.dumps({"id": "p1", "answer": "yes"}) + "\n",
    )
    _write_text(
        benchmark_dir / "judge.yaml",
        "type: exact_match\nnormalize:\n  - strip\n  - lowercase\n",
    )
    executor = tmp_path / "echo_yes.py"
    _write_text(
        executor,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "print('YES')",
            ]
        )
        + "\n",
    )
    executor.chmod(0o755)

    runtime_home = tmp_path / "runtime-home"
    run_stdout = io.StringIO()
    run_stderr = io.StringIO()
    run_code = main(
        [
            "run",
            str(benchmark_dir),
            "-m",
            "demo-model",
            "--executor-command",
            str(executor),
        ],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=run_stdout,
        stderr=run_stderr,
    )
    assert run_code == 0, run_stderr.getvalue()

    list_stdout = io.StringIO()
    list_stderr = io.StringIO()
    list_code = main(
        ["list"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=list_stdout,
        stderr=list_stderr,
    )
    assert list_code == 0, list_stderr.getvalue()
    assert "logic-mini" in list_stdout.getvalue()
    assert "demo-model" in list_stdout.getvalue()
    assert "100.0%" in list_stdout.getvalue()

    report_stdout = io.StringIO()
    report_stderr = io.StringIO()
    report_code = main(
        ["report", "latest"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=report_stdout,
        stderr=report_stderr,
    )
    assert report_code == 0, report_stderr.getvalue()
    assert "# Benchmark Run Report" in report_stdout.getvalue()
    assert "logic-mini" in report_stdout.getvalue()


def test_prompt_batch_supports_command_backed_llm_judge(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "semantic-mini"
    _write_text(
        benchmark_dir / "cases.jsonl",
        json.dumps({"id": "p1", "prompt": "What is two plus two?"}) + "\n",
    )
    _write_text(
        benchmark_dir / "answers.jsonl",
        json.dumps({"id": "p1", "answer": "4"}) + "\n",
    )
    _write_text(
        benchmark_dir / "judge.yaml",
        "\n".join(
            [
                "type: llm_judge",
                f"judge_command: {tmp_path / 'judge.py'}",
                "rubric: |",
                "  Grade semantic equivalence.",
            ]
        )
        + "\n",
    )
    executor = tmp_path / "executor.py"
    _write_text(
        executor,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "print('four')",
            ]
        )
        + "\n",
    )
    executor.chmod(0o755)
    judge = tmp_path / "judge.py"
    _write_text(
        judge,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "payload = {",
                "    'passed': os.environ['BENCH_RESPONSE_TEXT'].strip().lower() == 'four',",
                "    'reason': os.environ['BENCH_JUDGE_PROMPT'][:80],",
                "}",
                "print(json.dumps(payload))",
            ]
        )
        + "\n",
    )
    judge.chmod(0o755)

    runtime_home = tmp_path / "runtime-home"
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        [
            "run",
            str(benchmark_dir),
            "-m",
            "demo-model",
            "--executor-command",
            str(executor),
        ],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0, stderr.getvalue()
    run_dir = next((runtime_home / "runs").iterdir())
    judged_rows = [
        json.loads(line)
        for line in (run_dir / "judged.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert judged_rows[0]["passed"] is True
    assert "semantic equivalence" in judged_rows[0]["judge_reason"].lower()


def test_shared_demo_executor_reads_fixture_rows_from_benchmark_dir(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "logic-mini"
    _write_text(
        benchmark_dir / "cases.jsonl",
        "\n".join(
            [
                json.dumps({"id": "p1", "prompt": "Dynamic prompt one"}),
                json.dumps({"id": "p2", "prompt": "Dynamic prompt two"}),
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "answers.jsonl",
        "\n".join(
            [
                json.dumps({"id": "p1", "answer": "alpha"}),
                json.dumps({"id": "p2", "answer": "beta"}),
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "responses.jsonl",
        "\n".join(
            [
                json.dumps({"id": "p1", "response": "alpha"}),
                json.dumps({"id": "p2", "response": "beta"}),
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "judge.yaml",
        "type: exact_match\nnormalize:\n  - strip\n  - lowercase\n",
    )

    runtime_home = tmp_path / "runtime-home"
    stdout = io.StringIO()
    stderr = io.StringIO()
    shared_executor = (
        Path(__file__).resolve().parents[1] / "examples" / "shared" / "demo_prompt_executor.py"
    )

    exit_code = main(
        [
            "run",
            str(benchmark_dir),
            "-m",
            "demo-model",
            "--executor-command",
            str(shared_executor),
        ],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0, stderr.getvalue()
    run_dir = next((runtime_home / "runs").iterdir())
    raw_rows = [
        json.loads(line)
        for line in (run_dir / "raw_responses.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["response_text"] for row in raw_rows] == ["alpha", "beta"]


def test_prompt_batch_executor_environment_is_task_neutral(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "logic-mini"
    _write_text(
        benchmark_dir / "cases.jsonl",
        json.dumps({"id": "p1", "prompt": "Answer plainly"}) + "\n",
    )
    _write_text(
        benchmark_dir / "answers.jsonl",
        json.dumps({"id": "p1", "answer": "plain"}) + "\n",
    )
    _write_text(
        benchmark_dir / "judge.yaml",
        "type: exact_match\nnormalize:\n  - strip\n  - lowercase\n",
    )
    executor = tmp_path / "inspect_executor.py"
    _write_text(
        executor,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "assert os.environ['MODEL_ID'] == 'demo-model'",
                "assert os.environ['CASE_ID'] == 'p1'",
                "assert os.environ['TASK_PROMPT_TEXT'] == 'Answer plainly'",
                "assert 'TASK_RESPONSE_FIXTURES_JSON' in os.environ",
                "assert all(not key.startswith('BENCH_') for key in os.environ)",
                "assert 'PYTEST_CURRENT_TEST' not in os.environ",
                "print('plain')",
            ]
        )
        + "\n",
    )
    executor.chmod(0o755)

    runtime_home = tmp_path / "runtime-home"
    exit_code = main(
        [
            "run",
            str(benchmark_dir),
            "-m",
            "demo-model",
            "--executor-command",
            str(executor),
        ],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0


def test_prompt_batch_collects_optional_executor_metrics_sidecar(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "logic-mini"
    _write_text(
        benchmark_dir / "cases.jsonl",
        "\n".join(
            [
                json.dumps({"id": "p1", "prompt": "First"}),
                json.dumps({"id": "p2", "prompt": "Second"}),
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "answers.jsonl",
        "\n".join(
            [
                json.dumps({"id": "p1", "answer": "ok"}),
                json.dumps({"id": "p2", "answer": "ok"}),
            ]
        )
        + "\n",
    )
    _write_text(
        benchmark_dir / "judge.yaml",
        "type: exact_match\nnormalize:\n  - strip\n  - lowercase\n",
    )
    executor = tmp_path / "metrics_executor.py"
    _write_text(
        executor,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "from pathlib import Path",
                "metrics = {",
                "    'cost_usd': 0.12 if os.environ['CASE_ID'] == 'p1' else 0.08,",
                "    'input_tokens': 11,",
                "    'output_tokens': 7,",
                "    'provider_latency_ms': 321,",
                "}",
                "Path(os.environ['TASK_METRICS_PATH']).write_text(json.dumps(metrics), encoding='utf-8')",
                "print('ok')",
            ]
        )
        + "\n",
    )
    executor.chmod(0o755)

    runtime_home = tmp_path / "runtime-home"
    exit_code = main(
        [
            "run",
            str(benchmark_dir),
            "-m",
            "demo-model",
            "--executor-command",
            str(executor),
        ],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    run_dir = next((runtime_home / "runs").iterdir())
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metrics"]["cost_usd"] == 0.2
    assert manifest["metrics"]["input_tokens"] == 22
    assert manifest["metrics"]["output_tokens"] == 14
    assert manifest["metrics"]["total_tokens"] == 36

    command_rows = [
        json.loads(line)
        for line in (run_dir / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(row["elapsed_ms"] >= 0 for row in command_rows)
    assert command_rows[0]["metrics"]["cost_usd"] == 0.12
    assert command_rows[1]["metrics"]["cost_usd"] == 0.08


def test_run_supports_models_file_via_at_syntax(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "logic-mini"
    _write_text(
        benchmark_dir / "cases.jsonl",
        json.dumps({"id": "p1", "prompt": "Say yes"}) + "\n",
    )
    _write_text(
        benchmark_dir / "answers.jsonl",
        json.dumps({"id": "p1", "answer": "yes"}) + "\n",
    )
    _write_text(
        benchmark_dir / "judge.yaml",
        "type: exact_match\nnormalize:\n  - strip\n  - lowercase\n",
    )
    executor = tmp_path / "echo_yes.py"
    _write_text(executor, "#!/usr/bin/env python3\nprint('yes')\n")
    executor.chmod(0o755)
    models_file = tmp_path / "models.txt"
    _write_text(
        models_file,
        "\n".join(
            [
                "# benchmark set",
                "demo-model-a",
                "",
                "demo-model-b",
            ]
        )
        + "\n",
    )

    runtime_home = tmp_path / "runtime-home"
    exit_code = main(
        [
            "run",
            str(benchmark_dir),
            "-m",
            f"@{models_file}",
            "--executor-command",
            str(executor),
        ],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    run_dirs = sorted((runtime_home / "runs").iterdir())
    assert len(run_dirs) == 2
    manifests = [
        json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        for run_dir in run_dirs
    ]
    assert [manifest["model"] for manifest in manifests] == ["demo-model-a", "demo-model-b"]


def test_run_supports_separate_models_file_option_and_inline_models(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "logic-mini"
    _write_text(
        benchmark_dir / "cases.jsonl",
        json.dumps({"id": "p1", "prompt": "Say yes"}) + "\n",
    )
    _write_text(
        benchmark_dir / "answers.jsonl",
        json.dumps({"id": "p1", "answer": "yes"}) + "\n",
    )
    _write_text(
        benchmark_dir / "judge.yaml",
        "type: exact_match\nnormalize:\n  - strip\n  - lowercase\n",
    )
    executor = tmp_path / "echo_yes.py"
    _write_text(executor, "#!/usr/bin/env python3\nprint('yes')\n")
    executor.chmod(0o755)
    models_file = tmp_path / "models.txt"
    _write_text(
        models_file,
        "\n".join(
            [
                "demo-model-a",
                "demo-model-b",
                "demo-model-a",
            ]
        )
        + "\n",
    )

    runtime_home = tmp_path / "runtime-home"
    exit_code = main(
        [
            "run",
            str(benchmark_dir),
            "--models-file",
            str(models_file),
            "-m",
            "demo-model-c,demo-model-b",
            "--executor-command",
            str(executor),
        ],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    run_dirs = sorted((runtime_home / "runs").iterdir())
    assert len(run_dirs) == 4
    manifests = [
        json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        for run_dir in run_dirs
    ]
    assert [manifest["model"] for manifest in manifests] == [
        "demo-model-a",
        "demo-model-b",
        "demo-model-c",
        "demo-model-b",
    ]
