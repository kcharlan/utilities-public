# Dependency Modernization Follow-up Analysis — 2026-09-16

## Purpose

This document analyzes every dependency surface that the
[2026-09-16 dependency modernization audit](dependency_modernization_audit_2026_09_16.md)
did not move to the newest available line. It distinguishes work that is ready
to implement from updates that are correctly gated by release policy or an
explicit product decision. It does not authorize implementation; the companion
implementation plan defines that work.

## Executive conclusion

The remaining work is smaller and more tractable than the audit's hold table
suggests:

- The eleven embedded React applications can move from React 18 UMD globals to
  React 19 ESM modules without introducing an npm build or abandoning their
  single-file/embedded-SPA architecture. A browser probe successfully combined
  React 19.3.0, ReactDOM 19.3.0, Babel Standalone 8.0.5, Tailwind's 4.3.3
  browser package, Recharts 3.10.1, and `@xyflow/react` 12.11.6. The probe
  proves that an exact-version import map is viable for React 19; it does not
  make ESM a prerequisite for the other upgrades. Recharts 3 and React Flow 12
  still publish UMD builds and should first be migrated independently on React
  18 to reduce the diagnostic blast radius. Tailwind 4 is independent again.
- Cognitive Switchyard appears not to use Tailwind utilities, configuration,
  or generated CSS despite loading Tailwind 3. Its correct modernization is to
  prove the load is dead and remove it, not carry an unused dependency to v4.
- Cognitive Switchyard should adopt `httpx2` for its Starlette test client now.
  The remaining AnyIO warning is in the latest released Starlette 1.6.0 and
  should remain visible until an upstream release carries the fix already on
  Starlette's main branch. The suite also emits many unclosed-SQLite
  `ResourceWarning`s; those are not dependency upgrades, but they must be fixed
  before a useful warnings-as-errors gate can be enabled.
- `vid-compiler` should stop depending on the unreleased MoviePy commit. Stable
  MoviePy still has not published the relaxed Pillow constraint, while the
  utility only needs probing, trimming, and concatenation. Replacing MoviePy,
  NumPy, and tqdm with direct FFmpeg/ffprobe calls and standard-library code is
  the durable path.
- Node 24 is still the correct container base on 2026-09-16 because it is the
  Active LTS line. Node 26 is Current and must not replace it until the official
  release schedule promotes it to LTS (scheduled for 2026-10-28).
- The `gpt-5.4` default is an operational behavior/cost choice, not a package
  lag. It appears in both `coding/design_orch` and several distinct Cognitive
  Switchyard roles. A public-safe benchmark must compare it with the
  execution-time current Codex candidate before a role's default changes, but
  different workloads may validly select different defaults.
- Projects classified as audited/current or standard-library/system-only need
  no modernization merely because the audit changed no files. Moving-image
  channels, CDN integrity, and deployment-copy drift are separate policy and
  operations concerns, not hidden version upgrades.

## Scope classification

| Classification | Surfaces | Required action |
|---|---|---|
| Ready compatibility migrations | React 19, Babel 8, Tailwind 4, Recharts 3, React Flow 12 across the embedded SPAs | Decouple the library migrations, use ESM where React 19 requires it, preserve exact CDN package versions, and run each independent project's complete suite. |
| Dead dependency removal | Cognitive Switchyard's Tailwind 3 script | Prove no utility/configuration dependency, remove the script and stale documentation/test assertions, and do not add Tailwind 4. |
| Ready dependency/test-harness cleanup | Cognitive Switchyard's HTTPX 2 path | Replace the direct development dependency on `httpx` with `httpx2`; retain and track the upstream AnyIO warning. |
| Ready dependency elimination | `vid-compiler` MoviePy commit plus NumPy/tqdm | Replace the Python package graph with direct FFmpeg/ffprobe orchestration and a uv-managed standard-library launcher. |
| Evaluation-gated behavior change | `gpt-5.4` defaults in `coding/design_orch` and Cognitive Switchyard | Build role-specific representative benchmarks; change each default only if the candidate meets explicit quality, retry, cost, and latency gates for that role. |
| Date/status-gated platform change | `node:24-alpine` in Docker Webserver | Keep Node 24 now; re-evaluate only after Node 26 is officially LTS. |
| Intentional policy/reproducibility choices | Moving Docker tags, CDN delivery without SRI, private Abacus endpoint, lagging installed copies | Handle under separate reproducibility, operations, or upstream-compatibility work; do not conflate them with package freshness. |
| No upgradeable surface | Audit rows marked “No dependency change,” plus audited/current graphs that resolved current | No action unless requirements change or a new upstream release appears. |

