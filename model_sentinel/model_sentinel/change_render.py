"""Format-agnostic change classification for field-level diffs.

This module classifies a single `FieldChange` into a `RenderedChange`: a
structured description of what kind of change it is (price, count, boolean,
list, ...), which direction it moved, and what it means semantically (cost,
capacity, capability, coverage, neutral). Renderers (text/markdown/html/json)
consume `RenderedChange` instead of re-deriving this logic themselves.

TRANSITIONAL BRANCH ORDER (read before touching the cascade):

`classify_change` currently checks price/count/numeric *before* boolean. This
looks backwards relative to the final design -- boolean should normally win
over numeric for a real bool pair -- but it is deliberate for now.

The production renderer this module is being extracted from
(`reporting.py::_render_smart_change_text`) calls `_both_numeric()`, and
`_both_numeric()` calls `float()` on its arguments. Since Python's `bool` is a
subclass of `int`, `float(True)` succeeds, so a real `bool` pair has *always*
been caught by the numeric branch in production -- the dedicated boolean
branch in the old renderer is effectively dead code today. `is_moderated:
False -> True` currently renders as `0 -> 1 (+1)`, not as a boolean toggle,
and that behavior is pinned by the Task 1 characterization goldens.

Task 3 wires this module into the renderers and must be provably
behavior-neutral against those goldens, so `classify_change` here reproduces
today's effective ordering: numeric/price/count take precedence over boolean
for any pair `_both_numeric` currently accepts (including real `bool` pairs
and known-boolean integer-coded fields, since `0`/`1` are just as
`float()`-able as `True`/`False`). The `boolean` branch and the known-boolean
field set are fully implemented and unit-tested here, but under this ordering
they are only reachable for a bool-vs-`None` (one-sided) change -- the
two-sided case is intentionally still classified as `numeric`.

Task 4 (E2) is where the boolean branch is promoted ahead of numeric/price/
count. That reordering is the deliberate, visible fix for the E2 defect, and
it is expected to change the characterization goldens for boolean fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .models import FieldChange

# Fields whose recorded values are 0/1 (not real Python bool) but are
# semantically flags, not magnitudes. Seeded from the boolean-valued fields
# observed in the history database (`top_provider.is_moderated`,
# `reasoning.default_enabled`, `reasoning.mandatory`) plus `deprecated`, which
# is not observed in any recorded change but appears in
# `DEFAULT_REPORT_SHOW_FIELDS` (reporting.py) and is included as a forward
# guard.
#
# This set is a restriction, not a convenience: `default_parameters.top_p`,
# `default_parameters.temperature`, and `default_parameters.repetition_penalty`
# also hold 0/1 values in the history database, but they are genuinely
# numeric (a temperature of `1` is a magnitude, not a flag) and must never be
# treated as boolean.
KNOWN_BOOLEAN_FIELDS = frozenset(
    {
        "top_provider.is_moderated",
        "reasoning.default_enabled",
        "reasoning.mandatory",
        "deprecated",
    }
)


@dataclass(frozen=True)
class RenderedChange:
    kind: Literal["price", "count", "numeric", "boolean", "list", "scalar", "noop"]
    field_path: str
    label: str
    qualifier: str | None
    old_display: str
    new_display: str
    old_raw: str | None
    new_raw: str | None
    unit: str | None
    delta_display: str | None
    # Sorting only -- never format this for display.
    delta_abs: float | None
    pct_display: str | None
    direction: Literal["up", "down", "added", "removed", "none"]
    semantic: Literal["cost", "capacity", "capability", "coverage", "neutral"]
    list_added: tuple[str, ...]
    list_removed: tuple[str, ...]


# ---------------------------------------------------------------------------
# Shared primitives, moved verbatim from reporting.py (behavior-preserving).
# reporting.py re-exports these so existing call sites keep working unchanged.
# ---------------------------------------------------------------------------


def _classify_field(field_name: str) -> str:
    lower = field_name.lower()
    if any(p in lower for p in ("pricing.", "price", "cost", "_rate")):
        return "Pricing"
    if any(p in lower for p in ("context_length", "context_window", "max_completion", "max_tokens", "max_output")):
        return "Context & Limits"
    if "supported_parameters" in lower or lower == "parameters":
        return "Parameters"
    if any(p in lower for p in ("vision", "audio", "image", "tool", "reasoning", "structured", "modality")):
        return "Capabilities"
    if lower.startswith("benchmarks.") or lower == "benchmarks":
        return "Benchmarks"
    return "Other"


def _both_numeric(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    try:
        float(a)
        float(b)
        return True
    except (TypeError, ValueError):
        return False


def _numeric_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_price_amount_field(field_name: str) -> bool:
    """Distinguish monetary leaves from thresholds nested under pricing."""
    if _classify_field(field_name) != "Pricing":
        return False
    leaf = field_name.rsplit(".", 1)[-1]
    leaf = leaf.split("[", 1)[0]
    return "token" not in leaf.lower()


def _is_count_field(field_name: str) -> bool:
    lower = field_name.lower()
    leaf = lower.rsplit(".", 1)[-1].split("[", 1)[0]
    return "token" in leaf or _classify_field(field_name) == "Context & Limits"


def _fmt_int(value: float) -> str:
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _pct_change(old: float, new: float) -> str:
    if old == 0:
        return ""
    pct = ((new - old) / abs(old)) * 100
    arrow = "↑" if pct > 0 else "↓"
    return f"{arrow} {abs(pct):.1f}%"


def _fmt_price_per_m(value: float) -> str:
    if value == 0:
        return "free"
    abs_val = abs(value)
    if abs_val >= 1:
        formatted = f"{value:.2f}"
    elif abs_val >= 0.01:
        formatted = f"{value:.4f}"
    else:
        formatted = f"{value:.6f}"
    # Strip trailing zeros but keep at least 2 decimal places
    parts = formatted.split(".")
    decimals = parts[1].rstrip("0")
    if len(decimals) < 2:
        decimals = decimals.ljust(2, "0")
    return f"${parts[0]}.{decimals}"


def _normalize_price(raw_value: float, multiplier: int, divisor: int) -> float:
    return (raw_value * multiplier) / divisor


# ---------------------------------------------------------------------------
# Display helpers used only by classify_change and its per-kind helpers.
# ---------------------------------------------------------------------------


def _raw_value(value: Any) -> str | None:
    return None if value is None else str(value)


def _scalar_display(value: Any) -> str:
    return "null" if value is None else str(value)


def _is_integer_like(value: Any) -> bool:
    """True if value is a non-bool 0/1 int or float (bool is handled separately)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value in (0, 1)
    if isinstance(value, float):
        return value in (0.0, 1.0)
    return False


