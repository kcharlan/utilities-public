# Packet 22: Error States & Edge Cases

## Why This Packet Exists

The app currently silently skips repos whose disk paths no longer exist (they vanish from the fleet) and does not surface per-repo scan failures to the user. The spec (§5.7, §9) requires visible error states: a red-bordered card for missing paths, a "scan failed" badge for broken scans, and an offline indicator for failed dep checks. The 409 concurrent-scan rejection is already implemented (packet 08) and only needs a regression guard here.

## Scope

**Backend:**

- Schema migration: add `scan_error TEXT DEFAULT NULL` and `dep_check_error BOOLEAN DEFAULT FALSE` columns to `working_state` (idempotent ALTER TABLE)
- `scan_fleet_quick`: return repos with `path_exists: false` and empty working-state fields instead of silently skipping them
- `run_fleet_scan`: on per-repo scan failure, set `scan_error` in working_state; clear on success
- `run_dep_scan_for_repo`: set `dep_check_error = true` in working_state when any ecosystem check raises an exception; clear to `false` when all succeed
- `GET /api/fleet`: include `path_exists`, `scan_error`, and `dep_check_error` per repo in response
- `GET /api/repos/{id}`: include `path_exists` (dynamic check) in response
- `PATCH /api/repos/{id}`: new endpoint to update a repo's path (for the "Update Path" button)

**Frontend:**

- `ProjectCard`: red left border (`4px solid var(--status-red)`) when `path_exists === false`, overriding any freshness border
- `ProjectCard`: row 2 shows "Path not found" in `var(--status-red)` instead of the commit message when `path_exists === false`
- `ProjectCard`: "scan failed" badge at top-right corner when `scan_error` is truthy — `10px var(--font-body)` weight 600, `var(--status-red)` text on `var(--status-red-bg)`, padding `2px 6px`, border-radius `3px`
- `DetailHeader`: "Remove" and "Update Path" buttons when `path_exists === false` (Remove calls existing DELETE endpoint; Update Path shows an inline input + save that calls PATCH)
- `DepsTab`: offline indicator — small orange dot (6px circle, `var(--status-orange)`) + "offline" text in `var(--status-orange)` next to "Last checked" when `dep_check_error` is true

## Non-Goals

- Loading skeleton cards (packet 23: Polish & Accessibility)
- View transitions or animation polish (packet 23)
- Focus states or keyboard navigation (packet 23)
- Global "Dependencies" tab wiring (no packet assigned)
- Changes to individual analytics component internals
- Changes to scan_log table structure

## Relevant Design Doc Sections

- §5.7 "Empty / Loading / Error States" — error state visual specs (path not found, scan failed, offline indicator)
- §9 "Edge Cases and Error Handling" — behavior table (path deleted, concurrent scans, etc.)

## Allowed Files

- `git_dashboard.py` — schema migration, backend function changes, new PATCH endpoint, frontend component changes
- `tests/test_error_states.py` — new test file

## Tests to Write First

### Backend tests

1. **test_scan_fleet_quick_includes_missing_path**: Register a repo, delete its path, call `scan_fleet_quick`. Result list should include the repo with `path_exists: False` and null/empty working-state fields (not omitted from results).

2. **test_scan_fleet_quick_valid_path_has_path_exists_true**: Register a repo with a valid git repo path, call `scan_fleet_quick`. Result should include `path_exists: True`.

3. **test_fleet_endpoint_includes_path_exists**: `GET /api/fleet` after registering a repo whose path was deleted — response repo entry has `"path_exists": false`.

4. **test_repo_detail_includes_path_exists**: `GET /api/repos/{id}` for a repo whose path is deleted — response has `"path_exists": false`.

5. **test_repo_detail_valid_path_has_path_exists_true**: `GET /api/repos/{id}` for a valid repo — response has `"path_exists": true`.

6. **test_scan_error_set_on_failure**: Trigger `run_fleet_scan` for a repo whose path is invalid (so git commands fail). After scan completes, `working_state.scan_error` is non-null for that repo.

7. **test_scan_error_cleared_on_success**: Set `scan_error` manually in working_state, then run a successful full scan. After scan, `scan_error` should be null.

