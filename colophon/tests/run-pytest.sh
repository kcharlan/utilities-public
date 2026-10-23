#!/bin/sh
set -eu
real_home=$1
shift
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
test_scratch=$(mktemp -d /tmp/colophon-native-pytest.XXXXXX)
trap 'test_status=$?; rm -r -- "$test_scratch"; exit "$test_status"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir "$test_scratch/home" "$test_scratch/runtime"
unset CLAUDE_CONFIG_DIR OPENCODE_DB XDG_DATA_HOME ANTIGRAVITY_GEMINI_DIR ANTIGRAVITY_APP_DATA_DIR JETSKI_APP_DATA_DIR
run_profile() {
    profile=$1
    source_dir=$2
    shift 2
    policy_home=${COLOPHON_TEST_POLICY_HOME:-$real_home}
    /usr/bin/sandbox-exec -D "REAL_HOME=$policy_home" -D "PROJECT_DIR=$source_dir" \
    -f "$profile" \
    env HOME="$test_scratch/home" COLOPHON_HOME="$test_scratch/runtime" TMPDIR="$test_scratch" \
    PLAYWRIGHT_BROWSERS_PATH="$real_home/Library/Caches/ms-playwright" \
    COLOPHON_TEST_REAL_HOME="$policy_home" \
    PYTHONDONTWRITEBYTECODE=1 COLOPHON_PRICING_URL=http://127.0.0.1:9/catalog.json \
    "$project_dir/.venv/bin/python" -B -m pytest --basetemp "$test_scratch/cases" "$@"
}
# Evaluate source protection under allowlisted scratch without writing canaries.
# Separate invocations preserve the sandbox; macOS rejects nested sandbox_apply.
export COLOPHON_TEST_SOURCE_PROBE="$test_scratch/synthetic-project"
mkdir "$COLOPHON_TEST_SOURCE_PROBE"
COLOPHON_TEST_SOURCE_PROBE=$(CDPATH= cd -- "$COLOPHON_TEST_SOURCE_PROBE" && pwd -P)
run_profile "$project_dir/tests/sandbox.sb" "$COLOPHON_TEST_SOURCE_PROBE" \
    tests/test_cli.py -k sandbox_source_write_denied -p no:cacheprovider
sed '/^    (subpath (param "PROJECT_DIR"))$/d' "$project_dir/tests/sandbox.sb" \
    > "$test_scratch/synthetic-unprotected-source.sb"
if run_profile "$test_scratch/synthetic-unprotected-source.sb" "$COLOPHON_TEST_SOURCE_PROBE" \
    tests/test_cli.py -k sandbox_source_write_denied -p no:cacheprovider \
    > "$test_scratch/mutation.log" 2>&1; then
    echo 'Source protection mutation unexpectedly passed' >&2
    exit 1
fi
if ! rg -q 'AssertionError: PROJECT_DIR write protection missing' "$test_scratch/mutation.log"; then
    cat "$test_scratch/mutation.log" >&2
    exit 1
fi
echo 'Source protection mutation rejected as expected'
unset COLOPHON_TEST_SOURCE_PROBE
export COLOPHON_TEST_POLICY_HOME="$test_scratch/synthetic-claude-policy-home"
mkdir "$COLOPHON_TEST_POLICY_HOME"
COLOPHON_TEST_POLICY_HOME=$(CDPATH= cd -- "$COLOPHON_TEST_POLICY_HOME" && pwd -P)
for target in '.claude' '.config/claude' 'Library/Application Support/Claude' '.claude-swap-backup'; do
    export COLOPHON_TEST_POLICY_TARGET="$target"
    mkdir -p "$COLOPHON_TEST_POLICY_HOME/$target"
    run_profile "$project_dir/tests/sandbox.sb" "$project_dir" \
        tests/test_cli.py -k sandbox_claude_paths_denied -p no:cacheprovider
    awk -v target="/$target" 'index($0, "\"" target "\"" ) == 0' "$project_dir/tests/sandbox.sb" \
        > "$test_scratch/synthetic-unprotected-claude.sb"
    if run_profile "$test_scratch/synthetic-unprotected-claude.sb" "$project_dir" \
        tests/test_cli.py -k sandbox_claude_paths_denied -p no:cacheprovider \
        > "$test_scratch/claude-mutation.log" 2>&1; then
        echo "Claude protection mutation unexpectedly passed: $target" >&2
        exit 1
    fi
    if ! rg -q 'AssertionError: Claude source protection missing' "$test_scratch/claude-mutation.log"; then
        cat "$test_scratch/claude-mutation.log" >&2
        exit 1
    fi
    echo "Claude protection mutation rejected as expected: $target"
