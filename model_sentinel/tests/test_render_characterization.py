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

DELIBERATE UPDATES SO FAR (each was reviewed diff-by-diff before landing):

* Task 3c unified list-member stringification on JSON, changing how `dict`
  members inside a list field are spelled.
* Task 4 landed E1 and E2, the first intentional readability changes. E1
  removed every `null -> null` row -- and, where that was a model's only
  change, the whole card and its summary row -- from the text, markdown and
  HTML goldens while leaving the JSON goldens untouched. E2 moved boolean
  fields off the numeric path: `off -> on` / `on -> off` with an
  `enabled`/`disabled` pill instead of `0 -> 1 (+1)` and `↓ 100.0%`, and a
  one-sided boolean now reads `— -> on` with an `added` pill.
* Task 4 fix pass 1 completed E1's accounting. Dropping a card left the
  provider's `changed: 7` / `### Changed (7)` counters standing over six, with
  nothing to say where the seventh went -- and, when EVERY model under a
  heading was no-op-only, the heading was emitted over nothing at all. The
  counters stay record counts; a provider-level `no-op: N field changes across
  M models` rollup now follows the pre-existing `squelched` rollup in the text,
  markdown and HTML goldens and names the models whose rows were dropped. That
  rollup line is the ONLY diff in this pass; the JSON goldens are untouched.
* Task 5 introduced the field-label registry, replacing raw dotted paths with
  human labels throughout the text, markdown and HTML goldens.
* Task 5 fix pass 1 made the renderers print the registry's `qualifier`
  alongside its label. The registry alone had collapsed
  `pricing.overrides[min_prompt_tokens=200000].completion` and a plain
  `pricing.completion` to the same bare `Output`, so `synth/model-core` showed
  two rows that read identically. Two diffs in this module, both consequences
  of that one change:
    1. the tiered row now reads `Output (min_prompt_tokens=200000)` in the
       text, markdown, HTML change-table and HTML Change Summary goldens;
    2. that row MOVED within the Change Summary. `_summary_entry_sort_key`
       orders on the displayed field text, and `"output"` sorts before
       `"output (min_prompt_tokens=200000)"`, so the tiered row now follows
       the base `Output` row. The section is the same 15 rows either way --
       `test_qualifier_change_summary_is_a_pure_permutation` below asserts
       that as a multiset rather than leaving it to the eye.
  The JSON goldens are untouched, as always.

* Task 6 replaced the magnitude-based price precision with the operand-based
  rule and changed NOT ONE golden in this module -- stated because a silent
  no-diff on a deliberate output change is exactly what should be checked
  rather than assumed. Every price in `characterization_scan_result()`
  resolves at two decimal places (`$2.00`, `$3.50`, `$0.05`, `$0.09`, `$4.00`,
  `$5.00`), which both the old rule and the new one spell identically. The
  consequence is that this fixture cannot demonstrate the new rule at all, so
  `test_sub_cent_precision_reaches_every_human_format` and its JSON
  counterpart carry their own single-model fixture below.

* Task 6 fix pass 1 gave the four-place cap an escape hatch (a row whose two
  operands are numerically different but render as ONE string extends past the
  cap until they differ) and, again, changed NOT ONE golden in this module --
  for the same reason: the shared fixture's prices all resolve at two places,
  which is below the cap, so neither the cap nor its hatch is reachable from
  them. `test_price_escape_hatch_reaches_every_human_format_but_not_json`
  carries its own fixture below. The same pass also disclosed a SECOND
  behaviour-change class from Task 6 that had gone unrecorded: prices >= $1
  with three or four significant decimals now render those decimals
  (`$12.345`, not the old rule's `$12.35`). That class is likewise invisible
  here -- `$2.00`, `$4.00` and `$5.00` have no decimals to keep -- and is
  pinned in `test_change_render.py`.

* Task 6 fix pass 2 widened that hatch's trigger (a row also extends when its
  DELTA would print as zero while being numerically non-zero) and, for the
  third time, changed NOT ONE golden in this module -- same reason again: the
  shared fixture's prices resolve at two places, where every delta it produces
  prints plainly. `test_vanishing_delta_row_reaches_every_human_format_but_
  not_json` carries its own fixture below.

