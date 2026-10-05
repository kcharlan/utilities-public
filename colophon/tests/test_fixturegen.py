"""Contract checks for our synthetic Codex homes, independent of live data."""

import importlib
import importlib.util
import json
import sqlite3
from contextlib import closing
from uuid import UUID

import pytest


def load_generator():
    assert importlib.util.find_spec("fixturegen") is not None, "synthetic generator is not implemented"
    return importlib.import_module("fixturegen")


# Required payload keys from Task 2's binding record templates.
CASES = [
    ("meta", "session_meta", None, {"id", "session_id", "timestamp", "cwd", "originator", "cli_version", "model_provider", "history_mode", "thread_source", "base_instructions", "git", "source"}),
    ("turn_context", "turn_context", None, {"turn_id", "cwd", "model", "effort", "summary", "collaboration_mode"}),
    ("task_started", "event_msg", "task_started", {"turn_id", "started_at", "collaboration_mode_kind", "model_context_window"}),
    ("task_complete", "event_msg", "task_complete", {"turn_id", "completed_at", "last_agent_message"}),
    ("turn_aborted", "event_msg", "turn_aborted", {"turn_id", "completed_at", "duration_ms", "reason"}),
    ("thread_settings", "event_msg", "thread_settings_applied", {"thread_settings"}),
    ("user_item", "event_msg", "item_completed", {"thread_id", "turn_id", "completed_at_ms", "item"}),
    ("agent_item", "event_msg", "item_completed", {"thread_id", "turn_id", "completed_at_ms", "item"}),
    ("user_response", "response_item", "message", {"role", "content", "internal_chat_message_metadata_passthrough"}),
    ("agent_response", "response_item", "message", {"role", "phase", "content", "internal_chat_message_metadata_passthrough"}),
    ("user_event_legacy", "event_msg", "user_message", {"message"}),
    ("agent_event_legacy", "event_msg", "agent_message", {"message", "phase"}),
    ("command", "event_msg", "item_completed", {"item"}),
    ("file_change", "event_msg", "item_completed", {"item"}),
    ("mcp", "event_msg", "item_completed", {"item"}),
    ("web_search", "event_msg", "item_completed", {"item"}),
    ("extension", "event_msg", "item_completed", {"item"}),
    ("image_view", "event_msg", "item_completed", {"item"}),
    ("subagent_activity", "event_msg", "item_completed", {"item"}),
    ("collab_wait", "event_msg", "item_completed", {"item"}),
    ("function_call", "response_item", "function_call", {"name", "arguments", "call_id", "internal_chat_message_metadata_passthrough"}),
    ("function_output", "response_item", "function_call_output", {"call_id", "output"}),
    ("custom_tool_call", "response_item", "custom_tool_call", {"name", "input", "call_id", "status"}),
    ("web_search_call", "response_item", "web_search_call", {"action"}),
    ("local_shell_call", "response_item", "local_shell_call", {"action"}),
    ("tool_search_call", "response_item", "tool_search_call", {"arguments"}),
    ("reasoning", "response_item", "reasoning", {"summary"}),
    ("token_count", "event_msg", "token_count", {"info", "rate_limits"}),
    ("usage_record", "token_usage_record", None, {"response_id", "thread_id", "session_id", "turn_id", "root_turn_id", "usage", "turn_token_usage", "thread_token_usage"}),
    ("bare_usage", None, None, {"usage"}),
    ("realtime_segment", "realtime_item", "transcript_segment", {"id", "realtime_session_id", "role", "text"}),
    ("inter_agent", "inter_agent_communication_metadata", None, {"trigger_turn"}),
    ("agent_message_ia", "response_item", "agent_message", {"author", "recipient", "content"}),
    ("world_state", "world_state", None, set()),
    ("compacted", "compacted", None, set()),
    ("unknown", "synthetic_unknown", None, set()),
]


