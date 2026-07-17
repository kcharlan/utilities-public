# Packet 10: Project Detail View & Activity Chart

## Why This Packet Exists

Clicking a project card currently navigates to `#/repo/{id}` but renders nothing. This packet builds the project detail view with its header, sub-tab navigation, and the default Activity sub-tab with a diverging area chart — the primary way users inspect a single project's history.

## Scope

- **Backend: `GET /api/repos/{id}`** — Returns full detail for one repo: repositories row + working_state + last_full_scan_at.
- **Backend: `GET /api/repos/{id}/history?days=90`** — Returns daily_stats rows for the repo within the requested time range. Only dates with activity are included.
- **Frontend: ProjectDetail component** — Routed at `#/repo/{id}`. Contains detail header (back button, project name, path, meta line, "Scan Now" button placeholder) and sub-tab navigation.
- **Frontend: Sub-tab navigation** — Tabs: Activity | Commits | Branches | Dependencies. Activity is the default. Commits, Branches, and Dependencies render placeholder empty states (wired in packets 11 and 17).
- **Frontend: ActivityChart component** — Recharts `<AreaChart>` with `stackOffset="sign"`. Three series: insertions (green, upward), deletions (red, downward as negated values), net (blue line overlay). 300px height, tooltip on hover.
- **Frontend: TimeRangeSelector component** — Button group: [30d] [90d] [180d] [1y] [All]. Default 90d. Active button highlighted with `var(--accent-blue)`.
- **Frontend: Global table styling CSS** — Shared table styles for all sub-tabs (header row, body rows, hover, empty state). Defined once, used by packets 11 and 17.

## Non-Goals

- Commits sub-tab content (packet 11)
- Branches sub-tab content (packet 11)
- Dependencies sub-tab content (packet 17)
- "Scan Now" button wiring (clicking does nothing — wired in a later packet when single-repo scan exists)
- View transitions / animations between fleet and detail (packet 23)
- Error states for missing repos or scan failures (packet 22)

## Relevant Design Doc Sections

- §5.5 (lines 918–941): Project detail view header spec (back button, name, path, meta line, sub-tabs)
- §5.5 (lines 956–969): Activity sub-tab with diverging area chart spec (series, colors, tooltip, time range)
- §5.5 (lines 943–954): Global table styling spec (shared styles for sub-tab tables)
- §4 (lines 498–511): `GET /api/repos/{id}` response shape
- §4 (lines 514–527): `GET /api/repos/{id}/history` response shape
- §5.8 (lines 1149–1154): Client-side routing (`#/repo/{id}` routes)

## Allowed Files

- `git_dashboard.py`
- `tests/test_project_detail.py` (new)

## Tests to Write First

### Backend API tests

1. **`test_get_repo_detail_success`** — Register a repo (insert into `repositories` + `working_state`), call `GET /api/repos/{id}`. Verify response: 200 status, JSON contains `id`, `name`, `path`, `runtime`, `default_branch`, `working_state` (dict with expected keys), `last_full_scan_at`.

2. **`test_get_repo_detail_404`** — Call `GET /api/repos/nonexistent_id`. Verify 404 response with `{"detail": "Repo not found"}` or similar.

3. **`test_get_repo_history_with_data`** — Insert `daily_stats` rows for a repo (dates spanning 30 days), call `GET /api/repos/{id}/history?days=30`. Verify: 200 status, response has `repo_id`, `days`, `data` (list of dicts with `date`, `commits`, `insertions`, `deletions`, `files_changed`). Verify only dates within the 30-day window are returned.

4. **`test_get_repo_history_default_days`** — Call `GET /api/repos/{id}/history` without `days` param. Verify default is 90 days (check `days` field in response).

5. **`test_get_repo_history_empty`** — Repo with no `daily_stats` → response has `data: []`.

6. **`test_get_repo_history_404`** — Call history endpoint for non-existent repo. Verify 404.

7. **`test_history_excludes_old_data`** — Insert rows outside the requested window (e.g., 120 days ago with `days=90`). Verify those rows are not in the response.

### Frontend / template tests

8. **`test_project_detail_component_exists`** — `HTML_TEMPLATE` contains a component named `ProjectDetail`.

9. **`test_activity_chart_component_exists`** — `HTML_TEMPLATE` contains a component named `ActivityChart`.

