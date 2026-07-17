# div_conv

`div_conv` converts supported Fidelity and Vanguard activity CSV exports into an Actual-compatible “cooked” CSV and QIF investment transactions. It is a standalone, standard-library-only [uv](https://docs.astral.sh/uv/) launcher.

## Privacy and setup

Never put real account names, mappings, securities, categories, transfers, exports, or generated output in this public repository. Runtime configuration belongs at `~/.div_conv/config.json`. `DIV_CONV_HOME` may point to another runtime directory for controlled execution and tests.

On first processing run, the launcher atomically creates an intentionally incomplete configuration skeleton and stops. Fill it locally; there is no automatic migration from an older converter. [`config.example.json`](config.example.json) is synthetic documentation only and must not be used unchanged for real input.

The runtime directory and configuration are hardened to modes `0700` and `0600` on every processing run, including when they already exist. Symbolic links are rejected for both paths so the launcher never changes or reads a link target unexpectedly. Permission and file-type errors stop processing with an actionable error.

If a later version finds that an entire registered brokerage section is absent, it adds an empty section and prints a highly visible warning naming both the section and config path. Processing may continue for another, already configured brokerage. Selecting the backfilled brokerage stops with an actionable incomplete-configuration error.

## Usage

```sh
div_conv --help
div_conv export.csv
div_conv --brokerage fidelity 'exports/*.csv'
div_conv --output-dir /path/to/local/output export-1.csv export-2.csv
```

Quote glob patterns when the launcher should expand them. A batch must contain one brokerage only. Without `--brokerage`, every header is checked against all registered adapters and an ambiguous union header is rejected. `--brokerage` checks only the selected adapter’s contract, so it can intentionally resolve such ambiguity while still rejecting files that do not contain that adapter’s required headers. Files are fully validated before any output is committed.

Each input produces `<input-stem>.cooked.csv` and `<input-stem>.qif`. Existing regular-file output is refused unless `--overwrite` is supplied; directories, special files, and symbolic links are never valid output targets. Every artifact for the invocation is staged and synced before commit, then installed only if its target name is still unclaimed. A failed stage or commit removes new outputs and restores files replaced by `--overwrite`, leaving a clean retry. A target created by another writer during commit is preserved rather than replaced. If the filesystem also refuses a backup restore, the backup is preserved and the error names both the backup and intended destination for manual recovery. Cleanup failures never replace the original transaction error or turn already-installed outputs into a reported failure. The console lists every generated transaction with its source row, date, normalized action, mapped security, and amount before reporting file count, transaction count, and total amount.

Generated QIF files begin with `!Type:Invst` and deliberately contain no embedded `!Account` block. Choose the destination investment account during import. This prevents the import from targeting the configured account name and creating an unwanted aggregate transfer. Vanguard withdrawal rows still produce their explicit per-row `XOut` transactions; no synthetic total or balancing transaction is generated.

All output paths are planned invocation-wide before staging. An output may never resolve to any input path, even with `--overwrite`, and two inputs may not resolve to the same output. This protects source exports from accidental replacement.

## Exact public CSV contracts

Leading blank CSV records are ignored before contract detection. Headers are compared after trimming surrounding whitespace, but otherwise must match exactly. Extra declared columns are permitted; every listed required column for one variant must be present. A data row with more or fewer cells than its declared header is rejected.

Fidelity supports both the account-column variant:

```text
Account,Run Date,Action,Symbol,Description,Quantity,Price ($),Commission ($),Fees ($),Accrued Interest ($),Amount ($),Settlement Date
```

and Fidelity's single-account History export:

```text
Run Date,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date
```

History exports do not declare their account in the CSV. For that variant, `brokerages.fidelity.accounts` must contain exactly one mapping; the converter uses that sole source account and refuses to guess when multiple mappings exist. Fidelity's blank-record-separated, single-cell notice trailer is ignored after all tabular rows have been validated. The cooked CSV preserves the Fidelity header and every ledger row, normalizes `Run Date` to `M/D/YY`, and renders integral `Quantity` values without a decimal fraction, matching the earlier Actual-import contract.

Supported Fidelity actions:

- `DIVIDEND RECEIVED` (case-insensitive, with an optional detail suffix) → normalized `dividend`, rendered as QIF `MiscInc` with memo `Dividend <source symbol/security>`

`REINVESTMENT` (also with an optional detail suffix) is skipped with a visible warning and does not require a mapping.

Vanguard required headers, in the usual export order:

```text
Account Number,Trade Date,Settlement Date,Transaction Type,Transaction Description,Investment Name,Symbol,Shares,Share Price,Principal Amount,Commissions and Fees,Net Amount
```

Supported Vanguard actions:

- `Dividend` → normalized `dividend`, rendered as QIF `MiscInc` with memo `Dividend <source symbol/security>`
- `Withdrawal` → normalized `withdrawal`, rendered as QIF `XOut` with a transfer target, a fixed locally configured cash security, and the transaction description as its memo (`Withdrawal` when the description is blank)

`Reinvestment` and `Sweep out` are skipped with visible warnings and do not require mappings.

The Vanguard cooked CSV preserves the Vanguard header and every recognized source row unchanged, including reinvestment and sweep rows that are intentionally omitted from QIF output.

The two contracts are registered as separate adapters. Each adapter owns its required headers, allowed source actions, and raw-row extraction. Shared code owns configuration validation, batch cooking, rendering, and the all-artifact output transaction.

Blank rows are ignored. Dates may use ISO `YYYY-MM-DD` or Fidelity's `MM/DD/YYYY`; both are normalized before rendering in Moneydance form `M/D'YY`. Amounts use strict financial-number syntax: optional leading sign and dollar sign, correctly grouped thousands commas, decimal fraction, or surrounding parentheses for a negative amount. Forms such as `-$1,234.56`, `$-1,234.56`, and `($1,234.56)` are accepted; misplaced currency signs or malformed comma grouping are rejected instead of being stripped. Amounts must be finite and are bounded to 100 significant digits and 100 integer digits so formatting cannot allocate unbounded output or fail during rendering. Every processed source account and dividend security must have an exact local mapping. Unsupported actions and unmapped values stop the whole batch before outputs are written.

Generated QIF fields reject CR, LF, and other control characters instead of allowing record injection. Text written to cooked CSV also rejects values whose first non-space character is `=`, `+`, `-`, or `@`, because spreadsheet applications may interpret those values as formulas. Rename an unsafe source filename or change the named local mapping and retry; the launcher does not silently rewrite identifiers.

## Configuration contract

`schema_version` must be `1`. Each registered brokerage section contains four mapping objects:

- `accounts`: source account value → local normalized account name; source keys validate account-bearing exports and identify account-less Fidelity History exports
- `securities`: source `Symbol` (or investment/description fallback) → QIF security name; Vanguard also reserves `@withdrawal` for the fixed QIF cash security used by every withdrawal
- `categories`: normalized action → QIF category; `dividend` is required for both brokerages
- `transfers`: normalized action → QIF transfer account; `withdrawal` is required only for Vanguard

All four mapping objects must be present. `accounts` and `securities` must be non-empty for a selected brokerage. Fidelity may use an empty `transfers` object because its supported action does not use transfers. Vanguard requires both `securities.@withdrawal` and `transfers.withdrawal`; the reserved security value is deliberately distinct from dividend source-security mappings. No reinvestment mapping is required. Unknown top-level keys, unregistered brokerage sections, and unknown keys inside registered sections are preserved when the program backfills a missing registered section.

Cooked CSVs retain the selected brokerage's declared headers rather than using a combined normalized schema. Generated files are operational local data and must not be committed.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -v
```
