#!/bin/sh

TMUTIL_BIN=${TMUTIL_BIN:-/usr/bin/tmutil}
MOUNT_BIN=${MOUNT_BIN:-/sbin/mount}
DISKUTIL_BIN=${DISKUTIL_BIN:-/usr/sbin/diskutil}
ALERTER_BIN=${ALERTER_BIN:-/opt/homebrew/bin/alerter}
GZIP_BIN=${GZIP_BIN:-/usr/bin/gzip}
STAT_BIN=${STAT_BIN:-/usr/bin/stat}
DATE_BIN=${DATE_BIN:-/bin/date}

TMSM_RUNTIME_DIR=${TMSM_RUNTIME_DIR:-"$HOME/Library/Application Support/TimeMachineSnapshotMonitor"}
TMSM_LOG_DIR=$TMSM_RUNTIME_DIR/logs
TMSM_STATE_DIR=$TMSM_RUNTIME_DIR/state
TMSM_LOG_FILE=$TMSM_LOG_DIR/monitor.log
TMSM_ROTATED_LOG=$TMSM_LOG_DIR/monitor.log.1.gz
TMSM_MOUNT_PREFIX=/Volumes/com.apple.TimeMachine.localsnapshots/
TMSM_RUNNING_COUNTER=running_skip_count
TMSM_ERROR_COUNTER=status_error_count
TMSM_LOG_LIMIT_BYTES=${TMSM_LOG_LIMIT_BYTES:-1048576}
TMSM_LOG_LOCK=$TMSM_STATE_DIR/log.lock
TMSM_PUBLIC_CLI=${TMSM_PUBLIC_CLI:-"$HOME/Library/Scripts/tm-snapshot-monitor"}
TMSM_LAUNCH_AGENT_LABEL=${TMSM_LAUNCH_AGENT_LABEL:-local.time-machine-snapshot-monitor}

print_usage() {
    /bin/echo "Usage: tm-snapshot-monitor [--check|--status|--repair|--test-notification|--help]"
}

print_help() {
    print_usage
    /bin/cat <<'EOF'

Hourly scheduled checks are alert-only. They never unmount snapshots.

  --check              Run one alert-only monitor check (default).
  --status             Show Time Machine and monitor state.
  --repair             Attempt a normal unmount after fresh safety checks.
  --test-notification  Send a harmless notification test.
  --help               Show this help.

Repair never forces an unmount, deletes a snapshot, kills a process, or runs
while Time Machine is active or its status cannot be determined.
EOF
}

tm_status() {
    tm_output=$("$TMUTIL_BIN" status 2>/dev/null) || {
        /bin/echo unknown
        return 0
    }

    running_values=$(
        /usr/bin/printf '%s\n' "$tm_output" |
            /usr/bin/sed -nE 's/^[[:space:]]*Running = ([01]);[[:space:]]*$/\1/p'
    )

    case "$running_values" in
        0) /bin/echo idle ;;
        1) /bin/echo running ;;
        *) /bin/echo unknown ;;
    esac
}

list_snapshot_mounts() {
    "$MOUNT_BIN" 2>/dev/null |
        /usr/bin/sed -nE \
            's|^.* on (/Volumes/com\.apple\.TimeMachine\.localsnapshots/.*) \([^)]*\)$|\1|p' |
        while IFS= read -r mount_path; do
            case "$mount_path" in
                "$TMSM_MOUNT_PREFIX"*) /usr/bin/printf '%s\n' "$mount_path" ;;
            esac
        done
}

ensure_runtime() {
    old_umask=$(umask)
    umask 077
    if ! /bin/mkdir -p "$TMSM_LOG_DIR" "$TMSM_STATE_DIR"; then
        umask "$old_umask"
        return 1
    fi
    [ -e "$TMSM_LOG_FILE" ] || : >"$TMSM_LOG_FILE"
    /bin/chmod 700 "$TMSM_RUNTIME_DIR" "$TMSM_LOG_DIR" "$TMSM_STATE_DIR" 2>/dev/null || :
    /bin/chmod 600 "$TMSM_LOG_FILE" 2>/dev/null || :
    umask "$old_umask"
}

counter_path() {
    case "$1" in
        "$TMSM_RUNNING_COUNTER"|"$TMSM_ERROR_COUNTER")
            /usr/bin/printf '%s/%s\n' "$TMSM_STATE_DIR" "$1"
            ;;
        *)
            return 1
            ;;
    esac
}

