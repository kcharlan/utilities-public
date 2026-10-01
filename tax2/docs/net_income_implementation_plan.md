# Net Income Implementation Plan

Status: implemented and source-validated on 2026-10-01 on `codex/tax2-net-income`; deployment verification follows the source commit.

**Goal:** Show how much entered monthly income remains after subtracting all taxes in the displayed calculation.

**Architecture:** Add a net-income summary card to the embedded React UI. Derive it from the gross income captured with the accepted computation and the existing `total_monthly` response. Keep calculation results associated with their request so input edits, failures, and overlapping requests cannot produce a misleading net amount.

**Stack:** Existing inline React/JSX, native CSS, FastAPI response, and pytest/Playwright. No new dependency or frontend build.

## Recommendation and alternatives

Recommend **paired summary cards**, immediately below the federal/state breakdown:

```text
Federal Tax                 Selected State Tax(es)

Total Monthly Tax           Net Monthly Income
estimated tax amount        gross minus total monthly tax
```

Keep the existing income inputs and gross monthly/annual line above these cards. The net card uses the existing green income accent, normal high-contrast amount text, and the same typography and card treatment. Give total tax and net equal size; net should be easy to find without overwhelming the tax breakdown. A small, always-visible line below the summary reads: “Net income is after the estimated taxes shown above.”

| Approach | Benefit | Tradeoff / decision |
| --- | --- | --- |
| Paired total-tax and net cards, separate from the breakdown | Keeps the two outcomes together regardless of state count; larger amounts have more room | Adds a summary row; recommended because the center panel is already narrow with both side panels visible |
| Append a net card to the existing grid | Smallest layout change and familiar presentation | Existing grid has three desktop columns: one state creates four cards, placing net alone on a second row; two states creates five cards and can split total from net |
| Gross → taxes → net reconciliation strip or stacked bar | Shows the relationship explicitly | A bar emphasizes proportions over the exact amount, needs special treatment for zero/negative net, and duplicates existing gross/tax information; a text strip is viable but makes the new result less prominent |

The layout recommendation is grounded in the current 280px controls / flexible center / 320px export layout, the three-column `.results-grid`, and the rendered unchanged UI at a 1280px browser viewport, where the current card amounts visibly clip. Do not add a chart, sticky toolbar, additional gross card, retained-income percentage, or monthly/annual toggle for this enhancement.

## Calculation and presentation contract

- **Gross monthly income** is `monthlyEarned + monthlyUnearned`, including both buckets. Do not subtract standard deductions, allocate gross by state, or treat allocated incomes as additional income.
- **Taxes** are the existing response `total_monthly`. It includes federal tax once and every selected state's monthly tax, with allocations already applied. Do not sum the QIF expense and transfer transactions: those are two representations of the same payment.
- **Net monthly income** is displayed gross monthly income minus displayed total monthly tax, reconciled to cents. Compute it locally; keep `TaxRequest`, `TaxResponse`, `compute_taxes`, tax rules, table lookup, and QIF payloads unchanged.
- **Labels:** change the existing “Total Monthly” card label to **Total Monthly Tax**; add **Net Monthly Income**. Preserve total tax's effective-rate sublabel. The net card's sublabel is **Gross minus estimated taxes**.
- Display US dollar amounts with two decimals and grouping. Handle negative net explicitly as `-$123.45`; do not silently floor it to zero. Normalize zero to `$0.00`, never `-$0.00`. Green is a decorative accent, not the sole indicator of meaning.
- A successful zero-income calculation can show zero net. If table mode or synthetic rules produce nonzero taxes at zero income, still subtract them; do not assume zero gross guarantees zero tax.
- Continue using backend totals for either computation mode. State allocations remain independent, including two states at 100%; do not normalize allocations.
- Net is monthly only in this change. Existing gross annual information stays. The backend's `total_annual` is based on annual calculations and can differ slightly from `total_monthly * 12`; do not introduce an annual net figure with an unexplained rounding basis.
- Use a display-cents helper consistent with the existing `en-US`, two-decimal currency formatter. Convert its rounded decimal output to integer cents rather than independently applying binary floating-point rounding at a half-cent boundary. Then subtract integer cents and format the result. For example, deliberately synthetic gross `$100.005` displays `$100.01`; taxes `$10.00` must produce net `$90.01`. Sum the two raw income buckets before rounding the gross total.

