from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_logger = logging.getLogger(__name__)

_CLI_MAX_RETRIES = 3
_CLI_BACKOFF_BASE = 5  # seconds: 5, 10, 20

from .models import FixerAttemptResult, FixerContext, PackManifest


_SENSITIVE_PATTERNS = [
    # Anthropic API keys (most specific first)
    re.compile(r'\b(sk-ant-[a-zA-Z0-9]{4})[a-zA-Z0-9-]+\b'),
    # Generic sk- API keys
    re.compile(r'\b(sk-[a-zA-Z0-9]{8})[a-zA-Z0-9]+\b'),
    # key- and token- prefixed values
    re.compile(r'\b(key-[a-zA-Z0-9]{4})[a-zA-Z0-9]+\b'),
    re.compile(r'\b(token-[a-zA-Z0-9]{4})[a-zA-Z0-9]+\b'),
    # Bearer tokens
    re.compile(r'(Bearer\s+[a-zA-Z0-9]{4})[a-zA-Z0-9]+'),
    # Generic long hex/base64 strings (40+ chars, likely tokens)
    re.compile(r'\b([a-zA-Z0-9]{4})[a-zA-Z0-9]{36,}\b'),
]


def _mask_sensitive_values(text: str) -> str:
    """Replace values that look like API keys, tokens, or credentials with masked versions."""
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub(r'\1...REDACTED', text)
    return text


SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]
OutputLineCallback = Callable[[str, str], None]  # (phase, line)


@dataclass(frozen=True)
class ClaudeCliRuntimeError(RuntimeError):
    phase: str
    message: str
    command: tuple[str, ...]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class CodexCliRuntimeError(RuntimeError):
    phase: str
    message: str
    command: tuple[str, ...]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""

    def __str__(self) -> str:
        return self.message


