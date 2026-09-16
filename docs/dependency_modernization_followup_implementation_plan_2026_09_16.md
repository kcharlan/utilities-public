# Dependency Modernization Follow-up Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to execute this
> plan with review checkpoints in a separate session.
> The current user instruction requires a feature branch, forbids worktrees,
> and forbids work on `main`; do not use a worktree-based execution mode.

**Goal:** Bring the genuinely held dependency surfaces identified in the
[follow-up analysis](dependency_modernization_followup_analysis_2026_09_16.md)
to current supported lines without changing intentional LTS/product policies,
breaking the embedded no-build architecture, or weakening project validation.

**Architecture:** Decouple chart, graph, CSS, React/module-loader, test-client,
video-processing, model-selection, and Node-LTS work into independently
reviewable phases. Recharts 3 and React Flow 12 move on React 18 UMD first;
React 19 then uses an exact-version ESM import map. Real Tailwind consumers
move independently to Tailwind 4 while Cognitive Switchyard removes its unused
Tailwind load. `vid-compiler` becomes a standard-library uv launcher over
FFmpeg/ffprobe. Model and Node changes remain evidence/status gated.

**Tech stack:** Python 3.12+ and uv PEP 723 launchers, pytest, Playwright,
React/ReactDOM ESM, Babel Standalone, Tailwind browser runtime, Recharts,
`@xyflow/react`, FastAPI/Starlette test clients, FFmpeg/ffprobe, Docker Compose,
Node/npm, and `benchmark-llm` plugin benchmarks.

---

## Execution constraints and stop gates

- Start and remain on a `codex/` feature branch in the repository's primary
  checkout. Task 1 defines the executable branch/worktree gate; rerun it before
  every commit. Do not create a linked worktree for implementation or
  benchmark execution.
- Read the root and every applicable nested `AGENTS.md` and `CLAUDE.md` before
  editing. Stop to reconcile any instruction added after this plan was written.
- Read each affected project's README and its linked design/test documentation
  immediately before editing that project. The paths below identify known
  documentation, but the executor must follow newly added links too.
- Treat every listed directory as an independent project boundary. Run its
  complete documented suite after its change; a passing pilot does not replace
  consumer-project tests.
- Use a project virtual environment for every Python command. Creating the venv
  may use `python3 -m venv`; all subsequent Python/pip/pytest/Playwright
  commands must use that venv's executable.
- Do not execute paid model comparisons without explicit user approval. The
  benchmark harness and synthetic fixtures may be implemented and tested
  before that gate.
- Do not change Node 24 until the official Node lifecycle identifies Node 26 as
  LTS. A closed date/status gate produces no Dockerfile change.
- Use only conspicuously synthetic data. Raw benchmark output must stay outside
  the repository and must never be committed.
- Before every commit, inspect `git diff --cached --name-only` and
  `git diff --cached` for sensitive data. Every commit must have an imperative
  subject and a non-empty body that explains what changed, why, and how it was
  validated.
- Stop if a complete affected-project suite fails. Diagnose and fix every
  failure before moving to the next project; do not classify failures away.

## Dependency order

```text
baseline/version recheck
├── Cognitive Switchyard dead Tailwind removal
├── Cognitive Switchyard httpx2 test transport
├── Recharts 3 UMD (Git Fleet → RouterView)
├── React Flow 12 UMD (Cognitive Switchyard)
├── Tailwind 4 (Storage Monitor pilot → seven consumers)
└── React 19 + Babel 8 ESM (Launchmaster pilot → ten consumers)

vid-compiler FFmpeg replacement ─────────────── independent
model benchmark harness → paid-run approval → role-specific defaults
Node lifecycle check → only if LTS → Docker Webserver update
all completed/reported gate outcomes → final fleet audit and documentation
```

The frontend sequence intentionally accepts a short-lived React 18 plus current
Recharts/React Flow state. It makes major-library failures attributable before
the module-loader migration. Do not collapse phases unless a fresh probe and
review show that the combined change is lower risk for that specific project.

## Shared frontend acceptance contract

Apply this contract to every frontend task below:

- Automated support target: current Playwright Chromium. For the eight
  Tailwind consumers only, document Tailwind 4's manual-client minimums—Chrome
  111, Safari 16.4, Firefox 128. Do not claim automated Safari/Firefox coverage.
- Pin package versions in every CDN URL. Exact version pins prevent package
  resolution drift, not byte-identical CDN output; retain the existing runtime
  network requirement in documentation.
- Browser tests must fail on `pageerror` and unexpected `console.error`.
  Remove broad Recharts/framework error suppression; allow only a narrowly
  documented message when the upstream library proves it unavoidable.
- Preserve existing UI behavior, keyboard paths, dark-mode persistence, and
  API contracts. Add behavior assertions for the library being migrated; a
  URL-string check or “SVG exists” check is insufficient by itself.
- During React 19 ESM work, the base import map in all eleven projects must
  cover exact versions of `react`, `react/jsx-runtime`,
  `react/jsx-dev-runtime`, `react-dom`, `react-dom/client`, and aligned
  `react-is`.
  Recharts ESM must externalize `react`, `react-dom`, and `react-is`; React Flow
  ESM must externalize `react` and `react-dom`.
- Capture `performance.getEntriesByType("resource")` or equivalent browser
  routing evidence and assert that dependencies do not fetch an additional
  React, ReactDOM, or `react-is` version. Rendering without an invalid-hook-call
  error is not adequate proof of a single peer graph.