The JSON goldens have never changed and must not: JSON is the audit path.
"""

from __future__ import annotations

import os
import time

from model_sentinel.models import FieldChange, ModelDelta, ProviderScanResult
from model_sentinel.reporting import (
    DEFAULT_REPORT_SHOW_FIELDS,
    ReportDetailPolicy,
    render_scan_report,
)

# Pin the process timezone to UTC before any golden constant below is defined.
# render_scan_report() formats timestamps through to_local_human()/to_local_iso()
# (model_sentinel/time_utils.py), both of which convert via datetime.astimezone()
# to whatever the OS considers "local". Without this pin, the golden constants
# would have to be computed through those same helper functions to stay portable
# across machines/CI runners in different timezones -- which would make the goldens
# self-fulfilling and unable to catch a future regression in those helpers'
# formatting. Pinning TZ here means "local" resolves to UTC for the whole test
# run (this also overrides any ambient `TZ=...` set by whoever invokes pytest),
# so the golden constants below can be hardcoded literal strings instead.
os.environ["TZ"] = "UTC"
time.tzset()

# Fixed instant used for every golden render in this module.
GENERATED_AT = "2026-07-25T09:00:00+00:00"
COMMAND = "scan"

# Literal expected renderings of GENERATED_AT, valid because TZ is pinned to UTC
# above. Do NOT replace these with calls to to_local_human()/to_local_iso() --
# that would make the timestamp assertions below tautological.
_GENERATED_AT_HUMAN = "2026-07-25 09:00:00"
_GENERATED_AT_ISO = "2026-07-25T09:00:00+00:00"
HUMAN_TOKEN = "@@GENERATED_AT_HUMAN@@"
ISO_TOKEN = "@@GENERATED_AT_ISO@@"

# Placeholder substituted with _EXPECTED_HTML_STYLE_BLOCK (defined further down,
# next to the HTML templates) so the identical <style> block isn't pasted twice
# across _EXPECTED_HTML_TEMPLATE and _EXPECTED_HTML_DETAIL_ALL_TEMPLATE.
STYLE_TOKEN = "@@STYLE_BLOCK@@"

ALL_DETAIL_POLICY = ReportDetailPolicy(
    mode="all",
    show_fields=DEFAULT_REPORT_SHOW_FIELDS,
    squelch_fields=("benchmarks", "benchmarks.*"),
    unclassified_limit=20,
)


def characterization_scan_result() -> list[ProviderScanResult]:
    """Fixture builder covering every field-classification branch in reporting.py.

    One provider, seven models. Model ``synth/model-core`` carries the bulk of
    the cases (cases 1-4, 7, 9, 11-14 from the task-1 brief); cases 5, 6, 8, 9b,
    10, and 15 each get their own model because they reuse a field name already
    used by another case and a real diff would never emit the same field twice
    for one model.

    Seven models are ALWAYS reported in the provider counters (`changed: 7`),
    which count `ModelDelta`s, not visible rows. Since E1 only six of them
    reach the human-readable goldens: `synth/model-temp-null`'s single change
    is a no-op, so the model contributes no card and no summary row there
    while staying fully present in the JSON golden. That asymmetry between
    the counters, the human formats, and JSON is deliberate and is what these
    goldens pin.
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
            # Case 9b: numeric field holding 0/1 that must NOT classify as
            # boolean. E2 put the boolean branch ahead of the numeric family,
            # so this is the direct counter-example proving KNOWN_BOOLEAN_FIELDS
            # is applied as a restriction: a temperature of 1 is a magnitude
            # and must keep rendering `0 -> 1 (+1)`, not `off -> on`.
            # (Separate model from cases 9/10 -- same field name as case 10.)
            (FieldChange("default_parameters.temperature", 0, 1),),
        ),
        ModelDelta(
            "changed",
            "synth/model-temp-null",
            "Synth Model Temp Null",
            # Case 10: null -> null. E1's case. Deliberately the ONLY change
            # on its own model, so suppression shows up in the goldens as an
            # entire card and summary row disappearing rather than one row
            # among several -- and so a renderer that suppressed the row but
            # still emitted an empty card would fail here.
            (FieldChange("default_parameters.temperature", None, None),),
        ),
        ModelDelta(
            "changed",
            "synth/model-moderation-added",
            "Synth Model Moderation Added",
            # Case 15: bool paired with None (one-sided), added from
            # None -> True. Through Task 3 this fell through to the generic
            # scalar fallback and leaked a raw Python repr into the report
            # (`null -> True`). Task 4 settled the open question: a one-sided
            # boolean is a `coverage` change presented like every other
            # one-sided change -- em dash on the absent side, `added` pill in
            # the delta column -- so the golden now reads `— -> on`. Separate
            # model from cases 7/8 (same field name).
            (FieldChange("top_provider.is_moderated", None, True),),
        ),
    )
    return [
        ProviderScanResult(
            provider_id="synthprov",
            provider_label="Synth Provider",
            status="success",
            current_count=7,
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
  current_count: 7
  added: 0
  removed: 0
  changed: 7
    * synth/model-core (Synth Model Core)
      [Pricing]
        Output: 2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)
        Cache read: null → 5e-08 ($0.05 / 1M)
        Cache write: 9e-08 ($0.09 / 1M) → null
        Output (min_prompt_tokens=200000): 0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)
      [Context & Limits]
        Context length: 131,072 → 262,144 (+131,072, ↑ 100.0%)
      [Parameters]
        Supported parameters: +logit_bias (1 → 2)
      [Capabilities]
        Reasoning default: off → on
      [Other]
        Moderated: off → on
        Expiration date: null → 2030-12-31
      [Squelched]
        1 field change hidden by report detail policy
    * synth/model-limit-add (Synth Model Limit Add)
      Max output: null → 16,384
    * synth/model-limit-remove (Synth Model Limit Remove)
      Max output: 8,192 → null
    * synth/model-moderation-off (Synth Model Moderation Off)
      Moderated: on → off
    * synth/model-temp-toggle (Synth Model Temp Toggle)
      Temperature: 0 → 1 (+1)
    * synth/model-moderation-added (Synth Model Moderation Added)
      Moderated: — → on
  squelched: 1 field change across 1 model
    patterns: benchmarks, benchmarks.*
    models: synth/model-core
  no-op: 1 field change across 1 model
    models: synth/model-temp-null

Summary
------------------------------------------------------------
  Synth Provider: 7 changed"""

EXPECTED_TEXT = _EXPECTED_TEXT_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_TEXT_DETAIL_ALL_TEMPLATE = """Model Sentinel report
Generated at: @@GENERATED_AT_HUMAN@@
Command: scan

