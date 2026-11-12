import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
from tools.testkit import assert_launcher_help, run_launcher  # noqa: E402

LAUNCHER = PROJECT / "model_ladder"


def test_help_has_no_side_effects(tmp_path):
    result = assert_launcher_help(LAUNCHER)
    assert "available Artificial Analysis indexes" in " ".join(result.stdout.split())
    assert not (tmp_path / "ml-home").exists()


def test_version_prints_and_creates_nothing(tmp_path):
    result = run_launcher(LAUNCHER, "--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Model Ladder 1.1.3"
    assert not (tmp_path / "ml-home").exists()
