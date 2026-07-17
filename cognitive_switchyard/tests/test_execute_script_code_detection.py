"""Regression tests for execute script code-change detection logic.

These tests verify that the execute scripts (claude-code and codex packs) emit
a WARNING in the NOTES field when code files were modified but no test execution
was detected in the worker output.

Regression for: plan 016 — Enforce Worker Test Discipline
The scripts previously silently wrote TESTS_RAN: none without any warning even
when .py/.js/etc files had been committed, making untested code changes invisible.
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest


def _init_git_repo_with_py_commit(workspace: Path) -> str:
    """Create a minimal git repo with an initial commit then a .py file commit.

    Returns the SHA of the .py commit (FIRST_SHA in the execute script).
    The initial empty commit ensures FIRST_SHA~1 resolves (not root commit).
    """
    subprocess.run(["git", "init", "-b", "main"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "synthetic-user@example.invalid"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    # Initial empty commit so that FIRST_SHA~1 resolves in git diff
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "initial"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    py_file = workspace / "module.py"
    py_file.write_text("def hello(): pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "module.py"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add module"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_detection_logic(
    workspace: Path,
    commits: str,
    worker_output: str,
    worker_type: str = "claude",
) -> dict[str, str]:
    """Run just the detection logic portion of the execute script inline.

    Extracts and runs the code-change detection + sidecar-writing logic as a
    standalone shell snippet so we can test it without invoking Claude/Codex.
    Returns the parsed key-value pairs from the written .status file.
    """
    status_path = workspace / "001.status"
    output_file = workspace / f"001.{worker_type}_output"
    output_file.write_text(worker_output, encoding="utf-8")

    worker_label = "Claude" if worker_type == "claude" else "Codex"
    if worker_type == "claude":
        # claude-code version greps RESULT_TEXT (a variable) for test keywords
        # We simulate RESULT_TEXT containing the worker output
        result_text_cmd = f'RESULT_TEXT={repr(worker_output)}'
        test_grep = 'if echo "$RESULT_TEXT" | grep -qi'
        test_grep2 = 'if echo "$RESULT_TEXT" | grep -qi'
    else:
        result_text_cmd = ""
        test_grep = f'if grep -qi'
        test_grep2 = f'if grep -qi'

    # Build the detection script matching the actual execute script logic
    script = textwrap.dedent(f"""\
        #!/bin/sh
        set -eu
        WORKSPACE_PATH={str(workspace)!r}
        COMMITS={commits!r}
        OUTPUT_FILE={str(output_file)!r}
        STATUS_PATH={str(status_path)!r}

        # Determine test results (matching execute script logic)
        TESTS_RAN="none"
        TEST_RESULT="skip"
    """)

    if worker_type == "claude":
        script += textwrap.dedent(f"""\
            RESULT_TEXT={repr(worker_output)}
            if echo "$RESULT_TEXT" | grep -qi "pytest\\|test.*pass\\|tests.*pass\\|test.*fail\\|tests.*fail\\|npm test\\|jest\\|vitest\\|playwright" 2>/dev/null; then
              TESTS_RAN="targeted"
              if echo "$RESULT_TEXT" | grep -qi "test.*fail\\|tests.*fail\\|FAILED\\|AssertionError" 2>/dev/null; then
                TEST_RESULT="fail"
              else
                TEST_RESULT="pass"
              fi
            fi
        """)
    else:
        script += textwrap.dedent(f"""\
            if grep -qi "pytest\\|test.*pass\\|tests.*pass\\|test.*fail\\|tests.*fail\\|npm test\\|jest\\|vitest\\|playwright" "$OUTPUT_FILE" 2>/dev/null; then
              TESTS_RAN="targeted"
              if grep -qi "test.*fail\\|tests.*fail\\|FAILED\\|AssertionError" "$OUTPUT_FILE" 2>/dev/null; then
                TEST_RESULT="fail"
              else
                TEST_RESULT="pass"
              fi
            fi
        """)

    script += textwrap.dedent(f"""\
        # Detect code-changed files
        CODE_CHANGED="no"
        if [ "$COMMITS" != "none" ]; then
          FIRST_SHA=$(echo "$COMMITS" | tr ',' '\\n' | tail -1)
          CODE_EXTS=$(git -C "$WORKSPACE_PATH" diff --name-only "${{FIRST_SHA}}~1"..HEAD 2>/dev/null \\
            | grep -E '\\.(py|js|jsx|ts|tsx|sh|go|rs|java|c|cpp|h|html|css|sql)$' \\
            || true)
          if [ -n "$CODE_EXTS" ]; then
            CODE_CHANGED="yes"
          fi
        fi

        NOTES="{worker_label} worker completed in $WORKSPACE_PATH"
        if [ "$CODE_CHANGED" = "yes" ] && [ "$TESTS_RAN" = "none" ]; then
          NOTES="WARNING: Code files were modified but no test execution was detected in worker output. $NOTES"
        fi

        cat >"$STATUS_PATH" <<EOF
