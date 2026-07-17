from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cognitive_switchyard.parsers import (
    ArtifactParseError,
    extract_commit_description,
    parse_progress_line,
    parse_resolution_json,
    parse_status_sidecar,
    parse_task_plan,
)


def test_parse_task_plan_extracts_scheduler_metadata(repo_root: Path) -> None:
    fixture_path = repo_root / "tests" / "fixtures" / "tasks" / "plan_with_constraints.plan.md"

    plan = parse_task_plan(fixture_path.read_text(encoding="utf-8"), source=fixture_path)

    assert plan.task_id == "039"
    assert (
        plan.title == "Fix chunk progress counter double-counting during cross-model verification"
    )
    assert plan.depends_on == ("021d", "022")
    assert plan.anti_affinity == ("043",)
    assert plan.exec_order == 7
    assert plan.full_test_after is True
    assert "## Problem" in plan.body


def test_parse_task_plan_supports_yaml_list_constraints() -> None:
    plan = parse_task_plan(
        "---\n"
        "PLAN_ID: 039\n"
        "DEPENDS_ON:\n"
        "  - 021d\n"
        "  - 022\n"
        "ANTI_AFFINITY:\n"
        "  - 043\n"
        "EXEC_ORDER: 7\n"
        "FULL_TEST_AFTER: yes\n"
        "---\n"
        "\n"
        "# Plan: Fix chunk progress counter double-counting during cross-model verification\n"
    )

    assert plan.depends_on == ("021d", "022")
    assert plan.anti_affinity == ("043",)


def test_parse_status_sidecar_supports_done_and_blocked_payloads(repo_root: Path) -> None:
    done_path = repo_root / "tests" / "fixtures" / "status_reference_minimal.status"
    blocked_path = repo_root / "tests" / "fixtures" / "tasks" / "status_blocked.status"

    done_status = parse_status_sidecar(done_path.read_text(encoding="utf-8"), source=done_path)
    blocked_status = parse_status_sidecar(
        blocked_path.read_text(encoding="utf-8"), source=blocked_path
    )

    assert done_status.status == "done"
    assert done_status.commits == ("68cfc1c",)
    assert done_status.tests_ran == "targeted"
    assert done_status.test_result == "pass"
    assert done_status.blocked_reason is None

    assert blocked_status.status == "blocked"
    assert blocked_status.commits == ()
    assert blocked_status.tests_ran == "none"
    assert blocked_status.test_result == "skip"
    assert blocked_status.blocked_reason == "Waiting on operator approval"
    assert blocked_status.notes == "Needs manual decision."


def test_parse_status_sidecar_supports_json_and_yaml_formats() -> None:
    json_status = parse_status_sidecar(
        '{"status":"done","commits":"abc1234","tests_ran":"full","test_result":"pass"}',
        sidecar_format="json",
    )
    yaml_status = parse_status_sidecar(
        "status: blocked\ncommits: none\ntests_ran: none\ntest_result: skip\nblocked_reason: Manual review\n",
        sidecar_format="yaml",
    )

    assert json_status.status == "done"
    assert json_status.commits == ("abc1234",)
    assert json_status.tests_ran == "full"
    assert yaml_status.status == "blocked"
    assert yaml_status.blocked_reason == "Manual review"


@pytest.mark.parametrize(
    ("line", "expected_kind", "expected_value"),
    [
        (
            "##PROGRESS## 039 | Phase: execute | 3/5",
            "phase",
            ("execute", 3, 5),
        ),
        (
            "##PROGRESS## 039 | Detail: Processing chunk 3/9",
            "detail",
            "Processing chunk 3/9",
        ),
    ],
)
def test_parse_progress_line_supports_phase_and_detail_variants(
    line: str, expected_kind: str, expected_value: object
) -> None:
    progress = parse_progress_line(line)

    assert progress.kind == expected_kind
    assert progress.task_id == "039"
    if expected_kind == "phase":
        assert progress.phase_name == expected_value[0]
        assert progress.phase_index == expected_value[1]
        assert progress.phase_total == expected_value[2]
        assert progress.detail_message is None
    else:
        assert progress.detail_message == expected_value
        assert progress.phase_name is None


def test_parse_progress_line_supports_custom_progress_regex() -> None:
    progress = parse_progress_line(
        "@@PROG@@ 039 | Phase: execute | 2/4",
        progress_format="@@PROG@@",
    )

    assert progress.task_id == "039"
    assert progress.kind == "phase"
    assert progress.phase_name == "execute"
    assert progress.phase_index == 2
    assert progress.phase_total == 4


@pytest.mark.parametrize(
    "line",
    [
        "##PROGRESS## 039 | Phase: execute | 0/5",
        "##PROGRESS## 039 | Phase: execute | 6/5",
        "##PROGRESS## 039 | Phase: execute | 1/0",
    ],
)
def test_parse_progress_line_rejects_invalid_phase_counts(line: str) -> None:
    with pytest.raises(ArtifactParseError, match="phase"):
        parse_progress_line(line)


def test_parse_resolution_json_builds_typed_constraints(repo_root: Path) -> None:
    fixture_path = repo_root / "tests" / "fixtures" / "tasks" / "resolution_minimal.json"

    resolution = parse_resolution_json(fixture_path.read_text(encoding="utf-8"), source=fixture_path)

    assert resolution.resolved_at == "2026-03-05T14:16:45Z"
    assert [task.task_id for task in resolution.tasks] == ["021d", "022", "039", "043"]
    task_039 = next(task for task in resolution.tasks if task.task_id == "039")
    assert task_039.depends_on == ("021d", "022")
    assert task_039.anti_affinity == ("043",)
    assert task_039.exec_order == 7
    assert resolution.groups[0].members == ("039", "043")
    assert resolution.notes == "Maximum parallelism: 2 workers"


