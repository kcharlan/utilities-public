"""Golden-output characterization tests for BULK and STRUCTURED list rendering.

Companion to `test_render_characterization.py`. That module's eight goldens
cover fifteen field-change cases, but every one of them renders through a
single-model, non-bulk path, so three renderer paths were left unpinned:

1. **Bulk change grouping.** When three or more models (`BULK_CHANGE_MIN_MODELS`
   in reporting.py) share a byte-identical list-change signature, the default
   detail policy consolidates them into one bulk card rendered by
   `_render_bulk_list_diff_text` / `_render_html_bulk_list_diff` instead of one
   per-model card each. Those two renderers were entirely uncovered.
2. **Structured (`dict`) members inside a list field.** Bulk and per-model
   renderers used to stringify list members through *different* helpers that
   disagreed for `dict`/`list` members -- see BULK VS PER-MODEL below.
3. **One-sided list changes** (`None` -> list and list -> `None`), which never
   reach the list branch at all: `classify_change` routes them to `scalar`,
   and if the list is "structured" (contains dicts) `reporting.py` flattens it
   into indexed leaf changes before classification ever runs.

BULK VS PER-MODEL STRINGIFICATION (a shipped inconsistency, now fixed):

Bulk grouping and the bulk cards stringified members with `_list_item_text`,
which JSON-encodes `dict`/`list` members, while `classify_change`'s list
branch (per-model) used plain `str(x)`. For plain-string members the two
agreed exactly, so nothing downstream could tell them apart -- but for `dict`
members they produced different text in the same report:

    bulk:      architecture.tier_profiles: +{"name": "alpha", "weight": 2}
    per-model: architecture.tier_profiles: +{'name': 'beta', 'weight': 4} (1 -> 1)

JSON quoting in one, Python `repr` quoting in the other. Both paths now go
through the single shared `change_render._list_item_text` (JSON wins; repr
must not reach rendered output), so `synth/model-bulk-*` and
`synth/model-solo-struct` -- which carry the same *shape* of change to the
same field -- are spelled identically. That was a deliberate, approved output
change; it altered the goldens below and three goldens in
`test_render_characterization.py`. These constants exist so such a change is
reviewable rather than silent, and
`test_bulk_and_per_model_dict_member_spellings_match` names the invariant.

Do NOT update the golden constants to make a refactor's tests pass silently.
A failing test here means renderer output changed; the reviewer must look at
the diff and decide whether the new output is intentional before updating the
constant.

DELIBERATE UPDATE (Task 5 fix pass 1): `synth/model-struct-added` is a
one-sided structured list, so `_flatten_one_sided_structure` gives its leaves
INDEX brackets (`architecture.tier_profiles[0].name`) rather than the
condition brackets `_pricing_override_path` produces. The renderers now print
that bracketed segment as a qualifier, so `Name` / `Weight` became
`Name (#0)` / `Weight (#0)` in the text, markdown, HTML change-table and HTML
Change Summary goldens here. That is the only diff in this module, and no row
moved (`"name (#0)"` still sorts before `"weight (#0)"`). See
`test_change_render.py::test_index_qualifier_renders_as_an_ordinal` for why an
index reads `#0` while a condition renders literally.

DELIBERATELY NOT COVERED HERE: the full HTML document envelope (`<!DOCTYPE>`,
the `<style>` block, provider headers) is already pinned byte-for-byte by
`test_render_characterization.py`; duplicating it would add hundreds of lines
of noise and a second place to update. The HTML goldens below are the exact
changed-models region and the exact summary table, asserted by containment.
Also not covered: price/count/numeric/boolean classification (that module's
job), and the `squelched` detail mode.
"""

from __future__ import annotations

import json
import os
import time

from model_sentinel.models import FieldChange, ModelDelta, ProviderScanResult
from model_sentinel.reporting import (
    BULK_CHANGE_MIN_MODELS,
    make_report_detail_policy,
    render_scan_report,
)