def _is_boolean_change(field_change: FieldChange) -> bool:
    """True if this change should be treated as a boolean toggle.

    Either value is a real `bool`, or the field is in `KNOWN_BOOLEAN_FIELDS`
    and both values are integer-like 0/1. See the module docstring: under the
    current transitional branch order, the `KNOWN_BOOLEAN_FIELDS` condition is
    only reachable through this helper directly (in tests), not end-to-end
    through `classify_change`, because any pair satisfying it is also
    `_both_numeric` and gets caught by the numeric branch first.
    """
    old_value, new_value = field_change.old_value, field_change.new_value
    if isinstance(old_value, bool) or isinstance(new_value, bool):
        return True
    if field_change.field_name in KNOWN_BOOLEAN_FIELDS:
        return _is_integer_like(old_value) and _is_integer_like(new_value)
    return False


def _bool_state(value: Any) -> Literal["on", "off"]:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)):
        return "on" if value == 1 else "off"
    return "off"


# ---------------------------------------------------------------------------
# Per-kind classification helpers.
# ---------------------------------------------------------------------------


def _classify_boolean(field_change: FieldChange) -> RenderedChange:
    old_value, new_value = field_change.old_value, field_change.new_value
    new_state = _bool_state(new_value)
    direction: Literal["up", "down"] = "up" if new_state == "on" else "down"
    delta_display = "enabled" if direction == "up" else "disabled"
    return RenderedChange(
        kind="boolean",
        field_path=field_change.field_name,
        label=field_change.field_name,
        qualifier=None,
        old_display=_bool_state(old_value),
        new_display=new_state,
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit=None,
        delta_display=delta_display,
        delta_abs=None,
        pct_display=None,
        direction=direction,
        semantic="capability",
        list_added=(),
        list_removed=(),
    )