class ClaudeCliRuntime:
    def __init__(
        self,
        *,
        command: str = "claude",
        subprocess_runner: SubprocessRunner | None = None,
        output_line_callback: OutputLineCallback | None = None,
    ) -> None:
        self.command = command
        self._subprocess_runner = subprocess_runner or _default_subprocess_runner
        self._output_line_callback = output_line_callback

    def planner_agent(
        self,
        *,
        model: str,
        prompt_path: Path,
        intake_path: Path,
        intake_text: str,
        session_root: Path,
        **_: object,
    ) -> str:
        planning_task_id = f"__planner_{intake_path.stem}__"
        return self.run_planner(
            model=model,
            prompt_path=prompt_path,
            intake_path=intake_path,
            intake_text=intake_text,
            session_root=session_root,
            planning_task_id=planning_task_id,
        )

    def resolver_agent(
        self,
        *,
        model: str,
        prompt_path: Path,
        session_root: Path,
        staged_plans,
        plan_paths,
        **_: object,
    ) -> str:
        sections = [f"Session root: {session_root}\n", "Staged plans:\n"]
        for index, (plan_path, staged_plan) in enumerate(zip(plan_paths, staged_plans, strict=False), start=1):
            sections.extend(
                [
                    f"\n[{index}] {plan_path}\n",
                    "--- BEGIN PLAN ---\n",
                    staged_plan.body,
                    "\n--- END PLAN ---\n",
                ]
            )
        return self._run_phase(
            phase="resolution",
            model=model,
            prompt_path=prompt_path,
            session_root=session_root,
            input_text="".join(sections),
        )

    def fixer_executor(self, context: FixerContext, *, model: str, prompt_path: Path, session_root: Path):
        try:
            output = self._run_phase(
                phase="auto_fix",
                model=model,
                prompt_path=prompt_path,
                session_root=session_root,
                input_text=_format_fixer_context(context),
            )
        except ClaudeCliRuntimeError as exc:
            return FixerAttemptResult(success=False, summary=str(exc))
        return FixerAttemptResult(success=True, summary=output.strip())

    def run_planner(
        self,
        *,
        model: str,
        prompt_path: Path,
        intake_path: Path,
        intake_text: str,
        session_root: Path,
        planning_task_id: str | None = None,
    ) -> str:
        return self._run_phase(
            phase="planning",
            model=model,
            prompt_path=prompt_path,
            session_root=session_root,
            input_text=(
                f"Session root: {session_root}\n"
                f"Intake file: {intake_path}\n"
                "--- BEGIN INTAKE ---\n"
                f"{intake_text}"
                "--- END INTAKE ---\n"
            ),
            task_id_override=planning_task_id,
        )

    def _run_phase(
        self,
        *,
        phase: str,
        model: str,
        prompt_path: Path,
        session_root: Path,
        input_text: str,
        task_id_override: str | None = None,
    ) -> str:
        last_error: ClaudeCliRuntimeError | None = None
        for attempt in range(1, _CLI_MAX_RETRIES + 1):
            try:
                return self._run_phase_once(
                    phase=phase,
                    model=model,
                    prompt_path=prompt_path,
                    session_root=session_root,
                    input_text=input_text,
                    task_id_override=task_id_override,
                    attempt=attempt,
                )
            except ClaudeCliRuntimeError as exc:
                last_error = exc
                # Don't retry if the CLI ran successfully but produced
                # empty/unparseable output — that won't improve on retry.
                if exc.exit_code == 0:
                    raise
                if attempt < _CLI_MAX_RETRIES:
                    backoff = _CLI_BACKOFF_BASE * (2 ** (attempt - 1))
                    _logger.warning(
                        "Claude CLI %s attempt %d/%d failed (exit %s), retrying in %ds: %s",
                        phase, attempt, _CLI_MAX_RETRIES, exc.exit_code, backoff, exc,
                    )
                    if self._output_line_callback is not None:
                        effective_task_id = task_id_override or phase
                        self._output_line_callback(
                            effective_task_id,
                            f"[{phase}] CLI failed (exit {exc.exit_code}), retry {attempt + 1}/{_CLI_MAX_RETRIES} in {backoff}s...",
                        )
                    time.sleep(backoff)
        # All retries exhausted
        assert last_error is not None
        raise last_error

    def _run_phase_once(
        self,
        *,
        phase: str,
        model: str,
        prompt_path: Path,
        session_root: Path,
        input_text: str,
        task_id_override: str | None = None,
        attempt: int = 1,
    ) -> str:
        effective_task_id = task_id_override or phase
        prompt_text = _load_prompt_bundle(prompt_path)
        command = [
            self.command,
            "--dangerously-skip-permissions",
            "--model",
            model,
            "--output-format",
            "stream-json",
            "--verbose",
            "-p",
            prompt_text,
        ]
        attempt_label = f" (attempt {attempt}/{_CLI_MAX_RETRIES})" if attempt > 1 else ""
        if self._output_line_callback is not None:
            self._output_line_callback(effective_task_id, f"[{phase}] Launching Claude CLI ({model}){attempt_label}...")
            completed = _streaming_subprocess_runner(
                command=command,
                cwd=session_root,
                input_text=input_text,
                line_callback=_make_detail_extracting_callback(effective_task_id, self._output_line_callback),
            )
            self._output_line_callback(
                effective_task_id,
                f"[{phase}] Claude CLI finished (exit {completed.returncode})",
            )
        else:
            completed = self._subprocess_runner(
                command=command,
                cwd=session_root,
                input_text=input_text,
            )
        if completed.returncode != 0:
            stderr = completed.stderr or ""
            stdout = completed.stdout or ""
            details = stderr.strip() or stdout.strip() or "Claude CLI failed"
            raise ClaudeCliRuntimeError(
                phase=phase,
                message=f"Claude CLI {phase} failed with exit code {completed.returncode}: {details}",
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        raw_output = completed.stdout or ""
        if not raw_output.strip():
            raise ClaudeCliRuntimeError(
                phase=phase,
                message=f"Claude CLI {phase} did not produce output.",
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=raw_output,
                stderr=completed.stderr or "",
            )
        output = _extract_result_text_from_stream_json(raw_output)
        if not output.strip():
            raise ClaudeCliRuntimeError(
                phase=phase,
                message=f"Claude CLI {phase} produced stream-json output but no result text.",
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=raw_output,
                stderr=completed.stderr or "",
            )
        return output


class CodexCliRuntime:
    def __init__(
        self,
        *,
        command: str = "codex",
        subprocess_runner: SubprocessRunner | None = None,
        output_line_callback: OutputLineCallback | None = None,
    ) -> None:
        self.command = command
        self._subprocess_runner = subprocess_runner or _default_subprocess_runner
        self._output_line_callback = output_line_callback

    def planner_agent(
        self,
        *,
        model: str,
        prompt_path: Path,
        intake_path: Path,
        intake_text: str,
        session_root: Path,
        reasoning_effort: str | None = None,
        **_: object,
    ) -> str:
        planning_task_id = f"__planner_{intake_path.stem}__"
        return self.run_planner(
            model=model,
            prompt_path=prompt_path,
            intake_path=intake_path,
            intake_text=intake_text,
            session_root=session_root,
            planning_task_id=planning_task_id,
            reasoning_effort=reasoning_effort,
        )

    def resolver_agent(
        self,
        *,
        model: str,
        prompt_path: Path,
        session_root: Path,
        staged_plans,
        plan_paths,
        reasoning_effort: str | None = None,
        **_: object,
    ) -> str:
        sections = [f"Session root: {session_root}\n", "Staged plans:\n"]
        for index, (plan_path, staged_plan) in enumerate(zip(plan_paths, staged_plans, strict=False), start=1):
            sections.extend(
                [
                    f"\n[{index}] {plan_path}\n",
                    "--- BEGIN PLAN ---\n",
                    staged_plan.body,
                    "\n--- END PLAN ---\n",
                ]
            )
        return self._run_phase(
            phase="resolution",
            model=model,
            prompt_path=prompt_path,
            session_root=session_root,
            input_text="".join(sections),
            reasoning_effort=reasoning_effort,
        )

    def fixer_executor(
        self,
        context: FixerContext,
        *,
        model: str,
        prompt_path: Path,
        session_root: Path,
        reasoning_effort: str | None = None,
    ):
        try:
            output = self._run_phase(
                phase="auto_fix",
                model=model,
                prompt_path=prompt_path,
                session_root=session_root,
                input_text=_format_fixer_context(context),
                reasoning_effort=reasoning_effort,
            )
        except CodexCliRuntimeError as exc:
            return FixerAttemptResult(success=False, summary=str(exc))
        return FixerAttemptResult(success=True, summary=output.strip())

    def run_planner(
        self,
        *,
        model: str,
        prompt_path: Path,
        intake_path: Path,
        intake_text: str,
        session_root: Path,
        planning_task_id: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        return self._run_phase(
            phase="planning",
            model=model,
            prompt_path=prompt_path,
            session_root=session_root,
            input_text=(
                f"Session root: {session_root}\n"
                f"Intake file: {intake_path}\n"
                "--- BEGIN INTAKE ---\n"
                f"{intake_text}"
                "--- END INTAKE ---\n"
            ),
            task_id_override=planning_task_id,
            reasoning_effort=reasoning_effort,
        )

    def _run_phase(
        self,
        *,
        phase: str,
        model: str,
        prompt_path: Path,
        session_root: Path,
        input_text: str,
        task_id_override: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        last_error: CodexCliRuntimeError | None = None
        for attempt in range(1, _CLI_MAX_RETRIES + 1):
            try:
                return self._run_phase_once(
                    phase=phase,
                    model=model,
                    prompt_path=prompt_path,
                    session_root=session_root,
                    input_text=input_text,
                    task_id_override=task_id_override,
                    attempt=attempt,
                    reasoning_effort=reasoning_effort,
                )
            except CodexCliRuntimeError as exc:
                last_error = exc
                if exc.exit_code == 0:
                    raise
                if attempt < _CLI_MAX_RETRIES:
                    backoff = _CLI_BACKOFF_BASE * (2 ** (attempt - 1))
                    _logger.warning(
                        "Codex CLI %s attempt %d/%d failed (exit %s), retrying in %ds: %s",
                        phase, attempt, _CLI_MAX_RETRIES, exc.exit_code, backoff, exc,
                    )
                    if self._output_line_callback is not None:
                        effective_task_id = task_id_override or phase
                        self._output_line_callback(
                            effective_task_id,
                            f"[{phase}] CLI failed (exit {exc.exit_code}), retry {attempt + 1}/{_CLI_MAX_RETRIES} in {backoff}s...",
                        )
                    time.sleep(backoff)
        assert last_error is not None
        raise last_error

    def _run_phase_once(
        self,
        *,
        phase: str,
        model: str,
        prompt_path: Path,
        session_root: Path,
        input_text: str,
        task_id_override: str | None = None,
        attempt: int = 1,
        reasoning_effort: str | None = None,
    ) -> str:
        effective_task_id = task_id_override or phase
        prompt_text = _load_prompt_bundle(prompt_path)
        full_prompt = f"{prompt_text}\n\n{input_text}".strip()
        command = [
            self.command,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "-m",
            model,
            "-C",
            str(session_root),
        ]
        if reasoning_effort is not None:
            command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        if phase in {"planning", "resolution"}:
            command.extend(["-c", 'model_reasoning_summary="detailed"'])
        command.append(full_prompt)
        attempt_label = f" (attempt {attempt}/{_CLI_MAX_RETRIES})" if attempt > 1 else ""
        if self._output_line_callback is not None:
            self._output_line_callback(effective_task_id, f"[{phase}] Launching Codex CLI ({model}){attempt_label}...")
            completed = _streaming_subprocess_runner(
                command=command,
                cwd=session_root,
                input_text="",
                line_callback=_make_detail_extracting_callback(
                    effective_task_id,
                    self._output_line_callback,
                    detail_extractor=_extract_detail_from_codex_json,
                ),
            )
            self._output_line_callback(
                effective_task_id,
                f"[{phase}] Codex CLI finished (exit {completed.returncode})",
            )
        else:
            completed = self._subprocess_runner(
                command=command,
                cwd=session_root,
                input_text="",
            )
        if completed.returncode != 0:
            stderr = completed.stderr or ""
            stdout = completed.stdout or ""
            details = stderr.strip() or stdout.strip() or "Codex CLI failed"
            raise CodexCliRuntimeError(
                phase=phase,
                message=f"Codex CLI {phase} failed with exit code {completed.returncode}: {details}",
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        raw_output = completed.stdout or ""
        if not raw_output.strip():
            raise CodexCliRuntimeError(
                phase=phase,
                message=f"Codex CLI {phase} did not produce output.",
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=raw_output,
                stderr=completed.stderr or "",
            )
        output = _extract_result_text_from_codex_json(raw_output)
        if not output.strip():
            raise CodexCliRuntimeError(
                phase=phase,
                message=f"Codex CLI {phase} produced JSON output but no agent message text.",
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=raw_output,
                stderr=completed.stderr or "",
            )
        return output


def _extract_detail_from_stream_json(line: str) -> str | None:
    """Extract a meaningful human-readable detail snippet from a stream-json NDJSON line."""
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    msg_type = obj.get("type")
    if msg_type == "system":
        return "CLI initialized (session started)"
    if msg_type == "assistant":
        content = obj.get("message", {}).get("content", [])
        tools = [b["name"] for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        if tools:
            detail = "Using: " + ", ".join(tools)
            return _mask_sensitive_values(detail[:80])
        texts = [
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()
        ]
        if texts:
            first_line = texts[-1].strip().split("\n")[0]
            return _mask_sensitive_values(first_line[:80])
        return None
    if msg_type == "result":
        result_text = obj.get("result", "")
        if result_text:
            first_line = result_text.strip().split("\n")[0]
            return _mask_sensitive_values(("Completed: " + first_line)[:80])
        return None
    return None


def _extract_detail_from_codex_json(line: str) -> str | None:
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    event_type = obj.get("type")
    if event_type == "thread.started":
        return "CLI initialized (thread started)"
    if event_type == "turn.started":
        return "Turn started"
    if event_type == "item.completed":
        item = obj.get("item", {})
        if item.get("type") == "agent_message":
            text = item.get("text", "")
            if text:
                first_line = text.strip().split("\n")[0]
                return _mask_sensitive_values(first_line[:80])
    return None


def _extract_result_text_from_stream_json(raw_output: str) -> str:
    """Extract the result text from stream-json NDJSON output.

    Scans lines in reverse for a 'result' type object and returns its 'result'
    field. Falls back to the raw output if no result line is found (handles
    non-stream-json output gracefully).
    """
    for line in reversed(raw_output.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") == "result":
            return obj.get("result", "")
    return raw_output


def _extract_result_text_from_codex_json(raw_output: str) -> str:
    for line in reversed(raw_output.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") != "item.completed":
            continue
        item = obj.get("item", {})
        if item.get("type") == "agent_message":
            return item.get("text", "")
    return raw_output


def _make_detail_extracting_callback(
    task_id: str,
    output_callback: OutputLineCallback,
    *,
    detail_extractor: Callable[[str], str | None] = _extract_detail_from_stream_json,
) -> Callable[[str], None]:
    """Wrap an output callback to also emit parsed detail snippets from stream-json lines."""

    def callback(line: str) -> None:
        sanitized = _mask_sensitive_values(line)
        output_callback(task_id, sanitized)
        detail = detail_extractor(line)
        if detail:
            output_callback(task_id, f"##DETAIL## {detail}")

    return callback


def build_agent_runtime(
    runtime_kind: str,
    output_line_callback: OutputLineCallback | None = None,
):
    if runtime_kind == "claude":
        return ClaudeCliRuntime(output_line_callback=output_line_callback)
    if runtime_kind == "codex":
        return CodexCliRuntime(output_line_callback=output_line_callback)
    raise ValueError(f"Unsupported agent runtime kind: {runtime_kind!r}")


def build_default_agent_runtime(
    pack_manifest: PackManifest,
    output_line_callback: OutputLineCallback | None = None,
):
    return build_agent_runtime(
        pack_manifest.phases.planning.runtime,
        output_line_callback=output_line_callback,
    )


def _default_subprocess_runner(
    *,
    command: list[str],
    cwd: Path,
    input_text: str,
) -> subprocess.CompletedProcess[str]:
    # Strip CLAUDECODE env var so child Claude CLI sessions don't refuse to
    # launch when the orchestrator itself is running inside Claude Code.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    return subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _streaming_subprocess_runner(
    *,
    command: list[str],
    cwd: Path,
    input_text: str,
    line_callback: Callable[[str], None],
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess while streaming stdout lines through a callback.

    Returns a CompletedProcess with the full captured stdout/stderr, compatible
    with the non-streaming runner.
    """
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _read_stderr():
        assert proc.stderr is not None
        for raw_line in iter(proc.stderr.readline, ""):
            stderr_lines.append(raw_line)
        proc.stderr.close()

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    # Write input and close stdin
    assert proc.stdin is not None
    try:
        proc.stdin.write(input_text)
        proc.stdin.close()
    except BrokenPipeError:
        pass

    # Read stdout line-by-line, streaming to callback
    assert proc.stdout is not None
    for raw_line in iter(proc.stdout.readline, ""):
        stdout_lines.append(raw_line)
        try:
            line_callback(raw_line.rstrip("\r\n"))
        except Exception:
            pass  # callback errors must not crash the subprocess runner
    proc.stdout.close()

    stderr_thread.join(timeout=5.0)
    proc.wait()
    return subprocess.CompletedProcess(
        args=command,
        returncode=proc.returncode,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
    )


def _format_fixer_context(context: FixerContext) -> str:
    sections = [
        f"Context type: {context.context_type}\n",
        f"Session id: {context.session_id}\n",
        f"Task id: {context.task_id or 'none'}\n",
        f"Attempt: {context.attempt}\n",
    ]
    if context.failure_kind:
        sections.append(f"Failure kind: {context.failure_kind}\n")
    if context.plan_text:
        sections.extend(["--- BEGIN PLAN ---\n", context.plan_text, "\n--- END PLAN ---\n"])
    if context.status_text:
        sections.extend(["--- BEGIN STATUS ---\n", context.status_text, "\n--- END STATUS ---\n"])
    if context.worker_log_tail:
        sections.extend(["--- BEGIN WORKER LOG ---\n", context.worker_log_tail, "\n--- END WORKER LOG ---\n"])
    if context.verification_output:
        sections.extend(
            ["--- BEGIN VERIFICATION ---\n", context.verification_output, "\n--- END VERIFICATION ---\n"]
        )
    if context.previous_attempt_summary:
        sections.append(f"Previous attempt summary: {context.previous_attempt_summary}\n")
    return "".join(sections)


def _load_prompt_bundle(prompt_path: Path) -> str:
    prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    system_prompt_path = prompt_path.with_name("system.md")
    if not system_prompt_path.is_file():
        return prompt_text
    system_text = system_prompt_path.read_text(encoding="utf-8").strip()
    if not system_text:
        return prompt_text
    return f"{system_text}\n\n{prompt_text}"
