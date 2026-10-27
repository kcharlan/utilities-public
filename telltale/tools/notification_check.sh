#!/bin/bash
set -euo pipefail
# Spec section 4 spike runner: starts `Telltale --notification-check` from a temporary
# one-shot launchd job, so the notification is posted from a launchd-started process.
# It never touches ~/Library/LaunchAgents; the job exists only in gui/$UID until this exits.
usage='Usage: tools/notification_check.sh <Telltale.app> <mode>   (mode: ui-not-running | ui-running)'
app_argument=${1:?$usage}
mode=${2:?$usage}
timeout=${TELLTALE_NOTIFICATION_CHECK_TIMEOUT:-20}
label=local.utilities.telltale.notification-check

# Resolve the bundle against the caller's working directory and validate it
# before writing anything; launchd needs an absolute executable path.
case "$app_argument" in /*) candidate=$app_argument ;; *) candidate="$PWD/$app_argument" ;; esac
if ! parent=$(cd "$(dirname "$candidate")" 2>/dev/null && pwd -P); then
    echo "No such directory for app: $app_argument" >&2; exit 2
fi
app="$parent/$(basename "$candidate")"
executable="$app/Contents/MacOS/Telltale"
if [ ! -d "$app" ] || [ ! -x "$executable" ]; then
    echo "Not a Telltale app bundle (missing Contents/MacOS/Telltale): $app" >&2; exit 2
fi

work=$(mktemp -d "${TMPDIR:-/tmp}/telltale-notification-check.XXXXXX")
chmod 700 "$work"
domain="gui/$(id -u)"
cleanup() {
    launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT

result="$work/result.json"
plist="$work/$label.plist"
# plutil encodes each argument as one plist string, so spaces and XML characters survive.
plutil -create xml1 "$plist"
plutil -insert Label -string "$label" "$plist"
plutil -insert RunAtLoad -bool true "$plist"
plutil -insert ProgramArguments -array "$plist"
index=0
for argument in "$executable" --notification-check --result "$result" --mode "$mode"; do
    plutil -insert "ProgramArguments.$index" -string "$argument" "$plist"
    index=$((index + 1))
done

# A job left by an interrupted earlier run would make bootstrap fail.
launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
launchctl bootstrap "$domain" "$plist"

waited=0
while [ ! -s "$result" ]; do
    if [ "$waited" -ge $((timeout * 5)) ]; then
        echo "No result within ${timeout}s from the notification check." >&2; exit 1
    fi
    sleep 0.2
    waited=$((waited + 1))
done
cat "$result"
[ "$(plutil -extract delivered raw -o - "$result")" = true ]
