"""Synthetic request, final-answer and record-position voice contracts."""

import json
import statistics
import time

import pytest

from fixturegen import CodexHome, iso

BASE = 1_893_974_400_000  # 2030-01-07 UTC, fixture generator's default day.
HEADINGS = ("## My request:", "## My request for Codex:")
WRAPPERS = ("# Files mentioned by the user", "# Files pasted by the user",
            "# Browser comments", "<in-app-browser-context")
PREFIXES = ("# AGENTS.md", "<environment_context>", "<INSTRUCTIONS>",
            "<external_codex_apps_open_page>", "<permissions instructions>",
            "<recommended_plugins>", "<skills_instructions>",
            "<codex_apps_open_page_instructions>", "<realtime_delegation>",
            "<skill>", "<turn_aborted>")


def parse(colophon, log):
    path = log.write()
    stat = path.stat()
    return colophon.parse_log_file(path, size=stat.st_size, mtime_ns=stat.st_mtime_ns, archived=False)


def new_log(tmp_path):
    return CodexHome(tmp_path / "synthetic-codex-home").log().meta(at=BASE)


def test_rule_lists_are_complete(colophon):
    assert colophon.REQUEST_HEADINGS == HEADINGS
    assert colophon.CONTEXT_WRAPPERS == WRAPPERS
    assert colophon.INJECTED_PREFIXES == PREFIXES
    assert colophon.ANSWER_TAG == "send_user_message_question_reply"


@pytest.mark.parametrize("wrapper", WRAPPERS)
@pytest.mark.parametrize("heading", HEADINGS)
def test_every_wrapper_keeps_text_after_first_exact_heading(colophon, wrapper, heading):
    part = f"  {wrapper}\nSynthetic context\n  {heading}  \n Synthetic request 1 \n{HEADINGS[1]}\nSynthetic request 2"
    assert colophon.classify_user_part(part) == ("text", f"Synthetic request 1 \n{HEADINGS[1]}\nSynthetic request 2")


@pytest.mark.parametrize("wrapper", WRAPPERS)
def test_every_wrapper_without_heading_is_dropped(colophon, wrapper):
    assert colophon.classify_user_part(f"\t{wrapper}\nSynthetic context") is None
    assert colophon.classify_user_part(f"{wrapper}\n## My request: extra\nSynthetic context") is None


@pytest.mark.parametrize("prefix", PREFIXES)
def test_every_injected_prefix_is_dropped(colophon, prefix):
    assert colophon.classify_user_part(f" \n{prefix}\n{HEADINGS[0]}\nSynthetic injection") is None


def test_classification_order_and_answer_tag(colophon):
    assert colophon.classify_user_part(f"{WRAPPERS[0]}\n{HEADINGS[0]}\n{PREFIXES[0]}") == ("text", PREFIXES[0])
    assert colophon.classify_user_part("  <send_user_message_question_reply> Synthetic answer </send_user_message_question_reply> ") == ("answer", "Synthetic answer")
    assert colophon.classify_user_part("  Synthetic request 1  ") == ("text", "Synthetic request 1")


@pytest.mark.parametrize("part", ["<image synthetic>", " </image> ", "<image>"])
def test_image_text_parts_are_dropped(colophon, part):
    assert colophon.classify_user_part(part) is None


def test_d11_assembly_and_image_count(colophon, tmp_path):
    content = [{"type": "text", "text": "Synthetic request 1"},
               {"type": "input_text", "text": "<send_user_message_question_reply>Synthetic answer</send_user_message_question_reply>"},
               {"type": "text", "text": "<image synthetic>"},
               *({"type": t} for t in ("local_image", "image", "input_image")),
               {"type": "reasoning", "text": "Synthetic excluded"}]
    result = parse(colophon, new_log(tmp_path).task_started().user_item(content=content))
    assert result["messages"] == [{"role": "user", "kind": "answer", "text": "Synthetic request 1\n\nSynthetic answer",
                                   "images": 3, "at_ms": BASE + 2, "ts_src": "completed_at_ms",
                                   "turn_key": "synthetic-turn-1", "rec": 2}]


def test_image_only_message_is_kept(colophon, tmp_path):
    result = parse(colophon, new_log(tmp_path).task_started().user_item(content=[{"type": "input_image"}, {"type": "image"}]))
    assert result["messages"][0]["text"] == "+ 2 images"
    assert result["messages"][0]["images"] == 2


