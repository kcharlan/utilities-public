import json

from model_sentinel.change_render import classify_change
from model_sentinel.models import FieldChange, ModelDelta, ProviderScanResult
from model_sentinel.reporting import (
    DEFAULT_REPORT_SHOW_FIELDS,
    ReportDetailPolicy,
    _list_change_signature,
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


def _html_provider_sections(html: str) -> list[str]:
    """Every `<section class="provider-section">` body, in document order."""
    return [
        chunk.split("</section>", 1)[0]
        for chunk in html.split('<section class="provider-section">')[1:]
    ]


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
    assert "benchmarks.artificial_analysis.intelligence_index" not in report
    assert "[Unclassified]" in report
    assert "metadata.owner: old \u2192 new" in report


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
    assert "benchmarks.artificial_analysis.intelligence_index" in report


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

    assert "benchmarks.design_arena" in report
    assert "metadata.owner: old" not in report
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

    assert "new_payload.a: old \u2192 new" in report
    assert "new_payload.b: old \u2192 new" not in report
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

    assert "benchmarks.design_arena" in report
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

    summary = report.split("<h2>Change Summary</h2>", 1)[1]
    pricing_index = summary.index("<td>Pricing</td>")
    benchmarks_index = summary.index("<td>Benchmarks</td>")
    other_index = summary.index("<td>Other</td>")

    assert pricing_index < benchmarks_index < other_index


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

    movement = report.split('<section class="price-movement-summary">', 1)[1].split("</section>", 1)[0]
    assert 'Price Movement <span class="outcome price-mixed">\u2014 mixed</span>' in movement
    assert '<strong>4 affected models:</strong>' in movement
    assert '<span class="price-higher">1 with increases and no decreases</span>' in movement
    assert '<span class="price-lower">1 with decreases and no increases</span>' in movement
    assert '<span class="price-mixed">1 mixed</span>' in movement
    assert '<span class="price-coverage">1 with fields added/removed only</span>' in movement
    assert '<strong>8 changed price fields:</strong>' in movement
    assert '<span class="price-higher">2 higher</span>' in movement
    assert '<span class="price-lower">2 lower</span>' in movement
    assert '<span class="price-coverage">2 added</span>' in movement
    assert '<span class="price-coverage">2 removed</span>' in movement
    assert '<summary>View 4 affected models</summary>' in movement
    for model_id in ("higher-model", "lower-model", "mixed-model", "coverage-model"):
        assert movement.count(f"<code>{model_id}</code>") == 1

    assert report.index('<div class="provider-cards">') < report.index('<section class="price-movement-summary">')
    assert report.index('<section class="price-movement-summary">') < report.index('<section class="provider-section">')
    card_positions = [
        report.index(f'<div class="model-card-header"><code>{model_id}</code>')
        for model_id in ("higher-model", "lower-model", "mixed-model", "coverage-model")
    ]
    assert card_positions == sorted(card_positions)


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

    movement = report.split('<section class="price-movement-summary">', 1)[1].split("</section>", 1)[0]
    assert '<strong>2 affected models:</strong>' in movement
    assert movement.count("<code>shared-model</code>") == 2
    assert '<span class="price-movement-provider">Abacus.AI</span>' in movement
    assert '<span class="price-movement-provider">OpenRouter</span>' in movement


def test_html_price_movement_summary_omits_zero_categories_and_leads_with_direction() -> None:
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

    movement = report.split('<section class="price-movement-summary">', 1)[1].split("</section>", 1)[0]
    assert 'Price Movement <span class="outcome price-lower">\u2014 mostly lower</span>' in movement
    assert '<strong>2 affected models:</strong>' in movement
    assert '<span class="price-lower">1 with decreases and no increases</span>' in movement
    assert '<span class="price-mixed">1 mixed</span>' in movement
    assert "with increases and no decreases" not in movement
    assert "with fields added/removed only" not in movement
    assert '<strong>4 changed price fields:</strong>' in movement
    assert '<span class="price-lower">2 lower</span>' in movement
    assert '<span class="price-higher">1 higher</span>' in movement
    assert '<span class="price-coverage">1 removed</span>' in movement
    assert ">0 added</span>" not in movement


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

    movement = report.split('<section class="price-movement-summary">', 1)[1].split("</section>", 1)[0]
    assert 'Price Movement <span class="outcome price-coverage">\u2014 price fields added/removed</span>' in movement
    assert '<span class="price-coverage">1 added</span>' in movement
    assert '>0 removed</span>' not in movement
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
    assert "Price Movement" not in hidden_report


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

    assert "Price Movement" not in report


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

    assert "benchmarks.design_arena" not in report
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
    assert "supported_parameters: +reasoning_effort" in text_report
    assert "2 field changes across 2 of these models" in text_report
    assert "* priced-model (Priced Model)" in text_report
    assert "pricing.prompt: 0.000001 \u2192 0.000002" in text_report

    assert "**Bulk change \u2014 3 models**" in markdown_report
    assert "`supported_parameters: +reasoning_effort`" in markdown_report
    assert "`priced-model` - Priced Model" in markdown_report

    detail_html, summary_html = html_report.split("<h2>Change Summary</h2>", 1)
    assert '<div class="model-card-header"><code>Bulk change \u2014 3 models</code>' in detail_html
    assert '<div class="model-card-header"><code>alpha</code>' not in detail_html
    assert '<div class="model-card-header"><code>priced-model</code>' in detail_html
    assert '<summary>Models: alpha, beta, gamma</summary>' in detail_html
    assert '<summary>3 models</summary>' in summary_html
    assert summary_html.count("<td>Parameters</td>") == 2
    assert summary_html.count("<td>Squelched</td>") == 1
    assert "priced-model" in summary_html


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

    detail_html, _ = report.split("<h2>Change Summary</h2>", 1)
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

    detail_html, summary_html = html_report.split("<h2>Change Summary</h2>", 1)
    assert '<div class="model-card-header"><code>squelched-only</code>' not in detail_html
    assert '<div class="model-card-header"><code>visible-and-squelched</code>' in detail_html
    assert '<td>Squelched</td><td>OpenRouter</td><td><code>squelched-only</code>' not in summary_html
    assert summary_html.count("<td>Squelched</td>") == 1
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

    assert "pricing.prompt" in report
    assert "benchmarks.design_arena" not in report
    assert "squelched:" in report


def test_history_report_applies_detail_policy() -> None:
    from model_sentinel.models import HistoryEvent

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

    assert "pricing.prompt" in report
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

    assert "benchmarks.design_arena" in report


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

    expected = "pricing.input_audio_cache: null \u2192 0.0000003 ($0.30 / 1M)"
    assert expected in text_report
    assert expected in markdown_report
    assert '<td class="new-val">0.0000003 ($0.30 / 1M)</td>' in html_report
    assert '<td class="change-delta delta-price-coverage">added</td>' in html_report


def test_html_price_rows_use_cost_specific_direction_colors() -> None:
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
            ),
        ),
    )
    report = render_scan_report(
        generated_at="2026-07-15T13:05:00+00:00",
        command="scan",
        format_name="html",
        provider_results=[_scan_result(changed)],
    )

    assert '<td class="change-delta delta-price-higher">\u2191 100.0%</td>' in report
    assert '<td class="change-delta delta-price-lower">\u2193 25.0%</td>' in report
    assert '<td class="change-delta delta-price-coverage">removed</td>' in report
    assert '<td class="change-delta delta-increase">\u2191 100.0%</td>' in report


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

    assert "pricing.overrides[0].completion: null \u2192 0.0000225 ($22.50 / 1M)" in text_report
    assert "pricing.overrides[0].input_cache_read: null \u2192 0.0000006 ($0.60 / 1M)" in text_report
    assert "pricing.overrides[0].min_prompt_tokens: null \u2192 200,000" in text_report
    assert "$200" not in text_report
    assert "pricing.overrides[0].prompt" in html_report
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
    expected = f"{field_name}: 0.000001 \u2192 0.0000006 ($1.00 \u2192 $0.60 / 1M, \u2193 40.0%)"
    assert expected in text_report
    assert field_name in html_report
    assert "$1.00 \u2192 $0.60 / 1M" in html_report
    assert "pricing.overrides (2 \u2192 2)" not in text_report
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

    assert "pricing.overrides[min_prompt_tokens=200000].prompt: 0.000004 ($4.00 / 1M) \u2192 null" in report
    assert "pricing.overrides[min_prompt_tokens=300000].prompt: null \u2192 0.000005 ($5.00 / 1M)" in report
    assert "pricing.overrides[min_prompt_tokens=200000].min_prompt_tokens: 200,000 \u2192 null" in report
    assert "pricing.overrides[min_prompt_tokens=300000].min_prompt_tokens: null \u2192 300,000" in report


