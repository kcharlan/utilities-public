"""Golden-output characterization tests for the `changes` REPORT renderers.

Third companion to `test_render_characterization.py` (the scan report's eight
goldens) and `test_render_bulk_characterization.py` (bulk and structured list
rendering). Both of those render through `render_scan_report`. This module
renders through `render_changes_report`, which is a different document built by
different functions:

    scan report card    _render_html_model_changes -> _render_html_card_table
                        -> _render_html_card_row          (C1's eight columns)
    changes report card _render_changes_html
                        -> _append_html_field_changes
                        -> _render_html_table_row         (four columns)

WHY THIS MODULE EXISTS (fix pass 2, finding 1). The `changes` HTML report had
no golden at all, and a defect landed in it because of that. Fix pass 1 taught
the shared summary builder (`_build_summary_entries_from_fc`, used by BOTH
documents) to spell an absent side `—` instead of `null`, to close a split in
the SCAN report. `_render_html_table_row` was left alone, so the `changes`
report -- which had been internally consistent, printing `null` in its card and
`null` in its summary -- started printing `null` in its card and `—` in its
summary. The full suite stayed green through both revisions. Nothing in it was
looking at this document.

So the golden below is not decoration around the fix; it is the fix's other
half. It pins the exact provider section and the exact summary table, which is
where an absent side is spelled twice, a few inches apart.

WHAT THE FIXTURE COVERS. One provider, one date, and a change of every shape
that can reach `_render_html_table_row` or the list-diff block beside it:

  * two-sided price (`pricing.prompt`) -- the `sem-cost-up` branch;
  * ONE-SIDED price added (`pricing.input_cache_read`, `null` old side);
  * ONE-SIDED price removed under a DYNAMIC path
    (`pricing.overrides[min_prompt_tokens=200000].completion`), which also pins
    that the qualifier survives into both the card and the summary;
  * ONE-SIDED count removed (`top_provider.max_completion_tokens`);
  * two-sided count (`top_provider.context_length`);
  * boolean toggle (`top_provider.is_moderated`), whose absent-side spelling
    was never `null` -- it is the row the other three now match;
  * ONE-SIDED scalar added (`expiration_date`);
  * a list membership change (`supported_parameters`), which does not go
    through the table at all;
  * a squelched field (`benchmarks.design_arena`), pinning the per-model
    hidden-summary block AND the provider-level squelched rollup card;
  * a model added and a model removed, pinning the presence lists and the two
    `colspan="2"` summary rows.

Four of those carry an absent side, in three different renderer branches. That
is the property this module exists to hold still.

FIXTURE FAITHFULNESS: `change_kind` is `"field_changed"`, `"added"` or
`"removed"`, and the presence rows carry `field_name=None` with null values --
the row shape `storage.py::record_field_changes` actually writes and
`get_changes` actually returns, not a convenient approximation of it.

TEXT IS PINNED HERE TOO, and deliberately: it is the control. The text report
must still say `null` on all four absent sides. If a future change closes the
split in `change_render` rather than in the HTML renderers, this golden fails
and says so, instead of the HTML goldens quietly agreeing with each other.

WHAT FIX PASS 3 MOVED (both HTML goldens; the text golden is byte-unchanged,
which is the evidence that both changes are HTML-scoped):

  * B1 finally reaches this document. Every `<td class="change-delta ...">`
    class changed from the direction-keyed `delta-*` set to the semantic
    `sem-*` set the scan card already used. Four rows change MEANING, not just
    spelling: `Context length` ↑ 100.0% was GREEN (`delta-increase`) and is now
    amber (`sem-capacity`); `Max output` removed was RED (`delta-decrease`) and
    is now coverage blue; `Moderated` enabled was green and is now capability
    blue; `Expiration date` was amber (`delta-neutral`) and is now dim
    (`sem-neutral`). The two price rows and the two price-coverage rows keep
    their colours and change class name only -- `delta-price-higher` and
    `sem-cost-up` were always the same red.
  * A1 reaches the Change Summary. Its `Change` cells were built by splitting
    the TEXT renderer's line, so they led with the raw provider value; they are
    now composed from `RenderedChange` as `old → new unit (delta, pct)`. The
    four-column table above keeps its `raw (normalized / 1M)` value cells, so
    this document deliberately spells a price two ways -- audit form in the
    table, A1 form in the index -- and the two goldens pin both.

DELIBERATELY NOT COVERED HERE: the full HTML document envelope (`<!DOCTYPE>`,
the `<style>` block) is already pinned byte-for-byte by
`test_render_characterization.py`; duplicating it would add hundreds of lines
of noise and a second place to update. The header is pinned because the
`changes` report has its own -- a scope line and a date count the scan report
does not have. Also not covered: bulk consolidation (that is the bulk module's
job -- `changes` reports do not consolidate) and `--detail all`/`squelched`.

Do NOT update the golden constants to make a refactor's tests pass silently.
A failing test here means renderer output changed; the reviewer must look at
the diff and decide whether the new output is intentional before updating the
constant.
"""

