"""Format-agnostic change classification for field-level diffs.

This module classifies a single `FieldChange` into a `RenderedChange`: a
structured description of what kind of change it is (price, count, boolean,
list, ...), which direction it moved, and what it means semantically (cost,
capacity, capability, coverage, neutral). Renderers (text/markdown/html/json)
consume `RenderedChange` instead of re-deriving this logic themselves.

BRANCH ORDER (read before touching the cascade):

`classify_change` checks `boolean` BEFORE price/count/numeric. That ordering
is the E2 fix and must not be reshuffled.

Python's `bool` is a subclass of `int`, so `float(True)` succeeds and every
guard built on `_both_numeric`/`_numeric_value` accepts a real `bool` pair.
For the whole pre-E2 life of this code the numeric branch therefore swallowed
boolean toggles and the dedicated boolean branch in the renderer it replaced
(`reporting.py::_render_smart_change_text`) was dead code:
`top_provider.is_moderated: False -> True` shipped as `0 -> 1 (+1)`, and
`True -> False` shipped as `-1, down 100.0%` -- a flag percent-formatted as if
it were a magnitude. Integer-coded flags (`reasoning.default_enabled: 0 -> 1`)
had the same fate, with the added insult that `_pct_change` returns `""` for a
zero basis, so the HTML delta cell came out blank.

Putting `boolean` first is what makes the branch reachable. Its correctness
therefore rests entirely on `_is_boolean_change` being narrow: a false
positive there now *shadows* the numeric branch rather than being shadowed by
it, so a genuinely numeric field must never satisfy it. That is why
KNOWN_BOOLEAN_FIELDS is a restriction rather than a convenience, and why
`_bool_state` returns `None` for anything that is not a real bool or an
integer-coded 0/1.

ONE-SIDED BOOLEANS (Task 4 decision): a boolean-ish value paired with `None`
classifies as `boolean` with `direction="added"`/`"removed"` and
`semantic="coverage"`, the absent side rendering as an em dash and the delta
carrying an `added`/`removed` pill -- the design's uniform treatment of
one-sided changes. This shape is not hypothetical: `reporting.py`'s
`_flatten_one_sided_structure` turns a newly added `reasoning` object into
leaves like `reasoning.default_enabled: None -> True`, which previously fell
through to `scalar` and leaked the raw Python repr (`null -> True`) into the
report. The known-boolean restriction applies to the present side too, so a
numeric leaf appearing from nothing (`...[0].weight: null -> 1`) stays
`scalar`.
"""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# Field label registry
#
# `RenderedChange.label` is the human-readable name every non-JSON renderer
# prints; `field_path` keeps the raw dotted path because the HTML tooltips and
# the JSON payload are audit surfaces. JSON never routes through here at all --
# `_delta_to_json` serialises `FieldChange` directly -- so labelling cannot
# change the machine-readable output.
#
# TWO PLAIN DICTS, ON PURPOSE. Adding, removing, or renaming a field label is a
# one-line edit to one of the literals below; there is no derivation, no
# decorator, and no ordering dependency between them. Each label lives in
# exactly one table so a rename is never a two-place edit.
#
# WHICH TABLE DOES A NAME GO IN?
#
#   FIELD_PATH_LABELS -- keyed by the FULL dotted path. Use when the leaf alone
#   is ambiguous or when the name should only ever be labelled at that one
#   location.
#
#   FIELD_LEAF_LABELS -- keyed by the LAST segment. Use when the leaf names the
#   field unambiguously wherever it appears. This is what makes the dynamic
#   conditional-pricing paths work: `_pricing_override_path` (reporting.py)
#   emits `pricing.overrides[min_prompt_tokens=200000].completion`, so the
#   money leaves cannot be keyed by a fixed full path and must be keyed by leaf
#   to be labelled under BOTH `pricing.completion` and the override form. The
#   six `default_parameters` leaves are leaf-keyed for the same reason (the
#   design specifies them as leaves).
#
# Lookup order is exact path -> leaf -> prettified leaf. `resolve_field_label`
# is the only consumer.
#
# Seeded from the design's "Initial registry contents": every distinct
# non-benchmark `field_name` observed in the history database (42 names).
# `tests/test_change_render.py::test_registry_covers_every_seeded_field_name`
# pins all 42 key/label pairs.

