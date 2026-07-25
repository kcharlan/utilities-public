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
    _is_boolean_change,
    classify_change,
)
from model_sentinel.models import FieldChange
from model_sentinel.reporting import (
    _both_numeric,
    _classify_field,
    _fmt_int,
    _fmt_price_per_m,
    _is_count_field,
    _is_price_amount_field,
    _normalize_price,
    _numeric_value,
    _pct_change,
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
# 6. boolean (reachable, under this ordering, only for a bool-vs-None change)
# ---------------------------------------------------------------------------


def test_boolean_one_sided_added_from_none():
    result = classify_change(FieldChange("top_provider.is_moderated", None, True))
    assert result.kind == "boolean"
    assert result.direction == "up"
    assert result.semantic == "capability"
    assert result.old_display == "off"
    assert result.new_display == "on"
    assert result.delta_display == "enabled"
    assert result.pct_display is None
    assert result.delta_abs is None


def test_boolean_one_sided_removed_to_none():
    result = classify_change(FieldChange("top_provider.is_moderated", True, None))
    assert result.kind == "boolean"
    assert result.direction == "down"
    assert result.semantic == "capability"
    assert result.old_display == "on"
    assert result.new_display == "off"
    assert result.delta_display == "disabled"


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


# ---------------------------------------------------------------------------
# Step 1 in the brief: label/qualifier are the raw field_path in this task.
# ---------------------------------------------------------------------------


def test_label_and_qualifier_are_not_yet_populated_from_a_registry():
    result = classify_change(FieldChange("pricing.prompt", "0.000001", "0.000002"))
    assert result.field_path == "pricing.prompt"
    assert result.label == "pricing.prompt"
    assert result.qualifier is None


# ---------------------------------------------------------------------------
# Re-export shims: existing reporting.py call sites keep working unchanged.
# ---------------------------------------------------------------------------


def test_reporting_module_reexports_shared_primitives():
    assert _classify_field("pricing.prompt") == "Pricing"
    assert _both_numeric(1, 2) is True
    assert _numeric_value("3.5") == 3.5
    assert _is_price_amount_field("pricing.prompt") is True
    assert _is_count_field("context_length") is True
    assert _fmt_int(1024.0) == "1,024"
    assert _pct_change(10, 20) == "↑ 100.0%"
    assert _fmt_price_per_m(2.0) == "$2.00"
    assert _normalize_price(0.000002, 1_000_000, 1) == 2.0