from __future__ import annotations

import json
import os
import time

from tests.html_probe import absent_side_cells

from model_sentinel.reporting import render_changes_report
from model_sentinel.provider_profiles import OPENROUTER_PROFILE

# Pin the process timezone to UTC before any golden constant below is defined,
# for the same reason as the other two characterization modules -- and with one
# extra consequence here: `render_changes_report` GROUPS by the local date of
# `detected_at`, so an unpinned timezone could move a change into a different
# date section, not merely reformat a timestamp.
os.environ["TZ"] = "UTC"
time.tzset()

DETECTED_AT = "2026-07-25T09:00:00+00:00"
SINCE = "2026-07-01"

# OpenRouter-style per-token pricing, so the normalized `$X.XX / 1M` figures in
# the goldens are the product of a real conversion rather than an identity.
PRICE_MULTIPLIER, PRICE_DIVISOR = 1000000, 1


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _row(
    model_id: str,
    display_name: str,
    field_name: str | None,
    old_value: object,
    new_value: object,
    *,
    change_kind: str = "field_changed",
) -> dict:
    return {
        "detected_at": DETECTED_AT,
        "provider_id": "synthprov",
        "provider_label": "Synth Provider",
        "provider_model_id": model_id,
        "display_name": display_name,
        "change_kind": change_kind,
        "field_name": field_name,
        "old_value": old_value,
        "new_value": new_value,
    }


def _changed(field_name: str, old_value: object, new_value: object) -> dict:
    return _row("synth/model-changes", "Synth Changes", field_name, old_value, new_value)


CHANGES_ROWS: tuple[dict, ...] = (
    # Pricing: two-sided, added, and removed-under-a-dynamic-path.
    _changed("pricing.prompt", "0.000001", "0.000002"),
    _changed("pricing.input_cache_read", None, "0.00000005"),
    _changed("pricing.overrides[min_prompt_tokens=200000].completion", "0.000004", None),
    # Context & limits: removed, then two-sided.
    _changed("top_provider.max_completion_tokens", 8192, None),
    _changed("top_provider.context_length", 131072, 262144),
    # Boolean toggle -- the row whose absent-side spelling was already `—`.
    _changed("top_provider.is_moderated", False, True),
    # Scalar added.
    _changed("expiration_date", None, "2030-12-31"),
    # List membership, which bypasses the change table entirely.
    _changed("supported_parameters", ["temperature", "tools"], ["temperature", "tools", "seed"]),
    # Squelched by the default policy.
    _changed("benchmarks.design_arena", 1, 2),
    # Presence rows, in the shape storage writes them.
    _row("synth/model-arrived", "Synth Arrived", None, None, None, change_kind="added"),
    _row("synth/model-departed", "Synth Departed", None, None, None, change_kind="removed"),
)


def render(format_name: str) -> str:
    return render_changes_report(
        format_name=format_name,
        provider_id=None,
        since=SINCE,
        until=None,
        changes=CHANGES_ROWS,
        provider_profiles={
            "synthprov": OPENROUTER_PROFILE.with_pricing(
                PRICE_MULTIPLIER,
                PRICE_DIVISOR,
            )
        },
    )


# ---------------------------------------------------------------------------
# Goldens
# ---------------------------------------------------------------------------

# The control. Every one-sided price, count and scalar still says `null` here,
# because `old_display`/`new_display` are shared by every renderer and only the
# HTML renderers respell them.
EXPECTED_TEXT = """Model Sentinel — Change Log

Since: 2026-07-01

11 changes across 1 date
============================================================

  2026-07-25
  ----------------------------------------
    Synth Provider
      * synth/model-changes (Synth Changes)
          [Pricing]
            Input: 0.000001 → 0.000002 ($1.00 → $2.00 / 1M, ↑ 100.0%)
            Cache read: null → 0.00000005 ($0.05 / 1M)
            Output (min_prompt_tokens=200000): 0.000004 ($4.00 / 1M) → null
          [Context & Limits]
            Max output: 8,192 → null
            Context length: 131,072 → 262,144 (+131,072, ↑ 100.0%)
          [Parameters]
            Supported parameters: +seed (2 → 3)
          [Other]
            Moderated: off → on
            Expiration date: null → 2030-12-31
          [Squelched]
            1 field change hidden by report detail policy
      + synth/model-arrived (Synth Arrived)
      - synth/model-departed (Synth Departed)
      squelched: 1 field change across 1 model
        patterns: benchmarks, benchmarks.*
        models: synth/model-changes"""


