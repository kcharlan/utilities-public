# Backtest Monorepo Port Implementation Plan

> **Superseded:** [backtest_simple_port_implementation_plan.md](backtest_simple_port_implementation_plan.md) is the sole active specification. This document is retained as history; its withdrawn contracts are not implementation or acceptance gates.

**Status:** Proposed for review; no implementation or deployment authorized by this document.
**Inspection date:** 2026-10-01.
**Owner clarification incorporated:** 2026-10-01; ordinary UI defaults are illustrative, not personal financial values. No explicit third-party data redistribution permission has been obtained.

**Goal:** Admit a sanitized Market Atlas project into `Calculation tools/backtest`, make its static release reproducible and locally deployable, and document and verify the public-source/private-runtime boundary.

**Architecture:** Preserve the existing vanilla-JavaScript application and deterministic engine. Import only individually reviewed files, retain the checked public market-data snapshot subject to the data-rights gate, and add a dependency-free Node static packager. Deploy immutable asset generations before atomically replacing the entry HTML; extend the existing read-only deployment audit to verify the resulting artifact.

**Tech stack:** Classic browser scripts; CommonJS modules and `node:test`; Node 24 or later for maintainer tooling; pinned Playwright Chromium for browser-test provisioning; Python in a virtual environment, pandas 2.3.2 and xlrd 2.0.2 for data maintenance; existing Zsh deployment audit and Docker/Nginx static serving.

**Executor guidance:** Use normal feature-branch development in the existing monorepo checkout. Do not create a worktree unless explicitly requested. Execute the independently reviewable tasks below only after an explicit instruction to implement. Requirements, invariants, negative cases, and verification commands are binding; routine implementation and test bodies belong to the executor. Do not add subagent work merely because an older source plan recommended it.

## 1. Findings and evidence

All monorepo-relative paths below are rooted at `~/source/utilities-public`; all source-relative paths are rooted at `~/webroot/calculators/backtest`. These are portable home-relative descriptions, not personal absolute paths suitable for copying into public docs.

| Area | Observed state | Consequence |
|---|---|---|
| Source identity | Market Atlas resides in the current working directory's `backtest/`; that source has no Git repository. | Import a reviewed file snapshot, never initialize or import history from the deployment tree. Recheck source identity and changes before import. |
| Postal information | Content searches across non-generated source, tests, docs, and data found no ZIP/postal controls or suggestions. The two word `zip` occurrences are Python's sequence function. Five-digit tokens also occur as money, timing constants, and portions of data decimals. | The user's ZIP example is a threat to investigate, not an established finding in this version. Do not replace arbitrary numbers or public historical data with a blanket regex. If another version is identified, inspect it and revise the plan before importing. |
| Demonstrable privacy surfaces | The README and several historical plans contain a personal absolute home path. Docs include an HTML mockup and scenario outputs requiring separate admission review. The owner has clarified that ordinary UI defaults are not personal finances; individual fixtures still require contextual source review. | Retain illustrative defaults with synthetic labels; do not treat round financial examples as personal data without evidence. Continue auditing prose, comments, fixtures, screenshots if present, and generated content. Do not repeat removed private literals in public reviews or commit messages. |
| Runtime | Nine local scripts, inline CSS, local font stacks, SVG charts; no browser network data fetch or CDN dependency. `file://` works. | Preserve offline operation, script order, module namespaces, and browser-first delivery. No backend or frontend-framework migration is needed. |
| State | Inputs, pins, comparisons, and exports are in memory. Only `market-atlas-theme` is persisted in localStorage. | Preserve this boundary. Do not add a served private-default file or scenario persistence during the port. Exports can contain user-entered financial values and belong outside Git. |
| Source “build” | `build/compile_market_data.py` downloads/validates public XLS data and produces `market-data.js` and `.csv`. There is no current static packaging step. | Distinguish data refresh from release packaging. Deployment must not download or regenerate history. |
| Data snapshot | 154 contiguous annual rows, 1872–2025, generated 2026-08-20. Pre-1928 bills are null and quality is reconstructed; 1928+ is Damodaran data. | Preserve both generated files together and prove parity; do not introduce an annual update into the port. |
| Ignoring compiler source | Monorepo root `.gitignore` ignores any `build/` directory. Source `build/.gitignore` covers only `.venv/` and `cache/`. | Rename the compiler directory to `data/` in the imported project rather than forcing files into Git or changing global ignore behavior. |
| File modes | Existing generated JS/CSV files are `0600`, produced through `NamedTemporaryFile`. | Define readable deployment modes explicitly: regular files `0644`, directories `0755`. Source-copy mode preservation is inappropriate for this artifact. |
| Test portability | Browser tests hardcode `/Applications/Google Chrome.app/...` and skip when absent. Historical tests skip when the dataset is absent. | Missing prerequisites must fail release validation, not produce an apparently successful incomplete test run. |
| Calculator grouping | `Calculation tools` has four single-file apps, a pinned Playwright/http-server harness, Node tests, and independent docs. | Add a separately maintained nested project with its own complete test command. Preserve the sibling suite and document both project boundaries. |
| Deployment tooling | `tools/check_local_deployments.zsh` is an audit, not a general installer. Its `copy_mappings`, `home_projects`, and Model Sentinel logic do not cover static artifacts. | Add a narrow backtest installer and static-artifact audit integration; do not pretend adding a direct mapping deploys a built site. |
| Existing web stack | `docker/webserver/docker-compose.yml` binds port 7711 to loopback and mounts external `WEBROOT_PATH`. Nginx serves static files first and uses dynamic index fallback. | Keep the existing route and mount contract. Static asset deployment needs no container rebuild/restart. Validate the actual mount and HTTP bytes before accepting local deployment. |
| Legacy served tree | The live backtest directory contains source docs, tests, compiler, venv/cache, and `.DS_Store`. A project archive exists under the parent calculator `_backups/`. | The first transition must remove this project’s development material from the web-served tree without losing it. Never place migration backups inside webroot. |
| Repository workflow | Target checkout was clean on `main` when inspected. Root `agents.md` requires strict public-data admission and complete affected-project testing. PKM records specify feature branches rather than worktrees. | Preserve unrelated work if the state changes; use `codex/backtest-monorepo-port` when implementation is explicitly requested. |

### Validation actually performed during planning

- Source root: `node --test tests/*.test.js` — **258 passed, 0 failed, 0 skipped**, including the three real-Chrome browser tests; Node v24.15.0.
- Source `build/`: `./.venv/bin/python -m unittest test_compile_market_data` — **37 tests, OK**; inspected venv versions: Python 3.14.7, pandas 2.3.2, xlrd 2.0.2, NumPy 2.5.2.
- The compiler suite uses synthetic frames and controlled temporary files. No market-data refresh or live deployment was performed.
- These establish the inspected source baseline only. They do not validate the future port, new tooling, or monorepo integration. Planning changes only this Markdown document, so no unrelated monorepo suites are required now.

### Prior decisions incorporated

PKM resolution for the current calculator directory returned no registered project; global lookups were performed with that returned scope. The separately inspected monorepo resolved to project 6, `utilities-public`; deployment, calculation-tools, privacy, and workflow searches and component-tag queries supplied the relevant project context.

Binding decisions include history-free public admission, configuration outside source, normal feature branches, copied deployments as separate release targets, protected backups, canonical macOS path comparison, explicit metadata contracts, and static webroot deployment without restarting the webserver. See the current `agents.md`, `docs/privacy_scrub_design.md`, and `docs/local_deployment_sync.md`; PKM knowledge entries 127, 152, 168, and 225 corroborate those choices.

