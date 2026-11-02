import json
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path

import yaml


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_policy_engine_example_includes_adjudication_step_and_assets() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bench_yaml = yaml.safe_load(
        (repo_root / "examples" / "policy-engine" / "bench.yaml").read_text(encoding="utf-8")
    )
    steps = bench_yaml["steps"]
    step_names = [step["name"] if isinstance(step, dict) else step for step in steps]
    assert "validate" in step_names
    assert "mutation_probe" in step_names
    assert "adjudicate" in step_names
    assert bench_yaml["runs"] == 3
    assert bench_yaml["run_order"] == "breadth"
    assert bench_yaml["output_dir"] == "/Users/example/Documents/benchmark-llm"
    assert bench_yaml["execution_defaults"]["timeout_sec"] == 3600
    assert bench_yaml["execution_defaults"]["inactivity_timeout_sec"] == 900
    assert bench_yaml["execution_defaults"]["retries"]["max_attempts"] == 2

    assert (repo_root / "examples" / "policy-engine" / "scripts" / "adjudicate.sh").exists()
    assert (
        repo_root / "examples" / "policy-engine" / "scripts" / "render_final_summary_prompt.py"
    ).exists()
    assert (repo_root / "examples" / "policy-engine" / "hidden" / "data" / "benefits-hidden-c.yaml").exists()
    assert (
        repo_root
        / "examples"
        / "policy-engine"
        / "hidden"
        / "policies"
        / "professional-risk-only-extended.yaml"
    ).exists()
    assert (
        repo_root / "examples" / "policy-engine" / "visible" / "data" / "benefits-sample-a.json"
    ).exists()
    assert (repo_root / "examples" / "policy-engine" / "visible" / ".gitignore").exists()
    assert "visible/.gitignore" in bench_yaml["visibility"]["expose"]


def test_policy_engine_final_summary_prompt_renderer_groups_models_and_includes_benchmark_overview(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        repo_root / "examples" / "policy-engine" / "scripts" / "render_final_summary_prompt.py"
    )

    output_root = tmp_path / "results"
    run_one = output_root / "run-one"
    run_two = output_root / "run-two"
    run_one.mkdir(parents=True)
    run_two.mkdir(parents=True)
    (run_one / "report.md").write_text(
        "# Evaluation Sheet\n\n| Field | Value |\n| --- | --- |\n| Model | model-a |\n| Final score | 91/100 |\n\n## Findings\n\n- Strong visible coverage\n",
        encoding="utf-8",
    )
    (run_two / "report.md").write_text(
        "# Evaluation Sheet\n\n| Field | Value |\n| --- | --- |\n| Model | model-a |\n| Final score | 84/100 |\n\n## Findings\n\n- Hidden robustness was mixed\n",
        encoding="utf-8",
    )
    (output_root / "summary_runs.json").write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "run_id": "run-one",
                        "model": "model-a",
                        "status": "succeeded",
                        "report_path": str(run_one / "report.md"),
                        "score_percent": 91.0,
                        "attempts": [{"attempt": 1, "status": "succeeded"}],
                    },
                    {
                        "run_id": "run-two",
                        "model": "model-a",
                        "status": "succeeded",
                        "report_path": str(run_two / "report.md"),
                        "score_percent": 84.0,
                        "attempts": [{"attempt": 1, "status": "succeeded"}],
                    },
                    {
                        "run_id": "run-three",
                        "model": "model-b",
                        "status": "failed",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "retryable_failure",
                                "retry_reason": "inactivity_timeout",
                            },
                            {
                                "attempt": 2,
                                "status": "failed",
                                "retry_reason": "inactivity_timeout",
                            },
                        ],
                        "failure_summary": {
                            "retry_reasons": ["inactivity_timeout", "inactivity_timeout"],
                            "errors": ["Step failed: ./scripts/invoke_model.sh"],
                        },
                    },
                ],
                "settings": {"runs": 3, "run_order": "breadth"},
            }
        ),
        encoding="utf-8",
    )

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        assert module.main(
            [
                str(repo_root / "examples" / "policy-engine"),
                str(output_root / "summary_runs.json"),
            ]
        ) == 0

    prompt_text = stdout.getvalue()
    assert "## Executive Summary" in prompt_text
    assert "## Benchmark Run Overview" in prompt_text
    assert "## Synthesized Narrative" in prompt_text
    assert "## Model Commentary" in prompt_text
    assert "## Topline Results" in prompt_text
    assert "summarize each model across all of its runs" in prompt_text.lower()
    assert "do not imply that a model improved over time" in prompt_text.lower()
    assert "completion rates, retries, failure modes" in prompt_text.lower()
    assert "supporting quotes or evidence" in prompt_text.lower()
    assert "topline results table belongs at the end" in prompt_text.lower()
    assert "configured runs per model" in prompt_text.lower()
    assert "retry reason counts" in prompt_text.lower()
    assert "Model: model-a" in prompt_text
    assert '"successful_runs": 2' in prompt_text
    assert "Model: model-b" in prompt_text
    assert '"failed_runs": 1' in prompt_text
    assert "model-a" in prompt_text
    assert "model-b" in prompt_text
    assert "Strong visible coverage" in prompt_text
    assert "Hidden robustness was mixed" in prompt_text
    assert "inactivity_timeout" in prompt_text


