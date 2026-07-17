# Packet 20: Analytics: Dep Overlap

## Why This Packet Exists

The dependencies table (populated by packet 16) stores per-repo dependency data but there is no way to see which packages are shared across repos or whether those repos use divergent versions. This packet adds a fleet-wide dependency overlap API endpoint and an expandable table component showing shared packages, usage counts, and version spread.

## Scope

- **GET /api/analytics/dep-overlap** endpoint — queries `dependencies` joined with `repositories` to return packages appearing in 2+ repos, sorted by count descending, with per-repo version details and a min–max version spread string.
- **DepOverlap** React component — standalone, self-contained component that:
  - Fetches `/api/analytics/dep-overlap` on mount.
  - Renders a table with columns: Package, Manager, Used In, Version Spread.
  - "Used In" count is clickable to expand/collapse a detail section showing repo names and their versions.
  - Uses global table CSS classes already defined in the project.

**Note:** This packet delivers the API and the component definition. The component is NOT wired into the Analytics tab yet — that happens in packet 21 (Analytics Tab Wiring).

## Non-Goals

- Analytics tab wiring / layout (packet 21).
- Heatmap (packet 18 — already done).
- Time allocation chart (packet 19).
- Dependency health indicators (severity/vulnerability) in this table — it only shows version overlap.
- Filtering by manager or package name (could be a future enhancement).
- Version comparison logic (e.g., semver sorting) — the spread is just min/max by string value of whatever versions exist.

## Relevant Design Doc Sections

- §4.0 — `GET /api/analytics/dep-overlap` response shape (lines 622–641)
- §5.6 — Analytics Tab: Dependency Overlap Table (lines 1065–1080): columns, fonts, expandable rows, sort order
- §8.0 — Phase 4 implementation order

## Allowed Files

- `git_dashboard.py`
- `tests/test_analytics_dep_overlap.py` (new)

## Tests to Write First

1. **test_dep_overlap_empty_db** — No dependencies rows. `GET /api/analytics/dep-overlap` → 200, `{"packages": []}`.
2. **test_dep_overlap_single_repo_excluded** — Insert dependencies for one repo only. Verify `packages` is empty (packages must be in 2+ repos).
3. **test_dep_overlap_two_repos_shared** — Insert `fastapi` for repo A (version 0.109.0) and repo B (version 0.115.0), both with manager `pip`. Verify response has 1 package entry with `name: "fastapi"`, `manager: "pip"`, `count: 2`, `repos` array with 2 entries (each having `repo_id`, `name`, `version`), and `version_spread: "0.109.0 - 0.115.0"`.
4. **test_dep_overlap_sorted_by_count_desc** — Insert 3 packages: one shared by 4 repos, one by 3, one by 2. Verify the response `packages` array is sorted by count descending.
5. **test_dep_overlap_same_package_different_managers** — Insert `lodash` under both `npm` and `pip` managers for different repos. Verify they appear as separate entries (grouped by name + manager).
6. **test_dep_overlap_version_spread_single_version** — Insert `express` with the same version `4.18.0` in 3 repos. Verify `version_spread` is `"4.18.0 - 4.18.0"`.
7. **test_dep_overlap_null_versions** — Insert deps where `current_version` is NULL for some repos. Verify NULL versions are excluded from the spread calculation and the repos array shows `version: null`.
8. **test_dep_overlap_response_shape** — Each package entry has `name` (string), `manager` (string), `repos` (array), `version_spread` (string), `count` (integer). Each repo entry has `repo_id` (string), `name` (string), `version` (string or null).
9. **test_dep_overlap_component_exists** — `GET /` → HTML contains `function DepOverlap`.
10. **test_dep_overlap_table_uses_global_styles** — `GET /` → HTML contains `data-table` or global table class reference within the DepOverlap component.
11. **test_dep_overlap_expand_pattern** — `GET /` → HTML contains expand/collapse state logic (e.g., `expanded` or `toggle` pattern in the component).

## Implementation Notes

### API: GET /api/analytics/dep-overlap

```python
@app.get("/api/analytics/dep-overlap")
async def get_analytics_dep_overlap(db=Depends(get_db)):
```

Query approach — two-step:

**Step 1:** Find packages in 2+ repos:
```sql
SELECT d.name, d.manager, COUNT(DISTINCT d.repo_id) as cnt
FROM dependencies d
GROUP BY d.name, d.manager
HAVING cnt >= 2
ORDER BY cnt DESC
```

**Step 2:** For each qualifying package, fetch repo details:
```sql
SELECT d.repo_id, r.name, d.current_version
FROM dependencies d
JOIN repositories r ON r.id = d.repo_id
WHERE d.name = ? AND d.manager = ?
ORDER BY r.name
```

Alternatively, fetch all deps in a single query and group in Python for efficiency:
```sql
SELECT d.name, d.manager, d.repo_id, r.name as repo_name, d.current_version
FROM dependencies d
JOIN repositories r ON r.id = d.repo_id
ORDER BY d.name, d.manager, r.name
```

