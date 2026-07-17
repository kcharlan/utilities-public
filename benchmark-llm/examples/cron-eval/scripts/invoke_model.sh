#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL_ID}"
PROMPT="$(cat "$TASK_PROMPT_PATH")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP_ROOT="${TMPDIR:-/tmp}"
TMP_ROOT="${TMP_ROOT%/}"
EVENTS_BASE="$(mktemp "${TMP_ROOT}/opencode-events.XXXXXX")"
EXPORT_BASE="$(mktemp "${TMP_ROOT}/opencode-export.XXXXXX")"
EVENTS_PATH="${EVENTS_BASE}.jsonl"
EXPORT_PATH="${EXPORT_BASE}.json"
mv "$EVENTS_BASE" "$EVENTS_PATH"
mv "$EXPORT_BASE" "$EXPORT_PATH"
trap 'rm -f "$EVENTS_PATH" "$EXPORT_PATH"' EXIT

cd "$WORKSPACE_ROOT"

opencode run \
  --format json \
  --model "$MODEL" \
  --title "cron-eval" \
  "$PROMPT" | tee "$EVENTS_PATH"

SESSION_ID="$(
  python "$SCRIPT_DIR/harness_metrics.py" opencode-session-id "$EVENTS_PATH" \
    2>/dev/null || true
)"

if [ -n "$SESSION_ID" ]; then
  opencode export "$SESSION_ID" > "$EXPORT_PATH" 2>/dev/null || true
fi

python "$SCRIPT_DIR/harness_metrics.py" \
  extract-opencode-metrics \
  "$EVENTS_PATH" \
  "$EXPORT_PATH" \
  > "$TASK_METRICS_PATH" 2>/dev/null || true
