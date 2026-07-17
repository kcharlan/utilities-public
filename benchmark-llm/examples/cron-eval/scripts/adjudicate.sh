#!/usr/bin/env bash
set -euo pipefail

# Use a different adjudicator binary:
#   BENCH_CRON_EVAL_ADJUDICATOR_BIN=cc bench run examples/cron-eval ...
#
# Pin a specific model:
#   BENCH_CRON_EVAL_ADJUDICATOR_MODEL=openrouter/anthropic/claude-opus-4-7 bench run ...
#
# Switch to higher-reasoning mode:
#   BENCH_CRON_EVAL_ADJUDICATOR_ARGS='--reasoning-effort high' bench run ...

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ADJUDICATOR_MODEL="${BENCH_CRON_EVAL_ADJUDICATOR_MODEL:-}"
ADJUDICATOR_BIN="${BENCH_CRON_EVAL_ADJUDICATOR_BIN:-cx}"
EXTRA_ARGS="${BENCH_CRON_EVAL_ADJUDICATOR_ARGS:-}"
SUMMARY_MODE="${BENCH_FINAL_SUMMARY_MODE:-0}"

if [ "$SUMMARY_MODE" = "1" ]; then
  PROMPT_PATH="$BENCH_RUN_DIR/summary_prompt.txt"
  EVENTS_PATH="$BENCH_RUN_DIR/summary_events.jsonl"
  python "$BENCH_BENCHMARK_DIR/scripts/render_final_summary_prompt.py" \
    "$BENCH_BENCHMARK_DIR" \
    "$BENCH_SUMMARY_INPUT_PATH" \
    > "$PROMPT_PATH"
  ADJUDICATOR_ARGS=(exec --skip-git-repo-check -o "$BENCH_SUMMARY_REPORT_PATH" -)
else
  cd "$BENCH_WORKSPACE"
  source .venv/bin/activate
  PROMPT_PATH="$BENCH_RUN_DIR/adjudication_prompt.txt"
  EVENTS_PATH="$BENCH_RUN_DIR/adjudication_events.jsonl"
  python "$BENCH_BENCHMARK_DIR/scripts/render_adjudication_prompt.py" \
    "$BENCH_BENCHMARK_DIR" \
    "$BENCH_RUN_DIR" \
    "$BENCH_WORKSPACE" \
    "$BENCH_MODEL" \
    > "$PROMPT_PATH"
  ADJUDICATOR_ARGS=(exec -)
fi

if [ -n "$ADJUDICATOR_MODEL" ]; then
  ADJUDICATOR_ARGS+=(-m "$ADJUDICATOR_MODEL")
elif [ "$ADJUDICATOR_BIN" != "cx" ] && [ "$ADJUDICATOR_BIN" != "codex" ]; then
  ADJUDICATOR_ARGS+=(-m "$BENCH_MODEL")
fi

if [ -n "$EXTRA_ARGS" ]; then
  # shellcheck disable=SC2206
  EXTRA_ARRAY=($EXTRA_ARGS)
  ADJUDICATOR_ARGS+=("${EXTRA_ARRAY[@]}")
fi

ADJUDICATOR_COMMAND=("$ADJUDICATOR_BIN")
for arg in "${ADJUDICATOR_ARGS[@]}"; do
  ADJUDICATOR_COMMAND+=("$arg")
done

ADJUDICATOR_COMMAND_STRING=""
for arg in "${ADJUDICATOR_COMMAND[@]}"; do
  if [ -n "$ADJUDICATOR_COMMAND_STRING" ]; then
    ADJUDICATOR_COMMAND_STRING+=" "
  fi
  ADJUDICATOR_COMMAND_STRING+="$(printf '%q' "$arg")"
done

if ! zsh -lic "$ADJUDICATOR_COMMAND_STRING" < "$PROMPT_PATH" > "$BENCH_RUN_DIR/report.md" 2> "$BENCH_RUN_DIR/adjudication.stderr.log"; then
  python "$BENCH_BENCHMARK_DIR/scripts/render_report.py" "$BENCH_RUN_DIR" "${BENCH_MODEL:-}"
elif [ ! -s "$BENCH_RUN_DIR/report.md" ]; then
  python "$BENCH_BENCHMARK_DIR/scripts/render_report.py" "$BENCH_RUN_DIR" "${BENCH_MODEL:-}"
fi

python "$SCRIPT_DIR/harness_metrics.py" \
  extract-codex-metrics \
  "$BENCH_RUN_DIR/report.md" \
  > "$BENCH_COMMAND_METRICS_PATH" 2>/dev/null || true