## 2. Design decisions and alternatives

| Approach | Benefit | Problem | Decision |
|---|---|---|---|
| Copy runtime files in place, entry HTML last | Minimal tooling | Existing pages can load mixed script generations; raw files and stale development material need separate cleanup; no artifact identity | Reject for repeatable releases. |
| Flatten the app into one generated HTML | One replacement file | Rewrites an established multi-file/module contract, enlarges inline scripts, complicates structure tests and CSP, obscures provenance | Reject for this port. |
| Allowlisted package with versioned assets and stable entry HTML | Small deterministic build, coherent page loads, easy rollback, preserves source modules | Adds a modest build/installer/audit contract and retains old safe generations | **Recommended.** |

The import preserves behavior. It does not change withdrawal strategies, financial math, tax semantics, yearly timing, portfolio allocation, lifestyle metrics, cancellation, cache behavior, or design. Privacy-related labels and removal of any verified personal defaults are the only intended application changes. Public historical aggregate market series and published benchmark parameters are distinct from personal holdings or financial scenarios; their origin must be documented rather than “sanitized” into fabricated data.

The intended URL is `/calculators/backtest/`, with `/calculators/backtest/index.html` also working. Relative asset URLs preserve both HTTP subdirectory serving and direct file opening. No source-repository symlink is installed into webroot.

### Owner clarification: defaults and the custom barbell method

The owner reviewed the UI and confirmed that the ordinary starting balance, fees, and other displayed assumptions were defaults rather than supplied personal financial values. This closes the broad defaults-provenance admission question. Retain them as illustrative examples, label them conspicuously synthetic, and do not ask the owner to re-identify these same fields or change their values merely because the app models finances.

The owner's possible contribution was the custom barbell strategy. Contributing a method is not evidence that it embeds personal financial data. Inspection of `STRATEGIES.barbell` in source `engine.js` shows configurable `initialRate`, `reserveYears`, `reserveMix`, `spendRule`, and `refillRule`. Its reserve dollar targets derive from the supplied simulation balance/spending, rather than an embedded account or personal portfolio balance. Preserve the custom method and its behavioral tests; describe it neutrally as a configurable custom strategy, not a published benchmark or the owner's actual investment holdings.

The clarification concerns UI defaults; it does not certify every historical fixture, comment, or mockup as synthetic. The executor must still classify them against the source and their mathematical purpose. Preserve established historical acceptance controls. Escalate only a specific newly discovered item with evidence of personal provenance, using its field/scenario/location without disclosing the value. A blanket request for the owner to audit all financial numbers is unnecessary.

## 3. Publication and privacy boundary

### Admission inventory

Copy the following only after each has been reviewed in a private staging directory outside the public working tree:

- Runtime source: `index.html`, `app.js`, `engine.js`, `views.js`, `stats.js`, `lifestyle.js`, `charts.js`, `csv.js`, `format.js`.
- Public snapshot, after the rights/provenance gate: `market-data.js`, `market-data.csv`.
- Existing Node coverage: `tests/app-render.test.js`, `browser-smoke.test.js`, `charts.test.js`, `config-apply.test.js`, `engine.test.js`, `export.test.js`, `format.test.js`, `historical.test.js`, `lifestyle.test.js`, `stats.test.js`, `strategies.test.js`, `structure.test.js`, `sweep-render.test.js`, `theme.test.js`, and `window-render.test.js` (all under `tests/`), plus `tests/README.md`. Verify the actual inventory against the current source; changes since inspection require classification, not blind copying.
- Compiler source, renamed: `build/compile_market_data.py` → `data/compile_market_data.py`; `build/test_compile_market_data.py` → `data/test_compile_market_data.py`; `build/requirements.txt` → `data/requirements.txt`; rewrite `build/README.md` as `data/README.md`.
- Rewrite the project README; extract current behavior and useful lessons into new maintained documentation. Do not import the old docs directory wholesale.

Never import `.DS_Store`, `.venv`, caches, bytecode, private exports, screenshots of personal scenarios, logs, archives, old backups, or any Git metadata. Preserve the original historical docs privately. Replace their useful current contracts with `docs/architecture.md` and a sanitized `docs/LESSONS_LEARNED.md`; retire their obsolete “webroot is source” workflows. Audit the mockup separately only if its current design value justifies later inclusion; it is excluded from this port.

### Sanitization procedure

1. Make a restricted local literal inventory from discovered private values and any already available private scrub inventory. Keep it outside Git and webroot; report category, file, location, and count without printing matched values. Include encoded/escaped forms, source-map/string representations, and variants such as personal home paths.
2. Classify every input default, suggested value, fixture, comment, doc example, and rendered mockup. Remove personal location suggestions. Where a text ZIP example is needed, use `ZIP_CODE` as a conspicuous placeholder; do not pretend it is valid runtime input. Do not introduce a postal feature into Market Atlas solely to demonstrate sanitization.
3. Apply the owner clarification above: retain ordinary UI defaults as synthetic examples and preserve the generic custom barbell method. Label retained scenario defaults and artificial fixtures unmistakably synthetic. Published historical acceptance configurations and dimensionless/simple mathematical fixtures can retain their canonical numbers with public origin or synthetic purpose stated. Only if a specific additional value is established to represent personal finances, replace it and its genuinely coupled assertions; never weaken financial-result assertions to conceal a regression.
4. Keep private scenarios in page memory and optional user-managed exports outside the repository. Do not automatically reconstruct personal settings from source, browser history, or backups; no new runtime config facility is needed by this application.
5. Scan the proposed complete admitted tree, generated package, and eventual staged diff for private literals, credentials/high-entropy candidates, personal paths, private hosts, embedded metadata, and unsupported binary/archive content. Review human-readable context as well as scanner results.
6. Repeat admission checks against a fresh clone of the local sanitized branch before any push. The private literal inventory and reports containing private excerpts must never enter source, test fixtures, Git objects, CI artifacts, or commit messages.

Five-digit matching alone is not a privacy verdict. Financial numbers, milliseconds, year sequences, color literals, and public data decimals can collide with ZIP-like patterns. A harmless collision requires a documented safe origin, not a blanket ignore rule or a permanent scanner allowlist containing real private literals.

### Data provenance and rights gate

Create `DATA_SOURCES.md` before admitting the generated snapshot. It must identify exact input workbook hashes from the existing cached sources, selected series, source versions, transformed column lineage, date/range/row count, and output hashes. Hash only the known public workbook files; do not inspect arbitrary caches as if they were public.

The owner confirms that no explicit redistribution permission was obtained: the agent built and used the app and downloaded the data. Do not ask the owner again whether permission exists. This does not establish either unrestricted redistribution rights or a prohibition; the executor must investigate the applicable primary-source terms and upstream basis and record a concrete evidence-backed admission decision.

The current primary-source evidence is:

- Damodaran permits occupational/research use, requests attribution, and asks users not to resell the site's data. Document those conditions separately from project code licensing. [Damodaran usage rules](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/guide.html).
- Shiller's maintained page distributes the stock dataset and explains its upstream sources and transformations, but this review did not locate an explicit redistribution license there. Availability alone is not evidence of an unrestricted license. The legacy Yale page failed to load during inspection. [Shiller dataset and lineage](https://shillerdata.com/).
- Inflation lineage varies by period. The compiler takes 1872–1927 CPI changes from Shiller's workbook; Shiller identifies the pre-1913 price index as Warren–Pearson, spliced to BLS CPI in January 1913. Include that upstream reconstruction in the rights/provenance investigation rather than describing the entire series as BLS data. [Shiller inflation lineage](https://shillerdata.com/). The compiler uses FRED CPIAUCNS via Damodaran from 1928 onward. BLS published material is generally public domain with attribution requested, which does not by itself settle rights for the entire compiled dataset. [BLS copyright information](https://www.bls.gov/bls/linksite.htm), [FRED CPIAUCNS](https://fred.stlouisfed.org/series/CPIAUCNS).