Synth Provider (synthprov)
  status: success
  current_count: 7
  added: 0
  removed: 0
  changed: 7
    * synth/model-core (Synth Model Core)
      [Pricing]
        Output: 2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)
        Cache read: null → 5e-08 ($0.05 / 1M)
        Cache write: 9e-08 ($0.09 / 1M) → null
        Output (min_prompt_tokens=200000): 0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)
      [Context & Limits]
        Context length: 131,072 → 262,144 (+131,072, ↑ 100.0%)
      [Parameters]
        Supported parameters: +logit_bias (1 → 2)
      [Capabilities]
        Reasoning default: off → on
      [Benchmarks]
        Example suite: +{"score": 2}; -{"score": 1} (1 → 1)
      [Other]
        Moderated: off → on
        Expiration date: null → 2030-12-31
    * synth/model-limit-add (Synth Model Limit Add)
      Max output: null → 16,384
    * synth/model-limit-remove (Synth Model Limit Remove)
      Max output: 8,192 → null
    * synth/model-moderation-off (Synth Model Moderation Off)
      Moderated: on → off
    * synth/model-temp-toggle (Synth Model Temp Toggle)
      Temperature: 0 → 1 (+1)
    * synth/model-moderation-added (Synth Model Moderation Added)
      Moderated: — → on
  no-op: 1 field change across 1 model
    models: synth/model-temp-null

Summary
------------------------------------------------------------
  Synth Provider: 7 changed"""

EXPECTED_TEXT_DETAIL_ALL = _EXPECTED_TEXT_DETAIL_ALL_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_MARKDOWN_TEMPLATE = """# Model Sentinel Report

- Generated at: @@GENERATED_AT_HUMAN@@
- Command: scan

## Synth Provider (`synthprov`)

- Status: `success`
- Current models: `7`

### Added (0)

- None

### Removed (0)

- None

### Changed (7)

- `synth/model-core` - Synth Model Core
  - `Output: 2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)`
  - `Cache read: null → 5e-08 ($0.05 / 1M)`
  - `Cache write: 9e-08 ($0.09 / 1M) → null`
  - `Context length: 131,072 → 262,144 (+131,072, ↑ 100.0%)`
  - `Moderated: off → on`
  - `Reasoning default: off → on`
  - `Supported parameters: +logit_bias (1 → 2)`
  - `Output (min_prompt_tokens=200000): 0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)`
  - `Expiration date: null → 2030-12-31`
  - Squelched: `1` field change(s) hidden by report detail policy
- `synth/model-limit-add` - Synth Model Limit Add
  - `Max output: null → 16,384`
- `synth/model-limit-remove` - Synth Model Limit Remove
  - `Max output: 8,192 → null`
- `synth/model-moderation-off` - Synth Model Moderation Off
  - `Moderated: on → off`
- `synth/model-temp-toggle` - Synth Model Temp Toggle
  - `Temperature: 0 → 1 (+1)`
- `synth/model-moderation-added` - Synth Model Moderation Added
  - `Moderated: — → on`
- squelched: `1` field change across `1` model
- Squelch patterns: `benchmarks, benchmarks.*`
- Squelched models: `synth/model-core`
- no-op: `1` field change across `1` model
- No-op models: `synth/model-temp-null`"""

EXPECTED_MARKDOWN = _EXPECTED_MARKDOWN_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_MARKDOWN_DETAIL_ALL_TEMPLATE = """# Model Sentinel Report

- Generated at: @@GENERATED_AT_HUMAN@@
- Command: scan

## Synth Provider (`synthprov`)

- Status: `success`
- Current models: `7`

### Added (0)

- None

### Removed (0)

- None

### Changed (7)

- `synth/model-core` - Synth Model Core
  - `Output: 2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)`
  - `Cache read: null → 5e-08 ($0.05 / 1M)`
  - `Cache write: 9e-08 ($0.09 / 1M) → null`
  - `Context length: 131,072 → 262,144 (+131,072, ↑ 100.0%)`
  - `Moderated: off → on`
  - `Reasoning default: off → on`
  - `Supported parameters: +logit_bias (1 → 2)`
  - `Output (min_prompt_tokens=200000): 0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)`
  - `Expiration date: null → 2030-12-31`
  - `Example suite: +{"score": 2}; -{"score": 1} (1 → 1)`
- `synth/model-limit-add` - Synth Model Limit Add
  - `Max output: null → 16,384`
- `synth/model-limit-remove` - Synth Model Limit Remove
  - `Max output: 8,192 → null`
- `synth/model-moderation-off` - Synth Model Moderation Off
  - `Moderated: on → off`
- `synth/model-temp-toggle` - Synth Model Temp Toggle
  - `Temperature: 0 → 1 (+1)`
- `synth/model-moderation-added` - Synth Model Moderation Added
  - `Moderated: — → on`
