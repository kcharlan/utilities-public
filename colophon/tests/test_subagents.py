"""Subagent graph and turn evidence from isolated, conspicuously synthetic logs."""

import copy

import pytest

from fixturegen import CodexHome

BASE = 1_893_974_400_000
HOUR = 3_600_000


def record(colophon, log, *, mtime=BASE):
    path = log.write()
    return colophon.parse_log_file(path, size=path.stat().st_size,
                                   mtime_ns=mtime * 1_000_000, archived=False)


def parent_log(home, identifier="synthetic-parent"):
    return (home.log(identifier).meta(at=BASE)
            .task_started("synthetic-turn-1", at=BASE + 10)
            .task_complete(at=BASE + 100)
            .task_started("synthetic-turn-2", at=BASE + 110)
            .task_complete(at=BASE + 200)
            .task_started("synthetic-turn-3", at=BASE + 210)
            .task_complete(at=BASE + 300))


def child_log(home, identifier="synthetic-child", *, parent="synthetic-parent",
              depth=1, path="/root/synthetic_task", created=BASE + 50, **fields):
    return (home.log(identifier).meta(at=created, parent_thread_id=parent,
                                     depth=depth, agent_path=path, **fields)
            .task_started("synthetic-child-turn", at=created + 1)
            .task_complete(at=created + 10))


def assembled(colophon, records, *, metadata=None, snapshot=BASE + HOUR):
    return colophon.build_corpus(records, metadata or colophon.CodexMetadata(), snapshot)


def link(colophon, result, metadata=None, *, snapshot=BASE + HOUR):
    colophon.link_subagents(result, metadata or colophon.CodexMetadata(), snapshot)
    return result.sessions["synthetic-child"]


@pytest.mark.parametrize("method", ["activity", "spawn_call", "root_turn_id", "inferred"])
def test_spawn_method_precedence_and_fallback(colophon, tmp_path, method):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home).usage_record(
        root_turn_id="synthetic-turn-3", at=BASE + 70))
    parent["links"]["activities"] = [{"kind": "started", "child_id": "synthetic-child",
                                        "turn_key": "synthetic-turn-2"}]
    parent["links"]["spawn_calls"] = [{"task_name": "/root/synthetic_task",
                                         "at_ms": BASE + 20, "turn_key": "synthetic-turn-1"}]
    if method != "activity":
        parent["links"]["activities"][0]["turn_key"] = "synthetic-missing-turn"
    if method in ("root_turn_id", "inferred"):
        parent["links"]["spawn_calls"][0]["task_name"] = "/root/synthetic_other"
    if method == "inferred":
        child["usage_records"][0]["thread_id"] = "synthetic-other-thread"
    originals = copy.deepcopy([parent, child])
    result = assembled(colophon, [parent, child])
    model = link(colophon, result)
    expected = {"activity": "synthetic-turn-2", "spawn_call": "synthetic-turn-1",
                "root_turn_id": "synthetic-turn-3", "inferred": "synthetic-turn-1"}[method]
    assert model.parent_id == "synthetic-parent"
    assert model.link == {"spawn_turn": expected, "interaction_turns": [], "method": method}
    assert result.sessions["synthetic-parent"].children == ["synthetic-child"]
    assert next(t for t in result.sessions["synthetic-parent"].turns if t.id == expected).spawned == [model.id]
    assert result.inferred_links == ([model.id] if method == "inferred" else [])
    assert [parent, child] == originals


def test_latest_spawn_before_creation_and_later_spawns_fail_over(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home).usage_record(root_turn_id="synthetic-turn-3"))
    parent["links"]["spawn_calls"] = [
        {"task_name": "/root/synthetic_task", "at_ms": BASE + 40, "turn_key": "synthetic-turn-2"},
        {"task_name": "/root/synthetic_task", "at_ms": BASE + 10, "turn_key": "synthetic-turn-1"},
        {"task_name": "/root/synthetic_task", "at_ms": BASE + 60, "turn_key": "synthetic-turn-3"}]
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link["spawn_turn"] == "synthetic-turn-2"
    assert model.link["method"] == "spawn_call"
    for entry in parent["links"]["spawn_calls"]:
        entry["at_ms"] = BASE + 60
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link["spawn_turn"] == "synthetic-turn-3"
    assert model.link["method"] == "root_turn_id"


