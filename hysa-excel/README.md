# HYSA vs CD Excel Generator

Creates a formula-driven, four-sheet Excel workbook comparing a high-yield savings account (HYSA) with rolling certificate-of-deposit (CD) maturities.

Operational financial inputs are private local data. They are never stored in this public repository. By default, the generator reads `~/.hysa-excel/inputs.csv` and writes `~/.hysa-excel/CD_vs_HYSA_Model.xlsx`. Set `HYSA_EXCEL_HOME` to choose a different runtime directory.

The launcher keeps its runtime directory private (`0700`) and its input CSV and generated workbook owner-only (`0600`). It repairs more-permissive modes on existing files before use and refuses symbolic links at these sensitive path endpoints rather than changing or writing through their targets.

## Requirements

Install [uv](https://docs.astral.sh/uv/) once (`brew install uv`). The launcher requests Python 3.12 or newer and declares its own `xlsxwriter` dependency; uv resolves both automatically. There is no setup script or project virtual environment.

## First Run

Run the launcher directly:

```bash
./hysa_vs_cd_model.py
```

If the local input file does not exist, the launcher atomically creates an intentionally incomplete template at `~/.hysa-excel/inputs.csv`, prints a prominent `CONFIGURATION REQUIRED` message, and exits without creating a workbook. Fill in every value and run it again.

The launcher does not inspect, copy, or migrate an `inputs.csv` beside the source file. This prevents local financial data from becoming coupled to a public checkout.

`inputs.example.csv` is a documentation-only schema example whose values are literally all zero. It is intentionally invalid because cadence and duration must be positive; it cannot silently generate a plausible financial model. Do not replace it with operational values.

## Paths and Scenarios

Use explicit paths for one-off scenarios or outputs:

```bash
./hysa_vs_cd_model.py \
  --inputs /path/to/private/scenario.csv \
  --output /path/to/private/comparison.xlsx
```

The options are independent: if only one is supplied, the omitted path still uses the runtime-directory default. Run `./hysa_vs_cd_model.py --help` for the command reference.

The parent directory for an explicit output is created only after input validation succeeds. A missing explicit input path receives the same incomplete-template treatment and never triggers workbook generation.

The CSV header must contain exactly these columns, in this order:

```csv
Parameter,Value
```

Required parameters are:

- `Initial Principal`
- `Starting HYSA Rate`
- `Starting CD Rate`
- `Rate Step (per period)`
- `Rate Change Frequency (months)`
- `CD Sensitivity`
- `Total Duration (months)`

Numeric values may use ordinary number syntax or a trailing percent sign, which divides the value by 100 (`5%` is `0.05`). Use whole-number syntax for rate-change frequency and total duration. For `CD Sensitivity`, `1` or `100%` means the CD rate moves by the full configured rate step.

Validation errors identify missing, duplicate, blank, malformed, or out-of-range values before any output is written. The accepted ranges are:

- Initial principal: `0` through `1e100`.
- Starting HYSA and CD rates: `0` through `1` (`0%` through `100%`).
- Rate step per period: `-1` through `1`.
- Rate-change frequency: a positive whole number of months.
- CD sensitivity: `0` through `100`.
- Total duration: `1` through `1200` whole months.
- The maximum HYSA and CD annual rates projected over the complete cadence and duration must not exceed `100%`.
- A conservative maximum compounded balance must remain below `1e200`.

The upper bounds are technical overflow guards, not recommended financial assumptions. Inputs outside a limit are rejected before an output directory or workbook is created. The input and output paths must also be different.

## Workbook

The generated workbook contains:

- **Inputs** — the validated local inputs used for the run.
- **Monthly Balances** — formula-driven monthly HYSA and rolling CD balances for 3, 6, 12, 18, 24, 36, and 60-month terms.
- **Simple** — a small workspace for manual comparisons.
- **Output** — final balances and a formula-driven best-performer marker.

Rates step at the configured cadence and floor at zero. CD rates update on rollover and scale rate changes by `CD Sensitivity`. All balance calculations remain Excel formulas so the workbook can be audited and adjusted.

`Total Duration (months)` means the exact number of monthly compounding periods. Month 1 shows principal after Month 1 interest, each following row compounds once from the previous row, and the Output sheet points to the post-month-N balance.

The workbook is first built as a temporary file in the output directory and then moved into place, so an existing output is not modified in place while formulas are being generated.

## Development

Run the isolated project suite from the repository root:

```bash
uv run --with-requirements hysa-excel/requirements-dev.txt pytest hysa-excel/tests -v
uv run --script tools/check_uv_headers.py
```

Tests use temporary runtime directories and synthetic values; they never read or write `~/.hysa-excel`.
