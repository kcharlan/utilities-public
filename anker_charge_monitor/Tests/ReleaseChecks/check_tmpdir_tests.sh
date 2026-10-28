#!/bin/bash
set -euo pipefail
# The temporary-space check must flag only new prefixed leftovers and keep the
# wrapped suite's own failure status.
guard="$(cd "$(dirname "$0")" && pwd)/check_tmpdir.sh"
work=$(mktemp -d "${TMPDIR:-/tmp}/prime-tmpdir-tests.XXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir "$work/prime-synthetic-existing"
# Unprefixed names, such as this log, are outside the check.
log="$work/guard.log"
check() {
  local want=$1 code=0; shift
  TMPDIR="$work" "$guard" /bin/sh -c "$1" > "$log" 2>&1 || code=$?
  [ "$code" = "$want" ] || { echo "FAIL: expected $want, got $code for: $1"; exit 1; }
}
check 0 'mkdir "$TMPDIR/prime-synthetic-a"; rmdir "$TMPDIR/prime-synthetic-a"'
check 0 'mkdir "$TMPDIR/synthetic-other-project"'
check 1 'mkdir "$TMPDIR/prime-synthetic-leak"'
grep -q 'prime-synthetic-leak' "$log" && ! grep -q existing "$log" || { echo 'FAIL: leak report'; exit 1; }
check 3 'mkdir "$TMPDIR/prime-synthetic-failed"; exit 3'
grep -q 'prime-synthetic-failed' "$log" || { echo 'FAIL: leak report after failure'; exit 1; }
check 4 'exit 4'
echo 'PASS: temporary-space check regression suite'
