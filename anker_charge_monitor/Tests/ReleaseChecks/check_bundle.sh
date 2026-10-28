#!/bin/bash
set -euo pipefail
# Ports app-only cases from BV Tests/ReleaseChecks/release.test.mjs at 579ebb7.
# CLI and BV acceptance/prototype harness cases excluded.
# Fake signing commands exist ONLY in this private test PATH;
# these are structural tests, never evidence of a trusted real signature.
root=$(cd "$(dirname "$0")/../.." && pwd)
bash "$root/Tests/ReleaseChecks/check_rename.sh"
scratch=$(mktemp -d "${TMPDIR:-/tmp}/prime-bundle.XXXXXX")
chmod 700 "$scratch"
# The snapshot renderer requires its home in Foundation's temporary directory, the Darwin user
# temp dir whatever TMPDIR says (`make test` points TMPDIR into .build/tmp), so it gets its own
# scratch there, removed with this one.
snapshot_scratch=$(mktemp -d "$(getconf DARWIN_USER_TEMP_DIR)prime-bundle-snapshots.XXXXXX")
chmod 700 "$snapshot_scratch"
trap 'code=$?; if [ "$code" != 0 ]; then tail -20 "$scratch"/*.log 2>/dev/null || true; fi; rm -rf "$scratch" "$snapshot_scratch"' EXIT
mkdir -p "$scratch/project" "$scratch/bin" "$scratch/home"
for item in Package.swift Makefile Sources Resources tools Tests; do cp -Rp "$root/$item" "$scratch/project/"; done
# The Makefile's harness targets use the repository's shared leak check, found at ../tools/.
mkdir -p "$scratch/tools"; cp -p "$root/../tools/check_no_temp_leaks.sh" "$scratch/tools/"
cat > "$scratch/bin/security" <<'MOCK'
#!/bin/bash
[ "${SYNTHETIC_SECURITY_FAILURE:-0}" = 0 ] || exit 89
[ "$*" = 'find-identity -p codesigning' ] || exit 90
[ "${SYNTHETIC_NO_IDENTITY:-0}" = 0 ] || exit 0
cat <<'IDENTITIES'
Policy: Code Signing
  Matching identities
  1) AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA "CodexBar Local" (CSSMERR_TP_NOT_TRUSTED)
  2) BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB "Custom $ ` Identity"
  3) CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC "CodexBar Local Extra"
     3 identities found
IDENTITIES
if [ "${SYNTHETIC_AMBIGUOUS:-0}" = 1 ]; then
 printf '  4) DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD "CodexBar Local"\n'
fi
printf '  Valid identities only\n'
if [ "${SYNTHETIC_TRUSTED:-0}" = 1 ]; then
 printf '  1) AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA "CodexBar Local"\n     1 valid identities found\n'
else
 printf '     0 valid identities found\n'
fi
MOCK
cat > "$scratch/bin/codesign" <<'MOCK'
#!/bin/bash
printf '%s\n' "$*" >> "$SYNTHETIC_SIGN_LOG"
if [ "$#" -gt 3 ] && [ "$1" = --verify ]; then
 [ "$#" = 5 ] && [ "$2" = --strict ] && [ "$3" = -R ] &&
  [ "$4" = '=identifier "local.utilities.prime-monitor" and certificate leaf = H"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"' ] || {
  echo 'FAIL: codesign requires the exact literal =identifier/certificate requirement argument' >&2; exit 94;
 }
fi
if [[ "$*" = *--sign* ]]; then
 [[ "$*" = *'--sign AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA --timestamp=none'* ]] || exit 91
fi
if [[ "$*" = *--verify* && "${!#}" = "$PRIME_MONITOR_APPS_DIR/Anker Charge Monitor.app" && -e "$PRIME_MONITOR_TEST_FAILURE" && -e "$PRIME_MONITOR_TEST_ACTIVATED" ]]; then
 rm "$PRIME_MONITOR_TEST_FAILURE" "$PRIME_MONITOR_TEST_ACTIVATED"; exit 92
fi
MOCK
cat > "$scratch/bin/pgrep" <<'MOCK'
#!/bin/bash
exit "${SYNTHETIC_RUNNING:-1}"
MOCK
cat > "$scratch/bin/mv" <<'MOCK'
#!/bin/bash
/bin/mv "$@" || exit
if [[ "$1" = *'.prime-monitor-stage-'*'/Anker Charge Monitor.app' && "${!#}" = "$PRIME_MONITOR_APPS_DIR/Anker Charge Monitor.app" ]]; then
 touch "$PRIME_MONITOR_TEST_ACTIVATED"
