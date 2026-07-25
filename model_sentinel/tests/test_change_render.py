"""Unit tests for model_sentinel.change_render.

Covers the RenderedChange shape and every branch of classify_change's
cascade: noop, list, price, count, numeric, boolean, scalar.

IMPORTANT ORDERING NOTE (see change_render.py module docstring): the
production renderer this module is extracted from treats a real Python
`bool` pair as numeric, not boolean, because `_both_numeric()` calls
`float()` and `bool` is a subclass of `int`. classify_change here
deliberately reproduces that today, with numeric/price/count checked before
boolean. The tests below assert the CURRENT ordering on purpose --
`test_real_bool_pair_currently_classifies_as_numeric` and
`test_known_boolean_int_pair_currently_classifies_as_numeric` exist so that
Task 4 (E2) flipping the boolean branch ahead of numeric shows up as a
visible, deliberate test change rather than a silent one.
"""

from __future__ import annotations

import dataclasses

import pytest

from model_sentinel.change_render import (
    KNOWN_BOOLEAN_FIELDS,
    RenderedChange,
    _bool_state,
    _both_numeric,
    _classify_boolean,
    _fmt_int,
    _fmt_price_per_m,
    _is_boolean_change,
    _is_count_field,
    _list_diff_members,
    _list_item_text,
    _normalize_price,
    _pct_change,
    classify_change,
)
from model_sentinel.models import FieldChange

# Still re-exported from reporting.py because non-renderer call sites there
# (category grouping, _price_movement_kind) call them directly. The six other
# primitives that moved to change_render.py lost their reporting.py call sites
# when Task 3 rewired the renderers onto RenderedChange, so their transitional
# re-export shims were dropped and they are imported above from their real home.
from model_sentinel.reporting import (
    _classify_field,
    _is_price_amount_field,
    _list_change_signature,
    _numeric_value,
)


# ---------------------------------------------------------------------------
# RenderedChange shape
# ---------------------------------------------------------------------------


def test_rendered_change_is_frozen_with_expected_fields():
    field_names = {f.name for f in dataclasses.fields(RenderedChange)}
    assert field_names == {
        "kind",
        "field_path",
        "label",
        "qualifier",
        "old_display",
        "new_display",
        "old_raw",
        "new_raw",
        "unit",
        "delta_display",
        "delta_abs",
        "pct_display",
        "pct_basis_zero",
        "direction",
        "semantic",
        "list_added",
        "list_removed",
    }

    result = classify_change(FieldChange("status", None, None))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.kind = "scalar"


# ---------------------------------------------------------------------------
# 1. noop
# ---------------------------------------------------------------------------


def test_none_to_none_is_noop():
    result = classify_change(FieldChange("expiration_date", None, None))
    assert result.kind == "noop"
    assert result.direction == "none"
    assert result.semantic == "neutral"


def test_equal_values_is_noop():
    result = classify_change(FieldChange("status", "active", "active"))
    assert result.kind == "noop"
    assert result.direction == "none"
    assert result.semantic == "neutral"


# ---------------------------------------------------------------------------
# 2. list
# ---------------------------------------------------------------------------


def test_list_membership_change():
    result = classify_change(
        FieldChange("supported_parameters", ["tools", "logprobs"], ["tools", "stop"])
    )
    assert result.kind == "list"
    assert result.direction == "none"
    assert result.semantic == "capability"
    assert result.unit == "items"
    assert result.list_added == ("stop",)
    assert result.list_removed == ("logprobs",)


# ---------------------------------------------------------------------------
# 3. price
# ---------------------------------------------------------------------------


def test_price_both_numeric_increase():
    result = classify_change(
        FieldChange("pricing.prompt", "0.000001", "0.000002"),
        price_multiplier=1_000_000,
        price_divisor=1,
    )
    assert result.kind == "price"
    assert result.direction == "up"
    assert result.semantic == "cost"
    assert result.unit == "/1M"
    assert result.old_display == "$1.00"
    assert result.new_display == "$2.00"
    assert result.delta_abs == 1.0


def test_price_both_numeric_decrease():
    result = classify_change(
        FieldChange("pricing.prompt", "0.000002", "0.000001"),
        price_multiplier=1_000_000,
        price_divisor=1,
    )
    assert result.kind == "price"
    assert result.direction == "down"
    assert result.semantic == "cost"


