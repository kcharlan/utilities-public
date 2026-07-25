"""Unit tests for model_sentinel.change_render.

Covers the RenderedChange shape and every branch of classify_change's
cascade: noop, list, price, count, numeric, boolean, scalar.

BRANCH ORDER (see change_render.py module docstring): `boolean` is checked
BEFORE price/count/numeric. That ordering is load-bearing, not cosmetic:
Python's `bool` is a subclass of `int`, so `_both_numeric()` -- which calls
`float()` -- accepts a real `bool` pair, and for the whole pre-E2 life of
this code the numeric branch swallowed every boolean toggle
(`is_moderated: False -> True` rendered as `0 -> 1 (+1)`). Task 4 promoted
the boolean branch ahead of the numeric family; the ordering tests below
pin that so a future reshuffle cannot silently reinstate the defect.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest

from model_sentinel.change_render import (
    FIELD_LEAF_LABELS,
    FIELD_PATH_LABELS,
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
    _prettify_leaf,
    _split_field_path,
    classify_change,
    format_qualified_label,
    resolve_field_label,
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
# 3a. Price precision (Task 6)
#
# The rule: ONE precision per row -- the greater of the two operands'
# significant decimal places, floored at cents and capped at four -- applied
# identically to old, new and delta. It replaces a magnitude-based selection
# (2/4/6 places by size) under which a single card could show `$0.196` beside
# `$0.1876` beside `$0.0196`, decimal points landing in three different
# columns, and under which the three numbers of ONE row could each claim a
# different precision.
# ---------------------------------------------------------------------------


def _price_decimal_places(rendered_price: str) -> int:
    """Decimal places in a rendered price such as `$0.1425` or `-$0.0075`.

    Reads the DISPLAY string rather than re-deriving the precision from the
    input, so these assertions fail on what a reader would see. Rejects
    anything that is not a rendered price, so a `free`/`null`/`—` slipping
    into a precision comparison is a loud failure and not a silent 0.
    """
    body = rendered_price.lstrip("+-")
    assert body.startswith("$"), rendered_price
    whole, _, decimals = body[1:].partition(".")
    assert whole and decimals, rendered_price
    return len(decimals)


def _price_change(old: str, new: str, *, multiplier: int = 1, divisor: int = 1):
    """A two-sided `pricing.prompt` change, classified.

    `multiplier=1` means the raw values ARE the per-1M prices, which keeps the
    precision cases below readable: the number in the test is the number in the
    assertion. The float-noise case overrides it.
    """
    return classify_change(
        FieldChange("pricing.prompt", old, new),
        price_multiplier=multiplier,
        price_divisor=divisor,
    )


def test_cents_level_price_change_renders_two_places_on_every_value():
    """The design's first example: `$2.00 → $3.50`, delta `+$1.50`."""
    result = _price_change("2", "3.5")
    assert (result.old_display, result.new_display, result.delta_display) == (
        "$2.00",
        "$3.50",
        "+$1.50",
    )


def test_fourth_decimal_price_change_renders_four_places_on_every_value():
    """The design's second example: `$0.1500 → $0.1425`, delta `−$0.0075`.

    `0.15` alone needs two places. It renders at four because the OTHER operand
    needs four -- which is the whole point of deriving one precision from the
    pair rather than formatting each value on its own merits.
    """
    result = _price_change("0.15", "0.1425")
    assert (result.old_display, result.new_display, result.delta_display) == (
        "$0.1500",
        "$0.1425",
        "-$0.0075",
    )


def test_old_new_and_delta_always_share_one_precision():
    """THE invariant, asserted as an invariant.

    Not three expected strings that happen to agree: this compares the three
    rendered values against EACH OTHER, so a change that formats the delta from
    its own magnitude fails here even if every literal in the tests above were
    updated to match it.

    Each pair is one where independent per-value formatting would disagree:

      * `0.15 / 0.1425` -- operands disagree with each other (2 vs 4).
      * `0.1234 / 0.2234` -- operands agree at 4 but their difference is
        exactly `0.1`, which needs 2. This is the pair that catches a delta
        formatted from `abs(delta_norm)` alone.
      * `2 / 2.005` -- the mirror: the operands disagree (2 vs 3) and the delta
        needs 3, so nothing is pinned by coincidence.
      * `0.196 / 0.1876` -- the reported complaint, in its original numbers.
    """
    for old, new in (("0.15", "0.1425"), ("0.1234", "0.2234"), ("2", "2.005"), ("0.196", "0.1876")):
        result = _price_change(old, new)
        places = {
            _price_decimal_places(result.old_display),
            _price_decimal_places(result.new_display),
            _price_decimal_places(result.delta_display),
        }
        assert len(places) == 1, (old, new, result.old_display, result.new_display, result.delta_display)


def test_price_precision_is_not_chosen_by_magnitude():
    """The reported complaint, pinned on the values that produced it.

    Under the replaced rule these two rendered `$0.196` and `$0.1876`: three
    decimals against four, because the selection read each value's magnitude
    rather than the row's. Two numbers one column apart disagreed about how
    precise they were.
    """
    result = _price_change("0.196", "0.1876")
    assert result.old_display == "$0.1960"
    assert result.new_display == "$0.1876"


