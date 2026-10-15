"""Declaration identity migration against historical 1559dcb schema."""
import sqlite3

import pytest
import git_dashboard

# Historical _SCHEMA_SQL at 1559dcb; never use the new initializer for legacy DBs.
_LEGACY_SCHEMA_SQL = """\
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS repositories (
  id                  TEXT PRIMARY KEY,
  name                TEXT NOT NULL,
  path                TEXT NOT NULL UNIQUE,
  default_branch      TEXT DEFAULT 'main',
  runtime             TEXT,
  added_at            TEXT NOT NULL,
  last_quick_scan_at  TEXT,
  last_full_scan_at   TEXT
);

CREATE TABLE IF NOT EXISTS daily_stats (
  repo_id        TEXT    NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  date           TEXT    NOT NULL,
  commits        INTEGER DEFAULT 0,
  insertions     INTEGER DEFAULT 0,
  deletions      INTEGER DEFAULT 0,
  files_changed  INTEGER DEFAULT 0,
  PRIMARY KEY (repo_id, date)
);

CREATE TABLE IF NOT EXISTS branches (
  repo_id           TEXT    NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  name              TEXT    NOT NULL,
  last_commit_date  TEXT,
  is_default        BOOLEAN DEFAULT FALSE,
  is_stale          BOOLEAN DEFAULT FALSE,
  PRIMARY KEY (repo_id, name)
);

CREATE TABLE IF NOT EXISTS dependencies (
  repo_id          TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  manager          TEXT NOT NULL,
  name             TEXT NOT NULL,
  current_version  TEXT,
  wanted_version   TEXT,
  latest_version   TEXT,
  severity         TEXT DEFAULT 'ok',
  advisory_id      TEXT,
  checked_at       TEXT,
  source_path      TEXT DEFAULT '',
  PRIMARY KEY (repo_id, manager, name)
);

CREATE TABLE IF NOT EXISTS working_state (
  repo_id              TEXT PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
  has_uncommitted      BOOLEAN DEFAULT FALSE,
  modified_count       INTEGER DEFAULT 0,
  untracked_count      INTEGER DEFAULT 0,
  staged_count         INTEGER DEFAULT 0,
  current_branch       TEXT,
  last_commit_hash     TEXT,
  last_commit_message  TEXT,
  last_commit_date     TEXT,
  checked_at           TEXT,
  scan_error           TEXT DEFAULT NULL,
  dep_check_error      BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS scan_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_type       TEXT NOT NULL,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  repos_scanned   INTEGER DEFAULT 0,
  status          TEXT DEFAULT 'running'
);
"""
# Historical _MIGRATION_SQL at 1559dcb.
_LEGACY_MIGRATION_SQL = [
    "ALTER TABLE working_state ADD COLUMN scan_error TEXT DEFAULT NULL",
    "ALTER TABLE working_state ADD COLUMN dep_check_error BOOLEAN DEFAULT FALSE",
    "ALTER TABLE dependencies ADD COLUMN source_path TEXT DEFAULT ''",
]


def _legacy_db(tmp_path, *, source_path="proj/manifest", include_source=True,
               extra_ws_column=True):
    db = tmp_path / "legacy.db"
    schema = _LEGACY_SCHEMA_SQL
    if not include_source:
        schema = schema.replace("  source_path      TEXT DEFAULT '',\n", "")
    with sqlite3.connect(db) as conn:
        conn.executescript(schema)
        for sql in _LEGACY_MIGRATION_SQL:
            if not include_source and "source_path" in sql:
                continue
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        if extra_ws_column:
            conn.execute("ALTER TABLE working_state ADD COLUMN missing_tools TEXT")
        conn.execute("INSERT INTO repositories (id, name, path, added_at) VALUES ('synthetic-repo', 'synthetic-repo', '/synthetic/repo', 'synthetic-time')")
        columns = "repo_id, manager, name, current_version, wanted_version, latest_version, severity, advisory_id, checked_at"
        values = ['synthetic-repo', 'pip', 'SYNTHETIC_Pkg.Name', '1.0', '1.5', '2.0', 'vulnerable', 'SYNTHETIC-ADVISORY', 'synthetic-time']
        if include_source:
            columns += ", source_path"
            values.append(source_path)
        conn.execute(f"INSERT INTO dependencies ({columns}) VALUES ({','.join('?' for _ in values)})", values)
    return db


