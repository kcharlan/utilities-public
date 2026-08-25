from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
import stat as stat_module
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

UTILITIES_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(UTILITIES_ROOT))

from tools.testkit import load_launcher


MODULE_PATH = Path(__file__).with_name("router_log_analyze.py")
analyzer = load_launcher(MODULE_PATH, "router_log_analyze")


LEGACY_PARSE_STATS_KEYS = (
    "total_lines", "parsed_events", "malformed_lines", "duplicate_events", "spam_filtered",
    "ignored_lines", "export_noise_lines", "malformed_samples",
)


def legacy_parse_stats_projection(stats: dict[str, object]) -> dict[str, object]:
    return {key: stats[key] for key in LEGACY_PARSE_STATS_KEYS}


def seed_epoch(store: analyzer.StateStore) -> int:
    store.conn.execute(
        """
        INSERT INTO baseline_epochs(created_at, source_path, source_hash, label, is_active)
        VALUES(?, ?, ?, ?, 1)
        """,
        ("2037-03-01T00:00:00Z", None, None, "test"),
    )
    store.conn.commit()
    row = store.get_active_epoch()
    assert row is not None
    return int(row["id"])


def insert_history_day(
    store: analyzer.StateStore,
    epoch_id: int,
    file_hash: str,
    observed_date: str,
    mac: str,
    event_key: str,
    event_family: str,
    timestamps: list[str],
) -> int:
    run_id = store.insert_run(
        epoch_id=epoch_id,
        policy_profile_id=None,
        file_hash=file_hash,
        source_path=Path(f"/tmp/{file_hash}.log"),
        parse_stats=analyzer.ParseStats(parsed_events=len(timestamps)),
        observation_start=timestamps[0],
        observation_end=timestamps[-1],
        observed_dates=[observed_date],
        risk_score=0,
        status="Clean",
        is_partial=False,
    )
    device_stat = analyzer.DeviceDayAggregate(observed_date=observed_date, mac=mac)
    event_stat = analyzer.EventDayAggregate(
        observed_date=observed_date,
        mac=mac,
        event_key=event_key,
        event_family=event_family,
    )
    for timestamp_iso in timestamps:
        event = analyzer.Event(
            timestamp=datetime.fromisoformat(timestamp_iso),
            mac=mac,
            event_family=event_family,
            event_key=event_key,
            ip=None,
            raw_label=event_key,
            raw_line="",
            source="test",
        )
        device_stat.add_event(event)
        event_stat.add_event(event)
    store.insert_device_daily_stat(run_id, epoch_id, device_stat, True, None)
    store.insert_device_event_daily_stat(run_id, epoch_id, event_stat, True, None)
    store.conn.commit()
    return run_id


def mark_device_day_excluded(
    store: analyzer.StateStore,
    run_id: int,
    mac: str,
    reason: str,
) -> None:
    store.conn.execute(
        """
        UPDATE device_daily_stats
        SET included_in_learning = 0, exclusion_reason = ?
        WHERE run_id = ? AND mac = ?
        """,
        (reason, run_id, mac),
    )
    store.conn.commit()


def make_current_stat(
    observed_date: str,
    mac: str,
    event_key: str,
    event_family: str,
    timestamps: list[str],
) -> analyzer.EventDayAggregate:
    stat = analyzer.EventDayAggregate(
        observed_date=observed_date,
        mac=mac,
        event_key=event_key,
        event_family=event_family,
    )
    for timestamp_iso in timestamps:
        stat.add_event(
            analyzer.Event(
                timestamp=datetime.fromisoformat(timestamp_iso),
                mac=mac,
                event_family=event_family,
                event_key=event_key,
                ip=None,
                raw_label=event_key,
                raw_line="",
                source="test",
            )
        )
    return stat


def make_aggregate(
    mac_to_name: dict[str, str] | None = None,
    devices_snapshot: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "mac_to_name": mac_to_name or {},
        "devices_snapshot": devices_snapshot or {},
        "events_by_mac": {},
        "observation_range": {"start": None, "end": None},
        "events_per_hour": {},
    }


def make_event(
    timestamp_iso: str,
    mac: str,
    event_key: str,
    event_family: str | None = None,
) -> analyzer.Event:
    family = event_family
    if family is None:
        family = {
            "DHCP_IP": "DHCP",
            "WLAN_ACCESS_ALLOWED": "WLAN_ALLOWED",
            "WLAN_ACCESS_REJECTED": "WLAN_REJECTED",
        }.get(event_key, "OTHER")
    return analyzer.Event(
        timestamp=datetime.fromisoformat(timestamp_iso),
        mac=mac,
        event_family=family,
        event_key=event_key,
        ip=None,
        raw_label=event_key,
        raw_line="",
        source="test",
    )


def incident_devices(count: int) -> tuple[dict[str, object], dict[str, dict[str, object]], list[str]]:
    macs = [f"02:00:00:00:00:{index:02X}" for index in range(1, count + 1)]
    baseline = {"devices": {mac: {"name": f"Device {index}"} for index, mac in enumerate(macs, 1)}}
    snapshot = {
        mac: {"name": f"Device {index}", "status": "allowed", "source": "baseline_import"}
        for index, mac in enumerate(macs, 1)
    }
    return baseline, snapshot, macs


def build_v3_database(db_path: Path, *, populate: bool = True) -> dict[str, object]:
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE baseline_epochs (
          id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, source_path TEXT, source_hash TEXT,
          label TEXT, is_active INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_baseline_epochs_active ON baseline_epochs(is_active);
        CREATE TABLE baseline_seed_devices (
          id INTEGER PRIMARY KEY, epoch_id INTEGER NOT NULL, mac TEXT NOT NULL, name TEXT,
          dhcp_min REAL, dhcp_max REAL, dhcp_seed_weight REAL, total_events_min REAL,
          total_events_max REAL, total_events_seed_weight REAL, active_hours_json TEXT,
          expected_windows_json TEXT, expected_events_json TEXT, pattern TEXT, soft_max REAL,
          UNIQUE(epoch_id, mac), FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
        );
        CREATE INDEX idx_seed_devices_epoch_mac ON baseline_seed_devices(epoch_id, mac);
        CREATE TABLE baseline_seed_clusters (
          id INTEGER PRIMARY KEY, epoch_id INTEGER NOT NULL, cluster_name TEXT NOT NULL,
          mac_prefixes_json TEXT, cluster_size INTEGER, min_cluster_size INTEGER,
          cluster_time_window_seconds INTEGER, expected_windows_json TEXT,
          UNIQUE(epoch_id, cluster_name), FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
        );
        CREATE TABLE policy_profiles (
          id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, name TEXT NOT NULL,
          schema_version INTEGER NOT NULL, source_path TEXT, source_hash TEXT,
          is_active INTEGER NOT NULL DEFAULT 0, policy_json TEXT NOT NULL
        );
        CREATE INDEX idx_policy_profiles_active ON policy_profiles(is_active);
        CREATE TABLE runs (
          id INTEGER PRIMARY KEY, epoch_id INTEGER NOT NULL, policy_profile_id INTEGER,
          file_hash TEXT NOT NULL UNIQUE, source_path TEXT, ingested_at TEXT NOT NULL,
          observation_start TEXT, observation_end TEXT, observed_dates_json TEXT,
          parsed_event_count INTEGER NOT NULL DEFAULT 0,
          malformed_line_count INTEGER NOT NULL DEFAULT 0,
          export_noise_line_count INTEGER NOT NULL DEFAULT 0, risk_score INTEGER,
          status TEXT, is_partial INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id),
          FOREIGN KEY(policy_profile_id) REFERENCES policy_profiles(id)
        );
        CREATE INDEX idx_runs_epoch_time ON runs(epoch_id, ingested_at);
        CREATE TABLE network_incidents (
          id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, incident_id TEXT NOT NULL,
          incident_type TEXT NOT NULL, confidence TEXT NOT NULL, start TEXT NOT NULL,
          restored_at TEXT NOT NULL, recovery_end TEXT NOT NULL,
          disconnect_count INTEGER NOT NULL DEFAULT 0, connect_count INTEGER NOT NULL DEFAULT 0,
          affected_macs_json TEXT NOT NULL, event_counts_json TEXT NOT NULL,
          explained_event_count INTEGER NOT NULL DEFAULT 0,
          active_known_devices INTEGER NOT NULL DEFAULT 0,
          affected_device_fraction REAL NOT NULL DEFAULT 0, UNIQUE(run_id, incident_id),
          FOREIGN KEY(run_id) REFERENCES runs(id)
        );
        CREATE INDEX idx_network_incidents_run ON network_incidents(run_id);
        CREATE TABLE devices (
          mac TEXT PRIMARY KEY, name TEXT, status TEXT, connection_type TEXT, source TEXT,
          first_seen TEXT, last_seen TEXT
        );
        CREATE TABLE device_daily_stats (
          id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, epoch_id INTEGER NOT NULL,
          observed_date TEXT NOT NULL, mac TEXT NOT NULL, dhcp_count INTEGER NOT NULL DEFAULT 0,
          total_events INTEGER NOT NULL DEFAULT 0, first_seen TEXT, last_seen TEXT,
          event_types_json TEXT, active_hours_json TEXT,
          included_in_learning INTEGER NOT NULL DEFAULT 1, exclusion_reason TEXT,
          UNIQUE(run_id, observed_date, mac), FOREIGN KEY(run_id) REFERENCES runs(id),
          FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
        );
        CREATE INDEX idx_device_daily_epoch_mac_date
          ON device_daily_stats(epoch_id, mac, observed_date);
        CREATE TABLE device_event_daily_stats (
          id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, epoch_id INTEGER NOT NULL,
          observed_date TEXT NOT NULL, mac TEXT NOT NULL, event_key TEXT NOT NULL,
          event_family TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, first_seen TEXT,
          last_seen TEXT, hour_histogram_json TEXT,
          included_in_learning INTEGER NOT NULL DEFAULT 1, exclusion_reason TEXT,
          UNIQUE(run_id, observed_date, mac, event_key), FOREIGN KEY(run_id) REFERENCES runs(id),
          FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
        );
        CREATE INDEX idx_device_event_daily_epoch_mac_key_date
          ON device_event_daily_stats(epoch_id, mac, event_key, observed_date);
        CREATE TABLE behavior_subjects (
          subject_key TEXT NOT NULL, subject_type TEXT NOT NULL, display_name TEXT,
          attributes_json TEXT, first_seen TEXT, last_seen TEXT,
          PRIMARY KEY(subject_key, subject_type)
        );
        CREATE INDEX idx_behavior_subjects_type_key
          ON behavior_subjects(subject_type, subject_key);
        CREATE TABLE subject_behavior_daily_stats (
          id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, epoch_id INTEGER NOT NULL,
          observed_date TEXT NOT NULL, subject_key TEXT NOT NULL, subject_type TEXT NOT NULL,
          behavior_key TEXT NOT NULL, behavior_family TEXT NOT NULL,
          count INTEGER NOT NULL DEFAULT 0, first_seen TEXT, last_seen TEXT,
          hour_histogram_json TEXT, occurrence_starts_json TEXT, occurrence_ends_json TEXT,
          occurrence_sizes_json TEXT, context_json TEXT,
          included_in_learning INTEGER NOT NULL DEFAULT 1, exclusion_reason TEXT,
          UNIQUE(run_id, observed_date, subject_key, subject_type, behavior_key),
          FOREIGN KEY(run_id) REFERENCES runs(id),
          FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
        );
        CREATE INDEX idx_subject_behavior_epoch_subject_date
          ON subject_behavior_daily_stats(
            epoch_id, subject_key, subject_type, behavior_key, observed_date
          );
        INSERT INTO metadata(key, value) VALUES('schema_version', '3');
        """
    )
    if populate:
        connection.executescript(
            """
            INSERT INTO baseline_epochs(
              id, created_at, source_path, source_hash, label, is_active
            ) VALUES(11, '2037-01-01T00:00:00Z', '/synthetic/baseline.json',
                     'synthetic-baseline-hash', 'synthetic', 1);
            INSERT INTO baseline_seed_devices(
              id, epoch_id, mac, name, dhcp_min, dhcp_max, dhcp_seed_weight,
              total_events_min, total_events_max, total_events_seed_weight,
              active_hours_json, expected_windows_json, expected_events_json, pattern, soft_max
            ) VALUES(12, 11, '02:00:00:00:00:01', 'SYNTHETIC BASELINE DEVICE',
                     1, 3, 4, 2, 8, 4, '[8]', '[]', '[]', NULL, NULL);
            INSERT INTO baseline_seed_clusters(
              id, epoch_id, cluster_name, mac_prefixes_json, cluster_size,
              min_cluster_size, cluster_time_window_seconds, expected_windows_json
            ) VALUES(13, 11, 'SYNTHETIC CLUSTER', '["02:00:00"]', 2, 1, 300, '[]');
            INSERT INTO policy_profiles(
              id, created_at, name, schema_version, source_path, source_hash,
              is_active, policy_json
            ) VALUES(14, '2037-01-02T00:00:00Z', 'synthetic-policy', 1,
                     '/synthetic/policy.json', 'synthetic-policy-hash', 1, '{"schema_version":1}');
            INSERT INTO runs(
              id, epoch_id, policy_profile_id, file_hash, source_path, ingested_at,
              observation_start, observation_end, observed_dates_json,
              parsed_event_count, malformed_line_count, export_noise_line_count,
              risk_score, status, is_partial
            ) VALUES(15, 11, 14, 'synthetic-run-hash', '/synthetic/router.log',
                     '2037-02-01T13:00:00Z', '2037-02-01T12:00:00',
                     '2037-02-01T12:30:00', '["2037-02-01"]', 4, 1, 2, 10, 'Clean', 1);
            INSERT INTO network_incidents(
              id, run_id, incident_id, incident_type, confidence, start, restored_at,
              recovery_end, disconnect_count, connect_count, affected_macs_json,
              event_counts_json, explained_event_count, active_known_devices,
              affected_device_fraction
            ) VALUES(16, 15, 'synthetic-incident', 'internet_connection_reset', 'confirmed',
                     '2037-02-01T12:00:00', '2037-02-01T12:01:00',
                     '2037-02-01T12:02:00', 1, 1, '[]', '{}', 2, 1, 1.0);
            INSERT INTO devices VALUES(
              '02:00:00:00:00:01', 'SYNTHETIC BASELINE DEVICE', 'allowed', NULL,
              'baseline_import', '2037-01-01T00:00:00', '2037-02-01T12:00:00'
            );
            INSERT INTO devices VALUES(
              '02:00:00:00:00:02', 'SYNTHETIC CONFIG ONLY', 'blocked', 'wifi',
              'config_import', '2037-01-10T00:00:00', '2037-01-10T00:00:00'
            );
            INSERT INTO devices VALUES(
              '02:00:00:00:00:03', 'SYNTHETIC CATALOG ONLY', NULL, NULL,
              'observed', '2037-01-11T00:00:00', '2037-01-11T00:00:00'
            );
            INSERT INTO devices VALUES(
              '02:00:00:00:00:04', 'SYNTHETIC OBSERVED DEVICE', 'allowed', 'wired',
              'observed', '2037-02-01T12:01:00', '2037-02-01T12:29:00'
            );
            INSERT INTO devices VALUES(
              '__SYSTEM__', 'Router/System', 'allowed', NULL, 'system',
              '2037-02-01T12:00:00', '2037-02-01T12:30:00'
            );
            INSERT INTO device_daily_stats(
              id, run_id, epoch_id, observed_date, mac, dhcp_count, total_events,
              first_seen, last_seen, event_types_json, active_hours_json,
              included_in_learning, exclusion_reason
            ) VALUES(17, 15, 11, '2037-02-01', '02:00:00:00:00:04', 1, 2,
                     '2037-02-01T12:01:00', '2037-02-01T12:29:00',
                     '{"DHCP_IP":1}', '[12]', 1, NULL);
            INSERT INTO device_daily_stats(
              id, run_id, epoch_id, observed_date, mac, dhcp_count, total_events,
              first_seen, last_seen, event_types_json, active_hours_json,
              included_in_learning, exclusion_reason
            ) VALUES(18, 15, 11, '2037-02-01', '__SYSTEM__', 0, 2,
                     '2037-02-01T12:00:00', '2037-02-01T12:30:00',
                     '{"INTERNET_CONNECTED":1}', '[12]', 1, NULL);
            INSERT INTO device_event_daily_stats(
              id, run_id, epoch_id, observed_date, mac, event_key, event_family,
              count, first_seen, last_seen, hour_histogram_json,
              included_in_learning, exclusion_reason
            ) VALUES(19, 15, 11, '2037-02-01', '02:00:00:00:00:04',
                     'DHCP_IP', 'DHCP', 1, '2037-02-01T12:01:00',
                     '2037-02-01T12:01:00', '{"12":1}', 1, NULL);
            INSERT INTO device_event_daily_stats(
              id, run_id, epoch_id, observed_date, mac, event_key, event_family,
              count, first_seen, last_seen, hour_histogram_json,
              included_in_learning, exclusion_reason
            ) VALUES(20, 15, 11, '2037-02-01', '__SYSTEM__',
                     'INTERNET_CONNECTED', 'OTHER', 1, '2037-02-01T12:30:00',
                     '2037-02-01T12:30:00', '{"12":1}', 1, NULL);
            INSERT INTO behavior_subjects VALUES(
              '__SYSTEM__', 'device', 'Router/System', '{}',
              '2037-02-01T12:00:00', '2037-02-01T12:30:00'
            );
            INSERT INTO behavior_subjects VALUES(
              '02:00:00:00:00:04', 'device', 'SYNTHETIC OBSERVED DEVICE', '{}',
              '2037-02-01T12:01:00', '2037-02-01T12:29:00'
            );
            INSERT INTO subject_behavior_daily_stats(
              id, run_id, epoch_id, observed_date, subject_key, subject_type,
              behavior_key, behavior_family, count, first_seen, last_seen,
              hour_histogram_json, occurrence_starts_json, occurrence_ends_json,
              occurrence_sizes_json, context_json, included_in_learning, exclusion_reason
            ) VALUES(21, 15, 11, '2037-02-01', '__SYSTEM__', 'device',
                     'internet_cycle', 'OTHER', 1, '2037-02-01T12:00:00',
                     '2037-02-01T12:30:00', '{"12":1}', '[]', '[]', '[]', '[]', 1, NULL);
            INSERT INTO subject_behavior_daily_stats(
              id, run_id, epoch_id, observed_date, subject_key, subject_type,
              behavior_key, behavior_family, count, first_seen, last_seen,
              hour_histogram_json, occurrence_starts_json, occurrence_ends_json,
              occurrence_sizes_json, context_json, included_in_learning, exclusion_reason
            ) VALUES(22, 15, 11, '2037-02-01', '02:00:00:00:00:04', 'device',
                     'dhcp', 'DHCP', 1, '2037-02-01T12:01:00',
                     '2037-02-01T12:01:00', '{"12":1}', '[]', '[]', '[]', '[]', 1, NULL);
            """
        )
    connection.commit()
    legacy_tables = tuple(analyzer.V3_REQUIRED_COLUMNS)
    snapshot = {
        "counts": {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in legacy_tables
        },
        "ids": {
            table: [row[0] for row in connection.execute(f'SELECT id FROM "{table}" ORDER BY id')]
            for table in legacy_tables
            if "id" in analyzer.V3_REQUIRED_COLUMNS[table]
        },
    }
    connection.close()
    return snapshot


def rewrite_sqlite_schema_object(
    db_path: Path,
    object_name: str,
    rewrite: Callable[[str], str],
) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA journal_mode = DELETE")
        original_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?",
            (object_name,),
        ).fetchone()[0]
        rewritten_sql = rewrite(original_sql)
        assert rewritten_sql != original_sql
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute(
            "UPDATE sqlite_master SET sql = ? WHERE name = ?",
            (rewritten_sql, object_name),
        )
        schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
        connection.execute(f"PRAGMA schema_version = {schema_version + 1}")
        connection.commit()
    finally:
        connection.close()


def strand_wal_commit(db_path: Path, statement: str) -> None:
    child = """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
connection.execute("PRAGMA wal_autocheckpoint = 0")
connection.execute(sys.argv[2])
connection.commit()
os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", child, str(db_path), statement],
        check=True,
        capture_output=True,
        text=True,
    )
    assert Path(f"{db_path}-wal").is_file()
    assert Path(f"{db_path}-shm").is_file()


def database_artifact_state(db_path: Path) -> dict[str, tuple[bytes, int, int]]:
    state = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        artifact = Path(f"{db_path}{suffix}")
        if artifact.exists():
            stat = artifact.stat()
            state[suffix] = (artifact.read_bytes(), stat.st_size, stat.st_mtime_ns)
    return state


def lexical_artifact_state(
    db_path: Path,
) -> dict[str, tuple[int, int, int, str | None, bytes | None]]:
    state = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        artifact = Path(f"{db_path}{suffix}")
        try:
            artifact_stat = artifact.lstat()
        except FileNotFoundError:
            continue
        state[suffix] = (
            artifact_stat.st_mode,
            artifact_stat.st_size,
            artifact_stat.st_mtime_ns,
            os.readlink(artifact) if stat_module.S_ISLNK(artifact_stat.st_mode) else None,
            artifact.read_bytes() if stat_module.S_ISREG(artifact_stat.st_mode) else None,
        )
    return state


def strand_hot_journal(db_path: Path, transient_schema_version: int) -> None:
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE synthetic_hot_journal_pages(id INTEGER PRIMARY KEY, payload TEXT)"
    )
    connection.executemany(
        "INSERT INTO synthetic_hot_journal_pages VALUES(?, ?)",
        [(index, "a" * 3000) for index in range(96)],
    )
    connection.commit()
    connection.close()
    child = """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
assert connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0] == "delete"
connection.execute("PRAGMA synchronous = FULL")
connection.execute("PRAGMA cache_size = 1")
connection.execute("BEGIN IMMEDIATE")
connection.execute(
    "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
    (sys.argv[2],),
)
for index in range(96):
    connection.execute(
        "UPDATE synthetic_hot_journal_pages SET payload = ? WHERE id = ?",
        ("b" * 3000, index),
    )
os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", child, str(db_path), str(transient_schema_version)],
        check=True,
        capture_output=True,
        text=True,
    )
    journal_path = Path(f"{db_path}-journal")
    assert journal_path.is_file()
    assert journal_path.stat().st_size > 512
    assert journal_path.read_bytes()[:8] == bytes.fromhex("d9d505f920a163d7")


PRE_REVERSE_INDEX_V4_MISSING_INDEXES = (
    "idx_run_event_occurrences_occurrence",
    "idx_run_router_boot_sessions_boot_session",
    "idx_router_event_occurrences_boot_session",
)


def build_pre_reverse_index_v4_database(db_path: Path) -> dict[str, object]:
    """Build the exact runtime v4 shape emitted before reverse indexes were added."""
    store = analyzer.StateStore(db_path)
    try:
        epoch_id = seed_epoch(store)
        router_id = store.get_or_create_legacy_netgear_router_instance()
        run_id = store.insert_run(
            epoch_id=epoch_id,
            policy_profile_id=None,
            router_instance_id=router_id,
            format_id="netgear",
            file_hash="synthetic-pre-reverse-index-run",
            source_path=Path("/synthetic/pre-reverse-index.log"),
            parse_stats=analyzer.ParseStats(parsed_events=1),
            observation_start="2037-06-01T12:00:00",
            observation_end="2037-06-01T12:01:00",
            observed_dates=["2037-06-01"],
            risk_score=0,
            status="Clean",
            is_partial=False,
        )
        store.conn.execute(
            """
            INSERT INTO router_boot_sessions(
              id, router_instance_id, session_key, trusted_local_anchor,
              adapter_boot_id, startup_signature, identity_version, created_at
            ) VALUES(
              71, ?, 'synthetic-pre-index-session', '2037-06-01T12:00:00',
              NULL, 'synthetic-startup-signature', 'router-boot-session:v1',
              '2037-06-01T12:00:00Z'
            )
            """,
            (router_id,),
        )
        store.conn.execute(
            "INSERT INTO run_router_boot_sessions(run_id, boot_session_id) VALUES(?, 71)",
            (run_id,),
        )
        store.conn.execute(
            """
            INSERT INTO router_event_occurrences(
              id, router_instance_id, occurrence_digest, identity_version,
              boot_session_id, local_timestamp, clock_trust, component,
              process_id, vendor_event_code, syslog_severity, normalized_message,
              canonical_event_key, canonical_event_family, actor_scope,
              actor_identity, structured_evidence_json
            ) VALUES(
              81, ?, 'synthetic-pre-index-occurrence', 'router-event-occurrence:v1',
              71, '2037-06-01T12:00:30', 'trusted_local', 'synthetic-component',
              NULL, NULL, NULL, 'synthetic normalized message',
              'SYNTHETIC_EVENT', 'synthetic', 'router', NULL, '{}'
            )
            """,
            (router_id,),
        )
        store.conn.execute(
            """
            INSERT INTO run_event_occurrences(
              run_id, occurrence_id, is_novel, is_repeated, source_sequence, source_count
            ) VALUES(?, 81, 1, 0, 1, 1)
            """,
            (run_id,),
        )
        store.conn.commit()
        expected = {
            "run_id": run_id,
            "epoch_id": epoch_id,
            "router_id": router_id,
            "counts": {
                table: store.conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in analyzer.V4_REQUIRED_COLUMNS
            },
            "ids": {
                table: [
                    row[0]
                    for row in store.conn.execute(f'SELECT id FROM "{table}" ORDER BY id')
                ]
                for table, columns in analyzer.V4_REQUIRED_COLUMNS.items()
                if "id" in columns
            },
            "boot_session_ids": [row[0] for row in store.conn.execute(
                "SELECT id FROM router_boot_sessions ORDER BY id"
            )],
            "occurrence_ids": [row[0] for row in store.conn.execute(
                "SELECT id FROM router_event_occurrences ORDER BY id"
            )],
        }
        for index_name in PRE_REVERSE_INDEX_V4_MISSING_INDEXES:
            store.conn.execute(f'DROP INDEX "{index_name}"')
        store.conn.commit()
        return expected
    finally:
        store.close()


def test_empty_database_is_created_directly_as_schema_v4_with_foreign_keys_enabled(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "network.db"

    store = analyzer.StateStore(db_path)
    try:
        assert store.get_metadata("schema_version") == "4"
        assert store.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        table_names = {
            row[0]
            for row in store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "router_instances",
            "router_firmware_profiles",
            "device_registrations",
            "device_observations",
            "router_metadata_observations",
            "router_snapshot_metrics",
            "router_boot_sessions",
            "run_router_boot_sessions",
            "router_event_occurrences",
            "run_event_occurrences",
        } <= table_names
        assert store.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        store.close()


def test_existing_zero_length_database_is_created_directly_as_schema_v4(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "empty.db"
    db_path.touch()

    store = analyzer.StateStore(db_path)
    try:
        assert store.get_metadata("schema_version") == "4"
    finally:
        store.close()


@pytest.mark.parametrize(
    ("main_state", "sidecars"),
    [
        ("zero", ("-wal", "-shm")),
        ("zero", ("-wal",)),
        ("zero", ("-shm",)),
        ("absent", ("-wal", "-shm")),
        ("absent", ("-journal",)),
        ("zero", ("-journal",)),
    ],
)
def test_missing_or_zero_main_with_sidecars_fails_closed_without_touching_artifacts(
    tmp_path: Path,
    main_state: str,
    sidecars: tuple[str, ...],
) -> None:
    db_path = tmp_path / "orphaned-sidecars.db"
    if main_state == "zero":
        db_path.touch()
    for suffix in sidecars:
        Path(f"{db_path}{suffix}").write_bytes(
            f"synthetic orphaned SQLite artifact {suffix}".encode("ascii")
        )
    before = database_artifact_state(db_path)

    with pytest.raises(RuntimeError, match="sidecar|journal artifact"):
        analyzer.StateStore(db_path)

    assert database_artifact_state(db_path) == before


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_missing_main_with_dangling_sidecar_symlink_fails_closed_lexically(
    tmp_path: Path,
    suffix: str,
) -> None:
    db_path = tmp_path / "dangling-sidecar.db"
    target = tmp_path / "synthetic-missing-artifact-target"
    Path(f"{db_path}{suffix}").symlink_to(target)
    before = lexical_artifact_state(db_path)

    with pytest.raises(RuntimeError) as raised:
        analyzer.StateStore(db_path)

    assert lexical_artifact_state(db_path) == before
    assert "synthetic-missing-artifact-target" not in str(raised.value)
    assert not os.path.lexists(db_path)


def test_live_sidecar_symlink_and_external_target_are_unchanged_on_rejection(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "live-sidecar.db"
    target = tmp_path / "synthetic-external-sidecar-target"
    target.write_bytes(b"synthetic external SQLite sidecar bytes")
    sidecar = Path(f"{db_path}-wal")
    sidecar.symlink_to(target)
    before_artifacts = lexical_artifact_state(db_path)
    before_target = (target.read_bytes(), target.stat().st_size, target.stat().st_mtime_ns)

    with pytest.raises(RuntimeError) as raised:
        analyzer.StateStore(db_path)

    assert lexical_artifact_state(db_path) == before_artifacts
    assert (target.read_bytes(), target.stat().st_size, target.stat().st_mtime_ns) == before_target
    assert "synthetic-external-sidecar-target" not in str(raised.value)
    assert not os.path.lexists(db_path)


@pytest.mark.parametrize("target_state", ["dangling", "live"])
def test_symlink_main_fails_closed_without_following_or_mutating_target(
    tmp_path: Path,
    target_state: str,
) -> None:
    db_path = tmp_path / "symlink-main.db"
    target = tmp_path / "synthetic-external-main-target"
    if target_state == "live":
        target.touch()
    db_path.symlink_to(target)
    before_artifacts = lexical_artifact_state(db_path)
    before_target = (
        (target.read_bytes(), target.stat().st_size, target.stat().st_mtime_ns)
        if target_state == "live"
        else None
    )

    with pytest.raises(RuntimeError) as raised:
        analyzer.StateStore(db_path)

    assert lexical_artifact_state(db_path) == before_artifacts
    if before_target is None:
        assert not os.path.lexists(target)
    else:
        assert (target.read_bytes(), target.stat().st_size, target.stat().st_mtime_ns) == before_target
    assert "synthetic-external-main-target" not in str(raised.value)


@pytest.mark.parametrize("suffix", ["", "-journal"])
def test_fifo_artifact_fails_closed_without_opening_or_blocking(
    tmp_path: Path,
    suffix: str,
) -> None:
    db_path = tmp_path / "fifo-sidecar.db"
    fifo_path = Path(f"{db_path}{suffix}")
    os.mkfifo(fifo_path)
    before = lexical_artifact_state(db_path)

    with pytest.raises(RuntimeError, match="ordinary file"):
        analyzer.StateStore(db_path)

    assert lexical_artifact_state(db_path) == before
    assert os.path.lexists(db_path) is (suffix == "")


def test_explicit_in_memory_database_uses_direct_v4_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    store = analyzer.StateStore(Path(":memory:"))
    try:
        assert store.get_metadata("schema_version") == "4"
        assert store.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        store.close()

    assert not (tmp_path / ":memory:").exists()


def test_reopening_valid_schema_v4_is_a_noop(tmp_path: Path) -> None:
    db_path = tmp_path / "network.db"
    first = analyzer.StateStore(db_path)
    try:
        first.conn.execute(
            "INSERT INTO baseline_epochs(id, created_at, label, is_active) VALUES(41, ?, ?, 1)",
            ("2037-01-01T00:00:00Z", "synthetic",),
        )
        first.conn.commit()
    finally:
        first.close()

    second = analyzer.StateStore(db_path)
    try:
        assert second.get_metadata("schema_version") == "4"
        assert second.conn.execute(
            "SELECT id FROM baseline_epochs"
        ).fetchall()[0][0] == 41
        assert second.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        second.close()


def test_v4_validation_runs_sqlite_integrity_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "network.db"
    store = analyzer.StateStore(db_path)
    store.close()
    statements: list[str] = []
    original_open = analyzer.StateStore._open_connection

    def traced_open(database: str) -> sqlite3.Connection:
        connection = original_open(database)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(
        analyzer.StateStore,
        "_open_connection",
        staticmethod(traced_open),
    )

    reopened = analyzer.StateStore(db_path)
    reopened.close()

    assert any(statement.casefold() == "pragma integrity_check" for statement in statements)


def test_v4_reverse_relationship_indexes_are_present_and_selected(
    tmp_path: Path,
) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    queries = {
        "idx_run_event_occurrences_occurrence": (
            "SELECT * FROM run_event_occurrences WHERE occurrence_id = ?",
            1,
        ),
        "idx_run_router_boot_sessions_boot_session": (
            "SELECT * FROM run_router_boot_sessions WHERE boot_session_id = ?",
            1,
        ),
        "idx_router_event_occurrences_boot_session": (
            "SELECT * FROM router_event_occurrences WHERE boot_session_id = ?",
            1,
        ),
    }
    try:
        for index_name, (sql, parameter) in queries.items():
            assert store.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
                (index_name,),
            ).fetchone() is not None
            plan = " ".join(
                row[3]
                for row in store.conn.execute(f"EXPLAIN QUERY PLAN {sql}", (parameter,))
            )
            assert index_name in plan
    finally:
        store.close()


def test_pre_reverse_index_v4_is_repaired_transactionally_and_second_open_is_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pre-reverse-index-v4.db"
    expected = build_pre_reverse_index_v4_database(db_path)

    repaired = analyzer.StateStore(db_path)
    try:
        assert repaired.get_metadata("schema_version") == "4"
        assert repaired.conn.execute("SELECT id FROM runs").fetchone()[0] == expected["run_id"]
        for table, expected_count in expected["counts"].items():
            assert repaired.conn.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0] == expected_count
        for table, expected_ids in expected["ids"].items():
            assert [
                row[0]
                for row in repaired.conn.execute(f'SELECT id FROM "{table}" ORDER BY id')
            ] == expected_ids
        assert [row[0] for row in repaired.conn.execute(
            "SELECT id FROM router_boot_sessions ORDER BY id"
        )] == expected["boot_session_ids"]
        assert [row[0] for row in repaired.conn.execute(
            "SELECT id FROM router_event_occurrences ORDER BY id"
        )] == expected["occurrence_ids"]
        assert repaired.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        for index_name in PRE_REVERSE_INDEX_V4_MISSING_INDEXES:
            assert repaired.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
                (index_name,),
            ).fetchone() is not None
    finally:
        repaired.close()

    statements: list[str] = []
    original_open = analyzer.StateStore._open_connection

    def traced_open(database: str) -> sqlite3.Connection:
        connection = original_open(database)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(
        analyzer.StateStore,
        "_open_connection",
        staticmethod(traced_open),
    )
    reopened = analyzer.StateStore(db_path)
    reopened.close()
    assert not any(
        statement.lstrip().casefold().startswith("create index")
        and any(index_name in statement for index_name in PRE_REVERSE_INDEX_V4_MISSING_INDEXES)
        for statement in statements
    )


def test_pre_reverse_index_v4_repair_rolls_back_when_post_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "pre-reverse-index-rollback.db"
    build_pre_reverse_index_v4_database(db_path)

    def reject_real_database(store: analyzer.StateStore) -> None:
        store._validate_schema(analyzer.SCHEMA_VERSION)
        if store.db_path == db_path:
            raise RuntimeError("synthetic reverse-index post-validation failure")

    monkeypatch.setattr(
        analyzer.StateStore,
        "_validate_v4_maintenance_before_commit",
        reject_real_database,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="synthetic reverse-index post-validation failure"):
        analyzer.StateStore(db_path)

    verification = sqlite3.connect(db_path)
    try:
        assert verification.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0] == "4"
        assert {
            row[0]
            for row in verification.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }.isdisjoint(PRE_REVERSE_INDEX_V4_MISSING_INDEXES)
        assert verification.execute("SELECT id FROM router_boot_sessions").fetchall() == [(71,)]
        assert verification.execute("SELECT id FROM router_event_occurrences").fetchall() == [(81,)]
    finally:
        verification.close()


def test_pre_reverse_index_compatibility_rejects_any_additional_missing_index(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pre-reverse-index-malformed.db"
    build_pre_reverse_index_v4_database(db_path)
    connection = sqlite3.connect(db_path)
    connection.execute("DROP INDEX idx_runs_epoch_time")
    connection.commit()
    connection.close()
    before = database_artifact_state(db_path)

    with pytest.raises(RuntimeError, match="idx_runs_epoch_time"):
        analyzer.StateStore(db_path)

    assert database_artifact_state(db_path) == before


def test_partial_reverse_index_loss_is_not_treated_as_pre_release_compatibility(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "partial-reverse-index-loss.db"
    store = analyzer.StateStore(db_path)
    store.close()
    connection = sqlite3.connect(db_path)
    connection.execute("DROP INDEX idx_run_event_occurrences_occurrence")
    connection.commit()
    connection.close()
    before = database_artifact_state(db_path)

    with pytest.raises(RuntimeError, match="idx_run_event_occurrences_occurrence"):
        analyzer.StateStore(db_path)

    assert database_artifact_state(db_path) == before


def test_valid_populated_v3_migrates_atomically_and_preserves_legacy_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "network.db"
    before = build_v3_database(db_path)
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE synthetic_user_notes(note TEXT NOT NULL)")
    connection.execute("INSERT INTO synthetic_user_notes VALUES('synthetic retained note')")
    connection.commit()
    connection.close()

    store = analyzer.StateStore(db_path)
    try:
        assert store.get_metadata("schema_version") == "4"
        for table, expected_count in before["counts"].items():
            assert store.conn.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0] == expected_count
        for table, expected_ids in before["ids"].items():
            assert [
                row[0] for row in store.conn.execute(f'SELECT id FROM "{table}" ORDER BY id')
            ] == expected_ids

        legacy_instance_key = analyzer.sha256_bytes(
            b"router-instance:v1\0netgear\0legacy-default"
        )
        legacy_profile_key = analyzer.sha256_bytes(
            b"firmware-profile:v1\0netgear\0unknown-legacy-firmware"
        )
        legacy_subject_key = analyzer.sha256_bytes(
            (
                "router-subject:v1\0" + legacy_instance_key + "\0" + legacy_profile_key
            ).encode("utf-8")
        )
        router = store.conn.execute(
            "SELECT * FROM router_instances WHERE instance_key = ?", (legacy_instance_key,)
        ).fetchone()
        assert router is not None
        assert dict(router)["canonical_vendor"] == "netgear"
        firmware = store.conn.execute(
            "SELECT * FROM router_firmware_profiles WHERE profile_key = ?", (legacy_profile_key,)
        ).fetchone()
        assert firmware is not None
        assert firmware["normalized_firmware"] == "unknown-legacy-firmware"

        migrated_run = store.conn.execute("SELECT * FROM runs WHERE id = 15").fetchone()
        assert migrated_run is not None
        assert migrated_run["router_instance_id"] == router["id"]
        assert migrated_run["format_id"] == "netgear"
        assert json.loads(migrated_run["capabilities_json"])["coverage_mode"] == "continuous_log"
        assert migrated_run["novel_event_count"] == 0
        assert migrated_run["repeated_event_count"] == 0

        assert store.conn.execute(
            "SELECT COUNT(*) FROM behavior_subjects WHERE subject_key = ? AND subject_type = 'router'",
            (legacy_subject_key,),
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM subject_behavior_daily_stats "
            "WHERE id = 21 AND subject_key = ? AND subject_type = 'router'",
            (legacy_subject_key,),
        ).fetchone()[0] == 1
        assert store.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert store.conn.execute("SELECT note FROM synthetic_user_notes").fetchone()[0] == (
            "synthetic retained note"
        )
    finally:
        store.close()

    reopened = analyzer.StateStore(db_path)
    try:
        assert reopened.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert reopened.conn.execute("SELECT COUNT(*) FROM router_instances").fetchone()[0] == 1
    finally:
        reopened.close()


@pytest.mark.parametrize(
    ("mutation", "expected_detail"),
    [
        ("below", "schema version 2 is unsupported"),
        ("above", "schema version 5 is unsupported"),
        ("missing_version", "schema_version is missing"),
        ("malformed", "required index 'idx_runs_epoch_time' is missing"),
    ],
)
def test_unsupported_or_malformed_databases_fail_closed_without_mutation(
    tmp_path: Path,
    mutation: str,
    expected_detail: str,
) -> None:
    db_path = tmp_path / f"{mutation}.db"
    build_v3_database(db_path, populate=False)
    connection = sqlite3.connect(db_path)
    if mutation == "below":
        connection.execute("UPDATE metadata SET value = '2' WHERE key = 'schema_version'")
    elif mutation == "above":
        connection.execute("UPDATE metadata SET value = '5' WHERE key = 'schema_version'")
    elif mutation == "missing_version":
        connection.execute("DELETE FROM metadata WHERE key = 'schema_version'")
    else:
        connection.execute("DROP INDEX idx_runs_epoch_time")
    connection.commit()
    before_objects = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    before_journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    connection.close()

    with pytest.raises(RuntimeError, match=re.escape(expected_detail)):
        analyzer.StateStore(db_path)

    verification = sqlite3.connect(db_path)
    try:
        assert verification.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall() == before_objects
        assert verification.execute("PRAGMA journal_mode").fetchone()[0] == before_journal_mode
    finally:
        verification.close()
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()


def test_unsupported_stranded_wal_database_is_rejected_without_touching_any_artifact(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "unsupported-wal.db"
    store = analyzer.StateStore(db_path)
    store.close()
    strand_wal_commit(
        db_path,
        "UPDATE metadata SET value = '5' WHERE key = 'schema_version'",
    )
    before = database_artifact_state(db_path)
    assert set(before) == {"", "-wal", "-shm"}
    assert before[""][0][18:20] == b"\x02\x02"

    with pytest.raises(RuntimeError, match="schema version 5 is unsupported"):
        analyzer.StateStore(db_path)

    assert database_artifact_state(db_path) == before
    assert db_path.read_bytes()[18:20] == b"\x02\x02"


def test_unsupported_non_wal_database_preflight_preserves_exact_file_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "unsupported-delete-journal.db"
    build_v3_database(db_path, populate=False)
    connection = sqlite3.connect(db_path)
    connection.execute("UPDATE metadata SET value = '5' WHERE key = 'schema_version'")
    connection.commit()
    connection.close()
    before = database_artifact_state(db_path)
    assert set(before) == {""}
    assert before[""][0][18:20] == b"\x01\x01"

    with pytest.raises(RuntimeError, match="schema version 5 is unsupported"):
        analyzer.StateStore(db_path)

    assert database_artifact_state(db_path) == before


def test_valid_v4_with_stranded_wal_is_accepted(tmp_path: Path) -> None:
    db_path = tmp_path / "valid-v4-wal.db"
    store = analyzer.StateStore(db_path)
    store.conn.execute("CREATE TABLE synthetic_wal_notes(note TEXT NOT NULL)")
    store.commit()
    store.close()
    strand_wal_commit(
        db_path,
        "INSERT INTO synthetic_wal_notes VALUES('synthetic stranded WAL note')",
    )

    reopened = analyzer.StateStore(db_path)
    try:
        assert reopened.get_metadata("schema_version") == "4"
        assert reopened.conn.execute(
            "SELECT note FROM synthetic_wal_notes"
        ).fetchone()[0] == "synthetic stranded WAL note"
    finally:
        reopened.close()


def test_valid_v3_with_stranded_wal_is_preflighted_then_migrated(tmp_path: Path) -> None:
    db_path = tmp_path / "valid-v3-wal.db"
    build_v3_database(db_path, populate=False)
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE synthetic_wal_notes(note TEXT NOT NULL)")
    connection.commit()
    connection.close()
    strand_wal_commit(
        db_path,
        "INSERT INTO synthetic_wal_notes VALUES('synthetic pre-migration WAL note')",
    )

    migrated = analyzer.StateStore(db_path)
    try:
        assert migrated.get_metadata("schema_version") == "4"
        assert migrated.conn.execute(
            "SELECT note FROM synthetic_wal_notes"
        ).fetchone()[0] == "synthetic pre-migration WAL note"
        assert migrated.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        migrated.close()


def test_unsupported_v3_with_hot_journal_is_rejected_without_recovering_original(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "unsupported-hot-journal.db"
    build_v3_database(db_path, populate=False)
    connection = sqlite3.connect(db_path)
    connection.execute("UPDATE metadata SET value = '5' WHERE key = 'schema_version'")
    connection.commit()
    connection.close()
    strand_hot_journal(db_path, transient_schema_version=3)
    before = database_artifact_state(db_path)
    assert set(before) == {"", "-journal"}

    with pytest.raises(RuntimeError, match="schema version 5 is unsupported"):
        analyzer.StateStore(db_path)

    assert database_artifact_state(db_path) == before


def test_valid_v3_with_hot_journal_is_recovered_on_copy_then_migrated(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "valid-hot-journal.db"
    build_v3_database(db_path, populate=False)
    strand_hot_journal(db_path, transient_schema_version=5)

    migrated = analyzer.StateStore(db_path)
    try:
        assert migrated.get_metadata("schema_version") == "4"
        assert [
            tuple(row)
            for row in migrated.conn.execute(
                "SELECT DISTINCT substr(payload, 1, 1) "
                "FROM synthetic_hot_journal_pages"
            )
        ] == [("a",)]
        assert migrated.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        migrated.close()


def test_v4_missing_required_device_observation_uniqueness_fails_closed(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "malformed-v4.db"
    store = analyzer.StateStore(db_path)
    store.close()
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executescript(
        """
        ALTER TABLE device_observations RENAME TO malformed_device_observations;
        DROP INDEX idx_device_observations_mac_seen;
        CREATE TABLE device_observations (
          id INTEGER PRIMARY KEY,
          run_id INTEGER NOT NULL,
          mac TEXT NOT NULL,
          evidence_kind TEXT NOT NULL,
          seen_at TEXT NOT NULL,
          evidence_digest TEXT NOT NULL,
          attributes_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(run_id) REFERENCES runs(id),
          FOREIGN KEY(mac) REFERENCES devices(mac)
        );
        CREATE INDEX idx_device_observations_mac_seen
          ON device_observations(mac, seen_at, run_id);
        DROP TABLE malformed_device_observations;
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="device_observations.*unique"):
        analyzer.StateStore(db_path)


