#!/bin/bash
set -euo pipefail
# Port: anker_charge_monitor/Tests/ReleaseChecks/check_bundle.sh, maintained-snapshot runtime block
# (itself BV release.test.mjs, "maintained snapshot builder uses the same supported runtime"), 4f965e8.
# Adaptation: Telltale's builders, run from the project. Ruling R28: both build inside this
# script's scratch (TELLTALE_HARNESS_ROOT), which the trap removes on success and failure, so a
# suite run leaves nothing in TMPDIR; run `make snapshots` by hand to keep PNGs to look at. The
# synthetic acceptance build (with its generated service tests) runs here too, and its executable
# must carry the same supported runtime. PNG inspection and real-click acceptance stay README checks.
root=$(cd "$(dirname "$0")/../.." && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/telltale-harnesses.XXXXXX")
chmod 700 "$scratch"
trap 'code=$?; if [ "$code" != 0 ]; then tail -20 "$scratch"/*.log 2>/dev/null || true; fi; rm -rf "$scratch"' EXIT
cd "$root"
export TELLTALE_HARNESS_ROOT="$scratch"

make snapshots > "$scratch/snapshots.log" 2>&1
grep -v '^\[' "$scratch/snapshots.log" | grep -E '\.png |^Validated|^Snapshot executable|^Private snapshots'
snapshot_binary=$(sed -n 's/^Snapshot executable: //p' "$scratch/snapshots.log")
[ -x "$snapshot_binary" ]
vtool -show-build "$snapshot_binary" | grep -Eq '\bminos 27\.0\b'
vtool -show-build "$snapshot_binary" | grep -Eq '\bsdk 27\.0\b'
[ "$(grep -c '\.png (340 × ' "$scratch/snapshots.log")" = 6 ]
[ "$(grep -c '\.png (1100 × ' "$scratch/snapshots.log")" = 4 ]

make acceptance > "$scratch/acceptance.log" 2>&1
grep -Eq 'Test run with [0-9]+ tests? in [0-9]+ suites? passed' "$scratch/acceptance.log"
grep -E '^Acceptance app|^Private synthetic home' "$scratch/acceptance.log"
app=$(sed -n 's/^Acceptance app: //p' "$scratch/acceptance.log")
[ -d "$app" ]
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Contents/Info.plist")" = com.example.telltale.acceptance ]
codesign --verify --strict "$app"
vtool -show-build "$app/Contents/MacOS/Acceptance" | grep -Eq '\bminos 27\.0\b'
vtool -show-build "$app/Contents/MacOS/Acceptance" | grep -Eq '\bsdk 27\.0\b'
case "$snapshot_binary" in "$scratch"/*|"$(cd "$scratch" && pwd -P)"/*) ;; *) echo "FAIL: snapshot build outside the scratch: $snapshot_binary"; exit 1 ;; esac
case "$app" in "$scratch"/*) ;; *) echo "FAIL: acceptance build outside the scratch: $app"; exit 1 ;; esac
echo 'snapshot and acceptance harness checks passed (synthetic only; built in a removed scratch; PNGs and native clicks are inspected separately)'