Before staging the historical snapshot for public publication, resolve and record the applicable attribution/redistribution basis, including Shiller/upstream material. Preserve notices; do not apply a newly invented blanket open-source license to third-party data. No root project code license was located during inspection; do not select a repository-wide license as part of this port.

The data gate blocks admitting/staging/committing the actual historical dataset to the public repository and publishing an artifact that contains it. It does not require a blanket halt before independent implementation. Investigate terms first, then continue privacy-safe source preparation, compiler changes, synthetic fixture tests, packager/installer/audit development, and documentation while any data question remains unresolved. Keep the actual unresolved historical dataset and any data-dependent full-release testing in a private scratch copy outside the public working tree. Do not commit an incomplete public release or report the historical/full-release gates as passed while their data prerequisite is absent.

If primary-source investigation supports the intended redistribution, document the basis, attribution and restrictions and proceed without another generic permission question. If evidence remains insufficient or materially conflicts with the intended distribution, return a concrete decision packet: source and upstream series, exact relevant terms with primary-source links, the proposed inclusion/use, what is uncertain, and practical alternatives with their effects on offline operation and historical verification. Ask only for the decision that cannot be resolved from those sources. Do not contact data owners on the user's behalf unless explicitly authorized. Do not publish the data merely because it was downloadable, silently replace it with fake returns, remove the historical tests, or claim the planned offline public release is complete. A local-data-only distribution would materially change the design and needs an explicit revised decision.

## 4. Target file map

Use the existing modules as the reference implementation. New interfaces below are proposed contracts to implement, not existing functions.

| Path | Responsibility |
|---|---|
| `Calculation tools/backtest/index.html` and existing eight application JS files | Sanitized source app; same namespace and load-order contract; the ninth script is the paired market-data artifact below |
| `Calculation tools/backtest/market-data.js`, `market-data.csv` | Paired, checked public data artifacts |
| `Calculation tools/backtest/data/{compile_market_data.py,test_compile_market_data.py,requirements.txt,requirements.lock,README.md}` | Renamed data-maintenance project, reviewed complete dependency lock; cached inputs moved outside repo |
| `Calculation tools/backtest/DATA_SOURCES.md` | Public-safe data lineage, attribution, provenance, and rights record |
| `Calculation tools/backtest/README.md`, `tests/README.md`, `docs/{architecture.md,LESSONS_LEARNED.md}` | Current run/build/test/privacy/maintenance contracts |
| `Calculation tools/backtest/package.json`, `package-lock.json`, `.gitignore` | Independent Node maintainer commands and pinned browser-test dependencies; runtime still dependency-free |
| `Calculation tools/backtest/tools/build_static.mjs` | Pure artifact construction plus explicit output-writing CLI |
| `Calculation tools/backtest/tools/deploy_static.mjs` | Local install, dry-run, controlled legacy adoption, private rollback receipt |
| `Calculation tools/backtest/tests/{privacy.test.js,dataset.test.js,static-build.test.js,static-deploy.test.js}` | Meaningful public-admission, data, packager, and installer regressions |
| `Calculation tools/backtest/tests/{browser-smoke.test.js,historical.test.js}` | Port existing browser/historical coverage without skips |
| `Calculation tools/backtest/tests/helpers/browser-target.cjs`, `tests/run_artifact_browser.cjs` | Browser provisioning and file/HTTP artifact runner; helpers stay outside `*.test.js` discovery |
| `tools/check_static_deployments.mjs`, `tools/tests/check_static_deployments.test.mjs` | Read-only static comparison and fixture coverage |
| `tools/check_local_deployments.zsh`, `tools/tests/test_check_local_deployments.zsh` | Register the static scope and invoke/check the helper, retaining every existing audit guarantee |
| `Calculation tools/README.md`, root `README.md`, root `agents.md`, `docs/local_deployment_sync.md` | Discovery, project boundaries, validation matrix, static deployment and rollback instructions |

`data/` avoids the root `build/` ignore rule without changing global policy. Keep `dist/`, node_modules, test output, local venvs, and accidental user exports ignored; mutable inputs/cache belong outside the repository, not merely ignored inside it. Use targeted export patterns such as `market-atlas-*.csv`, an accidental `exports/` directory, and cached XLS files; never blanket-ignore all CSVs and hide the maintained `market-data.csv`. No webserver/Compose/Nginx source changes are planned.

## 5. Load-bearing contracts

### 5.1 Application and data invariants

Preserve script order:

`market-data.js → format.js → stats.js → views.js → lifestyle.js → charts.js → csv.js → engine.js → app.js`.

Preserve `BacktestEngine` and the frozen `MarketAtlasFormat`, `MarketAtlasStats`, `MarketAtlasViews`, `MarketAtlasLifestyle`, `MarketAtlasCharts`, and `MarketAtlasCsv` namespaces. Keep pure modules DOM-free and deterministic, the pre-paint theme script small, and existing size and contrast guards intact.

Keep `simulate(yearSequence, strategy, params, options)` and its return shape `{ rows, metrics }`. Preserve the withdrawal → returns → fees → rebalance ordering, effective-tax gross-up, failure-year accounting, and CPI timing. Preserve all fixed-real, fixed-percent, Guyton–Klinger, and barbell coverage.

For the pinned 1928–2025 historical subset, retain 69 complete 30-year windows: 50/50 fixed-real at 4% survives 64, failing in 1964, 1965, 1966, 1968, and 1969; worst safe rate is about 3.67% in 1966 under the existing tolerance. Retain the 75/25 assertions (65 surviving; worst about 3.80%). Dataset refresh must not implicitly expand or invalidate this pinned historical control.

Lifestyle remains after-tax retirement-start dollars regardless of the display toggle. Failed complete windows have zero floors and padded unfunded spending; partial observed windows are unpadded and excluded from complete aggregates. Need resolves once from the live configuration and applies to pinned comparisons. Frontier values use one common complete-window start cohort. Maintain latest-wins scheduling, cancellation and stale-export guards, formula-safe CSV serialization, namespace boundaries, keyboard access, theme contrasts, and narrow-screen behavior.

### 5.2 Static artifact format

Export from `tools/build_static.mjs`:

```text
RUNTIME_ASSETS: readonly string[]
buildArtifact({ sourceRoot, readFile? })
  -> Promise<{ artifactId: string, files: Map<string, Buffer>, manifest: object }>
writeArtifact(artifact, outputDirectory) -> Promise<void>
```

`buildArtifact` reads but never writes, never accesses the network, and does not evaluate application JavaScript. The optional reader supports in-memory synthetic tests and the audit's validated source membership. Restrict reads to the explicit allowlist; reject missing/nonregular/symlink inputs and unexpected script declarations. Callers must ensure the project and input ancestors are ordinary directories as well.

Runtime assets are the nine script files, `market-data.csv`, and the reviewed `DATA_SOURCES.md`. Treat the source `index.html` as a separate template input. Include no tests, compiler, package files, docs directory, private state, source maps, or local build caches.