@pytest.mark.parametrize("spoof_kind", ["line_comment", "block_comment", "quoted_string"])
def test_v4_boot_anchor_check_cannot_be_spoofed_outside_sql_tokens(
    tmp_path: Path,
    spoof_kind: str,
) -> None:
    db_path = tmp_path / f"spoofed-check-{spoof_kind}.db"
    store = analyzer.StateStore(db_path)
    store.close()
    anchor_check = "CHECK(trusted_local_anchor IS NOT NULL OR adapter_boot_id IS NOT NULL),"

    def spoof_check(sql: str) -> str:
        assert anchor_check in sql
        if spoof_kind == "line_comment":
            return sql.replace(anchor_check, f"-- {anchor_check}\n", 1)
        if spoof_kind == "block_comment":
            return sql.replace(anchor_check, f"/* {anchor_check} */", 1)
        without_check = sql.replace(anchor_check, "", 1)
        return without_check.replace(
            "FOREIGN KEY(router_instance_id)",
            f"CONSTRAINT '{anchor_check[:-1].casefold()}' FOREIGN KEY(router_instance_id)",
            1,
        )

    rewrite_sqlite_schema_object(db_path, "router_boot_sessions", spoof_check)
    before = db_path.read_bytes()

    with pytest.raises(RuntimeError, match="router_boot_sessions.*CHECK"):
        analyzer.StateStore(db_path)

    assert db_path.read_bytes() == before
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()


def test_v4_boot_anchor_check_cannot_be_removed(tmp_path: Path) -> None:
    db_path = tmp_path / "missing-check.db"
    store = analyzer.StateStore(db_path)
    store.close()
    anchor_check = "CHECK(trusted_local_anchor IS NOT NULL OR adapter_boot_id IS NOT NULL),"
    rewrite_sqlite_schema_object(
        db_path,
        "router_boot_sessions",
        lambda sql: sql.replace(anchor_check, "", 1),
    )

    with pytest.raises(RuntimeError, match="router_boot_sessions.*CHECK"):
        analyzer.StateStore(db_path)


@pytest.mark.parametrize(
    "anchor_operand",
    [
        '"truſted_local_anchor"',
        '"trυsted_local_anchor"',
        '"trusted_locаl_anchor"',
        "'trusted_local_anchor'",
        '"trusted_local_anchor_missing"',
    ],
)
def test_v4_boot_anchor_check_rejects_unicode_confusables_and_string_substitutions(
    tmp_path: Path,
    anchor_operand: str,
) -> None:
    db_path = tmp_path / "confusable-anchor-check.db"
    store = analyzer.StateStore(db_path)
    store.close()
    rewrite_sqlite_schema_object(
        db_path,
        "router_boot_sessions",
        lambda sql: sql.replace(
            "trusted_local_anchor IS NOT NULL",
            f"{anchor_operand} IS NOT NULL",
            1,
        ),
    )
    before = database_artifact_state(db_path)

    with pytest.raises(RuntimeError, match="router_boot_sessions"):
        unexpected_store = analyzer.StateStore(db_path)
        try:
            router_id = unexpected_store.get_or_create_legacy_netgear_router_instance()
            unexpected_store.conn.execute(
                """
                INSERT INTO router_boot_sessions(
                  router_instance_id, session_key, trusted_local_anchor,
                  adapter_boot_id, startup_signature, identity_version, created_at
                ) VALUES(
                  ?, 'synthetic-anchorless-session', NULL, NULL,
                  'synthetic-startup-signature', 'router-boot-session:v1', ?
                )
                """,
                (router_id, "2037-01-01T00:00:00Z"),
            )
        finally:
            unexpected_store.close()

    assert database_artifact_state(db_path) == before
    read_only = sqlite3.connect(
        f"file:{db_path}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        assert read_only.execute(
            "SELECT COUNT(*) FROM router_boot_sessions"
        ).fetchone()[0] == 0
    finally:
        read_only.close()


