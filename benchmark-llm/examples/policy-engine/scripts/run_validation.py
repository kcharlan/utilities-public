from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from eval_helpers import compare_expected_rows, extract_output_rows, load_json_or_yaml


def run_command(command: list[str], cwd: Path) -> dict:
    started = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    ended = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "started_at": started,
        "ended_at": ended,
    }


def evaluate_output(label: str, output_path: Path, expected_rows: list[dict]) -> dict:
    if not output_path.exists():
        return {"label": label, "passed": False, "failures": [f"Missing output file {output_path}"]}
    payload = load_json_or_yaml(output_path)
    rows = extract_output_rows(payload)
    comparison = compare_expected_rows(rows, expected_rows)
    return {"label": label, **comparison}


def main() -> int:
    run_dir = Path(sys.argv[1])
    workspace = Path(sys.argv[2])
    hidden_dir = Path(sys.argv[3])

    expectations = yaml.safe_load((hidden_dir / "expected_outcomes.yaml").read_text(encoding="utf-8"))

    command_log: list[dict] = []

    command_log.append(run_command(["pytest", "-q"], workspace))
    command_log.append(run_command([sys.executable, "-m", "pytest", "-q"], workspace))

    visible_commands = [
        (
            "sample_a",
            [
                sys.executable,
                "policy_engine.py",
                "--policy",
                "policies/professional-risk-only.yaml",
                "--benefits",
                "data/benefits-sample-a.json",
                "--output",
                "output/sample-a.json",
            ],
        ),
        (
            "sample_b",
            [
                sys.executable,
                "policy_engine.py",
                "--policy",
                "policies/professional-risk-only.yaml",
                "--benefits",
                "data/benefits-sample-b.yaml",
                "--output",
                "output/sample-b.json",
            ],
        ),
    ]

    visible_results = []
    for label, command in visible_commands:
        command_log.append(run_command(command, workspace))
        visible_results.append(
            evaluate_output(
                label,
                workspace / expectations["visible"][label]["output_path"],
                expectations["visible"][label]["rows"],
            )
        )

    hidden_commands = [
        (
            "hidden_c",
            [
                sys.executable,
                "policy_engine.py",
                "--policy",
                str(hidden_dir / "policies" / "professional-risk-only-extended.yaml"),
                "--benefits",
                str(hidden_dir / "data" / "benefits-hidden-c.yaml"),
                "--output",
                "output/hidden-c.json",
            ],
        ),
        (
            "hidden_d",
            [
                sys.executable,
                "policy_engine.py",
                "--policy",
                str(hidden_dir / "policies" / "professional-risk-only-extended.yaml"),
                "--benefits",
                str(hidden_dir / "data" / "benefits-hidden-d.json"),
                "--output",
                "output/hidden-d.json",
            ],
        ),
    ]

    hidden_results = []
    for label, command in hidden_commands:
        command_log.append(run_command(command, workspace))
        hidden_results.append(
            evaluate_output(
                label,
                workspace / expectations["hidden"][label]["output_path"],
                expectations["hidden"][label]["rows"],
            )
        )

    summary = {
        "commands": command_log,
        "tests": {
            "pytest_q": command_log[0],
            "python_m_pytest_q": command_log[1],
        },
        "visible": visible_results,
        "hidden": hidden_results,
    }
    (run_dir / "validation_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
