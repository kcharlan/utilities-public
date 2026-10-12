#!/usr/bin/env bash
set -euo pipefail
cd "$BENCH_WORKSPACE"
"${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv --clear .venv
source .venv/bin/activate
python "$BENCH_BENCHMARK_DIR/scripts/run_checks.py" \
  "$BENCH_RUN_DIR" \
  "$BENCH_WORKSPACE" \
  "$BENCH_HIDDEN_DIR"