def test_price_none_to_value_is_added():
    result = classify_change(
        FieldChange("pricing.prompt", None, "0.000002"),
        price_multiplier=1_000_000,
        price_divisor=1,
    )
    assert result.kind == "price"
    assert result.direction == "added"
    assert result.semantic == "coverage"
    assert result.old_display == "null"
    assert result.new_display == "$2.00"
    assert result.delta_display is None
    assert result.pct_display is None


def test_price_value_to_none_is_removed():
    result = classify_change(
        FieldChange("pricing.prompt", "0.000002", None),
        price_multiplier=1_000_000,
        price_divisor=1,
    )
    assert result.kind == "price"
    assert result.direction == "removed"
    assert result.semantic == "coverage"
    assert result.old_display == "$2.00"
    assert result.new_display == "null"


def test_price_field_rejects_non_numeric_string():
    """The price guard permits one-sided None but must reject malformed strings."""
    result = classify_change(FieldChange("pricing.prompt", "N/A", "0.000002"))
    assert result.kind != "price"
    assert result.kind == "scalar"


def test_price_amount_field_excludes_token_thresholds():
    # A pricing.* field whose leaf contains "token" is not a price *amount*
    # field (it's a threshold), so it should not classify as price.
    assert _is_price_amount_field("pricing.max_prompt_tokens") is False


# ---------------------------------------------------------------------------
# 4. count
# ---------------------------------------------------------------------------


def test_context_length_change_is_count():
    result = classify_change(FieldChange("context_length", 8192, 16384))
    assert result.kind == "count"
    assert result.direction == "up"
    assert result.semantic == "capacity"
    assert result.unit == "tok"
    assert result.old_display == "8,192"
    assert result.new_display == "16,384"
    assert result.delta_abs == 8192.0


def test_context_length_decrease_is_count_down():
    result = classify_change(FieldChange("context_length", 16384, 8192))
    assert result.kind == "count"
    assert result.direction == "down"
    assert result.semantic == "capacity"


def test_count_one_sided_added():
    result = classify_change(
        FieldChange("top_provider.max_completion_tokens", None, 4096)
    )
    assert result.kind == "count"
    assert result.direction == "added"
    assert result.semantic == "coverage"
    assert result.old_display == "null"
    assert result.new_display == "4,096"
    assert result.delta_display is None
    assert result.pct_display is None


def test_count_one_sided_removed():
    result = classify_change(
        FieldChange("top_provider.max_completion_tokens", 4096, None)
    )
    assert result.kind == "count"
    assert result.direction == "removed"
    assert result.semantic == "coverage"


def test_count_field_rejects_non_numeric_string():
    result = classify_change(FieldChange("context_length", "unknown", 16384))
    assert result.kind != "count"
    assert result.kind == "scalar"


def test_two_sided_count_must_render_like_numeric_for_neutrality():
    """Finding 1 (review fix pass): this module's count guard deliberately
    drops the fifth clause of reporting.py's equivalent guard (`and
    (old_numeric is None or new_numeric is None)`), so a two-sided count
    change classifies as `count`/`capacity` here instead of `numeric`/
    `neutral` as production does. That is the approved design (two-sided
    numeric count fields need "capacity" semantics) -- but it means a
    renderer built on this module MUST render a two-sided `count` change
    IDENTICALLY to `numeric`: same `(+delta, pct)` suffix, no `tok` unit. This
    test pins the exact fields a renderer needs to reproduce numeric's output
    from a `count` RenderedChange, so a renderer that instead prints a `tok`
    unit or omits the pct suffix for `count` breaks this test, not silence.
    """
    result = classify_change(FieldChange("context_length", 8192, 16384))
    assert result.kind == "count"
    assert result.semantic == "capacity"
    assert result.delta_display == "+8,192"
    assert result.pct_display == "↑ 100.0%"
    assert result.delta_abs == 8192.0
    assert result.old_display == "8,192"
    assert result.new_display == "16,384"


# ---------------------------------------------------------------------------
# 5. numeric fallback (and the transitional-ordering documentation tests)
# ---------------------------------------------------------------------------