def test_all_mid_turn_requests_are_kept(colophon, tmp_path):
    result = parse(colophon, new_log(tmp_path).task_started().user_item("Synthetic request 1")
                   .agent_item("Synthetic commentary", phase="commentary")
                   .user_item("Synthetic follow-up").user_event_legacy("Synthetic request 3").task_complete())
    assert [m["text"] for m in result["messages"]] == ["Synthetic request 1", "Synthetic follow-up", "Synthetic request 3"]
    assert {m["turn_key"] for m in result["messages"]} == {"synthetic-turn-1"}


def test_response_precedence_is_per_turn_and_before_dedup(colophon, tmp_path):
    log = new_log(tmp_path).task_started("synthetic-turn-a")
    log.user_response("Synthetic fallback a").agent_response("Synthetic fallback final a")
    log.agent_item("Synthetic commentary", phase="commentary").task_complete()
    log.task_started("synthetic-turn-b").user_response("Synthetic fallback b").agent_response("Synthetic fallback final b").task_complete()
    result = parse(colophon, log)
    assert [m["text"] for m in result["messages"]] == ["Synthetic fallback b", "Synthetic fallback final b"]


@pytest.mark.parametrize("role", ["developer", "system", "synthetic-invalid-role"])
def test_non_user_assistant_roles_are_never_stored(colophon, tmp_path, role):
    result = parse(colophon, new_log(tmp_path).task_started().user_response("Synthetic excluded", role=role))
    assert result["messages"] == []


@pytest.mark.parametrize("family", ["item", "event", "response"])
@pytest.mark.parametrize("phase", [None, "commentary", "final_answer"])
def test_only_final_answer_phase_is_stored(colophon, tmp_path, family, phase):
    log = new_log(tmp_path).task_started()
    {"item": log.agent_item, "event": log.agent_event_legacy, "response": log.agent_response}[family]("Synthetic final", phase=phase)
    result = parse(colophon, log)
    assert [m["kind"] for m in result["messages"]] == (["final"] if phase == "final_answer" else [])


def test_dedup_prefers_item_and_preserves_same_family_repeats(colophon, tmp_path):
    log = new_log(tmp_path).task_started()
    log.user_event_legacy(at=BASE + 2).user_item(at=BASE + 3).user_item(at=BASE + 4)
    result = parse(colophon, log)
    assert [m["rec"] for m in result["messages"]] == [3, 4]


def test_dedup_compares_only_kept_copies(colophon, tmp_path):
    # Event at +10s is discarded; it must not discard response at +20s.
    log = new_log(tmp_path).user_item(at=BASE, turn_id="synthetic-unknown")
    log.user_event_legacy(at=BASE + 10_000).user_response(at=BASE + 20_000, turn_id="synthetic-unknown")
    result = parse(colophon, log)
    assert [m["rec"] for m in result["messages"]] == [1, 3]


@pytest.mark.parametrize("delta, count", [(10_000, 1), (10_001, 2), (-10_000, 1), (-10_001, 2)])
def test_dedup_ten_second_boundary(colophon, tmp_path, delta, count):
    result = parse(colophon, new_log(tmp_path).task_started().user_item(at=BASE + 20_000)
                   .user_event_legacy(at=BASE + 20_000 + delta))
    assert len(result["messages"]) == count


def test_different_turn_ids_do_not_dedup(colophon, tmp_path):
    log = new_log(tmp_path).task_started("synthetic-turn-a").user_item(at=BASE + 2)
    log.task_complete().task_started("synthetic-turn-b").user_event_legacy(at=BASE + 5, turn_id="synthetic-turn-b")
    result = parse(colophon, log)
    assert len(result["messages"]) == 2