- Before a project's first Babel 8 or Tailwind 4 edit, inspect its README and
  linked user/design docs for browser promises. If the promise is below the
  new dependency floor, stop that project and deliberately choose retention or
  compiled compatibility assets. Add Tailwind-specific floor text only to the
  eight real Tailwind consumers; document Babel 8/ESM requirements separately
  for all eleven React applications.

## Task 1: Revalidate the snapshot and record implementation baselines

**Files:**

- Read: `docs/dependency_modernization_audit_2026_09_16.md`
- Read: `docs/dependency_modernization_followup_analysis_2026_09_16.md`
- Modify only if version facts changed:
  `docs/dependency_modernization_followup_analysis_2026_09_16.md`

- [ ] Enforce the branch and primary-checkout gate before editing and before
  every commit. Do not auto-create or auto-switch if it fails:

  ```zsh
  branch="$(git branch --show-current)"
  [[ "$branch" == codex/* ]] || { print -u2 "expected codex/* branch"; exit 1; }
  git_dir="$(git rev-parse --absolute-git-dir)"
  common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
  [[ "$git_dir" == "$common_dir" ]] || { print -u2 "linked worktree forbidden"; exit 1; }
  git status --short
  git diff
  ```

  Ordinary disposable repository copies under the benchmark runtime directory
  are allowed; linked Git worktrees of the user's source checkout are not.
- [ ] Re-query exact stable versions and peer metadata for `react`,
  `react-dom`, `react-is`, `@babel/standalone`, `@tailwindcss/browser`,
  `recharts`, `@xyflow/react`, Lucide, PropTypes, `httpx2`, and MoviePy. Record
  any changed target in the analysis before implementation.
- [ ] Re-read the official React, Babel, Tailwind, Recharts, React Flow,
  Starlette, Node, MoviePy, and OpenAI model references linked by the analysis.
  A target that changed after 2026-09-16 requires a small compatibility probe,
  not blind version substitution.
- [ ] Run the disposable cross-library Playwright probe with the resolved
  versions. Save only a sanitized textual result; do not check in browser
  profiles, caches, or downloaded assets.
- [ ] Record baseline full-suite results for the first project in each pilot
  below before editing it. Expected result: every baseline passes. A failure is
  a blocker to that project phase and must be fixed first.

## Task 2: Remove dead Tailwind from Cognitive Switchyard and repair its design reference

**Files:**

- Modify: `cognitive_switchyard/cognitive_switchyard/html_template.py`
- Modify: `cognitive_switchyard/tests/test_html_template.py`
- Modify: `cognitive_switchyard/README.md`
- Modify: `cognitive_switchyard/docs/cognitive_switchyard_design.md`
- Inspect: `cognitive_switchyard/tests/test_e2e.py`

- [ ] Change the existing dependency-pin test first so it asserts that no
  Tailwind script/configuration is present while retaining exact checks for
  React, Babel, Lucide, and React Flow.
- [ ] Confirm with source search and browser coverage that the template uses
  project CSS/classes only—no Tailwind utilities, `dark:` variants,
  `tailwind.config`, `@apply`, or generated Tailwind styles.
- [ ] Remove the Tailwind 3 script. Update the README's frontend-stack and
  network-dependency description instead of replacing it with Tailwind 4.
- [ ] Correct the design document statement that React Flow 12 requires React
  19. State the actual `react >=17`/`react-dom >=17` peer boundary and the
  independent reasons for the later React 19 ESM migration.
- [ ] Extend `tests/test_e2e.py` only if the existing suite does not already
  exercise representative styled pages and fail on browser/console errors.

**Validation:**

```zsh
cd cognitive_switchyard
.venv/bin/python -m pytest tests/ -v
```

Expected: the complete Cognitive Switchyard suite passes; rendered UI styling
and interactions are unchanged; no Tailwind request appears in the browser
resource list.

Suggested commit:

```text
Remove unused Switchyard Tailwind runtime

Prove the embedded UI uses project CSS, delete the dead CDN load, and correct
the React Flow peer-version guidance. Validate with the complete suite.
```

## Task 3: Move Cognitive Switchyard's test client to HTTPX 2

**Files:**

- Modify: `cognitive_switchyard/requirements-dev.txt`
- Modify: the narrowest applicable test module, expected
  `cognitive_switchyard/tests/test_server.py`
- Modify if dependency setup text changes: `cognitive_switchyard/README.md`
- Do not modify application runtime requirements solely for this test client.

- [ ] Replace the direct `httpx` development dependency with the current
  stable `httpx2` requirement accepted by the current Starlette release.
- [ ] Add a focused regression assertion that `TestClient` construction and a
  representative request do not emit the HTTPX-fallback deprecation. Do not
  introduce global warning filters.
- [ ] If a stable Starlette release now contains the
  `anyio.from_thread.BlockingPortal` change, update through the normal FastAPI
  compatibility graph and assert that warning is gone. Otherwise retain the
  latest stable graph and document the exact temporarily accepted AnyIO
  warning plus the next-release recheck trigger.
- [ ] Record unclosed-SQLite `ResourceWarning`s as a separate follow-up. Do not
  repair them or make global warnings-as-errors part of this dependency task.
- [ ] Capture the full suite's default warnings and group them by warning class
  plus normalized message. Require the HTTPX fallback count to be zero. If the
  stable Starlette fix has not shipped, keep the expected AnyIO category and
  message identifiable without assuming a count until the run establishes it.
  Inventory SQLite warnings separately. Any new category outside the accepted
  AnyIO message and tracked SQLite set is a failure to investigate.
- [ ] Recreate or refresh the project venv from tracked manifests before the
  full suite so the old `httpx` fallback cannot survive as an orphan.

