"""Golden-output characterization tests for the scan report renderers.

These tests lock in the exact current output of render_scan_report() across all
four output formats (text, markdown, html, json) and both the default and `all`
detail policies. They exist to protect a later readability redesign of the HTML/
text renderers: if a refactor changes rendered output, one of these tests will
fail and show the reviewer a full diff of old vs. new output.

Do NOT update the golden constants to make a refactor's tests pass silently.
A failing test here means the renderer output changed; the reviewer must look at
the diff and decide whether the new output is intentional before updating the
constant.
"""

from __future__ import annotations

from model_sentinel.models import FieldChange, ModelDelta, ProviderScanResult
from model_sentinel.reporting import (
    DEFAULT_REPORT_SHOW_FIELDS,
    ReportDetailPolicy,
    render_scan_report,
)
from model_sentinel.time_utils import to_local_human, to_local_iso

# Fixed instant used for every golden render in this module. render_scan_report()
# formats this through to_local_human()/to_local_iso(), both of which convert to the
# *local* system timezone. The golden constants below therefore embed a placeholder
# token instead of a literal timestamp, substituted at import time via the same
# helpers the renderer itself calls -- this keeps the tests deterministic across
# machines/CI runners in different timezones without weakening the assertions.
GENERATED_AT = "2026-07-25T09:00:00+00:00"
COMMAND = "scan"

_GENERATED_AT_HUMAN = to_local_human(GENERATED_AT)
_GENERATED_AT_ISO = to_local_iso(GENERATED_AT)
HUMAN_TOKEN = "@@GENERATED_AT_HUMAN@@"
ISO_TOKEN = "@@GENERATED_AT_ISO@@"

ALL_DETAIL_POLICY = ReportDetailPolicy(
    mode="all",
    show_fields=DEFAULT_REPORT_SHOW_FIELDS,
    squelch_fields=("benchmarks", "benchmarks.*"),
    unclassified_limit=20,
)


