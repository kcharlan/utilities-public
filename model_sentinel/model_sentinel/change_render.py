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
it, so a genuinely numeric field must never satisfy it. That is why a
profile's `known_boolean_fields` is a restriction rather than a convenience,
and why `_bool_state` returns `None` for anything that is not a real bool or
an integer-coded 0/1.

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
import math
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Literal

from .models import FieldChange
from .provider_profiles import ProviderProfile, ResolvedPriceRule


PricingFieldSortKey = tuple[int, int, str, str]


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
    `_scalar_display`, so a non-integer threshold puts a "." INSIDE the brackets
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


def resolve_field_label(
    field_path: str,
    profile: ProviderProfile,
) -> tuple[str, str | None]:
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
    label = profile.field_path_labels.get(bare_path)
    if label is None:
        leaf = bare_path.rsplit(".", 1)[-1]
        label = profile.field_leaf_labels.get(leaf, _prettify_leaf(leaf))
    return label, qualifier


def resolve_price_rule(
    field_path: str,
    profile: ProviderProfile,
) -> ResolvedPriceRule:
    """Resolve one price field by exact bare path, leaf, then profile fallback."""
    bare_path, _ = _split_field_path(field_path)
    leaf = bare_path.rsplit(".", 1)[-1]
    if bare_path in profile.price_path_rules:
        declaration = profile.price_path_rules[bare_path]
        source = "path"
    elif leaf in profile.price_leaf_rules:
        declaration = profile.price_leaf_rules[leaf]
        source = "leaf"
    else:
        declaration = profile.unmatched_price_rule
        source = "unmatched"

    multiplier = (
        profile.price_multiplier
        if declaration.multiplier is None
        else declaration.multiplier
    )
    divisor = (
        profile.price_divisor
        if declaration.divisor is None
        else declaration.divisor
    )
    if multiplier < 1 or divisor < 1:
        raise ValueError(
            f"effective price factors must be positive for field {field_path!r}: "
            f"multiplier={multiplier}, divisor={divisor}"
        )
    return ResolvedPriceRule(
        unit_label=declaration.unit_label,
        multiplier=multiplier,
        divisor=divisor,
        comparison_group=declaration.comparison_group,
        normalized_target=declaration.normalized_target,
        match_source=source,
    )


# `_split_field_path` joins multiple bracket groups with this exact separator,
# and `format_qualified_label` splits on it to recover them. The two must stay
# in step, so the string lives in one place rather than being spelled twice.
QUALIFIER_SEPARATOR = ", "


def _format_qualifier_part(part: str) -> str:
    """Render ONE bracketed segment for display.

    Two producers emit bracketed segments (see `_split_field_path`) and they
    are told apart EXACTLY, not heuristically:

      * `_pricing_override_path` builds its condition as
        `",".join(f"{key}={value}")`, so every segment it emits contains at
        least one "=" and can never consist solely of decimal digits.
      * `_flatten_one_sided_structure` interpolates `enumerate` output, so
        every segment it emits is exactly `str(int)`.

    An all-digits segment therefore cannot have come from the condition
    producer. That is a property of how the paths are constructed, not a guess
    about what the text means.

    A condition is rendered LITERALLY (`min_prompt_tokens=200000`) as the
    design requires. A list index gets a "#" so the parenthetical reads as an
    ordinal: `Weight (#0)`, not `Weight (0)` -- a bare number in parentheses
    sitting one column away from the old/new value columns reads as a value,
    which is precisely the ambiguity a qualifier exists to remove.
    """
    if part.isascii() and part.isdigit():
        return f"#{part}"
    return part


def format_qualified_label(label: str, qualifier: str | None) -> str:
    """THE single implementation of "label plus its bracketed qualifier".

    Every non-JSON renderer -- text, markdown, both HTML paths and the changes
    report -- reads `RenderedChange.display_label`, which is this function.
    There is deliberately no per-renderer copy: the previous shape of this code
    populated `qualifier` and left every renderer printing a bare `label`, so
    `pricing.prompt` and `pricing.overrides[min_prompt_tokens=200000].prompt`
    both rendered as `Input` and a tiered model showed two indistinguishable
    rows. Five copies of the parenthetical would be five places for that to
    regress again.

    JSON does NOT route through here. `_delta_to_json` serialises `FieldChange`
    directly and keeps raw dotted field paths.
    """
    if not qualifier:
        return label
    parts = QUALIFIER_SEPARATOR.join(
        _format_qualifier_part(part) for part in qualifier.split(QUALIFIER_SEPARATOR)
    )
    return f"{label} ({parts})"


