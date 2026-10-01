# Market Atlas: simple monorepo port replacement plan

**Date:** 2026-10-01. **Status:** Active implementation specification. Implementation and a validated branch/PR are authorized; live deployment follows upstream merge and branch completion.

**Precedence:** This replaces `backtest_monorepo_port_implementation_plan.md`, `backtest_local_data_setup_addendum.md`, and `backtest_explicit_index_routing_supplement.md` as the specification. Preserve sanitized source, real history outside Git, setup/build acquisition, offline browser operation, and `/calculators/backtest/index.html`. Withdraw immutable runtime releases, deployment receipts, strict metadata preservation and expanded audit machinery. Old documents are superseded history, not additional gates.

**Goal:** Finish the port with external local data, a flat static build, an ordinary copy installation with a private backup, a small drift check, and usable documentation.

**Scope:** One owner, one local static site, existing webserver, sequential maintainer commands. A brief deployment interruption is acceptable. No uninterrupted activation or exact macOS metadata restoration guarantee. Preserve calculations, strategies and UI; do not modify the proxy or unrelated apps.

## 1. Selective salvage

Inspection found branch `codex/backtest-monorepo-port` at `702a2c8`, no implementation commits, six modified tracked files and an untracked backtest project/tooling. Recheck because the coding agent may continue working. Keep useful app/compiler/setup work; rebuilding the whole port is unnecessary.

First stop this effort's running mutation commands and make a **private filesystem snapshot** outside Git/webroot: tracked diff including staged work, changed/authored untracked backtest/tool files, status and HEAD. Include ignored authored files if any; reproducible dependencies need not be archived. Preserve external data and validation records in place. Confirm representative app/compiler/tool files and the diff are recoverable. Do not commit unchecked WIP publicly.

No `git reset --hard`, blanket `git clean` or whole-project deletion. Restore only obsolete backtest hunks in shared tracked files, preserving unrelated edits. Delete obsolete untracked helpers only after confirming their snapshot and callers. Make small local milestone commits with explanatory bodies after staged privacy review; no push/PR/merge without authorization.

Paths are monorepo-relative; project-local paths are under `Calculation tools/backtest`.

| Action | Existing work |
|---|---|
| Keep | `index.html`, eight app modules, synthetic defaults, custom barbell, privacy fixes; original financial/render/export/theme/strategy tests and historical controls |
| Keep and simplify | `data/compile_market_data.py`, requirements/lock, `sources.json`, compiler tests; `tools/setup_data.mjs`, `data_contract.mjs`; `tests/helpers/dataset.cjs`; managed Chromium/browser harness |
| Rewrite | `tools/build_static.mjs`, `deploy_static.mjs`; root `tools/check_static_deployments.mjs` as a small comparison helper if useful |
| Remove framework | `tools/deployment_state.mjs`; runtime manifest/receipt/metadata/closure machinery; backtest-only `tools/vendor/acorn/` if no remaining consumer; framework-only fixtures |
| Simplify shared edits | `tools/check_local_deployments.zsh`, its tests, root/group/project docs and `agents.md` additions; preserve original unrelated audit behavior |
| Retire obsolete tests only | Immutable runtime generations, receipt state machines, AST/import proofs, platform metadata admission and exact xattr restoration. Adapt useful copy/backup/drift/data/browser cases. Never remove financial/privacy assertions to manufacture a pass. |

Reduce `tests/helpers/runner.cjs`, `tests/run_tests.cjs` and runner-policy tests: remove metadata/platform gates and implicit root-suite coupling. Keep practical `tools/check_admission.mjs` checks; retire recursive encoding/container detective machinery solely introduced for speculative contracts. Human staged-tree review remains mandatory.

## 2. Retained app and local data

Ordinary UI defaults are confirmed nonpersonal; preserve them with synthetic labels and preserve `STRATEGIES.barbell`. Audit other prose/fixtures/paths contextually. Do not blanket-scrub numbers or reopen the resolved defaults question.

Keep real workbooks, generated JS/CSV, exports and data-bearing builds outside Git/public artifacts. Retain `MARKET_ATLAS_DATA_HOME`, default `~/.cache/market-atlas`, and the working external cache/current-bundle format. Existing data hashes/provenance support validation and reproduction; do not turn them into deployment identities or invent another data migration.

Remove setup's whole-data-home inventory rejection (`tools/setup_data.mjs` currently accepts `builds` but not `site`). It must allow the new flat `site` output, its temporary siblings and preserved legacy cache entries without deleting or treating unrelated entries as dataset inputs. Continue validating only the selected data and files actually consumed. Cover setup, flat build and a second warm/offline build in one synthetic regression so the first build cannot break the next setup.

