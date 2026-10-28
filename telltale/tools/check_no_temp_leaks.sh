#!/bin/bash
# Ruling R28: a build or test run leaves nothing in TMPDIR or the Darwin user temp dir.
#
# check_no_temp_leaks.sh command [argument ...]
#   Runs the command with TMPDIR pointing at a private run directory under the given one, so the
#   Swift toolchain's own leftovers (its honored `TemporaryDirectory.*` folders and package lock
#   files) go with it, and removes that directory afterwards. Before removing it, fails if the run
#   left a Telltale entry inside it; afterwards fails if the run added one to the given TMPDIR or
#   to the Darwin user temp dir directly. A Telltale entry is a name starting `telltale-` or
#   `telltale_`, or containing `_telltale-` or `_telltale_`, such as a SwiftPM lock file named
#   after a Telltale package path (`..._T_telltale-bundle.XXXXXX_project_.build.lock`,
#   `..._worktrees_telltale_telltale_.build.lock`). Inside the run directory, the lock files of the
#   package in the working directory are the toolchain's own and are not reported.
#
# check_no_temp_leaks.sh --sweep-only command [argument ...]
#   Runs the command with the environment unchanged, for builders that keep a home in TMPDIR on
#   purpose, and only does the marker sweep below.
#
# Both modes: each compile puts one `TemporaryDirectory.*` in the Darwin user temp dir
# (`getconf DARWIN_USER_TEMP_DIR`) whatever TMPDIR says. The checker lists those before the run
# and afterwards removes only new ones whose sole content is an empty `.keep-directory`, by
# removing that file and then `rmdir`, so a directory that existed before the run, or one with any
# other content, is never touched. It reports how many it removed and names any new one it left.
# TELLTALE_DARWIN_TEMP_DIR replaces the Darwin user temp dir (the self-test uses a fake one).
#
# Entries that existed before the run are not reported, and the command's own failure is passed
# through. The Makefile wraps build, release and the whole test suite in it, and the snapshot and
# acceptance builders in --sweep-only; Tests/ReleaseChecks/test_check_no_temp_leaks.sh proves it.
set -uo pipefail
sweep_only=0
if [ "${1:-}" = --sweep-only ]; then sweep_only=1; shift; fi
if [ $# -eq 0 ]; then
    echo "usage: check_no_temp_leaks.sh [--sweep-only] command [argument ...]" >&2
    exit 2
fi
real="${TMPDIR:-/tmp}"
real="${real%/}"
darwin="${TELLTALE_DARWIN_TEMP_DIR:-$(getconf DARWIN_USER_TEMP_DIR)}"
darwin="${darwin%/}"
entries() { ls -A "$1" 2>/dev/null | grep -E '(^|_)telltale[-_]' | LC_ALL=C sort; return 0; }
markers() {
    local list
    list=$(ls -A "$darwin" 2>/dev/null) || return 1
    printf '%s\n' "$list" | grep -E '^TemporaryDirectory\.' | LC_ALL=C sort
    return 0
}
added() { LC_ALL=C comm -13 <(printf '%s\n' "$1") <(printf '%s\n' "$2") | sed '/^$/d'; }
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
# Without a before-list every marker would look new, so a failed listing turns the sweep off.
markers_listed=1
markers_before=$(markers) || markers_listed=0
if [ "$sweep_only" -eq 1 ]; then
    "$@"
    status=$?
    sweep
    exit "$status"
fi
before=$(entries "$real")
darwin_before=$(entries "$darwin")
run=$(mktemp -d "$real/telltale-run.XXXXXX") || exit 1
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
report() {
    [ -n "$2" ] || return 0
    echo "check_no_temp_leaks: this run left these entries in $1:" >&2
    printf '%s\n' "$2" | sed 's/^/  /' >&2
    [ "$status" -ne 0 ] || status=1
}
sweep
report "its private TMPDIR" "$inside"
report "$real" "$outside"
report "$darwin" "$darwin_outside"
exit "$status"