def test_parse_resolution_json_strips_code_fences(repo_root: Path) -> None:
    fixture_path = repo_root / "tests" / "fixtures" / "tasks" / "resolution_minimal.json"
    raw_json = fixture_path.read_text(encoding="utf-8")
    fenced = f"```json\n{raw_json}\n```"

    resolution = parse_resolution_json(fenced, source=fixture_path)

    assert resolution.resolved_at == "2026-03-05T14:16:45Z"
    assert [task.task_id for task in resolution.tasks] == ["021d", "022", "039", "043"]


@pytest.mark.parametrize(
    ("parser_name", "content"),
    [
        (
            "plan",
            "---\nDEPENDS_ON: none\nEXEC_ORDER: 1\n---\n\n# Missing plan id\n",
        ),
        (
            "status",
            "STATUS: blocked\nCOMMITS: none\nTEST_RESULT: skip\n",
        ),
        (
            "progress",
            "##PROGRESS## 039 | Phase: execute | three/five",
        ),
        (
            "resolution",
            "{\"tasks\": [{\"task_id\": \"039\", \"depends_on\": \"043\"}]}",
        ),
    ],
)
def test_parsers_fail_with_explicit_typed_errors(parser_name: str, content: str) -> None:
    with pytest.raises(ArtifactParseError):
        if parser_name == "plan":
            parse_task_plan(content)
        elif parser_name == "status":
            parse_status_sidecar(content)
        elif parser_name == "progress":
            parse_progress_line(content)
        else:
            parse_resolution_json(content)


def test_plan_list_constraint_errors_are_reported_as_plan_errors() -> None:
    with pytest.raises(ArtifactParseError, match=r"^plan: DEPENDS_ON entries must be non-empty strings$"):
        parse_task_plan(
            "---\n"
            "PLAN_ID: 039\n"
            "DEPENDS_ON:\n"
            "  - 021d\n"
            "  - bad: entry\n"
            "EXEC_ORDER: 7\n"
            "---\n"
            "\n"
            "# Plan title\n"
        )


# --- extract_commit_description regression tests ---


def test_extract_commit_description_intro_paragraph() -> None:
    body = textwrap.dedent("""\
        # My Plan Title

        This is the intro paragraph describing the plan.
        It spans multiple lines.

        ## Step 1

        Some step content.
    """)
    result = extract_commit_description(body)
    assert result == "This is the intro paragraph describing the plan. It spans multiple lines."


def test_extract_commit_description_no_intro_jumps_to_section() -> None:
    body = textwrap.dedent("""\
        # My Plan Title

        ## Step 1

        Some step content.
    """)
    result = extract_commit_description(body)
    assert result == ""


def test_extract_commit_description_summary_section_fallback() -> None:
    body = textwrap.dedent("""\
        # My Plan Title

        ## Summary

        This comes from the summary section.

        ## Step 1

        Some step content.
    """)
    result = extract_commit_description(body)
    assert result == "This comes from the summary section."


def test_extract_commit_description_empty_body() -> None:
    assert extract_commit_description("") == ""


def test_extract_commit_description_truncation() -> None:
    long_intro = "x" * 600
    body = f"# Title\n\n{long_intro}\n\n## Step 1\n"
    result = extract_commit_description(body)
    assert len(result) == 503  # 500 chars + "..."
    assert result.endswith("...")


_PLAN_COMMIT_MSG_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "cognitive_switchyard"
    / "scripts"
    / "plan_commit_msg.py"
)

_MINIMAL_PLAN = textwrap.dedent("""\
    ---
    PLAN_ID: 042
    DEPENDS_ON: none
    ANTI_AFFINITY: none
    EXEC_ORDER: 1
    FULL_TEST_AFTER: no
    ---

    # Do the important thing

    This plan does the important thing deterministically.

    ## Operator Actions

    None.
""")


def test_plan_commit_msg_script(tmp_path: Path) -> None:
    plan_file = tmp_path / "042.plan.md"
    plan_file.write_text(_MINIMAL_PLAN, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(_PLAN_COMMIT_MSG_SCRIPT), str(plan_file), "042", "1"],
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout
    assert "feat: Do the important thing" in output
    assert "This plan does the important thing deterministically." in output
    assert "Task: 042 (slot 1)" in output


def test_plan_commit_msg_script_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.plan.md"

    result = subprocess.run(
        [sys.executable, str(_PLAN_COMMIT_MSG_SCRIPT), str(missing), "099", "3"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "feat: merge task 099 from slot 3"


def test_generate_commit_message_from_plan(tmp_path: Path) -> None:
    """_generate_commit_message produces a rich message from a valid plan file."""
    from cognitive_switchyard.orchestrator import _generate_commit_message

    plan_file = tmp_path / "042.plan.md"
    plan_file.write_text(_MINIMAL_PLAN, encoding="utf-8")

    msg = _generate_commit_message(plan_file, "042", 1)
    assert msg is not None
    assert "feat: Do the important thing" in msg
    assert "This plan does the important thing deterministically." in msg
    assert "Task: 042 (slot 1)" in msg


def test_generate_commit_message_returns_none_for_missing_file(tmp_path: Path) -> None:
    """_generate_commit_message returns None when the plan file doesn't exist."""
    from cognitive_switchyard.orchestrator import _generate_commit_message

    missing = tmp_path / "nonexistent.plan.md"
    assert _generate_commit_message(missing, "099", 3) is None


def test_generate_commit_message_returns_none_for_none_path() -> None:
    """_generate_commit_message returns None when plan_path is None."""
    from cognitive_switchyard.orchestrator import _generate_commit_message

    assert _generate_commit_message(None, "001", 0) is None
