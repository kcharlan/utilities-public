"""Shared HTML probes for the report characterization and guard tests.

A test-support module rather than a fixture: the callers want a plain
function over a rendered string, not injected state. Imported as
`tests.html_probe` because `pytest.ini` sets `--import-mode=importlib`, so
pytest puts no directory on `sys.path`; `conftest.py` puts the project root
there, which makes `tests` an importable namespace package.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Shared HTML probe: the cells that can carry the absent side of a change
#
# Lives here rather than in one test module because BOTH HTML documents need
# the same question asked of them -- the scan report (test_reporting.py) and
# the `changes` report (test_render_changes_characterization.py) -- and two
# copies of this scoping would be two places for it to drift.
# ---------------------------------------------------------------------------

# The scan card's `<td class="old-val num" title="...">` and the `changes`
# table's `<td class="old-val">` alike; the class list and the optional
# attributes are both matched loosely so a later cell class cannot silently
# drop a cell out of the probe.
_VALUE_CELL_RE = re.compile(r'<td class="(?:old|new)-val\b[^"]*"[^>]*>(.*?)</td>')
# The Change Summary is a `<section>` in the `changes` report and a collapsed
# `<details>` in the scan report (E6). Both tags are matched, and the closing
# tag is tied to whichever opened, so a probe pointed at the scan report cannot
# silently return an empty list and let the loop over it pass vacuously.
_SUMMARY_SECTION_RE = re.compile(
    r'<(section|details) class="summary-section">(.*?)</\1>', re.S
)
# `<tr[^>]*>`, not `<tr>`, for the same reason the value-cell pattern above
# matches its class list loosely: a row that gains an attribute must not fall
# silently out of the probe. The scan report's summary rows now carry a
# `row-alt` zebra class on every other DATA row, and the tight pattern dropped
# exactly those -- halving what this function returned while every caller still
# read as though it covered the table. Group heading rows now match too, and
# are discarded by the `colspan` guard below, which is what that guard is for.
_SUMMARY_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_SUMMARY_CELL_RE = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)


def absent_side_cells(html: str) -> list[str]:
    """Every cell of an HTML report that can carry an absent side of a change.

    Fix pass 2, finding 4. The assertion this backs used to be `"null" not in
    html_report` over the WHOLE document, which is correct for its fixture and
    wrong as a rule: a model id, a provider label or a genuine string value of
    `"null"` would fail it, and the message would point at the absent-side
    spelling rather than at the value that actually contains the token.

    Two kinds of cell qualify, and only these two:

    * a value cell -- `old-val` / `new-val` -- in either the scan report's model
      card or the `changes` report's four-column change table;
    * the CHANGE cell of a Change Summary row, which is its last `<td>`. The
      earlier cells of that row hold the category, the provider label and the
      model id, none of which is a side of anything.

    A last cell carrying `colspan` is skipped. That is the `changes` report's
    model-arrived / model-departed row, where the Field and Change columns are
    merged into one cell holding a DISPLAY NAME -- provider text, with no old
    and no new, and exactly the kind of value that made the whole-document
    assertion the wrong shape.

    Returns raw inner HTML, not text: a caller asserting on the escaped form of
    a value wants to see it exactly as the document spells it.
    """
    return [match.group(1) for match in _VALUE_CELL_RE.finditer(html)] + summary_change_cells(html)


def summary_change_cells(html: str) -> list[str]:
    """The CHANGE cell -- the last `<td>` -- of every Change Summary data row.

    Split out of `absent_side_cells` rather than copied beside it. A caller
    asking "does any summary row lead with a raw provider value" must see the
    summary rows ALONE: the `changes` report's four-column table deliberately
    keeps `raw (normalized / 1M)` in its value cells, so a probe that folded
    those in would report a violation on every one of them.

    A last cell carrying `colspan` is skipped -- that is the model-arrived /
    model-departed row, whose merged cell holds a display name rather than a
    side of anything.
    """
    cells: list[str] = []
    for section in _SUMMARY_SECTION_RE.finditer(html):
        for row in _SUMMARY_ROW_RE.finditer(section.group(2)):
            row_cells = _SUMMARY_CELL_RE.findall(row.group(1))
            if row_cells and "colspan" not in row_cells[-1][0]:
                cells.append(row_cells[-1][1])
    return cells

