# Packet 11: Commits & Branches Sub-tabs

## Why This Packet Exists

The project detail view (packet 10) has placeholder tabs for Commits and Branches. This packet adds the API endpoints and React UI to display paginated commit history and branch status, completing the core per-repo exploration experience.

## Scope

- `GET /api/repos/{id}/commits?page=1&per_page=25` — live `git log` query with `--skip`/`--max-count` pagination
- `GET /api/repos/{id}/branches` — reads from the `branches` table (populated by packet 07's scan)
- `CommitsTab` React component: table with Date | Message | +/- | Files columns, pagination controls
- `BranchesTab` React component: table with Branch | Last Commit | Status columns, status badges
- Replace `PlaceholderTab` for commits and branches sub-tabs
- Wire hash routing so `#/repo/{id}/commits` and `#/repo/{id}/branches` open the correct sub-tab directly

## Non-Goals

- Caching commits in SQLite (the spec says commits are queried live from git)
- Dependencies sub-tab (packet 17)
- Commit detail/diff view
- Branch creation, deletion, or merge actions
- Full-text search within commits
- Sorting or filtering within the commits/branches tables (beyond the default sort)

## Relevant Design Doc Sections

- §3.2 Full History Scan — git log format string and parsing (reuse `parse_git_log`)
- §3.3 Branch Scan — branch format and stale detection
- §4 GET /api/repos/{id}/commits — response shape, pagination params
- §4 GET /api/repos/{id}/branches — response shape
- §5.5 Global Table Styling — shared table CSS (already in packet 10)
- §5.5 Commits Sub-tab — column layout, date format, message truncation, +/- coloring, pagination bar
- §5.5 Branches Sub-tab — column layout, status badges (default/stale/active), sort order
- §5.8 Routing — `#/repo/{id}/commits`, `#/repo/{id}/branches` hash routes

## Allowed Files

- `git_dashboard.py`
- `tests/test_commits_branches_subtabs.py`

## Tests to Write First

### API Tests

1. **GET /api/repos/{id}/commits — basic response shape**: Register a repo (with a real or mock git dir that has commits), call the endpoint, assert response contains `commits` (list), `page`, `per_page`, `total` keys. Each commit has `hash`, `date`, `author`, `message`, `insertions`, `deletions`, `files_changed`.

2. **GET /api/repos/{id}/commits — pagination defaults**: Call without params; assert `page == 1`, `per_page == 25`.

3. **GET /api/repos/{id}/commits — pagination params**: Call with `?page=2&per_page=10`; assert `page == 2`, `per_page == 10`, `commits` length ≤ 10.

4. **GET /api/repos/{id}/commits — 404 for unknown repo**: Call with a non-existent repo ID; assert 404.

5. **GET /api/repos/{id}/commits — empty repo**: Register a repo with zero commits (init-only, no commits); assert `commits == []`, `total == 0`.

6. **GET /api/repos/{id}/branches — basic response shape**: Register a repo, insert branches into the `branches` table, call the endpoint, assert response contains `branches` list. Each branch has `name`, `last_commit_date`, `is_default` (bool), `is_stale` (bool).

7. **GET /api/repos/{id}/branches — sort order**: Insert branches with mixed default/stale/active status; assert default branch comes first, then sorted by `last_commit_date` descending.

8. **GET /api/repos/{id}/branches — 404 for unknown repo**: Assert 404.

9. **GET /api/repos/{id}/branches — no branches in DB**: Register a repo with no branch rows in the table; assert `branches == []`.

### UI Tests (string presence in HTML_TEMPLATE)

10. **CommitsTab component exists**: Assert `HTML_TEMPLATE` contains `function CommitsTab`.

11. **BranchesTab component exists**: Assert `HTML_TEMPLATE` contains `function BranchesTab`.

12. **PlaceholderTab not used for commits/branches**: Assert `HTML_TEMPLATE` does NOT contain `PlaceholderTab text="Commits"` or `PlaceholderTab text="Branches"`.

13. **Pagination UI exists**: Assert `HTML_TEMPLATE` contains `Page ` (pagination display text pattern) within the commits section logic.

## Implementation Notes

### Commits API

- **Live git query, not cached.** Each call to the endpoint runs `git log`:
  ```
  git -C {path} log --all --format='%H%x00%aI%x00%an%x00%s' --shortstat --skip={skip} --max-count={per_page}
  ```
  Where `skip = (page - 1) * per_page`.

- **Total count** via separate command:
  ```
  git -C {path} rev-list --count --all
  ```

- **Reuse `parse_git_log()`** from packet 06 to parse the output. The function already returns a list of dicts with the correct keys (`hash`, `date`, `author`, `subject`, `insertions`, `deletions`, `files_changed`).

- **Response key mapping**: The spec calls the field `message` but `parse_git_log` uses `subject`. Map `subject` → `message` in the API response.

- **Repo path lookup**: Query the `repositories` table for the path. Return 404 if not found. Also verify the path still exists on disk before running git (return 404 with a message if the directory is gone).

- **Clamp parameters**: `page` must be ≥ 1, `per_page` must be 1–100 (default 25).

### Branches API

- **Read from DB**, not live git:
  ```sql
  SELECT name, last_commit_date, is_default, is_stale
  FROM branches
  WHERE repo_id = ?
  ORDER BY is_default DESC, last_commit_date DESC
  ```

- Return `is_default` and `is_stale` as booleans (SQLite stores as 0/1).

### CommitsTab Component

- Fetches `/api/repos/${repoId}/commits?page=${page}&per_page=25` on mount and page change.
- State: `commits`, `page`, `total`, `loading`.
- Table columns: Date (YYYY-MM-DD from ISO string), Message (truncate at 80 chars), +/- (green/red), Files.
- Pagination bar below table: `< Prev  Page X of Y  Next >`. Prev disabled on page 1, Next disabled on last page. Total pages = `Math.ceil(total / 25)`.
- Empty state: "No commits found" centered in table area.

### BranchesTab Component

- Fetches `/api/repos/${repoId}/branches` on mount.
- State: `branches`, `loading`.
- Table columns: Branch (mono font), Last Commit (YYYY-MM-DD), Status.
- Status rendering:
  - `is_default === true`: blue badge with text "default"
  - `is_stale === true`: orange badge with text "stale (N days)" where N = days since `last_commit_date`
  - Otherwise: plain "active" text in muted color
- Sort is handled server-side (default first, then by date desc).
- Empty state: "No branches found" centered in table area.

### Hash Routing for Sub-tabs

- The current routing likely maps `#/repo/{id}` to ProjectDetail. Extend the hash parser to extract an optional sub-tab segment: `#/repo/{id}/commits`, `#/repo/{id}/branches`, `#/repo/{id}/deps`.
- Pass the extracted sub-tab to `ProjectDetail` as the initial `activeSubTab` value.
- When the user clicks a sub-tab in `SubTabNav`, update `window.location.hash` to include the sub-tab (e.g., `#/repo/{id}/commits`).
- Changing `activeSubTab` via click should update the hash without full page reload.

### CSS Badge Styles

The branches status badges need two new badge styles (if not already present from packet 05's RuntimeBadge):
- **Blue badge** (default): `color: var(--accent-blue)`, `background: var(--accent-blue-dim)`, 11px font, weight 500, padding 2px 8px, border-radius 4px.
- **Orange badge** (stale): `color: var(--status-orange)`, `background: var(--status-orange-bg)`, same sizing.

Check whether `--status-orange-bg` CSS variable exists. If not, define it as a low-opacity orange (e.g., `rgba(245, 166, 35, 0.12)`). Similarly for `--accent-blue-dim` (e.g., `rgba(56, 132, 255, 0.12)`).

## Acceptance Criteria

1. `GET /api/repos/{id}/commits` returns 200 with keys: `commits`, `page`, `per_page`, `total`.
2. Each commit object in the response has keys: `hash`, `date`, `author`, `message`, `insertions`, `deletions`, `files_changed`.
3. Pagination works: `?page=2&per_page=10` skips the first 10 commits and returns up to 10.
4. `total` reflects the actual number of commits in the repo (via `git rev-list --count --all`).
5. `GET /api/repos/{id}/commits` returns 404 for unknown repo ID.
6. `GET /api/repos/{id}/branches` returns 200 with key: `branches`.
7. Each branch object has keys: `name`, `last_commit_date`, `is_default`, `is_stale`.
8. Branches are sorted: default branch first, then by `last_commit_date` descending.
9. `GET /api/repos/{id}/branches` returns 404 for unknown repo ID.
10. `CommitsTab` component renders a table with columns: Date, Message, +/-, Files.
11. `CommitsTab` shows pagination controls (`Prev`, page indicator, `Next`) below the table.
12. Insertions are styled green (`var(--status-green)`), deletions red (`var(--status-red)`).
13. `BranchesTab` renders a table with columns: Branch, Last Commit, Status.
14. Default branch shows a blue "default" badge.
15. Stale branches show an orange "stale (N days)" badge.
16. Active (non-default, non-stale) branches show "active" in muted text.
17. `PlaceholderTab` is no longer used for Commits or Branches.
18. Navigating to `#/repo/{id}/commits` opens the Commits sub-tab directly.
19. Navigating to `#/repo/{id}/branches` opens the Branches sub-tab directly.
20. Clicking a sub-tab updates `window.location.hash` to include the sub-tab segment.
21. All existing tests (178+) still pass (no regressions).

## Validation Focus Areas

- **Commit pagination accuracy**: Verify that page boundaries are correct — the Nth commit on page 1 should not appear on page 2. Test with a repo that has a known number of commits.
- **Git subprocess calls**: Ensure `--skip` and `--max-count` are correctly computed from page/per_page. Off-by-one errors are common here.
- **Branch sort order**: The default branch must always be first regardless of its date. Verify with a branch that has a very old `last_commit_date` but `is_default = true`.
- **Stale day calculation**: The "N days" in the stale badge should be computed in the frontend from `last_commit_date`, not sent by the server. Verify it's reasonable (matches the date).
- **Hash routing**: Navigate directly to `#/repo/{id}/branches` via URL bar and confirm the Branches tab is active on load, not Activity.
- **Empty states**: Verify both tables show their empty message when no data exists.
- **Regression**: Ensure the Activity sub-tab and all fleet overview functionality still works.