8. **test_fleet_response_includes_scan_error**: `GET /api/fleet` — each repo in response has a `scan_error` key (null when no error).

9. **test_patch_repo_path_success**: `PATCH /api/repos/{id}` with `{"path": "/new/valid/path"}` returns 200 and updates the path in the DB.

10. **test_patch_repo_path_not_found**: `PATCH /api/repos/{id}` for a non-existent repo returns 404.

11. **test_patch_repo_path_invalid**: `PATCH /api/repos/{id}` with a non-existent directory path returns 400.

12. **test_concurrent_scan_409_regression**: `POST /api/fleet/scan` while a scan is already running returns 409 (regression guard for packet 08).

13. **test_dep_check_error_flag**: After `run_dep_scan_for_repo` with a repo that triggers a dep-check exception, `working_state.dep_check_error` should be true.

14. **test_dep_check_error_cleared_on_success**: Set `dep_check_error = true`, run a successful dep scan — flag should be cleared to false.

### Frontend tests (HTML template inspection)

15. **test_card_path_not_found_ui**: `GET /` HTML contains the string "Path not found" (the error text rendered in cards).

16. **test_card_scan_failed_badge_ui**: `GET /` HTML contains the string "scan failed" (the badge text).

17. **test_detail_remove_update_buttons_ui**: `GET /` HTML contains both "Remove" and "Update Path" button strings.

18. **test_offline_indicator_ui**: `GET /` HTML contains the string "offline" associated with the dep check indicator.

## Implementation Notes

### Schema Migration

Add after existing schema initialization (idempotent — wrap in try/except to handle "column already exists"):

```python
_MIGRATION_SQL = [
    "ALTER TABLE working_state ADD COLUMN scan_error TEXT DEFAULT NULL",
    "ALTER TABLE working_state ADD COLUMN dep_check_error BOOLEAN DEFAULT FALSE",
]

def run_migrations(db_path):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    for sql in _MIGRATION_SQL:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()
```

Call `run_migrations(DB_PATH)` right after `init_schema(DB_PATH)` in `main()`.

### scan_fleet_quick Changes

Replace the `return None` for missing paths with a dict that has `path_exists: False`:

```python
if not Path(path).is_dir():
    return {
        "id": repo_id,
        "name": name,
        "path": path,
        "runtime": runtime,
        "default_branch": default_branch,
        "path_exists": False,
        "has_uncommitted": False,
        "modified_count": 0,
        "untracked_count": 0,
        "staged_count": 0,
        "current_branch": None,
        "last_commit_hash": None,
        "last_commit_message": None,
        "last_commit_date": None,
    }
```

For valid repos, add `"path_exists": True` to the returned dict.

Remove the `if r is not None` filter at line 558.

### run_fleet_scan Changes

In the per-repo try/except block (both `type='full'` and `type='deps'`):

```python
try:
    # ... existing scan logic ...
    # Clear error on success:
    await db.execute(
        "UPDATE working_state SET scan_error = NULL WHERE repo_id = ?",
        (repo_id,),
    )
    scanned += 1
except Exception as exc:
    logger.error("Scan failed for %s: %s", name, exc)
    await db.execute(
        "INSERT INTO working_state (repo_id, scan_error) VALUES (?, ?) "
        "ON CONFLICT(repo_id) DO UPDATE SET scan_error = excluded.scan_error",
        (repo_id, str(exc)),
    )
    await db.commit()
```

### run_dep_scan_for_repo Changes

Track whether any ecosystem check raised an exception. After all checks:

```python
any_error = False
# In each try/except:
except Exception as exc:
    logger.error(...)
    any_error = True

# After all checks:
await db.execute(
    "UPDATE working_state SET dep_check_error = ? WHERE repo_id = ?",
    (any_error, repo_id),
)
```

### GET /api/fleet Response Shape Addition

Each repo dict in the `repos` array gains:
- `path_exists` (bool) — already set by scan_fleet_quick
- `scan_error` (string|null) — read from working_state
- `dep_check_error` (bool) — read from working_state

Update the working_state SELECT in get_fleet to include the new columns.