# Keyed by full dotted path. Consulted FIRST.
FIELD_PATH_LABELS: dict[str, str] = {
    # Context & limits.
    #
    # `top_provider.context_length` is the ONLY entry here that exists to beat
    # a leaf entry: `context_length` is simultaneously a real top-level field
    # and this field's leaf. They are distinct fields that both occur in the
    # history database and must not share a label verbatim, or the report
    # becomes ambiguous about which one moved. Deleting this line does not
    # produce an unlabelled row -- it produces a WRONG one, silently labelling
    # the provider-level field "Context length (model)".
    "top_provider.context_length": "Context length",
    "top_provider.max_completion_tokens": "Max output",
    # Capabilities.
    "reasoning.default_enabled": "Reasoning default",
    "reasoning.default_effort": "Reasoning effort",
    "reasoning.supported_efforts": "Supported efforts",
    "reasoning.mandatory": "Reasoning required",
    "architecture.modality": "Modality",
    "architecture.input_modalities": "Input modalities",
    "architecture.instruct_type": "Instruct type",
    # Metadata.
    "top_provider.is_moderated": "Moderated",
}

# Keyed by leaf segment. Consulted only when no full-path entry matched.
FIELD_LEAF_LABELS: dict[str, str] = {
    # Pricing. Leaf-keyed rather than path-keyed because conditional pricing
    # relocates these same leaves under a dynamic bracketed parent -- see the
    # note above.
    "prompt": "Input",
    "completion": "Output",
    "input_cache_read": "Cache read",
    "input_cache_write": "Cache write",
    "input_cache_write_1h": "Cache write (1h)",
    "input_audio_cache": "Audio cache",
    "audio": "Audio",
    "audio_output": "Audio output",
    "image": "Image",
    "image_output": "Image output",
    "web_search": "Web search",
    "internal_reasoning": "Internal reasoning",
    "request": "Per request",
    "overrides": "Conditional pricing",
    # Context & limits. Deliberately carries the "(model)" disambiguator; the
    # provider-level sibling is path-keyed above.
    "context_length": "Context length (model)",
    # Capabilities.
    "reasoning": "Reasoning",
    "supported_parameters": "Supported parameters",
    "supported_voices": "Supported voices",
    # Metadata.
    "knowledge_cutoff": "Knowledge cutoff",
    "expiration_date": "Expiration date",
    "description": "Description",
    "name": "Name",
    "created": "Created",
    "links": "Links",
    "hugging_face_id": "Hugging Face ID",
    # Default parameters.
    "default_parameters": "Default parameters",
    "frequency_penalty": "Frequency penalty",
    "presence_penalty": "Presence penalty",
    "repetition_penalty": "Repetition penalty",
    "temperature": "Temperature",
    "top_k": "Top-K",
    "top_p": "Top-P",
}


