#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
STACK_DIR="${PROPAGATE_STACK_ROOT:-$SCRIPT_DIR}"
STACK_DIR="${STACK_DIR:A}"
cd "$STACK_DIR"

if [[ ! -f .env ]]; then
  print -u2 -- "Missing private config: $STACK_DIR/.env"
  print -u2 -- "Copy .env.example to .env and replace every synthetic value."
  exit 2
fi

if grep -Eq "^[[:space:]]*(export[[:space:]]+)?N8N_ENCRYPTION_KEY[[:space:]]*=[[:space:]]*['\"]?SYNTHETIC_ONLY_REPLACE_WITH_A_LONG_RANDOM_VALUE['\"]?([[:space:]]*(#.*)?)?$" .env || [[ "${N8N_ENCRYPTION_KEY:-}" == SYNTHETIC_ONLY_REPLACE_WITH_A_LONG_RANDOM_VALUE ]]; then
  print -u2 -- 'Replace the example N8N_ENCRYPTION_KEY before starting.'
  exit 2
fi

chmod 600 .env
compose=(docker compose)
if [[ -n "${PROPAGATE_STACK_ROOT:-}" ]]; then
  compose+=(-p n8n-poc --project-directory "$SCRIPT_DIR" --env-file "$STACK_DIR/.env" -f "$SCRIPT_DIR/docker-compose.yml")
fi
"${compose[@]}" config --quiet
resolved_key="$("${compose[@]}" config --format json | jq -er '.services.n8n.environment.N8N_ENCRYPTION_KEY')"
if [[ "$resolved_key" == SYNTHETIC_ONLY_REPLACE_WITH_A_LONG_RANDOM_VALUE ]]; then
  print -u2 -- 'Replace the example N8N_ENCRYPTION_KEY before starting.'
  exit 2
fi
unset resolved_key
"${compose[@]}" pull
"${compose[@]}" up -d --wait --wait-timeout 180
if [[ "${1:-}" == --status ]]; then
  "${compose[@]}" ps
fi
