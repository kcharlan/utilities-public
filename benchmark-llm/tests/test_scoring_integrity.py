from benchmark_llm.execution import run_command
from benchmark_llm.repo_task import _looks_like_retryable_llm_failure
from benchmark_llm.util import build_model_command_env


def test_successful_rate_limit_text_is_not_a_provider_failure():
    assert _looks_like_retryable_llm_failure({"exit_code": 0, "stdout": "rate limit"}) == (False, None)


def test_malformed_command_output_is_preserved_with_replacement(tmp_path):
    result = run_command("printf '\\377'", tmp_path, {}, "execute")
    assert result["stdout"] == "\ufffd"


def test_model_environment_excludes_unrelated_tokens_and_ssh_socket():
    env = build_model_command_env({"UNRELATED_TOKEN": "secret", "SSH_AUTH_SOCK": "/tmp/socket", "OPENAI_API_KEY": "model-key"}, {})
    assert "UNRELATED_TOKEN" not in env
    assert "SSH_AUTH_SOCK" not in env
    assert env["OPENAI_API_KEY"] == "model-key"


def test_hidden_files_are_staged_only_after_executor(tmp_path):
    import shlex
    import subprocess
    from benchmark_llm.execution import PROCESS_IDENTITY_ROOT
    from benchmark_llm.repo_task import run_repo_task
    from benchmark_llm.storage import ensure_runtime_layout

    source = tmp_path / "source"
    source.mkdir()
    def git(*args):
        subprocess.run(["git", "-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid", *args], cwd=source, check=True, capture_output=True)
    git("init")
    (source / "seed").write_text("seed")
    git("add", "seed")
    git("commit", "-m", "seed")
    bench = tmp_path / "benchmark"
    (bench / "hidden").mkdir(parents=True)
    (bench / "hidden" / "expected").write_text("synthetic")
    model = "test -z \"${BENCH_PROCESS_IDENTITY_ROOT+x}\" && test ! -e \"$(dirname \"$(dirname \"$TASK_METRICS_PATH\")\")/hidden/expected\" && echo done > \"$WORKSPACE_ROOT/result\""
    judge = f"test \"$BENCH_PROCESS_IDENTITY_ROOT\" = {shlex.quote(str(PROCESS_IDENTITY_ROOT))} && " + "test -f \"$BENCH_HIDDEN_DIR/expected\" && printf '%s' '{\"summary\":{\"score_percent\":100},\"checks\":[]}' > \"$BENCH_RUN_DIR/score.json\""
    config = {"id": "synthetic", "output_dir": str(tmp_path / "results"), "workspace": {"kind": "git_worktree", "source_repo": str(source)}, "visibility": {"hide": ["hidden/**"]}, "executor": {"command": model}, "steps": [{"name": "execute", "use_executor": True}, {"name": "judge", "run": judge}]}
    ensure_runtime_layout(tmp_path / "runtime")
    run_dir = run_repo_task(bench, tmp_path / "runtime", "fake", {"BENCH_PROCESS_IDENTITY_ROOT": "synthetic-untrusted"}, config=config)
    assert (run_dir / "score.json").exists()


def test_cron_evaluator_does_not_import_submitted_module_into_scorer(tmp_path):
    import importlib.util
    import json
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "examples/cron-eval/scripts/run_checks.py"
    spec = importlib.util.spec_from_file_location("synthetic_validator", script)
    validator = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = validator
    try:
        spec.loader.exec_module(validator)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "cron_eval.py").write_text("import sys\nif 'synthetic_validator' in sys.modules:\n sys.modules['synthetic_validator'].CATEGORY_MAX['field_validity_basic'] = 999\nclass InvalidCronExpr(Exception): pass\n")
        hidden = tmp_path / "hidden"
        (hidden / "conformance").mkdir(parents=True)
        run_dir = tmp_path / "run"
        validator.main([str(run_dir), str(workspace), str(hidden)])
        score = json.loads((run_dir / "score.json").read_text())
        assert score["import_ok"] is True
        assert score["category_breakdown"]["field_validity_basic"]["max"] == 20
    finally:
        del sys.modules[spec.name]


def test_cron_child_does_not_inherit_scoring_environment(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "examples/cron-eval/scripts/run_checks.py"
    spec = importlib.util.spec_from_file_location("synthetic_validator_env", script)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "cron_eval.py").write_text("import os\nclass InvalidCronExpr(Exception): pass\ndef next_fires(**kwargs):\n if 'PRIVATE_TOKEN' in os.environ: raise InvalidCronExpr()\n return []\n")
    monkeypatch.setenv("PRIVATE_TOKEN", "synthetic")
    result = validator._run_model(workspace, [{"after": "2026-01-01T00:00:00+00:00"}])
    assert result["results"] == [{"kind": "fires", "value": []}]


def test_cron_validator_requires_identity_helper(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    import pytest

    script = Path(__file__).resolve().parents[1] / "examples/cron-eval/scripts/run_checks.py"
    spec = importlib.util.spec_from_file_location("synthetic_validator_missing_helper", script)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    for value in (None, "relative/path", str(tmp_path / "missing")):
        if value is None:
            monkeypatch.delenv("BENCH_PROCESS_IDENTITY_ROOT", raising=False)
        else:
            monkeypatch.setenv("BENCH_PROCESS_IDENTITY_ROOT", value)
        with pytest.raises(RuntimeError, match="BENCH_PROCESS_IDENTITY_ROOT"):
            validator._run_model(tmp_path, [])