Existing `setupData(options)` and `verifySelected(options)` may remain. Keep official downloads/manual `--shiller` and `--damodaran`, external venv/lock, workbook size/schema/chronology/reconciliation checks, JS/CSV parity and failed refresh retaining the prior selection. Warm setup/build stays offline; `--offline` never resolves dependencies or downloads. Compiler output remains external via `--output-dir`; preserve 1872–2025, 154 rows, 1928 splice and historical financial controls. Record actual compile dates; recorded explicit dates serve reproduction only.

**Remove metadata gates throughout the stack:** `data_contract.mjs` (`metadata`, `guardDirectory`, `readOwned`, `safeRoot`); compiler `validate_output_dir` and metadata helpers; setup/build/runner/fixtures/docs. Check ordinary file types, readability, external placement and actual OS errors. No ancestor ACL/xattr/flags allowlists, exact owner/mode requirements on existing directories, or `com.apple.macl` refusal. Never strip attributes or chmod shared ancestors to satisfy tests. Create new private containers with normal restrictive permissions. No exact metadata recovery promise.

Use a venv for all Python/pip execution; only documented venv creation invokes the system interpreter. Keep compatible existing dependencies/lock. Do not reject an otherwise working environment solely for a patch-version or CPU-architecture string; document the tested environment and validate actual dependencies. Do not silently change pins.

## 3. Flat build

Keep `npm run setup:data` and `npm run build`. Build ensures local data exists, then copies exactly **12 files** to external `<DATA_HOME>/site` by default:

```text
index.html
market-data.js  market-data.csv
format.js  stats.js  views.js  lifestyle.js
charts.js  csv.js  engine.js  app.js
DATA_SOURCES.md
```

Source supplies HTML/eight modules/notice; selected external data supplies the pair. Preserve source bytes, relative URLs and script order. No HTML rewriting, `assets/<hash>`, generated deployment manifest, closure parser or runtime dependencies. No compiler/tests/source docs/cache/venv/backups enter the output.

A small `buildStatic({sourceRoot, dataRoot, outputDir})` may support fixtures; its copy portion never downloads or runs Python. Build in a temporary sibling, compare the 12 files to inputs, then replace only a known local output directory. Reject repo/source/webroot overlap, symlinked managed files, and arbitrary output directories containing unrelated material. Normalize runtime files to `0644` and directories to `0755`; the enclosing cache remains private. Ordinary errors fail clearly. Warm `npm run build -- --offline` reuses the pair; browser startup remains offline.

## 4. Ordinary copy deployment

`npm run deploy -- --webroot PATH --build-dir PATH [--dry-run]` consumes a previously built/validated flat directory. Defaults: external `site` build, `UTILITIES_WEBROOT_DIR` or `~/webroot`; target exactly `<webroot>/calculators/backtest`. Never run setup/build/compiler/dependency installation or modify the webserver during deployment.

Use ordinary `cp`/`mv` or straightforward standard-library equivalents. Check source/target separation, regular managed inputs, the specific app target and backup location outside repo/webroot. No metadata allowlist or exact xattr/ACL tests. Dry-run reports target/count/backup action and writes nothing.

1. Compare build inventory/bytes with current source and selected pair before mutation. A stale build must be rebuilt explicitly.
2. Create a timestamped private container under `~/.utilities-deploy-backups/backtest/` with normal restrictive permissions. If the app target exists, move that exact directory into the container using ordinary `mv`. Preserve everything it contains, including legacy symlinks; do not move other calculator files. Stop on an actual move error and report the recovery location/outcome.
3. Create the target and copy the 12 runtime files. On copy failure, remove only the partial target created by this invocation and move the saved tree back. Report both original/restoration errors if restoration fails; retain backup material.
4. Verify installed inventory/bytes and explicit-index HTTP responses. On post-copy failure restore the saved tree by ordinary documented recovery. For a previously absent site, restore absence by removing only this invocation's partial/new target. A brief unavailable route is accepted; no transactional or zero-downtime claim.

First cutover uses the same procedure for the old source-shaped directory; its complete old tree remains private. Move only the confirmed backtest archive under parent `_backups` if still web-served; preserve unrelated archives. Legacy restoration is emergency recovery and restores the old exposure profile.

Recovery is a documented command using the saved backup directory: move the failed/current app aside privately, move the saved directory back, check it. No receipt parser or `--rollback` framework. Never prune backups automatically. Do not police Git cleanliness inside the installer; the executor deploys its validated milestone and records the commit in its report.

Use `http://127.0.0.1:7711/calculators/backtest/index.html`; the folder may remain a file browser. No proxy edits/reload or container rebuild/restart. Honor existing live authorization; otherwise prepare the build/dry-run/recovery for review.

## 5. Small read-only drift integration

Keep the original fleet audit behavior. Replace only the new backtest subsystem: required source/notice files must belong to its existing validated Git inventory; local data is external by design; compare the deployed 12 regular files against current source/notice and selected data using ordinary byte comparison. Flat build has no transformations, so no packager or manifest is necessary. Missing inputs/target, extra runtime content or changed bytes fail this component; never print historical values.

