#!/bin/bash
set -euo pipefail
# Verifies the vendored zstd in Sources/CZstd against Sources/CZstd/VERSION.
# Usage: check_vendor.sh [package-root]   (default: this package)
# Exit 0: every listed file matches its recorded sha256, no unlisted .c/.h file exists
# (include/czstd.h, the shim, excepted), and Package.swift defines what VERSION says was compiled.
# VERSION lists upstream paths (lib/common/mem.h); the target keeps them without the lib/ prefix.
root=${1:-"$(cd "$(dirname "$0")/../.." && pwd)"}
target="$root/Sources/CZstd"
version="$target/VERSION"
failures=0
fail() { echo "check_vendor: $*" >&2; failures=$((failures + 1)); }

[ -f "$version" ] || { echo "check_vendor: missing $version" >&2; exit 1; }

listed=$(mktemp "${TMPDIR:-/tmp}/check-vendor-listed.XXXXXX")
actual=$(mktemp "${TMPDIR:-/tmp}/check-vendor-actual.XXXXXX")
trap 'rm -f "$listed" "$actual"' EXIT

checked=0
while IFS= read -r line; do
    case "$line" in
    *' sha256: '*) ;;
    *) continue ;;
    esac
    path=${line%% sha256: *}
    expected=${line##* sha256: }
    case "$path" in
    "archive") continue ;;  # the upstream archive digest, not a file in this tree
    lib/*) relative=${path#lib/} ;;
    *) relative=$path ;;
    esac
    file="$target/$relative"
    if [ ! -f "$file" ]; then
        fail "listed file is missing: $relative"
        continue
    fi
    computed=$(shasum -a 256 "$file" | awk '{print $1}')
    if [ "$computed" != "$expected" ]; then
        fail "sha256 mismatch: $relative (recorded $expected, found $computed)"
    fi
    echo "$relative" >> "$listed"
    checked=$((checked + 1))
done < "$version"

if [ "$checked" -eq 0 ]; then fail "VERSION lists no files"; fi

(cd "$target" && find . \( -name '*.c' -o -name '*.h' \) -type f ! -path './include/czstd.h' | sed 's|^\./||' | LC_ALL=C sort) > "$actual"
LC_ALL=C sort -o "$listed" "$listed"
unlisted=$(comm -13 "$listed" "$actual")
if [ -n "$unlisted" ]; then
    while IFS= read -r file; do fail "unlisted source file: $file"; done <<< "$unlisted"
fi

# The compiled: line names the defines the build needs; Package.swift must declare each one.
compiled=$(grep '^compiled:' "$version" || true)
for define in $(printf '%s\n' "$compiled" | tr ' ' '\n' | grep '^-D' || true); do
    name=${define#-D}
    value=${name#*=}
    name=${name%%=*}
    if ! grep -q "\.define(\"$name\", to: \"$value\")" "$root/Package.swift"; then
        fail "Package.swift does not define $name=$value as VERSION requires"
    fi
done
if [ -z "$compiled" ]; then fail "VERSION has no compiled: line"; fi

[ -f "$target/include/czstd.h" ] || fail "missing shim include/czstd.h"

if [ "$failures" -ne 0 ]; then
    echo "check_vendor: $failures problem(s)" >&2
    exit 1
fi
echo "check_vendor: $checked vendored files match VERSION"
