# Model View Picker and Tooltip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Add model results from being clipped and add an exact, all-model hover readout to numeric Models-view timelines.

**Architecture:** Keep the existing no-build Preact/htm/uPlot SPA and backend contracts. Move the typeahead list across the clipping boundary through a short-lived body-level Preact portal with deterministic viewport placement; add a self-contained uPlot plugin that builds and positions a safe DOM tooltip from the existing axis and series arrays.

**Tech Stack:** Python 3.11+ test suite; vendored Preact 10.29.8, preact/hooks, htm 3.1.1, and uPlot 1.6.32; hand-written JavaScript and CSS; no new dependencies or network access.

---

## Grounding and invariants

- Approved spec: `docs/superpowers/specs/2026-08-24-model-view-picker-and-tooltip-design.md`.
- Work on the existing normal branch `codex/model-view-picker-tooltips`; do not create a worktree.
- Repository-specific override: the generic Superpowers workflows name `using-git-worktrees`, but the user's explicit instruction and the utilities-public PKM workflow rule require a normal feature branch in this checkout. This override is intentional and applies to every implementer/reviewer.
- Execution for this effort is `superpowers:subagent-driven-development`, not inline `executing-plans`: one fresh implementer for each implementation task, followed by spec review and then code-quality review before advancing.
- Read `README.md`, the approved spec, and the project `AGENTS.md` before editing.
- Current focused baseline: `source .venv/bin/activate && pytest tests/test_browse_offline.py -q` reports `67 passed`.
- Public-repository rule: inspect every staged filename and staged diff for private or sensitive data before each commit.
- All Python commands run inside `.venv`; do not use system/Homebrew Python directly.
- Preserve the single-file frontend architecture in `model_sentinel/browse/assets/app.js` and `app.css`. Do not introduce npm, a build step, a CDN, a new vendored library, or an API change.
- Preserve uPlot stepped lines, synchronized cursor key `ms-browse`, drag zoom, date-range hash writes, theme recreation, resize behavior, legend focus, event-rail cursor movement, and cleanup.
- Use DOM APIs and `textContent` for dynamic tooltip content. Do not build user/provider/model-derived markup with `innerHTML`.
- The installed standalone at `~/Library/Scripts/model-sentinel` remains untouched on this feature branch.

## File map

| File | Responsibility in this change |
|---|---|
| `model_sentinel/browse/assets/app.js` | Portal lifecycle, typeahead geometry, picker wiring, exact-value formatting, uPlot tooltip plugin and TimelinePanel integration. |
| `model_sentinel/browse/assets/app.css` | Fixed typeahead overlay and chart tooltip layout, viewport bounds, z-order, theme-consistent presentation. |
| `tests/test_browse_offline.py` | Existing offline/frontend source-contract suite; add focused regression contracts for portal lifecycle, placement, accessible picker wiring, tooltip content, exact values, and cleanup. |
| `tests/model_view_validation_fixture.py` | Conspicuously synthetic, executable fixture builder for deterministic live browser validation outside the repository. |
| `tests/test_model_view_validation_fixture.py` | Verifies the validation home contains eight searchable models, close numeric values, missing observations, and several timestamps. |
| `docs/superpowers/specs/2026-08-24-model-view-picker-and-tooltip-design.md` | Binding behavior; change only if implementation uncovers a genuine contradiction, and report that before proceeding. |

## Mandatory subagent review gate

After each implementation Task 0, 1, and 2:

1. The task's fresh implementer follows TDD, runs focused and complete tests, self-reviews, audits the public diff, and commits.
2. The coordinator dispatches a fresh spec-compliance reviewer for the exact task commit range. If it finds a gap or extra scope, the same implementer fixes it and the same spec reviewer re-reviews.
3. Only after spec approval, the coordinator dispatches a fresh code-quality reviewer for the same cumulative task range. If it finds an issue, the same implementer fixes it and the same quality reviewer re-reviews.
4. The next task does not begin until both reviewers approve with no open findings.

Task 3 is integrated live/final verification and remains with the coordinator, followed by one fresh holistic branch reviewer.

## Task 0: Build a deterministic synthetic browser-validation home

**Files:**
- Create: `tests/model_view_validation_fixture.py`.
- Create: `tests/test_model_view_validation_fixture.py`.
- Reference: `tests/browse_fixtures.py` for `Store`, normalized synthetic scrapes, and conspicuously fake naming patterns.

