# Backtest port addendum: local data acquisition and builds

> **Superseded:** [backtest_simple_port_implementation_plan.md](backtest_simple_port_implementation_plan.md) is the sole active specification. This document is retained as history; its withdrawn contracts are not implementation or acceptance gates.

**Status:** Proposed implementation addendum for review; writing this document does not implement it or add deployment/publication authorization.
**Date:** 2026-10-01.
**Precedence:** This separate file supersedes the historical-data admission, source-data packaging, setup, and related validation/audit requirements in `docs/backtest_monorepo_port_implementation_plan.md` wherever they conflict. All other privacy, application behavior, atomic installation, recovery, and authorization requirements remain in force. Leave that active plan file unchanged while the coding agent is using it.

**Goal:** Publish the application, compiler, tooling, documentation, and synthetic tests without redistributing the historical dataset. Download the required upstream workbooks during initial local setup/build, compile and retain them outside the repository, and package them only into the user's local application build.

## 1. Decision and alternatives

Use a **local setup step automatically invoked by the first build**, followed by cached, offline builds. The browser loads the locally built dataset exactly as it does today; opening the app does not initiate upstream downloads. Deployment, rollback, and the deployment audit never acquire data or install dependencies.

| Approach | Effect | Decision |
|---|---|---|
| Download and compile once during local setup/build | Reuses the existing Python compiler; preserves offline browsing, static hosting, and the current simulation engine; first setup requires network/Python | Recommended |
| Download upstream workbooks on each browser startup | Requires a new browser acquisition/parser/cache path and new failure/loading behavior; browser access and source format support would need investigation; results may change between launches | Reject for this port |
| Run a permanent local data service | Can centralize downloads but introduces another process, API, lifecycle, and deployment contract | Unnecessary for the current static app |

This removes the need to establish redistribution rights for a dataset included in the public repo because no such inclusion is planned. It does not declare all upstream uses unrestricted. Keep attribution, source terms, and supported acquisition/use documented. The unresolved Shiller redistribution question no longer blocks code-only admission; a concrete restriction on the proposed automated download/local use would still require a specific resolution. Do not contact data owners, bypass access controls, or infer rights merely from download availability.

The generated local build necessarily contains historical values so the browser can compute results. Treat it as a local runtime artifact, not a public distributable. No data-bearing GitHub release, package, container image, hosted demo, public CI artifact/cache, screenshot, or downloadable build is part of this design. The existing localhost deployment remains the intended destination. External/public serving of that build requires a separate distribution decision.

## 2. Grounding in the current source

The original application is under `~/webroot/calculators/backtest`; the in-progress sanitized import is `Calculation tools/backtest` in the monorepo. The coding agent is actively changing the latter: reinspect it and adapt existing work rather than reverting or duplicating it. At inspection, runtime modules and compiler/tests had been imported, but no real market-data files were present in that project. This document changes no executable files.

Relevant existing interfaces:

- `index.html` declares nine scripts, with `market-data.js` first. `app.js` expects `globalThis.MARKET_DATA.rows` and reads its `generated` and `sources` metadata. Preserve this runtime contract and load order.
- `data/compile_market_data.py`: `acquire_source(name, url, supplied, refresh) -> Path`, `parse_shiller(path)`, `parse_damodaran(path)`, `verify_damodaran_anchor`, `reconcile`, `splice`, and `emit(rows, generated)`. `emit` currently writes the JS/CSV pair under `ROOT`; this must change to an explicit external output directory. Retain size, OLE signature, sheet/header, finite-value, chronology, reconciliation, and paired-output recovery controls.
- The in-progress compiler already uses `MARKET_ATLAS_DATA_HOME` for `CACHE` and has `--generated-date`. Preserve the supported explicit workbook inputs `--shiller` and `--damodaran`.
- Real-data references exist beyond `tests/historical.test.js`: `engine.test.js`, `export.test.js`, `lifestyle.test.js`, and `sweep-render.test.js` load `../market-data.js` directly. Find all such consumers and route them through the external dataset test contract below.
- The main plan proposes pure `buildArtifact`, installer receipts, immutable asset generations, and a read-only static audit. Their source/data input boundary must be revised; external data must not be mistakenly required to be Git-tracked.