def test_v4_boot_anchor_check_rejects_double_quoted_null_keyword(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "quoted-null-check.db"
    store = analyzer.StateStore(db_path)
    store.close()
    original_check = (
        "CHECK(trusted_local_anchor IS NOT NULL OR adapter_boot_id IS NOT NULL)"
    )
    rewrite_sqlite_schema_object(
        db_path,
        "router_boot_sessions",
        lambda sql: sql.replace(
            original_check,
            original_check.replace("NULL", '"NULL"', 1),
            1,
        ),
    )
    before = database_artifact_state(db_path)

    with pytest.raises(RuntimeError, match="router_boot_sessions.*CHECK"):
        unexpected_store = analyzer.StateStore(db_path)
        try:
            router_id = unexpected_store.get_or_create_legacy_netgear_router_instance()
            unexpected_store.conn.execute(
                """
                INSERT INTO router_boot_sessions(
                  router_instance_id, session_key, trusted_local_anchor,
                  adapter_boot_id, startup_signature, identity_version, created_at
                ) VALUES(
                  ?, 'synthetic-quoted-null-session', NULL, NULL,
                  'synthetic-startup-signature', 'router-boot-session:v1', ?
                )
                """,
                (router_id, "2037-01-01T00:00:00Z"),
            )
        finally:
            unexpected_store.close()

    assert database_artifact_state(db_path) == before


@pytest.mark.parametrize(
    ("sql_token", "substitution"),
    [
        ("CHECK", '"CHECK"'),
        ("IS", '"IS"'),
        ("NOT", '"NOT"'),
        ("OR", '"OR"'),
        ("NULL", "'NULL'"),
        ("OR", "'OR'"),
    ],
)
def test_v4_boot_anchor_check_rejects_quoted_keyword_or_literal_substitution(
    tmp_path: Path,
    sql_token: str,
    substitution: str,
) -> None:
    db_path = tmp_path / "quoted-keyword-check.db"
    store = analyzer.StateStore(db_path)
    store.close()
    original_check = (
        "CHECK(trusted_local_anchor IS NOT NULL OR adapter_boot_id IS NOT NULL)"
    )
    rewritten_check = original_check.replace(sql_token, substitution, 1)
    rewrite_sqlite_schema_object(
        db_path,
        "router_boot_sessions",
        lambda sql: sql.replace(original_check, rewritten_check, 1),
    )
    before = database_artifact_state(db_path)

    with pytest.raises(RuntimeError):
        analyzer.StateStore(db_path)

    assert database_artifact_state(db_path) == before


@pytest.mark.parametrize(
    "foreign_key_suffix",
    [
        " DEFERRABLE",
        " DEFERRABLE INITIALLY DEFERRED",
        " NOT DEFERRABLE INITIALLY IMMEDIATE",
        " ON DELETE CASCADE",
    ],
)
def test_v4_foreign_key_sql_rejects_action_or_deferrability_changes(
    tmp_path: Path,
    foreign_key_suffix: str,
) -> None:
    db_path = tmp_path / "altered-foreign-key.db"
    store = analyzer.StateStore(db_path)
    store.close()
    original_foreign_key = (
        "FOREIGN KEY(router_instance_id) REFERENCES router_instances(id)"
    )
    rewrite_sqlite_schema_object(
        db_path,
        "router_boot_sessions",
        lambda sql: sql.replace(
            original_foreign_key,
            original_foreign_key + foreign_key_suffix,
            1,
        ),
    )
    before = db_path.read_bytes()

    with pytest.raises(RuntimeError, match="router_boot_sessions.*foreign-key"):
        analyzer.StateStore(db_path)

    assert db_path.read_bytes() == before
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()


def test_v4_constraint_sql_accepts_safe_formatting_and_identifier_quoting(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "formatted-constraints.db"
    store = analyzer.StateStore(db_path)
    store.close()

    def reformat_constraints(sql: str) -> str:
        return sql.replace(
            "CHECK(trusted_local_anchor IS NOT NULL OR adapter_boot_id IS NOT NULL)",
            'CHECK ( "TRUSTED_LOCAL_ANCHOR" is not null OR [ADAPTER_BOOT_ID] is not null )',
            1,
        ).replace(
            "FOREIGN KEY(router_instance_id) REFERENCES router_instances(id)",
            'foreign key ( "router_instance_id" ) references [router_instances] ( "id" )',
            1,
        )

    rewrite_sqlite_schema_object(db_path, "router_boot_sessions", reformat_constraints)

    reopened = analyzer.StateStore(db_path)
    try:
        assert reopened.get_metadata("schema_version") == "4"
    finally:
        reopened.close()


def test_v4_index_sql_accepts_safe_formatting_and_identifier_quoting(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "formatted-index.db"
    store = analyzer.StateStore(db_path)
    store.close()
    rewrite_sqlite_schema_object(
        db_path,
        "idx_router_snapshot_history",
        lambda _sql: (
            'create index "idx_router_snapshot_history" '
            'on [router_snapshot_metrics]('
            '"router_instance_id", [epoch_id], "export_timestamp" desc, run_id DESC)'
        ),
    )

    reopened = analyzer.StateStore(db_path)
    try:
        assert reopened.get_metadata("schema_version") == "4"
    finally:
        reopened.close()


def test_v3_missing_required_runs_not_null_constraint_fails_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "malformed-v3.db"
    build_v3_database(db_path, populate=False)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("PRAGMA legacy_alter_table = ON")
    connection.executescript(
        """
        ALTER TABLE runs RENAME TO malformed_runs;
        DROP INDEX idx_runs_epoch_time;
        CREATE TABLE runs (
          id INTEGER PRIMARY KEY,
          epoch_id INTEGER NOT NULL,
          policy_profile_id INTEGER,
          file_hash TEXT UNIQUE,
          source_path TEXT,
          ingested_at TEXT NOT NULL,
          observation_start TEXT,
          observation_end TEXT,
          observed_dates_json TEXT,
          parsed_event_count INTEGER NOT NULL DEFAULT 0,
          malformed_line_count INTEGER NOT NULL DEFAULT 0,
          export_noise_line_count INTEGER NOT NULL DEFAULT 0,
          risk_score INTEGER,
          status TEXT,
          is_partial INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id),
          FOREIGN KEY(policy_profile_id) REFERENCES policy_profiles(id)
        );
        CREATE INDEX idx_runs_epoch_time ON runs(epoch_id, ingested_at);
        DROP TABLE malformed_runs;
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="runs.*NOT NULL"):
        analyzer.StateStore(db_path)


def test_v3_primary_key_cannot_be_replaced_by_an_ordinary_unique_key(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "malformed-primary-key-v3.db"
    build_v3_database(db_path, populate=False)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("PRAGMA legacy_alter_table = ON")
    connection.executescript(
        """
        ALTER TABLE baseline_epochs RENAME TO malformed_baseline_epochs;
        DROP INDEX idx_baseline_epochs_active;
        CREATE TABLE baseline_epochs (
          id INTEGER UNIQUE,
          created_at TEXT NOT NULL,
          source_path TEXT,
          source_hash TEXT,
          label TEXT,
          is_active INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_baseline_epochs_active ON baseline_epochs(is_active);
        DROP TABLE malformed_baseline_epochs;
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="baseline_epochs.*primary-key"):
        analyzer.StateStore(db_path)


def test_v3_trigger_on_required_table_is_rejected_before_it_can_mutate_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "triggered-v3.db"
    build_v3_database(db_path)
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TRIGGER mutate_devices_during_migration
        AFTER UPDATE ON devices
        BEGIN
          UPDATE devices SET name = 'TRIGGER MUTATED VALUE' WHERE mac = NEW.mac;
        END;
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="trigger.*required table"):
        analyzer.StateStore(db_path)

    verification = sqlite3.connect(db_path)
    try:
        assert verification.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0] == "3"
        assert verification.execute(
            "SELECT name FROM devices WHERE mac = '02:00:00:00:00:04'"
        ).fetchone()[0] == "SYNTHETIC OBSERVED DEVICE"
    finally:
        verification.close()


@pytest.mark.parametrize(
    "malformation",
    ["type", "default", "check", "fk_action", "unique_collation"],
)
def test_v3_runs_requires_exact_declared_structure(
    tmp_path: Path,
    malformation: str,
) -> None:
    db_path = tmp_path / f"malformed-runs-{malformation}.db"
    build_v3_database(db_path, populate=False)
    file_hash_type = "BLOB" if malformation == "type" else "TEXT"
    parsed_default = "7" if malformation == "default" else "0"
    check_clause = ", CHECK(parsed_event_count >= 0)" if malformation == "check" else ""
    epoch_fk_action = " ON DELETE CASCADE" if malformation == "fk_action" else ""
    file_hash_collation = " COLLATE NOCASE" if malformation == "unique_collation" else ""
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("PRAGMA legacy_alter_table = ON")
    connection.executescript(
        f"""
        ALTER TABLE runs RENAME TO malformed_runs;
        DROP INDEX idx_runs_epoch_time;
        CREATE TABLE runs (
          id INTEGER PRIMARY KEY,
          epoch_id INTEGER NOT NULL,
          policy_profile_id INTEGER,
          file_hash {file_hash_type}{file_hash_collation} NOT NULL UNIQUE,
          source_path TEXT,
          ingested_at TEXT NOT NULL,
          observation_start TEXT,
          observation_end TEXT,
          observed_dates_json TEXT,
          parsed_event_count INTEGER NOT NULL DEFAULT {parsed_default},
          malformed_line_count INTEGER NOT NULL DEFAULT 0,
          export_noise_line_count INTEGER NOT NULL DEFAULT 0,
          risk_score INTEGER,
          status TEXT,
          is_partial INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id){epoch_fk_action},
          FOREIGN KEY(policy_profile_id) REFERENCES policy_profiles(id)
          {check_clause}
        );
        CREATE INDEX idx_runs_epoch_time ON runs(epoch_id, ingested_at);
        DROP TABLE malformed_runs;
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(
        RuntimeError,
        match="runs.*(type|default|CHECK|foreign-key|unique)",
    ):
        analyzer.StateStore(db_path)


def test_v3_migration_validation_failure_rolls_back_to_usable_v3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "network.db"
    build_v3_database(db_path)

    def reject_migration(_store: analyzer.StateStore) -> None:
        raise RuntimeError("injected post-rebuild validation failure")

    monkeypatch.setattr(
        analyzer.StateStore,
        "_validate_migrated_v4_before_version_update",
        reject_migration,
    )
    with pytest.raises(RuntimeError, match="injected post-rebuild validation failure"):
        analyzer.StateStore(db_path)

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0] == "3"
        assert [
            row[1] for row in connection.execute("PRAGMA table_info('runs')")
        ] == list(analyzer.V3_REQUIRED_COLUMNS["runs"])
        assert connection.execute("SELECT id, file_hash FROM runs").fetchall() == [
            (15, "synthetic-run-hash")
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM network_incidents WHERE run_id = 15"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'router_instances'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_schema_creation_keyboard_interrupt_closes_connection_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "interrupted-create.db"
    opened_connections: list[sqlite3.Connection] = []
    original_open = analyzer.StateStore._open_connection
    original_validate = analyzer.StateStore._validate_schema

    def capture_open(database: str) -> sqlite3.Connection:
        connection = original_open(database)
        opened_connections.append(connection)
        return connection

    def interrupt_validation(_store: analyzer.StateStore, _version: int) -> None:
        raise KeyboardInterrupt("synthetic schema creation interruption")

    monkeypatch.setattr(
        analyzer.StateStore,
        "_open_connection",
        staticmethod(capture_open),
    )
    monkeypatch.setattr(analyzer.StateStore, "_validate_schema", interrupt_validation)

    with pytest.raises(KeyboardInterrupt, match="synthetic schema creation interruption"):
        analyzer.StateStore(db_path)

    assert opened_connections
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        opened_connections[-1].execute("SELECT 1")

    monkeypatch.setattr(analyzer.StateStore, "_validate_schema", original_validate)
    recovered = analyzer.StateStore(db_path)
    try:
        assert recovered.get_metadata("schema_version") == "4"
    finally:
        recovered.close()


def test_schema_migration_keyboard_interrupt_closes_connection_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "interrupted-migration.db"
    build_v3_database(db_path)
    opened_connections: list[sqlite3.Connection] = []
    original_open = analyzer.StateStore._open_connection
    original_hook = analyzer.StateStore._validate_migrated_v4_before_version_update

    def capture_open(database: str) -> sqlite3.Connection:
        connection = original_open(database)
        opened_connections.append(connection)
        return connection

    def interrupt_migration(_store: analyzer.StateStore) -> None:
        raise KeyboardInterrupt("synthetic schema migration interruption")

    monkeypatch.setattr(
        analyzer.StateStore,
        "_open_connection",
        staticmethod(capture_open),
    )
    monkeypatch.setattr(
        analyzer.StateStore,
        "_validate_migrated_v4_before_version_update",
        interrupt_migration,
    )

    with pytest.raises(KeyboardInterrupt, match="synthetic schema migration interruption"):
        analyzer.StateStore(db_path)

    assert opened_connections
    for connection in opened_connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")

    monkeypatch.setattr(
        analyzer.StateStore,
        "_validate_migrated_v4_before_version_update",
        original_hook,
    )
    recovered = analyzer.StateStore(db_path)
    try:
        assert recovered.get_metadata("schema_version") == "4"
        assert recovered.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        recovered.close()


def test_v3_migration_backfills_registration_and_observation_provenance(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "network.db"
    build_v3_database(db_path)

    store = analyzer.StateStore(db_path)
    try:
        registrations = {
            row["mac"]: dict(row)
            for row in store.conn.execute(
                "SELECT * FROM device_registrations ORDER BY registration_sequence"
            )
        }
        assert registrations["02:00:00:00:00:01"]["registration_source"] == (
            "legacy_baseline_registration"
        )
        assert registrations["02:00:00:00:00:01"]["epoch_id"] == 11
        config_registration = registrations["02:00:00:00:00:02"]
        assert config_registration["registration_source"] == "legacy_config_registration"
        assert config_registration["source_key"] == (
            "legacy-config-without-source-bytes:v1:02:00:00:00:00:02"
        )
        assert "hash" not in config_registration["source_key"]
        assert config_registration["registered_status"] == "blocked"
        assert registrations["02:00:00:00:00:03"]["registration_source"] == (
            "legacy_device_catalog"
        )
        observed_catalog_registration = registrations["02:00:00:00:00:04"]
        assert observed_catalog_registration["registration_source"] == "legacy_device_catalog"
        assert observed_catalog_registration["registered_name"] == "SYNTHETIC OBSERVED DEVICE"
        assert observed_catalog_registration["registered_status"] == "allowed"
        assert observed_catalog_registration["registered_connection_type"] == "wired"
        assert observed_catalog_registration["first_seen"] is None
        assert observed_catalog_registration["last_seen"] is None

        observations = [
            dict(row)
            for row in store.conn.execute(
                """
                SELECT * FROM device_observations
                WHERE evidence_kind LIKE 'legacy_device_daily_%'
                ORDER BY seen_at
                """
            )
        ]
        assert [row["seen_at"] for row in observations] == [
            "2037-02-01T12:01:00",
            "2037-02-01T12:29:00",
        ]
        assert [row["evidence_kind"] for row in observations] == [
            "legacy_device_daily_first_seen",
            "legacy_device_daily_last_seen",
        ]
        assert {row["run_id"] for row in observations} == {15}
        assert {row["mac"] for row in observations} == {"02:00:00:00:00:04"}
        assert store.conn.execute(
            "SELECT COUNT(*) FROM device_daily_stats WHERE mac = '__SYSTEM__'"
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM device_observations WHERE mac = '__SYSTEM__'"
        ).fetchone()[0] == 0
        observed_device = store.conn.execute(
            "SELECT first_seen, last_seen FROM devices WHERE mac = '02:00:00:00:00:04'"
        ).fetchone()
        assert tuple(observed_device) == (
            "2037-02-01T12:01:00",
            "2037-02-01T12:29:00",
        )
    finally:
        store.close()


def test_v3_migration_derives_caches_without_assigning_catalog_fields_to_baseline(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "network.db"
    build_v3_database(db_path)
    connection = sqlite3.connect(db_path)
    connection.execute("UPDATE baseline_seed_devices SET name = NULL WHERE id = 12")
    connection.execute(
        """
        UPDATE devices
        SET name = 'SYNTHETIC RETAINED CATALOG NAME', connection_type = 'wifi',
            first_seen = '2030-01-01T00:00:00', last_seen = '2040-01-01T00:00:00'
        WHERE mac = '02:00:00:00:00:01'
        """
    )
    connection.execute(
        """
        UPDATE devices
        SET first_seen = '2030-01-01T00:00:00', last_seen = '2040-01-01T00:00:00'
        WHERE mac = '02:00:00:00:00:04'
        """
    )
    connection.execute(
        """
        UPDATE behavior_subjects
        SET first_seen = '2030-01-01T00:00:00', last_seen = '2040-01-01T00:00:00'
        WHERE subject_key = '__SYSTEM__'
        """
    )
    connection.execute(
        """
        UPDATE behavior_subjects
        SET first_seen = '2030-01-01T00:00:00', last_seen = '2040-01-01T00:00:00'
        WHERE subject_key = '02:00:00:00:00:04'
        """
    )
    connection.execute(
        """
        UPDATE subject_behavior_daily_stats
        SET first_seen = NULL, last_seen = NULL
        WHERE subject_key = '02:00:00:00:00:04'
        """
    )
    connection.commit()
    connection.close()

    store = analyzer.StateStore(db_path)
    try:
        baseline_registration = store.conn.execute(
            """
            SELECT * FROM device_registrations
            WHERE mac = '02:00:00:00:00:01'
              AND registration_source = 'legacy_baseline_registration'
            """
        ).fetchone()
        assert baseline_registration["registered_name"] is None
        assert baseline_registration["registered_connection_type"] is None
        catalog_registration = store.conn.execute(
            """
            SELECT * FROM device_registrations
            WHERE mac = '02:00:00:00:00:01'
              AND registration_source = 'legacy_device_catalog'
            """
        ).fetchone()
        assert catalog_registration["registered_name"] == "SYNTHETIC RETAINED CATALOG NAME"
        assert catalog_registration["registered_connection_type"] == "wifi"
        assert catalog_registration["first_seen"] is None
        assert catalog_registration["last_seen"] is None
        migrated_baseline_device = store.conn.execute(
            """
            SELECT name, status, connection_type, first_seen, last_seen
            FROM devices WHERE mac = '02:00:00:00:00:01'
            """
        ).fetchone()
        assert tuple(migrated_baseline_device) == (
            "SYNTHETIC RETAINED CATALOG NAME",
            "allowed",
            "wifi",
            "2037-01-01T00:00:00Z",
            "2037-01-01T00:00:00Z",
        )
        migrated_observed_extrema = store.conn.execute(
            """
            SELECT first_seen, last_seen FROM devices
            WHERE mac = '02:00:00:00:00:04'
            """
        ).fetchone()
        assert tuple(migrated_observed_extrema) == (
            "2037-02-01T12:01:00",
            "2037-02-01T12:29:00",
        )
        router_subject = store.conn.execute(
            """
            SELECT first_seen, last_seen FROM behavior_subjects
            WHERE subject_type = 'router'
            """
        ).fetchone()
        assert tuple(router_subject) == (
            "2037-02-01T12:00:00",
            "2037-02-01T12:30:00",
        )
        device_subject = store.conn.execute(
            """
            SELECT first_seen, last_seen FROM behavior_subjects
            WHERE subject_key = '02:00:00:00:00:04' AND subject_type = 'device'
            """
        ).fetchone()
        assert tuple(device_subject) == (None, None)
    finally:
        store.close()


def test_v3_migration_router_extrema_use_ingestion_only_without_observation_endpoints(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "network.db"
    build_v3_database(db_path)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        UPDATE runs
        SET observation_start = NULL,
            observation_end = '2037-02-01T12:30:00',
            ingested_at = '2037-02-01T13:00:00Z'
        WHERE id = 15
        """
    )
    connection.commit()
    connection.close()

    store = analyzer.StateStore(db_path)
    try:
        extrema = store.conn.execute(
            """
            SELECT first_seen, last_seen FROM router_instances
            WHERE instance_key = ?
            """,
            (analyzer.LEGACY_NETGEAR_INSTANCE_KEY,),
        ).fetchone()
        assert tuple(extrema) == (
            "2037-02-01T12:30:00",
            "2037-02-01T12:30:00",
        )
    finally:
        store.close()


def test_v3_migration_registers_an_attribute_free_real_mac_catalog_row(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "network.db"
    build_v3_database(db_path)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        UPDATE devices
        SET name = NULL, status = NULL, connection_type = NULL,
            first_seen = NULL, last_seen = NULL
        WHERE mac = '02:00:00:00:00:03'
        """
    )
    connection.commit()
    connection.close()

    store = analyzer.StateStore(db_path)
    try:
        registration = store.conn.execute(
            """
            SELECT * FROM device_registrations
            WHERE mac = '02:00:00:00:00:03'
            """
        ).fetchone()
        assert registration is not None
        assert registration["registration_source"] == "legacy_device_catalog"
        assert registration["source_key"] == (
            "legacy-device-catalog:v1:02:00:00:00:00:03"
        )
        assert registration["registered_name"] is None
        assert registration["registered_status"] is None
        assert registration["registered_connection_type"] is None
        assert registration["first_seen"] is None
        assert registration["last_seen"] is None
        assert store.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        store.close()


@pytest.mark.parametrize(
    ("first_seen", "last_seen", "expected_kind", "expected_seen_at"),
    [
        (None, None, None, None),
        (
            "2037-02-01T12:05:00",
            None,
            "legacy_device_daily_first_seen",
            "2037-02-01T12:05:00",
        ),
        (
            None,
            "2037-02-01T12:25:00",
            "legacy_device_daily_last_seen",
            "2037-02-01T12:25:00",
        ),
    ],
)
def test_v3_migration_handles_attribute_free_daily_device_nullable_extrema(
    tmp_path: Path,
    first_seen: str | None,
    last_seen: str | None,
    expected_kind: str | None,
    expected_seen_at: str | None,
) -> None:
    db_path = tmp_path / "network.db"
    build_v3_database(db_path)
    mac = "02:00:00:00:00:05"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        INSERT INTO devices(
          mac, name, status, connection_type, source, first_seen, last_seen
        ) VALUES(?, NULL, NULL, NULL, 'observed', NULL, NULL)
        """,
        (mac,),
    )
    connection.execute(
        """
        INSERT INTO device_daily_stats(
          id, run_id, epoch_id, observed_date, mac, dhcp_count, total_events,
          first_seen, last_seen, event_types_json, active_hours_json,
          included_in_learning, exclusion_reason
        ) VALUES(23, 15, 11, '2037-02-01', ?, 0, 0, ?, ?, '{}', '[]', 1, NULL)
        """,
        (mac, first_seen, last_seen),
    )
    connection.commit()
    connection.close()

    store = analyzer.StateStore(db_path)
    try:
        registration = store.conn.execute(
            "SELECT * FROM device_registrations WHERE mac = ?",
            (mac,),
        ).fetchone()
        observations = list(store.conn.execute(
            """
            SELECT evidence_kind, seen_at FROM device_observations
            WHERE mac = ? ORDER BY evidence_kind
            """,
            (mac,),
        ))
        if expected_kind is None:
            assert registration is not None
            assert registration["registration_source"] == "legacy_device_catalog"
            assert registration["source_key"] == f"legacy-device-catalog:v1:{mac}"
            assert observations == []
        else:
            assert registration is None
            assert [tuple(row) for row in observations] == [
                (expected_kind, expected_seen_at)
            ]
        device_extrema = store.conn.execute(
            "SELECT first_seen, last_seen FROM devices WHERE mac = ?",
            (mac,),
        ).fetchone()
        assert tuple(device_extrema) == (expected_seen_at, expected_seen_at)
        assert store.conn.execute(
            "SELECT id FROM device_daily_stats WHERE id = 23"
        ).fetchone()[0] == 23
        assert store.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        store.close()


def test_v3_migration_materializes_seed_registration_missing_from_device_cache(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "missing-seed-cache.db"
    build_v3_database(db_path)
    mac = "02:00:00:00:00:31"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        INSERT INTO baseline_seed_devices(
          id, epoch_id, mac, name, dhcp_min, dhcp_max, dhcp_seed_weight,
          total_events_min, total_events_max, total_events_seed_weight,
          active_hours_json, expected_windows_json, expected_events_json,
          pattern, soft_max
        ) VALUES(
          31, 11, ?, 'SYNTHETIC SEED WITHOUT CACHE', 0, 1, 4,
          0, 2, 4, '[]', '[]', '{}', NULL, NULL
        )
        """,
        (mac,),
    )
    connection.commit()
    connection.close()

    store = analyzer.StateStore(db_path)
    try:
        snapshot = store.load_devices_snapshot()
        assert snapshot[mac]["name"] == "SYNTHETIC SEED WITHOUT CACHE"
        assert snapshot[mac]["status"] == "allowed"
        assert store.conn.execute(
            "SELECT source FROM devices WHERE mac = ?",
            (mac,),
        ).fetchone()[0] == "legacy_baseline_registration"
        assert store.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        store.close()


def test_migrated_system_daily_rows_remain_auditable_but_not_device_history(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "network.db"
    build_v3_database(db_path)
    store = analyzer.StateStore(db_path)
    try:
        assert store.conn.execute(
            "SELECT COUNT(*) FROM device_daily_stats WHERE mac = '__SYSTEM__'"
        ).fetchone()[0] == 1
        assert analyzer.SYSTEM_ACTOR not in store.fetch_epoch_macs(11)
    finally:
        store.close()


def test_v4_run_owned_foreign_keys_and_unique_keys_reference_final_runs(
    tmp_path: Path,
) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        run_owned_tables = (
            "network_incidents",
            "device_daily_stats",
            "device_event_daily_stats",
            "subject_behavior_daily_stats",
            "device_observations",
            "router_metadata_observations",
            "router_snapshot_metrics",
            "run_router_boot_sessions",
            "run_event_occurrences",
        )
        for table in run_owned_tables:
            run_targets = {
                (row[3], row[2], row[4])
                for row in store.conn.execute(f'PRAGMA foreign_key_list("{table}")')
                if row[3] == "run_id"
            }
            assert run_targets == {("run_id", "runs", "id")}
            sql = store.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()[0]
            assert "runs_v4" not in sql
            assert "runs_temp" not in sql

        assert [
            (row[1], row[5])
            for row in store.conn.execute("PRAGMA table_info('router_metadata_observations')")
            if row[5]
        ] == [("run_id", 1)]
        assert [
            (row[1], row[5])
            for row in store.conn.execute("PRAGMA table_info('router_snapshot_metrics')")
            if row[5]
        ] == [("run_id", 1)]
        assert [
            (row[1], row[5])
            for row in store.conn.execute("PRAGMA table_info('run_router_boot_sessions')")
            if row[5]
        ] == [("run_id", 1), ("boot_session_id", 2)]
        assert [
            (row[1], row[5])
            for row in store.conn.execute("PRAGMA table_info('run_event_occurrences')")
            if row[5]
        ] == [("run_id", 1), ("occurrence_id", 2)]
        assert store.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        store.close()


def test_v4_rejects_run_owned_rows_with_mismatched_router_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "mismatched-router.db"
    store = analyzer.StateStore(db_path)
    try:
        epoch_id = seed_epoch(store)
        run_id = store.insert_run(
            epoch_id=epoch_id,
            policy_profile_id=None,
            file_hash="synthetic-run",
            source_path=Path("/synthetic/router.log"),
            parse_stats=analyzer.ParseStats(),
            observation_start=None,
            observation_end=None,
            observed_dates=[],
            risk_score=0,
            status="Clean",
            is_partial=False,
        )
        second_router_id = store.conn.execute(
            """
            INSERT INTO router_instances(
              instance_key, canonical_vendor, identity_source, label, identity_version
            ) VALUES('synthetic-mismatch', 'netgear', 'test', 'Synthetic mismatch', 'v1')
            """
        ).lastrowid
        store.conn.execute(
            "UPDATE router_metadata_observations SET router_instance_id = ? WHERE run_id = ?",
            (second_router_id, run_id),
        )
        store.conn.commit()
    finally:
        store.close()

    with pytest.raises(RuntimeError, match="router_metadata_observations.*run identity"):
        analyzer.StateStore(db_path)


def test_migrated_runs_allow_same_file_hash_for_different_router_instances(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "network.db"
    build_v3_database(db_path)
    store = analyzer.StateStore(db_path)
    try:
        legacy_router_id = store.conn.execute(
            "SELECT router_instance_id FROM runs WHERE id = 15"
        ).fetchone()[0]
        second_router_id = store.conn.execute(
            """
            INSERT INTO router_instances(
              instance_key, canonical_vendor, identity_source, label, identity_version
            ) VALUES('synthetic-second-instance', 'netgear', 'test', 'Synthetic Router', 'v1')
            """
        ).lastrowid
        second_run_id = store.insert_run(
            epoch_id=11,
            policy_profile_id=14,
            router_instance_id=second_router_id,
            format_id="netgear",
            file_hash="synthetic-run-hash",
            source_path=Path("/synthetic/router-copy.log"),
            parse_stats=analyzer.ParseStats(),
            observation_start=None,
            observation_end=None,
            observed_dates=[],
            risk_score=0,
            status="Clean",
            is_partial=False,
        )
        assert second_run_id != 15
        with pytest.raises(sqlite3.IntegrityError):
            store.insert_run(
                epoch_id=11,
                policy_profile_id=14,
                router_instance_id=legacy_router_id,
                format_id="netgear",
                file_hash="synthetic-run-hash",
                source_path=Path("/synthetic/router-duplicate.log"),
                parse_stats=analyzer.ParseStats(),
                observation_start=None,
                observation_end=None,
                observed_dates=[],
                risk_score=0,
                status="Clean",
                is_partial=False,
            )
    finally:
        store.close()


def test_run_hash_lookup_requires_router_scope(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        with pytest.raises(TypeError):
            store.get_run_by_hash("synthetic-hash")
    finally:
        store.close()


def test_netgear_insert_run_refreshes_router_cache_by_chronological_extrema(
    tmp_path: Path,
) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        router_id = store.get_or_create_legacy_netgear_router_instance()
        for file_hash, start, end in (
            ("synthetic-later", "2037-04-02T12:00:00", "2037-04-02T13:00:00"),
            ("synthetic-earlier", "2037-04-01T12:00:00", "2037-04-01T13:00:00"),
        ):
            store.insert_run(
                epoch_id=epoch_id,
                policy_profile_id=None,
                router_instance_id=router_id,
                format_id="netgear",
                file_hash=file_hash,
                source_path=Path(f"/synthetic/{file_hash}.log"),
                parse_stats=analyzer.ParseStats(),
                observation_start=start,
                observation_end=end,
                observed_dates=[start[:10]],
                risk_score=0,
                status="Clean",
                is_partial=False,
            )
        router = store.conn.execute(
            "SELECT first_seen, last_seen FROM router_instances WHERE id = ?", (router_id,)
        ).fetchone()
        assert tuple(router) == ("2037-04-01T12:00:00", "2037-04-02T13:00:00")
    finally:
        store.close()


def test_registration_resolution_is_fieldwise_idempotent_and_epoch_scoped(
    tmp_path: Path,
) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    config_v1_path = tmp_path / "synthetic-config-v1.md"
    config_v2_path = tmp_path / "synthetic-config-v2.md"
    baseline_path = tmp_path / "synthetic-baseline.json"
    config_v1_path.write_text("SYNTHETIC CONFIG VERSION ONE\n", encoding="utf-8")
    config_v2_path.write_text("SYNTHETIC CONFIG VERSION TWO\n", encoding="utf-8")
    baseline_path.write_text("{\"devices\":{}}\n", encoding="utf-8")
    mac = "02:00:00:00:00:21"
    config_v1 = {
        "devices": {
            mac: analyzer.RouterConfigDevice(
                name="SYNTHETIC CONFIG NAME",
                mac=mac,
                connection_type="wifi",
            )
        },
        "blocked_macs": {mac},
    }
    config_v2 = {
        "devices": {
            mac: analyzer.RouterConfigDevice(
                name="SYNTHETIC UPDATED NAME",
                mac=mac,
                connection_type=None,
            )
        },
        "blocked_macs": {mac},
    }
    baseline = {"devices": {mac: {"name": "SYNTHETIC BASELINE NAME"}}}
    try:
        assert store.import_config(
            config_v1_path,
            config_v1,
            source_digest=analyzer.sha256_bytes(config_v1_path.read_bytes()),
        ) == 1
        first_registration = store.conn.execute(
            "SELECT * FROM device_registrations WHERE mac = ?", (mac,)
        ).fetchone()
        assert first_registration is not None
        assert first_registration["source_key"] == analyzer.sha256_bytes(
            config_v1_path.read_bytes()
        )

        assert store.import_config(
            config_v1_path,
            config_v1,
            source_digest=analyzer.sha256_bytes(config_v1_path.read_bytes()),
        ) == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM device_registrations WHERE mac = ?", (mac,)
        ).fetchone()[0] == 1
        confirmed = store.conn.execute(
            "SELECT * FROM device_registrations WHERE mac = ?", (mac,)
        ).fetchone()
        assert confirmed["id"] == first_registration["id"]
        assert confirmed["registration_sequence"] == first_registration["registration_sequence"]

        store.import_config(
            config_v2_path,
            config_v2,
            source_digest=analyzer.sha256_bytes(config_v2_path.read_bytes()),
        )
        snapshot = store.load_devices_snapshot()[mac]
        assert snapshot["name"] == "SYNTHETIC UPDATED NAME"
        assert snapshot["status"] == "blocked"
        assert snapshot["connection_type"] == "wifi"

        first_epoch = store.import_baseline(baseline_path, baseline, seed_weight=4.0)
        snapshot = store.load_devices_snapshot()[mac]
        assert snapshot["name"] == "SYNTHETIC BASELINE NAME"
        assert snapshot["status"] == "allowed"
        assert snapshot["connection_type"] == "wifi"

        second_epoch = store.import_baseline(baseline_path, baseline, seed_weight=4.0)
        assert second_epoch != first_epoch
        baseline_registrations = list(store.conn.execute(
            """
            SELECT epoch_id, source_key
            FROM device_registrations
            WHERE mac = ? AND registration_source = 'baseline_import'
            ORDER BY registration_sequence
            """,
            (mac,),
        ))
        assert [row["epoch_id"] for row in baseline_registrations] == [
            first_epoch,
            second_epoch,
        ]
        assert len({row["source_key"] for row in baseline_registrations}) == 2
        assert store.load_devices_snapshot()[mac]["status"] == "allowed"
    finally:
        store.close()


def test_config_snapshot_parses_and_digests_the_same_single_byte_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "synthetic-router-security-config.md"
    first_payload = b"""\
| Device Name | MAC Address | Status | Connection Type |
| --- | --- | --- | --- |
| SYNTHETIC SNAPSHOT A | 02:00:00:00:00:41 | Allowed | WiFi |
"""
    later_payload = b"""\
| Device Name | MAC Address | Status | Connection Type |
| --- | --- | --- | --- |
| SYNTHETIC SNAPSHOT B | 02:00:00:00:00:41 | Blocked | Wired |
"""
    config_path.write_bytes(first_payload)
    original_read_bytes = Path.read_bytes
    reads = 0

    def changing_read_bytes(path: Path) -> bytes:
        nonlocal reads
        if path == config_path:
            reads += 1
            return first_payload if reads == 1 else later_payload
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", changing_read_bytes)

    router_config, source_digest = analyzer.load_router_security_config_snapshot(config_path)
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        assert store.import_config(
            config_path,
            router_config,
            source_digest=source_digest,
        ) == 1
        registration = store.conn.execute(
            "SELECT * FROM device_registrations WHERE mac = '02:00:00:00:00:41'"
        ).fetchone()
        assert registration["source_key"] == analyzer.sha256_bytes(first_payload)
        assert registration["registered_name"] == "SYNTHETIC SNAPSHOT A"
        assert registration["registered_status"] == "allowed"
        assert registration["registered_connection_type"] == "WiFi"
        assert reads == 1
    finally:
        store.close()


def test_weekday_drift_is_suppressed_without_enough_history(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:01"
        event_key = "WLAN_ACCESS_ALLOWED"
        event_family = "WLAN_ALLOWED"
        insert_history_day(
            store,
            epoch_id,
            "history-1",
            "2037-03-16",
            mac,
            event_key,
            event_family,
            ["2037-03-16T03:58:31"],
        )
        current_stat = make_current_stat(
            "2037-03-17",
            mac,
            event_key,
            event_family,
            ["2037-03-17T03:58:31"],
        )
        aggregate = {"event_day_stats": {("2037-03-17", mac, event_key): current_stat}}
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_event_behavior_anomalies(aggregate, store, epoch_id, policy)

        assert findings == []
    finally:
        store.close()


def test_main_reprocess_atomically_replaces_matching_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "network.db"
    log_path = tmp_path / "router.log"
    mac = "02:00:00:00:00:02"
    log_path.write_text(
        (
            "[DHCP IP: (192.0.2.10)] to MAC address "
            f"{mac}, Wednesday, July 15, 2037 12:00:00\n"
        ),
        encoding="utf-8",
    )
    store = analyzer.StateStore(db_path)
    try:
        seed_epoch(store)
        store.upsert_device(
            mac=mac,
            name="Known device",
            status="allowed",
            connection_type=None,
            source="test",
        )
        store.commit()
    finally:
        store.close()

    assert analyzer.main([str(log_path), "--db", str(db_path), "--json"]) == 0
    first_report = json.loads(capsys.readouterr().out)
    assert first_report["state"]["deduplicated"] is False
    assert first_report["state"]["reprocessed_run_id"] is None

    store = analyzer.StateStore(db_path)
    try:
        existing = store.get_run_by_hash(
            store.get_or_create_legacy_netgear_router_instance(),
            analyzer.sha256_bytes(log_path.read_bytes()),
        )
        assert existing is not None
        existing_run_id = int(existing["id"])
        store.conn.execute(
            "UPDATE runs SET risk_score = 99, status = 'Suspicious' WHERE id = ?",
            (existing_run_id,),
        )
        store.conn.execute(
            """
            INSERT INTO network_incidents(
              run_id, incident_id, incident_type, confidence, start, restored_at,
              recovery_end, disconnect_count, connect_count, affected_macs_json,
              event_counts_json, explained_event_count, active_known_devices,
              affected_device_fraction
            )
            VALUES(?, 'stale-incident', 'internet_connection_reset', 'confirmed',
                   '2037-07-15T12:00:00', '2037-07-15T12:00:01',
                   '2037-07-15T12:05:01', 1, 1, '[]', '{}', 2, 1, 0)
            """,
            (existing_run_id,),
        )
        store.commit()
    finally:
        store.close()

    assert analyzer.main(
        [str(log_path), "--db", str(db_path), "--json", "--reprocess"]
    ) == 0
    replacement_report = json.loads(capsys.readouterr().out)
    assert replacement_report["state"]["deduplicated"] is False
    assert replacement_report["state"]["reprocessed_run_id"] == existing_run_id
    assert replacement_report["risk_score"] != 99

    store = analyzer.StateStore(db_path)
    try:
        replacement = store.get_run_by_hash(
            store.get_or_create_legacy_netgear_router_instance(),
            analyzer.sha256_bytes(log_path.read_bytes()),
        )
        assert replacement is not None
        assert replacement["risk_score"] == replacement_report["risk_score"]
        assert replacement["status"] == replacement_report["status"]
        stale_incident_count = store.conn.execute(
            "SELECT COUNT(*) FROM network_incidents WHERE incident_id = 'stale-incident'"
        ).fetchone()[0]
        assert stale_incident_count == 0
        assert store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert store.conn.execute("SELECT COUNT(*) FROM device_daily_stats").fetchone()[0] == 1
        assert store.conn.execute("SELECT COUNT(*) FROM device_event_daily_stats").fetchone()[0] == 1
    finally:
        store.close()


def test_delete_run_rolls_back_with_the_surrounding_transaction(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        run_id = insert_history_day(
            store,
            epoch_id,
            "rollback-run",
            "2037-07-15",
            "02:00:00:00:00:02",
            "DHCP_IP",
            "DHCP",
            ["2037-07-15T12:00:00"],
        )

        assert store.delete_run(run_id) is True
        assert store.conn.execute(
            "SELECT COUNT(*) FROM device_daily_stats WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0] == 0
        store.conn.rollback()

        assert store.conn.execute(
            "SELECT COUNT(*) FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM device_daily_stats WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM device_event_daily_stats WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0] == 1
    finally:
        store.close()


def test_main_reprocess_rolls_back_when_analysis_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "network.db"
    log_path = tmp_path / "router.log"
    log_path.write_text(
        (
            "[DHCP IP: (192.0.2.10)] to MAC address "
            "02:00:00:00:00:02, Wednesday, July 15, 2037 12:00:00\n"
        ),
        encoding="utf-8",
    )
    store = analyzer.StateStore(db_path)
    try:
        seed_epoch(store)
    finally:
        store.close()

    assert analyzer.main([str(log_path), "--db", str(db_path), "--json"]) == 0
    capsys.readouterr()

    store = analyzer.StateStore(db_path)
    try:
        existing = store.get_run_by_hash(
            store.get_or_create_legacy_netgear_router_instance(),
            analyzer.sha256_bytes(log_path.read_bytes()),
        )
        assert existing is not None
        existing_run_id = int(existing["id"])
    finally:
        store.close()

    def fail_after_reprocess_delete(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("simulated analysis failure")

    monkeypatch.setattr(analyzer, "aggregate_events", fail_after_reprocess_delete)
    with pytest.raises(RuntimeError, match="simulated analysis failure"):
        analyzer.main([str(log_path), "--db", str(db_path), "--reprocess"])

    store = analyzer.StateStore(db_path)
    try:
        restored = store.get_run_by_hash(
            store.get_or_create_legacy_netgear_router_instance(),
            analyzer.sha256_bytes(log_path.read_bytes()),
        )
        assert restored is not None
        assert int(restored["id"]) == existing_run_id
        assert store.conn.execute(
            "SELECT COUNT(*) FROM device_daily_stats WHERE run_id = ?",
            (existing_run_id,),
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM device_event_daily_stats WHERE run_id = ?",
            (existing_run_id,),
        ).fetchone()[0] == 1
    finally:
        store.close()


def test_weekday_drift_appears_after_minimum_history(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:01"
        event_key = "WLAN_ACCESS_ALLOWED"
        event_family = "WLAN_ALLOWED"
        history_dates = ["2037-02-16", "2037-02-23", "2037-03-02", "2037-03-09"]
        for index, history_date in enumerate(history_dates, start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                event_key,
                event_family,
                [f"{history_date}T03:58:31"],
            )
        current_stat = make_current_stat(
            "2037-03-17",
            mac,
            event_key,
            event_family,
            ["2037-03-17T03:58:31"],
        )
        aggregate = {"event_day_stats": {("2037-03-17", mac, event_key): current_stat}}
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_event_behavior_anomalies(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].metadata["reasons"] == ["weekday drift"]
        assert findings[0].metadata["history_count"] == 4
        assert findings[0].metadata["dominant_weekdays"] == [0]
        assert findings[0].metadata["current_weekday"] == 1
    finally:
        store.close()


def test_timing_detail_lines_show_observed_and_expected_hours() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "timing_anomaly",
            "rendered_message": "Timing drift for SYNTHETIC COMPUTER on 2037-03-17: 1 hour outside the expected window.",
            "metadata": {
                "day": "2037-03-17",
                "hours": ["2037-03-17T10:43:39"],
                "expected_active_hours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 20, 21, 22, 23],
            },
        }
    )

    assert "Observed: 10:43:39 AM" in lines
    assert "Expected active hours: 12:00 AM-9:59 AM, 8:00 PM-11:59 PM" in lines


def test_event_behavior_detail_lines_show_observed_and_learned_times() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "event_behavior_anomaly",
            "rendered_message": "WLAN Access Allowed behavior for SYNTHETIC DEVICE on 2037-03-17 changed: time shift 2 hours.",
            "metadata": {
                "reasons": ["time shift 2 hours", "weekday drift"],
                "observed_timestamps": ["2037-03-17T11:22:50"],
                "typical_hour": 9.0,
                "history_count": 4,
                "dominant_weekdays": [0],
                "current_weekday": 1,
            },
        }
    )

    assert "Observed weekday: Tuesday" in lines
    assert "Learned weekday pattern: Monday from 4 prior day(s)" in lines
    assert "Observed times: 11:22:50 AM" in lines
    assert "Learned typical time: around 9:00 AM from 4 prior day(s)" in lines


def test_render_finding_message_formats_small_timing_drift_as_minutes() -> None:
    finding = analyzer.Finding(
        kind="timing_anomaly",
        severity="low",
        mac="02:00:00:00:00:03",
        message="",
        metadata={
            "day": "2037-03-18",
            "distance_hours": 0.05,
        },
    )

    rendered = analyzer.render_finding_message(
        finding,
        {"mac_to_name": {"02:00:00:00:00:03": "SYNTHETIC SCALE"}},
    )

    assert rendered == (
        "Timing drift for SYNTHETIC SCALE (02:00:00:00:00:03) on 2037-03-18: "
        "3 minutes outside the expected window."
    )


def test_format_duration_hours_normalizes_subhour_and_mixed_durations() -> None:
    assert analyzer.format_duration_hours(0.05) == "3 minutes"
    assert analyzer.format_duration_hours(1.0) == "1 hour"
    assert analyzer.format_duration_hours(2.5) == "2 hours 30 minutes"


def test_help_examples_use_invoked_program_name(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(analyzer.sys, "argv", ["/tmp/custom-router-tool"])

    with pytest.raises(SystemExit):
        analyzer.parse_args(["--help"])

    output = capsys.readouterr().out
    assert "custom-router-tool router-log.pdf" in output
    assert "./router_log_analyze.py" not in output


def test_parse_log_text_scrapes_unknown_event_labels_without_whitelist() -> None:
    events, stats = analyzer.parse_log_text(
        "[vpn handshake retry] from source 192.0.2.25, Saturday, March 21, 2037 08:32:33",
        source="test",
    )

    assert stats.parsed_events == 1
    assert events[0].event_key == "VPN_HANDSHAKE_RETRY"
    assert events[0].event_family == "OTHER"
    assert events[0].mac == analyzer.SYSTEM_ACTOR
    assert events[0].ip == "192.0.2.25"


def test_netgear_adapter_detects_and_normalizes_the_legacy_format() -> None:
    text = "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26"

    adapter = analyzer.select_router_adapter(text, "auto")
    parsed = analyzer.parse_router_log(text, source="synthetic-netgear.log", requested_format="auto")

    assert adapter.format_id == "netgear"
    assert adapter.detect(text) >= 0.80
    assert parsed.format_id == "netgear"
    assert parsed.capabilities.stable_client_identity is True
    assert parsed.capabilities.client_dhcp_equivalence is True
    assert parsed.capabilities.client_access_decision_equivalence is True
    assert parsed.capabilities.comparable_device_event_coverage is True
    assert parsed.capabilities.router_system_events is True
    assert parsed.capabilities.wan_transitions is True
    assert parsed.capabilities.snapshot_counts is False
    assert parsed.capabilities.snapshot_buffer_semantic_dedup is False
    assert parsed.capabilities.coverage_mode == "continuous_log"
    assert parsed.events == analyzer.parse_log_text(text, source="synthetic-netgear.log")[0]


def test_router_snapshot_metrics_retains_invalid_raw_text_without_parsed_counts() -> None:
    metrics = analyzer.RouterSnapshotMetrics(
        raw_total_clients="many synthetic clients",
        raw_wifi_clients="not-a-number",
        total_clients=None,
        wifi_clients=None,
        derived_wired_clients=None,
        eligible=False,
        exclusion_reason="invalid_snapshot_counts",
    )

    serialized = analyzer.asdict(metrics)

    assert serialized == {
        "raw_total_clients": "many synthetic clients",
        "raw_wifi_clients": "not-a-number",
        "total_clients": None,
        "wifi_clients": None,
        "derived_wired_clients": None,
        "eligible": False,
        "exclusion_reason": "invalid_snapshot_counts",
    }
    assert json.loads(json.dumps(serialized)) == serialized


def test_router_capability_and_identity_sets_are_immutable_across_results() -> None:
    supplied_event_keys = {"SYNTHETIC_EVENT"}
    supplied_interfaces = {"02:00:00:00:00:09"}
    capabilities = analyzer.RouterCapabilities(supported_event_keys=supplied_event_keys)
    identity = analyzer.RouterIdentityCandidate(
        canonical_vendor="synthetic",
        router_owned_interfaces=supplied_interfaces,
    )
    text = "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26"
    parsed = analyzer.parse_router_log(text, "synthetic-netgear.log", "netgear")

    supplied_event_keys.add("CALLER_MUTATION")
    supplied_interfaces.add("02:00:00:00:00:0A")

    assert capabilities.supported_event_keys == frozenset({"SYNTHETIC_EVENT"})
    assert identity.router_owned_interfaces == frozenset({"02:00:00:00:00:09"})
    with pytest.raises(AttributeError):
        parsed.capabilities.supported_event_keys.add("RESULT_MUTATION")
    assert analyzer.parse_router_log(text, "synthetic-netgear.log", "netgear").capabilities.supported_event_keys == (
        parsed.capabilities.supported_event_keys
    )
    capabilities_json = parsed.capabilities.to_json()
    identity_json = identity.to_json()
    assert capabilities_json["supported_event_keys"] == sorted(parsed.capabilities.supported_event_keys)
    assert capabilities_json["supported_event_families"] == sorted(parsed.capabilities.supported_event_families)
    assert identity_json["router_owned_interfaces"] == ["02:00:00:00:00:09"]
    assert json.loads(json.dumps(capabilities_json)) == capabilities_json
    assert json.loads(json.dumps(identity_json)) == identity_json


def test_explicit_netgear_format_is_accepted_before_state_store_construction(tmp_path: Path) -> None:
    log_path = tmp_path / "synthetic-netgear.log"
    db_path = tmp_path / "not-created-before-baseline-validation.db"
    log_path.write_text(
        "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="No active baseline epoch"):
        analyzer.main([str(log_path), "--format", "netgear", "--db", str(db_path)])

    assert db_path.exists()


def test_explicit_format_structural_failure_does_not_create_database(tmp_path: Path) -> None:
    log_path = tmp_path / "synthetic-not-netgear.log"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text("synthetic unrelated export without router records", encoding="utf-8")

    with pytest.raises(SystemExit, match="plausible NETGEAR log structure"):
        analyzer.main([str(log_path), "--format", "netgear", "--db", str(db_path)])

    assert not db_path.exists()


def test_netgear_export_noise_is_not_detected_or_allowed_to_mutate_state(tmp_path: Path) -> None:
    text = "Sent: Saturday, March 21, 2037 08:07:26"
    log_path = tmp_path / "synthetic-export-noise.log"
    baseline_path = tmp_path / "synthetic-baseline.json"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text(text, encoding="utf-8")
    baseline_path.write_text(json.dumps({"devices": {}}), encoding="utf-8")

    assert analyzer.NetgearLogAdapter().detect(text) < analyzer.FORMAT_DETECTION_THRESHOLD
    with pytest.raises(SystemExit, match="plausible NETGEAR log structure"):
        analyzer.main([
            str(log_path), "--format", "netgear", "--import-baseline", str(baseline_path),
            "--db", str(db_path),
        ])

    assert not db_path.exists()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", {"total_lines": 0, "export_noise_lines": 0, "malformed_lines": 0}),
        ("Sent: Saturday, March 21, 2037 08:07:26", {"total_lines": 1, "export_noise_lines": 1, "malformed_lines": 0}),
        ("[synthetic malformed event without a timestamp]", {"total_lines": 1, "export_noise_lines": 0, "malformed_lines": 1}),
    ],
)
def test_parse_log_text_preserves_legacy_nonstructural_input_behavior(
    text: str,
    expected: dict[str, int],
) -> None:
    events, stats = analyzer.parse_log_text(text, source="synthetic.log")

    assert events == []
    assert {name: getattr(stats, name) for name in expected} == expected


def test_legacy_netgear_helper_names_remain_public_for_normal_malformed_and_noise_inputs() -> None:
    valid_line = "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26"

    assert analyzer.parse_timestamp_from_line(valid_line) == datetime(2037, 3, 21, 8, 7, 26)
    assert analyzer.parse_timestamp_from_line("[malformed synthetic event]") is None
    assert analyzer.is_export_noise_line("Sent: Saturday, March 21, 2037 08:07:26") is True
    assert analyzer.is_export_noise_line(valid_line) is False
    assert analyzer.normalize_event_key(" DHCP IP: (192.0.2.25) ") == "DHCP_IP"
    assert analyzer.normalize_event_key("   ") == "OTHER"
    assert analyzer.classify_event_family("WLAN_ACCESS_REJECTED", "synthetic") == "WLAN_REJECTED"
    assert analyzer.classify_event_family("OTHER", "blocked synthetic event") == "WLAN_REJECTED"
    assert analyzer.extract_ip(valid_line) == "192.0.2.25"
    assert analyzer.extract_ip("[malformed synthetic event]") is None


def test_auto_format_rejects_low_confidence_without_echoing_input() -> None:
    raw_input = "SYNTHETIC-UNRECOGNIZED-CONTENT-DO-NOT-ECHO"

    with pytest.raises(SystemExit) as exc_info:
        analyzer.select_router_adapter(raw_input, "auto")

    message = str(exc_info.value)
    assert "Could not confidently identify" in message
    assert "netgear=0.00" in message
    assert "tp-link-archer=0.00" in message
    assert raw_input not in message


@pytest.mark.parametrize(
    "invalid_score",
    [True, "0.95", float("nan"), float("inf"), float("-inf"), -0.01, 1.01],
    ids=("bool", "non-numeric", "nan", "positive-infinity", "negative-infinity", "below-zero", "above-one"),
)
def test_auto_format_rejects_invalid_detector_scores_before_selection_or_state_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_score: object,
) -> None:
    class SyntheticAdapter(analyzer.RouterLogAdapter):
        def __init__(self, format_id: str, cli_format: str, confidence: object) -> None:
            self.format_id = format_id
            self.cli_format = cli_format
            self.confidence = confidence

        def detect(self, text: str) -> float:
            return self.confidence  # type: ignore[return-value]

        def parse(self, text: str, source: str) -> analyzer.ParsedRouterLog:
            raise AssertionError("invalid detection score must stop before parsing")

    raw_input = "SYNTHETIC-INVALID-DETECTOR-INPUT-DO-NOT-ECHO"
    db_path = tmp_path / "must-not-exist.db"
    monkeypatch.setattr(
        analyzer,
        "ROUTER_LOG_ADAPTERS",
        {
            analyzer.FORMAT_NETGEAR: SyntheticAdapter(analyzer.FORMAT_NETGEAR, "netgear", invalid_score),
            analyzer.FORMAT_TP_LINK_ARCHER: SyntheticAdapter(analyzer.FORMAT_TP_LINK_ARCHER, "tp-link-archer", 0.0),
        },
    )

    with pytest.raises(SystemExit, match="netgear.*invalid detection score") as exc_info:
        analyzer.select_router_adapter(raw_input, "auto")

    assert raw_input not in str(exc_info.value)
    log_path = tmp_path / "synthetic-invalid-detector.log"
    log_path.write_text(raw_input, encoding="utf-8")
    with pytest.raises(SystemExit, match="netgear.*invalid detection score"):
        analyzer.main([str(log_path), "--db", str(db_path)])
    assert not db_path.exists()


def test_auto_format_low_confidence_diagnostic_preserves_subthreshold_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyntheticAdapter(analyzer.RouterLogAdapter):
        def __init__(self, format_id: str, cli_format: str, confidence: float) -> None:
            self.format_id = format_id
            self.cli_format = cli_format
            self.confidence = confidence

        def detect(self, text: str) -> float:
            return self.confidence

        def parse(self, text: str, source: str) -> analyzer.ParsedRouterLog:
            raise AssertionError("low-confidence selection test should not parse")

    monkeypatch.setattr(
        analyzer,
        "ROUTER_LOG_ADAPTERS",
        {
            analyzer.FORMAT_NETGEAR: SyntheticAdapter(analyzer.FORMAT_NETGEAR, "netgear", 0.7999),
            analyzer.FORMAT_TP_LINK_ARCHER: SyntheticAdapter(analyzer.FORMAT_TP_LINK_ARCHER, "tp-link-archer", 0.0),
        },
    )

    with pytest.raises(SystemExit, match="Could not confidently identify") as exc_info:
        analyzer.select_router_adapter("synthetic content", "auto")

    assert "netgear=0.7999" in str(exc_info.value)
    assert "netgear=0.80" not in str(exc_info.value)


def test_auto_format_rejects_ambiguous_high_confidence_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    class SyntheticAdapter(analyzer.RouterLogAdapter):
        def __init__(self, format_id: str, cli_format: str, confidence: float) -> None:
            self.format_id = format_id
            self.cli_format = cli_format
            self.confidence = confidence

        def detect(self, text: str) -> float:
            return self.confidence

        def parse(self, text: str, source: str) -> analyzer.ParsedRouterLog:
            raise AssertionError("selection test should not parse")

    netgear = SyntheticAdapter(analyzer.FORMAT_NETGEAR, "netgear", 0.90)
    tp_link = SyntheticAdapter(analyzer.FORMAT_TP_LINK_ARCHER, "tp-link-archer", 0.82)
    monkeypatch.setattr(
        analyzer,
        "ROUTER_LOG_ADAPTERS",
        {analyzer.FORMAT_NETGEAR: netgear, analyzer.FORMAT_TP_LINK_ARCHER: tp_link},
    )

    with pytest.raises(SystemExit, match="ambiguous") as exc_info:
        analyzer.select_router_adapter("synthetic content", "auto")

    assert "netgear=0.90" in str(exc_info.value)
    assert "tp-link-archer=0.82" in str(exc_info.value)


@pytest.mark.parametrize(
    ("netgear_score", "tp_link_score", "is_ambiguous"),
    [
        (0.9499, 0.80, True),
        (0.95, 0.80, False),
        (0.9501, 0.80, False),
    ],
    ids=("just-below-margin", "exact-margin", "just-above-margin"),
)
def test_auto_format_ambiguity_uses_the_decimal_margin_contract(
    monkeypatch: pytest.MonkeyPatch,
    netgear_score: float,
    tp_link_score: float,
    is_ambiguous: bool,
) -> None:
    class SyntheticAdapter(analyzer.RouterLogAdapter):
        def __init__(self, format_id: str, cli_format: str, confidence: float) -> None:
            self.format_id = format_id
            self.cli_format = cli_format
            self.confidence = confidence

        def detect(self, text: str) -> float:
            return self.confidence

        def parse(self, text: str, source: str) -> analyzer.ParsedRouterLog:
            raise AssertionError("selection test should not parse")

    netgear = SyntheticAdapter(analyzer.FORMAT_NETGEAR, "netgear", netgear_score)
    tp_link = SyntheticAdapter(analyzer.FORMAT_TP_LINK_ARCHER, "tp-link-archer", tp_link_score)
    monkeypatch.setattr(
        analyzer,
        "ROUTER_LOG_ADAPTERS",
        {analyzer.FORMAT_NETGEAR: netgear, analyzer.FORMAT_TP_LINK_ARCHER: tp_link},
    )

    if is_ambiguous:
        with pytest.raises(SystemExit, match="ambiguous"):
            analyzer.select_router_adapter("synthetic content", "auto")
    else:
        assert analyzer.select_router_adapter("synthetic content", "auto") is netgear


def test_explicit_format_bypasses_detection_ambiguity(monkeypatch: pytest.MonkeyPatch) -> None:
    class SyntheticAdapter(analyzer.RouterLogAdapter):
        def __init__(self, format_id: str, cli_format: str) -> None:
            self.format_id = format_id
            self.cli_format = cli_format

        def detect(self, text: str) -> float:
            return 0.90

        def parse(self, text: str, source: str) -> analyzer.ParsedRouterLog:
            raise AssertionError("selection test should not parse")

    netgear = SyntheticAdapter(analyzer.FORMAT_NETGEAR, "netgear")
    tp_link = SyntheticAdapter(analyzer.FORMAT_TP_LINK_ARCHER, "tp-link-archer")
    monkeypatch.setattr(
        analyzer,
        "ROUTER_LOG_ADAPTERS",
        {analyzer.FORMAT_NETGEAR: netgear, analyzer.FORMAT_TP_LINK_ARCHER: tp_link},
    )

    assert analyzer.select_router_adapter("synthetic content", "netgear") is netgear
    assert analyzer.select_router_adapter("synthetic content", "tp-link-archer") is tp_link


def test_ip_attribution_preserves_extended_event_metadata() -> None:
    dhcp_event = analyzer.Event(
        timestamp=datetime(2037, 3, 21, 8, 7, 26),
        mac="02:00:00:00:00:08",
        event_family="DHCP",
        event_key="DHCP_IP",
        ip="192.0.2.25",
        raw_label="DHCP IP",
        raw_line="synthetic DHCP",
        source="synthetic.log",
    )
    event = analyzer.Event(
        timestamp=datetime(2037, 3, 21, 8, 8, 26),
        mac=analyzer.SYSTEM_ACTOR,
        event_family="OTHER",
        event_key="ADMIN_LOGIN",
        ip="192.0.2.25",
        raw_label="admin login",
        raw_line="synthetic login",
        source="synthetic.log",
        actor_scope="router",
        stable_client_identity="synthetic-client-id",
        component="synthetic-component",
        process_id="42",
        syslog_severity="notice",
        vendor_event_code="9001",
        normalized_message="synthetic normalized message",
        structured_evidence={"synthetic": "evidence"},
        source_sequence=7,
        raw_timestamp="2037-03-21T08:08:26",
        clock_trust="trusted",
        clock_segment_id="clock-1",
        boot_context_id="boot-context-1",
        boot_session_id="boot-session-1",
        occurrence_digest="synthetic-occurrence",
    )

    attributed = analyzer.attribute_ip_only_events([dhcp_event, event])[1]

    assert attributed.mac == dhcp_event.mac
    for field_name in (
        "incident_id", "incident_role", "actor_scope", "stable_client_identity", "component",
        "process_id", "syslog_severity", "vendor_event_code", "normalized_message",
        "structured_evidence", "source_sequence", "raw_timestamp", "clock_trust",
        "clock_segment_id", "boot_context_id", "boot_session_id", "occurrence_digest",
        "trusted_overlap_identity",
    ):
        assert getattr(attributed, field_name) == getattr(event, field_name)

    incident = analyzer.NetworkIncident(
        incident_id="annotated-synthetic-incident",
        incident_type="internet_connection_reset",
        confidence="confirmed",
        start="2037-03-21T08:08:26",
        restored_at="2037-03-21T08:08:26",
        recovery_end="2037-03-21T08:08:26",
        disconnect_count=1,
        connect_count=1,
        affected_macs=[attributed.mac],
        event_counts={"ADMIN_LOGIN": 1},
        explained_event_count=1,
        active_known_devices=1,
        affected_device_fraction=1.0,
    )
    analyzer.annotate_incident_events(incident, [attributed], [])
    later = analyzer.replace(attributed, timestamp=datetime(2037, 3, 21, 8, 9, 26), source_sequence=8)
    retained = [
        candidate
        for candidate in sorted([later, attributed], key=lambda candidate: candidate.timestamp)
        if candidate.component == "synthetic-component"
    ]
    assert [candidate.source_sequence for candidate in retained] == [7, 8]
    assert retained[0].incident_id == "annotated-synthetic-incident"
    assert retained[0].incident_role == "wan_transition"
    for candidate in retained:
        assert candidate.component == "synthetic-component"
        assert candidate.structured_evidence == {"synthetic": "evidence"}
        assert candidate.occurrence_digest == "synthetic-occurrence"


MANAGEMENT_OPTIONS = [
    "--import-policy", "--export-policy", "--import-baseline", "--export-baseline", "--import-config",
]


def install_identityless_test_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    class IdentitylessAdapter(analyzer.RouterLogAdapter):
        format_id = analyzer.FORMAT_TP_LINK_ARCHER
        cli_format = "tp-link-archer"

        def detect(self, text: str) -> float:
            return 0.99

        def parse(self, text: str, source: str) -> analyzer.ParsedRouterLog:
            return analyzer.ParsedRouterLog(
                format_id=self.format_id,
                capabilities=analyzer.RouterCapabilities(coverage_mode="point_snapshot"),
                identity=analyzer.RouterIdentityCandidate(
                    canonical_vendor="tp-link",
                    lan_mac="02:00:00:00:00:FE",
                    persistence_safe_without_override=False,
                ),
                events=[],
                parse_stats=analyzer.ParseStats(),
            )

    monkeypatch.setattr(
        analyzer,
        "ROUTER_LOG_ADAPTERS",
        {
            analyzer.FORMAT_NETGEAR: analyzer.NetgearLogAdapter(),
            analyzer.FORMAT_TP_LINK_ARCHER: IdentitylessAdapter(),
        },
    )


@pytest.mark.parametrize("management_option", MANAGEMENT_OPTIONS)
def test_identityless_log_rejects_every_combined_management_mutation_before_store_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    management_option: str,
) -> None:
    install_identityless_test_adapter(monkeypatch)
    log_path = tmp_path / "synthetic-identityless.log"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text("synthetic identityless snapshot", encoding="utf-8")

    with pytest.raises(SystemExit, match="no stable router identity"):
        analyzer.main([
            str(log_path), "--format", "tp-link-archer", management_option,
            str(tmp_path / "synthetic-management.json"), "--db", str(db_path),
        ])

    assert not db_path.exists()


@pytest.mark.parametrize("management_option", MANAGEMENT_OPTIONS)
def test_ambiguous_log_rejects_every_combined_management_mutation_before_store_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    management_option: str,
) -> None:
    class AmbiguousAdapter(analyzer.RouterLogAdapter):
        def __init__(self, format_id: str, cli_format: str) -> None:
            self.format_id = format_id
            self.cli_format = cli_format

        def detect(self, text: str) -> float:
            return 0.90

        def parse(self, text: str, source: str) -> analyzer.ParsedRouterLog:
            raise AssertionError("ambiguous selection must stop before parsing")

    log_path = tmp_path / "synthetic-ambiguous.log"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text("synthetic ambiguous content", encoding="utf-8")
    monkeypatch.setattr(
        analyzer,
        "ROUTER_LOG_ADAPTERS",
        {
            analyzer.FORMAT_NETGEAR: AmbiguousAdapter(analyzer.FORMAT_NETGEAR, "netgear"),
            analyzer.FORMAT_TP_LINK_ARCHER: AmbiguousAdapter(analyzer.FORMAT_TP_LINK_ARCHER, "tp-link-archer"),
        },
    )

    with pytest.raises(SystemExit, match="ambiguous"):
        analyzer.main([
            str(log_path), management_option, str(tmp_path / "synthetic-management.json"), "--db", str(db_path),
        ])

    assert not db_path.exists()


@pytest.mark.parametrize("management_option", MANAGEMENT_OPTIONS)
def test_explicit_format_mismatch_rejects_every_combined_management_mutation_before_store_creation(
    tmp_path: Path,
    management_option: str,
) -> None:
    log_path = tmp_path / "synthetic-mismatch.log"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text("synthetic export without NETGEAR structure", encoding="utf-8")

    with pytest.raises(SystemExit, match="plausible NETGEAR log structure"):
        analyzer.main([
            str(log_path), "--format", "netgear", management_option,
            str(tmp_path / "synthetic-management.json"), "--db", str(db_path),
        ])

    assert not db_path.exists()


def test_identityless_log_emits_nonpersistent_report_without_creating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_identityless_test_adapter(monkeypatch)
    log_path = tmp_path / "synthetic-identityless.log"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text("synthetic identityless snapshot", encoding="utf-8")

    assert analyzer.main([str(log_path), "--format", "tp-link-archer", "--db", str(db_path), "--json"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["persistence"] == {"available": False, "reason": "no_stable_router_identity"}
    assert not db_path.exists()


def test_identityless_log_includes_router_label_in_minimal_default_and_json_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_identityless_test_adapter(monkeypatch)
    log_path = tmp_path / "synthetic-identityless.log"
    db_path = tmp_path / "must-not-exist.db"
    router_label = "SYNTHETIC IDENTITYLESS ROUTER"
    log_path.write_text("synthetic identityless snapshot", encoding="utf-8")

    assert analyzer.main([
        str(log_path), "--format", "tp-link-archer", "--router-label", router_label, "--db", str(db_path),
    ]) == 0
    assert router_label in capsys.readouterr().out
    assert not db_path.exists()

    assert analyzer.main([
        str(log_path), "--format", "tp-link-archer", "--router-label", router_label, "--db", str(db_path), "--json",
    ]) == 0
    json_output = capsys.readouterr().out
    report = json.loads(json_output)
    assert report["router_label"] == router_label
    assert "02:00:00:00:00:FE" not in json_output
    assert not db_path.exists()


@pytest.mark.parametrize(
    "report_args",
    [["--report", "json"], ["--report-dir", "synthetic-reports"]],
    ids=("report-format", "report-directory"),
)
def test_identityless_log_rejects_unavailable_explicit_report_outputs_before_output_or_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    report_args: list[str],
) -> None:
    install_identityless_test_adapter(monkeypatch)
    log_path = tmp_path / "synthetic-identityless.log"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text("synthetic identityless snapshot", encoding="utf-8")
    args = [str(log_path), "--format", "tp-link-archer", "--db", str(db_path), *report_args]
    if report_args[0] == "--report-dir":
        args[-1] = str(tmp_path / report_args[-1])

    with pytest.raises(SystemExit, match="Non-persistent reports do not support --report or --report-dir"):
        analyzer.main(args)

    assert capsys.readouterr().out == ""
    assert not db_path.exists()
    assert not (tmp_path / "synthetic-reports").exists()


@pytest.mark.parametrize("stateful_form", ["positional_baseline", "explicit_config", "inferred_config", "reprocess"])
def test_identityless_log_rejects_all_other_stateful_forms_before_store_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stateful_form: str,
) -> None:
    install_identityless_test_adapter(monkeypatch)
    log_path = tmp_path / "synthetic-identityless.log"
    db_path = tmp_path / "must-not-exist.db"
    auxiliary_path = tmp_path / "synthetic-auxiliary.json"
    log_path.write_text("synthetic identityless snapshot", encoding="utf-8")
    auxiliary_path.write_text(json.dumps({"devices": {}}), encoding="utf-8")
    args = [str(log_path), "--format", "tp-link-archer", "--db", str(db_path)]
    if stateful_form == "positional_baseline":
        args.insert(1, str(auxiliary_path))
    elif stateful_form == "explicit_config":
        args.extend(["--config", str(auxiliary_path)])
    elif stateful_form == "inferred_config":
        (tmp_path / "router-security-config.md").write_text("synthetic config", encoding="utf-8")
    else:
        args.append("--reprocess")

    with pytest.raises(SystemExit, match="no stable router identity"):
        analyzer.main(args)

    assert not db_path.exists()


def test_valid_persistent_log_allows_combined_baseline_import_after_parse_validation(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "synthetic-netgear.log"
    baseline_path = tmp_path / "synthetic-baseline.json"
    db_path = tmp_path / "network.db"
    log_path.write_text(
        "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26",
        encoding="utf-8",
    )
    baseline_path.write_text(
        json.dumps({"devices": {"02:00:00:00:00:08": {"name": "SYNTHETIC DEVICE"}}}),
        encoding="utf-8",
    )

    assert analyzer.main([
        str(log_path), "--format", "netgear", "--import-baseline", str(baseline_path),
        "--db", str(db_path), "--json",
    ]) == 0

    store = analyzer.StateStore(db_path)
    try:
        assert store.get_active_epoch() is not None
        assert store.get_run_by_hash(
            store.get_or_create_legacy_netgear_router_instance(),
            analyzer.sha256_bytes(log_path.read_bytes()),
        ) is not None
    finally:
        store.close()


@pytest.mark.parametrize(
    "management_option",
    ["--import-policy", "--export-policy", "--export-baseline", "--import-config"],
)
def test_valid_persistent_log_applies_combined_management_and_stores_analysis(
    tmp_path: Path,
    management_option: str,
) -> None:
    log_path = tmp_path / "synthetic-netgear.log"
    baseline_path = tmp_path / "synthetic-baseline.json"
    management_path = tmp_path / "synthetic-management.json"
    config_path = tmp_path / "synthetic-router-security-config.md"
    db_path = tmp_path / "network.db"
    log_path.write_text(
        "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26",
        encoding="utf-8",
    )
    baseline_path.write_text(
        json.dumps({"devices": {"02:00:00:00:00:08": {"name": "SYNTHETIC DEVICE"}}}),
        encoding="utf-8",
    )
    management_path.write_text(
        json.dumps({"schema_version": 1, "scoring": {"low": 3}}),
        encoding="utf-8",
    )
    config_path.write_text(
        "\n".join(
            [
                "| Device Name | MAC Address | Status | IP Address | Connection Type |",
                "|---|---|---|---|---|",
                "| SYNTHETIC CONFIG DEVICE | 02:00:00:00:00:09 | Allowed | 192.0.2.26 | Wi-Fi |",
            ]
        ),
        encoding="utf-8",
    )

    store = analyzer.StateStore(db_path)
    try:
        policy, _ = store.load_effective_policy()
        store.import_baseline(
            baseline_path,
            analyzer.normalize_baseline_document(json.loads(baseline_path.read_text(encoding="utf-8"))),
            float(policy["learning"]["seed_weight_frequent"]),
        )
    finally:
        store.close()

    option_path = {
        "--import-policy": management_path,
        "--export-policy": management_path,
        "--export-baseline": management_path,
        "--import-config": config_path,
    }[management_option]
    if management_option in {"--export-policy", "--export-baseline"}:
        option_path.unlink()

    assert analyzer.main([
        str(log_path), "--format", "netgear", management_option, str(option_path), "--db", str(db_path),
    ]) == 0

    store = analyzer.StateStore(db_path)
    try:
        assert store.get_run_by_hash(
            store.get_or_create_legacy_netgear_router_instance(),
            analyzer.sha256_bytes(log_path.read_bytes()),
        ) is not None
        if management_option == "--import-policy":
            policy, policy_row = store.load_effective_policy()
            assert policy_row is not None
            assert policy["scoring"]["low"] == 3
        elif management_option == "--export-policy":
            assert json.loads(option_path.read_text(encoding="utf-8"))["scoring"]["low"] == 2
        elif management_option == "--export-baseline":
            assert json.loads(option_path.read_text(encoding="utf-8"))["devices"] == {
                "02:00:00:00:00:08": {"name": "SYNTHETIC DEVICE"}
            }
        else:
            config_device = store.conn.execute(
                "SELECT name, status, source FROM devices WHERE mac = ?",
                ("02:00:00:00:00:09",),
            ).fetchone()
            assert dict(config_device) == {
                "name": "SYNTHETIC CONFIG DEVICE",
                "status": "allowed",
                "source": "config_import",
            }
    finally:
        store.close()


def test_router_instance_validation_occurs_before_state_store_creation(tmp_path: Path) -> None:
    log_path = tmp_path / "synthetic-netgear.log"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text(
        "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="router-instance"):
        analyzer.main([str(log_path), "--router-instance", "\x00", "--db", str(db_path)])

    assert not db_path.exists()


def test_netgear_adapter_preserves_source_and_clock_provenance_on_normalized_events() -> None:
    text = "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26"

    parsed = analyzer.parse_router_log(text, "synthetic-netgear.log", "netgear")
    event = parsed.events[0]

    assert event.actor_scope == "device"
    assert event.stable_client_identity == "02:00:00:00:00:08"
    assert event.source_sequence == 1
    assert event.raw_timestamp == "Saturday, March 21, 2037 08:07:26"
    assert event.clock_trust == "trusted"
    assert event.clock_segment_id == "netgear-local-time"


@pytest.mark.parametrize(
    ("mac", "stable_client_identity", "actor_scope"),
    [
        ("00:00:00:00:00:00", None, "router"),
        ("FF:FF:FF:FF:FF:FF", None, "router"),
        ("01:00:5E:00:00:01", None, "router"),
        ("02:00:00:00:00:08", "02:00:00:00:00:08", "device"),
    ],
    ids=("all-zero", "broadcast", "multicast", "locally-administered-unicast"),
)
def test_netgear_stable_client_identity_requires_an_identity_grade_mac(
    mac: str,
    stable_client_identity: str | None,
    actor_scope: str,
) -> None:
    text = f"[DHCP IP: (192.0.2.25)] to MAC address {mac}, Saturday, March 21, 2037 08:07:26"

    event = analyzer.parse_router_log(text, "synthetic-netgear.log", "netgear").events[0]

    assert analyzer.is_real_mac(mac) is True
    assert event.mac == mac
    assert event.stable_client_identity == stable_client_identity
    assert event.actor_scope == actor_scope


def test_netgear_adapter_deduplication_preserves_normalized_event_provenance() -> None:
    line = "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26"

    parsed = analyzer.parse_router_log(f"{line}\n{line}", "synthetic-netgear.log", "netgear")

    assert parsed.parse_stats.duplicate_events == 1
    assert len(parsed.events) == 1
    survivor = parsed.events[0]
    assert survivor.source_sequence == 1
    assert survivor.actor_scope == "device"
    assert survivor.stable_client_identity == "02:00:00:00:00:08"
    assert survivor.raw_timestamp == "Saturday, March 21, 2037 08:07:26"
    assert survivor.clock_trust == "trusted"
    assert survivor.clock_segment_id == "netgear-local-time"


def test_netgear_adapter_and_legacy_wrapper_preserve_every_extended_event_field() -> None:
    text = "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26"
    extended_fields = (
        "actor_scope", "stable_client_identity", "component", "process_id", "syslog_severity",
        "vendor_event_code", "normalized_message", "structured_evidence", "source_sequence",
        "raw_timestamp", "clock_trust", "clock_reason", "clock_segment_id", "boot_context_id", "boot_session_id",
        "occurrence_digest", "trusted_overlap_identity",
    )

    normalized = analyzer.parse_router_log(text, "synthetic-netgear.log", "netgear").events[0]
    legacy = analyzer.parse_log_text(text, "synthetic-netgear.log")[0][0]

    assert {name: getattr(normalized, name) for name in extended_fields} == {
        name: getattr(legacy, name) for name in extended_fields
    }


TP_LINK_SYNTHETIC_FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "tp_link_archer_synthetic.log"


def test_tp_link_archer_detects_and_parses_synthetic_snapshot_in_memory() -> None:
    text = TP_LINK_SYNTHETIC_FIXTURE.read_text(encoding="utf-8")

    adapter = analyzer.select_router_adapter(text, "auto")
    parsed = analyzer.parse_router_log(text, "synthetic-tp-link.log", "auto")

    assert adapter.format_id == analyzer.FORMAT_TP_LINK_ARCHER
    assert adapter.detect(text) >= analyzer.FORMAT_DETECTION_THRESHOLD
    assert parsed.format_id == analyzer.FORMAT_TP_LINK_ARCHER
    assert parsed.model == "SYNTHETIC-ARCHER-X9000"
    assert parsed.export_timestamp == datetime(2042, 6, 15, 12, 0, 0)
    assert parsed.export_timestamp.tzinfo is None
    assert parsed.hardware == "SYNTHETIC-HW-9000"
    assert parsed.firmware == "9.99.9 Build 20420101 rel.99999n"
    assert parsed.identity.canonical_vendor == "tp-link"
    assert parsed.identity.lan_mac == "02:00:00:00:00:01"
    assert parsed.identity.persistence_safe_without_override is True
    assert parsed.identity.router_owned_interfaces == frozenset({
        "02:00:00:00:00:01", "02:00:00:00:00:02",
    })
    assert parsed.snapshot_metrics == analyzer.RouterSnapshotMetrics(
        raw_total_clients="7",
        raw_wifi_clients="5",
        total_clients=7,
        wifi_clients=5,
        derived_wired_clients=2,
        eligible=True,
        exclusion_reason=None,
    )
    assert parsed.capabilities == analyzer.RouterCapabilities(
        stable_client_identity=False,
        client_dhcp_equivalence=False,
        client_access_decision_equivalence=False,
        comparable_device_event_coverage=False,
        router_system_events=True,
        wan_transitions=True,
        snapshot_counts=True,
        potentially_trustworthy_router_local_time=True,
        supported_event_keys=frozenset({
            "WAN_DHCP_DISCOVER", "WAN_DHCP_OFFER", "WAN_DHCP_REQUEST", "WAN_DHCP_ACK",
            "WAN_DHCP_RELEASE", "INTERNET_CONNECTED", "INTERNET_DISCONNECTED",
            "ROUTER_BOOT",
        }),
        supported_event_families=frozenset({"WAN_DHCP", "WAN", "ROUTER_SYSTEM"}),
        coverage_mode="point_snapshot",
        snapshot_buffer_semantic_dedup=True,
    )
    assert [event.event_key for event in parsed.events] == [
        "ROUTER_BOOT",
        "SERVICE_2001_START",
        "WAN_DHCP_DISCOVER",
        "WAN_DHCP_OFFER",
        "WAN_DHCP_REQUEST",
        "WAN_DHCP_ACK",
        "INTERNET_CONNECTED",
    ]
    assert [event.timestamp for event in parsed.events] == sorted(event.timestamp for event in parsed.events)
    assert [event.source_sequence for event in parsed.events] == [14, 13, 12, 11, 10, 9, 8]
    assert [event.clock_trust for event in parsed.events] == [
        "pre_synchronization", "pre_synchronization", "trusted", "trusted", "trusted", "trusted", "trusted",
    ]
    assert all(event.timestamp.tzinfo is None for event in parsed.events)
    assert all(event.actor_scope == "router" for event in parsed.events)
    assert all(event.stable_client_identity is None for event in parsed.events)
    assert all(event.mac == analyzer.SYSTEM_ACTOR for event in parsed.events)
    assert all(event.event_key != "DHCP_IP" for event in parsed.events)
    assert parsed.events[0].boot_context_id == parsed.events[-1].boot_context_id
    assert parsed.boot_candidates[0].trusted_anchor == datetime(2042, 6, 15, 11, 59, 54)
    assert parsed.warnings == []
    assert parsed.parse_stats.total_lines == 14
    assert parsed.parse_stats.parsed_events == 7
    assert parsed.parse_stats.malformed_lines == 0
    assert parsed.parse_stats.ignored_lines == 7
    assert parsed.coverage_stats["body_records"] == 7
    assert parsed.coverage_stats["trusted_records"] == 5
    assert parsed.coverage_stats["untrusted_records"] == 2
    assert parsed.coverage_stats["lan"] == {
        "ip": "192.0.2.1", "mask": "255.255.255.0", "mac": "02:00:00:00:00:01",
    }
    assert parsed.coverage_stats["wan"] == {
        "ip": "198.51.100.2",
        "mask": "255.255.255.0",
        "mac": "02:00:00:00:00:02",
        "gateway": "198.51.100.1",
        "dns": ["203.0.113.53", "203.0.113.54"],
    }
    assert parsed.order_stats == {"source_order": "newest_first", "emission_order_reconstructed": True}

    wan_ack = next(event for event in parsed.events if event.event_key == "WAN_DHCP_ACK")
    assert wan_ack.structured_evidence["mac_addresses"] == ["02:00:00:00:00:02"]
    assert wan_ack.structured_evidence["ipv4_addresses"] == ["198.51.100.1", "198.51.100.2"]
    assert "198.51.100.1" not in wan_ack.normalized_message
    assert "02:00:00:00:00:02" not in wan_ack.normalized_message
    assert wan_ack.raw_line.endswith("MAC 02:00:00:00:00:02")

    startup_service = next(event for event in parsed.events if event.component == "service")
    assert startup_service.structured_evidence["actor_names"] == ["SYNTHETIC-NODE-ALPHA"]
    assert "SYNTHETIC-NODE-ALPHA" not in startup_service.normalized_message


def tp_link_synthetic_snapshot(
    newest_first_records: list[str],
    *,
    export_time: str = "2042-06-15 12:00:00",
    firmware: str = "9.99.9 Build 20420101 rel.99999n",
    counts_line: str | None = "# Clients connected: 7 ; WI-FI : 5",
) -> str:
    headers = [
        "# SYNTHETIC-ARCHER-X9000 System Log",
        f"# Time = {export_time}",
        f"# H-Ver = SYNTHETIC-HW-9000 ; S-Ver = {firmware}",
        "# LAN I = 192.0.2.1 ; M = 255.255.255.0 ; MAC = 02:00:00:00:00:01",
        "# WAN I = 198.51.100.2 ; M = 255.255.255.0 ; MAC = 02:00:00:00:00:02",
        "# G = 198.51.100.1 ; DNS = 203.0.113.53 203.0.113.54",
    ]
    if counts_line is not None:
        headers.append(counts_line)
    return "\n".join([*headers, *newest_first_records])


@pytest.mark.parametrize(
    ("counts_line", "raw_total", "raw_wifi", "total", "wifi", "reason"),
    [
        (None, None, None, None, None, "missing_snapshot_counts"),
        ("# Clients connected: many ; WI-FI : 2", "many", "2", None, 2, "invalid_snapshot_counts"),
        ("# Clients connected: -1 ; WI-FI : 0", "-1", "0", -1, 0, "invalid_snapshot_counts"),
        ("# Clients connected: 3 ; WI-FI : 4", "3", "4", 3, 4, "inconsistent_snapshot_counts"),
    ],
    ids=("missing", "noninteger", "negative", "wifi-exceeds-total"),
)
def test_tp_link_snapshot_counts_are_one_correlated_diagnostic_set(
    counts_line: str | None,
    raw_total: str | None,
    raw_wifi: str | None,
    total: int | None,
    wifi: int | None,
    reason: str,
) -> None:
    text = tp_link_synthetic_snapshot(
        ["2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected"],
        counts_line=counts_line,
    )

    metrics = analyzer.parse_router_log(text, "synthetic-counts.log", "tp-link-archer").snapshot_metrics

    assert metrics is not None
    assert metrics.raw_total_clients == raw_total
    assert metrics.raw_wifi_clients == raw_wifi
    assert metrics.total_clients == total
    assert metrics.wifi_clients == wifi
    assert metrics.derived_wired_clients is None
    assert metrics.eligible is False
    assert metrics.exclusion_reason == reason


def test_tp_link_snapshot_counts_accept_the_digit_length_boundary() -> None:
    text = tp_link_synthetic_snapshot(
        ["2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected"],
        counts_line="# Clients connected: 999999999 ; WI-FI : 0",
    )

    metrics = analyzer.parse_router_log(text, "synthetic-count-boundary.log", "tp-link-archer").snapshot_metrics

    assert metrics == analyzer.RouterSnapshotMetrics(
        raw_total_clients="999999999",
        raw_wifi_clients="0",
        total_clients=999999999,
        wifi_clients=0,
        derived_wired_clients=999999999,
        eligible=True,
    )


@pytest.mark.parametrize(
    ("raw_total", "raw_wifi", "expected_wifi", "expected_reason"),
    [
        ("9" * 5000, "2", 2, "snapshot_count_out_of_range"),
        ("9" * 5000, "many", None, "invalid_snapshot_counts"),
        ("-" + ("9" * 5000), "0", 0, "invalid_snapshot_counts"),
    ],
    ids=("huge", "huge-with-noninteger", "huge-negative"),
)
def test_tp_link_snapshot_counts_bound_conversion_and_retain_raw_diagnostics(
    raw_total: str,
    raw_wifi: str,
    expected_wifi: int | None,
    expected_reason: str,
) -> None:
    text = tp_link_synthetic_snapshot(
        ["2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected"],
        counts_line=f"# Clients connected: {raw_total} ; WI-FI : {raw_wifi}",
    )

    metrics = analyzer.parse_router_log(text, "synthetic-huge-count.log", "tp-link-archer").snapshot_metrics

    assert metrics.raw_total_clients == raw_total
    assert metrics.raw_wifi_clients == raw_wifi
    assert metrics.total_clients is None
    assert metrics.wifi_clients == expected_wifi
    assert metrics.derived_wired_clients is None
    assert metrics.eligible is False
    assert metrics.exclusion_reason == expected_reason


def test_tp_link_body_parser_is_anchored_and_bounds_unknown_behavior_keys() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:59 vpn[77]: <4> 9901 Peer token-B closed",
        "2042-06-15 11:59:58 user@example.com: <4> 9901 PDF email noise",
        "2042-06-15 11:59:57 vpn[76]: <4> 9901 Peer token-A opened",
        "2042-06-15 11:59:56 invalid component[4]: <4> 9902 whitespace component",
        "2042-06-15 11:59:55 vpn: <4> not-numeric malformed code",
    ])

    parsed = analyzer.parse_router_log(text, "synthetic-anchoring.log", "tp-link-archer")

    assert [event.event_key for event in parsed.events] == ["VPN_9901_OTHER", "VPN_9901_OTHER"]
    assert parsed.parse_stats.parsed_events == 2
    assert parsed.parse_stats.malformed_lines == 3
    assert {event.component for event in parsed.events} == {"vpn"}
    assert {event.process_id for event in parsed.events} == {"76", "77"}


def test_tp_link_malformed_samples_do_not_create_a_persistence_side_channel() -> None:
    malformed = (
        "2042-06-15 11:59:58 user@example.com: <4> 9901 "
        "client SYNTHETIC-PRIVATE-NAME at 192.0.2.88"
    )
    text = tp_link_synthetic_snapshot([
        malformed,
        "2042-06-15 11:59:57 vpn[76]: <4> 9901 Synthetic valid record",
    ])

    parsed = analyzer.parse_router_log(text, "synthetic-malformed-privacy.log", "tp-link-archer")
    serialized_stats = json.dumps(analyzer.asdict(parsed.parse_stats), sort_keys=True)

    assert parsed.parse_stats.malformed_lines == 1
    assert parsed.parse_stats.malformed_samples == ["line 8: malformed TP-Link record"]
    assert malformed not in serialized_stats
    assert "SYNTHETIC-PRIVATE-NAME" not in serialized_stats
    assert "192.0.2.88" not in serialized_stats


def test_tp_link_privacy_reduction_precedes_identity_digest_boundaries() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:59 system[55]: <4> 9902 Contact client SYNTHETIC-CLIENT-OMEGA at 2001:db8::1234, 192.0.2.88, 02:00:00:00:00:02",
        "2042-06-15 11:59:58 system[54]: <5> 1000 System startup",
    ])

    parsed = analyzer.parse_router_log(text, "synthetic-privacy.log", "tp-link-archer")
    event = parsed.events[-1]
    candidate_persistent_fields = {
        "component": event.component,
        "process_id": event.process_id,
        "syslog_severity": event.syslog_severity,
        "vendor_event_code": event.vendor_event_code,
        "normalized_message": event.normalized_message,
        "event_key": event.event_key,
        "event_family": event.event_family,
        "actor_scope": event.actor_scope,
        "stable_client_identity": event.stable_client_identity,
        "structured_evidence": event.structured_evidence,
    }
    serialized = json.dumps(candidate_persistent_fields, sort_keys=True)

    assert event.normalized_message == (
        "normalized-message-v1\0Contact client <actor> at <ipv6>, <ipv4>, <mac>"
    )
    assert event.structured_evidence == {
        "action": "other",
        "actor_names": ["SYNTHETIC-CLIENT-OMEGA"],
        "ipv4_addresses": ["192.0.2.88"],
        "ipv6_addresses": ["2001:db8::1234"],
        "mac_addresses": ["02:00:00:00:00:02"],
    }
    assert event.raw_line.endswith("192.0.2.88, 02:00:00:00:00:02")
    assert event.raw_line not in serialized
    assert "Contact client SYNTHETIC-CLIENT-OMEGA" not in serialized
    assert parsed.boot_candidates[0].trusted_overlap_identities
    assert all(token.startswith("trusted-overlap-v1:") for token in parsed.boot_candidates[0].trusted_overlap_identities)
    assert parsed.boot_candidates[0].startup_signature.startswith("startup-signature-v1:")


def test_tp_link_privacy_reduction_replaces_address_like_tokens_even_when_invalid() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 system[55]: <4> 9902 Saw 999.999.999.999 and 2001:db8:::1234",
    ])

    event = analyzer.parse_router_log(text, "synthetic-address-like.log", "tp-link-archer").events[0]

    assert event.normalized_message == "normalized-message-v1\0Saw <ipv4> and <ipv6>"
    assert event.structured_evidence["ipv4_addresses"] == ["999.999.999.999"]
    assert event.structured_evidence["ipv6_addresses"] == ["2001:db8:::1234"]


def test_tp_link_privacy_reduction_handles_composite_and_punctuation_adjacent_addresses() -> None:
    message = (
        "Addresses IP:192.0.2.1 mapped ::ffff:192.0.2.9 compressed [2001:db8::7] "
        "full 2001:0db8:0000:0000:0000:0000:0000:0008 MAC(02:00:00:00:00:02)"
    )
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 system[55]: <4> 9902 {message}",
    ])

    event = analyzer.parse_router_log(text, "synthetic-address-redaction.log", "tp-link-archer").events[0]

    assert event.normalized_message == (
        "normalized-message-v1\0Addresses IP:<ipv4> mapped <ipv6> compressed <ipv6> "
        "full <ipv6> MAC(<mac>)"
    )
    assert event.structured_evidence["ipv4_addresses"] == ["192.0.2.1"]
    assert event.structured_evidence["ipv6_addresses"] == [
        "::ffff:192.0.2.9",
        "2001:db8::7",
        "2001:0db8:0000:0000:0000:0000:0000:0008",
    ]
    assert event.structured_evidence["mac_addresses"] == ["02:00:00:00:00:02"]
    for leaked_fragment in (
        "192.0.2.1", "192.0.2.9", "::ffff", "2001:db8", "0000:0008", "02:00:00:00:00:02",
    ):
        assert leaked_fragment not in event.normalized_message


def test_tp_link_privacy_reduction_handles_quoted_multitoken_and_email_actor_names() -> None:
    message = (
        'Contact client "SYNTHETIC ALPHA USER", user synthetic.beta@example.test; '
        "host: SYNTHETIC LAB NODE at 192.0.2.44"
    )
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 system[55]: <4> 9902 {message}",
    ])

    event = analyzer.parse_router_log(text, "synthetic-actor-redaction.log", "tp-link-archer").events[0]

    assert event.normalized_message == (
        "normalized-message-v1\0Contact client <actor>, user <actor>; host: <actor> at <ipv4>"
    )
    assert event.structured_evidence["actor_names"] == [
        "SYNTHETIC ALPHA USER", "synthetic.beta@example.test", "SYNTHETIC LAB NODE",
    ]
    assert event.structured_evidence["ipv4_addresses"] == ["192.0.2.44"]
    for actor_fragment in ("SYNTHETIC ALPHA", "synthetic.beta@", "LAB NODE"):
        assert actor_fragment not in event.normalized_message


def test_tp_link_privacy_reduction_handles_labeled_mac_punctuation_without_hex_overmatch() -> None:
    message = (
        "MAC:02:00:00:00:00:03 connected; mac-address=02:00:00:00:00:04 ready; "
        "digest dead:beef:cafe unchanged"
    )
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 system[55]: <4> 9902 {message}",
    ])

    event = analyzer.parse_router_log(text, "synthetic-labeled-mac.log", "tp-link-archer").events[0]

    assert event.normalized_message == (
        "normalized-message-v1\0MAC:<mac> connected; mac-address=<mac> ready; "
        "digest dead:beef:cafe unchanged"
    )
    assert event.structured_evidence["mac_addresses"] == [
        "02:00:00:00:00:03", "02:00:00:00:00:04",
    ]
    for leaked_fragment in ("02:00:00:00:00:03", "02:00:00:00:00:04"):
        assert leaked_fragment not in event.normalized_message


@pytest.mark.parametrize(
    ("decorated", "expected"),
    [
        ("<02:00:00:00:00:03>", "<<mac>>"),
        ("{02:00:00:00:00:03}", "{<mac>}"),
        ("/02:00:00:00:00:03/", "/<mac>/"),
        ("(02:00:00:00:00:03)", "(<mac>)"),
        ("[02:00:00:00:00:03]", "[<mac>]"),
        ("MAC:02:00:00:00:00:03", "MAC:<mac>"),
    ],
    ids=("angle", "brace", "slash", "parenthesis", "bracket", "label-colon"),
)
def test_tp_link_privacy_reduction_classifies_complete_mac_inside_delimiters(
    decorated: str,
    expected: str,
) -> None:
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 system[55]: <4> 9902 Peer {decorated} connected",
    ])

    event = analyzer.parse_router_log(text, "synthetic-delimited-mac.log", "tp-link-archer").events[0]

    assert event.normalized_message == f"normalized-message-v1\0Peer {expected} connected"
    assert event.structured_evidence["mac_addresses"] == ["02:00:00:00:00:03"]
    assert "02:00:00:00:00:03" not in event.normalized_message


def test_tp_link_privacy_reduction_preserves_trailing_mac_punctuation_and_prose() -> None:
    message = (
        "colon 02:00:00:00:00:03: connected; semicolon 02:00:00:00:00:04; ready; "
        "comma 02:00:00:00:00:05, accepted"
    )
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 system[55]: <4> 9902 {message}",
    ])

    event = analyzer.parse_router_log(text, "synthetic-trailing-mac.log", "tp-link-archer").events[0]

    assert event.normalized_message == (
        "normalized-message-v1\0colon <mac>: connected; semicolon <mac>; ready; "
        "comma <mac>, accepted"
    )
    assert event.structured_evidence["mac_addresses"] == [
        "02:00:00:00:00:03", "02:00:00:00:00:04", "02:00:00:00:00:05",
    ]


def test_tp_link_privacy_reduction_does_not_truncate_longer_colon_tokens_as_macs() -> None:
    message = (
        "pseudo 02:00:00:00:00:03:04; full 2001:0db8:0000:0000:0000:0000:0000:0008; "
        "compressed 2001:db8::9"
    )
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 system[55]: <4> 9902 {message}",
    ])

    event = analyzer.parse_router_log(text, "synthetic-long-colon-token.log", "tp-link-archer").events[0]

    assert event.normalized_message == (
        "normalized-message-v1\0pseudo <ipv6>; full <ipv6>; compressed <ipv6>"
    )
    assert "mac_addresses" not in event.structured_evidence
    assert event.structured_evidence["ipv6_addresses"] == [
        "02:00:00:00:00:03:04",
        "2001:0db8:0000:0000:0000:0000:0000:0008",
        "2001:db8::9",
    ]


def test_tp_link_privacy_reduction_canonicalizes_hyphenated_and_dotted_macs() -> None:
    message = (
        "hyphen <02-00-00-00-00-03>; dotted {0200.0000.0004}, "
        "slash /02-00-00-00-00-05/ ready"
    )
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 system[55]: <4> 9902 {message}",
    ])

    event = analyzer.parse_router_log(text, "synthetic-alternate-macs.log", "tp-link-archer").events[0]

    assert event.normalized_message == (
        "normalized-message-v1\0hyphen <<mac>>; dotted {<mac>}, slash /<mac>/ ready"
    )
    assert event.structured_evidence["mac_addresses"] == [
        "02:00:00:00:00:03", "02:00:00:00:00:04", "02:00:00:00:00:05",
    ]
    for leaked_fragment in ("02-00-00-00-00-03", "0200.0000.0004", "02-00-00-00-00-05"):
        assert leaked_fragment not in event.normalized_message


def test_tp_link_privacy_reduction_does_not_truncate_longer_alternate_mac_forms() -> None:
    message = "hyphen 02-00-00-00-00-03-04; dotted 0200.0000.0003.0004 unchanged"
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 system[55]: <4> 9902 {message}",
    ])

    event = analyzer.parse_router_log(text, "synthetic-long-alternate-macs.log", "tp-link-archer").events[0]

    assert event.normalized_message == f"normalized-message-v1\0{message}"
    assert "mac_addresses" not in event.structured_evidence


@pytest.mark.parametrize(
    ("lan_value", "wan_value", "message_mac"),
    [
        ("02-00-00-00-00-01", "02-00-00-00-00-02", "02-00-00-00-00-02"),
        ("0200.0000.0001", "0200.0000.0002", "0200.0000.0002"),
    ],
    ids=("hyphenated", "cisco-dotted"),
)
def test_tp_link_alternate_interface_mac_forms_are_canonical_router_owned_evidence(
    lan_value: str,
    wan_value: str,
    message_mac: str,
) -> None:
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 dhcpc[310]: <5> 1104 DHCP ACK for MAC {message_mac}",
    ]).replace(
        "MAC = 02:00:00:00:00:01", f"MAC = {lan_value}",
    ).replace(
        "MAC = 02:00:00:00:00:02", f"MAC = {wan_value}",
    )

    parsed = analyzer.parse_router_log(text, "synthetic-alternate-interface-mac.log", "tp-link-archer")

    assert parsed.identity.lan_mac == "02:00:00:00:00:01"
    assert parsed.identity.router_owned_interfaces == frozenset({
        "02:00:00:00:00:01", "02:00:00:00:00:02",
    })
    assert parsed.coverage_stats["lan"]["mac"] == "02:00:00:00:00:01"
    assert parsed.coverage_stats["wan"]["mac"] == "02:00:00:00:00:02"
    assert parsed.events[0].structured_evidence["mac_addresses"] == ["02:00:00:00:00:02"]
    assert parsed.events[0].mac == analyzer.SYSTEM_ACTOR
    assert parsed.events[0].stable_client_identity is None


def test_tp_link_privacy_reduction_handles_actor_labels_before_following_text() -> None:
    message = (
        "user alice@example.com connected; device:SYNTHETIC-NODE-ALPHA accepted; "
        "host=SYNTHETIC-NODE-BETA ready"
    )
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 system[55]: <4> 9902 {message}",
    ])

    event = analyzer.parse_router_log(text, "synthetic-following-actor.log", "tp-link-archer").events[0]

    assert event.normalized_message == (
        "normalized-message-v1\0user <actor> connected; device:<actor> accepted; "
        "host=<actor> ready"
    )
    assert event.structured_evidence["actor_names"] == [
        "alice@example.com", "SYNTHETIC-NODE-ALPHA", "SYNTHETIC-NODE-BETA",
    ]
    for leaked_fragment in ("alice@example.com", "SYNTHETIC-NODE-ALPHA", "SYNTHETIC-NODE-BETA"):
        assert leaked_fragment not in event.normalized_message


@pytest.mark.parametrize(
    "lan_mac",
    ["00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF", "01:00:5E:00:00:01", "not-a-mac"],
    ids=("all-zero", "broadcast", "multicast", "malformed"),
)
def test_tp_link_router_identity_candidate_requires_identity_grade_lan_mac(lan_mac: str) -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 dhcpc[310]: <5> 1104 DHCP ACK for MAC 02:00:00:00:00:02",
    ]).replace("MAC = 02:00:00:00:00:01", f"MAC = {lan_mac}")

    parsed = analyzer.parse_router_log(text, "synthetic-invalid-lan.log", "tp-link-archer")

    assert parsed.identity.lan_mac is None
    assert parsed.identity.persistence_safe_without_override is False
    assert parsed.identity.warnings == ("missing_or_invalid_lan_mac",)
    assert parsed.identity.router_owned_interfaces == frozenset({"02:00:00:00:00:02"})
    assert parsed.events[0].mac == analyzer.SYSTEM_ACTOR
    assert parsed.events[0].stable_client_identity is None
    assert parsed.events[0].actor_scope == "router"


@pytest.mark.parametrize(
    "malformed_mac",
    [
        "02:00:00:00:00:01:99",
        "junk02:00:00:00:00:01",
        "02:00:00:00:00:01junk",
        "02-00:00:00:00:01",
    ],
    ids=("seven-octet", "leading-junk", "trailing-junk", "mixed-separators"),
)
def test_tp_link_lan_header_mac_requires_an_exact_six_octet_field(malformed_mac: str) -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 system[55]: <4> 9902 Synthetic status",
    ]).replace("MAC = 02:00:00:00:00:01", f"MAC = {malformed_mac}")

    parsed = analyzer.parse_router_log(text, "synthetic-malformed-lan-mac.log", "tp-link-archer")

    assert parsed.identity.lan_mac is None
    assert parsed.identity.persistence_safe_without_override is False
    assert parsed.identity.router_owned_interfaces == frozenset({"02:00:00:00:00:02"})
    assert parsed.coverage_stats["lan"]["mac"] is None
    assert parsed.coverage_stats["lan"]["raw_mac"] == malformed_mac


@pytest.mark.parametrize(
    "malformed_mac",
    [
        "02:00:00:00:00:02:99",
        "junk02:00:00:00:00:02",
        "02:00:00:00:00:02junk",
        "02-00:00:00:00:02",
    ],
    ids=("seven-octet", "leading-junk", "trailing-junk", "mixed-separators"),
)
def test_tp_link_wan_header_mac_requires_an_exact_six_octet_field(malformed_mac: str) -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 dhcpc[310]: <5> 1104 DHCP ACK for synthetic WAN",
    ]).replace("MAC = 02:00:00:00:00:02", f"MAC = {malformed_mac}")

    parsed = analyzer.parse_router_log(text, "synthetic-malformed-wan-mac.log", "tp-link-archer")

    assert parsed.identity.lan_mac == "02:00:00:00:00:01"
    assert parsed.identity.persistence_safe_without_override is True
    assert parsed.identity.router_owned_interfaces == frozenset({"02:00:00:00:00:01"})
    assert parsed.identity.warnings == ("missing_or_invalid_wan_mac",)
    assert parsed.coverage_stats["wan"]["mac"] is None
    assert parsed.coverage_stats["wan"]["raw_mac"] == malformed_mac


def test_tp_link_maps_wan_release_and_disconnect_with_boot_context() -> None:
    emission_order = [
        "2042-06-15 11:50:00 system[101]: <5> 1000 System startup",
        "2042-06-15 11:50:01 dhcpc[310]: <5> 1105 DHCP RELEASE 198.51.100.2 from 02:00:00:00:00:02",
        "2042-06-15 11:50:02 inet[410]: <3> 3001 Internet disconnected",
    ]

    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(emission_order))),
        "synthetic-release-disconnect.log",
        "tp-link-archer",
    )

    assert [event.event_key for event in parsed.events] == [
        "ROUTER_BOOT", "WAN_DHCP_RELEASE", "INTERNET_DISCONNECTED",
    ]
    assert all(event.boot_context_id == "tp-link-boot-1" for event in parsed.events)
    assert all(event.actor_scope == "router" for event in parsed.events)
    assert all(event.stable_client_identity is None for event in parsed.events)


@pytest.mark.parametrize(
    ("code", "message", "expected_key"),
    [
        ("3002", "Internet up", "INTERNET_CONNECTED"),
        ("3002", "Internet is up", "INTERNET_CONNECTED"),
        ("3002", "Internet connected", "INTERNET_CONNECTED"),
        ("3002", "Internet is connected", "INTERNET_CONNECTED"),
        ("3002", "Internet connected.", "INTERNET_CONNECTED"),
        ("3001", "Internet down", "INTERNET_DISCONNECTED"),
        ("3001", "Internet is down", "INTERNET_DISCONNECTED"),
        ("3001", "Internet disconnected", "INTERNET_DISCONNECTED"),
        ("3001", "Internet is disconnected", "INTERNET_DISCONNECTED"),
        ("3001", "Internet is down!", "INTERNET_DISCONNECTED"),
    ],
)
def test_tp_link_maps_evidenced_internet_transition_phrases(
    code: str,
    message: str,
    expected_key: str,
) -> None:
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 inet[410]: <5> {code} {message}",
    ])

    event = analyzer.parse_router_log(text, "synthetic-internet-transition.log", "tp-link-archer").events[0]

    assert event.event_key == expected_key
    assert event.event_family == "WAN"


@pytest.mark.parametrize(
    ("component", "code", "message", "expected_key"),
    [
        ("dhcpc", "1101", "DHCP DISCOVER failed", "DHCPC_1101_FAILURE"),
        ("dhcpc", "1102", "DHCP OFFER failure", "DHCPC_1102_FAILURE"),
        ("dhcpc", "1103", "DHCP REQUEST denied", "DHCPC_1103_FAILURE"),
        ("dhcpc", "1104", "DHCP ACK unable to apply", "DHCPC_1104_FAILURE"),
        ("dhcpc", "1105", "DHCP RELEASE not completed", "DHCPC_1105_FAILURE"),
        ("inet", "3002", "Internet up failed", "INET_3002_FAILURE"),
        ("inet", "3002", "Internet not connected", "INET_3002_FAILURE"),
        ("system", "1000", "Router boot failed", "SYSTEM_1000_FAILURE"),
        ("system", "1000", "System startup unable to continue", "SYSTEM_1000_FAILURE"),
    ],
)
def test_tp_link_failed_or_negated_transition_evidence_never_becomes_success(
    component: str,
    code: str,
    message: str,
    expected_key: str,
) -> None:
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 {component}[410]: <3> {code} {message}",
    ])

    parsed = analyzer.parse_router_log(text, "synthetic-failed-transition.log", "tp-link-archer")
    event = parsed.events[0]

    assert event.event_key == expected_key
    assert event.event_family == "ROUTER_SYSTEM"
    assert event.structured_evidence["action"] == "failure"
    assert event.boot_context_id is None
    assert parsed.boot_candidates == []


@pytest.mark.parametrize(
    ("component", "code", "message", "expected_key"),
    [
        ("dhcpc", "9999", "DHCP ACK", "DHCPC_9999_ACK"),
        ("inet", "9999", "Internet connected", "INET_9999_CONNECTED"),
        ("system", "9999", "System startup", "SYSTEM_9999_START"),
        ("service", "3002", "Internet connected", "SERVICE_3002_CONNECTED"),
    ],
)
def test_tp_link_transition_phrases_require_adapter_approved_component_codes(
    component: str,
    code: str,
    message: str,
    expected_key: str,
) -> None:
    text = tp_link_synthetic_snapshot([
        f"2042-06-15 11:59:58 {component}[410]: <5> {code} {message}",
    ])

    parsed = analyzer.parse_router_log(text, "synthetic-unapproved-transition.log", "tp-link-archer")

    assert parsed.events[0].event_key == expected_key
    assert parsed.events[0].event_family == "ROUTER_SYSTEM"
    assert parsed.boot_candidates == []


def test_tp_link_routine_service_and_init_starts_do_not_create_boot_candidates() -> None:
    emission_order = [
        "2042-06-15 11:50:00 service[901]: <6> 9909 Start scheduled worker",
        "2042-06-15 11:50:01 init[902]: <6> 9910 Initialize synthetic cache",
        "2042-06-15 11:50:02 system[903]: <6> 9911 Start diagnostics",
    ]

    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(emission_order))),
        "synthetic-routine-starts.log",
        "tp-link-archer",
    )

    assert parsed.boot_candidates == []
    assert all(event.boot_context_id is None for event in parsed.events)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("2001", "Starting network services failed"),
        ("2003", "Initialize alternate network core denied"),
    ],
)
def test_tp_link_failed_startup_fragment_markers_do_not_create_boot_candidates(
    code: str,
    message: str,
) -> None:
    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot([
            f"2042-06-15 11:59:58 service[201]: <3> {code} {message}",
        ]),
        "synthetic-failed-startup-fragment.log",
        "tp-link-archer",
    )

    assert parsed.events[0].structured_evidence["action"] == "failure"
    assert parsed.events[0].boot_context_id is None
    assert parsed.boot_candidates == []


@pytest.mark.parametrize(
    ("component", "code", "message"),
    [
        ("inet", "3002", "Internet up timeout"),
        ("inet", "3002", "Internet connected unsuccessfully"),
        ("inet", "3002", "Internet up aborted"),
        ("inet", "3002", "Internet up? no"),
        ("inet", "3002", "Internet connected for synthetic maintenance"),
        ("inet", "3001", "Internet down canceled"),
        ("inet", "3001", "Internet down cancel"),
        ("inet", "3002", "Internet up abort"),
        ("dhcpc", "1104", "DHCP ACK timeout"),
        ("dhcpc", "1104", "DHCP ACK timed-out"),
        ("dhcpc", "1104", "Failed DHCP ACK"),
        ("dhcpc", "1104", "DHCP NAK"),
        ("dhcpc", "1101", "DHCP DISCOVER from synthetic-wan"),
        ("dhcpc", "1102", "DHCP OFFER synthetic-address from 198.51.100.1"),
        ("dhcpc", "1104", "DHCP ACK from synthetic-interface for 198.51.100.2"),
        ("dhcpc", "1104", "DHCP ACK for MAC 02:00:00:00:00:02:03"),
        ("dhcpc", "1103", "DHCP REQUEST for 198.51.100.2 retrying"),
        ("service", "2001", "Starting network services timeout"),
        ("service", "2001", "Starting network services for actor SYNTHETIC-NODE-ALPHA timed out"),
    ],
)
def test_tp_link_only_complete_approved_outcomes_create_transitions_or_startup_context(
    component: str,
    code: str,
    message: str,
) -> None:
    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot([
            f"2042-06-15 11:59:58 {component}[201]: <3> {code} {message}",
        ]),
        "synthetic-non-outcome.log",
        "tp-link-archer",
    )
    event = parsed.events[0]

    assert event.event_key not in {
        "WAN_DHCP_DISCOVER", "WAN_DHCP_OFFER", "WAN_DHCP_REQUEST", "WAN_DHCP_ACK",
        "WAN_DHCP_RELEASE", "INTERNET_CONNECTED", "INTERNET_DISCONNECTED", "ROUTER_BOOT",
    }
    assert event.event_family == "ROUTER_SYSTEM"
    assert event.boot_context_id is None
    assert parsed.boot_candidates == []


@pytest.mark.parametrize(
    ("code", "message", "expected_key"),
    [
        ("1101", "DHCP DISCOVER", "WAN_DHCP_DISCOVER"),
        ("1101", "DHCP DISCOVER!", "WAN_DHCP_DISCOVER"),
        ("1101", "DHCP DISCOVER from 02-00-00-00-00-02", "WAN_DHCP_DISCOVER"),
        ("1102", "DHCP OFFER 198.51.100.2 from 198.51.100.1", "WAN_DHCP_OFFER"),
        ("1102", "DHCP OFFER 2001:db8::2 from 2001:db8::1", "WAN_DHCP_OFFER"),
        ("1103", "DHCP REQUEST for 198.51.100.2", "WAN_DHCP_REQUEST"),
        (
            "1104",
            "DHCP ACK from 198.51.100.1 for 198.51.100.2 with MAC 02:00:00:00:00:02",
            "WAN_DHCP_ACK",
        ),
        (
            "1104",
            "DHCP ACK from [2001:db8::1] for [2001:db8::2] with MAC 0200.0000.0002",
            "WAN_DHCP_ACK",
        ),
        ("1104", "DHCP ACK for MAC 02-00-00-00-00-02", "WAN_DHCP_ACK"),
        ("1105", "DHCP RELEASE 198.51.100.2 from 02:00:00:00:00:02", "WAN_DHCP_RELEASE"),
    ],
)
def test_tp_link_wan_dhcp_transitions_require_complete_approved_grammars(
    code: str,
    message: str,
    expected_key: str,
) -> None:
    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot([
            f"2042-06-15 11:59:58 dhcpc[310]: <5> {code} {message}",
        ]),
        "synthetic-approved-dhcp.log",
        "tp-link-archer",
    )

    assert parsed.events[0].event_key == expected_key
    assert parsed.events[0].event_family == "WAN_DHCP"


@pytest.mark.parametrize(
    ("component", "code", "message", "expected_event_key"),
    [
        ("system", "1000", "System startup", "ROUTER_BOOT"),
        ("system", "1000", "Router boot!", "ROUTER_BOOT"),
        ("system", "1000", "Router booting.", "ROUTER_BOOT"),
        ("service", "2001", "Starting network services", "SERVICE_2001_START"),
        (
            "service", "2001", "Starting network services for actor SYNTHETIC-NODE-ALPHA",
            "SERVICE_2001_START",
        ),
        (
            "service", "2001", "Starting network services for actor synthetic@example.invalid",
            "SERVICE_2001_START",
        ),
        (
            "service", "2001", 'Starting network services for actor "SYNTHETIC NODE ALPHA"',
            "SERVICE_2001_START",
        ),
        ("service", "2003", "Initialize alternate network core", "SERVICE_2003_INITIALIZE"),
    ],
)
def test_tp_link_boot_context_requires_complete_approved_startup_grammars(
    component: str,
    code: str,
    message: str,
    expected_event_key: str,
) -> None:
    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot([
            f"2042-06-15 11:59:58 {component}[201]: <5> {code} {message}",
        ]),
        "synthetic-approved-startup.log",
        "tp-link-archer",
    )

    assert parsed.events[0].event_key == expected_event_key
    assert parsed.events[0].boot_context_id == "tp-link-boot-1"
    assert len(parsed.boot_candidates) == 1


def test_tp_link_missing_optional_headers_warn_without_discarding_body() -> None:
    text = "\n".join([
        "# SYNTHETIC-ARCHER-X9000 System Log",
        "# Time = 2042-06-15 12:00:00",
        "# LAN I = 192.0.2.1 ; M = 255.255.255.0 ; MAC = 02:00:00:00:00:01",
        "2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected",
    ])

    parsed = analyzer.parse_router_log(text, "synthetic-incomplete-header.log", "tp-link-archer")

    assert [event.event_key for event in parsed.events] == ["INTERNET_CONNECTED"]
    assert parsed.warnings == [
        "missing_hardware_header",
        "missing_firmware_header",
        "missing_wan_header",
        "missing_client_counts_header",
    ]
    assert parsed.snapshot_metrics.exclusion_reason == "missing_snapshot_counts"


def test_tp_link_invalid_export_time_warns_without_crashing_body_parse() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected",
    ]).replace("# Time = 2042-06-15 12:00:00", "# Time = 2042-99-99 99:99:99")

    parsed = analyzer.parse_router_log(text, "synthetic-invalid-export-time.log", "tp-link-archer")

    assert parsed.export_timestamp is None
    assert "missing_export_time_header" in parsed.warnings
    assert [event.event_key for event in parsed.events] == ["INTERNET_CONNECTED"]
    assert parsed.events[0].clock_trust == "clock_untrusted"
    assert parsed.events[0].clock_reason == "missing_export_timestamp"
    assert parsed.coverage_stats["timing_eligible_records"] == 0
    assert parsed.coverage_stats["run_span_start"] is None
    assert parsed.coverage_stats["run_span_end"] is None


def test_tp_link_missing_export_time_withholds_all_calendar_timing_evidence() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected",
    ]).replace("# Time = 2042-06-15 12:00:00\n", "")

    parsed = analyzer.parse_router_log(text, "synthetic-missing-export-time.log", "tp-link-archer")

    assert parsed.export_timestamp is None
    assert parsed.events[0].clock_trust == "clock_untrusted"
    assert parsed.events[0].clock_reason == "missing_export_timestamp"
    assert parsed.events[0].trusted_overlap_identity is None
    assert parsed.coverage_stats["trusted_records"] == 0
    assert parsed.coverage_stats["timing_eligible_records"] == 0
    assert parsed.coverage_stats["run_span_start"] is None
    assert parsed.coverage_stats["run_span_end"] is None
    assert "clock_untrusted_missing_export_timestamp" in parsed.warnings


def test_tp_link_export_future_tolerance_is_inclusive_and_later_events_are_ambiguous() -> None:
    emission_order = [
        "2042-06-15 12:05:00 service[201]: <6> 9901 Boundary sample",
        "2042-06-15 12:05:01 service[201]: <6> 9901 Beyond boundary sample",
    ]

    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(emission_order))),
        "synthetic-export-future-boundary.log",
        "tp-link-archer",
    )

    assert [event.clock_trust for event in parsed.events] == ["trusted", "clock_ambiguous"]
    assert [event.clock_reason for event in parsed.events] == [None, "after_export_tolerance"]
    assert parsed.coverage_stats["timing_eligible_records"] == 1
    assert parsed.coverage_stats["run_span_start"] == "2042-06-15T12:05:00"
    assert parsed.coverage_stats["run_span_end"] == "2042-06-15T12:05:00"


@pytest.mark.parametrize(
    ("event_time", "expected_trust", "expected_reason"),
    [
        ("2099-01-01 00:00:00", "clock_ambiguous", "after_export_tolerance"),
        ("2030-01-01 00:00:00", "clock_untrusted", "no_near_export_anchor"),
    ],
    ids=("far-future-year", "far-past-unanchored"),
)
def test_tp_link_implausible_unanchored_calendar_years_are_not_trusted(
    event_time: str,
    expected_trust: str,
    expected_reason: str,
) -> None:
    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot([
            f"{event_time} service[201]: <6> 9901 Synthetic health sample",
        ]),
        "synthetic-implausible-year.log",
        "tp-link-archer",
    )

    assert parsed.events[0].clock_trust == expected_trust
    assert parsed.events[0].clock_reason == expected_reason
    assert parsed.events[0].trusted_overlap_identity is None
    assert parsed.coverage_stats["timing_eligible_records"] == 0
    assert parsed.coverage_stats["run_span_start"] is None
    assert parsed.coverage_stats["run_span_end"] is None


def test_tp_link_missing_wan_gateway_dns_continuation_warns() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected",
    ]).replace("# G = 198.51.100.1 ; DNS = 203.0.113.53 203.0.113.54\n", "")

    parsed = analyzer.parse_router_log(text, "synthetic-missing-wan-continuation.log", "tp-link-archer")

    assert "missing_wan_gateway_dns_header" in parsed.warnings
    assert parsed.coverage_stats["wan"]["gateway"] is None
    assert parsed.coverage_stats["wan"]["dns"] == []


@pytest.mark.parametrize(
    ("existing_line", "conflicting_line", "private_marker"),
    [
        (
            "# SYNTHETIC-ARCHER-X9000 System Log",
            "# SYNTHETIC-CONFLICT-MODEL System Log",
            "SYNTHETIC-CONFLICT-MODEL",
        ),
        (
            "# Time = 2042-06-15 12:00:00",
            "# Time = 2043-07-16 13:01:01",
            "2043-07-16",
        ),
        (
            "# H-Ver = SYNTHETIC-HW-9000 ; S-Ver = 9.99.9 Build 20420101 rel.99999n",
            "# H-Ver = SYNTHETIC-CONFLICT-HW ; S-Ver = 8.88.8 Build 20430101 rel.88888n",
            "SYNTHETIC-CONFLICT-HW",
        ),
        (
            "# LAN I = 192.0.2.1 ; M = 255.255.255.0 ; MAC = 02:00:00:00:00:01",
            "# LAN I = 192.0.2.9 ; M = 255.255.255.0 ; MAC = 02:00:00:00:00:09",
            "02:00:00:00:00:09",
        ),
        (
            "# WAN I = 198.51.100.2 ; M = 255.255.255.0 ; MAC = 02:00:00:00:00:02",
            "# WAN I = 198.51.100.9 ; M = 255.255.255.0 ; MAC = 02:00:00:00:00:0A",
            "02:00:00:00:00:0A",
        ),
        (
            "# G = 198.51.100.1 ; DNS = 203.0.113.53 203.0.113.54",
            "# G = 198.51.100.9 ; DNS = 203.0.113.99",
            "203.0.113.99",
        ),
        (
            "# Clients connected: 7 ; WI-FI : 5",
            "# Clients connected: 9 ; WI-FI : 8",
            "9 ; WI-FI : 8",
        ),
    ],
    ids=("model", "time", "version", "lan", "wan", "wan-continuation", "counts"),
)
def test_tp_link_conflicting_repeated_headers_fail_closed_without_echoing_values(
    existing_line: str,
    conflicting_line: str,
    private_marker: str,
) -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected",
    ]).replace(existing_line, f"{existing_line}\n{conflicting_line}")

    with pytest.raises(SystemExit, match="Conflicting TP-Link") as exc_info:
        analyzer.parse_router_log(text, "synthetic-conflicting-header.log", "tp-link-archer")

    assert private_marker not in str(exc_info.value)


def test_tp_link_identical_repeated_headers_are_accepted_deterministically() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected",
    ])
    repeated = "\n".join(
        [item for line in text.splitlines() for item in ([line, line] if line.startswith("#") else [line])]
    )

    parsed = analyzer.parse_router_log(repeated, "synthetic-identical-headers.log", "tp-link-archer")

    assert parsed.model == "SYNTHETIC-ARCHER-X9000"
    assert parsed.export_timestamp == datetime(2042, 6, 15, 12, 0, 0)
    assert parsed.identity.lan_mac == "02:00:00:00:00:01"
    assert parsed.identity.router_owned_interfaces == frozenset({
        "02:00:00:00:00:01", "02:00:00:00:00:02",
    })
    assert parsed.snapshot_metrics.eligible is True


def test_tp_link_conflicting_identity_headers_reject_before_cli_database_or_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_lan = "# LAN I = 192.0.2.1 ; M = 255.255.255.0 ; MAC = 02:00:00:00:00:01"
    conflicting_lan = "# LAN I = 192.0.2.99 ; M = 255.255.255.0 ; MAC = 02:00:00:00:00:09"
    log_path = tmp_path / "synthetic-conflicting-identity.log"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text(
        tp_link_synthetic_snapshot([
            "2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected",
        ]).replace(original_lan, f"{original_lan}\n{conflicting_lan}"),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="Conflicting TP-Link") as exc_info:
        analyzer.main([
            str(log_path), "--format", "tp-link-archer", "--json", "--db", str(db_path),
        ])

    captured = capsys.readouterr()
    assert "02:00:00:00:00:09" not in str(exc_info.value)
    assert captured.out == ""
    assert captured.err == ""
    assert not db_path.exists()


def test_tp_link_already_correct_boot_time_is_trusted_and_anchored() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-06-15 11:59:58 service[201]: <6> 2002 Network services ready",
        "2042-06-15 11:59:57 system[101]: <5> 1000 System startup",
    ])

    parsed = analyzer.parse_router_log(text, "synthetic-correct-boot.log", "tp-link-archer")

    assert [event.clock_trust for event in parsed.events] == ["trusted", "trusted"]
    assert len(parsed.boot_candidates) == 1
    assert parsed.boot_candidates[0].trusted_anchor == datetime(2042, 6, 15, 11, 59, 57)
    assert parsed.coverage_stats["run_span_start"] == "2042-06-15T11:59:57"
    assert parsed.coverage_stats["run_span_end"] == "2042-06-15T11:59:58"


def test_tp_link_two_boot_epochs_keep_both_synchronized_segments_trusted() -> None:
    emission_order = [
        "2042-01-01 00:00:01 system[101]: <5> 1000 System startup",
        "2042-01-01 00:00:02 service[201]: <6> 2001 Starting network services",
        "2042-06-13 13:00:00 dhcpc[301]: <6> 1101 DHCP DISCOVER",
        "2042-06-13 13:10:00 service[201]: <6> 2002 Network services ready",
        "2042-01-01 00:00:01 system[102]: <5> 1000 System startup",
        "2042-01-01 00:00:02 service[202]: <6> 2001 Starting network services",
        "2042-06-15 11:00:00 dhcpc[302]: <6> 1101 DHCP DISCOVER",
        "2042-06-15 11:01:00 inet[402]: <5> 3002 Internet connected",
    ]
    text = tp_link_synthetic_snapshot(list(reversed(emission_order)))

    parsed = analyzer.parse_router_log(text, "synthetic-two-boots.log", "tp-link-archer")

    assert [event.clock_trust for event in parsed.events] == [
        "pre_synchronization", "pre_synchronization", "trusted", "trusted",
        "pre_synchronization", "pre_synchronization", "trusted", "trusted",
    ]
    assert len(parsed.boot_candidates) == 2
    assert [candidate.trusted_anchor for candidate in parsed.boot_candidates] == [
        datetime(2042, 6, 13, 13, 0, 0),
        datetime(2042, 6, 15, 11, 0, 0),
    ]
    assert parsed.boot_candidates[0].session_id != parsed.boot_candidates[1].session_id
    assert parsed.boot_candidates[0].startup_signature == parsed.boot_candidates[1].startup_signature
    assert parsed.coverage_stats["trusted_records"] == 4


def test_tp_link_genuine_later_reboot_with_correct_time_gets_distinct_context() -> None:
    emission_order = [
        "2042-06-14 10:00:00 system[101]: <5> 1000 System startup",
        "2042-06-14 10:00:05 service[201]: <6> 2002 Network services ready",
        "2042-06-15 11:00:00 system[102]: <5> 1000 System startup",
        "2042-06-15 11:00:05 service[202]: <6> 2002 Network services ready",
    ]

    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(emission_order))),
        "synthetic-real-reboot.log",
        "tp-link-archer",
    )

    assert [event.clock_trust for event in parsed.events] == ["trusted"] * 4
    assert len(parsed.boot_candidates) == 2
    assert [event.boot_context_id for event in parsed.events] == [
        "tp-link-boot-1", "tp-link-boot-1", "tp-link-boot-2", "tp-link-boot-2",
    ]
    assert [candidate.trusted_anchor for candidate in parsed.boot_candidates] == [
        datetime(2042, 6, 14, 10, 0, 0),
        datetime(2042, 6, 15, 11, 0, 0),
    ]


def test_tp_link_truncated_firmware_date_startup_is_untrusted_and_anchorless() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-01-01 00:00:02 service[201]: <6> 2001 Starting network services",
        "2042-01-01 00:00:01 system[101]: <5> 1000 System startup",
    ])

    parsed = analyzer.parse_router_log(text, "synthetic-truncated-presync.log", "tp-link-archer")

    assert [event.clock_trust for event in parsed.events] == ["pre_synchronization", "pre_synchronization"]
    assert parsed.boot_candidates[0].trusted_anchor is None
    assert parsed.boot_candidates[0].warnings == ("no_trusted_boot_anchor",)
    assert parsed.coverage_stats["timing_eligible_records"] == 0
    assert parsed.coverage_stats["run_span_start"] is None
    assert parsed.coverage_stats["run_span_end"] is None


def test_tp_link_truncated_startup_fragment_without_boot_line_still_has_run_local_context() -> None:
    text = tp_link_synthetic_snapshot([
        "2042-01-01 00:00:03 service[201]: <6> 2002 Network services ready",
        "2042-01-01 00:00:02 service[201]: <6> 2001 Starting network services",
    ])

    parsed = analyzer.parse_router_log(text, "synthetic-truncated-startup-fragment.log", "tp-link-archer")

    assert [event.clock_trust for event in parsed.events] == ["pre_synchronization", "pre_synchronization"]
    assert [event.boot_context_id for event in parsed.events] == ["tp-link-boot-1", "tp-link-boot-1"]
    assert len(parsed.boot_candidates) == 1
    assert parsed.boot_candidates[0].trusted_anchor is None
    assert parsed.boot_candidates[0].warnings == ("no_trusted_boot_anchor",)


def test_tp_link_nonboot_local_time_rollback_withholds_only_ambiguous_interval() -> None:
    emission_order = [
        "2042-06-15 11:00:00 service[201]: <6> 2002 Network services ready",
        "2042-06-15 11:10:00 inet[401]: <5> 3002 Internet connected",
        "2042-06-15 10:30:00 service[201]: <6> 9901 Health sample A",
        "2042-06-15 10:31:00 service[201]: <6> 9901 Health sample B",
        "2042-06-15 11:11:00 service[201]: <6> 9901 Health sample C",
    ]

    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(emission_order))),
        "synthetic-clock-rollback.log",
        "tp-link-archer",
    )

    assert [event.clock_trust for event in parsed.events] == [
        "trusted", "trusted", "clock_ambiguous", "clock_ambiguous", "trusted",
    ]
    assert parsed.coverage_stats["trusted_records"] == 3
    assert parsed.coverage_stats["run_span_start"] == "2042-06-15T11:00:00"
    assert parsed.coverage_stats["run_span_end"] == "2042-06-15T11:11:00"


def test_tp_link_boot_boundary_backward_jump_starts_untrusted_epoch() -> None:
    emission_order = [
        "2042-06-15 11:00:00 system[101]: <5> 1000 System startup",
        "2042-06-15 11:10:00 service[201]: <6> 2002 Network services ready",
        "2042-06-15 10:00:00 system[102]: <5> 1000 System startup",
        "2042-06-15 10:00:05 service[202]: <6> 2001 Starting network services",
    ]

    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(emission_order))),
        "synthetic-boot-rollback.log",
        "tp-link-archer",
    )

    assert [event.clock_trust for event in parsed.events] == [
        "trusted", "trusted", "clock_untrusted", "clock_untrusted",
    ]
    assert len(parsed.boot_candidates) == 2
    assert parsed.boot_candidates[0].trusted_anchor == datetime(2042, 6, 15, 11, 0, 0)
    assert parsed.boot_candidates[1].trusted_anchor is None
    assert all(event.clock_trust != "clock_ambiguous" for event in parsed.events[2:])


def test_tp_link_multiple_clock_corrections_create_independent_segments() -> None:
    emission_order = [
        "2042-01-01 00:00:01 system[101]: <5> 1000 System startup",
        "2042-01-01 00:00:02 service[201]: <6> 2001 Starting network services",
        "2042-06-15 10:00:00 service[201]: <6> 2002 Network services ready",
        "2042-06-15 09:30:00 service[201]: <6> 9901 Health sample rollback",
        "2042-06-15 10:01:00 inet[401]: <5> 3002 Internet connected",
    ]

    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(emission_order))),
        "synthetic-multiple-corrections.log",
        "tp-link-archer",
    )

    assert [event.clock_trust for event in parsed.events] == [
        "pre_synchronization", "pre_synchronization", "trusted", "clock_ambiguous", "trusted",
    ]
    assert [segment.clock_trust for segment in parsed.clock_segments] == [
        "pre_synchronization", "trusted", "clock_ambiguous", "trusted",
    ]
    assert all(
        segment.start_sequence is not None
        and segment.end_sequence is not None
        and segment.start_sequence <= segment.end_sequence
        for segment in parsed.clock_segments
    )


def test_tp_link_clock_segment_sequence_endpoints_are_numeric_source_bounds() -> None:
    parsed = analyzer.parse_router_log(
        TP_LINK_SYNTHETIC_FIXTURE.read_text(encoding="utf-8"),
        "synthetic-segment-bounds.log",
        "tp-link-archer",
    )

    assert [
        (segment.start_sequence, segment.end_sequence)
        for segment in parsed.clock_segments
    ] == [(13, 14), (8, 12)]


@pytest.mark.parametrize(
    ("export_time", "corrected_time"),
    [
        ("2042-01-04 00:00:00", "2042-01-02 00:00:00"),
        ("2042-06-15 12:00:00", "2042-06-15 12:05:00"),
    ],
    ids=("exactly-48-hours-before-export", "exactly-5-minutes-after-export"),
)
def test_tp_link_clock_correction_accepts_inclusive_boundary_thresholds(
    export_time: str,
    corrected_time: str,
) -> None:
    emission_order = [
        "2042-01-01 00:00:00 system[101]: <5> 1000 System startup",
        f"{corrected_time} service[201]: <6> 2002 Network services ready",
    ]

    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(
            list(reversed(emission_order)),
            export_time=export_time,
            firmware="9.99.9 Build 20420101 rel.99999n",
        ),
        "synthetic-clock-boundary.log",
        "tp-link-archer",
    )

    assert [event.clock_trust for event in parsed.events] == ["pre_synchronization", "trusted"]


def test_tp_link_five_minute_local_rollback_remains_trusted() -> None:
    emission_order = [
        "2042-06-15 11:00:00 service[201]: <6> 2002 Network services ready",
        "2042-06-15 11:10:00 inet[401]: <5> 3002 Internet connected",
        "2042-06-15 11:05:00 service[201]: <6> 9901 Health sample boundary",
    ]

    parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(emission_order))),
        "synthetic-five-minute-rollback.log",
        "tp-link-archer",
    )

    assert [event.clock_trust for event in parsed.events] == ["trusted", "trusted", "trusted"]


def test_tp_link_every_trusted_record_exposes_session_independent_overlap_identity() -> None:
    emission_order = [
        "2042-06-15 11:58:00 service[201]: <6> 9901 Synthetic sample A",
        "2042-06-15 11:59:00 service[202]: <6> 9901 Synthetic sample B",
    ]
    text = tp_link_synthetic_snapshot(list(reversed(emission_order)))

    first = analyzer.parse_router_log(text, "synthetic-no-startup-a.log", "tp-link-archer")
    second = analyzer.parse_router_log(text, "synthetic-no-startup-b.log", "tp-link-archer")

    assert first.boot_candidates == []
    assert all(event.clock_trust == "trusted" for event in first.events)
    assert all(event.trusted_overlap_identity is not None for event in first.events)
    assert first.trusted_overlap_identities == tuple(
        event.trusted_overlap_identity for event in first.events
    )
    assert first.trusted_overlap_identities == second.trusted_overlap_identities
    assert len(set(first.trusted_overlap_identities)) == 2
    assert all(identity.startswith("trusted-overlap-v1:") for identity in first.trusted_overlap_identities)

    first_event = first.events[0]
    expected = analyzer.TpLinkArcherAdapter._versioned_digest("trusted-overlap-v1", (
        "tp-link",
        "02:00:00:00:00:01",
        first_event.timestamp.isoformat(sep=" "),
        first_event.component,
        first_event.process_id,
        first_event.vendor_event_code,
        first_event.syslog_severity,
        first_event.normalized_message,
        first_event.actor_scope,
        first_event.stable_client_identity,
    ))
    assert first_event.trusted_overlap_identity == expected


def test_tp_link_untrusted_records_do_not_receive_trusted_overlap_identity() -> None:
    parsed = analyzer.parse_router_log(
        TP_LINK_SYNTHETIC_FIXTURE.read_text(encoding="utf-8"),
        "synthetic-mixed-clock.log",
        "tp-link-archer",
    )

    assert [event.trusted_overlap_identity is None for event in parsed.events] == [
        True, True, False, False, False, False, False,
    ]
    assert parsed.trusted_overlap_identities == tuple(
        event.trusted_overlap_identity for event in parsed.events if event.clock_trust == "trusted"
    )


def test_tp_link_startup_signature_ignores_unrelated_later_start_actions() -> None:
    core = [
        "2042-06-15 11:50:00 system[101]: <5> 1000 System startup",
        "2042-06-15 11:50:01 service[201]: <6> 2001 Starting network services",
        "2042-06-15 11:50:02 service[201]: <6> 2002 Network services ready",
    ]
    with_later_start = [
        *core,
        "2042-06-15 11:55:00 service[999]: <6> 9909 Start unrelated synthetic worker",
    ]

    core_parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(core))),
        "synthetic-startup-core.log",
        "tp-link-archer",
    )
    extended_parsed = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(with_later_start))),
        "synthetic-startup-extended.log",
        "tp-link-archer",
    )

    assert core_parsed.boot_candidates[0].startup_signature == (
        extended_parsed.boot_candidates[0].startup_signature
    )


def test_tp_link_startup_signature_changes_with_distinct_core_startup_evidence() -> None:
    first_core = [
        "2042-06-15 11:50:00 system[101]: <5> 1000 System startup",
        "2042-06-15 11:50:01 service[201]: <6> 2001 Starting network services",
        "2042-06-15 11:50:02 service[201]: <6> 2002 Network services ready",
    ]
    second_core = [
        "2042-06-15 11:50:00 system[101]: <5> 1000 System startup",
        "2042-06-15 11:50:01 service[201]: <6> 2003 Initialize alternate network core",
        "2042-06-15 11:50:02 service[201]: <6> 2002 Network services ready",
    ]

    first = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(first_core))),
        "synthetic-startup-core-a.log",
        "tp-link-archer",
    )
    second = analyzer.parse_router_log(
        tp_link_synthetic_snapshot(list(reversed(second_core))),
        "synthetic-startup-core-b.log",
        "tp-link-archer",
    )

    assert first.boot_candidates[0].startup_signature != second.boot_candidates[0].startup_signature


@pytest.mark.parametrize("router_override", [None, "synthetic-router-instance"])
@pytest.mark.parametrize("use_presync_fixture", [False, True], ids=("trusted", "pre-sync"))
def test_tp_link_cli_stays_nonpersistent_before_router_schema_support(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    router_override: str | None,
    use_presync_fixture: bool,
) -> None:
    log_path = tmp_path / "synthetic-tp-link.log"
    db_path = tmp_path / "must-not-exist.db"
    if use_presync_fixture:
        text = TP_LINK_SYNTHETIC_FIXTURE.read_text(encoding="utf-8")
    else:
        text = tp_link_synthetic_snapshot([
            "2042-06-15 11:59:58 inet[410]: <5> 3002 Internet connected",
        ])
    log_path.write_text(text, encoding="utf-8")
    argv = [str(log_path), "--format", "tp-link-archer", "--json", "--db", str(db_path)]
    if router_override is not None:
        argv.extend(["--router-instance", router_override])

    assert analyzer.main(argv) == 0
    first_report = json.loads(capsys.readouterr().out)
    assert analyzer.main(argv) == 0
    second_report = json.loads(capsys.readouterr().out)

    assert first_report == second_report
    assert first_report["format_id"] == analyzer.FORMAT_TP_LINK_ARCHER
    assert first_report["persistence"] == {
        "available": False,
        "reason": "tp_link_persistence_not_implemented",
    }
    assert not db_path.exists()
    assert list(tmp_path.iterdir()) == [log_path]


@pytest.mark.parametrize("router_override", [None, "synthetic-router-instance"])
def test_tp_link_cli_rejects_stateful_combination_before_database_creation(
    tmp_path: Path,
    router_override: str | None,
) -> None:
    log_path = tmp_path / "synthetic-tp-link.log"
    baseline_path = tmp_path / "synthetic-baseline.json"
    db_path = tmp_path / "must-not-exist.db"
    log_path.write_text(TP_LINK_SYNTHETIC_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    baseline_path.write_text(json.dumps({"devices": {}}), encoding="utf-8")
    argv = [
        str(log_path),
        "--format", "tp-link-archer",
        "--import-baseline", str(baseline_path),
        "--db", str(db_path),
    ]
    if router_override is not None:
        argv.extend(["--router-instance", router_override])

    with pytest.raises(SystemExit, match="TP-Link persistence is not implemented"):
        analyzer.main(argv)

    assert not db_path.exists()


def test_router_instance_override_is_vendor_scoped_and_opaque() -> None:
    netgear_key = analyzer.router_instance_override_key("netgear", "  synthetic-router  ")
    tp_link_key = analyzer.router_instance_override_key("tp-link", "synthetic-router")

    assert netgear_key == analyzer.router_instance_override_key("netgear", "synthetic-router")
    assert netgear_key != tp_link_key
    assert "synthetic-router" not in netgear_key
    assert re.fullmatch(r"[0-9a-f]{64}", netgear_key)


@pytest.mark.parametrize("override", ["synthetic\u0085router", "synthetic\u009frouter"])
def test_router_instance_override_rejects_all_unicode_control_characters(override: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        analyzer.validate_router_instance_override(override)

    assert "router-instance" in str(exc_info.value)
    assert override not in str(exc_info.value)


def test_parse_log_text_normalizes_internet_transition_events() -> None:
    events, stats = analyzer.parse_log_text(
        "\n".join(
            [
                "[Internet disconnected], Tuesday, July 14, 2037 04:17:02",
                "[Internet connected], Tuesday, July 14, 2037 04:19:45",
            ]
        ),
        source="router.log",
    )

    assert stats.parsed_events == 2
    assert [event.event_key for event in events] == [
        "INTERNET_DISCONNECTED",
        "INTERNET_CONNECTED",
    ]
    assert all(event.mac == analyzer.SYSTEM_ACTOR for event in events)


def test_parse_log_text_reconstructs_wrapped_access_rejection_timestamp() -> None:
    events, stats = analyzer.parse_log_text(
        "\n".join(
            [
                "[WLAN access rejected: incorrect security] from MAC address 02:00:00:00:00:04, Wednesday, March 25, 2037",
                "13:11:47",
            ]
        ),
        source="test",
    )

    assert stats.parsed_events == 1
    assert stats.malformed_lines == 0
    assert events[0].event_key == "WLAN_ACCESS_REJECTED"
    assert events[0].event_family == "WLAN_REJECTED"
    assert events[0].mac == "02:00:00:00:00:04"
    assert events[0].timestamp == datetime(2037, 3, 25, 13, 11, 47)


def test_parse_log_text_ignores_wrapped_access_control_status_line() -> None:
    events, stats = analyzer.parse_log_text(
        "\n".join(
            [
                "[Access Control] Device RokuUltra with MAC Address 02:00:00:00:00:05 is allowed to access the, Thursday, April",
                "02, 2037 04:18:12",
            ]
        ),
        source="test",
    )

    assert events == []
    assert stats.parsed_events == 0
    assert stats.malformed_lines == 0
    assert stats.ignored_lines == 1
    assert stats.malformed_samples == []


def test_parse_log_text_ignores_truncated_wrapped_access_control_status_line() -> None:
    events, stats = analyzer.parse_log_text(
        "\n".join(
            [
                "[Access Control] Device SYNTHETIC OUTLET with MAC Address 02:00:00:00:00:06 is allowed to acce, Thursday, April 02,",
                "2037 04:18:12",
            ]
        ),
        source="test",
    )

    assert events == []
    assert stats.parsed_events == 0
    assert stats.malformed_lines == 0
    assert stats.ignored_lines == 1


def test_parse_log_text_ignores_severely_truncated_access_control_status_line() -> None:
    events, stats = analyzer.parse_log_text(
        "[Access Control] Device android-a7a560af9888aea8 with MAC Address 02:00:00:00:00:07 is allowe, Thursday, April 02, 2037 04:18:12",
        source="test",
    )

    assert events == []
    assert stats.parsed_events == 0
    assert stats.malformed_lines == 0
    assert stats.ignored_lines == 1


def test_aggregate_events_attributes_ip_only_events_to_known_dhcp_mac() -> None:
    events, stats = analyzer.parse_log_text(
        "\n".join(
            [
                "[DHCP IP: (192.0.2.25)] to MAC address 02:00:00:00:00:08, Saturday, March 21, 2037 08:07:26",
                "[admin login] from source 192.0.2.25, Saturday, March 21, 2037 08:32:33",
            ]
        ),
        source="test",
    )

    assert stats.parsed_events == 2

    aggregate = analyzer.aggregate_events(
        events,
        {"devices": {"02:00:00:00:00:08": {"name": "SYNTHETIC COMPUTER"}}},
        {"02:00:00:00:00:08": {"name": "SYNTHETIC COMPUTER"}},
    )
    by_key = {event.event_key: event for event in aggregate["events"]}
    summary = {item["mac"]: item for item in analyzer.summarize_devices(aggregate)}

    assert by_key["ADMIN_LOGIN"].mac == "02:00:00:00:00:08"
    assert summary["02:00:00:00:00:08"]["total_events"] == 2
    assert "ADMIN_LOGIN" in summary["02:00:00:00:00:08"]["event_types"]
    assert "__SYSTEM__" not in summary


def test_new_event_type_is_reported_when_device_has_history_but_event_is_new(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:08"
        for index, history_date in enumerate(["2037-03-17", "2037-03-18", "2037-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26"],
            )
        current_stat = make_current_stat(
            "2037-03-21",
            mac,
            "ADMIN_LOGIN",
            "OTHER",
            ["2037-03-21T08:32:33"],
        )
        aggregate = {"event_day_stats": {("2037-03-21", mac, "ADMIN_LOGIN"): current_stat}}
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_new_event_types(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "new_event_type"
        assert findings[0].severity == "medium"
        assert findings[0].metadata["event_key"] == "ADMIN_LOGIN"
        assert findings[0].metadata["history_count"] == 3
    finally:
        store.close()


def test_new_event_type_single_wlan_access_allowed_for_configured_device_is_low(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:08"
        for index, history_date in enumerate(["2037-03-17", "2037-03-18", "2037-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26"],
            )
        current_stat = make_current_stat(
            "2037-03-21",
            mac,
            "WLAN_ACCESS_ALLOWED",
            "WLAN_ALLOWED",
            ["2037-03-21T08:32:33"],
        )
        aggregate = {
            "event_day_stats": {("2037-03-21", mac, "WLAN_ACCESS_ALLOWED"): current_stat},
            "devices_snapshot": {
                mac: {
                    "status": "allowed",
                    "source": "config_import",
                }
            },
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_new_event_types(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "new_event_type"
        assert findings[0].severity == "low"
    finally:
        store.close()


def test_new_event_type_repeated_wlan_access_allowed_for_configured_device_stays_medium(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:08"
        for index, history_date in enumerate(["2037-03-17", "2037-03-18", "2037-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26"],
            )
        current_stat = make_current_stat(
            "2037-03-21",
            mac,
            "WLAN_ACCESS_ALLOWED",
            "WLAN_ALLOWED",
            ["2037-03-21T08:32:33", "2037-03-21T08:33:00"],
        )
        aggregate = {
            "event_day_stats": {("2037-03-21", mac, "WLAN_ACCESS_ALLOWED"): current_stat},
            "devices_snapshot": {
                mac: {
                    "status": "allowed",
                    "source": "config_import",
                }
            },
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_new_event_types(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "new_event_type"
        assert findings[0].severity == "medium"
    finally:
        store.close()


def test_new_event_type_detail_lines_show_observed_times_and_history() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "new_event_type",
            "rendered_message": "Admin Login was first observed for SYNTHETIC COMPUTER on 2037-03-21.",
            "metadata": {
                "history_count": 3,
                "observed_timestamps": ["2037-03-21T08:32:33"],
            },
        }
    )

    assert "Observed times: 8:32:33 AM" in lines
    assert "No prior occurrences in 3 learned day(s) for this device" in lines


def test_single_wlan_access_allowed_behavior_for_configured_device_is_capped_to_low(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:01"
        insert_history_day(
            store,
            epoch_id,
            "history-1",
            "2037-03-16",
            mac,
            "WLAN_ACCESS_ALLOWED",
            "WLAN_ALLOWED",
            ["2037-03-16T08:00:00"],
        )
        current_stat = make_current_stat(
            "2037-03-17",
            mac,
            "WLAN_ACCESS_ALLOWED",
            "WLAN_ALLOWED",
            ["2037-03-17T13:00:00"],
        )
        aggregate = {
            "event_day_stats": {("2037-03-17", mac, "WLAN_ACCESS_ALLOWED"): current_stat},
            "mac_to_name": {mac: "Kindle Paperwhite"},
            "devices_snapshot": {
                mac: {
                    "status": "allowed",
                    "source": "config_import",
                }
            },
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_event_behavior_anomalies(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "event_behavior_anomaly"
        assert findings[0].severity == "low"
        assert findings[0].metadata["reasons"] == ["time shift 5 hours"]
    finally:
        store.close()


def test_compute_risk_score_deduplicates_correlated_event_findings() -> None:
    findings = {
        "all": [
            analyzer.Finding(
                kind="new_event_type",
                severity="medium",
                mac="02:00:00:00:00:04",
                message="",
                metadata={
                    "day": "2037-03-25",
                    "event_key": "WLAN_ACCESS_REJECTED",
                    "event_family": "WLAN_REJECTED",
                },
            ),
            analyzer.Finding(
                kind="event_behavior_anomaly",
                severity="low",
                mac="02:00:00:00:00:04",
                message="",
                metadata={
                    "day": "2037-03-25",
                    "event_key": "WLAN_ACCESS_REJECTED",
                    "event_family": "WLAN_REJECTED",
                    "reasons": ["time shift 5 minutes"],
                },
            ),
            analyzer.Finding(
                kind="dhcp_anomaly",
                severity="low",
                mac="02:00:00:00:00:04",
                message="",
                metadata={"day": "2037-03-25"},
            ),
        ]
    }
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

    score, status, breakdown = analyzer.compute_risk_score(findings, policy)

    assert score == 12
    assert status == "Clean"
    assert breakdown == {"new_event_type": 10, "dhcp_anomaly": 2}


def test_compute_risk_score_deduplicates_same_day_cluster_findings() -> None:
    findings = {
        "all": [
            analyzer.Finding(
                kind="cluster_anomaly",
                severity="medium",
                mac=None,
                message="cluster anomaly 1",
                metadata={
                    "cluster": "SYNTHETIC_OUTLETS",
                    "day": "2037-03-25",
                    "occurrence_index": 0,
                    "start": "2037-03-25T16:06:21",
                },
            ),
            analyzer.Finding(
                kind="cluster_anomaly",
                severity="medium",
                mac=None,
                message="cluster anomaly 2",
                metadata={
                    "cluster": "SYNTHETIC_OUTLETS",
                    "day": "2037-03-25",
                    "occurrence_index": 1,
                    "start": "2037-03-25T23:15:26",
                },
            ),
        ]
    }
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

    score, status, breakdown = analyzer.compute_risk_score(findings, policy)

    assert score == 12
    assert status == "Clean"
    assert breakdown == {"cluster_anomaly": 12}


def test_enforce_policy_severity_supports_maximum_and_suppress() -> None:
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
    policy["event_overrides"]["WLAN_ACCESS_REJECTED"] = {"maximum_severity": "low"}
    policy["device_overrides"]["02:00:00:00:00:04"] = {"suppress": True}

    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            event_key="WLAN_ACCESS_REJECTED",
            event_family="WLAN_REJECTED",
        )
        == "low"
    )
    assert (
        analyzer.enforce_policy_severity(
            "critical",
            policy,
            mac="02:00:00:00:00:04",
            event_key="WLAN_ACCESS_REJECTED",
            event_family="WLAN_REJECTED",
        )
        == "normal"
    )


def test_enforce_policy_severity_supports_finding_specific_device_and_cluster_caps() -> None:
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
    policy["device_overrides"]["02:00:00:00:00:04"] = {
        "finding_overrides": {
            "event_volume_anomaly": {"maximum_severity": "low"}
        }
    }
    policy["device_name_overrides"]["SYNTHETIC DEVICE"] = {
        "finding_overrides": {
            "event_volume_anomaly": {"maximum_severity": "low"}
        }
    }
    policy["cluster_overrides"]["SYNTHETIC_OUTLETS"] = {
        "finding_overrides": {
            "cluster_anomaly": {"maximum_severity": "low"}
        }
    }

    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            mac="02:00:00:00:00:04",
            finding_kind="event_volume_anomaly",
        )
        == "low"
    )
    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            device_name="SYNTHETIC DEVICE",
            finding_kind="event_volume_anomaly",
        )
        == "low"
    )
    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            mac="02:00:00:00:00:04",
            finding_kind="new_event_type",
        )
        == "medium"
    )
    assert (
        analyzer.enforce_policy_severity(
            "medium",
            policy,
            event_key="DHCP_IP",
            event_family="DHCP",
            finding_kind="cluster_anomaly",
            cluster_name="SYNTHETIC_OUTLETS",
        )
        == "low"
    )


def test_detect_unknown_devices_respects_device_suppression() -> None:
    mac = "02:00:00:00:00:09"
    aggregate = {
        "events_by_mac": {
            mac: [
                analyzer.Event(
                    timestamp=datetime(2037, 3, 25, 13, 11, 47),
                    mac=mac,
                    event_family="OTHER",
                    event_key="ADMIN_LOGIN",
                    ip=None,
                    raw_label="admin login",
                    raw_line="",
                    source="test",
                )
            ]
        },
        "cluster_profiles": {},
    }
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
    policy["device_overrides"][mac] = {"suppress": True}

    findings = analyzer.detect_unknown_devices(aggregate, {"devices": {}}, {}, policy)

    assert findings == []


def test_detect_device_metric_anomalies_respects_event_volume_cap(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:04"
        for index, history_date in enumerate(["2037-03-17", "2037-03-18", "2037-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26", f"{history_date}T08:10:00", f"{history_date}T08:12:00"],
            )
        current_device_stat = analyzer.DeviceDayAggregate(observed_date="2037-03-25", mac=mac)
        for minute in range(10):
            current_device_stat.add_event(
                analyzer.Event(
                    timestamp=datetime(2037, 3, 25, 13, minute, 0),
                    mac=mac,
                    event_family="DHCP",
                    event_key="DHCP_IP",
                    ip=f"192.0.2.{minute + 10}",
                    raw_label="DHCP IP",
                    raw_line="",
                    source="test",
                )
            )
        aggregate = {
            "device_day_stats": {("2037-03-25", mac): current_device_stat},
            "mac_to_name": {mac: "SYNTHETIC DEVICE"},
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
        policy["device_overrides"][mac] = {
            "finding_overrides": {"event_volume_anomaly": {"maximum_severity": "low"}}
        }

        findings = analyzer.detect_device_metric_anomalies(aggregate, {"devices": {}}, store, epoch_id, policy)
        event_volume = next(finding for finding in findings if finding.kind == "event_volume_anomaly")

        assert event_volume.severity == "low"
    finally:
        store.close()


def test_detect_device_metric_anomalies_respects_device_name_event_volume_cap(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:0A"
        device_name = "SYNTHETIC DEVICE"
        for index, history_date in enumerate(["2037-03-17", "2037-03-18", "2037-03-19"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"name-history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26", f"{history_date}T08:10:00", f"{history_date}T08:12:00"],
            )
        current_device_stat = analyzer.DeviceDayAggregate(observed_date="2037-03-25", mac=mac)
        for minute in range(10):
            current_device_stat.add_event(
                analyzer.Event(
                    timestamp=datetime(2037, 3, 25, 13, minute, 0),
                    mac=mac,
                    event_family="DHCP",
                    event_key="DHCP_IP",
                    ip=f"192.0.2.{minute + 30}",
                    raw_label="DHCP IP",
                    raw_line="",
                    source="test",
                )
            )
        aggregate = {
            "device_day_stats": {("2037-03-25", mac): current_device_stat},
            "mac_to_name": {mac: device_name},
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
        policy["device_name_overrides"][device_name] = {
            "finding_overrides": {"event_volume_anomaly": {"maximum_severity": "low"}}
        }

        findings = analyzer.detect_device_metric_anomalies(aggregate, {"devices": {}}, store, epoch_id, policy)
        event_volume = next(finding for finding in findings if finding.kind == "event_volume_anomaly")

        assert event_volume.severity == "low"
    finally:
        store.close()


def test_device_metric_profile_adapts_to_repeated_metric_only_anomalies(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:0B"
        history_counts = [
            ("2037-05-15", 39, "event_volume_anomaly"),
            ("2037-05-16", 20, "event_volume_anomaly"),
            ("2037-05-17", 21, "event_volume_anomaly"),
            ("2037-05-18", 2, None),
            ("2037-05-19", 26, "event_volume_anomaly"),
            ("2037-05-20", 27, "event_volume_anomaly"),
            ("2037-05-21", 23, "event_volume_anomaly"),
        ]
        for history_date, count, exclusion_reason in history_counts:
            timestamps = [f"{history_date}T08:{minute:02d}:00" for minute in range(count)]
            run_id = insert_history_day(
                store,
                epoch_id,
                f"metric-history-{history_date}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                timestamps,
            )
            if exclusion_reason:
                mark_device_day_excluded(store, run_id, mac, exclusion_reason)

        current_device_stat = analyzer.DeviceDayAggregate(observed_date="2037-05-22", mac=mac)
        for minute in range(34):
            current_device_stat.add_event(
                analyzer.Event(
                    timestamp=datetime(2037, 5, 22, 9, minute, 0),
                    mac=mac,
                    event_family="DHCP",
                    event_key="DHCP_IP",
                    ip=f"192.0.2.{minute + 10}",
                    raw_label="DHCP IP",
                    raw_line="",
                    source="test",
                )
            )
        aggregate = {
            "device_day_stats": {("2037-05-22", mac): current_device_stat},
            "mac_to_name": {mac: 'MBP 16"'},
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_device_metric_anomalies(aggregate, {"devices": {}}, store, epoch_id, policy)

        assert findings == []
    finally:
        store.close()


def test_device_metric_profile_keeps_partial_runs_out_of_adaptive_baseline(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:0B"
        for history_date, count in [("2037-05-12", 1), ("2037-05-13", 2), ("2037-05-14", 2)]:
            timestamps = [f"{history_date}T08:{minute:02d}:00" for minute in range(count)]
            insert_history_day(
                store,
                epoch_id,
                f"clean-history-{history_date}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                timestamps,
            )
        for history_date, count in [("2037-05-15", 39), ("2037-05-16", 20), ("2037-05-17", 21)]:
            timestamps = [f"{history_date}T08:{minute:02d}:00" for minute in range(count)]
            run_id = insert_history_day(
                store,
                epoch_id,
                f"partial-history-{history_date}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                timestamps,
            )
            mark_device_day_excluded(store, run_id, mac, "partial_run")

        current_device_stat = analyzer.DeviceDayAggregate(observed_date="2037-05-18", mac=mac)
        for minute in range(30):
            current_device_stat.add_event(
                analyzer.Event(
                    timestamp=datetime(2037, 5, 18, 9, minute, 0),
                    mac=mac,
                    event_family="DHCP",
                    event_key="DHCP_IP",
                    ip=f"192.0.2.{minute + 40}",
                    raw_label="DHCP IP",
                    raw_line="",
                    source="test",
                )
            )
        aggregate = {
            "device_day_stats": {("2037-05-18", mac): current_device_stat},
            "mac_to_name": {mac: 'MBP 16"'},
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_device_metric_anomalies(aggregate, {"devices": {}}, store, epoch_id, policy)

        assert {finding.kind for finding in findings} == {"dhcp_anomaly", "event_volume_anomaly"}
        assert all(finding.severity == "high" for finding in findings)
        assert all(finding.metadata["learned_mean"] == 1.67 for finding in findings)
    finally:
        store.close()


def test_detect_cluster_anomalies_respects_cluster_cap(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        stat = analyzer.SubjectBehaviorDayAggregate(
            observed_date="2037-03-25",
            subject_key="SYNTHETIC_OUTLETS",
            subject_type="group",
            behavior_key="DHCP_IP",
            behavior_family="DHCP",
        )
        stat.add_occurrence(
            start=datetime(2037, 3, 25, 16, 6, 21),
            end=datetime(2037, 3, 25, 16, 8, 28),
            size=4,
            context={
                "member_macs": [
                    "02:00:00:00:00:0C",
                    "02:00:00:00:00:0D",
                    "02:00:00:00:00:0E",
                    "02:00:00:00:00:06",
                ],
                "member_events": [
                    {"name": "SYNTHETIC OUTLET", "mac": "02:00:00:00:00:0C", "timestamp": "2037-03-25T16:06:21"},
                    {"name": "SYNTHETIC OUTLET", "mac": "02:00:00:00:00:0D", "timestamp": "2037-03-25T16:07:23"},
                ],
            },
        )
        aggregate = {
            "subject_behavior_day_stats": {
                ("2037-03-25", "SYNTHETIC_OUTLETS", "group", "DHCP_IP"): stat
            },
            "cluster_profiles": {
                "SYNTHETIC_OUTLETS": {
                    "cluster_size": 4,
                    "expected_windows": [{"start_hour": 1.75, "end_hour": 2.0}],
                }
            },
            "mac_to_name": {
                "02:00:00:00:00:0C": "SYNTHETIC OUTLET",
                "02:00:00:00:00:0D": "SYNTHETIC OUTLET",
            },
        }
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
        policy["cluster_overrides"]["SYNTHETIC_OUTLETS"] = {
            "finding_overrides": {"cluster_anomaly": {"maximum_severity": "low"}}
        }

        findings = analyzer.detect_cluster_anomalies(aggregate, store, epoch_id, policy)

        assert findings
        assert all(finding.severity == "low" for finding in findings)
    finally:
        store.close()


def test_build_priority_findings_surfaces_security_events_first() -> None:
    mac = "02:00:00:00:00:04"
    findings = {
        "critical": [],
        "observations": [
            analyzer.Finding(
                kind="event_volume_anomaly",
                severity="low",
                mac=mac,
                message="",
                metadata={
                    "day": "2037-03-25",
                    "expected_range": [1.0, 3.0],
                    "direction": "above",
                    "learned_mean": 2.0,
                    "trend": "flat",
                },
            )
        ],
        "anomalies": [
            analyzer.Finding(
                kind="cluster_anomaly",
                severity="medium",
                mac=None,
                message="",
                metadata={
                    "cluster": "SYNTHETIC_OUTLETS",
                    "day": "2037-03-25",
                    "distance_minutes": 581,
                    "member_events": [
                        {"name": "SYNTHETIC OUTLET", "mac": "02:00:00:00:00:0D", "timestamp": "2037-03-25T16:07:23"}
                    ],
                },
            ),
            analyzer.Finding(
                kind="new_event_type",
                severity="medium",
                mac=mac,
                message="",
                metadata={
                    "day": "2037-03-25",
                    "event_key": "WLAN_ACCESS_REJECTED",
                    "event_family": "WLAN_REJECTED",
                    "history_count": 8,
                    "observed_timestamps": ["2037-03-25T13:11:47"],
                },
            ),
        ],
        "all": [],
    }
    findings["all"] = findings["observations"] + findings["anomalies"]
    aggregate = make_aggregate({mac: "SYNTHETIC DEVICE"})

    findings_dict = analyzer.findings_to_dict(findings, aggregate)
    priority = analyzer.build_priority_findings(findings_dict)

    assert priority[0]["kind"] == "new_event_type"
    assert "WLAN Access Rejected" in priority[0]["rendered_message"]


def test_cluster_partial_visibility_detail_lines_do_not_report_zero_minutes() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "cluster_anomaly",
            "severity": "low",
            "event_count": 1,
            "rendered_message": "",
            "metadata": {
                "cluster": "SYNTHETIC_OUTLETS",
                "day": "2037-03-25",
                "expected_size": 4,
                "min_cluster_size": 2,
                "member_events": [
                    {"name": "SYNTHETIC OUTLET", "mac": "02:00:00:00:00:0D", "timestamp": "2037-03-25T23:15:26"}
                ],
            },
        }
    )

    assert lines[0] == "SYNTHETIC_OUTLETS on 2037-03-25: observed 1 of expected 4 device(s)."
    assert all("0 minutes outside expected timing" not in line for line in lines)


def test_render_text_report_uses_finding_index_and_device_grouping() -> None:
    iphone_finding = {
        "kind": "new_event_type",
        "severity": "medium",
        "mac": "02:00:00:00:00:04",
        "device_label": "SYNTHETIC DEVICE (02:00:00:00:00:02)",
        "rendered_message": "WLAN Access Rejected was first observed for SYNTHETIC DEVICE on 2037-03-25.",
        "metadata": {
            "day": "2037-03-25",
            "event_key": "WLAN_ACCESS_REJECTED",
            "history_count": 8,
            "observed_timestamps": ["2037-03-25T13:11:47"],
        },
    }
    volume_finding = {
        "kind": "event_volume_anomaly",
        "severity": "low",
        "mac": "02:00:00:00:00:04",
        "device_label": "SYNTHETIC DEVICE (02:00:00:00:00:02)",
        "event_count": 9,
        "rendered_message": "Daily event count for SYNTHETIC DEVICE on 2037-03-25 was slightly above expected range.",
        "metadata": {
            "day": "2037-03-25",
            "expected_range": [1.17, 5.38],
            "direction": "above",
            "learned_mean": 3.27,
            "trend": "flat",
        },
    }
    cluster_finding = {
        "kind": "cluster_anomaly",
        "severity": "low",
        "mac": None,
        "event_count": 1,
        "rendered_message": "",
        "metadata": {
            "cluster": "SYNTHETIC_OUTLETS",
            "day": "2037-03-25",
            "expected_size": 4,
            "min_cluster_size": 2,
            "member_events": [
                {"name": "SYNTHETIC OUTLET", "mac": "02:00:00:00:00:0D", "timestamp": "2037-03-25T23:15:26"}
            ],
        },
    }
    report = {
        "parse_stats": {
            "parsed_events": 1,
            "malformed_lines": 0,
            "duplicate_events": 0,
            "spam_filtered": 0,
            "export_noise_lines": 0,
            "malformed_samples": [],
        },
        "observation_range": {"start": "2037-03-25T13:11:47", "end": "2037-03-25T13:11:47"},
        "state": {"deduplicated": False},
        "inputs": {"db": "/tmp/network.db"},
        "risk_score": 10,
        "status": "Clean",
        "risk_breakdown": {"new_event_type": 10},
        "priority_findings": [iphone_finding],
        "findings": {
            "critical": [],
            "anomalies": [],
            "observations": [volume_finding, cluster_finding],
            "all": [iphone_finding, volume_finding, cluster_finding],
        },
        "device_summary": [],
    }

    rendered = analyzer.render_text_report(report)

    assert rendered.index("Finding Index") < rendered.index("Findings by Device/Group")
    assert "MEDIUM  SYNTHETIC DEVICE" in rendered
    assert "First observed WLAN Access Rejected" in rendered
    assert rendered.count("SYNTHETIC DEVICE") >= 2
    assert "LOW | event_volume_anomaly" in rendered
    assert "Count   : 9 observed vs 1.17-5.38 expected" in rendered
    assert "SYNTHETIC_OUTLETS" in rendered
    assert "Device group" in rendered
    assert "Observed: 1 of expected 4 device(s)" in rendered
    assert "SYNTHETIC OUTLET (02:00:00:00:00:0D) at 11:15:26 PM" in rendered


def test_rare_event_activity_is_reported_for_repeat_sparse_other_event(tmp_path: Path) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        mac = "02:00:00:00:00:08"
        insert_history_day(
            store,
            epoch_id,
            "admin-login-history",
            "2037-03-17",
            mac,
            "ADMIN_LOGIN",
            "OTHER",
            ["2037-03-17T08:32:33"],
        )
        for index, history_date in enumerate(["2037-03-16", "2037-03-18", "2037-03-19", "2037-03-20"], start=1):
            insert_history_day(
                store,
                epoch_id,
                f"dhcp-history-{index}",
                history_date,
                mac,
                "DHCP_IP",
                "DHCP",
                [f"{history_date}T08:07:26"],
            )
        current_stat = make_current_stat(
            "2037-03-21",
            mac,
            "ADMIN_LOGIN",
            "OTHER",
            ["2037-03-21T08:45:00"],
        )
        aggregate = {"event_day_stats": {("2037-03-21", mac, "ADMIN_LOGIN"): current_stat}}
        policy = copy.deepcopy(analyzer.DEFAULT_POLICY)

        findings = analyzer.detect_rare_event_activity(aggregate, store, epoch_id, policy)

        assert len(findings) == 1
        assert findings[0].kind == "rare_event_activity"
        assert findings[0].severity == "medium"
        assert findings[0].metadata["history_count"] == 1
        assert findings[0].metadata["observed_device_days"] == 5
        assert findings[0].metadata["learned_presence_rate"] == 0.2
    finally:
        store.close()


def test_rare_event_activity_detail_lines_show_rarity_context() -> None:
    lines = analyzer.finding_detail_lines(
        {
            "kind": "rare_event_activity",
            "rendered_message": "Admin Login remains rare for SYNTHETIC COMPUTER on 2037-03-21.",
            "metadata": {
                "history_count": 1,
                "observed_device_days": 5,
                "learned_presence_rate": 0.2,
                "observed_timestamps": ["2037-03-21T08:32:33"],
            },
        }
    )

    assert "Observed times: 8:32:33 AM" in lines
    assert "Learned rarity: 1 prior occurrence day(s) across 5 learned day(s) (20% presence)" in lines


def test_detect_network_incidents_merges_wan_flaps_and_attributes_recovery() -> None:
    baseline, snapshot, macs = incident_devices(6)
    events = [
        make_event("2037-07-14T04:17:02", analyzer.SYSTEM_ACTOR, "INTERNET_DISCONNECTED"),
        make_event("2037-07-14T04:19:08", analyzer.SYSTEM_ACTOR, "INTERNET_CONNECTED"),
        make_event("2037-07-14T04:19:12", analyzer.SYSTEM_ACTOR, "INTERNET_DISCONNECTED"),
        make_event("2037-07-14T04:19:45", analyzer.SYSTEM_ACTOR, "INTERNET_CONNECTED"),
        make_event("2037-07-14T04:18:30", macs[0], "DHCP_IP"),
        *[make_event("2037-07-14T04:18:12", mac, "WLAN_ACCESS_ALLOWED") for mac in macs],
    ]

    incidents = analyzer.detect_network_incidents(
        events, baseline, snapshot, copy.deepcopy(analyzer.DEFAULT_POLICY)
    )

    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.confidence == "confirmed"
    assert incident.disconnect_count == 2
    assert incident.connect_count == 2
    assert incident.affected_macs == sorted(macs)
    assert incident.explained_event_count == 11
    assert all(event.incident_id == incident.incident_id for event in events)


def test_network_incident_attribution_preserves_security_activity() -> None:
    baseline, snapshot, macs = incident_devices(5)
    unknown_mac = "02:00:00:00:00:09"
    blocked_mac = "02:00:00:00:00:0F"
    snapshot[blocked_mac] = {"name": "Blocked", "status": "blocked", "source": "config_import"}
    protected_events = [
        make_event("2037-07-14T04:18:20", unknown_mac, "DHCP_IP"),
        make_event("2037-07-14T04:18:21", blocked_mac, "WLAN_ACCESS_ALLOWED"),
        make_event("2037-07-14T04:18:22", macs[0], "WLAN_ACCESS_REJECTED"),
        make_event("2037-07-14T04:18:23", macs[0], "ADMIN_LOGIN"),
    ]
    events = [
        make_event("2037-07-14T04:17:02", analyzer.SYSTEM_ACTOR, "INTERNET_DISCONNECTED"),
        make_event("2037-07-14T04:19:08", analyzer.SYSTEM_ACTOR, "INTERNET_CONNECTED"),
        *[make_event("2037-07-14T04:18:12", mac, "WLAN_ACCESS_ALLOWED") for mac in macs],
        *protected_events,
    ]

    incidents = analyzer.detect_network_incidents(
        events, baseline, snapshot, copy.deepcopy(analyzer.DEFAULT_POLICY)
    )

    assert len(incidents) == 1
    assert all(event.incident_id is None for event in protected_events)


def test_detect_network_incidents_infers_strong_burst_without_wan_markers() -> None:
    baseline, snapshot, macs = incident_devices(8)
    events = [
        *[
            make_event(f"2037-07-14T04:18:{index:02d}", mac, "WLAN_ACCESS_ALLOWED")
            for index, mac in enumerate(macs)
        ],
        make_event("2037-07-14T04:18:30", macs[0], "DHCP_IP"),
    ]

    incidents = analyzer.detect_network_incidents(
        events, baseline, snapshot, copy.deepcopy(analyzer.DEFAULT_POLICY)
    )

    assert len(incidents) == 1
    assert incidents[0].confidence == "probable"
    assert incidents[0].disconnect_count == 0
    assert incidents[0].connect_count == 0
    assert incidents[0].affected_macs == sorted(macs)


def test_detect_network_incidents_rejects_small_burst_and_unpaired_outage() -> None:
    baseline, snapshot, macs = incident_devices(8)
    small_burst = [
        make_event(f"2037-07-14T04:18:{index:02d}", mac, "WLAN_ACCESS_ALLOWED")
        for index, mac in enumerate(macs[:7])
    ]
    small_burst.append(make_event("2037-07-14T04:18:30", macs[0], "DHCP_IP"))
    assert analyzer.detect_network_incidents(
        small_burst, baseline, snapshot, copy.deepcopy(analyzer.DEFAULT_POLICY)
    ) == []

    unpaired = [
        make_event("2037-07-14T04:17:02", analyzer.SYSTEM_ACTOR, "INTERNET_DISCONNECTED"),
        *[
            make_event(f"2037-07-14T04:18:{index:02d}", mac, "WLAN_ACCESS_ALLOWED")
            for index, mac in enumerate(macs)
        ],
        make_event("2037-07-14T04:18:30", macs[0], "DHCP_IP"),
    ]
    assert analyzer.detect_network_incidents(
        unpaired, baseline, snapshot, copy.deepcopy(analyzer.DEFAULT_POLICY)
    ) == []
    assert all(event.incident_id is None for event in unpaired)

    stale_activity = [
        make_event("2037-07-14T01:00:00", analyzer.SYSTEM_ACTOR, "INTERNET_DISCONNECTED"),
        *[make_event("2037-07-14T02:00:00", mac, "DHCP_IP") for mac in macs],
        make_event("2037-07-14T04:00:00", analyzer.SYSTEM_ACTOR, "INTERNET_CONNECTED"),
    ]
    assert analyzer.detect_network_incidents(
        stale_activity, baseline, snapshot, copy.deepcopy(analyzer.DEFAULT_POLICY)
    ) == []


def test_detect_network_incidents_supports_cross_midnight_recovery() -> None:
    baseline, snapshot, macs = incident_devices(5)
    events = [
        make_event("2037-07-14T23:59:30", analyzer.SYSTEM_ACTOR, "INTERNET_DISCONNECTED"),
        *[make_event("2037-07-15T00:00:20", mac, "DHCP_IP") for mac in macs],
        make_event("2037-07-15T00:01:00", analyzer.SYSTEM_ACTOR, "INTERNET_CONNECTED"),
    ]

    incidents = analyzer.detect_network_incidents(
        events, baseline, snapshot, copy.deepcopy(analyzer.DEFAULT_POLICY)
    )

    assert len(incidents) == 1
    assert incidents[0].start == "2037-07-14T23:59:30"
    assert incidents[0].restored_at == "2037-07-15T00:01:00"


def test_network_reset_excludes_attributed_rows_from_learning_only() -> None:
    baseline, snapshot, macs = incident_devices(5)
    events = [
        make_event("2037-07-14T04:17:02", analyzer.SYSTEM_ACTOR, "INTERNET_DISCONNECTED"),
        make_event("2037-07-14T04:19:08", analyzer.SYSTEM_ACTOR, "INTERNET_CONNECTED"),
        *[make_event("2037-07-14T04:18:12", mac, "WLAN_ACCESS_ALLOWED") for mac in macs],
        make_event("2037-07-14T12:00:00", macs[0], "ADMIN_LOGIN"),
    ]
    incidents = analyzer.detect_network_incidents(
        events, baseline, snapshot, copy.deepcopy(analyzer.DEFAULT_POLICY)
    )
    aggregate = analyzer.aggregate_events(events, baseline, snapshot)
    subject_stats, subjects = analyzer.build_subject_behavior_day_stats(
        aggregate, copy.deepcopy(analyzer.DEFAULT_POLICY)
    )
    aggregate["subject_behavior_day_stats"] = subject_stats
    aggregate["behavior_subjects"] = subjects
    incident_findings = analyzer.network_incident_findings(
        incidents, copy.deepcopy(analyzer.DEFAULT_POLICY)
    )
    findings = {
        "critical": [],
        "anomalies": [],
        "observations": incident_findings,
        "all": incident_findings,
    }

    exclusions = analyzer.build_exclusion_maps(aggregate, findings, snapshot, False)
    device_exclusions, _, event_exclusions, _, subject_exclusions, _ = exclusions

    assert ("2037-07-14", macs[0]) in device_exclusions
    assert ("2037-07-14", macs[0], "WLAN_ACCESS_ALLOWED") in event_exclusions
    assert ("2037-07-14", macs[0], "ADMIN_LOGIN") not in event_exclusions
    assert ("2037-07-14", macs[0], "WLAN_ACCESS_ALLOWED") in {
        (day, subject, behavior)
        for day, subject, _subject_type, behavior in subject_exclusions
    }


def test_network_incident_persistence_scoring_and_reporting(tmp_path: Path) -> None:
    baseline, snapshot, macs = incident_devices(5)
    events = [
        make_event("2037-07-14T04:17:02", analyzer.SYSTEM_ACTOR, "INTERNET_DISCONNECTED"),
        make_event("2037-07-14T04:19:08", analyzer.SYSTEM_ACTOR, "INTERNET_CONNECTED"),
        *[make_event("2037-07-14T04:18:12", mac, "DHCP_IP") for mac in macs],
    ]
    policy = copy.deepcopy(analyzer.DEFAULT_POLICY)
    incidents = analyzer.detect_network_incidents(events, baseline, snapshot, policy)
    incident_findings = analyzer.network_incident_findings(incidents, policy)
    findings = {
        "critical": [],
        "anomalies": [],
        "observations": incident_findings,
        "all": incident_findings,
    }
    score, status, breakdown = analyzer.compute_risk_score(findings, policy)
    assert (score, status, breakdown) == (2, "Clean", {"network_reset": 2})

    aggregate = analyzer.aggregate_events(events, baseline, snapshot)
    args = analyzer.argparse.Namespace(logfile="router.log", baseline=None, config=None)
    report = analyzer.build_report_data(
        args,
        tmp_path / "network.db",
        analyzer.ParseStats(parsed_events=len(events)),
        aggregate,
        findings,
        score,
        status,
        breakdown,
        False,
        1,
        None,
        incidents,
        0,
    )
    assert report["analysis_adjustments"]["incident_explained_event_count"] == len(events)
    assert "Confirmed internet connection reset" in analyzer.render_text_report(report)
    assert "Incident-Explained Events" in analyzer.render_markdown_report(report)
    assert "Reset-Explained" in analyzer.render_html_report(report)

    store = analyzer.StateStore(tmp_path / "network.db")
    try:
        epoch_id = seed_epoch(store)
        subject_stats, subjects = analyzer.build_subject_behavior_day_stats(aggregate, policy)
        aggregate["subject_behavior_day_stats"] = subject_stats
        aggregate["behavior_subjects"] = subjects
        deduplicated, run_id = analyzer.persist_analysis(
            store=store,
            run_hash="incident-run",
            logfile_path=tmp_path / "router.log",
            parse_stats=analyzer.ParseStats(parsed_events=len(events)),
            aggregate=aggregate,
            findings=findings,
            score=score,
            status=status,
            epoch_id=epoch_id,
            policy_profile_id=None,
            devices_snapshot=snapshot,
            is_partial=False,
            incidents=incidents,
        )
        assert deduplicated is False
        assert run_id is not None
        row = store.conn.execute("SELECT * FROM network_incidents WHERE run_id = ?", (run_id,)).fetchone()
        assert row is not None
        assert row["confidence"] == "confirmed"
        assert json.loads(row["affected_macs_json"]) == sorted(macs)
        learning_row = store.conn.execute(
            """
            SELECT included_in_learning, exclusion_reason
            FROM device_event_daily_stats
            WHERE run_id = ? AND mac = ? AND event_key = 'DHCP_IP'
            """,
            (run_id, macs[0]),
        ).fetchone()
        assert tuple(learning_row) == (0, "network_reset")

        duplicate, duplicate_run_id = analyzer.persist_analysis(
            store=store,
            run_hash="incident-run",
            logfile_path=tmp_path / "router.log",
            parse_stats=analyzer.ParseStats(parsed_events=len(events)),
            aggregate=aggregate,
            findings=findings,
            score=score,
            status=status,
            epoch_id=epoch_id,
            policy_profile_id=None,
            devices_snapshot=snapshot,
            is_partial=False,
            incidents=incidents,
        )
        assert (duplicate, duplicate_run_id) == (True, run_id)
        incident_count = store.conn.execute(
            "SELECT COUNT(*) FROM network_incidents WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        assert incident_count == 1
        assert store.get_metadata("schema_version") == str(analyzer.SCHEMA_VERSION)
    finally:
        store.close()


def test_persist_analysis_does_not_misclassify_invalid_epoch_as_duplicate(
    tmp_path: Path,
) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    aggregate = {
        "observation_range": {"start": None, "end": None},
        "observed_dates": [],
        "device_day_stats": {},
        "event_day_stats": {},
        "mac_to_name": {},
    }
    findings = {"critical": [], "anomalies": [], "observations": [], "all": []}
    try:
        router_id = store.get_or_create_legacy_netgear_router_instance()
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            analyzer.persist_analysis(
                store=store,
                run_hash="synthetic-invalid-epoch-run",
                logfile_path=tmp_path / "synthetic-router.log",
                parse_stats=analyzer.ParseStats(),
                aggregate=aggregate,
                findings=findings,
                score=0,
                status="Clean",
                epoch_id=999_999,
                policy_profile_id=None,
                devices_snapshot={},
                is_partial=False,
                router_instance_id=router_id,
            )
        assert store.get_run_by_hash(router_id, "synthetic-invalid-epoch-run") is None
    finally:
        store.close()


def test_persist_analysis_rolls_back_run_when_required_child_insert_fails(
    tmp_path: Path,
) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    aggregate = {
        "observation_range": {"start": None, "end": None},
        "observed_dates": [],
        "device_day_stats": {},
        "event_day_stats": {},
        "mac_to_name": {},
    }
    findings = {"critical": [], "anomalies": [], "observations": [], "all": []}
    try:
        epoch_id = seed_epoch(store)
        router_id = store.get_or_create_legacy_netgear_router_instance()
        store.conn.execute(
            """
            CREATE TRIGGER synthetic_reject_metadata
            BEFORE INSERT ON router_metadata_observations
            BEGIN
              SELECT RAISE(ABORT, 'synthetic required-child failure');
            END
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="required-child failure"):
            analyzer.persist_analysis(
                store=store,
                run_hash="synthetic-child-failure-run",
                logfile_path=tmp_path / "synthetic-router.log",
                parse_stats=analyzer.ParseStats(),
                aggregate=aggregate,
                findings=findings,
                score=0,
                status="Clean",
                epoch_id=epoch_id,
                policy_profile_id=None,
                devices_snapshot={},
                is_partial=False,
                router_instance_id=router_id,
            )
        assert store.get_run_by_hash(router_id, "synthetic-child-failure-run") is None
    finally:
        store.close()


def test_persist_analysis_releases_savepoint_after_non_integrity_insert_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    aggregate = {
        "observation_range": {"start": None, "end": None},
        "observed_dates": [],
        "device_day_stats": {},
        "event_day_stats": {},
        "mac_to_name": {},
    }
    findings = {"critical": [], "anomalies": [], "observations": [], "all": []}
    try:
        epoch_id = seed_epoch(store)
        router_id = store.get_or_create_legacy_netgear_router_instance()
        store.commit()
        original_insert_run = store.insert_run

        def fail_after_required_child_inserts(**kwargs: object) -> int:
            original_insert_run(**kwargs)
            raise sqlite3.OperationalError("synthetic post-insert failure")

        monkeypatch.setattr(store, "insert_run", fail_after_required_child_inserts)
        with pytest.raises(sqlite3.OperationalError, match="post-insert failure"):
            analyzer.persist_analysis(
                store=store,
                run_hash="synthetic-operational-failure-run",
                logfile_path=tmp_path / "synthetic-router.log",
                parse_stats=analyzer.ParseStats(),
                aggregate=aggregate,
                findings=findings,
                score=0,
                status="Clean",
                epoch_id=epoch_id,
                policy_profile_id=None,
                devices_snapshot={},
                is_partial=False,
                router_instance_id=router_id,
            )
        assert store.get_run_by_hash(router_id, "synthetic-operational-failure-run") is None
        assert store.conn.in_transaction is False
    finally:
        store.close()


@pytest.mark.parametrize(
    "failure_stage",
    ["metadata_snapshot", "daily", "subject", "incident"],
)
def test_persist_analysis_rolls_back_complete_write_set_after_late_child_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    db_path = tmp_path / "network.db"
    store = analyzer.StateStore(db_path)
    mac = "02:00:00:00:00:31"
    snapshot = {
        mac: {
            "name": "SYNTHETIC ATOMIC DEVICE",
            "status": "allowed",
            "connection_type": "wired",
            "source": "synthetic_test",
        }
    }
    event = make_event("2037-08-01T12:00:00", mac, "DHCP_IP")
    aggregate = analyzer.aggregate_events([event], {"devices": {}}, snapshot)
    subject_stats, subjects = analyzer.build_subject_behavior_day_stats(
        aggregate,
        copy.deepcopy(analyzer.DEFAULT_POLICY),
    )
    aggregate["subject_behavior_day_stats"] = subject_stats
    aggregate["behavior_subjects"] = subjects
    findings = {"critical": [], "anomalies": [], "observations": [], "all": []}
    incident = analyzer.NetworkIncident(
        incident_id="synthetic-atomic-incident",
        incident_type="internet_connection_reset",
        confidence="confirmed",
        start="2037-08-01T12:00:00",
        restored_at="2037-08-01T12:00:01",
        recovery_end="2037-08-01T12:00:02",
        disconnect_count=1,
        connect_count=1,
        affected_macs=[mac],
        event_counts={"DHCP_IP": 1},
        explained_event_count=1,
        active_known_devices=1,
        affected_device_fraction=1.0,
    )
    run_hash = f"synthetic-{failure_stage}-atomic-run"
    try:
        epoch_id = seed_epoch(store)
        router_id = store.get_or_create_legacy_netgear_router_instance()
        store.commit()
        method_name = {
            "metadata_snapshot": "insert_run",
            "daily": "insert_device_daily_stat",
            "subject": "insert_subject_behavior_daily_stat",
            "incident": "insert_network_incident",
        }[failure_stage]
        original_method = getattr(store, method_name)

        def fail_after_child_write(*args: object, **kwargs: object) -> None:
            original_method(*args, **kwargs)
            raise sqlite3.OperationalError(f"synthetic {failure_stage} child failure")

        monkeypatch.setattr(store, method_name, fail_after_child_write)
        with pytest.raises(sqlite3.OperationalError, match=f"{failure_stage} child failure"):
            analyzer.persist_analysis(
                store=store,
                run_hash=run_hash,
                logfile_path=tmp_path / "synthetic-router.log",
                parse_stats=analyzer.ParseStats(parsed_events=1),
                aggregate=aggregate,
                findings=findings,
                score=0,
                status="Clean",
                epoch_id=epoch_id,
                policy_profile_id=None,
                devices_snapshot=snapshot,
                is_partial=False,
                incidents=[incident],
                router_instance_id=router_id,
            )
        assert store.conn.in_transaction is False
        assert store.get_run_by_hash(router_id, run_hash) is None
        for table in (
            "runs",
            "router_metadata_observations",
            "router_snapshot_metrics",
            "device_daily_stats",
            "device_event_daily_stats",
            "subject_behavior_daily_stats",
            "network_incidents",
        ):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM devices WHERE mac = ?", (mac,)
        ).fetchone()[0] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM behavior_subjects WHERE subject_key = ?", (mac,)
        ).fetchone()[0] == 0
    finally:
        store.close()

    retry_store = analyzer.StateStore(db_path)
    try:
        deduplicated, retry_run_id = analyzer.persist_analysis(
            store=retry_store,
            run_hash=run_hash,
            logfile_path=tmp_path / "synthetic-router.log",
            parse_stats=analyzer.ParseStats(parsed_events=1),
            aggregate=aggregate,
            findings=findings,
            score=0,
            status="Clean",
            epoch_id=epoch_id,
            policy_profile_id=None,
            devices_snapshot=snapshot,
            is_partial=False,
            incidents=[incident],
            router_instance_id=router_id,
        )
        assert deduplicated is False
        assert retry_run_id is not None
    finally:
        retry_store.close()

    verification_store = analyzer.StateStore(db_path)
    try:
        persisted_run = verification_store.get_run_by_hash(router_id, run_hash)
        assert persisted_run is not None
        persisted_run_id = int(persisted_run["id"])
        assert verification_store.conn.execute(
            "SELECT COUNT(*) FROM router_metadata_observations WHERE run_id = ?",
            (persisted_run_id,),
        ).fetchone()[0] == 1
        assert verification_store.conn.execute(
            "SELECT COUNT(*) FROM router_snapshot_metrics WHERE run_id = ?",
            (persisted_run_id,),
        ).fetchone()[0] == 1
        assert verification_store.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        verification_store.close()


