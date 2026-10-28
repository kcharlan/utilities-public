#!/bin/bash
set -euo pipefail
# Proves tools/check_no_temp_leaks.sh (ruling R28) catches a leak, against a private fake TMPDIR
# inside this script's own scratch, which the trap removes.
root=$(cd "$(dirname "$0")/../.." && pwd)
checker="$root/tools/check_no_temp_leaks.sh"
scratch=$(mktemp -d "${TMPDIR:-/tmp}/telltale-leak-test.XXXXXX")
chmod 700 "$scratch"
trap 'rm -rf "$scratch"' EXIT
fake="$scratch/tmp"
mkdir "$fake"
export OUTER="$fake"
expect_pass() { if ! TMPDIR="$fake" "$checker" "$@" > "$scratch/out.log" 2>&1; then echo "FAIL: reported a clean run: $*"; cat "$scratch/out.log"; exit 1; fi; }
expect_leak() {
    local name=$1; shift
    if TMPDIR="$fake" "$checker" "$@" > "$scratch/out.log" 2>&1; then echo "FAIL: missed leak $name"; exit 1; fi
    grep -qF "  $name" "$scratch/out.log" || { echo "FAIL: leak $name not named"; cat "$scratch/out.log"; exit 1; }
}

expect_pass true
# The command runs with a private TMPDIR, removed afterwards with whatever the toolchain left.
expect_pass sh -c 'case "$TMPDIR" in "$OUTER"/telltale-run.*) mkdir "$TMPDIR/TemporaryDirectory.AbCdEf" ;; *) exit 1 ;; esac'
[ -z "$(ls -A "$fake")" ] || { echo "FAIL: the private TMPDIR was not removed"; ls -A "$fake"; exit 1; }
# A directory created and removed within the run is not a leak; neither is another tool's entry.
expect_pass sh -c 'mkdir "$TMPDIR/telltale-tests-transient" && rmdir "$TMPDIR/telltale-tests-transient"'
expect_pass sh -c 'mkdir "$OUTER/other-tool.XXXX"'
# A test or script that leaves its scratch in TMPDIR, or a package build's lock file.
expect_leak telltale-zstd-tests-0001 sh -c 'mkdir "$TMPDIR/telltale-zstd-tests-0001"'
expect_leak _private_var_T_telltale-bundle.AbCdEf_project_.build.lock \
    sh -c ': > "$TMPDIR/_private_var_T_telltale-bundle.AbCdEf_project_.build.lock"'
# Something written to the real TMPDIR directly.
expect_leak telltale-snapshots.Qr34St sh -c 'mkdir "$OUTER/telltale-snapshots.Qr34St"'
# Entries from before the run are not this run's leaks.
expect_pass true
# A failing command still fails with its own status, and its leak is still named.
if TMPDIR="$fake" "$checker" sh -c 'mkdir "$TMPDIR/telltale-acceptance.Xy12Zw"; exit 7' > "$scratch/out.log" 2>&1; then
    echo "FAIL: a failing command passed"; exit 1
else
    [ $? -eq 7 ] || { echo "FAIL: the command's status was not passed through"; exit 1; }
fi
grep -qF '  telltale-acceptance.Xy12Zw' "$scratch/out.log" || { echo "FAIL: leak from a failing run not named"; exit 1; }
if TMPDIR="$fake" "$checker" > /dev/null 2>&1; then echo "FAIL: no command accepted"; exit 1; fi
echo 'check_no_temp_leaks.sh checks passed'