- [ ] **Step 1: Write failing validation-fixture tests**

Add these exact tests:

- `test_model_view_validation_home_is_isolated_and_loadable`
- `test_model_view_validation_home_has_eight_searchable_models`
- `test_model_view_validation_home_has_close_and_missing_numeric_observations`

The tests call `build_model_view_validation_home(tmp_path / "runtime")` and verify:

- it writes only below the supplied temporary directory, producing `providers.env`, `settings.env`, and `model_sentinel.db`;
- `providers.env` defines one enabled fake provider (`validation`, label `Synthetic Validation Provider`, kind `openrouter`, base URL under `example.invalid`, credential variable name `SYNTHETIC_MODEL_SENTINEL_TOKEN`) and contains no credential value;
- settings disable notifications and remain parseable by the production loader;
- the database contains five successful saved scrapes at fixed synthetic timestamps and eight models in the latest scrape, all matching the query `comparator`;
- the canonical Input series has close but unequal values that remain distinguishable through `String(value)`, includes a missing observation for one model at the middle scrape, and returns all eight rows over the shared axis;
- every provider, model, URL, value, and timestamp is conspicuously synthetic.

- [ ] **Step 2: Run exact fixture tests and verify RED**

```bash
source .venv/bin/activate
pytest tests/test_model_view_validation_fixture.py::test_model_view_validation_home_is_isolated_and_loadable -q
pytest tests/test_model_view_validation_fixture.py::test_model_view_validation_home_has_eight_searchable_models -q
pytest tests/test_model_view_validation_fixture.py::test_model_view_validation_home_has_close_and_missing_numeric_observations -q
```

Expected: collection/import fails because `tests.model_view_validation_fixture` does not exist. Confirm the failure is the missing fixture module, not a typo.

- [ ] **Step 3: Implement the fixture builder**

Create `build_model_view_validation_home(runtime_home: Path) -> Path` and a small `python -m tests.model_view_validation_fixture <runtime-home>` entry point.

Use production `Store`, `ProviderConfig`, normalization, diffing, and snapshot/change persistence patterns already centralized in `tests/browse_fixtures.py`; extract or reuse a focused test helper rather than duplicating storage SQL. Build exactly one fake OpenRouter-profile provider and five fixed UTC scrapes. The latest scrape contains `synthetic-lab/comparator-01` through `synthetic-lab/comparator-08`; omit comparator-08 only from the middle scrape so the UI has a deterministic missing point while the model remains searchable in the latest catalog. Give numeric Input observations deliberately close per-million values (for example `1.000001`, `1.000002`, and nearby distinct values) and make at least one model step across first/middle/last timestamps.

Write a minimal synthetic `providers.env` and a settings file derived from the public template with notifications disabled. Never read or copy the user's runtime home, environment credential values, or real database. Refuse a target path inside the git repository root to prevent accidental public artifacts; an existing non-empty target must fail rather than overwrite unrelated data.

- [ ] **Step 4: Verify GREEN and the executable entry point**

```bash
source .venv/bin/activate
pytest tests/test_model_view_validation_fixture.py -q
validation_home="$(mktemp -d)/model-sentinel-validation"
python -m tests.model_view_validation_fixture "$validation_home"
test -f "$validation_home/model_sentinel.db"
```

Expected: all three fixture tests pass; the command reports only the synthetic runtime path and creates the three expected files outside the repository.

- [ ] **Step 5: Run full verification, audit, and commit Task 0**

```bash
source .venv/bin/activate
pytest
git diff --cached --check
```

Stage only the two fixture files. Inspect the complete staged diff for sensitive data and unmistakably synthetic naming, then commit:

```bash
git commit -m "Add deterministic model view browser fixture"
```

- [ ] **Step 6: Pass the mandatory spec and quality review gate**

Use the review loop above for the exact Task 0 range. Reviewers must specifically reject any access to the real runtime home, real credentials, real history, nondeterministic timestamps, or fewer than eight latest models.

## Task 1: Move Add model results outside the clipping sidebar

**Files:**
- Modify: `model_sentinel/browse/assets/app.js` around `Pins` and the shared frontend helpers above it.
- Modify: `model_sentinel/browse/assets/app.css` around `.pin-search` and `.typeahead`.
- Test: `tests/test_browse_offline.py` alongside the existing Models-view frontend contracts.

- [ ] **Step 1: Add failing picker regression contracts**