def characterization_scan_result() -> list[ProviderScanResult]:
    """Fixture builder covering every field-classification branch in reporting.py.

    One provider, six models. Model ``synth/model-core`` carries the bulk of the
    cases (cases 1-4, 7, 9, 11-14 from the task-1 brief); cases 5, 6, 8, 9b, and 10
    each get their own model because they reuse a field name already used by
    another case and a real diff would never emit the same field twice for one
    model.
    """
    changed = (
        ModelDelta(
            "changed",
            "synth/model-core",
            "Synth Model Core",
            (
                # Case 1: price change, both sides numeric.
                FieldChange("pricing.completion", 0.000002, 0.0000035),
                # Case 2: price addition.
                FieldChange("pricing.input_cache_read", None, 0.00000005),
                # Case 3: price removal.
                FieldChange("pricing.input_cache_write", 0.00000009, None),
                # Case 4: count field, both sides numeric.
                FieldChange("top_provider.context_length", 131072, 262144),
                # Case 7: boolean false -> true.
                FieldChange("top_provider.is_moderated", False, True),
                # Case 9: integer-encoded boolean.
                FieldChange("reasoning.default_enabled", 0, 1),
                # Case 11: list diff.
                FieldChange("supported_parameters", ["tools"], ["tools", "logit_bias"]),
                # Case 12: dynamic pricing-override path (real list-of-dicts shape,
                # keyed by min_prompt_tokens, so _expand_pricing_override_changes engages).
                FieldChange(
                    "pricing.overrides",
                    [{"min_prompt_tokens": 200000, "completion": "0.000004"}],
                    [{"min_prompt_tokens": 200000, "completion": "0.000005"}],
                ),
                # Case 13: scalar fallback.
                FieldChange("expiration_date", None, "2030-12-31"),
                # Case 14: squelched field (benchmarks.*).
                FieldChange("benchmarks.example_suite", [{"score": 1}], [{"score": 2}]),
            ),
        ),
        ModelDelta(
            "changed",
            "synth/model-limit-add",
            "Synth Model Limit Add",
            # Case 5: count field, one-sided add.
            (FieldChange("top_provider.max_completion_tokens", None, 16384),),
        ),
        ModelDelta(
            "changed",
            "synth/model-limit-remove",
            "Synth Model Limit Remove",
            # Case 6: count field, one-sided remove (separate model from case 5 --
            # same field name).
            (FieldChange("top_provider.max_completion_tokens", 8192, None),),
        ),
        ModelDelta(
            "changed",
            "synth/model-moderation-off",
            "Synth Model Moderation Off",
            # Case 8: boolean true -> false (separate model from case 7 -- same field name).
            (FieldChange("top_provider.is_moderated", True, False),),
        ),
        ModelDelta(
            "changed",
            "synth/model-temp-toggle",
            "Synth Model Temp Toggle",
            # Case 9b: numeric field holding 0/1 that must NOT classify as boolean
            # (separate model from cases 9/10 -- same field name as case 10).
            (FieldChange("default_parameters.temperature", 0, 1),),
        ),
        ModelDelta(
            "changed",
            "synth/model-temp-null",
            "Synth Model Temp Null",
            # Case 10: null -> null.
            (FieldChange("default_parameters.temperature", None, None),),
        ),
    )
    return [
        ProviderScanResult(
            provider_id="synthprov",
            provider_label="Synth Provider",
            status="success",
            current_count=6,
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
    ]


_EXPECTED_TEXT_TEMPLATE = """Model Sentinel report
Generated at: @@GENERATED_AT_HUMAN@@
Command: scan

Synth Provider (synthprov)
  status: success
  current_count: 6
  added: 0
  removed: 0
  changed: 6
    * synth/model-core (Synth Model Core)
      [Pricing]
        pricing.completion: 2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)
        pricing.input_cache_read: null → 5e-08 ($0.05 / 1M)
        pricing.input_cache_write: 9e-08 ($0.09 / 1M) → null
        pricing.overrides[min_prompt_tokens=200000].completion: 0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)
      [Context & Limits]
        top_provider.context_length: 131,072 → 262,144 (+131,072, ↑ 100.0%)
      [Parameters]
        supported_parameters: +logit_bias (1 → 2)
      [Capabilities]
        reasoning.default_enabled: 0 → 1 (+1)
      [Other]
        top_provider.is_moderated: 0 → 1 (+1)
        expiration_date: null → 2030-12-31
      [Squelched]
        1 field change hidden by report detail policy
    * synth/model-limit-add (Synth Model Limit Add)
      top_provider.max_completion_tokens: null → 16,384
    * synth/model-limit-remove (Synth Model Limit Remove)
      top_provider.max_completion_tokens: 8,192 → null
    * synth/model-moderation-off (Synth Model Moderation Off)
      top_provider.is_moderated: 1 → 0 (-1, ↓ 100.0%)
    * synth/model-temp-toggle (Synth Model Temp Toggle)
      default_parameters.temperature: 0 → 1 (+1)
    * synth/model-temp-null (Synth Model Temp Null)
      default_parameters.temperature: null → null
  squelched: 1 field change across 1 model
    patterns: benchmarks, benchmarks.*
    models: synth/model-core

Summary
------------------------------------------------------------
  Synth Provider: 6 changed"""

EXPECTED_TEXT = _EXPECTED_TEXT_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_TEXT_DETAIL_ALL_TEMPLATE = """Model Sentinel report
Generated at: @@GENERATED_AT_HUMAN@@
Command: scan

Synth Provider (synthprov)
  status: success
  current_count: 6
  added: 0
  removed: 0
  changed: 6
    * synth/model-core (Synth Model Core)
      [Pricing]
        pricing.completion: 2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)
        pricing.input_cache_read: null → 5e-08 ($0.05 / 1M)
        pricing.input_cache_write: 9e-08 ($0.09 / 1M) → null
        pricing.overrides[min_prompt_tokens=200000].completion: 0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)
      [Context & Limits]
        top_provider.context_length: 131,072 → 262,144 (+131,072, ↑ 100.0%)
      [Parameters]
        supported_parameters: +logit_bias (1 → 2)
      [Capabilities]
        reasoning.default_enabled: 0 → 1 (+1)
      [Benchmarks]
        benchmarks.example_suite: +{'score': 2}; -{'score': 1} (1 → 1)
      [Other]
        top_provider.is_moderated: 0 → 1 (+1)
        expiration_date: null → 2030-12-31
    * synth/model-limit-add (Synth Model Limit Add)
      top_provider.max_completion_tokens: null → 16,384
    * synth/model-limit-remove (Synth Model Limit Remove)
      top_provider.max_completion_tokens: 8,192 → null
    * synth/model-moderation-off (Synth Model Moderation Off)
      top_provider.is_moderated: 1 → 0 (-1, ↓ 100.0%)
    * synth/model-temp-toggle (Synth Model Temp Toggle)
      default_parameters.temperature: 0 → 1 (+1)
    * synth/model-temp-null (Synth Model Temp Null)
      default_parameters.temperature: null → null

Summary
------------------------------------------------------------
  Synth Provider: 6 changed"""

EXPECTED_TEXT_DETAIL_ALL = _EXPECTED_TEXT_DETAIL_ALL_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_MARKDOWN_TEMPLATE = """# Model Sentinel Report

- Generated at: @@GENERATED_AT_HUMAN@@
- Command: scan

## Synth Provider (`synthprov`)

- Status: `success`
- Current models: `6`

### Added (0)

- None

### Removed (0)

- None

### Changed (6)

- `synth/model-core` - Synth Model Core
  - `pricing.completion: 2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)`
  - `pricing.input_cache_read: null → 5e-08 ($0.05 / 1M)`
  - `pricing.input_cache_write: 9e-08 ($0.09 / 1M) → null`
  - `top_provider.context_length: 131,072 → 262,144 (+131,072, ↑ 100.0%)`
  - `top_provider.is_moderated: 0 → 1 (+1)`
  - `reasoning.default_enabled: 0 → 1 (+1)`
  - `supported_parameters: +logit_bias (1 → 2)`
  - `pricing.overrides[min_prompt_tokens=200000].completion: 0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)`
  - `expiration_date: null → 2030-12-31`
  - Squelched: `1` field change(s) hidden by report detail policy
- `synth/model-limit-add` - Synth Model Limit Add
  - `top_provider.max_completion_tokens: null → 16,384`
- `synth/model-limit-remove` - Synth Model Limit Remove
  - `top_provider.max_completion_tokens: 8,192 → null`
- `synth/model-moderation-off` - Synth Model Moderation Off
  - `top_provider.is_moderated: 1 → 0 (-1, ↓ 100.0%)`
- `synth/model-temp-toggle` - Synth Model Temp Toggle
  - `default_parameters.temperature: 0 → 1 (+1)`
- `synth/model-temp-null` - Synth Model Temp Null
  - `default_parameters.temperature: null → null`
- squelched: `1` field change across `1` model
- Squelch patterns: `benchmarks, benchmarks.*`
- Squelched models: `synth/model-core`"""

EXPECTED_MARKDOWN = _EXPECTED_MARKDOWN_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_MARKDOWN_DETAIL_ALL_TEMPLATE = """# Model Sentinel Report

- Generated at: @@GENERATED_AT_HUMAN@@
- Command: scan

## Synth Provider (`synthprov`)

- Status: `success`
- Current models: `6`

### Added (0)

- None

### Removed (0)

- None

### Changed (6)

- `synth/model-core` - Synth Model Core
  - `pricing.completion: 2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)`
  - `pricing.input_cache_read: null → 5e-08 ($0.05 / 1M)`
  - `pricing.input_cache_write: 9e-08 ($0.09 / 1M) → null`
  - `top_provider.context_length: 131,072 → 262,144 (+131,072, ↑ 100.0%)`
  - `top_provider.is_moderated: 0 → 1 (+1)`
  - `reasoning.default_enabled: 0 → 1 (+1)`
  - `supported_parameters: +logit_bias (1 → 2)`
  - `pricing.overrides[min_prompt_tokens=200000].completion: 0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)`
  - `expiration_date: null → 2030-12-31`
  - `benchmarks.example_suite: +{'score': 2}; -{'score': 1} (1 → 1)`
- `synth/model-limit-add` - Synth Model Limit Add
  - `top_provider.max_completion_tokens: null → 16,384`
- `synth/model-limit-remove` - Synth Model Limit Remove
  - `top_provider.max_completion_tokens: 8,192 → null`
- `synth/model-moderation-off` - Synth Model Moderation Off
  - `top_provider.is_moderated: 1 → 0 (-1, ↓ 100.0%)`
- `synth/model-temp-toggle` - Synth Model Temp Toggle
  - `default_parameters.temperature: 0 → 1 (+1)`
- `synth/model-temp-null` - Synth Model Temp Null
  - `default_parameters.temperature: null → null`"""

EXPECTED_MARKDOWN_DETAIL_ALL = _EXPECTED_MARKDOWN_DETAIL_ALL_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model Sentinel — @@GENERATED_AT_HUMAN@@</title>
<style>
:root {
  --bg: #0f1419;
  --bg-card: #1a1f2e;
  --bg-card-hover: #1e2536;
  --bg-table-row: #151a24;
  --bg-table-alt: #1a2030;
  --border: #2a3040;
  --border-accent: #3a4050;
  --text: #c5cdd8;
  --text-dim: #6b7a8d;
  --text-bright: #e8edf4;
  --accent-green: #34d399;
  --accent-green-dim: rgba(52, 211, 153, 0.12);
  --accent-red: #f87171;
  --accent-red-dim: rgba(248, 113, 113, 0.12);
  --accent-amber: #fbbf24;
  --accent-amber-dim: rgba(251, 191, 36, 0.12);
  --accent-blue: #60a5fa;
  --font-mono: "SF Mono", "Cascadia Code", "Fira Code", "JetBrains Mono", "Consolas", monospace;
  --font-body: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  font-size: 14px;
  line-height: 1.6;
  padding: 2rem;
  max-width: 1100px;
  margin: 0 auto;
}
header {
  border-bottom: 1px solid var(--border);
  padding-bottom: 1.5rem;
  margin-bottom: 2rem;
}
header h1 {
  font-family: var(--font-mono);
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-bright);
  letter-spacing: -0.02em;
}
header h1 .count {
  color: var(--accent-amber);
  font-weight: 400;
}
.meta {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-top: 0.4rem;
  font-family: var(--font-mono);
}
.provider-cards {
  display: flex;
  gap: 1rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
}
.provider-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  min-width: 200px;
  flex: 1;
  border-left: 3px solid var(--border);
}
.provider-card.status-clean { border-left-color: var(--accent-green); }
.provider-card.status-changed { border-left-color: var(--accent-amber); }
.provider-card.status-error { border-left-color: var(--accent-red); }
.provider-name {
  font-weight: 600;
  color: var(--text-bright);
  font-size: 1rem;
}
.provider-stats {
  color: var(--text-dim);
  font-size: 0.8rem;
  font-family: var(--font-mono);
  margin-top: 0.2rem;
}
.provider-badge {
  margin-top: 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.status-clean .provider-badge { color: var(--accent-green); }
.status-changed .provider-badge { color: var(--accent-amber); }
.status-error .provider-badge { color: var(--accent-red); }
.price-movement-summary {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 2rem;
}
.price-movement-title {
  font-family: var(--font-mono);
  color: var(--text-bright);
  font-size: 1.05rem;
  font-weight: 600;
  margin-bottom: 0.65rem;
}
.price-movement-title .outcome {
  font-weight: 400;
}
.price-movement-model-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0;
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
.price-movement-model-summary > strong,
.price-movement-fields > strong {
  color: var(--text-bright);
  font-weight: 600;
  margin-right: 0.45rem;
}
.price-higher { color: var(--accent-red); }
.price-lower { color: var(--accent-green); }
.price-mixed { color: var(--accent-amber); }
.price-coverage { color: var(--accent-blue); }
.price-movement-fields {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.78rem;
  margin-top: 0.45rem;
}
.price-movement-model-summary span + span::before,
.price-movement-fields span + span::before {
  content: " · ";
  color: var(--text-dim);
}
.price-movement-models {
  border-top: 1px solid var(--border);
  margin-top: 0.75rem;
  padding-top: 0.55rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.price-movement-models summary {
  cursor: pointer;
  color: var(--text);
}
.price-movement-model-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem 1.5rem;
  margin-top: 0.75rem;
}
.price-movement-group-label {
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 0.3rem;
}
.price-movement-model {
  display: grid;
  grid-template-columns: minmax(90px, auto) 1fr;
  gap: 0.5rem;
  padding: 0.15rem 0;
}
.price-movement-provider { color: var(--text-dim); }
.price-movement-model code {
  color: var(--text);
  overflow-wrap: anywhere;
}
.date-heading {
  font-family: var(--font-mono);
  font-size: 1.15rem;
  color: var(--text-bright);
  margin: 1.5rem 0 0.75rem 0;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}
.provider-section {
  margin-bottom: 2.5rem;
}
.provider-section h2 {
  font-family: var(--font-mono);
  font-size: 1.15rem;
  color: var(--text-bright);
  margin-bottom: 0.75rem;
  font-weight: 600;
}
.provider-id {
  color: var(--text-dim);
  font-weight: 400;
  font-size: 0.9rem;
}
.baseline-info {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
  margin-bottom: 1rem;
}
.error-msg {
  background: var(--accent-red-dim);
  color: var(--accent-red);
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  margin-bottom: 1rem;
}
h3 {
  font-size: 0.9rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 1.25rem 0 0.5rem 0;
  font-weight: 600;
}
.model-list {
  list-style: none;
  padding-left: 0;
}
.model-list li {
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  margin-bottom: 0.2rem;
}
.added-list li {
  background: var(--accent-green-dim);
  color: var(--accent-green);
}
.removed-list li {
  background: var(--accent-red-dim);
  color: var(--accent-red);
}
.model-list .display-name {
  color: var(--text-dim);
  font-family: var(--font-body);
}
.model-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 1rem;
  overflow: hidden;
}
.model-card-header {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-card-hover);
}
.model-card-header code {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  color: var(--accent-amber);
  font-weight: 600;
}
.model-card-header .display-name {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-left: 0.5rem;
}
.bulk-change-card {
  border-left: 3px solid var(--accent-amber);
}
.bulk-models, .summary-models {
  padding: 0.55rem 1rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.bulk-models summary, .summary-models summary {
  cursor: pointer;
  color: var(--text);
}
.bulk-model-list, .summary-model-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 0.25rem 1rem;
  margin-top: 0.6rem;
}
.bulk-model-list code, .summary-model-list code {
  color: var(--text-dim);
  overflow-wrap: anywhere;
}
.change-category {
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--border);
}
.change-category:last-child {
  border-bottom: none;
}
.category-label {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.4rem;
  font-weight: 600;
}
.change-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.change-table th {
  text-align: left;
  color: var(--text-dim);
  font-weight: 500;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.3rem 0.5rem;
  border-bottom: 1px solid var(--border);
}
.change-table td {
  padding: 0.4rem 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.82rem;
  vertical-align: top;
}
.change-table tr:nth-child(even) td {
  background: var(--bg-table-alt);
}
.field-name { color: var(--text); }
td.old-val { color: var(--text-dim); }
td.new-val { color: var(--text-bright); }
td.change-delta { font-weight: 600; }
td.delta-decrease { color: var(--accent-red); }
td.delta-increase { color: var(--accent-green); }
td.delta-neutral { color: var(--accent-amber); }
td.delta-price-higher { color: var(--accent-red); }
td.delta-price-lower { color: var(--accent-green); }
td.delta-price-coverage { color: var(--accent-blue); }
.list-diff {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  padding: 0.35rem 0;
}
.list-added { color: var(--accent-green); }
.list-removed { color: var(--accent-red); }
.list-count { color: var(--text-dim); font-size: 0.8rem; }
.summary-section {
  margin-top: 2.5rem;
  border-top: 1px solid var(--border);
  padding-top: 1.5rem;
}
.summary-section h2 {
  font-family: var(--font-mono);
  font-size: 1.1rem;
  color: var(--text-bright);
  margin-bottom: 1rem;
}
.summary-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.summary-table th {
  text-align: left;
  color: var(--text-dim);
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.5rem 0.75rem;
  border-bottom: 2px solid var(--border-accent);
  background: var(--bg-card);
}
.summary-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
.summary-table tr:nth-child(even) td {
  background: var(--bg-table-alt);
}
.summary-table .summary-models {
  padding: 0;
}
footer {
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 0.75rem;
  font-family: var(--font-mono);
}
</style>
</head>
<body>
<header>
  <h1>Model Sentinel <span class="count">— 6 changes</span></h1>
  <div class="meta">@@GENERATED_AT_HUMAN@@ &middot; scan</div>
