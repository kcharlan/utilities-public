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
run_profile() {
    profile=$1
    source_dir=$2
    shift 2
    /usr/bin/sandbox-exec -D "REAL_HOME=$real_home" -D "PROJECT_DIR=$source_dir" \
    -f "$profile" \
    env HOME="$test_scratch/home" COLOPHON_HOME="$test_scratch/runtime" TMPDIR="$test_scratch" \
    PLAYWRIGHT_BROWSERS_PATH="$real_home/Library/Caches/ms-playwright" \
    COLOPHON_TEST_REAL_HOME="$real_home" \
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
run_profile "$project_dir/tests/sandbox.sb" "$project_dir" "$@"
