"""Pure endpoint primitives: state, keys, diff, price leaves, capture status.

Every fixture is invented (fake provider names, invented prices).
"""

from __future__ import annotations

import hashlib
from fractions import Fraction
from typing import Any

import pytest

from model_sentinel import endpoints
from model_sentinel.endpoints import (
    CAPTURE_COMPLETE,
    CAPTURE_ERROR,
    CAPTURE_PARTIAL,
    CONCISE_ENDPOINT_LIST_CAP,
    DOSSIER_ENDPOINT_CHANGE_LIMIT,
    ENDPOINT_FETCH_BUDGET_SECONDS,
    ENDPOINT_FETCH_TIMEOUT_SECONDS,
    ENDPOINT_FETCH_WORKERS,
    ENDPOINT_RETRY_DELAY_SECONDS,
    aggregate_capture_status,
    diff_endpoint_lists,
    endpoint_key,
    endpoint_state,
    endpoint_state_hash,
    endpoint_status,
    key_endpoint_list,
    resolved_price_leaves,
)
from model_sentinel.models import EndpointChange, canonical_json
from model_sentinel.provider_profiles import GENERIC_PROFILE, OPENROUTER_PROFILE


def test_telemetry_uses_response_order_keys_and_skips_invalid_bodies() -> None:
    bodies = {
        "/z": {"data": {"endpoints": [{"provider_name": "Fake Z"}]}},
        "/bad": {"data": {"endpoints": [None]}},
        "/a": {"data": {"endpoints": [
            {"tag": "fake-duplicate", "uptime_last_5m": 100, "uptime_last_30m": 98.5,
             "uptime_last_1d": 97, "latency_last_30m": None},
            {"tag": "fake-duplicate", "uptime_last_5m": True,
             "uptime_last_30m": "99", "uptime_last_1d": 101},
        ]}},
    }
    records = endpoints.endpoint_telemetry_records(bodies, OPENROUTER_PROFILE)
    assert [(r.list_path, r.endpoint_key) for r in records] == [
        ("/a", "fake-duplicate#0"), ("/a", "fake-duplicate#1"), ("/z", "Fake Z#0")]
    assert [(r.uptime_5m, r.uptime_30m, r.uptime_1d) for r in records] == [
        (100, 98.5, 97), (None, None, None), (None, None, None)]
    assert records[0].telemetry == {"uptime_last_5m": 100, "uptime_last_30m": 98.5,
                                    "uptime_last_1d": 97, "latency_last_30m": None}
    assert records[1].telemetry == {"uptime_last_5m": True,
                                    "uptime_last_30m": "99", "uptime_last_1d": 101}
    assert records[2].telemetry == {}


@pytest.mark.parametrize("value,want", [(0, 0), (100, 100), (99.9, 99.9),
    (-1, None), (101, None), (False, None), ("99", None), (None, None),
    (float("nan"), None), (float("inf"), None), (10 ** 1000, None)])
def test_telemetry_rejects_nonfinite_and_nonpercentage_uptime(value, want) -> None:
    body = {"/fake": {"data": {"endpoints": [{"uptime_last_1d": value}]}}}
    record, = endpoints.endpoint_telemetry_records(body, OPENROUTER_PROFILE)
    assert record.uptime_1d == want
    assert "uptime_last_1d" in record.telemetry


@pytest.mark.parametrize("fields", [{"week": "uptime_last_1d"}, {"1d": "status"},
                                    {"1d": []}])
def test_telemetry_profile_rejects_invalid_uptime_declarations(fields) -> None:
    from dataclasses import replace

    with pytest.raises(ValueError, match="uptime"):
        replace(OPENROUTER_PROFILE, endpoint_uptime_fields=fields)


def _endpoint(**overrides: Any) -> dict[str, Any]:
    endpoint: dict[str, Any] = {
        "name": "Fake Host A | fake-org/test-model-a",
        "tag": "fake-host-a/fp8",
        "provider_name": "Fake Host A",
        "context_length": 8000,
        "quantization": "fp8",
        "status": 0,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "uptime_last_30m": 99.5,
        "latency_last_30m": {"p50": 120, "p99": 900},
    }
    endpoint.update(overrides)
    return endpoint