# Pin the process timezone to UTC before any golden constant below is defined,
# for the same reason as test_render_characterization.py: render_scan_report()
# formats timestamps through to_local_human()/to_local_iso(), which convert to
# whatever the OS considers "local". Pinning here (which also overrides any
# ambient `TZ=...`) lets the goldens hardcode literal timestamp strings instead
# of recomputing them through the very helpers they are meant to pin.
os.environ["TZ"] = "UTC"
time.tzset()

GENERATED_AT = "2026-07-25T09:00:00+00:00"
COMMAND = "scan"

# Literal expected rendering of GENERATED_AT, valid because TZ is pinned to UTC
# above. Do NOT replace with a call to to_local_human() -- that would make the
# timestamp assertions tautological.
_GENERATED_AT_HUMAN = "2026-07-25 09:00:00"
HUMAN_TOKEN = "@@GENERATED_AT_HUMAN@@"


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

# The identical pair of field changes shared by all three bulk models.
# Reusing the same objects is a convenience, NOT the mechanism: consolidation
# keys models by the *value* of `_bulk_change_signature` (a tuple of strings
# and string tuples used as a dict key), so object identity is irrelevant.
# `FieldChange` is a frozen dataclass, so three distinct-but-equal instances
# produce equal signatures and consolidate identically.
BULK_PARAMS_CHANGE = FieldChange(
    "supported_parameters",
    ["temperature", "tools"],
    ["logit_bias", "temperature", "tools"],
)
# A list whose members are dicts, on a field that DEFAULT_REPORT_SHOW_FIELDS
# admits (`architecture.*`) and DEFAULT_REPORT_SQUELCH_FIELDS does not squelch.
# Two-sided list -> list, so reporting.py's structured-expansion pass leaves it
# intact and it reaches the real list-diff renderers.
BULK_STRUCTURED_CHANGE = FieldChange(
    "architecture.tier_profiles",
    [{"name": "alpha", "weight": 1}],
    [{"name": "alpha", "weight": 2}],
)


def _delta(model_id: str, display_name: str, field_changes: tuple[FieldChange, ...]) -> ModelDelta:
    return ModelDelta("changed", model_id, display_name, field_changes)


# Exactly BULK_CHANGE_MIN_MODELS models sharing one signature -> consolidated.
BULK_TRIO = (
    _delta("synth/model-bulk-a", "Synth Bulk A", (BULK_PARAMS_CHANGE, BULK_STRUCTURED_CHANGE)),
    _delta("synth/model-bulk-b", "Synth Bulk B", (BULK_PARAMS_CHANGE, BULK_STRUCTURED_CHANGE)),
    _delta("synth/model-bulk-c", "Synth Bulk C", (BULK_PARAMS_CHANGE, BULK_STRUCTURED_CHANGE)),
)

# One BELOW the threshold: two models sharing a different identical signature.
# They must keep individual cards, which is what pins the threshold itself.
BULK_PAIR = (
    _delta("synth/model-pair-x", "Synth Pair X", (FieldChange("supported_parameters", ["tools"], ["tools", "seed"]),)),
    _delta("synth/model-pair-y", "Synth Pair Y", (FieldChange("supported_parameters", ["tools"], ["tools", "seed"]),)),
)

OTHER_MODELS = (
    # Same field and same dict-member shape as BULK_STRUCTURED_CHANGE, but a
    # unique signature so it stays a per-model card. This is the direct
    # side-by-side comparison for the stringification split described in the
    # module docstring.
    _delta(
        "synth/model-solo-struct",
        "Synth Solo Struct",
        (FieldChange("architecture.tier_profiles", [{"name": "beta", "weight": 3}], [{"name": "beta", "weight": 4}]),),
    ),
    # One-sided list changes. Members are plain strings, so reporting.py's
    # `_is_structured_list` is False and no flattening happens; classify_change
    # sends both through the `scalar` branch, where `_scalar_display`
    # JSON-encodes the list side.
    _delta("synth/model-list-added", "Synth List Added", (FieldChange("supported_parameters", None, ["tools", "logit_bias"]),)),
    _delta("synth/model-list-removed", "Synth List Removed", (FieldChange("supported_parameters", ["tools", "logit_bias"], None),)),
    # One-sided list whose members ARE dicts: `_is_structured_list` is True, so
    # reporting.py flattens it into indexed leaf changes and the list renderers
    # are never reached at all. Pinned so a future change to the flattening
    # pass is visible.
    _delta("synth/model-struct-added", "Synth Struct Added", (FieldChange("architecture.tier_profiles", None, [{"name": "gamma", "weight": 5}]),)),
)


