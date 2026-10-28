#!/bin/bash
set -euo pipefail
# Proves tools/check_no_temp_leaks.sh (ruling R28) catches a leak and sweeps only this run's empty
# SwiftPM markers, against a private fake TMPDIR and a fake Darwin user temp dir inside this
# script's own scratch, which the trap removes. The real Darwin user temp dir is never touched.
root=$(cd "$(dirname "$0")/../.." && pwd)
checker="$root/tools/check_no_temp_leaks.sh"
scratch=$(mktemp -d "${TMPDIR:-/tmp}/telltale-leak-test.XXXXXX")
chmod 700 "$scratch"
trap 'rm -rf "$scratch"' EXIT
fake="$scratch/tmp"
mkdir "$fake" "$scratch/darwin"
export OUTER="$fake" DARWIN="$scratch/darwin" TELLTALE_DARWIN_TEMP_DIR="$scratch/darwin"
expect_pass() { if ! TMPDIR="$fake" "$checker" "$@" > "$scratch/out.log" 2>&1; then echo "FAIL: reported a clean run: $*"; cat "$scratch/out.log"; exit 1; fi; }
expect_leak() {
    local name=$1; shift
    if TMPDIR="$fake" "$checker" "$@" > "$scratch/out.log" 2>&1; then echo "FAIL: missed leak $name"; exit 1; fi
    grep -qF "  $name" "$scratch/out.log" || { echo "FAIL: leak $name not named"; cat "$scratch/out.log"; exit 1; }
}

expect_pass true
# The command runs with a private TMPDIR, removed afterwards with whatever the toolchain left.
expect_pass sh -c 'case "$TMPDIR" in "$OUTER"/telltale-run.*) mkdir "$TMPDIR/TemporaryDirectory.AbCdEf" ;; *) exit 1 ;; esac'
[ -z "$(ls -A "$fake")" ] || { echo "FAIL: the private TMPDIR was not removed"; ls -A "$fake"; exit 1; }
# A directory created and removed within the run is not a leak; neither is another tool's entry.
expect_pass sh -c 'mkdir "$TMPDIR/telltale-tests-transient" && rmdir "$TMPDIR/telltale-tests-transient"'
expect_pass sh -c 'mkdir "$OUTER/other-tool.XXXX"'
# A test or script that leaves its scratch in TMPDIR, or a package build's lock file.
expect_leak telltale-zstd-tests-0001 sh -c 'mkdir "$TMPDIR/telltale-zstd-tests-0001"'
expect_leak _private_var_T_telltale-bundle.AbCdEf_project_.build.lock \
    sh -c ': > "$TMPDIR/_private_var_T_telltale-bundle.AbCdEf_project_.build.lock"'
# Something written to the real TMPDIR directly.
expect_leak telltale-snapshots.Qr34St sh -c 'mkdir "$OUTER/telltale-snapshots.Qr34St"'
# Entries from before the run are not this run's leaks.
expect_pass true
# A failing command still fails with its own status, and its leak is still named.
if TMPDIR="$fake" "$checker" sh -c 'mkdir "$TMPDIR/telltale-acceptance.Xy12Zw"; exit 7' > "$scratch/out.log" 2>&1; then
    echo "FAIL: a failing command passed"; exit 1
else
    [ $? -eq 7 ] || { echo "FAIL: the command's status was not passed through"; exit 1; }
fi
grep -qF '  telltale-acceptance.Xy12Zw' "$scratch/out.log" || { echo "FAIL: leak from a failing run not named"; exit 1; }
if TMPDIR="$fake" "$checker" > /dev/null 2>&1; then echo "FAIL: no command accepted"; exit 1; fi

# The widened pattern: a SwiftPM lock named after a `.../telltale/...` package path, in the given
# TMPDIR or in the Darwin user temp dir.
expect_leak _private_var_project_telltale_.build.lock sh -c ': > "$OUTER/_private_var_project_telltale_.build.lock"'
expect_leak _Users_someone_telltale_telltale_.build_workspace-state.json.lock \
    sh -c ': > "$DARWIN/_Users_someone_telltale_telltale_.build_workspace-state.json.lock"'