fi
if [ "${!#}" = "$PRIME_MONITOR_APPS_DIR/Anker Charge Monitor.app" ] && [ -e "$PRIME_MONITOR_TEST_CORRUPT" ]; then
 rm "$PRIME_MONITOR_TEST_CORRUPT"
 /usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier synthetic.invalid' "${!#}/Contents/Info.plist"
fi
MOCK
chmod 700 "$scratch/bin/"*
export PATH="$scratch/bin:$PATH" SYNTHETIC_SIGN_LOG="$scratch/sign.log"
export PRIME_MONITOR_APPS_DIR="$scratch/home/Applications" PRIME_MONITOR_BACKUP_DIR="$scratch/backups" PRIME_MONITOR_TEST_FAILURE="$scratch/fail-activation"
export PRIME_MONITOR_TEST_CORRUPT="$scratch/corrupt-activation"
export PRIME_MONITOR_TEST_ACTIVATED="$scratch/activated"
cd "$scratch/project"
if SYNTHETIC_NO_IDENTITY=1 make release > "$scratch/missing.log" 2>&1; then echo 'FAIL: missing identity accepted'; exit 1; fi
rg -q 'SIGN_IDENTITY' "$scratch/missing.log"
[ ! -d .build ]
# Resolver boundary cases catch valid-only filtering, partial matches, ambiguity,
# command failure, shell interpolation and unsupported ad-hoc selection.
[ "$(tools/resolve_signing_identity.sh 'CodexBar Local')" = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA ]
[ "$(SYNTHETIC_TRUSTED=1 tools/resolve_signing_identity.sh 'CodexBar Local')" = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA ]
[ "$(tools/resolve_signing_identity.sh 'Custom $ ` Identity')" = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB ]
[ "$(tools/resolve_signing_identity.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)" = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB ]
for selection in 'CodexBar' 'Local' 'AAAAAAAA' '-' ''; do
 if tools/resolve_signing_identity.sh "$selection" > "$scratch/rejected.log" 2>&1; then echo 'FAIL: invalid selection accepted'; exit 1; fi
done
if SYNTHETIC_AMBIGUOUS=1 tools/resolve_signing_identity.sh 'CodexBar Local' > "$scratch/ambiguous.log" 2>&1; then echo 'FAIL: ambiguous identity accepted'; exit 1; fi
if SYNTHETIC_SECURITY_FAILURE=1 tools/resolve_signing_identity.sh 'CodexBar Local' > "$scratch/security-failure.log" 2>&1; then echo 'FAIL: security failure accepted'; exit 1; fi
for mode in SYNTHETIC_NO_IDENTITY SYNTHETIC_AMBIGUOUS SYNTHETIC_SECURITY_FAILURE; do
 if env "$mode=1" make release > "$scratch/pre-build.log" 2>&1; then echo 'FAIL: invalid release preflight accepted'; exit 1; fi
 [ ! -d .build ]
 if env "$mode=1" tools/install.sh absent.app > "$scratch/pre-install.log" 2>&1; then echo 'FAIL: invalid install preflight accepted'; exit 1; fi
 # Prove rejection came from the resolver, not from the absent source bundle.
 case "$mode" in
  SYNTHETIC_SECURITY_FAILURE) rg -q '^Cannot query code-signing identities;' "$scratch/pre-install.log" ;;
  *) rg -q '^Signing identity missing or ambiguous\.' "$scratch/pre-install.log" ;;
 esac
 [ ! -e "$PRIME_MONITOR_APPS_DIR" ] && [ ! -e "$PRIME_MONITOR_BACKUP_DIR" ]
