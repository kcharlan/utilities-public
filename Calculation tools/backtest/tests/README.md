# Market Atlas tests

Invented fixtures exercise failure paths without distributing history. Full
acceptance uses a verified external real dataset and retains the original
financial assertions, barbell behavior and all three browser scenarios.

## Prerequisites

From this project, use Node.js 24 or newer, the locked dependencies and
managed Chromium. Verified history comes from the owner's `npm run setup:data`;
agents never run it (see the [project guide](../README.md)), so complete
acceptance runs only where the owner has already prepared data:

```sh
npm ci
npx playwright install chromium
npm run setup:data   # owner only: may download workbooks
```

`MARKET_ATLAS_DATA_HOME` defaults to `~/.cache/market-atlas`.
`MARKET_ATLAS_TEST_DATA_ROOT` optionally pins one verified `datasets/<bundleId>`
generation. Tests never acquire history, bootstrap Python or install packages.
The compiler needs a ready external venv with the locked dependencies:

```sh
export MARKET_ATLAS_TEST_PYTHON="<READY_COMPILER_VENV>/bin/python"
```

All Python runs inside that venv. Actual isolation, dependencies and imports
are checked; a patch-version or CPU string alone is not an admission gate.
See [data environment instructions](../data/README.md).

## Complete acceptance

```sh
npm test
npm run test:synthetic
PYTHONDONTWRITEBYTECODE=1 "$MARKET_ATLAS_TEST_PYTHON" -B -m unittest discover -s data -p 'test_*.py' -v
```

`npm test` runs every retained Node test followed by the three original browser
cases in two targets: flat `file://` build and isolated loopback HTTP at
`/calculators/backtest/index.html`. It ignores URL overrides; the separate
`test:browser` command supports one explicit local override. Expected HTML,
ordered scripts, source notice and CSV bytes are captured independently from
current source and selected history before assembly. Missing data or managed
Chromium fails clearly; skips and invented substitutes are prohibited.

The original cases retain financial controls, Window/Sweep/Lifestyle,
frontier performance, cancellation, reload/theme, narrow/keyboard behavior,
browser errors/request checks and actual CSV schema/content/formula guards.
The 69 complete 30-year historical windows and existing 50/50 and 75/25
controls remain unchanged. File startup is offline. Browser profiles, snapshots,
exports and data-bearing temporary assemblies stay outside the public checkout
and are cleaned after normal completion, errors or cancellation.

`test:synthetic` runs its explicitly named whole-file invented Node subset and
both complete invented compiler modules. It does not certify real historical
or browser acceptance and does not implicitly invoke the root audit suites.
Full compiler discovery also reproduces the selected pair exactly from all three
retained inputs (two workbooks and the FRED CSV) and the recorded compile date, without acquisition or
selector changes. Missing retained prerequisites fail.

Flat-build and copy-deploy tests cover inventory/bytes, runtime modes,
external boundaries, cold/warm/offline setup compatibility, private whole-tree
backup, failed-copy restoration and no-write dry-run. Read-only audit fixtures
cover source drift, a missing target, missing or empty installed data and
leftover runtime material; the audit checks installed data for presence only.
Withdrawn immutable runtime releases, receipt/state machines, AST import proofs,
strict native metadata admission and exact restoration tests were retired
when the port adopted the flat copy lifecycle. Application,
financial, privacy and meaningful recovery coverage is retained.

## Root audit checks

Run independently from the repository root:

```sh
node --test tools/tests/check_static_deployments.test.mjs
zsh tools/tests/test_check_local_deployments.zsh
```

These use invented isolated fixtures, preserve original fleet assertions and
perform no live deployment. No vendored parser or deployment receipts are needed.

## Installed acceptance

Only after live deployment is authorized, compare the installed responses and execute all three
cases at the explicit index URL:

```sh
MARKET_ATLAS_TEST_URL="http://127.0.0.1:7711/calculators/backtest/index.html" npm run test:browser
```

The installed bytes must equal current source and selected data, not merely
return HTTP 200. The shared folder route may remain a file browser; tests do
not require a proxy change. This command does not grant deployment authorization.
