# Tax2 Usage Guide

## Installation

No installation required. Simply run the executable:

```bash
./tax2
```

## Basic Usage

### Launch the Application
```bash
./tax2
```

This will:
1. Start the web server on port 8000
2. Automatically open your browser
3. Display the tax calculator interface

### Command-Line Options

**Custom Port**:
```bash
./tax2 --port 9000
```

**Disable Auto-Browser**:
```bash
./tax2 --no-browser
```

**Custom Rules Directory**:
```bash
./tax2 /path/to/custom/rules
```

## Features

### Tax Calculation Modes

1. **Rules Engine** (default)
   - Computes taxes directly from YAML rule files
   - Always uses the latest logic
   - Handles earned vs unearned income and component scoping
   - Ideal for testing rule changes

2. **Lookup Table**
   - Fast pre-computed results
   - Requires table generation first
   - Good for production use
   - Assumes all income is unearned; use rules mode when PA local EIT or another earned-only component is enabled

### Income and State Selection

Enter monthly unearned income and monthly earned income separately. Federal tax is computed once on the combined total. Each selected state computes on its own allocated share of the entered income.

Allocation percentages are independent. Setting GA to 100% and PA to 100% computes full state tax for both states. The app does not normalize percentages or require them to sum to 100.

### Generating Tables

Use the CLI:

```bash
.venv/bin/python cli.py generate-combined --year 2026 --states GA,PA
```

Outputs include one federal parquet, one state parquet per requested state, one `combined_YYYY_STATE.csv` per state, and `combined_YYYY.csv` as a legacy alias for the configured default state.

### QIF Export

1. Enter your income and select filing status
2. Review calculated taxes
3. Configure QIF settings in right panel:
   - Transaction date
   - Payee name
   - Account categories
4. Click "Download QIF"
5. Import into Quicken or Moneydance

The QIF bundle contains two federal transactions plus two transactions for each selected state. State expense and transfer defaults come from each state's YAML `qif` block and can be overridden in the UI.

## Customization

### Adding New Tax Years

1. Create YAML files:
   - `rules/federal/2026.yaml`
   - `rules/states/GA/2026.yaml`

2. Restart the application

3. New year appears in dropdown

### Adding New States

1. Create directory: `rules/states/TX/`
2. Add YAML file: `rules/states/TX/2025.yaml`
3. Restart application

The app discovers state directories automatically. A v2 state file may define multiple tax components:

```yaml
components:
  - name: state_income_tax
    enabled: true
    applies_to: [earned, unearned]
    standard_deduction: { single: 0, married_joint: 0 }
    brackets:
      single: [ { up_to: null, rate: 0.0307 } ]
      married_joint: [ { up_to: null, rate: 0.0307 } ]
```

Keep component names generic. Put locality-specific details in `label` and bracket data.

## Pennsylvania Notes

- PA personal income tax is modeled as a flat 3.07% with no standard deduction.
- Qualified and ordinary dividends are treated the same for PA in this tool.
- Return of capital is excluded from entered income until basis is exhausted; after that, enter it as gain.
- The PA local EIT component in `rules/states/PA/2026.yaml` is disabled by default and applies only to earned income. To use it, verify the local rate, edit the component rate if needed, and set `enabled: true`.
- PA estimated-payment thresholds and due-date mechanics are not enforced by the calculator.

## Runtime Config

The app stores preferences in `~/.tax2/config.yaml`, or `$TAX2_HOME/config.yaml` when `TAX2_HOME` is set. The config stores default states, the legacy combined-table alias state, and optional QIF account overrides. It never stores tax rates.

## Troubleshooting

**Port already in use**:
```bash
./tax2 --port 9000
```

**Dependencies not installing**:
```bash
rm -rf ~/.tax2
./tax2  # Will recreate and reinstall
```

**Calculation seems wrong**:
- Check YAML rules for typos
- Verify year is correct
- Try switching between rules/table mode
- Compare with previous year's rules