def test_persist_analysis_uses_complete_savepoint_inside_caller_transaction(
    tmp_path: Path,
) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    aggregate = {
        "observation_range": {"start": None, "end": None},
        "observed_dates": [],
        "device_day_stats": {},
        "event_day_stats": {},
        "mac_to_name": {},
    }
    findings = {"critical": [], "anomalies": [], "observations": [], "all": []}
    try:
        epoch_id = seed_epoch(store)
        router_id = store.get_or_create_legacy_netgear_router_instance()
        store.commit()
        store.conn.execute("BEGIN IMMEDIATE")
        store.set_metadata("synthetic_caller_transaction", "pending")
        deduplicated, run_id = analyzer.persist_analysis(
            store=store,
            run_hash="synthetic-caller-transaction-run",
            logfile_path=tmp_path / "synthetic-router.log",
            parse_stats=analyzer.ParseStats(),
            aggregate=aggregate,
            findings=findings,
            score=0,
            status="Clean",
            epoch_id=epoch_id,
            policy_profile_id=None,
            devices_snapshot={},
            is_partial=False,
            router_instance_id=router_id,
        )
        assert deduplicated is False
        assert run_id is not None
        assert store.conn.in_transaction is True
        store.conn.rollback()
        assert store.get_run_by_hash(router_id, "synthetic-caller-transaction-run") is None
        assert store.get_metadata("synthetic_caller_transaction") is None
    finally:
        store.close()


