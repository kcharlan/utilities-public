# EditDB User Guide

A walkthrough for browsing, editing, and querying SQLite databases with EditDB.

---

## 1. Getting Started

### Launch

```bash
# Open an existing database
editdb mydata.sqlite

# Create a new database (file created automatically)
editdb new_project.db

# Custom port
editdb mydata.sqlite -p 9000
```

EditDB starts a local web server on `127.0.0.1` and opens your browser automatically. The default port is **8000**.

### First-Time Setup

On first run, EditDB creates a private virtual environment at `~/.editdb_venv` and installs its dependencies (FastAPI, uvicorn). This happens once — subsequent launches start instantly.

**Requirements:** Python 3.8+ and a modern web browser. An internet connection on first run for CDN resources (React, Tailwind, fonts).

### Security

EditDB binds strictly to `127.0.0.1` (localhost only) — it is not accessible from other machines on your network. All SQL identifiers are validated and parameterized to prevent injection.

---

## 2. The Interface

### Layout

| Area | Position | Purpose |
|------|----------|---------|
| **Sidebar** | Left | Database name, dark mode toggle, SQL Console link, table list, index list |
| **Content area** | Center | Data grid, schema editor, or SQL console (depends on current view) |
| **FK drawer** | Right (overlay) | Foreign key relationship navigation (opens on demand) |

### Sidebar

The sidebar shows:

| Section | Contents |
|---------|----------|
| **Header** | Database filename and dark mode toggle (sun/moon icon) |
| **SQL Console** | Link to open the raw query editor |
| **Tables** | List of all tables with a **+** button to create a new one |
| **Indexes** | List of all indexes (only shown if indexes exist) with a **+** button to create a new one |

**Table selection:** Click a table name to load it in the content area. The active table is highlighted with a blue left border.

### Dark / Light Mode

Click the sun/moon icon in the sidebar header. EditDB auto-detects your OS preference on first visit and saves your choice to localStorage. All colors transition smoothly.

### Empty State

If no tables exist, the content area shows a database icon with the message "Select a table or open SQL Console" — prompting you to create a table or write SQL.

---

## 3. Data Grid

Select a table in the sidebar to see its data. The **Data** tab is selected by default (toggle to **Schema** to see the structure editor).

### Table Display

An Airtable-style grid with sticky headers. Each column header shows:

| Indicator | Icon | Meaning |
|-----------|------|---------|
| **Primary key** | Key (amber) | This column is the primary key |
| **Foreign key** | Link (blue) | This column references another table |
| **Type** | Text label | Column type: TEXT, INTEGER, REAL, or BLOB |

### Column Values

| Display | Meaning |
|---------|---------|
| Normal text | Regular value |
| Italic "NULL" | NULL value |
| Blue hyperlink | Foreign key value — click to navigate to the related row |

### Toolbar

Above the grid, action buttons provide table-level operations:

| Button | Description |
|--------|-------------|
| **Clone** | Copies the table's schema as SQL into the SQL Console for review and execution |
| **Rename** | Rename the current table |
| **Refresh** | Re-fetch the table data |
| **Delete Table** | Drop the table (with confirmation) |

### Search / Filter

A search box above the grid filters rows in real time (case-insensitive, searches across all columns).

### Pagination

| Control | Description |
|---------|-------------|
| **Previous / Next** | Page navigation buttons (disabled at boundaries) |
| **Page indicator** | Shows "3 / 10" style page position |
| **Row range** | Shows "201–300 of 1,245 rows" |

Default page size is **100 rows** (maximum 1,000).

---

## 4. Editing Data

### Edit a Single Cell

**Double-click** any cell to enter edit mode. The cell becomes an input field.

| Action | How |
|--------|-----|
| **Save** | Press **Enter** or click away |
| **Cancel** | Press **Escape** |

Primary key columns are read-only and cannot be edited (shown with a grayed-out background).

### Edit an Entire Row

Click the **pencil icon** on the left side of a row to enter bulk edit mode. All non-primary-key fields become editable. Click the **check mark** to save all changes at once.

### Add a Row

Click the blue **Add Row** button above the grid. A new row is inserted with empty values for all non-primary-key columns.

### Delete a Row

Hover over a row to reveal the **trash icon** on the far right. Click it and confirm to delete the row.

---

## 5. Foreign Key Navigation

EditDB makes it easy to explore relationships between tables.

### FK Indicators

- Column headers with foreign keys show a blue **link icon** and a tooltip: "References {table}({column})"
- FK cell values appear as **blue hyperlinks**

### FK Tooltip (Hover Preview)

Hover over a foreign key cell for 400ms to see a tooltip with:
- The related table name
- The FK reference (e.g., `user_id = 5`)
- A preview of up to 6 columns from the related row

### FK Drawer (Click Navigation)

Click a foreign key hyperlink to open the **FK drawer** — a slide-in panel from the right side showing the related table.

| Feature | Description |
|---------|-------------|
| **Width** | ~55% of screen |
| **Header** | Related table name, FK reference, close button |
| **Breadcrumbs** | Navigation trail when drilling through multiple FK relationships — click any breadcrumb to jump back |
| **Highlighted row** | The target row pulses with a blue highlight and auto-scrolls into view |
| **Full table view** | The drawer shows the related table with all the same features: sticky headers, type indicators, FK links |
| **Stackable** | Click another FK link inside the drawer to drill deeper — breadcrumbs track the full path |

