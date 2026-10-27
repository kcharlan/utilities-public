#!/bin/bash
set -euo pipefail
# Exercises tools/notification_check.sh with a temporary fake app and a fake launchctl
# first on its private PATH. The system launchctl is never invoked, HOME is a scratch
# directory, and every artifact is synthetic.
root=$(cd "$(dirname "$0")/../.." && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/telltale-check-test.XXXXXX")
chmod 700 "$scratch"
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin" "$scratch/home" "$scratch/tmp" "$scratch/work/Fake Telltale.app/Contents/MacOS" "$scratch/work/NoExecutable.app/Contents/MacOS"
printf '#!/bin/bash\nexit 0\n' > "$scratch/work/Fake Telltale.app/Contents/MacOS/Telltale"
chmod 755 "$scratch/work/Fake Telltale.app/Contents/MacOS/Telltale"

# The fake records every call and, on bootstrap, captures the plist and writes the
# synthetic result named by the plist's own --result argument.
cat > "$scratch/bin/launchctl" <<'MOCK'
#!/bin/bash
printf '%s\n' "$*" >> "$FAKE_LAUNCHCTL_LOG"
case "$1" in
bootout) exit 0 ;;
bootstrap)
    cp "$3" "$FAKE_CAPTURED_PLIST"
    case "${FAKE_RESULT:-delivered}" in
    none) ;;
    delivered|undelivered)
        path=$(plutil -extract ProgramArguments.3 raw -o - "$3")
        [ "${FAKE_RESULT:-delivered}" = delivered ] && flag=true || flag=false
        printf '{"authorization":"authorized","posted":true,"delivered":%s,"bundle":"synthetic.bundle","error":null}\n' "$flag" > "$path"
        ;;
    esac
    ;;
*) echo "unexpected launchctl call: $*" >&2; exit 99 ;;
esac
MOCK
chmod 755 "$scratch/bin/launchctl"
export PATH="$scratch/bin:$PATH" HOME="$scratch/home" TMPDIR="$scratch/tmp"
export FAKE_LAUNCHCTL_LOG="$scratch/launchctl.log" FAKE_CAPTURED_PLIST="$scratch/captured.plist"
uid=$(id -u)
physical_work=$(cd "$scratch/work" && pwd -P)
script="$root/tools/notification_check.sh"
fail() { echo "FAIL: $*" >&2; exit 1; }
plist_value() { plutil -extract "$1" raw -o - "$FAKE_CAPTURED_PLIST"; }
assert_clean() {
    [ -z "$(ls -A "$scratch/tmp")" ] || fail 'temporary directory was not removed'
    [ -z "$(ls -A "$scratch/home")" ] || fail 'script wrote into the home directory'
}

# Documented invocation: relative app path from the caller's working directory.
cd "$scratch/work"
output=$("$script" 'Fake Telltale.app' ui-not-running)
[[ "$output" == *'"delivered":true'* ]] || fail "result was not printed: $output"
[ "$(plist_value ProgramArguments.0)" = "$physical_work/Fake Telltale.app/Contents/MacOS/Telltale" ] || fail 'ProgramArguments[0] is not the absolute executable path'
[ "$(plist_value ProgramArguments.1)" = --notification-check ] || fail 'missing --notification-check'
[ "$(plist_value ProgramArguments.2)" = --result ] || fail 'missing --result'
case "$(plist_value ProgramArguments.3)" in "$scratch"/tmp/telltale-notification-check.*/result.json) ;; *) fail 'result path is not in a private temporary directory' ;; esac
[ "$(plist_value ProgramArguments.4)" = --mode ] || fail 'missing --mode'
[ "$(plist_value ProgramArguments.5)" = ui-not-running ] || fail 'wrong mode'
[ "$(plist_value Label)" = local.utilities.telltale.notification-check ] || fail 'wrong label'
[ "$(plist_value RunAtLoad)" = true ] || fail 'RunAtLoad is not set'
[ "$(plutil -extract ProgramArguments raw -o - "$FAKE_CAPTURED_PLIST")" = 6 ] || fail 'unexpected argument count'
# Order: stale bootout, bootstrap into this user's domain, bootout again on exit.
expected=$(printf 'bootout gui/%s/local.utilities.telltale.notification-check\nbootstrap gui/%s %s\nbootout gui/%s/local.utilities.telltale.notification-check\n' "$uid" "$uid" "$(dirname "$(plist_value ProgramArguments.3)")/local.utilities.telltale.notification-check.plist" "$uid")
[ "$(cat "$FAKE_LAUNCHCTL_LOG")" = "$expected" ] || fail "unexpected launchctl calls: $(cat "$FAKE_LAUNCHCTL_LOG")"
assert_clean

# Absolute app path and arguments needing plist escaping and spacing.
: > "$FAKE_LAUNCHCTL_LOG"
"$script" "$physical_work/Fake Telltale.app" 'a & b <c> "d"' > /dev/null
[ "$(plist_value ProgramArguments.5)" = 'a & b <c> "d"' ] || fail 'mode was not preserved as one plist string'
assert_clean

# A result with delivered=false prints it but fails.
: > "$FAKE_LAUNCHCTL_LOG"
if FAKE_RESULT=undelivered "$script" 'Fake Telltale.app' ui-running > "$scratch/out.log" 2>&1; then fail 'undelivered result accepted'; fi
rg -q '"delivered":false' "$scratch/out.log" || fail 'undelivered result was not printed'
assert_clean

# No result before the deadline fails and still cleans up.
: > "$FAKE_LAUNCHCTL_LOG"
if FAKE_RESULT=none TELLTALE_NOTIFICATION_CHECK_TIMEOUT=1 "$script" 'Fake Telltale.app' ui-running > "$scratch/out.log" 2>&1; then fail 'missing result accepted'; fi
rg -q 'No result within 1s' "$scratch/out.log" || fail 'timeout was not reported'
[ "$(tail -1 "$FAKE_LAUNCHCTL_LOG")" = "bootout gui/$uid/local.utilities.telltale.notification-check" ] || fail 'job was not booted out after timeout'
assert_clean

# Invalid bundles are rejected before launchctl is called or a plist is written.
for bad in 'Missing.app' 'NoExecutable.app' 'nodir/Missing.app'; do
    : > "$FAKE_LAUNCHCTL_LOG"
    if "$script" "$bad" ui-running > "$scratch/out.log" 2>&1; then fail "invalid app '$bad' accepted"; fi
    [ ! -s "$FAKE_LAUNCHCTL_LOG" ] || fail "launchctl called for invalid app '$bad'"
    assert_clean
done
if "$script" 'Fake Telltale.app' > "$scratch/out.log" 2>&1; then fail 'missing mode accepted'; fi
echo 'notification_check.sh checks passed (fake launchctl only)'