read_counter() {
    counter_file=$(counter_path "$1") || {
        /usr/bin/printf '0\n'
        return 1
    }
    if [ ! -f "$counter_file" ]; then
        /usr/bin/printf '0\n'
        return 0
    fi
    counter_value=$(/bin/cat "$counter_file" 2>/dev/null)
    case "$counter_value" in
        ''|*[!0-9]*)
            /usr/bin/printf '0\n'
            return 0
            ;;
        *)
            /usr/bin/printf '%s\n' "$counter_value"
            ;;
    esac
}

write_counter() {
    counter_name=$1
    counter_value=$2
    case "$counter_value" in
        ''|*[!0-9]*) return 1 ;;
    esac
    counter_file=$(counter_path "$counter_name") || return 1
    counter_tmp=$(/usr/bin/mktemp "$TMSM_STATE_DIR/.${counter_name}.XXXXXX") || return 1
    if ! /usr/bin/printf '%s\n' "$counter_value" >"$counter_tmp"; then
        /bin/rm -f "$counter_tmp"
        return 1
    fi
    /bin/chmod 600 "$counter_tmp" 2>/dev/null || :
    if ! /bin/mv -f "$counter_tmp" "$counter_file"; then
        /bin/rm -f "$counter_tmp"
        return 1
    fi
}

log_event() {
    log_level=$1
    log_name=$2
    shift 2
    acquire_log_lock || return 1
    if ! rotate_log_locked; then
        release_log_lock
        return 1
    fi
    log_timestamp=$("$DATE_BIN" '+%Y-%m-%dT%H:%M:%S%z')
    {
        /usr/bin/printf '%s level=%s event=%s' "$log_timestamp" "$log_level" "$log_name"
        for log_field in "$@"; do
            /usr/bin/printf ' %s' "$log_field"
        done
        /usr/bin/printf '\n'
    } >>"$TMSM_LOG_FILE"
    log_status=$?
    release_log_lock
    return "$log_status"
}

acquire_log_lock() {
    lock_attempt=0
    while [ "$lock_attempt" -lt 40 ]; do
        if /bin/mkdir "$TMSM_LOG_LOCK" 2>/dev/null; then
            /usr/bin/printf '%s\n' "$$" >"$TMSM_LOG_LOCK/pid"
            return 0
        fi
        lock_owner=$(/bin/cat "$TMSM_LOG_LOCK/pid" 2>/dev/null || :)
        case "$lock_owner" in
            ''|*[!0-9]*)
                /bin/rm -f "$TMSM_LOG_LOCK/pid" 2>/dev/null || :
                /bin/rmdir "$TMSM_LOG_LOCK" 2>/dev/null || :
                ;;
            *)
                if ! /bin/kill -0 "$lock_owner" 2>/dev/null; then
                    /bin/rm -f "$TMSM_LOG_LOCK/pid" 2>/dev/null || :
                    /bin/rmdir "$TMSM_LOG_LOCK" 2>/dev/null || :
                fi
                ;;
        esac
        /bin/sleep 0.05
        lock_attempt=$((lock_attempt + 1))
    done
    return 1
}

release_log_lock() {
    /bin/rm -f "$TMSM_LOG_LOCK/pid" 2>/dev/null || :
    /bin/rmdir "$TMSM_LOG_LOCK" 2>/dev/null || :
}

rotate_log_if_needed() {
    acquire_log_lock || return 1
    rotate_log_locked
    rotation_status=$?
    release_log_lock
    return "$rotation_status"
}

rotate_log_locked() {
    log_size=$("$STAT_BIN" -f '%z' "$TMSM_LOG_FILE" 2>/dev/null || /usr/bin/printf '0')
    case "$log_size" in
        ''|*[!0-9]*) log_size=0 ;;
    esac
    if [ "$log_size" -lt "$TMSM_LOG_LIMIT_BYTES" ]; then
        return 0
    fi

    rotation_tmp=$(/usr/bin/mktemp "$TMSM_LOG_DIR/.monitor.log.1.gz.XXXXXX") || {
        return 1
    }
    if ! "$GZIP_BIN" -c "$TMSM_LOG_FILE" >"$rotation_tmp" || [ ! -s "$rotation_tmp" ]; then
        /bin/rm -f "$rotation_tmp"
        return 1
    fi
    if ! /bin/mv -f "$rotation_tmp" "$TMSM_ROTATED_LOG"; then
        /bin/rm -f "$rotation_tmp"
        return 1
    fi
    : >"$TMSM_LOG_FILE"
    /bin/chmod 600 "$TMSM_LOG_FILE" "$TMSM_ROTATED_LOG" 2>/dev/null || :
}

