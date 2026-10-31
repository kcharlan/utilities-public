# EditDB

EditDB is a local, browser-based SQLite editor. A single uv-managed Python
launcher serves a FastAPI backend and an embedded Preact interface.

## Quick start

Install [uv](https://docs.astral.sh/uv/) and run the launcher from this
directory:

```zsh
./editdb data.sqlite
```

The database file and missing parent directories are created if necessary.
The server binds to `127.0.0.1:8000` and opens the default browser. Use a
different port with:

```zsh
./editdb data.sqlite --port 9000
```

To invoke EditDB from elsewhere, symlink `editdb/editdb` into a directory on
your `PATH`.

The first invocation may access the network while uv resolves a compatible
Python 3.12 through 3.15 interpreter and the dependencies declared in the launcher's PEP
723 header. The browser UI embeds its assets and works offline after the
launcher dependencies have been resolved.

## Features

- Browse tables in a grid with a fixed 100-row page size.
- Filter the rows currently loaded on the active page.
- Add, edit, and delete rows. Updates and deletes require a primary key.
- Create, rename, clone, and delete tables.
- Inspect foreign keys, hover for related-row previews, and follow
  relationships in a drawer.
- Add, rename, delete, or change the declared type of columns with the schema
  editor.
- Run one raw SQLite statement at a time in the SQL console. Successful
  statements are stored in browser-local query history.
- List, create, edit through the SQL console, and delete indexes. If a
  database has no indexes yet, create the first one in the SQL console because
  the index controls are only rendered after an index exists.
- Export all rows from a table as CSV or JSON, export its `CREATE TABLE`
  statement, and import UTF-8 CSV files up to 50 MB.
- Switch between light and dark themes; the preference is stored in
  `localStorage`.

See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for detailed operation and
current limitations.

## Important schema-editor limitation

Back up the database before applying schema-editor changes. The current
shadow-table migration rebuilds columns from their names and one of four
declared types (`TEXT`, `INTEGER`, `REAL`, or `BLOB`). It does **not** preserve
primary keys, `AUTOINCREMENT`, `NOT NULL`, default values, unique or check
constraints, foreign-key declarations, indexes, or triggers.

The rebuild and data copy are transactional, and source-column mappings are
validated, but those safeguards do not preserve omitted schema objects. Use
the SQL console or another SQLite migration tool when those objects matter.

## Security and limits

- The server listens only on `127.0.0.1`; it has no authentication and is not
  intended to be exposed through a proxy or network listener.
- Identifiers used by the generated table, index, row, and import operations
  must match `[A-Za-z_][A-Za-z0-9_]*` and are quoted before use.
- The SQL console intentionally executes the submitted statement directly. It
  is for trusted local use and is not restricted to read-only SQL.
- SQL requests are limited to 100 KB and query results to 10,000 rows.
- CSV uploads are limited to 50 MB.
- Table APIs accept at most 1,000 rows per request; the UI requests 100.
- SQLite connections use 30-second connection and busy timeouts.

CSV imports commit every 1,000 rows. If a later batch fails, rows from earlier
committed batches remain in the database.

The grid only recognizes the first component of a composite primary key when
locating rows. Use the SQL console or another SQLite client to update or delete
rows in tables with composite primary keys.

## Architecture

The executable [`editdb`](editdb) contains:

- the uv shebang and dependency metadata;
- the FastAPI application and SQLite operations;
- the CLI and server lifecycle; and
- the complete Preact interface and styles in `HTML_TEMPLATE`.

The frontend has no local build step or `node_modules`. The launcher opens the
browser automatically unless `UTILITIES_TESTING` is set to a truthy value.

The frontend embeds Preact, HTM, its icons and the Inter font. Its CSS is
included in the launcher and dark mode uses a class on the document.

`editdb_setup.sh` is a compatibility notice for the obsolete pre-uv workflow.
It creates no environment or dependencies; it verifies the current launcher
can resolve through uv and prints the direct run command. New installs should
run `editdb` directly. The compatibility script no longer references the
retired `src/editdb.py` layout.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- A modern browser

The automated browser suite covers the current Playwright Chromium; Safari and
Firefox are not covered by the automated browser test.

No manual runtime virtual environment or global `pip` installation is needed.

## Tests

From the repository root, run both test invocations through the shared runner:

```zsh
UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py editdb
```

If Chromium is missing, install it once with `UV_PYTHON_DOWNLOADS=never tools/run_project_tests.py editdb --install-browsers`.

Run the browser smoke separately because Playwright's synchronous event loop
conflicts with the unit suite's `asyncio.run()`-based ASGI test client when
both are collected in one process. It checks offline assets, custom and dark
styles, theme persistence, editing, and page/console cleanliness in Chromium.
