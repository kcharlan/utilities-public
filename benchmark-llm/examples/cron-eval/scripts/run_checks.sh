#!/usr/bin/env bash
set -euo pipefail
cd "$BENCH_WORKSPACE"
# Rebuild from the stable base. rm removes a .venv symlink without following it;
# the venv module's clear option would empty the symlink's target instead.
: "${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}"
rm -rf -- .venv
"$BENCH_BASE_PYTHON" -m venv .venv
source .venv/bin/activate
python "$BENCH_BENCHMARK_DIR/scripts/run_checks.py" \
  "$BENCH_RUN_DIR" \
  "$BENCH_WORKSPACE" \
  "$BENCH_HIDDEN_DIR"