# A list change where MULTIPLICITY changed but the member SET did not:
# ["tools", "tools", "seed"] -> ["tools", "seed", "seed"]. Both lists differ
# (so this is a real change, not a noop), yet added and removed both come out
# empty -- the only way to reach the `membership changed` fallback in
# `_render_bulk_list_diff_text` and `_render_html_bulk_list_diff`, which is
# bulk-only and therefore needs BULK_CHANGE_MIN_MODELS models to fire.
#
# Each model gets its own equal-but-distinct FieldChange instance on purpose:
# that also demonstrates that consolidation is driven by signature *value*,
# not by sharing one object (see the note on BULK_PARAMS_CHANGE above).
def _multiplicity_change() -> FieldChange:
    return FieldChange("supported_parameters", ["tools", "tools", "seed"], ["tools", "seed", "seed"])


MULTIPLICITY_TRIO = tuple(
    _delta(f"synth/model-multi-{suffix}", f"Synth Multi {suffix.upper()}", (_multiplicity_change(),))
    for suffix in ("a", "b", "c")
)


def scan_result(changed: tuple[ModelDelta, ...]) -> list[ProviderScanResult]:
    return [
        ProviderScanResult(
            provider_id="synthprov",
            provider_label="Synth Provider",
            status="success",
            current_count=len(changed),
            saved=False,
            baseline=None,
            baseline_message=None,
            scrape_id=None,
            added=(),
            removed=(),
            changed=tuple(changed),
            error_message=None,
            price_multiplier=1000000,
            price_divisor=1,
        )
    ]


def bulk_characterization_scan_result() -> list[ProviderScanResult]:
    """One provider, nine models, covering all three uncovered paths."""
    return scan_result(BULK_TRIO + BULK_PAIR + OTHER_MODELS)


def render(format_name: str, *, mode: str = "default", changed: tuple[ModelDelta, ...] | None = None) -> str:
    results = scan_result(changed) if changed is not None else bulk_characterization_scan_result()
    return render_scan_report(
        generated_at=GENERATED_AT,
        command=COMMAND,
        format_name=format_name,
        provider_results=results,
        detail_policy=make_report_detail_policy(mode=mode),
    )


# ---------------------------------------------------------------------------
# Goldens
# ---------------------------------------------------------------------------

_EXPECTED_TEXT_TEMPLATE = """Model Sentinel report
Generated at: @@GENERATED_AT_HUMAN@@
Command: scan

Synth Provider (synthprov)
  status: success
  current_count: 9
  added: 0
  removed: 0
  changed: 9
    * Bulk change — 3 models
      models: synth/model-bulk-a, synth/model-bulk-b, synth/model-bulk-c
      [Parameters]
        Supported parameters: +logit_bias
      [Other]
        Tier profiles: +{"name": "alpha", "weight": 2}; -{"name": "alpha", "weight": 1}
    * synth/model-pair-x (Synth Pair X)
      Supported parameters: +seed (1 → 2)
    * synth/model-pair-y (Synth Pair Y)
      Supported parameters: +seed (1 → 2)
    * synth/model-solo-struct (Synth Solo Struct)
      Tier profiles: +{"name": "beta", "weight": 4}; -{"name": "beta", "weight": 3} (1 → 1)
    * synth/model-list-added (Synth List Added)
      Supported parameters: null → ["tools", "logit_bias"]
    * synth/model-list-removed (Synth List Removed)
      Supported parameters: ["tools", "logit_bias"] → null
    * synth/model-struct-added (Synth Struct Added)
      [Other]
        Name (#0): null → gamma
        Weight (#0): null → 5

Summary
------------------------------------------------------------
  Synth Provider: 9 changed"""