- no-op: `1` field change across `1` model
- No-op models: `synth/model-temp-null`"""

EXPECTED_MARKDOWN_DETAIL_ALL = _EXPECTED_MARKDOWN_DETAIL_ALL_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


# The <style> block is byte-identical between _EXPECTED_HTML_TEMPLATE and
# _EXPECTED_HTML_DETAIL_ALL_TEMPLATE below (the detail policy only affects which
# rows/categories are rendered in <body>, not the stylesheet). It is kept here as
# one literal golden string and spliced into both templates via STYLE_TOKEN,
# rather than pasted twice, so a future CSS change only needs to be reviewed once.
# This is NOT imported from model_sentinel.reporting -- it is an independent golden
# copy, so it still catches an unintended CSS regression in the renderer.
_EXPECTED_HTML_STYLE_BLOCK = """:root {
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
}"""

_EXPECTED_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model Sentinel — @@GENERATED_AT_HUMAN@@</title>
<style>
@@STYLE_BLOCK@@
</style>
</head>
<body>
<header>
  <h1>Model Sentinel <span class="count">— 7 changes</span></h1>
  <div class="meta">@@GENERATED_AT_HUMAN@@ &middot; scan</div>
</header>
<div class="provider-cards">
  <div class="provider-card status-changed"><div class="provider-name">Synth Provider</div><div class="provider-stats">7 models</div><div class="provider-badge">7 changes</div></div>
</div>

<section class="price-movement-summary"><div class="price-movement-title">Price Movement <span class="outcome price-higher">— higher</span></div><div class="price-movement-model-summary"><strong>1 affected model:</strong><span class="price-higher">1 with increases and no decreases</span></div><div class="price-movement-fields"><strong>4 changed price fields:</strong><span class="price-higher">2 higher</span><span class="price-coverage">1 added</span><span class="price-coverage">1 removed</span></div><details class="price-movement-models"><summary>View 1 affected model</summary><div class="price-movement-model-groups"><div class="price-movement-group"><div class="price-movement-group-label price-higher">↑ Higher, no decreases — 1</div><div class="price-movement-model"><span class="price-movement-provider">Synth Provider</span><code>synth/model-core</code></div></div></div></details></section>

<section class="provider-section"><h2>Synth Provider <span class="provider-id">(synthprov)</span></h2>
<h3>Changed</h3>
<div class="model-card">
<div class="model-card-header"><code>synth/model-core</code><span class="display-name">Synth Model Core</span></div>
<div class="change-category"><div class="category-label">Pricing</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Output</td><td class="old-val">2e-06 ($2.00 / 1M)</td><td class="new-val">3.5e-06 ($3.50 / 1M)</td><td class="change-delta delta-price-higher">↑ 75.0%</td></tr>
<tr><td class="field-name">Cache read</td><td class="old-val">null</td><td class="new-val">5e-08 ($0.05 / 1M)</td><td class="change-delta delta-price-coverage">added</td></tr>
<tr><td class="field-name">Cache write</td><td class="old-val">9e-08 ($0.09 / 1M)</td><td class="new-val">null</td><td class="change-delta delta-price-coverage">removed</td></tr>
<tr><td class="field-name">Output (min_prompt_tokens=200000)</td><td class="old-val">0.000004 ($4.00 / 1M)</td><td class="new-val">0.000005 ($5.00 / 1M)</td><td class="change-delta delta-price-higher">↑ 25.0%</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Context length</td><td class="old-val">131,072</td><td class="new-val">262,144</td><td class="change-delta delta-increase">↑ 100.0%</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Parameters</div>
<div class="list-diff">
<span class="field-name">Supported parameters</span> 
<span class="list-count">(1 → 2)</span>
<div class="list-added">
&nbsp;&nbsp;+ logit_bias
</div>
</div>
</div>
<div class="change-category"><div class="category-label">Capabilities</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Reasoning default</td><td class="old-val">off</td><td class="new-val">on</td><td class="change-delta delta-increase">enabled</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Moderated</td><td class="old-val">off</td><td class="new-val">on</td><td class="change-delta delta-increase">enabled</td></tr>
<tr><td class="field-name">Expiration date</td><td class="old-val">null</td><td class="new-val">2030-12-31</td><td class="change-delta delta-neutral">—</td></tr>
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
<tr><td class="field-name">Max output</td><td class="old-val">null</td><td class="new-val">16,384</td><td class="change-delta delta-increase">added</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-limit-remove</code><span class="display-name">Synth Model Limit Remove</span></div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Max output</td><td class="old-val">8,192</td><td class="new-val">null</td><td class="change-delta delta-decrease">removed</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-moderation-off</code><span class="display-name">Synth Model Moderation Off</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Moderated</td><td class="old-val">on</td><td class="new-val">off</td><td class="change-delta delta-decrease">disabled</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-temp-toggle</code><span class="display-name">Synth Model Temp Toggle</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Temperature</td><td class="old-val">0</td><td class="new-val">1</td><td class="change-delta delta-neutral"></td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-moderation-added</code><span class="display-name">Synth Model Moderation Added</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Moderated</td><td class="old-val">—</td><td class="new-val">on</td><td class="change-delta delta-increase">added</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>squelched</code><span class="display-name">report detail summary</span></div>
<div class="change-category"><div class="category-label">squelched</div>
<div class="list-diff">1 field change across 1 model</div>
<div class="list-count">patterns: benchmarks, benchmarks.*</div>
<div class="list-count">models: synth/model-core</div>
</div></div>
<div class="model-card">
<div class="model-card-header"><code>no-op</code><span class="display-name">report detail summary</span></div>
<div class="change-category"><div class="category-label">no-op</div>
<div class="list-diff">1 field change across 1 model</div>
<div class="list-count">models: synth/model-temp-null</div>
</div></div></section>
<section class="summary-section"><h2>Change Summary</h2><table class="summary-table"><thead><tr><th>Category</th><th>Provider</th><th>Model</th><th>Field</th><th>Change</th></tr></thead><tbody><tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Cache read</td><td>null → 5e-08 ($0.05 / 1M)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Cache write</td><td>9e-08 ($0.09 / 1M) → null</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Output</td><td>2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Output (min_prompt_tokens=200000)</td><td>0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Context length</td><td>131,072 → 262,144 (+131,072, ↑ 100.0%)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-limit-add</code></td><td>Max output</td><td>null → 16,384</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-limit-remove</code></td><td>Max output</td><td>8,192 → null</td></tr>
<tr><td>Parameters</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Supported parameters</td><td>+logit_bias (1 → 2)</td></tr>
<tr><td>Capabilities</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Reasoning default</td><td>off → on</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Expiration date</td><td>null → 2030-12-31</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Moderated</td><td>off → on</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-moderation-added</code></td><td>Moderated</td><td>— → on</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-moderation-off</code></td><td>Moderated</td><td>on → off</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-temp-toggle</code></td><td>Temperature</td><td>0 → 1 (+1)</td></tr>
<tr><td>Squelched</td><td>Synth Provider</td><td><details class="summary-models"><summary>1 models</summary><div class="summary-model-list"><code>synth/model-core</code></div></details></td><td>benchmarks, benchmarks.*</td><td>1 field change hidden by report detail policy</td></tr></tbody></table></section>
<footer>Generated by Model Sentinel</footer>
</body>
</html>"""

