# Packet 19: Analytics: Time Allocation

## Why This Packet Exists

The daily_stats table contains per-repo daily commit counts but there is no way to see how development effort is distributed across repos over time. This packet adds a fleet-wide time allocation API endpoint and a Recharts stacked area chart component showing per-repo commit activity.

## Scope

- **GET /api/analytics/allocation?days=90** endpoint — queries `daily_stats` joined with `repositories` to return per-repo commit time series, filtered by a `days` window.
- **TimeAllocation** React component — standalone, self-contained component that:
  - Fetches `/api/analytics/allocation?days=90` on mount (reacts to `days` prop changes).
  - Renders a Recharts `<AreaChart>` with `stackOffset="none"`.
  - One stacked `<Area>` series per repo, colored from a 10-color palette.
  - Groups repos beyond 10 into an "Other" aggregate series.
  - Weekly aggregation when `days >= 90`, daily otherwise.
  - Legend below chart with clickable repo names to toggle series visibility.
  - Reuses the existing `TimeRangeSelector` component for range selection.

**Note:** This packet delivers the API and the component definition. The component is NOT wired into the Analytics tab yet — that happens in packet 21 (Analytics Tab Wiring).

## Non-Goals

- Analytics tab wiring / layout (packet 21).
- Heatmap (packet 18 — already done).
- Dependency overlap table (packet 20).
- Insertions/deletions breakdown — commits only.
- Per-branch or per-author allocation.
- Custom date range picker (only preset buttons via TimeRangeSelector).

## Relevant Design Doc Sections

- §4.0 — `GET /api/analytics/allocation?days=90` response shape (lines 604–620)
- §5.6 — Analytics Tab: Time Allocation (Stacked Area Chart) (lines 1050–1063): chart type, axes, color palette, legend, time range selector
- §8.0 — Phase 4 implementation order

## Allowed Files

- `git_dashboard.py`
- `tests/test_analytics_time_allocation.py` (new)

## Tests to Write First

1. **test_allocation_empty_db** — No daily_stats rows. `GET /api/analytics/allocation` → 200, `{"series": []}`.
2. **test_allocation_single_repo** — Insert daily_stats for one repo (3 dates). Verify response has 1 series entry with `repo_id`, `name`, and `data` array containing 3 entries with `date` and `commits` fields.
3. **test_allocation_multiple_repos** — Insert daily_stats for 2 repos on overlapping dates. Verify response has 2 series entries, each with correct repo_id/name and their respective data.
4. **test_allocation_excludes_inactive_repos** — Insert a repo with no daily_stats in the time window. Verify it does not appear in the series array.
5. **test_allocation_days_filter** — Insert data spanning 200 days. `GET /api/analytics/allocation?days=30` → only series entries with data within the last 30 days. Dates outside the window are excluded from each repo's data array.
6. **test_allocation_default_days** — `GET /api/analytics/allocation` (no `days` param) → defaults to 90 days.
7. **test_allocation_response_shape** — Each series entry has `repo_id` (string), `name` (string), `data` (array). Each data entry has `date` (YYYY-MM-DD string) and `commits` (integer).
8. **test_allocation_data_sorted_by_date** — Insert dates out of order for a single repo. Verify the repo's `data` array is sorted ascending by date.
9. **test_allocation_component_exists** — `GET /` → HTML contains `function TimeAllocation`.
10. **test_allocation_color_palette** — `GET /` → HTML contains at least the first 5 colors from the spec palette: `#4c8dff`, `#34d399`, `#fbbf24`, `#f97316`, `#ef4444`.
11. **test_allocation_uses_recharts_area_chart** — `GET /` → HTML contains `AreaChart` and `stackOffset` references within the TimeAllocation component.

## Implementation Notes

### API: GET /api/analytics/allocation

```python
@app.get("/api/analytics/allocation")
async def get_analytics_allocation(days: int = 90, db=Depends(get_db)):
```

Query:
```sql
SELECT ds.repo_id, r.name, ds.date, ds.commits
FROM daily_stats ds
JOIN repositories r ON r.id = ds.repo_id
WHERE ds.date >= ?
ORDER BY ds.repo_id, ds.date ASC
```

The `date >= ?` parameter is computed as `(today - days)` in ISO format (`YYYY-MM-DD`). Group the flat rows into per-repo series in Python:

```python
from itertools import groupby
series = []
for repo_id, rows in groupby(result, key=lambda r: r[0]):
    row_list = list(rows)
    series.append({
        "repo_id": repo_id,
        "name": row_list[0][1],
        "data": [{"date": r[2], "commits": r[3]} for r in row_list]
    })
return {"series": series}
```

