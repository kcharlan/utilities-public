"""Synthetic tool summaries and link evidence; no token mapping is done here."""

import json

import pytest

from fixturegen import CodexHome, iso

BASE = 1_893_456_000_000
FUNCTIONS = frozenset({"update_plan", "request_user_input", "request_user_input_async",
                       "write_stdin", "wait", "wait_agent", "list_agents", "spawn_agent",
                       "followup_task", "send_message", "interrupt_agent"})
JS = frozenset({"write_stdin", "update_plan", "wait", "request_user_input",
                "request_user_input_async", "clock__sleep"})


def counts(**changes):
    return {"shell": 0, "shell_failed": 0, "file_edits": 0, "mcp": {},
            "web": 0, "image": 0, "other": {}, **changes}


def tally(colophon):
    assert hasattr(colophon, "ToolTally"), "Task 6 ToolTally is missing"
    return colophon.ToolTally()


def raw(kind="function_call", **fields):
    return {"type": "response_item", "payload": {"type": kind, **fields}}


def new_log(tmp_path):
    return CodexHome(tmp_path / "synthetic-codex-home").log().meta(at=BASE)


def parse(colophon, log):
    path = log.write()
    stat = path.stat()
    result = colophon.parse_log_file(path, size=stat.st_size, mtime_ns=stat.st_mtime_ns, archived=False)
    assert {"tools", "links", "usage_records"} <= result.keys(), "Task 6 FileRecord fields are missing"
    return result


def test_orchestration_sets_are_exact(colophon):
    assert getattr(colophon, "ORCHESTRATION_FUNCTIONS", None) == FUNCTIONS
    assert getattr(colophon, "ORCHESTRATION_JS", None) == JS


@pytest.mark.parametrize("item, expected", [
    ({"type": "CommandExecution", "exit_code": 0}, counts(shell=1)),
    ({"type": "CommandExecution", "exit_code": -1}, counts(shell=1, shell_failed=1)),
    ({"type": "FileChange", "changes": {"/synthetic/a": {}, "/synthetic/b": {}}}, counts(file_edits=2)),
    ({"type": "McpToolCall", "server": "synthetic_srv"}, counts(mcp={"synthetic_srv": 1})),
    ({"type": "WebSearch"}, counts(web=1)),
    ({"type": "Extension", "kind": "web.search"}, counts(web=1)),
    ({"type": "Extension", "kind": "clock.sleep"}, counts()),
    ({"type": "Extension", "kind": "image_gen.generation"}, counts(other={"image_gen.generation": 1})),
    ({"type": "ImageView"}, counts(image=1)),
])
def test_every_structured_mapping(colophon, item, expected):
    tools = tally(colophon)
    tools.add_structured(item)
    assert tools.result() == expected


@pytest.mark.parametrize("record, expected", [
    (raw(name="exec_command"), counts(shell=1)),
    (raw(name="shell", namespace=None), counts(shell=1)),
    (raw("local_shell_call"), counts(shell=1)),
    (raw("custom_tool_call", name="apply_patch"), counts(file_edits=1)),
    (raw(name="lookup", namespace="mcp__synthetic_srv"), counts(mcp={"synthetic_srv": 1})),
    (raw("web_search_call"), counts(web=1)),
    (raw(name="run", namespace="web"), counts(web=1)),
    (raw(name="view_image"), counts(image=1)),
    (raw(name="synthetic_fn"), counts(other={"synthetic_fn": 1})),
    (raw(name="shell", namespace="synthetic_ns"), counts(other={"synthetic_ns:shell": 1})),
    (raw(name="generate", namespace="image_gen"), counts(other={"image_gen:generate": 1})),
    (raw("tool_search_call"), counts()),
    (raw("function_call_output", name="shell"), counts()),
    (raw("custom_tool_call", name="synthetic_custom"), counts()),
])
def test_every_raw_mapping(colophon, record, expected):
    tools = tally(colophon)
    tools.add_raw(record)
    assert tools.result() == expected


@pytest.mark.parametrize("name", sorted(FUNCTIONS))
@pytest.mark.parametrize("namespace", [None, "synthetic_ns"])
def test_every_function_orchestration_name_is_excluded(colophon, name, namespace):
    tools = tally(colophon)
    tools.add_raw(raw(name=name, namespace=namespace))
    assert tools.result() == counts()