Artifact identity is SHA-256 of the UTF-8 bytes of `JSON.stringify({ formatVersion: 1, inputs }) + '\n'`, with object keys inserted in that exact order. `inputs` is sorted by ASCII project-relative POSIX path and each record's keys are inserted as `{ path, sha256 }`; hashes are lowercase 64-character SHA-256 hex. Include the original HTML, every runtime asset, and the actual `tools/build_static.mjs` source bytes as a tooling input (never an installed asset). Pin serialization with a known-answer synthetic test. No absolute paths, timestamps, usernames, environment values, working-tree location, or mutable Git branch names enter artifact identity or packaged bytes. Increment the format version when packaging rules change. Hashing the builder also prevents an accidental missed version bump from reusing a prior generation identity. Public source attribution changes invalidate the release identity too.

For artifact ID `H`, produce:

```text
dist/index.html
dist/assets/H/market-data.js
dist/assets/H/{format,stats,views,lifestyle,charts,csv,engine,app}.js
dist/assets/H/market-data.csv
dist/assets/H/DATA_SOURCES.md
dist/assets/H/manifest.json
```

Rewrite the nine recognized script `src` attributes in the copied HTML to `assets/H/<name>`, preserving exact order and the inline theme script. Reject extra/missing/duplicate/external script references rather than silently packaging a changed app. Add one compact attribution anchor in source HTML with `href="DATA_SOURCES.md"`; packaging rewrites that exact recognized `href` to `assets/H/DATA_SOURCES.md`. Preserve fragment links such as the existing skip link. Both source and packaged notice links must resolve. No other HTML behavior changes. Never use root-absolute asset URLs or source-location `<base>` tags.

Manifest schema version 1 contains keys in this order: `schemaVersion: 1`, `artifactId`, `inputs`, and `files`. `inputs` uses the identity records above; `files` is ASCII-path-sorted output records whose keys are inserted as `{ path, sha256, size, mode }`, where `size` is a byte count and `mode` is the string `"0644"`. Serialize with `JSON.stringify(manifest, null, 2) + '\n'`. Output paths are artifact-root-relative and include the final entry HTML and 11 runtime assets, but exclude the manifest itself to avoid recursive hashing. Store the manifest inside its immutable generation, not beside `index.html`; there is only one mutable activation file. No secret/environment values are recorded. Recompute hashes from bytes, not metadata alone.

Build output has regular files `0644` and directories `0755`, independent of source umask/modes. The build CLI accepts `--out PATH` (default: the project `dist/`); reject source overlap and unsafe existing/unowned output layouts before replacement. Tests prove identical inputs in different roots/times produce identical artifacts, JS/CSV remain unchanged, and source bytes are not mutated. Do not minify or bundle modules. Deployment operates only on the freshly verified output; ordinary build requires no Python, cached workbook, or internet.

### 5.3 Installer and rollback

CLI contract for `tools/deploy_static.mjs`:

```text
--webroot PATH           default: UTILITIES_WEBROOT_DIR or ~/webroot
--dry-run               validate and describe changes without destination writes
--adopt-legacy          explicit one-time adoption of an existing unmanaged backtest tree
--rollback RECEIPT      restore a receipt-owned previous entry or first-adoption tree
```

The installed root is always `<webroot>/calculators/backtest`, not an arbitrary folder relative to the shell's cwd. Reject filesystem root, the source repository, canonical aliases of either, and symlinks/nonregular objects at managed path components. Source location is derived from the tool file. Require the release-input files/tooling to be committed, tracked, and clean for live installation; development builds and synthetic fixture tests can use an explicit injected source context. Rollback verifies its receipt/backups/live entry independently and does not require a clean current source checkout or regenerate old assets. Record release commit and artifact ID in a private receipt, not in browser assets. Do not download data or install dependencies during deployment. Support one maintainer deployment mutation at a time; use an exclusive lock in the private backup/state area, release it on normal exit/signals, and never automatically break an unexplained lock. Dry-run does not acquire a lock or create backup/state directories.

Private receipt schema must bind `schemaVersion`, canonical `sitePath`, operation (`install`, `update`, or `adopt`), validated source commit, `fromArtifactId` (or null), `toArtifactId`, `toEntrySha256`, previous-entry SHA-256/mode when present, and only receipt-directory-relative backup names. Reject unknown schema, traversal/absolute backup names, symlink/nonregular receipts/backups, or a different canonical site. Before rollback or automatic recovery, require the live entry to match the receipt's expected activated bytes, or the documented interrupted-adoption state; otherwise refuse to overwrite a later deployment or local modification. Test this condition. A private receipt is recovery metadata, not an authenticity claim about public content. Rollback of a fresh install restores prior absence by removing only its exactly verified receipt-owned runtime tree; any extra/unowned content causes refusal. That scoped recovery is distinct from pruning old generations during upgrades.

For an already managed deployment:

1. Build in a private stage outside webroot, verify the complete inventory and hashes, and check destination metadata before any mutation. Reject ACL/extended-metadata conditions the installer does not preserve; do not silently erase them. Keep the scope to the local single-owner filesystem, not a multi-user deployment framework.
2. Verify the existing deployment is a known valid managed layout. Unknown files, altered current assets, or invalid receipts/manifests fail the preflight; preserve them for review instead of overwriting apparent drift. Normal drift audit remains read-only.
3. Back up the previous entry bytes and mode, and write a private receipt under `~/.utilities-deploy-backups/` (directories `0700`, backup/receipt files `0600`). Finish that receipt before changing the live entry. Keep source/runtime metadata separately so protected backup modes do not corrupt restored deployment modes.
4. Copy the complete new asset generation via a same-parent temporary directory and rename it to `assets/H`. Reuse an existing generation only after exact inventory/hash/mode verification. Never overwrite existing immutable assets.
5. Stage new `index.html` in the destination directory, verify its bytes and `0644` mode, then rename over the old entry. This is the activation commit point. The prior entry remains active if any earlier step fails. If post-activation validation fails, restore the prior entry atomically and report both deployment and rollback errors if recovery also fails.
6. Retain old admitted generations for pages that loaded the previous HTML and for rollback. No automatic pruning or `rsync --delete`. Temporary served stages may contain only already sanitized runtime files and must be cleaned on normal failures/signals.

Old HTML continues to reference its own `H`; new HTML references the new generation. An interrupted build/deploy cannot produce an entry referencing incomplete assets. The immutable manifest carries that generation's entry hash, so no separately replaced root manifest can disagree with the active HTML. On rollback, restoring the entry restores the generation reference.

For first deployment into the currently unmanaged source tree, `--adopt-legacy` is required. The executor first verifies a complete private backup of the old tree, including maintenance material necessary for recovery, outside webroot. Preserve legacy venv symlinks as symlinks without following them; never chmod their interpreter targets. Record original regular-file/directory modes before applying restrictive backup modes so recovery can restore them. Do not apply the runtime input prohibition on symlinks to this separately quarantined legacy backup. Require the off-webroot quarantine location to be on the same filesystem as the live legacy tree; fail preflight without modifying the live tree if this condition cannot be met (no destructive cross-device copy/delete fallback). Move only this project's legacy tree out of the served path and install the verified runtime-only tree. This initial two-rename adoption can briefly leave the route unavailable; do not describe it as atomic or promise uninterrupted service. If installation fails between moves, restore the legacy directory. Do not stop/restart the webserver to hide the distinction.

Inventory the known backtest archive under the calculator parent's `_backups/`; move this project's confirmed archive to the protected backup area, preserving it and recording original mode for recovery. Leave unrelated archives and calculators untouched. Confirm no backtest development/private recovery material remains web-served. Never remove the old source or backups before backup verification succeeds. A legacy-tree rollback restores the old exposure profile and is an emergency recovery action, not a compliant final deployment.

### 5.4 Read-only audit integration

