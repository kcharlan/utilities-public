import importlib.util
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cron_eval_example_manifest_and_assets() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    benchmark_dir = repo_root / "examples" / "cron-eval"
    bench_yaml = yaml.safe_load((benchmark_dir / "bench.yaml").read_text(encoding="utf-8"))

    assert bench_yaml["type"] == "repo_task"
    assert bench_yaml["id"] == "cron-eval"
    assert bench_yaml["runs"] == 3
    assert bench_yaml["run_order"] == "breadth"
    assert bench_yaml["output_dir"] == "${BENCH_CRON_EVAL_OUTPUT_DIR:-~/Documents/benchmark-llm/cron-eval}"
    assert bench_yaml["workspace"]["source_repo"] == "${BENCH_CRON_EVAL_SOURCE_REPO}"
    assert bench_yaml["executor"]["command"] == "./scripts/invoke_model.sh"
    assert [step["name"] for step in bench_yaml["steps"]] == [
        "prepare",
        "execute",
        "validate",
        "adjudicate",
    ]

    for relative in [
        "prompt.txt",
        "README.md",
        "report_template.md",
        "models-openrouter.txt",
        "visible/spec.md",
        "visible/examples.md",
        "visible/starter_test.py",
        "visible/.gitignore",
        "hidden/reference_impl.py",
        "hidden/rubric.yaml",
        "hidden/adjudicator_prompt.md",
        "scripts/prepare.sh",
        "scripts/invoke_model.sh",
        "scripts/run_checks.py",
        "scripts/run_checks.sh",
        "scripts/adjudicate.sh",
        "scripts/render_adjudication_prompt.py",
        "scripts/render_report.py",
        "scripts/render_final_summary_prompt.py",
        "scripts/findings_io.py",
        "scripts/harness_metrics.py",
    ]:
        assert (benchmark_dir / relative).exists(), relative


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
    assert summary["total_cases"] == 100
    assert summary["failed_cases"] == []


def test_cron_eval_adjudication_prompt_is_explanatory_not_scoring() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompt_text = (
        repo_root / "examples" / "cron-eval" / "hidden" / "adjudicator_prompt.md"
    ).read_text(encoding="utf-8")
    script_text = (
        repo_root / "examples" / "cron-eval" / "scripts" / "adjudicate.sh"
    ).read_text(encoding="utf-8")

    assert "The score is fixed" in prompt_text
    assert "You may not change it" in prompt_text
    assert "Your only job is to explain what failed and why" in prompt_text
    assert 'ADJUDICATOR_BIN="${BENCH_CRON_EVAL_ADJUDICATOR_BIN:-cx}"' in script_text
    assert "BENCH_CRON_EVAL_ADJUDICATOR_MODEL" in script_text
    assert "BENCH_CRON_EVAL_ADJUDICATOR_ARGS" in script_text
    assert 'zsh -lic "$ADJUDICATOR_COMMAND_STRING" < "$PROMPT_PATH"' in script_text


def test_cron_eval_run_checks_wrapper_uses_repo_task_environment() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_text = (
        repo_root / "examples" / "cron-eval" / "scripts" / "run_checks.sh"
    ).read_text(encoding="utf-8")

    assert '"$BENCH_RUN_DIR"' in script_text
    assert '"$BENCH_WORKSPACE"' in script_text
    assert '"$BENCH_HIDDEN_DIR"' in script_text
    assert '"$@"' not in script_text
