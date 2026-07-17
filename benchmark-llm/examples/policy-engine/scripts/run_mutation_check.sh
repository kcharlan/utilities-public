#!/usr/bin/env bash
set -euo pipefail

cd "$BENCH_WORKSPACE"

source .venv/bin/activate

python "$BENCH_BENCHMARK_DIR/scripts/run_mutation_check.py" \
  "$BENCH_RUN_DIR" \
  "$BENCH_WORKSPACE"
