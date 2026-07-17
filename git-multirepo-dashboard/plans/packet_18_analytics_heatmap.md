# Packet 18: Analytics: Heatmap

## Why This Packet Exists

The daily_stats table (populated by packet 06) contains per-repo daily commit counts but there is no way to visualize cross-repo activity patterns over time. This packet adds a fleet-wide activity heatmap API endpoint and a GitHub-style contribution grid component.

## Scope

- **GET /api/analytics/heatmap?days=365** endpoint — aggregates `daily_stats.commits` across all repos by date, returns date/count pairs and the max count for color scaling.
- **Heatmap** React component — standalone, self-contained component that:
  - Fetches `/api/analytics/heatmap?days=365` on mount.
  - Renders a 52-column × 7-row grid of 12px cells (2px gap).
  - Applies a 5-level blue color scale based on percentile thresholds.
  - Shows day labels (Mon, Wed, Fri) on the left.
  - Shows month labels along the top.
  - Shows a tooltip on cell hover with date and commit count.

**Note:** This packet delivers the API and the component definition. The component is NOT wired into the Analytics tab yet — that happens in packet 21 (Analytics Tab Wiring). The component is defined in HTML_TEMPLATE and can be tested via the API and by verifying its presence in the template.

## Non-Goals

- Analytics tab wiring / layout (packet 21).
- Time range selector for the heatmap (packet 21 adds shared selectors).
- Time allocation chart (packet 19).
- Dependency overlap table (packet 20).
- Per-repo heatmaps — this is fleet-wide only.
- Insertions/deletions in heatmap — commits only.

## Relevant Design Doc Sections

- §4.0 — `GET /api/analytics/heatmap?days=365` response shape (lines 590–602)
- §5.6 — Analytics Tab: Activity Heatmap (lines 1028–1049): grid dimensions, color scale, labels, tooltip, hover
- §8.0 — Phase 4 implementation order (lines 1263–1269)

## Allowed Files

- `git_dashboard.py`
- `tests/test_analytics_heatmap.py` (new)

## Tests to Write First

1. **test_heatmap_empty_db** — No daily_stats rows. `GET /api/analytics/heatmap` → 200, `{"data": [], "max_count": 0}`.
2. **test_heatmap_single_repo** — Insert daily_stats for one repo (5 dates with varying commit counts). Verify response `data` has 5 entries, `max_count` equals the highest commit count.
3. **test_heatmap_aggregates_across_repos** — Insert daily_stats for 2 repos on the same date (repo A: 3 commits, repo B: 5 commits on 2026-03-01). Verify the date entry has `count: 8`. Verify `max_count` reflects the aggregated max.
4. **test_heatmap_days_filter** — Insert data spanning 400 days. `GET /api/analytics/heatmap?days=30` → only entries within the last 30 days. `GET /api/analytics/heatmap?days=365` → entries within the last 365 days.
5. **test_heatmap_default_days** — `GET /api/analytics/heatmap` (no `days` param) → defaults to 365 days.
6. **test_heatmap_response_shape** — Each entry in `data` has exactly `date` (string, YYYY-MM-DD) and `count` (integer). Top-level has `data` (array) and `max_count` (integer).
7. **test_heatmap_sorted_by_date** — Insert dates out of order. Verify response `data` is sorted ascending by date.
8. **test_heatmap_component_exists** — `GET /` → HTML contains `function Heatmap`.
9. **test_heatmap_color_scale** — `GET /` → HTML contains the 5 color scale values from the spec: `var(--bg-secondary)` for 0 commits and the 4 rgba blue values.
10. **test_heatmap_tooltip_pattern** — `GET /` → HTML contains tooltip rendering logic (date formatting + "commits" text pattern).

## Implementation Notes

### API: GET /api/analytics/heatmap

```python
@app.get("/api/analytics/heatmap")
async def get_analytics_heatmap(days: int = 365):
```

Query:
```sql
SELECT date, SUM(commits) as count
FROM daily_stats
WHERE date >= ?
GROUP BY date
ORDER BY date ASC
```

The `date >= ?` parameter is computed as `(today - days)` in ISO format (`YYYY-MM-DD`). Use `datetime.date.today()` for the cutoff.

Response:
```json
{
  "data": [
    {"date": "2026-03-09", "count": 8},
    {"date": "2026-03-08", "count": 3}
  ],
  "max_count": 15
}
```

