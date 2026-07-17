#!/bin/zsh
# Rebuild and start the container in the background
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../local_config.sh"

if ! load_llm_collector_env || [ -z "${API_KEY:-}" ]; then
  llm_collector_setup_hint
  exit 1
fi

mkdir -p "$LLM_COLLECTOR_DATA_DIR"
docker compose build --pull
docker compose up -d
