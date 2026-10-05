"""Time-independent parse facts assembled at an explicit synthetic snapshot."""

import copy

import pytest

from fixturegen import CodexHome

BASE = 1_893_974_400_000
HOUR = 3_600_000
SYNTHETIC_UUID = "12345678-1234-1234-1234-123456789abc"


def parsed(colophon, log, *, mtime=BASE, archived=False):
    path = log.write()
    return colophon.parse_log_file(path, size=path.stat().st_size,
                                   mtime_ns=mtime * 1_000_000, archived=archived)


def home(tmp_path):
    return CodexHome(tmp_path / "synthetic-codex-home")


def corpus(colophon, records, *, snapshot=BASE + HOUR, metadata=None):
    return colophon.build_corpus(records, metadata or colophon.CodexMetadata(), snapshot)


def only(colophon, record, **kwargs):
    result = corpus(colophon, [record], **kwargs)
    assert len(result.sessions) == 1
    return next(iter(result.sessions.values()))


@pytest.mark.parametrize("gap,status", [(2 * HOUR - 600_000, "running"),
                                        (2 * HOUR, "running"),
                                        (2 * HOUR + 600_000, "abandoned")])
def test_open_turn_quiet_threshold(colophon, tmp_path, gap, status):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started(at=BASE + 10))
    turn = only(colophon, record, snapshot=BASE + gap).turns[0]
    assert turn.status == status
    if status == "running":
        assert turn.end_ms == BASE + gap
        assert turn.duration_ms == gap - 10
        assert "live" in turn.flags
    else:
        assert turn.duration_ms is None
        assert "live" not in turn.flags


def test_cache_hit_flip_and_partial_line_diagnostics(colophon, tmp_path):
    log = home(tmp_path).log().meta(at=BASE).task_started(at=BASE + 1)
    log._lines.append(b'{"timestamp":"synthetic partial')
    record = parsed(colophon, log)
    original = copy.deepcopy(record)
    recent = corpus(colophon, [record], snapshot=BASE + HOUR)
    quiet = corpus(colophon, [record], snapshot=BASE + 3 * HOUR)
    assert next(iter(recent.sessions.values())).turns[0].status == "running"
    assert next(iter(quiet.sessions.values())).turns[0].status == "abandoned"
    assert recent.file_diagnostics["truncated_lines"] == {"total": 0, "files": []}
    assert quiet.file_diagnostics["truncated_lines"] == {
        "total": 1, "files": [{"path": record["key"]["path"], "count": 1}]}
    assert record == original


def test_interrupted_turn_is_snapshot_independent(colophon, tmp_path):
    log = (home(tmp_path).log().meta(at=BASE).task_started("synthetic-first", at=BASE + 10)
           .user_item(at=BASE + 20).task_started("synthetic-next", at=BASE + 40))
    record = parsed(colophon, log)
    first = only(colophon, record).turns[0]
    later = only(colophon, record, snapshot=BASE + 4 * HOUR).turns[0]
    assert first == later
    assert first.status == "interrupted"
    assert first.duration_ms == 10
    assert "interrupted" in only(colophon, record).flags


def test_duplicate_session_uses_newest_display_and_preserves_processing_order(colophon, tmp_path):
    synthetic = home(tmp_path)
    old = parsed(colophon, synthetic.log("synthetic-shared", name="synthetic-old.jsonl")
                 .meta(at=BASE, title="Synthetic old title").task_started().task_complete(), mtime=BASE)
    new = parsed(colophon, synthetic.log("synthetic-shared", name="synthetic-new.jsonl", archived=True)
                 .meta(at=BASE, title="Synthetic new title").task_started("synthetic-new-turn"),
                 mtime=BASE + HOUR, archived=True)
    model = next(iter(corpus(colophon, [old, new], snapshot=BASE + 2 * HOUR).sessions.values()))
    assert model.id == "synthetic-shared"
    assert model.record is new
    assert model.records == [new, old]
    assert model.archived is True
    assert model.log_path == new["key"]["path"]
    assert model.meta == new["meta"]
    assert model.title == "Synthetic new title"
    assert model.turns[0].id == "synthetic-new-turn"
    assert model.turns[0].status == "running"
    assert model.flags == {"live"}