</header>
<div class="provider-cards">
  <div class="provider-card status-changed"><div class="provider-name">Synth Provider</div><div class="provider-stats">6 models</div><div class="provider-badge">6 changes</div></div>
</div>

<section class="price-movement-summary"><div class="price-movement-title">Price Movement <span class="outcome price-higher">— higher</span></div><div class="price-movement-model-summary"><strong>1 affected model:</strong><span class="price-higher">1 with increases and no decreases</span></div><div class="price-movement-fields"><strong>4 changed price fields:</strong><span class="price-higher">2 higher</span><span class="price-coverage">1 added</span><span class="price-coverage">1 removed</span></div><details class="price-movement-models"><summary>View 1 affected model</summary><div class="price-movement-model-groups"><div class="price-movement-group"><div class="price-movement-group-label price-higher">↑ Higher, no decreases — 1</div><div class="price-movement-model"><span class="price-movement-provider">Synth Provider</span><code>synth/model-core</code></div></div></div></details></section>

<section class="provider-section"><h2>Synth Provider <span class="provider-id">(synthprov)</span></h2>
<h3>Changed</h3>
<div class="model-card">
<div class="model-card-header"><code>synth/model-core</code><span class="display-name">Synth Model Core</span></div>
<div class="change-category"><div class="category-label">Pricing</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">pricing.completion</td><td class="old-val">2e-06 ($2.00 / 1M)</td><td class="new-val">3.5e-06 ($3.50 / 1M)</td><td class="change-delta delta-price-higher">↑ 75.0%</td></tr>
<tr><td class="field-name">pricing.input_cache_read</td><td class="old-val">null</td><td class="new-val">5e-08 ($0.05 / 1M)</td><td class="change-delta delta-price-coverage">added</td></tr>
<tr><td class="field-name">pricing.input_cache_write</td><td class="old-val">9e-08 ($0.09 / 1M)</td><td class="new-val">null</td><td class="change-delta delta-price-coverage">removed</td></tr>
<tr><td class="field-name">pricing.overrides[min_prompt_tokens=200000].completion</td><td class="old-val">0.000004 ($4.00 / 1M)</td><td class="new-val">0.000005 ($5.00 / 1M)</td><td class="change-delta delta-price-higher">↑ 25.0%</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.context_length</td><td class="old-val">131,072</td><td class="new-val">262,144</td><td class="change-delta delta-increase">↑ 100.0%</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Parameters</div>
<div class="list-diff">
<span class="field-name">supported_parameters</span> 
<span class="list-count">(1 → 2)</span>
<div class="list-added">
&nbsp;&nbsp;+ logit_bias
</div>
</div>
</div>
<div class="change-category"><div class="category-label">Capabilities</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">reasoning.default_enabled</td><td class="old-val">0</td><td class="new-val">1</td><td class="change-delta delta-neutral"></td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.is_moderated</td><td class="old-val">0</td><td class="new-val">1</td><td class="change-delta delta-neutral"></td></tr>
<tr><td class="field-name">expiration_date</td><td class="old-val">null</td><td class="new-val">2030-12-31</td><td class="change-delta delta-neutral">—</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Squelched</div>
<div class="list-diff">1 field change hidden by report detail policy</div>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-limit-add</code><span class="display-name">Synth Model Limit Add</span></div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.max_completion_tokens</td><td class="old-val">null</td><td class="new-val">16,384</td><td class="change-delta delta-increase">added</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-limit-remove</code><span class="display-name">Synth Model Limit Remove</span></div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.max_completion_tokens</td><td class="old-val">8,192</td><td class="new-val">null</td><td class="change-delta delta-decrease">removed</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-moderation-off</code><span class="display-name">Synth Model Moderation Off</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.is_moderated</td><td class="old-val">1</td><td class="new-val">0</td><td class="change-delta delta-decrease">↓ 100.0%</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-temp-toggle</code><span class="display-name">Synth Model Temp Toggle</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">default_parameters.temperature</td><td class="old-val">0</td><td class="new-val">1</td><td class="change-delta delta-neutral"></td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-temp-null</code><span class="display-name">Synth Model Temp Null</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">default_parameters.temperature</td><td class="old-val">null</td><td class="new-val">null</td><td class="change-delta delta-neutral">—</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>squelched</code><span class="display-name">report detail summary</span></div>
<div class="change-category"><div class="category-label">squelched</div>
<div class="list-diff">1 field change across 1 model</div>
<div class="list-count">patterns: benchmarks, benchmarks.*</div>
<div class="list-count">models: synth/model-core</div>
</div></div></section>
<section class="summary-section"><h2>Change Summary</h2><table class="summary-table"><thead><tr><th>Category</th><th>Provider</th><th>Model</th><th>Field</th><th>Change</th></tr></thead><tbody><tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>pricing.completion</td><td>2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>pricing.input_cache_read</td><td>null → 5e-08 ($0.05 / 1M)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>pricing.input_cache_write</td><td>9e-08 ($0.09 / 1M) → null</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>pricing.overrides[min_prompt_tokens=200000].completion</td><td>0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>top_provider.context_length</td><td>131,072 → 262,144 (+131,072, ↑ 100.0%)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-limit-add</code></td><td>top_provider.max_completion_tokens</td><td>null → 16,384</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-limit-remove</code></td><td>top_provider.max_completion_tokens</td><td>8,192 → null</td></tr>
<tr><td>Parameters</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>supported_parameters</td><td>+logit_bias (1 → 2)</td></tr>
<tr><td>Capabilities</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>reasoning.default_enabled</td><td>0 → 1 (+1)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>expiration_date</td><td>null → 2030-12-31</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>top_provider.is_moderated</td><td>0 → 1 (+1)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-moderation-off</code></td><td>top_provider.is_moderated</td><td>1 → 0 (-1, ↓ 100.0%)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-temp-null</code></td><td>default_parameters.temperature</td><td>null → null</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-temp-toggle</code></td><td>default_parameters.temperature</td><td>0 → 1 (+1)</td></tr>
<tr><td>Squelched</td><td>Synth Provider</td><td><details class="summary-models"><summary>1 models</summary><div class="summary-model-list"><code>synth/model-core</code></div></details></td><td>benchmarks, benchmarks.*</td><td>1 field change hidden by report detail policy</td></tr></tbody></table></section>
<footer>Generated by Model Sentinel</footer>
</body>
</html>"""

EXPECTED_HTML = _EXPECTED_HTML_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_HTML_DETAIL_ALL_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model Sentinel — @@GENERATED_AT_HUMAN@@</title>
<style>
:root {
  --bg: #0f1419;
  --bg-card: #1a1f2e;
  --bg-card-hover: #1e2536;
  --bg-table-row: #151a24;
  --bg-table-alt: #1a2030;
  --border: #2a3040;
  --border-accent: #3a4050;
  --text: #c5cdd8;
  --text-dim: #6b7a8d;
  --text-bright: #e8edf4;
  --accent-green: #34d399;
  --accent-green-dim: rgba(52, 211, 153, 0.12);
  --accent-red: #f87171;
  --accent-red-dim: rgba(248, 113, 113, 0.12);
  --accent-amber: #fbbf24;
  --accent-amber-dim: rgba(251, 191, 36, 0.12);
  --accent-blue: #60a5fa;
  --font-mono: "SF Mono", "Cascadia Code", "Fira Code", "JetBrains Mono", "Consolas", monospace;
  --font-body: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  font-size: 14px;
  line-height: 1.6;
  padding: 2rem;
  max-width: 1100px;
  margin: 0 auto;
}
header {
  border-bottom: 1px solid var(--border);
  padding-bottom: 1.5rem;
  margin-bottom: 2rem;
}
header h1 {
  font-family: var(--font-mono);
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-bright);
  letter-spacing: -0.02em;
}
header h1 .count {
  color: var(--accent-amber);
  font-weight: 400;
}
.meta {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-top: 0.4rem;
  font-family: var(--font-mono);
}
.provider-cards {
  display: flex;
  gap: 1rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
}
.provider-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  min-width: 200px;
  flex: 1;
  border-left: 3px solid var(--border);
}
.provider-card.status-clean { border-left-color: var(--accent-green); }
.provider-card.status-changed { border-left-color: var(--accent-amber); }
.provider-card.status-error { border-left-color: var(--accent-red); }
.provider-name {
  font-weight: 600;
  color: var(--text-bright);
  font-size: 1rem;
}
.provider-stats {
  color: var(--text-dim);
  font-size: 0.8rem;
  font-family: var(--font-mono);
  margin-top: 0.2rem;
}
.provider-badge {
  margin-top: 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.status-clean .provider-badge { color: var(--accent-green); }
.status-changed .provider-badge { color: var(--accent-amber); }
.status-error .provider-badge { color: var(--accent-red); }
.price-movement-summary {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 2rem;
}
.price-movement-title {
  font-family: var(--font-mono);
  color: var(--text-bright);
  font-size: 1.05rem;
  font-weight: 600;
  margin-bottom: 0.65rem;
}
.price-movement-title .outcome {
  font-weight: 400;
}
.price-movement-model-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0;
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
.price-movement-model-summary > strong,
.price-movement-fields > strong {
  color: var(--text-bright);
  font-weight: 600;
  margin-right: 0.45rem;
}
.price-higher { color: var(--accent-red); }
.price-lower { color: var(--accent-green); }
.price-mixed { color: var(--accent-amber); }
.price-coverage { color: var(--accent-blue); }
.price-movement-fields {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.78rem;
  margin-top: 0.45rem;
}
.price-movement-model-summary span + span::before,
.price-movement-fields span + span::before {
  content: " · ";
  color: var(--text-dim);
}
.price-movement-models {
  border-top: 1px solid var(--border);
  margin-top: 0.75rem;
  padding-top: 0.55rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.price-movement-models summary {
  cursor: pointer;
  color: var(--text);
}
.price-movement-model-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem 1.5rem;
  margin-top: 0.75rem;
}
.price-movement-group-label {
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 0.3rem;
}
.price-movement-model {
  display: grid;
  grid-template-columns: minmax(90px, auto) 1fr;
  gap: 0.5rem;
  padding: 0.15rem 0;
}
.price-movement-provider { color: var(--text-dim); }
.price-movement-model code {
  color: var(--text);
  overflow-wrap: anywhere;
}
.date-heading {
  font-family: var(--font-mono);
  font-size: 1.15rem;
  color: var(--text-bright);
  margin: 1.5rem 0 0.75rem 0;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}
.provider-section {
  margin-bottom: 2.5rem;
}
.provider-section h2 {
  font-family: var(--font-mono);
  font-size: 1.15rem;
  color: var(--text-bright);
  margin-bottom: 0.75rem;
  font-weight: 600;
}
.provider-id {
  color: var(--text-dim);
  font-weight: 400;
  font-size: 0.9rem;
}
.baseline-info {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
  margin-bottom: 1rem;
}
.error-msg {
  background: var(--accent-red-dim);
  color: var(--accent-red);
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  margin-bottom: 1rem;
}
h3 {
  font-size: 0.9rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin: 1.25rem 0 0.5rem 0;
  font-weight: 600;
}
.model-list {
  list-style: none;
  padding-left: 0;
}
.model-list li {
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  margin-bottom: 0.2rem;
}
.added-list li {
  background: var(--accent-green-dim);
  color: var(--accent-green);
}
.removed-list li {
  background: var(--accent-red-dim);
  color: var(--accent-red);
}
.model-list .display-name {
  color: var(--text-dim);
  font-family: var(--font-body);
}
.model-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 1rem;
  overflow: hidden;
}
.model-card-header {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-card-hover);
}
.model-card-header code {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  color: var(--accent-amber);
  font-weight: 600;
}
.model-card-header .display-name {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-left: 0.5rem;
}
.bulk-change-card {
  border-left: 3px solid var(--accent-amber);
}
.bulk-models, .summary-models {
  padding: 0.55rem 1rem;
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.bulk-models summary, .summary-models summary {
  cursor: pointer;
  color: var(--text);
}
.bulk-model-list, .summary-model-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 0.25rem 1rem;
  margin-top: 0.6rem;
}
.bulk-model-list code, .summary-model-list code {
  color: var(--text-dim);
  overflow-wrap: anywhere;
}
.change-category {
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--border);
}
.change-category:last-child {
  border-bottom: none;
}
.category-label {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.4rem;
  font-weight: 600;
}
.change-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.change-table th {
  text-align: left;
  color: var(--text-dim);
  font-weight: 500;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.3rem 0.5rem;
  border-bottom: 1px solid var(--border);
}
.change-table td {
  padding: 0.4rem 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.82rem;
  vertical-align: top;
}
.change-table tr:nth-child(even) td {
  background: var(--bg-table-alt);
}
.field-name { color: var(--text); }
td.old-val { color: var(--text-dim); }
td.new-val { color: var(--text-bright); }
td.change-delta { font-weight: 600; }
td.delta-decrease { color: var(--accent-red); }
td.delta-increase { color: var(--accent-green); }
td.delta-neutral { color: var(--accent-amber); }
td.delta-price-higher { color: var(--accent-red); }
td.delta-price-lower { color: var(--accent-green); }
td.delta-price-coverage { color: var(--accent-blue); }
.list-diff {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  padding: 0.35rem 0;
}
.list-added { color: var(--accent-green); }
.list-removed { color: var(--accent-red); }
.list-count { color: var(--text-dim); font-size: 0.8rem; }
.summary-section {
  margin-top: 2.5rem;
  border-top: 1px solid var(--border);
  padding-top: 1.5rem;
}
.summary-section h2 {
  font-family: var(--font-mono);
  font-size: 1.1rem;
  color: var(--text-bright);
  margin-bottom: 1rem;
}
.summary-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.summary-table th {
  text-align: left;
  color: var(--text-dim);
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.5rem 0.75rem;
  border-bottom: 2px solid var(--border-accent);
  background: var(--bg-card);
}
.summary-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
.summary-table tr:nth-child(even) td {
  background: var(--bg-table-alt);
}
.summary-table .summary-models {
  padding: 0;
}
footer {
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 0.75rem;
  font-family: var(--font-mono);
}
</style>
</head>
<body>
<header>
  <h1>Model Sentinel <span class="count">— 6 changes</span></h1>
  <div class="meta">@@GENERATED_AT_HUMAN@@ &middot; scan</div>
</header>
<div class="provider-cards">
  <div class="provider-card status-changed"><div class="provider-name">Synth Provider</div><div class="provider-stats">6 models</div><div class="provider-badge">6 changes</div></div>
</div>

<section class="price-movement-summary"><div class="price-movement-title">Price Movement <span class="outcome price-higher">— higher</span></div><div class="price-movement-model-summary"><strong>1 affected model:</strong><span class="price-higher">1 with increases and no decreases</span></div><div class="price-movement-fields"><strong>4 changed price fields:</strong><span class="price-higher">2 higher</span><span class="price-coverage">1 added</span><span class="price-coverage">1 removed</span></div><details class="price-movement-models"><summary>View 1 affected model</summary><div class="price-movement-model-groups"><div class="price-movement-group"><div class="price-movement-group-label price-higher">↑ Higher, no decreases — 1</div><div class="price-movement-model"><span class="price-movement-provider">Synth Provider</span><code>synth/model-core</code></div></div></div></details></section>

<section class="provider-section"><h2>Synth Provider <span class="provider-id">(synthprov)</span></h2>
<h3>Changed</h3>
<div class="model-card">
<div class="model-card-header"><code>synth/model-core</code><span class="display-name">Synth Model Core</span></div>
<div class="change-category"><div class="category-label">Pricing</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">pricing.completion</td><td class="old-val">2e-06 ($2.00 / 1M)</td><td class="new-val">3.5e-06 ($3.50 / 1M)</td><td class="change-delta delta-price-higher">↑ 75.0%</td></tr>
<tr><td class="field-name">pricing.input_cache_read</td><td class="old-val">null</td><td class="new-val">5e-08 ($0.05 / 1M)</td><td class="change-delta delta-price-coverage">added</td></tr>
<tr><td class="field-name">pricing.input_cache_write</td><td class="old-val">9e-08 ($0.09 / 1M)</td><td class="new-val">null</td><td class="change-delta delta-price-coverage">removed</td></tr>
<tr><td class="field-name">pricing.overrides[min_prompt_tokens=200000].completion</td><td class="old-val">0.000004 ($4.00 / 1M)</td><td class="new-val">0.000005 ($5.00 / 1M)</td><td class="change-delta delta-price-higher">↑ 25.0%</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.context_length</td><td class="old-val">131,072</td><td class="new-val">262,144</td><td class="change-delta delta-increase">↑ 100.0%</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Parameters</div>
<div class="list-diff">
<span class="field-name">supported_parameters</span> 
<span class="list-count">(1 → 2)</span>
<div class="list-added">
&nbsp;&nbsp;+ logit_bias
</div>
</div>
</div>
<div class="change-category"><div class="category-label">Capabilities</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">reasoning.default_enabled</td><td class="old-val">0</td><td class="new-val">1</td><td class="change-delta delta-neutral"></td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Benchmarks</div>
<div class="list-diff">
<span class="field-name">benchmarks.example_suite</span> 
<span class="list-count">(1 → 1)</span>
<div class="list-added">
&nbsp;&nbsp;+ {&#x27;score&#x27;: 2}
</div>
<div class="list-removed">
&nbsp;&nbsp;− {&#x27;score&#x27;: 1}
</div>
</div>
</div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.is_moderated</td><td class="old-val">0</td><td class="new-val">1</td><td class="change-delta delta-neutral"></td></tr>
<tr><td class="field-name">expiration_date</td><td class="old-val">null</td><td class="new-val">2030-12-31</td><td class="change-delta delta-neutral">—</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-limit-add</code><span class="display-name">Synth Model Limit Add</span></div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.max_completion_tokens</td><td class="old-val">null</td><td class="new-val">16,384</td><td class="change-delta delta-increase">added</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-limit-remove</code><span class="display-name">Synth Model Limit Remove</span></div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.max_completion_tokens</td><td class="old-val">8,192</td><td class="new-val">null</td><td class="change-delta delta-decrease">removed</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-moderation-off</code><span class="display-name">Synth Model Moderation Off</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">top_provider.is_moderated</td><td class="old-val">1</td><td class="new-val">0</td><td class="change-delta delta-decrease">↓ 100.0%</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-temp-toggle</code><span class="display-name">Synth Model Temp Toggle</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">default_parameters.temperature</td><td class="old-val">0</td><td class="new-val">1</td><td class="change-delta delta-neutral"></td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-temp-null</code><span class="display-name">Synth Model Temp Null</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">default_parameters.temperature</td><td class="old-val">null</td><td class="new-val">null</td><td class="change-delta delta-neutral">—</td></tr>
</tbody></table>
</div>
</div></section>
<section class="summary-section"><h2>Change Summary</h2><table class="summary-table"><thead><tr><th>Category</th><th>Provider</th><th>Model</th><th>Field</th><th>Change</th></tr></thead><tbody><tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>pricing.completion</td><td>2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>pricing.input_cache_read</td><td>null → 5e-08 ($0.05 / 1M)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>pricing.input_cache_write</td><td>9e-08 ($0.09 / 1M) → null</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>pricing.overrides[min_prompt_tokens=200000].completion</td><td>0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>top_provider.context_length</td><td>131,072 → 262,144 (+131,072, ↑ 100.0%)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-limit-add</code></td><td>top_provider.max_completion_tokens</td><td>null → 16,384</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-limit-remove</code></td><td>top_provider.max_completion_tokens</td><td>8,192 → null</td></tr>
<tr><td>Parameters</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>supported_parameters</td><td>+logit_bias (1 → 2)</td></tr>
<tr><td>Capabilities</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>reasoning.default_enabled</td><td>0 → 1 (+1)</td></tr>
<tr><td>Benchmarks</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>benchmarks.example_suite</td><td>+{&#x27;score&#x27;: 2}; -{&#x27;score&#x27;: 1} (1 → 1)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>expiration_date</td><td>null → 2030-12-31</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>top_provider.is_moderated</td><td>0 → 1 (+1)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-moderation-off</code></td><td>top_provider.is_moderated</td><td>1 → 0 (-1, ↓ 100.0%)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-temp-null</code></td><td>default_parameters.temperature</td><td>null → null</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-temp-toggle</code></td><td>default_parameters.temperature</td><td>0 → 1 (+1)</td></tr></tbody></table></section>
<footer>Generated by Model Sentinel</footer>
</body>
</html>"""