def test_price_precision_is_capped_at_four_places():
    """A value needing more renders AT four -- not at whatever survives rounding.

    `0.1234567` needs seven. It renders `$0.1235`: four places, rounded, with
    `old_raw` still carrying the exact value for the audit paths.
    """
    result = _price_change("0.1234567", "0.2")
    assert result.old_display == "$0.1235"
    assert result.new_display == "$0.2000"
    assert result.delta_display == "+$0.0765"
    assert result.old_raw == "0.1234567"


def test_price_smaller_than_the_cap_can_resolve_renders_at_the_cap():
    """The cap's uncomfortable case, stated rather than hidden.

    A per-token price of `0.000001` needs six places, so under the cap both
    sides of a genuine doubling render `$0.0000` and the normalized column
    stops discriminating. That is the design's open assumption #2 (values
    needing more than four places rely on the raw value for exactness), not an
    accident: `old_raw`/`new_raw` and the percentage still carry the change.
    """
    result = _price_change("0.000001", "0.000002")
    assert result.old_display == "$0.0000"
    assert result.new_display == "$0.0000"
    assert (result.old_raw, result.new_raw) == ("0.000001", "0.000002")
    assert result.pct_display == "↑ 100.0%"


def test_price_precision_ignores_normalization_float_noise():
    """`5e-08 * 1_000_000` is `0.049999999999999996`, and must still read `$0.05`.

    The operands' "significant decimal places" are the provider's, not those of
    the binary approximation `_normalize_price` produces. Without the relative
    tolerance in `_significant_decimals` this five-cent cache read would render
    `$0.0500` -- four places demanded by representation noise.
    """
    assert _normalize_price(0.00000005, 1_000_000, 1) != 0.05  # precondition: noisy
    result = _price_change("0.00000005", "0.00000009", multiplier=1_000_000)
    assert result.old_display == "$0.05"
    assert result.new_display == "$0.09"
    assert result.delta_display == "+$0.04"


def test_zero_price_still_renders_free_at_any_precision():
    """`free` survives the new rule, on both sides and however precise the row."""
    assert _fmt_price_per_m(0) == "free"
    assert _fmt_price_per_m(0.0, 4) == "free"
    assert _price_change("0", "0.1425").old_display == "free"
    assert _price_change("0.1425", "0").new_display == "free"


def test_one_sided_price_uses_its_own_operand_precision():
    """With one operand there is nothing to agree with, so it prices itself."""
    assert _price_change("0.1425", "0").old_display == "$0.1425"
    added = classify_change(
        FieldChange("pricing.prompt", None, "0.1425"),
        price_multiplier=1,
        price_divisor=1,
    )
    assert added.new_display == "$0.1425"
    assert added.old_display == "null"


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
# 5. numeric fallback
# ---------------------------------------------------------------------------


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
        # Booleans in every form. `False -> True` is the one that matters:
        # under the pre-E2 ordering it was a `numeric` change off a zero
        # basis, so it reported pct_basis_zero=True.
        FieldChange("top_provider.is_moderated", False, True),
        FieldChange("top_provider.is_moderated", True, False),
        FieldChange("reasoning.default_enabled", 0, 1),
        FieldChange("top_provider.is_moderated", None, True),
        FieldChange("top_provider.is_moderated", True, None),
    )
    for field_change in cases:
        result = classify_change(field_change)
        assert result.pct_basis_zero is False, field_change.field_name
        assert result.pct_display is None, field_change.field_name


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
        FieldChange("top_provider.is_moderated", False, True),
        FieldChange("top_provider.is_moderated", None, True),
        FieldChange("reasoning.default_enabled", 1, 0),
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
# 6. boolean (E2) -- checked BEFORE price/count/numeric. See the module
# docstring: `bool` is an `int` subclass, so every branch guarded by
# `_both_numeric`/`_numeric_value` accepts a real bool pair, and for the whole
# pre-E2 life of this code the numeric branch swallowed boolean toggles.
# ---------------------------------------------------------------------------


def test_real_bool_pair_classifies_as_boolean_not_numeric():
    """E2, two-sided real-bool form. This is the regression test for the
    shipped defect where `top_provider.is_moderated: False -> True` rendered
    as `0 -> 1 (+1)` because `float(True)` succeeds and the numeric branch
    ran first."""
    result = classify_change(FieldChange("top_provider.is_moderated", False, True))
    assert result.kind == "boolean"
    assert result.direction == "up"
    assert result.semantic == "capability"
    assert result.old_display == "off"
    assert result.new_display == "on"
    assert result.delta_display == "enabled"


def test_known_boolean_int_pair_classifies_as_boolean_not_numeric():
    """Same defect, integer-coded form: `reasoning.default_enabled` holds 0/1
    rather than real bools, and is in KNOWN_BOOLEAN_FIELDS precisely so those
    values classify as a flag rather than a magnitude."""
    result = classify_change(FieldChange("reasoning.default_enabled", 0, 1))
    assert result.kind == "boolean"
    assert result.direction == "up"
    assert result.old_display == "off"
    assert result.new_display == "on"
    assert result.delta_display == "enabled"