def test_same_mtime_display_tie_uses_path_and_records_use_size_then_path(colophon, tmp_path):
    synthetic = home(tmp_path)
    first = parsed(colophon, synthetic.log("synthetic-shared", name="a-synthetic.jsonl")
                   .meta(at=BASE, title="Synthetic first").user_item("Synthetic longer " * 30))
    second = parsed(colophon, synthetic.log("synthetic-shared", name="z-synthetic.jsonl")
                    .meta(at=BASE, title="Synthetic second").user_item())
    model = only(colophon, first)
    merged = next(iter(corpus(colophon, [second, first]).sessions.values()))
    assert merged.record is first
    assert merged.title == model.title
    assert merged.records == [second, first]


def test_no_metadata_uuid_is_separate_from_real_session_and_collision_safe(colophon, tmp_path):
    synthetic = home(tmp_path)
    real = parsed(colophon, synthetic.log(SYNTHETIC_UUID).meta(at=BASE).task_started())
    missing = parsed(colophon, synthetic.log(name=f"synthetic-{SYNTHETIC_UUID}.jsonl").task_started())
    result = corpus(colophon, [real, missing])
    assert set(result.sessions) == {SYNTHETIC_UUID, f"file:{missing['key']['path']}"}
    model = result.sessions[f"file:{missing['key']['path']}"]
    assert model.id == f"file:{missing['key']['path']}"
    assert "no_session_meta" in model.flags
    assert model.record is missing


@pytest.mark.parametrize("filename,display", [(f"synthetic-{SYNTHETIC_UUID.upper()}.jsonl", SYNTHETIC_UUID.upper()),
                                             ("synthetic-no-uuid.jsonl", "synthetic-no-uuid")])
def test_no_metadata_uses_trailing_uuid_or_stem(colophon, tmp_path, filename, display):
    record = parsed(colophon, home(tmp_path).log(name=filename).task_started())
    result = corpus(colophon, [record])
    assert list(result.sessions) == [f"file:{record['key']['path']}"]
    assert next(iter(result.sessions.values())).id == display


def test_two_meta_less_display_collisions_remain_unique(colophon, tmp_path):
    synthetic = home(tmp_path)
    first = parsed(colophon, synthetic.log(name="synthetic-same.jsonl").task_started())
    second = parsed(colophon, synthetic.log(name="synthetic-same.jsonl", archived=True).task_started(), archived=True)
    result = corpus(colophon, [first, second])
    assert len(result.sessions) == 2
    assert {model.id for model in result.sessions.values()} == {
        f"file:{first['key']['path']}", f"file:{second['key']['path']}"}


def test_skipped_records_keep_header_for_later_parent_resolution(colophon, tmp_path):
    synthetic = home(tmp_path)
    empty = parsed(colophon, synthetic.log(name="synthetic-empty.jsonl"))
    header = parsed(colophon, synthetic.log("synthetic-header").meta(at=BASE))
    missing = parsed(colophon, synthetic.log(name="synthetic-no-meta.jsonl").user_item())
    metadata = colophon.CodexMetadata(threads={"synthetic-header": {}, "synthetic-no-log": {}})
    result = corpus(colophon, [empty, header, missing], metadata=metadata)
    assert len(result.sessions) == 1
    assert result.skipped == [{"path": r["key"]["path"], "reason": r["status"]}
                              for r in sorted([empty, header], key=lambda r: (r["key"]["size"], r["key"]["path"]))]
    assert {r["key"]["path"] for r in result.skipped_records} == {empty["key"]["path"], header["key"]["path"]}
    assert result.db_threads_without_logs == 1


def test_file_diagnostics_aggregate_every_copy_and_skipped_record(colophon, tmp_path):
    synthetic = home(tmp_path)
    first = parsed(colophon, synthetic.log("synthetic-shared").meta(at=BASE).task_started())
    second = parsed(colophon, synthetic.log("synthetic-shared", name="synthetic-copy.jsonl").meta(at=BASE).user_item())
    empty = parsed(colophon, synthetic.log(name="synthetic-empty.jsonl"))
    first["lines"].update(malformed=2, recovered=1)
    second["lines"].update(malformed=3, partial_final_line=True)
    empty["unknown_types"] = {"synthetic_type": 2}
    result = corpus(colophon, [first, second, empty], snapshot=BASE + 3 * HOUR)
    assert result.file_diagnostics["malformed_lines"]["total"] == 5
    assert result.file_diagnostics["recovered_lines"]["total"] == 1
    assert result.file_diagnostics["truncated_lines"]["total"] == 1
    assert result.file_diagnostics["unknown_record_types"] == {"synthetic_type": 2}