`max_count` is `max(entry["count"] for entry in data)` or `0` if data is empty.

### Heatmap React Component

This is a custom CSS grid component — Recharts does NOT have a heatmap type.

**Grid structure:**
- 52 columns (weeks) × 7 rows (days, Sun=0 through Sat=6).
- The grid is anchored to today's date. The rightmost column is the current week. Work backwards 52 weeks.
- Each cell maps to a specific date. Fill from the fetched data; missing dates = 0 commits.

**Color scale function:**
```javascript
function heatmapColor(count, maxCount) {
  if (count === 0) return 'var(--bg-secondary)';
  const pct = count / maxCount;
  if (pct <= 0.25) return 'rgba(76,141,255,0.2)';
  if (pct <= 0.50) return 'rgba(76,141,255,0.4)';
  if (pct <= 0.75) return 'rgba(76,141,255,0.65)';
  return 'rgba(76,141,255,0.9)';
}
```

The spec says "percentile" but since we have the full dataset client-side, simple ratio to max is equivalent and much simpler. The spec's phrasing ("relative to max") confirms this interpretation.

**Layout approach (inline styles, no new CSS classes needed beyond optional):**
- Outer container: `display: flex` (day labels column + grid + overflow handling).
- Day labels column: fixed 30px width, 7 rows, only Mon/Wed/Fri visible.
- Grid: `display: grid`, `gridTemplateColumns: repeat(52, 12px)`, `gridTemplateRows: repeat(7, 12px)`, `gap: 2px`.
- Month labels row above grid: positioned by calculating which column each month starts on.

**Tooltip:**
- Use React `useState` for hover state: `{date, count, x, y}` or null.
- On mouseEnter of a cell, set tooltip state. On mouseLeave, clear.
- Tooltip div: absolute positioned, `var(--bg-card)` background, `var(--border-default)` border, `var(--radius-sm)`, padding `8px 12px`.
- Text: "March 9, 2026: 8 commits" — use `toLocaleDateString` for formatting.
- The spec says "across N projects" but that would require per-repo data in the heatmap. Since our API only returns aggregated counts, use just "N commits" (the "across M projects" detail can be added in a future enhancement if desired). Keep it simple.

**Cell hover:**
- `outline: 2px solid var(--accent-blue)`, `outlineOffset: -1px` on the hovered cell.

### Component Signature

```javascript
function Heatmap({ data, maxCount, loading }) { ... }
```

The component accepts pre-fetched data as props (so packet 21 can manage the fetch lifecycle) OR fetches internally. For self-contained operation, include an internal fetch with `useEffect`. Packet 21 can refactor the data flow if needed.

### Date Arithmetic

Build a `Map<dateString, count>` from the API response for O(1) lookups. Iterate 52×7 = 364 cells starting from `today - 363 days` (aligned to start of week). Use `new Date()` arithmetic.

## Acceptance Criteria

1. `GET /api/analytics/heatmap` returns 200 with `{data: [...], max_count: N}`.
2. `data` entries have `date` (YYYY-MM-DD string) and `count` (integer).
3. `data` is sorted ascending by date.
4. `max_count` equals the maximum `count` value, or 0 if data is empty.
5. `days` query parameter filters to the specified window (default 365).
6. Commits are aggregated across all repos (same date, different repos → summed).
7. Empty database returns `{data: [], max_count: 0}`.
8. `Heatmap` function component exists in HTML_TEMPLATE.
9. Component renders a grid with 52 columns and 7 rows.
10. Color scale uses 5 levels: `var(--bg-secondary)` for 0, then 4 blue rgba levels matching spec.
11. Day labels (Mon, Wed, Fri) appear on the left side.
12. Month labels appear along the top.
13. Tooltip shows date and commit count on cell hover.
14. Cell hover shows `outline: 2px solid var(--accent-blue)`.
15. All existing tests pass (no regressions). Packet tests pass.

## Validation Focus Areas

- Date arithmetic correctness: grid cells map to the right dates, week alignment is correct.
- Color scale thresholds match the spec exactly (0.25/0.50/0.75 breakpoints).
- The API aggregation is correct (SUM across repos, not just one repo).
- Empty state handling: no crashes when data is empty, max_count=0 doesn't cause division by zero.
- Month label positioning: labels appear above the correct grid column.
- The component is defined but NOT yet rendered in the analytics tab (that's packet 21). Verify it doesn't accidentally appear.