def _split_field_path(field_path: str) -> tuple[str, str | None]:
    """Split a path into its bare dotted form and any bracketed condition(s).

    Two places in reporting.py append a bracketed segment to a path:

      * `_pricing_override_path` -- a conditional-pricing predicate, e.g.
        `pricing.overrides[min_prompt_tokens=200000]`, later extended by
        `_diff_structured_values` into `...[min_prompt_tokens=200000].completion`.
      * `_flatten_one_sided_structure` -- a list index, e.g.
        `architecture.tier_profiles[0].weight`.

    Both must be stripped for the registry lookup (the label belongs to the
    field, not to the instance) and both are carried out as the qualifier (the
    instance is what distinguishes two otherwise identical rows). The condition
    is returned LITERALLY; turning `min_prompt_tokens=200000` into prose is a
    renderer concern and out of scope here.

    Scans character by character tracking bracket depth rather than splitting
    on "." first. That is not defensiveness for its own sake:
    `_pricing_override_path` interpolates the condition value through
    `_render_value`, so a non-integer threshold puts a "." INSIDE the brackets
    and a naive `field_path.split(".")` would tear the segment in half, losing
    both the label and the qualifier.
    """
    bare: list[str] = []
    condition: list[str] = []
    conditions: list[str] = []
    depth = 0
    for char in field_path:
        if char == "[":
            depth += 1
            if depth == 1:
                condition = []
                continue
        elif char == "]" and depth > 0:
            depth -= 1
            if depth == 0:
                if condition:
                    conditions.append("".join(condition))
                continue
        (condition if depth > 0 else bare).append(char)
    return "".join(bare), (", ".join(conditions) or None)


def _prettify_leaf(leaf: str) -> str:
    """Fallback label for a field no registry entry claims.

    Split on "_" and sentence-case: `max_prompt_images` -> `Max prompt images`.
    Sentence case, NOT title case -- the registry's own labels are sentence
    cased ("Cache read", "Internal reasoning"), so title-casing the fallback
    would make unregistered fields visually distinct from registered ones for
    no reason the reader can interpret.
    """
    words = leaf.replace("_", " ").strip()
    if not words:
        return leaf
    return words[0].upper() + words[1:]


def resolve_field_label(field_path: str) -> tuple[str, str | None]:
    """Return `(label, qualifier)` for a raw field path.

    Lookup order -- exact full path, then leaf segment, then prettified leaf.
    Exact-before-leaf is what lets a path-keyed entry override a leaf-keyed one
    (the `top_provider.context_length` / `context_length` collision); reversing
    the two silently mislabels rather than failing loudly.

    NEVER mutates `field_path`. Callers must store the original string in
    `RenderedChange.field_path` regardless of what this returns, because the
    HTML tooltips and the JSON payload render the raw path.
    """
    bare_path, qualifier = _split_field_path(field_path)
    label = FIELD_PATH_LABELS.get(bare_path)
    if label is None:
        leaf = bare_path.rsplit(".", 1)[-1]
        label = FIELD_LEAF_LABELS.get(leaf, _prettify_leaf(leaf))
    return label, qualifier


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
    # True when a percent change was applicable to this kind but could not be
    # computed because the basis (the old value) was 0. This is the CAUSE, not
    # a re-derivation of `pct_display is None`: renderers that want "no
    # percentage is meaningful here" must read this field rather than infer it
    # from `pct_display` being absent, so that a future task suppressing
    # `pct_display` for some other reason (rounding, thresholds, ...) does not
    # silently change their behavior. False for every kind that never computes
    # a percentage (list/boolean/scalar/noop) and for one-sided price/count
    # changes, which have no basis to compare against.
    pct_basis_zero: bool
    direction: Literal["up", "down", "added", "removed", "none"]
    semantic: Literal["cost", "capacity", "capability", "coverage", "neutral"]
    list_added: tuple[str, ...]
    list_removed: tuple[str, ...]

    def __post_init__(self) -> None:
        # `pct_basis_zero` is the CAUSE ("a percentage applied but the basis
        # was 0"), `pct_display` is the derived display string. The two are set
        # independently at ~10 construction sites, with nothing but convention
        # keeping them in step. A zero basis makes the percentage undefined, so
        # a `RenderedChange` that claims a zero basis *and* carries a rendered
        # percentage is incoherent and must not be constructible.
        #
        # Deliberately one-directional: `pct_display is None` does NOT imply a
        # zero basis (one-sided price/count changes and every
        # list/boolean/scalar/noop change have no percentage and no zero
        # basis), so the converse is not checked.
        if self.pct_basis_zero and self.pct_display is not None:
            raise ValueError(
                f"pct_basis_zero=True requires pct_display=None for field "
                f"{self.field_path!r}, got pct_display={self.pct_display!r}"
            )


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
    """Match reporting.py's `_render_value` exactly (behavior-preserving).

    `_render_value` special-cases `dict`/`list` through
    `json.dumps(value, sort_keys=True, ensure_ascii=True)` (e.g. a one-sided
    list scalar renders as `["a", "b"]`, not Python's `str([...])` ->
    `['a', 'b']`). Any divergence here is a silent neutrality break once this
    module is wired into the renderers.
    """
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    return str(value)