@pytest.mark.parametrize("namespace", ["collaboration", "clock"])
def test_all_calls_in_orchestration_namespaces_are_excluded(colophon, namespace):
    tools = tally(colophon)
    tools.add_raw(raw(name="synthetic_unknown", namespace=namespace))
    assert tools.result() == counts()


@pytest.mark.parametrize("name", [*sorted(JS), "collaboration__synthetic_unknown"])
def test_every_js_orchestration_name_is_excluded(colophon, name):
    tools = tally(colophon)
    tools.add_raw(raw("custom_tool_call", name="exec", input=f"await tools.{name}();"))
    assert tools.result() == counts()


def test_js_markers_count_occurrences_and_extract_mcp_server(colophon):
    tools = tally(colophon)
    tools.add_raw(raw("custom_tool_call", name="exec", input="""
        await tools.exec_command(); await tools.exec_command();
        await tools.apply_patch(); await tools.mcp__synthetic_srv__lookup();
        await tools.mcp__synthetic_srv__other(); await tools.web__run();
        await web.run(); await tools.view_image(); await tools.synthetic_other();
        await tools._synthetic_2();
    """))
    assert tools.result() == counts(shell=2, file_edits=1, mcp={"synthetic_srv": 2},
                                    web=2, image=1, other={"synthetic_other": 1, "_synthetic_2": 1})


def test_exec_wrapper_is_not_a_file_edit_or_a_substring_marker(colophon):
    tools = tally(colophon)
    tools.add_raw(raw("custom_tool_call", name="exec", input="synthetic_tools.exec_command(); synthetic_web.run(); tools.9invalid();"))
    assert tools.result() == counts()


def test_standalone_web_marker_does_not_double_count_tools_web_run(colophon):
    tools = tally(colophon)
    tools.add_raw(raw("custom_tool_call", name="exec", input="tools.web.run(); web.run();"))
    assert tools.result() == counts(web=1)


def test_precedence_is_per_turn_and_order_independent(colophon, tmp_path):
    log = new_log(tmp_path).task_started("synthetic-a").function_call().command(exit_code=2).task_complete()
    log.task_started("synthetic-b").command().function_call().task_complete()
    log.task_started("synthetic-c").function_call().local_shell_call().task_complete()
    assert parse(colophon, log)["tools"] == {
        "synthetic-a": counts(shell=1, shell_failed=1), "synthetic-b": counts(shell=1),
        "synthetic-c": counts(shell=2)}


def test_sleep_extension_triggers_structured_precedence(colophon, tmp_path):
    log = new_log(tmp_path).task_started().function_call().extension("clock.sleep").task_complete()
    assert parse(colophon, log)["tools"] == {"synthetic-turn-1": counts()}


def test_non_tool_items_do_not_trigger_structured_precedence(colophon, tmp_path):
    log = new_log(tmp_path).task_started().function_call().subagent_activity().collab_wait().user_item().task_complete()
    assert parse(colophon, log)["tools"] == {"synthetic-turn-1": counts(shell=1)}


def test_tools_outside_turn_are_excluded_and_turn_with_no_tools_is_empty(colophon, tmp_path):
    log = new_log(tmp_path).command(turn_id="synthetic-no-turn").function_call(turn_id="synthetic-no-turn")
    log.task_started().task_complete().local_shell_call()
    assert parse(colophon, log)["tools"] == {"synthetic-turn-1": counts()}


def test_explicit_tools_before_start_are_attributed(colophon, tmp_path):
    log = new_log(tmp_path).command().task_started().task_complete()
    assert parse(colophon, log)["tools"] == {"synthetic-turn-1": counts(shell=1)}


