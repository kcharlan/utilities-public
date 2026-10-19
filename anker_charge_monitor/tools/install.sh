#!/bin/bash
set -euo pipefail
# App activation owner. The root deployer supplies its independently verified
# transaction backup and publishes the provenance receipt after this returns.
# Rename whole bundles; never truncate a running executable or quit/relaunch it.
source_app=${1:?Usage: tools/install.sh BUNDLE}
expected_plist=${PRIME_MONITOR_EXPECTED_PLIST:-"$(cd "$(dirname "$0")/.." && pwd)/Resources/Info.plist"}
apps=${PRIME_MONITOR_APPS_DIR:-/Applications}
target="$apps/Anker Charge Monitor.app"
legacy="$apps/Prime Monitor.app"
validate() {
    local bundle=$1
    [ -d "$bundle" ] && [ ! -L "$bundle" ] || return 1
    [ -z "$(find "$bundle" -type l -print)" ] || { echo 'App contains symlinks' >&2; return 1; }
    [ -z "$(find "$bundle" ! -type d ! -type f -print)" ] || return 1
    [ -x "$bundle/Contents/MacOS/PrimeMonitor" ] || return 1
    [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$bundle/Contents/Info.plist")" = local.utilities.prime-monitor ] || return 1
    [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$bundle/Contents/Info.plist")" = PrimeMonitor ] || return 1
    [ "$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$bundle/Contents/Info.plist")" = 27.0 ] || return 1
    [ "$(/usr/libexec/PlistBuddy -c 'Print :LSUIElement' "$bundle/Contents/Info.plist")" = true ] || return 1
    codesign --verify --strict -R "=identifier \"local.utilities.prime-monitor\" and certificate leaf = H\"$identity\"" "$bundle"
}
validate_release() {
    validate "$1" || return
    [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleName' "$1/Contents/Info.plist")" = "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleName' "$expected_plist")" ] || return
    [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$1/Contents/Info.plist")" = "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleDisplayName' "$expected_plist")" ] || return
    [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$1/Contents/Info.plist")" = "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$expected_plist")" ]
}
# Direct invocation retains the same mandatory signing preflight as make install.
identity=$("$(dirname "$0")/resolve_signing_identity.sh" "${SIGN_IDENTITY-CodexBar Local}")
validate_release "$source_app"
mkdir -p "$apps"
[ ! -L "$apps" ] && [ ! -L "$target" ] && [ ! -L "$legacy" ] || { echo 'Refusing linked installation paths' >&2; exit 1; }
if [ -e "$target" ] && [ -e "$legacy" ]; then
    echo 'Both Anker Charge Monitor.app and Prime Monitor.app exist; resolve the ambiguous installation before retrying.' >&2; exit 1
fi
previous="$target"
if [ -e "$legacy" ]; then previous="$legacy"; fi
# Validate ownership/signature before displacement; an older release may upgrade.
if [ -e "$previous" ]; then validate "$previous"; fi
backup_root=${PRIME_MONITOR_BACKUP_DIR:-"$HOME/.utilities-deploy-backups/anker-charge-monitor"}
if [ -n "${PRIME_MONITOR_TRANSACTION_BACKUP:-}" ]; then
    backup=$PRIME_MONITOR_TRANSACTION_BACKUP
    [ -d "$backup" ] && [ ! -L "$backup" ] || exit 1
else
    mkdir -p "$backup_root"; chmod 700 "$backup_root"
    backup=$(mktemp -d "$backup_root/copy.XXXXXX")
    chmod 700 "$backup"
fi
stage=$(mktemp -d "$apps/.prime-monitor-stage-XXXXXX")
chmod 700 "$stage"
preserve_stage=0
cleanup() { if [ "$preserve_stage" = 0 ]; then rm -rf "$stage"; fi; }
trap cleanup EXIT
cp -Rp "$source_app" "$stage/Anker Charge Monitor.app"
diff -rq "$source_app" "$stage/Anker Charge Monitor.app" >/dev/null
validate_release "$stage/Anker Charge Monitor.app"
had_previous=0
if [ -e "$previous" ]; then
    if [ -z "${PRIME_MONITOR_TRANSACTION_BACKUP:-}" ]; then
        cp -Rp "$previous" "$backup/$(basename "$previous")"
        diff -rq "$previous" "$backup/$(basename "$previous")" >/dev/null
    fi
    had_previous=1
fi
printf 'Recovery backup: %s\n' "$backup"
# Failure restores the displaced original (retaining its inode) and keeps the
# independent verified byte backup available if recovery itself fails.
activate() {
    if [ "$had_previous" = 1 ]; then mv "$previous" "$stage/displaced-app" || return; fi
    mv "$stage/Anker Charge Monitor.app" "$target" || return
    validate_release "$target" || return
}
if ! activate; then
    if [ -e "$stage/displaced-app" ]; then
        rm -rf "$target"
        if ! mv "$stage/displaced-app" "$previous"; then
            preserve_stage=1
            printf 'Activation and recovery failed; preserve %s and %s\n' "$stage" "$backup" >&2; exit 1
        fi
    elif [ "$had_previous" = 0 ]; then rm -rf "$target"
    fi
    echo 'Activation failed; previous app restored (or absent installation preserved).' >&2
    exit 1
fi
printf 'Anker Charge Monitor installed; recovery backup: %s\n' "$backup"
if pgrep -f '(Prime Monitor|Anker Charge Monitor).app/Contents/MacOS/PrimeMonitor' >/dev/null; then
    echo 'Quit and reopen Anker Charge Monitor when convenient to use the installed release; the current process remains running.'
fi
