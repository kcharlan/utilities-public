from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import yaml

from .models import (
    ProgressUpdate,
    ResolutionGraph,
    ResolutionGroup,
    ResolutionTask,
    StagedTaskPlan,
    TaskPlan,
    TaskStatus,
)

_LEADING_COMMENT_RE = re.compile(r"\A\s*<!--.*?-->\s*\n?", re.DOTALL)
_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```\w*\s*\n(.*?)\n\s*```", re.DOTALL)


class ArtifactParseError(ValueError):
    def __init__(self, artifact_type: str, message: str, source: Path | None = None) -> None:
        self.artifact_type = artifact_type
        self.source = source
        label = artifact_type if source is None else f"{artifact_type} ({source})"
        super().__init__(f"{label}: {message}")


def parse_task_plan(text: str, *, source: Path | None = None) -> TaskPlan:
    metadata, body, title = _parse_plan_document(text, source=source)

    return TaskPlan(
        task_id=_required_string(metadata, "PLAN_ID", artifact_type="plan", source=source),
        title=title,
        depends_on=_parse_id_list(metadata.get("DEPENDS_ON", "none"), field="DEPENDS_ON", source=source),
        anti_affinity=_parse_id_list(
            metadata.get("ANTI_AFFINITY", "none"),
            field="ANTI_AFFINITY",
            source=source,
        ),
        exec_order=_required_int(metadata, "EXEC_ORDER", artifact_type="plan", source=source),
        full_test_after=_parse_yes_no(
            metadata.get("FULL_TEST_AFTER", "no"),
            field="FULL_TEST_AFTER",
            source=source,
        ),
        body=body,
    )


def parse_staged_task_plan(text: str, *, source: Path | None = None) -> StagedTaskPlan:
    metadata, body, title = _parse_plan_document(text, source=source)
    normalized_metadata = {
        str(key).strip(): str(value).strip()
        for key, value in metadata.items()
    }
    return StagedTaskPlan(
        task_id=_required_string(normalized_metadata, "PLAN_ID", artifact_type="plan", source=source),
        title=title,
        metadata=normalized_metadata,
        declared_depends_on=_parse_id_list(
            normalized_metadata.get("DEPENDS_ON", "none"),
            field="DEPENDS_ON",
            source=source,
        ),
        full_test_after=_parse_yes_no(
            normalized_metadata.get("FULL_TEST_AFTER", "no"),
            field="FULL_TEST_AFTER",
            source=source,
        ),
        body=body,
    )


def parse_status_sidecar(
    text: str,
    *,
    source: Path | None = None,
    sidecar_format: str = "key-value",
) -> TaskStatus:
    mapping = _parse_status_mapping(text, source=source, sidecar_format=sidecar_format)

    status = _required_enum(
        mapping,
        "STATUS",
        ("done", "blocked"),
        artifact_type="status",
        source=source,
    )
    commits = _parse_commits(_required_string(mapping, "COMMITS", artifact_type="status", source=source))
    tests_ran_raw = _required_string(mapping, "TESTS_RAN", artifact_type="status", source=source)
    tests_ran = _normalize_tests_ran(tests_ran_raw, source)
    test_result = _required_enum(
        mapping,
        "TEST_RESULT",
        ("pass", "fail", "skip"),
        artifact_type="status",
        source=source,
    )
    blocked_reason = mapping.get("BLOCKED_REASON")
    notes = mapping.get("NOTES")

    if status == "blocked" and not blocked_reason:
        raise ArtifactParseError("status", "BLOCKED_REASON is required when STATUS is blocked", source)
    if status == "done" and blocked_reason:
        raise ArtifactParseError("status", "BLOCKED_REASON is only allowed when STATUS is blocked", source)

    return TaskStatus(
        status=status,
        commits=commits,
        tests_ran=tests_ran,
        test_result=test_result,
        blocked_reason=blocked_reason,
        notes=notes,
        tests_ran_raw=tests_ran_raw,
    )


