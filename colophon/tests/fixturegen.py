"""Deterministic, conspicuously synthetic Codex data for isolated test homes.

All writers use only the caller's root. Log methods append one record and return
self. ``at`` overrides the record's epoch-millisecond timestamp; the automatic
clock advances at least one millisecond per record and never rewinds. Extra keyword arguments
replace payload fields, or item fields for structured-item methods.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict
from uuid import UUID

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
SYNTHETIC_CWD = "/synthetic/projects/alpha"
SYNTHETIC_MODEL = "gpt-synthetic-1"
TOKEN_KEYS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
)
THREAD_COLUMNS = (
    "id", "name", "title", "cwd", "git_branch", "git_origin_url", "git_sha",
    "source", "originator", "archived", "first_user_message", "agent_nickname",
    "agent_role", "agent_path", "rollout_path",
)


def uuid7(at_ms: int, seq: int = 0) -> str:
    """Encode a timestamp and deterministic 74-bit sequence in a UUIDv7."""
    if not 0 <= at_ms < 2**48 or not 0 <= seq < 2**74:
        raise ValueError("UUIDv7 timestamp or sequence is out of range")
    return str(UUID(int=(at_ms << 80) | (7 << 76) | ((seq >> 62) << 64)
                    | (2 << 62) | (seq & (2**62 - 1))))


def iso(ms: int) -> str:
    """Format exact UTC milliseconds, including pre-epoch timestamps."""
    return (EPOCH + timedelta(milliseconds=ms)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _usage(value: dict | None) -> dict:
    return {**dict.fromkeys(TOKEN_KEYS, 0), **(value or {})}


class TraceRow(TypedDict, total=False):
    id: int
    ts: int | str
    ts_nanos: int
    level: str
    target: str
    feedback_log_body: str
    thread_id: str | None


class CodexHome:
    """Write logs and auxiliary databases beneath a supplied temporary root."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._sequence = 0

    def log(self, session_id: str | None = None, *, archived: bool = False,
            day: str = "2030-01-07", name: str | None = None) -> LogBuilder:
        instant = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        at_ms = int((instant - EPOCH).total_seconds()) * 1000
        if session_id is None:
            session_id = uuid7(at_ms, self._sequence)
            self._sequence += 1
        directory = self.root / ("archived_sessions" if archived else "sessions")
        directory = directory / instant.strftime("%Y/%m/%d")
        filename = name or f"rollout-{day}T00-00-00-{session_id}.jsonl"
        if Path(filename).name != filename or filename in (".", ".."):
            raise ValueError("A synthetic log name must be a filename within its home")
        return LogBuilder(directory / filename, session_id, at_ms)

    def state_db(self, threads: list[dict], *, version: int = 5,
                 spawn_edges: list[tuple[str, str]] | None = None) -> Path:
        """Edges are (parent, child); omitted edges omit the optional table."""
        path = self.root / f"state_{version}.sqlite"
        with closing(sqlite3.connect(path)) as db, db:
            columns = ",".join(f'{name} {"INTEGER" if name == "archived" else "TEXT"}' for name in THREAD_COLUMNS)
            db.execute(f"CREATE TABLE threads ({columns})")
            placeholders = ",".join("?" for _ in THREAD_COLUMNS)
            db.executemany(f"INSERT INTO threads VALUES ({placeholders})",
                           [tuple(row.get(name) for name in THREAD_COLUMNS) for row in threads])
            if spawn_edges is not None:
                db.execute("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT)")
                db.executemany("INSERT INTO thread_spawn_edges VALUES (?,?)", spawn_edges)
        return path

    def scaling_corpus(self, sessions: int) -> None:
        """Forty-turn own sessions, each with one equally shaped subagent.

        Every turn has token_count, request, shell item and final answer;
        alternating turns also have primary usage, exercising both retained
        accounting paths rather than replacing all fallback usage.
        """
        for index in range(sessions):
            parent = f"synthetic-scaling-session-{index:06d}"
            child = f"synthetic-scaling-agent-{index:06d}"
            for identifier, is_child in ((parent, False), (child, True)):
                meta = {"parent_thread_id": parent, "agent_nickname": "Agent-Alpha"} if is_child else {}
                log = self.log(identifier).meta(**meta)
                for turn in range(40):
                    log.task_started(f"{identifier}-turn-{turn:02d}").turn_context(model="gpt-5.4")
                    log.user_item(f"Synthetic request {turn + 1}").command()
                    if turn == 0 and not is_child:
                        log.subagent_activity(child)
                    counts = {"input_tokens": 100, "cached_input_tokens": 20,
                              "output_tokens": 10, "reasoning_output_tokens": 2,
                              "total_tokens": 110}
                    log.token_count(last=counts, total={key: value * (turn + 1) for key, value in counts.items()})
                    if turn % 2 == 0:
                        log.usage_record(usage=counts)
                    log.agent_item().task_complete()
                log.write(mtime=1)

    def session_index(self, entries: list[dict]) -> Path:
        path = self.root / "session_index.jsonl"
        path.write_text("".join(_json(entry) + "\n" for entry in entries), encoding="utf-8")
        return path

    def global_state(self, titles: dict[str, str]) -> Path:
        path = self.root / ".codex-global-state.json"
        path.write_text(_json({"thread-titles": {"titles": titles}}) + "\n", encoding="utf-8")
        return path

    def trace_db(self, rows: list[TraceRow]) -> Path:
        path = self.root / "logs_2.sqlite"
        columns = ("id", "ts", "ts_nanos", "level", "target", "feedback_log_body", "thread_id")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY, ts INTEGER, ts_nanos INTEGER, level TEXT, target TEXT, feedback_log_body TEXT, thread_id TEXT)")
            for n, row in enumerate(rows, 1):
                defaults = {"id": n, "ts": 0, "ts_nanos": 0, "level": "TRACE", "target": "synthetic_codex", "thread_id": None}
                values = {**defaults, **row}
                db.execute("INSERT INTO logs VALUES (?,?,?,?,?,?,?)", tuple(values.get(key) for key in columns))
        return path

    # Exact textual markers consumed by pinned 3bbf6bc48's
    # CostUsageScanner+CodexPriority.swift:1020–1098. No upstream runtime needed.
    def priority_request_row(self, turn_id: str, *, thread_id: str,
                             model: str, ts: int | str) -> TraceRow:
        body = f"synthetic turn.id={turn_id} thread_id={thread_id} websocket request: "
        body += _json({"type": "response.create", "service_tier": "priority", "model": model})
        return {"ts": ts, "thread_id": thread_id, "feedback_log_body": body}

    def submission_priority_row(self, turn_id: str, *, thread_id: str,
                                ts: int | str) -> TraceRow:
        body = f'synthetic thread_id={thread_id} Submission sub=Submission {{ id: "{turn_id}", service_tier: Some(Some("priority")) }}'
        return {"ts": ts, "thread_id": thread_id, "feedback_log_body": body}

    def completed_row(self, turn_id: str, model: str, ts: int | str) -> TraceRow:
        body = f"synthetic turn.id={turn_id} websocket event: "
        body += _json({"type": "response.completed", "response": {"model": model}})
        return {"ts": ts, "feedback_log_body": body}


