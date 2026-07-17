# Packet 05: Fleet Overview UI

## Why This Packet Exists

The Fleet Overview tab is the primary view users see on launch. It wires the GET /api/fleet data (delivered in packet 03) to live KPI cards, a sortable/filterable project grid, and compact 3-row project cards — turning the placeholder from packet 04 into a functional dashboard.

## Scope

- Replace the `ContentArea` placeholder for `tab='fleet'` with a `FleetOverview` component
- **KPI row**: 6 stat cards (Repos, Dirty, Commits This Week / This Month, Net LOC, Stale Branches, Vuln/Outdated) bound to `kpis` from GET /api/fleet
- **Project grid**: CSS Grid `repeat(auto-fill, minmax(340px, 1fr))` responsive layout
- **Project cards** (compact 3-row):
  - Row 1: Runtime badge (colored abbreviation), project name (truncated, tooltip with full path), relative time
  - Row 2: Last commit message (single line, truncated)
  - Row 3: Status pills (Clean green pill, or dirty: mod/new/staged pills), separator, current branch, branch count, dep badge
- **Sort control**: custom dropdown with 4 options — Last active (default), Name A-Z, Most changes, Most stale branches
- **Filter control**: text input, case-insensitive substring match on project name
- **Empty state**: shown when `repos` array is empty — message prompting user to add repos
- **Card click**: navigates to `#/repo/{id}` (detail view placeholder already exists from packet 04)
- **Freshness-based card styling**: background and left-border colors based on `last_commit_date` age
- **Hover sparkline container**: Recharts `<AreaChart>` overlay at card bottom, slides up on hover — renders sparkline data if present (empty `[]` until packets 06+09 populate it)
- **Conditional KPI coloring**: Dirty count yellow, Vuln count red, Stale Branches orange when > 0
- **Data fetching**: `useEffect` + `fetch('/api/fleet')` on mount, with loading state

## Non-Goals

- Populating sparkline data from daily_stats (packet 06 provides the data, packet 09 wires it to fleet response)
- Real `branch_count` / `stale_branch_count` values (packet 07)
- Real `dep_summary` values (packets 12–16)
- Wiring "Scan Dir" or "Full Scan" header buttons (packet 08)
- Grid re-sort animation / view transitions (packet 23)
- Loading skeletons (packet 23)
- Error state for failed API fetch (packet 22)

## Relevant Design Doc Sections

- §5.4 Fleet Overview Tab — KPI Row, Project Grid, Project Card (Compact 3-Row), Sort/Filter controls, Empty state
- §5.2 Design System — CSS custom properties (already implemented in packet 04)
- §4 API — GET /api/fleet response shape (already implemented in packet 03)

## Allowed Files

- `git_dashboard.py` — modify `HTML_TEMPLATE` to add FleetOverview and sub-components
- `tests/test_fleet_overview_ui.py` — new test file

## Tests to Write First

1. **`test_fleet_overview_component_exists`**: HTML_TEMPLATE contains a `FleetOverview` function component definition.
2. **`test_kpi_row_component_exists`**: HTML_TEMPLATE contains a `KpiRow` component that receives `kpis` prop.
3. **`test_project_card_component_exists`**: HTML_TEMPLATE contains a `ProjectCard` component.
4. **`test_sort_dropdown_options`**: HTML_TEMPLATE contains sort option labels: "Last active", "Name A-Z", "Most changes", "Most stale branches".
5. **`test_filter_input_placeholder`**: HTML_TEMPLATE contains a filter input with placeholder "Filter projects...".
6. **`test_empty_state_message`**: HTML_TEMPLATE contains an empty state element/message for when no repos are registered.
7. **`test_runtime_badge_labels`**: HTML_TEMPLATE contains runtime badge label mappings for all 11 types: PY, JS, GO, RS, RB, PHP, SH, DK, HTML, MIX, ??.
8. **`test_freshness_thresholds`**: HTML_TEMPLATE contains freshness classification logic with thresholds at 7, 30, and 90 days.
9. **`test_relative_time_function`**: HTML_TEMPLATE contains a `timeAgo` or equivalent function for formatting relative timestamps.
10. **`test_card_click_navigation`**: HTML_TEMPLATE includes `window.location.hash = '#/repo/'` navigation pattern on card click.
11. **`test_sparkline_hover_container`**: HTML_TEMPLATE contains sparkline container with `translateY` transform for hover reveal.
12. **`test_fleet_data_fetch`**: HTML_TEMPLATE contains `fetch('/api/fleet')` call.
13. **`test_status_pill_variants`**: HTML_TEMPLATE contains pill rendering logic for "Clean", "mod", "new", "staged" variants.
14. **`test_kpi_conditional_coloring`**: HTML_TEMPLATE contains conditional color logic for dirty (yellow), vuln (red), stale (orange) KPI values.

## Implementation Notes

### Data Flow

`FleetOverview` calls `fetch('/api/fleet')` on mount via `useEffect`. The response shape (from packet 03):

```json
{
  "repos": [{ "id", "name", "path", "runtime", "current_branch",
               "last_commit_date", "last_commit_message",
               "has_uncommitted", "modified_count", "untracked_count", "staged_count",
               "branch_count", "stale_branch_count", "dep_summary", "sparkline" }],
  "kpis": { "total_repos", "repos_with_changes", "commits_this_week",
            "commits_this_month", "net_lines_this_week", "stale_branches",
            "vulnerable_deps", "outdated_deps" },
  "scanned_at": "..."
}
```

