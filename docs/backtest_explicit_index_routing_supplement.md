# Backtest routing supplement: explicit installed entry

> **Superseded:** [backtest_simple_port_implementation_plan.md](backtest_simple_port_implementation_plan.md) is the sole active specification. This document is retained as history; its withdrawn contracts are not implementation or acceptance gates.

**Date:** 2026-10-01. **Status:** Binding owner decision for the implementation in progress.

This supplement supersedes only conflicting routing and installed-route acceptance requirements in [the original implementation plan](backtest_monorepo_port_implementation_plan.md) and [the local data addendum](backtest_local_data_setup_addendum.md). Both documents remain unchanged. The data, privacy, packaging, recovery and authorization requirements continue to apply.

## Installed URL

Use `/calculators/backtest/index.html` as the canonical installed application URL. With the existing loopback service, the application link is `http://127.0.0.1:7711/calculators/backtest/index.html`. App/catalog links, deployment instructions, installer output and installed browser-test targets must use the explicit entry.

The folder URL `/calculators/backtest/` may retain the existing file-browser behavior. It is not an application acceptance target. Do not change shared webserver or proxy routing for this port, restart or reload the proxy, or represent a folder listing as a successful application response.

The decision follows read-only checks: the explicit-index response matched the original application entry bytes; the folder response returned different file-browser content. A successful HTTP status alone does not verify either the application or an asset.

## Coverage and acceptance

Preserve the complete source-layout `file://` browser-test matrix in a temporary assembly outside the repository using verified external historical data. Preserve all packaged file and isolated HTTP coverage, including both directory and explicit-index routes on the test server. The isolated server's directory-index behavior verifies portable artifact serving; it does not assert that the existing shared proxy opens the application at the folder URL.

When live deployment is authorized, run the complete installed application/browser checks at the explicit-index URL: all existing scenarios and financial assertions, reload/theme, Window/Sweep/Lifestyle, frontier and cancellation, narrow/keyboard behavior, and every CSV download check. Keep the historical controls and performance bound unchanged. A different entry body, failed check or unexpected browser request/error is a failure.

Compare the installed entry and every expected script, attribution notice and dataset CSV response byte for byte with the independently validated artifact. Check asset inventory, hashes and modes through the read-only audit. Do not use HTTP 200 or a deployed manifest as the expected source of truth. Relative asset and notice URLs must resolve beneath `/calculators/backtest/` when opened from `index.html`.

## Authorization

This routing clarification adds no live-deployment, proxy-reload or publication authorization. Continue setup review, packaging, installer/rollback, audit, documentation and validation within the existing authorization. Prepare the validated local artifact, deployment dry-run and recovery procedure for review when live authorization is absent. Historical inputs, datasets, local builds and private recovery records stay outside the public repository and publication paths.

## Review record

One round of fresh clean-context review found no material findings and one polish issue, fixed by distinguishing the source-layout `file://` browser-test matrix from the folder file browser. A second fresh clean-context sanity review verified the fix and returned no findings; another round was not needed. None rejected, no unresolved review findings, and no material fixes after the final sanity check. The original plan and local-data addendum retain their recorded SHA-256 hashes. Implementation and installed verification remain separate gates.
