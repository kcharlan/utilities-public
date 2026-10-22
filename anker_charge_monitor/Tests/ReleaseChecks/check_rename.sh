#!/bin/bash
set -euo pipefail
# Real installer, private synthetic bundles/signing only. Catches migration that
# leaves duplicates, loses rollback path/inode, or displaces an unknown bundle.
root=$(cd "$(dirname "$0")/../.." && pwd)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/prime-rename.XXXXXX")
trap 'code=$?; if [ "$code" != 0 ]; then cat "$scratch"/*.log 2>/dev/null || true; fi; rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin" "$scratch/source.app/Contents/MacOS"
cp "$root/Resources/Info.plist" "$scratch/source.app/Contents/Info.plist"
printf 'new executable bytes\n' > "$scratch/source.app/Contents/MacOS/PrimeMonitor"
chmod 755 "$scratch/source.app/Contents/MacOS/PrimeMonitor"
cat > "$scratch/bin/security" <<'MOCK'
#!/bin/bash
[ "${SYNTHETIC_MISSING:-0}" = 0 ] || exit 0
echo '  Matching identities'
echo '  1) AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA "CodexBar Local"'
MOCK
cat > "$scratch/bin/codesign" <<'MOCK'
#!/bin/bash
bundle=${!#}
[ "$#" = 5 ] && [ "$1" = --verify ] && [ "$2" = --strict ] && [ "$3" = -R ] &&
 [ "$4" = '=identifier "local.utilities.prime-monitor" and certificate leaf = H"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"' ] || {
 echo 'FAIL: codesign requires the exact literal =identifier/certificate requirement argument' >&2; exit 94;
}
[ ! -e "$bundle/reject-signature" ] || exit 92
if [ "$bundle" = "$PRIME_MONITOR_APPS_DIR/Anker Charge Monitor.app" ] && [ -e "$RENAME_ACTIVATED" ]; then
 rm "$RENAME_ACTIVATED"
 if [ -e "$RENAME_FAIL" ]; then rm "$RENAME_FAIL"; exit 93; fi
fi
MOCK
cat > "$scratch/bin/mv" <<'MOCK'
#!/bin/bash
/bin/mv "$@" || exit
if [[ "$1" = *'.prime-monitor-stage-'*'/Anker Charge Monitor.app' && "${!#}" = "$PRIME_MONITOR_APPS_DIR/Anker Charge Monitor.app" ]]; then
 touch "$RENAME_ACTIVATED"
fi
MOCK
cat > "$scratch/bin/pgrep" <<'MOCK'
#!/bin/bash
exit 1
MOCK
chmod 700 "$scratch/bin/"*
export PATH="$scratch/bin:$PATH" PRIME_MONITOR_APPS_DIR="$scratch/apps" PRIME_MONITOR_BACKUP_DIR="$scratch/backups" RENAME_FAIL="$scratch/fail"
export RENAME_ACTIVATED="$scratch/activated"
legacy="$PRIME_MONITOR_APPS_DIR/Prime Monitor.app"
target="$PRIME_MONITOR_APPS_DIR/Anker Charge Monitor.app"
mkdir -p "$PRIME_MONITOR_APPS_DIR"
cp -Rp "$scratch/source.app" "$legacy"
/usr/libexec/PlistBuddy -c 'Set :CFBundleName Prime Monitor' "$legacy/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleShortVersionString 0.0.1' "$legacy/Contents/Info.plist"
printf 'legacy reader bytes\n' > "$legacy/Contents/MacOS/PrimeMonitor"
cp "$legacy/Contents/MacOS/PrimeMonitor" "$scratch/old"
inode=$(stat -f %i "$legacy/Contents/MacOS/PrimeMonitor")
exec 8< "$legacy/Contents/MacOS/PrimeMonitor"
# Mandatory resolver preflight leaves legacy and backup tree untouched.
if SYNTHETIC_MISSING=1 "$root/tools/install.sh" "$scratch/source.app" > "$scratch/preflight.log" 2>&1; then exit 1; fi
[ ! -e "$PRIME_MONITOR_BACKUP_DIR" ]
cmp "$scratch/old" "$legacy/Contents/MacOS/PrimeMonitor"
# Source/stage/activation still require exact current-release metadata.
cp -Rp "$scratch/source.app" "$scratch/wrong-version.app"
/usr/libexec/PlistBuddy -c 'Set :CFBundleShortVersionString 0.0.1' "$scratch/wrong-version.app/Contents/Info.plist"
if "$root/tools/install.sh" "$scratch/wrong-version.app" > "$scratch/wrong-source.log" 2>&1; then echo 'FAIL: wrong source version accepted'; exit 1; fi
[ ! -e "$PRIME_MONITOR_BACKUP_DIR" ]
# Failed activation restores original path and original executable inode.
touch "$RENAME_FAIL"
if "$root/tools/install.sh" "$scratch/source.app" > "$scratch/rollback.log" 2>&1; then echo 'FAIL: migration activation failure accepted'; exit 1; fi
rg -q 'previous app restored' "$scratch/rollback.log" || { echo 'FAIL: lower-version legacy rejected before activation rollback'; exit 1; }
[ ! -e "$target" ]
[ "$(stat -f %i "$legacy/Contents/MacOS/PrimeMonitor")" = "$inode" ]
cmp "$scratch/old" "$legacy/Contents/MacOS/PrimeMonitor"
backup=$(sed -n 's/^Recovery backup: //p' "$scratch/rollback.log")
cmp "$scratch/old" "$backup/Prime Monitor.app/Contents/MacOS/PrimeMonitor"
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$legacy/Contents/Info.plist")" = 0.0.1 ]
echo 'migration activation rollback and independent recovery bytes passed'
# Both names present is ambiguous: retain both byte-for-byte.
cp -Rp "$scratch/source.app" "$target"
if "$root/tools/install.sh" "$scratch/source.app" > "$scratch/collision.log" 2>&1; then echo 'FAIL: ambiguous destinations accepted'; exit 1; fi
cmp "$scratch/old" "$legacy/Contents/MacOS/PrimeMonitor"
cmp "$scratch/source.app/Contents/MacOS/PrimeMonitor" "$target/Contents/MacOS/PrimeMonitor"
rm -rf "$target"
# Unknown identity and invalid signature must never be displaced.
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier synthetic.unknown' "$legacy/Contents/Info.plist"
if "$root/tools/install.sh" "$scratch/source.app" > "$scratch/identity.log" 2>&1; then echo 'FAIL: unknown legacy identity accepted'; exit 1; fi
cmp "$scratch/old" "$legacy/Contents/MacOS/PrimeMonitor"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier local.utilities.prime-monitor' "$legacy/Contents/Info.plist"
touch "$legacy/reject-signature"
if "$root/tools/install.sh" "$scratch/source.app" > "$scratch/signature.log" 2>&1; then echo 'FAIL: invalid legacy signature accepted'; exit 1; fi
cmp "$scratch/old" "$legacy/Contents/MacOS/PrimeMonitor"
rm "$legacy/reject-signature"
echo 'collision, legacy identity and signature rejection passed'
"$root/tools/install.sh" "$scratch/source.app" > "$scratch/success.log"
[ ! -e "$legacy" ]
cmp "$scratch/source.app/Contents/MacOS/PrimeMonitor" "$target/Contents/MacOS/PrimeMonitor"
cat <&8 > "$scratch/held"; exec 8<&-
cmp "$scratch/old" "$scratch/held"
backup=$(sed -n 's/^Recovery backup: //p' "$scratch/success.log")
cmp "$scratch/old" "$backup/Prime Monitor.app/Contents/MacOS/PrimeMonitor"
# Already-renamed lower-version installs also upgrade and retain rollback readers.
/usr/libexec/PlistBuddy -c 'Set :CFBundleShortVersionString 0.0.2' "$target/Contents/Info.plist"
printf 'renamed older reader bytes\n' > "$target/Contents/MacOS/PrimeMonitor"
cp "$target/Contents/MacOS/PrimeMonitor" "$scratch/renamed-old"
inode=$(stat -f %i "$target/Contents/MacOS/PrimeMonitor")
exec 7< "$target/Contents/MacOS/PrimeMonitor"
touch "$RENAME_FAIL"
if "$root/tools/install.sh" "$scratch/source.app" > "$scratch/renamed-rollback.log" 2>&1; then echo 'FAIL: renamed upgrade activation failure accepted'; exit 1; fi
rg -q 'previous app restored' "$scratch/renamed-rollback.log"
[ "$(stat -f %i "$target/Contents/MacOS/PrimeMonitor")" = "$inode" ]
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$target/Contents/Info.plist")" = 0.0.2 ]
cmp "$scratch/renamed-old" "$target/Contents/MacOS/PrimeMonitor"
backup=$(sed -n 's/^Recovery backup: //p' "$scratch/renamed-rollback.log")
cmp "$scratch/renamed-old" "$backup/Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor"
"$root/tools/install.sh" "$scratch/source.app" > "$scratch/renamed-success.log"
cmp "$scratch/source.app/Contents/MacOS/PrimeMonitor" "$target/Contents/MacOS/PrimeMonitor"
[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$target/Contents/Info.plist")" = 0.4.0 ]
cat <&7 > "$scratch/renamed-held"; exec 7<&-
cmp "$scratch/renamed-old" "$scratch/renamed-held"
[ ! -e "$legacy" ]
echo 'older legacy and renamed upgrade/rollback, exact new-source version, requirement argument and held-reader checks passed'
[ -z "$(find "$PRIME_MONITOR_APPS_DIR" -name '.prime-monitor-stage-*' -print)" ]
echo 'rename migration, no duplicate, held reader and recovery checks passed (synthetic signing only)'
