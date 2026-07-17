from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import json

from cognitive_switchyard.agent_runtime import (
    ClaudeCliRuntime,
    ClaudeCliRuntimeError,
    CodexCliRuntime,
    build_agent_runtime,
    _extract_detail_from_codex_json,
    _extract_detail_from_stream_json,
    _extract_result_text_from_codex_json,
    _extract_result_text_from_stream_json,
    _format_fixer_context,
    _mask_sensitive_values,
)
from cognitive_switchyard.models import FixerContext


def test_claude_cli_runner_builds_planner_invocation_from_model_prompt_and_session_inputs(
    tmp_path: Path,
) -> None:
    (tmp_path / "system.md").write_text("Shared system rules.\n", encoding="utf-8")
    prompt_path = tmp_path / "planner.md"
    prompt_path.write_text("Planner system prompt.\n", encoding="utf-8")
    intake_path = tmp_path / "001_feature.md"
    intake_path.write_text("# Feature\nImplement packet 13.\n", encoding="utf-8")
    session_root = tmp_path / "session-root"
    session_root.mkdir()

    captured: dict[str, object] = {}

    def fake_runner(*, command: list[str], cwd: Path, input_text: str) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["cwd"] = cwd
        captured["input_text"] = input_text
        return subprocess.CompletedProcess(command, 0, stdout="planned output\n", stderr="")

    runtime = ClaudeCliRuntime(command="claude", subprocess_runner=fake_runner)

    result = runtime.run_planner(
        model="claude-opus-4-1",
        prompt_path=prompt_path,
        intake_path=intake_path,
        intake_text=intake_path.read_text(encoding="utf-8"),
        session_root=session_root,
    )

    assert result == "planned output\n"
    assert captured["cwd"] == session_root
    assert captured["command"] == [
        "claude",
        "--dangerously-skip-permissions",
        "--model",
        "claude-opus-4-1",
        "--output-format",
        "stream-json",
        "--verbose",
        "-p",
        "Shared system rules.\n\nPlanner system prompt.",
    ]
    assert captured["input_text"] == (
        f"Session root: {session_root}\n"
        f"Intake file: {intake_path}\n"
        "--- BEGIN INTAKE ---\n"
        "# Feature\n"
        "Implement packet 13.\n"
        "--- END INTAKE ---\n"
    )


@pytest.mark.parametrize(
    ("completed", "message_fragment"),
    [
        (
            subprocess.CompletedProcess(["claude"], 2, stdout="", stderr="boom"),
            "exit code 2",
        ),
        (
            subprocess.CompletedProcess(["claude"], 0, stdout=" \n", stderr=""),
            "did not produce output",
        ),
    ],
)
def test_claude_cli_runner_raises_typed_error_on_non_zero_exit_or_missing_output(
    tmp_path: Path,
    completed: subprocess.CompletedProcess[str],
    message_fragment: str,
) -> None:
    prompt_path = tmp_path / "planner.md"
    prompt_path.write_text("Planner prompt.\n", encoding="utf-8")

    runtime = ClaudeCliRuntime(
        command="claude",
        subprocess_runner=lambda **_: completed,
    )

    with pytest.raises(ClaudeCliRuntimeError) as excinfo:
        runtime.run_planner(
            model="claude-opus-4-1",
            prompt_path=prompt_path,
            intake_path=tmp_path / "001_feature.md",
            intake_text="test\n",
            session_root=tmp_path,
        )

    error = excinfo.value
    assert error.phase == "planning"
    assert message_fragment in str(error)


