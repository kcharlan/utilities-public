.PHONY: build test test-suite clean

# SwiftPM writes package lock files and empty TemporaryDirectory.* folders to TMPDIR, so build and
# release keep them in the ignored .build/tmp/.
PROJECT_TMPDIR := $(CURDIR)/.build/tmp/
build release: export TMPDIR := $(PROJECT_TMPDIR)
build:
	@mkdir -p "$(PROJECT_TMPDIR)"
	swift build

# The leak check wraps the whole suite and fails on anything it leaves in
# temporary space.
test:
	Tests/ReleaseChecks/check_tmpdir.sh $(MAKE) --no-print-directory test-suite

test-suite:
	swift test
	node --test Tests/ReleaseChecks/*.test.mjs

clean:
	rm -rf .build build

.PHONY: release acceptance
release:
	@mkdir -p "$(PROJECT_TMPDIR)"
	swift build -c release --product brew-version
	swift build -c release --product BrewVersion
	if [ -e "build/release/Brew Version.app" ]; then rm -r -- "build/release/Brew Version.app"; fi
	mkdir -p "build/release/Brew Version.app/Contents/MacOS" "build/release/Brew Version.app/Contents/Resources"
	command_tmp=$$(mktemp build/release/.brew-version.XXXXXX); \
		cp -p "$$(swift build -c release --show-bin-path)/brew-version" "$$command_tmp" && mv "$$command_tmp" build/release/brew-version
	app_tmp=$$(mktemp "build/release/Brew Version.app/Contents/MacOS/.BrewVersion.XXXXXX"); \
		cp -p "$$(swift build -c release --show-bin-path)/BrewVersion" "$$app_tmp" && mv "$$app_tmp" "build/release/Brew Version.app/Contents/MacOS/BrewVersion"
	cp Resources/Info.plist "build/release/Brew Version.app/Contents/Info.plist"
	cp Resources/Homebrew-LICENSE.txt "build/release/Brew Version.app/Contents/Resources/Homebrew-LICENSE.txt"
	codesign --force --sign - --timestamp=none build/release/brew-version
	codesign --force --sign - --timestamp=none "build/release/Brew Version.app"
	codesign --verify --strict build/release/brew-version
	codesign --verify --strict "build/release/Brew Version.app"

acceptance:
	Tests/Acceptance/build.sh

.PHONY: settings-prototype
settings-prototype:
	Tests/Acceptance/build-settings-prototype.sh

.PHONY: snapshots
snapshots:
	Tests/Snapshots/build.sh
