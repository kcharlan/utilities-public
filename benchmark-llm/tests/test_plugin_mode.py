import io
import json
from pathlib import Path

from benchmark_llm.cli import main
from benchmark_llm.discovery import detect_benchmark_mode
from benchmark_llm.storage import list_runs


def test_plugin_judge_without_summary_fails_without_index_row(tmp_path: Path) -> None:
    (tmp_path / "bench.py").write_text(
        "from benchsdk import BenchmarkPlugin\nclass ExamplePlugin(BenchmarkPlugin):\n"
        "    def execute(self, ctx, model):\n        pass\n"
        "    def judge(self, ctx):\n        return {'checks': []}\n", encoding="utf-8")
    runtime_home = tmp_path / "runtime-home"
    stderr = io.StringIO()
    code = main(["run", str(tmp_path), "-m", "demo-model"],
                environ={"BENCH_RUNTIME_HOME": str(runtime_home)}, stdout=io.StringIO(), stderr=stderr)
    assert code == 1
    assert "summary.score_percent" in stderr.getvalue()
    assert list_runs(runtime_home) == []
    run_dir = next((runtime_home / "runs").iterdir())
    failure = json.loads((run_dir / "failure.json").read_text())
    assert failure["run_id"] == run_dir.name
    assert failure["model"] == "demo-model"
    assert failure["phase"] == "plugin_judge"
    assert "summary.score_percent" in failure["error"]
    assert not (run_dir / "score.json").exists()
    commands = [json.loads(line) for line in (run_dir / "commands.jsonl").read_text().splitlines()]
    assert [row["phase"] for row in commands] == ["plugin_prepare", "plugin_execute", "plugin_judge"]


def test_plugin_mode_is_detected_from_bench_python_file(tmp_path: Path) -> None:
    (tmp_path / "bench.py").write_text("class Placeholder:\n    pass\n", encoding="utf-8")
    assert detect_benchmark_mode(tmp_path) == "plugin"


def test_plugin_benchmark_runs_and_writes_score(tmp_path: Path) -> None:
    (tmp_path / "bench.py").write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "from benchsdk import BenchmarkPlugin",
                "",
                "class ExamplePlugin(BenchmarkPlugin):",
                "    benchmark_id = 'plugin-mini'",
                "",
                "    def prepare(self, ctx):",
                "        (ctx.run_dir / 'prepared.txt').write_text('ready\\n', encoding='utf-8')",
                "",
                "    def execute(self, ctx, model):",
                "        (ctx.run_dir / 'execution.txt').write_text(f'{model}\\n', encoding='utf-8')",
                "",
                "    def judge(self, ctx):",
                "        return {",
                "            'summary': {'passed': 1, 'total': 1, 'score_percent': 100.0},",
                "            'checks': [{'name': 'plugin ran', 'passed': True}],",
                "        }",
                "",
                "    def summarize(self, ctx, score):",
                "        return {'note': 'plugin example'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    runtime_home = tmp_path / "runtime-home"
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = main(
        ["run", str(tmp_path), "-m", "demo-model"],
        environ={"BENCH_RUNTIME_HOME": str(runtime_home)},
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0, stderr.getvalue()
    run_dir = next((runtime_home / "runs").iterdir())
    assert "plugin-mini" in run_dir.name
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["timing"]["elapsed_ms"] >= 0
    command_rows = [
        json.loads(line)
        for line in (run_dir / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["phase"] for row in command_rows] == [
        "plugin_prepare",
        "plugin_execute",
        "plugin_judge",
        "plugin_summarize",
    ]
    assert all(row["elapsed_ms"] >= 0 for row in command_rows)
    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    assert score["summary"]["score_percent"] == 100.0
