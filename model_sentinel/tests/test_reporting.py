import json
import re

from tests.html_probe import absent_side_cells

from model_sentinel import reporting
from model_sentinel.change_render import (
    classify_change,
    format_qualified_label,
    resolve_field_label,
)
from model_sentinel.models import FieldChange, HistoryEvent, ModelDelta, ProviderScanResult
from model_sentinel.reporting import (
    DEFAULT_REPORT_SHOW_FIELDS,
    ReportDetailPolicy,
    _list_change_signature,
    make_report_detail_policy,
    render_changes_report,
    render_history_report,
    render_scan_report,
)


def _scan_result(
    changed: tuple[ModelDelta, ...],
    *,
    provider_id: str = "openrouter",
    provider_label: str = "OpenRouter",
    status: str = "success",
    error_message: str | None = None,
) -> ProviderScanResult:
    return ProviderScanResult(
        provider_id=provider_id,
        provider_label=provider_label,
        status=status,
        current_count=2,
        saved=False,
        baseline=None,
        baseline_message=None,
        scrape_id=None,
        added=(),
        removed=(),
        changed=changed,
        error_message=error_message,
        price_multiplier=1000000,
        price_divisor=1,
    )


def _card_rows(html: str) -> list[str]:
    """Every `<tr>` of a scan report's model-card tables, in document order.

    Matched on the `field-name` cell that only a card row carries, so the
    Change Summary's rows (plain `<td>`s) and the provider/price-movement
    markup cannot be mistaken for card rows.
    """
    return [
        row
        for row in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S)
        if 'class="field-name"' in row
    ]


def _card_row(html: str, label: str) -> str:
    """THE model-card row whose field cell renders exactly `label`.

    Fails when the label matches no row or more than one: a helper that
    silently returned the first of several would let an assertion about "the
    Output row" pass while pointing at a row the test's author never saw.
    """
    matches = [row for row in _card_rows(html) if f">{label}</td>" in row]
    assert len(matches) == 1, f"expected exactly one {label!r} card row, got {len(matches)}"
    return matches[0]


_PRICE_MOVEMENT_OPEN = '<section class="price-movement-summary">'


def _price_movement_card(html: str) -> str:
    """THE Price Movement card's inner HTML.

    One spelling of the split, because five tests were each carrying their own
    copy of it. Fails loudly when the card is absent or duplicated rather than
    raising `IndexError` from inside a test that reads as though it had a card.
    """
    occurrences = html.count(_PRICE_MOVEMENT_OPEN)
    assert occurrences == 1, f"expected exactly one Price Movement card, got {occurrences}"
    return html.split(_PRICE_MOVEMENT_OPEN, 1)[1].split("</section>", 1)[0]


def _without_price_movement_card(html: str) -> str:
    """`html` with the Price Movement card excised, for document-wide counts.

    The card is a SUMMARY: it repeats figures and labels that also appear on
    the model cards below it, so a count taken over the whole document counts
    some rows twice. Returns `html` unchanged when there is no card.
    """
    if _PRICE_MOVEMENT_OPEN not in html:
        return html
    before, rest = html.split(_PRICE_MOVEMENT_OPEN, 1)
    return before + rest.split("</section>", 1)[1]


def _html_section_body(html: str, heading: str) -> str:
    """Return what `heading` actually presides over, up to its `</section>`.

    Asserting `f"{heading}\\n</section>"` is absent cannot fail. Both HTML
    renderers assemble a section as
    `'<section ...>' + "\\n".join(parts) + '</section>'`, so `</section>` is
    never preceded by a newline in ANY output -- bare heading or full body.
    Split on the heading and inspect what follows instead, which is the shape
    the markdown assertions in this module already use.

    `str.split` takes the FIRST match, so a `heading` present more than once
    would silently narrow the returned body to whichever section happens to come
    first while the assertion still reads as though it covered "the" section.
    `"</h2>"` is exactly that hazard: every provider section's heading ends with
    it, and so does `Change Summary`. Refuse the ambiguity here rather than
    leaving a comment at each call site -- callers must pass a heading that
    identifies exactly one place in the document.
    """
    occurrences = html.count(heading)
    assert occurrences, f"{heading} missing from rendered output"
    assert occurrences == 1, (
        f"{heading} matches {occurrences} places in this document, so the body "
        "returned here would be only the first one's. Pass a heading unique to "
        "the section under test."
    )
    return html.split(heading, 1)[1].split("</section>", 1)[0].strip()


def _scan_html_provider_sections(html: str) -> list[str]:
    """Every SCAN-report provider section body, in document order.

    Scoped to the scan report on purpose. `provider-section` is not a
    scan-only class: `_render_changes_html` wraps each of its *date* sections
    in the very same class, so pointing this helper at a `changes` report
    would return date bodies while every name here still said "provider".
    The changes renderer is the only one that emits `<h2 class="date-heading">`,
    so refuse that document outright rather than quietly answering the wrong
    question.
    """
    assert '<h2 class="date-heading">' not in html, (
        "this is a changes report -- its `provider-section` elements are DATE "
        "sections, not provider sections. Split on `<h3>` instead."
    )
    return [
        chunk.split("</section>", 1)[0]
        for chunk in html.split('<section class="provider-section">')[1:]
    ]


# F1 split the concise scan report into two tiers. Both landmarks are spelled
# once here because a dozen tests below split the document on them.
_SECONDARY_OPEN = '<details class="secondary-changes">'
_SCAN_SUMMARY_OPEN = '<details class="summary-section">'


def _scan_detail_and_summary(html: str) -> tuple[str, str]:
    """A scan report split into "everything above the Change Summary" and it.

    The split used to be `html.split("<h2>Change Summary</h2>")`, spelled at
    each call site. E6 turned that heading into a `<summary>` inside a closed
    `<details>`, so the landmark moved; naming it here means the next move is
    one edit rather than a dozen, and the assertion below makes a document that
    has no Change Summary at all fail by name instead of by `IndexError`.
    """
    occurrences = html.count(_SCAN_SUMMARY_OPEN)
    assert occurrences == 1, f"expected exactly one Change Summary, got {occurrences}"
    detail, summary = html.split(_SCAN_SUMMARY_OPEN, 1)
    return detail, summary


def _scan_tiers(html: str) -> tuple[str, str]:
    """A scan report split at F1's disclosure: (tier 1, tier 2).

    Tier 2 includes the Change Summary, which lives inside the same
    `<details>`. Returns an empty tier 2 when the report has no disclosure.
    """
    if _SECONDARY_OPEN not in html:
        return html, ""
    primary, secondary = html.split(_SECONDARY_OPEN, 1)
    return primary, secondary


def _model_card_order(html: str) -> list[str]:
    """Every model-card headline id in document order.

    Reads the `<code>` that opens a card header, so it picks up the
    provider-level rollup pseudo-cards (`squelched`, `no-op`) too -- callers
    that care about real models scope the html they pass in.
    """
    return re.findall(r'<div class="model-card-header"><code>([^<]*)</code>', html)


def _bulk_parameter_changes() -> tuple[ModelDelta, ...]:
    return (
        ModelDelta(
            "changed",
            "alpha",
            "Alpha",
            (FieldChange("supported_parameters", ["tools"], ["tools", "reasoning_effort"]),),
        ),
        ModelDelta(
            "changed",
            "beta",
            "Beta",
            (
                FieldChange("supported_parameters", ["tools", "vision"], ["tools", "vision", "reasoning_effort"]),
                FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),
            ),
        ),
        ModelDelta(
            "changed",
            "gamma",
            "Gamma",
            (
                FieldChange("supported_parameters", ["audio", "tools", "vision"], ["audio", "tools", "vision", "reasoning_effort"]),
                FieldChange("benchmarks.design_arena", [{"elo": 3}], [{"elo": 4}]),
            ),
        ),
        ModelDelta(
            "changed",
            "priced-model",
            "Priced Model",
            (
                FieldChange("supported_parameters", ["tools"], ["tools", "reasoning_effort"]),
                FieldChange("pricing.prompt", "0.000001", "0.000002"),
            ),
        ),
    )


def test_scan_report_summarizes_benchmarks_by_default() -> None:
    report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[
            _scan_result(
                (
                    ModelDelta(
                        "changed",
                        "alpha",
                        "Alpha",
                        (
                            FieldChange("benchmarks.artificial_analysis.intelligence_index", 50, 55),
                            FieldChange("metadata.owner", "old", "new"),
                        ),
                    ),
                )
            )
        ],
    )

    assert "squelched: 1 field change across 1 model" in report
    assert "Intelligence index" not in report
    assert "[Unclassified]" in report
    assert "Owner: old \u2192 new" in report


def test_scan_report_all_detail_shows_benchmark_fields() -> None:
    report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[
            _scan_result(
                (
                    ModelDelta(
                        "changed",
                        "alpha",
                        "Alpha",
                        (
                            FieldChange("benchmarks.artificial_analysis.intelligence_index", 50, 55),
                            FieldChange("metadata.owner", "old", "new"),
                        ),
                    ),
                )
            )
        ],
        detail_policy=ReportDetailPolicy(
            mode="all",
            show_fields=DEFAULT_REPORT_SHOW_FIELDS,
            squelch_fields=("benchmarks", "benchmarks.*"),
            unclassified_limit=20,
        ),
    )

    assert "[Benchmarks]" in report
    assert "Intelligence index" in report


def test_scan_report_squelched_detail_only_shows_squelched_fields() -> None:
    report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[
            _scan_result(
                (
                    ModelDelta(
                        "changed",
                        "alpha",
                        "Alpha",
                        (
                            FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),
                            FieldChange("metadata.owner", "old", "new"),
                        ),
                    ),
                )
            )
        ],
        detail_policy=ReportDetailPolicy(
            mode="squelched",
            show_fields=DEFAULT_REPORT_SHOW_FIELDS,
            squelch_fields=("benchmarks", "benchmarks.*"),
            unclassified_limit=20,
        ),
    )

    assert "Design arena" in report
    assert "Owner: old" not in report
    assert "non-squelched" in report


def test_scan_report_unknown_fields_render_by_default_and_cap_overflow() -> None:
    report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[
            _scan_result(
                (
                    ModelDelta(
                        "changed",
                        "alpha",
                        "Alpha",
                        (
                            FieldChange("new_payload.a", "old", "new"),
                            FieldChange("new_payload.b", "old", "new"),
                        ),
                    ),
                )
            )
        ],
        detail_policy=ReportDetailPolicy(
            mode="default",
            show_fields=("pricing.*",),
            squelch_fields=("benchmarks", "benchmarks.*"),
            unclassified_limit=1,
        ),
    )

    assert "A: old \u2192 new" in report
    assert "B: old \u2192 new" not in report
    assert "1 additional unclassified field change hidden" in report


def test_show_pattern_wins_over_squelch_pattern() -> None:
    report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[
            _scan_result(
                (
                    ModelDelta(
                        "changed",
                        "alpha",
                        "Alpha",
                        (FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),),
                    ),
                )
            )
        ],
        detail_policy=ReportDetailPolicy(
            mode="default",
            show_fields=("benchmarks.design_arena",),
            squelch_fields=("benchmarks", "benchmarks.*"),
            unclassified_limit=20,
        ),
    )

    assert "Design arena" in report
    assert "squelched:" not in report


def test_html_change_summary_sorts_rows_by_change_type() -> None:
    report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="html",
        provider_results=[
            _scan_result(
                (
                    ModelDelta(
                        "changed",
                        "beta",
                        "Beta",
                        (FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),),
                    ),
                    ModelDelta(
                        "changed",
                        "alpha",
                        "Alpha",
                        (FieldChange("pricing.input", "0.000001", "0.000002"),),
                    ),
                    ModelDelta(
                        "changed",
                        "gamma",
                        "Gamma",
                        (FieldChange("metadata.owner", "old", "new"),),
                    ),
                )
            )
        ],
        detail_policy=ReportDetailPolicy(
            mode="all",
            show_fields=DEFAULT_REPORT_SHOW_FIELDS,
            squelch_fields=("benchmarks", "benchmarks.*"),
            unclassified_limit=20,
        ),
    )

    _, summary = _scan_detail_and_summary(report)
    # E6: the category is a group heading spanning the row, named once, rather
    # than a cell repeated on every row beneath it. The ORDER under test is
    # unchanged -- `_summary_entry_sort_key` still ranks the categories -- so
    # the assertion follows the headings instead of the per-row cells.
    pricing_index = summary.index('<td colspan="3">Pricing</td>')
    benchmarks_index = summary.index('<td colspan="3">Benchmarks</td>')
    other_index = summary.index('<td colspan="3">Other</td>')

    assert pricing_index < benchmarks_index < other_index
    # Named once each, which is what E6 bought.
    for category in ("Pricing", "Benchmarks", "Other"):
        assert summary.count(f'<td colspan="3">{category}</td>') == 1, category


def test_html_price_movement_summary_uses_exclusive_model_buckets() -> None:
    changed = (
        ModelDelta(
            "changed",
            "higher-model",
            "Higher Model",
            (
                FieldChange("pricing.prompt", "0.1", "0.2"),
                FieldChange("pricing.input_cache_read", None, "0.01"),
            ),
        ),
        ModelDelta(
            "changed",
            "lower-model",
            "Lower Model",
            (
                FieldChange("pricing.prompt", "0.2", "0.1"),
                FieldChange("pricing.input_cache_read", "0.01", None),
            ),
        ),
        ModelDelta(
            "changed",
            "mixed-model",
            "Mixed Model",
            (
                FieldChange("pricing.prompt", "0.1", "0.2"),
                FieldChange("pricing.completion", "0.4", "0.3"),
            ),
        ),
        ModelDelta(
            "changed",
            "coverage-model",
            "Coverage Model",
            (
                FieldChange("pricing.input_cache_read", None, "0.01"),
                FieldChange("pricing.input_cache_write", "0.02", None),
            ),
        ),
    )

    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )

    movement = _price_movement_card(report)
    # One model up, one down, one both: no bucket is strictly largest, so the
    # verdict is `mixed` and carries the counts it was derived from.
    assert (
        '<span class="outcome price-mixed">mixed \u2014 1 up, 1 down, 1 both</span>' in movement
    )
    assert '<span class="price-tally-label">4 models</span>' in movement
    assert '<span class="price-tally-chip price-higher">\u2191 1 higher</span>' in movement
    assert '<span class="price-tally-chip price-lower">\u2193 1 lower</span>' in movement
    assert '<span class="price-tally-chip price-mixed">\u2195 1 both</span>' in movement
    assert (
        '<span class="price-tally-chip price-coverage">\u00b1 1 added/removed only</span>'
        in movement
    )
    assert '<span class="price-tally-label">8 price fields</span>' in movement
    assert '<span class="price-tally-chip price-higher">\u2191 2</span>' in movement
    assert '<span class="price-tally-chip price-lower">\u2193 2</span>' in movement
    assert '<span class="price-tally-chip price-coverage">+2 added</span>' in movement
    assert '<span class="price-tally-chip price-coverage">\u22122 removed</span>' in movement
    assert '<summary>View 4 affected models</summary>' in movement
    for model_id in ("higher-model", "lower-model", "mixed-model", "coverage-model"):
        assert movement.count(f"<code>{model_id}</code>") == 1

    assert report.index('<div class="provider-cards">') < report.index('<section class="price-movement-summary">')
    assert report.index('<section class="price-movement-summary">') < report.index('<section class="provider-section">')
    # F2, not fixture order. All four models moved by the same $100,000/1M, so
    # the primary key ties at cents and the percent tiebreaker decides:
    # higher-model and mixed-model both peak at 100%, and higher-model's added
    # cache-read field wins the coverage tiebreaker; lower-model peaks at 50%;
    # coverage-model has no two-sided move at all and sorts at $0.00.
    primary, _ = _scan_tiers(report)
    assert _model_card_order(primary) == [
        "higher-model",
        "mixed-model",
        "lower-model",
        "coverage-model",
    ]