EXPECTED_HTML_DETAIL_ALL = _EXPECTED_HTML_DETAIL_ALL_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_JSON_TEMPLATE = """{
  "command": "scan",
  "generated_at": "@@GENERATED_AT_ISO@@",
  "providers": [
    {
      "added": [],
      "baseline": null,
      "baseline_message": null,
      "changed": [
        {
          "display_name": "Synth Model Core",
          "field_changes": [
            {
              "field_name": "pricing.completion",
              "new_value": 3.5e-06,
              "old_value": 2e-06
            },
            {
              "field_name": "pricing.input_cache_read",
              "new_value": 5e-08,
              "old_value": null
            },
            {
              "field_name": "pricing.input_cache_write",
              "new_value": null,
              "old_value": 9e-08
            },
            {
              "field_name": "top_provider.context_length",
              "new_value": 262144,
              "old_value": 131072
            },
            {
              "field_name": "top_provider.is_moderated",
              "new_value": true,
              "old_value": false
            },
            {
              "field_name": "reasoning.default_enabled",
              "new_value": 1,
              "old_value": 0
            },
            {
              "field_name": "supported_parameters",
              "new_value": [
                "tools",
                "logit_bias"
              ],
              "old_value": [
                "tools"
              ]
            },
            {
              "field_name": "pricing.overrides",
              "new_value": [
                {
                  "completion": "0.000005",
                  "min_prompt_tokens": 200000
                }
              ],
              "old_value": [
                {
                  "completion": "0.000004",
                  "min_prompt_tokens": 200000
                }
              ]
            },
            {
              "field_name": "expiration_date",
              "new_value": "2030-12-31",
              "old_value": null
            },
            {
              "field_name": "benchmarks.example_suite",
              "new_value": [
                {
                  "score": 2
                }
              ],
              "old_value": [
                {
                  "score": 1
                }
              ]
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-core"
        },
        {
          "display_name": "Synth Model Limit Add",
          "field_changes": [
            {
              "field_name": "top_provider.max_completion_tokens",
              "new_value": 16384,
              "old_value": null
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-limit-add"
        },
        {
          "display_name": "Synth Model Limit Remove",
          "field_changes": [
            {
              "field_name": "top_provider.max_completion_tokens",
              "new_value": null,
              "old_value": 8192
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-limit-remove"
        },
        {
          "display_name": "Synth Model Moderation Off",
          "field_changes": [
            {
              "field_name": "top_provider.is_moderated",
              "new_value": false,
              "old_value": true
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-moderation-off"
        },
        {
          "display_name": "Synth Model Temp Toggle",
          "field_changes": [
            {
              "field_name": "default_parameters.temperature",
              "new_value": 1,
              "old_value": 0
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-temp-toggle"
        },
        {
          "display_name": "Synth Model Temp Null",
          "field_changes": [
            {
              "field_name": "default_parameters.temperature",
              "new_value": null,
              "old_value": null
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-temp-null"
        }
      ],
      "current_count": 6,
      "error_message": null,
      "provider_id": "synthprov",
      "provider_label": "Synth Provider",
      "removed": [],
      "saved": false,
      "scrape_id": null,
      "status": "success"
    }
  ]
}"""

