/// Schema v1 (spec section 4: the database schema is the builder's, but it must hold
/// responses, failed turns, connection events, incidents, episodes, events, baseline epochs,
/// collector runs, per-source cursors and settings). Times are REAL Unix seconds.
///
/// The statements are plain `CREATE TABLE`, not `IF NOT EXISTS`: the migration runs once,
/// inside `BEGIN IMMEDIATE` after re-checking `user_version`, so a second run would be a bug
/// that should fail loudly.
enum Schema {
    static let currentVersion = 1

    static let version1: [String] = [
        """
        CREATE TABLE responses (
            provider TEXT NOT NULL,
            response_id TEXT NOT NULL,
            model TEXT NOT NULL,
            effort TEXT,
            service_tier TEXT,
            session_id TEXT NOT NULL,
            is_subagent INTEGER NOT NULL,
            turn_id TEXT,
            start_at REAL NOT NULL,
            end_at REAL NOT NULL,
            input_tokens INTEGER NOT NULL,
            cached_input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            reasoning_tokens INTEGER,
            PRIMARY KEY (provider, response_id)
        )
        """,
        "CREATE INDEX idx_responses_provider_model_end ON responses (provider, model, end_at)",
        "CREATE INDEX idx_responses_turn ON responses (turn_id)",
        """
        CREATE TABLE failed_turns (
            provider TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            started_at REAL NOT NULL,
            completed_at REAL,
            model TEXT,
            error_code TEXT NOT NULL,
            message TEXT NOT NULL,
            evaluated_at REAL,
            PRIMARY KEY (provider, turn_id)
        )
        """,
        "CREATE INDEX idx_failed_turns_started ON failed_turns (provider, started_at)",
        """
        CREATE TABLE connection_events (
            provider TEXT NOT NULL,
            source_id TEXT NOT NULL,
            at REAL NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL,
            retries INTEGER,
            max_retries INTEGER,
            PRIMARY KEY (provider, source_id)
        )
        """,
        "CREATE INDEX idx_connection_events_at ON connection_events (provider, at)",
        """
        CREATE TABLE status_components (
            source TEXT NOT NULL,
            component_id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (source, component_id)
        )
        """,
        """
        CREATE TABLE incidents (
            source TEXT NOT NULL,
            incident_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            published_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            link TEXT NOT NULL,
            history_json TEXT NOT NULL,
            impacts_json TEXT NOT NULL,
            PRIMARY KEY (source, incident_id)
        )
        """,
        """
        CREATE TABLE usage_limits (
            provider TEXT NOT NULL PRIMARY KEY,
            at REAL NOT NULL,
            used_percent REAL NOT NULL,
            window_minutes INTEGER NOT NULL,
            resets_at REAL
        )
        """,
        """
        CREATE TABLE eval_points (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            at REAL NOT NULL,
            speed_index REAL,
            mix_usual_tps REAL,
            median_tps REAL,
            samples INTEGER NOT NULL,
            state TEXT NOT NULL,
            PRIMARY KEY (provider, model, at)
        )
        """,
        """
        CREATE TABLE rule_state (
            rule TEXT NOT NULL,
            provider TEXT NOT NULL,
            scope TEXT NOT NULL,
            json TEXT NOT NULL,
            PRIMARY KEY (rule, provider, scope)
        )
        """,
        """
        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule TEXT NOT NULL,
            provider TEXT NOT NULL,
            scope TEXT NOT NULL,
            direction TEXT,
            onset_at REAL NOT NULL,
            fired_at REAL NOT NULL,
            ended_at REAL,
            end_reason TEXT,
            severity TEXT,
            worst_value REAL,
            detail_json TEXT
        )
        """,
        "CREATE INDEX idx_episodes_rule_scope ON episodes (rule, provider, scope, ended_at)",
        """
        CREATE TABLE baseline_epochs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            since_day TEXT NOT NULL,
            created_at REAL NOT NULL,
            undone_at REAL,
            before_json TEXT,
            after_json TEXT
        )
        """,
        "CREATE INDEX idx_baseline_epochs_model ON baseline_epochs (provider, model, created_at)",
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL NOT NULL,
            kind TEXT NOT NULL,
            provider TEXT NOT NULL,
            scope TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            episode_id INTEGER REFERENCES episodes (id) ON DELETE SET NULL,
            epoch_id INTEGER REFERENCES baseline_epochs (id) ON DELETE SET NULL,
            link TEXT,
            undone_at REAL
        )
        """,
        "CREATE INDEX idx_events_at ON events (at)",
        """
        CREATE TABLE shift_dismissals (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            direction TEXT NOT NULL,
            first_day TEXT NOT NULL,
            dismissed_at REAL NOT NULL,
            PRIMARY KEY (provider, model, direction, first_day)
        )
        """,
        """
        CREATE TABLE collector_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at REAL NOT NULL,
            finished_at REAL,
            outcome TEXT NOT NULL,
            detail TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_collector_runs_started ON collector_runs (started_at)",
        """
        CREATE TABLE cursors (
            source TEXT NOT NULL PRIMARY KEY,
            data BLOB NOT NULL
        )
        """,
        """
        CREATE TABLE source_state (
            source TEXT NOT NULL PRIMARY KEY,
            state_json TEXT NOT NULL,
            version TEXT,
            unavailable_since REAL,
            updated_at REAL NOT NULL
        )
        """,
        """
        CREATE TABLE settings (
            key TEXT NOT NULL PRIMARY KEY,
            value_json TEXT NOT NULL
        )
        """,
    ]
}