Close the drawer with the **X** button or press **Escape**.

---

## 6. Schema Editor

Click the **Schema** tab (next to **Data**) when viewing a table.

### Column Cards

Each column is shown as a card with:

| Field | Description |
|-------|-------------|
| **Name** | Editable text input for the column name |
| **Type** | Dropdown: TEXT, INTEGER, REAL, BLOB |
| **Delete** | Button to mark the column for deletion |

### Adding Columns

Click the **Add Column** button in the header. A new card appears with empty name and type fields.

### Deleting Columns

Click the delete button on a column card. The card turns red with reduced opacity and shows a **Restore** button — nothing is applied yet.

### Applying Changes

Click the green **Apply Changes** button. A confirmation dialog appears before the migration runs. EditDB uses a shadow-table migration pattern behind the scenes:

1. Creates a new table with the updated schema
2. Copies data from the old table (preserving values for renamed columns, discarding deleted columns)
3. Drops the old table and renames the new one
4. All wrapped in a transaction — if anything fails, it rolls back completely

---

## 7. SQL Console

Click **SQL Console** in the sidebar to open the raw query editor.

### Layout

| Area | Position | Purpose |
|------|----------|---------|
| **Query editor** | Left | Textarea for writing SQL |
| **History sidebar** | Right | Up to 50 recent queries (persisted in localStorage) |
| **Results** | Below | Query output in a scrollable table |

### Writing and Running Queries

Type any valid SQLite SQL into the editor and click **Run Query** (or use the keyboard).

| Query type | Result |
|------------|--------|
| **SELECT** | Results displayed in a table with sticky headers (limited to 10,000 rows) |
| **INSERT / UPDATE / DELETE** | Success message with affected row count |
| **DDL (CREATE, ALTER, DROP)** | Success message |
| **Errors** | Red banner with monospace error text |

### Query History

- The right sidebar stores up to **50 queries** in localStorage
- Click any history entry to load it into the editor
- **Clear History** button removes all entries
- History persists across sessions

### NULL Display

NULL values in query results appear as italic "NULL" text, consistent with the data grid.

---

## 8. Table Management

### Create a Table

Click the **+** button next to the "TABLES" header in the sidebar. Enter a name — the table is created with a single auto-increment primary key column (`id INTEGER PRIMARY KEY AUTOINCREMENT`).

### Rename a Table

With a table selected, click the **pencil icon** in the toolbar. Enter the new name.

### Clone a Table

Click the **Clone** button in the toolbar. The table's schema is loaded into the SQL Console as a `CREATE TABLE IF NOT EXISTS` statement with a suggested name. Review, edit, and click **Run Query** to create the clone.

### Delete a Table

Click the **Delete Table** button in the toolbar. Confirm the deletion. EditDB selects the next available table, or shows the empty state if none remain.

---

## 9. Index Management

The **Indexes** section in the sidebar appears only when indexes exist.

### View Indexes

Each index shows a **zap icon** (amber) and its name. Hover to see a tooltip with the table name and full SQL definition.

### Create an Index

Click the **+** button next to "INDEXES." Enter:
- Index name
- Columns (comma-separated)
- Whether it should be unique

### Edit an Index

Hover over an index and click the **edit button**. The index SQL is loaded into the SQL Console for manual editing — drop the old index and create the new one.

### Delete an Index

Hover over an index and click the **trash icon**.

---

## 10. Import and Export

Buttons above the data grid handle import and export:

### Export

| Format | Description |
|--------|-------------|
| **CSV** | Downloads all rows (not just the current page) as a CSV file |
| **JSON** | Downloads all rows as a JSON array |
| **SQL** | Exports the table schema as a `CREATE TABLE IF NOT EXISTS` DDL statement |

### Import

| Format | Description |
|--------|-------------|
| **CSV** | Upload a CSV file (up to **50 MB**) to import rows into the current table. Data is validated against the table schema. |

A success or error message appears after the import completes.

---

## 11. Quick Reference

### CLI Flags

```
editdb <path_to_db> [--port PORT]
```

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `<path_to_db>` | — | *(required)* | Path to SQLite database file (created if it doesn't exist) |
| `--port` | `-p` | 8000 | Server port |

### Keyboard Shortcuts

| Shortcut | Context | Action |
|----------|---------|--------|
| **Double-click** | Data grid cell | Enter edit mode |
| **Enter** | Cell edit | Save the edited value |
| **Escape** | Cell edit / FK drawer | Cancel edit or close drawer |

### Content Limits

| Limit | Value |
|-------|-------|
| CSV import size | 50 MB |
| SQL query size | 100 KB |
| Query result rows | 10,000 |
| Page size (max) | 1,000 rows |
| Query history | 50 entries |

### Color Legend

| Element | Color | Meaning |
|---------|-------|---------|
| Key icon | Amber | Primary key column |
| Link icon | Blue | Foreign key column |
| Zap icon | Amber | Index |
| Blue hyperlink | Blue | Foreign key value (clickable) |
| Blue left border | Blue | Selected / active table in sidebar |
| Blue highlight | Blue | Target row in FK drawer |
| Red card | Red | Column marked for deletion in schema editor |
| Italic "NULL" | Gray | NULL value |

### Fonts

| Font | Usage |
|------|-------|
| **Inter** | All UI text |
| **Monospace** | SQL editor, identifiers, error messages |
