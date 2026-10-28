# App-only release adapted from brew_version/Makefile at 579ebb7.
SIGN_IDENTITY ?= CodexBar Local
export SIGN_IDENTITY
.PHONY: build test test-suite snapshots clean release install deploy live-check signing-preflight
# SwiftPM writes package lock files and empty TemporaryDirectory.* folders to TMPDIR, so build and
# release keep them in the ignored .build/tmp/. release creates it only after the
# identity resolves, so a missing one leaves no .build behind.
PROJECT_TMPDIR := $(CURDIR)/.build/tmp/
build release: export TMPDIR := $(PROJECT_TMPDIR)
# The repository's shared leak check (see the comment at its top). The suite runs under a private
# TMPDIR inside .build/tmp/, removed afterwards with the toolchain's leftovers, and fails on any
# prime- or anker_charge_monitor entry it leaves in either temp dir. The snapshot builder keeps its
# printed home in TMPDIR on purpose, so it gets --sweep-only. Every run removes its empty
# TemporaryDirectory.* markers from the Darwin user temp dir, which compiles write whatever TMPDIR
# says.
LEAK_CHECK := $(CURDIR)/../tools/check_no_temp_leaks.sh
TEMP_NAMES := (^|_)(prime|anker[-_]charge[-_]monitor)[-_]
build:
	@mkdir -p "$(PROJECT_TMPDIR)"
	swift build -Xswiftc -warnings-as-errors
test:
	@mkdir -p "$(PROJECT_TMPDIR)"; TMPDIR="$(PROJECT_TMPDIR)" "$(LEAK_CHECK)" --names '$(TEMP_NAMES)' $(MAKE) --no-print-directory test-suite
test-suite:
	swift test -Xswiftc -warnings-as-errors
	Tests/ReleaseChecks/check_secrets_tests.sh
	Tests/ReleaseChecks/check_bundle.sh
	../tools/tests/test_check_no_temp_leaks.sh
clean:
	rm -rf .build build
snapshots:
	@"$(LEAK_CHECK)" --sweep-only --names '$(TEMP_NAMES)' Tests/Snapshots/build.sh
signing-preflight:
	@tools/resolve_signing_identity.sh "$$SIGN_IDENTITY"
release:
	@set -e; identity=$$(tools/resolve_signing_identity.sh "$$SIGN_IDENTITY"); mkdir -p "$(PROJECT_TMPDIR)"; \
		swift build -c release --product PrimeMonitor -Xswiftc -warnings-as-errors; \
		if [ -e "build/release/Anker Charge Monitor.app" ]; then rm -r -- "build/release/Anker Charge Monitor.app"; fi; \
		mkdir -p "build/release/Anker Charge Monitor.app/Contents/MacOS" "build/release/Anker Charge Monitor.app/Contents/Resources"; \
		app_tmp=$$(mktemp "build/release/Anker Charge Monitor.app/Contents/MacOS/.PrimeMonitor.XXXXXX"); \
		cp -p "$$(swift build -c release -Xswiftc -warnings-as-errors --show-bin-path)/PrimeMonitor" "$$app_tmp"; \
		mv "$$app_tmp" "build/release/Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor"; \
		cp Resources/Info.plist "build/release/Anker Charge Monitor.app/Contents/Info.plist"; \
		cp Resources/device_catalog.json "build/release/Anker Charge Monitor.app/Contents/Resources/device_catalog.json"; \
		codesign --force --sign "$$identity" --timestamp=none "build/release/Anker Charge Monitor.app"; \
		codesign --verify --strict "build/release/Anker Charge Monitor.app"
install deploy:
	node ../tools/deploy_anker_charge_monitor.mjs
live-check:
	"/Applications/Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor" --live-check