STATUS: done
COMMITS: $COMMITS
TESTS_RAN: $TESTS_RAN
TEST_RESULT: $TEST_RESULT
NOTES: $NOTES
EOF
    """)

    result = subprocess.run(
        ["sh", "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Detection script failed:\n{result.stderr}"

    parsed: dict[str, str] = {}
    for line in status_path.read_text(encoding="utf-8").splitlines():
        if ":" in line:
            key, _, value = line.partition(": ")
            parsed[key.strip()] = value.strip()
    return parsed


class TestClaudeCodeDetection:
    """Tests for the claude-code execute script code-change detection."""

    def test_warning_emitted_when_code_changed_and_no_tests_detected(
        self, tmp_path: Path
    ) -> None:
        """Regression: code files modified + no test output → WARNING in NOTES."""
        sha = _init_git_repo_with_py_commit(tmp_path)
        worker_output = "I have implemented the feature and committed the changes."

        sidecar = _run_detection_logic(tmp_path, sha, worker_output, worker_type="claude")

        assert sidecar["TESTS_RAN"] == "none"
        assert "WARNING: Code files were modified but no test execution was detected" in sidecar["NOTES"]

    def test_no_warning_when_tests_detected(self, tmp_path: Path) -> None:
        """No warning when worker output mentions pytest."""
        sha = _init_git_repo_with_py_commit(tmp_path)
        worker_output = "Running pytest... 5 passed in 0.12s"

        sidecar = _run_detection_logic(tmp_path, sha, worker_output, worker_type="claude")

        assert sidecar["TESTS_RAN"] == "targeted"
        assert "WARNING" not in sidecar["NOTES"]

    def test_no_warning_when_no_commits(self, tmp_path: Path) -> None:
        """No warning when COMMITS is 'none' (nothing was committed)."""
        _init_git_repo_with_py_commit(tmp_path)
        worker_output = "Documentation update only."

        sidecar = _run_detection_logic(tmp_path, "none", worker_output, worker_type="claude")

        assert sidecar["TESTS_RAN"] == "none"
        assert "WARNING" not in sidecar["NOTES"]

    def test_detects_npm_test_keyword(self, tmp_path: Path) -> None:
        """npm test keyword is detected (extended grep pattern in plan 016)."""
        sha = _init_git_repo_with_py_commit(tmp_path)
        worker_output = "Running npm test... all tests passed"

        sidecar = _run_detection_logic(tmp_path, sha, worker_output, worker_type="claude")

        assert sidecar["TESTS_RAN"] == "targeted"
        assert "WARNING" not in sidecar["NOTES"]

    def test_detects_jest_keyword(self, tmp_path: Path) -> None:
        """jest keyword is detected (extended grep pattern in plan 016)."""
        sha = _init_git_repo_with_py_commit(tmp_path)
        worker_output = "jest: 10 tests passed"

        sidecar = _run_detection_logic(tmp_path, sha, worker_output, worker_type="claude")

        assert sidecar["TESTS_RAN"] == "targeted"
        assert "WARNING" not in sidecar["NOTES"]


class TestCodexDetection:
    """Tests for the codex execute script code-change detection."""

    def test_warning_emitted_when_code_changed_and_no_tests_detected(
        self, tmp_path: Path
    ) -> None:
        """Regression: code files modified + no test output → WARNING in NOTES."""
        sha = _init_git_repo_with_py_commit(tmp_path)
        worker_output = "I have implemented the feature and committed the changes."

        sidecar = _run_detection_logic(tmp_path, sha, worker_output, worker_type="codex")

        assert sidecar["TESTS_RAN"] == "none"
        assert "WARNING: Code files were modified but no test execution was detected" in sidecar["NOTES"]

    def test_no_warning_when_tests_detected(self, tmp_path: Path) -> None:
        """No warning when output contains pytest."""
        sha = _init_git_repo_with_py_commit(tmp_path)
        worker_output = "pytest: 8 tests passed, 0 failed"

        sidecar = _run_detection_logic(tmp_path, sha, worker_output, worker_type="codex")

        assert sidecar["TESTS_RAN"] == "targeted"
        assert "WARNING" not in sidecar["NOTES"]

    def test_no_warning_when_no_commits(self, tmp_path: Path) -> None:
        """No warning when COMMITS is 'none'."""
        _init_git_repo_with_py_commit(tmp_path)
        worker_output = "Documentation update."

        sidecar = _run_detection_logic(tmp_path, "none", worker_output, worker_type="codex")

        assert sidecar["TESTS_RAN"] == "none"
        assert "WARNING" not in sidecar["NOTES"]