def _rows(db):
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM dependencies ORDER BY rowid")]


def test_fresh_schema_has_declaration_key(tmp_path):
    db = tmp_path / 'fresh.db'
    git_dashboard.init_schema(db)
    with sqlite3.connect(db) as conn:
        info = conn.execute('PRAGMA table_info(dependencies)').fetchall()
        assert [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]] == ['repo_id', 'manager', 'source_path', 'name']
        conn.execute("INSERT INTO dependencies (repo_id, manager, source_path, name) VALUES ('synthetic-repo', 'pip', 'a/requirements.txt', 'synthetic-pkg')")
        conn.execute("INSERT INTO dependencies (repo_id, manager, source_path, name) VALUES ('synthetic-repo', 'pip', 'b/requirements.txt', 'synthetic-pkg')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO dependencies (repo_id, manager, source_path, name) VALUES ('synthetic-repo', 'pip', NULL, 'synthetic-pkg')")


def test_migration_preserves_data_and_invalidates_coverage(tmp_path):
    db = _legacy_db(tmp_path)
    git_dashboard.run_migrations(db)
    row, = _rows(db)
    assert (row['name'], row['source_path']) == ('synthetic-pkg-name', 'proj/manifest')
    assert [row[k] for k in ('current_version', 'wanted_version', 'latest_version', 'checked_at')] == ['1.0', '1.5', '2.0', 'synthetic-time']
    assert [row[k] for k in ('severity', 'outdated_state', 'vuln_state')] == ['unchecked'] * 3
    assert row['advisory_id'] is None and row['declared_spec'] is None
    assert 'vulnerable' in row['check_note'] and 'SYNTHETIC-ADVISORY' in row['check_note']
    assert 'rescan' in row['check_note'].lower()


def test_migration_keeps_first_normalized_collision(tmp_path):
    db = _legacy_db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO dependencies (repo_id, manager, name, source_path, current_version) VALUES ('synthetic-repo', 'pip', 'synthetic-pkg-name', 'proj/manifest', '99.0')")
    git_dashboard.run_migrations(db)
    assert len(_rows(db)) == 1
    assert _rows(db)[0]['current_version'] == '1.0'


def test_migration_coalesces_sql_null_source(tmp_path):
    db = _legacy_db(tmp_path, source_path=None)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM dependencies WHERE source_path IS NULL').fetchone()[0] > 0
    git_dashboard.run_migrations(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM dependencies WHERE source_path IS NULL').fetchone()[0] == 0
        assert {r[0] for r in conn.execute('SELECT source_path FROM dependencies')} == {''}


def test_migration_handles_absent_source_column(tmp_path):
    db = _legacy_db(tmp_path, include_source=False)
    git_dashboard.run_migrations(db)
    assert _rows(db)[0]['source_path'] == ''
    assert _rows(db)[0]['severity'] == 'unchecked'


def test_migration_handles_existing_missing_tools_column(tmp_path):
    db = _legacy_db(tmp_path, extra_ws_column=True)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO working_state (repo_id, missing_tools) VALUES ('synthetic-repo', 'synthetic-tool')")
    git_dashboard.run_migrations(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT missing_tools FROM working_state').fetchone() == ('synthetic-tool',)
    assert _rows(db)[0]['severity'] == 'unchecked'


def test_migration_is_idempotent(tmp_path):
    db = _legacy_db(tmp_path)
    git_dashboard.run_migrations(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE dependencies SET severity='ok', outdated_state='checked', vuln_state='checked', advisory_id='SYNTHETIC-AFTER', check_note='synthetic checked'")
    before = _rows(db)
    git_dashboard.run_migrations(db)
    assert _rows(db) == before


def test_migration_rolls_back_failed_copy(tmp_path):
    db = _legacy_db(tmp_path)
    before = _rows(db)
    with sqlite3.connect(db) as conn:
        # SQLite authorizer rejects writes to the rebuilt table after its rename.
        def deny_copy(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_INSERT and table == 'dependencies':
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        conn.set_authorizer(deny_copy)
        with pytest.raises(sqlite3.DatabaseError):
            git_dashboard._migrate_dependencies_v2(conn)
        conn.set_authorizer(None)
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'dependencies%'").fetchall() == [('dependencies',)]
    assert _rows(db) == before
