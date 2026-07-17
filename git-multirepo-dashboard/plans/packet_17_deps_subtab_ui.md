# Packet 17: Dependencies Sub-tab UI

## Why This Packet Exists

The dependency health data collected by packets 12–16 is stored in the DB but invisible to users. This packet exposes it through a per-repo deps API endpoint and a table UI in the project detail view, replacing the current PlaceholderTab.

## Scope

- **GET /api/repos/{repo_id}/deps** endpoint — reads `dependencies` table, groups by manager, sorts packages by severity (vulnerable → major → outdated → ok), returns JSON array.
- **POST /api/repos/{repo_id}/scan/deps** endpoint — runs `run_dep_scan_for_repo` for the specified repo synchronously, returns the updated deps list. Returns 404 if repo not found.
- **DepsTab** React component replacing `PlaceholderTab('Dependencies')`:
  - Fetches `/api/repos/{repoId}/deps` on mount.
  - Renders one table section per manager (manager name as section header).
  - Columns: **Package** | **Current** | **Latest** | **Status**.
  - Severity color-coded status text (see Implementation Notes).
  - "Last checked: X ago" below table (relative time from `checked_at`).
  - "Check Now" button (secondary style) triggers POST, shows loading state, refetches on completion.
  - Empty state: "No dependencies detected" (existing `.table-empty` style).

## Non-Goals

- Fleet-wide dependency cross-view (packet 20/21).
- Dep overlap analysis (packet 20).
- Error states for scan failures (packet 22).
- Analytics tab anything (packets 18–21).
- Pagination — dep lists are small enough to render fully.

## Relevant Design Doc Sections

- §4.0 — `GET /api/repos/{id}/deps` response shape (lines 563–588)
- §5.5 — Dependencies Sub-tab table styling, columns, severity colors, sort order, "Check Now" button (lines 1006–1027)
- §5.5 — Global Table Styling (lines 943–955)

## Allowed Files

- `git_dashboard.py`
- `tests/test_deps_subtab_ui.py` (new)

## Tests to Write First

All tests use the HTTPX `AsyncClient` pattern established in prior packets.

1. **test_get_deps_empty_repo** — Register a repo with no dependencies. `GET /api/repos/{id}/deps` → 200, empty list `[]`.
2. **test_get_deps_single_manager** — Insert 3 deps (ok, outdated, vulnerable) for manager `pip`. `GET /api/repos/{id}/deps` → 200, single manager group, packages sorted vulnerable → outdated → ok.
3. **test_get_deps_multiple_managers** — Insert deps for both `pip` and `npm`. Response contains 2 manager groups.
4. **test_get_deps_sort_order** — Insert deps with all 4 severities (ok, outdated, major, vulnerable). Verify sort within each manager group: vulnerable first, then major, then outdated, then ok.
5. **test_get_deps_404** — `GET /api/repos/nonexistent/deps` → 404.
6. **test_get_deps_response_shape** — Verify each package object has: `name`, `current_version`, `wanted_version`, `latest_version`, `severity`, `advisory_id`. Verify each manager group has: `manager`, `packages`, `checked_at`.
7. **test_check_now_endpoint** — Mock `run_dep_scan_for_repo` (patch at module level). `POST /api/repos/{id}/scan/deps` → 200, verify mock was called with correct repo, response contains updated deps.
8. **test_check_now_404** — `POST /api/repos/nonexistent/scan/deps` → 404.
9. **test_deps_tab_component_exists** — `GET /` → HTML contains `function DepsTab`.
10. **test_deps_tab_replaces_placeholder** — `GET /` → HTML does NOT render `PlaceholderTab` for the `deps` sub-tab case. The switch/conditional for `activeSubTab === 'deps'` renders `DepsTab`.
11. **test_severity_status_text_mapping** — `GET /` → HTML contains the 4 status display strings: "up to date", "outdated", "major update", and the advisory_id display pattern for vulnerables.

## Implementation Notes

### API: GET /api/repos/{repo_id}/deps

```python
@app.get("/api/repos/{repo_id}/deps")
async def get_repo_deps(repo_id: str):
```

