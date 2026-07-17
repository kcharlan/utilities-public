#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
WRAPPER="$PROJECT_ROOT/run.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/apple-health-wrapper-test.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

make_project() {
    local project_dir="$1"
    mkdir -p "$project_dir/venv/bin"
    : > "$project_dir/extract_workout_stats.py"
    printf '#!/bin/bash\nprintf "cwd=%%s\\n" "$PWD"\nprintf "args=%%s\\n" "$*"\n' \
        > "$project_dir/venv/bin/python"
    chmod +x "$project_dir/venv/bin/python"
}

help_home="$TEST_ROOT/help-home"
HOME="$help_home" "$WRAPPER" --help > "$TEST_ROOT/help.out"
grep -q 'APPLE_HEALTH_EXTRACT_PROJECT_DIR' "$TEST_ROOT/help.out" || fail "help omits environment override"
[[ ! -e "$help_home/.apple-health-extract" ]] || fail "help created runtime state"

colocated="$TEST_ROOT/colocated project"
make_project "$colocated"
cp "$WRAPPER" "$colocated/run.sh"
"$colocated/run.sh" --check > "$TEST_ROOT/colocated.out"
colocated_canonical="$(cd "$colocated" && pwd -P)"
grep -Fq "$colocated_canonical" "$TEST_ROOT/colocated.out" || fail "colocated fallback did not resolve"

standalone="$TEST_ROOT/Library/Scripts/run-health"
configured_project="$TEST_ROOT/configured health project"
runtime_home="$TEST_ROOT/runtime home"
mkdir -p "$(dirname "$standalone")" "$runtime_home"
make_project "$configured_project"
configured_canonical="$(cd "$configured_project" && pwd -P)"
cp "$WRAPPER" "$standalone"
printf '%s\n' "$configured_project" > "$runtime_home/project-dir"
APPLE_HEALTH_EXTRACT_HOME="$runtime_home" "$standalone" --check > "$TEST_ROOT/standalone.out"
grep -Fq "$configured_canonical" "$TEST_ROOT/standalone.out" || fail "copied wrapper did not use local config"
[[ "$(stat -f '%OLp' "$runtime_home")" == "700" ]] || fail "runtime directory was not secured"
[[ "$(stat -f '%OLp' "$runtime_home/project-dir")" == "600" ]] || fail "project-dir config was not secured"

env -u HOME APPLE_HEALTH_EXTRACT_PROJECT_DIR="$configured_project" \
    "$standalone" --check > "$TEST_ROOT/environment.out"
grep -Fq "$configured_canonical" "$TEST_ROOT/environment.out" || fail "environment override unnecessarily required HOME"

APPLE_HEALTH_EXTRACT_HOME="$runtime_home" "$standalone" synthetic-argument > "$TEST_ROOT/launch.out"
grep -Fq "cwd=$configured_canonical" "$TEST_ROOT/launch.out" || fail "launcher did not use project working directory"
grep -Fq 'args=' "$TEST_ROOT/launch.out" || fail "launcher did not invoke project interpreter"
grep -Fq 'synthetic-argument' "$TEST_ROOT/launch.out" || fail "launcher did not forward arguments"

unsafe_home="$TEST_ROOT/unsafe-home"
marker="$TEST_ROOT/SHOULD_NOT_EXIST"
mkdir -p "$unsafe_home"
printf '%s\n%s\n' "$configured_project" "\$(touch $marker)" > "$unsafe_home/project-dir"
if APPLE_HEALTH_EXTRACT_HOME="$unsafe_home" "$standalone" --check > /dev/null 2> "$TEST_ROOT/unsafe.err"; then
    fail "multi-line config was accepted"
fi
[[ ! -e "$marker" ]] || fail "config content was executed"
grep -q 'exactly one line' "$TEST_ROOT/unsafe.err" || fail "unsafe config error was not actionable"

first_home="$TEST_ROOT/first-home"
if HOME="$first_home" "$standalone" --check > /dev/null 2> "$TEST_ROOT/first.err"; then
    fail "unconfigured copied wrapper unexpectedly succeeded"
fi
[[ -f "$first_home/.apple-health-extract/project-dir" ]] || fail "first run did not create empty config"
[[ ! -s "$first_home/.apple-health-extract/project-dir" ]] || fail "first-run config was not empty"
grep -q 'created empty local config' "$TEST_ROOT/first.err" || fail "first-run error was not actionable"

printf 'apple-health-extract wrapper tests: PASS\n'