def test_spawn_at_creation_is_eligible(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home))
    parent["links"]["spawn_calls"] = [{"task_name": "/root/synthetic_task", "at_ms": BASE + 50,
                                         "turn_key": "synthetic-turn-2"}]
    assert link(colophon, assembled(colophon, [parent, child])).link["method"] == "spawn_call"


def test_interactions_all_sources_deduplicated_in_turn_order(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home))
    parent["links"]["activities"] = [
        {"kind": "started", "child_id": "synthetic-child", "turn_key": "synthetic-turn-2"},
        {"kind": "interacted", "child_id": "synthetic-child", "turn_key": "synthetic-turn-3"},
        {"kind": "interacted", "child_id": "synthetic-child", "turn_key": "synthetic-turn-1"}]
    parent["links"]["targets"] = [{"target": "/root/synthetic_task", "turn_key": "synthetic-turn-2"},
                                  {"target": "synthetic_task", "turn_key": "synthetic-turn-3"}]
    parent["links"]["collab_receivers"] = [
        {"child_id": "synthetic-child", "turn_key": "synthetic-turn-1"},
        {"child_id": "synthetic-child", "turn_key": "synthetic-missing-turn"}]
    result = assembled(colophon, [child, parent])
    model = link(colophon, result)
    assert model.link == {"spawn_turn": "synthetic-turn-2", "method": "activity",
                          "interaction_turns": ["synthetic-turn-1", "synthetic-turn-3"]}
    assert [t.used for t in result.sessions["synthetic-parent"].turns] == [[model.id], [], [model.id]]
    # Linking at a second snapshot does not duplicate graph or turn annotations.
    link(colophon, result)
    assert result.sessions["synthetic-parent"].children == [model.id]
    assert [t.used for t in result.sessions["synthetic-parent"].turns] == [[model.id], [], [model.id]]


@pytest.mark.parametrize("target,matches", [("synthetic_task", True), ("/root/synthetic_task", True),
                                           ("/root", False), ("/root/synthetic_other", False)])
def test_d10_targets_match_all_repeated_paths(colophon, tmp_path, target, matches):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    children = [record(colophon, child_log(home, identifier=name))
                for name in ("synthetic-child", "synthetic-child-copy")]
    parent["links"]["targets"] = [{"target": target, "turn_key": "synthetic-turn-3"}]
    result = assembled(colophon, [parent, *children])
    link(colophon, result)
    for name in ("synthetic-child", "synthetic-child-copy"):
        assert result.sessions[name].link["interaction_turns"] == (["synthetic-turn-3"] if matches else [])


