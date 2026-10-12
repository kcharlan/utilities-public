#!/usr/bin/env bash
set -euo pipefail

cd "$BENCH_WORKSPACE"

"${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv --clear .venv
source .venv/bin/activate
python -m pip install pytest==9.1.1 PyYAML==6.0.3
if [ -f requirements.txt ]; then
  python -m pip install -r requirements.txt
fi

python "$BENCH_BENCHMARK_DIR/scripts/run_validation.py" \
  "$BENCH_RUN_DIR" \
  "$BENCH_WORKSPACE" \
  "$BENCH_HIDDEN_DIR"
