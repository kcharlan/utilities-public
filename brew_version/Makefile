.PHONY: build test clean

build:
	swift build

test:
	swift test

clean:
	rm -rf .build build

.PHONY: release acceptance
release:
	swift build -c release --product brew-version
	swift build -c release --product BrewVersion
	mkdir -p "build/release/Brew Version.app/Contents/MacOS" "build/release/Brew Version.app/Contents/Resources"
	cp "$$(swift build -c release --show-bin-path)/brew-version" build/release/brew-version
	cp "$$(swift build -c release --show-bin-path)/BrewVersion" "build/release/Brew Version.app/Contents/MacOS/BrewVersion"
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
