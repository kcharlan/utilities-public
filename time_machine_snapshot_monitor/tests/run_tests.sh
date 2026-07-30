#!/bin/sh

set -u

TEST_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && /bin/pwd -P)
PROJECT_DIR=$(CDPATH= cd -- "$TEST_DIR/.." && /bin/pwd -P)
CLI="$PROJECT_DIR/bin/tm-snapshot-monitor"
LIB="$PROJECT_DIR/lib/tm_snapshot_monitor.sh"

TMP_ROOT=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/tm-snapshot-monitor-tests.XXXXXX")
trap '/bin/rm -rf "$TMP_ROOT"' EXIT HUP INT TERM

PASS_COUNT=0
FAIL_COUNT=0

pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    /bin/echo "ok - $1"
}

fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    /bin/echo "not ok - $1"
    if [ "$#" -gt 1 ]; then
        /bin/echo "  $2"
    fi
}

assert_contains() {
    name=$1
    haystack=$2
    needle=$3
    case "$haystack" in
        *"$needle"*) pass "$name" ;;
        *) fail "$name" "expected output to contain: $needle" ;;
    esac
}

assert_status() {
    name=$1
    expected=$2
    actual=$3
    if [ "$expected" -eq "$actual" ]; then
        pass "$name"
    else
        fail "$name" "expected status $expected, got $actual"
    fi
}

assert_equals() {
    name=$1
    expected=$2
    actual=$3
    if [ "$expected" = "$actual" ]; then
        pass "$name"
    else
        fail "$name" "expected [$expected], got [$actual]"
    fi
}

assert_file_exists() {
    name=$1
    file_path=$2
    if [ -f "$file_path" ]; then
        pass "$name"
    else
        fail "$name" "expected file to exist: $file_path"
    fi
}

run_cli() {
    output_file=$1
    shift
    TMSM_RUNTIME_DIR="$TMP_ROOT/runtime" "$CLI" "$@" >"$output_file" 2>&1
}

FAKE_BIN="$TMP_ROOT/fake-bin"
/bin/mkdir -p "$FAKE_BIN"

/bin/cat >"$FAKE_BIN/tmutil" <<'EOF'
#!/bin/sh
if [ "${FAKE_TMUTIL_EXIT:-0}" -ne 0 ]; then
    exit "$FAKE_TMUTIL_EXIT"
fi
if [ -n "${FAKE_TMUTIL_OUTPUT:-}" ]; then
    /bin/cat "$FAKE_TMUTIL_OUTPUT"
else
    /usr/bin/printf 'Backup session status:\n{\n    Running = 0;\n}\n'
fi
EOF

/bin/cat >"$FAKE_BIN/mount" <<'EOF'
#!/bin/sh
if [ -n "${FAKE_MOUNT_CALLED_FILE:-}" ]; then
    /bin/echo called >>"$FAKE_MOUNT_CALLED_FILE"
fi
if [ -n "${FAKE_MOUNT_OUTPUT:-}" ]; then
    /bin/cat "$FAKE_MOUNT_OUTPUT"
fi
EOF

/bin/cat >"$FAKE_BIN/alerter" <<'EOF'
#!/bin/sh
if [ "${1:-}" = "--version" ]; then
    /usr/bin/printf '%s\n' "${FAKE_ALERTER_VERSION:-26.5}"
    exit "${FAKE_ALERTER_EXIT:-0}"
fi
if [ -n "${FAKE_ALERTER_RECORD:-}" ]; then
    /usr/bin/printf '%s\n' "$*" >>"$FAKE_ALERTER_RECORD"
fi
if [ -n "${FAKE_ALERTER_RESPONSE:-}" ]; then
    /usr/bin/printf '%s\n' "$FAKE_ALERTER_RESPONSE"
fi
exit "${FAKE_ALERTER_EXIT:-0}"
EOF

/bin/cat >"$FAKE_BIN/launchctl" <<'EOF'
#!/bin/sh
if [ -n "${FAKE_LAUNCHCTL_RECORD:-}" ]; then
    /usr/bin/printf '%s\n' "$*" >>"$FAKE_LAUNCHCTL_RECORD"
fi
case "${1:-}" in
    bootstrap) exit "${FAKE_BOOTSTRAP_EXIT:-0}" ;;
    print) exit "${FAKE_PRINT_EXIT:-0}" ;;
    *) exit 0 ;;
esac
EOF

/bin/cat >"$FAKE_BIN/plutil" <<'EOF'
#!/bin/sh
if [ -n "${FAKE_PLUTIL_RECORD:-}" ]; then
    /usr/bin/printf '%s\n' "$*" >>"$FAKE_PLUTIL_RECORD"
fi
exit "${FAKE_PLUTIL_EXIT:-0}"
EOF

