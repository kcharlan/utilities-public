# div_conv

`div_conv` converts supported Fidelity and Vanguard activity CSV exports into an Actual-compatible “cooked” CSV and QIF investment transactions. It is a standalone, standard-library-only [uv](https://docs.astral.sh/uv/) launcher.

## Privacy and setup

Never put real account names, mappings, securities, categories, transfers, exports, or generated output in this public repository. Runtime configuration belongs at `~/.div_conv/config.json`. `DIV_CONV_HOME` may point to another runtime directory for controlled execution and tests.

On first processing run, the launcher atomically creates an intentionally incomplete configuration skeleton and stops. Fill it locally; there is no automatic migration from an older converter. [`config.example.json`](config.example.json) is synthetic documentation only and must not be used unchanged for real input.

The runtime directory and configuration are hardened to modes `0700` and `0600` on every processing run, including when they already exist. Symbolic links are rejected for both paths so the launcher never changes or reads a link target unexpectedly. Permission and file-type errors stop processing with an actionable error.

If a later version finds that an entire registered brokerage section is absent, it adds an empty section and prints a highly visible warning naming both the section and config path. Processing may continue for another, already configured brokerage. Selecting the backfilled brokerage stops with an actionable incomplete-configuration error.

## Usage

Install [uv](https://docs.astral.sh/uv/) first. From this directory, invoke the
executable launcher directly; no project environment or dependency-install step is
required:

```sh
./div_conv --help
./div_conv "$HOME/.div_conv/exports/export.csv"
./div_conv --brokerage fidelity "$HOME/.div_conv/exports/*.csv"
./div_conv --output-dir /path/to/private/output \
  /path/to/private/export-1.csv /path/to/private/export-2.csv
```

If the launcher is placed or linked on `PATH`, the same commands may use
`div_conv` instead of `./div_conv`.

Quote glob patterns when the launcher should expand them. A batch must contain one brokerage only. Without `--brokerage`, every header is checked against all registered adapters and an ambiguous union header is rejected. `--brokerage` checks only the selected adapter’s contract, so it can intentionally resolve such ambiguity while still rejecting files that do not contain that adapter’s required headers. Files are fully validated before any output is committed.

Each input produces `<input-stem>.cooked.csv` and `<input-stem>.qif`. Existing regular-file output is refused unless `--overwrite` is supplied; directories, special files, and symbolic links are never valid output targets. Every artifact for the invocation is staged and synced before commit, then installed only if its target name is still unclaimed. A failed stage or commit removes new outputs and restores files replaced by `--overwrite`, leaving a clean retry. A target created by another writer during commit is preserved rather than replaced. If the filesystem also refuses a backup restore, the backup is preserved and the error names both the backup and intended destination for manual recovery. Cleanup failures never replace the original transaction error or turn already-installed outputs into a reported failure.

The default console report shows one row per generated transaction, using its date, amount, and original source symbol (trimmed of surrounding whitespace). A blank symbol displays `-`; the existing QIF security mapping and memo fallbacks do not replace that display symbol. For example, this entirely synthetic input produces:

```text
Transactions:

synthetic-export.csv — Dividends, oldest first
Date            Amount  Symbol
2030-01-03      125.00  SYNTH1
2030-01-04       80.00  SYNTH2
2030-01-05       42.50  SYNTH3
2030-01-06       17.25  SYNTH4
Total           264.75
Copy/paste sum:
125.00+80.00+42.50+17.25
```

Each input filename appears once. Within that file, transactions are grouped by source account and action, with groups in first-appearance order. Each group is sorted oldest first, preserving source order for equal dates. Files with multiple source accounts include the mapped account name in each group heading; source account labels disambiguate accounts that map to the same name. Every transaction remains a separate row, even when its date or symbol matches another row. This display sorting does not change the original transaction order in either cooked CSV or QIF.

Dates occupy a 10-character column, followed by two spaces and right-aligned amounts, then two spaces and the symbol. Amounts have exactly two decimal places; their shared column width is at least 10 characters and expands across the entire invocation when needed. Each group's total and bare copy/paste expression use those same displayed cent amounts. The expression occupies its own line after `Copy/paste sum:` and joins signed amounts with `+`, for example `10.00+-2.50+0.00`. Fractional-cent amounts are rounded individually using the same formatting as QIF, so group totals, expressions, and the final batch total reconcile with QIF amounts. Raw source amounts and cooked CSV amounts retain their existing behavior.

The complete report is checked before any output is staged and printed only after the output transaction commits successfully. It is followed by the existing `Wrote <path>` lines for both artifacts and the final file count, transaction count, and total amount. An input with no generated transactions shows `none` and has no copy/paste expression.

Generated QIF files with at least one transaction begin with `!Type:Invst` and deliberately contain no embedded `!Account` block. An input containing only headers or skipped actions produces an empty QIF file alongside its cooked CSV. Choose the destination investment account during import. This prevents the import from targeting the configured account name and creating an unwanted aggregate transfer. Vanguard withdrawal rows still produce their explicit per-row `XOut` transactions; no synthetic total or balancing transaction is generated.

All output paths are planned invocation-wide before staging. An output may never resolve to any input path, even with `--overwrite`, and two inputs may not resolve to the same output. This protects source exports from accidental replacement.

## Exact public CSV contracts

Contract detection searches nonblank CSV records for a registered transaction-table header. Headers are compared after trimming surrounding whitespace, but otherwise must match exactly. Extra declared columns are permitted; every listed required column for one variant must be present. A file containing more than one matching transaction table is rejected rather than partially converted. A data row with more or fewer cells than its selected declared header is rejected.

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

A Vanguard download may contain blank-record-separated holdings, investment-transaction, and account-activity tables in one CSV. The converter locates the one unique investment-transaction table shown above, ignores the surrounding Vanguard tables, and uses only the selected table for cooked CSV and QIF output. Extra columns declared by that transaction table are preserved. Unexpected rows within the selected table still receive the normal width, action, date, amount, and output-safety validation; only a recognized Vanguard surrounding-section header after a blank separator ends transaction parsing.

Supported Vanguard actions:

- `Dividend` → normalized `dividend`, rendered as QIF `MiscInc` with memo `Dividend <source symbol/security>`
- `Withdrawal` → normalized `withdrawal`, rendered as QIF `XOut` with a transfer target, a fixed locally configured cash security, and the transaction description as its memo (`Withdrawal` when the description is blank)

`Reinvestment` and `Sweep out` are skipped with visible warnings and do not require mappings.

The Vanguard cooked CSV preserves the Vanguard header and every recognized source row unchanged, including reinvestment and sweep rows that are intentionally omitted from QIF output.

The two contracts are registered as separate adapters. Each adapter owns its required headers, allowed source actions, and raw-row extraction. Shared code owns configuration validation, batch cooking, rendering, and the all-artifact output transaction.

Blank rows within the selected transaction table are ignored, except that a blank followed by a recognized Vanguard surrounding-section header marks the end of an embedded transaction table. Dates may use ISO `YYYY-MM-DD` or Fidelity's `MM/DD/YYYY`; both are normalized before rendering in Moneydance form `M/D'YY`. Amounts use strict financial-number syntax: optional leading sign and dollar sign, correctly grouped thousands commas, decimal fraction, or surrounding parentheses for a negative amount. Forms such as `-$1,234.56`, `$-1,234.56`, and `($1,234.56)` are accepted; misplaced currency signs or malformed comma grouping are rejected instead of being stripped. Amounts must be finite and are bounded to 100 significant digits and 100 integer digits so formatting cannot allocate unbounded output or fail during rendering. Every processed source account and dividend security must have an exact local mapping. Unsupported actions and unmapped values stop the whole batch before outputs are written.

Generated QIF fields reject CR, LF, and other control characters instead of allowing record injection. Non-numeric, non-date fields written to cooked CSV also reject values whose first non-space character is `=`, `+`, `-`, or `@`, because spreadsheet applications may interpret those values as formulas. Numeric and date columns are exempt so legitimate signed values and dates remain valid; the transaction date and amount are parsed strictly, while other numeric/date source columns pass through unchanged (apart from Fidelity's date and integral-quantity normalization described above). Rename an unsafe source filename, correct an unsafe source value, or change the named local mapping and retry; the launcher does not silently rewrite identifiers.

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