def test_real_bool_pair_currently_classifies_as_numeric():
    """Pinned per the Task 2 ordering directive: today's production code
    renders a real bool pair via the numeric path (`0 -> 1 (+1)`), not as a
    boolean toggle -- the dedicated boolean branch is currently dead code
    for this case. Task 4 (E2) promotes boolean ahead of numeric and this
    test is expected to change at that point, deliberately."""
    result = classify_change(FieldChange("top_provider.is_moderated", False, True))
    assert result.kind == "numeric"
    assert result.direction == "up"
    assert result.old_display == "0"
    assert result.new_display == "1"


def test_known_boolean_int_pair_currently_classifies_as_numeric():
    """Same E2 defect, integer-coded form: reasoning.default_enabled is in
    KNOWN_BOOLEAN_FIELDS, but under the current transitional ordering a
    two-sided 0/1 pair is still caught by the numeric branch first."""
    result = classify_change(FieldChange("reasoning.default_enabled", 0, 1))
    assert result.kind == "numeric"
    assert result.direction == "up"


def test_unclassified_numeric_fallback():
    result = classify_change(FieldChange("some.arbitrary.metric", 10, 20))
    assert result.kind == "numeric"
    assert result.direction == "up"
    assert result.semantic == "neutral"
    assert result.delta_abs == 10.0


# ---------------------------------------------------------------------------
# 5b. pct_basis_zero -- the explicit "no percentage is defined" signal that
# _render_html_table_row reads when choosing a delta CSS class. It replaced an
# inference over `pct_display is None`; these tests pin that it tracks the
# CAUSE (a zero old value) and not any of the nearby signals a future refactor
# might be tempted to substitute for it.
# ---------------------------------------------------------------------------


def test_pct_basis_zero_true_when_old_value_is_zero():
    for field, old, new, kind in (
        ("some.arbitrary.metric", 0, 20, "numeric"),
        ("top_provider.context_length", 0, 4096, "count"),
        ("pricing.completion", 0, 0.000002, "price"),
    ):
        result = classify_change(FieldChange(field, old, new))
        assert result.kind == kind, field
        assert result.pct_basis_zero is True, field
        assert result.pct_display is None, field


def test_pct_basis_zero_false_when_old_value_is_nonzero():
    for field, old, new, kind in (
        ("some.arbitrary.metric", 10, 20, "numeric"),
        ("top_provider.context_length", 4096, 8192, "count"),
        ("pricing.completion", 0.000002, 0.000003, "price"),
    ):
        result = classify_change(FieldChange(field, old, new))
        assert result.kind == kind, field
        assert result.pct_basis_zero is False, field
        assert result.pct_display is not None, field


def test_pct_basis_zero_is_not_the_same_signal_as_direction_none():
    """`direction == "none"` is NOT a valid substitute for `pct_basis_zero`.

    The two come apart in both directions, which is why the HTML delta-class
    branch needs a dedicated field:

    * `0 -> 20` has no percentage basis but moved up, so `direction == "up"`.
    * `"5" -> 5` is not caught by the noop branch (`"5" == 5` is False) yet has
      a zero delta, so `direction == "none"` while a percentage is still
      defined and displayed.
    """
    no_basis_but_moved = classify_change(FieldChange("some.arbitrary.metric", 0, 20))
    assert no_basis_but_moved.pct_basis_zero is True
    assert no_basis_but_moved.direction == "up"

    zero_delta_with_basis = classify_change(FieldChange("some.arbitrary.metric", "5", 5))
    assert zero_delta_with_basis.direction == "none"
    assert zero_delta_with_basis.pct_basis_zero is False
    assert zero_delta_with_basis.pct_display is not None


def test_pct_basis_zero_false_for_kinds_that_never_compute_a_percentage():
    # One-sided price/count have no basis to compare against, and
    # list/scalar/noop never compute a percentage at all. All must report
    # False so a renderer reading this field does not mistake them for a
    # zero-basis numeric move.
    cases = (
        FieldChange("pricing.completion", None, 0.000002),
        FieldChange("pricing.completion", 0.000002, None),
        FieldChange("top_provider.max_completion_tokens", None, 16384),
        FieldChange("top_provider.max_completion_tokens", 8192, None),
        FieldChange("supported_parameters", ["tools"], ["tools", "logit_bias"]),
        FieldChange("expiration_date", None, "2030-12-31"),
        FieldChange("expiration_date", None, None),
    )
    for field_change in cases:
        result = classify_change(field_change)
        assert result.pct_basis_zero is False, field_change.field_name