def test_boolean_disable_classifies_as_boolean_with_no_percentage():
    """The `True -> False` direction, and the other half of the E2 defect: the
    numeric branch rendered this as `-1, down 100.0%`, percent-formatting a
    flag. A boolean must never carry a percentage in any form."""
    result = classify_change(FieldChange("top_provider.is_moderated", True, False))
    assert result.kind == "boolean"
    assert result.direction == "down"
    assert result.old_display == "on"
    assert result.new_display == "off"
    assert result.delta_display == "disabled"
    assert result.pct_display is None
    assert result.pct_basis_zero is False
    assert result.delta_abs is None


def test_boolean_wins_over_every_numeric_family_branch():
    """Branch-order guard. Each of these pairs is also `_both_numeric`, so a
    cascade that put price/count/numeric first would classify them as such --
    exactly the pre-E2 behavior."""
    for field_name in ("top_provider.is_moderated", "reasoning.mandatory", "deprecated"):
        assert classify_change(FieldChange(field_name, False, True)).kind == "boolean", field_name
    assert _both_numeric(False, True) is True
    assert _both_numeric(0, 1) is True


def test_known_boolean_restriction_still_excludes_genuine_numeric_fields():
    """The known-boolean set is a restriction, not a blanket 0/1 rule: a
    temperature of `1` is a magnitude. This must stay `numeric` with a
    percent even though its values look identical to a flag's."""
    result = classify_change(FieldChange("default_parameters.temperature", 0, 1))
    assert result.kind == "numeric"
    assert result.delta_display == "+1"


def test_boolean_one_sided_added_from_none_is_coverage():
    """Task 4 decision: a boolean appearing from nothing is a `boolean`
    change with `coverage` semantics, presented like every other one-sided
    change in the design -- absent side as an em dash, an `added` pill in the
    delta column, no percent. Previously this fell through to `scalar` and
    rendered the raw Python repr `null -> True`."""
    result = classify_change(FieldChange("top_provider.is_moderated", None, True))
    assert result.kind == "boolean"
    assert result.direction == "added"
    assert result.semantic == "coverage"
    assert result.old_display == "—"
    assert result.new_display == "on"
    assert result.delta_display == "added"
    assert result.pct_display is None


def test_boolean_one_sided_removed_to_none_is_coverage():
    """Mirrored direction."""
    result = classify_change(FieldChange("top_provider.is_moderated", False, None))
    assert result.kind == "boolean"
    assert result.direction == "removed"
    assert result.semantic == "coverage"
    assert result.old_display == "off"
    assert result.new_display == "—"
    assert result.delta_display == "removed"
    assert result.pct_display is None


def test_boolean_one_sided_covers_the_integer_coded_form():
    """One-sided known-boolean ints matter in production, not just real
    bools: `_flatten_one_sided_structure` in reporting.py turns a whole newly
    added `reasoning` object into leaves like this one."""
    result = classify_change(FieldChange("reasoning.default_enabled", None, 1))
    assert result.kind == "boolean"
    assert result.direction == "added"
    assert result.new_display == "on"


def test_classify_boolean_raises_for_non_boolean_value():
    """`_classify_boolean`'s precondition (each present side boolean-ish per
    `_bool_state`) is enforced: calling it directly with a non-boolean value
    (bypassing `_is_boolean_change`) would fabricate `direction="down"` and
    put the literal string `None` into a `str`-typed display field."""
    with pytest.raises(ValueError, match="default_parameters.top_p"):
        _classify_boolean(FieldChange("default_parameters.top_p", False, 0.9))
    with pytest.raises(ValueError, match="default_parameters.top_p"):
        _classify_boolean(FieldChange("default_parameters.top_p", None, 0.9))
    with pytest.raises(ValueError, match="expiration_date"):
        _classify_boolean(FieldChange("expiration_date", None, None))


def test_is_boolean_change_true_for_real_bool_pair():
    assert _is_boolean_change(FieldChange("top_provider.is_moderated", False, True)) is True


def test_is_boolean_change_true_for_known_boolean_int_pair():
    """Likewise for the known-boolean integer-coded case."""
    assert _is_boolean_change(FieldChange("reasoning.default_enabled", 0, 1)) is True
    assert _is_boolean_change(FieldChange("reasoning.mandatory", 1, 0)) is True
    assert _is_boolean_change(FieldChange("deprecated", 0, 1)) is True


def test_is_boolean_change_true_for_one_sided_boolean_ish_side():
    """Task 4 decision, predicate-level: only the PRESENT side has to be
    boolean-ish for a one-sided change."""
    assert _is_boolean_change(FieldChange("top_provider.is_moderated", None, True)) is True
    assert _is_boolean_change(FieldChange("top_provider.is_moderated", True, None)) is True
    assert _is_boolean_change(FieldChange("reasoning.default_enabled", None, 1)) is True


def test_is_boolean_change_false_for_one_sided_value_outside_the_known_set():
    """The known-boolean restriction applies to one-sided changes too, so a
    genuinely numeric leaf appearing from nothing is not turned into a flag.
    `architecture.tier_profiles[0].weight: null -> 1` (a real shape produced
    by reporting.py's structured flattening) must stay `scalar`."""
    assert _is_boolean_change(FieldChange("default_parameters.top_p", None, 1)) is False
    assert _is_boolean_change(FieldChange("architecture.tier_profiles[0].weight", None, 1)) is False
    assert classify_change(FieldChange("default_parameters.top_p", None, 1)).kind == "scalar"


