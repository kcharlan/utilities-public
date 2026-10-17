#!/bin/zsh
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
acceptance_home="$(mktemp -d)"
chmod 700 "$acceptance_home"
package_dir="$acceptance_home/package"
mkdir -p "$package_dir/Sources/BrewVersionCore" "$package_dir/Sources/Acceptance"
cp "$project_dir"/Sources/BrewVersionCore/*.swift "$package_dir/Sources/BrewVersionCore/"
for source in "$project_dir"/Sources/BrewVersion/*.swift; do
  case "${source:t}" in BrewVersionApp.swift|AppDelegate.swift) continue ;; esac
  cp "$source" "$package_dir/Sources/Acceptance/"
done
cp "$project_dir/Tests/Acceptance/AcceptanceApp.swift" "$project_dir/Tests/Acceptance/SyntheticTransport.swift" "$package_dir/Sources/Acceptance/"
mkdir -p "$package_dir/Tests/AcceptanceServiceTests"
cp "$project_dir/Tests/Acceptance/AcceptanceServiceTests.swift" "$package_dir/Tests/AcceptanceServiceTests/"
cat > "$package_dir/Package.swift" <<'SWIFT'
// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "Acceptance", platforms: [.macOS(.v14)], products: [.executable(name: "Acceptance", targets: ["Acceptance"])], targets: [.target(name: "BrewVersionCore"), .executableTarget(name: "Acceptance", dependencies: ["BrewVersionCore"]), .testTarget(name: "AcceptanceServiceTests", dependencies: ["Acceptance", "BrewVersionCore"])], swiftLanguageModes: [.v6])
SWIFT
swift test --package-path "$package_dir"
swift build --package-path "$package_dir" -c release --product Acceptance
app="$acceptance_home/Brew Version Synthetic Acceptance.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$(swift build --package-path "$package_dir" -c release --show-bin-path)/Acceptance" "$app/Contents/MacOS/Acceptance"
cp "$project_dir/Resources/Info.plist" "$app/Contents/Info.plist"
cp "$project_dir/Resources/Homebrew-LICENSE.txt" "$app/Contents/Resources/"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier local.utilities.brew-version.synthetic-acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleName Brew Version Synthetic Acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleExecutable Acceptance' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :SyntheticAcceptanceHome string $acceptance_home" "$app/Contents/Info.plist"
codesign --force --sign - --timestamp=none "$app"
codesign --verify --strict "$app"
print -r -- "Acceptance app: $app"
print -r -- "Private synthetic home: $acceptance_home"