def test_unmatchable_pricing_overrides_keep_full_fidelity_list_fallback() -> None:
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
    assert 'pricing.overrides: +{"prompt": "0.000005"}; -{"prompt": "0.000004"} (1 \u2192 1)' in report


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

    assert "new_payload.tiers[0].label: null \u2192 small" in report
    assert "new_payload.tiers[1].limit: null \u2192 20" in report
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
        assert "default_parameters.temperature" not in report, format_name
        assert "status: active" not in report, format_name
        assert '<td class="field-name">status</td>' not in report, format_name
        # The real change on the same model still renders.
        assert "expiration_date" in report, format_name


def test_noop_only_model_gets_no_card_at_all() -> None:
    """A model whose every change is a noop has nothing to report, so it must
    not consume a card, a header, or a summary row."""
    reports = _render_all_human_formats((_NOOP_MODEL,))
    _assert_no_model_card(reports, "synth/model-noop-only")
    assert "default_parameters.temperature" not in reports["text"]
    assert "default_parameters.temperature" not in reports["markdown"]
    assert "default_parameters.temperature" not in reports["html"]


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
        assert "default_parameters.temperature" not in report, format_name
        assert "expiration_date" in report, format_name


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
        assert "default_parameters.temperature" not in report, format_name
        assert "expiration_date" in report, format_name

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
    """`<h3>Changed</h3>` with no cards after it was the HTML symptom."""
    html = _render_all_human_formats((_NOOP_MODEL,))["html"]
    body = _html_section_body(html, "<h3>Changed</h3>")
    assert body, "<h3>Changed</h3> rendered with nothing beneath it"
    # The rollup card is what justifies the heading, and it is what follows it.
    assert '<div class="category-label">no-op</div>' in body
    assert "1 field change across 1 model" in body


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
    sections = _html_provider_sections(html)
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
    assert "benchmarks.design_arena" not in report


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
    assert "benchmarks.design_arena" not in report


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
        assert "expiration_date: null → 2030-12-31" in report, format_name

    body = _html_section_body(reports["html"], "<h3>Synth Provider</h3>")
    assert '<ul class="model-list added-list">' in body
    assert '<div class="model-card-header"><code>synth/model-churn</code>' in body
    assert "expiration_date" in body

    summary = reports["html"].split('<section class="summary-section">', 1)[1]
    assert "<td>Added</td><td>Synth Provider</td><td><code>synth/model-churn</code></td>" in summary
    assert "expiration_date" in summary

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
        assert "expiration_date: null → 2030-12-31" in report, format_name

    body = _html_section_body(reports["html"], "<h3>Synth Provider</h3>")
    assert '<ul class="model-list removed-list">' in body
    assert '<div class="model-card-header"><code>synth/model-churn</code>' in body

    summary = reports["html"].split('<section class="summary-section">', 1)[1]
    assert "<td>Removed</td><td>Synth Provider</td><td><code>synth/model-churn</code></td>" in summary
    assert "expiration_date" in summary

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
        assert "supported_parameters" not in report, format_name
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
    assert "supported_parameters: +seed" in text


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
    assert "top_provider.is_moderated: on → off" in reports["text"]
    assert "`top_provider.is_moderated: on → off`" in reports["markdown"]
    assert (
        '<td class="field-name">top_provider.is_moderated</td>'
        '<td class="old-val">on</td><td class="new-val">off</td>'
        '<td class="change-delta delta-decrease">disabled</td>'
    ) in reports["html"]
    for format_name, report in reports.items():
        assert "%" not in report.replace("%;", ""), format_name