A short `tools/check_static_deployments.mjs` may use the maintained dataset reader. No vendor parser, import graph certification, execution sandbox, receipts, retained-runtime-generation checks or metadata gates. No setup/build/download/write/repair. A local data refresh not redeployed simply reports drift. Preserve original unrelated source-state checks and audit results.

Use a few invented fixtures: match, changed source/data, missing pair/target, leftover source/cache/backup files and no writes. Keep the original fleet suite and retire tests only for withdrawn backtest framework features. Do not implicitly run every root suite from every app test command.

## 6. Validation, docs and commits

Preserve financial/render/export/theme/strategy tests, 69 complete 30-year windows and existing 50/50 and 75/25 controls. Keep CSV content, browser errors, performance, cancellation and accessibility checks. Adapt harnesses to flat paths and ordinary temp directories; remove metadata/exact-platform policy assertions.

`npm test` runs complete retained Node coverage plus all three original browser scenarios on the flat build as `file://` and isolated loopback HTTP at the explicit-index route. Browser expected bytes come independently from source plus selected data, not the artifact being tested. Flat output is the unchanged source-layout assembly, so separate duplicate source-layout/package runs and isolated folder-route requirements are withdrawn. Missing real data/Chromium fails clearly; never silently skip or substitute invented history. Compiler validation remains a separately documented complete command. `test:synthetic` is an explicitly named offline subset, not full historical acceptance.

New tests focus on retained behavior: cold/warm/offline setup, failed refresh, pair/schema validation, correct copy inventory/bytes/modes, backup/copy-error restoration, no-write dry-run and audit match/drift. Retire only assertions describing withdrawn features and explain why in commit bodies. Lower counts from feature removal are not permission to lose app coverage.

| Milestone | Work | Commit after |
|---|---|---|
| A | Private snapshot and classification; keep app/privacy work; simplify compiler/setup/reader metadata policy | Complete relevant compiler/setup/data coverage and staged privacy review |
| B | Flat build and ordinary deploy; slim runner/audit; remove obsolete framework/vendor/tests | Full backtest Node/browser, compiler and affected audit suites |
| C | Consistent docs, clean-checkout validation, authorized local cutover | Final staged review and affected checks for any last executable changes |

Update project `README.md`, `tests/README.md`, `data/README.md`, `DATA_SOURCES.md`, architecture/lessons, `Calculation tools/README.md`, root README/agents and `docs/local_deployment_sync.md`. Replace new complex deployment sections and preserve unrelated prose. Explain acquisition/private storage, flat build, explicit-index URL, ordinary backup/recovery and brief interruption. Mark the previous three plan files superseded. This replacement is the single specification.

Commands after implementation, from backtest unless noted:

- `npm ci` and `npx playwright install chromium`: prerequisites.
- `npm run setup:data`, then `npm run build -- --offline`: local data and flat build.
- `npm test`: complete retained Node/browser coverage, no failures or silent prerequisite skips.
- Prepared external venv interpreter: `-m unittest discover -s data -p 'test_*.py'`: complete compiler suite.
- Repo root: `node --test tools/tests/check_static_deployments.test.mjs` and `zsh tools/tests/test_check_local_deployments.zsh`: full affected audit suites.
- The independent sibling `Calculation tools` suite is not required for README-only grouping edits. Run it only if the executor actually changes its calculators or shared executable/test configuration. Do not run unrelated project suites.
- `npm run deploy -- --dry-run`: no writes; review target/backup action.
- When authorized, deploy and run full installed browser checks at explicit-index. Compare served HTML/scripts/notice/CSV bytes against source/selected data, not just HTTP 200. Run fleet audit and report unrelated findings without repairing them.

Before each commit review complete staged files/diff for private data, and use a nonempty explanatory commit body. A final fresh local clone checks source/privacy and builds using the verified external dataset; run complete required project/audit gates there as clean-checkout validation. Avoid repetitive complete passing runs absent changes/failures; prior counts do not prove this rewrite. Record actual commands/failures/scope. Do not publish data-bearing builds or expand live/publication authorization.

## 7. Review record

Round 1 fresh adversarial review found two material issues, both fixed: setup's existing root inventory would reject the flat `site` output, and the unconditional sibling suite was outside affected testing scope. Setup now validates consumed data without rejecting unrelated root entries, with a warm-rebuild regression; sibling tests are conditional on actual executable impact. No findings rejected. A second fresh sanity reviewer verified both fixes and the revised plan/prompt, returning no findings; another round was not needed.

**Review record:** one round, two material findings fixed, none rejected, no unresolved review findings, no material fixes after the final sanity check; both reviewers had clean context. Implementation/test/deployment results remain executor acceptance checks, not claims this plan-writing session performed them.

The review explicitly challenged unnecessary complexity: safeguards must serve concrete requirements for this single-owner static site. Privacy/financial correctness stay binding; retired frameworks must not return under new names. This plan-only session ran no executable tests or live mutations.