10. **`test_time_range_selector_exists`** — `HTML_TEMPLATE` contains a component named `TimeRangeSelector` with the expected range options (30, 90, 180, 365 or similar).

11. **`test_detail_sub_tabs_exist`** — `HTML_TEMPLATE` contains sub-tab labels: "Activity", "Commits", "Branches", "Dependencies".

12. **`test_detail_route_renders_component`** — `HTML_TEMPLATE` routing logic maps `#/repo/` routes to `ProjectDetail` component.

13. **`test_global_table_styles`** — `HTML_TEMPLATE` CSS contains global table styling (`.table-header`, `.table-row` or equivalent class names).

## Implementation Notes

### GET /api/repos/{id} endpoint

```python
@app.get("/api/repos/{repo_id}")
async def get_repo_detail(repo_id: str, db=Depends(get_db)):
    cursor = await db.execute(
        "SELECT id, name, path, runtime, default_branch, last_full_scan_at FROM repositories WHERE id = ?",
        (repo_id,)
    )
    repo = await cursor.fetchone()
    if not repo:
        raise HTTPException(status_code=404, detail="Repo not found")

    # Fetch working_state
    ws_cursor = await db.execute(
        "SELECT * FROM working_state WHERE repo_id = ?", (repo_id,)
    )
    ws = await ws_cursor.fetchone()

    return {
        "id": repo[0], "name": repo[1], "path": repo[2],
        "runtime": repo[3], "default_branch": repo[4],
        "last_full_scan_at": repo[5],
        "working_state": dict(ws) if ws else None
    }
```

Use `db.row_factory = aiosqlite.Row` if not already set, or construct dict manually from column indices (match existing patterns in the codebase).

### GET /api/repos/{id}/history endpoint

```python
@app.get("/api/repos/{repo_id}/history")
async def get_repo_history(repo_id: str, days: int = 90, db=Depends(get_db)):
    # Verify repo exists
    cursor = await db.execute("SELECT id FROM repositories WHERE id = ?", (repo_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Repo not found")

    import datetime
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    cursor = await db.execute(
        "SELECT date, commits, insertions, deletions, files_changed "
        "FROM daily_stats WHERE repo_id = ? AND date >= ? ORDER BY date",
        (repo_id, cutoff)
    )
    rows = await cursor.fetchall()

    return {
        "repo_id": repo_id,
        "days": days,
        "data": [
            {"date": r[0], "commits": r[1], "insertions": r[2],
             "deletions": r[3], "files_changed": r[4]}
            for r in rows
        ]
    }
```

### ProjectDetail component

Structure:
```jsx
function ProjectDetail({ repoId }) {
  const [repo, setRepo] = useState(null);
  const [activeSubTab, setActiveSubTab] = useState('activity');

  useEffect(() => {
    fetch(`/api/repos/${repoId}`).then(r => r.json()).then(setRepo);
  }, [repoId]);

  if (!repo) return <div>Loading...</div>;

  return (
    <div className="detail-view">
      <DetailHeader repo={repo} />
      <SubTabNav active={activeSubTab} onChange={setActiveSubTab} />
      <div className="detail-content">
        {activeSubTab === 'activity' && <ActivityTab repoId={repoId} />}
        {activeSubTab === 'commits' && <PlaceholderTab text="Commits" />}
        {activeSubTab === 'branches' && <PlaceholderTab text="Branches" />}
        {activeSubTab === 'deps' && <PlaceholderTab text="Dependencies" />}
      </div>
    </div>
  );
}
```

### DetailHeader

- Back button: `onClick={() => window.location.hash = '#/fleet'}`. Left chevron icon (inline SVG or `←` character).
- Project name: 24px heading.
- Path: 12px mono, muted.
- Meta line: RuntimeBadge (reuse from packet 05) + default branch + "Last scanned X ago".
- "Scan Now" button: secondary style, `onClick={() => {}}` (placeholder).

### ActivityTab with chart

- Fetches `GET /api/repos/{id}/history?days={selectedDays}` on mount and when `days` changes.
- Fills date gaps with zeros (the API returns only dates with activity).
- Uses Recharts `<AreaChart>` with `stackOffset="sign"`:
  - `<Area dataKey="insertions">` — green, grows upward
  - `<Area dataKey="deletions">` — uses negated values (plotted as negative), red, grows downward
  - `<Area dataKey="net">` or `<Line dataKey="net">` — blue line overlay, `net = insertions - deletions`