def test_is_boolean_change_false_for_none_to_none():
    """`(None, None)` is a noop, not a one-sided boolean, even on a
    known-boolean field."""
    assert _is_boolean_change(FieldChange("top_provider.is_moderated", None, None)) is False
    assert classify_change(FieldChange("top_provider.is_moderated", None, None)).kind == "noop"


def test_is_boolean_change_false_for_mixed_bool_and_numeric_pair():
    """Finding 3 regression: `default_parameters.top_p` is not in
    KNOWN_BOOLEAN_FIELDS, so a `False`/`0.9` pair must never be treated as a
    boolean toggle just because `old_value` happens to be a real bool.
    Fixing Finding 2's `or` -> `and` already prevents this via
    `_is_boolean_change` (one side, `0.9`, is not `isinstance(..., bool)`),
    but the latent bug was one level down in `_bool_state`: it used to return
    "off" for ANY unrecognized value via a bare fallthrough, so if
    `_is_boolean_change` (or any future caller) ever again let a mixed-type
    pair through, `_classify_boolean` would render `0.9` as "off" and
    fabricate `direction="down"` -- a real change reported as a disable.
    `_bool_state` must return None instead. This matters more since E2 put
    the boolean branch first: a false positive here now shadows the numeric
    branch instead of being shadowed by it."""
    fc = FieldChange("default_parameters.top_p", False, 0.9)
    assert _is_boolean_change(fc) is False
    assert _bool_state(0.9) is None
    assert classify_change(fc).kind == "numeric"


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
# Field label registry (Task 5)
#
# `label` is the human-readable name shown in every non-JSON renderer;
# `field_path` stays the raw dotted path because tooltips and the JSON audit
# surface depend on it. Lookup order is exact full path -> leaf segment ->
# prettified leaf.
# ---------------------------------------------------------------------------


def test_exact_path_match_wins_over_leaf_suffix_match():
    """The path table is consulted first, and that ordering is load-bearing.

    The shipped registry no longer contains a name in both tables -- see
    `test_registry_tables_are_disjoint`, which requires exactly that -- so the
    ordering cannot be observed from the real data any more. It still has to
    hold: a leaf key claims every path ending in its segment, so the moment
    anyone adds a leaf entry that collides with an existing path entry, a
    leaf-first cascade would silently relabel the path-keyed field rather than
    fail. Inject the collision to pin the rule directly.
    """
    with (
        patch.dict(FIELD_PATH_LABELS, {"synthetic.parent.leaf_name": "From the path table"}),
        patch.dict(FIELD_LEAF_LABELS, {"leaf_name": "From the leaf table"}),
    ):
        # Precondition: both tables really do claim this name, with DIFFERENT
        # labels. Without this the assertion below could pass vacuously.
        assert (
            FIELD_PATH_LABELS["synthetic.parent.leaf_name"] != FIELD_LEAF_LABELS["leaf_name"]
        )

        assert resolve_field_label("synthetic.parent.leaf_name") == ("From the path table", None)
        result = classify_change(FieldChange("synthetic.parent.leaf_name", "a", "b"))
        assert result.label == "From the path table"

        # The leaf entry still governs any OTHER path ending in that segment.
        assert resolve_field_label("synthetic.other.leaf_name") == ("From the leaf table", None)

    # patch.dict restored both tables; no test after this one sees the collision.
    assert "synthetic.parent.leaf_name" not in FIELD_PATH_LABELS
    assert "leaf_name" not in FIELD_LEAF_LABELS


def test_context_length_and_top_provider_context_length_have_different_labels():
    """Two distinct fields that both occur in real data must read differently.

    The design's disambiguation note requires this explicitly. Both are now
    exact-path keys, so the distinction no longer depends on lookup order --
    each field states its own label at its own path, and deleting either
    produces a prettified fallback rather than the other field's label.
    """
    model_level = classify_change(FieldChange("context_length", 128000, 200000))
    provider_level = classify_change(FieldChange("top_provider.context_length", 128000, 200000))

    assert model_level.label == "Context length (model)"
    assert provider_level.label == "Context length"
    assert model_level.label != provider_level.label

    # Neither is reachable through the leaf table any more, so a nested
    # homonym cannot inherit either label -- see the nested-homonym tests.
    assert "context_length" not in FIELD_LEAF_LABELS


def test_leaf_suffix_match_resolves_a_dynamic_pricing_override_path():
    """Conditional pricing expands to a bracketed path; the leaf still labels it.

    `_pricing_override_path` (reporting.py) is what produces this shape:
    the condition is appended to the `pricing.overrides` segment, and
    `_diff_structured_values` then appends the money leaf. The bracketed
    condition must be stripped before lookup and carried as `qualifier`,
    and `field_path` must survive verbatim for the tooltip/audit surface.
    """
    path = "pricing.overrides[min_prompt_tokens=200000].completion"
    result = classify_change(FieldChange(path, "0.000001", "0.000002"))

    assert result.label == "Output"
    assert result.qualifier == "min_prompt_tokens=200000"
    assert result.field_path == path