def test_link_evidence_spawn_join_missing_output_targets_and_receivers(colophon, tmp_path):
    log = new_log(tmp_path).task_started()
    log.function_call("spawn_agent", namespace="collaboration", call_id="synthetic-spawn-a", at=BASE + 2)
    log.function_call("spawn_agent", namespace="collaboration", call_id="synthetic-spawn-b", at=BASE + 3)
    log.function_output(call_id="synthetic-spawn-a", output={"task_name": "/root/synthetic_child"})
    log.function_call("followup_task", namespace="collaboration", arguments={"target": "synthetic_child"})
    log.function_call("send_message", namespace="collaboration", arguments={"target": "/root/synthetic_child"})
    log.function_call("interrupt_agent", namespace="collaboration", arguments={"target": "synthetic_child"})
    log.subagent_activity("synthetic-child", agent_path="/root/synthetic_child")
    log.subagent_activity("synthetic-child", kind="interacted", agent_path="/root/synthetic_child")
    log.collab_wait(["synthetic-child", "synthetic-child-2"]).task_complete()
    links = parse(colophon, log)["links"]
    assert links == {
        "activities": [{"kind": kind, "child_id": "synthetic-child", "agent_path": "/root/synthetic_child", "turn_key": "synthetic-turn-1"}
                       for kind in ("started", "interacted")],
        "spawn_calls": [{"task_name": "/root/synthetic_child", "turn_key": "synthetic-turn-1", "at_ms": BASE + 2},
                        {"task_name": None, "turn_key": "synthetic-turn-1", "at_ms": BASE + 3}],
        "targets": [{"target": target, "turn_key": "synthetic-turn-1"} for target in ("synthetic_child", "/root/synthetic_child")],
        "collab_receivers": [{"child_id": child, "turn_key": "synthetic-turn-1"} for child in ("synthetic-child", "synthetic-child-2")],
    }


def test_inherited_tool_and_link_evidence_is_excluded_but_usage_retained(colophon, tmp_path):
    log = CodexHome(tmp_path / "synthetic-codex-home").log().meta(at=BASE + 10_000)
    log.command(at=BASE).subagent_activity(at=BASE).collab_wait(at=BASE)
    log.function_call("spawn_agent", namespace="collaboration", at=BASE, call_id="synthetic-inherited")
    log.function_output(at=BASE, output={"task_name": "/root/synthetic_inherited"})
    log.function_call("send_message", namespace="collaboration", arguments={"target": "synthetic_inherited"}, at=BASE)
    log.usage_record(thread_id="synthetic-foreign", at=BASE)
    log.task_started(at=BASE + 12_000).command().task_complete()
    result = parse(colophon, log)
    assert result["tools"] == {"synthetic-turn-1": counts(shell=1)}
    assert result["links"] == {"activities": [], "spawn_calls": [], "targets": [], "collab_receivers": []}
    assert result["usage_records"][0]["thread_id"] == "synthetic-foreign"


def test_inherited_output_cannot_supply_owned_spawn_evidence(colophon, tmp_path):
    log = CodexHome(tmp_path / "synthetic-codex-home").log().meta(at=BASE + 10_000)
    log.function_output(at=BASE, call_id="synthetic-call", output={"task_name": "/root/synthetic_inherited"})
    log.task_started(at=BASE + 12_000).function_call("spawn_agent", namespace="collaboration", call_id="synthetic-call")
    assert parse(colophon, log)["links"]["spawn_calls"][0]["task_name"] is None


@pytest.mark.parametrize("output", ["Synthetic invalid JSON", "[]", '{"task_name": null}', '{"task_name": 42}', '{"task_name": " "}'])
def test_invalid_spawn_output_keeps_unknown_name(colophon, tmp_path, output):
    log = new_log(tmp_path).task_started().function_call("spawn_agent", namespace="collaboration")
    log.function_output(output=output)
    assert parse(colophon, log)["links"]["spawn_calls"][0]["task_name"] is None


def test_missing_call_ids_never_join_spawn_and_output(colophon, tmp_path):
    log = new_log(tmp_path).task_started()
    log._response("function_call", {"name": "spawn_agent", "namespace": "collaboration"})
    log._response("function_call_output", {"output": '{"task_name": "/root/synthetic_child"}'})
    assert parse(colophon, log)["links"]["spawn_calls"][0]["task_name"] is None


def test_owned_links_outside_turn_retain_null_attribution(colophon, tmp_path):
    log = new_log(tmp_path).subagent_activity(turn_id="synthetic-no-turn")
    log.function_call("send_message", namespace="collaboration", turn_id="synthetic-no-turn", arguments={"target": "synthetic_child"})
    links = parse(colophon, log)["links"]
    assert links["activities"][0]["turn_key"] is None
    assert links["targets"] == [{"target": "synthetic_child", "turn_key": None}]