# The `changes` report's own header: a scope line built from `--since`, the
# total change count, and the number of date sections. The scan report's header
# shares none of this.
EXPECTED_HTML_HEADER = """<header>
  <h1>Model Sentinel <span class="count">— Change Log</span></h1>
  <div class="meta">Since: 2026-07-01 &middot; 11 changes across 1 date</div>
</header>"""


# The exact provider section. Note the four `—` cells: two in the Pricing
# table, one in Context & Limits, one in Other. Before fix pass 2 the first
# three of those said `null` while the summary below said `—`.
#
# The line holding `<span class="field-name">Supported parameters</span>` ends
# in a SIGNIFICANT trailing space -- that is what the list-diff block emits, and
# stripping it here would make this golden stop matching.
EXPECTED_HTML_BODY = """<section class="provider-section"><h2 class="date-heading">2026-07-25</h2>
<h3>Synth Provider</h3>
<ul class="model-list added-list">
<li><code>synth/model-arrived</code> <span class="display-name">Synth Arrived</span></li>
</ul>
<ul class="model-list removed-list">
<li><code>synth/model-departed</code> <span class="display-name">Synth Departed</span></li>
</ul>
<div class="model-card">
<div class="model-card-header"><code>synth/model-changes</code><span class="display-name">Synth Changes</span></div>
<div class="change-category"><div class="category-label">Pricing</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Input</td><td class="old-val">0.000001 ($1.00 / 1M)</td><td class="new-val">0.000002 ($2.00 / 1M)</td><td class="change-delta sem-cost-up">↑ 100.0%</td></tr>
<tr><td class="field-name">Cache read</td><td class="old-val">—</td><td class="new-val">0.00000005 ($0.05 / 1M)</td><td class="change-delta sem-coverage">added</td></tr>
<tr><td class="field-name">Output (min_prompt_tokens=200000)</td><td class="old-val">0.000004 ($4.00 / 1M)</td><td class="new-val">—</td><td class="change-delta sem-coverage">removed</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Context &amp; Limits</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Max output</td><td class="old-val">8,192</td><td class="new-val">—</td><td class="change-delta sem-coverage">removed</td></tr>
<tr><td class="field-name">Context length</td><td class="old-val">131,072</td><td class="new-val">262,144</td><td class="change-delta sem-capacity">↑ 100.0%</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Parameters</div>
<div class="list-diff">
<span class="field-name">Supported parameters</span> 
<span class="list-count">(2 → 3)</span>
<div class="list-added">
&nbsp;&nbsp;+ seed
</div>
</div>
</div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Moderated</td><td class="old-val">off</td><td class="new-val">on</td><td class="change-delta sem-capability">enabled</td></tr>
<tr><td class="field-name">Expiration date</td><td class="old-val">—</td><td class="new-val">2030-12-31</td><td class="change-delta sem-neutral">—</td></tr>
</tbody></table>
</div>
<div class="change-category"><div class="category-label">Squelched</div>
<div class="list-diff">1 field change hidden by report detail policy</div>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>squelched</code><span class="display-name">report detail summary</span></div>
<div class="change-category"><div class="category-label">squelched</div>
<div class="list-diff">1 field change across 1 model</div>
<div class="list-count">patterns: benchmarks, benchmarks.*</div>
<div class="list-count">models: synth/model-changes</div>
</div></div></section>"""


# The exact summary table. Rows are ordered by category, then by field label
# within a category, with the presence rows and the provider-level squelched
# rollup last. The three `—` sides here are the ones the body above must agree
# with.
EXPECTED_HTML_SUMMARY = """<section class="summary-section"><h2>Change Summary</h2><table class="summary-table"><thead><tr><th>Category</th><th>Provider</th><th>Model</th><th>Field</th><th>Change</th></tr></thead><tbody><tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-changes</code></td><td>Cache read</td><td>— → $0.05 /1M (added)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-changes</code></td><td>Input</td><td>$1.00 → $2.00 /1M (+$1.00, ↑ 100.0%)</td></tr>
<tr><td>Pricing</td><td>Synth Provider</td><td><code>synth/model-changes</code></td><td>Output (min_prompt_tokens=200000)</td><td>$4.00 → — /1M (removed)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-changes</code></td><td>Context length</td><td>131,072 → 262,144 tok (+131,072, ↑ 100.0%)</td></tr>
<tr><td>Context &amp; Limits</td><td>Synth Provider</td><td><code>synth/model-changes</code></td><td>Max output</td><td>8,192 → — tok (removed)</td></tr>
<tr><td>Parameters</td><td>Synth Provider</td><td><code>synth/model-changes</code></td><td>Supported parameters</td><td>+seed (2 → 3)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-changes</code></td><td>Expiration date</td><td>— → 2030-12-31</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-changes</code></td><td>Moderated</td><td>off → on (enabled)</td></tr>
<tr><td>Added</td><td>Synth Provider</td><td><code>synth/model-arrived</code></td><td colspan="2">Synth Arrived</td></tr>
<tr><td>Removed</td><td>Synth Provider</td><td><code>synth/model-departed</code></td><td colspan="2">Synth Departed</td></tr>
<tr><td>Squelched</td><td>Synth Provider</td><td><details class="summary-models"><summary>1 models</summary><div class="summary-model-list"><code>synth/model-changes</code></div></details></td><td>benchmarks, benchmarks.*</td><td>1 field change hidden by report detail policy</td></tr></tbody></table></section>"""


