# Moneydance JSON → CSV Converter

Convert a Moneydance JSON export into a flat CSV for reconciliation or import
into another accounting tool. The converter reconstructs hierarchical account
names, labels known account types, and expands transaction split fields into
CSV rows.

## Requirements

The converter uses only the Python standard library. It expects a Moneydance
export whose top-level object contains an `all_items` array with `acct` and
`txn` objects.

Use the included setup script to create a local virtual environment:

```bash
./setup.sh
source venv/bin/activate
```

No packages need to be installed after activation.

## Usage

```bash
python md_converter.py --input <your-moneydance-export.json> --output <your-desired-output.csv>
```

Run the command from the `md-json` directory. Both options are optional:

- `--input` defaults to `md-all-data.json`.
- `--output` defaults to `output_with_types_v4.csv`.

For example:

```bash
python md_converter.py
python md_converter.py --input my_export.json --output transactions.csv
```

The output file is replaced if it already exists. A missing or invalid input
file, or an unwritable output path, is reported on standard output.

## How It Works

1. Loads `all_items` from the Moneydance JSON.
2. Builds an account map from objects whose `obj_type` is `acct`, following
   `parentid` links to reconstruct names such as `Assets:Checking`.
3. Removes the leading `My Finances:` prefix from descendant account names.
4. Maps known account type codes to labels such as `BANK`, `CREDIT_CARD`,
   `EXPENSE`, and `INCOME`. Unknown codes are written as
   `UNKNOWN_CODE_<code>`.
5. Processes objects whose `obj_type` is `txn`. Transactions with an unknown
   main account or no valid splits are omitted.
6. Expands the numbered split fields:
   - A transaction with one valid split produces two rows: one from the main
     account's perspective and one counter-entry from the split account's
     perspective.
   - A transaction with multiple valid splits produces one row per split from
     the main account's perspective. These rows have a blank `Check#`.
7. Converts integer cent amounts to strings such as `$123.45` or `-$123.45`.
8. Sorts rows by account, date, and the original Moneydance `ts` value before
   writing the CSV. The timestamp is used only for ordering and is not exported.

## Output Columns

The CSV contains these columns:

| Column | Contents |
| --- | --- |
| `Account` | Account name for the row |
| `Date` | Moneydance `dt` converted from `YYYYMMDD` to `MM/DD/YYYY`; blank if invalid |
| `Check#` | Transaction check number; blank for multi-split rows |
| `Description` | Transaction description with commas removed |
| `Memo` | Split memo when present, otherwise the transaction memo, with commas removed |
| `Category` | Other account associated with the split |
| `C` | Always blank |
| `Amount` | Split amount formatted as currency |
| `Account_Type` | Mapped type of `Account` |
| `Category_Type` | Mapped type of `Category` |

## Customization

The root prefix and account-type map are constants inside
`generate_csv_from_json()` in `md_converter.py`. Edit
`ROOT_ACCOUNT_PREFIX_TO_STRIP` if your root account has another name, or extend
`ACCOUNT_TYPE_CODE_MAP` for additional Moneydance type codes.