def test_html_price_movement_summary_preserves_provider_identity() -> None:
    changed = (
        ModelDelta(
            "changed",
            "shared-model",
            "Shared Model",
            (FieldChange("pricing.prompt", "0.1", "0.2"),),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[
            _scan_result(changed, provider_id="openrouter", provider_label="OpenRouter"),
            _scan_result(changed, provider_id="abacus", provider_label="Abacus.AI"),
        ],
    )

    movement = _price_movement_card(report)
    assert '<span class="price-tally-label">2 models</span>' in movement
    assert movement.count("<code>shared-model</code>") == 2
    assert '<span class="price-movement-provider">Abacus.AI</span>' in movement
    assert '<span class="price-movement-provider">OpenRouter</span>' in movement


def test_html_price_movement_list_omits_the_provider_when_only_one_has_price_changes() -> None:
    """E5: two providers in the report, one of them with the price changes.

    The provider label earns its column only when the list mixes providers.
    The second provider here is present, changed, and has NO price change, so
    a renderer keying the label off "how many providers are in this report"
    rather than "how many are in this card" still prints it and fails.
    """
    priced = (
        ModelDelta(
            "changed",
            "priced-model",
            "Priced Model",
            (FieldChange("pricing.prompt", "0.1", "0.2"),),
        ),
    )
    unpriced = (
        ModelDelta(
            "changed",
            "limits-model",
            "Limits Model",
            (FieldChange("context_length", 1000, 2000),),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[
            _scan_result(priced, provider_id="openrouter", provider_label="OpenRouter"),
            _scan_result(unpriced, provider_id="abacus", provider_label="Abacus.AI"),
        ],
    )

    movement = _price_movement_card(report)
    assert "price-movement-provider" not in movement
    assert "OpenRouter" not in movement
    assert '<div class="price-movement-model"><code>priced-model</code></div>' in movement


def test_html_price_movement_summary_omits_zero_categories() -> None:
    changed = (
        ModelDelta(
            "changed",
            "lower-model",
            "Lower Model",
            (
                FieldChange("pricing.prompt", "0.2", "0.1"),
                FieldChange("pricing.input_cache_read", "0.01", None),
            ),
        ),
        ModelDelta(
            "changed",
            "mixed-model",
            "Mixed Model",
            (
                FieldChange("pricing.prompt", "0.1", "0.2"),
                FieldChange("pricing.completion", "0.4", "0.3"),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-21T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )

    movement = _price_movement_card(report)
    # One `lower` model and one `mixed` model, so no bucket is strictly
    # largest and the verdict is `mixed`. It used to read `mostly lower` on
    # this same fixture -- 2 falling fields against 1 rising one -- which is
    # D3's defect in miniature: the tally below has never shown a majority
    # here, because at the level of models there is not one.
    assert '<span class="outcome price-mixed">mixed \u2014 1 down, 1 both</span>' in movement
    assert "mostly" not in movement
    assert '<span class="price-tally-label">2 models</span>' in movement
    assert '<span class="price-tally-chip price-lower">\u2193 1 lower</span>' in movement
    assert '<span class="price-tally-chip price-mixed">\u2195 1 both</span>' in movement
    assert "higher</span>" not in movement
    assert "added/removed only" not in movement
    assert '<span class="price-tally-label">4 price fields</span>' in movement
    assert '<span class="price-tally-chip price-lower">\u2193 2</span>' in movement
    assert '<span class="price-tally-chip price-higher">\u2191 1</span>' in movement
    assert '<span class="price-tally-chip price-coverage">\u22121 removed</span>' in movement
    assert "+0 added" not in movement


def test_html_price_movement_summary_uses_visible_monetary_leaves_only() -> None:
    changed = (
        ModelDelta(
            "changed",
            "structured-model",
            "Structured Model",
            (
                FieldChange(
                    "pricing.overrides",
                    None,
                    [{"prompt": "0.1", "min_prompt_tokens": 200000}],
                ),
            ),
        ),
    )
    all_policy = ReportDetailPolicy(
        mode="all",
        show_fields=DEFAULT_REPORT_SHOW_FIELDS,
        squelch_fields=("benchmarks", "benchmarks.*"),
        unclassified_limit=20,
    )
    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
        detail_policy=all_policy,
    )

    movement = _price_movement_card(report)
    # No directional model at all, so there is no bucket to be "mostly" of and
    # `mixed` would assert a direction this report does not have.
    assert (
        '<span class="outcome price-coverage">price fields added/removed</span>' in movement
    )
    assert '<span class="price-tally-chip price-coverage">+1 added</span>' in movement
    assert "\u22120 removed" not in movement
    # Nothing moved, so there is no dollar figure to headline and no panel.
    assert "price-headline" not in movement
    assert movement.count("<code>structured-model</code>") == 1

    squelched_policy = ReportDetailPolicy(
        mode="squelched",
        show_fields=DEFAULT_REPORT_SHOW_FIELDS,
        squelch_fields=("benchmarks", "benchmarks.*"),
        unclassified_limit=20,
    )
    hidden_report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
        detail_policy=squelched_policy,
    )
    # Keyed off the section element, not the words in its header: the header
    # was re-worded in Task 8 (`Price Movement` -> `PRICE MOVEMENT`), and an
    # assertion phrased against the old wording would have gone on passing
    # while the card it was meant to exclude rendered in full.
    assert _PRICE_MOVEMENT_OPEN not in hidden_report


def test_html_price_movement_summary_is_omitted_without_price_amount_changes() -> None:
    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[
            _scan_result(
                (
                    ModelDelta(
                        "changed",
                        "limits-only",
                        "Limits Only",
                        (FieldChange("context_length", 1000, 2000),),
                    ),
                )
            )
        ],
    )

    # See the note on the assertion above: the element, not the header text.
    assert _PRICE_MOVEMENT_OPEN not in report


# ---------------------------------------------------------------------------
# D3: the verdict and the tally beneath it must be counting the same things.
# ---------------------------------------------------------------------------


def _price_model(model_id: str, *, higher: int = 0, lower: int = 0) -> ModelDelta:
    """A model with `higher` price fields going up and `lower` going down.

    Distinct leaves per field so no two changes collapse, and distinct values
    so nothing classifies as a no-op. The magnitudes are irrelevant to the
    verdict -- that is the point of the fixture below.
    """
    fields = [
        FieldChange(leaf, "0.1", "0.2")
        for leaf in ("pricing.prompt", "pricing.completion", "pricing.request")[:higher]
    ] + [
        FieldChange(leaf, "0.2", "0.1")
        for leaf in ("pricing.input_cache_read", "pricing.input_cache_write", "pricing.image")[:lower]
    ]
    assert len(fields) == higher + lower, "fixture asked for more price leaves than it has"
    return ModelDelta("changed", model_id, model_id.title(), tuple(fields))


def test_price_movement_verdict_counts_models_not_fields() -> None:
    """THE D3 regression: a tied MODEL split must not read `mostly lower`.

    Four models up, four down, three in both directions -- no bucket is
    strictly largest, so the verdict is `mixed`. The field counts deliberately
    disagree with the model counts: the down models carry two decreases each,
    so there are 7 rising fields against 11 falling ones. The previous
    implementation compared exactly those two numbers and announced `mostly
    lower` directly above a tally showing 4 and 4, which is the defect. Restore
    the field-count comparison and this test fails on the verdict string.
    """
    changed = tuple(
        [_price_model(f"up-{index}", higher=1) for index in range(4)]
        + [_price_model(f"down-{index}", lower=2) for index in range(4)]
        + [_price_model(f"both-{index}", higher=1, lower=1) for index in range(3)]
    )
    report = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    movement = _price_movement_card(report)

    # The premise: fields are NOT tied, and lower leads. Asserted here so the
    # test cannot quietly stop exercising the defect if the fixture is edited.
    assert '<span class="price-tally-chip price-lower">↓ 11</span>' in movement
    assert '<span class="price-tally-chip price-higher">↑ 7</span>' in movement

    assert (
        '<span class="outcome price-mixed">mixed — 4 up, 4 down, 3 both</span>' in movement
    )
    assert "mostly lower" not in movement
    # The line the verdict now agrees with.
    assert '<span class="price-tally-label">11 models</span>' in movement
    assert '<span class="price-tally-chip price-higher">↑ 4 higher</span>' in movement
    assert '<span class="price-tally-chip price-lower">↓ 4 lower</span>' in movement
    assert '<span class="price-tally-chip price-mixed">↕ 3 both</span>' in movement


def _verdict(changed: tuple[ModelDelta, ...]) -> str:
    """The card's verdict span, rendered from `changed`.

    Extracted so the verdict tests below state a shape and its verdict and
    nothing else; every one of them renders a whole report through the public
    entry point, exactly as the tests that predate this helper did.
    """
    report = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    movement = _price_movement_card(report)
    match = re.search(r'<span class="outcome [^"]*">[^<]*</span>', movement)
    assert match is not None, "no verdict span in the price movement card"
    return match.group(0)


def test_price_movement_verdict_names_a_strictly_largest_model_bucket() -> None:
    """One bucket strictly largest in each direction, and its counts appended.

    Both fixtures are MIXED populations -- the losing bucket is non-empty --
    which is what earns the `mostly` hedge. The unanimous shapes, where it is
    dropped, are the test below.
    """
    higher_led = tuple(
        [_price_model(f"up-{index}", higher=1) for index in range(3)]
        + [_price_model("down-0", lower=1)]
    )
    assert (
        _verdict(higher_led)
        == '<span class="outcome price-higher">mostly higher — 3 up, 1 down</span>'
    )

    lower_led = tuple(
        [_price_model(f"down-{index}", lower=1) for index in range(3)]
        + [_price_model("up-0", higher=1)]
    )
    assert (
        _verdict(lower_led)
        == '<span class="outcome price-lower">mostly lower — 1 up, 3 down</span>'
    )

    # The runner-up need not be the opposite direction: one `both` model is
    # still a model this scan did not move in one direction, so the hedge
    # stands. This is the boundary of the rule below -- exactly one non-leading
    # model, in the bucket that is neither `up` nor `down`.
    with_one_both = tuple(
        [_price_model(f"up-{index}", higher=1) for index in range(3)]
        + [_price_model("both-0", higher=1, lower=1)]
    )
    assert (
        _verdict(with_one_both)
        == '<span class="outcome price-higher">mostly higher — 3 up, 1 both</span>'
    )


def test_price_movement_verdict_drops_the_qualifier_when_unanimous() -> None:
    """A unanimous population is `higher` / `lower`, never `mostly` either.

    "mostly" claims that some models went the other way. When the two
    non-leading buckets are empty, none did, and the hedge understates what
    the card is showing -- `mostly higher — 5 up` over a list in which nothing
    fell. Size is irrelevant: one model alone is as unanimous as five, and the
    single-model form is what the concise-HTML characterization golden holds.

    This is an amendment to the approved design, which specified only "one
    bucket strictly largest -> mostly higher / mostly lower" and did not
    consider a population with nothing to be "mostly" of. Restore the
    unconditional `mostly ` and every assertion here fails.
    """
    for size in (1, 2, 5):
        rising = tuple(_price_model(f"up-{index}", higher=1) for index in range(size))
        assert (
            _verdict(rising)
            == f'<span class="outcome price-higher">higher — {size} up</span>'
        )

        falling = tuple(_price_model(f"down-{index}", lower=1) for index in range(size))
        assert (
            _verdict(falling)
            == f'<span class="outcome price-lower">lower — {size} down</span>'
        )

    # A unanimous `both` bucket keeps `mixed`: every model here moved in two
    # directions at once, so the verdict naming that is already exact and has
    # no qualifier to drop.
    both_only = tuple(
        _price_model(f"both-{index}", higher=1, lower=1) for index in range(3)
    )
    assert _verdict(both_only) == '<span class="outcome price-mixed">mixed — 3 both</span>'


def test_price_movement_verdict_is_mixed_when_both_directions_leads() -> None:
    """A strictly largest `both` bucket is still `mixed`, not a direction.

    `both` is the largest bucket here, and it is the one bucket whose name is
    not a direction -- a "strictly largest bucket wins" rule that forgot to
    check WHICH bucket won would have to invent a verdict for it.
    """
    changed = tuple(
        [_price_model(f"both-{index}", higher=1, lower=1) for index in range(3)]
        + [_price_model("up-0", higher=1), _price_model("down-0", lower=1)]
    )
    report = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    assert (
        '<span class="outcome price-mixed">mixed — 1 up, 1 down, 3 both</span>'
        in _price_movement_card(report)
    )


def test_price_movement_kind_and_classify_change_agree_on_direction() -> None:
    """The card's two authorities must not disagree about which way a price went.

    `_price_movement_kind` gates the counts (and so the buckets, and so the
    verdict); `classify_change` supplies the headline panel's magnitude and
    direction. They are separate functions with different branch orders --
    `classify_change` tries noop, list and boolean before price -- so nothing
    but this assertion stops a future edit to either one from producing a card
    whose verdict says one thing and whose headline says the other.

    Today they agree on every input below, and the disagreement is not
    reachable: `_collect_price_movement_summary` calls `classify_change` only
    for changes this gate has already admitted, and every one-sided form the
    gate admits carries no `delta_abs` and so can never headline. That makes
    the invariant latent, not absent -- it is load-bearing for the card's
    internal consistency, and it was unasserted.

    The mapping is checked in one direction only. The converse is false by
    design and deliberately so: a boolean-coded price field classifies `up`
    while the gate returns `None`, and the collector never reaches
    `classify_change` for it.
    """
    expected_direction = {
        "higher": "up",
        "lower": "down",
        "added": "added",
        "removed": "removed",
    }
    cases = [
        # two-sided, both directions, across string / float / int spellings
        FieldChange("pricing.prompt", "0.000001", "0.000002"),
        FieldChange("pricing.prompt", "0.000002", "0.000001"),
        FieldChange("pricing.completion", 1e-6, 3e-6),
        FieldChange("pricing.completion", 3, 1),
        FieldChange("pricing.request", "1e-6", "2e-6"),
        FieldChange("pricing.request", "2e-6", "1e-6"),
        # a zero on one side: still two-sided, and the percent basis is 0
        FieldChange("pricing.image", 0, "0.000001"),
        FieldChange("pricing.image", "0.000001", 0),
        # one-sided: counted, but never a headline mover
        FieldChange("pricing.input_cache_read", None, "0.000001"),
        FieldChange("pricing.input_cache_write", "0.000001", None),
        # a conditional tier, whose path carries a bracketed qualifier
        FieldChange("pricing.overrides[0].prompt", "0.000001", "0.000002"),
        # not admitted by the gate at all; asserted below to stay that way
        FieldChange("pricing.prompt", "0.1", "0.10"),
        FieldChange("pricing.prompt", "free", "0.000001"),
        FieldChange("pricing.prompt", False, True),
    ]
    # Every provider normalization the collector can be handed, including the
    # identity: normalization scales magnitudes, and a scale that could invert
    # a comparison would desync the buckets from the headline.
    normalizations = ((1_000_000, 1), (1, 1), (1, 1000), (1000, 1000))

    observed = set()
    for field_change in cases:
        kind = reporting._price_movement_kind(field_change)
        observed.add(kind)
        for multiplier, divisor in normalizations:
            rendered = classify_change(
                field_change,
                price_multiplier=multiplier,
                price_divisor=divisor,
            )
            if kind is None:
                # Not counted, so whatever it classifies as, it is not part of
                # any bucket -- but it must also not be able to headline, which
                # is what `delta_abs` decides.
                continue
            assert rendered.direction == expected_direction[kind], (
                f"{field_change.field_name} {field_change.old_value!r} -> "
                f"{field_change.new_value!r} at x{multiplier}/{divisor}: "
                f"counted {kind!r} but classified {rendered.direction!r}"
            )
            # The headline slot lookup, restated: only the two-sided
            # directions have a slot, so `added`/`removed` cannot headline.
            assert (rendered.direction in reporting._PRICE_MOVEMENT_SLOTS) == (
                kind in ("higher", "lower")
            )

    # The fixture must exercise every kind, or the loop above passes vacuously.
    assert observed == {"higher", "lower", "added", "removed", None}


# ---------------------------------------------------------------------------
# D1: the card leads with the two biggest dollar movers, by name and amount.
# ---------------------------------------------------------------------------


def _headline_panel(movement: str, label: str) -> str:
    """The `price-headline` panel whose label is `label`.

    Bounded by the headlines CONTAINER before splitting on the panels, so the
    last panel's text stops where the container does. Splitting the whole card
    on the panel opening tag instead would hand back everything from the final
    panel to the end of the card -- tallies and affected-model list included --
    and an assertion that some other model is absent "from the panel" would be
    reading the model list.
    """
    assert '<div class="price-movement-headlines">' in movement, "no headline movers rendered"
    container = movement.split('<div class="price-movement-headlines">', 1)[1]
    container = container.split('<div class="price-movement-tallies">', 1)[0]
    panels = [
        panel
        for panel in container.split('<div class="price-headline">')[1:]
        if f">{label}</div>" in panel
    ]
    assert len(panels) == 1, f"expected exactly one {label!r} panel, got {len(panels)}"
    return panels[0]


def test_price_movement_headline_names_the_biggest_dollar_mover() -> None:
    """The increase panel is chosen by DOLLARS, not by percent and not by count.

    `small-pct-big-dollars` moves $1.00 -> $3.00 (+$2.00, +200%);
    `big-pct-small-dollars` moves $0.01 -> $0.05 (+$0.04, +400%) and carries
    THREE rising fields to the other model's one. A selector keyed on percent
    or on how many fields moved picks the wrong model, and the panel names it.
    """
    changed = (
        ModelDelta(
            "changed",
            "small-pct-big-dollars",
            "Small Pct Big Dollars",
            (FieldChange("pricing.prompt", "0.000001", "0.000003"),),
        ),
        ModelDelta(
            "changed",
            "big-pct-small-dollars",
            "Big Pct Small Dollars",
            (
                FieldChange("pricing.prompt", "0.00000001", "0.00000005"),
                FieldChange("pricing.completion", "0.00000001", "0.00000005"),
                FieldChange("pricing.request", "0.00000001", "0.00000005"),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    panel = _headline_panel(_price_movement_card(report), "Biggest increase")

    assert '<code class="price-headline-model">small-pct-big-dollars</code>' in panel
    assert '<div class="price-headline-field" title="pricing.prompt">Input</div>' in panel
    assert "$1.00 → $3.00" in panel
    assert '<span class="price-headline-delta price-higher">+$2.00</span>' in panel
    assert '<span class="price-headline-pct price-higher">↑ 200.0%</span>' in panel
    assert "big-pct-small-dollars" not in panel


def test_price_movement_headline_panels_cover_both_directions() -> None:
    """Two panels when the scan moved both ways, each naming its own extreme."""
    changed = (
        ModelDelta(
            "changed",
            "riser",
            "Riser",
            (FieldChange("pricing.prompt", "0.000001", "0.000004"),),
        ),
        ModelDelta(
            "changed",
            "faller",
            "Faller",
            (FieldChange("pricing.completion", "0.000009", "0.000002"),),
        ),
        ModelDelta(
            "changed",
            "small-mover",
            "Small Mover",
            (
                FieldChange("pricing.prompt", "0.000001", "0.0000011"),
                FieldChange("pricing.completion", "0.000002", "0.0000019"),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    movement = _price_movement_card(report)
    assert movement.count('<div class="price-headline">') == 2

    increase = _headline_panel(movement, "Biggest increase")
    assert '<code class="price-headline-model">riser</code>' in increase
    assert '<span class="price-headline-delta price-higher">+$3.00</span>' in increase

    decrease = _headline_panel(movement, "Biggest decrease")
    assert '<code class="price-headline-model">faller</code>' in decrease
    assert '<span class="price-headline-delta price-lower">-$7.00</span>' in decrease

    # The increase panel comes first, so the two panels are in a fixed order
    # rather than whichever direction happened to be discovered first.
    assert movement.index("Biggest increase") < movement.index("Biggest decrease")


def test_price_movement_omits_the_decrease_panel_when_nothing_got_cheaper() -> None:
    """No decreases -> the panel is ABSENT, not an empty box.

    A panel headed `Biggest decrease` over blank space reads as a rendering
    failure, and there is nothing truthful to put in it.
    """
    changed = (
        ModelDelta(
            "changed",
            "riser",
            "Riser",
            (
                FieldChange("pricing.prompt", "0.000001", "0.000004"),
                # A removal, which is a price CHANGE with no direction and no
                # delta -- it must not be pressed into service as a decrease.
                FieldChange("pricing.input_cache_read", "0.000009", None),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    movement = _price_movement_card(report)

    assert movement.count('<div class="price-headline">') == 1
    assert "Biggest increase" in movement
    assert "Biggest decrease" not in movement


def test_price_movement_headline_prints_the_qualified_label() -> None:
    """The headline names the tier that moved, not the collapsed leaf label.

    The conditional tier moves $4.00 -> $9.00 and the base rate $1.00 ->
    $2.00, so the tier is the biggest mover and the panel must spell it
    `Input (min_prompt_tokens=200000)`. A renderer reading `label` instead of
    `display_label` prints a bare `Input` here, indistinguishable from the
    base-rate row on the card below.

    This is the guard `test_every_field_change_entry_point_surfaces_the_qualifier`
    cannot carry: its bare/qualified parity identity holds only for render
    sites that emit BOTH rows, and a headline emits one by construction.
    """
    changed = (
        ModelDelta(
            "changed",
            "synth/model-tiered",
            "Synth Tiered",
            (
                FieldChange("pricing.prompt", "0.000001", "0.000002"),
                FieldChange(
                    "pricing.overrides",
                    [{"min_prompt_tokens": 200000, "prompt": "0.000004"}],
                    [{"min_prompt_tokens": 200000, "prompt": "0.000009"}],
                ),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    panel = _headline_panel(_price_movement_card(report), "Biggest increase")

    assert (
        '<div class="price-headline-field" '
        'title="pricing.overrides[min_prompt_tokens=200000].prompt">'
        "Input (min_prompt_tokens=200000)</div>" in panel
    )
    assert '<span class="price-headline-delta price-higher">+$5.00</span>' in panel


def test_price_movement_tallies_state_their_units_independently() -> None:
    """Models and price fields are counted separately and each says which it is.

    The two counts differ here (2 models, 5 price fields) precisely so that a
    tally which printed one unit's number under the other's label is visible.
    """
    changed = (
        ModelDelta(
            "changed",
            "mover-a",
            "Mover A",
            (
                FieldChange("pricing.prompt", "0.1", "0.2"),
                FieldChange("pricing.completion", "0.4", "0.3"),
                FieldChange("pricing.input_cache_read", None, "0.01"),
            ),
        ),
        ModelDelta(
            "changed",
            "mover-b",
            "Mover B",
            (
                FieldChange("pricing.prompt", "0.2", "0.1"),
                FieldChange("pricing.input_cache_write", "0.02", None),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    movement = _price_movement_card(report)

    models_group, fields_group = movement.split('<div class="price-tally-group">')[1:3]
    assert '<span class="price-tally-label">2 models</span>' in models_group
    assert '<span class="price-tally-chip price-mixed">↕ 1 both</span>' in models_group
    assert '<span class="price-tally-chip price-lower">↓ 1 lower</span>' in models_group
    assert "↑" not in models_group  # no model rose without also falling

    assert '<span class="price-tally-label">5 price fields</span>' in fields_group
    assert '<span class="price-tally-chip price-lower">↓ 2</span>' in fields_group
    assert '<span class="price-tally-chip price-higher">↑ 1</span>' in fields_group
    assert '<span class="price-tally-chip price-coverage">+1 added</span>' in fields_group
    assert '<span class="price-tally-chip price-coverage">−1 removed</span>' in fields_group


def test_price_movement_buckets_hold_one_fixed_order_everywhere() -> None:
    """Chips and columns are ordered by the design's bucket list, not by count.

    Both tallies used to be ordered by magnitude -- the field chips put the
    leading direction first, the model chips and the affected-model columns
    sorted by bucket size -- so that the order itself carried the verdict.
    D3 gives that job to the verdict string, which now names the leading
    bucket and prints every bucket's count, and an order that still shifts
    with the data is a layout the reader has to re-parse on every report.

    The fixture is deliberately anti-sorted: the SMALLEST model bucket
    (`higher`, 1) is the one that must come first, and the field tally has
    more decreases than increases while `↑` must still precede `↓`. Any
    surviving count-sort therefore reverses something here.
    """
    changed = tuple(
        [_price_model("up-0", higher=1)]
        + [_price_model(f"down-{index}", lower=2) for index in range(2)]
        + [_price_model(f"both-{index}", higher=1, lower=1) for index in range(3)]
        + [
            ModelDelta(
                "changed",
                "coverage-0",
                "Coverage 0",
                (
                    FieldChange("pricing.input_cache_read", None, "0.01"),
                    FieldChange("pricing.input_cache_write", "0.02", None),
                ),
            )
        ]
    )
    report = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    movement = _price_movement_card(report)
    models_group, fields_group = movement.split('<div class="price-tally-group">')[1:3]

    def _order(haystack: str, needles: tuple[str, ...]) -> list[int]:
        positions = []
        for needle in needles:
            assert needle in haystack, needle
            positions.append(haystack.index(needle))
        return positions

    # Models: ↑ higher, ↓ lower, ↕ both, ± added/removed only -- despite the
    # counts running 1, 2, 3, 1.
    model_chips = _order(
        models_group, ("↑ 1 higher", "↓ 2 lower", "↕ 3 both", "± 1 added/removed only")
    )
    assert model_chips == sorted(model_chips), models_group

    # Price fields: ↓, ↑, +added, −removed -- the design's order, which puts
    # decreases first regardless of which direction leads.
    field_chips = _order(fields_group, ("↓ 7", "↑ 4", "+1 added", "−1 removed"))
    assert field_chips == sorted(field_chips), fields_group

    # The affected-model columns repeat the same order, so a chip and the
    # column it summarises are never read in different sequences.
    columns = _order(
        movement,
        (
            "↑ Higher only — 1",
            "↓ Lower only — 2",
            "↕ Both directions — 3",
            "± Added/removed only — 1",
        ),
    )
    assert columns == sorted(columns), movement


def test_default_html_summary_aggregates_squelched_benchmark_rows() -> None:
    report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="html",
        provider_results=[
            _scan_result(
                (
                    ModelDelta(
                        "changed",
                        "alpha",
                        "Alpha",
                        (FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),),
                    ),
                )
            )
        ],
    )

    assert "Design arena" not in report
    assert "1 field change across 1 model" in report


def test_default_scan_reports_group_repetitive_list_changes_but_keep_scalar_changes_individual() -> None:
    result = _scan_result(_bulk_parameter_changes())

    text_report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[result],
    )
    markdown_report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="markdown",
        provider_results=[result],
    )
    html_report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="html",
        provider_results=[result],
    )

    assert "Bulk change \u2014 3 models" in text_report
    assert "models: alpha, beta, gamma" in text_report
    assert "Supported parameters: +reasoning_effort" in text_report
    assert "2 field changes across 2 of these models" in text_report
    assert "* priced-model (Priced Model)" in text_report
    assert "Input: 0.000001 \u2192 0.000002" in text_report

    assert "**Bulk change \u2014 3 models**" in markdown_report
    assert "`Supported parameters: +reasoning_effort`" in markdown_report
    assert "`priced-model` - Priced Model" in markdown_report

    detail_html, summary_html = _scan_detail_and_summary(html_report)
    assert '<div class="model-card-header"><code>Bulk change \u2014 3 models</code>' in detail_html
    assert '<div class="model-card-header"><code>alpha</code>' not in detail_html
    assert '<div class="model-card-header"><code>priced-model</code>' in detail_html
    assert '<summary>Models: alpha, beta, gamma</summary>' in detail_html
    assert '<summary>3 models</summary>' in summary_html
    # E6: two Parameters rows still, but the category names itself once, in a
    # group heading over them, instead of once per row.
    assert summary_html.count('<td colspan="3">Parameters</td>') == 1
    assert summary_html.count('<td colspan="3">Squelched</td>') == 1
    assert "priced-model" in summary_html
    # F1/F2: the bulk group holds only list changes, so it can never carry a
    # price move and is always secondary; the priced model leads tier 1.
    primary, secondary = _scan_tiers(html_report)
    assert _model_card_order(primary) == ["priced-model"]
    assert "Bulk change \u2014 3 models" in _model_card_order(secondary)


def test_all_detail_scan_report_does_not_bulk_group_models() -> None:
    report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(_bulk_parameter_changes()[:3])],
        detail_policy=ReportDetailPolicy(
            mode="all",
            show_fields=DEFAULT_REPORT_SHOW_FIELDS,
            squelch_fields=("benchmarks", "benchmarks.*"),
            unclassified_limit=20,
        ),
    )

    detail_html, _ = _scan_detail_and_summary(report)
    assert "Bulk change" not in detail_html
    assert '<div class="model-card-header"><code>alpha</code>' in detail_html
    assert '<div class="model-card-header"><code>beta</code>' in detail_html
    assert '<div class="model-card-header"><code>gamma</code>' in detail_html


def test_default_scan_report_omits_squelched_only_models_from_details_and_summary() -> None:
    changed = (
        ModelDelta(
            "changed",
            "squelched-only",
            "Squelched Only",
            (FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),),
        ),
        ModelDelta(
            "changed",
            "visible-and-squelched",
            "Visible and Squelched",
            (
                FieldChange("pricing.input", "0.000001", "0.000002"),
                FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),
            ),
        ),
    )
    text_report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[_scan_result(changed)],
    )
    html_report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )

    assert "* squelched-only (Squelched Only)" not in text_report
    assert "* visible-and-squelched (Visible and Squelched)" in text_report
    assert "squelched: 2 field changes across 2 models" in text_report

    detail_html, summary_html = _scan_detail_and_summary(html_report)
    assert '<div class="model-card-header"><code>squelched-only</code>' not in detail_html
    assert '<div class="model-card-header"><code>visible-and-squelched</code>' in detail_html
    assert '<td><code>squelched-only</code>' not in summary_html
    assert summary_html.count('<td colspan="3">Squelched</td>') == 1
    assert '<summary>2 models</summary>' in summary_html
    assert "visible-and-squelched" in summary_html
    assert "2 field changes across 2 models" in detail_html


def test_changes_report_applies_detail_policy() -> None:
    changes = (
        {
            "detected_at": "2026-06-16T13:05:05+00:00",
            "provider_id": "openrouter",
            "provider_label": "OpenRouter",
            "provider_model_id": "alpha",
            "display_name": "Alpha",
            "change_kind": "changed",
            "field_name": "benchmarks.design_arena",
            "old_value": [{"elo": 1}],
            "new_value": [{"elo": 2}],
        },
        {
            "detected_at": "2026-06-16T13:05:05+00:00",
            "provider_id": "openrouter",
            "provider_label": "OpenRouter",
            "provider_model_id": "alpha",
            "display_name": "Alpha",
            "change_kind": "changed",
            "field_name": "pricing.prompt",
            "old_value": "0.1",
            "new_value": "0.2",
        },
    )

    report = render_changes_report(
        format_name="text",
        provider_id=None,
        since=None,
        until=None,
        changes=changes,
        provider_pricing={"openrouter": (1, 1)},
    )

    assert "Input" in report
    assert "Design arena" not in report
    assert "squelched:" in report


def test_history_report_applies_detail_policy() -> None:
    report = render_history_report(
        provider_id="openrouter",
        model_id="alpha",
        format_name="text",
        first_seen=None,
        last_seen=None,
        events=(
            HistoryEvent("2026-06-16T13:05:05+00:00", "changed", "benchmarks.design_arena", 1, 2),
            HistoryEvent("2026-06-16T13:05:05+00:00", "changed", "pricing.prompt", "0.1", "0.2"),
        ),
    )

    # The history report renders HistoryEvent rows directly and never builds a
    # RenderedChange, so it still prints RAW dotted paths. Labels stop at the
    # scan/changes reports; pinning the raw spelling here documents that
    # boundary rather than leaving it to be discovered by a future reader.
    assert "pricing.prompt" in report
    assert "Input" not in report
    assert "benchmarks.design_arena" not in report
    assert "squelched" in report


def test_json_output_remains_full_fidelity() -> None:
    report = render_scan_report(
        generated_at="2026-06-16T13:05:05+00:00",
        command="scan",
        format_name="json",
        provider_results=[
            _scan_result(
                (
                    ModelDelta(
                        "changed",
                        "alpha",
                        "Alpha",
                        (FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),),
                    ),
                )
            )
        ],
    )

    # JSON keeps the RAW dotted path: it is a machine-readable audit
    # surface and never routes through the label registry.
    assert "benchmarks.design_arena" in report
    assert "Design arena" not in report


def test_new_pricing_values_are_normalized_when_the_old_value_is_missing() -> None:
    changed = (
        ModelDelta(
            "changed",
            "google/gemini-3.5-flash",
            "Google: Gemini 3.5 Flash",
            (FieldChange("pricing.input_audio_cache", None, "0.0000003"),),
        ),
    )

    text_report = render_scan_report(
        generated_at="2026-07-14T13:05:03+00:00",
        command="scan",
        format_name="text",
        provider_results=[_scan_result(changed)],
    )
    markdown_report = render_scan_report(
        generated_at="2026-07-14T13:05:03+00:00",
        command="scan",
        format_name="markdown",
        provider_results=[_scan_result(changed)],
    )
    html_report = render_scan_report(
        generated_at="2026-07-14T13:05:03+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )

    expected = "Audio cache: null \u2192 0.0000003 ($0.30 / 1M)"
    assert expected in text_report
    assert expected in markdown_report
    # A1: the card leads with the normalized figure and keeps the provider's
    # raw value in the cell's tooltip; the absent side is an em dash, not
    # `null`.
    row = _card_row(html_report, "Audio cache")
    assert '<td class="new-val num" title="0.0000003">$0.30</td>' in row
    assert '<td class="old-val num">\u2014</td>' in row
    assert '<td class="unit">/1M</td>' in row
    assert '<td class="delta sem-coverage">added</td>' in row

    # Fix pass 1, finding 3: the Change Summary is in the SAME document, and it
    # spelled this absence `null` while the card above it spelled it `\u2014`.
    assert "<td>\u2014 \u2192 0.0000003 ($0.30 / 1M)</td>" in html_report
    assert "<td>null \u2192" not in html_report


def _mixed_direction_card_html() -> str:
    """A card spanning THREE categories, with both directions inside one of them.

    Three, not two: C1's claim is that a card's columns line up ACROSS category
    boundaries, and two groups exercise exactly one boundary -- which a renderer
    that reset its widths on every SECOND group would still pass. The third
    group is `Capabilities`, and it is also the only non-numeric value cell
    here, so it pins that a `boolean` row sits in the same eight columns as a
    price without claiming to be a number.
    """
    changed = (
        ModelDelta(
            "changed",
            "mixed-model",
            "Mixed Model",
            (
                FieldChange("pricing.prompt", "0.1", "0.2"),
                FieldChange("pricing.completion", "0.4", "0.3"),
                FieldChange("pricing.input_cache_read", "0.01", None),
                FieldChange("context_length", 1000, 2000),
                FieldChange("reasoning.default_enabled", False, True),
            ),
        ),
    )
    return render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )


def test_html_card_colors_are_driven_by_semantic_not_direction() -> None:
    """B1. A price rise and a context rise are BOTH `direction == "up"`; they
    must not be the same color, because one is money and the other is capacity.

    Asserted on the class names rather than on "they differ", so a future change
    that re-merges cost and capacity coloring fails here with the two spellings
    in the failure message. `sem-cost-up` is red and `sem-capacity` amber in
    `_HTML_CSS`; the pair of classes is the contract this pins.
    """
    report = _mixed_direction_card_html()

    price_up = _card_row(report, "Input")
    price_down = _card_row(report, "Output")
    price_gone = _card_row(report, "Cache read")
    capacity_up = _card_row(report, "Context length (model)")

    # No thousands separator: `_fmt_price_per_m` has never grouped digits, and
    # it is shared with text and markdown, so this task does not change it.
    assert '<td class="delta sem-cost-up">+$100000.00</td>' in price_up
    assert '<td class="pct sem-cost-up">\u2191 100.0%</td>' in price_up
    assert '<td class="delta sem-cost-down">-$100000.00</td>' in price_down
    assert '<td class="pct sem-cost-down">\u2193 25.0%</td>' in price_down
    assert '<td class="delta sem-coverage">removed</td>' in price_gone
    # THE regression this test exists for: same direction, same column,
    # different meaning -- so a different class.
    assert '<td class="delta sem-capacity">+1,000</td>' in capacity_up
    assert '<td class="pct sem-capacity">\u2191 100.0%</td>' in capacity_up
    assert "sem-cost-up" not in capacity_up
    assert "sem-capacity" not in price_up

    # The old direction-only classes are gone from the card entirely: they are
    # what made a context increase green, i.e. "good".
    for stale in ("delta-increase", "delta-decrease", "delta-price-higher", "delta-price-lower"):
        assert stale not in "".join(_card_rows(report)), stale


def test_html_card_emits_exactly_one_table_for_a_multi_category_model() -> None:
    """C1. Per-category tables size their columns independently, which is why a
    card's numbers did not line up from one category to the next. One table for
    the card, one `<colgroup>`, and the category names become row-group chips.
    """
    report = _mixed_direction_card_html()
    card = report[report.index('<div class="model-card">') : report.index(_SCAN_SUMMARY_OPEN)]

    assert card.count("<table") == 1
    assert card.count("<colgroup>") == 1
    # All THREE categories are present, each as a chip on the FIRST row of its
    # group only -- four price rows, one capacity row, one capability row,
    # three chips.
    assert card.count('<td class="cat-chip">') == 3
    assert '<td class="cat-chip">Pricing</td>' in card
    assert '<td class="cat-chip">Context &amp; Limits</td>' in card
    assert '<td class="cat-chip">Capabilities</td>' in card
    # Matched as a class TOKEN, not as a whole attribute: a row also carries
    # `row-alt` when it falls on a zebra stripe, so `class="group-start"` would
    # be a substring assertion about which classes happen to co-occur.
    assert len(re.findall(r'<tr class="[^"]*\bgroup-start\b', card)) == 3
    assert len(_card_rows(card)) == 5
    # Every row carries all eight cells, across every group boundary. Counted
    # rather than spot-checked: a row short of a cell shifts every cell to its
    # right into the wrong column, which is the failure this layout exists to
    # rule out, and it would not show up in a chip or border count.
    for row in _card_rows(card):
        assert row.count("<td") == 8, row


def test_html_card_sorts_pricing_rows_by_absolute_impact() -> None:
    """C1's ordering rule: within Pricing, the largest mover leads.

    Alphabetical order would put `Cache read` first and the two $100k movements
    below it; the fixture's field order would put `Input` before `Output`. The
    expected order matches neither, so this cannot pass by accident.
    """
    changed = (
        ModelDelta(
            "changed",
            "sorted-model",
            "Sorted Model",
            (
                FieldChange("pricing.input_cache_read", "0.000001", "0.000002"),
                FieldChange("pricing.prompt", "0.000004", "0.000005"),
                FieldChange("pricing.completion", "0.000001", "0.000009"),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    labels = re.findall(r'<td class="field-name"[^>]*>(.*?)</td>', report)
    # +$8.00, then +$1.00, then +$1.00 -- the last two tie on impact and keep
    # their arrival order (`Cache read` was first in the fixture).
    assert labels == ["Output", "Cache read", "Input"]


_LONG_PARAMETER_LIST = (
    '["tools", "tool_choice", "logit_bias", "logprobs", "top_logprobs", '
    '"response_format", "structured_outputs", "repetition_penalty", "seed", "stop"]'
)


def _list_and_scalar_card_html() -> str:
    """A card carrying a multi-member list diff AND a long one-sided scalar.

    Both shapes are reachable on real provider data and neither is exercised by
    the price/count fixtures above: `tier_profiles` moves two members in and two
    out at once, and a provider that starts reporting `supported_parameters`
    sends the whole list as one unbreakable-looking string.
    """
    changed = (
        ModelDelta(
            "changed",
            "synth/model-lists",
            "Synth Lists",
            (
                FieldChange("pricing.prompt", "0.000002", "0.0000035"),
                FieldChange("supported_parameters", None, _LONG_PARAMETER_LIST),
                FieldChange(
                    "tier_profiles",
                    ['{"name": "alpha", "weight": 1}', '{"name": "gamma", "weight": 7}'],
                    ['{"name": "alpha", "weight": 2}', '{"name": "beta", "weight": 4}'],
                ),
            ),
        ),
    )
    return render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )


def test_list_members_take_a_continuation_row_instead_of_a_mid_table_cell() -> None:
    """Fix pass 1, finding 1. The members are a BAND, not a squeezed cell.

    The shape this replaces put an inline count and a block-level member `<div>`
    in one `<td colspan="6">` that began at the `old` column. Two consequences,
    both asserted against here: the cell always ran to two lines, and its
    left-aligned members started under the right-aligned numeric columns of the
    rows above and below. No CSS fixes that, so the assertions are about the
    markup's SHAPE rather than about any declaration.
    """
    report = _list_and_scalar_card_html()

    # The defect's own spelling is gone from the document outright.
    assert "list-cell" not in report
    assert 'colspan="6"' not in report

    label_row = _card_row(report, "Tier profiles")
    # The label row is an ordinary grid row: eight cells, four of them the empty
    # value columns a membership change has no operands for.
    assert label_row.count("<td") == 8
    assert label_row.count("<td></td>") == 4
    # THE point of finding 1: the count sits in the delta column, so it lands
    # under the card's other deltas instead of floating mid-table.
    assert '<td class="delta list-count">(2 → 2)</td>' in label_row
    assert '<td class="pct"></td>' in label_row

    members = report.split(label_row, 1)[1].split("</tr>", 1)[0] + "</tr>"
    assert members.startswith('\n<tr class="list-members"><td></td><td colspan="7">')
    # Both blocks of a two-sided membership change land in the one band.
    assert '<div class="list-added">' in members
    assert '<div class="list-removed">' in members
    assert "+ {&quot;name&quot;: &quot;beta&quot;, &quot;weight&quot;: 4}" in members
    assert "− {&quot;name&quot;: &quot;gamma&quot;, &quot;weight&quot;: 7}" in members

    # A continuation row carries no `field-name` cell, so it is not a card row
    # and the row-count assertions elsewhere in this module are unaffected by
    # its arrival. Stated as an assertion because it is load-bearing for them.
    assert 'class="field-name"' not in members
    assert len(_card_rows(report)) == 3


def test_zebra_stripes_count_fields_not_table_rows() -> None:
    """A continuation row must not shift the stripe of everything below it.

    `:nth-child(even)` counts `<tr>` elements, and finding 1's members row is a
    `<tr>`. Under that rule one list change in a card made the stripes stutter
    -- two adjacent fields came out the same shade -- and shaded the members
    differently from the label they belong to. The stripe is now emitted as a
    `row-alt` class counted over FIELDS, and the members row inherits its
    label's.
    """
    changed = (
        ModelDelta(
            "changed",
            "synth/model-stripes",
            "Synth Stripes",
            (
                FieldChange("pricing.prompt", "0.000002", "0.0000035"),
                FieldChange("pricing.completion", "0.000004", "0.000009"),
                FieldChange("context_length", 1000, 2000),
                FieldChange("supported_parameters", ["tools"], ["tools", "seed"]),
                FieldChange("reasoning.default_enabled", False, True),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )

    # Five fields, so five field rows, and their shades strictly alternate.
    field_rows = _card_rows(report)
    assert len(field_rows) == 5
    assert ["row-alt" in row for row in field_rows] == [False, True, False, True, False]

    # The list field is the fourth, so it is striped -- and its members row
    # carries the SAME stripe, which is what makes the pair read as one band.
    list_row = _card_row(report, "Supported parameters")
    assert "row-alt" in list_row
    members = report.split(list_row, 1)[1].split("</tr>", 1)[0]
    assert members.startswith('\n<tr class="list-members row-alt">')

    # The field AFTER the list is unstriped. Under `:nth-child(even)` it was the
    # sixth `<tr>` and came out striped, directly below a striped row.
    assert "row-alt" not in _card_row(report, "Reasoning default")

    css = report.split("<style>", 1)[1].split("</style>", 1)[0]
    assert ".card-table tr.row-alt td {" in css
    assert ".card-table tr:nth-child(even)" not in css


def test_a_long_scalar_value_is_not_promised_nowrap_by_the_card() -> None:
    """Fix pass 1, finding 2. `nowrap` on an arbitrary-length value breaks the card.

    A `col` width is a HINT, not a maximum: a 100-character `supported_parameters`
    value in a `nowrap` cell widens the column until the card overflows
    sideways, which defeats the alignment the eight-column layout exists to
    deliver. Numeric cells keep `nowrap` -- `$3.50` and `+131,072` must never be
    broken across lines.
    """
    report = _list_and_scalar_card_html()

    scalar_row = _card_row(report, "Supported parameters")
    price_row = _card_row(report, "Input")

    # The long value's cell does NOT claim to be numeric...
    assert '<td class="new-val">' in scalar_row
    assert "num" not in scalar_row
    assert "logit_bias" in scalar_row
    # ...while both price cells do.
    assert '<td class="old-val num" title="0.000002">$2.00</td>' in price_row
    assert '<td class="new-val num" title="0.0000035">$3.50</td>' in price_row

    # And `nowrap` is scoped to that class, with the wrapping cells given an
    # explicit break rule. Asserted on the stylesheet because the class is only
    # half the fix -- markup that opts out of a declaration that still applies
    # to everything would pass every assertion above and still overflow.
    css = report.split("<style>", 1)[1].split("</style>", 1)[0]
    nowrap_rule = css.split(".card-table td.num,", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap;" in nowrap_rule
    assert ".card-table td.old-val," not in nowrap_rule
    wrap_rule = css.split(".card-table td.old-val,\n.card-table td.new-val {", 1)[1].split("}", 1)[0]
    assert "overflow-wrap: break-word;" in wrap_rule
    # The wrapper can still scroll if a single unbreakable token exceeds even
    # the widened column -- the backstop, not the fix.
    assert "overflow-x: auto;" in css


def test_card_list_members_keep_red_and_green_for_money() -> None:
    """Fix pass 1, finding 4. B1's stated effect was false inside a card.

    `+ logit_bias` rendered green and `− seed` red, so the two colours that mean
    "a price went up" and "a price went down" also meant "a member arrived" and
    "a member left" in the same card. The card now re-colours them to the
    `capability` pair (blue on, dim off); the `+`/`−` glyphs carry the
    add-vs-remove distinction, which is why losing the green/red contrast costs
    nothing here.

    Scoped to `.card-table`, so the `changes` report and the bulk cards -- which
    are not this task's document -- keep the global rules untouched.
    """
    report = _list_and_scalar_card_html()
    css = report.split("<style>", 1)[1].split("</style>", 1)[0]

    # The two-class descendant form is load-bearing and is why these assertions
    # name the selector rather than just the colour: `.card-table .list-added`
    # is specificity (0,2,0) against the global rule's (0,1,0), so it wins
    # WHEREVER it sits in the stylesheet. A single-class card override would
    # tie and silently depend on source order.
    assert ".card-table .list-added { color: var(--accent-blue); }" in css
    assert ".card-table .list-removed { color: var(--text-dim); }" in css
    # The global rules survive untouched, which is what keeps this change
    # inside the card: the `changes` report and the bulk cards still use them.
    assert ".list-added { color: var(--accent-green); }" in css
    assert ".list-removed { color: var(--accent-red); }" in css

    # No `sem-cost-*` class reaches a membership row: the money colours stay on
    # the money columns.
    members = report.split('<tr class="list-members">', 1)[1].split("</tr>", 1)[0]
    assert "sem-cost-up" not in members
    assert "sem-cost-down" not in members


def test_one_html_document_spells_an_absent_side_one_way() -> None:
    """Fix pass 1, finding 3. The card said `—` and the summary said `null`.

    Asserted over every cell that can carry a side of a change -- the card's
    value cells and each Change Summary row's change cell -- rather than over
    the two cells that prompted it, so a renderer that later reintroduces
    `null` for an absent side anywhere in this document still fails here.

    Fix pass 2, finding 4: the assertion used to be `"null" not in
    html_report`, which was right for this fixture and wrong as a rule. A model
    id, a provider label or a genuine string value of `"null"` would have
    tripped it, and the failure would have named the absent-side spelling while
    pointing at something else entirely. `absent_side_cells` is the scoping,
    shared with the `changes` report's characterization module.

    Text and markdown are asserted to still say `null`, so this cannot pass by
    having quietly changed the shared text line.
    """
    changed = (
        ModelDelta(
            "changed",
            "synth/model-absent",
            "Synth Absent",
            (
                FieldChange("pricing.input_cache_read", None, "0.00000005"),
                FieldChange("top_provider.max_completion_tokens", 8192, None),
                FieldChange("expiration_date", None, "2030-12-31"),
            ),
        ),
    )
    kwargs = {
        "generated_at": "2026-07-15T13:05:00+00:00",
        "command": "scan",
        "provider_results": [_scan_result(changed)],
    }
    html_report = render_scan_report(format_name="html", **kwargs)

    cells = absent_side_cells(html_report)
    # Precondition: the probe found the cells it is meant to police. Without
    # this, a regex that matched nothing would satisfy the loop below vacuously.
    assert len(cells) == 9, cells
    for cell in cells:
        assert "null" not in cell, cell

    for cell in ("<td>— → 0.00000005 ($0.05 / 1M)</td>", "<td>8,192 → —</td>", "<td>— → 2030-12-31</td>"):
        assert cell in html_report, cell
    for row_label in ("Cache read", "Max output", "Expiration date"):
        assert "—" in _card_row(html_report, row_label), row_label

    # The split is closed in HTML ONLY, and deliberately: `old_display` /
    # `new_display` are shared by every renderer, so respelling them there would
    # move the text and markdown characterization goldens.
    for format_name in ("text", "markdown"):
        other = render_scan_report(format_name=format_name, **kwargs)
        assert "null → 0.00000005 ($0.05 / 1M)" in other, format_name
        assert "8,192 → null" in other, format_name


def test_an_absent_price_side_is_never_composed_with_its_operands() -> None:
    """The `changes` table must not BUILD the text it is about to throw away.

    `_render_html_table_row` used to write `f"{raw} ({display} / 1M)"`
    unconditionally and hand the result to `_html_side_display`, which
    discards it when `raw is None`. The literal string `None (null / 1M)` was
    therefore constructed on every one-sided price row in the `changes`
    report -- invisible, correct by accident, and one refactor of that helper
    away from reaching a cell.

    A count of the output cannot catch that: the old code and the new code
    render identically. What distinguishes them is whether the operands are
    TOUCHED on the absent path, so this asserts exactly that, with a display
    operand that refuses to be formatted. Restore the eager f-string and this
    raises `AssertionError` from inside the formatter.
    """

    class _RefusesToBeFormatted:
        def __str__(self) -> str:  # pragma: no cover - the raise is the point
            raise AssertionError("the absent side must not format its operands")

    assert (
        reporting._html_raw_and_normalized(None, _RefusesToBeFormatted())  # type: ignore[arg-type]
        == "—"
    )
    # The present path still composes both operands, so the guard above cannot
    # be satisfied by a helper that formats nothing at all.
    assert reporting._html_raw_and_normalized("2e-06", "$2.00") == "2e-06 ($2.00 / 1M)"


# `num` is not optional in this pattern. A price is a number, so its cell must
# carry the class that earns tabular figures and `nowrap`; a price cell that
# lost it would silently start wrapping mid-figure and this regex would stop
# matching, failing the count assertion below rather than passing quietly.
_PRICE_VALUE_CELL = re.compile(r'<td class="(?:old|new)-val num"(?: title="([^"]*)")?>([^<]*)</td>')


def test_every_price_cell_pairs_a_normalized_value_with_its_raw_value() -> None:
    """A1 promoted the normalized per-1M figure and dropped the
    `2e-06 ($2.00 / 1M)` pair the old row led with, so the provider's raw value
    now lives in the cell's `title`.

    Asserted as an invariant over EVERY price cell in the report, not just the
    two spelled out below: a row added later that showed a normalized price
    with no raw behind it -- or a raw with no normalized figure in front of it
    -- fails here without anyone having to remember to extend the test.
    """
    changed = (
        ModelDelta(
            "changed",
            "synth/model-prices",
            "Synth Prices",
            (
                FieldChange("pricing.prompt", "0.000002", "0.0000035"),
                FieldChange("pricing.input_cache_read", None, "0.00000005"),
                FieldChange("pricing.input_cache_write", "0.00000009", None),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )

    price_rows = [row for row in _card_rows(report) if '<td class="unit">/1M</td>' in row]
    assert len(price_rows) == 3
    cells = [match for row in price_rows for match in _PRICE_VALUE_CELL.findall(row)]
    assert len(cells) == 6, cells
    for raw, shown in cells:
        if shown == "—":
            # The absent side of a one-sided change: nothing to show, and so
            # nothing to put in a tooltip either.
            assert raw == "", cells
            continue
        assert shown.startswith("$"), cells
        assert raw, cells
        # The tooltip is the PROVIDER's number, not a second copy of the
        # normalized one -- a title echoing the cell would be no audit trail.
        assert raw != shown, cells
        float(raw)

    row = _card_row(report, "Input")
    assert '<td class="old-val num" title="0.000002">$2.00</td>' in row
    assert '<td class="new-val num" title="0.0000035">$3.50</td>' in row


def _unscaled_price_report(old_value: str, new_value: str) -> str:
    """A provider whose raw prices are already per-1M (`price_multiplier=1`).

    The configuration that puts per-token magnitudes into a per-1M column,
    which is where the price columns meet the sentinel rule.
    """
    return render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[
            ProviderScanResult(
                provider_id="synthprov",
                provider_label="Synth Provider",
                status="success",
                current_count=1,
                saved=False,
                baseline=None,
                baseline_message=None,
                scrape_id=None,
                added=(),
                removed=(),
                changed=(
                    ModelDelta(
                        "changed",
                        "synth/model-unscaled",
                        "Synth Model Unscaled",
                        (FieldChange("pricing.prompt", old_value, new_value),),
                    ),
                ),
                error_message=None,
                price_multiplier=1,
                price_divisor=1,
            )
        ],
    )


def test_price_delta_column_renders_the_absolute_movement() -> None:
    """A1's column, and the first renderer ever to read a price
    `delta_display`.

    Until this layout, `RenderedChange.delta_display` had NO consumer on the
    price path: the text form prints the two prices and a percentage, and the
    old HTML row put the percentage in its single Change cell. A price row's
    absolute movement -- the "by how much" the report existed to answer -- was
    computed on every scan and shown nowhere.

    Both signs are asserted: the sign is what makes the column readable at a
    glance, and a formatter that dropped it would still pass a magnitude-only
    assertion.
    """
    changed = (
        ModelDelta(
            "changed",
            "synth/model-delta",
            "Synth Model Delta",
            (
                FieldChange("pricing.prompt", "0.000002", "0.0000035"),
                FieldChange("pricing.completion", "0.000004", "0.0000015"),
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )

    assert '<td class="delta sem-cost-up">+$1.50</td>' in _card_row(report, "Input")
    assert '<td class="delta sem-cost-down">-$2.50</td>' in _card_row(report, "Output")


def test_price_delta_column_renders_a_bounded_sentinel_rather_than_a_false_zero() -> None:
    """The degenerate delta, end to end, for the first time.

    The sentinel rule bounds a movement too small for the column
    (`+<$0.0001`), and `_fmt_price_per_m` has produced that string for the
    price delta since it landed -- but with no renderer reading a price
    `delta_display`, the price-delta sentinel had never reached a document.
    This is the test that exercises it.

    `$0.0000` is asserted absent from the whole report, not just this cell: a
    zero-priced delta beside two prices that differ is the defect the bound
    replaced, and it must not reappear in any column of the row.
    """
    report = _unscaled_price_report("0.000001", "0.000002")
    row = _card_row(report, "Input")

    # HTML-escaped, so the `<` goes through `html.escape` like every other
    # cell rather than being emitted raw into the document.
    assert '<td class="delta sem-cost-up">+&lt;$0.0001</td>' in row
    assert "+<$0.0001" not in report
    # The operands bound themselves at the same precision, and the percentage
    # is a real one -- the movement is reported, just not overstated.
    assert row.count("&lt;$0.0001") == 3
    assert '<td class="pct sem-cost-up">↑ 100.0%</td>' in row
    assert "$0.0000" not in report

    # The negative form takes the same bound with a leading sign.
    falling = _card_row(_unscaled_price_report("0.000002", "0.000001"), "Input")
    assert '<td class="delta sem-cost-down">-&lt;$0.0001</td>' in falling


def test_new_structured_values_expand_to_leaf_changes_in_human_reports_only() -> None:
    overrides = [
        {
            "completion": "0.0000225",
            "input_cache_read": "0.0000006",
            "min_prompt_tokens": 200000,
            "prompt": "0.000006",
        }
    ]
    changed = (
        ModelDelta(
            "changed",
            "anthropic/claude-sonnet-4",
            "Anthropic: Claude Sonnet 4",
            (FieldChange("pricing.overrides", None, overrides),),
        ),
    )

    text_report = render_scan_report(
        generated_at="2026-07-14T13:05:03+00:00",
        command="scan",
        format_name="text",
        provider_results=[_scan_result(changed)],
    )
    html_report = render_scan_report(
        generated_at="2026-07-14T13:05:03+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    json_report = render_scan_report(
        generated_at="2026-07-14T13:05:03+00:00",
        command="scan",
        format_name="json",
        provider_results=[_scan_result(changed)],
    )

    # `pricing.overrides` arrives one-sided, so `_flatten_one_sided_structure`
    # (not `_pricing_override_path`) supplies the bracketed segment and the
    # qualifier is a LIST INDEX. It renders "#0" so the parenthetical reads as
    # an ordinal rather than as a stray value in a row full of values.
    assert "Output (#0): null \u2192 0.0000225 ($22.50 / 1M)" in text_report
    assert "Cache read (#0): null \u2192 0.0000006 ($0.60 / 1M)" in text_report
    assert "Min prompt tokens (#0): null \u2192 200,000" in text_report
    assert "$200" not in text_report
    # The qualifier is required here too. A bare `assert "Input" in html_report`
    # passes whether or not the HTML renderer qualified the row, which makes it
    # weaker than its three text siblings above rather than merely shorter.
    assert "Input (#0)" in html_report
    assert "$6.00 / 1M" in html_report
    assert '"field_name": "pricing.overrides"' in json_report
    assert '"field_name": "pricing.overrides[0].prompt"' not in json_report


def test_existing_pricing_override_tiers_render_only_changed_leaves() -> None:
    old_overrides = [
        {
            "completion": "0.000012",
            "input_cache_read": "0.000001",
            "min_prompt_tokens": 200000,
            "prompt": "0.000004",
        },
        {
            "completion": "0.00000042",
            "prompt": "0.00000028",
            "utc_end": 1630,
            "utc_start": 30,
        },
    ]
    new_overrides = [
        {
            "completion": "0.00000042",
            "prompt": "0.00000028",
            "utc_end": 1630,
            "utc_start": 30,
        },
        {
            "completion": "0.000012",
            "input_cache_read": "0.0000006",
            "min_prompt_tokens": 200000,
            "prompt": "0.000004",
        },
    ]
    changed = (
        ModelDelta(
            "changed",
            "x-ai/grok-4.5",
            "xAI: Grok 4.5",
            (FieldChange("pricing.overrides", old_overrides, new_overrides),),
        ),
    )

    text_report = render_scan_report(
        generated_at="2026-07-19T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[_scan_result(changed)],
    )
    html_report = render_scan_report(
        generated_at="2026-07-19T13:05:05+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    json_report = render_scan_report(
        generated_at="2026-07-19T13:05:05+00:00",
        command="scan",
        format_name="json",
        provider_results=[_scan_result(changed)],
    )

    field_name = "pricing.overrides[min_prompt_tokens=200000].input_cache_read"
    label, qualifier = resolve_field_label(field_name)
    assert (label, qualifier) == ("Cache read", "min_prompt_tokens=200000")
    # The qualifier is what tells this tier's "Cache read" apart from the base
    # `pricing.input_cache_read`, so the rendered row must carry it. A
    # `_pricing_override_path` condition renders LITERALLY, per the design.
    display_label = format_qualified_label(label, qualifier)
    assert display_label == "Cache read (min_prompt_tokens=200000)"
    expected = f"{display_label}: 0.000001 \u2192 0.0000006 ($1.00 \u2192 $0.60 / 1M, \u2193 40.0%)"
    assert expected in text_report
    assert display_label in html_report
    assert "$1.00 \u2192 $0.60 / 1M" in html_report
    assert "Conditional pricing (2 \u2192 2)" not in text_report
    assert "utc_start=30" not in text_report
    assert '"field_name": "pricing.overrides"' in json_report
    assert field_name not in json_report


def test_pricing_override_tier_addition_and_removal_render_as_semantic_tiers() -> None:
    changed = (
        ModelDelta(
            "changed",
            "tiered-model",
            "Tiered Model",
            (
                FieldChange(
                    "pricing.overrides",
                    [{"min_prompt_tokens": 200000, "prompt": "0.000004"}],
                    [{"min_prompt_tokens": 300000, "prompt": "0.000005"}],
                ),
            ),
        ),
    )

    report = render_scan_report(
        generated_at="2026-07-19T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[_scan_result(changed)],
    )

    # Both tiers carry the same two leaves, so the tier condition is the ONLY
    # thing separating the removed tier's rows from the added tier's.
    assert "Input (min_prompt_tokens=200000): 0.000004 ($4.00 / 1M) \u2192 null" in report
    assert "Input (min_prompt_tokens=300000): null \u2192 0.000005 ($5.00 / 1M)" in report
    assert "Min prompt tokens (min_prompt_tokens=200000): 200,000 \u2192 null" in report
    assert "Min prompt tokens (min_prompt_tokens=300000): null \u2192 300,000" in report


# ---------------------------------------------------------------------------
# REGRESSION: a base price and a conditional-pricing tier must not collapse.
#
# The field-label registry resolves `pricing.prompt` and
# `pricing.overrides[min_prompt_tokens=200000].prompt` to the SAME label,
# `Input` -- deliberately, since the leaf names the field wherever it appears.
# It also records the bracketed condition as `qualifier`. While no renderer
# read `qualifier`, a model with tiered pricing showed two rows both spelled
# `Input` and a reader could not tell the base rate from the tier. The raw
# dotted paths had distinguished them before the registry existed, so this was
# information the registry removed.
#
# One fixture, three human formats. The assertion is not "the qualifier
# appears" but "the two rows differ", which is the property that was lost.
# ---------------------------------------------------------------------------

_TIERED_PRICING_MODEL = ModelDelta(
    "changed",
    "synth/model-tiered",
    "Synth Tiered",
    (
        FieldChange("pricing.prompt", "0.000001", "0.000002"),
        FieldChange(
            "pricing.overrides",
            [{"min_prompt_tokens": 200000, "prompt": "0.000004"}],
            [{"min_prompt_tokens": 200000, "prompt": "0.000005"}],
        ),
    ),
)


def _tiered_pricing_report(format_name: str) -> str:
    return render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name=format_name,
        provider_results=[_scan_result((_TIERED_PRICING_MODEL,))],
    )


def _tiered_pricing_changes_rows() -> tuple[dict, ...]:
    """The same two field changes, in the row shape the changes report takes.

    Derived from `_TIERED_PRICING_MODEL` rather than respelled, so the scan
    and changes entry points are provably fed the identical field changes and
    the fixture cannot drift between the two halves of the qualifier guard.
    """
    return tuple(
        {
            "detected_at": "2026-07-25T09:00:00+00:00",
            "provider_id": "synthprov",
            "provider_label": "Synth Provider",
            "provider_model_id": _TIERED_PRICING_MODEL.provider_model_id,
            "display_name": _TIERED_PRICING_MODEL.display_name,
            "change_kind": _TIERED_PRICING_MODEL.kind,
            "field_name": field_change.field_name,
            "old_value": field_change.old_value,
            "new_value": field_change.new_value,
        }
        for field_change in _TIERED_PRICING_MODEL.field_changes
    )


def test_base_price_and_conditional_tier_render_distinguishably_in_text() -> None:
    report = _tiered_pricing_report("text")

    base = "Input: 0.000001 → 0.000002 ($1.00 → $2.00 / 1M, ↑ 100.0%)"
    tier = "Input (min_prompt_tokens=200000): 0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)"
    assert base in report
    assert tier in report

    # The rows must not merely both exist -- they must READ differently. Count
    # the rendered field labels: exactly one bare `Input` row, exactly one
    # qualified row. A bare-`label` renderer produces two of the former.
    labels = [line.strip().split(":", 1)[0] for line in report.splitlines() if "→" in line]
    assert sorted(labels) == ["Input", "Input (min_prompt_tokens=200000)"]
    assert labels.count("Input") == 1


def test_base_price_and_conditional_tier_render_distinguishably_in_markdown() -> None:
    report = _tiered_pricing_report("markdown")

    assert "  - `Input: 0.000001 → 0.000002 ($1.00 → $2.00 / 1M, ↑ 100.0%)`" in report
    assert (
        "  - `Input (min_prompt_tokens=200000): "
        "0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)`"
    ) in report

    labels = [
        line.strip().removeprefix("- `").split(":", 1)[0]
        for line in report.splitlines()
        if line.strip().startswith("- `") and "→" in line
    ]
    assert sorted(labels) == ["Input", "Input (min_prompt_tokens=200000)"]


def test_base_price_and_conditional_tier_render_distinguishably_in_html() -> None:
    report = _tiered_pricing_report("html")

    # Change table (the per-model card). The cell also carries a `title` with
    # the full dotted path, so the pattern must tolerate attributes -- and the
    # two rows' titles are asserted below, since the qualifier is exactly what
    # distinguishes their paths.
    field_cells = re.findall(r'<td class="field-name"[^>]*>(.*?)</td>', report)
    assert sorted(field_cells) == ["Input", "Input (min_prompt_tokens=200000)"]
    assert '<td class="field-name" title="pricing.prompt">Input</td>' in report
    assert (
        '<td class="field-name" title="pricing.overrides[min_prompt_tokens=200000].prompt">'
        "Input (min_prompt_tokens=200000)</td>"
    ) in report

    # Change Summary (the other HTML path). Same requirement, separate renderer
    # input: the summary splits the already-formatted text line.
    _, summary = _scan_detail_and_summary(report)
    assert "<td>Input</td>" in summary
    assert "<td>Input (min_prompt_tokens=200000)</td>" in summary


def test_tiered_pricing_json_keeps_raw_paths_and_is_unaffected() -> None:
    """JSON is the audit path: raw `field_name`s, no labels, no qualifiers.

    `_delta_to_json` serialises `FieldChange` directly and never consults the
    registry, so this payload is byte-for-byte what b94a9d3 produced -- and
    what every commit before the registry produced.
    """
    payload = json.loads(_tiered_pricing_report("json"))
    field_changes = payload["providers"][0]["changed"][0]["field_changes"]

    assert field_changes == [
        {"field_name": "pricing.prompt", "old_value": "0.000001", "new_value": "0.000002"},
        {
            "field_name": "pricing.overrides",
            "old_value": [{"min_prompt_tokens": 200000, "prompt": "0.000004"}],
            "new_value": [{"min_prompt_tokens": 200000, "prompt": "0.000005"}],
        },
    ]
    # No display vocabulary at all: not the label, not the qualifier, and not
    # the expanded per-tier path the human renderers derive.
    raw = _tiered_pricing_report("json")
    assert "Input" not in raw
    assert "(min_prompt_tokens=200000)" not in raw
    assert "pricing.overrides[" not in raw


def _sub_cent_changes_rows() -> tuple[dict, ...]:
    """One changes-report row whose price change resolves below cents."""
    return (
        {
            "detected_at": "2026-07-25T09:00:00+00:00",
            "provider_id": "synthprov",
            "provider_label": "Synth Provider",
            "provider_model_id": "synth/model-subcent",
            "display_name": "Synth Model Subcent",
            "change_kind": "changed",
            "field_name": "pricing.prompt",
            "old_value": "0.00000015",
            "new_value": "0.0000001425",
        },
    )


def _sub_cent_changes_report(format_name: str) -> str:
    return render_changes_report(
        format_name=format_name,
        provider_id=None,
        since=None,
        until=None,
        changes=_sub_cent_changes_rows(),
        provider_pricing={"synthprov": (1000000, 1)},
    )


def test_changes_report_carries_the_shared_price_precision() -> None:
    """The changes report is a THIRD consumer of `RenderedChange`, verified here.

    It reaches the same formatter by a different route (history rows rather
    than a scan result), so "it consumes the same RenderedChange, therefore it
    follows" is an argument, not evidence. `0.15` renders at four places
    because the other operand needs four -- in the changes report's text, its
    per-model HTML table and its HTML Change Summary alike.
    """
    text = _sub_cent_changes_report("text")
    assert "($0.1500 → $0.1425 / 1M" in text

    html = _sub_cent_changes_report("html")
    assert '<td class="old-val">0.00000015 ($0.1500 / 1M)</td>' in html
    assert '<td class="new-val">0.0000001425 ($0.1425 / 1M)</td>' in html
    summary = html[html.index('<section class="summary-section">') :]
    assert "($0.1500 → $0.1425 / 1M" in summary

    # The audit path is untouched: raw values, no formatted price anywhere.
    payload = json.loads(_sub_cent_changes_report("json"))
    assert payload["changes"][0]["old_value"] == "0.00000015"
    assert payload["changes"][0]["new_value"] == "0.0000001425"
    assert "$" not in _sub_cent_changes_report("json")


# ---------------------------------------------------------------------------
# Every report entry point must surface the qualifier
#
# `RenderedChange.label` is the registry lookup with the bracketed segment
# already stripped, so it cannot identify a row on its own; only
# `display_label` re-attaches it. The guard below is BEHAVIOURAL, and replaces
# an earlier source-text assertion (`"rendered.label" not in reporting.py`)
# that could pass while the behaviour was broken -- a renderer written as
# `def _render_x(change: RenderedChange)` printing `change.label`, or reaching
# it via `getattr(rendered, "label")`, or binding `rc = rendered` first,
# contains no such substring. It also constrained what the module's own
# comments were allowed to say.
#
# The entry-point inventory is DISCOVERED from the module, not listed, so a
# seventh renderer reached through a new `render_*_report` cannot be added
# without either satisfying the qualifier assertion or being explicitly
# classified as a report that carries no field changes.
# ---------------------------------------------------------------------------

# Renders field changes, and must therefore surface the qualifier.
_FIELD_CHANGE_ENTRY_POINTS = {"render_scan_report", "render_changes_report"}
# Carries no `FieldChange` rows at all, so there is no label to qualify.
_NO_FIELD_CHANGE_ENTRY_POINTS = {
    "render_model_list_report",
    "render_providers_report",
    "render_healthcheck_report",
}
# Formats `HistoryEvent` rows directly and never builds a `RenderedChange`, so
# it prints raw dotted paths. Pinned separately below.
_RAW_PATH_ENTRY_POINTS = {"render_history_report"}


def test_every_public_report_entry_point_is_classified() -> None:
    """A new `render_*_report` must be triaged, not silently uncovered.

    This is what makes the qualifier guard below closed rather than a spot
    check: the set of entry points is read off the module, so adding one
    fails here until its qualifier behaviour is decided and asserted.
    """
    discovered = {
        name
        for name in dir(reporting)
        if name.startswith("render_") and name.endswith("_report")
    }
    assert discovered == (
        _FIELD_CHANGE_ENTRY_POINTS | _NO_FIELD_CHANGE_ENTRY_POINTS | _RAW_PATH_ENTRY_POINTS
    )
    for name in discovered:
        assert callable(getattr(reporting, name)), name


def test_every_field_change_entry_point_surfaces_the_qualifier() -> None:
    """One fixture, every entry point that renders field changes, every format.

    The fixture carries a base `pricing.prompt` move AND a conditional tier
    moving the same leaf, so the two rows collapse into an indistinguishable
    pair of `Input`s the moment any renderer prints the bare label. Asserting
    the parenthetical is present is not enough on its own -- a renderer could
    emit it for one row and not the other -- so each report is also required
    to contain a bare `Input` row and a qualified one, exactly once each.
    """
    qualified = "Input (min_prompt_tokens=200000)"

    scan_reports = {
        format_name: _tiered_pricing_report(format_name)
        for format_name in ("text", "markdown", "html")
    }
    changes_reports = _render_changes_human_formats(_tiered_pricing_changes_rows())

    rendered = {
        f"render_scan_report/{name}": _without_price_movement_card(report)
        for name, report in scan_reports.items()
    } | {
        f"render_changes_report/{name}": report for name, report in changes_reports.items()
    }
    # Precondition: every entry point classified as rendering field changes is
    # actually exercised here. Without this the loop could cover a subset.
    assert {key.split("/")[0] for key in rendered} == _FIELD_CHANGE_ENTRY_POINTS

    for key, report in rendered.items():
        assert qualified in report, f"{key} dropped the qualifier"
        # Pairing rather than a fixed count, because the number of render
        # SITES differs by format: HTML prints every label twice (the per-model
        # change table and the Change Summary), text and markdown once. What
        # holds in all of them is that each site emits the two rows together,
        # so bare and qualified occurrences must come in equal numbers. Every
        # qualified occurrence also contains the bare substring, hence the 2x.
        #
        # This is what fails when a renderer prints the bare label: the
        # collapsed site contributes two bare `Input`s and no qualified one,
        # and the equality breaks. A fixed count would have had to be spelled
        # per format, and would then pass for a format nobody updated.
        #
        # The pairing is why the scan HTML is counted with its Price Movement
        # card removed. Task 8's headline mover is the first render site that
        # emits ONE of the two rows by construction -- the biggest mover, not
        # both -- so it breaks the parity identity in whichever direction it
        # picks, and no arithmetic here can hold for a site that is not a pair.
        # Its qualifier behaviour is not thereby unguarded: it has its own
        # test, `test_price_movement_headline_prints_the_qualified_label`,
        # whose fixture makes the CONDITIONAL tier the biggest mover so that a
        # bare-`label` renderer is what fails it.
        assert report.count(qualified) >= 1, key
        assert report.count("Input") == 2 * report.count(qualified), key


def test_history_report_entry_point_prints_raw_paths_not_collapsed_labels() -> None:
    """The one entry point exempt from the qualifier rule, and why it is safe.

    `render_history_report` never builds a `RenderedChange`, so it has no
    label to collapse -- it prints the raw dotted path, which is strictly more
    specific than a qualified label. The exemption is therefore a real
    property of its output, not an untested carve-out: if it ever starts
    routing through the registry, this test fails and it joins the guard above.
    """
    events = (
        HistoryEvent(
            detected_at="2026-07-25T09:00:00+00:00",
            change_kind="changed",
            field_name="pricing.overrides[min_prompt_tokens=200000].prompt",
            old_value="0.000004",
            new_value="0.000005",
        ),
    )
    report = render_history_report(
        provider_id="synthprov",
        model_id="synth/model-tiered",
        format_name="text",
        first_seen="2026-07-01T09:00:00+00:00",
        last_seen="2026-07-25T09:00:00+00:00",
        events=events,
    )

    assert "pricing.overrides[min_prompt_tokens=200000].prompt" in report
    assert "Input" not in report


def test_unmatchable_pricing_overrides_keep_full_fidelity_list_fallback() -> None:
    """Overrides with no identifiable condition fall back to a whole-list diff.

    `_index_pricing_overrides` returns None when no tier carries one of the
    condition fields, so there is nothing to pair tiers on and no per-leaf
    expansion happens. The row must then keep the complete old and new member
    text rather than losing the values it could not align.
    """
    changed = (
        ModelDelta(
            "changed",
            "unidentified-tier-model",
            "Unidentified Tier Model",
            (
                FieldChange(
                    "pricing.overrides",
                    [{"prompt": "0.000004"}],
                    [{"prompt": "0.000005"}],
                ),
            ),
        ),
    )

    report = render_scan_report(
        generated_at="2026-07-19T13:05:05+00:00",
        command="scan",
        format_name="text",
        provider_results=[_scan_result(changed)],
    )

    # JSON quoting, not Python repr: list members are stringified by the single
    # shared `change_render._list_item_text` on both the per-model and bulk
    # paths. This assertion pinned the repr spelling before those two
    # conventions were unified.
    assert 'Conditional pricing: +{"prompt": "0.000005"}; -{"prompt": "0.000004"} (1 \u2192 1)' in report


def test_generic_new_structured_key_expands_recursively() -> None:
    changed = (
        ModelDelta(
            "changed",
            "alpha",
            "Alpha",
            (
                FieldChange(
                    "new_payload",
                    None,
                    {"tiers": [{"limit": 10, "label": "small"}, {"limit": 20, "label": "large"}]},
                ),
            ),
        ),
    )

    report = render_scan_report(
        generated_at="2026-07-14T13:05:03+00:00",
        command="scan",
        format_name="text",
        provider_results=[_scan_result(changed)],
    )

    # Two list members contribute the same two leaf names. Without the index
    # qualifier the report shows "Label" twice and "Limit" twice with nothing
    # tying a row to the member it came from.
    assert "Label (#0): null \u2192 small" in report
    assert "Label (#1): null \u2192 large" in report
    assert "Limit (#0): null \u2192 10" in report
    assert "Limit (#1): null \u2192 20" in report
    assert 'new_payload: null \u2192 {"tiers"' not in report


# ---------------------------------------------------------------------------
# E1: render-time no-op suppression. `noop` field changes (both sides null, or
# otherwise equal) are dropped by every non-JSON renderer through the single
# shared filter in `_field_display_plan`, and kept verbatim in JSON and in
# `ModelDelta.field_changes`.
# ---------------------------------------------------------------------------

_NOOP_MODEL = ModelDelta(
    "changed",
    "synth/model-noop-only",
    "Synth Noop Only",
    (FieldChange("default_parameters.temperature", None, None),),
)
_NOOP_PLUS_REAL_MODEL = ModelDelta(
    "changed",
    "synth/model-noop-mixed",
    "Synth Noop Mixed",
    (
        FieldChange("default_parameters.temperature", None, None),
        FieldChange("status", "active", "active"),
        FieldChange("expiration_date", None, "2030-12-31"),
    ),
)


def _render_all_human_formats(changed: tuple[ModelDelta, ...], **kwargs) -> dict[str, str]:
    """Render one fixture through every non-JSON scan format."""
    return {
        format_name: render_scan_report(
            generated_at="2026-07-25T09:00:00+00:00",
            command="scan",
            format_name=format_name,
            provider_results=[_scan_result(changed)],
            **kwargs,
        )
        for format_name in ("text", "markdown", "html")
    }


def _assert_no_model_card(reports: dict[str, str], model_id: str) -> None:
    """Assert no renderer gave `model_id` a card of its own.

    Checks the per-format card markers rather than bare substring absence: the
    model id legitimately appears inside the provider-level `no-op` rollup's
    model list, which is the whole point of the rollup.
    """
    assert f"* {model_id} (" not in reports["text"]
    assert f"- `{model_id}` - " not in reports["markdown"]
    assert f'<div class="model-card-header"><code>{model_id}</code>' not in reports["html"]


def test_noop_rows_are_absent_from_every_human_format() -> None:
    for format_name, report in _render_all_human_formats((_NOOP_PLUS_REAL_MODEL,)).items():
        # Both noop forms: null -> null, and equal non-null values. Asserted on
        # the rendered field-name/value pair, not on the bare word "active",
        # which any future CSS class or markup could contain.
        assert "Temperature" not in report, format_name
        assert "status: active" not in report, format_name
        assert '<td class="field-name">status</td>' not in report, format_name
        # The real change on the same model still renders.
        assert "Expiration date" in report, format_name


def test_noop_only_model_gets_no_card_at_all() -> None:
    """A model whose every change is a noop has nothing to report, so it must
    not consume a card, a header, or a summary row."""
    reports = _render_all_human_formats((_NOOP_MODEL,))
    _assert_no_model_card(reports, "synth/model-noop-only")
    assert "Temperature" not in reports["text"]
    assert "Temperature" not in reports["markdown"]
    assert "Temperature" not in reports["html"]


def test_noop_rows_are_suppressed_in_all_detail_mode_too() -> None:
    """`--detail all` is the audit view, but E1 is a correctness fix, not a
    verbosity setting: `_field_display_plan` returns early for mode="all", so
    the filter has to run before that early return."""
    policy = ReportDetailPolicy(
        mode="all",
        show_fields=DEFAULT_REPORT_SHOW_FIELDS,
        squelch_fields=("benchmarks", "benchmarks.*"),
        unclassified_limit=20,
    )
    for format_name, report in _render_all_human_formats(
        (_NOOP_PLUS_REAL_MODEL,), detail_policy=policy
    ).items():
        assert "Temperature" not in report, format_name
        assert "Expiration date" in report, format_name


def test_noop_rows_remain_in_json() -> None:
    """Suppression is render-time only. JSON is the audit path and must not
    silently drop records."""
    payload = json.loads(
        render_scan_report(
            generated_at="2026-07-25T09:00:00+00:00",
            command="scan",
            format_name="json",
            provider_results=[_scan_result((_NOOP_MODEL,))],
        )
    )
    changed = payload["providers"][0]["changed"]
    assert [entry["provider_model_id"] for entry in changed] == ["synth/model-noop-only"]
    assert changed[0]["field_changes"] == [
        {"field_name": "default_parameters.temperature", "old_value": None, "new_value": None}
    ]


def test_noop_suppression_does_not_mutate_the_model_delta() -> None:
    """`noop` entries stay in `ModelDelta.field_changes` (and therefore in
    whatever the storage layer persists) after a human render."""
    changed = (_NOOP_PLUS_REAL_MODEL,)
    _render_all_human_formats(changed)
    assert changed[0].field_changes == (
        FieldChange("default_parameters.temperature", None, None),
        FieldChange("status", "active", "active"),
        FieldChange("expiration_date", None, "2030-12-31"),
    )


def test_noop_rows_are_absent_from_the_changes_report() -> None:
    def _row(field_name, old_value, new_value):
        return {
            "detected_at": "2026-07-25T09:00:00+00:00",
            "provider_id": "openrouter",
            "provider_label": "OpenRouter",
            "provider_model_id": "alpha",
            "display_name": "Alpha",
            "change_kind": "changed",
            "field_name": field_name,
            "old_value": old_value,
            "new_value": new_value,
        }

    changes = (
        _row("default_parameters.temperature", None, None),
        _row("expiration_date", None, "2030-12-31"),
    )
    for format_name in ("text", "html"):
        report = render_changes_report(
            format_name=format_name,
            provider_id=None,
            since=None,
            until=None,
            changes=changes,
            provider_pricing={"openrouter": (1, 1)},
        )
        assert "Temperature" not in report, format_name
        assert "Expiration date" in report, format_name

    payload = json.loads(
        render_changes_report(
            format_name="json",
            provider_id=None,
            since=None,
            until=None,
            changes=changes,
            provider_pricing={"openrouter": (1, 1)},
        )
    )
    assert [row["field_name"] for row in payload["changes"]] == [
        "default_parameters.temperature",
        "expiration_date",
    ]


# ---------------------------------------------------------------------------
# E1 follow-up: when EVERY model under a heading is no-op-only, the heading
# must not be left standing over nothing, and the dropped rows must be
# accounted for -- the same contract the pre-existing squelched-only path
# already honours through its provider rollup.
# ---------------------------------------------------------------------------


def _noop_change_row(field_name: str = "default_parameters.temperature") -> dict:
    return {
        "detected_at": "2026-07-25T09:00:00+00:00",
        "provider_id": "synthprov",
        "provider_label": "Synth Provider",
        "provider_model_id": "synth/model-noop-only",
        "display_name": "Synth Noop Only",
        "change_kind": "changed",
        "field_name": field_name,
        "old_value": None,
        "new_value": None,
    }


def _noop_only_changes_report(format_name: str) -> str:
    return render_changes_report(
        format_name=format_name,
        provider_id=None,
        since=None,
        until=None,
        changes=(_noop_change_row(),),
        provider_pricing={"synthprov": (1, 1)},
    )


def test_scan_markdown_changed_section_is_never_an_empty_heading() -> None:
    """`### Changed (1)` used to be emitted with nothing at all beneath it --
    not even the `- None` that `Added (0)`/`Removed (0)` get."""
    markdown = _render_all_human_formats((_NOOP_MODEL,))["markdown"]
    section = markdown.split("### Changed (1)", 1)[1].strip()
    assert section, "Changed section rendered as a bare heading"
    assert "no-op: `1` field change across `1` model" in section
    assert "No-op models: `synth/model-noop-only`" in section


def test_scan_markdown_falls_back_to_none_when_a_section_has_no_body() -> None:
    """The `- None` fallback is what guarantees the invariant even for a future
    suppression reason that produces no rollup of its own."""
    markdown = _render_all_human_formats(())["markdown"]
    changed_section = markdown.split("### Changed (0)", 1)[1].strip()
    assert changed_section == "- None"


def test_scan_html_omits_the_changed_heading_when_no_card_survives() -> None:
    """`<h3>Changed</h3>` with no cards after it was the HTML symptom.

    F1 moved the rollup card that used to justify this heading into tier 2 --
    a provider-level rollup is not a change, so it never earns a place above
    the disclosure -- and no model card survives here. So the heading must now
    be absent ENTIRELY rather than present over a rollup, and the rollup must
    be findable inside the disclosure. Both halves are asserted: dropping the
    second would let a report that rendered no rollup at all pass.
    """
    html = _render_all_human_formats((_NOOP_MODEL,))["html"]
    primary, secondary = _scan_tiers(html)
    assert "<h3>Changed</h3>" not in html
    assert '<div class="category-label">no-op</div>' not in primary
    assert '<div class="category-label">no-op</div>' in secondary
    assert "1 field change across 1 model" in secondary


def test_scan_html_provider_section_is_never_a_bare_heading() -> None:
    """A provider `<h2>` always presides over something."""
    result = _scan_result(
        (_NOOP_MODEL,),
        provider_id="synthprov",
        provider_label="Synth Provider",
    )
    html = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[result],
    )
    # The section exists only because the rollup card fills it.
    assert '<section class="provider-section">' in html
    body = _html_section_body(html, "</h2>")
    assert body, "provider section rendered as a bare <h2>"
    assert '<div class="category-label">no-op</div>' in body


def test_scan_html_emits_no_provider_section_when_the_body_would_be_empty() -> None:
    """A provider section reduced to its `<h2>` is suppressed outright.

    Drives `_render_scan_html`'s `len(section_parts) == 1` guard directly. A
    `ModelDelta` carrying no field changes still counts toward `change_count`
    -- that is a record count -- so the section loop is entered, but nothing
    survives planning and no rollup stands in for it. The counter on the
    provider card still reports the record.
    """
    empty = ModelDelta("changed", "synth/model-empty", "Synth Empty", ())
    html = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[
            _scan_result((empty,), provider_id="synthprov", provider_label="Synth Provider")
        ],
    )
    assert '<section class="provider-section">' not in html
    assert "synth/model-empty" not in html
    assert '<div class="provider-badge">1 change</div>' in html


def test_scan_html_keeps_the_section_of_an_error_provider_with_no_body() -> None:
    """The `result.status != "error"` half of the same guard.

    An error provider whose message never made it into the result still
    reduces to a bare `<h2>`, and that section is deliberately kept: the
    provider card above says ERROR and the section is where a reader looks
    for it.
    """
    html = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[
            _scan_result(
                (),
                provider_id="synthprov",
                provider_label="Synth Provider",
                status="error",
                error_message=None,
            )
        ],
    )
    # `"Synth Provider" in html` cannot fail here: the provider-card block
    # above the sections carries the label in every render, including one where
    # this section was dropped. Assert instead that the surviving section is
    # this provider's own -- its `<h2>` -- and that it is all the section has.
    sections = _scan_html_provider_sections(html)
    assert sections == [
        '<h2>Synth Provider <span class="provider-id">(synthprov)</span></h2>'
    ]
    assert _html_section_body(html, "</h2>") == ""


def test_changes_text_report_omits_date_and_provider_when_nothing_survives() -> None:
    """The date heading, its `----` rule and the provider label used to be
    emitted with nothing underneath."""
    report = _noop_only_changes_report("text")
    assert "Synth Provider" in report
    assert "no-op: 1 field change across 1 model" in report
    assert "models: synth/model-noop-only" in report
    # Nothing is left dangling: the provider label is always followed by content.
    lines = [line for line in report.splitlines() if line.strip()]
    assert lines[-1].strip() == "models: synth/model-noop-only"
    assert "* synth/model-noop-only" not in report


def test_changes_html_report_omits_date_and_provider_when_nothing_survives() -> None:
    report = _noop_only_changes_report("html")
    body = _html_section_body(report, "<h3>Synth Provider</h3>")
    assert body, "provider heading rendered with nothing beneath it"
    assert '<div class="category-label">no-op</div>' in body
    assert '<div class="model-card-header"><code>synth/model-noop-only</code>' not in report


def test_changes_report_drops_a_date_section_with_no_surviving_provider() -> None:
    """With no rollup to carry it, a date whose every model is invisible must
    emit no section, not an orphan heading. Exercised through a model whose
    change rows carry no field name at all -- the pre-existing empty-plan case
    the four skip guards used to leave dangling."""
    row = _noop_change_row()
    row["field_name"] = None
    for format_name in ("text", "html"):
        report = render_changes_report(
            format_name=format_name,
            provider_id=None,
            since=None,
            until=None,
            changes=(row,),
            provider_pricing={"synthprov": (1, 1)},
        )
        assert "2026-07-25" not in report, format_name
        assert "Synth Provider" not in report, format_name


def test_noop_rollup_counts_every_dropped_row_not_just_whole_models() -> None:
    """Accounting is per field change, exactly like the squelched rollup: a
    model that still renders but lost a no-op row is counted too."""
    text = _render_all_human_formats((_NOOP_MODEL, _NOOP_PLUS_REAL_MODEL))["text"]
    assert "no-op: 3 field changes across 2 models" in text
    assert "models: synth/model-noop-mixed, synth/model-noop-only" in text


def test_noop_rollup_is_absent_when_nothing_was_dropped() -> None:
    """The rollup is accounting, not decoration -- a clean report never shows it."""
    clean = ModelDelta(
        "changed",
        "synth/model-clean",
        "Synth Clean",
        (FieldChange("expiration_date", None, "2030-12-31"),),
    )
    for format_name, report in _render_all_human_formats((clean,)).items():
        assert "no-op" not in report, format_name


# ---------------------------------------------------------------------------
# `changes --format html` with anything other than a plain field change used to
# raise `AttributeError: 'tuple' object has no attribute 'category'`: the added,
# removed and squelched paths appended raw 5-tuples to the same list
# `_summary_entry_sort_key` reads `_SummaryEntry` attributes off.
# ---------------------------------------------------------------------------


def _mixed_changes_rows() -> tuple[dict, ...]:
    def _row(**overrides) -> dict:
        row = {
            "detected_at": "2026-07-25T09:00:00+00:00",
            "provider_id": "synthprov",
            "provider_label": "Synth Provider",
            "provider_model_id": "synth/model-changed",
            "display_name": "Synth Changed",
            "change_kind": "changed",
            "field_name": "expiration_date",
            "old_value": None,
            "new_value": "2030-12-31",
        }
        row.update(overrides)
        return row

    return (
        _row(
            change_kind="added",
            provider_model_id="synth/model-new",
            display_name="Synth New",
            field_name=None,
            new_value=None,
        ),
        _row(
            change_kind="removed",
            provider_model_id="synth/model-gone",
            display_name="Synth Gone",
            field_name=None,
            new_value=None,
        ),
        _row(),
        # `benchmarks.*` is squelched by the default detail policy.
        _row(field_name="benchmarks.design_arena", old_value=1, new_value=2),
    )


def _mixed_changes_report(format_name: str, rows: tuple[dict, ...] | None = None) -> str:
    return render_changes_report(
        format_name=format_name,
        provider_id=None,
        since=None,
        until=None,
        changes=_mixed_changes_rows() if rows is None else rows,
        provider_pricing={"synthprov": (1, 1)},
    )


def test_changes_html_renders_added_removed_and_squelched_without_crashing() -> None:
    """Each of the three used to be enough on its own to abort the render."""
    report = _mixed_changes_report("html")

    # Body: added and removed models are listed, the changed model gets a card.
    assert '<li><code>synth/model-new</code> <span class="display-name">Synth New</span></li>' in report
    assert '<li><code>synth/model-gone</code> <span class="display-name">Synth Gone</span></li>' in report
    assert '<div class="model-card-header"><code>synth/model-changed</code>' in report

    # Summary table: one row per record, sorted by category rank, and the
    # squelched field change is accounted for rather than silently dropped.
    summary = report.split('<section class="summary-section">', 1)[1]
    assert "<td>Added</td><td>Synth Provider</td><td><code>synth/model-new</code></td>" in summary
    assert "<td>Removed</td><td>Synth Provider</td><td><code>synth/model-gone</code></td>" in summary
    assert "<td>Squelched</td>" in summary
    assert "1 field change hidden by report detail policy" in summary
    assert "benchmarks, benchmarks.*" in summary
    # Category rank puts field changes before Added/Removed/Squelched.
    assert summary.index("<td>Added</td>") < summary.index("<td>Removed</td>") < summary.index("<td>Squelched</td>")
    assert summary.index("synth/model-changed") < summary.index("<td>Added</td>")


def test_changes_html_keeps_added_and_removed_beside_a_squelched_change() -> None:
    """Added, Removed and Squelched reach the summary table together.

    Each was its own raw-5-tuple site, so each could abort the render alone.
    The fixture drops the only non-squelched field change; the added and removed
    rows carry `field_name=None` and so survive that filter untouched, which is
    the point of the test -- all three categories must be present at once.
    """
    rows = tuple(row for row in _mixed_changes_rows() if row["field_name"] != "expiration_date")
    assert [row["change_kind"] for row in rows] == ["added", "removed", "changed"]
    report = _mixed_changes_report("html", rows)

    # Body: the presence rows are listed, not merely counted somewhere.
    assert '<li><code>synth/model-new</code> <span class="display-name">Synth New</span></li>' in report
    assert '<li><code>synth/model-gone</code> <span class="display-name">Synth Gone</span></li>' in report

    summary = report.split('<section class="summary-section">', 1)[1]
    assert "<td>Added</td><td>Synth Provider</td><td><code>synth/model-new</code></td>" in summary
    assert "<td>Removed</td><td>Synth Provider</td><td><code>synth/model-gone</code></td>" in summary
    assert "<td>Squelched</td>" in summary
    # The squelched field is accounted for by the rollup, never spelled out.
    assert "Design arena" not in report


def test_changes_html_renders_a_provider_whose_only_record_is_squelched() -> None:
    """The scenario the previous test's name promised but never built.

    One provider, one model, one row, and that row is squelched. Nothing added,
    nothing removed, no visible field change: the squelched accounting is the
    only thing standing between the `<h3>` and an empty section, and the only
    thing that can put this provider in the summary table at all.
    """
    rows = tuple(
        row for row in _mixed_changes_rows() if row["field_name"] == "benchmarks.design_arena"
    )
    assert len(rows) == 1
    report = _mixed_changes_report("html", rows)

    body = _html_section_body(report, "<h3>Synth Provider</h3>")
    assert body, "provider heading rendered with nothing beneath it"
    # Per-model card, then the provider-level rollup that justifies the heading.
    assert '<div class="category-label">Squelched</div>' in body
    assert "1 field change hidden by report detail policy" in body
    assert '<div class="category-label">squelched</div>' in body
    assert "1 field change across 1 model" in body

    summary = report.split('<section class="summary-section">', 1)[1]
    assert "<td>Squelched</td>" in summary
    # Nothing is invented: no presence record exists, so no presence row may.
    assert "<td>Added</td>" not in summary
    assert "<td>Removed</td>" not in summary
    assert "synth/model-new" not in report
    assert "synth/model-gone" not in report
    assert "Design arena" not in report


def test_changes_text_and_json_are_unaffected_by_the_html_summary_fix() -> None:
    """The other two formats never went through `_build_html_summary_table`."""
    text = _mixed_changes_report("text")
    assert "synth/model-new" in text
    assert "synth/model-gone" in text

    payload = json.loads(_mixed_changes_report("json"))
    assert [(row["change_kind"], row["provider_model_id"], row["field_name"]) for row in payload["changes"]] == [
        ("added", "synth/model-new", None),
        ("removed", "synth/model-gone", None),
        ("changed", "synth/model-changed", "expiration_date"),
        ("changed", "synth/model-changed", "benchmarks.design_arena"),
    ]


# ---------------------------------------------------------------------------
# One model can record several changes inside a single date bucket -- more than
# one scan a day is routine. `_plan_changes_report_provider` used to read
# `model_changes[0]["change_kind"]` for the whole model and `continue` on a
# presence kind, so everything recorded after the first row was discarded:
# added-then-removed rendered as merely "added", added-then-field-changed lost
# all its field changes, and (the mirror case) field-changed-then-removed lost
# the removal, because `_field_changes_from_change_rows` skips rows with no
# field name. The record count in the header kept counting what the body no
# longer showed.
# ---------------------------------------------------------------------------


def _churn_row(change_kind: str, *, field_name: str | None, minute: int) -> dict:
    """One record for a single model on a single date.

    09:00 and 09:30 UTC land on the same local date under every UTC offset, so
    the two records share a date bucket wherever the suite runs.
    """
    return {
        "detected_at": f"2026-07-25T09:{minute:02d}:00+00:00",
        "provider_id": "synthprov",
        "provider_label": "Synth Provider",
        "provider_model_id": "synth/model-churn",
        "display_name": "Synth Churn",
        "change_kind": change_kind,
        "field_name": field_name,
        "old_value": None,
        # Storage writes NULL values for a presence record.
        "new_value": "2030-12-31" if field_name else None,
    }


def _render_changes_human_formats(rows: tuple[dict, ...]) -> dict[str, str]:
    """`changes` has no markdown renderer of its own -- `--format` offers only
    text and json, and html is generated internally. `format_name="markdown"`
    falls through to the text branch, so it is rendered here and pinned as
    identical rather than claimed as separate coverage: whoever adds a real
    markdown branch will be told by that assertion to extend these tests."""
    reports = {
        format_name: render_changes_report(
            format_name=format_name,
            provider_id=None,
            since=None,
            until=None,
            changes=rows,
            provider_pricing={"synthprov": (1, 1)},
        )
        for format_name in ("text", "markdown", "html")
    }
    assert reports["markdown"] == reports["text"], "changes grew a markdown branch"
    return reports


def _changes_json_kinds(rows: tuple[dict, ...]) -> list[tuple[str, str | None]]:
    payload = json.loads(
        render_changes_report(
            format_name="json", provider_id=None, since=None, until=None, changes=rows
        )
    )
    return [(row["change_kind"], row["field_name"]) for row in payload["changes"]]


def test_changes_report_keeps_both_presence_events_recorded_on_one_date() -> None:
    """A model added and removed the same day must not claim to be merely added.

    The report is a log of recorded events; the date bucket is a display
    grouping, not a merge. Both records happened, so both are shown, in the
    order they were recorded.
    """
    rows = (
        _churn_row("added", field_name=None, minute=0),
        _churn_row("removed", field_name=None, minute=30),
    )
    reports = _render_changes_human_formats(rows)

    for format_name in ("text", "markdown"):
        report = reports[format_name]
        # The header counts two records; the body has to show two.
        assert "2 changes across 1 date" in report, format_name
        assert "      + synth/model-churn (Synth Churn)" in report, format_name
        assert "      - synth/model-churn (Synth Churn)" in report, format_name
        assert report.index("      + synth/") < report.index("      - synth/"), format_name

    body = _html_section_body(reports["html"], "<h3>Synth Provider</h3>")
    assert '<ul class="model-list added-list">' in body
    assert '<ul class="model-list removed-list">' in body
    assert body.count("<code>synth/model-churn</code>") == 2

    summary = reports["html"].split('<section class="summary-section">', 1)[1]
    assert "<td>Added</td><td>Synth Provider</td><td><code>synth/model-churn</code></td>" in summary
    assert "<td>Removed</td><td>Synth Provider</td><td><code>synth/model-churn</code></td>" in summary

    assert _changes_json_kinds(rows) == [("added", None), ("removed", None)]


def test_changes_report_keeps_field_changes_recorded_after_an_addition() -> None:
    """The `continue` after a presence kind threw away the rest of the model."""
    rows = (
        _churn_row("added", field_name=None, minute=0),
        _churn_row("field_changed", field_name="expiration_date", minute=30),
    )
    reports = _render_changes_human_formats(rows)

    for format_name in ("text", "markdown"):
        report = reports[format_name]
        assert "2 changes across 1 date" in report, format_name
        assert "      + synth/model-churn (Synth Churn)" in report, format_name
        assert "      * synth/model-churn (Synth Churn)" in report, format_name
        assert "Expiration date: null \u2192 2030-12-31" in report, format_name

    body = _html_section_body(reports["html"], "<h3>Synth Provider</h3>")
    assert '<ul class="model-list added-list">' in body
    assert '<div class="model-card-header"><code>synth/model-churn</code>' in body
    assert "Expiration date" in body

    summary = reports["html"].split('<section class="summary-section">', 1)[1]
    assert "<td>Added</td><td>Synth Provider</td><td><code>synth/model-churn</code></td>" in summary
    assert "Expiration date" in summary

    assert _changes_json_kinds(rows) == [("added", None), ("field_changed", "expiration_date")]


def test_changes_report_keeps_a_removal_recorded_after_a_field_change() -> None:
    """The mirror of the same defect, reached by row order rather than by kind.

    With a field change first the model was planned as `changed`, and the
    removal -- carrying no field name -- was dropped by
    `_field_changes_from_change_rows`. Neither branch of the collapse survives.
    """
    rows = (
        _churn_row("field_changed", field_name="expiration_date", minute=0),
        _churn_row("removed", field_name=None, minute=30),
    )
    reports = _render_changes_human_formats(rows)

    for format_name in ("text", "markdown"):
        report = reports[format_name]
        assert "2 changes across 1 date" in report, format_name
        assert "      - synth/model-churn (Synth Churn)" in report, format_name
        assert "      * synth/model-churn (Synth Churn)" in report, format_name
        assert "Expiration date: null \u2192 2030-12-31" in report, format_name

    body = _html_section_body(reports["html"], "<h3>Synth Provider</h3>")
    assert '<ul class="model-list removed-list">' in body
    assert '<div class="model-card-header"><code>synth/model-churn</code>' in body

    summary = reports["html"].split('<section class="summary-section">', 1)[1]
    assert "<td>Removed</td><td>Synth Provider</td><td><code>synth/model-churn</code></td>" in summary
    assert "Expiration date" in summary

    assert _changes_json_kinds(rows) == [("field_changed", "expiration_date"), ("removed", None)]


def test_changes_report_still_renders_a_lone_presence_record() -> None:
    """The single-record case the collapse happened to get right stays right."""
    rows = (_churn_row("added", field_name=None, minute=0),)
    reports = _render_changes_human_formats(rows)
    assert "1 change across 1 date" in reports["text"]
    assert "      + synth/model-churn (Synth Churn)" in reports["text"]
    assert "      - synth/model-churn" not in reports["text"]
    assert "      * synth/model-churn" not in reports["text"]
    body = _html_section_body(reports["html"], "<h3>Synth Provider</h3>")
    assert body.count("<code>synth/model-churn</code>") == 1
    assert '<ul class="model-list removed-list">' not in body


def test_changes_report_keeps_a_removal_recorded_before_a_re_addition() -> None:
    """The mirror of the added-then-removed ordering test, and the reason the
    presence rows are kept in RECORDED order rather than sorted by kind.

    Removed-then-added is a model coming back; added-then-removed is a model
    that did not last the day. They are different stories about the same two
    records, and the only thing that tells them apart in the rendered report is
    which line comes first. Sorting `presence_rows` by kind -- an inviting
    tidy-up -- would silently rewrite half of them, and with only the
    added-then-removed fixture in the suite it would still be green.
    """
    rows = (
        _churn_row("removed", field_name=None, minute=0),
        _churn_row("added", field_name=None, minute=30),
    )
    reports = _render_changes_human_formats(rows)

    for format_name in ("text", "markdown"):
        report = reports[format_name]
        assert "2 changes across 1 date" in report, format_name
        assert "      - synth/model-churn (Synth Churn)" in report, format_name
        assert "      + synth/model-churn (Synth Churn)" in report, format_name
        assert report.index("      - synth/") < report.index("      + synth/"), format_name

    assert _changes_json_kinds(rows) == [("removed", None), ("added", None)]


def test_changes_report_rolls_up_a_squelched_change_recorded_after_an_addition() -> None:
    """A presence row first no longer costs the model its field-row planning.

    The old `continue` fired on the first row's kind, so a model whose bucket
    opened with `added` never reached `_field_display_plan` at all: its field
    rows were not planned, contributed nothing to the provider squelched
    rollup, and put no `Squelched` row in the Change Summary. The addition was
    reported and the squelched change simply evaporated -- unaccounted for
    rather than deliberately hidden.
    """
    rows = (
        _churn_row("added", field_name=None, minute=0),
        _churn_row("field_changed", field_name="benchmarks.design_arena", minute=30),
    )
    rows = (rows[0], {**rows[1], "old_value": 1, "new_value": 2})
    reports = _render_changes_human_formats(rows)

    text = reports["text"]
    assert "      + synth/model-churn (Synth Churn)" in text
    # The model keeps a line of its own carrying the hidden-detail summary...
    assert "      * synth/model-churn (Synth Churn)" in text
    assert "1 field change hidden by report detail policy" in text
    # ...and the provider-level rollup accounts for it once more, by pattern.
    assert "      squelched: 1 field change across 1 model" in text
    assert "patterns: benchmarks, benchmarks.*" in text
    assert "models: synth/model-churn" in text
    # Never spelled out: it is squelched, not merely relocated.
    assert "Design arena" not in text

    body = _html_section_body(reports["html"], "<h3>Synth Provider</h3>")
    assert '<ul class="model-list added-list">' in body
    assert '<div class="category-label">Squelched</div>' in body
    assert '<div class="category-label">squelched</div>' in body
    assert "1 field change across 1 model" in body

    summary = reports["html"].split('<section class="summary-section">', 1)[1]
    assert "<td>Added</td><td>Synth Provider</td><td><code>synth/model-churn</code></td>" in summary
    assert "<td>Squelched</td>" in summary

    assert _changes_json_kinds(rows) == [("added", None), ("field_changed", "benchmarks.design_arena")]


def test_changes_report_charges_a_post_addition_field_to_the_unclassified_budget() -> None:
    """The same `continue` also let a skipped model's fields dodge the budget.

    `unclassified_remaining` is a per-provider allowance threaded across models
    in order. A model whose bucket opened with a presence row used to be skipped
    before it could spend any of it, so a LATER model was shown an unclassified
    field that the budget had already been claimed for. The allowance is one, so
    exactly one of these two models may spell its field out -- and it must be
    the first one, which is the one that recorded it first.
    """
    def _row(model_id: str, display_name: str, change_kind: str, field_name: str | None, minute: int) -> dict:
        return {
            "detected_at": f"2026-07-25T09:{minute:02d}:00+00:00",
            "provider_id": "synthprov",
            "provider_label": "Synth Provider",
            "provider_model_id": model_id,
            "display_name": display_name,
            "change_kind": change_kind,
            "field_name": field_name,
            "old_value": 1 if field_name else None,
            "new_value": 2 if field_name else None,
        }

    rows = (
        _row("synth/model-first", "Synth First", "added", None, 0),
        _row("synth/model-first", "Synth First", "field_changed", "synth_unclassified_first", 10),
        _row("synth/model-second", "Synth Second", "field_changed", "synth_unclassified_second", 20),
    )
    report = render_changes_report(
        format_name="text",
        provider_id=None,
        since=None,
        until=None,
        changes=rows,
        provider_pricing={"synthprov": (1, 1)},
        detail_policy=make_report_detail_policy(unclassified_limit=1),
    )

    assert "      + synth/model-first (Synth First)" in report
    # The first model spends the allowance...
    assert "Synth unclassified first: 1 → 2" in report
    # ...so the second model's field is hidden and counted, not rendered.
    assert "synth_unclassified_second" not in report
    assert "1 additional unclassified field change hidden" in report


def test_json_output_is_unchanged_by_heading_suppression() -> None:
    """JSON is the audit path: `noop` entries stay, and no rollup leaks in."""
    scan_payload = json.loads(
        render_scan_report(
            generated_at="2026-07-25T09:00:00+00:00",
            command="scan",
            format_name="json",
            provider_results=[_scan_result((_NOOP_MODEL,))],
        )
    )
    changed = scan_payload["providers"][0]["changed"]
    assert changed[0]["field_changes"] == [
        {"field_name": "default_parameters.temperature", "old_value": None, "new_value": None}
    ]
    assert "no-op" not in json.dumps(scan_payload)

    changes_payload = json.loads(
        render_changes_report(
            format_name="json",
            provider_id=None,
            since=None,
            until=None,
            changes=(_noop_change_row(),),
            provider_pricing={"synthprov": (1, 1)},
        )
    )
    assert [row["field_name"] for row in changes_payload["changes"]] == [
        "default_parameters.temperature"
    ]
    assert "no-op" not in json.dumps(changes_payload)


def test_noop_suppression_cannot_desync_a_bulk_card_from_its_grouping_key() -> None:
    """`_list_change_signature` derives the bulk grouping key from
    `_list_diff_members`, NOT from `classify_change`, so it reports a
    difference for lists that compare equal but spell differently
    (`[1] == [True]`). E1 filters on `classify_change(...).kind`, which calls
    such a change a `noop`. If the filter ran AFTER grouping, three models
    could consolidate on a key whose only member had been suppressed, leaving
    a bulk card with a category header and no rows.

    The filter runs inside `_field_display_plan`, i.e. before
    `_bulk_change_signature` ever sees the changes, so the suppressed change
    is invisible to grouping and card alike and no such group can form.
    """
    equal_but_differently_spelled = tuple(
        ModelDelta("changed", f"synth/model-eq-{suffix}", f"Synth Eq {suffix.upper()}",
                   (FieldChange("supported_parameters", [1], [True]),))
        for suffix in ("a", "b", "c")
    )
    assert classify_change(equal_but_differently_spelled[0].field_changes[0]).kind == "noop"
    assert _list_change_signature(equal_but_differently_spelled[0].field_changes[0]) == (
        "supported_parameters",
        ("True",),
        ("1",),
    )

    reports = _render_all_human_formats(equal_but_differently_spelled)
    for format_name, report in reports.items():
        assert "Bulk change" not in report, format_name
        assert "Supported parameters" not in report, format_name
    for suffix in ("a", "b", "c"):
        _assert_no_model_card(reports, f"synth/model-eq-{suffix}")


def test_bulk_grouping_still_forms_when_the_list_change_is_real() -> None:
    """Control for the test above: an actually-differing list change is not a
    noop, is not suppressed, and still consolidates with rendered rows."""
    real = tuple(
        ModelDelta("changed", f"synth/model-real-{suffix}", f"Synth Real {suffix.upper()}",
                   (FieldChange("supported_parameters", ["tools"], ["tools", "seed"]),))
        for suffix in ("a", "b", "c")
    )
    text = _render_all_human_formats(real)["text"]
    assert "Bulk change — 3 models" in text
    assert "Supported parameters: +seed" in text


# ---------------------------------------------------------------------------
# E2: booleans render off/on, never as a percent-formatted magnitude.
# ---------------------------------------------------------------------------


def _boolean_reports(field_name: str, old_value, new_value) -> dict[str, str]:
    return _render_all_human_formats(
        (ModelDelta("changed", "synth/model-flag", "Synth Flag", (FieldChange(field_name, old_value, new_value),)),)
    )


def test_boolean_disable_renders_on_to_off_with_no_percent() -> None:
    """Regression test for the shipped `↓ 100.0%` defect: a flag turning off
    was percent-formatted as if it were a magnitude."""
    reports = _boolean_reports("top_provider.is_moderated", True, False)
    assert "Moderated: on \u2192 off" in reports["text"]
    assert "`Moderated: on \u2192 off`" in reports["markdown"]
    row = _card_row(reports["html"], "Moderated")
    assert '<td class="old-val">on</td>' in row
    assert '<td class="new-val">off</td>' in row
    # B1: a flag is `capability`, never `cost` -- off is dim, not red.
    assert '<td class="delta sem-capability-off">disabled</td>' in row
    for format_name, report in reports.items():
        assert "%" not in report.replace("%;", ""), format_name


def test_boolean_enable_renders_off_to_on_with_a_non_empty_delta_cell() -> None:
    """Regression test for the blank-Change-cell defect: `_pct_change`
    returns "" when the old value is 0, so `False -> True` produced an empty
    delta cell. The boolean branch never reaches percent logic at all."""
    reports = _boolean_reports("top_provider.is_moderated", False, True)
    assert "Moderated: off \u2192 on" in reports["text"]
    row = _card_row(reports["html"], "Moderated")
    assert '<td class="old-val">off</td>' in row
    assert '<td class="new-val">on</td>' in row
    assert '<td class="delta sem-capability">enabled</td>' in row
    # The defect this pins is an EMPTY delta cell, whatever class it carries.
    assert not re.search(r'<td class="delta [^"]*"></td>', reports["html"])


def test_integer_coded_boolean_renders_off_to_on_with_no_percent() -> None:
    """`reasoning.default_enabled` is recorded as 0/1, not as a real bool."""
    reports = _boolean_reports("reasoning.default_enabled", 0, 1)
    assert "Reasoning default: off \u2192 on" in reports["text"]
    assert '<td class="delta sem-capability">enabled</td>' in _card_row(
        reports["html"], "Reasoning default"
    )
    for format_name, report in reports.items():
        assert "%" not in report.replace("%;", ""), format_name


def test_one_sided_boolean_renders_as_coverage_with_an_em_dash() -> None:
    """Task 4 decision: a flag appearing from nothing is presented like every
    other one-sided change -- em dash on the absent side, `added` pill in the
    delta column -- instead of leaking the raw Python repr `null -> True`."""
    reports = _boolean_reports("top_provider.is_moderated", None, True)
    assert "Moderated: \u2014 \u2192 on" in reports["text"]
    row = _card_row(reports["html"], "Moderated")
    assert '<td class="old-val">—</td>' in row
    assert '<td class="new-val">on</td>' in row
    # B1: a field appearing is `coverage` -- blue in both directions, not the
    # green/red a one-sided flag used to borrow from the numeric path.
    assert '<td class="delta sem-coverage">added</td>' in row
    assert "null → True" not in reports["text"]

    removed = _boolean_reports("top_provider.is_moderated", True, None)
    assert "Moderated: on \u2192 \u2014" in removed["text"]
    removed_row = _card_row(removed["html"], "Moderated")
    assert '<td class="new-val">—</td>' in removed_row
    assert '<td class="delta sem-coverage">removed</td>' in removed_row


def test_numeric_field_holding_zero_and_one_is_not_treated_as_a_boolean() -> None:
    """The known-boolean set is a restriction, not a blanket 0/1 rule: a
    temperature is a magnitude even when its values look like a flag's.

    NOTE: `0 -> 1` has a zero basis, so `_pct_change` yields no percentage
    for it either -- that is the pre-existing zero-basis rule, not the E2
    boolean rule. The `0.5 -> 1` case below is what proves a percent still
    reaches a genuinely numeric default_parameters field.
    """
    reports = _boolean_reports("default_parameters.temperature", 0, 1)
    assert "Temperature: 0 \u2192 1 (+1)" in reports["text"]
    assert "off" not in reports["text"]

    with_percent = _boolean_reports("default_parameters.temperature", 0.5, 1)
    assert "Temperature: 0.50 \u2192 1 (+0.50, \u2191 100.0%)" in with_percent["text"]


# ---------------------------------------------------------------------------
# Provider identity in the `changes` report.
#
# `render_changes_report` grouped by `provider_label` -- display text that
# nothing in config.py constrained to be unique -- rather than by `provider_id`.
# Two providers sharing a label always merged into one section, and where both
# listed the same `provider_model_id` their rows merged into ONE list, after
# which `rows[0]` alone decided the display name AND the price
# multiplier/divisor for every row in it. One provider's raw prices were then
# converted with the other provider's factors: wrong dollar figures, rendered
# confidently, with no error anywhere.
#
# Overlapping model ids across providers is the documented expectation
# (README: "OpenRouter and Abacus.AI are tracked independently even when they
# expose similarly named upstream models"), not an edge case.
# ---------------------------------------------------------------------------


_SHARED_LABEL = "Shared Label"

# Deliberately far apart: 1000000/1 is the per-token convention, 1/1 the
# per-1M convention. The same raw price renders six orders of magnitude apart,
# so a crossover cannot hide inside rounding.
#
# B's own two cells discriminate as well, which is what makes this fixture
# catch more than the one defect it was written for: they pin B's exact
# multiplier/divisor RATIO, so changing either factor moves the rendered pair
# and the assertions fail.
#
# That property depends on B's converted prices being PRINTABLE, and the raw
# values were chosen for it. They were `0.000001 -> 0.000002`, which under B's
# 1/1 conversion lands below the four-place column: Task 6's cap rendered both
# cells `$0.0000` and Task 6c's sentinel renders both `<$0.0001`. Either way
# two DIFFERENT B misconfigurations render alike, and the ratio pin degrades
# into "B's price is somewhere below a hundredth of a cent" -- still enough to
# catch a crossover with A, blind to a wrong divisor on B.
#
# `0.0001 -> 0.0002` (a $100/1M model, an ordinary flagship price) converts to
# `$100.00 -> $200.00` under A and `$0.0001 -> $0.0002` under B: still six
# orders of magnitude apart, still one per-token convention and one per-1M
# convention, and now both sides printable so all four assertions pin ratios
# again. What the old values exercised -- how a below-resolution price renders
# -- is covered directly, and per format, by
# `test_a_price_below_the_columns_resolution_bounds_itself_in_every_format`
# in test_render_characterization.py.
_SHARED_LABEL_PRICING = {"synthprov-a": (1000000, 1), "synthprov-b": (1, 1)}


def _shared_label_row(
    provider_id: str,
    display_name: str,
    *,
    model_id: str = "synth/shared-model",
    label: str = _SHARED_LABEL,
    **overrides,
) -> dict:
    row = {
        "detected_at": "2026-07-25T09:00:00+00:00",
        "provider_id": provider_id,
        "provider_label": label,
        "provider_model_id": model_id,
        "display_name": display_name,
        "change_kind": "changed",
        "field_name": "pricing.prompt",
        "old_value": "0.0001",
        "new_value": "0.0002",
    }
    row.update(overrides)
    return row


def _shared_label_rows() -> tuple[dict, ...]:
    return (
        _shared_label_row("synthprov-a", "Alpha Shared"),
        _shared_label_row("synthprov-b", "Beta Shared"),
    )


def _shared_label_report(format_name: str, rows: tuple[dict, ...] | None = None) -> str:
    return render_changes_report(
        format_name=format_name,
        provider_id=None,
        since=None,
        until=None,
        changes=_shared_label_rows() if rows is None else rows,
        provider_pricing=_SHARED_LABEL_PRICING,
    )


def test_changes_report_does_not_merge_two_providers_that_share_a_label() -> None:
    """Distinct `provider_id`s render as distinct sections whatever their labels.

    Identity, not display text, is the grouping key. Both providers reported a
    change, so both must appear -- and because their labels collide, each
    heading is disambiguated with its id, the form the scan report already uses.
    """
    text = _shared_label_report("text")

    assert "2 changes across 1 date" in text
    assert f"    {_SHARED_LABEL} (synthprov-a)" in text
    assert f"    {_SHARED_LABEL} (synthprov-b)" in text
    # The bare label would be a single merged heading -- exactly the defect.
    assert f"    {_SHARED_LABEL}\n" not in text
    # Two headings, two model lines: nothing collapsed into the other.
    assert text.count("* synth/shared-model") == 2

    html = _shared_label_report("html")
    assert f"<h3>{_SHARED_LABEL} (synthprov-a)</h3>" in html
    assert f"<h3>{_SHARED_LABEL} (synthprov-b)</h3>" in html
    assert f"<h3>{_SHARED_LABEL}</h3>" not in html


def test_changes_report_prices_each_shared_label_provider_with_its_own_factors() -> None:
    """The silent-wrong-numbers case, asserted on the rendered dollar values.

    Both providers report the SAME raw price change on the SAME model id under
    the SAME label. Only their configured conversion factors differ. When
    `rows[0]` chose the factors for the merged list, provider B's raw prices
    were rendered with provider A's multiplier and read as $100.00 -> $200.00
    instead of B's own conversion -- a millionfold error presented as fact.

    B's `1/1` conversion renders `$0.0001 -> $0.0002` -- an absurd-looking pair
    for a per-1M column, which is exactly the point: that absurdity is the
    visible tell of a mis-set PRICE_MULTIPLIER/PRICE_DIVISOR, and it is
    asserted here in full rather than through a bound. See the note above
    `_SHARED_LABEL_PRICING` for why the raw values are what they are.
    """
    text = _shared_label_report("text")

    # Assert the VALUES before assigning them to sections, so the wrong number
    # is what fails rather than a section split that never found its heading.
    # Under the defect these read 2 and 0: A's conversion applied to both rows.
    assert text.count("$100.00 → $200.00 / 1M") == 1
    assert text.count("$0.0001 → $0.0002 / 1M") == 1

    a_section, b_section = (
        text.split(f"{_SHARED_LABEL} (synthprov-a)", 1)[1].split(f"{_SHARED_LABEL} (synthprov-b)", 1)[0],
        text.split(f"{_SHARED_LABEL} (synthprov-b)", 1)[1],
    )
    # ...and each lands under the provider it belongs to.
    assert "Input: 0.0001 \u2192 0.0002 ($100.00 \u2192 $200.00 / 1M, \u2191 100.0%)" in a_section
    assert "Input: 0.0001 \u2192 0.0002 ($0.0001 \u2192 $0.0002 / 1M, \u2191 100.0%)" in b_section

    html = _shared_label_report("html")
    assert '<td class="old-val">0.0001 ($100.00 / 1M)</td>' in html
    assert '<td class="new-val">0.0002 ($200.00 / 1M)</td>' in html
    assert '<td class="old-val">0.0001 ($0.0001 / 1M)</td>' in html
    assert '<td class="new-val">0.0002 ($0.0002 / 1M)</td>' in html

    # The Change Summary is built from the same per-provider factors, and keeps
    # the two providers apart by the disambiguated label.
    summary = html.split('<section class="summary-section">', 1)[1]
    assert (
        f"<td>{_SHARED_LABEL} (synthprov-a)</td><td><code>synth/shared-model</code></td>"
        "<td>Input</td><td>0.0001 → 0.0002 ($100.00 → $200.00 / 1M, ↑ 100.0%)</td>"
    ) in summary
    assert (
        f"<td>{_SHARED_LABEL} (synthprov-b)</td><td><code>synth/shared-model</code></td>"
        "<td>Input</td><td>0.0001 → 0.0002 ($0.0001 → $0.0002 / 1M, ↑ 100.0%)</td>"
    ) in summary


def test_changes_report_does_not_cross_display_names_between_shared_label_providers() -> None:
    """`model_changes[0]["display_name"]` decided the name for the merged list.

    Provider B's model was announced under provider A's display name, so the
    report named a model something its own provider never called it.
    """
    text = _shared_label_report("text")
    a_section, b_section = (
        text.split(f"{_SHARED_LABEL} (synthprov-a)", 1)[1].split(f"{_SHARED_LABEL} (synthprov-b)", 1)[0],
        text.split(f"{_SHARED_LABEL} (synthprov-b)", 1)[1],
    )
    assert "* synth/shared-model (Alpha Shared)" in a_section
    assert "* synth/shared-model (Beta Shared)" in b_section
    assert "Beta Shared" not in a_section
    assert "Alpha Shared" not in b_section

    html = _shared_label_report("html")
    assert html.count('<span class="display-name">Alpha Shared</span>') == 1
    assert html.count('<span class="display-name">Beta Shared</span>') == 1


def test_changes_report_keeps_presence_records_of_shared_label_providers_apart() -> None:
    """Added/removed rows merged too -- both lists hung off one `<h3>`."""
    rows = (
        _shared_label_row(
            "synthprov-a", "Alpha Shared", change_kind="added", field_name=None,
            old_value=None, new_value=None,
        ),
        _shared_label_row(
            "synthprov-b", "Beta Shared", change_kind="removed", field_name=None,
            old_value=None, new_value=None,
        ),
    )
    text = _shared_label_report("text", rows)
    a_section, b_section = (
        text.split(f"{_SHARED_LABEL} (synthprov-a)", 1)[1].split(f"{_SHARED_LABEL} (synthprov-b)", 1)[0],
        text.split(f"{_SHARED_LABEL} (synthprov-b)", 1)[1],
    )
    assert "      + synth/shared-model (Alpha Shared)" in a_section
    assert "      - synth/shared-model" not in a_section
    assert "      - synth/shared-model (Beta Shared)" in b_section
    assert "      + synth/shared-model" not in b_section

    summary = _shared_label_report("html", rows).split('<section class="summary-section">', 1)[1]
    assert f"<td>Added</td><td>{_SHARED_LABEL} (synthprov-a)</td>" in summary
    assert f"<td>Removed</td><td>{_SHARED_LABEL} (synthprov-b)</td>" in summary


def test_changes_report_leaves_a_unique_label_undecorated() -> None:
    """Disambiguation is a response to a collision, not a new default.

    A provider whose label nobody else claims still renders bare, so existing
    reports read exactly as before.
    """
    rows = (
        _shared_label_row("synthprov-a", "Alpha Shared", label="Alpha Provider"),
        _shared_label_row("synthprov-b", "Beta Shared", label="Beta Provider"),
    )
    text = _shared_label_report("text", rows)
    assert "    Alpha Provider\n" in text
    assert "    Beta Provider\n" in text
    assert "(synthprov-a)" not in text
    assert "(synthprov-b)" not in text

    html = _shared_label_report("html", rows)
    assert "<h3>Alpha Provider</h3>" in html
    assert "<h3>Beta Provider</h3>" in html


def test_changes_report_spells_a_colliding_label_the_same_way_on_every_date() -> None:
    """The label map is built over the whole report, not per date bucket.

    Were it built per date, a date on which only one of the two colliding
    providers reported would print the bare label while the other date printed
    the disambiguated one -- the same provider, two spellings, in one document.
    """
    rows = (
        _shared_label_row("synthprov-a", "Alpha Shared", detected_at="2026-07-24T09:00:00+00:00"),
        _shared_label_row("synthprov-a", "Alpha Shared"),
        _shared_label_row("synthprov-b", "Beta Shared"),
    )
    text = _shared_label_report("text", rows)
    assert text.count(f"    {_SHARED_LABEL} (synthprov-a)") == 2
    assert f"    {_SHARED_LABEL}\n" not in text


def test_changes_json_is_unchanged_by_provider_identity_grouping() -> None:
    """JSON is the audit path and never went through the grouping at all.

    It is a flat echo of the recorded rows, so both providers' records survive
    intact, in order, with their own ids, labels, names and raw values -- no
    disambiguation suffix, no conversion applied.
    """
    payload = json.loads(_shared_label_report("json"))
    assert payload == {
        "provider_id": None,
        "since": None,
        "until": None,
        "changes": list(_shared_label_rows()),
    }
    assert "(synthprov-a)" not in json.dumps(payload)


# ---------------------------------------------------------------------------
# Task 9: page structure and impact sorting (E3-E6, F1, F2)
#
# The sort tests below are built so that each level of the key is the ONLY
# thing that can produce the asserted order. Where a weaker implementation
# would agree by accident -- alphabetical order matching coverage order, raw
# float order matching cents-rounded order -- the fixture is arranged so the
# two disagree, and the assertion follows the design.
# ---------------------------------------------------------------------------


def _priced(model_id: str, *changes: FieldChange) -> ModelDelta:
    return ModelDelta("changed", model_id, model_id.upper(), changes)


def _impact_order(changed: tuple[ModelDelta, ...]) -> list[str]:
    """Tier-1 card ids of a one-provider scan report, in document order."""
    html = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    primary, _ = _scan_tiers(html)
    return _model_card_order(primary)


def test_impact_sort_leads_with_the_largest_absolute_dollar_move() -> None:
    """F2 level 1. Alphabetical order is the reverse, so it cannot pass by luck."""
    changed = (
        _priced("synth/model-alpha", FieldChange("pricing.prompt", "0.000001", "0.0000015")),
        _priced("synth/model-bravo", FieldChange("pricing.prompt", "0.000001", "0.000004")),
        _priced("synth/model-charlie", FieldChange("pricing.prompt", "0.000001", "0.000002")),
    )
    # $0.50, $3.00 and $1.00 per 1M respectively.
    assert _impact_order(changed) == [
        "synth/model-bravo",
        "synth/model-charlie",
        "synth/model-alpha",
    ]


def test_impact_sort_breaks_a_cents_rounded_tie_with_percent() -> None:
    """F2 level 2, and the evidence that level 1's rounding is load-bearing.

    Both models move ~$1.40 per 1M, but not by the same amount to the last
    binary place: `alpha` moves $1.4012 and `zulu` $1.4004. The expected order
    is `zulu` first, and each of the two things that could produce it is ruled
    out by the fixture:

    * compared RAW, `alpha` is the larger move and would lead, so the
      `round(..., 2)` on the primary key is what creates the tie at all. Drop
      it and this ordering inverts -- which is the only way to demonstrate that
      the percent tiebreaker is reachable rather than dead code;
    * `zulu` sorts AFTER `alpha` alphabetically, and both carry zero coverage,
      so neither of the remaining two levels can produce this order either.
      Only the percent can: `zulu` moved 140% off a $1.00 base while `alpha`
      moved 14% off a $10.00 base.
    """
    changed = (
        _priced("synth/model-alpha", FieldChange("pricing.prompt", "0.00001", "0.0000114012")),
        _priced("synth/model-zulu", FieldChange("pricing.prompt", "0.000001", "0.0000024004")),
    )
    assert _impact_order(changed) == ["synth/model-zulu", "synth/model-alpha"]


def test_impact_sort_breaks_a_percent_tie_with_coverage_count() -> None:
    """F2 level 3, isolated: the two models agree on levels 1 AND 2.

    Both move $1.00 per 1M off the same $1.00 base, so the dollar key and the
    percent key are identical and only the count of price fields added or
    removed separates them. `zulu` carries two such fields and `echo` none, so
    coverage must put `zulu` FIRST -- against the alphabetical order that the
    fourth level would otherwise impose.
    """
    changed = (
        _priced("synth/model-echo", FieldChange("pricing.prompt", "0.000001", "0.000002")),
        _priced(
            "synth/model-zulu",
            FieldChange("pricing.prompt", "0.000001", "0.000002"),
            FieldChange("pricing.input_cache_read", None, "0.0000001"),
            FieldChange("pricing.input_cache_write", "0.0000002", None),
        ),
    )
    assert _impact_order(changed) == ["synth/model-zulu", "synth/model-echo"]


def test_impact_sort_falls_back_to_the_model_id() -> None:
    """F2 level 4. Identical on all three impact levels, so only the id is left."""
    changed = (
        _priced("synth/model-golf", FieldChange("pricing.prompt", "0.000001", "0.000002")),
        _priced("synth/model-foxtrot", FieldChange("pricing.prompt", "0.000001", "0.000002")),
    )
    assert _impact_order(changed) == ["synth/model-foxtrot", "synth/model-golf"]


def test_a_one_sided_price_change_sorts_at_zero_dollars() -> None:
    """A model whose only price change is an addition or a removal.

    There is no second operand, so there is no delta and no percent: the design
    ranks it at $0.00 on the primary key, below every real move, and separates
    it from other $0.00 models by coverage. `juliet` moves four TENTHS of a
    cent, which also rounds to $0.00 -- the design's stated accepted
    consequence -- and its 0.4% beats the one-sided models' absent percent.
    """
    changed = (
        _priced("synth/model-hotel", FieldChange("pricing.prompt", None, "0.000003")),
        _priced(
            "synth/model-india",
            FieldChange("pricing.prompt", "0.000001", None),
            FieldChange("pricing.completion", "0.000002", None),
        ),
        _priced("synth/model-juliet", FieldChange("pricing.prompt", "0.000001", "0.000001004")),
        _priced("synth/model-kilo", FieldChange("pricing.prompt", "0.000001", "0.000002")),
    )
    assert _impact_order(changed) == [
        # A real $1.00 move outranks every $0.00 one.
        "synth/model-kilo",
        # $0.00 by rounding, but it has a percent.
        "synth/model-juliet",
        # $0.00 with no percent; two removals outrank one addition on coverage.
        "synth/model-india",
        "synth/model-hotel",
    ]


def test_the_header_counts_models_and_names_both_units() -> None:
    """E4. `change_count` is a MODEL count; the squelched figure counts FIELDS.

    The header used to print `7 changes · 3 squelched` -- two units, one
    sentence, and nothing on the line saying so.
    """
    changed = (
        _priced("synth/model-priced", FieldChange("pricing.prompt", "0.000001", "0.000002")),
        ModelDelta(
            "changed",
            "synth/model-benched",
            "Benched",
            (FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),),
        ),
    )
    html = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    assert (
        '<h1>Model Sentinel <span class="count">'
        "— 2 of 2 models changed · 1 field change squelched</span></h1>"
    ) in html
    # The defect, spelled out: the old header would have said `2 changes`.
    assert ">— 2 changes<" not in html


def test_the_header_omits_the_squelched_clause_when_nothing_was_squelched() -> None:
    changed = (_priced("synth/model-priced", FieldChange("pricing.prompt", "0.000001", "0.000002")),)
    html = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    assert '<span class="count">— 1 of 2 models changed</span>' in html
    assert "squelched" not in html.split("</header>", 1)[0]


def test_a_squelched_card_gets_a_hidden_chip_and_no_squelch_section() -> None:
    """E3. The section this replaces was taller than the change it was hiding."""
    changed = (
        ModelDelta(
            "changed",
            "synth/model-core",
            "Core",
            (
                FieldChange("pricing.prompt", "0.000001", "0.000002"),
                FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),
                FieldChange("benchmarks.other_arena", [{"elo": 1}], [{"elo": 3}]),
            ),
        ),
    )
    html = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    primary, _ = _scan_tiers(html)
    assert (
        '<div class="model-card-header"><code>synth/model-core</code>'
        '<span class="display-name">Core</span>'
        '<span class="hidden-count" title="2 squelched">+2 hidden</span></div>'
    ) in primary
    # The per-card section is gone from the CARD. The provider-level rollup
    # still exists and still says `Squelched`, so the assertion is scoped to
    # tier 1 rather than to the whole document.
    assert '<div class="category-label">Squelched</div>' not in primary


def test_a_card_with_nothing_hidden_carries_no_chip() -> None:
    """`+0 hidden` on every card would be the clutter E3 is removing."""
    changed = (_priced("synth/model-core", FieldChange("pricing.prompt", "0.000001", "0.000002")),)
    html = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )
    # Scoped past the `<style>` block, which necessarily names the class.
    assert "hidden-count" not in html.split("</head>", 1)[1]


def _tiering_report() -> str:
    changed = (
        _priced("synth/model-priced", FieldChange("pricing.prompt", "0.000001", "0.000002")),
        ModelDelta(
            "changed",
            "synth/model-quiet",
            "Quiet",
            (FieldChange("top_provider.context_length", 1000, 2000),),
        ),
        ModelDelta(
            "changed",
            "synth/model-benched",
            "Benched",
            (FieldChange("benchmarks.design_arena", [{"elo": 1}], [{"elo": 2}]),),
        ),
    )
    return render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )


def test_only_price_changed_cards_sit_above_the_disclosure() -> None:
    """F1. A context-length change is real but is not a price move."""
    primary, secondary = _scan_tiers(_tiering_report())
    assert _model_card_order(primary) == ["synth/model-priced"]
    assert _model_card_order(secondary) == ["synth/model-quiet", "squelched"]


def test_the_change_summary_is_collapsed_and_inside_the_disclosure() -> None:
    """E6 plus F1: one disclosure, and the summary is closed within it."""
    html = _tiering_report()
    primary, secondary = _scan_tiers(html)
    assert html.count(_SECONDARY_OPEN) == 1
    assert _SCAN_SUMMARY_OPEN in secondary
    assert _SCAN_SUMMARY_OPEN not in primary
    # Closed by default: neither disclosure carries an `open` attribute.
    assert "<details class=\"secondary-changes\" open" not in html
    assert "<details class=\"summary-section\" open" not in html
    assert "<h2>Change Summary</h2>" not in html


def test_the_disclosure_summary_states_its_contents_with_counts() -> None:
    html = _tiering_report()
    assert (
        "<summary>Other changes — 1 model with no price change · "
        "1 report-detail rollup · the Change Summary</summary>"
    ) in html


def test_the_change_summary_drops_the_provider_column_for_one_provider() -> None:
    """E5, applied outside the movement list."""
    _, summary = _scan_detail_and_summary(_tiering_report())
    assert "<thead><tr><th>Model</th><th>Field</th><th>Change</th></tr></thead>" in summary
    assert "<th>Provider</th>" not in summary
    assert "<th>Category</th>" not in summary
    assert "OpenRouter" not in summary


def test_the_change_summary_keeps_the_provider_column_for_two_providers() -> None:
    """E5's other half: with two providers the label is load-bearing."""
    first = _scan_result(
        (_priced("shared/model", FieldChange("pricing.prompt", "0.000001", "0.000002")),),
        provider_id="pa",
        provider_label="Provider A",
    )
    second = _scan_result(
        (_priced("shared/model", FieldChange("pricing.prompt", "0.000002", "0.000001")),),
        provider_id="pb",
        provider_label="Provider B",
    )
    html = render_scan_report(
        generated_at="2026-07-25T09:00:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[first, second],
    )
    _, summary = _scan_detail_and_summary(html)
    assert (
        "<thead><tr><th>Provider</th><th>Model</th><th>Field</th><th>Change</th></tr></thead>"
    ) in summary
    assert "<td>Provider A</td>" in summary
    assert "<td>Provider B</td>" in summary


def test_the_changes_report_keeps_its_own_summary_table() -> None:
    """The cross-renderer matrix scopes E3-E6 to the concise HTML report.

    Asserted from the `changes` report's output rather than trusted to the
    default argument, so a later caller that starts passing `concise=True`
    from `_render_changes_html` fails here.
    """
    html = _mixed_changes_report("html")
    assert '<section class="summary-section"><h2>Change Summary</h2>' in html
    assert (
        "<thead><tr><th>Category</th><th>Provider</th><th>Model</th>"
        "<th>Field</th><th>Change</th></tr></thead>"
    ) in html
    assert _SECONDARY_OPEN not in html
    assert _SCAN_SUMMARY_OPEN not in html
