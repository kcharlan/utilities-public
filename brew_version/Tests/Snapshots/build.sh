#!/bin/zsh
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
snapshot_home="$(mktemp -d)"
chmod 700 "$snapshot_home"
package_dir="$snapshot_home/package"
mkdir -p "$package_dir/Sources/BrewVersionCore" "$package_dir/Sources/Snapshots"
cp "$project_dir"/Sources/BrewVersionCore/*.swift "$package_dir/Sources/BrewVersionCore/"
for source in "$project_dir"/Sources/BrewVersion/*.swift; do
  case "${source:t}" in BrewVersionApp.swift|AppDelegate.swift) continue ;; esac
  cp "$source" "$package_dir/Sources/Snapshots/"
done
cp "$project_dir/Tests/Snapshots/Snapshots.swift" "$package_dir/Sources/Snapshots/"
cat > "$package_dir/Package.swift" <<'SWIFT'
// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "Snapshots", platforms: [.macOS("27.0")], targets: [.target(name: "BrewVersionCore"), .executableTarget(name: "Snapshots", dependencies: ["BrewVersionCore"])], swiftLanguageModes: [.v6])
SWIFT
swift build --package-path "$package_dir" -c release --product Snapshots
"$(swift build --package-path "$package_dir" -c release --show-bin-path)/Snapshots" "$snapshot_home"
print -r -- "Private snapshots: $snapshot_home"