def test_dynamic_path_qualifier_survives_a_condition_value_containing_a_dot():
    """The bracket stripper must not be a naive split on ".".

    `_pricing_override_path` interpolates the condition value through
    `_render_value`, so a non-integer threshold puts a "." INSIDE the
    brackets. A segment-wise splitter that tokenizes on "." first would tear
    `min_prompt_tokens=1.5` into two bogus segments and lose both the label
    and the qualifier.
    """
    path = "pricing.overrides[min_prompt_tokens=1.5].prompt"
    assert _split_field_path(path) == ("pricing.overrides.prompt", "min_prompt_tokens=1.5")

    result = classify_change(FieldChange(path, "0.000001", "0.000002"))
    assert result.label == "Input"
    assert result.qualifier == "min_prompt_tokens=1.5"
    assert result.field_path == path


def test_indexed_bracket_segments_are_also_stripped_and_carried():
    """`_flatten_one_sided_structure` emits `[index]` brackets, not just conditions.

    A second producer of bracketed segments exists in reporting.py, so the
    stripper cannot be specialised to `key=value` conditions.
    """
    path = "architecture.tier_profiles[0].weight"
    assert _split_field_path(path) == ("architecture.tier_profiles.weight", "0")

    result = classify_change(FieldChange(path, None, 1))
    assert result.label == "Weight"
    assert result.qualifier == "0"
    assert result.field_path == path


def test_unmatched_path_falls_back_to_prettified_leaf():
    """Neither table claims the name: split on "_" and sentence-case the leaf."""
    assert "max_prompt_images" not in FIELD_LEAF_LABELS
    assert "top_provider.max_prompt_images" not in FIELD_PATH_LABELS

    assert resolve_field_label("top_provider.max_prompt_images") == ("Max prompt images", None)
    result = classify_change(FieldChange("top_provider.max_prompt_images", 4, 8))
    assert result.label == "Max prompt images"
    assert result.field_path == "top_provider.max_prompt_images"


def test_prettify_leaf_sentence_cases_rather_than_title_cases():
    """Only the first word is capitalised; interior words stay lowercase."""
    assert _prettify_leaf("some_unregistered_metric") == "Some unregistered metric"
    assert _prettify_leaf("weight") == "Weight"
    # Not "Some Unregistered Metric" -- title-casing is a different rule and
    # would collide visually with the registry's own sentence-cased labels.
    assert _prettify_leaf("some_unregistered_metric") != "Some Unregistered Metric"


def test_field_path_is_preserved_verbatim_even_when_a_label_was_found():
    """A found label must never overwrite or normalise `field_path`.

    Tooltips render the dotted path and the JSON payload is an audit
    surface, so `field_path` is not allowed to become the pretty name.
    """
    # (path, old, new, expected label) -- one per lookup tier, plus a
    # bracketed path, and spread across `kind`s so that a single construction
    # site reverting to `field_path=label` cannot hide in an untested branch.
    cases = [
        ("top_provider.context_length", 1, 2, "Context length"),  # count
        ("pricing.prompt", 1, 2, "Input"),  # price
        ("hugging_face_id", "a", "b", "Hugging Face ID"),  # scalar
        ("supported_parameters", ["a"], ["a", "b"], "Supported parameters"),  # list
        ("reasoning.mandatory", False, True, "Reasoning required"),  # boolean
        ("default_parameters.top_p", 0.5, 0.9, "Top-P"),  # numeric
        ("knowledge_cutoff", "x", "x", "Knowledge cutoff"),  # noop
        ("pricing.overrides[min_prompt_tokens=200000].completion", 1, 2, "Output"),
        ("top_provider.max_prompt_images", 4, 8, "Max prompt images"),
    ]
    seen_kinds = set()
    for path, old, new, expected_label in cases:
        result = classify_change(FieldChange(path, old, new))
        seen_kinds.add(result.kind)
        assert result.field_path == path, path
        assert result.label == expected_label, path
        assert result.label != result.field_path, path
    # Every kind that can carry a label is actually exercised above.
    assert seen_kinds == {"count", "price", "scalar", "list", "boolean", "numeric", "noop"}