## Evidence and target versions

Versions were rechecked on 2026-09-16. Implementation must repeat these checks
instead of assuming this snapshot remains current.

| Surface | Retained version | Target or decision | Evidence |
|---|---:|---|---|
| React / ReactDOM | 18.3.1 UMD | 19.3.0 ESM | The [React 19 upgrade guide](https://react.dev/blog/2024/04/25/react-19-upgrade-guide) states that UMD builds are removed, recommends ESM CDNs such as esm.sh, and requires the modern JSX transform. |
| Babel Standalone | 7.29.8 | 8.0.5 | The [Babel 8 migration guide](https://babeljs.io/docs/v8-migration) documents the ESM-only package direction and React preset/runtime changes. |
| Tailwind browser runtime | classic Play CDN 3.4.17 | `@tailwindcss/browser` 4.3.3 | The [Tailwind 4 upgrade guide](https://tailwindcss.com/docs/upgrade-guide), [browser package guide](https://tailwindcss.com/docs/installation/play-cdn), [theme-variable guide](https://tailwindcss.com/docs/theme), and [dark-mode guide](https://tailwindcss.com/docs/dark-mode) define the new CSS-first configuration. Tailwind labels the browser package as development-only; these local tools already accept runtime-CDN compilation, so this remains an explicit architecture constraint rather than a newly introduced production claim. |
| Recharts | 2.15.4 UMD | 3.10.1 UMD first; ESM with React 19 later | The official [Recharts 3 migration guide](https://github.com/recharts/recharts/wiki/3.0-migration-guide) calls out internal-state removal and changed customized/active/legend behavior. Package metadata retains a `build-umd` output and peers on React, ReactDOM, and `react-is`. |
| React Flow | `reactflow` 11.11.4 | `@xyflow/react` 12.11.6 UMD first; ESM with React 19 later | The official [React Flow 12 migration guide](https://reactflow.dev/learn/troubleshooting/migrate-to-v12) covers the package rename, named component import, stylesheet path, immutable updates, measured dimensions, and API renames. Package metadata publishes both UMD and ESM entry points, and registry peer metadata accepts React 17 and later; React Flow 12 does **not** require React 19. |
| Starlette test transport | `httpx` 0.28.1 fallback | `httpx2` 2.13.0 | Starlette's current test client recommends `httpx2`; [Starlette release notes](https://github.com/Kludex/starlette/blob/main/docs/release-notes.md) track the transport work. |
| Node container base | Node 24 Active LTS | Retain until Node 26 becomes LTS | The official [Node.js release schedule](https://github.com/nodejs/Release) shows the lifecycle and 2026-10-28 LTS transition. |
| Codex model default | `gpt-5.4` | Evaluation-selected, supported model | The [GPT-5.4 model page](https://developers.openai.com/api/docs/models/gpt-5.4) confirms the retained model's support and reasoning levels; the [current model guidance](https://developers.openai.com/api/docs/guides/latest-model) identifies newer candidates but does not establish workload-specific quality or cost. |
| MoviePy | immutable upstream commit `211e4b15…` | Remove dependency | The latest stable [MoviePy releases](https://github.com/Zulko/moviepy/releases) still stop at 2.2.1. Upstream main relaxes the Pillow bound in its [project metadata](https://github.com/Zulko/moviepy/blob/master/pyproject.toml), but the stable line remains inconsistent and unreleased. |

## Embedded frontend migration

### Affected projects and files

The common React/Babel migration affects these eleven independently maintained
projects. The complete test suite of each project remains its own acceptance
boundary.

| Project | Runtime template | Additional major migration | Primary browser tests |
|---|---|---|---|
| `cognitive_switchyard` | `cognitive_switchyard/cognitive_switchyard/html_template.py` | Remove unused Tailwind; React Flow 12 | `cognitive_switchyard/tests/test_html_template.py`, `cognitive_switchyard/tests/test_e2e.py` |
| `editdb` | `editdb/editdb` | Tailwind 4 | `editdb/tests/test_e2e.py` |
| `expense_dock` | `expense_dock/expense_dock` | Tailwind 4 | `expense_dock/tests/test_e2e.py` |
| `git-multirepo-dashboard` | `git-multirepo-dashboard/git_dashboard.py` | Recharts 3 | `git-multirepo-dashboard/tests/test_html_shell.py`, `git-multirepo-dashboard/tests/test_e2e.py` |
| `harscope` | `harscope/harscope` | Tailwind 4 | `harscope/tests/test_e2e.py` |
| `jtree` | `jtree/jtree` | Tailwind 4 | `jtree/tests/test_e2e.py` |
| `launchmaster` | `launchmaster/launchmaster` | None beyond React/Babel | `launchmaster/tests/test_e2e.py` |
| `mls-tracker` | `mls-tracker/mls_tracker` | Tailwind 4 | `mls-tracker/tests/test_browser_smoke.py` |
| `routerview` | `routerview/routerview` | Tailwind 4; Recharts 3 | `routerview/tests/test_browser_smoke.py` |
| `storage_monitor` | `storage_monitor/storage_monitor` | Tailwind 4 | `storage_monitor/tests/test_browser_smoke.py` |
| `tax2` | `tax2/tax2` | Tailwind 4 | `tax2/tests/test_browser_smoke.py` |

### Architecture alternatives

1. **Decoupled no-build migrations, then exact-version ESM for React 19 —
   recommended.** Upgrade Recharts and React Flow using their current UMD
   builds while React 18 still supplies the expected globals. Remove
   Cognitive Switchyard's unused Tailwind load and migrate each real Tailwind
   consumer independently. Then move React/ReactDOM and Babel together to an
   exact-version ESM import map and module-aware inline JSX; convert Recharts
   and React Flow to ESM in the same project's React step. This temporarily
   touches the chart/graph integrations twice, but isolates their major-version
   behavior changes from the React module-loader change.
2. **One-step ESM conversion.** Move React, Babel, Recharts, React Flow, and
   Tailwind together per project using the already-proven import-map approach.
   This minimizes interim states but makes a browser failure harder to assign
   to one library and is therefore not the default rollout.
3. **Per-project bundle or checked-in compiled assets.** This improves offline
   behavior and can enable content hashing/SRI, but adds Node build tooling,
   generated artifacts, and release synchronization to eleven otherwise
   independent Python launchers. It is a valid later reproducibility project,
   not a prerequisite for current versions.
4. **Continue the version holds.** This has the smallest immediate change but
   does not meet the goal of bringing the surfaces current and allows the
   compatibility gap to grow.

### Probe result and binding integration contract

A disposable Playwright page loaded exact versions of React 19.3.0 and
ReactDOM Client through an import map, `react/jsx-runtime`, Babel Standalone
8.0.5, `@tailwindcss/browser` 4.3.3, Recharts 3.10.1, and
`@xyflow/react` 12.11.6 plus its stylesheet. It rendered a React heading,
computed Tailwind styling, a Recharts SVG, and a React Flow node with zero page
or console errors. The probe changed no repository files and proves
architectural compatibility, not project-level correctness.

The eventual React 19 ESM migration should preserve these constraints:

- Pin every CDN URL to an exact package version. Configure ESM packages that
  have React peers to externalize `react`, `react-dom`, and `react-is` so the
  browser does not load a second framework instance. The import map must cover
  `react`, `react/jsx-runtime`, `react/jsx-dev-runtime`, `react-dom`,
  `react-dom/client`, and a React-version-aligned `react-is`. Inspect the
  browser request/module graph and fail acceptance if any dependency fetches a
  second React or ReactDOM package instance; successful rendering alone is not
  proof of deduplication.
- Use `type="text/babel"`, `data-type="module"`, and explicit
  `data-presets="env,react"`. Import `React` and ReactDOM Client from the import
  map; keep the existing `createRoot` rendering model.
- For the first Recharts step, keep the global contract with the v3 UMD build
  and add an exact, React-version-aligned `react-is` UMD load before Recharts.
  Test real chart behavior affected by the v3 migration—not only the presence
  of an SVG. Convert the globals to ESM imports only during that project's
  React 19 step.
- For the first React Flow step, change from `reactflow` to the v12
  `@xyflow/react` UMD bundle and stylesheet, replace
  `ReactFlowLib.default` with `ReactFlowLib.ReactFlow`, and audit node/edge
  mutations and renamed APIs. Convert the global to ESM imports only during
  Cognitive Switchyard's React 19 step.
- First prove that Cognitive Switchyard has no Tailwind utility/configuration
  dependency, then remove its Tailwind script, README claim, and pin assertion.
  For actual Tailwind consumers, replace each JavaScript configuration with
  CSS-first declarations.
  Where the app toggles a `.dark` class, define
  `@custom-variant dark (&:where(.dark, .dark *));`. Translate custom colors,
  fonts, and other tokens to `@theme` variables. Browser tests must assert
  computed styles for custom tokens and dark mode; a no-console-error assertion
  alone will not catch silently missing CSS.
- Preserve existing Lucide and PropTypes versions unless execution-time
  revalidation finds a newer compatible release. They were current in the
  source audit and are not blockers for the ESM migration.

The ESM-CDN choice retains two known limitations: it still requires network
access at runtime, and modules assembled through import maps generally do not
gain classic script-tag SRI guarantees. Exact pins prevent package-version or
semver resolution drift, but they do not guarantee byte-identical
CDN-transformed output and do not prevent compromise or disappearance. Those
risks already exist for the current CDN architecture and should be addressed
in a distinct vendoring or release-artifact project if offline or byte-for-byte
delivery becomes a requirement.

Before adopting Babel 8 or Tailwind 4, document the browser support contract.
The recommended contract for these local tools is current stable Chromium as
the automated target, with manual clients required to meet Tailwind 4's stated
minimums (Chrome 111, Safari 16.4, or Firefox 128). If a project promises older
browsers, it must retain Tailwind 3.4 or introduce compiled compatibility CSS
instead of silently raising the floor.

### Rollout order

Use independent pilots so a problem is localized before the pattern is copied:

1. `cognitive_switchyard`: prove and remove the unused Tailwind load; correct
   the design document's false React Flow 12/React 19 coupling.
2. `git-multirepo-dashboard`, then `routerview`: Recharts 3 UMD first without
   and then with Tailwind in the same application.
3. `cognitive_switchyard`: React Flow 12 UMD on React 18.
4. `storage_monitor`: first real Tailwind 4 migration without a custom Tailwind
   configuration block.
5. `editdb`, `expense_dock`, `harscope`, `jtree`, `mls-tracker`, `routerview`,
   and `tax2`:
   apply the proven Tailwind contract one complete project at a time.
6. `launchmaster`: pilot React 19/Babel 8 ESM without a chart, graph, or
   Tailwind migration in the same change.
7. Migrate the remaining ten React applications to the proven React/Babel ESM
   contract one independent project at a time; move already-upgraded Recharts
   and React Flow from UMD globals to ESM in their respective projects.

This ordering is a risk-control sequence, not permission to skip any project's
own README, referenced design docs, or complete test suite.

## Cognitive Switchyard test-harness findings

The current environment resolves FastAPI 0.141.1, Starlette 1.6.0, HTTPX
0.28.1, AnyIO 4.15.1, and pytest 9.1.1. A targeted default-warning run of
`tests/test_server.py` passed all 104 tests and emitted 100 warnings:

- One Starlette deprecation warning asks users of `TestClient` to install
  `httpx2`. The project imports FastAPI's `TestClient` and does not directly use
  HTTPX, so `requirements-dev.txt` is the correct dependency boundary.
- One warning comes from Starlette 1.6.0's use of the deprecated
  `anyio.abc.BlockingPortal` alias. Starlette main now uses
  `anyio.from_thread.BlockingPortal`, but no release containing that change is
  available. Do not patch site-packages, pin an unreleased Starlette commit, or
  blanket-filter the warning.
- The remaining warnings are unclosed SQLite database `ResourceWarning`s.
  They are an adjacent project resource-lifecycle defect rather than a package
  hold and are not a completion gate for dependency modernization. Record a
  separate follow-up with the affected fixtures/application owners rather than
  hiding the warnings or expanding this migration to repair them.

The original audit's statement that the suite emits one warning of each kind
describes warning categories, not the total warning count. The implementation
must record exact categories and counts after the full suite so repeated
instances are not understated.

## Codex model-default evaluation

The original hold table names only `coding/design_orch`, but the same literal
is embedded in Cognitive Switchyard's built-in `codex` and `codex-hybrid`
packs, executors, scripts, docs, and assertions. That omission must be fixed in
the inventory, but equality of the current strings is not an architectural
invariant: design orchestration, planning, resolution, auto-fix, and worker
execution are distinct workloads and may select different defaults.

Use `benchmark-llm` to create a fixed, paired, conspicuously synthetic corpus
for each role: `design_orch` orchestration; Switchyard planning; resolution;
auto-fix; `codex` worker execution; and `codex-hybrid` worker execution where
its context differs. The harness records command provenance, elapsed time,
cost, tokens, retries, and attempt artifacts. Compare `gpt-5.4` with the
supported current candidate discovered at execution time; do not freeze this
analysis's current-product recommendation into the plan. Interleave models and
task order, capture exact model identifier, Codex CLI version, date, prompt,
and settings, and report paired per-task results plus dispersion rather than
treating three runs as sufficient evidence. Score:

- task correctness and acceptance-test success;
- verification quality and absence of unsafe/unrequested changes;
- retry/failure rate;
- total and successful-run cost;
- elapsed time.

Set explicit non-regression thresholds before seeing results. A candidate may
become a role's default only if correctness and verification are equal or
better, retry rate stays within the predeclared tolerance, and the user accepts
the observed cost/latency tradeoff. Preserve `MODEL_NAME`, phase-local model
fields, and `CODEX_WORKER_MODEL` overrides as applicable.

Raw benchmark artifacts are not repository deliverables. Configure output
outside the repository, because `commands.jsonl`, exact working directories,
stdout/stderr, failed attempts, and retained branches can expose usernames,
paths, or model-echoed data even when prompts are synthetic. This task's
branch-only constraint also excludes `benchmark-llm`'s built-in
`git_worktree` repo-task source: use a plugin runner with disposable repository
copies outside the checkout, or obtain a new explicit instruction before using
worktrees. Any summary proposed for commit must be independently sanitized and
reviewed under the public-repository policy. Building and locally testing the
benchmark is repository work; actually invoking paid external models requires
explicit user approval.

## Node container-base policy

`docker/webserver/index/Dockerfile` and
`docker/webserver/app_node_Dockerfile` correctly use `node:24-alpine` today.
Updating them to a non-LTS line would violate the reason for the hold. The
implementation task is a status gate, not an unconditional edit:

1. Recheck the official Node schedule and image availability on the execution
   date.
2. If Node 26 is not yet LTS, record the closed gate and make no source change.
3. After promotion, update both images and their READMEs together, rebuild the
   entire isolated Docker Webserver stack from clean inputs, audit both npm
   graphs, and repeat its health, API/configuration, static-first, and nginx
   routing checks.

Base tags remain mutable even after a major-line update. Digest pinning plus a
scheduled refresh cadence is a separate reproducibility decision.

## `vid-compiler`: remove the bridge instead of waiting

`vid-compiler/video_compiler.py` uses MoviePy for media probing, clip trimming,
concatenation, and rendering; NumPy for sample positions; and tqdm for progress.
The stable MoviePy release has not absorbed the Pillow-constraint fix despite
the long-lived upstream commit. Continuing to wait leaves a security bridge as
a permanent runtime dependency.

The replacement should be a Python 3.12+ uv-managed launcher with no Python
runtime packages:

- `ffprobe` returns JSON duration and audio-stream presence.
- Standard-library arithmetic and an injected `random.Random` produce even or
  random sample starts deterministically under test.
- One `ffmpeg` `filter_complex` invocation trims every interval from the shared
  source and concatenates them. For video, each leg uses `trim` plus
  `setpts=PTS-STARTPTS`; when audio exists, the matching leg uses `atrim` plus
  `asetpts=PTS-STARTPTS`. The concat filter sets `v=1,a=1` with audio and
  `v=1,a=0` without it.
- Subprocesses receive argument arrays and never `shell=True`. A per-file
  FFmpeg failure remains best-effort: report it, continue other files, and
  preserve the documented overall zero exit status. Any redesign to make a
  partial batch fail is a separate product decision, not part of dependency
  removal.
- Render to a temporary sibling file and atomically replace the requested
  output only after FFmpeg succeeds; clean up temporary files on failure.
- Preserve the exact sampling semantics: even mode uses the current linspace
  endpoints; random mode samples without replacement from the sorted 1,000
  point linspace grid. Inject randomness only to make that existing algorithm
  deterministic in tests. Preserve segment order, bounded parallelism,
  `h264_videotoolbox`, AAC when audio exists, documented sampling behavior,
  and video-only inputs. Replace tqdm with a
  simple standard-library progress report or omit animation while retaining
  useful completion/error messages.

The conversion also removes the destructive legacy virtual-environment setup
path. Register the launcher in `tools/check_uv_headers.py`, add a tracked
development/test manifest, and add unit plus synthetic audio/video render
coverage. This is preferable to replacing the commit pin with another
unreleased commit or adopting a large new wrapper around commands the project
already requires.

## Items that do not require an upgrade now

- Audit rows marked **No dependency change** are standard-library or
  system-tool projects. They have nothing to bring current until their runtime
  requirements change.
- Rows marked **Audited/current** already resolved current-compatible packages
  or intentionally use system tools. Rechecking them in a future fleet audit is
  sufficient.
- Actual, Excalidraw, and Mermaid intentionally follow moving `latest` image
  channels. Pinning digests would change the update policy and needs a refresh
  process; it is not a missed package upgrade.
- The Abacus bookmarklet's private unversioned endpoint cannot be made current
  through a dependency edit. Continue synthetic converter tests and treat a
  dashboard API break as an upstream compatibility incident without placing
  private exports in this public repository.
- CDN SRI/offline delivery and Docker digest pinning are meaningful security
  and reproducibility improvements, but neither is necessary to resolve the
  version holds analyzed here. They should not silently expand this
  modernization into an asset-supply-chain redesign.
- Installed user-home copies that lag source need an explicit deployment step;
  mutating them is outside this repository plan.

## Cross-cutting acceptance criteria

The modernization is complete only when:

- all eleven embedded SPAs use current React/Babel lines through the proven ESM
  contract, real Tailwind consumers use v4, Cognitive Switchyard no longer
  loads unused Tailwind, and Recharts/React Flow reach their current majors;
  every CDN package version is exact, the documented browser floor is met, the
  ESM request graph contains one React/ReactDOM/`react-is` peer graph, and every
  project's complete suite includes applicable behavioral browser assertions;
- Cognitive Switchyard uses `httpx2`, the HTTPX fallback warning is gone, and
  the precisely scoped upstream Starlette/AnyIO warning remains visible with a
  stable-release recheck trigger; SQLite resource warnings are tracked
  separately rather than hidden;
- `vid-compiler` has no MoviePy, Pillow, NumPy, or tqdm runtime dependency and
  passes unit, launcher-header, CLI, audio, video-only, duration, and failure
  smokes using synthetic public-safe media;
- each model-role default changes only after a paired, repeatable comparison
  and explicit acceptance of spend; code, overrides, docs, and tests agree for
  every role that changes;
- Node images change only after the LTS gate opens and the full isolated stack
  passes; and
- no sensitive or user-specific data enters code, tests, docs, generated
  artifacts, or commits.

## Open execution-time checks

These are intentional revalidation steps, not unresolved design decisions:

- Re-resolve current package/model versions and CDN URL syntax immediately
  before each implementation phase.
- Confirm whether a Starlette release containing the AnyIO alias fix has
  shipped; prefer a stable release when available.
- Confirm Node 26's official lifecycle status before changing Dockerfiles.
- Confirm ESM CDN peer externalization and browser support in each project's
  actual supported browser, not only the disposable probe.
- Obtain explicit approval before running paid external model comparisons.

## Adversarial review disposition

An independent, read-only adversarial review examined the source audit, this
analysis, repository policy, and the key frontend, test-harness, model,
Docker, benchmark, and video-compiler surfaces. Every substantive finding was
verified against repository source or package metadata and corrected:

- decoupled Recharts 3 and React Flow 12 UMD upgrades from the React 19 ESM
  requirement, while retaining ESM as the viable React 19 architecture;
- completed the ESM peer graph with `react-dom` and `react-is` and added a
  network/module-graph deduplication check;
- reclassified Cognitive Switchyard's unused Tailwind load as removal;
- changed model evaluation from a forced cross-project result to independent
  role-based decisions, strengthened experimental provenance, and required raw
  artifacts outside the public repository without worktrees for this task;
- preserved `vid-compiler`'s documented per-file continuation/zero-exit and
  exact sampling semantics;
- removed SQLite cleanup from the dependency completion gate;
- defined a concrete browser floor and required correction of Cognitive
  Switchyard's false React Flow 12/React 19 design statement; and
- narrowed exact-pin guarantees to package-version resolution, not immutable
  CDN bytes.

The review also challenged whether three model trials could justify a default
change. The fixed count was removed in favor of predeclared thresholds, paired
tasks, interleaving, exact provenance, and variance reporting. No actionable
finding remains open in this analysis.