send_counter_alert() {
    counter_kind=$1
    counter_value=$2
    case "$counter_kind" in
        running)
            alert_group=tm-snapshot-monitor.running
            alert_title="Time Machine still running"
            if [ "$counter_value" -eq 4 ]; then
                alert_message="Time Machine has been running across four hourly checks. This check was skipped."
            else
                alert_message="Time Machine has been running across $counter_value hourly checks. This check was skipped."
            fi
            ;;
        unknown)
            alert_group=tm-snapshot-monitor.health
            alert_title="Time Machine monitor needs attention"
            alert_message="The monitor could not determine Time Machine status across $counter_value hourly checks."
            ;;
        *)
            return 2
            ;;
    esac
    "$ALERTER_BIN" \
        --title "$alert_title" \
        --message "$alert_message" \
        --close-label "Dismiss" \
        --timeout 3300 \
        --group "$alert_group" \
        --sound default >/dev/null
}

send_stale_alert() {
    mount_count=$1
    alert_response=$(
        "$ALERTER_BIN" \
            --title "Stale Time Machine snapshot mounted" \
            --message "$mount_count local Time Machine snapshot mount(s) remain while Time Machine is idle." \
            --actions "Attempt Repair" \
            --close-label "Dismiss" \
            --timeout 3300 \
            --group "tm-snapshot-monitor.stale" \
            --sound default
    )
    alert_status=$?
    if [ "$alert_status" -ne 0 ]; then
        log_event ERROR notification_failed "kind=stale" "status=$alert_status"
        return 6
    fi
    case "$alert_response" in
        "Attempt Repair")
            log_event INFO repair_selected "source=notification"
            run_repair
            ;;
        *)
            log_event INFO notification_closed "kind=stale"
            ;;
    esac
}

send_result_notification() {
    result_title=$1
    result_message=$2
    "$ALERTER_BIN" \
        --title "$result_title" \
        --message "$result_message" \
        --close-label "Dismiss" \
        --timeout 120 \
        --group "tm-snapshot-monitor.repair" \
        --sound default >/dev/null 2>&1 || :
}

run_check() {
    ensure_runtime || return 6
    current_status=$(tm_status)

    case "$current_status" in
        idle)
            write_counter "$TMSM_RUNNING_COUNTER" 0 || return 6
            write_counter "$TMSM_ERROR_COUNTER" 0 || return 6
            snapshot_mounts=$(list_snapshot_mounts)
            if [ -z "$snapshot_mounts" ]; then
                log_event INFO check_clean "status=idle" "mounted_snapshots=0"
                return 0
            fi
            mount_count=$(
                /usr/bin/printf '%s\n' "$snapshot_mounts" |
                    /usr/bin/awk 'NF { count++ } END { print count + 0 }'
            )
            log_event WARN stale_snapshot_detected "count=$mount_count"
            send_stale_alert "$mount_count"
            ;;
        running)
            write_counter "$TMSM_ERROR_COUNTER" 0 || return 6
            running_count=$(read_counter "$TMSM_RUNNING_COUNTER")
            running_count=$((running_count + 1))
            write_counter "$TMSM_RUNNING_COUNTER" "$running_count" || return 6
            log_event INFO check_skipped "reason=running" "count=$running_count"
            if [ "$running_count" -ge 4 ]; then
                send_counter_alert running "$running_count" || return 6
            fi
            ;;
        unknown)
            write_counter "$TMSM_RUNNING_COUNTER" 0 || return 6
            error_count=$(read_counter "$TMSM_ERROR_COUNTER")
            error_count=$((error_count + 1))
            write_counter "$TMSM_ERROR_COUNTER" "$error_count" || return 6
            log_event ERROR check_skipped "reason=status_unknown" "count=$error_count"
            if [ "$error_count" -ge 4 ]; then
                send_counter_alert unknown "$error_count" || return 6
            fi
            ;;
    esac
    return 0
}

run_status() {
    ensure_runtime || return 6
    status_value=$(tm_status)
    mounted_values=$(list_snapshot_mounts)
    if [ -z "$mounted_values" ]; then
        mounted_count=0
    else
        mounted_count=$(
            /usr/bin/printf '%s\n' "$mounted_values" |
                /usr/bin/awk 'NF { count++ } END { print count + 0 }'
        )
    fi
    running_value=$(read_counter "$TMSM_RUNNING_COUNTER")
    error_value=$(read_counter "$TMSM_ERROR_COUNTER")

    /usr/bin/printf 'Time Machine status: %s\n' "$status_value"
    /usr/bin/printf 'Mounted local snapshots: %s\n' "$mounted_count"
    if [ -n "$mounted_values" ]; then
        /usr/bin/printf '%s\n' "$mounted_values" |
            while IFS= read -r mounted_path; do
                /usr/bin/printf '  %s\n' "$mounted_path"
            done
    fi
    /usr/bin/printf 'Running skip count: %s\n' "$running_value"
    /usr/bin/printf 'Status error count: %s\n' "$error_value"
    /usr/bin/printf 'Active log: %s\n' "$TMSM_LOG_FILE"
    /usr/bin/printf 'Rotated log: %s\n' "$TMSM_ROTATED_LOG"
    /usr/bin/printf 'LaunchAgent: %s\n' "$TMSM_LAUNCH_AGENT_LABEL"
    /usr/bin/printf 'Repair command: %s --repair\n' "$TMSM_PUBLIC_CLI"
}

