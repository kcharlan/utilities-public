#!/bin/bash
set -euo pipefail
# Tests check_test_isolation.sh against temporary synthetic Swift trees.
root=$(cd "$(dirname "$0")/../.." && pwd)
checker="$root/Tests/ReleaseChecks/check_test_isolation.sh"
scratch=$(mktemp -d "${TMPDIR:-/tmp}/telltale-isolation-test.XXXXXX")
chmod 700 "$scratch"
trap 'rm -rf "$scratch"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# Each forbidden pattern is reported with file:line and a nonzero exit.
n=0
while IFS= read -r line; do
    n=$((n + 1))
    dir="$scratch/forbidden-$n"; mkdir -p "$dir/Nested"
    printf 'import Foundation\n\n%s\n' "$line" > "$dir/Nested/Case.swift"
    status=0; output=$("$checker" "$dir" 2>/dev/null) || status=$?
    [ "$status" = 1 ] || fail "pattern not rejected (status $status): $line"
    [[ "$output" == *"Nested/Case.swift:3"* ]] || fail "file:line not reported for: $line"
done <<'CASES'
let paths = TelltalePaths.live()
let home = FileManager.default.homeDirectoryForCurrentUser
let home = NSHomeDirectory()
let codex = "~/.codex/sessions"
let library = "~/Library/Logs"
let absolute = "/Users/someone/project"
let login = LoginItem()
let item = LoginItem( )
let status = SMAppService.mainApp.status
let appService: SMAppService.Status = .enabled
let defaults = UserDefaults.standard
CASES

# Permitted injected-path code and /bin/launchctl literals pass.
mkdir -p "$scratch/permitted"
cat > "$scratch/permitted/Case.swift" <<'SWIFT'
import Foundation
let environment = ["CODEX_HOME": "/tmp/synthetic-codex"]
let paths = TelltalePaths.live(environment: environment)
let injected = TelltalePaths(home: URL(fileURLWithPath: "/tmp/synthetic-home", isDirectory: true))
let expectedExecutable = "/bin/launchctl"
let login = LoginItem(service: LoginServiceStub())
let status: LoginStatus = .notRegistered
let record = PreferencesLaunchRecord(preferences: MemoryPreferences())
let suite = MyLoginItem()
SWIFT
"$checker" "$scratch/permitted" || fail 'permitted injected-path code was rejected'

# Only Swift files are scanned: shell scripts and other files may mention the patterns.
mkdir -p "$scratch/non-swift"
printf 'TelltalePaths.live()\nhomeDirectoryForCurrentUser\n' > "$scratch/non-swift/notes.sh"
"$checker" "$scratch/non-swift" || fail 'non-Swift file was scanned'

# A missing root is a checker failure (2), not a clean result.
status=0; "$checker" "$scratch/does-not-exist" 2>/dev/null || status=$?
[ "$status" = 2 ] || fail "missing root should exit 2, got $status"

# The package's own tests are clean.
"$checker" || fail 'package tests contain forbidden patterns'
echo 'check_test_isolation.sh checks passed'
