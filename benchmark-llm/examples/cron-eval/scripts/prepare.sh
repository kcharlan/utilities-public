#!/usr/bin/env bash
set -euo pipefail

test -n "${BENCH_WORKSPACE:-}"
test -f "${BENCH_BENCHMARK_DIR}/prompt.txt"

cd "$BENCH_WORKSPACE"
if [ ! -d .venv ]; then
  "${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv .venv
fi
git status --short
