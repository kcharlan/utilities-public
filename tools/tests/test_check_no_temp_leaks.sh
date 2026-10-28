#!/bin/bash
set -euo pipefail
# Proves tools/check_no_temp_leaks.sh catches a leak and sweeps only this run's empty SwiftPM
# markers, against a private fake TMPDIR and a fake Darwin user temp dir inside this script's own
# scratch, which the trap removes. The real Darwin user temp dir is never touched. Then proves that
# the brew_version and anker_charge_monitor Makefiles run their suite and harness builders inside
# it, with a fake `swift` standing in for the toolchain. Ported from
# telltale/Tests/ReleaseChecks/test_check_no_temp_leaks.sh.
repo=$(cd "$(dirname "$0")/../.." && pwd)
checker="$repo/tools/check_no_temp_leaks.sh"
scratch=$(mktemp -d "${TMPDIR:-/tmp}/no-temp-leaks-test.XXXXXX")
chmod 700 "$scratch"
trap 'rm -rf "$scratch"' EXIT
fake="$scratch/tmp"
mkdir "$fake" "$scratch/darwin"
names='(^|_)synthetic[-_]tool[-_]'
export OUTER="$fake" DARWIN="$scratch/darwin" NO_TEMP_LEAKS_DARWIN_TEMP_DIR="$scratch/darwin"
expect_pass() { if ! TMPDIR="$fake" "$checker" --names "$names" "$@" > "$scratch/out.log" 2>&1; then echo "FAIL: reported a clean run: $*"; cat "$scratch/out.log"; exit 1; fi; }
expect_leak() {
    local name=$1; shift
    if TMPDIR="$fake" "$checker" --names "$names" "$@" > "$scratch/out.log" 2>&1; then echo "FAIL: missed leak $name"; exit 1; fi
    grep -qF "  $name" "$scratch/out.log" || { echo "FAIL: leak $name not named"; cat "$scratch/out.log"; exit 1; }
}

expect_pass true
# The command runs with a private TMPDIR, removed afterwards with whatever the toolchain left.
expect_pass sh -c 'case "$TMPDIR" in "$OUTER"/no-temp-leaks-run.*) mkdir "$TMPDIR/TemporaryDirectory.AbCdEf" ;; *) exit 1 ;; esac'
[ -z "$(ls -A "$fake")" ] || { echo "FAIL: the private TMPDIR was not removed"; ls -A "$fake"; exit 1; }
# A directory created and removed within the run is not a leak; neither is another tool's entry.
expect_pass sh -c 'mkdir "$TMPDIR/synthetic-tool-transient" && rmdir "$TMPDIR/synthetic-tool-transient"'
expect_pass sh -c 'mkdir "$OUTER/other-tool.XXXX"'
# A test or script that leaves its scratch in TMPDIR, or a package build's lock file.
expect_leak synthetic-tool-tests-0001 sh -c 'mkdir "$TMPDIR/synthetic-tool-tests-0001"'
expect_leak _private_var_T_synthetic-tool-bundle.AbCdEf_project_.build.lock \
    sh -c ': > "$TMPDIR/_private_var_T_synthetic-tool-bundle.AbCdEf_project_.build.lock"'
# Something written to the real TMPDIR directly.
expect_leak synthetic-tool-snapshots.Qr34St sh -c 'mkdir "$OUTER/synthetic-tool-snapshots.Qr34St"'
# Entries from before the run are not this run's leaks.
expect_pass true
# A failing command still fails with its own status, and its leak is still named.
if TMPDIR="$fake" "$checker" --names "$names" sh -c 'mkdir "$TMPDIR/synthetic-tool-acceptance.Xy12Zw"; exit 7' > "$scratch/out.log" 2>&1; then
    echo "FAIL: a failing command passed"; exit 1
else
    [ $? -eq 7 ] || { echo "FAIL: the command's status was not passed through"; exit 1; }
fi
grep -qF '  synthetic-tool-acceptance.Xy12Zw' "$scratch/out.log" || { echo "FAIL: leak from a failing run not named"; exit 1; }
# Bad arguments: no command, a missing pattern, or the full mode without one.
for args in "" "--names|$names" "--names" "true"; do
    IFS="|" read -r -a argv <<< "$args"
    if TMPDIR="$fake" "$checker" ${argv[@]+"${argv[@]}"} > /dev/null 2>&1; then echo "FAIL: accepted arguments: $args"; exit 1; fi
done

# A SwiftPM lock named after a `.../synthetic_tool/...` package path, in the given TMPDIR or in the
# Darwin user temp dir.
expect_leak _private_var_project_synthetic_tool_.build.lock sh -c ': > "$OUTER/_private_var_project_synthetic_tool_.build.lock"'
expect_leak _Users_someone_synthetic_tool_.build_workspace-state.json.lock \
    sh -c ': > "$DARWIN/_Users_someone_synthetic_tool_.build_workspace-state.json.lock"'