/bin/cat >"$FAKE_BIN/diskutil" <<'EOF'
#!/bin/sh
if [ -n "${FAKE_DISKUTIL_RECORD:-}" ]; then
    /usr/bin/printf '%s\n' "$*" >>"$FAKE_DISKUTIL_RECORD"
fi
exit_status=${FAKE_DISKUTIL_EXIT:-0}
if [ "$exit_status" -eq 0 ] && [ "${FAKE_DISKUTIL_CLEAR_MOUNTS:-0}" -eq 1 ] && [ -n "${FAKE_MOUNT_OUTPUT:-}" ]; then
    : >"$FAKE_MOUNT_OUTPUT"
fi
exit "$exit_status"
EOF

/bin/chmod 700 "$FAKE_BIN/tmutil" "$FAKE_BIN/mount" "$FAKE_BIN/alerter" "$FAKE_BIN/launchctl" "$FAKE_BIN/plutil" "$FAKE_BIN/diskutil"

run_function() {
    output_file=$1
    function_name=$2
    shift 2
    /usr/bin/env \
        HOME="${TMSM_TEST_HOME:-$HOME}" \
        TMSM_RUNTIME_DIR="$TMP_ROOT/runtime" \
        TMUTIL_BIN="$FAKE_BIN/tmutil" \
        MOUNT_BIN="$FAKE_BIN/mount" \
        ALERTER_BIN="$FAKE_BIN/alerter" \
        DISKUTIL_BIN="$FAKE_BIN/diskutil" \
        "$@" \
        /bin/sh -c '. "$1"; "$2"' tm-test "$LIB" "$function_name" \
        >"$output_file" 2>&1
}

run_fake_cli() {
    output_file=$1
    tm_fixture=$2
    mount_fixture=$3
    alerter_record=$4
    mount_called_record=$5
    shift 5
    /usr/bin/env \
        HOME="${TMSM_TEST_HOME:-$HOME}" \
        TMSM_RUNTIME_DIR="$TMP_ROOT/runtime" \
        TMUTIL_BIN="$FAKE_BIN/tmutil" \
        MOUNT_BIN="$FAKE_BIN/mount" \
        ALERTER_BIN="$FAKE_BIN/alerter" \
        DISKUTIL_BIN="$FAKE_BIN/diskutil" \
        FAKE_TMUTIL_OUTPUT="$tm_fixture" \
        FAKE_MOUNT_OUTPUT="$mount_fixture" \
        FAKE_ALERTER_RECORD="$alerter_record" \
        FAKE_MOUNT_CALLED_FILE="$mount_called_record" \
        "$CLI" "$@" >"$output_file" 2>&1
}

test_help_contract() {
    output="$TMP_ROOT/help.out"
    run_cli "$output" --help
    status=$?
    text=$(/bin/cat "$output")
    assert_status "--help exits successfully" 0 "$status"
    assert_contains "--help documents repair" "$text" "--repair"
    assert_contains "--help documents alert-only scheduling" "$text" "alert-only"
}

test_unknown_argument_contract() {
    output="$TMP_ROOT/unknown.out"
    run_cli "$output" --not-a-real-option
    status=$?
    assert_status "unsupported option exits 2" 2 "$status"
}

test_no_argument_dispatches_check() {
    output="$TMP_ROOT/default.out"
    run_cli "$output"
    status=$?
    assert_status "no arguments dispatches a successful check" 0 "$status"
}

test_tm_status_tristate() {
    idle_fixture="$TMP_ROOT/tm-idle"
    running_fixture="$TMP_ROOT/tm-running"
    missing_fixture="$TMP_ROOT/tm-missing"
    conflicting_fixture="$TMP_ROOT/tm-conflicting"

    /usr/bin/printf 'Backup session status:\n{\n    Running = 0;\n}\n' >"$idle_fixture"
    /usr/bin/printf 'Backup session status:\n{\n\tRunning = 1;\n}\n' >"$running_fixture"
    /usr/bin/printf 'Backup session status:\n{\n    Percent = 0;\n}\n' >"$missing_fixture"
    /usr/bin/printf '    Running = 0;\n    Running = 1;\n' >"$conflicting_fixture"

    output="$TMP_ROOT/status.out"
    run_function "$output" tm_status "FAKE_TMUTIL_OUTPUT=$idle_fixture"
    assert_equals "tm_status recognizes idle" "idle" "$(/bin/cat "$output")"

    run_function "$output" tm_status "FAKE_TMUTIL_OUTPUT=$running_fixture"
    assert_equals "tm_status recognizes running" "running" "$(/bin/cat "$output")"

    run_function "$output" tm_status "FAKE_TMUTIL_OUTPUT=$missing_fixture"
    assert_equals "tm_status treats missing Running as unknown" "unknown" "$(/bin/cat "$output")"

    run_function "$output" tm_status "FAKE_TMUTIL_OUTPUT=$conflicting_fixture"
    assert_equals "tm_status treats conflicting Running values as unknown" "unknown" "$(/bin/cat "$output")"

    run_function "$output" tm_status "FAKE_TMUTIL_OUTPUT=$idle_fixture" "FAKE_TMUTIL_EXIT=9"
    assert_equals "tm_status treats tmutil failure as unknown" "unknown" "$(/bin/cat "$output")"
}