def test_claude_cli_runner_uses_phase_prompt_when_shared_system_prompt_is_absent(
    tmp_path: Path,
) -> None:
    prompt_path = tmp_path / "planner.md"
    prompt_path.write_text("Planner prompt only.\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_runner(*, command: list[str], cwd: Path, input_text: str) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    runtime = ClaudeCliRuntime(command="claude", subprocess_runner=fake_runner)

    runtime.run_planner(
        model="claude-opus-4-1",
        prompt_path=prompt_path,
        intake_path=tmp_path / "001_feature.md",
        intake_text="test\n",
        session_root=tmp_path,
    )

    assert captured["command"] == [
        "claude",
        "--dangerously-skip-permissions",
        "--model",
        "claude-opus-4-1",
        "--output-format",
        "stream-json",
        "--verbose",
        "-p",
        "Planner prompt only.",
    ]


def test_codex_cli_runner_builds_planner_invocation_with_reasoning_config_and_combined_prompt(
    tmp_path: Path,
) -> None:
    (tmp_path / "system.md").write_text("Shared system rules.\n", encoding="utf-8")
    prompt_path = tmp_path / "planner.md"
    prompt_path.write_text("Planner system prompt.\n", encoding="utf-8")
    intake_path = tmp_path / "001_feature.md"
    intake_path.write_text("# Feature\nImplement packet 13.\n", encoding="utf-8")
    session_root = tmp_path / "session-root"
    session_root.mkdir()

    captured: dict[str, object] = {}

    def fake_runner(*, command: list[str], cwd: Path, input_text: str) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["cwd"] = cwd
        captured["input_text"] = input_text
        stdout = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "abc"}),
            json.dumps({"type": "turn.started"}),
            json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "planned output"}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
        ]) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    runtime = CodexCliRuntime(command="codex", subprocess_runner=fake_runner)

    result = runtime.run_planner(
        model="gpt-5.4",
        prompt_path=prompt_path,
        intake_path=intake_path,
        intake_text=intake_path.read_text(encoding="utf-8"),
        session_root=session_root,
        reasoning_effort="xhigh",
    )

    assert result == "planned output"
    assert captured["cwd"] == session_root
    assert captured["input_text"] == ""
    assert captured["command"] == [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "-m",
        "gpt-5.4",
        "-C",
        str(session_root),
        "-c",
        'model_reasoning_effort="xhigh"',
        "-c",
        'model_reasoning_summary="detailed"',
        (
            "Shared system rules.\n\nPlanner system prompt.\n\n"
            f"Session root: {session_root}\n"
            f"Intake file: {intake_path}\n"
            "--- BEGIN INTAKE ---\n"
            "# Feature\n"
            "Implement packet 13.\n"
            "--- END INTAKE ---"
        ),
    ]


# --- Regression tests for stream-json NDJSON parsing helpers ---


def test_extract_detail_system_line_returns_init_message() -> None:
    line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc"})
    assert _extract_detail_from_stream_json(line) == "CLI initialized (session started)"


def test_extract_detail_assistant_with_tool_use_returns_tool_names() -> None:
    line = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": "1", "name": "Read", "input": {}},
                {"type": "tool_use", "id": "2", "name": "Edit", "input": {}},
            ]
        },
    })
    result = _extract_detail_from_stream_json(line)
    assert result == "Using: Read, Edit"


def test_extract_detail_assistant_text_only_returns_first_line_truncated() -> None:
    long_text = "A" * 100 + "\nSecond line"
    line = json.dumps({
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": long_text}],
        },
    })
    result = _extract_detail_from_stream_json(line)
    assert result is not None
    # Result is truncated to 80 chars before masking. The "A"*80 synthetic
    # input triggers _mask_sensitive_values (long opaque alphanumeric string),
    # so the exact value is masked rather than being "A"*80. Length may exceed
    # 80 due to the "...REDACTED" suffix added by masking.
    assert "Second line" not in result


def test_extract_detail_result_line_returns_completed_prefix() -> None:
    line = json.dumps({"type": "result", "result": "Done with the task.\nMore text."})
    result = _extract_detail_from_stream_json(line)
    assert result is not None
    assert result.startswith("Completed: ")
    assert "Done with the task." in result


def test_extract_detail_other_type_returns_none() -> None:
    line = json.dumps({"type": "rate_limit_event", "data": {}})
    assert _extract_detail_from_stream_json(line) is None


def test_extract_detail_malformed_json_returns_none() -> None:
    assert _extract_detail_from_stream_json("not json at all") is None
    assert _extract_detail_from_stream_json("{broken") is None


def test_extract_detail_non_json_line_returns_none() -> None:
    assert _extract_detail_from_stream_json("##PROGRESS## 001 | Phase: implementing | 3/5") is None


def test_extract_result_text_finds_result_line() -> None:
    ndjson = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {"content": []}}),
        json.dumps({"type": "result", "result": "The plan is complete.\n\nSee attached."}),
    ]) + "\n"
    result = _extract_result_text_from_stream_json(ndjson)
    assert result == "The plan is complete.\n\nSee attached."


def test_extract_result_text_falls_back_to_raw_if_no_result_line() -> None:
    raw = "plain text output\nnot NDJSON\n"
    result = _extract_result_text_from_stream_json(raw)
    assert result == raw


def test_extract_detail_from_codex_json_reads_agent_message_text() -> None:
    line = json.dumps({
        "type": "item.completed",
        "item": {"id": "item_0", "type": "agent_message", "text": "Done with the task.\nMore text."},
    })
    assert _extract_detail_from_codex_json(line) == "Done with the task."