rm -f "$fake"/*.lock "$DARWIN"/*.lock
# Inside the private TMPDIR, the lock files of the package being built in the working directory are
# the toolchain's own; another package's lock still is a leak.
mkdir "$scratch/synthetic_tool"
own=$(cd "$scratch/synthetic_tool" && pwd -P | tr / _)
(cd "$scratch/synthetic_tool" && expect_pass sh -c ': > "$TMPDIR$1_.build.lock"; : > "$TMPDIR$1_.build_workspace-state.json.lock"' sh "$own")
(cd "$scratch/synthetic_tool" && expect_leak _private_var_T_synthetic-tool-bundle.Zz_project_.build.lock \
    sh -c ': > "$TMPDIR/_private_var_T_synthetic-tool-bundle.Zz_project_.build.lock"')

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
if ! TMPDIR="$fake" "$checker" --sweep-only --names "$names" sh -c '[ "$TMPDIR" = "$OUTER" ] && mkdir "$OUTER/synthetic-tool-snapshots.Kept12" && bash "$1"' sh "$scratch/compile.sh" > "$scratch/out.log" 2>&1; then
    echo "FAIL: --sweep-only did not run the command with TMPDIR unchanged"; cat "$scratch/out.log"; exit 1
fi
[ -d "$fake/synthetic-tool-snapshots.Kept12" ] || { echo "FAIL: --sweep-only removed the builder's home"; exit 1; }
expect_swept
rmdir "$fake/synthetic-tool-snapshots.Kept12"
if TMPDIR="$fake" "$checker" --sweep-only sh -c 'exit 5' > /dev/null 2>&1; then echo "FAIL: --sweep-only hid a failure"; exit 1
else [ $? -eq 5 ] || { echo "FAIL: --sweep-only did not pass the status through"; exit 1; }; fi
# With --names, --sweep-only fails on a project entry that is not a directory, such as a builder's
# lock file, in TMPDIR or the Darwin user temp dir; a builder's home directory is allowed.
for dir in OUTER DARWIN; do
    if TMPDIR="$fake" "$checker" --sweep-only --names "$names" bash -c 'mkdir "$OUTER/synthetic-tool-acceptance.Home01" && : > "${!1}/_x_synthetic-tool-acceptance.Home01_package_.build.lock"' bash "$dir" \
        > "$scratch/out.log" 2>&1; then
        echo "FAIL: --sweep-only missed a lock file in $dir"; exit 1
    fi
    grep -qF '  _x_synthetic-tool-acceptance.Home01_package_.build.lock' "$scratch/out.log" || { echo "FAIL: lock file in $dir not named"; cat "$scratch/out.log"; exit 1; }
    grep -qF '  synthetic-tool-acceptance.Home01' "$scratch/out.log" && { echo "FAIL: builder home reported as a leak"; exit 1; }
    rm -rf "$fake"/* "$DARWIN"/*.lock
done
# A Darwin temp dir that can't be listed before the run turns the sweep off: a marker-only
# directory that appears during the run is kept, never removed.
if ! TMPDIR="$fake" NO_TEMP_LEAKS_DARWIN_TEMP_DIR="$scratch/unlisted" "$checker" --sweep-only sh -c \
    'mkdir -p "$1/TemporaryDirectory.late" && : > "$1/TemporaryDirectory.late/.keep-directory"' sh "$scratch/unlisted" \
    > "$scratch/out.log" 2>&1; then
    echo "FAIL: an unlisted Darwin temp dir failed the run"; cat "$scratch/out.log"; exit 1
fi
grep -qF 'skipped the marker sweep' "$scratch/out.log" || { echo "FAIL: skipped sweep not reported"; cat "$scratch/out.log"; exit 1; }
[ -f "$scratch/unlisted/TemporaryDirectory.late/.keep-directory" ] || { echo "FAIL: sweep ran without a before-list"; exit 1; }

# The Makefiles. `make test` runs SwiftPM with TMPDIR in a private run directory under the
# project's own .build/tmp/, removed with the package's lock files and honored
# TemporaryDirectory.* inside it; the harness targets keep the builder's home in the caller's
# TMPDIR and nothing else; every target sweeps the compile's Darwin marker. A fake `swift` (and
# `node`) stand in for the toolchain, and stub scripts for the suites and builders.
tree="$scratch/repo" caller="$scratch/caller"
mkdir -p "$tree/tools/tests" "$caller" "$scratch/bin"
cp "$checker" "$tree/tools/"
stub() { mkdir -p "$(dirname "$1")"; printf '#!/bin/sh\nexit 0\n' > "$1"; chmod 755 "$1"; }
stub "$tree/tools/tests/test_check_no_temp_leaks.sh"
cat > "$scratch/bin/swift" <<'SH'
#!/bin/bash
set -e
printf '%s\n' "$TMPDIR" >> "$SWIFT_LOG"
own=$(pwd -P | tr / _)
tmp="${TMPDIR%/}/"
: > "${tmp}${own}_.build.lock"
mkdir "${tmp}TemporaryDirectory.honored$$"
mkdir "$DARWIN/TemporaryDirectory.compile$$" && : > "$DARWIN/TemporaryDirectory.compile$$/.keep-directory"
SH
stub "$scratch/bin/node"
chmod 755 "$scratch/bin/swift"
# A builder that keeps a fresh home in TMPDIR and points SwiftPM inside it, as the real ones do;
# SYNTHETIC_LEAKY_BUILDER=1 makes it leave TMPDIR alone, so its lock file lands beside the home.
builder() {
    mkdir -p "$(dirname "$1")"
    cat > "$1" <<SH
#!/bin/bash
set -e
home=\$(mktemp -d "\${TMPDIR%/}/$2.XXXXXX")
mkdir "\$home/tmp"
if [ "\${SYNTHETIC_LEAKY_BUILDER:-0}" = 1 ]; then swift build; else TMPDIR="\$home/tmp/" swift build; fi
echo "Private home: \$home"
SH
    chmod 755 "$1"
}
mkdir "$tree/brew_version" "$tree/anker_charge_monitor"
cp "$repo/brew_version/Makefile" "$tree/brew_version/"
cp "$repo/anker_charge_monitor/Makefile" "$tree/anker_charge_monitor/"
mkdir -p "$tree/brew_version/Tests/ReleaseChecks"
: > "$tree/brew_version/Tests/ReleaseChecks/synthetic.test.mjs"
builder "$tree/brew_version/Tests/Snapshots/build.sh" brew-version-snapshots
builder "$tree/brew_version/Tests/Acceptance/build.sh" brew-version-acceptance
builder "$tree/brew_version/Tests/Acceptance/build-settings-prototype.sh" brew-version-acceptance
stub "$tree/anker_charge_monitor/Tests/ReleaseChecks/check_secrets_tests.sh"
stub "$tree/anker_charge_monitor/Tests/ReleaseChecks/check_bundle.sh"
builder "$tree/anker_charge_monitor/Tests/Snapshots/build.sh" prime-snapshots
export SWIFT_LOG="$scratch/swift.log"
make_target() { env -u MAKEFLAGS -u MFLAGS -u MAKELEVEL TMPDIR="$caller" PATH="$scratch/bin:$PATH" make -C "$tree/$1" --no-print-directory "$2" > "$scratch/out.log" 2>&1; }
expect_clean_darwin() {
    [ "$(ls -A "$DARWIN")" = TemporaryDirectory.before1 ] || { echo "FAIL: make $1 left Darwin markers"; ls -A "$DARWIN"; exit 1; }
}
for project in brew_version anker_charge_monitor; do
    dir=$(cd "$tree/$project" && pwd -P)
    : > "$SWIFT_LOG"
    make_target "$project" test || { echo "FAIL: $project make test"; cat "$scratch/out.log"; exit 1; }
    [ "$(wc -l < "$SWIFT_LOG" | tr -d ' ')" = 1 ] || { echo "FAIL: $project make test ran swift other than once"; exit 1; }
    case "$(cat "$SWIFT_LOG")" in "$dir"/.build/tmp/no-temp-leaks-run.*/) ;; *) echo "FAIL: $project make test TMPDIR: $(cat "$SWIFT_LOG")"; exit 1 ;; esac
    [ -z "$(ls -A "$dir/.build/tmp")" ] || { echo "FAIL: $project make test left .build/tmp entries"; ls -A "$dir/.build/tmp"; exit 1; }
    expect_clean_darwin "test in $project"
    [ -z "$(ls -A "$caller")" ] || { echo "FAIL: $project make test wrote to the caller's TMPDIR"; ls -A "$caller"; exit 1; }