Binding arithmetic:

```text
grossCents = centsFromTwoDecimalDisplay(acceptedGrossMonthly)
taxCents   = centsFromTwoDecimalDisplay(acceptedResponse.total_monthly)
netCents   = grossCents - taxCents
netMonthly = netCents / 100
```

The helper can use `Intl.NumberFormat` without grouping and its formatted integer/fraction parts; sign handling must be explicit. Reuse the same rounding settings for the visible gross line. This is display reconciliation, not a change to tax precision or input parsing.

## Current code and intended file scope

The working directory `~/tax2` is a maintained deployment copy, not a Git checkout. Its executable currently matches `<repository>/tax2/tax2` byte for byte. All implementation must start in the canonical repository on a dedicated feature branch, followed by validation and repository-to-local deployment. Do not edit the deployed application and backport it.

The user confirmed a clean `main` and authorized implementation on a new feature branch in the existing canonical checkout. No worktree is needed. Preserve concurrent work; do not merge or publish this branch without an explicit instruction.

After implementation is authorized and validated, use the repository's documented deployment workflow in `<repository>/docs/local_deployment_sync.md` to update `~/tax2`: back up replaced destination files, copy only tracked Tax2 files from the validated source, preserve local configuration/generated tables/venvs, compare source and destination, and smoke-check the deployed app. `tools/check_local_deployments.zsh` is the read-only audit, not the copying operation. Implementation and repository-to-local deployment are now authorized.

Paths below are relative to the canonical `tax2/` project directory; recheck line positions before editing.

| File | Relevant code / responsibility | Planned change |
| --- | --- | --- |
| `tax2` | `HTML_TEMPLATE`: `.results-grid` / `.result-card` (~828), responsive CSS (~1133), `MainPanel` (~1387), `App` (~1579), debounced effect (~1626), `computeTaxes` (~1689), `downloadQIF` (~1726), `ExportPanel` (~1483) | Request-associated result lifecycle, display-cents helper, summary pair, net card, responsive styling |
| `tests/test_browser_smoke.py` | `live_server`, browser error guards, existing recomputation/theme/failure and Tailwind-unavailable coverage | Extend actual browser behavior tests and update the changed total-tax label assertion |
| `README.md` | Web UI section | Explain the monthly net result and its calculation scope |
| `docs/Usage.md` | Calculate estimated tax | Explain total/net cards and pending/error behavior |
| `docs/UI_Design_Reference.html` | Static result cards / grid / responsive CSS | Reflect the chosen layout with conspicuously synthetic values that reconcile |

Reference without changing: `tests/test_api.py` (existing computation goldens), `docs/multi_state_design.md` (allocation/QIF invariants), `taxkit/engine.py`, and shared `../tools/testkit.py`. Do not introduce a separate frontend project or refactor unrelated launcher/UI code.

## Implementation tasks

### 1. Keep accepted results tied to their computation

- [x] Add failing Playwright regressions for changing inputs while a response is delayed, a failed current request after a success, and overlapping requests completed in reverse order. Use deterministic request routing/event coordination, not timing-only sleeps. Include an older failure arriving after a newer success. At least one obsolete-response case must use a controlled fetch promise that deliberately ignores abort, or delayed JSON resolution after fetch completes: ordinary aborted routes alone do not exercise the active guard. Keep these interception fixtures confined to lifecycle tests.
- [x] Replace the separate unassociated success/loading/error bookkeeping with one request-associated computation record, or an equivalent equally strict implementation. Suggested record: `{ key, status, grossMonthly, data, error }`, where status is `idle`, `pending`, `success`, or `error`; `data` is the existing `TaxResponse` shape on success.
- [x] Build the request payload once from all calculation dependencies: monthly earned/unearned income, filing status, year, mode, ordered selected-state codes and each allocation (default 100). Serialize that payload deterministically as its key. Retain the request's gross sum with the accepted response.
- [x] Let the existing 300ms effect own the request lifecycle: capture payload/key, set pending, schedule the fetch, and clean up timer/request on dependency changes and unmount. Use `AbortController` plus an effect-local active flag. Only an active effect may publish success, error, or pending completion; cancellation is silent. Remove or adapt `computeTaxes` so it cannot publish outside this ownership rule.
- [x] In render, accept a success only when its key equals the current payload key. A key mismatch means pending immediately, including the interval before the next effect runs. An active flag guards request generations even when inputs change A → B → A and the serialized key repeats. Do not let an old response/error/finally handler clear the newest loading state.
- [x] Derive the `taxResults` passed to `MainPanel` and `ExportPanel` from this accepted current success. Display “Calculating...” while pending; on a current error show the existing error banner with no result cards. Disable QIF and guard `downloadQIF` whenever no current accepted result exists. QIF still exports taxes only; net never becomes a transaction.
- [x] Run the targeted browser tests and demonstrate the new regressions fail against the old lifecycle and pass after the change. Keep expected synthetic failure logging explicit and keep unexpected browser errors fatal.