def test_turn_numbering_uses_start_then_end_then_file_order(colophon):
    def fact(key, start, end):
        return {"key": key, "turn_id": key, "start_ms": start, "end_ms": end,
                "start_src": "record_timestamp", "end_src": "record_timestamp", "start_rec": 0,
                "reported_ms": None, "ttft_ms": None, "end_kind": "completed", "last_ms": end}
    facts = [fact("synthetic-late", 90, 100), fact("synthetic-no-clock", None, None),
             fact("synthetic-end-only", None, 50), fact("synthetic-first-tie", 50, 60),
             fact("synthetic-second-tie", 50, 80)]
    turns = colophon.classify_open_turns(facts, mtime_ms=BASE, snapshot_ms=BASE)
    assert [(t.id, t.n) for t in turns] == [("synthetic-end-only", 1), ("synthetic-first-tie", 2),
                                          ("synthetic-second-tie", 3), ("synthetic-late", 4), ("synthetic-no-clock", 5)]
    assert "unknown_duration" in turns[0].flags


def test_session_flags_collapsed_requests_and_reported_duration(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started(at=BASE)
                    .user_event_legacy(at=BASE).turn_aborted(at=BASE, duration_ms=25))
    model = only(colophon, record)
    assert model.flags == {"aborted", "uncertain_timing", "collapsed_timestamps"}
    assert model.turns[0].flags == {"reported_duration"}
    assert model.turns[0].duration_ms == 25
    assert model.turns[0].requests == [{"at_ms": BASE, "text": "Synthetic request 1", "kind": "text",
                                      "before_turn": False, "images": 0, "time_unreliable": True}]


def test_collapsed_embedded_request_clocks_are_reliable(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started(at=BASE)
                    .user_item("Synthetic first", at=BASE, completed_at_ms=BASE + 10)
                    .user_item("Synthetic last", at=BASE, completed_at_ms=BASE + 30)
                    .task_complete(at=BASE, duration_ms=0))
    model = only(colophon, record)
    assert all(not r["time_unreliable"] for r in model.turns[0].requests)
    assert model.user_span_ms == 20
    assert model.flags == {"collapsed_timestamps"}


def test_collapsed_unknown_turn_duration_flags_session(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started(at=BASE).task_complete(at=BASE))
    model = only(colophon, record)
    assert model.turns[0].duration_ms is None
    assert model.turns[0].flags == {"collapsed"}
    assert model.flags == {"collapsed_timestamps", "uncertain_timing"}


def test_idle_uses_owned_span_and_union_not_sum(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started("synthetic-first", at=BASE + 10)
                    .task_complete(at=BASE + 30).task_started("synthetic-second", at=BASE + 60)
                    .task_complete(at=BASE + 90))
    model = only(colophon, record)
    assert (model.start_ms, model.end_ms) == (BASE, BASE + 90)
    assert model.idle_ms == 40
    # Completion records can identify concurrent turns; overlapping intervals count once.
    record["turns"][1]["start_ms"] = BASE + 20
    model = only(colophon, record)
    assert model.idle_ms == 10


def test_idle_excludes_abandoned_and_unknown_intervals(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started(at=BASE + 10).user_item(at=BASE + 50))
    assert only(colophon, record, snapshot=BASE + 3 * HOUR).idle_ms == 50
    record["turns"][0]["start_ms"] = None
    model = only(colophon, record)
    assert model.idle_ms == 50
    assert "unknown_duration" in model.turns[0].flags
    assert "uncertain_timing" in model.flags


def test_user_span_includes_unattributed_requests_and_requires_reliable_times(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).user_item("Synthetic outside", at=BASE + 10)
                    .task_started(at=BASE + 20).user_item("Synthetic inside", at=BASE + 30).task_complete(at=BASE + 40))
    assert only(colophon, record).user_span_ms == 20
    record["messages"][0]["at_ms"] = None
    assert only(colophon, record).user_span_ms is None


def test_user_span_null_with_collapsed_or_fewer_than_two_requests(colophon, tmp_path):
    synthetic = home(tmp_path)
    single = parsed(colophon, synthetic.log().meta(at=BASE).task_started().user_item().task_complete())
    assert only(colophon, single).user_span_ms is None
    collapsed = parsed(colophon, synthetic.log().meta(at=BASE).task_started(at=BASE)
                       .user_event_legacy("Synthetic first", at=BASE)
                       .user_event_legacy("Synthetic second", at=BASE).task_complete(at=BASE))
    assert only(colophon, collapsed).user_span_ms is None