@pytest.mark.parametrize("method,top_type,payload_type,keys", CASES)
def test_each_builder_emits_template(tmp_path, method, top_type, payload_type, keys):
    gen = load_generator()
    log = gen.CodexHome(tmp_path).log()
    assert getattr(log, method)() is log
    data = log.write().read_bytes()
    assert data.endswith(b"\n")
    record = json.loads(data)
    assert record["ordinal"] == 0
    assert record["timestamp"] == "2030-01-07T00:00:00.000Z"
    if top_type is None:
        assert "type" not in record
        payload = record
    else:
        assert record["type"] == top_type
        payload = record["payload"]
    if payload_type:
        assert payload["type"] == payload_type
    assert keys <= payload.keys()


ITEM_KEYS = {
    "command": ("CommandExecution", {"id", "command", "cwd", "exit_code", "status", "aggregated_output", "stdout", "stderr", "duration", "source", "process_id", "parsed_cmd"}),
    "file_change": ("FileChange", {"id", "status", "changes", "stdout"}),
    "mcp": ("McpToolCall", {"id", "server", "tool", "arguments", "result", "status", "duration"}),
    "web_search": ("WebSearch", {"id", "query", "action"}),
    "extension": ("Extension", {"id", "kind"}),
    "image_view": ("ImageView", {"id", "path"}),
    "subagent_activity": ("SubAgentActivity", {"id", "kind", "agent_thread_id", "agent_path"}),
    "collab_wait": ("CollabAgentToolCall", {"id", "tool", "status", "sender_thread_id", "receiver_thread_ids", "receiver_agents", "agents_states"}),
    "user_item": ("UserMessage", {"id", "content"}),
    "agent_item": ("AgentMessage", {"id", "phase", "content"}),
}


@pytest.mark.parametrize("method", ITEM_KEYS)
def test_structured_item_template(tmp_path, method):
    gen = load_generator()
    record = json.loads(getattr(gen.CodexHome(tmp_path).log(), method)().write().read_text())
    payload = record["payload"]
    item = payload["item"]
    expected_type, keys = ITEM_KEYS[method]
    assert item["type"] == expected_type
    assert keys <= item.keys()
    assert {"thread_id", "turn_id", "completed_at_ms"} <= payload.keys()


def test_uuid7_timestamp_version_variant_and_sequence():
    gen = load_generator()
    ids = [UUID(gen.uuid7(1893974400123, n)) for n in (0, 1, 4096, 2**74 - 1)]
    assert len(set(ids)) == 4
    for value in ids:
        assert value.int >> 80 == 1893974400123
        assert value.version == 7
        assert value.variant == "specified in RFC 4122"
    assert gen.uuid7(1893974400123, 1) == str(ids[1])


@pytest.mark.parametrize("at,seq", [(-1, 0), (2**48, 0), (0, -1), (0, 2**74)])
def test_uuid7_rejects_out_of_range_fields(at, seq):
    gen = load_generator()
    with pytest.raises(ValueError):
        gen.uuid7(at, seq)


def test_clock_ordinals_at_override_and_iso(tmp_path):
    gen = load_generator()
    assert gen.iso(0) == "1970-01-01T00:00:00.000Z"
    assert gen.iso(-1) == "1969-12-31T23:59:59.999Z"
    log = gen.CodexHome(tmp_path).log().meta().task_started(at=1893974405000).task_complete()
    rows = [json.loads(line) for line in log.write().read_text().splitlines()]
    assert [r["ordinal"] for r in rows] == [0, 1, 2]
    assert [r["timestamp"] for r in rows] == ["2030-01-07T00:00:00.000Z", "2030-01-07T00:00:05.000Z", "2030-01-07T00:00:05.001Z"]
    assert rows[1]["payload"]["started_at"] == 1893974405
    assert rows[2]["payload"]["completed_at"] == 1893974405.001


def test_raw_partial_tail_and_mtime(tmp_path):
    gen = load_generator()
    log = gen.CodexHome(tmp_path).log().meta().raw(b"synthetic malformed\n")
    path = log.write(partial_tail=b'{"timestamp":"2030', mtime=1234567890)
    assert path.read_bytes().endswith(b'synthetic malformed\n{"timestamp":"2030')
    assert path.stat().st_mtime == 1234567890