`tools/check_static_deployments.mjs` compares the expected in-memory artifact with the actual deployment. It must not run the compiler, install a browser, write `dist`, copy files, read private scenario/configuration content, or fix anything. Integrate it into `tools/check_local_deployments.zsh` after the existing stage-0 index/source-state validation.

Extend `audited_scopes` to include the backtest release inputs and helper/tooling required for this audit. Pass a bounded, NUL-safe validated path inventory from the audit's private temporary directory. The expected source uses the current validated index membership and regular working-tree files, matching the existing audit contract; it is not silently substituted with HEAD or a remembered manifest. Untracked inputs cannot become release sources. Staged additions are visible; missing required indexed input, pending deletion of a required input, merge stages, unsupported indexed types, sparse entries, and failed Git collection suppress any static `OK` result. Non-runtime docs do not become required installed files.

Resolve destination as `UTILITIES_WEBROOT_DIR`, defaulting to `<UTILITIES_LOCAL_ROOT or HOME>/webroot`, so tests can isolate every destination. Preserve the existing environment override and private-temp conventions.

Verify exact current entry bytes, current generation ID, complete runtime inventory, manifest canonical structure, actual hashes/sizes, file/dir modes, and regular object types. A forged or stale deployed manifest cannot override expected source. Check for unexpected root content. Retained older generation directories are intentional only when they use the recognized ID/schema, contain the exact runtime inventory with internally matching hashes and valid modes, and are admitted public releases. Unrecognized trees/files are aggregate drift findings, not ignored user state. The audit does not claim cryptographic authenticity of old locally managed releases; trust is the prior public admission and owner-controlled deployment history.

Report categorized aggregate failures without printing private unknown filenames or bytes. Missing Node or invalid helper source must fail this audit component explicitly. Keep all current direct-copy, Model Sentinel, protected-config, history, mode, source-state, and read-only guarantees unchanged. No generic change to top-level project stale detection is needed.

## 6. Implementation tasks

### Task 1 — Establish the exact import snapshot and sanitize it

**Files:** private staging/inventory outside repo and webroot; admitted project files listed in section 3; new `tests/privacy.test.js`.

- [ ] Re-read root and any newly present nested instructions, record clean/dirty state, and create the normal feature branch after implementation authorization. Do not discard unrelated modifications.
- [ ] Resolve the ZIP/source discrepancy if new information arrives. Reinventory current source, preserve a restorable private snapshot, and record file hashes. Prevent an editor change during admission from silently entering the snapshot.
- [ ] Treat the broad defaults question as answered by the owner clarification in section 2. Preserve illustrative UI defaults and the generic custom barbell method; review fixtures for their individual origin and mathematical purpose. Request clarification only for a concrete new personal-data finding, not for all default financial fields again.
- [ ] Review and sanitize the allowlisted files privately, including financial-value provenance and personal paths. Investigate primary-source data terms before dataset admission; no explicit owner permission exists to retrieve. Resolve the data-admission gate before staging the dataset, but continue independent privacy-safe tasks if that gate remains open. Import no historical docs or mockups wholesale.
- [ ] Add durable privacy regressions using synthetic forbidden-marker fixtures, with any real literal scan supplied privately outside the test code. Assert no personal home path pattern, location-suggestion mechanism, remote runtime assets, or newly persisted scenario inputs enters admitted runtime content. Do not encode real private literals in the regression test.
- [ ] Explicitly label fictional defaults/fixtures; preserve canonical public benchmark math. Scan complete admitted files and stage only reviewed content. Verify compiler/data/tests are present with `git ls-files` after explicit staging.

**Acceptance:** Public tree contains exactly the reviewed source and documented additions, no sensitive literals or private binary artifacts; source snapshot identity is known; all baseline contracts are preserved. Stop admission of the affected material on unresolved evidence, not all independent work or an arbitrary empty scanner result. Track any remaining dataset/full-release dependency explicitly.

### Task 2 — Port data maintenance and prove snapshot parity

**Files:** `data/*`, `DATA_SOURCES.md`, project `.gitignore`, `tests/dataset.test.js`, `tests/historical.test.js`.

- [ ] Rename `build/` to `data/` for compiler code/docs/tests. `ROOT = Path(__file__).resolve().parents[1]` still identifies the project root; preserve that behavior.
- [ ] Change compiler cache location from its own directory to `MARKET_ATLAS_DATA_HOME` or `~/.cache/market-atlas`; test it with private temporary homes. Preserve existing `CACHE` patch-based tests, validated manual workbook arguments, download size/format/sheet checks, last-good-cache behavior, reconciliation, and pair rollback.
- [ ] Add an explicit optional `--generated-date YYYY-MM-DD` argument, defaulting to the current date, to reproduce a checked snapshot from exact input bytes without falsifying its provenance. Validate the argument. This changes metadata selection only, not financial calculations.
- [ ] Document the syntax minimum of Python 3.10 (strict zip and existing syntax), and the observed maintainer environment of Python 3.14.7. Keep the existing pinned direct requirements and generate/review `data/requirements.lock` for the complete resolution used by the clean-environment validation. Do not blindly freeze the old venv or capture personal package locations/private indexes. Do not promise other interpreter/dependency combinations without testing them. Do not add a public runnable launcher requiring a new bootstrap mechanism. A venv-creation command is the only setup use of system Python; all scripts/tests/package installation use the venv interpreter thereafter.
- [ ] Add JS/CSV parity and schema checks for exact field order, 154 rows, contiguous 1872–2025 years, finite decimals, returns/CPI greater than -1, null bills and reconstructed quality before 1928, and modern quality afterward. Require both files; remove historical skip-on-missing behavior.
- [ ] In a private scratch copy, reproduce the snapshot using the exact cached workbook hashes and `--generated-date 2026-08-20`. Compare both output bytes with the admitted originals. Never run `--refresh` for the port or hand-edit a generated artifact. If reproducing differs, investigate and resolve before declaring parity.

**Acceptance:** Both snapshot files reproduce from verified inputs or any actual provenance gap is reported as a release blocker; compiler controls and 37 baseline tests remain intact, plus new CLI/cache tests. Historical assertions remain unchanged and missing data fails.

### Task 3 — Make the complete project test command portable

**Files:** new nested `package.json`, `package-lock.json`; existing browser test; `tests/helpers/browser-target.cjs`, `tests/run_artifact_browser.cjs`; test docs.

- [ ] Declare Node >=24 and pin the Playwright package to the already established monorepo browser version, 1.63.0. Use it only as a test dependency. Preserve CommonJS loading for existing `.js` modules/tests (do not set package `type` to `module`); new maintainer ES modules use `.mjs`. Generate and review the lockfile; check it for local paths or private registry URLs.
- [ ] Adapt the existing CDP harness to locate Playwright's installed Chromium, keeping its current assertions, cold-frontier benchmark, exception/console capture, and process/profile cleanup. Fail if the binary is unavailable. Keep file-protocol coverage; do not replace the smoke matrix with a smaller test.
- [ ] Let the harness target `MARKET_ATLAS_TEST_URL` when explicitly provided, otherwise the source `index.html` file URL. For HTTP targets require loopback, correct path, successful status, and expected document/asset content. Reject external origins and requests beyond the expected static assets. Keep the stricter zero-HTTP-request assertion for the file case.
- [ ] Extend browser coverage to collect all three CSV downloads in an isolated temporary download directory and inspect their schema/values for the accepted synthetic scenario. Retain existing download status checks; a success message alone does not prove usable bytes. Include the notice link, directory and explicit-index routing, and reload/theme behavior.
- [ ] Initially provide `npm test` for the full existing Node suite and `npm run test:browser` for the full browser-smoke file using an explicit test URL or its source-file default. Task 4 extends `npm test` with the artifact runner and adds the build command; Task 5 adds deployment. Keep Python validation a separate explicit command in the README so it cannot be forgotten under an ambiguous “all tests” claim.