test_snapshot_mount_filtering() {
    mount_fixture="$TMP_ROOT/mounts"
    /usr/bin/printf '%s\n' \
        '/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled)' \
        '/dev/disk3s5@/Backups.backupdb/Example Mac/2026-07-30-081204/Data on /Volumes/com.apple.TimeMachine.localsnapshots/Backups.backupdb/Example Mac/2026-07-30-081204/Data (apfs, local, read-only, journaled, nobrowse)' \
        '/dev/disk3s5@/Other/Data on /Volumes/com.apple.TimeMachine.localsnapshots/Other Snapshot/Data (apfs, local, read-only)' \
        '/dev/fake on /tmp/Volumes/com.apple.TimeMachine.localsnapshots/deceptive (apfs, local)' \
        >"$mount_fixture"

    output="$TMP_ROOT/mount-filter.out"
    empty_tm="$TMP_ROOT/empty-tm"
    : >"$empty_tm"
    run_function "$output" list_snapshot_mounts \
        "FAKE_TMUTIL_OUTPUT=$empty_tm" \
        "FAKE_MOUNT_OUTPUT=$mount_fixture"
    text=$(/bin/cat "$output")
    expected="/Volumes/com.apple.TimeMachine.localsnapshots/Backups.backupdb/Example Mac/2026-07-30-081204/Data
/Volumes/com.apple.TimeMachine.localsnapshots/Other Snapshot/Data"
    assert_equals "mount filter returns only exact snapshot-prefix mounts" "$expected" "$text"
}

test_hourly_skip_counters_and_alert_thresholds() {
    runtime="$TMP_ROOT/runtime"
    /bin/rm -rf "$runtime"
    running_fixture="$TMP_ROOT/counter-running"
    empty_mounts="$TMP_ROOT/counter-mounts"
    alerter_record="$TMP_ROOT/counter-alerts"
    mount_calls="$TMP_ROOT/counter-mount-calls"
    output="$TMP_ROOT/counter.out"
    /usr/bin/printf '    Running = 1;\n' >"$running_fixture"
    : >"$empty_mounts"
    : >"$alerter_record"
    : >"$mount_calls"

    count=1
    while [ "$count" -le 3 ]; do
        run_fake_cli "$output" "$running_fixture" "$empty_mounts" "$alerter_record" "$mount_calls" --check
        assert_status "running check $count exits successfully" 0 "$?"
        count=$((count + 1))
    done

    assert_equals "first three running checks do not alert" "" "$(/bin/cat "$alerter_record")"
    assert_equals "running checks do not inspect mounts" "" "$(/bin/cat "$mount_calls")"
    assert_equals "running counter reaches three" "3" "$(/bin/cat "$runtime/state/running_skip_count")"
    assert_equals "running checks reset status error counter" "0" "$(/bin/cat "$runtime/state/status_error_count")"

    run_fake_cli "$output" "$running_fixture" "$empty_mounts" "$alerter_record" "$mount_calls" --check
    assert_status "fourth running check exits successfully" 0 "$?"
    assert_contains "fourth running check alerts" "$(/bin/cat "$alerter_record")" "four hourly checks"

    before_lines=$(/usr/bin/wc -l <"$alerter_record" | /usr/bin/tr -d ' ')
    run_fake_cli "$output" "$running_fixture" "$empty_mounts" "$alerter_record" "$mount_calls" --check
    after_lines=$(/usr/bin/wc -l <"$alerter_record" | /usr/bin/tr -d ' ')
    assert_equals "fifth running check refreshes alert" "$((before_lines + 1))" "$after_lines"
    assert_equals "running counter reaches five" "5" "$(/bin/cat "$runtime/state/running_skip_count")"
}