def test_registry_covers_every_seeded_field_name():
    """All 42 design-specified names resolve to their exact label.

    Spelled out as data rather than asserted against the dicts themselves so
    that a typo in a registry VALUE fails here, not just a missing key.
    """
    expected = {
        # Pricing
        "pricing.prompt": "Input",
        "pricing.completion": "Output",
        "pricing.input_cache_read": "Cache read",
        "pricing.input_cache_write": "Cache write",
        "pricing.input_cache_write_1h": "Cache write (1h)",
        "pricing.input_audio_cache": "Audio cache",
        "pricing.audio": "Audio",
        "pricing.audio_output": "Audio output",
        "pricing.image": "Image",
        "pricing.image_output": "Image output",
        "pricing.web_search": "Web search",
        "pricing.internal_reasoning": "Internal reasoning",
        "pricing.request": "Per request",
        "pricing.overrides": "Conditional pricing",
        # Context & limits
        "top_provider.context_length": "Context length",
        "context_length": "Context length (model)",
        "top_provider.max_completion_tokens": "Max output",
        # Capabilities
        "reasoning": "Reasoning",
        "reasoning.default_enabled": "Reasoning default",
        "reasoning.default_effort": "Reasoning effort",
        "reasoning.supported_efforts": "Supported efforts",
        "reasoning.mandatory": "Reasoning required",
        "supported_parameters": "Supported parameters",
        "supported_voices": "Supported voices",
        "architecture.modality": "Modality",
        "architecture.input_modalities": "Input modalities",
        "architecture.instruct_type": "Instruct type",
        # Metadata
        "top_provider.is_moderated": "Moderated",
        "knowledge_cutoff": "Knowledge cutoff",
        "expiration_date": "Expiration date",
        "description": "Description",
        "name": "Name",
        "created": "Created",
        "links": "Links",
        "hugging_face_id": "Hugging Face ID",
        # Default parameters
        "default_parameters": "Default parameters",
        "default_parameters.frequency_penalty": "Frequency penalty",
        "default_parameters.presence_penalty": "Presence penalty",
        "default_parameters.repetition_penalty": "Repetition penalty",
        "default_parameters.temperature": "Temperature",
        "default_parameters.top_k": "Top-K",
        "default_parameters.top_p": "Top-P",
    }
    # Both counts are DERIVED from `expected`, never spelled as literals.
    # Adding a label must be a one-line edit to the registry plus a one-line
    # edit here; a hard-coded total made it four lines and invited the count
    # and the data to drift apart.
    assert len(FIELD_PATH_LABELS) + len(FIELD_LEAF_LABELS) == len(expected)

    for path, label in expected.items():
        assert resolve_field_label(path) == (label, None), path


def test_registry_tables_are_disjoint():
    """No name may appear in both tables. The overlap allowance is gone.

    A leaf key claims EVERY path in the product ending in that segment, so it
    is a last resort reserved for fields whose parent is dynamic. Every other
    name is keyed by its exact path. Under that rule an overlap can only be
    one of two mistakes: a redundant duplicate, or a leaf entry silently
    shadowed by a path entry for one location while still mislabelling every
    other location that ends in the same segment. Both are defects, so the
    allowed overlap set is empty rather than a curated exception list.
    """
    overlapping = {
        path for path in FIELD_PATH_LABELS if path.rsplit(".", 1)[-1] in FIELD_LEAF_LABELS
    }
    assert overlapping == set()


def test_leaf_table_holds_only_names_with_a_dynamic_parent():
    """The leaf table's membership rule, asserted rather than documented.

    Two producers in reporting.py put a field under a parent that cannot be
    spelled as a fixed path: `_pricing_override_path` relocates the money
    leaves under `pricing.overrides[<condition>]`, and the payload nests the
    six tuning parameters under `default_parameters`. Those are the only
    names entitled to a leaf key. Anything else added here is a claim over
    unrelated nested homonyms, which is the defect this list exists to stop.
    """
    money_leaves = {
        "prompt",
        "completion",
        "input_cache_read",
        "input_cache_write",
        "input_cache_write_1h",
        "input_audio_cache",
        "audio_output",
        "image_output",
        "web_search",
        "internal_reasoning",
    }
    default_parameter_leaves = {
        "frequency_penalty",
        "presence_penalty",
        "repetition_penalty",
        "temperature",
        "top_k",
        "top_p",
    }
    assert set(FIELD_LEAF_LABELS) == money_leaves | default_parameter_leaves


def test_nested_homonym_does_not_inherit_the_top_level_context_length_label():
    """`...[0].context_length` is a TIER's limit, not the model's.

    This is the visible half of the defect. While `context_length` was
    leaf-keyed, any path ending in that segment inherited the model-level
    label including its "(model)" disambiguator, so a tier profile's own
    context limit rendered as `Context length (model) (#0)` -- a row that
    names the wrong field and asserts a distinction that does not apply to it.
    """
    nested = "architecture.tier_profiles[0].context_length"

    label, qualifier = resolve_field_label(nested)
    assert label == "Context length"
    assert qualifier == "0"
    assert format_qualified_label(label, qualifier) == "Context length (#0)"

    # The model-level field keeps its own label; only the homonym moved.
    assert resolve_field_label("context_length") == ("Context length (model)", None)


def test_nested_homonyms_no_longer_inherit_a_top_level_label():
    """The cases where leaf-keying was VISIBLY mislabelling nested fields.

    Each of these paths ends in a segment that used to be leaf-keyed, so each
    inherited the top-level field's label wherever it appeared. Now that the
    top-level fields are path-keyed, the nested rows fall through to the
    prettified-leaf fallback and describe themselves.

    `hugging_face_id` is included deliberately even though the fallback spells
    it less prettily than the registry did ("Hugging face id" vs "Hugging Face
    ID"). That is the correct outcome: a nested field the registry does not
    know about should read as an unregistered field, not borrow the casing of
    an unrelated one.
    """
    was_inherited = {
        # nested path: (label it used to inherit, label it resolves to now)
        "architecture.tier_profiles[0].context_length": (
            "Context length (model)",
            "Context length",
        ),
        "provider_metadata.hugging_face_id": ("Hugging Face ID", "Hugging face id"),
        "provider_metadata.request": ("Per request", "Request"),
        "provider_metadata.overrides": ("Conditional pricing", "Overrides"),
    }
    for path, (inherited, own) in was_inherited.items():
        assert inherited != own, path  # precondition: the case is observable
        label, _ = resolve_field_label(path)
        assert label == own, path
        assert label != inherited, path

    # The top-level fields themselves are untouched -- only the homonyms moved.
    assert resolve_field_label("context_length") == ("Context length (model)", None)
    assert resolve_field_label("hugging_face_id") == ("Hugging Face ID", None)
    assert resolve_field_label("pricing.request") == ("Per request", None)
    assert resolve_field_label("pricing.overrides") == ("Conditional pricing", None)


