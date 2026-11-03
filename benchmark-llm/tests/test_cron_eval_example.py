import importlib.util
import io
import json
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from benchmark_llm.cli import main
from benchmark_llm.storage import list_runs


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cron_eval_conformance_suite_has_expected_shape_and_weights() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    conformance_dir = repo_root / "examples" / "cron-eval" / "hidden" / "conformance"
    fixtures = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(conformance_dir.glob("*.json"))]

    assert len(fixtures) == 100
    expected_totals = {
        "field_validity_basic": (20, 20.0),
        "step_alignment": (10, 15.0),
        "lists_and_ranges": (8, 10.0),
        "dom_dow_interaction": (10, 15.0),
        "l_and_w": (7, 10.0),
        "calendar_edges": (12, 15.0),
        "timezone_dst": (8, 10.0),
        "errors": (25, 5.0),
    }
    for category, (expected_count, expected_weight) in expected_totals.items():
        category_fixtures = [fixture for fixture in fixtures if fixture["category"] == category]
        assert len(category_fixtures) == expected_count, category
        assert round(sum(float(fixture["weight"]) for fixture in category_fixtures), 6) == expected_weight

    assert round(sum(float(fixture["weight"]) for fixture in fixtures), 6) == 100.0
    for fixture in fixtures:
        assert set(fixture) == {"id", "category", "weight", "input", "expected"}
        assert set(fixture["input"]) == {"expr", "after", "n", "tz"}
        assert set(fixture["expected"]) == {"kind", "value"}


def test_cron_eval_reference_impl_self_check_and_known_edges() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    reference = _load_module(repo_root / "examples" / "cron-eval" / "hidden" / "reference_impl.py")

    assert reference.self_check(repo_root / "examples" / "cron-eval" / "hidden" / "conformance") == 0
    assert reference.next_fires(
        "0 0 29 2 *",
        datetime(2025, 1, 1, tzinfo=ZoneInfo("UTC")),
        n=3,
        tz="UTC",
    ) == [
        datetime(2028, 2, 29, tzinfo=ZoneInfo("UTC")),
        datetime(2032, 2, 29, tzinfo=ZoneInfo("UTC")),
        datetime(2036, 2, 29, tzinfo=ZoneInfo("UTC")),
    ]


def test_cron_eval_validator_scores_reference_impl_at_100(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    benchmark_dir = repo_root / "examples" / "cron-eval"
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()
    shutil.copyfile(benchmark_dir / "hidden" / "reference_impl.py", workspace / "cron_eval.py")

    validator = _load_module(benchmark_dir / "scripts" / "run_checks.py")
    assert validator.main([str(run_dir), str(workspace), str(benchmark_dir / "hidden")]) == 0

    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "validation_summary.json").read_text(encoding="utf-8"))
    assert score["score"] == 100
    assert score["max_score"] == 100
    assert score["import_ok"] is True
    assert score["summary"] == {"passed": 100, "total": 100, "score_percent": 100.0}
    assert summary["total_cases"] == 100
    assert summary["failed_cases"] == []


def test_cron_eval_validator_zero_score_has_runtime_summary(tmp_path: Path) -> None:
    benchmark_dir = Path(__file__).resolve().parents[1] / "examples" / "cron-eval"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_dir = tmp_path / "run"
    validator = _load_module(benchmark_dir / "scripts" / "run_checks.py")

    assert validator.main([str(run_dir), str(workspace), str(benchmark_dir / "hidden")]) == 0
    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    assert score["summary"] == {"passed": 0, "total": 0, "score_percent": 0.0}
    assert score["import_ok"] is False


def test_cron_eval_reference_impl_completes_bench_run_at_100(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / "cron-eval"
    benchmark = tmp_path / "cron-eval"
    shutil.copytree(example, benchmark, ignore=shutil.ignore_patterns("__pycache__"))
    source_repo = tmp_path / "synthetic-repo"
    source_repo.mkdir()
    for args in (["init", "-b", "main"], ["commit", "--allow-empty", "-m", "Synthetic initial commit"]):
        subprocess.run(
            ["git", "-c", "user.name=Benchmark Tests", "-c", "user.email=synthetic-user@example.invalid", *args],
            cwd=source_repo, check=True, capture_output=True, text=True,
        )
    manifest_path = benchmark / "bench.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["runs"] = 1
    manifest["output_dir"] = str(tmp_path / "results")
    manifest["workspace"]["source_repo"] = str(source_repo)
    manifest["workspace"]["commit_outputs"] = False
    reference = shlex.quote(str(benchmark / "hidden" / "reference_impl.py"))
    # The model step must see the task spec and the ignore file that keeps its
    # venv out of committed outputs before it writes the submission.
    manifest["executor"]["command"] = (
        'for name in prompt.txt spec.md examples.md starter_test.py .gitignore; do '
        'test -f "$WORKSPACE_ROOT/$name" || { echo "missing model-visible $name" >&2; exit 1; }; done; '
        'grep -Fqx ".venv/" "$WORKSPACE_ROOT/.gitignore" || { echo ".gitignore lacks .venv/" >&2; exit 1; }; '
        f'cp {reference} "$WORKSPACE_ROOT/cron_eval.py"'
    )
    manifest["steps"] = [step for step in manifest["steps"] if step["name"] != "adjudicate"]
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    runtime_home = tmp_path / "runtime"
    stdout, stderr = io.StringIO(), io.StringIO()

    result = main(["run", str(benchmark), "-m", "synthetic-model"],
                  environ={"BENCH_RUNTIME_HOME": str(runtime_home)}, stdout=stdout, stderr=stderr)

    assert result == 0, stderr.getvalue()
    runs = list_runs(runtime_home)
    assert len(runs) == 1
    assert runs[0]["score_percent"] == 100.0
    assert len(list((tmp_path / "results").glob("*/manifest.json"))) == 1