Add these exact tests, reading `app.js` and `app.css` through the existing `_read_asset` helper:

- `test_model_typeahead_portal_escapes_sidebar_and_cleans_up`
- `test_model_typeahead_placement_tracks_viewport_and_anchor`
- `test_model_typeahead_preserves_listbox_keyboard_contract`
- `test_model_typeahead_css_is_fixed_bounded_overlay`

Together they require all of the following observable contracts:

- a portal/overlay helper creates a host under `document.body`, renders the supplied Preact child into it with the existing `render` primitive, and removes/unmounts it during cleanup;
- a pure placement helper consumes anchor rectangle and viewport dimensions and represents both below-input and above-input placement, horizontal clamping, width capping, and available-height capping;
- placement is recomputed on captured `scroll`, `resize`, and `ResizeObserver` notifications, with `requestAnimationFrame` coalescing and complete listener/observer/frame cleanup;
- the input exposes `aria-expanded` and `aria-controls` and Arrow Down locates the first overlaid option by the listbox id rather than `nextElementSibling`;
- the listbox keeps `role="listbox"`, result buttons keep `role="option"`, and selecting or clearing the query removes the overlay;
- `.typeahead` is a fixed-position overlay with internal vertical scrolling and z-index `90`, below the drawer (`100`), spark layer (`110`), and toast region (`120`) but above normal panels;
- no rule removes `.model-controls` scrolling or changes its sticky/max-height contract.

Keep assertions scoped to the relevant function/rule slices so an unrelated occurrence cannot satisfy them. Do not assert whole implementation bodies or incidental variable names beyond the stable helper/component interfaces chosen below.

- [ ] **Step 2: Run the new picker tests and verify RED**

Run every new test node explicitly:

```bash
source .venv/bin/activate
pytest tests/test_browse_offline.py::test_model_typeahead_portal_escapes_sidebar_and_cleans_up -q
pytest tests/test_browse_offline.py::test_model_typeahead_placement_tracks_viewport_and_anchor -q
pytest tests/test_browse_offline.py::test_model_typeahead_preserves_listbox_keyboard_contract -q
pytest tests/test_browse_offline.py::test_model_typeahead_css_is_fixed_bounded_overlay -q
```

Expected: every new node fails because the portal/placement contracts do not exist and the result list is still an absolute child of `.model-controls`. The coordinator-established pre-change file baseline is `67 passed`; do not weaken or rewrite those prior contracts. Record each failing test and relevant assertion output.

- [ ] **Step 3: Implement deterministic overlay geometry**

Add a pure helper near the other small frontend utilities, named `typeaheadPlacement(anchor, viewport, margin = 8)`. It returns numeric `left`, `width`, `maxHeight` and exactly one of `top` or `bottom`.

Binding behavior:

1. `availableBelow = viewport.height - anchor.bottom - margin` and `availableAbove = anchor.top - margin`, both clamped at zero.
2. Prefer below. Flip above only when below cannot provide a practical 160px list and above offers more space.
3. Desired desktop width is the larger of the input width and 352px; cap it at `viewport.width - 2 * margin` and never return a negative width.
4. Clamp `left` between `margin` and `viewport.width - margin - width`.
5. Cap `maxHeight` to the selected available space and 320px; never return a negative height.
6. Below uses `top = anchor.bottom`; above uses `bottom = viewport.height - anchor.top`. The unused vertical property is absent, not a stale value.

This helper is the load-bearing placement policy. Keep DOM reads and CSS-string conversion outside it so its inputs/outputs remain inspectable.

- [ ] **Step 4: Implement the body-level Preact overlay lifecycle**

Add a focused `Portal` helper using the already imported `render`, `useMemo`, and `useEffect` primitives:

- create exactly one host element for the mounted helper;
- use one host-lifecycle effect, dependent only on the stable host, to append it to `document.body` and, on component unmount only, render `null` and remove the host;
- use a separate child-render effect to call `render(children, host)` when the child changes, with no cleanup that unmounts the child between result/loading updates;
- on final unmount, leave no document-level node or listener behind;
- mark the host with a stable class or data attribute useful for CSS and live validation.

Add `TypeaheadOverlay({anchorRef, open, children})` as the geometry/lifecycle boundary. While open it measures `anchorRef.current`, calls `typeaheadPlacement`, and passes fixed-position inline geometry to a `.typeahead` listbox rendered through `Portal`. Keep the overlay absent/hidden until the first valid anchor measurement; if the anchor disappears, clear placement and hide it rather than reusing stale geometry. Schedule geometry recomputation through a single outstanding animation frame. Listen to window `resize`, captured document/window scrolling, and a `ResizeObserver` on the input; cancel the frame, disconnect, and remove every listener on close/unmount.

