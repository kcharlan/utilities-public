# Port: anker_charge_monitor/Makefile, release/test recipes, 023737f.
# Adaptation: Telltale.app; no bundled resources; test runs every Tests/ReleaseChecks script;
# no live-check target (tools/notification_check.sh is the spike runner); snapshots and
# acceptance port BV's harness targets.
SIGN_IDENTITY ?= CodexBar Local
export SIGN_IDENTITY
.PHONY: build test test-suite clean release install deploy signing-preflight snapshots acceptance
build:
	swift build -Xswiftc -warnings-as-errors
# Ruling R28: the whole suite runs inside tools/check_no_temp_leaks.sh, which gives it a private
# TMPDIR (removed afterwards, toolchain leftovers included) and fails if it leaves a Telltale entry.
test:
	@tools/check_no_temp_leaks.sh $(MAKE) --no-print-directory test-suite
test-suite:
	swift test -Xswiftc -warnings-as-errors
	@set -e; for script in Tests/ReleaseChecks/*.sh; do echo "== $$script"; "$$script"; done
clean:
	rm -rf .build build
signing-preflight:
	@tools/resolve_signing_identity.sh "$$SIGN_IDENTITY"
release:
	@set -e; identity=$$(tools/resolve_signing_identity.sh "$$SIGN_IDENTITY"); \
		swift build -c release --product Telltale -Xswiftc -warnings-as-errors; \
		if [ -e "build/release/Telltale.app" ]; then rm -r -- "build/release/Telltale.app"; fi; \
		mkdir -p "build/release/Telltale.app/Contents/MacOS" "build/release/Telltale.app/Contents/Resources"; \
		app_tmp=$$(mktemp "build/release/Telltale.app/Contents/MacOS/.Telltale.XXXXXX"); \
		cp -p "$$(swift build -c release -Xswiftc -warnings-as-errors --show-bin-path)/Telltale" "$$app_tmp"; \
		mv "$$app_tmp" "build/release/Telltale.app/Contents/MacOS/Telltale"; \
		cp Resources/Info.plist "build/release/Telltale.app/Contents/Info.plist"; \
		mkdir -p "build/release/Telltale.app/Contents/Resources/Fonts"; \
		cp -p Resources/Fonts/*.ttf Resources/Fonts/OFL.txt "build/release/Telltale.app/Contents/Resources/Fonts/"; \
		codesign --force --sign "$$identity" --timestamp=none "build/release/Telltale.app"; \
		codesign --verify --strict "build/release/Telltale.app"
install deploy:
	node ../tools/deploy_telltale.mjs
# Private OS temporary builds only: maintained panel PNGs, and the synthetic acceptance bundle
# (com.example.telltale.acceptance, its service tests run first). Neither launches a GUI.
snapshots:
	Tests/Snapshots/build.sh
acceptance:
	Tests/Acceptance/build.sh