def pricing_field_sort_key(
    field_path: str,
    profile: ProviderProfile,
) -> PricingFieldSortKey:
    """Return the provider-defined presentation order for one Pricing field."""
    bare_path, _ = _split_field_path(field_path)
    leaf = bare_path.rsplit(".", 1)[-1]
    try:
        rank = profile.pricing_field_order.index(bare_path)
    except ValueError:
        try:
            rank = profile.pricing_field_order.index(leaf)
        except ValueError:
            rank = None

    label, qualifier = resolve_field_label(field_path, profile)
    display_label = format_qualified_label(label, qualifier).casefold()
    raw_path = field_path.casefold()
    if rank is None:
        return (1, 0, display_label, raw_path)
    return (0, rank, display_label, raw_path)


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
    price_rule: ResolvedPriceRule | None
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
        if self.kind == "price":
            if self.price_rule is None:
                raise ValueError(
                    f"price change requires price_rule for field {self.field_path!r}"
                )
            if self.unit != self.price_rule.unit_label:
                raise ValueError(
                    f"price change unit must match price_rule for field "
                    f"{self.field_path!r}: unit={self.unit!r}, "
                    f"rule={self.price_rule.unit_label!r}"
                )
        elif self.price_rule is not None:
            raise ValueError(
                f"non-price change requires price_rule=None for field {self.field_path!r}"
            )

    @property
    def display_label(self) -> str:
        """The field name every non-JSON renderer prints.

        `label` is the registry lookup and `qualifier` is the instance that
        lookup discarded; neither alone identifies the row. Renderers must read
        THIS, never `label`, or two tiers of a conditionally priced field
        collapse into two identical rows.

        A property, not a field: `dataclasses.fields(RenderedChange)` stays the
        classification contract, and there is no ~10-construction-site
        obligation to keep a derived string in step with its inputs.
        """
        return format_qualified_label(self.label, self.qualifier)


@dataclass(frozen=True)
class ResolvedPriceValue:
    """One provider price resolved without coupling it to a rendered change.

    Conditional schedules and ordinary scalar rows share this exact boundary:
    the provider spelling is retained for audit, exact arithmetic consumes the
    immutable rational value, and display/API compatibility consumes a finite
    float projection.
    """

    field_path: str
    raw_value: Any
    raw_display: str
    normalized_value: float
    normalized_exact_value: Fraction
    price_rule: ResolvedPriceRule

    def __post_init__(self) -> None:
        if not isinstance(self.field_path, str) or not self.field_path.strip():
            raise ValueError("resolved price field_path must be non-empty")
        if isinstance(self.raw_value, bool) or self.raw_value is None:
            raise ValueError("resolved price raw_value must be numeric and present")
        if not isinstance(self.raw_display, str):
            raise TypeError("resolved price raw_display must be a string")
        if not isinstance(self.normalized_value, float) or not math.isfinite(
            self.normalized_value
        ):
            raise ValueError("resolved price normalized_value must be a finite float")
        if not isinstance(self.normalized_exact_value, Fraction):
            raise TypeError("resolved price normalized_exact_value must be a Fraction")
        if not isinstance(self.price_rule, ResolvedPriceRule):
            raise TypeError("resolved price value requires a ResolvedPriceRule")


# ---------------------------------------------------------------------------
# Shared primitives, moved verbatim from reporting.py (behavior-preserving).
# reporting.py re-exports these so existing call sites keep working unchanged.
# ---------------------------------------------------------------------------


