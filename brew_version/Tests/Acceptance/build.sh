#!/bin/zsh
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
prototype=false
if [[ "${1:-}" == --settings-prototype && $# == 1 ]]; then prototype=true
elif (( $# != 0 )); then print -u2 -- "Unexpected builder arguments"; exit 2; fi
# A caller that removes its own scratch passes BREW_VERSION_HARNESS_HOME, a new
# path inside that scratch, and the builder keeps everything there. Otherwise the
# builder owns a fresh home: it keeps the signed bundle and its synthetic state
# and removes the scratch package, or removes everything after a failure.
if [[ -n "${BREW_VERSION_HARNESS_HOME:-}" ]]; then
  acceptance_home="$BREW_VERSION_HARNESS_HOME"
  mkdir -m 700 -- "$acceptance_home"
  owned=false
else
  acceptance_home="$(mktemp -d "${${TMPDIR:-/tmp}%/}/brew-version-acceptance.XXXXXX")"
  owned=true
fi
package_dir="$acceptance_home/package"
build_tmp="$acceptance_home/tmp"
finish() {
  local code=$?
  if $owned; then
    if (( code )); then rm -rf -- "$acceptance_home"; else rm -rf -- "$package_dir" "$build_tmp"; fi
  fi
  return $code
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
chmod 700 "$acceptance_home"
# SwiftPM writes package lock files and TemporaryDirectory.* folders to TMPDIR; keep them in the
# home, removed with the scratch package.
mkdir -p "$package_dir/Sources/BrewVersionCore" "$package_dir/Sources/Acceptance" "$build_tmp"
export TMPDIR="$build_tmp/"
cp "$project_dir"/Sources/BrewVersionCore/*.swift "$package_dir/Sources/BrewVersionCore/"
for source in "$project_dir"/Sources/BrewVersion/*.swift; do
  case "${source:t}" in BrewVersionApp.swift|AppDelegate.swift) continue ;; esac
  cp "$source" "$package_dir/Sources/Acceptance/"
done
entry=AcceptanceApp.swift
if $prototype; then entry=SettingsPrototype.swift; fi
cp "$project_dir/Tests/Acceptance/$entry" "$project_dir/Tests/Acceptance/SyntheticTransport.swift" "$project_dir/Tests/Acceptance/SyntheticEnvironment.swift" "$package_dir/Sources/Acceptance/"
mkdir -p "$package_dir/Tests/AcceptanceServiceTests"
cp "$project_dir/Tests/Acceptance/AcceptanceServiceTests.swift" "$package_dir/Tests/AcceptanceServiceTests/"
cat > "$package_dir/Package.swift" <<'SWIFT'
// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "Acceptance", platforms: [.macOS("27.0")], products: [.executable(name: "Acceptance", targets: ["Acceptance"])], targets: [.target(name: "BrewVersionCore"), .executableTarget(name: "Acceptance", dependencies: ["BrewVersionCore"]), .testTarget(name: "AcceptanceServiceTests", dependencies: ["Acceptance", "BrewVersionCore"])], swiftLanguageModes: [.v6])
SWIFT
if ! $prototype; then swift test --package-path "$package_dir"; fi
swift build --package-path "$package_dir" -c release --product Acceptance
app="$acceptance_home/Brew Version Synthetic Acceptance.app"
if $prototype; then app="$acceptance_home/Settings Prototype.app"; fi
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$(swift build --package-path "$package_dir" -c release --show-bin-path)/Acceptance" "$app/Contents/MacOS/Acceptance"
cp "$project_dir/Resources/Info.plist" "$app/Contents/Info.plist"
cp "$project_dir/Resources/Homebrew-LICENSE.txt" "$app/Contents/Resources/"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier local.utilities.brew-version.synthetic-acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleName Brew Version Synthetic Acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleExecutable Acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :SyntheticAcceptanceHome string $acceptance_home" "$app/Contents/Info.plist"
if $prototype; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier local.utilities.brew-version.settings-prototype" "$app/Contents/Info.plist"
    /usr/libexec/PlistBuddy -c "Set :CFBundleName Settings Prototype" "$app/Contents/Info.plist"
fi
codesign --force --sign - --timestamp=none "$app"
codesign --verify --strict "$app"
if $prototype; then print -r -- "Settings prototype: $app"
else print -r -- "Acceptance app: $app"; fi
print -r -- "Private synthetic home: $acceptance_home"
if $owned; then print -r -- "Remove when finished: rm -r -- ${(q)acceptance_home}"; fi