**Acceptance:** A fresh supported checkout uses `npm ci` and `npx playwright install chromium` to run every source browser test, even without system Chrome; missing data/browser fails. Harness supports later artifact and deployed HTTP targets; complete artifact matrix is Task 4's acceptance gate. New child project does not alter sibling package dependencies or test discovery.

### Task 4 — Implement deterministic static packaging

**Files:** `tools/build_static.mjs`, `tests/static-build.test.js`, `.gitignore`, package scripts, optional sanitized notice link in HTML.

- [ ] Write meaningful failing tests for the artifact contract in section 5.2, then implement it. Exercise actual production functions rather than copied source fragments.
- [ ] Cover deterministic identity, exact inventory, sorted serialization, same bytes in different roots, input mutation changing identity, source immutability, script order preservation, unchanged data/module bytes, and correct HTTP/file relative URLs.
- [ ] Negative cases: missing data/notice/module, added or duplicate/external scripts, symlinks/nonregular inputs, unsupported schema, output/source overlap, an output path that could erase source, and incomplete/failed output writing. Source input allowlist must not expand because a developer added a runtime-looking file.
- [ ] Normalize artifact modes and produce only the documented files. Build to a disposable staging directory before replacing a prior local `dist`; never recursively wipe an arbitrary user-selected path.
- [ ] Implement `tests/run_artifact_browser.cjs` using Task 3's harness: build into a fresh private temp directory, run the full matrix against the package's file URL, then start a dependency-free Node HTTP server on `127.0.0.1:0`, serve under `/calculators/backtest/`, run the full matrix over HTTP, and close/reap/clean on every outcome. Test spaces and port-in-use independence. Add this runner to `npm test`, add `npm run build`, and prove no CDN/runtime network dependency or source-tree reference. No permanent server or Python test server is needed.

**Acceptance:** Repeated clean builds compare byte-for-byte including manifests; full source-file and packaged file/HTTP artifact browser matrices pass. Building needs only Node and admitted files. The runtime is standalone after the repository is moved or unavailable.

### Task 5 — Implement safe local deployment and recovery

**Files:** `tools/deploy_static.mjs`, `tests/static-deploy.test.js`, package deployment script.

- [ ] Implement the committed-source preflight, path/type/metadata guards, dry-run, stage verification, protected receipts, immutable generation installation, entry activation, and rollback contract in section 5.3.
- [ ] Test a new empty target and repeated identical installation; upgrade two distinct synthetic generations; retain old assets; verify old/new entry references never mix modules.
- [ ] Inject failure before generation rename, before entry rename, during backup/receipt writing, and after activation. Assert previous entry/bytes remain usable or are restored; report rollback failures separately. Test retry after interrupted generation publication and valid idempotent reuse.
- [ ] Cover missing/untracked/dirty release source, corrupted current or existing target generation, unexpected root files, permissions, symlinks/ancestor aliases, forbidden destinations, unsupported extended metadata, insufficient-write failures, and path spaces. Test exclusive-operation refusal and receipt misuse against a different site, later release, tampered entry, or traversal backup reference. Dry-run must create no destination or backup artifacts or lock.
- [ ] Cover unmanaged legacy adoption in isolated synthetic fixtures: refusal without the flag, verified private backup before moves, preservation of legacy data and symlinks, cross-device quarantine preflight refusal, restoration if the second rename fails, exclusion of maintenance material from the new runtime, and private rollback semantics. Add the package deployment command only when its implementation is available. No test uses or alters the real live source tree.

**Acceptance:** Every tested failure has a truthful recovery state. Private backups are outside source/webroot, normal update activation is atomic, and initial adoption downtime is explicitly documented. No background data refresh, directory mirroring, pruning, container restart, or unrelated file modification occurs.

### Task 6 — Extend the repo deployment audit

**Files:** `tools/check_static_deployments.mjs`, `tools/tests/check_static_deployments.test.mjs`, existing Zsh audit and its test suite.

- [ ] Implement the read-only contract in section 5.4 using the packager's pure artifact function; do not invoke its writing CLI.
- [ ] Add the new scopes to the validated index inventory and invoke the static helper with a private path-list file. Propagate nonzero status without allowing an `OK` line. Extend the synthetic passing fixture to contain a managed static deployment.
- [ ] Node helper cases: entry/content/mode drift, missing/corrupt assets, unexpected root or generation contents, stale/forged manifest, incompatible schema, valid retained release, invalid retained release, and no writes to source/deployment. Log categories/counts, not unknown sensitive pathnames.
- [ ] Zsh integration cases: missing Node/helper, failed Git snapshot, missing required tracked input, untracked input, staged required addition/deletion, source symlink, sparse/unmerged state, override paths with spaces, and child-helper failure. Verify existing direct mappings, permissions, Model Sentinel, history and protected-state cases still pass.
- [ ] Update the audit doc's source/mode contract: static modes are artifact-derived and immutable generations are intentional, unlike formerly tracked stale files in maintained source copies.

**Acceptance:** The complete existing Zsh audit suite plus new static Node coverage passes. A missing static deployment is reported as missing before first deployment. The audit neither packages to disk nor mutates any target.

### Task 7 — Update maintained documentation at every level

**Files:** project README/test/data/architecture/lessons/attribution docs; `Calculation tools/README.md`; root README/agents; `docs/local_deployment_sync.md`.

- [ ] Explain Window, Sweep, Lifestyle, frontier, model limitations and canonical historical controls. Replace personal paths and obsolete statements that webroot is canonical source. Distinguish dependency-free browser runtime, Node maintainer tooling, and Python-only annual data maintenance.
- [ ] Document source-file opening, release build/output inventory, complete test setup, no-skip prerequisites, source and artifact browser coverage, private exports, theme-only persistence, data attribution, and refresh/reproduction workflow.
- [ ] Document installer commands, explicit first adoption, committed-source requirements, destination override, actual webroot mount verification, stable URL, no-restart behavior, bytes/HTTP checks, rollback, protected backup modes, and retained-generation policy.
- [ ] Add Market Atlas to the grouping README and root project index. Describe the nested independently maintained project and list its full validation commands in root `agents.md`. Preserve sibling calculator commands; do not make the parent `npm test` silently claim child coverage.
- [ ] Consolidate current architecture/lessons instead of importing contradictory old plans/audits. Mark this migration plan as implemented only after its release gates have actually been met.
- [ ] Check links and copy/paste commands from a clean checkout; show portable quoted paths, not a personal username. Do not record private mount/config/backup contents in public docs.

**Acceptance:** Users can distinguish opening, testing, packaging, refreshing data, deploying, and recovery. Docs at all three project/group/repo levels agree with actual commands and file layout.

### Task 8 — Full validation, adversarial implementation review, and clean-clone admission

**Files:** all admitted source and tooling; private validation records only.