def test_nested_depth_is_order_independent_and_root_turn_ignored_at_depth_two(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    first = record(colophon, child_log(home, depth=None))
    second = record(colophon, child_log(home, "synthetic-grandchild", parent="synthetic-child",
                                        depth=None, path="/root/synthetic_task/nested", created=BASE + 500)
                    .usage_record(root_turn_id="synthetic-child-turn"))
    result = assembled(colophon, [second, first, parent])
    link(colophon, result)
    assert result.sessions["synthetic-parent"].depth == 0
    assert result.sessions["synthetic-child"].depth == 1
    nested = result.sessions["synthetic-grandchild"]
    assert nested.depth == 2
    assert nested.parent_id == "synthetic-child"
    assert nested.link == {"spawn_turn": None, "interaction_turns": [], "method": None}
    assert result.sessions["synthetic-parent"].children == ["synthetic-child"]
    assert result.sessions["synthetic-child"].children == ["synthetic-grandchild"]


def test_child_sorting_and_explicit_depth(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    late = record(colophon, child_log(home, "synthetic-late", created=BASE + 80, depth=7))
    early = record(colophon, child_log(home, "synthetic-early", created=BASE + 20))
    unknown = record(colophon, child_log(home, "synthetic-unknown"))
    unknown["owned_span"]["first_ms"] = None
    result = assembled(colophon, [late, unknown, early, parent])
    colophon.link_subagents(result, colophon.CodexMetadata(), BASE + HOUR)
    assert result.sessions["synthetic-parent"].children == ["synthetic-early", "synthetic-late", "synthetic-unknown"]
    assert result.sessions["synthetic-late"].depth == 7


@pytest.mark.parametrize("parent", ["synthetic-missing", None, " "])
def test_orphan_missing_parent(colophon, tmp_path, parent):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    child = record(colophon, child_log(home))
    child["meta"]["parent_thread_id"] = parent
    result = assembled(colophon, [child])
    model = link(colophon, result)
    assert model.kind == "orphan"
    assert model.is_subagent is True
    assert "orphaned" in model.flags
    assert model.parent_id == (parent if parent == "synthetic-missing" else None)
    assert result.orphaned_subagents == [model.id]
    assert model.link == {"spawn_turn": None, "interaction_turns": [], "method": None}


def test_edge_table_takes_precedence_even_when_parent_log_missing(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    alternate = record(colophon, parent_log(home, "synthetic-alternate"))
    child = record(colophon, child_log(home))
    metadata = colophon.CodexMetadata(spawn_parents={"synthetic-child": "synthetic-alternate"})
    result = assembled(colophon, [parent, alternate, child], metadata=metadata)
    model = link(colophon, result, metadata)
    assert model.parent_id == "synthetic-alternate"
    assert result.sessions["synthetic-parent"].children == []
    metadata.spawn_parents["synthetic-child"] = "synthetic-missing"
    link(colophon, result, metadata)
    assert model.kind == "orphan"
    assert result.sessions["synthetic-alternate"].children == []
    assert result.orphaned_subagents == [model.id]


def test_forked_badge_and_non_subagent_forked_from(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home, forked_from_id="synthetic-parent"))
    standalone = record(colophon, home.log("synthetic-fork").meta(
        at=BASE + 50, forked_from_id="synthetic-parent").task_started(at=BASE + 60))
    result = assembled(colophon, [parent, child, standalone])
    model = link(colophon, result)
    assert "forked" in model.flags
    assert model.forked_from is None
    fork = result.sessions["synthetic-fork"]
    assert fork.forked_from == "synthetic-parent"
    assert fork.kind == "session"
    assert "forked" not in fork.flags
    standalone["meta"]["forked_from_id"] = "synthetic-unavailable-title"
    result = assembled(colophon, [standalone])
    colophon.link_subagents(result, colophon.CodexMetadata(), BASE + HOUR)
    assert result.sessions["synthetic-fork"].forked_from == "synthetic-unavailable-title"


@pytest.mark.parametrize("status,instant,matches", [("running", BASE + 500, True),
                                                   ("abandoned", BASE + 50, True),
                                                   ("abandoned", BASE + 70, False)])
def test_inferred_running_snapshot_and_abandoned_last_record(colophon, tmp_path, status, instant, matches):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, home.log("synthetic-parent").meta(at=BASE)
                    .task_started("synthetic-turn-1", at=BASE + 10).user_item(at=BASE + 50))
    child = record(colophon, child_log(home, created=instant))
    snapshot = BASE + (HOUR if status == "running" else 3 * HOUR)
    result = assembled(colophon, [parent, child], snapshot=snapshot)
    assert result.sessions["synthetic-parent"].turns[0].status == status
    model = link(colophon, result, snapshot=snapshot)
    assert model.link["method"] == ("inferred" if matches else None)


@pytest.mark.parametrize("invalid", [None, True, "synthetic-time", float("inf")])
def test_invalid_creation_time_does_not_infer_or_choose_spawn(colophon, tmp_path, invalid):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home))
    child["meta"]["created_at_ms"] = invalid
    parent["links"]["spawn_calls"] = [{"task_name": "/root/synthetic_task", "at_ms": invalid,
                                         "turn_key": "synthetic-turn-1"}]
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link["method"] is None
    assert model.created_at_ms is None


def test_missing_paths_and_thread_ids_never_match_none(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home, created=BASE + 500).usage_record(root_turn_id="synthetic-turn-1"))
    child["meta"]["agent_path"] = None
    child["usage_records"][0]["thread_id"] = None
    parent["links"]["spawn_calls"] = [{"task_name": None, "at_ms": BASE + 10, "turn_key": "synthetic-turn-1"}]
    parent["links"]["targets"] = [{"target": None, "turn_key": "synthetic-turn-2"}]
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link == {"spawn_turn": None, "interaction_turns": [], "method": None}


