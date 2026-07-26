# EditDB

EditDB is a local, browser-based SQLite editor. A single uv-managed Python
launcher serves a FastAPI backend and an embedded React interface.

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
Python 3.12+ interpreter and the dependencies declared in the launcher's PEP
723 header. The browser UI also loads React, Tailwind CSS, Babel, Lucide, and
Inter from CDNs, so those resources must be available when they are not
already cached.

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
- the complete React/Tailwind interface in `HTML_TEMPLATE`.

The frontend has no local build step or `node_modules`. The launcher opens the
browser automatically unless `UTILITIES_TESTING` is set to a truthy value.

`editdb_setup.sh` is an obsolete pre-uv setup script and should not be used; it
references the retired `src/editdb.py` layout. It remains only as a legacy
artifact.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- A modern browser with access to the UI's CDN dependencies

No manual runtime virtual environment or global `pip` installation is needed.

## Tests

Development tests use a project-local virtual environment:

```zsh
cd editdb
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