**Validation:**

```zsh
cd cognitive_switchyard
.venv/bin/python -m pytest tests/ -v -W default
```

Expected: every test passes; no Starlette “install httpx2” warning remains;
the report includes exact warning categories/messages/counts; any remaining
accepted AnyIO warning exactly matches the documented upstream category.
Report all other warnings rather than filtering them.

## Task 4: Upgrade Recharts to v3 under React 18 UMD

### 4A. Git Fleet pilot

**Files:**

- Modify: `git-multirepo-dashboard/git_dashboard.py`
- Modify: `git-multirepo-dashboard/tests/test_html_shell.py`
- Modify: `git-multirepo-dashboard/tests/test_e2e.py`
- Inspect/update behavioral tests:
  `git-multirepo-dashboard/tests/test_analytics_time_allocation.py` and
  `git-multirepo-dashboard/tests/test_analytics_heatmap.py`
- Modify if stack text changes:
  `git-multirepo-dashboard/README.md` and
  `git-multirepo-dashboard/docs/git_dashboard_final_spec.md`

- [ ] Update static dependency assertions first. Load exact, React-18-aligned
  `react-is` UMD before the exact Recharts 3 UMD build; preserve the global
  `Recharts` integration for this phase.
- [ ] Audit the three AreaChart surfaces (`RepoTrendSparkline`, analytics
  activity, and time allocation) against the Recharts 3 migration guide.
- [ ] Add/strengthen browser assertions for responsive sizing, rendered area
  paths, stacked positive/negative data, axis labels, and custom tooltip
  content after hover. Remove the existing broad Recharts/non-critical error
  filtering so real v3 errors fail the test.

**Validation:**

```zsh
cd git-multirepo-dashboard
.venv/bin/python -m pytest tests/ --ignore=tests/test_e2e.py -v
.venv/bin/python -m pytest tests/test_e2e.py -v
```

Expected: both separately documented suites pass with Recharts 3 and
`react-is` loaded once, with no page or console errors.

### 4B. RouterView consumer

**Files:**

- Modify: `routerview/routerview`
- Modify: `routerview/tests/test_browser_smoke.py`
- Inspect/update: `routerview/tests/test_frontend.py` and
  `routerview/tests/test_csv_import.py`
- Modify: `routerview/README.md`
- Modify if architectural dependency text changes: `routerview/docs/DESIGN.md`

- [ ] Apply the exact Recharts 3 plus aligned `react-is` UMD pattern proven in
  Git Fleet.
- [ ] Resolve v3 behavior changes explicitly around
  `activeTooltipIndex`, `activePayload`, custom tooltip payloads, legend click
  hiding, pie cells, and bar click filtering. Do not reach into removed
  internal chart state to mimic v2.
- [ ] Extend the browser smoke to hover a time-series point, toggle a legend
  item, and click a dimensional bar; assert the corresponding tooltip/filter
  behavior and no browser/console errors.

**Validation:**

```zsh
cd routerview
.venv/bin/python -m pytest -q
```

Expected: complete suite passes and each chart interaction has a behavioral
assertion, not just DOM presence.

## Task 5: Upgrade Cognitive Switchyard to React Flow 12 under React 18 UMD

**Files:**

- Modify: `cognitive_switchyard/cognitive_switchyard/html_template.py`
- Modify: `cognitive_switchyard/tests/test_html_template.py`
- Modify: `cognitive_switchyard/tests/test_e2e.py`
- Modify: `cognitive_switchyard/README.md`
- Modify: `cognitive_switchyard/docs/cognitive_switchyard_design.md`

- [ ] Change static tests first to require exact `@xyflow/react` 12 UMD and
  stylesheet paths and reject the legacy `reactflow` package.
- [ ] Load `window.ReactFlow` from the new UMD build. Change the component
  lookup from `ReactFlowLib.default` to `ReactFlowLib.ReactFlow`; preserve
  `ReactFlowProvider`, `MiniMap`, `Controls`, and `Background` named members.
- [ ] Audit the DAG adapter for v12 immutable node/edge updates, measured
  dimensions, renamed coordinate helpers, fit-view behavior, and selection
  callbacks. Do not add compatibility shims for APIs the application does not
  use.
- [ ] Extend E2E coverage to render a nontrivial DAG, assert nodes and edges,
  use controls/fit view, select a node, and verify the details UI plus no
  browser/console errors.

**Validation:**

```zsh
cd cognitive_switchyard
.venv/bin/python -m pytest tests/ -v
```

Expected: complete suite passes on React 18 plus React Flow 12. The design and
README describe React Flow 12 independently from the later React 19 work.

## Task 6: Migrate the eight real Tailwind consumers to v4

### 6A. Storage Monitor pilot

**Files:**

- Modify: `storage_monitor/storage_monitor`
- Modify: `storage_monitor/tests/test_browser_smoke.py`
- Modify: `storage_monitor/README.md`

- [ ] Change static tests first to require the exact
  `@tailwindcss/browser` v4 script and reject the classic CDN URL.
- [ ] Use `<style type="text/tailwindcss">` for any Tailwind-specific CSS.
  Storage Monitor has no JavaScript `tailwind.config`, so this pilot establishes
  the browser-package and content-discovery pattern without token conversion.
- [ ] Assert representative utility computed styles and the existing theme
  toggle/persistence behavior, plus page and console cleanliness.
- [ ] Document automated Chromium support and the Tailwind 4 manual-client
  minimums in the README.

**Validation:**

```zsh
cd storage_monitor
.venv/bin/python -m pytest -q
./storage_monitor --help
```