Do not duplicate model fetching, loading/error rendering, or pin mutation inside the overlay helper.

- [ ] **Step 5: Rewire `Pins` without changing its data behavior**

Keep the existing debounced `/api/models` request and `add(item)` behavior. Move only the result VNode into `TypeaheadOverlay`.

- Give the listbox a stable id such as `pin-results`.
- Set `aria-expanded` from the non-empty query/open state and `aria-controls` only while open.
- Replace the sibling-dependent Arrow Down lookup with `document.getElementById(listboxId)?.querySelector("button")`; prevent default and focus it when present.
- Escape still clears the query. Selection still clears the query after writing pins. Loading, API failure, no matches, display name, provider id, and model id remain unchanged.
- Do not change the pinned-model order, pin limit, dropped-pin toast, provider filtering, or debounce duration.

- [ ] **Step 6: Style the overlay and verify GREEN**

Convert `.typeahead` from sidebar-relative absolute positioning to a body-level fixed overlay. Inline geometry owns `top`/`bottom`/`left`/`width`/`max-height`; CSS owns `position: fixed`, internal `overflow-y: auto`, panel background, border, shadow, and z-index `90`. Preserve current result typography and hover/focus appearance. Ensure narrow viewports cannot create horizontal overflow.

Run:

```bash
source .venv/bin/activate
pytest tests/test_browse_offline.py -q
pytest
```

Expected: the focused suite includes the new picker contracts and passes; the complete suite has zero failures.

- [ ] **Step 7: Self-review and commit Task 1**

Review the diff specifically for leaked listeners/observers/animation frames, multiple portal hosts, stale geometry when flipping, loss of keyboard focus, z-index conflicts, and accidental sidebar changes. Stage only the three scoped files, run `git diff --cached --check`, inspect the complete staged diff for sensitive data, and commit:

```bash
git commit -m "Keep model search results outside the sidebar clip"
```

- [ ] **Step 8: Pass the mandatory spec and quality review gate**

Use the review loop above for the exact Task 1 range. Do not start Task 2 until both reviewers approve.

## Task 2: Add exact all-model hover values to numeric timelines

**Files:**
- Modify: `model_sentinel/browse/assets/app.js` around `TimelinePanel`, `cssSeries`, and small chart helpers.
- Modify: `model_sentinel/browse/assets/app.css` around `.plot-host` and uPlot styles.
- Test: `tests/test_browse_offline.py` alongside the numeric-panel and state-tooltip contracts.

- [ ] **Step 1: Add failing numeric-tooltip regression contracts**

Add these exact tests:

- `test_numeric_timeline_tooltip_preserves_exact_all_model_values`
- `test_numeric_timeline_tooltip_guards_pre_ready_cursor_and_cleans_up`
- `test_numeric_timeline_tooltip_is_pointer_gated_and_edge_bounded`
- `test_numeric_timeline_tooltip_css_keeps_eight_value_rows_visible`

Together they require:

- a `timelineTooltipValue(value)` helper returns `—` for `null`/non-finite input and `String(value)` for finite numbers, without `toFixed`, fixed significant-digit rounding, or axis formatter reuse;
- a dedicated `timelineTooltipPlugin` is passed through uPlot's `plugins` option for numeric panels only;
- the plugin reads one `u.cursor.idx`, the matching `axis[index].completed_at`, and every `items[*].values[index]` rather than selecting only one series;
- each row retains series color, model name, and a separate value element; missing models are retained rather than filtered out;
- dynamic text is assigned through `textContent`, with no tooltip `innerHTML` construction;
- pointer enter/leave gates visibility so synchronized/event-rail cursor updates do not open inactive plot tooltips;
- `setCursor` returns safely before `ready` has initialized `.u-over` and tooltip DOM;
- horizontal flip and clamping use the overlay width and cursor position; vertical placement is clamped to the plot overlay;
- tooltip `max-height` is derived from `.u-over` height, header/footer remain fixed, and the rows container scrolls vertically when eight rows cannot fit;
- plugin destruction removes pointer listeners and the tooltip node;
- CSS provides a two-column row grid whose value column is non-shrinking/right-aligned, a capped responsive width, `pointer-events: none`, hidden state, and existing theme tokens.

