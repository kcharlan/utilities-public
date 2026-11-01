#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
. "$SCRIPT_DIR/../local_config.sh"

if ! load_llm_collector_env || [ -z "${API_KEY:-}" ]; then
  llm_collector_setup_hint
  exit 1
fi

mkdir -p "$LLM_COLLECTOR_DATA_DIR"
export LLM_COLLECTOR_UID="$(id -u)" LLM_COLLECTOR_GID="$(id -g)"
STACK_DIR="${PROPAGATE_STACK_ROOT:-$SCRIPT_DIR}"
STACK_DIR="${STACK_DIR:A}"
cd "$STACK_DIR"
compose=(docker compose)
if [[ -n "${PROPAGATE_STACK_ROOT:-}" ]]; then
  compose+=(-p llm_collector_container --project-directory "$SCRIPT_DIR" -f "$SCRIPT_DIR/docker-compose.yml")
  [[ ! -f "$STACK_DIR/.env" ]] || compose+=(--env-file "$STACK_DIR/.env")
fi

# Force a clean dependency refresh while retaining the moving Python 3.14
# base tag and the intentionally selected direct dependency versions.
"${compose[@]}" build --pull --no-cache
"${compose[@]}" up -d --force-recreate --wait --wait-timeout 120

curl -fsS "$COLLECTOR_URL/health" >/dev/null
curl -fsS -H "X-API-KEY: $API_KEY" "$COLLECTOR_URL/counters" >/dev/null
"${compose[@]}" ps
