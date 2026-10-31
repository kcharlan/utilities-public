#!/bin/sh

set -u

umask 077

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && /bin/pwd -P) || exit 6

TMSM_HOME=${TMSM_HOME:-$HOME}
TMSM_INSTALL_DIR=${TMSM_INSTALL_DIR:-"$TMSM_HOME/Library/Scripts/time_machine_snapshot_monitor"}
TMSM_RUNTIME_DIR=${TMSM_RUNTIME_DIR:-"$TMSM_HOME/Library/Application Support/TimeMachineSnapshotMonitor"}
TMSM_PUBLIC_LINK=${TMSM_PUBLIC_LINK:-"$TMSM_HOME/Library/Scripts/tm-snapshot-monitor"}
TMSM_LAUNCH_AGENT_LABEL=${TMSM_LAUNCH_AGENT_LABEL:-local.time-machine-snapshot-monitor}
TMSM_PLIST_PATH=${TMSM_PLIST_PATH:-"$TMSM_HOME/Library/LaunchAgents/$TMSM_LAUNCH_AGENT_LABEL.plist"}
TMSM_BACKUP_ROOT=${TMSM_BACKUP_ROOT:-"$TMSM_HOME/.utilities-deploy-backups"}

SOURCE_CLI=$SOURCE_DIR/bin/tm-snapshot-monitor
SOURCE_LIB=$SOURCE_DIR/lib/tm_snapshot_monitor.sh

ALERTER_BIN=${ALERTER_BIN:-/opt/homebrew/bin/alerter}
LAUNCHCTL_BIN=${LAUNCHCTL_BIN:-/bin/launchctl}
PLUTIL_BIN=${PLUTIL_BIN:-/usr/bin/plutil}
UNAME_BIN=${UNAME_BIN:-/usr/bin/uname}
ID_BIN=${ID_BIN:-/usr/bin/id}

fail_install() {
    /bin/echo "Install failed: $1" >&2
    exit 6
}