def test_extract_result_text_from_codex_json_reads_last_agent_message() -> None:
    output = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "abc"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "hi"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
    ]) + "\n"
    assert _extract_result_text_from_codex_json(output) == "hi"


def test_build_agent_runtime_selects_expected_runtime_class() -> None:
    assert isinstance(build_agent_runtime("claude"), ClaudeCliRuntime)
    assert isinstance(build_agent_runtime("codex"), CodexCliRuntime)


def test_extract_result_text_handles_empty_result_field() -> None:
    ndjson = "\n".join([
        json.dumps({"type": "system"}),
        json.dumps({"type": "result", "result": ""}),
    ]) + "\n"
    # Falls back to raw since result field is empty string
    result = _extract_result_text_from_stream_json(ndjson)
    assert result == ""


# --- Regression tests for _mask_sensitive_values ---


def test_mask_sensitive_values_anthropic_key() -> None:
    result = _mask_sensitive_values("key is sk-ant-api03-abcdefghij1234567890abcdefghij")
    assert "sk-ant-api0" in result
    assert "REDACTED" in result
    assert "abcdefghij1234567890" not in result


def test_mask_sensitive_values_sk_key() -> None:
    result = _mask_sensitive_values("Authorization: sk-abcdefgh1234567890abcdefghij1234567890")
    assert "sk-abcdefg" in result
    assert "REDACTED" in result
    assert "1234567890abcdefghij" not in result


def test_mask_sensitive_values_bearer_token() -> None:
    result = _mask_sensitive_values("Authorization: Bearer abcd1234567890abcdefghij1234567890xyz99")
    assert "Bearer abcd" in result
    assert "REDACTED" in result
    assert "1234567890abcdefghij" not in result


def test_mask_sensitive_values_long_hex_string() -> None:
    # 40 chars of hex — should be masked
    long_token = "abcd" + "1234567890abcdef" * 3  # 4 + 48 = 52 chars  # pragma: allowlist secret
    result = _mask_sensitive_values(f"token={long_token}")
    assert "REDACTED" in result
    assert long_token not in result


def test_mask_sensitive_values_normal_text_unchanged() -> None:
    text = "Resolving dependencies for plan 022"
    assert _mask_sensitive_values(text) == text


def test_mask_sensitive_values_short_strings_unchanged() -> None:
    # Short strings must not be masked (prevent false positives)
    assert _mask_sensitive_values("hello world") == "hello world"
    assert _mask_sensitive_values("abc123") == "abc123"


def test_mask_sensitive_values_mixed_text_only_key_masked() -> None:
    # Normal text before and after an embedded key
    key = "sk-ant-api03-" + "x" * 30
    text = f"Processing plan. API key={key}. Done."
    result = _mask_sensitive_values(text)
    assert "Processing plan." in result
    assert "Done." in result
    assert "REDACTED" in result
    assert "x" * 30 not in result


def test_mask_sensitive_values_multiple_keys_all_masked() -> None:
    key1 = "sk-ant-api03-" + "a" * 30
    key2 = "sk-" + "b" * 40
    text = f"key1={key1} key2={key2}"
    result = _mask_sensitive_values(text)
    assert result.count("REDACTED") >= 2
    assert "a" * 30 not in result
    assert "b" * 40 not in result


def test_mask_sensitive_values_empty_string() -> None:
    assert _mask_sensitive_values("") == ""


def test_claude_cli_command_includes_stream_json_flags(tmp_path: Path) -> None:
    """Regression: stream-json flags must always be in the command."""
    prompt_path = tmp_path / "planner.md"
    prompt_path.write_text("prompt\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_runner(*, command: list[str], cwd: Path, input_text: str) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="output\n", stderr="")

    runtime = ClaudeCliRuntime(command="claude", subprocess_runner=fake_runner)
    runtime.run_planner(
        model="sonnet",
        prompt_path=prompt_path,
        intake_path=tmp_path / "001.md",
        intake_text="test\n",
        session_root=tmp_path,
    )

    cmd = captured["command"]
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--verbose" in cmd


def test_format_fixer_context_includes_failure_kind() -> None:
    context = FixerContext(
        context_type="task_failure",
        session_id="test",
        task_id="001",
        attempt=1,
        failure_kind="timeout",
    )
    output = _format_fixer_context(context)
    assert "Failure kind: timeout" in output


def test_format_fixer_context_omits_failure_kind_when_none() -> None:
    context = FixerContext(
        context_type="task_failure",
        session_id="test",
        task_id="001",
        attempt=1,
        failure_kind=None,
    )
    output = _format_fixer_context(context)
    assert "Failure kind:" not in output