def _rendered_change_kwargs(**overrides):
    """Minimal valid RenderedChange kwargs, for constructor-invariant tests."""
    kwargs = dict(
        kind="numeric",
        field_path="some.arbitrary.metric",
        label="some.arbitrary.metric",
        qualifier=None,
        old_display="0",
        new_display="20",
        old_raw="0",
        new_raw="20",
        unit=None,
        delta_display="+20",
        delta_abs=20.0,
        pct_display=None,
        pct_basis_zero=True,
        direction="up",
        semantic="neutral",
        list_added=(),
        list_removed=(),
    )
    kwargs.update(overrides)
    return kwargs


def test_rendered_change_rejects_zero_basis_with_a_percentage():
    """`pct_basis_zero` and `pct_display` are set independently at ~10
    construction sites with nothing but convention keeping them in step. A zero
    basis makes the percentage undefined, so the pair is incoherent and
    `__post_init__` must refuse to construct it."""
    with pytest.raises(ValueError, match="pct_basis_zero=True requires pct_display=None"):
        RenderedChange(**_rendered_change_kwargs(pct_basis_zero=True, pct_display="↑ 5.0%"))


def test_rendered_change_allows_absent_percentage_without_a_zero_basis():
    """The check is deliberately one-directional. `pct_display is None` does NOT
    imply a zero basis -- one-sided price/count changes and every
    list/boolean/scalar/noop change have no percentage and no zero basis -- so
    the converse must stay constructible."""
    result = RenderedChange(**_rendered_change_kwargs(pct_basis_zero=False, pct_display=None))
    assert result.pct_basis_zero is False
    assert result.pct_display is None

    # And the two consistent "has a percentage" / "has a zero basis" forms.
    assert RenderedChange(**_rendered_change_kwargs(pct_basis_zero=False, pct_display="↑ 5.0%"))
    assert RenderedChange(**_rendered_change_kwargs(pct_basis_zero=True, pct_display=None))


def test_every_classify_change_construction_site_satisfies_the_invariant():
    """`__post_init__` guards the dataclass; this walks the real cascade so a
    future construction site that sets the pair inconsistently fails here even
    if no golden happens to cover it."""
    cases = (
        FieldChange("some.arbitrary.metric", 0, 20),
        FieldChange("some.arbitrary.metric", 10, 20),
        FieldChange("top_provider.context_length", 0, 4096),
        FieldChange("top_provider.context_length", 4096, 8192),
        FieldChange("top_provider.context_length", None, 4096),
        FieldChange("top_provider.context_length", 4096, None),
        FieldChange("pricing.completion", 0, 0.000002),
        FieldChange("pricing.completion", 0.000002, 0.000003),
        FieldChange("pricing.completion", None, 0.000002),
        FieldChange("pricing.completion", 0.000002, None),
        FieldChange("supported_parameters", ["tools"], ["tools", "logit_bias"]),
        FieldChange("expiration_date", None, "2030-12-31"),
        FieldChange("expiration_date", None, None),
    )
    for field_change in cases:
        result = classify_change(field_change)
        if result.pct_basis_zero:
            assert result.pct_display is None, field_change.field_name


# ---------------------------------------------------------------------------
# 2b. list member stringification -- ONE convention, shared with the bulk
# grouping key and the bulk renderers in reporting.py. `dict`/`list` members
# are JSON-encoded; Python repr must never reach rendered output.
# ---------------------------------------------------------------------------


def test_list_members_are_json_encoded_not_python_repr():
    result = classify_change(
        FieldChange("architecture.tier_profiles", [{"name": "alpha", "weight": 1}], [{"name": "alpha", "weight": 2}])
    )
    assert result.kind == "list"
    assert result.list_added == ('{"name": "alpha", "weight": 2}',)
    assert result.list_removed == ('{"name": "alpha", "weight": 1}',)


