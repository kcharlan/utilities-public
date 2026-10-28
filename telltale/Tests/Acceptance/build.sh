#!/bin/zsh
set -euo pipefail
# Port: brew_version/Tests/Acceptance/build.sh, fbd3e03.
# Adaptation: Telltale's harness module names; the snapshot builder's production-source exclusions
# (TelltaleMain, AppDelegate, CollectorEntry, Registry, NotificationCheck) and recursive
# TelltaleCore copy; SyntheticEnvironment.swift replaces the Homebrew SyntheticTransport.swift;
# Telltale's release recipe (Info.plist and the bundled fonts in Resources, no Homebrew licence);
# bundle identifier com.example.telltale.acceptance, which LaunchAgentManager refuses; no
# --settings-prototype option. Ruling R28, as in Tests/Snapshots/build.sh: everything stays in
# the private home (TELLTALE_HARNESS_ROOT places it in a caller's scratch), and a manual run
# prints the command that removes it.
project_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
if (( $# != 0 )); then print -u2 -- "Unexpected builder arguments"; exit 2; fi
root="${TELLTALE_HARNESS_ROOT:-${TMPDIR:-/tmp}}"
[[ -d "$root" ]] || { print -u2 -- "TELLTALE_HARNESS_ROOT is not a directory: $root"; exit 2; }
acceptance_home="$(mktemp -d "${root%/}/telltale-acceptance.XXXXXX")"
chmod 700 "$acceptance_home"
package_dir="$acceptance_home/package"
mkdir -p "$package_dir/Sources/TelltaleCore" "$package_dir/Sources/Acceptance" "$acceptance_home/tmp"
cp -R "$project_dir/Sources/TelltaleCore/." "$package_dir/Sources/TelltaleCore/"
for source in "$project_dir"/Sources/Telltale/*.swift; do
  case "${source:t}" in TelltaleMain.swift|AppDelegate.swift|CollectorEntry.swift|Registry.swift|NotificationCheck.swift) continue ;; esac
  cp "$source" "$package_dir/Sources/Acceptance/"
done
if rg -n '^import ' "$package_dir/Sources" | rg -v 'import (Foundation|AppKit|SwiftUI|Charts|Observation|Darwin|Synchronization|SQLite3|UserNotifications|TelltaleCore)$'; then
  print -u2 'Unsupported import in maintained acceptance sources'; exit 1
fi
cp "$project_dir/Tests/Acceptance/AcceptanceApp.swift" "$project_dir/Tests/Acceptance/SyntheticEnvironment.swift" "$package_dir/Sources/Acceptance/"
mkdir -p "$package_dir/Tests/AcceptanceServiceTests"
cp "$project_dir/Tests/Acceptance/AcceptanceServiceTests.swift" "$package_dir/Tests/AcceptanceServiceTests/"
cat > "$package_dir/Package.swift" <<'SWIFT'
// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "Acceptance", platforms: [.macOS("27.0")], products: [.executable(name: "Acceptance", targets: ["Acceptance"])], targets: [.target(name: "TelltaleCore"), .executableTarget(name: "Acceptance", dependencies: ["TelltaleCore"]), .testTarget(name: "AcceptanceServiceTests", dependencies: ["Acceptance", "TelltaleCore"])], swiftLanguageModes: [.v6])
SWIFT
# SwiftPM's lock files and the service tests' scratch directories stay in the home.
export TMPDIR="$acceptance_home/tmp"
swift test --package-path "$package_dir" -Xswiftc -warnings-as-errors
swift build --package-path "$package_dir" -c release --product Acceptance -Xswiftc -warnings-as-errors
app="$acceptance_home/Telltale Synthetic Acceptance.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
mkdir -p "$app/Contents/Resources/Fonts"
cp -p "$project_dir"/Resources/Fonts/*.ttf "$project_dir/Resources/Fonts/OFL.txt" "$app/Contents/Resources/Fonts/"
cp "$(swift build --package-path "$package_dir" -c release -Xswiftc -warnings-as-errors --show-bin-path)/Acceptance" "$app/Contents/MacOS/Acceptance"
cp "$project_dir/Resources/Info.plist" "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier com.example.telltale.acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleName Telltale Synthetic Acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleDisplayName Telltale Synthetic Acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleExecutable Acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :SyntheticAcceptanceHome string $acceptance_home" "$app/Contents/Info.plist"
codesign --force --sign - --timestamp=none "$app"
codesign --verify --strict "$app"
print -r -- "Acceptance app: $app"
print -r -- "Private synthetic home: $acceptance_home"
print -r -- "Remove with: rm -r -- ${(q)acceptance_home}"