test_idle_resets_counters_and_detects_stale_mount() {
    runtime="$TMP_ROOT/runtime"
    /bin/mkdir -p "$runtime/state"
    /usr/bin/printf '7\n' >"$runtime/state/running_skip_count"
    /usr/bin/printf '3\n' >"$runtime/state/status_error_count"

    idle_fixture="$TMP_ROOT/reset-idle"
    stale_mounts="$TMP_ROOT/reset-mounts"
    alerter_record="$TMP_ROOT/reset-alerts"
    mount_calls="$TMP_ROOT/reset-mount-calls"
    output="$TMP_ROOT/reset.out"
    /usr/bin/printf '    Running = 0;\n' >"$idle_fixture"
    /usr/bin/printf '%s\n' \
        '/dev/disk3s5@/Data on /Volumes/com.apple.TimeMachine.localsnapshots/Backups.backupdb/Example Mac/2026-07-30-081204/Data (apfs, local, read-only)' \
        >"$stale_mounts"
    : >"$alerter_record"
    : >"$mount_calls"

    run_fake_cli "$output" "$idle_fixture" "$stale_mounts" "$alerter_record" "$mount_calls" --check
    assert_status "idle stale check exits successfully" 0 "$?"
    assert_equals "idle resets running counter" "0" "$(/bin/cat "$runtime/state/running_skip_count")"
    assert_equals "idle resets status error counter" "0" "$(/bin/cat "$runtime/state/status_error_count")"
    assert_contains "idle check inspects mounts" "$(/bin/cat "$mount_calls")" "called"
    assert_contains "stale mount triggers actionable alert" "$(/bin/cat "$alerter_record")" "Attempt Repair"
}

test_log_rotation_is_bounded() {
    runtime="$TMP_ROOT/runtime"
    /bin/rm -rf "$runtime"
    /bin/mkdir -p "$runtime/logs" "$runtime/state"
    /usr/bin/printf 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n' \
        >"$runtime/logs/monitor.log"

    idle_fixture="$TMP_ROOT/rotate-idle"
    empty_mounts="$TMP_ROOT/rotate-mounts"
    alerter_record="$TMP_ROOT/rotate-alerts"
    mount_calls="$TMP_ROOT/rotate-mount-calls"
    output="$TMP_ROOT/rotate.out"
    /usr/bin/printf '    Running = 0;\n' >"$idle_fixture"
    : >"$empty_mounts"
    : >"$alerter_record"
    : >"$mount_calls"

    export TMSM_LOG_LIMIT_BYTES=64
    run_fake_cli "$output" "$idle_fixture" "$empty_mounts" "$alerter_record" "$mount_calls" --check
    status=$?
    unset TMSM_LOG_LIMIT_BYTES

    assert_status "check succeeds while rotating log" 0 "$status"
    assert_file_exists "one compressed rotation is created" "$runtime/logs/monitor.log.1.gz"
    rotated_text=$(/usr/bin/gzip -dc "$runtime/logs/monitor.log.1.gz")
    assert_contains "rotation retains previous active log" "$rotated_text" "AAAAAAAA"
    active_text=$(/bin/cat "$runtime/logs/monitor.log")
    assert_contains "active log continues with current event" "$active_text" "event=check_clean"

    /usr/bin/printf 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB\n' \
        >"$runtime/logs/monitor.log"
    export TMSM_LOG_LIMIT_BYTES=64
    run_fake_cli "$output" "$idle_fixture" "$empty_mounts" "$alerter_record" "$mount_calls" --check
    status=$?
    unset TMSM_LOG_LIMIT_BYTES
    assert_status "second rotation succeeds" 0 "$status"
    rotated_text=$(/usr/bin/gzip -dc "$runtime/logs/monitor.log.1.gz")
    assert_contains "second rotation replaces prior archive" "$rotated_text" "BBBBBBBB"
    rotation_count=$(/usr/bin/find "$runtime/logs" -maxdepth 1 -name 'monitor.log.*.gz' -type f | /usr/bin/wc -l | /usr/bin/tr -d ' ')
    assert_equals "only one compressed rotation exists" "1" "$rotation_count"
}