- [ ] Run all validation/build commands in section 7 with required prerequisites, then review changes against all contracts. Use installer and recovery commands only on isolated fixtures at this stage; live commands belong to Task 9. Run the full sibling `Calculation tools` suite as a one-time integration gate for the newly grouped project; do not broaden to unrelated monorepo applications. Future documentation-only changes do not inherit this test requirement.
- [ ] Challenge the actual implementation with the scenarios in section 8, fix every finding, and rerun affected complete suites. Do not delete assertions, adjust canonical historical thresholds, skip browser tests, or silently suppress failures.
- [ ] Review every staged file and full staged diff for sensitive content. Inspect new code commits for an imperative subject and nonempty explanatory body before any push/PR. Do not copy private source-history or review excerpts into commit bodies.
- [ ] Create a fresh local clone of the sanitized branch, repeat source/artifact private-literal and secret checks, install from manifests, run full project/compiler/audit suites, build twice and compare artifacts, and open its file and HTTP outputs. Use the clone's own venv. Never rely on the source deployment's old venv or cache.
- [ ] Record exact commands/statuses, failures by name, source commit, artifact ID, and scope. The local fresh-clone gate precedes any network publication. Creating/pushing a PR or merging remains outside this plan unless explicitly requested during implementation.

**Acceptance:** Complete supported fresh-checkout reproduction with zero failures/skips, no known private admission findings, and no source-to-deployment dependency. Data rights/provenance gate resolved. No claim of deployed success yet.

### Task 9 — Perform the first local cutover after deployment authorization

**Files:** installed runtime and protected backup/receipt only; no unrelated calculator or webserver source edits.

- [ ] Verify actual Compose mount through narrowly selected mount information or local-only config inspection; do not print the entire `.env` or expanded Compose configuration. Confirm the expected loopback service is already running. If stopped, do not implicitly start a different stack.
- [ ] Confirm no source changes since the validated snapshot. Preserve the original tree and confirmed project archive privately; run installer dry-run and inspect the concrete change inventory before adoption.
- [ ] Invoke controlled legacy adoption, keeping all unrelated webroot files and Docker lifecycle state unchanged. Confirm root contains only entry HTML and managed asset generations.
- [ ] Compare installed files/hashes/modes and every HTTP response body with the validated artifact. Require correct HTML/JS content, not merely status 200; dynamic index fallback can return a successful wrong page for some missing routes.
- [ ] Run the full browser smoke matrix against the installed loopback URL using an isolated browser profile and synthetic scenarios. Exercise both explicit index and directory routes, reload/theme, Window/Sweep/Lifestyle/frontier/cancellation, narrow and keyboard behavior, and all three CSV download paths. Verify download data matches accepted synthetic inputs and no unexpected console/page errors or external network requests occur.
- [ ] Run the read-only fleet audit. Resolve the new static component and report any other real fleet findings honestly; do not silently repair unrelated deployments or claim the entire fleet passes when it does not. Prove rollback on fixture deployments; retain the real rollback receipt rather than taking down the live app for a redundant demonstration.

**Acceptance:** Installed standalone artifact equals validated output and served bytes, browser functionality passes, project development material is no longer served, rollback is available, and unrelated runtime state is preserved. Repo is canonical source; webroot is only the release target. Plan approval never authorizes this task; if the user's later instruction explicitly authorizes implementing the entire plan including local deployment, that authorization is sufficient and must not be requested again.

## 7. Commands and expected results

Run these after implementation from the monorepo root unless indicated otherwise. Commands describing planned interfaces do not exist yet; Tasks 3–6 implement them.

| Purpose | Command | Expected result |
|---|---|---|
| Install backtest test tools | `cd "Calculation tools/backtest" && npm ci && npx playwright install chromium` | Lockfile-driven install; supported Chromium available |
| Complete backtest JS/browser suites | In backtest: `npm test` | All unit/integration/source-file and packaged file/HTTP browser tests pass; zero skips |
| Data-maintenance setup | Using the documented tested Python interpreter, in backtest: `python3 -m venv .venv && .venv/bin/python -m pip install -r data/requirements.lock` | Project venv; reviewed complete dependency resolution; no system-package installation |
| Complete compiler suite | In backtest: `.venv/bin/python -m unittest discover -s data -p 'test_*.py'` | Existing 37 cases plus additions all pass |
| Static build | In backtest: `npm run build` | Only documented `dist` inventory; no data refresh/network/Python |
| Build determinism | Build twice to distinct temporary destinations using `node tools/build_static.mjs --out PATH`; compare with `diff -r` | Zero differences, including manifests |
| Packager/installer focused development | In backtest: `node --test tests/static-build.test.js tests/static-deploy.test.js` | All actual production-function negative and recovery cases pass; still run full `npm test` before release |
| Existing grouping suite | `cd "Calculation tools" && npm ci && npx playwright install chromium && npm test` | Complete sibling Node and Playwright suites pass |
| New static audit suite | `node --test tools/tests/check_static_deployments.test.mjs` | All static comparison/read-only cases pass |
| Existing audit suite with integration additions | `zsh tools/tests/test_check_local_deployments.zsh` | Full suite ends `check_local_deployments tests: PASS` |
| Ignore/admission check | `git ls-files -- "Calculation tools/backtest"`; `git check-ignore --no-index -- "Calculation tools/backtest/data/compile_market_data.py"` | Compiler/source/data tracked; compiler path is not ignored (check-ignore exit 1) |
| Live deploy preflight | In backtest: `npm run deploy -- --webroot "$HOME/webroot" --dry-run` | Reports reviewed changes; performs no live/backup writes |
| First cutover, only when authorized | In backtest: `npm run deploy -- --webroot "$HOME/webroot" --adopt-legacy` | Runtime-only deployment and private receipt/backup; truthful adoption status |
| Later update | In backtest: `npm run deploy -- --webroot "$HOME/webroot"` | Verified immutable assets installed, entry activated, receipt retained |
| Installed browser checks | In backtest: `MARKET_ATLAS_TEST_URL="http://127.0.0.1:7711/calculators/backtest/index.html" npm run test:browser` | Full matrix against installed release, isolated profile, no skips/errors/external requests |
| Fleet drift | `zsh tools/check_local_deployments.zsh` | Static component OK; every other finding/status reported accurately |
| Explicit recovery | In backtest: `npm run deploy -- --webroot "$HOME/webroot" --rollback PRIVATE_RECEIPT_PATH` | Receipt validated; prior entry/tree restored and verified; no pruning |

Annual refresh is a separate maintenance operation in the venv. It uses compiler source controls, checks both paired outputs, and reruns full tests before building/deploying a new release. A refresh never happens as an implicit deployment step. Exact-input reproduction uses the verified cached workbooks outside repo plus `--generated-date`; document public hashes without copying cached XLS files into Git.

Do not run the uv launcher fleet guard for this port unless a uv-managed launcher is actually introduced or modified. No such launcher is planned. Do not run unrelated Python/CLI/Docker project suites for prose edits or static assets that do not change those consumers.

## 8. Adversarial review and disposition

This is a separate adversarial pass over the proposed design, followed by revision and a sanity pass. It is a planner self-review, not a claim of independent-agent or implemented-code review. All identified plan findings have concrete dispositions below; future implementation must prove them.