Expected: complete suite and safe CLI smoke pass; computed-style assertions
prove Tailwind v4 generated the used classes.

### 6B. Custom-theme consumers, one project at a time

**Runtime files:**

- `editdb/editdb`
- `expense_dock/expense_dock`
- `harscope/harscope`
- `jtree/jtree`
- `mls-tracker/mls_tracker`
- `routerview/routerview`
- `tax2/tax2`

**Tests and maintained docs:**

- `editdb/tests/test_e2e.py`, `editdb/README.md`, `editdb/docs/USER_GUIDE.md`
- `expense_dock/tests/test_e2e.py`, `expense_dock/README.md`
- `harscope/tests/test_e2e.py`, `harscope/README.md`,
  `harscope/tests/README.md`, `harscope/tests/TEST_PLAN.md`
- `jtree/tests/test_e2e.py`, `jtree/README.md`, `jtree/docs/USER_GUIDE.md`
- `mls-tracker/tests/test_browser_smoke.py`, `mls-tracker/README.md`,
  `mls-tracker/docs/USER_GUIDE.md`
- `routerview/tests/test_browser_smoke.py`, `routerview/README.md`,
  `routerview/docs/DESIGN.md`
- `tax2/tests/test_browser_smoke.py`, `tax2/README.md`, `tax2/docs/Usage.md`

For each project independently:

- [ ] Replace classic Tailwind with the exact v4 browser package.
- [ ] Translate `tailwind.config` custom colors/fonts/tokens to `@theme`
  variables. When the UI toggles a `.dark` class, include
  `@custom-variant dark (&:where(.dark, .dark *));`.
- [ ] Search dynamic class construction. Whole literal alternatives are safe;
  refactor fragment concatenation to complete discoverable class strings or
  add explicit sources only where v4 scanning otherwise misses them.
- [ ] Add computed-style assertions for at least one custom theme token and,
  where present, one dark-mode variant. Exercise the project's key interaction
  and fail on page/console errors.
- [ ] Update the README/browser-floor statement and any linked user/design doc
  that describes the frontend stack or theming contract.
- [ ] Run the complete project suite before starting the next project.

**Minimum known per-project commands (not a substitute for README discovery):**

```zsh
cd editdb
.venv/bin/python -m pytest tests --ignore=tests/test_e2e.py -q
.venv/bin/python -m pytest tests/test_e2e.py -q

cd ../expense_dock
.venv/bin/python -m pytest -q
./expense_dock --help

cd ../harscope
.venv/bin/python -m pytest -q

cd ../jtree
.venv/bin/python -m pytest -q

cd ../mls-tracker
.venv/bin/python -m pytest -q

cd ../routerview
.venv/bin/python -m pytest -q

cd ../tax2
.venv/bin/python -m pytest
```

For every project, re-read its README and linked testing docs immediately
before the change, write a phase-local checklist of every documented unit,
integration, E2E, CLI, browser, and runtime-smoke category, and run all of
them. The block above is only the minimum known set. In particular, start
`mls_tracker --no-browser` and `tax2 --no-browser` on their launcher-selected
free ports, request their root page/health path, then terminate them cleanly;
also run each documented `--help` smoke. If governing `AGENTS.md` still calls
these Streamlit apps even though their maintained READMEs specify FastAPI,
reconcile the governance text but do not omit the entrypoint smoke.

Expected: every discovered validation category passes in its project's
reproducible venv. Do not run these projects from one shared interpreter.

## Task 7: Migrate React and Babel to ESM, one project at a time

### 7A. Launchmaster pilot

**Files:**

- Modify: `launchmaster/launchmaster`
- Modify: `launchmaster/tests/test_e2e.py`
- Modify: `launchmaster/README.md`

- [ ] Make the static/browser test expect an import map and module-aware Babel
  script before changing the runtime template.
- [ ] Replace React/ReactDOM UMD scripts with exact-version import-map entries
  for the complete base peer/subpath contract. Upgrade Babel Standalone to v8;
  use `type="text/babel"`, `data-type="module"`, and explicit
  `data-presets="env,react"`.
- [ ] Import `* as React` and ReactDOM Client in the inline module. Preserve
  existing `ReactDOM.createRoot` semantics and update only bindings required by
  the module scope/new JSX transform.
- [ ] Add browser request-graph assertions: exactly one selected React version,
  exactly one selected ReactDOM version, no React 18 UMD request, no unversioned
  package URL, and no page/console error.
- [ ] Exercise startup and a representative mutation in the full E2E suite.

**Validation:**

```zsh
cd launchmaster
.venv/bin/python -m pytest -q
```

Expected: complete suite passes and resource assertions prove a single React
peer graph.

### 7B. Roll out the proven base contract

**Runtime and primary test files:**

| Project | Runtime | Primary browser test |
|---|---|---|
| Cognitive Switchyard | `cognitive_switchyard/cognitive_switchyard/html_template.py` | `cognitive_switchyard/tests/test_e2e.py` |
| EditDB | `editdb/editdb` | `editdb/tests/test_e2e.py` |
| Expense Dock | `expense_dock/expense_dock` | `expense_dock/tests/test_e2e.py` |
| Git Fleet | `git-multirepo-dashboard/git_dashboard.py` | `git-multirepo-dashboard/tests/test_e2e.py` |
| HAR Scope | `harscope/harscope` | `harscope/tests/test_e2e.py` |
| JTree | `jtree/jtree` | `jtree/tests/test_e2e.py` |
| MLS Tracker | `mls-tracker/mls_tracker` | `mls-tracker/tests/test_browser_smoke.py` |
| RouterView | `routerview/routerview` | `routerview/tests/test_browser_smoke.py` |
| Storage Monitor | `storage_monitor/storage_monitor` | `storage_monitor/tests/test_browser_smoke.py` |
| Tax2 | `tax2/tax2` | `tax2/tests/test_browser_smoke.py` |