def test_nested_homonyms_whose_label_is_unchanged_are_still_severed():
    """Most of the moved names read the SAME either way. Stated, not hidden.

    `_prettify_leaf("name")` is "Name" -- exactly what the registry holds for
    the model's own `name` -- so `architecture.tier_profiles[0].name` renders
    `Name (#0)` both before and after this change and NO output golden can
    tell the two regimes apart. Ten of the fourteen names moved out of the
    leaf table are like this.

    That does not make the move cosmetic. Under leaf keying the coincidence
    was load-bearing: renaming the top-level field silently renamed every
    nested homonym with it. Under path keying the two are independent, which
    is what this asserts -- re-label the top-level fields and require the
    homonyms to stay put. The structural counterpart is
    `test_leaf_table_holds_only_names_with_a_dynamic_parent`.
    """
    homonyms = {
        "architecture.tier_profiles[0].name": "Name",
        "architecture.tier_profiles[0].description": "Description",
        "architecture.tier_profiles[0].created": "Created",
        "provider_metadata.links": "Links",
    }
    for path, expected in homonyms.items():
        assert resolve_field_label(path)[0] == expected, path

    renamed = {
        "name": "Model name",
        "description": "Model description",
        "created": "First seen",
        "links": "Model links",
    }
    # Precondition: every one of these really is a live top-level path entry,
    # so the patch below changes something rather than adding dead keys.
    assert set(renamed) <= set(FIELD_PATH_LABELS)

    with patch.dict(FIELD_PATH_LABELS, renamed):
        for path, expected in homonyms.items():
            assert resolve_field_label(path)[0] == expected, path
        # ...while the top-level fields themselves DID move, proving the patch
        # was live and the assertions above are not vacuous.
        for field, new_label in renamed.items():
            assert resolve_field_label(field)[0] == new_label


def test_registry_labels_are_non_empty_and_start_uppercase():
    for table_name, table in (("FIELD_PATH_LABELS", FIELD_PATH_LABELS), ("FIELD_LEAF_LABELS", FIELD_LEAF_LABELS)):
        for key, label in table.items():
            assert label, f"{table_name}[{key!r}] is empty"
            assert label[0].isupper(), f"{table_name}[{key!r}] = {label!r} is not capitalised"


def test_every_classify_branch_populates_label_and_qualifier():
    """Label resolution must reach every construction site, not just some.

    `classify_change` builds a RenderedChange at ~10 sites across six
    helpers. A site left on the old `label=field_path` spelling would leak a
    raw dotted path into one specific kind of row -- the sort of gap that
    only shows up in production on an uncommon change shape.
    """
    cases = [
        # (FieldChange, expected kind)
        (FieldChange("pricing.prompt", "0.000002", "0.000002"), "noop"),
        (FieldChange("supported_parameters", ["tools"], ["tools", "seed"]), "list"),
        (FieldChange("reasoning.mandatory", False, True), "boolean"),
        (FieldChange("reasoning.mandatory", None, True), "boolean"),
        (FieldChange("pricing.prompt", "0.000001", "0.000002"), "price"),
        (FieldChange("pricing.prompt", None, "0.000002"), "price"),
        (FieldChange("context_length", 128000, 200000), "count"),
        (FieldChange("context_length", None, 200000), "count"),
        (FieldChange("default_parameters.temperature", 0.7, 0.9), "numeric"),
        (FieldChange("knowledge_cutoff", "2024-01", "2025-01"), "scalar"),
    ]
    for field_change, expected_kind in cases:
        result = classify_change(field_change)
        assert result.kind == expected_kind, field_change.field_name
        expected_label, expected_qualifier = resolve_field_label(field_change.field_name)
        assert result.label == expected_label, (field_change.field_name, expected_kind)
        assert result.qualifier == expected_qualifier, (field_change.field_name, expected_kind)
        # And the raw path is still intact on every branch.
        assert result.field_path == field_change.field_name


def test_bracketed_path_labels_reach_every_classify_branch():
    """The same coverage check, but for paths carrying a qualifier."""
    prefix = "pricing.overrides[min_prompt_tokens=200000]"
    cases = [
        (FieldChange(f"{prefix}.completion", "0.000002", "0.000002"), "noop", "Output"),
        (FieldChange(f"{prefix}.completion", "0.000001", "0.000002"), "price", "Output"),
        (FieldChange(f"{prefix}.completion", None, "0.000002"), "price", "Output"),
    ]
    for field_change, expected_kind, expected_label in cases:
        result = classify_change(field_change)
        assert result.kind == expected_kind, field_change.field_name
        assert result.label == expected_label
        assert result.qualifier == "min_prompt_tokens=200000"
        assert result.field_path == field_change.field_name


