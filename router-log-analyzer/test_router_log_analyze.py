from __future__ import annotations

import copy
import json
import os
import re
import sys
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
        existing = store.get_run_by_hash(analyzer.sha256_bytes(log_path.read_bytes()))
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
        replacement = store.get_run_by_hash(analyzer.sha256_bytes(log_path.read_bytes()))
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
        existing = store.get_run_by_hash(analyzer.sha256_bytes(log_path.read_bytes()))
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
        restored = store.get_run_by_hash(analyzer.sha256_bytes(log_path.read_bytes()))
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
        assert store.get_run_by_hash(analyzer.sha256_bytes(log_path.read_bytes())) is not None
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
        assert store.get_run_by_hash(analyzer.sha256_bytes(log_path.read_bytes())) is not None
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
        "raw_timestamp", "clock_trust", "clock_segment_id", "boot_context_id", "boot_session_id",
        "occurrence_digest",
    )

    normalized = analyzer.parse_router_log(text, "synthetic-netgear.log", "netgear").events[0]
    legacy = analyzer.parse_log_text(text, "synthetic-netgear.log")[0][0]

    assert {name: getattr(normalized, name) for name in extended_fields} == {
        name: getattr(legacy, name) for name in extended_fields
    }


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