def test_db_agent_path_fallback_preserves_original_sources(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home))
    child["meta"]["agent_path"] = None
    parent["links"]["spawn_calls"] = [{"task_name": "/root/synthetic_db_task", "at_ms": BASE + 20,
                                         "turn_key": "synthetic-turn-2"}]
    metadata = colophon.CodexMetadata(threads={"synthetic-child": {"agent_path": "/root/synthetic_db_task"}})
    result = assembled(colophon, [parent, child], metadata=metadata)
    model = link(colophon, result, metadata)
    assert model.agent_path == "/root/synthetic_db_task"
    assert model.link["method"] == "spawn_call"
    assert child["meta"]["agent_path"] is None
    assert model.db_info == metadata.threads[model.id]


def test_generated_filename_identity_cannot_be_parent_or_edge_child(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, home.log(name="synthetic-parent.jsonl").task_started())
    child = record(colophon, child_log(home, parent=f"file:{parent['key']['path']}"))
    metadata = colophon.CodexMetadata(spawn_parents={"synthetic-parent": "synthetic-child"})
    result = assembled(colophon, [parent, child], metadata=metadata)
    model = link(colophon, result, metadata)
    assert model.kind == "orphan"
    file_model = result.sessions[f"file:{parent['key']['path']}"]
    assert file_model.kind == "session"
    assert file_model.parent_id is None
    assert file_model.children == []


@pytest.mark.parametrize("edge", [None, True, " "])
def test_invalid_edge_parent_falls_back_to_metadata(colophon, tmp_path, edge):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    records = [record(colophon, parent_log(home)), record(colophon, child_log(home))]
    metadata = colophon.CodexMetadata(spawn_parents={"synthetic-child": edge})
    assert link(colophon, assembled(colophon, records), metadata).parent_id == "synthetic-parent"


def test_ambiguous_latest_spawn_and_overlapping_intervals_keep_unknown(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home))
    parent["links"]["spawn_calls"] = [
        {"task_name": "/root/synthetic_task", "at_ms": BASE + 20, "turn_key": name}
        for name in ("synthetic-turn-1", "synthetic-turn-2")]
    parent["turns"][1]["start_ms"] = BASE + 10
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link == {"spawn_turn": None, "interaction_turns": [], "method": None}


def test_parent_cycles_are_orphans_and_do_not_invent_depth(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    first = record(colophon, child_log(home, parent="synthetic-cycle", depth=None))
    second = record(colophon, child_log(home, "synthetic-cycle", parent="synthetic-child", depth=None))
    result = assembled(colophon, [first, second])
    link(colophon, result)
    assert set(result.orphaned_subagents) == {"synthetic-child", "synthetic-cycle"}
    for model in result.sessions.values():
        assert model.parent_id is None
        assert model.kind == "orphan"
        assert model.depth is None
        assert model.children == []


def test_root_turn_id_must_name_real_parent_turn_not_generated_key(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    parent["turns"][0]["turn_id"] = None
    child = record(colophon, child_log(home, created=BASE + 500)
                   .usage_record(root_turn_id="synthetic-turn-1"))
    assert link(colophon, assembled(colophon, [parent, child])).link["method"] is None


def test_real_parser_link_evidence_reaches_turn_models(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, home.log("synthetic-parent").meta(at=BASE)
                    .task_started("synthetic-turn-1", at=BASE + 10)
                    .function_call("spawn_agent", namespace="collaboration", at=BASE + 20)
                    .function_output(output={"task_name": "/root/synthetic_task"}, at=BASE + 30)
                    .task_complete(at=BASE + 100)
                    .task_started("synthetic-turn-2", at=BASE + 110)
                    .subagent_activity("synthetic-child", kind="interacted", at=BASE + 120)
                    .collab_wait(["synthetic-child"], at=BASE + 130)
                    .function_call("send_message", namespace="collaboration",
                                   arguments={"target": "synthetic_task"}, at=BASE + 140)
                    .task_complete(at=BASE + 200))
    child = record(colophon, child_log(home))
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link == {"spawn_turn": "synthetic-turn-1", "method": "spawn_call",
                          "interaction_turns": ["synthetic-turn-2"]}


def test_conflicting_started_activities_fail_over_but_duplicates_are_evidence(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home))
    parent["links"]["activities"] = [
        {"kind": "started", "child_id": "synthetic-child", "turn_key": key}
        for key in ("synthetic-turn-1", "synthetic-turn-2")]
    parent["links"]["spawn_calls"] = [{"task_name": "/root/synthetic_task", "at_ms": BASE + 20,
                                         "turn_key": "synthetic-turn-3"}]
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link["method"] == "spawn_call"
    assert model.link["spawn_turn"] == "synthetic-turn-3"
    parent["links"]["activities"][1]["turn_key"] = "synthetic-turn-1"
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link["method"] == "activity"
    assert model.link["spawn_turn"] == "synthetic-turn-1"


@pytest.mark.parametrize("invalid_turn", [None, "synthetic-missing-turn"])
def test_latest_spawn_with_unusable_turn_does_not_borrow_older_spawn(colophon, tmp_path, invalid_turn):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home).usage_record(root_turn_id="synthetic-turn-3"))
    parent["links"]["spawn_calls"] = [
        {"task_name": "/root/synthetic_task", "at_ms": BASE + 20, "turn_key": "synthetic-turn-1"},
        {"task_name": "/root/synthetic_task", "at_ms": BASE + 40, "turn_key": invalid_turn}]
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link["method"] == "root_turn_id"
    assert model.link["spawn_turn"] == "synthetic-turn-3"