test_repair_safety_and_normal_unmount() {
    runtime="$TMP_ROOT/runtime"
    /bin/rm -rf "$runtime"
    running_fixture="$TMP_ROOT/repair-running"
    unknown_fixture="$TMP_ROOT/repair-unknown"
    idle_fixture="$TMP_ROOT/repair-idle"
    stale_mounts="$TMP_ROOT/repair-mounts"
    empty_mounts="$TMP_ROOT/repair-empty"
    alerter_record="$TMP_ROOT/repair-alerts"
    mount_calls="$TMP_ROOT/repair-mount-calls"
    diskutil_record="$TMP_ROOT/repair-diskutil"
    output="$TMP_ROOT/repair.out"
    /usr/bin/printf '    Running = 1;\n' >"$running_fixture"
    /usr/bin/printf '    Percent = 0;\n' >"$unknown_fixture"
    /usr/bin/printf '    Running = 0;\n' >"$idle_fixture"
    /usr/bin/printf '%s\n' \
        '/dev/disk3s5@/Data on /Volumes/com.apple.TimeMachine.localsnapshots/Backups.backupdb/Example Mac/2026-07-30-081204/Data (apfs, local, read-only)' \
        >"$stale_mounts"
    : >"$empty_mounts"
    : >"$alerter_record"
    : >"$mount_calls"
    : >"$diskutil_record"

    export FAKE_DISKUTIL_RECORD="$diskutil_record"
    run_fake_cli "$output" "$running_fixture" "$stale_mounts" "$alerter_record" "$mount_calls" --repair
    assert_status "repair refuses while Time Machine runs" 3 "$?"
    assert_equals "running refusal never calls diskutil" "" "$(/bin/cat "$diskutil_record")"

    run_fake_cli "$output" "$unknown_fixture" "$stale_mounts" "$alerter_record" "$mount_calls" --repair
    assert_status "repair refuses unknown Time Machine status" 4 "$?"
    assert_equals "unknown refusal never calls diskutil" "" "$(/bin/cat "$diskutil_record")"

    run_fake_cli "$output" "$idle_fixture" "$empty_mounts" "$alerter_record" "$mount_calls" --repair
    assert_status "repair with no current mount is a no-op" 0 "$?"
    assert_equals "no-mount repair never calls diskutil" "" "$(/bin/cat "$diskutil_record")"

    export FAKE_DISKUTIL_CLEAR_MOUNTS=1
    run_fake_cli "$output" "$idle_fixture" "$stale_mounts" "$alerter_record" "$mount_calls" --repair
    success_status=$?
    unset FAKE_DISKUTIL_CLEAR_MOUNTS
    assert_status "normal unmount repair succeeds" 0 "$success_status"
    diskutil_text=$(/bin/cat "$diskutil_record")
    assert_contains "repair calls only normal unmount" "$diskutil_text" "unmount /Volumes/com.apple.TimeMachine.localsnapshots/"
    case "$diskutil_text" in
        *force*|*delete*|*sudo*) fail "repair command excludes dangerous operations" "$diskutil_text" ;;
        *) pass "repair command excludes dangerous operations" ;;
    esac

    /usr/bin/printf '%s\n' \
        '/dev/disk3s5@/Data on /Volumes/com.apple.TimeMachine.localsnapshots/Still Mounted/Data (apfs, local, read-only)' \
        >"$stale_mounts"
    export FAKE_DISKUTIL_EXIT=1
    run_fake_cli "$output" "$idle_fixture" "$stale_mounts" "$alerter_record" "$mount_calls" --repair
    failed_status=$?
    unset FAKE_DISKUTIL_EXIT FAKE_DISKUTIL_RECORD
    assert_status "failed normal unmount returns 5" 5 "$failed_status"
}

test_notification_action_rechecks_and_repairs() {
    runtime="$TMP_ROOT/runtime"
    /bin/rm -rf "$runtime"
    idle_fixture="$TMP_ROOT/action-idle"
    stale_mounts="$TMP_ROOT/action-mounts"
    alerter_record="$TMP_ROOT/action-alerts"
    mount_calls="$TMP_ROOT/action-mount-calls"
    diskutil_record="$TMP_ROOT/action-diskutil"
    output="$TMP_ROOT/action.out"
    /usr/bin/printf '    Running = 0;\n' >"$idle_fixture"
    /usr/bin/printf '%s\n' \
        '/dev/disk3s5@/Data on /Volumes/com.apple.TimeMachine.localsnapshots/Action Test/Data (apfs, local, read-only)' \
        >"$stale_mounts"
    : >"$alerter_record"
    : >"$mount_calls"
    : >"$diskutil_record"

    export FAKE_ALERTER_RESPONSE="Attempt Repair"
    export FAKE_DISKUTIL_RECORD="$diskutil_record"
    export FAKE_DISKUTIL_CLEAR_MOUNTS=1
    run_fake_cli "$output" "$idle_fixture" "$stale_mounts" "$alerter_record" "$mount_calls" --check
    status=$?
    unset FAKE_ALERTER_RESPONSE FAKE_DISKUTIL_RECORD FAKE_DISKUTIL_CLEAR_MOUNTS

    assert_status "notification repair action completes successfully" 0 "$status"
    assert_contains "notification action invokes normal repair" "$(/bin/cat "$diskutil_record")" "unmount /Volumes/com.apple.TimeMachine.localsnapshots/Action Test/Data"
}