| Challenge/finding | Disposition in the revised plan |
|---|---|
| ZIP example may refer to another version; a numeric scrub would corrupt legitimate money or return series | Explicit source-identity assumption, contextual private-literal inventory, no invented postal UI, source reinspection if clarified (sections 1 and 3; Task 1) |
| A broad privacy question reopens owner-confirmed illustrative defaults or treats custom barbell logic as personal holdings | Owner clarification closes the ordinary defaults question; preserve generic method and benchmarks; audit individual fixtures and escalate only evidence-backed new findings (section 2; Task 1) |
| Importing raw source even briefly creates private Git objects or exposes content in the public tree | Private staging and per-file admission before any staging/commit; fresh-clone gate before push; no history import (Task 1/8) |
| Sanitizing HTML but retaining private docs/tests/screenshots defeats publication boundary | Rewrite current docs, exclude old mockups/audits/backups, classify financial examples, scan artifact and full staged diff (section 3; Tasks 1/7/8) |
| Publicly downloadable data was mistaken for freely redistributable data | Primary-source evidence, attribution notice, explicit unresolved Shiller rights/provenance admission gate, no invented blanket license (section 3; Task 2/8) |
| Absence of explicit owner permission halts unrelated coding or leads to asking the same question again | No explicit permission is recorded; executor investigates primary terms, continues independent safe work, and gates dataset admission/full-release claims only (section 3; Task 1) |
| `build/` compiler disappears under the monorepo ignore policy | Import under `data/`, verify tracked inventory and check-ignore result (Task 2) |
| Normal deployment refreshes moving upstream history or depends on abandoned caches | Release packaging consumes the admitted pair, no network/data refresh; separate exact-input reproduction with controlled date (Tasks 2/4) |
| Old venv passes while a fresh dependency resolution changes compiler behavior | Record observed interpreter/dependency versions, review a complete lock from direct requirements, and validate a fresh venv instead of blindly freezing local history (Task 2/8) |
| Generated data stays `0600` and Nginx cannot serve it | Artifact modes normalized and tested/audited, private backups use different modes (sections 5.2–5.4) |
| Per-file installation or naïve directory replacement mixes releases or creates availability gaps | Versioned immutable assets and single atomic entry activation; honest separate initial-adoption downtime (section 5.3) |
| Replacing a root manifest and entry independently leaves inconsistent audit state | Manifest stored in immutable generation; expected entry and manifest derived from source, one mutable activation file (section 5.2/5.4) |
| Packaging code changes but a missed version bump leaves the same asset identity | Builder bytes participate in canonical input hashing; exact serialization and known-answer tests are specified (section 5.2; Task 4) |
| Packaged attribution link points to an omitted source-root file | One recognized notice link rewritten to its generation; source/package link checks required (section 5.2; Tasks 3/4) |
| Existing source/venv/cache/backups remain served after a “successful” cutover | Controlled legacy adoption and verified private backup; runtime-only root; confirmed project archive relocated, unrelated material preserved (Task 9) |
| Absolute symlinks work on macOS but fail inside the container | Install regular copies using relative browser URLs; reject symlink inputs/managed targets, verify actual served route (sections 5.2/5.3; Task 9) |
| Browser/data tests silently skip on fresh machines | Pinned managed Chromium, fatal missing prerequisites, preserved full matrix and historical assertions, fresh-clone execution (Task 3/8) |
| Built artifact is only tested as source or at `/`, missing subdirectory/file regressions | Complete source-file and built file/HTTP browser matrices plus installed-route checks; require content, not status alone (Task 3/9) |
| Browser reports export success but downloads are absent, stale, or malformed | Inspect all three CSV downloads in isolated temporary storage for accepted synthetic configuration values and schema (Task 3/9) |
| Deployed manifest can lie about expected data or a helper changes the audit's source semantics | Derive expected artifact from validated stage-0 membership and current source; check actual bytes/types/modes; failure suppresses OK (Task 6) |
| Audit scope expansion causes unsafe writes or prints sensitive unknown paths | Pure in-memory comparison, no compiler/build CLI, existing private temp contract, aggregate reporting/read-only tests (Task 6) |
| Receipt or backup protection makes restored files unreadable; rename erases ACLs | Separate private backup modes from runtime modes; preserve documented metadata or fail unsupported preflight; test recovery (Task 5) |
| A stale/wrong-site receipt or simultaneous installer rolls back a later successful deployment | Canonical site and expected-entry binding, restricted backup references, and private exclusive-operation lock; fail instead of overwriting changed state (section 5.3; Task 5) |
| Legacy venv backup follows symlinks or chmods an external interpreter | Quarantined backup preserves links without dereferencing, records/restores original modes, and never applies public runtime input rules to legacy recovery material (section 5.3; Task 5) |
| Cross-device legacy moves silently become destructive copy/delete, or task ordering calls nonexistent tools | Reject cross-device quarantine before mutation; source browser provisioning precedes build/artifact runner, which precedes installer/audit (section 5.3; Tasks 3–6) |
| Lost prior asset generations break in-flight browsers or rollback; broad deletion loses personal files | Retain safe generations, no pruning/delete mirroring; unknown-layout refusal and explicit legacy adoption (Task 5) |
| Passing source tests are misrepresented as future migration/deployment validation | Planning baseline labeled separately; explicit full future suites and independent deployment acceptance (sections 1/7; Tasks 8/9) |
| Parent test command misses child tests or tooling changes silently break existing audit consumers | Independent child suite documented at all levels; full sibling and existing audit integration suites required (Tasks 6–8) |
| Port escalates into backend redesign, configuration product, fleet repair, license selection, or data-methodology rewrite | Narrow static design and explicit scope boundaries; material alternative decisions return to owner review (sections 2/3/7; Task 9) |

## 9. Final sanity check

- [x] Source and monorepo inspected; README/documentation chains, current tests, ignore policies, runtime/deployment code, public-admission policy, and PKM context checked.
- [x] The plan addresses privacy beyond ZIPs: defaults, fixtures, docs, mockups, source paths, generated output, caches, runtime state, exports, backups, logs, and Git/publication artifacts.
- [x] Three approaches compared; chosen approach preserves module boundaries and offline/browser-first delivery.
- [x] Static packaging and market-data maintenance are distinct; data invariants, provenance, and admission uncertainty are explicit.
- [x] Proposed helper interfaces, identity/schema, commit point, recovery path, modes, source membership, and retained-release behavior agree across build/install/audit tasks.
- [x] Tasks name exact files, existing functions/contracts, dependencies, acceptance criteria, negative cases, and verification commands without prewriting routine implementation.
- [x] Root/group/project documentation updates are covered; existing project tests are preserved; missing browser/data is not permitted to masquerade as a pass.
- [x] No source changes, market refresh, private-file import, Git commit, network publication, or local deployment was performed during planning.
- [x] Unverified assumptions are visible: Market Atlas is the intended source; exact workbook/provenance and data-redistribution checks precede dataset admission; live webroot mount is checked during cutover. These are explicit gates, not hidden claims of verification.
- [x] Plan review does not authorize implementation. Later explicit authorization for the full implementation/local cutover is honored without repeated permission requests; publication remains governed by the user's stated scope. The next action is owner review of this document.

## 10. Revision review record

The original section 8 documents a same-context planner self-review. The owner-clarification revision and coding-agent handoff prompt received a fresh clean-context adversarial review under the owner's updated deliverable-review process.

- Round 1 adversarial review: one material finding, fixed. Section 3 previously overgeneralized CPI as entirely BLS-origin. The revised lineage distinguishes Shiller's pre-1913 Warren–Pearson component, the BLS splice, and the compiler's 1928+ FRED-via-Damodaran inputs, and scopes BLS public-domain evidence accordingly. Sources: `build/compile_market_data.py` (`parse_shiller`, `parse_damodaran`, emitted field lineage) and the linked Shiller primary-source description.
- Findings rejected: none. No additional handoff-prompt findings.
- Round 1 sanity check: a second fresh clean-context reviewer verified the correction against the primary source and compiler, checked the revised plan and handoff prompt, and returned no findings. Another adversarial round was not needed.
- Review record: one round completed; one material finding fixed; none rejected; no material fixes after the final sanity check. Both revision reviewers had clean context. The earlier section 8 self-review remains identified separately.
- Unresolved implementation gate: sufficient historical-data redistribution basis and exact-input provenance must still be established before dataset admission. The owner has no explicit permission; this is recorded evidence, not a request to answer the same question again.
- No application code or deployment was changed. Automated application tests were not rerun for this documentation-only revision.
