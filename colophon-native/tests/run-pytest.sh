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
/usr/bin/sandbox-exec -D "REAL_HOME=$real_home" -D "PROJECT_DIR=$project_dir" \
    -f "$project_dir/tests/sandbox.sb" \
    env HOME="$test_scratch/home" COLOPHON_HOME="$test_scratch/runtime" TMPDIR="$test_scratch" \
    PLAYWRIGHT_BROWSERS_PATH="$real_home/Library/Caches/ms-playwright" \
    PYTHONDONTWRITEBYTECODE=1 COLOPHON_PRICING_URL=http://127.0.0.1:9/catalog.json \
    "$project_dir/.venv/bin/python" -B -m pytest --basetemp "$test_scratch/cases" "$@"