Query:
```sql
SELECT manager, name, current_version, wanted_version, latest_version,
       severity, advisory_id, checked_at
FROM dependencies WHERE repo_id = ?
ORDER BY manager,
  CASE severity
    WHEN 'vulnerable' THEN 0
    WHEN 'major' THEN 1
    WHEN 'outdated' THEN 2
    ELSE 3
  END,
  name
```

Group results by `manager` in Python. Return:
```json
[
  {
    "manager": "pip",
    "packages": [
      {
        "name": "requests",
        "current_version": "2.31.0",
        "wanted_version": "2.31.0",
        "latest_version": "2.32.3",
        "severity": "vulnerable",
        "advisory_id": "CVE-2024-35195"
      }
    ],
    "checked_at": "2026-03-10T07:55:00"
  }
]
```

`checked_at` is the MAX checked_at for that manager group (all deps in a manager are scanned together).

### API: POST /api/repos/{repo_id}/scan/deps

1. Look up repo row from `repositories` table. 404 if not found.
2. Call `await run_dep_scan_for_repo(db, repo_row)` (already exists from packet 16).
3. Re-query deps and return the same shape as GET (so the UI can update in-place).

### DepsTab React Component

Follow the same pattern as `BranchesTab`:
- `useState` for deps data, loading, and scanning states.
- `useEffect` fetch on mount (and when `repoId` changes).
- `handleCheckNow` — sets scanning=true, POSTs, updates deps data on success, clears scanning.
- Render one `.table-container` per manager group with a manager header.
- Grid columns: `1fr 100px 100px 160px` (Package, Current, Latest, Status).

### Severity → Display Mapping

| severity | Display Text | Color |
|---|---|---|
| `ok` | "up to date" | `var(--status-green)` |
| `outdated` | "outdated" | `var(--status-yellow)` |
| `major` | "major update" | `var(--status-orange)` |
| `vulnerable` | advisory_id value (e.g. "CVE-2024-35195") | `var(--status-red)`, weight 600 |

### Version Display

- If `current_version === latest_version`: show latest in normal weight.
- If `current_version !== latest_version`: show latest in `fontWeight: 600`.

### "Last checked" Relative Time

Reuse or adapt the existing `timeAgo` JavaScript function (already used by DetailHeader for `last_scanned`). Display below each manager table: "Last checked: 5 min ago" in 13px `var(--font-body)` `var(--text-muted)`.

## Acceptance Criteria

1. `GET /api/repos/{id}/deps` returns 200 with an array of manager groups.
2. Each manager group has `manager` (string), `packages` (array), `checked_at` (string or null).
3. Each package has `name`, `current_version`, `wanted_version`, `latest_version`, `severity`, `advisory_id`.
4. Packages within each manager group are sorted: vulnerable → major → outdated → ok, then alphabetical by name.
5. `GET /api/repos/{id}/deps` returns `[]` for a repo with no dependencies.
6. `GET /api/repos/nonexistent/deps` returns 404.
7. `POST /api/repos/{id}/scan/deps` calls `run_dep_scan_for_repo` and returns updated deps.
8. `POST /api/repos/nonexistent/scan/deps` returns 404.
9. DepsTab component exists in HTML_TEMPLATE and replaces the PlaceholderTab for the deps sub-tab.
10. DepsTab renders a table with columns: Package, Current, Latest, Status.
11. Status text uses the correct severity → color mapping from the spec.
12. "Last checked: X ago" text appears below each manager section.
13. "Check Now" button is present, styled as secondary, and shows loading/disabled state while scanning.
14. Empty state shows "No dependencies detected" when no deps exist.
15. All existing tests pass (no regressions). Packet tests pass.

## Validation Focus Areas

- Sort order correctness (severity ordering within each manager group).
- Null safety: `checked_at` can be null, `advisory_id` can be null, version fields can be null.
- The PlaceholderTab for deps is fully replaced (no residual placeholder).
- "Check Now" calls the real `run_dep_scan_for_repo`, not a no-op.
- CSS vars used match the spec (not hardcoded hex colors).