def test_persist_analysis_scoped_unique_race_remains_a_duplicate_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = analyzer.StateStore(tmp_path / "network.db")
    aggregate = {
        "observation_range": {"start": None, "end": None},
        "observed_dates": [],
        "device_day_stats": {},
        "event_day_stats": {},
        "mac_to_name": {},
    }
    findings = {"critical": [], "anomalies": [], "observations": [], "all": []}
    run_hash = "synthetic-scoped-unique-race"
    try:
        epoch_id = seed_epoch(store)
        router_id = store.get_or_create_legacy_netgear_router_instance()
        store.commit()
        deduplicated, original_run_id = analyzer.persist_analysis(
            store=store,
            run_hash=run_hash,
            logfile_path=tmp_path / "synthetic-router.log",
            parse_stats=analyzer.ParseStats(),
            aggregate=aggregate,
            findings=findings,
            score=0,
            status="Clean",
            epoch_id=epoch_id,
            policy_profile_id=None,
            devices_snapshot={},
            is_partial=False,
            router_instance_id=router_id,
        )
        assert deduplicated is False
        original_lookup = store.get_run_by_hash
        lookup_count = 0

        def miss_only_preinsert_lookup(
            scoped_router_id: int,
            scoped_run_hash: str,
        ) -> sqlite3.Row | None:
            nonlocal lookup_count
            lookup_count += 1
            if lookup_count == 1:
                return None
            return original_lookup(scoped_router_id, scoped_run_hash)

        monkeypatch.setattr(store, "get_run_by_hash", miss_only_preinsert_lookup)
        duplicate, duplicate_run_id = analyzer.persist_analysis(
            store=store,
            run_hash=run_hash,
            logfile_path=tmp_path / "synthetic-router.log",
            parse_stats=analyzer.ParseStats(),
            aggregate=aggregate,
            findings=findings,
            score=0,
            status="Clean",
            epoch_id=epoch_id,
            policy_profile_id=None,
            devices_snapshot={},
            is_partial=False,
            router_instance_id=router_id,
        )
        assert (duplicate, duplicate_run_id) == (True, original_run_id)
        assert lookup_count == 2
        assert store.conn.execute(
            "SELECT COUNT(*) FROM runs WHERE router_instance_id = ? AND file_hash = ?",
            (router_id, run_hash),
        ).fetchone()[0] == 1
    finally:
        store.close()