def test_unknown_owned_span_stays_unknown(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).user_item())
    record["owned_span"] = {"first_ms": None, "last_ms": None}
    model = only(colophon, record)
    assert model.start_ms is model.end_ms is model.idle_ms is None


def test_history_unresolved_withholds_activity_but_keeps_display_and_links(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE, title="Synthetic retained title")
                    .task_started().user_item().command().task_complete())
    record["history"]["method"] = "unresolved"
    original = copy.deepcopy(record)
    model = only(colophon, record)
    assert model.turns == []
    assert model.session_voice == {"requests": [], "replies": []}
    assert model.start_ms is model.end_ms is model.idle_ms is model.user_span_ms is None
    assert model.flags == {"history_unresolved"}
    assert model.title == "Synthetic retained title"
    assert model.log_path == record["key"]["path"]
    assert model.record["links"] == record["links"]
    assert model.record == original


def test_before_turn_voice_request_preserves_placement_and_final_rule(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started().user_item().agent_item().task_complete())
    key = record["turns"][0]["key"]
    record["voice"]["requests"] = [
        {"text": "Synthetic before", "at_ms": BASE, "turn_key": key, "before_turn": True, "follow_up": False, "reply": "Synthetic excluded"},
        {"text": "Synthetic spoken", "at_ms": BASE + 3, "turn_key": key, "before_turn": False, "follow_up": False, "reply": "Synthetic spoken final"},
        {"text": "Synthetic outside", "at_ms": BASE + 9, "turn_key": None, "before_turn": False, "follow_up": False, "reply": "Synthetic session reply"}]
    record["voice"]["replies"] = [{"text": "Synthetic unprompted", "at_ms": BASE + 10, "turn_key": None}]
    model = only(colophon, record)
    requests = model.turns[0].requests
    assert [(r["text"], r["before_turn"]) for r in requests if r["kind"] == "voice"] == [("Synthetic before", True), ("Synthetic spoken", False)]
    assert model.turns[0].final_answer == {"text": "Synthetic final answer.", "voice": False}
    assert model.session_voice == {"requests": [{"at_ms": BASE + 9, "text": "Synthetic outside", "kind": "voice", "before_turn": False, "images": 0, "time_unreliable": False}],
                                   "replies": [{"at_ms": None, "text": "Synthetic session reply"},
                                               {"at_ms": BASE + 10, "text": "Synthetic unprompted"}]}
    record["messages"] = [m for m in record["messages"] if m["kind"] != "final"]
    assert only(colophon, record).turns[0].final_answer == {"text": "Synthetic spoken final", "voice": True}


def test_tools_are_copy_independent_and_summed_from_display_file(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started().command(exit_code=1).task_complete())
    original = copy.deepcopy(record)
    model = only(colophon, record)
    assert model.tools["shell"] == model.turns[0].tools["shell"] == 1
    assert model.tools["shell_failed"] == 1
    model.turns[0].tools["mcp"]["synthetic-server"] = 1
    model.tools["other"]["synthetic-tool"] = 1
    model.turns[0].flags.add("synthetic-test-marker")
    assert record == original


def test_title_uses_earliest_kept_request_with_metadata_sources(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log("synthetic-session").meta(at=BASE)
                    .task_started().user_item("Synthetic later", at=BASE + 50)
                    .user_item("Synthetic earlier\nSynthetic second line", at=BASE + 10).task_complete(at=BASE + 60))
    model = only(colophon, record)
    assert model.title == "Synthetic earlier"
    assert model.title_full == "Synthetic earlier\nSynthetic second line"
    assert model.title_source == "first_user_message"
    metadata = colophon.CodexMetadata(threads={"synthetic-session": {"title": "Synthetic DB"}},
                                     index_titles={"synthetic-session": "Synthetic index"},
                                     desktop_titles={"synthetic-session": "Synthetic desktop"})
    assert only(colophon, record, metadata=metadata).title_source == "session_index"
    assert metadata.threads == {"synthetic-session": {"title": "Synthetic DB"}}