class LogBuilder:
    """Chainable JSONL records; defaults are synthetic and deterministic."""

    def __init__(self, path: Path, session_id: str, at_ms: int):
        self.path = path
        self.session_id = session_id
        self.clock = at_ms
        self.ordinal = 0
        self.turn_id = "synthetic-turn-1"
        self.call_id = "synthetic-call-1"
        self._lines: list[bytes] = []

    def _emit(self, record_type: str | None, payload: dict, *, at: int | None = None,
              top: dict | None = None) -> LogBuilder:
        instant = self.clock if at is None else at
        record = {"timestamp": iso(instant), "ordinal": self.ordinal}
        if record_type is None:
            record.update(payload)
        else:
            record.update(type=record_type, payload=payload)
        if top:
            record.update(top)
        self._lines.append((_json(record) + "\n").encode("utf-8"))
        self.clock = max(self.clock, instant) + 1
        self.ordinal += 1
        return self

    def _event(self, kind: str, fields: dict, *, at: int | None = None) -> LogBuilder:
        return self._emit("event_msg", {"type": kind, **fields}, at=at)

    def _response(self, kind: str, fields: dict, *, at: int | None = None) -> LogBuilder:
        return self._emit("response_item", {"type": kind, **fields}, at=at)

    def _item(self, kind: str, fields: dict, *, at: int | None = None,
              turn_id: str | None = None, thread_id: str | None = None,
              completed_at_ms: int | None = None) -> LogBuilder:
        instant = self.clock if at is None else at
        return self._event("item_completed", {
            "thread_id": self.session_id if thread_id is None else thread_id,
            "turn_id": self.turn_id if turn_id is None else turn_id,
            "completed_at_ms": instant if completed_at_ms is None else completed_at_ms,
            "item": {"type": kind, "id": f"synthetic-item-{self.ordinal}", **fields},
        }, at=at)

    def meta(self, *, at: int | None = None, **fields) -> LogBuilder:
        payload = {
            "id": self.session_id, "session_id": self.session_id,
            "timestamp": iso(self.clock if at is None else at), "cwd": SYNTHETIC_CWD,
            "originator": "Codex Desktop", "cli_version": "0.0.0-synthetic",
            "model_provider": "openai", "history_mode": "full", "thread_source": "user",
            "base_instructions": {"text": "Synthetic instructions."},
            "git": {"branch": "main", "commit_hash": "0000000", "repository_url": "https://example.invalid/synthetic/alpha.git"},
            "source": "vscode",
        }
        if fields.get("parent_thread_id"):
            payload["source"] = {"subagent": {"thread_spawn": {
                "parent_thread_id": fields["parent_thread_id"], "depth": fields.get("depth", 1),
                "agent_path": fields.get("agent_path", "/root/code_review"),
                "agent_nickname": fields.get("agent_nickname", "Agent-Alpha"),
                "agent_role": fields.get("agent_role"),
            }}}
        return self._emit("session_meta", {**payload, **fields}, at=at)

    def turn_context(self, turn_id: str | None = None, *, model: str = SYNTHETIC_MODEL,
                     at: int | None = None, **fields) -> LogBuilder:
        if turn_id is not None:
            self.turn_id = turn_id
        return self._emit("turn_context", {
            "turn_id": self.turn_id, "cwd": SYNTHETIC_CWD, "model": model,
            "effort": "medium", "summary": "auto",
            "collaboration_mode": {"mode": "default", "settings": {"model": model}}, **fields,
        }, at=at)

    def task_started(self, turn_id: str | None = None, *, at: int | None = None, **fields) -> LogBuilder:
        if turn_id is not None:
            self.turn_id = turn_id
        instant = self.clock if at is None else at
        return self._event("task_started", {"turn_id": self.turn_id, "started_at": instant / 1000,
            "collaboration_mode_kind": "default", "model_context_window": 272000, **fields}, at=at)

    def task_complete(self, turn_id: str | None = None, *, at: int | None = None, **fields) -> LogBuilder:
        instant = self.clock if at is None else at
        return self._event("task_complete", {"turn_id": self.turn_id if turn_id is None else turn_id,
            "completed_at": instant / 1000, "last_agent_message": "Synthetic final answer.", **fields}, at=at)

    def turn_aborted(self, turn_id: str | None = None, *, at: int | None = None, **fields) -> LogBuilder:
        instant = self.clock if at is None else at
        return self._event("turn_aborted", {"turn_id": self.turn_id if turn_id is None else turn_id,
            "completed_at": instant / 1000, "duration_ms": 0, "reason": "interrupted", **fields}, at=at)

    def thread_settings(self, *, model: str = SYNTHETIC_MODEL, cwd: str = SYNTHETIC_CWD,
                        service_tier: str | None = None, at: int | None = None, **fields) -> LogBuilder:
        settings = {"model": model, "cwd": cwd}
        if service_tier is not None:
            settings["service_tier"] = service_tier
        return self._event("thread_settings_applied", {"thread_settings": settings, **fields}, at=at)

    def user_item(self, text: str = "Synthetic request 1", *, images: list[str] | None = None,
                  at: int | None = None, turn_id: str | None = None, thread_id: str | None = None,
                  completed_at_ms: int | None = None, **fields) -> LogBuilder:
        content = [{"type": "text", "text": text, "text_elements": []}]
        content.extend({"type": "local_image", "path": path} for path in images or [])
        return self._item("UserMessage", {"content": content, **fields}, at=at,
                          turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def agent_item(self, text: str = "Synthetic final answer.", *, phase: str = "final_answer",
                   at: int | None = None, turn_id: str | None = None, thread_id: str | None = None,
                   completed_at_ms: int | None = None, **fields) -> LogBuilder:
        return self._item("AgentMessage", {"phase": phase, "content": [{"type": "Text", "text": text}], **fields},
                          at=at, turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def user_response(self, text: str = "Synthetic request 1", *, role: str = "user",
                      images: int = 0, turn_id: str | None = None, at: int | None = None, **fields) -> LogBuilder:
        content = [{"type": "input_text", "text": text}]
        content.extend({"type": "input_image", "image_url": "data:,"} for _ in range(images))
        return self._response("message", {"role": role, "content": content,
            "internal_chat_message_metadata_passthrough": {"turn_id": self.turn_id if turn_id is None else turn_id}, **fields}, at=at)

    def agent_response(self, text: str = "Synthetic final answer.", *, phase: str = "final_answer",
                       turn_id: str | None = None, at: int | None = None, **fields) -> LogBuilder:
        return self._response("message", {"role": "assistant", "phase": phase,
            "content": [{"type": "output_text", "text": text}],
            "internal_chat_message_metadata_passthrough": {"turn_id": self.turn_id if turn_id is None else turn_id}, **fields}, at=at)

    def user_event_legacy(self, text: str = "Synthetic request 1", *, at: int | None = None, **fields) -> LogBuilder:
        return self._event("user_message", {"message": text, **fields}, at=at)

    def agent_event_legacy(self, text: str = "Synthetic final answer.", *, phase: str = "final_answer",
                           at: int | None = None, **fields) -> LogBuilder:
        return self._event("agent_message", {"message": text, "phase": phase, **fields}, at=at)

    def command(self, *, at: int | None = None, turn_id: str | None = None,
                thread_id: str | None = None, completed_at_ms: int | None = None, **fields) -> LogBuilder:
        return self._item("CommandExecution", {"command": ["/bin/zsh", "-lc", "ls"], "cwd": SYNTHETIC_CWD,
            "exit_code": 0, "status": "completed", "aggregated_output": "", "stdout": "", "stderr": "",
            "duration": {"secs": 0, "nanos": 0}, "source": "unified_exec_startup", "process_id": "1", "parsed_cmd": [], **fields},
            at=at, turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def file_change(self, *, at: int | None = None, turn_id: str | None = None,
                    thread_id: str | None = None, completed_at_ms: int | None = None, **fields) -> LogBuilder:
        return self._item("FileChange", {"status": "completed", "changes": {
            f"{SYNTHETIC_CWD}/a.txt": {"type": "add", "content": "Synthetic file."},
            f"{SYNTHETIC_CWD}/b.txt": {"type": "delete", "content": "Synthetic file."}}, "stdout": "", **fields},
            at=at, turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def mcp(self, *, at: int | None = None, turn_id: str | None = None,
            thread_id: str | None = None, completed_at_ms: int | None = None, **fields) -> LogBuilder:
        return self._item("McpToolCall", {"server": "synthetic_server", "tool": "lookup", "arguments": {},
            "result": {"content": []}, "status": "completed", "duration": {"secs": 0, "nanos": 0}, **fields},
            at=at, turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def web_search(self, *, at: int | None = None, turn_id: str | None = None,
                   thread_id: str | None = None, completed_at_ms: int | None = None, **fields) -> LogBuilder:
        return self._item("WebSearch", {"query": "synthetic", "action": {"type": "search"}, **fields},
            at=at, turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def extension(self, kind: str = "web.search", *, at: int | None = None, turn_id: str | None = None,
                  thread_id: str | None = None, completed_at_ms: int | None = None, **fields) -> LogBuilder:
        return self._item("Extension", {"kind": kind, **fields},
            at=at, turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def image_view(self, *, at: int | None = None, turn_id: str | None = None,
                   thread_id: str | None = None, completed_at_ms: int | None = None, **fields) -> LogBuilder:
        return self._item("ImageView", {"path": "/synthetic/a.png", **fields},
            at=at, turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def subagent_activity(self, agent_thread_id: str = "synthetic-agent", *, kind: str = "started",
                          at: int | None = None, turn_id: str | None = None, thread_id: str | None = None,
                          completed_at_ms: int | None = None, **fields) -> LogBuilder:
        return self._item("SubAgentActivity", {"kind": kind, "agent_thread_id": agent_thread_id, "agent_path": "/root/code_review", **fields},
            at=at, turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def collab_wait(self, receiver_thread_ids: list[str] | None = None, *, at: int | None = None,
                    turn_id: str | None = None, thread_id: str | None = None,
                    completed_at_ms: int | None = None, **fields) -> LogBuilder:
        return self._item("CollabAgentToolCall", {"tool": "wait", "status": "completed",
            "sender_thread_id": self.session_id, "receiver_thread_ids": ["synthetic-agent"] if receiver_thread_ids is None else receiver_thread_ids,
            "receiver_agents": [], "agents_states": {}, **fields},
            at=at, turn_id=turn_id, thread_id=thread_id, completed_at_ms=completed_at_ms)

    def function_call(self, name: str = "exec_command", *, arguments: dict | str | None = None,
                      call_id: str | None = None, namespace: str | None = None,
                      turn_id: str | None = None, at: int | None = None, **fields) -> LogBuilder:
        self.call_id = call_id if call_id is not None else f"synthetic-call-{self.ordinal}"
        payload = {"name": name, "arguments": arguments if isinstance(arguments, str) else _json({"cmd": "ls"} if arguments is None else arguments),
            "call_id": self.call_id, "internal_chat_message_metadata_passthrough": {"turn_id": self.turn_id if turn_id is None else turn_id}}
        if namespace is not None:
            payload["namespace"] = namespace
        return self._response("function_call", {**payload, **fields}, at=at)

    def function_output(self, *, output: dict | str | None = None, call_id: str | None = None,
                        at: int | None = None, **fields) -> LogBuilder:
        return self._response("function_call_output", {"call_id": self.call_id if call_id is None else call_id,
            "output": output if isinstance(output, str) else _json({"task_name": "/root/code_review"} if output is None else output), **fields}, at=at)

    def custom_tool_call(self, name: str = "exec", *, input: str = "Synthetic tool input.",
                         call_id: str | None = None, at: int | None = None, **fields) -> LogBuilder:
        self.call_id = call_id if call_id is not None else f"synthetic-call-{self.ordinal}"
        return self._response("custom_tool_call", {"name": name, "input": input, "call_id": self.call_id, "status": "completed", **fields}, at=at)

    def web_search_call(self, *, at: int | None = None, **fields) -> LogBuilder:
        return self._response("web_search_call", {"action": {"type": "search", "query": "synthetic"}, **fields}, at=at)

    def local_shell_call(self, *, at: int | None = None, **fields) -> LogBuilder:
        return self._response("local_shell_call", {"action": {"type": "exec", "command": ["ls"], "cwd": SYNTHETIC_CWD}, **fields}, at=at)

    def tool_search_call(self, *, at: int | None = None, **fields) -> LogBuilder:
        return self._response("tool_search_call", {"arguments": _json({"query": "synthetic"}), **fields}, at=at)

    def reasoning(self, *, at: int | None = None, **fields) -> LogBuilder:
        return self._response("reasoning", {"summary": [{"type": "summary_text", "text": "Synthetic reasoning."}], **fields}, at=at)

    def token_count(self, *, total: dict | None = None, last: dict | None = None,
                    model: str | None = None, info_model: str | None = None,
                    top_model: str | None = None, at: int | None = None, **fields) -> LogBuilder:
        info = {"total_token_usage": _usage(total), "last_token_usage": _usage(last), "model_context_window": 272000}
        if info_model is not None:
            info["model"] = info_model
        payload = {"type": "token_count", "info": info, "rate_limits": {}, **fields}
        if model is not None:
            payload["model"] = model
        return self._emit("event_msg", payload, at=at, top={"model": top_model} if top_model is not None else None)

    def usage_record(self, *, usage: dict | None = None, turn_id: str | None = None,
                     thread_id: str | None = None, at: int | None = None, **fields) -> LogBuilder:
        counts = _usage(usage)
        turn = self.turn_id if turn_id is None else turn_id
        return self._emit("token_usage_record", {"response_id": f"synthetic-response-{self.ordinal}",
            "thread_id": self.session_id if thread_id is None else thread_id, "session_id": self.session_id,
            "turn_id": turn, "root_turn_id": turn, "usage": counts.copy(), "turn_token_usage": counts.copy(),
            "thread_token_usage": counts.copy(), **fields}, at=at)

    def bare_usage(self, *, usage: dict | None = None, at: int | None = None, **fields) -> LogBuilder:
        return self._emit(None, {"usage": _usage(usage), **fields}, at=at)

    def realtime_segment(self, text: str = "Synthetic voice request.", *, role: str = "user",
                         at: int | None = None, **fields) -> LogBuilder:
        return self._emit("realtime_item", {"type": "transcript_segment", "id": f"synthetic-segment-{self.ordinal}",
            "realtime_session_id": "synthetic-realtime", "role": role, "text": text, **fields}, at=at)

    def inter_agent(self, *, at: int | None = None, **fields) -> LogBuilder:
        return self._emit("inter_agent_communication_metadata", {"trigger_turn": True, **fields}, at=at)

    def agent_message_ia(self, *, at: int | None = None, **fields) -> LogBuilder:
        return self._response("agent_message", {"author": "synthetic-agent", "recipient": "synthetic-parent",
            "content": [{"type": "encrypted_content", "encrypted_content": "c3ludGhldGlj"}], **fields}, at=at)

    def world_state(self, *, at: int | None = None, **fields) -> LogBuilder:
        return self._emit("world_state", fields, at=at)

    def compacted(self, *, at: int | None = None, **fields) -> LogBuilder:
        return self._emit("compacted", fields, at=at)

    def unknown(self, record_type: str = "synthetic_unknown", *, at: int | None = None, **fields) -> LogBuilder:
        return self._emit(record_type, fields, at=at)

    def raw(self, line: bytes) -> LogBuilder:
        """Append bytes exactly, for malformed, glued or unterminated records."""
        self._lines.append(line)
        return self

    def write(self, *, partial_tail: bytes | None = None, mtime: float | None = None) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"".join(self._lines) + (partial_tail or b""))
        if mtime is not None:
            os.utime(self.path, (mtime, mtime))
        return self.path
