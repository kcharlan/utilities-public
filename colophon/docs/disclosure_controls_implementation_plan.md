# Disclosure Controls: Implementation Plan

## Goal and scope

Every control listed under Affected controls must be collapsible from
wherever the reader ends up, must say what state it is in, and must not
strand the reader after collapsing. The rules that achieve this are under
Shared behavior; each control's section applies them.

Out of scope: turn virtualization, navigation controls, accounting, workspace
resolution, and payload fields other than the release version.

## Source authorities and global constraints

Paths are relative to `colophon/`. Symbols are in `assets/page.js` unless
another file is named.

| Concern | Authority to preserve or extend |
|---|---|
| Element construction | `el` |
| Overview panels | `panel`, `renderOverview`, `renderWorkspaces`, `workspaceFills`, module state `expandedWorkspaces` and `workspaceMetric` |
| Reader text and turns | `expandableText`, `renderRequest`, `renderAnswer`, `renderSubagentRow`, `renderTurn` |
| Reader layout refits | `fitReader` and every call site of it |
| Footer and diagnostics | `renderFooter`, `diagnosticItems`, `diagnosticText`, `diagnosticCount` |
| Rerender cycle | `render`, `act` |
| Visual tokens and control styles | `assets/page.css`: `.panel-head`, `.metric-toggle`, `.view-all, .expand-workspaces`, `.long-text`, `.text-expander, .followup-toggle, .fork-link`, `details`, `summary` |
| Browser tests and fixtures | `tests/test_browser.py`: `source_page`, `opencode_page`, `open_native`, `browser_page`; `tests/browser_errors.py`: `guard_browser_errors`; payload mutation as `test_opencode_source_states_structured_diagnostics_and_preview` and `test_claude_continue_shell_roundtrip_and_eligibility` do; viewport sizes as `test_source_metric_colors_splits_and_cost_states` sets them |
| Asset digests | `assets/MANIFEST`, verified by `tools/check_assets.pl` (`make check-assets`) |
| Behavior documentation | `docs/runtime.md`; `README.md` release paragraphs; `docs/LESSONS_LEARNED.md` |
| Validation commands | `docs/development.md`; root `AGENTS.md` Validation Matrix entries for `colophon` and Static deployment/fleet audit tooling |

Target release: **0.4.2**. Locate maintained version declarations and assertions
with `rg -n '0\.4\.1' src tests docs/runtime.md ../tools/deploy_colophon.mjs
../tools/tests/deploy_colophon.test.mjs`. Inspect the matches at implementation
time; preserve historical release notes. Starting locations:

| File | Site |
|---|---|
| `src/out/payload.c` | `meta.version` string written by the payload writer |
| `src/cli/args.c` | `--version` output |
| `tests/test_cli.py` | `--version` assertion |
| `tests/test_browser.py` | payload version and `[data-version]` footer assertions |
| `tests/test_opencode.py` | payload version assertion |
| `docs/runtime.md` | footer version and "Version is currently" sentences |
| `../tools/deploy_colophon.mjs` | `diagnostic` version check |
| `../tools/tests/deploy_colophon.test.mjs` | synthetic `--version` output |

## Global constraints

Preserve the page shape and privacy rules in `README.md`, `docs/runtime.md`
and root `AGENTS.md`; use `el` and the surrounding JavaScript/CSS style.
Add no dependencies or storage keys. Preserve existing tested `data-*` hooks.

## Affected controls

| Control | Where | Required behavior |
|---|---|---|
| Workspaces list | `renderWorkspaces`, `.expand-workspaces` | Workspaces section |
| Long prompt and answer text | `expandableText` | Long text section |
| Follow-ups in a turn | `renderTurn`, `.followup-toggle` | Follow-ups section |
| Footer panels | `renderFooter` `<details>` elements | Footer panels section |

Leave the `renderSubagentRow` and reader-title toggles unchanged. Extend
`expandableText` at its shared entry point so its callers get the same behavior.

## Shared behavior

Provide a state control and an expanded-state end action. Segmented controls
use `aria-pressed`; custom disclosure toggles use `aria-expanded`; footer
summaries retain native semantics. End actions have no `aria-expanded`, except
the long-text toggle that serves as both state control and end control.
For long text, the top action's visibility predicate is
`expanded && exceedsViewport(paragraph)`.

On collapse, restore focus to the surviving state control without scrolling,
then return to the block's start if it is outside the viewport. After a
workspace rerender, resolve replacement nodes before focusing or scrolling.
Native summary closure follows the same return rule. Do not steal focus on
an ordinary footer rerender.

Add shared helpers beside `el`; use them rather than inline copies:

