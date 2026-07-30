#!/bin/sh

set -u

TMSM_HOME=${TMSM_HOME:-$HOME}
TMSM_INSTALL_DIR=${TMSM_INSTALL_DIR:-"$TMSM_HOME/Library/Scripts/time_machine_snapshot_monitor"}
TMSM_RUNTIME_DIR=${TMSM_RUNTIME_DIR:-"$TMSM_HOME/Library/Application Support/TimeMachineSnapshotMonitor"}
TMSM_PUBLIC_LINK=${TMSM_PUBLIC_LINK:-"$TMSM_HOME/Library/Scripts/tm-snapshot-monitor"}
TMSM_LAUNCH_AGENT_LABEL=${TMSM_LAUNCH_AGENT_LABEL:-local.time-machine-snapshot-monitor}
TMSM_PLIST_PATH=${TMSM_PLIST_PATH:-"$TMSM_HOME/Library/LaunchAgents/$TMSM_LAUNCH_AGENT_LABEL.plist"}

if [ -d "$TMSM_INSTALL_DIR" ] && [ ! -L "$TMSM_INSTALL_DIR" ]; then
    RESOLVED_INSTALL_DIR=$(CDPATH= cd -- "$TMSM_INSTALL_DIR" && /bin/pwd -P) ||
        exit 6
else
    RESOLVED_INSTALL_DIR=$TMSM_INSTALL_DIR
fi
EXPECTED_CLI=$RESOLVED_INSTALL_DIR/bin/tm-snapshot-monitor
EXPECTED_RUNTIME="$TMSM_HOME/Library/Application Support/TimeMachineSnapshotMonitor"

ALERTER_BIN=${ALERTER_BIN:-/opt/homebrew/bin/alerter}
LAUNCHCTL_BIN=${LAUNCHCTL_BIN:-/bin/launchctl}
ID_BIN=${ID_BIN:-/usr/bin/id}

purge_runtime=0
case "${1:-}" in
    '') ;;
    --purge) purge_runtime=1 ;;
    --help|-h)
        /bin/echo "Usage: uninstall.sh [--purge]"
        /bin/echo "Default preserves logs/state. --purge removes the exact runtime directory."
        exit 0
        ;;
    *)
        /bin/echo "Usage: uninstall.sh [--purge]" >&2
        exit 2
        ;;
esac

user_domain="gui/$("$ID_BIN" -u)"
"$LAUNCHCTL_BIN" bootout "$user_domain" "$TMSM_PLIST_PATH" >/dev/null 2>&1 || :
/bin/rm -f "$TMSM_PLIST_PATH"

if [ -L "$TMSM_PUBLIC_LINK" ]; then
    current_target=$(/usr/bin/readlink "$TMSM_PUBLIC_LINK" 2>/dev/null || :)
    if [ "$current_target" = "$EXPECTED_CLI" ]; then
        /bin/rm -f "$TMSM_PUBLIC_LINK"
    else
        /bin/echo "Preserved unrelated symlink: $TMSM_PUBLIC_LINK" >&2
    fi
elif [ -e "$TMSM_PUBLIC_LINK" ]; then
    /bin/echo "Preserved unrelated file: $TMSM_PUBLIC_LINK" >&2
fi

if [ -x "$ALERTER_BIN" ]; then
    for notification_group in \
        tm-snapshot-monitor.stale \
        tm-snapshot-monitor.running \
        tm-snapshot-monitor.health \
        tm-snapshot-monitor.repair \
        tm-snapshot-monitor.test
    do
        "$ALERTER_BIN" --remove "$notification_group" >/dev/null 2>&1 || :
    done
fi

if [ "$purge_runtime" -eq 1 ]; then
    if [ -z "$TMSM_RUNTIME_DIR" ] ||
        [ "$TMSM_RUNTIME_DIR" != "$EXPECTED_RUNTIME" ] ||
        [ "$TMSM_RUNTIME_DIR" = "$TMSM_HOME" ] ||
        [ "$TMSM_RUNTIME_DIR" = "$TMSM_HOME/Library/Application Support" ]; then
        /bin/echo "Refusing unsafe purge path: $TMSM_RUNTIME_DIR" >&2
        exit 6
    fi
    /bin/rm -rf -- "$TMSM_RUNTIME_DIR"
    /bin/echo "Uninstalled monitor and purged runtime logs/state."
else
    /bin/echo "Uninstalled monitor. Runtime logs/state were preserved."
fi