def test_log_paths_and_generated_ids(tmp_path):
    gen = load_generator()
    home = gen.CodexHome(tmp_path)
    first, second = home.log(), home.log()
    assert first.session_id != second.session_id
    path = first.meta().write()
    assert path.parent == tmp_path / "sessions/2030/01/07"
    assert path.name == f"rollout-2030-01-07T00-00-00-{first.session_id}.jsonl"
    archive = home.log(archived=True, day="2030-02-08", name="synthetic-renamed.jsonl").write()
    assert archive.parent == tmp_path / "archived_sessions/2030/02/08"
    assert archive.name == "synthetic-renamed.jsonl"
    assert json.loads(path.read_text())["payload"]["id"] == first.session_id


def test_metadata_optional_shapes_and_turn_identity(tmp_path):
    gen = load_generator()
    log = gen.CodexHome(tmp_path).log("synthetic-thread")
    log.meta(parent_thread_id="synthetic-parent", forked_from_id="synthetic-fork", history_base={"thread_id": "synthetic-base"}, subagent_history_start_ordinal=7)
    log.turn_context("synthetic-turn", model="gpt-synthetic-2", model_name="gpt-synthetic-alias", info={"model": "gpt-synthetic-3"}, title="Synthetic title")
    log.user_item("Synthetic request", images=["/synthetic/a.png"])
    log.agent_response("Synthetic response", phase="commentary")
    rows = [json.loads(line)["payload"] for line in log.write().read_text().splitlines()]
    assert rows[0]["source"]["subagent"]["thread_spawn"] == {"parent_thread_id": "synthetic-parent", "depth": 1, "agent_path": "/root/code_review", "agent_nickname": "Agent-Alpha", "agent_role": None}
    assert rows[0]["history_base"] == {"thread_id": "synthetic-base"}
    assert rows[1]["collaboration_mode"]["settings"]["model"] == "gpt-synthetic-2"
    assert rows[2]["turn_id"] == "synthetic-turn"
    assert rows[2]["item"]["content"] == [{"type": "text", "text": "Synthetic request", "text_elements": []}, {"type": "local_image", "path": "/synthetic/a.png"}]
    assert rows[3]["internal_chat_message_metadata_passthrough"] == {"turn_id": "synthetic-turn"}
    assert rows[3]["role"] == "assistant"


def test_usage_templates_keep_all_counts_and_override_locations(tmp_path):
    gen = load_generator()
    usage = {"input_tokens": 12, "cached_input_tokens": 3, "cache_write_input_tokens": 2, "output_tokens": 4, "reasoning_output_tokens": 1, "total_tokens": 16}
    log = gen.CodexHome(tmp_path).log().token_count(total=usage, last=usage, model="gpt-synthetic-2", info_model="gpt-synthetic-3", top_model="gpt-synthetic-4")
    log.usage_record(usage=usage, response_id="synthetic-response", root_turn_id="synthetic-root").bare_usage(usage=usage)
    rows = [json.loads(line) for line in log.write().read_text().splitlines()]
    assert rows[0]["payload"]["info"]["total_token_usage"] == usage
    assert rows[0]["payload"]["info"]["last_token_usage"] == usage
    assert rows[0]["payload"]["model"] == "gpt-synthetic-2"
    assert rows[0]["payload"]["info"]["model"] == "gpt-synthetic-3"
    assert rows[0]["model"] == "gpt-synthetic-4"
    for key in ("usage", "turn_token_usage", "thread_token_usage"):
        assert rows[1]["payload"][key] == usage
    assert rows[2]["usage"] == usage


def test_function_arguments_and_outputs_are_json_strings(tmp_path):
    gen = load_generator()
    log = gen.CodexHome(tmp_path).log().function_call("spawn_agent", namespace="collaboration", arguments={"task_name": "code_review", "message": "Synthetic task", "fork_turns": "none"}).function_output(output={"task_name": "/root/code_review"})
    rows = [json.loads(line)["payload"] for line in log.write().read_text().splitlines()]
    assert json.loads(rows[0]["arguments"])["fork_turns"] == "none"
    assert rows[0]["namespace"] == "collaboration"
    assert json.loads(rows[1]["output"]) == {"task_name": "/root/code_review"}
    assert rows[0]["call_id"] == rows[1]["call_id"]