run_repair() {
    ensure_runtime || return 6
    repair_status=$(tm_status)
    case "$repair_status" in
        running)
            log_event WARN repair_refused "reason=time_machine_running"
            /bin/echo "Repair refused: Time Machine is currently running."
            send_result_notification "Snapshot repair not attempted" "Time Machine is running. No unmount was attempted."
            return 3
            ;;
        unknown)
            log_event ERROR repair_refused "reason=status_unknown"
            /bin/echo "Repair refused: Time Machine status could not be determined."
            send_result_notification "Snapshot repair not attempted" "Time Machine status is unknown. No unmount was attempted."
            return 4
            ;;
    esac

    repair_mounts=$(/usr/bin/mktemp "$TMSM_STATE_DIR/.repair-mounts.XXXXXX") || return 6
    list_snapshot_mounts >"$repair_mounts"
    if [ ! -s "$repair_mounts" ]; then
        /bin/rm -f "$repair_mounts"
        log_event INFO repair_noop "reason=no_mounted_snapshots"
        /bin/echo "No stale mounted Time Machine snapshots were found."
        send_result_notification "No snapshot repair needed" "No mounted local Time Machine snapshots were found."
        return 0
    fi

    unmount_failures=0
    while IFS= read -r repair_mount; do
        case "$repair_mount" in
            "$TMSM_MOUNT_PREFIX"*) ;;
            *)
                unmount_failures=$((unmount_failures + 1))
                log_event ERROR repair_path_rejected "path=$repair_mount"
                continue
                ;;
        esac
        unmount_output=$("$DISKUTIL_BIN" unmount "$repair_mount" 2>&1)
        unmount_status=$?
        if [ "$unmount_status" -eq 0 ]; then
            log_event INFO unmount_succeeded "path=$repair_mount"
        else
            unmount_failures=$((unmount_failures + 1))
            log_event ERROR unmount_failed "status=$unmount_status" "path=$repair_mount"
            /usr/bin/printf 'Normal unmount failed for: %s\n%s\n' "$repair_mount" "$unmount_output" >&2
        fi
    done <"$repair_mounts"
    /bin/rm -f "$repair_mounts"

    remaining_mounts=$(list_snapshot_mounts)
    if [ -z "$remaining_mounts" ]; then
        "$ALERTER_BIN" --remove "tm-snapshot-monitor.stale" >/dev/null 2>&1 || :
        log_event INFO repair_complete "remaining=0" "command_failures=$unmount_failures"
        /bin/echo "Mounted Time Machine snapshots were cleared."
        send_result_notification "Snapshot repair completed" "The stale mounted Time Machine snapshot was unmounted."
        return 0
    fi

    remaining_count=$(
        /usr/bin/printf '%s\n' "$remaining_mounts" |
            /usr/bin/awk 'NF { count++ } END { print count + 0 }'
    )
    log_event ERROR repair_incomplete "remaining=$remaining_count" "command_failures=$unmount_failures"
    /usr/bin/printf 'Repair incomplete: %s mounted snapshot(s) remain.\n' "$remaining_count" >&2
    send_result_notification "Snapshot repair failed" "$remaining_count mounted snapshot(s) remain. Reboot may be required."
    return 5
}

run_test_notification() {
    ensure_runtime || return 6
    "$ALERTER_BIN" \
        --title "Time Machine Snapshot Monitor test" \
        --message "Notifications are configured correctly. No repair action was performed." \
        --close-label "Dismiss" \
        --timeout 10 \
        --group "tm-snapshot-monitor.test" \
        --sound default >/dev/null
    notification_status=$?
    if [ "$notification_status" -eq 0 ]; then
        log_event INFO test_notification_succeeded
        /bin/echo "Test notification sent."
        return 0
    fi
    log_event ERROR test_notification_failed "status=$notification_status"
    /bin/echo "Test notification failed." >&2
    return 6
}