def test_usage_records_preserve_all_raw_components_and_duplicate_foreign_ids(colophon, tmp_path):
    usage = {"input_tokens": 10, "cached_input_tokens": 3, "cache_read_input_tokens": 7,
             "cache_write_input_tokens": 5, "output_tokens": 2, "reasoning_output_tokens": 1}
    payload = {"response_id": "synthetic-duplicate", "thread_id": "synthetic-foreign", "turn_id": "synthetic-turn", "root_turn_id": "synthetic-root", "usage": usage}
    log = new_log(tmp_path)._emit("token_usage_record", payload, at=BASE + 1)
    log._emit("token_usage_record", payload, at=BASE + 2)
    rows = parse(colophon, log)["usage_records"]
    assert rows == [{"line": n, "rec": n, "response_id": "synthetic-duplicate", "thread_id": "synthetic-foreign", "turn_id": "synthetic-turn", "root_turn_id": "synthetic-root",
                     "ts": iso(BASE + n), "at_ms": BASE + n, "timestamp_unix_ms": BASE + n,
                     "input": 10, "cached_input": 3, "cache_read_input": 7, "cache_write": 5, "output": 2, "reasoning": 1}
                    for n in (1, 2)]


def test_usage_missing_or_invalid_values_remain_raw_and_time_is_not_invented(colophon, tmp_path):
    log = new_log(tmp_path)
    log.raw(b'{"type":"token_usage_record","payload":{"usage":{"input_tokens":"synthetic-invalid","output_tokens":null,"cache_write_input_tokens":false}}}\n')
    row = parse(colophon, log)["usage_records"][0]
    assert row == {"line": 1, "rec": 1, "response_id": None, "thread_id": None, "turn_id": None, "root_turn_id": None, "ts": None,
                   "at_ms": None, "timestamp_unix_ms": None, "input": "synthetic-invalid", "cached_input": None,
                   "cache_read_input": None, "cache_write": False, "output": None, "reasoning": None}


@pytest.mark.parametrize("fraction, increment", [("0004", 0), ("0006", 0), ("0015", 1)])
def test_usage_timestamp_native_parser_truncates_beyond_three_digits(colophon, tmp_path, fraction, increment):
    log = new_log(tmp_path)
    log.raw((json.dumps({"type": "token_usage_record", "timestamp": f"2030-01-01T00:00:00.{fraction}Z", "payload": {"usage": {}}}) + "\n").encode())
    row = parse(colophon, log)["usage_records"][0]
    assert row["timestamp_unix_ms"] == BASE + increment


@pytest.mark.parametrize("exit_code", [None, True, False, 2.0, "2"])
def test_malformed_exit_code_is_not_failure_evidence(colophon, exit_code):
    tools = tally(colophon)
    tools.add_structured({"type": "CommandExecution", "exit_code": exit_code})
    assert tools.result() == counts(shell=1)


def test_invalid_structured_keys_do_not_invent_group_names(colophon):
    tools = tally(colophon)
    for item in ({"type": "McpToolCall", "server": []}, {"type": "Extension", "kind": None},
                 {"type": "FileChange", "changes": ["/synthetic/a"]}):
        tools.add_structured(item)
    assert tools.result() == counts()


def test_malformed_link_inputs_do_not_invent_evidence(colophon, tmp_path):
    log = new_log(tmp_path).task_started()
    log.function_call("send_message", namespace="collaboration", arguments="[]")
    log.function_call("followup_task", namespace="collaboration", arguments={"target": " "})
    log.collab_wait([None, 42, " ", "synthetic-child"])
    links = parse(colophon, log)["links"]
    assert links["targets"] == [{"target": None, "turn_key": "synthetic-turn-1"}] * 2
    assert links["collab_receivers"] == [{"child_id": "synthetic-child", "turn_key": "synthetic-turn-1"}]


