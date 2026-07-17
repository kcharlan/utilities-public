# Expense Dock

Expense Dock is a uv-managed local web app for logging business expenses through a OneDrive-based workflow. It replaces the manual copy-paste cycle of filling out a spreadsheet and uploading receipts with a single submit action: fill in the expense details, attach the receipt, and Expense Dock handles the rest.

## What It Does

When you submit an expense, Expense Dock:

1. Renames the receipt file to a standardized format (`YYYY-MM-DD_Vendor_Amount_Purpose.ext`)
2. Uploads the receipt to OneDrive under `Business Expenses/YYYY/YYYY-MM/`, creating year and month folders as needed
3. Generates an anonymous read-only share link for the uploaded receipt
4. Downloads the expense tracking workbook from OneDrive, appends a new row with all the expense details and the receipt link, then uploads it back
5. If the receipt upload succeeds but the workbook write fails, the expense is queued for retry

The result is a populated expense spreadsheet on OneDrive with clickable receipt links, requiring no manual file management.

## Workbook Layout

The expense workbook is an Excel file with five worksheets. A schema template is included at [`docs/Expense_Tracker_Template.xlsx`](docs/Expense_Tracker_Template.xlsx) with conspicuously synthetic lookup placeholders and its formatting/formulas pre-configured. Copy it to private storage and replace every `SYNTHETIC` placeholder before use; never enter operational expenses into the tracked repository copy.

**Expense Log** -- the main data table. Each row is one expense with columns for ID, Date, Vendor, Amount, Category, Business Purpose, Paid By, Payment Method, Reimbursable flag, Reimbursement Status, Receipt Link, Receipt Filename, and Notes. Filters are enabled on the header row. Expense Dock appends new rows here automatically.

**Categories** -- lookup values that drive the dropdowns in the app and in the Entry Form worksheet. Four columns: Categories, Payment Methods, Paid By (people/entities), and Reimbursement Status. The tracked values are intentionally unusable `SYNTHETIC` placeholders; replace them only in your private operational copy.

**Summary** -- auto-calculated totals and a category-by-category spending breakdown. All formulas reference the Expense Log, so this stays current as rows are added.

**Entry Form** -- a manual data-entry form for use when working directly in Excel (without the Expense Dock app). Fill in the yellow input cells, then copy the green "Ready to Copy" row into the Expense Log. See the form for step-by-step instructions.

**Guidelines** -- detailed setup and usage documentation covering OneDrive folder structure, receipt naming conventions, how to use the Entry Form, and how to customize the tracker. Read this worksheet first if you are setting up the system for the first time or onboarding someone new.

## Quick Start

Run the entrypoint directly:

```zsh
./expense_dock
```

Or symlink it into your `PATH`:

```zsh
ln -s "$(pwd)/expense_dock" /usr/local/bin/expense_dock
expense_dock
```

Expense Dock runs via [uv](https://docs.astral.sh/uv/) (`brew install uv`) using a PEP 723 inline-metadata header. On first run it creates its runtime home at `~/.expense_dock/` and writes a default `config.json`; uv resolves the dependencies (fastapi, uvicorn[standard], python-multipart, httpx, msal, openpyxl) into its shared cache — that first invocation may briefly hit the network. No manual `pip install` and no virtual environment in your home directory are required.

## App Interface

The UI is an embedded React SPA served by a localhost-only FastAPI backend, organized into workspace views:

- **Submit** -- the main intake form for logging an expense and attaching a receipt
- **Setup** -- OneDrive and workbook configuration, Microsoft auth, and default values
- **Queue** -- retry items when a workbook upload needs another push
- **Lookups** -- cached dropdown values pulled from the Categories worksheet

A persistent bottom status bar shows live state for configuration readiness, Microsoft auth, workbook lookups, and retry queue health.

## Microsoft Setup

Create a Microsoft Entra app registration for a public client:

1. Supported account types: `Personal Microsoft accounts only`
2. Platform: `Mobile and desktop applications`
3. Redirect URI: `http://localhost`

Then paste the app's client ID into the Expense Dock Setup panel.

The app uses the delegated Microsoft Graph permission `Files.ReadWrite.All`. During interactive login, MSAL also requests the standard OpenID/offline scopes for sign-in and token refresh.

## Workbook Configuration

Expense Dock expects the workbook to follow the layout in the template ([`docs/Expense_Tracker_Template.xlsx`](docs/Expense_Tracker_Template.xlsx)):

- Expense worksheet named `Expense Log` with this header row. The template uses row 1, but Expense Dock will also tolerate a title/blank row above it and locate the header within the first 25 rows:

  ```
  ID, Date, Vendor, Amount, Category, Business Purpose, Paid By,
  Payment Method, Reimbursable?, Reimb. Status, Receipt Link,
  Receipt Filename, Notes
  ```

- Lookup worksheet named `Categories` with four columns: Categories (A), Payment Methods (B), Paid By (C), Reimbursement Status (D)

The workbook file should be located at the shared OneDrive root (e.g. `Business Expenses/Expense_Tracker.xlsx`). Configure the exact filename and path in the Setup panel.

## Runtime State

State files live under `~/.expense_dock/`:

- `config.json` -- saved app config and UI defaults
- `token_cache.json` -- Microsoft auth token cache
- `pending/*.json` -- queued retry records for workbook append failures
- `last_port` -- most recent port used

The runtime directory and `pending/` are enforced as mode `0700`; configuration, token cache, queue records, and other runtime files are atomically written or hardened to mode `0600`. Symlinked sensitive runtime paths are refused.

## Operational Notes

- Receipt filenames are normalized to `YYYY-MM-DD_Vendor_Amount_ShortPurpose.ext`
- If the normalized receipt filename already exists in the target month folder, Expense Dock reuses it instead of uploading again
- If the workbook already contains the same receipt link or receipt filename, the submission is treated as already logged (no duplicate row)
- Large files use a resumable upload session; small files use a direct upload
- OneDrive operations target resolved shared-drive item IDs, not a local OneDrive sync folder
- Help and instructions are available in the in-app Help modal
- Action results appear as toast notifications; failures with a CSV fallback expose that directly in the toast and retry queue

## Validation

Create the tracked test environment and run the full suite:

```zsh
cd /Users/example/source/utilities/expense_dock
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Runtime smoke checks:

```zsh
./expense_dock --help
./expense_dock --no-browser --port 8420
```
