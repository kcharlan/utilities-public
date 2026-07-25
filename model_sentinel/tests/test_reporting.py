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
) -> ProviderScanResult:
    return ProviderScanResult(
        provider_id=provider_id,
        provider_label=provider_label,
        status="success",
        current_count=2,
        saved=False,
        baseline=None,
        baseline_message=None,
        scrape_id=None,
        added=(),
        removed=(),
        changed=changed,
        error_message=None,
        price_multiplier=1000000,
        price_divisor=1,
    )


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


def test_noop_rows_are_absent_from_every_human_format() -> None:
    for format_name, report in _render_all_human_formats((_NOOP_PLUS_REAL_MODEL,)).items():
        # Both noop forms: null -> null, and equal non-null values.
        assert "default_parameters.temperature" not in report, format_name
        assert "active" not in report, format_name
        # The real change on the same model still renders.
        assert "expiration_date" in report, format_name


def test_noop_only_model_gets_no_card_at_all() -> None:
    """A model whose every change is a noop has nothing to report, so it must
    not consume a card, a header, or a summary row."""
    for format_name, report in _render_all_human_formats((_NOOP_MODEL,)).items():
        assert "synth/model-noop-only" not in report, format_name


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

    for format_name, report in _render_all_human_formats(equal_but_differently_spelled).items():
        assert "Bulk change" not in report, format_name
        assert "supported_parameters" not in report, format_name
        for suffix in ("a", "b", "c"):
            assert f"synth/model-eq-{suffix}" not in report, format_name


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