def parse_progress_line(
    line: str,
    *,
    source: Path | None = None,
    progress_format: str = "##PROGRESS##",
) -> ProgressUpdate:
    phase_re, detail_re = _progress_patterns(progress_format, source)
    phase_match = phase_re.match(line)
    if phase_match:
        phase_index = int(phase_match.group("index"))
        phase_total = int(phase_match.group("total"))
        if phase_total < 1:
            raise ArtifactParseError("progress", "phase total must be at least 1", source)
        if phase_index < 1 or phase_index > phase_total:
            raise ArtifactParseError(
                "progress",
                "phase index must be between 1 and the phase total",
                source,
            )
        return ProgressUpdate(
            task_id=phase_match.group("task_id"),
            kind="phase",
            phase_name=phase_match.group("phase"),
            phase_index=phase_index,
            phase_total=phase_total,
        )

    detail_match = detail_re.match(line)
    if detail_match:
        return ProgressUpdate(
            task_id=detail_match.group("task_id"),
            kind="detail",
            detail_message=detail_match.group("detail"),
        )

    raise ArtifactParseError("progress", "line does not match the progress protocol", source)


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences (```json ... ```) that LLM agents sometimes wrap around JSON output."""
    match = _CODE_FENCE_RE.search(text)
    return match.group(1) if match else text


def _parse_status_mapping(
    text: str,
    *,
    source: Path | None,
    sidecar_format: str,
) -> dict[str, Any]:
    if sidecar_format == "key-value":
        return _parse_key_value_lines(text, artifact_type="status", source=source)
    if sidecar_format == "json":
        return _normalize_mapping_keys(
            _load_json_mapping(text, artifact_type="status", source=source)
        )
    if sidecar_format == "yaml":
        return _normalize_mapping_keys(
            _load_yaml_mapping(text, artifact_type="status", source=source)
        )
    raise ArtifactParseError("status", f"unsupported sidecar format: {sidecar_format}", source)


def _parse_plan_document(
    text: str,
    *,
    source: Path | None,
) -> tuple[dict[str, Any], str, str]:
    normalized_text = _LEADING_COMMENT_RE.sub("", text, count=1)
    match = _FRONT_MATTER_RE.match(normalized_text)
    if match is None:
        raise ArtifactParseError("plan", "missing YAML front matter", source)

    metadata = _load_yaml_mapping(match.group(1), artifact_type="plan", source=source)
    body = normalized_text[match.end() :].lstrip("\n")
    title = _extract_title(body, source)
    return metadata, body, title


def _progress_patterns(
    progress_format: str,
    source: Path | None,
) -> tuple[re.Pattern[str], re.Pattern[str]]:
    try:
        phase_re = re.compile(
            rf"^(?:{progress_format})\s+(?P<task_id>\S+)\s+\|\s+Phase:\s+(?P<phase>.+?)\s+\|\s+"
            rf"(?P<index>\d+)/(?P<total>\d+)\s*$"
        )
        detail_re = re.compile(
            rf"^(?:{progress_format})\s+(?P<task_id>\S+)\s+\|\s+Detail:\s+(?P<detail>.+?)\s*$"
        )
    except re.error as exc:
        raise ArtifactParseError(
            "progress",
            f"invalid progress format regex: {exc.msg}",
            source,
        ) from exc
    return phase_re, detail_re


def parse_resolution_json(text: str, *, source: Path | None = None) -> ResolutionGraph:
    text = _strip_code_fences(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArtifactParseError("resolution", f"invalid JSON: {exc.msg}", source) from exc

    if not isinstance(payload, dict):
        raise ArtifactParseError("resolution", "top-level JSON value must be an object", source)

    tasks_data = payload.get("tasks")
    if not isinstance(tasks_data, list):
        raise ArtifactParseError("resolution", "tasks must be a JSON array", source)

    tasks = tuple(_parse_resolution_task(item, source) for item in tasks_data)
    groups_data = payload.get("groups", [])
    if not isinstance(groups_data, list):
        raise ArtifactParseError("resolution", "groups must be a JSON array", source)

    groups = tuple(_parse_resolution_group(item, source) for item in groups_data)
    conflicts = _parse_string_list(
        payload.get("conflicts", []),
        field="conflicts",
        artifact_type="resolution",
        source=source,
    )
    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ArtifactParseError("resolution", "notes must be a string when present", source)

    resolved_at = payload.get("resolved_at")
    if resolved_at is not None and not isinstance(resolved_at, str):
        raise ArtifactParseError("resolution", "resolved_at must be a string when present", source)

    return ResolutionGraph(
        resolved_at=resolved_at,
        tasks=tasks,
        groups=groups,
        conflicts=conflicts,
        notes=notes,
    )


def extract_commit_description(body: str) -> str:
    """Extract a short description from a plan body for use in git commit messages.

    Returns the first non-empty paragraph after the title heading, or falls back
    to the first paragraph of a ## Summary or ## Overview section. Returns an
    empty string if nothing suitable is found. Truncates to 500 chars.
    """
    lines = body.splitlines()

    # Skip the title line (first "# " heading)
    title_skipped = False
    start_index = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title_skipped = True
            start_index = i + 1
            break

    if not title_skipped:
        start_index = 0

    # Collect intro paragraph: contiguous non-blank lines before first "## " or blank gap
    intro_lines: list[str] = []
    in_intro = False
    for line in lines[start_index:]:
        if line.startswith("## "):
            break
        stripped = line.rstrip()
        if stripped:
            in_intro = True
            intro_lines.append(stripped)
        elif in_intro:
            # Blank line after content — end of intro paragraph
            break

    if intro_lines:
        return _truncate_description(" ".join(intro_lines))

    # Fallback: look for ## Summary or ## Overview section
    in_section = False
    section_lines: list[str] = []
    section_started = False
    for line in lines:
        header = line.strip()
        if header in ("## Summary", "## Overview"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            stripped = line.rstrip()
            if stripped:
                section_started = True
                section_lines.append(stripped)
            elif section_started:
                break

    if section_lines:
        return _truncate_description(" ".join(section_lines))

    return ""


def _truncate_description(text: str, limit: int = 500) -> str:
    text = text.strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def extract_operator_actions_section(markdown: str) -> str | None:
    lines = markdown.splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == "## Operator Actions":
            start_index = index + 1
            break
    if start_index is None:
        return None

    collected: list[str] = []
    for line in lines[start_index:]:
        if line.startswith("## "):
            break
        collected.append(line)
    section = "\n".join(collected).strip()
    return section or None


def _parse_resolution_task(item: Any, source: Path | None) -> ResolutionTask:
    if not isinstance(item, dict):
        raise ArtifactParseError("resolution", "each task must be an object", source)
    return ResolutionTask(
        task_id=_required_string(item, "task_id", artifact_type="resolution", source=source),
        depends_on=_parse_string_list(
            item.get("depends_on", []),
            field="depends_on",
            artifact_type="resolution",
            source=source,
        ),
        anti_affinity=_parse_string_list(
            item.get("anti_affinity", []),
            field="anti_affinity",
            artifact_type="resolution",
            source=source,
        ),
        exec_order=_required_int(item, "exec_order", artifact_type="resolution", source=source),
    )


def _parse_resolution_group(item: Any, source: Path | None) -> ResolutionGroup:
    if not isinstance(item, dict):
        raise ArtifactParseError("resolution", "each group must be an object", source)
    return ResolutionGroup(
        name=_required_string(item, "name", artifact_type="resolution", source=source),
        type=_required_string(item, "type", artifact_type="resolution", source=source),
        members=_parse_string_list(
            item.get("members", []),
            field="members",
            artifact_type="resolution",
            source=source,
        ),
        shared_resources=_parse_string_list(
            item.get("shared_resources", []),
            field="shared_resources",
            artifact_type="resolution",
            source=source,
        ),
    )


def _sanitize_yaml_list_values(text: str) -> str:
    """Fix common LLM YAML mistakes like  KEY: "a", "b"  →  KEY: ["a", "b"]"""
    # Matches lines where the value looks like multiple quoted strings separated by commas
    # e.g.  ANTI_AFFINITY: "028", "029"  →  ANTI_AFFINITY: ["028", "029"]
    return re.sub(
        r'^(\s*\w+:\s*)("(?:[^"\\]|\\.)*"(?:\s*,\s*"(?:[^"\\]|\\.)*")+)\s*$',
        lambda m: m.group(1) + "[" + m.group(2) + "]",
        text,
        flags=re.MULTILINE,
    )


def _load_yaml_mapping(text: str, *, artifact_type: str, source: Path | None) -> dict[str, Any]:
    try:
        loaded = yaml.load(_sanitize_yaml_list_values(text), Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise ArtifactParseError(artifact_type, "invalid YAML metadata", source) from exc
    if not isinstance(loaded, dict):
        raise ArtifactParseError(artifact_type, "metadata must be a mapping", source)
    return loaded


def _load_json_mapping(text: str, *, artifact_type: str, source: Path | None) -> dict[str, Any]:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArtifactParseError(artifact_type, f"invalid JSON: {exc.msg}", source) from exc
    if not isinstance(loaded, dict):
        raise ArtifactParseError(artifact_type, "top-level JSON value must be an object", source)
    return loaded


def _normalize_mapping_keys(mapping: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(key, str):
            normalized[key.strip().upper()] = value
        else:
            normalized[str(key).strip().upper()] = value
    return normalized


def _extract_title(body: str, source: Path | None) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            return title.removeprefix("Plan: ").strip()
    raise ArtifactParseError("plan", "missing top-level title heading", source)


def _parse_key_value_lines(text: str, *, artifact_type: str, source: Path | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ArtifactParseError(artifact_type, f"invalid key-value line: {raw_line!r}", source)
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def _required_string(
    mapping: dict[str, Any], key: str, *, artifact_type: str, source: Path | None
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ArtifactParseError(artifact_type, f"{key} must be a non-empty string", source)
    return value.strip()


def _required_int(
    mapping: dict[str, Any], key: str, *, artifact_type: str, source: Path | None
) -> int:
    value = mapping.get(key)
    if isinstance(value, bool):
        raise ArtifactParseError(artifact_type, f"{key} must be an integer", source)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ArtifactParseError(artifact_type, f"{key} must be an integer", source)


def _required_enum(
    mapping: dict[str, Any],
    key: str,
    allowed: tuple[str, ...],
    *,
    artifact_type: str,
    source: Path | None,
) -> str:
    value = _required_string(mapping, key, artifact_type=artifact_type, source=source).lower()
    if value not in allowed:
        joined = ", ".join(allowed)
        raise ArtifactParseError(artifact_type, f"{key} must be one of: {joined}", source)
    return value


def _parse_yes_no(value: Any, *, field: str, source: Path | None) -> bool:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ArtifactParseError("plan", f"{field} must be 'yes' or 'no'", source)
    normalized = value.strip().lower()
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    raise ArtifactParseError("plan", f"{field} must be 'yes' or 'no'", source)


def _parse_id_list(value: Any, *, field: str, source: Path | None) -> tuple[str, ...]:
    if isinstance(value, list):
        return _parse_string_list(value, field=field, artifact_type="plan", source=source)
    if not isinstance(value, str):
        raise ArtifactParseError("plan", f"{field} must be a string or list", source)
    normalized = value.strip()
    if normalized.lower() == "none":
        return ()
    return tuple(item.strip() for item in normalized.split(",") if item.strip())


def _parse_string_list(
    value: Any,
    *,
    field: str,
    artifact_type: str,
    source: Path | None,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        message = f"{field} must be a JSON array" if artifact_type == "resolution" else f"{field} must be a list"
        raise ArtifactParseError(artifact_type, message, source)
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ArtifactParseError(
                artifact_type,
                f"{field} entries must be non-empty strings",
                source,
            )
        items.append(item.strip())
    return tuple(items)


def _parse_commits(value: str) -> tuple[str, ...]:
    if value.lower() == "none":
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _normalize_tests_ran(value: str, source: Path | None) -> str:
    normalized = value.strip().lower()
    if normalized == "none":
        return "none"
    if normalized.startswith("targeted"):
        return "targeted"
    if normalized.startswith("full"):
        return "full"
    raise ArtifactParseError("status", "TESTS_RAN must start with targeted, full, or be none", source)