def synthetic_netgear_regression_log() -> str:
    """Multi-day, documentation-only NETGEAR sample for v3 compatibility tests."""
    known = "02:00:00:00:10:01"
    recovery_macs = [f"02:00:00:00:10:{suffix:02X}" for suffix in range(1, 6)]
    return "\n".join(
        [
            "Subject: SYNTHETIC NETGEAR EXPORT — NO REAL NETWORK DATA",
            "unstructured synthetic footer text",
            "[synthetic malformed event without a timestamp]",
            f"[DHCP IP: (192.0.2.101)] to MAC address {known}, Monday, July 13, 2037 08:00:00",
            "[email sent to synthetic-alerts@example.invalid], Monday, July 13, 2037 08:01:00",
            f"[DHCP IP: (192.0.2.101)] to MAC address {known}, Tuesday, July 14, 2037 04:18:30",
            "[internet disconnected], Tuesday, July 14, 2037 04:17:02",
            *[
                f"[WLAN access allowed] from MAC address {mac}, Tuesday, July 14, 2037 04:18:{12 + index:02d}"
                for index, mac in enumerate(recovery_macs)
            ],
            "[internet connected], Tuesday, July 14, 2037 04:19:08",
            "[log cleared], Tuesday, July 14, 2037 08:00:00",
            f"[WLAN access rejected] from MAC address 02:00:00:00:10:31, Wednesday, July 15, 2037 09:00:00",
            f"[admin login] from MAC address 02:00:00:00:10:30, Wednesday, July 15, 2037 09:01:00",
            "[log cleared], Wednesday, July 15, 2037 18:00:00",
            "[admin login], Wednesday, July 15, 2037 18:01:00",
            f"[DHCP IP: (192.0.2.101)] to MAC address {known}, Wednesday, July 15, 2037 18:02:00",
            f"[DHCP IP: (192.0.2.101)] to MAC address {known}, Wednesday, July 15, 2037 18:02:00",
            f"[DHCP IP: (192.0.2.101)] to MAC address {known}, Wednesday, July 15, 2037 18:02:01",
        ]
    )