EXPECTED_HTML = _EXPECTED_HTML_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN).replace(
    STYLE_TOKEN, _EXPECTED_HTML_STYLE_BLOCK
)


_EXPECTED_HTML_DETAIL_ALL_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model Sentinel — @@GENERATED_AT_HUMAN@@</title>
<style>
@@STYLE_BLOCK@@
</style>
</head>
<body>
<header>
  <h1>Model Sentinel <span class="count">— 7 changes</span></h1>
  <div class="meta">@@GENERATED_AT_HUMAN@@ &middot; scan</div>
</header>
<div class="provider-cards">
  <div class="provider-card status-changed"><div class="provider-name">Synth Provider</div><div class="provider-stats">7 models</div><div class="provider-badge">7 changes</div></div>
</div>

<section class="price-movement-summary"><div class="price-movement-title">Price Movement <span class="outcome price-higher">— higher</span></div><div class="price-movement-model-summary"><strong>1 affected model:</strong><span class="price-higher">1 with increases and no decreases</span></div><div class="price-movement-fields"><strong>4 changed price fields:</strong><span class="price-higher">2 higher</span><span class="price-coverage">1 added</span><span class="price-coverage">1 removed</span></div><details class="price-movement-models"><summary>View 1 affected model</summary><div class="price-movement-model-groups"><div class="price-movement-group"><div class="price-movement-group-label price-higher">↑ Higher, no decreases — 1</div><div class="price-movement-model"><span class="price-movement-provider">Synth Provider</span><code>synth/model-core</code></div></div></div></details></section>