def test_state_database_schema_rows_edges_and_versions(tmp_path):
    gen = load_generator()
    home = gen.CodexHome(tmp_path)
    row = {"id": "synthetic-child", "title": "Synthetic title", "cwd": "/synthetic/projects/alpha", "archived": 1}
    path = home.state_db([row], version=7, spawn_edges=[("synthetic-parent", "synthetic-child")])
    assert path == tmp_path / "state_7.sqlite"
    with closing(sqlite3.connect(path)) as db:
        columns = {r[1] for r in db.execute("PRAGMA table_info(threads)")}
        assert {"id", "name", "title", "cwd", "git_branch", "git_origin_url", "git_sha", "source", "originator", "archived", "first_user_message", "agent_nickname", "agent_role", "agent_path", "rollout_path"} <= columns
        assert db.execute("SELECT id,title,cwd,archived FROM threads").fetchone() == tuple(row.values())
        assert db.execute("SELECT parent_thread_id,child_thread_id FROM thread_spawn_edges").fetchall() == [("synthetic-parent", "synthetic-child")]
    empty = home.state_db([])
    with closing(sqlite3.connect(empty)) as db:
        assert db.execute("SELECT count(*) FROM threads").fetchone() == (0,)
        assert db.execute("SELECT name FROM sqlite_master WHERE name='thread_spawn_edges'").fetchone() is None


def test_index_and_global_state_shapes(tmp_path):
    gen = load_generator()
    home = gen.CodexHome(tmp_path)
    entries = [{"id": "synthetic-thread", "thread_name": "Synthetic title", "updated_at": "2030-01-07T00:00:00.000Z"}]
    assert [json.loads(line) for line in home.session_index(entries).read_text().splitlines()] == entries
    assert json.loads(home.global_state({"synthetic-thread": "Synthetic desktop title"}).read_text()) == {"thread-titles": {"titles": {"synthetic-thread": "Synthetic desktop title"}}}


def test_trace_rows_match_pinned_upstream_text_and_schema(tmp_path):
    gen = load_generator()
    # parseCodexPriorityTraceRow/SubmissionRow/CompletedRow, pinned commit
    # 3bbf6bc48, CostUsageScanner+CodexPriority.swift:1020–1098.
    home = gen.CodexHome(tmp_path)
    request = home.priority_request_row("synthetic-turn", thread_id="synthetic-thread", model="gpt-synthetic-1", ts=1893974400)
    submission = home.submission_priority_row("synthetic-turn", thread_id="synthetic-thread", ts=1893974401)
    completion = home.completed_row("synthetic-turn", "gpt-synthetic-2", 1893974402)
    path = home.trace_db([request, submission, completion])
    assert path == tmp_path / "logs_2.sqlite"
    with closing(sqlite3.connect(path)) as db:
        columns = {r[1] for r in db.execute("PRAGMA table_info(logs)")}
        assert {"id", "ts", "ts_nanos", "level", "target", "feedback_log_body", "thread_id"} <= columns
        rows = db.execute("SELECT ts,feedback_log_body,thread_id FROM logs ORDER BY rowid").fetchall()
    assert [r[0] for r in rows] == [1893974400, 1893974401, 1893974402]
    prefix, body = rows[0][1].split("websocket request:", 1)
    assert "turn.id=synthetic-turn " in prefix
    assert "thread_id=synthetic-thread " in prefix
    assert json.loads(body) == {"type": "response.create", "service_tier": "priority", "model": "gpt-synthetic-1"}
    assert 'Submission sub=Submission { id: "synthetic-turn",' in rows[1][1]
    assert 'service_tier: Some(Some("priority"))' in rows[1][1]
    prefix, body = rows[2][1].split("websocket event:", 1)
    assert "turn.id=synthetic-turn " in prefix
    assert json.loads(body) == {"type": "response.completed", "response": {"model": "gpt-synthetic-2"}}