@pytest.mark.parametrize("times, count", [([None, None], 1), ([None, BASE + 2], 2), ([BASE + 2, None], 2)])
def test_unknown_times_match_only_other_unknown_times(colophon, tmp_path, times, count):
    log = new_log(tmp_path).task_started()
    log.raw((json.dumps({"type": "event_msg", "timestamp": iso(times[0]) if times[0] is not None else "synthetic-invalid",
                        "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "Synthetic duplicate"}]}}}) + "\n").encode())
    log.raw((json.dumps({"type": "event_msg", "timestamp": iso(times[1]) if times[1] is not None else "synthetic-invalid",
                        "payload": {"type": "user_message", "message": "Synthetic duplicate"}}) + "\n").encode())
    assert len(parse(colophon, log)["messages"]) == count


def test_missing_turn_id_matches_any_other_family_turn(colophon, tmp_path):
    log = new_log(tmp_path).task_started().user_item(at=BASE + 2)
    log.task_complete().user_event_legacy(at=BASE + 3)
    assert len(parse(colophon, log)["messages"]) == 1


def test_explicit_message_before_start_gets_matching_turn_key(colophon, tmp_path):
    result = parse(colophon, new_log(tmp_path).user_item().task_started().task_complete())
    assert result["messages"][0]["turn_key"] == "synthetic-turn-1"


def test_invalid_content_does_not_become_text(colophon, tmp_path):
    log = new_log(tmp_path).task_started().user_item(content=[None, "Synthetic malformed", {"type": "text", "text": 3},
                                                           {"type": "text", "text": "  "}, {"type": "input_image"}])
    assert parse(colophon, log)["messages"][0]["text"] == "+ 1 images"


def test_unclosed_answer_keeps_known_text_without_inventing_tags(colophon):
    assert colophon.classify_user_part("<send_user_message_question_reply>Synthetic answer") == ("answer", "Synthetic answer")


def test_lone_surrogate_text_is_retained(colophon, tmp_path):
    assert parse(colophon, new_log(tmp_path).task_started().user_item("Synthetic \ud800"))["messages"][0]["text"] == "Synthetic \ud800"


def test_inherited_text_and_voice_are_excluded(colophon, tmp_path):
    log = CodexHome(tmp_path / "synthetic-codex-home").log().meta(at=BASE + 10_000)
    log.user_item("Synthetic inherited", at=BASE).realtime_segment("Synthetic inherited voice", at=BASE)
    log.task_started(at=BASE + 12_000).user_item("Synthetic owned").realtime_segment("Synthetic owned voice")
    result = parse(colophon, log)
    assert [m["text"] for m in result["messages"]] == ["Synthetic owned"]
    assert [v["text"] for v in result["voice"]["requests"]] == ["Synthetic owned voice"]


def test_voice_groups_segments_and_places_by_record_not_clock(colophon, tmp_path):
    log = new_log(tmp_path).task_started(at=BASE + 100)
    log.realtime_segment("Synthetic first", at=BASE + 9000).world_state()
    log.realtime_segment("Synthetic second", at=BASE + 8000)
    log.realtime_segment("Synthetic reply first", role="assistant", at=BASE + 200)
    log.realtime_segment("Synthetic reply second", role="assistant", at=BASE + 300).task_complete(at=BASE + 400)
    result = parse(colophon, log)
    assert result["voice"] == {"requests": [{"text": "Synthetic first Synthetic second", "at_ms": BASE + 9000,
                                            "turn_key": "synthetic-turn-1", "before_turn": False, "follow_up": False,
                                            "reply": "Synthetic reply first Synthetic reply second"}], "replies": []}


def test_voice_before_between_and_after_turns(colophon, tmp_path):
    log = new_log(tmp_path).realtime_segment("Synthetic before").realtime_segment("Synthetic reply before", role="assistant")
    log.task_started("synthetic-turn-a").task_complete()
    log.realtime_segment("Synthetic between").task_started("synthetic-turn-b").task_complete()
    log.realtime_segment("Synthetic reply between", role="assistant")
    log.realtime_segment("Synthetic after").realtime_segment("Synthetic reply after", role="assistant")
    requests = parse(colophon, log)["voice"]["requests"]
    assert [(v["turn_key"], v["before_turn"], v["follow_up"], v["reply"]) for v in requests] == [
        ("synthetic-turn-a", True, False, "Synthetic reply before"),
        ("synthetic-turn-b", True, False, "Synthetic reply between"),
        ("synthetic-turn-b", False, True, "Synthetic reply after")]


def test_voice_no_turns_stays_session_level(colophon, tmp_path):
    log = new_log(tmp_path).realtime_segment("Synthetic standalone reply", role="assistant")
    log.realtime_segment("Synthetic request").realtime_segment("Synthetic reply", role="assistant")
    result = parse(colophon, log)
    assert result["voice"]["replies"] == [{"text": "Synthetic standalone reply", "at_ms": BASE + 1, "turn_key": None}]
    assert result["voice"]["requests"] == [{"text": "Synthetic request", "at_ms": BASE + 2, "turn_key": None,
                                            "before_turn": False, "follow_up": False, "reply": "Synthetic reply"}]


def test_reply_without_request_uses_most_recent_started_turn(colophon, tmp_path):
    log = new_log(tmp_path).task_started().task_complete().realtime_segment("Synthetic orphan reply", role="assistant")
    result = parse(colophon, log)
    assert result["voice"]["replies"] == [{"text": "Synthetic orphan reply", "at_ms": BASE + 3, "turn_key": "synthetic-turn-1"}]
    assert colophon.select_final_answer(result, "synthetic-turn-1") is None


def test_reply_after_completion_stays_with_inside_request(colophon, tmp_path):
    log = new_log(tmp_path).task_started().realtime_segment("Synthetic inside").task_complete()
    log.realtime_segment("Synthetic reply after completion", role="assistant")
    result = parse(colophon, log)
    assert colophon.select_final_answer(result, "synthetic-turn-1") == {"text": "Synthetic reply after completion", "voice": True}


def test_final_answer_uses_last_final_in_file_order(colophon, tmp_path):
    log = new_log(tmp_path).task_started().agent_item("Synthetic first final", at=BASE + 500)
    log.realtime_segment("Synthetic request").realtime_segment("Synthetic voice reply", role="assistant")
    log.agent_item("Synthetic last final", at=BASE + 200).task_complete()
    result = parse(colophon, log)
    assert colophon.select_final_answer(result, "synthetic-turn-1") == {"text": "Synthetic last final", "voice": False}


def test_voice_final_uses_earlier_reply_when_last_request_unanswered(colophon, tmp_path):
    log = new_log(tmp_path).task_started().realtime_segment("Synthetic request 1")
    log.realtime_segment("Synthetic reply 1", role="assistant").realtime_segment("Synthetic request 2").task_complete()
    result = parse(colophon, log)
    assert colophon.select_final_answer(result, "synthetic-turn-1") == {"text": "Synthetic reply 1", "voice": True}


def test_before_turn_reply_never_supplies_final_answer(colophon, tmp_path):
    log = new_log(tmp_path).realtime_segment("Synthetic before").task_started()
    log.realtime_segment("Synthetic before reply", role="assistant").task_complete()
    result = parse(colophon, log)
    assert colophon.select_final_answer(result, "synthetic-turn-1") is None


def test_follow_up_voice_reply_supplies_final_answer(colophon, tmp_path):
    log = new_log(tmp_path).task_started().task_complete().realtime_segment("Synthetic follow-up")
    log.realtime_segment("Synthetic follow-up reply", role="assistant")
    result = parse(colophon, log)
    assert colophon.select_final_answer(result, "synthetic-turn-1") == {"text": "Synthetic follow-up reply", "voice": True}


def test_unknown_voice_clock_is_not_invented(colophon, tmp_path):
    log = new_log(tmp_path).task_started()
    log.raw(b'{"type":"realtime_item","payload":{"type":"transcript_segment","role":"user","text":"Synthetic unknown clock"}}\n')
    request = parse(colophon, log)["voice"]["requests"][0]
    assert request["at_ms"] is None
    assert request["turn_key"] == "synthetic-turn-1"
    assert request["before_turn"] is False
    assert request["follow_up"] is False


def test_dedup_scaling_ratio(colophon, tmp_path):
    def make(n):
        log = CodexHome(tmp_path / f"synthetic-scale-{n}").log().meta(at=BASE).task_started(at=BASE + 1)
        for _ in range(n):
            log.user_item("Synthetic identical", at=BASE + 2)
        for _ in range(n):
            log.user_event_legacy("Synthetic identical", at=BASE + 3)
        return log.write()

    paths = [make(10_000), make(20_000)]
    medians = []
    for path in paths:
        stat = path.stat()
        times = []
        for _ in range(3):
            start = time.perf_counter()
            result = colophon.parse_log_file(path, size=stat.st_size, mtime_ns=stat.st_mtime_ns, archived=False)
            times.append(time.perf_counter() - start)
            assert len(result["messages"]) == (10_000 if path == paths[0] else 20_000)
        medians.append(statistics.median(times))
    print(f"median timings: n={medians[0]:.6f}s, 2n={medians[1]:.6f}s, ratio={medians[1] / medians[0]:.3f}")
    assert medians[1] <= 3.0 * medians[0], f"median timings: n={medians[0]:.6f}s, 2n={medians[1]:.6f}s"


def test_reply_run_before_first_turn_is_dropped_as_one_run(colophon, tmp_path):
    log = new_log(tmp_path).realtime_segment("Synthetic first reply", role="assistant")
    log.task_started().task_complete().realtime_segment("Synthetic later reply", role="assistant")
    assert parse(colophon, log)["voice"]["replies"] == []


def test_empty_answer_part_still_marks_assembled_request_as_answer(colophon, tmp_path):
    content = [{"type": "text", "text": "Synthetic request"},
               {"type": "text", "text": "<send_user_message_question_reply></send_user_message_question_reply>"}]
    result = parse(colophon, new_log(tmp_path).task_started().user_item(content=content))
    assert result["messages"][0]["kind"] == "answer"
    assert result["messages"][0]["text"] == "Synthetic request"


def test_voice_after_completion_only_turn_is_follow_up(colophon, tmp_path):
    log = new_log(tmp_path).task_complete().realtime_segment("Synthetic follow-up")
    log.realtime_segment("Synthetic reply", role="assistant")
    result = parse(colophon, log)
    assert result["voice"]["requests"][0]["turn_key"] == "synthetic-turn-1"
    assert result["voice"]["requests"][0]["follow_up"] is True
    assert colophon.select_final_answer(result, "synthetic-turn-1") == {"text": "Synthetic reply", "voice": True}


def test_voice_before_completion_only_turn_has_unknown_placement(colophon, tmp_path):
    log = new_log(tmp_path).realtime_segment("Synthetic unknown placement").task_complete()
    result = parse(colophon, log)
    assert result["voice"]["requests"][0]["turn_key"] is None
    assert result["voice"]["requests"][0]["before_turn"] is False
    assert result["voice"]["requests"][0]["follow_up"] is False


def test_missing_id_copies_across_anonymous_turns_remain_compatible(colophon, tmp_path):
    log = new_log(tmp_path)._event("task_started", {}, at=BASE + 1)
    log.user_item(turn_id="", at=BASE + 2)._event("task_complete", {}, at=BASE + 3)
    log._event("task_started", {}, at=BASE + 4).user_event_legacy(at=BASE + 5)
    result = parse(colophon, log)
    assert len(result["turns"]) == 2
    assert result["messages"][0]["turn_key"] == "turn-1"
    assert len(result["messages"]) == 1


def test_response_exclusion_tracks_dropped_item_content(colophon, tmp_path):
    log = new_log(tmp_path).task_started().user_response("Synthetic fallback")
    log.user_item("<environment_context>Synthetic injected context")
    assert parse(colophon, log)["messages"] == []


def test_event_wins_over_response_without_item_message(colophon, tmp_path):
    log = new_log(tmp_path).task_started().user_response(at=BASE + 2).user_event_legacy(at=BASE + 3)
    assert [m["rec"] for m in parse(colophon, log)["messages"]] == [3]


def test_same_text_in_different_roles_is_kept(colophon, tmp_path):
    log = new_log(tmp_path).task_started().user_item("Synthetic same text")
    log.agent_event_legacy("Synthetic same text")
    assert [m["role"] for m in parse(colophon, log)["messages"]] == ["user", "assistant"]


def test_all_three_families_choose_item_copy_outside_turn(colophon, tmp_path):
    log = new_log(tmp_path).user_response(at=BASE + 1, turn_id="synthetic-no-turn")
    log.user_event_legacy(at=BASE + 2, turn_id="synthetic-no-turn").user_item(at=BASE + 3, turn_id="synthetic-no-turn")
    result = parse(colophon, log)
    assert [m["rec"] for m in result["messages"]] == [3]
    assert result["messages"][0]["turn_key"] is None


@pytest.mark.parametrize("first_id, second_id", [("*", "synthetic-other"), ("synthetic-other", "*")])
def test_reserved_star_turn_id_does_not_match_other_concrete_id(colophon, tmp_path, first_id, second_id):
    log = new_log(tmp_path).user_item(turn_id=first_id, at=BASE + 1)
    log.user_event_legacy(turn_id=second_id, at=BASE + 2)
    assert len(parse(colophon, log)["messages"]) == 2


def test_reserved_star_turn_id_matches_same_id_and_missing_id(colophon, tmp_path):
    log = new_log(tmp_path).user_item(turn_id="*", at=BASE + 1)
    log.user_event_legacy(turn_id="*", at=BASE + 2).user_event_legacy(at=BASE + 3)
    assert len(parse(colophon, log)["messages"]) == 1
