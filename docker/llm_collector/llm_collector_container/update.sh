#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../local_config.sh"

if ! load_llm_collector_env || [ -z "${API_KEY:-}" ]; then
  llm_collector_setup_hint
  exit 1
fi

mkdir -p "$LLM_COLLECTOR_DATA_DIR"
cd "$SCRIPT_DIR"

# Force a clean dependency refresh while retaining the moving Python 3.12
# base tag and the intentionally selected direct dependency versions.
docker compose build --pull --no-cache
docker compose up -d --force-recreate --wait --wait-timeout 120

curl -fsS "$COLLECTOR_URL/health" >/dev/null
curl -fsS -H "X-API-KEY: $API_KEY" "$COLLECTOR_URL/counters" >/dev/null
docker compose ps