EXPECTED_JSON = _EXPECTED_JSON_TEMPLATE.replace(ISO_TOKEN, _GENERATED_AT_ISO)


_EXPECTED_JSON_DETAIL_ALL_TEMPLATE = """{
  "command": "scan",
  "generated_at": "@@GENERATED_AT_ISO@@",
  "providers": [
    {
      "added": [],
      "baseline": null,
      "baseline_message": null,
      "changed": [
        {
          "display_name": "Synth Model Core",
          "field_changes": [
            {
              "field_name": "pricing.completion",
              "new_value": 3.5e-06,
              "old_value": 2e-06
            },
            {
              "field_name": "pricing.input_cache_read",
              "new_value": 5e-08,
              "old_value": null
            },
            {
              "field_name": "pricing.input_cache_write",
              "new_value": null,
              "old_value": 9e-08
            },
            {
              "field_name": "top_provider.context_length",
              "new_value": 262144,
              "old_value": 131072
            },
            {
              "field_name": "top_provider.is_moderated",
              "new_value": true,
              "old_value": false
            },
            {
              "field_name": "reasoning.default_enabled",
              "new_value": 1,
              "old_value": 0
            },
            {
              "field_name": "supported_parameters",
              "new_value": [
                "tools",
                "logit_bias"
              ],
              "old_value": [
                "tools"
              ]
            },
            {
              "field_name": "pricing.overrides",
              "new_value": [
                {
                  "completion": "0.000005",
                  "min_prompt_tokens": 200000
                }
              ],
              "old_value": [
                {
                  "completion": "0.000004",
                  "min_prompt_tokens": 200000
                }
              ]
            },
            {
              "field_name": "expiration_date",
              "new_value": "2030-12-31",
              "old_value": null
            },
            {
              "field_name": "benchmarks.example_suite",
              "new_value": [
                {
                  "score": 2
                }
              ],
              "old_value": [
                {
                  "score": 1
                }
              ]
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-core"
        },
        {
          "display_name": "Synth Model Limit Add",
          "field_changes": [
            {
              "field_name": "top_provider.max_completion_tokens",
              "new_value": 16384,
              "old_value": null
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-limit-add"
        },
        {
          "display_name": "Synth Model Limit Remove",
          "field_changes": [
            {
              "field_name": "top_provider.max_completion_tokens",
              "new_value": null,
              "old_value": 8192
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-limit-remove"
        },
        {
          "display_name": "Synth Model Moderation Off",
          "field_changes": [
            {
              "field_name": "top_provider.is_moderated",
              "new_value": false,
              "old_value": true
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-moderation-off"
        },
        {
          "display_name": "Synth Model Temp Toggle",
          "field_changes": [
            {
              "field_name": "default_parameters.temperature",
              "new_value": 1,
              "old_value": 0
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-temp-toggle"
        },
        {
          "display_name": "Synth Model Temp Null",
          "field_changes": [
            {
              "field_name": "default_parameters.temperature",
              "new_value": null,
              "old_value": null
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-temp-null"
        }
      ],
      "current_count": 6,
      "error_message": null,
      "provider_id": "synthprov",
      "provider_label": "Synth Provider",
      "removed": [],
      "saved": false,
      "scrape_id": null,
      "status": "success"
    }
  ]
}"""