done
export COLOPHON_TEST_POLICY_HOME="$test_scratch/synthetic-opencode-policy-home"
mkdir "$COLOPHON_TEST_POLICY_HOME"
COLOPHON_TEST_POLICY_HOME=$(CDPATH= cd -- "$COLOPHON_TEST_POLICY_HOME" && pwd -P)
for target in '.local/share/opencode' '.local/state/opencode' '.config/opencode' '.cache/opencode' 'Library/Application Support/ai.opencode.desktop'; do
    export COLOPHON_TEST_POLICY_TARGET="$target"
    mkdir -p "$COLOPHON_TEST_POLICY_HOME/$target"
    run_profile "$project_dir/tests/sandbox.sb" "$project_dir" \
        tests/test_opencode.py -k sandbox_opencode_paths_denied -p no:cacheprovider
    awk -v target="/$target" 'index($0, "\"" target "\"" ) == 0' "$project_dir/tests/sandbox.sb" \
        > "$test_scratch/synthetic-unprotected-opencode.sb"
    if run_profile "$test_scratch/synthetic-unprotected-opencode.sb" "$project_dir" \
        tests/test_opencode.py -k sandbox_opencode_paths_denied -p no:cacheprovider \
        > "$test_scratch/opencode-mutation.log" 2>&1; then
        echo "OpenCode protection mutation unexpectedly passed: $target" >&2
        exit 1
    fi
    if ! rg -q 'AssertionError: OpenCode source protection missing' "$test_scratch/opencode-mutation.log"; then
        cat "$test_scratch/opencode-mutation.log" >&2
        exit 1
    fi
    echo "OpenCode protection mutation rejected as expected: $target"
done
unset COLOPHON_TEST_POLICY_HOME COLOPHON_TEST_POLICY_TARGET
export COLOPHON_TEST_POLICY_HOME="$test_scratch/synthetic-antigravity-policy-home"
mkdir -p "$COLOPHON_TEST_POLICY_HOME/.gemini"
COLOPHON_TEST_POLICY_HOME=$(CDPATH= cd -- "$COLOPHON_TEST_POLICY_HOME" && pwd -P)
run_profile "$project_dir/tests/sandbox.sb" "$project_dir" \
    tests/test_antigravity.py -k sandbox_antigravity_paths_denied -p no:cacheprovider
awk 'index($0, "\"/.gemini\"") == 0' "$project_dir/tests/sandbox.sb" \
    > "$test_scratch/synthetic-unprotected-antigravity.sb"
if run_profile "$test_scratch/synthetic-unprotected-antigravity.sb" "$project_dir" \
    tests/test_antigravity.py -k sandbox_antigravity_paths_denied -p no:cacheprovider \
    > "$test_scratch/antigravity-mutation.log" 2>&1; then
    echo 'Antigravity protection mutation unexpectedly passed' >&2
    exit 1
fi
if ! rg -q 'AssertionError: Antigravity source protection missing' "$test_scratch/antigravity-mutation.log"; then
    cat "$test_scratch/antigravity-mutation.log" >&2
    exit 1
fi
echo 'Antigravity protection mutation rejected as expected: .gemini'
unset COLOPHON_TEST_POLICY_HOME
run_profile "$project_dir/tests/sandbox.sb" "$project_dir" "$@"