admit_backup_root() {
    case "$TMSM_BACKUP_ROOT" in
        /*) ;;
        *) /bin/echo "backup root must be absolute: $TMSM_BACKUP_ROOT" >&2; return 1 ;;
    esac
    case "/$TMSM_BACKUP_ROOT/" in
        */../*|*/./*) /bin/echo "unsafe backup root: $TMSM_BACKUP_ROOT" >&2; return 1 ;;
    esac
    probe=$TMSM_BACKUP_ROOT
    while [ "${probe%/}" != "$probe" ] && [ "$probe" != "/" ]; do probe=${probe%/}; done
    while [ "$probe" != "/" ] && [ "$probe" != "." ]; do
        if [ -L "$probe" ]; then
            case "$probe" in
                /tmp|/var) [ "$(/usr/bin/uname -s)" = Darwin ] && [ -d "$probe" ] || return 1 ;;
                *) /bin/echo "refusing linked backup path: $probe" >&2; return 1 ;;
            esac
        elif [ -e "$probe" ] && [ ! -d "$probe" ]; then
            /bin/echo "backup path is not a directory: $probe" >&2; return 1
        fi
        parent=$(dirname -- "$probe")
        [ "$parent" != "$probe" ] || break
        probe=$parent
    done
    if [ -d "$TMSM_BACKUP_ROOT" ]; then
        mode=$(/usr/bin/stat -f '%Lp' "$TMSM_BACKUP_ROOT") || return 1
        if [ $((0$mode & 0222)) -eq 0 ] || [ $((0$mode & 0111)) -eq 0 ] ||
            [ ! -w "$TMSM_BACKUP_ROOT" ] || [ ! -x "$TMSM_BACKUP_ROOT" ] ||
            ! /bin/ls -A "$TMSM_BACKUP_ROOT" >/dev/null; then
            /bin/echo "backup root is not readable/writable/searchable: $TMSM_BACKUP_ROOT" >&2
            return 1
        fi
    fi
}

prune_backups() {
    admit_backup_root || { /bin/echo "Warning: backup pruning refused" >&2; return; }
    [ -d "$TMSM_BACKUP_ROOT" ] || { /bin/echo "Warning: backup root missing: $TMSM_BACKUP_ROOT" >&2; return; }
    while :; do
        count=0 oldest=
        for candidate in "$TMSM_BACKUP_ROOT"/time-machine-snapshot-monitor.*; do
            [ -d "$candidate" ] && [ ! -L "$candidate" ] || continue
            count=$((count + 1))
            if [ -z "$oldest" ]; then
                oldest=$candidate
            else
                newer=$(/usr/bin/find -P "$oldest" -prune -newer "$candidate" -print) || {
                    /bin/echo "Warning: cannot compare backup: $candidate" >&2; return
                }
                reverse=$(/usr/bin/find -P "$candidate" -prune -newer "$oldest" -print) || {
                    /bin/echo "Warning: cannot compare backup: $candidate" >&2; return
                }
                if [ -n "$newer" ] || { [ -z "$reverse" ] && [ "$candidate" \< "$oldest" ]; }; then
                    oldest=$candidate
                fi
            fi
        done
        [ "$count" -gt 2 ] || return
        if ! /usr/bin/find -P "$oldest" -type d -exec /bin/chmod u+rwx {} + ||
            ! /bin/rm -rf -- "$oldest"; then
            /bin/echo "Warning: cannot remove backup: $oldest" >&2
            return
        fi
    done
}

distribution_files='
README.md
bin/tm-snapshot-monitor
install.sh
lib/tm_snapshot_monitor.sh
tests/run_tests.sh
uninstall.sh
'

deployment_matches_source() {
    [ -d "$TMSM_INSTALL_DIR" ] && [ ! -L "$TMSM_INSTALL_DIR" ] || return 1
    for relative_path in $distribution_files; do
        [ -f "$TMSM_INSTALL_DIR/$relative_path" ] &&
            [ ! -L "$TMSM_INSTALL_DIR/$relative_path" ] &&
            /usr/bin/cmp -s \
                "$SOURCE_DIR/$relative_path" \
                "$TMSM_INSTALL_DIR/$relative_path" ||
            return 1
        source_mode=$(/usr/bin/stat -f '%Mp%Lp' "$SOURCE_DIR/$relative_path") ||
            return 1
        deployed_mode=$(/usr/bin/stat -f '%Mp%Lp' "$TMSM_INSTALL_DIR/$relative_path") ||
            return 1
        [ "$source_mode" = "$deployed_mode" ] || return 1
    done
}

deploy_source_tree() {
    install_parent=$(dirname -- "$TMSM_INSTALL_DIR")
    case "$TMSM_INSTALL_DIR" in
        ''|/|"$TMSM_HOME"|"$install_parent")
            fail_install "unsafe installation directory: $TMSM_INSTALL_DIR"
            ;;
    esac
    if [ -e "$TMSM_INSTALL_DIR" ] || [ -L "$TMSM_INSTALL_DIR" ]; then
        [ -d "$TMSM_INSTALL_DIR" ] && [ ! -L "$TMSM_INSTALL_DIR" ] ||
            fail_install "installation path is not a regular directory: $TMSM_INSTALL_DIR"
    fi

    /bin/mkdir -p "$install_parent" ||
        fail_install "could not create installation parent directory"

    if deployment_matches_source; then
        TMSM_SETUP_ONLY=1 "$TMSM_INSTALL_DIR/install.sh"
        exit $?
    fi

    staging_dir=$(/usr/bin/mktemp -d \
        "$install_parent/.time_machine_snapshot_monitor.install.XXXXXX") ||
        fail_install "could not create installation staging directory"
    /bin/mkdir -p "$staging_dir/bin" "$staging_dir/lib" "$staging_dir/tests" || {
        /bin/rm -rf -- "$staging_dir"
        fail_install "could not create installation staging tree"
    }

    for relative_path in $distribution_files; do
        if ! /bin/cp -p \
            "$SOURCE_DIR/$relative_path" \
            "$staging_dir/$relative_path"; then
            /bin/rm -rf -- "$staging_dir"
            fail_install "could not stage project file: $relative_path"
        fi
    done

    for relative_path in $distribution_files; do
        if ! /usr/bin/cmp -s \
            "$SOURCE_DIR/$relative_path" \
            "$staging_dir/$relative_path"; then
            /bin/rm -rf -- "$staging_dir"
            fail_install "staged project verification failed: $relative_path"
        fi
    done

    backup_dir=
    if [ -d "$TMSM_INSTALL_DIR" ]; then
        admit_backup_root || { /bin/rm -rf -- "$staging_dir"; fail_install "unsafe deployment backup root"; }
        /bin/mkdir -p "$TMSM_BACKUP_ROOT" || {
            /bin/rm -rf -- "$staging_dir"; fail_install "could not create deployment backup directory"
        }
        admit_backup_root || { /bin/rm -rf -- "$staging_dir"; fail_install "unsafe deployment backup root"; }
        backup_dir=$(/usr/bin/mktemp -d \
            "$TMSM_BACKUP_ROOT/time-machine-snapshot-monitor.XXXXXX") || {
            /bin/rm -rf -- "$staging_dir"
            fail_install "could not create deployment backup"
        }
        /bin/chmod 700 "$backup_dir" 2>/dev/null || :
        if ! /bin/mv \
            "$TMSM_INSTALL_DIR" \
            "$backup_dir/time_machine_snapshot_monitor"; then
            /bin/rm -rf -- "$staging_dir"
            fail_install "could not back up the previous installation"
        fi
    fi

    if ! /bin/mv "$staging_dir" "$TMSM_INSTALL_DIR"; then
        if [ -n "$backup_dir" ]; then
            /bin/mv \
                "$backup_dir/time_machine_snapshot_monitor" \
                "$TMSM_INSTALL_DIR" 2>/dev/null || :
        fi
        fail_install "could not activate the staged installation"
    fi

    if ! TMSM_SETUP_ONLY=1 "$TMSM_INSTALL_DIR/install.sh"; then
        /bin/rm -rf -- "$TMSM_INSTALL_DIR"
        if [ -n "$backup_dir" ]; then
            /bin/mv \
                "$backup_dir/time_machine_snapshot_monitor" \
                "$TMSM_INSTALL_DIR" 2>/dev/null || :
        fi
        fail_install "deployed monitor setup failed; previous source was restored when available"
    fi

    if [ -n "$backup_dir" ]; then
        /bin/echo "Previous source backup: $backup_dir/time_machine_snapshot_monitor"
        prune_backups
    fi
    exit 0
}

[ "$("$UNAME_BIN" -s 2>/dev/null)" = "Darwin" ] ||
    fail_install "this monitor supports macOS only"
[ -x "$SOURCE_CLI" ] || fail_install "monitor CLI is missing or not executable: $SOURCE_CLI"
[ -r "$SOURCE_LIB" ] || fail_install "monitor library is missing or unreadable: $SOURCE_LIB"
[ -x "$ALERTER_BIN" ] || fail_install "alerter is required; install it with: brew install vjeantet/tap/alerter"

alerter_version=$("$ALERTER_BIN" --version 2>/dev/null) ||
    fail_install "could not determine alerter version"
alerter_major=$(
    /usr/bin/printf '%s\n' "$alerter_version" |
        /usr/bin/sed -nE 's/^[^0-9]*([0-9]+).*/\1/p' |
        /usr/bin/head -n 1
)
case "$alerter_major" in
    ''|*[!0-9]*) fail_install "unrecognized alerter version: $alerter_version" ;;