EXPECTED_JSON_DETAIL_ALL = _EXPECTED_JSON_DETAIL_ALL_TEMPLATE.replace(ISO_TOKEN, _GENERATED_AT_ISO)



def test_characterization_text() -> None:
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="text",
        provider_results=characterization_scan_result(),
    )
    assert report == EXPECTED_TEXT


def test_characterization_markdown() -> None:
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="markdown",
        provider_results=characterization_scan_result(),
    )
    assert report == EXPECTED_MARKDOWN


def test_characterization_html() -> None:
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="html",
        provider_results=characterization_scan_result(),
    )
    assert report == EXPECTED_HTML


def test_characterization_json() -> None:
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="json",
        provider_results=characterization_scan_result(),
    )
    assert report == EXPECTED_JSON


def test_characterization_text_detail_all() -> None:
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="text",
        provider_results=characterization_scan_result(),
        detail_policy=ALL_DETAIL_POLICY,
    )
    assert report == EXPECTED_TEXT_DETAIL_ALL


def test_characterization_markdown_detail_all() -> None:
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="markdown",
        provider_results=characterization_scan_result(),
        detail_policy=ALL_DETAIL_POLICY,
    )
    assert report == EXPECTED_MARKDOWN_DETAIL_ALL


def test_characterization_html_detail_all() -> None:
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="html",
        provider_results=characterization_scan_result(),
        detail_policy=ALL_DETAIL_POLICY,
    )
    assert report == EXPECTED_HTML_DETAIL_ALL


def test_characterization_json_detail_all() -> None:
    # The JSON renderer ignores detail_policy entirely and always emits full
    # fidelity, so this is expected to be byte-identical to EXPECTED_JSON above --
    # that identity is itself part of what this test protects.
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="json",
        provider_results=characterization_scan_result(),
        detail_policy=ALL_DETAIL_POLICY,
    )
    assert report == EXPECTED_JSON_DETAIL_ALL
    assert EXPECTED_JSON_DETAIL_ALL == EXPECTED_JSON