# ---------------------------------------------------------------------------
# Golden assertions
# ---------------------------------------------------------------------------


def test_changes_characterization_text() -> None:
    assert render("text") == EXPECTED_TEXT


def test_changes_characterization_html_header() -> None:
    assert EXPECTED_HTML_HEADER in render("html")


def test_changes_characterization_html_body() -> None:
    assert EXPECTED_HTML_BODY in render("html")


def test_changes_characterization_html_summary() -> None:
    assert EXPECTED_HTML_SUMMARY in render("html")


def test_changes_characterization_json_is_a_passthrough() -> None:
    """The audit path: `render_changes_report` serialises the rows verbatim.

    Pinned because it is the reason no HTML respelling can reach the machine-
    readable output -- there is no renderer between the rows and the JSON.
    """
    payload = json.loads(render("json"))
    assert payload["changes"] == list(CHANGES_ROWS)
    assert payload["since"] == SINCE
    assert "—" not in render("json")


# ---------------------------------------------------------------------------
# Targeted behavioral guards around the goldens
# ---------------------------------------------------------------------------


def test_the_changes_card_and_its_summary_agree_on_an_absent_side() -> None:
    """Fix pass 2, finding 1, stated as an invariant rather than a golden.

    The golden above would fail if this broke, but it would fail as a wall of
    diff. This names the property: within ONE document, every cell that can
    carry a side of a change spells an absent side the same way.

    Falsifiable by construction -- reverting `_render_html_table_row` to its
    `"null" if raw is None` literals puts `null` back into three of the cells
    below. The count assertion is what stops a probe that matched nothing from
    satisfying the loop vacuously.
    """
    html = render("html")
    cells = absent_side_cells(html)

    # 14 value cells (7 change-table rows x 2) + 9 summary change cells. The
    # two presence rows' merged `colspan="2"` cells carry a display name, not a
    # side, and are excluded by the probe.
    assert len(cells) == 23, cells
    for cell in cells:
        assert "null" not in cell, cell

    # The specific pair that was contradictory: the same field, spelled in the
    # card and in the summary of the same document. The two cells no longer
    # spell the VALUE identically -- the summary leads with the normalized
    # figure per fix pass 3's blocker 2, while this document's four-column
    # table keeps its `raw (normalized / 1M)` cell -- but the ABSENT side,
    # which is what this test is about, is `—` in both.
    assert '<td class="old-val">—</td><td class="new-val">0.00000005 ($0.05 / 1M)</td>' in html
    assert "<td>— → $0.05 /1M (added)</td>" in html

    # Exactly four cells are NOTHING BUT an em dash: the card's four absent
    # sides, produced by three different branches of `_render_html_table_row`
    # (price added, price removed, count removed, scalar added). The summary's
    # four matching sides read `— → ...` / `... → —`, so they are not counted
    # here -- the two assertions above are what pin those.
    assert sum(cell == "—" for cell in cells) == 4


def test_the_shared_text_line_still_spells_an_absent_side_null() -> None:
    """The respelling is confined to HTML, and this is what proves it.

    Without this, closing the split in `change_render._scalar_display` (or in
    the price and count classifiers) would satisfy every HTML assertion in this
    module while silently moving the text and markdown characterization
    goldens of the OTHER two modules.
    """
    text = render("text")
    for absent in (
        "Cache read: null → 0.00000005 ($0.05 / 1M)",
        "Output (min_prompt_tokens=200000): 0.000004 ($4.00 / 1M) → null",
        "Max output: 8,192 → null",
        "Expiration date: null → 2030-12-31",
    ):
        assert absent in text, absent
    # Not `"—" not in text`: the report TITLE is `Model Sentinel — Change Log`.
    # What must be absent is an em dash standing in for a side.
    assert "→ —" not in text
    assert "— →" not in text