Then group in Python:
```python
from itertools import groupby

packages = []
for (pkg_name, manager), rows in groupby(result, key=lambda r: (r[0], r[1])):
    row_list = list(rows)
    if len(row_list) < 2:
        continue
    versions = [r[4] for r in row_list if r[4] is not None]
    versions_sorted = sorted(versions) if versions else []
    spread = f"{versions_sorted[0]} - {versions_sorted[-1]}" if versions_sorted else ""
    packages.append({
        "name": pkg_name,
        "manager": manager,
        "repos": [
            {"repo_id": r[2], "name": r[3], "version": r[4]}
            for r in row_list
        ],
        "version_spread": spread,
        "count": len(row_list)
    })

# Sort by count descending
packages.sort(key=lambda p: p["count"], reverse=True)
return {"packages": packages}
```

### Version Spread

The spec shows `"0.109.0 - 0.115.0"` format (space-dash-space). Use simple string sorting for min/max — this is good enough for most version schemes and matches the spec's intent. If all versions are NULL, return an empty string.

### DepOverlap React Component

**Component signature:**
```javascript
function DepOverlap() { ... }
```

The component fetches data on mount and manages its own state.

**Expand/collapse state:**
Use React `useState` with a `Set` of expanded package keys (e.g., `"fastapi:pip"`). Toggle on click.

**Table structure (per spec §5.6):**
```html
<table class="data-table">
  <thead>
    <tr><th>Package</th><th>Manager</th><th>Used In</th><th>Version Spread</th></tr>
  </thead>
  <tbody>
    <!-- For each package: summary row -->
    <tr>
      <td style="fontFamily: 'var(--font-mono)', fontSize: '14px'">fastapi</td>
      <td style="fontSize: '12px', textTransform: 'uppercase', color: 'var(--text-muted)'">pip</td>
      <td>
        <span onClick={toggle} style="color: 'var(--accent-blue)', cursor: 'pointer'">
          ▸ 8 repos  <!-- ▸ collapsed, ▾ expanded -->
        </span>
      </td>
      <td style="fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)'">0.109.0 -- 0.115.0</td>
    </tr>
    <!-- If expanded: one row per repo, indented -->
    <tr>
      <td colSpan={4} style="paddingLeft: '24px'">
        <div>routerview — 0.109.0</div>
        <div>editdb — 0.115.0</div>
      </td>
    </tr>
  </tbody>
</table>
```

**Chevron icon:**
Use a simple text chevron that rotates: `▸` (collapsed) → `▾` (expanded). The spec says "small chevron rotating 90 degrees" — CSS `transform: rotate(90deg)` on a `▸` character, or just swap characters.

**Empty state:**
When `packages` is empty, show a muted message: "No shared dependencies found across repos."

**Styling details from spec:**
- Package column: 14px `var(--font-mono)`, `var(--text-primary)`.
- Manager column: 12px `var(--font-body)`, `var(--text-muted)`, uppercase.
- Used In count: 13px `var(--font-body)`, `var(--accent-blue)`, clickable.
- Expanded repo rows: indented 24px, 12px `var(--font-mono)`, `var(--text-secondary)`.
- Version Spread: 13px `var(--font-mono)`, `var(--text-secondary)`.

## Acceptance Criteria

1. `GET /api/analytics/dep-overlap` returns 200 with `{"packages": [...]}`.
2. Each package entry has `name` (string), `manager` (string), `repos` (array), `version_spread` (string), `count` (integer).
3. Each repo entry within a package has `repo_id` (string), `name` (string), `version` (string or null).
4. Only packages appearing in 2+ repos are included.
5. Packages are sorted by `count` descending.
6. `version_spread` shows `"min - max"` using sorted version strings, or empty string if all versions are null.
7. Same package under different managers appears as separate entries.
8. Empty database returns `{"packages": []}`.
9. `DepOverlap` function component exists in HTML_TEMPLATE.
10. Component renders a table using global table CSS classes.
11. "Used In" count is clickable and expands to show per-repo version details.
12. Expanded rows show repo name and version, indented 24px.
13. Chevron indicator shows expand/collapse state.
14. Empty state message displayed when no shared dependencies exist.
15. All existing tests pass (no regressions). Packet tests pass.

## Validation Focus Areas

- API correctness: the 2+ repo threshold, correct count, correct version spread computation.
- Grouping by (name, manager): same package name under different managers must be separate entries.
- NULL version handling: repos with NULL current_version should still appear in repos array but not affect version_spread.
- Expand/collapse: state is independent per package (expanding one doesn't collapse others).
- The component is defined but NOT rendered in the analytics tab (packet 21). Verify it doesn't accidentally appear.
- Table uses global styling classes from packet 04/10 (not inline-only styles for the table structure).