def test_list_member_stringification_matches_the_bulk_grouping_key():
    """The exact defect this unification removed: the bulk grouping key and the
    per-model list branch must spell a structured member identically."""
    field_change = FieldChange(
        "architecture.tier_profiles", [{"name": "alpha", "weight": 1}], [{"name": "alpha", "weight": 2}]
    )
    result = classify_change(field_change)
    assert _list_change_signature(field_change) == (
        result.field_path,
        result.list_added,
        result.list_removed,
    )


def test_grouping_key_does_not_route_through_the_noop_branch():
    """Why `_list_change_signature` calls `_list_diff_members` and NOT
    `classify_change`.

    `classify_change` checks `noop` (`old_value == new_value`) before the list
    branch, and Python list equality is not member-text equality: `[1] ==
    [True]` is True while the two spell as `"1"` and `"True"`. Routing the
    grouping key through the cascade would collapse this to the empty pair and
    change which models consolidate. The key must keep reporting the
    difference, byte-identically to its pre-unification behavior.

    (Unreachable in production -- `diffing._diff_values` emits a FieldChange
    only when `old_value != new_value` -- but the grouping guarantee is
    unconditional, not conditional on that argument.)
    """
    field_change = FieldChange("supported_parameters", [1], [True])
    assert field_change.old_value == field_change.new_value

    assert classify_change(field_change).kind == "noop"
    assert _list_change_signature(field_change) == ("supported_parameters", ("True",), ("1",))


def test_list_diff_members_is_the_one_shared_set_difference():
    for old, new in (
        (["tools"], ["tools", "logit_bias"]),
        ([{"b": 2, "a": 1}], [{"a": 1, "b": 3}]),
        (["a", "a", "b"], ["a", "b", "b"]),
        ([], []),
    ):
        rendered = classify_change(FieldChange("supported_parameters", old, new))
        expected = _list_diff_members(old, new)
        if rendered.kind == "list":
            assert (rendered.list_added, rendered.list_removed) == expected, (old, new)
        assert _list_change_signature(FieldChange("supported_parameters", old, new))[1:] == expected


def test_string_list_members_render_bare():
    """Unchanged by the unification: `str` members are returned as-is, so the
    overwhelmingly common case still renders `+tools`, not `+"tools"`."""
    result = classify_change(FieldChange("supported_parameters", ["tools"], ["tools", "logit_bias"]))
    assert result.list_added == ("logit_bias",)
    assert result.list_removed == ()


def test_non_string_scalar_list_members_use_str():
    result = classify_change(FieldChange("supported_parameters", [1, None], [1, True]))
    assert result.list_added == ("True",)
    assert result.list_removed == ("None",)