test_status_and_notification_self_test() {
    runtime="$TMP_ROOT/runtime"
    /bin/rm -rf "$runtime"
    /bin/mkdir -p "$runtime/state"
    /usr/bin/printf '2\n' >"$runtime/state/running_skip_count"
    /usr/bin/printf '0\n' >"$runtime/state/status_error_count"

    idle_fixture="$TMP_ROOT/status-idle"
    stale_mounts="$TMP_ROOT/status-mounts"
    alerter_record="$TMP_ROOT/status-alerts"
    mount_calls="$TMP_ROOT/status-mount-calls"
    output="$TMP_ROOT/status-cli.out"
    /usr/bin/printf '    Running = 0;\n' >"$idle_fixture"
    /usr/bin/printf '%s\n' \
        '/dev/disk3s5@/Data on /Volumes/com.apple.TimeMachine.localsnapshots/Status Test/Data (apfs, local, read-only)' \
        >"$stale_mounts"
    : >"$alerter_record"
    : >"$mount_calls"

    export TMSM_TEST_HOME="$TMP_ROOT/status-home"
    run_fake_cli "$output" "$idle_fixture" "$stale_mounts" "$alerter_record" "$mount_calls" --status
    unset TMSM_TEST_HOME
    assert_status "--status exits successfully" 0 "$?"
    status_text=$(/bin/cat "$output")
    assert_contains "--status reports Time Machine state" "$status_text" "Time Machine status: idle"
    assert_contains "--status reports mounted snapshot count" "$status_text" "Mounted local snapshots: 1"
    assert_contains "--status reports mounted snapshot path" "$status_text" "/Volumes/com.apple.TimeMachine.localsnapshots/Status Test/Data"
    assert_contains "--status reports running skip counter" "$status_text" "Running skip count: 2"
    assert_contains "--status prints exact repair command" "$status_text" "$TMP_ROOT/status-home/Library/Scripts/tm-snapshot-monitor --repair"

    run_fake_cli "$output" "$idle_fixture" "$stale_mounts" "$alerter_record" "$mount_calls" --test-notification
    assert_status "--test-notification exits successfully" 0 "$?"
    notification_args=$(/bin/cat "$alerter_record")
    assert_contains "test notification is clearly labeled" "$notification_args" "Time Machine Snapshot Monitor test"
    case "$notification_args" in
        *"Attempt Repair"*) fail "test notification has no repair action" "$notification_args" ;;
        *) pass "test notification has no repair action" ;;
    esac
}

test_notification_failure_records_real_status() {
    runtime="$TMP_ROOT/runtime"
    /bin/rm -rf "$runtime"
    idle_fixture="$TMP_ROOT/notification-failure-idle"
    empty_mounts="$TMP_ROOT/notification-failure-mounts"
    alerter_record="$TMP_ROOT/notification-failure-alerts"
    mount_calls="$TMP_ROOT/notification-failure-mount-calls"
    output="$TMP_ROOT/notification-failure.out"
    /usr/bin/printf '    Running = 0;\n' >"$idle_fixture"
    : >"$empty_mounts"
    : >"$alerter_record"
    : >"$mount_calls"

    export FAKE_ALERTER_EXIT=9
    run_fake_cli "$output" "$idle_fixture" "$empty_mounts" "$alerter_record" "$mount_calls" --test-notification
    failure_status=$?
    unset FAKE_ALERTER_EXIT

    assert_status "failed test notification returns dependency error" 6 "$failure_status"
    assert_contains "failed notification logs actual exit status" "$(/bin/cat "$runtime/logs/monitor.log")" "status=9"
}

