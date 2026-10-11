# Market Atlas

A standalone browser calculator comparing retirement withdrawal strategies over
historical windows. Ordinary defaults are visibly synthetic examples; the
configurable barbell reserve strategy is preserved. Scenario inputs and pinned
comparisons stay in page memory. Only the appearance preference is stored in
`localStorage` (`market-atlas-theme`). The runtime needs no backend or network.

## Setup and build

Use Node.js 24 or newer and npm, matching this project's `engines` contract.
Cold data setup also needs Python 3.10 or newer available for external venv
creation; the default command is `python3.14` (override with `--python`).

The public checkout contains application/compiler source and invented tests.
Real workbooks, generated history, builds, exports and validation records stay
outside Git and public artifacts.

**Market data is not redistributable.** No grant to redistribute the upstream
workbooks or the history built from them was verified (see
[DATA_SOURCES.md](DATA_SOURCES.md)). Never commit market data, builds or exports,
and never publish a data-bearing build. Acquiring data is a manual step for the
owner only. Agents must not run `npm run setup:data` (with or without
`--refresh`) or `npm run build` without `--offline`, unless the owner explicitly
asks: either can download workbooks and install the compiler's Python packages.
The read-only fleet audit only checks that data is already installed in the
webroot (see below). `npm run deploy` still needs a locally built, verified
dataset, which the owner prepares.

The owner prepares data and builds from this project directory:

```sh
npm ci
npm run setup:data
npm run build -- --offline
```

`MARKET_ATLAS_DATA_HOME` defaults to `~/.cache/market-atlas`. First setup prepares
an external Python venv, resolves the locked dependencies and acquires missing
official workbooks. Python execution and package installation occur only in the
venv. Manual inputs are supported:

```sh
npm run setup:data -- --shiller "<INPUT_DIR>/ie_data.xls" --damodaran "<INPUT_DIR>/histretSP.xls" --fred "<INPUT_DIR>/DTB3.csv"
npm run setup:data -- --refresh
npm run setup:data -- --offline
```

Warm setup/build reuses verified selected history offline, without Python,
downloads or dependency installation. `--offline` fails clearly when prerequisites
are missing. Failed refresh keeps the prior selection. Existing unrelated cache
entries are left alone. See [data maintenance](data/README.md) and
[source attribution and local-use restrictions](DATA_SOURCES.md).

The "Josh Tbill full refill" strategy sizes spending at the start of each year,
then pays it after returns and fees. Stock gains fund spending first; T-bills
cover the rest, with stocks covering any shortage. An empty bill sleeve is
refilled from stocks to the fixed first-year spending buffer when possible.
The T-bill series selector applies to every strategy holding bills. Damodaran
remains the default; daily FRED DTB3 uses annual mean discount-basis rates,
with Damodaran through 1953. Neither series compounds within a year.
The reference spreadsheet's 2024 and/or 2025 bill inputs differ from DTB3;
available evidence cannot identify which year accounts for the residual gap.

Adding DTB3 to an existing legacy selection requires the owner to supply
`--fred "<INPUT_DIR>/DTB3.csv"` once, then build offline. Existing Shiller and
Damodaran retained inputs are reused. Avoid `--refresh` for this migration:
it reacquires all sources and can change historical controls. Complete
historical acceptance requires the new selected bundle. Windows extending
beyond 2025 are incomplete; complete 30-year windows end with starts in 1996.

Build writes `<DATA_HOME>/site`: `index.html`, eight app modules,
`market-data.js`, `market-data.csv` and `DATA_SOURCES.md`. All twelve files retain
input bytes and relative links; no manifest, rewriting or runtime dependencies
are added. Open this external build's `index.html`; source alone lacks history.
Do not publish a data-bearing build without a separate distribution decision.

## Local install and recovery

Deploy consumes an existing build and verifies it against current source and
selected history. It never runs setup, compilation or dependency installation.

```sh
npm run deploy -- --dry-run
npm run deploy -- --dry-run --webroot "<WEBROOT>" --build-dir "<DATA_HOME>/site"
# Run only after live deployment is authorized:
npm run deploy -- --webroot "<WEBROOT>" --build-dir "<DATA_HOME>/site"
```

`--webroot` defaults to `UTILITIES_WEBROOT_DIR` or `~/webroot`; the target is
exactly `calculators/backtest`. Dry-run writes nothing. Installation moves the
whole prior app into a timestamped private container beneath
`~/.utilities-deploy-backups/backtest/`, then copies twelve runtime files.
Brief downtime is acceptable. Copy/verification failures restore the saved tree
by ordinary moves and report any recovery errors. Backups are never pruned.
Legacy files and symlinks remain in the private backup; other calculators are
untouched. Existing `com.apple.macl` is accepted, without stripping attributes
or changing shared ancestor permissions. Exact metadata restoration is not promised.

For manual recovery, replace the placeholders with the reported backup and
actual webroot. Keep the displaced tree outside the webroot:

```sh
mkdir -m 700 "<PRIVATE_RECOVERY_DIR>"
mv "<WEBROOT>/calculators/backtest" "<PRIVATE_RECOVERY_DIR>/failed-site"
mv "<BACKUP_CONTAINER>/backtest" "<WEBROOT>/calculators/backtest"
```

Check restored contents and the explicit index URL. If the current target is
absent, omit the first move. If the prior target was absent, recovery removes
only this installation's new target after moving it privately. Restoring a
legacy tree also restores its old exposure profile; this is emergency recovery.

The canonical installed URL is
`http://127.0.0.1:7711/calculators/backtest/index.html`. The folder route may
remain a file browser. No proxy reload, container restart or routing change is
needed. Live deployment requires separate authorization.

## Validation and audit

Prepare managed Chromium explicitly, then run complete affected checks:

```sh
npx playwright install chromium
npm test
npm run test:synthetic
PYTHONDONTWRITEBYTECODE=1 "<READY_COMPILER_VENV>/bin/python" -B -m unittest discover -s data -p 'test_*.py' -v
```

`npm test` runs all retained Node tests and all three original browser scenarios
on the flat build as a file and at an isolated loopback explicit-index route.
Expected response bytes come from source and selected history independently.
Missing history/Chromium fails; history is never replaced by invented data.
The synthetic subset is offline invented coverage, not historical acceptance.
See the [test guide](tests/README.md) for prerequisites and installed acceptance.

From the repository root, the read-only fleet audit compares the ten installed
code and notice files byte-for-byte with validated Git source, and checks that
the installed `market-data.js` and `market-data.csv` exist as regular, non-empty
files:

```sh
zsh tools/check_local_deployments.zsh
```

The audit never reads the external data home, so it works on machines without
local history, and it does not verify the data's content. A missing deployment,
missing or empty data, extra or missing files and changed code each fail with a
named reason. Refreshed local history is not reported as drift; rebuild and
redeploy to install it. Audit does not download, build, repair or write
deployment state. See the [deployment guide](../../docs/local_deployment_sync.md).

The [architecture](docs/architecture.md) documents calculation behavior;
[lessons](docs/LESSONS_LEARNED.md) explain privacy and validation boundaries.