def _classify_price(
    field_change: FieldChange,
    old_numeric: float | None,
    new_numeric: float | None,
    price_multiplier: int,
    price_divisor: int,
) -> RenderedChange:
    field_path = field_change.field_name
    old_value, new_value = field_change.old_value, field_change.new_value

    if old_numeric is not None and new_numeric is not None:
        norm_old = _normalize_price(old_numeric, price_multiplier, price_divisor)
        norm_new = _normalize_price(new_numeric, price_multiplier, price_divisor)
        delta_norm = norm_new - norm_old
        direction: Literal["up", "down", "none"]
        if delta_norm > 0:
            direction = "up"
        elif delta_norm < 0:
            direction = "down"
        else:
            direction = "none"
        sign = "+" if delta_norm > 0 else ("-" if delta_norm < 0 else "")
        delta_display = f"{sign}{_fmt_price_per_m(abs(delta_norm))}"
        pct_display = _pct_change(old_numeric, new_numeric) or None
        return RenderedChange(
            kind="price",
            field_path=field_path,
            label=field_path,
            qualifier=None,
            old_display=_fmt_price_per_m(norm_old),
            new_display=_fmt_price_per_m(norm_new),
            old_raw=_raw_value(old_value),
            new_raw=_raw_value(new_value),
            unit="/1M",
            delta_display=delta_display,
            delta_abs=delta_norm,
            pct_display=pct_display,
            direction=direction,
            semantic="cost",
            list_added=(),
            list_removed=(),
        )

    if old_numeric is None:
        one_sided_direction: Literal["added", "removed"] = "added"
        old_display = "null"
        new_display = _fmt_price_per_m(_normalize_price(new_numeric, price_multiplier, price_divisor))
    else:
        one_sided_direction = "removed"
        old_display = _fmt_price_per_m(_normalize_price(old_numeric, price_multiplier, price_divisor))
        new_display = "null"

    return RenderedChange(
        kind="price",
        field_path=field_path,
        label=field_path,
        qualifier=None,
        old_display=old_display,
        new_display=new_display,
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit="/1M",
        delta_display=None,
        delta_abs=None,
        pct_display=None,
        direction=one_sided_direction,
        semantic="coverage",
        list_added=(),
        list_removed=(),
    )


def _classify_count(
    field_change: FieldChange,
    old_numeric: float | None,
    new_numeric: float | None,
) -> RenderedChange:
    field_path = field_change.field_name
    old_value, new_value = field_change.old_value, field_change.new_value

    if old_numeric is not None and new_numeric is not None:
        delta = new_numeric - old_numeric
        direction: Literal["up", "down", "none"]
        if delta > 0:
            direction = "up"
        elif delta < 0:
            direction = "down"
        else:
            direction = "none"
        sign = "+" if delta > 0 else ("-" if delta < 0 else "")
        delta_display = f"{sign}{_fmt_int(abs(delta))}"
        pct_display = _pct_change(old_numeric, new_numeric) or None
        return RenderedChange(
            kind="count",
            field_path=field_path,
            label=field_path,
            qualifier=None,
            old_display=_fmt_int(old_numeric),
            new_display=_fmt_int(new_numeric),
            old_raw=_raw_value(old_value),
            new_raw=_raw_value(new_value),
            unit="tok",
            delta_display=delta_display,
            delta_abs=delta,
            pct_display=pct_display,
            direction=direction,
            semantic="capacity",
            list_added=(),
            list_removed=(),
        )

    if old_numeric is None:
        one_sided_direction: Literal["added", "removed"] = "added"
        old_display = "null"
        new_display = _fmt_int(new_numeric)
    else:
        one_sided_direction = "removed"
        old_display = _fmt_int(old_numeric)
        new_display = "null"

    return RenderedChange(
        kind="count",
        field_path=field_path,
        label=field_path,
        qualifier=None,
        old_display=old_display,
        new_display=new_display,
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit="tok",
        delta_display=None,
        delta_abs=None,
        pct_display=None,
        direction=one_sided_direction,
        semantic="coverage",
        list_added=(),
        list_removed=(),
    )