Upstream evidence: the [maintained Shiller page](https://shillerdata.com/) exposes a workbook download and describes the historical series, including Warren–Pearson inflation before the January 1913 BLS splice. [Damodaran's historical returns page](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html) links its workbook; [its usage guidance](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/guide.html) must remain documented separately from code licensing. These are acquisition/lineage references, not a claimed blanket redistribution license.

## 3. Public source versus local state

**Track:** the eight application JS modules, HTML template, compiler, source-selection/recipe metadata in `data/sources.json`, reviewed `data/requirements.lock`, build/setup/deployment/audit tools, notices, documentation, and conspicuously invented test fixtures. The versioned source recipe names Shiller/Damodaran official endpoint identifiers and expected workbook layouts, output first/last years, splice year and reconciliation last year. Public source-selection metadata may include official URLs, expected schema/period, transformation descriptions, and public hashes; it must not contain historical row values or personal paths.

**Never track or publish:** actual workbooks; `market-data.js` or `.csv`; an equivalent JSON/base64/compressed dataset; data-bearing test snapshots, expected-output dumps, source maps or embedded bundles; local provenance files containing operational paths; compiled local builds; download caches; venvs; or private recovery records. Existing accepted scalar historical controls can remain in tests; do not copy historical rows into fixtures to make CI pass.

Use `MARKET_ATLAS_DATA_HOME`, default `~/.cache/market-atlas`, as the external root. Retain existing workbook-cache compatibility: known cached XLS filenames may remain directly under this root. Add:

```text
<DATA_HOME>/.venv/                       local compiler environment
<DATA_HOME>/inputs/<sha256>/source.xls   immutable original workbook bytes
<DATA_HOME>/datasets/<bundleId>/         immutable JS/CSV + provenance.json
<DATA_HOME>/current.json                 atomically selected bundle/data/recipe IDs
<DATA_HOME>/builds/<artifactId>/          private, local runtime artifact
```

Fixed-name legacy workbook caches are compatibility inputs, not the retained originals. On first use, validate and copy each known workbook into immutable hash-addressed `inputs/<sha256>/source.xls`; verify an existing object's bytes before reusing it. Every bundle references its exact input hashes and relative object names. A refresh uses a separate private candidate cache, publishes validated immutable input objects, and preserves all prior referenced inputs. It never calls the existing overwrite-in-place acquisition against the sole retained old workbooks. Unselected successful input objects may remain after a later failure; failed candidates cannot change selected state. No input pruning is part of this port.

Reject roots/output destinations canonically inside the repo or webroot, including symlink aliases. Workbooks, provenance and local state use directories `0700` and files `0600`; local build/runtime descendants retain `0755`/`0644` as required for static serving, with the external local build's enclosing directory protected. Deployment copies only runtime assets to the existing webroot. Do not chmod unrelated pre-existing directories or follow symlinks to external targets. Restrict operations to recognized owned layouts and use the original plan's path/metadata guards.

Keep narrowly scoped project ignore entries as defense in depth for accidental `market-data.js`, `market-data.csv`, `*.xls`, `*.xlsx`, local data/build directories and exports. Do not blanket-ignore CSVs or substitute ignore rules for the external storage contract. Add a Git-index admission check rejecting actual data even when force-added or placed under another filename; combine prohibited-path inventory with contextual staged-tree review for renamed/encoded copies. If actual data has already entered unpublished Git commits, resolve those local objects before any push, preserving the owner's original runtime data. Never quietly rewrite published history.

## 4. Setup, acquisition and refresh contract

Add a Node maintainer entry point, `tools/setup_data.mjs`, and `npm run setup:data`. It orchestrates the existing compiler rather than reimplementing financial transformations. It supports `--offline`, `--refresh`, `--shiller PATH`, and `--damodaran PATH`; explicit source files are validated and copied into controlled external storage, never changed in place. Keep arguments structured and spawn subprocesses without a shell.

1. Resolve a safe external data home and serialize local setup/refresh mutations with an exclusive private lock. Ordinary read-only consumers do not lock or write. Refuse an unexplained existing mutation lock; do not delete another process's state.
2. Verify any selected bundle: recognized manifest/schema, plain regular files, exact JS/CSV hashes and parity, dataset ID, recipe identity, year/quality schema. Corrupt state fails clearly; it is not silently redownloaded or replaced by fake history.
3. If a valid bundle matches the current compiler/requirements/source-selection recipe and no refresh or explicit workbook override was requested, reuse it without Python execution, dependency resolution, network access, or date changes. No routine freshness request is made. `--refresh` or an explicit workbook input always takes the candidate-validation path, even when the current bundle is valid. Reject `--offline --refresh` before mutation; offline manual inputs are allowed with prerequisites ready, but any missing unsupplied input fails without network access.
4. If acquisition/compilation is needed, create the external venv with the documented supported interpreter and install the complete reviewed requirements lock into that venv. The only system-Python invocation is `python3 -m venv ...`; all compiler, tests and pip executions use a venv interpreter. Use an already compatible environment when possible. `--offline` must not resolve/install dependencies from the network: use existing prerequisites or fail with a specific setup instruction.
5. Acquire missing official workbooks with the existing bounded/time-limited validation. Verify the actual download endpoint and parser compatibility before selecting it in public recipe metadata. Prefer an official HTTPS endpoint; do not silently switch to an arbitrary mirror or disable TLS verification. The compiler currently uses the frozen Yale HTTP source for Shiller; a maintained-workbook substitution may change layout/values and must pass parsing, overlap and historical controls. If automatic acquisition is unavailable, give actionable `--shiller`/`--damodaran` instructions, with no public mirror supplied by this repo.
6. Compile into a fresh private stage with new explicit `--output-dir PATH`. Never emit into the project root. Initially select the existing 1872–2025 output range (154 rows), 1928 splice, and 1928–2022 reconciliation cohort. Add an explicit validated end-year selection if a current workbook includes later years; do not expand the model period implicitly. Default setup records the actual compile date; exact reproduction uses the recorded `--generated-date`. Do not backdate a new download to pretend it is the original snapshot.
7. Validate the complete JS/CSV pair and provenance, finish an immutable dataset generation, then atomically update `current.json`. If anything fails, retain the last selected good bundle and report the failure; no partially written generation becomes selected. `--refresh` obtains candidate inputs privately and changes neither existing inputs nor selected state until the candidate succeeds. Preserve previous bundles for reproduction/rollback; no automatic pruning.

When the recipe changes but inputs are already available, compile from those validated inputs without automatic refresh. A genuine upstream schema or historical-value change that fails accepted controls is investigated; do not weaken assertions. It may require a separately reviewed data-methodology/baseline decision, not a generic request for redistribution permission.

**Versioning:** public code pins the transformation and intended historical range, not the permanently available bytes of a moving upstream URL. Each local bundle records actual source SHA-256s, official URL identifiers, compiler/requirements/recipe hashes, generated date, range/count, and both output hashes. No absolute paths or acquisition timestamps go into browser-visible notices or artifact identity. Preserve input bytes locally. Identical recorded inputs, recipe, date and outputs reproduce a build; two fresh downloads at different times are not promised to match. A fresh clone on the same machine can explicitly select the already verified bundle for exact-byte reproduction without putting it in Git.

Use three distinct identities, all lowercase SHA-256 hex:

- `dataId`: hash UTF-8 `JSON.stringify({schemaVersion: 1, files}) + '\n'`, keys inserted in that order; `files` is ASCII-name-sorted records `{path, sha256}` for `market-data.csv` and `market-data.js`, keys inserted in that order.
- `recipeId`: the same canonical envelope/record rule applied to compiler source, `data/sources.json`, and `data/requirements.lock`, with their project-relative POSIX names. Include any additional code actually used to transform data in this explicit recipe inventory; acquisition orchestration changes that alter transformations must invalidate the recipe too.
- `bundleId`: hash UTF-8 `JSON.stringify({schemaVersion: 1, dataId, recipeId, sources, generatedDate}) + '\n'`, keys inserted in that order. `sources` is ASCII-source-ID-sorted `{id, url, sha256}` records, with those keys in order; `url` is the exact approved acquisition identifier in the recipe, not a private manual filename or redirect query string. `generatedDate` is the validated compiler date recorded in the payload/provenance.

Store immutable bundles under `datasets/<bundleId>/`. Identical outputs from different recipes or input workbooks may share `dataId` while receiving distinct bundle paths and provenance; never overwrite one recipe's provenance to reuse an output identity. Validate selector IDs by recomputing all identities from actual bytes and schema-controlled provenance; do not trust the mutable selector's claim. Persist manifests with explicit schema versions and relative owned filenames only. Verify bytes by parsing the known `globalThis.MARKET_DATA = <JSON>;` envelope as data, never by evaluating downloaded JavaScript. Logs report status/hashes/counts, not historical rows, private input paths or exports. Pin each identity serialization with known-answer synthetic tests.

## 5. Build, preview, install and audit changes

`npm run build` invokes the setup wrapper only to ensure missing or recipe-stale data is prepared, then packages the selected verified bundle. It supports `--offline` and `--out PATH`; default output is external, not project `dist/`. A warm build requires only Node and verified compiled files. Browser startup, `npm ci`, installer, rollback and audit have no data-download side effects. `--offline` applies to the entire command, including dependency preparation.

Revise the pure packager contract:

```text
buildArtifact({ sourceRoot, dataRoot, readFile?, readDataFile? })
  -> Promise<{ artifactId, files, manifest }>
```

`sourceRoot` supplies HTML, eight application modules, the public `DATA_SOURCES.md` notice and builder bytes. `dataRoot` is one explicitly selected immutable local generation, supplying `market-data.js`, `market-data.csv` and validated provenance. Both readers are allowlisted and read-only. Missing data throws a typed/actionable error; the pure function never calls setup or the network. A synthetic test may provide separate invented data buffers. Reject symlinks, missing pairs, malformed provenance, and source/data/output overlap before writes.

Use artifact/manifest **format version 2** so version-1 assumptions cannot silently admit a mixed layout. Retain the main plan's canonical serialization, immutable generation layout, exact inventories/modes and atomic entry activation. Hash tracked source inputs and external data separately using logical names, such as `source/index.html` and `data/market-data.js`; include both dataset hashes, the validated data/recipe identities, and canonical path-free provenance/notice bytes. Actual workbook contents never become runtime assets. Distinguish source membership from local-data membership in the manifest. Artifact IDs change when the dataset or relevant recipe changes, even if source HTML is unchanged.

The installed runtime still includes both generated files and the attribution notice under `assets/<artifactId>/`. The notice states that data was locally acquired and identifies the source/period/version without embedding private filesystem details. Public `DATA_SOURCES.md` documents lineage/use/setup, not an included public dataset. Stable relative URLs and the existing nine-script order remain unchanged.

The raw source `index.html` no longer runs directly from a clean checkout because its dataset is deliberately absent. Document opening the locally built `index.html` instead. For full source-layout browser tests, assemble a temporary source-layout copy outside the repo with the eight modules, HTML/notice and verified external pair; preserve the original source-file browser matrix there, then run the complete packaged file/HTTP matrices. This is a source-layout test fixture, not a new public dataset.

Installer preflight still requires tracked, committed, clean **source/tooling** inputs; external data is explicitly exempt from Git membership, not from validation. Live installation consumes a specified verified bundle and artifact, with no setup/download/refresh or dependency installation. Bind `bundleId`, `dataId`, recipe identity and relative external generation reference into the private receipt alongside the existing source commit/artifact/site/entry bindings. Recovery remains independent of current source/current dataset selection; retain old installed generations and protected receipts. An existing legacy source copy may seed local cached inputs only after validation; no data files are imported into the repo.

The read-only audit uses stage-0 Git membership for source/tooling and the active private receipt's validated `bundleId` to select the external generation. Recompute expected bytes with the pure packager; do not use the deployed manifest as the expected source of truth. Verify the current source recipe against that bundle, all actual deployed bytes/modes, and the original recovery/layout guards. Missing local dataset/receipt, incompatible recipe or invalid source is an explicit unverified/failure result, never `OK`, and never triggers a download. A different valid `current.json` selection is reported as a pending local data update separately from corruption; it cannot silently change the installed release's audit baseline. Keep audit override/test paths portable and do not print private receipt paths.

## 6. Tests, documentation and handoff tasks

Reinspect the active implementation, then apply these changes in independently reviewable tasks:

1. **Code-only boundary:** update project ignore/admission checks; verify no real dataset/workbook is in the index, new commits or public artifacts. Track a reviewed acquisition recipe/notice. Leave the live original data intact.
2. **External compiler/setup:** modify `data/compile_market_data.py` and its existing tests; add `tools/setup_data.mjs`, package command and focused setup tests. Preserve old validations and pair recovery; cover explicit output paths, selected end year, cold setup, warm/offline reuse, external venv/prerequisites, manual sources, failed refresh and atomic selection.
3. **Packaging and tests:** revise `tools/build_static.mjs`, package scripts, manifest version, `tests/dataset.test.js`, dataset test helper and all direct dataset consumers named above. The in-progress `dataset.test.js` asserts the original `2026-08-20` generation date; replace that snapshot-date assertion with strict ISO calendar-date validation and equality between payload and validated bundle provenance. Keep a separate compiler test proving explicit-date byte reproduction from recorded inputs. Preserve financial controls, year/range checks and pair parity; this metadata change is not permission to alter historical thresholds. Add local build/source-layout assembly and deterministic tests; missing real data must fail the full suite, not skip.
4. **Installer/audit:** update `tools/deploy_static.mjs`, private receipt schema, `tools/check_static_deployments.mjs`, stage-0 scope registration and their Node/Zsh tests. Keep pure/read-only boundaries, retained releases, negative/recovery cases and existing fleet semantics.
5. **Documentation/publication gates:** update project/group/root docs, compiler/test docs and root agents instructions to describe first-build network/Python, warm/offline behavior, external paths, opening local output, independent refresh and no data-bearing public artifacts. Preserve authorization gates and complete affected-project verification.

**Meaningful new cases:** acquisition timeout/HTML instead of XLS/oversize/wrong sheets; TLS or endpoint failure; corrupt cached pair; source recipe change with identical outputs yielding distinct immutable bundles; exact reproduction from old hash-addressed inputs after successful refresh; interrupted compile/selection; conflicting setup process; failed refresh preserving all old selected bytes and referenced inputs; override/refresh taking effect despite a valid current bundle; offline refresh rejection; generation hash/notice mismatches; environment/path overrides and spaces; source/data symlinks; forbidden output inside repo/webroot; installer/dry-run/audit with missing bundle proving no downloads/writes; rollback after selection changes; and attempt to force-add an actual data file. No automated test downloads real upstream data or modifies the live source/deployment.

Use small invented workbook/data fixtures or a temporary loopback HTTP server for acquisition tests. Declare their synthetic origin. Automated network tests may explicitly permit only the test server's loopback origin; production acquisition remains constrained to configured official sources. Provide `npm run test:synthetic` for a deliberately separate offline compiler/setup/packager/installer/audit and invented-engine subset. It must not be labeled full historical/browser release validation. Public CI uses this subset and never uploads data-bearing outputs; it may exercise the full browser behavior matrix with synthetic inputs but cannot certify historical results.

`npm test` remains the full project gate and requires a verified external real dataset: historical acceptance, all existing financial assertions, source-layout browser tests and packaged file/HTTP matrices run with zero skips. It fails with an actionable `npm run setup:data` instruction when data is absent. Full local validation remains necessary even if public CI cannot run real-history tests. Keep the 69-window 1928–2025 controls and existing 50/50 and 75/25 thresholds unchanged. Do not replace real-history tests with synthetic equivalents or delete affected cases.

### Proposed commands and acceptance

Run from `Calculation tools/backtest` unless specified; these are planned commands, not assertions they exist yet.

| Action | Command | Expected result |
|---|---|---|
| Test dependencies | `npm ci && npx playwright install chromium` | No historical-data acquisition |
| Optional explicit initial data setup | `npm run setup:data` | External venv/inputs/bundle created and validated; source unchanged |
| First local build | `npm run build` | Acquires/compiles only if needed; reports local output entry path |
| Warm/offline build | `npm run build -- --offline` | No network/Python/dependency resolution with a current verified bundle; missing prerequisites fail |
| Controlled refresh | `npm run setup:data -- --refresh` | Candidate validated before selection; old bundles preserved; live app unchanged |
| Manual source setup | `npm run setup:data -- --shiller PATH --damodaran PATH` | Validated external compilation; no upstream request with both supplied inputs and dependencies ready |
| Offline synthetic subset | `npm run test:synthetic` | Explicit subset, no real dataset; acquisition tests use only synthetic loopback fixtures |
| Full local validation | `npm test` plus external venv's `python -m unittest discover -s data -p 'test_*.py'` | Full real-data and existing browser/financial controls; zero skips; compiler suite complete |
| Determinism | Build twice offline to two external temporary `--out` paths; compare with `diff -r` | Same selected bundle/source yields identical bytes |
| Existing fleet integration | From repo root: `node --test tools/tests/check_static_deployments.test.mjs` and `zsh tools/tests/test_check_local_deployments.zsh` | Static/existing full audit suites pass without real network |
| Publication boundary | Review complete Git index/diff/new commits and configured CI/release upload paths | Code/metadata/synthetic fixtures only; no real rows/workbooks/build outputs |

A clean-clone check now has two explicitly separate outcomes: code-only/synthetic validation without upstream access; and complete local reproduction after setup or explicit selection of the verified external bundle. Record which actually ran. A network outage may block cold setup/full-history validation; report it honestly while continuing independent work. Code-only publication does not require redistribution permission for an absent dataset, but do not claim the complete functioning local port is validated before its full gates pass.

## 7. Addendum review record

Round 1 fresh clean-context adversarial review identified three material findings, all fixed: recipe/provenance collisions in immutable dataset paths; loss of exact raw inputs after refresh; and the active dataset test's fixed original generation date. The revised design separates content/recipe/bundle identities, preserves hash-addressed raw inputs, and validates actual compile dates against provenance while retaining explicit-date reproduction tests and unchanged historical controls. No findings were rejected.

A second fresh clean-context sanity reviewer verified all three fixes against the compiler/test sources, checked the identity, setup/offline, packaging/audit, publication and validation contracts, and returned no findings. Another adversarial round was not needed.

**Review record:** one round; three material findings fixed; none rejected; no unresolved review findings; no material fixes after the final sanity check; both reviewers had clean context. Actual endpoint/parser compatibility, implementation and full local validation remain executor acceptance checks, not claims this document has already proved them.

The original plan remains unchanged, confirmed by its matching before/after SHA-256. This addendum is documentation only; no executable tests, workbook downloads, deployments, commits or messages to the coding agent were performed while writing it.