def test_policy_engine_eval_helpers_compare_rows_and_render_template() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        repo_root / "examples" / "policy-engine" / "scripts" / "eval_helpers.py"
    )

    payload = {
        "results": [
            {
                "original_service_category": "PCP Visit",
                "canonical_service_category": "Primary Care Visit",
                "risk_holder": "professional",
                "system_configuration_action": "PAY",
                "match_status": "matched",
            }
        ]
    }
    rows = module.extract_output_rows(payload)
    assert len(rows) == 1

    expected_rows = [
        {
            "original_service_category": "PCP Visit",
            "canonical_service_category": "Primary Care Visit",
            "risk_holder": "professional",
            "system_configuration_action": "PAY",
            "match_status": "matched",
        }
    ]
    comparison = module.compare_expected_rows(rows, expected_rows)
    assert comparison["passed"] is True

    rendered = module.render_template(
        "Model: {{ model }}\nScore: {{ final_score }}\n",
        {"model": "GLM-5.1", "final_score": "92/100"},
    )
    assert "GLM-5.1" in rendered
    assert "92/100" in rendered


def test_policy_engine_harness_metrics_extracts_opencode_and_codex_shapes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        repo_root / "examples" / "policy-engine" / "scripts" / "harness_metrics.py"
    )

    opencode_events = tmp_path / "opencode-events.jsonl"
    opencode_events.write_text(
        "\n".join(
            [
                json.dumps({"type": "step_start", "sessionID": "ses_abc123XYZ"}),
                json.dumps(
                    {
                        "type": "step_finish",
                        "sessionID": "ses_abc123XYZ",
                        "part": {
                            "type": "step-finish",
                            "tokens": {"total": 24533, "input": 24512, "output": 7, "reasoning": 14},
                            "cost": 0.00800735,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    opencode_export = tmp_path / "opencode-export.json"
    opencode_export.write_text(
        json.dumps(
            {
                "info": {
                    "id": "ses_abc123XYZ",
                    "time": {"created": 1775927614760, "completed": 1775927615509},
                },
                "messages": [
                    {
                        "info": {
                            "cost": 0.42,
                            "tokens": {"input": 100, "output": 20, "total": 120},
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert module.extract_opencode_session_id(module._read_jsonl(opencode_events)) == "ses_abc123XYZ"
    event_metrics = module.extract_metrics_from_payload(module._read_jsonl(opencode_events))
    assert event_metrics["cost_usd"] == 0.008007
    assert event_metrics["input_tokens"] == 24512
    assert event_metrics["output_tokens"] == 7
    assert event_metrics["total_tokens"] == 24533

    metrics = module.extract_metrics_from_payload(module._read_json(opencode_export))
    assert metrics["cost_usd"] == 0.42
    assert metrics["provider_latency_ms"] == 749
    assert metrics["total_tokens"] == 120

    codex_events = tmp_path / "codex-events.jsonl"
    codex_events.write_text(
        "\n".join(
            [
                json.dumps({"type": "turn.completed", "usage": {"prompt_tokens": 210, "completion_tokens": 45}}),
                json.dumps({"type": "response.completed", "total_cost_usd": 0.031}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    codex_metrics = module.extract_metrics_from_payload(module._read_jsonl(codex_events))
    assert codex_metrics["input_tokens"] == 210
    assert codex_metrics["output_tokens"] == 45
    assert codex_metrics["total_tokens"] == 255
    assert codex_metrics["cost_usd"] == 0.031


def test_policy_engine_prompt_exposes_required_contract_without_eval_signaling() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompt_text = (repo_root / "examples" / "policy-engine" / "prompt.txt").read_text(
        encoding="utf-8"
    )

    for required in [
        "Build the full project in the current directory.",
        "Handle blank or missing values safely when reasonable",
        "blank or missing service_category and null coverage_status should not crash the program",
        "python policy_engine.py --policy <path> --benefits <path> [--output <path>]",
        "Straightforward defensive handling is desirable and in scope",
        "Do not hardcode the visible sample outputs",
        "Include a small but meaningful automated verification suite",
    ]:
        assert required in prompt_text

    prompt_lower = prompt_text.lower()
    for forbidden in ["benchmark", "evaluation", "adjudication", "evaluator", "test", "tests"]:
        assert forbidden not in prompt_lower


def test_policy_engine_findings_sidecar_supports_jsonl_append_and_load(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        repo_root / "examples" / "policy-engine" / "scripts" / "findings_io.py"
    )

    findings_path = tmp_path / "benchmark_findings.jsonl"
    first = {"phase": "validate", "summary": "validator summary"}
    second = {"phase": "mutation_probe", "summary": "mutation summary"}

    module.append_finding(findings_path, first)
    module.append_finding(findings_path, second)

    assert module.load_findings(findings_path) == [first, second]


def test_policy_engine_mutation_probe_prefers_source_file_over_entrypoint_and_tests(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        repo_root / "examples" / "policy-engine" / "scripts" / "run_mutation_check.py"
    )

    workspace = tmp_path / "workspace"
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True)

    (workspace / "policy_engine.py").write_text("print('entrypoint only')\n", encoding="utf-8")
    (workspace / "matcher.py").write_text(
        'MATCH_STATUS = "unmatched"\n',
        encoding="utf-8",
    )
    (tests_dir / "test_policy_engine.py").write_text(
        'assert "unmatched" == "unmatched"\n',
        encoding="utf-8",
    )

    assert module.find_mutation_target(workspace) == workspace / "matcher.py"


def test_policy_engine_render_adjudication_prompt_includes_benchmark_findings(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        repo_root / "examples" / "policy-engine" / "scripts" / "render_adjudication_prompt.py"
    )

    benchmark_dir = tmp_path / "benchmark"
    hidden_dir = benchmark_dir / "hidden"
    hidden_dir.mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    (hidden_dir / "adjudicator_prompt.md").write_text("Prompt header", encoding="utf-8")
    (benchmark_dir / "report_template.md").write_text("Report body", encoding="utf-8")
    (hidden_dir / "rubric.yaml").write_text("provider: OpenRouter\n", encoding="utf-8")
    (run_dir / "validation_summary.json").write_text(json.dumps({"visible": []}), encoding="utf-8")
    (run_dir / "benchmark_findings.jsonl").write_text(
        json.dumps({"phase": "mutation_probe", "summary": "Mutation caught"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "commands.jsonl").write_text(
        json.dumps({"phase": "validate", "exit_code": 0}) + "\n",
        encoding="utf-8",
    )

    stdout = io.StringIO()
    monkeypatch.setattr(
        "sys.argv",
        [
            "render_adjudication_prompt.py",
            str(benchmark_dir),
            str(run_dir),
            "openrouter/z-ai/glm-5.1",
        ],
    )
    with redirect_stdout(stdout):
        assert module.main() == 0

    prompt = stdout.getvalue()
    assert "Benchmark findings JSONL:" in prompt
    assert "Mutation caught" in prompt


def test_policy_engine_render_report_handles_short_findings_lists(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo_root / "examples" / "policy-engine" / "scripts"))
    module = _load_module(repo_root / "examples" / "policy-engine" / "scripts" / "render_report.py")

    template_path = tmp_path / "report_template.md"
    template_path.write_text(
        "\n".join(
            [
                "- {{ finding_1 }}",
                "- {{ finding_2 }}",
                "- {{ finding_3 }}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    for findings, expected_lines in [
        (["Only one finding"], ["- Only one finding", "- ", "- "]),
        (["First finding", "Second finding"], ["- First finding", "- Second finding", "- "]),
    ]:
        run_dir = tmp_path / f"run-{len(findings)}"
        run_dir.mkdir()
        (run_dir / "adjudication.json").write_text(
            json.dumps(
                {
                    "score_percent": 91.0,
                    "findings": findings,
                    "score_breakdown": {},
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            "sys.argv",
            [
                "render_report.py",
                str(run_dir),
                str(template_path),
            ],
        )
        assert module.main() == 0

        report_lines = (run_dir / "report.md").read_text(encoding="utf-8").splitlines()
        assert report_lines == expected_lines
        score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
        assert score["summary"]["score_percent"] == 91.0


def test_policy_engine_model_visible_assets_do_not_signal_evaluation_context() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompt_text = (repo_root / "examples" / "policy-engine" / "prompt.txt").read_text(
        encoding="utf-8"
    )
    visible_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repo_root / "examples" / "policy-engine" / "visible").rglob("*"))
        if path.is_file()
    )
    combined = f"{prompt_text}\n{visible_text}".lower()

    for forbidden in [
        "benchmark",
        "evaluation",
        "adjudication",
        "evaluator",
        "hidden asset",
        "hidden assets",
        "test",
        "tests",
    ]:
        assert forbidden not in combined