def test_boolean_enable_renders_off_to_on_with_a_non_empty_delta_cell() -> None:
    """Regression test for the blank-Change-cell defect: `_pct_change`
    returns "" when the old value is 0, so `False -> True` produced an empty
    delta cell. The boolean branch never reaches percent logic at all."""
    reports = _boolean_reports("top_provider.is_moderated", False, True)
    assert "top_provider.is_moderated: off → on" in reports["text"]
    assert (
        '<td class="field-name">top_provider.is_moderated</td>'
        '<td class="old-val">off</td><td class="new-val">on</td>'
        '<td class="change-delta delta-increase">enabled</td>'
    ) in reports["html"]
    assert '<td class="change-delta delta-neutral"></td>' not in reports["html"]


def test_integer_coded_boolean_renders_off_to_on_with_no_percent() -> None:
    """`reasoning.default_enabled` is recorded as 0/1, not as a real bool."""
    reports = _boolean_reports("reasoning.default_enabled", 0, 1)
    assert "reasoning.default_enabled: off → on" in reports["text"]
    assert '<td class="change-delta delta-increase">enabled</td>' in reports["html"]
    for format_name, report in reports.items():
        assert "%" not in report.replace("%;", ""), format_name


def test_one_sided_boolean_renders_as_coverage_with_an_em_dash() -> None:
    """Task 4 decision: a flag appearing from nothing is presented like every
    other one-sided change -- em dash on the absent side, `added` pill in the
    delta column -- instead of leaking the raw Python repr `null -> True`."""
    reports = _boolean_reports("top_provider.is_moderated", None, True)
    assert "top_provider.is_moderated: — → on" in reports["text"]
    assert (
        '<td class="field-name">top_provider.is_moderated</td>'
        '<td class="old-val">—</td><td class="new-val">on</td>'
        '<td class="change-delta delta-increase">added</td>'
    ) in reports["html"]
    assert "null → True" not in reports["text"]

    removed = _boolean_reports("top_provider.is_moderated", True, None)
    assert "top_provider.is_moderated: on → —" in removed["text"]
    assert '<td class="change-delta delta-decrease">removed</td>' in removed["html"]


def test_numeric_field_holding_zero_and_one_is_not_treated_as_a_boolean() -> None:
    """The known-boolean set is a restriction, not a blanket 0/1 rule: a
    temperature is a magnitude even when its values look like a flag's.

    NOTE: `0 -> 1` has a zero basis, so `_pct_change` yields no percentage
    for it either -- that is the pre-existing zero-basis rule, not the E2
    boolean rule. The `0.5 -> 1` case below is what proves a percent still
    reaches a genuinely numeric default_parameters field.
    """
    reports = _boolean_reports("default_parameters.temperature", 0, 1)
    assert "default_parameters.temperature: 0 → 1 (+1)" in reports["text"]
    assert "off" not in reports["text"]

    with_percent = _boolean_reports("default_parameters.temperature", 0.5, 1)
    assert "default_parameters.temperature: 0.50 → 1 (+0.50, ↑ 100.0%)" in with_percent["text"]