def seed_synthetic_netgear_regression_history(store: analyzer.StateStore, tmp_path: Path) -> int:
    known = "02:00:00:00:10:01"
    recovery_macs = [f"02:00:00:00:10:{suffix:02X}" for suffix in range(1, 6)]
    baseline = {
        "devices": {
            mac: {"name": f"SYNTHETIC RECOVERY DEVICE {index}"}
            for index, mac in enumerate(recovery_macs, 1)
        }
    }
    baseline["devices"][known] = {"name": "SYNTHETIC KNOWN DEVICE"}
    epoch_id = store.import_baseline(
        tmp_path / "synthetic-baseline.json",
        baseline,
        float(analyzer.DEFAULT_POLICY["learning"]["seed_weight_frequent"]),
    )
    store.upsert_device(
        mac="02:00:00:00:10:31",
        name="SYNTHETIC BLOCKED DEVICE",
        status="blocked",
        connection_type="wireless",
        source="synthetic_test",
    )
    store.commit()
    for index, history_date in enumerate(["2037-06-15", "2037-06-22", "2037-06-29", "2037-07-06"], 1):
        insert_history_day(
            store, epoch_id, f"synthetic-known-{index}", history_date, known,
            "WLAN_ACCESS_ALLOWED", "WLAN_ALLOWED", [f"{history_date}T08:00:00"],
        )
        insert_history_day(
            store, epoch_id, f"synthetic-system-log-{index}", history_date,
            analyzer.SYSTEM_ACTOR, "LOG_CLEARED", "OTHER", [f"{history_date}T08:00:00"],
        )
        insert_history_day(
            store, epoch_id, f"synthetic-system-dhcp-{index}", history_date,
            analyzer.SYSTEM_ACTOR, "DHCP_IP", "DHCP", [f"{history_date}T08:02:00"],
        )
    insert_history_day(
        store, epoch_id, "synthetic-system-email", "2037-07-06", analyzer.SYSTEM_ACTOR,
        "EMAIL_SENT", "OTHER", ["2037-07-06T08:03:00"],
    )
    return epoch_id


def legacy_netgear_report_projection(report: dict[str, object]) -> dict[str, object]:
    """Freeze v3 fields while permitting later report schemas to add fields."""
    metadata_keys = {
        "unknown_device": (),
        "blocked_device_activity": (),
        "new_event_type": ("day", "event_key", "event_family", "history_count", "observed_timestamps"),
        "rare_event_activity": (
            "day", "event_key", "event_family", "history_count", "observed_device_days",
            "learned_presence_rate", "observed_timestamps",
        ),
        "event_behavior_anomaly": (
            "day", "event_key", "event_family", "reasons", "history_count", "dominant_weekdays",
            "current_weekday", "learned_presence_rate", "learned_mean", "typical_hour",
            "current_hour", "current_streak", "observed_timestamps",
        ),
        "network_reset": (
            "incident_id", "incident_type", "confidence", "day", "start", "restored_at",
            "recovery_end", "disconnect_count", "connect_count", "affected_macs", "event_counts",
            "explained_event_count", "active_known_devices", "affected_device_fraction",
        ),
    }

    def finding_projection(finding: dict[str, object]) -> dict[str, object]:
        kind = str(finding["kind"])
        metadata = finding["metadata"]
        assert isinstance(metadata, dict)
        return {
            "kind": kind,
            "severity": finding["severity"],
            "message": finding["message"],
            "mac": finding["mac"],
            "event_count": finding["event_count"],
            "metadata": {key: metadata[key] for key in metadata_keys[kind]},
            "device_label": finding["device_label"],
            "rendered_message": finding["rendered_message"],
        }

    inputs = report["inputs"]
    state = report["state"]
    parse_stats = report["parse_stats"]
    adjustments = report["analysis_adjustments"]
    incidents = report["network_incidents"]
    observation_range = report["observation_range"]
    events_per_hour = report["events_per_hour"]
    breakdown = report["risk_breakdown"]
    findings = report["findings"]
    assert all(isinstance(value, dict) for value in (inputs, state, parse_stats, adjustments, observation_range, events_per_hour, breakdown, findings))
    assert isinstance(incidents, list)
    epoch_id = state["epoch_id"]
    assert isinstance(epoch_id, int) and not isinstance(epoch_id, bool) and epoch_id > 0
    return {
        "inputs": {
            "logfile": inputs["logfile"],
            "baseline": inputs["baseline"],
            "config": inputs["config"],
            "db": inputs["db"],
        },
        "state": {
            "epoch_id": "<database-generated-id>",
            "policy_profile_id": (
                "<database-generated-id>"
                if state["policy_profile_id"] is not None
                else None
            ),
            "deduplicated": state["deduplicated"],
            "reprocessed_run_id": state["reprocessed_run_id"],
        },
        "parse_stats": legacy_parse_stats_projection(parse_stats),
        "analysis_adjustments": {
            "raw_event_count": adjustments["raw_event_count"],
            "incident_explained_event_count": adjustments["incident_explained_event_count"],
            "analyzed_event_count": adjustments["analyzed_event_count"],
        },
        "network_incidents": [
            {
                "incident_id": incident["incident_id"],
                "incident_type": incident["incident_type"],
                "confidence": incident["confidence"],
                "start": incident["start"],
                "restored_at": incident["restored_at"],
                "recovery_end": incident["recovery_end"],
                "disconnect_count": incident["disconnect_count"],
                "connect_count": incident["connect_count"],
                "affected_macs": incident["affected_macs"],
                "event_counts": incident["event_counts"],
                "explained_event_count": incident["explained_event_count"],
                "active_known_devices": incident["active_known_devices"],
                "affected_device_fraction": incident["affected_device_fraction"],
            }
            for incident in incidents
        ],
        "observation_range": {
            "start": observation_range["start"],
            "end": observation_range["end"],
        },
        "events_per_hour": {
            hour: events_per_hour[hour]
            for hour in sorted(hour for hour in events_per_hour if hour.isdigit())
        },
        "risk_score": report["risk_score"],
        "status": report["status"],
        "risk_breakdown": {
            kind: breakdown[kind]
            for kind in (
                "unknown_device", "blocked_device_activity", "new_event_type", "rare_event_activity",
                "event_behavior_anomaly", "network_reset",
            )
        },
        "findings": {
            group: [finding_projection(finding) for finding in findings[group]]
            for group in ("critical", "anomalies", "observations", "all")
        },
        "priority_findings": [finding_projection(finding) for finding in report["priority_findings"]],
        "device_summary": [
            {
                "mac": device["mac"],
                "name": device["name"],
                "dhcp_count": device["dhcp_count"],
                "total_events": device["total_events"],
                "incident_explained_events": device["incident_explained_events"],
                "event_types": device["event_types"],
            }
            for device in report["device_summary"]
        ],
    }


def markdown_section(rendered: str, heading: str, next_heading: str | None = None) -> str:
    start = rendered.index(heading)
    end = rendered.index(next_heading, start) if next_heading else len(rendered)
    return rendered[start:end]


def html_section(rendered: str, heading: str) -> str:
    heading_index = rendered.index(f"<h2>{heading}</h2>")
    start = rendered.rfind("<section", 0, heading_index)
    section = rendered[start:rendered.index("</section>", heading_index) + len("</section>")]
    return re.sub(r">\s+<", "><", section)


