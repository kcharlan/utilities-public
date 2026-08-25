#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "PyMuPDF>=1.24,<2",
#     "pypdf>=5,<7",
# ]
# ///
import argparse
import copy
import hashlib
import html
import ipaddress
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import textwrap
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, DefaultDict, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple


DB_FILENAME = "network.db"
SCHEMA_VERSION = 3
FORMAT_NETGEAR = "netgear"
FORMAT_TP_LINK_ARCHER = "tp_link_archer"
CLI_FORMAT_TO_ID = {
    "netgear": FORMAT_NETGEAR,
    "tp-link-archer": FORMAT_TP_LINK_ARCHER,
}
AUTO_FORMAT = "auto"
FORMAT_DETECTION_THRESHOLD = 0.80
FORMAT_AMBIGUITY_MARGIN = 0.15
TIMESTAMP_FORMAT = "%A, %B %d, %Y %H:%M:%S"
SYSTEM_ACTOR = "__SYSTEM__"
SYSTEM_NAME = "Router/System"
MAC_PATTERN = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
TIMESTAMP_PATTERN = re.compile(
    r"(?P<timestamp>"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
    r"[A-Za-z]+ \d{1,2}, \d{4} \d{2}:\d{2}:\d{2}"
    r")"
)
TIMESTAMP_DATE_ONLY_PATTERN = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
    r"[A-Za-z]+ \d{1,2}, \d{4}$"
)
TIME_ONLY_PATTERN = re.compile(r"^\d{2}:\d{2}:\d{2}$")
TIMESTAMP_CONTINUATION_PATTERNS = [
    re.compile(r"^[A-Za-z]+ \d{1,2}, \d{4} \d{2}:\d{2}:\d{2}$"),
    re.compile(r"^\d{1,2}, \d{4} \d{2}:\d{2}:\d{2}$"),
    re.compile(r"^\d{4} \d{2}:\d{2}:\d{2}$"),
]
EXPORT_NOISE_PATTERNS = [
    re.compile(r"^Subject:\s+", re.IGNORECASE),
    re.compile(r"^From:\s+", re.IGNORECASE),
    re.compile(r"^Sent:\s+", re.IGNORECASE),
    re.compile(r"^To:\s+", re.IGNORECASE),
    re.compile(r"^Cc:\s+", re.IGNORECASE),
    re.compile(r"^Bcc:\s+", re.IGNORECASE),
    re.compile(r"^Attachment(?:s)?:\s+", re.IGNORECASE),
    re.compile(r"^Page \d+(?: of \d+)?$", re.IGNORECASE),
]
DEFAULT_POLICY = {
    "schema_version": 1,
    "scoring": {
        "low": 2,
        "medium": 10,
        "high": 25,
        "critical": 50,
    },
    "status_thresholds": {
        "watch": 20,
        "suspicious": 50,
    },
    "learning": {
        "rolling_days_frequent": 7,
        "rolling_days_sparse": 28,
        "seed_weight_frequent": 4.0,
        "stddev_floor": 1.0,
        "min_weekday_history": 4,
    },
    "rare_events": {
        "min_device_history_days": 3,
        "max_presence_rate": 0.2,
        "default_severity": "low",
        "other_family_severity": "medium",
    },
    "timing": {
        "low_shift_hours": 2,
    },
    "noise_suppression": {
        "low_only_cap": 10,
        "correlated_secondary_weight": 0.25,
        "configured_allowed_burst_window_seconds": 300,
    },
    "network_incidents": {
        "enabled": True,
        "disconnect_event_keys": ["INTERNET_DISCONNECTED"],
        "connect_event_keys": ["INTERNET_CONNECTED"],
        "recovery_event_keys": ["DHCP_IP", "WLAN_ACCESS_ALLOWED"],
        "merge_gap_seconds": 300,
        "recovery_lookback_seconds": 300,
        "recovery_window_seconds": 300,
        "minimum_known_devices": 5,
        "minimum_known_device_fraction": 0.25,
        "inferred_window_seconds": 300,
        "inferred_minimum_known_devices": 8,
        "inferred_minimum_known_device_fraction": 0.5,
        "inferred_require_dhcp": True,
        "confirmed_severity": "low",
        "probable_severity": "low",
    },
    "partial_detection": {
        "minimum_full_span_hours": 20,
    },
    "cluster": {
        "partial_visibility_min_fraction": 0.5,
        "partial_visibility_severity": "low",
        "missing_cluster_severity": "medium",
        "abnormal_time_escalation": "high",
        "group_gap_grace_seconds": 60,
        "learned_slot_min_occurrences": 2,
        "learned_time_floor_minutes": 15,
    },
    "event_overrides": {},
    "event_family_overrides": {},
    "finding_overrides": {},
    "device_overrides": {},
    "device_name_overrides": {},
    "cluster_overrides": {},
}
SEVERITY_ORDER = {
    "normal": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
FINDING_KIND_ORDER = {
    "unknown_device": 0,
    "blocked_device_activity": 1,
    "network_reset": 2,
    "new_event_type": 3,
    "rare_event_activity": 4,
    "timing_anomaly": 5,
    "event_behavior_anomaly": 6,
    "dhcp_anomaly": 7,
    "event_volume_anomaly": 8,
    "cluster_anomaly": 9,
}
METRIC_BASELINE_RECOVERY_REASONS = {"dhcp_anomaly", "event_volume_anomaly"}
PRIORITY_FINDING_LIMIT = 5
WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


@dataclass(frozen=True)
class RuntimePaths:
    home: Path
    db: Path


@dataclass
class Event:
    timestamp: datetime
    mac: str
    event_family: str
    event_key: str
    ip: Optional[str]
    raw_label: str
    raw_line: str
    source: str
    incident_id: Optional[str] = None
    incident_role: Optional[str] = None
    actor_scope: Optional[str] = None
    stable_client_identity: Optional[str] = None
    component: Optional[str] = None
    process_id: Optional[str] = None
    syslog_severity: Optional[str] = None
    vendor_event_code: Optional[str] = None
    normalized_message: Optional[str] = None
    structured_evidence: Dict[str, Any] = field(default_factory=dict)
    source_sequence: Optional[int] = None
    raw_timestamp: Optional[str] = None
    clock_trust: Optional[str] = None
    clock_reason: Optional[str] = None
    clock_segment_id: Optional[str] = None
    boot_context_id: Optional[str] = None
    boot_session_id: Optional[str] = None
    occurrence_digest: Optional[str] = None
    trusted_overlap_identity: Optional[str] = None


@dataclass(frozen=True)
class RouterCapabilities:
    stable_client_identity: bool = False
    client_dhcp_equivalence: bool = False
    client_access_decision_equivalence: bool = False
    comparable_device_event_coverage: bool = False
    router_system_events: bool = False
    wan_transitions: bool = False
    snapshot_counts: bool = False
    potentially_trustworthy_router_local_time: bool = False
    supported_event_keys: FrozenSet[str] = field(default_factory=frozenset)
    supported_event_families: FrozenSet[str] = field(default_factory=frozenset)
    coverage_mode: str = "continuous_log"
    snapshot_buffer_semantic_dedup: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "supported_event_keys", frozenset(self.supported_event_keys))
        object.__setattr__(self, "supported_event_families", frozenset(self.supported_event_families))

    def to_json(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["supported_event_keys"] = sorted(self.supported_event_keys)
        payload["supported_event_families"] = sorted(self.supported_event_families)
        return payload


@dataclass(frozen=True)
class RouterIdentityCandidate:
    canonical_vendor: str
    lan_mac: Optional[str] = None
    router_owned_interfaces: FrozenSet[str] = field(default_factory=frozenset)
    warnings: Tuple[str, ...] = ()
    persistence_safe_without_override: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "router_owned_interfaces", frozenset(self.router_owned_interfaces))

    def to_json(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["router_owned_interfaces"] = sorted(self.router_owned_interfaces)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class RouterSnapshotMetrics:
    raw_total_clients: Optional[str] = None
    raw_wifi_clients: Optional[str] = None
    total_clients: Optional[int] = None
    wifi_clients: Optional[int] = None
    derived_wired_clients: Optional[int] = None
    eligible: bool = False
    exclusion_reason: Optional[str] = None


@dataclass(frozen=True)
class ClockSegment:
    segment_id: str
    clock_trust: str
    start_sequence: Optional[int] = None
    end_sequence: Optional[int] = None


@dataclass(frozen=True)
class BootSessionCandidate:
    session_id: str
    start_sequence: Optional[int] = None
    trusted_anchor: Optional[datetime] = None
    trusted_overlap_identities: Tuple[str, ...] = ()
    startup_signature: Optional[str] = None
    warnings: Tuple[str, ...] = ()


@dataclass
class ParsedRouterLog:
    format_id: str
    capabilities: RouterCapabilities
    identity: RouterIdentityCandidate
    events: List[Event]
    parse_stats: "ParseStats"
    model: Optional[str] = None
    hardware: Optional[str] = None
    firmware: Optional[str] = None
    export_timestamp: Optional[datetime] = None
    snapshot_metrics: Optional[RouterSnapshotMetrics] = None
    coverage_stats: Dict[str, Any] = field(default_factory=dict)
    order_stats: Dict[str, Any] = field(default_factory=dict)
    clock_segments: List[ClockSegment] = field(default_factory=list)
    boot_candidates: List[BootSessionCandidate] = field(default_factory=list)
    trusted_overlap_identities: Tuple[str, ...] = ()
    warnings: List[str] = field(default_factory=list)


@dataclass
class RouterConfigDevice:
    name: str
    mac: str
    status: Optional[str] = None
    ip: Optional[str] = None
    connection_type: Optional[str] = None
    section: str = ""


@dataclass
class ParseStats:
    total_lines: int = 0
    parsed_events: int = 0
    malformed_lines: int = 0
    duplicate_events: int = 0
    spam_filtered: int = 0
    ignored_lines: int = 0
    export_noise_lines: int = 0
    malformed_samples: List[str] = field(default_factory=list)


@dataclass
class Finding:
    kind: str
    severity: str
    mac: Optional[str]
    message: str
    event_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NetworkIncident:
    incident_id: str
    incident_type: str
    confidence: str
    start: str
    restored_at: str
    recovery_end: str
    disconnect_count: int
    connect_count: int
    affected_macs: List[str]
    event_counts: Dict[str, int]
    explained_event_count: int
    active_known_devices: int
    affected_device_fraction: float


@dataclass
class DeviceDayAggregate:
    observed_date: str
    mac: str
    dhcp_count: int = 0
    total_events: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    event_families: Counter = field(default_factory=Counter)
    event_keys: Counter = field(default_factory=Counter)
    active_hours: Set[int] = field(default_factory=set)
    events: List[Event] = field(default_factory=list)

    def add_event(self, event: Event) -> None:
        self.total_events += 1
        if event.event_family == "DHCP":
            self.dhcp_count += 1
        self.event_families[event.event_family] += 1
        self.event_keys[event.event_key] += 1
        self.active_hours.add(event.timestamp.hour)
        self.events.append(event)
        if self.first_seen is None or event.timestamp < self.first_seen:
            self.first_seen = event.timestamp
        if self.last_seen is None or event.timestamp > self.last_seen:
            self.last_seen = event.timestamp


@dataclass
class EventDayAggregate:
    observed_date: str
    mac: str
    event_key: str
    event_family: str
    count: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    hour_histogram: Counter = field(default_factory=Counter)
    events: List[Event] = field(default_factory=list)

    def add_event(self, event: Event) -> None:
        self.count += 1
        self.hour_histogram[event.timestamp.hour] += 1
        self.events.append(event)
        if self.first_seen is None or event.timestamp < self.first_seen:
            self.first_seen = event.timestamp
        if self.last_seen is None or event.timestamp > self.last_seen:
            self.last_seen = event.timestamp


@dataclass
class SubjectBehaviorDayAggregate:
    observed_date: str
    subject_key: str
    subject_type: str
    behavior_key: str
    behavior_family: str
    count: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    hour_histogram: Counter = field(default_factory=Counter)
    occurrence_starts: List[str] = field(default_factory=list)
    occurrence_ends: List[str] = field(default_factory=list)
    occurrence_sizes: List[int] = field(default_factory=list)
    contexts: List[Dict[str, Any]] = field(default_factory=list)

    def add_occurrence(
        self,
        start: datetime,
        end: datetime,
        size: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.count += 1
        self.hour_histogram[start.hour] += 1
        self.occurrence_starts.append(start.isoformat())
        self.occurrence_ends.append(end.isoformat())
        self.occurrence_sizes.append(size)
        self.contexts.append(context or {})
        if self.first_seen is None or start < self.first_seen:
            self.first_seen = start
        if self.last_seen is None or end > self.last_seen:
            self.last_seen = end


def build_runtime_paths() -> RuntimePaths:
    override = os.environ.get("ROUTER_LOG_ANALYZER_HOME")
    home = Path(override).expanduser() if override else Path.home() / ".router-log-analyzer"
    return RuntimePaths(
        home=home,
        db=home / DB_FILENAME,
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    prog_name = Path(sys.argv[0]).name or "router_log_analyze.py"
    parser = argparse.ArgumentParser(
        prog=prog_name,
        description="Analyze NETGEAR router logs with persistent SQLite-backed learning.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            f"""\
            Examples:
              {prog_name} router-log.pdf
              {prog_name} router-log.pdf baseline.json
              {prog_name} --import-baseline baseline.json
              {prog_name} --import-config router-security-config.md
              {prog_name} --export-baseline learned-baseline.json
              {prog_name} --import-policy policy.json
            """
        ),
    )
    parser.add_argument("logfile", nargs="?", help="Router log export in PDF or plain-text format.")
    parser.add_argument(
        "baseline",
        nargs="?",
        help="Optional bootstrap baseline JSON. Used automatically if no active baseline epoch exists.",
    )
    parser.add_argument("--config", help="Router access-control markdown export.")
    parser.add_argument("--db", help="Path to the SQLite state database.")
    parser.add_argument(
        "--format",
        choices=[AUTO_FORMAT, *CLI_FORMAT_TO_ID],
        default=AUTO_FORMAT,
        help="Router log format (default: auto).",
    )
    parser.add_argument("--router-label", help="Presentation-only label for the analyzed router.")
    parser.add_argument(
        "--router-instance",
        help="Stable router-instance override; its raw value is never persisted or displayed.",
    )
    parser.add_argument("--json", action="store_true", help="Emit report as JSON.")
    parser.add_argument(
        "--report",
        help="Comma-separated report outputs: text, markdown, html, json.",
    )
    parser.add_argument(
        "--report-dir",
        help="Directory for generated report files when using --report. Defaults to the current working directory.",
    )
    parser.add_argument("--import-baseline", dest="import_baseline", help="Import a baseline JSON and activate a new epoch.")
    parser.add_argument("--export-baseline", dest="export_baseline", help="Export the active learned baseline to JSON.")
    parser.add_argument("--import-config", dest="import_config", help="Import router security config into the database.")
    parser.add_argument("--import-policy", dest="import_policy", help="Import and activate a policy JSON document.")
    parser.add_argument("--export-policy", dest="export_policy", help="Export the active merged policy to JSON.")
    parser.add_argument(
        "--version",
        action="version",
        version="router-log-analyzer 0.4.0",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help=(
            "Replace a previously stored analysis with the same file hash. "
            "The replacement is atomic and is rolled back if analysis fails."
        ),
    )
    return parser.parse_args(argv)


def utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(severity, 0)


def max_severity(*severities: str) -> str:
    candidates = [severity for severity in severities if severity]
    return max(candidates, key=severity_rank) if candidates else "normal"


def min_severity(*severities: str) -> str:
    candidates = [severity for severity in severities if severity]
    return min(candidates, key=severity_rank) if candidates else "normal"


def normalize_mac(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = MAC_PATTERN.search(value)
    return match.group(0).upper() if match else None


def is_real_mac(value: Optional[str]) -> bool:
    return normalize_mac(value) is not None


def is_identity_grade_mac(value: Optional[str]) -> bool:
    """Return whether a syntactically valid MAC is safe as a stable client identity."""
    normalized = normalize_mac(value)
    if normalized is None:
        return False
    octets = bytes.fromhex(normalized.replace(":", ""))
    if octets == b"\x00" * 6 or octets == b"\xff" * 6:
        return False
    return not bool(octets[0] & 1)


def load_json_file(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"JSON file must contain a top-level object: {path}")
    return data


def write_json_file(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_report_formats(raw_value: Optional[str], json_flag: bool) -> List[str]:
    formats: List[str] = []
    if raw_value:
        formats.extend(
            item.strip().lower()
            for item in raw_value.split(",")
            if item.strip()
        )
    if json_flag and "json" not in formats:
        formats.append("json")
    valid = {"text", "markdown", "html", "json"}
    invalid = [item for item in formats if item not in valid]
    if invalid:
        raise SystemExit(f"Unsupported report format(s): {', '.join(sorted(set(invalid)))}")
    if not formats:
        return ["text"]
    deduped: List[str] = []
    for item in formats:
        if item not in deduped:
            deduped.append(item)
    return deduped


def report_extension(report_format: str) -> str:
    return {
        "text": "txt",
        "markdown": "md",
        "html": "html",
        "json": "json",
    }[report_format]


def build_report_paths(
    logfile_path: Path,
    report_formats: Sequence[str],
    report_dir: Optional[Path],
) -> Dict[str, Path]:
    base_dir = report_dir.expanduser().resolve() if report_dir else Path.cwd()
    base_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{logfile_path.stem}.report"
    return {
        report_format: base_dir / f"{base_name}.{report_extension(report_format)}"
        for report_format in report_formats
        if report_format != "text"
    }


def normalize_baseline_document(data: Dict[str, Any]) -> Dict[str, Any]:
    devices = data.get("devices")
    if not isinstance(devices, dict):
        raise SystemExit("Baseline JSON must contain an object at devices")
    normalized_devices: Dict[str, Dict[str, Any]] = {}
    for key, value in devices.items():
        if not isinstance(value, dict):
            continue
        maybe_mac = normalize_mac(key)
        normalized_devices[maybe_mac or key] = value
    normalized = dict(data)
    normalized["devices"] = normalized_devices
    return normalized


def validate_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(policy, dict):
        raise SystemExit("Policy must be a JSON object")
    schema_version = policy.get("schema_version", DEFAULT_POLICY["schema_version"])
    if not isinstance(schema_version, int):
        raise SystemExit("Policy schema_version must be an integer")
    if schema_version != DEFAULT_POLICY["schema_version"]:
        raise SystemExit(
            f"Unsupported policy schema_version {schema_version}; "
            f"expected {DEFAULT_POLICY['schema_version']}"
        )
    return policy


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path.expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode = WAL;

            CREATE TABLE IF NOT EXISTS metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS baseline_epochs (
              id INTEGER PRIMARY KEY,
              created_at TEXT NOT NULL,
              source_path TEXT,
              source_hash TEXT,
              label TEXT,
              is_active INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_baseline_epochs_active
              ON baseline_epochs(is_active);

            CREATE TABLE IF NOT EXISTS baseline_seed_devices (
              id INTEGER PRIMARY KEY,
              epoch_id INTEGER NOT NULL,
              mac TEXT NOT NULL,
              name TEXT,
              dhcp_min REAL,
              dhcp_max REAL,
              dhcp_seed_weight REAL,
              total_events_min REAL,
              total_events_max REAL,
              total_events_seed_weight REAL,
              active_hours_json TEXT,
              expected_windows_json TEXT,
              expected_events_json TEXT,
              pattern TEXT,
              soft_max REAL,
              UNIQUE(epoch_id, mac),
              FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_seed_devices_epoch_mac
              ON baseline_seed_devices(epoch_id, mac);

            CREATE TABLE IF NOT EXISTS baseline_seed_clusters (
              id INTEGER PRIMARY KEY,
              epoch_id INTEGER NOT NULL,
              cluster_name TEXT NOT NULL,
              mac_prefixes_json TEXT,
              cluster_size INTEGER,
              min_cluster_size INTEGER,
              cluster_time_window_seconds INTEGER,
              expected_windows_json TEXT,
              UNIQUE(epoch_id, cluster_name),
              FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
            );

            CREATE TABLE IF NOT EXISTS policy_profiles (
              id INTEGER PRIMARY KEY,
              created_at TEXT NOT NULL,
              name TEXT NOT NULL,
              schema_version INTEGER NOT NULL,
              source_path TEXT,
              source_hash TEXT,
              is_active INTEGER NOT NULL DEFAULT 0,
              policy_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_policy_profiles_active
              ON policy_profiles(is_active);

            CREATE TABLE IF NOT EXISTS runs (
              id INTEGER PRIMARY KEY,
              epoch_id INTEGER NOT NULL,
              policy_profile_id INTEGER,
              file_hash TEXT NOT NULL UNIQUE,
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
            CREATE INDEX IF NOT EXISTS idx_runs_epoch_time
              ON runs(epoch_id, ingested_at);

            CREATE TABLE IF NOT EXISTS network_incidents (
              id INTEGER PRIMARY KEY,
              run_id INTEGER NOT NULL,
              incident_id TEXT NOT NULL,
              incident_type TEXT NOT NULL,
              confidence TEXT NOT NULL,
              start TEXT NOT NULL,
              restored_at TEXT NOT NULL,
              recovery_end TEXT NOT NULL,
              disconnect_count INTEGER NOT NULL DEFAULT 0,
              connect_count INTEGER NOT NULL DEFAULT 0,
              affected_macs_json TEXT NOT NULL,
              event_counts_json TEXT NOT NULL,
              explained_event_count INTEGER NOT NULL DEFAULT 0,
              active_known_devices INTEGER NOT NULL DEFAULT 0,
              affected_device_fraction REAL NOT NULL DEFAULT 0,
              UNIQUE(run_id, incident_id),
              FOREIGN KEY(run_id) REFERENCES runs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_network_incidents_run
              ON network_incidents(run_id);

            CREATE TABLE IF NOT EXISTS devices (
              mac TEXT PRIMARY KEY,
              name TEXT,
              status TEXT,
              connection_type TEXT,
              source TEXT,
              first_seen TEXT,
              last_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS device_daily_stats (
              id INTEGER PRIMARY KEY,
              run_id INTEGER NOT NULL,
              epoch_id INTEGER NOT NULL,
              observed_date TEXT NOT NULL,
              mac TEXT NOT NULL,
              dhcp_count INTEGER NOT NULL DEFAULT 0,
              total_events INTEGER NOT NULL DEFAULT 0,
              first_seen TEXT,
              last_seen TEXT,
              event_types_json TEXT,
              active_hours_json TEXT,
              included_in_learning INTEGER NOT NULL DEFAULT 1,
              exclusion_reason TEXT,
              UNIQUE(run_id, observed_date, mac),
              FOREIGN KEY(run_id) REFERENCES runs(id),
              FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_device_daily_epoch_mac_date
              ON device_daily_stats(epoch_id, mac, observed_date);

            CREATE TABLE IF NOT EXISTS device_event_daily_stats (
              id INTEGER PRIMARY KEY,
              run_id INTEGER NOT NULL,
              epoch_id INTEGER NOT NULL,
              observed_date TEXT NOT NULL,
              mac TEXT NOT NULL,
              event_key TEXT NOT NULL,
              event_family TEXT NOT NULL,
              count INTEGER NOT NULL DEFAULT 0,
              first_seen TEXT,
              last_seen TEXT,
              hour_histogram_json TEXT,
              included_in_learning INTEGER NOT NULL DEFAULT 1,
              exclusion_reason TEXT,
              UNIQUE(run_id, observed_date, mac, event_key),
              FOREIGN KEY(run_id) REFERENCES runs(id),
              FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_device_event_daily_epoch_mac_key_date
              ON device_event_daily_stats(epoch_id, mac, event_key, observed_date);

            CREATE TABLE IF NOT EXISTS behavior_subjects (
              subject_key TEXT NOT NULL,
              subject_type TEXT NOT NULL,
              display_name TEXT,
              attributes_json TEXT,
              first_seen TEXT,
              last_seen TEXT,
              PRIMARY KEY(subject_key, subject_type)
            );
            CREATE INDEX IF NOT EXISTS idx_behavior_subjects_type_key
              ON behavior_subjects(subject_type, subject_key);

            CREATE TABLE IF NOT EXISTS subject_behavior_daily_stats (
              id INTEGER PRIMARY KEY,
              run_id INTEGER NOT NULL,
              epoch_id INTEGER NOT NULL,
              observed_date TEXT NOT NULL,
              subject_key TEXT NOT NULL,
              subject_type TEXT NOT NULL,
              behavior_key TEXT NOT NULL,
              behavior_family TEXT NOT NULL,
              count INTEGER NOT NULL DEFAULT 0,
              first_seen TEXT,
              last_seen TEXT,
              hour_histogram_json TEXT,
              occurrence_starts_json TEXT,
              occurrence_ends_json TEXT,
              occurrence_sizes_json TEXT,
              context_json TEXT,
              included_in_learning INTEGER NOT NULL DEFAULT 1,
              exclusion_reason TEXT,
              UNIQUE(run_id, observed_date, subject_key, subject_type, behavior_key),
              FOREIGN KEY(run_id) REFERENCES runs(id),
              FOREIGN KEY(epoch_id) REFERENCES baseline_epochs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_subject_behavior_epoch_subject_date
              ON subject_behavior_daily_stats(epoch_id, subject_key, subject_type, behavior_key, observed_date);
            """
        )
        self.set_metadata("schema_version", str(SCHEMA_VERSION))
        self.conn.commit()

    def get_metadata(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO metadata(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def get_active_epoch(self) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM baseline_epochs WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def get_active_policy_row(self) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM policy_profiles WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def load_effective_policy(self) -> Tuple[Dict[str, Any], Optional[sqlite3.Row]]:
        row = self.get_active_policy_row()
        merged = copy.deepcopy(DEFAULT_POLICY)
        if row is not None:
            merged = deep_merge(merged, validate_policy(json.loads(row["policy_json"])))
        return merged, row

    def import_policy(self, source_path: Path, policy: Dict[str, Any]) -> int:
        validated = validate_policy(policy)
        payload = json.dumps(validated, sort_keys=True).encode("utf-8")
        self.conn.execute("UPDATE policy_profiles SET is_active = 0 WHERE is_active = 1")
        cursor = self.conn.execute(
            """
            INSERT INTO policy_profiles(
              created_at, name, schema_version, source_path, source_hash, is_active, policy_json
            )
            VALUES(?, ?, ?, ?, ?, 1, ?)
            """,
            (
                utcnow_iso(),
                source_path.stem,
                validated["schema_version"],
                str(source_path.resolve()),
                sha256_bytes(payload),
                json.dumps(validated, sort_keys=True),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def export_policy_data(self) -> Dict[str, Any]:
        policy, _ = self.load_effective_policy()
        return policy

    def import_baseline(self, source_path: Path, baseline: Dict[str, Any], seed_weight: float) -> int:
        payload = json.dumps(baseline, sort_keys=True).encode("utf-8")
        self.conn.execute("UPDATE baseline_epochs SET is_active = 0 WHERE is_active = 1")
        cursor = self.conn.execute(
            """
            INSERT INTO baseline_epochs(created_at, source_path, source_hash, label, is_active)
            VALUES(?, ?, ?, ?, 1)
            """,
            (utcnow_iso(), str(source_path.resolve()), sha256_bytes(payload), source_path.stem),
        )
        epoch_id = int(cursor.lastrowid)
        for key, config in baseline.get("devices", {}).items():
            if not isinstance(config, dict):
                continue
            if config.get("type") == "cluster":
                self.conn.execute(
                    """
                    INSERT INTO baseline_seed_clusters(
                      epoch_id, cluster_name, mac_prefixes_json, cluster_size, min_cluster_size,
                      cluster_time_window_seconds, expected_windows_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        epoch_id,
                        key,
                        json.dumps(config.get("mac_prefixes") or []),
                        config.get("cluster_size"),
                        config.get("min_cluster_size"),
                        config.get("cluster_time_window_seconds"),
                        json.dumps(config.get("expected_windows") or []),
                    ),
                )
                continue

            mac = normalize_mac(key)
            if not mac:
                continue
            total_events_range = config.get("expected_events_per_day") or config.get("events_per_day")
            self.conn.execute(
                """
                INSERT INTO baseline_seed_devices(
                  epoch_id, mac, name, dhcp_min, dhcp_max, dhcp_seed_weight,
                  total_events_min, total_events_max, total_events_seed_weight,
                  active_hours_json, expected_windows_json, expected_events_json,
                  pattern, soft_max
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    epoch_id,
                    mac,
                    config.get("name"),
                    value_at(config.get("dhcp_per_day_range"), 0),
                    value_at(config.get("dhcp_per_day_range"), 1),
                    seed_weight,
                    value_at(total_events_range, 0),
                    value_at(total_events_range, 1),
                    seed_weight,
                    json.dumps(config.get("active_hours") or []),
                    json.dumps(config.get("expected_windows") or []),
                    json.dumps(config.get("expected_events") or []),
                    config.get("pattern"),
                    config.get("soft_max"),
                ),
            )
            self.upsert_device(
                mac=mac,
                name=config.get("name"),
                status="allowed",
                connection_type=None,
                source="baseline_import",
            )
        self.conn.commit()
        return epoch_id

    def load_seed_baseline(self, epoch_id: int) -> Dict[str, Any]:
        devices: Dict[str, Dict[str, Any]] = {}
        for row in self.conn.execute(
            "SELECT * FROM baseline_seed_devices WHERE epoch_id = ? ORDER BY mac",
            (epoch_id,),
        ):
            config: Dict[str, Any] = {}
            if row["name"]:
                config["name"] = row["name"]
            if row["dhcp_min"] is not None and row["dhcp_max"] is not None:
                config["dhcp_per_day_range"] = [row["dhcp_min"], row["dhcp_max"]]
            if row["total_events_min"] is not None and row["total_events_max"] is not None:
                config["events_per_day"] = [row["total_events_min"], row["total_events_max"]]
            active_hours = json.loads(row["active_hours_json"] or "[]")
            if active_hours:
                config["active_hours"] = active_hours
            expected_windows = json.loads(row["expected_windows_json"] or "[]")
            if expected_windows:
                config["expected_windows"] = expected_windows
            expected_events = json.loads(row["expected_events_json"] or "[]")
            if expected_events:
                config["expected_events"] = expected_events
            if row["pattern"]:
                config["pattern"] = row["pattern"]
            if row["soft_max"] is not None:
                config["soft_max"] = row["soft_max"]
            devices[row["mac"]] = config

        for row in self.conn.execute(
            "SELECT * FROM baseline_seed_clusters WHERE epoch_id = ? ORDER BY cluster_name",
            (epoch_id,),
        ):
            devices[row["cluster_name"]] = {
                "type": "cluster",
                "mac_prefixes": json.loads(row["mac_prefixes_json"] or "[]"),
                "cluster_size": row["cluster_size"],
                "min_cluster_size": row["min_cluster_size"],
                "cluster_time_window_seconds": row["cluster_time_window_seconds"],
                "expected_windows": json.loads(row["expected_windows_json"] or "[]"),
            }
        return {"devices": devices}

    def import_config(self, source_path: Path, router_config: Dict[str, Any]) -> int:
        count = 0
        for device in router_config["devices"].values():
            status = "blocked" if device.mac in router_config["blocked_macs"] else "allowed"
            self.upsert_device(
                mac=device.mac,
                name=device.name,
                status=status,
                connection_type=device.connection_type,
                source="config_import",
            )
            count += 1
        self.conn.commit()
        return count

    def upsert_device(
        self,
        mac: str,
        name: Optional[str],
        status: Optional[str],
        connection_type: Optional[str],
        source: Optional[str],
        seen_at: Optional[str] = None,
    ) -> None:
        seen_at = seen_at or utcnow_iso()
        existing = self.conn.execute("SELECT * FROM devices WHERE mac = ?", (mac,)).fetchone()
        if existing is None:
            self.conn.execute(
                """
                INSERT INTO devices(mac, name, status, connection_type, source, first_seen, last_seen)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (mac, name, status, connection_type, source, seen_at, seen_at),
            )
            return
        self.conn.execute(
            """
            UPDATE devices
            SET
              name = COALESCE(?, name),
              status = COALESCE(?, status),
              connection_type = COALESCE(?, connection_type),
              source = COALESCE(?, source),
              first_seen = COALESCE(first_seen, ?),
              last_seen = ?
            WHERE mac = ?
            """,
            (name, status, connection_type, source, seen_at, seen_at, mac),
        )

    def load_devices_snapshot(self) -> Dict[str, Dict[str, Any]]:
        devices: Dict[str, Dict[str, Any]] = {}
        for row in self.conn.execute("SELECT * FROM devices ORDER BY mac"):
            devices[row["mac"]] = dict(row)
        if SYSTEM_ACTOR not in devices:
            devices[SYSTEM_ACTOR] = {
                "mac": SYSTEM_ACTOR,
                "name": SYSTEM_NAME,
                "status": "allowed",
                "connection_type": None,
                "source": "system",
                "first_seen": None,
                "last_seen": None,
            }
        return devices

    def get_run_by_hash(self, file_hash: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM runs WHERE file_hash = ?", (file_hash,)).fetchone()

    def delete_run(self, run_id: int) -> bool:
        existing = self.conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
        if existing is None:
            return False
        for table in (
            "network_incidents",
            "device_daily_stats",
            "device_event_daily_stats",
            "subject_behavior_daily_stats",
        ):
            self.conn.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
        self.conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        return True

    def insert_run(
        self,
        epoch_id: int,
        policy_profile_id: Optional[int],
        file_hash: str,
        source_path: Path,
        parse_stats: ParseStats,
        observation_start: Optional[str],
        observation_end: Optional[str],
        observed_dates: List[str],
        risk_score: int,
        status: str,
        is_partial: bool,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO runs(
              epoch_id, policy_profile_id, file_hash, source_path, ingested_at,
              observation_start, observation_end, observed_dates_json,
              parsed_event_count, malformed_line_count, export_noise_line_count,
              risk_score, status, is_partial
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                epoch_id,
                policy_profile_id,
                file_hash,
                str(source_path.resolve()),
                utcnow_iso(),
                observation_start,
                observation_end,
                json.dumps(observed_dates),
                parse_stats.parsed_events,
                parse_stats.malformed_lines,
                parse_stats.export_noise_lines,
                risk_score,
                status,
                1 if is_partial else 0,
            ),
        )
        return int(cursor.lastrowid)

    def insert_device_daily_stat(
        self,
        run_id: int,
        epoch_id: int,
        stat: DeviceDayAggregate,
        included: bool,
        exclusion_reason: Optional[str],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO device_daily_stats(
              run_id, epoch_id, observed_date, mac, dhcp_count, total_events,
              first_seen, last_seen, event_types_json, active_hours_json,
              included_in_learning, exclusion_reason
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                epoch_id,
                stat.observed_date,
                stat.mac,
                stat.dhcp_count,
                stat.total_events,
                stat.first_seen.isoformat() if stat.first_seen else None,
                stat.last_seen.isoformat() if stat.last_seen else None,
                json.dumps(dict(stat.event_keys)),
                json.dumps(sorted(stat.active_hours)),
                1 if included else 0,
                exclusion_reason,
            ),
        )

    def insert_network_incident(self, run_id: int, incident: NetworkIncident) -> None:
        self.conn.execute(
            """
            INSERT INTO network_incidents(
              run_id, incident_id, incident_type, confidence, start, restored_at,
              recovery_end, disconnect_count, connect_count, affected_macs_json,
              event_counts_json, explained_event_count, active_known_devices,
              affected_device_fraction
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                incident.incident_id,
                incident.incident_type,
                incident.confidence,
                incident.start,
                incident.restored_at,
                incident.recovery_end,
                incident.disconnect_count,
                incident.connect_count,
                json.dumps(incident.affected_macs),
                json.dumps(incident.event_counts, sort_keys=True),
                incident.explained_event_count,
                incident.active_known_devices,
                incident.affected_device_fraction,
            ),
        )

    def insert_device_event_daily_stat(
        self,
        run_id: int,
        epoch_id: int,
        stat: EventDayAggregate,
        included: bool,
        exclusion_reason: Optional[str],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO device_event_daily_stats(
              run_id, epoch_id, observed_date, mac, event_key, event_family,
              count, first_seen, last_seen, hour_histogram_json,
              included_in_learning, exclusion_reason
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                epoch_id,
                stat.observed_date,
                stat.mac,
                stat.event_key,
                stat.event_family,
                stat.count,
                stat.first_seen.isoformat() if stat.first_seen else None,
                stat.last_seen.isoformat() if stat.last_seen else None,
                json.dumps(dict(stat.hour_histogram)),
                1 if included else 0,
                exclusion_reason,
            ),
        )

    def upsert_behavior_subject(
        self,
        subject_key: str,
        subject_type: str,
        display_name: Optional[str],
        attributes: Optional[Dict[str, Any]],
        seen_at: Optional[str] = None,
    ) -> None:
        seen_at = seen_at or utcnow_iso()
        existing = self.conn.execute(
            "SELECT * FROM behavior_subjects WHERE subject_key = ? AND subject_type = ?",
            (subject_key, subject_type),
        ).fetchone()
        attributes_json = json.dumps(attributes or {}, sort_keys=True)
        if existing is None:
            self.conn.execute(
                """
                INSERT INTO behavior_subjects(
                  subject_key, subject_type, display_name, attributes_json, first_seen, last_seen
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (subject_key, subject_type, display_name, attributes_json, seen_at, seen_at),
            )
            return
        self.conn.execute(
            """
            UPDATE behavior_subjects
            SET
              display_name = COALESCE(?, display_name),
              attributes_json = CASE
                WHEN ? IS NOT NULL AND ? != '{}' THEN ?
                ELSE attributes_json
              END,
              first_seen = COALESCE(first_seen, ?),
              last_seen = ?
            WHERE subject_key = ? AND subject_type = ?
            """,
            (
                display_name,
                attributes_json,
                attributes_json,
                attributes_json,
                seen_at,
                seen_at,
                subject_key,
                subject_type,
            ),
        )

    def insert_subject_behavior_daily_stat(
        self,
        run_id: int,
        epoch_id: int,
        stat: SubjectBehaviorDayAggregate,
        included: bool,
        exclusion_reason: Optional[str],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO subject_behavior_daily_stats(
              run_id, epoch_id, observed_date, subject_key, subject_type,
              behavior_key, behavior_family, count, first_seen, last_seen,
              hour_histogram_json, occurrence_starts_json, occurrence_ends_json,
              occurrence_sizes_json, context_json, included_in_learning, exclusion_reason
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                epoch_id,
                stat.observed_date,
                stat.subject_key,
                stat.subject_type,
                stat.behavior_key,
                stat.behavior_family,
                stat.count,
                stat.first_seen.isoformat() if stat.first_seen else None,
                stat.last_seen.isoformat() if stat.last_seen else None,
                json.dumps(dict(stat.hour_histogram), sort_keys=True),
                json.dumps(stat.occurrence_starts),
                json.dumps(stat.occurrence_ends),
                json.dumps(stat.occurrence_sizes),
                json.dumps(stat.contexts, sort_keys=True),
                1 if included else 0,
                exclusion_reason,
            ),
        )

    def fetch_device_history(
        self,
        epoch_id: int,
        mac: str,
        before_date: Optional[str],
        limit: Optional[int],
    ) -> List[sqlite3.Row]:
        query = """
            SELECT *
            FROM device_daily_stats
            WHERE epoch_id = ? AND mac = ? AND included_in_learning = 1
        """
        params: List[Any] = [epoch_id, mac]
        if before_date is not None:
            query += " AND observed_date < ?"
            params.append(before_date)
        query += " ORDER BY observed_date DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return list(self.conn.execute(query, params))

    def fetch_device_metric_history(
        self,
        epoch_id: int,
        mac: str,
        before_date: Optional[str],
        limit: Optional[int],
    ) -> List[sqlite3.Row]:
        recovery_reasons = sorted(METRIC_BASELINE_RECOVERY_REASONS)
        placeholders = ", ".join("?" for _ in recovery_reasons)
        query = f"""
            SELECT *
            FROM device_daily_stats
            WHERE epoch_id = ? AND mac = ?
              AND (
                included_in_learning = 1
                OR exclusion_reason IN ({placeholders})
              )
        """
        params: List[Any] = [epoch_id, mac, *recovery_reasons]
        if before_date is not None:
            query += " AND observed_date < ?"
            params.append(before_date)
        query += " ORDER BY observed_date DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return list(self.conn.execute(query, params))

    def fetch_event_history(
        self,
        epoch_id: int,
        mac: str,
        event_key: str,
        before_date: Optional[str],
        limit: Optional[int],
    ) -> List[sqlite3.Row]:
        query = """
            SELECT *
            FROM device_event_daily_stats
            WHERE epoch_id = ? AND mac = ? AND event_key = ? AND included_in_learning = 1
        """
        params: List[Any] = [epoch_id, mac, event_key]
        if before_date is not None:
            query += " AND observed_date < ?"
            params.append(before_date)
        query += " ORDER BY observed_date DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return list(self.conn.execute(query, params))

    def fetch_subject_behavior_history(
        self,
        epoch_id: int,
        subject_key: str,
        subject_type: str,
        behavior_key: str,
        before_date: Optional[str],
        limit: Optional[int],
    ) -> List[sqlite3.Row]:
        query = """
            SELECT *
            FROM subject_behavior_daily_stats
            WHERE epoch_id = ? AND subject_key = ? AND subject_type = ? AND behavior_key = ?
              AND included_in_learning = 1
        """
        params: List[Any] = [epoch_id, subject_key, subject_type, behavior_key]
        if before_date is not None:
            query += " AND observed_date < ?"
            params.append(before_date)
        query += " ORDER BY observed_date DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return list(self.conn.execute(query, params))

    def fetch_epoch_macs(self, epoch_id: int) -> List[str]:
        macs = {
            row["mac"]
            for row in self.conn.execute(
                "SELECT DISTINCT mac FROM device_daily_stats WHERE epoch_id = ?",
                (epoch_id,),
            )
        }
        macs.update(
            row["mac"]
            for row in self.conn.execute(
                "SELECT mac FROM baseline_seed_devices WHERE epoch_id = ?",
                (epoch_id,),
            )
        )
        return sorted(macs)

    def fetch_epoch_event_keys(self, epoch_id: int, mac: str) -> List[str]:
        return [
            row["event_key"]
            for row in self.conn.execute(
                """
                SELECT DISTINCT event_key
                FROM device_event_daily_stats
                WHERE epoch_id = ? AND mac = ?
                ORDER BY event_key
                """,
                (epoch_id, mac),
            )
        ]

    def commit(self) -> None:
        self.conn.commit()


def value_at(value: Any, index: int) -> Optional[float]:
    if isinstance(value, list) and len(value) > index:
        item = value[index]
        if isinstance(item, (int, float)):
            return float(item)
    return None


def infer_config_path(args: argparse.Namespace) -> Optional[Path]:
    if args.config:
        return Path(args.config).expanduser()
    for candidate_source in (args.baseline, args.logfile):
        if not candidate_source:
            continue
        candidate = Path(candidate_source).expanduser().with_name("router-security-config.md")
        if candidate.exists():
            return candidate
    return None


def parse_markdown_table_row(line: str) -> Optional[List[str]]:
    if not line.strip().startswith("|"):
        return None
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if not cells or all(not cell for cell in cells):
        return None
    if all(set(cell) <= {"-"} for cell in cells if cell):
        return None
    return cells


def load_router_security_config(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {
            "devices": {},
            "allowed_macs": set(),
            "blocked_macs": set(),
        }
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {
            "devices": {},
            "allowed_macs": set(),
            "blocked_macs": set(),
        }

    current_section = "allowed_connected"
    header_map: Dict[str, int] = {}
    devices: Dict[str, RouterConfigDevice] = {}
    allowed_macs: Set[str] = set()
    blocked_macs: Set[str] = set()

    for line in lines:
        if "View list of allowed devices not currently connected" in line:
            current_section = "allowed_not_connected"
            header_map = {}
            continue
        if "View list of blocked devices not currently connected" in line:
            current_section = "blocked_not_connected"
            header_map = {}
            continue
        row = parse_markdown_table_row(line)
        if row is None:
            continue
        row_lower = [cell.lower() for cell in row]
        if "mac address" in row_lower:
            header_map = {cell.lower(): idx for idx, cell in enumerate(row)}
            continue
        if not header_map:
            continue

        def cell(name: str) -> str:
            idx = header_map.get(name)
            if idx is None or idx >= len(row):
                return ""
            return row[idx]

        mac = normalize_mac(cell("mac address"))
        if not mac:
            continue
        device = RouterConfigDevice(
            name=cell("device name") or mac,
            mac=mac,
            status=cell("status") or None,
            ip=cell("ip address") or None,
            connection_type=cell("connection type") or None,
            section=current_section,
        )
        devices[mac] = device
        if current_section == "blocked_not_connected" or (device.status or "").lower() == "blocked":
            blocked_macs.add(mac)
        else:
            allowed_macs.add(mac)

    return {
        "devices": devices,
        "allowed_macs": allowed_macs,
        "blocked_macs": blocked_macs,
    }


def extract_text_from_pdf(path: Path) -> str:
    errors: List[str] = []
    try:
        import fitz  # type: ignore

        with fitz.open(path) as doc:
            pages = [page.get_text("text", sort=True) for page in doc]
        text = "\n".join(pages).strip()
        if text:
            return text
        errors.append("PyMuPDF returned no text")
    except Exception as exc:  # pragma: no cover
        errors.append(f"PyMuPDF failed: {exc}")

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        if text:
            return text
        errors.append("pypdf returned no text")
    except Exception as exc:  # pragma: no cover
        errors.append(f"pypdf failed: {exc}")

    raise SystemExit(f"Unable to extract text from PDF {path}: {'; '.join(errors)}")


def load_log_content(path: Path) -> Tuple[bytes, str]:
    try:
        raw_bytes = path.read_bytes()
    except FileNotFoundError as exc:
        raise SystemExit(f"Log file not found: {path}") from exc
    if path.suffix.lower() == ".pdf":
        return raw_bytes, extract_text_from_pdf(path)
    return raw_bytes, raw_bytes.decode("utf-8", errors="replace")


def _netgear_parse_timestamp_from_line(line: str) -> Optional[datetime]:
    match = TIMESTAMP_PATTERN.search(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("timestamp"), TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _netgear_is_export_noise_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in EXPORT_NOISE_PATTERNS)


def _netgear_normalize_event_key(raw_label: str) -> str:
    label = raw_label.strip()
    lowered = label.lower()
    if lowered.startswith("dhcp ip"):
        return "DHCP_IP"
    if lowered.startswith("wlan access allowed"):
        return "WLAN_ACCESS_ALLOWED"
    if lowered.startswith("wlan access rejected") or lowered.startswith("wlan access denied"):
        return "WLAN_ACCESS_REJECTED"
    if lowered.startswith("email sent to"):
        return "EMAIL_SENT"
    if lowered.startswith("log cleared"):
        return "LOG_CLEARED"
    cleaned = re.sub(r"\([^)]*\)", "", label)
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", cleaned).strip("_").upper()
    return cleaned or "OTHER"


def _netgear_classify_event_family(event_key: str, line: str) -> str:
    if event_key.startswith("DHCP"):
        return "DHCP"
    if event_key == "WLAN_ACCESS_ALLOWED":
        return "WLAN_ALLOWED"
    if event_key == "WLAN_ACCESS_REJECTED":
        return "WLAN_REJECTED"
    if "blocked" in line.lower():
        return "WLAN_REJECTED"
    return "OTHER"


def _netgear_extract_ip(line: str) -> Optional[str]:
    dhcp_match = re.search(r"\[DHCP IP:\s*\(([^)]+)\)\]", line, re.IGNORECASE)
    if dhcp_match:
        return dhcp_match.group(1).strip()
    ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", line)
    return ip_match.group(0) if ip_match else None


def parse_timestamp_from_line(line: str) -> Optional[datetime]:
    """Compatibility wrapper for the legacy NETGEAR timestamp parser."""
    return _netgear_parse_timestamp_from_line(line)


def is_export_noise_line(line: str) -> bool:
    """Compatibility wrapper for the legacy NETGEAR export-noise detector."""
    return _netgear_is_export_noise_line(line)


def normalize_event_key(raw_label: str) -> str:
    """Compatibility wrapper for legacy NETGEAR event-key normalization."""
    return _netgear_normalize_event_key(raw_label)


def classify_event_family(event_key: str, line: str) -> str:
    """Compatibility wrapper for legacy NETGEAR event-family classification."""
    return _netgear_classify_event_family(event_key, line)


def extract_ip(line: str) -> Optional[str]:
    """Compatibility wrapper for the legacy NETGEAR IPv4 extractor."""
    return _netgear_extract_ip(line)


def _reconstruct_netgear_wrapped_log_lines(
    text: str,
    parse_timestamp: Callable[[str], Optional[datetime]] = _netgear_parse_timestamp_from_line,
) -> List[str]:
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    logical_lines: List[str] = []
    index = 0
    while index < len(raw_lines):
        merged = raw_lines[index].strip()
        consumed = 1
        while index + consumed < len(raw_lines):
            continuation = raw_lines[index + consumed].strip()
            if not continuation or parse_timestamp(merged) is not None:
                break
            if not (
                TIME_ONLY_PATTERN.fullmatch(continuation)
                or any(pattern.fullmatch(continuation) for pattern in TIMESTAMP_CONTINUATION_PATTERNS)
            ):
                break
            candidate = f"{merged.rstrip()} {continuation}"
            if parse_timestamp(candidate) is None:
                break
            merged = candidate
            consumed += 1
        logical_lines.append(merged)
        index += consumed
    return logical_lines


def is_access_control_status_line(line: str) -> bool:
    lowered = line.lower()
    return (
        lowered.startswith("[access control]")
        and "with mac address" in lowered
        and (" is allow" in lowered or " is block" in lowered)
    )


def _build_netgear_event_objects(
    adapter: "NetgearLogAdapter", text: str, source: str,
) -> Tuple[List[Event], ParseStats]:
    stats = ParseStats()
    candidates: List[Event] = []
    for source_sequence, raw_line in enumerate(adapter.reconstruct_wrapped_log_lines(text), start=1):
        line = raw_line.strip()
        if not line:
            continue
        stats.total_lines += 1
        if adapter.is_export_noise_line(line):
            stats.export_noise_lines += 1
            continue
        timestamp = adapter.parse_timestamp_from_line(line)
        mac = normalize_mac(line) or SYSTEM_ACTOR
        if timestamp is None:
            if "[" in line or MAC_PATTERN.search(line):
                stats.malformed_lines += 1
                if len(stats.malformed_samples) < 5:
                    stats.malformed_samples.append(line)
            else:
                stats.ignored_lines += 1
            continue
        if is_access_control_status_line(line):
            stats.ignored_lines += 1
            continue
        timestamp_match = TIMESTAMP_PATTERN.search(line)
        label_match = re.search(r"\[([^\]]+)\]", line)
        raw_label = label_match.group(1) if label_match else ""
        event_key = adapter.normalize_event_key(raw_label)
        event_family = adapter.classify_event_family(event_key, line)
        stable_client_identity = mac if is_identity_grade_mac(mac) else None
        candidates.append(
            Event(
                timestamp=timestamp,
                mac=mac,
                event_family=event_family,
                event_key=event_key,
                ip=adapter.extract_ip(line),
                raw_label=raw_label,
                raw_line=line,
                source=source,
                actor_scope="device" if stable_client_identity is not None else "router",
                stable_client_identity=stable_client_identity,
                source_sequence=source_sequence,
                raw_timestamp=timestamp_match.group("timestamp") if timestamp_match else None,
                clock_trust="trusted",
                clock_segment_id="netgear-local-time",
            )
        )

    deduped: List[Event] = []
    seen_exact: Set[Tuple[datetime, str, str, str, Optional[str], str]] = set()
    last_dhcp_seen: Dict[Tuple[str, Optional[str]], datetime] = {}
    for event in sorted(
        candidates,
        key=lambda item: (
            item.timestamp,
            item.mac,
            item.event_family,
            item.event_key,
            item.ip or "",
            item.raw_line,
        ),
    ):
        exact_key = (
            event.timestamp,
            event.mac,
            event.event_family,
            event.event_key,
            event.ip,
            event.raw_line,
        )
        if exact_key in seen_exact:
            stats.duplicate_events += 1
            continue
        seen_exact.add(exact_key)
        if event.event_family == "DHCP":
            burst_key = (event.mac, event.ip)
            prior = last_dhcp_seen.get(burst_key)
            if prior is not None and abs((event.timestamp - prior).total_seconds()) <= 1:
                stats.spam_filtered += 1
                continue
            last_dhcp_seen[burst_key] = event.timestamp
        deduped.append(event)
    stats.parsed_events = len(deduped)
    return deduped, stats


class RouterLogAdapter:
    format_id: str
    cli_format: str

    def detect(self, text: str) -> float:
        raise NotImplementedError

    def parse(self, text: str, source: str) -> ParsedRouterLog:
        raise NotImplementedError


class NetgearLogAdapter(RouterLogAdapter):
    format_id = FORMAT_NETGEAR
    cli_format = "netgear"
    capabilities = RouterCapabilities(
        stable_client_identity=True,
        client_dhcp_equivalence=True,
        client_access_decision_equivalence=True,
        comparable_device_event_coverage=True,
        router_system_events=True,
        wan_transitions=True,
        snapshot_counts=False,
        potentially_trustworthy_router_local_time=True,
        supported_event_keys={
            "DHCP_IP", "WLAN_ACCESS_ALLOWED", "WLAN_ACCESS_REJECTED",
            "INTERNET_DISCONNECTED", "INTERNET_CONNECTED", "EMAIL_SENT", "LOG_CLEARED",
        },
        supported_event_families={"DHCP", "WLAN_ALLOWED", "WLAN_REJECTED", "OTHER"},
        coverage_mode="continuous_log",
        snapshot_buffer_semantic_dedup=False,
    )

    def detect(self, text: str) -> float:
        for line in self.reconstruct_wrapped_log_lines(text):
            if (
                self.is_export_noise_line(line)
                or is_access_control_status_line(line)
                or self.parse_timestamp_from_line(line) is None
            ):
                continue
            if re.search(r"\[[^\]\n]+\]", line) is not None:
                return 0.95
        return 0.0

    def reconstruct_wrapped_log_lines(self, text: str) -> List[str]:
        return _reconstruct_netgear_wrapped_log_lines(text, self.parse_timestamp_from_line)

    def parse_timestamp_from_line(self, line: str) -> Optional[datetime]:
        return _netgear_parse_timestamp_from_line(line)

    def is_export_noise_line(self, line: str) -> bool:
        return _netgear_is_export_noise_line(line)

    def normalize_event_key(self, raw_label: str) -> str:
        return _netgear_normalize_event_key(raw_label)

    def classify_event_family(self, event_key: str, line: str) -> str:
        return _netgear_classify_event_family(event_key, line)

    def extract_ip(self, line: str) -> Optional[str]:
        return _netgear_extract_ip(line)

    def build_event_objects(self, text: str, source: str) -> Tuple[List[Event], ParseStats]:
        return _build_netgear_event_objects(self, text, source)

    def parse(self, text: str, source: str) -> ParsedRouterLog:
        events, parse_stats = self.build_event_objects(text, source)
        if self.detect(text) < FORMAT_DETECTION_THRESHOLD:
            raise SystemExit("The selected NETGEAR format does not contain plausible NETGEAR log structure.")
        return ParsedRouterLog(
            format_id=self.format_id,
            capabilities=self.capabilities,
            identity=RouterIdentityCandidate(
                canonical_vendor=FORMAT_NETGEAR,
                persistence_safe_without_override=True,
            ),
            events=events,
            parse_stats=parse_stats,
            coverage_stats={"continuous_log": True},
            clock_segments=[ClockSegment("netgear-local-time", "trusted")],
        )


class TpLinkArcherAdapter(RouterLogAdapter):
    """Parser for the evidenced TP-Link Archer point-snapshot system log."""

    format_id = FORMAT_TP_LINK_ARCHER
    cli_format = "tp-link-archer"
    capabilities = RouterCapabilities(
        stable_client_identity=False,
        client_dhcp_equivalence=False,
        client_access_decision_equivalence=False,
        comparable_device_event_coverage=False,
        router_system_events=True,
        wan_transitions=True,
        snapshot_counts=True,
        potentially_trustworthy_router_local_time=True,
        supported_event_keys={
            "WAN_DHCP_DISCOVER", "WAN_DHCP_OFFER", "WAN_DHCP_REQUEST", "WAN_DHCP_ACK",
            "WAN_DHCP_RELEASE", "INTERNET_CONNECTED", "INTERNET_DISCONNECTED", "ROUTER_BOOT",
        },
        supported_event_families={"WAN_DHCP", "WAN", "ROUTER_SYSTEM"},
        coverage_mode="point_snapshot",
        snapshot_buffer_semantic_dedup=True,
    )
    _body_pattern = re.compile(
        r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
        r"(?P<component>[A-Za-z][A-Za-z0-9_-]{0,31})"
        r"(?:\[(?P<pid>\d{1,10})\])?:\s+"
        r"<(?P<severity>[0-7])>\s+(?P<code>\d{1,10})"
        r"(?:\s+(?P<message>.*))?$"
    )
    _banner_pattern = re.compile(r"^#\s+(?P<model>[A-Za-z0-9][A-Za-z0-9._ -]{0,95})\s+System Log\s*$")
    _time_pattern = re.compile(r"^#\s+Time\s*=\s*(?P<value>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*$")
    _version_pattern = re.compile(r"^#\s+H-Ver\s*=\s*(?P<hardware>[^;]+?)\s*;\s*S-Ver\s*=\s*(?P<firmware>.+?)\s*$")
    _interface_pattern = re.compile(
        r"^#\s+(?P<kind>LAN|WAN)\s+I\s*=\s*(?P<ip>[^;]+?)\s*;\s*"
        r"M\s*=\s*(?P<mask>[^;]+?)\s*;\s*MAC\s*=\s*(?P<mac>\S+)\s*$"
    )
    _wan_continuation_pattern = re.compile(r"^#\s+G\s*=\s*(?P<gateway>[^;]+?)\s*;\s*DNS\s*=\s*(?P<dns>.+?)\s*$")
    _counts_pattern = re.compile(
        r"^#\s+Clients connected:\s*(?P<total>[^;]*?)\s*;\s*WI-FI\s*:\s*(?P<wifi>.*?)\s*$",
        re.IGNORECASE,
    )
    _approved_actions = (
        "discover", "offer", "request", "ack", "release", "connected", "disconnected",
        "start", "stop", "restart", "initialize", "ready", "timeout", "failure", "success",
    )
    _failure_pattern = re.compile(
        r"\b(?:fail(?:ed|ure|ures|ing)?|not|unable|denied|deny|error|unsuccessful|refused|rejected)\b",
        re.IGNORECASE,
    )
    _dhcp_transition_codes = {
        "1101": "discover",
        "1102": "offer",
        "1103": "request",
        "1104": "ack",
        "1105": "release",
    }
    _dhcp_success_patterns = {
        "1101": (
            re.compile(r"DHCP\s+DISCOVER", re.IGNORECASE),
            re.compile(r"DHCP\s+DISCOVER\s+from\s+(?P<source>\S+)", re.IGNORECASE),
        ),
        "1102": (
            re.compile(r"DHCP\s+OFFER", re.IGNORECASE),
            re.compile(
                r"DHCP\s+OFFER\s+(?P<offered>\S+)\s+from\s+(?P<source>\S+)",
                re.IGNORECASE,
            ),
        ),
        "1103": (
            re.compile(r"DHCP\s+REQUEST", re.IGNORECASE),
            re.compile(r"DHCP\s+REQUEST\s+for\s+(?P<requested>\S+)", re.IGNORECASE),
        ),
        "1104": (
            re.compile(r"DHCP\s+ACK", re.IGNORECASE),
            re.compile(
                r"DHCP\s+ACK\s+from\s+(?P<source>\S+)\s+for\s+(?P<assigned>\S+)"
                r"(?:\s+with\s+MAC\s+(?P<mac>\S+))?",
                re.IGNORECASE,
            ),
            re.compile(r"DHCP\s+ACK\s+for\s+MAC\s+(?P<mac>\S+)", re.IGNORECASE),
        ),
        "1105": (
            re.compile(r"DHCP\s+RELEASE", re.IGNORECASE),
            re.compile(
                r"DHCP\s+RELEASE\s+(?P<released>\S+)\s+from\s+(?P<source>\S+)",
                re.IGNORECASE,
            ),
        ),
    }
    _internet_success_patterns = {
        "3002": re.compile(r"Internet\s+(?:is\s+)?(?:connected|up)", re.IGNORECASE),
        "3001": re.compile(r"Internet\s+(?:is\s+)?(?:disconnected|down)", re.IGNORECASE),
    }
    _router_boot_pattern = re.compile(
        r"(?:system\s+startup|router\s+boot(?:ing)?)",
        re.IGNORECASE,
    )
    _startup_actor_token = (
        r'(?:"[^"\r\n]{1,128}"|\'[^\'\r\n]{1,128}\'|'
        r"[A-Za-z0-9][A-Za-z0-9._%+@-]{0,127})"
    )
    _startup_fragment_patterns = {
        ("service", "2001"): re.compile(
            rf"starting\s+network\s+services(?:\s+for\s+actor\s+{_startup_actor_token})?",
            re.IGNORECASE,
        ),
        ("service", "2003"): re.compile(
            rf"initialize\s+alternate\s+network\s+core(?:\s+for\s+actor\s+{_startup_actor_token})?",
            re.IGNORECASE,
        ),
    }

    def detect(self, text: str) -> float:
        lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines() if line.strip()]
        score = 0.0
        if any(self._banner_pattern.fullmatch(line) for line in lines):
            score += 0.35
        if any(self._time_pattern.fullmatch(line) for line in lines):
            score += 0.20
        if any(self._version_pattern.fullmatch(line) for line in lines):
            score += 0.10
        if any(self._interface_pattern.fullmatch(line) for line in lines):
            score += 0.10
        if any(self._counts_pattern.fullmatch(line) for line in lines):
            score += 0.05
        if any(self._body_pattern.fullmatch(line) for line in lines):
            score += 0.25
        return min(score, 0.99)

    def parse(self, text: str, source: str) -> ParsedRouterLog:
        if self.detect(text) < FORMAT_DETECTION_THRESHOLD:
            raise SystemExit("The selected TP-Link Archer format does not contain plausible supported structure.")

        model: Optional[str] = None
        hardware: Optional[str] = None
        firmware: Optional[str] = None
        export_timestamp: Optional[datetime] = None
        interfaces: Dict[str, Dict[str, Optional[str]]] = {}
        wan_gateway: Optional[str] = None
        wan_dns: List[str] = []
        raw_total: Optional[str] = None
        raw_wifi: Optional[str] = None
        stats = ParseStats()
        events: List[Event] = []
        observed_headers: Dict[str, Any] = {}

        def record_header(header_name: str, value: Any) -> None:
            if header_name in observed_headers and observed_headers[header_name] != value:
                raise SystemExit(
                    f"Conflicting TP-Link {header_name} headers; refusing a mixed router snapshot."
                )
            observed_headers[header_name] = value

        for source_sequence, raw_line in enumerate(
            text.replace("\r\n", "\n").replace("\r", "\n").splitlines(), start=1,
        ):
            line = raw_line.strip()
            if not line:
                continue
            stats.total_lines += 1
            body_match = self._body_pattern.fullmatch(line)
            if body_match is not None:
                try:
                    timestamp = datetime.strptime(body_match.group("timestamp"), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    stats.malformed_lines += 1
                    if len(stats.malformed_samples) < 5:
                        stats.malformed_samples.append(f"line {source_sequence}: malformed TP-Link record")
                    continue
                message = body_match.group("message") or ""
                component = body_match.group("component").lower()
                code = body_match.group("code")
                event_key, event_family, action = self._normalize_event(component, code, message)
                normalized_message, structured_evidence = self._privacy_reduce_message(message)
                structured_evidence["action"] = action
                events.append(Event(
                    timestamp=timestamp,
                    mac=SYSTEM_ACTOR,
                    event_family=event_family,
                    event_key=event_key,
                    ip=None,
                    raw_label=message,
                    raw_line=line,
                    source=source,
                    actor_scope="router",
                    stable_client_identity=None,
                    component=component,
                    process_id=body_match.group("pid"),
                    syslog_severity=body_match.group("severity"),
                    vendor_event_code=code,
                    normalized_message=normalized_message,
                    structured_evidence=structured_evidence,
                    source_sequence=source_sequence,
                    raw_timestamp=body_match.group("timestamp"),
                ))
                continue

            banner_match = self._banner_pattern.fullmatch(line)
            time_match = self._time_pattern.fullmatch(line)
            version_match = self._version_pattern.fullmatch(line)
            interface_match = self._interface_pattern.fullmatch(line)
            continuation_match = self._wan_continuation_pattern.fullmatch(line)
            counts_match = self._counts_pattern.fullmatch(line)
            if banner_match:
                parsed_model = " ".join(banner_match.group("model").split())
                record_header("model", parsed_model)
                model = parsed_model
            elif time_match:
                raw_export_timestamp = time_match.group("value")
                record_header("export-time", raw_export_timestamp)
                try:
                    export_timestamp = datetime.strptime(raw_export_timestamp, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    export_timestamp = None
            elif version_match:
                parsed_hardware = " ".join(version_match.group("hardware").split())
                parsed_firmware = " ".join(version_match.group("firmware").split())
                record_header("version", (parsed_hardware, parsed_firmware))
                hardware = parsed_hardware
                firmware = parsed_firmware
            elif interface_match:
                interface_kind = interface_match.group("kind").lower()
                raw_interface_mac = interface_match.group("mac").strip()
                interface_ip = interface_match.group("ip").strip()
                interface_mask = interface_match.group("mask").strip()
                record_header(
                    f"{interface_kind}-interface",
                    (interface_ip, interface_mask, raw_interface_mac),
                )
                interface_mac = self._normalize_exact_interface_mac(raw_interface_mac)
                interface_fields: Dict[str, Optional[str]] = {
                    "ip": interface_ip,
                    "mask": interface_mask,
                    "mac": interface_mac,
                }
                if interface_mac is None:
                    interface_fields["raw_mac"] = raw_interface_mac
                interfaces[interface_kind] = interface_fields
            elif continuation_match:
                parsed_gateway = continuation_match.group("gateway").strip()
                parsed_dns = continuation_match.group("dns").split()
                record_header("wan-continuation", (parsed_gateway, tuple(parsed_dns)))
                wan_gateway = parsed_gateway
                wan_dns = parsed_dns
            elif counts_match:
                parsed_total = counts_match.group("total").strip()
                parsed_wifi = counts_match.group("wifi").strip()
                record_header("client-counts", (parsed_total, parsed_wifi))
                raw_total = parsed_total
                raw_wifi = parsed_wifi
            elif line.startswith("#"):
                stats.ignored_lines += 1
                continue
            elif re.match(r"^\d{4}-\d{2}-\d{2}", line):
                stats.malformed_lines += 1
                if len(stats.malformed_samples) < 5:
                    stats.malformed_samples.append(f"line {source_sequence}: malformed TP-Link record")
                continue
            else:
                stats.ignored_lines += 1
                continue
            stats.ignored_lines += 1

        events.reverse()
        stats.parsed_events = len(events)
        parsed_lan_mac = interfaces.get("lan", {}).get("mac")
        lan_mac = parsed_lan_mac if is_identity_grade_mac(parsed_lan_mac) else None
        owned_interfaces = frozenset(
            mac for mac in (parsed_lan_mac, interfaces.get("wan", {}).get("mac")) if is_identity_grade_mac(mac)
        )
        identity_warnings: List[str] = []
        if lan_mac is None:
            identity_warnings.append("missing_or_invalid_lan_mac")
        wan_mac = interfaces.get("wan", {}).get("mac")
        if interfaces.get("wan") is not None and not is_identity_grade_mac(wan_mac):
            identity_warnings.append("missing_or_invalid_wan_mac")
        snapshot_metrics = self._parse_snapshot_metrics(raw_total, raw_wifi)
        warnings = self._header_warnings(
            model,
            export_timestamp,
            hardware,
            firmware,
            interfaces,
            wan_gateway,
            wan_dns,
            raw_total,
            raw_wifi,
        )
        events, clock_segments, boot_candidates, clock_warnings = self._classify_clock_and_boot(
            events, export_timestamp, firmware, lan_mac,
        )
        warnings.extend(clock_warnings)
        trusted_records = sum(event.clock_trust == "trusted" for event in events)
        coverage_stats: Dict[str, Any] = {
            "body_records": len(events),
            "trusted_records": trusted_records,
            "untrusted_records": len(events) - trusted_records,
            "timing_eligible_records": trusted_records,
            "run_span_start": min(
                (event.timestamp.isoformat() for event in events if event.clock_trust == "trusted"), default=None,
            ),
            "run_span_end": max(
                (event.timestamp.isoformat() for event in events if event.clock_trust == "trusted"), default=None,
            ),
            "lan": interfaces.get("lan"),
            "wan": {
                **(interfaces.get("wan") or {}),
                "gateway": wan_gateway,
                "dns": wan_dns,
            },
        }
        return ParsedRouterLog(
            format_id=self.format_id,
            capabilities=self.capabilities,
            identity=RouterIdentityCandidate(
                canonical_vendor="tp-link",
                lan_mac=lan_mac,
                router_owned_interfaces=owned_interfaces,
                warnings=tuple(identity_warnings),
                persistence_safe_without_override=is_identity_grade_mac(lan_mac),
            ),
            events=events,
            parse_stats=stats,
            model=model,
            hardware=hardware,
            firmware=firmware,
            export_timestamp=export_timestamp,
            snapshot_metrics=snapshot_metrics,
            coverage_stats=coverage_stats,
            order_stats={"source_order": "newest_first", "emission_order_reconstructed": True},
            clock_segments=clock_segments,
            boot_candidates=boot_candidates,
            trusted_overlap_identities=tuple(
                event.trusted_overlap_identity
                for event in events
                if event.trusted_overlap_identity is not None
            ),
            warnings=warnings,
        )

    def _normalize_event(self, component: str, code: str, message: str) -> Tuple[str, str, str]:
        lowered = message.casefold()
        normalized_component = re.sub(r"[^a-z0-9]+", "_", component).strip("_").upper() or "COMPONENT"
        action = next((candidate for candidate in self._approved_actions if re.search(rf"\b{candidate}\w*\b", lowered)), "other")
        dhcp_action = self._dhcp_transition_codes.get(code) if component == "dhcpc" else None
        if dhcp_action is not None and self._matches_dhcp_success(code, message):
            return f"WAN_DHCP_{dhcp_action.upper()}", "WAN_DHCP", dhcp_action
        outcome = self._without_benign_terminal_punctuation(message)
        internet_pattern = self._internet_success_patterns.get(code) if component == "inet" else None
        if internet_pattern is not None and internet_pattern.fullmatch(outcome) and code == "3002":
            return "INTERNET_CONNECTED", "WAN", "connected"
        if internet_pattern is not None and internet_pattern.fullmatch(outcome) and code == "3001":
            return "INTERNET_DISCONNECTED", "WAN", "disconnected"
        if component == "system" and code == "1000" and self._router_boot_pattern.fullmatch(outcome):
            return "ROUTER_BOOT", "ROUTER_SYSTEM", "start"
        if self._failure_pattern.search(lowered):
            return f"{normalized_component}_{code}_FAILURE", "ROUTER_SYSTEM", "failure"
        return f"{normalized_component}_{code}_{action.upper()}", "ROUTER_SYSTEM", action

    @staticmethod
    def _without_benign_terminal_punctuation(message: str) -> str:
        candidate = message.strip()
        if candidate.endswith((".", "!")):
            candidate = candidate[:-1].rstrip()
        return candidate

    def _matches_dhcp_success(self, code: str, message: str) -> bool:
        candidate = self._without_benign_terminal_punctuation(message)
        for pattern in self._dhcp_success_patterns.get(code, ()):
            match = pattern.fullmatch(candidate)
            if match is None:
                continue
            if all(
                self._is_approved_address_token(value, exact_mac=name == "mac")
                for name, value in match.groupdict().items()
                if value is not None
            ):
                return True
        return False

    def _is_approved_address_token(self, value: str, *, exact_mac: bool) -> bool:
        if self._normalize_exact_interface_mac(value) is not None:
            return True
        if exact_mac:
            return False
        unwrapped = value[1:-1] if value.startswith("[") and value.endswith("]") else value
        if value.startswith("[") != value.endswith("]"):
            return False
        try:
            ipaddress.ip_address(unwrapped)
        except ValueError:
            return False
        return True

    def _is_startup_marker(self, event: Event) -> bool:
        if event.structured_evidence.get("action") == "failure":
            return False
        if event.event_key == "ROUTER_BOOT":
            return True
        pattern = self._startup_fragment_patterns.get((event.component or "", event.vendor_event_code or ""))
        outcome = self._without_benign_terminal_punctuation(event.raw_label)
        return pattern is not None and pattern.fullmatch(outcome) is not None

    @staticmethod
    def _normalize_exact_interface_mac(value: str) -> Optional[str]:
        compact: Optional[str] = None
        if re.fullmatch(
            r"(?:(?:[0-9A-Fa-f]{2}:){5}|(?:[0-9A-Fa-f]{2}-){5})[0-9A-Fa-f]{2}",
            value,
        ):
            compact = value.replace(":", "").replace("-", "")
        elif re.fullmatch(r"[0-9A-Fa-f]{4}(?:\.[0-9A-Fa-f]{4}){2}", value):
            compact = value.replace(".", "")
        if compact is None:
            return None
        return ":".join(compact[index:index + 2] for index in range(0, 12, 2)).upper()

    def _privacy_reduce_message(self, message: str) -> Tuple[str, Dict[str, Any]]:
        evidence: Dict[str, Any] = {}
        message_holder = [message]
        exact_mac_pattern = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")

        def collect(
            pattern: re.Pattern[str],
            key: str,
            placeholder: str,
            normalize: Callable[[str], Optional[str]],
        ) -> None:
            found: List[str] = []

            def replace_match(match: re.Match[str]) -> str:
                normalized = normalize(match.group(0))
                if normalized is None:
                    return match.group(0)
                if normalized not in found:
                    found.append(normalized)
                return placeholder

            message_holder[0] = pattern.sub(replace_match, message_holder[0])
            if found:
                evidence[key] = found

        def is_complete_mac_token(source: str, start: int, end: int, separator: str) -> bool:
            if start > 0 and source[start - 1].isalnum():
                return False
            if start > 0 and source[start - 1] == separator:
                preceding = source[:start - 1]
                label_match = re.search(r"([A-Za-z0-9_-]+)\s*$", preceding)
                if label_match is None or re.fullmatch(r"[0-9A-Fa-f]+", label_match.group(1)):
                    return False
            if end < len(source) and source[end].isalnum():
                return False
            if end < len(source) and source[end] == separator:
                remainder = source[end + 1:]
                if remainder.startswith(separator):
                    return False
                next_segment = re.match(r"[0-9A-Fa-f]+", remainder)
                if next_segment is not None:
                    following_index = next_segment.end()
                    if following_index == len(remainder) or not remainder[following_index].isalnum():
                        return False
            return True

        mac_candidates: List[Tuple[int, int, str]] = []
        for mac_candidate_pattern, separator in (
            (re.compile(r"(?=((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}))"), ":"),
            (re.compile(r"(?=((?:[0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}))"), "-"),
            (re.compile(r"(?=([0-9A-Fa-f]{4}(?:\.[0-9A-Fa-f]{4}){2}))"), "."),
        ):
            for match in mac_candidate_pattern.finditer(message_holder[0]):
                start, end = match.span(1)
                if not is_complete_mac_token(message_holder[0], start, end, separator):
                    continue
                mac = self._normalize_exact_interface_mac(match.group(1))
                if mac is not None:
                    mac_candidates.append((start, end, mac))

        mac_addresses: List[str] = []
        mac_replacements: List[Tuple[int, int, str]] = []
        for start, end, mac in sorted(mac_candidates):
            if mac not in mac_addresses:
                mac_addresses.append(mac)
            mac_replacements.append((start, end, "<mac>"))

        for start, end, placeholder in reversed(mac_replacements):
            message_holder[0] = message_holder[0][:start] + placeholder + message_holder[0][end:]
        if mac_addresses:
            evidence["mac_addresses"] = mac_addresses

        ipv6_like_pattern = re.compile(
            r"(?<![0-9A-Za-z])(?:"
            r"\[(?:[0-9A-Fa-f]{0,4}:){2,7}(?:(?:\d{1,3}\.){3}\d{1,3}|[0-9A-Fa-f]{0,4})\]"
            r"|(?:[0-9A-Fa-f]{0,4}:){2,7}(?:(?:\d{1,3}\.){3}\d{1,3}|[0-9A-Fa-f]{0,4})"
            r")(?![0-9A-Za-z])"
        )

        def normalize_ipv6_like(token: str) -> Optional[str]:
            unwrapped = token[1:-1] if token.startswith("[") and token.endswith("]") else token
            if exact_mac_pattern.fullmatch(unwrapped):
                return None
            if "::" not in unwrapped and unwrapped.count(":") < 6:
                return None
            return unwrapped

        collect(ipv6_like_pattern, "ipv6_addresses", "<ipv6>", normalize_ipv6_like)
        collect(
            re.compile(r"(?<![A-Za-z0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![A-Za-z0-9.])"),
            "ipv4_addresses",
            "<ipv4>",
            lambda token: token,
        )

        actor_names: List[str] = []

        def replace_actor(match: re.Match[str]) -> str:
            name = match.group("name")
            if len(name) >= 2 and name[0] == name[-1] and name[0] in {'"', "'"}:
                name = name[1:-1]
            if name not in actor_names:
                actor_names.append(name)
            return f"{match.group('label')}{match.group('separator')}<actor>"

        message_holder[0] = re.sub(
            r"(?i)\b(?P<label>actor|client|device|host(?:name)?|user)"
            r"(?P<separator>\s*(?:=|:)\s*|\s+)"
            r"(?P<name>"
            r"\"[^\"\r\n]{1,128}\"|'[^'\r\n]{1,128}'|"
            r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}"
            r")(?=$|[\s,;)\]])",
            replace_actor,
            message_holder[0],
        )
        message_holder[0] = re.sub(
            r"(?i)\b(?P<label>actor|client|device|host(?:name)?|user)"
            r"(?P<separator>\s*(?:=|:)\s*|\s+)"
            r"(?P<name>"
            r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\s+[A-Za-z0-9][A-Za-z0-9._-]*){0,7}?"
            r")(?=\s+(?:at|from|via|with|on|using|connected|disconnected|accepted|rejected|ready|started|stopped)\b|[,;]|$)",
            replace_actor,
            message_holder[0],
        )
        if actor_names:
            evidence["actor_names"] = actor_names
        normalized = " ".join(message_holder[0].split())
        return f"normalized-message-v1\0{normalized}", evidence

    def _parse_snapshot_metrics(self, raw_total: Optional[str], raw_wifi: Optional[str]) -> RouterSnapshotMetrics:
        if raw_total is None or raw_wifi is None:
            return RouterSnapshotMetrics(
                raw_total_clients=raw_total,
                raw_wifi_clients=raw_wifi,
                exclusion_reason="missing_snapshot_counts",
            )
        def parse_count(raw_value: str) -> Tuple[Optional[int], str]:
            if re.fullmatch(r"[+-]?\d+", raw_value) is None:
                return None, "invalid"
            digits = raw_value.lstrip("+-")
            if raw_value.startswith("-"):
                if len(digits) > 9:
                    return None, "invalid"
                try:
                    return int(raw_value), "invalid"
                except ValueError:
                    return None, "invalid"
            if len(digits) > 9:
                return None, "out_of_range"
            try:
                return int(raw_value), "valid"
            except ValueError:
                return None, "out_of_range"

        total, total_status = parse_count(raw_total)
        wifi, wifi_status = parse_count(raw_wifi)
        if "invalid" in {total_status, wifi_status}:
            return RouterSnapshotMetrics(
                raw_total_clients=raw_total,
                raw_wifi_clients=raw_wifi,
                total_clients=total,
                wifi_clients=wifi,
                exclusion_reason="invalid_snapshot_counts",
            )
        if "out_of_range" in {total_status, wifi_status}:
            return RouterSnapshotMetrics(
                raw_total_clients=raw_total,
                raw_wifi_clients=raw_wifi,
                total_clients=total,
                wifi_clients=wifi,
                exclusion_reason="snapshot_count_out_of_range",
            )
        if wifi > total:
            return RouterSnapshotMetrics(
                raw_total_clients=raw_total,
                raw_wifi_clients=raw_wifi,
                total_clients=total,
                wifi_clients=wifi,
                exclusion_reason="inconsistent_snapshot_counts",
            )
        return RouterSnapshotMetrics(
            raw_total_clients=raw_total,
            raw_wifi_clients=raw_wifi,
            total_clients=total,
            wifi_clients=wifi,
            derived_wired_clients=total - wifi,
            eligible=True,
        )

    def _header_warnings(
        self,
        model: Optional[str],
        export_timestamp: Optional[datetime],
        hardware: Optional[str],
        firmware: Optional[str],
        interfaces: Dict[str, Dict[str, Optional[str]]],
        wan_gateway: Optional[str],
        wan_dns: Sequence[str],
        raw_total: Optional[str],
        raw_wifi: Optional[str],
    ) -> List[str]:
        warnings: List[str] = []
        for missing, value in (
            ("missing_model_header", model),
            ("missing_export_time_header", export_timestamp),
            ("missing_hardware_header", hardware),
            ("missing_firmware_header", firmware),
            ("missing_lan_header", interfaces.get("lan")),
            ("missing_wan_header", interfaces.get("wan")),
            ("missing_client_counts_header", raw_total if raw_wifi is not None else None),
        ):
            if value is None:
                warnings.append(missing)
        if interfaces.get("wan") is not None and (wan_gateway is None or not wan_dns):
            warnings.append("missing_wan_gateway_dns_header")
        return warnings

    @staticmethod
    def _versioned_digest(version: str, fields: Sequence[Optional[str]]) -> str:
        encoded = "\0".join([version, *(field if field is not None else "<null>" for field in fields)])
        return f"{version}:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _firmware_build_date(firmware: Optional[str]) -> Optional[date]:
        if firmware is None:
            return None
        match = re.search(r"\bBuild\s+(\d{8})\b", firmware, re.IGNORECASE)
        if match is None:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            return None

    def _classify_clock_and_boot(
        self,
        events: List[Event],
        export_timestamp: Optional[datetime],
        firmware: Optional[str],
        lan_mac: Optional[str],
    ) -> Tuple[List[Event], List[ClockSegment], List[BootSessionCandidate], List[str]]:
        if not events:
            return events, [], [], []
        firmware_date = self._firmware_build_date(firmware)
        explicit_boot_indices = [index for index, event in enumerate(events) if event.event_key == "ROUTER_BOOT"]
        startup_marker_indices = [
            index
            for index, event in enumerate(events)
            if self._is_startup_marker(event)
        ]
        candidate_starts = list(explicit_boot_indices)
        if startup_marker_indices and (
            not explicit_boot_indices or startup_marker_indices[0] < explicit_boot_indices[0]
        ):
            candidate_starts.insert(0, startup_marker_indices[0])
        candidate_starts = sorted(set(candidate_starts))
        context_number_by_start = {
            start: context_number for context_number, start in enumerate(candidate_starts, start=1)
        }
        epoch_starts = sorted(set([0, *candidate_starts]))
        epoch_ranges = [
            (start, epoch_starts[position + 1] if position + 1 < len(epoch_starts) else len(events))
            for position, start in enumerate(epoch_starts)
        ]
        trust_by_index = ["trusted"] * len(events)
        reason_by_index: List[Optional[str]] = [None] * len(events)
        epoch_by_index: List[Optional[int]] = [None] * len(events)
        clock_warnings: List[str] = []
        if export_timestamp is None:
            clock_warnings.append("clock_untrusted_missing_export_timestamp")

        for start, end in epoch_ranges:
            boot_at_start = start in candidate_starts
            if boot_at_start:
                context_number = context_number_by_start[start]
                for index in range(start, end):
                    epoch_by_index[index] = context_number

            if export_timestamp is None:
                for index in range(start, end):
                    trust_by_index[index] = "clock_untrusted"
                    reason_by_index[index] = "missing_export_timestamp"
                continue

            correction_index: Optional[int] = None
            for index in range(start + 1, end):
                delta = events[index].timestamp - events[index - 1].timestamp
                near_export = (
                    export_timestamp is not None
                    and timedelta(minutes=-5) <= export_timestamp - events[index].timestamp <= timedelta(hours=48)
                )
                if delta >= timedelta(hours=24) and near_export:
                    correction_index = index
                    break

            backward_boot_boundary = (
                boot_at_start
                and start > 0
                and events[start - 1].timestamp - events[start].timestamp > timedelta(minutes=5)
            )
            firmware_startup_cluster = (
                boot_at_start
                and firmware_date is not None
                and all(event.timestamp.date() == firmware_date for event in events[start:(correction_index or end)])
            )
            far_from_export = (
                export_timestamp is not None
                and export_timestamp - events[start].timestamp > timedelta(hours=48)
            )

            if correction_index is not None:
                early_trust = "pre_synchronization" if firmware_startup_cluster else "clock_untrusted"
                for index in range(start, correction_index):
                    trust_by_index[index] = early_trust
                    reason_by_index[index] = (
                        "firmware_date_pre_synchronization"
                        if early_trust == "pre_synchronization"
                        else "large_clock_correction"
                    )
                for index in range(correction_index, end):
                    trust_by_index[index] = "trusted"
                    reason_by_index[index] = None
            elif firmware_startup_cluster and far_from_export:
                for index in range(start, end):
                    trust_by_index[index] = "pre_synchronization"
                    reason_by_index[index] = "firmware_date_pre_synchronization"
            elif backward_boot_boundary:
                for index in range(start, end):
                    trust_by_index[index] = "clock_untrusted"
                    reason_by_index[index] = "boot_boundary_backward_correction"

            has_near_export_anchor = any(
                timedelta(minutes=-5) <= export_timestamp - events[index].timestamp <= timedelta(hours=48)
                for index in range(start, end)
            )
            for index in range(start, end):
                if trust_by_index[index] != "trusted":
                    continue
                if events[index].timestamp > export_timestamp + timedelta(minutes=5):
                    trust_by_index[index] = "clock_ambiguous"
                    reason_by_index[index] = "after_export_tolerance"
                elif not has_near_export_anchor:
                    trust_by_index[index] = "clock_untrusted"
                    reason_by_index[index] = "no_near_export_anchor"

            high_water: Optional[datetime] = None
            ambiguous_until: Optional[datetime] = None
            for index in range(start, end):
                if trust_by_index[index] != "trusted":
                    continue
                timestamp = events[index].timestamp
                if ambiguous_until is not None:
                    if timestamp >= ambiguous_until:
                        ambiguous_until = None
                        high_water = timestamp
                    else:
                        trust_by_index[index] = "clock_ambiguous"
                        reason_by_index[index] = "backward_clock_correction"
                    continue
                if high_water is not None and high_water - timestamp > timedelta(minutes=5):
                    ambiguous_until = high_water
                    trust_by_index[index] = "clock_ambiguous"
                    reason_by_index[index] = "backward_clock_correction"
                    continue
                high_water = timestamp if high_water is None else max(high_water, timestamp)

        classified: List[Event] = []
        segment_number = 0
        previous_trust: Optional[str] = None
        previous_epoch: Optional[int] = None
        for index, event in enumerate(events):
            epoch_number = epoch_by_index[index]
            if trust_by_index[index] != previous_trust or epoch_number != previous_epoch:
                segment_number += 1
            classified_event = replace(
                event,
                clock_trust=trust_by_index[index],
                clock_reason=reason_by_index[index],
                clock_segment_id=f"tp-link-clock-{segment_number}",
                boot_context_id=f"tp-link-boot-{epoch_number}" if epoch_number is not None else None,
            )
            if classified_event.clock_trust == "trusted":
                classified_event = replace(
                    classified_event,
                    trusted_overlap_identity=self._versioned_digest("trusted-overlap-v1", (
                        "tp-link",
                        lan_mac,
                        classified_event.timestamp.isoformat(sep=" "),
                        classified_event.component,
                        classified_event.process_id,
                        classified_event.vendor_event_code,
                        classified_event.syslog_severity,
                        classified_event.normalized_message,
                        classified_event.actor_scope,
                        classified_event.stable_client_identity,
                    )),
                )
            classified.append(classified_event)
            previous_trust = trust_by_index[index]
            previous_epoch = epoch_number

        segments: List[ClockSegment] = []
        for event in classified:
            if not segments or segments[-1].segment_id != event.clock_segment_id:
                segments.append(ClockSegment(
                    segment_id=event.clock_segment_id or "tp-link-clock",
                    clock_trust=event.clock_trust or "clock_untrusted",
                    start_sequence=event.source_sequence,
                    end_sequence=event.source_sequence,
                ))
            else:
                sequences = [
                    sequence
                    for sequence in (
                        segments[-1].start_sequence,
                        segments[-1].end_sequence,
                        event.source_sequence,
                    )
                    if sequence is not None
                ]
                segments[-1] = replace(
                    segments[-1],
                    start_sequence=min(sequences, default=None),
                    end_sequence=max(sequences, default=None),
                )

        boot_candidates: List[BootSessionCandidate] = []
        for candidate_number, boot_index in enumerate(candidate_starts, start=1):
            end = candidate_starts[candidate_number] if candidate_number < len(candidate_starts) else len(classified)
            boot_context_id = f"tp-link-boot-{epoch_by_index[boot_index]}"
            boot_events = classified[boot_index:end]
            trusted_events = [event for event in boot_events if event.clock_trust == "trusted"]
            overlap_ids = tuple(
                event.trusted_overlap_identity
                for event in trusted_events
                if event.trusted_overlap_identity is not None
            )
            startup_fields: List[Optional[str]] = ["tp-link", lan_mac]
            for event in boot_events:
                if not self._is_startup_marker(event):
                    break
                startup_fields.extend((
                    event.component,
                    event.vendor_event_code,
                    str(event.structured_evidence.get("action", "other")),
                ))
            boot_candidates.append(BootSessionCandidate(
                session_id=boot_context_id,
                start_sequence=classified[boot_index].source_sequence,
                trusted_anchor=trusted_events[0].timestamp if trusted_events else None,
                trusted_overlap_identities=overlap_ids,
                startup_signature=self._versioned_digest("startup-signature-v1", startup_fields),
                warnings=() if trusted_events else ("no_trusted_boot_anchor",),
            ))
        return classified, segments, boot_candidates, clock_warnings


ROUTER_LOG_ADAPTERS: Dict[str, RouterLogAdapter] = {
    FORMAT_NETGEAR: NetgearLogAdapter(),
    FORMAT_TP_LINK_ARCHER: TpLinkArcherAdapter(),
}


def _validate_adapter_detection_score(adapter: RouterLogAdapter, score: Any) -> float:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise SystemExit(f"Adapter {adapter.cli_format} returned an invalid detection score.")
    normalized_score = float(score)
    if not math.isfinite(normalized_score) or not 0.0 <= normalized_score <= 1.0:
        raise SystemExit(f"Adapter {adapter.cli_format} returned an invalid detection score.")
    return normalized_score


def _format_adapter_detection_score(score: float) -> str:
    decimal_score = Decimal(str(score))
    if decimal_score.as_tuple().exponent >= -2:
        return f"{score:.2f}"
    return format(decimal_score.normalize(), "f")


def _adapter_selection_error(prefix: str, scored: Sequence[Tuple[RouterLogAdapter, float]]) -> SystemExit:
    candidates = ", ".join(
        f"{adapter.cli_format}={_format_adapter_detection_score(score)}" for adapter, score in scored
    )
    return SystemExit(f"{prefix} Available format confidence: {candidates}.")


def select_router_adapter(text: str, requested_format: str = AUTO_FORMAT) -> RouterLogAdapter:
    if requested_format == AUTO_FORMAT:
        scored = [
            (adapter, _validate_adapter_detection_score(adapter, adapter.detect(text)))
            for adapter in ROUTER_LOG_ADAPTERS.values()
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        top_adapter, top_score = scored[0]
        if top_score < FORMAT_DETECTION_THRESHOLD:
            raise _adapter_selection_error("Could not confidently identify a supported router log format.", scored)
        contenders = [item for item in scored if item[1] >= FORMAT_DETECTION_THRESHOLD]
        if len(contenders) > 1 and (
            Decimal(str(contenders[0][1])) - Decimal(str(contenders[1][1]))
        ) < Decimal(str(FORMAT_AMBIGUITY_MARGIN)):
            raise _adapter_selection_error("Router log format is ambiguous.", contenders)
        return top_adapter
    format_id = CLI_FORMAT_TO_ID.get(requested_format)
    if format_id is None:
        raise SystemExit(f"Unsupported --format value: {requested_format}")
    return ROUTER_LOG_ADAPTERS[format_id]


def parse_router_log(text: str, source: str, requested_format: str = AUTO_FORMAT) -> ParsedRouterLog:
    return select_router_adapter(text, requested_format).parse(text, source)


def reconstruct_wrapped_log_lines(text: str) -> List[str]:
    """Compatibility helper for existing callers of NETGEAR reconstruction."""
    return ROUTER_LOG_ADAPTERS[FORMAT_NETGEAR].reconstruct_wrapped_log_lines(text)  # type: ignore[attr-defined]


def build_event_objects(text: str, source: str) -> Tuple[List[Event], ParseStats]:
    """Compatibility helper for existing callers of NETGEAR normalization."""
    return ROUTER_LOG_ADAPTERS[FORMAT_NETGEAR].build_event_objects(text, source)  # type: ignore[attr-defined]


def parse_log_text(text: str, source: str) -> Tuple[List[Event], ParseStats]:
    # This long-standing helper is intentionally permissive for callers that
    # need malformed/noise accounting; CLI ingestion uses parse_router_log().
    return ROUTER_LOG_ADAPTERS[FORMAT_NETGEAR].build_event_objects(text, source)  # type: ignore[attr-defined]


def find_cluster_profiles(baseline: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    profiles: Dict[str, Dict[str, Any]] = {}
    for key, config in baseline.get("devices", {}).items():
        if isinstance(config, dict) and config.get("type") == "cluster":
            profiles[key] = config
    return profiles


def cluster_profile_for_mac(mac: str, cluster_profiles: Dict[str, Dict[str, Any]]) -> Optional[str]:
    if not is_real_mac(mac):
        return None
    for cluster_name, profile in cluster_profiles.items():
        for prefix in profile.get("mac_prefixes") or []:
            if mac.startswith(prefix.upper()):
                return cluster_name
    return None


def build_full_days(events: List[Event]) -> Set[date]:
    if not events:
        return set()
    unique_days = sorted({event.timestamp.date() for event in events})
    if len(unique_days) <= 2:
        return set(unique_days)
    return set(unique_days[1:-1])


def attribute_ip_only_events(events: Sequence[Event]) -> List[Event]:
    assignments_by_ip: DefaultDict[str, List[Tuple[datetime, str]]] = defaultdict(list)
    unique_mac_by_ip: Dict[str, str] = {}
    for event in events:
        if event.event_family != "DHCP" or not event.ip or not is_real_mac(event.mac):
            continue
        assignments_by_ip[event.ip].append((event.timestamp, event.mac))

    for ip, assignments in assignments_by_ip.items():
        assignments.sort()
        unique_macs = {mac for _, mac in assignments}
        if len(unique_macs) == 1:
            unique_mac_by_ip[ip] = next(iter(unique_macs))

    attributed: List[Event] = []
    for event in events:
        if event.mac != SYSTEM_ACTOR or not event.ip or event.event_family == "DHCP":
            attributed.append(event)
            continue
        assignments = assignments_by_ip.get(event.ip) or []
        resolved_mac: Optional[str] = None
        for timestamp, mac in reversed(assignments):
            if timestamp <= event.timestamp:
                resolved_mac = mac
                break
        if resolved_mac is None:
            resolved_mac = unique_mac_by_ip.get(event.ip)
        if resolved_mac is None:
            attributed.append(event)
            continue
        attributed.append(replace(event, mac=resolved_mac))
    return attributed


def aggregate_events(
    events: List[Event],
    seed_baseline: Dict[str, Any],
    devices_snapshot: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    events = attribute_ip_only_events(events)
    cluster_profiles = find_cluster_profiles(seed_baseline)
    mac_to_name: Dict[str, str] = {
        mac: (device.get("name") or mac)
        for mac, device in devices_snapshot.items()
    }
    for mac, config in seed_baseline.get("devices", {}).items():
        if isinstance(config, dict) and is_real_mac(mac):
            mac_to_name[mac] = config.get("name") or mac
    mac_to_name[SYSTEM_ACTOR] = SYSTEM_NAME

    events_by_mac: DefaultDict[str, List[Event]] = defaultdict(list)
    dhcp_events_by_mac: DefaultDict[str, List[Event]] = defaultdict(list)
    device_day_stats: Dict[Tuple[str, str], DeviceDayAggregate] = {}
    event_day_stats: Dict[Tuple[str, str, str], EventDayAggregate] = {}
    events_per_hour: Counter = Counter()
    cluster_events: DefaultDict[str, List[Event]] = defaultdict(list)

    for event in events:
        observed_date = event.timestamp.date().isoformat()
        events_per_hour[event.timestamp.hour] += 1
        events_by_mac[event.mac].append(event)
        if event.event_family == "DHCP":
            dhcp_events_by_mac[event.mac].append(event)
        device_key = (observed_date, event.mac)
        if device_key not in device_day_stats:
            device_day_stats[device_key] = DeviceDayAggregate(observed_date=observed_date, mac=event.mac)
        device_day_stats[device_key].add_event(event)

        event_key = (observed_date, event.mac, event.event_key)
        if event_key not in event_day_stats:
            event_day_stats[event_key] = EventDayAggregate(
                observed_date=observed_date,
                mac=event.mac,
                event_key=event.event_key,
                event_family=event.event_family,
            )
        event_day_stats[event_key].add_event(event)

        cluster_name = cluster_profile_for_mac(event.mac, cluster_profiles)
        if cluster_name and event.event_family == "DHCP":
            cluster_events[cluster_name].append(event)

    observed_dates = sorted({event.timestamp.date().isoformat() for event in events})
    full_days = build_full_days(events)
    return {
        "events": events,
        "events_by_mac": dict(events_by_mac),
        "dhcp_events_by_mac": dict(dhcp_events_by_mac),
        "device_day_stats": device_day_stats,
        "event_day_stats": event_day_stats,
        "events_per_hour": dict(sorted(events_per_hour.items())),
        "mac_to_name": mac_to_name,
        "devices_snapshot": devices_snapshot,
        "cluster_profiles": cluster_profiles,
        "cluster_events": dict(cluster_events),
        "observed_dates": observed_dates,
        "full_days": full_days,
        "observation_range": {
            "start": events[0].timestamp.isoformat() if events else None,
            "end": events[-1].timestamp.isoformat() if events else None,
        },
    }


def is_known_allowed_incident_device(
    mac: str,
    seed_baseline: Dict[str, Any],
    devices_snapshot: Dict[str, Dict[str, Any]],
) -> bool:
    if not is_real_mac(mac):
        return False
    snapshot = devices_snapshot.get(mac, {})
    if (snapshot.get("status") or "").lower() == "blocked":
        return False
    if (snapshot.get("status") or "").lower() == "allowed":
        return True
    return mac in seed_baseline.get("devices", {})


def active_known_incident_macs(
    events: Sequence[Event],
    candidate_dates: Set[date],
    seed_baseline: Dict[str, Any],
    devices_snapshot: Dict[str, Dict[str, Any]],
) -> Set[str]:
    return {
        event.mac
        for event in events
        if event.timestamp.date() in candidate_dates
        and is_known_allowed_incident_device(event.mac, seed_baseline, devices_snapshot)
    }


def incident_threshold_met(
    affected_macs: Set[str],
    active_macs: Set[str],
    minimum_devices: int,
    minimum_fraction: float,
) -> bool:
    active_count = max(len(active_macs), len(affected_macs), 1)
    return len(affected_macs) >= minimum_devices and len(affected_macs) / active_count >= minimum_fraction


def build_network_incident(
    incident_id: str,
    confidence: str,
    start: datetime,
    restored_at: datetime,
    recovery_end: datetime,
    transition_events: Sequence[Event],
    recovery_events: Sequence[Event],
    active_macs: Set[str],
    disconnect_keys: Set[str],
    connect_keys: Set[str],
) -> NetworkIncident:
    affected_macs = sorted({event.mac for event in recovery_events})
    event_counts = Counter(event.event_key for event in [*transition_events, *recovery_events])
    active_count = max(len(active_macs), len(affected_macs), 1)
    return NetworkIncident(
        incident_id=incident_id,
        incident_type="internet_connection_reset",
        confidence=confidence,
        start=start.isoformat(),
        restored_at=restored_at.isoformat(),
        recovery_end=recovery_end.isoformat(),
        disconnect_count=sum(event.event_key in disconnect_keys for event in transition_events),
        connect_count=sum(event.event_key in connect_keys for event in transition_events),
        affected_macs=affected_macs,
        event_counts=dict(sorted(event_counts.items())),
        explained_event_count=len(transition_events) + len(recovery_events),
        active_known_devices=active_count,
        affected_device_fraction=round(len(affected_macs) / active_count, 4),
    )


def annotate_incident_events(
    incident: NetworkIncident,
    transition_events: Sequence[Event],
    recovery_events: Sequence[Event],
) -> None:
    for event in transition_events:
        if event.incident_id is None:
            event.incident_id = incident.incident_id
            event.incident_role = "wan_transition"
    for event in recovery_events:
        if event.incident_id is None:
            event.incident_id = incident.incident_id
            event.incident_role = "recovery"


def completed_wan_transition_groups(
    events: Sequence[Event],
    disconnect_keys: Set[str],
    connect_keys: Set[str],
    merge_gap_seconds: int,
) -> List[List[Event]]:
    transitions = sorted(
        (event for event in events if event.event_key in disconnect_keys | connect_keys),
        key=lambda event: event.timestamp,
    )
    completed: List[List[Event]] = []
    current: List[Event] = []
    has_connected = False
    for event in transitions:
        if not current:
            if event.event_key in disconnect_keys:
                current = [event]
                has_connected = False
            continue
        gap_seconds = (event.timestamp - current[-1].timestamp).total_seconds()
        if has_connected and gap_seconds > merge_gap_seconds:
            if current[-1].event_key in connect_keys:
                completed.append(current)
            current = [event] if event.event_key in disconnect_keys else []
            has_connected = False
            continue
        current.append(event)
        if event.event_key in disconnect_keys:
            has_connected = False
        elif event.event_key in connect_keys:
            has_connected = True
    if current and has_connected and current[-1].event_key in connect_keys:
        completed.append(current)
    return completed


def detect_network_incidents(
    events: Sequence[Event],
    seed_baseline: Dict[str, Any],
    devices_snapshot: Dict[str, Dict[str, Any]],
    policy: Dict[str, Any],
) -> List[NetworkIncident]:
    for event in events:
        event.incident_id = None
        event.incident_role = None

    config = policy.get("network_incidents", {})
    if not config.get("enabled", True):
        return []

    ordered_events = sorted(events, key=lambda event: event.timestamp)
    disconnect_keys = set(config.get("disconnect_event_keys") or ["INTERNET_DISCONNECTED"])
    connect_keys = set(config.get("connect_event_keys") or ["INTERNET_CONNECTED"])
    recovery_keys = set(config.get("recovery_event_keys") or ["DHCP_IP", "WLAN_ACCESS_ALLOWED"])
    recovery_window = timedelta(seconds=int(config.get("recovery_window_seconds", 300)))
    incidents: List[NetworkIncident] = []

    transition_groups = completed_wan_transition_groups(
        ordered_events,
        disconnect_keys,
        connect_keys,
        int(config.get("merge_gap_seconds", 300)),
    )
    for transition_group in transition_groups:
        start = transition_group[0].timestamp
        restored_at = max(
            event.timestamp for event in transition_group if event.event_key in connect_keys
        )
        recovery_start = max(
            start,
            restored_at - timedelta(seconds=int(config.get("recovery_lookback_seconds", 300))),
        )
        recovery_end = restored_at + recovery_window
        recovery_events = [
            event
            for event in ordered_events
            if recovery_start <= event.timestamp <= recovery_end
            and event.event_key in recovery_keys
            and is_known_allowed_incident_device(event.mac, seed_baseline, devices_snapshot)
        ]
        affected_macs = {event.mac for event in recovery_events}
        candidate_dates = {start.date(), recovery_end.date()}
        active_macs = active_known_incident_macs(
            ordered_events,
            candidate_dates,
            seed_baseline,
            devices_snapshot,
        )
        if not incident_threshold_met(
            affected_macs,
            active_macs,
            int(config.get("minimum_known_devices", 5)),
            float(config.get("minimum_known_device_fraction", 0.25)),
        ):
            continue
        incident_id = f"network-reset-{start.strftime('%Y%m%dT%H%M%S')}-{len(incidents) + 1}"
        incident = build_network_incident(
            incident_id,
            "confirmed",
            start,
            restored_at,
            recovery_end,
            transition_group,
            recovery_events,
            active_macs,
            disconnect_keys,
            connect_keys,
        )
        annotate_incident_events(incident, transition_group, recovery_events)
        incidents.append(incident)

    inferred_candidates = [
        event
        for event in ordered_events
        if event.incident_id is None
        and event.event_key in recovery_keys
        and is_known_allowed_incident_device(event.mac, seed_baseline, devices_snapshot)
    ]
    inferred_window = timedelta(seconds=int(config.get("inferred_window_seconds", 300)))
    candidate_index = 0
    while candidate_index < len(inferred_candidates):
        start_event = inferred_candidates[candidate_index]
        window_end = start_event.timestamp + inferred_window
        end_index = candidate_index
        while end_index < len(inferred_candidates) and inferred_candidates[end_index].timestamp <= window_end:
            end_index += 1
        recovery_events = inferred_candidates[candidate_index:end_index]
        affected_macs = {event.mac for event in recovery_events}
        candidate_dates = {start_event.timestamp.date(), window_end.date()}
        active_macs = active_known_incident_macs(
            ordered_events,
            candidate_dates,
            seed_baseline,
            devices_snapshot,
        )
        qualifies = incident_threshold_met(
            affected_macs,
            active_macs,
            int(config.get("inferred_minimum_known_devices", 8)),
            float(config.get("inferred_minimum_known_device_fraction", 0.5)),
        )
        if config.get("inferred_require_dhcp", True):
            qualifies = qualifies and any(event.event_key == "DHCP_IP" for event in recovery_events)
        preceding_transitions = [
            event
            for event in ordered_events
            if event.event_key in disconnect_keys | connect_keys and event.timestamp <= window_end
        ]
        if preceding_transitions and preceding_transitions[-1].event_key in disconnect_keys:
            # An unresolved outage is not a benign reset. Wait for an explicit
            # reconnect instead of allowing burst inference to hide it.
            qualifies = False
        if not qualifies:
            candidate_index += 1
            continue
        restored_at = start_event.timestamp
        recovery_end = recovery_events[-1].timestamp
        incident_id = f"probable-network-reset-{start_event.timestamp.strftime('%Y%m%dT%H%M%S')}-{len(incidents) + 1}"
        incident = build_network_incident(
            incident_id,
            "probable",
            start_event.timestamp,
            restored_at,
            recovery_end,
            [],
            recovery_events,
            active_macs,
            disconnect_keys,
            connect_keys,
        )
        annotate_incident_events(incident, [], recovery_events)
        incidents.append(incident)
        candidate_index = end_index

    return incidents


def network_incident_findings(
    incidents: Sequence[NetworkIncident],
    policy: Dict[str, Any],
) -> List[Finding]:
    config = policy.get("network_incidents", {})
    findings: List[Finding] = []
    for incident in incidents:
        severity = str(config.get(f"{incident.confidence}_severity", "low"))
        findings.append(
            Finding(
                kind="network_reset",
                severity=severity,
                mac=None,
                event_count=incident.explained_event_count,
                message=(
                    f"{incident.confidence.title()} internet connection reset affected "
                    f"{len(incident.affected_macs)} known device(s)."
                ),
                metadata={
                    **asdict(incident),
                    "day": incident.start[:10],
                },
            )
        )
    return findings


def apply_tolerance(
    value: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    soft_max: Optional[float] = None,
    missing_bias: bool = False,
) -> Dict[str, Any]:
    upper = soft_max if soft_max is not None else maximum
    result = {
        "state": "normal",
        "severity": "normal",
        "direction": "normal",
        "minimum": minimum,
        "maximum": maximum,
        "soft_max": soft_max,
        "value": value,
    }
    if minimum is not None and value < minimum:
        result["state"] = "anomaly"
        result["direction"] = "below"
        if missing_bias:
            result["severity"] = "low" if value > 0 else "medium"
            return result
        if minimum <= 0:
            result["severity"] = "low"
            return result
        ratio = value / minimum
        if ratio >= 0.5:
            result["severity"] = "low"
        elif ratio >= 0.25:
            result["severity"] = "medium"
        else:
            result["severity"] = "high"
        return result
    if upper is not None and value > upper:
        result["state"] = "anomaly"
        result["direction"] = "above"
        if upper <= 0:
            result["severity"] = "high"
        elif value <= upper * 1.5:
            result["severity"] = "low"
        elif value <= upper * 2:
            result["severity"] = "medium"
        else:
            result["severity"] = "high"
        return result
    return result


def classify_severity(tolerance_result: Dict[str, Any], fallback: str = "medium") -> str:
    severity = tolerance_result.get("severity")
    if tolerance_result.get("state") == "normal" or severity in {None, "normal"}:
        return "normal"
    return severity if severity in SEVERITY_ORDER else fallback


def circular_hour_distance(hour_a: float, hour_b: float) -> float:
    direct = abs(hour_a - hour_b)
    return min(direct, 24 - direct)


def distance_to_windows_hours(timestamp: datetime, windows: Sequence[Dict[str, Any]]) -> float:
    hour = timestamp.hour + (timestamp.minute / 60.0)
    distances: List[float] = []
    for window in windows:
        start_hour = float(window.get("start_hour", 0))
        end_hour = float(window.get("end_hour", 24))
        if start_hour <= hour <= end_hour:
            return 0.0
        if hour < start_hour:
            distances.append(start_hour - hour)
        else:
            distances.append(hour - end_hour)
    return min(distances) if distances else 0.0


def distance_to_active_hours(event: Event, active_hours: Sequence[int]) -> float:
    if not active_hours:
        return 0.0
    hour = event.timestamp.hour
    distances = [min(abs(hour - candidate), 24 - abs(hour - candidate)) for candidate in active_hours]
    return float(min(distances))


def within_expected_event(timestamp: datetime, expected_event: Dict[str, Any]) -> bool:
    target = timestamp.replace(
        hour=int(expected_event.get("hour", 0)),
        minute=int(expected_event.get("minute", 0)),
        second=0,
        microsecond=0,
    )
    tolerance = int(expected_event.get("tolerance_minutes", 0))
    return abs((timestamp - target).total_seconds()) <= tolerance * 60


def normalize_range(range_value: Any) -> Optional[Tuple[float, float]]:
    minimum = value_at(range_value, 0)
    maximum = value_at(range_value, 1)
    if minimum is None or maximum is None:
        return None
    return minimum, maximum


def compute_numeric_profile(
    values: Sequence[float],
    seed_range: Optional[Tuple[float, float]],
    seed_weight: float,
    stddev_floor: float,
) -> Optional[Dict[str, Any]]:
    if not values and not seed_range:
        return None
    weighted_count = float(len(values))
    weighted_sum = float(sum(values))
    weighted_squares = float(sum(value * value for value in values))
    sources = "history_only"
    if seed_range is not None:
        seed_mean = (seed_range[0] + seed_range[1]) / 2.0
        seed_std = max((seed_range[1] - seed_range[0]) / 4.0, stddev_floor)
        weighted_count += seed_weight
        weighted_sum += seed_mean * seed_weight
        weighted_squares += (seed_std ** 2 + seed_mean ** 2) * seed_weight
        sources = "blended" if values else "seed_only"
    mean = weighted_sum / max(weighted_count, 1.0)
    variance = max((weighted_squares / max(weighted_count, 1.0)) - (mean ** 2), stddev_floor ** 2)
    stddev = math.sqrt(variance)
    history_values = list(values)
    trend = "flat"
    if len(history_values) >= 2:
        recent = history_values[0]
        oldest = history_values[-1]
        if recent > oldest + stddev_floor:
            trend = "increasing"
        elif recent < oldest - stddev_floor:
            trend = "decreasing"
    return {
        "source": sources,
        "history_count": len(values),
        "weighted_count": weighted_count,
        "mean": mean,
        "stddev": stddev,
        "range_min": max(0.0, mean - 2 * stddev),
        "range_max": max(0.0, mean + 2 * stddev),
        "trend": trend,
    }


def build_device_metric_profile(
    store: StateStore,
    epoch_id: int,
    mac: str,
    observed_date: str,
    field_name: str,
    seed_range: Optional[Tuple[float, float]],
    policy: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    history_rows = store.fetch_device_metric_history(
        epoch_id,
        mac,
        observed_date,
        int(policy["learning"]["rolling_days_frequent"]),
    )
    values = [float(row[field_name]) for row in history_rows]
    return compute_numeric_profile(
        values=values,
        seed_range=seed_range,
        seed_weight=float(policy["learning"]["seed_weight_frequent"]),
        stddev_floor=float(policy["learning"]["stddev_floor"]),
    )


def weighted_hour_mean(histogram: Dict[str, Any]) -> Optional[float]:
    if not histogram:
        return None
    total = 0
    weighted = 0.0
    for raw_hour, raw_count in histogram.items():
        hour = int(raw_hour)
        count = int(raw_count)
        weighted += hour * count
        total += count
    return (weighted / total) if total else None


def build_event_profile(
    store: StateStore,
    epoch_id: int,
    mac: str,
    event_key: str,
    observed_date: str,
    policy: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    event_rows = store.fetch_event_history(
        epoch_id,
        mac,
        event_key,
        observed_date,
        int(policy["learning"]["rolling_days_sparse"]),
    )
    device_rows = store.fetch_device_history(
        epoch_id,
        mac,
        observed_date,
        int(policy["learning"]["rolling_days_sparse"]),
    )
    if not event_rows or not device_rows:
        return None

    count_values = [float(row["count"]) for row in event_rows]
    count_profile = compute_numeric_profile(
        values=count_values,
        seed_range=None,
        seed_weight=0.0,
        stddev_floor=float(policy["learning"]["stddev_floor"]),
    )
    weekday_counts: Counter = Counter()
    all_hours: List[float] = []
    for row in event_rows:
        row_date = date.fromisoformat(row["observed_date"])
        weekday_counts[row_date.weekday()] += 1
        hour_hist = json.loads(row["hour_histogram_json"] or "{}")
        hour_mean = weighted_hour_mean(hour_hist)
        if hour_mean is not None:
            all_hours.append(hour_mean)

    dominant_weekdays: List[int] = []
    if weekday_counts:
        highest = max(weekday_counts.values())
        if highest / max(len(event_rows), 1) >= 0.6:
            dominant_weekdays = sorted(
                weekday for weekday, count in weekday_counts.items() if count == highest
            )

    typical_hour = sum(all_hours) / len(all_hours) if all_hours else None
    hour_stddev = None
    if len(all_hours) >= 2 and typical_hour is not None:
        variance = sum((hour - typical_hour) ** 2 for hour in all_hours) / len(all_hours)
        hour_stddev = math.sqrt(max(variance, 0.0))

    return {
        "history_count": len(event_rows),
        "observed_device_days": len(device_rows),
        "presence_rate": len(event_rows) / max(len(device_rows), 1),
        "count_profile": count_profile,
        "dominant_weekdays": dominant_weekdays,
        "typical_hour": typical_hour,
        "hour_stddev": hour_stddev,
        "historical_dates": [row["observed_date"] for row in event_rows],
    }


def event_day_hour_mean(stat: EventDayAggregate) -> Optional[float]:
    if not stat.hour_histogram:
        return None
    total = sum(stat.hour_histogram.values())
    if not total:
        return None
    return sum(hour * count for hour, count in stat.hour_histogram.items()) / total


def streak_length(dates_present: Set[str], current_date: str) -> int:
    streak = 0
    cursor = date.fromisoformat(current_date)
    while cursor.isoformat() in dates_present:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def normalized_device_name(name: Optional[str], mac: Optional[str]) -> Optional[str]:
    if not name:
        return None
    stripped = name.strip()
    if not stripped or stripped == mac:
        return None
    return stripped


def is_configured_allowed_device(mac: Optional[str], aggregate: Dict[str, Any]) -> bool:
    if not is_real_mac(mac):
        return False
    device = aggregate.get("devices_snapshot", {}).get(mac or "", {})
    return (
        isinstance(device, dict)
        and (device.get("status") or "").lower() == "allowed"
        and (device.get("source") or "") == "config_import"
    )


def has_short_window_repeat(events: Sequence[Event], window_seconds: int) -> bool:
    if len(events) < 2:
        return False
    ordered = sorted(events, key=lambda event: event.timestamp)
    return any(
        (current.timestamp - previous.timestamp).total_seconds() <= window_seconds
        for previous, current in zip(ordered, ordered[1:])
    )


def cap_configured_allowed_wlan_access_severity(
    severity: str,
    aggregate: Dict[str, Any],
    mac: Optional[str],
    event_key: Optional[str],
    events: Sequence[Event],
    policy: Dict[str, Any],
) -> str:
    if severity not in SEVERITY_ORDER or event_key != "WLAN_ACCESS_ALLOWED":
        return severity
    if not is_configured_allowed_device(mac, aggregate):
        return severity
    burst_window_seconds = int(policy["noise_suppression"].get("configured_allowed_burst_window_seconds", 300))
    if has_short_window_repeat(events, burst_window_seconds):
        return severity
    return min_severity(severity, "low")


def enforce_policy_severity(
    severity: str,
    policy: Dict[str, Any],
    event_key: Optional[str] = None,
    event_family: Optional[str] = None,
    mac: Optional[str] = None,
    device_name: Optional[str] = None,
    finding_kind: Optional[str] = None,
    cluster_name: Optional[str] = None,
) -> str:
    result = severity
    overrides: List[Dict[str, Any]] = []
    if finding_kind:
        override = policy.get("finding_overrides", {}).get(finding_kind)
        if isinstance(override, dict):
            overrides.append(override)
    if mac:
        override = policy.get("device_overrides", {}).get(mac)
        if isinstance(override, dict):
            overrides.append(override)
            finding_override = override.get("finding_overrides", {}).get(finding_kind) if finding_kind else None
            if isinstance(finding_override, dict):
                overrides.append(finding_override)
    if device_name:
        override = policy.get("device_name_overrides", {}).get(device_name)
        if isinstance(override, dict):
            overrides.append(override)
            finding_override = override.get("finding_overrides", {}).get(finding_kind) if finding_kind else None
            if isinstance(finding_override, dict):
                overrides.append(finding_override)
    if cluster_name:
        override = policy.get("cluster_overrides", {}).get(cluster_name)
        if isinstance(override, dict):
            overrides.append(override)
            finding_override = override.get("finding_overrides", {}).get(finding_kind) if finding_kind else None
            if isinstance(finding_override, dict):
                overrides.append(finding_override)
    if event_family:
        override = policy.get("event_family_overrides", {}).get(event_family)
        if isinstance(override, dict):
            overrides.append(override)
    if event_key:
        override = policy.get("event_overrides", {}).get(event_key)
        if isinstance(override, dict):
            overrides.append(override)

    for override in overrides:
        if override.get("suppress") is True:
            return "normal"
        minimum = override.get("minimum_severity")
        if minimum in SEVERITY_ORDER:
            result = max_severity(result, minimum)
        maximum = override.get("maximum_severity")
        if maximum in SEVERITY_ORDER:
            result = min_severity(result, maximum)
    return result


def detect_unknown_devices(
    aggregate: Dict[str, Any],
    seed_baseline: Dict[str, Any],
    devices_snapshot: Dict[str, Dict[str, Any]],
    policy: Dict[str, Any],
) -> List[Finding]:
    findings: List[Finding] = []
    baseline_devices = {
        mac for mac in seed_baseline.get("devices", {}) if is_real_mac(mac)
    }
    cluster_profiles = aggregate["cluster_profiles"]
    allowed_macs = {
        mac
        for mac, device in devices_snapshot.items()
        if (device.get("status") or "").lower() == "allowed"
    }
    for mac, events in sorted(aggregate["events_by_mac"].items()):
        if mac == SYSTEM_ACTOR:
            continue
        if mac in baseline_devices or mac in allowed_macs or cluster_profile_for_mac(mac, cluster_profiles):
            continue
        device_name = normalized_device_name(devices_snapshot.get(mac, {}).get("name"), mac)
        severity = enforce_policy_severity(
            "critical",
            policy,
            mac=mac,
            device_name=device_name,
            finding_kind="unknown_device",
        )
        if severity == "normal":
            continue
        findings.append(
            Finding(
                kind="unknown_device",
                severity=severity,
                mac=mac,
                event_count=len(events),
                message=f"Observed unknown device {mac} with {len(events)} event(s).",
            )
        )
    return findings


def detect_blocked_devices(
    aggregate: Dict[str, Any],
    devices_snapshot: Dict[str, Dict[str, Any]],
    policy: Dict[str, Any],
) -> List[Finding]:
    blocked_macs = {
        mac for mac, device in devices_snapshot.items()
        if (device.get("status") or "").lower() == "blocked"
    }
    findings: List[Finding] = []
    for mac, events in sorted(aggregate["events_by_mac"].items()):
        if mac not in blocked_macs:
            continue
        device_name = normalized_device_name(devices_snapshot.get(mac, {}).get("name"), mac)
        severity = enforce_policy_severity(
            "critical",
            policy,
            mac=mac,
            device_name=device_name,
            finding_kind="blocked_device_activity",
        )
        if severity == "normal":
            continue
        findings.append(
            Finding(
                kind="blocked_device_activity",
                severity=severity,
                mac=mac,
                event_count=len(events),
                message=f"Blocked device {mac} generated {len(events)} event(s).",
            )
        )
    return findings


def detect_device_metric_anomalies(
    aggregate: Dict[str, Any],
    seed_baseline: Dict[str, Any],
    store: StateStore,
    epoch_id: int,
    policy: Dict[str, Any],
) -> List[Finding]:
    findings: List[Finding] = []
    seed_devices = seed_baseline.get("devices", {})
    for (observed_date, mac), stat in sorted(aggregate["device_day_stats"].items()):
        if mac == SYSTEM_ACTOR:
            continue
        seed_config = seed_devices.get(mac, {})
        device_name = normalized_device_name(aggregate.get("mac_to_name", {}).get(mac), mac)

        dhcp_profile = build_device_metric_profile(
            store,
            epoch_id,
            mac,
            observed_date,
            "dhcp_count",
            normalize_range(seed_config.get("dhcp_per_day_range")),
            policy,
        )
        if dhcp_profile is not None:
            tolerance = apply_tolerance(
                stat.dhcp_count,
                minimum=max(0.0, dhcp_profile["range_min"]),
                maximum=dhcp_profile["range_max"],
                soft_max=seed_config.get("soft_max"),
                missing_bias=True,
            )
            severity = classify_severity(tolerance)
            severity = enforce_policy_severity(
                severity,
                policy,
                event_key="DHCP_IP",
                event_family="DHCP",
                mac=mac,
                device_name=device_name,
                finding_kind="dhcp_anomaly",
            )
            if severity != "normal":
                findings.append(
                    Finding(
                        kind="dhcp_anomaly",
                        severity=severity,
                        mac=mac,
                        event_count=stat.dhcp_count,
                        message=f"DHCP activity for {mac} on {observed_date} was {stat.dhcp_count}.",
                        metadata={
                            "day": observed_date,
                            "observed": stat.dhcp_count,
                            "expected_range": [
                                round(max(0.0, dhcp_profile["range_min"]), 2),
                                round(dhcp_profile["range_max"], 2),
                            ],
                            "learned_mean": round(dhcp_profile["mean"], 2),
                            "learned_stddev": round(dhcp_profile["stddev"], 2),
                            "trend": dhcp_profile["trend"],
                            "direction": tolerance["direction"],
                        },
                    )
                )

        total_range = normalize_range(seed_config.get("events_per_day"))
        total_profile = build_device_metric_profile(
            store,
            epoch_id,
            mac,
            observed_date,
            "total_events",
            total_range,
            policy,
        )
        if total_profile is not None:
            tolerance = apply_tolerance(
                stat.total_events,
                minimum=max(0.0, total_profile["range_min"]),
                maximum=total_profile["range_max"],
                soft_max=seed_config.get("soft_max"),
                missing_bias=True,
            )
            severity = classify_severity(tolerance)
            severity = enforce_policy_severity(
                severity,
                policy,
                mac=mac,
                device_name=device_name,
                finding_kind="event_volume_anomaly",
            )
            if severity != "normal":
                findings.append(
                    Finding(
                        kind="event_volume_anomaly",
                        severity=severity,
                        mac=mac,
                        event_count=stat.total_events,
                        message=f"Daily event count for {mac} on {observed_date} was {stat.total_events}.",
                        metadata={
                            "day": observed_date,
                            "observed": stat.total_events,
                            "expected_range": [
                                round(max(0.0, total_profile["range_min"]), 2),
                                round(total_profile["range_max"], 2),
                            ],
                            "learned_mean": round(total_profile["mean"], 2),
                            "learned_stddev": round(total_profile["stddev"], 2),
                            "trend": total_profile["trend"],
                            "direction": tolerance["direction"],
                        },
                    )
                )
    return findings


def detect_timing_anomalies(
    aggregate: Dict[str, Any],
    seed_baseline: Dict[str, Any],
    policy: Dict[str, Any],
) -> List[Finding]:
    findings: List[Finding] = []
    low_shift = float(policy["timing"]["low_shift_hours"])
    for (observed_date, mac), stat in sorted(aggregate["device_day_stats"].items()):
        seed_config = seed_baseline.get("devices", {}).get(mac, {})
        if not isinstance(seed_config, dict):
            continue
        device_name = normalized_device_name(aggregate.get("mac_to_name", {}).get(mac), mac)
        expected_windows = seed_config.get("expected_windows") or []
        if expected_windows:
            outside = [event for event in stat.events if not is_in_windows(event.timestamp, expected_windows)]
            if outside:
                distance = max(distance_to_windows_hours(event.timestamp, expected_windows) for event in outside)
                severity = "low" if distance <= low_shift else "medium"
                severity = enforce_policy_severity(
                    severity,
                    policy,
                    mac=mac,
                    device_name=device_name,
                    finding_kind="timing_anomaly",
                )
                findings.append(
                    Finding(
                        kind="timing_anomaly",
                        severity=severity,
                        mac=mac,
                        event_count=len(outside),
                        message=f"{len(outside)} event(s) for {mac} fell outside expected windows.",
                        metadata={
                            "day": observed_date,
                            "distance_hours": round(distance, 2),
                            "hours": [event.timestamp.isoformat() for event in outside[:5]],
                            "expected_windows": expected_windows,
                        },
                    )
                )

        active_hours = seed_config.get("active_hours") or []
        if active_hours:
            outside = [event for event in stat.events if event.timestamp.hour not in active_hours]
            if outside:
                distance = max(distance_to_active_hours(event, active_hours) for event in outside)
                severity = "low" if distance <= low_shift else "medium"
                severity = enforce_policy_severity(
                    severity,
                    policy,
                    mac=mac,
                    device_name=device_name,
                    finding_kind="timing_anomaly",
                )
                findings.append(
                    Finding(
                        kind="timing_anomaly",
                        severity=severity,
                        mac=mac,
                        event_count=len(outside),
                        message=f"{len(outside)} event(s) for {mac} occurred outside active hours.",
                        metadata={
                            "day": observed_date,
                            "distance_hours": round(distance, 2),
                            "hours": [event.timestamp.isoformat() for event in outside[:5]],
                            "expected_active_hours": sorted(int(hour) for hour in active_hours),
                        },
                    )
                )

        expected_events = seed_config.get("expected_events") or []
        for expected_event in expected_events:
            if any(within_expected_event(event.timestamp, expected_event) for event in stat.events):
                continue
            findings.append(
                Finding(
                    kind="timing_anomaly",
                    severity=enforce_policy_severity(
                        "low",
                        policy,
                        mac=mac,
                        device_name=device_name,
                        finding_kind="timing_anomaly",
                    ),
                    mac=mac,
                    event_count=0,
                    message=(
                        f"Expected event for {mac} near "
                        f"{expected_event.get('hour', 0):02d}:{expected_event.get('minute', 0):02d} "
                        f"was not observed on {observed_date}."
                    ),
                    metadata={
                        "day": observed_date,
                        "expected_event": expected_event,
                    },
                )
            )
    return findings


def detect_new_event_types(
    aggregate: Dict[str, Any],
    store: StateStore,
    epoch_id: int,
    policy: Dict[str, Any],
) -> List[Finding]:
    findings: List[Finding] = []
    rolling_days = int(policy["learning"]["rolling_days_sparse"])
    for (observed_date, mac, event_key), stat in sorted(aggregate["event_day_stats"].items()):
        if event_key == "DHCP_IP":
            continue
        device_name = normalized_device_name(aggregate.get("mac_to_name", {}).get(mac), mac)
        event_rows = store.fetch_event_history(
            epoch_id,
            mac,
            event_key,
            observed_date,
            rolling_days,
        )
        if event_rows:
            continue
        device_rows = store.fetch_device_history(
            epoch_id,
            mac,
            observed_date,
            rolling_days,
        )
        if not device_rows:
            continue
        severity = enforce_policy_severity(
            "medium",
            policy,
            event_key=event_key,
            event_family=stat.event_family,
            mac=mac,
            device_name=device_name,
            finding_kind="new_event_type",
        )
        severity = cap_configured_allowed_wlan_access_severity(
            severity,
            aggregate,
            mac,
            event_key,
            stat.events,
            policy,
        )
        findings.append(
            Finding(
                kind="new_event_type",
                severity=severity,
                mac=mac,
                event_count=stat.count,
                message=f"First observed {event_key} event for {mac} on {observed_date}.",
                metadata={
                    "day": observed_date,
                    "event_key": event_key,
                    "event_family": stat.event_family,
                    "history_count": len(device_rows),
                    "observed_timestamps": [event.timestamp.isoformat() for event in stat.events[:5]],
                },
            )
        )
    return findings


def detect_rare_event_activity(
    aggregate: Dict[str, Any],
    store: StateStore,
    epoch_id: int,
    policy: Dict[str, Any],
) -> List[Finding]:
    findings: List[Finding] = []
    rare_policy = policy.get("rare_events", {})
    min_device_history_days = int(rare_policy.get("min_device_history_days", 3))
    max_presence_rate = float(rare_policy.get("max_presence_rate", 0.2))
    default_severity = str(rare_policy.get("default_severity", "low"))
    other_family_severity = str(rare_policy.get("other_family_severity", "medium"))
    for (observed_date, mac, event_key), stat in sorted(aggregate["event_day_stats"].items()):
        if event_key == "DHCP_IP":
            continue
        device_name = normalized_device_name(aggregate.get("mac_to_name", {}).get(mac), mac)
        profile = build_event_profile(store, epoch_id, mac, event_key, observed_date, policy)
        if profile is None:
            continue
        if profile["observed_device_days"] < min_device_history_days:
            continue
        if profile["presence_rate"] > max_presence_rate:
            continue
        base_severity = other_family_severity if stat.event_family == "OTHER" else default_severity
        severity = enforce_policy_severity(
            base_severity,
            policy,
            event_key=event_key,
            event_family=stat.event_family,
            mac=mac,
            device_name=device_name,
            finding_kind="rare_event_activity",
        )
        findings.append(
            Finding(
                kind="rare_event_activity",
                severity=severity,
                mac=mac,
                event_count=stat.count,
                message=f"Rare {event_key} activity observed for {mac} on {observed_date}.",
                metadata={
                    "day": observed_date,
                    "event_key": event_key,
                    "event_family": stat.event_family,
                    "history_count": profile["history_count"],
                    "observed_device_days": profile["observed_device_days"],
                    "learned_presence_rate": round(profile["presence_rate"], 2),
                    "observed_timestamps": [event.timestamp.isoformat() for event in stat.events[:5]],
                },
            )
        )
    return findings


def detect_event_behavior_anomalies(
    aggregate: Dict[str, Any],
    store: StateStore,
    epoch_id: int,
    policy: Dict[str, Any],
) -> List[Finding]:
    findings: List[Finding] = []
    low_shift = float(policy["timing"]["low_shift_hours"])
    min_weekday_history = int(policy["learning"].get("min_weekday_history", 4))
    for (observed_date, mac, event_key), stat in sorted(aggregate["event_day_stats"].items()):
        if event_key == "DHCP_IP":
            continue
        device_name = normalized_device_name(aggregate.get("mac_to_name", {}).get(mac), mac)
        profile = build_event_profile(store, epoch_id, mac, event_key, observed_date, policy)
        if profile is None:
            continue

        reasons: List[str] = []
        severity = "normal"

        count_profile = profile.get("count_profile")
        if count_profile is not None:
            tolerance = apply_tolerance(
                stat.count,
                minimum=max(0.0, count_profile["range_min"]),
                maximum=count_profile["range_max"],
                missing_bias=True,
            )
            count_severity = classify_severity(tolerance)
            if count_severity != "normal":
                severity = max_severity(severity, count_severity)
                reasons.append(
                    f"count {stat.count} vs learned {round(count_profile['mean'], 2)} +/- {round(2 * count_profile['stddev'], 2)}"
                )

        dominant_weekdays = profile.get("dominant_weekdays") or []
        current_weekday = date.fromisoformat(observed_date).weekday()
        if (
            dominant_weekdays
            and profile["history_count"] >= min_weekday_history
            and current_weekday not in dominant_weekdays
        ):
            severity = max_severity(severity, "medium")
            reasons.append("weekday drift")

        typical_hour = profile.get("typical_hour")
        current_hour = event_day_hour_mean(stat)
        if typical_hour is not None and current_hour is not None:
            distance = circular_hour_distance(current_hour, typical_hour)
            if distance > 0:
                hour_severity = "low" if distance <= low_shift else "medium"
                severity = max_severity(severity, hour_severity)
                reasons.append(f"time shift {format_duration_hours(distance)}")

        historical_dates = set(profile.get("historical_dates") or [])
        historical_dates.add(observed_date)
        current_streak = streak_length(historical_dates, observed_date)
        if profile["presence_rate"] < 0.3 and current_streak >= 2:
            streak_severity = "medium" if current_streak == 2 else "high"
            severity = max_severity(severity, streak_severity)
            reasons.append(f"{current_streak}-day streak for sparse event")

        severity = enforce_policy_severity(
            severity,
            policy,
            event_key=event_key,
            event_family=stat.event_family,
            mac=mac,
            device_name=device_name,
            finding_kind="event_behavior_anomaly",
        )
        severity = cap_configured_allowed_wlan_access_severity(
            severity,
            aggregate,
            mac,
            event_key,
            stat.events,
            policy,
        )
        if severity == "normal" or not reasons:
            continue
        findings.append(
            Finding(
                kind="event_behavior_anomaly",
                severity=severity,
                mac=mac,
                event_count=stat.count,
                message=f"{event_key} behavior changed for {mac} on {observed_date}.",
                metadata={
                    "day": observed_date,
                    "event_key": event_key,
                    "event_family": stat.event_family,
                    "reasons": reasons,
                    "history_count": profile["history_count"],
                    "dominant_weekdays": dominant_weekdays,
                    "current_weekday": current_weekday,
                    "learned_presence_rate": round(profile["presence_rate"], 2),
                    "learned_mean": round(count_profile["mean"], 2) if count_profile else None,
                    "typical_hour": round(typical_hour, 2) if typical_hour is not None else None,
                    "current_hour": round(current_hour, 2) if current_hour is not None else None,
                    "current_streak": current_streak,
                    "observed_timestamps": [event.timestamp.isoformat() for event in stat.events[:5]],
                },
            )
        )
    return findings


def group_cluster_events(
    events: List[Event],
    window_seconds: int,
    grace_seconds: int = 0,
) -> List[List[Event]]:
    if not events:
        return []
    sorted_events = sorted(events, key=lambda event: event.timestamp)
    groups: List[List[Event]] = [[sorted_events[0]]]
    max_gap_seconds = max(window_seconds, 0) + max(grace_seconds, 0)
    for event in sorted_events[1:]:
        group = groups[-1]
        # Use rolling gaps instead of anchoring to the first event so clusters
        # with small stepwise jitter are not split into separate findings.
        if (event.timestamp - group[-1].timestamp).total_seconds() <= max_gap_seconds:
            group.append(event)
        else:
            groups.append([event])
    return groups


def build_subject_behavior_day_stats(
    aggregate: Dict[str, Any],
    policy: Dict[str, Any],
) -> Tuple[Dict[Tuple[str, str, str, str], SubjectBehaviorDayAggregate], Dict[Tuple[str, str], Dict[str, Any]]]:
    subject_stats: Dict[Tuple[str, str, str, str], SubjectBehaviorDayAggregate] = {}
    subject_catalog: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for (observed_date, mac, event_key), stat in sorted(aggregate["event_day_stats"].items()):
        subject_type = "system" if mac == SYSTEM_ACTOR else "device"
        subject_key = mac
        subject_catalog[(subject_key, subject_type)] = {
            "display_name": aggregate["mac_to_name"].get(mac, mac),
            "attributes": {"source": subject_type},
        }
        subject_stats[(observed_date, subject_key, subject_type, event_key)] = SubjectBehaviorDayAggregate(
            observed_date=observed_date,
            subject_key=subject_key,
            subject_type=subject_type,
            behavior_key=event_key,
            behavior_family=stat.event_family,
        )
        for event in stat.events:
            subject_stats[(observed_date, subject_key, subject_type, event_key)].add_occurrence(
                start=event.timestamp,
                end=event.timestamp,
                size=1,
                context={
                    "members": [
                        {
                            "mac": event.mac,
                            "name": aggregate["mac_to_name"].get(event.mac, event.mac),
                            "timestamp": event.timestamp.isoformat(),
                        }
                    ]
                },
            )

    grace_seconds = int(policy["cluster"].get("group_gap_grace_seconds", 0) or 0)
    for cluster_name, profile in sorted(aggregate["cluster_profiles"].items()):
        events = aggregate["cluster_events"].get(cluster_name, [])
        if not events:
            continue
        subject_key = cluster_name
        subject_type = "group"
        subject_catalog[(subject_key, subject_type)] = {
            "display_name": cluster_name,
            "attributes": {
                "mac_prefixes": profile.get("mac_prefixes") or [],
                "cluster_size": profile.get("cluster_size"),
            },
        }
        by_day: DefaultDict[str, List[Event]] = defaultdict(list)
        for event in events:
            by_day[event.timestamp.date().isoformat()].append(event)
        for observed_date, day_events in sorted(by_day.items()):
            stat = SubjectBehaviorDayAggregate(
                observed_date=observed_date,
                subject_key=subject_key,
                subject_type=subject_type,
                behavior_key="DHCP_IP",
                behavior_family="DHCP",
            )
            groups = group_cluster_events(
                day_events,
                int(profile.get("cluster_time_window_seconds", 90) or 90),
                grace_seconds,
            )
            for sequence, group in enumerate(groups):
                unique_macs = sorted({event.mac for event in group if is_real_mac(event.mac)})
                member_events = [
                    {
                        "mac": event.mac,
                        "name": aggregate["mac_to_name"].get(event.mac, event.mac),
                        "timestamp": event.timestamp.isoformat(),
                    }
                    for event in group
                ]
                stat.add_occurrence(
                    start=group[0].timestamp,
                    end=group[-1].timestamp,
                    size=len(unique_macs),
                    context={
                        "sequence": sequence,
                        "member_macs": unique_macs,
                        "member_events": member_events,
                        "span_seconds": int((group[-1].timestamp - group[0].timestamp).total_seconds()),
                    },
                )
            subject_stats[(observed_date, subject_key, subject_type, "DHCP_IP")] = stat

    return subject_stats, subject_catalog


def hour_from_timestamp(value: datetime) -> float:
    return value.hour + (value.minute / 60.0) + (value.second / 3600.0)


def hour_from_iso(value: str) -> float:
    return hour_from_timestamp(datetime.fromisoformat(value))


def circular_mean(hours: Sequence[float]) -> Optional[float]:
    if not hours:
        return None
    radians = [2 * math.pi * (hour / 24.0) for hour in hours]
    x = sum(math.cos(angle) for angle in radians) / len(radians)
    y = sum(math.sin(angle) for angle in radians) / len(radians)
    angle = math.atan2(y, x)
    if angle < 0:
        angle += 2 * math.pi
    return (angle / (2 * math.pi)) * 24.0


def circular_stddev(hours: Sequence[float], mean_hour: Optional[float]) -> Optional[float]:
    if mean_hour is None or len(hours) < 2:
        return None
    variance = sum(circular_hour_distance(hour, mean_hour) ** 2 for hour in hours) / len(hours)
    return math.sqrt(max(variance, 0.0))


def assign_occurrence_slot(
    occurrence_index: int,
    occurrence_hour: float,
    expected_windows: Sequence[Dict[str, Any]],
) -> str:
    if expected_windows:
        distances = []
        for index, window in enumerate(expected_windows):
            center = (float(window.get("start_hour", 0)) + float(window.get("end_hour", 24))) / 2.0
            distances.append((circular_hour_distance(occurrence_hour, center), index))
        distances.sort()
        return f"window:{distances[0][1]}"
    return f"ordinal:{occurrence_index}"


def build_subject_behavior_profile(
    store: StateStore,
    epoch_id: int,
    subject_key: str,
    subject_type: str,
    behavior_key: str,
    observed_date: str,
    policy: Dict[str, Any],
    expected_windows: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    rows = store.fetch_subject_behavior_history(
        epoch_id,
        subject_key,
        subject_type,
        behavior_key,
        observed_date,
        int(policy["learning"]["rolling_days_sparse"]),
    )
    if not rows:
        return None

    count_values = [float(row["count"]) for row in rows]
    count_profile = compute_numeric_profile(
        values=count_values,
        seed_range=None,
        seed_weight=0.0,
        stddev_floor=float(policy["learning"]["stddev_floor"]),
    )
    weekday_counts: Counter = Counter()
    slot_hours: DefaultDict[str, List[float]] = defaultdict(list)
    slot_sizes: DefaultDict[str, List[float]] = defaultdict(list)

    for row in rows:
        row_date = date.fromisoformat(row["observed_date"])
        weekday_counts[row_date.weekday()] += 1
        starts = json.loads(row["occurrence_starts_json"] or "[]")
        sizes = json.loads(row["occurrence_sizes_json"] or "[]")
        for index, start_iso in enumerate(starts):
            occurrence_hour = hour_from_iso(start_iso)
            slot_key = assign_occurrence_slot(index, occurrence_hour, expected_windows or [])
            slot_hours[slot_key].append(occurrence_hour)
            if index < len(sizes):
                slot_sizes[slot_key].append(float(sizes[index]))

    dominant_weekdays: List[int] = []
    if weekday_counts:
        highest = max(weekday_counts.values())
        if highest / max(len(rows), 1) >= 0.6:
            dominant_weekdays = sorted(
                weekday for weekday, count in weekday_counts.items() if count == highest
            )

    slot_profiles: Dict[str, Dict[str, Any]] = {}
    for slot_key, hours in slot_hours.items():
        mean_hour = circular_mean(hours)
        stddev_hours = circular_stddev(hours, mean_hour)
        size_values = slot_sizes.get(slot_key) or []
        mean_size = (sum(size_values) / len(size_values)) if size_values else None
        slot_profiles[slot_key] = {
            "history_count": len(hours),
            "mean_hour": mean_hour,
            "stddev_hours": stddev_hours,
            "mean_size": mean_size,
        }

    return {
        "history_count": len(rows),
        "count_profile": count_profile,
        "dominant_weekdays": dominant_weekdays,
        "slot_profiles": slot_profiles,
    }


def detect_cluster_anomalies(
    aggregate: Dict[str, Any],
    store: StateStore,
    epoch_id: int,
    policy: Dict[str, Any],
) -> List[Finding]:
    findings: List[Finding] = []
    low_shift = float(policy["timing"]["low_shift_hours"])
    partial_fraction = float(policy["cluster"]["partial_visibility_min_fraction"])
    learned_slot_min_occurrences = int(policy["cluster"].get("learned_slot_min_occurrences", 2) or 2)
    learned_time_floor_hours = float(policy["cluster"].get("learned_time_floor_minutes", 15) or 15) / 60.0
    for (observed_date, subject_key, subject_type, behavior_key), stat in sorted(aggregate["subject_behavior_day_stats"].items()):
        if subject_type != "group" or behavior_key != "DHCP_IP":
            continue
        cluster_name = subject_key
        profile = aggregate["cluster_profiles"].get(cluster_name)
        if not profile:
            continue
        expected_windows = profile.get("expected_windows") or []
        learned_profile = build_subject_behavior_profile(
            store,
            epoch_id,
            cluster_name,
            "group",
            "DHCP_IP",
            observed_date,
            policy,
            expected_windows=expected_windows,
        )
        expected_size = int(profile.get("cluster_size") or 0)
        min_cluster_size = int(
            profile.get("min_cluster_size")
            or max(1, math.ceil(expected_size * partial_fraction))
        )
        for index, start_iso in enumerate(stat.occurrence_starts):
            start = datetime.fromisoformat(start_iso)
            end = datetime.fromisoformat(stat.occurrence_ends[index])
            size = stat.occurrence_sizes[index] if index < len(stat.occurrence_sizes) else 0
            context = stat.contexts[index] if index < len(stat.contexts) else {}
            member_macs = context.get("member_macs") or []
            member_events = context.get("member_events") or []
            slot_key = assign_occurrence_slot(index, hour_from_timestamp(start), expected_windows)

            abnormal_time = expected_windows and not is_in_windows(start, expected_windows)
            if expected_size and size < expected_size:
                if size >= min_cluster_size or size >= 1:
                    severity = policy["cluster"]["partial_visibility_severity"]
                else:
                    severity = policy["cluster"]["missing_cluster_severity"]
                if abnormal_time and severity == policy["cluster"]["missing_cluster_severity"]:
                    severity = policy["cluster"]["abnormal_time_escalation"]
                severity = enforce_policy_severity(
                    severity,
                    policy,
                    event_key="DHCP_IP",
                    event_family="DHCP",
                    finding_kind="cluster_anomaly",
                    cluster_name=cluster_name,
                )
                if severity == "normal":
                    continue
                findings.append(
                    Finding(
                        kind="cluster_anomaly",
                        severity=severity,
                        mac=None,
                        event_count=size,
                        message=(
                            f"Cluster {cluster_name} observed {size} device(s) "
                            f"between {start.isoformat()} and {end.isoformat()}."
                        ),
                        metadata={
                            "cluster": cluster_name,
                            "day": observed_date,
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                            "macs": member_macs,
                            "member_events": member_events,
                            "expected_size": expected_size,
                            "min_cluster_size": min_cluster_size,
                            "abnormal_time": bool(abnormal_time),
                            "occurrence_index": index,
                        },
                    )
                )

            slot_profile = (learned_profile or {}).get("slot_profiles", {}).get(slot_key)
            if slot_profile and slot_profile.get("history_count", 0) >= learned_slot_min_occurrences:
                distance = circular_hour_distance(hour_from_timestamp(start), float(slot_profile["mean_hour"]))
                learned_band = max(
                    learned_time_floor_hours,
                    2 * float(slot_profile["stddev_hours"] or 0.0),
                )
                if distance > learned_band:
                    severity = "low" if distance <= learned_band + learned_time_floor_hours else "medium"
                    severity = enforce_policy_severity(
                        severity,
                        policy,
                        event_key="DHCP_IP",
                        event_family="DHCP",
                        finding_kind="cluster_anomaly",
                        cluster_name=cluster_name,
                    )
                    if severity == "normal":
                        continue
                    findings.append(
                        Finding(
                            kind="cluster_anomaly",
                            severity=severity,
                            mac=None,
                            event_count=size,
                            message=f"Cluster {cluster_name} shifted from its learned start time at {start.isoformat()}.",
                            metadata={
                                "cluster": cluster_name,
                                "day": observed_date,
                                "start": start.isoformat(),
                                "end": end.isoformat(),
                                "distance_hours": distance,
                                "distance_minutes": int(round(distance * 60)),
                                "learned_band_minutes": int(round(learned_band * 60)),
                                "learned_reference_hour": round(float(slot_profile["mean_hour"]), 2),
                                "macs": member_macs,
                                "member_events": member_events,
                                "occurrence_index": index,
                                "timing_basis": "learned",
                            },
                        )
                    )
            elif expected_windows and abnormal_time:
                distance = distance_to_windows_hours(start, expected_windows)
                severity = "low" if distance <= low_shift else "medium"
                severity = enforce_policy_severity(
                    severity,
                    policy,
                    event_key="DHCP_IP",
                    event_family="DHCP",
                    finding_kind="cluster_anomaly",
                    cluster_name=cluster_name,
                )
                if severity == "normal":
                    continue
                findings.append(
                    Finding(
                        kind="cluster_anomaly",
                        severity=severity,
                        mac=None,
                        event_count=size,
                        message=f"Cluster {cluster_name} activated outside expected windows at {start.isoformat()}.",
                        metadata={
                            "cluster": cluster_name,
                            "day": observed_date,
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                            "distance_hours": distance,
                            "distance_minutes": int(round(distance * 60)),
                            "macs": member_macs,
                            "member_events": member_events,
                            "expected_windows": expected_windows,
                            "occurrence_index": index,
                            "timing_basis": "seed_window",
                        },
                    )
                )
    return findings


def build_exclusion_maps(
    aggregate: Dict[str, Any],
    findings: Dict[str, List[Finding]],
    devices_snapshot: Dict[str, Dict[str, Any]],
    is_partial: bool,
) -> Tuple[
    Set[Tuple[str, str]],
    Dict[Tuple[str, str], str],
    Set[Tuple[str, str, str]],
    Dict[Tuple[str, str, str], str],
    Set[Tuple[str, str, str, str]],
    Dict[Tuple[str, str, str, str], str],
]:
    device_day_exclusions: Set[Tuple[str, str]] = set()
    device_day_reasons: Dict[Tuple[str, str], str] = {}
    event_day_exclusions: Set[Tuple[str, str, str]] = set()
    event_day_reasons: Dict[Tuple[str, str, str], str] = {}
    subject_day_exclusions: Set[Tuple[str, str, str, str]] = set()
    subject_day_reasons: Dict[Tuple[str, str, str, str], str] = {}

    if is_partial:
        for key in aggregate["device_day_stats"]:
            device_day_exclusions.add(key)
            device_day_reasons[key] = "partial_run"
        for key in aggregate["event_day_stats"]:
            event_day_exclusions.add(key)
            event_day_reasons[key] = "partial_run"
        for key in aggregate.get("subject_behavior_day_stats", {}):
            subject_day_exclusions.add(key)
            subject_day_reasons[key] = "partial_run"

    incident_event_keys = {
        (event.timestamp.date().isoformat(), event.mac, event.event_key)
        for event in aggregate.get("events", [])
        if event.incident_id is not None
    }
    for observed_date, mac, _event_key in incident_event_keys:
        device_key = (observed_date, mac)
        device_day_exclusions.add(device_key)
        device_day_reasons[device_key] = "network_reset"
    for event_key in incident_event_keys:
        event_day_exclusions.add(event_key)
        event_day_reasons[event_key] = "network_reset"
    for key, stat in aggregate.get("subject_behavior_day_stats", {}).items():
        observed_date, subject_key, subject_type, behavior_key = key
        explained = (observed_date, subject_key, behavior_key) in incident_event_keys
        if subject_type == "group" and not explained:
            explained = any(
                (
                    observed_date,
                    str(member.get("mac") or ""),
                    behavior_key,
                )
                in incident_event_keys
                for context in stat.contexts
                for member in context.get("member_events", [])
            )
        if explained:
            subject_day_exclusions.add(key)
            subject_day_reasons[key] = "network_reset"

    for (observed_date, mac), stat in aggregate["device_day_stats"].items():
        if mac != SYSTEM_ACTOR and (devices_snapshot.get(mac, {}).get("status") or "").lower() == "blocked":
            device_day_exclusions.add((observed_date, mac))
            device_day_reasons[(observed_date, mac)] = "blocked_device"

    for finding in findings["all"]:
        if finding.severity not in {"high", "critical"}:
            continue
        day = finding.metadata.get("day")
        event_key = finding.metadata.get("event_key")
        if finding.mac and day:
            device_day_exclusions.add((day, finding.mac))
            device_day_reasons[(day, finding.mac)] = finding.kind
            if event_key:
                event_key_tuple = (day, finding.mac, event_key)
                event_day_exclusions.add(event_key_tuple)
                event_day_reasons[event_key_tuple] = finding.kind
        cluster_name = finding.metadata.get("cluster")
        if cluster_name and day:
            subject_key = (day, cluster_name, "group", "DHCP_IP")
            subject_day_exclusions.add(subject_key)
            subject_day_reasons[subject_key] = finding.kind

    return (
        device_day_exclusions,
        device_day_reasons,
        event_day_exclusions,
        event_day_reasons,
        subject_day_exclusions,
        subject_day_reasons,
    )


def detect_partial_run(events: List[Event], policy: Dict[str, Any]) -> bool:
    if not events:
        return False
    span = events[-1].timestamp - events[0].timestamp
    return span < timedelta(hours=float(policy["partial_detection"]["minimum_full_span_hours"]))


def detect_anomalies(
    aggregate: Dict[str, Any],
    seed_baseline: Dict[str, Any],
    devices_snapshot: Dict[str, Dict[str, Any]],
    store: StateStore,
    epoch_id: int,
    policy: Dict[str, Any],
    incidents: Optional[Sequence[NetworkIncident]] = None,
) -> Dict[str, List[Finding]]:
    findings = {
        "critical": [],
        "observations": [],
        "anomalies": [],
        "all": [],
    }
    all_findings = (
        network_incident_findings(incidents or [], policy)
        + detect_unknown_devices(aggregate, seed_baseline, devices_snapshot, policy)
        + detect_blocked_devices(aggregate, devices_snapshot, policy)
        + detect_device_metric_anomalies(aggregate, seed_baseline, store, epoch_id, policy)
        + detect_timing_anomalies(aggregate, seed_baseline, policy)
        + detect_new_event_types(aggregate, store, epoch_id, policy)
        + detect_rare_event_activity(aggregate, store, epoch_id, policy)
        + detect_event_behavior_anomalies(aggregate, store, epoch_id, policy)
        + detect_cluster_anomalies(aggregate, store, epoch_id, policy)
    )
    findings["all"].extend(all_findings)
    for finding in all_findings:
        if finding.severity == "critical":
            findings["critical"].append(finding)
        elif finding.severity == "low":
            findings["observations"].append(finding)
        else:
            findings["anomalies"].append(finding)
    return findings


def finding_day(metadata: Dict[str, Any]) -> str:
    day = metadata.get("day")
    if isinstance(day, str) and day:
        return day
    start = metadata.get("start")
    if isinstance(start, str) and len(start) >= 10:
        return start[:10]
    return ""


def finding_security_priority(kind: str, metadata: Dict[str, Any]) -> int:
    event_key = metadata.get("event_key")
    event_family = metadata.get("event_family")
    if kind in {"unknown_device", "blocked_device_activity"}:
        return 2
    if event_key == "WLAN_ACCESS_REJECTED" or event_family == "WLAN_REJECTED":
        return 2
    if kind == "new_event_type":
        return 1
    return 0


def finding_kind_rank(kind: str) -> int:
    return FINDING_KIND_ORDER.get(kind, len(FINDING_KIND_ORDER))


def finding_sort_key(finding: Finding) -> Tuple[int, int, int, str, str, str]:
    metadata = finding.metadata or {}
    return (
        -finding_security_priority(finding.kind, metadata),
        -severity_rank(finding.severity),
        finding_kind_rank(finding.kind),
        finding_day(metadata),
        finding.mac or "",
        str(metadata.get("event_key") or metadata.get("cluster") or finding.kind),
    )


def finding_entry_sort_key(entry: Dict[str, Any]) -> Tuple[int, int, int, str, str, str]:
    metadata = entry.get("metadata", {})
    return (
        -finding_security_priority(entry["kind"], metadata),
        -severity_rank(entry["severity"]),
        finding_kind_rank(entry["kind"]),
        finding_day(metadata),
        str(entry.get("mac") or ""),
        str(metadata.get("event_key") or metadata.get("cluster") or entry["kind"]),
    )


def finding_score_group_key(finding: Finding) -> Tuple[str, str, str, str]:
    metadata = finding.metadata or {}
    day = finding_day(metadata)
    if finding.kind == "network_reset":
        return ("network_incident", str(metadata.get("incident_id") or ""), day, "")
    if finding.kind == "cluster_anomaly":
        return (
            "cluster",
            str(metadata.get("cluster") or ""),
            day,
            "",
        )
    event_key = metadata.get("event_key")
    if finding.mac and event_key:
        return ("device_event", finding.mac, day, str(event_key))
    if finding.mac:
        return ("device_metric", finding.mac, day, finding.kind)
    return (
        "finding",
        finding.kind,
        day,
        str(metadata.get("cluster") or event_key or finding.message),
    )


def compute_risk_score(findings: Dict[str, List[Finding]], policy: Dict[str, Any]) -> Tuple[int, str, Dict[str, int]]:
    score = 0
    breakdown: Dict[str, int] = {}
    seen_keys: Set[Tuple[str, Optional[str], str, str]] = set()
    severities_seen: Set[str] = set()
    scoring = policy["scoring"]
    secondary_weight = float(policy["noise_suppression"].get("correlated_secondary_weight", 0.25))
    grouped_findings: DefaultDict[Tuple[str, str, str, str], List[Finding]] = defaultdict(list)
    for finding in findings["all"]:
        unique_key = (
            finding.kind,
            finding.mac,
            finding.metadata.get("day") or finding.metadata.get("start") or finding.metadata.get("cluster") or "",
            finding.metadata.get("event_key") or finding.message,
        )
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        severities_seen.add(finding.severity)
        grouped_findings[finding_score_group_key(finding)].append(finding)

    for group_findings in grouped_findings.values():
        ordered_findings = sorted(
            group_findings,
            key=lambda finding: (
                -severity_rank(finding.severity),
                -finding_security_priority(finding.kind, finding.metadata or {}),
                finding_kind_rank(finding.kind),
            ),
        )
        for index, finding in enumerate(ordered_findings):
            weight = int(scoring.get(finding.severity, 0))
            contribution = weight if index == 0 else int(round(weight * secondary_weight))
            if contribution <= 0:
                continue
            score += contribution
            breakdown[finding.kind] = breakdown.get(finding.kind, 0) + contribution

    capped_score = min(score, 100)
    if findings["all"] and severities_seen == {"low"}:
        capped_score = min(capped_score, int(policy["noise_suppression"]["low_only_cap"]))
        return capped_score, "Clean", breakdown

    if capped_score >= int(policy["status_thresholds"]["suspicious"]):
        return capped_score, "Suspicious", breakdown
    if capped_score >= int(policy["status_thresholds"]["watch"]):
        return capped_score, "Watch", breakdown
    return capped_score, "Clean", breakdown


def summarize_devices(aggregate: Dict[str, Any]) -> List[Dict[str, Any]]:
    summary: List[Dict[str, Any]] = []
    for mac in sorted(aggregate["events_by_mac"]):
        device_events = aggregate["events_by_mac"][mac]
        summary.append(
            {
                "mac": mac,
                "name": aggregate["mac_to_name"].get(mac, mac),
                "dhcp_count": len([event for event in device_events if event.event_family == "DHCP"]),
                "total_events": len(device_events),
                "incident_explained_events": len(
                    [event for event in device_events if event.incident_id is not None]
                ),
                "event_types": sorted({event.event_key for event in device_events}),
            }
        )
    return sorted(summary, key=lambda item: (item["name"].lower(), item["mac"]))


def describe_device(mac: Optional[str], aggregate: Dict[str, Any]) -> str:
    if not mac:
        return "Unknown device"
    return f"{aggregate['mac_to_name'].get(mac, mac)} ({mac})"


def humanize_event_key(event_key: str) -> str:
    acronyms = {"DHCP", "WLAN", "IP", "MAC", "NAS", "SSID"}
    parts = []
    for token in event_key.split("_"):
        upper = token.upper()
        parts.append(upper if upper in acronyms else token.capitalize())
    return " ".join(parts)


def describe_cluster_macs(macs: Sequence[str], aggregate: Dict[str, Any]) -> str:
    return ", ".join(describe_device(mac, aggregate) for mac in macs) if macs else "none"


def format_clock_from_iso(timestamp_iso: str, include_seconds: bool = True) -> str:
    value = datetime.fromisoformat(timestamp_iso)
    fmt = "%I:%M:%S %p" if include_seconds else "%I:%M %p"
    return value.strftime(fmt).lstrip("0")


def format_hour_value(hour_value: float) -> str:
    total_minutes = int(round(hour_value * 60)) % (24 * 60)
    return format_clock_minutes(total_minutes)


def format_clock_minutes(total_minutes: int) -> str:
    normalized_minutes = total_minutes % (24 * 60)
    hour = normalized_minutes // 60
    minute = normalized_minutes % 60
    return datetime(2000, 1, 1, hour, minute).strftime("%I:%M %p").lstrip("0")


def format_active_hours(active_hours: Sequence[int]) -> str:
    hours = sorted({int(hour) % 24 for hour in active_hours})
    if not hours:
        return "none"
    ranges: List[Tuple[int, int]] = []
    start = hours[0]
    end = hours[0]
    for hour in hours[1:]:
        if hour == end + 1:
            end = hour
            continue
        ranges.append((start, end))
        start = hour
        end = hour
    ranges.append((start, end))
    return ", ".join(
        f"{format_clock_minutes(start * 60)}-{format_clock_minutes(((end + 1) * 60) - 1)}"
        for start, end in ranges
    )


def format_timestamp_samples(samples: Sequence[str]) -> str:
    return ", ".join(format_clock_from_iso(sample) for sample in samples) if samples else "n/a"


def weekday_name(index: int) -> str:
    return WEEKDAY_NAMES[index % len(WEEKDAY_NAMES)]


def format_window(window: Dict[str, Any]) -> str:
    return (
        f"{format_hour_value(float(window.get('start_hour', 0)))}-"
        f"{format_hour_value(float(window.get('end_hour', 24)))}"
    )


def format_duration_minutes(minutes: int) -> str:
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def format_duration_hours(hours: float) -> str:
    total_seconds = max(0, int(round(float(hours) * 3600)))
    if total_seconds < 60:
        return f"{total_seconds} second{'s' if total_seconds != 1 else ''}"

    total_minutes = max(1, int(round(total_seconds / 60)))
    if total_minutes < 60:
        return format_duration_minutes(total_minutes)

    whole_hours, remaining_minutes = divmod(total_minutes, 60)
    hour_text = f"{whole_hours} hour{'s' if whole_hours != 1 else ''}"
    if remaining_minutes == 0:
        return hour_text
    return f"{hour_text} {format_duration_minutes(remaining_minutes)}"


def render_member_events(member_events: Sequence[Dict[str, Any]], aggregate: Dict[str, Any]) -> str:
    if not member_events:
        return "no member timestamps captured"
    rendered = []
    for item in member_events:
        mac = item.get("mac")
        label = describe_device(mac, aggregate) if mac else item.get("name", "Unknown device")
        timestamp = item.get("timestamp")
        rendered.append(f"{label} at {format_clock_from_iso(timestamp)}" if timestamp else label)
    return "; ".join(rendered)


def render_finding_message(finding: Finding, aggregate: Dict[str, Any]) -> str:
    if finding.kind == "unknown_device" and finding.mac:
        return f"Unknown device {describe_device(finding.mac, aggregate)} generated {finding.event_count} event(s)."
    if finding.kind == "blocked_device_activity" and finding.mac:
        return f"Blocked device {describe_device(finding.mac, aggregate)} generated {finding.event_count} event(s)."
    if finding.kind == "network_reset":
        confidence = str(finding.metadata.get("confidence") or "probable").title()
        affected_count = len(finding.metadata.get("affected_macs") or [])
        return (
            f"{confidence} internet connection reset from {finding.metadata.get('start')} through "
            f"{finding.metadata.get('restored_at')} affected {affected_count} known device(s) and "
            f"explained {finding.event_count} recovery event(s)."
        )
    if finding.kind == "dhcp_anomaly" and finding.mac:
        expected = finding.metadata.get("expected_range") or ["?", "?"]
        return (
            f"DHCP activity for {describe_device(finding.mac, aggregate)} on {finding.metadata.get('day')} "
            f"was {finding.metadata.get('direction')} expected range at {finding.event_count} vs "
            f"{round(expected[0], 2)}-{round(expected[1], 2)}. "
            f"Learned mean {finding.metadata.get('learned_mean')}, trend {finding.metadata.get('trend')}."
        )
    if finding.kind == "event_volume_anomaly" and finding.mac:
        expected = finding.metadata.get("expected_range") or ["?", "?"]
        direction = finding.metadata.get("direction")
        qualifier = "slightly above" if finding.severity == "low" and direction == "above" else direction
        qualifier = "slightly below" if finding.severity == "low" and direction == "below" else qualifier
        return (
            f"Daily event count for {describe_device(finding.mac, aggregate)} on {finding.metadata.get('day')} "
            f"was {qualifier} expected range at {finding.event_count} vs "
            f"{round(expected[0], 2)}-{round(expected[1], 2)}. "
            f"Learned mean {finding.metadata.get('learned_mean')}, trend {finding.metadata.get('trend')}."
        )
    if finding.kind == "timing_anomaly" and finding.mac:
        if "expected_event" in finding.metadata:
            expected = finding.metadata["expected_event"]
            return (
                f"Expected event for {describe_device(finding.mac, aggregate)} near "
                f"{expected.get('hour', 0):02d}:{expected.get('minute', 0):02d} "
                f"was not observed on {finding.metadata.get('day')}."
            )
        if "distance_hours" in finding.metadata:
            return (
                f"Timing drift for {describe_device(finding.mac, aggregate)} on {finding.metadata.get('day')}: "
                f"{format_duration_hours(float(finding.metadata['distance_hours']))} outside the expected window."
            )
    if finding.kind == "new_event_type" and finding.mac:
        return (
            f"{humanize_event_key(finding.metadata.get('event_key', 'EVENT'))} was first observed for "
            f"{describe_device(finding.mac, aggregate)} on {finding.metadata.get('day')}."
        )
    if finding.kind == "rare_event_activity" and finding.mac:
        return (
            f"{humanize_event_key(finding.metadata.get('event_key', 'EVENT'))} remains rare for "
            f"{describe_device(finding.mac, aggregate)} and was observed on {finding.metadata.get('day')}."
        )
    if finding.kind == "event_behavior_anomaly" and finding.mac:
        reasons = ", ".join(finding.metadata.get("reasons") or [])
        return (
            f"{humanize_event_key(finding.metadata.get('event_key', 'EVENT'))} behavior for "
            f"{describe_device(finding.mac, aggregate)} on {finding.metadata.get('day')} changed: {reasons}."
        )
    if finding.kind == "cluster_anomaly":
        if "distance_hours" in finding.metadata and finding.metadata.get("cluster"):
            start = finding.metadata.get("start")
            expected_windows = finding.metadata.get("expected_windows") or []
            reference_text = "expected window"
            if expected_windows:
                start_hour = hour_from_iso(start)
                nearest = min(
                    expected_windows,
                    key=lambda window: min(
                        circular_hour_distance(start_hour, float(window.get("start_hour", 0))),
                        circular_hour_distance(start_hour, float(window.get("end_hour", 24))),
                    ),
                )
                reference_text = f"expected window ({format_window(nearest)})"
            basis = finding.metadata.get("timing_basis")
            if basis == "learned" and finding.metadata.get("learned_reference_hour") is not None:
                reference_text = (
                    f"learned start window around {format_hour_value(float(finding.metadata['learned_reference_hour']))}"
                )
            return (
                f"Cluster {finding.metadata.get('cluster')} activated at {format_clock_from_iso(start)} on "
                f"{finding.metadata.get('day')}, {format_duration_minutes(int(finding.metadata.get('distance_minutes', 0)))} "
                f"outside the {reference_text}. "
                f"Members: {render_member_events(finding.metadata.get('member_events') or [], aggregate)}."
            )
        macs = finding.metadata.get("macs") or []
        if macs:
            return (
                f"Cluster {finding.metadata.get('cluster')} observed {finding.event_count} device(s) between "
                f"{finding.metadata.get('start')} and {finding.metadata.get('end')}; expected "
                f"{finding.metadata.get('expected_size', 'n/a')}. Observed members: "
                f"{describe_cluster_macs(macs, aggregate)}. Timestamps: "
                f"{render_member_events(finding.metadata.get('member_events') or [], aggregate)}."
            )
    return finding.message


def findings_to_dict(findings: Dict[str, List[Finding]], aggregate: Dict[str, Any]) -> Dict[str, Any]:
    converted = {
        group: [
            {
                **asdict(finding),
                "device_label": describe_device(finding.mac, aggregate) if finding.mac else None,
                "rendered_message": render_finding_message(finding, aggregate),
            }
            for finding in items
        ]
        for group, items in findings.items()
    }
    for group, items in converted.items():
        converted[group] = sorted(items, key=finding_entry_sort_key)
    return converted


def build_priority_findings(findings: Dict[str, Any]) -> List[Dict[str, Any]]:
    seen: Set[Tuple[str, str, str, str]] = set()
    prioritized: List[Dict[str, Any]] = []
    for entry in sorted(findings.get("all", []), key=finding_entry_sort_key):
        metadata = entry.get("metadata", {})
        if entry["severity"] == "low" and finding_security_priority(entry["kind"], metadata) == 0:
            continue
        unique_key = (
            entry["kind"],
            str(entry.get("mac") or ""),
            finding_day(metadata),
            str(metadata.get("event_key") or metadata.get("cluster") or entry["rendered_message"]),
        )
        if unique_key in seen:
            continue
        seen.add(unique_key)
        prioritized.append(entry)
        if len(prioritized) >= PRIORITY_FINDING_LIMIT:
            break
    return prioritized


def build_report_data(
    args: argparse.Namespace,
    db_path: Path,
    parse_stats: ParseStats,
    aggregate: Dict[str, Any],
    findings: Dict[str, List[Finding]],
    score: int,
    status: str,
    breakdown: Dict[str, int],
    deduplicated: bool,
    epoch_id: Optional[int],
    policy_profile_id: Optional[int],
    incidents: Optional[Sequence[NetworkIncident]] = None,
    analyzed_event_count: Optional[int] = None,
    reprocessed_run_id: Optional[int] = None,
) -> Dict[str, Any]:
    findings_dict = findings_to_dict(findings, aggregate)
    incident_list = list(incidents or [])
    raw_event_count = len(aggregate.get("events", []))
    explained_event_count = sum(incident.explained_event_count for incident in incident_list)
    return {
        "inputs": {
            "logfile": str(Path(args.logfile).expanduser().resolve()) if args.logfile else None,
            "baseline": str(Path(args.baseline).expanduser().resolve()) if args.baseline else None,
            "config": str(Path(args.config).expanduser().resolve()) if args.config else None,
            "db": str(db_path.resolve()),
        },
        "state": {
            "epoch_id": epoch_id,
            "policy_profile_id": policy_profile_id,
            "deduplicated": deduplicated,
            "reprocessed_run_id": reprocessed_run_id,
        },
        "parse_stats": asdict(parse_stats),
        "analysis_adjustments": {
            "raw_event_count": raw_event_count,
            "incident_explained_event_count": explained_event_count,
            "analyzed_event_count": (
                analyzed_event_count
                if analyzed_event_count is not None
                else max(0, raw_event_count - explained_event_count)
            ),
        },
        "network_incidents": [asdict(incident) for incident in incident_list],
        "observation_range": aggregate["observation_range"],
        "events_per_hour": aggregate["events_per_hour"],
        "risk_score": score,
        "status": status,
        "risk_breakdown": breakdown,
        "findings": findings_dict,
        "priority_findings": build_priority_findings(findings_dict),
        "device_summary": summarize_devices(aggregate),
    }


def render_key_value_lines(items: Sequence[Tuple[str, Any]]) -> List[str]:
    label_width = max((len(label) for label, _ in items), default=0)
    return [f"{label:<{label_width}} : {value}" for label, value in items]


def run_persistence_text(report: Dict[str, Any]) -> str:
    reprocessed_run_id = report.get("state", {}).get("reprocessed_run_id")
    if reprocessed_run_id is not None:
        return f"Reprocessed (replaced run {reprocessed_run_id})"
    if report.get("state", {}).get("deduplicated"):
        return "Skipped (duplicate file hash)"
    return "Stored"


def make_panel(title: str, body_lines: Sequence[str], width: int) -> List[str]:
    inner_width = max(40, width - 4)
    top = f"+- {title[:max(0, inner_width - 3)]}".ljust(inner_width + 1, "-") + "+"
    lines = [top]
    if body_lines:
        for line in body_lines:
            wrapped = textwrap.wrap(line, width=inner_width) or [""]
            for wrapped_line in wrapped:
                lines.append(f"| {wrapped_line.ljust(inner_width)} |")
    else:
        lines.append(f"| {'None'.ljust(inner_width)} |")
    lines.append("+" + "-" * (inner_width + 2) + "+")
    return lines


def finding_detail_lines(entry: Dict[str, Any]) -> List[str]:
    metadata = entry.get("metadata", {})
    if entry["kind"] == "network_reset":
        event_counts = metadata.get("event_counts") or {}
        breakdown = ", ".join(
            f"{humanize_event_key(key)}: {value}" for key, value in sorted(event_counts.items())
        )
        return [
            entry["rendered_message"],
            f"Recovery window: {metadata.get('start')} to {metadata.get('recovery_end')}",
            f"Evidence: {breakdown or 'none'}",
        ]
    if entry["kind"] == "timing_anomaly":
        lines = [entry["rendered_message"]]
        if metadata.get("hours"):
            lines.append(f"Observed: {format_timestamp_samples(metadata['hours'])}")
        if metadata.get("expected_windows"):
            windows = ", ".join(format_window(window) for window in metadata["expected_windows"])
            lines.append(f"Expected window(s): {windows}")
        elif metadata.get("expected_active_hours"):
            lines.append(f"Expected active hours: {format_active_hours(metadata['expected_active_hours'])}")
        elif metadata.get("expected_event"):
            expected_event = metadata["expected_event"]
            target_hour = int(expected_event.get("hour", 0))
            target_minute = int(expected_event.get("minute", 0))
            target_minutes = target_hour * 60 + target_minute
            tolerance = int(expected_event.get("tolerance_minutes", 0))
            lines.append(
                f"Expected event time: {format_clock_minutes(target_minutes)} +/- {tolerance} minute(s)"
            )
        return lines
    if entry["kind"] == "event_behavior_anomaly":
        lines = [entry["rendered_message"]]
        reasons = metadata.get("reasons") or []
        if "weekday drift" in reasons and metadata.get("dominant_weekdays") is not None:
            observed_weekday = metadata.get("current_weekday")
            if observed_weekday is not None:
                lines.append(f"Observed weekday: {weekday_name(int(observed_weekday))}")
            dominant = metadata.get("dominant_weekdays") or []
            if dominant:
                lines.append(
                    "Learned weekday pattern: "
                    f"{', '.join(weekday_name(int(weekday)) for weekday in dominant)} "
                    f"from {metadata.get('history_count', 0)} prior day(s)"
                )
        if any(reason.startswith("time shift ") for reason in reasons):
            if metadata.get("observed_timestamps"):
                lines.append(f"Observed times: {format_timestamp_samples(metadata['observed_timestamps'])}")
            if metadata.get("typical_hour") is not None:
                lines.append(
                    "Learned typical time: "
                    f"around {format_hour_value(float(metadata['typical_hour']))} "
                    f"from {metadata.get('history_count', 0)} prior day(s)"
                )
        return lines
    if entry["kind"] == "new_event_type":
        lines = [entry["rendered_message"]]
        if metadata.get("observed_timestamps"):
            lines.append(f"Observed times: {format_timestamp_samples(metadata['observed_timestamps'])}")
        lines.append(
            f"No prior occurrences in {metadata.get('history_count', 0)} learned day(s) for this device"
        )
        return lines
    if entry["kind"] == "rare_event_activity":
        lines = [entry["rendered_message"]]
        if metadata.get("observed_timestamps"):
            lines.append(f"Observed times: {format_timestamp_samples(metadata['observed_timestamps'])}")
        lines.append(
            "Learned rarity: "
            f"{metadata.get('history_count', 0)} prior occurrence day(s) across "
            f"{metadata.get('observed_device_days', 0)} learned day(s) "
            f"({int(round(float(metadata.get('learned_presence_rate', 0.0)) * 100))}% presence)"
        )
        return lines
    if entry["kind"] == "cluster_anomaly" and metadata.get("member_events"):
        lines: List[str]
        if metadata.get("distance_minutes") is not None:
            lines = [
                f"{metadata.get('cluster')} on {metadata.get('day')}: "
                f"{format_duration_minutes(int(metadata.get('distance_minutes', 0)))} outside expected timing."
            ]
            if metadata.get("expected_windows"):
                windows = ", ".join(format_window(window) for window in metadata["expected_windows"])
                lines.append(f"Expected window(s): {windows}")
            elif metadata.get("learned_reference_hour") is not None:
                lines.append(
                    f"Learned start: {format_hour_value(float(metadata['learned_reference_hour']))}"
                )
        else:
            observed_size = entry.get("event_count", 0)
            expected_size = metadata.get("expected_size", "n/a")
            lines = [
                f"{metadata.get('cluster')} on {metadata.get('day')}: "
                f"observed {observed_size} of expected {expected_size} device(s)."
            ]
            min_cluster_size = metadata.get("min_cluster_size")
            if min_cluster_size is not None:
                lines.append(f"Alert threshold: fewer than {expected_size} device(s); partial threshold {min_cluster_size}")
        lines.append("Members:")
        for member in metadata["member_events"]:
            member_name = member.get("name") or member.get("mac") or "Unknown device"
            timestamp = member.get("timestamp")
            lines.append(f"- {member_name} ({member.get('mac')}) at {format_clock_from_iso(timestamp)}")
        return lines
    return [entry["rendered_message"]]


def finding_subject_label(entry: Dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    if entry["kind"] == "network_reset":
        return "Network recovery"
    if entry["kind"] == "cluster_anomaly":
        return str(metadata.get("cluster") or "Cluster")
    label = str(entry.get("device_label") or entry.get("mac") or "Unknown device")
    mac = str(entry.get("mac") or "")
    suffix = f" ({mac})"
    if mac and label.endswith(suffix):
        return label[: -len(suffix)]
    return label


def finding_subject_key(entry: Dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    if entry["kind"] == "network_reset":
        return f"incident:{metadata.get('incident_id') or 'network-reset'}"
    if entry["kind"] == "cluster_anomaly":
        return f"cluster:{metadata.get('cluster') or 'Cluster'}"
    return f"device:{entry.get('mac') or finding_subject_label(entry)}"


def finding_subject_identifier(entry: Dict[str, Any]) -> str:
    if entry["kind"] == "network_reset":
        return str(entry.get("metadata", {}).get("incident_id") or "Network incident")
    if entry["kind"] == "cluster_anomaly":
        return "Device group"
    return str(entry.get("mac") or "")


def finding_issue_summary(entry: Dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    kind = entry["kind"]
    if kind == "unknown_device":
        return "Unknown device activity"
    if kind == "blocked_device_activity":
        return "Blocked device activity"
    if kind == "network_reset":
        return f"{str(metadata.get('confidence') or 'probable').title()} internet connection reset"
    if kind == "dhcp_anomaly":
        return f"DHCP {metadata.get('direction', 'outside')} expected range"
    if kind == "event_volume_anomaly":
        direction = metadata.get("direction", "outside")
        qualifier = f"{direction} expected range"
        if entry.get("severity") == "low" and direction in {"above", "below"}:
            qualifier = f"slightly {direction} expected range"
        return f"Daily event count {qualifier}"
    if kind == "timing_anomaly":
        if "expected_event" in metadata:
            return "Expected event missing"
        return "Timing drift"
    if kind == "new_event_type":
        return f"First observed {humanize_event_key(metadata.get('event_key', 'EVENT'))}"
    if kind == "rare_event_activity":
        return f"Rare {humanize_event_key(metadata.get('event_key', 'EVENT'))}"
    if kind == "event_behavior_anomaly":
        return f"{humanize_event_key(metadata.get('event_key', 'EVENT'))} behavior changed"
    if kind == "cluster_anomaly":
        if metadata.get("distance_minutes") is not None:
            return "Cluster activated outside expected timing"
        return "Cluster partially observed"
    return str(entry.get("rendered_message") or kind)


def compact_metric_value(value: Any) -> str:
    if isinstance(value, float):
        return str(round(value, 2))
    return str(value)


def expected_range_text(metadata: Dict[str, Any]) -> str:
    expected = metadata.get("expected_range") or ["?", "?"]
    return f"{compact_metric_value(expected[0])}-{compact_metric_value(expected[1])}"


def finding_field_lines(entry: Dict[str, Any]) -> List[Tuple[str, str]]:
    metadata = entry.get("metadata", {})
    kind = entry["kind"]
    lines: List[Tuple[str, str]] = [("Issue", finding_issue_summary(entry))]
    day = finding_day(metadata)
    if day:
        lines.append(("Date", day))

    if kind in {"unknown_device", "blocked_device_activity"}:
        lines.append(("Events", f"{entry.get('event_count', 0)} event(s)"))
        return lines

    if kind == "network_reset":
        lines.append(("Confidence", str(metadata.get("confidence") or "probable").title()))
        lines.append(("Window", f"{metadata.get('start')} to {metadata.get('recovery_end')}"))
        lines.append(("Affected", f"{len(metadata.get('affected_macs') or [])} known device(s)"))
        lines.append(("Explained", f"{entry.get('event_count', 0)} event(s)"))
        event_counts = metadata.get("event_counts") or {}
        if event_counts:
            lines.append(
                (
                    "Evidence",
                    ", ".join(
                        f"{humanize_event_key(key)} {value}" for key, value in sorted(event_counts.items())
                    ),
                )
            )
        return lines

    if kind in {"dhcp_anomaly", "event_volume_anomaly"}:
        lines.append(
            (
                "Count",
                f"{entry.get('event_count', 0)} observed vs {expected_range_text(metadata)} expected",
            )
        )
        lines.append(("Basis", f"learned mean {metadata.get('learned_mean')}, trend {metadata.get('trend')}"))
        return lines

    if kind == "timing_anomaly":
        if "expected_event" in metadata:
            expected_event = metadata["expected_event"]
            target_hour = int(expected_event.get("hour", 0))
            target_minute = int(expected_event.get("minute", 0))
            target_minutes = target_hour * 60 + target_minute
            tolerance = int(expected_event.get("tolerance_minutes", 0))
            lines.append(("Expected", f"{format_clock_minutes(target_minutes)} +/- {tolerance} minute(s)"))
        elif "distance_hours" in metadata:
            lines.append(("Drift", f"{format_duration_hours(float(metadata['distance_hours']))} outside expected window"))
        if metadata.get("hours"):
            lines.append(("Seen", format_timestamp_samples(metadata["hours"])))
        if metadata.get("expected_windows"):
            lines.append(("Expected", ", ".join(format_window(window) for window in metadata["expected_windows"])))
        elif metadata.get("expected_active_hours"):
            lines.append(("Expected", format_active_hours(metadata["expected_active_hours"])))
        return lines

    if kind in {"new_event_type", "rare_event_activity"}:
        if metadata.get("observed_timestamps"):
            lines.append(("Seen", format_timestamp_samples(metadata["observed_timestamps"])))
        if kind == "new_event_type":
            lines.append(("Basis", f"no prior occurrences in {metadata.get('history_count', 0)} learned day(s)"))
        else:
            lines.append(
                (
                    "Basis",
                    f"{metadata.get('history_count', 0)} prior occurrence day(s) across "
                    f"{metadata.get('observed_device_days', 0)} learned day(s), "
                    f"{int(round(float(metadata.get('learned_presence_rate', 0.0)) * 100))}% presence",
                )
            )
        return lines

    if kind == "event_behavior_anomaly":
        reasons = metadata.get("reasons") or []
        if reasons:
            lines.append(("Change", ", ".join(reasons)))
        if metadata.get("observed_timestamps"):
            lines.append(("Seen", format_timestamp_samples(metadata["observed_timestamps"])))
        if any(reason.startswith("time shift ") for reason in reasons) and metadata.get("typical_hour") is not None:
            lines.append(
                (
                    "Basis",
                    f"typical time around {format_hour_value(float(metadata['typical_hour']))} "
                    f"from {metadata.get('history_count', 0)} prior day(s)",
                )
            )
        if "weekday drift" in reasons and metadata.get("dominant_weekdays") is not None:
            observed_weekday = metadata.get("current_weekday")
            if observed_weekday is not None:
                lines.append(("Weekday", weekday_name(int(observed_weekday))))
            dominant = metadata.get("dominant_weekdays") or []
            if dominant:
                lines.append(
                    (
                        "Pattern",
                        f"{', '.join(weekday_name(int(weekday)) for weekday in dominant)} "
                        f"from {metadata.get('history_count', 0)} prior day(s)",
                    )
                )
        return lines

    if kind == "cluster_anomaly":
        if metadata.get("distance_minutes") is not None:
            if metadata.get("start"):
                lines.append(("Started", format_clock_from_iso(metadata["start"])))
            lines.append(("Drift", f"{format_duration_minutes(int(metadata.get('distance_minutes', 0)))} outside expected timing"))
            if metadata.get("expected_windows"):
                lines.append(("Expected", ", ".join(format_window(window) for window in metadata["expected_windows"])))
            elif metadata.get("learned_reference_hour") is not None:
                lines.append(("Expected", f"learned start around {format_hour_value(float(metadata['learned_reference_hour']))}"))
        else:
            observed_size = entry.get("event_count", 0)
            expected_size = metadata.get("expected_size", "n/a")
            lines.append(("Observed", f"{observed_size} of expected {expected_size} device(s)"))
            min_cluster_size = metadata.get("min_cluster_size")
            if min_cluster_size is not None:
                lines.append(("Threshold", f"fewer than {expected_size} device(s); partial threshold {min_cluster_size}"))
        return lines

    return lines


def finding_member_lines(entry: Dict[str, Any]) -> List[str]:
    metadata = entry.get("metadata", {})
    if entry["kind"] != "cluster_anomaly" or not metadata.get("member_events"):
        return []
    rendered = []
    for member in metadata["member_events"]:
        member_name = member.get("name") or member.get("mac") or "Unknown device"
        timestamp = member.get("timestamp")
        rendered.append(f"{member_name} ({member.get('mac')}) at {format_clock_from_iso(timestamp)}")
    return rendered


def all_report_findings(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = report["findings"]
    if findings.get("all"):
        return list(findings["all"])
    return list(findings.get("critical", [])) + list(findings.get("anomalies", [])) + list(findings.get("observations", []))


def finding_index_rows(report: Dict[str, Any]) -> List[Dict[str, str]]:
    rows = []
    for entry in sorted(all_report_findings(report), key=finding_entry_sort_key):
        rows.append(
            {
                "severity": entry["severity"].upper(),
                "subject": finding_subject_label(entry),
                "issue": finding_issue_summary(entry),
                "date": finding_day(entry.get("metadata", {})) or "n/a",
            }
        )
    return rows


def grouped_finding_entries(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for entry in sorted(all_report_findings(report), key=finding_entry_sort_key):
        key = finding_subject_key(entry)
        if key not in grouped:
            grouped[key] = {
                "label": finding_subject_label(entry),
                "identifier": finding_subject_identifier(entry),
                "entries": [],
            }
        grouped[key]["entries"].append(entry)
    return sorted(
        grouped.values(),
        key=lambda group: (
            min(finding_entry_sort_key(entry) for entry in group["entries"]),
            group["label"].lower(),
        ),
    )


def wrap_label_value(label: str, value: str, width: int, indent: str = "    ") -> List[str]:
    label_text = f"{label:<8}: "
    available = max(30, width - len(indent) - len(label_text))
    wrapped = textwrap.wrap(value, width=available) or [""]
    return [f"{indent}{label_text}{wrapped[0]}"] + [
        f"{indent}{' ' * len(label_text)}{line}" for line in wrapped[1:]
    ]


def markdown_table_cell(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|")


def report_entry_lines(entry: Dict[str, Any], width: int) -> List[str]:
    detail_width = max(30, width - 8)
    lines = finding_detail_lines(entry)
    rendered: List[str] = []
    for line in lines:
        subsequent_indent = "  " if not line.startswith("- ") else "      "
        wrapped = textwrap.wrap(line, width=detail_width, subsequent_indent=subsequent_indent) or [line]
        rendered.extend(wrapped)
    return rendered


def section_rule(title: str, width: int, char: str = "-") -> str:
    title_text = f" {title} "
    if len(title_text) >= width:
        return title
    remaining = width - len(title_text)
    left = remaining // 2
    right = remaining - left
    return f"{char * left}{title_text}{char * right}"


def group_device_summary(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item["name"]].append(item)
    summaries: List[Dict[str, Any]] = []
    for name, group_items in grouped.items():
        sorted_members = sorted(group_items, key=lambda item: item["mac"])
        summaries.append(
            {
                "name": name,
                "count": len(sorted_members),
                "events": sum(item["total_events"] for item in sorted_members),
                "dhcp": sum(item["dhcp_count"] for item in sorted_members),
                "incident_explained": sum(item.get("incident_explained_events", 0) for item in sorted_members),
                "macs": [item["mac"] for item in sorted_members],
                "event_types": sorted({event_type for item in sorted_members for event_type in item["event_types"]}),
            }
        )
    return sorted(
        summaries,
        key=lambda item: (-item["events"], -item["dhcp"], item["name"].lower()),
    )


def render_text_report(report: Dict[str, Any]) -> str:
    width = min(max(shutil.get_terminal_size((110, 24)).columns, 80), 120)
    parse_stats = report["parse_stats"]
    observation_range = report["observation_range"]
    adjustments = report.get("analysis_adjustments", {})
    summary_lines = render_key_value_lines(
        [
            ("Risk Score", f"{report['risk_score']} / 100"),
            ("Status", report["status"]),
            ("Database", report["inputs"]["db"]),
            ("Run Persistence", run_persistence_text(report)),
            ("Parsed Events", parse_stats["parsed_events"]),
            ("Incident-Explained", adjustments.get("incident_explained_event_count", 0)),
            ("Events Analyzed", adjustments.get("analyzed_event_count", parse_stats["parsed_events"])),
            ("Malformed Lines", parse_stats["malformed_lines"]),
            ("Duplicate Events", parse_stats["duplicate_events"]),
            ("Spam-Filtered DHCP", parse_stats["spam_filtered"]),
            ("Export Noise", parse_stats["export_noise_lines"]),
            (
                "Observation Range",
                f"{observation_range['start'] or 'n/a'} to {observation_range['end'] or 'n/a'}",
            ),
        ]
    )
    if parse_stats.get("malformed_samples"):
        summary_lines.append("Malformed Samples:")
        summary_lines.extend(f"  - {sample}" for sample in parse_stats["malformed_samples"])

    lines: List[str] = [
        "Network Analysis Report",
        "=" * min(width, max(24, len("Network Analysis Report"))),
        "",
    ]
    lines.extend(summary_lines)
    lines.append("")

    lines.append(section_rule("Finding Index", min(width, 92)))
    lines.append("")
    index_rows = finding_index_rows(report)
    if index_rows:
        severity_width = max(3, max(len(row["severity"]) for row in index_rows))
        date_width = max(4, max(len(row["date"]) for row in index_rows))
        subject_width = min(32, max(7, max(len(row["subject"]) for row in index_rows)))
        issue_width = max(18, width - severity_width - subject_width - date_width - 8)
        lines.append(
            f"{'Sev':<{severity_width}}  {'Subject':<{subject_width}}  "
            f"{'Issue':<{issue_width}}  {'Date':<{date_width}}"
        )
        for row in index_rows:
            subject = textwrap.shorten(row["subject"], width=subject_width, placeholder="...")
            issue = textwrap.shorten(row["issue"], width=issue_width, placeholder="...")
            lines.append(
                f"{row['severity']:<{severity_width}}  {subject:<{subject_width}}  "
                f"{issue:<{issue_width}}  {row['date']:<{date_width}}"
            )
    else:
        lines.append("None")
        lines.append("")
    lines.append("")

    lines.append(section_rule("Findings by Device/Group", min(width, 92)))
    lines.append("")
    groups = grouped_finding_entries(report)
    if groups:
        for group in groups:
            lines.append(group["label"])
            if group["identifier"]:
                lines.append(f"  {group['identifier']}")
            lines.append("")
            for entry in group["entries"]:
                lines.append(f"  {entry['severity'].upper()} | {entry['kind']}")
                for label, value in finding_field_lines(entry):
                    lines.extend(wrap_label_value(label, value, width))
                members = finding_member_lines(entry)
                if members:
                    lines.append("    Members:")
                    for member in members:
                        wrapped = textwrap.wrap(member, width=max(30, width - 8)) or [member]
                        lines.append(f"      - {wrapped[0]}")
                        lines.extend(f"        {line}" for line in wrapped[1:])
                lines.append("")
    else:
        lines.append("None")
        lines.append("")

    lines.append(section_rule("Risk Breakdown", min(width, 92)))
    lines.append("")
    breakdown_lines = [f"{key}: {value}" for key, value in sorted(report["risk_breakdown"].items())] or ["None"]
    lines.extend(breakdown_lines)
    lines.append("")

    lines.append(section_rule("Device Summary", min(width, 92)))
    lines.append("")
    if report["device_summary"]:
        name_width = max(len(item["name"]) + (5 if item["count"] > 1 else 0) for item in group_device_summary(report["device_summary"]))
        for group in group_device_summary(report["device_summary"]):
            heading = f"{group['name']} ({group['count']})" if group["count"] > 1 else group["name"]
            lines.append(
                f"{heading:<{name_width + 4}} events {group['events']:>2}   dhcp {group['dhcp']:>2}   "
                f"reset {group['incident_explained']:>2}"
            )
            mac_chunks = [group["macs"][index:index + 2] for index in range(0, len(group["macs"]), 2)]
            for chunk in mac_chunks:
                lines.append(f"  {', '.join(chunk)}")
            if group["event_types"]:
                lines.append(
                    f"  {', '.join(humanize_event_key(event_type) for event_type in group['event_types'])}"
                )
            lines.append("")
    else:
        lines.append("No events parsed.")
    return "\n".join(lines)


def render_markdown_report(report: Dict[str, Any]) -> str:
    adjustments = report.get("analysis_adjustments", {})
    lines = [
        "# Network Analysis Report",
        "",
        f"- Risk Score: **{report['risk_score']} / 100**",
        f"- Status: **{report['status']}**",
        f"- Database: `{report['inputs']['db']}`",
        f"- Run Persistence: {run_persistence_text(report)}",
        "",
        "## Input Summary",
        "",
        f"- Parsed Events: {report['parse_stats']['parsed_events']}",
        f"- Incident-Explained Events: {adjustments.get('incident_explained_event_count', 0)}",
        f"- Events Analyzed: {adjustments.get('analyzed_event_count', report['parse_stats']['parsed_events'])}",
        f"- Malformed Lines: {report['parse_stats']['malformed_lines']}",
        f"- Duplicate Events Removed: {report['parse_stats']['duplicate_events']}",
        f"- Spam-Filtered DHCP Entries: {report['parse_stats']['spam_filtered']}",
        f"- Export Noise Lines Ignored: {report['parse_stats']['export_noise_lines']}",
        f"- Observation Range: {report['observation_range']['start'] or 'n/a'} to {report['observation_range']['end'] or 'n/a'}",
        "",
    ]
    if report["parse_stats"].get("malformed_samples"):
        lines.append("### Malformed Samples")
        lines.append("")
        lines.extend(f"- `{sample}`" for sample in report["parse_stats"]["malformed_samples"])
        lines.append("")

    lines.append("## Finding Index")
    lines.append("")
    index_rows = finding_index_rows(report)
    if index_rows:
        lines.append("| Severity | Subject | Issue | Date |")
        lines.append("| --- | --- | --- | --- |")
        for row in index_rows:
            lines.append(
                f"| {markdown_table_cell(row['severity'])} | {markdown_table_cell(row['subject'])} | "
                f"{markdown_table_cell(row['issue'])} | {markdown_table_cell(row['date'])} |"
            )
        lines.append("")
    else:
        lines.append("- None")
        lines.append("")

    lines.append("## Findings by Device/Group")
    lines.append("")
    groups = grouped_finding_entries(report)
    if groups:
        for group in groups:
            lines.append(f"### {group['label']}")
            lines.append("")
            if group["identifier"]:
                lines.append(f"`{group['identifier']}`")
                lines.append("")
            for entry in group["entries"]:
                lines.append(f"#### {entry['severity'].upper()} | `{entry['kind']}`")
                lines.append("")
                for label, value in finding_field_lines(entry):
                    lines.append(f"- **{label}:** {value}")
                members = finding_member_lines(entry)
                if members:
                    lines.append("- **Members:**")
                    lines.extend(f"  - {member}" for member in members)
                lines.append("")
    else:
        lines.append("- None")
        lines.append("")

    lines.append("## Risk Breakdown")
    lines.append("")
    if report["risk_breakdown"]:
        for key, value in sorted(report["risk_breakdown"].items()):
            lines.append(f"- `{key}`: {value}")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Device Summary")
    lines.append("")
    lines.append("| Name | MAC | DHCP | Events | Reset-Explained | Types |")
    lines.append("| --- | --- | ---: | ---: | ---: | --- |")
    for item in report["device_summary"]:
        lines.append(
            f"| {item['name']} | `{item['mac']}` | {item['dhcp_count']} | {item['total_events']} | "
            f"{item.get('incident_explained_events', 0)} | "
            f"{', '.join(humanize_event_key(event_type) for event_type in item['event_types'])} |"
        )
    return "\n".join(lines) + "\n"


def render_html_report(report: Dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value))

    adjustments = report.get("analysis_adjustments", {})

    def render_finding_index() -> str:
        rows = finding_index_rows(report)
        if not rows:
            return "<section><h2>Finding Index</h2><p>None</p></section>"
        row_html = "".join(
            "<tr>"
            f"<td>{esc(row['severity'])}</td>"
            f"<td>{esc(row['subject'])}</td>"
            f"<td>{esc(row['issue'])}</td>"
            f"<td>{esc(row['date'])}</td>"
            "</tr>"
            for row in rows
        )
        return (
            "<section><h2>Finding Index</h2><table>"
            "<thead><tr><th>Severity</th><th>Subject</th><th>Issue</th><th>Date</th></tr></thead>"
            f"<tbody>{row_html}</tbody></table></section>"
        )

    def render_grouped_findings() -> str:
        groups = grouped_finding_entries(report)
        if not groups:
            return "<section><h2>Findings by Device/Group</h2><p>None</p></section>"
        group_blocks: List[str] = []
        for group in groups:
            entry_blocks: List[str] = []
            identifier = f"<p><code>{esc(group['identifier'])}</code></p>" if group["identifier"] else ""
            for entry in group["entries"]:
                detail_items = "".join(
                    f"<li><strong>{esc(label)}:</strong> {esc(value)}</li>"
                    for label, value in finding_field_lines(entry)
                )
                members = finding_member_lines(entry)
                member_html = ""
                if members:
                    member_html = (
                        "<li><strong>Members:</strong><ul>"
                        + "".join(f"<li>{esc(member)}</li>" for member in members)
                        + "</ul></li>"
                    )
                entry_blocks.append(
                    "<article class=\"finding\">"
                    f"<h4>{esc(entry['severity'].upper())} | {esc(entry['kind'])}</h4>"
                    f"<ul>{detail_items}{member_html}</ul>"
                    "</article>"
                )
            group_blocks.append(
                "<article class=\"subject\">"
                f"<h3>{esc(group['label'])}</h3>"
                f"{identifier}"
                f"{''.join(entry_blocks)}"
                "</article>"
            )
        return f"<section><h2>Findings by Device/Group</h2>{''.join(group_blocks)}</section>"

    device_rows = "".join(
        "<tr>"
        f"<td>{esc(item['name'])}</td>"
        f"<td><code>{esc(item['mac'])}</code></td>"
        f"<td>{item['dhcp_count']}</td>"
        f"<td>{item['total_events']}</td>"
        f"<td>{item.get('incident_explained_events', 0)}</td>"
        f"<td>{esc(', '.join(humanize_event_key(event_type) for event_type in item['event_types']))}</td>"
        "</tr>"
        for item in report["device_summary"]
    )
    risk_rows = "".join(
        f"<li><code>{esc(key)}</code>: {value}</li>"
        for key, value in sorted(report["risk_breakdown"].items())
    ) or "<li>None</li>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Network Analysis Report</title>
  <style>
    :root {{
      --bg: #f4f1e8;
      --panel: #fffdf8;
      --ink: #1f2328;
      --muted: #5f6b76;
      --accent: #6b4f2a;
      --line: #d7cfbf;
    }}
    body {{ margin: 0; padding: 32px; background: linear-gradient(180deg, #efe8d9, #f7f4ed); color: var(--ink); font: 16px/1.5 Georgia, 'Iowan Old Style', serif; }}
    main {{ max-width: 1080px; margin: 0 auto; display: grid; gap: 20px; }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 20px 22px; box-shadow: 0 10px 30px rgba(60, 41, 17, 0.06); }}
    h1, h2 {{ margin: 0 0 12px; color: var(--accent); }}
    h3 {{ margin: 0 0 10px; color: var(--ink); }}
    h4 {{ margin: 0 0 8px; color: var(--ink); }}
    dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; margin: 0; }}
    dt {{ font-weight: 700; }}
    dd {{ margin: 0; color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 10px 8px; border-top: 1px solid var(--line); vertical-align: top; }}
    th {{ border-top: 0; color: var(--accent); }}
    code {{ font-size: 0.92em; }}
    ul {{ margin: 0; padding-left: 20px; }}
    .subject + .subject {{ margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }}
    .finding + .finding {{ margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--line); }}
    .finding p {{ margin: 0 0 8px; }}
  </style>
</head>
<body>
  <main>
    <section>
      <h1>Network Analysis Report</h1>
      <dl>
        <dt>Risk Score</dt><dd>{report['risk_score']} / 100</dd>
        <dt>Status</dt><dd>{esc(report['status'])}</dd>
        <dt>Database</dt><dd><code>{esc(report['inputs']['db'])}</code></dd>
        <dt>Run Persistence</dt><dd>{esc(run_persistence_text(report))}</dd>
        <dt>Observation Range</dt><dd>{esc(report['observation_range']['start'] or 'n/a')} to {esc(report['observation_range']['end'] or 'n/a')}</dd>
      </dl>
    </section>
    <section>
      <h2>Input Summary</h2>
      <dl>
        <dt>Parsed Events</dt><dd>{report['parse_stats']['parsed_events']}</dd>
        <dt>Incident-Explained Events</dt><dd>{adjustments.get('incident_explained_event_count', 0)}</dd>
        <dt>Events Analyzed</dt><dd>{adjustments.get('analyzed_event_count', report['parse_stats']['parsed_events'])}</dd>
        <dt>Malformed Lines</dt><dd>{report['parse_stats']['malformed_lines']}</dd>
        <dt>Duplicate Events Removed</dt><dd>{report['parse_stats']['duplicate_events']}</dd>
        <dt>Spam-Filtered DHCP</dt><dd>{report['parse_stats']['spam_filtered']}</dd>
        <dt>Export Noise</dt><dd>{report['parse_stats']['export_noise_lines']}</dd>
      </dl>
    </section>
    {render_finding_index()}
    {render_grouped_findings()}
    <section>
      <h2>Risk Breakdown</h2>
      <ul>{risk_rows}</ul>
    </section>
    <section>
      <h2>Device Summary</h2>
      <table>
        <thead>
          <tr><th>Name</th><th>MAC</th><th>DHCP</th><th>Events</th><th>Reset-Explained</th><th>Types</th></tr>
        </thead>
        <tbody>{device_rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def emit_report_outputs(
    report: Dict[str, Any],
    report_formats: Sequence[str],
    logfile_path: Path,
    report_dir: Optional[Path],
) -> None:
    report_paths = build_report_paths(logfile_path, report_formats, report_dir)
    if "text" in report_formats:
        print(render_text_report(report))
        if len(report_formats) > 1:
            report_paths["text"] = (report_dir.expanduser().resolve() if report_dir else Path.cwd()) / f"{logfile_path.stem}.report.txt"
            report_paths["text"].write_text(render_text_report(report) + "\n", encoding="utf-8")

    if "markdown" in report_formats:
        report_paths["markdown"].write_text(render_markdown_report(report), encoding="utf-8")
    if "html" in report_formats:
        report_paths["html"].write_text(render_html_report(report), encoding="utf-8")
    if "json" in report_formats and "text" not in report_formats:
        # Legacy --json behavior remains stdout-only unless --report requested explicitly.
        report_paths["json"].write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    elif "json" in report_formats and "text" in report_formats:
        report_paths["json"].write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    generated = [
        f"{fmt}: {path}"
        for fmt, path in report_paths.items()
        if fmt != "text" or len(report_formats) > 1
    ]
    if generated:
        print()
        print("Generated reports:")
        for item in generated:
            print(f"- {item}")


def persist_analysis(
    store: StateStore,
    run_hash: str,
    logfile_path: Path,
    parse_stats: ParseStats,
    aggregate: Dict[str, Any],
    findings: Dict[str, List[Finding]],
    score: int,
    status: str,
    epoch_id: int,
    policy_profile_id: Optional[int],
    devices_snapshot: Dict[str, Dict[str, Any]],
    is_partial: bool,
    incidents: Optional[Sequence[NetworkIncident]] = None,
) -> Tuple[bool, Optional[int]]:
    existing_run = store.get_run_by_hash(run_hash)
    if existing_run is not None:
        return True, existing_run["id"]

    (
        device_day_exclusions,
        device_day_reasons,
        event_day_exclusions,
        event_day_reasons,
        subject_day_exclusions,
        subject_day_reasons,
    ) = build_exclusion_maps(
        aggregate,
        findings,
        devices_snapshot,
        is_partial,
    )
    try:
        run_id = store.insert_run(
            epoch_id=epoch_id,
            policy_profile_id=policy_profile_id,
            file_hash=run_hash,
            source_path=logfile_path,
            parse_stats=parse_stats,
            observation_start=aggregate["observation_range"]["start"],
            observation_end=aggregate["observation_range"]["end"],
            observed_dates=aggregate["observed_dates"],
            risk_score=score,
            status=status,
            is_partial=is_partial,
        )
    except sqlite3.IntegrityError:
        existing_run = store.get_run_by_hash(run_hash)
        return True, existing_run["id"] if existing_run is not None else None

    for (observed_date, mac), stat in aggregate["device_day_stats"].items():
        store.upsert_device(
            mac=mac,
            name=aggregate["mac_to_name"].get(mac),
            status=devices_snapshot.get(mac, {}).get("status"),
            connection_type=devices_snapshot.get(mac, {}).get("connection_type"),
            source=devices_snapshot.get(mac, {}).get("source") or "observed",
            seen_at=stat.last_seen.isoformat() if stat.last_seen else utcnow_iso(),
        )
        store.insert_device_daily_stat(
            run_id,
            epoch_id,
            stat,
            included=(observed_date, mac) not in device_day_exclusions,
            exclusion_reason=device_day_reasons.get((observed_date, mac)),
        )

    for key, stat in aggregate["event_day_stats"].items():
        store.insert_device_event_daily_stat(
            run_id,
            epoch_id,
            stat,
            included=key not in event_day_exclusions,
            exclusion_reason=event_day_reasons.get(key),
        )

    for (subject_key, subject_type), subject in aggregate.get("behavior_subjects", {}).items():
        store.upsert_behavior_subject(
            subject_key=subject_key,
            subject_type=subject_type,
            display_name=subject.get("display_name"),
            attributes=subject.get("attributes"),
        )

    for key, stat in aggregate.get("subject_behavior_day_stats", {}).items():
        store.insert_subject_behavior_daily_stat(
            run_id,
            epoch_id,
            stat,
            included=key not in subject_day_exclusions,
            exclusion_reason=subject_day_reasons.get(key),
        )
    for incident in incidents or []:
        store.insert_network_incident(run_id, incident)
    store.commit()
    return False, run_id


def export_baseline_document(
    store: StateStore,
    epoch_id: int,
    seed_baseline: Dict[str, Any],
    policy: Dict[str, Any],
    devices_snapshot: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    exported: Dict[str, Any] = {"devices": {}}
    for mac in store.fetch_epoch_macs(epoch_id):
        if mac == SYSTEM_ACTOR:
            continue
        history = store.fetch_device_metric_history(epoch_id, mac, None, None)
        dhcp_values = [float(row["dhcp_count"]) for row in history]
        total_values = [float(row["total_events"]) for row in history]
        seed_config = seed_baseline.get("devices", {}).get(mac, {})
        dhcp_profile = compute_numeric_profile(
            dhcp_values,
            normalize_range(seed_config.get("dhcp_per_day_range")),
            float(policy["learning"]["seed_weight_frequent"]),
            float(policy["learning"]["stddev_floor"]),
        )
        total_profile = compute_numeric_profile(
            total_values,
            normalize_range(seed_config.get("events_per_day")),
            float(policy["learning"]["seed_weight_frequent"]),
            float(policy["learning"]["stddev_floor"]),
        )

        exported_config: Dict[str, Any] = {}
        device_name = devices_snapshot.get(mac, {}).get("name") or seed_config.get("name")
        if device_name:
            exported_config["name"] = device_name
        if dhcp_profile is not None:
            exported_config["dhcp_per_day_range"] = [
                round(max(0.0, dhcp_profile["range_min"]), 2),
                round(dhcp_profile["range_max"], 2),
            ]
            exported_config["mean_dhcp"] = round(dhcp_profile["mean"], 2)
            exported_config["stddev_dhcp"] = round(dhcp_profile["stddev"], 2)
        if total_profile is not None:
            exported_config["events_per_day"] = [
                round(max(0.0, total_profile["range_min"]), 2),
                round(total_profile["range_max"], 2),
            ]
            exported_config["mean_events"] = round(total_profile["mean"], 2)
            exported_config["stddev_events"] = round(total_profile["stddev"], 2)
        for config_field in ("active_hours", "expected_windows", "expected_events", "pattern", "soft_max"):
            if config_field in seed_config:
                exported_config[config_field] = seed_config[config_field]

        event_profiles: Dict[str, Any] = {}
        for event_key in store.fetch_epoch_event_keys(epoch_id, mac):
            if event_key == "DHCP_IP":
                continue
            profile = build_event_profile(store, epoch_id, mac, event_key, "9999-12-31", policy)
            if profile is None:
                continue
            event_profiles[event_key] = {
                "presence_rate": round(profile["presence_rate"], 2),
                "dominant_weekdays": profile["dominant_weekdays"],
                "typical_hour": round(profile["typical_hour"], 2) if profile["typical_hour"] is not None else None,
                "history_count": profile["history_count"],
            }
            if profile["count_profile"] is not None:
                event_profiles[event_key]["mean_count"] = round(profile["count_profile"]["mean"], 2)
                event_profiles[event_key]["stddev_count"] = round(profile["count_profile"]["stddev"], 2)
        if event_profiles:
            exported_config["event_profiles"] = event_profiles

        if exported_config:
            exported["devices"][mac] = exported_config

    for cluster_name, config in find_cluster_profiles(seed_baseline).items():
        exported["devices"][cluster_name] = config
    return exported


def handle_management_commands(args: argparse.Namespace, store: StateStore) -> bool:
    handled = False
    if args.import_policy:
        policy_doc = load_json_file(Path(args.import_policy).expanduser())
        policy_id = store.import_policy(Path(args.import_policy).expanduser(), policy_doc)
        print(f"Imported policy profile {policy_id} from {args.import_policy}")
        handled = True

    if args.export_policy:
        write_json_file(Path(args.export_policy).expanduser(), store.export_policy_data())
        print(f"Exported active policy to {args.export_policy}")
        handled = True

    if args.import_baseline:
        baseline_doc = normalize_baseline_document(load_json_file(Path(args.import_baseline).expanduser()))
        policy, _ = store.load_effective_policy()
        epoch_id = store.import_baseline(
            Path(args.import_baseline).expanduser(),
            baseline_doc,
            float(policy["learning"]["seed_weight_frequent"]),
        )
        print(f"Imported baseline epoch {epoch_id} from {args.import_baseline}")
        handled = True

    if args.import_config:
        router_config = load_router_security_config(Path(args.import_config).expanduser())
        imported = store.import_config(Path(args.import_config).expanduser(), router_config)
        print(f"Imported {imported} config device rows from {args.import_config}")
        handled = True

    if args.export_baseline:
        epoch = store.get_active_epoch()
        if epoch is None:
            raise SystemExit("No active baseline epoch to export")
        policy, _ = store.load_effective_policy()
        seed_baseline = store.load_seed_baseline(epoch["id"])
        devices_snapshot = store.load_devices_snapshot()
        exported = export_baseline_document(store, epoch["id"], seed_baseline, policy, devices_snapshot)
        write_json_file(Path(args.export_baseline).expanduser(), exported)
        print(f"Exported active learned baseline to {args.export_baseline}")
        handled = True

    return handled


def has_management_command(args: argparse.Namespace) -> bool:
    return any(
        getattr(args, name, None)
        for name in (
            "import_policy", "export_policy", "import_baseline", "export_baseline", "import_config",
        )
    )


def has_stateful_log_request(args: argparse.Namespace) -> bool:
    if has_management_command(args) or args.baseline or args.config or args.reprocess:
        return True
    inferred_config = infer_config_path(args)
    return inferred_config is not None and inferred_config.exists()


def validate_router_instance_override(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or any(unicodedata.category(character) == "Cc" for character in normalized):
        raise SystemExit("--router-instance must be nonempty and contain no control characters.")
    return normalized


def router_instance_override_key(canonical_vendor: str, value: str) -> str:
    """Return the opaque, vendor-scoped identity for a validated local override."""
    normalized_value = validate_router_instance_override(value)
    assert normalized_value is not None
    normalized_vendor = " ".join(canonical_vendor.strip().split()).casefold()
    payload = "router-instance-override:v1\0" + normalized_vendor + "\0" + normalized_value
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def emit_nonpersistent_report(
    args: argparse.Namespace,
    parsed: ParsedRouterLog,
    reason: str = "no_stable_router_identity",
) -> None:
    """Report parsed current evidence without opening state for an identity-less adapter."""
    if args.report or args.report_dir:
        raise SystemExit("Non-persistent reports do not support --report or --report-dir.")
    router_label = args.router_label.strip() if args.router_label and args.router_label.strip() else parsed.identity.canonical_vendor
    report = {
        "format_id": parsed.format_id,
        "router_label": router_label,
        "parse_stats": asdict(parsed.parse_stats),
        "event_count": len(parsed.events),
        "persistence": {"available": False, "reason": reason},
        "warnings": parsed.warnings,
    }
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Parsed router log for {router_label} without persistent state: {reason}")


def is_in_windows(timestamp: datetime, windows: Sequence[Dict[str, Any]]) -> bool:
    hour = timestamp.hour + (timestamp.minute / 60.0)
    for window in windows:
        start_hour = float(window.get("start_hour", 0))
        end_hour = float(window.get("end_hour", 24))
        if start_hour <= hour <= end_hour:
            return True
    return False


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report_formats = parse_report_formats(args.report, args.json)
    explicit_report = bool(args.report)
    runtime_paths = build_runtime_paths()
    db_path = Path(args.db).expanduser() if args.db else runtime_paths.db
    stateful_log_requested = has_stateful_log_request(args) if args.logfile is not None else False
    parsed: Optional[ParsedRouterLog] = None
    logfile_path: Optional[Path] = None
    raw_bytes: Optional[bytes] = None

    if args.logfile is not None:
        logfile_path = Path(args.logfile).expanduser()
        raw_bytes, log_text = load_log_content(logfile_path)
        parsed = parse_router_log(log_text, source=str(logfile_path), requested_format=args.format)
        router_instance_override = validate_router_instance_override(args.router_instance)
        if router_instance_override is not None:
            # The digest is deliberately the only override representation allowed beyond this scope.
            router_instance_override_key(parsed.identity.canonical_vendor, router_instance_override)
        if not parsed.identity.persistence_safe_without_override and router_instance_override is None:
            if stateful_log_requested:
                raise SystemExit(
                    "Cannot combine stateful operations with a log that has no stable router identity. "
                    "Provide --router-instance or run the non-persistent report separately."
                )
            emit_nonpersistent_report(args, parsed)
            return 0
        if parsed.format_id == FORMAT_TP_LINK_ARCHER:
            if stateful_log_requested:
                raise SystemExit(
                    "TP-Link persistence is not implemented yet; stateful operations require the router-scoped "
                    "schema and occurrence provenance added in later tasks."
                )
            emit_nonpersistent_report(args, parsed, "tp_link_persistence_not_implemented")
            return 0

    store = StateStore(db_path)
    try:
        handled = handle_management_commands(args, store)
        if handled and not args.logfile:
            return 0

        if args.logfile is None:
            raise SystemExit("No logfile provided")

        config_path = infer_config_path(args)
        if config_path and config_path.exists():
            router_config = load_router_security_config(config_path)
            store.import_config(config_path, router_config)

        epoch = store.get_active_epoch()
        policy, policy_row = store.load_effective_policy()

        if epoch is None:
            if args.baseline:
                baseline_doc = normalize_baseline_document(load_json_file(Path(args.baseline).expanduser()))
                epoch_id = store.import_baseline(
                    Path(args.baseline).expanduser(),
                    baseline_doc,
                    float(policy["learning"]["seed_weight_frequent"]),
                )
                epoch = store.get_active_epoch()
                if epoch is None:
                    raise SystemExit(f"Failed to activate baseline epoch {epoch_id}")
            else:
                raise SystemExit(
                    "No active baseline epoch. Run --import-baseline baseline.json or provide a bootstrap baseline path."
                )

        seed_baseline = store.load_seed_baseline(epoch["id"])
        devices_snapshot = store.load_devices_snapshot()
        assert logfile_path is not None
        assert raw_bytes is not None
        assert parsed is not None
        run_hash = sha256_bytes(raw_bytes)
        events, parse_stats = parsed.events, parsed.parse_stats
        reprocessed_run_id: Optional[int] = None
        existing_run = store.get_run_by_hash(run_hash)
        if args.reprocess and existing_run is not None:
            reprocessed_run_id = int(existing_run["id"])
            if not store.delete_run(reprocessed_run_id):
                raise RuntimeError(f"Failed to prepare run {reprocessed_run_id} for reprocessing")
        aggregate = aggregate_events(events, seed_baseline, devices_snapshot)
        incidents = detect_network_incidents(events, seed_baseline, devices_snapshot, policy)
        subject_behavior_day_stats, behavior_subjects = build_subject_behavior_day_stats(aggregate, policy)
        aggregate["subject_behavior_day_stats"] = subject_behavior_day_stats
        aggregate["behavior_subjects"] = behavior_subjects

        analyzed_events = [event for event in events if event.incident_id is None]
        analysis_aggregate = aggregate_events(analyzed_events, seed_baseline, devices_snapshot)
        analysis_subject_stats, analysis_subjects = build_subject_behavior_day_stats(analysis_aggregate, policy)
        analysis_aggregate["subject_behavior_day_stats"] = analysis_subject_stats
        analysis_aggregate["behavior_subjects"] = analysis_subjects
        findings = detect_anomalies(
            aggregate=analysis_aggregate,
            seed_baseline=seed_baseline,
            devices_snapshot=devices_snapshot,
            store=store,
            epoch_id=epoch["id"],
            policy=policy,
            incidents=incidents,
        )
        score, status, breakdown = compute_risk_score(findings, policy)
        is_partial = detect_partial_run(events, policy)
        deduplicated, run_id = persist_analysis(
            store=store,
            run_hash=run_hash,
            logfile_path=logfile_path,
            parse_stats=parse_stats,
            aggregate=aggregate,
            findings=findings,
            score=score,
            status=status,
            epoch_id=epoch["id"],
            policy_profile_id=policy_row["id"] if policy_row else None,
            devices_snapshot=devices_snapshot,
            is_partial=is_partial,
            incidents=incidents,
        )

        report = build_report_data(
            args=args,
            db_path=db_path,
            parse_stats=parse_stats,
            aggregate=aggregate,
            findings=findings,
            score=score,
            status=status,
            breakdown=breakdown,
            deduplicated=deduplicated,
            epoch_id=epoch["id"],
            policy_profile_id=policy_row["id"] if policy_row else None,
            incidents=incidents,
            analyzed_event_count=len(analyzed_events),
            reprocessed_run_id=reprocessed_run_id,
        )

        if args.json and not explicit_report:
            print(json.dumps(report, indent=2, default=str))
        elif explicit_report:
            emit_report_outputs(
                report=report,
                report_formats=report_formats,
                logfile_path=logfile_path,
                report_dir=Path(args.report_dir).expanduser() if args.report_dir else None,
            )
        else:
            print(render_text_report(report))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
