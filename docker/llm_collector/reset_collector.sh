#!/bin/bash
# reset_collector.sh — clears LLM counters at midnight

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/local_config.sh"

if ! load_llm_collector_env || [ -z "${API_KEY:-}" ]; then
  llm_collector_setup_hint
  exit 1
fi

BASE_DIR="$SCRIPT_DIR"
LOG_FILE="$BASE_DIR/reset_launchd.log"
ERR_FILE="$BASE_DIR/reset_launchd.err"
MAX_LOG_LINES=100

# --- Command Paths ---
CURL_CMD="/usr/bin/curl"
GREP_CMD="/usr/bin/grep"
MV_CMD="/bin/mv"
WC_CMD="/usr/bin/wc"
XARGS_CMD="/usr/bin/xargs"
SLEEP_CMD="/bin/sleep"
DATE_CMD="/bin/date"

# --- Functions ---
log_error() {
  echo "$($DATE_CMD): ERROR: $1" >> "$ERR_FILE"
}

log_info() {
  echo "$($DATE_CMD): INFO: $1" >> "$LOG_FILE"
}

rotate_log() {
  local file="$1"
  local max_lines="$2"
  if [ -f "$file" ]; then
    local lines=$($WC_CMD -l < "$file" | $XARGS_CMD)
    if [ "$lines" -ge "$max_lines" ]; then
      $MV_CMD "$file" "$file.1"
    fi
  fi
}

curl_with_api_key() {
  $CURL_CMD -fsS -H "X-API-KEY: $API_KEY" "$@"
}

wait_for_health() {
  local retries="$1"
  local backoff="$2"
  local attempt=1

  while [ "$attempt" -le "$retries" ]; do
    if $CURL_CMD -fsS "${COLLECTOR_URL}/health" > /dev/null; then
      log_info "Collector health check succeeded."
      return 0
    fi

    log_info "Collector health check failed (attempt $attempt/$retries)."
    if [ "$attempt" -lt "$retries" ]; then
      $SLEEP_CMD $((backoff * attempt))
    fi
    attempt=$((attempt + 1))
  done

  return 1
}

# --- Main Script ---

# Rotate logs
rotate_log "$LOG_FILE" "$MAX_LOG_LINES"
rotate_log "$ERR_FILE" "$MAX_LOG_LINES"

log_info "Starting reset_collector.sh script."

# Delay for system to stabilize (e.g., after waking from sleep)
$SLEEP_CMD 5

MAX_RETRIES=3
BACKOFF=3

if ! wait_for_health "$MAX_RETRIES" "$BACKOFF"; then
  log_error "Collector health check failed after $MAX_RETRIES attempts."
  exit 1
fi

log_info "Checking for active counters before reset."
if ! COUNTERS_RESPONSE="$(curl_with_api_key "${COLLECTOR_URL}/counters" 2>> "$ERR_FILE")"; then
  log_error "Failed to read counters from ${COLLECTOR_URL}/counters."
  exit 1
fi
if echo "$COUNTERS_RESPONSE" | $GREP_CMD -q '^{"counters":{}}$'; then
  log_info "No active counters found. No reset needed."
  exit 0
fi

RETRY_COUNT=0
log_info "Attempting to reset collector."
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if curl_with_api_key -X POST "${COLLECTOR_URL}/reset" >> "$LOG_FILE" 2>> "$ERR_FILE"; then
    log_info "Collector reset successfully."
    exit 0
  fi

  RETRY_COUNT=$((RETRY_COUNT + 1))
  log_info "Collector reset failed. Retrying in $((BACKOFF * RETRY_COUNT)) seconds..."
  if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
    $SLEEP_CMD $((BACKOFF * RETRY_COUNT))
  fi
done

log_error "Failed to reset collector after $MAX_RETRIES attempts."
exit 1
