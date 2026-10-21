"""HTML for a scan report's alias events, Provider endpoints disclosure and ladders.

`reporting._render_scan_html` calls `render_endpoint_html` once with the
sections `endpoint_report.scan_endpoint_sections` built for the page's detail
mode. Everything about ordering, the concise list cap, summary clauses,
persisting-alias selection, squelched omission and wording is decided there;
this module only renders those records, so the HTML cannot drift from the text
and Markdown reports. Price ladders render `alias_check.price_ladder`'s
positions as given and never recompute the scale.

The report has no JavaScript (README HTML Auto-Reports): the disclosure is a
native `<details>`, raw values ride the page's CSS-only `Show raw values`
checkbox, and the ladders are static SVG. Color follows README Color
Semantics: red and green appear only on a price cell or row that moved up or
down; endpoint presence and price coverage are the neutral coverage blue; the
ladders' endpoint dots and target/alias marks are neutral and told apart by
shape and label, never by a cost color.

This module imports `reporting`'s card-row helpers, so `reporting` imports
this module inside `_render_scan_html` rather than at module level.
"""

from __future__ import annotations

import html as html_module
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote as url_quote

from .alias_check import (
    ALIAS_EVENT_CHANGED,
    ALIAS_EVENT_NEW,
    ALIAS_EVENT_PERSISTING,
    LADDER_ENDPOINT,
    UNPLACED_INCOMPATIBLE,
    UNPLACED_INVALID,
    UNPLACED_MISSING,
    UNPLACED_NEGATIVE,
    UNPLACED_ZERO,
)
from .change_render import ABSENT_DISPLAY, absent_side_display, resolve_price_rule
from .endpoint_report import (
    AliasEventView,
    EndpointListView,
    EndpointPriceCell,
    EndpointPriceColumn,
    EndpointPriceRow,
    ProviderAliasReport,
    ProviderEndpointReport,
    Quote,
    ScanEndpointSections,
    alias_event_heading,
    alias_event_reason,
    alias_ladders,
    alias_leaf_sentence,
    alias_match_sentence,
    alias_unavailable_leaf_sentence,
    detail_only_lists_phrase,
    endpoint_list_heading,
    omitted_lists_phrase,
)
from .models import Ladder, ProviderScanResult, canonical_json
from .provider_profiles import ProviderProfile
from .reporting import (
    _CARD_TABLE_COLGROUP,
    _card_semantic_class,
    _raw_price_derivation,
    _render_html_card_row,
)

# The fixed landmarks other pages link to: the companion reports point at each
# other's disclosure, so the id is part of the navigation contract.
PROVIDER_ENDPOINTS_ANCHOR: Final = "provider-endpoints"
ALIAS_CHECK_ANCHOR: Final = "alias-check"

# Kinds whose leaves are a divergence, so each displayed leaf gets a ladder.
_LADDER_KINDS: Final = frozenset({ALIAS_EVENT_NEW, ALIAS_EVENT_CHANGED, ALIAS_EVENT_PERSISTING})

_h = html_module.escape


@dataclass(frozen=True)
class EndpointHtml:
    """The page's endpoint and alias additions; every field is `""` when absent.

    `alias_html` goes after the Price Movement card, `disclosure_html` after
    the scan's `Other changes` disclosure, and `css` into the page stylesheet.
    """

    alias_html: str
    disclosure_html: str
    css: str


def render_endpoint_html(
    sections: ScanEndpointSections,
    provider_results: Sequence[ProviderScanResult],
    *,
    companion_link: tuple[str, str] | None,
) -> EndpointHtml:
    """Render both sections; nothing at all (CSS included) when both are empty."""
    profiles = {result.provider_id: result.profile for result in provider_results}
    ids = _Ids()
    alias_html = _alias_section(sections.alias_reports, profiles, ids)
    disclosure_html = _endpoint_disclosure(sections.endpoint_reports, profiles, ids, companion_link)
    css = ENDPOINT_HTML_CSS if alias_html or disclosure_html else ""
    return EndpointHtml(alias_html, disclosure_html, css)


class _Ids:
    """Page-unique ids for ladder titles and their text equivalents."""

    def __init__(self) -> None:
        self._count = 0

    def next(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}-{self._count}"


