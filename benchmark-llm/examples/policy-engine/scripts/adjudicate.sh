#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ADJUDICATOR_MODEL="${BENCH_POLICY_ENGINE_ADJUDICATOR_MODEL:-}"
ADJUDICATOR_BIN="${BENCH_POLICY_ENGINE_ADJUDICATOR_BIN:-cx}"
SUMMARY_MODE="${BENCH_FINAL_SUMMARY_MODE:-0}"

if [ "$SUMMARY_MODE" = "1" ]; then
  PROMPT_PATH="$BENCH_RUN_DIR/summary_prompt.txt"
  EVENTS_PATH="$BENCH_RUN_DIR/summary_events.jsonl"
  python "$BENCH_BENCHMARK_DIR/scripts/render_final_summary_prompt.py" \
    "$BENCH_BENCHMARK_DIR" \
    "$BENCH_SUMMARY_INPUT_PATH" \
    > "$PROMPT_PATH"

  ADJUDICATOR_ARGS=(
    exec
    --skip-git-repo-check
    -o "$BENCH_SUMMARY_REPORT_PATH"
    -
  )
else
  cd "$BENCH_WORKSPACE"
  source .venv/bin/activate

  PROMPT_PATH="$BENCH_RUN_DIR/adjudication_prompt.txt"
  EVENTS_PATH="$BENCH_RUN_DIR/adjudication_events.jsonl"
  python "$BENCH_BENCHMARK_DIR/scripts/render_adjudication_prompt.py" \
    "$BENCH_BENCHMARK_DIR" \
    "$BENCH_RUN_DIR" \
    "$BENCH_MODEL" \
    > "$PROMPT_PATH"

  ADJUDICATOR_ARGS=(
    exec
    --json
    -o "$BENCH_RUN_DIR/adjudication.json"
    -
  )
fi

if [ -n "$ADJUDICATOR_MODEL" ]; then
  ADJUDICATOR_ARGS+=(-m "$ADJUDICATOR_MODEL")
elif [ "$ADJUDICATOR_BIN" != "cx" ] && [ "$ADJUDICATOR_BIN" != "codex" ]; then
  ADJUDICATOR_ARGS+=(-m "$BENCH_MODEL")
fi

ADJUDICATOR_COMMAND=()
ADJUDICATOR_COMMAND+=("$ADJUDICATOR_BIN")
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

# Claude Code alternative via your `cc` wrapper:
# "$ADJUDICATOR_BIN" --print \
#   --model "$ADJUDICATOR_MODEL" \
#   --output-format json \
#   "$(cat "$PROMPT_PATH")" | tee "$BENCH_RUN_DIR/claude_adjudication.json"
# python "$SCRIPT_DIR/harness_metrics.py" \
#   extract-claude-metrics \
#   "$BENCH_RUN_DIR/claude_adjudication.json" \
#   > "$BENCH_COMMAND_METRICS_PATH" 2>/dev/null || true
#
zsh -lic "$ADJUDICATOR_COMMAND_STRING" < "$PROMPT_PATH" | tee "$EVENTS_PATH"

python "$SCRIPT_DIR/harness_metrics.py" \
  extract-codex-metrics \
  "$EVENTS_PATH" \
  > "$BENCH_COMMAND_METRICS_PATH" 2>/dev/null || true

if [ "$SUMMARY_MODE" != "1" ]; then
  python "$BENCH_BENCHMARK_DIR/scripts/render_report.py" \
    "$BENCH_RUN_DIR" \
    "$BENCH_BENCHMARK_DIR/report_template.md"
fi
