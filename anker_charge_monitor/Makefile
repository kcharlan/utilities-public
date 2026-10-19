# App-only release adapted from brew_version/Makefile at 579ebb7.
SIGN_IDENTITY ?= CodexBar Local
export SIGN_IDENTITY
.PHONY: build test snapshots clean release install deploy live-check signing-preflight
build:
	swift build -Xswiftc -warnings-as-errors
test:
	swift test -Xswiftc -warnings-as-errors
	Tests/ReleaseChecks/check_secrets_tests.sh
	Tests/ReleaseChecks/check_bundle.sh
clean:
	rm -rf .build build
snapshots:
	Tests/Snapshots/build.sh
signing-preflight:
	@tools/resolve_signing_identity.sh "$$SIGN_IDENTITY"
release:
	@set -e; identity=$$(tools/resolve_signing_identity.sh "$$SIGN_IDENTITY"); \
		swift build -c release --product PrimeMonitor -Xswiftc -warnings-as-errors; \
		if [ -e "build/release/Anker Charge Monitor.app" ]; then rm -r -- "build/release/Anker Charge Monitor.app"; fi; \
		mkdir -p "build/release/Anker Charge Monitor.app/Contents/MacOS" "build/release/Anker Charge Monitor.app/Contents/Resources"; \
		app_tmp=$$(mktemp "build/release/Anker Charge Monitor.app/Contents/MacOS/.PrimeMonitor.XXXXXX"); \
		cp -p "$$(swift build -c release -Xswiftc -warnings-as-errors --show-bin-path)/PrimeMonitor" "$$app_tmp"; \
		mv "$$app_tmp" "build/release/Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor"; \
		cp Resources/Info.plist "build/release/Anker Charge Monitor.app/Contents/Info.plist"; \
		codesign --force --sign "$$identity" --timestamp=none "build/release/Anker Charge Monitor.app"; \
		codesign --verify --strict "build/release/Anker Charge Monitor.app"
install deploy:
	node ../tools/deploy_anker_charge_monitor.mjs
live-check:
	"/Applications/Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor" --live-check