def _list_item_text(value: Any) -> str:
    """Stringify one member of a list field. THE single convention.

    Moved here from reporting.py, where it backed `_list_change_signature`
    (the bulk grouping key and the bulk renderers) while `classify_change`'s
    list branch used a plain `str(x)`. The two agreed for string members and
    diverged for `dict`/`list` members, so one report could render the same
    shape of data as `+{"name": "alpha"}` on a bulk card and
    `+{'name': 'beta'}` on a per-model card. JSON wins: Python `repr` must not
    reach rendered output.

    Both the bulk grouping key and every list renderer now funnel through this
    one function, so the conventions cannot drift apart again. `str` members
    are returned as-is rather than JSON-encoded, so plain-string list members
    render bare (`+tools`, not `+"tools"`) -- that is the shipped spelling for
    the overwhelmingly common case and is unchanged by the unification.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    return str(value)


def _list_diff_members(old_value: Any, new_value: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return `(added, removed)` sorted member text for two list values.

    THE single implementation of "what changed in this list": used by
    `classify_change`'s list branch (and therefore by every renderer, via
    `RenderedChange.list_added`/`list_removed`) and directly by
    `reporting.py::_list_change_signature`, the bulk grouping key.

    `_list_change_signature` calls this rather than `classify_change` on
    purpose. `classify_change` checks its `noop` branch (`old_value ==
    new_value`) BEFORE the list branch, and Python list equality is not the
    same relation as member-text equality: `[1] == [True]` is True while
    `_list_item_text` spells them `"1"` and `"True"`. Routing the grouping key
    through the full cascade would therefore return the empty pair for such an
    input where the previous hand-rolled key reported a difference -- a change
    to which models consolidate. Calling this helper keeps the key byte-
    identical to its pre-unification behavior for every possible input while
    still sharing one stringification and one set difference.

    (No FieldChange of that shape reaches production anyway: `diffing.py`'s
    `_diff_values` and `reporting.py`'s `_diff_structured_values` both emit a
    FieldChange only when `old_value != new_value`. The helper split makes the
    grouping guarantee unconditional rather than resting on that argument.)
    """
    old_set = {_list_item_text(x) for x in old_value}
    new_set = {_list_item_text(x) for x in new_value}
    return tuple(sorted(new_set - old_set)), tuple(sorted(old_set - new_set))