test_installer_and_uninstaller_are_idempotent() {
    test_home="$TMP_ROOT/install-home"
    runtime="$test_home/Library/Application Support/TimeMachineSnapshotMonitor"
    install_dir="$test_home/Library/Scripts/time_machine_snapshot_monitor"
    backup_root="$test_home/deployment-backups"
    public_link="$test_home/Library/Scripts/tm-snapshot-monitor"
    plist="$test_home/Library/LaunchAgents/local.time-machine-snapshot-monitor.plist"
    launchctl_record="$TMP_ROOT/install-launchctl"
    plutil_record="$TMP_ROOT/install-plutil"
    alerter_record="$TMP_ROOT/install-alerter"
    idle_fixture="$TMP_ROOT/install-idle"
    empty_mounts="$TMP_ROOT/install-mounts"
    output="$TMP_ROOT/install.out"
    /bin/mkdir -p "$test_home/Library/Scripts" "$test_home/Library/LaunchAgents"
    /bin/chmod 755 "$test_home/Library/Scripts" "$test_home/Library/LaunchAgents"
    /usr/bin/printf '    Running = 0;\n' >"$idle_fixture"
    : >"$empty_mounts"
    : >"$launchctl_record"
    : >"$plutil_record"
    : >"$alerter_record"

    /usr/bin/env \
        TMSM_HOME="$test_home" \
        TMSM_RUNTIME_DIR="$runtime" \
        TMSM_INSTALL_DIR="$install_dir" \
        TMSM_BACKUP_ROOT="$backup_root" \
        TMSM_PUBLIC_LINK="$public_link" \
        TMSM_PLIST_PATH="$plist" \
        ALERTER_BIN="$FAKE_BIN/alerter" \
        LAUNCHCTL_BIN="$FAKE_BIN/launchctl" \
        PLUTIL_BIN="$FAKE_BIN/plutil" \
        TMUTIL_BIN="$FAKE_BIN/tmutil" \
        MOUNT_BIN="$FAKE_BIN/mount" \
        FAKE_TMUTIL_OUTPUT="$idle_fixture" \
        FAKE_MOUNT_OUTPUT="$empty_mounts" \
        FAKE_LAUNCHCTL_RECORD="$launchctl_record" \
        FAKE_PLUTIL_RECORD="$plutil_record" \
        FAKE_ALERTER_RECORD="$alerter_record" \
        "$PROJECT_DIR/install.sh" >"$output" 2>&1
    install_status=$?
    assert_status "installer succeeds in fake home" 0 "$install_status"
    assert_file_exists \
        "installer deploys monitor command" \
        "$install_dir/bin/tm-snapshot-monitor"
    if /usr/bin/cmp -s \
        "$PROJECT_DIR/lib/tm_snapshot_monitor.sh" \
        "$install_dir/lib/tm_snapshot_monitor.sh"; then
        pass "installer deploys monitor library byte-for-byte"
    else
        fail "installer deploys monitor library byte-for-byte"
    fi
    if [ -L "$public_link" ]; then
        pass "installer creates public symlink"
    else
        fail "installer creates public symlink" "missing symlink: $public_link"
    fi
    canonical_install_dir=$(CDPATH= cd -- "$install_dir" && /bin/pwd -P)
    assert_equals \
        "public symlink targets installed command" \
        "$canonical_install_dir/bin/tm-snapshot-monitor" \
        "$(/usr/bin/readlink "$public_link")"
    assert_file_exists "installer writes LaunchAgent plist" "$plist"
    plist_text=$(/bin/cat "$plist" 2>/dev/null)
    assert_contains "LaunchAgent schedules minute 45" "$plist_text" "<integer>45</integer>"
    case "$plist_text" in
        *RunAtLoad*|*KeepAlive*|*--repair*) fail "LaunchAgent remains alert-only" "$plist_text" ;;
        *) pass "LaunchAgent remains alert-only" ;;
    esac
    assert_contains "installer bootstraps user job" "$(/bin/cat "$launchctl_record")" "bootstrap"
    scripts_mode=$(/usr/bin/stat -f '%Lp' "$test_home/Library/Scripts")
    agents_mode=$(/usr/bin/stat -f '%Lp' "$test_home/Library/LaunchAgents")
    assert_equals "installer preserves existing Scripts directory mode" "755" "$scripts_mode"
    assert_equals "installer preserves existing LaunchAgents directory mode" "755" "$agents_mode"

    /usr/bin/printf 'synthetic installed drift\n' >"$install_dir/README.md"
    /usr/bin/env \
        TMSM_HOME="$test_home" \
        TMSM_RUNTIME_DIR="$runtime" \
        TMSM_INSTALL_DIR="$install_dir" \
        TMSM_BACKUP_ROOT="$backup_root" \
        TMSM_PUBLIC_LINK="$public_link" \
        TMSM_PLIST_PATH="$plist" \
        ALERTER_BIN="$FAKE_BIN/alerter" \
        LAUNCHCTL_BIN="$FAKE_BIN/launchctl" \
        PLUTIL_BIN="$FAKE_BIN/plutil" \
        TMUTIL_BIN="$FAKE_BIN/tmutil" \
        MOUNT_BIN="$FAKE_BIN/mount" \
        FAKE_TMUTIL_OUTPUT="$idle_fixture" \
        FAKE_MOUNT_OUTPUT="$empty_mounts" \
        "$PROJECT_DIR/install.sh" >"$output" 2>&1
    assert_status "installer updates a changed installed source tree" 0 "$?"
    if /usr/bin/cmp -s "$PROJECT_DIR/README.md" "$install_dir/README.md"; then
        pass "installer restores repository bytes after installed drift"
    else
        fail "installer restores repository bytes after installed drift"
    fi
    backup_readme=$(
        /usr/bin/find "$backup_root" \
            -path '*/time_machine_snapshot_monitor/README.md' \
            -type f -print -quit
    )
    assert_file_exists "installer backs up changed installed source" "$backup_readme"
    assert_contains \
        "deployment backup preserves previous installed bytes" \
        "$(/bin/cat "$backup_readme")" \
        "synthetic installed drift"

    /usr/bin/env \
        TMSM_HOME="$test_home" \
        TMSM_RUNTIME_DIR="$runtime" \
        TMSM_INSTALL_DIR="$install_dir" \
        TMSM_BACKUP_ROOT="$backup_root" \
        TMSM_PUBLIC_LINK="$public_link" \
        TMSM_PLIST_PATH="$plist" \
        ALERTER_BIN="$FAKE_BIN/alerter" \
        LAUNCHCTL_BIN="$FAKE_BIN/launchctl" \
        PLUTIL_BIN="$FAKE_BIN/plutil" \
        TMUTIL_BIN="$FAKE_BIN/tmutil" \
        MOUNT_BIN="$FAKE_BIN/mount" \
        FAKE_TMUTIL_OUTPUT="$idle_fixture" \
        FAKE_MOUNT_OUTPUT="$empty_mounts" \
        "$PROJECT_DIR/install.sh" >"$output" 2>&1
    assert_status "installer is safe to rerun without source drift" 0 "$?"

    marker="$runtime/logs/preserve-me"
    /usr/bin/printf 'preserve\n' >"$marker"
    /usr/bin/env \
        TMSM_HOME="$test_home" \
        TMSM_RUNTIME_DIR="$runtime" \
        TMSM_INSTALL_DIR="$install_dir" \
        TMSM_PUBLIC_LINK="$public_link" \
        TMSM_PLIST_PATH="$plist" \
        ALERTER_BIN="$FAKE_BIN/alerter" \
        LAUNCHCTL_BIN="$FAKE_BIN/launchctl" \
        FAKE_LAUNCHCTL_RECORD="$launchctl_record" \
        "$PROJECT_DIR/uninstall.sh" >"$output" 2>&1
    assert_status "default uninstaller succeeds" 0 "$?"
    if [ ! -e "$plist" ] && [ ! -L "$public_link" ]; then
        pass "default uninstaller removes job and public link"
    else
        fail "default uninstaller removes job and public link"
    fi
    assert_file_exists "default uninstaller preserves runtime logs" "$marker"

    /usr/bin/env \
        TMSM_HOME="$test_home" \
        TMSM_RUNTIME_DIR="$runtime" \
        TMSM_INSTALL_DIR="$install_dir" \
        TMSM_PUBLIC_LINK="$public_link" \
        TMSM_PLIST_PATH="$plist" \
        ALERTER_BIN="$FAKE_BIN/alerter" \
        LAUNCHCTL_BIN="$FAKE_BIN/launchctl" \
        "$PROJECT_DIR/uninstall.sh" --purge >"$output" 2>&1
    assert_status "purging uninstaller succeeds" 0 "$?"
    if [ ! -e "$runtime" ]; then
        pass "purging uninstaller removes only runtime directory"
    else
        fail "purging uninstaller removes only runtime directory" "runtime still exists"
    fi
}

