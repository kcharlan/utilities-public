#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

if [[ ! -f .env ]]; then
  print -u2 -- "Missing private config: $SCRIPT_DIR/.env"
  print -u2 -- "Copy .env.example to .env and replace every synthetic value."
  exit 2
fi

chmod 600 .env
docker compose config --quiet
docker compose pull
docker compose up -d --wait --wait-timeout 180