- Important Recharts note: `<Line>` inside `<AreaChart>` is silently ignored (per MEMORY.md). Use `<Area fill="none">` for the net line, OR use `<ComposedChart>` container which supports both `<Area>` and `<Line>`.
- Chart dimensions: 100% width, 300px height.
- Tooltip: shows date, insertions (green), deletions (red), net (blue), commits.

### TimeRangeSelector

Button group above the chart. Options: `[{label: '30d', days: 30}, {label: '90d', days: 90}, {label: '180d', days: 180}, {label: '1y', days: 365}, {label: 'All', days: 9999}]`. Active button: `var(--accent-blue)` background + white text. Inactive: transparent + `var(--text-secondary)`.

### Date gap filling (frontend)

The API returns only dates with activity. The chart needs continuous dates:
```javascript
function fillDateGaps(data, days) {
  const map = {};
  data.forEach(d => { map[d.date] = d; });
  const result = [];
  const today = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const dateStr = d.toISOString().slice(0, 10);
    result.push(map[dateStr] || {date: dateStr, commits: 0, insertions: 0, deletions: 0, files_changed: 0});
  }
  return result;
}
```

### Global table CSS

Define shared table styles in the `<style>` block:
```css
.table-container { width: 100%; border-radius: var(--radius-md); overflow: hidden; }
.table-header { background: var(--bg-secondary); /* ... spec styles */ }
.table-row { padding: 12px 16px; border-bottom: 1px solid var(--border-default); }
.table-row:nth-child(even) { background: rgba(255,255,255,0.02); }
.table-row:hover { background: var(--bg-card-hover); transition: background var(--transition-fast); }
.table-empty { /* centered muted text */ }
```

### Routing update

Update the App component's route matching:
```javascript
// Existing: #/repo/{id} → placeholder div
// New: #/repo/{id} → <ProjectDetail repoId={route.repoId} />
```

The `parseRoute` function already handles `#/repo/{id}` and returns `{tab: 'repo', repoId: id}`. Wire it to render `ProjectDetail`.

## Acceptance Criteria

1. `GET /api/repos/{valid_id}` returns 200 with `id`, `name`, `path`, `runtime`, `default_branch`, `working_state`, `last_full_scan_at`.
2. `GET /api/repos/{invalid_id}` returns 404.
3. `GET /api/repos/{id}/history?days=90` returns 200 with `repo_id`, `days`, `data` (list of daily stat objects).
4. `GET /api/repos/{id}/history` defaults to 90 days when `days` param is omitted.
5. History endpoint excludes dates outside the requested window.
6. History endpoint returns 404 for non-existent repos.
7. Clicking a project card navigates to `#/repo/{id}` and renders `ProjectDetail`.
8. Detail header shows project name, path, runtime badge, default branch, and last scan time.
9. Back button navigates to `#/fleet`.
10. Sub-tab navigation shows Activity, Commits, Branches, Dependencies tabs.
11. Activity sub-tab is the default when entering detail view.
12. Activity chart renders a diverging area chart with insertions (green, up), deletions (red, down), and net (blue line).
13. TimeRangeSelector renders 5 options (30d, 90d, 180d, 1y, All) and defaults to 90d.
14. Changing the time range refetches history data and updates the chart.
15. Chart tooltip shows date, insertions, deletions, net, and commits on hover.
16. Global table CSS styles are defined (for use by packets 11 and 17).
17. Commits, Branches, and Dependencies sub-tabs render placeholder empty states.
18. All new tests pass. All existing tests still pass (no regressions).

## Validation Focus Areas

- Verify the diverging chart renders correctly: insertions should grow upward from zero, deletions downward. Check that `stackOffset="sign"` is used and that deletion values are negated in the data.
- Verify the Recharts container type supports all three series (use `ComposedChart` if mixing `Area` and `Line`, since `Line` inside `AreaChart` is silently ignored).
- Verify date gap filling produces a continuous date series (no gaps = no visual jumps in the chart).
- Verify the detail view properly handles repos with no history data (empty chart, not a crash).
- Verify the back button works correctly and returns to the fleet view with state preserved.
- Test that `parseRoute` correctly extracts repo ID from `#/repo/abc123def` hashes.
