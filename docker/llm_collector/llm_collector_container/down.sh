#!/bin/zsh
# Stop and remove the container
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../local_config.sh"

if ! load_llm_collector_env || [ -z "${API_KEY:-}" ]; then
  llm_collector_setup_hint
  exit 1
fi

docker compose down