### 2. Add the paired summary and net calculation

- [x] Add failing browser scenarios asserting the actual net amount, including both income buckets, state toggling, changed allocations, zero income, fractional-cent gross, and a synthetic result whose taxes exceed gross.
- [x] Add the display-cents helper inside the existing inline module and derive net from the accepted gross/response. Federal/state effective-rate sublabels must also use the accepted gross denominator, avoiding live-input/old-response mixtures.
- [x] Keep federal/state cards in `.results-grid`; move the total card into a distinct `.summary-grid` alongside `.result-card.net`. Preserve `.result-card.total .result-amount` so existing amount selectors remain valid. Use semantic grouping/names sufficient to locate the summary and each amount without relying on accent color.
- [x] Make both grids fit the available center-panel content width: use an adaptive breakdown grid, maximum three columns, and a summary pair capped at two columns. Use at least about 230px per card when space permits, accounting for the existing 24px gaps; a viewport breakpoint alone cannot reliably describe center-panel space because the export panel disappears at 1200px. Set the app's flexible center track to `minmax(0, 1fr)` and allow `.main-panel`/cards to shrink with `min-width: 0`, so intrinsic content does not enlarge the entire layout. At the existing ≤768px breakpoint both grids have one column. Preserve DOM order federal → selected states → total tax → net.
- [x] Ensure amounts and explanatory text remain readable in both themes, at 200% zoom, and for large synthetic amounts. Allow long amounts to wrap within their card when necessary; do not truncate the monetary value. Preserve native CSS styling when Tailwind fails to load.
- [x] Run the expanded targeted browser tests; inspect both themes at 1440px and 1280px, near the 1200px export-panel breakpoint, 900px, and 390px. Assert no document/card horizontal overflow, and verify total/net adjacency when sufficient space exists and stacking when it does not.

### 3. Documentation and complete validation

- [x] Update the two operating guides and the static reference. Explain that net subtracts all displayed federal/selected-state estimates; it is not an additional tax or a QIF export item. Keep reference arithmetic consistent and mark all example amounts synthetic.
- [x] Extend the existing Tailwind-unavailable test to verify that the new summary layout/card remains visible and styled. Preserve the existing CDN/import-map/theme and browser-error checks.
- [x] Run the full Tax2 suite, plus the canonical repository's required launcher smoke checks below. Investigate every failure; do not weaken assertions or narrow the final suite to obtain a pass.
- [x] Review the implementation diff for scope and invariant preservation. If committing, follow the imperative subject + meaningful body requirement and inspect all branch commits before any publication. Keep unrelated work and local runtime state out of the diff.

## Browser acceptance scenarios

Use conspicuously synthetic fixtures under temporary `TAX2_HOME`, isolated from personal preferences. Existing API goldens provide useful fixed references:

| Scenario | Expected behavior |
| --- | --- |
| Existing 2026/single/rules golden, monthly unearned 5000, earned 0, GA 100% | Existing total tax `$621.93`; net `$4,378.07` |
| Same golden with GA and PA both 100% | Existing total tax `$775.43`; net `$4,224.57`; federal counted once |
| Same golden with GA 100%, PA 50% | Existing federal `$418.33`, GA `$203.60`, PA `$76.75`; total `$698.68`, net `$4,301.32` |
| Both earned and unearned nonzero | Net reconciles to their displayed combined gross minus response total, with both buckets represented in the actual POST |
| Synthetic gross 100.005 / tax 10.00 | Displayed gross `$100.01`, net `$90.01` |
| Successful gross 0 / tax 0 | `$0.00` net, no invalid percentage, no negative zero |
| Synthetic gross 100 / tax 125 | Net `-$25.00`, without clamping |
| Lookup-table mode using synthetic table/response fixtures | Net uses entered gross and the returned table-mode total; no independent tax recalculation |
| Delayed/latest request and input changes | Prior cards immediately stop being current; no mixed calculation; QIF disabled through debounce and fetch |
| Late success or late failure from obsolete request | Latest pending/success/error state remains authoritative, including A → B → A |
| Current request fails, then user changes input and succeeds | Error replaces cards; QIF disabled; next valid success restores all cards and export |
| Theme reload, responsive layout, Tailwind outage | Both summary amounts stay readable, correctly ordered, and visible; existing theme persistence remains intact |