### PATCH /api/repos/{id}

```python
@app.patch("/api/repos/{repo_id}")
async def update_repo(repo_id: str, body: dict = Body(...), db=Depends(get_db)):
    cursor = await db.execute("SELECT id FROM repositories WHERE id = ?", (repo_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Repo not found")
    new_path = body.get("path", "").strip()
    if not new_path or not Path(new_path).is_dir():
        raise HTTPException(status_code=400, detail="Invalid path")
    resolved = str(Path(new_path).resolve())
    await db.execute("UPDATE repositories SET path = ? WHERE id = ?", (resolved, repo_id))
    await db.commit()
    return {"id": repo_id, "path": resolved}
```

### ProjectCard Error UI

In `ProjectCard`, check `repo.path_exists === false`:
- Override cardStyle borderLeft to `4px solid var(--status-red)`
- Override cardStyle background to remove freshness coloring
- Row 2: show "Path not found" in `var(--status-red)` instead of `repo.last_commit_message`

Check `repo.scan_error`:
- Render a small badge at `position: absolute; top: 8px; right: 8px` with text "scan failed"
- Badge styles: fontSize `10px`, fontFamily `var(--font-body)`, fontWeight 600, color `var(--status-red)`, background `var(--status-red-bg)`, padding `2px 6px`, borderRadius `3px`

### DetailHeader Error Buttons

When `repo.path_exists === false`, render below the header:
- "Remove" button: secondary style, `var(--status-red)` text — calls `DELETE /api/repos/{id}` then navigates to `#/fleet`
- "Update Path" button: secondary style, normal text — toggles an inline path input + "Save" button that calls `PATCH /api/repos/{id}`

### DepsTab Offline Indicator

When the repo's `dep_check_error` is true, show next to "Last checked: X ago":
- 6px circle with `var(--status-orange)` background
- "offline" text in `var(--status-orange)`, 12px `var(--font-body)`

## Acceptance Criteria

1. Repos with deleted paths appear in the fleet grid (not silently omitted).
2. Path-not-found cards show a 4px red left border (`var(--status-red)`), overriding freshness.
3. Path-not-found cards show "Path not found" in `var(--status-red)` in the commit-message row.
4. When a full scan fails for a specific repo, the card shows a "scan failed" badge at top-right.
5. The "scan failed" badge uses 10px text, `var(--status-red)` on `var(--status-red-bg)`, padding `2px 6px`, border-radius `3px`.
6. The scan-error is cleared when a subsequent scan succeeds for that repo.
7. The detail view for a path-not-found repo shows "Remove" and "Update Path" buttons.
8. "Remove" calls `DELETE /api/repos/{id}` and returns to fleet view.
9. "Update Path" allows entering a new path and calls `PATCH /api/repos/{id}`.
10. `PATCH /api/repos/{id}` validates the path is an existing directory and updates the DB.
11. `PATCH /api/repos/{id}` returns 404 for unknown repo, 400 for invalid path.
12. The deps tab shows an offline indicator (orange dot + "offline") when `dep_check_error` is true.
13. `dep_check_error` is set when any ecosystem dep check raises an exception during dep scan.
14. `dep_check_error` is cleared when all ecosystem dep checks succeed.
15. Concurrent scan rejection (409) still works (regression guard).
16. Schema migration is idempotent (running it twice does not error).
17. `GET /api/fleet` response includes `path_exists`, `scan_error`, and `dep_check_error` per repo.
18. `GET /api/repos/{id}` response includes `path_exists`.
19. All existing tests pass (no regressions).
20. `python git_dashboard.py --help` exits cleanly.

## Validation Focus Areas

- Verify that previously-skipped (missing path) repos now appear in the fleet with error state.
- Verify the red left border visually overrides freshness borders (green/yellow/orange/red).
- Verify scan_error persists across fleet refreshes (it's in working_state, not ephemeral).
- Verify the PATCH endpoint validates path existence before accepting the update.
- Verify the migration is truly idempotent by running it twice in tests.
- Run the full test suite to confirm no regressions in the existing 394+ tests.
- Start the app and verify path-not-found cards render correctly when a repo path is manually deleted.
