#!/usr/bin/env bash
set -euo pipefail

test -n "${BENCH_WORKSPACE:-}"
test -f "${BENCH_BENCHMARK_DIR}/prompt.txt"

cd "$BENCH_WORKSPACE"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
git status --short