done
# Make command-line variables require $$ for a literal dollar.
make signing-preflight SIGN_IDENTITY='Custom $$ ` Identity' > "$scratch/custom.log" 2>&1
make release > "$scratch/release.log" 2>&1
app='build/release/Anker Charge Monitor.app'
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleName' "$app/Contents/Info.plist")" = 'Anker Charge Monitor' ]
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$app/Contents/Info.plist")" = 'Anker Charge Monitor' ]
exe="$app/Contents/MacOS/PrimeMonitor"
vtool -show-build "$exe" | rg -q '\bminos 27\.0\b'
[ "$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$app/Contents/Info.plist")" = '27.0' ]
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Contents/Info.plist")" = 'local.utilities.prime-monitor' ]
# The bundled device-catalog seed is the tracked resource, byte for byte.
cmp "$root/Resources/device_catalog.json" "$app/Contents/Resources/device_catalog.json"
# Keep an open reader of the prior executable: release must replace, not truncate.
printf 'synthetic prior executable\n' > "$scratch/prior"
rm "$exe"; cp "$scratch/prior" "$exe"; chmod 755 "$exe"
printf 'stale\n' > "$app/Contents/Resources/synthetic-stale.txt"
exec 9< "$exe"
old_inode=$(stat -f %i "$exe")
make release >> "$scratch/release.log" 2>&1
[ ! -e "$app/Contents/Resources/synthetic-stale.txt" ]
cmp "$root/Resources/device_catalog.json" "$app/Contents/Resources/device_catalog.json"
[ "$(stat -f %i "$exe")" != "$old_inode" ]
cat <&9 > "$scratch/held"; cmp "$scratch/prior" "$scratch/held"; exec 9<&-
# Successful activation, failed activation recovery, and notice preserve old readers.
tools/install.sh "$app" > "$scratch/install.log"
rm -f "$PRIME_MONITOR_TEST_ACTIVATED"
installed="$PRIME_MONITOR_APPS_DIR/Anker Charge Monitor.app"
printf 'prior installed executable\n' > "$scratch/installed-prior"
rm "$installed/Contents/MacOS/PrimeMonitor"; cp "$scratch/installed-prior" "$installed/Contents/MacOS/PrimeMonitor"; chmod 755 "$installed/Contents/MacOS/PrimeMonitor"
exec 8< "$installed/Contents/MacOS/PrimeMonitor"
touch "$PRIME_MONITOR_TEST_FAILURE"
if tools/install.sh "$app" > "$scratch/recover.log" 2>&1; then echo 'FAIL: activation failure accepted'; exit 1; fi
rg -q 'previous app restored' "$scratch/recover.log"
cmp "$scratch/installed-prior" "$installed/Contents/MacOS/PrimeMonitor"
touch "$PRIME_MONITOR_TEST_CORRUPT"
if tools/install.sh "$app" > "$scratch/corrupt.log" 2>&1; then echo 'FAIL: corrupt activation metadata accepted'; exit 1; fi
cmp "$scratch/installed-prior" "$installed/Contents/MacOS/PrimeMonitor"
SYNTHETIC_RUNNING=0 tools/install.sh "$app" > "$scratch/running.log"
rg -q 'Quit and reopen Anker Charge Monitor' "$scratch/running.log"
cmp "$exe" "$installed/Contents/MacOS/PrimeMonitor"
cat <&8 > "$scratch/held-installed"; cmp "$scratch/installed-prior" "$scratch/held-installed"; exec 8<&-
[ -z "$(find "$PRIME_MONITOR_APPS_DIR" -name '.prime-monitor-stage-*' -print)" ]
rg -q -- '--force --sign AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA --timestamp=none' "$SYNTHETIC_SIGN_LOG"
rg -q -- '--verify --strict' "$SYNTHETIC_SIGN_LOG"
# Port: BV release.test.mjs, "maintained snapshot builder uses the same supported
# runtime", 579ebb7. This invokes the public target once as part of the full gate,
# in a caller-owned home inside the snapshot scratch so the trap removes it with the rest.
# Run `make snapshots` by hand to keep the PNGs for visual inspection.
# SwiftPM's lock files and TemporaryDirectory.* folders stay in that home, not in TMPDIR.
mkdir -m 700 "$scratch/snapshots-tmp"
TMPDIR="$scratch/snapshots-tmp" PRIME_MONITOR_HARNESS_HOME="$snapshot_scratch/snapshots" make snapshots > "$scratch/snapshots.log" 2>&1
[ -z "$(ls -A "$scratch/snapshots-tmp")" ] || { echo "FAIL: snapshot build left TMPDIR entries: $(ls -A "$scratch/snapshots-tmp")"; exit 1; }
cat "$scratch/snapshots.log"
snapshot_binary=$(sed -n 's/^Snapshot executable: //p' "$scratch/snapshots.log")
[ -x "$snapshot_binary" ]
vtool -show-build "$snapshot_binary" | rg -q '\bminos 27\.0\b'
vtool -show-build "$snapshot_binary" | rg -q '\bsdk 27\.0\b'
# A failed build in a builder-owned home removes that whole home.
mkdir -m 700 "$scratch/failing-bin" "$scratch/failing-tmp"
printf '#!/bin/sh\nexit 7\n' > "$scratch/failing-bin/swift"; chmod 700 "$scratch/failing-bin/swift"
code=0; PATH="$scratch/failing-bin:$PATH" TMPDIR="$scratch/failing-tmp" Tests/Snapshots/build.sh > "$scratch/failing.log" 2>&1 || code=$?
[ "$code" = 7 ] || { echo "FAIL: failed snapshot build exited $code"; exit 1; }
[ -z "$(ls -A "$scratch/failing-tmp")" ] || { echo 'FAIL: failed snapshot build left its home'; exit 1; }
echo 'bundle/install structural checks passed (synthetic signing only)'