def _with_code(build: Callable[[Quote], str]) -> str:
    """Escape a model-built sentence, rendering its quoted identifiers as `<code>`.

    The sentence comes from the shared wording helpers, which wrap identifiers
    through a `Quote`. Each identifier becomes a private-use placeholder, the
    whole sentence is escaped, then each placeholder is replaced by its escaped
    identifier in `<code>`. An index outside the recorded identifiers is left
    as escaped text, so stray placeholder characters cannot inject markup.
    """
    values: list[str] = []

    def quote(value: str) -> str:
        values.append(value)
        return f"{len(values) - 1}"

    escaped = _h(build(quote))

    def code(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return f"<code>{_h(values[index])}</code>" if index < len(values) else match.group(0)

    return re.sub("(\\d+)", code, escaped)


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def _companion_href(companion_link: tuple[str, str]) -> str:
    """The sibling report's disclosure, encoded as `_companion_link_html` does."""
    filename, _ = companion_link
    return f"{url_quote(filename, safe='')}#{PROVIDER_ENDPOINTS_ANCHOR}"


def _nav_link(companion_link: tuple[str, str]) -> str:
    _, label = companion_link
    return f'<a class="endpoint-nav" href="{_h(_companion_href(companion_link))}">{_h(label)}</a>'


# ---------------------------------------------------------------------------
# Alias events
# ---------------------------------------------------------------------------


def _alias_section(
    reports: Sequence[ProviderAliasReport],
    profiles: Mapping[str, ProviderProfile],
    ids: _Ids,
) -> str:
    if not reports:
        return ""
    parts = [
        f'<section class="alias-check" id="{ALIAS_CHECK_ANCHOR}" aria-labelledby="alias-check-title">'
        '<h2 class="alias-check-title" id="alias-check-title">Alias check</h2>'
    ]
    for report in reports:
        parts.append(_provider_name(report.provider_label, report.provider_id, "alias-provider"))
        parts.extend(_alias_event(view, profiles[report.provider_id], ids) for view in report.events)
    parts.append("</section>")
    return "".join(parts)


def _provider_name(label: str, provider_id: str, css_class: str) -> str:
    return f'<div class="{css_class}">{_h(label)} <code>{_h(provider_id)}</code></div>'


def _alias_event(view: AliasEventView, profile: ProviderProfile, ids: _Ids) -> str:
    """One alias event: heading, a sentence per leaf, match evidence and ladders."""
    parts = [
        f'<article class="alias-event" data-kind="{_h(view.kind)}">'
        '<div class="alias-event-header">'
        f'<span class="alias-event-title">{_h(view.title)}</span> '
        f'<span class="alias-event-heading">{_with_code(lambda quote: alias_event_heading(view, quote))}</span>'
        "</div>"
    ]
    reason = alias_event_reason(view)
    if reason:
        parts.append(f'<div class="alias-event-reason">{_h(_capitalized(reason))}</div>')
    if view.leaves:
        items = []
        for leaf in view.leaves:
            sentence = alias_leaf_sentence(leaf, view.kind, raw_first=False)
            lead = f"{leaf.label}: "
            if sentence.startswith(lead):
                body = (
                    f'<span class="alias-leaf-label">{_h(leaf.label)}</span>: '
                    f"{_h(sentence[len(lead):])}"
                )
            else:
                body = _h(sentence)
            items.append(f"<li>{body}</li>")
        parts.append(f'<ul class="alias-leaves">{"".join(items)}</ul>')
    if alias_match_sentence(view) is not None:
        match = _with_code(lambda quote: alias_match_sentence(view, quote) or "")
        parts.append(f'<div class="alias-match">{match}</div>')
    if view.unavailable_leaves:
        items = "".join(f"<li>{_h(alias_unavailable_leaf_sentence(leaf))}</li>" for leaf in view.unavailable_leaves)
        parts.append(f'<ul class="alias-unavailable">{items}</ul>')
    parts.extend(_alias_ladders(view, profile, ids))
    parts.append("</article>")
    return "".join(parts)


def _alias_ladders(view: AliasEventView, profile: ProviderProfile, ids: _Ids) -> list[str]:
    """A ladder per displayed divergent leaf, when the target's list has endpoints."""
    if view.kind not in _LADDER_KINDS or view.target_list is None:
        return []
    return [
        _ladder_figure(ladder, view.target_list.display_id, ids)
        for ladder in alias_ladders(view.leaves, view.target_list, profile)
    ]


# ---------------------------------------------------------------------------
# Price ladders
# ---------------------------------------------------------------------------

# Layout in SVG user units (= CSS px, because the SVG is drawn at its own size
# and scrolls inside its figure on a narrow viewport rather than shrinking its
# labels into illegibility). Label widths are estimated from a monospace
# advance a little wider than the report fonts' 0.6em, so an estimate can only
# reserve too much room, never too little.
_LADDER_FONT_PX: Final = 11
_LADDER_CHAR_PX: Final = 7.0
_LADDER_ROW_PX: Final = 15
_LADDER_MIN_WIDTH: Final = 720
_LADDER_EDGE: Final = 12
_LADDER_AXIS_INSET: Final = 28
_LADDER_LABEL_GAP: Final = 8
_LADDER_LABEL_PAD: Final = 4

_UNPLACED_TEXT: Final = {
    UNPLACED_MISSING: "no {label} price",
    UNPLACED_INVALID: "not a valid price",
    UNPLACED_INCOMPATIBLE: "a different unit",
}


@dataclass(frozen=True)
class LadderLabel:
    """One placed label: its box (top-left to bottom-right), text and anchor point.

    `kind` is `endpoint` or `mark` and `name` the entry's label (an endpoint
    key, `target` or `alias`); `point_x` is the position it labels.
    """

    kind: str
    name: str
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    point_x: float
    baseline: float


@dataclass(frozen=True)
class LadderLayout:
    """Where everything on one ladder SVG goes. Positions come from the Ladder."""

    width: float
    height: float
    axis_y: float
    axis_x0: float
    axis_x1: float
    alias_lane_y: float
    target_lane_y: float
    domain_baseline: float
    points: tuple[tuple[float, int], ...]   # (x, index into ladder.positions)
    labels: tuple[LadderLabel, ...]


def _label_width(text: str) -> float:
    return len(text) * _LADDER_CHAR_PX + _LADDER_LABEL_PAD


def _assign_rows(
    items: Sequence[tuple[str, str, str, float]], width: float
) -> list[tuple[int, float, float, str, str, str, float]]:
    """First-fit collision rows: (row, x0, x1, kind, name, text, point_x) per label.

    A label starts just left of its point, or ends just right of it when that
    would cross the right edge; it is then clamped inside the edges. Labels in
    one row never overlap, so coincident and crowded positions stack.
    """
    rows: list[list[tuple[float, float]]] = []
    placed = []
    for kind, name, text, x in sorted(items, key=lambda item: item[3]):
        span = _label_width(text)
        x0 = x - 3
        if x0 + span > width - _LADDER_EDGE:
            x0 = x + 3 - span
        x0 = min(max(x0, _LADDER_EDGE), width - _LADDER_EDGE - span)
        x1 = x0 + span
        for index, occupied in enumerate(rows):
            if all(x1 + _LADDER_LABEL_GAP <= left or x0 >= right + _LADDER_LABEL_GAP for left, right in occupied):
                occupied.append((x0, x1))
                row = index
                break
        else:
            rows.append([(x0, x1)])
            row = len(rows) - 1
        placed.append((row, x0, x1, kind, name, text, x))
    return placed


def layout_ladder(ladder: Ladder) -> LadderLayout:
    """Lay out a ladder's labels in collision rows, sized to fit every label.

    Mark labels (target, alias) sit in rows above the axis, over the two mark
    lanes; endpoint labels sit in rows below it. The SVG is widened when the
    longest label would not fit the minimum width.
    """
    entries: list[tuple[str, str, str, int]] = []
    for index, position in enumerate(ladder.positions):
        for entry in position.entries:
            entries.append((entry.kind, entry.label, f"{entry.label} {position.display}", index))
    longest = max((_label_width(text) for _, _, text, _ in entries), default=0.0)
    width = max(float(_LADDER_MIN_WIDTH), math.ceil(longest + 2 * (_LADDER_EDGE + _LADDER_AXIS_INSET)))
    axis_x0 = _LADDER_EDGE + _LADDER_AXIS_INSET
    axis_x1 = width - _LADDER_EDGE - _LADDER_AXIS_INSET

    def x_of(index: int) -> float:
        return axis_x0 + ladder.positions[index].position * (axis_x1 - axis_x0)

    marks = _assign_rows([(k, n, t, x_of(i)) for k, n, t, i in entries if k != LADDER_ENDPOINT], width)
    endpoints = _assign_rows([(k, n, t, x_of(i)) for k, n, t, i in entries if k == LADDER_ENDPOINT], width)
    mark_rows = 1 + max((row for row, *_ in marks), default=0)
    endpoint_rows = 1 + max((row for row, *_ in endpoints), default=-1)

    top = 4.0
    mark_bottom = top + mark_rows * _LADDER_ROW_PX
    alias_lane_y = mark_bottom + 7
    target_lane_y = mark_bottom + 19
    axis_y = mark_bottom + 31
    endpoint_top = axis_y + 9
    domain_baseline = endpoint_top + endpoint_rows * _LADDER_ROW_PX + _LADDER_ROW_PX - 3
    height = domain_baseline + 6

    labels = []
    for row, x0, x1, kind, name, text, point_x in marks:
        # Row 0 is the row nearest the axis.
        row_top = mark_bottom - (row + 1) * _LADDER_ROW_PX
        labels.append(LadderLabel(kind, name, text, x0, row_top, x1, row_top + _LADDER_ROW_PX, point_x, row_top + 11))
    for row, x0, x1, kind, name, text, point_x in endpoints:
        row_top = endpoint_top + row * _LADDER_ROW_PX
        labels.append(LadderLabel(kind, name, text, x0, row_top, x1, row_top + _LADDER_ROW_PX, point_x, row_top + 11))
    points = tuple((x_of(index), index) for index in range(len(ladder.positions)))
    return LadderLayout(
        width=width,
        height=height,
        axis_y=axis_y,
        axis_x0=axis_x0,
        axis_x1=axis_x1,
        alias_lane_y=alias_lane_y,
        target_lane_y=target_lane_y,
        domain_baseline=domain_baseline,
        points=points,
        labels=tuple(labels),
    )


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _join_words(words: Sequence[str]) -> str:
    if len(words) <= 2:
        return " and ".join(words)
    return ", ".join(words[:-1]) + f" and {words[-1]}"


def _position_text(entries: Iterable) -> str:
    """`endpoints a#0 and b#0; alias price` for one ladder position."""
    entries = tuple(entries)
    keys = [entry.label for entry in entries if entry.kind == LADDER_ENDPOINT]
    parts = []
    if keys:
        parts.append(f"{'endpoint' if len(keys) == 1 else 'endpoints'} {_join_words(keys)}")
    parts.extend(f"{entry.label} price" for entry in entries if entry.kind != LADDER_ENDPOINT)
    return "; ".join(parts)


def _unplaced_text(ladder: Ladder) -> str:
    items = []
    for item in ladder.unplaced:
        if item.reason in (UNPLACED_ZERO, UNPLACED_NEGATIVE) and item.display:
            detail = item.display
        else:
            detail = _UNPLACED_TEXT.get(item.reason, item.reason).format(label=ladder.label)
        name = item.label if item.kind == LADDER_ENDPOINT else f"{item.label} price"
        items.append(f"{name} ({detail})")
    return ", ".join(items)


def _ladder_figure(ladder: Ladder, list_display_id: str, ids: _Ids) -> str:
    """The SVG ladder with an accessible title and an equivalent text list."""
    figure_id = ids.next("ladder")
    title_id, text_id = f"{figure_id}-title", f"{figure_id}-text"
    layout = layout_ladder(ladder)
    title = (
        f"{ladder.label} price ladder: endpoints of {list_display_id} with the alias and target prices,"
        f" {ladder.unit_label}, log scale"
    )
    svg = [
        f'<svg class="ladder-svg" xmlns="http://www.w3.org/2000/svg" role="img"'
        f' aria-labelledby="{title_id}" aria-describedby="{text_id}"'
        f' width="{_fmt(layout.width)}" height="{_fmt(layout.height)}"'
        f' viewBox="0 0 {_fmt(layout.width)} {_fmt(layout.height)}">'
        f'<title id="{title_id}">{_h(title)}</title>'
        f'<line class="ladder-axis" x1="{_fmt(layout.axis_x0)}" y1="{_fmt(layout.axis_y)}"'
        f' x2="{_fmt(layout.axis_x1)}" y2="{_fmt(layout.axis_y)}"/>'
    ]
    # Leaders first, so the labels' background stroke masks any they cross.
    for label in layout.labels:
        if label.kind == LADDER_ENDPOINT:
            y_from, y_to = layout.axis_y + 5, label.y0 + 2
        else:
            lane = layout.alias_lane_y if label.name == "alias" else layout.target_lane_y
            y_from, y_to = label.y1 - 2, lane - 5
        if y_to - y_from > 2 or y_from - y_to > 2:
            svg.append(
                f'<line class="ladder-leader" x1="{_fmt(label.point_x)}" y1="{_fmt(y_from)}"'
                f' x2="{_fmt(label.point_x)}" y2="{_fmt(y_to)}"/>'
            )
    for x, index in layout.points:
        position = ladder.positions[index]
        tooltip = f"{position.display} {ladder.unit_label}: {_position_text(position.entries)}"
        glyphs = []
        if any(entry.kind == LADDER_ENDPOINT for entry in position.entries):
            glyphs.append(f'<circle class="ladder-endpoint" cx="{_fmt(x)}" cy="{_fmt(layout.axis_y)}" r="4"/>')
        for entry in position.entries:
            if entry.kind == LADDER_ENDPOINT:
                continue
            if entry.label == "alias":
                y = layout.alias_lane_y
                glyphs.append(
                    f'<path class="ladder-mark ladder-mark-alias"'
                    f' d="M{_fmt(x - 5)} {_fmt(y - 4)}H{_fmt(x + 5)}L{_fmt(x)} {_fmt(y + 4)}Z"/>'
                )
            else:
                y = layout.target_lane_y
                glyphs.append(
                    f'<path class="ladder-mark ladder-mark-target"'
                    f' d="M{_fmt(x)} {_fmt(y - 5)}L{_fmt(x + 5)} {_fmt(y)}L{_fmt(x)} {_fmt(y + 5)}L{_fmt(x - 5)} {_fmt(y)}Z"/>'
                )
        svg.append(f'<g class="ladder-point"><title>{_h(tooltip)}</title>{"".join(glyphs)}</g>')
    for label in layout.labels:
        css = "ladder-label ladder-label-endpoint" if label.kind == LADDER_ENDPOINT else "ladder-label ladder-label-mark"
        svg.append(
            f'<text class="{css}" x="{_fmt(label.x0 + _LADDER_LABEL_PAD / 2)}"'
            f' y="{_fmt(label.baseline)}">{_h(label.text)}</text>'
        )
    if len(ladder.positions) > 1:
        middle = (layout.axis_x0 + layout.axis_x1) / 2
        svg.append(
            f'<text class="ladder-domain" x="{_fmt(layout.axis_x0)}" y="{_fmt(layout.domain_baseline)}">'
            f"low {_h(ladder.domain_min_display)}</text>"
            f'<text class="ladder-domain" x="{_fmt(middle)}" y="{_fmt(layout.domain_baseline)}"'
            ' text-anchor="middle">log scale</text>'
            f'<text class="ladder-domain" x="{_fmt(layout.axis_x1)}" y="{_fmt(layout.domain_baseline)}"'
            f' text-anchor="end">high {_h(ladder.domain_max_display)}</text>'
        )
    svg.append("</svg>")

    items = "".join(
        f"<li>{_h(position.display)}: {_h(_position_text(position.entries))}</li>"
        for position in ladder.positions
    )
    unplaced = (
        f'<p class="ladder-unplaced">Not placed: {_h(_unplaced_text(ladder))}</p>' if ladder.unplaced else ""
    )
    return (
        f'<figure class="price-ladder" id="{figure_id}">'
        f'<div class="ladder-scroll">{"".join(svg)}</div>'
        f'<figcaption class="ladder-text" id="{text_id}">'
        f'<span class="ladder-text-lead">{_h(ladder.label)} {_h(ladder.unit_label)}, low to high:</span>'
        f"<ol>{items}</ol>{unplaced}</figcaption></figure>"
    )


# ---------------------------------------------------------------------------
# Provider endpoints disclosure
# ---------------------------------------------------------------------------

_ROW_CHANGE_TEXT: Final = {
    "up": ("↑ higher", "sem-cost-up"),
    "down": ("↓ lower", "sem-cost-down"),
    "mixed": ("↕ mixed", "ep-mixed"),
    "coverage": ("price added/removed", "sem-coverage"),
    "added": ("endpoint added", "sem-coverage"),
    "removed": ("endpoint removed", "sem-coverage"),
}


def _report_summary(report: ProviderEndpointReport) -> str:
    if report.summary_clauses:
        return " · ".join(report.summary_clauses)
    if report.no_change_line:
        return report.no_change_line
    return f"capture {report.capture.status}" if report.capture is not None else report.capture_line


def _endpoint_disclosure(
    reports: Sequence[ProviderEndpointReport],
    profiles: Mapping[str, ProviderProfile],
    ids: _Ids,
    companion_link: tuple[str, str] | None,
) -> str:
    """The closed `Provider endpoints` disclosure, its summary from uncapped data."""
    if not reports:
        return ""
    if len(reports) == 1:
        summary = _report_summary(reports[0])
    else:
        summary = "; ".join(f"{report.provider_label}: {_report_summary(report)}" for report in reports)
    parts = [
        f'<details class="endpoint-disclosure" id="{PROVIDER_ENDPOINTS_ANCHOR}">'
        f"<summary>Provider endpoints — {_h(summary)}</summary>"
    ]
    if companion_link is not None and all(report.full_detail for report in reports):
        parts.append(f'<p class="endpoint-back">{_nav_link(companion_link)}</p>')
    for report in reports:
        parts.append(_endpoint_provider(report, profiles[report.provider_id], ids, companion_link))
    parts.append("</details>")
    return "".join(parts)


def _endpoint_provider(
    report: ProviderEndpointReport,
    profile: ProviderProfile,
    ids: _Ids,
    companion_link: tuple[str, str] | None,
) -> str:
    facts = [("Capture", report.capture_line)]
    if report.persistence_error:
        facts.append(("Not saved", report.persistence_error))
    if report.baseline_line:
        facts.append(("Baseline", report.baseline_line))
    parts = [
        f'<section class="endpoint-provider" aria-label="{_h(report.provider_label)} provider endpoints">',
        _provider_name(report.provider_label, report.provider_id, "endpoint-provider-name"),
        '<dl class="endpoint-facts">'
        + "".join(f"<dt>{_h(label)}</dt><dd>{_h(value)}</dd>" for label, value in facts)
        + "</dl>",
    ]
    if report.no_change_line:
        parts.append(f'<p class="endpoint-no-change">{_h(_capitalized(report.no_change_line))}</p>')
    parts.extend(_alias_event(view, profile, ids) for view in report.persisting)
    parts.extend(_endpoint_list(listing, profile, full_detail=report.full_detail) for listing in report.lists)
    forward = companion_link is not None and not report.full_detail
    for count, phrase, pronoun_text in (
        (report.omitted_list_count, omitted_lists_phrase, "every list"),
        (
            report.detail_only_list_count,
            detail_only_lists_phrase,
            "it" if report.detail_only_list_count == 1 else "them",
        ),
    ):
        if not count:
            continue
        if forward:
            body = f"{_h(phrase(count))} — {_nav_link(companion_link)}"
        else:
            body = (
                f"{_h(phrase(count))}; the full-detail report (<code>--detail all</code>)"
                f" shows {_h(pronoun_text)}"
            )
        parts.append(f'<p class="endpoint-omitted">{body}</p>')
    if report.gaps:
        items = "".join(
            "<li>"
            + _with_code(
                lambda quote, gap=gap: quote(gap.list_path)
                + (
                    f" (from {quote(gap.from_list_path)})"
                    if gap.from_list_path is not None and gap.from_list_path != gap.list_path
                    else ""
                )
                + f": {gap.description}"
            )
            + "</li>"
            for gap in report.gaps
        )
        parts.append(_evidence("endpoint-gaps", "Comparison gaps", items))
    if report.failed_lists:
        items = "".join(
            f"<li><code>{_h(listing.list_path)}</code>: {_h(str(listing.error_code))}: {_h(str(listing.error_message))}</li>"
            for listing in report.failed_lists
        )
        parts.append(_evidence("endpoint-failed-lists", "Failed lists", items))
    parts.append("</section>")
    return "".join(parts)


def _evidence(css_class: str, title: str, items: str) -> str:
    return (
        f'<div class="endpoint-evidence {css_class}">'
        f'<div class="endpoint-evidence-title">{_h(title)}</div><ul>{items}</ul></div>'
    )


def _endpoint_list(listing: EndpointListView, profile: ProviderProfile, *, full_detail: bool) -> str:
    heading = _with_code(lambda quote: f"List {endpoint_list_heading(listing, quote)}")
    parts = [f'<article class="endpoint-list"><div class="endpoint-list-heading">{heading}</div>']
    if listing.price_rows:
        parts.append(_price_table(listing, profile))
    if listing.conditional_rows:
        items = []
        for row in listing.conditional_rows:
            evidence = ""
            if full_detail:
                evidence = "".join(
                    f'<div class="ep-json"><span class="ep-json-label">{label}</span>'
                    f" <code>{_h(canonical_json(value))}</code></div>"
                    for label, value in (("Old", row.change.old_value), ("New", row.change.new_value))
                )
            items.append(f"<li><code>{_h(row.endpoint_key)}</code> {_h(row.label)}{evidence}</li>")
        parts.append(f'<ul class="endpoint-conditional">{"".join(items)}</ul>')
    field_rows = [row for row in (*listing.metadata_rows, *listing.status_rows) if row.rendered is not None]
    if field_rows:
        rows = []
        previous_key = None
        for index, row in enumerate(field_rows):
            rows.append(
                _render_html_card_row(
                    row.rendered,
                    category=row.endpoint_key if row.endpoint_key != previous_key else None,
                    alternate=index % 2 == 1,
                )
            )
            previous_key = row.endpoint_key
        parts.append(
            '<div class="endpoint-field-wrap"><table class="card-table endpoint-field-table">'
            f"{_CARD_TABLE_COLGROUP}<tbody>\n" + "\n".join(rows) + "\n</tbody></table></div>"
        )
    parts.append("</article>")
    return "".join(parts)


def _price_table(listing: EndpointListView, profile: ProviderProfile) -> str:
    """Provider tag, one column per resolved price leaf (unit in its header), change."""
    header = (
        '<th scope="col" class="ep-key-col">Endpoint</th>'
        + "".join(
            f'<th scope="col" class="ep-price-col">{_h(column.label)}'
            f' <span class="ep-unit">{_h(column.unit_label)}</span></th>'
            for column in listing.price_columns
        )
        + '<th scope="col" class="ep-change-col">Change</th>'
    )
    rows = [_price_row(row, listing.price_columns, profile) for row in listing.price_rows]
    return (
        '<div class="endpoint-table-wrap"><table class="endpoint-price-table">'
        f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _price_row(row: EndpointPriceRow, columns: Sequence[EndpointPriceColumn], profile: ProviderProfile) -> str:
    text, css = _ROW_CHANGE_TEXT.get(row.direction, (row.direction, "sem-neutral"))
    cells = "".join(_price_cell(cell, column, profile) for cell, column in zip(row.cells, columns))
    return (
        f'<tr data-change="{_h(row.change_kind)}">'
        f'<th scope="row" class="ep-key"><code>{_h(row.endpoint_key)}</code></th>'
        f'{cells}<td class="ep-change {css}">{_h(text)}</td></tr>'
    )


def _raw_text(raw: object) -> str | None:
    return None if raw is None else str(raw)


def _price_cell(cell: EndpointPriceCell | None, column: EndpointPriceColumn, profile: ProviderProfile) -> str:
    """A normalized price with its raw evidence (derivation tooltip and raw line)."""
    if cell is None:
        return f'<td class="ep-price num ep-empty">{ABSENT_DISPLAY}</td>'
    rendered = cell.rendered
    rule = rendered.price_rule if rendered is not None else resolve_price_rule(column.path, profile)
    old_raw, new_raw = _raw_text(cell.old_raw), _raw_text(cell.new_raw)
    if rendered is not None:
        value = (
            f"{absent_side_display(rendered.old_display, rendered.old_raw)}"
            f" → {absent_side_display(rendered.new_display, rendered.new_raw)}"
        )
        raw_line = f"{absent_side_display(old_raw or '', old_raw)} → {absent_side_display(new_raw or '', new_raw)}"
        derivations = [
            f"{side}: {_raw_price_derivation(raw, display, rule)}"
            for side, raw, display in (
                ("old", old_raw, rendered.old_display),
                ("new", new_raw, rendered.new_display),
            )
            if raw is not None
        ]
        css = f" {_card_semantic_class(rendered)}"
    else:
        raw = new_raw if new_raw is not None else old_raw
        display = cell.new_display if cell.new_display is not None else cell.old_display
        value = display or ABSENT_DISPLAY
        raw_line = raw or ""
        derivations = [_raw_price_derivation(raw, display, rule)] if raw is not None and display else []
        css = ""
    title = f' title="{_h(chr(10).join(derivations))}"' if derivations else ""
    return (
        f'<td class="ep-price num{css}"{title}><span class="ep-value">{_h(value)}</span>'
        f'<span class="ep-raw">{_h(raw_line)}</span></td>'
    )


ENDPOINT_HTML_CSS: Final = """\
.alias-check {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 2rem;
}
.alias-check-title {
  font-family: var(--font-mono);
  color: var(--text-bright);
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.alias-provider,
.endpoint-provider-name {
  margin-top: 0.5rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.78rem;
}
.alias-check .alias-provider code,
.endpoint-disclosure .endpoint-provider-name code { color: var(--text-dim); }
.alias-event {
  border-top: 1px solid var(--border);
  padding: 0.65rem 0;
  margin-top: 0.4rem;
}
.alias-event-header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.2rem 0.65rem;
}
.alias-event-title {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.alias-event-heading,
.alias-leaves,
.alias-match,
.alias-event-reason,
.alias-unavailable {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}
.alias-event-heading code,
.alias-match code,
.endpoint-disclosure code {
  font-family: var(--font-mono);
  color: var(--text-bright);
  overflow-wrap: anywhere;
}
.alias-leaves,
.alias-unavailable { list-style: none; margin-top: 0.35rem; }
.alias-leaves li { padding: 0.1rem 0; }
.alias-leaf-label { color: var(--text-bright); font-weight: 600; }
.alias-match,
.alias-event-reason,
.alias-unavailable { color: var(--text-dim); margin-top: 0.3rem; }
.price-ladder { margin-top: 0.6rem; }
.ladder-scroll { max-width: 100%; overflow-x: auto; }
.ladder-svg {
  display: block;
  font-family: var(--font-mono);
  font-size: 11px;
}
.ladder-axis { stroke: var(--border-accent); stroke-width: 1.5; }
.ladder-leader { stroke: var(--border-accent); stroke-width: 1; }
.ladder-endpoint { fill: var(--text-dim); }
.ladder-mark-target { fill: none; stroke: var(--text-bright); stroke-width: 1.5; }
.ladder-mark-alias { fill: var(--text-bright); }
.ladder-label {
  fill: var(--text);
  paint-order: stroke;
  stroke: var(--bg-card);
  stroke-width: 3px;
  stroke-linejoin: round;
}
.ladder-label-mark { fill: var(--text-bright); }
.ladder-domain { fill: var(--text-dim); }
.ladder-text {
  margin-top: 0.35rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.74rem;
  overflow-wrap: anywhere;
}
.ladder-text ol { margin: 0.2rem 0 0 1.4rem; }
.endpoint-disclosure {
  margin-top: 2.5rem;
  border-top: 1px solid var(--border);
  padding-top: 1.5rem;
}
.endpoint-disclosure > summary {
  cursor: pointer;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.9rem;
  font-weight: 600;
}
.endpoint-disclosure > summary:hover,
.endpoint-disclosure:target > summary { color: var(--text-bright); }
.endpoint-provider { margin-top: 1rem; }
.endpoint-provider .alias-event {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.65rem 1rem;
  margin-top: 1rem;
}
.endpoint-facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 0.15rem 0.9rem;
  margin-top: 0.4rem;
  font-family: var(--font-mono);
  font-size: 0.78rem;
}
.endpoint-facts dt {
  color: var(--text-dim);
  font-size: 0.68rem;
  letter-spacing: 0.06em;
  padding-top: 0.12rem;
  text-transform: uppercase;
}
.endpoint-facts dd { overflow-wrap: anywhere; }
.endpoint-no-change,
.endpoint-omitted,
.endpoint-back {
  margin-top: 0.75rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.78rem;
}
.endpoint-nav { color: var(--text-dim); text-decoration: none; }
.endpoint-nav:hover { color: var(--text-bright); }
.endpoint-list {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-top: 1rem;
  overflow: hidden;
}
.endpoint-list-heading {
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-card-hover);
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}
.endpoint-list-heading code { color: var(--accent-amber); font-weight: 600; }
.endpoint-table-wrap,
.endpoint-field-wrap { padding: 0.5rem 1rem; overflow-x: auto; }
.endpoint-field-wrap { border-top: 1px solid var(--border); }
.endpoint-price-table {
  width: auto;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
.endpoint-price-table th,
.endpoint-price-table td {
  padding: 0.35rem 0.5rem;
  text-align: right;
  vertical-align: top;
}
.endpoint-price-table thead th {
  color: var(--text-dim);
  font-size: 0.72rem;
  font-weight: 600;
  border-bottom: 1px solid var(--border-accent);
  white-space: nowrap;
}
.endpoint-price-table tbody tr:nth-child(even) > * { background: var(--bg-table-alt); }
.endpoint-price-table th.ep-key-col,
.endpoint-price-table th.ep-key,
.endpoint-price-table th.ep-change-col,
.endpoint-price-table td.ep-change { text-align: left; }
.endpoint-price-table th.ep-key { font-weight: 400; white-space: nowrap; }
.endpoint-price-table th.ep-key code { color: var(--text); }
.ep-unit { display: block; font-size: 0.65rem; font-weight: 400; }
.endpoint-price-table td.ep-price {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.endpoint-price-table td.ep-change { font-weight: 600; white-space: nowrap; }
td.ep-empty { color: var(--text-dim); }
td.ep-mixed { color: var(--accent-amber); }
.ep-raw {
  display: none;
  color: var(--text-dim);
  font-size: 0.72rem;
  font-weight: 400;
  user-select: text;
}
body:has(#show-raw:checked) .ep-raw { display: block; }
.endpoint-field-table td.cat-chip {
  color: var(--text);
  font-size: 0.78rem;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  white-space: nowrap;
}
.endpoint-conditional {
  list-style: none;
  padding: 0.5rem 1rem;
  border-top: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.endpoint-conditional li { padding: 0.15rem 0; }
.ep-json {
  margin: 0.2rem 0 0 1rem;
  color: var(--text-dim);
  font-size: 0.74rem;
  overflow-wrap: anywhere;
}
.ep-json code { user-select: text; }
.ep-json-label { text-transform: uppercase; font-size: 0.66rem; letter-spacing: 0.06em; }
.endpoint-evidence {
  margin-top: 1rem;
  font-family: var(--font-mono);
  font-size: 0.78rem;
}
.endpoint-evidence-title {
  color: var(--text-dim);
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.endpoint-evidence ul { list-style: none; margin-top: 0.3rem; }
.endpoint-evidence li { padding: 0.1rem 0; overflow-wrap: anywhere; }"""