esac
[ "$alerter_major" -ge 26 ] ||
    fail_install "alerter 26 or newer is required; found: $alerter_version"

if [ "${TMSM_SETUP_ONLY:-0}" != 1 ] &&
    [ "$SOURCE_DIR" != "$TMSM_INSTALL_DIR" ]; then
    deploy_source_tree
fi

PUBLIC_DIR=$(dirname -- "$TMSM_PUBLIC_LINK")
PLIST_DIR=$(dirname -- "$TMSM_PLIST_PATH")
/bin/mkdir -p "$PUBLIC_DIR" "$PLIST_DIR" "$TMSM_RUNTIME_DIR/logs" "$TMSM_RUNTIME_DIR/state" ||
    fail_install "could not create installation directories"
/bin/chmod 700 "$TMSM_RUNTIME_DIR" "$TMSM_RUNTIME_DIR/logs" "$TMSM_RUNTIME_DIR/state" 2>/dev/null || :

if [ -L "$TMSM_PUBLIC_LINK" ]; then
    current_target=$(/usr/bin/readlink "$TMSM_PUBLIC_LINK") ||
        fail_install "could not read existing public symlink"
    [ "$current_target" = "$SOURCE_CLI" ] ||
        fail_install "public symlink points elsewhere and will not be overwritten: $TMSM_PUBLIC_LINK"
    /bin/rm -f "$TMSM_PUBLIC_LINK" ||
        fail_install "could not refresh public symlink"