def _both_numeric(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    try:
        a_numeric = float(a)
        b_numeric = float(b)
        return math.isfinite(a_numeric) and math.isfinite(b_numeric)
    except (TypeError, ValueError, OverflowError):
        return False


def _numeric_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


# ---------------------------------------------------------------------------
# THE SENTINEL RULE.
#
# A column that would round to a DEGENERATE value -- a zero price, a zero
# delta, a zero percentage -- prints a bounded sentinel instead of a false one.
# `<$0.0001` says "smaller than this column can show"; `$0.0000` says
# "nothing", which for a value that is not nothing is simply untrue.
#
# WHAT COUNTS AS DEGENERATE, AND WHY ONLY THAT. Every other rendering in this
# module is a ROUNDING, and a rounding is an honest claim: `$12.345` says "this
# value rounds to 12.345 here", which is true of the number behind it. Zero is
# the one display whose natural reading is absolute rather than approximate --
# `$0.0000` reads as "free", `+$0.00000` as "unchanged", `0.0%` as "no
# movement". So zero is the only rendering that can be FALSE rather than
# merely coarse, and it is the only one the rule replaces.
#
# WHY A BOUND RATHER THAN MORE PRECISION. This replaces three accumulated
# escape hatches, each of which extended some column's precision until the
# degenerate value went away, and each of which fixed one column by pushing the
# inconsistency into another: a row whose operands had been separated still
# printed a vanishing delta; a row whose delta had been rescued still printed
# `0.0%`. A bound needs no extension at all, because it is already true at the
# precision the column has: `0 < |x| < B` is a fact about the value, not a
# rendering of it. Every cell of every row then states something true about the
# operands, and true statements about the same two numbers cannot contradict
# one another -- which is why the rule holds by construction rather than
# case by case.
#
# WHY IT MUST REMAIN DISTINGUISHABLE FROM ZERO. `free` (and `_fmt_int`'s bare
# `0`) means EXACTLY zero, is decided before the sentinel is consulted, and is
# spelled differently from it. A reader can therefore still tell "this costs
# nothing" from "this costs less than the column can show" -- a distinction
# `$0.0000` destroyed.
# ---------------------------------------------------------------------------


def _prints_as_zero(value: float, precision: int) -> bool:
    """True when a numerically non-zero magnitude prints as nothing but zeroes.

    THE trigger for the sentinel rule, and the only one. Shared by every column
    that can vanish this way -- the price operands, the price delta, the
    count/numeric operands and delta, and the percentage -- because `$0.0000`
    beside two different prices, `+$0.00000` beside a real movement and `0.0%`
    beside two different numbers are one defect seen in five columns. A second
    copy of the test could drift from the first.

    Decided on the STRING the column would print, never on the magnitude behind
    it: a magnitude threshold has to guess where the defect starts, and would
    fire on rows that read perfectly well (`0.15 -> 0.15006` has a delta below
    one unit in the last place, yet it ROUNDS UP to a visible `+$0.0001` and
    needs no sentinel).

    Compared against the digits a zero WOULD print at this precision rather
    than against any renderer's spelling of zero: an exactly zero price prints
    `free`, so the renderer's own spelling is not the string this magnitude is
    in danger of being mistaken for. `0.0000` is. Values that format to
    something other than digits (`inf`, `nan`) never match the zero digits, so
    they are never called vanished and never take a sentinel.
    """
    if value == 0:
        return False
    return f"{abs(value):.{precision}f}" == f"{0.0:.{precision}f}"


def _smallest_printable(precision: int) -> str:
    """The smallest magnitude `precision` decimal places can show, as digits.

    THE bound every sentinel quotes, derived from the column's own precision
    and never spelled at a call site: four places bound at `0.0001`, two at
    `0.01`, the percent column's one at `0.1`. A literal at each call site
    would be a second place where the column's precision is decided, and the
    two would part company the first time a precision moved.

    Deliberately the smallest PRINTABLE magnitude and not the tightest true
    one. A value printing as zero at four places is in fact below `0.00005`,
    half a unit; `<$0.0001` is the bound the reader can verify from the width
    of the column in front of them, where `<$0.00005` would be a number the row
    never mentions anywhere else. Both are true statements; this is the one
    that explains itself.
    """
    return f"{10.0 ** -precision:.{precision}f}"


def _minus(value: float) -> str:
    """THE sign position for a rendered magnitude: leading, before any mark.

    `-$3.00` and `-<$0.0001`, never `$-3.00`. One convention, in one function,
    because a column that spelled its ordinary negatives one way and its
    bounded ones another would align on nothing, and a reader scanning for a
    minus should find it in the same place in every cell. It is also the
    spelling the delta column has always used, where the sign leads by
    construction (`+$0.0075` above `-$0.0075`), so the price operands now agree
    with the delta printed beside them.

    A consequence worth naming: it keeps a negative's degenerate spelling
    (`-$0.00`) the same shape as a positive's (`$0.00`), so one predicate
    recognises both. `$-0.00` would need a second one, and a second one is how
    the first drifts.

    No observed payload prices below zero, so this is a guard rather than a
    live case on the price path; it is reachable on the numeric path, where
    `-0.001` renders `-<0.01`.
    """
    return "-" if value < 0 else ""


def _sentinel(
    value: float,
    precision: int,
    *,
    mark: str = "",
    suffix: str = "",
    lead: str | None = None,
) -> str:
    """THE spelling of a bounded magnitude, composed in exactly one place.

    `lead` + `<` + `mark` + the column's bound + `suffix`, which is every
    sentinel this module emits: `<$0.0001` and `-<$0.0001` (price, mark `$`),
    `<0.01` and `-<0.01` (count/numeric, no mark), `↑ <0.1%` and `↓ <0.1%`
    (percent, suffix `%`, lead supplied by the caller because the percent
    column's prefix is a DIRECTION and not a sign -- the magnitude's own minus
    would be a second, contradictory statement of the same thing).

    This existed as three separate f-strings, one per column, each rebuilding
    the same shape from the same two pieces. That is one rule with three
    renderings, and a rule with three renderings is three rules that happen to
    agree today: the moment one column grows a prefix the others do not know
    about, anything reading the column's output back -- including the test that
    asserts the rule -- is reading a spelling it was not written for. That is
    not hypothetical; it is exactly how the percent column's arrow escaped the
    acceptance criterion.
    """
    prefix = _minus(value) if lead is None else lead
    return f"{prefix}<{mark}{_smallest_printable(precision)}{suffix}"


# The decimal places `_fmt_int` gives a value that is not a whole number.
INT_FRACTION_PRECISION = 2


def _fmt_int(value: float) -> str:
    """A count or plain numeric value: exact when whole, two places otherwise.

    The sentinel rule reaches this column too, and must. `_fmt_int` is not a
    price formatter, but it had the identical failure: `0.001 -> 0.002` printed
    `0.00 -> 0.00` with a delta of `+0.00`, three cells asserting nothing
    beside a percentage asserting a doubling. It now prints
    `<0.01 -> <0.01  +<0.01`, three true bounds.

    Whole numbers are untouched, which is nearly the whole of this column in
    practice: `context_length` and every published count field is an integer,
    prints exactly at any magnitude, and can never round to a zero it is not.
    The sentinel is reachable here only through fractional values on the
    count/numeric paths.

    The sign is carried onto the sentinel through `_minus`, the same function
    the price column uses, so a negative magnitude is not flattened into a
    positive bound: `-0.001` renders `-<0.01`, not `<0.01` (true of the
    magnitude, and the direction the rest of the row asserts).
    """
    if value == int(value):
        return f"{int(value):,}"
    if _prints_as_zero(value, INT_FRACTION_PRECISION):
        return _sentinel(value, INT_FRACTION_PRECISION)
    return f"{value:,.{INT_FRACTION_PRECISION}f}"


# The percent column's one decimal place -- `↑ 63.6%`, `↓ 20.5%` (design:
# "RenderedChange / pct_display"). One place is what the column is FOR, and the
# sentinel is what lets it stay one place: a movement too small to show here
# prints `↑ <0.1%`, not the `↑ 0.0%` that denied it.
PCT_PRECISION = 1


def signed_pct_change(old: float, new: float) -> float | None:
    """The row's relative movement as a SIGNED NUMBER, or `None` for a zero basis.

    The arithmetic behind `_pct_change`'s string, extracted so that the one
    other consumer of a percentage -- `reporting._model_price_impact`, which
    orders model cards by impact (design F2, tiebreaker 2) -- ranks by the
    percentage the row actually prints instead of re-deriving it beside this
    one. A second copy of `(new - old) / abs(old)` would be a second place for
    the zero-basis case and the sign convention to drift.

    Signed -- as the name now says. It was called `pct_change_magnitude` while
    returning a signed value, so the docstring had to spend a sentence
    disclaiming the name, and both callers take `abs()` or strip the sign
    themselves. NOT rounded to `PCT_PRECISION` either: the sort wants the true
    ordering, and rounding here would manufacture ties that the display's one
    decimal place merely hides. Callers that want a magnitude take `abs()`.

    `None`, not `0.0`, when `old == 0`: `(new - 0) / 0` has no relative reading
    at all, and a zero would sort such a row as if it had not moved.
    """
    if old == 0:
        return None
    return ((new - old) / abs(old)) * 100


def _pct_change(old: float, new: float) -> str:
    """The row's relative movement: one place, bounded rather than denied.

    Serves price, count AND numeric rows, so the sentinel does too -- a
    six-token bump on a 262,144 context window reads `↑ <0.1%` for exactly the
    same reason a tenth-of-a-cent price move does, and a price-only fix would
    have left the same lie in the other two columns.

    A zero basis still yields NO percentage at all: `(new - 0) / 0` has no
    relative reading, and the empty string is how this function has always said
    so (callers pair it with `pct_basis_zero`, which names the cause). The
    sentinel cannot reach that case -- it is decided before any percentage is
    computed -- and must not: a bound on an undefined quantity is not a truer
    statement than its absence.

    An exactly zero movement (`3 -> "3"`: different recorded values, equal as
    numbers) prints `0.0%` and NO arrow. `0.0%` is what actually happened, so
    the sentinel declines it -- and the arrow is dropped because a movement of
    zero has no direction. The `↓` this used to print was the row's last
    remaining false claim: one column reporting a decrease beside three
    reporting no change.
    """
    pct = signed_pct_change(old, new)
    if pct is None:
        return ""
    arrow = "↑ " if pct > 0 else ("↓ " if pct < 0 else "")
    if _prints_as_zero(pct, PCT_PRECISION):
        return _sentinel(pct, PCT_PRECISION, suffix="%", lead=arrow)
    return f"{arrow}{abs(pct):.{PCT_PRECISION}f}%"


# Price precision bounds (design: "Value formatting / Price display (A1)").
#
# Every price in a row renders at ONE precision, between these two bounds. The
# floor is cents because that is the granularity a reader prices in; the
# ceiling keeps the normalized column narrow for the values it was sized for.
#
# The ceiling is now a real ceiling. It used to be extended, without limit up
# to twenty places, by whichever row would otherwise have printed a degenerate
# value; a price too small to show at four places says so with a bound instead
# (see THE SENTINEL RULE above), so nothing is left for the extension to buy.
PRICE_MIN_PRECISION = 2
PRICE_MAX_PRECISION = 4

# Absorbs the float error `_normalize_price` introduces, NOT a fudge factor.
# `(raw * multiplier) / divisor` is inexact in binary: `5e-08 * 1_000_000` is
# `0.049999999999999996`, whose shortest exact decimal form has seventeen
# places. Asking for exact equality would price a five-cent cache read at
# `$0.0500` because of representation noise in a value the provider spelled
# with two significant digits. The tolerance is RELATIVE because the error it
# absorbs is relative: it scales with the magnitude the multiplication
# produced.
_PRICE_PRECISION_REL_TOL = 1e-9


def _significant_decimals(value: float) -> int:
    """Decimal places `value` actually needs, clamped to the price bounds.

    Returns the smallest precision in [PRICE_MIN_PRECISION, PRICE_MAX_PRECISION]
    that reproduces `value`, or PRICE_MAX_PRECISION when no precision in that
    range does -- which is what makes "capped at 4" mean "renders at 4" rather
    than "renders at whatever is left after rounding".

    A value of 0.000001 needs six places. At four it is NOT rounded away into
    `$0.0000`: `_fmt_money` bounds it into `<$0.0001`, which is the
    statement the cap was always trying to make ("too small for this column")
    without the false one it used to make instead ("nothing").

    The relative tolerance is load-bearing, not a fudge: `(raw * multiplier) /
    divisor` is inexact in binary, so an exact comparison would price a
    five-cent cache read at `$0.0500`. See _PRICE_PRECISION_REL_TOL.
    """
    for places in range(PRICE_MIN_PRECISION, PRICE_MAX_PRECISION):
        if math.isclose(round(value, places), value, rel_tol=_PRICE_PRECISION_REL_TOL, abs_tol=0.0):
            return places
    return PRICE_MAX_PRECISION


def _price_precision(*values: float) -> int:
    """THE shared precision for one price row: its operands', capped at four.

    Called ONCE per row and passed to every `_fmt_money` call for that
    row. The point of the function is that old, new and delta cannot disagree:
    formatting them from three independent magnitude-based decisions is exactly
    the defect this replaces, where `$0.196`, `$0.1876` and `$0.0196` could
    share a card with their decimal points in three different columns and the
    three numbers of one row could each claim a different precision.

    The DELTA gets no say in the answer, and no longer needs one. It is a
    difference of the two operands, so letting it choose its own precision is
    how `$0.1500 -> $0.1425` ends up beside a delta claiming more (or fewer)
    places than the numbers it was computed from; and a delta too small to
    print at the row's precision now says exactly that (`+<$0.0001`) instead of
    demanding the whole row be widened until it can be spelled in full. That
    demand was the second of the three escape hatches, and the reason this
    function used to take a required keyword-only `delta`.
    """
    return max((_significant_decimals(value) for value in values), default=PRICE_MIN_PRECISION)


def _fmt_money(value: float, precision: int) -> str:
    """Format one display-denominated price at the row's shared precision.

    Three outcomes, and only one of them is a rendering of the number:

      * EXACTLY zero -> `free`. The one value permitted to claim it is nothing,
        because it is.
      * non-zero but too small to print here -> `<$0.0001`, the sentinel (see
        THE SENTINEL RULE). Not `$0.0000`, which makes `free`'s claim falsely
        and which a reader cannot tell apart from it.
      * anything else -> the number, at the row's precision.

    `precision` is REQUIRED. It used to default to a value derived from this
    one operand, which was correct only for the one-sided branches; any future
    two-sided caller that forgot to pass the row's precision would silently
    have reintroduced the desynchronised-precision defect. One-sided callers
    pass `_price_precision(value)` explicitly instead, which says the same
    thing at the call site where it is true.

    Both the bound and the number carry their sign through `_minus`, so a
    negative price is spelled `-$3.00` and a negative bound `-<$0.0001` -- one
    sign position for the column rather than one per branch. No observed
    payload prices below zero, so both are guards rather than live cases; that
    is precisely why they must not be allowed to disagree, because nothing
    downstream would ever see them do it.
    """
    if value == 0:
        return "free"
    if _prints_as_zero(value, precision):
        return _sentinel(value, precision, mark="$")
    return f"{_minus(value)}${abs(value):.{precision}f}"


def _normalize_price(raw_value: float, multiplier: int, divisor: int) -> float:
    return (raw_value * multiplier) / divisor


PRICE_VALUE_MAX_DECIMAL_DIGITS = 1_000
PRICE_VALUE_MAX_ABS_DECIMAL_EXPONENT = 10_000


def _bounded_decimal_price_value(raw_value: Any) -> Decimal | None:
    """Parse a finite provider price within fixed exact-arithmetic bounds.

    Provider prices observed by this project need hundreds, not thousands, of
    decimal places (the exact underflow contract intentionally includes
    ``1e-400``).  A 1,000-digit Decimal coefficient and an absolute base-10
    exponent of 10,000 leave orders of magnitude of headroom while bounding a
    raw rational to roughly 11,000 decimal digits.  The check happens while
    the value is still a compact Decimal, before ``Fraction`` can expand a
    spelling such as ``1e-1000000`` into a million-power denominator.

    The digit limit intentionally counts Decimal's stored coefficient digits,
    including retained trailing zeroes: those zeroes can still make exact
    rational construction do proportional work even though they do not change
    the mathematical value.
    """
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        decimal_value = Decimal(str(raw_value).strip())
    except (InvalidOperation, ValueError, OverflowError):
        return None
    if not decimal_value.is_finite():
        return None
    decimal_tuple = decimal_value.as_tuple()
    exponent = decimal_tuple.exponent
    if not isinstance(exponent, int):
        return None
    if (
        len(decimal_tuple.digits) > PRICE_VALUE_MAX_DECIMAL_DIGITS
        or abs(exponent) > PRICE_VALUE_MAX_ABS_DECIMAL_EXPONENT
    ):
        return None
    return decimal_value


def _exact_numeric_fraction(raw_value: Any) -> Fraction | None:
    """Parse one finite provider numeric spelling without a float intermediate."""
    decimal_value = _bounded_decimal_price_value(raw_value)
    if decimal_value is None:
        return None
    return Fraction(decimal_value)


def _finite_fraction_projection(value: Fraction) -> float | None:
    """Project an exact value to a finite float without erasing nonzero sign."""
    try:
        projected = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(projected):
        return None
    if value != 0 and projected == 0:
        minimum = math.nextafter(0.0, math.inf)
        return minimum if value > 0 else -minimum
    return projected


# ---------------------------------------------------------------------------
# Display helpers used only by classify_change and its per-kind helpers.
# ---------------------------------------------------------------------------


# THE two spellings of a side that is absent, both owned here because this
# module is what puts them into `old_display`/`new_display`. Consumers import
# them rather than respelling the literal:
#
#   ABSENT_DISPLAY      the `—` a one-sided BOOLEAN already carries, and the
#                       spelling every HTML surface uses for any absent side;
#   ABSENT_TEXT_DISPLAY the `null` a one-sided price, count or scalar carries
#                       in the shared text line, and therefore in the text and
#                       markdown reports built from it. (JSON never routes
#                       through here at all -- `_delta_to_json` serialises
#                       `FieldChange` directly -- so neither spelling can reach
#                       the audit output.)
#
# The split is historical and is preserved on purpose: respelling
# `ABSENT_TEXT_DISPLAY` here would move the text and markdown characterization
# goldens. HTML closes it at the renderer, keyed on `raw is None`.
#
# `ABSENT_TEXT_DISPLAY` is a constant because the token had ten independent
# literals across the two modules before this, and the text renderers still
# emit it while the HTML ones must not. It is no longer RECOGNISED anywhere:
# `_summary_detail_with_absent_sides`, which respelled the token after the fact
# in the Change Summary, is gone -- the summary composes its cell from
# `RenderedChange` through `_html_side_display`, so `null` is never produced on
# an HTML path rather than produced and then replaced.
ABSENT_DISPLAY = "—"
ABSENT_TEXT_DISPLAY = "null"


def _raw_value(value: Any) -> str | None:
    return None if value is None else str(value)


def resolve_price_value(
    field_path: str,
    raw_value: Any,
    profile: ProviderProfile,
    *,
    allow_unmatched: bool = False,
) -> ResolvedPriceValue | None:
    """Resolve one finite provider price through the active profile.

    The public default is deliberately strict for composite schedules: an
    unmatched declaration has no provider-owned unit/comparison identity and
    therefore cannot enter schedule arithmetic.  Scalar classification passes
    ``allow_unmatched=True`` to preserve the established safe visible fallback
    for an otherwise monetary field.
    """
    if raw_value is None or isinstance(raw_value, bool):
        return None
    exact_value = _exact_numeric_fraction(raw_value)
    if exact_value is None:
        return None
    price_rule = resolve_price_rule(field_path, profile)
    if price_rule.match_source == "unmatched" and not allow_unmatched:
        return None
    normalized_exact = exact_value * Fraction(
        price_rule.multiplier,
        price_rule.divisor,
    )
    normalized = _finite_fraction_projection(normalized_exact)
    if normalized is None:
        return None
    raw_display = _raw_value(raw_value)
    if raw_display is None:  # guarded above; keeps the constructor invariant local
        return None
    return ResolvedPriceValue(
        field_path=field_path,
        raw_value=raw_value,
        raw_display=raw_display,
        normalized_value=float(normalized),
        normalized_exact_value=normalized_exact,
        price_rule=price_rule,
    )


def _precision_basis_value(value: ResolvedPriceValue | int | float) -> float:
    numeric = (
        value.normalized_value
        if isinstance(value, ResolvedPriceValue)
        else float(value)
    )
    if isinstance(value, bool) or not math.isfinite(numeric):
        raise ValueError("price precision basis values must be finite numbers")
    return numeric


def format_price_values(
    values: Iterable[ResolvedPriceValue],
    *,
    precision_basis: Iterable[ResolvedPriceValue | int | float],
) -> tuple[str, ...]:
    """Format normalized prices through the one scalar precision/sentinel path."""
    resolved_values = tuple(values)
    if any(not isinstance(value, ResolvedPriceValue) for value in resolved_values):
        raise TypeError("values must contain only ResolvedPriceValue instances")
    basis = tuple(_precision_basis_value(value) for value in precision_basis)
    if not basis:
        basis = tuple(value.normalized_value for value in resolved_values)
    precision = _price_precision(*basis)
    return tuple(
        _fmt_money(value.normalized_value, precision) for value in resolved_values
    )


def _scalar_display(value: Any) -> str:
    """THE scalar spelling for every renderer (behavior-preserving).

    `dict`/`list` are special-cased through
    `json.dumps(value, sort_keys=True, ensure_ascii=True)` (e.g. a one-sided
    list scalar renders as `["a", "b"]`, not Python's `str([...])` ->
    `['a', 'b']`). This body started as a copy of reporting.py's
    `_render_value`, which was kept alive as an alias to this function and has
    since been deleted outright; its call sites now call this directly, so
    there is no second name left for the two spellings to drift between.
    """
    if value is None:
        return ABSENT_TEXT_DISPLAY
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


def _is_boolean_side(
    field_name: str,
    value: Any,
    profile: ProviderProfile,
) -> bool:
    """True if one side of a change is a value that means on/off, not a number.

    A real `bool` always qualifies. A plain `0`/`1` qualifies ONLY when the
    field is in `profile.known_boolean_fields`: gating on the value alone would
    capture `default_parameters.top_p: 0 -> 1`, a magnitude, and -- since the
    boolean branch now runs before the numeric one -- render it as a toggle.
    The restriction is what keeps that branch from over-reaching.
    """
    if isinstance(value, bool):
        return True
    if field_name in profile.known_boolean_fields:
        return _is_integer_like(value)
    return False


def _is_boolean_change(
    field_change: FieldChange,
    profile: ProviderProfile,
) -> bool:
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
        return _is_boolean_side(field_name, new_value, profile)
    if new_value is None:
        return _is_boolean_side(field_name, old_value, profile)
    return _is_boolean_side(
        field_name,
        old_value,
        profile,
    ) and _is_boolean_side(field_name, new_value, profile)


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


def _classify_boolean(
    field_change: FieldChange,
    profile: ProviderProfile,
) -> RenderedChange:
    """Build the `boolean` RenderedChange for a two-sided or one-sided flag.

    Precondition: `_is_boolean_change(field_change)`. Enforced rather than
    assumed -- calling this with a value `_bool_state` does not recognize
    would otherwise fabricate a direction and put a non-display string into a
    display field (e.g. `top_p: False -> 0.9` reported as a disable).
    """
    field_path = field_change.field_name
    label, qualifier = resolve_field_label(field_path, profile)
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
            price_rule=None,
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
        price_rule=None,
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
    old_price: ResolvedPriceValue | None,
    new_price: ResolvedPriceValue | None,
    old_numeric: float | None,
    new_numeric: float | None,
    profile: ProviderProfile,
) -> RenderedChange:
    field_path = field_change.field_name
    label, qualifier = resolve_field_label(field_path, profile)
    present_price = old_price if old_price is not None else new_price
    if present_price is None:
        raise ValueError("price classification requires at least one resolved value")
    price_rule = present_price.price_rule

    if old_price is not None and new_price is not None:
        if old_numeric is None or new_numeric is None:
            raise ValueError("two-sided price classification requires raw numerics")
        norm_old = _normalize_price(
            old_numeric,
            price_rule.multiplier,
            price_rule.divisor,
        )
        norm_new = _normalize_price(
            new_numeric,
            price_rule.multiplier,
            price_rule.divisor,
        )
        delta_norm = norm_new - norm_old
        direction: Literal["up", "down", "none"]
        if delta_norm > 0:
            direction = "up"
        elif delta_norm < 0:
            direction = "down"
        else:
            direction = "none"
        sign = "+" if delta_norm > 0 else ("-" if delta_norm < 0 else "")
        # ONE precision for the whole row, sized by the OPERANDS and passed to
        # all three formats. The delta does not get a say in how many places
        # the row prints -- it is a difference of the two operands, so letting
        # it choose its own precision is how `$0.1500 -> $0.1425` ends up next
        # to a delta claiming more (or fewer) places than the numbers it was
        # computed from. A delta too small to print here bounds itself
        # (`+<$0.0001`) rather than widening the row.
        precision = _price_precision(norm_old, norm_new)
        delta_display = f"{sign}{_fmt_money(abs(delta_norm), precision)}"
        pct_display = _pct_change(old_numeric, new_numeric) or None
        return RenderedChange(
            kind="price",
            field_path=field_path,
            label=label,
            qualifier=qualifier,
            old_display=_fmt_money(norm_old, precision),
            new_display=_fmt_money(norm_new, precision),
            old_raw=old_price.raw_display,
            new_raw=new_price.raw_display,
            unit=price_rule.unit_label,
            price_rule=price_rule,
            delta_display=delta_display,
            delta_abs=delta_norm,
            pct_display=pct_display,
            pct_basis_zero=old_numeric == 0,
            direction=direction,
            semantic="cost",
            list_added=(),
            list_removed=(),
        )

    # One-sided: a single operand, with no second value to agree with and no
    # difference to print, so it prices itself. The precision is derived and
    # passed EXPLICITLY rather than left to a default, so the only way to
    # format a price is to have named its precision at the call site.
    if old_price is None:
        one_sided_direction: Literal["added", "removed"] = "added"
        old_display = ABSENT_TEXT_DISPLAY
        if new_price is None or new_numeric is None:
            raise ValueError("added price classification requires a new value")
        norm_only = _normalize_price(
            new_numeric,
            price_rule.multiplier,
            price_rule.divisor,
        )
        new_display = _fmt_money(norm_only, _price_precision(norm_only))
    else:
        one_sided_direction = "removed"
        if old_numeric is None:
            raise ValueError("removed price classification requires an old value")
        norm_only = _normalize_price(
            old_numeric,
            price_rule.multiplier,
            price_rule.divisor,
        )
        old_display = _fmt_money(norm_only, _price_precision(norm_only))
        new_display = ABSENT_TEXT_DISPLAY

    return RenderedChange(
        kind="price",
        field_path=field_path,
        label=label,
        qualifier=qualifier,
        old_display=old_display,
        new_display=new_display,
        old_raw=None if old_price is None else old_price.raw_display,
        new_raw=None if new_price is None else new_price.raw_display,
        unit=price_rule.unit_label,
        price_rule=price_rule,
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
    profile: ProviderProfile,
) -> RenderedChange:
    field_path = field_change.field_name
    label, qualifier = resolve_field_label(field_path, profile)
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
            price_rule=None,
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
        old_display = ABSENT_TEXT_DISPLAY
        new_display = _fmt_int(new_numeric)
    else:
        one_sided_direction = "removed"
        old_display = _fmt_int(old_numeric)
        new_display = ABSENT_TEXT_DISPLAY

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
        price_rule=None,
        delta_display=None,
        delta_abs=None,
        pct_display=None,
        pct_basis_zero=False,
        direction=one_sided_direction,
        semantic="coverage",
        list_added=(),
        list_removed=(),
    )