For real backend scenarios, compare rendered currency against the intercepted actual `/api/compute` response rather than hardcoding additional tax formulas. For races, rounding, negative net, and table mode, narrowly scoped synthetic responses are appropriate; do not route away real computation in all tests. Verify a successful QIF request still contains the accepted federal/state amounts and contains no net field.

## Verification commands for the executor

Run from the canonical project's `tax2/` directory (or its corresponding worktree). The shared `../tools/testkit.py` is required by the existing tests; do not run the maintained home copy's suite as though it were self-contained.

```bash
python3 -m venv .venv                     # only if this project has no venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest tests/test_browser_smoke.py -v
python -m pytest
./tax2 --help
```

Expected: targeted browser tests and the complete Tax2 suite pass with no unexpected browser errors; `--help` exits successfully. Python execution/installations stay in the activated venv; the launcher's uv shebang uses uv's isolated environment.

Then start `./tax2 --no-browser --port <verified-free-port>` with `UTILITIES_TESTING=1` and a temporary external `TAX2_HOME`; request `/` and `/api/status`, expecting HTTP 200, the HTML UI at `/`, and status JSON containing `version: "2.0"` and `rules_dir: "default"` when no custom rules directory is supplied; terminate the FastAPI process cleanly and remove that exact temporary runtime. Tax2 currently does not auto-scan ports, so verify availability before starting. If launcher header/bootstrap imports or dependencies change, run `uv run --script ../tools/check_uv_headers.py` as well; the planned UI work requires no such changes. No rule/table-generation command is needed because the plan does not change those components.

**Planning validation (before implementation):** Source inspection, PKM lookup, and read-only rendering of the unchanged UI were performed. No implementation tests have been run for this document-only deliverable, and no application changes are claimed.

## Review record

One review round completed with fresh, clean-context adversarial and sanity reviewers. The adversarial review found no material issues and one polish issue: aborting delayed routes could leave the active guard untested. Fixed by requiring an obsolete response that ignores abort or resolves JSON late. Self-review also corrected one material source-contract error in the proposed launcher smoke check: `/api/status` returns `version` and `rules_dir`, not `status: ok`. Clarified intrinsic sizing and recorded the observed amount clipping. The independent sanity check verified these changes, reported no findings, and requested no second round. Material findings fixed: 1 (self-review); polish findings fixed: 1. Findings rejected: none. Unresolved items: none. Material fixes after the final sanity check: none.

Subsequent user workflow clarification recorded: implement in the canonical repository on a feature branch, prefer the existing checkout while the user checks concurrent work, then deploy to the local copy using the documented synchronization workflow. This clarification changes no UI/calculation design; it was checked against the deployment guide without another review round.


## Implementation validation record

- Regression-first verification reproduced the missing net card and stale cards during the debounce interval before implementation.
- Expanded browser suite: 15 passed. Full Tax2 suite: 39 passed, including API, CLI/table, configuration, engine, golden, QIF, rules, and browser tests.
- Actual uv launcher: `./tax2 --help` exited successfully. Isolated `--no-browser` startup on a verified free port returned HTTP 200 for `/` and `/api/status`, with the documented status fields and the net-income UI in the served HTML.
- Visual inspection of the running source confirmed readable federal/state cards and the paired total-tax/net summary at 1280px. Automated layout checks covered both themes, 1440/1280/1201/1200/900/768/390px, large synthetic amounts, and a halved desktop viewport for zoom layout.
- Independent clean-context specification and code-quality reviews both reported no actionable findings. Nothing was rejected or left unresolved. No application changes followed the reviews.
- The tax API, calculation engine, rules, table lookup, and QIF schemas remain unchanged. Only Tax2 source, browser tests, UI documentation, and this plan are in scope.
