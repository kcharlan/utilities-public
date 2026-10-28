.PHONY: build test test-suite clean

# SwiftPM writes package lock files and empty TemporaryDirectory.* folders to TMPDIR, so build and
# release keep them in the ignored .build/tmp/.
PROJECT_TMPDIR := $(CURDIR)/.build/tmp/
build release: export TMPDIR := $(PROJECT_TMPDIR)
# The repository's shared leak check (see the comment at its top). The suite runs under a private
# TMPDIR inside .build/tmp/, removed afterwards with the toolchain's leftovers, and fails on any
# brew-version entry it leaves in either temp dir. The harness builders keep their printed homes in
# TMPDIR on purpose, so they get --sweep-only. Every run removes its empty TemporaryDirectory.*
# markers from the Darwin user temp dir, which compiles write whatever TMPDIR says.
LEAK_CHECK := $(CURDIR)/../tools/check_no_temp_leaks.sh
TEMP_NAMES := (^|_)brew[-_]version[-_]
build:
	@mkdir -p "$(PROJECT_TMPDIR)"
	swift build

test:
	@mkdir -p "$(PROJECT_TMPDIR)"; TMPDIR="$(PROJECT_TMPDIR)" "$(LEAK_CHECK)" --names '$(TEMP_NAMES)' $(MAKE) --no-print-directory test-suite

test-suite:
	swift test
	node --test Tests/ReleaseChecks/*.test.mjs
	../tools/tests/test_check_no_temp_leaks.sh

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
	@"$(LEAK_CHECK)" --sweep-only --names '$(TEMP_NAMES)' Tests/Acceptance/build.sh

.PHONY: settings-prototype
settings-prototype:
	@"$(LEAK_CHECK)" --sweep-only --names '$(TEMP_NAMES)' Tests/Acceptance/build-settings-prototype.sh

.PHONY: snapshots
snapshots:
	@"$(LEAK_CHECK)" --sweep-only --names '$(TEMP_NAMES)' Tests/Snapshots/build.sh
