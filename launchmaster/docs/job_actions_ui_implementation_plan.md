# Job Actions UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make per-job actions (stop, run, delete, etc.) discoverable and reachable from the top-level job list via always-visible buttons, a kebab (⋯) menu, and a right-click context menu — with a consistent, settings-aware confirmation layer — instead of today's hover-only, off-screen icon row.

**Architecture:** All UI lives in the embedded React SPA inside the single `launchmaster` launcher file (HTML string, Babel-transpiled JSX, CDN React 18 + lucide icons). We introduce one shared action layer (`useJobActions` hook + `JOB_ACTIONS` registry) that every surface (table rows, kebab menu, context menu, detail panel, failed panel, keyboard shortcuts) calls, and one shared popover component (`JobActionMenu`) used by both the kebab button and the context menu. A small backend change makes deleting a defunct job (plist already gone) succeed instead of erroring.

**Tech Stack:** Python 3.12+ (uv-managed single-file FastAPI launcher), embedded React 18 SPA, lucide icons via CDN, pytest + Playwright for tests.

## Global Constraints

- **All work happens on a feature branch `codex/job-actions-ui`** created from up-to-date `main` (Task 0). Never commit this work directly to `main`; Task 8 finishes with a PR.
- `launchmaster` stays a **single uv-managed launcher file**; all frontend code remains inside its embedded HTML string. No new files except tests and docs. No new dependencies, no new CDN loads.
- **Apple-ness of a job is determined by `isAppleJob(job)`** (defined in Task 1), never by domain alone: orphan jobs (loaded in launchd, no plist on disk) have `domain: "unknown"` with `is_apple: true` set by label prefix — `isAppleDomain(job.domain)` misses them.
- **Canonical settings schema is snake_case** (`confirm_destructive`, `confirm_apple_modify`, `dark_mode`, `show_apple_jobs`, `poll_interval`) — matching the backend `_load_config` defaults. The React settings state adopts these keys (Task 2 migrates it off camelCase).
- **E2E tests must be order-independent.** The `server` fixture is module-scoped — one server and one persisted config for all of `test_e2e.py`. Any test that mutates settings must snapshot `GET /api/settings` and restore it in `finally` (Task 0 provides a fixture). No test may depend on a button or state another task's test created or removed.
- **No conditional skips for data availability.** Apple, failed, and plist-less jobs needed by tests come from the deterministic synthetic-jobs harness (Task 0), not from whatever the host machine happens to have loaded. (`pytest.skip` for genuinely absent tooling, e.g. Playwright not installed, remains as-is.)
- **Public repo:** no sensitive data anywhere, including test fixtures — use conspicuously synthetic labels like `com.example.fake-job`.
- **E2E tests run against the real machine's launchd.** They must NEVER complete a mutating action on a real job. Mutating API calls in E2E tests must be intercepted with `page.route(...)`, and confirmation dialogs must always be dismissed via Cancel/Esc — never the confirm button — unless the network route for that action is intercepted.
- Line numbers in this plan reference commit `3b33280` and **will drift** (another agent works in this repo concurrently). Always re-locate code by searching for the quoted identifiers (`rg -n "handleRowAction" launchmaster`), never by raw line number.
- After any edit to the `launchmaster` file, run the fleet drift guard from the monorepo root: `uv run --script tools/check_uv_headers.py` (part of exit verification; the PEP 723 header itself must not change).
- Full-suite command (from `launchmaster/`, venv per README): `.venv/bin/python -m pytest -q`. E2E only: `.venv/bin/python -m pytest tests/test_e2e.py -v`.
- Existing behavior that must not regress: bulk bar on checkbox selection, detail panel actions, delete = backup → unload → remove plist, one-step (no stop required first).

## File Structure

- Modify: `launchmaster` (single file — CSS block ~lines 660–690, React components ~lines 1270–2900, backend `_load_config`/`delete_job`/`api_delete_job`/export route, synthetic-jobs injection in the refresh path)
- Create: `tests/test_delete_job.py` (backend unit tests via module import)
- Modify: `tests/conftest.py` (synthetic-jobs wiring for the E2E server; `restore_settings` fixture)
- Modify: `tests/test_e2e.py` (new test classes per task), `tests/test_api.py` (export GET test; `test_put_settings` only if it asserts camelCase)
- This plan: `docs/job_actions_ui_implementation_plan.md`

## Current-State Map (verified against code and a live sandboxed run)

