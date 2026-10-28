#!/bin/bash
# A build or test run leaves nothing in TMPDIR or the Darwin user temp dir. Shared by the
# brew_version and anker_charge_monitor Makefiles; generalized from
# telltale/tools/check_no_temp_leaks.sh, which Telltale's release path still needs in its own tree.
#
# check_no_temp_leaks.sh --names ERE command [argument ...]
#   Runs the command with TMPDIR pointing at a private run directory under the given one, so the
#   Swift toolchain's own leftovers (its honored `TemporaryDirectory.*` folders and package lock
#   files) go with it, and removes that directory afterwards. Before removing it, fails if the run
#   left a project entry inside it; afterwards fails if the run added one to the given TMPDIR or to
#   the Darwin user temp dir directly. A project entry is a name the extended regular expression
#   ERE matches, such as `(^|_)brew[-_]version[-_]`: a test's `brew-version-*` scratch, or a
#   SwiftPM lock file named after a package path (`..._T_brew-version-acceptance.XXXXXX_package_
#   .build.lock`). Inside the run directory, the lock files of the package in the working directory
#   are the toolchain's own and are not reported.
#
# check_no_temp_leaks.sh --sweep-only [--names ERE] command [argument ...]
#   Runs the command with the environment unchanged, for builders that keep a home in TMPDIR on
#   purpose, and does the marker sweep below. With --names it also fails if the run added a project
#   entry other than a directory (a builder's home) to TMPDIR or the Darwin user temp dir, such as a
#   SwiftPM lock file from a builder that left TMPDIR pointing outside its home.
#
# Both modes: each compile puts one `TemporaryDirectory.*` in the Darwin user temp dir
# (`getconf DARWIN_USER_TEMP_DIR`) whatever TMPDIR says. The checker lists those before the run
# and afterwards removes only new ones whose sole content is an empty `.keep-directory`, by
# removing that file and then `rmdir`, so a directory that existed before the run, or one with any
# other content, is never touched. It reports how many it removed and names any new one it left,
# without failing: another process may own it. NO_TEMP_LEAKS_DARWIN_TEMP_DIR replaces the Darwin
# user temp dir (the self-test uses a fake one).
#
# Entries that existed before the run are not reported, and the command's own failure is passed
# through. tools/tests/test_check_no_temp_leaks.sh proves it and both Makefiles' wiring.
set -uo pipefail
usage() { echo "usage: check_no_temp_leaks.sh [--sweep-only] --names ERE command [argument ...]" >&2; exit 2; }
sweep_only=0 names=""
while [ $# -gt 0 ]; do
    case "$1" in
        --sweep-only) sweep_only=1; shift ;;
        --names) [ $# -ge 2 ] && [ -n "$2" ] || usage; names=$2; shift 2 ;;
        *) break ;;
    esac
done
[ $# -gt 0 ] || usage
[ "$sweep_only" -eq 1 ] || [ -n "$names" ] || usage
real="${TMPDIR:-/tmp}"
real="${real%/}"
darwin="${NO_TEMP_LEAKS_DARWIN_TEMP_DIR:-$(getconf DARWIN_USER_TEMP_DIR)}"
darwin="${darwin%/}"
entries() { [ -n "$names" ] || return 0; ls -A "$1" 2>/dev/null | grep -E -e "$names" | LC_ALL=C sort; return 0; }
markers() {
    local list
    list=$(ls -A "$darwin" 2>/dev/null) || return 1
    printf '%s\n' "$list" | grep -E '^TemporaryDirectory\.' | LC_ALL=C sort
    return 0
}
added() { LC_ALL=C comm -13 <(printf '%s\n' "$1") <(printf '%s\n' "$2") | sed '/^$/d'; }
# The added entries of directory $1 that are not directories themselves.
not_directories() {
    local name
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        if [ ! -d "$1/$name" ] || [ -L "$1/$name" ]; then printf '%s\n' "$name"; fi
    done <<< "$2"
}
# A directory holding nothing but an empty, regular `.keep-directory`.
marker_only() {
    [ -d "$1" ] && [ ! -L "$1" ] && [ "$(ls -A "$1" 2>/dev/null)" = .keep-directory ] &&
        [ -f "$1/.keep-directory" ] && [ ! -L "$1/.keep-directory" ] && [ ! -s "$1/.keep-directory" ]
}
sweep() {
    local name removed=0 kept=()
    if [ "$markers_listed" -eq 0 ]; then
        echo "check_no_temp_leaks: skipped the marker sweep: couldn't list $darwin before the run" >&2
        return 0
    fi
    while IFS= read -r name; do
        if marker_only "$darwin/$name" && rm -- "$darwin/$name/.keep-directory" && rmdir -- "$darwin/$name"; then
            removed=$((removed + 1))
        else
            kept+=("$name")
        fi
    done < <(added "$markers_before" "$(markers)")
    echo "check_no_temp_leaks: removed $removed empty TemporaryDirectory.* marker(s) from $darwin" >&2
    if [ ${#kept[@]} -gt 0 ]; then
        echo "check_no_temp_leaks: left ${#kept[@]} new TemporaryDirectory.* with other content in $darwin:" >&2
        printf '  %s\n' "${kept[@]}" >&2
    fi
}
report() {
    [ -n "$2" ] || return 0
    echo "check_no_temp_leaks: this run left these entries in $1:" >&2
    printf '%s\n' "$2" | sed 's/^/  /' >&2
    [ "$status" -ne 0 ] || status=1
}
# Without a before-list every marker would look new, so a failed listing turns the sweep off.
markers_listed=1
markers_before=$(markers) || markers_listed=0
before=$(entries "$real")
darwin_before=""
[ "$darwin" = "$real" ] || darwin_before=$(entries "$darwin")
if [ "$sweep_only" -eq 1 ]; then
    "$@"
    status=$?
    sweep
    report "$real" "$(not_directories "$real" "$(added "$before" "$(entries "$real")")")"
    [ "$darwin" = "$real" ] ||
        report "$darwin" "$(not_directories "$darwin" "$(added "$darwin_before" "$(entries "$darwin")")")"
    exit "$status"
fi
run=$(mktemp -d "$real/no-temp-leaks-run.XXXXXX") || exit 1
chmod 700 "$run"
trap 'rm -rf "$run"' EXIT
TMPDIR="$run/" "$@"
status=$?
# SwiftPM names a package's lock files after its .build path, slashes turned into underscores.
own=$(pwd -P | tr / _)
inside=$(entries "$run" | grep -v -F -x -e "${own}_.build.lock" -e "${own}_.build_workspace-state.json.lock")
rm -rf "$run"
trap - EXIT
outside=$(added "$before" "$(entries "$real")")
darwin_outside=""
[ "$darwin" = "$real" ] || darwin_outside=$(added "$darwin_before" "$(entries "$darwin")")
sweep
report "its private TMPDIR" "$inside"
report "$real" "$outside"
report "$darwin" "$darwin_outside"
exit "$status"
