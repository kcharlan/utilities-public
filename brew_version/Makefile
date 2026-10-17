.PHONY: build test clean

build:
	swift build

test:
	swift test
	node --test Tests/ReleaseChecks/*.test.mjs

clean:
	rm -rf .build build

.PHONY: release acceptance
release:
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
