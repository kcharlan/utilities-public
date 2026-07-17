from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

UTILITIES_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(UTILITIES_ROOT))

from tools.testkit import run_launcher


def _write_non_executable_builtin_pack(root: Path) -> None:
    scripts_dir = root / "claude-code" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (root / "claude-code" / "pack.yaml").write_text(
        dedent(
            """
            name: claude-code
            description: Failing built-in pack fixture.
            version: 1.2.3

            phases:
              resolution:
                enabled: true
                executor: passthrough
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 1

            timeouts:
              task_idle: 5
              task_max: 0
              session_max: 60

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path = scripts_dir / "execute"
    execute_path.write_text("#!/usr/bin/env python3\nprint('fail preflight')\n", encoding="utf-8")
    execute_path.chmod(0o644)


def _write_intake_plan(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dedent(
            """
            ---
            PLAN_ID: 001
            PRIORITY: normal
            ESTIMATED_SCOPE: src/001.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task 001
            """
        ).lstrip(),
        encoding="utf-8",
    )


def test_switchyard_help_succeeds(repo_root: Path) -> None:
    result = run_launcher(repo_root / "switchyard", "--help", cwd=repo_root)

    assert result.returncode == 0
    assert "cognitive_switchyard" in result.stdout
    assert "~/.cognitive_switchyard" in result.stdout
    assert "Traceback" not in result.stderr


def test_paths_reports_default_without_creating_state(repo_root: Path, tmp_path: Path) -> None:
    result = run_launcher(
        repo_root / "switchyard",
        "paths",
        cwd=repo_root,
        env_overrides={"HOME": str(tmp_path)},
    )

    assert result.returncode == 0
    assert "runtime home: ~/.cognitive_switchyard" in result.stdout
    assert not (tmp_path / ".cognitive_switchyard").exists()


def test_paths_reports_override_without_creating_state(repo_root: Path, tmp_path: Path) -> None:
    runtime_root = tmp_path / "sandbox"

    result = run_launcher(
        repo_root / "switchyard",
        "--runtime-root",
        str(runtime_root),
        "paths",
        cwd=repo_root,
    )

    assert result.returncode == 0
    assert f"runtime home: {runtime_root / '.cognitive_switchyard'}" in result.stdout
    assert not runtime_root.exists()


def test_switchyard_propagates_nonzero_exit_codes_from_start_failures(
    repo_root: Path, tmp_path: Path
) -> None:
    builtin_root = tmp_path / "builtin"
    runtime_root = tmp_path / "runtime"
    _write_non_executable_builtin_pack(builtin_root)
    _write_intake_plan(
        runtime_root / ".cognitive_switchyard" / "sessions" / "demo" / "intake" / "001.plan.md"
    )

    result = run_launcher(
        repo_root / "switchyard",
        "--runtime-root",
        str(runtime_root),
        "--builtin-packs-root",
        str(builtin_root),
        "start",
        "--pack",
        "claude-code",
        "--session",
        "demo",
        cwd=repo_root,
    )

    assert result.returncode == 1