**Governing guidance after the pilot pattern is proven:**

- Modify: `AGENTS.md`
- Modify its mirrored repository guidance: `CLAUDE.md`

Update the “Embedded React SPA” preferred pattern to describe React 19 through
the validated exact-version import map, Babel 8 module-aware inline JSX,
Tailwind 4 only when the project actually uses Tailwind, CSS-first `@theme`,
the explicit `.dark` custom variant, and the no-build/CDN network and
non-immutable-delivery constraints. Remove the blanket React 18/UMD and v3
`darkMode` guidance. Reconcile outdated project labels in the validation
matrix against maintained READMEs without weakening their required entrypoint
smokes.

- [ ] Apply the Launchmaster import-map/Babel contract to one project, update
  its exact static assertions and maintained stack documentation, then run its
  complete suite before continuing.
- [ ] For Git Fleet and RouterView, replace Recharts/`react-is` UMD globals with
  ESM imports whose CDN URLs externalize the import-map peers. Preserve and
  rerun every Task 4 behavioral chart assertion.
- [ ] For Cognitive Switchyard, replace the React Flow UMD global with
  `@xyflow/react` ESM imports externalized to the import-map peers; retain its
  exact stylesheet and rerun every Task 5 DAG assertion.
- [ ] For Tailwind projects, rerun computed-style and dark-mode tests because
  Babel's module transform and load ordering can affect browser initialization.
- [ ] Update all dependency-pin tests and linked README/design/user-guide stack
  descriptions. In particular, remove every stale claim that UMD is required,
  React 18 is the architecture ceiling, or React Flow 12 requires React 19.
- [ ] After the Launchmaster pattern and at least one Tailwind v4 consumer have
  passed in full, update `AGENTS.md` and `CLAUDE.md` together. Confirm their
  preferred frontend pattern agrees with the implemented architecture and
  their validation matrix still requires all affected project categories.
- [ ] Repeat the per-project README/documentation discovery and run every
  documented validation category from Tasks 2, 4, and 6 immediately after its
  migration. Treat the printed commands as minimum known commands, not an
  authoritative definition of a complete suite.

Expected: all eleven applications run React 19/Babel 8 through exact ESM
imports, use one React peer graph, preserve key interactions, and emit no page
or console error. No project gains npm/build-generated frontend artifacts.

## Task 8: Replace `vid-compiler`'s Python package graph with FFmpeg

**Files:**

- Modify: `vid-compiler/video_compiler.py`
- Modify: `vid-compiler/README.md`
- Delete after updating every maintained reference: `vid-compiler/setup.sh`
- Remove runtime role: `vid-compiler/requirements.txt`
- Add: `vid-compiler/requirements-dev.txt`
- Add: `vid-compiler/tests/test_video_compiler.py`
- Modify: `tools/check_uv_headers.py`
- Modify: `tools/tests/test_check_uv_headers.py`

### Required interfaces and invariants

The executor may choose local names around these load-bearing interfaces, but
must preserve the stated contracts:

```python
@dataclass(frozen=True)
class MediaInfo:
    duration: float
    has_audio: bool

@dataclass(frozen=True)
class Segment:
    start: float
    duration: float

def probe_media(path: Path) -> MediaInfo: ...
def sample_start_times(
    total_duration: float,
    tail_length: float,
    sample_length: float,
    num_samples: int,
    method: str,
    rng: random.Random | None = None,
) -> list[float]: ...
def build_filter_graph(
    segments: Sequence[Segment], has_audio: bool
) -> tuple[str, list[str]]: ...  # filter string, output map labels
def process_video(...) -> bool: ...  # success/failure for progress reporting
```

- [ ] Add the canonical uv shebang and PEP 723 block with
  `requires-python = ">=3.12"` and `dependencies = []`. Register
  `vid-compiler/video_compiler.py` in `LAUNCHERS`; map it to the tracked dev
  manifest in `DEPENDENCY_MANIFESTS`, allowing only pytest.
- [ ] Write unit tests first for current even sampling and random sampling.
  Preserve this golden matrix before removing NumPy:

  | Case | Required result |
  |---|---|
  | even, `num_samples == 0` | `[0]` (legacy asymmetry) |
  | even, `num_samples == 1` | `[0]` |
  | even, `num_samples > 1` | linspace endpoints included |
  | even, `max_start == 0`, multiple samples | repeated zeros |
  | random, `num_samples == 0` | `[]` |
  | random, `max_start <= 0` | `[]` |
  | random, requested samples > 1,000 | cap at 1,000 |
  | random, normal case | no replacement; ascending output |
  | tail longer than source | clamp tail to source duration |
  | accepted sample near tail | retain full `sample_length` after the legacy `end > start` eligibility check |
  | all modes | append tail last |

  Inject `random.Random` only for repeatable tests; preserve the sorted
  1,000-point linspace grid and its distribution.
- [ ] Implement `ffprobe` JSON parsing for duration and audio-stream presence.
  Validate finite positive duration and produce actionable messages for missing
  tools, invalid JSON, and unreadable media.
- [ ] Preserve segment construction exactly: clamp tail length to duration;
  include a sample when the current `end > start` check permits it; retain the
  current full `sample_length` clip even when it overlaps the appended tail;
  append the tail last.
