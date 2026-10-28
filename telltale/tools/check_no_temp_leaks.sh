#!/bin/bash
# Ruling R28: a test run leaves nothing in TMPDIR. Runs the given command with TMPDIR pointing at a
# private run directory under the real one, so the Swift toolchain's own leftovers (its
# `TemporaryDirectory.*` folders and package lock files) go with it, and removes that directory
# afterwards. Before removing it, fails if the run left a Telltale entry inside it, and afterwards
# fails if the run added one to the real TMPDIR directly. A Telltale entry is a name starting
# `telltale-` or a SwiftPM lock file naming a `telltale-*` directory
# (`..._T_telltale-bundle.XXXXXX_project_.build.lock`). Entries that existed before the run are
# not reported, and the command's own failure is passed through. `make test` wraps the whole suite
# in it; Tests/ReleaseChecks/test_check_no_temp_leaks.sh proves it catches a leak.
set -uo pipefail
if [ $# -eq 0 ]; then
    echo "usage: check_no_temp_leaks.sh command [argument ...]" >&2
    exit 2
fi
real="${TMPDIR:-/tmp}"
real="${real%/}"
entries() { ls -A "$1" 2>/dev/null | grep -E '(^|_)telltale-' | LC_ALL=C sort; return 0; }
before=$(entries "$real")
run=$(mktemp -d "$real/telltale-run.XXXXXX") || exit 1
chmod 700 "$run"
trap 'rm -rf "$run"' EXIT
TMPDIR="$run/" "$@"
status=$?
inside=$(entries "$run")
rm -rf "$run"
trap - EXIT
after=$(entries "$real")
outside=$(LC_ALL=C comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | sed '/^$/d')
report() {
    [ -n "$2" ] || return 0
    echo "check_no_temp_leaks: this run left these entries in $1:" >&2
    printf '%s\n' "$2" | sed 's/^/  /' >&2
    [ "$status" -ne 0 ] || status=1
}
report "its private TMPDIR" "$inside"
report "$real" "$outside"
exit "$status"