done
for target in brew_version:snapshots:brew-version-snapshots brew_version:acceptance:brew-version-acceptance \
    brew_version:settings-prototype:brew-version-acceptance anker_charge_monitor:snapshots:prime-snapshots; do
    IFS=: read -r project goal home <<< "$target"
    : > "$SWIFT_LOG"
    make_target "$project" "$goal" || { echo "FAIL: $project make $goal"; cat "$scratch/out.log"; exit 1; }
    left=$(ls -A "$caller")
    case "$left" in "$home".??????) ;; *) echo "FAIL: $project make $goal left in TMPDIR: $left"; exit 1 ;; esac
    expect_clean_darwin "$goal in $project"
    rm -rf "${caller:?}/$left"
    # A builder that lets SwiftPM write to the caller's TMPDIR fails the target, naming the lock.
    if SYNTHETIC_LEAKY_BUILDER=1 make_target "$project" "$goal"; then echo "FAIL: $project make $goal missed a leaky builder"; cat "$scratch/out.log"; ls -A "$caller"; exit 1; fi
    lock="$(cd "$tree/$project" && pwd -P | tr / _)_.build.lock"
    grep -qF "  $lock" "$scratch/out.log" || { echo "FAIL: $project make $goal did not name $lock"; cat "$scratch/out.log"; exit 1; }
    rm -rf "${caller:?}"/* "${caller:?}"/.[!.]* 2>/dev/null || true
    expect_clean_darwin "$goal in $project"
done
echo 'check_no_temp_leaks.sh checks passed'