```js
// Expanded text taller than the screen gets a collapse control above it.
const exceedsViewport = node => node.getBoundingClientRect().height > innerHeight;
// After collapsing, bring an offscreen block's start back into view.
function returnTo(anchor, control) {
  if (!anchor.isConnected) return;
  control.focus({preventScroll: true});
  const top = anchor.getBoundingClientRect().top;
  if (top < 0 || top >= innerHeight) anchor.scrollIntoView({block: "start"});
}
```

Do not pass a `behavior` option to `scrollIntoView`.

## Workspaces

- Add the module constant `WORKSPACE_PREVIEW` for the preview row count and
  derive its value from `renderWorkspaces`' current slice limit; replace the
  corresponding literals there.
- Mark the workspaces section returned by `panel` with `data-workspaces`, so
  `returnTo` can find it after `render` rebuilds the DOM.
- State control: when there are more rows than `WORKSPACE_PREVIEW`, render a
  second `.metric-toggle` group in a `.panel-head` row together with the
  existing time/tokens group. Its buttons are `top <WORKSPACE_PREVIEW>` and
  `all <row count>`, with `aria-pressed` following `expandedWorkspaces` and
  accessible names starting with "Workspaces", like the metric buttons.
  Clicking sets `expandedWorkspaces` and calls `render`; restore focus to
  the replacement selected scope button. Collapse uses Shared behavior with
  `[data-workspaces]` as anchor.
- End control: while collapsed, keep the `.expand-workspaces` "+ N more"
  button. While expanded, the same position holds a `.expand-workspaces`
  button labelled `show top <WORKSPACE_PREVIEW>`. Use the same state-setting
  handler as the scope group. The collapsed expansion action focuses the
  selected scope button after rerender. Omit scope and end controls when the
  filtered row count fits the preview, even if `expandedWorkspaces` is true.

## Long text

Rework `expandableText(text)`. Drop the `label` parameter and update
`renderRequest` and `renderAnswer`.

- Structure inside `[data-expandable-text]`: the Tall-text control
  `[data-text-collapse-top]` (hidden initially), the `[data-long-text]`
  paragraph, and the State and End control in one bottom button
  `[data-text-toggle]` with the `.text-expander` class. While collapsed the
  text is a short clamped preview, so this bottom button is also next to the
  block's start according to `assets/page.css::.long-text`; this is the
  explicit exception to a separate start toggle.
- `[data-text-toggle]` says `show more` when collapsed and `show less` when
  expanded; the top action uses the expanded label.
- One click handler serves the buttons in the Long text structure. It toggles
  `.expanded`, sets every
  control's label and the toggle's `aria-expanded`, updates the top action
  using Shared behavior's visibility predicate, and
  applies Shared behavior with the wrapper and bottom toggle when collapsing.
- In `fitReader`'s `[data-expandable-text]` loop, select the toggle as
  `[data-text-toggle]` instead of the wrapper's first button, keep its
  existing hide rule, and recompute the Tall-text control's `hidden` with the
  rule above for measurable paragraphs. Reuse `fitReader`'s call sites
  named in Source authorities rather than adding parallel refit plumbing.

## Follow-ups

For the hidden follow-up block `renderTurn` builds:

- State control: the toggle reads `+ N follow-ups sent while it worked` while
  collapsed and `hide N follow-ups` while expanded.
- End control: a `.followup-toggle` button `[data-followup-collapse]`, using
  the expanded state label, as the block's last child. It is inside the hidden
  block. Share one state-setting handler with the state control; after
  `fitReader`, collapse applies Shared behavior using the state control as
  anchor and focus target.

## Footer panels

Route `renderFooter`'s details construction through one helper, for diagnostics
and the OpenCode database panel. Keep `diagnosticItems`, `diagnosticText` and
`diagnosticCount` as the content authorities.

- Open state: keep a module-level `Set` of open panel keys (the
  `data-diagnostic` value, or `opencode_databases` for the database panel).
  Snapshot connected panels' live `.open` values before replacing the footer,
  so rerender does not depend on delivery of queued native `toggle` events.
  Restore `.open` as a DOM property: `el`'s attribute setter must not receive
  `open: false`. Connected-panel `toggle` listeners update the set; detached
  listeners do nothing. The explicit close action updates the set
  synchronously. Restoring an open panel must not trigger collapse scrolling.
- State control: the native `<summary>`.
- End control: a `.followup-toggle`-styled button `[data-details-close]`,
  labelled `hide`, as the panel's last child. Use Shared behavior with the
  panel and its summary. For native summary toggles, apply the return rule
  only to an actual open-to-closed transition of a connected panel.

## Tasks