def quote_sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def application_table_snapshot(store: analyzer.StateStore) -> dict[str, dict[str, object]]:
    """Capture every non-internal application table with stable column and row ordering."""
    table_names = [
        row["name"]
        for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    snapshot = {}
    for table_name in table_names:
        quoted_table = quote_sqlite_identifier(table_name)
        columns = tuple(
            row["name"] for row in store.conn.execute(f"PRAGMA table_info({quoted_table})")
        )
        quoted_columns = ", ".join(quote_sqlite_identifier(column) for column in columns)
        rows = store.conn.execute(
            f"SELECT {quoted_columns} FROM {quoted_table} ORDER BY {quoted_columns}"
        ).fetchall()
        snapshot[table_name] = {
            "columns": columns,
            "rows": [tuple(row) for row in rows],
        }
    return snapshot


def text_renderer_contract(rendered: str, db_path: Path) -> dict[str, object]:
    summary, finding_index = rendered.split(" Finding Index ", 1)
    summary_rows = {}
    for line in summary.splitlines():
        if " : " not in line:
            continue
        label, value = line.split(" : ", 1)
        summary_rows[label.strip()] = value.strip().replace(str(db_path), "<temporary-db>")
    malformed_heading = summary.splitlines().index("Malformed Samples:")
    summary_rows["Malformed Samples"] = tuple(
        line.strip()[2:]
        for line in summary.splitlines()[malformed_heading + 1:]
        if line.strip().startswith("- ")
    )
    index, grouped = finding_index.split(" Findings by Device/Group ", 1)
    index_rows = [
        tuple(re.split(r" {2,}", line.strip()))
        for line in index.splitlines()
        if line.strip() and not line.lstrip().startswith("Sev") and set(line.strip()) != {"-"}
    ]
    grouped = grouped.split(" Risk Breakdown ", 1)[0]
    lines = grouped.splitlines()
    groups = []
    index = 0
    while index < len(lines):
        if not lines[index].strip() or lines[index].startswith(" ") or set(lines[index].strip()) == {"-"}:
            index += 1
            continue
        label = lines[index].strip()
        identifier = lines[index + 1].strip()
        index += 3
        entries = []
        while index < len(lines) and (not lines[index].strip() or lines[index].startswith("  ")):
            if not lines[index].strip():
                index += 1
                continue
            match = re.fullmatch(r"  ([A-Z]+) \| (.+)", lines[index])
            if match is None:
                break
            severity, kind = match.groups()
            index += 1
            details = []
            while index < len(lines) and lines[index].startswith("    "):
                detail = lines[index].strip()
                if ": " in detail:
                    detail_label, detail_value = detail.split(": ", 1)
                    details.append((detail_label.strip(), detail_value))
                index += 1
            entries.append((severity, kind, tuple(details)))
        groups.append((label, identifier, tuple(entries)))
    return {"summary": summary_rows, "finding_index": index_rows, "findings": groups}


def text_device_summary_contract(rendered: str) -> list[tuple[str, int, int, int, tuple[str, ...], str]]:
    section = rendered.split(" Device Summary ", 1)[1]
    lines = section.splitlines()[2:]
    groups = []
    index = 0
    heading_pattern = re.compile(r"(.+?)\s+events\s+(\d+)\s+dhcp\s+(\d+)\s+reset\s+(\d+)$")
    while index < len(lines):
        if not lines[index].strip() or set(lines[index].strip()) == {"-"}:
            index += 1
            continue
        match = heading_pattern.fullmatch(lines[index])
        assert match is not None
        name, events, dhcp, reset = match.groups()
        index += 1
        indented = []
        while index < len(lines) and lines[index].startswith("  "):
            indented.append(lines[index].strip())
            index += 1
        assert indented
        groups.append((name.rstrip(), int(events), int(dhcp), int(reset), tuple(indented[:-1]), indented[-1]))
    return groups


def markdown_renderer_contract(rendered: str, db_path: Path) -> dict[str, object]:
    summary = markdown_section(rendered, "# Network Analysis Report", "## Finding Index")
    summary_rows = {}
    for line in summary.splitlines():
        match = re.fullmatch(r"- (.+): (.+)", line)
        if match:
            label, value = match.groups()
            summary_rows[label] = value.replace(f"`{db_path}`", "<temporary-db>")
    malformed_heading = summary.splitlines().index("### Malformed Samples")
    summary_rows["Malformed Samples"] = tuple(
        line[2:]
        for line in summary.splitlines()[malformed_heading + 1:]
        if line.startswith("- ")
    )
    index = markdown_section(rendered, "## Finding Index", "## Findings by Device/Group")
    index_rows = [
        tuple(cell.strip() for cell in line.strip("|").split("|"))
        for line in index.splitlines()
        if line.startswith("|") and not line.startswith("| ---")
    ][1:]
    grouped = markdown_section(rendered, "## Findings by Device/Group", "## Risk Breakdown")
    lines = grouped.splitlines()[2:]
    groups = []
    index = 0
    while index < len(lines):
        if not lines[index]:
            index += 1
            continue
        assert lines[index].startswith("### ")
        label = lines[index][4:]
        identifier = lines[index + 2].strip("`")
        index += 4
        entries = []
        while index < len(lines) and not lines[index].startswith("### "):
            if not lines[index]:
                index += 1
                continue
            assert lines[index].startswith("#### ")
            severity, kind = lines[index][5:].split(" | `", 1)
            index += 2
            details = []
            while index < len(lines) and lines[index].startswith("- **"):
                label_value = lines[index][4:]
                detail_label, detail_value = label_value.split(":** ", 1)
                details.append((detail_label, detail_value))
                index += 1
            entries.append((severity, kind.rstrip("`"), tuple(details)))
        groups.append((label, identifier, tuple(entries)))
    return {"summary": summary_rows, "finding_index": index_rows, "findings": groups}


def html_renderer_contract(rendered: str, db_path: Path) -> dict[str, object]:
    main_start = rendered.index("<main>")
    header_start = rendered.index("<section>", main_start)
    header_section = rendered[header_start:rendered.index("</section>", header_start) + len("</section>")]
    summary_rows = dict(re.findall(r"<dt>([^<]+)</dt><dd>(.*?)</dd>", header_section))
    summary_rows["Database"] = summary_rows["Database"].replace(
        f"<code>{db_path}</code>", "<temporary-db>"
    )
    input_summary = html_section(rendered, "Input Summary")
    summary_rows.update(dict(re.findall(r"<dt>([^<]+)</dt><dd>(.*?)</dd>", input_summary)))
    index = html_section(rendered, "Finding Index")
    index_rows = [
        tuple(re.findall(r"<td>(.*?)</td>", row))
        for row in re.findall(r"<tr>(.*?)</tr>", index)
    ][1:]
    grouped = html_section(rendered, "Findings by Device/Group")
    groups = []
    subject_pattern = re.compile(
        r'<article class="subject"><h3>(.*?)</h3><p><code>(.*?)</code></p>(.*?)</article>(?=<article class="subject">|</section>)'
    )
    for label, identifier, body in subject_pattern.findall(grouped):
        entries = []
        for severity, kind, detail_html in re.findall(
            r'<article class="finding"><h4>([A-Z]+) \| (.*?)</h4><ul>(.*?)</ul></article>', body
        ):
            details = tuple(
                re.findall(r"<li><strong>(.*?):</strong> (.*?)</li>", detail_html)
            )
            entries.append((severity, kind, details))
        groups.append((label, identifier, tuple(entries)))
    return {"summary": summary_rows, "finding_index": index_rows, "findings": groups}


def test_synthetic_netgear_regression_locks_parser_and_v3_report_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_text = synthetic_netgear_regression_log()
    events, stats = analyzer.parse_log_text(log_text, source="synthetic-netgear.log")
    assert [
        (event.timestamp.isoformat(), event.mac, event.event_key, event.event_family, event.ip)
        for event in events
    ] == [
        ("2037-07-13T08:00:00", "02:00:00:00:10:01", "DHCP_IP", "DHCP", "192.0.2.101"),
        ("2037-07-13T08:01:00", analyzer.SYSTEM_ACTOR, "EMAIL_SENT", "OTHER", None),
        ("2037-07-14T04:17:02", analyzer.SYSTEM_ACTOR, "INTERNET_DISCONNECTED", "OTHER", None),
        ("2037-07-14T04:18:12", "02:00:00:00:10:01", "WLAN_ACCESS_ALLOWED", "WLAN_ALLOWED", None),
        ("2037-07-14T04:18:13", "02:00:00:00:10:02", "WLAN_ACCESS_ALLOWED", "WLAN_ALLOWED", None),
        ("2037-07-14T04:18:14", "02:00:00:00:10:03", "WLAN_ACCESS_ALLOWED", "WLAN_ALLOWED", None),
        ("2037-07-14T04:18:15", "02:00:00:00:10:04", "WLAN_ACCESS_ALLOWED", "WLAN_ALLOWED", None),
        ("2037-07-14T04:18:16", "02:00:00:00:10:05", "WLAN_ACCESS_ALLOWED", "WLAN_ALLOWED", None),
        ("2037-07-14T04:18:30", "02:00:00:00:10:01", "DHCP_IP", "DHCP", "192.0.2.101"),
        ("2037-07-14T04:19:08", analyzer.SYSTEM_ACTOR, "INTERNET_CONNECTED", "OTHER", None),
        ("2037-07-14T08:00:00", analyzer.SYSTEM_ACTOR, "LOG_CLEARED", "OTHER", None),
        ("2037-07-15T09:00:00", "02:00:00:00:10:31", "WLAN_ACCESS_REJECTED", "WLAN_REJECTED", None),
        ("2037-07-15T09:01:00", "02:00:00:00:10:30", "ADMIN_LOGIN", "OTHER", None),
        ("2037-07-15T18:00:00", analyzer.SYSTEM_ACTOR, "LOG_CLEARED", "OTHER", None),
        ("2037-07-15T18:01:00", analyzer.SYSTEM_ACTOR, "ADMIN_LOGIN", "OTHER", None),
        ("2037-07-15T18:02:00", "02:00:00:00:10:01", "DHCP_IP", "DHCP", "192.0.2.101"),
    ]
    assert legacy_parse_stats_projection(analyzer.asdict(stats)) == {
        "total_lines": 21, "parsed_events": 16, "malformed_lines": 1,
        "duplicate_events": 1, "spam_filtered": 1, "ignored_lines": 1,
        "export_noise_lines": 1,
        "malformed_samples": ["[synthetic malformed event without a timestamp]"],
    }
    db_path = tmp_path / "network.db"
    log_path = tmp_path / "synthetic-netgear.log"
    log_path.write_text(log_text, encoding="utf-8")
    store = analyzer.StateStore(db_path)
    try:
        seed_synthetic_netgear_regression_history(store, tmp_path)
    finally:
        store.close()
    assert analyzer.main([str(log_path), "--db", str(db_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {
        "inputs", "state", "parse_stats", "analysis_adjustments", "network_incidents",
        "observation_range", "events_per_hour", "risk_score", "status", "risk_breakdown",
        "findings", "priority_findings", "device_summary",
    } <= set(report)
    assert {"critical", "anomalies", "observations", "all"} <= set(report["findings"])
    expected_legacy_projection = {
        "inputs": {"logfile": str(log_path), "baseline": None, "config": None, "db": str(db_path)},
        "state": {"epoch_id": "<database-generated-id>", "policy_profile_id": None, "deduplicated": False, "reprocessed_run_id": None},
        "parse_stats": legacy_parse_stats_projection(analyzer.asdict(stats)),
        "analysis_adjustments": {"raw_event_count": 16, "incident_explained_event_count": 8, "analyzed_event_count": 8},
        "network_incidents": [{
            "incident_id": "network-reset-20370714T041702-1", "incident_type": "internet_connection_reset",
            "confidence": "confirmed", "start": "2037-07-14T04:17:02", "restored_at": "2037-07-14T04:19:08",
            "recovery_end": "2037-07-14T04:24:08", "disconnect_count": 1, "connect_count": 1,
            "affected_macs": [f"02:00:00:00:10:{suffix:02X}" for suffix in range(1, 6)],
            "event_counts": {"DHCP_IP": 1, "INTERNET_CONNECTED": 1, "INTERNET_DISCONNECTED": 1, "WLAN_ACCESS_ALLOWED": 5},
            "explained_event_count": 8, "active_known_devices": 5, "affected_device_fraction": 1.0,
        }],
        "observation_range": {"start": "2037-07-13T08:00:00", "end": "2037-07-15T18:02:00"},
        "events_per_hour": {"4": 8, "8": 3, "9": 2, "18": 3},
        "risk_score": 100,
        "status": "Suspicious",
        "risk_breakdown": {"unknown_device": 100, "blocked_device_activity": 50, "new_event_type": 10, "rare_event_activity": 10, "event_behavior_anomaly": 20, "network_reset": 2},
        "findings": {
            "critical": [
                {"kind": "unknown_device", "severity": "critical", "message": "Observed unknown device 02:00:00:00:10:30 with 1 event(s).", "mac": "02:00:00:00:10:30", "event_count": 1, "device_label": "02:00:00:00:10:30 (02:00:00:00:10:30)", "metadata": {}, "rendered_message": "Unknown device 02:00:00:00:10:30 (02:00:00:00:10:30) generated 1 event(s)."},
                {"kind": "unknown_device", "severity": "critical", "message": "Observed unknown device 02:00:00:00:10:31 with 1 event(s).", "mac": "02:00:00:00:10:31", "event_count": 1, "device_label": "SYNTHETIC BLOCKED DEVICE (02:00:00:00:10:31)", "metadata": {}, "rendered_message": "Unknown device SYNTHETIC BLOCKED DEVICE (02:00:00:00:10:31) generated 1 event(s)."},
                {"kind": "blocked_device_activity", "severity": "critical", "message": "Blocked device 02:00:00:00:10:31 generated 1 event(s).", "mac": "02:00:00:00:10:31", "event_count": 1, "device_label": "SYNTHETIC BLOCKED DEVICE (02:00:00:00:10:31)", "metadata": {}, "rendered_message": "Blocked device SYNTHETIC BLOCKED DEVICE (02:00:00:00:10:31) generated 1 event(s)."},
            ],
            "anomalies": [
                {"kind": "new_event_type", "severity": "medium", "message": "First observed ADMIN_LOGIN event for __SYSTEM__ on 2037-07-15.", "mac": analyzer.SYSTEM_ACTOR, "event_count": 1, "device_label": "Router/System (__SYSTEM__)", "metadata": {"day": "2037-07-15", "event_key": "ADMIN_LOGIN", "event_family": "OTHER", "history_count": 9, "observed_timestamps": ["2037-07-15T18:01:00"]}, "rendered_message": "Admin Login was first observed for Router/System (__SYSTEM__) on 2037-07-15."},
                {"kind": "rare_event_activity", "severity": "medium", "message": "Rare EMAIL_SENT activity observed for __SYSTEM__ on 2037-07-13.", "mac": analyzer.SYSTEM_ACTOR, "event_count": 1, "device_label": "Router/System (__SYSTEM__)", "metadata": {"day": "2037-07-13", "event_key": "EMAIL_SENT", "event_family": "OTHER", "history_count": 1, "observed_device_days": 9, "learned_presence_rate": 0.11, "observed_timestamps": ["2037-07-13T08:01:00"]}, "rendered_message": "Email Sent remains rare for Router/System (__SYSTEM__) and was observed on 2037-07-13."},
                {"kind": "event_behavior_anomaly", "severity": "medium", "message": "LOG_CLEARED behavior changed for __SYSTEM__ on 2037-07-14.", "mac": analyzer.SYSTEM_ACTOR, "event_count": 1, "device_label": "Router/System (__SYSTEM__)", "metadata": {"day": "2037-07-14", "event_key": "LOG_CLEARED", "event_family": "OTHER", "reasons": ["weekday drift"], "history_count": 4, "dominant_weekdays": [0], "current_weekday": 1, "learned_presence_rate": 0.44, "learned_mean": 1.0, "typical_hour": 8.0, "current_hour": 8.0, "current_streak": 1, "observed_timestamps": ["2037-07-14T08:00:00"]}, "rendered_message": "Log Cleared behavior for Router/System (__SYSTEM__) on 2037-07-14 changed: weekday drift."},
                {"kind": "event_behavior_anomaly", "severity": "medium", "message": "LOG_CLEARED behavior changed for __SYSTEM__ on 2037-07-15.", "mac": analyzer.SYSTEM_ACTOR, "event_count": 1, "device_label": "Router/System (__SYSTEM__)", "metadata": {"day": "2037-07-15", "event_key": "LOG_CLEARED", "event_family": "OTHER", "reasons": ["weekday drift", "time shift 10 hours"], "history_count": 4, "dominant_weekdays": [0], "current_weekday": 2, "learned_presence_rate": 0.44, "learned_mean": 1.0, "typical_hour": 8.0, "current_hour": 18.0, "current_streak": 1, "observed_timestamps": ["2037-07-15T18:00:00"]}, "rendered_message": "Log Cleared behavior for Router/System (__SYSTEM__) on 2037-07-15 changed: weekday drift, time shift 10 hours."},
            ],
            "observations": [
                {"kind": "network_reset", "severity": "low", "message": "Confirmed internet connection reset affected 5 known device(s).", "mac": None, "event_count": 8, "device_label": None, "metadata": {"incident_id": "network-reset-20370714T041702-1", "incident_type": "internet_connection_reset", "confidence": "confirmed", "day": "2037-07-14", "start": "2037-07-14T04:17:02", "restored_at": "2037-07-14T04:19:08", "recovery_end": "2037-07-14T04:24:08", "disconnect_count": 1, "connect_count": 1, "affected_macs": [f"02:00:00:00:10:{suffix:02X}" for suffix in range(1, 6)], "event_counts": {"DHCP_IP": 1, "INTERNET_CONNECTED": 1, "INTERNET_DISCONNECTED": 1, "WLAN_ACCESS_ALLOWED": 5}, "explained_event_count": 8, "active_known_devices": 5, "affected_device_fraction": 1.0}, "rendered_message": "Confirmed internet connection reset from 2037-07-14T04:17:02 through 2037-07-14T04:19:08 affected 5 known device(s) and explained 8 recovery event(s)."},
            ],
            "all": [],
        },
        "priority_findings": [],
        "device_summary": [
            {"mac": "02:00:00:00:10:30", "name": "02:00:00:00:10:30", "dhcp_count": 0, "total_events": 1, "incident_explained_events": 0, "event_types": ["ADMIN_LOGIN"]},
            {"mac": analyzer.SYSTEM_ACTOR, "name": "Router/System", "dhcp_count": 0, "total_events": 6, "incident_explained_events": 2, "event_types": ["ADMIN_LOGIN", "EMAIL_SENT", "INTERNET_CONNECTED", "INTERNET_DISCONNECTED", "LOG_CLEARED"]},
            {"mac": "02:00:00:00:10:31", "name": "SYNTHETIC BLOCKED DEVICE", "dhcp_count": 0, "total_events": 1, "incident_explained_events": 0, "event_types": ["WLAN_ACCESS_REJECTED"]},
            {"mac": "02:00:00:00:10:01", "name": "SYNTHETIC KNOWN DEVICE", "dhcp_count": 3, "total_events": 4, "incident_explained_events": 2, "event_types": ["DHCP_IP", "WLAN_ACCESS_ALLOWED"]},
            *[{"mac": f"02:00:00:00:10:{suffix:02X}", "name": f"SYNTHETIC RECOVERY DEVICE {suffix}", "dhcp_count": 0, "total_events": 1, "incident_explained_events": 1, "event_types": ["WLAN_ACCESS_ALLOWED"]} for suffix in range(2, 6)],
        ],
    }
    expected_findings = expected_legacy_projection["findings"]
    expected_findings["all"] = (
        expected_findings["critical"]
        + expected_findings["anomalies"]
        + expected_findings["observations"]
    )
    expected_legacy_projection["priority_findings"] = (
        expected_findings["critical"] + expected_findings["anomalies"][:2]
    )
    assert legacy_netgear_report_projection(report) == expected_legacy_projection
    report_with_additive_v4_fields = copy.deepcopy(report)
    report_with_additive_v4_fields["format"] = {"id": "netgear"}
    report_with_additive_v4_fields["inputs"]["router_label"] = "SYNTHETIC ROUTER"
    report_with_additive_v4_fields["state"]["router_instance_id"] = "opaque-v4-id"
    report_with_additive_v4_fields["parse_stats"]["adapter_warning_count"] = 0
    report_with_additive_v4_fields["analysis_adjustments"]["eligible_event_count"] = 8
    report_with_additive_v4_fields["network_incidents"][0]["router_instance_id"] = "opaque-v4-id"
    report_with_additive_v4_fields["observation_range"]["clock_trust"] = "trusted"
    report_with_additive_v4_fields["events_per_hour"]["router"] = 1
    report_with_additive_v4_fields["risk_breakdown"]["router_new_event_type"] = 10
    report_with_additive_v4_fields["findings"]["router"] = []
    report_with_additive_v4_fields["findings"]["all"][0]["metadata"]["adapter_context"] = "v4"
    report_with_additive_v4_fields["findings"]["all"][0]["occurrence_id"] = "opaque-v4-id"
    report_with_additive_v4_fields["priority_findings"][0]["metadata"]["adapter_context"] = "v4"
    report_with_additive_v4_fields["device_summary"][0]["router_instance_id"] = "opaque-v4-id"
    assert legacy_netgear_report_projection(report_with_additive_v4_fields) == expected_legacy_projection
    report_with_extra_legacy_hour = copy.deepcopy(report_with_additive_v4_fields)
    report_with_extra_legacy_hour["events_per_hour"]["19"] = 1
    extra_hour_projection = legacy_netgear_report_projection(report_with_extra_legacy_hour)
    assert extra_hour_projection["events_per_hour"] == {
        "4": 8, "8": 3, "9": 2, "18": 3, "19": 1,
    }
    assert extra_hour_projection != expected_legacy_projection
    report_with_invalid_epoch = copy.deepcopy(report_with_additive_v4_fields)
    report_with_invalid_epoch["state"]["epoch_id"] = None
    with pytest.raises(AssertionError):
        legacy_netgear_report_projection(report_with_invalid_epoch)
    report_without_epoch = copy.deepcopy(report_with_additive_v4_fields)
    del report_without_epoch["state"]["epoch_id"]
    with pytest.raises(KeyError):
        legacy_netgear_report_projection(report_without_epoch)

    monkeypatch.setattr(
        analyzer.shutil,
        "get_terminal_size",
        lambda _fallback: os.terminal_size((110, 24)),
    )
    text_report = analyzer.render_text_report(report)
    text_risk_start = text_report.index(" Risk Breakdown ")
    text_risk_end = text_report.index(" Device Summary ", text_risk_start)
    assert [
        line.rstrip()
        for line in text_report[text_risk_start:text_risk_end].splitlines()[2:]
        if line.strip() and set(line.strip()) != {"-"}
    ] == [
        "blocked_device_activity: 50",
        "event_behavior_anomaly: 20",
        "network_reset: 2",
        "new_event_type: 10",
        "rare_event_activity: 10",
        "unknown_device: 100",
    ]

    markdown_report = analyzer.render_markdown_report(report)
    assert markdown_section(markdown_report, "## Risk Breakdown", "## Device Summary") == """## Risk Breakdown

- `blocked_device_activity`: 50
- `event_behavior_anomaly`: 20
- `network_reset`: 2
- `new_event_type`: 10
- `rare_event_activity`: 10
- `unknown_device`: 100

"""
    assert markdown_section(markdown_report, "## Device Summary") == """## Device Summary

| Name | MAC | DHCP | Events | Reset-Explained | Types |
| --- | --- | ---: | ---: | ---: | --- |
| 02:00:00:00:10:30 | `02:00:00:00:10:30` | 0 | 1 | 0 | Admin Login |
| Router/System | `__SYSTEM__` | 0 | 6 | 2 | Admin Login, Email Sent, Internet Connected, Internet Disconnected, Log Cleared |
| SYNTHETIC BLOCKED DEVICE | `02:00:00:00:10:31` | 0 | 1 | 0 | WLAN Access Rejected |
| SYNTHETIC KNOWN DEVICE | `02:00:00:00:10:01` | 3 | 4 | 2 | DHCP IP, WLAN Access Allowed |
| SYNTHETIC RECOVERY DEVICE 2 | `02:00:00:00:10:02` | 0 | 1 | 1 | WLAN Access Allowed |
| SYNTHETIC RECOVERY DEVICE 3 | `02:00:00:00:10:03` | 0 | 1 | 1 | WLAN Access Allowed |
| SYNTHETIC RECOVERY DEVICE 4 | `02:00:00:00:10:04` | 0 | 1 | 1 | WLAN Access Allowed |
| SYNTHETIC RECOVERY DEVICE 5 | `02:00:00:00:10:05` | 0 | 1 | 1 | WLAN Access Allowed |
"""

    html_report = analyzer.render_html_report(report)
    assert html_section(html_report, "Risk Breakdown") == (
        "<section><h2>Risk Breakdown</h2><ul>"
        "<li><code>blocked_device_activity</code>: 50</li>"
        "<li><code>event_behavior_anomaly</code>: 20</li>"
        "<li><code>network_reset</code>: 2</li>"
        "<li><code>new_event_type</code>: 10</li>"
        "<li><code>rare_event_activity</code>: 10</li>"
        "<li><code>unknown_device</code>: 100</li>"
        "</ul></section>"
    )
    assert html_section(html_report, "Device Summary") == (
        "<section><h2>Device Summary</h2><table><thead>"
        "<tr><th>Name</th><th>MAC</th><th>DHCP</th><th>Events</th><th>Reset-Explained</th><th>Types</th></tr>"
        "</thead><tbody>"
        "<tr><td>02:00:00:00:10:30</td><td><code>02:00:00:00:10:30</code></td><td>0</td><td>1</td><td>0</td><td>Admin Login</td></tr>"
        "<tr><td>Router/System</td><td><code>__SYSTEM__</code></td><td>0</td><td>6</td><td>2</td><td>Admin Login, Email Sent, Internet Connected, Internet Disconnected, Log Cleared</td></tr>"
        "<tr><td>SYNTHETIC BLOCKED DEVICE</td><td><code>02:00:00:00:10:31</code></td><td>0</td><td>1</td><td>0</td><td>WLAN Access Rejected</td></tr>"
        "<tr><td>SYNTHETIC KNOWN DEVICE</td><td><code>02:00:00:00:10:01</code></td><td>3</td><td>4</td><td>2</td><td>DHCP IP, WLAN Access Allowed</td></tr>"
        "<tr><td>SYNTHETIC RECOVERY DEVICE 2</td><td><code>02:00:00:00:10:02</code></td><td>0</td><td>1</td><td>1</td><td>WLAN Access Allowed</td></tr>"
        "<tr><td>SYNTHETIC RECOVERY DEVICE 3</td><td><code>02:00:00:00:10:03</code></td><td>0</td><td>1</td><td>1</td><td>WLAN Access Allowed</td></tr>"
        "<tr><td>SYNTHETIC RECOVERY DEVICE 4</td><td><code>02:00:00:00:10:04</code></td><td>0</td><td>1</td><td>1</td><td>WLAN Access Allowed</td></tr>"
        "<tr><td>SYNTHETIC RECOVERY DEVICE 5</td><td><code>02:00:00:00:10:05</code></td><td>0</td><td>1</td><td>1</td><td>WLAN Access Allowed</td></tr>"
        "</tbody></table></section>"
    )

    expected_index = [
        ("CRITICAL", "02:00:00:00:10:30", "Unknown device activity", "n/a"),
        ("CRITICAL", "SYNTHETIC BLOCKED DEVICE", "Unknown device activity", "n/a"),
        ("CRITICAL", "SYNTHETIC BLOCKED DEVICE", "Blocked device activity", "n/a"),
        ("MEDIUM", "Router/System", "First observed Admin Login", "2037-07-15"),
        ("MEDIUM", "Router/System", "Rare Email Sent", "2037-07-13"),
        ("MEDIUM", "Router/System", "Log Cleared behavior changed", "2037-07-14"),
        ("MEDIUM", "Router/System", "Log Cleared behavior changed", "2037-07-15"),
        ("LOW", "Network recovery", "Confirmed internet connection reset", "2037-07-14"),
    ]
    expected_groups = [
        ("02:00:00:00:10:30", "02:00:00:00:10:30", (
            ("CRITICAL", "unknown_device", (("Issue", "Unknown device activity"), ("Events", "1 event(s)"))),
        )),
        ("SYNTHETIC BLOCKED DEVICE", "02:00:00:00:10:31", (
            ("CRITICAL", "unknown_device", (("Issue", "Unknown device activity"), ("Events", "1 event(s)"))),
            ("CRITICAL", "blocked_device_activity", (("Issue", "Blocked device activity"), ("Events", "1 event(s)"))),
        )),
        ("Router/System", analyzer.SYSTEM_ACTOR, (
            ("MEDIUM", "new_event_type", (("Issue", "First observed Admin Login"), ("Date", "2037-07-15"), ("Seen", "6:01:00 PM"), ("Basis", "no prior occurrences in 9 learned day(s)"))),
            ("MEDIUM", "rare_event_activity", (("Issue", "Rare Email Sent"), ("Date", "2037-07-13"), ("Seen", "8:01:00 AM"), ("Basis", "1 prior occurrence day(s) across 9 learned day(s), 11% presence"))),
            ("MEDIUM", "event_behavior_anomaly", (("Issue", "Log Cleared behavior changed"), ("Date", "2037-07-14"), ("Change", "weekday drift"), ("Seen", "8:00:00 AM"), ("Weekday", "Tuesday"), ("Pattern", "Monday from 4 prior day(s)"))),
            ("MEDIUM", "event_behavior_anomaly", (("Issue", "Log Cleared behavior changed"), ("Date", "2037-07-15"), ("Change", "weekday drift, time shift 10 hours"), ("Seen", "6:00:00 PM"), ("Basis", "typical time around 8:00 AM from 4 prior day(s)"), ("Weekday", "Wednesday"), ("Pattern", "Monday from 4 prior day(s)"))),
        )),
        ("Network recovery", "network-reset-20370714T041702-1", (
            ("LOW", "network_reset", (("Issue", "Confirmed internet connection reset"), ("Date", "2037-07-14"), ("Confidence", "Confirmed"), ("Window", "2037-07-14T04:17:02 to 2037-07-14T04:24:08"), ("Affected", "5 known device(s)"), ("Explained", "8 event(s)"), ("Evidence", "DHCP IP 1, Internet Connected 1, Internet Disconnected 1, WLAN Access Allowed 5"))),
        )),
    ]
    text_contract = text_renderer_contract(text_report, db_path)
    markdown_contract = markdown_renderer_contract(markdown_report, db_path)
    html_contract = html_renderer_contract(html_report, db_path)
    assert html_renderer_contract(
        html_report.replace(
            "</main>",
            "<dl><dt>Risk Score</dt><dd>moved-and-duplicated</dd></dl></main>",
        ),
        db_path,
    ) == html_contract
    assert text_contract == {
        "summary": {
            "Risk Score": "100 / 100", "Status": "Suspicious", "Database": "<temporary-db>",
            "Run Persistence": "Stored", "Parsed Events": "16", "Incident-Explained": "8",
            "Events Analyzed": "8", "Malformed Lines": "1", "Duplicate Events": "1",
            "Spam-Filtered DHCP": "1", "Export Noise": "1",
            "Observation Range": "2037-07-13T08:00:00 to 2037-07-15T18:02:00",
            "Malformed Samples": ("[synthetic malformed event without a timestamp]",),
        },
        "finding_index": expected_index,
        "findings": expected_groups,
    }
    assert markdown_contract == {
        "summary": {
            "Risk Score": "**100 / 100**", "Status": "**Suspicious**", "Database": "<temporary-db>",
            "Run Persistence": "Stored", "Parsed Events": "16", "Incident-Explained Events": "8",
            "Events Analyzed": "8", "Malformed Lines": "1", "Duplicate Events Removed": "1",
            "Spam-Filtered DHCP Entries": "1", "Export Noise Lines Ignored": "1",
            "Observation Range": "2037-07-13T08:00:00 to 2037-07-15T18:02:00",
            "Malformed Samples": ("`[synthetic malformed event without a timestamp]`",),
        },
        "finding_index": expected_index,
        "findings": expected_groups,
    }
    assert html_contract == {
        "summary": {
            "Risk Score": "100 / 100", "Status": "Suspicious", "Database": "<temporary-db>",
            "Run Persistence": "Stored", "Observation Range": "2037-07-13T08:00:00 to 2037-07-15T18:02:00",
            "Parsed Events": "16", "Incident-Explained Events": "8", "Events Analyzed": "8",
            "Malformed Lines": "1", "Duplicate Events Removed": "1", "Spam-Filtered DHCP": "1", "Export Noise": "1",
        },
        "finding_index": expected_index,
        "findings": expected_groups,
    }
    assert text_device_summary_contract(text_report) == [
        ("Router/System", 6, 0, 2, (analyzer.SYSTEM_ACTOR,), "Admin Login, Email Sent, Internet Connected, Internet Disconnected, Log Cleared"),
        ("SYNTHETIC KNOWN DEVICE", 4, 3, 2, ("02:00:00:00:10:01",), "DHCP IP, WLAN Access Allowed"),
        ("02:00:00:00:10:30", 1, 0, 0, ("02:00:00:00:10:30",), "Admin Login"),
        ("SYNTHETIC BLOCKED DEVICE", 1, 0, 0, ("02:00:00:00:10:31",), "WLAN Access Rejected"),
        ("SYNTHETIC RECOVERY DEVICE 2", 1, 0, 1, ("02:00:00:00:10:02",), "WLAN Access Allowed"),
        ("SYNTHETIC RECOVERY DEVICE 3", 1, 0, 1, ("02:00:00:00:10:03",), "WLAN Access Allowed"),
        ("SYNTHETIC RECOVERY DEVICE 4", 1, 0, 1, ("02:00:00:00:10:04",), "WLAN Access Allowed"),
        ("SYNTHETIC RECOVERY DEVICE 5", 1, 0, 1, ("02:00:00:00:10:05",), "WLAN Access Allowed"),
    ]


def test_netgear_unknown_and_blocked_defaults_are_critical_before_policy_overrides() -> None:
    unknown_mac = "02:00:00:00:10:30"
    blocked_mac = "02:00:00:00:10:31"
    events_by_mac = {
        mac: [make_event("2037-07-15T09:00:00", mac, "WLAN_ACCESS_REJECTED")]
        for mac in (unknown_mac, blocked_mac)
    }
    aggregate = {"events_by_mac": events_by_mac, "cluster_profiles": {}}
    snapshot = {blocked_mac: {"name": "SYNTHETIC BLOCKED DEVICE", "status": "blocked"}}

    unknown_findings = analyzer.detect_unknown_devices(aggregate, {"devices": {}}, snapshot, analyzer.DEFAULT_POLICY)
    blocked_findings = analyzer.detect_blocked_devices(aggregate, snapshot, analyzer.DEFAULT_POLICY)

    assert [(finding.kind, finding.mac, finding.severity) for finding in unknown_findings] == [
        ("unknown_device", unknown_mac, "critical"),
        ("unknown_device", blocked_mac, "critical"),
    ]
    assert [(finding.kind, finding.mac, finding.severity) for finding in blocked_findings] == [
        ("blocked_device_activity", blocked_mac, "critical"),
    ]


def test_byte_identical_netgear_log_rebuilds_report_without_duplicate_learning_rows(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "network.db"
    log_path = tmp_path / "synthetic-netgear.log"
    log_path.write_text(synthetic_netgear_regression_log(), encoding="utf-8")
    store = analyzer.StateStore(db_path)
    try:
        seed_synthetic_netgear_regression_history(store, tmp_path)
    finally:
        store.close()

    assert analyzer.main([str(log_path), "--db", str(db_path), "--json"]) == 0
    first_report = json.loads(capsys.readouterr().out)
    store = analyzer.StateStore(db_path)
    try:
        epoch = store.get_active_epoch()
        assert epoch is not None
        insert_history_day(
            store,
            int(epoch["id"]),
            "synthetic-current-history",
            "2037-07-12",
            analyzer.SYSTEM_ACTOR,
            "EMAIL_SENT",
            "OTHER",
            ["2037-07-12T08:03:00"],
        )
        policy_id = store.import_policy(
            tmp_path / "synthetic-current-policy.json",
            {
                "schema_version": 1,
                "device_overrides": {
                    "02:00:00:00:10:30": {"finding_overrides": {"unknown_device": {"suppress": True}}},
                    "02:00:00:00:10:31": {"finding_overrides": {"unknown_device": {"suppress": True}}},
                },
            },
        )
        before_snapshot = application_table_snapshot(store)
    finally:
        store.close()

    assert analyzer.main([str(log_path), "--db", str(db_path), "--json"]) == 0
    second_report = json.loads(capsys.readouterr().out)
    assert first_report["state"]["deduplicated"] is False
    assert second_report["state"]["deduplicated"] is True
    assert second_report["state"]["policy_profile_id"] == policy_id
    assert all(finding["kind"] != "unknown_device" for finding in second_report["findings"]["all"])
    assert any(finding["kind"] == "blocked_device_activity" for finding in second_report["findings"]["all"])
    rare_email = next(
        finding
        for finding in second_report["findings"]["all"]
        if finding["kind"] == "rare_event_activity" and finding["metadata"]["event_key"] == "EMAIL_SENT"
    )
    assert rare_email["metadata"] == {
        "day": "2037-07-13",
        "event_key": "EMAIL_SENT",
        "event_family": "OTHER",
        "history_count": 2,
        "observed_device_days": 10,
        "learned_presence_rate": 0.2,
        "observed_timestamps": ["2037-07-13T08:01:00"],
    }
    store = analyzer.StateStore(db_path)
    try:
        after_snapshot = application_table_snapshot(store)
    finally:
        store.close()
    assert after_snapshot == before_snapshot
