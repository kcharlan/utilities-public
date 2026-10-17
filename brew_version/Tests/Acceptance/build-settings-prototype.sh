#!/bin/zsh
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
prototype_home="$(mktemp -d "$HOME/.brew-version-settings-prototype.XXXXXX")"
chmod 700 "$prototype_home"
app="$prototype_home/Settings Prototype.app"
mkdir -p "$app/Contents/MacOS"
swiftc -parse-as-library -target "$(uname -m)-apple-macos14.0" "$project_dir/Tests/Acceptance/SettingsPrototype.swift" -o "$app/Contents/MacOS/Prototype"
cp "$project_dir/Resources/Info.plist" "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleExecutable Prototype' "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier local.utilities.brew-version.settings-prototype' "$app/Contents/Info.plist"
codesign --force --sign - --timestamp=none "$app"
codesign --verify --strict "$app"
print -r -- "Settings prototype: $app"
