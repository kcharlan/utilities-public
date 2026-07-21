from model_sentinel.models import FieldChange, ModelDelta, ProviderScanResult
from model_sentinel.reporting import (
    DEFAULT_REPORT_SHOW_FIELDS,
    ReportDetailPolicy,
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

    assert "pricing.overrides: +{'prompt': '0.000005'}; -{'prompt': '0.000004'} (1 \u2192 1)" in report


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