- `JobTable` renders 8 per-row icon buttons (`.row-actions`) that are `opacity: 0` until row hover, in an Actions column that overflows off-screen at ≤1280px window width (table min-width ≈ 1371px). `handleRowAction` in `JobTable` does fetch+toast, with a hard-coded confirm for delete.
- `DetailPanel` duplicates the same logic in `handleAction`/`handleDelete`. `BulkBar.bulkAction` duplicates it again. `App` passes a bespoke `onReload` into `FailedPanel`.
- `FailedPanel` rows offer only Logs / Edit / Reload — no Stop/Delete.
- `ConfirmDialog` exists (overlay click or Cancel to dismiss; no keyboard handling; global Esc handler does not clear `showConfirm`).
- Settings modal persists `confirmDestructive` and `confirmApple` (defaults `true`) via `PUT /api/settings`, but **no code reads them** — they are dead toggles.
- Shortcuts help advertises `s x r e l ? Esc-deselect`; only `n`, `/`, `Esc`(close panels) are implemented.
- Backend `delete_job(label, domain, plist_path)` returns failure if the plist file is missing, so a defunct job (uninstalled app, plist gone, still loaded in launchd) cannot be deleted from the UI. `api_delete_job` additionally early-returns before `delete_job` when `plist_path` is falsy.
- Icons render via `Icon name="..."` → `lucide.icons[name]` with kebab-case names (`'trash-2'`, `'refresh-cw'`). For the kebab button use `'more-vertical'`; if it doesn't render in the pinned CDN lucide build, fall back to `'ellipsis-vertical'` (verify in browser console: `Object.keys(lucide.icons).filter(k => /vert/i.test(k))`).
- Every job dict includes an `is_apple` boolean: plist-backed jobs set it from the domain, orphans set it from the `com.apple.` label prefix while carrying `domain: "unknown"`.
- Settings schemas currently disagree: backend `_load_config`/`GET /api/settings` use snake_case; React state and `PUT` bodies use camelCase (`darkMode`, `confirmDestructive`, `confirmApple`). `PUT` does `_config.update(body)`, so a saved config accumulates both spellings.
- The `api()` fetch helper rejects only on non-2xx. Action endpoints (`start`, `stop`, …, `DELETE`) return HTTP 200 with `{"success": false, "message": ...}` on launchctl failure — the UI currently shows a **success toast for failed actions**.
- Export is broken end-to-end today: the backend route is `@app.post("/api/jobs/{label:path}/export")` but both frontend export paths trigger an anchor-click GET → 405. (The row button also fires a success toast regardless, per the previous bullet's cousin: anchor navigation bypasses `api()` entirely.)
- `.job-table thead th` is already `position: sticky; top: 0; z-index: 10; background: var(--bg-elevated)` — the Actions header cell must compose with (not override) that rule.
- The detail panel's delete closes the panel after a successful delete (`onClose()` inside its confirm callback) — the shared action layer must preserve a way for callers to react to completion.
- E2E `server` fixture: `scope="module"` (one server + one persisted config for the whole E2E module); API `server_url` fixture: `scope="session"`.

---

### Task 0: Feature branch + deterministic E2E harness

Prerequisites every later task's tests rely on: a feature branch, synthetic job data (so Apple/failed/orphan coverage never depends on the host machine), and a settings snapshot/restore fixture (so the module-scoped server's persisted config can't leak between tests).

**Files:**
- Modify: `launchmaster` (`build_job_list`: env-gated synthetic-job injection at the single choke point)
- Modify: `tests/conftest.py` (synthetic jobs file + env wiring in `_running_server`; `restore_settings` fixture)
- Test: `tests/test_e2e.py` (new class `TestSyntheticHarness`)

**Interfaces (produced):**
- Env var `LAUNCHMASTER_SYNTHETIC_JOBS` = path to a JSON file containing a list of job dicts. When set, the backend appends these dicts to the job list **inside `build_job_list` itself** (at the end, after real discovery). This is the single choke point through which all three cache rebuild paths flow — lifespan startup, `_refresh_jobs`, and `_poll_loop` all call `build_job_list` directly — so injecting anywhere else (e.g. only in `_refresh_jobs`) would make synthetic jobs absent at startup or washed away by the next poll cycle. Respect the function's `include_apple` parameter for synthetic jobs with `is_apple: true`. Test-only, env-gated, documented with a comment at the injection site; never set outside tests. Synthetic dicts must carry every field a real job dict has (copy the orphan-assembly field list from the launcher) so the frontend renders them indistinguishably.
- `conftest.py` writes the synthetic file into the E2E server's isolated `LAUNCHMASTER_HOME` and sets the env var in `_running_server` **only for the E2E server fixture** (API-suite server stays synthetic-free so existing launchctl-comparison tests keep passing).
- Three synthetic jobs (labels are conspicuously fake, public-repo rule):
  1. `com.example.synthetic-idle` — `domain: "user-agent"`, `is_apple: false`, loaded, enabled, `last_exit: 0`, a real-looking `plist_path` inside `LAUNCHMASTER_HOME` (write an actual tiny plist file there so export/delete flows have a target).
  2. `com.apple.example-synthetic` — `domain: "unknown"`, `is_apple: true`, `plist_path: null`, loaded (the orphan-Apple shape that motivates `isAppleJob`).
  3. `com.example.synthetic-failed` — `domain: "user-agent"`, `is_apple: false`, loaded, enabled, `pid: null`, `last_exit: 78` (drives the failed-jobs panel deterministically).
- `restore_settings` (function-scoped fixture): GETs `/api/settings` before the test, PUTs the snapshot back after, regardless of outcome. Every settings-mutating test takes it.

- [ ] **Step 1: Create the branch.** `git checkout -b codex/job-actions-ui` (from up-to-date `main`).
- [ ] **Step 2: Commit the plan alone — required first commit.** `git add docs/job_actions_ui_implementation_plan.md && git commit -m "docs: job actions UI implementation plan"`. Nothing else may be in this commit; the harness work comes after (repo convention: plan committed first, as on prior `codex/...` branches).
- [ ] **Step 3: Baseline.** Run the full suite: `.venv/bin/python -m pytest -q` → record the pass count.
- [ ] **Step 4: Write failing E2E test** (`TestSyntheticHarness`): with the harness active, the job table (Apple toggle on, search for `synthetic`) shows all three labels above; the failed panel shows `com.example.synthetic-failed`; searching `com.apple.example-synthetic` with the Apple toggle ON shows the orphan. Also assert the synthetic jobs are still present after a WS poll cycle (`page.wait_for_timeout` past the poll interval, rows still there — catches injection at the wrong layer).
- [ ] **Step 5: Run** `-k TestSyntheticHarness` → FAIL (no injection exists).
- [ ] **Step 6: Implement** the `build_job_list` injection + conftest wiring + `restore_settings`.
- [ ] **Step 7: Run** the class, then the **full suite** — API-suite tests that compare against real `launchctl` output must be unaffected (they use the separate session-scoped server without the env var).
- [ ] **Step 8: Commit.** `git add launchmaster tests && git commit -m "test: deterministic synthetic-jobs harness and settings-restore fixture"`

### Task 1: Shared job-action layer (`JOB_ACTIONS` + `useJobActions`)

Behavior-neutral refactor: one implementation of "perform action on job", called by every existing surface. No visual changes yet. This satisfies the no-duplicate-logic rule before we add three new action surfaces.

**Files:**
- Modify: `launchmaster` (add registry + hook near the `api()` helper; refactor `JobTable.handleRowAction`, `DetailPanel.handleAction`/`handleDelete`, `App`'s `FailedPanel onReload`)
- Test: `tests/test_e2e.py` (new class `TestSharedActions`)

**Interfaces (produced — later tasks depend on these exact names):**

```js
// Registry: one entry per action. `kind` decides dispatch:
//   'api'    → POST /jobs/{label}/{endpoint}  (or DELETE /jobs/{label} for delete)
//   'nav'    → open detail panel on a tab (edit / logs / info)
//   'export' → trigger plist file download (existing anchor-click technique)
const JOB_ACTIONS = {
  'start':    { label: 'Start',    icon: 'play',        kind: 'api', mutating: true },
  'stop':     { label: 'Stop',     icon: 'square',      kind: 'api', mutating: true },
  'run-now':  { label: 'Run Now',  icon: 'zap',         kind: 'api', mutating: true },
  'reload':   { label: 'Reload',   icon: 'refresh-cw',  kind: 'api', mutating: true },
  'enable':   { label: 'Enable',   icon: 'toggle-left', kind: 'api', mutating: true },
  'disable':  { label: 'Disable',  icon: 'toggle-right',kind: 'api', mutating: true },
  'load':     { label: 'Load',     icon: 'log-in',      kind: 'api', mutating: true },
  'unload':   { label: 'Unload',   icon: 'log-out',     kind: 'api', mutating: true },
  'edit':     { label: 'Edit',     icon: 'pencil',      kind: 'nav', tab: 'edit' },
  'logs':     { label: 'Logs',     icon: 'file-text',   kind: 'nav', tab: 'logs' },
  'info':     { label: 'Details',  icon: 'info',        kind: 'nav', tab: 'info' },
  'export':   { label: 'Export',   icon: 'download',    kind: 'export' },
  'delete':   { label: 'Delete',   icon: 'trash-2',     kind: 'api', mutating: true, danger: true },
};

// Apple-ness helper (module scope) — the ONLY way any code decides a job is Apple's.
// Orphans have domain "unknown" but is_apple true; domain check is the fallback for
// any dict lacking the field.
function isAppleJob(job) { return job.is_apple === true || isAppleDomain(job.domain); }

// Hook defined at module scope, instantiated ONCE in App and passed down as `runAction`.
// openDetail(job, tab) is App's existing handleRowClick.
function useJobActions({ addToast, setShowConfirm, settings, openDetail }) {
  // returns runAction(job, actionId) -> Promise<{ok: boolean, cancelled?: boolean}>
}
```

**`runAction` completion contract (binding):** the returned promise resolves `{ok: true}` only after the action's API call succeeded; `{ok: false}` on API failure (toast already shown); `{ok: false, cancelled: true}` if a confirmation dialog was dismissed. When a confirm dialog gates the action, the promise resolves **after** the user's choice — implement by wrapping the dialog in a promise: the `showConfirm` object gains an optional `onCancel` callback, and `App`'s ConfirmDialog wiring invokes it on every cancel path (button, overlay, Esc) before clearing state. This is what lets the detail panel keep its close-after-successful-delete behavior: `runAction(job, 'delete').then(r => { if (r.ok) onClose(); })`.

**`success: false` handling (binding):** the `api()` helper additionally rejects when the parsed JSON body has `success === false` (`throw new Error(data.message || 'Operation failed')`). Responses without a `success` key (`/jobs` list, plist content, logs) are unaffected. This fixes the existing bug where a 200-with-`success: false` launchctl failure shows a success toast — from every surface, including the bulk bar. E2E route stubs must therefore always fulfill with `{"success": true, ...}` (the snippets in this plan already do).

**Export fix (this task):** change the backend route to `@app.get("/api/jobs/{label:path}/export")` — export is an idempotent read; the anchor-click download the frontend already performs is the correct client. Both frontend export paths currently 405. Keep the anchor technique (it must bypass `api()` for the file download), routed through the `'export'` kind in the registry.

Success/error toast texts must match today's strings (e.g. `'Stopped ' + job.label`, `'Running ' + job.label + ' (one-shot)...'`, `'Deleted ' + job.label`, `'Failed to delete: ' + err.message`) so existing user expectations and any string-matching tests keep working. In this task, delete keeps its current unconditional confirm (Task 2 makes it policy-driven).

- [ ] **Step 1: Write failing E2E test.** Add `TestSharedActions` to `tests/test_e2e.py`. Use Playwright route interception so no real job is mutated — this is the load-bearing pattern for all action tests in this plan:

```python
class TestSharedActions:
    def test_row_stop_calls_stop_endpoint(self, server, page):
        """Clicking a row Stop button issues POST .../stop (intercepted, not real)."""
        calls = []
        page.route(
            re.compile(r".*/api/jobs/.*/stop$"),
            lambda route: (calls.append(route.request.url),
                           route.fulfill(status=200, content_type="application/json",
                                         body=json.dumps({"success": True, "message": "ok"}))),
        )
        page.goto(server, wait_until="networkidle")
        row = page.locator(".job-table tbody tr").first
        row.hover()
        row.locator("button[title^='Stop']").click()
        expect(page.locator(".toast.success")).to_be_visible()
        assert len(calls) == 1
```

This passes against current code — that is fine; it is the regression harness for the refactor. Additionally assert the single-implementation property with a source-level check (regression test for the duplication itself):

```python
    def test_no_duplicate_action_fetch_logic(self):
        """Action fetch+toast logic exists once (useJobActions), not per-component."""
        src = LAUNCHMASTER_SCRIPT.read_text()          # reuse conftest's path constant
        assert src.count("'/run-now'") + src.count('"/run-now"') <= 1, (
            "run-now endpoint string appears in multiple frontend call sites; "
            "all surfaces must go through useJobActions"
        )
```

(Adjust the exact assertion to whatever distinctive string the final implementation centralizes — the intent is: the per-action endpoint dispatch appears exactly once. `BulkBar` is exempt until its Task 2 refactor; scope the assertion accordingly, e.g. count occurrences of `"/jobs/' + label + '/"`-style row/detail dispatch.)

Additional failing tests in this class (use synthetic jobs from Task 0 — search for the label first so the target row is deterministic):
  - **Failure toast on `success: false`:** intercept the stop route to fulfill `200` with `{"success": false, "message": "boot-out failed"}`; click Stop on `com.example.synthetic-idle`; expect an **error** toast containing "boot-out failed" and no success toast. (Fails against current `api()`.)
  - **Export works:** open `com.example.synthetic-idle`'s **detail panel** and click its Export Plist button (this control survives Task 3's row-layout replacement; the synthetic job's real plist file in `LAUNCHMASTER_HOME` makes the response deterministic); assert the resulting request to `/api/jobs/.../export` returns status 200 with a `Content-Disposition` attachment header (use `page.expect_download()` or capture via `page.on("response")`). (Fails today: 405.) Also add an API-level test in `tests/test_api.py`: GET export for a nonexistent label returns 404 (no real-job export there — the API server has no synthetics and host jobs are not guaranteed exportable).
  - **Detail panel closes after successful delete:** open `com.example.synthetic-idle`'s detail panel, intercept DELETE to fulfill success, click Delete Job → Confirm → panel closes (`.detail-panel.open` count 0). Safe: the route never reaches the backend.

- [ ] **Step 2: Run the new tests.** `.venv/bin/python -m pytest tests/test_e2e.py -k TestSharedActions -v`. Expected: the first interception test PASSES; duplication, failure-toast, export, and close-after-delete tests FAIL.
- [ ] **Step 3: Implement** `isAppleJob`, the `api()` `success: false` rejection, the export route POST→GET, and `JOB_ACTIONS` + `useJobActions` with the completion contract; refactor `JobTable` (drop its `handleRowAction`, receive `runAction` prop), `DetailPanel` (its `handleAction`/`handleDelete` become `runAction` calls; close-after-delete via the `{ok}` result; keep its extra buttons Enable/Disable/Load/Unload/Export wired through the hook), and `App`'s `FailedPanel onReload` (becomes `(j) => runAction(j, 'reload')`). `App` instantiates the hook once. Keep `BulkBar` untouched for now.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_e2e.py -k TestSharedActions -v` → all PASS, then the full E2E file `.venv/bin/python -m pytest tests/test_e2e.py -q` → no regressions (all pre-existing tests pass).
- [ ] **Step 5: Commit.** `git add launchmaster tests && git commit -m "refactor: centralize job actions; fix success:false toasts and export method"`

### Task 2: Settings-aware confirmation policy

Make the two dead settings toggles real, keep delete confirmed by default, and add the promised Apple-job guard — one dialog even when two rules trigger.

**Files:**
- Modify: `launchmaster` (`useJobActions` gains the policy; `BulkBar` refactor; global Esc handling; `ConfirmDialog` keyboard support)
- Test: `tests/test_e2e.py` (new class `TestConfirmationPolicy`)

**Interfaces:**
- Consumes: `runAction`, `JOB_ACTIONS`, `isAppleJob(job)` (from Task 1 — never `isAppleDomain` directly, or orphan Apple jobs bypass the guard).
- Produces: `confirmationFor(job, actionId, settings) -> null | {title, message, danger}` — a **pure function at module scope** (unit-testable via source inspection, and the single place policy lives). `useJobActions` calls it before dispatch; `BulkBar` calls it per-selection via a bulk variant `bulkConfirmationFor(labels, jobs, actionId, settings)`.
- Produces: normalized settings keys. React state and all reads switch to the backend's canonical snake_case: `settings.poll_interval`, `settings.show_apple_jobs`, `settings.dark_mode`, `settings.confirm_destructive`, `settings.confirm_apple_modify`. The React defaults object, the dark-mode effect, the Settings modal fields, and the `PUT` body all use these keys. **Migration:** in backend `_load_config`, after merging defaults, map every legacy camelCase key from a previously saved config onto its snake_case equivalent when the snake_case key was absent from the file — the complete table: `pollInterval → poll_interval`, `showApple → show_apple_jobs`, `darkMode → dark_mode`, `confirmDestructive → confirm_destructive`, `confirmApple → confirm_apple_modify` — then drop the camelCase keys before returning; the next save persists clean snake_case. Existing `test_put_settings` in `tests/test_api.py` must still pass — update it only if it asserts camelCase echoes (per test-integrity rules, with a comment).
- Produces: `show_apple_jobs` connected to the Apple filter. Today the persisted setting and `App`'s separate `showApple` filter state are disconnected (the setting does nothing). Binding behavior: when settings load or save changes `show_apple_jobs`, `App` syncs the filter (`useEffect` on `settings.show_apple_jobs` → `setShowApple(...)`). The FilterBar's quick "Apple Jobs" chip remains a session-local override and does not write the setting back — the setting is the startup default, the chip is a transient view toggle. Add an E2E test: (`restore_settings`) PUT `show_apple_jobs: true`, reload page, Apple rows are visible without touching the chip.
- Produces: `presentConfirm(spec)` — the only way any code sets `showConfirm`. Before storing a new spec it invokes the displaced spec's `onCancel` (if one is pending), so a confirmation promise can never be orphaned by a second dialog replacing the first. All `setShowConfirm({...})` call sites go through it.

**Policy decision table (binding — `apple` below means `isAppleJob(job)`):**

| Condition | Confirm? | Dialog |
|---|---|---|
| `delete`, `confirm_destructive` ON (default) | Yes | danger, current wording |
| `delete`, `confirm_destructive` OFF | No | — |
| Any `mutating` action on an `apple` job, `confirm_apple_modify` ON | Yes | warning wording: names the job, states it is an Apple system job |
| Both rules trigger (delete `apple` job) | Yes, **one** dialog | danger; message covers both ("Apple system job" + "unload and remove the plist file") |
| Non-mutating (`edit`/`logs`/`info`/`export`) | Never | — |
| Bulk delete | Same as single delete (`confirm_destructive`); if selection includes `apple` jobs and `confirm_apple_modify` ON, message appends a count-of-Apple-jobs warning line | danger |
| Bulk start/stop/reload/enable/disable containing `apple` jobs, `confirm_apple_modify` ON | Yes, once for the batch | warning |

Also in this task (dialog ergonomics, small and colocated):
- `ConfirmDialog`: `autoFocus` the **Cancel** button (Enter must not confirm a danger dialog); component-level `onKeyDown` for `Escape` → `onCancel`.
- Global Esc priority in `App`'s keydown handler: `showConfirm` → close it and return; else close detail/create/settings panels; else clear checkbox selection (`setSelected([])`). This makes the advertised "Esc … deselect" true.
- `BulkBar` refactor: replace its inline fetch loop's confirm logic with `bulkConfirmationFor`; the per-job fetch loop itself may stay in `BulkBar` (it is batch orchestration, not per-job dispatch — but route both through one small shared `apiJobAction(label, actionId)` helper the hook also uses, so endpoint construction exists once).

- [ ] **Step 1: Write failing E2E tests** (`TestConfirmationPolicy`). All destructive flows intercepted or cancelled. **Order-independence rules:** every scenario drives actions through the **detail panel's** buttons (open via row click on a synthetic job) — the detail panel's Stop/Delete buttons exist unchanged through every task of this plan, whereas Task 3 replaces the row-button layout and would invalidate row-button-based tests. Settings-mutating scenarios take the `restore_settings` fixture (Task 0) and use snake_case keys. Scenarios (each its own test method):
  1. Delete via detail panel on `com.example.synthetic-idle`: confirm dialog appears; press `Escape`; dialog closes; no DELETE request was made (assert via `page.route` interception recording zero calls).
  2. Confirm dialog Cancel button has focus on open (`page.evaluate("document.activeElement.textContent")` → `"Cancel"`).
  3. (`restore_settings`) With `confirm_destructive` set false via API then page reload: detail-panel Delete issues DELETE immediately (intercepted) with **no** dialog.
  4. Apple guard on the orphan shape the domain check misses: enable the Apple Jobs toggle, open `com.apple.example-synthetic` (synthetic, `domain: "unknown"`, `is_apple: true`), click its Stop; expect a confirm dialog mentioning "Apple"; Cancel; zero intercepted calls. Deterministic — no skip.
  5. Esc with rows selected (no dialog/panels open) clears the selection (bulk bar disappears).
- [ ] **Step 2: Run them** — expect FAIL (no policy, Esc doesn't clear dialog/selection, dialog not focused). `.venv/bin/python -m pytest tests/test_e2e.py -k TestConfirmationPolicy -v`
- [ ] **Step 3: Implement** the settings key normalization + `_load_config` migration, then `confirmationFor` / `bulkConfirmationFor` (using `isAppleJob`), wire into `useJobActions` and `BulkBar`, add dialog keyboard/focus behavior and the Esc priority chain.
- [ ] **Step 4: Run** the class, then full E2E file. All PASS; pre-existing `test_detail_panel_escape_closes` must still pass (priority chain must not break it).
- [ ] **Step 5: Commit.** `git commit -m "feat: settings-aware confirmation policy with Apple-job guard"`

### Task 3: Always-visible row actions, kebab menu, sticky Actions column

The core discoverability fix (Option B).

**Files:**
- Modify: `launchmaster` (CSS `.row-actions` block; `JobTable` row markup; new `JobActionMenu` component; `App` menu state)
- Test: `tests/test_e2e.py` (new class `TestRowActionsAndKebab`)

**Interfaces:**
- Consumes: `runAction`, `JOB_ACTIONS`, `openDetail`.
- Produces:
  - `App` state: `actionMenu` = `null | {label: string, x: number, y: number}`; `openActionMenu(job, x, y)` passed down to `JobTable` (and later `FailedPanel`). App resolves the job fresh each render: `jobs.find(j => j.label === actionMenu.label)` — if it disappears (WS refresh removed it), the menu unmounts automatically. **Menu state lives in App keyed by label, never by row element or index** — the WS feed re-sorts/replaces rows every few seconds and must not orphan or misbind an open menu.
  - `JobActionMenu({ job, x, y, onClose, runAction, openDetail })` — rendered via `ReactDOM.createPortal(..., document.body)`.

**Row layout (binding):** the Actions cell shows exactly three always-visible buttons — Run Now (`zap`), Stop (`square`), kebab (`more-vertical`) — replacing the 8 hover-only icons. Buttons keep the `title` tooltips. At-rest style: visible (e.g. `opacity: .6`, full opacity on row hover); delete the `opacity: 0` rule. Column: header `Actions`, `width: 110`, and **sticky**:

```css
/* Body cells: sticky right only. */
.job-table td.actions-cell {
  position: sticky; right: 0; z-index: 1;
  background: var(--bg-surface);           /* sticky cells cannot be transparent */
  box-shadow: -10px 0 10px -10px rgba(0,0,0,0.5);  /* scroll-edge affordance */
}
.job-table tbody tr:hover td.actions-cell { background: var(--bg-hover); }
.job-table tbody tr.selected td.actions-cell { background: /* match tr.selected bg */; }

/* Header cell: COMPOSE with the existing `.job-table thead th` rule, which is
   already sticky top with z-index 10 and background var(--bg-elevated).
   Add `right: 0` (sticky on both axes) and raise z-index above both the body
   sticky cells (1) and sibling header cells (10). Do NOT redeclare background
   or top — the base rule owns them. */
.job-table thead th.actions-col { right: 0; z-index: 11; }
```

Executor: read the existing `tr:hover` / `tr.selected` / `.apple-row` / `.status-failed` row background rules in the CSS block and mirror each on `td.actions-cell` so the sticky cell never visibly "tears" from its row. `background: inherit` does NOT work on sticky table cells — set explicit values. Verify the corner behavior manually: when scrolled both down and right, the Actions header cell must stay pinned in the corner above body cells.

**Menu content (grouped, state-aware toggles):**
1. Start, Stop, Run Now, Reload
2. `job.enabled ? 'Disable' : 'Enable'`, `job.loaded ? 'Unload' : 'Load'` (dispatch the matching actionId)
3. Edit, Logs, Details
4. Export
5. Delete (danger styling — red text; the confirm policy from Task 2 applies unchanged)

**Menu behavior (load-bearing):**
- Position `position: fixed; left: x; top: y` with viewport flip: after mount, measure with `getBoundingClientRect()`; if `bottom > innerHeight` set `top = y - height`; if `right > innerWidth` set `left = x - width`. (Render invisible → measure → position in one `useLayoutEffect` to avoid flicker.)
- Close on: item click (after dispatch), `mousedown` outside (document listener), `Escape`, window `resize`, and any `scroll` (capture-phase listener on `document` — the table container scrolls, not the window).
- Kebab click: `e.stopPropagation()` (don't open the detail panel), open at the button's rect (`rect.left, rect.bottom + 4`).
- The global Esc priority chain (binding, final order): **confirm dialog → action menu → detail/create/settings panels → clear selection.** The dialog outranks the menu: a menu item click closes the menu before its confirmation appears, but if both are ever visible, Esc must dismiss the dialog (resolving its promise as cancelled via `onCancel`) and leave everything beneath it untouched.

- [ ] **Step 1: Write failing E2E tests** (`TestRowActionsAndKebab`). Deterministic target: search for `com.example.synthetic-idle` first so assertions bind to a known row.
  1. Kebab is visible **without hover**: `expect(row's button[title='More actions']).to_be_visible()` immediately after load.
  2. Actions column on-screen: at default viewport, the kebab's `bounding_box()` fits within `page.viewport_size["width"]` **without any horizontal scrolling** (do not scroll before asserting).
  3. Kebab opens menu containing exactly the grouped items incl. a red Delete; click elsewhere closes it.
  4. Menu Delete → confirm dialog (Task 2 wording) → Cancel.
  5. Menu Run Now issues intercepted POST `/run-now` and closes the menu.
  6. Exactly 3 buttons per row (`.row-actions button` count == 3 within the target row).
- [ ] **Step 2: Run** `-k TestRowActionsAndKebab` → FAIL (8 hover-hidden buttons, no kebab).
- [ ] **Step 3: Implement** CSS, row markup, `JobActionMenu`, `App` menu state.
- [ ] **Step 4: Run** class + full E2E file → PASS. Manually smoke-check in a sandboxed run (`LAUNCHMASTER_HOME=$(mktemp -d) ./launchmaster --no-browser`) at a narrow (~1100px) window: sticky column visible, no tearing, menu flips near the bottom row.
- [ ] **Step 5: Commit.** `git commit -m "feat: always-visible row actions with kebab menu and sticky column"`

### Task 4: Right-click context menu (Option C)

**Files:**
- Modify: `launchmaster` (`JobTable` row `onContextMenu`)
- Test: `tests/test_e2e.py` (new class `TestContextMenu`)

**Interfaces:** Consumes `openActionMenu(job, x, y)` from Task 3 — the context menu IS `JobActionMenu`, opened at the cursor. No new component.

- [ ] **Step 1: Write failing E2E tests:** right-click a row (`row.click(button="right")`) → menu appears at/near the pointer with the same items; browser-native menu suppressed (assert our `.job-action-menu` is visible); `Escape` closes it; right-clicking a second row moves the menu to that row's job (menu shows only once — `count() == 1`).
- [ ] **Step 2: Run** `-k TestContextMenu` → FAIL.
- [ ] **Step 3: Implement:** on `<tr>` add `onContextMenu={e => { e.preventDefault(); openActionMenu(job, e.clientX, e.clientY); }}`. Do not alter checkbox selection on right-click.
- [ ] **Step 4: Run** class + full E2E → PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: right-click context menu on job rows"`

### Task 5: Failed panel gets full actions

**Files:**
- Modify: `launchmaster` (`FailedPanel` row actions)
- Test: `tests/test_e2e.py` (extend existing failed-panel coverage or new class `TestFailedPanelActions`)

**Interfaces:** Consumes `openActionMenu`. `FailedPanel` gains props `openActionMenu` and (already from Task 1) routes Reload through `runAction`.

- [ ] **Step 1: Write failing E2E test:** the failed panel deterministically contains `com.example.synthetic-failed` (Task 0 harness — no skip); its `.failed-job-row` contains a kebab button that opens the shared menu with Stop and a red Delete. Keep the existing Logs/Edit/Reload text buttons — this is an addition, not a swap.
- [ ] **Step 2: Run** → FAIL (kebab does not exist yet; the row itself must already be visible or Task 0 has regressed).
- [ ] **Step 3: Implement:** append a kebab button (same 26px style, always visible) to `.failed-job-actions`, `e.stopPropagation()`, open at button rect.
- [ ] **Step 4: Run** class + full E2E → PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: full action menu from failed-jobs panel"`

### Task 6: Real keyboard shortcuts

Make the advertised shortcuts true, and update the help text where behavior differs.

**Files:**
- Modify: `launchmaster` (`App` keydown handler; `SettingsModal` shortcuts help text)
- Test: `tests/test_e2e.py` — **extend the existing `TestKeyboardShortcuts` class** (it already exists with `test_n_opens_create_modal` and `test_slash_focuses_search`; defining a second class with the same name would silently shadow and drop those tests — add methods to the existing class only).

**Interfaces:** Consumes `runAction`, `openDetail`, `detailJob`, `selected`, `jobs`, `showConfirm`, `showCreate`, `showSettings`, `actionMenu`.

**Binding behavior:**
- **Modal guard first:** while a confirm dialog, create modal, or settings modal is open, every action shortcut (`s x r e l n ?`) is inert — early-return before target resolution. Only Esc (priority chain) and the dialog's own keys operate. Together with `presentConfirm` (Task 2) this makes an orphaned confirmation promise impossible: shortcuts can't stack a second dialog, and anything else that could must go through `presentConfirm`, which cancels the displaced one.
- Target resolution for `s x r e l`: the detail-panel job if the panel is open; else the single checkbox-selected job if `selected.length === 1`; else no-op with `addToast('warning', 'Select one job or open its details first')`.
- `s` → start, `x` → stop, `r` → reload, `e` → `openDetail(job,'edit')`, `l` → `openDetail(job,'logs')`. All action dispatch goes through `runAction` (confirmation policy applies — e.g. `x` on an Apple job prompts).
- `?` (i.e. `e.key === '?'`) → open the Settings modal (which contains the shortcuts reference). Update help text from "Toggle shortcuts help" to "Open settings & shortcuts".
- Guards: ignore when `e.metaKey || e.ctrlKey || e.altKey`, and keep the existing INPUT/TEXTAREA/SELECT early-return.
- Update the help grid: `Esc` line becomes "Close menu/dialog/panel, then deselect" (matching the Task 2/3 priority chain).

- [ ] **Step 1: Write failing E2E tests** (added to the existing `TestKeyboardShortcuts` class): all selection-based scenarios target `com.example.synthetic-idle` (search for it, check its checkbox — non-Apple, so no Apple-guard dialog interferes): (a) with exactly that row checked, press `l` → detail panel opens on Logs tab; (b) with nothing selected, press `x` → warning toast, no dialog, no intercepted call; (c) with that row checked, press `x` with the stop route intercepted → intercepted call happens; (d) press `?` → settings modal visible; (e) modal guard: open the synthetic job's delete confirm (via detail panel), press `x` → no new dialog, no intercepted stop call, original dialog still visible; Cancel it.
- [ ] **Step 2: Run** `-k TestKeyboardShortcuts` → FAIL.
- [ ] **Step 3: Implement** handler + help text.
- [ ] **Step 4: Run** class + full E2E → PASS (existing `test_n_opens_create_modal`, `test_slash_focuses_search` must still pass).
- [ ] **Step 5: Commit.** `git commit -m "feat: implement advertised keyboard shortcuts"`

### Task 7: Backend — deleting a defunct job succeeds

A job whose plist file is already gone (uninstalled app) currently cannot be deleted: `delete_job` returns `success: False` before unloading. Fix both layers.

**Files:**
- Modify: `launchmaster` (`delete_job`, `api_delete_job`)
- Create: `tests/test_delete_job.py`

**Interfaces:**
- `delete_job(label, domain, plist_path) -> Dict` keeps its signature. New behavior: if `plist_path` is falsy **or** the file does not exist, still call `await unload_job(label, domain, plist_path)`; return `{"success": True, "message": f"Unloaded {label}; plist file was already absent (nothing to back up)"}` when the unload reports success, else propagate the unload failure result. The existing happy path (backup → unload → remove) is unchanged.
- `api_delete_job`: remove its early-return for missing `plist_path`; always delegate to `delete_job` and refresh on success.

**Test harness (load-bearing — use the fleet's shared loader, not a hand-rolled one):**

The monorepo already ships `tools/testkit.py` with `load_launcher(path)` for importing extensionless launchers without executing their `__main__` block — it is the established pattern (harscope, storage_monitor, mls-tracker, expense_dock all use it). Import idiom (copy from `mls-tracker/conftest.py`):

```python
import sys
from pathlib import Path

UTILITIES_ROOT = Path(__file__).resolve().parent.parent.parent   # monorepo root
sys.path.insert(0, str(UTILITIES_ROOT))
from tools.testkit import load_launcher
```

Environment must be set via pytest's `monkeypatch` **before** the import (module-level code resolves the runtime home) and is then restored automatically — never mutate `os.environ` directly:

```python
@pytest.fixture
def lm_module(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUNCHMASTER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("UTILITIES_TESTING", "1")
    return load_launcher(Path(__file__).resolve().parent.parent / "launchmaster")
```

Executor: before relying on this, read the launcher's module-level code and confirm import does not start the server or open a browser (only `main()` under `__main__` should do that) and that the runtime-home resolution honors `LAUNCHMASTER_HOME` at import time. If module-level side effects exist beyond creating the runtime home directory, isolate or monkeypatch them and note it in the test docstring. Monkeypatch `mod.unload_job` with an async stub recording its calls (via `monkeypatch.setattr`).

**Test cases (each its own test; all plists synthetic under `tmp_path`, label `com.example.fake-job`):**
1. Happy path: real temp plist → success True, file removed, backup file exists in the runtime home's backup dir, unload stub called once.
2. Plist path points to a nonexistent file → success True, unload stub called once, message mentions the plist was absent, no backup created.
3. Unload stub returns `{"success": False, "message": "boot-out failed"}` with missing plist → overall result success False, message propagated.
4. Permission denied on remove (make the plist's parent dir read-only via `chmod 0o500`, restore in `finally`) → success False, "Permission denied" in message.
5. **Endpoint level — proves the `api_delete_job` early return is gone** (calling `delete_job` directly cannot): monkeypatch `mod._find_job` to return `{"label": "com.example.fake-job", "plist_path": None, "domain": "unknown"}`, monkeypatch `mod.delete_job` with an async stub recording its arguments and returning `{"success": True, "message": "ok"}`, monkeypatch `mod._refresh_jobs` with an async no-op; `asyncio.run(mod.api_delete_job("com.example.fake-job"))` → assert `delete_job` was called once **with `plist_path=None`** and the result propagated. Against current code this test fails because the early return means `delete_job` is never called. (No `TestClient`/httpx — direct coroutine call keeps dev deps unchanged.)

- [ ] **Step 1: Write the failing tests** (`tests/test_delete_job.py`, cases above).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_delete_job.py -v` → cases 2, 3, and 5 FAIL against current code (cases 1 and 4 pass).
- [ ] **Step 3: Implement** the `delete_job` / `api_delete_job` changes.
- [ ] **Step 4: Run** the file → all PASS. Also confirm the frontend delete confirm message still reads correctly for this case (generic "unload and remove the plist file" wording is acceptable; no UI change required).
- [ ] **Step 5: Commit.** `git commit -m "fix: allow deleting defunct jobs whose plist is already gone"`

### Task 8: Exit verification and documentation

**Files:**
- Modify: `README.md` (only if run/test commands changed — they should not have), `docs/job_actions_ui_implementation_plan.md` (check off tasks)

- [ ] **Step 1: Full suite** from `launchmaster/`: `.venv/bin/python -m pytest -q`. Every test passes — report any failure verbatim and fix before proceeding; no category skipped (E2E included).
- [ ] **Step 2: Fleet drift guard** from the monorepo root: `uv run --script tools/check_uv_headers.py` → clean.
- [ ] **Step 3: Duplicate-logic exit check:** `rg -n "'/jobs/' \+" launchmaster` (and equivalent template-literal forms) — per-job endpoint construction must appear only inside the shared helper from Tasks 1–2. If a stray copy exists, refactor before declaring done.
- [ ] **Step 4: Manual smoke** in a sandboxed instance (`LAUNCHMASTER_HOME=$(mktemp -d) ./launchmaster --no-browser`): kebab + context menu + delete-cancel on a real (Apple-filtered-out) row at 1100px and 1600px widths; verify sticky column (including the header corner when scrolled both axes) and menu flip.
- [ ] **Step 5: Tracking check** (on `codex/job-actions-ui`): `git ls-files launchmaster tests docs | sort` — confirm `tests/test_delete_job.py` and this plan are tracked; `git diff --stat main...HEAD` matches the files this plan names (three-dot diff against the merge base — valid because all work is on the feature branch, never on `main`).
- [ ] **Step 6: Commit** any doc updates. `git commit -m "docs: check off job actions UI plan"`
- [ ] **Step 7: Hand off for merge.** Push the branch and open a PR to `main` (repo convention: squash-merge after review, as with prior `codex/...` branches). Do not merge without Kevin's review.

---

## Self-Review Checklist (run after implementation, before hand-back)

1. **Spec coverage:** plan-first commit + branch + deterministic harness (T0), kebab menu (T3), context menu (T4), always-visible + sticky actions (T3), delete confirm preserved and policy-driven (T2), failed-panel stop/delete (T5), shortcuts real incl. modal guard (T6), dead toggles wired with full snake_case migration (all five keys) and `show_apple_jobs` connected to the Apple filter (T2), `presentConfirm` prevents orphaned confirmation promises (T2/T6), Esc chain: dialog → menu → panels → deselect (T2/T3), `success: false` surfaces as error toast (T1), export method fixed and tested via the detail panel (T1), close-after-delete preserved via `runAction` result (T1), Apple guard covers plist-less orphans via `isAppleJob` (T1/T2), synthetic injection inside `build_job_list` covers startup/refresh/poll (T0), defunct-job delete incl. endpoint-level early-return coverage using `tools.testkit.load_launcher` + `monkeypatch` (T7).
2. **Type/name consistency:** `runAction(job, actionId) -> Promise<{ok, cancelled?}>`, `isAppleJob(job)`, `openActionMenu(job, x, y)`, `actionMenu.label`, `confirmationFor`, `bulkConfirmationFor`, `presentConfirm`, snake_case settings keys — identical spelling across all tasks.
3. **No placeholder scan:** no TBD/TODO in shipped code or tests.
4. **Safety re-check:** no E2E test clicks a confirm button without an intercepted route; no real job mutated; synthetic-job injection is env-gated and off outside tests; settings-mutating tests all take `restore_settings`.
5. **Order-independence re-check:** run the E2E file twice, once forward and once with `-p no:randomly --lf`-style spot checks (`pytest tests/test_e2e.py -k "TestConfirmationPolicy or TestRowActionsAndKebab" -v` in isolation) — every class must pass when run alone. Confirm no test class name collides with an existing one (`rg "^class Test" tests/test_e2e.py | sort | uniq -d` → empty).
