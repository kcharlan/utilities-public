#!/bin/zsh
set -euo pipefail
# Port: BV Tests/Snapshots/build.sh, 579ebb7. Compile maintained sources with
# a separate synthetic entry point, never the cloud composition or live check.
project_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
snapshot_home="$(mktemp -d "${TMPDIR:-/tmp}/prime-snapshots.XXXXXX")"
chmod 700 "$snapshot_home"
package_dir="$snapshot_home/package"
mkdir -p "$package_dir/Sources/PrimeMonitorCore" "$package_dir/Sources/Snapshots"
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
print -r -- "Snapshot executable: $binary_dir/Snapshots"
print -r -- "Private snapshots: $snapshot_home"
