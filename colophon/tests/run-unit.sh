#!/bin/sh
set -eu
real_home=$1
unit_binary=$2
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
unit_scratch=$(mktemp -d /tmp/colophon-native-unit.XXXXXX)
trap 'unit_status=$?; rm -r -- "$unit_scratch"; exit "$unit_status"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p /private/tmp/colophon-native-canary "$unit_scratch/home" "$unit_scratch/runtime"
unset CLAUDE_CONFIG_DIR
/usr/bin/sandbox-exec -D "REAL_HOME=$real_home" -D "PROJECT_DIR=$project_dir" \
    -f "$project_dir/tests/sandbox.sb" \
    env HOME="$unit_scratch/home" COLOPHON_HOME="$unit_scratch/runtime" TMPDIR="$unit_scratch" \
    COLOPHON_PRICING_URL=http://127.0.0.1:9/catalog.json "$unit_binary"