def test_unbracketed_paths_have_no_qualifier():
    """`qualifier` is None unless the path actually carried a condition."""
    for path in ("pricing.prompt", "context_length", "top_provider.max_prompt_images"):
        assert _split_field_path(path) == (path, None)
        assert classify_change(FieldChange(path, 1, 2)).qualifier is None


# ---------------------------------------------------------------------------
# display_label: the label a renderer actually prints.
#
# `label` is the registry lookup with the bracketed segment REMOVED, so it does
# not identify a row on its own. Every non-JSON renderer reads `display_label`.
# ---------------------------------------------------------------------------


def test_display_label_is_the_bare_label_when_there_is_no_qualifier():
    """No brackets in the path means no parenthetical -- not an empty one."""
    result = classify_change(FieldChange("pricing.prompt", "0.000001", "0.000002"))
    assert result.qualifier is None
    assert result.display_label == "Input"
    assert result.display_label == result.label


def test_display_label_distinguishes_a_base_price_from_a_conditional_tier():
    """THE regression. `label` alone collapses two different fields into one row.

    `pricing.prompt` and `pricing.overrides[...].prompt` are different prices
    on the same model: the base rate and a high-context tier. The registry
    labels both `Input`, by design -- the leaf names the field wherever it
    appears -- so the QUALIFIER is the only thing left that tells the two rows
    apart. A renderer printing `label` shows a reader two identical `Input`
    rows and no way to know which tier moved.
    """
    base = classify_change(FieldChange("pricing.prompt", "0.000001", "0.000002"))
    tier = classify_change(
        FieldChange("pricing.overrides[min_prompt_tokens=200000].prompt", "0.000004", "0.000005")
    )

    assert base.label == tier.label == "Input"
    assert base.display_label != tier.display_label
    assert base.display_label == "Input"
    assert tier.display_label == "Input (min_prompt_tokens=200000)"


def test_condition_qualifier_renders_literally():
    """The design's spelling: a parenthetical carrying the condition verbatim.

    Turning `min_prompt_tokens=200000` into prose ("above 200K prompt tokens")
    is explicitly out of scope, so the rendered text must be the raw predicate.
    """
    assert format_qualified_label("Output", "min_prompt_tokens=200000") == (
        "Output (min_prompt_tokens=200000)"
    )
    assert format_qualified_label("Input", "utc_start=30,utc_end=1630") == (
        "Input (utc_start=30,utc_end=1630)"
    )


def test_index_qualifier_renders_as_an_ordinal():
    """DECISION: a list index gets "#", a condition does not.

    The two producers are told apart exactly, not by guesswork:
    `_pricing_override_path` builds every segment as `key=value`, so a segment
    of nothing but decimal digits cannot have come from it, while
    `_flatten_one_sided_structure` interpolates `enumerate` output and emits
    nothing else.

    They are treated differently because a bare `Weight (0)` sits one column
    away from the old/new value columns and reads as a value -- reintroducing,
    in a new spelling, exactly the ambiguity the qualifier exists to remove.
    `Weight (#0)` reads as "the zeroth member".
    """
    assert format_qualified_label("Weight", "0") == "Weight (#0)"
    assert format_qualified_label("Name", "11") == "Name (#11)"

    result = classify_change(FieldChange("architecture.tier_profiles[0].weight", None, 1))
    assert result.qualifier == "0", "the stored qualifier stays the literal segment"
    assert result.display_label == "Weight (#0)"


def test_two_list_members_contributing_the_same_leaf_stay_distinguishable():
    """The index form has the same collapse failure mode as the condition form."""
    first = classify_change(FieldChange("new_payload.tiers[0].label", None, "small"))
    second = classify_change(FieldChange("new_payload.tiers[1].label", None, "large"))

    assert first.label == second.label == "Label"
    assert first.display_label == "Label (#0)"
    assert second.display_label == "Label (#1)"
    assert first.display_label != second.display_label


def test_each_bracket_group_is_formatted_independently():
    """A nested path carries both producers' segments; each keeps its own form.

    `_split_field_path` joins bracket groups with ", ", and the formatter must
    decide per group -- not once for the joined string -- or a mixed path gets
    one rule applied to both segments.
    """
    path = "pricing.overrides[min_prompt_tokens=200000].tiers[0].prompt"
    result = classify_change(FieldChange(path, "0.000001", "0.000002"))

    assert result.qualifier == "min_prompt_tokens=200000, 0"
    assert result.display_label == "Input (min_prompt_tokens=200000, #0)"


def test_display_label_is_derived_not_stored():
    """It must not become an 11th thing every construction site has to set.

    `classify_change` builds a RenderedChange at ~10 sites. A stored display
    string would have to be kept in step at every one of them; a property
    cannot fall out of step with the `label`/`qualifier` it reads.
    """
    assert "display_label" not in {f.name for f in dataclasses.fields(RenderedChange)}
    assert isinstance(RenderedChange.display_label, property)


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
