#!/bin/zsh
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
# A caller that removes its own scratch passes BREW_VERSION_HARNESS_HOME, a new
# path inside that scratch, and the builder keeps everything there. Otherwise the
# builder owns a fresh home: it keeps only the PNGs, or nothing after a failure.
if [[ -n "${BREW_VERSION_HARNESS_HOME:-}" ]]; then
  snapshot_home="$BREW_VERSION_HARNESS_HOME"
  mkdir -m 700 -- "$snapshot_home"
  owned=false
else
  snapshot_home="$(mktemp -d "${${TMPDIR:-/tmp}%/}/brew-version-snapshots.XXXXXX")"
  owned=true
fi
package_dir="$snapshot_home/package"
build_tmp="$snapshot_home/tmp"
finish() {
  local code=$?
  if $owned; then
    if (( code )); then rm -rf -- "$snapshot_home"
    else rm -rf -- "$package_dir" "$build_tmp" "$snapshot_home"/fixture-*(N); fi
  fi
  return $code
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
chmod 700 "$snapshot_home"
# SwiftPM writes package lock files and TemporaryDirectory.* folders to TMPDIR; keep them in the
# home, removed with the scratch package.
mkdir -p "$package_dir/Sources/BrewVersionCore" "$package_dir/Sources/Snapshots" "$build_tmp"
export TMPDIR="$build_tmp/"
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
if $owned; then print -r -- "Remove when finished: rm -r -- ${(q)snapshot_home}"; fi