@pytest.mark.parametrize("source", ["activities", "targets", "collab_receivers"])
def test_each_interaction_source_independently_establishes_usage(colophon, tmp_path, source):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home, created=BASE + 500))
    evidence = {"activities": {"kind": "interacted", "child_id": "synthetic-child"},
                "targets": {"target": "synthetic_task"},
                "collab_receivers": {"child_id": "synthetic-child"}}
    parent["links"][source] = [{**evidence[source], "turn_key": "synthetic-turn-2"}]
    result = assembled(colophon, [parent, child])
    model = link(colophon, result)
    assert model.link == {"spawn_turn": None, "method": None,
                          "interaction_turns": ["synthetic-turn-2"]}
    assert result.sessions["synthetic-parent"].turns[1].used == [model.id]


@pytest.mark.parametrize("depth", [None, True, "1", -1])
def test_invalid_depth_falls_back_to_parent_plus_one(colophon, tmp_path, depth):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home, depth=depth, created=BASE + 500)
                   .usage_record(root_turn_id="synthetic-turn-2"))
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.depth == 1
    assert model.link["method"] == "root_turn_id"


@pytest.mark.parametrize("instant", [BASE + 10, BASE + 100])
def test_inferred_completed_turn_interval_is_inclusive(colophon, tmp_path, instant):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home, created=instant))
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link["method"] == "inferred"
    assert model.link["spawn_turn"] == "synthetic-turn-1"


@pytest.mark.parametrize("method", ["activity", "root_turn_id"])
def test_non_temporal_evidence_still_links_with_unknown_creation_clock(colophon, tmp_path, method):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home).usage_record(root_turn_id="synthetic-turn-2")
                   .usage_record(root_turn_id="synthetic-turn-3"))
    child["meta"]["created_at_ms"] = None
    if method == "activity":
        parent["links"]["activities"] = [{"kind": "started", "child_id": "synthetic-child",
                                            "turn_key": "synthetic-turn-1"}]
    model = link(colophon, assembled(colophon, [parent, child]))
    assert model.link["method"] == method
    assert model.link["spawn_turn"] == ("synthetic-turn-1" if method == "activity" else "synthetic-turn-2")


def test_nested_relative_target_uses_child_path_parent_and_rollout_path_wins(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home, path="/root/synthetic_parent/nested"))
    parent["links"]["targets"] = [{"target": "nested", "turn_key": "synthetic-turn-2"},
                                  {"target": "/root", "turn_key": "synthetic-turn-3"}]
    metadata = colophon.CodexMetadata(threads={"synthetic-child": {"agent_path": "/root/synthetic_other"}})
    model = link(colophon, assembled(colophon, [parent, child], metadata=metadata), metadata)
    assert model.agent_path == "/root/synthetic_parent/nested"
    assert model.link["interaction_turns"] == ["synthetic-turn-2"]


def test_forked_badge_requires_usable_parent_identity_equality(colophon, tmp_path):
    home = CodexHome(tmp_path / "synthetic-codex-home")
    parent = record(colophon, parent_log(home))
    child = record(colophon, child_log(home, forked_from_id="synthetic-other"))
    result = assembled(colophon, [parent, child])
    assert "forked" not in link(colophon, result).flags
    child["meta"].update(forked_from_id=None, parent_thread_id=None)
    assert "forked" not in link(colophon, assembled(colophon, [child])).flags