EXPECTED_TEXT = _EXPECTED_TEXT_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


# `all` detail mode never consolidates (reporting.py returns early from
# `_plan_provider_changes` when mode != "default"), so every bulk member gets
# its own card AND the dict members render in per-model `str()` form -- the
# same data as the bulk card above, spelled differently.
_EXPECTED_TEXT_DETAIL_ALL_TEMPLATE = """Model Sentinel report
Generated at: @@GENERATED_AT_HUMAN@@
Command: scan

Synth Provider (synthprov)
  status: success
  current_count: 9
  added: 0
  removed: 0
  changed: 9
    * synth/model-bulk-a (Synth Bulk A)
      [Parameters]
        Supported parameters: +logit_bias (2 → 3)
      [Other]
        Tier profiles: +{"name": "alpha", "weight": 2}; -{"name": "alpha", "weight": 1} (1 → 1)
    * synth/model-bulk-b (Synth Bulk B)
      [Parameters]
        Supported parameters: +logit_bias (2 → 3)
      [Other]
        Tier profiles: +{"name": "alpha", "weight": 2}; -{"name": "alpha", "weight": 1} (1 → 1)
    * synth/model-bulk-c (Synth Bulk C)
      [Parameters]
        Supported parameters: +logit_bias (2 → 3)
      [Other]
        Tier profiles: +{"name": "alpha", "weight": 2}; -{"name": "alpha", "weight": 1} (1 → 1)
    * synth/model-pair-x (Synth Pair X)
      Supported parameters: +seed (1 → 2)
    * synth/model-pair-y (Synth Pair Y)
      Supported parameters: +seed (1 → 2)
    * synth/model-solo-struct (Synth Solo Struct)
      Tier profiles: +{"name": "beta", "weight": 4}; -{"name": "beta", "weight": 3} (1 → 1)
    * synth/model-list-added (Synth List Added)
      Supported parameters: null → ["tools", "logit_bias"]
    * synth/model-list-removed (Synth List Removed)
      Supported parameters: ["tools", "logit_bias"] → null
    * synth/model-struct-added (Synth Struct Added)
      [Other]
        Name (#0): null → gamma
        Weight (#0): null → 5

Summary
------------------------------------------------------------
  Synth Provider: 9 changed"""

EXPECTED_TEXT_DETAIL_ALL = _EXPECTED_TEXT_DETAIL_ALL_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


_EXPECTED_MARKDOWN_TEMPLATE = """# Model Sentinel Report

- Generated at: @@GENERATED_AT_HUMAN@@
- Command: scan

## Synth Provider (`synthprov`)

- Status: `success`
- Current models: `9`

### Added (0)

- None

### Removed (0)

- None

### Changed (9)

- **Bulk change — 3 models**
  - Models: `synth/model-bulk-a, synth/model-bulk-b, synth/model-bulk-c`
  - **Parameters**
    - `Supported parameters: +logit_bias`
  - **Other**
    - `Tier profiles: +{"name": "alpha", "weight": 2}; -{"name": "alpha", "weight": 1}`
- `synth/model-pair-x` - Synth Pair X
  - `Supported parameters: +seed (1 → 2)`
- `synth/model-pair-y` - Synth Pair Y
  - `Supported parameters: +seed (1 → 2)`
- `synth/model-solo-struct` - Synth Solo Struct
  - `Tier profiles: +{"name": "beta", "weight": 4}; -{"name": "beta", "weight": 3} (1 → 1)`
- `synth/model-list-added` - Synth List Added
  - `Supported parameters: null → ["tools", "logit_bias"]`
- `synth/model-list-removed` - Synth List Removed
  - `Supported parameters: ["tools", "logit_bias"] → null`
- `synth/model-struct-added` - Synth Struct Added
  - `Name (#0): null → gamma`
  - `Weight (#0): null → 5`"""

EXPECTED_MARKDOWN = _EXPECTED_MARKDOWN_TEMPLATE.replace(HUMAN_TOKEN, _GENERATED_AT_HUMAN)


