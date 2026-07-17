# EditDB: World-Class SQLite Management

EditDB is a professional-grade, local web-based utility for managing SQLite databases. It combines the power of a Python backend with a high-performance, modern React-based frontend to deliver a "desktop-class" experience in your browser.

## Quick Start (Global Utility)

EditDB runs via [uv](https://docs.astral.sh/uv/) (`brew install uv`) using a PEP 723 inline-metadata header. You don't need to manage virtual environments manually.

1. **Make it Global (Optional):**
   Link the script to your local bin to run it from anywhere:
   ```zsh
   ln -s "$(pwd)/editdb" /usr/local/bin/editdb
   ```

2. **Run:** Just launch it. The first run resolves its dependencies (fastapi, uvicorn, python-multipart, pydantic) into uv's shared cache — that invocation may briefly hit the network; later runs are fast.
   ```zsh
   editdb data.sqlite
   ```

3. **Options:**
   ```
   editdb <path_to_db> [-p <port>]
   ```
   - `<path_to_db>` -- path to the SQLite file (created if it doesn't exist)
   - `-p`, `--port` -- port for the local server (default: 8000)

## Homebrew & PEP 668 Friendly
Because macOS and Homebrew prevent global `pip` installs, uv resolves EditDB's dependencies into its managed shared cache. This ensures:
- No "Externally Managed Environment" errors.
- No interference with your system Python.
- A "just works" experience like a Homebrew-installed binary.

## Key Features

- **Airtable-Style Data Grid:** A high-performance grid with sticky headers and intuitive row editing. Paginated with configurable page size (default 100, max 1000 rows per page).
- **Advanced Schema Designer:** Add, rename, or delete columns and change data types. EditDB handles complex SQLite migrations (shadow-table pattern) automatically with transaction safety and mapping validation.
- **SQL Console:** A dedicated space for running raw SQL queries with history tracking (stored in localStorage). Results capped at 10,000 rows.
- **Table Management:** Create, rename, and delete tables. View foreign key relationships.
- **Index Management:** Create and delete indexes with ease to optimize your query performance.
- **Data Import/Export:** Export tables as CSV or JSON. Export table schemas as SQL DDL. Import data from CSV files (up to 50 MB).
- **Row Operations:** Add, edit, and delete individual rows through the grid UI. Row preview on click.
- **CLI-First Workflow:** Pass a database path directly via the terminal to open it instantly.
- **Zero-Build Frontend:** The UI is delivered as a single-file SPA using CDN-based React and Tailwind CSS, meaning no `node_modules` or complex build steps for you.

## Security & Robustness

- **Localhost Only:** The server binds strictly to `127.0.0.1` to prevent unauthorized network access.
- **SQL Injection Protection:** All dynamic SQL identifiers (tables, columns, indexes) are validated against a strict pattern and properly quoted.
- **Safe Migrations:** Structure changes use a shadow-table migration pattern wrapped in transactions. Column mappings are validated before execution to prevent data corruption.
- **Resource Limits:** CSV import size cap (50 MB), query size cap (100 KB), query result truncation (10k rows), and SQLite connection timeouts (30 s).

## How It Works

### The Backend (FastAPI)
The backend is a lightweight Python server that provides:
- **REST API:** Endpoints for fetching schemas, rows, executing queries, managing tables/indexes, and import/export.
- **Shadow-Table Migrations:** Since SQLite's `ALTER TABLE` is limited, EditDB performs migrations by creating a temporary table, copying data, and swapping them -- all within a safe transaction.
- **Auto-Browser Launch:** Opens the default browser to the local server on startup.

### The Frontend (React + Tailwind)
The UI is built with:
- **React 18** and **ReactDOM 18** (CDN, no build step).
- **Tailwind CSS** for styling.
- **Babel Standalone** for in-browser JSX transpilation.
- **Lucide Icons** for interface elements.
- **Single-File Design:** The entire frontend is embedded in the Python script as `HTML_TEMPLATE`.

## Developer & Maintainer Notes

### Project Structure
- `editdb` -- The unified entry point (uv-managed via a PEP 723 header). Contains the FastAPI server, CLI harness, and the embedded HTML/React frontend.
- `editdb_setup.sh` -- Legacy setup script from before the uv-managed launcher. Not needed for normal use.
- `docs/` -- Contains audit and past-issues documentation for maintainers.

### Modifying the UI
The UI is embedded within the `HTML_TEMPLATE` constant in the `editdb` file. This allows the utility to remain a single-file tool for easy portability while still delivering a complex web interface.

### Safety & Transactions
All schema changes are wrapped in SQLite transactions. If a migration fails during the data-copying phase, the changes are rolled back automatically to prevent data loss.

## Requirements
- [uv](https://docs.astral.sh/uv/) (`brew install uv`) — manages the Python interpreter and dependencies
- Dependencies (`fastapi`, `uvicorn`, `python-multipart`, `pydantic`) resolved automatically by uv on first run
- A modern web browser

## Tests

```bash
cd /Users/example/source/utilities/editdb
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
