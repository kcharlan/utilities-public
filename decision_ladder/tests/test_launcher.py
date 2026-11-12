from pathlib import Path
from tools.testkit import assert_launcher_help, run_launcher

LAUNCHER = Path(__file__).resolve().parents[1] / "decision_ladder"


def test_help_and_version_create_nothing(tmp_path):
    assert "decision_ladder" in assert_launcher_help(LAUNCHER).stdout
    result = run_launcher(LAUNCHER, "--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "Decision Ladder 1.2.1"
    assert not (tmp_path / "decision-home").exists()