# Exact changed-models region of the HTML document: from the bulk card through
# the last per-model card, ending where the summary section begins.
EXPECTED_HTML_CHANGE_BODY = """<div class="model-card bulk-change-card">
<div class="model-card-header"><code>Bulk change — 3 models</code></div>
<details class="bulk-models"><summary>Models: synth/model-bulk-a, synth/model-bulk-b, synth/model-bulk-c</summary><div class="bulk-model-list"><code>synth/model-bulk-a</code><code>synth/model-bulk-b</code><code>synth/model-bulk-c</code></div></details>
<div class="change-category"><div class="category-label">Parameters</div>
<div class="list-diff"><span class="field-name">Supported parameters</span>
<div class="list-added">
&nbsp;&nbsp;+ logit_bias
</div>
</div>
</div>
<div class="change-category"><div class="category-label">Other</div>
<div class="list-diff"><span class="field-name">Tier profiles</span>
<div class="list-added">
&nbsp;&nbsp;+ {&quot;name&quot;: &quot;alpha&quot;, &quot;weight&quot;: 2}
</div>
<div class="list-removed">
&nbsp;&nbsp;− {&quot;name&quot;: &quot;alpha&quot;, &quot;weight&quot;: 1}
</div>
</div>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-pair-x</code><span class="display-name">Synth Pair X</span></div>
<div class="change-category"><div class="category-label">Parameters</div>
<div class="list-diff">
<span class="field-name">Supported parameters</span> 
<span class="list-count">(1 → 2)</span>
<div class="list-added">
&nbsp;&nbsp;+ seed
</div>
</div>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-pair-y</code><span class="display-name">Synth Pair Y</span></div>
<div class="change-category"><div class="category-label">Parameters</div>
<div class="list-diff">
<span class="field-name">Supported parameters</span> 
<span class="list-count">(1 → 2)</span>
<div class="list-added">
&nbsp;&nbsp;+ seed
</div>
</div>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-solo-struct</code><span class="display-name">Synth Solo Struct</span></div>
<div class="change-category"><div class="category-label">Other</div>
<div class="list-diff">
<span class="field-name">Tier profiles</span> 
<span class="list-count">(1 → 1)</span>
<div class="list-added">
&nbsp;&nbsp;+ {&quot;name&quot;: &quot;beta&quot;, &quot;weight&quot;: 4}
</div>
<div class="list-removed">
&nbsp;&nbsp;− {&quot;name&quot;: &quot;beta&quot;, &quot;weight&quot;: 3}
</div>
</div>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-list-added</code><span class="display-name">Synth List Added</span></div>
<div class="change-category"><div class="category-label">Parameters</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Supported parameters</td><td class="old-val">null</td><td class="new-val">[&quot;tools&quot;, &quot;logit_bias&quot;]</td><td class="change-delta delta-neutral">—</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-list-removed</code><span class="display-name">Synth List Removed</span></div>
<div class="change-category"><div class="category-label">Parameters</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Supported parameters</td><td class="old-val">[&quot;tools&quot;, &quot;logit_bias&quot;]</td><td class="new-val">null</td><td class="change-delta delta-neutral">—</td></tr>
</tbody></table>
</div>
</div>
<div class="model-card">
<div class="model-card-header"><code>synth/model-struct-added</code><span class="display-name">Synth Struct Added</span></div>
<div class="change-category"><div class="category-label">Other</div>
<table class="change-table"><thead><tr><th>Field</th><th>Old</th><th>New</th><th>Change</th></tr></thead><tbody>
<tr><td class="field-name">Name (#0)</td><td class="old-val">null</td><td class="new-val">gamma</td><td class="change-delta delta-neutral">—</td></tr>
<tr><td class="field-name">Weight (#0)</td><td class="old-val">null</td><td class="new-val">5</td><td class="change-delta delta-neutral">—</td></tr>
</tbody></table>
</div>
</div></section>
"""