### Component Hierarchy

```
FleetOverview
├── KpiRow (kpis)
│   └── KpiCard × 6 (value, label, color)
├── GridControls (sortBy, filterText, onSortChange, onFilterChange)
│   ├── SortDropdown (custom, not native <select>)
│   └── FilterInput
├── ProjectGrid (repos, sortBy, filterText)
│   └── ProjectCard × N (repo)
│       ├── Row 1: RuntimeBadge + name + timeAgo
│       ├── Row 2: commit message
│       ├── Row 3: StatusPills + branch + deps
│       └── SparklineOverlay (sparkline data)
└── EmptyState (when repos.length === 0)
```

### KPI Card Mapping

| Position | Label | Value source | Color when > 0 |
|----------|-------|-------------|-----------------|
| 1 | Repos | `kpis.total_repos` | default |
| 2 | Dirty | `kpis.repos_with_changes` | `--status-yellow` |
| 3 | Commits | `kpis.commits_this_week` / `kpis.commits_this_month` (show as "X / Y") | default |
| 4 | Net LOC | `kpis.net_lines_this_week` (show with + prefix if positive) | default |
| 5 | Stale Br | `kpis.stale_branches` | `--status-orange` |
| 6 | Vuln/Out | `kpis.vulnerable_deps` / `kpis.outdated_deps` | `--status-red` |

### Runtime Badge Mapping

```javascript
const RUNTIME_LABELS = {
  python: 'PY', node: 'JS', go: 'GO', rust: 'RS', ruby: 'RB',
  php: 'PHP', shell: 'SH', docker: 'DK', html: 'HTML', mixed: 'MIX', unknown: '??'
};
```

Use `var(--runtime-{type})` for badge color. Background at 20% opacity, text at full color.

### Relative Time Formatting

Convert ISO 8601 `last_commit_date` to relative string:
- < 1 hour: "Xm ago"
- < 24 hours: "Xh ago"
- < 30 days: "Xd ago"
- < 365 days: "Xmo ago"
- else: "Xy ago"
- null: "never"

### Sort Logic (client-side)

All sorting is done on the `repos` array in React state after filtering:
- **Last active**: sort by `last_commit_date` descending (null last)
- **Name A-Z**: sort by `name` case-insensitive ascending
- **Most changes**: sort by `modified_count + untracked_count` descending
- **Most stale branches**: sort by `stale_branch_count` descending

### Card Freshness

Determine from `last_commit_date` (days since):
- ≤ 7 days: background `--fresh-this-week`, left border `--fresh-border-this-week` (3px blue)
- ≤ 30 days: background `--fresh-this-month`, no special left border
- ≤ 90 days: background `--fresh-older`, no special left border
- > 90 days or null: background `--fresh-stale`, left border `--fresh-border-stale` (3px orange)

### Sparkline Hover

The sparkline container is absolutely positioned at the bottom of each card. Uses CSS `transform: translateY(100%)` → `translateY(0)` on card hover, with `150ms ease-out` transition. On mouse leave: `100ms ease-in`. The Recharts `<AreaChart>` fills the container (full width, 28px height). Fill `--accent-blue-dim`, stroke `--accent-blue`, no axes/tooltip. Gracefully handles empty `sparkline` array (renders nothing visible).

### Custom Sort Dropdown

Not a native `<select>`. Build a simple dropdown component:
- Trigger button shows current selection
- On click, toggles a positioned menu of options
- Close on outside click or option select
- Style per spec: `--bg-input` background, `--border-default` border, 13px `--font-body`

## Acceptance Criteria

1. Navigating to `#/fleet` (or `/` with no hash) renders the Fleet Overview with KPI cards and project grid.
2. KPI row shows 6 cards with correct labels and values from the API response.
3. KPI "Dirty" value uses `--status-yellow` color when > 0.
4. KPI "Vuln/Out" value uses `--status-red` color when > 0.
5. KPI "Stale Br" value uses `--status-orange` color when > 0.
6. Project grid uses CSS Grid with `minmax(340px, 1fr)` responsive columns.
7. Each project card shows: runtime badge, name, relative time, commit message, and status pills.
8. Runtime badge displays correct abbreviation (PY, JS, GO, etc.) with correct runtime color.
9. Status pills show "Clean" (green) when no uncommitted changes, or individual mod/new/staged pills when dirty.
10. Sort dropdown offers 4 options and re-sorts the grid when changed.
11. Filter input filters cards by name (case-insensitive substring match).
12. When no repos are registered, an empty state message is displayed instead of the grid.
13. Clicking a card navigates to `#/repo/{id}`.
14. Cards have freshness-based background colors (4 tiers) and left-border accents (this-week blue, stale orange).
15. Hovering a card reveals a sparkline overlay from the bottom (slides up with transition).
16. `FleetOverview` fetches data from `/api/fleet` on mount.
17. All existing tests (96) continue to pass.

## Validation Focus Areas

- Verify the data binding is correct — KPI values match what GET /api/fleet returns
- Verify sort and filter work together (filter first, then sort the filtered results)
- Verify empty sparkline array (`[]`) doesn't cause rendering errors
- Verify null `last_commit_date` is handled gracefully (shows "never", uses stale freshness)
- Verify null `dep_summary` doesn't crash the dep badge rendering (should omit badge entirely)
- Check that the card layout is responsive — grid wraps correctly at narrow widths
- Verify no console errors when loading the page
