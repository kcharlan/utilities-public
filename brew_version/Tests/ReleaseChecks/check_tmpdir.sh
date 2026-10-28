#!/bin/bash
set -euo pipefail
# Runs a suite and fails if it leaves new entries with this project's temporary
# prefix behind, whether or not the suite passed. Shell tools honor $TMPDIR, while
# Foundation's temporaryDirectory uses the per-user directory, so both are watched.
# A concurrent run of this project's suite can trip it; run one at a time.
prefix=brew-version-
[ "$#" -gt 0 ] || { echo 'usage: check_tmpdir.sh command [argument ...]' >&2; exit 2; }
candidates=("${TMPDIR:-/tmp}")
if user_tmp=$(getconf DARWIN_USER_TEMP_DIR 2>/dev/null); then candidates+=("$user_tmp"); fi
roots=()
while IFS= read -r root; do roots+=("$root"); done < <(
  for candidate in "${candidates[@]}"; do
    if [ -d "$candidate" ]; then (cd "$candidate" && pwd -P); fi
  done | LC_ALL=C sort -u)
entries() {
  local root
  for root in "${roots[@]}"; do find "$root" -mindepth 1 -maxdepth 1 -name "$prefix*" -print; done | LC_ALL=C sort
}
before=$(entries)
status=0
"$@" || status=$?
leaked=$(LC_ALL=C comm -13 <(printf '%s\n' "$before") <(entries) | sed '/^$/d')
if [ -n "$leaked" ]; then
  printf 'FAIL: the suite left temporary entries behind:\n%s\n' "$leaked" >&2
  [ "$status" != 0 ] || status=1
fi
exit "$status"
