#!/usr/bin/env bash
set -euo pipefail

cd "$BENCH_WORKSPACE"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install pytest PyYAML
if [ -f requirements.txt ]; then
  python -m pip install -r requirements.txt
fi

python "$BENCH_BENCHMARK_DIR/scripts/run_validation.py" \
  "$BENCH_RUN_DIR" \
  "$BENCH_WORKSPACE" \
  "$BENCH_HIDDEN_DIR"