def test_subagent_uses_label_not_user_title_chain(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log("synthetic-child").meta(at=BASE, parent_thread_id="synthetic-parent",
                    agent_path="/root/synthetic_check", agent_nickname="Agent-Alpha", title="Synthetic rollout")
                    .task_started().user_item())
    metadata = colophon.CodexMetadata(threads={"synthetic-child": {"name": "Synthetic DB name"}})
    model = only(colophon, record, metadata=metadata)
    assert model.is_subagent is True
    assert (model.title, model.title_source) == ("synthetic check · Agent-Alpha", "agent_path")
    assert model.parent_id is None
    assert model.children == model.units == []
    assert model.workspace is model.subfolder is model.link is None


def test_running_future_start_never_invents_negative_duration(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started(at=BASE + 2 * HOUR))
    model = only(colophon, record, snapshot=BASE + HOUR)
    assert model.turns[0].status == "running"
    assert model.turns[0].duration_ms is None
    assert model.turns[0].flags == {"live", "unknown_duration"}


def test_meta_less_filename_never_supplies_metadata_identity(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log(name=f"synthetic-{SYNTHETIC_UUID}.jsonl").task_started().user_item())
    metadata = colophon.CodexMetadata(threads={SYNTHETIC_UUID: {"name": "Synthetic wrong DB title"}},
                                     index_titles={SYNTHETIC_UUID: "Synthetic wrong index"},
                                     desktop_titles={SYNTHETIC_UUID: "Synthetic wrong desktop"})
    model = only(colophon, record, metadata=metadata)
    assert model.title == "Synthetic request 1"
    assert model.title_source == "first_user_message"
    assert model.db_info == {}
    assert corpus(colophon, [record], metadata=metadata).db_threads_without_logs == 1


def test_collapsed_voice_without_provenance_is_unreliable(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started(at=BASE).task_complete(at=BASE))
    key = record["turns"][0]["key"]
    record["voice"]["requests"] = [{"text": "Synthetic voice", "at_ms": BASE + 20,
        "turn_key": key, "before_turn": False, "follow_up": False, "reply": None}]
    model = only(colophon, record)
    assert model.turns[0].requests[0]["time_unreliable"] is True
    assert model.user_span_ms is None
    assert "uncertain_timing" in model.flags


def test_running_idle_follows_owned_span_minus_full_active_union(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started(at=BASE + 10)
                    .user_item(at=BASE + 20))
    model = only(colophon, record, snapshot=BASE + 100)
    assert (model.start_ms, model.end_ms) == (BASE, BASE + 20)
    assert model.idle_ms == 20 - 90


@pytest.mark.parametrize("identity", [None, "", " ", 42])
def test_unusable_metadata_id_does_not_merge_or_supply_lookup(colophon, tmp_path, identity):
    synthetic = home(tmp_path)
    records = [parsed(colophon, synthetic.log(name=f"synthetic-{n}.jsonl").meta(at=BASE).user_item())
               for n in range(2)]
    for record in records:
        record["meta"]["id"] = identity
    result = corpus(colophon, records)
    assert len(result.sessions) == 2
    assert set(result.sessions) == {f"file:{r['key']['path']}" for r in records}
    assert all(model.meta["id"] == identity for model in result.sessions.values())


def test_no_turn_voice_reply_survives_without_inventing_reply_clock(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE)
                    .realtime_segment("Synthetic spoken question", at=BASE + 10)
                    .realtime_segment("Synthetic spoken answer", role="assistant", at=BASE + 20))
    model = only(colophon, record)
    assert model.turns == []
    assert model.session_voice["requests"][0]["text"] == "Synthetic spoken question"
    assert model.session_voice["replies"] == [{"at_ms": None, "text": "Synthetic spoken answer"}]


def test_database_adapter_preserves_independent_sources_and_cached_meta(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log("synthetic-id").meta(at=BASE).task_started())
    original = copy.deepcopy(record)
    metadata = colophon.CodexMetadata(threads={"synthetic-id": {
        "cwd": "/synthetic/database/cwd", "git_origin_url": "https://example.invalid/synthetic/db.git",
        "agent_path": "/root/synthetic_db_agent"}})
    model = only(colophon, record, metadata=metadata)
    assert model.db_info == metadata.threads["synthetic-id"]
    assert model.meta["git"]["origin_url"] == "https://example.invalid/synthetic/alpha.git"
    assert model.record == original
    model.db_info["cwd"] = "/synthetic/changed"
    assert metadata.threads["synthetic-id"]["cwd"] == "/synthetic/database/cwd"