def _classify_numeric(field_change: FieldChange) -> RenderedChange:
    field_path = field_change.field_name
    old_value, new_value = field_change.old_value, field_change.new_value
    old_f = float(old_value)
    new_f = float(new_value)
    delta = new_f - old_f
    direction: Literal["up", "down", "none"]
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "none"
    sign = "+" if delta > 0 else ("-" if delta < 0 else "")
    delta_display = f"{sign}{_fmt_int(abs(delta))}"
    pct_display = _pct_change(old_f, new_f) or None
    return RenderedChange(
        kind="numeric",
        field_path=field_path,
        label=field_path,
        qualifier=None,
        old_display=_fmt_int(old_f),
        new_display=_fmt_int(new_f),
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit=None,
        delta_display=delta_display,
        delta_abs=delta,
        pct_display=pct_display,
        direction=direction,
        semantic="neutral",
        list_added=(),
        list_removed=(),
    )


def classify_change(
    field_change: FieldChange,
    *,
    price_multiplier: int = 1,
    price_divisor: int = 1,
) -> RenderedChange:
    """Classify a single field change into a structured `RenderedChange`.

    Branch order (see module docstring for why boolean sits after numeric):
    noop -> list -> price -> count -> numeric -> boolean -> scalar.
    """
    field_path = field_change.field_name
    old_value, new_value = field_change.old_value, field_change.new_value

    # 1. noop
    if (old_value is None and new_value is None) or old_value == new_value:
        return RenderedChange(
            kind="noop",
            field_path=field_path,
            label=field_path,
            qualifier=None,
            old_display=_scalar_display(old_value),
            new_display=_scalar_display(new_value),
            old_raw=_raw_value(old_value),
            new_raw=_raw_value(new_value),
            unit=None,
            delta_display=None,
            delta_abs=None,
            pct_display=None,
            direction="none",
            semantic="neutral",
            list_added=(),
            list_removed=(),
        )

    # 2. list
    if isinstance(old_value, list) and isinstance(new_value, list):
        old_set = {str(x) for x in old_value}
        new_set = {str(x) for x in new_value}
        added = tuple(sorted(new_set - old_set))
        removed = tuple(sorted(old_set - new_set))
        return RenderedChange(
            kind="list",
            field_path=field_path,
            label=field_path,
            qualifier=None,
            old_display=_fmt_int(len(old_value)),
            new_display=_fmt_int(len(new_value)),
            old_raw=_raw_value(old_value),
            new_raw=_raw_value(new_value),
            unit="items",
            delta_display=None,
            delta_abs=None,
            pct_display=None,
            direction="none",
            semantic="capability",
            list_added=added,
            list_removed=removed,
        )

    old_numeric = _numeric_value(old_value)
    new_numeric = _numeric_value(new_value)

    # 3. price -- guard preserved exactly from reporting.py's current
    # _render_smart_change_text (permits one-sided None, rejects non-numeric
    # strings).
    if (
        _is_price_amount_field(field_path)
        and (old_numeric is not None or new_numeric is not None)
        and (old_value is None or old_numeric is not None)
        and (new_value is None or new_numeric is not None)
    ):
        return _classify_price(field_change, old_numeric, new_numeric, price_multiplier, price_divisor)

    # 4. count -- same numeric-shape guard as price (permits one-sided None,
    # rejects non-numeric strings). Unlike reporting.py's text-formatting
    # guard, this is not restricted to the one-sided case: a two-sided count
    # change (e.g. context_length up/down) is classified as `count` here too.
    if (
        _is_count_field(field_path)
        and (old_numeric is not None or new_numeric is not None)
        and (old_value is None or old_numeric is not None)
        and (new_value is None or new_numeric is not None)
    ):
        return _classify_count(field_change, old_numeric, new_numeric)

    # 5. numeric -- both numeric, no category match. Transitional ordering:
    # this also catches real bool pairs and known-boolean integer-coded
    # pairs, matching today's production behavior (see module docstring).
    if _both_numeric(old_value, new_value):
        return _classify_numeric(field_change)

    # 6. boolean -- only reachable here for a bool-vs-None (one-sided) change
    # under the current transitional ordering (see module docstring).
    if _is_boolean_change(field_change):
        return _classify_boolean(field_change)

    # 7. scalar fallback
    return RenderedChange(
        kind="scalar",
        field_path=field_path,
        label=field_path,
        qualifier=None,
        old_display=_scalar_display(old_value),
        new_display=_scalar_display(new_value),
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit=None,
        delta_display=None,
        delta_abs=None,
        pct_display=None,
        direction="none",
        semantic="neutral",
        list_added=(),
        list_removed=(),
    )
