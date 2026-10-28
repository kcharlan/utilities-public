#!/bin/zsh
set -euo pipefail
# Port: BV Tests/Snapshots/build.sh, 579ebb7. Compile maintained sources with
# a separate synthetic entry point, never the cloud composition or live check.
project_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
# A caller that removes its own scratch passes PRIME_MONITOR_HARNESS_HOME, a new
# path inside that scratch, and the builder keeps everything there. Otherwise the
# builder owns a fresh home: it keeps only the PNGs, or nothing after a failure.
if [[ -n "${PRIME_MONITOR_HARNESS_HOME:-}" ]]; then
  snapshot_home="$PRIME_MONITOR_HARNESS_HOME"
  mkdir -m 700 -- "$snapshot_home"
  owned=false
else
  snapshot_home="$(mktemp -d "${${TMPDIR:-/tmp}%/}/prime-snapshots.XXXXXX")"
  owned=true
fi
package_dir="$snapshot_home/package"
finish() {
  local code=$?
  if $owned; then
    if (( code )); then rm -rf -- "$snapshot_home"
    else rm -rf -- "$package_dir"; find "$snapshot_home" -mindepth 1 -maxdepth 1 -type d -exec rm -rf -- {} +; fi
  fi
  return $code
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
chmod 700 "$snapshot_home"
# SwiftPM writes package lock files and TemporaryDirectory.* folders to TMPDIR; keep them in the
# home, in a directory the finish trap removes with the scratch package.
mkdir -p "$package_dir/Sources/PrimeMonitorCore" "$package_dir/Sources/Snapshots" "$snapshot_home/tmp"
export TMPDIR="$snapshot_home/tmp/"
cp "$project_dir"/Sources/PrimeMonitorCore/*.swift "$package_dir/Sources/PrimeMonitorCore/"
for source in "$project_dir"/Sources/PrimeMonitor/*.swift; do
  case "${source:t}" in PrimeMonitorApp.swift|AppDelegate.swift|LiveCheck.swift) continue ;; esac
  cp "$source" "$package_dir/Sources/Snapshots/"
done
if rg -n '^import ' "$package_dir/Sources" | rg -v 'import (Foundation|AppKit|SwiftUI|Observation|ServiceManagement|Network|Darwin|PrimeMonitorCore)$'; then
  print -u2 'Unsupported import in maintained snapshot sources'; exit 1
fi
cp "$project_dir/Tests/Snapshots/Snapshots.swift" "$package_dir/Sources/Snapshots/"
cat > "$package_dir/Package.swift" <<'SWIFT'
// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "Snapshots", platforms: [.macOS("27.0")], targets: [.target(name: "PrimeMonitorCore"), .executableTarget(name: "Snapshots", dependencies: ["PrimeMonitorCore"])], swiftLanguageModes: [.v6])
SWIFT
swift build --package-path "$package_dir" -c release --product Snapshots -Xswiftc -warnings-as-errors
binary_dir="$(swift build --package-path "$package_dir" -c release --show-bin-path)"
"$binary_dir/Snapshots" "$snapshot_home"
print -r -- "Private snapshots: $snapshot_home"
if $owned; then print -r -- "Remove when finished: rm -r -- ${(q)snapshot_home}"
else print -r -- "Snapshot executable: $binary_dir/Snapshots"; fi