<section class="provider-section"><h2>Synth Provider <span class="provider-id">(synthprov)</span></h2>
<h3>Changed</h3>
<div class="model-card">
<div class="model-card-header"><code>synth/model-core</code><span class="display-name">Synth Model Core</span></div>
<div class="change-category"><div class="category-label">Pricing</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Output</td><td class="old-val">2e-06 ($2.00 / 1M)</td><td class="new-val">3.5e-06 ($3.50 / 1M)</td><td class="change-delta delta-price-higher">↑ 75.0%</td></tr>
<tr><td class="field-name">Cache read</td><td class="old-val">null</td><td class="new-val">5e-08 ($0.05 / 1M)</td><td class="change-delta delta-price-coverage">added</td></tr>
<tr><td class="field-name">Cache write</td><td class="old-val">9e-08 ($0.09 / 1M)</td><td class="new-val">null</td><td class="change-delta delta-price-coverage">removed</td></tr>
<tr><td class="field-name">Output (min_prompt_tokens=200000)</td><td class="old-val">0.000004 ($4.00 / 1M)</td><td class="new-val">0.000005 ($5.00 / 1M)</td><td class="change-delta delta-price-higher">↑ 25.0%</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Context length</td><td class="old-val">131,072</td><td class="new-val">262,144</td><td class="change-delta delta-increase">↑ 100.0%</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Parameters</div>
<div class="list-diff">
<span class="field-name">Supported parameters</span> 
<span class="list-count">(1 → 2)</span>
<div class="list-added">
&nbsp;&nbsp;+ logit_bias
</div>
</div>
</div>
<div class="change-category"><div class="category-label">Capabilities</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Reasoning default</td><td class="old-val">off</td><td class="new-val">on</td><td class="change-delta delta-increase">enabled</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Benchmarks</div>
<div class="list-diff">
<span class="field-name">Example suite</span> 
<span class="list-count">(1 → 1)</span>
<div class="list-added">
&nbsp;&nbsp;+ {&quot;score&quot;: 2}
</div>
<div class="list-removed">
&nbsp;&nbsp;− {&quot;score&quot;: 1}
</div>
</div>
</div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Moderated</td><td class="old-val">off</td><td class="new-val">on</td><td class="change-delta delta-increase">enabled</td></tr>
<tr><td class="field-name">Expiration date</td><td class="old-val">null</td><td class="new-val">2030-12-31</td><td class="change-delta delta-neutral">—</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-limit-add</code><span class="display-name">Synth Model Limit Add</span></div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Max output</td><td class="old-val">null</td><td class="new-val">16,384</td><td class="change-delta delta-increase">added</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-limit-remove</code><span class="display-name">Synth Model Limit Remove</span></div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Max output</td><td class="old-val">8,192</td><td class="new-val">null</td><td class="change-delta delta-decrease">removed</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-moderation-off</code><span class="display-name">Synth Model Moderation Off</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Moderated</td><td class="old-val">on</td><td class="new-val">off</td><td class="change-delta delta-decrease">disabled</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-temp-toggle</code><span class="display-name">Synth Model Temp Toggle</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Temperature</td><td class="old-val">0</td><td class="new-val">1</td><td class="change-delta delta-neutral"></td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-moderation-added</code><span class="display-name">Synth Model Moderation Added</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Moderated</td><td class="old-val">—</td><td class="new-val">on</td><td class="change-delta delta-increase">added</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>no-op</code><span class="display-name">report detail summary</span></div>
<div class="change-category"><div class="category-label">no-op</div>
<div class="list-diff">1 field change across 1 model</div>
<div class="list-count">models: synth/model-temp-null</div>
</div></div></section>
<section class="summary-section"><h2>Change Summary</h2><table class="summary-table"><thead><tr><th>Category</th><th>Provider</th><th>Model</th><th>Field</th><th>Change</th></tr></thead><tbody><tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Cache read</td><td>null → 5e-08 ($0.05 / 1M)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Cache write</td><td>9e-08 ($0.09 / 1M) → null</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Output</td><td>2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Output (min_prompt_tokens=200000)</td><td>0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Context length</td><td>131,072 → 262,144 (+131,072, ↑ 100.0%)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-limit-add</code></td><td>Max output</td><td>null → 16,384</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-limit-remove</code></td><td>Max output</td><td>8,192 → null</td></tr>
<tr><td>Parameters</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Supported parameters</td><td>+logit_bias (1 → 2)</td></tr>
<tr><td>Capabilities</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Reasoning default</td><td>off → on</td></tr>
<tr><td>Benchmarks</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Example suite</td><td>+{&quot;score&quot;: 2}; -{&quot;score&quot;: 1} (1 → 1)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Expiration date</td><td>null → 2030-12-31</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-core</code></td><td>Moderated</td><td>off → on</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-moderation-added</code></td><td>Moderated</td><td>— → on</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-moderation-off</code></td><td>Moderated</td><td>on → off</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-temp-toggle</code></td><td>Temperature</td><td>0 → 1 (+1)</td></tr></tbody></table></section>
<footer>Generated by Model Sentinel</footer>
</body>
</html>"""

EXPECTED_HTML_DETAIL_ALL = _EXPECTED_HTML_DETAIL_ALL_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN).replace(
    STYLE_TOKEN, _EXPECTED_HTML_STYLE_BLOCK
)


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
        },
        {
          "display_name": "Synth Model Moderation Added",
          "field_changes": [
            {
              "field_name": "top_provider.is_moderated",
              "new_value": true,
              "old_value": null
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-moderation-added"
        }
      ],
      "current_count": 7,
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
        },
        {
          "display_name": "Synth Model Moderation Added",
          "field_changes": [
            {
              "field_name": "top_provider.is_moderated",
              "new_value": true,
              "old_value": null
            }
          ],
          "kind": "changed",
          "provider_model_id": "synth/model-moderation-added"
        }
      ],
      "current_count": 7,
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


# ---------------------------------------------------------------------------
# Change Summary: what the qualifier did, and did not, do to the section.
#
# `_summary_entry_sort_key` sorts on the DISPLAYED field text, so any change to
# how a field is spelled reorders this section. Task 5 moved it once (raw paths
# -> registry labels) and this pass moves it again (labels -> labels with
# qualifiers). Reordering is acceptable; gaining, losing or duplicating a row
# is not, and an ordered golden alone cannot tell those apart at a glance.
#
# The two constants below split each row at the only cell a qualifier can
# touch. `_SUMMARY_ROW_SHAPES` is the row multiset with the Field cell removed
# -- it is byte-identical to what b94a9d3 produced and must stay that way.
# `_SUMMARY_FIELD_CELLS` is the Field cells alone; exactly one entry differs
# from b94a9d3, which is the whole intent of this pass.
# ---------------------------------------------------------------------------

_SUMMARY_CORE = "<td>Synth Provider</td><td><code>synth/model-core</code></td>"

_SUMMARY_ROW_SHAPES = (
    f"<td>Pricing</td>{_SUMMARY_CORE}<td>null → 5e-08 ($0.05 / 1M)</td>",
    f"<td>Pricing</td>{_SUMMARY_CORE}<td>9e-08 ($0.09 / 1M) → null</td>",
    f"<td>Pricing</td>{_SUMMARY_CORE}<td>2e-06 → 3.5e-06 ($2.00 → $3.50 / 1M, ↑ 75.0%)</td>",
    f"<td>Pricing</td>{_SUMMARY_CORE}<td>0.000004 → 0.000005 ($4.00 → $5.00 / 1M, ↑ 25.0%)</td>",
    f"<td>Context &amp; Limits</td>{_SUMMARY_CORE}<td>131,072 → 262,144 (+131,072, ↑ 100.0%)</td>",
    "<td>Context &amp; Limits</td><td>Synth Provider</td>"
    "<td><code>synth/model-limit-add</code></td><td>null → 16,384</td>",
    "<td>Context &amp; Limits</td><td>Synth Provider</td>"
    "<td><code>synth/model-limit-remove</code></td><td>8,192 → null</td>",
    f"<td>Parameters</td>{_SUMMARY_CORE}<td>+logit_bias (1 → 2)</td>",
    f"<td>Capabilities</td>{_SUMMARY_CORE}<td>off → on</td>",
    f"<td>Other</td>{_SUMMARY_CORE}<td>null → 2030-12-31</td>",
    f"<td>Other</td>{_SUMMARY_CORE}<td>off → on</td>",
    "<td>Other</td><td>Synth Provider</td>"
    "<td><code>synth/model-moderation-added</code></td><td>— → on</td>",
    "<td>Other</td><td>Synth Provider</td>"
    "<td><code>synth/model-moderation-off</code></td><td>on → off</td>",
    "<td>Other</td><td>Synth Provider</td>"
    "<td><code>synth/model-temp-toggle</code></td><td>0 → 1 (+1)</td>",
    '<td>Squelched</td><td>Synth Provider</td><td><details class="summary-models">'
    '<summary>1 models</summary><div class="summary-model-list">'
    "<code>synth/model-core</code></div></details></td>"
    "<td>1 field change hidden by report detail policy</td>",
)

_SUMMARY_FIELD_CELLS = (
    "Cache read",
    "Cache write",
    "Output",
    # The ONLY cell this pass changed. Under b94a9d3 this read "Output" -- two
    # rows for one model, both spelled "Output", one the base rate and one the
    # 200K-token tier, with nothing in the report to say which was which.
    "Output (min_prompt_tokens=200000)",
    "Context length",
    "Max output",
    "Max output",
    "Supported parameters",
    "Reasoning default",
    "Expiration date",
    "Moderated",
    "Moderated",
    "Moderated",
    "Temperature",
    "benchmarks, benchmarks.*",
)


def _summary_rows(html: str) -> list[str]:
    """The `<tr>` bodies of the Change Summary section, in document order."""
    start = html.index('<section class="summary-section">')
    section = html[start : html.index("</section>", start)]
    body = section[section.index("<tbody>") : section.index("</tbody>")]
    return [row for row in body.split("<tr>")[1:]]


def _split_summary_row(row: str) -> tuple[str, str]:
    """Return `(row_without_field_cell, field_cell)` for one summary row.

    Every summary row is five `<td>`s (or three, for the colspan-2 presence
    rows, which this fixture does not produce). The Field cell is the fourth
    and is the only one a qualifier can reach.
    """
    body = row[: row.index("</tr>")]
    cells = ["<td>" + cell for cell in body.split("<td>")[1:]]
    assert len(cells) == 5, row
    field_cell = cells[3]
    assert field_cell.startswith("<td>") and field_cell.endswith("</td>"), field_cell
    return "".join(cells[:3] + cells[4:]), field_cell[len("<td>") : -len("</td>")]


def test_qualifier_change_summary_is_a_pure_permutation() -> None:
    """The section still holds the same 15 rows; only order and one cell moved.

    Checked as a MULTISET, not by reading the ordered golden: `sorted()` on
    both sides, so a row that was silently duplicated or dropped by the re-sort
    fails here even though the ordered golden was updated wholesale.

    `_SUMMARY_ROW_SHAPES` deliberately excludes the Field cell, which makes it
    invariant across this pass -- if anything OTHER than the field label
    changed, this assertion is what catches it.
    """
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="html",
        provider_results=characterization_scan_result(),
    )
    rows = _summary_rows(report)
    assert len(rows) == 15
    assert len(_SUMMARY_ROW_SHAPES) == 15
    assert len(_SUMMARY_FIELD_CELLS) == 15

    shapes, field_cells = zip(*(_split_summary_row(row) for row in rows))
    assert sorted(shapes) == sorted(_SUMMARY_ROW_SHAPES)
    assert sorted(field_cells) == sorted(_SUMMARY_FIELD_CELLS)


def test_qualifier_is_what_reordered_the_change_summary() -> None:
    """Names the cause of the reorder, so a future reorder is not mistaken for it.

    The tiered row sorts after the base row for exactly one reason: the sort
    key is the displayed field text and `"output"` is a prefix of
    `"output (min_prompt_tokens=200000)"`. Both rows belong to the same model
    and the same category, so nothing else in the key can separate them.
    """
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="html",
        provider_results=characterization_scan_result(),
    )
    field_cells = [_split_summary_row(row)[1] for row in _summary_rows(report)]
    assert field_cells.index("Output") < field_cells.index("Output (min_prompt_tokens=200000)")
    assert "Output".casefold() < "Output (min_prompt_tokens=200000)".casefold()


def _sub_cent_price_scan_result() -> list[ProviderScanResult]:
    """One model, one price change, deliberately below cent resolution.

    Separate from `characterization_scan_result()` ON PURPOSE. Every price in
    that fixture resolves at two decimal places, so the Task 6 precision rule
    left all eight of its goldens byte-identical -- which is worth having, but
    means the shared fixture cannot demonstrate the new rule at all. Adding a
    sub-cent field to it would also have moved the JSON goldens (a new field
    change is a new JSON entry), destroying the evidence that JSON is untouched.
    """
    return [
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
                    "synth/model-subcent",
                    "Synth Model Subcent",
                    (FieldChange("pricing.prompt", 0.00000015, 0.0000001425),),
                ),
            ),
            error_message=None,
            price_multiplier=1000000,
            price_divisor=1,
        )
    ]


def test_sub_cent_precision_reaches_every_human_format() -> None:
    """The shared precision is a property of `RenderedChange`, so it should
    reach text, markdown and HTML without any per-renderer change. Verified,
    not assumed.

    `0.15` needs two decimal places on its own and renders at four because the
    other operand needs four. Every human format must show BOTH operands at
    four: a format that formatted one of them independently would print
    `$0.15` here and pass every other test in this module.
    """
    for format_name in ("text", "markdown", "html"):
        report = render_scan_report(
            generated_at=GENERATED_AT,
            command=COMMAND,
            format_name=format_name,
            provider_results=_sub_cent_price_scan_result(),
        )
        assert "$0.1500" in report, format_name
        assert "$0.1425" in report, format_name
        # The replaced rule's spelling of the same pair: two places against
        # four. Absent from every format, or the row is still magnitude-priced.
        assert "$0.15 " not in report, format_name
        # ...and absent in EVERY delimiter, not just the space-delimited one.
        # `$0.1500` contains `$0.15`, so equal counts means every occurrence of
        # `$0.15` is the head of a `$0.1500` and none is a bare two-place
        # price. (The previous line's `"$0.196" not in report` was vacuous:
        # this fixture's operands are 0.15 and 0.1425, so no implementation
        # could ever emit 0.196.)
        assert report.count("$0.15") == report.count("$0.1500"), format_name


def test_sub_cent_precision_does_not_reach_json() -> None:
    """JSON is the audit path: raw values, no formatted prices, ever.

    The precision rule lives entirely in `RenderedChange`, and `_delta_to_json`
    serialises `FieldChange` directly -- so no rounding can reach the machine-
    readable output. Asserted on the absence of a dollar sign rather than on a
    golden string, so any future formatted price leaking into JSON fails here.
    """
    report = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="json",
        provider_results=_sub_cent_price_scan_result(),
    )
    assert "$" not in report
    assert "1.5e-07" in report
    assert "1.425e-07" in report


def _escape_hatch_price_scan_result() -> list[ProviderScanResult]:
    """A provider configured as if its raw prices were already per-1M.

    `price_multiplier=1` is the misconfiguration the escape hatch exists for:
    per-TOKEN values land unscaled in a per-1M column, where the four-place cap
    would render both sides of a doubling as `$0.0000`. Separate fixture for
    the same reason as `_sub_cent_price_scan_result` -- adding a field to the
    shared fixture would move the JSON goldens.
    """
    return [
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
                    (FieldChange("pricing.prompt", 0.000001, 0.000002),),
                ),
            ),
            error_message=None,
            price_multiplier=1,
            price_divisor=1,
        )
    ]


def test_price_escape_hatch_reaches_every_human_format_but_not_json() -> None:
    """The hatch is a property of `RenderedChange`, so every renderer gets it.

    Text and markdown are the reason the hatch had to exist at all: the design
    note that "the tooltip will carry exactness" is an HTML-only mitigation,
    unavailable in the two formats a scheduled run actually mails out. All
    three human formats must therefore show the movement themselves, and none
    may still print the capped `$0.0000` for either operand.

    JSON is asserted unchanged in the same test rather than a separate one, so
    the human-format expectation and the audit-path expectation cannot drift.
    """
    for format_name in ("text", "markdown", "html"):
        report = render_scan_report(
            generated_at=GENERATED_AT,
            command=COMMAND,
            format_name=format_name,
            provider_results=_escape_hatch_price_scan_result(),
        )
        assert "$0.000001" in report, format_name
        assert "$0.000002" in report, format_name
        # The capped spelling the hatch replaces. `$0.000001` does not contain
        # `$0.0000 ` (the next char is a digit), so this cannot pass by prefix.
        assert "$0.0000 " not in report, format_name

    payload = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="json",
        provider_results=_escape_hatch_price_scan_result(),
    )
    assert "$" not in payload
    assert "1e-06" in payload
    assert "2e-06" in payload


def _vanishing_delta_price_scan_result() -> list[ProviderScanResult]:
    """A row whose operands separate at the cap's edge but whose delta does not.

    `0.000124999 -> 0.000125001` is the hatch's second face: five places
    already tell the two prices apart, so the operand face stops asking there
    and leaves a `+$0.00000` delta standing beside two visibly different
    numbers. Separate fixture for the same reason as the two above -- adding a
    field to the shared fixture would move the JSON goldens and destroy the
    evidence that JSON is untouched.
    """
    return [
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
                    "synth/model-vanishing",
                    "Synth Model Vanishing",
                    (FieldChange("pricing.prompt", 0.000124999, 0.000125001),),
                ),
            ),
            error_message=None,
            price_multiplier=1,
            price_divisor=1,
        )
    ]


def test_vanishing_delta_row_reaches_every_human_format_but_not_json() -> None:
    """The widened hatch is a property of `RenderedChange`, so every renderer gets it.

    The five-place row the operand face alone produced (`$0.00012 → $0.00013`)
    must appear in NO human format: it prints two prices whose difference the
    row then puts at zero. All three must show the nine-place spelling instead.

    JSON is asserted unchanged in the same test rather than a separate one, so
    the human-format expectation and the audit-path expectation cannot drift.
    """
    for format_name in ("text", "markdown", "html"):
        report = render_scan_report(
            generated_at=GENERATED_AT,
            command=COMMAND,
            format_name=format_name,
            provider_results=_vanishing_delta_price_scan_result(),
        )
        assert "$0.000124999" in report, format_name
        assert "$0.000125001" in report, format_name
        # The five-place spelling, ruled out by counting rather than by
        # `not in`: BOTH nine-place prices begin `$0.00012`, so equal counts
        # means every occurrence of the short form is the head of a long one
        # and none is a bare five-place price.
        assert report.count("$0.00012") == (
            report.count("$0.000124999") + report.count("$0.000125001")
        ), format_name

    payload = render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name="json",
        provider_results=_vanishing_delta_price_scan_result(),
    )
    assert "$" not in payload
    assert "0.000124999" in payload
    assert "0.000125001" in payload


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
