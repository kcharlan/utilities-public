#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
STACK_DIR="${PROPAGATE_STACK_ROOT:-$SCRIPT_DIR}"
STACK_DIR="${STACK_DIR:A}"
cd "$STACK_DIR"
compose=(docker compose)
if [[ -n "${PROPAGATE_STACK_ROOT:-}" ]]; then
  compose+=(-p excalidraw --project-directory "$SCRIPT_DIR" -f "$SCRIPT_DIR/docker-compose.yml")
  [[ ! -f "$STACK_DIR/.env" ]] || compose+=(--env-file "$STACK_DIR/.env")
fi

"${compose[@]}" pull excalidraw
"${compose[@]}" up -d --force-recreate --wait --wait-timeout 120
"${compose[@]}" ps
