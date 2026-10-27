#!/bin/bash
set -euo pipefail
# Review check: Swift tests must not reach the real home, ~/Library or ~/.codex.
# Usage: check_test_isolation.sh [root]   (default: this package's Tests/)
# Exit 0: clean. Exit 1: forbidden patterns, printed as file:line. Exit 2: checker failure.
# Fake-runner expectations may keep /bin/launchctl literals; tests never execute them.
root=${1:-"$(cd "$(dirname "$0")/.." && pwd)"}
if [ ! -d "$root" ]; then echo "check_test_isolation: no such directory: $root" >&2; exit 2; fi
status=0
matches=$(rg --no-heading --line-number --no-ignore --glob '*.swift' \
    -e 'TelltalePaths\.live\(\)' \
    -e 'homeDirectoryForCurrentUser' \
    -e 'NSHomeDirectory\(' \
    -e '~/\.codex' \
    -e '~/Library' \
    -e '"/Users/' \
    "$root") || status=$?
case "$status" in
0)
    echo 'Tests must inject paths instead of reaching the real home:' >&2
    printf '%s\n' "$matches"
    exit 1 ;;
1) exit 0 ;;
*) echo "check_test_isolation: rg failed with status $status" >&2; exit 2 ;;
esac