def _observation(endpoint: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    return endpoint_state(endpoint, OPENROUTER_PROFILE), endpoint_status(
        endpoint, OPENROUTER_PROFILE
    )


def test_endpoint_constants_match_the_contract() -> None:
    assert ENDPOINT_FETCH_TIMEOUT_SECONDS == 30.0
    assert ENDPOINT_FETCH_WORKERS == 4
    assert ENDPOINT_FETCH_BUDGET_SECONDS == 180.0
    assert ENDPOINT_RETRY_DELAY_SECONDS == 1.0
    assert CONCISE_ENDPOINT_LIST_CAP == 25
    assert DOSSIER_ENDPOINT_CHANGE_LIMIT == 200


def test_endpoint_key_fallback_and_duplicate_reordering() -> None:
    assert endpoint_key({"tag": "t", "name": "n", "provider_name": "p"}, 0) == "t#0"
    assert endpoint_key({"tag": "", "name": "n", "provider_name": "p"}, 0) == "n#0"
    assert endpoint_key({"tag": 7, "name": None, "provider_name": "p"}, 2) == "p#2"
    assert endpoint_key({"name": "", "provider_name": ""}, 0) == endpoint_key({}, 0)
    unnamed = endpoint_key({"tag": None}, 3)
    assert unnamed == "#3"
    # The unnamed base is empty, so it cannot collide with any nonempty base.
    assert unnamed != endpoint_key({"tag": "unnamed"}, 3)
    with pytest.raises(ValueError):
        endpoint_key({"tag": "t"}, -1)

    entries = [
        {"tag": "dup", "context_length": 1},
        {"name": "solo"},
        {"tag": "dup", "context_length": 2},
        {},
        {"tag": "dup", "context_length": 3},
        {"provider_name": "solo"},
    ]
    keyed = key_endpoint_list(entries)
    assert [key for key, _ in keyed] == ["dup#0", "solo#0", "dup#1", "#0", "dup#2", "solo#1"]
    assert [entry for _, entry in keyed] == entries

    # Occurrence counting is per base, in response order: reordering entries that
    # share a base moves their contents between keys (documented limitation).
    reordered = dict(key_endpoint_list([entries[2], entries[0], entries[4]]))
    original = dict(key_endpoint_list([entries[0], entries[2], entries[4]]))
    assert reordered["dup#0"]["context_length"] == 2
    assert original["dup#0"]["context_length"] == 1
    changes = diff_endpoint_lists(
        {key: (dict(entry), None) for key, entry in original.items()},
        {key: (dict(entry), None) for key, entry in reordered.items()},
    )
    assert [(c.endpoint_key, c.field_name) for c in changes] == [
        ("dup#0", "context_length"),
        ("dup#1", "context_length"),
    ]
    assert key_endpoint_list([]) == ()


def test_endpoint_telemetry_and_status_identity() -> None:
    base = _endpoint()
    state = endpoint_state(base, OPENROUTER_PROFILE)
    assert "uptime_last_30m" not in state
    assert "latency_last_30m" not in state
    assert "status" not in state
    assert state["pricing"] == {"prompt": "0.000001", "completion": "0.000002"}
    assert endpoint_status(base, OPENROUTER_PROFILE) == 0
    # The input is not mutated.
    assert base["status"] == 0 and "uptime_last_30m" in base

    # Telemetry-only differences leave the hash unchanged; stable fields do not.
    noisy = _endpoint(uptime_last_30m=12.0, latency_last_30m={"p50": 1})
    assert endpoint_state_hash(endpoint_state(noisy, OPENROUTER_PROFILE)) == endpoint_state_hash(
        state
    )
    assert endpoint_state_hash(
        endpoint_state(_endpoint(quantization="int4"), OPENROUTER_PROFILE)
    ) != endpoint_state_hash(state)
    # Status is not part of the hash.
    assert endpoint_state_hash(
        endpoint_state(_endpoint(status=-5), OPENROUTER_PROFILE)
    ) == endpoint_state_hash(state)

    expected = hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()
    assert endpoint_state_hash(state) == expected
    assert endpoint_state_hash({"b": 1, "a": 2}) == endpoint_state_hash({"a": 2, "b": 1})

    # Profiles without endpoint metadata keep every field and report no status.
    assert endpoint_state(base, GENERIC_PROFILE) == base
    assert endpoint_status(base, GENERIC_PROFILE) is None
    assert endpoint_status({"name": "x"}, OPENROUTER_PROFILE) is None

    # Telemetry-only differences produce no diff; a status change is its own kind.
    assert diff_endpoint_lists(
        {"a#0": _observation(base)}, {"a#0": _observation(noisy)}
    ) == ()
    changes = diff_endpoint_lists(
        {"a#0": _observation(base)}, {"a#0": _observation(_endpoint(status=-5))}
    )
    assert changes == (EndpointChange("a#0", "status_changed", None, 0, -5),)


def test_endpoint_change_kinds() -> None:
    kept = _endpoint(tag="kept")
    gone = _endpoint(tag="gone")
    fresh = _endpoint(tag="fresh")
    old = {
        "kept#0": _observation(kept),
        "gone#0": _observation(gone),
    }
    new_kept = _endpoint(
        tag="kept",
        context_length=16000,
        quantization=None,
        status=-1,
        pricing={"prompt": "0.000003", "completion": "0.000002"},
    )
    new_kept["supports_new_thing"] = True
    new = {
        "kept#0": _observation(new_kept),
        "fresh#0": _observation(fresh),
    }
    changes = diff_endpoint_lists(old, new)

    by_kind: dict[str, list[EndpointChange]] = {}
    for change in changes:
        by_kind.setdefault(change.change_kind, []).append(change)
    assert set(by_kind) == {"endpoint_added", "endpoint_removed", "field_changed", "status_changed"}

    (removed,) = by_kind["endpoint_removed"]
    assert (removed.endpoint_key, removed.field_name, removed.new_value) == ("gone#0", None, None)
    assert removed.old_value == endpoint_state(gone, OPENROUTER_PROFILE)
    (added,) = by_kind["endpoint_added"]
    assert (added.endpoint_key, added.field_name, added.old_value) == ("fresh#0", None, None)
    assert added.new_value == endpoint_state(fresh, OPENROUTER_PROFILE)

    fields = {c.field_name: (c.old_value, c.new_value) for c in by_kind["field_changed"]}
    assert fields == {
        "context_length": (8000, 16000),
        "pricing.prompt": ("0.000001", "0.000003"),
        "quantization": ("fp8", None),
        "supports_new_thing": (None, True),
    }
    assert [c.field_name for c in by_kind["field_changed"]] == sorted(fields)
    assert all(c.endpoint_key == "kept#0" for c in by_kind["field_changed"])
    (status,) = by_kind["status_changed"]
    assert (status.endpoint_key, status.old_value, status.new_value) == ("kept#0", 0, -1)

    # Removed, then changed (old order), then added: deterministic output order.
    assert [c.change_kind for c in changes] == [
        "field_changed", "field_changed", "field_changed", "field_changed",
        "status_changed", "endpoint_removed", "endpoint_added",
    ]

    assert diff_endpoint_lists({}, {}) == ()
    assert diff_endpoint_lists({"kept#0": _observation(kept)}, {"kept#0": _observation(kept)}) == ()


def test_endpoint_override_parent_changes() -> None:
    rule_a = {"min_prompt_tokens": 200000, "prompt": "0.000004"}
    rule_b = {"min_prompt_tokens": 200000, "prompt": "0.000005"}

    def with_overrides(overrides: Any, **pricing: Any) -> dict[str, Any]:
        merged = {"prompt": "0.000001", **pricing}
        if overrides is not None:
            merged["overrides"] = overrides
        return _endpoint(pricing=merged)

    # Changed override list: one parent-level change, no descendant selector/rate paths.
    changes = diff_endpoint_lists(
        {"e#0": _observation(with_overrides([rule_a]))},
        {"e#0": _observation(with_overrides([rule_b, rule_a]))},
    )
    assert changes == (
        EndpointChange("e#0", "field_changed", "pricing.overrides", [rule_a], [rule_b, rule_a]),
    )

    # An override object (not a list) is still opaque.
    changes = diff_endpoint_lists(
        {"e#0": _observation(with_overrides({"k": {"prompt": "1"}}))},
        {"e#0": _observation(with_overrides({"k": {"prompt": "2"}}))},
    )
    assert [c.field_name for c in changes] == ["pricing.overrides"]

    # Overrides added/removed beside an unchanged pricing object.
    added = diff_endpoint_lists(
        {"e#0": _observation(with_overrides(None))},
        {"e#0": _observation(with_overrides([rule_a]))},
    )
    assert added == (EndpointChange("e#0", "field_changed", "pricing.overrides", None, [rule_a]),)
    removed = diff_endpoint_lists(
        {"e#0": _observation(with_overrides([rule_a]))},
        {"e#0": _observation(with_overrides(None))},
    )
    assert removed == (
        EndpointChange("e#0", "field_changed", "pricing.overrides", [rule_a], None),
    )

    # Parent object added or removed: overrides stay one parent-level change and
    # scalar children are reported individually rather than as one `pricing` blob.
    without_pricing = {k: v for k, v in _endpoint().items() if k != "pricing"}
    with_pricing = with_overrides([rule_a], completion="0.000002")
    appeared = diff_endpoint_lists(
        {"e#0": _observation(without_pricing)}, {"e#0": _observation(with_pricing)}
    )
    assert {c.field_name: (c.old_value, c.new_value) for c in appeared} == {
        "pricing.completion": (None, "0.000002"),
        "pricing.overrides": (None, [rule_a]),
        "pricing.prompt": (None, "0.000001"),
    }
    vanished = diff_endpoint_lists(
        {"e#0": _observation(with_pricing)}, {"e#0": _observation(without_pricing)}
    )
    assert {c.field_name: (c.old_value, c.new_value) for c in vanished} == {
        "pricing.completion": ("0.000002", None),
        "pricing.overrides": ([rule_a], None),
        "pricing.prompt": ("0.000001", None),
    }
    assert not any(
        c.field_name and c.field_name.startswith("pricing.overrides[") for c in appeared + vanished
    )

    # A null pricing value on one side behaves like a missing parent.
    null_parent = diff_endpoint_lists(
        {"e#0": _observation(_endpoint(pricing=None))},
        {"e#0": _observation(with_overrides([rule_a]))},
    )
    assert "pricing.overrides" in {c.field_name for c in null_parent}
    assert "pricing" not in {c.field_name for c in null_parent}

    # Unchanged identical overrides are no change.
    assert diff_endpoint_lists(
        {"e#0": _observation(with_overrides([rule_a]))},
        {"e#0": _observation(with_overrides([dict(rule_a)]))},
    ) == ()


@pytest.mark.parametrize(
    "requested,failed,mapping,exception,expected",
    [
        (0, 0, 0, False, CAPTURE_COMPLETE),  # empty catalog / nothing to fetch
        (5, 0, 0, False, CAPTURE_COMPLETE),
        (5, 1, 0, False, CAPTURE_PARTIAL),
        (5, 0, 2, False, CAPTURE_PARTIAL),
        (5, 2, 1, False, CAPTURE_PARTIAL),
        (5, 5, 0, False, CAPTURE_ERROR),
        (5, 5, 3, False, CAPTURE_ERROR),
        (0, 0, 4, False, CAPTURE_ERROR),  # failure and no successful path
        (1, 1, 0, False, CAPTURE_ERROR),
        (5, 0, 0, True, CAPTURE_ERROR),  # capture-level exception
        (0, 0, 0, True, CAPTURE_ERROR),
    ],
)
def test_endpoint_status_aggregation(
    requested: int, failed: int, mapping: int, exception: bool, expected: str
) -> None:
    assert (
        aggregate_capture_status(
            paths_requested=requested,
            paths_failed=failed,
            mapping_failures=mapping,
            capture_exception=exception,
        )
        == expected
    )


def test_endpoint_status_aggregation_rejects_impossible_counts() -> None:
    for kwargs in (
        {"paths_requested": -1, "paths_failed": 0, "mapping_failures": 0},
        {"paths_requested": 1, "paths_failed": 2, "mapping_failures": 0},
        {"paths_requested": 1, "paths_failed": -1, "mapping_failures": 0},
        {"paths_requested": 1, "paths_failed": 0, "mapping_failures": -1},
    ):
        with pytest.raises(ValueError):
            aggregate_capture_status(**kwargs)
    assert endpoints.CAPTURE_STATUSES == (CAPTURE_COMPLETE, CAPTURE_PARTIAL, CAPTURE_ERROR)


def test_endpoint_price_leaf_namespace() -> None:
    metadata = {
        "id": "fake-org/test-model-a",
        "pricing": {
            "prompt": "0.000001",
            "completion": 0.000002,
            "request": "0",
            "mystery_unit": "0.5",
            "discount": None,
            "flag": True,
            "label": "not-a-price",
            "overrides": [{"min_prompt_tokens": 200000, "prompt": "0.000004"}],
            "nested": {"prompt": "0.000009"},
        },
        "top_provider": {"max_completion_tokens": 100},
        "prompt": "0.5",
    }
    leaves = resolved_price_leaves(metadata, OPENROUTER_PROFILE)
    by_path = {leaf.path: leaf for leaf in leaves}

    # Only direct scalar children of `pricing`: no objects, arrays, overrides,
    # descendants or top-level keys.
    assert set(by_path) == {
        "pricing.prompt",
        "pricing.completion",
        "pricing.request",
        "pricing.mystery_unit",
        "pricing.discount",
        "pricing.flag",
        "pricing.label",
    }
    assert [leaf.path for leaf in leaves] == sorted(by_path)

    prompt = by_path["pricing.prompt"]
    assert prompt.resolved is True
    assert prompt.raw_value == "0.000001"
    assert prompt.normalized_exact_value == Fraction(1)  # 1e-6 per token -> 1 per 1M
    assert prompt.unit_label == "/1M tokens"
    assert prompt.comparison_group == "usd_per_million_tokens"
    assert by_path["pricing.completion"].normalized_exact_value == Fraction(2)
    assert by_path["pricing.completion"].comparison_group == prompt.comparison_group

    request = by_path["pricing.request"]
    assert request.resolved is True
    assert request.unit_label == "/request"
    assert request.comparison_group != prompt.comparison_group

    # Unresolved scalars stay visible but carry no arithmetic identity.
    for path in ("pricing.mystery_unit", "pricing.discount", "pricing.flag", "pricing.label"):
        leaf = by_path[path]
        assert leaf.resolved is False, path
        assert leaf.normalized_exact_value is None
        assert leaf.unit_label is None
        assert leaf.comparison_group is None
    assert by_path["pricing.flag"].raw_value is True
    assert by_path["pricing.discount"].raw_value is None

    # No pricing, or pricing of the wrong shape, yields no leaves.
    assert resolved_price_leaves({"id": "x"}, OPENROUTER_PROFILE) == ()
    assert resolved_price_leaves({"pricing": None}, OPENROUTER_PROFILE) == ()
    assert resolved_price_leaves({"pricing": ["0.1"]}, OPENROUTER_PROFILE) == ()
    assert resolved_price_leaves({"pricing": {}}, OPENROUTER_PROFILE) == ()

    # The generic profile has no declared price fields, so nothing resolves.
    generic = resolved_price_leaves({"pricing": {"prompt": "0.1"}}, GENERIC_PROFILE)
    assert [(leaf.path, leaf.resolved) for leaf in generic] == [("pricing.prompt", False)]


@pytest.mark.parametrize("overrides", (None, "not-a-policy", 0, True, [], {}))
def test_endpoint_price_leaf_namespace_excludes_overrides_of_any_type(overrides) -> None:
    """`pricing.overrides` is a policy, never a scalar price leaf, whatever its value."""
    metadata = {"pricing": {"prompt": "0.000001", "overrides": overrides}}
    leaves = resolved_price_leaves(metadata, OPENROUTER_PROFILE)
    assert [leaf.path for leaf in leaves] == ["pricing.prompt"]


def test_endpoint_price_leaf_namespace_single_leaf_keeps_resolved_price() -> None:
    leaf = endpoints.resolve_price_leaf("pricing.prompt", "0.000003", OPENROUTER_PROFILE)
    assert (leaf.resolved, leaf.normalized_exact_value, leaf.unit_label) == (
        True,
        Fraction(3),
        "/1M tokens",
    )
    assert leaf.price is not None
    assert leaf.price.normalized_exact_value == Fraction(3)
    # The full resolved value takes no part in equality.
    assert leaf == endpoints.PriceLeaf(
        "pricing.prompt", "0.000003", True, Fraction(3), "/1M tokens", "usd_per_million_tokens"
    )
    unresolved = endpoints.resolve_price_leaf("pricing.mystery_unit", "0.5", OPENROUTER_PROFILE)
    assert (unresolved.resolved, unresolved.price) == (False, None)
    collected = resolved_price_leaves({"pricing": {"prompt": "0.000003"}}, OPENROUTER_PROFILE)
    assert collected[0].price is not None