def test_newest_display_uses_submillisecond_mtime(colophon, tmp_path):
    synthetic = home(tmp_path)
    first = parsed(colophon, synthetic.log("synthetic-shared", name="a-synthetic.jsonl").meta(at=BASE, title="Synthetic old").user_item())
    second = parsed(colophon, synthetic.log("synthetic-shared", name="z-synthetic.jsonl").meta(at=BASE, title="Synthetic new").user_item())
    first["key"]["mtime_ns"] += 1
    second["key"]["mtime_ns"] += 2
    model = next(iter(corpus(colophon, [first, second]).sessions.values()))
    assert model.record is second


def test_numbering_uses_effective_reported_start(colophon):
    def fact(key, start, end, reported=None):
        return {"key": key, "turn_id": key, "start_ms": start, "end_ms": end,
                "start_src": "record_timestamp", "end_src": "record_timestamp", "start_rec": 0,
                "reported_ms": reported, "ttft_ms": None, "end_kind": "completed", "last_ms": end}
    facts = [fact("synthetic-normal", 40, 50), fact("synthetic-reported", None, 100, 80)]
    turns = colophon.classify_open_turns(facts, mtime_ms=BASE, snapshot_ms=BASE)
    assert [(t.id, t.n, t.start_ms) for t in turns] == [("synthetic-reported", 1, 20), ("synthetic-normal", 2, 40)]


def test_before_turn_reply_facts_survive_without_becoming_final_answer(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE)
                    .realtime_segment("Synthetic before request", at=BASE + 10)
                    .realtime_segment("Synthetic before reply", role="assistant", at=BASE + 20)
                    .task_started(at=BASE + 30).task_complete(at=BASE + 40))
    original = copy.deepcopy(record)
    model = only(colophon, record)
    assert model.turns[0].requests[0]["before_turn"] is True
    assert model.turns[0].final_answer is None
    assert model.record["voice"]["requests"][0]["reply"] == "Synthetic before reply"
    assert model.record == original


def test_unprompted_in_turn_voice_reply_does_not_move_to_session_level(colophon, tmp_path):
    record = parsed(colophon, home(tmp_path).log().meta(at=BASE).task_started(at=BASE + 10)
                    .realtime_segment("Synthetic unprompted turn reply", role="assistant", at=BASE + 20)
                    .task_complete(at=BASE + 30))
    original = copy.deepcopy(record)
    model = only(colophon, record)
    assert record["voice"]["replies"][0]["turn_key"] == record["turns"][0]["key"]
    assert model.session_voice == {"requests": [], "replies": []}
    assert model.turns[0].final_answer is None
    assert model.record["voice"]["replies"][0]["text"] == "Synthetic unprompted turn reply"
    assert model.record == original


@pytest.mark.parametrize("reverse_input", [False, True])
@pytest.mark.parametrize("missing_is_newer", [False, True])
@pytest.mark.parametrize("reserved_prefixes", [1, 3])
def test_generated_file_identity_never_merges_with_true_metadata_id(
        colophon, tmp_path, reverse_input, missing_is_newer, reserved_prefixes):
    synthetic = home(tmp_path)
    missing = parsed(colophon, synthetic.log(name="synthetic-no-meta.jsonl")
                     .task_started().user_item("Synthetic file request"),
                     mtime=BASE + HOUR if missing_is_newer else BASE)
    file_identity = f"file:{missing['key']['path']}"
    true_ids = ["file:" * prefix + missing["key"]["path"]
                for prefix in range(1, reserved_prefixes + 1)]
    real = [parsed(colophon, synthetic.log(identifier, name=f"synthetic-real-{n}.jsonl")
                   .meta(at=BASE).task_started().user_item(f"Synthetic real request {n}"),
                   mtime=BASE if missing_is_newer else BASE + HOUR)
            for n, identifier in enumerate(true_ids)]
    records = [missing, *real]
    original = copy.deepcopy(records)
    metadata = colophon.CodexMetadata(threads={identifier: {"name": f"Synthetic DB title {n}"}
                                               for n, identifier in enumerate(true_ids)})
    result = corpus(colophon, list(reversed(records)) if reverse_input else records, metadata=metadata)
    assert len(result.sessions) == len(records)
    escaped_key = "file:" * (reserved_prefixes + 1) + missing["key"]["path"]
    assert set(result.sessions) == {*true_ids, escaped_key}
    assert file_identity in metadata.threads  # The conflicting spelling is a true ID here.
    file_model = result.sessions[escaped_key]
    assert file_model.records == [missing]
    assert file_model.record["key"]["path"] == missing["key"]["path"]
    assert file_model.title == "Synthetic file request"
    assert file_model.db_info == {}
    assert "no_session_meta" in file_model.flags
    for identifier, source in zip(true_ids, real):
        model = result.sessions[identifier]
        assert model.id == identifier
        assert model.meta["id"] == identifier
        assert model.records == [source]
        assert model.db_info == metadata.threads[identifier]
        assert model.title_source == "database_name"
    assert result.db_threads_without_logs == 0
    assert records == original