Each task includes its behavior, regression tests and a focused runtime-doc
update; add a disclosure-controls paragraph rather than accumulating unrelated
reader behavior in the workspace-identity paragraph. Refresh changed asset
entries using `shasum -a 256 assets/page.css assets/page.js`, following the
Asset digests authority. Full-suite validation applies before calling a task
complete; selected browser tests are development feedback only.

Use the Browser tests and fixtures authorities for setup, synthetic payload
mutation, error/request guards and viewport sizes. New cases retain those
guards. Factor repeated browser setup and geometry assertions into test helpers.
For scroll-return cases, make expanded content exceed the viewport and provide
enough trailing content that document-end clamping cannot return the anchor.
Assert the anchor top is more than one viewport above the screen immediately
before activation. Keep bottom actions visible when clicking; use DOM activation
for offscreen start controls so
Playwright's automatic scrolling cannot perform the return under test. Check
`-1 <= anchor.top < innerHeight` after collapse and the expected focused control.
The one CSS pixel tolerance accommodates Chromium's integral scroll-offset
rounding of fractional block starts; it does not permit a missing return.
Add an in-view case that must not scroll. Separately exercise visible controls
with keyboard activation. Prove the return regressions fail with only the
helper's scrolling disabled; keep focus restoration enabled for that check.

### Task 1: Shared helpers and Workspaces

Implement Shared behavior and Workspaces. Record the collapse/return lesson in
`docs/LESSONS_LEARNED.md` alongside the regression evidence.

Tests in `tests/test_browser.py`:

- New `test_workspaces_collapse_from_top_and_bottom`: through `source_page`,
  add enough synthetic workspaces for the expanded card to exceed the
  viewport. Navigate to the overview (`.brand`). Assert the scope toggle's
  `aria-pressed` and the row count in the collapsed and expanded states.
  Exercise every expansion/collapse path from Workspaces using the Tasks
  scroll-return protocol; verify metric changes retain scope and filtered
  row counts update the scope label.
- In the same test, with no more workspaces than `WORKSPACE_PREVIEW`, assert
  that neither the scope toggle nor an End control is rendered. Include the
  case reached by filtering an already expanded list.

### Task 2: Long text and follow-ups

Implement Long text and Follow-ups, including the `fitReader` change.

Tests:

- New `test_long_text_collapses_from_top_and_returns`: give one request and
  one final answer synthetic text taller than the viewport. Assert that the
  request and answer obey Long text, including top/bottom collapse through the
  Tasks protocol. Cover a subagent answer, an expanded paragraph below the
  viewport threshold, and an unclipped short paragraph. Resize the viewport
  and drag the splitter across the tall-text threshold; assert the top
  action's visibility changes without altering expansion state.
- New `test_followups_label_and_bottom_hide`: give one turn enough synthetic
  follow-ups to make the expanded block taller than the viewport. Assert the
  Follow-ups contract through each collapse path. Reopen the block and verify
  nested long-text controls are refitted. Apply the Tasks protocol.

### Task 3: Footer panels and release

Implement Footer panels and prepare the Target release.

Tests:

- New `test_footer_panels_close_from_bottom_and_survive_render`: give one
  diagnostic and the database panel enough synthetic items to exceed the
  viewport. Parameterize over panel kind and collapse path. Check independent
  open states across source/metric rerenders, immediate rerender before a
  native toggle event is delivered, and closed panels staying closed after
  rerender. Apply the Tasks protocol. Preserve existing footer assertions
  except the intentional release-version updates.

Release:

- Update the Release version sites to the Target release and add its README
  release paragraph. Verify CLI, payload and rendered-footer versions agree
  through the version tests named in Source authorities.

## Full-suite validation

Follow the Validation commands authorities for affected projects and expected
results. The installer version change requires the Static deployment/fleet
audit tooling commands. Apply the dependency rule there if shared audit code
changes. Record failures and unrun gates explicitly; selected tests do not
replace full categories.

## Visual acceptance

Inspect the synthetic pages produced by the new browser tests at the viewport
sizes named in Browser tests and fixtures. Exercise Affected controls with
mouse and keyboard; check collapse return, focus and horizontal overflow.
Keep evidence under each test's external scratch root as the screenshot test
in that authority does. Real-session acceptance is a separately authorized
gate governed by `docs/LESSONS_LEARNED.md` and `docs/runtime.md`'s SQLite
coordination contract; it is unnecessary for these invented-content cases.

## Deployment

Deployment follows `../docs/local_deployment_sync.md#native-colophon-deployment`
after validated changes are merged to `main`, when Kevin authorizes it.
Use that guide's commands and installed-artifact checks, and compare the
installed version with Target release. Implementation approval alone does
not authorize later deployments.