Scope source assertions to the tooltip helper/plugin and relevant CSS rule blocks. Keep the existing state-strip tooltip tests unchanged.

- [ ] **Step 2: Run the new tooltip tests and verify RED**

```bash
source .venv/bin/activate
pytest tests/test_browse_offline.py::test_numeric_timeline_tooltip_preserves_exact_all_model_values -q
pytest tests/test_browse_offline.py::test_numeric_timeline_tooltip_guards_pre_ready_cursor_and_cleans_up -q
pytest tests/test_browse_offline.py::test_numeric_timeline_tooltip_is_pointer_gated_and_edge_bounded -q
pytest tests/test_browse_offline.py::test_numeric_timeline_tooltip_css_keeps_eight_value_rows_visible -q
```

Expected: new tests fail because `TimelinePanel` currently has no value tooltip plugin. Record the expected failures.

- [ ] **Step 3: Implement exact value and DOM-content helpers**

Add `timelineTooltipValue(value)` with this exact policy:

```text
if value is not a finite JavaScript number: "—"
otherwise: String(value)
```

Do not use an axis tick label, `toFixed`, or locale rounding. The API has already applied aspect scaling; the tooltip reports that JSON-decoded value and shows `aspect.unit` separately.

Add small DOM helpers only where they reduce duplication. All timestamp, model name, value, unit, and missing-observation copy must be assigned with `textContent`. Use `pinParts(item.model, providers).model` for the displayed model portion and `cssSeries(pins.indexOf(item.model))` for its color. Do not omit a row when its value is missing.

- [ ] **Step 4: Implement the uPlot tooltip plugin**

Implement `timelineTooltipPlugin({aspect, axis, items, pins, providers})` returning uPlot hooks.

Required lifecycle/data flow:

1. `ready`: locate `.u-over`, append one hidden tooltip with `role="tooltip"`, and register pointer enter/leave listeners. Build stable header, independently scrollable rows container, and footer DOM.
2. Pointer enter marks the plot active; pointer leave marks it inactive and hides the tooltip.
3. `setCursor`: first guard `if (!over || !tooltip) return` because vendored uPlot 1.6.32 invokes `setCursor` during initial rendering before `ready`. Then, when active and `u.cursor.idx` is a valid axis index, set the localized header from `axis[index].completed_at`, rebuild/update one row per `items` entry from that same index, set the unit/missing footer, and prepare the tooltip for measurement. If inactive or invalid, hide it.
4. Before final measurement, cap the tooltip to `over.clientHeight` minus a small inset and cap the rows container to the remaining height after measured header/footer/separators. Header and footer do not scroll; `.timeline-tooltip-rows` owns `overflow-y: auto`. Measure again after applying those constraints.
5. Position relative to `.u-over`: start to the right and below the cursor with a small gap; flip left when the right side cannot fit; clamp left/top using the post-constraint tooltip dimensions so its bounding box remains wholly inside the plot overlay. Reposition on every cursor update even when the index has not changed.
6. `destroy`: remove listeners and the tooltip node. Cleanup must be safe if uPlot is destroyed before `ready` or before a pointer interaction.

Keep mutable plugin state inside the plugin closure, not global state or Preact state, so mouse movement does not rerender/recreate `TimelinePanel`.

- [ ] **Step 5: Integrate without disturbing chart behavior**

Pass the plugin in `TimelinePanel` through `plugins: [timelineTooltipPlugin(...)]`. Pass `providers` from `PanelStack` into `TimelinePanel`; do not broaden other component interfaces.

Do not change:

- `cursor.drag`, `cursor.sync`, `legend.show`, series paths/colors, or `spanGaps`;
- the existing `ready` and `setScale` hooks;
- pointer drag fallback handlers and zoom debounce;
- `plots.current`, event-rail cursor methods, ResizeObserver behavior, theme key, or uPlot cleanup.

- [ ] **Step 6: Style and verify GREEN**

Add narrowly scoped tooltip classes under `.plot-host`/`.u-over`:

- theme-token panel, border, shadow, and monospace typography;
- responsive capped width with a minimum usable size only when space permits;
- header/footer separators;
- row grid `minmax(0, 1fr) auto`, model ellipsis, and a non-shrinking right-aligned value;
- hidden state and `pointer-events: none`;
- fixed header/footer plus `.timeline-tooltip-rows { min-height: 0; overflow-y: auto; }`, with the plugin-supplied height caps providing deterministic eight-row containment without hiding the value column.

