#!/bin/bash
set -euo pipefail
# Verify Telltale's Makefile routes build and test through the shared temp-leak checker.
root=$(cd "$(dirname "$0")/../.." && pwd)
checker="$root/../tools/check_no_temp_leaks.sh"
scratch=$(mktemp -d "${TMPDIR:-/tmp}/telltale-wiring-test.XXXXXX")
chmod 700 "$scratch"
trap 'code=$?; rm -r -- "${scratch:?}" || { [ "$code" -ne 0 ] || code=1; }; exit "$code"' EXIT
mkdir "$scratch/darwin"
export DARWIN="$scratch/darwin" NO_TEMP_LEAKS_DARWIN_TEMP_DIR="$scratch/darwin"
mkdir "$DARWIN/TemporaryDirectory.before1"
: > "$DARWIN/TemporaryDirectory.before1/.keep-directory"
# The Makefile: `make build` and `make test` run SwiftPM with TMPDIR in a private run directory
# under the project's own .build/tmp/, which is removed with the package's lock files and honored
# TemporaryDirectory.* inside it, and the compile's Darwin marker is swept. A fake `swift` stands in.
project="$scratch/project/telltale" caller="$scratch/caller"
mkdir -p "$caller" "$scratch/project/tools" "$project/Tests/ReleaseChecks" "$scratch/bin"
project=$(cd "$project" && pwd -P)
cp "$root/Makefile" "$project/"
cp "$checker" "$scratch/project/tools/"
printf '#!/bin/sh\nexit 0\n' > "$project/Tests/ReleaseChecks/synthetic.sh"
cat > "$scratch/bin/swift" <<'SH'
#!/bin/bash
set -e
printf '%s\n' "$TMPDIR" >> "$SWIFT_LOG"
own=$(pwd -P | tr / _)
: > "${TMPDIR}${own}_.build.lock"
mkdir "${TMPDIR}TemporaryDirectory.honored$$"
mkdir "$DARWIN/TemporaryDirectory.compile$$" && : > "$DARWIN/TemporaryDirectory.compile$$/.keep-directory"
SH
chmod 755 "$project/Tests/ReleaseChecks/synthetic.sh" "$scratch/bin/swift"
export SWIFT_LOG="$scratch/swift.log"
for target in build test; do
    : > "$SWIFT_LOG"
    if ! TMPDIR="$caller" PATH="$scratch/bin:$PATH" make -C "$project" --no-print-directory "$target" > "$scratch/out.log" 2>&1; then
        echo "FAIL: make $target"; cat "$scratch/out.log"; exit 1
    fi
    [ "$(wc -l < "$SWIFT_LOG" | tr -d ' ')" = 1 ] || { echo "FAIL: make $target ran swift other than once"; exit 1; }
    case "$(cat "$SWIFT_LOG")" in "$project"/.build/tmp/no-temp-leaks-run.*/) ;; *) echo "FAIL: make $target TMPDIR: $(cat "$SWIFT_LOG")"; exit 1 ;; esac
    [ -z "$(ls -A "$project/.build/tmp")" ] || { echo "FAIL: make $target left .build/tmp entries"; ls -A "$project/.build/tmp"; exit 1; }
    [ "$(ls -A "$DARWIN")" = TemporaryDirectory.before1 ] || { echo "FAIL: make $target left Darwin markers"; ls -A "$DARWIN"; exit 1; }
    [ -z "$(ls -A "$caller")" ] || { echo "FAIL: make $target wrote to the caller's TMPDIR"; ls -A "$caller"; exit 1; }
done
echo 'Telltale temp wiring checks passed'
