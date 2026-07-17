#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Moving tags and dependency ranges are intentional. This command is the
# explicit maintenance boundary that refreshes all upstream inputs.
docker compose pull web
docker compose build --pull --no-cache index app_py app_node
docker compose up -d --force-recreate --remove-orphans --wait --wait-timeout 120

curl -fsS http://127.0.0.1:7711/api/py/hello >/dev/null
curl -fsS http://127.0.0.1:7711/api/node/hello >/dev/null
curl -fsS http://127.0.0.1:7711/configure/api/endpoints >/dev/null

docker compose ps