rm -f "$fake"/*.lock "$DARWIN"/*.lock
# Inside the private TMPDIR, the lock files of the package being built in the working directory are
# the toolchain's own; another Telltale package's lock still is a leak.
mkdir "$scratch/telltale"
own=$(cd "$scratch/telltale" && pwd -P | tr / _)
(cd "$scratch/telltale" && expect_pass sh -c ': > "$TMPDIR$1_.build.lock"; : > "$TMPDIR$1_.build_workspace-state.json.lock"' sh "$own")
(cd "$scratch/telltale" && expect_leak _private_var_T_telltale-bundle.Zz_project_.build.lock \
    sh -c ': > "$TMPDIR/_private_var_T_telltale-bundle.Zz_project_.build.lock"')

# The marker sweep. One marker-only directory from before the run must survive; of the new ones,
# only the one whose sole content is an empty .keep-directory is removed.
marker() { mkdir "$DARWIN/$1" && : > "$DARWIN/$1/.keep-directory"; }
marker TemporaryDirectory.before1
cat > "$scratch/compile.sh" <<'SH'
set -e
mkdir "$DARWIN/TemporaryDirectory.new1" && : > "$DARWIN/TemporaryDirectory.new1/.keep-directory"
mkdir "$DARWIN/TemporaryDirectory.new2" && : > "$DARWIN/TemporaryDirectory.new2/.keep-directory" && : > "$DARWIN/TemporaryDirectory.new2/other"
mkdir "$DARWIN/TemporaryDirectory.new3" && echo content > "$DARWIN/TemporaryDirectory.new3/.keep-directory"
mkdir "$DARWIN/TemporaryDirectory.new4"
mkdir "$DARWIN/TemporaryDirectory.new5" && : > "$DARWIN/TemporaryDirectory.new5/.keep-directory"
mkdir "$DARWIN/other-tool.new6" && : > "$DARWIN/other-tool.new6/.keep-directory"
SH
expect_swept() {
    grep -qF "removed 2 empty TemporaryDirectory.* marker(s) from $DARWIN" "$scratch/out.log" || { echo "FAIL: sweep count not reported"; cat "$scratch/out.log"; exit 1; }
    local left
    left=$(ls -A "$DARWIN" | LC_ALL=C sort | tr '\n' ' ')
    [ "$left" = "TemporaryDirectory.before1 TemporaryDirectory.new2 TemporaryDirectory.new3 TemporaryDirectory.new4 other-tool.new6 " ] ||
        { echo "FAIL: sweep removed the wrong entries: $left"; exit 1; }
    [ -f "$DARWIN/TemporaryDirectory.before1/.keep-directory" ] && [ -f "$DARWIN/TemporaryDirectory.new2/other" ] &&
        [ -s "$DARWIN/TemporaryDirectory.new3/.keep-directory" ] || { echo "FAIL: sweep changed a kept directory"; exit 1; }
    grep -qF '  TemporaryDirectory.new2' "$scratch/out.log" || { echo "FAIL: kept new marker not named"; cat "$scratch/out.log"; exit 1; }
    rm -rf "$DARWIN"/TemporaryDirectory.new* "$DARWIN"/other-tool.new6
}
expect_pass bash "$scratch/compile.sh"
expect_swept
# --sweep-only keeps the environment (a builder's home in TMPDIR stays) and still sweeps.
if ! TMPDIR="$fake" "$checker" --sweep-only sh -c '[ "$TMPDIR" = "$OUTER" ] && mkdir "$OUTER/telltale-snapshots.Kept12" && bash "$1"' sh "$scratch/compile.sh" > "$scratch/out.log" 2>&1; then
    echo "FAIL: --sweep-only did not run the command with TMPDIR unchanged"; cat "$scratch/out.log"; exit 1
fi
[ -d "$fake/telltale-snapshots.Kept12" ] || { echo "FAIL: --sweep-only removed the builder's home"; exit 1; }
expect_swept
rmdir "$fake/telltale-snapshots.Kept12"
if TMPDIR="$fake" "$checker" --sweep-only sh -c 'exit 5' > /dev/null 2>&1; then echo "FAIL: --sweep-only hid a failure"; exit 1
else [ $? -eq 5 ] || { echo "FAIL: --sweep-only did not pass the status through"; exit 1; }; fi
# A Darwin temp dir that can't be listed before the run turns the sweep off: a marker-only
# directory that appears during the run is kept, never removed.
if ! TMPDIR="$fake" TELLTALE_DARWIN_TEMP_DIR="$scratch/unlisted" "$checker" --sweep-only sh -c \
    'mkdir -p "$1/TemporaryDirectory.late" && : > "$1/TemporaryDirectory.late/.keep-directory"' sh "$scratch/unlisted" \
    > "$scratch/out.log" 2>&1; then
    echo "FAIL: an unlisted Darwin temp dir failed the run"; cat "$scratch/out.log"; exit 1
fi
grep -qF 'skipped the marker sweep' "$scratch/out.log" || { echo "FAIL: skipped sweep not reported"; cat "$scratch/out.log"; exit 1; }
[ -f "$scratch/unlisted/TemporaryDirectory.late/.keep-directory" ] || { echo "FAIL: sweep ran without a before-list"; exit 1; }

# The Makefile: `make build` and `make test` run SwiftPM with TMPDIR in a private run directory
# under the project's own .build/tmp/, which is removed with the package's lock files and honored
# TemporaryDirectory.* inside it, and the compile's Darwin marker is swept. A fake `swift` stands in.
project="$scratch/project/telltale" caller="$scratch/caller"
mkdir -p "$caller" "$project/tools" "$project/Tests/ReleaseChecks" "$scratch/bin"
project=$(cd "$project" && pwd -P)
cp "$root/Makefile" "$project/"
cp "$checker" "$project/tools/"
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
    case "$(cat "$SWIFT_LOG")" in "$project"/.build/tmp/telltale-run.*/) ;; *) echo "FAIL: make $target TMPDIR: $(cat "$SWIFT_LOG")"; exit 1 ;; esac
    [ -z "$(ls -A "$project/.build/tmp")" ] || { echo "FAIL: make $target left .build/tmp entries"; ls -A "$project/.build/tmp"; exit 1; }
    [ "$(ls -A "$DARWIN")" = TemporaryDirectory.before1 ] || { echo "FAIL: make $target left Darwin markers"; ls -A "$DARWIN"; exit 1; }
    [ -z "$(ls -A "$caller")" ] || { echo "FAIL: make $target wrote to the caller's TMPDIR"; ls -A "$caller"; exit 1; }
done
echo 'check_no_temp_leaks.sh checks passed'
