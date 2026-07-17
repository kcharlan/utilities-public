#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def now() -> str:
    return time.strftime("%H:%M:%S")


def truncate(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(path)


def write_state(state_path: Path, event_type: str, summary: str, *, item_type: str = "") -> None:
    payload = {
        "timestamp": time.time(),
        "event_type": event_type,
        "item_type": item_type,
        "summary": summary,
    }
    write_json_atomic(state_path, payload)


def write_output(output_path: Path | None, text: str) -> None:
    if output_path is None:
        return
    output_path.write_text(text.rstrip() + "\n", encoding="utf-8")


def load_timeline(timeline_path: Path | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "raw_line_count": 0,
        "json_event_count": 0,
        "normalized_event_count": 0,
        "first_event_epoch": None,
        "first_command_started_epoch": None,
        "first_command_completed_epoch": None,
        "last_command_completed_epoch": None,
        "first_agent_message_epoch": None,
        "last_agent_message_epoch": None,
        "turn_completed_epoch": None,
        "last_event_epoch": None,
        "last_normalized_event_type": "",
        "last_normalized_item_type": "",
    }
    if timeline_path is None or not timeline_path.exists():
        return payload
    try:
        loaded = json.loads(timeline_path.read_text(encoding="utf-8"))
    except Exception:
        return payload
    if isinstance(loaded, dict):
        payload.update(loaded)
    return payload


def write_timeline(timeline_path: Path | None, timeline: dict[str, object]) -> None:
    if timeline_path is None:
        return
    write_json_atomic(timeline_path, timeline)


def note_timeline_event(
    timeline: dict[str, object],
    event_type: str,
    item_type: str,
    *,
    event_time: float,
) -> None:
    timeline["normalized_event_count"] = int(timeline.get("normalized_event_count", 0)) + 1
    if timeline.get("first_event_epoch") is None:
        timeline["first_event_epoch"] = event_time
    timeline["last_event_epoch"] = event_time
    timeline["last_normalized_event_type"] = event_type
    timeline["last_normalized_item_type"] = item_type

    if event_type == "item.started" and item_type == "command_execution":
        if timeline.get("first_command_started_epoch") is None:
            timeline["first_command_started_epoch"] = event_time
    elif event_type == "item.completed" and item_type == "command_execution":
        if timeline.get("first_command_completed_epoch") is None:
            timeline["first_command_completed_epoch"] = event_time
        timeline["last_command_completed_epoch"] = event_time
    elif event_type == "item.completed" and item_type == "agent_message":
        if timeline.get("first_agent_message_epoch") is None:
            timeline["first_agent_message_epoch"] = event_time
        timeline["last_agent_message_epoch"] = event_time
    elif event_type == "turn.completed":
        timeline["turn_completed_epoch"] = event_time


def assistant_text(message: dict) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    text_parts: list[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
    return "\n".join(text_parts).strip()


def has_tool_use(message: dict) -> bool:
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(part, dict) and part.get("type") == "tool_use" for part in content)


def has_tool_result(event: dict) -> bool:
    if isinstance(event.get("tool_use_result"), dict):
        return True
    message = event.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(part, dict) and part.get("type") == "tool_result" for part in content)


def codex_event_summary(event: dict) -> tuple[str, str, bool, str, str]:
    event_type = str(event.get("type", "unknown"))

    if event_type == "thread.started":
        return event_type, "session started", True, "", ""

    if event_type == "turn.started":
        return event_type, "turn started", True, "", ""

    if event_type == "turn.completed":
        usage = event.get("usage", {})
        summary = (
            f"turn completed; input_tokens={usage.get('input_tokens', 0)} "
            f"output_tokens={usage.get('output_tokens', 0)}"
        )
        return event_type, summary, True, "", ""

    if event_type in {"item.started", "item.completed"}:
        item = event.get("item", {})
        item_type = str(item.get("type", "unknown"))
        if item_type == "agent_message":
            text = truncate(str(item.get("text", "agent message")))
            output_text = str(item.get("text", "")).strip()
            return event_type, text, True, item_type, output_text
        return event_type, f"{event_type.replace('.', ' ')}: {item_type}", False, item_type, ""

    if event_type == "error":
        return event_type, truncate(json.dumps(event)), True, "", ""

    return event_type, event_type, False, "", ""


def claude_event_summary(event: dict) -> tuple[str, str, bool, str, str]:
    event_type = str(event.get("type", "unknown"))

    if event_type == "system" and event.get("subtype") == "init":
        return "thread.started", "session started", True, "", ""

    if event_type == "assistant":
        message = event.get("message", {})
        if not isinstance(message, dict):
            return "assistant", "assistant event", False, "", ""
        if has_tool_use(message):
            return "item.started", "item started: command_execution", False, "command_execution", ""
        text = assistant_text(message)
        if text:
            return "item.completed", truncate(text), True, "agent_message", text
        return "assistant", "assistant event", False, "", ""

    if event_type == "user" and has_tool_result(event):
        return "item.completed", "item completed: command_execution", False, "command_execution", ""

    if event_type == "result":
        usage = event.get("usage", {})
        summary = (
            f"turn completed; input_tokens={usage.get('input_tokens', 0)} "
            f"output_tokens={usage.get('output_tokens', 0)}"
        )
        output_text = str(event.get("result", "")).strip()
        return "turn.completed", summary, True, "", output_text

    if event_type == "error":
        return "error", truncate(json.dumps(event)), True, "", ""

    return event_type, event_type, False, "", ""


def event_summary(cli_family: str, event: dict) -> tuple[str, str, bool, str, str]:
    if cli_family == "claude":
        return claude_event_summary(event)
    return codex_event_summary(event)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--cli-family", choices=("codex", "claude"), default="codex")
    parser.add_argument("--output-file")
    parser.add_argument("--timeline-file")
    args = parser.parse_args()

    state_path = Path(args.state_file)
    output_path = Path(args.output_file) if args.output_file else None
    timeline_path = Path(args.timeline_file) if args.timeline_file else None
    timeline = load_timeline(timeline_path)

    for raw_line in sys.stdin:
        timeline["raw_line_count"] = int(timeline.get("raw_line_count", 0)) + 1
        line = raw_line.rstrip("\n")
        if not line.strip():
            write_timeline(timeline_path, timeline)
            continue

        event_time = time.time()

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            summary = truncate(line)
            write_state(state_path, "raw", summary)
            timeline["last_event_epoch"] = event_time
            timeline["last_normalized_event_type"] = "raw"
            timeline["last_normalized_item_type"] = ""
            write_timeline(timeline_path, timeline)
            print(f"[{now()}] {args.stage}: {summary}", flush=True)
            continue

        timeline["json_event_count"] = int(timeline.get("json_event_count", 0)) + 1
        normalized_type, summary, should_print, item_type, output_text = event_summary(
            args.cli_family, event
        )
        write_state(state_path, normalized_type, summary, item_type=item_type)
        note_timeline_event(timeline, normalized_type, item_type, event_time=event_time)
        write_timeline(timeline_path, timeline)
        if output_text:
            write_output(output_path, output_text)
        if should_print:
            print(f"[{now()}] {args.stage}: {summary}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