- [ ] Build one FFmpeg filter graph. For each video leg use
  `trim=start=...:duration=...,setpts=PTS-STARTPTS`; for audio use matching
  `atrim`/`asetpts`. Concatenate ordered labels with `concat=n=N:v=1:a=1`
  when audio exists and `a=0` otherwise. Map `[v]` and optional `[a]`.
- [ ] Pass subprocess argument arrays with `shell=False`. Preserve
  `h264_videotoolbox`, AAC for audio inputs, bounded `ProcessPoolExecutor`
  parallelism, glob behavior, output naming/collision behavior, and verbose
  sample messages.
- [ ] Render to a temporary sibling and `os.replace` it only after FFmpeg
  succeeds. Each invocation gets a unique same-directory temporary name that
  still ends in `.mp4` (or explicitly passes `-f mp4`); workers processing
  equal basenames must never share a temporary path. Remove only that
  invocation's partial output on failure, never an existing final. Test that a
  failed rerender leaves an existing final byte-identical, success replaces
  it, same-basename workers preserve the documented final-path collision
  behavior, and no `*.partial*.mp4` survives.
- [ ] Preserve best-effort batch semantics: a failed file reports an error and
  other files continue; missing matches and partial batch failures retain the
  documented overall zero exit status. A future nonzero-status redesign
  requires separate approval.
- [ ] Replace tqdm with clear standard-library progress. Delete `setup.sh`
  after updating every maintained reference; the repository's uv pattern
  requires one entry point and no setup shim.
- [ ] Consume every `Future.result()`. Ordinary per-file failures may return
  `False`, but an unexpected worker/process-pool exception must be associated
  with its input and reported while the batch continues with its documented
  zero status; never silently discard an exceptional future.
- [ ] Update the README for uv invocation, system prerequisites, unchanged
  limitations, and both audio/video-only validation.

**Validation:**

```zsh
cd vid-compiler
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
uv run --script video_compiler.py --help
cd ..
uv run --script tools/check_uv_headers.py
vid-compiler/.venv/bin/python -m pytest tools/tests/test_check_uv_headers.py -q
```

Use a temporary directory and FFmpeg lavfi to create two conspicuously
synthetic sources: one with `testsrc` plus a sine-wave audio track and one
video-only source. Run the CLI on each, then use ffprobe JSON to assert output
duration tolerance, H.264 video, AAC only for the audio input, and absence of
partial files. Make source intervals visually/time distinguishable and compare
boundary frame hashes (or equivalent frame probes) to prove segment order.
Unit-test the filter graph structurally: one ordered video leg per segment;
matching audio legs when present; timestamp reset on every leg; concat `n`
equal to segment count; correct `v=1:a=1` versus `v=1:a=0`; and exact output
map labels. Also run a two-file batch containing one invalid file and a mocked
worker-level exception; assert the valid output completes, both failures are
reported with their inputs, and the command preserves the documented zero
status.

Expected: no MoviePy, Pillow, NumPy, or tqdm runtime dependency/import remains;
unit, guard, CLI, synthetic render, and failure-semantics checks all pass.

## Task 9: Build a public-safe, branch-only model-default evaluation

**Files:**

- Add: `benchmark-llm/examples/orchestrator-model-eval/bench.py`
- Add: `benchmark-llm/examples/orchestrator-model-eval/README.md`
- Add conspicuously synthetic fixtures under:
  `benchmark-llm/examples/orchestrator-model-eval/tasks/`
- Add: `benchmark-llm/tests/test_orchestrator_model_eval_example.py`
- Modify: `benchmark-llm/examples/README.md`
- After approved evidence only, potentially modify the model-default files
  listed in Task 9C.

### 9A. Harness and safety contract

- [ ] Use `benchmark-llm` plugin mode, not its `git_worktree` repo-task source.
  Create disposable copies of the conspicuously synthetic task repositories
  beneath `ctx.run_dir / "workspaces"`, one per trial, and run serially or with
  bounded concurrency. Never mutate the user's checkout and never create a
  worktree.
- [ ] Use a fixed paired corpus spanning these independent cells:
  `design_orch` orchestration; Switchyard planning; resolution; auto-fix;
  `codex` worker execution; and `codex-hybrid` worker execution when its
  context differs. Fixtures and expected outputs must be unmistakably fake and
  contain no local paths, accounts, or real user/project data.
- [ ] Set `BENCH_RUNTIME_HOME` to a canonical external directory before
  invoking `bench`. Plugin mode creates its core `commands.jsonl`, manifests,
  reports, SQLite index, and `ctx.run_dir` beneath that runtime home; it has no
  repo-task `output_dir`. Treat `ctx.run_dir / "workspaces"` as the plugin's
  disposable-workspace root. After realpath/symlink resolution, refuse any
  runtime home or workspace path inside the canonical source checkout.
- [ ] Document that raw plugin artifacts may contain exact cwd, stdout/stderr,
  failed attempts, absolute paths, and model output by design and therefore
  remain private/external. Generate a separate sanitized summary as the only
  commit-eligible artifact; it must contain no absolute user path or raw model
  output.
- [ ] Capture exact candidate/model identifier, `codex --version`, execution
  date, prompt hash, reasoning effort, task order, correctness, verification
  score, retries, cost/tokens when reported, and elapsed time.
- [ ] Predeclare per-cell non-regression thresholds before live runs. Interleave
  model/task order and report paired per-task results plus dispersion. Do not
  treat an arbitrary three trials as statistically sufficient.
