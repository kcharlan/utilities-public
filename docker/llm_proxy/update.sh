#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
STACK_DIR="${PROPAGATE_STACK_ROOT:-$SCRIPT_DIR}"
STACK_DIR="$(cd "$STACK_DIR" && pwd -P)"
cd "$STACK_DIR"
compose=(docker compose)
if [[ -n "${PROPAGATE_STACK_ROOT:-}" ]]; then
  export PROPAGATE_PROXY_OUTPUT_DIR="$STACK_DIR/output"
  compose+=(-p llm_proxy --project-directory "$SCRIPT_DIR" -f "$SCRIPT_DIR/docker-compose.yml" -f "$SCRIPT_DIR/compose.propagate.yml")
  [[ ! -f "$STACK_DIR/.env" ]] || compose+=(--env-file "$STACK_DIR/.env")
fi

# Refresh the moving Python and uv bases while installing the checked-in frozen lock.
"${compose[@]}" build --pull --no-cache
"${compose[@]}" up -d --force-recreate --wait --wait-timeout 120
curl -fsS http://127.0.0.1:4141/health >/dev/null
"${compose[@]}" ps