def _is_integer_like(value: Any) -> bool:
    """True if value is a non-bool 0/1 int or float (bool is handled separately)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value in (0, 1)
    if isinstance(value, float):
        return value in (0.0, 1.0)
    return False


def _is_boolean_side(field_name: str, value: Any) -> bool:
    """True if one side of a change is a value that means on/off, not a number.

    A real `bool` always qualifies. A plain `0`/`1` qualifies ONLY when the
    field is in `KNOWN_BOOLEAN_FIELDS`: gating on the value alone would
    capture `default_parameters.top_p: 0 -> 1`, a magnitude, and -- since the
    boolean branch now runs before the numeric one -- render it as a toggle.
    The restriction is what keeps that branch from over-reaching.
    """
    if isinstance(value, bool):
        return True
    if field_name in KNOWN_BOOLEAN_FIELDS:
        return _is_integer_like(value)
    return False


def _is_boolean_change(field_change: FieldChange) -> bool:
    """True if this change should be presented as a flag rather than a number.

    Two-sided: BOTH sides must be boolean-ish, so a mixed pair such as
    `default_parameters.top_p: False -> 0.9` (a real change where only the old
    value happens to be a bool) is not mistaken for a disable.

    One-sided: exactly one side is `None` and the PRESENT side is boolean-ish.
    `(None, None)` is not one-sided -- it is a noop, and the cascade catches it
    before this predicate is ever consulted.
    """
    old_value, new_value = field_change.old_value, field_change.new_value
    field_name = field_change.field_name
    if old_value is None and new_value is None:
        return False
    if old_value is None:
        return _is_boolean_side(field_name, new_value)
    if new_value is None:
        return _is_boolean_side(field_name, old_value)
    return _is_boolean_side(field_name, old_value) and _is_boolean_side(field_name, new_value)


def _bool_state(value: Any) -> Literal["on", "off"] | None:
    """Return "on"/"off" for a boolean-ish value, or `None` if not recognized.

    Boolean-ish means a real `bool`, or an int/float equal to 0 or 1. Any
    other value (e.g. `0.9`, `"yes"`) must return `None`, NOT be silently
    coerced to "off" via a bare fallthrough -- that was the root cause of a
    latent bug (Finding 3): a genuinely numeric change like
    `default_parameters.top_p: False -> 0.9` could previously render with
    both sides displaying "off" and a fabricated `direction="down"`, as if it
    were a disable, when in fact only `old_value` was ever boolean-ish.

    Callers must only rely on the returned value being non-`None` after
    confirming (e.g. via `_is_boolean_change`) that the value is meant to be
    treated as boolean; `_classify_boolean` relies on that precondition.
    """
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)) and value in (0, 1):
        return "on" if value == 1 else "off"
    return None


# ---------------------------------------------------------------------------
# Per-kind classification helpers.
# ---------------------------------------------------------------------------


# Rendered in place of a value that is absent on one side of a change. The
# design's uniform treatment of one-sided changes; `null`/`None` must not leak
# into a rendered flag.
ABSENT_DISPLAY = "—"


def _classify_boolean(field_change: FieldChange) -> RenderedChange:
    """Build the `boolean` RenderedChange for a two-sided or one-sided flag.

    Precondition: `_is_boolean_change(field_change)`. Enforced rather than
    assumed -- calling this with a value `_bool_state` does not recognize
    would otherwise fabricate a direction and put a non-display string into a
    display field (e.g. `top_p: False -> 0.9` reported as a disable).
    """
    field_path = field_change.field_name
    label, qualifier = resolve_field_label(field_path)
    old_value, new_value = field_change.old_value, field_change.new_value
    old_state = _bool_state(old_value)
    new_state = _bool_state(new_value)

    # One-sided: the absent side is `None` by definition, so only the present
    # side is required to be boolean-ish. `semantic="coverage"` and an
    # added/removed pill, matching one-sided price and count changes.
    one_sided_direction: Literal["added", "removed"] | None = None
    if old_value is None and new_state is not None:
        one_sided_direction = "added"
        old_display, new_display = ABSENT_DISPLAY, new_state
    elif new_value is None and old_state is not None:
        one_sided_direction = "removed"
        old_display, new_display = old_state, ABSENT_DISPLAY

    if one_sided_direction is not None:
        return RenderedChange(
            kind="boolean",
            field_path=field_path,
            label=label,
            qualifier=qualifier,
            old_display=old_display,
            new_display=new_display,
            old_raw=_raw_value(old_value),
            new_raw=_raw_value(new_value),
            unit=None,
            delta_display=one_sided_direction,
            delta_abs=None,
            pct_display=None,
            pct_basis_zero=False,
            direction=one_sided_direction,
            semantic="coverage",
            list_added=(),
            list_removed=(),
        )

    if old_state is None or new_state is None:
        offending = []
        if old_state is None:
            offending.append(f"old_value={old_value!r}")
        if new_state is None:
            offending.append(f"new_value={new_value!r}")
        raise ValueError(
            f"_classify_boolean requires boolean-ish values for field "
            f"{field_change.field_name!r}, got {', '.join(offending)}"
        )
    direction: Literal["up", "down"] = "up" if new_state == "on" else "down"
    delta_display = "enabled" if direction == "up" else "disabled"
    return RenderedChange(
        kind="boolean",
        field_path=field_path,
        label=label,
        qualifier=qualifier,
        old_display=old_state,
        new_display=new_state,
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit=None,
        delta_display=delta_display,
        delta_abs=None,
        pct_display=None,
        pct_basis_zero=False,
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
    label, qualifier = resolve_field_label(field_path)
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
            label=label,
            qualifier=qualifier,
            old_display=_fmt_price_per_m(norm_old),
            new_display=_fmt_price_per_m(norm_new),
            old_raw=_raw_value(old_value),
            new_raw=_raw_value(new_value),
            unit="/1M",
            delta_display=delta_display,
            delta_abs=delta_norm,
            pct_display=pct_display,
            pct_basis_zero=old_numeric == 0,
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
        label=label,
        qualifier=qualifier,
        old_display=old_display,
        new_display=new_display,
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit="/1M",
        delta_display=None,
        delta_abs=None,
        pct_display=None,
        pct_basis_zero=False,
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
    label, qualifier = resolve_field_label(field_path)
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
            label=label,
            qualifier=qualifier,
            old_display=_fmt_int(old_numeric),
            new_display=_fmt_int(new_numeric),
            old_raw=_raw_value(old_value),
            new_raw=_raw_value(new_value),
            unit="tok",
            delta_display=delta_display,
            delta_abs=delta,
            pct_display=pct_display,
            pct_basis_zero=old_numeric == 0,
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
        label=label,
        qualifier=qualifier,
        old_display=old_display,
        new_display=new_display,
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit="tok",
        delta_display=None,
        delta_abs=None,
        pct_display=None,
        pct_basis_zero=False,
        direction=one_sided_direction,
        semantic="coverage",
        list_added=(),
        list_removed=(),
    )


def _classify_numeric(field_change: FieldChange) -> RenderedChange:
    field_path = field_change.field_name
    label, qualifier = resolve_field_label(field_path)
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
        label=label,
        qualifier=qualifier,
        old_display=_fmt_int(old_f),
        new_display=_fmt_int(new_f),
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit=None,
        delta_display=delta_display,
        delta_abs=delta,
        pct_display=pct_display,
        pct_basis_zero=old_f == 0,
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

    Branch order (see module docstring for why boolean must precede the
    numeric family): noop -> list -> boolean -> price -> count -> numeric ->
    scalar.
    """
    field_path = field_change.field_name
    label, qualifier = resolve_field_label(field_path)
    old_value, new_value = field_change.old_value, field_change.new_value

    # 1. noop
    if (old_value is None and new_value is None) or old_value == new_value:
        return RenderedChange(
            kind="noop",
            field_path=field_path,
            label=label,
            qualifier=qualifier,
            old_display=_scalar_display(old_value),
            new_display=_scalar_display(new_value),
            old_raw=_raw_value(old_value),
            new_raw=_raw_value(new_value),
            unit=None,
            delta_display=None,
            delta_abs=None,
            pct_display=None,
            pct_basis_zero=False,
            direction="none",
            semantic="neutral",
            list_added=(),
            list_removed=(),
        )

    # 2. list
    if isinstance(old_value, list) and isinstance(new_value, list):
        # `_list_diff_members` (JSON member text), NOT a local set difference
        # over `str(x)`: the same helper that produces the bulk grouping key,
        # so per-model and bulk renderings of a structured list member are
        # spelled identically.
        added, removed = _list_diff_members(old_value, new_value)
        return RenderedChange(
            kind="list",
            field_path=field_path,
            label=label,
            qualifier=qualifier,
            # Raw int, NOT _fmt_int: production's _render_list_diff_text
            # interpolates len(...) directly (no thousands separator), so
            # _fmt_int here would silently diverge at >=1000 items (Finding 5).
            old_display=str(len(old_value)),
            new_display=str(len(new_value)),
            old_raw=_raw_value(old_value),
            new_raw=_raw_value(new_value),
            unit="items",
            delta_display=None,
            delta_abs=None,
            pct_display=None,
            pct_basis_zero=False,
            direction="none",
            semantic="capability",
            list_added=added,
            list_removed=removed,
        )

    # 3. boolean (E2) -- MUST precede price/count/numeric. `bool` is an `int`
    # subclass, so every guard below accepts a real bool pair and would
    # classify a flag as a magnitude; that is the defect this ordering fixes.
    # See the module docstring.
    if _is_boolean_change(field_change):
        return _classify_boolean(field_change)

    old_numeric = _numeric_value(old_value)
    new_numeric = _numeric_value(new_value)

    # 4. price -- guard preserved exactly from reporting.py's current
    # _render_smart_change_text (permits one-sided None, rejects non-numeric
    # strings).
    if (
        _is_price_amount_field(field_path)
        and (old_numeric is not None or new_numeric is not None)
        and (old_value is None or old_numeric is not None)
        and (new_value is None or new_numeric is not None)
    ):
        return _classify_price(field_change, old_numeric, new_numeric, price_multiplier, price_divisor)

    # 5. count -- same numeric-shape guard as price (permits one-sided None,
    # rejects non-numeric strings), with one deliberate difference from
    # reporting.py's `_render_smart_change_text`: that function's equivalent
    # guard has a fifth clause, `and (old_numeric is None or new_numeric is
    # None)`, which restricts it to the one-sided case and routes any
    # two-sided count change (e.g. context_length up/down) through the
    # *numeric* branch instead. This guard drops that fifth clause on
    # purpose, so a two-sided count change is classified as `count` here.
    #
    # This is a KEPT design choice, not a bug: the approved design requires
    # `semantic="capacity"` for two-sided numeric count fields, and the
    # five-clause guard makes that impossible (it never lets a two-sided pair
    # reach `_classify_count` at all).
    #
    # CONSEQUENCE FOR RENDERERS (read before wiring this module in): because
    # of this divergence, a two-sided `count` RenderedChange from this module
    # corresponds to a `numeric` RenderedChange in production for the exact
    # same input. Any renderer consuming this module MUST render a two-sided
    # `count` change IDENTICALLY to how it renders `numeric` -- the same
    # `(+delta, pct)` suffix, and NO `tok` unit -- or behavior neutrality
    # against the Task 1 characterization goldens breaks silently. See
    # test_two_sided_count_must_render_like_numeric_for_neutrality in
    # test_change_render.py, which pins the delta/pct fields a renderer needs
    # to reproduce numeric's exact output from a `count` RenderedChange.
    if (
        _is_count_field(field_path)
        and (old_numeric is not None or new_numeric is not None)
        and (old_value is None or old_numeric is not None)
        and (new_value is None or new_numeric is not None)
    ):
        return _classify_count(field_change, old_numeric, new_numeric)

    # 6. numeric -- both numeric, no category match. Real bool pairs and
    # known-boolean integer-coded pairs no longer reach here: step 3 claims
    # them first.
    if _both_numeric(old_value, new_value):
        return _classify_numeric(field_change)

    # 7. scalar fallback
    return RenderedChange(
        kind="scalar",
        field_path=field_path,
        label=label,
        qualifier=qualifier,
        old_display=_scalar_display(old_value),
        new_display=_scalar_display(new_value),
        old_raw=_raw_value(old_value),
        new_raw=_raw_value(new_value),
        unit=None,
        delta_display=None,
        delta_abs=None,
        pct_display=None,
        pct_basis_zero=False,
        direction="none",
        semantic="neutral",
        list_added=(),
        list_removed=(),
    )