- [ ] Unit-test realpath/symlink containment rejection, core/plugin workspace
  placement, task-order balancing, provenance, scoring, and sanitized-summary
  generation with fake model executors. Do not invoke a paid model in tests.

**Validation:**

```zsh
cd benchmark-llm
.venv/bin/python -m pytest -q
```

Expected: complete benchmark-llm suite passes; all raw fake-run artifacts write
only beneath external `BENCH_RUNTIME_HOME`; raw provenance may contain absolute
paths, while the separately generated commit-eligible summary contains none.

### 9B. Paid-run approval gate

- [ ] Present the candidate list, fixed corpus, thresholds, projected run
  count, and cost controls to the user. Stop this phase until explicit approval
  is received.
- [ ] If approval is denied or deferred, retain every current default and
  record the evaluation gate as closed—not as a dependency failure.
- [ ] If approved, resolve the current supported Codex candidate immediately
  before execution and run the paired/interleaved evaluation. Keep raw output
  external and inspect any proposed summary independently for sensitive paths
  or echoed data.

### 9C. Apply only evidence-supported, role-specific decisions

Potential files for a winning `design_orch` default:

- `coding/design_orch/scripts/codex_packet_loop.zsh`
- related `coding/design_orch` README/design/help assertions discovered during
  the required documentation-chain pass

Potential files for Switchyard planner/resolver/auto-fix defaults:

- `cognitive_switchyard/cognitive_switchyard/builtin_packs/codex/pack.yaml`
- `cognitive_switchyard/tests/test_pack_loader.py`
- `cognitive_switchyard/docs/builtin_codex_pack.md`

Potential files for Switchyard worker defaults:

- `cognitive_switchyard/cognitive_switchyard/builtin_packs/codex/scripts/execute`
- `cognitive_switchyard/cognitive_switchyard/builtin_packs/codex-hybrid/scripts/execute`
- both built-in pack `README.md` files
- `cognitive_switchyard/docs/builtin_codex_pack.md`
- `cognitive_switchyard/docs/builtin_codex_hybrid_pack.md`
- `cognitive_switchyard/README.md`
- affected assertions in `cognitive_switchyard/tests/test_agent_runtime.py` and
  `cognitive_switchyard/tests/test_pack_loader.py`

The standalone packet-loop copy at
`cognitive_switchyard/scripts/codex_packet_loop.zsh` is another independent
consumer; update its default only if the matching role evidence supports it.

- [ ] Change each role independently; do not force all `gpt-5.4` literals to
  the same result. Preserve `MODEL_NAME`, phase-local model configuration, and
  `CODEX_WORKER_MODEL` overrides.
- [ ] Update help, docs, and exact assertions for each changed role. If no
  candidate clears a cell's thresholds, leave that cell on `gpt-5.4` and
  record why.
- [ ] Validate `coding/design_orch` with `zsh -n` on both shell files plus the
  documented help/parser compile smokes, and validate Cognitive Switchyard
  with its complete suite from Task 2.

## Task 10: Apply the Node 26 LTS gate to Docker Webserver

**Files only if the gate opens:**

- Modify: `docker/webserver/index/Dockerfile`
- Modify: `docker/webserver/app_node_Dockerfile`
- Modify: `docker/webserver/README.md`
- Modify: `docker/webserver/index/README.md`
- Modify: `docker/webserver/app_node/README.md`
- Refresh only if the Node/npm resolver changes them:
  `docker/webserver/index/package-lock.json` and
  `docker/webserver/app_node/package-lock.json`

- [ ] Check the official Node schedule on the execution date. If Node 26 is not
  LTS, record the closed gate and make no Dockerfile/lock change.
- [ ] If the gate is open, change both bases together to the current Node 26
  Alpine tag. Run `npm ci` and `npm audit` against both checked-in lockfiles in
  isolated Node 26 environments; refresh a lock only for a reproducible
  compatibility reason, never merely because npm rewrites metadata.
- [ ] Create a temporary root with a `webroot/`, a synthetic static marker, and
  an external Compose env file containing only that absolute
  `WEBROOT_PATH`. Pass the env file explicitly; do not read or modify the
  repository's `.env`. Use a unique Compose project name for every command.
- [ ] Preflight host port 7711 and abort if it is occupied; do not stop or
  replace an existing stack. Before startup, run `docker compose config` with
  the unique project/env and inspect the rendered bind mounts to prove every
  writable webroot/config path is under the temporary root.
- [ ] Install an exit/interrupt trap that runs `down --remove-orphans -v` with
  the same project name and env file. Explicitly pull the image-only `web`
  service, then build the full application stack with clean/pulled inputs.
- [ ] Verify container health, `/api/py/hello`, `/api/node/hello`,
  `/configure/api/endpoints`, a synthetic static file, directory listing,
  static-first precedence, reserved-route protection, and `nginx -t`.
- [ ] Run both npm audits and inspect service logs for startup/runtime warnings.
  Tear down the isolated stack afterward.

Core command shape after creating the temporary env file with `apply_patch`:

