#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
WRAPPER="$PROJECT_ROOT/run.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/apple-health-wrapper-test.XXXXXX")"
trap 'rm -r -- "$TEST_ROOT"' EXIT
mkdir -p "$TEST_ROOT/bin"
cat > "$TEST_ROOT/bin/uv" <<'EOF'
#!/bin/bash
printf 'cwd=%s\n' "$PWD"
printf 'arg=<%s>\n' "$@"
EOF
chmod +x "$TEST_ROOT/bin/uv"
export PATH="$TEST_ROOT/bin:$PATH"

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

make_project() {
    local project_dir="$1"
    mkdir -p "$project_dir"
    : > "$project_dir/extract_workout_stats.py"
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
printf 'cwd=%s\narg=<run>\narg=<--no-python-downloads>\narg=<--script>\narg=<%s/extract_workout_stats.py>\narg=<synthetic-argument>\n' "$configured_canonical" "$configured_canonical" > "$TEST_ROOT/expected.out"
cmp -s "$TEST_ROOT/expected.out" "$TEST_ROOT/launch.out" || fail "uv command or forwarded arguments differ"

mkdir -p "$TEST_ROOT/no-uv"
for command in dirname mkdir chmod; do ln -s "$(command -v "$command")" "$TEST_ROOT/no-uv/$command"; done
for option in launch --check; do
    if PATH="$TEST_ROOT/no-uv" APPLE_HEALTH_EXTRACT_PROJECT_DIR="$configured_project" "$standalone" ${option/launch/} > /dev/null 2> "$TEST_ROOT/no-uv.err"; then
        fail "$option succeeded without uv"
    fi
    grep -q 'brew install uv' "$TEST_ROOT/no-uv.err" || fail "$option missing uv installation guidance"
done

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