# Exact summary table. Bulk entries collapse the model column into a
# <details> disclosure listing the grouped model ids.
EXPECTED_HTML_SUMMARY = """<section class="summary-section"><h2>Change Summary</h2><table class="summary-table"><thead><tr><th>Category</th><th>Provider</th><th>Model</th><th>Field</th><th>Change</th></tr></thead><tbody><tr><td>Parameters</td><td>Synth Provider</td><td><details class="summary-models"><summary>3 models</summary><div class="summary-model-list"><code>synth/model-bulk-a</code><code>synth/model-bulk-b</code><code>synth/model-bulk-c</code></div></details></td><td>Supported parameters</td><td>+logit_bias</td></tr>
<tr><td>Parameters</td><td>Synth Provider</td><td><code>synth/model-list-added</code></td><td>Supported parameters</td><td>null → [&quot;tools&quot;, &quot;logit_bias&quot;]</td></tr>
<tr><td>Parameters</td><td>Synth Provider</td><td><code>synth/model-list-removed</code></td><td>Supported parameters</td><td>[&quot;tools&quot;, &quot;logit_bias&quot;] → null</td></tr>
<tr><td>Parameters</td><td>Synth Provider</td><td><code>synth/model-pair-x</code></td><td>Supported parameters</td><td>+seed (1 → 2)</td></tr>
<tr><td>Parameters</td><td>Synth Provider</td><td><code>synth/model-pair-y</code></td><td>Supported parameters</td><td>+seed (1 → 2)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><details class="summary-models"><summary>3 models</summary><div class="summary-model-list"><code>synth/model-bulk-a</code><code>synth/model-bulk-b</code><code>synth/model-bulk-c</code></div></details></td><td>Tier profiles</td><td>+{&quot;name&quot;: &quot;alpha&quot;, &quot;weight&quot;: 2}; -{&quot;name&quot;: &quot;alpha&quot;, &quot;weight&quot;: 1}</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-solo-struct</code></td><td>Tier profiles</td><td>+{&quot;name&quot;: &quot;beta&quot;, &quot;weight&quot;: 4}; -{&quot;name&quot;: &quot;beta&quot;, &quot;weight&quot;: 3} (1 → 1)</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-struct-added</code></td><td>Name (#0)</td><td>null → gamma</td></tr>
<tr><td>Other</td><td>Synth Provider</td><td><code>synth/model-struct-added</code></td><td>Weight (#0)</td><td>null → 5</td></tr></tbody></table></section>"""


# ---------------------------------------------------------------------------
# Golden assertions
# ---------------------------------------------------------------------------


def test_bulk_characterization_text():
    assert render("text") == EXPECTED_TEXT


def test_bulk_characterization_text_detail_all():
    assert render("text", mode="all") == EXPECTED_TEXT_DETAIL_ALL


def test_bulk_characterization_markdown():
    assert render("markdown") == EXPECTED_MARKDOWN


def test_bulk_characterization_html_change_body():
    assert EXPECTED_HTML_CHANGE_BODY in render("html")


def test_bulk_characterization_html_summary():
    assert EXPECTED_HTML_SUMMARY in render("html")


# ---------------------------------------------------------------------------
# Targeted behavioral guards around the goldens
# ---------------------------------------------------------------------------


def test_bulk_grouping_requires_at_least_three_models():
    """Two models with an identical signature must NOT consolidate."""
    assert BULK_CHANGE_MIN_MODELS == 3

    two = render("text", changed=BULK_TRIO[:2])
    assert "Bulk change" not in two
    assert "* synth/model-bulk-a (Synth Bulk A)" in two
    assert "* synth/model-bulk-b (Synth Bulk B)" in two

    three = render("text", changed=BULK_TRIO)
    assert "* Bulk change — 3 models" in three
    assert "* synth/model-bulk-a (Synth Bulk A)" not in three


def test_all_detail_mode_never_consolidates():
    for format_name in ("text", "markdown", "html"):
        assert "Bulk change" not in render(format_name, mode="all"), format_name
        assert "Bulk change" in render(format_name), format_name