Run:

```bash
source .venv/bin/activate
pytest tests/test_browse_offline.py -q
pytest
```

Expected: focused tooltip contracts and all prior browser contracts pass; the full suite has zero failures.

- [ ] **Step 7: Self-review and commit Task 2**

Review for wrong-axis indexing, hidden missing rows, value rounding, unsafe HTML, tooltip activation from synchronized/event-rail cursors, edge clipping, repeated DOM nodes, missing cleanup, and regressions to zoom or chart recreation. Stage only scoped files, run `git diff --cached --check`, inspect the staged diff for sensitive data, and commit:

```bash
git commit -m "Show exact model values on timeline hover"
```

- [ ] **Step 8: Pass the mandatory spec and quality review gate**

Use the review loop above for the exact Task 2 range. Do not start integrated validation until both reviewers approve.

## Task 3: Live responsive validation and final verification

**Files:**
- No production changes expected.
- Update the approved spec or maintained browser contract only if validation exposes a genuine documented-contract mismatch; otherwise leave docs unchanged.

- [ ] **Step 1: Run the source browser against isolated synthetic history**

From the repository with `.venv` active, create a disposable runtime outside the repository, populate it with Task 0's deterministic fixture, and start the source command on an ephemeral port without auto-opening:

```bash
source .venv/bin/activate
validation_parent="$(mktemp -d)"
validation_home="$validation_parent/runtime"
python -m tests.model_view_validation_fixture "$validation_home"
MODEL_SENTINEL_HOME="$validation_home" ./model-sentinel browse --no-open --port 0
```

Use the printed local URL. Do not read, copy, or run against the default/real runtime home, database, provider configuration, or credentials. Run the server in a controllable terminal session. After the browser checks, send `Ctrl-C`, verify that the process exits and the port is released, then remove only the exact non-empty `validation_parent` returned by `mktemp` after confirming it is outside the repository.

- [ ] **Step 2: Validate the picker at wide and narrow widths**

Using the browser-control workflow, reproduce both user states:

1. no pinned models, query with multiple matches;
2. one pinned model plus the long aspect list, query with multiple matches.

At a desktop width comparable to the supplied screenshots and at a narrow width at or below the 48rem breakpoint, verify:

- multiple results are visible in both states;
- the overlay is not clipped by the sidebar, viewport, or neighboring panels;
- long identifiers remain readable through internal scrolling;
- below/above placement and horizontal clamping respond to scroll/viewport space;
- Arrow Down focuses the first result, Escape closes, and click selection pins and closes;
- no orphan overlay remains after view change or component unmount.

Capture concise evidence (DOM geometry and temporary screenshots) using only the synthetic fixture. Do not add screenshots or browser artifacts to this public repository.

- [ ] **Step 3: Validate numeric tooltips**

Select one, several, and exactly all eight synthetic comparator models with the Input aspect. Hover first, middle, and last observations and verify:

- timestamp and unit are present;
- every visible model has a row and an exact value or `—`;
- close numeric values remain distinguishable;
- the value column is visible at both chart edges and narrow width;
- with all eight models selected, the tooltip bounding rectangle remains wholly within `.u-over`; if rows cannot all fit simultaneously, only the rows region scrolls while the timestamp, unit/footer, and complete value column remain visible;
- leaving the plot hides the tooltip;
- event-rail hover moves the synchronized cursor without opening tooltips;
- drag zoom, URL range update, legend focus, theme switch, and resize still work.
- the browser console contains no exceptions during initial chart construction, cursor synchronization, interaction, or teardown, specifically exercising uPlot's pre-`ready` `setCursor` path.

- [ ] **Step 4: Run final automated verification**

```bash
source .venv/bin/activate
pytest
git diff --check 3703215..HEAD
git status --short --branch
```

Expected: complete suite has zero failures; diff check is clean; only intentional branch commits exist; working tree is clean.

- [ ] **Step 5: Final audit and review**

Inspect `git diff 3703215..HEAD` and the commit list for scope, placeholders, sensitive data, accidental generated/browser artifacts, or changes to the installed standalone. Dispatch a fresh holistic reviewer for the full range. Resolve all findings through the same implementer/reviewer loop before declaring completion.

Do not push, open a PR, merge, delete the branch, or deploy unless the user separately requests those actions.