elif [ -e "$TMSM_PUBLIC_LINK" ]; then
    fail_install "public path already exists and will not be overwritten: $TMSM_PUBLIC_LINK"
fi

/bin/ln -s "$SOURCE_CLI" "$TMSM_PUBLIC_LINK" ||
    fail_install "could not create public symlink"

plist_tmp=$(/usr/bin/mktemp "$PLIST_DIR/.tm-snapshot-monitor.plist.XXXXXX") ||
    fail_install "could not create temporary plist"

/bin/cat >"$plist_tmp" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$TMSM_LAUNCH_AGENT_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$TMSM_PUBLIC_LINK</string>
        <string>--check</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Minute</key>
        <integer>45</integer>
    </dict>
    <key>ProcessType</key>
    <string>Background</string>
    <key>LowPriorityIO</key>
    <true/>
    <key>Nice</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>/dev/null</string>
    <key>StandardErrorPath</key>
    <string>/dev/null</string>
</dict>
</plist>
EOF

if ! "$PLUTIL_BIN" -lint "$plist_tmp" >/dev/null; then
    /bin/rm -f "$plist_tmp"
    fail_install "LaunchAgent plist validation failed"
fi

/bin/mv -f "$plist_tmp" "$TMSM_PLIST_PATH" ||
    fail_install "could not install LaunchAgent plist"
/bin/chmod 600 "$TMSM_PLIST_PATH" 2>/dev/null || :

user_domain="gui/$("$ID_BIN" -u)"
"$LAUNCHCTL_BIN" bootout "$user_domain" "$TMSM_PLIST_PATH" >/dev/null 2>&1 || :
if ! "$LAUNCHCTL_BIN" bootstrap "$user_domain" "$TMSM_PLIST_PATH"; then
    fail_install "launchctl bootstrap failed"
fi
if ! "$LAUNCHCTL_BIN" print "$user_domain/$TMSM_LAUNCH_AGENT_LABEL" >/dev/null; then
    fail_install "loaded LaunchAgent could not be verified"
fi

TMSM_RUNTIME_DIR="$TMSM_RUNTIME_DIR" \
TMUTIL_BIN="${TMUTIL_BIN:-/usr/bin/tmutil}" \
MOUNT_BIN="${MOUNT_BIN:-/sbin/mount}" \
ALERTER_BIN="$ALERTER_BIN" \
"$TMSM_PUBLIC_LINK" --status || fail_install "installed status check failed"

TMSM_RUNTIME_DIR="$TMSM_RUNTIME_DIR" \
ALERTER_BIN="$ALERTER_BIN" \
"$TMSM_PUBLIC_LINK" --test-notification || fail_install "test notification failed"

/bin/echo "Installed Time Machine Snapshot Monitor."
/bin/echo "Schedule: hourly at minute 45 (alert-only)."
/bin/echo "Command: $TMSM_PUBLIC_LINK"
