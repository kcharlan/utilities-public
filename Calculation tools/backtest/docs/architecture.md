# Market Atlas architecture

Market Atlas is a local static calculator for comparing generic withdrawal
strategies over historical annual windows. Ordinary numerical defaults are
synthetic illustrations; the configurable barbell reserve is a generic custom
strategy. Historical simulations describe this model, not a forecast or
personal financial recommendation. See the [project guide](../README.md) for
operation and [source lineage and use restrictions](../DATA_SOURCES.md) for data
attribution.

## Runtime and module boundaries

The [entry page](../index.html) contains the HTML/CSS and one dependency-free
inline appearance initializer. It loads nine local classic scripts, in order:

1. `market-data.js` supplies `globalThis.MARKET_DATA`.
2. [format.js](../format.js) exposes `MarketAtlasFormat`.
3. [stats.js](../stats.js) exposes `MarketAtlasStats`.
4. [views.js](../views.js) exposes `MarketAtlasViews`.
5. [lifestyle.js](../lifestyle.js) exposes `MarketAtlasLifestyle`.
6. [charts.js](../charts.js) exposes `MarketAtlasCharts`.
7. [csv.js](../csv.js) exposes `MarketAtlasCsv`.
8. [engine.js](../engine.js) exposes `BacktestEngine`.
9. [app.js](../app.js) owns browser controls, render scheduling and page state.

The helper/engine modules also expose CommonJS exports for Node tests.
Formatting, statistics, view models and SVG generation remain separate from
the DOM controller. This is vanilla JavaScript: the runtime needs no framework,
CDN, backend or compilation service. The public checkout deliberately omits
`market-data.js`; open an external built entry rather than the raw checkout.

## Annual simulation model

The engine accepts validated options and cloned/frozen inputs. Annual rows
carry stock, ten-year-bond and bill nominal total returns, CPI change and quality.
Strategy asset requirements constrain available years; missing bill history is
not fabricated. The compiler's splice, source reconciliation and rounding are
documented in the [data guide](../data/README.md) and source notice.

For each year, `runSimulation` uses this order:

1. Give the strategy beginning-year balances, accumulated CPI and remaining
   horizon, then obtain its spending and withdrawal-source decision.
2. Gross the requested after-tax spending up by `1 / (1 - taxRate)` and withdraw
   from the selected sleeves before applying returns.
3. If the requested gross withdrawal exceeds starting assets, record actual
   delivered spending and exhaustion, then stop. That row has zero applied
   return amounts/fees and no ending CPI update.
4. Otherwise apply that year's asset returns, charge the annual fee, and execute
   the strategy's dollar/allocation rebalance or the shared annual allocation
   rebalance when applicable.
5. Update CPI and real ending wealth, append the ledger row, and call the
   optional strategy `afterYear` hook.

The tax input is a flat effective rate on withdrawals, not a tax-bracket,
account-type or cost-basis model. Spending uses beginning-year CPI; real ending
wealth uses ending-year CPI. The simulation is annual, not a monthly cash-flow
model. The strategies are fixed real spending, fixed portfolio percentage,
Guyton–Klinger guardrails, and configurable barbell reserve spending/refill
rules. Preserve their existing timing and parameter semantics when changing
presentation or deployment code.

## Window, Sweep, Lifestyle and frontier

**Window** selects a contiguous start-year/horizon sequence and runs one
configuration. It presents solvency, nominal/real balances, spending and the
annual ledger. A surviving sequence shorter than the requested horizon remains
partial rather than proving a completed horizon.

**Sweep** runs configurations across available start years. Its heatmap adds
multiple horizons. Complete windows determine survival fractions, terminal
wealth summaries and lifestyle aggregates; partial windows are counted
separately. Safe-rate values are computed only for strategies declaring that
capability and complete horizons. The engine searches within its bounded rate
range using the strategy's monotonic or adaptive search, rather than treating
every strategy as monotonic.

**Lifestyle** is a view of real after-tax spending in retirement-start dollars,
regardless of the balance display setting. `spendingProfile` includes zeros for
unfunded years after failure; its failed floor is zero, while funded floor and
the last partial payment remain distinct. It reports typical spending, floor,
ceiling and deepest cut. `needProfile` compares a configurable real spending need
with that path, including years below need, longest run and accumulated
shortfall expressed in year-one-spending units.

