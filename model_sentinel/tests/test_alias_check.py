"""Alias price evaluation, divergence events and price ladders.

Every fixture is invented: fake provider and model IDs and invented prices.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import pytest

from model_sentinel.alias_check import (
    ALIAS_EVENT_CHANGED,
    ALIAS_EVENT_NEW,
    ALIAS_EVENT_PERSISTING,
    ALIAS_EVENT_RESOLVED,
    ALIAS_EVENT_UNAVAILABLE,
    divergence_events,
    evaluate_aliases,
    price_ladder,
)
from model_sentinel.config import ProviderConfig
from model_sentinel.endpoints import endpoint_list_records
from model_sentinel.models import (
    AliasEvaluation,
    EndpointFetchResult,
    EndpointListRecord,
    EndpointMapping,
    EndpointPathResult,
    LadderMarkInput,
)
from model_sentinel.normalize import normalize_models
from model_sentinel.provider_profiles import OPENROUTER_PROFILE

FAKE_PROVIDER = ProviderConfig(
    provider_id="fake_router",
    label="Fake Router",
    kind="openrouter",
    base_url="https://fake-router.invalid/api/v1",
    models_path="/models",
    credential_env_var="FAKE_ROUTER_NOT_A_REAL_KEY",
    price_multiplier=1,
    price_divisor=1,
    enabled=True,
)
PREFIX = "/api/v1/models/"
TARGET = "fake-org/test-model-a"
ALIAS = "fake-org/test-model-latest"
TARGET_PATH = f"{PREFIX}{TARGET}/endpoints"


def _listed(model_id: str, pricing: Any, **extra: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": model_id,
        "links": {"details": f"{PREFIX}{model_id}/endpoints"},
        "pricing": pricing,
    }
    raw.update(extra)
    return raw


def _alias(model_id: str, target: Any, pricing: Any, **extra: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {"id": model_id, "alias_target": {"slug": target}, "pricing": pricing}
    raw.update(extra)
    return raw


def _catalog(*raw_models: dict[str, Any]) -> dict[str, Any]:
    models = normalize_models(FAKE_PROVIDER, list(raw_models), OPENROUTER_PROFILE)
    return {model.provider_model_id: model for model in models}


def _endpoint(tag: str, pricing: Any) -> dict[str, Any]:
    return {"tag": tag, "provider_name": "Fake Host", "status": 0, "pricing": pricing}


def _lists(
    *paths: tuple[str, str, tuple[dict[str, Any], ...]],
    mappings: tuple[EndpointMapping, ...] = (),
) -> tuple[EndpointListRecord, ...]:
    """Build list records through the real capture projection."""
    results = tuple(
        EndpointPathResult(
            list_path=path,
            list_model_id=None,
            outcome=outcome,
            endpoints=endpoints,
            error_code="http_status" if outcome == "error" else None,
            error_message="HTTP 503" if outcome == "error" else None,
            http_status=503 if outcome == "error" else None,
        )
        for path, outcome, endpoints in paths
    )
    fetch = EndpointFetchResult(
        provider_id="fake_router",
        started_at="2030-01-02T03:04:05+00:00",
        completed_at="2030-01-02T03:04:06+00:00",
        mappings=mappings or tuple(
            EndpointMapping(TARGET, "listed", path, None, None, None) for path, _, _ in paths
        ),
        paths=results,
        paths_requested=len(results),
        paths_attempted=len(results),
        paths_failed=sum(1 for result in results if result.outcome == "error"),
        mapping_failures=0,
        bodies={},
    )
    return endpoint_list_records(fetch, OPENROUTER_PROFILE)


def _only(evaluations: tuple[AliasEvaluation, ...], alias_id: str = ALIAS) -> AliasEvaluation:
    matches = [evaluation for evaluation in evaluations if evaluation.alias_model_id == alias_id]
    assert len(matches) == 1
    return matches[0]


def _base_catalog(**alias_pricing: Any) -> dict[str, Any]:
    pricing = {"prompt": "0.000001", "completion": "0.000003", "request": "0.01"}
    pricing.update(alias_pricing)
    return _catalog(
        _listed(TARGET, {"prompt": "0.000001", "completion": "0.000002", "request": "0.01"}),
        _alias(ALIAS, TARGET, pricing),
    )


# ---------------------------------------------------------------------------
# alias_leaf_comparison_and_matching
# ---------------------------------------------------------------------------


def test_alias_leaf_comparison_and_matching_compares_fixed_leaf_set() -> None:
    evaluation = _only(evaluate_aliases(_base_catalog(), OPENROUTER_PROFILE))

    assert evaluation.alias_target_model_id == TARGET
    assert evaluation.target_model_id == TARGET
    assert evaluation.unavailable_reason is None
    # Profile order: Input, then Output, then the unordered request leaf.
    assert [leaf.path for leaf in evaluation.compared_leaves] == [
        "pricing.prompt",
        "pricing.completion",
        "pricing.request",
    ]
    completion = evaluation.compared_leaves[1]
    assert completion.label == "Output"
    assert completion.unit_label == "/1M tokens"
    assert completion.comparison_group == "usd_per_million_tokens"
    assert (completion.alias_raw, completion.target_raw) == ("0.000003", "0.000002")
    assert (completion.alias_exact, completion.target_exact) == ("3", "2")
    assert (completion.alias_display, completion.target_display) == ("$3.00", "$2.00")
    assert completion.equal is False
    request = evaluation.compared_leaves[2]
    assert (request.unit_label, request.alias_display, request.equal) == ("/request", "$0.01", True)
    assert evaluation.unavailable_leaves == ()

    assert evaluation.divergence is not None
    assert evaluation.divergence.target_model_id == TARGET
    assert [leaf.path for leaf in evaluation.divergence.leaves] == ["pricing.completion"]
    assert evaluation.divergence.signature == (
        TARGET,
        (("pricing.completion", "3", "2", "/1M tokens", "usd_per_million_tokens"),),
    )
    # Without capture evidence the endpoint match is unavailable, not empty.
    assert evaluation.endpoint_match.unavailable_reason == "not_captured"
    assert evaluation.endpoint_match.compared_leaves == (
        "pricing.prompt",
        "pricing.completion",
        "pricing.request",
    )
    # Records are JSON-safe for later serializers.
    json.dumps(asdict(evaluation))


def test_alias_leaf_comparison_and_matching_uses_exact_values_not_spelling() -> None:
    catalog = _catalog(
        _listed(TARGET, {"prompt": "0.0000010", "completion": 2e-06}),
        _alias(ALIAS, TARGET, {"prompt": 1e-06, "completion": "0.000002"}),
    )
    evaluation = _only(evaluate_aliases(catalog, OPENROUTER_PROFILE))
    assert all(leaf.equal for leaf in evaluation.compared_leaves)
    assert evaluation.divergence is None


def test_alias_leaf_comparison_and_matching_classifies_endpoint_candidates() -> None:
    lists = _lists(
        (
            TARGET_PATH,
            "ok",
            (
                # Every required leaf equal to the alias (spelling differs): match.
                _endpoint("match", {"prompt": 1e-06, "completion": "0.0000030", "request": "0.01"}),
                # One proven unequal leaf: nonmatch.
                _endpoint("target-price", {"prompt": "0.000001", "completion": "0.000002", "request": "0.01"}),
                # Missing required leaf, no proven inequality: unknown.
                _endpoint("no-request", {"prompt": "0.000001", "completion": "0.000003"}),
                # Unresolved required leaf: unknown.
                _endpoint("odd-request", {"prompt": "0.000001", "completion": "0.000003", "request": "n/a"}),
                # A proven inequality wins over a missing leaf.
                _endpoint("cheap-partial", {"prompt": "0.0000005"}),
                # No pricing object at all: unknown.
                {"tag": "unpriced", "status": 0},
                # Extra leaves outside the comparison set do not matter.
                _endpoint(
                    "extra",
                    {"prompt": "0.000001", "completion": "0.000003", "request": "0.01", "web_search": "0.02"},
                ),
            ),
        )
    )
    evaluation = _only(evaluate_aliases(_base_catalog(), OPENROUTER_PROFILE, lists))
    match = evaluation.endpoint_match
    assert match.unavailable_reason is None
    assert match.list_path == TARGET_PATH
    assert match.list_outcome == "ok"
    assert match.matching_keys == ("match#0", "extra#0")
    assert match.differing_keys == ("target-price#0", "cheap-partial#0")
    assert match.unknown_keys == ("no-request#0", "odd-request#0", "unpriced#0")


def test_alias_leaf_comparison_and_matching_incomplete_candidate_is_never_a_match() -> None:
    # The candidate's available leaves all agree with the alias, but the fixed
    # comparison set is never reduced to them.
    lists = _lists((TARGET_PATH, "ok", (_endpoint("partial", {"completion": "0.000003"}),)))
    evaluation = _only(evaluate_aliases(_base_catalog(), OPENROUTER_PROFILE, lists))
    assert evaluation.endpoint_match.matching_keys == ()
    assert evaluation.endpoint_match.differing_keys == ()
    assert evaluation.endpoint_match.unknown_keys == ("partial#0",)


def test_alias_leaf_comparison_and_matching_conditional_subtree_is_excluded() -> None:
    overrides_a = [{"min_prompt_tokens": 200000, "prompt": "0.000004"}]
    overrides_b = [{"min_prompt_tokens": 100000, "prompt": "0.000009"}]
    catalog = _catalog(
        _listed(TARGET, {"prompt": "0.000001", "completion": "0.000002", "overrides": overrides_a}),
        _alias(ALIAS, TARGET, {"prompt": "0.000001", "completion": "0.000002", "overrides": overrides_b}),
    )
    lists = _lists(
        (
            TARGET_PATH,
            "ok",
            (_endpoint("tiered", {"prompt": "0.000001", "completion": "0.000002", "overrides": overrides_a}),),
        )
    )
    evaluation = _only(evaluate_aliases(catalog, OPENROUTER_PROFILE, lists))
    paths = {leaf.path for leaf in evaluation.compared_leaves} | {
        leaf.path for leaf in evaluation.unavailable_leaves
    }
    assert paths == {"pricing.prompt", "pricing.completion"}
    assert evaluation.divergence is None
    assert evaluation.endpoint_match.compared_leaves == ("pricing.prompt", "pricing.completion")
    assert evaluation.endpoint_match.matching_keys == ("tiered#0",)


def test_alias_leaf_comparison_and_matching_empty_comparison_set() -> None:
    catalog = _catalog(
        _listed(TARGET, {"prompt": "0.000001"}),
        _alias(ALIAS, TARGET, {"web_search": "0.02"}),
    )
    lists = _lists((TARGET_PATH, "ok", (_endpoint("only", {"prompt": "0.000001"}),)))
    evaluation = _only(evaluate_aliases(catalog, OPENROUTER_PROFILE, lists))
    assert evaluation.compared_leaves == ()
    assert evaluation.divergence is None
    unavailable = [
        (leaf.path, leaf.reason, leaf.alias_state, leaf.target_state)
        for leaf in evaluation.unavailable_leaves
    ]
    assert unavailable == [
        ("pricing.prompt", "missing", "missing", "resolved"),
        ("pricing.web_search", "missing", "resolved", "missing"),
    ]
    match = evaluation.endpoint_match
    assert match.unavailable_reason == "no_comparable_leaves"
    assert (match.compared_leaves, match.matching_keys, match.differing_keys, match.unknown_keys) == (
        (),
        (),
        (),
        (),
    )


def test_alias_leaf_comparison_and_matching_successful_empty_list_has_no_candidates() -> None:
    lists = _lists((TARGET_PATH, "empty", ()))
    match = _only(evaluate_aliases(_base_catalog(), OPENROUTER_PROFILE, lists)).endpoint_match
    assert match.unavailable_reason is None
    assert match.list_outcome == "empty"
    assert (match.matching_keys, match.differing_keys, match.unknown_keys) == ((), (), ())


def test_alias_leaf_comparison_and_matching_follows_chains_and_shared_lists() -> None:
    other = "fake-org/test-model-a-mirror"
    middle = "fake-org/test-model-stable"
    catalog = _catalog(
        _listed(TARGET, {"prompt": "0.000001"}),
        # A second listed model sharing the target's list path.
        _listed(other, {"prompt": "0.000001"}, links={"details": TARGET_PATH}),
        _alias(middle, TARGET, {"prompt": "0.000001"}),
        _alias(ALIAS, middle, {"prompt": "0.000002"}),
    )
    mappings = (
        EndpointMapping(TARGET, "listed", TARGET_PATH, None, None, None),
        EndpointMapping(other, "listed", TARGET_PATH, None, None, None),
    )
    lists = _lists(
        (
            TARGET_PATH,
            "ok",
            (_endpoint("cheap", {"prompt": "0.000001"}), _endpoint("dear", {"prompt": "0.000002"})),
        ),
        mappings=mappings,
    )
    evaluations = evaluate_aliases(catalog, OPENROUTER_PROFILE, lists)
    assert [evaluation.alias_model_id for evaluation in evaluations] == [ALIAS, middle]
    evaluation = evaluations[0]
    assert evaluation.alias_target_model_id == middle
    assert evaluation.target_model_id == TARGET
    assert evaluation.divergence is not None
    assert evaluation.endpoint_match.matching_keys == ("dear#0",)
    assert evaluation.endpoint_match.differing_keys == ("cheap#0",)
    assert evaluations[1].divergence is None
    assert evaluations[1].endpoint_match.matching_keys == ("cheap#0",)


def test_alias_leaf_comparison_and_matching_target_without_link_is_still_compared() -> None:
    catalog = _catalog(
        {"id": TARGET, "pricing": {"prompt": "0.000001"}},
        _alias(ALIAS, TARGET, {"prompt": "0.000002"}),
    )
    unrelated_path = f"{PREFIX}fake-org/unrelated/endpoints"
    lists = _lists(
        (unrelated_path, "ok", (_endpoint("x", {"prompt": "0.000002"}),)),
        mappings=(EndpointMapping("fake-org/unrelated", "listed", unrelated_path, None, None, None),),
    )
    evaluation = _only(evaluate_aliases(catalog, OPENROUTER_PROFILE, lists))
    assert evaluation.target_model_id == TARGET
    assert evaluation.divergence is not None
    assert evaluation.endpoint_match.unavailable_reason == "list_missing"
    assert evaluation.endpoint_match.matching_keys == ()


def test_alias_leaf_comparison_and_matching_accepts_metadata_mappings() -> None:
    models = {
        TARGET: {"id": TARGET, "pricing": {"prompt": "0.000001"}},
        ALIAS: {"id": ALIAS, "alias_target": {"slug": TARGET}, "pricing": {"prompt": "0.000002"}},
    }
    evaluation = _only(evaluate_aliases(models, OPENROUTER_PROFILE))
    assert evaluation.divergence is not None
    assert evaluation.divergence.leaves[0].alias_display == "$2.00"


# ---------------------------------------------------------------------------
# alias_missing_evidence
# ---------------------------------------------------------------------------


def test_alias_missing_evidence_unresolved_targets() -> None:
    catalog = _catalog(
        _listed(TARGET, {"prompt": "0.000001"}),
        _alias("fake-org/missing-alias", "fake-org/not-in-catalog", {"prompt": "0.000002"}),
        _alias("fake-org/cycle-a", "fake-org/cycle-b", {"prompt": "0.000002"}),
        _alias("fake-org/cycle-b", "fake-org/cycle-a", {"prompt": "0.000002"}),
        _alias("fake-org/self", "fake-org/self", {"prompt": "0.000002"}),
        {"id": "fake-org/malformed", "alias_target": {"slug": ""}, "pricing": {"prompt": "0.000002"}},
        _alias("fake-org/to-malformed", "fake-org/malformed", {"prompt": "0.000002"}),
    )
    evaluations = {e.alias_model_id: e for e in evaluate_aliases(catalog, OPENROUTER_PROFILE, ())}
    outcomes = {
        model_id: (e.alias_target_model_id, e.target_model_id, e.unavailable_reason)
        for model_id, e in evaluations.items()
    }
    assert outcomes == {
        "fake-org/missing-alias": ("fake-org/not-in-catalog", None, "alias_target_missing"),
        "fake-org/cycle-a": ("fake-org/cycle-b", None, "alias_cycle"),
        "fake-org/cycle-b": ("fake-org/cycle-a", None, "alias_cycle"),
        "fake-org/self": ("fake-org/self", None, "alias_cycle"),
        "fake-org/malformed": (None, None, "invalid_link"),
        "fake-org/to-malformed": ("fake-org/malformed", None, "invalid_link"),
    }
    for evaluation in evaluations.values():
        assert evaluation.compared_leaves == ()
        assert evaluation.divergence is None
        assert evaluation.endpoint_match.unavailable_reason == evaluation.unavailable_reason


def test_alias_missing_evidence_unavailable_catalog_leaves_are_retained() -> None:
    catalog = _catalog(
        _listed(TARGET, {"prompt": "0.000001", "completion": "free", "request": None}),
        _alias(ALIAS, TARGET, {"prompt": "0.000001", "completion": "0.000004", "image": "0.03"}),
    )
    evaluation = _only(evaluate_aliases(catalog, OPENROUTER_PROFILE))
    assert [leaf.path for leaf in evaluation.compared_leaves] == ["pricing.prompt"]
    assert evaluation.divergence is None
    unavailable = {leaf.path: leaf for leaf in evaluation.unavailable_leaves}
    assert set(unavailable) == {"pricing.completion", "pricing.image", "pricing.request"}
    completion = unavailable["pricing.completion"]
    assert (completion.reason, completion.alias_state, completion.target_state) == (
        "unresolved",
        "resolved",
        "unresolved",
    )
    assert (completion.alias_raw, completion.target_raw) == ("0.000004", "free")
    assert (completion.alias_unit_label, completion.target_unit_label) == ("/1M tokens", None)
    image = unavailable["pricing.image"]
    assert (image.reason, image.target_state) == ("missing", "missing")
    assert (unavailable["pricing.request"].alias_state, unavailable["pricing.request"].target_state) == (
        "missing",
        "unresolved",
    )


def test_alias_missing_evidence_list_unavailability_reasons() -> None:
    catalog = _base_catalog()
    failed = _lists((TARGET_PATH, "error", ()))
    for lists, reason in ((failed, "list_failed"), ((), "list_missing"), (None, "not_captured")):
        match = _only(evaluate_aliases(catalog, OPENROUTER_PROFILE, lists)).endpoint_match
        assert match.unavailable_reason == reason
        assert (match.matching_keys, match.differing_keys, match.unknown_keys) == ((), (), ())
    failed_match = _only(evaluate_aliases(catalog, OPENROUTER_PROFILE, failed)).endpoint_match
    assert (failed_match.list_path, failed_match.list_outcome) == (TARGET_PATH, "error")


def test_alias_missing_evidence_tolerates_malformed_metadata() -> None:
    models = {
        TARGET: {"id": TARGET, "pricing": ["not", "an", "object"]},
        ALIAS: {"id": ALIAS, "alias_target": {"slug": TARGET}, "pricing": "0.000002"},
        "fake-org/not-object": ["not metadata"],
        "fake-org/alias-string": {"alias_target": "fake-org/test-model-a"},
        "fake-org/to-not-object": {
            "alias_target": {"slug": "fake-org/not-object"},
            "pricing": {"prompt": "0.000001"},
        },
    }
    evaluations = {e.alias_model_id: e for e in evaluate_aliases(models, OPENROUTER_PROFILE)}
    assert set(evaluations) == {ALIAS, "fake-org/alias-string", "fake-org/to-not-object"}
    assert evaluations[ALIAS].compared_leaves == ()
    assert evaluations[ALIAS].endpoint_match.unavailable_reason == "no_comparable_leaves"
    assert evaluations["fake-org/alias-string"].unavailable_reason == "invalid_link"
    # A catalog model with non-object metadata is still a present target; it
    # just offers no price evidence.
    to_not_object = evaluations["fake-org/to-not-object"]
    assert (to_not_object.target_model_id, to_not_object.unavailable_reason) == ("fake-org/not-object", None)
    assert [(leaf.path, leaf.target_state) for leaf in to_not_object.unavailable_leaves] == [
        ("pricing.prompt", "missing")
    ]


def test_alias_missing_evidence_events_never_claim_prices_match_again() -> None:
    baseline = _base_catalog()
    alias_gone = _catalog(_listed(TARGET, {"prompt": "0.000001", "completion": "0.000002", "request": "0.01"}))
    target_gone = _catalog(_alias(ALIAS, TARGET, {"prompt": "0.000001", "completion": "0.000002"}))
    leaf_unresolved = _catalog(
        _listed(TARGET, {"prompt": "0.000001", "completion": "varies", "request": "0.01"}),
        _alias(ALIAS, TARGET, {"prompt": "0.000001", "completion": "0.000003", "request": "0.01"}),
    )
    leaf_missing = _catalog(
        _listed(TARGET, {"prompt": "0.000001", "request": "0.01"}),
        _alias(ALIAS, TARGET, {"prompt": "0.000001", "request": "0.01"}),
    )
    no_longer_alias = _catalog(
        _listed(TARGET, {"prompt": "0.000001", "completion": "0.000002", "request": "0.01"}),
        _listed(ALIAS, {"prompt": "0.000001", "completion": "0.000002", "request": "0.01"}),
    )
    cases = [
        (alias_gone, "alias_missing"),
        (target_gone, "alias_target_missing"),
        (leaf_unresolved, "leaves_unavailable"),
        (leaf_missing, "leaves_unavailable"),
        (no_longer_alias, "not_alias"),
    ]
    for current, reason in cases:
        (event,) = divergence_events(baseline, current, OPENROUTER_PROFILE)
        assert event.kind == ALIAS_EVENT_UNAVAILABLE
        assert event.unavailable_reason == reason
        assert event.alias_model_id == ALIAS
        assert event.baseline is not None and event.baseline.divergence is not None
        # The event keeps the previously divergent leaves as its evidence.
        assert [leaf.path for leaf in event.leaves] == ["pricing.completion"]
        assert event.leaves[0].equal is False
    (event,) = divergence_events(baseline, alias_gone, OPENROUTER_PROFILE)
    assert event.current is None


# ---------------------------------------------------------------------------
# alias_semantic_event_transitions
# ---------------------------------------------------------------------------


def test_alias_semantic_event_transitions_new_and_no_event() -> None:
    current = _base_catalog()
    (event,) = divergence_events({}, current, OPENROUTER_PROFILE)
    assert event.kind == ALIAS_EVENT_NEW
    assert event.baseline is None
    assert event.current is not None and event.current.divergence is not None
    assert [leaf.path for leaf in event.leaves] == ["pricing.completion"]
    assert divergence_events(None, current, OPENROUTER_PROFILE)[0].kind == ALIAS_EVENT_NEW
    # Neither side diverges: no event.
    matching = _base_catalog(completion="0.000002")
    assert divergence_events(matching, matching, OPENROUTER_PROFILE) == ()
    # Unresolved on both sides without a prior divergence: no event.
    broken = _catalog(_alias(ALIAS, "fake-org/not-in-catalog", {"prompt": "0.000001"}))
    assert divergence_events(broken, broken, OPENROUTER_PROFILE) == ()


def test_alias_semantic_event_transitions_persisting_ignores_spelling_and_endpoint_evidence() -> None:
    baseline = _base_catalog()
    respelled = _catalog(
        _listed(TARGET, {"prompt": 1e-06, "completion": 2e-06, "request": 0.01}),
        _alias(ALIAS, TARGET, {"prompt": "0.0000010", "completion": 3e-06, "request": "0.010"}),
    )
    matching = _endpoint("match", {"prompt": "0.000001", "completion": "0.000003", "request": "0.01"})
    lists = _lists((TARGET_PATH, "ok", (matching,)))
    (event,) = divergence_events(baseline, respelled, OPENROUTER_PROFILE, lists)
    assert event.kind == ALIAS_EVENT_PERSISTING
    assert event.current is not None
    assert event.current.endpoint_match.matching_keys == ("match#0",)
    assert event.baseline is not None
    assert event.baseline.endpoint_match.unavailable_reason == "not_captured"


def test_alias_semantic_event_transitions_changed_signatures() -> None:
    baseline = _base_catalog()
    moved_value = _base_catalog(completion="0.000004")
    extra_leaf = _base_catalog(prompt="0.0000015")
    other_target = "fake-org/test-model-b"
    retargeted = _catalog(
        _listed(TARGET, {"prompt": "0.000001", "completion": "0.000002", "request": "0.01"}),
        _listed(other_target, {"prompt": "0.000001", "completion": "0.000002", "request": "0.01"}),
        _alias(ALIAS, other_target, {"prompt": "0.000001", "completion": "0.000003", "request": "0.01"}),
    )
    for current in (moved_value, extra_leaf, retargeted):
        (event,) = divergence_events(baseline, current, OPENROUTER_PROFILE)
        assert event.kind == ALIAS_EVENT_CHANGED
        assert event.baseline is not None and event.current is not None
        assert event.current.divergence is not None and event.baseline.divergence is not None
        assert event.current.divergence.signature != event.baseline.divergence.signature
    (event,) = divergence_events(baseline, retargeted, OPENROUTER_PROFILE)
    assert event.current is not None and event.current.target_model_id == other_target
    (event,) = divergence_events(baseline, extra_leaf, OPENROUTER_PROFILE)
    assert [leaf.path for leaf in event.leaves] == ["pricing.prompt", "pricing.completion"]


def test_alias_semantic_event_transitions_resolved() -> None:
    baseline = _base_catalog()
    current = _base_catalog(completion="0.0000020")
    (event,) = divergence_events(baseline, current, OPENROUTER_PROFILE)
    assert event.kind == ALIAS_EVENT_RESOLVED
    assert event.unavailable_reason is None
    assert [(leaf.path, leaf.alias_display, leaf.target_display, leaf.equal) for leaf in event.leaves] == [
        ("pricing.completion", "$2.00", "$2.00", True)
    ]


def test_alias_semantic_event_transitions_order_and_json_safety() -> None:
    second = "fake-org/test-model-zeta"
    first = "fake-org/test-model-alpha"
    current = _catalog(
        _listed(TARGET, {"prompt": "0.000001"}),
        _alias(second, TARGET, {"prompt": "0.000002"}),
        _alias(first, TARGET, {"prompt": "0.000003"}),
    )
    events = divergence_events({}, current, OPENROUTER_PROFILE)
    assert [event.alias_model_id for event in events] == [first, second]
    json.dumps([asdict(event) for event in events])


# ---------------------------------------------------------------------------
# ladder_domain_and_unplaced_values
# ---------------------------------------------------------------------------


def _priced(*values: tuple[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(key, {"pricing": {"prompt": value}}) for key, value in values]


def test_ladder_domain_and_unplaced_values_positions_and_coincident_labels() -> None:
    ladder = price_ladder(
        _priced(("low#0", "0.000001"), ("mid#0", "0.00001"), ("high#0", "0.0001"), ("low-twin#0", 1e-06)),
        leaf="pricing.prompt",
        marks=[LadderMarkInput("target", "pricing.prompt", "0.0000010")],
        profile=OPENROUTER_PROFILE,
    )
    assert ladder is not None
    assert (ladder.leaf, ladder.label, ladder.unit_label, ladder.comparison_group) == (
        "pricing.prompt",
        "Input",
        "/1M tokens",
        "usd_per_million_tokens",
    )
    assert (ladder.domain_min_exact, ladder.domain_max_exact) == ("1", "100")
    assert (ladder.domain_min_display, ladder.domain_max_display) == ("$1.00", "$100.00")
    assert [(p.position, p.exact_value, p.display) for p in ladder.positions] == [
        (0.0, "1", "$1.00"),
        (0.5, "10", "$10.00"),
        (1.0, "100", "$100.00"),
    ]
    low = ladder.positions[0]
    assert [(entry.kind, entry.label, entry.raw_value) for entry in low.entries] == [
        ("endpoint", "low#0", "0.000001"),
        ("endpoint", "low-twin#0", 1e-06),
        ("mark", "target", "0.0000010"),
    ]
    assert ladder.unplaced == ()
    json.dumps(asdict(ladder))


def test_ladder_domain_and_unplaced_values_marks_expand_domain() -> None:
    ladder = price_ladder(
        _priced(("a#0", "0.000001"), ("b#0", "0.00001")),
        leaf="pricing.prompt",
        marks=[LadderMarkInput("alias", "pricing.prompt", "0.001"), ("target", "pricing.prompt", "0.0001")],
        profile=OPENROUTER_PROFILE,
    )
    assert ladder is not None
    assert (ladder.domain_min_exact, ladder.domain_max_exact) == ("1", "1000")
    positions = [(p.exact_value, round(p.position, 12), [e.label for e in p.entries]) for p in ladder.positions]
    assert positions == [
        ("1", 0.0, ["a#0"]),
        ("10", round(1 / 3, 12), ["b#0"]),
        ("100", round(2 / 3, 12), ["target"]),
        ("1000", 1.0, ["alias"]),
    ]


def test_ladder_domain_and_unplaced_values_single_value_is_centered() -> None:
    ladder = price_ladder(
        _priced(("a#0", "0.000002"), ("b#0", "2e-6")),
        leaf="pricing.prompt",
        marks=[LadderMarkInput("target", "pricing.prompt", 2e-06)],
        profile=OPENROUTER_PROFILE,
    )
    assert ladder is not None
    assert [(p.position, len(p.entries)) for p in ladder.positions] == [(0.5, 3)]
    assert ladder.domain_min_exact == ladder.domain_max_exact == "2"


def test_ladder_domain_and_unplaced_values_reports_unplaced_reasons() -> None:
    endpoints = [
        ("ok#0", {"pricing": {"prompt": "0.000003"}}),
        ("free#0", {"pricing": {"prompt": "0"}}),
        ("negative#0", {"pricing": {"prompt": "-0.000001"}}),
        ("absent#0", {"pricing": {"completion": "0.000001"}}),
        ("null#0", {"pricing": {"prompt": None}}),
        ("unpriced#0", {"tag": "unpriced"}),
        ("text#0", {"pricing": {"prompt": "n/a"}}),
        ("bool#0", {"pricing": {"prompt": True}}),
        ("object#0", {"pricing": {"prompt": {"amount": "0.000001"}}}),
    ]
    marks = [
        LadderMarkInput("alias", "pricing.prompt", "0.000003"),
        LadderMarkInput("per-request", "pricing.request", "0.01"),
        LadderMarkInput("unknown-unit", "pricing.mystery_fee", "0.01"),
        LadderMarkInput("target", "pricing.prompt", None),
    ]
    ladder = price_ladder(endpoints, leaf="pricing.prompt", marks=marks, profile=OPENROUTER_PROFILE)
    assert ladder is not None
    assert [(p.position, [e.label for e in p.entries]) for p in ladder.positions] == [(0.5, ["ok#0", "alias"])]
    assert [(u.kind, u.label, u.reason, u.raw_value, u.display) for u in ladder.unplaced] == [
        ("endpoint", "free#0", "zero", "0", "free"),
        ("endpoint", "negative#0", "negative", "-0.000001", "-$1.00"),
        ("endpoint", "absent#0", "missing", None, None),
        ("endpoint", "null#0", "missing", None, None),
        ("endpoint", "unpriced#0", "missing", None, None),
        ("endpoint", "text#0", "invalid", "n/a", None),
        ("endpoint", "bool#0", "invalid", True, None),
        ("endpoint", "object#0", "invalid", {"amount": "0.000001"}, None),
        ("mark", "per-request", "incompatible", "0.01", None),
        ("mark", "unknown-unit", "incompatible", "0.01", None),
        ("mark", "target", "missing", None, None),
    ]
    json.dumps(asdict(ladder))


def test_ladder_domain_and_unplaced_values_returns_none_without_positive_values() -> None:
    assert price_ladder(
        [("free#0", {"pricing": {"prompt": "0"}})],
        leaf="pricing.prompt",
        marks=[LadderMarkInput("alias", "pricing.prompt", "-0.000001")],
        profile=OPENROUTER_PROFILE,
    ) is None
    assert price_ladder([], leaf="pricing.prompt", marks=[], profile=OPENROUTER_PROFILE) is None
    # A leaf without a strict profile identity has no compatible values at all.
    assert price_ladder(
        [("a#0", {"pricing": {"mystery_fee": "0.01"}})],
        leaf="pricing.mystery_fee",
        marks=[],
        profile=OPENROUTER_PROFILE,
    ) is None


def test_ladder_domain_and_unplaced_values_extreme_span_does_not_overflow() -> None:
    # 1e-400 and 1e300 (per token) are 1e706 apart: their float ratio overflows.
    ladder = price_ladder(
        _priced(("tiny#0", "1e-400"), ("middle#0", "1e-50"), ("huge#0", "1e300")),
        leaf="pricing.prompt",
        marks=[],
        profile=OPENROUTER_PROFILE,
    )
    assert ladder is not None
    positions = {p.entries[0].label: p.position for p in ladder.positions}
    assert positions["tiny#0"] == 0.0
    assert positions["huge#0"] == 1.0
    assert positions["middle#0"] == pytest.approx((-44 + 394) / 700)


def test_ladder_domain_and_unplaced_values_keeps_distinct_exact_values_apart() -> None:
    # Two values whose float logs coincide stay separate positions.
    ladder = price_ladder(
        _priced(("a#0", "0.000001"), ("b#0", "0.0000010000000000000000001")),
        leaf="pricing.prompt",
        marks=[],
        profile=OPENROUTER_PROFILE,
    )
    assert ladder is not None
    assert [p.exact_value for p in ladder.positions] == ["1", "10000000000000000001/10000000000000000000"]
    assert [p.position for p in ladder.positions] == [0.5, 0.5]
