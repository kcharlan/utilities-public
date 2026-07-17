from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Mapping

from .models import FixerContext, VerificationRunResult

_PYTEST_SUMMARY_RE = re.compile(
    r"(\d+ passed(?:,\s*\d+ \w+)*)",
    re.IGNORECASE,
)


_logger = __import__("logging").getLogger(__name__)


def run_verification_command(
    *,
    session_root: Path,
    verify_log_path: Path,
    command: str,
    env: Mapping[str, str] | None = None,
    output_line_callback: Callable[[str], None] | None = None,
) -> VerificationRunResult:
    # Strip CLAUDECODE so verification scripts get the same clean environment
    # as hook and agent subprocesses. F-12 fix.
    command_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    if env is not None:
        command_env.update(env)

    try:
        if output_line_callback is not None:
            proc = subprocess.Popen(
                command,
                cwd=session_root,
                env=command_env,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            stdout_lines: list[str] = []
            if proc.stdout:
                for line in proc.stdout:
                    stripped = line.rstrip("\n")
                    stdout_lines.append(stripped)
                    try:
                        output_line_callback(stripped)
                    except Exception:
                        pass  # callback errors must not crash verification
            proc.wait()
            output = "\n".join(stdout_lines)
            exit_code = proc.returncode
        else:
            result = subprocess.run(
                command,
                cwd=session_root,
                env=command_env,
                shell=True,
                capture_output=True,
                text=True,
            )
            output = (result.stdout or "") + (result.stderr or "")
            exit_code = result.returncode
    except Exception as exc:
        _logger.error("Verification subprocess failed: %s", exc)
        output = f"Verification subprocess failed: {exc}"
        exit_code = 127

    verify_log_path.parent.mkdir(parents=True, exist_ok=True)
    verify_log_path.write_text(output, encoding="utf-8")
    return VerificationRunResult(
        ok=(exit_code == 0),
        exit_code=exit_code,
        output=output,
        log_path=verify_log_path,
    )


def parse_test_summary(output: str) -> str | None:
    """Extract a pytest-style test count summary from verification command output.

    Returns a string like "279 passed" or "277 passed, 2 failed", or None if
    no recognizable pytest summary line is found.
    """
    for line in reversed(output.splitlines()):
        match = _PYTEST_SUMMARY_RE.search(line)
        if match:
            return match.group(1)
    return None


def build_task_failure_context(
    *,
    session_id: str,
    task_id: str,
    attempt: int,
    plan_path: Path,
    status_path: Path | None,
    worker_log_path: Path | None,
    verify_log_path: Path,
    previous_attempt_summary: str | None,
    previous_verification_output: str | None = None,
    failure_kind: str | None = None,
) -> FixerContext:
    enriched_summary = _enrich_previous_summary(
        previous_attempt_summary, previous_verification_output
    )
    return FixerContext(
        context_type="task_failure",
        session_id=session_id,
        task_id=task_id,
        attempt=attempt,
        plan_text=_read_text(plan_path),
        status_text=_read_text(status_path),
        worker_log_tail=_tail_text(worker_log_path, limit=80),
        verification_output=_read_text(verify_log_path),
        previous_attempt_summary=enriched_summary,
        failure_kind=failure_kind,
    )


def build_verification_failure_context(
    *,
    session_id: str,
    attempt: int,
    verify_log_path: Path,
    previous_attempt_summary: str | None,
    previous_verification_output: str | None = None,
) -> FixerContext:
    enriched_summary = _enrich_previous_summary(
        previous_attempt_summary, previous_verification_output
    )
    return FixerContext(
        context_type="verification_failure",
        session_id=session_id,
        task_id=None,
        attempt=attempt,
        verification_output=_read_text(verify_log_path),
        previous_attempt_summary=enriched_summary,
    )


def _enrich_previous_summary(
    fixer_summary: str | None,
    verification_output: str | None,
) -> str | None:
    """Combine fixer self-report with actual verification output for richer retry context."""
    if fixer_summary is None and verification_output is None:
        return None
    parts: list[str] = []
    if fixer_summary:
        parts.append(f"Previous fixer summary:\n{fixer_summary}")
    if verification_output:
        parts.append(f"Actual verification output:\n{verification_output}")
    parts.append(
        "Try a DIFFERENT approach. The previous fixer's changes are already committed."
    )
    return "\n\n".join(parts)


def _read_text(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _tail_text(path: Path | None, *, limit: int) -> str | None:
    contents = _read_text(path)
    if contents is None:
        return None
    lines = contents.splitlines()
    return "\n".join(lines[-limit:])
