#!/bin/zsh
set -euo pipefail
# Port: brew_version/Tests/Snapshots/build.sh, 579ebb7 (by way of anker_charge_monitor's port).
# Adaptation: compiles the maintained panel sources with a separate synthetic entry point. The
# production lifecycle owners (TelltaleMain, AppDelegate), the collector entry, the source
# registry (live Codex and status plugins) and the notification check stay out; TelltaleCore is
# copied recursively so its nested layout is preserved. The seeded scenes come from
# Tests/Acceptance/SyntheticEnvironment.swift, shared with the acceptance builder.
# Ruling R28: everything this build writes stays in its private home, SwiftPM's temporary lock
# files included. TELLTALE_HARNESS_ROOT (an existing directory under the OS temporary directory)
# places the home inside a caller's scratch, which check_harnesses.sh removes; a manual run keeps
# the home for inspection and prints the command that removes it.
project_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
root="${TELLTALE_HARNESS_ROOT:-${TMPDIR:-/tmp}}"
[[ -d "$root" ]] || { print -u2 -- "TELLTALE_HARNESS_ROOT is not a directory: $root"; exit 2; }
snapshot_home="$(mktemp -d "${root%/}/telltale-snapshots.XXXXXX")"
chmod 700 "$snapshot_home"
package_dir="$snapshot_home/package"
mkdir -p "$package_dir/Sources/TelltaleCore" "$package_dir/Sources/Snapshots" "$snapshot_home/tmp"
cp -R "$project_dir/Sources/TelltaleCore/." "$package_dir/Sources/TelltaleCore/"
for source in "$project_dir"/Sources/Telltale/*.swift; do
  case "${source:t}" in TelltaleMain.swift|AppDelegate.swift|CollectorEntry.swift|Registry.swift|NotificationCheck.swift) continue ;; esac
  cp "$source" "$package_dir/Sources/Snapshots/"
done
if rg -n '^import ' "$package_dir/Sources" | rg -v 'import (Foundation|AppKit|SwiftUI|Charts|Observation|Darwin|Synchronization|SQLite3|UserNotifications|TelltaleCore)$'; then
  print -u2 'Unsupported import in maintained snapshot sources'; exit 1
fi
cp "$project_dir/Tests/Snapshots/Snapshots.swift" "$project_dir/Tests/Acceptance/SyntheticEnvironment.swift" "$package_dir/Sources/Snapshots/"
# The bundled readout fonts, registered by the snapshot executable from the home.
mkdir -p "$snapshot_home/Fonts"
cp "$project_dir"/Resources/Fonts/*.ttf "$project_dir/Resources/Fonts/OFL.txt" "$snapshot_home/Fonts/"
cat > "$package_dir/Package.swift" <<'SWIFT'
// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "Snapshots", platforms: [.macOS("27.0")], targets: [.target(name: "TelltaleCore"), .executableTarget(name: "Snapshots", dependencies: ["TelltaleCore"])], swiftLanguageModes: [.v6])
SWIFT
# SwiftPM writes its package lock files to TMPDIR; keep them in the home.
TMPDIR="$snapshot_home/tmp" swift build --package-path "$package_dir" -c release --product Snapshots -Xswiftc -warnings-as-errors
binary_dir="$(TMPDIR="$snapshot_home/tmp" swift build --package-path "$package_dir" -c release --show-bin-path)"
"$binary_dir/Snapshots" "$snapshot_home"
print -r -- "Snapshot executable: $binary_dir/Snapshots"
print -r -- "Private snapshots: $snapshot_home"
print -r -- "Remove with: rm -r -- ${(q)snapshot_home}"