```zsh
cd docker/webserver
tmp_root="$(mktemp -d)"
webroot="$tmp_root/webroot"
env_file="$tmp_root/compose.env"
project="depmod-node26-$$"
mkdir -p "$webroot"
lsof -nP -iTCP:7711 -sTCP:LISTEN | rg -q '.' && {
  print -u2 "port 7711 is already in use; refusing to disturb it"
  exit 1
}
# Use apply_patch to create $env_file with: WEBROOT_PATH=<absolute $webroot>
compose=(docker compose -p "$project" --env-file "$env_file")
cleanup_compose() {
  "${compose[@]}" down --remove-orphans -v >/dev/null 2>&1 || true
}
trap cleanup_compose EXIT INT TERM
"${compose[@]}" config
"${compose[@]}" pull web
"${compose[@]}" build --pull --no-cache index app_py app_node
"${compose[@]}" up -d --force-recreate --remove-orphans --wait --wait-timeout 120
curl -fsS http://127.0.0.1:7711/api/py/hello
curl -fsS http://127.0.0.1:7711/api/node/hello
curl -fsS http://127.0.0.1:7711/configure/api/endpoints
"${compose[@]}" exec web nginx -t
"${compose[@]}" ps
"${compose[@]}" logs index app_node web
"${compose[@]}" down --remove-orphans -v
trap - EXIT INT TERM
```

Expected if open: full stack and routing contract pass on Node 26 LTS, both npm
audits are clean, docs agree, no container remains in the unique project, and
no state was written outside the verified temporary root. Expected if closed:
no source diff for this task and a dated gate result in the final implementation
report.

## Task 11: Final fleet verification and handoff

- [ ] Run `uv run --script tools/check_uv_headers.py` after all launcher/header
  work and run `tools/tests/test_check_uv_headers.py` inside an existing project
  venv that has pytest.
- [ ] Rerun every complete affected-project suite, including both separately
  documented Git Fleet suites and all Cognitive Switchyard categories. For
  frontend changes, collect the exact project-by-project pass counts and
  browser versions.
- [ ] Run the `vid-compiler` synthetic media matrix again after the final diff.
- [ ] If any model default changed, rerun the full `benchmark-llm`,
  `cognitive_switchyard`, and `coding/design_orch` validations. Do not commit
  raw benchmark output.
- [ ] If the Node gate opened, rerun the complete Docker Webserver isolated
  validation after the final diff. If it remained closed, confirm both
  Dockerfiles still use Node 24.
- [ ] Search for stale held versions and claims. Every remaining occurrence
  must be either historical text in the dated audit, a deliberately retained
  closed-gate value, or an explicit test that rejects the old version.
- [ ] Run `git diff --check`. Inspect the complete changed-file list and diff
  for generated artifacts, private paths, credentials, tokens, real account or
  financial data, and benchmark output.
- [ ] Perform a path-only scan of tracked, untracked, and ignored locations for
  benchmark/browser artifacts (`commands.jsonl`, raw responses, attempt/run
  directories, disposable repositories, browser profiles, caches). Confirm
  none was created anywhere under the canonical checkout; `.gitignore` is not
  permission to leave private output in this public repository. Resolve paths
  before inspecting content so potentially sensitive raw output is not printed
  unnecessarily.
- [ ] Update the two follow-up documents with execution-time target changes or
  gate outcomes only where they affect their factual guidance. Do not rewrite
  the historical audit as though its 2026-09-16 snapshot were a later run.
- [ ] Commit in independently reviewable project/phase units. Verify every
  branch commit beyond the base has both a concise imperative subject and a
  meaningful body before any push or pull request.

Final acceptance requires zero failing tests in every affected project, no
hidden browser/console errors, no sensitive repository content, no worktree
use, and explicit reporting of both conditional-gate outcomes. Record model
evaluation and Node LTS separately as open-and-completed, closed-and-skipped,
or stopped by their governing condition; do not assume both will be closed at
the future execution date.

## Adversarial review disposition

An independent, read-only adversarial review checked the plan against the
corrected analysis, governing repository policy, and the attached runtime,
test, benchmark, Docker, and uv-guard implementations. The review affirmed the
UMD-before-ESM sequence and the main technical direction, then surfaced
fourteen actionable handoff defects. Each was verified and corrected:

- made the `codex/*` branch and primary-checkout/no-linked-worktree rule an
  executable gate that repeats before commits;
- added root/nested `AGENTS.md` and `CLAUDE.md` discovery, and included both
  governing files in the frontend architecture migration so future guidance
  does not recreate React 18/UMD/Tailwind 3 patterns;
- made `react-is` part of the base React 19 import map and peer-request
  deduplication checks for all eleven applications;
- narrowed Tailwind browser-floor text to its eight real consumers and added a
  per-project compatibility stop gate for both Tailwind 4 and Babel 8;
- strengthened HTTPX2 acceptance with full-suite warning category/message/count
  accounting while leaving SQLite cleanup out of scope;
- reclassified embedded validation commands as minimum known commands, added
  README/doc discovery per project, and restored mandatory app-entrypoint
  smokes;
- specified `vid-compiler`'s asymmetric zero/one/random sampling matrix,
  unique MP4-safe temporary outputs, collision behavior, structural filter
  assertions, time-distinguishable render checks, and process-pool exception
  reporting; deletion of `setup.sh` is now required rather than optional;
- replaced the infeasible plugin `output_dir` contract with external
  `BENCH_RUNTIME_HOME`, an external `ctx.run_dir/workspaces` root, and a
  separate sanitized commit-eligible summary; raw absolute-path provenance is
  allowed only outside the checkout;
- replaced the normal Docker Compose commands with a unique project, explicit
  external env file, temporary synthetic webroot, port preflight, rendered
  mount inspection, image pull, and guaranteed cleanup trap; and
- added a path-only scan for ignored/untracked raw artifacts and changed final
  reporting to record either open-and-completed or closed-and-skipped outcomes
  for the model and Node gates.

The review also requested Lucide and PropTypes revalidation; they are now in
Task 1 even though neither was held in the source audit. No actionable review
finding remains open in this plan.