def test_bulk_group_with_unchanged_member_set_renders_membership_changed():
    """Cover the `membership changed` fallback in both bulk renderers.

    Reachable only when a bulk group's added and removed sets are BOTH empty
    while the lists themselves still differ -- i.e. multiplicity (or order)
    moved but the set did not. Deliberately rendered with its own trio rather
    than folded into `bulk_characterization_scan_result()`, so the goldens
    above keep pinning exactly the cases they were written for.

    Also evidence for the identity-vs-value note on the fixture: the three
    models carry three distinct `FieldChange` instances and still consolidate.
    """
    assert len({id(delta.field_changes[0]) for delta in MULTIPLICITY_TRIO}) == 3

    text = render("text", changed=MULTIPLICITY_TRIO)
    assert "* Bulk change — 3 models" in text
    assert "Supported parameters: membership changed" in text

    markdown = render("markdown", changed=MULTIPLICITY_TRIO)
    assert "`Supported parameters: membership changed`" in markdown

    html = render("html", changed=MULTIPLICITY_TRIO)
    assert '<div class="list-count">membership changed</div>' in html
    # The bulk card carries no +/- rows at all for this change.
    assert '<div class="list-added">' not in html
    assert '<div class="list-removed">' not in html


def test_json_output_is_unaffected_by_bulk_grouping():
    """JSON reports bypass every presentation helper touched here.

    No consolidation, no member stringification, no structured flattening --
    each model keeps its own entry with raw `old_value`/`new_value` payloads.
    """
    payload = json.loads(
        render_scan_report(
            generated_at=GENERATED_AT,
            command=COMMAND,
            format_name="json",
            provider_results=bulk_characterization_scan_result(),
        )
    )
    changed = payload["providers"][0]["changed"]
    assert [entry["provider_model_id"] for entry in changed] == [
        "synth/model-bulk-a",
        "synth/model-bulk-b",
        "synth/model-bulk-c",
        "synth/model-pair-x",
        "synth/model-pair-y",
        "synth/model-solo-struct",
        "synth/model-list-added",
        "synth/model-list-removed",
        "synth/model-struct-added",
    ]
    # Raw structured payloads survive as real JSON objects, un-stringified and
    # un-flattened.
    assert changed[0]["field_changes"] == [
        {
            "field_name": "supported_parameters",
            "old_value": ["temperature", "tools"],
            "new_value": ["logit_bias", "temperature", "tools"],
        },
        {
            "field_name": "architecture.tier_profiles",
            "old_value": [{"name": "alpha", "weight": 1}],
            "new_value": [{"name": "alpha", "weight": 2}],
        },
    ]
    assert changed[8]["field_changes"] == [
        {
            "field_name": "architecture.tier_profiles",
            "old_value": None,
            "new_value": [{"name": "gamma", "weight": 5}],
        }
    ]


def test_bulk_and_per_model_dict_member_spellings_match():
    """Pin the bulk/per-model stringification UNIFICATION as an explicit assertion.

    This test previously pinned the opposite -- a real shipped inconsistency
    where the bulk card spelled a `dict` member as JSON (`_list_item_text`) and
    the per-model card spelled the same shape as a Python repr
    (`classify_change`'s `str(x)`), in the same report. Both now go through
    `change_render._list_item_text`, so the second assertion flipped from repr
    to JSON. The goldens above encode this too, but only implicitly, buried in
    large constants; this test names the invariant so a regression fails with
    a statement of what broke rather than a wall of diff.

    It is the regression guard that the two conventions stay unified: any
    future change that reintroduces `str(x)` on either path fails here. Python
    repr quoting must never reach rendered output.
    """
    text = render("text")
    # Bulk card (grouped trio) -- JSON quoting.
    assert 'Tier profiles: +{"name": "alpha", "weight": 2}; -{"name": "alpha", "weight": 1}' in text
    # Per-model card, same field and same dict-member shape -- JSON quoting too.
    assert (
        'Tier profiles: +{"name": "beta", "weight": 4}; '
        '-{"name": "beta", "weight": 3} (1 → 1)'
    ) in text
    # No Python repr spelling anywhere in the rendered report.
    assert "{'" not in text