def test_explicit_empty_arguments_and_receivers_are_preserved(tmp_path):
    gen = load_generator()
    log = gen.CodexHome(tmp_path).log().function_call(arguments={}).collab_wait([])
    rows = [json.loads(line)["payload"] for line in log.write().read_text().splitlines()]
    assert rows[0]["arguments"] == "{}"
    assert rows[1]["item"]["receiver_thread_ids"] == []


@pytest.mark.parametrize("name", ["../synthetic-escape.jsonl", "/synthetic/escape.jsonl"])
def test_filename_cannot_escape_supplied_home(tmp_path, name):
    gen = load_generator()
    with pytest.raises(ValueError):
        gen.CodexHome(tmp_path).log(name=name)


def test_default_nested_values_match_record_templates(tmp_path):
    gen = load_generator()
    log = gen.CodexHome(tmp_path).log().meta().user_item().agent_item().user_response().agent_response().thread_settings().token_count().agent_message_ia()
    rows = [json.loads(line)["payload"] for line in log.write().read_text().splitlines()]
    assert rows[0]["git"] == {"branch": "main", "commit_hash": "0000000", "repository_url": "https://example.invalid/synthetic/alpha.git"}
    assert rows[0]["base_instructions"] == {"text": "Synthetic instructions."}
    assert rows[1]["item"]["content"] == [{"type": "text", "text": "Synthetic request 1", "text_elements": []}]
    assert rows[2]["item"]["content"] == [{"type": "Text", "text": "Synthetic final answer."}]
    assert rows[3]["content"] == [{"type": "input_text", "text": "Synthetic request 1"}]
    assert rows[4]["content"] == [{"type": "output_text", "text": "Synthetic final answer."}]
    assert rows[5]["thread_settings"] == {"model": "gpt-synthetic-1", "cwd": "/synthetic/projects/alpha"}
    zero_usage = {"input_tokens": 0, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0, "total_tokens": 0}
    assert rows[6]["info"] == {"total_token_usage": zero_usage, "last_token_usage": zero_usage, "model_context_window": 272000}
    assert rows[7]["content"] == [{"type": "encrypted_content", "encrypted_content": "c3ludGhldGlj"}]


def test_backwards_at_override_keeps_automatic_clock_monotonic(tmp_path):
    gen = load_generator()
    log = gen.CodexHome(tmp_path).log().meta(at=1893974409000).world_state(at=1893974401000).compacted()
    records = [json.loads(line) for line in log.write().read_text().splitlines()]
    assert [r["timestamp"] for r in records] == ["2030-01-07T00:00:09.000Z", "2030-01-07T00:00:01.000Z", "2030-01-07T00:00:09.002Z"]


@pytest.mark.parametrize("writer", ["state_db", "trace_db"])
@pytest.mark.parametrize("fails", [False, True], ids=["success", "failure"])
def test_database_writers_close_real_connections_on_every_exit(tmp_path, monkeypatch, writer, fails):
    gen = load_generator()
    home = gen.CodexHome(tmp_path)
    real_connect = sqlite3.connect
    connections = []

    def capture_connection(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", capture_connection)
    if writer == "state_db":
        # A list cannot bind to a SQLite TEXT column; failure occurs after open.
        rows = [{"id": "synthetic-thread", "title": [] if fails else "Synthetic title"}]
    else:
        # A list cannot bind to a SQLite INTEGER column, also after open.
        rows = [{"ts": [] if fails else 1893974400, "feedback_log_body": "Synthetic trace."}]
    if fails:
        with pytest.raises(sqlite3.ProgrammingError, match="type 'list' is not supported"):
            getattr(home, writer)(rows)
    else:
        getattr(home, writer)(rows)
    assert len(connections) == 1
    # Check the actual retained connection; this must not rely on garbage
    # collection, reference counts, or a fake close implementation.
    try:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connections[0].execute("SELECT 1")
    finally:
        # Keep the regression itself leak-free if it catches a future failure.
        connections[0].close()