The **frontier** starts from the last committed Sweep snapshot, varies a bounded
numeric strategy parameter, and reruns complete fixed-horizon windows. It plots
worst and median real spending floors and failure counts; failures contribute
a zero floor. Comparison series with unequal initial balances are normalized
by their own initial balance. It is a parameter sensitivity view, not an
optimizer that chooses a recommended strategy.

## Rendering, state and exports

`createRenderCoordinator` tags each request and aborts its predecessor.
`executeRendererRequest` admits progress and final commits only for the current,
non-aborted request; stale results and stale errors cannot overwrite newer
output. The latest-wins scheduler coalesces control changes to a frame.
Sweep/frontier jobs yield to the UI and check cancellation. In-memory caches
include configuration, horizon/start-year and data-generation identity.
The frontier has its own coordinator and cannot replace Sweep exports.

Controls, pinned comparisons and scenario snapshots stay in memory.
Only appearance persists in `localStorage`, under `market-atlas-theme`; selecting
system appearance removes that key. No scenario persistence or session-storage
contract is introduced.

CSV buttons use accepted committed render models. [csv.js](../csv.js) defines
three schemas: Window annual ledger/spending rows, Sweep configuration/window
summaries, and heatmap start-year/horizon/metric/status/value cells. Unfunded
Window years remain explicit, and partial/no-rate cells do not masquerade as
numeric results. Serialization uses the first row's ordered keys, CRLF rows and
standard CSV quoting. Strings beginning with `=`, `+`, `-` or `@` after ASCII
control/space padding receive a leading apostrophe; negative numeric values
remain numeric. User-triggered Blob downloads revoke their object URL.
Downloads remain user-managed local data-bearing outputs.

## External data and deterministic packaging

[setup_data.mjs](../tools/setup_data.mjs) owns controlled data preparation;
[data_contract.mjs](../tools/data_contract.mjs) supplies read-only verification.
Under the external data home, raw inputs are retained by hash, compiled bundles
under `datasets/<bundleId>`, selection in `current.json`, and local builds under
`site`. The compiler venv and real inputs are never public source.
The compiled JS assignment is parsed as strict JSON in Node, never evaluated.
Pair parity, retained recipe bytes, provenance and identities are checked.

Cold setup prepares the supported external compiler environment and acquires
missing reviewed official inputs over HTTPS. Warm reuse of the verified current recipe
needs no Python, network, dependency installation or date change. Manual inputs,
refresh and exact retained-input reproduction are distinct operations; identical
financial rows do not imply identical metadata or bundle identity.

[build_static.mjs](../tools/build_static.mjs) copies exactly twelve runtime
files into the external `<DATA_HOME>/site`: unchanged HTML/eight modules/notice
from source and the verified external data JS/CSV pair. Relative URLs and
script order remain intact. Runtime files use `0644` and directories `0755`,
inside the private local data boundary. No manifest, hashed asset generation or
HTML rewriting is needed.

Installation compares the flat build against current inputs, moves the complete
prior app into a new private backup container and copies the twelve files.
Copy/verification failures restore the saved tree by ordinary moves. Brief
local downtime is acceptable. There are no release receipts, state machines,
parser proofs or exact metadata restoration requirements. Existing native
attributes are accepted; shared ancestor permissions remain untouched.

The [fleet helper](../../../tools/check_static_deployments.mjs) compares installed
inventory/bytes with current source from validated Git membership and selected
external data. Refreshing local data without redeployment reports drift. It
does not acquire, build or repair. See the [operator guide](../README.md).

## Source acceptance and installed entry

The canonical installed route is
`http://127.0.0.1:7711/calculators/backtest/index.html`. The folder route may
remain a file browser. The [test guide](../tests/README.md) specifies retained
Node tests and all three original browser scenarios on flat file and isolated
HTTP explicit-index targets. Independent source/data bytes define expectations.
Installed acceptance follows authorized cutover and checks served bytes as well
as application behavior; source validation does not imply live deployment.