@pytest.mark.parametrize("duplicate", ["call", "output"])
def test_duplicate_call_id_is_ambiguous_spawn_evidence(colophon, tmp_path, duplicate):
    log = new_log(tmp_path).task_started()
    log.function_call("spawn_agent", namespace="collaboration", call_id="synthetic-duplicate")
    if duplicate == "call":
        log.function_call("spawn_agent", namespace="collaboration", call_id="synthetic-duplicate")
    log.function_output(call_id="synthetic-duplicate", output={"task_name": "/root/synthetic_child"})
    if duplicate == "output":
        log.function_output(call_id="synthetic-duplicate", output={"task_name": "/root/synthetic_other"})
    assert all(spawn["task_name"] is None for spawn in parse(colophon, log)["links"]["spawn_calls"])


def test_spawn_join_is_independent_of_output_order(colophon, tmp_path):
    log = new_log(tmp_path).task_started()
    log.function_output(call_id="synthetic-call", output={"task_name": "/root/synthetic_child"})
    log.function_call("spawn_agent", namespace="collaboration", call_id="synthetic-call")
    assert parse(colophon, log)["links"]["spawn_calls"][0]["task_name"] == "/root/synthetic_child"


def test_tool_and_link_candidates_release_raw_payloads_before_phase_two(colophon, tmp_path, monkeypatch):
    import weakref

    log = new_log(tmp_path).task_started().command().file_change().extension("clock.sleep")
    log.custom_tool_call(input="await tools.apply_patch();")
    log.function_call("spawn_agent", namespace="collaboration").function_output()
    log.subagent_activity().collab_wait().usage_record()
    references = []
    decode, history = colophon.decode_line, colophon._history

    class TrackedDict(dict):
        pass

    def tracked(value):
        if isinstance(value, dict):
            item = TrackedDict({key: tracked(child) for key, child in value.items()})
            references.append(weakref.ref(item))
            return item
        if isinstance(value, list):
            return [tracked(child) for child in value]
        return value

    def track(data):
        decoded = decode(data)
        return colophon.DecodedLine(tracked(decoded.obj), decoded.status)

    def phase_two(meta, facts):
        assert references and all(ref() is None for ref in references)
        return history(meta, facts)

    monkeypatch.setattr(colophon, "decode_line", track)
    monkeypatch.setattr(colophon, "_history", phase_two)
    parse(colophon, log)


def test_tally_precedence_applies_even_when_structured_count_is_zero(colophon):
    tools = tally(colophon)
    tools.add_raw(raw(name="exec_command"))
    tools.add_structured({"type": "FileChange", "changes": {}})
    tools.add_raw(raw(name="view_image"))
    assert tools.result() == counts()


def test_missing_activity_identities_are_retained_as_unknown(colophon, tmp_path):
    log = new_log(tmp_path).task_started()
    log.subagent_activity(agent_thread_id=None, agent_path=42, kind=None)
    assert parse(colophon, log)["links"]["activities"] == [
        {"kind": None, "child_id": None, "agent_path": None, "turn_key": "synthetic-turn-1"}]


@pytest.mark.parametrize("timestamp, expected", [
    ("1970-01-01T00:00:00.0005Z", 0),
    ("1970-01-01T00:00:00.0015Z", 1),
    ("1969-12-31T23:59:59.9996Z", -1),
    ("1969-12-31T23:59:59.9999Z", -1),
    ("1969-12-31T23:59:00.0006Z", -60_000),
    ("2030-01-01T00:00:59.9999Z", BASE + 59_999),
    ("2030-01-01T00:00:00.000000001Z", BASE),
])
def test_usage_timestamp_native_precision_at_ties_negative_epochs_and_second_boundary(colophon, tmp_path, timestamp, expected):
    # Hand-derived: parseNativeRFC3339 keeps only three fraction digits
    # (CostUsageScanner+Timestamp.swift:59–69, CodexBar 3bbf6bc48).
    # unixMilliseconds rounds that already-integral ms (Scanner.swift:4262–4267),
    # so extra source precision supplies neither a tie nor a second carry.
    log = new_log(tmp_path)
    log.raw((json.dumps({"type": "token_usage_record", "timestamp": timestamp, "payload": {"usage": {}}}) + "\n").encode())
    row = parse(colophon, log)["usage_records"][0]
    assert row["timestamp_unix_ms"] == expected