Only repos with activity in the period are included (the JOIN + WHERE naturally excludes repos with no matching daily_stats rows).

### TimeAllocation React Component

**Color palette** (10 colors, per spec):
```javascript
const ALLOC_COLORS = [
  '#4c8dff', '#34d399', '#fbbf24', '#f97316', '#ef4444',
  '#a78bfa', '#ec4899', '#06b6d4', '#84cc16', '#f43f5e'
];
```

**Weekly aggregation logic:**
When `days >= 90`, aggregate daily data into ISO weeks (group by `YYYY-Www` or by Monday-start week). Sum commits per repo per week. This keeps the chart readable for longer time ranges.

For `days < 90`, use daily data as-is.

The aggregation happens client-side after fetching the API response:
```javascript
function aggregateWeekly(data) {
  const weeks = {};
  data.forEach(({ date, commits }) => {
    const d = new Date(date + 'T00:00:00');
    // Find Monday of this week
    const day = d.getDay();
    const monday = new Date(d);
    monday.setDate(d.getDate() - ((day + 6) % 7));
    const key = monday.toISOString().slice(0, 10);
    weeks[key] = (weeks[key] || 0) + commits;
  });
  return Object.entries(weeks)
    .map(([date, commits]) => ({ date, commits }))
    .sort((a, b) => a.date.localeCompare(b.date));
}
```

**Chart data transformation:**
Recharts AreaChart needs a single data array where each entry has a `date` key plus one key per repo. Transform the per-repo series into this merged format:

```javascript
// Build merged array: [{ date: "2026-03-01", "routerview": 3, "editdb": 1 }, ...]
const allDates = new Set();
processedSeries.forEach(s => s.data.forEach(d => allDates.add(d.date)));
const merged = [...allDates].sort().map(date => {
  const entry = { date };
  processedSeries.forEach(s => {
    const match = s.data.find(d => d.date === date);
    entry[s.name] = match ? match.commits : 0;
  });
  return entry;
});
```

**"Other" grouping:**
If more than 10 repos have activity, sort by total commits descending, take top 10, and sum the rest into an "Other" key. Use `var(--text-muted)` color for "Other".

**Legend toggle:**
Use React `useState` to track a `Set` of hidden repo names. When a legend item is clicked, toggle its presence in the set. Filter the `<Area>` elements by excluding hidden series (set `Area` opacity to 0 or conditionally render).

**Component signature:**
```javascript
function TimeAllocation() { ... }
```

The component manages its own `days` state and renders `TimeRangeSelector` internally. Packet 21 can refactor to lift state if needed.

### Axes styling (per spec §5.6)

- X axis: `tick={{ fontSize: 11, fontFamily: 'var(--font-mono)', fill: 'var(--text-muted)' }}`
- Y axis: `tick={{ fontSize: 11, fontFamily: 'var(--font-mono)', fill: 'var(--text-muted)' }}`

## Acceptance Criteria

1. `GET /api/analytics/allocation` returns 200 with `{"series": [...]}`.
2. Each series entry has `repo_id` (string), `name` (string), `data` (array of `{date, commits}`).
3. `data` arrays are sorted ascending by date.
4. `days` query parameter filters to the specified window (default 90).
5. Only repos with activity in the requested period are included.
6. Empty database returns `{"series": []}`.
7. `TimeAllocation` function component exists in HTML_TEMPLATE.
8. Component renders a Recharts `<AreaChart>` with `stackOffset="none"`.
9. One `<Area>` per repo, colored from the 10-color palette.
10. If >10 repos, extras are grouped into "Other" (gray).
11. Weekly aggregation is applied when the selected range is 90 days or more.
12. Legend below chart shows repo name + color swatch; clicking toggles visibility.
13. `TimeRangeSelector` is rendered within the component for range selection.
14. X axis and Y axis use 11px monospace font with muted color per spec.
15. All existing tests pass (no regressions). Packet tests pass.

## Validation Focus Areas

- API correctness: per-repo grouping, date filtering, sort order, empty state.
- Weekly aggregation: commits are summed correctly per ISO week, no off-by-one at week boundaries.
- "Other" grouping: activates only when >10 repos, correctly sums remaining repos.
- Legend toggle: clicking hides/shows the correct series without affecting others.
- The component is defined but NOT rendered in the analytics tab (packet 21). Verify it doesn't accidentally appear.
- Recharts stacked areas: values stack correctly (not overlapping), fill colors match palette.