def test_list_item_text_conventions():
    assert _list_item_text("tools") == "tools"
    # dict/list members: JSON, key-sorted, never Python repr.
    assert _list_item_text({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'
    assert _list_item_text(["x", "y"]) == '["x", "y"]'
    assert "'" not in _list_item_text({"name": "alpha"})
    # Everything else falls back to str().
    assert _list_item_text(5) == "5"
    assert _list_item_text(None) == "None"
    assert _list_item_text(True) == "True"


# ---------------------------------------------------------------------------
# 6. boolean -- currently UNREACHABLE through classify_change (see module
# docstring and Finding 2/3 fix below): every two-sided bool/known-boolean-int
# pair is caught by the numeric branch (step 5) first, and one-sided
# (bool-vs-None) pairs now fall through to scalar (step 7) instead of being
# coerced into a boolean toggle. `_classify_boolean` itself is still directly
# unit-tested below so it stays correct for when Task 4 promotes this branch
# ahead of numeric.
# ---------------------------------------------------------------------------


def test_boolean_one_sided_added_from_none_falls_through_to_scalar():
    """Finding 2 fix: a bool paired with None must NOT classify as boolean --
    production's dedicated boolean branch requires `isinstance(old, bool) and
    isinstance(new, bool)`, so a one-sided change like this falls through to
    its generic scalar fallback (`_render_value`). Before this fix,
    `_is_boolean_change`'s `or` let this incorrectly classify as `boolean`
    with a fabricated on/off display, which would have silently changed
    output once this module is wired into the renderers (no fixture in
    tests/test_render_characterization.py covered a bool-vs-None case, so
    nothing would have caught it)."""
    result = classify_change(FieldChange("top_provider.is_moderated", None, True))
    assert result.kind == "scalar"
    assert result.direction == "none"
    assert result.semantic == "neutral"
    assert result.old_display == "null"
    assert result.new_display == "True"


def test_boolean_one_sided_removed_to_none_falls_through_to_scalar():
    """Same fix, mirrored direction."""
    result = classify_change(FieldChange("top_provider.is_moderated", True, None))
    assert result.kind == "scalar"
    assert result.direction == "none"
    assert result.semantic == "neutral"
    assert result.old_display == "True"
    assert result.new_display == "null"


def test_classify_boolean_helper_still_produces_boolean_kind_directly():
    """`_classify_boolean` is unreachable through classify_change today (see
    section docstring above) but must stay correct for Task 4, which promotes
    the boolean branch ahead of numeric. Exercised directly since
    classify_change can't reach it for a two-sided bool pair under the
    current transitional ordering."""
    result = _classify_boolean(FieldChange("top_provider.is_moderated", False, True))
    assert result.kind == "boolean"
    assert result.direction == "up"
    assert result.semantic == "capability"
    assert result.old_display == "off"
    assert result.new_display == "on"
    assert result.delta_display == "enabled"


def test_classify_boolean_raises_for_non_boolean_value():
    """`_classify_boolean`'s precondition (both sides boolean-ish per
    `_bool_state`) is documented but was previously unenforced: calling it
    directly with a non-boolean value (bypassing `_is_boolean_change`) would
    fabricate `direction="down"` and put the literal string `None` into a
    `str`-typed display field. It must raise instead."""
    with pytest.raises(ValueError, match="default_parameters.top_p"):
        _classify_boolean(FieldChange("default_parameters.top_p", False, 0.9))
    with pytest.raises(ValueError, match="top_provider.is_moderated"):
        _classify_boolean(FieldChange("top_provider.is_moderated", None, True))
    with pytest.raises(ValueError, match="top_provider.is_moderated"):
        _classify_boolean(FieldChange("top_provider.is_moderated", True, None))


def test_is_boolean_change_true_for_real_bool_pair():
    """The boolean predicate itself (not the cascade) recognizes a real bool
    pair -- exercised directly since classify_change can't reach this branch
    for a two-sided bool pair under the transitional ordering."""
    assert _is_boolean_change(FieldChange("top_provider.is_moderated", False, True)) is True


def test_is_boolean_change_true_for_known_boolean_int_pair():
    """Likewise for the known-boolean integer-coded case."""
    assert _is_boolean_change(FieldChange("reasoning.default_enabled", 0, 1)) is True
    assert _is_boolean_change(FieldChange("reasoning.mandatory", 1, 0)) is True
    assert _is_boolean_change(FieldChange("deprecated", 0, 1)) is True


def test_is_boolean_change_false_for_one_sided_real_bool_pair():
    """Finding 2 fix, predicate-level: a bool paired with None is NOT a
    two-sided toggle. Before the fix, `_is_boolean_change` used `or`, which
    made this return True."""
    assert _is_boolean_change(FieldChange("top_provider.is_moderated", None, True)) is False
    assert _is_boolean_change(FieldChange("top_provider.is_moderated", True, None)) is False


def test_is_boolean_change_false_for_mixed_bool_and_numeric_pair():
    """Finding 3 regression: `default_parameters.top_p` is not in
    KNOWN_BOOLEAN_FIELDS, so a `False`/`0.9` pair must never be treated as a
    boolean toggle just because `old_value` happens to be a real bool.
    Fixing Finding 2's `or` -> `and` already prevents this via
    `_is_boolean_change` (one side, `0.9`, is not `isinstance(..., bool)`),
    but the latent bug was one level down in `_bool_state`: it used to return
    "off" for ANY unrecognized value via a bare fallthrough, so if
    `_is_boolean_change` (or a future caller, e.g. after Task 4 reorders the
    cascade) ever again let a mixed-type pair through, `_classify_boolean`
    would render `0.9` as "off" and fabricate `direction="down"` -- a real
    change reported as a disable. `_bool_state` must return None instead."""
    fc = FieldChange("default_parameters.top_p", False, 0.9)
    assert _is_boolean_change(fc) is False
    assert _bool_state(0.9) is None


def test_bool_state_returns_none_for_unrecognized_values():
    """`_bool_state` must never coerce a non-boolean-ish value to "off" --
    only real bool and integer-coded 0/1 are recognized."""
    assert _bool_state(True) == "on"
    assert _bool_state(False) == "off"
    assert _bool_state(1) == "on"
    assert _bool_state(0) == "off"
    assert _bool_state(1.0) == "on"
    assert _bool_state(0.0) == "off"
    assert _bool_state(0.9) is None
    assert _bool_state(2) is None
    assert _bool_state("yes") is None
    assert _bool_state(None) is None


def test_is_boolean_change_false_for_int_fields_outside_known_set():
    """The known-boolean set restriction is load-bearing: a genuinely
    numeric field holding 0/1 (e.g. a parameter magnitude) must not be
    treated as boolean just because its values happen to be 0 or 1."""
    assert _is_boolean_change(FieldChange("default_parameters.top_p", 0, 1)) is False
    assert _is_boolean_change(FieldChange("default_parameters.temperature", 0, 1)) is False
    assert (
        _is_boolean_change(FieldChange("default_parameters.repetition_penalty", 0, 1))
        is False
    )


def test_known_boolean_fields_set_contents():
    assert KNOWN_BOOLEAN_FIELDS == frozenset(
        {
            "top_provider.is_moderated",
            "reasoning.default_enabled",
            "reasoning.mandatory",
            "deprecated",
        }
    )


# ---------------------------------------------------------------------------
# 7. scalar fallback
# ---------------------------------------------------------------------------


def test_unclassified_scalar():
    result = classify_change(FieldChange("status", "active", "deprecated"))
    assert result.kind == "scalar"
    assert result.direction == "none"
    assert result.semantic == "neutral"
    assert result.old_display == "active"
    assert result.new_display == "deprecated"


def test_one_sided_list_scalar_matches_render_value_json_form():
    """Finding 4 fix: a one-sided list (old_value is None, so classify_change's
    list branch -- which requires BOTH sides to be `list` -- never engages)
    must format through the scalar fallback exactly like reporting.py's
    `_render_value`: `json.dumps(value, sort_keys=True, ensure_ascii=True)`
    for dict/list, not Python's `str(value)`. `str(['a', 'b'])` would give
    `"['a', 'b']"` (single quotes) -- a silent divergence from production's
    `'["a", "b"]'` (double quotes) once this module is wired into a renderer.
    """
    result = classify_change(FieldChange("some.arbitrary.list_field", None, ["a", "b"]))
    assert result.kind == "scalar"
    assert result.old_display == "null"
    assert result.new_display == '["a", "b"]'


# ---------------------------------------------------------------------------
# Step 1 in the brief: label/qualifier are the raw field_path in this task.
# ---------------------------------------------------------------------------


def test_label_and_qualifier_are_not_yet_populated_from_a_registry():
    result = classify_change(FieldChange("pricing.prompt", "0.000001", "0.000002"))
    assert result.field_path == "pricing.prompt"
    assert result.label == "pricing.prompt"
    assert result.qualifier is None


# ---------------------------------------------------------------------------
# Shared primitives: still correct wherever they are imported from.
# ---------------------------------------------------------------------------


def test_reporting_module_reexports_still_used_primitives():
    """The three primitives reporting.py still calls stay importable from it.

    Task 3 rewired reporting.py's renderers onto RenderedChange, which removed
    every reporting.py call site for the other six primitives; their
    transitional re-export shims were dropped rather than kept as unused
    imports. These three are still called there (by the category grouping
    helpers and _price_movement_kind), so they remain importable from
    reporting.py for external call sites that predate the move.
    """
    assert _classify_field("pricing.prompt") == "Pricing"
    assert _numeric_value("3.5") == 3.5
    assert _is_price_amount_field("pricing.prompt") is True


def test_shared_primitives_behave_the_same_in_change_render():
    """The six primitives no longer re-exported keep their exact behavior."""
    assert _both_numeric(1, 2) is True
    assert _is_count_field("context_length") is True
    assert _fmt_int(1024.0) == "1,024"
    assert _pct_change(10, 20) == "↑ 100.0%"
    assert _fmt_price_per_m(2.0) == "$2.00"
    assert _normalize_price(0.000002, 1_000_000, 1) == 2.0