def test_final_answers_keep_recorded_precedence_and_last_eligible_voice(colophon, tmp_path):
    log = (home(tmp_path).log().meta(at=BASE)
           .realtime_segment("Synthetic before first")
           .realtime_segment("Synthetic excluded first reply", role="assistant")
           .task_started("synthetic-first").user_item()
           .realtime_segment("Synthetic first spoken request")
           .realtime_segment("Synthetic first spoken reply", role="assistant")
           .agent_item("Synthetic earlier recorded final")
           .agent_item("Synthetic last recorded final")
           .realtime_segment("Synthetic later spoken request")
           .realtime_segment("Synthetic later spoken reply", role="assistant")
           .task_complete()
           .realtime_segment("Synthetic before second")
           .realtime_segment("Synthetic excluded second reply", role="assistant")
           .task_started("synthetic-second")
           .realtime_segment("Synthetic answered request")
           .realtime_segment("Synthetic retained voice reply", role="assistant")
           .task_complete()
           .realtime_segment("Synthetic before third")
           .realtime_segment("Synthetic excluded third reply", role="assistant")
           .task_started("synthetic-third").task_complete()
           .task_started("synthetic-fourth")
           .realtime_segment("Synthetic fourth first request")
           .realtime_segment("Synthetic fourth first reply", role="assistant")
           .realtime_segment("Synthetic fourth last request")
           .realtime_segment("Synthetic fourth last reply", role="assistant")
           .realtime_segment("Synthetic unanswered request").task_complete())
    record = parsed(colophon, log)
    original = copy.deepcopy(record)
    model = only(colophon, record)
    expected = [{"text": "Synthetic last recorded final", "voice": False},
                {"text": "Synthetic retained voice reply", "voice": True}, None,
                {"text": "Synthetic fourth last reply", "voice": True}]
    assert [turn.final_answer for turn in model.turns] == expected
    assert [colophon.select_final_answer(record, turn.id) for turn in model.turns] == expected
    assert record == original


@pytest.mark.parametrize("turn_count", [100, 200])
def test_assembly_bounds_retained_fact_visits_as_sessions_grow(colophon, tmp_path, turn_count):
    # Instrument source access, not a particular indexing implementation or
    # wall-clock speed: a growing session must not reread its whole transcript
    # for every turn. This still allows several independent linear passes.
    visits = {"count": 0}
    class CountedFacts(list):
        def __iter__(self):
            for value in super().__iter__():
                visits["count"] += 1
                yield value

        def __reversed__(self):
            for value in super().__reversed__():
                visits["count"] += 1
                yield value

        def __getitem__(self, index):
            value = super().__getitem__(index)
            visits["count"] += len(value) if isinstance(index, slice) else 1
            return value

    log = home(tmp_path).log().meta(at=BASE)
    for number in range(turn_count):
        log.task_started(f"synthetic-turn-{number}").user_item(f"Synthetic request {number}")
        log.realtime_segment(f"Synthetic voice request {number}")
        log.realtime_segment(f"Synthetic voice reply {number}", role="assistant")
        if number % 2 == 0:
            log.agent_item(f"Synthetic final {number}")
        log.task_complete()
    record = parsed(colophon, log)
    source_count = len(record["messages"]) + len(record["voice"]["requests"]) + len(record["turns"])
    record["messages"] = CountedFacts(record["messages"])
    record["voice"]["requests"] = CountedFacts(record["voice"]["requests"])
    model = only(colophon, record)
    assert len(model.turns) == turn_count
    assert all(turn.final_answer == {"text": f"Synthetic final {n}", "voice": False}
               if n % 2 == 0 else turn.final_answer == {"text": f"Synthetic voice reply {n}", "voice": True}
               for n, turn in enumerate(model.turns))
    assert visits["count"] <= 8 * source_count