test_installer_refuses_unrelated_public_file() {
    test_home="$TMP_ROOT/refuse-home"
    runtime="$test_home/Library/Application Support/TimeMachineSnapshotMonitor"
    install_dir="$test_home/Library/Scripts/time_machine_snapshot_monitor"
    public_link="$test_home/Library/Scripts/tm-snapshot-monitor"
    plist="$test_home/Library/LaunchAgents/local.time-machine-snapshot-monitor.plist"
    output="$TMP_ROOT/refuse.out"
    /bin/mkdir -p "$test_home/Library/Scripts" "$test_home/Library/LaunchAgents"
    /usr/bin/printf 'do not overwrite\n' >"$public_link"

    /usr/bin/env \
        TMSM_HOME="$test_home" \
        TMSM_RUNTIME_DIR="$runtime" \
        TMSM_INSTALL_DIR="$install_dir" \
        TMSM_PUBLIC_LINK="$public_link" \
        TMSM_PLIST_PATH="$plist" \
        ALERTER_BIN="$FAKE_BIN/alerter" \
        LAUNCHCTL_BIN="$FAKE_BIN/launchctl" \
        PLUTIL_BIN="$FAKE_BIN/plutil" \
        "$PROJECT_DIR/install.sh" >"$output" 2>&1
    assert_status "installer refuses unrelated public file" 6 "$?"
    assert_equals "installer preserves unrelated public file" "do not overwrite" "$(/bin/cat "$public_link")"
}

test_help_contract
test_unknown_argument_contract
test_no_argument_dispatches_check
test_tm_status_tristate
test_snapshot_mount_filtering
test_hourly_skip_counters_and_alert_thresholds
test_idle_resets_counters_and_detects_stale_mount
test_log_rotation_is_bounded
test_repair_safety_and_normal_unmount
test_notification_action_rechecks_and_repairs
test_status_and_notification_self_test
test_notification_failure_records_real_status
test_installer_and_uninstaller_are_idempotent
test_installer_refuses_unrelated_public_file

/bin/echo "1..$((PASS_COUNT + FAIL_COUNT))"
/bin/echo "# pass=$PASS_COUNT fail=$FAIL_COUNT"

if [ "$FAIL_COUNT" -ne 0 ]; then
    exit 1
fi
