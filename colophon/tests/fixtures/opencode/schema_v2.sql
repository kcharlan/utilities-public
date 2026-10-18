-- Schema only: minimal projection of Homebrew OpenCode 2.0.32's public schema.
CREATE TABLE migration (id TEXT PRIMARY KEY, time_completed INTEGER NOT NULL);
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL,
                 time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL);
CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT NOT NULL,
                      time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL,
                      time_archived INTEGER);
CREATE TABLE session_v2 (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT, fork_session_id TEXT,
  directory TEXT NOT NULL, title TEXT, version TEXT NOT NULL, agent TEXT, model TEXT,
  cost REAL DEFAULT 0 NOT NULL,
  tokens_input INTEGER DEFAULT 0 NOT NULL, tokens_output INTEGER DEFAULT 0 NOT NULL,
  tokens_reasoning INTEGER DEFAULT 0 NOT NULL, tokens_cache_read INTEGER DEFAULT 0 NOT NULL,
  tokens_cache_write INTEGER DEFAULT 0 NOT NULL,
  time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, time_idle INTEGER,
  idle_outcome TEXT, time_archived INTEGER,
  FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);
CREATE TABLE session_message (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL, seq INTEGER NOT NULL,
  time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES session_v2(id) ON DELETE CASCADE
);
