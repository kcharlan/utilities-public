# Packet 18 Validation: Analytics: Heatmap

## Result: VALIDATED

## Test Results

- Packet tests: **15/15 pass** (10 original + 5 added during validation)
- Full suite: **371/371 pass** (no regressions)

## Defect Found and Repaired

### Missing `data-heatmap-root` attribute (tooltip positioning bug)

The `Heatmap` component references `e.currentTarget.closest('[data-heatmap-root]')` on line 4300 to compute tooltip position relative to the container. However, the outer container `<div>` at line 4241 did not have the `data-heatmap-root` attribute. This caused `closest()` to return `null`, falling back to the cell's own rect, making `x=0, y=0`. Since the tooltip uses `position: fixed`, it would always render at viewport coordinates `(16, 0)` — top-left corner instead of near the hovered cell.

**Fix:** Added `data-heatmap-root` attribute to the outer container div.
**Regression guard:** `test_heatmap_root_attr` asserts the attribute exists in the HTML.

## Tests Added During Validation

| Test | What It Covers |
|---|---|
| `test_heatmap_root_attr` | `data-heatmap-root` attribute exists (tooltip positioning fix) |
| `test_heatmap_grid_dimensions` | Grid uses `repeat(52,...)` × `repeat(7,...)` (AC 9) |
| `test_heatmap_hover_outline` | Hovered cell uses `2px solid var(--accent-blue)` (AC 14) |
| `test_heatmap_day_labels` | Mon, Wed, Fri labels present (AC 11) |
| `test_heatmap_month_labels` | Month label array (Jan–Dec) present (AC 12) |

## Acceptance Criteria Verification

| # | Criterion | Status |
|---|---|---|
| 1 | `GET /api/analytics/heatmap` returns 200 with `{data, max_count}` | PASS |
| 2 | `data` entries have `date` (YYYY-MM-DD) and `count` (int) | PASS |
| 3 | `data` sorted ascending by date | PASS |
| 4 | `max_count` = max count, or 0 if empty | PASS |
| 5 | `days` param filters window (default 365) | PASS |
| 6 | Commits aggregated across repos (SUM) | PASS |
| 7 | Empty DB → `{data: [], max_count: 0}` | PASS |
| 8 | `function Heatmap` exists in HTML_TEMPLATE | PASS |
| 9 | Grid: 52 columns × 7 rows | PASS |
| 10 | 5-level color scale matches spec | PASS |
| 11 | Day labels (Mon, Wed, Fri) on left | PASS |
| 12 | Month labels along top | PASS |
| 13 | Tooltip shows date + commit count on hover | PASS (fixed positioning bug) |
| 14 | Cell hover outline: `2px solid var(--accent-blue)` | PASS |
| 15 | No regressions, all tests pass | PASS (371/371) |

## Scope Check

- No files modified outside allowed list (`git_dashboard.py`, `tests/test_analytics_heatmap.py`)
- Component is defined but NOT rendered — no `<Heatmap` invocations (correct; wiring is packet 21)
- No scope creep: no time allocation, dep overlap, or analytics tab wiring added