def _classify_numeric(
    field_change: FieldChange,
    profile: ProviderProfile,
) -> RenderedChange:
    field_path = field_change.field_name
    label, qualifier = resolve_field_label(field_path, profile)
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
        price_rule=None,
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
    profile: ProviderProfile,
) -> RenderedChange:
    """Classify a single field change into a structured `RenderedChange`.

    Branch order (see module docstring for why boolean must precede the
    numeric family): noop -> list -> boolean -> price -> count -> numeric ->
    scalar.
    """
    field_path = field_change.field_name
    label, qualifier = resolve_field_label(field_path, profile)
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
            price_rule=None,
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
            # `None`, not "items". Every renderer that prints `unit` prints it
            # beside a pair of operands -- the card's unit column, the price
            # headline, the Change Summary's `old → new unit` -- and a list
            # change has no operand row: its counts live inside the parenthesis
            # `(1 → 2)` beside the member names. "items" was set at
            # construction, read by nothing, and would have read as
            # `+logit_bias (1 → 2) items` the moment anything did read it.
            unit=None,
            price_rule=None,
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
    if _is_boolean_change(field_change, profile):
        return _classify_boolean(field_change, profile)

    old_numeric = _numeric_value(old_value)
    new_numeric = _numeric_value(new_value)

    # 4. price -- guard preserved exactly from reporting.py's current
    # _render_smart_change_text (permits one-sided None, rejects non-numeric
    # strings).
    is_price_amount_field = (
        profile.is_price_amount_field(field_path)
        and not profile.is_pricing_override_selector_path(field_path)
    )
    if is_price_amount_field:
        old_price = resolve_price_value(
            field_path,
            old_value,
            profile,
            allow_unmatched=True,
        )
        new_price = resolve_price_value(
            field_path,
            new_value,
            profile,
            allow_unmatched=True,
        )
        if (
            (old_price is not None or new_price is not None)
            and (old_value is None or old_price is not None)
            and (new_value is None or new_price is not None)
        ):
            return _classify_price(
                field_change,
                old_price,
                new_price,
                old_numeric,
                new_numeric,
                profile,
            )

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
        not is_price_amount_field
        and profile.is_count_field(field_path)
        and (old_numeric is not None or new_numeric is not None)
        and (old_value is None or old_numeric is not None)
        and (new_value is None or new_numeric is not None)
    ):
        return _classify_count(field_change, old_numeric, new_numeric, profile)

    # 6. numeric -- both numeric, no category match. Real bool pairs and
    # known-boolean integer-coded pairs no longer reach here: step 3 claims
    # them first.
    if not is_price_amount_field and _both_numeric(old_value, new_value):
        return _classify_numeric(field_change, profile)

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
        price_rule=None,
        delta_display=None,
        delta_abs=None,
        pct_display=None,
        pct_basis_zero=False,
        direction="none",
        semantic="neutral",
        list_added=(),
        list_removed=(),
    )
